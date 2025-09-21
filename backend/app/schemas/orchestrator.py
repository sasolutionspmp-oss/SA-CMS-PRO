from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from pydantic import BaseModel, Field

from .user import UserPublic


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrchestratorResponse(BaseModel):
    """Response returned by the orchestrator readiness endpoint."""

    status: str = Field(examples=["ok"])
    message: str
    user: UserPublic
    active_jobs: List[str] = Field(default_factory=list)
    refreshed_at: datetime = Field(default_factory=_utcnow)


class EstimateResponse(BaseModel):
    """Response returned by the estimating overview endpoint."""

    status: str = Field(examples=["ok"])
    total_estimates: int
    drafts: int
    submitted: int
    updated_at: datetime = Field(default_factory=_utcnow)
