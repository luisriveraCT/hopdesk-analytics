# Cómo sincronizar Analítica Financiera — estado actual y qué falta

**Para quien vaya a montar la sincronización.** Documento de entrega, no de
referencia: dice qué está construido, qué no, y por qué está así.

Resumen en tres líneas: el código ya sabe leer y escribir en S3, con escritura
concurrente segura y secretos cifrados. **No está activado.** Hoy todo vive en
el disco de una laptop, y por eso nada se sincroniza.

---

## 1. Lo que ya está hecho

### Hay DOS usos de S3, y no son el mismo

Esto es lo primero que hay que tener claro, porque mezclarlos sería un problema
de seguridad:

| | **Bucket de datos del tablero** | **Almacén de configuración** |
|---|---|---|
| Nombre | `hopdesk-analytics-dashboard` | *(no existe todavía)* |
| Qué guarda | `data/rows-2020.json` … `rows-2026.json` (~8 MB) | configuración, entradas manuales, bitácora, secretos |
| Quién lo lee | el navegador de cualquiera que abra el tablero | solo el código, nunca el navegador |
| Acceso | **lectura pública** | **tiene que ser privado** |
| Estado | funcionando | **local, en una laptop** |
| Código | `dashboard/publicar.py` | `finanzas/configuracion/almacen.py` |
| Perfil AWS | `facturacion-dashboard` | por definir |

El primero es público a propósito: son los chunks de facturación que la página
pide por URL. El segundo **no puede ir ahí**. Guarda los identificadores de las
empresas, las URLs de conexión al ERP, las credenciales cifradas y una bitácora
con nombres de personas.

> Hay un `hopdesk-analytics-dashboard` y existe además el bucket de HopDesk. Se
> decidió explícitamente **no reciclar** el bucket ni las llaves de HopDesk para
> este desarrollo. El perfil `facturacion-dashboard` en `~/.aws/credentials` es
> el dedicado.

### El almacén ya está escrito y probado

`finanzas/configuracion/almacen.py` tiene dos implementaciones con la misma
interfaz:

- `AlmacenLocal` — carpetas en disco. **Es la que está activa hoy.**
- `AlmacenS3` — el bucket. Escrita, sin usar.

Las dos hacen lo mismo: `leer(ruta) → (datos, version)` y
`escribir(ruta, datos, version_esperada)`.

**La escritura es una comparación e intercambio atómico.** En S3 se hace con el
PUT condicional de AWS:

```python
cond = ({'IfMatch': version_esperada} if version_esperada
        else {'IfNoneMatch': '*'})
```

Si alguien más escribió entre que leíste y que escribes, S3 rechaza tu PUT y
`actualizar_con_reintento()` vuelve a leer y reintenta sobre lo nuevo.

Esto importa más de lo que parece: **dos personas capturando a la vez en la
hoja de entradas es el caso normal, no el raro.** Sin esa comprobación, la
segunda en guardar borraría el trabajo de la primera sin que ninguna se entere.

### Los secretos ya van cifrados

Las credenciales del ERP se guardan con **AES-256-GCM**. Comprobado — así se ve
uno de los archivos:

```json
{"alg": "AES-256-GCM", "datos": "<texto cifrado>", "nonce": "<nonce>", "v": 1}
```

La llave maestra **no está en el repositorio**. Se lee de la variable de entorno
`HOPDESK_SECRETS_KEY`. De ella se deriva, con HKDF, una llave por cliente, y el
id del cliente entra como dato autenticado — así un archivo cifrado para un
cliente no se puede descifrar como si fuera de otro aunque alguien lo copie de
una carpeta a otra.

### Activarlo es una variable de entorno

`repositorio.almacen_por_defecto()` decide dónde vive todo:

```python
bucket = os.environ.get('ALMACEN_S3_BUCKET', '').strip()
if not bucket:
    return AlmacenLocal(raiz_local())
return AlmacenS3(bucket, perfil=..., region=..., prefijo_base=...)
```

```
set ALMACEN_S3_BUCKET=nombre-del-bucket-privado
set ALMACEN_S3_PREFIJO=config
set ALMACEN_S3_PERFIL=facturacion-dashboard
set ALMACEN_S3_REGION=us-east-1
```

**Sin la variable se usa el disco, y es a propósito.** Quien clone el proyecto y
corra una prueba no debe tocar el almacén compartido por omisión. La degradación
va en esa dirección y nunca en la contraria: no existe ningún "no pude hablar
con S3, guardo en disco", porque eso sí produce dos verdades.

---

## 2. Dónde está el problema, exactamente

Son **dos** problemas distintos. Conviene no confundirlos porque se resuelven
por separado y el primero es mucho más fácil.

### Problema A — el almacén está en una laptop

Hoy `ALMACEN_S3_BUCKET` no está definida. Todo esto vive en
`finanzas/datos_config/` de una sola máquina:

```
clientes/9402c520.../configuracion.json         empresas, ERP, metas, supuestos
clientes/9402c520.../entradas_manuales.json     lo capturado a mano
clientes/9402c520.../bitacora_cambios.json      quién tocó qué y por qué
clientes/9402c520.../secretos/...               credenciales cifradas
clientes/indice.json
```

Nadie más puede leerlo ni escribirlo. **Esta es la razón de fondo por la que
nada se sincroniza**, antes que cualquier cosa de la interfaz.

**Qué hace falta:** un bucket privado, un usuario IAM con permiso de
lectura/escritura solo sobre ese prefijo, y las cuatro variables puestas donde
corra el proceso. El código no se toca.

Es importante que el usuario IAM tenga permitido `s3:PutObject` **con
condiciones** — la escritura condicional necesita que el `ETag` viaje de vuelta,
que es el comportamiento normal de S3, pero conviene no poner una política que
lo bloquee.

### Problema B — el navegador no puede escribir

Aunque el almacén esté en S3, la página **sigue sin poder guardar sola**.

El tablero es un archivo HTML estático en Posit Connect Cloud. Para escribir en
S3 desde el navegador harían falta credenciales dentro de la página, y la página
la abre cualquiera del equipo. Eso no se hace.

Por eso hoy la hoja de captura:

1. edita una copia de trabajo en el navegador (`localStorage`),
2. exporta un archivo JSON,
3. y alguien corre:
   ```
   python finanzas/entradas.py --aplicar entradas-2026-09-26.json --autor "Nombre"
   ```

**Este es el paso que no va a hacer nadie.** El diagnóstico es correcto: un
proceso que depende de que una persona recuerde correr un comando es un proceso
que deja de correrse.

---

## 3. Cómo cerrar el problema B

Tres caminos, de menos a más trabajo. **Los tres requieren resolver A primero.**

### Opción 1 — Un endpoint de escritura (lo que recomendaría)

Una función pequeña —Lambda detrás de API Gateway, o lo que ya usen— que reciba
el lote de cambios y haga exactamente lo que hoy hace `entradas.py --aplicar`.

La hoja de captura deja de exportar un archivo y hace un `POST`.

Lo que hay que respetar del diseño actual, y no es negociable porque es lo que
hace auditable la captura:

- **Validar en el servidor, no en el navegador.** `entradas_manuales.validar()`
  ya tiene las reglas: el campo tiene que existir, una sobrescritura exige
  motivo escrito, y el valor tiene que caer en su rango. Esa última atrapa el
  error de captura más silencioso que existe, que es el factor 100 — escribir 18
  donde va 0.18.
- **El autor es obligatorio.** Sale de quien esté autenticado en Connect, no de
  un campo que el usuario llene.
- **Escribir con la comparación de versión**, no con un PUT a secas.
- **Registrar en la bitácora**, incluidas las consultas.

Reutiliza el módulo tal cual: la lógica ya está separada de la línea de comandos
a propósito.

### Opción 2 — Que el tablero deje de ser estático

Convertirlo en una aplicación con servidor. Resuelve la escritura de raíz, pero
es otro despliegue, otra forma de operarlo y otra cosa que mantener. Solo tiene
sentido si de todas formas van a necesitar sesión de usuario.

### Opción 3 — Un proceso programado

Dejar el archivo exportado en una carpeta vigilada y aplicarlo solo cada hora.
Es el menor trabajo, pero la persona que captura no sabe si su cambio entró
hasta la siguiente corrida, y cuando algo se rechaza se entera tarde o no se
entera. Para capturas ocasionales alcanza; para trabajo diario no.

---

## 4. El orden que sugiero

1. **Crear el bucket privado y el usuario IAM.** Media hora.
2. **Poner las cuatro variables y migrar lo que hay en disco.** Copiar
   `finanzas/datos_config/clientes/` al prefijo del bucket. Verificar con:
   ```
   python finanzas/configuracion/configurar.py --mostrar
   python finanzas/entradas.py --ver
   ```
   Los dos imprimen dónde están leyendo (`descripcion_almacen()` existe justo
   para eso: correr contra el disco creyendo que se corre contra el bucket es el
   error que se quiso hacer imposible de cometer sin darse cuenta).
3. **Decidir dónde vive `HOPDESK_SECRETS_KEY`** para los procesos que no son la
   laptop. Hoy se lee del entorno, del `.Renviron` de HopDesk o de un `.env`
   local. Un secreto gestionado (AWS Secrets Manager o el equivalente que usen)
   es lo que corresponde.
4. **Recién entonces, el endpoint de escritura.**

Hacerlo al revés —montar el endpoint contra un almacén que sigue en una laptop—
no funciona.

---

## 5. Un asunto de seguridad que conviene atender de paso

**Las cinco empresas comparten exactamente la misma contraseña de SAP.**

Está documentado como hallazgo en la revisión con el equipo contable. Filtrarse
una es filtrarse el grupo entero, y rotarla obliga a rotar las cinco a la vez —
que es justamente la fricción que hace que no se rote nunca.

Si se va a tocar la gestión de credenciales para montar esto, es el momento.

---

## 6. Dónde está cada cosa

| Qué | Archivo |
|---|---|
| El almacén, local y S3, con la escritura condicional | `finanzas/configuracion/almacen.py` |
| Qué almacén se usa y cómo se decide | `finanzas/configuracion/repositorio.py` → `almacen_por_defecto()` |
| Cifrado de credenciales | `finanzas/configuracion/secretos.py` |
| Reglas de validación de la captura | `finanzas/entradas_manuales.py` → `validar()` |
| Lo que haría el endpoint | `finanzas/entradas.py` → `aplicar()` |
| Bitácora | `finanzas/bitacora_cambios.py` |
| Subida de los datos públicos del tablero | `dashboard/publicar.py` |
| Publicación del HTML | `refrescar.py` (raíz) |
| Por qué cada cosa está así | `FUNDAMENTOS.md` |

Todo el código lleva su razonamiento en el encabezado. Los comentarios cuentan
**qué salió mal antes** — no son decoración, y conviene leerlos antes de
cambiar algo.
