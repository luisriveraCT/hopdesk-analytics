# Lo que la app sabe hacer

Este es el hilo de las capacidades del tablero: **qué puede hacer quien lo usa**
y **qué pieza del código lo sostiene**. Existe para que ningún desarrollo apague
una función por accidente. Ya pasó una vez: la métrica "Base sin IVA" seguía
viva pero escondida dentro de Ajustes, y nadie lo notó hasta que alguien la buscó.

**Las reglas:**

- Si agregas una capacidad, agrégala aquí, con sus piezas.
- Si quitas una, quítala de aquí **a propósito**, y di en el commit por qué.
- Si renombras una pieza, cámbiala aquí también.

`dashboard/verificar_capacidades.py` lee la columna **Piezas** y comprueba que
cada una siga existiendo. Corre en cada actualización. Si una pieza desaparece,
lo dice con el nombre de la capacidad que se perdió.

Cómo se escriben las piezas (entre comillas invertidas):

| Forma | Qué se comprueba |
|---|---|
| `nombre()` | que la función exista en `dashboard/plantilla.html` |
| `#id` | que el elemento con ese `id` exista en la plantilla |
| `t:clave` | que el texto exista en los dos idiomas |
| `ruta/archivo.py` | que el archivo exista en el repositorio |

---

## Facturación

| Capacidad | Para quien la usa | Piezas |
|---|---|---|
| Ventas y Compras | Cambia la pestaña entera entre facturas a clientes (por cobrar) y de proveedores (por pagar), con los mismos filtros, gráficas, tabla y descargas. Conserva empresas, periodo y filtros al cambiar | `fijarTipo()` `#segTipo` `t:tipo.venta` `t:tipo.compra` |
| Toda la historia del ERP | Desde la primera factura que el ERP tenga. Abre en los últimos cinco años | `aplicarPeriodo()` `#segPer` `finanzas/erp/extraer_facturacion.py` |
| Memoria de corto plazo | Recuerda el tipo y el periodo elegidos durante 12 horas; después vuelve a ventas y cinco años | `recordar()` `recordado()` `restaurarPeriodo()` |
| Filtro por empresa | Burbujas por sigla, con nombre completo al pasar el cursor | `buildControls()` `#bubbles` |
| Intercompañía | Incluir, excluir o solo operaciones entre empresas del grupo, según el registro configurado (RFC y códigos de socio), nunca por nombre | `#segInterco` `t:f.interco` |
| Canceladas | Excluidas por omisión; se pueden incluir o ver solas. Los documentos de cancelación nunca se suman | `#segCancel` `t:f.canceladas` |
| Abiertas y cerradas | Las facturas con saldo pendiente de cobro o de pago, según el ERP el día de la extracción | `#segSituacion` `t:f.situacion` |
| Métrica global | Total MXN, Base sin IVA, número de facturas o Total USD, de golpe en todas las tarjetas | `fijarMetricaGlobal()` `#segMetrica` |
| Búsqueda | Por contraparte, RFC, folio, referencia (el folio del proveedor en compras), empresa o monto | `prepQuery()` `applyFilters()` `#q` |
| Menos filtros | Pliega todo menos la primera fila, y se recuerda por navegador | `aplicarColapso()` `#fColapsar` |
| Mosaicos de cifras | Total, base, facturas, ticket promedio, % intercompañía, USD, tipo de cambio ponderado, canceladas | `drawKpis()` `#kpis` |
| Serie mensual | Apilada por empresa o en 100%, por mes, trimestre o año | `drawSerie()` `#cardSerie` |
| Pronóstico | Cinco métodos, al extender "Hasta" al futuro. Los mismos parámetros que el reporte de Finanzas | `calcularPronostico()` `pronosticoHolt()` `finanzas/precision_pronostico.py` |
| Tarjetas de análisis | Empresa, intercompañía vs. terceros, clientes o proveedores, tamaño de factura, exposición en dólares | `drawBarsH()` `drawInterco()` `drawHist()` `drawFx()` |
| Plazas | Aparece sola cuando el catálogo de sedes tenga datos (hoy viven en las líneas del documento, que no se extraen) | `aplicarCatalogos()` `#cardPlaza` |
| Tabla de detalle | Todas las facturas filtradas, virtualizada, ordenable por cualquier columna | `renderTable()` `columnasTabla()` `#mt` |
| Carga en dos tiempos | Pinta al instante con el resumen incrustado y completa con el detalle; si un archivo no llega, lo dice | `aggregateMeta()` `cargarTipo()` `pintarCarga()` |
| Moneda correcta | Los pesos y los dólares de cada factura vienen del ERP por separado; ninguno se calcula del otro | `finanzas/erp/sap_b1.py` `finanzas/verificar_datos.py` |

## Estados financieros, Dirección e Indicadores

| Capacidad | Para quien la usa | Piezas |
|---|---|---|
| Balance y Estado de Resultados | Por empresa y periodo (mes, trimestre, semestre, año, del año a la fecha), con comparación | `fzConstruir()` `fzBalanceAgregado()` `fzResultadosAgregados()` |
| Consolidado del grupo | Con eliminaciones intercompañía, no una suma | `fzEmpresasDisponibles()` `finanzas/consolidacion.py` |
| Netear intercompañía | Ver solo el negocio con terceros de una empresa | `fzNetear()` `#fzNeteo` |
| Dirección | Cinco cifras, semáforo contra meta, tendencia de doce meses, comparación entre empresas | `kpConstruir()` `kpSemPintar()` `kpComparativo()` |
| Indicadores | Todas las razones por familia, DuPont del ROE y costo de capital abierto | `tfConstruir()` `tfDupont()` `tfWacc()` |
| Huecos honestos | Lo que no se puede calcular con honestidad no se muestra, y dice por qué | `kpAvisosDe()` `finanzas/razones_financieras.py` |

## Captura de entradas manuales

| Capacidad | Para quien la usa | Piezas |
|---|---|---|
| Hoja de captura | Suministro de lo que el ERP no tiene; se abre desde Ajustes o con `#entradas` | `enConstruir()` `ajRenderEntradas()` `#panelEntradas` |
| Sobrescritura con candado | Reemplazar una cifra calculada exige quitar el candado y escribir el motivo | `enCapturar()` `#enCandado` |
| A qué empresas | Esta empresa, una selección o todas, con la regla "gana la más específica" | `enAmbitos()` `#enDestino` |
| Guardar | Guarda en el servidor cuando la página corre en la aplicación; si no, produce el archivo para aplicarlo | `enGuardar()` `enExportar()` `servidor/app.py` |
| Bitácora de cambios | Quién tocó qué, cuándo y por qué; solo se agrega | `enPintarBitacora()` `finanzas/bitacora_cambios.py` |

## Para todo el tablero

| Capacidad | Para quien la usa | Piezas |
|---|---|---|
| Botón Montos | Ver montos, solo estructura (análisis vertical) u ocultar montos, en pantalla, impresión y descarga | `fijarModoMontos()` `enmascararFilas()` `#btnDiscreto` `dashboard/verificar_modo_discreto.py` |
| Descargar la hoja abierta | Excel o PDF de la pestaña que se ve, con sus gráficas y el contexto de sus filtros | `exportarHojaXLSX()` `exportarHojaPDF()` `svgAPng()` `#btnDescargarGlobal` |
| Descargar una tarjeta | Copiar, CSV, Excel o PDF de una sola tarjeta | `exportarXLSX()` `exportarPDF()` `copyText()` |
| Imprimir | La hoja abierta en tema claro, sin barra de herramientas ni avisos | `#btnImprimir` |
| Dos idiomas | Español e inglés completos, sin mezclar | `setLang()` `t()` `#langEs` `#langEn` `dashboard/verificar_idiomas.py` |
| Glosario | Todo término, sigla y criterio, buscable, en los dos idiomas | `renderGlosario()` `#gmodal` `#btnGlosario` |
| Ayuda en cada tarjeta | El botón "?" junto a cada título | `helpTipShow()` |
| Ajustes | Configuración del cliente, bitácora de actualizaciones del ERP y fuentes de los datos | `ajRenderConfig()` `ajRenderBitacora()` `ajRenderFuentes()` `#btnAjustes` |
| Tema claro y oscuro | Sigue al del sistema | `cssv()` |
| Sin terceros | Librerías y tipografías servidas desde el mismo almacén; el navegador no le pide nada a nadie más | `dashboard/estaticos/lib/exceljs.min.js` |

## El pipeline

| Capacidad | Para quien la usa | Piezas |
|---|---|---|
| Un solo comando | Extraer, verificar, calcular, construir y publicar | `actualizar.py` |
| Punto de paro contable | La identidad contable de cada empresa y periodo | `finanzas/verificar_cuadre.py` |
| Comprobación de los datos | Miles de relaciones sobre los datos de cada corrida, incluida la de moneda | `finanzas/verificar_datos.py` |
| Nada de secretos publicados | Punto de paro antes de publicar | `dashboard/verificar_publicacion.py` |
| Bucket limpio | Sube lo que hay y retira lo que ya no corresponde | `dashboard/publicar.py` |
| Nada del negocio en git | Antes de subir al repositorio | `verificar_repositorio.py` |
| Configuración del cliente | Empresas, ERP, interco, retención, metas: sin tocar código | `finanzas/configuracion/configurar.py` |
