import sys
from pathlib import Path

import pytest

from app.transkription import MlxWhisper, TranskriptionsFehler


def test_fehlendes_mlx_whisper_gibt_verstaendlichen_fehler(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)  # Import schlägt fehl
    with pytest.raises(TranskriptionsFehler, match="Apple Silicon"):
        MlxWhisper().transkribiere(tmp_path / "x.ogg")


def test_mlx_whisper_aufruf(monkeypatch, tmp_path):
    aufrufe = []

    class Attrappe:
        @staticmethod
        def transcribe(pfad, **kwargs):
            aufrufe.append((pfad, kwargs))
            return {"text": "  Rächnig für Herr Meier  "}

    monkeypatch.setitem(sys.modules, "mlx_whisper", Attrappe)
    monkeypatch.setattr("shutil.which", lambda name: "/opt/homebrew/bin/ffmpeg")
    text = MlxWhisper(modell="test/modell").transkribiere(Path(tmp_path / "a.ogg"))
    assert text == "Rächnig für Herr Meier"
    (pfad, kwargs), = aufrufe
    assert pfad.endswith("a.ogg")
    assert kwargs["path_or_hf_repo"] == "test/modell"
    assert kwargs["language"] == "de"


def test_ffmpeg_fehlt(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "mlx_whisper", object())
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(TranskriptionsFehler, match="brew install ffmpeg"):
        MlxWhisper().transkribiere(tmp_path / "a.ogg")
