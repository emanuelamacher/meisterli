#!/usr/bin/env bash
# Startet den Meisterli-Piloten auf http://127.0.0.1:8000
#   ./run.sh        App starten
#   ./run.sh test   Tests laufen lassen
set -euo pipefail
cd "$(dirname "$0")"

HOST=127.0.0.1
PORT="${MEISTERLI_PORT:-8000}"

# WeasyPrint findet Pango auf macOS nur über den Homebrew-Pfad.
if [[ "$(uname)" == "Darwin" ]] && command -v brew >/dev/null; then
  export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib:${DYLD_FALLBACK_LIBRARY_PATH:-}"
fi

if command -v uv >/dev/null; then
  uv sync --quiet
  PY=(uv run --quiet)
else
  if [[ ! -x .venv/bin/python ]]; then
    command -v python3.12 >/dev/null || { echo "Python 3.12 oder uv fehlt (brew install uv)."; exit 1; }
    python3.12 -m venv .venv
    .venv/bin/pip install --quiet -r requirements.txt
  fi
  PY=(.venv/bin/python -m)
fi

if [[ "${1:-}" == "test" ]]; then
  shift
  exec "${PY[@]}" pytest "$@"
fi

command -v ffmpeg >/dev/null || echo "Hinweis: ffmpeg fehlt – Audio geht erst nach 'brew install ffmpeg'. Das Textfeld funktioniert."
curl -s --max-time 2 "${MEISTERLI_OLLAMA_URL:-http://localhost:11434}/api/tags" >/dev/null \
  || echo "Hinweis: Ollama antwortet nicht – bitte die Ollama-App starten."

echo "Meisterli-Pilot läuft auf http://$HOST:$PORT (beenden mit Ctrl+C)"
exec "${PY[@]}" uvicorn --factory app.main:create_app --host "$HOST" --port "$PORT"
