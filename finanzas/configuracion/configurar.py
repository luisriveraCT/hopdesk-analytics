# -*- coding: utf-8 -*-
"""
===============================================================================
 CONFIGURAR — alta y edición de clientes, empresas, conectores y retención
===============================================================================
Esta es hoy la herramienta de configuración. Corre en la máquina local, que es
la única que debe ver una credencial de ERP.

POR QUÉ NO ES UNA PANTALLA DEL TABLERO (todavía)
------------------------------------------------
El tablero publicado es HTML estático: no tiene servidor. Un formulario de
contraseñas ahí significa que la credencial del ERP viaja al navegador de
cualquiera que abra el enlace y queda en el código de la página. No es un
detalle de implementación que se pueda pulir después: es la diferencia entre un
secreto y un secreto publicado.

Así que el reparto es:
  · **Capturar** configuración y credenciales → aquí, en local.
  · **Mostrar** la configuración vigente (sin secretos) → panel de Ajustes del
    tablero, que lee lo que este comando publica.

El plan para convertir esto en una pantalla de verdad —servida, con sesión, sin
que el secreto salga del servidor— está en `PLAN_UNIFICACION.md`. Lo que sí
queda hecho desde hoy es el modelo de datos: el día que exista esa pantalla,
escribirá exactamente estos mismos objetos.

USO
---
    python configurar.py --semilla              crea el cliente inicial
    python configurar.py --mostrar              muestra la configuración
    python configurar.py --retencion 7          años de historia (o "todo")
    python configurar.py --credenciales NG      captura usuario y contraseña
    python configurar.py --importar-renviron    trae las credenciales existentes
    python configurar.py --agregar-empresa      da de alta una empresa nueva
    python configurar.py --publicar             escribe la config para el tablero
===============================================================================
"""
import os
import sys
import json
import getpass
import argparse

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.dirname(AQUI))

from modelo import (Cliente, Empresa, ConexionERP, Retencion,  # noqa: E402
                    PoliticaFinanciera, ErrorConfiguracion, RETENCION_TODO)
import repositorio as repo                                      # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import razones_financieras as rf_mod                            # noqa: E402
from secretos import AlmacenSecretos, SecretoNoDisponible       # noqa: E402


# ---------------------------------------------------------------------------
# Datos semilla del primer cliente
# ---------------------------------------------------------------------------
# Verificados contra el ERP y contra las facturas reales el 2026-09-25. Están
# aquí SOLO como datos de arranque, no como configuración del programa: el
# segundo cliente no toca este archivo, se da de alta con --agregar-empresa.
#
# Nota sobre los RFC: salieron de las facturas intercompañía del propio ERP. De
# paso aparecieron dos erratas en el maestro de socios de negocio de SAP, que
# conviene corregir allá y que NO se replican aquí:
#     NRE08091519A  convive con  NRE080915I9A   (un 1 donde va una I)
#     NCS040697CU8  convive con  NCS040623CU8
# Se usa en cada caso el RFC mayoritario, que es el correcto.
SEMILLA_NOMBRE = 'Networks'
SEMILLA_SERVIDOR = 'https://192.168.14.131:50000/b1s/v1'
SEMILLA_CONECTOR = 'sap_b1_service_layer'
SEMILLA_VERSION = 'SAP Business One 10.0 — Service Layer v1'

SEMILLA_EMPRESAS = [
    dict(iniciales='NCS', nombre='Networks Crossdocking Services, S.A. de C.V.',
         rfc='NCS040623CU8', id_en_erp='SBO_CROSSDOCKING'),
    dict(iniciales='NG',  nombre='Networks Group LCT, S.C.',
         rfc='NGL210728KD3', id_en_erp='SBO_NETWORKSSS'),
    dict(iniciales='NL',  nombre='Networks & Logistics, S.A. de C.V.',
         rfc='N&L0004045Y8', id_en_erp='SBO_LOGISTICS'),
    dict(iniciales='NRS', nombre='Networks Realtors, S.A. de C.V.',
         rfc='NRE080915I9A', id_en_erp='SBO_REALTORS'),
    dict(iniciales='NTS', nombre='Networks Trucking Services, S.A. de C.V.',
         rfc='NTS061025613', id_en_erp='SBO_TRUCKING'),
    # Paragon existe como socio de negocio en el ERP (aparece con RFC en
    # facturas) pero NO tiene base de datos propia: no se puede extraer de ella
    # todavía. Se da de alta sin conexión, a propósito, para que aparezca en el
    # listado como pendiente en vez de desaparecer y olvidarse.
    dict(iniciales='PL',  nombre='Paragon Logistics, S.A. de C.V.',
         rfc='PLO2509182U5', id_en_erp='',
         notas='Pendiente de alta en el ERP. Mientras no tenga base de datos '
               'propia no se le puede extraer; sus facturas históricas solo '
               'existían en los archivos de Excel que se retiraron.'),
]

# Política financiera de arranque: los supuestos del costo de capital y las
# metas del semáforo. Las metas son las del "Diccionario_KPIs" de
# KPIs_Finanzas.xlsx —las que ya usa Finanzas— y los supuestos son los que
# estaban en el mismo archivo.
#
# Están aquí y no en el código porque son de ESTE cliente. Otro grupo, en otro
# sector, tiene otro ciclo de cobranza y otro costo de capital; debe poder
# cambiarlos desde la configuración sin que nadie edite un archivo .py.
SEMILLA_SUPUESTOS = {
    'rf': 0.095,       # tasa libre de riesgo
    'beta': 1.10,      # beta apalancada
    'erp': 0.065,      # prima de riesgo de mercado
    'kd': 0.115,       # costo de la deuda antes de impuestos
    'tasa_impositiva': 0.30,
}

# De dónde sale cada supuesto. Se guarda para que quien lea un WACC sepa qué
# parte viene de un mercado observable y qué parte es un juicio: en una empresa
# privada, beta y prima de mercado NO se pueden observar, y presentarlos sin
# decirlo hace que el WACC parezca más preciso de lo que es.
SEMILLA_FUENTES = {
    'rf': 'Banxico — se refresca automáticamente cuando hay conexión; este '
          'valor es el respaldo.',
    'beta': 'ENTRADA MANUAL. Networks es privada: no hay precio de acción del '
            'cual estimarla. Es un juicio, revisable.',
    'erp': 'ENTRADA MANUAL. Prima de riesgo de mercado para México.',
    'kd': 'Se puede sustituir por el costo real de los financiamientos '
          'registrados en HopDesk.',
    'tasa_impositiva': 'Respaldo. La tasa efectiva real se calcula del ERP por '
                       'empresa y periodo, y gana sobre este valor cuando es '
                       'confiable.',
}

# Convenciones de cálculo de este cliente. La de días de pago NO es la clásica,
# y la razón está medida: el costo de ventas de este grupo es el 5.8% de los
# ingresos en su empresa más grande, el 0.2% en otra y exactamente cero en una
# tercera, porque el diesel, el personal de operación y las rentas de equipo se
# registran como gastos de operación. Contra esa base los días de pago salían en
# 365 para una empresa y 1,564 para el consolidado.
#
# Si contabilidad reclasifica el costo directo a la clase de costo —que es una
# de las decisiones que están sobre la mesa—, esto vuelve a 'costo_de_ventas'
# cambiando la configuración, no el código.
SEMILLA_CONVENCIONES = {
    'base_dias_pago': 'costos_operativos_efectivo',
    # Días del año para las razones de días. 365 es lo usual en estados
    # financieros; 360 se usa en tesorería y en varios contratos de crédito.
    'dias_anio': '365',
    # Qué tan cerca de la meta sigue siendo amarillo, en tanto por uno. Lo que
    # usa KPIs_Finanzas.xlsx.
    'holgura_semaforo': '0.10',
    # Dentro de qué banda una tasa efectiva de impuestos es utilizable. La de
    # aquí cubre el régimen mexicano (ISR 30% más PTU 10% sobre otra base, que
    # en la práctica da 35-45%) con holgura. Un cliente en otra jurisdicción
    # tiene otra banda: con ésta se le marcarían como no confiables tasas
    # perfectamente normales de su país.
    'banda_tasa_efectiva': '0.0,0.60',
}

SEMILLA_METAS = {
    'roe': 0.18,
    'roic': 0.13,
    'wacc': 0.11,
    'spread_roic_wacc': 0.0,
    'margen_fcf': 0.03,
    'deuda_neta_ebitda': 3.0,
    'dso': 55,
    'dpo': 40,
    'ccc': 30,
    'ctn_sobre_ventas': 0.18,
    'deuda_entre_patrimonio': 1.5,
    'tasa_efectiva': 0.30,
    'costo_deuda_efectivo': 0.11,
    'margen_ebitda': 0.19,
    'margen_ebit': 0.13,
    'rotacion_activos': 1.2,
}

# Cómo se llamaban las variables del sistema anterior, para poder importarlas.
_RENVIRON_HOPDESK = r'C:\Users\luisr\Antiguedad_App\.Renviron'


def _almacen():
    return repo.almacen_por_defecto()


# ---------------------------------------------------------------------------
def sembrar(almacen) -> Cliente:
    existentes = repo.listar_clientes(almacen)
    if existentes:
        print('Ya hay clientes configurados:')
        for c in existentes:
            print(f"   {c['nombre']}  ({c['id']})")
        print('La semilla no se vuelve a correr para no duplicar. Usa '
              '--agregar-empresa o --mostrar.')
        return repo.cargar_cliente(almacen, existentes[0]['id'])

    conexion = ConexionERP(
        nombre='SAP Business One — producción',
        conector=SEMILLA_CONECTOR,
        version=SEMILLA_VERSION,
        parametros={'url': SEMILLA_SERVIDOR, 'ssl_verify': False,
                    'requiere_vpn': True},
    )
    empresas = []
    for e in SEMILLA_EMPRESAS:
        datos = dict(e)
        # Solo se conecta lo que tiene base de datos en el ERP.
        datos['conexion_id'] = conexion.id if datos.get('id_en_erp') else ''
        empresas.append(Empresa(**datos))

    cliente = Cliente(nombre=SEMILLA_NOMBRE, empresas=empresas,
                      conexiones=[conexion], retencion=Retencion(),
                      politica=PoliticaFinanciera(
                          supuestos=dict(SEMILLA_SUPUESTOS),
                          metas=dict(SEMILLA_METAS),
                          fuentes=dict(SEMILLA_FUENTES),
                          convenciones=dict(SEMILLA_CONVENCIONES)))
    repo.guardar_cliente(almacen, cliente)
    print(f'Cliente creado: {cliente.nombre}')
    print(f'   id      : {cliente.id}')
    print(f'   carpeta : {cliente.prefijo_s3()}/')
    print(f'   empresas: {len(cliente.empresas)} '
          f'({len(cliente.empresas_conectadas())} conectadas, '
          f'{len(cliente.empresas_sin_conectar())} pendientes)')
    print(f'   retención: {cliente.retencion.anios} años')
    print()
    print('Siguiente paso: cargar las credenciales del ERP con')
    print('   python configurar.py --importar-renviron')
    return cliente


# ---------------------------------------------------------------------------
def mostrar(cliente: Cliente, almacen) -> None:
    # DÓNDE se está leyendo, antes que QUÉ se leyó. Correr contra el disco
    # creyendo que se corre contra el bucket compartido es el error que este
    # renglón existe para hacer imposible de cometer sin darse cuenta: los
    # datos se ven idénticos, y solo el encabezado distingue una configuración
    # que ve todo el equipo de una que vive en una laptop.
    print(f'\nalmacén: {repo.descripcion_almacen()}')
    print(f'\n=== {cliente.nombre} ===')
    print(f'  id        : {cliente.id}')
    print(f'  carpeta   : {cliente.prefijo_s3()}/')
    r = cliente.retencion
    minimo = r.anio_minimo()
    print(f'  retención : {r.anios}'
          + (f' años (desde {minimo})' if minimo else ' (toda la historia)'))
    print('\n  Conexiones a ERP:')
    for c in cliente.conexiones:
        print(f'     {c.nombre}')
        print(f'        conector : {c.conector}')
        print(f'        versión  : {c.version or "—"}')
        print(f'        servidor : {c.parametros.get("url", "—")}')
    print('\n  Empresas:')
    try:
        secretos = AlmacenSecretos(almacen, cliente.id)
    except SecretoNoDisponible:
        secretos = None
    for e in cliente.empresas:
        cx = cliente.conexion_de(e.iniciales)
        if not cx:
            estado = 'SIN CONECTAR'
        elif secretos is None:
            estado = 'conectada (no se pudo revisar credenciales)'
        elif secretos.existe(f'{cx.id}/{e.iniciales}'):
            estado = 'lista'
        else:
            estado = 'FALTAN CREDENCIALES'
        print(f'     {e.iniciales:<5} {e.nombre[:46]:<47} {estado}')
        if e.rfc:
            print(f'           RFC {e.rfc}'
                  + (f'   ERP: {e.id_en_erp}' if e.id_en_erp else ''))
        if e.notas:
            print(f'           nota: {e.notas[:96]}')
    print()


# ---------------------------------------------------------------------------
# =============================================================================
# ⚠ VULNERABILIDAD PENDIENTE — detectada 2026-09-25, NO corregida
# =============================================================================
# Para encontrarlas todas:  grep -rn "VULNERABILIDAD PENDIENTE" .
#
# --- V1: las cinco empresas comparten la MISMA contraseña de SAP -------------
# Verificado al importar del .Renviron: SAP_NCS_PASSWORD, SAP_NG_PASSWORD,
# SAP_NL_PASSWORD, SAP_NRS_PASSWORD y SAP_NTS_PASSWORD tienen **un solo valor
# distinto entre las cinco**.
#
# Consecuencia: la contraseña de una empresa es la contraseña de todas. Si se
# filtra por cualquier vía —una captura de pantalla, un log, un respaldo— el
# alcance no es una empresa, es el grupo completo. Y rotarla obliga a rotar las
# cinco a la vez, que es justo la fricción que hace que no se rote nunca.
#
# Se descubrió de rebote: al probar el detector de fugas del tablero inyectando
# la contraseña de NG, marcó las cinco variables.
#
# Cómo se arregla: contraseñas distintas por empresa en SAP, y volver a correr
# `--importar-renviron`. Este código ya las guarda por separado, así que no hay
# cambio que hacer aquí — el arreglo es del lado del ERP.
#
# --- V2: RESEND_API_KEY es un placeholder sin rotar --------------------------
# Vale literalmente "sandbox". No es un secreto filtrado; es que el envío de
# correo no está configurado con una llave real. Lo anoto porque una variable
# que *parece* una credencial y no lo es termina excluida de las revisiones, y
# el día que reciba una llave de verdad nadie se acuerda de volver a incluirla.
# =============================================================================


def importar_renviron(cliente: Cliente, almacen) -> None:
    """Trae las credenciales que ya existen en el .Renviron de HopDesk.

    Se hace una vez, para no volver a capturar a mano lo que ya funciona. A
    partir de aquí la fuente de verdad es el almacén cifrado, y las variables
    del .Renviron dejan de consultarse para este cliente.
    """
    if not os.path.exists(_RENVIRON_HOPDESK):
        print(f'No existe {_RENVIRON_HOPDESK}; nada que importar.')
        return
    valores = {}
    with open(_RENVIRON_HOPDESK, encoding='utf-8') as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith('#') or '=' not in linea:
                continue
            k, v = linea.split('=', 1)
            valores[k.strip()] = v.strip().strip('"\'')

    secretos = AlmacenSecretos(almacen, cliente.id)
    puestas, faltantes = [], []
    for e in cliente.empresas_conectadas():
        cx = cliente.conexion_de(e.iniciales)
        usuario = valores.get(f'SAP_{e.iniciales}_USER', '')
        clave = valores.get(f'SAP_{e.iniciales}_PASSWORD', '')
        if not (usuario and clave):
            faltantes.append(e.iniciales)
            continue
        secretos.guardar(f'{cx.id}/{e.iniciales}',
                         {'usuario': usuario, 'contrasena': clave})
        puestas.append(e.iniciales)
    print(f'Credenciales importadas: {", ".join(puestas) or "ninguna"}')
    if faltantes:
        print(f'Sin credenciales en el .Renviron: {", ".join(faltantes)}')
        print('   Cárgalas con  python configurar.py --credenciales <INICIALES>')
    print('\nDesde ahora estas credenciales viven cifradas y aisladas por '
          'cliente. El .Renviron ya no es la fuente para este cliente.')


def capturar_credenciales(cliente: Cliente, almacen, iniciales: str) -> None:
    e = cliente.empresa(iniciales)
    if not e:
        raise ErrorConfiguracion(
            f'{cliente.nombre} no tiene una empresa {iniciales!r}. '
            f'Las que hay: {", ".join(x.iniciales for x in cliente.empresas)}')
    cx = cliente.conexion_de(e.iniciales)
    if not cx:
        raise ErrorConfiguracion(
            f'{e.iniciales} no está asociada a ninguna conexión de ERP, así que '
            f'no hay dónde usar una credencial. Conéctala primero.')
    print(f'Credenciales de {e.iniciales} — {e.nombre}')
    print(f'   conexión: {cx.nombre} ({cx.conector})')
    usuario = input('   usuario: ').strip()
    clave = getpass.getpass('   contraseña (no se muestra): ')
    if not usuario or not clave:
        print('   Cancelado: no se guarda una credencial incompleta.')
        return
    AlmacenSecretos(almacen, cliente.id).guardar(
        f'{cx.id}/{e.iniciales}', {'usuario': usuario, 'contrasena': clave})
    print(f'   Guardadas y cifradas para {e.iniciales}.')


# ---------------------------------------------------------------------------
def agregar_empresa(cliente: Cliente, almacen) -> None:
    print('Alta de empresa. Los campos con * son obligatorios.\n')
    ini = input('  * Iniciales (2-8, p.ej. PL): ').strip().upper()
    nombre = input('  * Nombre o razón social completa: ').strip()
    rfc = input('    RFC (opcional, se valida si lo capturas): ').strip().upper()

    print('\n  Conexión al ERP:')
    for i, c in enumerate(cliente.conexiones, 1):
        print(f'     {i}) {c.nombre}  [{c.conector}]')
    print(f'     {len(cliente.conexiones) + 1}) Sin conectar por ahora')
    op = input('  * Elige: ').strip()
    conexion_id, id_en_erp = '', ''
    try:
        idx = int(op) - 1
        if 0 <= idx < len(cliente.conexiones):
            conexion_id = cliente.conexiones[idx].id
            id_en_erp = input('  * Identificador de la empresa en el ERP '
                              '(en SAP B1 es la base de datos): ').strip()
            if not id_en_erp:
                raise ErrorConfiguracion(
                    'Sin identificador en el ERP no se puede extraer. Si aún no '
                    'lo tienes, da de alta la empresa "Sin conectar" y la '
                    'conectas después.')
    except ValueError:
        pass
    notas = input('    Notas (opcional): ').strip()

    empresa = Empresa(iniciales=ini, nombre=nombre, rfc=rfc,
                      conexion_id=conexion_id, id_en_erp=id_en_erp, notas=notas)
    cliente.empresas.append(empresa)
    cliente.__post_init__()          # revalida el conjunto, no solo la nueva
    repo.guardar_cliente(almacen, cliente)
    print(f'\n  Empresa {empresa.iniciales} dada de alta.')
    if conexion_id:
        print(f'  Falta cargar sus credenciales:')
        print(f'     python configurar.py --credenciales {empresa.iniciales}')


def detectar_interco(cliente: Cliente, almacen) -> None:
    """Llena el registro intercompañía leyendo las facturas ya extraídas.

    Busca, en los documentos de todas las empresas, con qué CardCodes y con qué
    RFC aparece cada empresa del grupo cuando es la contraparte. Es una tarea
    que nadie debería hacer de memoria: los CardCodes cambian de un libro a otro
    porque cada base de datos tiene su propio catálogo de socios, así que una
    misma empresa tiene un código distinto en cada una de las otras.

    El emparejamiento arranca por el RFC configurado, que es el identificador
    fiscal y no admite interpretación. Lo que encuentra por RFC le da los
    CardCodes; y si un CardCode aparece además con OTRO RFC, ese RFC se propone
    como alterno — así es como se detectan las erratas del maestro de socios.
    """
    datos = os.path.join(os.path.dirname(AQUI), 'datos_erp')
    if not os.path.isdir(datos):
        print('No hay facturas extraídas todavía. Corre primero la extracción.')
        return

    rfc_a_ini = {e.rfc.upper(): e.iniciales for e in cliente.empresas if e.rfc}
    if not rfc_a_ini:
        print('Ninguna empresa tiene RFC capturado; sin eso no hay por dónde '
              'empezar. Captúralos primero.')
        return

    import collections
    codigos = collections.defaultdict(collections.Counter)
    rfcs_vistos = collections.defaultdict(collections.Counter)

    # UN CARDCODE SOLO TIENE SENTIDO DENTRO DE SU LIBRO. Cada base de datos del
    # ERP tiene su propio catálogo de socios, así que "C1004" existe en las
    # cinco y en cada una nombra a alguien distinto. Se califican con el libro
    # de origen ("NCS:C1004"); sin eso, cruzar códigos entre libros mezcla
    # terceros sin relación — la primera versión de esta función proponía como
    # "RFC alterno de Paragon" el RFC de un proveedor cualquiera que compartía
    # número de código en otra empresa.
    def libro_de(nombre_archivo):
        return nombre_archivo.split('_')[1]

    archivos = [a for a in sorted(os.listdir(datos))
                if a.startswith('facturas_') and a.endswith('.json')]

    for arch in archivos:
        libro = libro_de(arch)
        with open(os.path.join(datos, arch), encoding='utf-8') as f:
            docs = json.load(f)
        for d in docs:
            rfc = (d.get('rfc') or '').strip().upper()
            ini = rfc_a_ini.get(rfc)
            if not ini:
                continue
            cc = (d.get('contraparte_id') or '').strip().upper()
            if cc:
                codigos[ini][f'{libro}:{cc}'] += 1
            rfcs_vistos[ini][rfc] += 1

    # Segunda pasada: un CardCode calificado ya conocido que aparezca con otro
    # RFC delata una errata en el maestro de socios — el mismo socio capturado
    # dos veces con el RFC mal escrito.
    cc_a_ini = {cc: ini for ini, cs in codigos.items() for cc in cs}
    for arch in archivos:
        libro = libro_de(arch)
        with open(os.path.join(datos, arch), encoding='utf-8') as f:
            docs = json.load(f)
        for d in docs:
            cc = (d.get('contraparte_id') or '').strip().upper()
            rfc = (d.get('rfc') or '').strip().upper()
            ini = cc_a_ini.get(f'{libro}:{cc}') if cc else None
            if ini and rfc and rfc not in rfc_a_ini:
                rfcs_vistos[ini][rfc] += 1

    print('Registro intercompañía detectado:\n')
    for e in cliente.empresas:
        cs = codigos.get(e.iniciales, {})
        alternos = [r for r in rfcs_vistos.get(e.iniciales, {})
                    if r != e.rfc.upper()]
        if not cs and not alternos:
            print(f'  {e.iniciales:<5} sin apariciones como contraparte')
            continue
        e.codigos_erp = sorted(cs)
        e.rfcs_alternos = sorted(alternos)
        print(f'  {e.iniciales:<5} {len(cs)} código(s): '
              f'{", ".join(sorted(cs)[:8])}{" …" if len(cs) > 8 else ""}')
        for r in alternos:
            print(f'        RFC alterno detectado: {r}  '
                  f'(probable errata del maestro de SAP — conviene corregirla allá)')

    repo.guardar_cliente(almacen, cliente)
    print('\nGuardado. La clasificación intercompañía ya sale de aquí, no de '
          'adivinar por el nombre.')


def fijar_retencion(cliente: Cliente, almacen, valor: str) -> None:
    cliente.retencion = Retencion(anios=valor)
    repo.guardar_cliente(almacen, cliente)
    minimo = cliente.retencion.anio_minimo()
    print(f'Retención: {cliente.retencion.anios}'
          + (f' años — se conserva desde {minimo}' if minimo
             else ' — se conserva toda la historia'))
    if minimo:
        print(f'Los datos anteriores a {minimo} dejan de publicarse. No se '
              f'borran del ERP: esto controla qué se sube, no qué existe.')


def sembrar_politica(cliente: Cliente, almacen) -> None:
    """Llena lo que falte de la política, sin pisar lo ya capturado.

    No sobrescribe: si el usuario ya movió una meta, su valor gana. Un comando
    de migración que pisa decisiones del usuario es peor que no tenerlo.
    """
    pol = cliente.politica
    nuevos = [k for k in SEMILLA_SUPUESTOS if k not in pol.supuestos]
    metas_nuevas = [k for k in SEMILLA_METAS if k not in pol.metas]
    for k in nuevos:
        pol.supuestos[k] = SEMILLA_SUPUESTOS[k]
        pol.fuentes.setdefault(k, SEMILLA_FUENTES.get(k, ''))
    for k in metas_nuevas:
        pol.metas[k] = SEMILLA_METAS[k]
    conv_nuevas = [k for k in SEMILLA_CONVENCIONES if k not in pol.convenciones]
    for k in conv_nuevas:
        pol.convenciones[k] = SEMILLA_CONVENCIONES[k]
    if not nuevos and not metas_nuevas and not conv_nuevas:
        print('La política ya estaba completa; no se cambió nada.')
    else:
        repo.guardar_cliente(almacen, cliente)
        print(f'Agregados {len(nuevos)} supuestos, {len(metas_nuevas)} metas y '
              f'{len(conv_nuevas)} convenciones. Lo capturado no se tocó.')
    fijar_politica(cliente, almacen)


def fijar_politica(cliente: Cliente, almacen, par: str = None) -> None:
    """Muestra o cambia un supuesto/meta. `par` con forma `metas.dso=50`.

    Sin argumento, solo muestra. Un cliente creado antes de que existiera la
    política queda sin metas, y entonces el tablero no pinta semáforos —
    deliberadamente, porque la alternativa es pintarle las metas de otro. Este
    comando es el que las llena.
    """
    pol = cliente.politica
    if par:
        try:
            ruta, valor = par.split('=', 1)
            grupo, clave = ruta.strip().split('.', 1)
        except ValueError:
            raise ErrorConfiguracion(
                f'Formato esperado: grupo.clave=valor — por ejemplo '
                f'"metas.dso=50" o "supuestos.beta=1.2". Recibido: {par!r}')
        if grupo not in ('metas', 'supuestos'):
            raise ErrorConfiguracion(
                f'Grupo desconocido: {grupo!r}. Solo hay "metas" y "supuestos".')
        if grupo == 'metas' and clave not in rf_mod.CATALOGO_KPIS:
            raise ErrorConfiguracion(
                f'No existe el indicador {clave!r}. Una meta sobre un indicador '
                f'inexistente nunca se compara con nada y nadie lo nota. Los '
                f'registrados son: {", ".join(sorted(rf_mod.CATALOGO_KPIS))}')
        getattr(pol, grupo)[clave] = float(valor)
        cliente.politica = PoliticaFinanciera(
            supuestos=pol.supuestos, metas=pol.metas, fuentes=pol.fuentes)
        repo.guardar_cliente(almacen, cliente)
        print(f'{grupo}.{clave} = {valor}')

    print('\n  Supuestos del costo de capital')
    if not pol.supuestos:
        print('    (ninguno — el WACC no se puede calcular sin ellos)')
    for k, v in sorted(pol.supuestos.items()):
        fuente = pol.fuentes.get(k, '')
        print(f'    {k:<18} {v:>10,.4f}   {fuente}')
    print('\n  Convenciones de cálculo')
    if not pol.convenciones:
        print('    (ninguna — se usan las clásicas)')
    for k, v in sorted(pol.convenciones.items()):
        print(f'    {k:<18} {v}')
    print('\n  Metas del semáforo')
    if not pol.metas:
        print('    (ninguna — los indicadores se muestran sin color, que es '
              'correcto: no hay contra qué compararlos)')
    for k, v in sorted(pol.metas.items()):
        cat = rf_mod.CATALOGO_KPIS.get(k, {})
        direccion = 'mayor es mejor' if cat.get('mayor_mejor') else 'menor es mejor'
        print(f'    {k:<24} {v:>9,.4f} {cat.get("unidad",""):<5} {direccion}')


def publicar(cliente: Cliente, almacen) -> None:
    """Escribe la configuración sin secretos para que la lea el tablero."""
    datos = repo.configuracion_publicable(cliente)
    ruta = f'{cliente.prefijo_s3()}/configuracion_publica.json'
    _, version = almacen.leer(ruta)
    almacen.escribir(ruta, datos, version)
    print(f'Publicada en {ruta}')
    print(json.dumps(datos, ensure_ascii=False, indent=2)[:700])


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--semilla', action='store_true')
    ap.add_argument('--mostrar', action='store_true')
    ap.add_argument('--retencion', metavar='AÑOS|todo')
    ap.add_argument('--credenciales', metavar='INICIALES')
    ap.add_argument('--importar-renviron', action='store_true')
    ap.add_argument('--agregar-empresa', action='store_true')
    ap.add_argument('--detectar-interco', action='store_true')
    ap.add_argument('--politica', nargs='?', const='', metavar='grupo.clave=valor',
                    help='muestra la política financiera, o cambia un valor: '
                         '--politica metas.dso=50')
    ap.add_argument('--sembrar-politica', action='store_true',
                    help='llena supuestos y metas de arranque en un cliente '
                         'creado antes de que existiera la política')
    ap.add_argument('--publicar', action='store_true')
    args = ap.parse_args()

    almacen = _almacen()
    if args.semilla:
        sembrar(almacen)
        return

    cliente = repo.cliente_actual(almacen)

    if args.importar_renviron:
        importar_renviron(cliente, almacen)
    elif args.credenciales:
        capturar_credenciales(cliente, almacen, args.credenciales)
    elif args.agregar_empresa:
        agregar_empresa(cliente, almacen)
    elif args.detectar_interco:
        detectar_interco(cliente, almacen)
    elif args.sembrar_politica:
        sembrar_politica(cliente, almacen)
    elif args.politica is not None:
        fijar_politica(cliente, almacen, args.politica or None)
    elif args.retencion:
        fijar_retencion(cliente, almacen, args.retencion)
    elif args.publicar:
        publicar(cliente, almacen)
    else:
        mostrar(cliente, almacen)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except ErrorConfiguracion as e:
        print(f'\nConfiguración inválida: {e}')
        raise SystemExit(2)
