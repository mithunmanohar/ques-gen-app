import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import REPO_ROOT, get_settings
from .db import init_db
from .routers import patterns, question_sets, source_documents, submissions

logging.basicConfig(level=logging.INFO)

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_title, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(source_documents.router)
app.include_router(patterns.router)
app.include_router(question_sets.router)
app.include_router(submissions.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "mock_mode": settings.effective_mock_mode}


# Serve the no-build-step frontend. Mounted last so it doesn't shadow /api/*.
frontend_dir = REPO_ROOT / "frontend"
app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
