import logging
import platform
import re
import time
import traceback
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import REPO_ROOT, get_settings
from .db import init_db
from .logging_setup import request_id_var, setup_logging
from .routers import past_papers, patterns, question_sets, source_documents, submissions, system

settings = get_settings()
LOG_FILE = setup_logging(settings.log_level, settings.logs_dir)
logger = logging.getLogger("app.main")

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
# Polled constantly by the UI (live logs, status) — keep them out of the INFO log.
QUIET_PATHS = ("/api/logs", "/api/health")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting %s", settings.app_title)
    logger.info("Python %s on %s", platform.python_version(), platform.platform())
    logger.info("Data folder: %s", settings.data_dir)
    logger.info("Database: %s", settings.resolved_database_url)
    logger.info("Log file: %s (level %s)", LOG_FILE, settings.log_level.upper())
    if settings.effective_mock_mode:
        logger.warning(
            "MOCK MODE: no DEEPSEEK_API_KEY set — AI generation, topic tagging and grading return placeholder data. "
            "Past-paper extraction works fully."
        )
    else:
        logger.info(
            "DeepSeek: %s (text model %s, vision model %s)",
            settings.deepseek_base_url,
            settings.deepseek_text_model,
            settings.deepseek_vision_model,
        )
    init_db()
    logger.info("Database ready")
    yield
    logger.info("Shutting down")


app = FastAPI(title=settings.app_title, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Give every request an id (the browser may supply one so it can follow its own live log), time it, and
    turn any unhandled exception into a JSON error that names its type and carries the traceback."""
    supplied = request.headers.get("x-request-id", "")
    request_id = supplied if REQUEST_ID_RE.match(supplied) else uuid.uuid4().hex[:10]
    token = request_id_var.set(request_id)
    path = request.url.path
    is_api = path.startswith("/api/")
    level = logging.INFO if is_api and not path.startswith(QUIET_PATHS) else logging.DEBUG
    started = time.perf_counter()
    logger.log(level, "→ %s %s%s", request.method, path, f"?{request.url.query}" if request.url.query else "")
    try:
        response = await call_next(request)
    except Exception as e:  # noqa: BLE001 — last line of defence; logged with full traceback
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.exception("✗ %s %s crashed after %.0f ms: %s: %s", request.method, path, elapsed_ms, type(e).__name__, e)
        response = JSONResponse(
            status_code=500,
            content={
                "detail": f"Unexpected server error: {type(e).__name__}: {e}",
                "error_type": type(e).__name__,
                "request_id": request_id,
                "traceback": traceback.format_exc().splitlines()[-25:],
                "hint": "Open Logs & diagnostics in the app (or data/logs/app.log) and search for this request id.",
            },
        )
    else:
        elapsed_ms = (time.perf_counter() - started) * 1000
        status_level = logging.WARNING if response.status_code >= 400 else level
        logger.log(status_level, "← %s %s %s in %.0f ms", request.method, path, response.status_code, elapsed_ms)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    logger.warning("%s %s → %s: %s", request.method, request.url.path, exc.status_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": request_id_var.get()},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    errors = [{"loc": list(e.get("loc", [])), "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))} for e in exc.errors()]
    logger.warning("%s %s → 422 invalid request: %s", request.method, request.url.path, errors)
    return JSONResponse(status_code=422, content={"detail": errors, "request_id": request_id_var.get()})


app.include_router(source_documents.router)
app.include_router(patterns.router)
app.include_router(question_sets.router)
app.include_router(submissions.router)
app.include_router(past_papers.router)
app.include_router(system.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "mock_mode": settings.effective_mock_mode}


# Serve the no-build-step frontend. Mounted last so it doesn't shadow /api/*.
frontend_dir = REPO_ROOT / "frontend"
app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
