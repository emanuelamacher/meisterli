"""Der Demo-Ablauf aus dem Auftrag als automatischer Test (gespeicherte Modellantworten)."""

from pypdf import PdfReader

import pytest

from tests.chat_hilfen import Chat, texte_von, typen
from tests.conftest import GespeichertesChatModell


@pytest.mark.parametrize(
    "ordner",
    [
        "chat_antworten",  # saubere Antworten nach Schema
        "chat_antworten_qwen3",  # wörtlich, was qwen3:8b geliefert hat (./run.sh probe)
    ],
)
def test_demo_vier_gespraeche(tmp_path, ordner):
    chat = Chat(tmp_path, modell=GespeichertesChatModell(ordner))

    # Gespräch 1: Kunde neu, Adresse fehlt
    a = chat.sende("Rächnig für Familie Keller: 3 Stund à 90, 2 Schalter à 24, Sicherigskaschte 180")
    assert typen(a) == ["rueckfrage"]
    assert texte_von(a) == ["Welche Adresse hat Familie Keller?"]

    a = chat.sende("Rosenweg 7, 8404 Winterthur")
    assert typen(a) == ["text", "zusammenfassung"]
    assert texte_von(a)[0] == "Gemerkt: Familie Keller, Rosenweg 7, 8404 Winterthur."
    z = a[1]["inhalt"]
    assert (z["netto"], z["mwst"], z["total"]) == ("498.00", "40.34", "538.34")
    assert z["knoepfe"] == ["Ja, erstellen", "Ändern", "Abbrechen"]

    a = chat.sende("Ja")
    assert typen(a) == ["pdf"]
    pdf1 = a[0]["inhalt"]
    assert pdf1["dateiname"] == f"Rechnung_{pdf1['nummer']}.pdf"
    assert pdf1["seiten"] == 1

    # Gespräch 2: Stundenansatz und Adresse fehlen
    a = chat.sende("Rächnig für Herr Meier: Boiler entkalche 2 Stund, Aafahrt 45")
    assert texte_von(a) == ["Welchen Stundenansatz nimmst du?"]
    a = chat.sende("90")
    assert texte_von(a) == ["Gemerkt: Stundenansatz 90.–", "Welche Adresse hat Herr Meier?"]
    a = chat.sende("Bahnhofstrasse 3, 6003 Luzern")
    assert texte_von(a)[0] == "Gemerkt: Herr Meier, Bahnhofstrasse 3, 6003 Luzern."
    z = a[1]["inhalt"]
    assert [(p["beschreibung"], p["menge"], p["einheit"], p["preis"]) for p in z["positionen"]] == [
        ("Boiler entkalken", "2", "Std.", "90.–"),
        ("Anfahrt", "1", "pauschal", "45.–"),
    ]
    assert (z["netto"], z["mwst"], z["total"]) == ("225.00", "18.23", "243.23")
    assert typen(chat.sende("Ja")) == ["pdf"]

    # Gespräch 3: Adresse und Ansatz bekannt, ein Begriff unklar
    a = chat.sende("Rächnig für Familie Keller: 2 Stund, 1 FI")
    assert texte_von(a) == ["Was meinst du mit «FI»?"]
    a = chat.sende("FI-Schutzschalter, 85 Franke")
    assert texte_von(a)[0] == "Gemerkt: «FI» = FI-Schutzschalter, 85.– pro Stk."
    z = a[1]["inhalt"]
    assert z["kunde"]["strasse"] == "Rosenweg 7" and z["kunde"]["gespeichert"] is True
    assert [(p["beschreibung"], p["preis"], p["gespeichert"]) for p in z["positionen"]] == [
        ("Arbeit", "90.–", True),
        ("FI-Schutzschalter", "85.–", False),
    ]
    assert (z["netto"], z["mwst"], z["total"]) == ("265.00", "21.47", "286.47")
    assert typen(chat.sende("Ja")) == ["pdf"]

    # Gespräch 4: alles bekannt, auch nach einem Neustart
    chat.neustart()
    a = chat.sende("Rächnig für Herr Meier: 1 FI")
    assert typen(a) == ["zusammenfassung"]  # keine einzige Rückfrage
    z = a[0]["inhalt"]
    assert [(p["beschreibung"], p["menge"], p["einheit"], p["preis"], p["gespeichert"]) for p in z["positionen"]] == [
        ("FI-Schutzschalter", "1", "Stk.", "85.–", True)
    ]
    assert z["kunde"]["ort"] == "Luzern"
    assert (z["netto"], z["mwst"], z["total"]) == ("85.00", "6.89", "91.89")
    pdf4 = chat.sende("Ja")[0]["inhalt"]

    # Vier Rechnungen mit fortlaufenden Nummern, Rückfragen und Wissen gespeichert
    nummern = [r["nummer"] for r in reversed(chat.db.rechnungen())]
    assert nummern == ["2026-001", "2026-002", "2026-003", "2026-004"]
    assert pdf4["dateiname"] == "Rechnung_2026-004.pdf"
    rueckfragen = chat.db.rueckfragen()
    assert [(r["art"], r["antwort"]) for r in rueckfragen] == [
        ("adresse", "Rosenweg 7, 8404 Winterthur"),
        ("stundenansatz", "90"),
        ("adresse", "Bahnhofstrasse 3, 6003 Luzern"),
        ("begriff", "FI-Schutzschalter, 85 Franke"),
    ]
    arten = sorted((e["art"], e["schluessel"]) for e in chat.gedaechtnis.alle())
    assert arten == [
        ("begriff", "FI"),
        ("kunde", "Familie Keller"),
        ("kunde", "Herr Meier"),
        ("materialpreis", "FI-Schutzschalter"),
        ("stundenansatz", "stunde"),
    ]
    text = PdfReader(chat.db.rechnung(4)["pdf_pfad"]).pages[0].extract_text()
    assert "FI-Schutzschalter" in text and "91.89" in text and "Bahnhofstrasse 3" in text
