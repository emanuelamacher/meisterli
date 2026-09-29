"""Das Sprachmodell im Chat: deutet eine Nachricht, entscheidet aber nichts.

Es liefert Absicht, Änderungen am Entwurf, die Antwort auf eine offene Rückfrage
und unklare Begriffe. Was daraus folgt, entscheidet `gespraech.py`.
"""

from datetime import date
from typing import Protocol

from .auslesen import AuslesenFehler, OllamaClient
from .positionen import fasse_taetigkeiten_zusammen, nur_positiv
from .prompt import MUNDART_BEISPIELE
from .rechnen import zahl

ABSICHTEN = ("neue_rechnung", "antwort", "korrektur", "bestaetigung", "abbruch", "anderes")

_T = {"type": ["string", "null"]}
_Z = {"type": ["number", "null"]}

SCHEMA = {
    "type": "object",
    "properties": {
        "absicht": {"type": "string", "enum": list(ABSICHTEN)},
        "aenderungen": {
            "type": "object",
            "properties": {
                "kunde": {
                    "type": "object",
                    "properties": {"name": _T, "strasse": _T, "plz": _T, "ort": _T},
                    "required": ["name", "strasse", "plz", "ort"],
                },
                "positionen": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"beschreibung": {"type": "string"}, "menge": _Z, "einheit": _T, "einzelpreis": _Z},
                        "required": ["beschreibung", "menge", "einheit", "einzelpreis"],
                    },
                },
                "positionen_aendern": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "nr": {"type": "integer"},
                            "beschreibung": _T,
                            "menge": _Z,
                            "einheit": _T,
                            "einzelpreis": _Z,
                            "entfernen": {"type": "boolean"},
                        },
                        "required": ["nr", "beschreibung", "menge", "einheit", "einzelpreis", "entfernen"],
                    },
                },
                "leistungsdatum": _T,
                "zahlungsfrist_tage": {"type": ["integer", "null"]},
            },
            "required": ["kunde", "positionen", "positionen_aendern", "leistungsdatum", "zahlungsfrist_tage"],
        },
        "antwort_auf_rueckfrage": {
            "type": "object",
            "properties": {
                "wert": _T, "bedeutung": _T, "betrag": _Z,
                "name": _T, "strasse": _T, "plz": _T, "ort": _T, "menge": _Z,
            },
            "required": ["wert", "bedeutung", "betrag", "name", "strasse", "plz", "ort", "menge"],
        },
        "unklare_begriffe": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["absicht", "aenderungen", "antwort_auf_rueckfrage", "unklare_begriffe"],
}

SYSTEMPROMPT = f"""\
Du bist der Teil von Meisterli, der Chat-Nachrichten eines Schweizer Handwerkers deutet.
Meisterli macht aus den Nachrichten Rechnungen. Die Nachrichten sind Schweizerdeutsch oder
Hochdeutsch, oft ungenau transkribiert. Antworte nur mit JSON nach dem Schema.
Du entscheidest nichts und rechnest nie. Du hältst nur fest, was in der Nachricht steht.

absicht:
- "neue_rechnung": Die Nachricht beginnt eine neue Rechnung (z. B. "Rächnig für …").
- "antwort": Die Nachricht beantwortet die offene Rückfrage.
- "korrektur": Die Nachricht ändert den bestehenden Entwurf ("nein, 4 Stunden", "Preis isch 95").
- "bestaetigung": Die Nachricht bestätigt die Zusammenfassung ("ja", "passt", "mach").
- "abbruch": Die Rechnung soll verworfen werden ("abbreche", "vergiss es").
- "anderes": alles andere (Smalltalk, Fragen, die nichts mit der Rechnung zu tun haben).

aenderungen (nur was in DIESER Nachricht steht, sonst null bzw. leere Liste):
- kunde: Name genau wie genannt, inklusive Anrede ("Familie Keller", "Herr Meier").
  Artikel wie "d", "de", "em" gehören nicht zum Namen. Adresse nur, wenn sie genannt wird.
- positionen: neue Positionen. Erfinde keine Preise und keine Mengen: Fehlt etwas, setze null.
  "2 Stund" ohne Preis → menge 2, einheit "Std.", einzelpreis null.
  Ein Betrag ohne Menge ist eine Pauschale: "Aafahrt 45" → menge 1, einheit "pauschal", einzelpreis 45.
  Ein Ding mit Anzahl ohne Preis: "1 FI" → beschreibung "FI", menge 1, einheit "Stk.", einzelpreis null.
  Steht nur eine Stundenzahl ohne Tätigkeit, heisst die Position "Arbeit".
  Wird die Tätigkeit vor den Stunden genannt ("Boiler entkalche 2 Stund"), ist sie die Beschreibung.
- positionen_aendern: Änderungen an bestehenden Positionen, "nr" ist die Nummer im Entwurf.
- leistungsdatum im Format JJJJ-MM-TT nur, wenn ein Tag genannt wird. zahlungsfrist_tage nur, wenn genannt.

antwort_auf_rueckfrage (nur bei absicht "antwort", sonst alles null):
- wert: die Antwort als kurzer Text.
- Adresse → strasse (mit Hausnummer), plz, ort. Kundenname → name.
- Zahl oder Preis → betrag (ohne Währung). Anzahl → menge.
- Erklärung eines Begriffs → bedeutung (Hochdeutsch), und betrag, falls ein Preis genannt wird:
  "FI-Schutzschalter, 85 Franke" → bedeutung "FI-Schutzschalter", betrag 85.

unklare_begriffe: Abkürzungen oder Wörter aus DIESER Nachricht, die du nicht sicher verstehst
und die für die Rechnung wichtig sind (z. B. "FI"). Begriffe aus dem Gedächtnis sind nie unklar.

Beschreibungen kurz, Hochdeutsch, Schweizer Rechtschreibung (immer "ss", nie Eszett).
Einheiten: "Std.", "Stk.", "m²", "m", "pauschal".

{MUNDART_BEISPIELE}"""


class ChatModell(Protocol):
    modell: str

    def deute(self, nachricht: str, kontext: dict) -> dict: ...


def nutzertext(nachricht: str, kontext: dict) -> str:
    teile = [f"Heute ist {kontext.get('heute') or date.today().isoformat()}."]
    entwurf = kontext.get("entwurf")
    if entwurf and (entwurf.get("kunde", {}).get("name") or entwurf.get("positionen")):
        k = entwurf.get("kunde", {})
        zeilen = [f"Kunde: {k.get('name') or '?'}"]
        for i, p in enumerate(entwurf.get("positionen", []), start=1):
            zeilen.append(
                f"{i}. {p.get('beschreibung')}: menge {p.get('menge') or '?'} {p.get('einheit') or ''}, "
                f"einzelpreis {p.get('einzelpreis') or '?'}"
            )
        teile.append("Aktueller Entwurf:\n" + "\n".join(zeilen))
    else:
        teile.append("Es ist kein Entwurf offen.")
    if kontext.get("rueckfrage"):
        teile.append(f"Offene Rückfrage von Meisterli: {kontext['rueckfrage']}")
    if kontext.get("wissen"):
        teile.append("Gedächtnis:\n" + "\n".join(f"- {z}" for z in kontext["wissen"]))
    teile.append(f"Nachricht:\n{nachricht.strip()}")
    return "\n\n".join(teile)


def _text(w) -> str | None:
    if w is None:
        return None
    t = str(w).strip()
    return t or None


def _zahl(w) -> str | None:
    try:
        d = zahl(w)
    except ValueError:
        return None
    return None if d is None else format(d.normalize(), "f")


def normalisiere(roh: dict, text: str = "") -> dict:
    """Bringt die Modellantwort in eine feste Form. Fehlende Teile werden leer."""
    if not isinstance(roh, dict):
        raise AuslesenFehler("Die Antwort des Sprachmodells ist kein JSON-Objekt.")
    absicht = roh.get("absicht") if roh.get("absicht") in ABSICHTEN else "anderes"
    ae = roh.get("aenderungen") if isinstance(roh.get("aenderungen"), dict) else {}
    kunde = ae.get("kunde") if isinstance(ae.get("kunde"), dict) else {}
    positionen = []
    for p in ae.get("positionen") or []:
        if isinstance(p, dict) and _text(p.get("beschreibung")):
            positionen.append({
                "beschreibung": _text(p.get("beschreibung")),
                "menge": nur_positiv(_zahl(p.get("menge"))),
                "einheit": _text(p.get("einheit")) or "",
                "einzelpreis": nur_positiv(_zahl(p.get("einzelpreis"))),
            })
    positionen = fasse_taetigkeiten_zusammen(positionen, text)
    aendern = []
    for p in ae.get("positionen_aendern") or []:
        if isinstance(p, dict) and isinstance(p.get("nr"), int):
            aendern.append({
                "nr": p["nr"],
                "beschreibung": _text(p.get("beschreibung")),
                "menge": nur_positiv(_zahl(p.get("menge"))),
                "einheit": _text(p.get("einheit")),
                "einzelpreis": nur_positiv(_zahl(p.get("einzelpreis"))),
                "entfernen": bool(p.get("entfernen")),
            })
    frist = ae.get("zahlungsfrist_tage")
    frist = int(frist) if isinstance(frist, (int, float)) and not isinstance(frist, bool) and frist > 0 else None
    antwort_roh = roh.get("antwort_auf_rueckfrage") if isinstance(roh.get("antwort_auf_rueckfrage"), dict) else {}
    antwort = {f: _text(antwort_roh.get(f)) for f in ("wert", "bedeutung", "name", "strasse", "plz", "ort")}
    antwort["betrag"] = nur_positiv(_zahl(antwort_roh.get("betrag")))
    antwort["menge"] = nur_positiv(_zahl(antwort_roh.get("menge")))
    return {
        "absicht": absicht,
        "aenderungen": {
            "kunde": {f: _text(kunde.get(f)) for f in ("name", "strasse", "plz", "ort")},
            "positionen": positionen,
            "positionen_aendern": aendern,
            "leistungsdatum": _text(ae.get("leistungsdatum")),
            "zahlungsfrist_tage": frist,
        },
        "antwort_auf_rueckfrage": antwort,
        "unklare_begriffe": [b.strip() for b in roh.get("unklare_begriffe") or [] if isinstance(b, str) and b.strip()],
    }


class OllamaChatModell(OllamaClient):
    def anfrage_text(self, nachricht: str, kontext: dict) -> str:
        return nutzertext(nachricht, kontext)

    def deute(self, nachricht: str, kontext: dict) -> dict:
        if not nachricht or not nachricht.strip():
            raise AuslesenFehler("Die Nachricht ist leer.")
        return normalisiere(self.json_chat(SYSTEMPROMPT, nutzertext(nachricht, kontext), SCHEMA), nachricht)

