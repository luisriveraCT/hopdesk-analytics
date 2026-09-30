# -*- coding: utf-8 -*-
"""
===============================================================================
 NORMAS CONTABLES — qué marco aplica y qué decide cada uno
===============================================================================
Un estado financiero no se arma igual en todas partes. Qué entra al EBITDA, si
la utilidad de operación se presenta como renglón, cómo se clasifican los
intereses pagados: son decisiones de NORMA, no de programación.

Este archivo es el registro de esas decisiones. El cliente dice qué norma
sigue; el código pregunta aquí y nunca decide por su cuenta.

POR QUÉ ES CONFIGURACIÓN Y NO UNA CONSTANTE
--------------------------------------------
Networks reporta bajo **IFRS en cumplimiento con las NIF** mexicanas. El
siguiente cliente puede reportar bajo US GAAP, o bajo NIF sin IFRS, o tener una
subsidiaria en otro país con otra norma. Cablear "así se hace" en el código
significa que ese cliente necesita un programador para algo que es una decisión
de su contador.

La norma vive en la configuración del cliente (`Cliente.normas`). El día que
haya carpetas de cliente con su archivo de políticas, este registro es lo que
ese archivo llena.

CÓMO SE AGREGA UNA NORMA
------------------------
Una entrada más en `NORMAS`, con sus políticas. Nada más. Si una política nueva
hace falta, se agrega a TODAS las normas con su valor correcto en cada una —
nunca con un valor por defecto que "seguramente aplica", porque un default
silencioso es exactamente cómo una norma ajena se cuela en un estado.
===============================================================================
"""
from typing import Dict, List

# ---------------------------------------------------------------------------
# Las políticas que hoy consulta el código
# ---------------------------------------------------------------------------
# Cada una lleva quién la usa. Si nadie la usa, no debe estar aquí: una política
# declarada y no consultada da una sensación de control que no corresponde a
# nada — el mismo error que tenían los 16 permisos sin verificar de HopDesk.
POLITICAS: Dict[str, str] = {
    'dya_para_ebitda': (
        'Qué conceptos se suman de vuelta al EBIT para llegar al EBITDA. '
        'Lo consulta mapeo_kpis.depreciacion_del_periodo().'),
    'presenta_utilidad_operacion': (
        'Si el Estado de Resultados muestra "Utilidad de operación" como '
        'subtotal. Lo consulta analisis_vertical_horizontal.estado_resultados().'),
    'resultado_financiero_despues_de_operacion': (
        'Si el resultado financiero va debajo de la utilidad de operación en '
        'vez de dentro de los gastos.'),
}


NORMAS: Dict[str, Dict] = {
    # -----------------------------------------------------------------------
    'ifrs_nif': {
        'nombre': 'IFRS en cumplimiento con NIF (México)',
        'descripcion':
            'IFRS como base, con las Normas de Información '
            'Financiera mexicanas donde aplican.',
        # EBITDA = Earnings Before Interest, Taxes, DEPRECIATION and
        # AMORTIZATION. "Amortization" son intangibles y activos de derecho de
        # uso — NO el consumo de pagos anticipados.
        #
        # La distinción no es teórica: en el catálogo de Networks existe
        # "Amortización - Primas Seguros", que es una póliza pagada por
        # adelantado consumiéndose mes a mes. Es un gasto de operación
        # corriente. Sumarla de vuelta al EBITDA lo infla con algo que sí
        # consume caja todos los años.
        # La estructura es amplia-incluye / específica-excluye, y ese orden
        # importa. La versión anterior listaba en `incluye` solo
        # "amortización de intangibles", y con eso dejaba fuera
        # "Amortización - Programas de Cómputo", que es software: un intangible
        # de libro que SÍ entra al EBITDA. Enumerar cada forma en que alguien
        # puede nombrar un intangible es una carrera perdida.
        #
        # Se incluye la amortización en general y se excluye lo que de verdad
        # no es un activo de capital, que es una lista corta y estable.
        'dya_para_ebitda': {
            'incluye': [
                'depreciacion', 'depreciation',
                'amortizacion', 'amortization',
                'deterioro', 'impairment',
                'right of use', 'derecho de uso',
            ],
            'excluye': [
                # Pagos anticipados consumiéndose: gasto de operación, no D&A.
                'prima', 'seguro', 'insurance',
                'renta pagada por anticipado', 'rentas pagadas por anticipado',
                'prepaid', 'anticipad',
                'gastos de instalacion', 'papeleria',
            ],
        },
        'presenta_utilidad_operacion': True,
        'resultado_financiero_despues_de_operacion': True,
    },

    # -----------------------------------------------------------------------
    'us_gaap': {
        'nombre': 'US GAAP',
        'descripcion':
            'Marco estadounidense. Declarado para que un cliente que lo siga '
            'no requiera tocar código; NO se ha usado todavía en producción.',
        'dya_para_ebitda': {
            'incluye': [
                'depreciation', 'amortization of intangibles',
                'depletion', 'impairment',
            ],
            'excluye': ['prepaid', 'insurance'],
        },
        # US GAAP no exige un subtotal de utilidad de operación; muchas
        # empresas lo presentan igual, pero no es obligatorio.
        'presenta_utilidad_operacion': True,
        'resultado_financiero_despues_de_operacion': True,
    },
}

NORMA_POR_DEFECTO = 'ifrs_nif'


class NormaDesconocida(ValueError):
    """Se pidió una norma que no está en el registro."""


def obtener(clave: str = None) -> Dict:
    """La norma pedida. Si no se indica ninguna, la de por defecto.

    Una clave desconocida LEVANTA en vez de caer a la de por defecto: aplicar
    en silencio las reglas de otro marco a los estados de alguien es
    exactamente el tipo de error que nadie detecta leyendo el resultado.
    """
    if clave is None:
        clave = NORMA_POR_DEFECTO
    clave = str(clave).strip().lower()
    if clave not in NORMAS:
        raise NormaDesconocida(
            f'Norma contable desconocida: {clave!r}. Las registradas son: '
            f'{", ".join(sorted(NORMAS))}. Si hace falta una nueva, se agrega '
            f'a normas_contables.NORMAS con todas sus políticas.')
    return NORMAS[clave]


def politica(nombre: str, clave_norma: str = None):
    """El valor de una política bajo la norma indicada."""
    if nombre not in POLITICAS:
        raise KeyError(
            f'Política desconocida: {nombre!r}. Las declaradas son: '
            f'{", ".join(sorted(POLITICAS))}.')
    norma = obtener(clave_norma)
    if nombre not in norma:
        raise KeyError(
            f'La norma {norma["nombre"]!r} no declara la política {nombre!r}. '
            f'Toda norma debe declarar todas las políticas: un valor por '
            f'defecto silencioso mete reglas de otro marco sin que nadie lo vea.')
    return norma[nombre]


def normas_disponibles() -> List[Dict]:
    """Para poder ofrecerlas en una interfaz sin conocer el registro."""
    return [{'clave': k, 'nombre': v['nombre'], 'descripcion': v['descripcion']}
            for k, v in sorted(NORMAS.items())]
