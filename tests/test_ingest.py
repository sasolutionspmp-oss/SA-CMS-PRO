import time
from pathlib import Path
import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.main import app
from app.db import get_db


def wait_job(client, job_id, timeout=30):
    for _ in range(timeout):
        r = client.get(f"/api/jobs/{job_id}")
        data = r.json()
        if data.get('status') == 'done':
            return data
        time.sleep(1)
    raise RuntimeError('timeout')


def test_zip_ingestion():
    with TestClient(app) as client:
        sample = client.get('/api/ingest/sample').content
        files = {'file': ('sample.zip', sample, 'application/zip')}
        resp = client.post('/api/ingest/zip', files=files)
        job_id = resp.json()['job_id']
        wait_job(client, job_id)
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM files')
        file_count = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM chunks')
        chunk_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM fts WHERE fts MATCH 'hello'")
        hits = cur.fetchone()[0]
        assert file_count == 3
        assert chunk_count >= 2
        assert hits >= 2
