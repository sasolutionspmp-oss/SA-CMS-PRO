import os
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

if os.path.exists("test.db"):
    os.remove("test.db")
os.environ["DATABASE_URL"] = "sqlite:///./test.db"

from fastapi.testclient import TestClient
from app.main import app
from app import models
from app.db import engine

# Create database tables for testing
models.Base.metadata.create_all(bind=engine)

client = TestClient(app)


def auth_headers():
    return {"Authorization": "Bearer dev-token"}


def test_register_and_me():
    r = client.post(
        "/auth/register",
        json={"username": "alice", "role": "Admin", "token": "dev-token"},
    )
    assert r.status_code == 200
    r = client.get("/auth/me", headers=auth_headers())
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


def test_ingest_and_search():
    client.post(
        "/auth/register",
        json={"username": "bob", "role": "Viewer", "token": "dev-token"},
    )
    r = client.post("/ingest/", json={"content": "hello world"}, headers=auth_headers())
    assert r.status_code == 200
    r2 = client.get("/search/", params={"q": "hello"}, headers=auth_headers())
    assert len(r2.json()) >= 1


def test_misc_routes():
    paths = [
        "/orchestrator/",
        "/estimate/",
        "/compliance/",
        "/pm/",
        "/safety/",
        "/finance/",
        "/history/",
    ]
    for path in paths:
        resp = client.get(path, headers=auth_headers())
        assert resp.status_code == 200
