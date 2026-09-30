# -*- coding: utf-8 -*-
"""
===============================================================================
 REGISTRO DE CONECTORES ERP — el "multicontacto"
===============================================================================
Un solo lugar define QUÉ necesita cada tipo de ERP para conectarse y QUÉ es
capaz de entregar. Todo lo demás (formularios, validación, extracción,
análisis) se genera leyendo este registro, nunca con código específico de un
ERP regado por ahí.

Es el mismo patrón que ya usa HopDesk en `R/erp_connector_registry.R`, traído
a Python y extendido con una pieza que allá no hace falta y aquí sí:
`capacidades`. HopDesk solo necesita facturas (AR/AP); aquí necesitamos
Estados Financieros completos, y no todos los ERP los exponen igual. En vez de
descubrirlo a media extracción, cada conector declara de entrada qué puede
entregar, y el orquestador decide con eso.


-------------------------------------------------------------------------------
 MULTIEMPRESA HOY, MULTICLIENTE MAÑANA — y por qué NO se construye aquí
-------------------------------------------------------------------------------
Estas herramientas nacieron para Networks, pero el destino conocido es que sean
de muchas empresas: cada cliente un grupo, cada grupo sus usuarios y su lista de
compañías. Networks es entonces UN cliente con seis compañías, no "el" cliente.

La decisión, tomada a conciencia: **eso no se construye en este repositorio.**
HopDesk ya resuelve identidad, usuarios, grupos y carpetas de cliente, y ya está
en camino a producción. Levantar aquí un segundo sistema de tenancy produciría
dos fuentes de verdad sobre quién es quién — y dos padrones de usuarios que se
desincronizan es un problema que no se arregla después, se arrastra. El día que
esto se multiplique, la tenencia se DELEGA a HopDesk y este código se vuelve
inquilino, no anfitrión.

Lo que sí se hace hoy, que cuesta casi nada y es lo que hará posible ese día:

 1. CERO IDENTIDAD CABLEADA EN LA LÓGICA. No hay un "Networks" escrito dentro de
    ninguna función de negocio. Lo que hay son iniciales de empresa que entran
    como parámetro (`extraer_empresa('NG')`, `clasificar_catalogo(cs, 'NG')`) y
    la configuración del cliente, que dice qué empresas hay y cuáles tienen ERP.
    Sustituir esas listas por lo que devuelva HopDesk para un cliente es un
    cambio de origen de datos, no una reescritura.

 2. LA EMPRESA ES PARTE DE LA LLAVE, SIEMPRE. Credenciales
    (`SAP_<INICIALES>_*`), archivos (`cuentas_<EMPRESA>.json`), caché de
    movimientos, overrides de clasificación: todo va segmentado por empresa
    desde el primer día. Anteponer un cliente a esa llave es agregar un nivel,
    no reacomodar los datos. Es la diferencia entre una migración de una tarde y
    una de un mes.

 3. LO ESPECÍFICO DE UN CLIENTE VIVE EN TABLAS, NO EN `if`. El vocabulario
    bilingüe de `clasificador_cuentas.py`, sus `OVERRIDES` (con empresa y motivo
    obligatorios) y los sinónimos de `adaptador_formatos.py` son diccionarios
    editables. Un cliente que numere su plan de cuentas distinto o nombre sus
    renglones de otra forma se resuelve agregando términos — sin tocar lógica,
    y por lo tanto sin poder romperle nada a los demás clientes.

 4. LA FORMA CANÓNICA ES LA FRONTERA. `CUENTAS_CANONICO` y `SALDOS_CANONICO`
    (abajo) son el contrato: nada fuera del conector conoce nombres de campo de
    ningún ERP. Un cliente con otro ERP entra escribiendo un conector nuevo, y
    todo el análisis financiero funciona sin enterarse.

 5. EL AISLAMIENTO YA ES FÍSICO. Cada extracción produce sus propios archivos y
    su propio snapshot. No hay estado global compartido entre empresas que
    obligue a inventar un filtrado por cliente más adelante — el punto donde
    estas cosas suelen filtrarse entre inquilinos.

Dicho en corto: aquí no se construye tenancy, se construye para que la tenancy
de HopDesk pueda ponerse encima sin abrir el código de negocio.

-------------------------------------------------------------------------------
 LA REGLA QUE SOSTIENE TODO: LA FORMA CANÓNICA
-------------------------------------------------------------------------------
Un conector nuevo implementa UNA función obligatoria: `fn_homologar`, que
traduce la respuesta cruda de SU ERP a la forma canónica de más abajo. Nada
del resto del sistema conoce los nombres de campo de ningún ERP — ni ahora ni
cuando entre el segundo. Si un conector "necesita" una columna nueva que los
demás no tienen, es señal de que el modelo canónico está incompleto, no de que
ese ERP sea especial: la columna se agrega aquí, para todos.

-------------------------------------------------------------------------------
 RESTRICCIÓN DE RED — NO ES UN DETALLE, ES ARQUITECTURA
-------------------------------------------------------------------------------
El SAP B1 de Networks vive en una IP privada (192.168.14.131:50000): solo se
alcanza desde la red corporativa o por VPN. Comprobado el 2026-09-24: sin VPN
el Login ni siquiera hace handshake (ConnectTimeout).

Consecuencia directa: **la app publicada en Connect Cloud NUNCA podrá hablarle
a SAP**, y no tiene caso intentarlo. La extracción corre en la máquina local
(con VPN), igual que `refrescar.py`, y su salida viaja a S3 para que el
tablero la lea. Es exactamente la misma arquitectura que ya usa la
facturación: pipeline local -> S3 -> tablero estático. Cualquier diseño que
suponga que el navegador del usuario puede consultar el ERP en vivo está mal
desde el principio.
===============================================================================
"""
from dataclasses import dataclass, field
from typing import Callable, List, Dict, Optional


# ---------------------------------------------------------------------------
# FORMA CANÓNICA — lo que todo conector debe producir, se llame como se llame
# en su ERP de origen.
# ---------------------------------------------------------------------------
CUENTAS_CANONICO = {
    'codigo':        'Código de la cuenta contable, tal como lo usa el ERP.',
    'nombre':        'Nombre de la cuenta.',
    'clase':         "Una de: ACTIVO, PASIVO, CAPITAL, INGRESO, COSTO, GASTO, OTRO. "
                     "Es la clasificación que decide en qué estado financiero cae la cuenta.",
    'nivel':         'Nivel jerárquico (1 = mayor). Sirve para presentar el estado resumido o a detalle.',
    'cuenta_padre':  'Código de la cuenta de nivel superior; vacío si es raíz.',
    'es_acumulativa': 'True si es cuenta de título/acumulación (no recibe movimientos directos).',
    'moneda':        'Moneda de la cuenta.',
    'activa':        'True si la cuenta está activa en el ERP.',
}

FACTURAS_CANONICO = {
    'empresa':      'Iniciales de la empresa emisora/receptora.',
    'tipo':         "'venta' (facturas a clientes) o 'compra' (facturas de proveedores).",
    'folio':        'Número de documento del ERP (DocNum). No es el folio fiscal.',
    'fecha':        'Fecha del documento (ISO). Es la contable, no la de captura.',
    'anio':         'Año de la fecha del documento.',
    'mes':          'Mes de la fecha del documento.',
    'contraparte':  'Cliente o proveedor (nombre).',
    'contraparte_id': 'Código del socio de negocios en el ERP.',
    'rfc':          'Registro fiscal de la contraparte, si el ERP lo tiene.',
    'subtotal':     'Importe antes de impuestos, en la moneda del documento.',
    'impuestos':    'IVA y demás impuestos del documento.',
    'total':        'Importe total del documento.',
    'moneda':       "Moneda del documento tal como la nombra el ERP (ojo: aquí el peso es 'MXP', no 'MXN').",
    'tipo_cambio':  'Tipo de cambio aplicado por el ERP al documento.',
    'total_local':  'Total convertido a moneda local por el ERP.',
    'cancelada':    'True si el documento está cancelado. CRÍTICO: ver la nota de abajo.',
    'estatus':      'Estado del documento en el ERP (abierto/cerrado).',
    'fecha_registro': 'Cuándo se CAPTURÓ el documento, que no es lo mismo que su fecha contable. '
                      'Es lo que permite medir días de cierre y detectar capturas retroactivas.',
}
# POR QUÉ `cancelada` NO ES UN CAMPO MÁS: en NG, 16 de 595 facturas están
# canceladas. Sumarlas infla las ventas y el número resultante no coincide con
# nada — ni con el Excel de facturación, ni con la contabilidad, ni con lo que
# recuerda quien factura. Se extraen SIEMPRE (una factura cancelada es un hecho
# que existió y a veces hay que explicarlo), pero quien sume tiene que decidir
# explícitamente si las incluye. Por eso el campo viaja en la forma canónica en
# vez de filtrarse durante la extracción: filtrar aquí escondería la decisión.

SALDOS_CANONICO = {
    'codigo':        'Código de cuenta; llave contra el catálogo.',
    'anio':          'Año del periodo.',
    'mes':           'Mes del periodo (1-12).',
    'saldo_inicial': 'Saldo al inicio del mes.',
    'debe':          'Sumatoria de cargos del mes.',
    'haber':         'Sumatoria de abonos del mes.',
    'saldo_final':   'Saldo al cierre del mes. Es el que alimenta el Balance.',
    'empresa':       'Iniciales de la empresa, tal como se dieron de alta en la '
                         'configuración del cliente.',
}

# Clases canónicas y a qué estado financiero pertenece cada una.
CLASES = {
    'ACTIVO':  'balance',
    'PASIVO':  'balance',
    'CAPITAL': 'balance',
    'INGRESO': 'resultados',
    'COSTO':   'resultados',
    'GASTO':   'resultados',
    'OTRO':    'sin_clasificar',   # se reporta, nunca se esconde
}


@dataclass
class Capacidades:
    """Qué puede entregar de verdad este conector. Declararlo por adelantado
    evita descubrir a media extracción que falta la mitad del Balance."""
    catalogo_cuentas: bool = False
    saldos_por_periodo: bool = False
    polizas_detalle: bool = False        # asientos línea por línea
    facturas_ar: bool = False
    facturas_ap: bool = False
    multiempresa: bool = False           # una conexión por empresa del grupo
    taxonomia_flujo_nativa: bool = False # el ERP ya trae clasificación de flujo de efectivo

    def faltantes_para_estados_financieros(self) -> List[str]:
        faltan = []
        if not self.catalogo_cuentas:
            faltan.append('catálogo de cuentas')
        if not self.saldos_por_periodo and not self.polizas_detalle:
            faltan.append('saldos por periodo (o pólizas para derivarlos)')
        return faltan


@dataclass
class Campo:
    nombre: str
    etiqueta: str
    tipo: str = 'texto'          # texto | password | checkbox
    requerido: bool = True
    ayuda: str = ''


@dataclass
class ConectorERP:
    tipo: str
    etiqueta: str
    campos_config: List[Campo]        # no secretos
    campos_secretos: List[Campo]      # se guardan cifrados / en .env, nunca en el repo
    capacidades: Capacidades
    fn_probar: Optional[Callable] = None      # prueba de conexión en vivo
    fn_homologar: Optional[Callable] = None   # crudo -> forma canónica  (OBLIGATORIA)
    notas: str = ''


# ---------------------------------------------------------------------------
# REGISTRO
# ---------------------------------------------------------------------------
REGISTRO: Dict[str, ConectorERP] = {}


def registrar(conector: ConectorERP):
    REGISTRO[conector.tipo] = conector
    return conector


def tipos_disponibles() -> List[str]:
    return list(REGISTRO.keys())


def obtener(tipo: str) -> ConectorERP:
    c = REGISTRO.get(tipo)
    if c is None:
        raise KeyError(f'Conector ERP no registrado: {tipo!r}. '
                       f'Registrados: {", ".join(tipos_disponibles()) or "ninguno"}')
    return c


# --- Registro del único conector implementado hoy ---------------------------
# Se importa al final para evitar import circular: sap_b1 importa este módulo.
SAP_B1 = 'sap_b1_service_layer'


def _registrar_sap_b1():
    # Import tolerante: funciona tanto como paquete (-m finanzas.erp.…) como
    # corriendo el script directo desde la carpeta erp/.
    try:
        from . import sap_b1
    except ImportError:
        import sap_b1
    registrar(ConectorERP(
        tipo=SAP_B1,
        etiqueta='SAP Business One — Service Layer',
        campos_config=[
            Campo('url', 'URL del Service Layer', ayuda='ej. https://servidor:50000/b1s/v1'),
            Campo('company', 'Base de datos de la compañía (CompanyDB)'),
            Campo('ssl_verify', 'Verificar certificado SSL', tipo='checkbox', requerido=False,
                  ayuda='En servidores on-premise con certificado autofirmado suele ir en falso.'),
        ],
        campos_secretos=[
            Campo('user', 'Usuario'),
            Campo('password', 'Contraseña', tipo='password'),
        ],
        capacidades=Capacidades(
            catalogo_cuentas=True,
            saldos_por_periodo=False,   # no hay endpoint directo: se derivan de JournalEntries
            polizas_detalle=True,
            facturas_ar=True,
            facturas_ap=True,
            multiempresa=True,          # una CompanyDB por empresa del grupo
            taxonomia_flujo_nativa=True,  # CashFlowLineItem existe en el esquema; falta confirmar si está configurada
        ),
        fn_probar=sap_b1.probar_conexion,
        fn_homologar=sap_b1.homologar,
        notas=(
            'Mismo servidor y mismas credenciales que usa HopDesk (se leen de su .Renviron). '
            'Los saldos por periodo NO tienen endpoint propio en el Service Layer: se '
            'construyen sumando JournalEntries por cuenta y mes. Por eso el permiso de '
            'lectura sobre JournalEntries es indispensable y no opcional.'
        ),
    ))


def inicializar():
    """Llamar una vez al arrancar. Separado del import para que el registro
    se pueda leer (formularios, capacidades) sin cargar clientes HTTP."""
    if SAP_B1 not in REGISTRO:
        _registrar_sap_b1()
    return REGISTRO


# ---------------------------------------------------------------------------
# Cómo se agrega un ERP nuevo (NO se implementa ninguno hoy, por instrucción)
# ---------------------------------------------------------------------------
COMO_AGREGAR_UN_ERP = """
1. Crear finanzas/erp/<nombre>.py con, como mínimo:
      probar_conexion(config, secretos) -> (ok: bool, mensaje: str)
      homologar(crudo, que: str)        -> lista de dicts en forma canónica
   donde `que` es 'cuentas' o 'saldos'.

2. Registrarlo aquí con registrar(ConectorERP(...)), declarando con honestidad
   sus `capacidades`: si ese ERP no entrega catálogo de cuentas, se declara
   False y el orquestador lo dirá de frente en vez de producir un Balance
   incompleto sin avisar.

3. NO tocar nada más. Si hace falta modificar el análisis o el tablero para
   que "funcione" con el ERP nuevo, es que la homologación quedó a medias: el
   análisis solo conoce la forma canónica.

Lo que NO hay que hacer: agregar columnas propias de un ERP a la forma
canónica "porque solo ese las tiene". Si un dato es valioso, se agrega al
canon para todos, con su valor vacío en los que no lo tengan.
"""
