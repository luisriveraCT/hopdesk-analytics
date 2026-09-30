# -*- coding: utf-8 -*-
"""
===============================================================================
 SUBE EL TABLERO AL ALMACÉN PRIVADO
===============================================================================
Deja `index.html` en el almacén para que lo lea la aplicación de `servidor/`.

POR QUÉ NO VIAJA CON EL CÓDIGO
-------------------------------
Connect Cloud publica las aplicaciones de Python desde un repositorio de
GitHub. Y este archivo pesa un megabyte y medio porque lleva **dentro** los
estados financieros y los indicadores del grupo — no son una referencia a unos
datos, son los datos.

Meter eso en un repositorio es publicar las cifras del negocio en un sitio que
nadie vuelve a revisar, y con la historia de Git no se borra: queda en cada
copia que alguien haya clonado.

Así que cada cosa viaja por donde le toca:

    el CÓDIGO por Git   — cambia cuando alguien programa
    los DATOS por S3    — cambian cada vez que se actualiza

De paso resuelve el problema práctico: publicar un tablero nuevo es correr
`actualizar.py`. No hay que tocar Git ni volver a desplegar la aplicación.

VA AL PREFIJO PRIVADO, NO AL PÚBLICO
-------------------------------------
Al mismo `config/` donde vive la configuración, que ya se comprobó que no
contesta sin credenciales. El prefijo `data/` del mismo bucket SÍ es de lectura
pública —ahí viven los trozos de facturación que el navegador pide por URL— y
este archivo no puede acabar ahí.

    python publicar_tablero.py              sube
    python publicar_tablero.py --simular    dice qué haría
===============================================================================
"""
import os
import sys
import argparse
import datetime as dt

sys.stdout.reconfigure(encoding='utf-8')

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, os.path.join(RAIZ, 'finanzas'))
sys.path.insert(0, os.path.join(RAIZ, 'finanzas', 'configuracion'))

import repositorio as repo                    # noqa: E402

CLAVE = 'tablero/index.html'
# La base con la que el servidor recalcula los indicadores cuando alguien
# cambia un supuesto. Sin ella, el servidor guarda pero no puede rehacer los
# números, y la pantalla no se mueve.
CLAVE_BASE = 'tablero/base_financiera.json'
MARCADOR = '<meta name="shiny-dependency-placeholder" content="">'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--simular', action='store_true')
    args = ap.parse_args()

    ruta = os.path.join(AQUI, 'index.html')
    if not os.path.exists(ruta):
        raise SystemExit('No hay index.html que subir. Constrúyelo primero.')
    with open(ruta, encoding='utf-8') as f:
        html = f.read()

    # PUNTO DE PARO. Sin el marcador, la aplicación serviría la página sin el
    # canal de Shiny: se vería idéntica y el botón de guardar caería al modo
    # archivo, sin nada que explicara por qué dejó de guardar.
    if MARCADOR not in html:
        raise SystemExit(
            'ALTO: este index.html no trae el marcador de dependencias de\n'
            'Shiny, así que la aplicación lo serviría SIN poder guardar.\n'
            'El marcador está en dashboard/plantilla.html, junto a los <meta>.')

    almacen = repo.almacen_por_defecto()
    destino = repo.descripcion_almacen()
    kb = len(html.encode('utf-8')) / 1024

    if 'disco local' in destino:
        print(f'  aviso: el almacén es {destino}.')
        print('  La aplicación de Connect no va a poder leer de ahí. Define')
        print('  ALMACEN_S3_BUCKET para que esto sirva de algo.')

    if args.simular:
        print(f'  (simulación) se subirían {kb:.0f} KB a {destino} → {CLAVE}')
        return 0

    _, version = almacen.leer(CLAVE)
    almacen.escribir(CLAVE, {
        'html': html,
        'generado': dt.datetime.now().isoformat(timespec='seconds'),
        'bytes': len(html.encode('utf-8')),
    }, version)
    print(f'  tablero publicado: {kb:.0f} KB → {destino} → {CLAVE}')

    # La base del recálculo. Va junto al tablero y no en el repositorio: son
    # cifras del negocio, aunque sean intermedias.
    ruta_base = os.path.join(AQUI, 'base_financiera.json')
    if os.path.exists(ruta_base):
        import json as _json
        with open(ruta_base, encoding='utf-8') as f:
            base = _json.load(f)
        _, v = almacen.leer(CLAVE_BASE)
        almacen.escribir(CLAVE_BASE, base, v)
        print(f'  base del recálculo: '
              f'{os.path.getsize(ruta_base)/1024:.0f} KB → {CLAVE_BASE}')
    else:
        print('  aviso: no hay base_financiera.json. El servidor va a poder')
        print('  guardar, pero NO recalcular los indicadores al hacerlo.')

    print('  La aplicación lo toma en su próximo arranque.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
