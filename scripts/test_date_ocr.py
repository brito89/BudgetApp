"""Experimento: OCR de la celda de fecha con y sin whitelist."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pytesseract
from PIL import Image

from budget.ocr import TESSDATA_DIR

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

IMG = Image.open(r"C:\Users\Brito\AppData\Local\Temp\opencode\datecell0.png")

variants = []
for scale in (1, 2, 3):
    im = IMG if scale == 1 else IMG.resize((IMG.size[0] * scale, IMG.size[1] * scale), Image.LANCZOS)
    for psm in (6, 7, 8, 13):
        variants.append((f"x{scale} psm{psm} sin-wl", im, f"--psm {psm}"))
variants.append(("x2 psm7 dig-wl", IMG.resize((IMG.size[0] * 2, IMG.size[1] * 2), Image.LANCZOS),
                 "--psm 7 -c tessedit_char_whitelist=0123456789-SepOct-" ))

for name, im, cfg in variants:
    txt = pytesseract.image_to_string(
        im, lang="spa", config=f"--tessdata-dir {TESSDATA_DIR} {cfg}").strip()
    print(f"{name:20s} -> {txt!r}")
