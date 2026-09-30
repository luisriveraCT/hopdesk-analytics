# -*- coding: utf-8 -*-
"""
===============================================================================
 RAZONES FINANCIERAS — cálculo mensual a partir del esquema financiero
===============================================================================
Todas las razones del "Diccionario_KPIs" de KPIs_Finanzas.xlsx, más las de
liquidez que ese archivo no incluye pero que salen gratis si Contabilidad
manda activo y pasivo circulante.

Tres convenciones que hay que tener presentes al leer los números:

1) ANUALIZACIÓN. Los datos son mensuales pero ROE, ROIC, rotación y Deuda
   Neta/EBITDA se leen en términos anuales. Aquí se anualiza multiplicando el
   flujo del mes por 12 (no por un promedio móvil), que es como lo hace
   KPIs_Finanzas.xlsx. Es simple y consistente, pero amplifica la
   estacionalidad: un diciembre fuerte se ve como un año espectacular. Por eso
   cada razón anualizada trae también su versión TTM (últimos 12 meses) cuando
   hay historia suficiente — esa es la que conviene mirar para decidir.

2) SALDOS vs FLUJOS. Utilidad es flujo (pasa durante el mes); patrimonio es
   saldo (foto a fin de mes). Mezclarlos sin cuidado infla o desinfla los
   rendimientos. Donde importa, se usa el saldo PROMEDIO del periodo
   (inicial+final)/2, que es la práctica correcta; si no hay mes anterior, se
   usa el saldo final y se marca en la salida.

3) DIVISIÓN ENTRE CERO. Nunca se revienta ni se devuelve 0 disimulando: se
   devuelve None. Un None significa "no se puede calcular", que es distinto de
   "vale cero" — y esa diferencia importa cuando alguien decide con el número.
===============================================================================
"""
from math import isnan

# Días del año para las razones de días. 365 es la convención usual en estados
# financieros; tesorería y algunos contratos de crédito usan 360. Es una
# convención del cliente, no una verdad: viaja como argumento.
DIAS_ANIO = 365

# Cuántos periodos trae un año de datos. Es estructural, no una preferencia:
# la extracción del ERP es mensual. Existe como nombre para que las
# anualizaciones no aparezcan como un "* 12" suelto a lo largo del archivo —
# que es como se cuela una que multiplica lo que no debía.
PERIODOS_POR_ANIO = 12


def _div(a, b):
    """División segura: None si no se puede calcular (no cero disimulado)."""
    if a is None or b is None:
        return None
    try:
        if b == 0 or isnan(b) or isnan(a):
            return None
        return a / b
    except (TypeError, ValueError):
        return None


def _prom(actual, anterior):
    """Saldo promedio del periodo; si no hay mes anterior, el saldo final."""
    if actual is None:
        return None
    if anterior is None:
        return actual
    return (actual + anterior) / 2


class SupuestoFaltante(ValueError):
    """Se pidió un cálculo que depende de un supuesto que nadie capturó."""


def derivar_estado(fila, supuestos, fila_anterior=None):
    """Calcula los campos DERIVADOS del esquema a partir de los capturados.
    No modifica la fila original: regresa un dict nuevo con todo junto."""
    f = dict(fila)

    # LA TASA IMPOSITIVA NO TIENE VALOR POR DEFECTO, Y ESO ES DELIBERADO.
    #
    # Antes caía a 0.30 si no venía en la configuración. Treinta por ciento es
    # la tasa de ISR **mexicana**: un cliente en otro país habría visto su NOPAT
    # y su WACC calculados con el impuesto de México sin que nada lo dijera. Un
    # supuesto que no se capturó debe producir un hueco, no un número plausible.
    t = f.get('tasa_impositiva', supuestos.get('tasa_impositiva'))

    ing = f.get('ingresos')

    # ===================================================================
    # NO SE RECALCULA LO QUE EL ESTADO DE RESULTADOS YA CALCULÓ
    # ===================================================================
    # Esta función recomputaba el EBIT así:
    #
    #     ebit = ingresos − costo − gastos_operacion − depreciacion
    #
    # y estaba mal, porque **la depreciación ya está dentro de los gastos de
    # operación**: son cuentas de la clase GASTO y el Estado de Resultados las
    # suma ahí. Restarla otra vez la descuenta dos veces.
    #
    # El daño medido en un mes real: la utilidad de operación del estado era
    # 2,631,384 y aquí salía −280,143. La diferencia, 2,911,527, es exactamente
    # la depreciación del mes. Y como el EBITDA se arma sumándole de vuelta la
    # depreciación al EBIT, el "EBITDA" publicado terminaba siendo el EBIT: el
    # margen EBITDA del tablero era en realidad el margen operativo.
    #
    # De ahí colgaba todo lo demás — EBT, utilidad neta, NOPAT, ROIC, el spread
    # contra el WACC y el EVA— y también las tasas efectivas imposibles, porque
    # el EBT salía con el signo cambiado en los meses ajustados.
    #
    # Peor que la cifra: las dos pestañas se contradecían. Estados Financieros
    # lee el Estado de Resultados directo y mostraba lo correcto; Indicadores
    # mostraba esto. El diseño decía explícitamente que eso no podía pasar.
    #
    # La regla, la misma que ya rige las bases de días: **si la llave viene, se
    # respeta**. Quien construye la fila tiene el estado financiero enfrente;
    # esta función solo completa lo que falte.
    if 'ebit' not in f or f['ebit'] is None:
        # Respaldo para quien entregue una fila cruda sin utilidad de operación.
        # Aquí SÍ hay que restar la depreciación, porque en ese caso
        # `gastos_operacion` es el gasto sin ella.
        f['ebit'] = None
        if None not in (ing, f.get('costo_servicio'), f.get('gastos_operacion'),
                        f.get('depreciacion')):
            f['ebit'] = (ing - f['costo_servicio'] - f['gastos_operacion']
                         - f['depreciacion'])
    if 'ebitda' not in f or f['ebitda'] is None:
        f['ebitda'] = (None if f['ebit'] is None or f.get('depreciacion') is None
                       else f['ebit'] + f['depreciacion'])
    if 'ebt' not in f or f['ebt'] is None:
        f['ebt'] = (None if f['ebit'] is None or f.get('gastos_financieros') is None
                    else f['ebit'] - f['gastos_financieros'])

    # Si el ER trae impuestos reales se respetan y se deriva la tasa efectiva;
    # si no, se estiman con la tasa supuesta.
    #
    # `tasa_estimada` distingue los dos casos y hace falta: antes, cuando no
    # había impuesto real, el campo `tasa_efectiva` se llenaba con el SUPUESTO y
    # salía en pantalla bajo el rótulo "Tasa efectiva de impuestos", como si se
    # hubiera medido. Un supuesto presentado como medición es peor que un hueco.
    if 'tasa_efectiva' in fila and fila.get('tasa_efectiva') is not None:
        # Quien armó la fila ya la calculó Y decidió si es interpretable. No se
        # vuelve a dividir aquí: la versión anterior la recomputaba por su
        # cuenta y anulaba ese criterio, publicando tasas de −3% y 175% con la
        # bandera de confiable puesta.
        f['tasa_estimada'] = False
    elif f.get('impuestos') is not None and f.get('ebt'):
        f['tasa_efectiva'] = _div(f['impuestos'], f['ebt'])
        f['tasa_estimada'] = False
    else:
        f['impuestos'] = None if (f['ebt'] is None or t is None) else f['ebt'] * t
        f['tasa_efectiva'] = None
        f['tasa_estimada'] = True
    if 'utilidad_neta' not in fila or fila.get('utilidad_neta') is None:
        f['utilidad_neta'] = (None if f['ebt'] is None or f['impuestos'] is None
                              else f['ebt'] - f['impuestos'])

    # QUÉ TASA ENTRA AL NOPAT Y AL ESCUDO FISCAL DEL WACC.
    #
    # Antes entraba siempre el supuesto (0.30), aun teniendo la tasa real del
    # ERP. No es un detalle: las tasas efectivas medidas de este grupo van de
    # 37% a 41%, así que el NOPAT salía entre 10% y 16% alto, y con él el ROIC y
    # el spread contra el WACC — que es el indicador del que cuelga la decisión.
    #
    # Se usa la tasa MEDIDA cuando es confiable, y el supuesto cuando no. Cuál
    # de las dos se usó viaja en `origen_tasa_nopat` hasta la pantalla: sin eso,
    # dos empresas con el mismo ROIC podrían estar calculadas distinto y nadie
    # tendría cómo saberlo.
    te, confiable = f.get('tasa_efectiva'), f.get('tasa_confiable')
    if confiable and te is not None:
        t_nopat, f['origen_tasa_nopat'] = te, 'efectiva_del_erp'
    elif t is not None:
        t_nopat, f['origen_tasa_nopat'] = t, 'supuesto_configurado'
    else:
        t_nopat, f['origen_tasa_nopat'] = None, 'sin_tasa'
    f['tasa_usada_nopat'] = t_nopat

    f['deuda_neta'] = None
    if f.get('deuda_con_costo') is not None and f.get('efectivo') is not None:
        f['deuda_neta'] = f['deuda_con_costo'] - f['efectivo']
    f['capital_invertido'] = None
    if f.get('patrimonio') is not None and f['deuda_neta'] is not None:
        f['capital_invertido'] = f['patrimonio'] + f['deuda_neta']

    # Δ capital de trabajo: si no viene, se estima contra el mes anterior.
    if f.get('delta_capital_trabajo') is None and fila_anterior is not None:
        ctn_hoy = _ctn(f)
        ctn_ayer = _ctn(fila_anterior)
        if ctn_hoy is not None and ctn_ayer is not None:
            f['delta_capital_trabajo'] = ctn_hoy - ctn_ayer
            f['delta_capital_trabajo_estimado'] = True

    f['nopat'] = (None if (f['ebit'] is None or t_nopat is None)
                  else f['ebit'] * (1 - t_nopat))
    f['fcf'] = None
    if None not in (f['nopat'], f.get('depreciacion'), f.get('capex'), f.get('delta_capital_trabajo')):
        f['fcf'] = f['nopat'] + f['depreciacion'] - f['capex'] - f['delta_capital_trabajo']

    # Costo de capital
    rf = f.get('rf', supuestos.get('rf'))
    beta = f.get('beta', supuestos.get('beta'))
    erp = f.get('erp', supuestos.get('erp'))
    kd = f.get('kd', supuestos.get('kd'))
    f['ke'] = None if None in (rf, beta, erp) else rf + beta * erp
    f['wacc'] = None
    pat, deu = f.get('patrimonio'), f.get('deuda_con_costo')
    # El escudo fiscal usa la MISMA tasa que el NOPAT. Si no fuera la misma, el
    # spread ROIC − WACC estaría restando dos números calculados con supuestos
    # fiscales distintos, y la diferencia se leería como creación de valor.
    if (None not in (pat, deu, f['ke'], kd, t_nopat)) and (pat + deu) != 0:
        we = pat / (pat + deu)
        wd = deu / (pat + deu)
        f['wacc'] = we * f['ke'] + wd * kd * (1 - t_nopat)
    return f


def _ctn(f):
    """Capital de trabajo neto operativo = CxC + Inventarios − CxP."""
    cxc, inv, cxp = f.get('cuentas_x_cobrar'), f.get('inventarios') or 0, f.get('cuentas_x_pagar')
    if cxc is None or cxp is None:
        return None
    return cxc + inv - cxp


def razones(fila, fila_anterior=None, ttm=None, dias_anio=None):
    """Razones financieras de un mes ya derivado (pasar la salida de derivar_estado).

    ttm: opcional, dict con los agregados de los últimos 12 meses y los saldos
         PROMEDIO de esa misma ventana. Cuando se entrega, se calculan las
         versiones TTM, que son las que conviene usar para decidir.

    dias_anio: convención de días del año (365 o 360). Del cliente.
    """
    f = fila
    r = {}
    ing = f.get('ingresos')
    dias = dias_anio or DIAS_ANIO
    P = PERIODOS_POR_ANIO

    # --- Rentabilidad (márgenes: flujo sobre flujo, no requieren anualizar) ---
    r['margen_bruto'] = _div((ing - f['costo_servicio']) if None not in (ing, f.get('costo_servicio')) else None, ing)
    r['margen_ebitda'] = _div(f.get('ebitda'), ing)
    r['margen_ebit'] = _div(f.get('ebit'), ing)
    r['margen_neto'] = _div(f.get('utilidad_neta'), ing)
    r['margen_fcf'] = _div(f.get('fcf'), ing)

    # --- Rendimiento sobre capital (flujo anualizado / saldo promedio) --------
    pat_prom = _prom(f.get('patrimonio'), (fila_anterior or {}).get('patrimonio'))
    act_prom = _prom(f.get('activos_totales'), (fila_anterior or {}).get('activos_totales'))
    ci_prom = _prom(f.get('capital_invertido'), (fila_anterior or {}).get('capital_invertido'))

    r['roe'] = _div((f['utilidad_neta'] * P) if f.get('utilidad_neta') is not None else None, pat_prom)
    r['roa'] = _div((f['utilidad_neta'] * P) if f.get('utilidad_neta') is not None else None, act_prom)
    r['roic'] = _div((f['nopat'] * P) if f.get('nopat') is not None else None, ci_prom)
    r['rotacion_activos'] = _div((ing * P) if ing is not None else None, act_prom)

    # --- Creación de valor: el indicador que manda ---------------------------
    # EL EVA VA EN PESOS AL AÑO, las dos versiones.
    #
    # Antes `eva` se dividía entre doce (pesos del mes) y `eva_ttm` no (pesos
    # del año). Dos cifras con nombres casi iguales, en la misma pantalla, en
    # unidades distintas y sin nada que lo dijera: la del mes se veía doce veces
    # más chica y se leía como una mejora.
    #
    # Se dejan las dos anuales porque el spread que las produce es anual: ROIC
    # anualizado menos WACC anual. Multiplicarlo por el capital da pesos al año,
    # y volver a dividir entre doce mezclaba una tasa anual con un periodo
    # mensual.
    if r['roic'] is not None and f.get('wacc') is not None:
        r['spread_roic_wacc'] = r['roic'] - f['wacc']
        r['eva'] = (r['spread_roic_wacc'] * f['capital_invertido']
                    if f.get('capital_invertido') else None)
    else:
        r['spread_roic_wacc'] = None
        r['eva'] = None

    # --- Ciclo de efectivo ---------------------------------------------------
    # LA BASE DE CADA RAZÓN DE DÍAS NO ES OBVIA, Y ELEGIRLA MAL PRODUCE NÚMEROS
    # QUE PARECEN VÁLIDOS.
    #
    # Días de cobranza: el numerador son las cuentas por cobrar A TERCEROS —los
    # saldos con empresas del grupo viven en otras cuentas—, así que el
    # denominador tienen que ser las ventas a terceros. Dividir cobranza de
    # terceros entre ventas totales (con intercompañía adentro) da un DSO
    # sistemáticamente bajo, y el sesgo crece justo en las empresas que más le
    # facturan al grupo, que es donde más engaña.
    #
    # Días de pago: el denominador clásico es el costo de ventas, y eso supone
    # que las compras pasan por ahí. En este grupo no pasan: el costo de ventas
    # es el 0.2% de los ingresos en una empresa y cero en otra, porque el diesel
    # y el personal de operación se registran como gastos. Contra esa base el
    # DPO salía en 365 días para una empresa y 1,564 para el grupo. No era un
    # error de cálculo: era la respuesta correcta a una pregunta mal planteada.
    #
    # Quien llama entrega las bases ya calculadas —sabe de intercompañía y de
    # la convención que eligió el cliente; este módulo no—. Sin ellas se usan
    # las clásicas, para que la función siga sirviendo con datos sueltos.
    cxc_prom = _prom(f.get('cuentas_x_cobrar'), (fila_anterior or {}).get('cuentas_x_cobrar'))
    inv_prom = _prom(f.get('inventarios'), (fila_anterior or {}).get('inventarios'))
    cxp_prom = _prom(f.get('cuentas_x_pagar'), (fila_anterior or {}).get('cuentas_x_pagar'))
    # Se pregunta si la LLAVE está, no si el valor es None, y la diferencia es
    # el punto entero:
    #
    #   llave ausente  → quien llama no calculó bases; se usan las clásicas.
    #   llave con None → quien llama SÍ calculó y determinó que no aplica —
    #                    la empresa no tiene ventas a terceros contra las cuales
    #                    medir días de cobranza.
    #
    # Tratar los dos casos igual hace que el segundo caiga a la base bruta sin
    # avisar. Pasó: una empresa cuyos días de cobranza se habían suprimido a
    # propósito volvió a mostrar 187 días, calculados contra ingresos que son
    # casi todos facturación a sus propias hermanas.
    base_cob = f['base_cobranza'] if 'base_cobranza' in f else ing
    base_pag = f['base_pago'] if 'base_pago' in f else f.get('costo_servicio')
    r['base_cobranza'] = base_cob
    r['base_pago'] = base_pag
    ventas_anual = (base_cob * P) if base_cob is not None else None
    costo_anual = (base_pag * P) if base_pag is not None else None

    r['dso'] = _div(cxc_prom, ventas_anual)
    r['dso'] = r['dso'] * dias if r['dso'] is not None else None
    r['dio'] = _div(inv_prom, costo_anual)
    r['dio'] = r['dio'] * dias if r['dio'] is not None else None
    r['dpo'] = _div(cxp_prom, costo_anual)
    r['dpo'] = r['dpo'] * dias if r['dpo'] is not None else None
    if None not in (r['dso'], r['dpo']):
        r['ccc'] = r['dso'] + (r['dio'] or 0) - r['dpo']
    else:
        r['ccc'] = None
    r['ctn_sobre_ventas'] = _div(_ctn(f), ing)

    # --- Apalancamiento y solvencia -----------------------------------------
    r['deuda_entre_patrimonio'] = _div(f.get('deuda_con_costo'), f.get('patrimonio'))
    ebitda_anual = (f['ebitda'] * P) if f.get('ebitda') is not None else None
    r['deuda_neta_ebitda'] = _div(f.get('deuda_neta'), ebitda_anual)

    # COBERTURA DE INTERESES: SOLO CUANDO HAY INTERESES QUE CUBRIR.
    #
    # El renglón del que sale es el resultado financiero NETO, que incluye los
    # productos financieros. En 177 de 468 meses de este grupo es negativo — la
    # empresa ganó más por intereses de los que pagó. Dividir entre un número
    # negativo daba una cobertura negativa, que se lee como "no alcanza a pagar
    # sus intereses" cuando pasa exactamente lo contrario. Y con el meta de
    # "mayor es mejor" el semáforo lo pintaba rojo.
    #
    # Sin costo financiero neto la razón no existe: no hay nada que cubrir.
    gf = f.get('gastos_financieros')
    r['cobertura_intereses'] = _div(f.get('ebit'), gf) if (gf or 0) > 0 else None
    r['costo_deuda_efectivo'] = (
        _div(gf * P, f.get('deuda_con_costo')) if (gf or 0) > 0 else None)
    r['razon_deuda'] = _div(f.get('pasivos_totales'), f.get('activos_totales'))

    # LA TASA EFECTIVA SOLO SE PUBLICA CUANDO ES CONFIABLE.
    #
    # Es mensual, y el resultado antes de impuestos de un mes puede ser casi
    # cero o negativo: la división produce cualquier cosa. Medido sobre esta
    # serie, entre 10 y 36 meses por empresa caen fuera de todo rango usable.
    #
    # El caso que obligó a cerrarlo: una empresa mostraba una tasa efectiva de
    # −308% y el semáforo la pintaba VERDE, porque la meta es "menor es mejor" y
    # −3.08 es menor que 0.30. Un número sin sentido presentado como un logro.
    # La bandera `tasa_confiable` ya existía y nadie la consultaba aquí.
    r['tasa_efectiva'] = (f.get('tasa_efectiva')
                          if f.get('tasa_confiable') else None)

    # --- Liquidez (requiere circulantes; por eso se piden en el esquema) -----
    r['razon_circulante'] = _div(f.get('activo_circulante'), f.get('pasivo_circulante'))
    ac, inv_v = f.get('activo_circulante'), (f.get('inventarios') or 0)
    r['prueba_acida'] = _div((ac - inv_v) if ac is not None else None, f.get('pasivo_circulante'))
    r['razon_efectivo'] = _div(f.get('efectivo'), f.get('pasivo_circulante'))

    # --- Versiones TTM (las buenas para decidir) -----------------------------
    if ttm:
        r['margen_ebitda_ttm'] = _div(ttm.get('ebitda'), ttm.get('ingresos'))
        r['margen_ebit_ttm'] = _div(ttm.get('ebit'), ttm.get('ingresos'))
        r['margen_neto_ttm'] = _div(ttm.get('utilidad_neta'), ttm.get('ingresos'))

        # EL DENOMINADOR DE UNA RAZÓN DE DOCE MESES ES EL SALDO PROMEDIO DE ESOS
        # DOCE MESES, no el de los dos últimos.
        #
        # Un flujo acumulado de un año se ganó sobre el capital que hubo durante
        # ese año. Usar el promedio de los dos meses finales mete el saldo más
        # reciente contra una utilidad que se generó cuando el saldo era otro, y
        # el sesgo crece con la velocidad a la que cambia el balance: en una
        # empresa que capitaliza fuerte, el ROE de doce meses sale bajo sin que
        # nada en la cifra lo delate.
        #
        # Si quien llama no calculó los promedios de doce meses se usan los de
        # dos, que es mejor que no dar la razón — pero se marca, para que la
        # pantalla pueda decirlo.
        pat12 = ttm.get('patrimonio_prom')
        ci12 = ttm.get('capital_invertido_prom')
        act12 = ttm.get('activos_totales_prom')
        r['promedios_de_doce_meses'] = pat12 is not None
        pat_ttm = pat12 if pat12 is not None else pat_prom
        ci_ttm = ci12 if ci12 is not None else ci_prom
        act_ttm = act12 if act12 is not None else act_prom

        r['roe_ttm'] = _div(ttm.get('utilidad_neta'), pat_ttm)
        r['roic_ttm'] = _div(ttm.get('nopat'), ci_ttm)
        r['rotacion_activos_ttm'] = _div(ttm.get('ingresos'), act_ttm)
        # La deuda neta SÍ es el saldo al corte: "cuántos años de EBITDA me
        # tomaría pagar lo que debo HOY". Promediarla contestaría otra pregunta.
        r['deuda_neta_ebitda_ttm'] = _div(f.get('deuda_neta'), ttm.get('ebitda'))
        if r['roic_ttm'] is not None and f.get('wacc') is not None:
            r['spread_roic_wacc_ttm'] = r['roic_ttm'] - f['wacc']
            r['eva_ttm'] = (r['spread_roic_wacc_ttm'] * ci_ttm
                            if ci_ttm else None)
    return r


def dupont_5_factores(f, fila_anterior=None):
    """Descomposición DuPont de 5 factores del ROE — la que pide el
    Diccionario_KPIs. ROE = carga fiscal × carga de intereses × margen EBIT ×
    rotación de activos × apalancamiento. El producto debe reproducir el ROE;
    si no, es que hay un dato inconsistente (se reporta la diferencia)."""
    pat_prom = _prom(f.get('patrimonio'), (fila_anterior or {}).get('patrimonio'))
    act_prom = _prom(f.get('activos_totales'), (fila_anterior or {}).get('activos_totales'))
    d = {
        'carga_fiscal': _div(f.get('utilidad_neta'), f.get('ebt')),          # UN / EBT
        'carga_intereses': _div(f.get('ebt'), f.get('ebit')),                 # EBT / EBIT
        'margen_ebit': _div(f.get('ebit'), f.get('ingresos')),                # EBIT / Ventas
        'rotacion_activos': _div((f['ingresos'] * PERIODOS_POR_ANIO)
                                 if f.get('ingresos') is not None else None, act_prom),
        'apalancamiento': _div(act_prom, pat_prom),                           # Activos / Patrimonio
    }
    if all(v is not None for v in d.values()):
        d['roe_reconstruido'] = (d['carga_fiscal'] * d['carga_intereses'] * d['margen_ebit']
                                 * d['rotacion_activos'] * d['apalancamiento'])
    else:
        d['roe_reconstruido'] = None
    return d


def calcular_ttm(filas_derivadas, i):
    """Agregados de los últimos 12 meses terminando en el índice i.

    Devuelve dos cosas distintas, y la distinción es la de siempre:

      · los FLUJOS se **suman** — ingresos, EBITDA, utilidad;
      · los SALDOS se **promedian** — patrimonio, activos, capital invertido.

    Sumar un saldo lo multiplicaría por doce; promediarlo da el capital que
    realmente estuvo puesto durante el año, que es contra lo que se mide un
    rendimiento anual.

    Regresa None si no hay 12 meses de historia: un acumulado de siete meses se
    lee igual que uno de doce y nada en la pantalla lo distingue.
    """
    if i < PERIODOS_POR_ANIO - 1:
        return None
    ventana = filas_derivadas[i - (PERIODOS_POR_ANIO - 1):i + 1]
    flujos = ('ingresos', 'ebitda', 'ebit', 'utilidad_neta', 'nopat',
              'costo_servicio', 'fcf', 'impuestos', 'depreciacion')
    saldos = ('patrimonio', 'activos_totales', 'capital_invertido',
              'cuentas_x_cobrar', 'cuentas_x_pagar', 'deuda_con_costo')
    out = {}
    for c in flujos:
        vals = [f.get(c) for f in ventana]
        out[c] = sum(vals) if all(v is not None for v in vals) else None
    for c in saldos:
        vals = [f.get(c) for f in ventana]
        out[f'{c}_prom'] = (sum(vals) / len(vals)
                            if all(v is not None for v in vals) else None)
    return out


# ---------------------------------------------------------------------------
# Catálogo de indicadores — QUÉ ES cada uno, no cuánto debería valer
# ---------------------------------------------------------------------------
# La separación entre este catálogo y las metas del cliente importa y no es
# cosmética:
#
#   "El DSO se lee mejor cuando es más bajo"  → es un hecho sobre el indicador.
#   "Nuestro DSO objetivo son 55 días"        → es una decisión de esta empresa.
#
# Lo primero vive aquí porque es igual para todos. Lo segundo vive en la
# configuración del cliente (`Cliente.metas`), porque el siguiente cliente
# opera en otro sector, con otro ciclo de cobranza y otro costo de capital, y
# no debería necesitar que alguien edite código para tener sus propias metas.
#
# Antes de esta separación, las metas de Networks —ROE 18%, WACC 11%, DSO 55—
# estaban aquí como constantes. Funcionaba porque solo había un cliente.
# Las familias son el orden de lectura de un análisis financiero: primero
# cuánto gana, luego sobre cuánto capital, luego cuánto tarda el dinero en dar
# la vuelta, cuánto debe y con qué holgura paga lo que vence.
FAMILIAS = [
    ('rentabilidad', 'Rentabilidad'),
    ('rendimiento',  'Rendimiento sobre capital'),
    ('ciclo',        'Ciclo de efectivo'),
    ('deuda',        'Apalancamiento y solvencia'),
    ('liquidez',     'Liquidez'),
]

# Cada indicador declara TODO lo que se necesita saber de él: cómo se llama, en
# qué unidad va, de qué lado está el verde, a qué familia pertenece, si tiene
# versión de doce meses y si se expresa en dinero.
#
# Está completo a propósito. La versión anterior dejaba la familia, la lista de
# los que tienen TTM y la de los monetarios escritas en el JavaScript del
# tablero: tres listas paralelas que había que recordar actualizar juntas, y
# agregar un indicador sin tocar las tres lo dejaba calculado pero invisible.
# Ahora el catálogo viaja en los datos y el tablero se arma con él.
#
# 'ttm' es el nombre de la versión de doce meses, o None si no tiene. No todos
# la tienen: un saldo del balance no se acumula, y los días de cobranza ya se
# calculan contra ventas anualizadas.
def _k(nombre, unidad, mayor_mejor, familia, ttm=None, monetario=False,
       destacado=False, fuente='razon'):
    return {'nombre': nombre, 'unidad': unidad, 'mayor_mejor': mayor_mejor,
            'familia': familia, 'ttm': ttm, 'monetario': monetario,
            # 'destacado' marca los que salen en el comparativo entre empresas
            # del tablero de dirección — no caben todos, y cuáles caben es una
            # decisión de presentación que vale la pena tener en un solo lugar.
            'destacado': destacado,
            # De dónde sale el valor: 'razon' lo produce razones(), 'derivado'
            # vive en la fila derivada (el WACC es el único así).
            #
            # Se declara porque el tablero necesitaba buscarlo en dos lugares, y
            # "búscalo aquí y si no está, allá" reintroduce en la interfaz el
            # error que se acababa de cerrar en el cálculo: la tasa efectiva se
            # suprime en razones() cuando no es confiable, y la búsqueda de
            # respaldo la recuperaba del campo crudo —los mismos −308%— sin que
            # nada lo dijera.
            'fuente': fuente}


CATALOGO_KPIS = {
    # --- Rentabilidad ------------------------------------------------------
    'margen_bruto':      _k('Margen bruto', '%', True, 'rentabilidad'),
    'margen_ebitda':     _k('Margen EBITDA', '%', True, 'rentabilidad',
                            ttm='margen_ebitda_ttm', destacado=True),
    'margen_ebit':       _k('Margen operativo', '%', True, 'rentabilidad',
                            ttm='margen_ebit_ttm'),
    'margen_neto':       _k('Margen neto', '%', True, 'rentabilidad',
                            ttm='margen_neto_ttm', destacado=True),
    'margen_fcf':        _k('Margen de flujo libre', '%', True, 'rentabilidad'),
    # --- Rendimiento sobre capital ----------------------------------------
    'roe':               _k('ROE', '%', True, 'rendimiento', ttm='roe_ttm'),
    'roa':               _k('ROA', '%', True, 'rendimiento'),
    'roic':              _k('ROIC', '%', True, 'rendimiento', ttm='roic_ttm',
                            destacado=True),
    'wacc':              _k('WACC', '%', False, 'rendimiento', fuente='derivado'),
    'spread_roic_wacc':  _k('Spread ROIC−WACC', 'pp', True, 'rendimiento',
                            ttm='spread_roic_wacc_ttm', destacado=True),
    # Las dos versiones van en pesos AL AÑO. La del mes se anualiza a partir de
    # un solo mes, así que brinca mucho; la de doce meses es la que sirve para
    # decidir, y es la que el tablero muestra por defecto.
    'eva':               _k('EVA (valor económico agregado)', '$', True,
                            'rendimiento', ttm='eva_ttm', monetario=True),
    'rotacion_activos':  _k('Rotación de activos', 'x', True, 'rendimiento',
                            ttm='rotacion_activos_ttm'),
    # --- Ciclo de efectivo -------------------------------------------------
    'dso':               _k('Días de cobranza', 'días', False, 'ciclo',
                            destacado=True),
    'dio':               _k('Días de inventario', 'días', False, 'ciclo'),
    'dpo':               _k('Días de pago', 'días', True, 'ciclo'),
    'ccc':               _k('Ciclo de efectivo', 'días', False, 'ciclo'),
    'ctn_sobre_ventas':  _k('Capital de trabajo / ventas', '%', False, 'ciclo'),
    # --- Apalancamiento y solvencia ---------------------------------------
    'deuda_entre_patrimonio': _k('Deuda / patrimonio', 'x', False, 'deuda'),
    'deuda_neta_ebitda': _k('Deuda neta / EBITDA', 'x', False, 'deuda',
                            ttm='deuda_neta_ebitda_ttm', destacado=True),
    'cobertura_intereses': _k('Cobertura de intereses', 'x', True, 'deuda'),
    'costo_deuda_efectivo': _k('Costo de la deuda', '%', False, 'deuda'),
    'razon_deuda':       _k('Pasivo / activo', '%', False, 'deuda'),
    'tasa_efectiva':     _k('Tasa efectiva de impuestos', '%', False, 'deuda'),
    # --- Liquidez ----------------------------------------------------------
    'razon_circulante':  _k('Razón circulante', 'x', True, 'liquidez'),
    'prueba_acida':      _k('Prueba del ácido', 'x', True, 'liquidez'),
    'razon_efectivo':    _k('Razón de efectivo', 'x', True, 'liquidez'),
}

# Qué tan cerca de la meta sigue contando como amarillo. Es el valor que usa
# KPIs_Finanzas.xlsx y por eso es el de arranque, pero se puede cambiar desde
# la configuración del cliente: qué tan estrecha es la banda de tolerancia es
# una decisión de quien fija las metas, no del programa.
HOLGURA_AMARILLO = 0.10


def semaforo(clave, valor, metas, holgura=None):
    """Verde / Amarillo / Rojo contra la meta que el cliente definió.

    `metas` es {clave: valor_objetivo} y viene de la configuración del cliente.
    Es un argumento obligatorio a propósito: un semáforo que cae a metas por
    defecto le pinta a un cliente la meta de otro, y el número se ve igual de
    creíble en verde que en rojo.

    Sin meta para esa clave, el resultado es None — "no hay contra qué
    compararlo", que es distinto de "está mal".
    """
    k = CATALOGO_KPIS.get(clave)
    if k is None or valor is None or metas is None:
        return None
    meta = metas.get(clave)
    if meta is None:
        return None
    if holgura is None:
        holgura = HOLGURA_AMARILLO
    # La banda de amarillo se mide en VALOR ABSOLUTO de la meta, no como un
    # porcentaje de ella. Con una meta de 0 —el spread ROIC−WACC, que es
    # exactamente donde empieza a crearse valor— un umbral relativo colapsa:
    # meta*0.9 sigue siendo 0 y el amarillo desaparece. Con una meta negativa se
    # invierte y el amarillo queda del lado equivocado.
    banda = abs(meta) * holgura
    if k['mayor_mejor']:
        if valor >= meta:
            return 'Verde'
        return 'Amarillo' if valor >= meta - banda else 'Rojo'
    if valor <= meta:
        return 'Verde'
    return 'Amarillo' if valor <= meta + banda else 'Rojo'
