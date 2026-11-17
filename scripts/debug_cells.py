"""Diagnostico: vuelca las celdas crudas de las tablas de un PDF."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from PIL import Image

from budget.ocr import render_pdf_pages
from budget.parsers.base import page_lines, table_rows
from budget.parsers.hsbc import HSBCParser

pdf = sys.argv[1] if len(sys.argv) > 1 else r"G:\My Drive\Bancos\Hsbc\2026-10-16_Estado de cuenta.pdf"
only_page = int(sys.argv[2]) if len(sys.argv) > 2 else 0

p = HSBCParser()
images = render_pdf_pages(pdf, dpi=300)

kind = card = None
for n, path in enumerate(images, start=1):
    if only_page and n != only_page:
        continue
    img = Image.open(path)
    lines = page_lines(img)
    segments = []
    seg_start = 0
    seg_kind = kind
    seg_card = card if card is not None else (None, None)

    def close_segment(until_y):
        global seg_start
        if seg_kind and seg_card[0] and until_y - seg_start > 60:
            segments.append((seg_start, until_y, seg_kind, seg_card))
        seg_start = until_y

    for ln in lines:
        u = ln.upper()
        if p.SECTION_MSI_RE.search(u):
            close_segment(ln.y0)
            seg_kind = "msi"
            print(f"[pg{n}] SECCION MSI @y{ln.y0}")
            continue
        if p.SECTION_REG_RE.search(u):
            close_segment(ln.y0)
            seg_kind = "regular"
            print(f"[pg{n}] SECCION REGULAR @y{ln.y0}")
            continue
        m = p.CARD_RE.search(u)
        if m:
            close_segment(ln.y0)
            seg_card = (m.group(1).lower()[:8], m.group(2).replace(" ", "")[-4:])
            print(f"[pg{n}] TARJETA {seg_card} @y{ln.y0}")
            continue
        if p.TOTAL_RE.search(u):
            print(f"[pg{n}] TOTAL: {ln.text!r} @y{ln.y0}")

    if seg_kind and seg_card[0]:
        close_segment(img.size[1] - 40)
    kind, card = seg_kind, seg_card

    for y0, y1, k, cd in segments:
        rows = table_rows(img, y0, y1)
        print(f"\n[pg{n}] REGION {k} {cd} y=[{y0},{y1}] -> {len(rows)} filas")
        for r in rows:
            texts = [" ".join(c.text.split()) for c in r.cells]
            print(f"  y={r.cells[0].box[1]:5d} n={len(texts)} | " +
                  " | ".join(t[:24] for t in texts))
