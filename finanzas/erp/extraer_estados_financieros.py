# -*- coding: utf-8 -*-
"""
===============================================================================
 EXTRACCIÓN DE ESTADOS FINANCIEROS DESDE EL ERP
===============================================================================
Orquestador. No conoce SAP: le pide al registro el conector configurado, y
trabaja contra la forma canónica. El día que entre un segundo ERP, este
archivo no se toca.

-------------------------------------------------------------------------------
 LA ARQUITECTURA: SNAPSHOT. Y NO ES UN PARCHE MIENTRAS LLEGA ALGO MEJOR.
-------------------------------------------------------------------------------
                 [VPN]                      [S3]                  [internet]
   SAP B1  ──────────────►  máquina local  ──────►  snapshot  ──────►  app
   192.168.14.131          extrae, verifica        JSON en           publicada
   (IP privada)            y publica               AWS               (solo lee)

El servidor SAP vive en una IP privada. Una app publicada en Connect Cloud no
lo alcanza, y no es cuestión de configuración: no existe ruta de red entre
internet y 192.168.14.131, ni debería existir. Así que sí — el plan es el que
recuerdas, el mismo de HopDesk: **la extracción corre local con VPN, deja un
snapshot en S3, y la versión publicada solo lee ese snapshot.**

Vale la pena decir por qué esto NO es un arreglo temporal. Aunque mañana IT
meta una copia de la app dentro de la VPN, el patrón se queda, por tres razones
que no cambian con la red:

  · La app publicada nunca necesita credenciales de SAP. No puede filtrar lo
    que no tiene. Exponer el ERP a un servicio en internet para ahorrarse un
    paso sería cambiar una molestia por un riesgo.
  · El snapshot es reproducible y auditable: es un archivo con fecha que se
    puede volver a leer, comparar y explicar. Una consulta en vivo contra el
    ERP entrega un número distinto cada vez que alguien recarga, y entonces dos
    personas viendo "el mismo" reporte discuten sobre cuál está bien.
  · La app sigue en pie cuando el ERP no. Mantenimiento de SAP, VPN caída,
    servidor saturado: el snapshot sigue ahí. Una app que consulta en vivo se
    cae junto con su fuente, y se cae justo el día que más se está usando.

Lo que la copia dentro de la VPN sí aportará —y para eso conviene— es correr la
extracción sola y a horario, sin depender de que alguien tenga la laptop
encendida y conectada. Eso mejora quién dispara el proceso, no cómo llegan los
datos a la app de fuera.

REGLA DEL PIPELINE: antes de publicar un snapshot se corre
`finanzas/verificar_cuadre.py`, que devuelve exit code 1 si algo no articula.
Publicar números que no cuadran cuesta mucho más que no publicar.

Uso:
    python -m finanzas.erp.extraer_estados_financieros --diagnostico
    python -m finanzas.erp.extraer_estados_financieros --empresa NG
    python -m finanzas.erp.extraer_estados_financieros --todas --desde 2020
===============================================================================
"""
import os
import sys
import json
import argparse
import datetime as dt

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))       # finanzas/
sys.path.insert(0, AQUI)                        # finanzas/erp/

import sap_b1
import registro_conectores as reg

SALIDA_DIR = os.path.join(os.path.dirname(AQUI), 'datos_erp')


def _guardar(nombre, obj):
    os.makedirs(SALIDA_DIR, exist_ok=True)
    ruta = os.path.join(SALIDA_DIR, nombre)
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    kb = os.path.getsize(ruta) / 1024
    print(f'  guardado: {nombre}  ({kb:,.0f} KB)')
    return ruta


def mostrar_diagnostico(empresas):
    print('=' * 78)
    print(' DIAGNÓSTICO DE CONEXIÓN AL ERP')
    print('=' * 78)
    hay_red = False
    for ini in empresas:
        d = sap_b1.diagnostico(ini)
        print(f'\n--- {ini} ---')
        print(f'  servidor     : {d.get("servidor", "?")}')
        print(f'  base de datos: {d.get("company_db", "?")}')
        print(f'  credenciales : {d.get("fuente_credenciales", "?")}')
        print(f'  red          : {d.get("red")}')
        print(f'  login        : {d.get("login")}')
        if d.get('endpoints'):
            hay_red = True
            print('  permisos de lectura:')
            for ep, r in d['endpoints'].items():
                if r['ok']:
                    print(f'      OK     {ep:<20} campos: {", ".join(r["campos"][:5])}')
                else:
                    print(f'      NEGADO {ep:<20} {r["error"][:100]}')
                    print(f'             ({r["desc"]})')
    if not hay_red:
        print('\n' + '!' * 78)
        print(' No hubo alcance de red al servidor SAP.')
        print(' El servidor está en una IP privada: hay que estar en la red de la')
        print(' oficina o con la VPN conectada. Conéctate y vuelve a correr esto.')
        print('!' * 78)
    return hay_red


def extraer_empresa(iniciales, desde_anio=2020, con_saldos=True):
    print(f'\n=== {iniciales} ===')
    with sap_b1.SesionSAP(iniciales) as ses:
        print('  login OK · extrayendo catálogo de cuentas...')
        cuentas = sap_b1.extraer_catalogo_cuentas(ses)
        print(f'  {len(cuentas):,} cuentas')

        sin_clasificar = [c for c in cuentas if c['clase'] == 'OTRO']
        if sin_clasificar:
            print(f'  AVISO: {len(sin_clasificar)} cuenta(s) no cayeron en ninguna clase '
                  f'(quedaron como OTRO). Ejemplos:')
            for c in sin_clasificar[:5]:
                print(f'      {c["codigo"]:<14} {c["nombre"][:48]}')
            print('  Revisa MAPEO_CLASE_POR_PREFIJO en sap_b1.py — no se adivinan clases.')

        _guardar(f'cuentas_{iniciales}.json', cuentas)

        if not con_saldos:
            return cuentas, []

        print(f'  extrayendo pólizas desde {desde_anio} (parte lenta, reanudable)...')
        cache = os.path.join(SALIDA_DIR, 'cache_movimientos')

        def progreso(i, total, a, m, n_ctas, desde_cache):
            marca = 'cache' if desde_cache else 'SAP  '
            barra = ('#' * int(28 * i / total)).ljust(28)
            print(f'\r    [{barra}] {i:>3}/{total}  {a}-{m:02d}  {marca}  '
                  f'{n_ctas:>4} cuentas', end='', flush=True)

        saldos = sap_b1.extraer_saldos_por_mes(
            ses, desde_anio=desde_anio, cache_dir=cache, progreso=progreso)
        print()
        print(f'  {len(saldos):,} renglones de saldo mensual por cuenta')
        _guardar(f'saldos_{iniciales}.json', saldos)
        return cuentas, saldos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--diagnostico', action='store_true',
                    help='solo probar conexión y permisos, sin extraer')
    ap.add_argument('--empresa',
                    help='iniciales de la empresa; las disponibles salen de '
                         'la configuración del cliente (configurar.py --mostrar)')
    ap.add_argument('--todas', action='store_true')
    ap.add_argument('--desde', type=int, default=2020)
    ap.add_argument('--sin-saldos', action='store_true',
                    help='solo catálogo de cuentas (rápido)')
    args = ap.parse_args()

    reg.inicializar()
    conector = reg.obtener(reg.SAP_B1)
    faltan = conector.capacidades.faltantes_para_estados_financieros()
    if faltan:
        print(f'AVISO: el conector declara que le falta: {", ".join(faltan)}')

    empresas = ([args.empresa.upper()] if args.empresa
                else sap_b1.empresas_con_erp() if args.todas
                else sap_b1.empresas_con_erp()[:1])

    if args.diagnostico:
        mostrar_diagnostico(empresas)
        return

    if not mostrar_diagnostico(empresas[:1]):
        raise SystemExit(1)

    for ini in empresas:
        try:
            extraer_empresa(ini, desde_anio=args.desde, con_saldos=not args.sin_saldos)
        except PermissionError as e:
            print(f'  PERMISO FALTANTE en {ini}:\n    {e}')
        except Exception as e:
            print(f'  ERROR en {ini}: {type(e).__name__}: {e}')

    sin_erp = sap_b1.empresas_sin_erp()
    if sin_erp:
        print(f'\nNota: {", ".join(sin_erp)} no tiene(n) credenciales SAP configuradas. '
              f'Si esa empresa ya opera en SAP, hay que agregar sus variables '
              f'SAP_<INICIALES>_* para incluirla.')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
