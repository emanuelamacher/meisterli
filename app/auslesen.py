"""Auslesen der Rechnungsangaben mit einem lokalen Sprachmodell über Ollama."""

import json
import re
from datetime import date
from typing import Protocol

import httpx

from . import config
from .prompt import SYSTEMPROMPT, nutzernachricht
from .rechnen import zahl

_TEXT_ODER_NULL = {"type": ["string", "null"]}
_ZAHL_ODER_NULL = {"type": ["number", "null"]}

SCHEMA = {
    "type": "object",
    "properties": {
        "kunde": {
            "type": "object",
            "properties": {
                "name": _TEXT_ODER_NULL,
                "strasse": _TEXT_ODER_NULL,
                "plz": _TEXT_ODER_NULL,
                "ort": _TEXT_ODER_NULL,
            },
            "required": ["name", "strasse", "plz", "ort"],
        },
        "leistungsdatum": _TEXT_ODER_NULL,
        "positionen": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "beschreibung": {"type": "string"},
                    "menge": _ZAHL_ODER_NULL,
                    "einheit": _TEXT_ODER_NULL,
                    "einzelpreis": _ZAHL_ODER_NULL,
                },
                "required": ["beschreibung", "menge", "einheit", "einzelpreis"],
            },
        },
        "zahlungsfrist_tage": {"type": ["integer", "null"]},
        "unsichere_felder": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kunde", "leistungsdatum", "positionen", "zahlungsfrist_tage", "unsichere_felder"],
}

KUNDENFELDER = ("name", "strasse", "plz", "ort")


class AuslesenFehler(Exception):
    """Verständliche Fehlermeldung für die Oberfläche."""


class Ausleser(Protocol):
    def lese_aus(self, text: str, heute: date | None = None) -> dict: ...


def _text(wert) -> str:
    if wert is None:
        return ""
    return str(wert).strip()


def _zahl_text(wert) -> str | None:
    try:
        d = zahl(wert)
    except ValueError:
        return None
    return None if d is None else format(d.normalize(), "f")


def normalisiere(roh: dict) -> dict:
    """Macht aus der Modellantwort einen sauberen Entwurf.

    Zahlen werden als Text (für Decimal) gespeichert. Fehlende Angaben landen
    zusätzlich in "unsichere_felder", auch wenn das Modell sie vergessen hat.
    """
    if not isinstance(roh, dict):
        raise AuslesenFehler("Die Antwort des Sprachmodells ist kein JSON-Objekt.")
    unsicher = {f for f in roh.get("unsichere_felder") or [] if isinstance(f, str)}

    kunde_roh = roh.get("kunde") if isinstance(roh.get("kunde"), dict) else {}
    kunde = {f: _text(kunde_roh.get(f)) for f in KUNDENFELDER}
    for f in KUNDENFELDER:
        if not kunde[f]:
            unsicher.add(f"kunde.{f}")

    leistungsdatum = None
    if roh.get("leistungsdatum"):
        try:
            leistungsdatum = date.fromisoformat(str(roh["leistungsdatum"]).strip()).isoformat()
        except ValueError:
            unsicher.add("leistungsdatum")

    positionen = []
    for p in roh.get("positionen") or []:
        if not isinstance(p, dict):
            continue
        i = len(positionen)
        pos = {
            "beschreibung": _text(p.get("beschreibung")),
            "menge": _zahl_text(p.get("menge")),
            "einheit": _text(p.get("einheit")),
            "einzelpreis": _zahl_text(p.get("einzelpreis")),
        }
        for f in ("beschreibung", "menge", "einzelpreis"):
            if not pos[f]:
                unsicher.add(f"positionen.{i}.{f}")
        positionen.append(pos)
    if not positionen:
        unsicher.add("positionen")

    frist = roh.get("zahlungsfrist_tage")
    if isinstance(frist, bool) or not isinstance(frist, (int, float)) or frist <= 0:
        frist = None
    else:
        frist = int(frist)

    return {
        "kunde": kunde,
        "leistungsdatum": leistungsdatum,
        "positionen": positionen,
        "zahlungsfrist_tage": frist,
        "unsichere_felder": sorted(unsicher),
    }


def _json_aus_antwort(inhalt: str) -> dict:
    inhalt = re.sub(r"<think>.*?</think>", "", inhalt, flags=re.S).strip()
    inhalt = re.sub(r"^```(?:json)?\s*|\s*```$", "", inhalt).strip()
    try:
        return json.loads(inhalt)
    except json.JSONDecodeError as e:
        raise AuslesenFehler(f"Das Sprachmodell hat kein gültiges JSON geliefert: {e}") from e


class OllamaClient:
    """Gemeinsamer HTTP-Teil: /api/chat mit Structured Outputs, Temperatur 0, ohne Thinking."""

    def __init__(
        self,
        url: str = config.OLLAMA_URL,
        modell: str = config.OLLAMA_MODEL,
        timeout: float = config.OLLAMA_TIMEOUT,
        client: httpx.Client | None = None,
    ):
        self.url = url.rstrip("/")
        self.modell = modell
        self.client = client or httpx.Client(timeout=timeout)

    def payload(self, system: str, nutzer: str, schema: dict, think: bool | None = False) -> dict:
        payload = {
            "model": self.modell,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": nutzer},
            ],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0},
        }
        if think is not None:
            payload["think"] = think
        return payload

    def _post(self, payload: dict) -> httpx.Response:
        try:
            return self.client.post(f"{self.url}/api/chat", json=payload)
        except httpx.ConnectError as e:
            raise AuslesenFehler(
                f"Ollama ist unter {self.url} nicht erreichbar. Läuft Ollama?"
            ) from e
        except httpx.TimeoutException as e:
            raise AuslesenFehler("Ollama hat nicht rechtzeitig geantwortet.") from e

    def json_chat(self, system: str, nutzer: str, schema: dict) -> dict:
        antwort = self._post(self.payload(system, nutzer, schema))
        if antwort.status_code == 400 and "think" in antwort.text.lower():
            # Modelle ohne Thinking-Unterstützung kennen den Parameter nicht.
            antwort = self._post(self.payload(system, nutzer, schema, think=None))
        if antwort.status_code == 404:
            raise AuslesenFehler(
                f"Das Modell «{self.modell}» fehlt. Bitte `ollama pull {self.modell}` ausführen."
            )
        if antwort.status_code >= 400:
            raise AuslesenFehler(f"Ollama-Fehler {antwort.status_code}: {antwort.text[:300]}")
        inhalt = antwort.json().get("message", {}).get("content", "")
        return _json_aus_antwort(inhalt)


class OllamaAusleser(OllamaClient):
    def anfrage(self, text: str, heute: date, think: bool | None = False) -> dict:
        return self.payload(SYSTEMPROMPT, nutzernachricht(text, heute.isoformat()), SCHEMA, think)

    def roh(self, text: str, heute: date | None = None) -> dict:
        heute = heute or date.today()
        return self.json_chat(SYSTEMPROMPT, nutzernachricht(text, heute.isoformat()), SCHEMA)

    def lese_aus(self, text: str, heute: date | None = None) -> dict:
        if not text or not text.strip():
            raise AuslesenFehler("Der Text ist leer.")
        return normalisiere(self.roh(text, heute))
