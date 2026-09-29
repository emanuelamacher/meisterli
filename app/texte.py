"""Alle Nachrichten von Meisterli als Vorlagen. Kurz, im Du, Schweizer Rechtschreibung."""

from decimal import Decimal

from . import format as fmt

BEGRUESSUNG = (
    "Hallo! Ich bin Meisterli 👋 Schick mir eine Sprachnachricht oder schreib, was du gemacht hast. "
    "Ich mache die Rechnung daraus."
)
HILFE = "Ich helfe dir bei Rechnungen. Schreib zum Beispiel: «Rächnig für Familie Keller: 3 Stund à 90»."
VERWORFEN = "Okay, die Rechnung ist verworfen."
NICHTS_OFFEN = "Gerade ist keine Rechnung offen."
AENDERN = "Was soll ich ändern? Zum Beispiel: «4 Stunden statt 3» oder «Anfahrt 50»."
NOCH_OFFEN = "Mir fehlt noch etwas:"
NICHT_VERSTANDEN = "Das habe ich nicht verstanden."
ERSTELLEN_FRAGE = "Soll ich die Rechnung erstellen?"
EINSTELLUNGEN_FEHLEN = "Mir fehlen noch deine Firmendaten. Trag sie unter «Einstellungen» ein, dann geht es."

KNOEPFE = ["Ja, erstellen", "Ändern", "Abbrechen"]


def preis(betrag: Decimal | str | None) -> str:
    """90 → «90.–», 85.5 → «85.50»"""
    if betrag is None:
        return ""
    text = fmt.chf(Decimal(str(betrag)))
    return text[:-3] + ".–" if text.endswith(".00") else text


def _satz(t: str) -> str:
    return t if t.endswith(".") else t + "."


def frage_begriff(begriff: str) -> str:
    return f"Was meinst du mit «{begriff}»?"


def frage_stundenansatz() -> str:
    return "Welchen Stundenansatz nimmst du?"


def frage_preis(beschreibung: str, einheit: str) -> str:
    pro = f" pro {einheit}" if einheit and einheit not in ("pauschal",) else ""
    return f"Welchen Preis hat «{beschreibung}»{pro}?"


def frage_menge(beschreibung: str, einheit: str) -> str:
    if einheit == "Std.":
        return f"Wie viele Stunden waren es für «{beschreibung}»?"
    return f"Wie viele «{beschreibung}» waren es?"


def frage_positionen() -> str:
    return "Was hast du gemacht? Zum Beispiel: «3 Stunden à 90, Anfahrt 45»."


def frage_kunde_name() -> str:
    return "Für wen ist die Rechnung?"


def frage_kunde_wahl(kandidaten: list[dict]) -> str:
    namen = [f"{k['name']} ({k['ort']})" if k.get("ort") else k["name"] for k in kandidaten]
    return "Meinst du " + ", ".join(namen[:-1]) + " oder " + namen[-1] + "?"


def frage_adresse(name: str) -> str:
    return f"Welche Adresse hat {name}?"


def gemerkt_kunde(name: str, strasse: str, plz: str, ort: str) -> str:
    return _satz(f"Gemerkt: {name}, {strasse}, {plz} {ort}")


def gemerkt_stundenansatz(betrag) -> str:
    return f"Gemerkt: Stundenansatz {preis(betrag)}"


def gemerkt_begriff(begriff: str, bedeutung: str, betrag=None, einheit: str = "Stk.") -> str:
    text = f"Gemerkt: «{begriff}» = {bedeutung}"
    if betrag is not None:
        text += f", {preis(betrag)} pro {einheit}"
    return _satz(text)


def gemerkt_preis(beschreibung: str, betrag, einheit: str) -> str:
    pro = f" pro {einheit}" if einheit and einheit != "pauschal" else ""
    return _satz(f"Gemerkt: {beschreibung} {preis(betrag)}{pro}")


def fehler_beim_erstellen(fehler: dict) -> str:
    if "einstellungen" in fehler:
        return EINSTELLUNGEN_FEHLEN
    return "Das geht noch nicht: " + " ".join(fehler.values())
