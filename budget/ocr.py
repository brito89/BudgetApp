"""OCR sobre estados de cuenta PDF.

Los PDFs de HSBC y Santander Mexico son de imagen (sin capa de texto),
asi que el pipeline es: renderizar paginas con Poppler (pdftoppm) y pasarlas
por Tesseract OCR en espanol.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytesseract
from PIL import Image

# Tesseract instalado por winget en Program Files
TESSERACT_EXE = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

# Datos de idioma (spa) dentro del proyecto, porque Program Files no es escribible
TESSDATA_DIR = Path(__file__).resolve().parent.parent / "tessdata"

# Poppler (pdftoppm) ya esta en el PATH del sistema
PDFTOPPM_EXE = "pdftoppm"

pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_EXE)


def render_pdf_pages(
    pdf_path: str | Path,
    pages: tuple[int, int] | None = None,
    dpi: int = 200,
    out_dir: str | Path | None = None,
) -> list[Path]:
    """Renderiza un PDF a PNGs (escala de grises) con Poppler.

    pages: rango 1-based (primera, ultima) inclusive. None = todas.
    Devuelve la lista de PNGs generados, en orden de pagina.
    """
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir or (Path.home() / "AppData/Local/Temp/opencode/budgetapp_ocr"))
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / pdf_path.stem.replace(" ", "_")

    # Limpiar restos de corridas anteriores para no mezclar paginas viejas
    for old in out_dir.glob(f"{prefix.name}*.png"):
        old.unlink()

    cmd = [PDFTOPPM_EXE, "-png", "-gray", "-r", str(dpi)]
    if pages:
        cmd += ["-f", str(pages[0]), "-l", str(pages[1])]
    cmd += [str(pdf_path), str(prefix)]

    subprocess.run(cmd, check=True, capture_output=True)

    # pdftoppm nombra con ceros a la izquierda segun el total de paginas
    generated = sorted(out_dir.glob(f"{prefix.name}*.png"))
    if not generated:
        raise RuntimeError(f"pdftoppm no genero imagenes para {pdf_path.name}")
    return generated


def ocr_image(image_path: str | Path, lang: str = "spa", psm: int = 6) -> str:
    """Extrae texto de una imagen con Tesseract."""
    config = f"--tessdata-dir {TESSDATA_DIR} --psm {psm}"
    return pytesseract.image_to_string(Image.open(image_path), lang=lang, config=config)


def ocr_pdf(
    pdf_path: str | Path,
    pages: tuple[int, int] | None = None,
    dpi: int = 200,
    psm: int = 6,
) -> list[str]:
    """Pipeline completo: PDF -> paginas PNG -> textos OCR (uno por pagina)."""
    images = render_pdf_pages(pdf_path, pages=pages, dpi=dpi)
    return [ocr_image(img, psm=psm) for img in images]


if __name__ == "__main__":
    pdf = sys.argv[1]
    pages = None
    if len(sys.argv) > 3:
        pages = (int(sys.argv[2]), int(sys.argv[3]))
    for i, text in enumerate(ocr_pdf(pdf, pages=pages), start=(pages[0] if pages else 1)):
        print(f"\n{'=' * 70}\n== PAGINA {i} ==\n{'=' * 70}")
        print(text)
