"""Zustandsautomat und Gedächtnis-Regeln im Gespräch."""

from decimal import Decimal

import pytest

from app import texte
from tests.chat_hilfen import Chat, texte_von, typen

KELLER = "Rächnig für Familie Keller: 3 Stund à 90, 2 Schalter à 24, Sicherigskaschte 180"
MEIER = "Rächnig für Herr Meier: Boiler entkalche 2 Stund, Aafahrt 45"


@pytest.fixture
def chat(tmp_path):
    return Chat(tmp_path)


def bis_zusammenfassung(chat):
    chat.sende(KELLER)
    return chat.sende("Rosenweg 7, 8404 Winterthur")


def test_fehlende_angabe_genau_eine_frage(chat):
    a = chat.sende(MEIER)  # Stundenansatz UND Adresse fehlen
    assert typen(a) == ["rueckfrage"]
    assert len(chat.db.rueckfragen()) == 1
    entwurf = chat.entwurf()
    assert entwurf["zustand"] == "sammeln"
    assert entwurf["rueckfrage"]["art"] == "stundenansatz"


def test_reihenfolge_begriff_vor_preis_vor_adresse(chat):
    a = chat.sende("Rächnig für Familie Keller: 2 Stund, 1 FI")
    assert texte_von(a) == ["Was meinst du mit «FI»?"]
    a = chat.sende("FI-Schutzschalter")  # Bedeutung ohne Preis
    assert texte_von(a) == [
        "Gemerkt: «FI» = FI-Schutzschalter.",
        "Welchen Stundenansatz nimmst du?",
    ]
    a = chat.sende("90.–")
    assert texte_von(a)[-1] == "Welchen Preis hat «FI-Schutzschalter» pro Stk.?"
    a = chat.sende("85 Fr.")
    assert texte_von(a) == ["Gemerkt: FI-Schutzschalter 85.– pro Stk.", "Welche Adresse hat Familie Keller?"]


def test_kein_pdf_ohne_ja(chat):
    a = bis_zusammenfassung(chat)
    assert a[-1]["typ"] == "zusammenfassung"
    assert chat.db.rechnungen() == []
    assert chat.entwurf()["zustand"] == "bestaetigen"
    a = chat.sende("Ja, erstellen")
    assert typen(a) == ["pdf"]
    assert len(chat.db.rechnungen()) == 1
    assert chat.entwurf() is None  # Entwurf ist erstellt, nicht mehr offen


def test_ja_waehrend_rueckfrage_macht_kein_pdf(chat):
    chat.sende(KELLER)
    a = chat.sende("Ja")
    assert texte_von(a) == [texte.NOCH_OFFEN, "Welche Adresse hat Familie Keller?"]
    assert chat.db.rechnungen() == []
    assert len(chat.db.rueckfragen()) == 1  # dieselbe Frage, kein neuer Eintrag


def test_abbrechen_verwirft_entwurf(chat):
    bis_zusammenfassung(chat)
    entwurf_id = chat.entwurf()["id"]
    assert texte_von(chat.sende("Abbrechen")) == [texte.VERWORFEN]
    assert chat.entwurf() is None
    assert chat.db.chat_entwurf(entwurf_id)["zustand"] == "verworfen"
    assert chat.db.rechnungen() == []
    assert texte_von(chat.sende("Ja")) == [texte.NICHTS_OFFEN]


def test_korrektur_gibt_neue_zusammenfassung(chat):
    bis_zusammenfassung(chat)
    a = chat.sende("Nein, 4 Stunden")
    assert typen(a) == ["zusammenfassung"]
    z = a[0]["inhalt"]
    assert z["positionen"][0]["menge"] == "4"
    assert (z["netto"], z["mwst"], z["total"]) == ("588.00", "47.63", "635.63")
    assert chat.entwurf()["zustand"] == "bestaetigen"


def test_aendern_knopf(chat):
    bis_zusammenfassung(chat)
    assert texte_von(chat.sende("Ändern")) == [texte.AENDERN]
    assert chat.entwurf()["zustand"] == "bestaetigen"


def test_anderes_nur_rechnungen(chat):
    assert texte_von(chat.sende("Wie wird das Wetter morgen?")) == [texte.HILFE]
    chat.sende(KELLER)
    a = chat.sende("Wie wird das Wetter morgen?")
    assert texte_von(a) == [texte.HILFE, "Welche Adresse hat Familie Keller?"]
    assert len(chat.db.rueckfragen()) == 1


def test_adresse_als_satz_ueber_sprachmodell(chat):
    chat.sende(KELLER)
    a = chat.sende("Die wohnen am Rosenweg 7 in 8404 Winterthur")
    assert texte_von(a)[0] == "Gemerkt: Familie Keller, Rosenweg 7, 8404 Winterthur."
    assert a[1]["typ"] == "zusammenfassung"
    # Das Modell bekam Entwurf und offene Rückfrage mit
    nachricht, kontext = chat.modell.aufrufe[-1]
    assert kontext["rueckfrage"] == "Welche Adresse hat Familie Keller?"
    assert kontext["entwurf"]["kunde"]["name"] == "Familie Keller"


def test_eindeutige_antworten_ohne_sprachmodell(chat):
    chat.sende(MEIER)
    chat.sende("90")
    chat.sende("Bahnhofstrasse 3, 6003 Luzern")
    chat.sende("Ja")
    assert [n for n, _ in chat.modell.aufrufe] == [MEIER]


def test_ohne_firmendaten_kein_pdf(chat):
    chat.db.speichere_einstellungen({"firma_name": ""})
    bis_zusammenfassung(chat)
    assert texte_von(chat.sende("Ja")) == [texte.EINSTELLUNGEN_FEHLEN]
    assert chat.db.rechnungen() == []
    assert chat.entwurf()["zustand"] == "bestaetigen"


# Gedächtnis ----------------------------------------------------------------


def test_ausdrueckliches_schlaegt_gespeichertes(chat):
    chat.gedaechtnis.merke_kunde("Familie Keller", "Rosenweg 7", "8404", "Winterthur")
    chat.gedaechtnis.merke_stundenansatz(Decimal("90"))
    a = chat.sende("Rächnig für Familie Keller, Seeweg 2, 8400 Winterthur: 3 Stund à 95")
    assert typen(a) == ["zusammenfassung"]
    z = a[0]["inhalt"]
    assert z["kunde"]["strasse"] == "Seeweg 2" and z["kunde"]["gespeichert"] is False
    assert z["positionen"][0]["preis"] == "95.–" and z["positionen"][0]["gespeichert"] is False
    # Das Gedächtnis bleibt unverändert
    assert chat.gedaechtnis.suche_kunde("Familie Keller").treffer["wert"]["strasse"] == "Rosenweg 7"
    assert chat.gedaechtnis.stundenansatz()[0] == Decimal("90")


def test_gespeicherte_werte_sind_markiert(chat):
    chat.gedaechtnis.merke_kunde("Familie Keller", "Rosenweg 7", "8404", "Winterthur")
    chat.gedaechtnis.merke_stundenansatz(Decimal("90"))
    z = chat.sende("Rächnig für Keller: 1 Stund")[0]["inhalt"]
    assert z["kunde"]["name"] == "Familie Keller"  # unscharf erkannt
    assert z["kunde"]["gespeichert"] is True
    assert z["positionen"][0]["gespeichert"] is True
    assert chat.gedaechtnis.stundenansatz()[1]["benutzt"] == 1


def test_zwei_aehnliche_kunden_rueckfrage(chat):
    chat.gedaechtnis.merke_kunde("Familie Keller", "Rosenweg 7", "8404", "Winterthur")
    chat.gedaechtnis.merke_kunde("Herr Keller", "Seeweg 1", "6003", "Luzern")
    chat.gedaechtnis.merke_stundenansatz(Decimal("90"))
    a = chat.sende("Rächnig für Keller: 1 Stund")
    assert texte_von(a) == ["Meinst du Familie Keller (Winterthur) oder Herr Keller (Luzern)?"]
    a = chat.sende("2")
    assert a[-1]["typ"] == "zusammenfassung"
    assert a[-1]["inhalt"]["kunde"]["ort"] == "Luzern"


def test_begriff_aus_gedaechtnis_nie_unklar(chat):
    chat.gedaechtnis.merke_kunde("Familie Keller", "Rosenweg 7", "8404", "Winterthur")
    chat.gedaechtnis.merke_stundenansatz(Decimal("90"))
    chat.gedaechtnis.merke_begriff("FI", "FI-Schutzschalter")
    chat.gedaechtnis.merke_materialpreis("FI-Schutzschalter", Decimal("85"), "Stk.")
    # Das Modell meldet «FI» trotzdem als unklar – der Code fragt nicht.
    a = chat.sende("Rächnig für Familie Keller: 2 Stund, 1 FI")
    assert typen(a) == ["zusammenfassung"]
    assert a[0]["inhalt"]["total"] == "286.47"


def test_geloeschtes_wissen_wird_wieder_erfragt(chat):
    chat.gedaechtnis.merke_stundenansatz(Decimal("90"))
    e = chat.gedaechtnis.merke_kunde("Herr Meier", "Bahnhofstrasse 3", "6003", "Luzern")
    chat.gedaechtnis.loesche(e["id"])
    chat.sende(MEIER)
    a = chat.entwurf()
    assert a["rueckfrage"]["art"] == "adresse"


def test_schweizer_rechtschreibung():
    from pathlib import Path

    from app import chat_modell

    dateien = [Path("app/texte.py"), Path("app/templates/chat.html"), Path("app/templates/wissen.html"),
               Path("app/static/chat.js")]
    for d in dateien:
        assert "ß" not in d.read_text(encoding="utf-8"), d
    assert "ß" not in chat_modell.SYSTEMPROMPT
