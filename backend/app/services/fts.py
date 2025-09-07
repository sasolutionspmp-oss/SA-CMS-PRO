"""SQLite FTS5 utilities."""
from sqlalchemy import text
from sqlalchemy.engine import Connection


def ensure_fts(conn: Connection) -> None:
    conn.execute(
        text("CREATE VIRTUAL TABLE IF NOT EXISTS fts_docs USING fts5(content)")
    )


def index_document(conn: Connection, doc_id: int, content: str) -> None:
    ensure_fts(conn)
    conn.execute(
        text("INSERT INTO fts_docs(rowid, content) VALUES (:id, :content)"),
        {"id": doc_id, "content": content},
    )


def search(conn: Connection, query: str) -> list[str]:
    ensure_fts(conn)
    result = conn.execute(
        text("SELECT content FROM fts_docs WHERE fts_docs MATCH :q"), {"q": query}
    )
    return [row[0] for row in result]
