# -*- coding: utf-8 -*-
r"""
===============================================================================
 DÓNDE VIVE EL ALMACÉN, Y CÓMO SE MUEVE AL BUCKET
===============================================================================
La configuración, las entradas manuales y la bitácora viven en un almacén. Cuál
lo deciden cuatro variables de entorno, no un archivo — ver
`repositorio.almacen_por_defecto()` para el porqué.

    python finanzas/configuracion/almacenar.py --donde
    python finanzas/configuracion/almacenar.py --comprobar
    python finanzas/configuracion/almacenar.py --migrar
    python finanzas/configuracion/almacenar.py --verificar

POR QUÉ HAY UNA COMPROBACIÓN ANTES DE SUBIR NADA
------------------------------------------------
El bucket que sirve el tablero tiene su prefijo `data/` **de lectura pública**:
así es como la página, que no lleva credenciales, baja los chunks de
facturación. Está bien para lo que hay ahí, y está mal para todo lo demás.

Las entradas manuales son cifras del negocio y la bitácora trae nombres de
personas. Subirlas a un prefijo que contesta sin credenciales las publica, y
nada avisaría: el archivo se sube, el pipeline lo lee, todo funciona. Se
descubriría el día que alguien pegue la URL en otro navegador.

Por eso `--migrar` no sube nada hasta que `--comprobar` demuestre, con un
objeto de prueba real, que el prefijo de destino NO contesta a quien no trae
credenciales. Es la misma comprobación que un humano haría, hecha siempre.

LOS SECRETOS SÍ PUEDEN VIAJAR
-----------------------------
Las credenciales del ERP se guardan cifradas con AES-256-GCM y una clave
derivada por cliente; lo que se sube es el texto cifrado, inútil sin la clave
maestra, que vive en el entorno y nunca en el almacén. Aun así van al mismo
prefijo privado que el resto: cifrado y privado no son alternativas, son capas.
===============================================================================
"""
import argparse
import os
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.dirname(AQUI))

import repositorio as repo                                        # noqa: E402
from almacen import AlmacenLocal, AlmacenS3, ConflictoDeEscritura  # noqa: E402

CANARIO = '_canario_de_visibilidad.json'


def _s3_desde_entorno():
    """El almacén de destino, o un error que dice exactamente qué falta."""
    bucket = os.environ.get(repo.VAR_S3_BUCKET, '').strip()
    if not bucket:
        raise SystemExit(
            'No hay bucket configurado. Sin él no hay a dónde migrar:\n'
            f'    set {repo.VAR_S3_BUCKET}=mi-bucket-privado\n'
            f'    set {repo.VAR_S3_PREFIJO}=config\n'
            f'    set {repo.VAR_S3_PERFIL}=facturacion-dashboard\n'
            f'    set {repo.VAR_S3_REGION}=us-east-1   (opcional)')
    return AlmacenS3(
        bucket,
        perfil=os.environ.get(repo.VAR_S3_PERFIL, '').strip() or None,
        region=os.environ.get(repo.VAR_S3_REGION, '').strip() or 'us-east-1',
        prefijo_base=os.environ.get(repo.VAR_S3_PREFIJO, '').strip('/'))


def _url_publica(bucket, region, clave):
    return f'https://{bucket}.s3.{region}.amazonaws.com/{clave}'


def _responde_sin_credenciales(url):
    """(contesta, detalle). True significa que cualquiera con la URL lo lee."""
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return True, f'HTTP {r.status}'
    except urllib.error.HTTPError as e:
        return False, f'HTTP {e.code}'
    except Exception as e:                                       # noqa: BLE001
        # Un fallo de red no es una prueba de privacidad. Se trata como
        # "no lo sé", que para esto vale lo mismo que "no".
        return None, str(e)


def comprobar(verboso=True):
    """¿Se puede escribir ahí, y ese sitio es privado? Devuelve True si las dos.

    Escribe un objeto de prueba, lo interroga desde fuera y lo borra. Comprobar
    la política del bucket no sirve: el perfil que usa el pipeline no tiene
    permiso para leerla, y aunque lo tuviera, lo que importa no es lo que la
    política dice sino lo que el bucket contesta.
    """
    from botocore.exceptions import ClientError
    s3 = _s3_desde_entorno()
    bucket = s3.bucket
    region = os.environ.get(repo.VAR_S3_REGION, '').strip() or 'us-east-1'
    clave = s3._clave(CANARIO)
    ok = True

    if verboso:
        print(f'  destino     : s3://{bucket}/{clave}')

    # 1. ¿se puede escribir?
    try:
        version = s3.escribir(CANARIO, {'canario': True})
    except ConflictoDeEscritura:
        # Quedó de una corrida anterior que no llegó a borrarlo.
        _, version = s3.leer(CANARIO)
        version = s3.escribir(CANARIO, {'canario': True}, version)
    except ClientError as e:
        codigo = e.response['Error']['Code']
        print(f'  escritura   : DENEGADA ({codigo})')
        print(_ayuda_iam(bucket, s3.prefijo_base))
        return False
    if verboso:
        print('  escritura   : OK')

    try:
        # 2. ¿contesta sin credenciales?
        contesta, detalle = _responde_sin_credenciales(
            _url_publica(bucket, region, clave))
        if contesta is True:
            print(f'  privacidad  : NO — contesta sin credenciales ({detalle})')
            print('\n  ALTO: ese prefijo es de lectura pública. Ahí no pueden ir')
            print('  las entradas manuales ni la bitácora: son cifras del')
            print('  negocio y nombres de personas. Usa un prefijo o un bucket')
            print('  que no esté cubierto por la política de lectura pública.')
            ok = False
        elif contesta is False:
            if verboso:
                print(f'  privacidad  : OK — no contesta sin credenciales ({detalle})')
        else:
            print(f'  privacidad  : NO SE PUDO COMPROBAR ({detalle})')
            print('  No se continúa: sin esta prueba no hay forma de saber si')
            print('  lo que se suba queda a la vista.')
            ok = False

        # 3. ¿el bucket soporta escritura condicional? Sin eso, AlmacenS3 no
        #    puede evitar que dos guardados se pisen, y prefiere fallar.
        try:
            s3.escribir(CANARIO, {'canario': 'version equivocada'}, '0' * 32)
            print('  concurrencia: NO — aceptó una escritura con versión falsa')
            ok = False
        except ConflictoDeEscritura:
            if verboso:
                print('  concurrencia: OK — rechaza escrituras desactualizadas')
    finally:
        try:
            s3.s3.delete_object(Bucket=bucket, Key=clave)
        except ClientError:
            print(f'  aviso: no se pudo borrar el canario {clave}')
    return ok


def _ayuda_iam(bucket, prefijo):
    p = (prefijo + '/') if prefijo else ''
    return f"""
  El perfil no puede escribir ahí. Hace falta una política como esta sobre
  el usuario o rol que usa el pipeline (no sobre el bucket):

    {{
      "Version": "2012-10-17",
      "Statement": [
        {{"Effect": "Allow",
         "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
         "Resource": "arn:aws:s3:::{bucket}/{p}*"}},
        {{"Effect": "Allow",
         "Action": "s3:ListBucket",
         "Resource": "arn:aws:s3:::{bucket}",
         "Condition": {{"StringLike": {{"s3:prefix": "{p}*"}}}}}}
      ]
    }}

  Y comprueba que la política del BUCKET no extienda la lectura pública a
  ese prefijo: --comprobar lo verifica de verdad, pidiéndolo sin credenciales."""


def _rutas_locales(local):
    return local.listar('')


def migrar(forzar=False, simular=False):
    local = AlmacenLocal(repo.raiz_local())
    rutas = _rutas_locales(local)
    if not rutas:
        raise SystemExit(f'No hay nada en {repo.raiz_local()} que migrar.')

    print('Comprobando el destino antes de subir nada:')
    if not comprobar():
        raise SystemExit('\nNo se migró nada.')

    s3 = _s3_desde_entorno()
    print(f'\n{len(rutas)} archivo(s) para migrar:')
    subidos, saltados = 0, 0
    for ruta in rutas:
        datos, _ = local.leer(ruta)
        actual, version = s3.leer(ruta)
        if actual is not None and not forzar:
            print(f'  · {ruta}  — ya existe, se salta (usa --forzar para reemplazar)')
            saltados += 1
            continue
        if simular:
            print(f'  · {ruta}  — se subiría')
            subidos += 1
            continue
        s3.escribir(ruta, datos, version)
        print(f'  · {ruta}  — subido')
        subidos += 1

    print(f'\n{"(simulación) " if simular else ""}subidos: {subidos} · '
          f'saltados: {saltados}')
    if subidos and not simular:
        print('\nA partir de ahora, con esas variables de entorno puestas, todo\n'
              'el pipeline lee y escribe ahí. Compruébalo con --verificar.')


def verificar():
    """Compara disco y bucket archivo por archivo. Dice qué difiere, no arregla."""
    local = AlmacenLocal(repo.raiz_local())
    s3 = _s3_desde_entorno()
    rutas = sorted(set(_rutas_locales(local)) | set(s3.listar('')))
    if not rutas:
        raise SystemExit('No hay nada que comparar.')
    iguales = diferentes = solo_local = solo_s3 = 0
    for ruta in rutas:
        a, _ = local.leer(ruta)
        b, _ = s3.leer(ruta)
        if a is None:
            print(f'  solo en S3    : {ruta}'); solo_s3 += 1
        elif b is None:
            print(f'  solo en disco : {ruta}'); solo_local += 1
        elif a == b:
            iguales += 1
        else:
            print(f'  DIFIEREN      : {ruta}'); diferentes += 1
    print(f'\n  iguales {iguales} · difieren {diferentes} · '
          f'solo en disco {solo_local} · solo en S3 {solo_s3}')
    return 0 if (diferentes or solo_local or solo_s3) == 0 else 1


def main():
    ap = argparse.ArgumentParser(
        description='Dónde vive el almacén y cómo moverlo al bucket.')
    ap.add_argument('--donde', action='store_true',
                    help='qué almacén está activo ahora mismo')
    ap.add_argument('--comprobar', action='store_true',
                    help='¿se puede escribir en el destino, y es privado?')
    ap.add_argument('--migrar', action='store_true',
                    help='sube el almacén local al bucket')
    ap.add_argument('--verificar', action='store_true',
                    help='compara disco y bucket archivo por archivo')
    ap.add_argument('--forzar', action='store_true',
                    help='con --migrar: reemplaza lo que ya exista en el bucket')
    ap.add_argument('--simular', action='store_true',
                    help='con --migrar: dice qué haría, sin subir nada')
    args = ap.parse_args()

    if args.donde or not any((args.comprobar, args.migrar, args.verificar)):
        print(f'Almacén activo: {repo.descripcion_almacen()}')
        activo = repo.almacen_por_defecto()
        rutas = activo.listar('')
        print(f'{len(rutas)} archivo(s):')
        for r in rutas:
            print(f'  · {r}')
        if not args.donde:
            print('\n(--comprobar, --migrar o --verificar para lo demás)')
        return 0
    if args.comprobar:
        print('Comprobando el destino:')
        return 0 if comprobar() else 1
    if args.migrar:
        migrar(forzar=args.forzar, simular=args.simular)
        return 0
    if args.verificar:
        return verificar()
    return 0


if __name__ == '__main__':
    sys.exit(main())
