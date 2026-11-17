"""Capa de almacenamiento local (SQLite).

Todo vive en data/budget.db junto al proyecto: nada sale de la PC.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from budget.parsers.base import Transaction

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "budget.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    banco TEXT NOT NULL,
    tarjeta_tipo TEXT,
    tarjeta_ultimos4 TEXT,
    seccion TEXT NOT NULL,
    fecha_operacion TEXT,
    fecha_cargo TEXT,
    descripcion TEXT NOT NULL,
    monto TEXT NOT NULL,
    msi_pago_num INTEGER,
    msi_pago_total INTEGER,
    msi_monto_original TEXT,
    msi_saldo_pendiente TEXT,
    msi_pago_requerido TEXT,
    tasa TEXT,
    periodo TEXT,
    mes TEXT,
    categoria TEXT,
    origen TEXT NOT NULL DEFAULT 'importado',
    cuenta_gasto INTEGER NOT NULL DEFAULT 1,
    huella TEXT NOT NULL UNIQUE,
    importado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_mov_periodo ON movimientos(periodo);
CREATE INDEX IF NOT EXISTS idx_mov_banco ON movimientos(banco);

CREATE TABLE IF NOT EXISTS reglas_categoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    categoria TEXT NOT NULL,
    patron TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS importaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archivo TEXT NOT NULL,
    banco TEXT,
    periodo TEXT,
    movimientos_nuevos INTEGER,
    movimientos_duplicados INTEGER,
    validacion_ok INTEGER,
    mensajes TEXT,
    importado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _migrar(con)
    _seed(con)
    return con


def _migrar(con: sqlite3.Connection) -> None:
    """Agrega columnas nuevas a bases creadas con versiones anteriores."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(movimientos)").fetchall()}
    if "origen" not in cols:
        con.execute("ALTER TABLE movimientos ADD COLUMN origen TEXT "
                    "NOT NULL DEFAULT 'importado'")
        con.commit()
    if "mes" not in cols:
        con.execute("ALTER TABLE movimientos ADD COLUMN mes TEXT")
        # mes calendario real: el del cargo (o de la compra si no hay cargo)
        con.execute(
            "UPDATE movimientos SET mes = COALESCE(substr(fecha_cargo, 1, 7), "
            "substr(fecha_operacion, 1, 7))")
        con.commit()
    if "cuenta_gasto" not in cols:
        con.execute("ALTER TABLE movimientos ADD COLUMN cuenta_gasto "
                    "INTEGER NOT NULL DEFAULT 1")
        # en Santander la mensualidad MSI se cobra via cargos regulares,
        # por lo que la fila del plan no cuenta como gasto
        con.execute("UPDATE movimientos SET cuenta_gasto = 0 "
                    "WHERE seccion = 'msi' AND banco = 'Santander'")
        con.commit()
    con.execute("CREATE INDEX IF NOT EXISTS idx_mov_mes ON movimientos(mes)")


def _seed(con: sqlite3.Connection) -> None:
    from budget.categorize import seed_reglas
    seed_reglas(con)


def huella(t: Transaction) -> str:
    """Fingerprint unico de un movimiento para deduplicar importaciones.

    Para filas MSI usa el monto original de la compra (no el de la cuota),
    asi una misma compra a meses detectada en varios estados de cuenta
    genera huellas identicas y no se duplica.
    """
    desc = re.sub(r"[^A-Z0-9]", "", (t.descripcion or "").upper())
    fecha = t.fecha_operacion or t.fecha_cargo
    if t.section == "msi" and t.msi_monto_original is not None:
        monto = str(t.msi_monto_original)
    else:
        monto = str(abs(t.monto))
    parts = [
        t.bank,
        t.card_last4 or "",
        fecha.isoformat() if fecha else "",
        monto,
        "cargo" if t.monto > 0 else "abono",
        desc,
        str(t.msi_pago_num or ""),
        str(t.msi_pago_total or ""),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


# Bancos que cobran la mensualidad MSI como cargo regular (la fila del
# plan MSI es informativa). Para el resto, la cuota mensual se genera aqui.
MSI_VIA_REGULAR = {"Santander"}


def _mes_de(fecha: date, offset: int) -> date:
    """Mismo dia del mes en fecha+offset meses, ajustado al ultimo dia valido."""
    import calendar
    m = fecha.month - 1 + offset
    anio = fecha.year + m // 12
    mes = m % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return date(anio, mes, dia)


def _expandir_msi(t: Transaction) -> list[Transaction]:
    """Convierte una compra a meses sin intereses en N cuotas mensuales.

    Cuota actual = pago requerido impreso; las demas = (monto original -
    pago requerido) / cuotas restantes, con ajuste de centavos en la ultima
    cuota no-current para que la suma cierre exacta.
    """
    from decimal import ROUND_HALF_UP, Decimal

    two = Decimal("0.01")
    total = t.msi_pago_total or 1
    num = t.msi_pago_num or 1
    orig = t.msi_monto_original or t.monto
    req = t.msi_pago_requerido

    # montos por cuota (1-based)
    cuotas = []
    if req is not None:
        n_otros = total - 1
        base = ((orig - req) / n_otros).quantize(two, ROUND_HALF_UP) if n_otros else None
        otros_suma = Decimal(0)
        otros_ult = None
        for k in range(total):
            n = k + 1
            if n == num:
                cuotas.append(req)
            else:
                otros_ult = k
                cuotas.append(base)
        if otros_ult is not None:
            otros_suma = sum(c for k, c in enumerate(cuotas)
                             if (k + 1) != num and k != otros_ult)
            cuotas[otros_ult] = orig - req - otros_suma
    else:
        base = (orig / total).quantize(two, ROUND_HALF_UP)
        cuotas = [base] * total
        cuotas[-1] = orig - sum(cuotas[:-1], Decimal(0))

    salidas = []
    for k, amt in enumerate(cuotas):
        fecha = _mes_de(t.fecha_operacion, k)
        salidas.append(Transaction(
            bank=t.bank, card_type=t.card_type, card_last4=t.card_last4,
            section="msi",
            fecha_operacion=fecha, fecha_cargo=fecha,
            descripcion=t.descripcion,
            monto=amt,
            msi_pago_num=k + 1, msi_pago_total=total,
            msi_monto_original=orig, msi_saldo_pendiente=None,
            msi_pago_requerido=amt, tasa=t.tasa,
            statement_period=t.statement_period,
            categoria=t.categoria,
        ))
    return salidas


def _preparar(t: Transaction) -> list[Transaction]:
    """Devuelve las filas a insertar por un movimiento parseado."""
    if t.section == "msi":
        if t.bank in MSI_VIA_REGULAR:
            # Santander cobra la mensualidad como cargo regular cada mes;
            # la fila del plan MSI (monto completo) no se importa
            return []
        return _expandir_msi(t)
    return [t]


def _d(value) -> str | None:
    return str(value) if value is not None else None


def guardar_movimientos(con: sqlite3.Connection,
                        transacciones: list[Transaction]) -> tuple[int, int]:
    """Inserta movimientos ignorando duplicados.

    Devuelve (nuevos, duplicados). Idempotente: reimportar el mismo PDF
    no crea movimientos repetidos.
    """
    cur = con.cursor()
    from budget import categorize
    cache = [(r["categoria"], r["patron"]) for r in categorize.reglas(con)]
    nuevos = dups = 0
    for t in transacciones:
        for item in _preparar(t):
            h = huella(item)
            if cur.execute("SELECT 1 FROM movimientos WHERE huella = ?",
                           (h,)).fetchone():
                dups += 1
                continue
            from budget import categorize
            if not item.categoria:
                item.categoria = categorize.categorizar(item.descripcion, cache)
            fecha_ref = item.fecha_cargo or item.fecha_operacion
            mes = fecha_ref.isoformat()[:7] if fecha_ref else None
            cur.execute(
                """INSERT INTO movimientos
                   (banco, tarjeta_tipo, tarjeta_ultimos4, seccion,
                    fecha_operacion, fecha_cargo, descripcion, monto,
                    msi_pago_num, msi_pago_total, msi_monto_original,
                    msi_saldo_pendiente, msi_pago_requerido, tasa,
                    periodo, mes, categoria, origen, cuenta_gasto, huella)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item.bank, item.card_type, item.card_last4, item.section,
                 item.fecha_operacion.isoformat() if item.fecha_operacion else None,
                 item.fecha_cargo.isoformat() if item.fecha_cargo else None,
                 item.descripcion, str(item.monto),
                 item.msi_pago_num, item.msi_pago_total,
                 _d(item.msi_monto_original), _d(item.msi_saldo_pendiente),
                 _d(item.msi_pago_requerido), item.tasa,
                 item.statement_period, mes, item.categoria, item.bank.lower(),
                 item.cuenta_gasto, h),
            )
            nuevos += 1
    con.commit()
    return nuevos, dups


def eliminar_movimiento(con: sqlite3.Connection, mov_id: int) -> None:
    con.execute("DELETE FROM movimientos WHERE id = ?", (mov_id,))
    con.commit()


def registrar_importacion(con: sqlite3.Connection, archivo: str, banco: str,
                          periodo: str, nuevos: int, duplicados: int,
                          validacion_ok: bool, mensajes: list[str]) -> None:
    con.execute(
        """INSERT INTO importaciones
           (archivo, banco, periodo, movimientos_nuevos, movimientos_duplicados,
            validacion_ok, mensajes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (archivo, banco, periodo, nuevos, duplicados,
         1 if validacion_ok else 0, " | ".join(mensajes)),
    )
    con.commit()


# ------------------------------------------------------------------ consultas

_FILTROS = {
    "banco": "banco = ?",
    "mes": "mes = ?",
    "tarjeta": "tarjeta_ultimos4 = ?",
    "categoria": "categoria = ?",
}


def df_movimientos(con: sqlite3.Connection, texto: str | None = None,
                   **filtros) -> pd.DataFrame:
    q = "SELECT * FROM movimientos WHERE 1=1"
    params: list = []
    for key, clause in _FILTROS.items():
        val = filtros.get(key)
        if val and val not in ("Todos", "Todas"):
            q += f" AND {clause}"
            params.append(val)
    if texto:
        q += " AND descripcion LIKE ?"
        params.append(f"%{texto.upper()}%")
    q += " ORDER BY fecha_operacion, id"
    df = pd.read_sql_query(q, con, params=params)
    if not df.empty:
        df["monto_dec"] = df["monto"].map(Decimal)
    return df


def meses_disponibles(con: sqlite3.Connection) -> list[str]:
    """Meses calendario con movimientos, del mas reciente al mas viejo.

    Solo se muestran hasta un mes en el futuro: los compromisos de cuotas
    MSI mas adelante quedan en la base pero no ensucian los selectores.
    """
    hoy = date.today()
    limite = hoy.year * 12 + hoy.month + 1  # un mes por adelantado
    rows = con.execute(
        "SELECT DISTINCT mes FROM movimientos WHERE mes IS NOT NULL "
        "ORDER BY mes DESC").fetchall()
    out = []
    for r in rows:
        try:
            y, m = int(r["mes"][:4]), int(r["mes"][5:7])
        except (ValueError, TypeError):
            continue
        if y * 12 + m <= limite:
            out.append(r["mes"])
    return out


def tarjetas_disponibles(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        """SELECT banco, tarjeta_ultimos4, tarjeta_tipo, COUNT(*) n
           FROM movimientos GROUP BY banco, tarjeta_ultimos4, tarjeta_tipo
           ORDER BY banco, tarjeta_ultimos4""").fetchall()
    return [dict(r) for r in rows]


def resumen(con: sqlite3.Connection, mes: str | None = None) -> pd.DataFrame:
    """Cargos y abonos por banco/tarjeta para un mes (o todos)."""
    q = """SELECT banco, tarjeta_ultimos4,
                  SUM(CASE WHEN CAST(monto AS REAL) > 0
                       THEN CAST(monto AS REAL) ELSE 0 END) AS cargos,
                  SUM(CASE WHEN CAST(monto AS REAL) < 0
                       THEN CAST(monto AS REAL) ELSE 0 END) AS abonos,
                  COUNT(*) AS movimientos
           FROM movimientos"""
    params: list = []
    if mes and mes != "Todos":
        q += " WHERE mes = ?"
        params.append(mes)
    q += " GROUP BY banco, tarjeta_ultimos4 ORDER BY banco, tarjeta_ultimos4"
    return pd.read_sql_query(q, con, params=params)


def stats_generales(con: sqlite3.Connection) -> dict:
    r = con.execute("SELECT COUNT(*) n FROM movimientos").fetchone()
    n_import = con.execute("SELECT COUNT(*) n FROM importaciones").fetchone()
    return {"movimientos": r["n"], "importaciones": n_import["n"]}
