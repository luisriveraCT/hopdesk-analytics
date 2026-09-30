# -*- coding: utf-8 -*-
"""
===============================================================================
 MAPEO DEL ERP A LOS CAMPOS DE LOS KPIs
===============================================================================
El puente entre lo que el ERP entrega (un catálogo de cientos de cuentas y sus
saldos) y lo que las razones financieras necesitan (efectivo, cuentas por
cobrar, deuda con costo, depreciación...).

CÓMO SE IDENTIFICA CADA RUBRO
-----------------------------
Por el ÁRBOL y el NOMBRE, con vocabulario en español e inglés — el mismo
criterio que ya usan `clasificador_cuentas` para las clases y para el impuesto a
la utilidad. Nunca por el prefijo del código: la numeración es una convención de
cada empresa y en este mismo catálogo ya demostró estar corrida un cajón.

Una cuenta pertenece a un rubro si ella o alguno de sus antepasados coincide con
el vocabulario de ese rubro. Se elige el rubro cuyo término coincida de la forma
más específica (el término más largo gana), para que "Cuentas por Cobrar" no se
lea como "Cuentas por Pagar" ni "Anticipo de Impuestos" como "Impuestos".

QUÉ HACE CUANDO NO ENCUENTRA ALGO
---------------------------------
Devuelve `None`, no cero. Un cero dice "esta empresa no tiene inventarios"; un
`None` dice "no se pudo determinar". La diferencia importa: con cero, una razón
que divida entre inventarios da un número; con `None`, la razón no se calcula y
el tablero muestra un hueco honesto.

LO QUE ESTE MÓDULO NO PUEDE DAR
-------------------------------
  · **Capex y depreciación del periodo**: la depreciación del gasto sí (está en
    el Estado de Resultados); el capex necesitaría el detalle de altas de activo
    fijo, que es otra extracción.
  · **Parámetros de mercado del WACC**: tasa libre de riesgo, beta y prima. Son
    externos por naturaleza. La tasa impositiva efectiva SÍ sale de aquí.
===============================================================================
"""
import os
import re
import sys
import json
from typing import Dict, List, Optional

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS_ERP = os.path.join(AQUI, 'datos_erp')
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(AQUI, 'erp'))
sys.path.insert(0, os.path.join(AQUI, 'configuracion'))

from erp.clasificador_cuentas import normalizar, clasificar_catalogo  # noqa: E402
import analisis_vertical_horizontal as av                             # noqa: E402

# ---------------------------------------------------------------------------
# Vocabulario de rubros
# ---------------------------------------------------------------------------
# El orden dentro de cada lista no importa: gana el término más largo de todos
# los rubros, que es el más específico. Lo que sí importa es que cada término
# sea discriminante — "impuestos" a secas aparecería en media docena de rubros.
RUBROS: Dict[str, List[str]] = {
    'efectivo': [
        'caja y bancos', 'efectivo y equivalentes', 'efectivo y equivalentes de efectivo',
        'cash and cash equivalents', 'cash equivalents', 'caja', 'bancos', 'cash',
    ],
    'cuentas_x_cobrar': [
        'cuentas por cobrar', 'clientes y cuentas por cobrar',
        'accounts receivable', 'trade receivables', 'receivables', 'clientes',
    ],
    'inventarios': [
        'inventario', 'inventarios', 'almacen', 'existencias',
        'inventory', 'inventories', 'stock',
    ],
    'cuentas_x_pagar': [
        'cuentas por pagar', 'proveedores y cuentas por pagar',
        'accounts payable', 'trade payables', 'payables', 'proveedores',
    ],
    'deuda_con_costo': [
        'obligaciones con bancos e instituciones financieras',
        'creditos bancarios a largo plazo', 'creditos bancarios',
        'documentos por pagar', 'prestamos bancarios', 'deuda financiera',
        'obligaciones con bancos', 'arrendamiento financiero',
        'bank loans', 'long term debt', 'notes payable', 'borrowings',
        'lease liabilities',
    ],
    # Saldos con empresas del propio grupo. Tiene rubro propio para SACARLOS de
    # cuentas por cobrar y por pagar, no para lucirlos.
    #
    # Sin esto, la cuenta de NRS "Documentos y cuentas por pagar empresas
    # relacionadas largo plazo" casaba con "cuentas por pagar" y entraba al DPO:
    # días de pago a proveedores inflados con deuda que el grupo se debe a sí
    # mismo, y encima de largo plazo. El DSO y el DPO miden qué tan rápido cobra
    # y paga la empresa AL MUNDO; meterle lo intercompañía los vuelve ilegibles.
    #
    # Gana sobre "cuentas por pagar" porque el término es más largo, que es
    # justamente la regla de especificidad del módulo.
    'partes_relacionadas': [
        'empresas relacionadas', 'partes relacionadas', 'companias relacionadas',
        'compañias relacionadas', 'entidades relacionadas', 'empresas afiliadas',
        'related parties', 'related party', 'intercompany', 'affiliates',
    ],
    'depreciacion_acumulada': [
        'depreciacion acumulada', 'amortizacion acumulada',
        'accumulated depreciation', 'accumulated amortization',
    ],
    'activo_fijo': [
        'activos fijos', 'activo fijo', 'propiedad planta y equipo',
        'property plant and equipment', 'fixed assets',
    ],
}

# ---------------------------------------------------------------------------
# Circulante: una clasificación SEPARADA, y tiene que serlo
# ---------------------------------------------------------------------------
# La tentación es agregar 'activo_circulante' a RUBROS y terminar. No funciona,
# y falla en silencio: en RUBROS gana el término más largo, así que
# "activos circulantes" (19 letras) le ganaría a "bancos" (6) en toda cuenta de
# banco —que cuelga justo de ahí— y el efectivo del grupo se volvería cero.
# Las razones de liquidez saldrían bien y el ROE mal, sin ninguna señal.
#
# Es que son dos preguntas distintas sobre la misma cuenta: QUÉ ES (banco,
# cliente, proveedor) y CUÁNDO VENCE (circulante o no). Una cuenta tiene las dos
# respuestas a la vez, así que no caben en una sola asignación exclusiva.
CIRCULANTE: Dict[str, List[str]] = {
    'activo_circulante': [
        'activos circulantes', 'activo circulante',
        'current assets', 'total current assets',
    ],
    'pasivo_circulante': [
        'pasivo circulante', 'pasivos circulantes', 'pasivo a corto plazo',
        'current liabilities', 'total current liabilities',
    ],
}

# QUÉ CUENTA COMO D&A LO DECIDE LA NORMA, NO ESTE ARCHIVO.
#
# Bajo IFRS/NIF la "A" de EBITDA es amortización de intangibles y de activos
# por derecho de uso, no el consumo de un pago anticipado. En el catálogo de
# Networks existe "Amortización - Primas Seguros": una póliza pagada por
# adelantado que se consume mes a mes. Es gasto de operación corriente, y
# sumarla de vuelta inflaba el EBITDA con algo que sí consume caja cada año.
#
# La lista vive en `normas_contables`, indexada por el marco que declara el
# cliente en su configuración. Un cliente con otra norma cambia su
# configuración, no este código.
import normas_contables as nc  # noqa: E402


def _terminos_dya(clave_norma=None):
    pol = nc.politica('dya_para_ebitda', clave_norma)
    incluye = sorted((normalizar(t) for t in pol['incluye']), key=len, reverse=True)
    excluye = sorted((normalizar(t) for t in pol['excluye']), key=len, reverse=True)
    return incluye, excluye

# Rubros que GANAN aunque su término sea más corto.
#
# La regla general —gana el término más largo— funciona para distinguir cosas
# que compiten ("cuentas por cobrar" contra "cobrar"). No funciona cuando un
# término CALIFICA a otro, porque entonces la longitud es una coincidencia del
# idioma y no una señal:
#
#   "Documentos y cuentas por pagar empresas relacionadas largo plazo"
#      "cuentas por pagar" (17)  vs  "empresas relacionadas" (21)  → gana el
#      calificador, por suerte.
#
#   "Accounts Receivable - Related Parties"
#      "accounts receivable" (19)  vs  "related parties" (15)  → gana el
#      genérico, y la cuenta intercompañía se cuela a los días de cobranza.
#
# La misma cuenta, el mismo error, y la diferencia es cuántas letras tiene la
# palabra en cada idioma. Que sea parte relacionada es lo más específico que se
# puede decir de una cuenta, así que se decide antes y no por tamaño.
RUBROS_PRIORITARIOS = ('partes_relacionadas',)

def _ordenar_terminos(rubros):
    prio = sorted(((t, r) for r in RUBROS_PRIORITARIOS if r in rubros
                   for t in rubros[r]), key=lambda x: -len(x[0]))
    resto = sorted(((t, r) for r, ts in rubros.items()
                    if r not in RUBROS_PRIORITARIOS for t in ts),
                   key=lambda x: -len(x[0]))
    return prio + resto


_TERMINOS = _ordenar_terminos(RUBROS)


# ---------------------------------------------------------------------------
# Vocabulario propio del cliente
# ---------------------------------------------------------------------------
# El vocabulario de arriba cubre las formas usuales de nombrar cada rubro en
# español y en inglés, pero no puede cubrirlas todas: un catálogo que llame
# "Disponibilidades" a la caja, o "Deudores por Ventas" a los clientes, no
# coincide con nada — y el fallo es silencioso, porque el rubro simplemente sale
# vacío y con él las razones que dependen de él.
#
# `aplicar_vocabulario_cliente` deja que la configuración del cliente AGREGUE
# términos. Agregue, no reemplace: quitar los de fábrica dejaría de reconocer
# cuentas que hoy sí se reconocen, y ese tipo de regresión no se ve hasta que
# alguien nota que un indicador lleva meses vacío.
#
# La forma en la configuración es {rubro: [términos]}, con los mismos nombres de
# rubro de RUBROS. Un rubro inventado LEVANTA: un término colgado de un rubro
# que no existe no clasifica nada y nadie se entera.
class RubroDesconocido(ValueError):
    """Se configuró vocabulario para un rubro que el sistema no reconoce."""


def aplicar_vocabulario_cliente(extra: Dict[str, List[str]]) -> None:
    global _TERMINOS
    if not extra:
        return
    fusion = {k: list(v) for k, v in RUBROS.items()}
    for rubro, terminos in extra.items():
        if rubro not in fusion:
            raise RubroDesconocido(
                f'No existe el rubro {rubro!r}. Los reconocidos son: '
                f'{", ".join(sorted(RUBROS))}. Un término colgado de un rubro '
                f'inexistente no clasifica nada y no avisa.')
        for t in terminos:
            t = normalizar(str(t))
            if t and t not in fusion[rubro]:
                fusion[rubro].append(t)
    _TERMINOS = _ordenar_terminos(fusion)


def vocabulario_activo() -> List:
    """Los términos en uso, para poder mostrarlos y auditarlos."""
    return list(_TERMINOS)


def _cadena_nombres(codigo: str, cuentas: Dict[str, Dict]) -> List[str]:
    """Nombres normalizados de la cuenta y sus antepasados, de hoja a raíz."""
    visto, salida = set(), []
    actual = cuentas.get(codigo)
    while actual and actual['codigo'] not in visto:
        visto.add(actual['codigo'])
        salida.append(normalizar(actual.get('nombre', '')))
        padre = (actual.get('cuenta_padre') or '').strip()
        actual = cuentas.get(padre) if padre else None
    return salida


def rubro_de_cuenta(codigo: str, cuentas: Dict[str, Dict]) -> Optional[str]:
    """A qué rubro pertenece una cuenta, o None si no se reconoce.

    Se prueban los términos de más largo a más corto: el primero que coincida
    en cualquier eslabón de la cadena decide. Así "cuentas por cobrar" gana
    sobre "cobrar" y "depreciacion acumulada" sobre "depreciacion".
    """
    cadena = _cadena_nombres(codigo, cuentas)
    for termino, rubro in _TERMINOS:
        patron = r'\b' + re.escape(termino) + r'\b'
        for nombre in cadena:
            if re.search(patron, nombre):
                return rubro
    return None


_TERMINOS_CIRC = sorted(
    ((t, grupo) for grupo, ts in CIRCULANTE.items() for t in ts),
    key=lambda x: -len(x[0]))


def grupo_circulante(codigo: str, cuentas: Dict[str, Dict]) -> Optional[str]:
    """'activo_circulante', 'pasivo_circulante', o None si no cuelga de ninguno."""
    cadena = _cadena_nombres(codigo, cuentas)
    for termino, grupo in _TERMINOS_CIRC:
        patron = r'\b' + re.escape(termino) + r'\b'
        for nombre in cadena:
            if re.search(patron, nombre):
                return grupo
    return None


def es_depreciacion_gasto(codigo: str, cuentas: Dict[str, Dict],
                          clave_norma: str = None) -> bool:
    """¿Es gasto por depreciación o amortización, según la norma del cliente?

    Tres criterios, y el orden importa porque el más específico debe ganar:

    1. La depreciación **ACUMULADA** nunca lo es: es un contra-activo del
       Balance. Confundirla metería el saldo histórico completo dentro del
       gasto de un mes.
    2. Lo que la norma **excluye** de la "A" de EBITDA. Bajo IFRS/NIF son los
       pagos anticipados consumiéndose —primas de seguro, rentas pagadas por
       adelantado—: gasto de operación corriente, no amortización de un activo
       de capital. Esta exclusión gana sobre la inclusión porque el nombre
       propio de la cuenta es más específico que el del rubro del que cuelga.
    3. Lo que la norma **incluye**.
    """
    incluye, excluye = _terminos_dya(clave_norma)
    cadena = _cadena_nombres(codigo, cuentas)
    if any(re.search(r'\bacumulad', n) for n in cadena):
        return False
    for termino in excluye:
        if any(re.search(r'\b' + re.escape(termino), n) for n in cadena):
            return False
    for termino in incluye:
        patron = r'\b' + re.escape(termino) + r'\b'
        if any(re.search(patron, n) for n in cadena):
            return True
    return False


# ---------------------------------------------------------------------------
# Construcción de la fila financiera
# ---------------------------------------------------------------------------
def cargar_empresa(ini: str):
    with open(os.path.join(DATOS_ERP, f'cuentas_{ini}.json'), encoding='utf-8') as f:
        cuentas = json.load(f)
    cuentas, _ = clasificar_catalogo(cuentas, ini)
    with open(os.path.join(DATOS_ERP, f'saldos_{ini}.json'), encoding='utf-8') as f:
        saldos = json.load(f)
    return {c['codigo']: c for c in cuentas}, saldos


def saldos_por_rubro(saldos, cuentas, anio, mes) -> Dict[str, float]:
    """Suma de la última posición conocida de cada cuenta, agrupada por rubro.

    Usa el mismo criterio de "última posición hasta la fecha" que el Balance,
    para que los rubros sumen exactamente el activo y el pasivo del estado.
    """
    ultimo = {}
    for s in saldos:
        if (s['anio'], s['mes']) > (anio, mes):
            continue
        k = s['codigo']
        if k not in ultimo or (s['anio'], s['mes']) > (ultimo[k]['anio'], ultimo[k]['mes']):
            ultimo[k] = s
    tot = {}
    for codigo, s in ultimo.items():
        cta = cuentas.get(codigo)
        if not cta or cta.get('es_acumulativa'):
            continue
        if cta['clase'] not in ('ACTIVO', 'PASIVO'):
            continue
        # Los pasivos vienen con saldo acreedor (negativo); se presentan en
        # positivo, que es como los espera el módulo de razones.
        v = s['saldo_final']
        v = -v if cta['clase'] == 'PASIVO' else v
        rubro = rubro_de_cuenta(codigo, cuentas)
        if rubro:
            tot[rubro] = tot.get(rubro, 0.0) + v
        # Se pregunta aparte porque es otra dimensión: la misma cuenta es
        # "bancos" Y "circulante" al mismo tiempo.
        circ = grupo_circulante(codigo, cuentas)
        if circ:
            tot[circ] = tot.get(circ, 0.0) + v
    return tot


def depreciacion_del_periodo(saldos, cuentas, anio, mes,
                             clave_norma: str = None) -> float:
    """Gasto por depreciación y amortización del mes, bajo la norma del cliente."""
    total = 0.0
    for s in saldos:
        if s['anio'] != anio or s['mes'] != mes:
            continue
        cta = cuentas.get(s['codigo'])
        if not cta or cta.get('es_acumulativa') or cta['clase'] != 'GASTO':
            continue
        if es_depreciacion_gasto(s['codigo'], cuentas, clave_norma):
            total += s['debe'] - s['haber']
    return round(total, 2)


def mes_parece_incompleto(saldos, cuentas, anio, mes,
                          clave_norma: str = None) -> bool:
    """¿Este mes está a medio capturar?

    POR QUÉ HACE FALTA: el mes en curso siempre está incompleto, y los asientos
    que faltan no son aleatorios — son justo los de cierre mensual. La
    depreciación, por ejemplo, se registra a fin de mes: en NCS aparece en los
    81 meses de la serie salvo en el mes corriente. Un EBITDA calculado sin ella
    sale inflado, y nada en la cifra avisa de eso.

    Se detecta por comportamiento, no por calendario: si hay cuentas que se
    mueven TODOS los meses anteriores y en éste no, el mes está incompleto.
    Preguntar "¿es el mes actual?" fallaría con una empresa que cierra tarde o
    con datos extraídos a media mañana.
    """
    pers = sorted({(s['anio'], s['mes']) for s in saldos})
    if (anio, mes) not in pers or len(pers) < 4:
        return False
    previos = [p for p in pers if p < (anio, mes)][-6:]
    if len(previos) < 3:
        return False

    recurrentes = set()
    for codigo, cta in cuentas.items():
        if cta.get('es_acumulativa') or cta['clase'] != 'GASTO':
            continue
        if not es_depreciacion_gasto(codigo, cuentas, clave_norma):
            continue
        recurrentes.add(codigo)
    if not recurrentes:
        return False

    def movio(a, m):
        return any(s['codigo'] in recurrentes and abs(s['debe'] - s['haber']) > 0.5
                   for s in saldos if s['anio'] == a and s['mes'] == m)

    # Si se movió en todos los meses previos y en éste no, falta el cierre.
    return all(movio(a, m) for a, m in previos) and not movio(anio, mes)


def fila_financiera(ini: str, anio: int, mes: int, datos=None,
                    clave_norma: str = None) -> Dict:
    """Los campos que necesitan las razones financieras, para un mes.

    `datos` permite pasar (cuentas, saldos) ya cargados: construir 81 filas
    releyendo el catálogo cada vez multiplica el trabajo por nada.

    `clave_norma` es el marco contable del cliente y decide qué cuenta como
    depreciación y amortización. Viaja como argumento —y no se lee de una
    variable global— para que el módulo sirva igual con dos clientes de normas
    distintas en la misma corrida.
    """
    cuentas, saldos = datos if datos else cargar_empresa(ini)
    bal = av.balance_general(saldos, cuentas, anio, mes)
    er = av.estado_resultados(saldos, cuentas, anio, mes)
    rub = saldos_por_rubro(saldos, cuentas, anio, mes)
    dep = depreciacion_del_periodo(saldos, cuentas, anio, mes, clave_norma)

    ing = er['ingresos']
    ebit = er['utilidad_operacion']
    return {
        'empresa': ini, 'anio': anio, 'mes': mes,
        'periodo': f'{anio}-{mes:02d}',
        # --- Estado de Resultados ---
        'ingresos': ing,
        'costo_servicio': er['costo'],
        'gastos_operacion': er['gastos_operacion'],
        'depreciacion': dep,
        'gastos_financieros': er['resultado_financiero'],
        'ebit': ebit,
        # EBITDA = EBIT más la depreciación, que ya está restada dentro de los
        # gastos de operación. Sumarla de vuelta es el único paso.
        'ebitda': ebit + dep,
        'ebt': er['resultado_antes_impuestos'],
        'impuestos': er['impuestos'],
        'utilidad_neta': er['utilidad_neta'],
        'tasa_efectiva': er.get('tasa_efectiva'),
        'tasa_confiable': er.get('tasa_confiable', False),
        # --- Balance ---
        'activos_totales': bal['activo'],
        'pasivos_totales': bal['pasivo'],
        'patrimonio': bal['capital'],
        'efectivo': rub.get('efectivo'),
        'cuentas_x_cobrar': rub.get('cuentas_x_cobrar'),
        'inventarios': rub.get('inventarios'),
        'cuentas_x_pagar': rub.get('cuentas_x_pagar'),
        'deuda_con_costo': rub.get('deuda_con_costo'),
        'activo_fijo': rub.get('activo_fijo'),
        'activo_circulante': rub.get('activo_circulante'),
        'pasivo_circulante': rub.get('pasivo_circulante'),
        'partes_relacionadas': rub.get('partes_relacionadas'),
        'es_cierre_anual': bal.get('es_cierre_anual', False),
        'mes_incompleto': mes_parece_incompleto(saldos, cuentas, anio, mes,
                                                clave_norma),
        'descuadre': bal['descuadre'],
    }


def serie_financiera(ini: str, desde_anio: Optional[int] = None,
                     clave_norma: str = None) -> List[Dict]:
    """Todas las filas de una empresa, ordenadas."""
    cuentas, saldos = cargar_empresa(ini)
    pers = sorted({(s['anio'], s['mes']) for s in saldos})
    if desde_anio:
        pers = [p for p in pers if p[0] >= desde_anio]
    return [fila_financiera(ini, a, m, (cuentas, saldos), clave_norma)
            for a, m in pers]
