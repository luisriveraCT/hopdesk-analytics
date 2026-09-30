# -*- coding: utf-8 -*-
"""
===============================================================================
 PRECISIÓN DE PRONÓSTICO — backtest honesto de los métodos del tablero
===============================================================================
Produce exactamente lo que pide la pestaña "Precision_Pronostico" de
KPIs_Finanzas.xlsx (MAPE, MPE, RSFE, MAD, tracking signal, banda μ+1σ y
semáforo) y además responde la pregunta que esa pestaña no contesta:
¿CUÁL de los métodos de pronóstico es el más preciso para esta operación?

LA PARTE QUE IMPORTA: el backtest es de origen móvil (walk-forward). Para
pronosticar el mes t solo se usa información hasta t-1, se compara contra el
real de t, y se avanza. Nunca se ajusta un método con datos que en su momento
no existían. Eso es lo que hace que el MAPE resultante sea creíble: si en vez
de esto se ajustara el modelo con toda la historia y luego se "predijera" el
pasado, el MAPE saldría bonito y mentiroso.

SINCRONÍA CON EL TABLERO — IMPORTANTE:
Los 5 métodos de abajo son la contraparte en Python de las funciones
pronosticoSMA/SES/Lineal/Estacional/Holt de dashboard/plantilla.html. Si se
cambia un parámetro allá (ventana=3, alpha=0.3, beta=0.1) hay que cambiarlo
aquí, o el tablero y el reporte de finanzas dirán cosas distintas sobre el
mismo mes. Los parámetros viven en PARAMS justo para que el cambio sea en un
solo lugar por archivo y sea fácil de cotejar.
===============================================================================
"""
from statistics import mean, pstdev, stdev

PARAMS = {
    'sma_ventana': 3,     # = ventana en pronosticoSMA del tablero
    'ses_alpha': 0.3,     # = alpha en pronosticoSES
    'holt_alpha': 0.3,    # = alpha en pronosticoHolt
    'holt_beta': 0.1,     # = beta  en pronosticoHolt
}

UMBRAL_VERDE = 0.05    # MAPE ≤ 5%  (igual que KPIs_Finanzas.xlsx, celda C3)
UMBRAL_AMBAR = 0.10    # MAPE ≤ 10% (celda G3)


# ---------------------------------------------------------------------------
# Los 5 métodos. Cada uno recibe la historia (lista de floats, meses
# consecutivos sin huecos) y cuántos meses hacia adelante pronosticar.
# ---------------------------------------------------------------------------
def sma(historia, n_futuro, ventana=None):
    w = min(ventana or PARAMS['sma_ventana'], len(historia))
    prom = sum(historia[-w:]) / w
    return [prom] * n_futuro


def ses(historia, n_futuro, alpha=None):
    a = alpha if alpha is not None else PARAMS['ses_alpha']
    nivel = historia[0]
    for v in historia[1:]:
        nivel = a * v + (1 - a) * nivel
    return [nivel] * n_futuro


def lineal(historia, n_futuro):
    n = len(historia)
    xs = list(range(n))
    mx, my = mean(xs), mean(historia)
    num = sum((xs[i] - mx) * (historia[i] - my) for i in range(n))
    den = sum((x - mx) ** 2 for x in xs)
    b = num / den if den else 0.0
    a = my - b * mx
    return [a + b * (n + i) for i in range(n_futuro)]


def estacional(historia, n_futuro, meses=None):
    """Promedio del mismo mes calendario en años anteriores.
    'meses' es la lista de meses calendario (0-11) alineada con historia."""
    if not meses:
        return [mean(historia)] * n_futuro
    global_prom = mean(historia)
    ultimo = meses[-1]
    out = []
    for i in range(n_futuro):
        cm = (ultimo + 1 + i) % 12
        mismos = [historia[j] for j in range(len(historia)) if meses[j] == cm]
        out.append(mean(mismos) if mismos else global_prom)
    return out


def holt(historia, n_futuro, alpha=None, beta=None):
    a = alpha if alpha is not None else PARAMS['holt_alpha']
    b = beta if beta is not None else PARAMS['holt_beta']
    nivel = historia[0]
    tendencia = historia[1] - historia[0] if len(historia) > 1 else 0.0
    for v in historia[1:]:
        nivel_ant = nivel
        nivel = a * v + (1 - a) * (nivel + tendencia)
        tendencia = b * (nivel - nivel_ant) + (1 - b) * tendencia
    return [nivel + (i + 1) * tendencia for i in range(n_futuro)]


METODOS = {
    'sma': ('Promedio móvil (SMA)', sma),
    'ses': ('Suavizamiento exponencial simple (SES)', ses),
    'lineal': ('Regresión lineal (tendencia)', lineal),
    'estacional': ('Promedio estacional', estacional),
    'holt': ('Holt (tendencia + nivel)', holt),
}


# ---------------------------------------------------------------------------
# Backtest de origen móvil
# ---------------------------------------------------------------------------
def backtest(serie, metodo, min_historia=12, horizonte=1):
    """serie: lista de dicts {'ym': int, 'mes_cal': 0-11, 'real': float}
    Regresa una lista de filas con pronóstico vs real, mes por mes.

    min_historia: cuántos meses se exigen antes del primer pronóstico. 12 por
    default para que el método estacional tenga al menos un año — con menos,
    ese método no tendría de dónde sacar el mismo mes del año pasado y se
    estaría comparando contra algo que no es.
    """
    nombre, fn = METODOS[metodo]
    filas = []
    for i in range(min_historia, len(serie) - horizonte + 1):
        historia = [p['real'] for p in serie[:i]]
        meses = [p['mes_cal'] for p in serie[:i]]
        if metodo == 'estacional':
            pron = fn(historia, horizonte, meses)
        else:
            pron = fn(historia, horizonte)
        objetivo = serie[i + horizonte - 1]
        filas.append({
            'ym': objetivo['ym'],
            'pronostico': max(0.0, pron[horizonte - 1]),
            'real': objetivo['real'],
        })
    return filas


def metricas(filas):
    """Calcula, acumulando mes a mes, exactamente las columnas de la pestaña
    Precision_Pronostico: error, |error|, APE, PE, MAPE acum., MPE acum.,
    RSFE, MAD, tracking signal, banda de control (μ+1σ) y estado."""
    out, apes, errores, abs_errores = [], [], [], []
    for f in filas:
        real, pron = f['real'], f['pronostico']
        error = real - pron                      # + = subestimamos (igual que el Excel: C−B)
        abs_error = abs(error)
        ape = abs_error / real if real else None
        pe = error / real if real else None
        errores.append(error)
        abs_errores.append(abs_error)
        if ape is not None:
            apes.append(ape)
        mape_acum = mean(apes) if apes else None
        # MPE acumulado = promedio de todos los PE hasta este mes inclusive
        pes = [o['pe'] for o in out if o['pe'] is not None]
        if pe is not None:
            pes = pes + [pe]
        mpe_acum = mean(pes) if pes else None
        rsfe = sum(errores)
        mad = mean(abs_errores) if abs_errores else None
        ts = (rsfe / mad) if mad else None
        banda = (mean(apes) + (stdev(apes) if len(apes) > 1 else 0.0)) if apes else None
        if ape is None:
            estado = None
        elif ape <= UMBRAL_VERDE:
            estado = 'Verde'
        elif ape <= UMBRAL_AMBAR:
            estado = 'Amarillo'
        else:
            estado = 'Rojo'
        out.append({
            'ym': f['ym'], 'pronostico': pron, 'real': real,
            'error': error, 'error_abs': abs_error, 'ape': ape, 'pe': pe,
            'mape_acum': mape_acum, 'mpe_acum': mpe_acum, 'rsfe': rsfe,
            'mad': mad, 'tracking_signal': ts, 'banda_control': banda,
            'estado': estado,
        })
    return out


def resumen(filas_metricas):
    """Bloque 'RESUMEN ESTADÍSTICO' de la pestaña (filas 19-25)."""
    apes = [f['ape'] for f in filas_metricas if f['ape'] is not None]
    pes = [f['pe'] for f in filas_metricas if f['pe'] is not None]
    if not apes:
        return {}
    sigma = stdev(apes) if len(apes) > 1 else 0.0
    mape = mean(apes)
    return {
        'mape_global': mape,
        'mpe_global': mean(pes) if pes else None,
        'sigma_ape': sigma,
        'banda_control': mape + sigma,
        'pct_meses_dentro_umbral': sum(1 for a in apes if a <= UMBRAL_AMBAR) / len(apes),
        'tracking_signal_final': filas_metricas[-1]['tracking_signal'],
        'n_meses': len(apes),
        'alerta_sesgo': abs(filas_metricas[-1]['tracking_signal'] or 0) > 4,
    }


def comparar_metodos(serie, min_historia=12, horizonte=1):
    """Corre el backtest con los 5 métodos y los ordena por MAPE.
    Esta es la tabla que contesta 'cuál método uso'."""
    resultados = []
    for clave, (nombre, _) in METODOS.items():
        filas = backtest(serie, clave, min_historia, horizonte)
        if not filas:
            continue
        met = metricas(filas)
        res = resumen(met)
        if not res:
            continue
        res.update({'metodo': clave, 'nombre': nombre, 'filas': met})
        resultados.append(res)
    resultados.sort(key=lambda r: r['mape_global'])
    return resultados


def interpretar(res):
    """Traduce las métricas a una frase que alguien pueda accionar.
    El sesgo (MPE) es la parte que más se ignora y la que más cuesta: un
    pronóstico que falla 8% pero siempre hacia el mismo lado es peor que uno
    que falla 8% alternando, porque el error se acumula en el presupuesto."""
    mape, mpe, ts = res['mape_global'], res.get('mpe_global'), res.get('tracking_signal_final')
    partes = []
    if mape <= UMBRAL_VERDE:
        partes.append(f'Precisión excelente (MAPE {mape:.1%}).')
    elif mape <= UMBRAL_AMBAR:
        partes.append(f'Precisión aceptable (MAPE {mape:.1%}).')
    elif mape <= 0.20:
        partes.append(f'Precisión mejorable (MAPE {mape:.1%}).')
    else:
        partes.append(f'Precisión deficiente (MAPE {mape:.1%}): el pronóstico no es confiable para presupuestar.')
    if mpe is not None:
        if abs(mpe) < 0.01:
            partes.append('Sin sesgo porcentual relevante: los errores se compensan entre meses.')
        elif mpe > 0:
            partes.append(f'Sesgo porcentual a SUBESTIMAR ({mpe:+.1%}): el real suele salir por encima.')
        else:
            partes.append(f'Sesgo porcentual a SOBREESTIMAR ({mpe:+.1%}): el real suele salir por debajo.')
    if ts is not None and abs(ts) > 4:
        direccion = 'quedándose CORTO' if ts > 0 else 'PASÁNDOSE'
        partes.append(f'ALERTA de tracking signal ({ts:+.1f}): en pesos acumulados el método viene '
                      f'{direccion} de forma sistemática, no por ruido — hay que recalibrarlo.')
        # MPE (porcentual) y TS (pesos acumulados) pueden apuntar a lados
        # distintos, y no es un error: significa que el método le atina mejor a
        # los meses chicos que a los grandes. Vale la pena decirlo, porque
        # presupuestar con el % engaña cuando el error real vive en los meses
        # de mayor volumen.
        if mpe is not None and mpe != 0 and (mpe > 0) != (ts > 0):
            partes.append('Ojo: el sesgo en porcentaje y el sesgo en pesos apuntan a lados opuestos, '
                          'lo que indica que el método falla distinto en los meses grandes que en los '
                          'chicos — para presupuestar, pesa más el sesgo en pesos.')
    return ' '.join(partes)
