"""Chat und Wissen über HTTP, mit Attrappen für Whisper und Ollama."""

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.chat_hilfen import FIRMA
from tests.conftest import GespeichertesChatModell
from tests.test_app import FakeAusleser, FakeTranskribierer

KELLER = "Rächnig für Familie Keller: 3 Stund à 90, 2 Schalter à 24, Sicherigskaschte 180"
MEIER = "Rächnig für Herr Meier: Boiler entkalche 2 Stund, Aafahrt 45"


@pytest.fixture
def client(tmp_path):
    app = create_app(
        data_dir=tmp_path,
        transkribierer=FakeTranskribierer(text=KELLER),
        ausleser=FakeAusleser(),
        chat_modell=GespeichertesChatModell(),
    )
    app.state.db.speichere_einstellungen(FIRMA)
    with TestClient(app) as c:
        yield c


def sende(client, text):
    """Schickt eine Nachricht und gibt die Antworten von Meisterli zurück (Hintergrund läuft im TestClient mit)."""
    vorher = client.get("/api/chat/verlauf").json()["letzte_id"]
    r = client.post("/api/chat/senden", data={"text": text})
    assert r.status_code == 200, r.text
    neu = client.get("/api/chat/verlauf", params={"nach": vorher}).json()["nachrichten"]
    assert neu[0]["absender"] == "ich"
    return neu[1:]


def test_chat_seite(client):
    html = client.get("/chat").text
    assert "Meisterli" in html and ">Demo<" in html
    assert "whatsapp" not in html.lower()
    assert client.get("/static/chat.js").status_code == 200
    assert client.get("/static/chat.css").status_code == 200
    v = client.get("/api/chat/verlauf").json()
    assert v["schreibt"] is False
    assert v["nachrichten"][0]["absender"] == "meisterli"  # Begrüssung


def test_gespraech_ueber_http(client):
    a = sende(client, KELLER)
    assert [(n["typ"], n["inhalt"]["text"]) for n in a] == [("rueckfrage", "Welche Adresse hat Familie Keller?")]
    a = sende(client, "Rosenweg 7, 8404 Winterthur")
    assert [n["typ"] for n in a] == ["text", "zusammenfassung"]
    v = client.get("/api/chat/verlauf").json()
    assert v["aktive_knoepfe"] == a[1]["id"]
    assert a[1]["inhalt"]["total"] == "538.34"

    a = sende(client, "Ja, erstellen")
    pdf = a[0]["inhalt"]
    assert a[0]["typ"] == "pdf"
    assert pdf["nummer"] == f"{date.today().year}-001"
    assert pdf["dateiname"] == f"Rechnung_{pdf['nummer']}.pdf"
    assert client.get("/api/chat/verlauf").json()["aktive_knoepfe"] is None
    r = client.get(f"/api/chat/pdf/{pdf['rechnung_id']}")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert f"Rechnung_{pdf['nummer']}.pdf" in r.headers["content-disposition"]

    # Verlauf ist gespeichert und kommt nach einem Neuladen wieder
    alle = client.get("/api/chat/verlauf").json()["nachrichten"]
    assert [n["absender"] for n in alle].count("ich") == 3


def test_sprachnachricht(client):
    r = client.post(
        "/api/chat/senden",
        files={"audio": ("sprachnachricht.webm", b"webm-daten", "audio/webm")},
        data={"dauer": "4.2"},
    )
    assert r.status_code == 200
    alle = client.get("/api/chat/verlauf").json()["nachrichten"]
    audio = next(n for n in alle if n["typ"] == "audio")
    assert audio["inhalt"]["transkript"] == KELLER
    assert audio["inhalt"]["status"] == "fertig"
    assert audio["inhalt"]["dauer"] == 4.2
    assert alle[-1]["inhalt"]["text"] == "Welche Adresse hat Familie Keller?"
    assert client.get(f"/api/chat/audio/{audio['id']}").content == b"webm-daten"
    assert client.post("/api/chat/senden", files={"audio": ("x.pdf", b"x", "application/pdf")}).status_code == 400


def test_leeren_und_zuruecksetzen(client):
    sende(client, KELLER)
    sende(client, "Rosenweg 7, 8404 Winterthur")

    assert client.post("/api/chat/leeren").json() == {"ok": True}
    alle = client.get("/api/chat/verlauf").json()["nachrichten"]
    assert len(alle) == 1 and alle[0]["absender"] == "meisterli"
    # Gedächtnis bleibt: keine Frage nach der Adresse mehr
    assert sende(client, KELLER)[-1]["typ"] == "zusammenfassung"

    client.post("/api/chat/zuruecksetzen")
    assert "Noch nichts gelernt" in client.get("/wissen").text
    assert sende(client, KELLER)[-1]["inhalt"]["text"] == "Welche Adresse hat Familie Keller?"


def test_wissen_anzeigen_aendern_loeschen(client):
    sende(client, MEIER)
    sende(client, "90")
    sende(client, "Bahnhofstrasse 3, 6003 Luzern")

    seite = client.get("/wissen").text
    assert "Stundenansatz" in seite and "Bahnhofstrasse 3" in seite
    assert "«Welchen Stundenansatz nimmst du?» → «90»" in seite

    gedaechtnis = client.app.state.gedaechtnis
    ansatz = gedaechtnis.alle("stundenansatz")[0]
    r = client.post(f"/wissen/{ansatz['id']}", data={"betrag": "95"}, follow_redirects=False)
    assert r.status_code == 303
    assert gedaechtnis.stundenansatz()[0] == 95
    r = client.post(f"/wissen/{ansatz['id']}", data={"betrag": "abc"})
    assert "gültigen Betrag" in r.text

    # Löschen wirkt sofort: beim nächsten Mal fragt Meisterli wieder nach der Adresse
    meier = gedaechtnis.suche_kunde("Herr Meier").treffer
    client.post(f"/wissen/{meier['id']}/loeschen")
    assert "Bahnhofstrasse" not in client.get("/wissen").text
    client.post("/api/chat/senden", data={"text": "Abbrechen"})
    a = sende(client, MEIER)
    assert a[-1]["inhalt"]["text"] == "Welche Adresse hat Herr Meier?"


def test_vorgabe_zahlungsfrist(client):
    r = client.post("/wissen-vorgabe/zahlungsfrist", data={"wert": "10"}, follow_redirects=False)
    assert r.status_code == 303
    assert client.app.state.gedaechtnis.vorgabe("zahlungsfrist_tage")[0] == 10
    sende(client, KELLER)
    sende(client, "Rosenweg 7, 8404 Winterthur")
    sende(client, "Ja")
    rechnung = client.app.state.db.rechnungen()[0]
    assert rechnung["zahlungsfrist_tage"] == 10
    assert re.search(r"Zahlungsfrist", client.get("/wissen").text)
