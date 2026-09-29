"""Ganzer Ablauf über die HTTP-Schnittstelle, mit Attrappen für Whisper und Ollama."""

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auslesen import AuslesenFehler, normalisiere
from app.main import create_app
from app.transkription import TranskriptionsFehler
from tests.conftest import FIXTURES, TEST_IBAN, lade_texte

FAELLE = {f["text"]: f for f in lade_texte()}
JAHR = date.today().year


class FakeTranskribierer:
    name = "Attrappe"

    def __init__(self, text=lade_texte()[0]["text"], fehler=None):
        self.text = text
        self.fehler = fehler
        self.dateien: list[Path] = []

    def transkribiere(self, audio: Path) -> str:
        self.dateien.append(audio)
        if self.fehler:
            raise TranskriptionsFehler(self.fehler)
        return self.text


class FakeAusleser:
    """Liefert die gespeicherte Ollama-Antwort passend zum Text."""

    modell = "attrappe"

    def lese_aus(self, text, heute=None):
        fall = FAELLE.get(text)
        if not fall:
            raise AuslesenFehler("Unbekannter Text")
        antwort = json.loads((FIXTURES / "ollama_antworten" / f"{fall['id']}.json").read_text("utf-8"))
        return normalisiere(json.loads(antwort["message"]["content"]))


EINSTELLUNGEN = {
    "firma_name": "Elektro Muster GmbH",
    "firma_strasse": "Werkstrasse 12",
    "firma_plz": "3011",
    "firma_ort": "Bern",
    "iban": TEST_IBAN,
    "uid": "CHE-123.456.789 MWST",
    "mwst_pflichtig": "on",
    "zahlungsfrist_tage": "30",
}


@pytest.fixture
def transkribierer():
    return FakeTranskribierer()


@pytest.fixture
def client(tmp_path, transkribierer):
    app = create_app(data_dir=tmp_path, transkribierer=transkribierer, ausleser=FakeAusleser())
    with TestClient(app) as c:
        yield c


def einrichten(client):
    r = client.post("/einstellungen", data=EINSTELLUNGEN, follow_redirects=False)
    assert r.status_code == 303


def entwurf_aus_text(client, text) -> int:
    r = client.post("/api/verarbeiten", data={"text": text})
    assert r.status_code == 200, r.text
    return r.json()["entwurf_id"]


def eingabe(fall, adresse=True, **extra) -> dict:
    kunde = {"name": fall["kunde"], "strasse": "", "plz": "", "ort": ""}
    if adresse:
        kunde.update(strasse="Rosenweg 5", plz="3006", ort="Bern")
    return {"kunde": kunde, "leistungsdatum": "", "zahlungsfrist_tage": "",
            "positionen": fall["positionen"], **extra}


def test_seiten_laden(client):
    for pfad in ["/", "/rechnungen", "/einstellungen", "/static/app.js", "/static/style.css"]:
        assert client.get(pfad).status_code == 200, pfad
    assert "Firmendaten sind noch unvollständig" in client.get("/").text


def test_einstellungen_pruefen(client):
    r = client.post("/einstellungen", data={**EINSTELLUNGEN, "iban": "CH00 1234"})
    assert r.status_code == 422
    assert "Keine gültige Schweizer IBAN" in r.text
    r = client.post("/einstellungen", data={**EINSTELLUNGEN, "uid": ""})
    assert "braucht eine UID" in r.text
    einrichten(client)
    seite = client.get("/einstellungen?gespeichert=1").text
    assert "Gespeichert" in seite and "CH93 0076 2011 6238 5295 7" in seite


def test_text_bis_pdf(client):
    einrichten(client)
    fall = lade_texte()[0]
    r = client.post("/api/verarbeiten", data={"text": fall["text"]})
    daten = r.json()
    assert daten["dauer_transkription"] is None
    assert daten["dauer_auslesen"] >= 0

    seite = client.get(daten["url"]).text
    assert "Familie Keller" in seite
    assert "übersprungen (Text)" in seite
    assert 'name="kunde.strasse" value="" class=" unsicher"' in seite
    assert "538.34" in seite
    assert "Nicht genannt – heute eingesetzt" in seite

    # Ohne Kundenadresse keine Rechnung
    r = client.post("/api/rechnungen", json=eingabe(fall, adresse=False, entwurf_id=daten["entwurf_id"]))
    assert r.status_code == 422
    assert set(r.json()["fehler"]) == {"kunde.strasse", "kunde.plz", "kunde.ort"}
    assert client.get("/rechnungen").text.count("Rechnung erstellt") == 0

    r = client.post("/api/rechnungen", json=eingabe(fall, entwurf_id=daten["entwurf_id"]))
    assert r.status_code == 200, r.text
    rechnung = r.json()
    assert rechnung["nummer"] == f"{JAHR}-001"

    pdf = client.get(rechnung["pdf_url"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    download = client.get(rechnung["pdf_url"] + "?download=1")
    assert "attachment" in download.headers["content-disposition"]
    assert f"Rechnung-{JAHR}-001.pdf" in download.headers["content-disposition"]

    liste = client.get("/rechnungen").text
    assert f"{JAHR}-001" in liste and "538.34" in liste and "Familie Keller" in liste


def test_nummern_und_kunde_wiedererkennen(client):
    einrichten(client)
    fall = lade_texte()[0]
    client.post("/api/rechnungen", json=eingabe(fall))

    # Zweiter Auftrag für denselben Kunden: Adresse wird übernommen
    entwurf_id = entwurf_aus_text(client, fall["text"])
    seite = client.get(f"/vorschau/{entwurf_id}").text
    assert "bekannt – Adresse übernommen" in seite
    assert 'name="kunde.strasse" value="Rosenweg 5" class=""' in seite
    assert client.get("/api/kunden", params={"name": "familie keller"}).json()["plz"] == "3006"
    assert client.get("/api/kunden", params={"name": "Niemand"}).json() == {"gefunden": False}

    r = client.post("/api/rechnungen", json=eingabe(fall))
    assert r.json()["nummer"] == f"{JAHR}-002"


def test_leistungsdatum_und_frist(client):
    einrichten(client)
    fall = lade_texte()[1]
    r = client.post("/api/rechnungen", json=eingabe(fall, leistungsdatum="2026-09-01", zahlungsfrist_tage="10"))
    assert r.status_code == 200
    seite = client.get("/rechnungen").text
    assert "946.96" in seite


def test_berechnen(client):
    einrichten(client)
    fall = lade_texte()[3]
    s = client.post("/api/berechnen", json={"positionen": fall["positionen"]}).json()
    assert (s["netto"], s["mwst"], s["total"]) == ("435.00", "35.24", "470.24")
    assert s["zeilen"] == ["375.00", "60.00"]

    s = client.post("/api/berechnen", json={"positionen": [
        {"beschreibung": "Arbeit", "menge": "1’000", "einheit": "Std.", "einzelpreis": "90"},
        {"beschreibung": "Kaputt", "menge": "x", "einheit": "", "einzelpreis": "5"},
        {"beschreibung": "", "menge": "", "einheit": "", "einzelpreis": ""},
    ]}).json()
    assert s["zeilen"] == ["90’000.00", "", ""]
    assert s["total"] == "97’290.00"
    assert list(s["fehler"]) == ["positionen.1.menge"]


def test_ohne_mwst(client):
    client.post("/einstellungen", data={k: v for k, v in EINSTELLUNGEN.items() if k != "mwst_pflichtig"})
    fall = lade_texte()[2]
    s = client.post("/api/berechnen", json={"positionen": fall["positionen"]}).json()
    assert s["total"] == "273.00" and s["mwst_pflichtig"] is False
    r = client.post("/api/rechnungen", json=eingabe(fall))
    assert r.status_code == 200
    assert "273.00" in client.get("/rechnungen").text


def test_ohne_einstellungen_keine_rechnung(client):
    r = client.post("/api/rechnungen", json=eingabe(lade_texte()[0]))
    assert r.status_code == 422
    assert "einstellungen" in r.json()["fehler"]


def test_ungueltige_positionen(client):
    einrichten(client)
    fall = lade_texte()[0]
    r = client.post("/api/rechnungen", json=eingabe(fall, positionen=[
        {"beschreibung": "", "menge": "2", "einheit": "", "einzelpreis": "abc"},
    ]))
    assert r.status_code == 422
    assert set(r.json()["fehler"]) == {"positionen.0.beschreibung", "positionen.0.einzelpreis"}
    r = client.post("/api/rechnungen", json=eingabe(fall, positionen=[]))
    assert "positionen" in r.json()["fehler"]


def test_audio_upload(client, transkribierer, tmp_path):
    r = client.post("/api/verarbeiten", files={"audio": ("nachricht.ogg", b"OggS...", "audio/ogg")})
    assert r.status_code == 200, r.text
    daten = r.json()
    assert daten["transkript"] == lade_texte()[0]["text"]
    assert daten["dauer_transkription"] is not None
    (gespeichert,) = transkribierer.dateien
    assert gespeichert.suffix == ".ogg" and gespeichert.parent == tmp_path / "audio"
    assert gespeichert.read_bytes() == b"OggS..."

    seite = client.get(daten["url"]).text
    assert "Transkription: <strong>" in seite and "übersprungen" not in seite
    assert client.get(f"/entwuerfe/{daten['entwurf_id']}/audio").content == b"OggS..."


def test_audio_falsches_format(client):
    r = client.post("/api/verarbeiten", files={"audio": ("brief.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 400
    assert "nicht unterstützt" in r.json()["fehler"]


def test_fehler_werden_angezeigt(tmp_path):
    app = create_app(
        data_dir=tmp_path,
        transkribierer=FakeTranskribierer(fehler="ffmpeg fehlt."),
        ausleser=FakeAusleser(),
    )
    with TestClient(app) as c:
        r = c.post("/api/verarbeiten", files={"audio": ("a.m4a", b"x", "audio/mp4")})
        assert r.status_code == 502 and r.json()["fehler"] == "ffmpeg fehlt."
        r = c.post("/api/verarbeiten", data={"text": "etwas Unbekanntes"})
        assert r.status_code == 502
        assert r.json()["transkript"] == "etwas Unbekanntes"
        assert c.post("/api/verarbeiten", data={"text": " "}).status_code == 400
        assert c.get("/vorschau/999").status_code == 404
        assert c.get("/rechnungen/999/pdf").status_code == 404
