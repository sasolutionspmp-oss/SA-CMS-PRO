from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core import Settings, get_settings
from app.db.session import SessionLocal
from app.models import User
from app.utils.security import get_bearer_token


def get_db() -> Generator[Session, None, None]:
    """Provide a transactional SQLAlchemy session."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    authorization: str | None = Header(default=None, convert_underscores=False),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from a bearer token."""

    token = get_bearer_token(authorization)
    user = (
        db.query(User)
        .filter(User.token == token)
        .filter(User.is_active.is_(True))
        .first()
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_app_settings() -> Settings:
    """Expose cached application settings for dependency injection."""

    return get_settings()


__all__ = ["get_db", "get_current_user", "get_app_settings"]
