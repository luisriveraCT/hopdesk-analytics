# -*- coding: utf-8 -*-
"""
===============================================================================
 PRUEBAS DE LA CAPA DE CONFIGURACIÓN
===============================================================================
Cada prueba de aquí corresponde a un hallazgo concreto de la auditoría al
sistema anterior. No son pruebas genéricas de "que no truene": son la evidencia
de que un problema conocido no se reprodujo.

    python test_configuracion.py
===============================================================================
"""
import os
import sys
import shutil
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

from modelo import Empresa, Cliente, ConexionERP, Retencion, ErrorConfiguracion  # noqa
from almacen import AlmacenLocal, ConflictoDeEscritura, actualizar_con_reintento  # noqa
from secretos import AlmacenSecretos, SecretoNoDisponible                         # noqa
import repositorio as repo                                                        # noqa

_fallos = []


def check(nombre, condicion, detalle=''):
    print(f"  {'ok  ' if condicion else 'FALLA'}  {nombre}"
          + (f'   {detalle}' if detalle and not condicion else ''))
    if not condicion:
        _fallos.append(nombre)


def seccion(t):
    print(f'\n--- {t} ---')


# ---------------------------------------------------------------------------
seccion('Validación: un dato inválido NO se guarda en silencio')
# En el sistema anterior se podía crear un usuario con nombre vacío porque el
# generador hacía gsub sobre el display_name y, si eran puros símbolos, quedaba
# "" y se guardaba sin protestar.
try:
    Empresa(iniciales='', nombre='X')
    check('iniciales vacías se rechazan', False)
except ErrorConfiguracion:
    check('iniciales vacías se rechazan', True)

try:
    Empresa(iniciales='NG', nombre='')
    check('nombre vacío se rechaza', False)
except ErrorConfiguracion:
    check('nombre vacío se rechaza', True)

try:
    Empresa(iniciales='NG', nombre='Networks', rfc='ESTO-NO-ES-RFC')
    check('RFC mal formado se rechaza', False)
except ErrorConfiguracion:
    check('RFC mal formado se rechaza', True)

check('RFC válido se acepta',
      Empresa(iniciales='NCS', nombre='Networks Crossdocking',
              rfc='NCS040623CU8').rfc == 'NCS040623CU8')
check('RFC opcional: sin RFC se acepta',
      Empresa(iniciales='PL', nombre='Paragon Logistics').rfc == '')

try:
    Cliente(nombre='X', empresas=[Empresa(iniciales='NG', nombre='A'),
                                  Empresa(iniciales='NG', nombre='B')])
    check('empresa duplicada se rechaza', False)
except ErrorConfiguracion:
    check('empresa duplicada se rechaza', True)

try:
    Cliente(nombre='X', empresas=[Empresa(iniciales='NG', nombre='A',
                                          conexion_id='no-existe')])
    check('referencia rota a conexión se rechaza', False)
except ErrorConfiguracion:
    check('referencia rota a conexión se rechaza', True)


# ---------------------------------------------------------------------------
seccion('Nada cableado: el ERP es un dato, no una suposición')
cx = ConexionERP(nombre='Odoo del cliente', conector='odoo_xmlrpc',
                 version='17.0', parametros={'url': 'https://ejemplo'})
c = Cliente(nombre='Otro Cliente',
            empresas=[Empresa(iniciales='ACME', nombre='Acme, S.A. de C.V.',
                              conexion_id=cx.id, id_en_erp='acme_db')],
            conexiones=[cx])
check('un cliente con otro ERP se configura sin tocar código',
      c.conexion_de('ACME').conector == 'odoo_xmlrpc')
try:
    ConexionERP(nombre='x', conector='')
    check('conexión sin conector se rechaza', False)
except ErrorConfiguracion:
    check('conexión sin conector se rechaza', True)


# ---------------------------------------------------------------------------
seccion('Retención configurable')
check('default son 7 años', Retencion().anios == 7)
check('acepta "todo"', Retencion(anios='todo').anio_minimo() is None)
check('calcula el año mínimo', isinstance(Retencion(anios=3).anio_minimo(), int))
try:
    Retencion(anios=0)
    check('retención de 0 se rechaza', False)
except ErrorConfiguracion:
    check('retención de 0 se rechaza', True)


# ---------------------------------------------------------------------------
seccion('Autorización: UNA función, y solo permisos que se verifican')
check('rol bajo no puede configurar', not repo.puede('lector', 'configurar_erp'))
check('administrador sí puede', repo.puede('administrador', 'configurar_erp'))
check('rol desconocido niega', not repo.puede('inventado', 'ver_configuracion'))
try:
    repo.puede('administrador', 'permiso_que_no_existe')
    check('permiso desconocido levanta error', False)
except ErrorConfiguracion:
    check('permiso desconocido levanta error', True)

# El hallazgo #1 de la auditoría: 16 de 20 permisos no se consultaban en ningún
# `if`. Aquí cada permiso declara dónde se verifica, y esto lo comprueba.
sin_lugar = [p for p, donde in repo.PERMISOS.items() if not donde.strip()]
check('todo permiso declara dónde se verifica', not sin_lugar, str(sin_lugar))
huerfanos = [p for r in repo.ROLES.values() for p in r if p not in repo.PERMISOS]
check('ningún rol otorga un permiso inexistente', not huerfanos, str(huerfanos))


# ---------------------------------------------------------------------------
seccion('Almacén: escritura atómica, sin lost-update')
raiz = tempfile.mkdtemp()
try:
    al = AlmacenLocal(raiz)
    al.escribir('p.json', {'n': 1}, None)
    _, v1 = al.leer('p.json')
    al.escribir('p.json', {'n': 2}, v1)          # otro proceso escribe
    try:
        al.escribir('p.json', {'n': 99}, v1)     # yo, con versión vieja
        check('escritura con versión vieja se rechaza', False)
    except ConflictoDeEscritura:
        check('escritura con versión vieja se rechaza', True)
    check('el cambio del otro proceso sobrevive', al.leer('p.json')[0] == {'n': 2})

    try:
        al.escribir('p.json', {'n': 3}, None)    # None = "solo si no existe"
        check('crear sobre algo existente se rechaza', False)
    except ConflictoDeEscritura:
        check('crear sobre algo existente se rechaza', True)

    al.escribir('q.json', {'n': 0}, None)
    actualizar_con_reintento(al, 'q.json', lambda d: {'n': d['n'] + 1})
    check('actualizar_con_reintento aplica el cambio', al.leer('q.json')[0] == {'n': 1})

    try:
        al.leer('../fuera.json')
        check('ruta fuera del almacén se rechaza', False)
    except ValueError:
        check('ruta fuera del almacén se rechaza', True)

    # -----------------------------------------------------------------
    seccion('Secretos: aislados por cliente, sin fallback')
    try:
        A, B = 'cliente-aaa', 'cliente-bbb'
        sa = AlmacenSecretos(al, A)
        sa.guardar('conexion/x', {'usuario': 'u', 'contrasena': 'clave'})
        check('ida y vuelta del secreto',
              sa.leer('conexion/x') == {'usuario': 'u', 'contrasena': 'clave'})

        # El hallazgo de seguridad: en el sistema anterior, un fallo de
        # descifrado caía a las credenciales globales y un cliente podía
        # autenticarse contra el ERP de otro.
        os.makedirs(os.path.join(raiz, 'clientes', B, 'secretos', 'conexion'),
                    exist_ok=True)
        shutil.copy(
            os.path.join(raiz, 'clientes', A, 'secretos', 'conexion', 'x.json'),
            os.path.join(raiz, 'clientes', B, 'secretos', 'conexion', 'x.json'))
        try:
            AlmacenSecretos(al, B).leer('conexion/x')
            check('blob de otro cliente NO se descifra', False,
                  'se descifró: hay cruce entre inquilinos')
        except SecretoNoDisponible:
            check('blob de otro cliente NO se descifra', True)

        try:
            sa.leer('conexion/inexistente')
            check('secreto ausente falla en vez de usar uno global', False)
        except SecretoNoDisponible:
            check('secreto ausente falla en vez de usar uno global', True)
    except SecretoNoDisponible as e:
        print(f'  (omitidas: no hay clave maestra disponible — {e})')

    # -----------------------------------------------------------------
    seccion('Publicación: los secretos no salen')
    cx2 = ConexionERP(nombre='ERP', conector='cualquiera',
                      parametros={'url': 'https://host', 'password': 'NO-DEBE-SALIR'})
    cli = Cliente(nombre='Demo',
                  empresas=[Empresa(iniciales='AA', nombre='Alfa',
                                    conexion_id=cx2.id, id_en_erp='db')],
                  conexiones=[cx2])
    import json as _json
    publicado = _json.dumps(repo.configuracion_publicable(cli), ensure_ascii=False)
    check('la configuración publicable no lleva contraseñas',
          'NO-DEBE-SALIR' not in publicado)
    check('tampoco lleva la referencia al secreto',
          'secretos_ref' not in publicado)
    check('pero sí lo que sirve para diagnosticar', 'https://host' in publicado)

    # -----------------------------------------------------------------
    seccion('Repositorio: guardar y recuperar')
    repo.guardar_cliente(al, cli)
    recuperado = repo.cargar_cliente(al, cli.id)
    check('se recupera igual', recuperado.nombre == 'Demo'
          and recuperado.empresa('AA').nombre == 'Alfa')
    check('aparece en el índice',
          any(x['id'] == cli.id for x in repo.listar_clientes(al)))
    check('la carpeta usa el id opaco, no el nombre',
          cli.prefijo_s3() == f'clientes/{cli.id}' and 'demo' not in cli.prefijo_s3())
finally:
    shutil.rmtree(raiz, ignore_errors=True)

print()
if _fallos:
    print(f'{len(_fallos)} PRUEBA(S) FALLARON: {", ".join(_fallos)}')
    raise SystemExit(1)
print('Todas las pruebas pasaron.')
