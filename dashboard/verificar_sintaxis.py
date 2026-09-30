# -*- coding: utf-8 -*-
"""Verifica la sintaxis del JavaScript incrustado en el tablero, con un parser
de verdad (esprima) en vez de balancear llaves a ojo.

Se hizo así después de que un verificador casero basado en expresiones
regulares acusara dos errores inexistentes: en un archivo con plantillas
anidadas y divisiones, el análisis léxico por regex no es aproximado, es
inservible. Vale más instalar un parser que confiar en un semáforo que miente.

    python chk_js.py index.html
"""
import re
import sys

import esprima

sys.stdout.reconfigure(encoding='utf-8')
ruta = sys.argv[1]
s = open(ruta, encoding='utf-8').read()

# Los comentarios HTML se quitan ANTES de buscar <script>: el bloque de
# instrucciones para desarrolladores menciona la etiqueta en prosa, y sin esto
# el verificador intenta parsear un párrafo en español y reporta un error que
# no existe.
s_sin_comentarios = re.sub(r'<!--.*?-->', ' ', s, flags=re.S)
bloques = re.findall(r'<script>(.*?)</script>', s_sin_comentarios, re.S)
print(f'bloques <script>: {len(bloques)}')

problemas = 0
for i, b in enumerate(bloques, 1):
    # esprima 4 llega hasta ES2017 y el tablero usa `??` (ES2020). Para una
    # revisión de SINTAXIS basta sustituirlo por un operador equivalente en
    # forma: no se ejecuta nada, solo se parsea. Lo que no se puede es aceptar
    # un "error" que solo existe en el parser.
    b_chk = b.replace('??', '||').replace('?.', '.')
    try:
        esprima.parseScript(b_chk, {'tolerant': False})
        print(f'  bloque {i}: sintaxis OK ({len(b):,} car.)')
    except Exception as e:
        print(f'  bloque {i}: ERROR DE SINTAXIS -> {e}')
        m = re.search(r'Line (\d+)', str(e))
        if m:
            ln = int(m.group(1))
            for j in range(max(0, ln - 3), min(len(b.splitlines()), ln + 2)):
                marca = '>>' if j == ln - 1 else '  '
                print(f'     {marca} {j+1}: {b.splitlines()[j][:110]}')
        problemas += 1

sin = [m for m in ('__META_JSON__', '__CHUNKS_JSON__', '__BITACORA_JSON__') if m in s]
if sin:
    print('  MARCADORES SIN SUSTITUIR:', sin)
    problemas += 1

print('RESULTADO:', 'OK' if not problemas else f'{problemas} problema(s)')
sys.exit(1 if problemas else 0)
