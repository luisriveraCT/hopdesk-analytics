# Conexión a ERP — diseño y estado

## Resumen en una línea

La estructura multi-ERP está construida y el conector de SAP B1 funciona
(conecta, autentica y lee), **pero el usuario de integración no tiene permiso
de lectura sobre la contabilidad**, así que hoy no se pueden extraer Estados
Financieros. Es un permiso, no un problema de código.

---

## 1. El "multicontacto": cómo está armado

`registro_conectores.py` es el único lugar donde se declara un ERP. Cada
conector registra cuatro cosas:

| Qué declara | Para qué |
|---|---|
| `campos_config` | Los datos no secretos (URL, base de datos). De aquí se genera el formulario de conexión, no se escribe a mano. |
| `campos_secretos` | Usuario y contraseña. Nunca viven en el repositorio. |
| `capacidades` | **Qué puede entregar de verdad** ese ERP: catálogo de cuentas, saldos, pólizas, facturas, multiempresa. |
| `fn_homologar` | La única función obligatoria: traduce la respuesta cruda de ese ERP a la forma canónica. |

La pieza que sostiene todo es la **forma canónica**: `cuentas` y `saldos` con
nombres de campo propios, independientes de cualquier ERP. Ni el análisis ni el
tablero conocen los nombres de SAP — solo el archivo `sap_b1.py` los conoce. El
día que entre un segundo ERP, se escribe su `fn_homologar` y **nada más del
sistema se toca**.

`capacidades` es una adición sobre el patrón de HopDesk. HopDesk solo necesita
facturas, y todos los ERP las tienen. Aquí necesitamos Estados Financieros
completos, y ahí sí difieren mucho entre sí. Declararlo por adelantado evita
descubrir a media extracción que falta media contabilidad.

**No se implementó ningún otro ERP**, por instrucción. Cómo agregar uno está en
la constante `COMO_AGREGAR_UN_ERP` al final de `registro_conectores.py`.

## 2. Restricción de red — esto es arquitectura, no un detalle

El SAP de Networks vive en `192.168.14.131:50000`, una IP privada. Solo se
alcanza desde la red de la oficina o por VPN.

Por lo tanto **la app publicada en Connect Cloud nunca va a poder consultar
SAP**, y no tiene caso intentarlo. El flujo correcto es el mismo que ya usa la
facturación:

```
  máquina local (con VPN) → extrae del ERP → archivos → S3 → tablero estático
```

Cualquier diseño que suponga que el navegador consulta el ERP en vivo está mal
desde el arranque.

## 3. Estado real de los permisos (verificado en vivo el 2026-09-24)

Se probó contra las **cinco** bases de datos. El resultado es idéntico en todas:

| Endpoint | NCS | NG | NL | NRS | NTS | Para qué se necesita |
|---|:--:|:--:|:--:|:--:|:--:|---|
| Login | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `FinancialYears` | ✅ | ✅ | ✅ | ✅ | ✅ | Ejercicios fiscales |
| `Invoices` | ✅ | ✅ | ✅ | ✅ | ✅ | Facturas AR (lo que ya usa HopDesk) |
| `PurchaseInvoices` | ✅ | ✅ | ✅ | ✅ | ✅ | Facturas AP |
| **`ChartOfAccounts`** | ❌ | ❌ | ❌ | ❌ | ❌ | **Catálogo de cuentas → sin esto no hay Balance ni Estado de Resultados** |
| **`JournalEntries`** | ❌ | ❌ | ❌ | ❌ | ❌ | **Pólizas → de aquí se derivan los saldos por mes** |
| `CashFlowLineItems` | ❌ | ❌ | ❌ | ❌ | ❌ | Taxonomía nativa de flujo de efectivo |

Error en todos los bloqueados: `HTTP 403 — SAP code = -3000 · "The logged-on
user does not have permission to use this"`.

Es **el mismo bloqueo detectado el 2 de septiembre de 2026**: el permiso que se
solicitó entonces nunca se aplicó.

### Qué hay que pedirle al administrador de SAP

> Al usuario de integración del Service Layer (el mismo que ya usa HopDesk) le
> falta autorización de **solo lectura** sobre el módulo de Finanzas, en las
> cinco bases (SBO_CROSSDOCKING, SBO_NETWORKSSS, SBO_LOGISTICS, SBO_REALTORS,
> SBO_TRUCKING).
>
> En SAP B1: **Administración → Inicialización de sistema → Autorizaciones →
> Autorizaciones generales**, sobre ese usuario, dar *Solo lectura* en:
> - Finanzas → Plan de cuentas
> - Finanzas → Asientos / Documento de asiento (Journal Entries)
>
> No se requiere permiso de escritura en nada. Todas las llamadas del conector
> son GET salvo el Login/Logout.

Un solo permiso de Finanzas desbloquea los tres endpoints a la vez: no son tres
solicitudes distintas.

## 4. Qué pasa el día que se otorgue el permiso

```bash
# 1. Verificar que ya quedó
python extraer_estados_financieros.py --diagnostico --empresa NG

# 2. Extraer (con VPN conectada)
python extraer_estados_financieros.py --todas --desde 2020
```

Produce, en `finanzas/datos_erp/`, para cada empresa: `cuentas_<INI>.json` y
`saldos_<INI>.json` en forma canónica. De ahí `analisis_vertical_horizontal.py`
arma Balance y Estado de Resultados por mes.

**Cómo se derivan los saldos.** El Service Layer no expone una balanza de
comprobación. El único campo de saldo disponible, `ChartOfAccounts.CurrentBalance`,
es el saldo de *hoy* — inútil para una serie desde 2020. Así que los saldos se
construyen sumando las líneas de las pólizas por cuenta y por mes. Es más lento,
pero es la única fuente fiel y además es auditable: cada saldo se puede rastrear
hasta sus asientos.

## 5. Dos detalles que van a morder si no se anotan

**a) Las iniciales no coinciden entre sistemas.** HopDesk/SAP usa `NRS` para
Networks Realtors; la base de facturación usa `NR`. El mapeo está en
`sap_b1.INICIALES_SAP_A_FACTURACION` — hay que cruzarlas por ahí, no por
coincidencia de texto.

**b) Paragon Logistics (PL) no tiene SAP configurado.** Aparece en la
facturación desde 2026 pero no hay variables `SAP_PL_*`. Si ya opera en SAP,
hay que agregarlas; si todavía no, sus estados financieros tendrán que llegar
por otra vía.

## 6. La clasificación de cuentas no se adivina

SAP B1 no guarda "Activo/Pasivo/Capital" como tal: guarda `AcctType`
(`at_Revenues` / `at_Expenses` / `at_Other`) y organiza el Balance por cajones.
El conector clasifica por prefijo de código de cuenta (plan mexicano estándar:
1=Activo, 2=Pasivo, 3=Capital, 4=Ingreso, 5=Costo, 6/7=Gasto), configurable en
`MAPEO_CLASE_POR_PREFIJO`.

Lo que **no** hace: acomodar por parecido una cuenta que no encaje. Esas salen
marcadas como `OTRO` y la extracción las lista en pantalla para que un humano
decida. Un Balance que cuadra porque el código forzó una clasificación es peor
que uno que no cuadra y lo dice.
