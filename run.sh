#!/usr/bin/env bash
# One-command local start: creates/uses a virtualenv, installs dependencies,
# and starts the app. Open http://localhost:8000 once it says "Uvicorn
# running". Press Ctrl+C to stop.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment (.venv)…"
  python3 -m venv .venv
fi

source .venv/bin/activate
echo "Installing/checking dependencies…"
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  echo "No .env found — copying .env.example. The app will run in mock mode until you add a DEEPSEEK_API_KEY."
  cp .env.example .env
fi

echo "Starting Question Set Studio at http://localhost:8000 ..."
cd backend
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
