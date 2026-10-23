# Diseño: pronósticos financieros

Estado: **diseño, sin desarrollar.** Falta una pieza que define la mitad del
trabajo: el formato del Financial Modeling Institute (FMI) que se va a convertir
en algoritmo (ver [La pieza que falta](#la-pieza-que-falta-el-formato-del-fmi)).

La herramienta tiene dos trabajos:

1. **Analizar el histórico.** Ya existe: la vista Avanzado de Indicadores, con
   estadística, tendencia, control, ARIMA/SARIMA y sus pruebas.
2. **Pronosticar.** Es lo que diseña este documento.

---

## La idea central: pronosticar las piezas, no las razones

Hoy se puede pronosticar un margen directamente: es una serie como cualquier
otra. Pero ese margen pronosticado no corresponde a ningún ingreso ni a ningún
costo pronosticado. Si además se pronostican los ingresos por su lado, el
margen por el suyo y la deuda por el suyo, los tres números no cuadran entre sí,
y el balance pronosticado no suma.

El modelo profesional va al revés:

```
  SUPUESTOS (drivers)  →  ESTADOS PRONOSTICADOS  →  RAZONES
  crecimiento, % de       Estado de Resultados,      las mismas fórmulas de
  costos, días de         Balance y Flujo, que        razones_financieras.py
  cobranza, capex,        cuadran entre sí            que ya se usan para el
  tasa de la deuda…                                   histórico
```

Las razones del futuro se calculan **con el mismo código** que las del pasado.
Así un margen pronosticado es el EBITDA pronosticado entre los ingresos
pronosticados, y el histórico y el pronóstico se pueden poner en la misma
gráfica sin cambiar de definición.

---

## Arquitectura en cinco capas

### Capa 1 — Supuestos

Una tabla por tema. La lista definitiva sale del formato del FMI; ésta es la
esperada:

| Tema | Supuestos típicos |
|---|---|
| Ingresos | crecimiento por empresa (o por cliente / línea, con la facturación que ya está en la app) |
| Costos y gastos | costo de ventas y gastos como % de ingresos; la parte fija aparte |
| Capital de trabajo | días de cobranza, de pago y de inventario |
| Activo fijo | capex, vidas útiles y depreciación |
| Deuda | saldos, amortizaciones y tasa por crédito |
| Impuestos | tasa efectiva |
| Capital | dividendos y aportaciones |
| Intercompañía | lo que se factura entre empresas, para eliminarlo al consolidar |

**Cada supuesto declara su origen**, y la pantalla lo muestra:

- **Manual.** Lo escribe alguien, con bitácora. Reutiliza la hoja de captura,
  `entradas_manuales.py` y la escritura que no pisa a otros.
- **Estadístico.** Lo da el motor de la capa 2 a partir del histórico de ese
  supuesto. Por ejemplo, los días de cobranza de los próximos 12 meses.
- **Histórico.** La mediana de los últimos N periodos.

Así se puede empezar con todo estadístico y ir reemplazando con criterio lo que
el equipo conoce mejor que la serie.

### Capa 2 — Motor de pronóstico estadístico

Amplía `finanzas/modelos_series.py`. Pronostica una serie a la vez: un
supuesto, un monto o una razón suelta.

| Familia | Modelos |
|---|---|
| Referencias | ingenuo, ingenuo estacional, deriva |
| Suavizamiento exponencial | ETS / Holt-Winters con parámetros estimados (no fijos como hoy), tendencia amortiguada, estacionalidad aditiva o multiplicativa |
| ARIMA / SARIMA | ya existe |
| Theta | método Theta |
| Descomposición | STL + ETS, STL + ARIMA |
| Combinación | promedio de los mejores según la validación |

Quedan fuera Prophet y el aprendizaje automático: con ~80 meses por serie no
tienen datos suficientes, y Prophet además es una dependencia pesada.

**Validación con la misma vara para todos.** Se usa la prueba hacia atrás de
origen móvil que ya existe en `finanzas/precision_pronostico.py`: para
pronosticar el mes *t* solo se usa lo que se sabía hasta *t − 1*, se compara
contra el real y se avanza. Cada modelo recibe:

- **Errores:** MAE, RMSE, MASE (error contra el ingenuo; menor que 1 significa
  que le gana) y MAPE. El MAPE se avisa cuando la serie pasa cerca de cero,
  porque ahí explota.
- **Sesgo:** si el modelo sobrestima o subestima de forma sistemática.
- **Cobertura del intervalo:** qué tanto del real cayó dentro del intervalo de
  95%. Un intervalo que solo atrapa el 70% está mintiendo.

**Presentación decidida: comparar y recomendar.** Una tabla de precisión con
todos los modelos; la app marca el ganador y lo dibuja, y los demás se pueden
encender como capas.

Referencia honesta: la meta de MAPE de 5% hoy no se cumple. La prueba que ya
existe da 15–17% en facturación. Esta capa tiene que decir cuánto se acerca
cada modelo, no prometerlo.

### Capa 3 — El modelo de tres estados (el algoritmo del FMI)

Con los supuestos de cada periodo:

1. **Estado de Resultados:** ingresos → costos → EBITDA → depreciación (del
   programa de activo fijo) → intereses (del programa de deuda) → impuestos →
   utilidad.
2. **Balance:** cuentas por cobrar, inventarios y por pagar a partir de los
   días; activo fijo a partir del capex y la depreciación; deuda a partir del
   programa; capital a partir de utilidades y dividendos.
3. **Flujo de efectivo:** resulta de los dos anteriores. El efectivo es la
   cuenta que cierra.

Reglas que el código hace cumplir. Son las del buen modelado financiero:

- **Separar supuestos, cálculos y resultados.** Ningún número escrito a mano
  dentro de un cálculo.
- **La circularidad se resuelve iterando, no se esconde.** Los intereses
  dependen de la deuda, la deuda de la caja y la caja de los intereses. Se
  itera hasta converger y se reporta si no converge.
- **Comprobaciones que bloquean:** Activo = Pasivo + Capital en cada periodo;
  el efectivo del flujo coincide con el del balance. Si una falla, no se
  publica el pronóstico.
- **Consolidación con eliminaciones intercompañía**, con
  `finanzas/consolidacion.py`, que ya existe.
- **Prueba de referencia:** el ejemplo del formato del FMI se reproduce al peso.
  Es la prueba de que el algoritmo hace lo mismo que el formato.

### Capa 4 — Incertidumbre: Monte Carlo, escenarios y sensibilidad

(En espera, decidido: va de la mano con la capa 3.)

- **Monte Carlo sobre los supuestos:**
  - Cada supuesto lleva una distribución: normal, triangular, PERT, o la
    empírica de su propio histórico.
  - Las correlaciones entre supuestos se respetan. Por ejemplo, ventas altas
    suelen venir con días de cobranza altos.
  - Se corren miles de simulaciones del modelo de tres estados completo,
    vectorizadas con numpy.
- **Resultados:**
  - percentiles de cada línea y de cada razón, en gráfica de abanico;
  - probabilidad de cumplir cada meta ("margen EBITDA ≥ 19%: 34%");
  - probabilidad de que la caja baje de un mínimo.
- **Escenarios deterministas:** base, optimista y pesimista, guardados con
  nombre.
- **Sensibilidad:** un tornado que dice qué supuesto mueve más el resultado.
  Es la lista de en qué vale la pena afinar el pronóstico.

### Capa 5 — Presentación

En la vista Avanzado, una sección **Pronóstico** al lado del análisis del
histórico:

- la tabla de supuestos, editable, con el origen de cada uno;
- los estados pronosticados junto al histórico;
- la tabla de precisión de los modelos y el recomendado;
- el abanico de Monte Carlo y el tornado;
- todo en los dos idiomas, en el glosario y en `CAPACIDADES.md`.

**Después, aparte (decidido):** la página principal de Facturación pasa a usar
estos mismos modelos e intervalos, en lugar de sus cinco métodos con
parámetros fijos.

---

## Guardar los pronósticos

Un pronóstico que no se guarda no se puede auditar. Cada pronóstico publicado
se guarda con:

- su fecha y su autor;
- sus supuestos y la versión del modelo.

Cuando llegue el real, la app compara contra lo que se pronosticó **en su
momento**, no contra un pronóstico rehecho con datos nuevos. De ahí salen el
seguimiento (*tracking signal*) y la cuenta honesta de qué tan bien pronostica
el equipo.

---

## Lo que ya existe y lo que falta

| Ya existe | Falta |
|---|---|
| Estados mensuales por empresa desde 2020, derivados y consolidados | Estados antes de 2020 (extracción larga, ya en la lista de pendientes) |
| Razones con las mismas fórmulas para cualquier periodo | El detalle de capex |
| Facturación por cliente desde 2013 (podría alimentar el pronóstico de ingresos por cliente) | El detalle de la deuda por crédito: tasa, plazo, amortización |
| ARIMA/SARIMA con pruebas; prueba hacia atrás de origen móvil | ETS, Theta, STL, combinación; la tabla comparativa |
| Captura con bitácora y escritura segura en S3 | Las tablas de supuestos; el modelo de tres estados; Monte Carlo |

---

## Orden de entrega propuesto

| Etapa | Qué | ¿Depende del FMI? |
|---|---|---|
| 1 | Motor multi-modelo + validación + comparar y recomendar, sobre las series que ya existen | No: puede empezar cuando se decida |
| 2 | Esquema de supuestos y su captura | Sí |
| 3 | Modelo de tres estados con comprobaciones, más la prueba de referencia contra el ejemplo del FMI | Sí |
| 4 | Monte Carlo, escenarios y sensibilidad | Sí (va sobre la etapa 3) |
| 5 | Guardar pronósticos y medir contra el real | No |
| 6 | Página principal con los mismos modelos | No |

---

## La pieza que falta: el formato del FMI

Para convertirlo en algoritmo hace falta:

1. **El archivo.** Lo ideal es la versión con fórmulas, no solo valores: las
   fórmulas son la especificación.
2. **Un ejemplo lleno**, si lo trae, para la prueba de referencia al peso.
3. **Cómo se recorre:** qué pestañas son supuestos, cuáles programas de
   cálculo (deuda, activo fijo, capital de trabajo) y cuáles resultados.

Con eso, cada pestaña se vuelve una función con entradas y salidas declaradas,
y cada celda de supuesto, un campo del esquema de la capa 1.

## Decisiones abiertas

- **Granularidad del modelo de tres estados.** Mensual coincide con lo que la
  app ya tiene; trimestral o anual suele ser lo del formato. Se puede tener
  mensual adentro y agregar con las mismas reglas que ya usa la periodicidad.
- **Horizonte.** ¿12 meses para operación, 3 a 5 años para valuación, o los dos?
- **Nivel.** Por empresa y consolidado, o también por cliente o línea de ingreso.
- **Quién captura los supuestos** y quién aprueba un pronóstico antes de
  publicarlo.
- **Distribuciones de Monte Carlo:** por omisión, la empírica del histórico de
  cada supuesto, o elegidas a mano.
