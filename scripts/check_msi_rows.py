"""Revision: filas MSI guardadas y limpieza de planes totales (Santander)."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import sqlite3

con = sqlite3.connect(r"C:\Users\Brito\Documents\Git\BudgetApp\data\budget.db")
con.row_factory = sqlite3.Row
rows = con.execute(
    "SELECT id, banco, seccion, cuenta_gasto, descripcion, monto, mes "
    "FROM movimientos WHERE seccion = 'msi'").fetchall()
for r in rows:
    print(dict(r))
print("total movimientos:",
      con.execute("SELECT COUNT(*) c FROM movimientos").fetchone()["c"])
print("planes a borrar:",
      con.execute("SELECT COUNT(*) c FROM movimientos WHERE seccion='msi' "
                  "AND cuenta_gasto=0").fetchone()["c"])

if "--borrar" in sys.argv:
    n = con.execute("DELETE FROM movimientos WHERE seccion='msi' "
                    "AND cuenta_gasto=0").rowcount
    con.commit()
    print(f"ELIMINADOS: {n}")
    print("total restante:",
          con.execute("SELECT COUNT(*) c FROM movimientos").fetchone()["c"])
