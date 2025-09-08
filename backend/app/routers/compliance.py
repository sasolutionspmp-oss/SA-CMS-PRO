"""Compliance router."""
from fastapi import APIRouter

router = APIRouter(prefix="/compliance", tags=["compliance"])


@router.get("/")
def compliance() -> dict:
    return {"compliant": True}
