# -*- coding: utf-8 -*-
"""
===============================================================================
 ESQUEMA FINANCIERO — el contrato de datos del módulo de finanzas
===============================================================================
Este archivo define, en un solo lugar, QUÉ datos se necesitan del Balance
General y del Estado de Resultados para poder calcular todo lo demás
(razones financieras, WACC, EVA, y las pestañas Datos_Financieros y
Precision_Pronostico de KPIs_Finanzas.xlsx).

Está alineado columna por columna con la pestaña "Datos_Financieros" de
KPIs_Finanzas.xlsx, para que la salida de este módulo se pueda pegar ahí
sin traducir nada.

IMPORTANTE — dos tipos de campo:
  · CAPTURADO: viene del Balance o del Estado de Resultados. Es lo único que
    hay que conseguir del área contable.
  · DERIVADO: NO se captura, se calcula aquí. Si el archivo de origen ya trae
    el valor, se usa solo para validar contra el calculado (y avisar si no
    cuadra), nunca para sustituirlo. Misma filosofía que la regla dura del
    tablero de facturación: los totales se calculan, no se leen.

UNIDADES: todos los montos en PESOS (MXN). El archivo KPIs_Finanzas.xlsx
trabaja en miles ('000); la conversión se hace al exportar, no aquí, para que
los cálculos internos nunca dependan de la escala de presentación.
===============================================================================
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Campo:
    clave: str            # nombre interno, estable, sin acentos
    etiqueta: str         # nombre como aparece en KPIs_Finanzas.xlsx
    origen: str           # 'ER' (Estado de Resultados) | 'BG' (Balance) | 'FLUJO' | 'SUPUESTO' | 'DERIVADO'
    unidad: str           # 'MXN' | '%' | 'x' | 'dias'
    formula: Optional[str] = None   # solo para DERIVADO: cómo se calcula
    nota: str = ''


# --- Estado de Resultados (mensual) ------------------------------------------
ESTADO_RESULTADOS = [
    Campo('ingresos', 'Ingresos', 'ER', 'MXN',
          nota='Ventas netas del mes. Puede venir de la base de facturación '
               '(ya la tenemos 2020-2026) o del ER contable — ver nota de conciliación abajo.'),
    Campo('costo_servicio', 'Costo de servicio', 'ER', 'MXN',
          nota='Costo directo de operación (fletes, maniobras, personal operativo).'),
    Campo('gastos_operacion', 'Gastos de operación', 'ER', 'MXN',
          nota='Gastos de administración y venta, SIN depreciación.'),
    Campo('depreciacion', 'Deprec. y amort.', 'ER', 'MXN',
          nota='Se separa porque entra y sale: baja del EBIT y se suma de vuelta en EBITDA y FCF.'),
    Campo('gastos_financieros', 'Gastos financieros', 'ER', 'MXN',
          nota='Intereses pagados. Sin esto no hay cobertura de intereses ni costo de deuda efectivo.'),
    Campo('ebit', 'EBIT', 'DERIVADO', 'MXN',
          formula='ingresos - costo_servicio - gastos_operacion - depreciacion'),
    Campo('ebitda', 'EBITDA', 'DERIVADO', 'MXN', formula='ebit + depreciacion'),
    Campo('ebt', 'EBT', 'DERIVADO', 'MXN', formula='ebit - gastos_financieros'),
    Campo('impuestos', 'Impuestos', 'DERIVADO', 'MXN', formula='ebt * tasa_impositiva',
          nota='Si el ER trae el impuesto real, se usa ese y se recalcula la tasa efectiva.'),
    Campo('utilidad_neta', 'Utilidad neta', 'DERIVADO', 'MXN', formula='ebt - impuestos'),
]

# --- Balance General (saldo a fin de mes) ------------------------------------
BALANCE = [
    Campo('activos_totales', 'Activos totales', 'BG', 'MXN'),
    Campo('patrimonio', 'Patrimonio', 'BG', 'MXN', nota='Capital contable total.'),
    Campo('deuda_con_costo', 'Deuda con costo', 'BG', 'MXN',
          nota='Solo pasivo financiero (bancos, arrendamiento financiero, bursátil). '
               'NO incluye proveedores ni impuestos por pagar — esa distinción es la que '
               'hace creíbles al apalancamiento y al WACC.'),
    Campo('efectivo', 'Efectivo', 'BG', 'MXN', nota='Efectivo y equivalentes.'),
    Campo('cuentas_x_cobrar', 'Cuentas x cobrar', 'BG', 'MXN'),
    Campo('inventarios', 'Inventarios', 'BG', 'MXN',
          nota='En una operación logística suele ser chico o cero; se conserva para el CCC.'),
    Campo('cuentas_x_pagar', 'Cuentas x pagar', 'BG', 'MXN', nota='Proveedores.'),
    Campo('deuda_neta', 'Deuda neta', 'DERIVADO', 'MXN', formula='deuda_con_costo - efectivo'),
    Campo('capital_invertido', 'Capital invertido', 'DERIVADO', 'MXN',
          formula='patrimonio + deuda_neta',
          nota='Base del ROIC. Definición usada por KPIs_Finanzas.xlsx.'),
    # Deseables pero opcionales: habilitan razones de liquidez que hoy no están en el archivo
    Campo('activo_circulante', 'Activo circulante', 'BG', 'MXN',
          nota='OPCIONAL pero muy recomendable: sin esto no hay razón circulante ni prueba ácida.'),
    Campo('pasivo_circulante', 'Pasivo circulante', 'BG', 'MXN',
          nota='OPCIONAL pero muy recomendable: mismo caso.'),
    Campo('pasivos_totales', 'Pasivos totales', 'BG', 'MXN',
          nota='OPCIONAL: habilita razón de deuda y comprobación activos = pasivos + capital.'),
]

# --- Flujo ---------------------------------------------------------------------
FLUJO = [
    Campo('capex', 'Capex', 'FLUJO', 'MXN', nota='Inversión en activo fijo del mes.'),
    Campo('delta_capital_trabajo', 'Δ Capital trabajo', 'FLUJO', 'MXN',
          nota='Cambio del capital de trabajo. Si no viene, se estima como el cambio de '
               '(CxC + Inventarios − CxP) contra el mes anterior.'),
    Campo('nopat', 'NOPAT', 'DERIVADO', 'MXN', formula='ebit * (1 - tasa_impositiva)'),
    Campo('fcf', 'FCF', 'DERIVADO', 'MXN', formula='nopat + depreciacion - capex - delta_capital_trabajo'),
]

# --- Supuestos de costo de capital (WACC) --------------------------------------
WACC_SUPUESTOS = [
    Campo('tasa_impositiva', 'Tasa impositiva efectiva', 'SUPUESTO', '%',
          nota='Default 0.30 (tasa ISR México). Si el ER trae impuestos reales se calcula la efectiva.'),
    Campo('rf', 'Rf', 'SUPUESTO', '%', nota='Tasa libre de riesgo (CETES/bono M a 10 años).'),
    Campo('beta', 'Beta', 'SUPUESTO', 'x', nota='Beta apalancada del sector transporte/logística.'),
    Campo('erp', 'ERP', 'SUPUESTO', '%', nota='Prima de riesgo de mercado.'),
    Campo('kd', 'Kd (antes imp.)', 'SUPUESTO', '%', nota='Costo de deuda antes de impuestos.'),
    Campo('ke', 'Ke', 'DERIVADO', '%', formula='rf + beta * erp', nota='CAPM.'),
    Campo('wacc', 'WACC', 'DERIVADO', '%',
          formula='wE*ke + wD*kd*(1-tasa_impositiva), con wE=patrimonio/(patrimonio+deuda_con_costo)'),
]

TODOS_LOS_CAMPOS = ESTADO_RESULTADOS + BALANCE + FLUJO + WACC_SUPUESTOS

# Lo mínimo indispensable: sin esto no se puede calcular prácticamente nada.
CAMPOS_MINIMOS = [
    'ingresos', 'costo_servicio', 'gastos_operacion', 'depreciacion', 'gastos_financieros',
    'activos_totales', 'patrimonio', 'deuda_con_costo', 'efectivo',
    'cuentas_x_cobrar', 'cuentas_x_pagar',
]

SUPUESTOS_DEFAULT = {
    'tasa_impositiva': 0.30,
    'rf': 0.095,
    'beta': 0.90,
    'erp': 0.06,
    'kd': 0.11,
}


def campos_capturados():
    """Los campos que SÍ hay que conseguir del área contable."""
    return [c for c in TODOS_LOS_CAMPOS if c.origen in ('ER', 'BG', 'FLUJO')]


def campos_derivados():
    return [c for c in TODOS_LOS_CAMPOS if c.origen == 'DERIVADO']


def validar_mes(fila, estricto=False):
    """Revisa una fila mensual (dict clave->valor). Regresa lista de avisos.
    No corrige nada: solo señala. Quien llama decide si aborta."""
    avisos = []
    for clave in CAMPOS_MINIMOS:
        if fila.get(clave) is None:
            avisos.append(f'falta campo mínimo: {clave}')
    # coherencia contable básica
    act = fila.get('activos_totales')
    pas = fila.get('pasivos_totales')
    pat = fila.get('patrimonio')
    if act is not None and pas is not None and pat is not None:
        desc = abs(act - (pas + pat))
        if desc > max(1.0, abs(act) * 0.005):
            avisos.append(f'el balance no cuadra: activos ({act:,.0f}) != pasivos + capital '
                          f'({pas + pat:,.0f}), diferencia {desc:,.0f}')
    if fila.get('deuda_con_costo') is not None and fila.get('pasivos_totales') is not None:
        if fila['deuda_con_costo'] > fila['pasivos_totales']:
            avisos.append('deuda con costo > pasivos totales: revisar que no incluya proveedores')
    for clave in ('ingresos', 'activos_totales', 'patrimonio'):
        v = fila.get(clave)
        if v is not None and v < 0:
            avisos.append(f'{clave} es negativo ({v:,.0f}) — posible signo invertido')
    if estricto and avisos:
        raise ValueError('La fila no pasó validación:\n  - ' + '\n  - '.join(avisos))
    return avisos


def imprimir_formato_requerido():
    """Imprime, en texto plano, lo que hay que pedirle a Contabilidad."""
    print('=' * 78)
    print(' DATOS REQUERIDOS POR MES (enero 2020 en adelante)')
    print('=' * 78)
    for grupo, titulo in ((ESTADO_RESULTADOS, 'ESTADO DE RESULTADOS'),
                          (BALANCE, 'BALANCE GENERAL (saldo a fin de mes)'),
                          (FLUJO, 'FLUJO')):
        print(f'\n{titulo}')
        for c in grupo:
            if c.origen == 'DERIVADO':
                print(f'   (se calcula)  {c.etiqueta:<24} = {c.formula}')
            else:
                marca = '*' if c.clave in CAMPOS_MINIMOS else ' '
                print(f'  {marca} CAPTURAR    {c.etiqueta:<24} [{c.unidad}] {c.nota}')
    print('\n  * = mínimo indispensable')


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    imprimir_formato_requerido()
