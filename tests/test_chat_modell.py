import json

import httpx
import pytest

from app.auslesen import AuslesenFehler
from app.chat_modell import SCHEMA, OllamaChatModell, normalisiere
from tests.conftest import FIXTURES


def modell_mit(inhalt: dict, anfragen: list) -> OllamaChatModell:
    def handler(request):
        anfragen.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(inhalt)}})

    return OllamaChatModell(url="http://ollama.test", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_anfrage_und_kontext():
    gespeichert = json.loads((FIXTURES / "chat_antworten" / "g4_meier_fi.json").read_text("utf-8"))
    anfragen = []
    kontext = {
        "heute": "2026-09-29",
        "entwurf": None,
        "rueckfrage": None,
        "wissen": ["Begriff: «FI» bedeutet «FI-Schutzschalter»"],
    }
    d = modell_mit(gespeichert["antwort"], anfragen).deute(gespeichert["nachricht"], kontext)
    assert d["absicht"] == "neue_rechnung"
    assert d["aenderungen"]["positionen"] == [
        {"beschreibung": "FI", "menge": "1", "einheit": "Stk.", "einzelpreis": None}
    ]
    (a,) = anfragen
    assert a["format"] == SCHEMA and a["options"]["temperature"] == 0 and a["think"] is False
    nutzer = a["messages"][1]["content"]
    assert "Heute ist 2026-09-29." in nutzer
    assert "Begriff: «FI» bedeutet «FI-Schutzschalter»" in nutzer
    assert gespeichert["nachricht"] in nutzer
    assert "ß" not in a["messages"][0]["content"]


def test_normalisiere_ist_tolerant():
    d = normalisiere({"absicht": "quatsch", "aenderungen": {"positionen": [{"beschreibung": " "}, "x"]},
                      "unklare_begriffe": ["", 3, "FI"]})
    assert d["absicht"] == "anderes"
    assert d["aenderungen"]["positionen"] == []
    assert d["unklare_begriffe"] == ["FI"]
    assert d["antwort_auf_rueckfrage"]["betrag"] is None


def test_leere_nachricht():
    with pytest.raises(AuslesenFehler):
        modell_mit({}, []).deute("  ", {})
