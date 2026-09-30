# -*- coding: utf-8 -*-
"""
===============================================================================
 CONECTOR SAP BUSINESS ONE — Service Layer
===============================================================================
Único conector implementado. Replica el patrón que ya usa HopDesk en
`R/sap_api.R`, con las mismas credenciales y el mismo servidor:

  · Resolución de credenciales en cascada: variables de entorno del proceso ->
    el .Renviron de HopDesk -> archivo .env local. Así no se duplican secretos:
    si ya están configurados para HopDesk, esto los reusa tal cual.
  · Login por sesión (POST /Login con CompanyDB/UserName/Password), sesión
    reutilizada mientras dure la extracción, Logout al final.
  · Paginación OData: el Service Layer corta en 20 filas por default y expone
    la siguiente página en @odata.nextLink. Ignorar eso es el error clásico
    que hace que un catálogo de 800 cuentas "traiga" 20 y nadie lo note.

LO QUE ESTE CONECTOR NO HACE, A PROPÓSITO:
  · No escribe nada en SAP. Todas las llamadas son GET salvo Login/Logout.
  · No inventa clasificaciones. Si una cuenta de SAP no cae en el mapeo de
    clases, se marca como OTRO y se reporta — nunca se acomoda "por parecido"
    para que el Balance cuadre visualmente.
===============================================================================
"""
import os
import sys
import json
import re
import time
from typing import Dict, List, Tuple, Optional

try:
    import requests
    import urllib3
    urllib3.disable_warnings()
except ImportError:
    requests = None

RENVIRON_HOPDESK = r'C:\Users\luisr\Antiguedad_App\.Renviron'

# Empresas del grupo. Ojo con las iniciales: HopDesk usa NRS para Networks
# Realtors, mientras que la base de facturación usa NR. Se mapea aquí para que
# los dos mundos se puedan cruzar sin que nadie tenga que acordarse.
# =============================================================================
# QUÉ EMPRESAS HAY: SALE DE LA CONFIGURACIÓN, NO DE AQUÍ
# =============================================================================
# Hasta el 2026-09-25 este archivo tenía escritas las cinco empresas de Networks
# y sus iniciales. Funcionaba, y era exactamente el tipo de atajo que impide que
# un segundo cliente use esto sin que alguien edite código.
#
# También había un `INICIALES_SAP_A_FACTURACION` que traducía NRS→NR para
# empatar con los archivos de Excel. Ese Excel se retiró: el mapeo se eliminó
# porque ya no traduce a nada.
#
# Ahora las empresas, su base de datos en el ERP y sus credenciales salen del
# cliente configurado. Lo único que queda aquí es cómo se habla con SAP.
def _repo():
    import importlib
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ruta = os.path.join(base, 'configuracion')
    if ruta not in sys.path:
        sys.path.insert(0, ruta)
    return importlib.import_module('repositorio')


def cliente_configurado():
    """El cliente sobre el que trabaja esta instalación."""
    repo = _repo()
    return repo.cliente_actual(repo.almacen_por_defecto())


def empresas_con_erp(cliente=None) -> List[str]:
    """Iniciales de las empresas que SÍ se pueden extraer.

    Antes era una lista literal. Ahora son las empresas activas del cliente que
    tienen conexión a un ERP y un identificador dentro de él.
    """
    c = cliente or cliente_configurado()
    return [e.iniciales for e in c.empresas_conectadas() if e.id_en_erp]


def empresas_sin_erp(cliente=None) -> List[str]:
    """Las dadas de alta que todavía no tienen ERP. Se reportan en vez de
    desaparecer del listado: una empresa pendiente que nadie ve es una empresa
    que se olvida."""
    c = cliente or cliente_configurado()
    return [e.iniciales for e in c.empresas_sin_conectar()]


# ---------------------------------------------------------------------------
# Credenciales
# ---------------------------------------------------------------------------
def _leer_renviron(path: str) -> Dict[str, str]:
    env = {}
    if not os.path.isfile(path):
        return env
    with open(path, encoding='utf-8-sig', errors='ignore') as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith('#') or '=' not in linea:
                continue
            k, v = linea.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def credenciales(iniciales: str) -> Tuple[Dict, Dict, str]:
    """Regresa (config, secretos, fuente).

    PRIMERO LA CONFIGURACIÓN DEL CLIENTE. La empresa dice de qué conexión cuelga
    y cuál es su base de datos en el ERP; la conexión dice la URL y sus
    parámetros; el almacén cifrado da usuario y contraseña. Nada de esto se
    deduce de una convención de nombres.

    Después, y solo si la configuración no lo resuelve, la cascada de variables
    de entorno `SAP_<INICIALES>_*` que se usaba antes. Se conserva para poder
    arrancar en una máquina sin configurar todavía, y porque es de donde salió
    la carga inicial — pero es el respaldo, no la fuente.

    La fuente usada viaja en el tercer valor de retorno a propósito: cuando algo
    falla, la primera pregunta útil es de dónde salieron las credenciales.
    """
    ini = iniciales.upper()
    try:
        cliente = cliente_configurado()
        emp = cliente.empresa(ini)
        cx = cliente.conexion_de(ini) if emp else None
        if emp and cx and emp.id_en_erp:
            from secretos import AlmacenSecretos
            repo = _repo()
            sec = AlmacenSecretos(repo.almacen_por_defecto(), cliente.id)
            datos = sec.leer(f'{cx.id}/{ini}')
            return (
                {'url': str(cx.parametros.get('url', '')).rstrip('/'),
                 'company': emp.id_en_erp,
                 'ssl_verify': bool(cx.parametros.get('ssl_verify', True))},
                {'user': datos['usuario'], 'password': datos['contrasena']},
                'configuracion',
            )
    except Exception as e:
        # No se oculta: si la configuración existe pero está incompleta, hay que
        # enterarse. Se sigue al respaldo para no bloquear una máquina a medio
        # configurar, pero el motivo queda dicho.
        print(f'  aviso: la configuración no resolvió las credenciales de {ini} '
              f'({type(e).__name__}: {str(e)[:90]}); se intenta con el entorno.')

    pre = f'SAP_{ini}_'
    fuentes = [
        ('entorno', dict(os.environ)),
        ('renviron_hopdesk', _leer_renviron(RENVIRON_HOPDESK)),
        ('env_local', _leer_renviron(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))),
    ]
    for nombre, env in fuentes:
        url = env.get(pre + 'URL', '')
        company = env.get(pre + 'COMPANY', '')
        user = env.get(pre + 'USER', '')
        pwd = env.get(pre + 'PASSWORD', '')
        if all([url, company, user, pwd]):
            ssl_raw = str(env.get(pre + 'SSL_VERIFY', 'true')).strip().lower()
            return (
                {'url': url.rstrip('/'), 'company': company,
                 'ssl_verify': ssl_raw not in ('false', '0', 'no', 'f')},
                {'user': user, 'password': pwd},
                nombre,
            )
    raise RuntimeError(
        f'No hay credenciales SAP para {iniciales}. Se buscó SAP_{iniciales.upper()}_URL/'
        f'COMPANY/USER/PASSWORD en el entorno, en {RENVIRON_HOPDESK} y en erp/.env')


# ---------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------
class SesionSAP:
    """Sesión viva contra una CompanyDB. Usar como context manager para que el
    Logout ocurra aunque truene algo a media extracción."""

    def __init__(self, iniciales: str, timeout: int = 120):
        if requests is None:
            raise RuntimeError('Falta la librería requests: pip install requests')
        self.iniciales = iniciales.upper()
        self.config, self._secretos, self.fuente_credenciales = credenciales(self.iniciales)
        self.timeout = timeout
        self.s = requests.Session()
        self.s.verify = self.config['ssl_verify']
        self.conectado = False

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, *exc):
        self.logout()
        return False

    def login(self):
        r = self.s.post(f'{self.config["url"]}/Login', timeout=self.timeout, json={
            'CompanyDB': self.config['company'],
            'UserName': self._secretos['user'],
            'Password': self._secretos['password'],
        })
        if r.status_code != 200:
            raise RuntimeError(f'Login SAP falló para {self.iniciales}: HTTP {r.status_code} — '
                               f'{_mensaje_error(r)}')
        self.conectado = True

    def logout(self):
        if self.conectado:
            try:
                self.s.post(f'{self.config["url"]}/Logout', timeout=30)
            except Exception:
                pass
            self.conectado = False

    def contar(self, endpoint: str, filtro: Optional[str] = None) -> Optional[int]:
        """Total autoritativo de filas vía /$count. Se usa para comprobar que
        la descarga trajo TODO — ver la advertencia en get_todo()."""
        try:
            params = {'$filter': filtro} if filtro else None
            r = self.s.get(f'{self.config["url"]}/{endpoint}/$count',
                           params=params, timeout=self.timeout)
            if r.status_code != 200:
                return None
            return int(re.sub(r'[^0-9]', '', r.text.split()[-1]))
        except Exception:
            return None

    def get_todo(self, endpoint: str, select: Optional[List[str]] = None,
                 filtro: Optional[str] = None, orderby: Optional[str] = None,
                 pagina: int = 500, max_filas: Optional[int] = None,
                 verificar_total: bool = True) -> List[Dict]:
        """GET paginado con $skip explícito, y comprobación contra /$count.

        ────────────────────────────────────────────────────────────────────
        CUIDADO — ESTE SERVIDOR TRUNCA EN SILENCIO
        Comprobado el 2026-09-24 contra el SAP de Networks: este Service Layer
        NO devuelve `@odata.nextLink`. Con `odata.maxpagesize=200` regresa 200
        filas y nada más — sin señal alguna de que faltan datos — cuando
        /$count reporta 337. Un paginador que confíe en nextLink (que es lo
        que dice la documentación de OData) se queda con la primera página y
        entrega un catálogo incompleto sin un solo error.

        Por eso aquí se pagina con $skip a ciegas hasta que una página regrese
        menos filas que el tamaño pedido, y al final se contrasta contra
        /$count. Si no coinciden, se levanta la mano: mejor una excepción que
        un Estado de Resultados al que le faltan pólizas.
        ────────────────────────────────────────────────────────────────────
        """
        base = {}
        if select:
            base['$select'] = ','.join(select)
        if filtro:
            base['$filter'] = filtro
        if orderby:
            base['$orderby'] = orderby

        url = f'{self.config["url"]}/{endpoint}'
        headers = {'Prefer': f'odata.maxpagesize={pagina}'}
        filas: List[Dict] = []
        skip = 0
        while True:
            params = dict(base)
            if skip:
                params['$skip'] = skip
            r = self.s.get(url, params=params, headers=headers, timeout=self.timeout)
            if r.status_code != 200:
                raise PermissionError(f'{endpoint}: HTTP {r.status_code} — {_mensaje_error(r)}')
            lote = r.json().get('value', [])
            filas.extend(lote)
            if max_filas and len(filas) >= max_filas:
                return filas[:max_filas]
            if len(lote) < pagina:
                break                      # última página
            skip += len(lote)
            if skip > 2_000_000:
                raise RuntimeError(f'{endpoint}: demasiadas filas, posible bucle')

        # Comprobación de integridad SOLO en descargas sin filtro.
        # Se midió contra este servidor: /$count es correcto sin filtro
        # (ChartOfAccounts -> 337, exacto), pero con $filter devuelve basura
        # (JournalEntries de un mes con 138 filas reales reportó 2). Aplicarlo
        # ahí tumbaba descargas buenas. La integridad de las consultas
        # filtradas ya la garantiza la paginación por $skip, que solo se
        # detiene cuando una página viene incompleta.
        if verificar_total and not max_filas and not filtro:
            total = self.contar(endpoint)
            if total and total > 0 and total != len(filas):
                raise RuntimeError(
                    f'{endpoint}: descarga incompleta — se bajaron {len(filas):,} filas pero '
                    f'el servidor reporta {total:,}. No se continúa con datos parciales.')
        return filas


def _mensaje_error(r) -> str:
    try:
        j = r.json()
        err = j.get('error', {})
        msg = err.get('message')
        if isinstance(msg, dict):
            msg = msg.get('value')
        return f'SAP code={err.get("code")} · {msg}'
    except Exception:
        return (r.text or '')[:200].replace('\n', ' ')


# ---------------------------------------------------------------------------
# Prueba de conexión y permisos (la que usa el registro)
# ---------------------------------------------------------------------------
ENDPOINTS_REQUERIDOS = {
    'ChartOfAccounts': 'catálogo de cuentas — sin esto no hay Balance ni Estado de Resultados',
    'JournalEntries': 'pólizas — de aquí se derivan los saldos por mes',
}
ENDPOINTS_OPCIONALES = {
    'FinancialYears': 'ejercicios fiscales (ayuda a validar periodos)',
    'Invoices': 'facturas AR (control: HopDesk ya las lee)',
    'PurchaseInvoices': 'facturas AP (control)',
    'CashFlowLineItems': 'taxonomía nativa de flujo de efectivo de SAP',
}


def probar_conexion(iniciales: str = 'NG') -> Tuple[bool, str]:
    """Prueba rápida: ¿hay red, login y permisos de lectura contable?"""
    try:
        with SesionSAP(iniciales, timeout=40) as ses:
            faltan = []
            for ep in ENDPOINTS_REQUERIDOS:
                try:
                    ses.get_todo(ep, max_filas=1, pagina=1)
                except PermissionError as e:
                    faltan.append(f'{ep} ({e})')
            if faltan:
                return False, 'Login OK pero sin permiso de lectura en: ' + '; '.join(faltan)
            return True, f'Conexión y permisos contables OK ({iniciales})'
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


def diagnostico(iniciales: str = 'NG') -> Dict:
    """Radiografía completa de qué se puede leer. Es lo primero que hay que
    correr cuando algo no jala, y lo que hay que mandarle al equipo de SAP
    cuando falte un permiso: dice exactamente qué endpoint y con qué error."""
    salida = {'empresa': iniciales, 'red': None, 'login': None, 'endpoints': {}}
    try:
        ses = SesionSAP(iniciales, timeout=40)
    except Exception as e:
        salida['red'] = f'sin credenciales: {e}'
        return salida
    salida['servidor'] = ses.config['url']
    salida['company_db'] = ses.config['company']
    salida['fuente_credenciales'] = ses.fuente_credenciales
    try:
        ses.login()
        salida['red'] = 'ok'
        salida['login'] = 'ok'
    except Exception as e:
        txt = str(e)
        salida['red'] = 'sin alcance de red (¿falta VPN?)' if 'imeout' in txt or 'Max retries' in txt else 'ok'
        salida['login'] = txt[:300]
        return salida
    try:
        for ep, desc in {**ENDPOINTS_REQUERIDOS, **ENDPOINTS_OPCIONALES}.items():
            try:
                filas = ses.get_todo(ep, max_filas=1, pagina=1)
                salida['endpoints'][ep] = {'ok': True, 'desc': desc,
                                           'campos': list(filas[0].keys())[:8] if filas else []}
            except Exception as e:
                salida['endpoints'][ep] = {'ok': False, 'desc': desc, 'error': str(e)[:220]}
    finally:
        ses.logout()
    return salida


# ---------------------------------------------------------------------------
# Extracción + homologación
# ---------------------------------------------------------------------------
# SAP B1 no guarda "Activo/Pasivo/Capital" como tal: guarda AccountType
# (at_Revenues / at_Expenses / at_Other), que en este servidor sale `at_Other`
# en el 85% de las cuentas, y organiza el Balance por "cajones" (drawers) — que
# son, literalmente, las cuentas raíz del árbol.
#
# La clasificación NO vive aquí: vive en `clasificador_cuentas.py`, que lee el
# árbol del propio ERP y el nombre de cada raíz en español o inglés. Se sacó de
# este archivo a propósito, porque clasificar es contabilidad y no protocolo:
# sap_b1.py debe saber de OData y de nombres de campo, nada más.
#
# El mapeo por prefijo (1→ACTIVO … 6→GASTO) que vivía aquí se ELIMINÓ. Daba los
# resultados correctos en Networks por una coincidencia de numeración, no por
# leer el plan de cuentas: en el árbol real las cuentas 81*/82* (financieras)
# cuelgan del cajón 7 y las 91* (extraordinarias) del cajón 8. Ver el
# encabezado de `clasificador_cuentas.py` para el detalle verificado.
try:
    from . import clasificador_cuentas as clasif
except ImportError:                       # corriendo como script suelto
    import clasificador_cuentas as clasif

# Último informe de clasificación, para que el orquestador lo reporte sin tener
# que reclasificar. Se sobrescribe en cada homologar() de cuentas.
ULTIMO_INFORME_CLASIFICACION = None

# Nombres reales del esquema de ESTE servidor. Ojo: aquí el campo es
# `AccountType` (no `AcctType`, que es como se llama en otras versiones y
# devuelve error -1000), y NO existe `Postable`.
CAMPOS_CUENTAS = ['Code', 'Name', 'ForeignName', 'AccountType', 'FatherAccountKey',
                  'AccountLevel', 'ActiveAccount', 'AcctCurrency',
                  'CashFlowRelevant', 'CashAccount', 'U_Natur']


def homologar(crudo: List[Dict], que: str, empresa: str = '') -> List[Dict]:
    """Traduce la respuesta cruda de SAP a la forma canónica del registro.
    Es la ÚNICA función que conoce los nombres de campo de SAP."""
    if que == 'cuentas':
        # Este servidor no expone `Postable`. Una cuenta es acumulativa (de
        # título) si alguien la tiene como padre — se deduce del árbol, que es
        # más fiable que confiar en un campo que puede no venir.
        padres = {str(c.get('FatherAccountKey') or '').strip()
                  for c in crudo if c.get('FatherAccountKey')}
        salida = []
        for c in crudo:
            codigo = str(c.get('Code', '')).strip()
            natur = (c.get('U_Natur') or '').strip().upper()
            salida.append({
                'codigo': codigo,
                'nombre': (c.get('Name') or '').strip(),
                'nombre_en': (c.get('ForeignName') or '').strip(),
                'clase': 'OTRO',   # la asigna clasificar_catalogo(), abajo:
                                   # necesita el árbol completo, no una cuenta suelta
                'nivel': c.get('AccountLevel'),
                'cuenta_padre': str(c.get('FatherAccountKey') or '').strip(),
                'es_acumulativa': codigo in padres,
                'naturaleza': {'D': 'deudora', 'A': 'acreedora'}.get(natur, ''),
                'moneda': c.get('AcctCurrency') or '',
                'activa': str(c.get('ActiveAccount', '')).lower() in ('tyes', 'y', 'true'),
                'flujo_relevante': str(c.get('CashFlowRelevant', '')).lower() == 'tyes',
                'es_cuenta_efectivo': str(c.get('CashAccount', '')).lower() == 'tyes',
                'empresa': empresa,
                'account_type_sap': c.get('AccountType'),   # se conserva para auditar el mapeo
            })
        # La clasificación necesita el catálogo entero (se resuelve por árbol),
        # así que va aquí y no dentro del bucle.
        global ULTIMO_INFORME_CLASIFICACION
        salida, ULTIMO_INFORME_CLASIFICACION = clasif.clasificar_catalogo(salida, empresa)
        return salida
    raise ValueError(f'homologar(): no sé traducir {que!r}')


# ---------------------------------------------------------------------------
# Facturas (ventas y compras)
# ---------------------------------------------------------------------------
# Campos de CABECERA únicamente. `Invoices` expone 331 campos escalares más las
# líneas anidadas; pedirlo completo para las ~219,000 facturas del grupo sería
# descargar cientos de megabytes para usar doce columnas. Las líneas
# (concepto, flete, servicios) se agregarán como una extracción aparte si se
# necesitan, porque multiplican el volumen por el número de renglones.
CAMPOS_FACTURA = ['DocEntry', 'DocNum', 'DocDate', 'CardCode', 'CardName',
                  'FederalTaxID', 'DocTotal', 'VatSum', 'DocCurrency', 'DocRate',
                  'DocTotalSys', 'CancelStatus', 'Cancelled', 'DocumentStatus',
                  'CreationDate', 'NumAtCard', 'Series']

# LA CANCELACIÓN TIENE TRES ESTADOS, NO DOS. Verificado en NCS (29,630 ventas):
#     csNo           27,008   factura normal
#     csYes           1,311   factura cancelada
#     csCancellation  1,311   el DOCUMENTO DE CANCELACIÓN que anula a la anterior
# Los dos últimos coinciden en número porque SAP emite un documento de
# cancelación por cada factura cancelada. Y —esto es lo que hace daño— el
# documento de cancelación trae el importe en POSITIVO (se vio uno de
# $1,497,119). Sumar "todas las facturas" cuenta tres veces la misma operación:
# la original, su cancelación y el documento que la cancela.
#
# El campo heredado `Cancelled` solo tiene dos valores y deja el documento de
# cancelación en nulo, que es como se ve "dato faltante" cuando en realidad es
# una tercera categoría perfectamente definida. Se conservan ambos campos: el
# nuevo para decidir, el viejo para poder auditar contra extracciones previas.
CANCEL_STATUS = {'csNo': 'normal', 'csYes': 'cancelada',
                 'csCancellation': 'documento_de_cancelacion'}

ENDPOINT_FACTURA = {'venta': 'Invoices', 'compra': 'PurchaseInvoices'}


def _num(v):
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def homologar_facturas(crudo: List[Dict], tipo: str, empresa: str = '') -> List[Dict]:
    """Traduce cabeceras de factura a la forma canónica FACTURAS_CANONICO."""
    salida = []
    for d in crudo:
        fecha = (d.get('DocDate') or '')[:10]
        total = _num(d.get('DocTotal'))
        iva = _num(d.get('VatSum'))
        salida.append({
            'empresa': empresa,
            'tipo': tipo,
            'folio': d.get('DocNum'),
            'fecha': fecha,
            'anio': int(fecha[:4]) if len(fecha) >= 4 and fecha[:4].isdigit() else None,
            'mes': int(fecha[5:7]) if len(fecha) >= 7 and fecha[5:7].isdigit() else None,
            'contraparte': (d.get('CardName') or '').strip(),
            'contraparte_id': (d.get('CardCode') or '').strip(),
            'rfc': (d.get('FederalTaxID') or '').strip(),
            'subtotal': round(total - iva, 2),
            'impuestos': round(iva, 2),
            'total': round(total, 2),
            'moneda': d.get('DocCurrency') or '',
            'tipo_cambio': _num(d.get('DocRate')) or None,
            'total_local': round(_num(d.get('DocTotalSys')), 2),
            # `clase_documento` es el campo con el que se debe filtrar. Solo
            # 'normal' cuenta como venta o compra realizada. Se deriva de
            # `Cancelled` cuando falta `CancelStatus`, para que los archivos
            # extraídos antes de descubrir el campo sigan siendo legibles.
            'clase_documento': CANCEL_STATUS.get(
                d.get('CancelStatus'),
                {'tNO': 'normal', 'tYES': 'cancelada'}.get(
                    d.get('Cancelled'), 'documento_de_cancelacion')),
            'cancelada': d.get('CancelStatus') == 'csYes' or d.get('Cancelled') == 'tYES',
            'serie': d.get('Series'),
            'estatus': d.get('DocumentStatus') or '',
            'referencia': (d.get('NumAtCard') or '').strip(),
            'fecha_registro': (d.get('CreationDate') or '')[:10],
        })
    return salida


def extraer_facturas(ses: SesionSAP, tipo: str = 'venta',
                     desde_anio: Optional[int] = None) -> List[Dict]:
    """Todas las facturas de cabecera de un tipo, en forma canónica.

    Se descarga SIN filtro de fecha aunque se pida `desde_anio`, y se filtra
    después en memoria. No es descuido: en este Service Layer el filtrado por
    fecha combinado con paginación es justo donde ya aparecieron truncamientos
    silenciosos, y el volumen por empresa (la mayor tiene 181,000 cabeceras)
    es perfectamente manejable. Se prefiere bajar de más y verificar contra
    `/$count`, que sin filtro sí es fiable, a bajar de menos sin enterarse.
    """
    endpoint = ENDPOINT_FACTURA.get(tipo)
    if not endpoint:
        raise ValueError(f'tipo de factura desconocido: {tipo!r}')
    crudo = ses.get_todo(endpoint, select=CAMPOS_FACTURA)
    filas = homologar_facturas(crudo, tipo, ses.iniciales)
    if desde_anio:
        filas = [f for f in filas if f['anio'] and f['anio'] >= desde_anio]
    return filas


def extraer_catalogo_cuentas(ses: SesionSAP) -> List[Dict]:
    crudo = ses.get_todo('ChartOfAccounts', select=CAMPOS_CUENTAS, orderby='Code')
    return homologar(crudo, 'cuentas', empresa=ses.iniciales)


# =============================================================================
# EL CIERRE Y LA REAPERTURA SE EXCLUYEN, Y ES LO QUE HACE QUE EL BALANCE EXISTA
# =============================================================================
# SAP no cierra solo las cuentas de resultados contra el capital: hace un cierre
# TOTAL que deja en cero **también las cuentas de balance**, y las reabre en
# enero. Verificado en NG: la cuenta de banco cierra noviembre en 259,756.93, en
# diciembre recibe un haber de 289,023.16 que la deja exactamente en cero, y
# enero la reabre.
#
# Si esas pólizas se suman como cualquier otra, el Balance de diciembre da CERO
# en todas las cuentas — y lo peor es que cuadra: 0 = 0 + 0 + 0 cumple la
# identidad contable a la perfección, así que ninguna verificación protesta.
# Durante un tiempo esto pasó desapercibido en todos los diciembres de las cinco
# empresas.
#
# SAP las marca con `OriginalJournal`, así que no hay que adivinar por fecha ni
# por memo:
#     ttClosingBalance  → el asiento de cierre (diciembre)
#     ttOpeningBalance  → el de reapertura (enero; 40 asientos en NG 2026)
#
# Se excluyen LAS DOS, no solo la de cierre. Son un par que se anula: la primera
# pone en cero y la segunda restaura. Quitando ambas, el libro queda continuo y
# los saldos cruzan el fin de año como debe ser. Quitar solo una descuadraría
# el ejercicio siguiente por el monto completo del balance.
#
# Un mes normal no trae ninguna de las dos (noviembre 2025: 94 asientos, cero
# de cierre), así que el filtro no le quita nada a los meses ordinarios.
ASIENTOS_DE_CIERRE = {'ttClosingBalance', 'ttOpeningBalance'}


def extraer_movimientos_mes(ses: SesionSAP, anio: int, mes: int) -> Dict[str, Dict]:
    """Movimientos (debe/haber) por cuenta de UN mes, desde las pólizas.

    Unidad mínima de trabajo de la extracción. Se hace mes por mes a
    propósito: son seis años por cinco empresas, y bajar un año entero de
    pólizas con sus líneas anidadas en una sola llamada es justo la forma de
    provocar un timeout a media descarga y perder todo el avance.
    """
    from collections import defaultdict
    ultimo_dia = [31, 29 if (anio % 4 == 0 and (anio % 100 != 0 or anio % 400 == 0)) else 28,
                  31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mes - 1]
    filtro = (f"ReferenceDate ge '{anio}-{mes:02d}-01' and "
              f"ReferenceDate le '{anio}-{mes:02d}-{ultimo_dia}'")
    pol = ses.get_todo('JournalEntries', filtro=filtro,
                       select=['ReferenceDate', 'JdtNum', 'OriginalJournal',
                               'JournalEntryLines'])
    acum = defaultdict(lambda: {'debe': 0.0, 'haber': 0.0, 'n_asientos': 0})
    for p in pol:
        if p.get('OriginalJournal') in ASIENTOS_DE_CIERRE:
            continue
        for l in (p.get('JournalEntryLines') or []):
            cta = str(l.get('AccountCode', '')).strip()
            if not cta:
                continue
            acum[cta]['debe'] += float(l.get('Debit') or 0)
            acum[cta]['haber'] += float(l.get('Credit') or 0)
            acum[cta]['n_asientos'] += 1
    return dict(acum)


def extraer_saldo_apertura(ses: SesionSAP, hasta_anio: int) -> Dict[str, Dict]:
    """Saldo acumulado de cada cuenta ANTES del 1-ene-<hasta_anio>.

    POR QUÉ ES INDISPENSABLE: un Balance General es una posición acumulada
    desde que nació la empresa, no desde la fecha en que se nos ocurrió
    empezar a extraer. Si se arranca en 2020 sin traer lo anterior, el
    Capital Contable sale en cero (el capital social se registró años antes),
    el Activo solo refleja el movimiento del periodo, y el Balance no cuadra
    por exactamente el monto que falta. El Estado de Resultados no sufre esto
    porque es un flujo del mes, pero el Balance sí.
    """
    from collections import defaultdict
    filtro = f"ReferenceDate lt '{hasta_anio}-01-01'"
    pol = ses.get_todo('JournalEntries', filtro=filtro,
                       select=['ReferenceDate', 'OriginalJournal', 'JournalEntryLines'])
    acum = defaultdict(lambda: {'debe': 0.0, 'haber': 0.0, 'n_asientos': 0})
    for p in pol:
        # Mismo criterio que en los movimientos mensuales, y aquí importa más:
        # este rango corta justo en un 1 de enero, o sea entre un asiento de
        # cierre y su reapertura. Incluirlos dejaría el saldo de apertura en
        # cero —el cierre ya ocurrió, la reapertura todavía no— y el Balance
        # arrancaría sin capital ni activo fijo.
        if p.get('OriginalJournal') in ASIENTOS_DE_CIERRE:
            continue
        for l in (p.get('JournalEntryLines') or []):
            cta = str(l.get('AccountCode', '')).strip()
            if not cta:
                continue
            acum[cta]['debe'] += float(l.get('Debit') or 0)
            acum[cta]['haber'] += float(l.get('Credit') or 0)
            acum[cta]['n_asientos'] += 1
    return dict(acum)


def extraer_saldos_por_mes(ses: SesionSAP, desde_anio: int = 2020,
                           cache_dir: Optional[str] = None,
                           progreso=None, con_apertura: bool = True) -> List[Dict]:
    """Saldos mensuales por cuenta, desde 'desde_anio' hasta hoy.

    POR QUÉ SE DERIVAN Y NO SE PIDEN: el Service Layer no expone balanza de
    comprobación. El único saldo disponible, `ChartOfAccounts.CurrentBalance`,
    es el de HOY — inútil para una serie histórica. Sumar las líneas de las
    pólizas es la única fuente fiel, y además queda auditable: cada saldo se
    puede rastrear hasta sus asientos.

    REANUDABLE: con `cache_dir`, cada mes ya bajado se guarda en disco y una
    segunda corrida lo salta. Si se cae la red en el mes 40 de 70, al volver a
    correr retoma donde se quedó en vez de empezar de cero.
    """
    import json
    from collections import defaultdict

    hoy = time.localtime()
    meses = [(a, m) for a in range(desde_anio, hoy.tm_year + 1)
             for m in range(1, 13)
             if not (a == hoy.tm_year and m > hoy.tm_mon)]

    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)

    movimientos = {}    # (anio, mes) -> {cuenta: {debe, haber}}
    for i, (a, m) in enumerate(meses, start=1):
        ruta = os.path.join(cache_dir, f'mov_{ses.iniciales}_{a}{m:02d}.json') if cache_dir else None
        if ruta and os.path.isfile(ruta):
            with open(ruta, encoding='utf-8') as f:
                movimientos[(a, m)] = json.load(f)
            if progreso:
                progreso(i, len(meses), a, m, len(movimientos[(a, m)]), True)
            continue
        datos = extraer_movimientos_mes(ses, a, m)
        movimientos[(a, m)] = datos
        if ruta:
            with open(ruta, 'w', encoding='utf-8') as f:
                json.dump(datos, f)
        if progreso:
            progreso(i, len(meses), a, m, len(datos), False)

    # Saldo de apertura: todo lo registrado ANTES del periodo extraído.
    apertura = {}
    if con_apertura:
        ruta_ap = (os.path.join(cache_dir, f'apertura_{ses.iniciales}_{desde_anio}.json')
                   if cache_dir else None)
        if ruta_ap and os.path.isfile(ruta_ap):
            with open(ruta_ap, encoding='utf-8') as f:
                apertura = json.load(f)
        else:
            apertura = extraer_saldo_apertura(ses, desde_anio)
            if ruta_ap:
                with open(ruta_ap, 'w', encoding='utf-8') as f:
                    json.dump(apertura, f)

    # Saldo acumulado por cuenta a lo largo del tiempo.
    # Se recorre en orden cronológico ESTRICTO y arrastrando el saldo, porque
    # el saldo final de un mes es el inicial del siguiente — si se calculara
    # cada mes por separado, el Balance solo reflejaría el movimiento del mes
    # y no la posición acumulada, que es justo lo que un Balance debe mostrar.
    por_cuenta = defaultdict(dict)
    for (a, m), datos in movimientos.items():
        for cta, v in datos.items():
            por_cuenta[cta][(a, m)] = v

    # Las cuentas que solo tienen saldo de apertura (capital social, activos
    # fijos viejos) no aparecen en ningún mes del periodo, pero SÍ van en el
    # Balance. Si no se agregan aquí, se pierden.
    for cta in apertura:
        por_cuenta.setdefault(cta, {})

    filas = []
    for cta, meses_cta in por_cuenta.items():
        ap = apertura.get(cta)
        saldo = (ap['debe'] - ap['haber']) if ap else 0.0
        if ap:
            filas.append({
                'codigo': cta, 'anio': desde_anio - 1, 'mes': 12,
                'saldo_inicial': 0.0,
                'debe': round(ap['debe'], 2), 'haber': round(ap['haber'], 2),
                'saldo_final': round(saldo, 2),
                'n_asientos': ap.get('n_asientos', 0),
                'empresa': ses.iniciales,
                'es_apertura': True,
            })
        for (a, m) in sorted(meses_cta.keys()):
            v = meses_cta[(a, m)]
            inicial = saldo
            saldo = saldo + v['debe'] - v['haber']
            filas.append({
                'codigo': cta, 'anio': a, 'mes': m,
                'saldo_inicial': round(inicial, 2),
                'debe': round(v['debe'], 2), 'haber': round(v['haber'], 2),
                'saldo_final': round(saldo, 2),
                'n_asientos': v.get('n_asientos', 0),
                'empresa': ses.iniciales,
            })
    filas.sort(key=lambda f: (f['codigo'], f['anio'], f['mes']))
    return filas
