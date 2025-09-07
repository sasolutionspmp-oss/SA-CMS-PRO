"""Project management router."""
from fastapi import APIRouter

router = APIRouter(prefix="/pm", tags=["pm"])


@router.get("/")
def pm_status() -> dict:
    return {"projects": []}
