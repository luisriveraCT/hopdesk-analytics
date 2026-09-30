# -*- coding: utf-8 -*-
"""
===============================================================================
 CLASIFICADOR DE CUENTAS — adaptativo y bilingüe
===============================================================================
POR QUÉ EXISTE ESTE ARCHIVO
---------------------------
La primera versión clasificaba por el primer dígito del código: 1→ACTIVO,
2→PASIVO, etc. Funciona perfectamente con el plan de cuentas de Networks, y por
eso mismo es peligroso: no es una regla contable, es una foto de UN catálogo.
Otro cliente que numere distinto, o la misma empresa en inglés, produce
silenciosamente un Balance mal clasificado que además CUADRA (porque los signos
siguen siendo correctos) — el peor error posible: invisible.

Este módulo invierte la lógica. En vez de imponerle al ERP un plan de cuentas
que suponemos, LE PREGUNTA AL ERP cuál tiene, usando lo único que todo sistema
contable tiene por construcción: **el árbol**. Cada cuenta cuelga de una raíz,
y esa raíz ES el cajón. Clasificamos la raíz y los hijos heredan.

LAS TRES FUENTES DE EVIDENCIA, Y POR QUÉ NINGUNA BASTA SOLA
------------------------------------------------------------
  1. `AccountType` del ERP — autoritativo cuando es concluyente, pero en este
     servidor el 85% de las cuentas dice `at_Other`. Sirve para confirmar,
     no para decidir.
  2. El NOMBRE de la raíz, en español o inglés — legible y casi siempre
     correcto... salvo cuando miente (ver abajo).
  3. El PREFIJO del código — último recurso. Es la convención mexicana
     (1 activo … 6 gasto); vale como desempate, nunca como primera voz.

EL CASO QUE JUSTIFICA TODO ESTE DISEÑO (verificado en el catálogo real el
2026-09-24): en Networks, **la numeración y el árbol están corridos un cajón**.

    cuentas 81* 82* 83*  (Gastos Financieros, Diferencia Cambiaria,
                          Misceláneos)            cuelgan de la raíz 700 "Financieros"
    cuentas 91*          (Bajas de Activo, Gastos no Deducibles,
                          Reexpresión)            cuelgan de la raíz 800 "Otros
                                                  Ingresos y Egresos"

Es decir: una cuenta numerada 81xxxx ES financiera pero vive en el cajón 7, y
una numerada 91xxxx es extraordinaria pero vive en el cajón 8. El clasificador
por prefijo acertaba —mapeando '8'→FINANCIERO y dejando '9' sin mapear— pero
**por la razón equivocada**: coincidencia entre dos numeraciones, no lectura del
plan de cuentas. Basta que un cliente numere sus financieros como 7x para que
ese mismo mapeo mande los intereses al renglón incorrecto, sin error visible.

El árbol, en cambio, es coherente: "Gastos Financieros" cuelga de "Financieros"
y "Extraordinarios" cuelga de "Otros Ingresos y Egresos". Por eso el árbol manda.

Regla de oro: **cuando las fuentes se contradicen, NO se resuelve
automáticamente.** Se reporta el conflicto y se exige un override explícito y
con motivo escrito. Un clasificador que adivina bien el 95% de las veces es peor
que uno que dice "no sé" el 5%, porque el 5% malo no se ve.

MULTIEMPRESA / MULTICLIENTE
---------------------------
Ni las clases ni el vocabulario son de Networks. Los overrides SÍ lo son, y por
eso viven en una tabla aparte, con empresa y motivo, en vez de estar cableados
en la lógica. Cuando entre otro cliente, su tabla de overrides es lo único que
se agrega — el clasificador no se toca.
===============================================================================
"""
import os
import re
import sys
import json
import unicodedata
from typing import Dict, List, Optional, Tuple

# Las clases canónicas. Las cinco primeras arman el Balance; las demás, el
# Estado de Resultados. `OTRO` NO es una clase: es la marca de "no clasificada",
# y por eso siempre se reporta.
CLASES_BALANCE = ('ACTIVO', 'PASIVO', 'CAPITAL')
CLASES_RESULTADO = ('INGRESO', 'COSTO', 'GASTO', 'FINANCIERO')
CLASES = CLASES_BALANCE + CLASES_RESULTADO + ('OTRO',)


# ---------------------------------------------------------------------------
# 1. Vocabulario bilingüe
# ---------------------------------------------------------------------------
# Se compara contra el nombre de la RAÍZ, no de cada cuenta: las raíces son diez
# y están redactadas en el lenguaje del plan contable, no en el del capturista.
# Cada término se normaliza (minúsculas, sin acentos) antes de comparar, así que
# "Capital Contable" y "capital contable" son el mismo término.
#
# El orden dentro de cada lista importa: se prueban de más específico a más
# genérico. "costo de ventas" tiene que ganarle a "ventas" (que es INGRESO), y
# "gastos financieros" a "gastos".
VOCABULARIO = {
    # Va primero por una razón: "Otros Ingresos y Egresos" contiene la palabra
    # "ingresos", y sin un término más específico que la capture entera, ese
    # cajón se leería como INGRESO y las partidas extraordinarias entrarían a
    # ventas. Los términos largos ganan por especificidad (ver clase_por_nombre).
    'OTRO': [
        'otros ingresos y egresos', 'otros ingresos y gastos',
        'other revenues and expenses', 'other income and expenses',
        'partidas extraordinarias', 'extraordinarios', 'extraordinary',
        'otros ingresos', 'otros gastos', 'other income', 'other expenses',
    ],
    'COSTO': [
        'costo de ventas', 'costos de venta', 'costo de lo vendido',
        'cost of sales', 'cost of goods sold', 'cogs', 'costo', 'costos',
    ],
    'FINANCIERO': [
        'gastos financieros', 'productos financieros', 'resultado integral de financiamiento',
        'financial expenses', 'financial income', 'finance costs', 'interest',
        'financieros', 'financiero', 'financing', 'financial',
    ],
    'CAPITAL': [
        'capital contable', 'capital social', 'patrimonio',
        "stockholders equity", "shareholders equity", 'equity', 'capital',
    ],
    'ACTIVO': ['activos', 'activo', 'assets', 'asset'],
    'PASIVO': ['pasivos', 'pasivo', 'liabilities', 'liability'],
    'INGRESO': [
        'ingresos', 'ingreso', 'ventas', 'venta',
        'revenues', 'revenue', 'sales', 'income',
    ],
    'GASTO': [
        'gastos de operacion', 'gastos de administracion', 'gastos generales',
        'operating expenses', 'expenses', 'expense', 'gastos', 'gasto',
    ],
}

# `AccountType` de SAP → clase. Solo se listan los CONCLUYENTES. `at_Expenses`
# no está porque un gasto financiero también es `at_Expenses`: si se mapeara,
# el cajón de financieros se volvería GASTO sin que nadie lo notara.
ACCTTYPE_CONCLUYENTE = {
    'at_Revenues': 'INGRESO',
}

# Convención mexicana de plan de cuentas. Es el ÚLTIMO recurso y está aquí
# declarado como lo que es: una convención de un país, no una verdad contable.
PREFIJO_CONVENCION_MX = {
    '1': 'ACTIVO', '2': 'PASIVO', '3': 'CAPITAL', '4': 'INGRESO',
    '5': 'COSTO', '6': 'GASTO', '7': 'FINANCIERO',
}


# ---------------------------------------------------------------------------
# 2. Overrides: lo único específico de un cliente
# ---------------------------------------------------------------------------
# Clave: (empresa o '*' para todas, código de la raíz o su prefijo).
# Cada entrada EXIGE motivo — si alguien no puede escribir por qué, no debería
# estar forzando la clasificación.
# Networks, hoy, NO necesita ninguno: el árbol de las cinco empresas se lee
# entero por nombre de raíz. Se deja vacío a propósito, con el registro de lo
# que SÍ se evaluó y por qué se descartó — un override que existió y se quitó es
# información, y sin esta nota alguien lo volvería a agregar.
#
#   ('*', '8') -> FINANCIERO : DESCARTADO. Venía de pensar en prefijos: las
#   cuentas 81*/82* sí son financieras, pero en el árbol cuelgan de la raíz 700
#   "Financieros", que ya se clasifica sola por su nombre. Aplicado a la raíz
#   800 arrastraba las 91* (bajas de activo, no deducibles, reexpresión) a
#   financieros, que es justo el error que el override pretendía evitar.
OVERRIDES = {}


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos, sin puntuación, espacios colapsados.
    Es lo que permite que 'Capital Contable', 'CAPITAL CONTABLE' y
    'capital  contable' sean el mismo término."""
    if not texto:
        return ''
    t = unicodedata.normalize('NFKD', str(texto))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r'[^0-9a-zA-Z ]+', ' ', t.lower())
    return re.sub(r'\s+', ' ', t).strip()


def clase_por_nombre(*nombres: str) -> Tuple[Optional[str], str]:
    """Busca el término más específico que aparezca en CUALQUIERA de los
    nombres dados (español, inglés, los que haya). Devuelve (clase, término).

    Prueba término por término en orden de especificidad para que 'costo de
    ventas' no se lea como 'ventas'."""
    candidatos = [normalizar(n) for n in nombres if n]
    if not candidatos:
        return None, ''
    # Recorremos por longitud de término descendente: el más largo es el más
    # específico, sin depender del orden en que quedó escrito el diccionario.
    terminos = sorted(
        ((t, clase) for clase, ts in VOCABULARIO.items() for t in ts),
        key=lambda x: -len(x[0]))
    for termino, clase in terminos:
        for nom in candidatos:
            if re.search(r'\b' + re.escape(termino) + r'\b', nom):
                return clase, termino
    return None, ''


# ---------------------------------------------------------------------------
# Impuesto a la utilidad: se separa del resto de los gastos
# ---------------------------------------------------------------------------
# Un Estado de Resultados termina en utilidad NETA, y para llegar ahí hay que
# restar el impuesto a la utilidad por separado. Mezclado con los demás gastos,
# la utilidad de operación queda contaminada y la tasa impositiva efectiva
# —que hace falta para el WACC— no se puede calcular.
#
# La trampa: en un plan de cuentas mexicano conviven varios "impuestos" que NO
# son impuesto a la utilidad. El impuesto sobre nómina y el predial son gastos
# de operación como cualquier otro; contarlos como impuesto a la utilidad
# inflaría la tasa efectiva y desinflaría los gastos.
#
# Se distinguen por el ÁRBOL, igual que las clases: en este catálogo el ISR y
# la PTU cuelgan de un rubro llamado "Provisión de Impuestos", mientras que el
# de nómina cuelga de "Gastos de Nómina". Se lee el nombre del antepasado, no
# el prefijo del código.
VOCABULARIO_IMPUESTO_UTILIDAD = [
    'provision de impuestos', 'provisiones de impuestos',
    'impuesto sobre la renta', 'impuestos sobre la renta',
    'impuesto a la utilidad', 'impuestos a la utilidad',
    'participacion de los trabajadores en las utilidades',
    'income tax', 'income taxes', 'tax provision', 'provision for income taxes',
    'profit sharing', 'isr', 'ptu', 'ietu',
]

# Lo que dice "impuesto" pero es gasto de operación.
VOCABULARIO_IMPUESTO_OPERATIVO = [
    'impuesto sobre nomina', 'impuestos sobre nomina', 'sobre nomina',
    'predial', 'derechos', 'tenencia', 'iva', 'ieps',
    'payroll tax', 'property tax', 'vat',
]


def es_impuesto_a_la_utilidad(codigo: str, cuentas: Dict[str, Dict]) -> bool:
    """¿Esta cuenta es impuesto a la utilidad (ISR/PTU) y no un gasto operativo?

    Mira la cuenta y a sus antepasados. Gana la señal más específica: si el
    nombre propio dice "nómina", es operativo aunque cuelgue de un rubro de
    impuestos; si ni él ni sus padres mencionan impuesto a la utilidad, no lo es.
    """
    visto = set()
    actual = cuentas.get(codigo)
    cadena = []
    while actual and actual['codigo'] not in visto:
        visto.add(actual['codigo'])
        cadena.append(normalizar(actual.get('nombre', '')))
        padre = (actual.get('cuenta_padre') or '').strip()
        actual = cuentas.get(padre) if padre else None

    # La propia cuenta manda: un "impuesto sobre nómina" es operativo aunque
    # alguien lo haya colgado del rubro de provisiones.
    propio = cadena[0] if cadena else ''
    for t in VOCABULARIO_IMPUESTO_OPERATIVO:
        if re.search(r'\b' + re.escape(t) + r'\b', propio):
            return False
    for nombre in cadena:
        for t in VOCABULARIO_IMPUESTO_UTILIDAD:
            if re.search(r'\b' + re.escape(t) + r'\b', nombre):
                return True
    return False


def _raiz_de(cuenta: Dict, indice: Dict[str, Dict]) -> Dict:
    """Sube por el árbol hasta la cuenta sin padre. Protegido contra ciclos:
    un catálogo corrupto con A padre de B y B padre de A colgaría el proceso."""
    visitadas = set()
    actual = cuenta
    while True:
        padre = (actual.get('cuenta_padre') or '').strip()
        if not padre or padre not in indice or padre == actual['codigo']:
            return actual
        if actual['codigo'] in visitadas:
            return actual          # ciclo: nos quedamos donde estamos
        visitadas.add(actual['codigo'])
        actual = indice[padre]


def clasificar_raiz(raiz: Dict, descendientes: List[Dict],
                    empresa: str = '') -> Dict:
    """Clasifica UN cajón reuniendo las tres evidencias, sin resolver los
    conflictos por su cuenta.

    Devuelve un dict con la clase, la ruta por la que se llegó, todas las
    evidencias y la lista de desacuerdos. Quien llama decide qué hacer con un
    desacuerdo — aquí no se esconde ninguno."""
    codigo = raiz['codigo']
    prefijo = re.sub(r'[^0-9A-Za-z]', '', codigo)[:1]

    ev = {}

    # (a) nombre, en cualquiera de los dos idiomas
    cl_nom, termino = clase_por_nombre(raiz.get('nombre'), raiz.get('nombre_en'))
    if cl_nom:
        idioma = 'es' if termino in normalizar(raiz.get('nombre', '')) else 'en'
        ev['nombre'] = {'clase': cl_nom, 'detalle': f'"{termino}" ({idioma})'}

    # (b) AccountType concluyente entre los descendientes: solo cuenta si NINGÚN
    #     descendiente contradice. Un solo at_Revenues dentro de un cajón de
    #     gastos no convierte el cajón en ingresos.
    tipos = {d.get('account_type_sap') for d in descendientes}
    concluyentes = {ACCTTYPE_CONCLUYENTE[t] for t in tipos if t in ACCTTYPE_CONCLUYENTE}
    if len(concluyentes) == 1:
        ev['account_type'] = {'clase': concluyentes.pop(),
                              'detalle': f'{len(descendientes)} descendientes'}

    # (c) prefijo, la convención
    if prefijo in PREFIJO_CONVENCION_MX:
        ev['prefijo'] = {'clase': PREFIJO_CONVENCION_MX[prefijo],
                         'detalle': f'convención MX, prefijo {prefijo}'}

    # ¿se contradicen?
    votos = {k: v['clase'] for k, v in ev.items()}
    conflicto = len(set(votos.values())) > 1

    # override explícito (gana sobre todo, y deja constancia de por qué)
    ov = OVERRIDES.get((empresa, codigo)) or OVERRIDES.get((empresa, prefijo)) \
        or OVERRIDES.get(('*', codigo)) or OVERRIDES.get(('*', prefijo))
    if ov:
        return {'codigo': codigo, 'nombre': raiz.get('nombre', ''),
                'clase': ov['clase'], 'ruta': 'override',
                'motivo': ov['motivo'], 'evidencias': votos,
                'conflicto': conflicto, 'n_cuentas': len(descendientes)}

    # Sin override: manda el nombre, luego el AccountType, luego el prefijo.
    # El nombre va primero porque es lo único que sobrevive a un cambio de
    # numeración —que es justo lo que cambia entre clientes.
    for fuente in ('nombre', 'account_type', 'prefijo'):
        if fuente in ev:
            return {'codigo': codigo, 'nombre': raiz.get('nombre', ''),
                    'clase': ev[fuente]['clase'], 'ruta': fuente,
                    'motivo': ev[fuente]['detalle'], 'evidencias': votos,
                    'conflicto': conflicto, 'n_cuentas': len(descendientes)}

    return {'codigo': codigo, 'nombre': raiz.get('nombre', ''),
            'clase': 'OTRO', 'ruta': 'sin evidencia', 'motivo': '',
            'evidencias': votos, 'conflicto': False,
            'n_cuentas': len(descendientes)}


def clasificar_catalogo(cuentas: List[Dict], empresa: str = '') -> Tuple[List[Dict], Dict]:
    """Clasifica un catálogo completo. Devuelve (cuentas, informe).

    Las cuentas salen con `clase` asignada y con `clase_via` (la raíz y la ruta)
    para poder auditar después de dónde salió cada clasificación — sin eso, un
    Balance mal clasificado no se puede diagnosticar."""
    indice = {c['codigo']: c for c in cuentas}
    por_raiz = {}
    for c in cuentas:
        por_raiz.setdefault(_raiz_de(c, indice)['codigo'], []).append(c)

    informe = {'empresa': empresa, 'raices': [], 'conflictos': [],
               'sin_clasificar': 0, 'total': len(cuentas)}

    for cod_raiz, hijos in sorted(por_raiz.items()):
        res = clasificar_raiz(indice[cod_raiz], hijos, empresa)
        informe['raices'].append(res)
        if res['conflicto']:
            informe['conflictos'].append(res)
        for c in hijos:
            c['clase'] = res['clase']
            c['clase_via'] = f"{cod_raiz}/{res['ruta']}"
        # "Sin clasificar" NO es lo mismo que "clase OTRO". Un cajón que se
        # llama "Otros Ingresos y Egresos" y se clasificó como OTRO por su
        # nombre está perfectamente clasificado; el que preocupa es aquel del
        # que no hubo NINGUNA evidencia. Contarlos juntos convertiría el aviso
        # en ruido permanente, y un aviso que siempre aparece deja de leerse.
        if res['ruta'] == 'sin evidencia':
            informe['sin_clasificar'] += len(hijos)

    return cuentas, informe


def imprimir_informe(inf: Dict) -> None:
    print(f"--- {inf['empresa'] or 'catálogo'}: {inf['total']:,} cuentas ---")
    for r in inf['raices']:
        marca = ' [!]' if r['conflicto'] else ''
        print(f"   {r['codigo'][:3]:<4} {r['nombre'][:26]:<27} -> {r['clase']:<11}"
              f" vía {r['ruta']:<13} ({r['n_cuentas']:>3}){marca}")
    if inf['conflictos']:
        print(f"   ATENCIÓN: {len(inf['conflictos'])} cajón(es) con evidencia "
              f"contradictoria:")
        for r in inf['conflictos']:
            print(f"      {r['codigo'][:3]} {r['nombre'][:30]}: {r['evidencias']}")
            print(f"         resuelto por {r['ruta']}: {r['motivo'][:150]}")
    if inf['sin_clasificar']:
        print(f"   {inf['sin_clasificar']} cuenta(s) quedaron sin clase (OTRO).")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'datos_erp')
    for arch in sorted(os.listdir(base)):
        if not arch.startswith('cuentas_'):
            continue
        emp = arch.replace('cuentas_', '').replace('.json', '')
        with open(os.path.join(base, arch), encoding='utf-8') as f:
            cs = json.load(f)
        previas = {c['codigo']: c.get('clase') for c in cs}
        cs, inf = clasificar_catalogo(cs, emp)
        imprimir_informe(inf)
        difs = [c for c in cs if previas.get(c['codigo']) != c['clase']]
        print(f"   contra la clasificación anterior: {len(difs)} diferencia(s)")
        for c in difs[:8]:
            print(f"      {c['codigo'][:6]:<7} {c['nombre'][:34]:<35} "
                  f"{previas.get(c['codigo'])} -> {c['clase']}")
        print()
