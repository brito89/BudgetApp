"""Diagnostico HSBC: filas de tablas regulares y de totales a 600 DPI."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from PIL import Image

from budget.ocr import render_pdf_pages
from budget.parsers.base import ocr_cell, page_lines, table_rows
from budget.parsers.hsbc import HSBCParser

pdf = r"G:\My Drive\Bancos\Hsbc\2026-10-16_Estado de cuenta.pdf"
images = render_pdf_pages(pdf, dpi=600)
p = HSBCParser()

for n in (4, 5):
    img = Image.open(images[n - 1])
    lines = page_lines(img)
    for ln in lines:
        u = ln.upper()
        if p.CARD_RE.search(u) or p.SECTION_REG_RE.search(u) or p.SECTION_MSI_RE.search(u):
            print(f"[pg{n}] y={ln.y0:5d} {ln.text[:70]!r}")
        if p.TOTAL_RE.search(u):
            print(f"[pg{n}] TOTAL y={ln.y0:5d} {ln.text!r}")

    # regiones fijas conocidas por el debug previo
    for y0, y1, label in ((460, 1400, "titular"), (2860, 4300, "adicional")):
        rows = table_rows(img, y0, y1)
        print(f"\n[pg{n}] {label}: {len(rows)} filas")
        for r in rows:
            texts = [" ".join(c.text.split()) for c in r.cells]
            joined = " ".join(texts).upper()
            if "TOTAL" in joined:
                print(f"  TOTAL fila: {texts}")
                for i in range(len(r.cells) - 1, 0, -1):
                    if any(ch.isdigit() for ch in texts[i]):
                        retry = ocr_cell(r.img, r.cells[i].box, "amount")
                        print(f"    celda[{i}] txt={texts[i]!r} reOCR={retry!r}")
                continue
            last = texts[-1]
            retry = ocr_cell(r.img, r.cells[-1].box, "amount")
            sign = ocr_cell(r.img, r.cells[-2].box, "sign") if len(texts) > 1 else ""
            print(f"  {texts[0][:12]:12s} last={last!r:22s} reOCR={retry!r:16s} "
                  f"sign={sign!r}")
    print()
