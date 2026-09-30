# -*- coding: utf-8 -*-
r"""
===============================================================================
 refrescar.py — PUBLICAR EL TABLERO EN LÍNEA
===============================================================================
Sube lo que ya está construido: los datos al bucket de S3 y el HTML a Posit
Connect Cloud. No construye nada — eso lo hace `actualizar.py`.

    python refrescar.py                 sube datos y redespliega el HTML
    python refrescar.py --solo-subir    solo los datos a S3
    python refrescar.py --solo-html     solo el redespliegue del HTML
    python refrescar.py --simular       dice qué haría, sin tocar nada

POR QUÉ SON DOS DESTINOS Y NO UNO
---------------------------------
El tablero se sirve en dos piezas y viven en lugares distintos:

  · **index.html** — la página. Va a Posit Connect Cloud, que es donde el
    equipo la abre y donde se controla quién puede verla.
  · **data/*.json** — los chunks de facturación, ~12 MB. Van a S3 y la página
    los pide por URL. No se incrustan en el HTML porque lo harían pesar
    demasiado para abrirlo en una conexión lenta.

Los estados financieros y los indicadores sí van incrustados en el HTML: pesan
poco al lado de los chunks y así esas pestañas abren sin esperar red.

QUÉ PASÓ CON LA VERSIÓN ANTERIOR DE ESTE ARCHIVO
------------------------------------------------
Hasta el 2026-09-26 este script era el orquestador completo del pipeline de
Excel: reconsolidaba los archivos de origen, revisaba si el formato de alguno
había cambiado, exportaba, construía y subía. Todo eso quedó obsoleto cuando la
fuente de verdad pasó al ERP, y los pasos de Excel se eliminaron con el resto.

Se conserva el NOMBRE y la posición en la raíz por dos razones: `actualizar.py
--subir` lo llama por ahí, y es donde alguien lo va a buscar. La versión vieja
estuvo un tiempo en `legacy/`, y el resultado fue que `--subir` quedó apuntando
a un archivo que ya no estaba ahí —con una bandera que además nunca existió—,
así que la subida llevaba tiempo fallando en silencio.

LA SUBIDA A S3 NO ESTÁ AQUÍ, Y ES A PROPÓSITO
----------------------------------------------
La hace `dashboard/publicar.py`, que además **borra del bucket lo que ya no
corresponde**. Esa limpieza importa: al cambiar de fuente, el bucket conservó
archivos que solo existían en la base de Excel y siguió sirviéndolos dos días.
Tener dos códigos que suben lo mismo garantiza que un día solo uno limpie.
===============================================================================
"""
import os
import re
import sys
import json
import argparse
import subprocess

sys.stdout.reconfigure(encoding='utf-8')
# También stderr: los mensajes de los puntos de paro salen por ahí, y en la
# consola de Windows sus acentos se veían como rombos negros justo cuando más
# hace falta leer el mensaje entero.
sys.stderr.reconfigure(encoding='utf-8')

AQUI = os.path.dirname(os.path.abspath(__file__))
TABLERO = os.path.join(AQUI, 'dashboard')
PY = sys.executable

# ---------------------------------------------------------------------------
# Destino del HTML — configuración de ESTA instalación
# ---------------------------------------------------------------------------
# Esto no es configuración del cliente (eso vive en finanzas/configuracion/):
# es de la máquina y la cuenta desde la que se publica. Por eso se puede
# sobrescribir con variables de entorno, que es como se configura un servidor
# de integración sin editar el archivo.
#
# Connect Cloud publica contenido estático a través del paquete de R
# `rsconnect` (`rsconnect::deployApp`), no de rsconnect-python — se probó en
# vivo. `rsconnect` guarda el registro del despliegue anterior en
# `dashboard/rsconnect/`, así que volver a correr el mismo `deployApp()`
# ACTUALIZA el contenido existente en vez de crear uno nuevo. Por eso aquí no
# hace falta guardar ningún identificador.
RSCRIPT = os.environ.get(
    'RSCRIPT_PATH', r'C:\Program Files\R\R-4.5.2\bin\Rscript.exe')
TITULO_CONNECT = os.environ.get('CONNECT_TITULO', 'Analitica Financiera')


def paso(titulo):
    print(f'\n{"─" * 72}\n  {titulo}\n{"─" * 72}')


def subir_datos(simular=False):
    """Los chunks a S3, delegando en quien sabe limpiar el bucket."""
    args = ['--simular'] if simular else []
    r = subprocess.run([PY, os.path.join(TABLERO, 'publicar.py')] + args,
                       cwd=TABLERO)
    if r.returncode != 0:
        raise SystemExit(f'La publicación a S3 falló (código {r.returncode}).')


def comprobar_modo_del_html(ruta_html):
    """PUNTO DE PARO: que el index.html que se va a publicar lea los datos de S3.

    Connect Cloud recibe UN archivo, index.html, y nada más. Un index.html
    construido en modo local apunta a "data/rows-2024.json" — rutas que en
    Connect no existen. La página abre perfectamente, la barra de carga llega
    al final y el punto se pone verde, y las cuatro pestañas salen en cero con
    un "Sin datos con los filtros actuales" que parece un problema de filtros.

    Pasó: alguien corrió `actualizar.py --ver` (que construye en local, y debe
    hacerlo) y después publicó. Nada en el camino se quejó. Por eso se
    comprueba aquí, que es el último punto donde todavía se puede evitar.
    """
    html = open(ruta_html, encoding='utf-8').read()
    m = re.search(r'const CHUNKS = (\[.*?\]);', html, re.S)
    if not m:
        raise SystemExit(
            'No se encontró el arreglo CHUNKS en index.html. O no está '
            'construido, o la plantilla cambió de forma:\n'
            '    python actualizar.py --solo-tablero')
    try:
        chunks = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise SystemExit(f'El arreglo CHUNKS de index.html no es JSON válido: {e}')
    locales = [c['archivo'] for c in chunks
               if not str(c.get('archivo', '')).startswith('http')]
    if locales:
        raise SystemExit(
            'ALTO: este index.html está construido en MODO LOCAL.\n'
            f'  {len(locales)} de {len(chunks)} archivos de datos apuntan a rutas\n'
            f'  relativas (p. ej. {locales[0]!r}).\n'
            '  A Connect Cloud solo sube index.html, así que esas rutas no van a\n'
            '  existir y el tablero saldría en ceros sin avisar.\n'
            '  Reconstrúyelo apuntando a S3 y vuelve a intentar:\n'
            '      python dashboard\construir.py --modo s3')
    print(f'  index.html lee sus {len(chunks)} archivos de datos de S3. Correcto.')


def redesplegar_html(simular=False):
    """El HTML a Posit Connect Cloud.

    Se despliega SOLO index.html. Subir la carpeta entera llevaría también los
    scripts de exportación, la plantilla y —lo que importa— los archivos de
    datos intermedios. No hay secretos ahí, pero tampoco tienen por qué estar
    publicados, y cada uno es una URL más que alguien puede pedir.
    """
    ruta_html = os.path.join(TABLERO, 'index.html')
    if not os.path.exists(ruta_html):
        raise SystemExit(
            'No hay dashboard/index.html que publicar. Constrúyelo primero:\n'
            '    python actualizar.py --solo-tablero')
    # Se comprueba también en --simular: el sentido de simular es enterarse de
    # esto antes, no después.
    comprobar_modo_del_html(ruta_html)

    codigo_r = (
        'rsconnect::deployApp('
        f'appDir = {TABLERO!r}, '
        'appFiles = "index.html", '
        f'appTitle = {TITULO_CONNECT!r}, '
        'forceUpdate = TRUE, launch.browser = FALSE)'
    ).replace("'", '"')
    cmd = [RSCRIPT, '-e', codigo_r]

    if simular:
        print('  (simulación) se correría:')
        print('  $', ' '.join(cmd))
        return
    if not os.path.exists(RSCRIPT):
        raise SystemExit(
            f'No se encontró Rscript en {RSCRIPT}.\n'
            f'Connect Cloud publica contenido estático vía el paquete de R '
            f'`rsconnect`. Si R está en otra ruta:\n'
            f'    set RSCRIPT_PATH=C:\\ruta\\a\\Rscript.exe')
    print('  $', ' '.join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise SystemExit(f'El redespliegue a Connect Cloud falló (código {r.returncode}).')


def main():
    ap = argparse.ArgumentParser(
        description='Publica el tablero ya construido: datos a S3 y HTML a Connect.')
    ap.add_argument('--solo-subir', action='store_true',
                    help='solo los datos a S3')
    ap.add_argument('--solo-html', action='store_true',
                    help='solo el redespliegue del HTML')
    ap.add_argument('--simular', action='store_true',
                    help='dice qué haría, sin tocar nada')
    args = ap.parse_args()

    hacer_datos = not args.solo_html
    hacer_html = not args.solo_subir

    if hacer_datos:
        paso('Datos del tablero → S3')
        subir_datos(args.simular)
    if hacer_html:
        paso('index.html → Posit Connect Cloud')
        redesplegar_html(args.simular)

    print('\nListo.' if not args.simular else '\nSimulación terminada; no se tocó nada.')


if __name__ == '__main__':
    main()
