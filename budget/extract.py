"""Orquestador: detecta el banco, infiere el periodo del corte y parsea."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytesseract

from budget.ocr import render_pdf_pages
from budget.parsers import PARSERS, ParseResult
from budget.parsers.base import TESS_CFG

MESES_ARCHIVO = {
    "ENE": "01", "FEB": "02", "MAR": "03", "ABR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AGO": "08", "SEP": "09", "SEP": "09", "OCT": "10",
    "NOV": "11", "DIC": "12",
}


def detect_bank(pdf: str | Path) -> str:
    """Detecta el banco por OCR de la portada (paginas 1-2)."""
    from PIL import Image
    imgs = render_pdf_pages(pdf, pages=(1, 2), dpi=150)
    for path in imgs:
        txt = pytesseract.image_to_string(
            Image.open(path), lang="spa", config=f"{TESS_CFG} --psm 6").upper()
        if "HSBC" in txt:
            return "HSBC"
        if "SANTANDER" in txt:
            return "Santander"
    raise ValueError(f"No se pudo detectar el banco de {pdf}")


def infer_statement_period(pdf: str | Path, result: ParseResult | None = None) -> str:
    """Periodo de corte 'YYYY-MM'. Primero por nombre de archivo, luego por
    la fecha maxima de los movimientos (mes de corte)."""
    name = Path(pdf).stem.upper()

    m = re.search(r"(20\d{2})-(\d{2})-\d{2}", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    m = re.search(r"\b(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)", name)
    if m:
        year_m = re.search(r"(20\d{2})", name)
        year = year_m.group(1) if year_m else None
        if year:
            return f"{year}-{MESES_ARCHIVO[m.group(1)]}"

    # respaldo: mes de la fecha mas reciente de los movimientos
    if result and result.transactions:
        fechas = [t.fecha_cargo or t.fecha_operacion for t in result.transactions]
        fechas = [f for f in fechas if f]
        if fechas:
            latest = max(fechas)
            return f"{latest.year}-{latest.month:02d}"
    return ""


def parse_statement(pdf: str | Path) -> ParseResult:
    """Pipeline completo para un PDF de estado de cuenta."""
    bank = detect_bank(pdf)
    parser = PARSERS[bank]()
    period = infer_statement_period(pdf)
    result = parser.parse(pdf, statement_period=period)
    if not period:
        # re-intentar el periodo con la fecha maxima ya parseada
        period = infer_statement_period(pdf, result)
        if period:
            for tx in result.transactions:
                tx.statement_period = period
    return result
