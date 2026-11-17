"""Parsers de estados de cuenta por banco."""

from budget.parsers.base import ParseResult, StatementParser, Transaction
from budget.parsers.hsbc import HSBCParser
from budget.parsers.santander import SantanderParser

PARSERS = {
    "HSBC": HSBCParser,
    "Santander": SantanderParser,
}

__all__ = ["ParseResult", "StatementParser", "Transaction",
           "HSBCParser", "SantanderParser", "PARSERS"]
