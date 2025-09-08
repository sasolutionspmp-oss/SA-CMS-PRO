"""Finance router."""
from fastapi import APIRouter

router = APIRouter(prefix="/finance", tags=["finance"])


@router.get("/")
def finance_status() -> dict:
    return {"balance": 0.0}
