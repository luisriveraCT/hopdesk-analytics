# -*- coding: utf-8 -*-
"""
===============================================================================
 EL TABLERO COMO APLICACIÓN — para que escribir guarde, sin pasos intermedios
===============================================================================
Sirve el mismo `dashboard/index.html` de siempre, pero con un servidor detrás.
Eso cambia una sola cosa, y es la que importaba: **la hoja de captura guarda al
oprimir guardar.** Se acabó exportar un archivo y correr un comando.

POR QUÉ SHINY Y NO UN ENDPOINT NORMAL
--------------------------------------
Posit Connect Cloud —donde ya se publica esto— admite Shiny, Streamlit, Dash,
Bokeh y Quarto. **No admite APIs sueltas de Flask o FastAPI.** Así que no hay
forma de publicar un `POST /guardar` como tal.

Shiny sí tiene un canal propio entre el navegador y el servidor, y alcanza de
sobra: el JavaScript de la página manda el lote con `Shiny.setInputValue`, aquí
se recibe, se valida y se escribe en S3, y se contesta con un mensaje. Es el
mismo viaje de ida y vuelta que haría un endpoint, por la puerta que la
plataforma sí abre.

CÓMO CONVIVE CON LA PÁGINA QUE YA EXISTE
-----------------------------------------
El tablero es un documento HTML completo —con su `<head>`, su `<style>` y sus
250 KB de JavaScript propio—. `ui.page_html` existe justo para eso: sirve un
documento propio tal cual y le inserta las dependencias de Shiny donde la
página marca con `<meta name="shiny-dependency-placeholder">`.

No se parte el archivo ni se le reconstruye la cabeza. El primer intento sí lo
hacía, y era frágil de la peor manera: cualquier cambio en la forma del HTML
habría dejado media página servida sin que nada se quejara.

**No se duplica el tablero.** Este archivo lee el `index.html` que produce
`actualizar.py`. Si aquí se copiara la página, existirían dos tableros y un día
uno de los dos se quedaría atrás sin que nadie lo notara.

LO QUE ESTE ARCHIVO NO HACE
---------------------------
No valida por su cuenta. Las reglas —qué campo existe, qué rango es plausible,
que una sobrescritura exige motivo— viven en `entradas_manuales.validar()` y se
llaman desde aquí. Un servidor con su propia copia de las reglas es un servidor
que un día acepta lo que la línea de comandos rechaza.

QUIÉN FIRMA LA CAPTURA
----------------------
El nombre sale de la sesión, no de un campo que alguien llene. En Connect el
usuario viene autenticado; en local no hay sesión y se marca como tal. Un autor
que se teclea es un autor que se puede inventar, y la bitácora existe
precisamente para poder preguntar quién decidió una cifra.
===============================================================================
"""
import os
import re
import sys
import json
import traceback

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
FINANZAS = os.path.join(RAIZ, 'finanzas')

sys.path.insert(0, FINANZAS)
sys.path.insert(0, os.path.join(FINANZAS, 'configuracion'))
sys.path.insert(0, os.path.join(FINANZAS, 'erp'))
sys.path.insert(0, os.path.join(RAIZ, 'dashboard'))
sys.path.insert(0, AQUI)

from shiny import App, ui, reactive, Session   # noqa: E402

import entradas_manuales as em                 # noqa: E402
import bitacora_cambios as bc                  # noqa: E402
import repositorio as repo                     # noqa: E402

# ---------------------------------------------------------------------------
# De dónde sale la página
# ---------------------------------------------------------------------------
# Del almacén privado en S3, y en su defecto del disco. El orden importa y es
# la decisión de diseño de este archivo.
#
# Connect Cloud publica las aplicaciones de Python DESDE UN REPOSITORIO DE
# GITHUB. Y `index.html` pesa un megabyte y medio porque lleva dentro los
# estados financieros y los indicadores del grupo. Meter eso en un repositorio
# —público o no— es publicar las cifras del negocio en un sitio que nadie
# vuelve a mirar.
#
# Así que se separan las dos cosas por su naturaleza:
#
#     el CÓDIGO viaja por Git      — cambia cuando alguien programa
#     los DATOS viajan por S3      — cambian cada vez que se actualiza
#
# De paso resuelve lo otro: publicar un tablero nuevo es correr
# `actualizar.py`, sin tocar Git ni volver a desplegar nada.
CLAVE_TABLERO = 'tablero/index.html'
RUTAS_LOCALES = [
    os.path.join(RAIZ, 'dashboard', 'index.html'),
    os.path.join(AQUI, 'index.html'),
]


def _leer_tablero():
    """(html, de dónde salió). Primero el almacén, luego el disco."""
    try:
        almacen = repo.almacen_por_defecto()
        datos, _ = almacen.leer(CLAVE_TABLERO)
        if datos and datos.get('html'):
            return datos['html'], f'{repo.descripcion_almacen()} → {CLAVE_TABLERO}'
    except Exception as e:                                   # noqa: BLE001
        # No se calla: que el almacén no conteste y la app sirva una copia
        # vieja del disco sin decirlo es cómo alguien acaba mirando cifras de
        # hace tres semanas convencido de que son las de hoy.
        print(f'aviso: no se pudo leer el tablero del almacén ({e}); '
              f'se intenta el disco.', file=sys.stderr, flush=True)
    for ruta in RUTAS_LOCALES:
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                return f.read(), ruta
    raise SystemExit(
        'No se encontró el tablero, ni en el almacén ni en disco.\n'
        'Constrúyelo y publícalo con:  python actualizar.py')


_HTML, _RUTA = _leer_tablero()

MARCADOR = '<meta name="shiny-dependency-placeholder" content="">'
if MARCADOR not in _HTML:
    # Se comprueba al arrancar y se detiene. Sin el marcador la página se
    # serviría igual de bien pero SIN el canal de Shiny, así que el botón de
    # guardar caería al modo archivo — la misma pantalla, el mismo botón, y
    # nada que explique por qué dejó de guardar.
    raise SystemExit(
        f'{_RUTA} no trae el marcador de dependencias de Shiny.\n'
        f'Está en dashboard/plantilla.html, junto a las demás etiquetas <meta>.\n'
        f'Reconstruye con: python actualizar.py --solo-tablero')

app_ui = ui.page_html(_HTML)


# ---------------------------------------------------------------------------
# Recalcular los indicadores sin volver a tocar el ERP
# ---------------------------------------------------------------------------
# Cambiar una beta tiene que moverse en la pantalla al momento. Antes no lo
# hacía: los indicadores venían precalculados con la construcción del tablero,
# así que capturar un supuesto nuevo no cambiaba nada y parecía que el guardado
# no había servido de nada.
#
# Rehacer el pipeline completo no es opción —son minutos y necesita los 180 MB
# de extracción, que en la nube no están—. Pero tampoco hace falta: todo lo que
# depende de los supuestos (Ke, WACC, NOPAT, ROIC, el spread y el EVA) se
# calcula a partir de cifras que ya están en `base_financiera.json`.
#
# SE REUSA EL MISMO CÓDIGO DE SIEMPRE. Este archivo no reimplementa ninguna
# fórmula: llama a `exportar_kpis.procesar`, que es lo que corre en el
# pipeline. Un servidor con su propia copia de las fórmulas es un servidor que
# un día da un ROIC distinto del que da el archivo, y nadie sabe cuál creer.
CLAVE_BASE = 'tablero/base_financiera.json'
RUTAS_BASE = [
    os.path.join(RAIZ, 'dashboard', 'base_financiera.json'),
    os.path.join(AQUI, 'base_financiera.json'),
]


def _leer_base():
    """La base para recalcular, o None si no está publicada."""
    try:
        datos, _ = repo.almacen_por_defecto().leer(CLAVE_BASE)
        if datos and datos.get('series'):
            return datos
    except Exception as e:                                   # noqa: BLE001
        print(f'aviso: no se pudo leer la base del almacén ({e})',
              file=sys.stderr, flush=True)
    for ruta in RUTAS_BASE:
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                return json.load(f)
    return None


_BASE = _leer_base()
if _BASE is None:
    print('aviso: sin base_financiera.json, los indicadores NO se van a '
          'recalcular al guardar. Genérala con: python actualizar.py',
          file=sys.stderr, flush=True)


def recalcular_series(entradas_obj):
    """Los indicadores con los supuestos capturados. None si no hay base.

    Devuelve lo mismo que `kpis.json` en su campo `series`, para que la página
    pueda reemplazarlo tal cual y repintar.
    """
    if _BASE is None:
        return None
    import exportar_kpis as ek

    almacen = repo.almacen_por_defecto()
    cliente = repo.cliente_actual(almacen)
    pol = cliente.politica
    conv = ek.leer_convenciones(pol)
    supuestos = dict(pol.supuestos)
    metas = dict(pol.metas)
    interco = _BASE.get('interco') or {}
    grupo = _BASE.get('clave_grupo')

    series = {}
    for clave, filas in (_BASE.get('series') or {}).items():
        ic = {} if clave == grupo else interco.get(clave, {})
        ent = None if clave == grupo else entradas_obj
        series[clave] = ek.procesar(filas, supuestos, metas, ic, conv,
                                    ent, clave)
    return series


def _autor_de(session: Session) -> str:
    """Quién está capturando, según la sesión.

    En Connect el usuario llega autenticado y su nombre viaja en las cabeceras
    de la petición. En local no hay sesión, y eso se DICE en vez de inventar un
    nombre: una bitácora que dice "Luis" cuando no sabe quién era es peor que
    una que dice que no lo sabe.
    """
    try:
        cab = dict(session.http_conn.headers)
    except Exception:                                        # noqa: BLE001
        return '(sesión local, sin autenticar)'
    for clave in ('rstudio-connect-credentials', 'x-rsc-user',
                  'x-forwarded-user', 'x-auth-request-user'):
        crudo = cab.get(clave)
        if not crudo:
            continue
        # Connect manda un JSON con el usuario; otros proxies mandan el nombre
        # pelado. Se aceptan las dos formas.
        try:
            datos = json.loads(crudo)
            nombre = datos.get('user') or datos.get('username')
            if nombre:
                return str(nombre)
        except (ValueError, AttributeError):
            return str(crudo)
    return '(sesión local, sin autenticar)'


def aplicar_lote(cambios, autor):
    """Guarda un lote de capturas. Devuelve (aplicados, rechazados).

    Es la misma lógica que `entradas.py --aplicar`, y a propósito: se validan
    los cambios uno por uno y se guardan los que pasan. Rechazar el lote entero
    porque un renglón trae un error obliga a rehacer el trabajo de los otros
    veinte, y en la práctica eso termina en que alguien desactiva la validación.
    """
    almacen = repo.almacen_por_defecto()
    cliente = repo.cliente_actual(almacen)
    ent = em.cargar(almacen, cliente)

    aplicados, rechazados = [], []
    for c in cambios:
        campo = c.get('campo')
        empresa = (c.get('empresa') or em.COMODIN).upper()
        periodo = c.get('periodo') or em.COMODIN
        try:
            if c.get('borrar'):
                reg = ent.borrar(empresa, periodo, campo)
                if reg:
                    aplicados.append(('borrado', campo, empresa, periodo,
                                      reg['valor'], None, ''))
                continue
            previo = ent.entradas.get(em.clave(empresa, periodo, campo))
            reg = ent.fijar(empresa, periodo, campo, c.get('valor'),
                            c.get('motivo', ''), autor,
                            desbloqueado=bool(c.get('desbloqueado')))
            aplicados.append(('cambio' if previo else 'captura', campo, empresa,
                              periodo, previo['valor'] if previo else None,
                              reg['valor'], reg['motivo']))
        except em.EntradaInvalida as e:
            rechazados.append({'campo': campo, 'empresa': empresa,
                               'periodo': periodo, 'motivo': str(e)})

    if aplicados:
        em.guardar(almacen, cliente, ent)
        # Se devuelve el estado COMPLETO tras guardar, no solo "salió bien".
        #
        # Sin esto la hoja se repinta con las entradas que venían horneadas en
        # la página desde que se construyó, así que un valor recién guardado
        # reaparece con su valor viejo. La escritura era correcta —estaba en
        # S3— y la pantalla decía lo contrario. Nada resulta más difícil de
        # confiar que un guardado que dice "listo" y deja la cifra anterior.
        for acto, campo, empresa, periodo, de, a, motivo in aplicados:
            bc.registrar(almacen, cliente, acto, autor,
                         {'campo': campo, 'empresa': empresa,
                          'periodo': periodo, 'de': de, 'a': a,
                          'motivo': motivo}, origen='tablero')
        bc.registrar(almacen, cliente, 'aplicacion', autor,
                     {'n': len(aplicados), 'rechazados': len(rechazados)},
                     origen='tablero')
    return aplicados, rechazados, ent.entradas


def server(input, output, session):        # noqa: A002

    # NO se usa `priority: "event"` del lado del navegador, y conviene saber
    # por qué antes de "arreglarlo": esa opción es de Shiny para R. El Shiny de
    # Python la rechaza con «No input handler registered for type: shiny.event»
    # y descarta el envío entero.
    #
    # No falla de forma visible: el botón se queda en "Guardando…" para
    # siempre y aquí no se registra nada, así que parece que el clic nunca
    # ocurrió. La página manda en su lugar un número de envío que cambia cada
    # vez, y eso basta para que Shiny vea un valor nuevo.
    @reactive.effect
    @reactive.event(input.guardar_entradas)
    async def _guardar():
        lote = input.guardar_entradas()
        autor = _autor_de(session)
        # Se registra ANTES de intentar nada. Si el guardado revienta a la
        # mitad, esta línea es la que dice que la petición sí llegó — la
        # diferencia entre "el servidor no lo recibió" y "lo recibió y falló"
        # es media hora de búsqueda en el lugar equivocado.
        n = len((lote or {}).get('cambios') or [])
        print(f'guardar_entradas: {n} cambio(s) de {autor}',
              file=sys.stderr, flush=True)
        try:
            cambios = (lote or {}).get('cambios') or []
            if not cambios:
                await session.send_custom_message(
                    'entradas_guardadas',
                    {'ok': False, 'mensaje': 'El lote no traía ningún cambio.'})
                return
            aplicados, rechazados, entradas = aplicar_lote(cambios, autor)
            print(f'  aplicados {len(aplicados)}, rechazados {len(rechazados)}',
                  file=sys.stderr, flush=True)
            # Los indicadores se rehacen SOLO si de verdad se guardó algo.
            # Recalcular tras un lote rechazado entero gastaría medio segundo
            # para devolver exactamente lo mismo que ya estaba en pantalla.
            series = None
            if aplicados:
                try:
                    almacen = repo.almacen_por_defecto()
                    cliente = repo.cliente_actual(almacen)
                    series = recalcular_series(em.cargar(almacen, cliente))
                    print(f'  indicadores recalculados: '
                          f'{len(series or {})} serie(s)',
                          file=sys.stderr, flush=True)
                except Exception:                            # noqa: BLE001
                    # El guardado ya ocurrió y es lo que importa. Si el
                    # recálculo falla se dice, pero no se pierde la captura ni
                    # se le devuelve un error a quien sí guardó bien.
                    print('ERROR al recalcular indicadores:',
                          traceback.format_exc(), file=sys.stderr, flush=True)
            await session.send_custom_message('entradas_guardadas', {
                'ok': not rechazados,
                'aplicados': len(aplicados),
                'rechazados': rechazados,
                'autor': autor,
                # El estado completo, para que la hoja se repinte con la verdad
                # y no con lo que traía desde que se construyó la página.
                'entradas': entradas,
                # Los indicadores ya rehechos con los supuestos nuevos, para
                # que la pantalla los muestre sin esperar una reconstrucción.
                'series': series,
            })
        except Exception as e:                               # noqa: BLE001
            # El error se registra COMPLETO del lado del servidor y se le manda
            # al navegador uno corto. Un rastro de pila en la pantalla no le
            # dice nada a quien captura, y sí le dice de más a cualquiera que
            # abra la página.
            print('ERROR al guardar entradas:', traceback.format_exc(),
                  file=sys.stderr, flush=True)
            await session.send_custom_message('entradas_guardadas', {
                'ok': False,
                'mensaje': f'No se pudo guardar ({type(e).__name__}). '
                           f'El detalle quedó en el registro del servidor.'})


app = App(app_ui, server)
