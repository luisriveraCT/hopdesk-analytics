# -*- coding: utf-8 -*-
"""
===============================================================================
 MODELO DE CONFIGURACIÓN — clientes, empresas, conectores y retención
===============================================================================
QUÉ ES ESTO Y QUÉ NO ES
-----------------------
Es la **configuración** de la aplicación: qué clientes existen, qué empresas
tiene cada uno, con qué ERP se conecta cada empresa y cuánta historia se guarda.

NO es un sistema de identidad. Aquí no hay contraseñas de personas, ni sesiones,
ni login. Esa separación es deliberada y es la lección principal de la auditoría
al sistema anterior: mezclar identidad con configuración produjo 8,400 líneas
donde la autorización se decidía en once lugares distintos. Quien construya
encima de esto: **si estás a punto de agregar un usuario aquí, párate.**

LAS TRES REGLAS QUE SOSTIENEN TODO
----------------------------------
 1. **NADA CABLEADO, EMPEZANDO POR EL ERP.** Que el cliente use SAP Business One
    es un dato de configuración, no una suposición del código. Un cliente con
    Odoo, CONTPAQi o lo que sea se da de alta cambiando `conector`, sin tocar
    una línea. Por eso no verás la palabra "SAP" en ninguna decisión de este
    archivo — solo como valor de ejemplo en los datos semilla.

 2. **UN PERMISO QUE NO SE VERIFICA NO EXISTE.** En el sistema anterior, 16 de
    20 permisos se mostraban en la interfaz, se guardaban en disco, y no se
    consultaban en ningún `if`. Eso es peor que no tenerlos: da una sensación de
    control que no corresponde a nada. Aquí, si un permiso no tiene código que
    lo verifique, no se declara.

 3. **LA IDENTIDAD DEL CLIENTE ES UN UUID, NO SU NOMBRE.** La carpeta se llama
    `clientes/7f3a9c12.../`, no `clientes/networks/`. Si el cliente se renombra,
    se fusiona con otro o cambia de razón social, no hay que mover un solo
    archivo. El nombre legible vive dentro de la configuración, donde se puede
    editar sin consecuencias.

VALIDACIÓN
----------
Todo lo que entra se valida al construirse y truena fuerte si está mal. En el
sistema anterior se podía crear un usuario con nombre vacío (el generador hacía
`gsub` sobre el nombre y si eran puros símbolos quedaba ""), y se guardaba sin
protestar. Un dato inválido que se guarda en silencio reaparece semanas después
como un error incomprensible en otra parte.
===============================================================================
"""
import re
import uuid
import datetime as dt
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

# Cuántos años de historia se guardan por defecto. El usuario lo cambia desde la
# configuración, hacia arriba o hacia abajo, o lo pone en TODO.
RETENCION_DEFAULT_ANIOS = 7
RETENCION_TODO = 'todo'

# RFC mexicano: 3 letras (moral) o 4 (física), fecha, homoclave.
_RFC = re.compile(r'^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$')
# Iniciales: lo que la gente usa para referirse a la empresa en el día a día.
_INICIALES = re.compile(r'^[A-Z0-9]{2,8}$')


class ErrorConfiguracion(ValueError):
    """Se levanta cuando un dato de configuración no es válido.

    Es una excepción propia y no un ValueError pelón para que quien llame pueda
    distinguir "el usuario capturó algo mal" (se le muestra y se le pide
    corregir) de "el programa tiene un bug" (se registra y se investiga).
    """


def _hoy() -> str:
    return dt.datetime.now().isoformat(timespec='seconds')


def nuevo_id() -> str:
    """Identificador opaco. Sin significado a propósito: un identificador que
    describe lo que nombra obliga a renombrarlo cuando la realidad cambia."""
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Empresa
# ---------------------------------------------------------------------------
@dataclass
class Empresa:
    """Una entidad legal del cliente.

    `iniciales` es la llave con la que el resto del sistema se refiere a ella, y
    **es local al cliente**: dos clientes distintos pueden tener ambos una
    empresa "NG" sin pisarse, porque toda ruta y toda caché llevan el id del
    cliente adelante. En el sistema anterior las sesiones de ERP se guardaban en
    un diccionario global indexado solo por iniciales, así que dos clientes con
    las mismas iniciales compartían sesión. Ese error se evita aquí por
    construcción, no por cuidado.
    """
    iniciales: str
    nombre: str
    rfc: str = ''
    # Referencia a la conexión ERP que atiende a esta empresa. Vacío = la
    # empresa existe en el sistema pero todavía no está conectada a ningún ERP,
    # que es exactamente el estado de Paragon Logistics hoy.
    conexion_id: str = ''
    # Identificador de la empresa DENTRO del ERP (en SAP B1 es la CompanyDB; en
    # otro ERP será otra cosa). Se guarda como texto libre a propósito: el
    # modelo no debe saber qué forma tiene el identificador de cada ERP.
    id_en_erp: str = ''
    activa: bool = True
    notas: str = ''

    # ----- Registro intercompañía -------------------------------------------
    # Con qué identificadores aparece ESTA empresa cuando es la contraparte en
    # los libros de las otras. Es el mismo patrón que usa HopDesk (`interco_v2`,
    # que guarda RFCs y CardCodes): la pertenencia al grupo es un DATO
    # CONFIGURADO, no una deducción del nombre.
    #
    # Importa que sea configurado y no adivinado: detectar por nombre falla en
    # los dos sentidos. Se pierde a la empresa cuando el maestro trae el nombre
    # escrito distinto, y se cuela un tercero que se llame parecido. Ninguno de
    # los dos errores se nota: solo mueve el porcentaje de intercompañía, que es
    # justo lo que nadie puede verificar de memoria.
    #
    # `rfcs_alternos` existe porque el maestro de socios de SAP tiene erratas
    # reales: en Networks conviven NRE08091519A y NRE080915I9A (un 1 donde va
    # una I) para la misma empresa. Corregirlas en el ERP es lo correcto;
    # mientras tanto, reconocerlas evita perder facturas.
    #
    # `codigos_erp` son los CardCodes. Cambian de un libro a otro —cada base de
    # datos tiene su propio catálogo de socios— así que una misma empresa tiene
    # varios. Se llenan solos con `configurar.py --detectar-interco`.
    rfcs_alternos: List[str] = field(default_factory=list)
    codigos_erp: List[str] = field(default_factory=list)

    def identificadores_interco(self) -> set:
        """Todo lo que identifica a esta empresa como contraparte."""
        ids = {self.rfc.upper()} if self.rfc else set()
        ids |= {r.strip().upper() for r in self.rfcs_alternos if r.strip()}
        ids |= {c.strip().upper() for c in self.codigos_erp if c.strip()}
        return ids

    def __post_init__(self):
        self.iniciales = (self.iniciales or '').strip().upper()
        self.nombre = (self.nombre or '').strip()
        self.rfc = (self.rfc or '').strip().upper()
        if not _INICIALES.match(self.iniciales):
            raise ErrorConfiguracion(
                f'Iniciales inválidas: {self.iniciales!r}. Se esperan de 2 a 8 '
                f'letras o dígitos, por ejemplo "NG" o "PL".')
        if not self.nombre:
            raise ErrorConfiguracion(
                f'La empresa {self.iniciales} necesita nombre o razón social.')
        # El RFC es opcional (puede no conocerse al dar de alta), pero si se
        # captura tiene que ser válido. Aceptar un RFC mal formado "por no
        # estorbar" garantiza descubrirlo el día que se emita un documento.
        if self.rfc and not _RFC.match(self.rfc):
            raise ErrorConfiguracion(
                f'RFC inválido para {self.iniciales}: {self.rfc!r}. '
                f'Formato esperado: 3 o 4 letras, 6 dígitos de fecha y 3 de '
                f'homoclave (ejemplo: ABC010203XY4).')


# ---------------------------------------------------------------------------
# Conexión a un ERP
# ---------------------------------------------------------------------------
@dataclass
class ConexionERP:
    """Cómo se llega al ERP de un cliente.

    `conector` es el identificador del tipo de ERP, tal como lo registra
    `erp/registro_conectores.py`. El modelo no valida que sea SAP ni ningún otro:
    valida que exista un conector registrado con ese nombre. Así, agregar
    soporte para otro ERP es registrar un conector — nunca editar este archivo.

    `secretos_ref` NO contiene las credenciales: contiene una referencia a dónde
    están. Las credenciales viven cifradas en el almacén de secretos. Esta
    separación es lo que permite publicar la configuración (para que la
    aplicación muestre qué ERP y qué empresas hay) sin publicar jamás una
    contraseña.
    """
    id: str = field(default_factory=nuevo_id)
    nombre: str = ''                 # cómo lo llama el usuario: "SAP producción"
    conector: str = ''               # p.ej. 'sap_b1_service_layer'
    version: str = ''                # versión del ERP, informativa
    # Parámetros NO secretos del conector (url, puerto, verificar ssl...). Las
    # claves permitidas las declara el conector, no este archivo.
    parametros: Dict[str, Any] = field(default_factory=dict)
    secretos_ref: str = ''           # llave en el almacén de secretos
    activa: bool = True
    creada: str = field(default_factory=_hoy)

    def __post_init__(self):
        self.nombre = (self.nombre or '').strip()
        self.conector = (self.conector or '').strip()
        if not self.conector:
            raise ErrorConfiguracion(
                'La conexión necesita un conector. Los disponibles los declara '
                'el registro de conectores; si el que buscas no está, se agrega '
                'ahí — no se cablea aquí.')
        if not self.nombre:
            self.nombre = self.conector
        if not self.secretos_ref:
            self.secretos_ref = f'conexion/{self.id}'


# ---------------------------------------------------------------------------
# Retención de historia
# ---------------------------------------------------------------------------
@dataclass
class Retencion:
    """Cuánta historia se conserva en la nube para este cliente.

    Por defecto siete años. El usuario puede subirlo, bajarlo, o pedir TODO.
    Se guarda como configuración y no como constante porque el volumen tiene
    costo y cada cliente decide el suyo: para uno, tres años es de sobra; para
    otro, tirar un solo ejercicio es inaceptable por una revisión fiscal.
    """
    anios: Any = RETENCION_DEFAULT_ANIOS   # int, o la cadena 'todo'

    def __post_init__(self):
        v = self.anios
        if isinstance(v, str) and v.strip().lower() in (RETENCION_TODO, 'all'):
            self.anios = RETENCION_TODO
            return
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise ErrorConfiguracion(
                f'Retención inválida: {v!r}. Debe ser un número de años o '
                f'"{RETENCION_TODO}".')
        if n < 1:
            raise ErrorConfiguracion(
                'La retención no puede ser menor a un año. Si la intención es '
                'no guardar historia, lo que se desactiva es la extracción, no '
                'la retención — y conviene que esa decisión sea explícita.')
        self.anios = n

    def anio_minimo(self, hoy: Optional[dt.date] = None) -> Optional[int]:
        """Primer año que se conserva. `None` significa que se conserva todo."""
        if self.anios == RETENCION_TODO:
            return None
        hoy = hoy or dt.date.today()
        return hoy.year - int(self.anios) + 1


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------
@dataclass
class PoliticaFinanciera:
    """Los números que el cliente decide, no que se calculan.

    Dos grupos, con orígenes muy distintos y por eso separados:

    `supuestos` son las entradas del costo de capital que NO salen del ERP.
    Networks es una empresa privada: no tiene precio de acción del que sacar una
    beta ni una cotización de deuda pública. La beta y la prima de mercado son
    juicios, y aquí se guardan como tales —con su `fuente`— en vez de aparecer
    como si el sistema los hubiera calculado. La tasa libre de riesgo sí es
    observable (Banxico) y la tasa efectiva de impuestos sale del ERP: cuando
    están disponibles ganan sobre lo capturado aquí.

    `metas` son los objetivos contra los que se pinta el semáforo. Vivían como
    constantes en el código, lo cual funcionaba mientras hubiera un solo
    cliente. Las claves válidas son las de `razones_financieras.CATALOGO_KPIS`;
    una meta ausente simplemente deja ese indicador sin semáforo, que es mejor
    que compararlo contra la meta de alguien más.
    """
    supuestos: Dict[str, float] = field(default_factory=dict)
    metas: Dict[str, float] = field(default_factory=dict)
    # De dónde salió cada supuesto, para que quien lea el WACC sepa qué parte es
    # observada y qué parte es juicio. Texto libre: es para leerse, no para que
    # el código decida con ello.
    fuentes: Dict[str, str] = field(default_factory=dict)
    # Convenciones de cálculo que no las fija ninguna norma contable: son
    # decisiones analíticas del cliente. Las razones de días son el caso claro —
    # ni IFRS ni las NIF dicen contra qué base se miden los días de pago, porque
    # no son cifras del estado financiero sino lecturas sobre él.
    #
    # Valores admitidos hoy:
    #   base_dias_pago = 'costo_de_ventas'          el clásico
    #                  | 'costos_operativos_efectivo'  costo + gastos − D&A
    #
    # El segundo existe porque en un grupo que registra el costo directo como
    # gasto de operación, el primero divide entre un número casi cero y produce
    # días de pago en los cientos. Cuál aplica depende de cómo esté armado el
    # plan de cuentas del cliente, así que es configuración.
    convenciones: Dict[str, str] = field(default_factory=dict)
    # Términos extra para reconocer rubros del balance en el catálogo de este
    # cliente: {rubro: [términos]}. Se AGREGAN a los de fábrica, no los
    # reemplazan.
    #
    # Existe porque el vocabulario de fábrica no puede cubrir todas las formas
    # de nombrar una cuenta. Un catálogo que llame "Disponibilidades" a la caja
    # no coincide con nada, y el fallo es mudo: el rubro sale vacío y con él las
    # razones que dependen de él. Nadie revisa un indicador que nunca tuvo
    # valor.
    vocabulario_rubros: Dict[str, List[str]] = field(default_factory=dict)

    def __post_init__(self):
        for campo in ('supuestos', 'metas'):
            d = getattr(self, campo)
            for k, v in list(d.items()):
                if v is None:
                    del d[k]
                    continue
                try:
                    d[k] = float(v)
                except (TypeError, ValueError):
                    raise ErrorConfiguracion(
                        f'La política financiera tiene un valor no numérico en '
                        f'{campo}[{k!r}]: {v!r}.')


@dataclass
class Cliente:
    """Un grupo empresarial. La unidad de aislamiento del sistema.

    Todo lo del cliente vive bajo `clientes/<id>/` y nada cruza esa frontera.
    """
    id: str = field(default_factory=nuevo_id)
    nombre: str = ''
    empresas: List[Empresa] = field(default_factory=list)
    conexiones: List[ConexionERP] = field(default_factory=list)
    retencion: Retencion = field(default_factory=Retencion)
    politica: PoliticaFinanciera = field(default_factory=PoliticaFinanciera)
    # Marco contable bajo el que se presentan los estados. Decide cosas como
    # qué entra al EBITDA. Vive aquí y no en el código porque es una decisión
    # del contador del cliente, no del programador: el siguiente cliente puede
    # reportar bajo otro marco y no debería necesitar que alguien edite nada.
    # Las claves válidas las registra `normas_contables.NORMAS`.
    normas: str = 'ifrs_nif'
    activo: bool = True
    creado: str = field(default_factory=_hoy)
    actualizado: str = field(default_factory=_hoy)

    def __post_init__(self):
        self.nombre = (self.nombre or '').strip()
        if not self.nombre:
            raise ErrorConfiguracion('El cliente necesita un nombre.')
        vistas = set()
        for e in self.empresas:
            if e.iniciales in vistas:
                raise ErrorConfiguracion(
                    f'La empresa {e.iniciales} está dos veces en {self.nombre}. '
                    f'Las iniciales identifican a la empresa dentro del cliente '
                    f'y tienen que ser únicas.')
            vistas.add(e.iniciales)
        ids = {c.id for c in self.conexiones}
        for e in self.empresas:
            if e.conexion_id and e.conexion_id not in ids:
                raise ErrorConfiguracion(
                    f'La empresa {e.iniciales} apunta a una conexión que no '
                    f'existe ({e.conexion_id}). Una referencia rota aquí se '
                    f'traduce en una extracción que falla sin explicar por qué.')

    # -- consultas ---------------------------------------------------------
    def empresa(self, iniciales: str) -> Optional[Empresa]:
        ini = (iniciales or '').strip().upper()
        return next((e for e in self.empresas if e.iniciales == ini), None)

    def conexion(self, conexion_id: str) -> Optional[ConexionERP]:
        return next((c for c in self.conexiones if c.id == conexion_id), None)

    def conexion_de(self, iniciales: str) -> Optional[ConexionERP]:
        e = self.empresa(iniciales)
        return self.conexion(e.conexion_id) if e and e.conexion_id else None

    def empresas_conectadas(self) -> List[Empresa]:
        """Las que sí se pueden extraer hoy. Las demás existen en el sistema
        pero todavía no tienen ERP — y se reportan como tales en vez de
        desaparecer del listado, que es como se pierde el rastro de una empresa
        pendiente de dar de alta."""
        return [e for e in self.empresas if e.activa and e.conexion_id]

    def empresas_sin_conectar(self) -> List[Empresa]:
        return [e for e in self.empresas if e.activa and not e.conexion_id]

    def mapa_interco(self) -> Dict[str, str]:
        """identificador (RFC o CardCode, en mayúsculas) → iniciales de la empresa.

        Es LA fuente de la clasificación intercompañía. Quien necesite saber si
        una contraparte es del grupo pregunta aquí y no inventa su propio
        criterio — que es como se acaba con dos porcentajes de intercompañía
        distintos en dos pantallas de la misma aplicación.
        """
        mapa = {}
        for e in self.empresas:
            for ident in e.identificadores_interco():
                mapa[ident] = e.iniciales
        return mapa

    # -- serialización -----------------------------------------------------
    def a_dict(self, incluir_secretos_ref: bool = True) -> Dict:
        d = asdict(self)
        if not incluir_secretos_ref:
            # Lo que se publica para que la aplicación muestre la configuración
            # no necesita ni siquiera la referencia al secreto.
            for c in d['conexiones']:
                c.pop('secretos_ref', None)
        return d

    @staticmethod
    def de_dict(d: Dict) -> 'Cliente':
        return Cliente(
            id=d.get('id') or nuevo_id(),
            nombre=d.get('nombre', ''),
            empresas=[Empresa(**e) for e in d.get('empresas', [])],
            conexiones=[ConexionERP(**c) for c in d.get('conexiones', [])],
            retencion=Retencion(**(d.get('retencion') or {})),
            politica=PoliticaFinanciera(**(d.get('politica') or {})),
            normas=d.get('normas') or 'ifrs_nif',
            activo=d.get('activo', True),
            creado=d.get('creado') or _hoy(),
            actualizado=d.get('actualizado') or _hoy(),
        )

    def prefijo_s3(self) -> str:
        """La única función que construye la ruta del cliente.

        Existe una sola vez a propósito. En el sistema anterior había una
        función centralizada para esto y aun así la ruta se armaba a mano con
        `paste0` en más de veinte lugares, porque la centralizada no servía para
        el caso cross-cliente. Aquí la función recibe el cliente como argumento
        —no lo lee de una variable de entorno— así que sirve para todos los
        casos y no hay motivo para replicarla.
        """
        return f'clientes/{self.id}'
