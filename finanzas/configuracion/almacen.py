# -*- coding: utf-8 -*-
"""
===============================================================================
 ALMACÉN DE CONFIGURACIÓN — con escritura atómica de verdad
===============================================================================
EL PROBLEMA QUE ESTE ARCHIVO EXISTE PARA NO REPETIR
---------------------------------------------------
El sistema anterior guardaba todo en S3 y cada guardado hacía
leer → modificar → sobrescribir, sin bloqueo ni versionado. Su propio código lo
documentaba con precisión incómoda: *"both S3 writes succeed, no exception is
raised anywhere, whichever process wrote last simply wins"*. Dos personas
editando a la vez: una pierde su cambio y nadie se entera. El único mitigante
era un bloqueo de archivo que solo funcionaba en Windows — y el despliegue real
corre en Linux, donde esa función retorna sin hacer nada.

No se arregla con cuidado ni con reintentos. Se arregla cambiando la operación:
**toda escritura lleva la versión que el llamador creía estar modificando**, y
el almacén la rechaza si alguien más escribió en medio. Es comparar-e-intercambiar,
y convierte un dato perdido en silencio en un error visible que se puede reintentar.

S3 soporta esto de forma nativa con escrituras condicionales (`If-Match` sobre el
ETag). No es una técnica exótica: es la misma idea que un `UPDATE ... WHERE
version = ?` en una base de datos.

DOS RESPALDOS, LA MISMA SEMÁNTICA
---------------------------------
  · `AlmacenLocal` — archivos en disco. Para correr sin nube y para pruebas.
  · `AlmacenS3`    — el bucket. Es el que usa la extracción de verdad.
Ambos cumplen el mismo contrato, incluida la detección de conflicto, para que un
error de concurrencia aparezca en la laptop y no por primera vez en producción.
===============================================================================
"""
import os
import json
import hashlib
from typing import Any, Dict, Optional, Tuple


class ConflictoDeEscritura(RuntimeError):
    """Alguien más modificó el dato entre tu lectura y tu escritura.

    No es un fallo del sistema: es el sistema haciendo su trabajo. Quien lo
    recibe debe volver a leer, reaplicar su cambio sobre lo nuevo y reintentar
    — nunca forzar la escritura, que es exactamente el dato perdido que se
    quiere evitar.
    """


class Almacen:
    """Contrato. `leer` devuelve (datos, version); `escribir` exige la versión."""

    def leer(self, ruta: str) -> Tuple[Optional[Any], Optional[str]]:
        raise NotImplementedError

    def escribir(self, ruta: str, datos: Any,
                 version_esperada: Optional[str] = None) -> str:
        """Guarda y devuelve la versión nueva.

        `version_esperada`:
          · una versión  → solo escribe si el dato sigue en esa versión.
          · None         → solo escribe si el dato NO existe (creación).
        No hay forma de decir "escribe pase lo que pase". Es intencional: esa
        opción es la que convierte el almacén en el anterior.
        """
        raise NotImplementedError

    def listar(self, prefijo: str) -> list:
        raise NotImplementedError


def _serializar(datos: Any) -> bytes:
    # `sort_keys` para que el mismo contenido produzca siempre los mismos bytes
    # y, por lo tanto, la misma versión. Sin eso, reescribir un dato idéntico
    # generaría una versión nueva y los conflictos serían aleatorios.
    return json.dumps(datos, ensure_ascii=False, sort_keys=True,
                      indent=2).encode('utf-8')


class AlmacenLocal(Almacen):
    """Archivos en disco. La versión es el hash del contenido."""

    def __init__(self, raiz: str):
        self.raiz = os.path.abspath(raiz)

    def _ruta(self, ruta: str) -> str:
        # Se normaliza y se comprueba que no salga de la raíz: un `..` en la
        # ruta del cliente no debe poder leer la carpeta de otro.
        completa = os.path.abspath(os.path.join(self.raiz, ruta))
        if not completa.startswith(self.raiz + os.sep) and completa != self.raiz:
            raise ValueError(f'Ruta fuera del almacén: {ruta!r}')
        return completa

    def leer(self, ruta: str):
        p = self._ruta(ruta)
        try:
            with open(p, 'rb') as f:
                crudo = f.read()
        except FileNotFoundError:
            return None, None
        return json.loads(crudo.decode('utf-8')), hashlib.sha256(crudo).hexdigest()

    def escribir(self, ruta: str, datos: Any, version_esperada=None) -> str:
        p = self._ruta(ruta)
        _, actual = self.leer(ruta)
        if actual != version_esperada:
            raise ConflictoDeEscritura(
                f'{ruta}: esperabas la versión {version_esperada!r} y la actual '
                f'es {actual!r}. Alguien más lo modificó: vuelve a leer, '
                f'reaplica tu cambio y reintenta.')
        crudo = _serializar(datos)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        # Se escribe a un temporal y se reemplaza: `os.replace` es atómico en el
        # mismo sistema de archivos, así que nadie llega a leer medio archivo.
        tmp = p + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(crudo)
        os.replace(tmp, p)
        return hashlib.sha256(crudo).hexdigest()

    def listar(self, prefijo: str):
        base = self._ruta(prefijo)
        if not os.path.isdir(base):
            return []
        salida = []
        for dirpath, _, archivos in os.walk(base):
            for a in archivos:
                if a.endswith('.tmp'):
                    continue
                completa = os.path.join(dirpath, a)
                salida.append(os.path.relpath(completa, self.raiz).replace(os.sep, '/'))
        return sorted(salida)


class AlmacenS3(Almacen):
    """El bucket, con escrituras condicionales por ETag.

    Requiere boto3. Si el bucket o la versión de S3 no soportan escritura
    condicional, `escribir` **falla en vez de degradarse a sobrescritura
    incondicional**: preferimos un error explícito hoy a un dato perdido en
    silencio dentro de seis meses.
    """

    def __init__(self, bucket: str, perfil: Optional[str] = None,
                 region: str = 'us-east-1', prefijo_base: str = ''):
        import boto3
        sesion = boto3.Session(profile_name=perfil) if perfil else boto3.Session()
        self.s3 = sesion.client('s3', region_name=region)
        self.bucket = bucket
        self.prefijo_base = prefijo_base.strip('/')

    def _clave(self, ruta: str) -> str:
        r = ruta.strip('/')
        return f'{self.prefijo_base}/{r}' if self.prefijo_base else r

    def leer(self, ruta: str):
        from botocore.exceptions import ClientError
        try:
            r = self.s3.get_object(Bucket=self.bucket, Key=self._clave(ruta))
        except ClientError as e:
            if e.response['Error']['Code'] in ('NoSuchKey', '404'):
                return None, None
            raise
        crudo = r['Body'].read()
        return json.loads(crudo.decode('utf-8')), r['ETag'].strip('"')

    def escribir(self, ruta: str, datos: Any, version_esperada=None) -> str:
        from botocore.exceptions import ClientError
        crudo = _serializar(datos)
        cond = ({'IfMatch': version_esperada} if version_esperada
                else {'IfNoneMatch': '*'})
        try:
            r = self.s3.put_object(Bucket=self.bucket, Key=self._clave(ruta),
                                   Body=crudo, ContentType='application/json',
                                   **cond)
        except ClientError as e:
            codigo = e.response['Error']['Code']
            if codigo in ('PreconditionFailed', 'ConditionalRequestConflict'):
                raise ConflictoDeEscritura(
                    f'{ruta}: otro proceso lo modificó mientras trabajabas. '
                    f'Vuelve a leer, reaplica tu cambio y reintenta.') from e
            if codigo == 'NotImplemented':
                raise RuntimeError(
                    'Este destino de S3 no soporta escrituras condicionales. '
                    'Sin ellas no hay forma de evitar que dos guardados '
                    'simultáneos se pisen, así que no se continúa: revisa la '
                    'configuración del bucket antes de usarlo para '
                    'configuración compartida.') from e
            raise
        return r['ETag'].strip('"')

    def listar(self, prefijo: str):
        p = self._clave(prefijo)
        salida, token = [], None
        while True:
            kw = {'Bucket': self.bucket, 'Prefix': p}
            if token:
                kw['ContinuationToken'] = token
            r = self.s3.list_objects_v2(**kw)
            for o in r.get('Contents', []):
                k = o['Key']
                if self.prefijo_base and k.startswith(self.prefijo_base + '/'):
                    k = k[len(self.prefijo_base) + 1:]
                salida.append(k)
            if not r.get('IsTruncated'):
                return sorted(salida)
            token = r.get('NextContinuationToken')


def actualizar_con_reintento(almacen: Almacen, ruta: str, transformar,
                             intentos: int = 5):
    """Lee, aplica `transformar(datos)` y guarda; si alguien escribió en medio,
    vuelve a leer y reaplica.

    Este es el patrón correcto y por eso está aquí, resuelto una sola vez, en
    lugar de repetido en cada llamador —que es como se acaba teniendo cinco
    variantes ligeramente distintas y cuatro de ellas mal.

    `transformar` puede ejecutarse más de una vez, así que debe ser una función
    pura sobre los datos: no mandes correos ni escribas archivos dentro.
    """
    for intento in range(intentos):
        datos, version = almacen.leer(ruta)
        nuevos = transformar(datos)
        try:
            return almacen.escribir(ruta, nuevos, version)
        except ConflictoDeEscritura:
            if intento == intentos - 1:
                raise
    raise AssertionError('inalcanzable')
