# -*- coding: utf-8 -*-
"""
===============================================================================
 VERIFICACIÓN DE CUADRE — corre esto antes de creerle a cualquier número
===============================================================================
Un error de extracción contable casi nunca se anuncia. Los totales se ven
razonables, las gráficas salen bonitas, y el problema solo aparece cuando
alguien de fuera pregunta por qué el activo no coincide con lo que reporta el
contador. Este archivo existe para que ese momento no llegue.

Hace DOS pruebas, y la segunda es la que de verdad vale:

  1. IDENTIDAD CONTABLE (por periodo)
         Activo = Pasivo + Capital contable + Resultado del ejercicio
     Es necesaria pero débil: se cumple sola mientras los signos estén bien,
     incluso si las cuentas están clasificadas en el cajón equivocado. Pasa
     esta prueba un Balance con los intereses metidos en ventas.

  2. ARTICULACIÓN ENTRE ESTADOS (la prueba fuerte)
         suma de los Estados de Resultados mensuales de enero a N
           ==  resultado del ejercicio del Balance al mes N
     Esta sí es difícil de pasar por accidente, porque los dos lados se
     calculan por caminos completamente distintos: el Estado de Resultados suma
     MOVIMIENTOS del mes; el Balance toma la ÚLTIMA POSICIÓN CONOCIDA de cada
     cuenta. Que coincidan al peso durante doce meses seguidos significa que la
     clasificación, los signos, el saldo de apertura y la paginación están todos
     bien a la vez. Es la prueba que atrapa el truncamiento silencioso de
     descargas —el bug más peligroso de este proyecto— porque a una cuenta que
     falta se le nota en el acumulado aunque el mes aislado parezca sano.

CUÁNDO CORRERLO: después de cada extracción, y obligatoriamente antes de subir
un snapshot a S3. Devuelve exit code 1 si algo no cuadra, para poder encadenarlo
en refrescar.py y que el pipeline se detenga en vez de publicar números malos.

    python verificar_cuadre.py                # todas las empresas con datos
    python verificar_cuadre.py --empresa NG
===============================================================================
"""
import os
import sys
import json
import argparse

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(AQUI, 'erp'))

import analisis_vertical_horizontal as av
from erp import clasificador_cuentas as cl  # noqa: E402

DATOS = os.path.join(AQUI, 'datos_erp')

# Tolerancia. No es cero absoluto por el redondeo de punto flotante al sumar
# decenas de miles de renglones; es lo bastante estrecha para que un centavo
# real no se escape.
TOLERANCIA = 1.0


def _cargar(empresa):
    with open(os.path.join(DATOS, f'cuentas_{empresa}.json'), encoding='utf-8') as f:
        cuentas = json.load(f)
    # Se reclasifica siempre al cargar, en vez de confiar en la `clase` que
    # venga guardada: un archivo extraído antes de un cambio en el clasificador
    # trae clases viejas, y esa discrepancia es invisible salvo que se haga esto.
    cuentas, informe = cl.clasificar_catalogo(cuentas, empresa)
    with open(os.path.join(DATOS, f'saldos_{empresa}.json'), encoding='utf-8') as f:
        saldos = json.load(f)
    return {c['codigo']: c for c in cuentas}, saldos, informe


def periodos_de(saldos):
    """Los (año, mes) presentes, ordenados, excluyendo el renglón de apertura
    (que es anterior al primer ejercicio y no es un periodo reportable)."""
    return sorted({(s['anio'], s['mes']) for s in saldos})


def verificar_empresa(empresa, verboso=True):
    cuentas, saldos, informe = _cargar(empresa)
    fallas = []

    # Una cuenta sin clasificar solo importa SI MUEVE DINERO. El plan de
    # cuentas trae cajones vacíos y reservados (en Networks, dos raíces
    # llamadas literalmente "#9" y "#10"), y alarmar por ellos convertiría
    # este verificador en un semáforo permanentemente en rojo — que es lo mismo
    # que no tener verificador. Se revisa contra los saldos reales.
    con_movimiento = {s['codigo'] for s in saldos
                      if abs(s.get('saldo_final') or 0) > 0.005
                      or abs(s.get('debe') or 0) > 0.005
                      or abs(s.get('haber') or 0) > 0.005}
    huerfanas = [c for k, c in cuentas.items()
                 if c.get('clase_via', '').endswith('sin evidencia') and k in con_movimiento]
    if huerfanas:
        fallas.append(f'{len(huerfanas)} cuenta(s) CON MOVIMIENTO y sin clasificar: '
                      + ', '.join(f"{c['codigo']} {c['nombre'][:30]}" for c in huerfanas[:5]))
    if informe['conflictos']:
        fallas.append(f"{len(informe['conflictos'])} cajón(es) con evidencia contradictoria")

    pers = periodos_de(saldos)
    if not pers:
        return [f'{empresa}: no hay saldos'], None

    # Se verifica año por año: el resultado del ejercicio se reinicia en enero,
    # así que acumular a través del cierre anual compararía peras con manzanas.
    anios = sorted({a for a, _ in pers})
    filas = []
    for anio in anios:
        acumulado = 0.0
        for (a, m) in [p for p in pers if p[0] == anio]:
            bal = av.balance_general(saldos, cuentas, a, m)
            er = av.estado_resultados(saldos, cuentas, a, m)
            # UTILIDAD NETA, no "antes de impuestos". El resultado del ejercicio
            # que trae el Balance incluye TODAS las cuentas de resultados, y el
            # impuesto a la utilidad es una de ellas. Cuando el Estado de
            # Resultados empezó a separar el ISR y la PTU en su propio renglón,
            # comparar contra "antes de impuestos" dejó de articular y esta
            # prueba marcó 139 periodos. Era la prueba haciendo su trabajo: el
            # cambio en un módulo rompió un supuesto del otro, y se supo de
            # inmediato en vez de meses después.
            acumulado += er['utilidad_neta']

            d1 = bal['descuadre']
            d2 = acumulado - bal['resultado_ejercicio']
            ok1, ok2 = abs(d1) <= TOLERANCIA, abs(d2) <= TOLERANCIA
            filas.append((f'{a}-{m:02d}', bal['activo'], bal['pasivo'],
                          bal['resultado_ejercicio'], acumulado, d1, d2, ok1, ok2))
            # PUNTO CIEGO QUE ESTA PRUEBA TUVO Y YA NO: un balance en CEROS
            # cumple la identidad contable perfectamente (0 = 0 + 0 + 0) y
            # pasaba como "ok". Pero un activo total de cero en una empresa en
            # marcha no es un cuadre: es la ausencia del dato.
            #
            # Pasa de verdad, y no por error de extracción: SAP hace cierre y
            # reapertura TOTAL a fin de año, arrasando también las cuentas de
            # balance. Verificado en NG: la cuenta de banco cierra noviembre en
            # 259,756.93, en diciembre recibe un haber de 289,023.16 que la deja
            # exactamente en cero, y enero la reabre. Por eso TODOS los
            # diciembres de TODAS las empresas daban activo = 0.
            #
            # Se reporta como problema porque para cualquier análisis anual el
            # dato que importa es la posición ANTES del asiento de cierre.
            if abs(bal['activo']) < 1.0 and abs(bal['pasivo']) < 1.0:
                fallas.append(
                    f'{a}-{m:02d}: balance en ceros — es el asiento de cierre y '
                    f'reapertura de SAP. El cierre anual hay que leerlo antes de '
                    f'ese asiento, no después.')
            if not ok1:
                fallas.append(f'{a}-{m:02d}: la identidad contable no cuadra por {d1:,.2f}')
            if not ok2:
                fallas.append(f'{a}-{m:02d}: el Estado de Resultados acumulado no articula '
                              f'con el Balance, difiere {d2:,.2f}')

    if verboso:
        print(f'\n=== {empresa} — {len(cuentas):,} cuentas, {len(saldos):,} saldos ===')
        print(f"{'periodo':<9}{'activo':>14}{'pasivo':>14}{'result.bal':>14}"
              f"{'result.acum':>14}{'ident.':>10}{'artic.':>10}")
        for f in filas:
            print(f'{f[0]:<9}{f[1]:>14,.0f}{f[2]:>14,.0f}{f[3]:>14,.0f}{f[4]:>14,.0f}'
                  f"{'ok' if f[7] else 'FALLA':>10}{'ok' if f[8] else 'FALLA':>10}")

    return fallas, filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--empresa')
    args = ap.parse_args()

    if args.empresa:
        empresas = [args.empresa.upper()]
    else:
        empresas = sorted(a.replace('saldos_', '').replace('.json', '')
                          for a in os.listdir(DATOS) if a.startswith('saldos_'))
    if not empresas:
        print('No hay archivos de saldos todavía. Corre primero la extracción.')
        raise SystemExit(1)

    todas = []
    for e in empresas:
        try:
            fallas, _ = verificar_empresa(e)
        except FileNotFoundError as ex:
            fallas = [f'falta un archivo: {ex.filename}']
        todas += [f'{e}: {f}' for f in fallas]

    print('\n' + '=' * 72)
    if todas:
        print(f' {len(todas)} PROBLEMA(S) — no subas el snapshot todavía')
        for f in todas:
            print(f'   · {f}')
        raise SystemExit(1)
    print(' TODO CUADRA — identidad contable y articulación entre estados, '
          'en todos los periodos')
    print('=' * 72)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
