#!/usr/bin/env python3
"""
Question Set Studio launcher — sets everything up and starts the app.

Normally you don't run this directly: double-click / run one of
  run.bat                              (Windows)
  Start Question Set Studio.command    (macOS)
  ./run.sh                             (macOS / Linux terminal)
which find a suitable Python and then run this file.

What it does, each time:
  1. checks the Python version
  2. creates a private Python environment in .venv (first run only)
  3. installs the required packages (first run, or when requirements.txt changes)
  4. creates the .env settings file and offers to store your DeepSeek API key
  5. picks a free port, starts the app and opens it in your browser

Options:
  --port N        use port N (default 8000, or the next free one)
  --debug         very detailed logs (LOG_LEVEL=DEBUG)
  --no-browser    don't open the browser automatically
  --reinstall     reinstall all packages (fixes a broken install)
  --setup-only    do steps 1-4 and stop, without starting the app
  --dev           auto-restart when code changes (for developers)

Uses only the Python standard library, so it works before anything is installed.
"""
import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
LOG_DIR = ROOT / "data" / "logs"
SETUP_LOG = LOG_DIR / "setup.log"
APP_LOG = LOG_DIR / "app.log"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV / ".requirements.sha256"
MIN_PYTHON = (3, 10)
TOTAL_STEPS = 5
IMPORT_CHECK = "import fastapi, uvicorn, sqlalchemy, pydantic_settings, pymupdf, pypdf, openai"

# Windows consoles may not be UTF-8; never crash on a character we print.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


# ---------------------------------------------------------------- output


def banner() -> None:
    print("=" * 64)
    print("  Question Set Studio")
    print("=" * 64, flush=True)


def step(n: int, title: str) -> None:
    print(f"\n[{n}/{TOTAL_STEPS}] {title}", flush=True)


def ok(msg: str) -> None:
    print(f"      OK  {msg}", flush=True)


def info(msg: str) -> None:
    print(f"          {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"    WARN  {msg}", flush=True)


def fail(msg: str, hints: list[str] | None = None, show_log: Path | None = None) -> None:
    print("\n" + "-" * 64)
    print(f"  PROBLEM: {msg}")
    for hint in hints or []:
        print(f"    - {hint}")
    if show_log and show_log.is_file():
        tail = show_log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
        print(f"\n  Last lines of {show_log}:")
        for line in tail:
            print(f"    | {line}")
    print(f"\n  Setup details are logged in: {SETUP_LOG}")
    print(f"  App logs are in:             {APP_LOG}")
    print("-" * 64, flush=True)
    sys.exit(1)


def log_setup(text: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with SETUP_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")


def run_logged(cmd: list[str], what: str, *, cwd: Path = ROOT) -> int:
    """Run a command with its output going to setup.log, printing a heartbeat so it never looks frozen."""
    log_setup(f"$ {' '.join(map(str, cmd))}")
    started = time.monotonic()
    done = threading.Event()

    def heartbeat() -> None:
        while not done.wait(10):
            info(f"... still {what} ({int(time.monotonic() - started)}s so far)")

    threading.Thread(target=heartbeat, daemon=True).start()
    with SETUP_LOG.open("a", encoding="utf-8") as f:
        code = subprocess.call(list(map(str, cmd)), cwd=cwd, stdout=f, stderr=subprocess.STDOUT)
    done.set()
    log_setup(f"exit code {code} after {time.monotonic() - started:.0f}s")
    return code


# ---------------------------------------------------------------- steps


def check_python() -> None:
    step(1, "Checking Python")
    version = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info < MIN_PYTHON:
        fail(
            f"Python {version} is too old; version {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is needed.",
            ["Install the latest Python from https://www.python.org/downloads/ and run this again."],
        )
    ok(f"Python {version} ({sys.executable})")
    log_setup(f"launcher started with Python {version} at {sys.executable} on {sys.platform}")


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_works() -> bool:
    py = venv_python()
    return py.is_file() and subprocess.call([str(py), "-c", "import sys"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def ensure_venv() -> Path:
    step(2, "Preparing the app's private Python environment (.venv)")
    if venv_works():
        ok(f"Using existing environment in {VENV}")
        return venv_python()
    if VENV.exists():
        warn("The existing .venv folder is broken (Python moved or upgraded?) — rebuilding it.")
        shutil.rmtree(VENV, ignore_errors=True)
    info("Creating it now (first run only)...")
    if run_logged([sys.executable, "-m", "venv", str(VENV)], "creating the environment") != 0 or not venv_works():
        hints = ["Make sure the folder isn't read-only and there is free disk space."]
        if sys.platform.startswith("linux"):
            hints.insert(0, "On Ubuntu/Debian install the venv module first:  sudo apt install python3-venv")
        fail("Could not create the Python environment.", hints, SETUP_LOG)
    ok(f"Created {VENV}")
    return venv_python()


def requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def ensure_packages(py: Path, force: bool) -> None:
    step(3, "Installing the required packages")
    wanted = requirements_hash()
    if not force and STAMP.is_file() and STAMP.read_text().strip() == wanted:
        if subprocess.call([str(py), "-c", IMPORT_CHECK], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
            ok("Already installed and up to date")
            return
        warn("Packages look incomplete — reinstalling.")
    info("Downloading and installing (the first time takes 1-3 minutes; needs internet)...")
    run_logged([py, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"], "updating pip")
    code = run_logged(
        [py, "-m", "pip", "install", "--disable-pip-version-check", "-r", REQUIREMENTS], "installing packages"
    )
    if code != 0:
        fail(
            "Installing the packages failed.",
            [
                "Check your internet connection (and proxy settings, if you're on a school/office network).",
                "If the log mentions 'pymupdf' or building a wheel, your Python may be too new for it: "
                "install Python 3.12 from python.org and run again.",
                "Then run again with --reinstall.",
            ],
            SETUP_LOG,
        )
    check = subprocess.run([str(py), "-c", IMPORT_CHECK], capture_output=True, text=True)
    if check.returncode != 0:
        log_setup(f"import check failed:\n{check.stderr}")
        fail("Packages installed but can't be loaded.", ["Run again with --reinstall."], SETUP_LOG)
    STAMP.write_text(wanted)
    ok("All packages installed")


def read_env_value(key: str) -> str:
    if not ENV_FILE.is_file():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def write_env_value(key: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_env() -> None:
    step(4, "Checking settings (.env)")
    created = False
    if not ENV_FILE.is_file():
        shutil.copy(ENV_EXAMPLE, ENV_FILE)
        created = True
        ok(f"Created {ENV_FILE.name} from {ENV_EXAMPLE.name}")
    if not read_env_value("DEEPSEEK_API_KEY") and created and sys.stdin and sys.stdin.isatty():
        print(
            "\n      The app uses DeepSeek (an AI service) to write new questions, tag topics and grade\n"
            "      answer sheets. Past-paper extraction works without it.\n"
            "      Paste your DeepSeek API key and press Enter, or just press Enter to try the app in\n"
            "      demo mode first (you can add the key to the .env file any time later).\n"
        )
        try:
            key = input("      DeepSeek API key: ").strip()
        except EOFError:
            key = ""
        if key:
            write_env_value("DEEPSEEK_API_KEY", key)
            ok("Key saved to .env")
    if read_env_value("DEEPSEEK_API_KEY"):
        ok("DeepSeek API key found — AI features are on")
    else:
        warn("No DeepSeek API key — running in demo (mock) mode. Add DEEPSEEK_API_KEY=... to .env to enable AI.")


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def app_running_at(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            return json.load(r).get("status") == "ok"
    except Exception:  # noqa: BLE001 — anything else on that port isn't us
        return False


def lan_address() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def choose_port(preferred: int, open_browser: bool) -> int:
    if port_free(preferred):
        return preferred
    if app_running_at(preferred):
        url = f"http://localhost:{preferred}"
        print(f"\n  Question Set Studio is already running at {url}")
        if open_browser:
            webbrowser.open(url)
        print("  (Close the other window to stop it.)")
        sys.exit(0)
    for port in range(preferred + 1, preferred + 50):
        if port_free(port):
            warn(f"Port {preferred} is used by another program — using port {port} instead.")
            return port
    fail(f"No free port found between {preferred} and {preferred + 49}.", ["Start with --port 9000 (or another number)."])
    return preferred


def wait_until_ready(proc: subprocess.Popen, port: int, open_browser: bool) -> None:
    url = f"http://localhost:{port}"
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return  # the main thread reports the exit
        if app_running_at(port):
            print("\n" + "=" * 64)
            print(f"  READY:  {url}")
            lan = lan_address()
            if lan:
                print(f"  Other devices on your Wi-Fi (e.g. a phone for answer-sheet photos): http://{lan}:{port}")
            print("  Keep this window open while using the app. Press Ctrl+C here to stop it.")
            print(f"  Logs: {APP_LOG}  (also under 'Logs & diagnostics' in the app)")
            print("=" * 64 + "\n", flush=True)
            if open_browser:
                webbrowser.open(url)
            return
        time.sleep(0.5)
    warn(f"The app hasn't answered at {url} after 90 seconds. Check the messages above and {APP_LOG}.")


def run_app(py: Path, port: int, args: argparse.Namespace) -> int:
    step(5, f"Starting the app on port {port}")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    if args.debug:
        env["LOG_LEVEL"] = "DEBUG"
        info("Debug logging is on (LOG_LEVEL=DEBUG)")
    cmd = [str(py), "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(port)]
    if args.dev:
        cmd.append("--reload")
    log_setup(f"starting app: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=ROOT / "backend", env=env)
    threading.Thread(target=wait_until_ready, args=(proc, port, not args.no_browser), daemon=True).start()
    try:
        code = proc.wait()
    except KeyboardInterrupt:
        print("\n  Stopping...", flush=True)
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("  Stopped. You can close this window.")
        return 0
    if code != 0:
        fail(
            f"The app stopped unexpectedly (exit code {code}).",
            [
                "The messages just above usually say why.",
                f"Full details: {APP_LOG}",
                "If it mentions a missing module, run again with --reinstall.",
            ],
        )
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up and start Question Set Studio.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--debug", action="store_true", help="very detailed logs")
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser")
    parser.add_argument("--reinstall", action="store_true", help="reinstall all packages")
    parser.add_argument("--setup-only", action="store_true", help="set up, but don't start the app")
    parser.add_argument("--dev", action="store_true", help="auto-restart on code changes")
    args = parser.parse_args()

    banner()
    check_python()
    py = ensure_venv()
    ensure_packages(py, args.reinstall)
    ensure_env()
    if args.setup_only:
        print("\n  Setup complete. Start the app with run.bat / run.sh (without --setup-only).")
        return 0
    port = choose_port(args.port, not args.no_browser)
    return run_app(py, port, args)


if __name__ == "__main__":
    sys.exit(main())
