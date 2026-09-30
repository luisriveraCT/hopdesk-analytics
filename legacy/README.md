# Por qué la fuente de verdad es el ERP y no los archivos de Excel

**Carpeta de registro histórico.** Aquí ya no hay código ni datos: solo la
constancia de una decisión, porque alguien va a volver a preguntarse por qué las
cifras del tablero no coinciden con un Excel viejo.

## La decisión

**2026-09-25 — la facturación se lee del ERP.**
**2026-09-26 — se eliminó todo rastro del Excel del desarrollo.**

## Lo que se eliminó, y dónde quedó lo que existía antes

| Qué | Dónde está ahora |
|---|---|
| `BASE_FACTURACION_CONSOLIDADA.xlsx` (19.6 MB) | Eliminado de la app. El archivo original sigue en la carpeta compartida de la empresa |
| `consolidar_facturacion.py` | Eliminado. Su método está descrito abajo |
| `auditoria_contra_excel.py` | Eliminado. Su resultado está en esta misma página |
| Copias de `ARCHIVOS DE FACTURACION 2018…2026` (61 MB) | Eliminadas de la app. **Los originales siguen en la carpeta compartida de la empresa**, que es su lugar |
| `FORMATO_ESTADOS_FINANCIEROS.md` | Eliminado: describía cómo entregar Balance y Estado de Resultados a mano, y eso lo hace el ERP |
| `refrescar.py` (versión Excel) | Reemplazado por `refrescar.py` en la raíz, que solo publica |

No se borró nada que fuera la única copia. Los archivos de origen son registros
de la empresa y viven donde siempre vivieron.

## La evidencia que sustentó el cambio

| | Excel | ERP |
|---|---|---|
| Facturas de venta | 159,123 | **218,808** |
| Historia | desde 2020 | **desde 2013** |
| Facturas de compra | — | **197,639** |
| Depende de que alguien guarde un archivo | sí | **no** |

Y donde ambas fuentes cubrían lo mismo, **coincidían**: NG 2021, 2022 y 2023 al
centavo, igual que NL 2020/2022/2023 y NRS 2020/2023.

Las diferencias que quedaron eran defectos del lado del Excel. En NCS 2022:

- **383 filas duplicadas** (3,931 filas para 3,548 folios distintos).
- **49 folios que no existen en el ERP en ningún año.**
- **0 folios del ERP faltantes en el Excel** — el ERP no perdía nada.

El Excel además guardaba las canceladas como renglones en cero con la palabra
"CANCELADA" donde va el cliente (2,484 en total), una convención que había que
conocer para no restarlas dos veces.

## Lo que el consolidador hacía bien, por si alguien tiene que repetirlo

Leía ~400 hojas repartidas en nueve carpetas anuales con unos 35 formatos
distintos. Cuatro cosas suyas valían y se conservaron como ideas en el
desarrollo actual:

1. **Detección tolerante de encabezados** — no exigía un nombre exacto de
   columna. Vive hoy en `finanzas/adaptador_formatos.py`.
2. **Ventana de recuperación de cinco filas** — un renglón basura a media tabla
   no cortaba la lectura.
3. **Registro de lo que no reconocía**, en vez de omitirlo en silencio. Es la
   misma regla que hoy gobierna todo el desarrollo.
4. **Las cifras declaradas guardadas aparte**, para poder comparar contra la
   suma real. De ahí salió la regla número uno: **nunca sumar leyendo una fila
   de "TOTAL"** — había 8 hojas donde el total escrito no coincidía con la suma
   de sus propias filas.

## Qué lo reemplaza

- `finanzas/erp/extraer_facturacion.py` — cabeceras de ventas y compras.
- `finanzas/erp/extraer_estados_financieros.py` — catálogo de cuentas y saldos.
- `finanzas/erp/registro_conectores.py` — el conector es intercambiable.

## Lo único que el ERP todavía no cubre

**Paragon Logistics no está dada de alta en el ERP.** Sus facturas existían solo
en el Excel. La ruta acordada es darla de alta desde la configuración de la
aplicación, no reanimar el consolidador.
