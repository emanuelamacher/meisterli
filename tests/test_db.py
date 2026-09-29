from app.db import Datenbank, formatiere_nummer, normalisiere_name


def rechnung(datum: str) -> dict:
    return dict(
        kunde_id=None, kunde_name="A", kunde_strasse="B 1", kunde_plz="3000", kunde_ort="Bern",
        rechnungsdatum=datum, leistungsdatum=datum, faellig_am=datum, zahlungsfrist_tage=30,
        mwst_pflichtig=1, mwst_satz="8.1", netto="1.00", mwst="0.08", total="1.08",
    )


def test_nummern_fortlaufend_pro_jahr(tmp_path):
    db = Datenbank(tmp_path / "t.db")
    nummern = []
    with db.verbindung() as con:
        for datum in ["2026-01-05", "2026-03-01", "2027-01-02", "2026-12-31", "2027-02-01"]:
            nummern.append(db.lege_rechnung_an(con, rechnung(datum), [])[1])
    assert nummern == ["2026-001", "2026-002", "2027-001", "2026-003", "2027-002"]
    assert formatiere_nummer(2026, 12) == "2026-012"


def test_kunden_wiedererkennen(tmp_path):
    db = Datenbank(tmp_path / "t.db")
    with db.verbindung() as con:
        db.speichere_kunde(con, "Familie Keller", "Rosenweg 5", "3006", "Bern")
    k = db.finde_kunde("  familie   KELLER ")
    assert k and k["strasse"] == "Rosenweg 5" and k["ort"] == "Bern"
    assert db.finde_kunde("Keller") is None
    with db.verbindung() as con:
        db.speichere_kunde(con, "Familie Keller", "Neuweg 1", "3000", "Bern")
    assert db.finde_kunde("Familie Keller")["strasse"] == "Neuweg 1"
    assert normalisiere_name(" A  b ") == "a b"


def test_einstellungen(tmp_path):
    db = Datenbank(tmp_path / "t.db")
    assert db.einstellungen()["zahlungsfrist_tage"] == 30
    assert db.einstellungen()["mwst_pflichtig"] is True
    db.speichere_einstellungen({"firma_name": "Muster", "mwst_pflichtig": False})
    e = db.einstellungen()
    assert e["firma_name"] == "Muster" and e["mwst_pflichtig"] is False


def test_fehler_rollt_zurueck(tmp_path):
    db = Datenbank(tmp_path / "t.db")
    try:
        with db.verbindung() as con:
            db.lege_rechnung_an(con, rechnung("2026-01-01"), [])
            raise RuntimeError("PDF kaputt")
    except RuntimeError:
        pass
    assert db.rechnungen() == []
