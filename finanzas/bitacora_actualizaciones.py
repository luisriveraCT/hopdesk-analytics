# -*- coding: utf-8 -*-
"""
===============================================================================
 BITÁCORA DE ACTUALIZACIONES — qué cambió, cuándo, y en qué periodo
===============================================================================
EL PROBLEMA QUE RESUELVE
------------------------
La contabilidad no es de solo escritura hacia adelante. Se corrigen periodos ya
reportados: una póliza mal clasificada en marzo se arregla en agosto, una
provisión se ajusta después del cierre, un auditor pide reclasificar el año
pasado. Cuando eso pasa, el número que alguien presentó en su momento deja de
coincidir con el que el sistema muestra hoy — y nadie se entera, porque el ERP
simplemente responde con el valor nuevo.

Esta bitácora existe para que sí se enteren. Cada extracción deja una huella de
cada periodo; en la siguiente se comparan, y todo lo que cambió queda
registrado con fecha, empresa, periodo afectado y magnitud.

POR QUÉ ESTO ES VALIOSO Y NO SOLO PROLIJO
-----------------------------------------
  · Explica discrepancias sin investigación forense. "El EBITDA de marzo ya no
    es el que reporté" deja de ser un misterio de medio día y pasa a ser una
    consulta.
  · Mide la calidad del cierre con datos reales en vez de percepción. Un
    periodo que sigue moviéndose tres meses después no estaba cerrado, por más
    que el calendario diga que sí.
  · Alimenta directamente dos de las columnas más difíciles de `Datos_Funcion`
    del tablero de KPIs: *Reprocesos/correcciones* y *Errores post-cierre*.
    Esas dos normalmente se capturan a mano —y por lo tanto se capturan mal,
    porque quien corrige rara vez registra que corrigió. Aquí salen solas, del
    hecho de que el dato cambió.

LO QUE ESTE MÓDULO **NO** INVENTA
---------------------------------
De las diez columnas de `Datos_Funcion`, esta bitácora produce honestamente
tres y media. Las demás requieren captura humana o una fuente que hoy no
tenemos, y se marcan como tal en vez de rellenarse con una estimación:

    Días de cierre .............. PARCIAL. Se infiere del comportamiento: el
                                  periodo se considera cerrado cuando deja de
                                  cambiar. Es una medición empírica y llega
                                  tarde por definición. Para el dato exacto
                                  hace falta la fecha de REGISTRO de cada
                                  póliza (`CreationDate`), que hoy no se
                                  guarda: la extracción agrega importes por
                                  cuenta y mes, y ahí esa fecha se pierde. Es
                                  una pasada adicional ligera, no una
                                  reextracción — ver NOTA_EXTRACCION abajo.
    Reprocesos/correcciones ..... SÍ. Es exactamente lo que se detecta.
    Errores post-cierre ......... SÍ. Correcciones a un periodo ya cerrado.
    Efectivo ocioso ............. PARCIAL. Los saldos de cuentas de efectivo
                                  están; falta la POLÍTICA (cuánto es ocioso),
                                  que es una decisión de tesorería, no un dato.
    Reportes comprometidos ...... NO. Proceso interno.
    Reportes a tiempo ........... NO. Proceso interno.
    Conciliaciones pendientes ... NO. Requiere InternalReconciliations de SAP.
    Antigüedad conciliaciones ... NO. Ídem.
    Hallazgos de auditoría ...... NO. Proceso interno.

Rellenar las siete restantes con números plausibles sería fácil y sería el peor
resultado posible: un tablero que se ve completo y miente. Se entregan vacías y
marcadas, para que quien las conozca las capture.

CÓMO ESTÁ GUARDADA
------------------
Dos archivos, con propósitos distintos a propósito:
  · `bitacora_estado.json` — las huellas actuales. Se sobrescribe. Es el "antes"
    contra el que se compara la próxima vez.
  · `bitacora.jsonl` — el registro histórico, **append-only**. Nunca se reescribe
    ni se corrige: un registro de auditoría que se puede editar no es un
    registro de auditoría. Una línea por evento, en JSON, para que sea legible
    con cualquier herramienta y no dependa de este código para sobrevivir.
===============================================================================
"""
import os
import sys
import json
import hashlib
import datetime as dt
from typing import Dict, List, Optional

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(AQUI, 'datos_erp')
ESTADO = os.path.join(DATOS, 'bitacora_estado.json')
LOG = os.path.join(DATOS, 'bitacora.jsonl')

# Un cambio por debajo de esto se registra pero no se considera "corrección":
# son diferencias de redondeo al reagregar, no ajustes contables.
UMBRAL_MATERIAL = 1.0

# Meses tras el fin del periodo a partir de los cuales un cambio se considera
# POST-CIERRE. Un ajuste dentro del mes siguiente es cierre normal; uno tres
# meses después es una corrección a algo ya reportado.
MESES_PARA_CIERRE = 2

NOTA_EXTRACCION = """
Para obtener 'Días de cierre' exacto hace falta una pasada adicional que NO
implica reextraer todo: una consulta por mes a JournalEntries pidiendo solo
$select=CreationDate,TaxDate (sin las líneas anidadas, que es lo que la hace
pesada). Con eso, días de cierre = fecha del último asiento REGISTRADO para el
periodo − fin del periodo. Es barata porque no baja importes; se puede correr
sobre los mismos meses ya cacheados sin tocar el resto del pipeline.
""".strip()


def _huella_periodo(filas: List[Dict]) -> Dict:
    """Huella de un (empresa, año, mes). Guarda los totales para poder decir
    CUÁNTO cambió, y un hash para detectar cambios que se compensan.

    El hash importa: si una póliza se reclasifica de una cuenta a otra por el
    mismo importe, los totales de debe y haber NO se mueven y el cambio sería
    invisible. El hash por cuenta sí lo ve. Es el caso más común de corrección
    contable, así que detectarlo no es un lujo."""
    debe = sum(f.get('debe') or 0 for f in filas)
    haber = sum(f.get('haber') or 0 for f in filas)
    detalle = sorted((f['codigo'], round(f.get('debe') or 0, 2),
                      round(f.get('haber') or 0, 2)) for f in filas)
    h = hashlib.sha256(json.dumps(detalle, separators=(',', ':')).encode()).hexdigest()[:16]
    return {'debe': round(debe, 2), 'haber': round(haber, 2),
            'n_cuentas': len(filas), 'hash': h}


def huellas_de(empresa: str) -> Dict[str, Dict]:
    ruta = os.path.join(DATOS, f'saldos_{empresa}.json')
    if not os.path.exists(ruta):
        return {}
    with open(ruta, encoding='utf-8') as f:
        saldos = json.load(f)
    por_periodo: Dict[str, List[Dict]] = {}
    for s in saldos:
        por_periodo.setdefault(f"{s['anio']}-{s['mes']:02d}", []).append(s)
    return {k: _huella_periodo(v) for k, v in por_periodo.items()}


def _es_post_cierre(periodo: str, hoy: dt.date) -> bool:
    a, m = (int(x) for x in periodo.split('-'))
    meses_transcurridos = (hoy.year - a) * 12 + (hoy.month - m)
    return meses_transcurridos > MESES_PARA_CIERRE


def comparar(empresas: Optional[List[str]] = None, registrar: bool = True) -> List[Dict]:
    """Compara el estado actual contra la última huella guardada y devuelve los
    eventos. Con `registrar=False` no escribe nada — útil para ver qué pasaría
    antes de dejar rastro."""
    previo = {}
    if os.path.exists(ESTADO):
        with open(ESTADO, encoding='utf-8') as f:
            previo = json.load(f)

    if empresas is None:
        empresas = sorted(a.replace('saldos_', '').replace('.json', '')
                          for a in os.listdir(DATOS) if a.startswith('saldos_'))

    hoy = dt.date.today()
    ahora = dt.datetime.now().isoformat(timespec='seconds')
    eventos, nuevo_estado = [], dict(previo)

    for emp in empresas:
        actuales = huellas_de(emp)
        anteriores = previo.get(emp, {})
        nuevo_estado[emp] = actuales

        for periodo, h in sorted(actuales.items()):
            ant = anteriores.get(periodo)
            if ant is None:
                # Primera vez que vemos el periodo. Si nunca habíamos visto NADA
                # de esta empresa es la carga inicial, no una novedad: marcarlo
                # como "nuevo" llenaría la bitácora de ruido el primer día.
                tipo = 'CARGA_INICIAL' if not anteriores else 'PERIODO_NUEVO'
                eventos.append({'fecha': ahora, 'empresa': emp, 'periodo': periodo,
                                'tipo': tipo, 'delta_debe': 0.0, 'delta_haber': 0.0,
                                'post_cierre': False})
                continue
            if ant['hash'] == h['hash']:
                continue

            d_debe = round(h['debe'] - ant['debe'], 2)
            d_haber = round(h['haber'] - ant['haber'], 2)
            material = max(abs(d_debe), abs(d_haber)) >= UMBRAL_MATERIAL
            post = _es_post_cierre(periodo, hoy)
            if not material and h['n_cuentas'] == ant['n_cuentas']:
                tipo = 'RECLASIFICACION'   # mismos totales, distinto reparto
            elif post:
                tipo = 'CORRECCION_POST_CIERRE'
            else:
                tipo = 'AJUSTE_DE_CIERRE'
            eventos.append({
                'fecha': ahora, 'empresa': emp, 'periodo': periodo, 'tipo': tipo,
                'delta_debe': d_debe, 'delta_haber': d_haber,
                'delta_cuentas': h['n_cuentas'] - ant['n_cuentas'],
                'post_cierre': post,
            })

    if registrar and eventos:
        os.makedirs(DATOS, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            for e in eventos:
                f.write(json.dumps(e, ensure_ascii=False) + '\n')
        with open(ESTADO, 'w', encoding='utf-8') as f:
            json.dump(nuevo_estado, f, ensure_ascii=False, separators=(',', ':'))
    return eventos


def leer_log() -> List[Dict]:
    if not os.path.exists(LOG):
        return []
    with open(LOG, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def datos_funcion(anio: int) -> List[Dict]:
    """Arma los renglones de la pestaña `Datos_Funcion` del tablero de KPIs,
    con las columnas que SÍ se pueden derivar y las demás en None.

    None no es un hueco por descuido: es la afirmación de que el dato no se
    conoce. Un cero diría que no hubo reprocesos, que es una mentira distinta."""
    log = leer_log()
    filas = []
    for mes in range(1, 13):
        periodo = f'{anio}-{mes:02d}'
        evs = [e for e in log if e['periodo'] == periodo]
        correcciones = [e for e in evs if e['tipo'] in
                        ('CORRECCION_POST_CIERRE', 'AJUSTE_DE_CIERRE', 'RECLASIFICACION')]
        post_cierre = [e for e in evs if e['tipo'] == 'CORRECCION_POST_CIERRE']
        filas.append({
            'mes': periodo,
            'dias_de_cierre': None,              # requiere CreationDate — ver NOTA_EXTRACCION
            'reportes_comprometidos': None,      # proceso interno
            'reportes_a_tiempo': None,           # proceso interno
            'errores_post_cierre': len(post_cierre),
            'reprocesos_correcciones': len(correcciones),
            'conciliaciones_pendientes': None,   # requiere InternalReconciliations
            'antiguedad_conciliaciones': None,   # ídem
            'hallazgos_auditoria': None,         # proceso interno
            'efectivo_ocioso': None,             # requiere política de tesorería
            'empresas_afectadas': sorted({e['empresa'] for e in correcciones}),
            'monto_corregido': round(sum(abs(e.get('delta_debe') or 0)
                                         for e in correcciones), 2),
        })
    return filas


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--simular', action='store_true',
                    help='comparar sin escribir en la bitácora')
    ap.add_argument('--historial', action='store_true', help='mostrar el log completo')
    ap.add_argument('--datos-funcion', type=int, metavar='AÑO',
                    help='armar los renglones de Datos_Funcion para ese año')
    args = ap.parse_args()

    if args.historial:
        log = leer_log()
        print(f'{len(log)} evento(s) en la bitácora')
        for e in log[-40:]:
            print(f"   {e['fecha'][:16]}  {e['empresa']:<4} {e['periodo']}  "
                  f"{e['tipo']:<24} Δdebe {e.get('delta_debe', 0):>14,.2f}")
        return

    if args.datos_funcion:
        print(f'--- Datos_Funcion {args.datos_funcion} ---')
        print(f"{'mes':<9}{'errores p/cierre':>18}{'reprocesos':>13}"
              f"{'monto corregido':>18}  empresas")
        for f in datos_funcion(args.datos_funcion):
            print(f"{f['mes']:<9}{f['errores_post_cierre']:>18}"
                  f"{f['reprocesos_correcciones']:>13}{f['monto_corregido']:>18,.2f}"
                  f"  {', '.join(f['empresas_afectadas'])}")
        print('\nLas columnas en blanco requieren captura o una fuente adicional.')
        print(NOTA_EXTRACCION)
        return

    evs = comparar(registrar=not args.simular)
    if not evs:
        print('Sin cambios respecto a la última extracción.')
        return
    print(f"{len(evs)} evento(s)" + (' (SIMULACIÓN, no se registró)' if args.simular else ''))
    resumen = {}
    for e in evs:
        resumen[e['tipo']] = resumen.get(e['tipo'], 0) + 1
    for t, n in sorted(resumen.items()):
        print(f'   {t:<24} {n}')
    for e in evs:
        if e['tipo'] in ('CORRECCION_POST_CIERRE', 'RECLASIFICACION'):
            print(f"   ATENCIÓN {e['empresa']} {e['periodo']}: {e['tipo']}  "
                  f"Δdebe {e.get('delta_debe', 0):,.2f}")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
