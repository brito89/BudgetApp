"""Prueba de importacion: importa los dos estados de cuenta, verifica la
deduplicacion re-importando, y muestra resumen de la base de datos."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from budget.db import connect, df_movimientos, guardar_movimientos, resumen
from budget.importer import analizar_pdf, confirmar

SAMPLES = [
    r"G:\My Drive\Bancos\Hsbc\2026-10-16_Estado de cuenta.pdf",
    r"G:\My Drive\Bancos\Santander\Estado de cuenta Oct 2026.pdf",
]

con = connect()
# empezar con base limpia para la prueba
con.execute("DELETE FROM movimientos")
con.execute("DELETE FROM importaciones")
con.commit()

for pdf in SAMPLES:
    previa = analizar_pdf(pdf)
    print(f"\n{Path(pdf).name}")
    print(f"  banco={previa.banco} periodo={previa.periodo} "
          f"validacion={'OK' if previa.validacion_ok else 'FALLO'} "
          f"movimientos={len(previa.transacciones)}")
    confirmar(previa, con)
    print(f"  -> guardados: {previa.nuevos} nuevos / {previa.duplicados} duplicados")

    # prueba de deduplicacion: guardar de nuevo las mismas transacciones
    n2, d2 = guardar_movimientos(con, previa.transacciones)
    print(f"  -> reimport (dedup): {n2} nuevos / {d2} duplicados "
          f"{'OK' if (n2 == 0 and d2 == len(previa.transacciones)) else 'FALLO'}")

df = df_movimientos(con)
print(f"\nTotal en DB: {len(df)}")
print(resumen(con))
print("\nPor periodo:")
print(df.groupby("periodo")["monto_dec"].agg(["sum", "count"]))
print("\nPrimeras 5 filas:")
print(df[["banco", "tarjeta_ultimos4", "fecha_operacion", "descripcion",
          "monto"]].head())
