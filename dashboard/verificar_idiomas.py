# -*- coding: utf-8 -*-
"""Comprueba que ninguna clave de texto falte en ningún idioma.

POR QUÉ HACE FALTA UNA HERRAMIENTA PARA ESTO
--------------------------------------------
Una clave que no existe en el diccionario no truena: `t()` devuelve la clave o
una cadena vacía, y el resultado es una etiqueta en blanco o un texto críptico
en medio de una tabla. Nadie lo nota en español si la clave se agregó en
español; se nota en inglés, semanas después, y para entonces no hay forma de
relacionarlo con el cambio que lo causó.

El caso peor es el inverso: una clave que sí existe en un idioma y no en el
otro. La pantalla se ve perfecta mientras se revise en el idioma en que se
escribió.

QUÉ CUENTA COMO USO
-------------------
  · t('clave') en el JavaScript
  · data-i18n, data-i18n-ph y data-help en el HTML
  · claves armadas por concatenación: t('tf.du.' + k). De éstas solo se ve el
    prefijo, así que se expanden con los valores posibles declarados abajo.

    Esa lista hay que mantenerla a mano, y es su única debilidad. Se prefiere
    así a no comprobar las claves dinámicas: son justo las que más fácil se
    olvidan al agregar una entrada nueva a una familia.

    python verificar_idiomas.py plantilla.html
"""
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

ruta = sys.argv[1] if len(sys.argv) > 1 else 'plantilla.html'
s = open(ruta, encoding='utf-8').read()

# Los idiomas que el tablero ofrece. Se leen del selector para no mantener dos
# listas: si mañana se agrega uno, esta comprobación lo cubre sola.
IDIOMAS = sorted(set(re.findall(r"LANG\s*===\s*'(\w+)'", s))
                 | {'es', 'en'})

# Familias de claves que se arman concatenando. Cada entrada es
# (prefijo, [sufijos]) y se expande al producto.
DINAMICAS = [
    ('tf.fam.', ['rentabilidad', 'rendimiento', 'ciclo', 'deuda', 'liquidez']),
    ('tf.fam.', [f'{x}.s' for x in
                 ('rentabilidad', 'rendimiento', 'ciclo', 'deuda', 'liquidez')]),
    ('tf.du.', ['carga_fiscal', 'carga_intereses', 'margen_ebit',
                'rotacion_activos', 'apalancamiento', 'roe', 'descuadre']),
    ('tf.w.', ['rf', 'beta', 'erp', 'kd', 'tasa', 'tasa.n', 'tasa.nofiable',
               'ke', 'wacc', 'wacc.n']),
    ('disc.m.', ['ver', 'estructura', 'ocultar']),
    ('f.ic.', ['todo', 'solo', 'excluir']),
    ('f.cn.', ['incluir', 'excluir', 'solo']),
]


def diccionarios():
    """{idioma: {claves}} leyendo solo los bloques que son idiomas.

    Se filtra por nombre contra IDIOMAS en vez de tomar todo lo que parezca un
    objeto anidado: dentro de I18N hay bloques que no son traducciones, y
    contarlos produce cientos de faltantes inventados.
    """
    bloque = s[s.index('const I18N = {'):]
    out = {}
    for nombre, cuerpo in re.findall(r"^\s{2}(\w+):\s*\{(.*?)^\s{2}\},?$",
                                     bloque, re.S | re.M):
        if nombre in IDIOMAS:
            out[nombre] = set(re.findall(r"'([a-zA-Z0-9_.]+)'\s*:", cuerpo))
    return out


def usadas():
    # Se quitan los comentarios ANTES de buscar. La documentación del archivo
    # trae ejemplos escritos con la misma forma que el código —incluido el
    # ejemplo de qué pasa con una clave sin definir— y contarlos como uso
    # produce faltantes que no existen. Una herramienta que reporta problemas
    # inventados se deja de leer, y entonces tampoco reporta los reales.
    sin_com = re.sub(r'<!--.*?-->', ' ', s, flags=re.S)
    sin_com = re.sub(r'/\*.*?\*/', ' ', sin_com, flags=re.S)
    sin_com = re.sub(r'^\s*//[^\n]*', ' ', sin_com, flags=re.M)

    # Cualquier literal dentro de t(...), lo que cubre t('a') y también
    # t(cond ? 'a' : 'b'), que es como se eligen varias etiquetas.
    u = set()
    for args in re.findall(r"\bt\(([^()]*)\)", sin_com):
        u |= set(re.findall(r"'([a-zA-Z0-9_.]+)'", args))
    for attr in ('data-i18n', 'data-i18n-ph', 'data-help'):
        u |= set(re.findall(attr + r'="([a-zA-Z0-9_.]+)"', sin_com))
    for prefijo, sufijos in DINAMICAS:
        u |= {prefijo + x for x in sufijos}
    # Los pedazos que deja la concatenación no son claves: ni el prefijo suelto
    # de t('tf.fam.' + id) ni el sufijo suelto de + '.s'.
    return {k for k in u if not k.endswith('.') and not k.startswith('.')}


def main():
    dic = diccionarios()
    if not dic:
        print('No se encontró ningún diccionario de idioma.')
        return 1
    u = usadas()
    print(f'idiomas: {", ".join(sorted(dic))}')
    for idioma, claves in sorted(dic.items()):
        print(f'  {idioma}: {len(claves)} claves definidas')
    print(f'claves usadas: {len(u)}')

    problemas = 0
    for idioma, claves in sorted(dic.items()):
        faltan = sorted(u - claves)
        if faltan:
            problemas += len(faltan)
            print(f'\nSIN TRADUCIR en {idioma} ({len(faltan)}):')
            for k in faltan:
                print(f'   {k}')

    # Claves que existen en un idioma y no en otro. Es el caso que no se ve
    # revisando la pantalla en el idioma en que se escribió.
    todas = set().union(*dic.values())
    for idioma, claves in sorted(dic.items()):
        solo_falta = sorted(todas - claves)
        if solo_falta:
            problemas += len(solo_falta)
            print(f'\nEXISTE EN OTRO IDIOMA PERO NO EN {idioma} ({len(solo_falta)}):')
            for k in solo_falta:
                print(f'   {k}')

    # Definidas y nunca usadas. No rompen nada, pero envejecen: alguien las lee
    # como si describieran algo que la aplicación hace.
    huerfanas = sorted(todas - u)
    if huerfanas:
        print(f'\nDefinidas y sin usar ({len(huerfanas)}) — no es un error, '
              f'pero conviene depurarlas:')
        for k in huerfanas[:30]:
            print(f'   {k}')
        if len(huerfanas) > 30:
            print(f'   … y {len(huerfanas) - 30} más')

    print('\n' + ('OK — todos los idiomas están completos y parejos.'
                  if not problemas else f'{problemas} PROBLEMA(S)'))
    return 1 if problemas else 0


if __name__ == '__main__':
    sys.exit(main())
