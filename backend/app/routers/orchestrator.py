"""Simple orchestrator router."""
from fastapi import APIRouter

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


@router.get("/")
def orchestrate() -> dict:
    return {"status": "ok"}
