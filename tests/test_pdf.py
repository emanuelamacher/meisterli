import io
from datetime import date, timedelta
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.rechnen import Position, berechne
from app.rechnung import Adresse, RechnungsDaten, erstelle_pdf, qr_rechnung, teile_strasse
from tests.conftest import TEST_IBAN, als_positionen

FIRMA = Adresse("Elektro Muster GmbH", "Werkstrasse 12", "3011", "Bern")
KUNDE = Adresse("Familie Keller", "Rosenweg 5a", "3006", "Bern")


def rechnungsdaten(positionen, mwst_pflichtig=True, nummer="2026-001") -> RechnungsDaten:
    heute = date(2026, 9, 29)
    return RechnungsDaten(
        nummer=nummer,
        firma=FIRMA,
        uid="CHE-123.456.789 MWST",
        iban=TEST_IBAN,
        kunde=KUNDE,
        rechnungsdatum=heute,
        leistungsdatum=date(2026, 9, 25),
        faellig_am=heute + timedelta(days=30),
        zahlungsfrist_tage=30,
        mwst_pflichtig=mwst_pflichtig,
        positionen=positionen,
        summen=berechne(positionen, mwst_pflichtig),
    )


def pdf_text(pdf: bytes) -> tuple[int, str]:
    reader = PdfReader(io.BytesIO(pdf))
    return len(reader.pages), "\n".join(p.extract_text() for p in reader.pages)


def test_pdf_mit_qr_zahlteil(fall, tmp_path):
    daten = rechnungsdaten(als_positionen(fall))
    ziel = tmp_path / "rechnung.pdf"
    pdf = erstelle_pdf(daten, ziel)

    assert pdf.startswith(b"%PDF")
    assert ziel.read_bytes() == pdf
    seiten, text = pdf_text(pdf)
    assert seiten == 1
    # Pflichtangaben
    for teil in [
        "Elektro Muster GmbH", "CHE-123.456.789 MWST", "Familie Keller", "Rosenweg 5a",
        "Rechnung 2026-001", "29.09.2026", "25.09.2026", "29.10.2026", "MWST 8.1 %",
        fall["netto"], fall["mwst"], fall["total"],
    ]:
        assert teil in text, teil
    # Zahlteil (von qrbill, deutsch)
    for teil in ["Zahlteil", "Empfangsschein", "Konto / Zahlbar an", TEST_IBAN]:
        assert teil in text, teil


def test_qr_daten():
    daten = rechnungsdaten(als_positionen({"positionen": [
        {"beschreibung": "Arbeit", "menge": "3", "einheit": "Std.", "einzelpreis": "90"},
        {"beschreibung": "Schalter", "menge": "2", "einheit": "Stk.", "einzelpreis": "24"},
        {"beschreibung": "Sicherungskasten", "menge": "1", "einheit": "Stk.", "einzelpreis": "180"},
    ]}))
    zeilen = qr_rechnung(daten).qr_data().split("\r\n")
    assert zeilen[0:3] == ["SPC", "0200", "1"]
    assert zeilen[3] == "CH9300762011623852957"
    assert zeilen[4:11] == ["S", "Elektro Muster GmbH", "Werkstrasse", "12", "3011", "Bern", "CH"]
    assert "538.34" in zeilen and "CHF" in zeilen
    assert ["S", "Familie Keller", "Rosenweg", "5a", "3006", "Bern", "CH"] == zeilen[20:27]
    assert zeilen[27:30] == ["NON", "", "Rechnung 2026-001"]
    assert zeilen[30] == "EPD"


def test_pdf_ohne_mwst():
    positionen = [Position("Hecke schneiden", Decimal(5), "Std.", Decimal(75))]
    _, text = pdf_text(erstelle_pdf(rechnungsdaten(positionen, mwst_pflichtig=False)))
    assert "Nicht MWST-pflichtig" in text
    assert "MWST 8.1" not in text
    assert "375.00" in text


def test_viele_positionen_zahlteil_auf_eigener_seite():
    positionen = [Position(f"Arbeit {i}", Decimal(1), "Std.", Decimal(90)) for i in range(30)]
    seiten, text = pdf_text(erstelle_pdf(rechnungsdaten(positionen)))
    assert seiten >= 2
    assert "Zahlteil" in text
    assert "2’700.00" in text


def test_ungueltige_iban():
    daten = rechnungsdaten([Position("x", Decimal(1), "Stk.", Decimal(1))])
    daten.iban = "CH00 0000 0000 0000 0000 0"
    with pytest.raises(ValueError):
        qr_rechnung(daten)


@pytest.mark.parametrize(
    "eingabe, erwartet",
    [
        ("Lindenweg 4", ("Lindenweg", "4")),
        ("Rosenweg 5a", ("Rosenweg", "5a")),
        ("Rue de la Gare 12 B", ("Rue de la Gare", "12B")),
        ("Dorfstrasse", ("Dorfstrasse", "")),
        ("Postfach", ("Postfach", "")),
    ],
)
def test_teile_strasse(eingabe, erwartet):
    assert teile_strasse(eingabe) == erwartet
