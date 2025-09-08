"""Index management utilities."""
from sqlalchemy.orm import Session

from .. import models
from . import fts


def rebuild_indices(session: Session) -> int:
    conn = session.connection()
    fts.ensure_fts(conn)
    docs = session.query(models.Document).all()
    for doc in docs:
        fts.index_document(conn, doc.id, doc.content)
    return len(docs)
