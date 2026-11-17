"""Prueba de la categorizacion con fronteras de palabra."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from budget.categorize import categorizar

pruebas = [
    ("NWM 970924444 BODEGA EXPRESS FLOREST MER", "Supermercado y abarrotes"),
    ("ELEVEN T2760 FLORESTA SEM 980701STA", "Supermercado y abarrotes"),
    ("REST SUSHI ROLL MERIDA IRO 140529175", "Comida y bebida"),
    ("REST TEXAS MONTEJO OTM 160920108", "Comida y bebida"),
    ("FARM F CARRETERA MOTUL MPB 891006LR6", "Salud y farmacia"),
    ("SMP 040315FH0 GASOL MONTECARLO MER", "Gasolina y transporte"),
    ("TELMEX CARGO RECURR 3 CIU", "Facturas y servicios"),
    ("SU PAGO GRACIAS", "Otros"),
]

ok = True
for desc, esperado in pruebas:
    got = categorizar(desc)
    estado = "OK   " if got == esperado else "FALLO"
    ok &= got == esperado
    print(f"{estado} {desc[:42]:44s} -> {got}")

print("RESULTADO:", "EXITO" if ok else "REVISAR")
