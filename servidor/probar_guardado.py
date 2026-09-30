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

    python probar_guardado.py [http://127.0.0.1:1914]

Necesita playwright:  pip install playwright && playwright install chromium
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')

URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:1914'
problemas = []


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
