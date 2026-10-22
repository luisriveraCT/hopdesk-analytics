# -*- coding: utf-8 -*-
"""Comprueba que cada capacidad de CAPACIDADES.md siga teniendo sus piezas.

POR QUÉ EXISTE
--------------
Una capacidad se pierde sin ruido. Se borra una función que "ya nadie usaba",
se renombra un id, se quita un texto, y la pantalla se ve bien —simplemente le
falta algo que nadie revisa todos los días—. CAPACIDADES.md lista lo que la
app sabe hacer y qué pieza lo sostiene; esto comprueba que las piezas sigan
ahí, y cuando falta una dice el nombre de la capacidad, no solo el de la pieza.

No comprueba que la capacidad FUNCIONE —eso se mira en el navegador—, sino que
no se haya ido. Es la clase de pérdida que no se ve revisando.

    python verificar_capacidades.py
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
LISTA = os.path.join(RAIZ, 'CAPACIDADES.md')
PLANTILLA = os.path.join(AQUI, 'plantilla.html')


def main():
    lista = open(LISTA, encoding='utf-8').read()
    html = open(PLANTILLA, encoding='utf-8').read()
    idiomas = {}
    bloque = html[html.index('const I18N = {'):]
    for nombre, cuerpo in re.findall(r"^\s{2}(\w+):\s*\{(.*?)^\s{2}\},?$", bloque, re.S | re.M):
        if nombre in ('es', 'en'):
            idiomas[nombre] = set(re.findall(r"'([a-zA-Z0-9_.]+)'\s*:", cuerpo))

    def existe(pieza):
        if pieza.endswith('()'):
            n = re.escape(pieza[:-2])
            return re.search(r'function\s+' + n + r'\s*\(|(?:const|let)\s+' + n + r'\s*=', html)
        if pieza.startswith('#'):
            return f'id="{pieza[1:]}"' in html
        if pieza.startswith('css:'):
            return (pieza[4:] + '{') in html
        if pieza.startswith('t:'):
            return all(pieza[2:] in claves for claves in idiomas.values()) and idiomas
        return os.path.exists(os.path.join(RAIZ, pieza))

    capacidades = faltan = 0
    for fila in lista.splitlines():
        celdas = [c.strip() for c in fila.strip().strip('|').split('|')]
        if len(celdas) != 3 or celdas[0] in ('Capacidad', '---') or set(celdas[0]) <= {'-'}:
            continue
        piezas = re.findall(r'`([^`]+)`', celdas[2])
        if not piezas:
            continue
        capacidades += 1
        perdidas = [p for p in piezas if not existe(p)]
        if perdidas:
            faltan += 1
            print(f'  FALTA  {celdas[0]}: {", ".join(perdidas)}')

    print(f'\n{capacidades} capacidades revisadas')
    if faltan:
        print(f'{faltan} CAPACIDAD(ES) PERDIERON UNA PIEZA. Si fue a propósito, '
              f'actualiza CAPACIDADES.md; si no, algo se borró de más.')
        return 1
    print('OK — todas conservan sus piezas.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
