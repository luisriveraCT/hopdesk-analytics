# -*- coding: utf-8 -*-
"""
===============================================================================
 VERIFICADOR DE PERMISOS SAP — corre esto las veces que haga falta
===============================================================================
Herramienta de autoservicio: prueba, empresa por empresa, cada permiso de
lectura que necesita el análisis financiero, y te dice exactamente cuál falta
y dónde otorgarlo en SAP.

Está hecha para correrse muchas veces mientras se gestionan los permisos, sin
tener que preguntarle a nadie si ya quedó.

    python verificar_permisos.py              todas las empresas, todo
    python verificar_permisos.py --empresa NG  una sola
    python verificar_permisos.py --criticos    solo lo indispensable

CÓDIGO DE SALIDA (por si lo quieres encadenar en un script):
    0 = todos los permisos críticos funcionan en todas las empresas
    1 = falta al menos un permiso crítico
===============================================================================
"""
import os
import sys
import datetime as dt
import argparse

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import sap_b1


# ---------------------------------------------------------------------------
# Catálogo de lo que necesitamos, con dónde se otorga cada cosa en SAP B1.
# La ruta del menú es la del cliente en español; entre paréntesis la inglesa,
# porque muchas instalaciones están en inglés.
# ---------------------------------------------------------------------------
PERMISOS = [
    # --- CRÍTICOS: sin estos no existe el estado financiero ---
    dict(endpoint='ChartOfAccounts', nivel='CRITICO',
         para='Catálogo de cuentas — la columna vertebral del Balance y del Estado de Resultados',
         ruta='Finanzas → Plan de cuentas  (Financials → Chart of Accounts)'),
    dict(endpoint='JournalEntries', nivel='CRITICO',
         para='Pólizas — de aquí se derivan TODOS los saldos mensuales desde 2020',
         ruta='Finanzas → Asiento  (Financials → Journal Entry)'),

    # --- IMPORTANTES: completan el análisis ---
    dict(endpoint='BusinessPartners', nivel='IMPORTANTE',
         para='Clientes y proveedores — para analizar cartera y cuentas por pagar por contraparte',
         ruta='Socios de negocios → Datos maestros de socio de negocios  '
              '(Business Partners → Business Partner Master Data)'),
    dict(endpoint='Currencies', nivel='IMPORTANTE',
         para='Catálogo de monedas — necesario porque se factura en USD además de MXN',
         ruta='Gestión → Definiciones → Finanzas → Monedas  '
              '(Administration → Setup → Financials → Currencies)'),
    # NO existe una entidad `ExchangeRates` en este Service Layer. Se verificó
    # contra el documento de servicio del propio servidor (376 entidades): las
    # únicas parecidas son tablas de usuario (U_CTX_EXCHANGERATE, U_CTX_AVGRATES)
    # y están VACÍAS. Los tipos de cambio estándar se piden por la acción
    # SBOBobService_GetCurrencyRate, que se prueba aparte en probar_empresa().
    # Pedirlos como entidad devolvía HTTP 400 "Unrecognized resource path", que
    # este verificador reportaba como permiso faltante — mandando a alguien a
    # buscar en SAP una autorización que no existe. Un verificador que acusa
    # permisos inexistentes es peor que no tenerlo: quema la confianza en el
    # resto de sus avisos.
    dict(endpoint='IncomingPayments', nivel='IMPORTANTE',
         para='Pagos recibidos — flujo de efectivo real de entrada (cobranza)',
         ruta='Bancos → Pagos recibidos  (Banking → Incoming Payments)'),
    dict(endpoint='VendorPayments', nivel='IMPORTANTE',
         para='Pagos efectuados — flujo de efectivo real de salida',
         ruta='Bancos → Pagos efectuados  (Banking → Outgoing Payments)'),

    # --- ÚTILES: habilitan análisis adicionales, no bloquean ---
    dict(endpoint='ProfitCenters', nivel='UTIL',
         para='Centros de beneficio — análisis de rentabilidad por unidad de negocio',
         ruta='Finanzas → Contabilidad de costes → Centros de beneficio  '
              '(Financials → Cost Accounting → Profit Centers)'),
    dict(endpoint='Dimensions', nivel='UTIL',
         para='Dimensiones — segmentación adicional del análisis de costos',
         ruta='Finanzas → Contabilidad de costes → Dimensiones  '
              '(Financials → Cost Accounting → Dimensions)'),
    dict(endpoint='CashFlowLineItems', nivel='UTIL',
         para='Taxonomía nativa de flujo de efectivo de SAP (si está configurada, nos ahorra clasificar a mano)',
         ruta='Finanzas → Definiciones → Partidas de flujo de efectivo  '
              '(Financials → Setup → Cash Flow Line Items)'),
    dict(endpoint='BudgetScenarios', nivel='UTIL',
         para='Escenarios de presupuesto — para comparar presupuesto contra real',
         ruta='Finanzas → Presupuesto → Escenarios de presupuesto  '
              '(Financials → Budget → Budget Scenarios)'),
    dict(endpoint='ChecksforPayment', nivel='UTIL',
         para='Cheques emitidos — detalle de pagos con cheque',
         ruta='Bancos → Pagos efectuados → Cheques para pago  '
              '(Banking → Outgoing Payments → Checks for Payment)'),

    # --- CONTROL: ya funcionan; si alguno falla, el problema es otro ---
    dict(endpoint='Invoices', nivel='CONTROL',
         para='Facturas de venta (ya funciona — sirve para confirmar que la conexión está sana)',
         ruta='—'),
    dict(endpoint='PurchaseInvoices', nivel='CONTROL',
         para='Facturas de compra (ya funciona)',
         ruta='—'),
]

COLOR = {'CRITICO': '!!', 'IMPORTANTE': ' !', 'UTIL': '  ', 'CONTROL': '  '}


def probar_empresa(iniciales, solo_criticos=False):
    """Prueba todos los permisos en una empresa. Regresa (resultados, error_conexion)."""
    try:
        ses = sap_b1.SesionSAP(iniciales, timeout=40)
    except Exception as e:
        return None, f'sin credenciales: {e}'
    try:
        ses.login()
    except Exception as e:
        txt = str(e)
        if 'imeout' in txt or 'Max retries' in txt:
            return None, 'SIN RED — el servidor no responde. ¿Está conectada la VPN?'
        return None, f'login falló: {txt[:200]}'

    resultados = {}
    try:
        for p in PERMISOS:
            if solo_criticos and p['nivel'] != 'CRITICO':
                continue
            ep = p['endpoint']
            try:
                ses.get_todo(ep, max_filas=1, pagina=1)
                resultados[ep] = {'ok': True, 'error': ''}
            except Exception as e:
                m = str(e)
                # Distinguir permiso de bug propio. -3000 es la única respuesta
                # que significa "el usuario no está autorizado". Un 400 con
                # "Unrecognized resource path" significa que ESTE código pidió
                # algo que no existe, y decirle "falta permiso" a quien
                # administra SAP lo manda a buscar un fantasma.
                if '-3000' in m:
                    motivo = 'SIN PERMISO (-3000)'
                elif 'Unrecognized resource path' in m or 'code=200' in m:
                    motivo = ('NO EXISTE en este servidor — es un error de este '
                              'verificador, NO un permiso faltante')
                else:
                    motivo = m[:110]
                resultados[ep] = {'ok': False, 'error': motivo}

        # Tipos de cambio: no es entidad, es una acción. Se prueba aparte y se
        # interpreta distinto: -4006 ("Update the exchange rate") NO es falta de
        # permiso, es que SAP no tiene tipo cargado para esa fecha — un dato que
        # falta en el ERP, que se arregla en contabilidad y no en autorizaciones.
        try:
            r = ses.s.post(f'{ses.config["url"]}/SBOBobService_GetCurrencyRate',
                           timeout=40, json={'Currency': 'USD',
                                             'Date': dt.date.today().isoformat()})
            if r.status_code == 200:
                resultados['TipoDeCambio(USD)'] = {'ok': True, 'error': ''}
            elif '-4006' in r.text:
                resultados['TipoDeCambio(USD)'] = {
                    'ok': True,
                    'error': 'accesible, pero SAP no tiene tipo de cambio cargado hoy'}
            elif '-3000' in r.text:
                resultados['TipoDeCambio(USD)'] = {'ok': False,
                                                   'error': 'SIN PERMISO (-3000)'}
            else:
                resultados['TipoDeCambio(USD)'] = {'ok': False,
                                                   'error': r.text[:110]}
        except Exception as e:
            resultados['TipoDeCambio(USD)'] = {'ok': False, 'error': str(e)[:110]}
    finally:
        ses.logout()
    return resultados, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--empresa',
                    help='iniciales de la empresa; las disponibles salen de '
                         'la configuración del cliente (configurar.py --mostrar)')
    ap.add_argument('--criticos', action='store_true', help='probar solo los permisos críticos')
    args = ap.parse_args()

    empresas = [args.empresa.upper()] if args.empresa else sap_b1.empresas_con_erp()

    # El usuario de integración se LEE de las credenciales configuradas, no se
    # escribe aquí. Escrito, decía el nombre de un usuario de este cliente, y
    # además podía mentir: el día que alguien rotara la cuenta en la
    # configuración, este encabezado habría seguido anunciando la anterior
    # mientras la verificación corría con la nueva.
    try:
        _, auth, fuente = sap_b1.credenciales(empresas[0])
        usuario = f"{auth.get('user') or '(sin usuario)'}  [{fuente}]"
    except Exception:
        usuario = '(no se pudo leer de la configuración)'
    print('=' * 79)
    print(f' VERIFICACIÓN DE PERMISOS DEL ERP — usuario de integración: {usuario}')
    print('=' * 79)

    faltantes_globales = {}   # endpoint -> [empresas donde falta]
    criticos_fallando = False
    sin_conexion = []

    for ini in empresas:
        res, err = probar_empresa(ini, solo_criticos=args.criticos)
        db = ''
        try:
            cfg, _, _ = sap_b1.credenciales(ini)
            db = cfg['company']
        except Exception:
            pass
        print(f'\n─── {ini}  ({db}) ───')
        if err:
            print(f'   {err}')
            sin_conexion.append(ini)
            criticos_fallando = True
            continue
        for p in PERMISOS:
            ep = p['endpoint']
            if ep not in res:
                continue
            r = res[ep]
            marca = 'OK    ' if r['ok'] else 'FALTA '
            print(f'   {COLOR[p["nivel"]]} {marca} {ep:<22} {"" if r["ok"] else r["error"]}')
            if not r['ok']:
                faltantes_globales.setdefault(ep, []).append(ini)
                if p['nivel'] == 'CRITICO':
                    criticos_fallando = True

    # ── Resumen accionable ────────────────────────────────────────────────
    print('\n' + '=' * 79)
    if sin_conexion:
        print(f' NO HUBO CONEXIÓN con: {", ".join(sin_conexion)}')
        print(' Revisa la VPN antes que cualquier otra cosa. Si el login falla pero hay red,')
        print(' el problema es la contraseña del usuario, no los permisos.')
        print('=' * 79)

    if not faltantes_globales:
        print(' TODO EN ORDEN — no falta ningún permiso.')
        print(' Siguiente paso: correr la extracción')
        print('     python extraer_estados_financieros.py --todas --desde 2020')
        print('=' * 79)
        return 0

    print(' PERMISOS QUE FALTAN — esto es lo que hay que otorgar en SAP')
    print('=' * 79)
    for p in PERMISOS:
        ep = p['endpoint']
        if ep not in faltantes_globales:
            continue
        emp = faltantes_globales[ep]
        todas = 'TODAS las empresas' if len(emp) == len(empresas) else ', '.join(emp)
        print(f'\n [{p["nivel"]}]  {ep}')
        print(f'   Para qué  : {p["para"]}')
        print(f'   Otorgar en: {p["ruta"]}')
        print(f'   Falta en  : {todas}')

    print('\n' + '-' * 79)
    print(' Ruta en SAP: Gestión → Inicialización de sistema → Autorizaciones →')
    print('              Autorizaciones generales → usuario LARivera → poner "Sólo lectura"')
    print(' IMPORTANTE: los permisos son POR BASE DE DATOS. Hay que repetirlo en las 5.')
    print('-' * 79)

    if criticos_fallando:
        print('\n Todavía faltan permisos CRÍTICOS: el análisis financiero no puede correr.')
        return 1
    print('\n Los permisos críticos ya están. El análisis básico puede correr;')
    print(' los que faltan solo limitan análisis adicionales.')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
