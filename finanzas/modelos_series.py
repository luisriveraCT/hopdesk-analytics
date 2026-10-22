# -*- coding: utf-8 -*-
"""
===============================================================================
 MODELOS DE SERIES DE TIEMPO — ARIMA/SARIMA, correlogramas y pruebas
===============================================================================
Lo que la vista de análisis no puede hacer en el navegador: ajustar un modelo
por máxima verosimilitud y someterlo a las pruebas que dicen si se puede creer.

Recibe la serie TAL COMO SE VE en pantalla —la ventana, la periodicidad, sin
los meses dudosos si están excluidos— y devuelve todo en un diccionario listo
para JSON. No lee el almacén ni sabe de empresas: es estadística sobre una
lista de números, y por eso se puede probar sola.

EL ORDEN EN QUE SE TRABAJA, que es el orden en que se debe leer:

  1. ¿Es estacionaria? ADF (H0: tiene raíz unitaria) y KPSS (H0: es
     estacionaria) sobre el nivel y sobre las diferencias. Se usan las dos
     porque se equivocan en sentidos opuestos: si coinciden, la conclusión es
     firme; si no, se dice.
  2. ¿Tiene estacionalidad? Descomposición STL y su "fuerza estacional"
     (1 − Var(residuo) / Var(estacional + residuo)). Pasa de 0.64 → una
     diferencia estacional; es el criterio de uso común para elegir D.
  3. ACF y PACF de la serie ya diferenciada: lo que sugiere los órdenes.
  4. El modelo: automático (búsqueda escalonada por AICc, la de Hyndman y
     Khandakar) o con los órdenes que el usuario escriba.
  5. ¿Los residuos son ruido? Ljung-Box (H0: sin autocorrelación),
     Jarque-Bera (H0: normalidad) y varianza constante (H0: homocedasticidad).
     Un modelo cuyos residuos todavía tienen estructura no la explicó.
  6. ¿Pronostica mejor que no hacer nada? Se esconden los últimos periodos, se
     ajusta con el resto y se compara contra el pronóstico ingenuo (repetir el
     último valor, o el del mismo periodo del año anterior). Si no le gana al
     ingenuo, el modelo no aporta, por bonitas que se vean sus p.

HUECOS: los periodos sin dato (o excluidos por dudosos) viajan como None. El
modelo los maneja directamente —el filtro de Kalman salta las observaciones
faltantes—; las pruebas de raíz unitaria y STL no, así que para ellas se
interpolan los huecos interiores, y se dice cuántos.

LOG: solo con todos los valores > 0. Se rechaza aquí también aunque la
pantalla ya lo bloquee: la regla no puede vivir solo en el lado que se puede
saltar. El pronóstico se regresa a la escala original con exp(), y lo que se
obtiene es la MEDIANA del pronóstico, no la media; se dice en la nota.
===============================================================================
"""
import math
import time
import warnings

import numpy as np

PERIODICIDADES = (12, 6, 4, 3, 2, 1)

# Lo que se acepta del navegador. Órdenes altos con pocos datos no se pueden
# estimar con honestidad, y una búsqueda sin tope puede tardar minutos.
N_MAX = 600
P_MAX, Q_MAX, D_MAX = 5, 5, 2
PS_MAX, QS_MAX, DS_MAX = 2, 2, 1
H_MAX = 36
REZAGOS_MAX = 48
ALFAS = (0.01, 0.05, 0.10)
# La búsqueda automática se queda más corta que el manual: con seis o siete
# años de datos, un SAR o SMA de orden 2 casi nunca se estima con precisión,
# y cada uno cuesta segundos. Quien lo quiera probar lo escribe en manual.
P_AUTO, Q_AUTO, PS_AUTO, QS_AUTO = 3, 3, 1, 1
N_MIN = 12                    # menos que esto no es una serie, es una anécdota
FUERZA_ESTACIONAL = 0.64      # umbral para una diferencia estacional
# La búsqueda se corta por NÚMERO de modelos, no por tiempo: con un tope de
# tiempo, los mismos datos darían un modelo distinto según qué tan ocupado esté
# el servidor, y una prueba de hipótesis que cambia de resultado sola no sirve.
# El tiempo queda solo como freno de emergencia, y si se usa se dice.
TOPE_AJUSTES = 40
TOPE_SEGUNDOS = 90.0


class ErrorModelo(ValueError):
    """Un motivo para no calcular, con un código que la pantalla traduce."""
    def __init__(self, codigo, **datos):
        super().__init__(codigo)
        self.codigo, self.datos = codigo, datos


def _num(x, dec=6):
    """float listo para JSON: None en vez de nan o inf."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return float(f'{x:.{dec}g}')


def _entero(v, lo, hi, campo):
    """Un entero dentro de [lo, hi]; 2.5 o 'x' no son un orden."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ErrorModelo('parametro', campo=campo, lo=lo, hi=hi)
    if not f.is_integer() or not lo <= f <= hi:
        raise ErrorModelo('parametro', campo=campo, lo=lo, hi=hi)
    return int(f)


def _interpolar(y):
    """Rellena huecos INTERIORES linealmente; devuelve (serie, cuántos)."""
    y = y.copy()
    malos = ~np.isfinite(y)
    n = int(malos.sum())
    if n:
        idx = np.arange(len(y))
        y[malos] = np.interp(idx[malos], idx[~malos], y[~malos])
    return y, n


# --- 1 y 2: estacionariedad y estacionalidad --------------------------------
def _adf(x):
    from statsmodels.tsa.stattools import adfuller
    # statsmodels va a cambiar lo que devuelve adfuller (una tupla hoy, un
    # objeto después). Se pide la tupla explícitamente donde ya existe la
    # opción, y en versiones viejas que no la conocen, la tupla es lo de siempre.
    try:
        res = adfuller(x, autolag='AIC', regression='c', result_object=False)
    except TypeError:
        res = adfuller(x, autolag='AIC', regression='c')
    est, p, lags, nobs, crit = res[:5]
    return {'estadistico': _num(est), 'p': _num(p), 'rezagos': int(lags), 'n': int(nobs),
            'criticos': {k: _num(v) for k, v in crit.items()}}


def _kpss(x):
    from statsmodels.tsa.stattools import kpss
    from statsmodels.tools.sm_exceptions import InterpolationWarning
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        est, p, lags, crit = kpss(x, regression='c', nlags='auto')
    # La tabla de KPSS solo cubre p entre 0.01 y 0.10: fuera de ahí el valor
    # es una cota, y se dice cuál.
    cota = None
    if any(issubclass(a.category, InterpolationWarning) for a in w):
        cota = 'mayor' if p >= 0.1 else 'menor'
    return {'estadistico': _num(est), 'p': _num(p), 'rezagos': int(lags), 'cota': cota,
            'criticos': {k: _num(v) for k, v in crit.items()}}


def _diferenciar(x, d, D, s):
    for _ in range(D):
        x = x[s:] - x[:-s]
    for _ in range(d):
        x = np.diff(x)
    return x


def pruebas_estacionariedad(yc, s, alfa):
    """ADF y KPSS sobre el nivel, la primera diferencia y la estacional."""
    out, d_sug = [], None
    casos = [('nivel', 0, 0), ('d1', 1, 0), ('d2', 2, 0)]
    if s > 1 and len(yc) >= 3 * s:
        casos += [('ds', 0, 1), ('d1ds', 1, 1)]
    for nombre, d, D in casos:
        x = _diferenciar(yc, d, D, s)
        if len(x) < 10 or np.allclose(x, x[0]):
            continue
        fila = {'serie': nombre, 'd': d, 'D': D}
        try:
            fila['adf'] = _adf(x)
        except Exception:                                    # noqa: BLE001
            fila['adf'] = None
        try:
            fila['kpss'] = _kpss(x)
        except Exception:                                    # noqa: BLE001
            fila['kpss'] = None
        out.append(fila)
    # d sugerido: la menor diferenciación (sin la estacional) con la que KPSS
    # ya no rechaza estacionariedad. KPSS manda porque su H0 es la que se
    # quiere conservar; ADF se reporta para ver si coincide.
    for f in out:
        if f['D'] == 0 and f['kpss'] and f['kpss']['p'] is not None and f['kpss']['p'] > alfa:
            d_sug = f['d']
            break
    if d_sug is None:
        d_sug = 1
    return out, d_sug


def descomposicion_stl(yc, s):
    """STL robusta: componentes y fuerza de tendencia y de estacionalidad."""
    if s < 2 or len(yc) < 2 * s + 1:
        return None
    from statsmodels.tsa.seasonal import STL
    r = STL(yc, period=s, robust=True).fit()
    vr = np.var(r.resid)
    f_est = max(0.0, 1 - vr / np.var(r.seasonal + r.resid)) if np.var(r.seasonal + r.resid) else 0.0
    f_ten = max(0.0, 1 - vr / np.var(r.trend + r.resid)) if np.var(r.trend + r.resid) else 0.0
    return {'fuerza_estacional': _num(f_est), 'fuerza_tendencia': _num(f_ten),
            'tendencia': [_num(v) for v in r.trend], 'estacional': [_num(v) for v in r.seasonal],
            'residuo': [_num(v) for v in r.resid]}


# --- 3: correlogramas --------------------------------------------------------
def correlogramas(x, rezagos, alfa, con_pacf=True):
    from statsmodels.tsa.stattools import acf, pacf
    n = len(x)
    k = int(min(rezagos, max(1, n // 2 - 1)))
    z = _z(alfa)
    a, ic = acf(x, nlags=k, alpha=alfa, fft=False)
    # Banda de Bartlett para la ACF (crece con los rezagos); para la PACF la
    # banda constante ±z/√n.
    out = {'rezagos': k, 'n': n,
           'acf': [_num(v) for v in a[1:]],
           'acf_banda': [_num(ic[i][1] - a[i]) for i in range(1, k + 1)]}
    if con_pacf:
        p = pacf(x, nlags=k, method='ywm')
        out['pacf'] = [_num(v) for v in p[1:]]
        out['pacf_banda'] = _num(z / math.sqrt(n))
    return out


def _z(alfa):
    from scipy.stats import norm
    return float(norm.ppf(1 - alfa / 2))


# --- 4: el modelo ------------------------------------------------------------
def _ajustar(y, orden, est, s, avisos=None):
    """Máxima verosimilitud exacta por espacio de estados (filtro de Kalman),
    que admite huecos. Se usa la clase ARIMA y no SARIMAX directo: con la misma
    especificación encuentra óptimos mejores (medido: AICc 22.7 contra 25.1 en
    la misma serie), por cómo arranca los parámetros. Con d + D = 0 lleva
    constante; diferenciada, no (la constante se va con la diferencia)."""
    from statsmodels.tsa.arima.model import ARIMA
    d, D = orden[1], est[1]
    tendencia = 'c' if d + D == 0 else 'n'
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        m = ARIMA(y, order=tuple(orden),
                  seasonal_order=(tuple(est) + (s,)) if s > 1 and any(est) else (0, 0, 0, 0),
                  trend=tendencia, enforce_stationarity=True, enforce_invertibility=True)
        r = m.fit(method='statespace')
    if avisos is not None:
        conv = r.mle_retvals.get('converged', True) if isinstance(r.mle_retvals, dict) else True
        if not conv or any('converge' in str(a.message).lower() for a in w):
            avisos.append('no_converge')
    return r


def _aicc(r):
    v = getattr(r, 'aicc', None)
    return float(v) if v is not None and math.isfinite(v) else math.inf


def busqueda_automatica(y, d, D, s, estacional):
    """Búsqueda escalonada por AICc: empieza en unos cuantos modelos y se mueve
    a los vecinos (un orden más o menos) mientras alguno mejore."""
    inicio = time.time()
    probados, ajustes = {}, {}

    def probar(p, q, P, Q):
        clave = (p, q, P, Q)
        if clave in probados:
            return probados[clave]
        if not (0 <= p <= P_AUTO and 0 <= q <= Q_AUTO and 0 <= P <= PS_AUTO and 0 <= Q <= QS_AUTO):
            return math.inf
        if len(probados) >= TOPE_AJUSTES or time.time() - inicio > TOPE_SEGUNDOS:
            return math.inf
        try:
            r = _ajustar(y, (p, d, q), (P, D, Q), s)
            v = _aicc(r)
            ajustes[clave] = r
        except Exception:                                    # noqa: BLE001
            v = math.inf
        probados[clave] = v
        return v

    # Semillas de lo barato a lo caro: con un tope de tiempo, lo que alcance a
    # probarse tiene que ser lo más informativo por segundo. Un SARIMA con MA
    # estacional de orden 2 llega a tardar cinco segundos por ajuste.
    if estacional:
        semillas = [(0, 0, 0, 0), (1, 0, 1, 0), (0, 1, 0, 1), (1, 1, 1, 1)]
    else:
        semillas = [(0, 0, 0, 0), (1, 0, 0, 0), (0, 1, 0, 0), (1, 1, 0, 0), (2, 2, 0, 0)]
    mejor = min(semillas, key=lambda c: probar(*c))
    while True:
        p, q, P, Q = mejor
        vecinos = [(p + a, q + b, P, Q) for a, b in
                   ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1))]
        if estacional:
            vecinos += [(p, q, P + a, Q + b) for a, b in
                        ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1))]
        cand = min(vecinos, key=lambda c: probar(*c))
        if probar(*cand) < probar(*mejor) - 1e-9:
            mejor = cand
        else:
            break
        if len(probados) >= TOPE_AJUSTES or time.time() - inicio > TOPE_SEGUNDOS:
            break
    ranking = sorted(((v, k) for k, v in probados.items() if math.isfinite(v)))
    alternativas = [{'orden': [k[0], d, k[1]], 'estacional': [k[2], D, k[3]], 'aicc': _num(v)}
                    for v, k in ranking[:6]]
    agotado = len(probados) >= TOPE_AJUSTES or time.time() - inicio > TOPE_SEGUNDOS
    # El ganador ya está ajustado: se entrega para no repetir el ajuste más caro.
    return mejor, alternativas, len(probados), agotado, ajustes.get(mejor)


# --- 5 y 6: diagnóstico y validación ----------------------------------------
def diagnostico(r, s, k_param):
    from statsmodels.stats.diagnostic import acorr_ljungbox
    from statsmodels.stats.stattools import jarque_bera
    burn = int(getattr(r, 'loglikelihood_burn', 0) or 0)
    e = np.asarray(r.resid, dtype=float)[burn:]
    e = e[np.isfinite(e)]
    out = {'n': int(len(e))}
    if len(e) < 8:
        return out, e
    lags = sorted({l for l in ((s if s > 1 else 6), (2 * s if s > 1 else 12)) if l < len(e) - 1})
    lags = [l for l in lags if l > k_param] or [min(len(e) - 2, k_param + 1)]
    lb = acorr_ljungbox(e, lags=lags, model_df=k_param, return_df=True)
    out['ljung_box'] = [{'rezagos': int(l), 'estadistico': _num(lb.loc[l, 'lb_stat']),
                         'p': _num(lb.loc[l, 'lb_pvalue'])} for l in lb.index]
    jb, jbp, sesgo, curt = jarque_bera(e)
    out['jarque_bera'] = {'estadistico': _num(jb), 'p': _num(jbp), 'sesgo': _num(sesgo),
                          'curtosis': _num(curt)}
    try:
        h = r.test_heteroskedasticity('breakvar')[0]
        out['heterocedasticidad'] = {'estadistico': _num(h[0]), 'p': _num(h[1])}
    except Exception:                                        # noqa: BLE001
        out['heterocedasticidad'] = None
    return out, e


def _raices(r):
    """Módulo mínimo de las raíces AR y MA: cerca de 1 = al borde de no ser
    estacionario (AR) o invertible (MA)."""
    out = {}
    for nombre, attr in (('ar', 'arroots'), ('ma', 'maroots')):
        try:
            v = np.abs(np.asarray(getattr(r, attr)))
            out[nombre] = _num(v.min()) if len(v) else None
        except Exception:                                    # noqa: BLE001
            out[nombre] = None
    return out


def validacion(y, orden, est, s, log, n_obs):
    """Esconde los últimos k periodos, ajusta con el resto, compara contra el
    ingenuo. Todo en la escala original."""
    k = s if s > 1 else 4
    k = min(k, max(2, n_obs // 4))
    if n_obs - k < N_MIN:
        return None
    entren, prueba = y[:-k], y[-k:]
    try:
        r = _ajustar(entren, orden, est, s)
        f = np.asarray(r.get_forecast(k).predicted_mean, dtype=float)
    except Exception:                                        # noqa: BLE001
        return None
    # Ingenuo: el mismo periodo del año anterior si hay estacionalidad y datos;
    # si no, el último valor conocido.
    hist = entren[np.isfinite(entren)]
    if s > 1 and len(entren) >= s and np.all(np.isfinite(entren[-s:])):
        ing = np.array([entren[len(entren) - s + (i % s)] for i in range(k)])
        tipo = 'estacional'
    else:
        ing = np.repeat(hist[-1], k)
        tipo = 'ultimo'
    if log:
        f, ing, real = np.exp(f), np.exp(ing), np.exp(prueba)
    else:
        real = prueba
    ok = np.isfinite(real)
    if ok.sum() < 2:
        return None

    def met(pred):
        err = real[ok] - pred[ok]
        mape = (float(np.mean(np.abs(err / real[ok]))) if np.all(real[ok] != 0) else None)
        return {'mae': _num(np.mean(np.abs(err))), 'rmse': _num(math.sqrt(np.mean(err ** 2))),
                'mape': _num(mape)}
    m, n = met(f), met(ing)
    razon = (m['rmse'] / n['rmse']) if m['rmse'] is not None and n['rmse'] else None
    return {'k': int(k), 'modelo': m, 'ingenuo': n, 'ingenuo_tipo': tipo,
            'razon_rmse': _num(razon),
            'real': [_num(v) for v in real], 'pronostico': [_num(v) for v in f]}


def calentar():
    """Carga statsmodels y hace un ajuste mínimo. La primera vez cuesta unos
    diez segundos de importaciones; el servidor lo hace al arrancar para que no
    los pague quien pide el primer modelo."""
    y = np.sin(np.arange(40) / 3.0) + np.arange(40) / 40.0
    _ajustar(y, (1, 0, 0), (0, 0, 0), 1)
    _adf(y)
    _kpss(y)
    correlogramas(y, 6, 0.05)


# --- todo junto ---------------------------------------------------------------
def analizar(valores, periodicidad, params=None):
    """El análisis completo. `valores` es la serie de la ventana (None = sin
    dato). Lanza ErrorModelo con un código cuando no se puede calcular."""
    params = params or {}
    if periodicidad not in PERIODICIDADES:
        raise ErrorModelo('periodicidad', lista=list(PERIODICIDADES))
    if not isinstance(valores, (list, tuple)) or len(valores) > N_MAX:
        raise ErrorModelo('serie_larga', max=N_MAX)
    s = int(periodicidad)
    alfa = float(params.get('alfa', 0.05))
    if alfa not in ALFAS:
        raise ErrorModelo('parametro', campo='alfa', lo=min(ALFAS), hi=max(ALFAS))
    rezagos = _entero(params.get('rezagos', 24), 1, REZAGOS_MAX, 'rezagos')
    h = _entero(params.get('horizonte', max(s, 4)), 1, H_MAX, 'horizonte')
    log = bool(params.get('log'))
    modo = params.get('modo', 'auto')
    if modo not in ('auto', 'manual'):
        raise ErrorModelo('parametro', campo='modo', lo=0, hi=0)

    y = np.array([np.nan if v is None else float(v) for v in valores], dtype=float)
    # Se recortan los huecos de las orillas: un modelo no "empieza" en un hueco.
    validos = np.flatnonzero(np.isfinite(y))
    if len(validos) < N_MIN:
        raise ErrorModelo('pocos_datos', n=int(len(validos)), min=N_MIN)
    ini, fin = int(validos[0]), int(validos[-1]) + 1
    y = y[ini:fin]
    n_obs = int(np.isfinite(y).sum())
    if log:
        malos = int((y[np.isfinite(y)] <= 0).sum())
        if malos:
            raise ErrorModelo('log_no_positivo', n=malos)
        y = np.log(y)
    avisos = []
    yc, interpolados = _interpolar(y)
    if interpolados:
        avisos.append('interpolados')

    # Con muy pocos años no hay estacionalidad que estimar.
    estacional_posible = s > 1 and len(y) >= 2 * s + 4
    if s > 1 and not estacional_posible:
        avisos.append('sin_estacional')
    pruebas, d_sug = pruebas_estacionariedad(yc, s, alfa)
    stl = descomposicion_stl(yc, s) if estacional_posible else None
    D_sug = 1 if (stl and (stl['fuerza_estacional'] or 0) > FUERZA_ESTACIONAL) else 0

    if modo == 'manual':
        o = params.get('orden') or [0, 0, 0]
        e = params.get('estacional') or [0, 0, 0]
        orden = [_entero(o[0], 0, P_MAX, 'p'), _entero(o[1], 0, D_MAX, 'd'), _entero(o[2], 0, Q_MAX, 'q')]
        est = [_entero(e[0], 0, PS_MAX, 'P'), _entero(e[1], 0, DS_MAX, 'D'), _entero(e[2], 0, QS_MAX, 'Q')]
        if not estacional_posible and any(est):
            raise ErrorModelo('estacional_sin_datos', n=int(len(y)), min=2 * s + 4)
        alternativas, probados, agotado, ya = None, 1, False, None
    else:
        d, D = d_sug, (D_sug if estacional_posible else 0)
        # Diferenciar de más destruye información: con una estacional, rara vez
        # hace falta además más de una normal.
        if D and d > 1:
            d = 1
        (p, q, P, Q), alternativas, probados, agotado, ya = busqueda_automatica(
            y, d, D, s, estacional_posible)
        orden, est = [p, d, q], [P, D, Q]
        if agotado:
            avisos.append('busqueda_cortada')
    if len(y) - orden[1] - est[1] * s < N_MIN:
        raise ErrorModelo('pocos_datos', n=int(len(y) - orden[1] - est[1] * s), min=N_MIN)

    try:
        r = ya if ya is not None else _ajustar(y, orden, est, s)
    except Exception:                                        # noqa: BLE001
        raise ErrorModelo('no_ajusta')
    if not (r.mle_retvals or {}).get('converged', True):
        avisos.append('no_converge')

    # Coeficientes con su error estándar, z, p e intervalo.
    ic = np.asarray(r.conf_int(alpha=alfa))
    nombres = list(r.model.param_names)
    coef = [{'nombre': nm, 'coef': _num(r.params[i]), 'ee': _num(r.bse[i]),
             'z': _num(r.zvalues[i]), 'p': _num(r.pvalues[i]),
             'lo': _num(ic[i][0]), 'hi': _num(ic[i][1])} for i, nm in enumerate(nombres)]
    k_param = orden[0] + orden[2] + est[0] + est[2]
    diag, resid = diagnostico(r, s, k_param)
    dx = _diferenciar(yc, orden[1], est[1], s)

    # Ajuste dentro de la muestra (predicción a un paso) y pronóstico.
    burn = int(getattr(r, 'loglikelihood_burn', 0) or 0)
    aj = np.asarray(r.fittedvalues, dtype=float)
    aj[:burn] = np.nan
    fc = r.get_forecast(h).summary_frame(alpha=alfa)
    media, lo, hi = (np.asarray(fc[c], dtype=float) for c in ('mean', 'mean_ci_lower', 'mean_ci_upper'))
    if log:
        aj, media, lo, hi = np.exp(aj), np.exp(media), np.exp(lo), np.exp(hi)

    return {
        'inicio': ini, 'n': int(len(y)), 'n_obs': n_obs, 's': s, 'log': log, 'alfa': alfa,
        'modo': modo, 'orden': orden, 'estacional': est if s > 1 else [0, 0, 0],
        'sugerido': {'d': d_sug, 'D': D_sug if estacional_posible else 0},
        'probados': probados, 'alternativas': alternativas,
        'info': {'aic': _num(r.aic), 'aicc': _num(_aicc(r)), 'bic': _num(r.bic),
                 'llf': _num(r.llf), 'nobs': int(r.nobs)},
        'coeficientes': coef, 'raices': _raices(r),
        'estacionariedad': pruebas, 'stl': stl,
        'correlograma': correlogramas(dx, rezagos, alfa) if len(dx) >= 8 else None,
        'correlograma_residuos': (correlogramas(resid, rezagos, alfa, con_pacf=False)
                                  if len(resid) >= 8 else None),
        'diagnostico': diag,
        'validacion': validacion(y, orden, est, s, log, n_obs),
        'ajuste': [_num(v) for v in aj],
        'pronostico': {'media': [_num(v) for v in media], 'lo': [_num(v) for v in lo],
                       'hi': [_num(v) for v in hi]},
        'avisos': sorted(set(avisos)), 'interpolados': interpolados,
    }
