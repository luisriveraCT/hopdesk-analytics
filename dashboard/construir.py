# -*- coding: utf-8 -*-
"""Inyecta meta.json y el índice de chunks en plantilla.html -> index.html.
Vive en ...\\Analitica_Financiera\\dashboard\\, normalmente llamado por
refrescar.py un nivel arriba.

============================================================================
 ARQUITECTURA DE DATOS: OPCIÓN A (activa) vs OPCIÓN B (diseñada, no activa)
============================================================================
meta.json (chico, ~40 KB) SIEMPRE se incrusta dentro de index.html, en las
dos opciones — así el primer render es instantáneo sin depender de red.
Lo que cambia entre A y B es de dónde se leen los chunks pesados
(data/rows-<año>.json, ~7.5 MB en total), es decir, el arreglo CHUNKS que
también queda incrustado en el HTML.

OPCIÓN A — activa hoy (MODO_DATOS = 'local'):
  Los chunks se publican junto con el HTML (como archivos del propio
  Artifact/deploy) y CHUNKS los referencia con rutas relativas ("data/rows-
  2024.json"). Cuando se suban a un bucket S3 de lectura pública (sin
  ListBucket), el único cambio es apuntar esas mismas rutas a la URL
  pública del bucket (MODO_DATOS = 's3', llenar S3_BASE_URL abajo) — nada
  más cambia, ni en este script ni en index.html.

OPCIÓN B — diseñada, NO implementar código real todavía (privacidad real):
  El bucket se vuelve privado. En vez de una URL pública fija por archivo,
  cada entrada de CHUNKS necesita una URL PRE-FIRMADA (presigned) con
  expiración, generada por refrescar.py en el momento de subir cada
  refresco de datos a S3 (usando boto3
  `s3_client.generate_presigned_url('get_object', ...)`, con Expiration de
  unas 2-3 semanas ya que el refresco es semanal). Ese cambio ocurre
  ÚNICAMENTE en refrescar.py (que pasaría el diccionario de URLs firmadas a
  este script en vez de que este script arme rutas locales/públicas) — la
  función construir_html() de abajo seguiría recibiendo simplemente "una
  URL por archivo", sin saber ni importarle si es relativa, pública o
  firmada. Por eso NO hay que tocar la firma de construir_html() para
  activar B más adelante, solo lo que le pasa refrescar.py.
  Además, en Opción B el contenido en Connect Cloud debe quedar restringido
  a los usuarios de la organización (se configura en Connect Cloud, no en
  código).
============================================================================
"""
import os, json, sys
sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))

MODO_DATOS = 's3'  # 'local' (solo para pruebas sin bucket) | 's3' (Opción A vía S3, activo)
S3_BASE_URL = 'https://hopdesk-analytics-dashboard.s3.us-east-1.amazonaws.com/data'


BITACORA_PATH = os.path.join(os.path.dirname(HERE), 'finanzas', 'datos_erp', 'bitacora.jsonl')
MAX_EVENTOS_BITACORA = 400


def leer_bitacora():
    """Los eventos de la bitácora, para el panel de Ajustes.

    Se incrusta en el HTML (no se sirve aparte) porque son pocos kilobytes y
    así el panel abre al instante y sigue funcionando sin red — igual que
    meta.json. Se recortan a los más recientes: la bitácora crece para siempre,
    y un día alguien descubriría que el index.html pesa 40 MB por un registro
    de auditoría que nadie lee completo en pantalla. El archivo .jsonl conserva
    la historia entera; esto es solo la ventana visible.

    Si el archivo no existe todavía, devuelve una lista vacía: el panel ya
    tiene un estado vacío que explica por qué. Fallar aquí dejaría sin tablero
    a quien solo quiere ver facturación."""
    try:
        with open(BITACORA_PATH, encoding='utf-8') as f:
            evs = [json.loads(l) for l in f if l.strip()]
        return evs[-MAX_EVENTOS_BITACORA:]
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f'  aviso: no se pudo leer la bitácora ({e}); el panel abrirá vacío')
        return []


CONFIG_DIR = os.path.join(os.path.dirname(HERE), 'finanzas', 'datos_config', 'clientes')


def leer_config_publica():
    """La configuración del cliente SIN secretos, para el panel de Ajustes.

    La produce `finanzas/configuracion/configurar.py --publicar`, que la arma por
    lista blanca: nombra lo que sale en vez de quitar lo que no debe salir. Esa
    diferencia es la que garantiza que un campo sensible agregado mañana al
    modelo quede fuera por omisión.

    Aquí NO se filtra nada: si este archivo tuviera que limpiar el dato, habría
    dos lugares decidiendo qué es secreto y tarde o temprano discreparían.
    """
    if not os.path.isdir(CONFIG_DIR):
        return {}
    for cid in sorted(os.listdir(CONFIG_DIR)):
        ruta = os.path.join(CONFIG_DIR, cid, 'configuracion_publica.json')
        if os.path.exists(ruta):
            try:
                with open(ruta, encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f'  aviso: no se pudo leer la configuración ({e})')
    return {}



def _leer_json_crudo(nombre, aviso):
    """Devuelve la cadena JSON tal cual, sin volver a serializar: el archivo ya
    está compacto y re-serializarlo solo gastaría tiempo. Si no existe, se
    devuelve un objeto vacío y la pestaña muestra su propio mensaje — el
    tablero de facturación no debe dejar de construirse porque falte esto.
    """
    try:
        with open(os.path.join(HERE, nombre), encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f'  aviso: {aviso}')
        return '{}'


def leer_finanzas():
    """Los estados financieros para su pestaña."""
    return _leer_json_crudo(
        'finanzas.json',
        'no hay finanzas.json; la pestaña de Estados Financieros abrirá '
        'vacía. Genera con: python exportar_finanzas.py')


def leer_entradas():
    """La hoja de captura: catálogo, lo capturado y la bitácora."""
    return _leer_json_crudo(
        'entradas.json',
        'no hay entradas.json; la hoja de captura abrirá vacía. '
        'Genera con: python exportar_entradas.py')


def leer_kpis():
    """Los indicadores para el Dashboard de Dirección y el Tablero de Finanzas."""
    return _leer_json_crudo(
        'kpis.json',
        'no hay kpis.json; las pestañas de Dirección y Finanzas abrirán '
        'vacías. Genera con: python exportar_kpis.py')


def construir_html(chunk_urls, out_path=None):
    """chunk_urls: lista de dicts {'archivo': <url o ruta>, 'n': <filas>}.
    No le importa si 'archivo' es una ruta relativa, una URL pública de S3 o
    (a futuro, Opción B) una URL pre-firmada — ese detalle lo decide quien
    llama a esta función, no esta función."""
    with open(os.path.join(HERE, 'plantilla.html'), encoding='utf-8') as f:
        html = f.read()
    with open(os.path.join(HERE, 'meta.json'), encoding='utf-8') as f:
        meta = f.read()
    html = html.replace('__META_JSON__', meta)
    html = html.replace('__CHUNKS_JSON__', json.dumps(chunk_urls, ensure_ascii=False))
    html = html.replace('__BITACORA_JSON__', json.dumps(leer_bitacora(), ensure_ascii=False))
    html = html.replace('__CONFIG_JSON__', json.dumps(leer_config_publica(), ensure_ascii=False))
    html = html.replace('__FINANZAS_JSON__', leer_finanzas())
    html = html.replace('__KPIS_JSON__', leer_kpis())
    html = html.replace('__ENTRADAS_JSON__', leer_entradas())
    out_path = out_path or os.path.join(HERE, 'index.html')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print('index.html:', round(os.path.getsize(out_path) / 1024, 1), 'KB')
    print('chunks:', len(chunk_urls), 'filas:', sum(c['n'] for c in chunk_urls))
    return out_path


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--modo', choices=('local', 's3'), default=MODO_DATOS,
                    help="de dónde lee el tablero los datos pesados. "
                         "'local' para verlo en esta máquina; 's3' para publicar.")
    args = ap.parse_args()

    with open(os.path.join(HERE, 'indice.json'), encoding='utf-8') as f:
        idx = json.load(f)

    if args.modo == 'local':
        chunks = [{'archivo': 'data/' + c['archivo'], 'n': c['n']} for c in idx]
    else:
        chunks = [{'archivo': f'{S3_BASE_URL}/{c["archivo"]}', 'n': c['n']} for c in idx]
        # Aviso, no error: construir en modo s3 es correcto y necesario para
        # publicar. Lo que no es correcto es ABRIR ese archivo aquí esperando
        # ver los datos recién extraídos — los leería del bucket, que tiene la
        # generación anterior hasta que alguien suba la nueva. El diccionario
        # incrustado sería el nuevo y las filas las viejas: una mezcla que no
        # falla, solo miente.
        print('AVISO: modo s3 — este index.html lee los datos del bucket, no de')
        print('       data/. Para ver lo recién extraído en esta máquina usa:')
        print('           python ..\\actualizar.py --ver')

    construir_html(chunks)
    print(f'modo: {args.modo}')


if __name__ == '__main__':
    main()
