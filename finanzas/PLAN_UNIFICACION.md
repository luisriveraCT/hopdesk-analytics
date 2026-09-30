# Plan de unificación — de dos sistemas a uno

**Estado: la Etapa 0 está hecha.** Lo demás es plan, no promesa.

---

## El principio que ordena todo

**Identidad ≠ configuración.** Son dos problemas distintos que el sistema
anterior mezcló, y esa mezcla es el origen de sus 8,400 líneas con once
mecanismos de autorización.

| | Qué es | Dónde vive hoy |
|---|---|---|
| **Identidad** | Quién eres: usuario, contraseña, sesión, tier | HopDesk |
| **Configuración** | Qué clientes hay, sus empresas, qué ERP, credenciales del ERP, retención | **Aquí** (nuevo) |

La configuración es la parte chica —unas 400 líneas contra 8,400— y es la que
esta aplicación necesita para funcionar. La identidad es la cara y la que menos
urge mover.

**Regla para cualquiera que trabaje en esto:** si estás a punto de agregar una
tabla de usuarios a `finanzas/configuracion/`, párate. Ese es exactamente el
camino por el que se llega a dos padrones de usuarios desincronizados, que es un
problema que no se arregla después: se arrastra.

---

## Etapa 0 — La capa de configuración ✅ hecha

`finanzas/configuracion/` — cuatro archivos, 28 pruebas que pasan.

| Archivo | Qué resuelve |
|---|---|
| `modelo.py` | Clientes, empresas, conexiones a ERP, retención. Validación al construir. |
| `almacen.py` | Escritura atómica con comparar-e-intercambiar. Local y S3. |
| `secretos.py` | Credenciales cifradas, con clave derivada **por cliente**. |
| `repositorio.py` | La API, y **una** función de autorización. |
| `configurar.py` | Herramienta de alta y edición. |

### Qué se corrigió respecto al sistema anterior, y cómo se comprueba

| Problema anterior | Aquí | Prueba |
|---|---|---|
| Lost-update admitido; el bloqueo solo corría en Windows | Toda escritura lleva la versión esperada; si cambió, se rechaza | `escritura con versión vieja se rechaza` |
| Una clave maestra para todos los clientes | Clave derivada por cliente con HKDF | `blob de otro cliente NO se descifra` |
| Fallo de descifrado → credenciales globales de otro cliente | Falla y detiene | `secreto ausente falla en vez de usar uno global` |
| Once mecanismos de autorización | Uno: `repositorio.puede()` | `permiso desconocido levanta error` |
| 16 de 20 permisos sin verificar | Cada permiso declara dónde se verifica | `todo permiso declara dónde se verifica` |
| Ruta armada a mano en 20+ lugares | `Cliente.prefijo_s3()`, una vez | `la carpeta usa el id opaco` |
| Datos inválidos guardados en silencio | Se rechazan al construir | 7 pruebas de validación |
| Carpeta con el nombre del cliente | UUID opaco | `la carpeta usa el id opaco, no el nombre` |

### Lo que Etapa 0 **no** hace
No tiene usuarios, ni login, ni sesiones. **A propósito.**

---

## Etapa 1 — La configuración deja de ser local

**Hoy** la configuración vive en disco, junto a la extracción. **Después** vive
en S3, bajo `clientes/<uuid>/`, y la extracción la lee de ahí.

Ya está resuelto: `AlmacenS3` cumple el mismo contrato que `AlmacenLocal`,
incluidas las escrituras condicionales. Es cambiar qué almacén se construye.

**Qué confirmar antes:** que el bucket soporte escrituras condicionales. Si no,
`AlmacenS3.escribir()` **falla en vez de degradarse** a sobrescritura
incondicional — preferible a perder datos en silencio dentro de seis meses.

**Riesgo:** bajo. Si falla, se sigue con el almacén local.

---

## Etapa 2 — La pantalla de configuración

Hoy la configuración se captura con `configurar.py` en la máquina local, y el
tablero solo la **muestra**. Esa separación no es pereza: el tablero publicado es
HTML estático sin servidor, y un formulario de contraseñas ahí significa que la
credencial del ERP viaja al navegador de cualquiera que abra el enlace.

Para que haya una pantalla de verdad hace falta **un servidor**. Dos caminos:

**A. Una pantalla en HopDesk que escriba estos mismos objetos.**
HopDesk ya tiene servidor, login y sesión. Escribiría el JSON que define
`modelo.py`. Ventaja: cero infraestructura nueva. Desventaja: sigue creciendo el
sistema que queremos adelgazar, y en otro lenguaje.

**B. Un servicio propio, en un contenedor aparte.**
Un servidor pequeño que sirva la pantalla y hable con esta capa. Ventaja: es el
mismo lenguaje que la extracción y el mismo modelo. Desventaja: necesita
autenticar a alguien — y ahí reaparece la identidad.

**Recomendación:** decidirlo cuando llegue, con la Etapa 1 funcionando. Ambos
caminos escriben exactamente los mismos objetos, así que la decisión no bloquea
nada hoy. Lo que sí queda resuelto desde ahora es el modelo de datos.

**Lo que no debe pasar:** capturar la credencial en el tablero estático "por
mientras".

---

## Etapa 3 — Unificar la identidad

La más grande, y **la que no hay que apurar**.

Precondición: que la capa de configuración lleve meses operando sin incidentes.
Una capa de identidad nueva que falla deja a todos fuera; no se gana ese derecho
con un diseño bonito, sino operando.

Orden propuesto, de menor a mayor riesgo:

1. **Inventario de lo que se enforcea de verdad.** De los 20 permisos de HopDesk,
   4 se verifican. La capa nueva debe nacer con esos 4 —o los que sobrevivan a la
   revisión— y ni uno más. *Un permiso que no se verifica no existe.*
2. **Una sola función de autorización en HopDesk**, aunque siga en R. Reemplazar
   los once mecanismos por llamadas a una. Se puede hacer **sin** tocar el resto:
   es refactor, no migración, y hace todo lo demás más seguro.
3. **Mover el almacenamiento antes que la lógica.** Que HopDesk siga decidiendo
   quién puede qué, pero guardando con escritura condicional. Mata la clase
   lost-update sin tocar autenticación.
4. **Hasta el final, el login.**

**Qué puede romperse en cada paso:** el 2 puede dejar fuera a alguien si una de
las once reglas era más permisiva de lo que aparenta (`settings_hub.R:15` excluye
a `hopdesk` y `principal`, seguramente sin querer — al unificar, *ganarían*
acceso). El 3 puede hacer fallar guardados que antes "funcionaban" pisando datos
de otro. Ambos casos son ruido bueno: estaban rotos antes, solo que en silencio.

---

## Sobre los dos contenedores

Mencionaste que ya están en lenguajes distintos y que dos contenedores están
bien. De acuerdo, con una condición: **que compartan el almacén de configuración,
no que cada uno tenga el suyo.** Dos contenedores leyendo la misma configuración
son un sistema. Dos contenedores con su propia copia son dos sistemas que van a
divergir, y nadie se entera hasta que un cliente aparece en uno y no en el otro.

La escritura condicional del `Almacen` es justo lo que hace seguro que dos
procesos —en dos lenguajes— escriban el mismo archivo.

---

## Lo que NO haría

- **Reescribir las 8,400 líneas de una vez.** Funcionan, y el costo de
  equivocarse es que nadie entra a trabajar.
- **Levantar un segundo padrón de usuarios** mientras el primero sigue vivo.
- **Migrar la identidad antes que el almacenamiento.** Es el orden que maximiza
  el riesgo: lo más visible primero y sin haber arreglado la causa de los datos
  perdidos.
