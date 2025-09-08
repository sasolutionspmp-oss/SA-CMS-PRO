import json
from datetime import datetime
from typing import List

from .db import get_db


def create_job(job_type: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO jobs(type, status, logs) VALUES (?, ?, ?)",
        (job_type, 'pending', json.dumps([])),
    )
    conn.commit()
    return cur.lastrowid


def log(job_id: int, message: str) -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT logs FROM jobs WHERE id=?", (job_id,))
    row = cur.fetchone()
    logs: List[str] = json.loads(row["logs"]) if row else []
    logs.append(message)
    cur.execute("UPDATE jobs SET logs=? WHERE id=?", (json.dumps(logs), job_id))
    conn.commit()


def update_status(job_id: int, status: str) -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE jobs SET status=?, finished_at=? WHERE id=?",
        (status, datetime.utcnow() if status in ("error", "done") else None, job_id),
    )
    conn.commit()


def get_job(job_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    row = cur.fetchone()
    if not row:
        return None
    return dict(row)
