import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.rechnen import Position

FIXTURES = Path(__file__).parent / "fixtures"
TEST_IBAN = "CH93 0076 2011 6238 5295 7"


def lade_texte() -> list[dict]:
    return json.loads((FIXTURES / "texte.json").read_text(encoding="utf-8"))


def als_positionen(fall: dict) -> list[Position]:
    return [
        Position(
            beschreibung=p["beschreibung"],
            menge=Decimal(p["menge"]),
            einheit=p["einheit"],
            einzelpreis=Decimal(p["einzelpreis"]),
        )
        for p in fall["positionen"]
    ]


@pytest.fixture(params=lade_texte(), ids=lambda f: f["id"])
def fall(request) -> dict:
    return request.param
