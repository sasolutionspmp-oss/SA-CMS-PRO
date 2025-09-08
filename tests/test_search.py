import os
import sys
from fastapi.testclient import TestClient

# Ensure root path for importing
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app

client = TestClient(app)


def test_keyword_search_order():
    res = client.get("/api/search/keyword", params={"q": "cat", "k": 3})
    data = res.json()["results"]
    assert data[0]["file"] == "doc2.txt"
    assert data[1]["file"] == "doc1.txt"


def test_semantic_search_threshold():
    res = client.post("/api/search/semantic", json={"query": "cat", "k": 2, "threshold": 0.1})
    data = res.json()["results"]
    assert any(d["file"] == "doc1.txt" for d in data)
    res2 = client.post("/api/search/semantic", json={"query": "bird", "k": 2, "threshold": 0.1})
    data2 = res2.json()["results"]
    assert data2 == []
