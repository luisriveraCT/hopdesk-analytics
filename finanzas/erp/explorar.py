# -*- coding: utf-8 -*-
"""
===============================================================================
 EXPLORAR EL ERP — consultas sueltas, para mirar sin escribir código
===============================================================================
POR QUÉ EXISTE
--------------
Abrir `https://192.168.14.131:50000/b1s/v1` en el navegador pide usuario y
contraseña y **nunca deja entrar**, por más correcta que sea la contraseña.

No es un problema de credenciales: el Service Layer de SAP B1 no usa
autenticación básica. Necesita TRES datos —usuario, contraseña y la base de
datos de la empresa— enviados en un `POST /Login`. El diálogo del navegador
solo puede mandar dos, así que la petición se rechaza con HTTP 401 antes de
mirar siquiera la contraseña.

Esta herramienta hace el login correcto y te deja consultar.

USO
---
    python explorar.py --empresas                   qué empresas hay y su base
    python explorar.py --entidades                  qué se puede consultar
    python explorar.py --buscar factura             entidades que coincidan
    python explorar.py NG Invoices                  las primeras filas
    python explorar.py NG Invoices --campos DocNum,DocDate,DocTotal
    python explorar.py NG Invoices --filtro "DocDate ge '2026-01-01'" --n 5
    python explorar.py NG ChartOfAccounts --contar  cuántas hay en total

TODO ES DE SOLO LECTURA. No hay forma de escribir desde aquí, a propósito.
===============================================================================
"""
import os
import sys
import json
import argparse

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import sap_b1


def listar_empresas():
    print('Empresas con acceso al ERP:\n')
    print(f"  {'iniciales':<12}{'base de datos en SAP':<24}servidor")
    for ini in sap_b1.empresas_con_erp():
        try:
            cfg, _, fuente = sap_b1.credenciales(ini)
            print(f"  {ini:<12}{cfg['company']:<24}{cfg['url']}")
        except Exception as e:
            print(f'  {ini:<12}(sin credenciales: {type(e).__name__})')
    sin_erp = sap_b1.empresas_sin_erp()
    if sin_erp:
        print(f"\n  Sin ERP todavía: {', '.join(sin_erp)}")
    print('\nLa base de datos es el tercer dato que el navegador no puede mandar;')
    print('por eso su diálogo de usuario y contraseña siempre falla.')


def listar_entidades(empresa, filtro_texto=None):
    with sap_b1.SesionSAP(empresa) as ses:
        r = ses.s.get(ses.config['url'] + '/', timeout=90)
        nombres = sorted(v.get('name') or v.get('url')
                         for v in r.json().get('value', []))
    if filtro_texto:
        t = filtro_texto.lower()
        nombres = [n for n in nombres if n and t in n.lower()]
        print(f'Entidades que contienen "{filtro_texto}": {len(nombres)}\n')
    else:
        print(f'Entidades disponibles: {len(nombres)}\n')
    for i in range(0, len(nombres), 3):
        print('   ' + ''.join(f'{n:<34}' for n in nombres[i:i + 3]))


def consultar(empresa, entidad, campos, filtro, n, contar):
    with sap_b1.SesionSAP(empresa) as ses:
        if contar:
            total = ses.contar(entidad)
            print(f'{entidad} en {empresa}: {total:,} registros')
            if filtro:
                print('(el total es SIN filtro: este servidor no siempre respeta '
                      '$filter en el conteo — por eso no se muestra un número '
                      'filtrado que podría estar mal)')
            return
        sel = [c.strip() for c in campos.split(',')] if campos else None
        filas = ses.get_todo(entidad, select=sel, filtro=filtro, max_filas=n)
        print(f'{entidad} en {empresa}: mostrando {len(filas)}\n')
        for f in filas:
            plano = {k: v for k, v in f.items() if not isinstance(v, (list, dict))}
            if sel:
                plano = {k: plano.get(k) for k in sel}
            print(json.dumps(plano, ensure_ascii=False, indent=2)[:1200])
            print('   ' + '-' * 60)
        if filas and not sel:
            escalares = [k for k, v in filas[0].items()
                         if not isinstance(v, (list, dict))]
            anidados = [k for k, v in filas[0].items() if isinstance(v, list)]
            print(f'\n{len(escalares)} campos escalares'
                  + (f' · anidados: {", ".join(anidados)}' if anidados else ''))
            print('Usa --campos para pedir solo los que te interesan.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('empresa', nargs='?', help='iniciales, p.ej. NG')
    ap.add_argument('entidad', nargs='?', help='p.ej. Invoices')
    ap.add_argument('--empresas', action='store_true')
    ap.add_argument('--entidades', action='store_true')
    ap.add_argument('--buscar', metavar='TEXTO')
    ap.add_argument('--campos', metavar='A,B,C')
    ap.add_argument('--filtro', metavar='ODATA')
    ap.add_argument('--n', type=int, default=3)
    ap.add_argument('--contar', action='store_true')
    args = ap.parse_args()

    if args.empresas or not (args.empresa or args.entidades or args.buscar):
        listar_empresas()
        return
    # La empresa por defecto es la primera configurada, no una escrita aquí.
    empresa = (args.empresa or sap_b1.empresas_con_erp()[0]).upper()
    if args.entidades or args.buscar:
        listar_entidades(empresa, args.buscar)
        return
    if not args.entidad:
        print('Falta la entidad. Prueba: python explorar.py '
              f'{empresa} --entidades')
        return
    consultar(empresa, args.entidad, args.campos, args.filtro, args.n, args.contar)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
