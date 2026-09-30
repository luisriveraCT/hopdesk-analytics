# -*- coding: utf-8 -*-
"""
===============================================================================
 CONSOLIDACIÓN — identificar y eliminar las operaciones entre empresas
===============================================================================
EL PROBLEMA
-----------
Sumar los estados financieros de las cinco empresas no da el estado del grupo:
da una suma que cuenta dos veces lo que las empresas se venden entre sí, y no
es un matiz: en este grupo una porción grande de la facturación es
intercompañía. El porcentaje exacto lo calcula el tablero del agregado vigente;
escribirlo aquí solo garantizaría que envejezca.

Para consolidar hay que eliminar:
  · Ingresos y gastos entre empresas del grupo  → ya resuelto: las facturas
    traen la contraparte y el registro intercompañía dice quién es del grupo.
  · Saldos por cobrar y por pagar entre empresas → lo que resuelve este archivo.
  · Inversiones de una empresa en otra → **no aplica aquí**: el usuario confirmó
    que ninguna empresa es dueña de otra. Las cinco son hermanas, con un solo
    propietario y sin clases de acciones, así que no hay capital que eliminar ni
    participación minoritaria que calcular.

POR QUÉ ESTO ES UN ALGORITMO Y NO UNA LISTA
--------------------------------------------
Una lista de cuentas escrita a mano envejece: cada mes alguien abre una cuenta
nueva, y la lista no se entera. El resultado es una consolidación que va
quedando incompleta sin avisar. Por eso las cuentas se DETECTAN en cada corrida.

CÓMO SE DETECTAN, EN DOS PASOS
------------------------------
**1. Por el nombre, puntuando cada palabra según lo que distingue.**
Las cuentas llevan el nombre de la contraparte: "11510004 Networks Trucking
Sevices". El reto es que las seis empresas se llaman "Networks algo", así que esa
palabra no identifica a nadie. Cada palabra recibe un peso inverso a cuántas
empresas la comparten —NETWORKS pesa 0.2, SERVICES 0.5, TRUCKING 1.0— y gana la
empresa con más peso acumulado, siempre que le saque margen a la segunda. Todo
se calcula de los nombres configurados: una empresa nueva, o un cliente
distinto, no requiere editar nada.

Dos trampas reales que este esquema resuelve, y que costó encontrar:

  · **Erratas del maestro.** El catálogo trae "Networks Trucking **Sevices**",
    sin la R. Se acepta porque TRUCKING —la palabra que pesa— está bien escrita,
    y la palabra sobrante se parece lo suficiente a SERVICES.

  · **Terceros de nombre parecido.** "Networks **Outsourcing** Services" NO es
    del grupo, pero comparte NETWORKS y SERVICES con Networks Trucking Services
    y por poco entra a la eliminación con su saldo. Se rechaza porque
    OUTSOURCING no se parece a ninguna palabra de esa empresa: **una palabra
    sobrante que no es una errata delata a otra entidad.**

**2. Por reciprocidad — y esta es la parte que hace el método confiable.**
Si NCS tiene una cuenta por cobrar a NTS, NTS tiene que tener una por pagar a
NCS por el mismo importe y signo contrario. El algoritmo busca ese espejo:

  · **Espeja y los saldos se compensan** → intercompañía confirmada.
  · **Espeja pero los saldos NO cuadran** → sí es intercompañía, y además hay
    una diferencia de conciliación que alguien debe explicar. Se reporta con el
    monto.
  · **No espeja** → candidata dudosa. Se reporta, NO se elimina. Puede ser una
    coincidencia de nombre, o que la contraparte no haya registrado su lado.

Eliminar una cuenta que no espeja descuadraría el consolidado por ese importe.
Reportarla deja el consolidado íntegro y pone el problema donde se puede
resolver: con quien lleva la contabilidad.
===============================================================================
"""
import os
import re
import sys
import json
import unicodedata
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS_ERP = os.path.join(AQUI, 'datos_erp')
sys.path.insert(0, os.path.join(AQUI, 'configuracion'))
sys.path.insert(0, os.path.join(AQUI, 'erp'))

# Diferencia máxima entre los dos lados de una cuenta recíproca para darla por
# conciliada. No es cero absoluto: hay redondeos y partidas en tránsito.
# Es 0.5% del importe, con un piso de $1,000 para que una cuenta chica no se
# marque por una diferencia irrelevante.
TOLERANCIA_PCT = 0.005
TOLERANCIA_PISO = 1000.0


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).upper().replace('&', ' Y ')
    return re.sub(r'\s+', ' ', re.sub(r'[^A-Z0-9 ]+', ' ', s)).strip()


# Palabras que no distinguen a nadie: formas societarias y conectores.
RUIDO = {'SA', 'S', 'A', 'DE', 'CV', 'C', 'V', 'SC', 'SAPI', 'SAB', 'Y', 'DEL',
         'LA', 'EL', 'LOS', 'LAS', 'SRL', 'LLC', 'INC', 'LTD'}


def vocabulario(nombres_por_empresa):
    """Las palabras significativas del nombre de cada empresa, con su peso.

    Una palabra pesa más cuanto menos empresas la comparten: "NETWORKS" la
    tienen las cinco y no distingue a nadie; "CROSSDOCKING" la tiene una sola y
    la identifica. El peso se calcula, no se escribe, así que una empresa nueva
    —o un cliente distinto— no requiere tocar nada.

    LA PRIMERA VERSIÓN DE ESTO ESTABA MAL, y vale la pena que quede dicho:
    exigía que cada empresa tuviera una palabra ÚNICA. Funcionaba para cuatro,
    pero "Networks & Logistics" y "Paragon Logistics" comparten LOGISTICS, así
    que Networks & Logistics se quedó sin término propio y sus cuentas en los
    libros ajenos dejaron de reconocerse. El síntoma era sutil: los pares con
    esa empresa aparecían espejando contra cero, como si la contraparte no
    hubiera registrado su lado. Un dato faltante que parecía un hallazgo.
    """
    tokens = {ini: set(norm(n).split()) - RUIDO
              for ini, n in nombres_por_empresa.items()}
    frecuencia = defaultdict(int)
    for ts in tokens.values():
        for t in ts:
            frecuencia[t] += 1
    return {ini: {t: 1.0 / frecuencia[t] for t in ts if len(t) >= 3}
            for ini, ts in tokens.items()}


# Cuánto debe ganarle la mejor empresa a la segunda para aceptar la asignación.
# Sin margen, "Networks & Logistics" y "Paragon Logistics" se disputarían las
# cuentas que solo digan "Logistics", y asignarla al azar es peor que no
# asignarla: mete el saldo de un tercero en la eliminación.
MARGEN_MINIMO = 1.25


def identificar_contraparte(nombre_cuenta, vocab, empresa_propia):
    """A qué empresa del grupo se refiere el nombre de una cuenta.

    Puntúa por traslape ponderado contra cada empresa y exige que la ganadora
    le saque un margen a la siguiente. Devuelve (iniciales, puntaje) o
    (None, 0).

    Tolera las erratas del maestro: "Networks Trucking Sevices" (sin la R) gana
    igual, porque TRUCKING —la palabra que pesa— está bien escrita.
    """
    import difflib
    palabras = set(norm(nombre_cuenta).split()) - RUIDO
    palabras = {p for p in palabras if len(p) >= 3}
    if not palabras:
        return None, 0.0

    puntajes = []
    for ini, pesos in vocab.items():
        if ini == empresa_propia:
            continue
        p = sum(w for t, w in pesos.items() if t in palabras)
        if p <= 0:
            continue
        # UNA PALABRA SOBRANTE DELATA A OTRA ENTIDAD. Sin esto, "Networks
        # Outsourcing Services" se asignaba a Networks Trucking Services:
        # comparten NETWORKS y SERVICES, y con eso ganaba. Pero Outsourcing es
        # una empresa distinta y NO está en el grupo configurado — su saldo
        # habría entrado a la eliminación como si fuera intercompañía.
        #
        # La excepción son las erratas del maestro, que existen: el catálogo
        # trae "Networks Trucking Sevices" (sin la R). Por eso una palabra
        # sobrante solo descalifica si NO se parece a ninguna de la empresa;
        # SEVICES se parece a SERVICES, OUTSOURCING no se parece a nada de NTS.
        sobrantes = [w for w in palabras if w not in pesos]
        ajenas = [w for w in sobrantes
                  if not difflib.get_close_matches(w, list(pesos), n=1, cutoff=0.82)]
        if ajenas:
            continue
        puntajes.append((p, ini))

    if not puntajes:
        return None, 0.0
    puntajes.sort(reverse=True)
    mejor, ini = puntajes[0]
    if len(puntajes) > 1:
        segundo = puntajes[1][0]
        if segundo > 0 and mejor < segundo * MARGEN_MINIMO:
            return None, mejor          # empate: no se adivina
    # Un traslape de una sola palabra común (peso bajo) no basta: "Networks"
    # a secas lo comparten todas.
    return (ini, mejor) if mejor >= 0.5 else (None, mejor)


def detectar_candidatas(cuentas, empresa_propia, vocab):
    """Cuentas de `empresa_propia` que nombran a otra empresa del grupo.

    Devuelve {codigo: iniciales_de_la_contraparte}.
    """
    salida = {}
    for c in cuentas.values():
        if c.get('es_acumulativa'):
            continue
        if c.get('clase') not in ('ACTIVO', 'PASIVO'):
            continue          # solo saldos; ingresos y gastos se eliminan por factura
        otra, _ = identificar_contraparte(c['nombre'], vocab, empresa_propia)
        if otra:
            salida[c['codigo']] = otra
    return salida


def saldo_en(saldos, codigo, anio, mes):
    """Última posición conocida de una cuenta hasta el periodo dado."""
    mejor = None
    for s in saldos:
        if s['codigo'] != codigo or (s['anio'], s['mes']) > (anio, mes):
            continue
        if mejor is None or (s['anio'], s['mes']) > (mejor['anio'], mejor['mes']):
            mejor = s
    return mejor['saldo_final'] if mejor else 0.0


def analizar(anio, mes, verbose=True):
    """Detecta las cuentas intercompañía y verifica su reciprocidad."""
    import repositorio as repo
    from erp import clasificador_cuentas as cl

    cliente = repo.cliente_actual(repo.almacen_por_defecto())
    nombres = {e.iniciales: e.nombre for e in cliente.empresas if e.activa}
    vocab = vocabulario(nombres)

    if verbose:
        print('Peso de cada palabra por empresa (calculado, no escrito):')
        for ini, pesos in sorted(vocab.items()):
            top = sorted(pesos.items(), key=lambda kv: -kv[1])[:3]
            print(f'   {ini:<5} ' + "  ".join(f"{t}={w:.2f}" for t, w in top))
        print()

    cuentas, saldos, candidatas = {}, {}, {}
    for ini in nombres:
        rc = os.path.join(DATOS_ERP, f'cuentas_{ini}.json')
        rs = os.path.join(DATOS_ERP, f'saldos_{ini}.json')
        if not (os.path.exists(rc) and os.path.exists(rs)):
            continue
        with open(rc, encoding='utf-8') as f:
            cs = json.load(f)
        cs, _ = cl.clasificar_catalogo(cs, ini)
        cuentas[ini] = {c['codigo']: c for c in cs}
        with open(rs, encoding='utf-8') as f:
            saldos[ini] = json.load(f)
        candidatas[ini] = detectar_candidatas(cuentas[ini], ini, vocab)

    # Agregar por par (empresa, contraparte)
    pares = defaultdict(float)
    detalle = defaultdict(list)
    for ini, cands in candidatas.items():
        for cod, otra in cands.items():
            v = saldo_en(saldos[ini], cod, anio, mes)
            pares[(ini, otra)] += v
            if abs(v) >= 0.5:
                detalle[(ini, otra)].append(
                    {'codigo': cod, 'nombre': cuentas[ini][cod]['nombre'],
                     'clase': cuentas[ini][cod]['clase'], 'saldo': round(v, 2)})

    resultado = {'periodo': f'{anio}-{mes:02d}', 'confirmadas': [],
                 'a_revisar': [], 'eliminable': 0.0}
    vistos = set()
    for (a, b), v in sorted(pares.items()):
        if (b, a) in vistos:
            continue
        vistos.add((a, b))
        w = pares.get((b, a), 0.0)
        # Recíprocas: el saldo de A contra B y el de B contra A deben sumar cero
        # (uno es derecho y el otro obligación, con signos opuestos).
        dif = v + w
        escala = max(abs(v), abs(w))
        tol = max(escala * TOLERANCIA_PCT, TOLERANCIA_PISO)
        fila = {'a': a, 'b': b, 'saldo_a': round(v, 2), 'saldo_b': round(w, 2),
                'diferencia': round(dif, 2),
                'cuentas_a': detalle.get((a, b), []),
                'cuentas_b': detalle.get((b, a), [])}
        if (b, a) not in pares or escala < 0.5:
            fila['motivo'] = 'la contraparte no tiene cuenta espejo'
            resultado['a_revisar'].append(fila)
        elif abs(dif) <= tol:
            resultado['confirmadas'].append(fila)
            resultado['eliminable'] += escala
        else:
            fila['motivo'] = (f'espeja pero no concilia: difieren '
                              f'{dif:,.2f} ({abs(dif) / escala * 100:.1f}%)')
            resultado['a_revisar'].append(fila)
            resultado['eliminable'] += min(abs(v), abs(w))
    return resultado


def imprimir(r):
    print(f"=== Cuentas intercompañía al {r['periodo']} ===\n")
    print(f"CONFIRMADAS (espejan y concilian): {len(r['confirmadas'])} par(es)")
    for f in r['confirmadas']:
        print(f"   {f['a']:<4} ↔ {f['b']:<4}  {f['saldo_a']:>16,.2f} / "
              f"{f['saldo_b']:>16,.2f}   dif {f['diferencia']:>10,.2f}")
    if r['a_revisar']:
        print(f"\nA REVISAR (no se eliminan): {len(r['a_revisar'])} par(es)")
        for f in r['a_revisar']:
            print(f"   {f['a']:<4} ↔ {f['b']:<4}  {f['saldo_a']:>16,.2f} / "
                  f"{f['saldo_b']:>16,.2f}")
            print(f"        {f['motivo']}")
            for c in (f['cuentas_a'] + f['cuentas_b'])[:3]:
                print(f"          {c['codigo']:<12} {c['nombre'][:40]:<41} "
                      f"{c['saldo']:>14,.2f}")
    print(f"\nEliminable en la consolidación: {r['eliminable']:,.2f}")
    if r['a_revisar']:
        print('Lo que está a revisar NO se elimina: hacerlo descuadraría el '
              'consolidado por esa diferencia.')


# ---------------------------------------------------------------------------
def _pruebas():
    """Casos que costaron encontrar. Correr con: python consolidacion.py --probar"""
    vocab = vocabulario({
        'NCS': 'Networks Crossdocking Services, S.A. de C.V.',
        'NG': 'Networks Group LCT, S.C.', 'NL': 'Networks & Logistics, S.A. de C.V.',
        'NRS': 'Networks Realtors, S.A. de C.V.',
        'NTS': 'Networks Trucking Services, S.A. de C.V.',
        'PL': 'Paragon Logistics, S.A. de C.V.'})
    casos = [
        # (nombre de la cuenta, libro donde vive, contraparte esperada)
        ('Networks Trucking Sevices, S.A. de C.V.', 'NCS', 'NTS'),   # errata real del maestro
        ('Networks Outsourcing Services, S.A. de C', 'NCS', None),   # tercero, NO es del grupo
        ('Networks & Logistics, S.A. de C.V.', 'NCS', 'NL'),         # comparte LOGISTICS con Paragon
        ('Paragon Logistics, S.A. de C.V.', 'NCS', 'PL'),
        ('Networks Crossdocking Services', 'NG', 'NCS'),
        ('Networks Group LCT', 'NL', 'NG'),
        ('Clientes Nacionales', 'NCS', None),                        # cuenta común
        ('Logistics', 'NCS', None),                                  # empate NL/PL: no se adivina
    ]
    fallos = []
    for nombre, libro, esperado in casos:
        r, _ = identificar_contraparte(nombre, vocab, libro)
        marca = 'ok  ' if r == esperado else 'FALLA'
        print(f'  {marca}  {nombre[:44]:<45} [{libro}] -> {r}')
        if r != esperado:
            fallos.append(nombre)
    print(f'\n{len(casos) - len(fallos)} de {len(casos)}')
    return not fallos


if __name__ == '__main__':
    import argparse
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--periodo', default='2026-09', help='AAAA-MM')
    ap.add_argument('--probar', action='store_true')
    args = ap.parse_args()
    if args.probar:
        raise SystemExit(0 if _pruebas() else 1)
    a, m = (int(x) for x in args.periodo.split('-'))
    imprimir(analizar(a, m))


# ---------------------------------------------------------------------------
# Consolidación de estados
# ---------------------------------------------------------------------------
def eliminaciones(anio, mes):
    """Cuánto se elimina de cada empresa al consolidar, y qué queda sin conciliar.

    REGLA: se elimina lo que EMPAREJA, no lo que una empresa dice sola.

    Si NCS registra 4,249,838 por cobrar a NL y NL registra 2,953,101 por pagar
    a NCS, lo que de verdad es una operación entre ambas es la parte común
    —2,953,101— y la diferencia de 1,296,737 es un problema de conciliación.
    Eliminar la cifra mayor dejaría el consolidado descuadrado por esa
    diferencia; eliminar solo la común lo deja cuadrado y la diferencia visible
    donde alguien puede resolverla.

    Esa diferencia NO se esconde ni se "ajusta": sale como renglón propio.
    """
    r = analizar(anio, mes, verbose=False)
    # Se acumula POR CLASE DE CUENTA, no como neto por empresa.
    #
    # La primera versión guardaba un solo número por empresa y después lo
    # asignaba a activo o pasivo según su signo. Falla en cuanto una empresa
    # tiene a la vez cuentas por cobrar con una hermana y por pagar con otra:
    # el neto esconde de qué lado venía cada parte, y al repartirlo se elimina
    # de más en un lado y de menos en el otro. El consolidado quedaba
    # descuadrado por esa diferencia en 8 de 81 periodos — y como el descuadre
    # era chico frente al activo, era del tipo que se confunde con redondeo.
    por_empresa_clase = defaultdict(float)   # (empresa, 'ACTIVO'|'PASIVO') -> monto
    sin_conciliar = []

    def lado(saldo):
        """De qué lado del balance está esta posición NETA con la contraparte.

        Un saldo positivo es un derecho (activo); uno negativo, una obligación
        (pasivo). Se decide con el neto de esa relación concreta, no con el
        acumulado de la empresa: NCS puede ser acreedora de NL y deudora de NTS
        el mismo día, y sumar las dos antes de decidir pierde esa distinción —
        que es justo lo que descuadraba el consolidado.
        """
        return 'ACTIVO' if saldo > 0 else 'PASIVO'

    for f in r['confirmadas'] + r['a_revisar']:
        a, b = f['a'], f['b']
        va, vb = f['saldo_a'], f['saldo_b']
        comun = min(abs(va), abs(vb))
        if comun < 0.5:
            if abs(va) >= 0.5 or abs(vb) >= 0.5:
                sin_conciliar.append({'a': a, 'b': b, 'monto': round(va + vb, 2),
                                      'motivo': f.get('motivo', 'sin contraparte')})
            continue
        # Los dos lados de un par siempre tienen signo opuesto si la
        # contabilidad es correcta, así que uno va a activo y el otro a pasivo:
        # el consolidado queda cuadrado por construcción. Si ambos tuvieran el
        # mismo signo —las dos empresas registrando un derecho contra la otra—
        # no habría eliminación posible sin descuadrar, y eso se reporta.
        if lado(va) == lado(vb):
            sin_conciliar.append({
                'a': a, 'b': b, 'monto': round(va + vb, 2),
                'motivo': f'ambas registran la relación del mismo lado '
                          f'({lado(va).lower()}); no se puede eliminar sin descuadrar'})
            continue
        por_empresa_clase[(a, lado(va))] += comun
        por_empresa_clase[(b, lado(vb))] += comun
        resto = round(va + vb, 2)
        if abs(resto) >= 0.5:
            sin_conciliar.append({'a': a, 'b': b, 'monto': resto,
                                  'motivo': f.get('motivo', 'no concilia')})

    activo = sum(v for (_, cl_), v in por_empresa_clase.items() if cl_ == 'ACTIVO')
    pasivo = sum(v for (_, cl_), v in por_empresa_clase.items() if cl_ == 'PASIVO')
    return {'por_clase': {f'{e}|{c}': round(v, 2)
                          for (e, c), v in por_empresa_clase.items()},
            'activo': round(activo, 2), 'pasivo': round(pasivo, 2),
            'sin_conciliar': sin_conciliar,
            'total_eliminado': round(min(activo, pasivo), 2)}


def consolidar(anio, mes, empresas=None):
    """Balance y Estado de Resultados consolidados del grupo.

    Qué se elimina, y de dónde sale cada cosa:

      · **Saldos entre empresas** (por cobrar / por pagar): de `eliminaciones()`,
        que empareja cuenta contra cuenta y solo quita la parte común.
      · **Ingresos y gastos entre empresas**: de las facturas, donde la
        contraparte está identificada por el registro intercompañía. Se elimina
        el mismo importe de los ingresos de quien vendió y de los gastos de
        quien compró, así que la utilidad del grupo no cambia — que es
        precisamente la señal de que la eliminación está bien hecha.
      · **Capital**: NO se elimina nada. El usuario confirmó que ninguna empresa
        es dueña de otra; las cinco son hermanas con un solo propietario. Sin
        inversiones cruzadas no hay capital que eliminar ni participación
        minoritaria que calcular.

    LO QUE NO CONCILIA SE REVELA, NO SE AJUSTA. La diferencia entre lo que una
    empresa dice que le deben y lo que la otra dice que debe sale como renglón
    propio. Ajustarla para que cuadre sería inventar un asiento que nadie hizo.
    """
    import importlib
    av = importlib.import_module('analisis_vertical_horizontal')
    from erp import clasificador_cuentas as cl
    import repositorio as repo

    cliente = repo.cliente_actual(repo.almacen_por_defecto())
    inis = empresas or [e.iniciales for e in cliente.empresas_conectadas()]

    elim = eliminaciones(anio, mes)
    bal = {'activo': 0.0, 'pasivo': 0.0, 'capital_contable': 0.0,
           'resultados_acumulados': 0.0, 'resultado_ejercicio': 0.0}
    er = {k: 0.0 for k in ('ingresos', 'costo', 'utilidad_bruta', 'gastos_operacion',
                           'utilidad_operacion', 'resultado_financiero', 'otros',
                           'resultado_antes_impuestos', 'impuestos', 'utilidad_neta')}
    por_empresa = {}
    for ini in inis:
        rc = os.path.join(DATOS_ERP, f'cuentas_{ini}.json')
        rs = os.path.join(DATOS_ERP, f'saldos_{ini}.json')
        if not (os.path.exists(rc) and os.path.exists(rs)):
            continue
        with open(rc, encoding='utf-8') as f:
            cs = json.load(f)
        cs, _ = cl.clasificar_catalogo(cs, ini)
        cuentas = {c['codigo']: c for c in cs}
        with open(rs, encoding='utf-8') as f:
            saldos = json.load(f)
        b = av.balance_general(saldos, cuentas, anio, mes)
        r = av.estado_resultados(saldos, cuentas, anio, mes)
        por_empresa[ini] = {'balance': b, 'resultados': r}
        for k in bal:
            bal[k] += b.get(k, 0.0)
        for k in er:
            er[k] += r.get({'utilidad_bruta': 'utilidad_bruta'}.get(k, k), 0.0)

    # Eliminación de saldos, por la clase de cuenta que la generó. Ver
    # `eliminaciones()`: repartirla por el signo del neto descuadraba el
    # consolidado cuando una empresa tenía cuentas de los dos lados.
    elim_activo, elim_pasivo = elim['activo'], elim['pasivo']
    bal['activo'] -= elim_activo
    bal['pasivo'] -= elim_pasivo

    # ELIMINACIÓN DE INGRESOS Y GASTOS ENTRE EMPRESAS.
    #
    # Faltaba: durante un tiempo esta función eliminaba los saldos del balance
    # pero dejaba el Estado de Resultados igual que una suma simple. El
    # consolidado reportaba 61,480,819 de ingresos cuando 17,514,783 de esos
    # eran facturas que las empresas se hicieron entre ellas — un 28% inflado.
    #
    # Se elimina el MISMO importe de los ingresos de quien vendió y de los
    # gastos de quien compró, así que la utilidad del grupo NO cambia. Esa es
    # justamente la prueba de que la eliminación está bien hecha: consolidar no
    # crea ni destruye utilidad, solo deja de contar dos veces la operación.
    # SE ELIMINA LO QUE EMPAREJA, igual que con los saldos. Si el grupo facturó
    # 52.6 millones entre sus empresas pero solo registró 41.6 de compras, lo
    # que de verdad es una operación interna son los 41.6 comunes; los 11.0 de
    # diferencia son facturas que un lado emitió y el otro no registró.
    #
    # Eliminar cada lado por su cuenta CAMBIARÍA la utilidad del grupo por esa
    # diferencia, y consolidar no puede crear ni destruir utilidad. Pasó: en
    # diciembre de 2024 la utilidad consolidada salía 11 millones peor que la
    # suma de las empresas, y el descalce se descompone en tres importes
    # redondos (7.5M, 3.0M y 0.5M) que delatan facturas sin registrar.
    ic = _interco_resultados(cliente, anio, mes, inis)
    comun = min(ic['ingresos'], ic['gastos'])
    descalce = round(ic['ingresos'] - ic['gastos'], 2)
    er['ingresos'] -= comun
    er['gastos_operacion'] -= comun
    er['utilidad_bruta'] = er['ingresos'] - er['costo']
    er['utilidad_operacion'] = er['utilidad_bruta'] - er['gastos_operacion']
    er['resultado_antes_impuestos'] = (er['utilidad_operacion']
                                       - er['resultado_financiero'] - er['otros'])
    er['utilidad_neta'] = er['resultado_antes_impuestos'] - er['impuestos']

    return {
        'periodo': f'{anio}-{mes:02d}', 'empresas': list(por_empresa),
        'balance': bal, 'resultados': er,
        'eliminado_saldos': round(min(elim_activo, elim_pasivo), 2),
        # Cada lado por separado, además del mínimo. Quien consolide un rubro
        # —el activo circulante, por ejemplo— necesita restar exactamente lo
        # que se le restó al activo, no el mínimo de los dos lados: con eso el
        # rubro dejaría de sumar el total del estado por la diferencia.
        'eliminado_activo': round(elim_activo, 2),
        'eliminado_pasivo': round(elim_pasivo, 2),
        'eliminado_resultados': round(comun, 2),
        # El descalce de facturación intercompañía NO se ajusta: se revela.
        # Es facturación que un lado emitió y el otro no registró, y quien lo
        # tiene que resolver es contabilidad, no este código.
        'descalce_facturacion': descalce,
        'sin_conciliar': elim['sin_conciliar'],
        'descuadre': round(bal['activo'] - (bal['pasivo'] + bal['capital_contable']
                                            + bal['resultados_acumulados']
                                            + bal['resultado_ejercicio']), 2),
        'por_empresa': por_empresa,
    }


def _interco_resultados(cliente, anio, mes, inis):
    """Ingresos y gastos del grupo con el propio grupo, en un mes.

    Se lee de las FACTURAS, no del mayor: es donde está identificada la
    contraparte. Y se usa el SUBTOTAL, no el total — el Estado de Resultados
    viene del mayor y está neto de IVA, así que restarle un total con impuestos
    dejaría el ingreso consolidado más bajo de lo debido, con un error que
    además crece con el volumen y parecería una tendencia.

    Los dos lados deberían coincidir: lo que una empresa del grupo facturó a
    otra es lo que esa otra le compró. Se midió la reciprocidad en 0.1%, así
    que eliminar cada lado por su cuenta deja la utilidad prácticamente igual.
    """
    mapa = cliente.mapa_interco()
    tot = {'ingresos': 0.0, 'gastos': 0.0}
    for ini in inis:
        for tipo, campo in (('venta', 'ingresos'), ('compra', 'gastos')):
            ruta = os.path.join(DATOS_ERP, f'facturas_{ini}_{tipo}.json')
            if not os.path.exists(ruta):
                continue
            with open(ruta, encoding='utf-8') as f:
                docs = json.load(f)
            for d in docs:
                if (d.get('clase_documento') != 'normal'
                        or d.get('anio') != anio or d.get('mes') != mes):
                    continue
                rfc = (d.get('rfc') or '').strip().upper()
                cc = (d.get('contraparte_id') or '').strip().upper()
                if mapa.get(rfc) or mapa.get(f'{ini}:{cc}'):
                    tot[campo] += d.get('subtotal') or 0.0
    return {k: round(v, 2) for k, v in tot.items()}
