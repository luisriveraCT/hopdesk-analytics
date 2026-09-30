# -*- coding: utf-8 -*-
"""
===============================================================================
 PREPARA LOS DATOS DEL TABLERO — desde el ERP
===============================================================================
Lee las facturas extraídas del ERP (`finanzas/datos_erp/facturas_*_venta.json`)
y produce lo que consume el tablero:

  meta.json            diccionarios + agregado mensual (se incrusta en el HTML)
  data/rows-YYYY.json  detalle fila por fila, columnar, por año
  indice.json          qué archivos hay y cuántas filas trae cada uno

CAMBIO DE FUENTE (2026-09-25)
----------------------------
Hasta esta fecha leía `BASE_FACTURACION_CONSOLIDADA.xlsx`, armado a partir de
~400 hojas de Excel. Ese archivo ya no se actualiza: la auditoría del
2026-09-25 mostró que el ERP es una fuente estrictamente mejor —218,808
facturas de venta desde 2013 contra 159,123 desde 2020— y que donde ambas
cubrían lo mismo coincidían al centavo. El consolidador está en `legacy/`.

TRES COSAS QUE CAMBIAN Y HAY QUE SABER AL LEER EL TABLERO
---------------------------------------------------------
 1. **Las canceladas se manejan distinto, y bien.** El ERP guarda TRES clases de
    documento: `normal`, `cancelada`, y `documento_de_cancelacion` —este último
    es el que anula a una cancelada, y trae el importe en POSITIVO. Sumar todo
    cuenta tres veces la misma operación. Aquí solo entran los `normal`, y las
    otras dos clases se reportan al final para que se vean.

 2. **La base sin IVA ahora está completa.** El Excel solo la traía en el 29% de
    las filas (el resto había que inferirla de componentes); el ERP da el
    subtotal en todas. Deja de existir el concepto de "cobertura de base".

 3. **Concepto y Localidad ya no vienen.** En el ERP esos datos viven en las
    LÍNEAS del documento, no en la cabecera, y bajar las líneas de 218 mil
    facturas multiplica el volumen por un orden de magnitud. Los catálogos
    quedan vacíos y sus filtros sin opciones —visiblemente vacíos, no
    inventados—. Si se necesitan, es una extracción adicional, no un parche
    aquí.

NADA CABLEADO
-------------
La lista de empresas, sus nombres y la retención salen de la configuración del
cliente (`finanzas/configuracion/`), no de constantes en este archivo. Un
cliente con otras empresas —o Networks el día que dé de alta Paragon— no
requiere tocar este código.
===============================================================================
"""
import os
import re
import sys
import json
import math
import unicodedata
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(HERE)
FINANZAS = os.path.join(BASE_DIR, 'finanzas')
DATOS_ERP = os.path.join(FINANZAS, 'datos_erp')
OUT_DIR = HERE
DATA_DIR = os.path.join(OUT_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

sys.path.insert(0, os.path.join(FINANZAS, 'configuracion'))

ANIO_EPOCH = 2020          # base del índice `ym` que usa el tablero

SUFIJOS_LEGALES = (
    r'\b(S\s*A\s*P\s*I|S\s*A\s*B|S\s*A|S\s*C|S\s*DE\s*R\s*L|SRL|DS)\b\s*'
    r'(DE\s*)?(C\s*V)?|(\bDE\s*C\s*V\b)|\bLLC\b|\bINC\b|\bLTD\b|\bGMBH\b|\bCORP\b'
)


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

    Se conserva del exportador anterior porque el problema no cambió: el mismo
    cliente aparece como "ACME SA DE CV", "Acme, S.A. de C.V." y "ACME" según
    quién lo capturó, y sin canonicalizar salen como tres clientes distintos.
    """
    t = norm_txt(s)
    prev = None
    while prev != t:
        prev = t
        t = re.sub(SUFIJOS_LEGALES, ' ', t)
        t = re.sub(r'\s+', ' ', t).strip()
    return t


def dias_desde_epoch(fecha_iso):
    """Días desde el 1-ene-2020. Sin pandas: son cuentas de calendario y
    arrastrar la dependencia para esto no se justifica."""
    import datetime as dt
    try:
        d = dt.date.fromisoformat(fecha_iso[:10])
    except (ValueError, TypeError):
        return None
    return (d - dt.date(ANIO_EPOCH, 1, 1)).days


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
                       if a.startswith('facturas_') and a.endswith('_venta.json')})
        return None, [(i, i) for i in inis], None


def main():
    cliente, empresas_cfg, anio_minimo = cargar_configuracion()
    if cliente:
        print(f'cliente: {cliente.nombre}')
    if anio_minimo:
        print(f'retención: se publica desde {anio_minimo} '
              f'({cliente.retencion.anios} años)')
    else:
        print('retención: toda la historia disponible')

    # Iniciales tal como las usa el tablero, en el orden de la configuración.
    EMPRESAS = [i for i, _ in empresas_cfg]
    EMPRESA_NOMBRE = dict(empresas_cfg)
    emp_map = {e: i for i, e in enumerate(EMPRESAS)}

    # ---------------- cargar las facturas del ERP ----------------
    filas, descartes = [], defaultdict(int)
    for ini in EMPRESAS:
        ruta = os.path.join(DATOS_ERP, f'facturas_{ini}_venta.json')
        if not os.path.exists(ruta):
            print(f'  {ini}: sin extracción todavía')
            continue
        with open(ruta, encoding='utf-8') as f:
            docs = json.load(f)
        # UN ARCHIVO CON EL ESQUEMA ANTERIOR SE AVISA, NO SE DISIMULA.
        # La tolerancia estaba pensada como una gentileza y por poco cuesta
        # caro: el archivo de NTS se quedó con el esquema viejo mientras los
        # otros cuatro se reextraían, el respaldo lo aceptó en silencio, y el
        # tablero mostró 4,663 M mientras el generador de KPIs —que no tiene
        # respaldo— calculaba 3,038 M. Dos números distintos para la misma
        # cosa, y ninguno de los dos se quejaba.
        if docs and 'clase_documento' not in docs[0]:
            print(f'     AVISO: {ini} trae el esquema anterior. Se interpreta, '
                  f'pero conviene reextraerlo:')
            print(f'            python finanzas/erp/extraer_facturacion.py '
                  f'--empresa {ini}')

        n_ini = 0
        for d in docs:
            clase = d.get('clase_documento')
            if clase is None:            # archivo del esquema anterior
                c = d.get('cancelada')
                clase = ('normal' if c is False else
                         'cancelada' if c is True else 'documento_de_cancelacion')
            if clase != 'normal':
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
        print(f'  {ini}: {n_ini:,} facturas vigentes')

    if not filas:
        raise SystemExit(
            'No hay facturas extraídas. Corre primero:\n'
            '   python finanzas/erp/extraer_facturacion.py --todas')

    print(f'\ntotal a publicar: {len(filas):,} facturas')
    for k, n in sorted(descartes.items(), key=lambda kv: -kv[1]):
        print(f'   descartadas por {k}: {n:,}')

    # ---------------- clientes (contrapartes) ----------------
    por_clave = defaultdict(lambda: defaultdict(int))
    for d in filas:
        k = clave_cliente(d.get('contraparte'))
        if k:
            por_clave[k][d['contraparte']] += 1

    claves = sorted(por_clave)
    cli_idx_map = {k: i for i, k in enumerate(claves)}
    # El nombre a mostrar es la variante cruda más frecuente de cada clave.
    display = {k: max(v.items(), key=lambda kv: kv[1])[0] for k, v in por_clave.items()}

    # ---------------- intercompañía ----------------
    # NO se deduce del nombre. Sale del REGISTRO INTERCOMPAÑÍA de la
    # configuración, que guarda por empresa su RFC, sus RFC alternos (el maestro
    # de socios de SAP tiene erratas reales) y sus CardCodes calificados por
    # libro. Es el mismo criterio que usa HopDesk, y lo llena solo
    # `configurar.py --detectar-interco`.
    #
    # Por qué no por nombre: falla en los dos sentidos y de forma invisible. Se
    # pierde la empresa cuando el maestro la escribió distinto, y se cuela un
    # tercero que se llame parecido. Ninguno de los dos errores salta a la
    # vista: solo mueve el porcentaje de intercompañía, que nadie puede
    # verificar de memoria.
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

    # Se resuelve por documento y se consolida por clave de cliente: una misma
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
        clientes_meta.append({'n': display[k], 'g': 1 if code else 0, 'c': code})

    # ---------------- catálogos ----------------
    # Concepto y Localidad no existen en la cabecera del documento (ver el
    # encabezado). Se dejan vacíos a propósito: un filtro sin opciones se ve
    # vacío, que es la verdad; uno relleno con un valor inventado no.
    conceptos, localidades, plazas = [], [], []
    loc_a_plaza = []

    estatus_cat = ['VIGENTE', 'CANCELADA', 'EN SAP', 'CARGA', 'OTRO']

    # ---------------- construir las columnas ----------------
    cols = {k: [] for k in 'e d ym c k l s t b u x f'.split()}
    anios = set()
    for d in filas:
        ini = d['empresa']
        dias = dias_desde_epoch(d['fecha'])
        ym = (d['anio'] - ANIO_EPOCH) * 12 + (d['mes'] - 1)
        es_usd = (d.get('moneda') or '').upper() == 'USD'
        cols['e'].append(emp_map.get(ini, -1))
        cols['d'].append(dias if dias is not None else -99999)
        cols['ym'].append(ym)
        cols['c'].append(cli_idx_map.get(clave_cliente(d.get('contraparte')), -1))
        cols['k'].append(-1)                     # concepto: no disponible
        cols['l'].append(-1)                     # localidad: no disponible
        cols['s'].append(0)                      # todas las publicadas son vigentes
        cols['t'].append(round(d.get('total') or 0, 2))
        cols['b'].append(round(d.get('subtotal') or 0, 2))
        cols['u'].append(round(d.get('total') or 0, 2) if es_usd else 0.0)
        tc = d.get('tipo_cambio') or 0
        cols['x'].append(round(tc, 4) if 10 <= tc <= 35 else 0.0)
        cols['f'].append(str(d.get('folio') or ''))
        anios.add(d['anio'])

    # ---------------- agregado mensual (primer render) ----------------
    agg = defaultdict(lambda: {'n': 0, 't': 0.0, 'b': 0.0, 'u': 0.0})
    for i in range(len(filas)):
        ic = clientes_meta[cols['c'][i]]['g'] if cols['c'][i] >= 0 else 0
        k = (cols['e'][i], cols['ym'][i], ic, 0)
        a = agg[k]
        a['n'] += 1
        a['t'] += cols['t'][i]
        a['b'] += cols['b'][i]
        a['u'] += cols['u'][i]
    agg_records = [[e, ym, ic, cn, v['n'], round(v['t'], 2), round(v['b'], 2),
                    round(v['u'], 2)]
                   for (e, ym, ic, cn), v in sorted(agg.items())]
    n_interco = sum(1 for i in range(len(filas))
                    if cols['c'][i] >= 0 and clientes_meta[cols['c'][i]]['g'])
    print(f'\nintercompañía: {n_interco:,} de {len(filas):,} '
          f'({n_interco / len(filas) * 100:.1f}%)')
    print(f'registros de agregado mensual: {len(agg_records)}')

    import datetime as dt
    meta = {
        'generado': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'filas': len(filas),
        'fuente': 'ERP',
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
    ruta_meta = os.path.join(OUT_DIR, 'meta.json')
    with open(ruta_meta, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, separators=(',', ':'))
    print(f'meta.json: {os.path.getsize(ruta_meta) / 1024:.0f} KB')

    # ---------------- chunks por año ----------------
    por_anio = defaultdict(list)
    for i in range(len(filas)):
        por_anio[filas[i]['anio']].append(i)

    indice, total_bytes = [], 0
    for a in sorted(por_anio):
        idxs = por_anio[a]
        payload = {'anio': a, 'n': len(idxs)}
        for c in 'e d c k l s t b u x f'.split():
            payload[c] = [cols[c][i] for i in idxs]
        nombre = f'rows-{a}.json'
        ruta = os.path.join(DATA_DIR, nombre)
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
        size = os.path.getsize(ruta)
        total_bytes += size
        indice.append({'archivo': nombre, 'anio': a, 'n': len(idxs)})
        print(f'  {nombre}: {len(idxs):>7,} filas  {size / 1024 / 1024:.2f} MB')

    # Los chunks de años que ya no se publican (por retención o por cambio de
    # fuente) se borran: dejarlos haría que el tablero cargara datos viejos que
    # ya nadie recalcula, y esa es justo la clase de dato fantasma que después
    # nadie puede explicar.
    vigentes = {d['archivo'] for d in indice}
    for a in os.listdir(DATA_DIR):
        if a.startswith('rows-') and a.endswith('.json') and a not in vigentes:
            os.remove(os.path.join(DATA_DIR, a))
            print(f'  (retirado {a}: fuera de lo que se publica)')

    with open(os.path.join(OUT_DIR, 'indice.json'), 'w', encoding='utf-8') as f:
        json.dump(indice, f, ensure_ascii=False)
    print(f'total: {total_bytes / 1024 / 1024:.2f} MB')


if __name__ == '__main__':
    main()
