from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HealthResponse(BaseModel):
    """Response payload returned by the root health endpoint."""

    status: str = Field(examples=["ok"])
    detail: str = Field(default="Ready")
    timestamp: datetime = Field(default_factory=_utcnow)


class RegionsResponse(BaseModel):
    """List of configured estimating regions."""

    regions: List[str]
    updated_at: datetime = Field(default_factory=_utcnow)
