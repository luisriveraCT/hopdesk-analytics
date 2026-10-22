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

    · **La aplicación, no un servidor de archivos.** Se arranca la MISMA app de
      servidor/app.py que corre en Connect, en modo local: sirve lo recién
      construido y GUARDA. Antes esto levantaba un servidor de archivos
      estático, y una página estática no puede escribir en el almacén: la hoja
      de captura caía a "Exportar cambios" y las metas no se podían fijar.
      Lo que se guarda va al almacén de almacen.json —el de producción—: ver en
      local es la misma app en otra máquina, no un entorno de pruebas.
    """
    import threading
    import webbrowser

    paso(1, 'Construir el tablero para verlo en esta máquina')
    correr(os.path.join(TABLERO, 'construir.py'), ['--modo', 'local'],
           cwd=TABLERO, titulo='construcción en modo local')

    url = f'http://127.0.0.1:{PUERTO_LOCAL}/'
    print(f'\n{"=" * 74}')
    print(f' Tablero disponible en:  {url}')
    print(' Guarda de verdad en el almacén. Ctrl+C para detener.')
    print(f'{"=" * 74}\n', flush=True)
    threading.Timer(3.0, lambda: webbrowser.open(url)).start()
    entorno = dict(os.environ, ANALITICA_TABLERO_LOCAL='1')
    try:
        subprocess.run([PY, '-m', 'shiny', 'run', '--host', '127.0.0.1',
                        '--port', str(PUERTO_LOCAL),
                        os.path.join(AQUI, 'servidor', 'app.py')],
                       cwd=AQUI, env=entorno)
    except KeyboardInterrupt:
        print('\nServidor detenido.')


def decir_almacen():
    """Qué almacén se va a usar, dicho antes de tocar nada.

    Va aquí y no solo en los comandos de configuración porque estos dos son los
    que recalculan y publican. Correr contra el disco creyendo que se corre
    contra el bucket recalcula sin las entradas capturadas y publica el
    resultado, y nada en la salida lo delata — solo lo nota, semanas después,
    quien busca una cifra que capturó.
    """
    import sys as _sys
    _sys.path.insert(0, os.path.join(AQUI, 'finanzas'))
    _sys.path.insert(0, os.path.join(AQUI, 'finanzas', 'configuracion'))
    try:
        import repositorio as repo
        # flush: los pasos siguientes lanzan subprocesos que escriben
        # directo a la terminal, y sin esto el aviso sale DESPUÉS de lo
        # que avisa — que es igual que no avisar.
        print(f'  almacén: {repo.descripcion_almacen()}', flush=True)
    except Exception as e:                                   # noqa: BLE001
        print(f'  almacén: NO SE PUDO DETERMINAR ({e})', flush=True)
        raise


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

    decir_almacen()

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

    paso(6, 'Preparar los datos de facturación del tablero (ventas y compras)')
    # Lee `datos_erp/facturas_*.json`. Si falla se avisa y se sigue: quien solo
    # quiera actualizar los estados financieros no debe quedarse sin tablero
    # por esto.
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

    # Más de veinte mil comprobaciones sobre los datos recién calculados: que
    # el balance cuadre en las cinco empresas y los ochenta y un periodos, que
    # los rubros sumen el activo, que consolidar no cree utilidad, que ningún
    # plazo salga negativo, que las dos pestañas digan lo mismo.
    #
    # Vivían en una batería de pruebas que nadie corría. No comprueban el
    # código —eso se comprueba una vez— sino el DATO de esta corrida, que es
    # distinto cada vez. Por eso van aquí: después de calcularlo y antes de
    # construir el tablero con él.
    #
    # No detienen la corrida, a diferencia del cuadre contable del paso 4: ése
    # comprueba una identidad que no admite excepción, y éstas abarcan
    # relaciones donde un caso raro legítimo es concebible. Si se quiere que
    # detengan, es cambiar detener_si_falla a True.
    paso(9, 'Comprobar los datos calculados')
    correr(os.path.join(AQUI, 'finanzas', 'verificar_datos.py'), [], cwd=AQUI,
           detener_si_falla=False, titulo='comprobación de los datos')

    # La hoja de captura y la bitácora. Va antes de construir porque su
    # archivo se incrusta en el HTML.
    paso(10, 'Hoja de captura y bitácora de cambios')
    correr(os.path.join(TABLERO, 'exportar_entradas.py'), [], cwd=TABLERO,
           detener_si_falla=False, titulo='hoja de captura')

    paso(11, 'Construir el tablero')
    correr(os.path.join(TABLERO, 'construir.py'), [], cwd=TABLERO,
           titulo='construcción del tablero')

    paso(12, 'Sintaxis del tablero')
    correr(os.path.join(TABLERO, 'verificar_sintaxis.py'), ['index.html'],
           cwd=TABLERO, titulo='verificación de sintaxis')

    # Los dos que siguen atrapan fallas que NO se ven revisando la pantalla:
    # un bloque de código que quedó dentro de otra función deja su sección en
    # blanco sin error visible, y una clave de texto sin traducir solo se nota
    # al abrir el tablero en el otro idioma.
    paso(13, 'Alcance del código del tablero')
    correr(os.path.join(TABLERO, 'verificar_alcance.py'),
           ['index.html', 'DASHBOARD DE DIRECCIÓN Y TABLERO DE INDICADORES'],
           cwd=TABLERO, detener_si_falla=False, titulo='verificación de alcance')

    paso(14, 'Textos completos en todos los idiomas')
    correr(os.path.join(TABLERO, 'verificar_idiomas.py'), ['plantilla.html'],
           cwd=TABLERO, detener_si_falla=False, titulo='verificación de idiomas')

    # Existía y no lo llamaba nadie. Un verificador que no corre no verifica:
    # el modo de montos es justo donde un descuido no se ve —la pantalla
    # oculta la cifra y el archivo descargado la lleva dentro.
    paso(15, 'El modo de montos oculta lo que debe, y solo eso')
    correr(os.path.join(TABLERO, 'verificar_modo_discreto.py'), ['plantilla.html'],
           cwd=TABLERO, detener_si_falla=False, titulo='verificación del modo de montos')

    # El guardado falla mudo cuando se rompe: el botón se queda cargando y no
    # hay error en ningún lado. Esto comprueba que las tres piezas —lo que la
    # página manda, lo que el servidor escucha y lo que la página oye de
    # vuelta— sigan coincidiendo.
    # Una capacidad que desaparece no rompe nada que se vea: se borra una
    # función que "ya nadie usaba" y la pantalla sigue bien, solo le falta algo.
    # CAPACIDADES.md dice qué sabe hacer la app y con qué piezas; esto comprueba
    # que las piezas sigan ahí.
    paso('15b', 'Ninguna capacidad de la app se perdió')
    correr(os.path.join(TABLERO, 'verificar_capacidades.py'), [], cwd=TABLERO,
           detener_si_falla=False, titulo='verificación de capacidades')

    paso(16, 'El botón de guardar puede hablar con el servidor')
    correr(os.path.join(TABLERO, 'verificar_guardado.py'), ['index.html'],
           cwd=TABLERO, detener_si_falla=False, titulo='verificación del guardado')

    paso(17, 'Que no se publique ningún secreto  ← PUNTO DE PARO')
    correr(os.path.join(TABLERO, 'verificar_publicacion.py'), ['index.html'],
           cwd=TABLERO, titulo='verificación de secretos')

    # El tablero al almacén privado, para que lo lea la aplicación de Connect.
    # Va aquí y no en el paso de publicación porque no depende de --subir: la
    # aplicación tiene que ver el tablero nuevo aunque no se toque S3 público.
    paso(18, 'Publicar el tablero para la aplicación')
    correr(os.path.join(TABLERO, 'publicar_tablero.py'), [], cwd=TABLERO,
           detener_si_falla=False, titulo='publicación del tablero')

    if args.subir:
        # Llamaba a refrescar.py cuando refrescar.py estaba en otra carpeta, y
        # con una bandera que aquella versión no tenía. La subida llevaba tiempo
        # fallando sin que nadie lo notara, porque el paso no detiene la
        # corrida. Ahora existen las dos cosas y se prueba con --simular.
        # SOLO los datos de facturación al bucket público. El HTML ya NO se
        # redespliega a Connect: desde que el tablero vive dentro de la
        # aplicación de `servidor/`, hacerlo dejaría una copia estática vieja
        # conviviendo con la app, y sin nada que indicara cuál es cuál.
        #
        # Los trozos de facturación sí siguen yendo al bucket público: el
        # navegador los pide por URL, esté la página servida por la aplicación
        # o suelta.
        paso(19, 'Publicar los datos de facturación en el bucket público')
        correr(os.path.join(AQUI, 'refrescar.py'), ['--solo-subir'], cwd=AQUI,
               detener_si_falla=False, titulo='publicación de datos')

    print(f'\n{"=" * 74}')
    print(f' LISTO en {time.time() - t0:.0f}s')
    print(f' Tablero: {os.path.join(TABLERO, "index.html")}')
    print(f'{"=" * 74}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
