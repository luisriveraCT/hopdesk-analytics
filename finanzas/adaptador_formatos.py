# -*- coding: utf-8 -*-
"""
===============================================================================
 ADAPTADOR DE FORMATOS — que la app resuelva sola las tablas que le lleguen
===============================================================================
EL PROBLEMA REAL
----------------
Los estados financieros no llegan en un formato: llegan en muchos parecidos.
El mismo concepto aparece como "Ingresos", "Ventas netas", "Revenue", "Total
revenues" o "Ventas" según quién exportó el archivo, de qué ERP salió y en qué
idioma está configurado. Y el layout cambia: a veces los conceptos van en las
filas y los meses en las columnas, a veces al revés; a veces el encabezado está
en la fila 1 y a veces hay tres filas de logo y título encima.

Pedirle al usuario que "acomode el archivo antes de subirlo" es trasladarle a
una persona un trabajo que la máquina hace mejor y sin cansarse. Este módulo
existe para que no haya que pedirlo.

CÓMO LO RESUELVE, Y POR QUÉ ASÍ
-------------------------------
No es un mapeo fijo de nombre→campo: es un emparejamiento por evidencia, el
mismo criterio que usa `erp/clasificador_cuentas.py` para el plan de cuentas.

  · Se normaliza todo (minúsculas, sin acentos, sin puntuación), así que
    "Utilidad de Operación", "UTILIDAD DE OPERACION" y "utilidad operacion" son
    el mismo texto antes de comparar.
  · Se busca el término MÁS ESPECÍFICO que aparezca. Esto no es un detalle:
    "costo de ventas" tiene que ganarle a "ventas", y "utilidad antes de
    impuestos" a "utilidad". Un emparejador que recorre el diccionario en orden
    arbitrario acierta o falla según cómo quedó escrito el diccionario — que es
    una forma elegante de ser aleatorio.
  · La fila de encabezado se BUSCA, no se supone: se prueba cada una de las
    primeras filas y gana la que reconozca más términos. Es la misma técnica
    que ya se usó con éxito en `consolidar_facturacion.py` contra 398 hojas de
    Excel con 35 layouts distintos.
  · La orientación también se detecta: si los conceptos conocidos aparecen en
    la primera COLUMNA en vez de en la primera fila, la tabla viene transpuesta
    (que es como sale casi todo Balance General) y se voltea.

LA REGLA QUE NO SE NEGOCIA
--------------------------
Cuando dos campos canónicos empatan por la misma columna, o cuando ninguno
alcanza la confianza mínima, **no se elige**: se reporta como ambigüedad o como
no reconocido, y el campo queda vacío. Un importe puesto en el renglón
equivocado es peor que un renglón faltante, porque el faltante se ve y el
equivocado se presenta en una junta.

QUÉ HACER CUANDO ALGO NO SE RECONOCE
------------------------------------
Agregar el término a SINONIMOS y volver a correr. NO agregar una regla especial
en el código: el diccionario es el único lugar donde vive el conocimiento sobre
cómo nombra la gente las cosas, y mantenerlo así es lo que permite que un
cliente nuevo se resuelva editando datos en vez de programando.
===============================================================================
"""
import re
import sys
import unicodedata
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Sinónimos por campo canónico (las claves son las de esquema_financiero.py)
# ---------------------------------------------------------------------------
# Español e inglés en la misma lista a propósito: el idioma no es una dimensión
# del problema, es solo más vocabulario. Separarlos obligaría a detectar el
# idioma primero —un paso más que puede fallar— sin ganar nada, y rompería con
# los archivos mixtos, que en la práctica son comunes (encabezados en inglés
# del ERP, conceptos en español escritos por contabilidad).
SINONIMOS: Dict[str, List[str]] = {
    # --- Estado de Resultados ---
    'ingresos': [
        'ingresos por servicios', 'ingresos operativos', 'ventas netas',
        'total de ingresos', 'total revenues', 'net sales', 'net revenue',
        'ingresos', 'ventas', 'revenue', 'revenues', 'sales', 'turnover',
    ],
    'costo_servicio': [
        'costo de los servicios', 'costo de lo vendido', 'costo de ventas',
        'cost of goods sold', 'cost of services', 'cost of sales', 'cogs',
        'costo de servicio', 'costo', 'cost of revenue',
    ],
    'gastos_operacion': [
        'gastos de administracion y venta', 'gastos de operacion',
        'gastos generales', 'gastos de administracion', 'gastos de venta',
        'operating expenses', 'selling general and administrative', 'sg a',
        'opex', 'gastos operativos',
    ],
    'depreciacion': [
        'depreciacion y amortizacion', 'depreciacion y amortizacion del ejercicio',
        'depreciation and amortization', 'depreciation amortization',
        'depreciacion', 'amortizacion', 'depreciation', 'amortization', 'd a',
    ],
    'gastos_financieros': [
        'resultado integral de financiamiento', 'gastos financieros netos',
        'intereses pagados', 'costo integral de financiamiento',
        'interest expense', 'finance costs', 'financial expenses',
        'gastos financieros', 'intereses',
    ],
    'ebit': ['utilidad de operacion', 'resultado de operacion', 'operating income',
             'operating profit', 'ebit'],
    'ebitda': ['ebitda', 'flujo operativo'],
    'ebt': ['utilidad antes de impuestos', 'resultado antes de impuestos',
            'earnings before tax', 'income before taxes', 'ebt', 'pretax income'],
    'impuestos': ['impuesto sobre la renta', 'provision para impuestos', 'isr',
                  'income tax expense', 'income tax', 'taxes', 'impuestos'],
    'utilidad_neta': ['utilidad neta del ejercicio', 'resultado neto',
                      'utilidad del ejercicio', 'net income', 'net profit',
                      'net earnings', 'utilidad neta'],

    # --- Balance General ---
    'activos_totales': ['total de activos', 'suma del activo', 'activo total',
                        'total assets', 'activos totales', 'activo'],
    'patrimonio': ['total capital contable', 'capital contable', 'suma del capital',
                   "total stockholders equity", "shareholders equity",
                   'total equity', 'patrimonio', 'equity'],
    'deuda_con_costo': ['deuda con costo financiero', 'prestamos bancarios',
                        'deuda financiera', 'documentos por pagar',
                        'interest bearing debt', 'total debt', 'borrowings',
                        'deuda con costo', 'deuda'],
    'efectivo': ['efectivo y equivalentes de efectivo', 'caja y bancos',
                 'efectivo y equivalentes', 'cash and cash equivalents',
                 'cash equivalents', 'efectivo', 'bancos', 'cash'],
    'cuentas_x_cobrar': ['clientes y cuentas por cobrar', 'cuentas por cobrar',
                         'accounts receivable', 'trade receivables',
                         'receivables', 'clientes', 'cartera'],
    'inventarios': ['inventarios', 'existencias', 'inventory', 'inventories',
                    'stock'],
    'cuentas_x_pagar': ['proveedores y cuentas por pagar', 'cuentas por pagar',
                        'accounts payable', 'trade payables', 'payables',
                        'proveedores'],
    'activo_circulante': ['total activo circulante', 'activo circulante',
                          'activo corriente', 'total current assets',
                          'current assets'],
    'pasivo_circulante': ['total pasivo circulante', 'pasivo circulante',
                          'pasivo corriente', 'total current liabilities',
                          'current liabilities'],
    'pasivos_totales': ['total de pasivos', 'suma del pasivo', 'pasivo total',
                        'total liabilities', 'pasivos totales', 'pasivo'],

    # --- Identificación de periodo / entidad ---
    'periodo': ['periodo', 'mes', 'fecha', 'period', 'month', 'date'],
    'anio': ['anio', 'ano', 'ejercicio', 'year', 'fy'],
    'empresa': ['empresa', 'compania', 'entidad', 'razon social',
                'company', 'entity', 'legal entity'],
}

# Meses en los dos idiomas, completos y abreviados. Los encabezados de un estado
# financiero suelen ser los periodos, no los conceptos, así que reconocerlos es
# lo que permite detectar que una tabla viene transpuesta.
MESES = {}
for _i, (_es, _en) in enumerate([
        ('enero', 'january'), ('febrero', 'february'), ('marzo', 'march'),
        ('abril', 'april'), ('mayo', 'may'), ('junio', 'june'),
        ('julio', 'july'), ('agosto', 'august'), ('septiembre', 'september'),
        ('octubre', 'october'), ('noviembre', 'november'), ('diciembre', 'december')], 1):
    for _t in (_es, _en, _es[:3], _en[:3]):
        MESES[_t] = _i
MESES['sept'] = 9
MESES['setiembre'] = 9

# Confianza mínima para aceptar un emparejamiento. Un término de 3 letras que
# aparece dentro de un encabezado de 60 no es evidencia de nada.
COBERTURA_MINIMA = 0.34


def normalizar(texto) -> str:
    """Minúsculas, sin acentos, sin puntuación, espacios colapsados."""
    if texto is None:
        return ''
    t = unicodedata.normalize('NFKD', str(texto))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r'[^0-9a-zA-Z ]+', ' ', t.lower())
    return re.sub(r'\s+', ' ', t).strip()


# Los términos, precalculados y ordenados de más largo a más corto: la
# especificidad se resuelve por longitud, no por el orden en que alguien
# escribió el diccionario.
_TERMINOS: List[Tuple[str, str]] = sorted(
    ((t, clave) for clave, ts in SINONIMOS.items() for t in ts),
    key=lambda x: -len(x[0]))


def identificar_campo(encabezado) -> Tuple[Optional[str], str, float]:
    """Devuelve (clave_canonica, termino_encontrado, cobertura).

    `cobertura` es qué fracción del encabezado ocupó el término reconocido. Un
    encabezado que es exactamente "Ingresos" tiene cobertura 1.0; uno que dice
    "Ingresos por servicios prestados en el extranjero" apenas la roza — y esa
    diferencia es justo lo que distingue una columna de total de una de detalle.
    """
    norm = normalizar(encabezado)
    if not norm:
        return None, '', 0.0
    for termino, clave in _TERMINOS:
        if re.search(r'\b' + re.escape(termino) + r'\b', norm):
            return clave, termino, len(termino) / len(norm)
    return None, '', 0.0


def identificar_periodo(texto) -> Optional[Tuple[Optional[int], Optional[int]]]:
    """Reconoce 'ene-24', 'Jan 2024', '2024-01', '01/2024', 'enero de 2024'.
    Devuelve (anio, mes) con None en lo que no se pueda determinar."""
    norm = normalizar(texto)
    if not norm:
        return None
    anio = mes = None

    # 1) ¿el mes viene escrito con letras? ("ene", "enero", "Jan", "January")
    for t, n in MESES.items():
        if re.search(r'\b' + t + r'\b', norm):
            mes = n
            break

    # 2) el año de cuatro dígitos, si está
    # Sin `\b` al inicio a propósito: "FY2024" no tiene frontera de palabra
    # entre la letra y el dígito, y con \b se perdía el año por completo.
    m4 = re.search(r'(?<!\d)(19|20)\d{2}(?!\d)', norm)
    if m4:
        anio = int(m4.group(0))

    # 3) los números sueltos que queden, quitando ya el año de cuatro dígitos.
    #    Se hace sobre el texto SIN el año para no volver a leerlo como mes —
    #    el error que hacía que "feb-24" perdiera el año era manipular la
    #    cadena a ciegas en vez de descontar lo ya identificado.
    resto = norm.replace(m4.group(0), ' ') if m4 else norm
    sueltos = [int(x) for x in re.findall(r'\b\d{1,2}\b', resto)]

    if mes is not None and anio is None and sueltos:
        # "feb-24": el mes ya se conoce por su nombre, así que el número de dos
        # dígitos solo puede ser el año abreviado.
        anio = 2000 + sueltos[0] if sueltos[0] < 100 else sueltos[0]
    elif mes is None and anio is not None and sueltos:
        # "2024-01" o "01/2024": con el año fuera, el 1-12 que queda es el mes.
        for s in sueltos:
            if 1 <= s <= 12:
                mes = s
                break
    return (anio, mes) if (anio or mes) else None


def _puntuar_fila(celdas) -> int:
    """Cuántos campos canónicos distintos reconoce esta fila."""
    return len({identificar_campo(c)[0] for c in celdas} - {None})


def _puntuar_periodos(celdas) -> int:
    return sum(1 for c in celdas if identificar_periodo(c))


def analizar_tabla(filas: List[List], max_filas_encabezado: int = 12) -> Dict:
    """Analiza una tabla cruda (lista de listas, tal como sale de openpyxl o de
    `df.values.tolist()`) y decide dónde está el encabezado y cómo está
    orientada. NO convierte nada: solo informa lo que encontró, para que quien
    llama pueda revisarlo antes de confiar.

    Devuelve un dict con: fila_encabezado, orientacion, mapeo, periodos,
    no_reconocidos, ambiguos.
    """
    if not filas:
        return {'error': 'tabla vacía'}

    tope = min(max_filas_encabezado, len(filas))

    # ¿Dónde está el encabezado? Gana la fila que más campos reconozca. El
    # empate se resuelve por la primera, que es la convención razonable.
    mejor_fila, mejor_pts = 0, -1
    for i in range(tope):
        p = _puntuar_fila(filas[i])
        if p > mejor_pts:
            mejor_fila, mejor_pts = i, p

    # ¿Está transpuesta? Si la primera COLUMNA reconoce más conceptos que la
    # mejor fila, los conceptos van hacia abajo y los periodos hacia la derecha
    # — que es la forma normal de un Balance General exportado.
    primera_col = [f[0] if f else None for f in filas[:60]]
    pts_col = _puntuar_fila(primera_col)

    orientacion = 'columnas'          # conceptos en las columnas (una fila por periodo)
    if pts_col > mejor_pts:
        orientacion = 'filas'         # conceptos en las filas (una columna por periodo)

    encabezado = (primera_col if orientacion == 'filas' else filas[mejor_fila])

    mapeo, ambiguos, no_reconocidos = {}, [], []
    vistos = {}
    for idx, celda in enumerate(encabezado):
        clave, termino, cob = identificar_campo(celda)
        if clave is None or cob < COBERTURA_MINIMA:
            if normalizar(celda):
                no_reconocidos.append({'pos': idx, 'texto': str(celda)[:60],
                                       'cobertura': round(cob, 2)})
            continue
        if clave in vistos:
            # Dos posiciones reclaman el mismo campo. Gana la de mayor
            # cobertura, pero AMBAS se reportan: normalmente significa que una
            # es el total y otra un subtotal, y quien conoce el archivo debe
            # confirmarlo. Resolverlo en silencio es cómo se suma dos veces
            # el mismo importe.
            ambiguos.append({'campo': clave, 'posiciones': [vistos[clave]['pos'], idx],
                             'textos': [vistos[clave]['texto'], str(celda)[:60]]})
            if cob <= vistos[clave]['cobertura']:
                continue
        vistos[clave] = {'pos': idx, 'texto': str(celda)[:60], 'cobertura': cob,
                         'termino': termino}
        mapeo[clave] = vistos[clave]

    # Los periodos viven en el eje contrario al de los conceptos. Ojo: cuando
    # la tabla está transpuesta, la fila de periodos NO es la que más conceptos
    # reconoce (esa es una fila de datos como "Cost of sales"), sino la que más
    # FECHAS reconoce. Buscarla con el criterio equivocado devolvía cero
    # periodos sin error visible.
    if orientacion == 'filas':
        fila_per = max(range(tope), key=lambda i: _puntuar_periodos(filas[i]))
        eje_periodos = filas[fila_per]
    else:
        eje_periodos = [f[0] if f else None for f in filas[mejor_fila + 1:]]
    periodos = []
    for idx, celda in enumerate(eje_periodos):
        p = identificar_periodo(celda)
        if p:
            periodos.append({'pos': idx, 'texto': str(celda)[:40],
                             'anio': p[0], 'mes': p[1]})

    return {'fila_encabezado': mejor_fila, 'orientacion': orientacion,
            'mapeo': mapeo, 'periodos': periodos,
            'no_reconocidos': no_reconocidos, 'ambiguos': ambiguos,
            'campos_reconocidos': len(mapeo)}


def imprimir_analisis(a: Dict) -> None:
    if 'error' in a:
        print(f"  ERROR: {a['error']}")
        return
    print(f"  orientación: conceptos en {a['orientacion']} · "
          f"encabezado en la fila {a['fila_encabezado'] + 1} · "
          f"{a['campos_reconocidos']} campo(s) reconocido(s)")
    for clave, m in sorted(a['mapeo'].items()):
        print(f"     {clave:<20} <- pos {m['pos']:>2}  \"{m['texto']}\"  "
              f"(por \"{m['termino']}\", {m['cobertura']:.0%})")
    if a['periodos']:
        p0, p1 = a['periodos'][0], a['periodos'][-1]
        print(f"     {len(a['periodos'])} periodo(s): "
              f"{p0['anio']}-{p0['mes']} … {p1['anio']}-{p1['mes']}")
    for amb in a['ambiguos']:
        print(f"     AMBIGUO {amb['campo']}: {amb['textos']} — confirmar cuál es")
    if a['no_reconocidos']:
        print(f"     {len(a['no_reconocidos'])} encabezado(s) sin reconocer "
              f"(se ignoran, no se adivinan):")
        for n in a['no_reconocidos'][:6]:
            print(f"        pos {n['pos']:>2}  \"{n['texto']}\"")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    # Tres tablas del mismo estado, escritas como las escribiría gente distinta.
    # Si el adaptador sirve, las tres producen el mismo mapeo.
    casos = {
        'español, encabezado en la fila 3, conceptos en columnas': [
            ['NETWORKS GROUP, S.A. DE C.V.', None, None, None],
            ['Estado de Resultados', None, None, None],
            ['Periodo', 'Ingresos', 'Costo de ventas', 'Utilidad de operación'],
            ['ene-24', 1810652, 0, 281505],
            ['feb-24', 1556772, 0, -222243],
        ],
        'inglés, encabezado en la fila 1': [
            ['Month', 'Total revenues', 'Cost of sales', 'Operating income'],
            ['Jan 2024', 1810652, 0, 281505],
            ['Feb 2024', 1556772, 0, -222243],
        ],
        'transpuesta (conceptos en filas), mixta ES/EN': [
            ['Concepto', 'enero 2024', 'febrero 2024', 'marzo 2024'],
            ['Ventas netas', 1810652, 1556772, 2137761],
            ['Cost of sales', 0, 0, 0],
            ['Utilidad de operación', 281505, -222243, 520120],
            ['Total assets', 591817, 701777, 923937],
        ],
    }
    for nombre, filas in casos.items():
        print(f'\n--- {nombre} ---')
        imprimir_analisis(analizar_tabla(filas))
