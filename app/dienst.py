"""Ablauf zwischen Oberfläche, Rechnen, Speicher und PDF."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from stdnum import iban as iban_pruefung

from . import format as fmt
from .db import Datenbank
from .rechnen import MWST_SATZ, Position, berechne, zahl
from .rechnung import Adresse, RechnungsDaten, erstelle_pdf, qr_rechnung

KUNDENFELDER = ("name", "strasse", "plz", "ort")


@dataclass
class EingabeFehler(Exception):
    fehler: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return "; ".join(self.fehler.values())


# Vorschau ----------------------------------------------------------------


def ergaenze_kunde(db: Datenbank, entwurf: dict) -> dict:
    """Bekannter Kunde → Adresse übernehmen und nicht mehr als unsicher markieren."""
    entwurf = dict(entwurf, kunde=dict(entwurf["kunde"]))
    entwurf["kunde_bekannt"] = False
    kunde = db.finde_kunde(entwurf["kunde"].get("name", ""))
    if not kunde:
        return entwurf
    unsicher = set(entwurf["unsichere_felder"])
    for f in ("strasse", "plz", "ort"):
        if not entwurf["kunde"].get(f) and kunde[f]:
            entwurf["kunde"][f] = kunde[f]
            unsicher.discard(f"kunde.{f}")
    entwurf["kunde"]["name"] = kunde["name"]
    entwurf["unsichere_felder"] = sorted(unsicher)
    entwurf["kunde_bekannt"] = True
    return entwurf


def _leer(p: dict) -> bool:
    return not any(str(p.get(f) or "").strip() for f in ("beschreibung", "menge", "einzelpreis"))


def lies_positionen(roh: list[dict]) -> tuple[list[Position | None], dict[str, str]]:
    """Liest Formularzeilen. Ungültige Zeilen ergeben None und einen Fehler."""
    positionen: list[Position | None] = []
    fehler: dict[str, str] = {}
    for i, p in enumerate(roh or []):
        try:
            menge = zahl(p.get("menge"))
        except ValueError:
            menge = None
            fehler[f"positionen.{i}.menge"] = "Menge ist keine Zahl."
        try:
            preis = zahl(p.get("einzelpreis"))
        except ValueError:
            preis = None
            fehler[f"positionen.{i}.einzelpreis"] = "Preis ist keine Zahl."
        beschreibung = str(p.get("beschreibung") or "").strip()
        if _leer(p):
            positionen.append(None)
            continue
        if menge is None:
            fehler.setdefault(f"positionen.{i}.menge", "Menge fehlt.")
        if preis is None:
            fehler.setdefault(f"positionen.{i}.einzelpreis", "Preis fehlt.")
        if not beschreibung:
            fehler[f"positionen.{i}.beschreibung"] = "Beschreibung fehlt."
        if menge is None or preis is None:
            positionen.append(None)
        else:
            einheit = str(p.get("einheit") or "").strip()
            positionen.append(Position(beschreibung, menge, einheit, preis))
    return positionen, fehler


def vorschau_summen(roh_positionen: list[dict], mwst_pflichtig: bool) -> dict:
    """Für die Live-Berechnung im Formular. Ungültige Zeilen zählen nicht."""
    positionen, fehler = lies_positionen(roh_positionen)
    gueltig = [p for p in positionen if p is not None]
    summen = berechne(gueltig, mwst_pflichtig)
    return {
        "zeilen": [fmt.chf(p.betrag) if p else "" for p in positionen],
        "netto": fmt.chf(summen.netto),
        "mwst": fmt.chf(summen.mwst),
        "total": fmt.chf(summen.total),
        "mwst_pflichtig": mwst_pflichtig,
        "mwst_satz": str(MWST_SATZ) if mwst_pflichtig else None,
        "fehler": fehler,
    }


# Einstellungen -----------------------------------------------------------


def pruefe_einstellungen(e: dict) -> dict[str, str]:
    fehler = {}
    for f, name in [
        ("firma_name", "Firmenname"),
        ("firma_strasse", "Strasse"),
        ("firma_plz", "PLZ"),
        ("firma_ort", "Ort"),
        ("iban", "IBAN"),
    ]:
        if not str(e.get(f) or "").strip():
            fehler[f] = f"{name} fehlt."
    iban = str(e.get("iban") or "").replace(" ", "").upper()
    if iban and not (iban[:2] in ("CH", "LI") and iban_pruefung.is_valid(iban)):
        fehler["iban"] = "Keine gültige Schweizer IBAN (CH… oder LI…)."
    if e.get("mwst_pflichtig") and not str(e.get("uid") or "").strip():
        fehler["uid"] = "Wer MWST-pflichtig ist, braucht eine UID/MWST-Nummer."
    try:
        frist = int(e.get("zahlungsfrist_tage"))
        if not 0 < frist <= 365:
            raise ValueError
    except (TypeError, ValueError):
        fehler["zahlungsfrist_tage"] = "Zahlungsfrist in Tagen (1–365)."
    return fehler


def formatiere_iban(iban: str) -> str:
    kompakt = iban.replace(" ", "").upper()
    return " ".join(kompakt[i : i + 4] for i in range(0, len(kompakt), 4))


# Rechnung erstellen ------------------------------------------------------


def erstelle_rechnung(
    db: Datenbank, pdf_ordner: Path, eingabe: dict, transkript: str = "", heute: date | None = None
) -> tuple[int, str]:
    heute = heute or date.today()
    einstellungen = db.einstellungen()
    fehler: dict[str, str] = {}

    if pruefe_einstellungen(einstellungen):
        fehler["einstellungen"] = "Bitte zuerst die Firmendaten in den Einstellungen vervollständigen."

    kunde_roh = eingabe.get("kunde") or {}
    kunde = {f: str(kunde_roh.get(f) or "").strip() for f in KUNDENFELDER}
    if not kunde["name"]:
        fehler["kunde.name"] = "Kundenname fehlt."
    for f, name in [("strasse", "Strasse"), ("plz", "PLZ"), ("ort", "Ort")]:
        if not kunde[f]:
            fehler[f"kunde.{f}"] = f"{name} des Kunden fehlt – ohne Adresse keine Rechnung."

    leistungsdatum = heute
    if str(eingabe.get("leistungsdatum") or "").strip():
        try:
            leistungsdatum = date.fromisoformat(str(eingabe["leistungsdatum"]).strip())
        except ValueError:
            fehler["leistungsdatum"] = "Ungültiges Datum."

    frist = einstellungen["zahlungsfrist_tage"]
    if str(eingabe.get("zahlungsfrist_tage") or "").strip():
        try:
            frist = int(str(eingabe["zahlungsfrist_tage"]).strip())
            if not 0 < frist <= 365:
                raise ValueError
        except ValueError:
            fehler["zahlungsfrist_tage"] = "Zahlungsfrist in Tagen (1–365)."

    positionen, pos_fehler = lies_positionen(eingabe.get("positionen") or [])
    fehler.update(pos_fehler)
    positionen = [p for p in positionen if p is not None]
    if not positionen and not pos_fehler:
        fehler["positionen"] = "Mindestens eine Position erfassen."

    mwst_pflichtig = einstellungen["mwst_pflichtig"]
    summen = berechne(positionen, mwst_pflichtig)
    if positionen and not pos_fehler and summen.total <= 0:
        fehler["positionen"] = "Das Total muss grösser als 0 sein."
    if fehler:
        raise EingabeFehler(fehler)

    daten = RechnungsDaten(
        nummer="",
        firma=Adresse(
            einstellungen["firma_name"],
            einstellungen["firma_strasse"],
            einstellungen["firma_plz"],
            einstellungen["firma_ort"],
        ),
        uid=einstellungen["uid"],
        iban=einstellungen["iban"],
        kunde=Adresse(kunde["name"], kunde["strasse"], kunde["plz"], kunde["ort"]),
        rechnungsdatum=heute,
        leistungsdatum=leistungsdatum,
        faellig_am=heute + timedelta(days=frist),
        zahlungsfrist_tage=frist,
        mwst_pflichtig=mwst_pflichtig,
        positionen=positionen,
        summen=summen,
    )

    with db.verbindung() as con:
        kunde_id = db.speichere_kunde(con, **kunde)
        rechnung_id, nummer = db.lege_rechnung_an(
            con,
            {
                "kunde_id": kunde_id,
                "kunde_name": kunde["name"],
                "kunde_strasse": kunde["strasse"],
                "kunde_plz": kunde["plz"],
                "kunde_ort": kunde["ort"],
                "rechnungsdatum": heute.isoformat(),
                "leistungsdatum": leistungsdatum.isoformat(),
                "faellig_am": daten.faellig_am.isoformat(),
                "zahlungsfrist_tage": frist,
                "mwst_pflichtig": int(mwst_pflichtig),
                "mwst_satz": str(summen.mwst_satz) if summen.mwst_satz else None,
                "netto": str(summen.netto),
                "mwst": str(summen.mwst),
                "total": str(summen.total),
                "transkript": transkript,
            },
            [
                {
                    "beschreibung": p.beschreibung,
                    "menge": p.menge,
                    "einheit": p.einheit,
                    "einzelpreis": p.einzelpreis,
                    "betrag": p.betrag,
                }
                for p in positionen
            ],
        )
        daten.nummer = nummer
        try:
            qr_rechnung(daten)  # prüft Adressen und IBAN nach QR-Standard
        except ValueError as e:
            raise EingabeFehler({"qr": f"QR-Zahlteil nicht möglich: {e}"}) from e
        pfad = Path(pdf_ordner) / f"Rechnung-{nummer}.pdf"
        erstelle_pdf(daten, pfad)
        con.execute("UPDATE rechnungen SET pdf_pfad = ? WHERE id = ?", (str(pfad), rechnung_id))
    return rechnung_id, nummer
