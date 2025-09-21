from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401 - ensure models are imported for alembic discovery
from app.api import api_router
from app.core import get_settings

settings = get_settings()

app = FastAPI(title=settings.api_title, version=settings.api_version)

allowed_origins = {
    settings.frontend_dev_url,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


__all__ = ["app"]
