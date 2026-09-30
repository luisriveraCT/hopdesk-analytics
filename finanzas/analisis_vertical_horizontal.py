# -*- coding: utf-8 -*-
"""
===============================================================================
 ANÁLISIS VERTICAL Y HORIZONTAL
===============================================================================
Las dos lecturas clásicas de un estado financiero, y la razón por la que se
usan juntas:

  · VERTICAL (análisis de estructura, "common-size"): cada renglón como % de
    una base del mismo periodo — Ingresos para el Estado de Resultados, Activos
    Totales para el Balance. Contesta "¿de qué está hecho este peso?" y permite
    comparar la empresa contra sí misma en el tiempo o contra otra de distinto
    tamaño, porque elimina la escala.

  · HORIZONTAL (análisis de tendencia): cada renglón contra el mismo renglón de
    un periodo anterior, en variación absoluta y porcentual. Contesta "¿qué se
    movió y cuánto?".

LA TRAMPA QUE ESTE MÓDULO SÍ MANEJA: las variaciones porcentuales cuando la
base es cero, muy chica, o de signo contrario. Un renglón que pasa de −100 a
+50 no "creció 150%", y uno que pasa de 0 a 1,000 no tiene variación
porcentual definida. Casi todas las hojas de cálculo escupen un número igual
(o #¡DIV/0!) y alguien termina presentándolo. Aquí eso regresa None con una
marca que dice por qué, y quien presenta decide — pero no se inventa un número.
===============================================================================
"""
from typing import Dict, List, Optional

# Cuando la base es menor a esto en valor absoluto, el % de variación no se
# reporta: matemáticamente existe, pero no significa nada y engaña.
UMBRAL_BASE_INSIGNIFICANTE = 1.0

# Dentro de qué banda una tasa efectiva de impuestos se considera utilizable.
# La de arranque cubre el régimen mexicano —ISR 30% más PTU 10% sobre una base
# distinta, que en la práctica da 35-45%— con holgura hacia los dos lados.
#
# Es configuración del cliente y no una constante: un cliente en otra
# jurisdicción tiene otra banda, y con ésta se le marcarían como no confiables
# tasas perfectamente normales de su país. Se pasa como argumento a
# `estado_resultados`; quien no lo pase usa ésta.
BANDA_TASA_EFECTIVA = (0.0, 0.60)


def variacion(actual: Optional[float], anterior: Optional[float]) -> Dict:
    """Variación horizontal entre dos periodos, con el porcentaje calculado
    solo cuando de verdad significa algo."""
    if actual is None or anterior is None:
        return {'absoluta': None, 'porcentual': None, 'nota': 'falta un periodo'}
    abs_ = actual - anterior
    if abs(anterior) < UMBRAL_BASE_INSIGNIFICANTE:
        nota = 'base cero o insignificante: el % no es interpretable'
        return {'absoluta': abs_, 'porcentual': None, 'nota': nota}
    if (anterior < 0) != (actual < 0) and anterior < 0:
        # cruce de signo desde negativo: el % tiene signo contraintuitivo
        return {'absoluta': abs_, 'porcentual': None,
                'nota': 'cambio de signo desde base negativa: el % invertiría la lectura'}
    return {'absoluta': abs_, 'porcentual': abs_ / abs(anterior), 'nota': ''}


def analisis_vertical(renglones: Dict[str, Optional[float]], base: Optional[float],
                      nombre_base: str = 'base') -> Dict[str, Dict]:
    """Cada renglón como % de la base del MISMO periodo."""
    out = {}
    for k, v in renglones.items():
        if v is None or base is None or base == 0:
            out[k] = {'valor': v, 'pct': None,
                      'nota': f'sin {nombre_base}' if base in (None, 0) else 'sin valor'}
        else:
            out[k] = {'valor': v, 'pct': v / base, 'nota': ''}
    return out


def analisis_horizontal(serie: List[Dict], campos: List[str],
                        modo: str = 'periodo_anterior',
                        indice_base: int = 0) -> List[Dict]:
    """serie: lista de periodos ordenada, cada uno un dict con `campos`.

    modo:
      'periodo_anterior' — variación contra el periodo inmediato anterior.
      'base_fija'        — todo contra un periodo base (índice `indice_base`),
                           que es como se construye un análisis de números
                           índice (base 100). Útil para ver la tendencia
                           acumulada desde el inicio sin el ruido mes a mes.
    """
    salida = []
    for i, periodo in enumerate(serie):
        ref = serie[indice_base] if modo == 'base_fija' else (serie[i - 1] if i > 0 else None)
        fila = {k: periodo.get(k) for k in ('anio', 'mes', 'periodo') if k in periodo}
        for campo in campos:
            actual = periodo.get(campo)
            anterior = ref.get(campo) if ref else None
            v = variacion(actual, anterior)
            fila[campo] = actual
            fila[f'{campo}__var_abs'] = v['absoluta']
            fila[f'{campo}__var_pct'] = v['porcentual']
            if v['nota']:
                fila[f'{campo}__nota'] = v['nota']
            if modo == 'base_fija' and anterior not in (None, 0):
                fila[f'{campo}__indice'] = (actual / anterior * 100) if actual is not None else None
        salida.append(fila)
    return salida


# ---------------------------------------------------------------------------
# Armado de estados financieros desde saldos canónicos
# ---------------------------------------------------------------------------
def estado_resultados(saldos: List[Dict], cuentas: Dict[str, Dict],
                      anio: int, mes: int, banda_tasa=None) -> Dict:
    """Estado de Resultados del mes, armado desde los saldos canónicos.

    OJO CON LOS SIGNOS: en la convención de partida doble que usa este módulo
    (saldo = debe − haber), las cuentas de ingreso quedan con saldo NEGATIVO
    porque se abonan. Se invierten aquí para presentarlas en positivo, que es
    como las lee cualquier persona. Es el tipo de detalle que, si se omite,
    produce un estado con márgenes negativos perfectos y nadie entiende por qué.

    FINANCIERO Y OTRO VAN DESPUÉS DE LA UTILIDAD DE OPERACIÓN, no dentro. El
    Resultado Integral de Financiamiento (intereses pagados y cobrados,
    diferencia cambiaria) no es un gasto de operación: mezclarlo destruye la
    comparabilidad del margen operativo entre empresas que se financian
    distinto — que es precisamente lo que aquí se quiere medir, porque las seis
    empresas del grupo tienen estructuras de deuda muy diferentes.

    Ambos totales quedan con signo de COSTO: positivo = resta a la utilidad.
    Un RIF negativo significa que la empresa ganó más por intereses/tipo de
    cambio de lo que pagó.
    """
    # EL IMPUESTO A LA UTILIDAD SE SEPARA DE LOS DEMÁS GASTOS. Sin eso, la
    # utilidad de operación queda contaminada con el ISR y el estado no llega a
    # una utilidad NETA — además de que la tasa impositiva efectiva, que hace
    # falta para el WACC, no se puede calcular.
    #
    # Se detecta leyendo el árbol del catálogo (ver
    # erp/clasificador_cuentas.es_impuesto_a_la_utilidad), no por el prefijo del
    # código: en este plan de cuentas el ISR y la PTU cuelgan de "Provisión de
    # Impuestos", mientras que el impuesto sobre nómina y el predial cuelgan de
    # rubros de gasto operativo y deben quedarse donde están.
    try:
        from erp.clasificador_cuentas import es_impuesto_a_la_utilidad
    except ImportError:
        try:
            from clasificador_cuentas import es_impuesto_a_la_utilidad
        except ImportError:
            # Sin el clasificador, el impuesto se queda dentro de los gastos y
            # el estado llega solo hasta "antes de impuestos". Se degrada, pero
            # no se inventa una separación que no se pudo hacer.
            def es_impuesto_a_la_utilidad(_c, _cs):
                return False

    tot = {'INGRESO': 0.0, 'COSTO': 0.0, 'GASTO': 0.0,
           'FINANCIERO': 0.0, 'OTRO': 0.0, 'IMPUESTO': 0.0}
    detalle = {c: [] for c in tot}
    for s in saldos:
        if s['anio'] != anio or s['mes'] != mes:
            continue
        cta = cuentas.get(s['codigo'])
        if not cta or cta.get('es_acumulativa'):
            continue           # las acumulativas duplicarían a sus hijas
        clase = cta['clase']
        if clase not in tot:
            continue
        # El impuesto a la utilidad se saca de GASTO y va a su propio renglón.
        if clase == 'GASTO' and es_impuesto_a_la_utilidad(s['codigo'], cuentas):
            clase = 'IMPUESTO'
        movimiento = s['debe'] - s['haber']
        valor = -movimiento if clase == 'INGRESO' else movimiento
        tot[clase] += valor
        detalle.setdefault(clase, []).append(
            {'codigo': s['codigo'], 'nombre': cta['nombre'], 'valor': valor})

    ingresos = tot['INGRESO']
    utilidad_bruta = ingresos - tot['COSTO']
    utilidad_operacion = utilidad_bruta - tot['GASTO']
    resultado_antes_impuestos = utilidad_operacion - tot['FINANCIERO'] - tot['OTRO']
    utilidad_neta = resultado_antes_impuestos - tot['IMPUESTO']
    # Tasa impositiva EFECTIVA: la que de verdad pagó la empresa, no la de ley.
    # Es la que entra al WACC (el factor 1−t del costo de la deuda).
    #
    # Se devuelve None y no cero cuando el resultado antes de impuestos es
    # negativo o insignificante: una tasa calculada sobre una base negativa sale
    # con el signo invertido y se presenta sola en una junta. Preferimos decir
    # "no es interpretable" a entregar un número que engaña.
    tasa_efectiva = (tot['IMPUESTO'] / resultado_antes_impuestos
                     if resultado_antes_impuestos > UMBRAL_BASE_INSIGNIFICANTE else None)
    # Una tasa aritméticamente correcta puede no ser utilizable. En México lo
    # normal ronda 35-45% (ISR 30% más PTU 10% sobre una base distinta); fuera
    # de esa banda suele significar que la base es diminuta frente al impuesto
    # —se vio 206% en una empresa con utilidad casi nula— o que hubo un ajuste
    # de ejercicios anteriores. El número se entrega igual, pero marcado: quien
    # lo use en un WACC tiene que saber que no puede tomarlo tal cual.
    lo, hi = banda_tasa or BANDA_TASA_EFECTIVA
    tasa_confiable = tasa_efectiva is not None and lo <= tasa_efectiva <= hi
    return {
        'anio': anio, 'mes': mes,
        'ingresos': ingresos,
        'costo': tot['COSTO'],
        'utilidad_bruta': utilidad_bruta,
        'gastos_operacion': tot['GASTO'],
        'utilidad_operacion': utilidad_operacion,
        'resultado_financiero': tot['FINANCIERO'],
        'otros': tot['OTRO'],
        'resultado_antes_impuestos': resultado_antes_impuestos,
        'impuestos': tot['IMPUESTO'],
        'utilidad_neta': utilidad_neta,
        'tasa_efectiva': tasa_efectiva,
        'tasa_confiable': tasa_confiable,
        'detalle': detalle,
        'vertical': analisis_vertical(
            {'Costo': tot['COSTO'], 'Utilidad bruta': utilidad_bruta,
             'Gastos de operación': tot['GASTO'], 'Utilidad de operación': utilidad_operacion,
             'Resultado financiero': tot['FINANCIERO'], 'Otros': tot['OTRO'],
             'Resultado antes de impuestos': resultado_antes_impuestos,
             'Impuestos': tot['IMPUESTO'], 'Utilidad neta': utilidad_neta},
            ingresos, 'ingresos'),
    }


def _es_periodo_de_cierre(ultimo: Dict, cuentas: Dict[str, Dict]) -> bool:
    """¿Este periodo quedó arrasado por el asiento de cierre anual?

    SAP hace cierre y reapertura TOTAL a fin de año: no solo cierra las cuentas
    de resultados contra el capital, sino que deja en cero **también las de
    balance**, y las reabre en enero. Verificado en NG: la cuenta de banco
    cierra noviembre en 259,756.93, en diciembre recibe un haber de 289,023.16
    que la deja exactamente en cero, y enero la reabre.

    Se detecta por el efecto y no por la fecha porque el ejercicio fiscal no
    tiene que terminar en diciembre, y porque una empresa puede no haber cerrado
    todavía. Preguntar "¿es diciembre?" daría falsos positivos y falsos
    negativos; preguntar "¿quedó todo en cero?" describe lo que de verdad pasó.
    """
    con_saldo = [s for c, s in ultimo.items()
                 if (cuentas.get(c) or {}).get('clase') in CLASES_BALANCE_SET
                 and not (cuentas.get(c) or {}).get('es_acumulativa')]
    if len(con_saldo) < 5:
        return False
    en_cero = sum(1 for s in con_saldo if abs(s.get('saldo_final') or 0) < 0.005)
    # Que TODAS las cuentas de balance de una empresa en marcha queden en cero
    # el mismo mes no ocurre por casualidad.
    return en_cero == len(con_saldo)


CLASES_BALANCE_SET = {'ACTIVO', 'PASIVO', 'CAPITAL'}


def balance_general(saldos: List[Dict], cuentas: Dict[str, Dict],
                    anio: int, mes: int) -> Dict:
    """Balance al cierre del mes, con la comprobación que importa:
    Activo = Pasivo + Capital. Si no cuadra, se dice — no se ajusta.

    OJO CON EL CIERRE ANUAL. Si el periodo pedido es aquel en el que SAP aplicó
    el cierre y reapertura, el libro dice cero en TODAS las cuentas, y un
    balance en ceros **cumple la identidad contable a la perfección**
    (0 = 0 + 0 + 0). Durante un tiempo esta función devolvió exactamente eso y
    el verificador lo aprobaba: todos los diciembres de todas las empresas
    daban activo cero y nada protestaba.

    Ahora se detecta y se devuelve la última posición real anterior, marcada con
    `es_cierre_anual` y una nota. No es el saldo al 31 de diciembre —para eso
    hace falta separar el asiento de cierre de los movimientos ordinarios del
    mes, y con los agregados mensuales que hoy se extraen eso es
    matemáticamente indeterminado (ver `PENDIENTE_CIERRE_ANUAL` abajo)—. Es la
    mejor cifra disponible, y viene diciendo lo que es.
    """
    tot = {'ACTIVO': 0.0, 'PASIVO': 0.0, 'CAPITAL': 0.0}
    detalle = {c: [] for c in tot}

    # Un Balance es la ÚLTIMA POSICIÓN CONOCIDA hasta la fecha, no el
    # movimiento del mes. Una cuenta sin movimiento en el mes (capital social,
    # activo fijo comprado hace años) conserva su saldo anterior: si se
    # filtrara por mes exacto, esas cuentas simplemente desaparecerían del
    # Balance y el Capital saldría en cero. Por eso se toma, por cuenta, el
    # renglón más reciente con fecha <= al periodo pedido.
    def _posicion_hasta(a, m):
        ult = {}
        for s in saldos:
            if (s['anio'], s['mes']) > (a, m):
                continue
            k = s['codigo']
            if k not in ult or (s['anio'], s['mes']) > (ult[k]['anio'], ult[k]['mes']):
                ult[k] = s
        return ult

    ultimo = _posicion_hasta(anio, mes)
    es_cierre = _es_periodo_de_cierre(ultimo, cuentas)
    nota_cierre = ''
    if es_cierre:
        # Retroceder al último periodo con posición real. Se retrocede mes a mes
        # en vez de asumir "el anterior" porque una empresa puede tener varios
        # meses sin movimiento antes del cierre.
        a, m = anio, mes
        for _ in range(12):
            m -= 1
            if m == 0:
                a, m = a - 1, 12
            candidato = _posicion_hasta(a, m)
            if not _es_periodo_de_cierre(candidato, cuentas):
                ultimo = candidato
                nota_cierre = (
                    f'El periodo {anio}-{mes:02d} es el del asiento de cierre y '
                    f'reapertura: en el libro TODAS las cuentas quedan en cero. '
                    f'Se reporta la última posición real, al {a}-{m:02d}. NO es '
                    f'el saldo al cierre del ejercicio: para eso hay que separar '
                    f'el asiento de cierre de los movimientos ordinarios del mes.')
                break
        else:
            nota_cierre = (f'{anio}-{mes:02d} está arrasado por el cierre y no se '
                           f'encontró ningún periodo anterior con posición real.')

    for codigo, s in ultimo.items():
        cta = cuentas.get(codigo)
        if not cta or cta.get('es_acumulativa'):
            continue
        clase = cta['clase']
        if clase not in tot:
            continue
        saldo = s['saldo_final']
        valor = -saldo if clase in ('PASIVO', 'CAPITAL') else saldo
        tot[clase] += valor
        detalle[clase].append({'codigo': codigo, 'nombre': cta['nombre'], 'valor': valor})

    # Resultado del ejercicio: las cuentas de resultados (ingresos, costos,
    # gastos, financieros, otros) NO se cierran contra el capital hasta el
    # cierre del año. A mitad de ejercicio la ecuación contable es
    #     Activo = Pasivo + Capital + Resultado acumulado
    # Omitirlo produce un descuadre que crece mes a mes — y que se confunde
    # fácilmente con un error de extracción cuando en realidad es la utilidad
    # del periodo que todavía no se ha capitalizado.
    CLASES_RESULTADO = {'INGRESO', 'COSTO', 'GASTO', 'FINANCIERO', 'OTRO'}
    acumulado_total = 0.0
    for codigo, s in ultimo.items():
        cta = cuentas.get(codigo)
        if not cta or cta.get('es_acumulativa'):
            continue
        if cta['clase'] not in CLASES_RESULTADO:
            continue
        # saldo = debe - haber. Ingresos quedan negativos (se abonan) y los
        # gastos positivos, así que -saldo da la utilidad con signo correcto.
        acumulado_total += -s['saldo_final']

    # SEPARAR EL EJERCICIO EN CURSO DE LO ACUMULADO DE AÑOS ANTERIORES.
    #
    # Hace falta desde que la extracción excluye el asiento de cierre (ver
    # `ASIENTOS_DE_CIERRE` en erp/sap_b1.py). Antes, SAP cerraba las cuentas de
    # resultados cada diciembre, así que su saldo era siempre el del año en
    # curso. Al no aplicar ese asiento —que es lo correcto, porque también
    # arrasaba las cuentas de balance— las de resultados ya nunca se cierran y
    # acumulan desde el origen de la empresa.
    #
    # Sin esta separación la ecuación seguía cuadrando (el total es el mismo),
    # pero `resultado_ejercicio` traía la utilidad de TODOS los años juntos y
    # dejaba de articular con el Estado de Resultados del año. Se detectó justo
    # así: en 2020-12 el Balance decía 35,435,285 y el Estado de Resultados
    # acumulado 15,395,516 — la diferencia era, al peso, el resultado de 2019.
    ejercicio = 0.0
    for s in saldos:
        if s['anio'] != anio or s['mes'] > mes:
            continue
        cta = cuentas.get(s['codigo'])
        if not cta or cta.get('es_acumulativa'):
            continue
        if cta['clase'] not in CLASES_RESULTADO:
            continue
        ejercicio += -(s['debe'] - s['haber'])

    resultado = ejercicio
    resultados_acumulados = acumulado_total - ejercicio
    capital_total = tot['CAPITAL'] + acumulado_total
    descuadre = tot['ACTIVO'] - (tot['PASIVO'] + capital_total)
    return {
        'anio': anio, 'mes': mes,
        'activo': tot['ACTIVO'], 'pasivo': tot['PASIVO'],
        'capital_contable': tot['CAPITAL'],
        'resultado_ejercicio': resultado,
        'resultados_acumulados': resultados_acumulados,
        'capital': capital_total,
        'es_cierre_anual': es_cierre,
        'nota': nota_cierre,
        'descuadre': descuadre,
        'cuadra': abs(descuadre) <= max(1.0, abs(tot['ACTIVO']) * 0.001),
        'detalle': detalle,
        'vertical': analisis_vertical(
            {'Pasivo': tot['PASIVO'], 'Capital contable': tot['CAPITAL'],
             'Resultado del ejercicio': resultado}, tot['ACTIVO'], 'activo total'),
    }
