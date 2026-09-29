"""Optionaler Test gegen das echte Ollama. Wird übersprungen, wenn Ollama nicht läuft.

Vergleicht nur Mengen, Preise und Total – nicht den Wortlaut der Beschreibungen.
"""

from decimal import Decimal

import httpx
import pytest

from app import config
from app.auslesen import OllamaAusleser
from app.rechnen import Position, berechne


def _ollama_bereit() -> str | None:
    try:
        antwort = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=2)
        modelle = {m["name"] for m in antwort.json().get("models", [])}
    except Exception:
        return f"Ollama läuft nicht unter {config.OLLAMA_URL}"
    if config.OLLAMA_MODEL not in modelle and f"{config.OLLAMA_MODEL}:latest" not in modelle:
        return f"Modell {config.OLLAMA_MODEL} ist nicht installiert"
    return None


grund = _ollama_bereit()
pytestmark = pytest.mark.skipif(grund is not None, reason=grund or "")


def test_echtes_ollama(fall):
    entwurf = OllamaAusleser().lese_aus(fall["text"])

    erhalten = sorted(
        (Decimal(p["menge"]), Decimal(p["einzelpreis"]))
        for p in entwurf["positionen"]
        if p["menge"] and p["einzelpreis"]
    )
    erwartet = sorted((Decimal(p["menge"]), Decimal(p["einzelpreis"])) for p in fall["positionen"])
    assert erhalten == erwartet, entwurf["positionen"]

    positionen = [
        Position(p["beschreibung"], Decimal(p["menge"]), p["einheit"], Decimal(p["einzelpreis"]))
        for p in entwurf["positionen"]
    ]
    assert berechne(positionen).total == Decimal(fall["total"])
