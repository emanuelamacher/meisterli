import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.rechnen import Position

FIXTURES = Path(__file__).parent / "fixtures"
TEST_IBAN = "CH93 0076 2011 6238 5295 7"


def lade_texte() -> list[dict]:
    return json.loads((FIXTURES / "texte.json").read_text(encoding="utf-8"))


def als_positionen(fall: dict) -> list[Position]:
    return [
        Position(
            beschreibung=p["beschreibung"],
            menge=Decimal(p["menge"]),
            einheit=p["einheit"],
            einzelpreis=Decimal(p["einzelpreis"]),
        )
        for p in fall["positionen"]
    ]


@pytest.fixture(params=lade_texte(), ids=lambda f: f["id"])
def fall(request) -> dict:
    return request.param


class GespeichertesChatModell:
    """Ersetzt Ollama im Chat: liefert gespeicherte Antworten passend zur Nachricht."""

    modell = "gespeichert"

    def __init__(self, ordner: str = "chat_antworten"):
        from app.chat_modell import normalisiere

        self._normalisiere = normalisiere
        self.antworten = {}
        for datei in sorted((FIXTURES / ordner).glob("*.json")):
            eintrag = json.loads(datei.read_text(encoding="utf-8"))
            self.antworten[eintrag["nachricht"]] = eintrag["antwort"]
        self.aufrufe: list[tuple[str, dict]] = []

    def deute(self, nachricht: str, kontext: dict) -> dict:
        self.aufrufe.append((nachricht, kontext))
        if nachricht not in self.antworten:
            raise AssertionError(f"Keine gespeicherte Antwort für: {nachricht!r}")
        return self._normalisiere(self.antworten[nachricht], nachricht)
