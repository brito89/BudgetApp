# 💳 BudgetApp

Control de gastos local para México: arrastra los estados de cuenta **PDF** de
tus tarjetas de crédito **Santander** y **HSBC** y la app los lee con OCR,
extrae cada movimiento, lo categoriza y te muestra cuánto y en qué gastas
**por mes calendario** — todo en tu PC, sin que tus datos salgan de ella.

Licencia: [MIT](LICENSE).

---

## ✨ Qué hace

| Función | Detalle |
|---|---|
| 📥 Importar PDF | Drag & drop de estados de cuenta (1–3 min por archivo por el OCR) |
| ✅ Extracción validada | Cada importación se valida contra los totales impresos en el propio estado de cuenta (exacta al centavo) |
| 🔁 Deduplicación | Reimportar el mismo PDF no crea duplicados (ni reimportar el siguiente estado que re-imprime cuotas MSI) |
| 🧾 Categorización | Reglas palabra clave → categoría (Comida y bebida, Facturas y servicios, Gasolina…). Puedes crear/borrar reglas en la app |
| ✍️ Gasto manual | Para lo que no aparece en estados (efectivo, hipoteca, renta…) |
| 📊 Reportes | Pastel por categorías, gasto por mes, evolución mensual, gasto por comercio |
| 💳 MSI | Las compras a meses sin intereses se cuentan **por mensualidad**, cada mes que toca |
| 🔒 100% local | SQLite en tu PC. Nada sale de tu máquina |

## 🖥 Requisitos (ya instalados en esta PC)

- **Python 3.12** (`winget install Python.Python.3.12`)
- **Tesseract OCR** con idioma español (`winget install UB-Mannheim.TesseractOCR`;
  el idioma `spa` está en la carpeta `tessdata/` del proyecto)
- **Poppler** (`pdftotext`/`pdftoppm` en el PATH, vía winget)
- Librerías Python: `pip install -r requirements.txt` (streamlit, pandas,
  plotly, pytesseract, pillow, numpy)

## 🚀 Cómo usarla

1. Doble clic en **`Ejecutar_BudgetApp.bat`** → se abre en tu navegador
   (`http://localhost:8501`).
2. Pestaña **📥 Importar**: arrastra los PDF mensuales y confirma.
3. Pestaña **✍️ Gasto manual**: registra gastos que no salen en los estados.
4. Pestaña **🧾 Categorías**: revisa el pastel del mes; si algo quedó mal
   clasificado, agrega una regla (se aplica a todo el histórico al instante)
   o edita la categoría directo en la tabla de movimientos.

### Flujo mensual sugerido

- Cuando llegue el corte (Santander ~día 10, HSBC ~día 16), descarga el PDF
  desde la app del banco y arrástralo a BudgetApp.
- Cada estado cubre ~1 mes de movimientos; la app los asigna al **mes
  calendario real** de cada cargo (el estado de octubre reparte entre
  septiembre y octubre).
- Las cuotas MSI futuras se pre-cargan solo hasta **un mes adelante** en los
  selectores, para no ensuciar la navegación.

## 🗂 Estructura

```
BudgetApp/
├─ app.py                    # interfaz Streamlit (5 páginas)
├─ budget/
│  ├─ ocr.py                 # PDF → imágenes (Poppler) → texto (Tesseract)
│  ├─ extract.py             # detecta banco + periodo, orquesta
│  ├─ parsers/               # base.py + hsbc.py + santander.py
│  ├─ categorize.py          # reglas palabra clave → categoría
│  ├─ db.py                  # SQLite, dedup por huella, expansión MSI
│  └─ importer.py            # vista previa → confirmación
├─ data/
│  ├─ budget.db              # ← tus datos (respalda esta carpeta)
│  └─ uploads/               # copias de los PDFs importados
├─ scripts/                  # pruebas y diagnósticos (verify_ocr, test_import…)
└─ tessdata/spa.traineddata  # idioma español para OCR
```

## 🔍 Cómo funciona la extracción

Los PDFs de HSBC/Santander son de **imagen** (sin capa de texto), así que:

1. Se renderizan a **600 DPI** con Poppler.
2. Tesseract lee cada página y localiza secciones (`Meses sin intereses`,
   `Cargos regulares`) y tarjetas (titular / adicional).
3. Las tablas se detectan por sus **líneas de borde** (análisis de píxeles)
   y cada celda se lee con la configuración óptima (montos con whitelist de
   dígitos, fechas con psm 8, signo con whitelist `+-`).
4. **Validación**: la suma de los movimientos debe cuadrar con los
   `Total de cargos / abonos` impresos. Si no cuadra, la importación se
   marca ⚠️ para revisión — nunca se te colarán montos erróneos en silencio.

Detalles por banco que quedan codificados:

- **HSBC**: el `Total cargos` impreso incluye los montos originales de las
  compras MSI nuevas del ciclo (`01 de NN`).
- **Santander**: cobra la mensualidad MSI **como cargo regular** (ej. el
  `$997.50` de ATT DROCASA cada mes), por lo que la fila del plan MSI
  (monto completo) **no se importa** — solo salen los cobros mensuales.

## 💾 Respaldo

Todo tu historial vive en `data/budget.db`. Basta con copiar esa carpeta
(`data/`) para respaldar o migrar a otra PC (junto con el proyecto).

## 🧰 Solución de problemas

| Síntoma | Qué hacer |
|---|---|
| La app no abre | Verifica que Tesseract esté en `C:\Program Files\Tesseract-OCR` y Poppler en el PATH (`pdftotext -v`) |
| Importación marcada ⚠️ | Revisa la pestaña Movimientos: si los montos se ven bien fue un total del banco con otro criterio; si no, reporta el PDF problemático |
| Un comercio mal categorizado | Categorías → agregar regla con la palabra clave exacta como aparece en el estado |
| Puerto ocupado | Corre `streamlit run app.py --server.port 8502` |

## 🛠 Scripts útiles (carpeta `scripts/`)

- `verify_ocr.py` — prueba el OCR contra un PDF de ejemplo
- `verify_parsers.py` — extrae y valida ambos bancos, exporta CSV
- `test_import.py` / `test_msi.py` / `test_categorias.py` — pruebas de
  importación, deduplicación y categorización

> ⚠️ Los scripts de prueba **borran movimientos** para reproducir escenarios
> limpios — no los corras si ya tienes tus datos reales guardados.
