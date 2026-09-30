# -*- coding: utf-8 -*-
"""
===============================================================================
 PREPARA LOS INDICADORES PARA EL DASHBOARD DE DIRECCIÓN Y EL TABLERO DE FINANZAS
===============================================================================
Produce `kpis.json`: por empresa y por mes, los campos financieros derivados
(EBITDA, NOPAT, FCF, WACC...), las razones, la descomposición DuPont del ROE y
el semáforo contra las metas que el cliente configuró.

DE DÓNDE SALE CADA COSA — Y POR QUÉ IMPORTA DECIRLO
---------------------------------------------------
Un WACC impreso con cuatro decimales parece un hecho medido. No lo es. En este
grupo:

  · **Tasa libre de riesgo** — observable (Banxico).
  · **Tasa efectiva de impuestos** — se calcula del ERP, por empresa y periodo.
  · **Beta y prima de mercado** — NO son observables. Networks es privada: no
    hay precio de acción del cual estimar una beta. Son juicios capturados en la
    configuración, y viajan marcados como tales hasta la pantalla.
  · **Costo de la deuda** — capturado; sustituible por el costo real de los
    financiamientos que ya registra HopDesk.

Por eso cada indicador que depende de un supuesto sale acompañado de su origen.
Un número que no se puede verificar y no dice que no se puede verificar es peor
que no tenerlo.

EL CONSOLIDADO SALE DE `finanzas.json`, A PROPÓSITO
---------------------------------------------------
No se vuelve a consolidar aquí. Se leen los totales que ya calculó
`exportar_finanzas.py` —con sus eliminaciones— y se construye encima.

Es una decisión de diseño, no un atajo: si cada pantalla consolidara por su
cuenta, la utilidad consolidada del Estado de Resultados y el margen neto
consolidado del tablero de KPIs podrían diferir, y no habría forma de saber
cuál de las dos está bien. Leyendo de la misma fuente, o las dos están bien o
las dos están mal — y eso sí se detecta.

LO QUE NO SE PUEDE CALCULAR SE DEJA VACÍO
-----------------------------------------
No hay extracción de altas de activo fijo, así que no hay capex; sin capex no
hay flujo libre. Aparece como hueco, no como cero. Un cero en el margen de FCF
se lee como "esta empresa no genera flujo", que es una afirmación, y no la
podemos sostener.
===============================================================================
"""
import os
import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(AQUI)
FINANZAS = os.path.join(BASE, 'finanzas')

sys.path.insert(0, FINANZAS)
sys.path.insert(0, os.path.join(FINANZAS, 'erp'))
sys.path.insert(0, os.path.join(FINANZAS, 'configuracion'))

import mapeo_kpis as mk                 # noqa: E402
import razones_financieras as rz        # noqa: E402
import analisis_vertical_horizontal as av  # noqa: E402
import entradas_manuales as em          # noqa: E402

# Clave con la que viaja el grupo consolidado. Se distingue de unas iniciales de
# empresa por los guiones bajos: ninguna empresa real puede llamarse así, porque
# el modelo solo admite letras y dígitos en las iniciales.
CLAVE_GRUPO = '__CONSOLIDADO__'

# Campos derivados que se publican por periodo. Se enumeran en vez de volcar
# todo el diccionario para que el archivo no crezca con campos intermedios que
# nadie grafica — y para que agregar uno sea una decisión, no un accidente.
CAMPOS_DERIVADOS = (
    'ingresos', 'costo_servicio', 'gastos_operacion', 'depreciacion',
    'ebit', 'ebitda', 'gastos_financieros', 'ebt', 'impuestos', 'utilidad_neta',
    'tasa_efectiva', 'tasa_confiable',
    'activos_totales', 'pasivos_totales', 'patrimonio',
    'efectivo', 'cuentas_x_cobrar', 'inventarios', 'cuentas_x_pagar',
    'deuda_con_costo', 'deuda_neta', 'capital_invertido',
    'activo_circulante', 'pasivo_circulante', 'partes_relacionadas',
    'nopat', 'fcf', 'ke', 'wacc',
    'base_cobranza', 'base_pago',
    'mes_incompleto', 'es_cierre_anual', 'costo_inmaterial',
    'sin_base_dias',
    # Con qué tasa se calcularon el NOPAT y el escudo fiscal del WACC, y de
    # dónde salió. Sin esto, dos empresas con el mismo ROIC podrían estar
    # calculadas con tasas distintas —una medida del ERP, otra supuesta— y no
    # habría forma de saberlo mirando la pantalla.
    'tasa_usada_nopat', 'origen_tasa_nopat', 'tasa_estimada',
    # Qué campos de esta fila los puso una persona, con su motivo. Es lo que
    # permite al tablero resaltarlos: sin este rastro, una cifra sobrescrita se
    # ve idéntica a una calculada y seis meses después nadie sabe cuál era cuál.
    '_manual',
)

# Campos que son TASAS y no importes. Van con seis decimales porque dos los
# destruyen: una tasa libre de riesgo de 0.095 redondeada a dos decimales queda
# en 0.10 —un punto entero de más— y el WACC construido sobre ella deja de
# reproducir el spread contra el ROIC que se muestra a su lado. El error se ve
# chiquito en pantalla (16.00% contra 16.01%) y mueve el EVA en millones.
CAMPOS_TASA = frozenset({'tasa_efectiva', 'ke', 'wacc', 'tasa_usada_nopat'})

# Nota: qué razones se publican YA NO se enumera aquí. Lo decide
# `razones_financieras.CATALOGO_KPIS`, que es el mismo que usa el tablero para
# armar sus tablas. Dos listas paralelas se desincronizan: un indicador nuevo
# quedaba calculado, publicado y sin aparecer en ninguna pantalla.


def _r(v, dec=2):
    """Redondea sin convertir None en cero — esa conversión es el error que más
    veces se cuela en un export, porque el resultado se ve perfectamente bien."""
    if v is None:
        return None
    try:
        if v != v:            # NaN
            return None
        return round(float(v), dec)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
def serie_consolidada(fin, series_empresa):
    """Arma la serie del grupo consolidado a partir de `finanzas.json`.

    Los totales de estado (ingresos, utilidad, activo, pasivo) vienen ya
    consolidados. Los rubros de balance se suman de las empresas, y ahí hay una
    distinción que decide si los números significan algo:

      · **Cuentas por cobrar y por pagar**: se suman tal cual. En este catálogo
        los saldos entre empresas del grupo NO viven ahí —cuelgan de Deudores y
        Acreedores Diversos, y los de largo plazo de "empresas relacionadas"—,
        así que la suma ya es contra terceros. Restarles la eliminación los
        dejaría por debajo de lo que la empresa realmente tiene por cobrar, y el
        DSO saldría artificialmente bueno.

      · **Activo y pasivo circulante**: ahí sí están. Se les resta la
        eliminación de su propio lado, que es exactamente lo que se le restó al
        activo y al pasivo totales.
    """
    cons = fin.get('consolidado') or {}
    if not cons:
        return []
    salida = []
    for periodo in sorted(cons):
        c = cons[periodo]
        b, r = c['balance'], c['resultados']
        a, m = (int(x) for x in periodo.split('-'))

        # Lo que no cambia al consolidar: depreciación y los rubros de terceros.
        # Ninguna de las dos cosas tiene componente intercompañía.
        suma = {k: 0.0 for k in ('depreciacion', 'efectivo', 'cuentas_x_cobrar',
                                 'inventarios', 'cuentas_x_pagar',
                                 'deuda_con_costo', 'partes_relacionadas',
                                 'activo_circulante', 'pasivo_circulante')}
        presente = {k: False for k in suma}
        for ini, serie in series_empresa.items():
            fila = serie.get(periodo)
            if not fila:
                continue
            for k in suma:
                v = fila.get(k)
                if v is not None:
                    suma[k] += v
                    presente[k] = True

        fila = {
            'empresa': CLAVE_GRUPO, 'anio': a, 'mes': m, 'periodo': periodo,
            'ingresos': r['ingresos'], 'costo_servicio': r['costo'],
            'gastos_operacion': r['gastos'],
            'gastos_financieros': r['financiero'],
            'impuestos': r['impuestos'],
            'activos_totales': b['activo'], 'pasivos_totales': b['pasivo'],
            'patrimonio': b['capital'],
            'es_cierre_anual': bool(b.get('cierre')),
            'descuadre': b.get('descuadre', 0.0),
            # Un mes incompleto lo es para el grupo si lo es para cualquiera:
            # basta que a una empresa le falte el cierre para que el EBITDA
            # consolidado salga inflado.
            'mes_incompleto': any(
                (s.get(periodo) or {}).get('mes_incompleto')
                for s in series_empresa.values()),
        }
        for k in suma:
            fila[k] = suma[k] if presente[k] else None
        for k, elim in (('activo_circulante', c.get('eliminado_activo') or 0.0),
                        ('pasivo_circulante', c.get('eliminado_pasivo') or 0.0)):
            if fila[k] is not None:
                fila[k] -= elim
        salida.append(fila)
    return salida


# ---------------------------------------------------------------------------
# Bases de las razones de días
# ---------------------------------------------------------------------------
BASES_DIAS_PAGO = ('costo_de_ventas', 'costos_operativos_efectivo')

# La resolución del dato: los importes se publican al peso con dos decimales,
# así que por debajo de un peso no hay información, hay ruido de redondeo.
RESOLUCION_IMPORTE = 1.0


class ConvencionDesconocida(ValueError):
    """Se configuró una convención de cálculo que el código no implementa."""


def bases_de_dias(fila, interco_mes, convenciones):
    """Contra qué se miden los días de cobranza y los días de pago.

    **Cobranza.** Las cuentas por cobrar de este catálogo son a TERCEROS: los
    saldos con empresas del grupo viven en Deudores Diversos y en las cuentas de
    partes relacionadas, no ahí. Medirlas contra los ingresos de libros —que sí
    traen la facturación intercompañía— da días de cobranza bajos, y el sesgo es
    peor en la empresa que más le factura al grupo. Se usan los ingresos a
    terceros.

    **Pago.** El denominador clásico es el costo de ventas. Eso supone que las
    compras pasan por ahí, y en este grupo no pasan. La convención la declara el
    cliente en su configuración; aquí solo se aplica la que haya elegido, y una
    desconocida LEVANTA en vez de caer a la clásica: un tablero que dice medir
    contra una base y mide contra otra no da ninguna señal de estarlo haciendo.
    """
    conv = (convenciones or {}).get('base_dias_pago') or 'costo_de_ventas'
    if conv not in BASES_DIAS_PAGO:
        raise ConvencionDesconocida(
            f'base_dias_pago = {conv!r} no está implementada. Las disponibles '
            f'son: {", ".join(BASES_DIAS_PAGO)}.')

    ic = interco_mes or {}
    ing = fila.get('ingresos')
    base_cob = None if ing is None else ing - (ic.get('ingresos') or 0.0)

    if conv == 'costo_de_ventas':
        base_pag = fila.get('costo_servicio')
    else:
        # Salidas operativas en efectivo: costo más gastos de operación, menos
        # la depreciación, que está dentro de los gastos y no se le paga a nadie.
        partes = (fila.get('costo_servicio'), fila.get('gastos_operacion'),
                  fila.get('depreciacion'))
        base_pag = (None if any(p is None for p in partes)
                    else partes[0] + partes[1] - partes[2])
    if base_pag is not None:
        base_pag -= (ic.get('gastos') or 0.0)

    # UNA BASE QUE NO ES POSITIVA NO ES UNA BASE.
    #
    # Hay empresas del grupo que le facturan casi todo al propio grupo. Al
    # quitarles lo intercompañía, sus ventas a terceros quedan en cero o en
    # negativo —la facturación entre hermanas del mes llega a superar el ingreso
    # registrado en el mayor, por diferencias de fecha entre el documento y su
    # póliza—. Dividir entre eso produjo días de cobranza de −2,213 y días de
    # pago de −3,554.
    #
    # Un número negativo de días no se puede leer mal de una sola forma: parece
    # un error de captura, o un cobro anticipado, o cualquier cosa menos lo que
    # es. Se devuelve None y el tablero muestra el hueco con su explicación:
    # esta empresa opera esencialmente dentro del grupo y sus días contra
    # terceros no significan nada.
    # El corte es UN PESO, no cero, y la diferencia importó de verdad. Los
    # importes se publican con dos decimales, así que por debajo de un peso ya
    # no hay dato: lo que queda es ruido de punto flotante de restar dos cifras
    # casi iguales. Una empresa quedó con base de 1e-14 y sus días de cobranza
    # salieron en 1.8 × 10^16 — un número que la pantalla habría mostrado tal
    # cual. Cero no basta como frontera porque el ruido cae de los dos lados.
    motivo = None
    if base_cob is not None and base_cob < RESOLUCION_IMPORTE:
        base_cob, motivo = None, 'sin_ventas_a_terceros'
    if base_pag is not None and base_pag < RESOLUCION_IMPORTE:
        base_pag = None
        motivo = motivo or 'sin_compras_a_terceros'
    return base_cob, base_pag, motivo


def leer_convenciones(pol):
    """Traduce las convenciones capturadas a los valores que usa el cálculo.

    Se valida aquí y se levanta al primer error, no se ignora lo que no se
    entienda. Una convención mal escrita que cae en silencio al valor por
    defecto produce un tablero que dice medir de una forma y mide de otra.
    """
    c = dict(pol.convenciones or {})
    out = {'base_dias_pago': c.get('base_dias_pago') or 'costo_de_ventas'}
    if out['base_dias_pago'] not in BASES_DIAS_PAGO:
        raise ConvencionDesconocida(
            f"base_dias_pago = {out['base_dias_pago']!r} no está implementada. "
            f"Las disponibles son: {', '.join(BASES_DIAS_PAGO)}.")
    try:
        out['dias_anio'] = int(float(c.get('dias_anio') or rz.DIAS_ANIO))
        out['holgura_semaforo'] = float(
            c.get('holgura_semaforo') or rz.HOLGURA_AMARILLO)
        banda = c.get('banda_tasa_efectiva')
        if banda:
            lo, hi = (float(x) for x in str(banda).split(','))
        else:
            lo, hi = av.BANDA_TASA_EFECTIVA
        out['banda_tasa_efectiva'] = (lo, hi)
    except (TypeError, ValueError) as e:
        raise ConvencionDesconocida(
            f'Una convención de cálculo no se pudo leer: {e}. '
            f'`dias_anio` y `holgura_semaforo` son números; '
            f'`banda_tasa_efectiva` son dos números separados por coma.')
    if out['dias_anio'] <= 0:
        raise ConvencionDesconocida('dias_anio tiene que ser positivo.')
    if not 0 <= out['holgura_semaforo'] < 1:
        raise ConvencionDesconocida(
            'holgura_semaforo va en tanto por uno, entre 0 y 1 — 0.10 es 10%.')
    lo, hi = out['banda_tasa_efectiva']
    if lo >= hi:
        raise ConvencionDesconocida(
            'banda_tasa_efectiva: el límite inferior tiene que ser menor que '
            'el superior.')
    return out


def depurar_dias(r, dias_anio):
    """Suprime las razones de días cuando dejan de describir lo que nombran.

    Una empresa tenía 11,983,235 por cobrar contra 42,000 de ventas a terceros
    en el mes: días de cobranza, 5,124. La división es correcta y el resultado
    no significa nada — el saldo por cobrar no lo explican esas ventas, así que
    no es un plazo de cobranza sino otra cosa (saldos viejos, o partidas que el
    registro intercompañía todavía no reconoce).

    El límite es un año, y no es un número de ajuste: la razón se construye
    anualizando el mes, así que un año es el horizonte completo que el cálculo
    abarca. Pasado eso, el numerador no cabe en el denominador ni una vez, y lo
    que el indicador está diciendo es "este saldo no viene de aquí".

    Se suprime en vez de recortarse. Un valor recortado al límite se ve como un
    dato y se compara contra la meta como si lo fuera.
    """
    limite = dias_anio
    motivos = {}
    for k in ('dso', 'dio', 'dpo'):
        if r.get(k) is not None and r[k] > limite:
            motivos[k] = r[k]
            r[k] = None
    if motivos:
        # El ciclo de efectivo es la suma de los tres: si falta uno, no existe.
        r['ccc'] = None
    return motivos


def costo_inmaterial(fila):
    """¿El costo de ventas es tan chico que el margen bruto no dice nada?

    No lleva un umbral inventado: la pregunta es si el costo de ventas explica
    los costos del negocio, y se contesta comparándolo contra el total de
    costos y gastos de operación. Si el costo directo es la parte menor de lo
    que la empresa gasta en operar, el margen bruto no es un margen bruto — es
    casi el 100% y no se puede comparar contra nada.
    """
    c, g = fila.get('costo_servicio'), fila.get('gastos_operacion')
    if c is None or g is None:
        return False
    total = abs(c) + abs(g)
    return total > 0 and abs(c) < abs(g)


# ---------------------------------------------------------------------------
def procesar(filas, supuestos, metas, interco=None, conv=None, entradas=None,
             empresa=None):
    """Deriva, calcula razones y pinta semáforo para una serie completa.

    `entradas` son las capturas manuales del cliente. Se aplican ANTES de
    derivar nada: si se aplicaran después, una sobrescritura de ingresos
    quedaría en la fila pero los márgenes seguirían calculados con el valor
    viejo, y la pantalla mostraría un ingreso corregido con un margen que no
    corresponde a él.
    """
    derivadas, anterior = [], None
    for f in filas:
        f = dict(f)
        # Los supuestos se resuelven POR FILA, no una vez para toda la serie.
        # Una beta capturada para una empresa y un periodo concreto no serviría
        # de nada si el costo de capital se calculara con un único juego de
        # supuestos para las 81 filas — y el que quedaría es el global, así que
        # la captura específica desaparecería sin dejar rastro.
        sup_fila = supuestos
        if entradas is not None:
            resueltas = entradas.resolver(empresa or f.get('empresa') or '',
                                          f['periodo'])
            f = em.aplicar_a_fila(f, resueltas)
            sup_fila = em.aplicar_a_supuestos(supuestos, resueltas)
        f['base_cobranza'], f['base_pago'], f['sin_base_dias'] = bases_de_dias(
            f, (interco or {}).get(f['periodo']), conv)
        f['costo_inmaterial'] = costo_inmaterial(f)
        d = rz.derivar_estado(f, sup_fila, anterior)
        derivadas.append(d)
        anterior = d

    salida = []
    for i, d in enumerate(derivadas):
        ttm = rz.calcular_ttm(derivadas, i)
        ant = derivadas[i - 1] if i else None
        r = rz.razones(d, ant, ttm, dias_anio=conv['dias_anio'])
        suprimidos = depurar_dias(r, conv['dias_anio'])
        du = rz.dupont_5_factores(d, ant)
        fila = {'periodo': d['periodo']}
        if suprimidos:
            fila['dias_no_explicados'] = sorted(suprimidos)
        for k in CAMPOS_DERIVADOS:
            v = d.get(k)
            # Las banderas y los motivos pasan tal cual. `_r` convierte a float
            # lo que le den y devuelve None cuando no puede: un motivo de
            # supresión como 'sin_ventas_a_terceros' salía anulado, así que el
            # tablero no podía explicar el hueco que él mismo había dejado.
            # Las banderas, los motivos y el rastro de captura manual pasan
            # tal cual. `_r` convierte a float lo que le den y devuelve None
            # cuando no puede: el diccionario de marcas manuales salía anulado
            # y el tablero no podía resaltar lo que él mismo había marcado.
            fila[k] = (v if isinstance(v, (bool, str, dict, list))
                       else _r(v, 6 if k in CAMPOS_TASA else 2))
        # TODO INDICADOR DEL CATÁLOGO VIVE EN UN SOLO LUGAR: `r`.
        #
        # El catálogo declara de dónde sale cada uno, y aquí se resuelve de una
        # vez. Antes el tablero buscaba primero en las razones y, si no estaba,
        # en los campos derivados — y esa búsqueda de respaldo deshacía las
        # supresiones: la tasa efectiva se anula en razones() cuando no es
        # confiable, y reaparecía desde el campo crudo con sus −308%.
        #
        # Que falte una llave significa ahora una sola cosa: no se pudo
        # calcular. Sin segundas lecturas.
        valores = {}
        for k, cat in rz.CATALOGO_KPIS.items():
            v = d.get(k) if cat['fuente'] == 'derivado' else r.get(k)
            if v is not None:
                valores[k] = v
            if cat['ttm'] and r.get(cat['ttm']) is not None:
                valores[cat['ttm']] = r[cat['ttm']]
        # Las razones llevan más decimales: un margen redondeado a dos queda en
        # 0.19 y pierde justo la diferencia contra una meta de 0.19.
        fila['r'] = {k: _r(v, 6) for k, v in valores.items()}
        fila['dupont'] = {k: _r(v, 6) for k, v in du.items() if v is not None}
        # NO se publica el semáforo ya resuelto, y es deliberado. El tablero
        # tiene que recalcularlo de todos modos: el usuario puede ver la base de
        # doce meses, y entonces lo que hay que comparar contra la meta es el
        # acumulado, no el valor del mes. Un semáforo precocido contra el mes
        # sería un segundo dato que dice lo mismo de otra forma, y el día que
        # los dos no coincidan nadie sabría cuál manda.
        salida.append(fila)
    return salida


# ---------------------------------------------------------------------------
def main():
    import repositorio as repo
    cliente = repo.cliente_actual(repo.almacen_por_defecto())
    pol = cliente.politica
    supuestos = dict(pol.supuestos)
    metas = dict(pol.metas)
    print(f'cliente: {cliente.nombre} · norma: {cliente.normas}')
    if not supuestos:
        print('  AVISO: sin supuestos de costo de capital. El WACC, el ROIC '
              'contra WACC y el EVA no se van a poder calcular.')
        print('  Se llenan con: python finanzas/configuracion/configurar.py '
              '--sembrar-politica')
    if not metas:
        print('  AVISO: sin metas configuradas. Los indicadores salen sin '
              'semáforo — no hay contra qué compararlos.')

    # El vocabulario extra del cliente se aplica ANTES de leer nada del ERP:
    # después, los rubros ya estarían clasificados con el de fábrica.
    mk.aplicar_vocabulario_cliente(getattr(pol, 'vocabulario_rubros', None))

    # Las capturas manuales del equipo. Se cargan aquí y no dentro del bucle:
    # leer el archivo una vez por empresa multiplicaría el trabajo y, peor,
    # abriría la puerta a que dos series se construyeran con versiones
    # distintas si alguien guarda a media corrida.
    entradas = em.cargar(repo.almacen_por_defecto(), cliente)
    if entradas.entradas:
        n_sob = len(entradas.sobrescrituras())
        print(f'  entradas manuales: {len(entradas.entradas)} '
              f'({n_sob} sobrescritura(s) de cifras calculadas)')

    conv = leer_convenciones(pol)
    print(f'  convenciones: días/año {conv["dias_anio"]} · '
          f'holgura {conv["holgura_semaforo"]:.0%} · '
          f'base de días de pago "{conv["base_dias_pago"]}"')

    ruta_fin = os.path.join(AQUI, 'finanzas.json')
    if not os.path.exists(ruta_fin):
        print('Falta finanzas.json. Corre antes exportar_finanzas.py: el '
              'consolidado de este archivo se construye sobre aquél para que '
              'las dos pantallas no puedan contradecirse.')
        return 1
    with open(ruta_fin, encoding='utf-8') as f:
        fin = json.load(f)

    anio_min = cliente.retencion.anio_minimo()
    empresas = [e for e in fin['empresas']]

    crudas, series_idx = {}, {}
    for ini in empresas:
        filas = mk.serie_financiera(ini, anio_min, cliente.normas)
        crudas[ini] = filas
        series_idx[ini] = {f['periodo']: f for f in filas}
        print(f'  {ini}: {len(filas)} periodos')

    cons = serie_consolidada(fin, series_idx)
    if cons:
        crudas[CLAVE_GRUPO] = cons
        print(f'  consolidado: {len(cons)} periodos')

    salida = {
        'cliente': cliente.nombre,
        'norma': cliente.normas,
        'clave_grupo': CLAVE_GRUPO,
        'empresas': empresas,
        'nombres': fin.get('nombres', {}),
        'periodos': fin.get('periodos', []),
        'metas': metas,
        'supuestos': supuestos,
        'fuentes': dict(pol.fuentes),
        'catalogo': rz.CATALOGO_KPIS,
        'familias': [{'id': k, 'nombre': n} for k, n in rz.FAMILIAS],
        'holgura_semaforo': conv['holgura_semaforo'],
        'series': {},
        'avisos': [],
    }
    convenciones_pub = dict(pol.convenciones)
    salida['convenciones'] = convenciones_pub
    interco = fin.get('interco') or {}
    for clave, filas in crudas.items():
        # El consolidado NO lleva ajuste de intercompañía: sus ingresos y gastos
        # ya vienen eliminados. Restárselo otra vez lo quitaría dos veces.
        ic = {} if clave == CLAVE_GRUPO else interco.get(clave, {})
        # El consolidado NO recibe las entradas manuales: ya se construyó sobre
        # los estados de las empresas, que sí las llevan. Aplicárselas otra vez
        # sumaría dos veces la misma corrección.
        ent_serie = None if clave == CLAVE_GRUPO else entradas
        salida['series'][clave] = procesar(filas, supuestos, metas, ic, conv,
                                           ent_serie, clave)

    # --- Avisos que el tablero muestra arriba, no escondidos en un log -------
    faltan = [k for k in ('rf', 'beta', 'erp', 'kd') if k not in supuestos]
    if faltan:
        salida['avisos'].append(
            f'Sin {", ".join(faltan)} en la configuración, el WACC no se calcula.')
    sin_capex = all(f.get('fcf') is None
                    for s in salida['series'].values() for f in s)
    if sin_capex:
        salida['avisos'].append(
            'No hay extracción de altas de activo fijo, así que no hay capex y '
            'el flujo libre no se puede calcular. Aparece vacío, no en cero.')
    if conv['base_dias_pago'] != 'costo_de_ventas':
        salida['avisos'].append(
            'Los días de pago se miden contra costos y gastos de operación en '
            'efectivo, no contra el costo de ventas: en este grupo el costo '
            'directo se registra como gasto de operación y el cálculo clásico '
            'daba cientos de días. Se cambia desde la configuración.')
    solo_grupo = sorted({c for c, s in salida['series'].items()
                         if s and s[-1].get('sin_base_dias') == 'sin_ventas_a_terceros'})
    if solo_grupo:
        salida['avisos'].append(
            f'Los días de cobranza y el ciclo de efectivo salen vacíos en '
            f'{", ".join(solo_grupo)}: al descontar la facturación entre '
            f'empresas del grupo no les quedan ventas a terceros contra las '
            f'cuales medirlos. No es un dato faltante; es que la razón no '
            f'aplica a una empresa que opera hacia adentro del grupo.')
    inmateriales = sorted({c for c, s in salida['series'].items()
                           if s and s[-1].get('costo_inmaterial')})
    if inmateriales:
        salida['avisos'].append(
            f'El margen bruto no es interpretable en {", ".join(inmateriales)}: '
            f'su costo de ventas es menor que sus gastos de operación, así que '
            f'sale cerca del 100% y no se puede comparar con nada.')
    incompletos = sorted({f['periodo'] for s in salida['series'].values()
                          for f in s if f.get('mes_incompleto')})
    if incompletos:
        salida['avisos'].append(
            f'Periodo(s) a medio cerrar: {", ".join(incompletos)}. Les falta el '
            f'asiento de depreciación del mes, así que su EBITDA sale alto.')

    # ---------------------------------------------------------------------
    # La BASE del cálculo, aparte de los indicadores ya calculados
    # ---------------------------------------------------------------------
    # Son las filas tal como salen del ERP, ANTES de aplicarles supuestos. Con
    # esto —y sin necesidad de los 180 MB de extracción— se puede recalcular
    # todo lo que depende del costo de capital: Ke, WACC, NOPAT, ROIC, el
    # spread y el EVA.
    #
    # Existe para que el servidor pueda rehacer los indicadores cuando alguien
    # cambia una beta, en vez de tener que correr el pipeline entero. Sin este
    # archivo, cambiar un supuesto obliga a una reextracción de cinco minutos
    # para ver el efecto — y en la práctica eso significa que nadie lo prueba.
    #
    # Se publica aparte de kpis.json a propósito: kpis.json es el RESULTADO y
    # lo consume la pantalla; esto es la ENTRADA y lo consume el servidor.
    ruta_base = os.path.join(AQUI, 'base_financiera.json')
    with open(ruta_base, 'w', encoding='utf-8') as f:
        json.dump({'series': crudas, 'empresas': empresas,
                   'clave_grupo': CLAVE_GRUPO, 'interco': interco,
                   'metas': metas, 'convenciones': convenciones_pub,
                   'norma': cliente.normas},
                  f, ensure_ascii=False, separators=(',', ':'))
    print(f'base_financiera.json: {os.path.getsize(ruta_base) / 1024:.0f} KB '
          f'(lo que el servidor necesita para recalcular sin el ERP)')

    ruta = os.path.join(AQUI, 'kpis.json')
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, separators=(',', ':'))
    print(f'\nkpis.json: {os.path.getsize(ruta) / 1024:.0f} KB · '
          f'{len(salida["series"])} series · {len(salida["periodos"])} periodos')
    for a in salida['avisos']:
        print(f'  aviso: {a}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
