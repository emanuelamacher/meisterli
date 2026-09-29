"""SQLite-Speicher für Einstellungen, Kunden, Entwürfe, Rechnungen und Positionen."""

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS einstellungen (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    firma_name TEXT NOT NULL DEFAULT '',
    firma_strasse TEXT NOT NULL DEFAULT '',
    firma_plz TEXT NOT NULL DEFAULT '',
    firma_ort TEXT NOT NULL DEFAULT '',
    iban TEXT NOT NULL DEFAULT '',
    uid TEXT NOT NULL DEFAULT '',
    mwst_pflichtig INTEGER NOT NULL DEFAULT 1,
    zahlungsfrist_tage INTEGER NOT NULL DEFAULT 30
);
INSERT OR IGNORE INTO einstellungen (id) VALUES (1);

CREATE TABLE IF NOT EXISTS kunden (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL UNIQUE,
    strasse TEXT NOT NULL DEFAULT '',
    plz TEXT NOT NULL DEFAULT '',
    ort TEXT NOT NULL DEFAULT '',
    erstellt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entwuerfe (
    id INTEGER PRIMARY KEY,
    erstellt TEXT NOT NULL,
    transkript TEXT NOT NULL,
    audio_pfad TEXT,
    dauer_transkription REAL,
    dauer_auslesen REAL,
    daten TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rechnungen (
    id INTEGER PRIMARY KEY,
    nummer TEXT NOT NULL UNIQUE,
    jahr INTEGER NOT NULL,
    laufnummer INTEGER NOT NULL,
    kunde_id INTEGER REFERENCES kunden(id),
    kunde_name TEXT NOT NULL,
    kunde_strasse TEXT NOT NULL,
    kunde_plz TEXT NOT NULL,
    kunde_ort TEXT NOT NULL,
    rechnungsdatum TEXT NOT NULL,
    leistungsdatum TEXT NOT NULL,
    faellig_am TEXT NOT NULL,
    zahlungsfrist_tage INTEGER NOT NULL,
    mwst_pflichtig INTEGER NOT NULL,
    mwst_satz TEXT,
    netto TEXT NOT NULL,
    mwst TEXT NOT NULL,
    total TEXT NOT NULL,
    pdf_pfad TEXT,
    transkript TEXT,
    erstellt TEXT NOT NULL,
    UNIQUE (jahr, laufnummer)
);

CREATE TABLE IF NOT EXISTS positionen (
    id INTEGER PRIMARY KEY,
    rechnung_id INTEGER NOT NULL REFERENCES rechnungen(id) ON DELETE CASCADE,
    nr INTEGER NOT NULL,
    beschreibung TEXT NOT NULL,
    menge TEXT NOT NULL,
    einheit TEXT NOT NULL,
    einzelpreis TEXT NOT NULL,
    betrag TEXT NOT NULL
);
"""

EINSTELLUNGEN_FELDER = (
    "firma_name",
    "firma_strasse",
    "firma_plz",
    "firma_ort",
    "iban",
    "uid",
    "mwst_pflichtig",
    "zahlungsfrist_tage",
)


def normalisiere_name(name: str) -> str:
    """Für das Wiedererkennen: Gross/klein und Leerzeichen spielen keine Rolle."""
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def formatiere_nummer(jahr: int, laufnummer: int) -> str:
    return f"{jahr}-{laufnummer:03d}"


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Datenbank:
    def __init__(self, pfad: Path):
        self.pfad = Path(pfad)
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        with self.verbindung() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def verbindung(self):
        con = sqlite3.connect(self.pfad)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    # Einstellungen -------------------------------------------------------

    def einstellungen(self) -> dict:
        with self.verbindung() as con:
            row = con.execute("SELECT * FROM einstellungen WHERE id = 1").fetchone()
        d = dict(row)
        d.pop("id")
        d["mwst_pflichtig"] = bool(d["mwst_pflichtig"])
        return d

    def speichere_einstellungen(self, werte: dict) -> None:
        felder = [f for f in EINSTELLUNGEN_FELDER if f in werte]
        if not felder:
            return
        zuweisung = ", ".join(f"{f} = ?" for f in felder)
        params = [int(werte[f]) if f == "mwst_pflichtig" else werte[f] for f in felder]
        with self.verbindung() as con:
            con.execute(f"UPDATE einstellungen SET {zuweisung} WHERE id = 1", params)

    # Kunden --------------------------------------------------------------

    def finde_kunde(self, name: str) -> dict | None:
        norm = normalisiere_name(name)
        if not norm:
            return None
        with self.verbindung() as con:
            row = con.execute("SELECT * FROM kunden WHERE name_norm = ?", (norm,)).fetchone()
        return dict(row) if row else None

    def speichere_kunde(self, con, name: str, strasse: str, plz: str, ort: str) -> int:
        norm = normalisiere_name(name)
        con.execute(
            """INSERT INTO kunden (name, name_norm, strasse, plz, ort, erstellt)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (name_norm) DO UPDATE SET
                   name = excluded.name, strasse = excluded.strasse,
                   plz = excluded.plz, ort = excluded.ort""",
            (name.strip(), norm, strasse, plz, ort, _jetzt()),
        )
        return con.execute("SELECT id FROM kunden WHERE name_norm = ?", (norm,)).fetchone()[0]

    # Entwürfe ------------------------------------------------------------

    def speichere_entwurf(
        self,
        transkript: str,
        daten: dict,
        audio_pfad: str | None = None,
        dauer_transkription: float | None = None,
        dauer_auslesen: float | None = None,
    ) -> int:
        with self.verbindung() as con:
            cur = con.execute(
                """INSERT INTO entwuerfe
                   (erstellt, transkript, audio_pfad, dauer_transkription, dauer_auslesen, daten)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    _jetzt(),
                    transkript,
                    audio_pfad,
                    dauer_transkription,
                    dauer_auslesen,
                    json.dumps(daten, ensure_ascii=False),
                ),
            )
            return cur.lastrowid

    def entwurf(self, entwurf_id: int) -> dict | None:
        with self.verbindung() as con:
            row = con.execute("SELECT * FROM entwuerfe WHERE id = ?", (entwurf_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["daten"] = json.loads(d["daten"])
        return d

    # Rechnungen ----------------------------------------------------------

    def naechste_laufnummer(self, con, jahr: int) -> int:
        row = con.execute(
            "SELECT COALESCE(MAX(laufnummer), 0) FROM rechnungen WHERE jahr = ?", (jahr,)
        ).fetchone()
        return row[0] + 1

    def lege_rechnung_an(self, con, rechnung: dict, positionen: list[dict]) -> tuple[int, str]:
        """Legt Rechnung + Positionen in der offenen Verbindung an (Transaktion beim Aufrufer)."""
        jahr = date.fromisoformat(rechnung["rechnungsdatum"]).year
        laufnummer = self.naechste_laufnummer(con, jahr)
        nummer = formatiere_nummer(jahr, laufnummer)
        daten = dict(rechnung, nummer=nummer, jahr=jahr, laufnummer=laufnummer, erstellt=_jetzt())
        spalten = ", ".join(daten)
        platzhalter = ", ".join("?" for _ in daten)
        cur = con.execute(
            f"INSERT INTO rechnungen ({spalten}) VALUES ({platzhalter})", list(daten.values())
        )
        rechnung_id = cur.lastrowid
        for nr, p in enumerate(positionen, start=1):
            con.execute(
                """INSERT INTO positionen
                   (rechnung_id, nr, beschreibung, menge, einheit, einzelpreis, betrag)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    rechnung_id,
                    nr,
                    p["beschreibung"],
                    str(p["menge"]),
                    p["einheit"],
                    str(p["einzelpreis"]),
                    str(p["betrag"]),
                ),
            )
        return rechnung_id, nummer

    def rechnungen(self) -> list[dict]:
        with self.verbindung() as con:
            rows = con.execute("SELECT * FROM rechnungen ORDER BY jahr DESC, laufnummer DESC")
            return [dict(r) for r in rows]

    def rechnung(self, rechnung_id: int) -> dict | None:
        with self.verbindung() as con:
            row = con.execute("SELECT * FROM rechnungen WHERE id = ?", (rechnung_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["positionen"] = [
                dict(p)
                for p in con.execute(
                    "SELECT * FROM positionen WHERE rechnung_id = ? ORDER BY nr", (rechnung_id,)
                )
            ]
        return d
