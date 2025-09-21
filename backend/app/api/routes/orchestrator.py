from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.models import User
from app.schemas import OrchestratorResponse, UserPublic

router = APIRouter(tags=["orchestrator"])


@router.get(
    "/orchestrator",
    response_model=OrchestratorResponse,
    summary="Return orchestrator dashboard readiness information",
)
def read_orchestrator(current_user: User = Depends(get_current_user)) -> OrchestratorResponse:
    """Return a simple readiness payload for the orchestrator workspace."""

    user_payload = UserPublic.model_validate(current_user)
    return OrchestratorResponse(
        status="ok",
        message="Workflow engine is ready",
        user=user_payload,
        active_jobs=[],
    )
