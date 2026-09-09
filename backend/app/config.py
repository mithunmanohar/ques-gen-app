"""
Central application settings.

Everything here is overridable via environment variables (or a local .env
file — see .env.example at the repo root). Nothing in this file needs to
change for normal use; it's the knobs, not the logic.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two levels up from this file (backend/app/config.py -> repo root)
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Storage -----------------------------------------------------
    data_dir: Path = REPO_ROOT / "data"
    database_url: str = ""  # computed from data_dir if left blank

    # --- DeepSeek ------------------------------------------------------
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    # Text model used for question-set generation.
    deepseek_text_model: str = "deepseek-chat"
    # Vision-capable model used to read + grade photographed answer sheets.
    # DeepSeek's vision offering has changed names before — if grading
    # requests start failing with a "model not found" style error, check
    # DeepSeek's current API docs and update this value in .env.
    deepseek_vision_model: str = "deepseek-vl2"

    # If true (or no API key is configured), generation/evaluation calls
    # return realistic canned data instead of calling out to DeepSeek.
    # This lets the whole app be exercised end-to-end with zero setup.
    mock_mode: bool = False

    # --- Misc ------------------------------------------------------
    app_title: str = "Question Set Studio"
    cors_allow_origins: list[str] = ["*"]

    @property
    def effective_mock_mode(self) -> bool:
        return self.mock_mode or not self.deepseek_api_key.strip()

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def source_documents_dir(self) -> Path:
        return self.uploads_dir / "source_documents"

    @property
    def submissions_dir(self) -> Path:
        return self.uploads_dir / "submissions"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'app.db'}"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.uploads_dir, self.source_documents_dir, self.submissions_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
