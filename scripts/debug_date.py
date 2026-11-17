"""Diagnostico de celda de fecha '2/-Sep-2026' en HSBC."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pytesseract
from PIL import Image

from budget.ocr import TESSDATA_DIR, render_pdf_pages
from budget.parsers.base import ocr_cell, table_rows

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

pdf = r"G:\My Drive\Bancos\Hsbc\2026-10-16_Estado de cuenta.pdf"
img = Image.open(render_pdf_pages(pdf, dpi=600)[4])
rows = table_rows(img, 0, 2900)
for r in rows:
    t0 = " ".join(r.cells[0].text.split())
    if "/" in t0:
        print("fila:", [" ".join(c.text.split())[:22] for c in r.cells][:3])
        for i in (0, 1):
            box = r.cells[i].box
            raw = img.crop(box)
            print(f"celda{i} box={box} txt={r.cells[i].text!r}")
            print(f"  reOCR tight: {ocr_cell(img, box, 'date')!r}")
            raw2 = raw.resize((raw.size[0] * 2, raw.size[1] * 2), Image.LANCZOS)
            cfg = ("--psm 7 -c "
                   "tessedit_char_whitelist=0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            t = pytesseract.image_to_string(
                raw2, lang="spa",
                config=f"--tessdata-dir {TESSDATA_DIR} {cfg}").strip()
            print(f"  raw x2     : {t!r}")
            raw.save(rf"C:\Users\Brito\AppData\Local\Temp\opencode\datecell{i}.png")
        break
