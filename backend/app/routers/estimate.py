"""Estimate router."""
from fastapi import APIRouter

router = APIRouter(prefix="/estimate", tags=["estimate"])


@router.get("/")
def estimate() -> dict:
    return {"estimate": 42}
