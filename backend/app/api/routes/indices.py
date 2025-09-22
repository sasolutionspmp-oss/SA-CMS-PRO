from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.models import User
from app.schemas import RegionsResponse

router = APIRouter(prefix="/indices", tags=["indices"])


@router.get("/regions", response_model=RegionsResponse, summary="Return available estimating regions")
def read_regions(current_user: User = Depends(get_current_user)) -> RegionsResponse:
    """Return a curated list of estimating regions for drop-downs."""

    regions = [
        "us-northeast",
        "us-southeast",
        "us-midwest",
        "us-southwest",
        "us-westcoast",
    ]
    return RegionsResponse(regions=regions)
