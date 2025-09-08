from pathlib import Path
from typing import List

from .db import get_db


def index_chunks(file_id: int, chunks: List[Path]) -> None:
    conn = get_db()
    cur = conn.cursor()
    for idx, path in enumerate(chunks):
        text = path.read_text()
        cur.execute("INSERT INTO fts(content) VALUES (?)", (text,))
        rowid = cur.lastrowid
        cur.execute(
            "INSERT INTO fts_map(rowid, file_id, chunk_idx, page_hint) VALUES (?,?,?,?)",
            (rowid, file_id, idx, None),
        )
    conn.commit()
