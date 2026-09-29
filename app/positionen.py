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


# Kunde und Datum ------------------------------------------------------------

ANREDEN = r"(?:Familie|Fam\.|Herr|Herrn|Hr\.|Frau|Fr\.|Firma)"
_ANREDE_WORT = re.compile(rf"^{ANREDEN}$", re.I)

DATUMSWOERTER = re.compile(
    r"\d{1,2}\.\s*(?:\d{1,2}\.?|[a-zä]{3,})|\d{4}-\d{2}-\d{2}|\b(?:hüt|hüte|heute|geschter|gestern|"
    r"vorgeschter|vorgestern|mäntig|montag|ziischtig|zischtig|dienstag|mittwoch|mittwuch|donnschtig|"
    r"donnerstag|fritig|freitag|samschtig|samstag|sunntig|sonntag|letscht\w*|letzte\w*)\b",
    re.I,
)


def datum_genannt(text: str) -> bool:
    return bool(DATUMSWOERTER.search(text or ""))


def bereinige_kunde(kunde: dict, text: str) -> dict:
    """Repariert typische Fehler beim Kunden.

    - «Familie» landet als Strasse → gehört zum Namen.
    - Die Anrede fehlt im Namen, steht aber im Text («Herr Meier» → «Meier»).
    - Eine Adresse ohne Hausnummer und ohne PLZ ist keine Adresse.
    """
    k = {f: (kunde.get(f) or "").strip() for f in ("name", "strasse", "plz", "ort")}
    if k["strasse"] and _ANREDE_WORT.match(k["strasse"]):
        k["name"] = f"{k['strasse']} {k['name']}".strip()
        k["strasse"] = ""
    if k["name"] and not re.match(rf"{ANREDEN}\s", k["name"], re.I):
        m = re.search(rf"({ANREDEN})\s+{re.escape(k['name'])}\b", text or "", re.I)
        if m:
            k["name"] = f"{m.group(1)} {k['name']}"
    hat_nummer = bool(re.search(r"\d", k["strasse"]))
    plz_ok = bool(re.fullmatch(r"\d{4}", k["plz"]))
    if not hat_nummer and not plz_ok:
        k["strasse"] = k["plz"] = k["ort"] = ""
    if k["plz"] and not plz_ok:
        k["plz"] = ""
    return {f: (k[f] or None) for f in k}


ABKUERZUNG = re.compile(r"(?<![\w-])([A-ZÄÖÜ]{2,4})(?![\w-])")
BEKANNTE_ABKUERZUNGEN = {"CHF", "MWST", "AG", "GMBH", "SA", "PLZ", "STK", "STD", "UID", "MWS"}


def abkuerzungen_im_text(text: str, kundenname: str = "") -> list[str]:
    """Kurze Abkürzungen in Grossbuchstaben (z. B. «FI»), die nicht zum Kundennamen gehören."""
    name = set(re.findall(r"[\wÄÖÜäöü]+", kundenname or ""))
    treffer = []
    for m in ABKUERZUNG.finditer(text or ""):
        w = m.group(1)
        if w.upper() not in BEKANNTE_ABKUERZUNGEN and w not in name and w not in treffer:
            treffer.append(w)
    return treffer
