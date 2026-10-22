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
from modelo import CLAVE_GRUPO                 # noqa: E402

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


# ---------------------------------------------------------------------------
# LO PUBLICADO CAMBIA MIENTRAS LA APP CORRE, Y LA APP TIENE QUE ENTERARSE
# ---------------------------------------------------------------------------
# Esto se leía UNA vez, al importar el módulo. Publicabas con `actualizar.py`
# y la app seguía sirviendo lo anterior hasta reiniciarla; en Connect el
# proceso vive días, así que "hasta reiniciarla" quería decir "hasta que
# alguien se diera cuenta".
#
# Tampoco se puede traer el archivo en cada visita: el tablero pesa 1.6 MB.
# Se pregunta por la VERSIÓN, que es un HEAD de S3 —medido: ~350 ms contra
# ~900 ms de la descarga— y solo se vuelve a traer si cambió. Y no más de una
# vez cada TTL_VERSION segundos, para que una ráfaga de visitas no se
# convierta en una ráfaga de llamadas a S3.
TTL_VERSION = 30.0
_cache = {}

# EN TU MÁQUINA, EL TABLERO RECIÉN CONSTRUIDO. `actualizar.py --ver` arranca
# esta misma aplicación con ANALITICA_TABLERO_LOCAL=1: sirve el index.html y
# los datos de dashboard/ —lo que acabas de construir— en vez de lo publicado.
# Sin esto, verlo en local era abrir una página estática, y una página estática
# no puede guardar: la hoja caía a "Exportar cambios". Lo que se GUARDA sigue
# yendo al almacén de siempre (almacen.json), que es el mismo de producción:
# ver en local no es un entorno de pruebas, es la misma app en otra máquina.
TABLERO_LOCAL = os.environ.get('ANALITICA_TABLERO_LOCAL', '').strip() == '1'


def _del_almacen(clave, respaldos, leer_respaldo):
    """El contenido de `clave`, vuelto a traer solo si cambió.

    Si el almacén no contesta se sigue sirviendo lo último bueno —una caída de
    red no debe tumbar la página— pero se dice en el registro. Lo que no se
    hace nunca es bajar al respaldo de disco teniendo algo del almacén: así es
    como alguien acaba mirando cifras de hace tres semanas convencido de que
    son las de hoy.
    """
    import time
    ent = _cache.get(clave)
    ahora = time.monotonic()
    if TABLERO_LOCAL:
        for ruta in respaldos:
            if os.path.exists(ruta):
                v = os.path.getmtime(ruta)
                if not (ent and ent['version'] == v):
                    _cache[clave] = ent = {'datos': leer_respaldo(ruta), 'version': v,
                                           'revisado': ahora, 'de': ruta}
                return ent['datos']
    if ent and ahora - ent['revisado'] < TTL_VERSION:
        return ent['datos']
    try:
        almacen = repo.almacen_por_defecto()
        version = almacen.version(clave)
        if ent and version == ent['version']:
            ent['revisado'] = ahora
            return ent['datos']
        if version is not None:
            datos, v = almacen.leer(clave)
            if datos:
                if ent:
                    print(f'{clave}: versión nueva, recargado del almacén',
                          file=sys.stderr, flush=True)
                _cache[clave] = {'datos': datos, 'version': v, 'revisado': ahora,
                                 'de': f'{repo.descripcion_almacen()} → {clave}'}
                return datos
    except Exception as e:                                   # noqa: BLE001
        print(f'aviso: no se pudo leer {clave} del almacén ({e})',
              file=sys.stderr, flush=True)
        if ent:
            return ent['datos']
    for ruta in respaldos:
        if os.path.exists(ruta):
            _cache[clave] = {'datos': leer_respaldo(ruta), 'version': None,
                             'revisado': ahora, 'de': ruta}
            return _cache[clave]['datos']
    return None


def _leer_tablero():
    """(html, de dónde salió), de la publicación más reciente."""
    datos = _del_almacen(
        CLAVE_TABLERO, RUTAS_LOCALES,
        lambda r: {'html': open(r, encoding='utf-8').read()})
    if datos and datos.get('html'):
        return datos['html'], _cache[CLAVE_TABLERO]['de']
    raise SystemExit(
        'No se encontró el tablero, ni en el almacén ni en disco.\n'
        'Constrúyelo y publícalo con:  python actualizar.py')


def _etiqueta_almacen() -> str:
    """Bucket y prefijo, sin el perfil. Vacío si se está sirviendo del disco."""
    try:
        ajustes, _ = repo.ajustes_almacen()
    except Exception:                                        # noqa: BLE001
        return ''
    if not ajustes:
        return 'local'
    pref = ajustes.get('prefijo', '').strip('/')
    return f'{ajustes["bucket"]}/{pref}' if pref else ajustes['bucket']


MARCADOR = '<meta name="shiny-dependency-placeholder" content="">'
_servido = {'crudo': None, 'texto': None}


def _html_actual():
    """El tablero listo para servir, de la publicación más reciente.

    Sin el marcador la página se serviría igual de bien pero SIN el canal de
    Shiny, así que el botón de guardar caería al modo archivo: la misma
    pantalla, el mismo botón, y nada que explique por qué dejó de guardar. Al
    arrancar, eso detiene el servidor. Una publicación POSTERIOR que llegue
    rota se descarta y se sigue sirviendo la anterior — tirar una app que está
    funcionando por una publicación mala es cambiar un problema por otro peor.
    """
    html, ruta = _leer_tablero()
    if _servido['crudo'] == html:
        return _servido['texto']
    if MARCADOR not in html:
        aviso = (f'{ruta} no trae el marcador de dependencias de Shiny.\n'
                 f'Está en dashboard/plantilla.html, junto a las demás <meta>.\n'
                 f'Reconstruye con: python actualizar.py --solo-tablero')
        if _servido['texto'] is None:
            raise SystemExit(aviso)
        print(f'aviso: se descarta la publicación nueva. {aviso}',
              file=sys.stderr, flush=True)
        return _servido['texto']
    # Se inyecta junto al marcador, que ya se comprobó que existe.
    texto = html.replace(
        MARCADOR,
        f'<meta name="almacen-activo" content="{_etiqueta_almacen()}">\n' + MARCADOR,
        1)
    _servido['crudo'], _servido['texto'] = html, texto
    return texto


# Una FUNCIÓN y no un valor: Shiny la llama en cada petición, y es ahí donde
# se nota que hubo una publicación nueva. Como valor, el tablero se quedaba
# congelado en el que hubiera al arrancar el proceso.
def app_ui(request):                                         # noqa: ARG001
    return ui.page_html(_html_actual())


_html_actual()      # falla pronto si lo que hay publicado no sirve


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
    """La base para recalcular, de la publicación más reciente, o None.

    Se consulta en cada guardado y no al arrancar: si acabas de actualizar los
    estados financieros, el recálculo tiene que hacerse con los nuevos. Antes
    usaba los que hubiera cuando el proceso arrancó.
    """
    datos = _del_almacen(
        CLAVE_BASE, RUTAS_BASE,
        lambda r: json.load(open(r, encoding='utf-8')))
    return datos if datos and datos.get('series') else None


if _leer_base() is None:
    print('aviso: sin base_financiera.json, los indicadores NO se van a '
          'recalcular al guardar. Genérala con: python actualizar.py',
          file=sys.stderr, flush=True)


def recalcular_series(entradas_obj, cliente=None):
    """Los indicadores con los supuestos capturados. None si no hay base.

    Devuelve lo mismo que `kpis.json` en su campo `series`, para que la página
    pueda reemplazarlo tal cual y repintar. Las metas entran aquí también: el
    semáforo de cada indicador se recalcula contra las metas vigentes.
    """
    base = _leer_base()
    if base is None:
        return None
    import exportar_kpis as ek

    if cliente is None:
        cliente = repo.cliente_actual(repo.almacen_por_defecto())
    pol = cliente.politica
    conv = ek.leer_convenciones(pol)
    supuestos = dict(pol.supuestos)
    interco = base.get('interco') or {}
    grupo = base.get('clave_grupo')

    series = {}
    for clave, filas in (base.get('series') or {}).items():
        ic = {} if clave == grupo else interco.get(clave, {})
        ent = None if clave == grupo else entradas_obj
        series[clave] = ek.procesar(filas, supuestos, pol.metas_de(clave), ic, conv,
                                    ent, clave)
    return series


def _autor_de(session: Session) -> str:
    """Quién está capturando, según la sesión.

    En Connect el usuario llega autenticado y su nombre viaja en las cabeceras
    de la petición. En local no hay sesión, y eso se DICE en vez de inventar un
    nombre: una bitácora que dice "Luis" cuando no sabe quién era es peor que
    una que dice que no lo sabe.
    """
    import getpass
    # En tu máquina no hay sesión de Connect, pero sí un usuario del sistema
    # operativo: es quien está sentado frente a la app, y se dice que es local
    # para que nadie lo confunda con un usuario autenticado.
    # Solo en modo local: en Connect, getuser() sería la cuenta del contenedor,
    # y firmar con ella sería inventar un autor.
    local = (f'{getpass.getuser()} (local)' if TABLERO_LOCAL
             else '(sesión sin autenticar)')
    try:
        cab = dict(session.http_conn.headers)
    except Exception:                                        # noqa: BLE001
        return local
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
    return local


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


def estado_actual(almacen=None, cliente=None, entradas_obj=None):
    """Lo que hay HOY en el almacén: entradas, metas e indicadores rehechos.

    La página trae horneado lo que había el día que se construyó. Sin esto,
    guardar funcionaba pero al recargar la pantalla volvía a enseñar lo de la
    última publicación: la captura estaba en S3 y la página decía lo contrario
    hasta el siguiente `actualizar.py`. Ahora, en cuanto la página se conecta,
    pide el estado vigente y se repinta con él. Es el mismo paquete que se
    devuelve después de guardar, armado en un solo sitio.
    """
    almacen = almacen or repo.almacen_por_defecto()
    cliente = cliente or repo.cliente_actual(almacen)
    ent = entradas_obj or em.cargar(almacen, cliente)
    series = None
    try:
        series = recalcular_series(ent, cliente)
    except Exception:                                        # noqa: BLE001
        # Sin indicadores rehechos la página sigue sirviendo: enseña los
        # horneados. Se registra para que alguien lo vea.
        print('ERROR al recalcular indicadores:', traceback.format_exc(),
              file=sys.stderr, flush=True)
    # La bitácora reciente también: lo recién guardado tiene que aparecer en
    # ella sin esperar la siguiente publicación. Mismo recorte que la que se
    # incrusta al construir (exportar_entradas.ASIENTOS_PUBLICADOS).
    try:
        import exportar_entradas as ee
        bitacora = bc.leer(almacen, cliente, ee.ASIENTOS_PUBLICADOS)
    except Exception:                                        # noqa: BLE001
        bitacora = None
    # Las metas de CADA empresa y del Grupo, igual que las publica kpis.json.
    ents = [e.iniciales for e in cliente.empresas if e.activa] + [CLAVE_GRUPO]
    return {'entradas': ent.entradas, 'metas': cliente.politica.todas_las_metas(ents),
            'series': series, 'bitacora': bitacora, 'bitacora_actos': bc.ACTOS}


def aplicar_metas(cambios_metas, autor):
    """Guarda una lista de {entidad, campo, valor | None} en las metas.

    Las reglas y la escritura viven en configurar.cambiar_metas(), que es lo
    mismo que usa `configurar.py --politica metas.x=y`: una sola puerta.
    """
    import configurar as cfg
    almacen = repo.almacen_por_defecto()
    cliente = repo.cliente_actual(almacen)
    aplicados, rechazados, _ = cfg.cambiar_metas(almacen, cliente.id, cambios_metas)
    for acto, entidad, clave, de, a in aplicados:
        bc.registrar(almacen, cliente, 'meta', autor,
                     {'campo': clave, 'empresa': entidad, 'de': de, 'a': a,
                      'tipo': acto}, origen='tablero')
    return aplicados, rechazados


def server(input, output, session):        # noqa: A002

    # En cuanto la página se conecta pide el estado vigente (ver estado_actual).
    @reactive.effect
    @reactive.event(input.pedir_estado)
    async def _estado():
        try:
            await session.send_custom_message('estado_actual', estado_actual())
        except Exception:                                    # noqa: BLE001
            # Si falla, la página se queda con lo horneado, que es lo mismo que
            # pasaba antes de existir esto. No vale tumbar la sesión por ello.
            print('ERROR al entregar el estado:', traceback.format_exc(),
                  file=sys.stderr, flush=True)

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
        lote = input.guardar_entradas() or {}
        autor = _autor_de(session)
        cambios = lote.get('cambios') or []
        metas = lote.get('metas') or {}
        # Se registra ANTES de intentar nada. Si el guardado revienta a la
        # mitad, esta línea es la que dice que la petición sí llegó — la
        # diferencia entre "el servidor no lo recibió" y "lo recibió y falló"
        # es media hora de búsqueda en el lugar equivocado.
        print(f'guardar_entradas: {len(cambios)} cambio(s) y {len(metas)} meta(s) '
              f'de {autor}', file=sys.stderr, flush=True)
        try:
            if not cambios and not metas:
                await session.send_custom_message(
                    'entradas_guardadas',
                    {'ok': False, 'mensaje': 'El lote no traía ningún cambio.'})
                return
            aplicados, rechazados, ent = [], [], None
            if cambios:
                aplicados, rechazados, _ = aplicar_lote(cambios, autor)
            if metas:
                a_m, r_m = aplicar_metas(metas, autor)
                aplicados += a_m
                rechazados += r_m
            print(f'  aplicados {len(aplicados)}, rechazados {len(rechazados)}',
                  file=sys.stderr, flush=True)
            # El estado COMPLETO tras guardar, no solo "salió bien" —entradas,
            # metas e indicadores rehechos—, para que la página se repinte con
            # la verdad y no con lo que traía desde que se construyó. Solo se
            # recalcula si de verdad se guardó algo: tras un lote rechazado
            # entero sería medio segundo para devolver lo mismo.
            estado = estado_actual() if aplicados else {}
            await session.send_custom_message('entradas_guardadas', dict(estado, **{
                'ok': not rechazados,
                'aplicados': len(aplicados),
                'rechazados': rechazados,
                'autor': autor,
            }))
        except Exception as e:                               # noqa: BLE001
            # El error se registra COMPLETO del lado del servidor y se le manda
            # al navegador uno corto. Un rastro de pila en la pantalla no le
            # dice nada a quien captura, y sí le dice de más a cualquiera que
            # abra la página.
            print('ERROR al guardar:', traceback.format_exc(),
                  file=sys.stderr, flush=True)
            await session.send_custom_message('entradas_guardadas', {
                'ok': False,
                'mensaje': f'No se pudo guardar ({type(e).__name__}). '
                           f'El detalle quedó en el registro del servidor.'})


# En modo local la página pide sus datos y librerías con rutas relativas
# (data/…, estaticos/…): se sirven desde dashboard/. Publicada, los pide al
# bucket por URL completa y esto no hace falta.
_estaticos = ({'/data': os.path.join(RAIZ, 'dashboard', 'data'),
               '/estaticos': os.path.join(RAIZ, 'dashboard', 'estaticos')}
              if TABLERO_LOCAL else None)

app = App(app_ui, server, static_assets=_estaticos)
