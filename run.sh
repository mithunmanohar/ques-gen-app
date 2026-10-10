#!/usr/bin/env bash
# Start Question Set Studio on macOS / Linux.
#   ./run.sh               set up (first run) and start; opens your browser
#   ./run.sh --debug       same, with very detailed logs
#   ./run.sh --help        all options
# All the real work happens in start.py; this script just finds a suitable Python.
cd "$(dirname "$0")" || exit 1

MIN_MINOR=10   # Python 3.10+
MAX_MINOR=14   # newest version tested; newer ones are tried after these

# Where Python installers put versioned executables, in case they aren't on PATH
# (python.org installer, Homebrew on Apple Silicon and Intel, pyenv, system).
EXTRA_DIRS="/Library/Frameworks/Python.framework/Versions/Current/bin /opt/homebrew/bin /usr/local/bin $HOME/.pyenv/shims /usr/bin"

python_ok() {
  "$1" -c "import sys; sys.exit(0 if sys.version_info >= (3, $MIN_MINOR) else 1)" >/dev/null 2>&1
}

find_python() {
  local minor name dir
  # Tested versions first (newest first), then anything newer, then plain python3/python.
  local names=""
  for minor in $(seq "$MAX_MINOR" -1 "$MIN_MINOR") $(seq 20 -1 $((MAX_MINOR + 1))); do
    names="$names python3.$minor"
  done
  names="$names python3 python"

  for name in $names; do
    if command -v "$name" >/dev/null 2>&1 && python_ok "$name"; then
      command -v "$name"
      return 0
    fi
    for dir in $EXTRA_DIRS /Library/Frameworks/Python.framework/Versions/3.*/bin; do
      if [ -x "$dir/$name" ] && python_ok "$dir/$name"; then
        echo "$dir/$name"
        return 0
      fi
    done
  done
  return 1
}

if ! PYTHON="$(find_python)"; then
  echo "----------------------------------------------------------------"
  echo "  PROBLEM: Python 3.$MIN_MINOR or newer was not found on this computer."
  echo ""
  case "$(uname -s)" in
    Darwin) echo "  (The python3 built into macOS is version 3.9, which is too old.)"
            echo "  Install a current Python from https://www.python.org/downloads/ (or: brew install python),"
            echo "  then open a NEW Terminal window and run this script again." ;;
    *)      echo "  Install it with your package manager, e.g.:  sudo apt install python3 python3-venv"
            echo "  then run this script again." ;;
  esac
  if command -v python3 >/dev/null 2>&1; then
    echo ""
    echo "  (Found $(python3 --version 2>&1) at $(command -v python3) — too old.)"
  fi
  echo "----------------------------------------------------------------"
  exit 1
fi

echo "Using $("$PYTHON" --version 2>&1) at $PYTHON"
exec "$PYTHON" start.py "$@"
