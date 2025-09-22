from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR_ENV = "SA_CMS_DATA_DIR"
_DEFAULT_DATA_DIR = _PROJECT_ROOT
_data_dir_override = os.environ.get(_DATA_DIR_ENV)
if _data_dir_override:
    _DEFAULT_DATA_DIR = Path(_data_dir_override).expanduser().resolve()
_DEFAULT_DB_PATH = (_DEFAULT_DATA_DIR / "sa_cms_dev.db").resolve()


class Settings(BaseSettings):
    """Application configuration sourced from environment variables."""

    api_title: str = "SA CMS Pro API"
    api_version: str = "0.1.0"
    backend_port: int = 8000
    frontend_dev_url: str = "http://localhost:5173"
    database_url: str = Field(
        default=f"sqlite:///{_DEFAULT_DB_PATH.as_posix()}",
        alias="DATABASE_URL",
        description="SQLAlchemy connection string",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def model_post_init(self, __context: Any) -> None:  # noqa: D401 - BaseSettings hook
        object.__setattr__(self, "database_url", self._resolve_database_url(self.database_url))

    def _resolve_database_url(self, url: str) -> str:
        if not url.lower().startswith("sqlite"):
            return url
        prefix = "sqlite:///"
        raw_path = url[len(prefix) :]
        if url.startswith("sqlite:////"):
            raw_path = url.replace("sqlite:////", "/", 1)
        path = Path(raw_path)
        if not path.is_absolute():
            path = (_DEFAULT_DATA_DIR / path).resolve()
        return f"sqlite:///{path.as_posix()}"

    @property
    def sqlite_path(self) -> Path:
        """Return the resolved SQLite file path if using SQLite."""

        if not self.database_url.lower().startswith("sqlite"):
            return _DEFAULT_DB_PATH
        prefix = "sqlite:///"
        raw_path = self.database_url[len(prefix) :]
        return Path(raw_path)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()


__all__ = ["Settings", "get_settings"]
