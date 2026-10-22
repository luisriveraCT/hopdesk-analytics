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

Pasó de verdad: al cambiar de fuente, el bucket conservó `rows-2005.json`,
`rows-2019.json` y `rows-sin-fecha.json`, archivos que la fuente nueva ya no
produce. Ahí se quedaron sirviéndose durante dos días, con datos que nadie
recalculaba.

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

# Las librerías y las fuentes que la página pide por URL. Viven versionadas en
# dashboard/estaticos/ y se publican aquí porque este script RETIRA del bucket
# lo que no reconoce: subirlas por fuera sería verlas desaparecer en la
# siguiente corrida.
DIR_ESTATICOS = os.path.join(HERE, 'estaticos')
PREFIJO_ESTATICOS = 'data/estaticos/'
TIPOS = {'.js': 'application/javascript; charset=utf-8',
         '.woff2': 'font/woff2', '.css': 'text/css; charset=utf-8'}
# Un día. No son inmutables —el nombre no lleva versión— pero cambian una vez
# al año, así que pedirlas en cada visita sería gasto puro.
CACHE_ESTATICOS = 'public, max-age=86400'

# Cuánto puede cachear el navegador. Corto a propósito: el snapshot se
# reemplaza y un caché largo haría que alguien viera datos viejos sin manera de
# saberlo. Un minuto es suficiente para que una recarga no vuelva a bajar todo.
CACHE = 'public, max-age=60'


def estaticos_locales():
    """{clave en el bucket: ruta en disco} de todo lo que hay que publicar."""
    salida = {}
    if not os.path.isdir(DIR_ESTATICOS):
        return salida
    for raiz, _, archivos in os.walk(DIR_ESTATICOS):
        for a in archivos:
            if a.startswith('_'):
                continue                      # notas de trabajo, no se publican
            ruta = os.path.join(raiz, a)
            rel = os.path.relpath(ruta, DIR_ESTATICOS).replace(os.sep, '/')
            salida[PREFIJO_ESTATICOS + rel] = ruta
    return salida


def md5_de(ruta):
    import hashlib
    h = hashlib.md5()
    with open(ruta, 'rb') as f:
        for trozo in iter(lambda: f.read(1 << 20), b''):
            h.update(trozo)
    return h.hexdigest()


def cliente_s3():
    import boto3
    sesion = boto3.Session(profile_name=PERFIL)
    return sesion.client('s3', region_name=REGION)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--simular', action='store_true',
                    help='muestra qué se subiría y qué se borraría, sin hacerlo')
    args = ap.parse_args()

    # Los índices mandan: son lo que el tablero va a pedir. Uno por tipo de
    # factura, y TODOS entran en `esperados`. Si el de compras faltara aquí, la
    # limpieza de abajo retiraría del bucket los trozos de compras en cada
    # corrida, y el tablero se quedaría pidiéndolos.
    indice = []
    for nombre in ('indice.json', 'indice-compra.json'):
        ruta = os.path.join(HERE, nombre)
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                indice += json.load(f)
        elif nombre == 'indice.json':
            raise SystemExit('Falta indice.json: corre exportar_dashboard.py')
    estaticos = estaticos_locales()
    # Los estáticos entran en `esperados`: así la limpieza de abajo no los ve
    # como sobrantes y no hay que acordarse de excluirlos a mano.
    esperados = {PREFIJO_DATOS + c['archivo'] for c in indice} | set(estaticos)

    locales = {PREFIJO_DATOS + os.path.relpath(os.path.join(r, a), DATA_DIR).replace(os.sep, '/')
               for r, _, archivos in os.walk(DATA_DIR) for a in archivos
               if a.endswith('.json')}
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
        print(f'\n(simulación: se subirían {len(indice)} archivo(s) de datos '
              f'y {len(estaticos)} estático(s))')
        return

    for c in indice:
        clave = PREFIJO_DATOS + c['archivo']
        ruta = os.path.join(DATA_DIR, c['archivo'])
        s3.upload_file(ruta, BUCKET, clave, ExtraArgs={
            'ContentType': 'application/json', 'CacheControl': CACHE})
        print(f'   subido {clave}  ({os.path.getsize(ruta) / 1048576:.2f} MB)')

    # Los estáticos se suben solo si cambiaron: son 1.8 MB que cambian una vez
    # al año, y volver a empujarlos en cada actualización es tiempo regalado.
    iguales = 0
    for clave, ruta in sorted(estaticos.items()):
        try:
            etag = s3.head_object(Bucket=BUCKET, Key=clave)['ETag'].strip('"')
        except Exception:                                    # noqa: BLE001
            etag = None
        if etag == md5_de(ruta):
            iguales += 1
            continue
        ext = os.path.splitext(ruta)[1].lower()
        s3.upload_file(ruta, BUCKET, clave, ExtraArgs={
            'ContentType': TIPOS.get(ext, 'application/octet-stream'),
            'CacheControl': CACHE_ESTATICOS})
        print(f'   subido {clave}  ({os.path.getsize(ruta) / 1024:.0f} KB)')
    if iguales:
        print(f'   {iguales} estático(s) ya estaban al día')

    if a_borrar:
        # `delete_objects` NO lanza excepción cuando falla: devuelve los fallos
        # dentro de la respuesta, en `Errors`. La primera versión de esto
        # imprimía "retirados 3 archivo(s)" sin mirar esa lista, y los tres
        # archivos obsoletos siguieron publicándose — con un mensaje de
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
