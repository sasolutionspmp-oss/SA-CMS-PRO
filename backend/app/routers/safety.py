"""Safety router."""
from fastapi import APIRouter

router = APIRouter(prefix="/safety", tags=["safety"])


@router.get("/")
def safety() -> dict:
    return {"incidents": 0}
