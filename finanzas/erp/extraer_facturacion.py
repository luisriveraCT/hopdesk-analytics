# -*- coding: utf-8 -*-
"""
===============================================================================
 EXTRACCIÓN DE FACTURACIÓN DESDE EL ERP  +  AUDITORÍA CONTRA LA BASE DE EXCEL
===============================================================================
PARA QUÉ
--------
Hoy la base de facturación se arma leyendo ~400 hojas de Excel repartidas en
siete carpetas anuales, con unos 35 formatos distintos. Funciona, pero depende
de que alguien guarde el archivo del mes con la forma de siempre. SAP tiene la
misma información de origen, con más historia (desde 2013, no 2020) y sin
depender de ningún archivo.

Este módulo baja las facturas del ERP y las compara contra la base de Excel,
empresa por empresa y año por año. La comparación es el entregable, no un
extra: **antes de sustituir una fuente por otra hay que demostrar que dicen lo
mismo**, y donde no lo digan, entender por qué antes de decidir cuál manda.

LO QUE YA SE SABE Y HAY QUE TENER EN CUENTA AL LEER EL RESULTADO
---------------------------------------------------------------
 1. **PL (Paragon Logistics) no existe en SAP.** Sus 16 facturas solo están en
    el Excel. Sustituir la base completa por SAP perdería esa empresa: o se
    conserva el Excel para PL, o se le da de alta en el ERP. No hay tercera.
 2. **Las facturas canceladas.** SAP las conserva (en NG, 16 de 595) y el Excel
    aparentemente no. Sumar sin filtrarlas infla las ventas. La extracción las
    trae SIEMPRE, marcadas — filtrarlas aquí escondería la decisión.
 3. **Hay documentos con `Cancelled` nulo** (16 en NG). No se asumen vigentes:
    quedan como desconocidos y se reportan aparte.
 4. **Las iniciales no coinciden entre sistemas:** SAP usa `NRS` para Realtors
    y la facturación usaba `NR`. Ese mapeo desapareció con el Excel.
 5. **SAP arranca en 2013 y el Excel en 2020.** La comparación se limita al
    periodo común; fuera de él una diferencia no significa nada.

CACHÉ
-----
Las cabeceras se guardan en `datos_erp/facturas_<EMPRESA>_<tipo>.json`. La
auditoría se puede repetir sin volver a bajar 219,000 documentos, que es lo que
permite discutir las diferencias sin castigar al servidor cada vez.

    python extraer_facturacion.py --todas            # bajar todo (ventas y compras)
    python extraer_facturacion.py --auditar          # retirada (ver legacy/)
    python extraer_facturacion.py --empresa NG
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
# El Excel ya no se actualiza y vive en legacy/. La ruta se conserva solo para
# _auditar_historico(), que permite reproducir la comparación de aquella fecha.
# Ya no hay ninguna ruta al Excel en este archivo: el único código que lo
# abría se movió a legacy/auditoria_contra_excel.py. Ver auditar().
ANIO_COMUN_DESDE = 2020


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


def auditar():
    """RETIRADA. La comparación contra la base de Excel ya cumplió su función.

    Existió para responder una pregunta: ¿puede el ERP sustituir a los archivos
    de Excel? La respuesta fue sí, y está documentada con números en
    `legacy/README.md`. El Excel dejó de actualizarse el 2026-09-25 y vive en
    `legacy/`; compararse contra él hoy solo mediría cuánto ha avanzado el ERP
    desde esa fecha, que no le sirve a nadie.

    Se conserva la función, y no se borra el archivo de Excel, porque algún día
    alguien va a preguntar por una cifra histórica de antes del cambio. Pero
    dejarla ejecutable era dejar armada una trampa: el día que alguien la
    corriera vería "diferencias" crecientes y creería que el ERP está mal.
    """
    raise SystemExit(
        'La auditoría contra el Excel está retirada.\n\n'
        'Cumplió su función el 2026-09-25: demostró que el ERP es una fuente\n'
        'estrictamente mejor (218,808 facturas desde 2013 contra 159,123 desde\n'
        '2020) y que donde ambas coincidían, coincidían al centavo. El detalle\n'
        'está en legacy/README.md.\n\n'
        'El Excel ya no se actualiza, así que compararse contra él hoy solo\n'
        'mediría el tiempo transcurrido. Para verificar los datos del ERP usa:\n'
        '    python finanzas/verificar_cuadre.py')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--empresa')
    ap.add_argument('--todas', action='store_true')
    ap.add_argument('--auditar', action='store_true')
    ap.add_argument('--solo-ventas', action='store_true')
    args = ap.parse_args()

    if args.auditar:
        auditar()
        return

    tipos = ('venta',) if args.solo_ventas else ('venta', 'compra')
    empresas = ([args.empresa.upper()] if args.empresa
                else sap_b1.empresas_con_erp() if args.todas
                else sap_b1.empresas_con_erp()[:1])
    for ini in empresas:
        try:
            extraer(ini, tipos)
        except Exception as e:
            print(f'  ERROR en {ini}: {type(e).__name__}: {e}', flush=True)
    sin_erp = sap_b1.empresas_sin_erp()
    if sin_erp:
        print(f'\nNota: {", ".join(sin_erp)} no tiene(n) ERP configurado '
              f'todavía; se dan de alta con configurar.py --agregar-empresa.')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
