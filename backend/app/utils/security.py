from __future__ import annotations

from fastapi import HTTPException, status


def get_bearer_token(authorization: str | None) -> str:
    """Extract a bearer token from the provided Authorization header."""

    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization scheme",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token.strip()


__all__ = ["get_bearer_token"]
