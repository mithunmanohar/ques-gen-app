#!/usr/bin/env bash
# Start Question Set Studio on macOS / Linux.
#   ./run.sh               set up (first run) and start; opens your browser
#   ./run.sh --debug       same, with very detailed logs
#   ./run.sh --help        all options
# All the real work happens in start.py; this script just finds a suitable Python.
cd "$(dirname "$0")" || exit 1

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if ! PYTHON="$(find_python)"; then
  echo "----------------------------------------------------------------"
  echo "  PROBLEM: Python 3.10 or newer was not found on this computer."
  echo ""
  case "$(uname -s)" in
    Darwin) echo "  (The python3 built into macOS is version 3.9, which is too old.)"
            echo "  Install a current Python from https://www.python.org/downloads/ (or: brew install python)," ;;
    *)      echo "  Install it with your package manager, e.g.:  sudo apt install python3 python3-venv" ;;
  esac
  echo "  then run this script again."
  echo "----------------------------------------------------------------"
  exit 1
fi

exec "$PYTHON" start.py "$@"
