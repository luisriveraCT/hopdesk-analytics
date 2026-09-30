# Fundamentos: cómo se calcula, por qué así, y en qué NO hay que volver a caer

Para quien tenga que tocar este desarrollo. No es documentación de referencia
—esa vive en los encabezados de cada archivo— sino el razonamiento detrás de
las decisiones que no son obvias, y el registro de los errores que ya se
cometieron para que no se vuelvan a cometer.

Si vas a cambiar un cálculo, lee la sección 3 primero. Casi todo lo que parece
una mejora evidente ahí ya se intentó y salió mal.

---

## 1. Las cinco reglas de las que cuelga todo

### 1.1 Nunca sumar leyendo una fila de "TOTAL"

Los números se calculan sumando documentos individuales. Nació porque había 8
hojas de Excel donde el total escrito no coincidía con la suma de sus propias
filas, y sobrevivió al cambio de fuente porque en el ERP reapareció con otra
cara: las facturas canceladas conviven con su **documento de cancelación**, que
trae el importe en positivo. Sumar "todo lo que hay" cuenta tres veces la misma
operación.

Por eso se filtra siempre por `clase_documento == 'normal'`.

### 1.2 Ninguna verificación debe poder cumplirse sola

El Balance de diciembre daba cero en todas las cuentas porque SAP hace cierre y
reapertura total. Y cero = cero + cero cumple la identidad contable a la
perfección: **el verificador lo aprobaba**.

Una prueba que pasa por construcción no es una prueba. Cada verificación tiene
que poder fallar con datos plausibles.

### 1.3 Lo que no se puede calcular con honestidad no se calcula

`None`, nunca cero. Un cero dice "esto vale cero", que es una afirmación. Un
hueco dice "no se pudo determinar", que es la verdad.

Aplica a: flujo libre sin capex, días de cobranza en una empresa que solo
factura al grupo, razones de doce meses antes del mes doce, tasas efectivas
fuera de rango.

### 1.4 Nada que el cliente decida vive en el código

Empresas, ERP, identificadores intercompañía, norma contable, metas del
semáforo, supuestos del WACC, días del año, base de los días de pago,
vocabulario de rubros. Todo en `finanzas/configuracion/`.

La prueba de que se sostiene: en el código no hay ninguna decisión que dependa
de que el ERP sea SAP, ni ningún número que solo tenga sentido para este
cliente.

### 1.5 Nada queda a medias entre piezas

Un campo nuevo trae su traducción en los dos idiomas, su entrada de glosario y
su tooltip. Si falta uno, la aplicación queda mintiendo en silencio, que es
peor que quedarse corta.

---

## 2. Las decisiones de cálculo, con su razón

### 2.1 Un balance NO se suma; un estado de resultados SÍ

  · El **Estado de Resultados** es un FLUJO. El trimestre es la suma de sus tres
    meses.
  · El **Balance** es una POSICIÓN. El trimestre es el saldo del último mes.

Sumar un balance triplicaría el activo — y **seguiría cuadrando**, porque
también triplicaría el pasivo y el capital. Un error que cuadra no se detecta
leyendo el resultado.

Por eso son dos funciones distintas y no una con un parámetro: quien agregue un
renglón nuevo tiene que elegir a cuál pertenece.

Lo mismo aplica a los agregados de doce meses: los flujos se suman, los saldos
se promedian. Promediar es lo correcto porque un rendimiento anual se ganó
sobre el capital que estuvo puesto durante el año.

### 2.2 Qué entra al EBITDA lo decide la norma contable, no el código

Bajo IFRS/NIF la "A" de EBITDA es amortización de intangibles y de activos por
derecho de uso — **no** el consumo de un pago anticipado.

En este catálogo existe "Amortización - Primas Seguros": una póliza pagada por
adelantado que se consume mes a mes. Es gasto de operación corriente. Sumarla
de vuelta inflaba el EBITDA con algo que sí consume caja todos los años.

La estructura es **amplia-incluye / específica-excluye**, y ese orden importa:
la primera versión listaba en `incluye` solo "amortización de intangibles", y
con eso dejaba fuera "Amortización - Programas de Cómputo", que es software —
un intangible de libro. Enumerar cada forma de nombrar un intangible es una
carrera perdida.

### 2.3 Consolidar no crea ni destruye utilidad

Se elimina el mismo importe de los ingresos de quien vendió y de los gastos de
quien compró. Que la utilidad del grupo no cambie es **la prueba** de que la
eliminación está bien hecha.

Y se elimina **solo lo que empareja**. Si el grupo facturó 52.6 millones entre
sus empresas pero registró 41.6 de compras, lo que de verdad es una operación
interna son los 41.6 comunes. Eliminar cada lado por su cuenta cambiaría la
utilidad del grupo por la diferencia.

**Lo que no concilia se revela, no se ajusta.** Ajustarlo sería inventar un
asiento que nadie hizo.

### 2.4 Los días de cobranza y de pago no usan la base clásica

  · **Cobranza**: contra ventas **a terceros**. Las cuentas por cobrar de este
    catálogo son de terceros —los saldos con empresas del grupo viven en
    Deudores Diversos—, así que medirlas contra ventas de libros (que traen la
    facturación intercompañía) da un plazo bajo, y el sesgo es peor justo en la
    empresa que más le factura al grupo.

  · **Pago**: contra **costos y gastos de operación en efectivo**, no contra el
    costo de ventas. El denominador clásico supone que las compras pasan por el
    costo de ventas, y en este grupo no pasan: el costo de ventas es el 0.2% de
    los ingresos en una empresa y cero en otra. Contra esa base los días de pago
    daban 365 en una empresa y 1,564 en el consolidado.

    **Es configurable.** Si contabilidad reclasifica el costo directo, vuelve a
    la base clásica cambiando un valor.

### 2.5 El WACC mezcla observación con juicio, y lo dice

  · Tasa libre de riesgo — observable.
  · Tasa efectiva de impuestos — se calcula del ERP, por empresa y periodo.
  · **Beta y prima de mercado — NO son observables.** Esta es una empresa
    privada: no hay precio de acción del cual estimar una beta.
  · Costo de la deuda — capturado.

Cada insumo viaja con su origen hasta la pantalla, marcado como *observado* o
*juicio*. Un WACC impreso con dos decimales parece un hecho medido, y la mitad
no lo es.

El escudo fiscal usa **la misma tasa** que el NOPAT. Si fueran distintas, el
spread ROIC − WACC estaría restando dos números calculados con supuestos
fiscales diferentes, y la diferencia se leería como creación de valor.

### 2.6 La pertenencia al grupo es un dato configurado, no una deducción

Detectar intercompañía por nombre falla en los dos sentidos: se pierde la
empresa cuando el maestro trae el nombre escrito distinto, y se cuela un tercero
que se llame parecido. Ninguno de los dos errores se nota — solo mueve el
porcentaje de intercompañía, que es justo lo que nadie puede verificar de
memoria.

`rfcs_alternos` existe porque el maestro de socios tiene erratas reales
(un `1` donde va una `I`). Corregirlas en el ERP es lo correcto; mientras tanto,
reconocerlas evita perder facturas.

### 2.7 Dos clases de captura manual, y la diferencia es el diseño entero

  · **Suministro** — un dato que el ERP no tiene y nunca va a tener. Se edita
    sin ceremonia: no compite con nada.
  · **Sobrescritura** — un dato que el sistema SÍ calcula y alguien reemplaza.
    Exige desbloquear, exige motivo escrito, queda marcada y va a la bitácora.

Un número sobrescrito se ve idéntico a uno calculado, y seis meses después nadie
recuerda cuál era cuál.

**Borrar la cifra devuelve el cálculo automático.** No hay un botón aparte: un
mecanismo de reversión distinto del de borrado es uno que alguien no va a
encontrar.

---

## 3. Los errores que ya se cometieron — no los repitas

### 3.1 🔴 Restar la depreciación dos veces

**El más caro.** El módulo de indicadores calculaba:

```
EBIT = ingresos − costo − gastos de operación − depreciación
```

**La depreciación ya está dentro de los gastos de operación.** Son cuentas de
clase GASTO y el Estado de Resultados las suma ahí.

En un mes real: la utilidad de operación del estado era 2,631,384 y aquí salía
−280,143. La diferencia, 2,911,527, era exactamente la depreciación.

Como el EBITDA se arma sumándole la depreciación de vuelta al EBIT, **el
"EBITDA" publicado era el EBIT**. De ahí colgaban NOPAT, ROIC, spread y EVA. El
spread de dos empresas cambió de signo al corregirlo.

**La regla que quedó:** `derivar_estado` NO recalcula lo que el Estado de
Resultados ya calculó. Si la llave viene, se respeta.

**La trampa que queda viva:** esa función conserva una fórmula de respaldo para
filas crudas donde los gastos NO incluyen depreciación. Si escribes código que
recalcula el EBIT, fíjate primero en qué caso estás.

### 3.2 🔴 Un número sin sentido pintado de verde

Una empresa mostraba una tasa efectiva de impuestos de **−308%** y el semáforo
la pintaba **verde**, porque la meta es "menor es mejor" y −3.08 es menor que
0.30.

La bandera `tasa_confiable` ya existía. **No la consultaba nadie.**

**La regla:** una bandera que nadie consulta no existe. Si declaras que un dato
puede no ser confiable, el código que lo muestra tiene que preguntarlo.

### 3.3 🔴 Bloques de código dentro de otra función

El panel de Ajustes quedó dentro de `bindGlosario()`, y la pestaña de Estados
Financieros dejó de pintar por lo mismo. Sus definiciones quedan en ese alcance
y cualquier llamada desde fuera revienta con `ReferenceError`.

En un archivo de 4,000 líneas no se ve, y el síntoma —una sección en blanco— no
señala la causa.

**Lo que lo evita:** `dashboard/verificar_alcance.py`, que corre en el pipeline.

### 3.4 🟠 `None` significando dos cosas

`razones()` trataba igual "quien llama no calculó la base" y "quien llama
determinó que no aplica". Resultado: unos días de cobranza que se habían
suprimido a propósito volvieron a mostrar 187 días, calculados contra ingresos
que son casi todos facturación a las empresas hermanas.

**La regla:** se pregunta si la LLAVE está, no si el valor es `None`.

El mismo error reapareció en la interfaz: buscaba el indicador en las razones y,
si no estaba, en el campo derivado crudo — y esa segunda lectura recuperaba la
tasa de −308% que el cálculo acababa de suprimir. Por eso el catálogo declara
`fuente`: cada indicador vive en **un solo lugar**.

### 3.5 🟠 Listas paralelas que se separan

La interfaz tenía cuatro listas propias: familias de indicadores, cuáles tienen
versión de doce meses, cuáles van en dinero, y las columnas del comparativo.
Agregar un indicador obligaba a acordarse de las cuatro, y olvidarse de una lo
dejaba calculado, publicado y **sin aparecer en ninguna pantalla**.

**La regla:** un solo catálogo, que viaja en los datos.

### 3.6 🟠 Redondear tasas como si fueran importes

El exportador redondeaba todo a dos decimales. Una tasa libre de riesgo de 0.095
quedaba en **0.10**. El WACC construido sobre ella dejaba de reproducir el
spread contra el ROIC que se mostraba a su lado.

En pantalla se ve mínimo (16.00% contra 16.01%). En el EVA se mueve en millones.

### 3.7 🟠 Dividir entre ruido de punto flotante

Al restar la facturación intercompañía de los ingresos, algunas empresas
quedaban con una base de 10⁻¹⁴ pesos. Días de cobranza resultantes: **1.8 ×
10¹⁶**.

Cero no basta como frontera, porque el ruido cae de los dos lados. El corte es
**un peso**: la resolución del propio dato.

### 3.8 🟠 Criterios de especificidad por longitud de cadena

El clasificador de rubros elegía el término más largo. Funciona para distinguir
cosas que compiten ("cuentas por cobrar" contra "cobrar"), pero falla cuando un
término **califica** a otro:

```
"Documentos y cuentas por pagar empresas relacionadas largo plazo"
   "cuentas por pagar" (17)  vs  "empresas relacionadas" (21)  → gana el bueno

"Accounts Receivable - Related Parties"
   "accounts receivable" (19)  vs  "related parties" (15)  → gana el malo
```

La misma cuenta, el mismo error, y la diferencia es cuántas letras tiene la
palabra en cada idioma. Por eso `RUBROS_PRIORITARIOS` decide antes que la
longitud.

### 3.9 🟠 Clasificar una cuenta en una sola dimensión

La tentación fue agregar "activo circulante" al vocabulario de rubros. No
funciona: "activos circulantes" (19 letras) le gana a "bancos" (6) en toda
cuenta de banco, y **el efectivo del grupo se vuelve cero**. Las razones de
liquidez saldrían bien y el ROE mal, sin ninguna señal.

Son dos preguntas distintas sobre la misma cuenta: QUÉ ES y CUÁNDO VENCE. No
caben en una sola asignación exclusiva.

### 3.10 🟡 `float(nan or 0)` devuelve `nan`

Una celda vacía envenenaba la suma de un año entero.

### 3.11 🟡 Comparar contra la columna equivocada

Se auditó contra `Importe`, que solo estaba llena al 34%. La columna completa
era `Total MXN`. La auditoría "pasaba" porque comparaba huecos contra huecos.

### 3.12 🟡 Borrar en S3 sin revisar la respuesta

`delete_objects` devuelve los errores **en el cuerpo de la respuesta**, no como
excepción. El código imprimía "retirados 3 archivos" habiendo borrado cero.

### 3.13 🟡 Variables CSS que no existen

`--acc` y `--fg` se usaban y nunca se definían. Una `var()` inválida no avisa:
la regla entera se descarta. Costó tres cosas que nadie relacionaba entre sí —
la línea de ingresos de una gráfica salía con `stroke=""` y por lo tanto
invisible, los renglones de total perdían su subrayado, y la pestaña activa se
subrayaba del color del texto.

### 3.14 🟡 Esconder el error al revisar

Corrí el exportador con `| grep "kpis.json"` y el grep se tragó un
`NameError`. Di por bueno un archivo que no se había regenerado.

**Si filtras la salida de un comando, filtras también sus errores.**

### 3.15 🟡 Un paso del pipeline que fallaba en silencio

`actualizar.py --subir` llamaba a `refrescar.py` en la raíz cuando el archivo
estaba en `legacy/`, con una bandera que esa versión nunca tuvo. El paso no
detiene la corrida, así que la subida llevaba tiempo fallando sin que nadie lo
notara.

**Si un paso no detiene la corrida, tiene que probarse con `--simular`.**

### 3.16 🟡 Una sobrescritura sin rehacer la cascada

Al permitir corregir los ingresos a mano, la fila quedaba con el ingreso
corregido y el EBIT viejo: 26 millones de ingreso con un margen calculado sobre
26.3. Lo detectó la prueba que compara las dos pestañas.

---

## 4. Lo que las pruebas vigilan

**21,000+ pruebas**, en dos clases:

  · **Unitarias**, sobre casos construidos a mano: meta en cero, meta negativa,
    división entre cero, catálogos con ciclos, convenciones mal escritas.
  · **De propiedad, sobre los datos reales**. No comprueban un valor esperado
    —nadie sabe de memoria el ROIC de un mes— sino relaciones que tienen que
    cumplirse siempre.

La más importante de todas: **que las dos pestañas coincidan**, mes por mes y
empresa por empresa. Estados Financieros lee el Estado de Resultados directo;
Indicadores construye encima. Si no coinciden, una de las dos miente y nadie
tiene cómo saber cuál.

Esa prueba faltaba, y por eso el error 3.1 sobrevivió tanto tiempo.

**Cada error de la sección 3 tiene ahora una prueba que lo vigila.** Esa es la
diferencia entre corregirlo y evitar que vuelva.

---

## 5. Cómo trabajar aquí

**Verificar en vez de suponer.** Antes de usar una librería de un CDN se
comprueba que la URL y la versión existan. Antes de dar por buena una
exportación se abre el archivo generado y se revisa por dentro. Antes de afirmar
que algo quedó bien, se mira.

Varios errores reales de este proyecto —meses corridos por zona horaria,
mojibake que rompía el JavaScript, un `var(--mono)` que moría al aislar el SVG
en una imagen— se encontraron exactamente así, no razonando.

**Cuando algo no se puede calcular con honestidad, no se calcula.**

**Nada queda a medias entre piezas.**

**Un comentario explica por qué, no qué.** Los comentarios de este código
cuentan qué salió mal antes. Si borras uno porque "el código ya se entiende",
estás borrando la única constancia de un error que costó encontrar.
