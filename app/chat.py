"""Routen für den Chat (/chat, /api/chat/…) und das Gedächtnis (/wissen).

Der Browser schickt Nachrichten per POST. Transkription und Sprachmodell laufen im
Hintergrund; der Browser holt neue Nachrichten per Polling und zeigt «schreibt…»,
solange Meisterli arbeitet.
"""

import logging
import threading
import time
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import texte
from .auslesen import AuslesenFehler
from .db import Datenbank
from .dienst import pruefe_einstellungen
from .gedaechtnis import ARTEN, STUNDENANSATZ, Gedaechtnis
from .gespraech import Gespraech
from .rechnen import zahl
from .transkription import AUDIO_ENDUNGEN, Transkribierer, TranskriptionsFehler

log = logging.getLogger("meisterli.chat")


class ChatDienst:
    """Verarbeitet Nachrichten nacheinander und merkt sich, ob Meisterli gerade «schreibt»."""

    def __init__(self, db: Datenbank, gespraech: Gespraech, transkribierer: Transkribierer, audio_dir: Path):
        self.db = db
        self.gespraech = gespraech
        self.transkribierer = transkribierer
        self.audio_dir = audio_dir
        self._lock = threading.Lock()
        self._arbeitet: dict[int, int] = {}
        self._zaehler = threading.Lock()

    def schreibt(self, gespraech_id: int) -> bool:
        return self._arbeitet.get(gespraech_id, 0) > 0

    def beginne(self, gespraech_id: int) -> None:
        with self._zaehler:
            self._arbeitet[gespraech_id] = self._arbeitet.get(gespraech_id, 0) + 1

    def _fertig(self, gespraech_id: int) -> None:
        with self._zaehler:
            self._arbeitet[gespraech_id] = max(0, self._arbeitet.get(gespraech_id, 0) - 1)

    def begruesse(self, gespraech_id: int) -> None:
        if not self.db.nachrichten(gespraech_id):
            self.db.neue_nachricht(gespraech_id, "meisterli", "text", {"text": texte.BEGRUESSUNG})
            if pruefe_einstellungen(self.db.einstellungen()):
                self.db.neue_nachricht(gespraech_id, "meisterli", "text", {"text": texte.EINSTELLUNGEN_FEHLEN})

    def verarbeite(self, gespraech_id: int, nachricht_id: int) -> None:
        """Läuft im Hintergrund: Audio transkribieren, Nachricht deuten, Antworten speichern."""
        try:
            with self._lock:
                n = self.db.nachricht(nachricht_id)
                if n is None:  # Chat wurde inzwischen geleert
                    return
                if n["typ"] == "audio":
                    eingabe = self._transkribiere(n)
                    if eingabe is None:
                        return
                else:
                    eingabe = n["inhalt"]["text"]
                t0 = time.perf_counter()
                try:
                    antworten = self.gespraech.verarbeite(gespraech_id, eingabe)
                except AuslesenFehler as e:
                    antworten = [{"typ": "text", "inhalt": {"text": f"⚠️ {e}", "fehler": True}}]
                dauer = round(time.perf_counter() - t0, 1)
                for i, a in enumerate(antworten):
                    inhalt = dict(a["inhalt"], dauer_verarbeitung=dauer) if i == 0 else a["inhalt"]
                    self.db.neue_nachricht(gespraech_id, "meisterli", a["typ"], inhalt)
        except Exception as e:  # nie stillschweigend hängen bleiben
            log.exception("Fehler beim Verarbeiten")
            self.db.neue_nachricht(
                gespraech_id, "meisterli", "text", {"text": f"⚠️ Da ist etwas schiefgelaufen: {e}", "fehler": True}
            )
        finally:
            self._fertig(gespraech_id)

    def _transkribiere(self, n: dict) -> str | None:
        inhalt = dict(n["inhalt"])
        t0 = time.perf_counter()
        try:
            transkript = self.transkribierer.transkribiere(self.audio_dir / inhalt["datei"])
        except TranskriptionsFehler as e:
            inhalt.update(transkript="", status="fehler")
            self.db.aendere_nachricht(n["id"], inhalt)
            self.db.neue_nachricht(n["gespraech_id"], "meisterli", "text", {"text": f"⚠️ {e}", "fehler": True})
            return None
        inhalt.update(
            transkript=transkript, status="fertig", dauer_transkription=round(time.perf_counter() - t0, 1)
        )
        self.db.aendere_nachricht(n["id"], inhalt)
        if not transkript:
            self.db.neue_nachricht(
                n["gespraech_id"], "meisterli", "text", {"text": "Ich habe in der Sprachnachricht nichts verstanden."}
            )
            return None
        return transkript


def _aktive_knoepfe(nachrichten: list[dict], entwurf: dict | None) -> int | None:
    """Die Knöpfe der letzten Zusammenfassung sind aktiv, solange der Entwurf auf «Ja» wartet."""
    if not nachrichten or not entwurf or entwurf["zustand"] != "bestaetigen":
        return None
    letzte = nachrichten[-1]
    if letzte["typ"] == "zusammenfassung" and letzte["inhalt"].get("entwurf_id") == entwurf["id"]:
        return letzte["id"]
    return None


def chat_router(
    db: Datenbank,
    gedaechtnis: Gedaechtnis,
    dienst: ChatDienst,
    templates: Jinja2Templates,
    audio_dir: Path,
) -> APIRouter:
    router = APIRouter()

    # Chat ------------------------------------------------------------------

    @router.get("/chat")
    def chat_seite(request: Request):
        dienst.begruesse(db.aktuelles_gespraech())
        return templates.TemplateResponse(request, "chat.html", {})

    @router.get("/api/chat/verlauf")
    def verlauf(nach: int = 0):
        gid = db.aktuelles_gespraech()
        dienst.begruesse(gid)
        alle = db.nachrichten(gid)
        return {
            "gespraech_id": gid,
            "nachrichten": [n for n in alle if n["id"] > nach],
            "schreibt": dienst.schreibt(gid),
            "aktive_knoepfe": _aktive_knoepfe(alle, db.offener_entwurf(gid)),
            "letzte_id": alle[-1]["id"] if alle else 0,
        }

    @router.post("/api/chat/senden")
    def senden(
        hintergrund: BackgroundTasks,
        text: str | None = Form(None),
        audio: UploadFile | None = File(None),
        dauer: float | None = Form(None),
    ):
        gid = db.aktuelles_gespraech()
        if text and text.strip():
            nid = db.neue_nachricht(gid, "ich", "text", {"text": text.strip()})
        elif audio is not None and audio.filename:
            endung = Path(audio.filename).suffix.lower()
            if endung not in AUDIO_ENDUNGEN:
                return JSONResponse({"fehler": f"Dateiformat {endung or '?'} wird nicht unterstützt."}, 400)
            name = f"{date.today():%Y%m%d}-{uuid.uuid4().hex[:8]}{endung}"
            with (audio_dir / name).open("wb") as f:
                while block := audio.file.read(1 << 20):
                    f.write(block)
            nid = db.neue_nachricht(
                gid, "ich", "audio",
                {"datei": name, "dauer": dauer, "transkript": None, "status": "transkribiere"},
            )
        else:
            return JSONResponse({"fehler": "Leere Nachricht."}, 400)
        dienst.beginne(gid)
        hintergrund.add_task(dienst.verarbeite, gid, nid)
        return {"id": nid}

    @router.get("/api/chat/audio/{nachricht_id}")
    def audio_datei(nachricht_id: int):
        n = db.nachricht(nachricht_id)
        if not n or n["typ"] != "audio" or not (audio_dir / n["inhalt"]["datei"]).exists():
            raise HTTPException(404, "Keine Aufnahme")
        return FileResponse(audio_dir / n["inhalt"]["datei"])

    @router.get("/api/chat/pdf/{rechnung_id}")
    def pdf(rechnung_id: int):
        r = db.rechnung(rechnung_id)
        if not r or not r["pdf_pfad"] or not Path(r["pdf_pfad"]).exists():
            raise HTTPException(404, "PDF nicht gefunden")
        return FileResponse(
            r["pdf_pfad"], media_type="application/pdf",
            filename=f"Rechnung_{r['nummer']}.pdf", content_disposition_type="inline",
        )

    @router.post("/api/chat/leeren")
    def leeren():
        gid = db.aktuelles_gespraech()
        db.chat_leeren(gid)
        dienst.begruesse(gid)
        return {"ok": True}

    @router.post("/api/chat/zuruecksetzen")
    def zuruecksetzen():
        gedaechtnis.alles_vergessen()
        dienst.begruesse(db.aktuelles_gespraech())
        return {"ok": True}

    # Wissen ------------------------------------------------------------------

    @router.get("/wissen")
    def wissen(request: Request, meldung: str = "", fehler: str = ""):
        rueckfragen = {r["id"]: r for r in db.rueckfragen()}
        eintraege = gedaechtnis.alle()
        reihenfolge = list(ARTEN)
        eintraege.sort(key=lambda e: (reihenfolge.index(e["art"]), e["schluessel"].casefold()))
        return templates.TemplateResponse(
            request, "wissen.html",
            {"aktiv": "wissen", "eintraege": eintraege, "arten": ARTEN, "rueckfragen": rueckfragen,
             "meldung": meldung, "fehler": fehler,
             "frist": gedaechtnis.vorgabe("zahlungsfrist_tage")[0]},
        )

    def _zurueck(meldung: str = "", fehler: str = ""):
        from urllib.parse import urlencode

        return RedirectResponse("/wissen?" + urlencode({"meldung": meldung, "fehler": fehler}), status_code=303)

    def _betrag(w: str) -> str:
        try:
            d = zahl(w)
        except ValueError:
            d = None
        if d is None or d < 0:
            raise ValueError("Bitte einen gültigen Betrag eingeben.")
        return format(d.normalize(), "f")

    @router.post("/wissen/{eintrag_id}")
    async def wissen_aendern(eintrag_id: int, request: Request):
        e = gedaechtnis.hole(eintrag_id)
        if not e:
            return _zurueck(fehler="Eintrag nicht gefunden.")
        f = {k: str(v).strip() for k, v in (await request.form()).items()}
        try:
            art = e["art"]
            if art == "kunde":
                if not all(f.get(x) for x in ("name", "strasse", "plz", "ort")):
                    raise ValueError("Name, Strasse, PLZ und Ort ausfüllen.")
                schluessel = f["name"]
                wert = {x: f[x] for x in ("name", "strasse", "plz", "ort")}
            elif art == "stundenansatz":
                schluessel, wert = STUNDENANSATZ, {"betrag": _betrag(f.get("betrag", ""))}
            elif art == "begriff":
                if not f.get("schluessel") or not f.get("bedeutung"):
                    raise ValueError("Begriff und Bedeutung ausfüllen.")
                schluessel, wert = f["schluessel"], {"bedeutung": f["bedeutung"]}
            elif art == "materialpreis":
                if not f.get("schluessel"):
                    raise ValueError("Material ausfüllen.")
                schluessel = f["schluessel"]
                wert = {"betrag": _betrag(f.get("betrag", "")), "einheit": f.get("einheit") or "Stk."}
            else:
                schluessel, wert = e["schluessel"], {"wert": int(f.get("wert", ""))}
            gedaechtnis.aendere(eintrag_id, schluessel, wert)
        except ValueError as ex:
            return _zurueck(fehler=str(ex) if "invalid literal" not in str(ex) else "Bitte eine Zahl eingeben.")
        except Exception:
            return _zurueck(fehler="Speichern nicht möglich (gibt es den Eintrag schon?).")
        return _zurueck(meldung="Gespeichert.")

    @router.post("/wissen/{eintrag_id}/loeschen")
    def wissen_loeschen(eintrag_id: int):
        gedaechtnis.loesche(eintrag_id)
        return _zurueck(meldung="Gelöscht.")

    @router.post("/wissen-vorgabe/zahlungsfrist")
    def frist_setzen(wert: str = Form("")):
        if not wert.strip():
            e = gedaechtnis.vorgabe("zahlungsfrist_tage")[1]
            if e:
                gedaechtnis.loesche(e["id"])
            return _zurueck(meldung="Vorgabe entfernt.")
        try:
            tage = int(wert)
            if not 0 < tage <= 365:
                raise ValueError
        except ValueError:
            return _zurueck(fehler="Zahlungsfrist in Tagen (1–365).")
        gedaechtnis.merke("vorgabe", "zahlungsfrist_tage", {"wert": tage}, quelle="Wissen-Seite")
        return _zurueck(meldung="Gespeichert.")

    return router
