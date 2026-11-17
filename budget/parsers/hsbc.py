from budget.parsers.base import StatementParser


class HSBCParser(StatementParser):
    NAME = "HSBC"
    # 'Total cargos' incluye los montos originales de compras a meses
    CARGOS_INCLUDES_MSI = True
