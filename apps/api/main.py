from __future__ import annotations

from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules

from fastapi import FastAPI

from packages.core.database import Base, engine

# Import lane 3 models to register mappings
from apps.api.models import crm  # noqa: F401
from apps.api.models import estimator  # noqa: F401
from apps.api.models import intake  # noqa: F401
from apps.api.routes import account as account_routes
from apps.api.routes import auth as auth_routes
from apps.api.routes import bootstrap as bootstrap_routes
from apps.api.routes import crm as crm_routes
from apps.api.routes import estimator as estimator_routes
from apps.api.routes import export as export_routes
from apps.api.routes import health as health_routes
from apps.api.routes import intake as intake_routes
from apps.api.routes import jobs as jobs_routes
from apps.api.routes import orgs as orgs_routes
from apps.api.routes import workflows as workflows_routes

OPENAPI_TAGS = [
    {"name": "health", "description": "Platform service health and dependency diagnostics."},
    {"name": "auth", "description": "Authentication, refresh, and account session helpers."},
    {"name": "account", "description": "Profile lookups, organization switching, and user preferences."},
    {"name": "orgs", "description": "Organization roster management and membership utilities."},
    {"name": "bootstrap", "description": "Composite bootstrap payloads for first-load UX hydration."},
    {"name": "intake", "description": "File ingestion status, runs, and document lifecycle endpoints."},
    {"name": "jobs", "description": "Long-running workflow submission and polling APIs."},
    {"name": "crm", "description": "Opportunity pipeline, Kanban operations, and audit telemetry."},
    {"name": "estimator", "description": "Estimating grids, cost curves, and export orchestration."},
    {"name": "export", "description": "Bid package export download streams and artifact metadata."},
    {"name": "workflows", "description": "Composite copilot-driven workflow orchestration endpoints."},
]


def _include_feature_modules(app: FastAPI) -> None:
    modules_path = Path(__file__).resolve().parent / "modules"
    if not modules_path.exists():
        return
    prefix = "apps.api.modules."
    for module in iter_modules([str(modules_path)], prefix):
        mod = import_module(module.name)
        router = getattr(mod, "router", None)
        if router is not None:
            app.include_router(router)


def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine)
    app = FastAPI(
        title="SA-CMS Pro API",
        description="Operator and copilot APIs for the S&A control center.",
        version="0.1.0",
        openapi_tags=OPENAPI_TAGS,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    for router in (
        health_routes.router,
        auth_routes.router,
        account_routes.router,
        orgs_routes.router,
        bootstrap_routes.router,
        intake_routes.router,
        jobs_routes.router,
        crm_routes.router,
        estimator_routes.router,
        export_routes.router,
        workflows_routes.router,
    ):
        app.include_router(router)
    _include_feature_modules(app)
    return app


app = create_app()
