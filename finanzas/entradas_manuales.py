# -*- coding: utf-8 -*-
"""
===============================================================================
 ENTRADAS MANUALES — lo que el equipo captura, y lo que corrige a mano
===============================================================================
Dos cosas que parecen la misma y NO lo son. Tenerlas separadas es el diseño
entero de este módulo.

  · **SUMINISTRO** — un dato que el ERP no tiene y nunca va a tener. La beta de
    una empresa privada, la prima de riesgo de mercado, el capex mientras no se
    extraiga. Aquí la captura manual no compite con nada: es la única fuente.
    Se edita libremente.

  · **SOBRESCRITURA** — un dato que el sistema SÍ calcula, y que alguien
    decidió reemplazar. Para un escenario hipotético, o porque la cifra del ERP
    está mal capturada y hay que corregirla mientras contabilidad la arregla en
    su origen.

    Esto es otra cosa. Un número sobrescrito se ve idéntico a uno calculado, y
    seis meses después nadie recuerda cuál era cuál. Por eso una sobrescritura:
      - exige desbloquear explícitamente el campo,
      - exige un motivo escrito,
      - queda MARCADA hasta que alguien la retire,
      - y se registra en la bitácora con quién y cuándo.

BORRAR LA CIFRA DEVUELVE EL CÁLCULO AUTOMÁTICO
-----------------------------------------------
No hay un botón de "volver a automático" separado. Se borra el valor y el campo
vuelve solo a lo que calcula el sistema. Un mecanismo de reversión distinto del
de borrado es un mecanismo que alguien no va a encontrar.

EL ÁMBITO: HASTA DÓNDE LLEGA CADA ENTRADA
------------------------------------------
    ('*',   '*')        todas las empresas, todos los periodos
    ('NCS', '*')        una empresa, todos los periodos
    ('*',   '2026-09')  todas las empresas, un periodo
    ('NCS', '2026-09')  una empresa y un periodo

Gana **la más específica**. Una beta global de 1.10 con una de NTS en 1.35 deja
a NTS en 1.35 y a las demás en 1.10, sin que haya que repetir el valor cuatro
veces. Sin esta regla, capturar un supuesto que aplica a todo el grupo
obligaría a capturarlo una vez por empresa y por mes — y al mes siguiente
alguien olvidaría una.

POR QUÉ NO SE GUARDA DESDE EL NAVEGADOR
----------------------------------------
El tablero es una página estática: no tiene servidor propio y no puede escribir
en S3 sin llevar credenciales dentro, que es justo lo que no se hace. Así que
la hoja de captura edita una copia de trabajo en el navegador y produce un
archivo; quien corre la actualización lo aplica con `entradas.py --aplicar`.

Se dice en pantalla con todas sus letras. Una hoja que parece guardar y no
guarda es peor que una que pide un paso extra.
===============================================================================
"""
import os
import sys
import json
import datetime as dt
from typing import Dict, List, Optional, Any

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(AQUI, 'configuracion'))

RUTA_ENTRADAS = 'entradas_manuales.json'
COMODIN = '*'

# Las dos clases de entrada. La diferencia no es cosmética: decide si hace
# falta desbloquear, si hace falta motivo, y si el valor sale marcado.
SUMINISTRO = 'suministro'
SOBRESCRITURA = 'sobrescritura'


class EntradaInvalida(ValueError):
    """Un dato capturado no cumple las reglas del campo."""


# ---------------------------------------------------------------------------
# La unidad en que se escribe no es la unidad en que se calcula
# ---------------------------------------------------------------------------
# Una tasa del nueve punto seis por ciento se ESCRIBE `9.6` y se CALCULA como
# `0.096`. Las dos son la misma cifra; lo que cambia es quién la lee.
#
# La convención financiera manda en la pantalla: donde dice `%`, se teclea el
# porcentaje. Pedirle a alguien que escriba 0.096 bajo una etiqueta que dice
# `%` es pedirle que haga la división mentalmente, y tarde o temprano alguien
# no la hace. Pasó: se capturaron 9.6, 1.77, 7.75 y 12.24 en campos que
# esperaban fracciones, y los cuatro se habrían rechazado.
#
# La conversión ocurre en UN SOLO PAR DE FUNCIONES, y todo lo que entra o sale
# pasa por ellas. Si la hoja convirtiera por su lado y la línea de comandos por
# el suyo, tarde o temprano una de las dos quedaría con el criterio viejo — y
# la cifra se vería perfectamente normal en las dos pantallas.
#
#   escribe la persona  --a_interno-->  se guarda y se calcula
#   se guarda           --a_mostrado--> se le muestra a la persona
FACTOR_PORCENTAJE = 100.0


def _es_porcentaje(campo: str) -> bool:
    return (CAMPOS.get(campo) or {}).get('unidad') == '%'


def a_interno(campo: str, valor: float) -> float:
    """Del número que escribe una persona al que usa el cálculo.

    El redondeo no es cosmético. `12.24 / 100` da 0.12240000000000001 en punto
    flotante, y ese número queda guardado en el archivo y escrito en la
    bitácora. Quien audite la captura de un supuesto va a leer esa cola de
    dígitos y va a dudar de si alguien tecleó algo raro — que es exactamente lo
    que una bitácora existe para evitar.

    Doce decimales dejan intacto cualquier porcentaje que alguien escriba de
    verdad y borran el ruido de la división.
    """
    v = float(valor)
    return round(v / FACTOR_PORCENTAJE, 12) if _es_porcentaje(campo) else v


def a_mostrado(campo: str, valor):
    """Del número guardado al que se le enseña a una persona."""
    if valor is None:
        return None
    v = float(valor)
    return v * FACTOR_PORCENTAJE if _es_porcentaje(campo) else v


# ---------------------------------------------------------------------------
# Catálogo de campos capturables
# ---------------------------------------------------------------------------
# Cada campo declara qué es, en qué unidad va, en qué ámbito tiene sentido y si
# es suministro o sobrescritura. La hoja de captura se arma con esto: no tiene
# una lista propia de columnas.
#
# `rango` existe porque el error de captura más común y más silencioso es el
# factor 100: escribir 18 donde va 0.18. Un ROE objetivo de 1,800% no lo
# detecta nadie leyendo una hoja de cálculo llena de números.
def _campo(etiqueta, unidad, tipo, grupo, ayuda, rango=None, ambito='ambos'):
    return {'etiqueta': etiqueta, 'unidad': unidad, 'tipo': tipo,
            'grupo': grupo, 'ayuda': ayuda, 'rango': rango,
            # 'ambito' dice si el campo admite periodo: un supuesto de mercado
            # cambia con el tiempo; la beta de una empresa, en la práctica, no.
            'ambito': ambito}


CAMPOS: Dict[str, Dict] = {
    # --- Costo de capital: puro suministro, el ERP no tiene nada de esto ----
    'rf': _campo('Tasa libre de riesgo', '%', SUMINISTRO, 'costo_capital',
                 'Observable. Se toma de la curva de deuda gubernamental; este '
                 'valor es el respaldo cuando no hay conexión.',
                 rango=(0.0, 60.0)),
    'beta': _campo('Beta', 'x', SUMINISTRO, 'costo_capital',
                   'JUICIO. En una empresa privada no hay precio de acción del '
                   'cual estimarla. Revísala cuando cambie la estructura del '
                   'negocio, no cada mes.',
                   rango=(0.0, 5.0)),
    'erp': _campo('Prima de riesgo de mercado', '%', SUMINISTRO, 'costo_capital',
                  'JUICIO. Cuánto se le exige de más a una inversión en capital '
                  'frente a la deuda gubernamental.',
                  rango=(0.0, 30.0)),
    'kd': _campo('Costo de la deuda', '%', SUMINISTRO, 'costo_capital',
                 'Antes de impuestos. Sustituible por el costo real de los '
                 'financiamientos registrados.',
                 rango=(0.0, 60.0)),
    'tasa_impositiva': _campo(
        'Tasa impositiva supuesta', '%', SUMINISTRO, 'costo_capital',
        'Se usa solo cuando la tasa efectiva del periodo no es interpretable. '
        'La medida del ERP gana siempre que sea confiable.',
        rango=(0.0, 80.0)),

    # --- Lo que falta extraer del ERP --------------------------------------
    'capex': _campo('Inversión en activo fijo (capex)', '$', SUMINISTRO, 'flujo',
                    'Altas de activo fijo del periodo. Mientras no se extraiga '
                    'del ERP, sin esto no hay flujo libre ni margen de FCF.'),
    'delta_capital_trabajo': _campo(
        'Δ capital de trabajo', '$', SUMINISTRO, 'flujo',
        'Cambio en el capital de trabajo operativo. Si se deja vacío se estima '
        'contra el periodo anterior.'),

    # --- Sobrescrituras: el sistema SÍ calcula esto -------------------------
    'ingresos': _campo('Ingresos', '$', SOBRESCRITURA, 'resultados',
                       'Sale del Estado de Resultados del ERP.', ambito='periodo'),
    'costo_servicio': _campo('Costo de ventas', '$', SOBRESCRITURA, 'resultados',
                             'Sale del Estado de Resultados del ERP.', ambito='periodo'),
    'gastos_operacion': _campo('Gastos de operación', '$', SOBRESCRITURA, 'resultados',
                               'Incluyen la depreciación del periodo.', ambito='periodo'),
    'depreciacion': _campo('Depreciación y amortización', '$', SOBRESCRITURA, 'resultados',
                           'Qué cuenta como D&A lo decide la norma contable '
                           'configurada, no este campo.', ambito='periodo'),
    'gastos_financieros': _campo('Resultado financiero, neto', '$', SOBRESCRITURA,
                                 'resultados',
                                 'Positivo = costo neto. Negativo = la empresa '
                                 'ganó más por intereses de los que pagó.',
                                 ambito='periodo'),
    'impuestos': _campo('Impuesto a la utilidad', '$', SOBRESCRITURA, 'resultados',
                        'ISR y PTU del periodo.', ambito='periodo'),
    'activos_totales': _campo('Activo total', '$', SOBRESCRITURA, 'balance',
                              'Posición al cierre del periodo.', ambito='periodo'),
    'pasivos_totales': _campo('Pasivo total', '$', SOBRESCRITURA, 'balance',
                              'Posición al cierre del periodo.', ambito='periodo'),
    'patrimonio': _campo('Capital contable', '$', SOBRESCRITURA, 'balance',
                         'Posición al cierre del periodo.', ambito='periodo'),
    'efectivo': _campo('Efectivo y equivalentes', '$', SOBRESCRITURA, 'balance',
                       '', ambito='periodo'),
    'cuentas_x_cobrar': _campo('Cuentas por cobrar', '$', SOBRESCRITURA, 'balance',
                               'A terceros: los saldos con empresas del grupo '
                               'viven en otras cuentas.', ambito='periodo'),
    'cuentas_x_pagar': _campo('Cuentas por pagar', '$', SOBRESCRITURA, 'balance',
                              'A terceros.', ambito='periodo'),
    'inventarios': _campo('Inventarios', '$', SOBRESCRITURA, 'balance', '',
                          ambito='periodo'),
    'deuda_con_costo': _campo('Deuda con costo', '$', SOBRESCRITURA, 'balance',
                              'La que causa intereses. No incluye proveedores.',
                              ambito='periodo'),
    'activo_circulante': _campo('Activo circulante', '$', SOBRESCRITURA, 'balance',
                                '', ambito='periodo'),
    'pasivo_circulante': _campo('Pasivo circulante', '$', SOBRESCRITURA, 'balance',
                                '', ambito='periodo'),
}

GRUPOS = [
    ('costo_capital', 'Costo de capital',
     'Lo que el ERP no tiene y no va a tener. Aquí la captura es la única fuente.'),
    ('flujo', 'Flujo libre',
     'Lo que falta extraer del ERP. Sin esto, el flujo libre sale vacío.'),
    ('resultados', 'Estado de Resultados',
     'El sistema ya los calcula. Editarlos es SOBRESCRIBIR y queda marcado.'),
    ('balance', 'Balance General',
     'El sistema ya los calcula. Editarlos es SOBRESCRIBIR y queda marcado.'),
]


def _hoy() -> str:
    return dt.datetime.now().isoformat(timespec='seconds')


def clave(empresa: str, periodo: str, campo: str) -> str:
    return f'{empresa or COMODIN}|{periodo or COMODIN}|{campo}'


def validar(campo: str, valor: Any, motivo: str = '',
            desbloqueado: bool = False) -> float:
    """Comprueba una entrada antes de guardarla. Levanta si no pasa.

    Tres reglas, y cada una nace de una forma concreta de equivocarse:

    1. **El campo tiene que existir.** Un valor capturado contra un campo
       inventado no lo lee nadie y no avisa: se queda ahí pareciendo trabajo
       hecho.
    2. **Una sobrescritura exige desbloqueo y motivo.** Sin motivo, dentro de
       seis meses la cifra sigue ahí y nadie sabe si fue un escenario que se
       quedó puesto o una corrección legítima.
    3. **El valor tiene que caer en su rango.** El error de captura más común y
       más silencioso es el factor 100: escribir 18 donde va 0.18.
    """
    c = CAMPOS.get(campo)
    if c is None:
        raise EntradaInvalida(
            f'No existe el campo {campo!r}. Los capturables son: '
            f'{", ".join(sorted(CAMPOS))}.')
    try:
        v = float(valor)
    except (TypeError, ValueError):
        raise EntradaInvalida(
            f'{c["etiqueta"]}: {valor!r} no es un número.')
    if v != v:
        raise EntradaInvalida(f'{c["etiqueta"]}: el valor no es un número.')

    if c['tipo'] == SOBRESCRITURA:
        if not desbloqueado:
            raise EntradaInvalida(
                f'{c["etiqueta"]} es un campo que el sistema calcula. Para '
                f'reemplazarlo hay que desbloquearlo explícitamente — el '
                f'desbloqueo es lo que deja constancia de que alguien lo '
                f'decidió, no un trámite.')
        if not (motivo or '').strip():
            raise EntradaInvalida(
                f'{c["etiqueta"]}: una sobrescritura necesita motivo. Dentro de '
                f'seis meses el número va a seguir ahí y el motivo es lo único '
                f'que va a explicar por qué.')

    r = c.get('rango')
    if r and not (r[0] <= v <= r[1]):
        raise EntradaInvalida(
            f'{c["etiqueta"]}: {v:g}{c["unidad"]} está fuera del rango '
            f'esperado [{r[0]:g}, {r[1]:g}]{c["unidad"]}.')
    # Se valida en la unidad EN QUE SE ESCRIBE y se guarda en la unidad EN QUE
    # SE CALCULA. Ver `a_interno`.
    return a_interno(campo, v)


# ---------------------------------------------------------------------------
# Colección
# ---------------------------------------------------------------------------
class Entradas:
    """Las entradas de un cliente, con la resolución por especificidad."""

    def __init__(self, datos: Optional[Dict] = None):
        d = datos or {}
        self.entradas: Dict[str, Dict] = dict(d.get('entradas') or {})
        self.actualizado: str = d.get('actualizado') or _hoy()

    # -- escritura ---------------------------------------------------------
    def fijar(self, empresa: str, periodo: str, campo: str, valor,
              motivo: str = '', autor: str = '', desbloqueado: bool = False) -> Dict:
        v = validar(campo, valor, motivo, desbloqueado)
        c = CAMPOS[campo]
        if c['ambito'] == 'periodo' and (periodo or COMODIN) == COMODIN:
            raise EntradaInvalida(
                f'{c["etiqueta"]} es un dato de un periodo concreto. Fijarlo '
                f'para todos los periodos a la vez copiaría la misma cifra a '
                f'81 meses, y eso no es un dato: es un borrón.')
        k = clave(empresa, periodo, campo)
        reg = {'empresa': empresa or COMODIN, 'periodo': periodo or COMODIN,
               'campo': campo, 'valor': v, 'tipo': c['tipo'],
               'motivo': (motivo or '').strip(), 'autor': (autor or '').strip(),
               'fecha': _hoy()}
        self.entradas[k] = reg
        self.actualizado = reg['fecha']
        return reg

    def borrar(self, empresa: str, periodo: str, campo: str) -> Optional[Dict]:
        """Quitar el valor ES la forma de volver al cálculo automático."""
        k = clave(empresa, periodo, campo)
        reg = self.entradas.pop(k, None)
        if reg:
            self.actualizado = _hoy()
        return reg

    # -- lectura -----------------------------------------------------------
    def resolver(self, empresa: str, periodo: str) -> Dict[str, Dict]:
        """Qué entradas aplican a esta empresa y periodo. Gana la más específica.

        El orden de preferencia va de lo general a lo particular, así que la
        última asignación que sobrevive es la más específica. Escribirlo al
        revés —particular primero— dejaría que lo general pisara lo particular,
        que es el error que hace que una beta capturada para una empresa no
        surta efecto y nadie entienda por qué.
        """
        salida = {}
        for emp, per in ((COMODIN, COMODIN), (COMODIN, periodo),
                         (empresa, COMODIN), (empresa, periodo)):
            for reg in self.entradas.values():
                if reg['empresa'] == emp and reg['periodo'] == per:
                    salida[reg['campo']] = reg
        return salida

    def sobrescrituras(self) -> List[Dict]:
        return [r for r in self.entradas.values() if r['tipo'] == SOBRESCRITURA]

    def a_dict(self) -> Dict:
        return {'entradas': self.entradas, 'actualizado': self.actualizado,
                'version_catalogo': sorted(CAMPOS)}


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------
def _ruta(cliente) -> str:
    return f'{cliente.prefijo_s3()}/{RUTA_ENTRADAS}'


def cargar(almacen, cliente) -> Entradas:
    datos, _ = almacen.leer(_ruta(cliente))
    return Entradas(datos)


def guardar(almacen, cliente, entradas: Entradas) -> None:
    """Escritura con reintento, igual que la configuración.

    Dos personas capturando a la vez en la misma hoja es el caso normal, no el
    raro. Sin comparación de versión, la última en guardar borra el trabajo de
    la primera sin que ninguna de las dos se entere.
    """
    from almacen import actualizar_con_reintento
    actualizar_con_reintento(almacen, _ruta(cliente),
                             lambda _actual: entradas.a_dict())


def aplicar_a_supuestos(supuestos: Dict, resueltas: Dict[str, Dict]) -> Dict:
    """Los supuestos del costo de capital, con lo capturado encima."""
    out = dict(supuestos)
    for campo in ('rf', 'beta', 'erp', 'kd', 'tasa_impositiva'):
        if campo in resueltas:
            out[campo] = resueltas[campo]['valor']
    return out


# Cómo se llama cada campo capturable dentro del Estado de Resultados y del
# Balance que produce `analisis_vertical_horizontal`. Los nombres difieren
# porque cada módulo nombró lo suyo antes de que existiera el otro; la tabla
# está aquí, en un solo lugar, en vez de repetida en cada exportador.
_EN_RESULTADOS = {
    'ingresos': 'ingresos', 'costo_servicio': 'costo',
    'gastos_operacion': 'gastos_operacion',
    'gastos_financieros': 'resultado_financiero', 'impuestos': 'impuestos',
}
_EN_BALANCE = {
    'activos_totales': 'activo', 'pasivos_totales': 'pasivo',
    'patrimonio': 'capital',
}


def aplicar_a_estado(er: Dict, bal: Dict, resueltas: Dict[str, Dict]):
    """El Estado de Resultados y el Balance con lo capturado encima.

    **Los subtotales se recalculan.** Sustituir los ingresos sin rehacer la
    utilidad bruta, la de operación y la neta dejaría un estado donde el
    renglón de arriba ya está corregido y los de abajo no — y cuadraría, porque
    cada uno se mostraría tal como estaba. Un estado que no suma sus propios
    renglones es peor que uno con una cifra mala.

    Existe para que la corrección se vea en TODAS partes. Si solo se aplicara
    del lado de los indicadores, el Estado de Resultados y el tablero mostrarían
    cifras distintas del mismo mes, que es exactamente lo que este desarrollo
    se propuso que no pudiera pasar.
    """
    if not resueltas:
        return er, bal, {}
    er, bal, marcas = dict(er), dict(bal), {}
    for campo, reg in resueltas.items():
        destino = _EN_RESULTADOS.get(campo)
        if destino:
            er[destino] = reg['valor']
        elif campo in _EN_BALANCE:
            bal[_EN_BALANCE[campo]] = reg['valor']
        else:
            continue
        marcas[campo] = {'tipo': reg['tipo'], 'motivo': reg['motivo'],
                         'autor': reg['autor'], 'fecha': reg['fecha']}
    if not marcas:
        return er, bal, {}

    # Rehacer la cascada del Estado de Resultados, en el mismo orden en que se
    # presenta. Cada renglón depende del anterior, así que el orden no es
    # decorativo.
    er['utilidad_bruta'] = er['ingresos'] - er['costo']
    er['utilidad_operacion'] = er['utilidad_bruta'] - er['gastos_operacion']
    er['resultado_antes_impuestos'] = (er['utilidad_operacion']
                                       - er['resultado_financiero']
                                       - er.get('otros', 0.0))
    er['utilidad_neta'] = er['resultado_antes_impuestos'] - er['impuestos']
    return er, bal, marcas


def aplicar_a_fila(fila: Dict, resueltas: Dict[str, Dict]) -> Dict:
    """La fila financiera de un periodo, con lo capturado encima.

    Devuelve la fila nueva y deja constancia en `_manual` de qué campos se
    tocaron y por qué. Ese rastro es el que hace que el tablero pueda resaltar
    la cifra: sin él, un valor sobrescrito se ve idéntico a uno calculado.
    """
    if not resueltas:
        return fila
    f = dict(fila)
    marcas = {}
    for campo, reg in resueltas.items():
        if campo not in CAMPOS:
            continue
        if CAMPOS[campo]['grupo'] == 'costo_capital':
            continue          # esos entran por los supuestos, no por la fila
        f[campo] = reg['valor']
        marcas[campo] = {'tipo': reg['tipo'], 'motivo': reg['motivo'],
                         'autor': reg['autor'], 'fecha': reg['fecha']}
    if not marcas:
        return f

    # REHACER LA CASCADA. Sustituir los ingresos y dejar el EBIT viejo produce
    # una fila donde el renglón de arriba ya está corregido y los de abajo no:
    # un ingreso de 26 millones con un margen calculado sobre 26.3. Pasó, y lo
    # detectó la prueba que compara las dos pestañas.
    #
    # LA FÓRMULA NO ES LA MISMA QUE LA DE RESPALDO DE `derivar_estado`, Y ESO
    # IMPORTA. Aquélla resta la depreciación aparte porque supone una fila
    # cruda donde los gastos de operación no la incluyen. En estas filas SÍ la
    # incluyen —vienen del Estado de Resultados, donde la depreciación es una
    # cuenta de gasto más—, así que restarla otra vez la descontaría dos veces.
    # Es exactamente el error que costó corregir el EBITDA de todo el tablero.
    campos_cascada = {'ingresos', 'costo_servicio', 'gastos_operacion',
                      'gastos_financieros', 'impuestos'}
    if campos_cascada & set(marcas):
        ing = f.get('ingresos')
        costo = f.get('costo_servicio')
        gastos = f.get('gastos_operacion')
        fin = f.get('gastos_financieros')
        imp = f.get('impuestos')
        dep = f.get('depreciacion')
        if None not in (ing, costo, gastos):
            f['ebit'] = ing - costo - gastos
            if dep is not None:
                f['ebitda'] = f['ebit'] + dep
            if fin is not None:
                f['ebt'] = f['ebit'] - fin
                if imp is not None:
                    f['utilidad_neta'] = f['ebt'] - imp
    # La depreciación sola no mueve el EBIT —ya está dentro de los gastos— pero
    # sí el EBITDA, que la suma de vuelta.
    elif 'depreciacion' in marcas and f.get('ebit') is not None:
        if f.get('depreciacion') is not None:
            f['ebitda'] = f['ebit'] + f['depreciacion']

    f['_manual'] = marcas
    return f
