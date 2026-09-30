# Riesgos y capacidad de crecer

Evaluación del 2026-09-29, sobre el estado real del código medido ese día. No es
una lista de buenas prácticas: cada riesgo trae la evidencia que lo sostiene en
este repositorio y qué cuesta atenderlo ahora contra atenderlo después.

---

## Dónde estás hoy, en números

| | |
|---|---|
| Python | 13,324 líneas |
| HTML del tablero | 5,728 líneas, de las cuales **4,869 son un solo `<script>`** |
| Pruebas | **21,239**, todas pasan |
| `index.html` publicado | 1,536 KB, de los cuales ~1,172 KB son JSON incrustado |
| Datos que baja **cada** visitante | 7.9 MB (155,434 facturas) |
| **Líneas bajo control de versiones** | **0** |
| Entornos | 1 (producción) |
| Dependencias de terceros en la página | 3 librerías de cdnjs + Google Fonts, **sin SRI** |

Dos cosas que conviene decir antes de la lista, porque cambian cómo se lee:

**Los cimientos son mejores que la infraestructura.** 21,239 pruebas de propiedad
sobre datos reales, una capa de configuración con comparación-e-intercambio de
verdad, secretos con AES-256-GCM y clave derivada por cliente, tres verificadores
escritos a mano para los fallos que este diseño produce, y una disciplina de
documentación que explica el *porqué* de cada decisión. Eso es más difícil de
construir que cualquiera de los arreglos de abajo.

**Y casi nada de lo que sigue es un error.** Las decisiones que hoy limitan
fueron correctas para lo que la app era: un tablero interno, de un cliente, que
ve un equipo que ya tiene acceso a todo. Dejan de serlo en cuanto hay varios
clientes y usuarios con alcances distintos. Eso no es deuda técnica; es un
cambio de producto.

---

## Registro de riesgos

### 1. No hay control de versiones — **CRÍTICO**

**Evidencia.** `Analitica_Financiera` no es un repositorio git. HopDesk sí lo es,
así que no es falta de costumbre: es la excepción. Hoy mismo otra sesión editó
`configurar.py` y `entradas.py`, y solo lo detecté comparando fechas de archivo.

**Qué implica.** No hay historial, no hay forma de volver atrás, no hay revisión,
no hay ramas, no hay culpa de línea. Dos personas —o dos sesiones de IA—
trabajando a la vez es cuestión de suerte.

**Sobre tu pregunta de las cien mil líneas:** no se puede. 13,324 líneas sin git
ya es frágil. Y todo lo demás de esta lista depende de esto: CI, entornos,
revisión, despliegue reproducible y el despliegue de apps de Connect Cloud —que
publica desde un repo— empiezan todos aquí.

**Costo ahora:** una tarde, contando el `.gitignore` (ya existe) y limpiar lo que
no debe subir. **Costo después:** crece con cada línea y con cada persona.

---

### 2. No hay entorno de prueba — **ALTO**

**Evidencia.** Lo único parecido es `construir.py --modo local|s3`. Y ya falló:
se publicó un `index.html` construido en modo local, cuyas rutas relativas no
existen en Connect, y el tablero salió en ceros con la barra de carga en verde.
Nadie pudo distinguirlo de un periodo sin facturas.

Le puse una guardia a `refrescar.py` y `loadAll()` dejó de mentir, pero eso es un
parche a la ausencia de entornos: cada cambio se sigue probando en producción.

**Costo ahora:** un segundo contenido en Connect y un bucket (o prefijo) de
pruebas. **Costo después:** el primer error que vea un cliente.

---

### 3. El navegador recibe **todos** los datos — **ESTRUCTURAL**

Este es el que bloquea "muchos usuarios", y el que hay que entender antes de
elegir nada más.

**Evidencia.** `CHUNKS` baja los 7.9 MB con las 155,434 facturas a cada
visitante. `meta.json`, `kpis.json` y `finanzas.json` van **incrustados** en el
HTML. Todo el cálculo de agregación ocurre en el navegador (`applyFilters`,
`aggregateRows`).

**Qué implica.** No puede haber permisos por fila, por empresa ni por cliente. Si
alguien no debe ver NTS, no hay forma de impedirlo: el dato ya está en su
máquina. El modo Montos que construimos oculta cifras **en la pantalla**, no en
los datos — quien abra las herramientas del navegador las lee enteras. Está bien
para lo que es (evitar que se vean en una presentación) y no es un control de
acceso.

**Qué cuesta cambiarlo.** Mover la agregación al servidor. Es el cambio más
grande de esta lista y el que convierte el producto en un SaaS de verdad. No hay
atajo: mientras el navegador reciba el dato completo, "usuarios con permisos
distintos" es una etiqueta, no un mecanismo.

**Cuándo.** El día que haya un segundo cliente, o un usuario que no deba ver
todo. Ni antes ni después.

---

### 4. Muro de volumen en el navegador — **MEDIO, con número**

**Evidencia.** Los arreglos tipados de `R` ocupan ~42 bytes por fila, más un
string de folio por fila (~40–60 B con sobrecarga). 155,434 facturas ≈ **15 MB**
en memoria.

**El muro.** Alrededor de **1 a 2 millones de documentos** el navegador empieza a
sufrir y en móviles antes. Al ritmo actual (~30,000 facturas al año) el cliente
de hoy tiene décadas de margen. **Un cliente nuevo con más volumen lo alcanza el
primer día.** Es un muro del modelo de negocio, no de Networks.

Se resuelve con lo mismo que el riesgo 3: agregar en el servidor.

---

### 5. Dos productos, dos identidades — **ALTO**

**Evidencia.** HopDesk ya tiene usuarios, tiers y permisos. Este tablero no tiene
ninguno. El propio código de la capa de configuración documenta cómo terminó el
sistema anterior: **once mecanismos de autorización distintos**, y 16 de 20
permisos que se mostraban, se guardaban y no se consultaban en ningún `if`.

**Qué implica.** Si aquí se mete Firebase o Cognito por su cuenta, habrá dos
sistemas de identidad para las mismas personas, y la pregunta "¿quién puede ver
los montos de NTS?" tendrá dos respuestas que se separarán.

**La decisión de identidad se toma una vez, para los dos productos.** Y no antes
de que existan git y un entorno de prueba, porque es un cambio que se revisa.

---

### 6. El almacén es un documento JSON por cliente — **MEDIO**

**Evidencia.** `entradas_manuales.json` y `bitacora_cambios.json`: un archivo
cada uno, con comparación-e-intercambio por ETag. La bitácora ya se recorta a 400
asientos para poder publicarla.

**Dónde se rompe.** El CAS es correcto y es la decisión buena a esta escala. Con
decenas de personas capturando a la vez se vuelve contención: cada escritura
reintenta sobre el documento entero, y la probabilidad de conflicto crece con el
cuadrado de los escritores. La bitácora, además, crece sin límite en un archivo.

**Umbral:** decenas de escritores concurrentes. A partir de ahí, base de datos.
No antes: cambiarla hoy sería pagar complejidad por un problema que no tienes.

---

### 7. Dependencias de terceros sin verificación de integridad — **MEDIO**

**Evidencia.** Tres librerías desde `cdnjs.cloudflare.com` (jsPDF, autotable,
ExcelJS) y fuentes desde Google, todas sin atributo `integrity`.

**Qué implica.** Dos cosas distintas. Si cdnjs no responde, las descargas dejan
de funcionar. Si cdnjs se compromete, se ejecuta código arbitrario **en la página
que muestra los estados financieros** — y podría leerlos y mandarlos a cualquier
parte.

**Costo ahora:** una hora. O se añade `integrity=` con el hash de cada archivo, o
se sirven desde tu propio bucket, que además quita la dependencia externa.
Es el mejor arreglo por peso de esta lista.

---

### 8. Un solo archivo de 4,869 líneas de JavaScript — **MEDIO**

**Evidencia.** Todo el tablero vive en un `<script>` de `plantilla.html`.

**Por qué funciona hoy.** Por algo poco común: un índice de funciones mantenido a
mano y tres verificadores propios —alcance, idiomas, sintaxis— que atrapan
exactamente los fallos que un archivo así produce. Uno de ellos nació porque un
bloque quedó dentro de otra función y dejó una pestaña en blanco sin error.

**Dónde se rompe.** A esta escala, bien. A 50,000 líneas, no: los conflictos de
edición se vuelven diarios y ningún editor ayuda.

**Pero no lo dividas todavía.** El costo aparece cuando haya más de una persona
tocándolo a la vez, y eso llega junto con git y equipo. Partirlo antes cambia un
problema que no tienes por uno que sí (un paso de construcción).

---

### 9. Las pruebas no corren solas — **MEDIO**

21,239 pruebas que solo se ejecutan si alguien se acuerda. Con git, la
integración continua es gratis y cierra el hueco. Sin git no hay dónde ponerla.

Y una limitación que conviene saber: son pruebas de propiedad sobre los cálculos.
**No cubren la pantalla.** Para verificar el modo de montos y las descargas hubo
que manejar un navegador sin interfaz desde fuera. Si la interfaz va a crecer,
esa clase de prueba hay que incorporarla al repositorio, no improvisarla.

---

### 10. La clave maestra vive en una laptop — **MEDIO**

Los secretos del ERP están bien cifrados (AES-256-GCM, clave derivada por cliente
con HKDF, y falla en vez de caer a credenciales globales — que es el error del
sistema anterior). Pero la clave maestra está en el entorno de una máquina. Si se
pierde, las credenciales del ERP son irrecuperables; si se filtra, no hay
rotación documentada.

**Costo ahora:** un gestor de secretos (AWS Secrets Manager o Parameter Store) y
un procedimiento de rotación escrito.

---

## Respuestas a lo que preguntaste

**Cookies y cache.** Hoy no hay sesión, así que no hay cookies; no es un riesgo,
es una consecuencia de no tener servidor. Y el cache que va a importar no es el
del navegador sino el de las agregaciones del lado del servidor. Los chunks
tienen `max-age=60` a propósito, para que nadie vea datos viejos sin saberlo.
**Llega solo cuando haya servidor y es barato.**

**Encriptación.** En reposo, los secretos están bien. En tránsito, TLS lo dan
Connect y S3. Lo que falta: los chunks del tablero están en un bucket de lectura
pública **a propósito**, porque la página no lleva credenciales. Eso es aceptable
mientras los datos sean de un cliente que ya los comparte con todo su equipo, y
deja de serlo con el segundo cliente. Se arregla con el mismo movimiento del
riesgo 3.

**Gestión de usuarios.** Tres opciones y ninguna se decide aquí sola:
- *Connect Cloud* autentica, pero no es una plataforma de usuarios de un SaaS: no
  tiene planes, ni alta de clientes, ni permisos por cliente.
- *Cognito* es nativo de AWS, donde ya vive el almacén, y es barato a escala.
- *Firebase* se trabaja mejor, pero mete un segundo proveedor de nube y dos
  facturas.

Lo importante no es cuál, es **que sea una sola para HopDesk y para esto**
(riesgo 5). Decidirlo aquí en aislamiento es exactamente cómo se llega a once
mecanismos de autorización.

**Cien mil líneas.** El límite no es el lenguaje ni el archivo: es que hoy no hay
historial, ni revisión, ni pruebas automáticas al integrar. Con git + CI +
entornos, 100,000 líneas es cuestión de tiempo. Sin eso, 20,000 ya duele.

---

## El orden en que conviene hacerlo

No es una lista de deseos: cada paso hace posible el siguiente.

1. **Git.** Todo lo demás cuelga de aquí. Una tarde.
2. **Integración continua** que corra las 21,239 pruebas y los verificadores.
   Gratis una vez que hay repositorio.
3. **`integrity=` o librerías propias.** Una hora, cierra el riesgo 7.
4. **Entorno de prueba** separado de producción.
5. **Servidor** (la app que ya discutimos). Desbloquea sesión, permisos, cache y
   escritura desde el navegador, todo de una vez.
6. **Identidad unificada con HopDesk.** Una sola decisión, dos productos.
7. **Agregación en el servidor.** El cambio grande. Solo cuando haya un segundo
   cliente o usuarios con alcances distintos.
8. **Base de datos.** Solo cuando el documento JSON por cliente duela de verdad.
9. **Gestor de secretos y rotación.**

## Lo que NO hay que hacer todavía

Partir el HTML en módulos, meter un framework de interfaz, migrar a base de
datos, separar en servicios. Todo eso cuesta semanas, y **ninguno resuelve
ninguno de los diez riesgos de arriba**. Son las respuestas correctas a problemas
que este proyecto todavía no tiene.
