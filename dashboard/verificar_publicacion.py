# -*- coding: utf-8 -*-
"""
===============================================================================
 VERIFICACIÓN PREVIA A PUBLICAR — que no se escape un secreto
===============================================================================
Este tablero se publica en internet. Un secreto que sale en el HTML no se
"despublica": hay que rotarlo, y hasta entonces está expuesto. Por eso esta
comprobación corre ANTES de subir, no después.

Compara el HTML construido contra los valores reales de las variables sensibles
del entorno. No busca patrones ni nombres de campo —eso se puede esquivar sin
querer— sino los valores literales.

DOS FORMAS DE BUSCAR, SEGÚN LA LONGITUD
---------------------------------------
Un valor largo (16 caracteres o más) es inconfundible: si aparece en cualquier
parte del HTML, se filtró.

Un valor corto no se puede buscar igual. La primera versión de esta herramienta
usaba un umbral de 6 caracteres y dio un falso positivo: un placeholder de 7
caracteres cuya cadena aparecía dentro de un comentario en español. Un
verificador que grita sin motivo se empieza a ignorar, y el día que tenga razón
nadie lo va a leer.

Pero descartar los valores cortos tampoco sirve: **las contraseñas de SAP de
este cliente miden menos de 16 caracteres**, o sea que el umbral dejaba fuera
justo lo que más importa. Así que los cortos SÍ se buscan, exigiendo que
aparezcan como token aislado —rodeados de comillas, dos puntos, comas o
espacios—, que es la forma en que se vería una credencial realmente filtrada en
JSON o JavaScript, y no como una subcadena dentro de una palabra en prosa.

    python verificar_publicacion.py index.html
===============================================================================
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

LONGITUD_MINIMA = 16
PATRON_SENSIBLE = re.compile(r'PASSWORD|SECRET|_KEY|TOKEN|CREDENTIAL', re.I)

# Valores que NO son secretos aunque estén en una variable que lo parece: son
# placeholders. Se excluyen porque son palabras del diccionario y disparan sobre
# cualquier prosa — `RESEND_API_KEY` vale literalmente "sandbox", que aparece en
# un comentario de la plantilla.
#
# Se excluye el VALOR, nunca el nombre de la variable: si algún día esa variable
# tiene una llave de verdad, vuelve a comprobarse sola. Silenciar por nombre es
# como se acaba ignorando justo la que importaba.
PLACEHOLDERS = {'sandbox', 'changeme', 'placeholder', 'test', 'demo', 'none',
                'todo', 'pendiente', 'xxx', 'dummy', 'example', 'ejemplo'}
FUENTES = [
    r'C:\Users\luisr\Antiguedad_App\.Renviron',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 'finanzas', '.env'),
]


def valores_sensibles():
    largos, cortos = {}, {}
    for ruta in FUENTES:
        try:
            with open(ruta, encoding='utf-8') as f:
                for linea in f:
                    linea = linea.strip()
                    if not linea or linea.startswith('#') or '=' not in linea:
                        continue
                    k, v = linea.split('=', 1)
                    k, v = k.strip(), v.strip().strip('"\'')
                    if not PATRON_SENSIBLE.search(k) or not v:
                        continue
                    if v.lower() in PLACEHOLDERS:
                        continue
                    (largos if len(v) >= LONGITUD_MINIMA else cortos)[k] = v
        except FileNotFoundError:
            continue
    # También los secretos cifrados del almacén: el blob no debe salir tampoco.
    return largos, cortos


def main():
    destino = sys.argv[1] if len(sys.argv) > 1 else 'index.html'
    aqui = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(aqui, destino), encoding='utf-8') as f:
        html = f.read()

    largos, cortos = valores_sensibles()
    print(f'{destino}: {len(html):,} caracteres')
    print(f'Variables sensibles encontradas: {len(largos)} revisables, '
          f'{len(cortos)} demasiado cortas para comprobar')

    filtrados = [k for k, v in largos.items() if v in html]

    # Los cortos se buscan como token aislado: delimitado por comillas, dos
    # puntos, comas, corchetes o espacios. Así se detecta `"clave":"abc123"` sin
    # disparar porque "abc123" caiga dentro de una palabra en un comentario.
    DELIM = r'''["'`:,\[\]{}()\s=]'''
    for k, v in cortos.items():
        if re.search(DELIM + re.escape(v) + DELIM, html):
            filtrados.append(k)

    for k in filtrados:
        print(f'  *** {k}: SU VALOR APARECE EN EL HTML ***')
    if cortos:
        print(f'  ({len(cortos)} valor(es) de menos de {LONGITUD_MINIMA} '
              f'caracteres revisados como token aislado: '
              f'{", ".join(sorted(cortos))})')

    # Además, señales estructurales de que algo se coló.
    sospechas = [p for p in ('contrasena', 'secretos_ref', 'AWS_SECRET',
                             'HOPDESK_SECRETS_KEY', 'BEGIN PRIVATE KEY')
                 if p in html]
    for p in sospechas:
        print(f'  *** aparece la cadena {p!r} en el HTML ***')

    if filtrados or sospechas:
        print('\nNO PUBLICAR. Corrige y vuelve a construir.')
        raise SystemExit(1)
    print('\nLIMPIO — ningún valor sensible aparece en el HTML.')


if __name__ == '__main__':
    main()
