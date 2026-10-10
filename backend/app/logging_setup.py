"""
Logging for the whole app.

- Every log line carries the request id of the HTTP request that produced it,
  so one upload/generation/grading can be followed end to end.
- Lines go to the console (where run.sh / run.bat is running) and to a
  rotating file, data/logs/app.log, which the Logs page in the UI reads.
- capture_operation_log() also collects the lines of a single operation
  (e.g. one past-paper import) so they can be stored with the record and
  shown next to it in the UI.

LOG_LEVEL=DEBUG in .env (or `run.sh --debug`) turns on the most detailed output.
"""
import logging
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILE_NAME = "app.log"
# Parses LOG_FORMAT lines back into fields for the Logs page.
LOG_LINE_RE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (?P<level>[A-Z]+)\s+\[(?P<request_id>[^\]]*)\] "
    r"(?P<logger>[^:]+): (?P<message>.*)$"
)
_CONFIGURED_MARKER = "_qgs_configured"


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging(level: str, logs_dir: Path) -> Path:
    """Configure console + file logging once; safe to call again (e.g. on reload or in tests)."""
    log_file = logs_dir / LOG_FILE_NAME
    root = logging.getLogger()
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    if getattr(root, _CONFIGURED_MARKER, None) == str(log_file):
        root.setLevel(numeric_level)
        return log_file

    logs_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    request_filter = RequestIdFilter()

    console = logging.StreamHandler()
    file_handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    for handler in (console, file_handler):
        handler.setFormatter(formatter)
        handler.addFilter(request_filter)

    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(console)
    root.addHandler(file_handler)
    root.setLevel(numeric_level)
    # Third-party chatter stays at WARNING unless something is wrong.
    for noisy in ("httpx", "httpcore", "openai", "multipart", "PIL", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    setattr(root, _CONFIGURED_MARKER, str(log_file))
    return log_file


class _OperationHandler(logging.Handler):
    def __init__(self, request_id: str, lines: list[str]):
        super().__init__(level=logging.DEBUG)
        self.request_id = request_id
        self.lines = lines
        self.started = time.monotonic()

    def emit(self, record: logging.LogRecord) -> None:
        if request_id_var.get() != self.request_id or not record.name.startswith("app"):
            return
        elapsed = time.monotonic() - self.started
        line = f"+{elapsed:6.2f}s {record.levelname:<7} {record.getMessage()}"
        if record.exc_info:
            line += "\n" + logging.Formatter().formatException(record.exc_info)
        self.lines.append(line)


@contextmanager
def capture_operation_log(min_level: int = logging.INFO):
    """Collect this request's app log lines (INFO and up by default) into a list while the block runs."""
    lines: list[str] = []
    handler = _OperationHandler(request_id_var.get(), lines)
    handler.setLevel(min_level)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield lines
    finally:
        root.removeHandler(handler)


def read_log_entries(log_file: Path, *, limit: int, min_level: str = "DEBUG", request_id: str = "", query: str = "") -> list[dict]:
    """The newest `limit` entries of the log file (oldest first), with tracebacks folded into their entry."""
    if not log_file.is_file():
        return []
    with log_file.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 4_000_000))
        text = f.read().decode("utf-8", errors="replace")

    entries: list[dict] = []
    for raw in text.splitlines():
        m = LOG_LINE_RE.match(raw)
        if m:
            entries.append(m.groupdict())
        elif entries:
            entries[-1]["message"] += "\n" + raw  # traceback / multi-line continuation

    threshold = logging.getLevelName(min_level.upper()) if isinstance(logging.getLevelName(min_level.upper()), int) else 0
    q = query.lower().strip()
    out = [
        e
        for e in entries
        if logging.getLevelName(e["level"]) >= threshold
        and (not request_id or e["request_id"] == request_id)
        and (not q or q in e["message"].lower() or q in e["logger"].lower())
    ]
    return out[-limit:]
