from decimal import Decimal

import pytest

from app.db import Datenbank
from app.gedaechtnis import Gedaechtnis, kern_name


@pytest.fixture
def g(tmp_path):
    return Gedaechtnis(Datenbank(tmp_path / "t.db"))


@pytest.mark.parametrize(
    "name, kern",
    [("Familie Keller", "keller"), ("Fam. Keller", "keller"), ("keller", "keller"),
     ("Herr Meier", "meier"), ("d STWEG Lindenweg 4", "stweg lindenweg 4"), ("Frau", "frau")],
)
def test_kern_name(name, kern):
    assert kern_name(name) == kern


def test_kunde_unscharf(g):
    g.merke_kunde("Familie Keller", "Rosenweg 7", "8404", "Winterthur")
    for name in ["Familie Keller", "familie keller", "Keller", "Fam. Keller", "Familie Kellr"]:
        suche = g.suche_kunde(name)
        assert suche.treffer and suche.treffer["wert"]["ort"] == "Winterthur", name
    assert g.suche_kunde("Herr Meier").treffer is None
    assert g.suche_kunde("").treffer is None


def test_zwei_aehnliche_kunden(g):
    g.merke_kunde("Familie Keller", "Rosenweg 7", "8404", "Winterthur")
    g.merke_kunde("Herr Keller", "Seeweg 1", "6003", "Luzern")
    suche = g.suche_kunde("Keller")
    assert suche.treffer is None
    assert {k["schluessel"] for k in suche.kandidaten} == {"Familie Keller", "Herr Keller"}
    # Der volle Name ist eindeutig
    assert g.suche_kunde("Herr Keller").treffer["wert"]["ort"] == "Luzern"


def test_kunde_auch_in_kundentabelle(g):
    g.merke_kunde("Familie Keller", "Rosenweg 7", "8404", "Winterthur")
    assert g.db.finde_kunde("Familie Keller")["plz"] == "8404"


def test_stundenansatz_begriff_preis(g):
    assert g.stundenansatz() == (None, None)
    g.merke_stundenansatz(Decimal("90"))
    assert g.stundenansatz()[0] == Decimal("90")
    g.merke_stundenansatz(Decimal("95"))  # überschreibt, kein zweiter Eintrag
    assert g.stundenansatz()[0] == Decimal("95")
    assert len(g.alle("stundenansatz")) == 1

    g.merke_begriff("FI", "FI-Schutzschalter")
    assert g.begriff("fi")["wert"]["bedeutung"] == "FI-Schutzschalter"
    assert [e["schluessel"] for e in g.begriffe_in("2 Stund, 1 FI")] == ["FI"]
    assert g.begriffe_in("Filter ersetzen") == []  # nur ganze Wörter

    g.merke_materialpreis("FI-Schutzschalter", Decimal("85"), "Stk.")
    assert g.materialpreis("FI-Schutzschalter")["wert"]["betrag"] == "85"
    assert g.materialpreis("Fi-Schutzschalter")["wert"]["betrag"] == "85"
    assert g.materialpreis("Boiler") is None


def test_relevant_fuer(g):
    g.merke_kunde("Herr Meier", "Bahnhofstrasse 3", "6003", "Luzern")
    g.merke_kunde("Familie Keller", "Rosenweg 7", "8404", "Winterthur")
    g.merke_stundenansatz(Decimal("90"))
    g.merke_begriff("FI", "FI-Schutzschalter")
    g.merke_materialpreis("FI-Schutzschalter", Decimal("85"), "Stk.")
    zeilen = g.relevant_fuer("Rächnig für Herr Meier: 1 FI")
    assert "Stundenansatz: 90 CHF pro Stunde" in zeilen
    assert "Begriff: «FI» bedeutet «FI-Schutzschalter»" in zeilen
    assert "Materialpreis: FI-Schutzschalter 85 CHF pro Stk." in zeilen
    assert "Kunde: Herr Meier, Bahnhofstrasse 3, 6003 Luzern" in zeilen
    assert not any("Keller" in z for z in zeilen)


def test_aendern_loeschen_benutzt(g):
    e = g.merke_begriff("FI", "FI-Schalter")
    g.aendere(e["id"], "FI", {"bedeutung": "FI-Schutzschalter"})
    assert g.begriff("FI")["wert"]["bedeutung"] == "FI-Schutzschalter"
    g.benutzt(g.begriff("FI"))
    assert g.begriff("FI")["benutzt"] == 1
    g.loesche(e["id"])
    assert g.begriff("FI") is None


def test_quelle_rueckfrage(g):
    db = g.db
    gid = db.aktuelles_gespraech()
    eid = db.neuer_chat_entwurf(gid, {})
    rid = db.neue_rueckfrage(gid, eid, "stundenansatz", "", "Welchen Stundenansatz nimmst du?")
    e = g.merke_stundenansatz(Decimal("90"), rueckfrage_id=rid)
    assert e["quelle_rueckfrage_id"] == rid and e["quelle"] == "Rückfrage"
