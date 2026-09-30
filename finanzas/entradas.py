# -*- coding: utf-8 -*-
"""
===============================================================================
 entradas.py — capturar, aplicar y auditar las entradas manuales
===============================================================================
La contraparte de la hoja de captura del tablero. La hoja edita una copia de
trabajo en el navegador y produce un archivo; esto lo aplica, lo registra en la
bitácora y deja el dato listo para la siguiente construcción.

    python entradas.py --ver                       qué hay capturado hoy
    python entradas.py --campos                    qué se puede capturar
    python entradas.py --fijar beta=1.25 --empresa NTS --autor "Ana"
    python entradas.py --fijar ingresos=1200000 --empresa NCS --periodo 2026-08 \
                       --desbloquear --motivo "Factura 4471 capturada dos veces en SAP"
    python entradas.py --borrar beta --empresa NTS --autor "Ana"
    python entradas.py --aplicar cambios.json --autor "Ana"
    python entradas.py --bitacora                  los últimos movimientos
    python entradas.py --bitacora --todo           la bitácora completa

POR QUÉ EL AUTOR ES OBLIGATORIO
--------------------------------
Una cifra puesta a mano sin nombre no se puede auditar: dentro de seis meses la
pregunta no va a ser "¿cuánto vale?" sino "¿quién decidió esto y por qué?".
Preferimos estorbar hoy a no poder contestar después.
===============================================================================
"""
import os
import sys
import json
import argparse

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(AQUI, 'configuracion'))

sys.stdout.reconfigure(encoding='utf-8')

import entradas_manuales as em            # noqa: E402
import bitacora_cambios as bc             # noqa: E402
import repositorio as repo                # noqa: E402


def _contexto():
    almacen = repo.almacen_por_defecto()
    cliente = repo.cliente_actual(almacen)
    return almacen, cliente


def mostrar_campos():
    print('\nCampos capturables\n' + '=' * 72)
    for gid, gnombre, gdesc in em.GRUPOS:
        campos = [(k, c) for k, c in em.CAMPOS.items() if c['grupo'] == gid]
        if not campos:
            continue
        print(f'\n  {gnombre}')
        print(f'  {gdesc}')
        for k, c in sorted(campos):
            marca = '  ' if c['tipo'] == em.SUMINISTRO else '!!'
            rango = (f"  rango [{c['rango'][0]:g}, {c['rango'][1]:g}]{c['unidad']}"
                     if c.get('rango') else '')
            print(f'    {marca} {k:<24} {c["etiqueta"]:<34} '
                  f'{c["unidad"]:<3}{rango}')
    print('\n  !! = el sistema lo calcula; editarlo es SOBRESCRIBIR y requiere '
          '--desbloquear y --motivo.\n')


def _donde():
    """Dónde se lee y se escribe. Se imprime SIEMPRE, antes del dato.

    Capturar una cifra contra el disco de la laptop creyendo que se captura
    contra el almacén compartido produce trabajo que nadie más va a ver, y no
    hay nada en el resultado que lo delate.
    """
    print(f'\nalmacén: {repo.descripcion_almacen()}')


def ver(almacen, cliente):
    _donde()
    ent = em.cargar(almacen, cliente)
    if not ent.entradas:
        print('\nNo hay ninguna entrada manual capturada.\n')
        return
    print(f'\nEntradas manuales de {cliente.nombre}  '
          f'(última actualización: {ent.actualizado})\n' + '=' * 76)
    filas = sorted(ent.entradas.values(),
                   key=lambda r: (r['tipo'], r['campo'], r['empresa'], r['periodo']))
    for r in filas:
        c = em.CAMPOS.get(r['campo'], {})
        marca = '!!' if r['tipo'] == em.SOBRESCRITURA else '  '
        # Se muestra en la unidad en que se escribe, no en la que se guarda:
        # una tasa capturada como 9.6% no debe reaparecer como 0.096.
        mostrado = em.a_mostrado(r['campo'], r['valor'])
        print(f"  {marca} {r['campo']:<22} {r['empresa']:<5} {r['periodo']:<8} "
              f"{mostrado:>16,.4f}  {c.get('unidad', '')}")
        if r['motivo']:
            print(f"        motivo: {r['motivo']}")
        if r['autor']:
            print(f"        capturó: {r['autor']}  ({r['fecha']})")
    sob = ent.sobrescrituras()
    if sob:
        print(f'\n  {len(sob)} sobrescritura(s) activas: son cifras que el '
              f'sistema calcula y alguien reemplazó.')
        print('  Para devolver cualquiera al cálculo automático, bórrala:')
        r = sob[0]
        print(f"      python entradas.py --borrar {r['campo']} "
              f"--empresa {r['empresa']} --periodo {r['periodo']} --autor TU_NOMBRE")
    print()


def fijar(almacen, cliente, asignacion, empresa, periodo, motivo, autor,
          desbloquear):
    if '=' not in asignacion:
        raise SystemExit('Formato esperado: --fijar campo=valor')
    campo, valor = asignacion.split('=', 1)
    campo = campo.strip()
    ent = em.cargar(almacen, cliente)
    anterior = ent.entradas.get(em.clave(empresa, periodo, campo))
    try:
        reg = ent.fijar(empresa, periodo, campo, valor, motivo, autor,
                        desbloquear)
    except em.EntradaInvalida as e:
        raise SystemExit(f'\n  No se guardó: {e}\n')
    em.guardar(almacen, cliente, ent)

    if desbloquear and em.CAMPOS[campo]['tipo'] == em.SOBRESCRITURA:
        bc.registrar(almacen, cliente, 'desbloqueo', autor,
                     {'campo': campo, 'empresa': empresa, 'periodo': periodo,
                      'motivo': motivo})
    bc.registrar(almacen, cliente, 'cambio' if anterior else 'captura', autor,
                 {'campo': campo, 'empresa': empresa, 'periodo': periodo,
                  'de': anterior['valor'] if anterior else None,
                  'a': reg['valor'], 'motivo': motivo, 'tipo': reg['tipo']})
    # Se confirma con lo que la persona escribió, no con lo que se guardó.
    # Ver `a_interno`: son la misma cifra en dos unidades, y devolverle la otra
    # hace dudar de si el sistema entendió.
    _u = em.CAMPOS[campo]['unidad']
    print(f"\n  {campo} = {em.a_mostrado(campo, reg['valor']):g}{_u}  [{empresa}/{periodo}]"
          + (f"\n  SOBRESCRITURA — queda marcada en el tablero hasta que se borre."
             if reg['tipo'] == em.SOBRESCRITURA else '') + '\n')


def borrar(almacen, cliente, campo, empresa, periodo, autor):
    ent = em.cargar(almacen, cliente)
    reg = ent.borrar(empresa, periodo, campo)
    if reg is None:
        raise SystemExit(f'\n  No había nada capturado en '
                         f'{campo} [{empresa}/{periodo}].\n')
    em.guardar(almacen, cliente, ent)
    bc.registrar(almacen, cliente, 'borrado', autor,
                 {'campo': campo, 'empresa': empresa, 'periodo': periodo,
                  'de': reg['valor'], 'a': None})
    print(f"\n  Borrado {campo} [{empresa}/{periodo}]. "
          f"Vuelve al cálculo automático en la próxima construcción.\n")


def aplicar(almacen, cliente, ruta, autor):
    """Aplica un lote producido por la hoja de captura del tablero.

    Se valida cambio por cambio y se aplican solo los que pasan. Un lote que se
    rechaza entero porque un renglón trae un error obliga a rehacer el trabajo
    de los otros veinte, y en la práctica eso termina en que alguien desactiva
    la validación.
    """
    with open(ruta, encoding='utf-8') as f:
        lote = json.load(f)
    cambios = lote.get('cambios') or []
    if not cambios:
        raise SystemExit('El archivo no trae ningún cambio.')

    ent = em.cargar(almacen, cliente)
    aplicados, rechazados = [], []
    for c in cambios:
        campo = c.get('campo')
        empresa = c.get('empresa') or em.COMODIN
        periodo = c.get('periodo') or em.COMODIN
        try:
            if c.get('borrar'):
                reg = ent.borrar(empresa, periodo, campo)
                if reg:
                    aplicados.append(('borrado', campo, empresa, periodo,
                                      reg['valor'], None, ''))
                continue
            previo = ent.entradas.get(em.clave(empresa, periodo, campo))
            reg = ent.fijar(empresa, periodo, campo, c.get('valor'),
                            c.get('motivo', ''), autor,
                            desbloqueado=bool(c.get('desbloqueado')))
            aplicados.append(('cambio' if previo else 'captura', campo, empresa,
                              periodo, previo['valor'] if previo else None,
                              reg['valor'], reg['motivo']))
        except em.EntradaInvalida as e:
            rechazados.append((campo, empresa, periodo, str(e)))

    if aplicados:
        em.guardar(almacen, cliente, ent)
        for acto, campo, empresa, periodo, de, a, motivo in aplicados:
            bc.registrar(almacen, cliente, acto, autor,
                         {'campo': campo, 'empresa': empresa,
                          'periodo': periodo, 'de': de, 'a': a,
                          'motivo': motivo}, origen='tablero')
        bc.registrar(almacen, cliente, 'aplicacion', autor,
                     {'n': len(aplicados), 'archivo': os.path.basename(ruta),
                      'rechazados': len(rechazados)}, origen='tablero')

    print(f'\n  Aplicados: {len(aplicados)}')
    for acto, campo, empresa, periodo, de, a, _ in aplicados:
        print(f'    {acto:<9} {campo:<22} [{empresa}/{periodo}]  {de} → {a}')
    if rechazados:
        print(f'\n  Rechazados: {len(rechazados)} — no se guardaron, el resto sí')
        for campo, empresa, periodo, msg in rechazados:
            print(f'    {campo:<22} [{empresa}/{periodo}]  {msg}')
    print('\n  Corre `python actualizar.py --solo-tablero` para que se reflejen.\n')


def ver_bitacora(almacen, cliente, autor, limite, filtro_acto, filtro_autor):
    _donde()
    asientos = bc.leer(almacen, cliente, limite, filtro_acto, filtro_autor)
    r = bc.resumen(almacen, cliente)
    print(f'\nBitácora de cambios de {cliente.nombre}\n' + '=' * 76)
    print(f'  {r["total"]} asiento(s)'
          + (f'  ·  último: {r["ultimo"]}' if r['ultimo'] else ''))
    if r['por_acto']:
        print('  ' + '  ·  '.join(f'{bc.ACTOS.get(k, k)}: {v}'
                                  for k, v in sorted(r['por_acto'].items())))
    print()
    if not asientos:
        print('  (sin movimientos que mostrar)\n')
    for a in asientos:
        print('  ' + bc.describir(a))
    print()
    # Consultar la bitácora también se registra: quién la revisó y cuándo es
    # parte de la auditoría, no ruido.
    bc.registrar(almacen, cliente, 'consulta', autor,
                 {'n': len(asientos), 'filtro_acto': filtro_acto or '',
                  'filtro_autor': filtro_autor or ''})


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--ver', action='store_true')
    ap.add_argument('--campos', action='store_true')
    ap.add_argument('--fijar', metavar='campo=valor')
    ap.add_argument('--borrar', metavar='campo')
    ap.add_argument('--aplicar', metavar='ARCHIVO.json')
    ap.add_argument('--bitacora', action='store_true')
    ap.add_argument('--empresa', default=em.COMODIN)
    ap.add_argument('--periodo', default=em.COMODIN)
    ap.add_argument('--motivo', default='')
    ap.add_argument('--autor', default='')
    ap.add_argument('--desbloquear', action='store_true',
                    help='permite editar un campo que el sistema calcula')
    ap.add_argument('--todo', action='store_true',
                    help='con --bitacora, muestra todos los asientos')
    ap.add_argument('--acto', help='con --bitacora, filtra por tipo de acto')
    ap.add_argument('--de-autor', help='con --bitacora, filtra por autor')
    args = ap.parse_args()

    if args.campos:
        mostrar_campos()
        return

    almacen, cliente = _contexto()

    # Todo lo que MODIFICA exige autor. Consultar no.
    if (args.fijar or args.borrar or args.aplicar) and not args.autor.strip():
        raise SystemExit(
            '\n  Falta --autor. Una cifra puesta a mano sin nombre no se puede\n'
            '  auditar: la pregunta que alguien va a hacer dentro de seis meses\n'
            '  no es cuánto vale, es quién lo decidió y por qué.\n')

    if args.fijar:
        fijar(almacen, cliente, args.fijar, args.empresa.upper(), args.periodo,
              args.motivo, args.autor, args.desbloquear)
    elif args.borrar:
        borrar(almacen, cliente, args.borrar, args.empresa.upper(),
               args.periodo, args.autor)
    elif args.aplicar:
        aplicar(almacen, cliente, args.aplicar, args.autor)
    elif args.bitacora:
        ver_bitacora(almacen, cliente, args.autor,
                     None if args.todo else 40, args.acto, args.de_autor)
    else:
        ver(almacen, cliente)


if __name__ == '__main__':
    main()
