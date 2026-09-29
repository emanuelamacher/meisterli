from decimal import Decimal

import pytest

from app import format as fmt
from app.rechnen import Position, berechne, runden, zahl
from tests.conftest import als_positionen


def test_testfaelle(fall):
    summen = berechne(als_positionen(fall), mwst_pflichtig=True)
    assert summen.netto == Decimal(fall["netto"])
    assert summen.mwst == Decimal(fall["mwst"])
    assert summen.total == Decimal(fall["total"])
    assert summen.mwst_satz == Decimal("8.1")
    assert str(summen.total) == fall["total"]  # zwei Nachkommastellen


def test_zeilenbetraege_keller():
    fall = {
        "positionen": [
            {"beschreibung": "Arbeit", "menge": "3", "einheit": "Std.", "einzelpreis": "90"},
            {"beschreibung": "Schalter", "menge": "2", "einheit": "Stk.", "einzelpreis": "24"},
        ]
    }
    assert berechne(als_positionen(fall)).zeilen == [Decimal("270.00"), Decimal("48.00")]


def test_ohne_mwst(fall):
    summen = berechne(als_positionen(fall), mwst_pflichtig=False)
    assert summen.mwst == Decimal("0.00")
    assert summen.mwst_satz is None
    assert summen.total == Decimal(fall["netto"])


def test_kaufmaennisch_runden():
    # 435.00 × 8.1 % = 35.235 → 35.24 (ROUND_HALF_UP, nicht Banker's Rounding)
    assert runden(Decimal("35.235")) == Decimal("35.24")
    assert runden(Decimal("35.2349")) == Decimal("35.23")


def test_zeile_mit_bruchteilen():
    p = Position("Arbeit", Decimal("1.5"), "Std.", Decimal("33.33"))
    assert p.betrag == Decimal("50.00")  # 49.995 → 50.00


def test_leere_rechnung():
    summen = berechne([])
    assert summen.netto == summen.mwst == summen.total == Decimal("0.00")


@pytest.mark.parametrize(
    "eingabe, erwartet",
    [
        (90, Decimal("90")),
        (1.5, Decimal("1.5")),
        ("1'234.50", Decimal("1234.50")),
        ("1’234.50", Decimal("1234.50")),
        ("12,5", Decimal("12.5")),
        ("", None),
        (None, None),
    ],
)
def test_zahl(eingabe, erwartet):
    assert zahl(eingabe) == erwartet


@pytest.mark.parametrize("eingabe", ["abc", "1.2.3", "nan", True])
def test_zahl_ungueltig(eingabe):
    with pytest.raises(ValueError):
        zahl(eingabe)


@pytest.mark.parametrize(
    "betrag, text",
    [
        (Decimal("1234.5"), "1’234.50"),
        (Decimal("538.34"), "538.34"),
        (Decimal("0"), "0.00"),
        (Decimal("1234567.891"), "1’234’567.89"),
    ],
)
def test_chf_format(betrag, text):
    assert fmt.chf(betrag) == text


def test_menge_format():
    assert fmt.menge(Decimal("3.00")) == "3"
    assert fmt.menge(Decimal("1.50")) == "1.5"
    assert fmt.menge(Decimal("42")) == "42"
