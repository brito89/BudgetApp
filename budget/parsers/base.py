"""Motor generico de extraccion de tablas de estados de cuenta (PDFs de imagen).

Estrategia:
1. Renderizar paginas a 300 DPI (Poppler) y OCR de la pagina completa para
   localizar lineas de texto (encabezados de seccion, tarjeta, totales).
2. Detectar la cuadricula de cada tabla por sus bordes (analisis de pixeles
   con numpy) y extraer celda por celda.
3. Re-OCR de celdas criticas (montos con whitelist de caracteres, fechas).
4. Validar contra los totales impresos en el propio estado de cuenta.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

import numpy as np
import pytesseract
from PIL import Image

from budget.ocr import TESSDATA_DIR, render_pdf_pages

TESS_CFG = f"--tessdata-dir {TESSDATA_DIR}"

MESES = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}

AMOUNT_IN_TEXT_RE = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")


# ---------------------------------------------------------------- modelo

@dataclass
class Word:
    text: str
    x0: int
    y0: int
    x1: int
    y1: int


@dataclass
class OcrLine:
    words: list[Word]

    @property
    def y0(self) -> int:
        return min(w.y0 for w in self.words)

    @property
    def y1(self) -> int:
        return max(w.y1 for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    def upper(self) -> str:
        return self.text.upper()


@dataclass
class Cell:
    text: str
    box: tuple[int, int, int, int]  # x0, y0, x1, y1 absolutos en la pagina


@dataclass
class Row:
    img: Image.Image
    cells: list[Cell]


@dataclass
class Table:
    kind: str  # "regular" | "msi"
    card: tuple[Optional[str], Optional[str]]  # (tipo, ultimos4)
    rows: list[Row] = field(default_factory=list)
    transactions: list["Transaction"] = field(default_factory=list)

    @property
    def cargos_sum(self) -> Decimal:
        return sum((t.monto for t in self.transactions if t.monto > 0), Decimal(0))

    @property
    def abonos_sum(self) -> Decimal:
        return sum((t.monto for t in self.transactions if t.monto < 0), Decimal(0))


@dataclass
class Transaction:
    bank: str = ""
    card_type: Optional[str] = None
    card_last4: Optional[str] = None
    section: str = "regular"  # "regular" | "msi"
    fecha_operacion: Optional[date] = None
    fecha_cargo: Optional[date] = None
    descripcion: str = ""
    monto: Decimal = Decimal(0)  # + cargo, - abono
    msi_pago_num: Optional[int] = None
    msi_pago_total: Optional[int] = None
    msi_monto_original: Optional[Decimal] = None
    msi_saldo_pendiente: Optional[Decimal] = None
    msi_pago_requerido: Optional[Decimal] = None
    tasa: Optional[str] = None
    statement_period: Optional[str] = None  # "YYYY-MM"
    categoria: Optional[str] = None
    cuenta_gasto: int = 1  # 0 = fila informativa (plan MSI Santander)


@dataclass
class ParseResult:
    transactions: list[Transaction] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    totals: list[tuple[str, Decimal]] = field(default_factory=list)
    validation_ok: bool = False
    validation_mode: str = ""
    messages: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)  # filas con fecha que no parsearon


# ---------------------------------------------------------------- OCR base

def page_lines(img: Image.Image) -> list[OcrLine]:
    """Lineas de texto de una pagina con coordenadas (image_to_data)."""
    data = pytesseract.image_to_data(
        img, lang="spa", config=f"{TESS_CFG} --psm 6",
        output_type=pytesseract.Output.DICT,
    )
    groups: dict[tuple, list[Word]] = {}
    n = len(data["text"])
    for i in range(n):
        t = (data["text"][i] or "").strip()
        if not t:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        groups.setdefault(key, []).append(
            Word(t, data["left"][i], data["top"][i],
                 data["left"][i] + data["width"][i],
                 data["top"][i] + data["height"][i])
        )
    lines = [OcrLine(sorted(ws, key=lambda w: w.x0)) for ws in groups.values()]
    lines.sort(key=lambda l: l.y0)
    return lines


def _cluster(idx: list[int], gap: int = 4) -> list[int]:
    """Agrupa indices casi consecutivos (bordes de 2-3 px de grosor)."""
    out: list[list[int]] = []
    for i in idx:
        if out and i - out[-1][-1] <= gap:
            out[-1].append(i)
        else:
            out.append([i])
    return [int(round(sum(g) / len(g))) for g in out]


def _tight_crop(crop: Image.Image) -> Image.Image:
    """Recorta al bounding box del contenido, ignorando restos de bordes."""
    a = np.asarray(crop.convert("L"))
    h, w = a.shape
    m = 3  # margen descartado (restos de linea de borde)
    if h <= 2 * m or w <= 2 * m:
        return crop
    dark = a[m:h - m, m:w - m] < 160
    if not dark.any():
        return crop
    ys, xs = np.where(dark)
    pad = 4
    y0p = max(int(ys.min()) + m - pad, 0)
    y1p = min(int(ys.max()) + m + pad, h)
    x0p = max(int(xs.min()) + m - pad, 0)
    x1p = min(int(xs.max()) + m + pad, w)
    return crop.crop((x0p, y0p, x1p, y1p))


def ocr_cell(img: Image.Image, box, mode: str = "text") -> str:
    x0, y0, x1, y1 = box
    crop = img.crop((max(x0, 0), max(y0, 0), x1, y1))
    if crop.size[0] < 8 or crop.size[1] < 8:
        return ""
    if mode in ("amount", "sign"):
        crop = _tight_crop(crop)
        # el escalado 2x mejora mucho la lectura de digitos pequeños
        crop = crop.resize((crop.size[0] * 2, crop.size[1] * 2), Image.LANCZOS)
    elif mode == "date":
        # para fechas el recorte ajustado altera la segmentacion ('27'->'21');
        # se usa el recuadro completo con escalado moderado
        crop = crop.resize((crop.size[0] * 2, crop.size[1] * 2), Image.LANCZOS)
    if mode == "amount":
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789$.,+-"
    elif mode == "date":
        # sin whitelist: el whitelist degrada al motor LSTM ('27'->'2-S')
        cfg = "--psm 8"
    elif mode == "sign":
        cfg = "--psm 7 -c tessedit_char_whitelist=+-"
    else:
        cfg = "--psm 6"
    txt = pytesseract.image_to_string(crop, lang="spa", config=f"{TESS_CFG} {cfg}")
    return " ".join(txt.split())


def table_rows(img: Image.Image, y0: int, y1: int) -> list[Row]:
    """Extrae las filas de la tabla con bordes dentro de [y0, y1).

    Bordes horizontales: a nivel de region. Bordes verticales: por votacion
    entre filas (un borde real esta presente en casi todas las filas; las
    columnas de texto solo producen falsos positivos aislados).
    """
    a = np.asarray(img.convert("L"))
    y1c = min(y1, a.shape[0])
    if y1c - y0 < 60:
        return []
    region = a[y0:y1c, :]
    dark = region < 140

    row_frac = dark.mean(axis=1)
    h_lines = _cluster([i for i, f in enumerate(row_frac) if f > 0.75])
    if len(h_lines) < 2:
        return []

    bands = [(ta, tb) for ta, tb in zip(h_lines, h_lines[1:]) if tb - ta >= 18]
    if len(bands) < 2:
        return []

    width = region.shape[1]
    votes = np.zeros(width, dtype=int)
    for ta, tb in bands:
        col_frac = dark[ta:tb, :].mean(axis=0)
        votes += col_frac > 0.9  # un borde real ocupa toda la altura de la fila
    border_ok = votes / len(bands) > 0.6

    # runs de columnas de borde (un borde mide 3-8 px de grosor)
    runs: list[list[int]] = []
    for x in (x for x in range(width) if border_ok[x]):
        if runs and x - runs[-1][-1] <= 3:
            runs[-1].append(x)
        else:
            runs.append([x])
    if len(runs) < 2:
        return []

    rows: list[Row] = []
    for ta, tb in bands:
        cells: list[Cell] = []
        for r1, r2 in zip(runs, runs[1:]):
            x0, x1 = r1[-1] + 2, r2[0] - 2
            if x1 - x0 < 14:
                continue
            box = (x0, y0 + ta + 3, x1, y0 + tb - 3)
            cells.append(Cell(ocr_cell(img, box, "text"), box))
        if cells:
            rows.append(Row(img=img, cells=cells))
    return rows


# ---------------------------------------------------------------- parseo

def normalize_month(tok: str) -> Optional[int]:
    tok = tok.upper()
    if tok in MESES:
        return MESES[tok]
    m = difflib.get_close_matches(tok, list(MESES), n=1, cutoff=0.6)
    return MESES[m[0]] if m else None


def parse_date(text: str, ref_year: int) -> Optional[date]:
    """Parsea fechas tipo '14-Oct-2026' tolerando errores OCR del mes."""
    m = re.search(r"(\d{1,2})[-\s]([A-Z0-9]{3})[-\s](\d{4})", text.upper())
    if not m:
        return None
    d, mon, y = int(m.group(1)), normalize_month(m.group(2)), int(m.group(3))
    if mon is None or not (1 <= d <= 31):
        return None
    if y > ref_year:  # el OCR confunde 6->8; el ano nunca excede el del corte
        y = ref_year
    try:
        return date(y, mon, d)
    except ValueError:
        return None


def parse_amount(text: str) -> Optional[Decimal]:
    """Parseo estricto de montos: exige formato monetario con centavos.

    Rechaza texto con espacios internos entre digitos, decoraciones de la
    caja de signo ('[+1$') u otros caracteres ajenos (senales de OCR
    corrompido) para forzar el re-OCR con whitelist.
    """
    s = " ".join(text.split()).upper()
    if not s:
        return None
    if "[" in s or "(" in s:  # decoracion de caja de signo -> re-OCR
        return None
    neg = s.lstrip().startswith("-")
    body = s.lstrip("+- ").replace("$", " ").strip()
    if re.search(r"\d\s+\d", body):          # '9 2/.00' -> dudoso
        return None
    if re.search(r"[^0-9.,]", body):         # letras, '/', etc.
        return None
    if not re.fullmatch(r"\d+(,\d{3})*\.\d{2}", body):
        return None
    ent = body.split(".")[0]
    if ent.startswith("0") and ent != "0" and len(ent) > 1:
        return None                          # '063.50' -> dudoso
    v = Decimal(body.replace(",", ""))
    return -v if neg else v


def parse_amount_lenient(text: str) -> Optional[Decimal]:
    """Parseo tolerante (ultimo recurso tras re-OCR con whitelist)."""
    s = " ".join(text.split()).upper()
    s = re.sub(r"[^0-9.,]", "", s)
    if not s:
        return None
    if "." not in s and "," not in s and len(s) > 2:
        s = s[:-2] + "." + s[-2:]  # el OCR perdio el punto decimal
    else:
        s = s.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", s):
        return None
    ent = s.split(".")[0]
    if ent.startswith("0") and ent != "0" and len(ent) > 1:
        return None
    return Decimal(s)


DATE_LOOSE_RE = re.compile(r"\d{1,2}\s*[-/.]\s*[A-Z0-9]{2,3}\s*[-/.]\s*\d{4}")


def _looks_like_date(text: str) -> bool:
    return bool(DATE_LOOSE_RE.search(text.upper()))


def clean_description(text: str) -> str:
    t = text.replace(">>>", " ").replace("|", " ").replace("+", " ")
    t = " ".join(t.split())
    return t.strip(" -_")


# ---------------------------------------------------------------- parser

@dataclass
class _TotalRec:
    keyword: str  # cargos | abonos
    amount: Decimal


class StatementParser:
    """Parser generico de estados de cuenta HSBC/Santander Mexico."""

    NAME = ""
    # En HSBC el 'Total cargos' impreso incluye los montos originales de las
    # compras a meses sin intereses; en Santander solo las compras regulares.
    CARGOS_INCLUDES_MSI = False
    SECTION_MSI_RE = re.compile(r"COMPRAS Y CARGOS DIFERIDOS A MESES SIN INTERESES", re.I)
    SECTION_REG_RE = re.compile(r"CARGOS,?\s+ABONOS Y COMPRAS REGULARES", re.I)
    CARD_RE = re.compile(r"TARJETA\s+(TITULAR|ADICIONA\w*)\s*:?\s*([\d\s]{6,})", re.I)
    TOTAL_RE = re.compile(r"TOTAL\s+(?:DE\s+)?(CARGOS|ABONOS)", re.I)

    def parse(self, pdf: str | Path, statement_period: Optional[str] = None) -> ParseResult:
        images = render_pdf_pages(pdf, dpi=600)
        tables: list[Table] = []
        total_recs: list[_TotalRec] = []
        line_total_recs: list[_TotalRec] = []  # respaldo si la cuadricula falla
        raw_years: list[int] = []
        kind: Optional[str] = None
        card: tuple[Optional[str], Optional[str]] = (None, None)

        for path in images:
            img = Image.open(path)
            lines = page_lines(img)
            page_h = img.size[1]
            segments: list[tuple[int, int, str, tuple]] = []
            seg_start = 0
            seg_kind, seg_card = kind, card

            def close_segment(until_y: int) -> None:
                nonlocal seg_start
                if seg_kind and seg_card[0] and until_y - seg_start > 60:
                    segments.append((seg_start, until_y, seg_kind, seg_card))
                seg_start = until_y

            for ln in lines:
                u = ln.upper()
                if self.SECTION_MSI_RE.search(u):
                    close_segment(ln.y0)
                    seg_kind = "msi"
                    continue
                if self.SECTION_REG_RE.search(u):
                    close_segment(ln.y0)
                    seg_kind = "regular"
                    continue
                m = self.CARD_RE.search(u)
                if m:
                    close_segment(ln.y0)
                    seg_card = (m.group(1).lower()[:8],
                                m.group(2).replace(" ", "")[-4:])
                    continue
                tm = self.TOTAL_RE.search(u)
                if tm:  # respaldo por linea de texto (la via fiable es por celda)
                    amts = AMOUNT_IN_TEXT_RE.findall(u)
                    if amts:
                        line_total_recs.append(
                            _TotalRec(tm.group(1).lower(),
                                      Decimal(amts[-1].replace(",", ""))))

            if seg_kind and seg_card[0]:
                close_segment(page_h - 40)
            kind, card = seg_kind, seg_card

            for y0, y1, k, cd in segments:
                rows = table_rows(img, y0, y1)
                if not rows:
                    continue
                t = Table(kind=k, card=cd)
                t.rows = rows
                tables.append(t)
                for row in rows:
                    texts = [c.text for c in row.cells]
                    joined = " ".join(texts).upper()
                    tm = self.TOTAL_RE.search(joined)
                    if tm:
                        amt = self._total_amount_from_row(row)
                        if amt is not None:
                            total_recs.append(_TotalRec(tm.group(1).lower(), amt))
                        continue
                    for c in texts[:2]:
                        for ytok in re.findall(r"(\d{1,2})-([A-Z0-9]{3})-(\d{4})",
                                               c.upper()):
                            raw_years.append(int(ytok[2]))

        # ano de referencia: el del periodo del corte, o el modal de las fechas
        if statement_period:
            ref_year = int(statement_period[:4])
        elif raw_years:
            ref_year = max(set(raw_years), key=raw_years.count)
        else:
            ref_year = date.today().year

        result = ParseResult(tables=tables)
        # totales: la linea completa de texto suele leerse mejor que las
        # celdas fragmentadas de la fila de totales; preferirla por keyword
        by_kw_line = {}
        for r in line_total_recs:
            by_kw_line.setdefault(r.keyword, r.amount)
        by_kw_grid = {}
        for r in total_recs:
            by_kw_grid.setdefault(r.keyword, r.amount)
        for kw in ("cargos", "abonos"):
            amt = by_kw_line.get(kw, by_kw_grid.get(kw))
            if amt is not None:
                mag = abs(amt)
                result.totals.append((kw, mag if kw == "cargos" else -mag))

        for t in tables:
            for row in t.rows:
                tx = self.parse_row(row, t.kind, ref_year)
                if tx is None:
                    joined = " ".join(" ".join(c.text.split()) for c in row.cells)
                    if re.search(r"\d{1,2}\s*[-/]\s*[A-Z0-9]{2,3}\s*[-/]\s*\d{4}",
                                 joined.upper()):
                        result.rejected.append(joined[:130])
                    continue
                tx.bank = self.NAME
                tx.card_type, tx.card_last4 = t.card
                tx.statement_period = statement_period
                t.transactions.append(tx)
                result.transactions.append(tx)

        # totales ya recogidos arriba; normalizar signo por palabra clave
        norm = []
        for kw, amt in result.totals:
            mag = abs(amt)
            norm.append((kw, mag if kw == "cargos" else -mag))
        result.totals = norm

        self._validate(result)
        return result

    # ------------------------------------------------------------ filas

    def parse_row(self, row: Row, kind: str, ref_year: int) -> Optional[Transaction]:
        texts = [" ".join(c.text.split()) for c in row.cells]
        if not texts:
            return None
        fecha = self._date_cell(row, 0, ref_year)
        if fecha is None:
            return None  # encabezado, totales o ruido
        if kind == "msi":
            return self._parse_msi_row(row, texts, fecha, ref_year)
        return self._parse_regular_row(row, texts, fecha, ref_year)

    def _parse_regular_row(self, row: Row, texts, fecha, ref_year) -> Optional[Transaction]:
        # layout: fecha | fecha cargo | descripcion | [signo] | monto
        idx = 1
        fecha_cargo = None
        if len(texts) > 2:
            fecha_cargo = self._date_cell(row, 1, ref_year)
            if fecha_cargo is not None:
                idx = 2
            elif _looks_like_date(texts[1]):
                # la fecha de cargo no parseo pero la celda contiene una
                # fecha: es la columna de fecha de cargo; no mezclarla
                # con la descripcion
                idx = 2
        if fecha_cargo is not None and fecha_cargo < fecha:
            # la fecha de cargo nunca es anterior a la de operacion:
            # reintentar y si persiste, aserarla a la de operacion
            alt = parse_date(ocr_cell(row.img, row.cells[1].box, "date"), ref_year)
            fecha_cargo = alt if (alt and alt >= fecha) else fecha
        desc = " ".join(texts[idx:-1]).strip()
        monto = self._amount_from_right(row, texts)
        if monto is None:
            return None
        amount_idx = len(row.cells) - 1
        if self._is_abono(row, texts, amount_idx) and monto > 0:
            monto = -monto
        desc = clean_description(desc)
        if not desc:
            return None
        return Transaction(
            section="regular", fecha_operacion=fecha, fecha_cargo=fecha_cargo,
            descripcion=desc, monto=monto,
        )

    def _is_abono(self, row: Row, texts, amount_idx: int) -> bool:
        """True si la fila es abono (signo '-' en su celda o en el monto)."""
        if "-" in texts[amount_idx]:
            return True  # el signo viene pegado al monto ('- $13,345.06')
        if amount_idx >= 1:
            s = texts[amount_idx - 1].replace("|", "").strip()
            if s == "-":
                return True
            retry = ocr_cell(row.img, row.cells[amount_idx - 1].box, "sign").strip()
            if retry.startswith("-"):
                return True
            # ultimo recurso: OCR de la region combinada signo+monto
            b1 = row.cells[amount_idx - 1].box
            b2 = row.cells[amount_idx].box
            combo = ocr_cell(row.img, (b1[0], min(b1[1], b2[1]),
                                       b2[2], max(b1[3], b2[3])), "amount")
            if "-" in combo:
                return True
        return False

    def _parse_msi_row(self, row: Row, texts, fecha, ref_year) -> Optional[Transaction]:
        # layout: fecha | desc | monto original | saldo pend. | pago req. | num | tasa
        # (las ultimas columnas pueden venir fusionadas en una sola celda)
        if len(texts) < 5:
            return None
        desc = clean_description(texts[1])
        monto = self._numeric_cell(row, 2, texts)
        if monto is None or not desc:
            return None
        saldo = self._numeric_cell(row, 3, texts)
        tail = " ".join(texts[4:]).upper()

        pago_req = self._numeric_cell(row, 4, texts)
        if pago_req is None:
            m = AMOUNT_IN_TEXT_RE.search(texts[4])
            if m:
                pago_req = Decimal(m.group().replace(",", ""))

        num = total = None
        mn = re.search(r"(\d{1,2})\s*DE\s*(\d{1,2})", tail)
        if mn:
            num, total = int(mn.group(1)), int(mn.group(2))

        tasa = next((t for t in texts[5:] if "%" in t), None)
        if tasa is None and "%" in texts[4]:
            m = re.search(r"[\d.,]+\s*%", texts[4])
            tasa = m.group() if m else None
        return Transaction(
            section="msi", fecha_operacion=fecha, fecha_cargo=None,
            descripcion=desc, monto=monto,
            msi_pago_num=num, msi_pago_total=total,
            msi_monto_original=monto, msi_saldo_pendiente=saldo,
            msi_pago_requerido=pago_req, tasa=tasa,
        )

    def _numeric_cell(self, row: Row, idx: int, texts) -> Optional[Decimal]:
        v = parse_amount(texts[idx])
        if v is not None:
            return v
        retry = ocr_cell(row.img, row.cells[idx].box, "amount")
        v = parse_amount(retry)
        if v is not None:
            return v
        return parse_amount_lenient(retry)

    # ------------------------------------------------------------ celdas

    def _date_cell(self, row: Row, idx: int, ref_year: int) -> Optional[date]:
        text = row.cells[idx].text
        d = parse_date(text, ref_year)
        if d is None and idx < len(row.cells):
            retry = ocr_cell(row.img, row.cells[idx].box, "date")
            d = parse_date(retry, ref_year)
        return d

    def _amount_from_right(self, row: Row, texts) -> Optional[Decimal]:
        # el monto esta en una de las ultimas 2 celdas (monto o signo+monto);
        # nunca buscar en celdas mas a la izquierda (la descripcion contiene
        # numeros que no son montos)
        for i in list(range(len(row.cells) - 1, max(len(row.cells) - 3, 0), -1)):
            v = parse_amount(texts[i])
            if v is not None:
                return v
            retry = ocr_cell(row.img, row.cells[i].box, "amount")
            v = parse_amount(retry)
            if v is not None:
                return v
            v = parse_amount_lenient(retry)
            if v is not None:
                return v
        return None

    def _total_amount_from_row(self, row: Row) -> Optional[Decimal]:
        """Monto de una fila de totales.

        Preferencia: texto crudo de la celda (suele ser limpio) -> limpieza
        de decoraciones + regex con signo -> re-OCR con whitelist.
        """
        texts = [" ".join(c.text.split()) for c in row.cells]
        for i in range(len(row.cells) - 1, 0, -1):
            t = texts[i]
            if not re.search(r"\d", t):
                continue
            v = parse_amount(t)
            if v is not None:
                return v
            # limpiar decoraciones de la caja de signo ('[+1$', '[-]$') y usar
            # la ultima cifra del texto, con el signo que la precede
            c = (t.replace("[", " ").replace("]", " ")
                  .replace("(", " ").replace(")", " ").replace("|", " "))
            last = None
            for last in AMOUNT_IN_TEXT_RE.finditer(c):
                pass
            if last is not None:
                neg = "-" in c[:last.start()]
                return Decimal(last.group().replace(",", "")) * (-1 if neg else 1)
            retry = ocr_cell(row.img, row.cells[i].box, "amount")
            v = parse_amount(retry)
            if v is not None:
                return v
            v = parse_amount_lenient(retry)
            if v is not None:
                return v
        return None

    # ------------------------------------------------------------ validacion

    def _validate(self, result: ParseResult) -> None:
        reg = [t for t in result.tables if t.kind == "regular" and t.transactions]
        recs_c = [amt for kw, amt in result.totals if kw == "cargos"]
        recs_a = [amt for kw, amt in result.totals if kw == "abonos"]

        if not reg:
            result.messages.append("No se detecto ninguna tabla regular")
            return
        if not recs_c or not recs_a:
            result.messages.append("No se encontraron totales de cargos/abonos "
                                   "para validar")
            return

        pos = sum((t.cargos_sum for t in reg), Decimal(0))
        neg = sum((t.abonos_sum for t in reg), Decimal(0))

        # interpretaciones del 'Total de cargos' impreso:
        #  - solo compras regulares (Santander)
        #  - regulares + montos originales de MSI nuevos del ciclo,
        #    es decir compras a '01 de NN' (HSBC)
        candidates = [("solo compras regulares", pos)]
        msi_nuevo = sum((tx.msi_monto_original or tx.monto
                         for t in result.tables if t.kind == "msi"
                         for tx in t.transactions if tx.msi_pago_num == 1),
                        Decimal(0))
        if msi_nuevo and pos + msi_nuevo != pos:
            candidates.append(("regulares + compras MSI nuevas del ciclo",
                               pos + msi_nuevo))

        ok, mode = False, ""
        for name, cval in candidates:
            if cval in recs_c and neg in recs_a:
                ok, mode = True, name
                break

        result.validation_ok = ok
        result.validation_mode = mode
        if ok:
            result.messages.append(f"Validacion OK ({mode}): suma de movimientos "
                                   f"== totales impresos")
        else:
            esperados = f"cargos {recs_c} / abonos {recs_a}"
            calculados = [(str(t.card[1]), str(t.cargos_sum), str(t.abonos_sum))
                          for t in reg]
            result.messages.append(
                f"VALIDACION FALLO: esperados {esperados}; "
                f"calculados por tabla {calculados} -> revisar")
