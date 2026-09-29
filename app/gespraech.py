"""Gesprächslogik: Python entscheidet, nicht das Sprachmodell.

Zustände eines Entwurfs: leer → sammeln (Rückfrage offen) → bestaetigen → erstellt
(oder verworfen). Pro Nachricht:

1. Deuten: eindeutige Antworten (Knöpfe, «Ja», Adresse, Zahl …) direkt in Python,
   alles andere über das Sprachmodell.
2. Änderungen in den Entwurf einführen. Was ausdrücklich im Text steht, gewinnt.
3. Lücken aus dem Gedächtnis füllen (markiert als «gespeichert»).
4. Nächster Schritt: genau eine Rückfrage (Begriffe → Mengen/Preise → Kunde/Adresse)
   oder die Zusammenfassung. Ein PDF entsteht nur nach «Ja».
"""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from rapidfuzz import fuzz

from . import format as fmt
from . import texte
from .chat_modell import ChatModell
from .db import Datenbank, normalisiere_name
from .dienst import EingabeFehler, erstelle_rechnung
from .gedaechtnis import Gedaechtnis, woerter
from .rechnen import Position, berechne, zahl

KUNDENFELDER = ("name", "strasse", "plz", "ort")
ADRESSFELDER = ("strasse", "plz", "ort")

JA = {
    "ja", "jo", "jap", "jawohl", "genau", "passt", "ok", "okay", "mach", "mach das", "machs",
    "stimmt", "ja bitte", "ja, erstellen", "ja erstellen", "ja gern", "ja gerne", "gut", "erstellen",
}
ABBRUCH = {"abbrechen", "abbruch", "stopp", "stop", "vergiss es", "abbreche", "verwerfen", "lösch", "löschen"}
AENDERN = {"ändern", "aendern", "ändere", "korrigieren", "korrektur"}

_BETRAG = r"(?:à\s*|a\s+|je\s+)?(?P<betrag>\d+(?:[.,]\d{1,2})?)\s*(?:fr\.?|franken?|franke|stutz|chf|\.[-–])?\.?"
RE_BETRAG = re.compile(rf"^{_BETRAG}(?:\s*(?:pro|/|i\s*de|in\s*der)\s*(?:stund[e]?|std\.?|h|stk\.?|stück))?$", re.I)
RE_MENGE = re.compile(r"^(?P<menge>\d+(?:[.,]\d+)?)\s*(?:stk\.?|stück|std\.?|stund[e]?n?|mal|x)?\.?$", re.I)
RE_ADRESSE = re.compile(
    r"^(?P<strasse>[^\d,]*?[A-Za-zÄÖÜäöüéèà.]\s*\d+\s?[a-zA-Z]?)\s*,?\s*(?:CH-)?(?P<plz>\d{4})\s+(?P<ort>[^\d,]+?)\.?$"
)
RE_BEGRIFF_PREIS = re.compile(rf"^(?P<bedeutung>[^\d,]*[A-Za-zÄÖÜäöü][^\d,]*?)\s*(?:,\s*|\s+){_BETRAG}$", re.I)
RE_BEGRIFF = re.compile(r"^[A-Za-zÄÖÜäöüéè][\w\-äöüÄÖÜ ]{1,60}$")
RE_ABKUERZUNG = re.compile(r"^[A-ZÄÖÜ]{1,4}\d?$")
RE_NAME = re.compile(r"^[^\d]{2,60}$")

STUNDEN_EINHEITEN = {"std.", "std", "h", "stunde", "stunden", "stund"}


def _t(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().casefold()).strip(" .!?")


def ist_stunde(einheit: str) -> bool:
    return (einheit or "").strip().casefold() in STUNDEN_EINHEITEN


def leerer_entwurf() -> dict:
    return {
        "kunde": {"name": "", "strasse": "", "plz": "", "ort": "", "gespeichert": False},
        "kunde_kandidaten": [],
        "positionen": [],
        "leistungsdatum": None,
        "zahlungsfrist_tage": None,
        "unklare_begriffe": [],
        "geklaert": [],
        "texte": [],
    }


def leere_deutung(absicht: str) -> dict:
    return {
        "absicht": absicht,
        "aenderungen": {
            "kunde": {f: None for f in KUNDENFELDER},
            "positionen": [],
            "positionen_aendern": [],
            "leistungsdatum": None,
            "zahlungsfrist_tage": None,
        },
        "antwort_auf_rueckfrage": {
            f: None for f in ("wert", "bedeutung", "betrag", "name", "strasse", "plz", "ort", "menge")
        },
        "unklare_begriffe": [],
    }


def _hat_inhalt(ae: dict) -> bool:
    return bool(any(ae["kunde"].values()) or ae["positionen"] or ae["positionen_aendern"])


def nachricht(typ: str, **inhalt) -> dict:
    return {"typ": typ, "inhalt": inhalt}


def text(t: str) -> dict:
    return nachricht("text", text=t)


class Gespraech:
    def __init__(
        self,
        db: Datenbank,
        gedaechtnis: Gedaechtnis,
        modell: ChatModell,
        pdf_ordner: Path,
        heute: date | None = None,
    ):
        self.db = db
        self.g = gedaechtnis
        self.modell = modell
        self.pdf_ordner = Path(pdf_ordner)
        self._heute = heute

    @property
    def heute(self) -> date:
        return self._heute or date.today()

    # Einstieg -----------------------------------------------------------

    def verarbeite(self, gespraech_id: int, eingabe: str) -> list[dict]:
        """Verarbeitet eine Nachricht und gibt die Antworten von Meisterli zurück."""
        eingabe = (eingabe or "").strip()
        if not eingabe:
            return [text(texte.HILFE)]
        eintrag = self.db.offener_entwurf(gespraech_id)
        zustand = eintrag["zustand"] if eintrag else None
        rueckfrage = eintrag["rueckfrage"] if eintrag else None

        deutung = self.deute_direkt(eingabe, zustand, rueckfrage)
        if deutung is None:
            deutung = self.modell.deute(eingabe, self._kontext(eingabe, eintrag))
        absicht = deutung["absicht"]
        ae = deutung["aenderungen"]

        if absicht == "abbruch":
            if not eintrag:
                return [text(texte.NICHTS_OFFEN)]
            self._speichere(eintrag, "verworfen", None)
            return [text(texte.VERWORFEN)]

        if absicht == "aendern_knopf":
            if not eintrag:
                return [text(texte.NICHTS_OFFEN)]
            return [text(texte.AENDERN)]

        if absicht == "bestaetigung":
            if not eintrag:
                return [text(texte.NICHTS_OFFEN)]
            if zustand == "bestaetigen":
                return self._erstelle(eintrag)
            return [text(texte.NOCH_OFFEN)] + self._weiter(gespraech_id, eintrag)

        antworten: list[dict] = []
        if absicht == "neue_rechnung" or (not eintrag and _hat_inhalt(ae)):
            if eintrag:
                self._speichere(eintrag, "verworfen", None)
            entwurf_id = self.db.neuer_chat_entwurf(gespraech_id, leerer_entwurf())
            eintrag = self.db.chat_entwurf(entwurf_id)
            self._fuehre_ein(eintrag["daten"], ae, eingabe, deutung["unklare_begriffe"])
        elif absicht == "antwort" and eintrag and rueckfrage:
            antworten += self._beantworte(eintrag, rueckfrage, deutung["antwort_auf_rueckfrage"], eingabe)
            self._fuehre_ein(eintrag["daten"], ae, eingabe, deutung["unklare_begriffe"], korrektur=True)
        elif absicht in ("antwort", "korrektur") and eintrag and _hat_inhalt(ae):
            self._fuehre_ein(eintrag["daten"], ae, eingabe, deutung["unklare_begriffe"], korrektur=True)
        else:
            # «anderes» oder nichts Verwertbares: Meisterli führt keine allgemeinen Gespräche.
            antworten.append(text(texte.HILFE))
            if eintrag and rueckfrage:
                antworten.append(nachricht("rueckfrage", text=rueckfrage["frage"], art=rueckfrage["art"]))
            elif eintrag and zustand == "bestaetigen":
                antworten.append(text(texte.ERSTELLEN_FRAGE))
            return antworten

        return antworten + self._weiter(gespraech_id, eintrag)

    # 1. Deuten ------------------------------------------------------------

    def deute_direkt(self, eingabe: str, zustand: str | None, rueckfrage: dict | None) -> dict | None:
        """Eindeutige Nachrichten erkennt Python selbst – schneller und zuverlässiger."""
        t = _t(eingabe)
        if t in ABBRUCH:
            return leere_deutung("abbruch")
        if t in JA:
            return leere_deutung("bestaetigung")  # was daraus folgt, hängt vom Zustand ab
        if zustand == "bestaetigen" and t in AENDERN:
            return leere_deutung("aendern_knopf")
        if not rueckfrage:
            return None
        art = rueckfrage["art"]
        d = leere_deutung("antwort")
        a = d["antwort_auf_rueckfrage"]
        a["wert"] = eingabe.strip()
        if art in ("stundenansatz", "preis") and (m := RE_BETRAG.match(eingabe.strip())):
            a["betrag"] = m.group("betrag").replace(",", ".")
            return d
        if art == "menge" and (m := RE_MENGE.match(eingabe.strip())):
            a["menge"] = m.group("menge").replace(",", ".")
            return d
        if art == "adresse" and (m := RE_ADRESSE.match(eingabe.strip())):
            a.update(strasse=m.group("strasse").strip(), plz=m.group("plz"), ort=m.group("ort").strip())
            return d
        if art == "begriff":
            if m := RE_BEGRIFF_PREIS.match(eingabe.strip()):
                a.update(bedeutung=m.group("bedeutung").strip(), betrag=m.group("betrag").replace(",", "."))
                return d
            if RE_BEGRIFF.match(eingabe.strip()) and len(eingabe.split()) <= 4:
                a["bedeutung"] = eingabe.strip()
                return d
        if art == "kunde_wahl":
            optionen = rueckfrage.get("optionen") or []
            if t.isdigit() and 1 <= int(t) <= len(optionen):
                a["name"] = optionen[int(t) - 1]["name"]
                return d
            bewertet = sorted(
                ((fuzz.WRatio(eingabe, o["name"] + " " + o.get("ort", "")), o) for o in optionen),
                key=lambda s: s[0], reverse=True,
            )
            if bewertet and bewertet[0][0] >= 80 and (len(bewertet) == 1 or bewertet[1][0] < bewertet[0][0]):
                a["name"] = bewertet[0][1]["name"]
                return d
        if art == "kunde_name" and RE_NAME.match(eingabe.strip()) and len(eingabe.split()) <= 5:
            if not re.search(r"r[äa]chnig|rechnung", t):
                a["name"] = eingabe.strip()
                return d
        return None

    def _kontext(self, eingabe: str, eintrag: dict | None) -> dict:
        daten = eintrag["daten"] if eintrag else None
        name = daten["kunde"]["name"] if daten else ""
        return {
            "heute": self.heute.isoformat(),
            "entwurf": daten,
            "rueckfrage": eintrag["rueckfrage"]["frage"] if eintrag and eintrag.get("rueckfrage") else None,
            "wissen": self.g.relevant_fuer(eingabe, name),
        }

    # 2. Änderungen einführen ---------------------------------------------

    def _fuehre_ein(
        self, daten: dict, ae: dict, eingabe: str, unklar: list[str], korrektur: bool = False
    ) -> None:
        daten["texte"].append(eingabe)
        kunde = daten["kunde"]
        neu = {f: (ae["kunde"].get(f) or "").strip() for f in KUNDENFELDER}
        if neu["name"] and normalisiere_name(neu["name"]) != normalisiere_name(kunde["name"]):
            # Anderer Kunde: alte Adresse gilt nicht mehr.
            kunde.update(name=neu["name"], strasse="", plz="", ort="", gespeichert=False)
            daten["kunde_kandidaten"] = []
        for f in ADRESSFELDER:
            if neu[f]:
                kunde[f] = neu[f]
                kunde["gespeichert"] = False

        for p in ae["positionen"]:
            position = {
                "beschreibung": p["beschreibung"],
                "menge": p["menge"],
                "einheit": self._einheit(p.get("einheit")),
                "einzelpreis": p["einzelpreis"],
                "gespeichert": False,
                "begriff": None,
            }
            gleich = None
            if korrektur:
                gleich = next(
                    (q for q in daten["positionen"]
                     if normalisiere_name(q["beschreibung"]) == normalisiere_name(p["beschreibung"])),
                    None,
                )
            if gleich:
                self._aendere_position(gleich, p)
            else:
                daten["positionen"].append(position)

        for aenderung in sorted(ae["positionen_aendern"], key=lambda a: a["nr"], reverse=True):
            i = aenderung["nr"] - 1
            if not 0 <= i < len(daten["positionen"]):
                continue
            if aenderung["entfernen"]:
                daten["positionen"].pop(i)
            else:
                self._aendere_position(daten["positionen"][i], aenderung)

        if ae.get("leistungsdatum"):
            try:
                daten["leistungsdatum"] = date.fromisoformat(ae["leistungsdatum"]).isoformat()
            except ValueError:
                pass
        if ae.get("zahlungsfrist_tage"):
            daten["zahlungsfrist_tage"] = ae["zahlungsfrist_tage"]

        # Unklare Begriffe nur, wenn sie wirklich in der Nachricht stehen.
        im_text = set(woerter(eingabe))
        name_woerter = set(woerter(kunde["name"]))
        for b in unklar:
            if set(woerter(b)) <= im_text and not set(woerter(b)) <= name_woerter:
                if b not in daten["unklare_begriffe"]:
                    daten["unklare_begriffe"].append(b)

    def _aendere_position(self, position: dict, a: dict) -> None:
        if a.get("beschreibung"):
            position["beschreibung"] = a["beschreibung"]
        if a.get("menge") is not None:
            position["menge"] = a["menge"]
        if a.get("einheit"):
            position["einheit"] = self._einheit(a["einheit"])
        if a.get("einzelpreis") is not None:
            position["einzelpreis"] = a["einzelpreis"]
            position["gespeichert"] = False

    @staticmethod
    def _einheit(einheit: str | None) -> str:
        e = (einheit or "").strip()
        if ist_stunde(e):
            return "Std."
        if e.casefold() in ("stk", "stk.", "stück", "stueck"):
            return "Stk."
        return e

    # 3. Rückfrage beantworten und lernen ---------------------------------

    def _beantworte(self, eintrag: dict, rueckfrage: dict, a: dict, eingabe: str) -> list[dict]:
        daten = eintrag["daten"]
        art = rueckfrage["art"]
        rid = rueckfrage["id"]
        schluessel = rueckfrage.get("schluessel", "")
        antworten: list[dict] = []
        verstanden = False

        if art == "adresse" and a.get("strasse") and a.get("plz") and a.get("ort"):
            k = daten["kunde"]
            k.update(strasse=a["strasse"], plz=a["plz"], ort=a["ort"], gespeichert=False)
            self.g.merke_kunde(k["name"], k["strasse"], k["plz"], k["ort"], rueckfrage_id=rid)
            antworten.append(text(texte.gemerkt_kunde(k["name"], k["strasse"], k["plz"], k["ort"])))
            verstanden = True

        elif art == "stundenansatz" and (betrag := self._zahl(a.get("betrag"))) is not None:
            for p in daten["positionen"]:
                if ist_stunde(p["einheit"]) and p["einzelpreis"] is None:
                    p["einzelpreis"] = str(betrag)
            self.g.merke_stundenansatz(betrag, rueckfrage_id=rid)
            antworten.append(text(texte.gemerkt_stundenansatz(betrag)))
            verstanden = True

        elif art == "preis" and (betrag := self._zahl(a.get("betrag"))) is not None:
            einheit = "Stk."
            for p in daten["positionen"]:
                if normalisiere_name(p["beschreibung"]) == normalisiere_name(schluessel) and p["einzelpreis"] is None:
                    p["einzelpreis"] = str(betrag)
                    einheit = p["einheit"] or "Stk."
            self.g.merke_materialpreis(schluessel, betrag, einheit, rueckfrage_id=rid)
            antworten.append(text(texte.gemerkt_preis(schluessel, betrag, einheit)))
            verstanden = True

        elif art == "menge" and (menge := self._zahl(a.get("menge") or a.get("betrag"))) is not None:
            i = int(schluessel)
            if 0 <= i < len(daten["positionen"]):
                daten["positionen"][i]["menge"] = str(menge)
            verstanden = True

        elif art == "begriff" and (bedeutung := (a.get("bedeutung") or "").strip()):
            betrag = self._zahl(a.get("betrag"))
            einheit = "Stk."
            for p in daten["positionen"]:
                if self._ersetze_begriff(p, schluessel, bedeutung):
                    einheit = p["einheit"] or "Stk."
                    if betrag is not None and p["einzelpreis"] is None:
                        p["einzelpreis"] = str(betrag)
            daten["geklaert"].append(schluessel)
            self.g.merke_begriff(schluessel, bedeutung, rueckfrage_id=rid)
            if betrag is not None:
                self.g.merke_materialpreis(bedeutung, betrag, einheit, rueckfrage_id=rid)
            antworten.append(text(texte.gemerkt_begriff(schluessel, bedeutung, betrag, einheit)))
            verstanden = True

        elif art == "kunde_wahl" and a.get("name"):
            treffer = self.g.finde("kunde", a["name"])
            if treffer:
                w = treffer["wert"]
                daten["kunde"].update(
                    name=w["name"], strasse=w["strasse"], plz=w["plz"], ort=w["ort"], gespeichert=True
                )
                daten["kunde_kandidaten"] = []
                self.g.benutzt(treffer)
                verstanden = True

        elif art == "kunde_name" and a.get("name"):
            daten["kunde"].update(name=a["name"].strip(), strasse="", plz="", ort="", gespeichert=False)
            verstanden = True

        elif art == "positionen":
            verstanden = True  # die Positionen kommen über die Änderungen

        if verstanden:
            self.db.beantworte_rueckfrage(rid, eingabe)
            eintrag["rueckfrage"] = None
        else:
            antworten.append(text(texte.NICHT_VERSTANDEN))
        return antworten

    @staticmethod
    def _zahl(w) -> Decimal | None:
        try:
            d = zahl(w)
        except ValueError:
            return None
        return d if d is not None and d >= 0 else None

    @staticmethod
    def _ersetze_begriff(position: dict, begriff: str, bedeutung: str) -> bool:
        """Ersetzt einen Begriff (ganzes Wort) in der Beschreibung durch seine Bedeutung."""
        b = position["beschreibung"]
        if normalisiere_name(b) == normalisiere_name(begriff):
            position["beschreibung"] = bedeutung
        else:
            neu = re.sub(rf"(?<![\w-]){re.escape(begriff)}(?![\w-])", bedeutung, b, flags=re.I)
            if neu == b:
                return False
            position["beschreibung"] = neu
        position["begriff"] = begriff
        return True

    # 4. Lücken füllen und nächster Schritt ------------------------------

    def fuelle_luecken(self, daten: dict) -> None:
        """Gespeichertes Wissen füllt nur Lücken und überschreibt nichts."""
        for p in daten["positionen"]:
            if not p.get("begriff"):
                for e in self.g.begriffe_in(p["beschreibung"]):
                    if self._ersetze_begriff(p, e["schluessel"], e["wert"]["bedeutung"]):
                        self.g.benutzt(e)
            if p["einzelpreis"] is None:
                if ist_stunde(p["einheit"]):
                    ansatz, e = self.g.stundenansatz()
                    if ansatz is not None:
                        p.update(einzelpreis=str(ansatz), gespeichert=True)
                        self.g.benutzt(e)
                elif e := self.g.materialpreis(p["beschreibung"]):
                    p.update(einzelpreis=e["wert"]["betrag"], gespeichert=True)
                    if not p["einheit"]:
                        p["einheit"] = e["wert"].get("einheit") or "Stk."
                    self.g.benutzt(e)
            if not p["einheit"] and p["menge"] is not None:
                p["einheit"] = "Stk."

        k = daten["kunde"]
        if k["name"] and not all(k[f] for f in ADRESSFELDER) and not daten["kunde_kandidaten"]:
            suche = self.g.suche_kunde(k["name"])
            if suche.treffer:
                w = suche.treffer["wert"]
                if not any(k[f] for f in ADRESSFELDER):
                    k["name"] = w["name"]
                for f in ADRESSFELDER:
                    if not k[f] and w.get(f):
                        k[f] = w[f]
                        k["gespeichert"] = True
                self.g.benutzt(suche.treffer)
            elif suche.kandidaten:
                daten["kunde_kandidaten"] = [
                    {"name": c["wert"]["name"], "ort": c["wert"].get("ort", "")} for c in suche.kandidaten
                ]

    def offene_begriffe(self, daten: dict) -> list[str]:
        begriffe = list(daten["unklare_begriffe"])
        for p in daten["positionen"]:
            b = p["beschreibung"].strip()
            if not p.get("begriff") and RE_ABKUERZUNG.match(b) and b not in begriffe:
                begriffe.append(b)
        geklaert = {normalisiere_name(b) for b in daten["geklaert"]}
        offen = []
        for b in begriffe:
            if normalisiere_name(b) in geklaert or self.g.begriff(b):
                continue
            offen.append(b)
        return offen

    def naechste_rueckfrage(self, daten: dict) -> dict | None:
        """Höchstens eine Frage: Begriffe → Mengen/Preise → Kunde/Adresse."""
        if offen := self.offene_begriffe(daten):
            return {"art": "begriff", "schluessel": offen[0], "frage": texte.frage_begriff(offen[0])}
        if not daten["positionen"]:
            return {"art": "positionen", "schluessel": "", "frage": texte.frage_positionen()}
        for i, p in enumerate(daten["positionen"]):
            if p["menge"] is None:
                return {"art": "menge", "schluessel": str(i),
                        "frage": texte.frage_menge(p["beschreibung"], p["einheit"])}
            if p["einzelpreis"] is None:
                if ist_stunde(p["einheit"]):
                    return {"art": "stundenansatz", "schluessel": "", "frage": texte.frage_stundenansatz()}
                return {"art": "preis", "schluessel": p["beschreibung"],
                        "frage": texte.frage_preis(p["beschreibung"], p["einheit"])}
        k = daten["kunde"]
        if not k["name"]:
            return {"art": "kunde_name", "schluessel": "", "frage": texte.frage_kunde_name()}
        if daten["kunde_kandidaten"]:
            return {"art": "kunde_wahl", "schluessel": k["name"], "optionen": daten["kunde_kandidaten"],
                    "frage": texte.frage_kunde_wahl(daten["kunde_kandidaten"])}
        if not all(k[f] for f in ADRESSFELDER):
            return {"art": "adresse", "schluessel": k["name"], "frage": texte.frage_adresse(k["name"])}
        return None

    def _weiter(self, gespraech_id: int, eintrag: dict) -> list[dict]:
        daten = eintrag["daten"]
        self.fuelle_luecken(daten)
        frage = self.naechste_rueckfrage(daten)
        if frage:
            offen = eintrag.get("rueckfrage")
            if offen and (offen["art"], offen["schluessel"]) == (frage["art"], frage["schluessel"]):
                frage["id"] = offen["id"]  # dieselbe Frage nochmals, kein neuer Eintrag
            else:
                frage["id"] = self.db.neue_rueckfrage(
                    gespraech_id, eintrag["id"], frage["art"], frage["schluessel"], frage["frage"]
                )
            self._speichere(eintrag, "sammeln", frage)
            return [nachricht("rueckfrage", text=frage["frage"], art=frage["art"])]
        self._speichere(eintrag, "bestaetigen", None)
        return [self.zusammenfassung(eintrag)]

    def _speichere(self, eintrag: dict, zustand: str, rueckfrage: dict | None, rechnung_id=None) -> None:
        eintrag["zustand"] = zustand
        eintrag["rueckfrage"] = rueckfrage
        self.db.speichere_chat_entwurf(eintrag["id"], eintrag["daten"], zustand, rueckfrage, rechnung_id)

    # Zusammenfassung und PDF --------------------------------------------

    def _positionen(self, daten: dict) -> list[Position]:
        return [
            Position(p["beschreibung"], Decimal(p["menge"]), p["einheit"], Decimal(p["einzelpreis"]))
            for p in daten["positionen"]
        ]

    def zusammenfassung(self, eintrag: dict) -> dict:
        daten = eintrag["daten"]
        mwst_pflichtig = self.db.einstellungen()["mwst_pflichtig"]
        positionen = self._positionen(daten)
        summen = berechne(positionen, mwst_pflichtig)
        k = daten["kunde"]
        return nachricht(
            "zusammenfassung",
            entwurf_id=eintrag["id"],
            kunde={f: k[f] for f in KUNDENFELDER} | {"gespeichert": k["gespeichert"]},
            positionen=[
                {
                    "beschreibung": pos.beschreibung,
                    "menge": fmt.menge(pos.menge),
                    "einheit": pos.einheit,
                    "preis": texte.preis(pos.einzelpreis),
                    "betrag": fmt.chf(betrag),
                    "gespeichert": bool(p.get("gespeichert")),
                }
                for pos, betrag, p in zip(positionen, summen.zeilen, daten["positionen"])
            ],
            leistungsdatum=fmt.datum(daten["leistungsdatum"] or self.heute),
            leistungsdatum_heute=not daten["leistungsdatum"],
            mwst_pflichtig=mwst_pflichtig,
            mwst_satz=str(summen.mwst_satz) if summen.mwst_satz else None,
            netto=fmt.chf(summen.netto),
            mwst=fmt.chf(summen.mwst),
            total=fmt.chf(summen.total),
            knoepfe=texte.KNOEPFE,
        )

    def _erstelle(self, eintrag: dict) -> list[dict]:
        daten = eintrag["daten"]
        frist = daten["zahlungsfrist_tage"]
        if not frist:
            frist, e = self.g.vorgabe("zahlungsfrist_tage")
            self.g.benutzt(e)
        k = daten["kunde"]
        eingabe = {
            "kunde": {f: k[f] for f in KUNDENFELDER},
            "leistungsdatum": daten["leistungsdatum"] or "",
            "zahlungsfrist_tage": str(frist) if frist else "",
            "positionen": [
                {f: p[f] for f in ("beschreibung", "menge", "einheit", "einzelpreis")} for p in daten["positionen"]
            ],
        }
        try:
            rechnung_id, nummer = erstelle_rechnung(
                self.db, self.pdf_ordner, eingabe, "\n".join(daten["texte"]), self.heute
            )
        except EingabeFehler as e:
            return [text(texte.fehler_beim_erstellen(e.fehler))]
        if not self.g.suche_kunde(k["name"]).treffer:
            self.g.merke_kunde(k["name"], k["strasse"], k["plz"], k["ort"], quelle="Rechnung")
        self._speichere(eintrag, "erstellt", None, rechnung_id)
        pfad = self.db.rechnung(rechnung_id)["pdf_pfad"]
        return [
            nachricht(
                "pdf",
                rechnung_id=rechnung_id,
                nummer=nummer,
                dateiname=f"Rechnung_{nummer}.pdf",
                seiten=pdf_seiten(Path(pfad)),
                groesse_kb=max(1, round(Path(pfad).stat().st_size / 1024)),
            )
        ]


def pdf_seiten(pfad: Path) -> int:
    return max(1, len(re.findall(rb"/Type\s*/Page(?![s\w])", pfad.read_bytes())))

