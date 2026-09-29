"""Gedächtnis: was Meisterli aus Rückfragen gelernt hat.

Arten: kunde, stundenansatz, begriff, materialpreis, vorgabe.
Suche ohne Vektordatenbank: Kunden unscharf (rapidfuzz), Begriffe als Wörter,
Stundenansatz und Vorgaben direkt.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from rapidfuzz import fuzz

from .db import Datenbank, normalisiere_name
from .rechnen import zahl

ARTEN = {
    "kunde": "Kunde",
    "stundenansatz": "Stundenansatz",
    "begriff": "Begriff",
    "materialpreis": "Materialpreis",
    "vorgabe": "Vorgabe",
}
STUNDENANSATZ = "stunde"

# Anreden und Artikel zählen beim Wiedererkennen von Kunden nicht.
_ANREDEN = {
    "familie", "fam", "herr", "hr", "herrn", "frau", "fr", "firma", "fa",
    "d", "de", "die", "der", "dr", "sig", "sgra", "mme", "m",
}
UNSCHARF_SCHWELLE = 88


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def woerter(text: str) -> list[str]:
    return re.findall(r"[\wäöüÄÖÜéèàç²-]+", (text or "").casefold())


def kern_name(name: str) -> str:
    """«Fam. Keller» → «keller»: ohne Anrede, Satzzeichen und Gross/klein."""
    teile = [w.strip("-") for w in re.split(r"[\s.,;:]+", (name or "").casefold()) if w.strip("-")]
    kern = [w for w in teile if w not in _ANREDEN]
    return " ".join(kern or teile)


@dataclass
class Kundensuche:
    treffer: dict | None  # eindeutiger Treffer (Wissenseintrag)
    kandidaten: list[dict]  # bei mehreren ähnlichen Treffern


class Gedaechtnis:
    def __init__(self, db: Datenbank):
        self.db = db

    # Lesen ---------------------------------------------------------------

    @staticmethod
    def _zeile(r) -> dict:
        d = dict(r)
        d["wert"] = json.loads(d["wert"])
        return d

    def alle(self, art: str | None = None) -> list[dict]:
        sql = "SELECT * FROM wissen"
        params: tuple = ()
        if art:
            sql += " WHERE art = ?"
            params = (art,)
        sql += " ORDER BY art, schluessel COLLATE NOCASE"
        with self.db.verbindung() as con:
            return [self._zeile(r) for r in con.execute(sql, params)]

    def hole(self, eintrag_id: int) -> dict | None:
        with self.db.verbindung() as con:
            r = con.execute("SELECT * FROM wissen WHERE id = ?", (eintrag_id,)).fetchone()
        return self._zeile(r) if r else None

    def finde(self, art: str, schluessel: str) -> dict | None:
        with self.db.verbindung() as con:
            r = con.execute(
                "SELECT * FROM wissen WHERE art = ? AND schluessel_norm = ?",
                (art, normalisiere_name(schluessel)),
            ).fetchone()
        return self._zeile(r) if r else None

    def benutzt(self, eintrag: dict | None) -> None:
        if not eintrag:
            return
        with self.db.verbindung() as con:
            con.execute("UPDATE wissen SET benutzt = benutzt + 1 WHERE id = ?", (eintrag["id"],))

    # Schreiben -----------------------------------------------------------

    def merke(
        self, art: str, schluessel: str, wert: dict, rueckfrage_id: int | None = None, quelle: str = "Rückfrage"
    ) -> dict:
        if art not in ARTEN:
            raise ValueError(f"Unbekannte Art: {art}")
        schluessel = schluessel.strip()
        jetzt = _jetzt()
        with self.db.verbindung() as con:
            con.execute(
                """INSERT INTO wissen
                   (art, schluessel, schluessel_norm, wert, quelle_rueckfrage_id, quelle, erstellt, geaendert)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (art, schluessel_norm) DO UPDATE SET
                       schluessel = excluded.schluessel, wert = excluded.wert,
                       quelle_rueckfrage_id = COALESCE(excluded.quelle_rueckfrage_id, quelle_rueckfrage_id),
                       quelle = excluded.quelle, geaendert = excluded.geaendert""",
                (
                    art, schluessel, normalisiere_name(schluessel),
                    json.dumps(wert, ensure_ascii=False), rueckfrage_id, quelle, jetzt, jetzt,
                ),
            )
            if art == "kunde":
                self.db.speichere_kunde(
                    con, wert.get("name") or schluessel,
                    wert.get("strasse", ""), wert.get("plz", ""), wert.get("ort", ""),
                )
        return self.finde(art, schluessel)

    def aendere(self, eintrag_id: int, schluessel: str, wert: dict) -> dict:
        alt = self.hole(eintrag_id)
        if not alt:
            raise KeyError(eintrag_id)
        with self.db.verbindung() as con:
            con.execute(
                """UPDATE wissen SET schluessel = ?, schluessel_norm = ?, wert = ?, geaendert = ?
                   WHERE id = ?""",
                (
                    schluessel.strip(), normalisiere_name(schluessel),
                    json.dumps(wert, ensure_ascii=False), _jetzt(), eintrag_id,
                ),
            )
            if alt["art"] == "kunde":
                self.db.speichere_kunde(
                    con, wert.get("name") or schluessel,
                    wert.get("strasse", ""), wert.get("plz", ""), wert.get("ort", ""),
                )
        return self.hole(eintrag_id)

    def loesche(self, eintrag_id: int) -> None:
        with self.db.verbindung() as con:
            con.execute("DELETE FROM wissen WHERE id = ?", (eintrag_id,))

    # Kunden ----------------------------------------------------------------

    def merke_kunde(self, name: str, strasse: str, plz: str, ort: str, rueckfrage_id=None, quelle="Rückfrage"):
        wert = {"name": name.strip(), "strasse": strasse.strip(), "plz": plz.strip(), "ort": ort.strip()}
        return self.merke("kunde", name, wert, rueckfrage_id, quelle)

    def suche_kunde(self, name: str) -> Kundensuche:
        """Exakter Name → Kern ohne Anrede → unscharf. Mehrere gleich gute Treffer → Rückfrage."""
        if not (name or "").strip():
            return Kundensuche(None, [])
        kunden = self.alle("kunde")
        norm = normalisiere_name(name)
        exakt = [k for k in kunden if k["schluessel_norm"] == norm]
        if len(exakt) == 1:
            return Kundensuche(exakt[0], [])
        kern = kern_name(name)
        gleich = [k for k in kunden if kern_name(k["schluessel"]) == kern]
        if len(gleich) == 1:
            return Kundensuche(gleich[0], [])
        if len(gleich) > 1:
            return Kundensuche(None, gleich)
        bewertet = sorted(
            ((fuzz.WRatio(kern, kern_name(k["schluessel"])), k) for k in kunden),
            key=lambda t: t[0], reverse=True,
        )
        gut = [(s, k) for s, k in bewertet if s >= UNSCHARF_SCHWELLE]
        if not gut:
            return Kundensuche(None, [])
        beste = gut[0][0]
        nahe = [k for s, k in gut if beste - s < 5]
        if len(nahe) == 1:
            return Kundensuche(nahe[0], [])
        return Kundensuche(None, nahe)

    # Stundenansatz, Begriffe, Preise, Vorgaben ----------------------------

    def stundenansatz(self) -> tuple[Decimal | None, dict | None]:
        e = self.finde("stundenansatz", STUNDENANSATZ)
        return (zahl(e["wert"]["betrag"]), e) if e else (None, None)

    def merke_stundenansatz(self, betrag: Decimal, rueckfrage_id=None):
        return self.merke("stundenansatz", STUNDENANSATZ, {"betrag": str(betrag)}, rueckfrage_id)

    def begriff(self, wort: str) -> dict | None:
        return self.finde("begriff", wort)

    def begriffe_in(self, text: str) -> list[dict]:
        """Gespeicherte Begriffe, die als ganzes Wort im Text vorkommen."""
        vorhanden = set(woerter(text))
        treffer = []
        for e in self.alle("begriff"):
            schluessel = woerter(e["schluessel"])
            if schluessel and all(w in vorhanden for w in schluessel):
                treffer.append(e)
        return treffer

    def merke_begriff(self, wort: str, bedeutung: str, rueckfrage_id=None):
        return self.merke("begriff", wort, {"bedeutung": bedeutung.strip()}, rueckfrage_id)

    def materialpreis(self, beschreibung: str) -> dict | None:
        e = self.finde("materialpreis", beschreibung)
        if e:
            return e
        norm = normalisiere_name(beschreibung)
        for kandidat in self.alle("materialpreis"):
            if fuzz.ratio(norm, kandidat["schluessel_norm"]) >= 92:
                return kandidat
        return None

    def merke_materialpreis(self, beschreibung: str, betrag: Decimal, einheit: str, rueckfrage_id=None):
        return self.merke(
            "materialpreis", beschreibung, {"betrag": str(betrag), "einheit": einheit or "Stk."}, rueckfrage_id
        )

    def vorgabe(self, schluessel: str):
        e = self.finde("vorgabe", schluessel)
        return (e["wert"].get("wert"), e) if e else (None, None)

    # Für das Sprachmodell ------------------------------------------------

    def relevant_fuer(self, text: str, kundenname: str = "") -> list[str]:
        """Kurze Zeilen mit den Einträgen, die zu einer Nachricht passen."""
        zeilen = []
        ansatz, _ = self.stundenansatz()
        if ansatz is not None:
            zeilen.append(f"Stundenansatz: {ansatz} CHF pro Stunde")
        begriffe = self.begriffe_in(text)
        for e in begriffe:
            zeilen.append(f"Begriff: «{e['schluessel']}» bedeutet «{e['wert']['bedeutung']}»")
        tokens = set(woerter(text)) | {w for e in begriffe for w in woerter(e["wert"]["bedeutung"])}
        for e in self.alle("materialpreis"):
            if set(woerter(e["schluessel"])) & tokens:
                zeilen.append(f"Materialpreis: {e['schluessel']} {e['wert']['betrag']} CHF pro {e['wert']['einheit']}")
        namen = {kundenname} if kundenname else set()
        for e in self.alle("kunde"):
            kern = kern_name(e["schluessel"])
            if kern and (set(kern.split()) <= set(woerter(text)) or e["schluessel"] in namen):
                w = e["wert"]
                zeilen.append(f"Kunde: {w['name']}, {w['strasse']}, {w['plz']} {w['ort']}")
        return zeilen

    # Zurücksetzen --------------------------------------------------------

    def alles_vergessen(self) -> None:
        self.db.alles_zuruecksetzen()
