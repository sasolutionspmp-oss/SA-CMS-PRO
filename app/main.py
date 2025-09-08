from fastapi import FastAPI

from app.api import orchestrator, estimate, indices

app = FastAPI()
app.include_router(orchestrator.router)
app.include_router(estimate.router)
app.include_router(indices.router)
