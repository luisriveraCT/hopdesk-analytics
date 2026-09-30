# -*- coding: utf-8 -*-
"""Comprueba que el botón de guardar pueda funcionar contra el servidor.

POR QUÉ HACE FALTA UNA HERRAMIENTA PARA ESTO
--------------------------------------------
El guardado falla MUDO. Cuando se rompe, el botón se queda en "Guardando…"
para siempre, el servidor no registra nada, y no hay error en ningún lado: se
ve exactamente igual que si el clic nunca hubiera ocurrido.

Pasó, y costó encontrarlo. La página mandaba el valor con
`priority: "event"`, que es una opción de Shiny para **R**. El Shiny de Python
la rechaza con «No input handler registered for type: shiny.event» y descarta
el envío entero, sin contestar nada.

Son tres piezas que tienen que coincidir y viven en archivos distintos:

  1. la página manda a un nombre de entrada,
  2. el servidor escucha ese mismo nombre,
  3. la página escucha el nombre del mensaje de vuelta que el servidor manda.

Cualquiera de las tres que se renombre sin las otras produce el mismo silencio.

    python verificar_guardado.py index.html
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

AQUI = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(AQUI), 'servidor', 'app.py')

ruta = sys.argv[1] if len(sys.argv) > 1 else os.path.join(AQUI, 'index.html')
html_crudo = open(ruta, encoding='utf-8').read()
app_crudo = open(APP, encoding='utf-8').read() if os.path.exists(APP) else ''


def _sin_comentarios(s, estilo):
    """Quita comentarios antes de buscar.

    Hace falta por la misma razón que en el verificador de idiomas: los
    comentarios de este código EXPLICAN el error que se busca, y nombrarlo es
    la forma de que nadie lo reintroduzca. Sin este filtro, la explicación de
    por qué no usar `priority: "event"` se cuenta como un uso de
    `priority: "event"`, y la herramienta reporta un problema que ella misma
    inventó. Una herramienta que siempre marca algo se deja de leer.
    """
    if estilo == 'js':
        s = re.sub(r'<!--.*?-->', ' ', s, flags=re.S)
        s = re.sub(r'/\*.*?\*/', ' ', s, flags=re.S)
        return re.sub(r'^\s*//[^\n]*', ' ', s, flags=re.M)
    s = re.sub(r'"""(?:.|\n)*?"""', ' ', s)
    return re.sub(r'^\s*#[^\n]*', ' ', s, flags=re.M)


html = _sin_comentarios(html_crudo, 'js')
app = _sin_comentarios(app_crudo, 'py')

problemas = []


def revisar(nombre, condicion, detalle=''):
    print(f'  {"OK  " if condicion else "FALLA"}  {nombre}'
          + (f'   {detalle}' if detalle and not condicion else ''))
    if not condicion:
        problemas.append(nombre)


print('Guardado contra el servidor\n' + '=' * 70)

# 1. La opción que rompe el envío, y que se ve inofensiva.
revisar('la página NO usa priority:"event" (es de Shiny para R)',
        "priority: 'event'" not in html and 'priority: "event"' not in html,
        'py-shiny lo rechaza y descarta el envío sin avisar')

# 2. Los tres nombres coinciden.
envios = set(re.findall(r"setInputValue\(\s*['\"]([\w.]+)['\"]", html))
escuchas = set(re.findall(r"input\.(\w+)\(\)", app)) | set(
    re.findall(r"reactive\.event\(input\.(\w+)\)", app))
revisar('la página manda a alguna entrada', bool(envios), 'no se encontró setInputValue')
revisar('el servidor escucha lo que la página manda',
        bool(envios & escuchas), f'manda {sorted(envios)}, escucha {sorted(escuchas)}')

manda_srv = set(re.findall(r"send_custom_message\(\s*['\"](\w+)['\"]", app))
oye_pag = set(re.findall(r"addCustomMessageHandler\(\s*['\"](\w+)['\"]", html))
revisar('la página escucha la respuesta del servidor',
        bool(manda_srv & oye_pag),
        f'servidor manda {sorted(manda_srv)}, página oye {sorted(oye_pag)}')

# 3. Sin el marcador, la página se sirve sin el canal de Shiny.
revisar('la página trae el marcador de dependencias de Shiny',
        'shiny-dependency-placeholder' in html_crudo
        or 'shiny.js' in html_crudo,
        'sin él, `ui.page_html` no inserta shiny.js y el guardado cae al modo archivo')

# 4. Un envío repetido tiene que verse distinto, o Shiny no dispara nada.
revisar('cada envío se distingue del anterior',
        're.envio' in html.replace('EN.envio', 're.envio') or 'EN.envio' in html,
        'sin un valor que cambie, reintentar un guardado fallido no hace nada')

print()
if problemas:
    print(f'{len(problemas)} PROBLEMA(S) — el guardado fallaría en silencio:')
    for p in problemas:
        print(f'   · {p}')
    sys.exit(1)
print('OK — las tres piezas del guardado coinciden.')
