"""FastAPI application entry point."""
from fastapi import FastAPI

from .routers import (
    ingest,
    search,
    orchestrator,
    estimate,
    compliance,
    pm,
    safety,
    finance,
    history,
    auth,
)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="SA-CMS-Pro")
    for router in [
        auth.router,
        ingest.router,
        search.router,
        orchestrator.router,
        estimate.router,
        compliance.router,
        pm.router,
        safety.router,
        finance.router,
        history.router,
    ]:
        app.include_router(router)
    return app


app = create_app()
