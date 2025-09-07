"""Security helpers."""
from fastapi import Header, HTTPException, status

from ..config import settings


def get_bearer_token(authorization: str = Header(...)) -> str:
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Bad auth header")
    token = authorization[len(prefix) :]
    if token != settings.local_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return token


def create_token(username: str) -> str:
    return settings.local_token
