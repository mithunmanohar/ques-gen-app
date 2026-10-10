"""Logs and diagnostics, so problems can be investigated from the browser."""
import importlib.metadata
import platform
import shutil
import sys

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models
from ..config import get_settings
from ..db import get_db
from ..logging_setup import LOG_FILE_NAME, read_log_entries

router = APIRouter(prefix="/api", tags=["system"])

PACKAGES = ("fastapi", "uvicorn", "sqlalchemy", "pydantic", "pymupdf", "pypdf", "openai")


def _log_file():
    return get_settings().logs_dir / LOG_FILE_NAME


@router.get("/logs")
def get_logs(
    limit: int = Query(300, ge=1, le=5000),
    level: str = Query("DEBUG", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"),
    request_id: str = "",
    q: str = "",
):
    """Newest log entries (oldest first). Filter by minimum level, request id, or text."""
    return {
        "log_file": str(_log_file()),
        "entries": read_log_entries(_log_file(), limit=limit, min_level=level, request_id=request_id, query=q),
    }


@router.get("/logs/download")
def download_logs():
    path = _log_file()
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return FileResponse(path, media_type="text/plain", filename="question-set-studio.log")


@router.get("/diagnostics")
def diagnostics(db: Session = Depends(get_db)):
    settings = get_settings()
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed"
    disk = shutil.disk_usage(settings.data_dir)
    return {
        "app": settings.app_title,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": versions,
        "mock_mode": settings.effective_mock_mode,
        "deepseek": {
            "api_key_set": bool(settings.deepseek_api_key.strip()),
            "base_url": settings.deepseek_base_url,
            "text_model": settings.deepseek_text_model,
            "vision_model": settings.deepseek_vision_model,
        },
        "log_level": settings.log_level.upper(),
        "log_file": str(_log_file()),
        "data_dir": str(settings.data_dir),
        "database": settings.resolved_database_url,
        "disk_free_gb": round(disk.free / 1e9, 1),
        "counts": {
            "past_papers": db.query(models.PastPaper).count(),
            "bank_questions": db.query(models.BankQuestion).count(),
            "question_sets": db.query(models.QuestionSet).count(),
            "submissions": db.query(models.Submission).count(),
            "patterns": db.query(models.Pattern).count(),
            "source_documents": db.query(models.SourceDocument).count(),
        },
    }
