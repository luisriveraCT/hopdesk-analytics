# -*- coding: utf-8 -*-
"""
===============================================================================
 BITÁCORA DE CAMBIOS — quién tocó qué, cuándo y por qué
===============================================================================
Registro de todo lo que una persona hace sobre las cifras: capturas, cambios,
borrados, desbloqueos de campos calculados, aplicaciones de un lote de cambios
y consultas de la propia bitácora.

QUÉ LA DISTINGUE DE `bitacora_actualizaciones.py`
-------------------------------------------------
Son dos registros distintos y conviene no mezclarlos:

  · `bitacora_actualizaciones.py` — qué cambió en los DATOS entre una
    extracción del ERP y la siguiente. Contesta "¿se modificó un periodo
    anterior?". El sujeto es el ERP.
  · Este archivo — qué hizo una PERSONA. Contesta "¿quién puso este número y
    por qué?". El sujeto es alguien del equipo.

Un número que no cuadra puede venir de cualquiera de los dos lados, y buscarlo
en el registro equivocado cuesta horas.

SOLO SE AGREGA, NUNCA SE MODIFICA
----------------------------------
Cada asiento se escribe una vez y no se toca más. Corregir un asiento
equivocado se hace escribiendo otro, igual que en contabilidad. Una bitácora
que se puede editar no sirve para lo único que sirve una bitácora.

Tampoco se borra sola. Crece, y crecer es lo correcto: una bitácora con
caducidad silenciosa caduca justo el registro que alguien iba a buscar. Si
algún día estorba por tamaño, se archiva a un archivo por año — se mueve, no se
descarta.

POR QUÉ SE REGISTRAN TAMBIÉN LAS CONSULTAS
-------------------------------------------
Porque el equipo pidió saber "todos todos los cambios y las consultas". Ver
quién revisó la bitácora y cuándo es parte de una auditoría: si alguien
capturó una cifra rara y tres personas la revisaron sin decir nada, eso es un
dato sobre el proceso, no sobre el número.

DÓNDE VIVE
----------
`clientes/<id>/bitacora_cambios.json`, con la misma escritura atómica que la
configuración: se lee con su versión, se agrega el asiento y se escribe solo si
la versión no cambió mientras tanto. Si cambió, se reintenta sobre lo nuevo.

Dos personas capturando a la vez es el caso normal, no el raro. Sin esa
comprobación, la segunda en guardar borraría los asientos de la primera — y una
bitácora que pierde asientos no sirve para lo único que sirve una bitácora.
===============================================================================
"""
import os
import sys
import json
import datetime as dt
from typing import Dict, List, Optional

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, 'configuracion'))

RUTA_BITACORA = 'bitacora_cambios.json'

# Los actos que se registran. Cada uno lleva cómo se lee en pantalla, para que
# la bitácora no muestre nombres internos a quien la consulta.
ACTOS = {
    'captura':     'Capturó un valor',
    'cambio':      'Cambió un valor',
    'borrado':     'Borró un valor (vuelve al cálculo automático)',
    'desbloqueo':  'Desbloqueó un campo calculado para editarlo',
    'bloqueo':     'Volvió a bloquear los campos calculados',
    'aplicacion':  'Aplicó un lote de cambios',
    'consulta':    'Consultó la bitácora',
    'exportacion': 'Exportó la hoja de captura',
}


class ActoDesconocido(ValueError):
    """Se intentó registrar un acto que no está declarado."""


def _ahora() -> str:
    return dt.datetime.now().isoformat(timespec='seconds')


def _ruta(cliente) -> str:
    return f'{cliente.prefijo_s3()}/{RUTA_BITACORA}'


def asiento(acto: str, autor: str, detalle: Optional[Dict] = None,
            origen: str = 'cli') -> Dict:
    """Arma un asiento. No lo escribe — eso lo hace `registrar`."""
    if acto not in ACTOS:
        raise ActoDesconocido(
            f'Acto desconocido: {acto!r}. Los declarados son: '
            f'{", ".join(sorted(ACTOS))}. Un acto sin declarar se registraría '
            f'con un nombre que nadie sabe leer después.')
    return {
        'fecha': _ahora(),
        'acto': acto,
        # Sin autor el registro no sirve para nada, así que se dice cuando
        # falta en vez de guardar una cadena vacía que parece un dato.
        'autor': (autor or '').strip() or '(sin identificar)',
        'origen': origen,          # 'cli', 'tablero', 'automatico'
        'detalle': detalle or {},
    }


def registrar(almacen, cliente, acto: str, autor: str,
              detalle: Optional[Dict] = None, origen: str = 'cli') -> Dict:
    """Agrega un asiento al final. Nunca reescribe lo anterior."""
    from almacen import actualizar_con_reintento
    a = asiento(acto, autor, detalle, origen)

    # El reintento importa aquí más que en ningún otro archivo: el asiento se
    # AGREGA a lo que haya en el momento de escribir, no a lo que había cuando
    # se leyó. Construir la lista fuera de esta función y escribirla entera
    # borraría los asientos que otra persona agregó entre medias.
    def agregar(actual):
        datos = dict(actual or {})
        asientos = list(datos.get('asientos') or [])
        asientos.append(a)
        return {'asientos': asientos}

    actualizar_con_reintento(almacen, _ruta(cliente), agregar)
    return a


def leer(almacen, cliente, limite: Optional[int] = None,
         acto: Optional[str] = None, autor: Optional[str] = None) -> List[Dict]:
    """Los asientos, del más reciente al más viejo."""
    datos, _ = almacen.leer(_ruta(cliente))
    asientos = list((datos or {}).get('asientos') or [])
    if acto:
        asientos = [a for a in asientos if a.get('acto') == acto]
    if autor:
        a_norm = autor.strip().lower()
        asientos = [a for a in asientos
                    if a_norm in (a.get('autor') or '').lower()]
    asientos.sort(key=lambda a: a.get('fecha') or '', reverse=True)
    return asientos[:limite] if limite else asientos


def resumen(almacen, cliente) -> Dict:
    """Cifras de cabecera para mostrar sin abrir la bitácora entera."""
    asientos = leer(almacen, cliente)
    por_acto: Dict[str, int] = {}
    por_autor: Dict[str, int] = {}
    for a in asientos:
        por_acto[a['acto']] = por_acto.get(a['acto'], 0) + 1
        por_autor[a['autor']] = por_autor.get(a['autor'], 0) + 1
    return {
        'total': len(asientos),
        'ultimo': asientos[0]['fecha'] if asientos else None,
        'por_acto': por_acto,
        'por_autor': por_autor,
    }


def describir(a: Dict) -> str:
    """Un asiento en una línea legible, para la pantalla y para la consola."""
    d = a.get('detalle') or {}
    partes = [a.get('fecha', ''), ACTOS.get(a.get('acto'), a.get('acto', '')),
              f"· {a.get('autor')}"]
    if d.get('campo'):
        ambito = f"{d.get('empresa', '*')}/{d.get('periodo', '*')}"
        partes.append(f"· {d['campo']} [{ambito}]")
    if d.get('de') is not None or d.get('a') is not None:
        partes.append(f"· {d.get('de')} → {d.get('a')}")
    if d.get('motivo'):
        partes.append(f"· {d['motivo']}")
    if d.get('n'):
        partes.append(f"· {d['n']} cambio(s)")
    return '  '.join(str(p) for p in partes if p)
