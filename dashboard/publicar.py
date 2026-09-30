# -*- coding: utf-8 -*-
"""
===============================================================================
 PUBLICAR EL SNAPSHOT A S3
===============================================================================
Sube los datos del tablero al bucket y **borra lo que ya no corresponde**.

POR QUÉ BORRA, Y NO SOLO SUBE
------------------------------
Subir sin limpiar deja archivos huérfanos de generaciones anteriores, y en un
bucket que se lee por URL fija eso no es inocuo: el tablero pide los archivos
que dice su índice, pero cualquiera —o cualquier versión vieja del HTML que
alguien tenga abierta— puede seguir pidiendo los otros, y recibirlos.

Pasó de verdad. Al cambiar la fuente del Excel al ERP, el bucket conservó
`rows-2005.json`, `rows-2019.json` y `rows-sin-fecha.json`: archivos que solo
existían en la base de Excel y que el ERP no produce. Ahí se quedaron
sirviéndose durante dos días, con datos de una fuente retirada.

Por eso esto sincroniza en vez de sumar: sube lo que hay y retira lo que sobra.

    python publicar.py              sube y limpia
    python publicar.py --simular    dice qué haría, sin tocar el bucket
===============================================================================
"""
import os
import sys
import json
import argparse

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, 'data')

BUCKET = 'hopdesk-analytics-dashboard'
REGION = 'us-east-1'
PERFIL = 'facturacion-dashboard'
PREFIJO_DATOS = 'data/'

# Cuánto puede cachear el navegador. Corto a propósito: el snapshot se
# reemplaza y un caché largo haría que alguien viera datos viejos sin manera de
# saberlo. Un minuto es suficiente para que una recarga no vuelva a bajar todo.
CACHE = 'public, max-age=60'


def cliente_s3():
    import boto3
    sesion = boto3.Session(profile_name=PERFIL)
    return sesion.client('s3', region_name=REGION)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--simular', action='store_true',
                    help='muestra qué se subiría y qué se borraría, sin hacerlo')
    args = ap.parse_args()

    # El índice manda: es lo que el tablero va a pedir.
    with open(os.path.join(HERE, 'indice.json'), encoding='utf-8') as f:
        indice = json.load(f)
    esperados = {PREFIJO_DATOS + c['archivo'] for c in indice}

    locales = {PREFIJO_DATOS + a for a in os.listdir(DATA_DIR) if a.endswith('.json')}
    sobran_local = locales - esperados
    if sobran_local:
        print(f'AVISO: hay {len(sobran_local)} archivo(s) en data/ que el índice '
              f'no menciona; no se suben: {", ".join(sorted(sobran_local))}')

    s3 = cliente_s3()
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIJO_DATOS)
    en_bucket = {o['Key'] for o in r.get('Contents', [])}
    while r.get('IsTruncated'):
        r = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIJO_DATOS,
                               ContinuationToken=r['NextContinuationToken'])
        en_bucket |= {o['Key'] for o in r.get('Contents', [])}

    a_borrar = sorted(en_bucket - esperados)
    print(f'\nEn el bucket: {len(en_bucket)} archivo(s) · '
          f'el índice pide {len(esperados)}')
    if a_borrar:
        print(f'\nSe retiran {len(a_borrar)} archivo(s) que ya no corresponden:')
        for k in a_borrar:
            print(f'   {k}')
    else:
        print('\nNada que retirar.')

    if args.simular:
        print(f'\n(simulación: se subirían {len(esperados)} archivo(s) de datos '
              f'y el index.html)')
        return

    for c in indice:
        clave = PREFIJO_DATOS + c['archivo']
        ruta = os.path.join(DATA_DIR, c['archivo'])
        s3.upload_file(ruta, BUCKET, clave, ExtraArgs={
            'ContentType': 'application/json', 'CacheControl': CACHE})
        print(f'   subido {clave}  ({os.path.getsize(ruta) / 1048576:.2f} MB)')

    if a_borrar:
        # `delete_objects` NO lanza excepción cuando falla: devuelve los fallos
        # dentro de la respuesta, en `Errors`. La primera versión de esto
        # imprimía "retirados 3 archivo(s)" sin mirar esa lista, y los tres
        # archivos de la era Excel siguieron publicándose — con un mensaje de
        # éxito en pantalla. Hay que revisar la respuesta, siempre.
        r = s3.delete_objects(Bucket=BUCKET,
                              Delete={'Objects': [{'Key': k} for k in a_borrar]})
        borrados = [d['Key'] for d in r.get('Deleted', [])]
        errores = r.get('Errors', [])
        if borrados:
            print(f'   retirados {len(borrados)} archivo(s) obsoletos')
        if errores:
            print(f'\n   !! NO se pudieron retirar {len(errores)} archivo(s):')
            for e in errores:
                print(f"      {e['Key']}  →  {e['Code']}")
            if any(e['Code'] == 'AccessDenied' for e in errores):
                print('\n   El usuario de IAM no tiene permiso de borrado. Hasta '
                      'que lo tenga, esos archivos siguen publicándose aunque el '
                      'tablero ya no los pida.')
                print('   Se agrega "s3:DeleteObject" a la política del usuario, '
                      'junto a "s3:PutObject".')
            raise SystemExit(1)

    print('\nDatos publicados. El index.html se despliega aparte '
          '(Connect Cloud), con:')
    print('   python construir.py --modo s3')


if __name__ == '__main__':
    main()
