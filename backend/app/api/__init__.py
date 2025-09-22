"""API router package."""

from fastapi import APIRouter

from .routes import estimate, health, indices, orchestrator

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(orchestrator.router)
api_router.include_router(estimate.router)
api_router.include_router(indices.router)

__all__ = ["api_router"]
