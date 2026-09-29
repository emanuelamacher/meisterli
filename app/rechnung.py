"""QR-Zahlteil (qrbill) und PDF-Erzeugung (WeasyPrint)."""

import base64
import io
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from qrbill import QRBill

from . import format as fmt
from .rechnen import Position, Summen

TEMPLATES = Path(__file__).resolve().parent / "templates"


@dataclass
class Adresse:
    name: str
    strasse: str
    plz: str
    ort: str

    def vollstaendig(self) -> bool:
        return all(s and s.strip() for s in (self.name, self.strasse, self.plz, self.ort))


@dataclass
class RechnungsDaten:
    nummer: str
    firma: Adresse
    uid: str
    iban: str
    kunde: Adresse
    rechnungsdatum: date
    leistungsdatum: date
    faellig_am: date
    zahlungsfrist_tage: int
    mwst_pflichtig: bool
    positionen: list[Position]
    summen: Summen


def teile_strasse(strasse: str) -> tuple[str, str]:
    """«Lindenweg 4b» → («Lindenweg», «4b»). Ohne Hausnummer bleibt alles in der Strasse."""
    strasse = (strasse or "").strip()
    m = re.fullmatch(r"(.*?\S)\s+(\d+\s?[a-zA-Z]?(?:[-/]\d+[a-zA-Z]?)?)", strasse)
    if m:
        return m.group(1), m.group(2).replace(" ", "")
    return strasse, ""


def _qr_adresse(a: Adresse) -> dict:
    strasse, hausnummer = teile_strasse(a.strasse)
    return {
        "name": a.name.strip(),
        "street": strasse,
        "house_num": hausnummer,
        "pcode": a.plz.strip(),
        "city": a.ort.strip(),
        "country": "CH",
    }


def qr_rechnung(daten: RechnungsDaten) -> QRBill:
    """QR-Rechnung ohne Referenz (NON), Rechnungsnummer als zusätzliche Information."""
    return QRBill(
        account=daten.iban,
        creditor=_qr_adresse(daten.firma),
        debtor=_qr_adresse(daten.kunde),
        amount=f"{daten.summen.total:.2f}",
        currency="CHF",
        additional_information=f"Rechnung {daten.nummer}",
        language="de",
        top_line=True,
    )


def qr_svg(bill: QRBill) -> str:
    puffer = io.StringIO()
    bill.as_svg(puffer)
    return puffer.getvalue()


def _umgebung() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"])
    )
    env.filters["chf"] = fmt.chf
    env.filters["menge"] = fmt.menge
    env.filters["datum"] = fmt.datum
    return env


def rendere_html(daten: RechnungsDaten, modus: str, svg: str | None = None) -> str:
    svg_uri = None
    if svg is not None:
        svg_uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    zeilen = list(zip(daten.positionen, daten.summen.zeilen))
    return _umgebung().get_template("rechnung_pdf.html").render(
        r=daten, zeilen=zeilen, modus=modus, qr_svg=svg_uri
    )


def erstelle_pdf(daten: RechnungsDaten, ziel: Path | None = None) -> bytes:
    """Erzeugt das PDF. Passt der Inhalt über den Zahlteil, kommt alles auf eine Seite,
    sonst steht der Zahlteil allein auf der letzten Seite."""
    from weasyprint import HTML  # erst hier importieren: braucht Pango

    svg = qr_svg(qr_rechnung(daten))

    probe = HTML(string=rendere_html(daten, "pruefen"), base_url=str(TEMPLATES)).render()
    modus = "eine_seite" if len(probe.pages) == 1 else "mehrseitig"

    pdf = HTML(string=rendere_html(daten, modus, svg), base_url=str(TEMPLATES)).write_pdf()
    if ziel is not None:
        ziel = Path(ziel)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(pdf)
    return pdf

