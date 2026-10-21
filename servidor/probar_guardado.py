# -*- coding: utf-8 -*-
"""Prueba el guardado con un navegador de verdad, de punta a punta.

POR QUÉ CON UN NAVEGADOR Y NO POR WEBSOCKET
-------------------------------------------
Porque el fallo que motivó esta prueba **no se ve** desde el servidor.

Al hablarle al servidor por websocket, el guardado funcionaba perfectamente:
recibía, validaba, escribía en S3 y contestaba. En el navegador, el mismo
guardado llegaba al servidor y se aplicaba —el registro decía «aplicados 1,
rechazados 0»— pero la confirmación no volvía a la pantalla y el botón se
quedaba en "Guardando…" para siempre.

La causa estaba solo del lado del navegador: el manejador de la respuesta se
registraba escuchando `shiny:connected`, que Shiny emite con jQuery y que un
`addEventListener` nativo no atrapa de forma fiable.

Ninguna prueba del servidor podía encontrarlo. Esta sí.

QUÉ COMPRUEBA
-------------
  1. que la página reconozca que hay servidor (el botón dice "Guardar",
     no "Exportar cambios"),
  2. que al oprimirlo el dato llegue, se guarde y **vuelva la confirmación**,
  3. que lo pendiente se limpie solo cuando el servidor confirmó,
  4. que no haya errores de JavaScript en el camino.

    python probar_guardado.py [http://127.0.0.1:1914] [--si-es-produccion]

Necesita playwright:  pip install playwright && playwright install chromium

ESTA PRUEBA ESCRIBE DE VERDAD
-----------------------------
Captura un valor y lo guarda; es justo lo que comprueba, así que no hay forma
de que no escriba. Lo que sí se puede evitar es que escriba en el almacén de
producción sin que nadie lo haya decidido — que es lo que pasó la primera vez
que se corrió después de mover el almacén a S3: dejó un `NCS|*|rf` a nombre de
«(sesión local, sin autenticar)» que habría pisado el rf del grupo para NCS.

Lo correcto es levantar el servidor contra un prefijo aparte:

    set ALMACEN_S3_PREFIJO=config/pruebas
    python -m shiny run --port 1914 servidor/app.py

DENTRO de `config/`, no al lado: la politica IAM del perfil esta acotada a
`config/*`, y un prefijo hermano como `config-pruebas/` da AccessDenied.

Si el almacén resulta ser el que declara `almacen.json` —o sea, producción—
esta prueba se detiene y pide `--si-es-produccion` a propósito. Y entonces hay
que acordarse de borrar lo que dejó:

    python finanzas/entradas.py --borrar rf --empresa NCS --autor "..."
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, os.path.join(RAIZ, 'finanzas'))
sys.path.insert(0, os.path.join(RAIZ, 'finanzas', 'configuracion'))

ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
URL = ARGS[0] if ARGS else 'http://127.0.0.1:1914'
FORZAR = '--si-es-produccion' in sys.argv
problemas = []


DEL_SERVIDOR = None


def leer_almacen_del_servidor():
    """Qué almacén dice el servidor que usa, leído de la página que sirve.

    Se le pregunta A ÉL y no al entorno de este proceso: quien escribe es el
    servidor. Adivinarlo desde aquí hacía que poner una variable en la prueba
    abriera el seguro mientras los datos seguían yendo a producción — pasó, y
    dejó entradas de prueba en el almacén bueno tres veces.
    """
    global DEL_SERVIDOR
    try:
        import re
        import urllib.request
        with urllib.request.urlopen(URL, timeout=20) as r:
            html = r.read().decode('utf-8', 'replace')
        m = re.search(r'<meta name="almacen-activo" content="([^"]*)"', html)
        DEL_SERVIDOR = m.group(1) if m else None
    except Exception as e:                                   # noqa: BLE001
        print(f'  aviso: no se pudo preguntar al servidor por su almacén ({e})')
        DEL_SERVIDOR = None


def comprobar_destino():
    """Dónde va a escribir esto, y si hace falta que alguien lo autorice.

    Se compara el DESTINO —bucket y prefijo— contra el que declara
    `almacen.json`, no el origen de la decisión. La primera versión miraba el
    origen y se abría sola: en la máquina donde se desarrolla, las variables de
    entorno suelen estar puestas apuntando al mismo sitio de producción, así
    que el origen dejaba de ser `almacen.json` y el seguro no actuaba. Escribió
    en producción dos veces antes de que alguien lo notara.

    Se resuelve igual que lo resuelve la aplicación. Es una conjetura sobre un
    servidor local —por HTTP no hay forma de preguntárselo—, y por eso avisa en
    vez de prohibir cuando el destino no coincide con el declarado.
    """
    import repositorio as repo
    declarado = repo._declaracion()
    if str(declarado.get('tipo', '')).lower() != 's3':
        return True
    pref = str(declarado.get('prefijo', '')).strip().strip('/')
    produccion = (f'{declarado.get("bucket")}/{pref}' if pref
                  else str(declarado.get('bucket')))
    print(f'  producción es: {produccion}')
    if DEL_SERVIDOR is None:
        print('  (el servidor no dijo su almacén; se asume producción)')
    else:
        print(f'  el servidor usa: {DEL_SERVIDOR}')
    if DEL_SERVIDOR is not None and DEL_SERVIDOR != produccion:
        return True
    if FORZAR:
        print('  AVISO: se va a escribir en el almacén de producción '
              '(--si-es-produccion).')
        print('  Acuérdate de borrar la entrada que deje esta prueba.')
        return True
    print()
    print('  ALTO: ese es el almacén de producción y esta prueba escribe en él.')
    print('  Levanta el servidor contra un prefijo aparte:')
    print('      set ALMACEN_S3_PREFIJO=config/pruebas')
    print('  o acepta el riesgo a propósito con  --si-es-produccion')
    return False


def revisar(nombre, condicion, detalle=''):
    print(f'  {"OK  " if condicion else "FALLA"}  {nombre}'
          + (f'   {detalle}' if detalle else ''))
    if not condicion:
        problemas.append(nombre)


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('Falta playwright. Instálalo con:')
        print('    pip install playwright && playwright install chromium')
        return 2

    print(f'Guardado de punta a punta contra {URL}\n' + '=' * 70)
    leer_almacen_del_servidor()
    if not comprobar_destino():
        return 2
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        pg = nav.new_page()
        errores = []
        pg.on('pageerror', lambda e: errores.append(str(e)))
        try:
            pg.goto(f'{URL}/#entradas', wait_until='networkidle', timeout=60000)
            # Se espera a que Shiny se anuncie. Llega después de los scripts de
            # la página, así que preguntar de inmediato da siempre "no hay
            # servidor" — que fue exactamente el error que esto vigila.
            pg.wait_for_function('typeof Shiny !== "undefined"', timeout=20000)
            pg.wait_for_timeout(2500)

            revisar('la página reconoce que hay servidor',
                    pg.evaluate('enHayServidor()') is True)
            etiqueta = pg.inner_text('#enExportar').strip()
            revisar('el botón ofrece guardar, no exportar',
                    'uardar' in etiqueta, f'dice {etiqueta!r}')

            celda = pg.locator('.ecelda').first
            celda.fill('11.5')
            celda.dispatch_event('change')
            pg.wait_for_timeout(700)
            revisar('el cambio queda pendiente',
                    pg.evaluate('Object.keys(EN.cambios).length') > 0)

            pg.click('#enExportar')
            texto = ''
            for _ in range(25):
                pg.wait_for_timeout(1000)
                texto = pg.inner_text('#enExportar')
                if 'uardando' not in texto:
                    break
            revisar('el botón se recupera (no se queda cargando)',
                    'uardando' not in texto, f'quedó en {texto!r}')

            aviso = pg.inner_text('#toast')
            revisar('el servidor confirmó el guardado',
                    'uardado' in aviso, f'dijo {aviso[:80]!r}')
            revisar('lo pendiente se limpió tras confirmar',
                    pg.evaluate('Object.keys(EN.cambios).length') == 0)
            revisar('sin errores de JavaScript', not errores,
                    str(errores[:2]) if errores else '')
        finally:
            nav.close()

    print()
    if problemas:
        print(f'{len(problemas)} PROBLEMA(S):')
        for p in problemas:
            print(f'   · {p}')
        return 1
    print('OK — se escribe en la hoja, se guarda y vuelve la confirmación.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
