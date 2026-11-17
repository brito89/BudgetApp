"""Prueba de categorizacion + gasto manual + reporte por categorias."""

import io
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from budget.categorize import recategorizar_todo
from budget.db import (connect, df_movimientos, guardar_movimientos,
                       meses_disponibles)
from budget.parsers.base import Transaction

con = connect()
n = recategorizar_todo(con)
print(f"Recategorizados: {n}")

# gasto manual de ejemplo (luz CFE, tipico gasto que no aparece en estados)
t = Transaction(
    bank="Manual", card_type="manual", card_last4="EFECTIVO",
    section="manual",
    fecha_operacion=date(2026, 11, 15), fecha_cargo=date(2026, 11, 15),
    descripcion="Recibo de luz CFE noviembre",
    monto=Decimal("487.00"),
    statement_period="2026-11",
    categoria="Facturas y servicios",
)
n, d = guardar_movimientos(con, [t])
print(f"Gasto manual: {n} nuevos / {d} duplicados")

# gasto manual en efectivo de comida
t2 = Transaction(
    bank="Manual", card_type="manual", card_last4="EFECTIVO",
    section="manual",
    fecha_operacion=date(2026, 11, 14), fecha_cargo=date(2026, 11, 14),
    descripcion="Comida en la loncheria",
    monto=Decimal("85.50"),
    statement_period="2026-11",
)
n2, d2 = guardar_movimientos(con, [t2])
print(f"Gasto manual 2 (sin categoria -> auto): {n2} nuevos")

# dedup del manual
n3, d3 = guardar_movimientos(con, [t])
print(f"Reimport manual (dedup): {n3} nuevos / {d3} duplicados")

df = df_movimientos(con)
print(f"\nTotal en DB: {len(df)}")
print(f"Meses: {meses_disponibles(con)}")

# reporte por categorias del mes calendario 2026-10
octubre = df[(df["mes"] == "2026-10") & (df["monto_dec"] > 0)]
rep = (octubre.groupby("categoria")["monto_dec"].sum()
       .sort_values(ascending=False))
print("\n=== Reporte por categorias mes 2026-10 ===")
for cat, monto in rep.items():
    print(f"  {cat:28s} {monto:>12} ({monto / rep.sum() * 100:4.1f}%)")
print(f"  {'TOTAL':28s} {rep.sum():>12}")

print("\n=== Movimientos 2026-11 (manuales) ===")
nov = df[df["mes"] == "2026-11"]
print(nov[["banco", "fecha_operacion", "descripcion", "monto", "categoria"]])
