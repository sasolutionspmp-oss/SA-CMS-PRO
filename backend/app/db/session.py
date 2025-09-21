from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import get_settings

_settings = get_settings()

_connect_args = {}
if _settings.database_url.lower().startswith("sqlite"):
    sqlite_path = _settings.sqlite_path
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    _settings.database_url,
    connect_args=_connect_args,
    future=True,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


__all__ = ["engine", "SessionLocal"]
