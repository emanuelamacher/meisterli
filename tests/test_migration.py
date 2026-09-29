import sqlite3

from app.db import SCHEMA, Datenbank


def phase1_datenbank(pfad):
    """Datenbank, wie sie Phase 1 hinterlassen hat (user_version 0)."""
    con = sqlite3.connect(pfad)
    con.executescript(SCHEMA)
    con.execute("UPDATE einstellungen SET firma_name = 'Elektro Muster GmbH' WHERE id = 1")
    con.execute(
        "INSERT INTO kunden (name, name_norm, strasse, plz, ort, erstellt) "
        "VALUES ('Familie Keller', 'familie keller', 'Rosenweg 7', '8404', 'Winterthur', '2026-09-01')"
    )
    con.execute(
        """INSERT INTO rechnungen (nummer, jahr, laufnummer, kunde_id, kunde_name, kunde_strasse,
           kunde_plz, kunde_ort, rechnungsdatum, leistungsdatum, faellig_am, zahlungsfrist_tage,
           mwst_pflichtig, mwst_satz, netto, mwst, total, erstellt)
           VALUES ('2026-001', 2026, 1, 1, 'Familie Keller', 'Rosenweg 7', '8404', 'Winterthur',
           '2026-09-01', '2026-09-01', '2026-10-01', 30, 1, '8.1', '498.00', '40.34', '538.34', 'x')"""
    )
    con.execute(
        "INSERT INTO entwuerfe (erstellt, transkript, daten) VALUES ('2026-09-01', 'Text', '{}')"
    )
    con.commit()
    con.close()


def test_migration_behaelt_daten(tmp_path):
    pfad = tmp_path / "meisterli.db"
    phase1_datenbank(pfad)

    db = Datenbank(pfad)

    assert db.sicherung is not None and db.sicherung.exists()
    assert db.einstellungen()["firma_name"] == "Elektro Muster GmbH"
    assert [r["nummer"] for r in db.rechnungen()] == ["2026-001"]
    assert db.finde_kunde("Familie Keller")["ort"] == "Winterthur"
    assert db.entwurf(1)["transkript"] == "Text"
    with db.verbindung() as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2
        tabellen = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        wissen = con.execute("SELECT art, schluessel, quelle FROM wissen").fetchall()
    assert {"gespraeche", "nachrichten", "entwuerfe", "rueckfragen", "wissen"} <= tabellen
    assert [tuple(w) for w in wissen] == [("kunde", "Familie Keller", "Phase 1")]


def test_migration_nur_einmal(tmp_path):
    pfad = tmp_path / "meisterli.db"
    phase1_datenbank(pfad)
    Datenbank(pfad)
    zweites_mal = Datenbank(pfad)
    assert zweites_mal.sicherung is None
    assert len(list(tmp_path.glob("meisterli.db.bak-*"))) == 1


def test_neue_datenbank_ohne_sicherung(tmp_path):
    db = Datenbank(tmp_path / "neu.db")
    assert db.sicherung is None
    assert db.aktuelles_gespraech() == db.aktuelles_gespraech()


def test_chat_tabellen(tmp_path):
    db = Datenbank(tmp_path / "t.db")
    g = db.aktuelles_gespraech()
    n = db.neue_nachricht(g, "ich", "text", {"text": "Hallo"})
    db.aendere_nachricht(n, {"text": "Hallo!"})
    assert db.nachrichten(g)[0]["inhalt"] == {"text": "Hallo!"}
    assert db.nachrichten(g, nach=n) == []

    e = db.neuer_chat_entwurf(g, {"positionen": []})
    assert db.offener_entwurf(g)["id"] == e
    db.speichere_chat_entwurf(e, {"positionen": [1]}, "sammeln", {"art": "adresse"})
    entwurf = db.offener_entwurf(g)
    assert entwurf["zustand"] == "sammeln" and entwurf["rueckfrage"] == {"art": "adresse"}

    db.chat_leeren(g)
    assert db.nachrichten(g) == [] and db.offener_entwurf(g) is None
    assert db.chat_entwurf(e)["zustand"] == "verworfen"


def test_zuruecksetzen_behaelt_rechnungen(tmp_path):
    pfad = tmp_path / "meisterli.db"
    phase1_datenbank(pfad)
    db = Datenbank(pfad)
    db.neue_nachricht(db.aktuelles_gespraech(), "ich", "text", {"text": "x"})
    db.alles_zuruecksetzen()
    assert db.finde_kunde("Familie Keller") is None
    assert [r["nummer"] for r in db.rechnungen()] == ["2026-001"]
    assert db.einstellungen()["firma_name"] == "Elektro Muster GmbH"
    with db.verbindung() as con:
        assert con.execute("SELECT count(*) FROM wissen").fetchone()[0] == 0
