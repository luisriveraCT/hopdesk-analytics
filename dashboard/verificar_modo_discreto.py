# -*- coding: utf-8 -*-
"""Comprueba el modo de montos: la clasificación de columnas y las descargas.

DOS COSAS, Y LAS DOS HACEN FALTA

1. LA CLASIFICACIÓN. La regla es por exclusión: es monto todo lo que no sea
   conteo, porcentaje, tipo de cambio, periodo, días o texto. Si esta parte
   falla, el modo o deja un importe a la vista o esconde algo que no es dinero
   —que ya pasó con la columna de participación, un porcentaje que salía en
   "•••" y dejaba la tabla sin nada que leer.

2. QUE LA DESCARGA PASE POR AHÍ. Lo que se ve en pantalla y lo que se baja en
   un archivo salen de sitios distintos: las tres pestañas de estados e
   indicadores se cosechan de la tabla a la vista —y por eso heredan el modo
   solas—, pero Facturación exporta los mismos arreglos crudos que alimentan
   las gráficas. Esa ruta tiene que pasar por enmascararFilas(), y se comprueba
   aquí porque es un descuido que no se ve: la pantalla sigue diciendo "•••" y
   el Excel sale con todos los importes dentro.
"""
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

s = open(sys.argv[1], encoding='utf-8').read()
m = re.search(r'return !/\((.*?)\)/\.test\(n\);', s, re.S)
if not m:
    print('no se encontró el patrón de esColumnaDeMonto')
    raise SystemExit(1)

# El patrón viene de un literal JS: las barras invertidas dobles del código
# fuente representan una sola en la expresión real.
patron = m.group(1).replace('\\\\', '\\')
rx = re.compile(patron, re.I)

CASOS = [
    # (nombre de columna, ¿debe tratarse como monto?)
    ('Total MXN', True), ('Base sin IVA', True), ('Facturado en USD', True),
    ('Ingresos', True), ('Utilidad de operación', True), ('Activo', True),
    ('Importe', True), ('Saldo', True),
    ('N.º de facturas', False), ('Facturas', False), ('Invoices', False),
    ('N', False),
    ('% del total', False), ('Porcentaje', False),
    # La participación es un porcentaje aunque no traiga el signo.
    ('Part.', False), ('Share', False), ('Participación', False),
    # El tipo de cambio es una cotización pública, no un importe del negocio.
    ('T.C.', False), ('FX', False), ('TC', False), ('Tipo de cambio prom.', False),
    ('Mes', False), ('Periodo', False), ('Año', False),
    ('Cliente', False), ('Empresa', False), ('Concepto', False),
    ('Días de cierre', False), ('Folio', False), ('Estatus', False),
]

print(f"{'columna':<26}{'tratada como':<14}{'esperado'}")
fallos = []
for nombre, esperado in CASOS:
    obtenido = not bool(rx.search(nombre.lower()))
    bien = obtenido == esperado
    if not bien:
        fallos.append(nombre)
    print(f"  {nombre:<26}{'monto' if obtenido else 'otro':<14}"
          f"{'monto' if esperado else 'otro':<10}{'' if bien else '  <-- MAL'}")

print(f'\n{len(CASOS) - len(fallos)} de {len(CASOS)}')

# --- 2. las rutas de descarga que no vienen de la pantalla -----------------
RUTAS = [
    ('descarga de una tarjeta',
     r"const rows = enmascararFilas\(\s*c\.key\s*===?\s*'tabla'"),
    ('descarga de la hoja de Facturación',
     r"const rows = enmascararFilas\(\s*\n?\s*c\.key === 'tabla'"),
    ('la función existe y respeta el modo',
     r"function enmascararFilas\(rows\)\{[^}]*?if \(!DISCRETO"),
]
print()
for nombre, patron in RUTAS:
    if re.search(patron, s, re.S):
        print(f'  {nombre}: pasa por enmascararFilas()')
    else:
        fallos.append(nombre)
        print(f'  {nombre}: NO pasa por enmascararFilas()   <-- MAL')

raise SystemExit(1 if fallos else 0)
