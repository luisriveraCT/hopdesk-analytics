# -*- coding: utf-8 -*-
"""
===============================================================================
 QUE NO SE SUBA NINGÚN DATO DEL NEGOCIO AL REPOSITORIO
===============================================================================
Revisa lo que Git enviaría y se detiene si encuentra cifras reales,
credenciales o archivos que solo deberían vivir en S3.

POR QUÉ EXISTE
--------------
Porque ya pasó. El primer commit se llevó `dashboard/base_financiera.json`:
420 KB con los ingresos, los activos y los saldos de las cinco empresas. No fue
descuido al escribir el `.gitignore` — fue que ese archivo se creó DESPUÉS de
escribirlo, y nadie volvió a revisar la lista.

Se detectó antes de subirlo, por suerte. Y esa es exactamente la palabra que no
debe aparecer en un proceso: **Git no olvida**. Un archivo con cifras del
negocio que entra una vez queda en la historia y en cada copia que alguien haya
clonado; borrarlo después no lo quita de ahí.

Una lista escrita a mano envejece cada vez que alguien agrega un archivo. Una
comprobación que mira lo que de verdad se va a subir, no.

    python verificar_repositorio.py
===============================================================================
"""
import os
import re
import sys
import subprocess

sys.stdout.reconfigure(encoding='utf-8')

AQUI = os.path.dirname(os.path.abspath(__file__))

# Lo que nunca debe viajar en el repositorio, por su forma.
#
# No se buscan nombres de archivo —esa es la lista que envejece— sino el
# CONTENIDO: un archivo nuevo con cifras del ERP cae aquí aunque nadie lo haya
# previsto.
# Cada patrón exige CARGA, no solo la forma. Un documento que explica cómo se
# ve un secreto cifrado escribe `{"alg": "AES-256-GCM", "datos": "<cifrado>"}`,
# y marcarlo sería una falsa alarma — y una herramienta que siempre marca algo
# se deja de leer. Por eso se piden dígitos de verdad y bloques largos de
# base64, que es lo que distingue un ejemplo de un dato.
SENALES = [
    (r'"saldo_final":\s*-?\d', 'saldos del ERP'),
    (r'"cuenta_padre":\s*"\d', 'catálogo de cuentas del ERP'),
    (r'"activos_totales":\s*\d{7,}', 'balances reales'),
    (r'"ingresos":\s*\d{7,}', 'ingresos reales'),
    (r'aws_secret_access_key\s*=\s*\S{20,}|AKIA[0-9A-Z]{16}',
     'credenciales de AWS'),
    (r'"datos":\s*"[A-Za-z0-9+/=]{40,}"', 'secreto cifrado de verdad'),
    (r'-----BEGIN [A-Z ]*PRIVATE KEY-----', 'llave privada'),
]

# Este archivo contiene, por definición, todos los patrones que busca. Si se
# revisara a sí mismo se denunciaría siempre.
SE_EXCLUYE = {'verificar_repositorio.py'}

# Peso a partir del cual un archivo de datos merece una mirada. El código de
# este proyecto no pasa de 400 KB por archivo.
LIMITE_KB = 500


def rastreados():
    r = subprocess.run(['git', 'ls-files'], cwd=AQUI,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print('No es un repositorio de Git todavía.')
        return None
    return [f for f in r.stdout.split('\n') if f.strip()]


def main():
    archivos = rastreados()
    if archivos is None:
        return 0

    print(f'Lo que Git subiría: {len(archivos)} archivo(s)\n' + '=' * 70)
    problemas = []

    for f in archivos:
        if os.path.basename(f) in SE_EXCLUYE:
            continue
        ruta = os.path.join(AQUI, f)
        if not os.path.exists(ruta):
            continue
        kb = os.path.getsize(ruta) / 1024
        if kb > LIMITE_KB:
            problemas.append((f, f'pesa {kb:.0f} KB', 'revisar si son datos'))
        try:
            texto = open(ruta, encoding='utf-8', errors='ignore').read()
        except Exception:                                    # noqa: BLE001
            continue
        for patron, que in SENALES:
            if re.search(patron, texto):
                problemas.append((f, que, f'{kb:.0f} KB'))
                break

    if not problemas:
        total = sum(os.path.getsize(os.path.join(AQUI, f)) / 1024
                    for f in archivos if os.path.exists(os.path.join(AQUI, f)))
        print(f'  limpio — solo código, {total / 1024:.1f} MB')
        print('\nOK — no hay datos del negocio en lo que se subiría.')
        return 0

    print('  ALTO: hay archivos que NO deberían subirse\n')
    for f, que, extra in problemas:
        print(f'   {f}')
        print(f'      {que}  ({extra})')
    print('\n  Git no olvida: lo que entre una vez queda en la historia y en')
    print('  cada copia clonada. Quítalos ANTES de subir:')
    print(f'      git rm --cached {problemas[0][0]}')
    print('      (agrégalo también a .gitignore)')
    return 1


if __name__ == '__main__':
    sys.exit(main())
