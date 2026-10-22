# -*- coding: utf-8 -*-
"""
===============================================================================
 EXTRACCIÓN DE FACTURACIÓN DESDE EL ERP — ventas y compras, toda la historia
===============================================================================
PARA QUÉ
--------
Baja las cabeceras de todas las facturas de venta y de compra de cada empresa,
desde el primer documento que el ERP tenga. No hay límite de año: cuánta
historia se PUBLICA lo decide la retención del cliente, más adelante en el
pipeline; aquí se trae todo lo que existe.

LO QUE HAY QUE TENER EN CUENTA AL LEER EL RESULTADO
---------------------------------------------------
 1. **Las facturas canceladas.** El ERP las conserva, marcadas, y además emite
    un documento de cancelación por cada una (ver CANCEL_STATUS en sap_b1).
    La extracción las trae SIEMPRE — filtrarlas aquí escondería la decisión.
 2. **Hay documentos con `Cancelled` nulo.** No se asumen vigentes: son los
    documentos de cancelación, y se clasifican como tales.
 3. **Cada importe viene en dos monedas:** la local (`total`) y la del
    documento (`total_moneda`, los dólares de una factura en USD). Ninguna se
    calcula a partir de la otra.
 4. **Una empresa sin ERP configurado no se extrae.** Se da de alta con
    configurar.py --agregar-empresa.

CACHÉ
-----
Las cabeceras se guardan en `datos_erp/facturas_<EMPRESA>_<tipo>.json`, y todo
lo demás del pipeline lee de ahí sin volver a molestar al servidor.

    python extraer_facturacion.py --todas            # todas las empresas
    python extraer_facturacion.py --empresa NG       # una
    python extraer_facturacion.py --empresa NCS --tipo compra
===============================================================================
"""
import os
import sys
import json
import argparse
import collections

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.dirname(AQUI))

import sap_b1

SALIDA = os.path.join(os.path.dirname(AQUI), 'datos_erp')


def _ruta(empresa, tipo):
    return os.path.join(SALIDA, f'facturas_{empresa}_{tipo}.json')


def extraer(empresa, tipos=('venta', 'compra')):
    os.makedirs(SALIDA, exist_ok=True)
    resumen = {}
    with sap_b1.SesionSAP(empresa, timeout=300) as ses:
        for tipo in tipos:
            print(f'  {empresa} {tipo}: descargando cabeceras...', flush=True)
            filas = sap_b1.extraer_facturas(ses, tipo)
            with open(_ruta(empresa, tipo), 'w', encoding='utf-8') as f:
                json.dump(filas, f, ensure_ascii=False, separators=(',', ':'))
            c = collections.Counter(x['clase_documento'] for x in filas)
            print(f"     {len(filas):,} documentos  "
                  f"({c['normal']:,} normales, {c['cancelada']:,} canceladas, "
                  f"{c['documento_de_cancelacion']:,} docs. de cancelación)", flush=True)
            resumen[tipo] = len(filas)
    return resumen


def cargar(empresa, tipo):
    """Lee las facturas guardadas, tolerando el esquema anterior.

    Los archivos extraídos antes de descubrir `CancelStatus` traen `cancelada`
    con tres valores (True/False/None) en vez de `clase_documento`. La
    equivalencia se verificó exacta contra 29,630 documentos de NCS:
    tNO↔csNo, tYES↔csYes, None↔csCancellation. Se convierte al leer en lugar
    de obligar a rebajar todo, pero la extracción nueva sí guarda el campo
    explícito: deducir está bien para lo ya descargado, no para lo que viene.

    `total_moneda` (los dólares de una factura en USD) NO se deduce: el ERP lo
    tiene (DocTotalFc) y se extrae. Un archivo que no lo trae se queda sin él,
    y quien lo lea avisa que hay que reextraer — un importe calculado aquí se
    vería idéntico al de SAP sin serlo.
    """
    try:
        with open(_ruta(empresa, tipo), encoding='utf-8') as f:
            filas = json.load(f)
    except FileNotFoundError:
        return []
    for f in filas:
        if 'clase_documento' not in f:
            c = f.get('cancelada')
            f['clase_documento'] = ('normal' if c is False else
                                    'cancelada' if c is True else
                                    'documento_de_cancelacion')
    return filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--empresa')
    ap.add_argument('--todas', action='store_true')
    ap.add_argument('--tipo', choices=('venta', 'compra'),
                    help='solo un tipo de factura; por omisión, los dos')
    args = ap.parse_args()

    tipos = (args.tipo,) if args.tipo else ('venta', 'compra')
    empresas = ([args.empresa.upper()] if args.empresa
                else sap_b1.empresas_con_erp() if args.todas
                else sap_b1.empresas_con_erp()[:1])
    # UNA EMPRESA QUE FALLA SE DICE CON EL CÓDIGO DE SALIDA, no solo en
    # pantalla. Se sigue con las demás —no hay razón para perderlas—, pero al
    # final se sale con error. Antes salía con 0: una caída de la VPN a la mitad
    # de las compras de NCS dejó el archivo de un mes antes, y actualizar.py
    # siguió construyendo y publicando con él sin enterarse.
    fallidas = []
    for ini in empresas:
        try:
            extraer(ini, tipos)
        except Exception as e:
            fallidas.append(ini)
            print(f'  ERROR en {ini}: {type(e).__name__}: {e}', flush=True)
    sin_erp = sap_b1.empresas_sin_erp()
    if sin_erp:
        print(f'\nNota: {", ".join(sin_erp)} no tiene(n) ERP configurado '
              f'todavía; se dan de alta con configurar.py --agregar-empresa.')
    if fallidas:
        raise SystemExit(f'\nLa extracción falló en: {", ".join(fallidas)}. Sus '
                         f'archivos conservan la extracción anterior.')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
