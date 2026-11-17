"""Categorizacion automatica de gastos por reglas de palabras clave.

Las reglas viven en la tabla reglas_categoria de la base de datos (se
pueden agregar/quitar desde la interfaz). La primera regla que coincida
con la descripcion (por orden de id) gana.
"""

from __future__ import annotations

import re
import sqlite3
from functools import lru_cache

from budget.parsers.base import Transaction

CATEGORIAS = [
    "Comida y bebida",
    "Supermercado y abarrotes",
    "Gasolina y transporte",
    "Facturas y servicios",
    "Hogar y mantenimiento",
    "Compras y electronica",
    "Compras en linea",
    "Salud y farmacia",
    "Mascotas",
    "Entretenimiento y ocio",
    "Suscripciones y gym",
    "Seguros",
    "Otros",
]

CATEGORIA_DEFAULT = "Otros"

# Reglas iniciales basadas en los comercios de los estados de cuenta
# reales del usuario. Se insertan con INSERT OR IGNORE, asi que las que
# edite/borre el usuario no se restauran.
REGLAS_DEFAULT: dict[str, list[str]] = {
    "Comida y bebida": [
        "REST", "SUSHI", "PIZZA", "DOMINOS", "PECHANG", "YUPPIP",
        "STARBUCK", "CAFE", "BARISTA", "MERPAGO", "FOOD", "BURGER",
        "KFC", "TACO", "MC DONALD", "MCDONALD", "WING", "TORTA",
        "MENUD", "PANADER", "HELADER", "CHEESECAKE",
    ],
    "Supermercado y abarrotes": [
        "WALMART", "WAL MART", "BODEGA", "SUPERAMA", "COSTCO", "SAMS",
        "SORIANA", "CHEDRAUI", "HEB", "AKI", "OXXO", "ELEVEN",
        "CIRCULO K", "ARCO", "AHORRO MELA", "DIANA", "OROMELO",
        "SANTA CATARINA", "HUICAL",
    ],
    "Gasolina y transporte": [
        "GASOL", "PEMEX", "DISTGAS", "COMBUSTIBLES", "CM DEL MAYAB",
        "UBER", "DIDI", "CABIFY", "ESTACION", "PARQUIM", "TOLL",
        "CASETA",
    ],
    "Facturas y servicios": [
        "TELMEX", "TELCEL", "CFE", "LUZ", "JAPAY", "AGUA", "INTERNET",
        "SKY", "TOTALPLAY", "IZZI", "MEGACABLE", "TELEFONIA",
        "PAGO POR TRANSFERENCIA",
    ],
    "Hogar y mantenimiento": [
        "FERRE", "BOXITO", "HOME DEPOT", "HOMEMART", "LUMBRERA",
        "PINTERA", "CERAMICA", "MOBILIARIO", "MUEBLE",
    ],
    "Compras y electronica": [
        "STEREN", "TCH 850701", "ELECTRO", "ELECTRIC", "MUEBLERIA",
        "ZAPATER", "ROPA", "BOUTIQUE", "SUBURBIA", "C&A", "LIVERPOOL",
        "PALACIO", "Sears", "SEARS",
    ],
    "Compras en linea": [
        "AMAZON", "MERCADOLIBRE", "MERCADO LIBRE", "ALIEXPRESS",
        "SHEIN", "EBAY", "CLIP MX",
    ],
    "Salud y farmacia": [
        "FARM", "DROG", "SANITAS", "LABORATOR", "OPTICA", "DENTAL",
        "SIMILARES", "GUADALAJARA", "MEDICA", "CLINICA",
    ],
    "Mascotas": ["VET", "AGROPUPPI", "PETCO", "PET"],
    "Entretenimiento y ocio": [
        "CINE", "CINEPOLIS", "CINEMEX", "STEAM", "PLAYSTATION",
        "XBOX", "NINTENDO", "PARQUE", "MUSEO",
    ],
    "Suscripciones y gym": [
        "NETFLIX", "SPOTIFY", "HBO", "DISNEY", "PRIME VIDEO",
        "ICLOUD", "GOOGLE", "APPLE", "MICROSOFT", "SMARTFIT", "GYM",
    ],
    "Seguros": ["GNP", "SEGURO", "QUALITAS", "AXA", "MAPFRE"],
}


def _norm(desc: str) -> str:
    return " ".join((desc or "").upper().split())


def seed_reglas(con: sqlite3.Connection) -> None:
    """Inserta las reglas iniciales si no existen (no toca las del usuario)."""
    con.executemany(
        "INSERT OR IGNORE INTO reglas_categoria (categoria, patron) VALUES (?, ?)",
        [(cat, pat) for cat, pats in REGLAS_DEFAULT.items() for pat in pats],
    )
    con.commit()


def reglas(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT id, categoria, patron FROM reglas_categoria "
        "ORDER BY id").fetchall()


def agregar_regla(con: sqlite3.Connection, categoria: str, patron: str) -> bool:
    patron = patron.strip().upper()
    if not patron:
        return False
    try:
        con.execute("INSERT INTO reglas_categoria (categoria, patron) VALUES (?, ?)",
                    (categoria, patron))
        con.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def borrar_regla(con: sqlite3.Connection, regla_id: int) -> None:
    con.execute("DELETE FROM reglas_categoria WHERE id = ?", (regla_id,))
    con.commit()


@lru_cache(maxsize=512)
def _patron_regex(patron: str) -> "re.Pattern[str]":
    """Patron como regex con fronteras de palabra.

    'REST' coincide en 'REST SUSHI ROLL' pero NO dentro de 'FLOREST'
    (que no es un restaurante).
    """
    return re.compile(r"(?<![A-Z0-9])" + re.escape(patron) + r"(?![A-Z0-9])")


def categorizar(desc: str, reglas_cache: list[tuple[str, str]] | None = None) -> str:
    """Categoria para una descripcion segun las reglas (primera coincidencia).

    Primero se intentan los patrones respetando fronteras de palabra; si
    nada coincide, se cae a la coincidencia simple como respaldo.
    """
    if reglas_cache is None:
        con = _con_tmp()
        reglas_cache = [(r["categoria"], r["patron"]) for r in reglas(con)]
    d = _norm(desc)
    for categoria, patron in reglas_cache:
        if _patron_regex(patron).search(d):
            return categoria
    for categoria, patron in reglas_cache:
        if patron in d:
            return categoria
    return CATEGORIA_DEFAULT


def _con_tmp():
    from budget.db import connect
    return connect()


def aplicar_a_movimiento(t: Transaction, reglas_cache=None) -> str:
    t.categoria = categorizar(t.descripcion, reglas_cache)
    return t.categoria


def recategorizar_todo(con: sqlite3.Connection) -> int:
    """Recalcula la categoria de todos los movimientos con la tabla de reglas."""
    cache = [(r["categoria"], r["patron"]) for r in reglas(con)]
    rows = con.execute("SELECT id, descripcion FROM movimientos").fetchall()
    n = 0
    for r in rows:
        cat = categorizar(r["descripcion"], cache)
        con.execute("UPDATE movimientos SET categoria = ? WHERE id = ?",
                    (cat, r["id"]))
        n += 1
    con.commit()
    return n


def fijar_categoria(con: sqlite3.Connection, mov_id: int, categoria: str) -> None:
    con.execute("UPDATE movimientos SET categoria = ? WHERE id = ?",
                (categoria, mov_id))
    con.commit()
