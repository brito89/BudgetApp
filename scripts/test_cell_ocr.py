"""Experimento de configuraciones OCR sobre una celda de monto conocida."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pytesseract
from PIL import Image

from budget.parsers.base import TESS_CFG

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

RAW = Image.open(r"C:\Users\Brito\AppData\Local\Temp\opencode\cell_raw.png")   # $ 27.00
RAW2 = Image.open(r"C:\Users\Brito\AppData\Local\Temp\opencode\cell_863.png")  # $ 863.50
T3 = Image.open(r"C:\Users\Brito\AppData\Local\Temp\opencode\cell_tight.png")

BIN = T3.point(lambda p: 255 if p > 150 else 0).convert("L")


def run(im, cfg, lang="spa"):
    try:
        return pytesseract.image_to_string(im, lang=lang, config=f"{TESS_CFG} {cfg}").strip()
    except Exception as e:
        return f"ERR {e}"


tests = [
    ("raw   psm7      ", RAW, "--psm 7"),
    ("raw   psm7  wl   ", RAW, "--psm 7 -c tessedit_char_whitelist=0123456789$.,+-"),
    ("raw   psm13     ", RAW, "--psm 13"),
    ("tight3 psm7      ", T3, "--psm 7"),
    ("tight3 psm13     ", T3, "--psm 13"),
    ("tight3 psm6      ", T3, "--psm 6"),
    ("tight3 bin psm13 ", BIN, "--psm 13"),
    ("tight3 eng psm13 ", T3, "--psm 13", "eng"),
    ("raw863 psm7      ", RAW2, "--psm 7"),
    ("raw863 psm13     ", RAW2, "--psm 13"),
    ("raw863 bin psm13 ", RAW2.point(lambda p: 255 if p > 150 else 0).convert("L"), "--psm 13"),
    ("raw863 eng psm13 ", RAW2, "--psm 13", "eng"),
]

for t in tests:
    name, im, cfg = t[0], t[1], t[2]
    lang = t[3] if len(t) > 3 else "spa"
    print(f"{name} [{lang}] -> {run(im, cfg, lang)!r}")
