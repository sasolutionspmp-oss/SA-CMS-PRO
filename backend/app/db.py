"""Database configuration and session management."""
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import settings


def _create_engine():
    url = settings.database_url
    engine = create_engine(url, future=True)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
    return engine


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def get_session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
