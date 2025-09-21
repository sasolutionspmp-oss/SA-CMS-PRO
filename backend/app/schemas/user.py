from __future__ import annotations

from pydantic import BaseModel, Field


class UserPublic(BaseModel):
    """Public user projection returned by API endpoints."""

    id: int = Field(..., ge=1)
    email: str
    full_name: str | None = None
    role: str = "admin"
    is_active: bool = True

    class Config:
        from_attributes = True
