@echo off
REM One-command local start on Windows: creates/uses a virtualenv, installs
REM dependencies, and starts the app. Open http://localhost:8000 once it
REM says "Uvicorn running". Press Ctrl+C to stop.

cd /d "%~dp0"

if not exist ".venv" (
  echo Creating virtual environment .venv ...
  python -m venv .venv
)

call .venv\Scripts\activate.bat
echo Installing/checking dependencies...
pip install -q -r requirements.txt

if not exist ".env" (
  echo No .env found - copying .env.example. The app will run in mock mode until you add a DEEPSEEK_API_KEY.
  copy .env.example .env
)

echo Starting Question Set Studio at http://localhost:8000 ...
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
