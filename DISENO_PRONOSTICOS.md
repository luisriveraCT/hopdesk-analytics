# Pronósticos financieros — pendiente de diseño

Estado: **abierto.** Este documento solo fija el propósito y lo que se sabe hoy.
El proceso y los modelos se definen cuando esté el formato de referencia.

## Propósito

La vista de análisis tiene dos trabajos:

1. **Analizar el histórico.** Ya existe: la vista Avanzado de Indicadores.
2. **Pronosticar.** Pendiente de diseño.

## Lo que se sabe

- **El proceso lo define el formato del Financial Modeling Institute (FMI).**
  Es un protocolo que acomoda toda la información financiera en tablas y
  cédulas con un formato particular. El pronóstico se construye sobre esa
  estructura, así que no se diseña nada del proceso antes de tenerlo.
- **Las razones del futuro se calculan con las mismas fórmulas que las del
  pasado** (`finanzas/razones_financieras.py`), a partir de lo que se
  pronostique. Así el histórico y el pronóstico se pueden comparar sin cambiar
  de definición.
- **Los modelos de pronóstico no están elegidos.** Tienen que ser los adecuados
  para el comportamiento particular de estas empresas, y se eligen después.
- **Monte Carlo queda en espera** y va de la mano con lo anterior.
- **La presentación ya está decidida:** varios modelos se comparan con la misma
  prueba y la app recomienda uno.
- **La página principal de Facturación** se actualiza después y por separado.

## Lo que ya existe y puede servir

- Estados financieros mensuales por empresa desde 2020, derivados y
  consolidados.
- Facturación por cliente desde 2013.
- La prueba hacia atrás honesta de `finanzas/precision_pronostico.py`: cada
  periodo se pronostica solo con lo que se sabía antes.
- `finanzas/modelos_series.py`: ARIMA/SARIMA con sus pruebas.
- La captura con bitácora y la escritura segura en S3.

## Para empezar hace falta

- El formato del FMI, de preferencia con fórmulas y un ejemplo lleno.
- La decisión sobre los modelos, una vez conocido el formato.
