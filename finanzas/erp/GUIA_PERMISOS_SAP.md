# Guía para desbloquear los permisos SAP

**Para:** Luis Rivera · **Objetivo:** dejar la extracción automática de Estados
Financieros funcionando al 100%, sin descargas manuales.

Esta guía es autosuficiente: trae qué pedir, cómo aplicarlo, y **cómo
comprobarlo tú mismo** después de cada cambio, sin tener que preguntarme si ya
quedó. Cuando el verificador te diga que todo pasó, avísame y seguimos.

---

## 0. Lo que necesitas saber de entrada

| Dato | Valor |
|---|---|
| Usuario de integración | **`LARivera`** |
| Servidor SAP | `192.168.14.131:50000` (Service Layer) |
| Tipo de acceso requerido | **Solo lectura.** Nada de escritura, en ningún módulo. |
| Bases de datos | `SBO_CROSSDOCKING`, `SBO_NETWORKSSS`, `SBO_LOGISTICS`, `SBO_REALTORS`, `SBO_TRUCKING` |

> ### ⚠️ Lo más importante de toda la guía
> **Los permisos en SAP B1 se configuran POR BASE DE DATOS.** Otorgarlos en una
> empresa no los otorga en las otras cuatro. Este es el error que hace perder
> más tiempo: se configura una, se prueba, "ya quedó", y luego la extracción
> falla en las otras. El verificador prueba las cinco justamente por eso.

---

## 1. Tu herramienta de comprobación

Corre esto las veces que haga falta, después de cada cambio:

```bash
cd "C:\Users\luisr\Analitica_Financiera\finanzas\erp"
python verificar_permisos.py
```

Te dice, empresa por empresa, qué permiso funciona y cuál falta — y para cada
uno que falte, **en qué menú de SAP se otorga**.

Variantes útiles:

```bash
python verificar_permisos.py --empresa NG     # una sola empresa (más rápido)
python verificar_permisos.py --criticos       # solo lo indispensable
```

**Cómo leer el resultado:**

- `OK` → ese permiso ya funciona.
- `FALTA ... SIN PERMISO (-3000)` → falta autorización en SAP. Es lo que vamos a resolver.
- `SIN RED` → no es un permiso: es la VPN. Conéctala y repite.

Al final imprime **"TODO EN ORDEN"** cuando ya no falta nada. Ese es el momento
de avisarme.

---

## 2. Qué permisos pedir, y para qué sirve cada uno

Están en tres niveles. Los **críticos** son los que bloquean todo; los demás
amplían el análisis pero no impiden arrancar.

### 🔴 Críticos — sin estos no hay Estados Financieros

| Permiso | Ruta en SAP B1 | Para qué |
|---|---|---|
| **Plan de cuentas** | Finanzas → Plan de cuentas<br>*(Financials → Chart of Accounts)* | El catálogo de cuentas. Es la columna vertebral: sin él no se puede armar ni el Balance ni el Estado de Resultados. |
| **Asientos** | Finanzas → Asiento<br>*(Financials → Journal Entry)* | Las pólizas. De aquí salen **todos** los saldos mensuales desde 2020. |

### 🟡 Importantes — completan el análisis

| Permiso | Ruta en SAP B1 | Para qué |
|---|---|---|
| Socios de negocios | Socios de negocios → Datos maestros de socio de negocios | Analizar cartera y cuentas por pagar por contraparte. |
| Monedas | Gestión → Definiciones → Finanzas → Monedas | Facturan en USD además de MXN; sin esto no hay análisis multimoneda. |
| Tipos de cambio | Gestión → Tipos de cambio e índices | Convertir y medir exposición cambiaria. |
| Pagos recibidos | Bancos → Pagos recibidos | Flujo de efectivo real de entrada (cobranza), no solo lo facturado. |
| Pagos efectuados | Bancos → Pagos efectuados | Flujo de efectivo real de salida. |

### 🟢 Útiles — habilitan análisis adicionales

| Permiso | Ruta en SAP B1 | Para qué |
|---|---|---|
| Centros de beneficio | Finanzas → Contabilidad de costes → Centros de beneficio | Rentabilidad por unidad de negocio. |
| Dimensiones | Finanzas → Contabilidad de costes → Dimensiones | Segmentación adicional de costos. |
| Partidas de flujo de efectivo | Finanzas → Definiciones → Partidas de flujo de efectivo | SAP trae una taxonomía nativa de flujo. Si está configurada, nos ahorra clasificar a mano. |
| Escenarios de presupuesto | Finanzas → Presupuesto → Escenarios de presupuesto | Comparar presupuesto contra real. |
| Cheques para pago | Bancos → Pagos efectuados → Cheques para pago | Detalle de pagos con cheque. |

---

## 3. Cómo se aplican en SAP B1

1. Entra al **cliente de SAP Business One** con un usuario que sea
   **superusuario** (solo un superusuario puede modificar autorizaciones).
2. Conéctate a **la primera base de datos** (por ejemplo `SBO_NETWORKSSS`).
3. Ve a:
   **Gestión → Inicialización de sistema → Autorizaciones → Autorizaciones generales**
   *(Administration → System Initialization → Authorizations → General Authorizations)*
4. En la lista de usuarios de la izquierda, selecciona **`LARivera`**.
5. En el árbol de la derecha, busca cada permiso de la sección 2 y ponlo en
   **`Sólo lectura`** *(Read Only)*.
6. **Actualizar / OK.**
7. **Cambia de base de datos y repite los pasos 3-6 en las otras cuatro.**

### Atajo que puede ahorrarte mucho tiempo

En vez de ir permiso por permiso, en el árbol de autorizaciones puedes poner
**el módulo completo de `Finanzas` en `Sólo lectura`** (y lo mismo con
`Bancos`). Eso cubre de un golpe casi todo lo de las tres tablas. Como todo es
solo lectura, el riesgo es el mismo que dar los permisos individuales.

### Si el árbol no muestra alguna opción

Algunas instalaciones no muestran ciertos nodos si el módulo no está en uso.
Si no encuentras "Partidas de flujo de efectivo", por ejemplo, sáltalo: es de
nivel 🟢 y no bloquea nada.

---

## 4. Cómo probar, paso a paso

**Prueba 1 — después de configurar la primera empresa:**

```bash
python verificar_permisos.py --empresa NG
```

Esperado: `ChartOfAccounts` y `JournalEntries` en `OK`.

**Prueba 2 — después de configurar las cinco:**

```bash
python verificar_permisos.py
```

Esperado: `TODO EN ORDEN — no falta ningún permiso.`

**Prueba 3 — la prueba de fuego (extracción real, una empresa, rápida):**

```bash
python extraer_estados_financieros.py --empresa NG --sin-saldos
```

Esto baja solo el catálogo de cuentas (segundos, no minutos). Si ves algo como
`1,234 cuentas` y se guarda `cuentas_NG.json`, el permiso crítico #1 está bien
de verdad, no solo "responde".

**Prueba 4 — extracción completa de una empresa:**

```bash
python extraer_estados_financieros.py --empresa NG --desde 2025
```

Empieza por 2025 (un año) para medir cuánto tarda antes de lanzar los seis años
completos. Verás una barra de progreso mes por mes.

Si esto corre bien, **ya está todo listo** y puedes avisarme.

---

## 5. Qué esperar cuando ya funcione

```bash
# La corrida completa: 5 empresas, 2020 a hoy
python extraer_estados_financieros.py --todas --desde 2020
```

- Es **reanudable**: cada mes descargado se guarda en caché. Si se corta la red
  a medio camino, vuelves a correr el mismo comando y retoma donde se quedó en
  lugar de empezar de cero.
- La primera corrida es la lenta (son ~70 meses × 5 empresas). Las siguientes
  solo bajan los meses nuevos.
- Produce, en `finanzas/datos_erp/`: `cuentas_<EMPRESA>.json` y
  `saldos_<EMPRESA>.json` por cada una.

---

## 6. Problemas frecuentes y qué significan

| Lo que ves | Qué es realmente | Qué hacer |
|---|---|---|
| `SIN RED` / ConnectTimeout | No es permiso: no hay ruta al servidor. | Conecta la VPN. |
| `login falló` con red OK | La contraseña del usuario cambió. | Actualizar `SAP_*_PASSWORD` en el `.Renviron` de HopDesk. |
| `-3000` en un solo endpoint | Ese permiso específico falta. | Otorgarlo según la tabla de la sección 2. |
| `-3000` en todo, en una sola empresa | Se configuró en las otras bases pero no en esa. | Repetir en esa base. |
| Funciona y de repente deja de funcionar | En SAP, **cambiar la licencia de un usuario puede reiniciar sus autorizaciones**. | Volver a correr el verificador y reaplicar. |
| `Cuentas marcadas como OTRO` al extraer | No es error: son cuentas cuyo código no encaja en el plan estándar. | Mándame la lista y ajusto el mapeo. No las voy a clasificar adivinando. |

---

## 7. Qué NO hace falta pedir

Para evitar que la solicitud se frene por parecer invasiva, conviene ser claro
sobre lo que **no** se está pidiendo:

- **Ningún permiso de escritura.** Todas las llamadas son de lectura (GET); las
  únicas excepciones son el inicio y cierre de sesión.
- **Ningún acceso directo a la base de datos.** Todo pasa por el Service Layer,
  que respeta las autorizaciones de SAP.
- **Ningún usuario nuevo.** Se usa el mismo `LARivera` que ya opera HopDesk.
- **Ninguna licencia adicional.** El usuario ya existe y ya se conecta.

---

## 8. Cuando termines

Avísame con el resultado de:

```bash
python verificar_permisos.py
```

Si dice **TODO EN ORDEN**, lanzo la extracción completa y armamos el análisis
vertical y horizontal sobre datos reales. Si quedaron permisos 🟡 o 🟢
pendientes pero los 🔴 ya pasaron, también avísame: podemos arrancar con el
análisis base y sumar el resto después.
