"""Verificacion de Fase 1: corre el OCR sobre las paginas de movimientos
de los dos estados de cuenta de ejemplo y busca los totales que sirven
de checksum para validar la extraccion.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from budget.ocr import ocr_pdf  # noqa: E402

SAMPLES = [
    ("HSBC", r"G:\My Drive\Bancos\Hsbc\2026-10-16_Estado de cuenta.pdf"),
    ("Santander", r"G:\My Drive\Bancos\Santander\Estado de cuenta Oct 2026.pdf"),
]

# Las tablas de movimientos estan en las paginas 3..5 de ambos PDFs
PAGE_RANGE = (3, 5)

# Cadenas que DEBEN aparecer en las paginas 3-5 segun lo verificado
# visualmente contra el PDF a alta resolucion
EXPECTED_TOTALS = {
    "HSBC": [
        "$38,774.96",  # SU PAGO GRACIAS (tarjeta titular)
        "$240.40", "$851.70", "$130.00",  # filas verificadas a alta res.
        "$42,471.02",  # Total cargos
        "$40,656.43",  # Total abonos
    ],
    "Santander": [
        "9,107.08",    # Total de cargos
        "13,345.06",   # Total de abonos / pago por transferencia
        "ATT D ROCASA",
    ],
}


def main() -> None:
    ok_all = True
    for bank, pdf in SAMPLES:
        print(f"\n{'#' * 70}\n# {bank}: {pdf}\n{'#' * 70}")
        pages = ocr_pdf(pdf, pages=PAGE_RANGE, dpi=300, psm=6)
        full_text = "\n".join(pages)
        print(full_text)

        print(f"\n--- Validacion {bank} ---")
        for expected in EXPECTED_TOTALS[bank]:
            found = expected in full_text
            ok_all &= found
            print(f"  [{'OK' if found else 'FALLO'}] {expected!r}")

        # Conteo de lineas de movimiento tipo fecha+descripcion+monto
        lines = [ln for ln in full_text.splitlines() if re.search(r"\d{2}-\w{3}-\d{4}", ln)]
        print(f"  Lineas con fecha detectadas: {len(lines)}")

    print(f"\n{'=' * 70}\nRESULTADO GLOBAL: {'EXITO' if ok_all else 'REVISAR'}")


if __name__ == "__main__":
    main()
