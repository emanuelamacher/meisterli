"""Gemeinsame Hilfen für die Chat-Tests."""

from datetime import date

from app.db import Datenbank
from app.gedaechtnis import Gedaechtnis
from app.gespraech import Gespraech
from tests.conftest import TEST_IBAN, GespeichertesChatModell

HEUTE = date(2026, 9, 29)

FIRMA = {
    "firma_name": "Elektro Muster GmbH",
    "firma_strasse": "Werkstrasse 12",
    "firma_plz": "3011",
    "firma_ort": "Bern",
    "iban": TEST_IBAN,
    "uid": "CHE-123.456.789 MWST",
    "mwst_pflichtig": True,
    "zahlungsfrist_tage": 30,
}


class Chat:
    """Ein Chat wie in der App, aber ohne HTTP. `neustart()` baut alles mit neuer Verbindung neu auf."""

    def __init__(self, tmp_path, modell=None):
        self.tmp_path = tmp_path
        self.modell = modell or GespeichertesChatModell()
        self.neustart()
        self.db.speichere_einstellungen(FIRMA)

    def neustart(self):
        self.db = Datenbank(self.tmp_path / "meisterli.db")
        self.gedaechtnis = Gedaechtnis(self.db)
        self.gespraech = Gespraech(self.db, self.gedaechtnis, self.modell, self.tmp_path / "pdf", heute=HEUTE)
        self.gid = self.db.aktuelles_gespraech()

    def sende(self, text: str) -> list[dict]:
        return self.gespraech.verarbeite(self.gid, text)

    def entwurf(self):
        return self.db.offener_entwurf(self.gid)


def typen(antworten):
    return [a["typ"] for a in antworten]


def texte_von(antworten):
    return [a["inhalt"].get("text") for a in antworten]
