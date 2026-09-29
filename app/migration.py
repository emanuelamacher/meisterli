"""Schema-Versionen über PRAGMA user_version.

Version 1 = Phase 1 (Formular), Version 2 = Phase 2 (Chat, Rückfragen, Gedächtnis).
Vor jeder Migration einer bestehenden Datenbank wird eine Sicherungskopie angelegt.
"""

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

VERSION = 2

PHASE2 = """
CREATE TABLE IF NOT EXISTS gespraeche (
    id INTEGER PRIMARY KEY,
    erstellt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nachrichten (
    id INTEGER PRIMARY KEY,
    gespraech_id INTEGER NOT NULL REFERENCES gespraeche(id) ON DELETE CASCADE,
    absender TEXT NOT NULL CHECK (absender IN ('ich', 'meisterli')),
    typ TEXT NOT NULL,
    inhalt TEXT NOT NULL,
    zeit TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS nachrichten_gespraech ON nachrichten (gespraech_id, id);

CREATE TABLE IF NOT EXISTS rueckfragen (
    id INTEGER PRIMARY KEY,
    gespraech_id INTEGER REFERENCES gespraeche(id) ON DELETE SET NULL,
    entwurf_id INTEGER REFERENCES entwuerfe(id) ON DELETE SET NULL,
    art TEXT NOT NULL,
    schluessel TEXT NOT NULL DEFAULT '',
    frage TEXT NOT NULL,
    antwort TEXT,
    gefragt TEXT NOT NULL,
    beantwortet TEXT
);

CREATE TABLE IF NOT EXISTS wissen (
    id INTEGER PRIMARY KEY,
    art TEXT NOT NULL,
    schluessel TEXT NOT NULL,
    schluessel_norm TEXT NOT NULL,
    wert TEXT NOT NULL,
    quelle_rueckfrage_id INTEGER REFERENCES rueckfragen(id) ON DELETE SET NULL,
    quelle TEXT NOT NULL DEFAULT '',
    erstellt TEXT NOT NULL,
    geaendert TEXT NOT NULL,
    benutzt INTEGER NOT NULL DEFAULT 0,
    UNIQUE (art, schluessel_norm)
);
"""

ENTWURF_SPALTEN = {
    "gespraech_id": "INTEGER REFERENCES gespraeche(id) ON DELETE SET NULL",
    "zustand": "TEXT",
    "rueckfrage": "TEXT",
    "rechnung_id": "INTEGER",
    "geaendert": "TEXT",
}


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _hat_tabellen(con: sqlite3.Connection) -> bool:
    return con.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0] > 0


def _sichern(pfad: Path, von: int) -> Path | None:
    if not pfad.exists() or pfad.stat().st_size == 0:
        return None
    ziel = pfad.with_name(f"{pfad.name}.bak-v{von}-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(pfad, ziel)
    return ziel


def _auf_v2(con: sqlite3.Connection) -> None:
    con.executescript(PHASE2)
    vorhanden = {r[1] for r in con.execute("PRAGMA table_info(entwuerfe)")}
    for spalte, typ in ENTWURF_SPALTEN.items():
        if spalte not in vorhanden:
            con.execute(f"ALTER TABLE entwuerfe ADD COLUMN {spalte} {typ}")
    # Kunden aus Phase 1 kennt Meisterli ab sofort.
    from .db import normalisiere_name  # zyklischen Import vermeiden

    jetzt = _jetzt()
    for name, strasse, plz, ort in con.execute("SELECT name, strasse, plz, ort FROM kunden").fetchall():
        wert = {"name": name, "strasse": strasse, "plz": plz, "ort": ort}
        con.execute(
            """INSERT OR IGNORE INTO wissen
               (art, schluessel, schluessel_norm, wert, quelle, erstellt, geaendert)
               VALUES ('kunde', ?, ?, ?, 'Phase 1', ?, ?)""",
            (name, normalisiere_name(name), json.dumps(wert, ensure_ascii=False), jetzt, jetzt),
        )


def migriere(pfad: Path, phase1_schema: str) -> Path | None:
    """Bringt die Datenbank auf die aktuelle Version. Gibt die Sicherungskopie zurück (falls eine entstand)."""
    pfad = Path(pfad)
    con = sqlite3.connect(pfad)
    try:
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version >= VERSION:
            return None
        sicherung = _sichern(pfad, version) if _hat_tabellen(con) else None
        with con:
            con.executescript(phase1_schema)  # Phase-1-Tabellen (idempotent)
            _auf_v2(con)
            con.execute(f"PRAGMA user_version = {VERSION}")
        return sicherung
    finally:
        con.close()
