# -*- coding: utf-8 -*-
"""
===============================================================================
 GENERADOR DE KPIs FINANCIEROS
===============================================================================
Produce un Excel con la estructura de KPIs_Finanzas.xlsx, lleno con lo que ya
tenemos hoy y con los huecos marcados de lo que falta.

QUÉ SE PUEDE LLENAR HOY (sin esperar a Contabilidad):
  · "Ingresos" mensuales reales 2020-2026 — salen de la base de facturación
    consolidada que ya vive en esta misma carpeta. Son ~159 mil facturas
    sumadas una por una, no totales leídos de un Excel.
  · La pestaña "Precision_Pronostico" COMPLETA, con backtest de origen móvil
    de los 5 métodos de pronóstico, y la comparación de cuál es más preciso.

QUÉ FALTA (viene del Balance General y el Estado de Resultados):
  · Todo lo demás: costos, gastos, depreciación, activos, patrimonio, deuda,
    CxC/CxP, capex. Ver FORMATO_ESTADOS_FINANCIEROS.md.
  Cuando lleguen esos archivos, este mismo script calcula las razones
  financieras completas sin cambiar nada de su estructura.

Uso:
    python generar_kpis_finanzas.py
    python generar_kpis_finanzas.py --interco excluir   (ventas a terceros)
===============================================================================
"""
import os
import sys
import argparse
import datetime as dt

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import precision_pronostico as pp
import razones_financieras as rf
from esquema_financiero import SUPUESTOS_DEFAULT, CAMPOS_MINIMOS, TODOS_LOS_CAMPOS

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(AQUI)
# La facturación ya no viene de un Excel: sale del ERP (ver ingresos_mensuales).
SALIDA = os.path.join(AQUI, 'KPIs_Finanzas_generado.xlsx')

MESES_ES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
            'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

AZUL = 'FF1F3864'
GRIS = 'FFF2F2F2'
VERDE = 'FFC6EFCE'
AMARILLO = 'FFFFEB9C'
ROJO = 'FFFFC7CE'


def etiqueta_mes(ym):
    return f'{MESES_ES[ym % 12]}-{str(2020 + ym // 12)[2:]}'


# ---------------------------------------------------------------------------
# 1. Ingresos reales desde la base de facturación
# ---------------------------------------------------------------------------
def ingresos_mensuales(interco='todo', excluir_canceladas=True):
    """Ingresos por mes, documento por documento, desde el ERP.

    Hasta el 2026-09-25 esto leía `BASE_FACTURACION_CONSOLIDADA.xlsx`. Ese
    archivo dejó de actualizarse y vive en `legacy/`: la fuente es el ERP.

    Dos cosas cambian respecto a la versión anterior, y las dos son mejoras:

    · **Intercompañía sale del registro configurado**, no de una expresión
      regular sobre el nombre del cliente. El criterio por nombre fallaba en
      los dos sentidos sin avisar: perdía a la empresa cuando el maestro la
      escribía distinto, y podía colar a un tercero de nombre parecido. Al
      cambiar, aparecieron dos variantes de nombre que el patrón anterior no
      reconocía.

    · **Las canceladas se manejan con las tres clases del ERP.** No basta
      excluir lo marcado "CANCELADA": existe además el *documento de
      cancelación*, que trae el importe en positivo. Contarlo sumaría dos veces
      la operación que anula.

    interco: 'todo' | 'excluir' (solo terceros) | 'solo'
    """
    import json
    datos = os.path.join(BASE_DIR, 'finanzas', 'datos_erp')
    sys.path.insert(0, os.path.join(BASE_DIR, 'finanzas', 'configuracion'))

    try:
        import repositorio as repo
        cliente = repo.cliente_actual(repo.almacen_por_defecto())
        mapa_ic = cliente.mapa_interco()
        empresas = [e.iniciales for e in cliente.empresas if e.activa]
    except Exception as e:
        raise SystemExit(
            f'No se pudo leer la configuración del cliente ({type(e).__name__}: {e}).\n'
            f'Sin ella no se sabe qué empresas hay ni cuáles contrapartes son del '
            f'grupo. Revisa: python finanzas/configuracion/configurar.py --mostrar')
    if not mapa_ic and interco != 'todo':
        raise SystemExit(
            'El registro intercompañía está vacío, así que no se puede separar '
            'terceros de grupo. Llénalo con:\n'
            '   python finanzas/configuracion/configurar.py --detectar-interco')

    serie = {}
    for ini in empresas:
        ruta = os.path.join(datos, f'facturas_{ini}_venta.json')
        if not os.path.exists(ruta):
            continue
        with open(ruta, encoding='utf-8') as f:
            docs = json.load(f)

        # Un archivo con el esquema anterior no trae `clase_documento`. La
        # versión anterior de este bucle lo descartaba entero en silencio y
        # devolvía cero para esa empresa — así es como el tablero reportó
        # 4,663 M y esta función 3,038 M el mismo día, sin que ninguna de las
        # dos protestara. Se interpreta, y se avisa.
        esquema_viejo = bool(docs) and 'clase_documento' not in docs[0]
        if esquema_viejo:
            print(f'  AVISO: {ini} trae el esquema anterior; se interpreta. '
                  f'Conviene reextraerlo.')

        for d in docs:
            clase = d.get('clase_documento')
            if clase is None:
                c = d.get('cancelada')
                clase = ('normal' if c is False else
                         'cancelada' if c is True else 'documento_de_cancelacion')
            if excluir_canceladas and clase != 'normal':
                continue
            if not d.get('anio') or d['anio'] < 2020:
                continue
            rfc = (d.get('rfc') or '').strip().upper()
            cc = (d.get('contraparte_id') or '').strip().upper()
            es_ic = bool(mapa_ic.get(rfc) or mapa_ic.get(f'{ini}:{cc}'))
            if (interco == 'excluir' and es_ic) or (interco == 'solo' and not es_ic):
                continue
            ym = (d['anio'] - 2020) * 12 + (d['mes'] - 1)
            serie[ym] = serie.get(ym, 0.0) + (d.get('total') or 0.0)

    if not serie:
        raise SystemExit(
            'No hay facturas extraídas. Corre primero:\n'
            '   python actualizar.py --solo-erp')
    return [{'ym': k, 'mes_cal': k % 12, 'real': v} for k, v in sorted(serie.items())]


# ---------------------------------------------------------------------------
# 2. Escritura del Excel
# ---------------------------------------------------------------------------
def _encabezado(ws, fila, textos, ancho_titulo=None):
    for j, tx in enumerate(textos, start=1):
        c = ws.cell(fila, j, tx)
        c.font = Font(bold=True, color='FFFFFFFF', size=10, name='Calibri')
        c.fill = PatternFill('solid', fgColor=AZUL)
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    ws.freeze_panes = ws.cell(fila + 1, 1)


def _titulo(ws, fila, texto, sub=None):
    c = ws.cell(fila, 1, texto)
    c.font = Font(bold=True, size=14, color=AZUL, name='Calibri')
    if sub:
        c2 = ws.cell(fila + 1, 1, sub)
        c2.font = Font(italic=True, size=9, color='FF808080', name='Calibri')
    return fila + (2 if sub else 1)


def hoja_datos_financieros(wb, serie_ingresos):
    """Réplica de la pestaña Datos_Financieros, con Ingresos ya llenos y el
    resto marcado como pendiente de Contabilidad."""
    ws = wb.create_sheet('Datos_Financieros')
    f = _titulo(ws, 1, 'DATOS FINANCIEROS — Entradas mensuales',
                'Montos en MXN. Ingresos = facturación real consolidada (suma factura por factura). '
                'Las columnas en blanco son las que faltan del Balance y el Estado de Resultados.')
    f += 1
    ws.cell(f, 1, 'Supuesto — Tasa impositiva efectiva:').font = Font(bold=True, size=10)
    ws.cell(f, 2, SUPUESTOS_DEFAULT['tasa_impositiva']).number_format = '0.0%'
    f += 2

    cols = ['Mes', 'Ingresos', 'Costo de servicio', 'Gastos de operación', 'Deprec. y amort.',
            'EBIT', 'EBITDA', 'Gastos financieros', 'EBT', 'Impuestos', 'Utilidad neta',
            'Activos totales', 'Patrimonio', 'Deuda con costo', 'Efectivo', 'Deuda neta',
            'Capital invertido', 'Cuentas x cobrar', 'Inventarios', 'Cuentas x pagar',
            'Capex', 'Δ Capital trabajo', 'NOPAT', 'FCF']
    _encabezado(ws, f, cols)
    fila_enc = f
    f += 1
    for i, p in enumerate(serie_ingresos):
        ws.cell(f, 1, etiqueta_mes(p['ym']))
        c = ws.cell(f, 2, round(p['real'], 2))
        c.number_format = '#,##0'
        c.font = Font(name='Calibri', size=10)
        if i % 2 == 1:
            for j in range(1, len(cols) + 1):
                if not ws.cell(f, j).fill or ws.cell(f, j).fill.fgColor.rgb in (None, '00000000'):
                    ws.cell(f, j).fill = PatternFill('solid', fgColor=GRIS)
        f += 1
    ws.auto_filter.ref = f'A{fila_enc}:{get_column_letter(len(cols))}{fila_enc}'
    ws.column_dimensions['A'].width = 11
    for j in range(2, len(cols) + 1):
        ws.column_dimensions[get_column_letter(j)].width = max(13, min(22, len(cols[j - 1]) + 3))
    f += 1
    nota = ws.cell(f, 1, 'PENDIENTE: las columnas C en adelante se llenan cuando llegue el Balance '
                         'General y el Estado de Resultados mensual desde enero 2020 '
                         '(ver FORMATO_ESTADOS_FINANCIEROS.md). EBIT, EBITDA, EBT, Impuestos, '
                         'Utilidad neta, Deuda neta, Capital invertido, NOPAT y FCF se calculan solos.')
    nota.font = Font(italic=True, size=9, color='FFB00000')
    return ws


def hoja_precision(wb, resultados, serie):
    """Pestaña Precision_Pronostico con el método más preciso, más la
    comparación de los 5 métodos."""
    ws = wb.create_sheet('Precision_Pronostico')
    mejor = resultados[0]
    f = _titulo(ws, 1, 'PRECISIÓN DE PRONÓSTICO — Ingresos',
                f'Backtest de origen móvil (walk-forward): cada mes se pronostica usando solo '
                f'información anterior a ese mes. Método mostrado: {mejor["nombre"]} '
                f'(el más preciso de los 5 evaluados).')
    f += 1
    ws.cell(f, 1, 'Umbral objetivo (Verde) — MAPE ≤').font = Font(bold=True, size=10)
    ws.cell(f, 3, pp.UMBRAL_VERDE).number_format = '0.0%'
    ws.cell(f, 5, 'Umbral aceptable (Ámbar) — MAPE ≤').font = Font(bold=True, size=10)
    ws.cell(f, 7, pp.UMBRAL_AMBAR).number_format = '0.0%'
    f += 2

    cols = ['Mes', 'Pronóstico', 'Real', 'Error', 'Error abs.', 'APE', 'PE (sesgo)',
            'MAPE acum.', 'MPE acum.', 'RSFE', 'MAD', 'Tracking Signal',
            'Banda control (μ+1σ)', 'Estado']
    _encabezado(ws, f, cols)
    fila_enc = f
    f += 1
    for r in mejor['filas']:
        vals = [etiqueta_mes(r['ym']), r['pronostico'], r['real'], r['error'], r['error_abs'],
                r['ape'], r['pe'], r['mape_acum'], r['mpe_acum'], r['rsfe'], r['mad'],
                r['tracking_signal'], r['banda_control'], r['estado']]
        for j, v in enumerate(vals, start=1):
            c = ws.cell(f, j, v)
            c.font = Font(name='Calibri', size=10)
            if j in (2, 3, 4, 5, 10, 11):
                c.number_format = '#,##0'
            elif j in (6, 7, 8, 9, 13):
                c.number_format = '0.0%'
            elif j == 12:
                c.number_format = '0.00'
        estado = r['estado']
        if estado:
            color = {'Verde': VERDE, 'Amarillo': AMARILLO, 'Rojo': ROJO}[estado]
            ws.cell(f, 14).fill = PatternFill('solid', fgColor=color)
        f += 1
    ws.auto_filter.ref = f'A{fila_enc}:{get_column_letter(len(cols))}{fila_enc}'
    ws.column_dimensions['A'].width = 11
    for j in range(2, len(cols) + 1):
        ws.column_dimensions[get_column_letter(j)].width = max(13, min(20, len(cols[j - 1]) + 2))

    # --- resumen estadístico
    f += 1
    f = _titulo(ws, f, 'RESUMEN ESTADÍSTICO')
    filas_res = [
        ('MAPE global (magnitud del error)', mejor['mape_global'], '0.0%'),
        ('MPE global (sesgo: + subestima / − sobreestima)', mejor['mpe_global'], '0.0%'),
        ('Desv. estándar de APE (σ)', mejor['sigma_ape'], '0.0%'),
        ('Banda de control = μ+1σ', mejor['banda_control'], '0.0%'),
        ('% de meses dentro del umbral aceptable', mejor['pct_meses_dentro_umbral'], '0.0%'),
        ('Tracking signal final (alerta si |TS|>4)', mejor['tracking_signal_final'], '0.00'),
        ('Meses evaluados', mejor['n_meses'], '0'),
    ]
    for etq, val, fmt in filas_res:
        ws.cell(f, 1, etq).font = Font(size=10)
        c = ws.cell(f, 3, val)
        c.number_format = fmt
        c.font = Font(bold=True, size=10)
        f += 1
    f += 1
    ws.cell(f, 1, 'Lectura: ' + pp.interpretar(mejor)).font = Font(italic=True, size=10, color=AZUL)
    ws.cell(f, 1).alignment = Alignment(wrap_text=True, vertical='top')
    ws.merge_cells(start_row=f, start_column=1, end_row=f + 2, end_column=10)

    # --- comparación de métodos
    f += 4
    f = _titulo(ws, f, 'COMPARACIÓN DE MÉTODOS',
                'Mismo backtest para los 5 métodos. El de menor MAPE es el que mejor predice '
                'esta operación; el MPE dice si además se equivoca siempre hacia el mismo lado.')
    _encabezado(ws, f, ['Método', 'MAPE', 'MPE (sesgo)', 'σ APE', 'Banda μ+1σ',
                        '% meses aceptables', 'Tracking signal', 'Meses'])
    f += 1
    for k, r in enumerate(resultados):
        vals = [r['nombre'], r['mape_global'], r['mpe_global'], r['sigma_ape'], r['banda_control'],
                r['pct_meses_dentro_umbral'], r['tracking_signal_final'], r['n_meses']]
        for j, v in enumerate(vals, start=1):
            c = ws.cell(f, j, v)
            c.font = Font(name='Calibri', size=10, bold=(k == 0))
            if j in (2, 3, 4, 5, 6):
                c.number_format = '0.0%'
            elif j == 7:
                c.number_format = '0.00'
        if k == 0:
            for j in range(1, 9):
                ws.cell(f, j).fill = PatternFill('solid', fgColor=VERDE)
        f += 1
    ws.column_dimensions['A'].width = 38
    return ws


def hoja_razones(wb, filas_derivadas):
    """Razones financieras mensuales. Si aún no hay Balance/ER, deja la hoja
    con el catálogo de razones y sus metas, para que se vea qué va a salir."""
    ws = wb.create_sheet('Razones_Financieras')
    f = _titulo(ws, 1, 'RAZONES FINANCIERAS',
                'Se calculan en automático en cuanto lleguen el Balance y el Estado de Resultados. '
                'Metas tomadas del Diccionario_KPIs de KPIs_Finanzas.xlsx.')
    f += 1
    if not filas_derivadas:
        _encabezado(ws, f, ['Razón', 'Fórmula', 'Unidad', 'Meta', 'Requiere'])
        f += 1
        catalogo = [
            ('Margen EBITDA', 'EBITDA ÷ Ingresos', '%', 0.19, 'ER'),
            ('Margen EBIT', 'EBIT ÷ Ingresos', '%', 0.13, 'ER'),
            ('Margen neto', 'Utilidad neta ÷ Ingresos', '%', None, 'ER'),
            ('Margen FCF', 'FCF ÷ Ingresos', '%', 0.03, 'ER + Flujo'),
            ('ROE', 'Utilidad neta anualizada ÷ Patrimonio promedio', '%', 0.18, 'ER + BG'),
            ('ROA', 'Utilidad neta anualizada ÷ Activos promedio', '%', None, 'ER + BG'),
            ('ROIC', 'NOPAT anualizado ÷ Capital invertido promedio', '%', 0.13, 'ER + BG'),
            ('WACC', 'wE·Ke + wD·Kd·(1−t); Ke = Rf + β·ERP', '%', 0.11, 'BG + supuestos'),
            ('Spread ROIC−WACC', 'ROIC − WACC', 'pp', 0.0, 'ER + BG'),
            ('EVA', '(ROIC − WACC) × Capital invertido', 'MXN', None, 'ER + BG'),
            ('DSO', 'CxC ÷ Ventas × 365', 'días', 55, 'BG + ER'),
            ('DIO', 'Inventarios ÷ Costo × 365', 'días', None, 'BG + ER'),
            ('DPO', 'CxP ÷ Costo × 365', 'días', 40, 'BG + ER'),
            ('CCC', 'DSO + DIO − DPO', 'días', 30, 'BG + ER'),
            ('CTN / Ventas', '(CxC + Inv − CxP) ÷ Ventas', '%', 0.18, 'BG + ER'),
            ('Deuda Neta / EBITDA', '(Deuda con costo − Efectivo) ÷ EBITDA anualizado', 'x', 3.0, 'BG + ER'),
            ('D/E', 'Deuda con costo ÷ Patrimonio', 'x', 1.5, 'BG'),
            ('Cobertura de intereses', 'EBIT ÷ Gastos financieros', 'x', None, 'ER'),
            ('Costo de deuda efectivo', 'Gastos financieros × 12 ÷ Deuda', '%', 0.11, 'ER + BG'),
            ('Tasa impositiva efectiva', 'Impuestos ÷ EBT', '%', 0.30, 'ER'),
            ('Rotación de activos', 'Ventas anualizadas ÷ Activos', 'x', 1.2, 'ER + BG'),
            ('Razón circulante', 'Activo circulante ÷ Pasivo circulante', 'x', None, 'BG (circulantes)'),
            ('Prueba ácida', '(Activo circulante − Inventarios) ÷ Pasivo circulante', 'x', None, 'BG (circulantes)'),
            ('Razón de efectivo', 'Efectivo ÷ Pasivo circulante', 'x', None, 'BG (circulantes)'),
            ('DuPont 5 factores', 'Carga fiscal × carga intereses × margen EBIT × rotación × apalancamiento',
             '%', None, 'ER + BG'),
        ]
        for nombre, formula, unidad, meta, req in catalogo:
            ws.cell(f, 1, nombre).font = Font(size=10, bold=True)
            ws.cell(f, 2, formula).font = Font(size=10)
            ws.cell(f, 3, unidad).font = Font(size=10)
            c = ws.cell(f, 4, meta)
            if meta is not None:
                c.number_format = '0.0%' if unidad == '%' else '0.00'
            ws.cell(f, 5, req).font = Font(size=10, italic=True, color='FF808080')
            f += 1
        ws.column_dimensions['A'].width = 26
        ws.column_dimensions['B'].width = 62
        ws.column_dimensions['C'].width = 8
        ws.column_dimensions['D'].width = 10
        ws.column_dimensions['E'].width = 20
    return ws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--interco', choices=['todo', 'excluir', 'solo'], default='todo',
                    help="qué facturación cuenta como Ingresos (default: todo)")
    ap.add_argument('--min-historia', type=int, default=12,
                    help='meses mínimos antes del primer pronóstico del backtest')
    args = ap.parse_args()

    print('=== 1/3 — Ingresos mensuales desde la base de facturación ===')
    serie = ingresos_mensuales(interco=args.interco)
    print(f'  {len(serie)} meses, de {etiqueta_mes(serie[0]["ym"])} a {etiqueta_mes(serie[-1]["ym"])}')
    print(f'  total del periodo: ${sum(p["real"] for p in serie):,.0f} MXN')

    print('\n=== 2/3 — Backtest de los 5 métodos de pronóstico ===')
    resultados = pp.comparar_metodos(serie, min_historia=args.min_historia)
    print(f'  {"método":<40} {"MAPE":>8} {"MPE":>8} {"TS":>7}')
    for r in resultados:
        print(f'  {r["nombre"]:<40} {r["mape_global"]:>7.1%} {r["mpe_global"]:>+7.1%} '
              f'{r["tracking_signal_final"]:>7.1f}')
    print(f'\n  Mejor: {resultados[0]["nombre"]}')
    print(f'  {pp.interpretar(resultados[0])}')

    print('\n=== 3/3 — Escribiendo Excel ===')
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    hoja_datos_financieros(wb, serie)
    hoja_precision(wb, resultados, serie)
    hoja_razones(wb, [])
    wb.save(SALIDA)
    print(f'  guardado: {SALIDA}')
    print('\nListo. La pestaña Precision_Pronostico ya está completa con datos reales.')
    print('Datos_Financieros tiene Ingresos reales; el resto espera Balance y Estado de Resultados.')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
