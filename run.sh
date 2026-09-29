#!/usr/bin/env bash
# Startet den Meisterli-Piloten auf http://127.0.0.1:8000
#   ./run.sh        App starten
#   ./run.sh test   Tests laufen lassen
#   ./run.sh probe  rohe Antworten des Sprachmodells für die Testtexte anzeigen
#   ./run.sh https  Demo im lokalen Netz über HTTPS (fürs Handy, braucht Zertifikate in data/certs/)
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
  PYTHON=(uv run --quiet python)
else
  if [[ ! -x .venv/bin/python ]]; then
    command -v python3.12 >/dev/null || { echo "Python 3.12 oder uv fehlt (brew install uv)."; exit 1; }
    python3.12 -m venv .venv
    .venv/bin/pip install --quiet -r requirements.txt
  fi
  PY=(.venv/bin/python -m)
  PYTHON=(.venv/bin/python)
fi

if [[ "${1:-}" == "probe" ]]; then
  exec "${PYTHON[@]}" -m app.probe
fi

if [[ "${1:-}" == "test" ]]; then
  shift
  exec "${PY[@]}" pytest "$@"
fi

command -v ffmpeg >/dev/null || echo "Hinweis: ffmpeg fehlt – Audio geht erst nach 'brew install ffmpeg'. Das Textfeld funktioniert."
curl -s --max-time 2 "${MEISTERLI_OLLAMA_URL:-http://localhost:11434}/api/tags" >/dev/null \
  || echo "Hinweis: Ollama antwortet nicht – starte es mit «brew services start ollama»."

if [[ "${1:-}" == "https" ]]; then
  CERT=data/certs/cert.pem
  KEY=data/certs/key.pem
  if [[ ! -f "$CERT" || ! -f "$KEY" ]]; then
    cat <<HILFE
Für HTTPS fehlen die Zertifikate. Einmalig (siehe README, Abschnitt «Demo auf dem Handy»):
  brew install mkcert
  mkcert -install
  mkdir -p data/certs
  mkcert -cert-file $CERT -key-file $KEY localhost 127.0.0.1 \$(ipconfig getifaddr en0) \$(scutil --get LocalHostName).local
HILFE
    exit 1
  fi
  IP="$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
  echo "Achtung: Die App ist jetzt im ganzen lokalen Netz erreichbar."
  echo "Auf dem Handy (gleiches WLAN): https://${IP:-<IP-Adresse>}:$PORT/chat"
  exec "${PY[@]}" uvicorn --factory app.main:create_app --host 0.0.0.0 --port "$PORT" \
    --ssl-certfile "$CERT" --ssl-keyfile "$KEY"
fi

echo "Meisterli läuft auf http://$HOST:$PORT – Chat: http://$HOST:$PORT/chat (beenden mit Ctrl+C)"
exec "${PY[@]}" uvicorn --factory app.main:create_app --host "$HOST" --port "$PORT"
