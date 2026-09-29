"""Diagnose: schickt die Testtexte an das echte Ollama und zeigt die rohen Antworten.

Aufruf: ./run.sh probe
"""

import json
import time
from datetime import date
from pathlib import Path

from . import config
from .auslesen import SCHEMA as SCHEMA_PHASE1
from .auslesen import OllamaAusleser
from .auslesen import normalisiere as normalisiere_phase1
from .chat_modell import SCHEMA as SCHEMA_CHAT
from .chat_modell import SYSTEMPROMPT as PROMPT_CHAT
from .chat_modell import normalisiere as normalisiere_chat
from .chat_modell import nutzertext
from .prompt import SYSTEMPROMPT as PROMPT_PHASE1
from .prompt import nutzernachricht

TEXTE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "texte.json"
CHAT = [
    "Rächnig für Familie Keller: 3 Stund à 90, 2 Schalter à 24, Sicherigskaschte 180",
    "Rächnig für Herr Meier: Boiler entkalche 2 Stund, Aafahrt 45",
    "Rächnig für Familie Keller: 2 Stund, 1 FI",
    "Rächnig für Herr Meier: 1 FI",
]


def kurz(positionen):
    return [f"{p['beschreibung']} | {p['menge']} {p['einheit']} | {p['einzelpreis']}" for p in positionen]


def main():
    client = OllamaAusleser()
    heute = date.today().isoformat()
    print(f"Modell: {config.OLLAMA_MODEL} · {config.OLLAMA_URL}\n")
    print("=== Phase 1: Auslesen ===")
    for fall in json.loads(TEXTE.read_text(encoding="utf-8")):
        t0 = time.perf_counter()
        roh = client.json_chat(PROMPT_PHASE1, nutzernachricht(fall["text"], heute), SCHEMA_PHASE1)
        print(f"\n# {fall['text']}  ({time.perf_counter() - t0:.1f} s)")
        print("roh:      ", json.dumps(roh.get("positionen"), ensure_ascii=False))
        print("bereinigt:", kurz(normalisiere_phase1(roh, fall["text"])["positionen"]))
    print("\n=== Phase 2: Chat (erste Nachricht, leeres Gedächtnis) ===")
    for text in CHAT:
        t0 = time.perf_counter()
        kontext = {"heute": heute, "entwurf": None, "rueckfrage": None, "wissen": []}
        roh = client.json_chat(PROMPT_CHAT, nutzertext(text, kontext), SCHEMA_CHAT)
        d = normalisiere_chat(roh, text)
        print(f"\n# {text}  ({time.perf_counter() - t0:.1f} s)")
        print("roh:      ", json.dumps(roh, ensure_ascii=False))
        print("bereinigt:", kurz(d["aenderungen"]["positionen"]), "unklar:", d["unklare_begriffe"])


if __name__ == "__main__":
    from .auslesen import AuslesenFehler

    try:
        main()
    except AuslesenFehler as e:
        raise SystemExit(f"Fehler: {e}")
