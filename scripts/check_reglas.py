"""Diagnostico: reglas BODEGA/ELEVEN y categorias de sus movimientos."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from budget.db import connect, df_movimientos

con = connect()

print("=== Reglas que contienen BODEGA o ELEVEN ===")
for r in con.execute(
        "SELECT id, categoria, patron FROM reglas_categoria "
        "WHERE patron LIKE '%BODEGA%' OR patron LIKE '%ELEVEN%' ORDER BY id"):
    print(f"  id={r['id']:3d}  categoria={r['categoria']:28s} patron={r['patron']}")

print("\n=== Orden: primeras 8 reglas (ganan primero) ===")
for r in con.execute("SELECT id, categoria, patron FROM reglas_categoria ORDER BY id LIMIT 8"):
    print(f"  id={r['id']:3d}  {r['categoria']:28s} {r['patron']}")

df = df_movimientos(con)
ej = df[df["descripcion"].str.contains("BODEGA|ELEVEN", na=False, case=False)]
print(f"\n=== Movimientos con BODEGA/ELEVEN: {len(ej)} ===")
print(ej.groupby("categoria")["id"].count())
print(ej[["descripcion", "categoria"]].head(6).to_string(index=False))
