"""Owned evidence: documents with immutable, hashed revisions.

Downstream records (estimates, commitments, bills) bind to a specific
revision id and content hash.  A new revision never erases accepted history;
it marks dependents stale for review.
"""
from __future__ import annotations

from typing import Any

from ..core.audit import Audit
from ..core.db import Database
from ..core.ids import new_id, sha256_hex, utcnow_iso


class EvidenceError(RuntimeError):
    pass


class Evidence:
    def __init__(self, db: Database, audit: Audit):
        self.db = db
        self.audit = audit

    def register_document(self, *, project_id: str, kind: str, title: str, actor: str) -> dict[str, Any]:
        doc_id = new_id("doc")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO documents (id, project_id, kind, title, created_at) VALUES (?,?,?,?,?)", (doc_id, project_id, kind, title, utcnow_iso()))
            self.audit.record(actor, "document.registered", "document", doc_id, {"project_id": project_id, "kind": kind, "title": title})
        return self.document(doc_id)

    def add_revision(self, *, document_id: str, content: bytes | str, note: str = "", actor: str) -> dict[str, Any]:
        content_hash = sha256_hex(content)
        rev_id = new_id("rev")
        with self.db.transaction() as conn:
            if conn.execute("SELECT id FROM documents WHERE id=?", (document_id,)).fetchone() is None:
                raise EvidenceError(f"unknown document {document_id}")
            last = conn.execute("SELECT MAX(revision) FROM document_revisions WHERE document_id=?", (document_id,)).fetchone()[0] or 0
            conn.execute(
                "INSERT INTO document_revisions (id, document_id, revision, content_hash, note, created_at) VALUES (?,?,?,?,?,?)",
                (rev_id, document_id, last + 1, content_hash, note, utcnow_iso()),
            )
            self.audit.record(actor, "document.revised", "document", document_id, {"revision_id": rev_id, "revision": last + 1, "content_hash": content_hash, "note": note})
        return self.revision(rev_id)

    def revision(self, revision_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM document_revisions WHERE id=?", (revision_id,))
        if row is None:
            raise EvidenceError(f"unknown document revision {revision_id}")
        current = self.current_revision(row["document_id"])
        row["is_current"] = current is not None and current["id"] == revision_id
        row["current_revision"] = current["revision"] if current else None
        return row

    def current_revision(self, document_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM document_revisions WHERE document_id=? ORDER BY revision DESC LIMIT 1", (document_id,))

    def is_current(self, revision_id: str) -> bool:
        return self.revision(revision_id)["is_current"]

    def document(self, document_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM documents WHERE id=?", (document_id,))
        if row is None:
            raise EvidenceError(f"unknown document {document_id}")
        row["revisions"] = self.db.query("SELECT * FROM document_revisions WHERE document_id=? ORDER BY revision", (document_id,))
        return row

    def documents(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM documents WHERE project_id=? ORDER BY created_at", (project_id,))
        for r in rows:
            cur = self.current_revision(r["id"])
            r["current_revision"] = cur
        return rows
