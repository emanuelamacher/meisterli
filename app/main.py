"""FastAPI-App. Start: uvicorn --factory app.main:create_app --host 127.0.0.1"""

import time
import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config
from . import format as fmt
from .auslesen import Ausleser, AuslesenFehler, OllamaAusleser
from .chat import ChatDienst, chat_router
from .chat_modell import ChatModell, OllamaChatModell
from .db import Datenbank
from .gedaechtnis import Gedaechtnis
from .gespraech import Gespraech
from .dienst import (
    EingabeFehler,
    ergaenze_kunde,
    erstelle_rechnung,
    formatiere_iban,
    pruefe_einstellungen,
    vorschau_summen,
)
from .rechnen import zahl
from .transkription import (
    AUDIO_ENDUNGEN,
    Transkribierer,
    TranskriptionsFehler,
    standard_transkribierer,
)

APP_DIR = Path(__file__).resolve().parent


def create_app(
    data_dir: Path | None = None,
    transkribierer: Transkribierer | None = None,
    ausleser: Ausleser | None = None,
    chat_modell: ChatModell | None = None,
) -> FastAPI:
    data_dir = Path(data_dir or config.DATA_DIR)
    audio_dir = data_dir / "audio"
    pdf_dir = data_dir / "pdf"
    for ordner in (audio_dir, pdf_dir):
        ordner.mkdir(parents=True, exist_ok=True)

    db = Datenbank(data_dir / "meisterli.db")
    transkribierer = transkribierer or standard_transkribierer()
    ausleser = ausleser or OllamaAusleser()
    chat_modell = chat_modell or OllamaChatModell()
    gedaechtnis = Gedaechtnis(db)
    gespraech = Gespraech(db, gedaechtnis, chat_modell, pdf_dir)
    dienst = ChatDienst(db, gespraech, transkribierer, audio_dir)

    app = FastAPI(title="Meisterli-Pilot")
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=APP_DIR / "templates")
    templates.env.filters["chf"] = lambda w: fmt.chf(zahl(w))
    templates.env.filters["menge"] = lambda w: fmt.menge(zahl(w))
    templates.env.filters["datum"] = fmt.datum
    templates.env.globals["modell"] = getattr(ausleser, "modell", "")

    app.include_router(chat_router(db, gedaechtnis, dienst, templates, audio_dir))
    app.state.db = db
    app.state.gedaechtnis = gedaechtnis
    app.state.chat_dienst = dienst

    def seite(request: Request, name: str, **kontext):
        return templates.TemplateResponse(request, name, kontext)

    # Start ---------------------------------------------------------------

    @app.get("/")
    def start(request: Request):
        return seite(
            request,
            "start.html",
            aktiv="neu",
            einstellungen_ok=not pruefe_einstellungen(db.einstellungen()),
            transkribierer=transkribierer.name,
        )

    @app.post("/api/verarbeiten")
    def verarbeiten(audio: UploadFile | None = File(None), text: str | None = Form(None)):
        audio_pfad = None
        dauer_transkription = None
        if text and text.strip():
            transkript = text.strip()
        elif audio is not None and audio.filename:
            endung = Path(audio.filename).suffix.lower()
            if endung not in AUDIO_ENDUNGEN:
                return JSONResponse(
                    {"fehler": f"Dateiformat {endung or '?'} wird nicht unterstützt."}, 400
                )
            ziel = audio_dir / f"{date.today():%Y%m%d}-{uuid.uuid4().hex[:8]}{endung}"
            with ziel.open("wb") as f:
                while block := audio.file.read(1 << 20):
                    f.write(block)
            audio_pfad = str(ziel)
            t0 = time.perf_counter()
            try:
                transkript = transkribierer.transkribiere(ziel)
            except TranskriptionsFehler as e:
                return JSONResponse({"fehler": str(e)}, 502)
            dauer_transkription = round(time.perf_counter() - t0, 1)
            if not transkript:
                return JSONResponse(
                    {"fehler": "In der Aufnahme wurde kein Text erkannt.",
                     "dauer_transkription": dauer_transkription},
                    422,
                )
        else:
            return JSONResponse({"fehler": "Bitte Audio aufnehmen, hochladen oder Text eingeben."}, 400)

        t0 = time.perf_counter()
        try:
            entwurf = ausleser.lese_aus(transkript)
        except AuslesenFehler as e:
            return JSONResponse(
                {"fehler": str(e), "transkript": transkript,
                 "dauer_transkription": dauer_transkription},
                502,
            )
        dauer_auslesen = round(time.perf_counter() - t0, 1)

        entwurf_id = db.speichere_entwurf(
            transkript, entwurf, audio_pfad, dauer_transkription, dauer_auslesen
        )
        return {
            "entwurf_id": entwurf_id,
            "url": f"/vorschau/{entwurf_id}",
            "transkript": transkript,
            "dauer_transkription": dauer_transkription,
            "dauer_auslesen": dauer_auslesen,
        }

    # Vorschau ------------------------------------------------------------

    def lade_entwurf(entwurf_id: int) -> dict:
        entwurf = db.entwurf(entwurf_id)
        if not entwurf:
            raise HTTPException(404, "Entwurf nicht gefunden")
        return entwurf

    @app.get("/vorschau/{entwurf_id}")
    def vorschau(request: Request, entwurf_id: int):
        eintrag = lade_entwurf(entwurf_id)
        einstellungen = db.einstellungen()
        daten = ergaenze_kunde(db, eintrag["daten"])
        positionen = daten["positionen"] or [
            {"beschreibung": "", "menge": None, "einheit": "", "einzelpreis": None}
        ]
        return seite(
            request,
            "vorschau.html",
            aktiv="neu",
            eintrag=eintrag,
            daten=daten,
            positionen=positionen,
            unsicher=set(daten["unsichere_felder"]),
            summen=vorschau_summen(positionen, einstellungen["mwst_pflichtig"]),
            einstellungen=einstellungen,
            einstellungen_ok=not pruefe_einstellungen(einstellungen),
            heute=date.today().isoformat(),
        )

    @app.get("/entwuerfe/{entwurf_id}/audio")
    def entwurf_audio(entwurf_id: int):
        eintrag = lade_entwurf(entwurf_id)
        if not eintrag["audio_pfad"] or not Path(eintrag["audio_pfad"]).exists():
            raise HTTPException(404, "Keine Aufnahme")
        return FileResponse(eintrag["audio_pfad"])

    @app.post("/api/berechnen")
    async def berechnen(request: Request):
        eingabe = await request.json()
        return vorschau_summen(eingabe.get("positionen") or [], db.einstellungen()["mwst_pflichtig"])

    @app.get("/api/kunden")
    def kunde_suchen(name: str = ""):
        kunde = db.finde_kunde(name)
        if not kunde:
            return {"gefunden": False}
        return {"gefunden": True, **{f: kunde[f] for f in ("name", "strasse", "plz", "ort")}}

    @app.post("/api/rechnungen")
    async def rechnung_anlegen(request: Request):
        eingabe = await request.json()
        transkript = ""
        if eingabe.get("entwurf_id"):
            eintrag = db.entwurf(int(eingabe["entwurf_id"]))
            transkript = eintrag["transkript"] if eintrag else ""
        try:
            rechnung_id, nummer = erstelle_rechnung(db, pdf_dir, eingabe, transkript)
        except EingabeFehler as e:
            return JSONResponse({"fehler": e.fehler}, 422)
        return {
            "id": rechnung_id,
            "nummer": nummer,
            "pdf_url": f"/rechnungen/{rechnung_id}/pdf",
            "url": f"/rechnungen?neu={rechnung_id}",
        }

    # Rechnungen ----------------------------------------------------------

    @app.get("/rechnungen")
    def rechnungen(request: Request, neu: int | None = None):
        return seite(request, "rechnungen.html", aktiv="rechnungen", rechnungen=db.rechnungen(), neu=neu)

    @app.get("/rechnungen/{rechnung_id}/pdf")
    def rechnung_pdf(rechnung_id: int, download: bool = False):
        r = db.rechnung(rechnung_id)
        if not r or not r["pdf_pfad"] or not Path(r["pdf_pfad"]).exists():
            raise HTTPException(404, "PDF nicht gefunden")
        return FileResponse(
            r["pdf_pfad"],
            media_type="application/pdf",
            filename=f"Rechnung-{r['nummer']}.pdf",
            content_disposition_type="attachment" if download else "inline",
        )

    # Einstellungen -------------------------------------------------------

    @app.get("/einstellungen")
    def einstellungen(request: Request, gespeichert: bool = False):
        e = db.einstellungen()
        return seite(
            request, "einstellungen.html", aktiv="einstellungen",
            e=e, fehler={}, gespeichert=gespeichert,
        )

    @app.post("/einstellungen")
    def einstellungen_speichern(
        request: Request,
        firma_name: str = Form(""),
        firma_strasse: str = Form(""),
        firma_plz: str = Form(""),
        firma_ort: str = Form(""),
        iban: str = Form(""),
        uid: str = Form(""),
        mwst_pflichtig: str | None = Form(None),
        zahlungsfrist_tage: str = Form("30"),
    ):
        e = {
            "firma_name": firma_name.strip(),
            "firma_strasse": firma_strasse.strip(),
            "firma_plz": firma_plz.strip(),
            "firma_ort": firma_ort.strip(),
            "iban": formatiere_iban(iban),
            "uid": uid.strip(),
            "mwst_pflichtig": mwst_pflichtig is not None,
            "zahlungsfrist_tage": zahlungsfrist_tage.strip(),
        }
        fehler = pruefe_einstellungen(e)
        if fehler:
            return templates.TemplateResponse(
                request, "einstellungen.html",
                {"aktiv": "einstellungen", "e": e, "fehler": fehler, "gespeichert": False},
                status_code=422,
            )
        e["zahlungsfrist_tage"] = int(e["zahlungsfrist_tage"])
        db.speichere_einstellungen(e)
        return RedirectResponse("/einstellungen?gespeichert=1", status_code=303)

    return app
