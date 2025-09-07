import sqlite3
from typing import List, Dict, Any
import numpy as np

# Synthetic documents for demonstration
DOCUMENTS = [
    {"id": 1, "file": "doc1.txt", "page": 1, "content": "cat sat on the mat"},
    {"id": 2, "file": "doc2.txt", "page": 1, "content": "cat cat cat"},
    {"id": 3, "file": "doc3.txt", "page": 1, "content": "dog dog dog"},
]

# Pre-computed simple embeddings for semantic search
EMBEDDINGS = {
    1: np.array([1.0, 0.0]),  # cat
    2: np.array([1.0, 0.0]),  # cat repeated
    3: np.array([0.0, 1.0]),  # dog
}

# Setup in-memory SQLite database with FTS5
CONN = sqlite3.connect(":memory:", check_same_thread=False)
CONN.execute(
    "CREATE VIRTUAL TABLE docs USING fts5(id UNINDEXED, file, page, content)"
)
for doc in DOCUMENTS:
    CONN.execute(
        "INSERT INTO docs(id, file, page, content) VALUES (?, ?, ?, ?)",
        (doc["id"], doc["file"], doc["page"], doc["content"]),
    )
CONN.commit()


def keyword_search(q: str, k: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
    cur = CONN.execute(
        """
        SELECT id, file, page, content, bm25(docs) as rank
        FROM docs
        WHERE docs MATCH ?
        ORDER BY rank
        LIMIT ? OFFSET ?
        """,
        (q, k, offset),
    )
    rows = cur.fetchall()
    results = []
    for row in rows:
        doc_id, file, page, content, rank = row
        results.append(
            {
                "file": file,
                "page": page,
                "content": content,
                "rank": rank,
                "openHere": f"{file}#page={page}",
            }
        )
    return results


def _embed(text: str) -> np.ndarray:
    vec = np.zeros(2, dtype=float)
    vec[0] = text.count("cat")
    vec[1] = text.count("dog")
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


def semantic_search(query: str, k: int = 10, threshold: float = 0.3) -> List[Dict[str, Any]]:
    qvec = _embed(query)
    results = []
    for doc in DOCUMENTS:
        dvec = EMBEDDINGS[doc["id"]]
        score = float(np.dot(qvec, dvec))
        if score >= threshold:
            results.append(
                {
                    "file": doc["file"],
                    "page": doc["page"],
                    "content": doc["content"],
                    "score": score,
                    "openHere": f"{doc['file']}#page={doc['page']}",
                }
            )
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:k]
