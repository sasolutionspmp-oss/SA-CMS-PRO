from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core import Settings
from app.deps import get_app_settings
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse, summary="API health check")
def read_health(settings: Settings = Depends(get_app_settings)) -> HealthResponse:
    """Report service readiness for load balancers and monitors."""

    return HealthResponse(status="ok", detail=f"Backend ready on port {settings.backend_port}")


@router.get("/", response_model=HealthResponse, include_in_schema=False)
def read_root(settings: Settings = Depends(get_app_settings)) -> HealthResponse:
    """Root endpoint for quick smoke checks."""

    return HealthResponse(status="ok", detail=f"Welcome to {settings.api_title}")
