"""Correccion one-time: convierte a abono las filas 'USO DE SALDO HSBC
CASHBACK' que se guardaron como cargo, y recalcula su huella."""
import io
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import sqlite3

from budget.db import huella, DB_PATH

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row

rows = con.execute(
    "SELECT * FROM movimientos WHERE descripcion LIKE '%USO DE SALDO%' "
    "AND CAST(monto AS REAL) > 0").fetchall()
print(f"filas a corregir: {len(rows)}")
for r in rows:
    monto_nuevo = -Decimal(r["monto"])
    from budget.parsers.base import Transaction
    t = Transaction(
        bank=r["banco"], card_type=r["tarjeta_tipo"], card_last4=r["tarjeta_ultimos4"],
        section=r["seccion"],
        fecha_operacion=date.fromisoformat(r["fecha_operacion"]) if r["fecha_operacion"] else None,
        fecha_cargo=date.fromisoformat(r["fecha_cargo"]) if r["fecha_cargo"] else None,
        descripcion=r["descripcion"], monto=monto_nuevo,
        msi_pago_num=r["msi_pago_num"], msi_pago_total=r["msi_pago_total"],
        msi_monto_original=Decimal(r["msi_monto_original"]) if r["msi_monto_original"] else None,
    )
    huella_nueva = huella(t)
    con.execute(
        "UPDATE movimientos SET monto = ?, huella = ? WHERE id = ?",
        (str(monto_nuevo), huella_nueva, r["id"]))
    print(f"  id={r['id']:4d} {r['descripcion'][:36]:38s} {r['monto']} -> {monto_nuevo}")
con.commit()

n = con.execute(
    "SELECT COUNT(*) c FROM movimientos WHERE descripcion LIKE '%USO DE SALDO%' "
    "AND CAST(monto AS REAL) < 0").fetchone()["c"]
print(f"filas de cashback ahora negativas: {n}")
