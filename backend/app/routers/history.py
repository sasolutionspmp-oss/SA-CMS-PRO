"""History router."""
from fastapi import APIRouter

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/")
def history() -> dict:
    return {"events": []}
