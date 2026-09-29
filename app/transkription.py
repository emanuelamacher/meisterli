"""Transkription hinter einer kleinen Schnittstelle.

Ein anderes Modell (z. B. ein Schweizerdeutsch-Whisper) braucht nur eine Klasse
mit `name` und `transkribiere(pfad) -> str`.
"""

import shutil
from pathlib import Path
from typing import Protocol

from . import config

AUDIO_ENDUNGEN = {".ogg", ".opus", ".m4a", ".mp3", ".wav", ".webm", ".mp4", ".aac", ".flac"}

# Hilft Whisper bei Fachwörtern und Schreibweise, ohne den Inhalt vorzugeben.
STANDARD_PROMPT = "Rechnung für Familie Keller: 3 Stunden à 90 Franken, Anfahrt pauschal 45."


class TranskriptionsFehler(Exception):
    """Verständliche Fehlermeldung für die Oberfläche."""


class Transkribierer(Protocol):
    name: str

    def transkribiere(self, audio: Path) -> str: ...


class MlxWhisper:
    """Whisper auf Apple Silicon über mlx-whisper."""

    def __init__(
        self,
        modell: str = config.WHISPER_MODEL,
        sprache: str = config.WHISPER_LANGUAGE,
        initial_prompt: str | None = STANDARD_PROMPT,
    ):
        self.modell = modell
        self.sprache = sprache
        self.initial_prompt = initial_prompt
        self.name = f"mlx-whisper ({modell})"

    def transkribiere(self, audio: Path) -> str:
        try:
            import mlx_whisper
        except ImportError as e:
            raise TranskriptionsFehler(
                "mlx-whisper ist nicht installiert (läuft nur auf Macs mit Apple Silicon)."
            ) from e
        if shutil.which("ffmpeg") is None:
            raise TranskriptionsFehler("ffmpeg fehlt. Bitte `brew install ffmpeg` ausführen.")
        try:
            ergebnis = mlx_whisper.transcribe(
                str(audio),
                path_or_hf_repo=self.modell,
                language=self.sprache,
                initial_prompt=self.initial_prompt,
                condition_on_previous_text=False,
            )
        except Exception as e:  # ffmpeg- oder Modellfehler
            raise TranskriptionsFehler(f"Transkription fehlgeschlagen: {e}") from e
        return (ergebnis.get("text") or "").strip()


def standard_transkribierer() -> Transkribierer:
    return MlxWhisper()
