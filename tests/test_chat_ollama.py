"""Optionaler Durchlauf der vier Demo-Gespräche mit dem echten Ollama.

Wird übersprungen, wenn Ollama nicht läuft. Vergleicht nur Mengen, Preise und Totale.
"""

import pytest

from app.chat_modell import OllamaChatModell
from tests.chat_hilfen import Chat
from tests.test_auslesen_ollama import grund

pytestmark = pytest.mark.skipif(grund is not None, reason=grund or "")


def zusammenfassung(antworten):
    z = [a for a in antworten if a["typ"] == "zusammenfassung"]
    assert z, f"Keine Zusammenfassung: {antworten}"
    return z[-1]["inhalt"]


def mengen_preise(z):
    return sorted((p["menge"], p["preis"]) for p in z["positionen"])


def test_demo_mit_echtem_ollama(tmp_path):
    chat = Chat(tmp_path, modell=OllamaChatModell())

    chat.sende("Rächnig für Familie Keller: 3 Stund à 90, 2 Schalter à 24, Sicherigskaschte 180")
    z = zusammenfassung(chat.sende("Rosenweg 7, 8404 Winterthur"))
    assert mengen_preise(z) == [("1", "180.–"), ("2", "24.–"), ("3", "90.–")]
    assert z["total"] == "538.34"
    chat.sende("Ja")

    chat.sende("Rächnig für Herr Meier: Boiler entkalche 2 Stund, Aafahrt 45")
    chat.sende("90")
    z = zusammenfassung(chat.sende("Bahnhofstrasse 3, 6003 Luzern"))
    assert mengen_preise(z) == [("1", "45.–"), ("2", "90.–")]
    assert z["total"] == "243.23"
    chat.sende("Ja")

    a = chat.sende("Rächnig für Familie Keller: 2 Stund, 1 FI")
    assert [x["inhalt"]["text"] for x in a] == ["Was meinst du mit «FI»?"]
    z = zusammenfassung(chat.sende("FI-Schutzschalter, 85 Franke"))
    assert z["total"] == "286.47"
    chat.sende("Ja")

    chat.neustart()
    a = chat.sende("Rächnig für Herr Meier: 1 FI")
    assert [x["typ"] for x in a] == ["zusammenfassung"]
    assert mengen_preise(a[0]["inhalt"]) == [("1", "85.–")]
    assert a[0]["inhalt"]["total"] == "91.89"
