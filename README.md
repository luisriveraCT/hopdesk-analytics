# Analítica Financiera

Tablero analítico del grupo, construido directamente sobre el ERP. Facturación
documento por documento, estados financieros por empresa y consolidados,
indicadores de dirección y captura de las cifras que el ERP no tiene.

---

## Lo que hay que saber para empezar

```
python actualizar.py --ver
```

Construye todo con los datos que ya hay en disco, levanta un servidor local y
abre el navegador. **No toca el ERP ni publica nada.** Es la forma de ver el
tablero sin riesgo.

```
python actualizar.py
```

El ciclo completo: extrae del ERP, verifica el cuadre contable, calcula, revisa
y construye. Se detiene solo en dos puntos y ninguno se puede saltar:

- si el **cuadre contable** falla,
- si aparece un **secreto** dentro del HTML.

```
python actualizar.py --subir
```

Lo anterior más publicar: datos a S3 y la página a Posit Connect Cloud.

### Otras banderas útiles

| Bandera | Qué hace |
|---|---|
| `--solo-erp` | solo extrae; no construye el tablero |
| `--solo-tablero` | solo reconstruye con lo que ya hay en disco |
| `--sin-facturas` | omite la extracción de facturación (es la más lenta) |
| `--desde 2022` | limita la extracción a partir de ese año |

---

## Las cuatro pestañas, y una quinta discreta

| Pestaña | Para quién | Qué contesta |
|---|---|---|
| **Facturación** | operación | el detalle documento por documento, con filtros, búsqueda y pronóstico |
| **Estados Financieros** | contabilidad | Balance y Estado de Resultados por empresa y por periodo, más el grupo consolidado |
| **Dirección** | quien decide | ¿vamos bien? Cinco cifras, semáforo contra meta, tendencia y comparación entre empresas |
| **Indicadores** | quien revisa | ¿por qué? Todas las razones por familia, el DuPont del ROE y el costo de capital abierto |
| **Hoja de captura** | quien tenga asignada la tarea | las cifras que el ERP no tiene, y las correcciones a mano. Se abre desde **Ajustes**, o con `#entradas` en la dirección |

La hoja de captura no está en la barra de arriba a propósito: la usa quien tenga
asignada la captura, no todo el que abre el tablero.

---

## El botón **Montos**: cuánto de las cifras se ve

Tres estados, de más a menos revelador. Se elige en la barra de arriba y se
recuerda por navegador.

| Estado | Qué hace |
|---|---|
| **Ver montos** | todo a la vista |
| **Solo estructura** | el Balance y el Estado de Resultados pierden la columna del importe y se quedan con la del porcentaje: el estado se vuelve un **análisis vertical**. El resto de los importes, ocultos |
| **Ocultar montos** | ningún importe. Los estados conservan su forma, con el importe enmascarado |

En los tres se quedan los porcentajes, los días, los conteos, el tipo de cambio
y la forma de las gráficas. No son montos, y sin ellos no quedaría nada que
leer.

En **Solo estructura**, el subtítulo de cada estado dice contra qué base va el
porcentaje —el activo total en el Balance, los ingresos en el Estado de
Resultados—. Un porcentaje sin su base no es un dato.

En la **hoja de captura** el modo va más lejos: con los montos ocultos, los
campos de dinero además no se pueden capturar. Escribir sobre una cifra que no
se puede leer es escribir a ciegas, y todo lo que se captura ahí queda en la
bitácora con nombre. Los campos que no son dinero —la beta, la prima de
mercado, las tasas— se capturan igual.

**Lo que se descarga sale como lo que se ve.** No hay una segunda ruta por la
que los importes puedan salir a un archivo: `verificar_modo_discreto.py`
comprueba las dos mitades del asunto —qué columna cuenta como monto, y que la
única ruta que no viene de la pantalla pase por el enmascarado—.

> El día que haga falta un permiso de "ver montos" por usuario, se conecta en
> `fijarModoMontos()` y en ningún otro sitio: fijar el modo y esconder el botón
> cubre pantalla, impresión y descarga de una vez.

---

## Imprimir y descargar

**Imprimir** saca la hoja abierta en tema claro, sin barra de herramientas y
**sin los avisos**. En pantalla los avisos son el contexto que evita leer mal
una cifra; en papel son media página de prosa antes de la primera tabla. Lo que
sí tiene que sobrevivir al papel va en el subtítulo de cada tarjeta, no en un
aviso.

**Descargar** baja **la hoja que está abierta** —no el tablero entero— en Excel
o en PDF, con sus gráficas, el contexto de sus filtros y, si los montos están
ocultos, la línea que dice por qué el archivo no los trae.

---

## La hoja de captura de entradas manuales

Dos cosas que parecen iguales y no lo son:

### Suministro

Un dato que el ERP **no tiene y nunca va a tener**: la beta de una empresa
privada, la prima de riesgo de mercado, el capex mientras no se extraiga. Aquí
la captura es la única fuente, así que se edita sin más.

### A qué empresas se captura

El selector **Aplicar a**, arriba de la hoja:

| Destino | Qué guarda |
|---|---|
| **Esta empresa** | una entrada, la de la empresa mostrada |
| **Selección** | una entrada **por empresa** marcada. Son capturas explícitas: reemplazan lo que cada una tuviera |
| **Todas** | **una** entrada global, que hereda cualquier empresa que no tenga la suya |

Los dos últimos no son lo mismo y la diferencia importa: **gana la más
específica**. Una beta global convive con la de NTS y deja a NTS con la suya.
Por eso «Todas» no reemplaza a quien ya capturó por su cuenta —la barra dice
cuáles son— y «Selección» sí.

El periodo no se elige: lo decide el catálogo del campo. Un dato mensual se
captura en su mes; fijarlo para todos los periodos copiaría la misma cifra a 81
meses y el sistema lo rechaza.

### Sobrescritura

Un dato que el sistema **sí calcula** y que alguien reemplaza. Para un escenario
hipotético, o porque la cifra del ERP está mal capturada y hay que corregirla
mientras contabilidad la arregla en su origen.

Esto es otra cosa, y el sistema lo trata como tal:

1. Hay que **quitar el candado** (el botón arriba a la derecha de la hoja).
2. Hace falta un **motivo escrito**. Sin él no se guarda.
3. El renglón queda **marcado** con franja roja y etiqueta — no solo con color,
   para que se vea igual en blanco y negro y para quien no distinga los colores.
4. Todo va a la **bitácora**.

**Para devolver una cifra al cálculo automático, se vacía su celda.** No hay un
botón aparte: un mecanismo de reversión distinto del de borrado es uno que
alguien no va a encontrar cuando lo necesite.

### Cómo se guarda (importante)

El tablero es una página estática: no tiene servidor propio y no puede escribir
en el almacén sin llevar credenciales dentro, que es justo lo que no se hace.

Así que la hoja edita una **copia de trabajo en el navegador** (sobrevive a
recargar la página) y produce un archivo. Quien corre la actualización lo
aplica:

```
python finanzas/entradas.py --aplicar entradas-2026-09-26.json --autor "Tu Nombre"
```

La pantalla lo dice con todas sus letras. Una hoja que parece guardar y no
guarda es peor que una que pide un paso extra.

### También desde la línea de comandos

```
python finanzas/entradas.py --campos            qué se puede capturar
python finanzas/entradas.py --ver               qué hay capturado hoy
python finanzas/entradas.py --fijar beta=1.25 --empresa NTS --autor "Ana"
python finanzas/entradas.py --borrar beta --empresa NTS --autor "Ana"
python finanzas/entradas.py --bitacora          los últimos movimientos
python finanzas/entradas.py --bitacora --todo   la bitácora completa
```

**El autor es obligatorio** en todo lo que modifica. Una cifra puesta a mano sin
nombre no se puede auditar: dentro de seis meses la pregunta no va a ser cuánto
vale, sino quién lo decidió y por qué.

---

## La bitácora de cambios

Registra **todo** lo que una persona hace sobre las cifras: capturas, cambios,
borrados, desbloqueos de campos calculados, aplicaciones de un lote y consultas
de la propia bitácora.

**Solo se agrega.** Un asiento se escribe una vez y no se toca. Corregir uno
equivocado se hace escribiendo otro, igual que en contabilidad.

Se ve en la propia hoja de captura (los más recientes) y completa con
`--bitacora --todo`.

No confundirla con la **otra** bitácora, la de Ajustes: aquélla registra qué
cambió en los **datos** entre una extracción del ERP y la siguiente. El sujeto
de una es una persona; el de la otra es el ERP.

---

## Configuración: nada que decidas vive en el código

Todo lo que es decisión del cliente está en `finanzas/configuracion/`:

```
python finanzas/configuracion/configurar.py --mostrar
python finanzas/configuracion/configurar.py --politica
python finanzas/configuracion/configurar.py --politica metas.dso=50
python finanzas/configuracion/configurar.py --agregar-empresa
python finanzas/configuracion/configurar.py --detectar-interco
```

Qué vive ahí: las empresas y su ERP, los identificadores que las hacen
intercompañía, cuántos años de historia se conservan, la norma contable, las
metas del semáforo, los supuestos del WACC, los días del año, la base de los
días de pago y el vocabulario para reconocer rubros del balance.

Un cliente nuevo se da de alta sin tocar un archivo `.py`.

---

## Dónde está cada cosa

### Raíz

| Archivo | Qué es |
|---|---|
| `actualizar.py` | **el comando único.** Todo el ciclo, con sus dos puntos de paro |
| `refrescar.py` | publicar lo ya construido: datos a S3 y HTML a Connect |
| `FUNDAMENTOS.md` | **por qué se calcula así, y los errores que no hay que repetir** |
| `README.md` | esto |

### `finanzas/` — el cálculo

| Archivo | Qué hace |
|---|---|
| `erp/` | la conexión al ERP. `registro_conectores.py` lo hace intercambiable |
| `erp/extraer_estados_financieros.py` | catálogo de cuentas y saldos |
| `erp/extraer_facturacion.py` | cabeceras de ventas y compras |
| `erp/clasificador_cuentas.py` | qué clase es cada cuenta, por árbol y nombre |
| `analisis_vertical_horizontal.py` | Balance y Estado de Resultados desde los saldos |
| `consolidacion.py` | el grupo con sus eliminaciones intercompañía |
| `mapeo_kpis.py` | del catálogo de cuentas a los campos que usan las razones |
| `razones_financieras.py` | **el catálogo de indicadores** y su cálculo |
| `normas_contables.py` | qué decide cada marco contable (IFRS/NIF, US GAAP) |
| `entradas_manuales.py` | suministro y sobrescritura, con sus reglas |
| `bitacora_cambios.py` | quién tocó qué, cuándo y por qué |
| `entradas.py` | la línea de comandos de la captura |
| `verificar_cuadre.py` | el punto de paro contable |
| `configuracion/` | todo lo que decide el cliente |
| `test_financiero.py` | **21,000+ pruebas** |

### `dashboard/` — la pantalla

| Archivo | Qué hace |
|---|---|
| `plantilla.html` | la aplicación entera. Su encabezado explica cómo trabajar aquí |
| `exportar_dashboard.py` | los datos de facturación (chunks) |
| `exportar_finanzas.py` | Balance y Estado de Resultados |
| `exportar_kpis.py` | indicadores, razones, DuPont y costo de capital |
| `exportar_entradas.py` | la hoja de captura y la bitácora |
| `construir.py` | inyecta todo en la plantilla → `index.html` |
| `publicar.py` | sube a S3 **y borra lo que sobra** |
| `verificar_sintaxis.py` | que el JavaScript compile |
| `verificar_alcance.py` | que ningún bloque quede dentro de otra función |
| `verificar_idiomas.py` | que no falte ninguna traducción |
| `verificar_modo_discreto.py` | qué columna es un monto, y que la descarga lo respete |
| `verificar_publicacion.py` | que no se publique ningún secreto |

### `legacy/`

Solo un `README.md` con la constancia de por qué la fuente de verdad es el ERP
y no los archivos de Excel. Ya no hay código ni datos ahí.

---

## Pruebas

```
python finanzas/test_financiero.py            todo (~21,000 pruebas)
python finanzas/test_financiero.py --rapido   solo las unitarias
python finanzas/configuracion/test_configuracion.py
```

Dos clases, y las dos hacen falta:

- **Unitarias**, sobre casos construidos a mano: los límites que los datos
  reales rara vez producen.
- **De propiedad, sobre los datos reales**. No comprueban un valor esperado
  —nadie sabe de memoria el ROIC de un mes— sino relaciones que tienen que
  cumplirse siempre: que el balance cuadre, que el EBITDA menos el EBIT sea
  exactamente la depreciación, que ningún plazo salga negativo, que consolidar
  no cree utilidad, y **que las dos pestañas coincidan**.

Esa última faltaba, y por eso un EBIT con la depreciación restada dos veces
sobrevivió semanas. Está contado en `FUNDAMENTOS.md`.

---

## Si algo se rompe

| Síntoma | Dónde mirar |
|---|---|
| Una sección del tablero sale en blanco | `verificar_alcance.py` — casi siempre un bloque quedó dentro de otra función |
| Un texto sale en el idioma equivocado | `verificar_idiomas.py` |
| Un importe sale en un archivo con los montos ocultos | `verificar_modo_discreto.py` — casi siempre una ruta de exportación nueva que no pasa por `enmascararFilas()` |
| El cuadre falla | `finanzas/verificar_cuadre.py` dice qué empresa y qué periodo |
| Un indicador sale vacío | probablemente es correcto. Ver "Lo que no se puede calcular con honestidad no se calcula" en `FUNDAMENTOS.md` |
| Un número no coincide con otro reporte | `FUNDAMENTOS.md` §2.4 — los días de cobranza y de pago no usan la base clásica, y está explicado por qué |
| La subida no llega | `python refrescar.py --simular` |

---

## Lo que falta

- **Capex**: sin él no hay flujo libre. Es una extracción más del ERP.
- **Paragon Logistics**: no está dada de alta en el ERP, así que queda fuera de
  todo el análisis.
- **Presupuesto**: falta el permiso `BudgetScenarios` en el ERP.
- **Unificar la identidad con HopDesk**: ver `finanzas/PLAN_UNIFICACION.md`.
