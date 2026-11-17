"""Prueba del modelo de cuotas MSI: reimporta los dos estados de cuenta
(conservando gastos manuales) y muestra el gasto por mes calendario."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from budget.db import connect, df_movimientos, guardar_movimientos
from budget.importer import analizar_pdf, confirmar

SAMPLES = [
    r"G:\My Drive\Bancos\Hsbc\2026-10-16_Estado de cuenta.pdf",
    r"G:\My Drive\Bancos\Santander\Estado de cuenta Oct 2026.pdf",
]

con = connect()
# conservar solo los gastos manuales
con.execute("DELETE FROM movimientos WHERE banco != 'Manual'")
con.execute("DELETE FROM importaciones")
con.commit()

for pdf in SAMPLES:
    previa = analizar_pdf(pdf)
    print(f"\n{Path(pdf).name}: {len(previa.transacciones)} movimientos "
          f"({'OK' if previa.validacion_ok else 'FALLO'})")
    confirmar(previa, con)
    print(f"  guardados: {previa.nuevos} nuevos / {previa.duplicados} duplicados")
    n2, d2 = guardar_movimientos(con, previa.transacciones)
    print(f"  dedup: {n2} nuevos / {d2} duplicados "
          f"{'OK' if n2 == 0 and d2 == previa.nuevos + previa.duplicados else 'FALLO'}")

df = df_movimientos(con)
print(f"\nTotal en DB: {len(df)}")

print("\n=== Gasto por mes calendario (solo cuenta_gasto=1) ===")
g = df[(df["monto_dec"] > 0) & (df["cuenta_gasto"] == 1)]
rep = g.groupby("mes")["monto_dec"].agg(["sum", "count"])
print(rep)

print("\n=== Cuotas MSI generadas (HSBC) ===")
msi = df[(df["seccion"] == "msi") & (df["banco"] == "HSBC")]
print(msi[["mes", "descripcion", "monto", "msi_pago_num",
           "msi_pago_total"]].to_string(index=False))

print("\n=== Plan MSI informativo (Santander) ===")
plan = df[(df["seccion"] == "msi") & (df["banco"] == "Santander")]
print(plan[["mes", "descripcion", "monto", "cuenta_gasto"]].to_string(index=False))

print("\n=== Gasto por mes y categoria (2026-09 y 2026-10) ===")
for mes in ("2026-09", "2026-10"):
    sub = g[g["mes"] == mes].groupby("categoria")["monto_dec"].sum()
    print(f"\n-- {mes} (total {sub.sum()}) --")
    print(sub.sort_values(ascending=False).head(6))
