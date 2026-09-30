# -*- coding: utf-8 -*-
"""
===============================================================================
 REPOSITORIO DE CONFIGURACIÓN — la API que usa el resto del sistema
===============================================================================
Nadie fuera de este paquete abre un archivo de configuración ni construye una
ruta. Se pide por aquí. Esa es la regla que hace que la ruta del cliente exista
en un solo lugar (`Cliente.prefijo_s3`) y no en veinte, como terminó pasando en
el sistema anterior.

SOBRE LA AUTORIZACIÓN
---------------------
Abajo hay UNA función que decide si alguien puede hacer algo: `puede()`. Una.
La auditoría del sistema anterior encontró once mecanismos distintos de
autorización, y el archivo que definía los tiers escribía la lista de tiers de
staff a mano en vez de usar su propio helper. Con once copias, cambiar una regla
es apostar a cuántas encontraste.

Y una regla que viene de ese mismo hallazgo: **aquí solo existen los permisos
que alguien verifica**. En el sistema anterior, 16 de 20 permisos se mostraban
en la interfaz, se guardaban en disco y no se consultaban en ningún `if`. Si
agregas un permiso a `PERMISOS` sin escribir el código que lo comprueba, estás
construyendo teatro. La prueba `test_permisos_se_usan` existe para no dejarte.
===============================================================================
"""
import os
from typing import Dict, List, Optional

try:
    from .modelo import Cliente, Empresa, ConexionERP, Retencion, ErrorConfiguracion
    from .almacen import (Almacen, AlmacenLocal, AlmacenS3,
                          ConflictoDeEscritura)
except ImportError:                      # corriendo como script suelto
    from modelo import Cliente, Empresa, ConexionERP, Retencion, ErrorConfiguracion
    from almacen import (Almacen, AlmacenLocal, AlmacenS3,
                         ConflictoDeEscritura)

RUTA_INDICE = 'clientes/indice.json'


# ---------------------------------------------------------------------------
# Permisos — cada uno con el lugar que lo verifica
# ---------------------------------------------------------------------------
# El valor no es decorativo: es dónde vive el `if` que lo comprueba. Si no
# puedes escribir esa referencia, el permiso no debe existir.
PERMISOS: Dict[str, str] = {
    'configurar_erp':   'configurar.py — alta y edición de conexiones y credenciales',
    'ver_configuracion': 'panel de Ajustes del tablero — muestra la configuración vigente',
    'extraer_datos':    'erp/extraer_estados_financieros.py — dispara la extracción',
}

# Roles, de menor a mayor. Un rol incluye lo de los anteriores.
ROLES: Dict[str, List[str]] = {
    'lector':        ['ver_configuracion'],
    'operador':      ['ver_configuracion', 'extraer_datos'],
    'administrador': ['ver_configuracion', 'extraer_datos', 'configurar_erp'],
}


def puede(rol: str, permiso: str) -> bool:
    """La única función de autorización del sistema.

    Si necesitas preguntar algo que esta función no contesta, extiende esta
    función. No escribas la comprobación en tu archivo: así es como se llega a
    once mecanismos que se contradicen entre sí.
    """
    if permiso not in PERMISOS:
        # Un permiso desconocido NIEGA. Si alguien escribe mal el nombre, lo
        # correcto es cerrar la puerta, no abrirla por descuido.
        raise ErrorConfiguracion(
            f'Permiso desconocido: {permiso!r}. Los válidos son: '
            f'{", ".join(sorted(PERMISOS))}. Si es nuevo, agrégalo a PERMISOS '
            f'junto con el lugar donde se verifica.')
    return permiso in ROLES.get((rol or '').strip().lower(), [])


# ---------------------------------------------------------------------------
# Lectura y escritura de clientes
# ---------------------------------------------------------------------------
def listar_clientes(almacen: Almacen) -> List[Dict]:
    """El índice: id y nombre de cada cliente. Es lo mínimo para presentar un
    selector sin tener que abrir la configuración completa de cada uno."""
    datos, _ = almacen.leer(RUTA_INDICE)
    return (datos or {}).get('clientes', [])


def cargar_cliente(almacen: Almacen, cliente_id: str) -> Optional[Cliente]:
    datos, _ = almacen.leer(f'clientes/{cliente_id}/configuracion.json')
    return Cliente.de_dict(datos) if datos else None


def guardar_cliente(almacen: Almacen, cliente: Cliente) -> None:
    """Guarda la configuración y actualiza el índice.

    Son dos escrituras y no hay transacción entre ellas. Se hace en este orden
    —primero la configuración, luego el índice— porque el fallo intermedio deja
    un cliente completo que no aparece en el listado, que es recuperable
    (`reconstruir_indice`). Al revés dejaría una entrada en el índice apuntando
    a una configuración que no existe, que rompe a quien la abra.
    """
    ruta = f'clientes/{cliente.id}/configuracion.json'
    _, version = almacen.leer(ruta)
    almacen.escribir(ruta, cliente.a_dict(), version)

    datos, version_idx = almacen.leer(RUTA_INDICE)
    indice = datos or {'clientes': []}
    entradas = [c for c in indice['clientes'] if c.get('id') != cliente.id]
    entradas.append({'id': cliente.id, 'nombre': cliente.nombre,
                     'activo': cliente.activo})
    indice['clientes'] = sorted(entradas, key=lambda c: c['nombre'].lower())
    almacen.escribir(RUTA_INDICE, indice, version_idx)


def reconstruir_indice(almacen: Almacen) -> int:
    """Rearma el índice leyendo las carpetas. Existe porque el guardado son dos
    escrituras sin transacción: si la segunda falla, esto lo repara sin que
    nadie tenga que editar JSON a mano."""
    encontrados = []
    for ruta in almacen.listar('clientes/'):
        if not ruta.endswith('/configuracion.json'):
            continue
        datos, _ = almacen.leer(ruta)
        if datos:
            encontrados.append({'id': datos.get('id'),
                                'nombre': datos.get('nombre', ''),
                                'activo': datos.get('activo', True)})
    _, version = almacen.leer(RUTA_INDICE)
    almacen.escribir(RUTA_INDICE,
                     {'clientes': sorted(encontrados,
                                         key=lambda c: c['nombre'].lower())},
                     version)
    return len(encontrados)


# ---------------------------------------------------------------------------
# Qué cliente atiende esta instalación
# ---------------------------------------------------------------------------
VAR_CLIENTE = 'CLIENTE_ID'


def cliente_actual(almacen: Almacen) -> Cliente:
    """El cliente sobre el que trabaja esta corrida.

    Se toma de `CLIENTE_ID`. Si no está y hay exactamente uno, se usa ese —una
    comodidad razonable mientras solo existe un cliente—. Si hay varios, se
    exige elegir: adivinar cuál, con datos de clientes distintos en juego, es
    justo el tipo de conveniencia que produce una fuga entre inquilinos.
    """
    cid = os.environ.get(VAR_CLIENTE, '').strip()
    if cid:
        c = cargar_cliente(almacen, cid)
        if not c:
            raise ErrorConfiguracion(
                f'{VAR_CLIENTE}={cid!r} pero no existe ese cliente.')
        return c
    clientes = [c for c in listar_clientes(almacen) if c.get('activo', True)]
    if len(clientes) == 1:
        return cargar_cliente(almacen, clientes[0]['id'])
    if not clientes:
        raise ErrorConfiguracion(
            'No hay ningún cliente configurado. Corre `configurar.py --semilla` '
            'para crear el primero.')
    nombres = ', '.join(f"{c['nombre']} ({c['id'][:8]})" for c in clientes)
    raise ErrorConfiguracion(
        f'Hay {len(clientes)} clientes y no se indicó cuál: define '
        f'{VAR_CLIENTE}. Disponibles: {nombres}')


# ---------------------------------------------------------------------------
# Lo que se publica para el tablero
# ---------------------------------------------------------------------------
def _nombre_norma(clave):
    try:
        import normas_contables as nc
        return {'clave': clave, 'nombre': nc.obtener(clave)['nombre']}
    except Exception:
        return {'clave': clave, 'nombre': clave}


def configuracion_publicable(cliente: Cliente) -> Dict:
    """La configuración SIN nada sensible, para que el tablero la muestre.

    Se construye por lista blanca —se nombra lo que sale— y no quitando campos
    de la estructura completa. La diferencia importa: con lista blanca, un campo
    nuevo y sensible que alguien agregue al modelo mañana queda fuera por
    omisión. Quitando campos, entra por omisión.
    """
    return {
        'cliente': {'id': cliente.id, 'nombre': cliente.nombre},
        'retencion': {'anios': cliente.retencion.anios},
        # El marco contable decide cosas visibles —qué entra al EBITDA, por
        # ejemplo— así que quien lee el tablero tiene derecho a saber cuál se
        # aplicó sin preguntar.
        'normas': _nombre_norma(cliente.normas),
        'empresas': [
            {'iniciales': e.iniciales, 'nombre': e.nombre, 'rfc': e.rfc,
             'activa': e.activa, 'conectada': bool(e.conexion_id),
             'erp': (cliente.conexion_de(e.iniciales).conector
                     if cliente.conexion_de(e.iniciales) else ''),
             'notas': e.notas}
            for e in cliente.empresas
        ],
        'conexiones': [
            {'id': c.id, 'nombre': c.nombre, 'conector': c.conector,
             'version': c.version, 'activa': c.activa,
             # De los parámetros solo sale la URL: es lo que sirve para
             # diagnosticar ("¿está apuntando al servidor correcto?") y no es
             # un secreto. Usuario y contraseña ni siquiera viven aquí.
             'servidor': str(c.parametros.get('url', ''))}
            for c in cliente.conexiones
        ],
    }


VAR_S3_BUCKET = 'ALMACEN_S3_BUCKET'
VAR_S3_PREFIJO = 'ALMACEN_S3_PREFIJO'
VAR_S3_PERFIL = 'ALMACEN_S3_PERFIL'
VAR_S3_REGION = 'ALMACEN_S3_REGION'


def raiz_local() -> str:
    """Dónde vive el almacén de disco: `finanzas/datos_config/`."""
    return os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'datos_config')


def descripcion_almacen() -> str:
    """Una línea que dice dónde se está guardando. Para que cualquier script
    pueda imprimirla: correr contra el disco creyendo que se corre contra el
    bucket —o al revés— es la clase de error que solo se nota cuando alguien
    busca un dato que capturó y no está."""
    bucket = os.environ.get(VAR_S3_BUCKET, '').strip()
    if not bucket:
        return f'disco local — {raiz_local()}'
    pref = os.environ.get(VAR_S3_PREFIJO, '').strip('/')
    perfil = os.environ.get(VAR_S3_PERFIL, '').strip()
    return (f's3://{bucket}/{pref + "/" if pref else ""}'
            f'  (perfil {perfil or "por defecto"})')


def almacen_por_defecto() -> Almacen:
    """Dónde vive la configuración: el bucket si está configurado, el disco si no.

    POR QUÉ POR VARIABLES DE ENTORNO Y NO EN UN ARCHIVO DE CONFIGURACIÓN
    --------------------------------------------------------------------
    Porque esto decide dónde está el archivo de configuración. Guardar la
    respuesta dentro del archivo que hay que encontrar no resuelve nada. Y
    además no es una decisión del cliente —lo que vive en su configuración—
    sino de la instalación: la misma configuración de Networks se lee desde la
    laptop de quien extrae y desde el proceso que publica, y cada uno puede
    apuntar a un sitio distinto sin que el dato cambie.

        set ALMACEN_S3_BUCKET=mi-bucket-privado
        set ALMACEN_S3_PREFIJO=config
        set ALMACEN_S3_PERFIL=facturacion-dashboard

    SIN LA VARIABLE SE USA EL DISCO, y es a propósito: quien clona el proyecto
    y corre una prueba no debe tocar el bucket compartido por omisión. La
    degradación va en esa dirección y no en la contraria —nunca "no pude
    hablar con S3, guardo en disco"—, porque esa sí produce dos verdades.
    """
    bucket = os.environ.get(VAR_S3_BUCKET, '').strip()
    if not bucket:
        return AlmacenLocal(raiz_local())
    return AlmacenS3(
        bucket,
        perfil=os.environ.get(VAR_S3_PERFIL, '').strip() or None,
        region=os.environ.get(VAR_S3_REGION, '').strip() or 'us-east-1',
        prefijo_base=os.environ.get(VAR_S3_PREFIJO, '').strip('/'))
