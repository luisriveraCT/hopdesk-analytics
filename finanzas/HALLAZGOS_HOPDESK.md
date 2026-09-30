# Hallazgos en HopDesk — auditoría del 2026-09-25

**Para quien vaya a corregirlos**, probablemente en una sesión sobre
`C:\Users\luisr\Antiguedad_App`, no aquí.

Esto es evidencia y diagnóstico, **no una receta**. En cada caso digo qué
observé, por qué creo que pasa y qué habría que confirmar antes de tocar nada.
Quien haga el arreglo conoce ese código mejor que yo y decidirá la forma.

No modifiqué ningún archivo de HopDesk. No leí valores de secretos, solo nombres
de variables.

---

## Lo primero: por qué "se siente frágil"

No es desorden. Son **dos ausencias** que generan casi todo lo demás:

1. **No hay un solo lugar que decida quién puede qué.** Hay once mecanismos
   independientes de autorización. Con once copias, cambiar una regla es apostar
   a cuántas encontraste — de ahí la sensación de que nada es seguro tocar.

2. **S3 no tiene transacciones y todo el modelo asume que sí.** Cada `save_*()`
   hace leer→mutar→sobrescribir sin bloqueo.

Todo lo de abajo son síntomas de una de esas dos.

---

## 🔴 Con consecuencia de seguridad

### 1. Las credenciales de ERP de un cliente pueden caer a las de otro
**`R/sap_api.R:88-94`**

Si `decrypt_secret()` falla —clave rotada, blob corrupto, dato de otro cliente—
el código emite un `message()` y **continúa con las credenciales globales del
`.Renviron`**. El comentario en `R/sap_api.R:31-34` lo declara como diseño
intencional (fallback legacy).

**Por qué importa ahora y no antes:** mientras Networks fuera el único cliente,
el fallback apuntaba a las credenciales correctas. Con un segundo cliente, un
fallo de descifrado lo conecta al SAP de Networks.

**Qué confirmaría antes de tocar:** si hay clientes hoy dependiendo del fallback
para operar (es decir, con `erp_connections.rds` vacío o sin migrar). Quitarlo de
golpe los deja sin conexión.

---

## 🟠 Rotos en silencio: reportan éxito y no hacen nada

Estos tres comparten causa: `isTRUE()` aplicado a un **vector**. `isTRUE()`
espera un escalar; con un vector devuelve un único `FALSE`, así que el filtro
siempre resulta vacío. No hay error, no hay aviso.

### 2. `deactivate_contact()` nunca desactiva
**`R/persistence.R:2299`** — `which(df$id == contact_id & isTRUE(df$active))`
devuelve `integer(0)` siempre. La función retorna `invisible(FALSE)` y quien la
llamó no distingue eso de "no encontré el contacto".

### 3. Las alertas de cupo de usuarios no se envían
**`R/persistence.R:2324-2326`** — mismo patrón sobre `contacts$active` y
`contacts$receives_limit_alerts`: la lista de destinatarios por el lado de
contactos siempre sale vacía.

**`R/persistence.R:2335`** — además, `isTRUE(hd_staff$can_manage_invites)` lee
una **columna que no existe** en `usuarios.rds`: los permisos viven en la columna
`permisos` como JSON. Así que el lado de staff también sale vacío.

Resultado combinado: `get_limit_alert_recipients()` (`:2312-2344`) devuelve
prácticamente siempre una lista vacía. **Vale la pena revisar si alguna vez llegó
una alerta de cupo.**

### 4. Los permisos de acceso entre clientes pueden "concederse" sin escribirse
**`R/persistence.R:2396-2404`** (`save_hop_requests`) y **`:2419-2426`**
(`save_hop_grants`)

Ambas envuelven la escritura en `tryCatch(..., error = function(e) warning(...))`
y devuelven `invisible(df)` pase lo que pase. **El llamador no puede distinguir
éxito de fallo.** Call sites afectados: `R/tiers_module.R:3186, 3252, 3271, 3337,
3368, 3544`.

**Síntoma esperable:** la interfaz confirma que se concedió un acceso, y el
acceso no funciona. Si eso te pasó alguna vez y lo atribuiste a caché, era esto.

---

## 🟡 Estructural: por qué cuesta tanto cambiar algo

### 5. Dieciséis de veinte permisos no se verifican en ningún lado
Definidos en **`R/auth.R:400-511`**. Los únicos lugares donde se comprueba alguno:

| Permiso | Dónde se verifica |
|---|---|
| `can_manage_empresas` | `R/empresas_module.R:241-242` |
| `can_view_payment_audit` | `R/pagos_audit_viewer_module.R:26` |
| `can_view_client_audit_logs` | `R/audit_log_viewer_module.R:878-879` |
| `can_manage_invites` | `R/persistence.R:2335` (y está roto, ver #3) |

Los otros dieciséis —`can_view_cobros`, `can_view_pagos`, `can_edit_invoices`,
`can_manage_users`, `can_jump_clients`…— se muestran como interruptores, se
guardan en disco, y **no aparecen en ningún `if` ni `req()`**.

No es solo trabajo desperdiciado: es un tablero de controles desconectados. Quien
administre va a creer que restringió algo.

### 6. La pantalla "Config. de Tiers" no afecta a la autorización
`tiers_config.rds` se escribe en **`R/tiers_module.R:3949`** y se lee **solo** en
**`R/tiers_module.R:674`**, para repintar sus propias casillas.
`auth_resolve_perms()` (**`R/auth.R:400`**) nunca lo lee. El propio comentario en
`R/tiers_module.R:659-668` lo admite.

### 7. Once mecanismos de autorización distintos
Los que más me llamaron la atención:

- **`R/auth.R:172` y `:193`** — `tier %in% c("principal","hopdesk")` escrito a
  mano **en el archivo que define los tiers**, en vez de usar su propio
  `is_staff_tier()`. Un tier de staff nuevo en `TIER_REGISTRY` no entraría al
  overlay de credenciales.
- **`R/settings/settings_hub.R:15`** y **`R/settings/settings_sincro.R:135`** —
  `tier %in% c("dev","admin")`: deja fuera de Configuración a `hopdesk` y
  `principal`, que son los tiers **más altos**.
- **`R/tiers_module.R:556-563`, `:603-609`, `:2738-2748`** — la validez de un hop
  grant se recalcula tres veces en el mismo archivo, con expresiones que no son
  idénticas (una captura `Sys.time()` antes, otra lo llama en línea).
- **`R/empresas_module.R:237`** vs **`R/audit_log_viewer_module.R:769`** — la
  misma operación contra clientes distintos: empresas resuelve permisos contra
  `effective_client_id()` (el cliente saltado) y el visor de auditoría contra
  `home_client_id()`. Con un staff en jump, empresas busca al usuario en el
  `usuarios.rds` ajeno, no lo encuentra y devuelve `FALSE` (`:240`).

### 8. Lost-update admitido, y el mitigante no corre en producción
**`R/global.R:181-190`** lo documenta con precisión: *"both S3 writes succeed, no
exception is raised anywhere, whichever process wrote last simply wins"*.

El único mitigante es un bloqueo de archivo en **`R/global.R:216-238`** que
arranca con `if (!identical(os_type,"windows")) return()`. Producción es
shinyapps.io, o sea Linux: **el bloqueo no se ejecuta nunca ahí**.

Sitios con el patrón: `R/persistence.R:252-272` (índice global de usernames),
`:2096-2116` (conteo de usuarios por cliente), `:2121-2141` (notificaciones),
`:2204-2229` (invitaciones), `R/tiers_module.R:3239-3252, 3362-3368, 3529-3544`
(hop grants).

---

## 🔵 Vale la pena revisar, menor urgencia

9. **Token de invitación con RNG no criptográfico** — `R/persistence.R:2186` usa
   `sample(c(letters, LETTERS, 0:9), 32, replace = TRUE)` (Mersenne Twister). Es
   la única credencial que crea cuentas nuevas.

10. **Dos algoritmos para el mismo campo** — `account_code` se genera con
    `sprintf("U%04d", nrow(usuarios) + 1L)` en `app.R:1020` (colisiona tras un
    borrado lógico) y con `max()+1` en `R/tiers_module.R:433-447`.

11. **Username generado puede quedar vacío** — `app.R:1013`:
    `tolower(gsub("[^a-z0-9]", "", invite$display_name))`. "José Ángel" → `jsngel`;
    un nombre de puros símbolos → `""`, y se guarda. Tampoco llama a
    `check_username_available()`.

12. **Reglas de contraseña incoherentes** — `R/tiers_module.R:807` y `:1119` piden
    ≥8 sin complejidad; `app.R:906-907` y `:988-989` piden ≥6 con dígito y símbolo.

13. **`assign("COMPANY_MAP", ..., envir = .GlobalEnv)` desde una sesión de
    usuario** — `app.R:1169` y `:1172`. En el despliegue compartido `hd-admin`, la
    sesión del cliente A reescribe el mapa global que lee la sesión del cliente B.

14. **Sesiones de ERP indexadas solo por iniciales** — `R/sap_api.R:18`: dos
    clientes con una empresa "NG" comparten sesión SAP.

15. **Hashes de producción copiados a desarrollo** — `R/global.R:88-142`
    (`.hopdesk_sync_dev_users_from_prod`) copia `usuarios.rds` de producción al
    bucket de desarrollo al arrancar, si existe `.Renviron.local`.

16. **Una sola llave AWS con acceso a todos los prefijos.** Hay cuatro notas
    "Future IAM" distintas (`R/persistence.R:20-27, 163-165, 206-209, 2062-2066`)
    y dos políticas escritas y **no aplicadas** (`scripts/iam_policy_client.json`,
    `scripts/iam_policy_hd_admin.json`). Hoy el aislamiento entre clientes es
    convención de código, no permiso de infraestructura.

---

## Dimensión

| | |
|---|---|
| Código de tenencia/auth en producción | **≈ 8,400 líneas** en ~17 archivos |
| `R/tiers_module.R` solo | 3,971 líneas (**47%**) |
| Scripts operativos | 594 líneas |
| Pruebas | ≈ 3,800 líneas |

`R/tiers_module.R` es el punto único de reemplazo con mayor retorno.

---

## Mi lectura, para lo que valga

Los puntos 2, 3 y 4 son **arreglos chicos y acotados** que no requieren tocar
arquitectura. El 1 es chico también, pero conviene confirmar antes quién depende
del fallback.

Los puntos 5 a 8 no se arreglan con parches: son la arquitectura. La ruta que
propuse —y que ya está construida y probada en
`finanzas/configuracion/`— es separar **identidad** de **configuración**, empezar
por la configuración (que es la parte chica), y dejar la identidad donde está
hasta que la nueva capa se haya ganado la confianza operando. El plan por etapas
está en `PLAN_UNIFICACION.md`.
