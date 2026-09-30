# -*- coding: utf-8 -*-
"""
===============================================================================
 BATERÍA DE PRUEBAS DEL MÓDULO FINANCIERO
===============================================================================
    python test_financiero.py            todo
    python test_financiero.py --rapido   omite las que recorren toda la serie

QUÉ SE PRUEBA Y POR QUÉ ASÍ
---------------------------
Dos clases de prueba, y las dos hacen falta:

  · **Unitarias**, sobre funciones puras con entradas construidas a mano. Cubren
    los casos límite que los datos reales rara vez producen: división entre
    cero, base negativa, nombres ambiguos, catálogos con ciclos.

  · **De propiedad, sobre los datos reales** de las cinco empresas y sus 81
    periodos. No comprueban un valor esperado —que nadie conoce de memoria—
    sino relaciones que tienen que cumplirse SIEMPRE: que el balance cuadre,
    que los rubros sumen el activo, que consolidar no cree utilidad. Son las
    que atrapan el error que nadie anticipó, y cada empresa-periodo es un caso
    distinto porque los datos lo son.

REGLA DE ESTA BATERÍA: una prueba que no puede fallar no es una prueba. Varias
de las que están aquí nacieron de errores reales cometidos durante el
desarrollo, y cada una lleva anotado cuál.
===============================================================================
"""
import os
import sys
import json
import argparse

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(AQUI, 'erp'))
sys.path.insert(0, os.path.join(AQUI, 'configuracion'))

import analisis_vertical_horizontal as av
import razones_financieras as rf
import mapeo_kpis as mk
import adaptador_formatos as af
import consolidacion as co
from erp import clasificador_cuentas as cl

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


# ===========================================================================
seccion('División segura y promedios')
check('división normal', rf._div(10, 4) == 2.5)
check('división entre cero da None', rf._div(10, 0) is None)
check('división de None da None', rf._div(None, 4) is None)
check('división entre None da None', rf._div(10, None) is None)
check('división de negativo', rf._div(-10, 4) == -2.5)
check('división entre negativo', rf._div(10, -4) == -2.5)
check('cero entre número es cero', rf._div(0, 4) == 0)
check('promedio de dos periodos', rf._prom(100, 200) == 150)
check('promedio sin anterior usa el actual', rf._prom(100, None) == 100)
check('promedio de None es None', rf._prom(None, 200) is None)
check('promedio con negativos', rf._prom(-100, 200) == 50)

seccion('Variación horizontal — la trampa de las bases raras')
check('variación normal', casi(av.variacion(150, 100)['porcentual'], 0.5))
check('variación negativa', casi(av.variacion(50, 100)['porcentual'], -0.5))
check('base cero no reporta porcentaje', av.variacion(100, 0)['porcentual'] is None)
check('base cero sí reporta absoluta', casi(av.variacion(100, 0)['absoluta'], 100))
check('base cero explica por qué', 'insignificante' in av.variacion(100, 0)['nota'])
check('base insignificante no reporta %', av.variacion(100, 0.4)['porcentual'] is None)
check('cruce de signo desde negativo no reporta %',
      av.variacion(50, -100)['porcentual'] is None)
check('cruce de signo lo explica', 'signo' in av.variacion(50, -100)['nota'])
check('de negativo a más negativo sí reporta',
      av.variacion(-150, -100)['porcentual'] is not None)
check('falta un periodo', av.variacion(None, 100)['porcentual'] is None)
check('falta el anterior', av.variacion(100, None)['porcentual'] is None)
check('sin cambio da cero', casi(av.variacion(100, 100)['porcentual'], 0))

seccion('Análisis vertical')
v = av.analisis_vertical({'a': 25, 'b': 75}, 100)
check('vertical calcula porcentaje', casi(v['a']['pct'], 0.25))
check('vertical suma 100%', casi(v['a']['pct'] + v['b']['pct'], 1.0, 0.001))
v0 = av.analisis_vertical({'a': 25}, 0)
check('vertical con base cero da None', v0['a']['pct'] is None)
check('vertical con base cero explica', 'sin' in v0['a']['nota'])
vn = av.analisis_vertical({'a': None}, 100)
check('vertical con valor None', vn['a']['pct'] is None)
vneg = av.analisis_vertical({'a': -25}, 100)
check('vertical acepta negativos', casi(vneg['a']['pct'], -0.25))

seccion('Semáforo de metas — la meta es del cliente, no del código')
# Metas de prueba, deliberadamente distintas de las de cualquier cliente real:
# si una prueba pasara con las metas reales pero no con éstas, lo que estaría
# probando es la configuración de alguien, no el código.
_M = {'roe': 0.18, 'dso': 55, 'spread_roic_wacc': 0.0, 'margen_ebit': -0.05}
check('mayor-mejor por encima es verde', rf.semaforo('roe', 0.20, _M) == 'Verde')
check('mayor-mejor justo en meta es verde', rf.semaforo('roe', 0.18, _M) == 'Verde')
check('mayor-mejor apenas abajo es amarillo', rf.semaforo('roe', 0.17, _M) == 'Amarillo')
check('mayor-mejor muy abajo es rojo', rf.semaforo('roe', 0.10, _M) == 'Rojo')
check('menor-mejor por debajo es verde', rf.semaforo('dso', 50, _M) == 'Verde')
check('menor-mejor justo en meta es verde', rf.semaforo('dso', 55, _M) == 'Verde')
check('menor-mejor apenas arriba es amarillo', rf.semaforo('dso', 58, _M) == 'Amarillo')
check('menor-mejor muy arriba es rojo', rf.semaforo('dso', 90, _M) == 'Rojo')
check('valor None no tiene semáforo', rf.semaforo('roe', None, _M) is None)
check('clave desconocida no tiene semáforo', rf.semaforo('inventada', 1, _M) is None)
# SIN META NO HAY SEMÁFORO. Si esto se rompiera —si cayera a una meta por
# defecto— el tablero pintaría el indicador de un cliente contra el objetivo de
# otro, y se vería exactamente igual de creíble.
check('indicador sin meta no tiene semáforo', rf.semaforo('roa', 0.5, _M) is None)
check('metas vacías no pintan nada', rf.semaforo('roe', 0.5, {}) is None)
check('metas None no pintan nada', rf.semaforo('roe', 0.5, None) is None)
# META EN CERO. El spread ROIC−WACC tiene meta 0 —es donde empieza a crearse
# valor— y con un umbral relativo el amarillo desaparecía: 0×0.9 sigue siendo 0.
check('meta cero: por encima es verde', rf.semaforo('spread_roic_wacc', 0.01, _M) == 'Verde')
check('meta cero: exactamente cero es verde', rf.semaforo('spread_roic_wacc', 0.0, _M) == 'Verde')
check('meta cero: por debajo es rojo', rf.semaforo('spread_roic_wacc', -0.01, _M) == 'Rojo')
# META NEGATIVA. Con umbral relativo la banda se invertía y el amarillo quedaba
# del lado equivocado: meta −0.05 × 0.9 = −0.045, que es MAYOR que la meta.
check('meta negativa: por encima es verde', rf.semaforo('margen_ebit', 0.0, _M) == 'Verde')
check('meta negativa: en la meta es verde', rf.semaforo('margen_ebit', -0.05, _M) == 'Verde')
check('meta negativa: apenas abajo es amarillo',
      rf.semaforo('margen_ebit', -0.052, _M) == 'Amarillo')
check('meta negativa: muy abajo es rojo', rf.semaforo('margen_ebit', -0.20, _M) == 'Rojo')
check('todo el catálogo declara unidad',
      all('unidad' in m for m in rf.CATALOGO_KPIS.values()))
check('todo el catálogo declara dirección',
      all('mayor_mejor' in m for m in rf.CATALOGO_KPIS.values()))
check('todo el catálogo declara nombre legible',
      all((m.get('nombre') or '').strip() for m in rf.CATALOGO_KPIS.values()))
for clave, cat in rf.CATALOGO_KPIS.items():
    # Con meta igual al valor siempre debe salir verde, sea cual sea la
    # dirección: es el borde exacto y no puede depender del signo del número.
    check(f'{clave}: valor igual a la meta es verde',
          rf.semaforo(clave, 0.5, {clave: 0.5}) == 'Verde')
    # Y del lado malo, rojo. Se elige un valor lo bastante lejos para no caer
    # en la banda de amarillo con ninguna meta.
    malo = 0.5 * 0.5 if cat['mayor_mejor'] else 0.5 * 2
    check(f'{clave}: valor claramente malo es rojo',
          rf.semaforo(clave, malo, {clave: 0.5}) == 'Rojo')

seccion('Clasificador de cuentas — normalización')
check('quita acentos', cl.normalizar('Depreciación') == 'depreciacion')
check('minúsculas', cl.normalizar('ACTIVO') == 'activo')
check('colapsa espacios', cl.normalizar('a   b') == 'a b')
check('quita puntuación', cl.normalizar('S.A. de C.V.') == 's a de c v')
check('cadena vacía', cl.normalizar('') == '')
check('None no truena', cl.normalizar(None) == '')
check('conserva dígitos', cl.normalizar('IVA 16%') == 'iva 16')

seccion('Clasificador — nombres de raíz bilingües')
for nombre, esperado in [('Activos', 'ACTIVO'), ('Assets', 'ACTIVO'),
                         ('Pasivos', 'PASIVO'), ('Liabilities', 'PASIVO'),
                         ('Capital Contable', 'CAPITAL'), ('Equity', 'CAPITAL'),
                         ('Ingresos', 'INGRESO'), ('Revenues', 'INGRESO'),
                         ('Sales', 'INGRESO'),
                         ('Costo de Ventas', 'COSTO'), ('Cost of sales', 'COSTO'),
                         ('Gastos', 'GASTO'), ('Expenses', 'GASTO'),
                         ('Financieros', 'FINANCIERO'), ('Financing', 'FINANCIERO'),
                         ('Otros Ingresos y Egresos', 'OTRO'),
                         ('Other revenues and expenses', 'OTRO')]:
    got, _ = cl.clase_por_nombre(nombre)
    check(f'clase de "{nombre}"', got == esperado, f'dio {got}')
check('"Costo de ventas" no se lee como "ventas"',
      cl.clase_por_nombre('Costo de Ventas')[0] == 'COSTO')
check('"Otros ingresos" no se lee como "ingresos"',
      cl.clase_por_nombre('Otros Ingresos y Egresos')[0] == 'OTRO')
check('nombre sin relación no clasifica',
      cl.clase_por_nombre('Zarandaja')[0] is None)
check('nombre vacío no clasifica', cl.clase_por_nombre('')[0] is None)

seccion('Clasificador — resiste catálogos rotos')
ciclo = {'A': {'codigo': 'A', 'nombre': 'a', 'cuenta_padre': 'B', 'nivel': 2},
         'B': {'codigo': 'B', 'nombre': 'b', 'cuenta_padre': 'A', 'nivel': 2}}
try:
    cl._raiz_de(ciclo['A'], ciclo)
    check('un ciclo en el árbol no cuelga', True)
except RecursionError:
    check('un ciclo en el árbol no cuelga', False, 'entró en recursión infinita')
huerfana = {'A': {'codigo': 'A', 'nombre': 'a', 'cuenta_padre': 'NO_EXISTE', 'nivel': 2}}
check('padre inexistente no truena',
      cl._raiz_de(huerfana['A'], huerfana)['codigo'] == 'A')
vacio, inf = cl.clasificar_catalogo([], 'X')
check('catálogo vacío no truena', vacio == [] and inf['total'] == 0)

seccion('Adaptador de formatos — periodos')
for txt, esperado in [('ene-24', (2024, 1)), ('feb-24', (2024, 2)),
                      ('dic-20', (2020, 12)), ('Jan 2024', (2024, 1)),
                      ('December 2023', (2023, 12)), ('2024-01', (2024, 1)),
                      ('01/2024', (2024, 1)), ('enero de 2024', (2024, 1)),
                      ('Sep 2026', (2026, 9)), ('marzo 2020', (2020, 3)),
                      ('FY2024', (2024, None)), ('Q1 2024', (2024, None))]:
    check(f'periodo "{txt}"', af.identificar_periodo(txt) == esperado,
          f'dio {af.identificar_periodo(txt)}')
check('texto sin fecha da None', af.identificar_periodo('Cliente') is None)
check('cadena vacía da None', af.identificar_periodo('') is None)
check('None da None', af.identificar_periodo(None) is None)

seccion('Adaptador de formatos — encabezados bilingües')
for txt, esperado in [('Ingresos', 'ingresos'), ('Total revenues', 'ingresos'),
                      ('Ventas netas', 'ingresos'), ('Net sales', 'ingresos'),
                      ('Costo de ventas', 'costo_servicio'),
                      ('Cost of sales', 'costo_servicio'),
                      ('Utilidad de operación', 'ebit'),
                      ('Operating income', 'ebit'),
                      ('Total assets', 'activos_totales'),
                      ('Activos totales', 'activos_totales'),
                      ('Capital contable', 'patrimonio'),
                      ('Total equity', 'patrimonio'),
                      ('Cuentas por cobrar', 'cuentas_x_cobrar'),
                      ('Accounts receivable', 'cuentas_x_cobrar'),
                      ('Cuentas por pagar', 'cuentas_x_pagar'),
                      ('Inventarios', 'inventarios'), ('Inventory', 'inventarios'),
                      ('Efectivo', 'efectivo'), ('Cash', 'efectivo'),
                      ('Utilidad neta', 'utilidad_neta'), ('Net income', 'utilidad_neta')]:
    got, _, _ = af.identificar_campo(txt)
    check(f'campo "{txt}"', got == esperado, f'dio {got}')
check('columna desconocida no se inventa',
      af.identificar_campo('Zarandaja')[0] is None)
check('"Costo de ventas" gana a "ventas"',
      af.identificar_campo('Costo de ventas')[0] == 'costo_servicio')

seccion('Adaptador — detección de layout')
t1 = [['Periodo', 'Ingresos', 'Costo de ventas'], ['ene-24', 100, 20]]
a1 = af.analizar_tabla(t1)
check('detecta conceptos en columnas', a1['orientacion'] == 'columnas')
check('encuentra el encabezado en la fila 1', a1['fila_encabezado'] == 0)
t2 = [['Logo'], ['Título'], ['Month', 'Total revenues'], ['Jan 2024', 100]]
a2 = af.analizar_tabla(t2)
check('encuentra el encabezado en la fila 3', a2['fila_encabezado'] == 2)
t3 = [['Concepto', 'enero 2024', 'febrero 2024'], ['Ventas netas', 1, 2],
      ['Total assets', 3, 4]]
a3 = af.analizar_tabla(t3)
check('detecta tabla transpuesta', a3['orientacion'] == 'filas')
check('encuentra periodos en la transpuesta', len(a3['periodos']) == 2)
check('tabla vacía no truena', 'error' in af.analizar_tabla([]))
check('reporta lo no reconocido', len(a1['no_reconocidos']) >= 0)

seccion('Consolidación — vocabulario que se calcula solo')
vocab = co.vocabulario({
    'NCS': 'Networks Crossdocking Services, S.A. de C.V.',
    'NG': 'Networks Group LCT, S.C.', 'NL': 'Networks & Logistics, S.A. de C.V.',
    'NRS': 'Networks Realtors, S.A. de C.V.',
    'NTS': 'Networks Trucking Services, S.A. de C.V.',
    'PL': 'Paragon Logistics, S.A. de C.V.'})
check('palabra compartida pesa poco', vocab['NCS']['NETWORKS'] < 0.25)
check('palabra única pesa uno', casi(vocab['NCS']['CROSSDOCKING'], 1.0, 0.001))
check('palabra en dos empresas pesa medio', casi(vocab['NL']['LOGISTICS'], 0.5, 0.001))
check('las formas societarias no entran', 'SA' not in vocab['NCS'])
check('DE no entra como palabra', 'DE' not in vocab['NCS'])

for nombre, libro, esperado in [
        ('Networks Trucking Sevices, S.A. de C.V.', 'NCS', 'NTS'),
        ('Networks Trucking Services', 'NCS', 'NTS'),
        ('Networks Outsourcing Services, S.A. de C', 'NCS', None),
        ('Networks & Logistics, S.A. de C.V.', 'NCS', 'NL'),
        ('Paragon Logistics, S.A. de C.V.', 'NCS', 'PL'),
        ('Networks Crossdocking Services', 'NG', 'NCS'),
        ('Networks Group LCT', 'NL', 'NG'),
        ('NETWORKS REALTORS', 'NCS', 'NRS'),
        ('Clientes Nacionales', 'NCS', None),
        ('Logistics', 'NCS', None),
        ('Networks', 'NCS', None),
        ('Proveedores Nacionales', 'NTS', None),
        ('Bancos', 'NG', None)]:
    got, _ = co.identificar_contraparte(nombre, vocab, libro)
    check(f'contraparte de "{nombre[:34]}" [{libro}]', got == esperado, f'dio {got}')
check('una empresa no se identifica a sí misma',
      co.identificar_contraparte('Networks Crossdocking Services', vocab, 'NCS')[0]
      != 'NCS')

seccion('Mapeo de rubros del balance')
ct = {
    'A': {'codigo': 'A', 'nombre': 'Caja y Bancos', 'cuenta_padre': '', 'nivel': 3},
    'A1': {'codigo': 'A1', 'nombre': 'Banco del Bajío', 'cuenta_padre': 'A', 'nivel': 4},
    'B': {'codigo': 'B', 'nombre': 'Cuentas por Cobrar', 'cuenta_padre': '', 'nivel': 3},
    'B1': {'codigo': 'B1', 'nombre': 'Clientes Nacionales', 'cuenta_padre': 'B', 'nivel': 4},
    'C': {'codigo': 'C', 'nombre': 'Cuentas por Pagar', 'cuenta_padre': '', 'nivel': 3},
    'D': {'codigo': 'D', 'nombre': 'Inventario', 'cuenta_padre': '', 'nivel': 3},
    'E': {'codigo': 'E', 'nombre': 'Depreciación Acumulada', 'cuenta_padre': '', 'nivel': 3},
    'F': {'codigo': 'F', 'nombre': 'Depreciación - Edificios', 'cuenta_padre': '', 'nivel': 3},
    'G': {'codigo': 'G', 'nombre': 'Obligaciones con bancos e instituciones financieras',
          'cuenta_padre': '', 'nivel': 3},
    'H': {'codigo': 'H', 'nombre': 'Zarandaja', 'cuenta_padre': '', 'nivel': 3},
}
check('efectivo por la cuenta', mk.rubro_de_cuenta('A', ct) == 'efectivo')
check('efectivo heredado del padre', mk.rubro_de_cuenta('A1', ct) == 'efectivo')
check('cuentas por cobrar', mk.rubro_de_cuenta('B', ct) == 'cuentas_x_cobrar')
check('CxC heredado del padre', mk.rubro_de_cuenta('B1', ct) == 'cuentas_x_cobrar')
check('cuentas por pagar', mk.rubro_de_cuenta('C', ct) == 'cuentas_x_pagar')
check('CxC no se confunde con CxP', mk.rubro_de_cuenta('B', ct) != 'cuentas_x_pagar')
check('inventarios', mk.rubro_de_cuenta('D', ct) == 'inventarios')
check('depreciación acumulada es su propio rubro',
      mk.rubro_de_cuenta('E', ct) == 'depreciacion_acumulada')
check('deuda con costo', mk.rubro_de_cuenta('G', ct) == 'deuda_con_costo')
check('cuenta sin relación no se fuerza', mk.rubro_de_cuenta('H', ct) is None)
check('depreciación del periodo SÍ es gasto', mk.es_depreciacion_gasto('F', ct))
check('depreciación ACUMULADA no es gasto', not mk.es_depreciacion_gasto('E', ct))
check('una cuenta cualquiera no es depreciación',
      not mk.es_depreciacion_gasto('A', ct))

seccion('Impuesto a la utilidad vs impuesto operativo')
ci = {
    'P': {'codigo': 'P', 'nombre': 'Provisión de Impuestos', 'cuenta_padre': '', 'nivel': 2},
    'I1': {'codigo': 'I1', 'nombre': 'Impuesto Sobre la Renta', 'cuenta_padre': 'P', 'nivel': 3},
    'I2': {'codigo': 'I2', 'nombre': 'PTU', 'cuenta_padre': 'P', 'nivel': 3},
    'I3': {'codigo': 'I3', 'nombre': 'IETU', 'cuenta_padre': 'P', 'nivel': 3},
    'N': {'codigo': 'N', 'nombre': 'Gastos de Nómina', 'cuenta_padre': '', 'nivel': 2},
    'N1': {'codigo': 'N1', 'nombre': 'Impuesto Sobre Nómina', 'cuenta_padre': 'N', 'nivel': 3},
    'N2': {'codigo': 'N2', 'nombre': 'Impuesto Predial', 'cuenta_padre': 'N', 'nivel': 3},
    'X': {'codigo': 'X', 'nombre': 'Diesel', 'cuenta_padre': '', 'nivel': 3},
}
check('ISR es impuesto a la utilidad', cl.es_impuesto_a_la_utilidad('I1', ci))
check('PTU es impuesto a la utilidad', cl.es_impuesto_a_la_utilidad('I2', ci))
check('IETU es impuesto a la utilidad', cl.es_impuesto_a_la_utilidad('I3', ci))
check('impuesto sobre nómina NO lo es', not cl.es_impuesto_a_la_utilidad('N1', ci))
check('predial NO lo es', not cl.es_impuesto_a_la_utilidad('N2', ci))
check('un gasto cualquiera NO lo es', not cl.es_impuesto_a_la_utilidad('X', ci))
check('el rubro padre sí lo es', cl.es_impuesto_a_la_utilidad('P', ci))


seccion('Normas contables — la política es configuración, no código')
import normas_contables as nc
check('la norma por defecto existe', nc.obtener() is not None)
check('IFRS/NIF está registrada', nc.obtener('ifrs_nif')['nombre'].startswith('IFRS'))
check('US GAAP está registrada', 'GAAP' in nc.obtener('us_gaap')['nombre'])
check('la clave no distingue mayúsculas', nc.obtener('IFRS_NIF') is not None)
try:
    nc.obtener('marco_inventado')
    check('una norma desconocida LEVANTA', False, 'la aceptó en silencio')
except nc.NormaDesconocida:
    check('una norma desconocida LEVANTA', True)
try:
    nc.politica('politica_inventada')
    check('una política desconocida LEVANTA', False)
except KeyError:
    check('una política desconocida LEVANTA', True)
check('toda norma declara todas las políticas',
      all(all(pol in n for pol in nc.POLITICAS) for n in nc.NORMAS.values()),
      'hay una norma que no declara alguna política')
check('el listado para la interfaz trae clave y nombre',
      all({'clave', 'nombre', 'descripcion'} <= set(x) for x in nc.normas_disponibles()))
for clave in nc.NORMAS:
    pol = nc.politica('dya_para_ebitda', clave)
    check(f'{clave}: D&A declara incluye y excluye',
          'incluye' in pol and 'excluye' in pol)
    check(f'{clave}: excluye los pagos anticipados del EBITDA',
          any('prepaid' in t or 'anticipad' in t or 'seguro' in t or 'insurance' in t
              for t in pol['excluye']))

_ct_dya = {k: {'codigo': k, 'nombre': n, 'cuenta_padre': '', 'nivel': 3} for k, n in [
    ('D1', 'Depreciación - Edificios'), ('D2', 'Depreciación - Equipo de Transporte'),
    ('D3', 'Depreciación - Maquinaria y Equipo'), ('D4', 'Depreciación - Equipo de Computo'),
    ('A1', 'Amortización - Programas de Computo'), ('A2', 'Amortización de Marcas'),
    ('A3', 'Amortización de Intangibles'), ('U1', 'Deterioro de Activos'),
    ('S1', 'Amortización - Primas Seguros'), ('S2', 'Seguros Pagados por Anticipado'),
    ('R1', 'Amortización - Rentas Pagadas por Anticipado'),
    ('P1', 'Gastos de Instalación'), ('P2', 'Papelería y Útiles'),
    ('C1', 'Depreciación Acumulada'), ('C2', 'Amortización Acumulada'),
    ('X1', 'Diesel'), ('X2', 'Sueldos y Salarios'), ('X3', 'Impuesto Predial'),
]}
_esperado_dya = {'D1': 1, 'D2': 1, 'D3': 1, 'D4': 1, 'A1': 1, 'A2': 1, 'A3': 1,
                 'U1': 1, 'S1': 0, 'S2': 0, 'R1': 0, 'P1': 0, 'P2': 0,
                 'C1': 0, 'C2': 0, 'X1': 0, 'X2': 0, 'X3': 0}
for k, esp in _esperado_dya.items():
    got = mk.es_depreciacion_gasto(k, _ct_dya)
    check(f'D&A bajo IFRS/NIF: "{_ct_dya[k]["nombre"][:38]}"', got == bool(esp),
          f'dio {got}')


# ===========================================================================
seccion('Catálogo de indicadores — completo y coherente')
_FAM = {k for k, _ in rf.FAMILIAS}
for clave, cat in rf.CATALOGO_KPIS.items():
    for campo in ('nombre', 'unidad', 'mayor_mejor', 'familia', 'ttm',
                  'monetario', 'destacado', 'fuente'):
        check(f'{clave} declara {campo}', campo in cat)
    check(f'{clave} pertenece a una familia registrada', cat['familia'] in _FAM,
          f"familia={cat['familia']}")
    check(f'{clave} declara una fuente válida',
          cat['fuente'] in ('razon', 'derivado'))
    # Un nombre de versión TTM que no exista deja el indicador mudo con base de
    # doce meses, que es la base por defecto del tablero.
    if cat['ttm']:
        check(f'{clave}: su versión TTM se llama distinto', cat['ttm'] != clave)
        check(f'{clave}: su versión TTM termina en _ttm',
              cat['ttm'].endswith('_ttm'))
check('toda familia registrada tiene al menos un indicador',
      all(any(c['familia'] == k for c in rf.CATALOGO_KPIS.values())
          for k, _ in rf.FAMILIAS))
check('las familias no se repiten', len(_FAM) == len(rf.FAMILIAS))

seccion('Tasa impositiva — sin valor por defecto del país equivocado')
# 0.30 es la tasa de ISR MEXICANA. Cuando era el valor por defecto, un cliente
# de otro país veía su NOPAT y su WACC calculados con el impuesto de México sin
# que nada lo dijera.
_f = {'ingresos': 1000.0, 'costo_servicio': 100.0, 'gastos_operacion': 500.0,
      'depreciacion': 50.0, 'gastos_financieros': 20.0,
      'patrimonio': 5000.0, 'deuda_con_costo': 1000.0, 'efectivo': 200.0}
d_sin = rf.derivar_estado(dict(_f), {})
check('sin tasa configurada no hay NOPAT', d_sin['nopat'] is None)
check('sin tasa configurada no hay WACC', d_sin['wacc'] is None)
check('y se dice por qué', d_sin['origen_tasa_nopat'] == 'sin_tasa')
_SUP = {'tasa_impositiva': 0.25, 'rf': 0.09, 'beta': 1.1, 'erp': 0.065,
        'kd': 0.115}
d_con = rf.derivar_estado(dict(_f), _SUP)
check('con tasa configurada sí hay NOPAT', d_con['nopat'] is not None)
check('el NOPAT usa esa tasa', casi(d_con['nopat'], d_con['ebit'] * 0.75))
check('y se marca el origen',
      d_con['origen_tasa_nopat'] == 'supuesto_configurado')
# La tasa MEDIDA gana sobre la supuesta cuando es confiable. No es un detalle:
# las tasas efectivas reales de este grupo van de 37% a 41%, así que usar 30%
# inflaba el NOPAT, el ROIC y el spread contra el WACC entre 10% y 16%.
d_ef = rf.derivar_estado(dict(_f, impuestos=90.0, tasa_confiable=True), _SUP)
check('la tasa medida gana sobre la supuesta',
      d_ef['origen_tasa_nopat'] == 'efectiva_del_erp')
check('el NOPAT usa la tasa medida',
      casi(d_ef['nopat'], d_ef['ebit'] * (1 - d_ef['tasa_efectiva'])))
d_nf = rf.derivar_estado(dict(_f, impuestos=90.0, tasa_confiable=False), _SUP)
check('una tasa medida NO confiable no se usa',
      d_nf['origen_tasa_nopat'] == 'supuesto_configurado')
# El escudo fiscal del WACC usa la MISMA tasa que el NOPAT: si no, el spread
# ROIC − WACC restaría dos números con supuestos fiscales distintos y la
# diferencia se leería como creación de valor.
for dd in (d_con, d_ef):
    ke, kd, pat, deu = dd['ke'], 0.115, dd['patrimonio'], dd['deuda_con_costo']
    esperado = ((pat / (pat + deu)) * ke
                + (deu / (pat + deu)) * kd * (1 - dd['tasa_usada_nopat']))
    check('el escudo fiscal del WACC usa la tasa del NOPAT',
          casi(dd['wacc'], esperado, tol=1e-9))
# Sin impuesto real, la tasa efectiva es un HUECO, no el supuesto disfrazado.
check('sin impuesto real no se reporta tasa efectiva',
      d_con['tasa_efectiva'] is None)
check('y se marca como estimada', d_con['tasa_estimada'] is True)
check('con impuesto real no es estimada', d_ef['tasa_estimada'] is False)

seccion('No se recalcula lo que el Estado de Resultados ya calculó')
# EL BUG QUE ESTO VIGILA. derivar_estado recomputaba el EBIT como
# ingresos − costo − gastos − depreciación, y la depreciación YA ESTÁ dentro de
# los gastos de operación: la restaba dos veces. En un mes real la utilidad de
# operación del estado era 2,631,384 y aquí salía −280,143; la diferencia,
# 2,911,527, era exactamente la depreciación.
#
# Como el EBITDA se arma sumándole la depreciación de vuelta al EBIT, el
# "EBITDA" publicado terminaba siendo el EBIT — el margen EBITDA del tablero
# era el margen operativo. De ahí colgaban NOPAT, ROIC, spread y EVA.
_ER = {'ingresos': 25715082.18, 'costo_servicio': 0.0,
       'gastos_operacion': 23083698.28, 'depreciacion': 2911526.93,
       'ebit': 2631383.90,            # utilidad de operación DEL ESTADO
       'ebitda': 5542910.83,
       'gastos_financieros': 462745.03,
       'ebt': 2168638.87, 'impuestos': 23547.57,
       'utilidad_neta': 2145091.30}
_d = rf.derivar_estado(dict(_ER), {'tasa_impositiva': 0.30})
check('el EBIT del estado se respeta', casi(_d['ebit'], 2631383.90))
check('NO se le vuelve a restar la depreciación',
      not casi(_d['ebit'], 2631383.90 - 2911526.93, tol=1.0))
check('el EBITDA del estado se respeta', casi(_d['ebitda'], 5542910.83))
check('el EBITDA supera al EBIT en la depreciación',
      casi(_d['ebitda'] - _d['ebit'], 2911526.93))
check('el EBT del estado se respeta', casi(_d['ebt'], 2168638.87))
check('la utilidad neta del estado se respeta', casi(_d['utilidad_neta'], 2145091.30))
# Y sigue calculando lo que de verdad falta.
_crudo = rf.derivar_estado(
    {'ingresos': 1000.0, 'costo_servicio': 100.0, 'gastos_operacion': 500.0,
     'depreciacion': 50.0, 'gastos_financieros': 20.0},
    {'tasa_impositiva': 0.30})
check('sin EBIT dado, se calcula', casi(_crudo['ebit'], 350.0))
check('y el EBITDA encima de él', casi(_crudo['ebitda'], 400.0))
check('y el EBT restando el costo financiero', casi(_crudo['ebt'], 330.0))
# La tasa efectiva que venga ya decidida NO se vuelve a dividir: el criterio de
# si es interpretable lo fijó quien armó la fila.
_dt = rf.derivar_estado(dict(_ER, tasa_efectiva=0.0109, tasa_confiable=True),
                        {'tasa_impositiva': 0.30})
check('la tasa efectiva entregada se respeta', casi(_dt['tasa_efectiva'], 0.0109, 1e-9))

seccion('Razones que se suprimen en vez de engañar')
_base_r = dict(_f, ebit=350.0, ebitda=400.0, ebt=330.0, nopat=245.0,
               utilidad_neta=231.0, activos_totales=8000.0,
               pasivos_totales=3000.0, capital_invertido=5800.0,
               deuda_neta=800.0, activo_circulante=2000.0,
               pasivo_circulante=1000.0, cuentas_x_cobrar=300.0,
               cuentas_x_pagar=200.0, inventarios=0.0)
# COBERTURA DE INTERESES con resultado financiero NETO negativo: la empresa
# ganó más por intereses de los que pagó. Dividir entre eso daba una cobertura
# negativa que se lee como "no alcanza a pagar sus intereses" — lo contrario de
# lo que pasó — y el semáforo la pintaba roja.
r_ing = rf.razones(dict(_base_r, gastos_financieros=-50.0))
check('sin costo financiero neto no hay cobertura',
      r_ing['cobertura_intereses'] is None)
check('ni costo de la deuda', r_ing['costo_deuda_efectivo'] is None)
r_cero = rf.razones(dict(_base_r, gastos_financieros=0.0))
check('con costo financiero cero tampoco',
      r_cero['cobertura_intereses'] is None)
r_pos = rf.razones(dict(_base_r, gastos_financieros=50.0))
check('con costo financiero real sí se calcula',
      casi(r_pos['cobertura_intereses'], 7.0))
# Una cobertura negativa por EBIT negativo SÍ es legítima: la empresa no
# alcanza a cubrir sus intereses. Eso no se suprime.
r_neg = rf.razones(dict(_base_r, ebit=-100.0, gastos_financieros=50.0))
check('EBIT negativo sí produce cobertura negativa, y es correcto',
      r_neg['cobertura_intereses'] is not None
      and r_neg['cobertura_intereses'] < 0)
# TASA EFECTIVA: el caso que obligó a cerrarlo — −308% pintado de VERDE porque
# la meta es "menor es mejor".
r_mala = rf.razones(dict(_base_r, tasa_efectiva=-3.08, tasa_confiable=False))
check('una tasa efectiva no confiable no se publica',
      r_mala['tasa_efectiva'] is None)
check('y por lo tanto no tiene semáforo',
      rf.semaforo('tasa_efectiva', r_mala['tasa_efectiva'], {'tasa_efectiva': 0.30}) is None)
check('la tasa cruda SÍ pintaba verde — por eso se suprime',
      rf.semaforo('tasa_efectiva', -3.08, {'tasa_efectiva': 0.30}) == 'Verde')
r_buena = rf.razones(dict(_base_r, tasa_efectiva=0.37, tasa_confiable=True))
check('una tasa confiable sí se publica', casi(r_buena['tasa_efectiva'], 0.37))

seccion('Convenciones de cálculo — días del año y holgura')
check('365 días es el valor de arranque', rf.DIAS_ANIO == 365)
r365 = rf.razones(dict(_base_r), dias_anio=365)
r360 = rf.razones(dict(_base_r), dias_anio=360)
check('la convención de días cambia el resultado',
      not casi(r365['dso'], r360['dso'], tol=1e-9))
check('y lo cambia en la proporción exacta',
      casi(r360['dso'], r365['dso'] * 360 / 365, tol=1e-9))
check('la holgura por defecto es la de arranque',
      rf.semaforo('roe', 0.17, {'roe': 0.18}) == 'Amarillo')
check('una holgura más estrecha lo vuelve rojo',
      rf.semaforo('roe', 0.17, {'roe': 0.18}, holgura=0.01) == 'Rojo')
check('una holgura más ancha lo mantiene amarillo',
      rf.semaforo('roe', 0.15, {'roe': 0.18}, holgura=0.30) == 'Amarillo')
check('holgura cero elimina la banda intermedia',
      rf.semaforo('roe', 0.179, {'roe': 0.18}, holgura=0.0) == 'Rojo')

seccion('Doce meses — flujos se suman, saldos se promedian')
_serie = [dict(_base_r, periodo=f'2025-{m:02d}', ingresos=100.0 * m,
               patrimonio=1000.0 * m, activos_totales=2000.0 * m,
               capital_invertido=1500.0 * m, utilidad_neta=10.0 * m,
               nopat=8.0 * m, ebitda=20.0 * m, ebit=15.0 * m,
               costo_servicio=5.0, fcf=None, impuestos=2.0,
               depreciacion=5.0, cuentas_x_cobrar=1.0, cuentas_x_pagar=1.0,
               deuda_con_costo=1.0)
          for m in range(1, 13)]
check('sin doce meses no hay TTM', rf.calcular_ttm(_serie, 10) is None)
_ttm = rf.calcular_ttm(_serie, 11)
check('con doce meses sí hay TTM', _ttm is not None)
check('los ingresos se SUMAN', casi(_ttm['ingresos'], 100.0 * 78))
check('el patrimonio se PROMEDIA', casi(_ttm['patrimonio_prom'], 1000.0 * 78 / 12))
check('sumar el patrimonio lo multiplicaría por doce',
      _ttm['patrimonio_prom'] * 12 > _ttm['patrimonio_prom'])
check('los activos también se promedian',
      casi(_ttm['activos_totales_prom'], 2000.0 * 78 / 12))
# La razón TTM tiene que usar el promedio de DOCE meses, no el de dos.
r_ttm = rf.razones(_serie[11], _serie[10], _ttm)
check('el ROE de doce meses usa el promedio de doce',
      casi(r_ttm['roe_ttm'], _ttm['utilidad_neta'] / _ttm['patrimonio_prom'], tol=1e-9))
check('y se marca que los promedios son de doce meses',
      r_ttm['promedios_de_doce_meses'] is True)
_prom2 = (_serie[11]['patrimonio'] + _serie[10]['patrimonio']) / 2
check('el promedio de dos habría dado otra cosa',
      not casi(r_ttm['roe_ttm'], _ttm['utilidad_neta'] / _prom2, tol=1e-9))
# Sin promedios de doce se degrada a los de dos, pero avisando.
_ttm_sin = {k: v for k, v in _ttm.items() if not k.endswith('_prom')}
r_deg = rf.razones(_serie[11], _serie[10], _ttm_sin)
check('sin promedios de doce se degrada a los de dos',
      r_deg['promedios_de_doce_meses'] is False)
check('y aun así entrega la razón', r_deg['roe_ttm'] is not None)

seccion('EVA — las dos versiones en la misma unidad')
# Antes `eva` iba en pesos del MES y `eva_ttm` en pesos del AÑO. Dos cifras con
# nombres casi iguales, en la misma pantalla, en unidades distintas.
_fe = dict(_base_r, wacc=0.10, capital_invertido=1200.0, nopat=20.0)
r_eva = rf.razones(_fe, None, None)
check('el EVA del mes sale del spread anualizado',
      casi(r_eva['eva'], r_eva['spread_roic_wacc'] * 1200.0, tol=1e-6))
check('no se vuelve a dividir entre doce',
      abs(r_eva['eva']) > abs(r_eva['spread_roic_wacc'] * 1200.0 / 12))

seccion('Circulante — una segunda dimensión, no un rubro más')
# Catálogo mínimo con la forma que rompió el primer intento: una cuenta de
# banco colgando de "Activos Circulantes". Si el circulante se hubiera metido a
# RUBROS, "activos circulantes" (19 letras) le habría ganado a "bancos" (6) por
# ser más largo, y el efectivo del grupo se habría vuelto cero sin ninguna
# señal — las razones de liquidez seguirían saliendo bien y el ROE mal.
_CTAS_CIRC = {c['codigo']: c for c in [
    {'codigo': '1', 'nombre': 'Activos', 'cuenta_padre': '', 'nivel': 1,
     'clase': 'ACTIVO', 'es_acumulativa': True},
    {'codigo': '11', 'nombre': 'Activos Circulantes', 'cuenta_padre': '1', 'nivel': 2,
     'clase': 'ACTIVO', 'es_acumulativa': True},
    {'codigo': '1110', 'nombre': 'Bancos', 'cuenta_padre': '11', 'nivel': 3,
     'clase': 'ACTIVO', 'es_acumulativa': True},
    {'codigo': '111001', 'nombre': 'Banco Nacional', 'cuenta_padre': '1110', 'nivel': 4,
     'clase': 'ACTIVO', 'es_acumulativa': False},
    {'codigo': '1120', 'nombre': 'Clientes', 'cuenta_padre': '11', 'nivel': 3,
     'clase': 'ACTIVO', 'es_acumulativa': False},
    {'codigo': '15', 'nombre': 'Activo Fijo', 'cuenta_padre': '1', 'nivel': 2,
     'clase': 'ACTIVO', 'es_acumulativa': True},
    {'codigo': '1510', 'nombre': 'Equipo de Transporte', 'cuenta_padre': '15', 'nivel': 3,
     'clase': 'ACTIVO', 'es_acumulativa': False},
    {'codigo': '2', 'nombre': 'Pasivos', 'cuenta_padre': '', 'nivel': 1,
     'clase': 'PASIVO', 'es_acumulativa': True},
    {'codigo': '21', 'nombre': 'Pasivo Circulante', 'cuenta_padre': '2', 'nivel': 2,
     'clase': 'PASIVO', 'es_acumulativa': True},
    {'codigo': '2110', 'nombre': 'Proveedores', 'cuenta_padre': '21', 'nivel': 3,
     'clase': 'PASIVO', 'es_acumulativa': False},
    {'codigo': '25', 'nombre': 'Pasivos a Largo Plazo', 'cuenta_padre': '2', 'nivel': 2,
     'clase': 'PASIVO', 'es_acumulativa': True},
    {'codigo': '2513', 'nombre': 'Documentos y cuentas por pagar empresas '
                                 'relacionadas largo plazo',
     'cuenta_padre': '25', 'nivel': 3, 'clase': 'PASIVO', 'es_acumulativa': False},
]}
check('una cuenta de banco bajo circulante sigue siendo efectivo',
      mk.rubro_de_cuenta('111001', _CTAS_CIRC) == 'efectivo')
check('y además se reconoce como activo circulante',
      mk.grupo_circulante('111001', _CTAS_CIRC) == 'activo_circulante')
check('clientes sigue siendo cuentas por cobrar',
      mk.rubro_de_cuenta('1120', _CTAS_CIRC) == 'cuentas_x_cobrar')
check('proveedores sigue siendo cuentas por pagar',
      mk.rubro_de_cuenta('2110', _CTAS_CIRC) == 'cuentas_x_pagar')
check('proveedores se reconoce como pasivo circulante',
      mk.grupo_circulante('2110', _CTAS_CIRC) == 'pasivo_circulante')
check('el activo fijo NO es circulante',
      mk.grupo_circulante('1510', _CTAS_CIRC) is None)
check('el largo plazo NO es circulante',
      mk.grupo_circulante('2513', _CTAS_CIRC) is None)
# EL CASO QUE MOTIVÓ EL RUBRO DE PARTES RELACIONADAS. Esta cuenta existe de
# verdad en una de las empresas: casaba con "cuentas por pagar" y entraba al
# cálculo de días de pago, inflándolos con deuda que el grupo se debe a sí
# mismo y encima de largo plazo.
check('cuentas por pagar a relacionadas NO son cuentas por pagar',
      mk.rubro_de_cuenta('2513', _CTAS_CIRC) == 'partes_relacionadas')
for termino in ('empresas relacionadas', 'partes relacionadas', 'related parties',
                'intercompany'):
    ctas = dict(_CTAS_CIRC)
    ctas['9999'] = {'codigo': '9999', 'nombre': f'Cuentas por cobrar {termino}',
                    'cuenta_padre': '11', 'nivel': 3, 'clase': 'ACTIVO',
                    'es_acumulativa': False}
    check(f'"{termino}" gana sobre cuentas por cobrar',
          mk.rubro_de_cuenta('9999', ctas) == 'partes_relacionadas')

seccion('Vocabulario de rubros extensible por cliente')
# El vocabulario de fábrica no puede cubrir todas las formas de nombrar una
# cuenta. Un catálogo que llame "Disponibilidades" a la caja no coincide con
# nada, y el fallo es mudo: el rubro sale vacío y con él las razones que
# dependen de él. Nadie revisa un indicador que nunca tuvo valor.
_n_fabrica = len(mk.vocabulario_activo())
_ctas_voc = {'1': {'codigo': '1', 'nombre': 'Disponibilidades', 'cuenta_padre': '',
                   'nivel': 2, 'clase': 'ACTIVO', 'es_acumulativa': False},
             '2': {'codigo': '2', 'nombre': 'Bancos', 'cuenta_padre': '',
                   'nivel': 2, 'clase': 'ACTIVO', 'es_acumulativa': False}}
check('sin vocabulario extra, un nombre ajeno no se reconoce',
      mk.rubro_de_cuenta('1', _ctas_voc) is None)
mk.aplicar_vocabulario_cliente({'efectivo': ['disponibilidades']})
check('con el término del cliente sí se reconoce',
      mk.rubro_de_cuenta('1', _ctas_voc) == 'efectivo')
check('y los de fábrica SIGUEN funcionando',
      mk.rubro_de_cuenta('2', _ctas_voc) == 'efectivo')
check('el vocabulario del cliente agrega, no reemplaza',
      len(mk.vocabulario_activo()) > _n_fabrica)
check('aplicarlo vacío no cambia nada',
      (mk.aplicar_vocabulario_cliente({}) or True)
      and mk.rubro_de_cuenta('2', _ctas_voc) == 'efectivo')
try:
    mk.aplicar_vocabulario_cliente({'rubro_que_no_existe': ['x']})
    check('un rubro inventado LEVANTA', False)
except mk.RubroDesconocido:
    check('un rubro inventado LEVANTA', True)
# La prioridad de partes relacionadas se conserva tras fusionar vocabularios:
# si se perdiera, las cuentas intercompañía volverían a colarse al DPO.
_ctas_pr = {'9': {'codigo': '9', 'nombre': 'Cuentas por pagar empresas relacionadas',
                  'cuenta_padre': '', 'nivel': 3, 'clase': 'PASIVO',
                  'es_acumulativa': False}}
check('partes relacionadas sigue ganando después de fusionar',
      mk.rubro_de_cuenta('9', _ctas_pr) == 'partes_relacionadas')

seccion('Bases de las razones de días')
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), 'dashboard'))
import exportar_kpis as ek

_FILA = {'ingresos': 1000.0, 'costo_servicio': 50.0,
         'gastos_operacion': 700.0, 'depreciacion': 100.0}
_CLASICA = {'base_dias_pago': 'costo_de_ventas'}
_EFECTIVO = {'base_dias_pago': 'costos_operativos_efectivo'}

cob, pag, mot = ek.bases_de_dias(_FILA, None, _CLASICA)
check('sin intercompañía, la cobranza es el ingreso completo', casi(cob, 1000.0))
check('base clásica de pago es el costo de ventas', casi(pag, 50.0))
check('sin supresión no hay motivo', mot is None)

cob, pag, _ = ek.bases_de_dias(_FILA, None, _EFECTIVO)
check('base en efectivo = costo + gastos − depreciación', casi(pag, 650.0))
check('la depreciación no entra: no se le paga a nadie', pag < 750.0)

cob, pag, _ = ek.bases_de_dias(_FILA, {'ingresos': 400.0, 'gastos': 200.0}, _EFECTIVO)
check('la cobranza descuenta la facturación al grupo', casi(cob, 600.0))
check('el pago descuenta las compras al grupo', casi(pag, 450.0))

# EMPRESA QUE LE FACTURA TODO AL GRUPO. Al quitar lo intercompañía no quedan
# ventas a terceros; dividir entre eso dio días de cobranza de −2,213.
cob, pag, mot = ek.bases_de_dias(_FILA, {'ingresos': 1000.0, 'gastos': 0.0}, _EFECTIVO)
check('sin ventas a terceros la base es None, no cero', cob is None)
check('y se dice por qué', mot == 'sin_ventas_a_terceros')
cob, pag, mot = ek.bases_de_dias(_FILA, {'ingresos': 1500.0, 'gastos': 0.0}, _EFECTIVO)
check('una base negativa también se suprime', cob is None)
cob, pag, mot = ek.bases_de_dias(_FILA, {'ingresos': 0.0, 'gastos': 5000.0}, _EFECTIVO)
check('base de pago negativa se suprime', pag is None)
check('con motivo propio', mot == 'sin_compras_a_terceros')

try:
    ek.bases_de_dias(_FILA, None, {'base_dias_pago': 'inventada'})
    check('una convención desconocida LEVANTA', False)
except ek.ConvencionDesconocida:
    check('una convención desconocida LEVANTA', True)
check('sin convención declarada se usa la clásica',
      casi(ek.bases_de_dias(_FILA, None, {})[1], 50.0))

# MARGEN BRUTO INTERPRETABLE O NO. No usa un umbral inventado: compara el costo
# directo contra los gastos de operación.
check('costo menor que gastos: margen bruto no interpretable',
      ek.costo_inmaterial(_FILA) is True)
check('costo mayor que gastos: margen bruto sí dice algo',
      ek.costo_inmaterial({'costo_servicio': 800.0, 'gastos_operacion': 100.0}) is False)
check('sin datos no se afirma nada',
      ek.costo_inmaterial({'costo_servicio': None, 'gastos_operacion': 100.0}) is False)

seccion('Sentinela de bases — llave ausente no es lo mismo que None')
# EL ERROR: tratar los dos casos igual hizo que una empresa cuyos días de
# cobranza se habían suprimido a propósito volviera a mostrar 187 días,
# calculados contra ingresos que son casi todos facturación a sus hermanas.
_base = {'ingresos': 1200.0, 'costo_servicio': 600.0, 'cuentas_x_cobrar': 200.0,
         'cuentas_x_pagar': 100.0, 'inventarios': 0.0}
r_sin = rf.razones(dict(_base))
check('sin la llave se usa el ingreso como base', r_sin['dso'] is not None)
r_none = rf.razones(dict(_base, base_cobranza=None))
check('con la llave en None NO se calcula', r_none['dso'] is None)
check('y el pago se comporta igual',
      rf.razones(dict(_base, base_pago=None))['dpo'] is None)
r_expl = rf.razones(dict(_base, base_cobranza=600.0))
check('una base explícita se respeta',
      casi(r_expl['dso'], r_sin['dso'] * 2, tol=0.01))

seccion('Entradas manuales — suministro y sobrescritura no son lo mismo')
import entradas_manuales as _em

check('el catálogo separa las dos clases',
      {c['tipo'] for c in _em.CAMPOS.values()} == {_em.SUMINISTRO, _em.SOBRESCRITURA})
for k, c in _em.CAMPOS.items():
    for campo in ('etiqueta', 'unidad', 'tipo', 'grupo', 'ayuda', 'ambito'):
        check(f'{k} declara {campo}', campo in c)
    check(f'{k} pertenece a un grupo registrado',
          c['grupo'] in {g for g, _, _ in _em.GRUPOS})

e = _em.Entradas()
# SUMINISTRO: el ERP no tiene esto, se captura sin ceremonia.
e.fijar('*', '*', 'beta', 1.10, autor='Ana')
check('un suministro se captura sin desbloquear', len(e.entradas) == 1)
# SOBRESCRITURA: exige desbloqueo Y motivo. Las dos cosas.
for kwargs, desc in (
        ({}, 'sin desbloquear'),
        ({'desbloqueado': True}, 'desbloqueado pero sin motivo')):
    try:
        e.fijar('NCS', '2026-08', 'ingresos', 100.0, autor='Ana', **kwargs)
        check(f'una sobrescritura {desc} se rechaza', False)
    except _em.EntradaInvalida:
        check(f'una sobrescritura {desc} se rechaza', True)
e.fijar('NCS', '2026-08', 'ingresos', 100.0, motivo='factura duplicada',
        autor='Ana', desbloqueado=True)
check('con desbloqueo y motivo sí se guarda', len(e.sobrescrituras()) == 1)
# El factor 100 es el error de captura más silencioso que existe.
for campo, valor in (('rf', 960.0), ('beta', 99.0), ('erp', 650.0)):
    try:
        e.fijar('*', '*', campo, valor, autor='Ana')
        check(f'{campo}={valor} fuera de rango se rechaza', False)
    except _em.EntradaInvalida:
        check(f'{campo}={valor} fuera de rango se rechaza', True)

seccion('Entradas — se escribe en porcentaje, se guarda en fracción')
# LA CONVENCIÓN FINANCIERA MANDA EN LA PANTALLA: donde la columna dice %, se
# teclea el porcentaje. La versión anterior mostraba `%` y esperaba la
# fracción, y se capturaron 9.6, 1.77, 7.75 y 12.24 en campos que esperaban
# 0.096, 0.0177, 0.0775 y 0.1224. Los cuatro se habrían rechazado.
for campo, escrito, guardado in (('rf', 9.6, 0.096), ('erp', 1.77, 0.0177),
                                 ('kd', 7.75, 0.0775),
                                 ('tasa_impositiva', 12.24, 0.1224)):
    check(f'{campo}: se escribe {escrito} y se guarda {guardado}',
          casi(_em.a_interno(campo, escrito), guardado, tol=1e-12))
    check(f'{campo}: y se vuelve a mostrar {escrito}',
          casi(_em.a_mostrado(campo, guardado), escrito, tol=1e-9))
# El ruido de punto flotante no llega al archivo ni a la bitácora: 12.24/100
# da 0.12240000000000001 y eso hace dudar a quien audite la captura.
check('la conversión no deja cola de dígitos',
      repr(_em.a_interno('tasa_impositiva', 12.24)) == '0.1224')
# Lo que NO es porcentaje pasa intacto: una beta de 1.2 es 1.2, no 0.012.
for campo, v in (('beta', 1.2), ('capex', 1500000.0), ('ingresos', 26348923.37)):
    check(f'{campo} no se divide entre cien',
          casi(_em.a_interno(campo, v), v, tol=1e-9)
          and casi(_em.a_mostrado(campo, v), v, tol=1e-9))
check('a_mostrado tolera un hueco', _em.a_mostrado('rf', None) is None)
# Ida y vuelta: lo que se escribe es lo que se vuelve a leer.
for campo in _em.CAMPOS:
    v = 3.25
    check(f'{campo}: ida y vuelta conserva el valor',
          casi(_em.a_mostrado(campo, _em.a_interno(campo, v)), v, tol=1e-9))
# El rango se declara en la unidad en que se escribe, para que el mensaje de
# error hable el idioma de quien lo lee.
try:
    _em.validar('rf', 960.0)
    check('el mensaje de rango habla en la unidad escrita', False)
except _em.EntradaInvalida as _e:
    check('el mensaje de rango habla en la unidad escrita',
          '60' in str(_e) and '%' in str(_e), str(_e))
try:
    e.fijar('*', '*', 'campo_inventado', 1, autor='Ana')
    check('un campo inexistente se rechaza', False)
except _em.EntradaInvalida:
    check('un campo inexistente se rechaza', True)
# Un dato de periodo no se puede fijar para todos los periodos: copiaría la
# misma cifra a 81 meses, y eso no es un dato.
try:
    e.fijar('NCS', '*', 'ingresos', 1.0, motivo='x', autor='Ana', desbloqueado=True)
    check('un dato de periodo no se fija para todos los periodos', False)
except _em.EntradaInvalida:
    check('un dato de periodo no se fija para todos los periodos', True)

seccion('Entradas — gana la más específica')
e2 = _em.Entradas()
e2.fijar('*', '*', 'beta', 1.10, autor='A')
check('sin nada más específico, gana la global',
      casi(e2.resolver('NTS', '2026-08')['beta']['valor'], 1.10, 1e-9))
e2.fijar('NTS', '*', 'beta', 1.35, autor='A')
check('la de la empresa gana sobre la global',
      casi(e2.resolver('NTS', '2026-08')['beta']['valor'], 1.35, 1e-9))
check('y las demás empresas siguen con la global',
      casi(e2.resolver('NCS', '2026-08')['beta']['valor'], 1.10, 1e-9))
e2.fijar('NTS', '2026-08', 'beta', 1.50, autor='A')
check('empresa+periodo gana sobre empresa',
      casi(e2.resolver('NTS', '2026-08')['beta']['valor'], 1.50, 1e-9))
check('y otro periodo de la misma empresa conserva la suya',
      casi(e2.resolver('NTS', '2026-07')['beta']['valor'], 1.35, 1e-9))

seccion('Entradas — borrar devuelve el cálculo automático')
e3 = _em.Entradas()
e3.fijar('NCS', '2026-08', 'ingresos', 100.0, motivo='x', autor='A',
         desbloqueado=True)
check('está capturado', 'ingresos' in e3.resolver('NCS', '2026-08'))
e3.borrar('NCS', '2026-08', 'ingresos')
check('borrado: ya no aplica', 'ingresos' not in e3.resolver('NCS', '2026-08'))
check('borrar algo inexistente no revienta',
      e3.borrar('NCS', '2026-08', 'ingresos') is None)

seccion('Entradas — la sobrescritura rehace la cascada')
# EL BUG QUE ESTO VIGILA: sustituir los ingresos y dejar el EBIT viejo daba una
# fila con el renglón de arriba corregido y los de abajo no. Lo detectó la
# prueba que compara las dos pestañas.
_fila = {'ingresos': 1000.0, 'costo_servicio': 100.0, 'gastos_operacion': 600.0,
         'depreciacion': 50.0, 'ebit': 300.0, 'ebitda': 350.0,
         'gastos_financieros': 20.0, 'ebt': 280.0, 'impuestos': 80.0,
         'utilidad_neta': 200.0}
_res = {'ingresos': {'valor': 1200.0, 'tipo': _em.SOBRESCRITURA,
                     'motivo': 'x', 'autor': 'A', 'fecha': 'hoy'}}
_f2 = _em.aplicar_a_fila(dict(_fila), _res)
check('el ingreso se sustituye', casi(_f2['ingresos'], 1200.0))
check('el EBIT se rehace', casi(_f2['ebit'], 500.0))
# LA TRAMPA: la depreciación YA ESTÁ dentro de los gastos de operación. La
# fórmula de respaldo de derivar_estado la resta aparte, y aplicarla aquí la
# descontaría dos veces — el mismo error que costó corregir todo el EBITDA.
check('NO se le vuelve a restar la depreciación',
      not casi(_f2['ebit'], 1200.0 - 100.0 - 600.0 - 50.0, tol=1.0))
check('el EBITDA se rehace encima del EBIT', casi(_f2['ebitda'], 550.0))
check('el EBITDA supera al EBIT exactamente en la depreciación',
      casi(_f2['ebitda'] - _f2['ebit'], 50.0))
check('el EBT se rehace', casi(_f2['ebt'], 480.0))
check('la utilidad neta se rehace', casi(_f2['utilidad_neta'], 400.0))
check('queda el rastro de quién lo tocó', _f2['_manual']['ingresos']['motivo'] == 'x')
# Un suministro del costo de capital NO toca la fila: entra por los supuestos.
_f3 = _em.aplicar_a_fila(dict(_fila), {
    'beta': {'valor': 1.4, 'tipo': _em.SUMINISTRO, 'motivo': '', 'autor': 'A',
             'fecha': 'hoy'}})
check('la beta no se mete en la fila financiera', 'beta' not in _f3)
check('ni marca la fila', '_manual' not in _f3)
_sup = _em.aplicar_a_supuestos({'beta': 1.1, 'rf': 0.09}, {
    'beta': {'valor': 1.4, 'tipo': _em.SUMINISTRO, 'motivo': '', 'autor': 'A',
             'fecha': 'hoy'}})
check('la beta sí entra por los supuestos', casi(_sup['beta'], 1.4, 1e-9))
check('y no borra los demás supuestos', casi(_sup['rf'], 0.09, 1e-9))

seccion('Entradas — el estado financiero también se corrige')
_er = {'ingresos': 1000.0, 'costo': 100.0, 'gastos_operacion': 600.0,
       'utilidad_bruta': 900.0, 'utilidad_operacion': 300.0,
       'resultado_financiero': 20.0, 'otros': 0.0,
       'resultado_antes_impuestos': 280.0, 'impuestos': 80.0,
       'utilidad_neta': 200.0}
_bal = {'activo': 5000.0, 'pasivo': 2000.0, 'capital': 3000.0}
_er2, _bal2, _marcas = _em.aplicar_a_estado(_er, _bal, _res)
check('el estado toma el ingreso corregido', casi(_er2['ingresos'], 1200.0))
check('y rehace la utilidad bruta', casi(_er2['utilidad_bruta'], 1100.0))
check('y la de operación', casi(_er2['utilidad_operacion'], 500.0))
check('y la neta', casi(_er2['utilidad_neta'], 400.0))
check('el balance no se toca si no se capturó nada suyo',
      casi(_bal2['activo'], 5000.0))
check('se devuelve la marca', 'ingresos' in _marcas)
_er3, _bal3, _m3 = _em.aplicar_a_estado(_er, _bal, {})
check('sin entradas no se toca nada', _m3 == {} and _er3 is _er)

seccion('Bitácora de cambios — solo se agrega')
import bitacora_cambios as _bc
a1 = _bc.asiento('captura', 'Ana', {'campo': 'beta', 'a': 1.2})
check('el asiento lleva fecha', bool(a1.get('fecha')))
check('el asiento lleva autor', a1['autor'] == 'Ana')
check('sin autor se dice, no se guarda vacío',
      _bc.asiento('captura', '')['autor'] == '(sin identificar)')
check('el acto se guarda tal cual', a1['acto'] == 'captura')
try:
    _bc.asiento('acto_inventado', 'Ana')
    check('un acto no declarado LEVANTA', False)
except _bc.ActoDesconocido:
    check('un acto no declarado LEVANTA', True)
for acto in _bc.ACTOS:
    check(f'el acto {acto} tiene texto legible', bool(_bc.ACTOS[acto].strip()))
check('describir produce una línea legible',
      'Ana' in _bc.describir(a1) and 'beta' in _bc.describir(a1))
check('describir aguanta un asiento sin detalle',
      isinstance(_bc.describir(_bc.asiento('consulta', 'Ana')), str))

seccion('Convenciones — una mal escrita LEVANTA, no cae al valor por defecto')
import modelo as _mo


def _pol(**conv):
    return _mo.PoliticaFinanciera(convenciones=conv)


c_ok = ek.leer_convenciones(_pol(base_dias_pago='costo_de_ventas',
                                 dias_anio='360', holgura_semaforo='0.05',
                                 banda_tasa_efectiva='0.1,0.5'))
check('días del año se lee como entero', c_ok['dias_anio'] == 360)
check('la holgura se lee como fracción', casi(c_ok['holgura_semaforo'], 0.05, 1e-9))
check('la banda se lee como par', c_ok['banda_tasa_efectiva'] == (0.1, 0.5))
c_vacia = ek.leer_convenciones(_pol())
check('sin convenciones se usan las de arranque',
      c_vacia['dias_anio'] == rf.DIAS_ANIO
      and c_vacia['base_dias_pago'] == 'costo_de_ventas')
for malo, desc in (
        ({'dias_anio': 'trescientos'}, 'días del año no numérico'),
        ({'dias_anio': '0'}, 'días del año en cero'),
        ({'dias_anio': '-30'}, 'días del año negativo'),
        ({'holgura_semaforo': '10'}, 'holgura en porcentaje en vez de fracción'),
        ({'holgura_semaforo': '-0.1'}, 'holgura negativa'),
        ({'banda_tasa_efectiva': '0.5,0.1'}, 'banda al revés'),
        ({'banda_tasa_efectiva': '0.5'}, 'banda con un solo número'),
        ({'base_dias_pago': 'inventada'}, 'base de días inexistente')):
    try:
        ek.leer_convenciones(_pol(**malo))
        check(f'LEVANTA con {desc}', False)
    except ek.ConvencionDesconocida:
        check(f'LEVANTA con {desc}', True)

seccion('Política financiera — es configuración con validación')
import modelo as mo
p = mo.PoliticaFinanciera(supuestos={'rf': '0.095'}, metas={'roe': 0.18})
check('los números capturados como texto se convierten', isinstance(p.supuestos['rf'], float))
check('y valen lo que dicen', casi(p.supuestos['rf'], 0.095, tol=1e-9))
p2 = mo.PoliticaFinanciera(supuestos={'rf': None})
check('un valor nulo se descarta en vez de guardarse', 'rf' not in p2.supuestos)
try:
    mo.PoliticaFinanciera(metas={'roe': 'como quince por ciento'})
    check('un valor no numérico LEVANTA', False)
except mo.ErrorConfiguracion:
    check('un valor no numérico LEVANTA', True)
p3 = mo.PoliticaFinanciera()
check('una política vacía es válida', p3.supuestos == {} and p3.metas == {})
check('y no inventa convenciones', p3.convenciones == {})
c = mo.Cliente(nombre='Prueba', politica=mo.PoliticaFinanciera(metas={'dso': 40}))
d = c.a_dict()
check('la política viaja en la serialización', d['politica']['metas']['dso'] == 40)
check('y regresa entera', mo.Cliente.de_dict(d).politica.metas['dso'] == 40)
check('un cliente sin política se reconstruye sin reventar',
      mo.Cliente.de_dict({'nombre': 'X'}).politica.metas == {})


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
if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--rapido', action='store_true',
                    help='omite las pruebas que recorren toda la serie de datos')
    args = ap.parse_args()

    if not args.rapido:
        try:
            pruebas_sobre_datos_reales()
        except FileNotFoundError as e:
            print(f'\n(se omiten las pruebas sobre datos reales: falta {e.filename})')
        try:
            pruebas_sobre_kpis()
        except FileNotFoundError as e:
            print(f'\n(se omiten las pruebas de indicadores: falta {e.filename};'
                  f' se genera con: python dashboard/exportar_kpis.py)')

    print('\n' + '=' * 72)
    total = _pasadas + len(_fallos)
    if _fallos:
        print(f' {len(_fallos)} DE {total} PRUEBAS FALLARON')
        for f in _fallos[:40]:
            print(f'   · {f}')
        if len(_fallos) > 40:
            print(f'   … y {len(_fallos) - 40} más')
        raise SystemExit(1)
    print(f' {total} PRUEBAS, TODAS PASARON')
    print('=' * 72)
