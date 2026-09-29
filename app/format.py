"""Formatierung im Schweizer Stil."""

from datetime import date
from decimal import Decimal

TAUSENDER = "’"  # typografischer Apostroph: 1’234.50


def chf(betrag: Decimal | None) -> str:
    if betrag is None:
        return ""
    text = f"{Decimal(betrag):,.2f}"
    return text.replace(",", TAUSENDER)


def menge(wert: Decimal | None) -> str:
    """3.00 → 3, 1.50 → 1.5"""
    if wert is None:
        return ""
    d = Decimal(wert)
    if d == d.to_integral_value():
        return f"{d.quantize(Decimal(1)):,}".replace(",", TAUSENDER)
    return format(d.normalize(), "f")


def datum(wert: date | str | None) -> str:
    if not wert:
        return ""
    if isinstance(wert, str):
        wert = date.fromisoformat(wert)
    return wert.strftime("%d.%m.%Y")
