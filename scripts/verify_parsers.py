"""Verificacion de Fase 2: parsea los dos estados de cuenta de octubre,
muestra los movimientos extraidos y valida contra los totales impresos.
"""

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from budget.extract import parse_statement  # noqa: E402

SAMPLES = [
    ("HSBC", r"G:\My Drive\Bancos\Hsbc\2026-10-16_Estado de cuenta.pdf"),
    ("Santander", r"G:\My Drive\Bancos\Santander\Estado de cuenta Oct 2026.pdf"),
]

HEADERS = ["banco", "tarjeta", "tipo_tarjeta", "seccion", "fecha_oper",
           "fecha_cargo", "descripcion", "monto", "msi", "periodo"]


def main() -> None:
    all_ok = True
    for bank, pdf in SAMPLES:
        print(f"\n{'#' * 78}\n# {bank}: {Path(pdf).name}\n{'#' * 78}")
        result = parse_statement(pdf)

        print(f"Tablas detectadas: {len(result.tables)}")
        for t in result.tables:
            print(f"  - {t.kind:8s} tarjeta {t.card[1]} ({t.card[0]}): "
                  f"{len(t.rows)} filas -> {len(t.transactions)} movimientos "
                  f"[cargos {t.cargos_sum} / abonos {t.abonos_sum}]")

        print(f"\nTotales impresos leidos: {[(k, str(a)) for k, a in result.totals]}")
        print(f"Movimientos extraidos: {len(result.transactions)}")
        for msg in result.messages:
            print(f"  * {msg}")
        if result.rejected:
            print(f"Filas rechazadas ({len(result.rejected)}):")
            for rj in result.rejected:
                print(f"    ? {rj}")

        print("\nMovimientos:")
        for tx in result.transactions:
            msi = (f" {tx.msi_pago_num}/{tx.msi_pago_total}" if tx.msi_pago_num else "")
            print(f"  {tx.fecha_operacion} | {tx.fecha_cargo or '------------'} | "
                  f"{tx.card_last4} | {tx.monto:>10} | {tx.descripcion[:60]}{msi}")

        # export CSV para revision en Excel
        out = Path(__file__).parent / f"extracted_{bank.lower()}.csv"
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(HEADERS)
            for tx in result.transactions:
                w.writerow([
                    tx.bank, tx.card_last4, tx.card_type, tx.section,
                    tx.fecha_operacion, tx.fecha_cargo, tx.descripcion,
                    str(tx.monto),
                    f"{tx.msi_pago_num}/{tx.msi_pago_total}" if tx.msi_pago_num else "",
                    tx.statement_period,
                ])
        print(f"\nCSV: {out}")

        all_ok &= result.validation_ok
        print(f"\n>>> {bank}: {'EXITO' if result.validation_ok else 'REVISAR'}\n")

    print(f"{'=' * 78}\nRESULTADO GLOBAL: {'EXITO' if all_ok else 'REVISAR'}")


if __name__ == "__main__":
    main()
