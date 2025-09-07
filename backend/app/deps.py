"""Common dependencies for FastAPI routers."""
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from .db import get_session
from .models import User
from .utils.security import get_bearer_token


def get_db() -> Session:
    with get_session() as session:
        yield session


def get_current_user(
    db: Session = Depends(get_db), token: str = Depends(get_bearer_token)
) -> User:
    user = db.query(User).filter(User.token == token).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user
