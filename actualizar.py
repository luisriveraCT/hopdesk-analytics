# -*- coding: utf-8 -*-
"""
===============================================================================
 ACTUALIZAR — el único comando que hay que correr
===============================================================================
Corre en la máquina local, CON VPN. Baja lo nuevo del ERP, registra qué cambió
respecto a la corrida anterior, verifica que cuadre, y deja el tablero listo.

    cd "C:\\Users\\luisr\\Analitica_Financiera"
    python actualizar.py

Opciones:
    python actualizar.py --solo-erp        baja del ERP y para (no toca el tablero)
    python actualizar.py --solo-tablero    reconstruye el tablero con lo ya bajado
    python actualizar.py --sin-facturas    omite facturación (mucho más rápido)
    python actualizar.py --subir           además sube el snapshot a S3

POR QUÉ ES UN SOLO COMANDO Y NO SIETE PASOS SUELTOS
---------------------------------------------------
Porque el orden importa y hay dos puntos donde HAY QUE DETENERSE:

  · Si el cuadre contable falla, **no se publica**. Números que no cuadran
    cuestan mucho más que un tablero desactualizado un día.
  · Si aparece un secreto en el HTML, **no se publica**. Un secreto publicado no
    se despublica: hay que rotarlo, y hasta entonces está expuesto.

Dejar esos dos como pasos que alguien "debería acordarse de correr" es como no
tenerlos.

LA BITÁCORA
-----------
Entre bajar los datos y publicarlos, se compara esta extracción contra la
anterior y se registra qué periodos cambiaron. La contabilidad se corrige hacia
atrás —una póliza mal clasificada en marzo se arregla en agosto— y sin esto
nadie se entera de que el número que presentó ya no es el que el sistema
muestra. El registro se ve en el panel de Ajustes del tablero.
===============================================================================
"""
import os
import sys
import time
import argparse
import subprocess

AQUI = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
FINANZAS = os.path.join(AQUI, 'finanzas')
ERP = os.path.join(FINANZAS, 'erp')
TABLERO = os.path.join(AQUI, 'dashboard')


def paso(n, titulo):
    print(f'\n{"=" * 74}\n [{n}] {titulo}\n{"=" * 74}', flush=True)


def correr(script, args=None, cwd=None, detener_si_falla=True, titulo=''):
    """Corre un script y devuelve True si salió bien.

    `detener_si_falla=True` es el default a propósito: en un pipeline de datos,
    seguir después de un error produce un resultado que parece bueno y no lo es.
    """
    cmd = [PY, '-u', script] + (args or [])
    r = subprocess.run(cmd, cwd=cwd or AQUI)
    if r.returncode != 0:
        print(f'\n!! Falló: {titulo or script} (código {r.returncode})')
        if detener_si_falla:
            print('!! Se detiene aquí. No se publica nada a medias.')
            raise SystemExit(r.returncode)
        return False
    return True


PUERTO_LOCAL = 1913        # 1912 lo usa HopDesk; se evita el choque a propósito


def ver_local():
    """Construye el tablero apuntando a los datos de esta máquina y lo sirve.

    HACEN FALTA LAS DOS COSAS, no solo abrir el archivo:

    · **Reconstruir en modo local.** El index.html que se publica apunta a S3.
      Abrirlo aquí mostraría las filas que estén en el bucket —la generación
      anterior— junto al diccionario recién generado. No truena: mezcla, que es
      peor, porque se ve bien.

    · **Un servidor, no doble clic.** Con `file://` el navegador bloquea la
      lectura de los archivos de `data/` por seguridad, y el tablero se queda
      cargando para siempre sin decir por qué.
    """
    import http.server
    import socketserver
    import threading
    import webbrowser

    paso(1, 'Construir el tablero para verlo en esta máquina')
    correr(os.path.join(TABLERO, 'construir.py'), ['--modo', 'local'],
           cwd=TABLERO, titulo='construcción en modo local')

    os.chdir(TABLERO)
    manejador = http.server.SimpleHTTPRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(('127.0.0.1', PUERTO_LOCAL), manejador) as srv:
        url = f'http://127.0.0.1:{PUERTO_LOCAL}/index.html'
        print(f'\n{"=" * 74}')
        print(f' Tablero disponible en:  {url}')
        print(' Ctrl+C para detener el servidor.')
        print(f'{"=" * 74}\n')
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print('\nServidor detenido.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--solo-erp', action='store_true')
    ap.add_argument('--solo-tablero', action='store_true')
    ap.add_argument('--sin-facturas', action='store_true')
    ap.add_argument('--subir', action='store_true')
    ap.add_argument('--ver', action='store_true',
                    help='construye para esta máquina, levanta un servidor '
                         'local y abre el navegador')
    ap.add_argument('--desde', type=int, default=2020)
    args = ap.parse_args()

    if args.ver:
        ver_local()
        return

    t0 = time.time()
    print('ACTUALIZACIÓN DE DATOS')
    print(f'  carpeta: {AQUI}')
    print('  requiere VPN conectada: el ERP vive en una IP privada.')

    if not args.solo_tablero:
        paso(1, 'Estados financieros desde el ERP (reanudable)')
        correr(os.path.join(ERP, 'extraer_estados_financieros.py'),
               ['--todas', '--desde', str(args.desde)], cwd=ERP,
               titulo='extracción de estados financieros')

        if not args.sin_facturas:
            paso(2, 'Facturación desde el ERP (ventas y compras)')
            correr(os.path.join(ERP, 'extraer_facturacion.py'), ['--todas'],
                   cwd=ERP, titulo='extracción de facturación')

        paso(3, 'Bitácora — qué cambió respecto a la corrida anterior')
        # No detiene el pipeline: un cambio retroactivo es información, no un
        # error. Lo que importa es que quede registrado y visible.
        correr(os.path.join(FINANZAS, 'bitacora_actualizaciones.py'), [],
               cwd=FINANZAS, detener_si_falla=False, titulo='bitácora')

        paso(4, 'Verificación de cuadre contable  ← PUNTO DE PARO')
        correr(os.path.join(FINANZAS, 'verificar_cuadre.py'), [], cwd=FINANZAS,
               titulo='verificación de cuadre')

    if args.solo_erp:
        print(f'\nListo (solo ERP) en {time.time() - t0:.0f}s.')
        return

    paso(5, 'Publicar la configuración del cliente (sin secretos)')
    correr(os.path.join(FINANZAS, 'configuracion', 'configurar.py'),
           ['--publicar'], cwd=os.path.join(FINANZAS, 'configuracion'),
           detener_si_falla=False, titulo='publicación de configuración')

    paso(6, 'Preparar los datos de facturación del tablero')
    # Desde el 2026-09-25 lee `datos_erp/facturas_*.json`, no el Excel. Si falla
    # se avisa y se sigue: quien solo quiera actualizar los estados financieros
    # no debe quedarse sin tablero por esto.
    if not correr(os.path.join(TABLERO, 'exportar_dashboard.py'), [], cwd=TABLERO,
                  detener_si_falla=False, titulo='exportación de facturación'):
        print('   (el tablero conserva los datos de la corrida anterior)')

    paso(7, 'Preparar los estados financieros')
    correr(os.path.join(TABLERO, 'exportar_finanzas.py'), [], cwd=TABLERO,
           detener_si_falla=False, titulo='exportación de estados financieros')

    # Va DESPUÉS de los estados financieros y no puede ir antes: el consolidado
    # de los indicadores se construye leyendo finanzas.json, justamente para que
    # las dos pantallas no puedan mostrar números distintos del mismo grupo.
    paso(8, 'Calcular los indicadores (Dirección y Tablero de Finanzas)')
    correr(os.path.join(TABLERO, 'exportar_kpis.py'), [], cwd=TABLERO,
           detener_si_falla=False, titulo='cálculo de indicadores')

    # La hoja de captura y la bitácora. Va antes de construir porque su
    # archivo se incrusta en el HTML.
    paso(9, 'Hoja de captura y bitácora de cambios')
    correr(os.path.join(TABLERO, 'exportar_entradas.py'), [], cwd=TABLERO,
           detener_si_falla=False, titulo='hoja de captura')

    paso(10, 'Construir el tablero')
    correr(os.path.join(TABLERO, 'construir.py'), [], cwd=TABLERO,
           titulo='construcción del tablero')

    paso(11, 'Sintaxis del tablero')
    correr(os.path.join(TABLERO, 'verificar_sintaxis.py'), ['index.html'],
           cwd=TABLERO, titulo='verificación de sintaxis')

    # Los dos que siguen atrapan fallas que NO se ven revisando la pantalla:
    # un bloque de código que quedó dentro de otra función deja su sección en
    # blanco sin error visible, y una clave de texto sin traducir solo se nota
    # al abrir el tablero en el otro idioma.
    paso(12, 'Alcance del código del tablero')
    correr(os.path.join(TABLERO, 'verificar_alcance.py'),
           ['index.html', 'DASHBOARD DE DIRECCIÓN Y TABLERO DE INDICADORES'],
           cwd=TABLERO, detener_si_falla=False, titulo='verificación de alcance')

    paso(13, 'Textos completos en todos los idiomas')
    correr(os.path.join(TABLERO, 'verificar_idiomas.py'), ['plantilla.html'],
           cwd=TABLERO, detener_si_falla=False, titulo='verificación de idiomas')

    # Existía y no lo llamaba nadie. Un verificador que no corre no verifica:
    # el modo de montos es justo donde un descuido no se ve —la pantalla
    # oculta la cifra y el archivo descargado la lleva dentro.
    paso(14, 'El modo de montos oculta lo que debe, y solo eso')
    correr(os.path.join(TABLERO, 'verificar_modo_discreto.py'), ['plantilla.html'],
           cwd=TABLERO, detener_si_falla=False, titulo='verificación del modo de montos')

    # El guardado falla mudo cuando se rompe: el botón se queda cargando y no
    # hay error en ningún lado. Esto comprueba que las tres piezas —lo que la
    # página manda, lo que el servidor escucha y lo que la página oye de
    # vuelta— sigan coincidiendo.
    paso(15, 'El botón de guardar puede hablar con el servidor')
    correr(os.path.join(TABLERO, 'verificar_guardado.py'), ['index.html'],
           cwd=TABLERO, detener_si_falla=False, titulo='verificación del guardado')

    paso(16, 'Que no se publique ningún secreto  ← PUNTO DE PARO')
    correr(os.path.join(TABLERO, 'verificar_publicacion.py'), ['index.html'],
           cwd=TABLERO, titulo='verificación de secretos')

    # El tablero al almacén privado, para que lo lea la aplicación de Connect.
    # Va aquí y no en el paso de publicación porque no depende de --subir: la
    # aplicación tiene que ver el tablero nuevo aunque no se toque S3 público.
    paso(17, 'Publicar el tablero para la aplicación')
    correr(os.path.join(TABLERO, 'publicar_tablero.py'), [], cwd=TABLERO,
           detener_si_falla=False, titulo='publicación del tablero')

    if args.subir:
        # Llamaba a refrescar.py cuando refrescar.py estaba en legacy/, y con
        # una bandera que aquella versión no tenía. La subida llevaba tiempo
        # fallando sin que nadie lo notara, porque el paso no detiene la
        # corrida. Ahora existen las dos cosas y se prueba con --simular.
        paso(18, 'Publicar en línea (datos a S3 y HTML a Connect)')
        correr(os.path.join(AQUI, 'refrescar.py'), [], cwd=AQUI,
               detener_si_falla=False, titulo='publicación en línea')

    print(f'\n{"=" * 74}')
    print(f' LISTO en {time.time() - t0:.0f}s')
    print(f' Tablero: {os.path.join(TABLERO, "index.html")}')
    print(f'{"=" * 74}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
