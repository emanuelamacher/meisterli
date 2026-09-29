"""Auslesen mit gespeicherten Ollama-Antworten – ohne laufendes Ollama."""

import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.auslesen import SCHEMA, AuslesenFehler, OllamaAusleser, normalisiere
from app.rechnen import Position, berechne
from tests.conftest import FIXTURES


def gespeicherte_antwort(fall_id: str) -> dict:
    return json.loads((FIXTURES / "ollama_antworten" / f"{fall_id}.json").read_text("utf-8"))


def ausleser_mit(antworten: list, anfragen: list) -> OllamaAusleser:
    """Ollama-Attrappe: gibt der Reihe nach die Antworten zurück und merkt sich die Anfragen."""

    def handler(request: httpx.Request) -> httpx.Response:
        anfragen.append(json.loads(request.content))
        status, body = antworten.pop(0)
        return httpx.Response(status, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaAusleser(url="http://ollama.test", modell="qwen3:8b", client=client)


def als_positionen(entwurf: dict) -> list[Position]:
    return [
        Position(p["beschreibung"], Decimal(p["menge"]), p["einheit"], Decimal(p["einzelpreis"]))
        for p in entwurf["positionen"]
    ]


def test_auslesen_mit_gespeicherter_antwort(fall):
    anfragen = []
    ausleser = ausleser_mit([(200, gespeicherte_antwort(fall["id"]))], anfragen)
    entwurf = ausleser.lese_aus(fall["text"], heute=date(2026, 9, 29))

    assert entwurf["kunde"]["name"] == fall["kunde"]
    assert [(p["menge"], p["einzelpreis"]) for p in entwurf["positionen"]] == [
        (p["menge"], p["einzelpreis"]) for p in fall["positionen"]
    ]
    assert berechne(als_positionen(entwurf)).total == Decimal(fall["total"])
    assert {"kunde.strasse", "kunde.plz", "kunde.ort"} <= set(entwurf["unsichere_felder"])
    assert entwurf["leistungsdatum"] is None

    # Anfrage: Structured Outputs, Temperatur 0, kein Thinking
    (anfrage,) = anfragen
    assert anfrage["model"] == "qwen3:8b"
    assert anfrage["format"] == SCHEMA
    assert anfrage["options"]["temperature"] == 0
    assert anfrage["think"] is False
    assert anfrage["stream"] is False
    assert fall["text"] in anfrage["messages"][1]["content"]
    assert "2026-09-29" in anfrage["messages"][1]["content"]


def test_beispiel_aus_auftrag_ist_im_prompt():
    from app.prompt import SYSTEMPROMPT

    for teil in ["3 Stund à 90", "Aafahrt 45", "Abdecke pauschal 120", "Sicherigskaschte"]:
        assert teil in SYSTEMPROMPT
    assert "ß" not in SYSTEMPROMPT


def test_fehlende_angaben_werden_unsicher():
    entwurf = normalisiere({
        "kunde": {"name": "Herr Meier", "strasse": "Dorfstrasse 3", "plz": None, "ort": ""},
        "leistungsdatum": "irgendwann",
        "positionen": [{"beschreibung": "Material", "menge": None, "einheit": None, "einzelpreis": 38}],
        "zahlungsfrist_tage": 10,
        "unsichere_felder": [],
    })
    assert entwurf["unsichere_felder"] == [
        "kunde.ort", "kunde.plz", "leistungsdatum", "positionen.0.menge",
    ]
    assert entwurf["kunde"]["strasse"] == "Dorfstrasse 3"
    assert entwurf["positionen"][0]["einzelpreis"] == "38"
    assert entwurf["zahlungsfrist_tage"] == 10


def test_zahlen_und_datum_werden_bereinigt():
    entwurf = normalisiere({
        "kunde": {"name": "A", "strasse": "B 1", "plz": 3000, "ort": "Bern"},
        "leistungsdatum": "2026-09-25",
        "positionen": [{"beschreibung": "Arbeit", "menge": 2.5, "einheit": "Std.", "einzelpreis": 90.0}],
        "zahlungsfrist_tage": -3,
        "unsichere_felder": ["", 5, "kunde.name"],
    })
    assert entwurf["kunde"]["plz"] == "3000"
    assert entwurf["leistungsdatum"] == "2026-09-25"
    assert entwurf["positionen"][0]["menge"] == "2.5"
    assert entwurf["positionen"][0]["einzelpreis"] == "90"
    assert entwurf["zahlungsfrist_tage"] is None
    assert entwurf["unsichere_felder"] == ["", "kunde.name"]


def test_keine_positionen():
    entwurf = normalisiere({"kunde": {}, "positionen": []})
    assert "positionen" in entwurf["unsichere_felder"]
    assert "kunde.name" in entwurf["unsichere_felder"]


def test_ungueltiges_json():
    antwort = {"message": {"content": "Hier ist die Rechnung: ..."}}
    ausleser = ausleser_mit([(200, antwort)], [])
    with pytest.raises(AuslesenFehler, match="kein gültiges JSON"):
        ausleser.lese_aus("Rächnig für Herr Meier")


def test_modell_fehlt():
    ausleser = ausleser_mit([(404, {"error": "model 'qwen3:8b' not found"})], [])
    with pytest.raises(AuslesenFehler, match="ollama pull qwen3:8b"):
        ausleser.lese_aus("Rächnig für Herr Meier")


def test_modell_ohne_thinking():
    anfragen = []
    ausleser = ausleser_mit(
        [
            (400, {"error": "\"llama3.1:8b\" does not support thinking"}),
            (200, gespeicherte_antwort("meier")),
        ],
        anfragen,
    )
    entwurf = ausleser.lese_aus("Rächnig für Herr Meier: ...")
    assert entwurf["kunde"]["name"] == "Herr Meier"
    assert "think" in anfragen[0] and "think" not in anfragen[1]


def test_ollama_nicht_erreichbar():
    def handler(request):
        raise httpx.ConnectError("verbindung abgelehnt")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(AuslesenFehler, match="nicht erreichbar"):
        OllamaAusleser(url="http://ollama.test", client=client).lese_aus("Test")


def test_leerer_text():
    with pytest.raises(AuslesenFehler, match="leer"):
        ausleser_mit([], []).lese_aus("   ")
