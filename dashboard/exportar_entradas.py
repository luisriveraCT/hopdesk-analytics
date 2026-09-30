# -*- coding: utf-8 -*-
"""
===============================================================================
 PREPARA LA HOJA DE CAPTURA Y LA BITÁCORA PARA EL TABLERO
===============================================================================
Produce `entradas.json`: el catálogo de lo que se puede capturar, lo que ya está
capturado, y la bitácora de cambios.

QUÉ SE PUBLICA Y QUÉ NO
-----------------------
Se publica el catálogo completo, las entradas y la bitácora. No hay secretos
aquí —son cifras de negocio y nombres de quienes las capturaron— pero sí hay una
decisión: **la bitácora se publica recortada**.

Se envían los últimos asientos, no los de tres años. El archivo viaja incrustado
en el HTML y crece sin límite; una bitácora completa terminaría pesando más que
todo lo demás junto para que nadie desplace hasta el final. La completa se
consulta con `python finanzas/entradas.py --bitacora --todo`, que lee el
original sin recortes.

POR QUÉ EL CATÁLOGO VIAJA EN LOS DATOS
--------------------------------------
Para que la hoja de captura no tenga su propia lista de campos. Es la misma
razón por la que el catálogo de indicadores viaja: dos listas paralelas se
separan, y el día que alguien agregue un campo capturable sin tocar la pantalla,
el campo queda existiendo y sin forma de capturarlo.
===============================================================================
"""
import os
import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(AQUI)
FINANZAS = os.path.join(BASE, 'finanzas')

sys.path.insert(0, FINANZAS)
sys.path.insert(0, os.path.join(FINANZAS, 'configuracion'))

import entradas_manuales as em          # noqa: E402
import bitacora_cambios as bc           # noqa: E402

# Cuántos asientos de bitácora se incrustan. Suficientes para ver el trabajo
# reciente del equipo sin que el archivo crezca sin control.
ASIENTOS_PUBLICADOS = 400


def main():
    import repositorio as repo
    almacen = repo.almacen_por_defecto()
    cliente = repo.cliente_actual(almacen)

    entradas = em.cargar(almacen, cliente)
    asientos = bc.leer(almacen, cliente, ASIENTOS_PUBLICADOS)
    resumen = bc.resumen(almacen, cliente)

    salida = {
        'cliente': cliente.nombre,
        'comodin': em.COMODIN,
        'campos': em.CAMPOS,
        'grupos': [{'id': g, 'nombre': n, 'desc': d} for g, n, d in em.GRUPOS],
        'tipos': {'suministro': em.SUMINISTRO, 'sobrescritura': em.SOBRESCRITURA},
        'entradas': entradas.entradas,
        'actualizado': entradas.actualizado,
        'empresas': [e.iniciales for e in cliente.empresas if e.activa],
        'bitacora': asientos,
        'bitacora_resumen': resumen,
        'bitacora_actos': bc.ACTOS,
        'bitacora_truncada': resumen['total'] > len(asientos),
    }

    ruta = os.path.join(AQUI, 'entradas.json')
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, separators=(',', ':'))
    n_sob = len(entradas.sobrescrituras())
    print(f'entradas.json: {os.path.getsize(ruta) / 1024:.0f} KB · '
          f'{len(entradas.entradas)} entrada(s) ({n_sob} sobrescritura(s)) · '
          f'{len(asientos)} de {resumen["total"]} asiento(s) de bitácora')
    if n_sob:
        print(f'  AVISO: hay {n_sob} cifra(s) calculada(s) reemplazada(s) a mano. '
              f'Salen resaltadas en el tablero.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
