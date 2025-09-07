from fastapi import FastAPI, Query
from pydantic import BaseModel
from typing import Dict, Any

from .db import keyword_search, semantic_search

app = FastAPI()


@app.get("/api/search/keyword")
def search_keyword(q: str, k: int = 10, offset: int = 0, filters: Dict[str, Any] | None = None):
    results = keyword_search(q, k, offset)
    return {"results": results}


class SemanticRequest(BaseModel):
    query: str
    k: int = 10
    filters: Dict[str, Any] | None = None
    threshold: float = 0.3


@app.post("/api/search/semantic")
def search_semantic(req: SemanticRequest):
    results = semantic_search(req.query, req.k, req.threshold)
    return {"results": results}
