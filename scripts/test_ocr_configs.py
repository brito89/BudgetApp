"""Prueba de configuraciones OCR: DPI y PSM sobre las paginas de movimientos
de HSBC, para ver si se recuperan los montos que se perdieron a 200 DPI.

Montos que faltaron en la corrida a 200 DPI:
  249.40, 637.00, 179.96, 111.00, 219.03, 160.10(fue ok), 100.00(fue ok)
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from budget.ocr import ocr_pdf  # noqa: E402

HSBC = r"G:\My Drive\Bancos\Hsbc\2026-10-16_Estado de cuenta.pdf"

# Montos que deben aparecer en las paginas de movimientos (lista completa
# leida visualmente del PDF, paginas 4 y 5)
KNOWN_AMOUNTS = [
    "38,774.96",  # SU PAGO GRACIAS
    "249.40", "637.00", "57.00", "2,902.96", "179.96", "139.00", "500.00",
    "2,680.00", "300.00", "150.49", "228.00", "1,111.00", "88.00", "101.00",
    "231.11", "188.10", "1,087.48", "205.50", "39.90", "190.00", "759.00",
    "100.00", "207.00", "160.10", "219.03", "187.85", "330.00", "965.29",
    "627.50", "627.50", "100.00", "273.00",
]


def main() -> None:
    for dpi in (200, 300):
        for psm in (6, 4):
            pages = ocr_pdf(HSBC, pages=(4, 5), dpi=dpi, psm=psm)
            text = "\n".join(pages)
            # normalizar: OCR confunde $->5, [+]->[+1], O->0 en fechas
            found = sum(1 for a in KNOWN_AMOUNTS if a in text)
            print(f"dpi={dpi} psm={psm}: montos encontrados {found}/{len(KNOWN_AMOUNTS)}")
            for a in KNOWN_AMOUNTS:
                if a not in text:
                    print(f"    falta: {a}")
            if dpi == 300 and psm == 6:
                out = Path(__file__).parent / "hsbc_300_psm6.txt"
                out.write_text(text, encoding="utf-8")
                print(f"    texto completo guardado en {out}")


if __name__ == "__main__":
    main()
