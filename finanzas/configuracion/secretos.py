# -*- coding: utf-8 -*-
"""
===============================================================================
 ALMACÉN DE SECRETOS — credenciales de ERP, cifradas y aisladas por cliente
===============================================================================
QUÉ GUARDA
----------
Las credenciales con las que se entra al ERP de cada cliente. Nada más. Ni
contraseñas de personas, ni tokens de sesión.

TRES DECISIONES, Y POR QUÉ
--------------------------
**1. Una clave derivada POR CLIENTE, no una clave global.**
El sistema anterior cifraba las credenciales de todos los clientes con una sola
clave maestra compartida; su propio código señalaba el riesgo. Aquí la clave
maestra nunca cifra nada directamente: de ella se deriva, con HKDF y el id del
cliente como contexto, una clave distinta para cada uno. Comprometer el blob de
un cliente no acerca a nadie a los demás, y rotar la clave de uno es posible sin
tocar al resto.

**2. AES-256-GCM, que autentica. Y si falla, FALLA.**
Esta es la corrección más importante respecto al sistema anterior. Allá, si el
descifrado de las credenciales de un cliente fallaba —clave rotada, blob
corrupto—, el código registraba un mensaje y **caía silenciosamente a las
credenciales globales del archivo de entorno**. Es decir: el cliente A podía
terminar autenticándose contra el ERP del cliente B. Estaba documentado como
diseño.

Aquí no hay camino alternativo. Si un secreto no se puede descifrar, se levanta
una excepción y la extracción de ese cliente se detiene. Una extracción que no
corre es un problema; una extracción que corre contra el ERP equivocado es un
incidente.

**3. El secreto nunca sale en la serialización de la configuración.**
La configuración que se publica trae qué ERP y qué empresas hay. Las
credenciales viven en otro archivo, en otro lugar, y nada que se publique las
referencia siquiera.

LA CLAVE MAESTRA
----------------
Vive en la variable de entorno `HOPDESK_SECRETS_KEY` (la misma que ya usa
HopDesk, para no multiplicar secretos que administrar), o en `.env` local. NUNCA
en el repositorio, y nunca en nada que se suba a la nube.
===============================================================================
"""
import os
import json
import base64
from typing import Dict, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VAR_CLAVE = 'HOPDESK_SECRETS_KEY'
_RENVIRON_HOPDESK = r'C:\Users\luisr\Antiguedad_App\.Renviron'


class SecretoNoDisponible(RuntimeError):
    """No se pudo obtener o descifrar un secreto.

    Que sea una excepción y no un valor por defecto es la decisión de diseño
    central de este archivo. Ver el encabezado.
    """


def _leer_clave_maestra() -> bytes:
    """Entorno del proceso → .Renviron de HopDesk → .env local.

    Se reutiliza la clave que ya administra HopDesk a propósito: dos claves
    maestras distintas para la misma organización significa el doble de
    superficie y el doble de probabilidad de que una se rote sin la otra.
    """
    val = os.environ.get(VAR_CLAVE, '').strip()
    if not val:
        for ruta in (_RENVIRON_HOPDESK,
                     os.path.join(os.path.dirname(os.path.dirname(
                         os.path.abspath(__file__))), '.env')):
            try:
                with open(ruta, encoding='utf-8') as f:
                    for linea in f:
                        if linea.strip().startswith(VAR_CLAVE):
                            val = linea.split('=', 1)[1].strip().strip('"\'')
                            break
            except (FileNotFoundError, IndexError):
                continue
            if val:
                break
    if not val:
        raise SecretoNoDisponible(
            f'No se encontró {VAR_CLAVE}. Sin clave maestra no se pueden leer '
            f'ni guardar credenciales de ERP. Se busca en el entorno del '
            f'proceso, en el .Renviron de HopDesk y en un .env local.')
    # La clave puede venir en base64 o como texto; en ambos casos se normaliza
    # a 32 bytes con la derivación, así que no se impone un formato al usuario.
    try:
        crudo = base64.b64decode(val, validate=True)
    except Exception:
        crudo = val.encode('utf-8')
    return crudo


def _clave_de_cliente(maestra: bytes, cliente_id: str) -> bytes:
    """Deriva la clave de UN cliente. El id va como `info`, que es lo que hace
    que dos clientes nunca compartan clave aunque compartan maestra."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=f'configuracion-erp:{cliente_id}'.encode('utf-8')
                ).derive(maestra)


class AlmacenSecretos:
    """Guarda y lee credenciales cifradas usando el mismo almacén de archivos.

    Va por el `Almacen` (local o S3) y no por su propio mecanismo, para que la
    escritura condicional y la protección contra lost-update también apliquen
    aquí. Un secreto perdido por una escritura pisada es tan grave como
    cualquier otro dato perdido, y más difícil de notar.
    """

    def __init__(self, almacen, cliente_id: str):
        self.almacen = almacen
        self.cliente_id = cliente_id
        self._clave = _clave_de_cliente(_leer_clave_maestra(), cliente_id)

    def _ruta(self, ref: str) -> str:
        return f'clientes/{self.cliente_id}/secretos/{ref}.json'

    def guardar(self, ref: str, secretos: Dict[str, str]) -> None:
        """Cifra y guarda. `secretos` es un diccionario plano: usuario,
        contraseña y lo que el conector declare necesitar."""
        if not isinstance(secretos, dict):
            raise ValueError('Los secretos deben ser un diccionario plano.')
        aes = AESGCM(self._clave)
        nonce = os.urandom(12)
        claro = json.dumps(secretos, ensure_ascii=False).encode('utf-8')
        # El id del cliente va como dato autenticado adicional: un blob copiado
        # de un cliente a otro NO descifra, aunque quien lo copie tenga acceso a
        # la clave maestra. Es la defensa concreta contra el cruce entre
        # inquilinos que el sistema anterior tenía abierto.
        cifrado = aes.encrypt(nonce, claro, self.cliente_id.encode('utf-8'))
        sobre = {'v': 1, 'alg': 'AES-256-GCM',
                 'nonce': base64.b64encode(nonce).decode(),
                 'datos': base64.b64encode(cifrado).decode()}
        ruta = self._ruta(ref)
        _, version = self.almacen.leer(ruta)
        self.almacen.escribir(ruta, sobre, version)

    def leer(self, ref: str) -> Dict[str, str]:
        sobre, _ = self.almacen.leer(self._ruta(ref))
        if sobre is None:
            raise SecretoNoDisponible(
                f'No hay credenciales guardadas en {ref!r} para este cliente. '
                f'Se capturan desde la configuración; no hay valor por defecto '
                f'ni credencial global a la que recurrir, a propósito.')
        try:
            aes = AESGCM(self._clave)
            claro = aes.decrypt(base64.b64decode(sobre['nonce']),
                                base64.b64decode(sobre['datos']),
                                self.cliente_id.encode('utf-8'))
        except Exception as e:
            # Aquí es donde el sistema anterior caía a las credenciales
            # globales. Aquí se detiene.
            raise SecretoNoDisponible(
                f'No se pudieron descifrar las credenciales de {ref!r}. Causas '
                f'posibles: la clave maestra cambió, el dato se corrompió, o el '
                f'blob pertenece a otro cliente. NO se recurre a ninguna '
                f'credencial alternativa: continuar podría conectar a este '
                f'cliente contra el ERP de otro.') from e
        return json.loads(claro.decode('utf-8'))

    def existe(self, ref: str) -> bool:
        datos, _ = self.almacen.leer(self._ruta(ref))
        return datos is not None

    def borrar(self, ref: str) -> None:
        ruta = self._ruta(ref)
        _, version = self.almacen.leer(ruta)
        if version is not None:
            self.almacen.escribir(ruta, {'v': 1, 'borrado': True}, version)
