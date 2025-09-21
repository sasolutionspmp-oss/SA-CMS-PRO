from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.models import User
from app.schemas import EstimateResponse

router = APIRouter(tags=["estimate"])


@router.get(
    "/estimate",
    response_model=EstimateResponse,
    summary="Return aggregate estimate dashboard statistics",
)
def read_estimate(current_user: User = Depends(get_current_user)) -> EstimateResponse:
    """Return a stubbed estimate summary for the shell UI."""

    # Placeholder data for the dev bootstrap; real implementation will pull from the database.
    total = 3
    drafts = 1
    submitted = total - drafts
    return EstimateResponse(status="ok", total_estimates=total, drafts=drafts, submitted=submitted)
