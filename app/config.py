"""Konfiguration über Umgebungsvariablen."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("MEISTERLI_DATA", BASE_DIR / "data"))

OLLAMA_URL = os.environ.get("MEISTERLI_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("MEISTERLI_MODEL", "qwen3:8b")
OLLAMA_TIMEOUT = float(os.environ.get("MEISTERLI_OLLAMA_TIMEOUT", "180"))

WHISPER_MODEL = os.environ.get(
    "MEISTERLI_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo"
)
WHISPER_LANGUAGE = os.environ.get("MEISTERLI_WHISPER_LANGUAGE", "de")
