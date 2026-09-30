# -*- coding: utf-8 -*-
"""Comprueba que todo lo que llama un bloque de JS esté a nivel de módulo.

Nace de un error cometido dos veces: insertar un bloque dentro del cuerpo de
otra función deja sus definiciones en ese alcance, y cualquier llamada desde
fuera revienta con ReferenceError. El panel de Ajustes quedó dentro de
bindGlosario() y la pestaña de Estados Financieros dejó de pintar por eso.

Un archivo de 3,000 líneas no permite verlo a simple vista, y el síntoma —una
sección en blanco— no señala la causa.
"""
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

ruta, marca_inicio = sys.argv[1], sys.argv[2]
s = open(ruta, encoding='utf-8').read()

# Definiciones a nivel de módulo: empiezan en la columna 0.
nivel_modulo = set(re.findall(r'^(?:async\s+)?(?:function|const|let|var)\s+(\w+)',
                              s, re.M))
nivel_modulo |= set(re.findall(r'^(\w+)\s*=', s, re.M))

bloque = s[s.index(marca_inicio):]
# Si el corte cae DENTRO de un comentario de bloque, su `/*` queda fuera del
# trozo y el texto se analiza como si fuera código: la prosa en español produce
# "llamadas" inexistentes ("del agregado (ver...)" parece agregado(...)). Se
# descarta lo que haya antes del primer cierre de comentario cuando no hay
# apertura previa.
primer_cierre = bloque.find('*/')
primera_apertura = bloque.find('/*')
if primer_cierre != -1 and (primera_apertura == -1 or primer_cierre < primera_apertura):
    bloque = bloque[primer_cierre + 2:]
# Quitar cadenas y comentarios para no analizar prosa.
b = re.sub(r'/\*.*?\*/', ' ', bloque, flags=re.S)
b = re.sub(r'//[^\n]*', ' ', b)
b = re.sub(r'`(?:\\.|[^`\\])*`', ' ', b, flags=re.S)
b = re.sub(r"'(?:\\.|[^'\\\n])*'", ' ', b)
b = re.sub(r'"(?:\\.|[^"\\\n])*"', ' ', b)

# Lo definido dentro del propio bloque (incluye parámetros y locales).
locales = set(re.findall(r'(?:function|const|let|var)\s+(\w+)', b))
# Declaraciones DESESTRUCTURADAS: `const {jsPDF} = window.jspdf` y
# `const [a, b] = ...`. Sin esto, lo que se saca de un objeto se reportaba como
# fuera de alcance — que es lo contrario de lo que es: no hay nada más local.
for grupo in re.findall(r'(?:const|let|var)\s*[{\[]([^}\]]*)[}\]]\s*=', b):
    # Se toma el nombre de cada enlace, incluido el de `{a: b}` donde el que
    # queda declarado es `b`, no `a`.
    for par in grupo.split(','):
        nombres = re.findall(r'\w+', par)
        if nombres:
            locales.add(nombres[-1])
# Parámetros de funciones nombradas. Sin esto, una función que recibe una
# retrollamada y la invoca por su nombre de parámetro se reporta como fuera de
# alcance — que es justo lo contrario de lo que pasa: es lo más local que hay.
for grupo in re.findall(r'function\s+\w+\s*\(([^)]*)\)', b):
    locales |= set(re.findall(r'\w+', grupo))
locales |= set(re.findall(r'\(([^)]*)\)\s*=>', b)) and set(
    w for grupo in re.findall(r'\(([^)]*)\)\s*=>', b)
    for w in re.findall(r'\w+', grupo))
locales |= set(re.findall(r'(\w+)\s*=>', b))
locales |= set(re.findall(r'for\s*\(\s*(?:const|let|var)\s+(\w+)', b))
locales |= set(re.findall(r'\.forEach\(\s*(\w+)\s*=>', b))

GLOBALES_JS = {
    'document', 'window', 'console', 'Math', 'JSON', 'Object', 'Array', 'String',
    'Number', 'Boolean', 'Date', 'Intl', 'Map', 'Set', 'Promise', 'parseInt',
    'parseFloat', 'isFinite', 'isNaN', 'setTimeout', 'clearTimeout', 'fetch',
    'encodeURIComponent', 'decodeURIComponent', 'Blob', 'URL', 'navigator',
    'localStorage', 'alert', 'undefined', 'null', 'true', 'false', 'NaN',
    'Infinity', 'requestAnimationFrame', 'XMLSerializer', 'Image', 'atob', 'btoa',
    # Métodos de `window` que se llaman sin escribir `window.`. Son globales
    # legítimas; sin ellas aquí, el verificador reportaba una falsa alarma
    # permanente, y una herramienta que siempre marca algo deja de leerse.
    'addEventListener', 'removeEventListener', 'print', 'open', 'scrollTo',
    'matchMedia', 'getComputedStyle', 'structuredClone', 'queueMicrotask',
    'setInterval', 'clearInterval', 'crypto', 'location', 'history',
}

# Solo llamadas DIRECTAS. Las precedidas de punto son métodos de un objeto
# (`lista.map(...)`, `texto.slice(...)`) y no dependen del alcance del módulo;
# incluirlas llenaba el reporte de falsos positivos y escondía el único
# hallazgo real.
llamadas = set(re.findall(r'(?<![.\w])(\w+)\s*\(', b))
faltan = sorted(c for c in llamadas
                if c not in nivel_modulo and c not in locales
                and c not in GLOBALES_JS and not c[0].isupper()
                and not re.match(r'^(if|for|while|switch|catch|return|typeof|'
                                 r'function|new|await|of|in)$', c))

print(f'Bloque desde {marca_inicio[:44]!r}')
print(f'  {len(llamadas)} llamadas distintas')
if faltan:
    print('  POSIBLEMENTE FUERA DE ALCANCE:')
    for f in faltan:
        # ¿existe pero anidada?
        anidada = re.search(r'^\s+(?:function|const|let)\s+' + re.escape(f) + r'\b',
                            s, re.M)
        estado = ('definida CON INDENTACIÓN (dentro de otra función)'
                  if anidada else 'no se encuentra definida')
        print(f'     {f}: {estado}')
    sys.exit(1)
print('  OK — todo lo que llama está a nivel de módulo o es local suyo.')
