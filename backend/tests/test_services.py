from sqlalchemy.orm import Session
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app import models
from app.db import engine
from app.services import (
    parsing,
    chunking,
    embedding,
    pricing,
    indices,
    rsmeans_import,
    learn,
    reporter,
    jobs,
    fts,
)


def test_service_functions():
    assert parsing.parse_bytes(b"hello") == "hello"
    assert list(parsing.iter_lines("a\nb")) == ["a", "b"]
    assert chunking.chunk_text("abcd", 2) == ["ab", "cd"]
    assert len(embedding.embed_text("test")) == 8
    assert pricing.estimate_cost(100) == 1.0
    assert rsmeans_import.load_cost_data()[0]["item"] == "Concrete"
    assert learn.train(["a", "b"]) == {"trained": 2}
    assert reporter.generate_report(["x", "y"]) == "x\ny"

    job_list: list[jobs.Job] = []
    jobs.queue_job(jobs.Job(sum, ([1, 2, 3],), {}), job_list)
    assert jobs.run_jobs(job_list) == [6]

    models.Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(models.Document.__table__.insert(), [{"content": "hello world"}])
        session = Session(bind=conn)
        assert indices.rebuild_indices(session) >= 1
        assert "hello world" in fts.search(conn, "hello")
