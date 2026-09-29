"""Bereinigung der Positionen, die das Sprachmodell liefert (Phase 1 und Chat).

Beobachtet mit qwen3:8b:
- Fehlende Preise kommen manchmal als 0 statt null.
- Eine Tätigkeit wird manchmal als eigene Position ohne Preis angelegt, getrennt von der
  Menge, die dazugehört: «Stube striiche, 42 m² à 18» → «Stube streichen» (1, 0) und (42 m², 18).
Python korrigiert das, statt auf das Modell zu hoffen.
"""

import re
from decimal import Decimal

GENERISCH = {
    "", "arbeit", "arbeiten", "arbeitszeit", "stunden", "stunde", "std", "std.", "aufwand",
    "fläche", "flaeche", "quadratmeter", "m²", "m2", "laufmeter", "zeit",
}
MENGEN_EINHEITEN = {"std.", "std", "h", "stunden", "m²", "m2", "m", "lfm", "km"}
ZAEHL_EINHEITEN = {"stk.", "stk", "stück"}


def nur_positiv(wert: str | None) -> str | None:
    """0 oder weniger als Menge oder Preis heisst: fehlt."""
    if wert is None:
        return None
    try:
        return wert if Decimal(wert) > 0 else None
    except Exception:
        return None


def _woerter(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüé]+", (text or "").casefold()) if len(w) > 2}


def _stamm(w: str) -> str:
    return w[:5]


def _verwandt(a: str, b: str) -> bool:
    return bool({_stamm(w) for w in _woerter(a)} & {_stamm(w) for w in _woerter(b)})


def _eins_genannt(text: str) -> bool:
    return bool(re.search(r"(?<![\d.,])1(?![\d.,])|\b(ein|eine|einen|eis|es|äs|ei)\b", (text or "").casefold()))


def fasse_taetigkeiten_zusammen(positionen: list[dict], text: str = "") -> list[dict]:
    """Verbindet eine Tätigkeit ohne Preis mit der folgenden Mengen-Position.

    Eine Position gilt als reine Tätigkeit, wenn sie keinen Preis hat und keine Menge –
    oder Menge 1, obwohl im Text nirgends «1» oder «ein» steht. Die folgende Position muss
    eine Menge haben und nach Stunden/Fläche aussehen oder zur Tätigkeit passen.
    """
    ergebnis: list[dict] = []
    i = 0
    while i < len(positionen):
        p = positionen[i]
        q = positionen[i + 1] if i + 1 < len(positionen) else None
        einheit_p = (p.get("einheit") or "").casefold()
        nur_taetigkeit = p.get("einzelpreis") is None and (
            p.get("menge") is None
            or (p.get("menge") == "1" and einheit_p not in ZAEHL_EINHEITEN and not _eins_genannt(text))
        )
        if q and nur_taetigkeit and q.get("menge") is not None:
            einheit_q = (q.get("einheit") or "").casefold()
            generisch = (q.get("beschreibung") or "").strip().casefold() in GENERISCH
            if einheit_q in MENGEN_EINHEITEN or generisch or _verwandt(p["beschreibung"], q["beschreibung"]):
                zusammen = dict(q)
                if generisch or _verwandt(p["beschreibung"], q["beschreibung"]):
                    zusammen["beschreibung"] = p["beschreibung"]
                else:
                    zusammen["beschreibung"] = f"{p['beschreibung']}: {q['beschreibung']}"
                ergebnis.append(zusammen)
                i += 2
                continue
        ergebnis.append(p)
        i += 1
    return ergebnis
