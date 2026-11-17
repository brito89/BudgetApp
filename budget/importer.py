"""Importacion de estados de cuenta a la base de datos.

Dos pasos: analizar_pdf() genera una vista previa (sin escribir nada) y
confirmar() guarda los movimientos nuevos ignorando duplicados.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from budget.db import guardar_movimientos, registrar_importacion
from budget.extract import parse_statement


@dataclass
class Previa:
    """Vista previa de una importacion pendiente de confirmar."""

    archivo: str
    banco: str = ""
    periodo: str = ""
    validacion_ok: bool = False
    mensajes: list[str] = field(default_factory=list)
    rechazados: list[str] = field(default_factory=list)
    transacciones: list = field(default_factory=list)
    guardado: bool = False
    nuevos: int = 0
    duplicados: int = 0


def analizar_pdf(pdf: str | Path) -> Previa:
    """Parsea un estado de cuenta y devuelve la vista previa."""
    result = parse_statement(pdf)
    p = Previa(archivo=str(pdf))
    if result.transactions:
        primero = result.transactions[0]
        p.banco = primero.bank
        p.periodo = primero.statement_period or ""
    p.transacciones = result.transactions
    p.validacion_ok = result.validation_ok
    p.mensajes = result.messages
    p.rechazados = result.rejected
    return p


def confirmar(previa: Previa, con: sqlite3.Connection) -> Previa:
    """Guarda los movimientos de la previa (idempotente)."""
    if previa.guardado:
        return previa
    nuevos, duplicados = guardar_movimientos(con, previa.transacciones)
    registrar_importacion(con, Path(previa.archivo).name, previa.banco,
                          previa.periodo, nuevos, duplicados,
                          previa.validacion_ok, previa.mensajes)
    previa.guardado = True
    previa.nuevos = nuevos
    previa.duplicados = duplicados
    return previa
