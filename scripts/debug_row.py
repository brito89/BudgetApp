"""Diagnostico de una fila: muestra el pipeline completo de parseo."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from PIL import Image

from budget.ocr import render_pdf_pages
from budget.parsers.base import (ocr_cell, parse_amount, parse_amount_lenient,
                                 page_lines, table_rows)
from budget.parsers.santander import SantanderParser

pdf = r"G:\My Drive\Bancos\Santander\Estado de cuenta Oct 2026.pdf"
images = render_pdf_pages(pdf, dpi=600)
img = Image.open(images[3])  # pagina 4

lines = page_lines(img)
p = SantanderParser()
seg_start, seg_kind, seg_card = 0, "regular", ("titular", "1246")

# la tabla regular esta entre la linea de tarjeta (~y1026 a 600dpi) y ~y3000
rows = table_rows(img, 1026, 3000)
print(f"filas: {len(rows)}\n")
for r in rows[:8]:
    texts = [" ".join(c.text.split()) for c in r.cells]
    n = len(r.cells)
    print(f"--- fila n={n} | " + " | ".join(t[:22] for t in texts))
    # fecha
    print(f"    fecha txt[0]={texts[0]!r} -> {p._date_cell(r, 0, 2026)}")
    print(f"    fecha txt[1]={texts[1]!r} -> {p._date_cell(r, 1, 2026)}")
    # monto
    last = n - 1
    print(f"    monto txt[{last}]={texts[last]!r} strict={parse_amount(texts[last])}")
    retry = ocr_cell(img, r.cells[last].box, "amount")
    print(f"    monto reOCR={retry!r} strict={parse_amount(retry)} "
          f"lenient={parse_amount_lenient(retry)}")
    prev = ocr_cell(img, r.cells[last - 1].box, "amount")
    print(f"    celda previa reOCR={prev!r} strict={parse_amount(prev)}")
    sign = ocr_cell(img, r.cells[last - 1].box, "sign")
    print(f"    signo reOCR={sign!r}")
    tx = p.parse_row(r, "regular", 2026)
    print(f"    RESULTADO: {tx.monto if tx else None} | {tx.descripcion[:40] if tx else ''}")
    print()
