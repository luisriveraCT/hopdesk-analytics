# Prompt — Módulo de KPIs Financieros

> **Para quien reciba este encargo.** Es un documento de trabajo autosuficiente:
> trae el objetivo, las fuentes de datos reales, lo que ya está construido y no
> debe rehacerse, las reglas que no se negocian y las trampas ya descubiertas.
> Léelo completo antes de escribir código.

---

## 1. Qué se pide

Construir el módulo que alimenta y reemplaza al archivo
`C:\Users\luisr\Documents\NETWORKS\NWS2026\Gerente de Finanzas\KPIs Finanzas\KPIs_Finanzas.xlsx`,
dentro del desarrollo que ya vive en `Analitica_Financiera\finanzas\`.

Hoy ese Excel funciona con **datos de ejemplo**. Se nota: la serie de "Días de
cierre" va 9, 9, 8, 8, 8, 7, 7, 7, 6, 6, 6, 5 — una recta perfecta que ningún
proceso real produce. El encargo es sustituir esos datos sintéticos por datos
reales, conservando la estructura conceptual del archivo, que es buena.

El objetivo final es que el tablero viva en la aplicación, no en un Excel que
alguien actualiza a mano. El Excel queda como especificación y como salida
opcional, no como la fuente.

---

## 2. Las tres fuentes de datos, y qué da cada una

Este es el punto más importante del encargo. **No hay una sola fuente**, y
confundirlas produce un tablero que parece completo y está mal.

### Fuente A — SAP B1, vía el conector ya construido

Ubicación: `finanzas/erp/`. Entrega Estados Financieros completos de las cinco
empresas con SAP (NCS, NG, NL, NRS, NTS) desde 2020, mes a mes.

Da: ingresos, costo, gastos, resultado financiero, utilidad; activos, pasivos,
capital, efectivo, cuentas por cobrar y por pagar, inventarios.

**Paragon Logistics (PL) no tiene SAP.** Sus datos vienen de la base de
facturación consolidada. Cualquier KPI consolidado del grupo debe decir
explícitamente si incluye o excluye a PL — no asumir.

### Fuente B — HopDesk (la aplicación hermana)

Estas dos aplicaciones trabajan juntas. HopDesk **ya tiene**:

- **Antigüedad de saldos** (cartera por cobrar y por pagar, con sus cubetas de
  antigüedad). Esto es mejor que derivar DSO/DPO del Balance: da el detalle por
  edad y por contraparte, no solo el saldo.
- **El listado completo de los financiamientos** con sus datos. Esto vuelve
  reales varios KPIs que de otro modo serían estimaciones: el costo efectivo de
  la deuda (Kd), la deuda con costo, D/E y Deuda Neta/EBITDA salen del
  instrumento, no de un promedio inferido del Balance.

**Antes de escribir cualquier cálculo de DSO, DPO, CCC, Kd o deuda: revisa qué
expone HopDesk y consúmelo.** Volver a derivarlo del Balance sería tener dos
números distintos para la misma cosa en dos aplicaciones de la misma casa, que
es exactamente el problema que se quiere evitar.

### Fuente C — Captura humana y mercado

Hay datos que ningún sistema de la casa tiene, y hay que decirlo en vez de
rellenarlos:

- **Parámetros de mercado para el WACC**: tasa libre de riesgo (Rf), Beta, prima
  de mercado (ERP). Son externos y requieren una fuente y una fecha declaradas.
- **Métricas de proceso**: reportes comprometidos y entregados a tiempo,
  hallazgos de auditoría abiertos. Son del proceso interno de Finanzas.
- **La política de "efectivo ocioso"**: los saldos están; cuánto se considera
  ocioso es una decisión de tesorería, no un dato que se descubra.

---

## 3. Lo que YA está construido — reutilizar, no rehacer

| Archivo | Qué hace | Por qué importa |
|---|---|---|
| `erp/registro_conectores.py` | El "multicontacto" de ERPs. Forma canónica de cuentas y saldos. | Es la frontera. Nada fuera del conector conoce nombres de campo de SAP. |
| `erp/sap_b1.py` | Único conector implementado. Sesión, paginación, homologación. | Ya resuelve cuatro bugs de protocolo que no se ven razonando (ver §6). |
| `erp/clasificador_cuentas.py` | Clasifica cuentas por el **árbol del ERP** y el nombre de la raíz, en español o inglés. | No uses prefijos de código para clasificar. Ver §6. |
| `analisis_vertical_horizontal.py` | Balance, Estado de Resultados, análisis vertical y horizontal. | Ya maneja los signos de partida doble y las variaciones con base cero o negativa. |
| `razones_financieras.py` | Las razones del `Diccionario_KPIs` más liquidez. Saldos promedio, anualización, DuPont de 5 factores, semáforo. | **Buena parte de los KPIs principales ya está aquí.** Revísalo antes de escribir una fórmula. |
| `precision_pronostico.py` | Los cinco métodos de pronóstico, backtesting walk-forward, MAPE/MPE/RSFE/MAD. | Alimenta la pestaña `Precision_Pronostico` directamente. |
| `adaptador_formatos.py` | Resuelve encabezados en español/inglés, detecta fila de encabezado y orientación. | Úsalo para cualquier Excel que entre. No escribas otro parser. |
| `bitacora_actualizaciones.py` | Detecta cambios retroactivos a periodos ya cerrados. | Alimenta `Datos_Funcion`. Ver §5. |
| `verificar_cuadre.py` | Identidad contable + articulación entre estados. Exit 1 si falla. | **Correr antes de publicar cualquier cosa.** |

---

## 4. Qué construir, pestaña por pestaña

### `Datos_Financieros` — la base de todo
Las demás pestañas la referencian con `INDEX`. Alimentarla desde las fuentes A y
B. El contrato de columnas ya está en `finanzas/esquema_financiero.py`, que
distingue lo **capturado** de lo **derivado**: respétalo, es el que evita que
alguien capture a mano un campo que debería calcularse.

### `Seg_Principales` — ROE, ROIC, WACC, Spread/EVA, FCF, Deuda Neta/EBITDA
La mayoría sale de `razones_financieras.py`. El WACC necesita la fuente C para
Ke y **debería usar el Kd real de los financiamientos de HopDesk**, no una tasa
supuesta.

### `Seg_Derivados` — DSO, DPO, DIO, CCC, CTN/Ventas, D/E, tasas efectivas
**Consumir la antigüedad de saldos de HopDesk** en lugar de derivar del Balance.

### `Seg_Funcion` + `Datos_Funcion` — calidad del cierre
Ver §5, que es donde está el trabajo nuevo de verdad.

### `Precision_Pronostico`
Ya resuelto por `precision_pronostico.py`. **Advertencia honesta:** el archivo
fija el umbral verde en MAPE ≤ 5%. El backtesting real sobre los datos de
Networks da **15–17%**. Esa meta no es alcanzable con estos métodos y esta
serie; hay que decirlo, no ajustar el método hasta que dé 5%.

### `Dashboard_Direccion`, `Tablero_Finanzas`, `Desglose_KPIs`
Presentación: valor actual, meta, semáforo, y el desglose de variación del WACC.
`razones_financieras.METAS` y `semaforo()` ya existen.

---

## 5. `Datos_Funcion` — lo que se puede derivar y lo que no

Diez columnas. `bitacora_actualizaciones.py` produce honestamente tres y media.
**Las otras se entregan vacías y marcadas.**

| Columna | Origen | Estado |
|---|---|---|
| Días de cierre | Fecha de registro del último asiento del periodo | **Falta una pasada ligera** — ver abajo |
| Reportes comprometidos | Proceso interno | Captura |
| Reportes a tiempo | Proceso interno | Captura |
| Errores post-cierre | Bitácora: correcciones a periodo ya cerrado | **Derivado** |
| Reprocesos/correcciones | Bitácora: cualquier cambio a un periodo ya extraído | **Derivado** |
| Conciliaciones pendientes | `InternalReconciliations` de SAP | No extraído aún |
| Antigüedad conciliaciones | Ídem | No extraído aún |
| Hallazgos auditoría | Proceso interno | Captura |
| Efectivo ocioso | Saldos de efectivo + política de tesorería | **Parcial** |

**Para "Días de cierre"** hace falta una consulta adicional por mes a
`JournalEntries` pidiendo solo `$select=CreationDate,TaxDate` —sin las líneas
anidadas, que es lo que la hace pesada—. Días de cierre = fecha del último
asiento *registrado* para el periodo − fin del periodo. Es barata y no obliga a
reextraer nada.

---

## 6. Trampas ya descubiertas — no las repitas

1. **Paginación silenciosa.** Este Service Layer **no emite `@odata.nextLink`**:
   con `maxpagesize=200` devuelve 200 filas y se calla, aunque haya 337. El
   paginador "según la documentación de OData" entregaba catálogos incompletos
   **sin error**. Se pagina con `$skip` hasta página corta. *El bug más
   peligroso del proyecto.*
2. **`/$count` ignora `$filter`** en JournalEntries (138 filas reales → reportó
   2). La verificación de integridad solo aplica a consultas sin filtro.
3. **Nombres de campo:** es `AccountType`, no `AcctType`. No existe `Postable`.
4. **No clasifiques cuentas por el prefijo del código.** En Networks la
   numeración y el árbol están corridos un cajón: las cuentas `81*` (financieras)
   cuelgan de la raíz 700 y las `91*` (extraordinarias) de la raíz 800. El mapeo
   por prefijo acertaba **por coincidencia**, no por leer el plan de cuentas.
5. **El Balance es la última posición conocida hasta la fecha**, no el
   movimiento del mes, y necesita **saldo de apertura** y **resultado del
   ejercicio** o no cuadra.
6. **`ExchangeRates` no existe** como entidad en este servidor. Los tipos de
   cambio se piden con la acción `SBOBobService_GetCurrencyRate`. El error
   `-4006` significa "no hay tipo cargado", no "no tienes permiso".
7. **`-3000` es permiso; HTTP 400 es bug propio.** No mandes a nadie a tocar
   autorizaciones de SAP sin haber descartado primero que el error es tuyo.

---

## 7. Reglas que no se negocian

- **Nunca inventar un número.** Un dato que no se conoce va como `None`, no como
  cero: el cero afirma que no hubo reprocesos, que es una mentira distinta. Una
  meta que no se alcanza se reporta como no alcanzada.
- **Nunca forzar un cuadre.** Si el Balance no cuadra, se dice y se investiga.
- **Correr `verificar_cuadre.py` antes de publicar.** Devuelve exit 1.
- **Todo en español**, con el código preparado para i18n (diccionarios de
  términos, no cadenas incrustadas).
- **No mencionar "CFA" ni al CFA Institute** en ningún entregable, aunque el
  fundamento metodológico venga de ahí.
- **Lo específico de un cliente vive en diccionarios editables, no en `if`.**
  Networks es *un* cliente; el diseño apunta a varios (ver el párrafo de
  multiempresa en `erp/registro_conectores.py`).
- **La tenencia de usuarios y carpetas la resuelve HopDesk.** No construir aquí
  un segundo padrón de usuarios.

---

## 8. Arquitectura de ejecución

El servidor SAP está en IP privada. La extracción corre **local con VPN**, deja
un **snapshot en S3**, y la aplicación publicada **solo lee ese snapshot**. No es
un arreglo temporal: la app publicada nunca necesita credenciales del ERP, el
snapshot es auditable y reproducible, y el tablero sigue en pie cuando el ERP no.
Documentado en `erp/extraer_estados_financieros.py`.
