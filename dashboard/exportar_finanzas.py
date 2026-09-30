# -*- coding: utf-8 -*-
"""
===============================================================================
 PREPARA LOS ESTADOS FINANCIEROS PARA EL TABLERO
===============================================================================
Toma los saldos extraídos del ERP y produce `finanzas.json`: Balance General y
Estado de Resultados por empresa y por mes, más el detalle por rubro para poder
abrir cada renglón.

POR EMPRESA, NO CONSOLIDADO — Y ESO SE DICE EN PANTALLA
-------------------------------------------------------
Cada empresa se presenta por separado. Se incluye además un total del grupo,
pero marcado como **suma, no consolidación**: no elimina las operaciones entre
empresas del grupo.

La distinción no es académica aquí: una parte grande de la facturación del
grupo es entre sus propias empresas. Una "utilidad del grupo" que
no elimine eso está contando ventas que el grupo se hizo a sí mismo. Por eso el
total viaja con `es_suma: true` y la interfaz lo etiqueta — un número que puede
malinterpretarse tiene que venir diciendo qué es.

LO QUE HAY QUE SABER DE LOS DICIEMBRES
--------------------------------------
SAP hace cierre y reapertura total a fin de año: el asiento de cierre deja en
cero TODAS las cuentas, incluidas las de balance. La extracción ya excluye ese
asiento y el de reapertura (son un par que se anula), así que los diciembres
traen posición real. `balance_general()` además detecta el caso por si algún
periodo quedara arrasado, y lo marca en vez de devolver ceros en silencio.
===============================================================================
"""
import os
import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(HERE)
FINANZAS = os.path.join(BASE_DIR, 'finanzas')
DATOS_ERP = os.path.join(FINANZAS, 'datos_erp')

sys.path.insert(0, FINANZAS)
sys.path.insert(0, os.path.join(FINANZAS, 'erp'))
sys.path.insert(0, os.path.join(FINANZAS, 'configuracion'))

import analisis_vertical_horizontal as av       # noqa: E402
import entradas_manuales as em                 # noqa: E402
from erp import clasificador_cuentas as cl      # noqa: E402

ANIO_EPOCH = 2020

# Cuánto detalle se publica. Nivel 2 es el rubro ("Bancos", "Clientes
# Nacionales"), que es a lo que alguien quiere bajar desde un total. El nivel 3
# y más es el detalle de auxiliares: multiplica el tamaño por diez y para verlo
# uno ya está en el ERP, no en un tablero.
NIVEL_DETALLE = 2


def cargar(empresa):
    with open(os.path.join(DATOS_ERP, f'cuentas_{empresa}.json'), encoding='utf-8') as f:
        cuentas = json.load(f)
    cuentas, _ = cl.clasificar_catalogo(cuentas, empresa)
    with open(os.path.join(DATOS_ERP, f'saldos_{empresa}.json'), encoding='utf-8') as f:
        saldos = json.load(f)
    return {c['codigo']: c for c in cuentas}, saldos


def rubro_de(codigo, cuentas):
    """Sube por el árbol hasta el nivel de rubro. Devuelve (código, nombre).

    Se sube por el ÁRBOL y no se corta el código por longitud: la numeración y
    la jerarquía no siempre coinciden —en este plan de cuentas las cuentas 81*
    cuelgan del cajón 7— y cortar el código agruparía cosas que el ERP tiene
    separadas.
    """
    visto = set()
    actual = cuentas.get(codigo)
    mejor = actual
    while actual and actual['codigo'] not in visto:
        visto.add(actual['codigo'])
        # Se PARA en el primer antepasado del nivel buscado. Subiendo desde la
        # hoja, ese es el más profundo que cumple — y por lo tanto el rubro.
        # Seguir subiendo hace que la raíz ("Activos") termine pisando la
        # elección y todo el detalle se colapse a un solo renglón, que fue
        # exactamente lo que pasó en la primera versión.
        if (actual.get('nivel') or 99) <= NIVEL_DETALLE:
            return actual['codigo'], actual['nombre']
        mejor = actual
        padre = (actual.get('cuenta_padre') or '').strip()
        if not padre or padre not in cuentas:
            break
        actual = cuentas[padre]
    return (mejor['codigo'], mejor['nombre']) if mejor else (codigo, codigo)


def detalle_balance(bal, cuentas):
    """Agrupa el detalle del Balance por rubro, quedándose con lo material."""
    salida = {}
    for clase, filas in bal['detalle'].items():
        por_rubro = {}
        for f in filas:
            cod, nom = rubro_de(f['codigo'], cuentas)
            r = por_rubro.setdefault(cod, {'n': nom, 'v': 0.0})
            r['v'] += f['valor']
        # Se descarta lo que redondea a cero: son cuentas abiertas sin uso y
        # llenan la pantalla de renglones en cero.
        salida[clase] = sorted(
            ({'c': c, 'n': r['n'], 'v': round(r['v'], 2)}
             for c, r in por_rubro.items() if abs(r['v']) >= 0.5),
            key=lambda x: -abs(x['v']))
    return salida



# ---------------------------------------------------------------------------
# Intercompañía: lo que hace falta para netear y para consolidar
# ---------------------------------------------------------------------------
def interco_por_periodo(cliente):
    """Por empresa y mes: cuánto facturó al grupo y cuánto le compró al grupo.

    Se usa el SUBTOTAL, no el total. El Estado de Resultados viene del mayor y
    está neto de IVA; restarle un total con impuestos dejaría el ingreso neteado
    más bajo de lo que corresponde, y la diferencia sería justo el IVA — un
    error que además crece con el volumen, así que parecería una tendencia.
    """
    mapa = cliente.mapa_interco()
    out = {}
    for e in cliente.empresas:
        ini = e.iniciales
        acum = {}
        for tipo, campo in (('venta', 'ingresos'), ('compra', 'gastos')):
            ruta = os.path.join(DATOS_ERP, f'facturas_{ini}_{tipo}.json')
            if not os.path.exists(ruta):
                continue
            with open(ruta, encoding='utf-8') as f:
                docs = json.load(f)
            for d in docs:
                if d.get('clase_documento') != 'normal' or not d.get('anio'):
                    continue
                rfc = (d.get('rfc') or '').strip().upper()
                cc = (d.get('contraparte_id') or '').strip().upper()
                if not (mapa.get(rfc) or mapa.get(f'{ini}:{cc}')):
                    continue
                k = f"{d['anio']}-{d['mes']:02d}"
                reg = acum.setdefault(k, {'ingresos': 0.0, 'gastos': 0.0})
                reg[campo] += d.get('subtotal') or 0.0
        out[ini] = {k: {kk: round(vv, 2) for kk, vv in v.items()}
                    for k, v in acum.items()}
    return out


def consolidado_por_periodo(periodos, empresas):
    """El grupo consolidado en cada periodo, con las eliminaciones aplicadas."""
    sys.path.insert(0, FINANZAS)
    import consolidacion as co
    out, avisos = {}, []
    for clave in periodos:
        a, m = (int(x) for x in clave.split('-'))
        try:
            c = co.consolidar(a, m, empresas)
        except Exception as e:
            avisos.append(f'{clave}: no se pudo consolidar ({type(e).__name__})')
            continue
        b, r = c['balance'], c['resultados']
        out[clave] = {
            'balance': {
                'activo': round(b['activo'], 2), 'pasivo': round(b['pasivo'], 2),
                'capital_contable': round(b['capital_contable'], 2),
                'acumulados': round(b['resultados_acumulados'], 2),
                'resultado': round(b['resultado_ejercicio'], 2),
                'capital': round(b['capital_contable'] + b['resultados_acumulados']
                                 + b['resultado_ejercicio'], 2),
                'descuadre': c['descuadre'], 'cierre': False,
            },
            'resultados': {
                'ingresos': round(r['ingresos'], 2), 'costo': round(r['costo'], 2),
                'bruta': round(r['utilidad_bruta'], 2),
                'gastos': round(r['gastos_operacion'], 2),
                'operacion': round(r['utilidad_operacion'], 2),
                'financiero': round(r['resultado_financiero'], 2),
                'otros': round(r['otros'], 2),
                'antes_impuestos': round(r['resultado_antes_impuestos'], 2),
                'impuestos': round(r['impuestos'], 2),
                'neta': round(r['utilidad_neta'], 2),
            },
            'eliminado': c['eliminado_saldos'],
            'eliminado_activo': c['eliminado_activo'],
            'eliminado_pasivo': c['eliminado_pasivo'],
            'eliminado_resultados': c['eliminado_resultados'],
            'descalce_facturacion': c['descalce_facturacion'],
            'sin_conciliar': c['sin_conciliar'],
        }
    return out, avisos


def main():
    try:
        import repositorio as repo
        cliente = repo.cliente_actual(repo.almacen_por_defecto())
        empresas = [e.iniciales for e in cliente.empresas if e.activa]
        nombres = {e.iniciales: e.nombre for e in cliente.empresas}
        anio_min = cliente.retencion.anio_minimo()
        entradas = em.cargar(repo.almacen_por_defecto(), cliente)
        n_sob = len(entradas.sobrescrituras())
        print(f'cliente: {cliente.nombre}'
              + (f'  ·  {len(entradas.entradas)} entrada(s) manual(es), '
                 f'{n_sob} sobrescritura(s)' if entradas.entradas else ''))
    except Exception as e:
        print(f'  aviso: sin configuración ({type(e).__name__}); se deducen las empresas')
        empresas = sorted({a.split('_')[1].replace('.json', '')
                           for a in os.listdir(DATOS_ERP) if a.startswith('saldos_')})
        nombres = {e: e for e in empresas}
        anio_min = None
        entradas = None

    salida = {'empresas': [], 'nombres': nombres, 'periodos': [],
              'balance': {}, 'resultados': {}, 'detalle': {}, 'avisos': []}
    periodos_vistos = set()

    for ini in empresas:
        if not os.path.exists(os.path.join(DATOS_ERP, f'saldos_{ini}.json')):
            print(f'  {ini}: sin estados financieros extraídos')
            continue
        cuentas, saldos = cargar(ini)
        pers = sorted({(s['anio'], s['mes']) for s in saldos})
        if anio_min:
            pers = [p for p in pers if p[0] >= anio_min]
        salida['empresas'].append(ini)
        salida['balance'][ini] = {}
        salida['resultados'][ini] = {}
        salida['detalle'][ini] = {}
        n_cierre = 0
        for (a, m) in pers:
            clave = f'{a}-{m:02d}'
            periodos_vistos.add((a, m))
            bal = av.balance_general(saldos, cuentas, a, m)
            er = av.estado_resultados(saldos, cuentas, a, m)
            # Las correcciones capturadas a mano entran AQUÍ, en el estado, no
            # solo del lado de los indicadores. Si se aplicaran nada más allá,
            # esta pestaña y la de indicadores mostrarían cifras distintas del
            # mismo mes — justo lo que este desarrollo se propuso evitar.
            marcas = {}
            if entradas is not None:
                er, bal, marcas = em.aplicar_a_estado(
                    er, bal, entradas.resolver(ini, clave))
            if bal.get('es_cierre_anual'):
                n_cierre += 1
            salida['balance'][ini][clave] = {
                'activo': round(bal['activo'], 2),
                'pasivo': round(bal['pasivo'], 2),
                'capital': round(bal['capital'], 2),
                'capital_contable': round(bal['capital_contable'], 2),
                'acumulados': round(bal.get('resultados_acumulados', 0), 2),
                'resultado': round(bal['resultado_ejercicio'], 2),
                'descuadre': round(bal['descuadre'], 2),
                'cierre': bool(bal.get('es_cierre_anual')),
            }
            if marcas:
                salida['balance'][ini][clave]['manual'] = marcas
            salida['resultados'][ini][clave] = {
                'ingresos': round(er['ingresos'], 2),
                'costo': round(er['costo'], 2),
                'bruta': round(er['utilidad_bruta'], 2),
                'gastos': round(er['gastos_operacion'], 2),
                'operacion': round(er['utilidad_operacion'], 2),
                'financiero': round(er['resultado_financiero'], 2),
                'otros': round(er['otros'], 2),
                'antes_impuestos': round(er['resultado_antes_impuestos'], 2),
                'impuestos': round(er.get('impuestos', 0), 2),
                'neta': round(er.get('utilidad_neta', 0), 2),
            }
            if marcas:
                salida['resultados'][ini][clave]['manual'] = marcas
            # El detalle solo del último periodo de cada año: es lo que alguien
            # abre. Guardarlo de los 81 meses multiplicaría el archivo por
            # veinte para que nadie lo mire.
            if m == 12 or (a, m) == pers[-1]:
                salida['detalle'][ini][clave] = detalle_balance(bal, cuentas)
        print(f'  {ini}: {len(pers)} periodos'
              + (f'  ({n_cierre} marcados como cierre anual)' if n_cierre else ''))
        if n_cierre:
            salida['avisos'].append(
                f'{ini}: {n_cierre} periodo(s) quedaron arrasados por el asiento '
                f'de cierre de SAP; se muestra la última posición real anterior.')

    salida['periodos'] = [f'{a}-{m:02d}' for (a, m) in sorted(periodos_vistos)]

    # Intercompañía por periodo: habilita la vista neteada por empresa.
    try:
        salida['interco'] = interco_por_periodo(cliente) if cliente else {}
    except Exception as e:
        print(f'  aviso: no se pudo calcular el intercompañía ({type(e).__name__})')
        salida['interco'] = {}

    # CONSOLIDADO DE VERDAD, con eliminaciones. Sustituye a la suma que se
    # mostraba antes marcada con advertencia: ya no hace falta advertir de algo
    # que ahora se calcula bien.
    if len(salida['empresas']) > 1:
        print('  consolidando el grupo...')
        cons, avisos_c = consolidado_por_periodo(salida['periodos'], salida['empresas'])
        salida['consolidado'] = cons
        salida['avisos'] += avisos_c
        malos = [k for k, v in cons.items() if abs(v['balance']['descuadre']) > 1]
        if malos:
            salida['avisos'].append(
                f'{len(malos)} periodo(s) consolidados no cuadran: {", ".join(malos[:5])}')
        print(f'  consolidado: {len(cons)} periodos'
              + (f', {len(malos)} con descuadre' if malos else ', todos cuadran'))

    # Se conserva además la SUMA simple, para poder contrastarla contra el
    # consolidado y ver de un vistazo cuánto pesaba lo intercompañía.
    if len(salida['empresas']) > 1:
        suma_b, suma_r = {}, {}
        for clave in salida['periodos']:
            b = {k: 0.0 for k in ('activo', 'pasivo', 'capital', 'capital_contable',
                                  'acumulados', 'resultado', 'descuadre')}
            r = {k: 0.0 for k in ('ingresos', 'costo', 'bruta', 'gastos', 'operacion',
                                  'financiero', 'otros', 'antes_impuestos')}
            hay = False
            for ini in salida['empresas']:
                bi = salida['balance'][ini].get(clave)
                ri = salida['resultados'][ini].get(clave)
                if bi:
                    hay = True
                    for k in b:
                        b[k] += bi.get(k, 0.0)
                if ri:
                    for k in r:
                        r[k] += ri.get(k, 0.0)
            if hay:
                suma_b[clave] = {k: round(v, 2) for k, v in b.items()}
                suma_b[clave]['cierre'] = False
                suma_r[clave] = {k: round(v, 2) for k, v in r.items()}
        salida['balance']['__GRUPO__'] = suma_b
        salida['resultados']['__GRUPO__'] = suma_r
        salida['es_suma'] = True

    ruta = os.path.join(HERE, 'finanzas.json')
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, separators=(',', ':'))
    print(f'\nfinanzas.json: {os.path.getsize(ruta) / 1024:.0f} KB · '
          f'{len(salida["empresas"])} empresas · {len(salida["periodos"])} periodos')
    for a in salida['avisos']:
        print(f'  aviso: {a}')


if __name__ == '__main__':
    main()
