"""Rechenlogik. Alle Beträge in CHF mit Decimal – das Sprachmodell rechnet nie."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MWST_SATZ = Decimal("8.1")
RAPPEN = Decimal("0.01")


def runden(betrag: Decimal) -> Decimal:
    """Kaufmännisch auf 0.01 runden."""
    return betrag.quantize(RAPPEN, rounding=ROUND_HALF_UP)


def zahl(wert) -> Decimal | None:
    """Wandelt Eingaben wie 90, 1.5, "1'234.50" oder "12,5" in Decimal um.

    Leere Werte ergeben None, Unsinn löst ValueError aus.
    """
    if wert is None:
        return None
    if isinstance(wert, Decimal):
        return wert
    if isinstance(wert, bool):
        raise ValueError(f"Keine Zahl: {wert!r}")
    if isinstance(wert, (int, float)):
        return Decimal(str(wert))
    text = str(wert).strip()
    if not text:
        return None
    for zeichen in ("'", "’", " ", " "):
        text = text.replace(zeichen, "")
    text = text.replace(",", ".")
    try:
        d = Decimal(text)
    except InvalidOperation as e:
        raise ValueError(f"Keine Zahl: {wert!r}") from e
    if not d.is_finite():
        raise ValueError(f"Keine Zahl: {wert!r}")
    return d


@dataclass(frozen=True)
class Position:
    beschreibung: str
    menge: Decimal
    einheit: str
    einzelpreis: Decimal

    @property
    def betrag(self) -> Decimal:
        """Zeilenbetrag = Menge × Einzelpreis (auf Rappen gerundet)."""
        return runden(self.menge * self.einzelpreis)


@dataclass(frozen=True)
class Summen:
    zeilen: list[Decimal]
    netto: Decimal
    mwst_satz: Decimal | None
    mwst: Decimal
    total: Decimal


def berechne(
    positionen: list[Position], mwst_pflichtig: bool = True, satz: Decimal = MWST_SATZ
) -> Summen:
    zeilen = [p.betrag for p in positionen]
    netto = sum(zeilen, Decimal("0.00"))
    if mwst_pflichtig:
        mwst = runden(netto * satz / Decimal(100))
        mwst_satz = satz
    else:
        mwst = Decimal("0.00")
        mwst_satz = None
    return Summen(
        zeilen=zeilen,
        netto=runden(netto),
        mwst_satz=mwst_satz,
        mwst=mwst,
        total=runden(netto + mwst),
    )
