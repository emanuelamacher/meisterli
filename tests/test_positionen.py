"""Bereinigung von Modellantworten, wie sie qwen3:8b tatsächlich geliefert hat."""

from app.auslesen import normalisiere as normalisiere_phase1
from app.chat_modell import normalisiere as normalisiere_chat
from app.positionen import fasse_taetigkeiten_zusammen, nur_positiv
from tests.chat_hilfen import Chat, texte_von

BRUNNER = "Rächnig für Frau Brunner: Stube striiche, 42 m² à 18, Abdecke pauschal 120"


def pos(b, m, e, p):
    return {"beschreibung": b, "menge": m, "einheit": e, "einzelpreis": p}


def test_null_heisst_fehlt():
    assert nur_positiv("0") is None and nur_positiv("0.00") is None
    assert nur_positiv("18") == "18" and nur_positiv(None) is None


def test_taetigkeit_mit_menge_verbinden_phase1():
    roh = {
        "kunde": {"name": "Frau Brunner"},
        "positionen": [
            pos("Stube streichen", 1, "pauschal", 0),
            pos("Stube streichen", 42, "m²", 18),
            pos("Abdecken", 1, "pauschal", 120),
        ],
        "unsichere_felder": [],
    }
    e = normalisiere_phase1(roh, BRUNNER)
    assert [(p["beschreibung"], p["menge"], p["einzelpreis"]) for p in e["positionen"]] == [
        ("Stube streichen", "42", "18"),
        ("Abdecken", "1", "120"),
    ]
    assert not any(f.startswith("positionen") for f in e["unsichere_felder"])


def test_taetigkeit_ohne_menge_und_generische_folgeposition():
    ergebnis = fasse_taetigkeiten_zusammen(
        [pos("Boiler entkalken", None, None, None), pos("Arbeit", "2", "Std.", "95")],
        "Boiler entkalche, 2 Stund à 95",
    )
    assert ergebnis == [pos("Boiler entkalken", "2", "Std.", "95")]


def test_genanntes_stueck_bleibt_eigene_position():
    positionen = [pos("FI", "1", "Stk.", None), pos("Arbeit", "2", "Std.", None)]
    assert fasse_taetigkeiten_zusammen(positionen, "1 FI, 2 Stund") == positionen


def test_chat_preis_null_wird_erfragt(tmp_path):
    """So kam «Boiler entkalche 2 Stund» vom echten Modell: Preis 0 statt null."""
    text = "Rächnig für Herr Meier: Boiler entkalche 2 Stund, Aafahrt 45"
    roh = {
        "absicht": "neue_rechnung",
        "aenderungen": {
            "kunde": {"name": "Herr Meier"},
            "positionen": [pos("Boiler entkalken", 2, "Std.", 0), pos("Anfahrt", 1, "pauschal", 45)],
        },
        "unklare_begriffe": [],
    }

    class EchtesVerhalten:
        modell = "nachgebildet"

        def deute(self, nachricht, kontext):
            return normalisiere_chat(roh, nachricht)

    chat = Chat(tmp_path, modell=EchtesVerhalten())
    assert texte_von(chat.sende(text)) == ["Welchen Stundenansatz nimmst du?"]
    chat.sende("90")
    z = chat.sende("Bahnhofstrasse 3, 6003 Luzern")[-1]["inhalt"]
    assert z["total"] == "243.23"


def test_stundenansatz_null_gilt_nicht(tmp_path):
    chat = Chat(tmp_path)
    chat.sende("Rächnig für Herr Meier: Boiler entkalche 2 Stund, Aafahrt 45")
    a = chat.sende("0")
    assert "Welchen Stundenansatz nimmst du?" in texte_von(a)
