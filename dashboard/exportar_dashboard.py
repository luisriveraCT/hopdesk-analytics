# -*- coding: utf-8 -*-
"""
===============================================================================
 PREPARA LOS DATOS DEL TABLERO — desde el ERP
===============================================================================
Lee las facturas extraídas del ERP (`finanzas/datos_erp/facturas_*_<tipo>.json`)
y produce, para cada TIPO de factura —venta o compra—, lo que consume el
tablero:

                        ventas               compras
  diccionarios + agr.   meta.json            meta-compra.json     (se incrustan)
  detalle por año       data/rows-AAAA.json  data/compra/rows-AAAA.json
  índice                indice.json          indice-compra.json

Los dos tipos salen del MISMO código y con el MISMO formato. Es lo que permite
que el tablero use para las compras exactamente los mismos filtros, gráficas,
tabla y descargas que ya tenía para las ventas: solo cambia qué datos lee. Las
rutas de ventas son las de siempre, así que nada de lo que ya las lee cambió.

    python exportar_dashboard.py                 los dos tipos
    python exportar_dashboard.py --tipo compra   solo uno

LO QUE HAY QUE SABER AL LEER EL TABLERO
---------------------------------------
 1. **Tres clases de documento.** El ERP guarda `normal`, `cancelada` y
    `documento_de_cancelacion` —este último anula a una cancelada y trae el
    importe en POSITIVO—. Se publican las normales y las canceladas, éstas
    marcadas (`s` = 1) para que el filtro de Canceladas tenga qué enseñar y las
    excluya por omisión. Los documentos de cancelación NO se publican: sumarlos
    contaría la misma operación otra vez.

 2. **Cada importe en su moneda.** `t` es el total en moneda local (DocTotal);
    `u` son los dólares de las facturas emitidas en USD (DocTotalFc). Ninguno
    se calcula aquí: los dos vienen del ERP.

 3. **Abierta o cerrada** (`o`) es el DocumentStatus del ERP al momento de la
    extracción: en una venta, pendiente de cobro; en una compra, pendiente de
    pago. Es una foto de ese día, y meta.generado dice cuál.

 4. **Concepto y Localidad no vienen.** En el ERP viven en las LÍNEAS del
    documento, no en la cabecera. Los catálogos quedan vacíos y el tablero
    esconde lo que dependa de ellos. Si se necesitan, es una extracción
    adicional, no un parche aquí.

NADA CABLEADO
-------------
Las empresas, sus nombres y cuánta historia se publica salen de la
configuración del cliente (`finanzas/configuracion/`). El año base del índice
de meses sale de los propios datos: el primer año publicado.
===============================================================================
"""
import os
import re
import sys
import json
import math
import argparse
import unicodedata
import datetime as dt
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(HERE)
FINANZAS = os.path.join(BASE_DIR, 'finanzas')
DATOS_ERP = os.path.join(FINANZAS, 'datos_erp')
OUT_DIR = HERE
DATA_DIR = os.path.join(OUT_DIR, 'data')

sys.path.insert(0, os.path.join(FINANZAS, 'configuracion'))
sys.path.insert(0, os.path.join(FINANZAS, 'erp'))
from extraer_facturacion import cargar as cargar_facturas   # noqa: E402

TIPOS = ('venta', 'compra')

SUFIJOS_LEGALES = (
    r'\b(S\s*A\s*P\s*I|S\s*A\s*B|S\s*A|S\s*C|S\s*DE\s*R\s*L|SRL|DS)\b\s*'
    r'(DE\s*)?(C\s*V)?|(\bDE\s*C\s*V\b)|\bLLC\b|\bINC\b|\bLTD\b|\bGMBH\b|\bCORP\b'
)

# Las columnas de cada trozo, en el orden en que el tablero las lee
# (mergeChunk en plantilla.html). Agregar una es agregarla aquí Y allá.
COLUMNAS = 'e d c k l s o t b u x f r'.split()


def rutas(tipo):
    """Dónde va cada archivo de un tipo. Es el único lugar que lo decide."""
    if tipo == 'venta':
        return {'meta': os.path.join(OUT_DIR, 'meta.json'),
                'indice': os.path.join(OUT_DIR, 'indice.json'),
                'datos': DATA_DIR, 'prefijo': ''}
    return {'meta': os.path.join(OUT_DIR, f'meta-{tipo}.json'),
            'indice': os.path.join(OUT_DIR, f'indice-{tipo}.json'),
            'datos': os.path.join(DATA_DIR, tipo), 'prefijo': f'{tipo}/'}


def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(s))
                   if not unicodedata.combining(c))


def norm_txt(s):
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return ''
    t = strip_accents(s).upper().replace('&', ' Y ')
    t = re.sub(r'[^A-Z0-9 ]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def clave_cliente(s):
    """Clave canónica: sin acentos, sin puntuación y sin sufijos societarios.

    El problema es el mismo con clientes y con proveedores: la misma
    contraparte aparece como "ACME SA DE CV", "Acme, S.A. de C.V." y "ACME"
    según quién la capturó, y sin canonicalizar salen como tres distintas.
    """
    t = norm_txt(s)
    prev = None
    while prev != t:
        prev = t
        t = re.sub(SUFIJOS_LEGALES, ' ', t)
        t = re.sub(r'\s+', ' ', t).strip()
    return t


def dias_desde(fecha_iso, anio_base):
    """Días desde el 1-ene del año base. Sin pandas: son cuentas de calendario."""
    try:
        d = dt.date.fromisoformat(fecha_iso[:10])
    except (ValueError, TypeError):
        return None
    return (d - dt.date(anio_base, 1, 1)).days


def cargar_configuracion():
    """Empresas, nombres y retención, desde la configuración del cliente.

    Si no hay configuración todavía, se deduce de los archivos extraídos y se
    avisa. Se prefiere avisar y seguir a fallar: quien apenas está montando el
    entorno necesita ver el tablero antes de configurar nada.
    """
    try:
        import repositorio as repo
        cliente = repo.cliente_actual(repo.almacen_por_defecto())
        empresas = [(e.iniciales, e.nombre) for e in cliente.empresas if e.activa]
        return cliente, empresas, cliente.retencion.anio_minimo()
    except Exception as e:
        print(f'  aviso: sin configuración de cliente ({type(e).__name__}); '
              f'se deducen las empresas de los archivos extraídos.')
        inis = sorted({a.split('_')[1] for a in os.listdir(DATOS_ERP)
                       if a.startswith('facturas_') and a.endswith('.json')})
        return None, [(i, i) for i in inis], None


def exportar(tipo, cliente, empresas_cfg, anio_minimo):
    print(f'\n=== {tipo.upper()} ===')
    R = rutas(tipo)
    os.makedirs(R['datos'], exist_ok=True)

    # Iniciales tal como las usa el tablero, en el orden de la configuración.
    # Es la misma lista para los dos tipos: los colores y las burbujas de las
    # empresas no se mueven al cambiar de ventas a compras.
    EMPRESAS = [i for i, _ in empresas_cfg]
    EMPRESA_NOMBRE = dict(empresas_cfg)
    emp_map = {e: i for i, e in enumerate(EMPRESAS)}

    # ---------------- cargar las facturas del ERP ----------------
    filas, descartes = [], defaultdict(int)
    for ini in EMPRESAS:
        # La lectura y la compatibilidad con esquemas anteriores viven en
        # cargar(), y solo ahí: cuando este archivo tenía su propia copia de
        # esa tolerancia, las dos discreparon y el tablero mostró 4,663 M
        # mientras el generador de KPIs calculaba 3,038 M para lo mismo.
        docs = cargar_facturas(ini, tipo)
        if not docs:
            print(f'  {ini}: sin extracción todavía')
            continue
        # UN ARCHIVO CON EL ESQUEMA ANTERIOR SE AVISA, NO SE DISIMULA.
        if any('total_moneda' not in d for d in docs):
            print(f'     AVISO: {ini} no trae el importe en moneda del documento '
                  f'(DocTotalFc); sus dólares salen en cero. Hay que reextraerlo:')
            print(f'            python finanzas/erp/extraer_facturacion.py '
                  f'--empresa {ini}')

        n_ini = n_can = 0
        for d in docs:
            clase = d['clase_documento']
            if clase not in ('normal', 'cancelada'):
                descartes[clase] += 1
                continue
            if not d.get('anio'):
                descartes['sin fecha'] += 1
                continue
            if anio_minimo and d['anio'] < anio_minimo:
                descartes['fuera de la retención'] += 1
                continue
            filas.append(d)
            n_ini += 1
            n_can += clase == 'cancelada'
        print(f'  {ini}: {n_ini - n_can:,} vigentes + {n_can:,} canceladas')

    if not filas:
        print(f'  No hay facturas de {tipo} extraídas. Corre primero:\n'
              f'     python finanzas/erp/extraer_facturacion.py --todas')
        return False

    print(f'total a publicar: {len(filas):,} facturas')
    for k, n in sorted(descartes.items(), key=lambda kv: -kv[1]):
        print(f'   no publicadas por {k}: {n:,}')

    # El año base del índice de meses es el primero que se publica. Antes era
    # 2020 escrito aquí y en el tablero, y la historia anterior no cabía.
    anio_base = min(d['anio'] for d in filas)

    # ---------------- contrapartes (clientes o proveedores) ----------------
    por_clave = defaultdict(lambda: defaultdict(int))
    rfc_por_clave = defaultdict(lambda: defaultdict(int))
    for d in filas:
        k = clave_cliente(d.get('contraparte'))
        if k:
            por_clave[k][d['contraparte']] += 1
            if d.get('rfc'):
                rfc_por_clave[k][d['rfc'].strip().upper()] += 1

    claves = sorted(por_clave)
    cli_idx_map = {k: i for i, k in enumerate(claves)}
    # El nombre a mostrar es la variante cruda más frecuente de cada clave; lo
    # mismo el RFC, que es por donde se busca a una contraparte sin acordarse
    # de cómo se escribió su nombre.
    display = {k: max(v.items(), key=lambda kv: kv[1])[0] for k, v in por_clave.items()}
    rfc_de = {k: max(v.items(), key=lambda kv: kv[1])[0] for k, v in rfc_por_clave.items()}

    # ---------------- intercompañía ----------------
    # NO se deduce del nombre. Sale del REGISTRO INTERCOMPAÑÍA de la
    # configuración, que guarda por empresa su RFC, sus RFC alternos (el maestro
    # de socios de SAP tiene erratas reales) y sus CardCodes calificados por
    # libro. Es el mismo criterio que usa HopDesk, y lo llena solo
    # `configurar.py --detectar-interco`, que lee ventas y compras: por eso
    # sirve igual cuando la contraparte es un proveedor.
    #
    # Ojo con el CardCode: solo significa algo DENTRO de su libro. "C1004"
    # existe en las cinco bases nombrando a socios distintos, así que se
    # califica con la empresa de la que salió el documento.
    mapa_ic = cliente.mapa_interco() if cliente else {}
    if not mapa_ic:
        print('  AVISO: el registro intercompañía está vacío. Nada se marcará '
              'como interco. Llénalo con: configurar.py --detectar-interco')

    def codigo_interco(d):
        rfc = (d.get('rfc') or '').strip().upper()
        if rfc in mapa_ic:
            return mapa_ic[rfc]
        cc = (d.get('contraparte_id') or '').strip().upper()
        return mapa_ic.get(f"{d['empresa']}:{cc}", '') if cc else ''

    # Se resuelve por documento y se consolida por clave: una misma
    # contraparte siempre cae del mismo lado.
    ic_por_clave = {}
    for d in filas:
        k = clave_cliente(d.get('contraparte'))
        code = codigo_interco(d)
        if k and code:
            ic_por_clave[k] = code

    clientes_meta = []
    for k in claves:
        code = ic_por_clave.get(k, '')
        clientes_meta.append({'n': display[k], 'g': 1 if code else 0, 'c': code,
                              'r': rfc_de.get(k, '')})

    # ---------------- catálogos ----------------
    # Concepto y Localidad no existen en la cabecera del documento (ver el
    # encabezado). Se dejan vacíos a propósito: el tablero esconde lo que no
    # tiene datos, que es la verdad; un catálogo relleno a mano no lo sería.
    conceptos, localidades, plazas = [], [], []
    loc_a_plaza = []

    estatus_cat = ['VIGENTE', 'CANCELADA']

    # ---------------- construir las columnas ----------------
    cols = {k: [] for k in ['ym'] + COLUMNAS}
    anios = set()
    for d in filas:
        ini = d['empresa']
        dias = dias_desde(d['fecha'], anio_base)
        ym = (d['anio'] - anio_base) * 12 + (d['mes'] - 1)
        es_usd = (d.get('moneda') or '').upper() == 'USD'
        cols['e'].append(emp_map.get(ini, -1))
        cols['d'].append(dias if dias is not None else -99999)
        cols['ym'].append(ym)
        cols['c'].append(cli_idx_map.get(clave_cliente(d.get('contraparte')), -1))
        cols['k'].append(-1)                     # concepto: no disponible
        cols['l'].append(-1)                     # localidad: no disponible
        cols['s'].append(1 if d['clase_documento'] == 'cancelada' else 0)
        cols['o'].append(1 if d.get('estatus') == 'bost_Open' else 0)
        cols['t'].append(round(d.get('total') or 0, 2))
        cols['b'].append(round(d.get('subtotal') or 0, 2))
        # `total` está en moneda LOCAL aunque la factura sea en dólares; los
        # dólares son `total_moneda` (DocTotalFc). Ver CAMPOS_FACTURA en sap_b1.
        cols['u'].append(round(d.get('total_moneda') or 0, 2) if es_usd else 0.0)
        # Solo el tipo de cambio del dólar: el del euro (~21.5) cae dentro del
        # rango plausible y se promediaba con el del dólar sin que nada lo
        # distinguiera.
        tc = (d.get('tipo_cambio') or 0) if es_usd else 0
        cols['x'].append(round(tc, 4) if 10 <= tc <= 35 else 0.0)
        cols['f'].append(str(d.get('folio') or ''))
        cols['r'].append(d.get('referencia') or '')
        anios.add(d['anio'])

    # ---------------- agregado mensual (primer render) ----------------
    agg = defaultdict(lambda: {'n': 0, 't': 0.0, 'b': 0.0, 'u': 0.0})
    for i in range(len(filas)):
        ic = clientes_meta[cols['c'][i]]['g'] if cols['c'][i] >= 0 else 0
        k = (cols['e'][i], cols['ym'][i], ic, cols['s'][i], cols['o'][i])
        a = agg[k]
        a['n'] += 1
        a['t'] += cols['t'][i]
        a['b'] += cols['b'][i]
        a['u'] += cols['u'][i]
    # [empresa, mes, interco, cancelada, abierta, n, total, base, usd] — el
    # orden que lee aggregateMeta() en el tablero.
    agg_records = [[e, ym, ic, cn, ab, v['n'], round(v['t'], 2), round(v['b'], 2),
                    round(v['u'], 2)]
                   for (e, ym, ic, cn, ab), v in sorted(agg.items())]
    n_interco = sum(1 for i in range(len(filas))
                    if cols['c'][i] >= 0 and clientes_meta[cols['c'][i]]['g'])
    print(f'intercompañía: {n_interco:,} de {len(filas):,} '
          f'({n_interco / len(filas) * 100:.1f}%)')

    vigentes = sum(1 for s in cols['s'] if s == 0)
    meta = {
        'tipo': tipo,
        'generado': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'filas': vigentes,
        'canceladas': len(filas) - vigentes,
        'fuente': 'ERP',
        'anioBase': anio_base,
        'empresas': EMPRESAS,
        'empresasNombre': [EMPRESA_NOMBRE.get(e, e) for e in EMPRESAS],
        'clientes': clientes_meta,
        'localidades': localidades,
        'localidadPlaza': loc_a_plaza,
        'plazas': plazas,
        'conceptos': conceptos,
        'estatus': estatus_cat,
        'ymMin': min(cols['ym']),
        'ymMax': max(cols['ym']),
        'anios': sorted(anios),
        'agg': agg_records,
        'coberturaBase': len(filas),   # el ERP trae subtotal siempre
        'sinFecha': descartes.get('sin fecha', 0),
    }
    with open(R['meta'], 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, separators=(',', ':'))
    print(f'{os.path.basename(R["meta"])}: {os.path.getsize(R["meta"]) / 1024:.0f} KB')

    # ---------------- trozos por año ----------------
    por_anio = defaultdict(list)
    for i in range(len(filas)):
        por_anio[filas[i]['anio']].append(i)

    indice, total_bytes = [], 0
    for a in sorted(por_anio):
        idxs = por_anio[a]
        payload = {'anio': a, 'n': len(idxs)}
        for c in COLUMNAS:
            payload[c] = [cols[c][i] for i in idxs]
        nombre = f'rows-{a}.json'
        ruta = os.path.join(R['datos'], nombre)
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
        size = os.path.getsize(ruta)
        total_bytes += size
        indice.append({'archivo': R['prefijo'] + nombre, 'anio': a, 'n': len(idxs)})
        print(f'  {R["prefijo"]}{nombre}: {len(idxs):>7,} filas  {size / 1024 / 1024:.2f} MB')

    # Los trozos de años que ya no se publican (por retención o por cambio de
    # fuente) se borran: dejarlos haría que el tablero cargara datos viejos que
    # ya nadie recalcula, y esa es justo la clase de dato fantasma que después
    # nadie puede explicar. Solo se mira la carpeta de ESTE tipo.
    vigentes_arch = {os.path.basename(d['archivo']) for d in indice}
    for a in os.listdir(R['datos']):
        if a.startswith('rows-') and a.endswith('.json') and a not in vigentes_arch:
            os.remove(os.path.join(R['datos'], a))
            print(f'  (retirado {R["prefijo"]}{a}: fuera de lo que se publica)')

    with open(R['indice'], 'w', encoding='utf-8') as f:
        json.dump(indice, f, ensure_ascii=False)
    print(f'total: {total_bytes / 1024 / 1024:.2f} MB')
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tipo', choices=TIPOS,
                    help='solo un tipo de factura; por omisión, los dos')
    args = ap.parse_args()

    cliente, empresas_cfg, anio_minimo = cargar_configuracion()
    if cliente:
        print(f'cliente: {cliente.nombre}')
    if anio_minimo:
        print(f'retención: se publica desde {anio_minimo} '
              f'({cliente.retencion.anios} años)')
    else:
        print('retención: toda la historia disponible')

    hechos = [exportar(t, cliente, empresas_cfg, anio_minimo)
              for t in ([args.tipo] if args.tipo else TIPOS)]
    if not any(hechos):
        raise SystemExit('No se exportó ningún tipo de factura.')


if __name__ == '__main__':
    main()
