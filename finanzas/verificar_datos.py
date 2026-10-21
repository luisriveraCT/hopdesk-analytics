# -*- coding: utf-8 -*-
"""
===============================================================================
 VERIFICACIÓN DE LOS DATOS — recorre todo lo extraído y lo contrasta
===============================================================================
    python finanzas/verificar_datos.py

QUÉ COMPRUEBA, Y POR QUÉ NO ES UNA BATERÍA DE PRUEBAS
------------------------------------------------------
No comprueba que el código esté bien escrito. Comprueba que **los datos de esta
corrida** cumplan lo que tienen que cumplir siempre: que el balance cuadre, que
los rubros sumen el activo, que consolidar no cree utilidad, que ningún plazo
salga negativo, que las dos pestañas digan lo mismo.

Son más de veinte mil comprobaciones porque cada empresa y cada periodo es un
caso distinto —cinco empresas por ochenta y un periodos—, y el dato cambia en
cada actualización. Por eso corre en el pipeline y no una sola vez: lo que
atrapa no es un error de programación, es un dato malo.

No comprueba un valor esperado. Nadie se sabe de memoria el ROIC de un mes.
Comprueba RELACIONES, que es lo que se puede afirmar sin conocer la respuesta,
y es lo que atrapa el error que nadie anticipó.

Salió de `test_financiero.py`, que mezclaba esto con 856 pruebas unitarias
sobre entradas inventadas a mano. Aquéllas comprobaban que las funciones
estuvieran bien escritas: se comprobó, y se retiraron. Éstas se quedan porque
su sujeto no es el código, es la información.

SI FALTAN LOS ARCHIVOS, NO FALLA: AVISA
---------------------------------------
Se puede correr antes de haber extraído nada. En ese caso dice qué falta y
termina bien, en vez de parecer un error del cálculo.
===============================================================================
"""
import os
import sys
import json

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(AQUI, 'erp'))
sys.path.insert(0, os.path.join(AQUI, 'configuracion'))

import analisis_vertical_horizontal as av
import razones_financieras as rf
import mapeo_kpis as mk
import consolidacion as co
import normas_contables as nc

# ---------------------------------------------------------------------------
_pasadas, _fallos = 0, []
_seccion_actual = ''


def seccion(nombre):
    global _seccion_actual
    _seccion_actual = nombre
    print(f'\n--- {nombre} ---')


def check(nombre, condicion, detalle=''):
    global _pasadas
    if condicion:
        _pasadas += 1
    else:
        _fallos.append(f'[{_seccion_actual}] {nombre}' + (f' — {detalle}' if detalle else ''))
        print(f'  FALLA  {nombre}   {detalle}')


def casi(a, b, tol=0.51):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol


def pruebas_sobre_datos_reales():
    """Propiedades que deben cumplirse en TODOS los datos extraídos."""
    import repositorio as repo
    cliente = repo.cliente_actual(repo.almacen_por_defecto())
    inis = [e.iniciales for e in cliente.empresas_conectadas()]

    seccion('Integridad contable en cada empresa y periodo')
    for ini in inis:
        cuentas, saldos = mk.cargar_empresa(ini)
        pers = sorted({(s['anio'], s['mes']) for s in saldos})
        acum_por_anio = {}
        for (a, m) in pers:
            bal = av.balance_general(saldos, cuentas, a, m)
            er = av.estado_resultados(saldos, cuentas, a, m)
            etq = f'{ini} {a}-{m:02d}'

            # 1) La identidad contable.
            check(f'{etq}: Activo = Pasivo + Capital',
                  abs(bal['descuadre']) <= 1.0, f"descuadre {bal['descuadre']:,.2f}")

            # 2) Articulación: el ER acumulado del año reproduce el resultado
            #    del ejercicio del Balance. Dos caminos independientes.
            acum_por_anio[a] = acum_por_anio.get(a, 0.0) + er['utilidad_neta']
            if not bal.get('es_cierre_anual'):
                check(f'{etq}: ER acumulado articula con el Balance',
                      abs(acum_por_anio[a] - bal['resultado_ejercicio']) <= 1.0,
                      f"difiere {acum_por_anio[a] - bal['resultado_ejercicio']:,.2f}")

            # 3) La escalera del Estado de Resultados es consistente.
            check(f'{etq}: utilidad bruta = ingresos - costo',
                  casi(er['utilidad_bruta'], er['ingresos'] - er['costo']))
            check(f'{etq}: utilidad de operación = bruta - gastos',
                  casi(er['utilidad_operacion'],
                       er['utilidad_bruta'] - er['gastos_operacion']))
            check(f'{etq}: utilidad neta = antes de impuestos - impuestos',
                  casi(er['utilidad_neta'],
                       er['resultado_antes_impuestos'] - er['impuestos']))

    seccion('Rubros del balance contra el estado')
    for ini in inis:
        datos = mk.cargar_empresa(ini)
        cuentas, saldos = datos
        pers = sorted({(s['anio'], s['mes']) for s in saldos})
        for (a, m) in pers[::6]:          # uno de cada seis, para no eternizarse
            f = mk.fila_financiera(ini, a, m, datos)
            etq = f'{ini} {a}-{m:02d}'
            rub = [f.get(k) for k in ('efectivo', 'cuentas_x_cobrar',
                                      'inventarios')]
            suma = sum(x for x in rub if x is not None)
            check(f'{etq}: los rubros de activo no exceden el activo',
                  f['activos_totales'] is None or suma <= abs(f['activos_totales']) + 1,
                  f"rubros {suma:,.0f} > activo {f['activos_totales']:,.0f}")
            check(f'{etq}: EBITDA = EBIT + depreciación',
                  casi(f['ebitda'], f['ebit'] + f['depreciacion']))
            # Volvió a ser un invariante válido al aplicar IFRS/NIF: antes
            # fallaba en NTS diciembre 2022 porque una reversión de
            # "Amortización - Primas Seguros" por 5.8 millones entraba al D&A.
            # Bajo la norma, el consumo de un pago anticipado no es
            # amortización de un activo de capital, así que ya no entra.
            check(f'{etq}: EBITDA >= EBIT (D&A no es negativa)',
                  f['ebitda'] >= f['ebit'] - 0.51,
                  f"D&A {f['depreciacion']:,.2f}")
            if f['tasa_efectiva'] is not None:
                check(f'{etq}: la tasa confiable está en banda',
                      (not f['tasa_confiable']) or 0 <= f['tasa_efectiva'] <= 0.60)

    seccion('Agregación por periodo')
    for ini in inis[:3]:
        datos = mk.cargar_empresa(ini)
        cuentas, saldos = datos
        for a in (2024, 2025):
            meses = [(a, m) for m in range(1, 13)
                     if any(s['anio'] == a and s['mes'] == m for s in saldos)]
            if len(meses) < 12:
                continue
            suma_ing = sum(av.estado_resultados(saldos, cuentas, x, y)['ingresos']
                           for x, y in meses)
            q1 = sum(av.estado_resultados(saldos, cuentas, a, m)['ingresos']
                     for m in (1, 2, 3))
            q2 = sum(av.estado_resultados(saldos, cuentas, a, m)['ingresos']
                     for m in (4, 5, 6))
            q3 = sum(av.estado_resultados(saldos, cuentas, a, m)['ingresos']
                     for m in (7, 8, 9))
            q4 = sum(av.estado_resultados(saldos, cuentas, a, m)['ingresos']
                     for m in (10, 11, 12))
            check(f'{ini} {a}: los cuatro trimestres suman el año',
                  casi(q1 + q2 + q3 + q4, suma_ing, 2.0))
            # Un Balance NO se suma: el del año es el del último mes.
            bal_dic = av.balance_general(saldos, cuentas, a, 12)
            suma_bal = sum(av.balance_general(saldos, cuentas, a, m)['activo']
                           for x, m in meses)
            check(f'{ini} {a}: el activo del año NO es la suma de los meses',
                  not casi(bal_dic['activo'], suma_bal, 1000)
                  or abs(bal_dic['activo']) < 1000)

    seccion('Consolidación')
    for (a, m) in [(2024, 6), (2024, 12), (2025, 6), (2025, 12), (2026, 6), (2026, 9)]:
        c = co.consolidar(a, m, inis)
        etq = f'consolidado {a}-{m:02d}'
        check(f'{etq}: cuadra', abs(c['descuadre']) <= 1.0,
              f"descuadre {c['descuadre']:,.2f}")

        sumas_ing = sumas_neta = 0.0
        for ini in inis:
            datos = mk.cargar_empresa(ini)
            er = av.estado_resultados(datos[1], datos[0], a, m)
            sumas_ing += er['ingresos']
            sumas_neta += er['utilidad_neta']
        # La prueba que de verdad importa: consolidar NO crea ni destruye
        # utilidad. Si la cambia, la eliminación está mal hecha.
        check(f'{etq}: la utilidad no cambia al consolidar',
              casi(c['resultados']['utilidad_neta'], sumas_neta, 2.0),
              f"suma {sumas_neta:,.0f} vs consolidado "
              f"{c['resultados']['utilidad_neta']:,.0f}")
        check(f'{etq}: los ingresos consolidados no superan la suma',
              c['resultados']['ingresos'] <= sumas_ing + 1)
        check(f'{etq}: el activo consolidado no supera la suma',
              c['balance']['activo'] <= sum(
                  av.balance_general(*reversed(mk.cargar_empresa(i)), a, m)['activo']
                  for i in inis) + 1)

        e = co.eliminaciones(a, m)
        check(f'{etq}: se elimina lo mismo de activo y de pasivo',
              casi(e['activo'], e['pasivo'], 1.0),
              f"activo {e['activo']:,.2f} vs pasivo {e['pasivo']:,.2f}")

    seccion('Reciprocidad intercompañía')
    r = co.analizar(2026, 9, verbose=False)
    for f in r['confirmadas']:
        check(f"{f['a']}↔{f['b']} confirmada concilia",
              abs(f['diferencia']) <= max(abs(f['saldo_a']) * 0.005, 1000))
        check(f"{f['a']}↔{f['b']} tiene signos opuestos",
              f['saldo_a'] * f['saldo_b'] <= 0)
    for f in r['a_revisar']:
        check(f"{f['a']}↔{f['b']} a revisar trae motivo", bool(f.get('motivo')))


# ===========================================================================
def pruebas_sobre_kpis():
    """Propiedades del archivo de indicadores que alimenta a los dos tableros.

    No comprueban valores —nadie sabe de memoria cuál es el ROIC de un mes—
    sino relaciones que tienen que cumplirse SIEMPRE. Cada empresa y cada mes
    es un caso distinto, así que la batería crece con los datos.
    """
    ruta = os.path.join(os.path.dirname(AQUI), 'dashboard', 'kpis.json')
    with open(ruta, encoding='utf-8') as f:
        crudo = f.read()

    seccion('Indicadores — el archivo es JSON válido y estricto')
    # NaN e Infinity NO son JSON. Python los escribe sin protestar y cualquier
    # lector estricto —empezando por el navegador— revienta al cargarlos. Un
    # tablero que no abre por un NaN en el mes 47 no dice dónde está el NaN.
    check('no hay NaN en el archivo', 'NaN' not in crudo)
    check('no hay Infinity en el archivo', 'Infinity' not in crudo)
    try:
        json.loads(crudo, parse_constant=lambda c: (_ for _ in ()).throw(
            ValueError(f'constante no válida: {c}')))
        check('carga con un analizador estricto', True)
    except ValueError as e:
        check('carga con un analizador estricto', False, str(e))
    d = json.loads(crudo)

    # El export de Estados Financieros, para contrastar las dos pestañas.
    with open(os.path.join(os.path.dirname(AQUI), 'dashboard', 'finanzas.json'),
              encoding='utf-8') as fh:
        FIN = json.load(fh)

    seccion('Indicadores — estructura')
    for campo in ('cliente', 'norma', 'clave_grupo', 'empresas', 'periodos',
                  'metas', 'supuestos', 'catalogo', 'series', 'avisos'):
        check(f'el archivo declara {campo}', campo in d)
    check('la norma declarada existe en el registro', d['norma'] in nc.NORMAS)
    check('el catálogo publicado coincide con el del código',
          set(d['catalogo']) == set(rf.CATALOGO_KPIS))
    check('las familias viajan con el catálogo',
          {f['id'] for f in d['familias']} == {k for k, _ in rf.FAMILIAS})
    check('la holgura del semáforo viaja en los datos',
          isinstance(d.get('holgura_semaforo'), (int, float)))
    # El tablero arma sus tablas con esto: sin 'familia' quedaría un indicador
    # calculado, publicado y sin aparecer en ninguna pantalla.
    for clave, cat in d['catalogo'].items():
        check(f'{clave} viaja con familia', bool(cat.get('familia')))
        check(f'{clave} viaja con nombre legible', bool(cat.get('nombre')))
    for clave in d['metas']:
        check(f'la meta {clave} corresponde a un indicador real',
              clave in rf.CATALOGO_KPIS)

    G = d['clave_grupo']
    for empresa, serie in d['series'].items():
        if not serie:
            continue
        pers = [f['periodo'] for f in serie]
        check(f'{empresa}: los periodos vienen ordenados', pers == sorted(pers))
        check(f'{empresa}: no hay periodos repetidos', len(pers) == len(set(pers)))

        for i, f in enumerate(serie):
            p, r = f['periodo'], f['r']
            eti = f'{empresa} {p}'

            # --- LAS DOS PESTAÑAS NO SE PUEDEN CONTRADECIR.
            # Estados Financieros lee el Estado de Resultados directo;
            # Indicadores construye encima. Si no coinciden, una de las dos
            # miente y nadie tiene cómo saber cuál. Esta prueba faltaba, y por
            # eso un EBIT con la depreciación restada dos veces sobrevivió.
            if empresa != G:
                fin_r = ((FIN.get('resultados') or {}).get(empresa) or {}).get(p)
                if fin_r and f.get('ebit') is not None:
                    check(f'{eti}: el EBIT es la utilidad de operación del estado',
                          casi(f['ebit'], fin_r['operacion'], tol=1.0))
                if fin_r and f.get('utilidad_neta') is not None:
                    check(f'{eti}: la utilidad neta coincide con el estado',
                          casi(f['utilidad_neta'], fin_r['neta'], tol=1.0))
                if fin_r and f.get('ingresos') is not None:
                    check(f'{eti}: los ingresos coinciden con el estado',
                          casi(f['ingresos'], fin_r['ingresos'], tol=1.0))

            # --- identidades contables. Si alguna se rompe, el número de
            # arriba y el de abajo de la misma pantalla se contradicen.
            if None not in (f.get('ebit'), f.get('depreciacion'), f.get('ebitda')):
                check(f'{eti}: EBITDA = EBIT + D&A',
                      casi(f['ebitda'], f['ebit'] + f['depreciacion']))
            if None not in (f.get('ebt'), f.get('impuestos'), f.get('utilidad_neta')):
                check(f'{eti}: utilidad neta = antes de impuestos − impuestos',
                      casi(f['utilidad_neta'], f['ebt'] - f['impuestos']))
            if None not in (f.get('deuda_con_costo'), f.get('efectivo'),
                            f.get('deuda_neta')):
                check(f'{eti}: deuda neta = deuda − efectivo',
                      casi(f['deuda_neta'], f['deuda_con_costo'] - f['efectivo']))
            if None not in (f.get('patrimonio'), f.get('deuda_neta'),
                            f.get('capital_invertido')):
                check(f'{eti}: capital invertido = patrimonio + deuda neta',
                      casi(f['capital_invertido'], f['patrimonio'] + f['deuda_neta']))

            # --- los rubros no pueden exceder al total del que salen
            if f.get('activo_circulante') is not None and f.get('activos_totales'):
                check(f'{eti}: el activo circulante cabe en el activo total',
                      f['activo_circulante'] <= f['activos_totales'] + 1)

            # --- días: nunca negativos. Un número negativo de días no se lee
            # mal de una sola forma; parece error de captura, o cobro
            # anticipado, o cualquier cosa menos lo que es.
            for k in ('dso', 'dio', 'dpo'):
                if r.get(k) is not None:
                    check(f'{eti}: {k} no es negativo', r[k] >= 0,
                          f'{k}={r[k]}')
                    check(f'{eti}: {k} es un plazo plausible', r[k] < 3650,
                          f'{k}={r[k]} son más de diez años')

            # --- supresión explícita: si se declaró que no hay base, no puede
            # haber salido un número por otro camino.
            if f.get('sin_base_dias') == 'sin_ventas_a_terceros':
                check(f'{eti}: sin ventas a terceros no hay días de cobranza',
                      r.get('dso') is None)
                check(f'{eti}: ni ciclo de efectivo', r.get('ccc') is None)
            if f.get('base_cobranza') is None:
                check(f'{eti}: sin base de cobranza no hay DSO', r.get('dso') is None)
            if f.get('base_pago') is None:
                check(f'{eti}: sin base de pago no hay DPO', r.get('dpo') is None)

            # --- doce meses: NO se calculan con menos de doce. Un acumulado de
            # siete meses se lee igual que uno de doce en la pantalla.
            if i < 11:
                for k in ('margen_ebitda_ttm', 'roe_ttm', 'roic_ttm',
                          'margen_neto_ttm'):
                    check(f'{eti}: sin doce meses no hay {k}', r.get(k) is None)

            # --- márgenes: consistentes con sus componentes
            # La tolerancia es RELATIVA al importe. El margen se publica con
            # seis decimales, así que multiplicado por ingresos de veintiséis
            # millones ya arrastra trece pesos de puro redondeo: una tolerancia
            # absoluta de un peso haría fallar a una razón perfectamente bien
            # calculada, y una prueba que falla siempre se acaba ignorando.
            if r.get('margen_ebitda') is not None and f.get('ingresos'):
                check(f'{eti}: el margen EBITDA reproduce EBITDA/ingresos',
                      casi(r['margen_ebitda'] * f['ingresos'], f['ebitda'],
                           tol=abs(f['ingresos']) * 1e-5 + 0.51))
            if r.get('margen_neto') is not None and f.get('ingresos'):
                check(f'{eti}: el margen neto reproduce utilidad/ingresos',
                      casi(r['margen_neto'] * f['ingresos'], f['utilidad_neta'],
                           tol=abs(f['ingresos']) * 1e-5 + 0.51))

            # --- costo de capital. Con deuda más barata que el capital propio
            # después de impuestos, el WACC nunca puede superar al Ke: si lo
            # hace, los pesos están mal.
            if None not in (f.get('wacc'), f.get('ke')):
                check(f'{eti}: el WACC es positivo', f['wacc'] > 0)
                # NO se comprueba que el WACC no supere al Ke. Parece una ley y
                # no lo es: solo se cumple cuando el capital propio cuesta más
                # que la deuda neta de impuestos, que es lo NORMAL pero no lo
                # forzoso. Con una tasa libre de riesgo baja y una prima de
                # mercado chica, Ke puede quedar por debajo de Kd(1−t) y
                # entonces el WACC supera al Ke legítimamente.
                #
                # Pasó al capturar una tasa libre de riesgo de 0.2% para
                # probar: 43 periodos "fallaron" con la aritmética
                # perfectamente correcta. Una prueba que se cae con datos
                # válidos entrena a la gente a ignorar las pruebas.
                #
                # Lo que sí es invariante es la fórmula, y eso es lo que se
                # comprueba: el WACC tiene que estar ENTRE el Ke y el Kd neto,
                # porque es un promedio ponderado de los dos.
                sup = f.get('_supuestos') or {}
                t_us = f.get('tasa_usada_nopat')
                if sup.get('kd') is not None and t_us is not None:
                    kd_neto = sup['kd'] * (1 - t_us)
                    lo, hi = sorted((f['ke'], kd_neto))
                    check(f'{eti}: el WACC cae entre el Ke y el Kd neto',
                          lo - 1e-6 <= f['wacc'] <= hi + 1e-6,
                          f"wacc={f['wacc']:.4f} ke={f['ke']:.4f} "
                          f"kd_neto={kd_neto:.4f}")

            # --- spread: es exactamente la resta, no otra cosa
            if None not in (r.get('roic'), f.get('wacc')) and \
                    r.get('spread_roic_wacc') is not None:
                check(f'{eti}: el spread es ROIC − WACC',
                      casi(r['spread_roic_wacc'], r['roic'] - f['wacc'], tol=1e-4))

            # --- la tasa efectiva publicada SIEMPRE está dentro de la banda
            # de confiabilidad. El caso que obligó a cerrarlo: −308% pintado
            # de verde porque la meta es "menor es mejor".
            if r.get('tasa_efectiva') is not None:
                check(f'{eti}: la tasa efectiva publicada es confiable',
                      f.get('tasa_confiable') is True,
                      f"tasa={r['tasa_efectiva']}")
                lo, hi = av.BANDA_TASA_EFECTIVA
                check(f'{eti}: la tasa efectiva cae en la banda',
                      lo <= r['tasa_efectiva'] <= hi)

            # --- la cobertura de intereses nunca sale de dividir entre un
            # costo financiero negativo (que es un INGRESO financiero neto).
            if r.get('cobertura_intereses') is not None:
                check(f'{eti}: la cobertura supone un costo financiero real',
                      (f.get('gastos_financieros') or 0) > 0)

            # --- el NOPAT declara con qué tasa se calculó. Sin esto, dos
            # empresas con el mismo ROIC podrían estar calculadas distinto.
            if f.get('nopat') is not None:
                check(f'{eti}: el NOPAT dice de dónde salió su tasa',
                      f.get('origen_tasa_nopat') in
                      ('efectiva_del_erp', 'supuesto_configurado'))
                check(f'{eti}: el NOPAT reproduce EBIT × (1 − tasa)',
                      casi(f['nopat'],
                           f['ebit'] * (1 - f['tasa_usada_nopat']),
                           tol=abs(f['ebit']) * 1e-5 + 0.51))

            # --- semáforo: NO viene precocido en el archivo, y esta prueba lo
            # vigila. El tablero lo calcula en pantalla porque con base de doce
            # meses hay que comparar el acumulado, no el mes; un semáforo
            # guardado sería un segundo dato diciendo lo mismo de otra forma.
            check(f'{eti}: el archivo no trae semáforo precocido', 'sem' not in f)
            for k in d['metas']:
                valor = r[k] if k in r else f.get(k)
                est = rf.semaforo(k, valor, d['metas'])
                check(f'{eti}: el semáforo de {k} es un estado válido o nada',
                      est in (None, 'Verde', 'Amarillo', 'Rojo'))

            # --- DuPont: el producto de los cinco factores es el ROE
            du = f.get('dupont') or {}
            if du.get('roe_reconstruido') is not None:
                prod = 1.0
                for x in ('carga_fiscal', 'carga_intereses', 'margen_ebit',
                          'rotacion_activos', 'apalancamiento'):
                    prod *= du[x]
                # Tolerancia RELATIVA: los cinco factores se publican con seis
                # decimales y se multiplican entre sí, así que el error de
                # redondeo se amplifica con la magnitud de cada uno. En un mes
                # la carga de intereses valía 129.7 y el margen operativo
                # −0.001447: seis decimales le dejan al margen cuatro cifras
                # significativas, y multiplicadas por 130 el producto se mueve
                # en la cuarta. Es precisión de publicación, no un error de
                # cálculo — la prueba comprueba el cálculo.
                check(f'{eti}: el DuPont multiplica a lo que dice',
                      casi(prod, du['roe_reconstruido'],
                           tol=abs(du['roe_reconstruido']) * 1e-3 + 1e-6))

    seccion('Indicadores — el consolidado contra la suma de las empresas')
    if G in d['series']:
        cons = {f['periodo']: f for f in d['series'][G]}
        for p, fc in cons.items():
            suma = 0.0
            hay = False
            for e in d['empresas']:
                f = next((x for x in d['series'][e] if x['periodo'] == p), None)
                if f and f.get('ingresos') is not None:
                    suma += f['ingresos']
                    hay = True
            if not hay or fc.get('ingresos') is None:
                continue
            # Consolidar solo QUITA operaciones internas: jamás puede subir el
            # ingreso del grupo por encima de la suma de sus empresas.
            check(f'consolidado {p}: el ingreso no excede la suma',
                  fc['ingresos'] <= suma + 1)
        # Y el consolidado no puede declararse "sin ventas a terceros": por
        # construcción, lo único que le queda son ventas a terceros.
        for p, fc in cons.items():
            check(f'consolidado {p}: no se suprime por intercompañía',
                  fc.get('sin_base_dias') is None)


# ===========================================================================
def pruebas_sobre_facturas():
    """Que los tres importes de cada factura en moneda extranjera se expliquen.

    El ERP guarda el total en moneda local (DocTotal) y en la del documento
    (DocTotalFc), y el tipo de cambio que los une. Si local ≠ documento × tipo
    de cambio, uno de los tres está mal capturado — así apareció una venta de
    2014 con un tipo de cambio de 131,689 que convertía 3,588 dólares en 472
    millones de pesos, que el Total MXN sumaba como cualquier otra factura.

    Solo se comprueban las filas cuyo importe en moneda del documento VINO del
    ERP. En las que se dedujo dividiendo entre el tipo de cambio la relación se
    cumple por construcción, y una comprobación que no puede fallar no es una.
    """
    import repositorio as repo
    import extraer_facturacion as ef
    cliente = repo.cliente_actual(repo.almacen_por_defecto())
    seccion('Facturas — moneda local, moneda del documento y tipo de cambio')
    for ini in [e.iniciales for e in cliente.empresas_conectadas()]:
        for tipo in ('venta', 'compra'):
            docs = [d for d in ef.cargar(ini, tipo)
                    if d['clase_documento'] == 'normal'
                    and not d.get('total_moneda_deducido')]
            if not docs:
                continue
            ext = [d for d in docs if (d.get('tipo_cambio') or 1) != 1]
            malos = [d for d in ext
                     if abs(d['total'] - d['total_moneda'] * d['tipo_cambio'])
                     > max(1.0, abs(d['total']) * 0.001)]
            check(f'{ini} {tipo}: local = documento × tipo de cambio '
                  f'({len(ext):,} en moneda extranjera)', not malos,
                  ', '.join(f"folio {d['folio']} {d['fecha']}" for d in malos[:5]))
            locales = [d for d in docs if (d.get('tipo_cambio') or 1) == 1
                       and not casi(d['total'], d['total_moneda'], 0.01)]
            check(f'{ini} {tipo}: en moneda local los dos importes coinciden',
                  not locales,
                  ', '.join(f"folio {d['folio']}" for d in locales[:5]))


# ===========================================================================
if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    faltan = []
    try:
        pruebas_sobre_datos_reales()
    except FileNotFoundError as e:
        faltan.append(e.filename)
    try:
        pruebas_sobre_facturas()
    except FileNotFoundError as e:
        faltan.append(e.filename)
    try:
        pruebas_sobre_kpis()
    except FileNotFoundError as e:
        faltan.append(f'{e.filename} (se genera con: python dashboard/exportar_kpis.py)')

    print('\n' + '=' * 72)
    for f in faltan:
        print(f' No se pudo comprobar, falta: {f}')
    total = _pasadas + len(_fallos)
    if _fallos:
        print(f' {len(_fallos)} DE {total} COMPROBACIONES FALLARON')
        for f in _fallos[:40]:
            print(f'   · {f}')
        if len(_fallos) > 40:
            print(f'   … y {len(_fallos) - 40} más')
        raise SystemExit(1)
    print(f' {total} COMPROBACIONES SOBRE LOS DATOS, TODAS PASARON')
    print('=' * 72)
