"""Drawing register: issued versus working revisions and exact references.

A drawing is a controlled register entry (``number`` unique within its
project).  Its content lives in the evidence module: every drawing revision
binds to one immutable ``document_revisions`` row and copies that row's
content hash.  Revision lifecycle::

    working --(drawing.issue, approval-bound)--> issued --(next issue)--> superseded
    working --(replace_working)----------------> withdrawn

Rules:

* at most one *working* and at most one *issued* revision per drawing (partial
  unique indexes enforce both); issuing the next revision supersedes the
  issued one;
* the *usable* revision is the issued one, never the working one, so a
  drawing under revision still resolves to the set that was actually issued;
* references (from commitments, bills, RFIs, anything) are exact: they bind
  the revision id and content hash, are permitted only on the issued revision
  and are append-only, so a later issue never rewrites what a record relied on;
* every change to a drawing bumps its version (a trigger rejects an update
  that does not).  The issue manifest binds that version, the revision label
  and status, the evidence content hash and whether that evidence revision is
  still current, so an approval granted against one state cannot execute
  against another.  Withdrawing a working revision also invalidates its open
  approvals outright, because a withdrawn revision can never be issued.

Drawings carry no money: nothing here posts a journal.  Issue is nonetheless
recorded against an open accounting period (``ledger.require_open``) so the
issued set is frozen together with the period.
"""
from __future__ import annotations

from typing import Any

from ..core.approvals import build_manifest
from ..core.ids import new_id, utcnow_iso
from .evidence import EvidenceError

SCHEMA_NAME = "drawings"
PLUGIN_NAME = "drawing"
ISSUE_OPERATION = "drawing.issue"
SUBJECT_TYPE = "drawing_revision"

SCHEMA_STATEMENTS = [
    """CREATE TABLE drawing_register (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        number TEXT NOT NULL,
        title TEXT NOT NULL,
        discipline TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (project_id, number)
    )""",
    "CREATE TRIGGER drawing_register_no_delete BEFORE DELETE ON drawing_register BEGIN SELECT RAISE(ABORT, 'drawings are never deleted from the register'); END",
    """CREATE TRIGGER drawing_register_identity_immutable BEFORE UPDATE OF id, project_id, number ON drawing_register
        BEGIN SELECT RAISE(ABORT, 'drawing identity (project, number) is immutable'); END""",
    """CREATE TRIGGER drawing_register_version_bumps BEFORE UPDATE ON drawing_register
        WHEN NEW.version <= OLD.version
        BEGIN SELECT RAISE(ABORT, 'every drawing change must bump the drawing version'); END""",
    """CREATE TABLE drawing_revisions (
        id TEXT PRIMARY KEY,
        drawing_id TEXT NOT NULL REFERENCES drawing_register(id),
        sequence INTEGER NOT NULL,
        label TEXT NOT NULL,
        document_revision_id TEXT NOT NULL REFERENCES document_revisions(id),
        content_hash TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL CHECK (status IN ('working','issued','superseded','withdrawn')),
        approval_id TEXT REFERENCES approvals(id),
        issued_period_id TEXT REFERENCES periods(id),
        created_at TEXT NOT NULL,
        issued_at TEXT,
        superseded_at TEXT,
        superseded_by TEXT REFERENCES drawing_revisions(id),
        withdrawn_at TEXT,
        replaced_by TEXT REFERENCES drawing_revisions(id),
        UNIQUE (drawing_id, sequence)
    )""",
    "CREATE UNIQUE INDEX drawing_revisions_one_working ON drawing_revisions (drawing_id) WHERE status = 'working'",
    "CREATE UNIQUE INDEX drawing_revisions_one_issued ON drawing_revisions (drawing_id) WHERE status = 'issued'",
    "CREATE UNIQUE INDEX drawing_revisions_live_label ON drawing_revisions (drawing_id, label) WHERE status != 'withdrawn'",
    "CREATE UNIQUE INDEX drawing_revisions_live_evidence ON drawing_revisions (drawing_id, document_revision_id) WHERE status != 'withdrawn'",
    "CREATE TRIGGER drawing_revisions_no_delete BEFORE DELETE ON drawing_revisions BEGIN SELECT RAISE(ABORT, 'drawing revisions are history and are never deleted'); END",
    """CREATE TRIGGER drawing_revisions_binding_immutable BEFORE UPDATE OF id, drawing_id, sequence, label, document_revision_id, content_hash ON drawing_revisions
        BEGIN SELECT RAISE(ABORT, 'a drawing revision binding (label, evidence, hash) is immutable; add or replace a revision instead'); END""",
    """CREATE TRIGGER drawing_revisions_status_machine BEFORE UPDATE OF status ON drawing_revisions
        WHEN NEW.status != OLD.status AND NOT (
            (OLD.status = 'working' AND NEW.status IN ('issued', 'withdrawn'))
            OR (OLD.status = 'issued' AND NEW.status = 'superseded')
        )
        BEGIN SELECT RAISE(ABORT, 'illegal drawing revision status transition'); END""",
    """CREATE TABLE drawing_references (
        id TEXT PRIMARY KEY,
        drawing_id TEXT NOT NULL REFERENCES drawing_register(id),
        drawing_revision_id TEXT NOT NULL REFERENCES drawing_revisions(id),
        referenced_by_type TEXT NOT NULL,
        referenced_by_id TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (drawing_revision_id, referenced_by_type, referenced_by_id)
    )""",
    """CREATE TRIGGER drawing_references_issued_only BEFORE INSERT ON drawing_references
        BEGIN
            SELECT CASE
                WHEN (SELECT status FROM drawing_revisions WHERE id = NEW.drawing_revision_id) IS NOT 'issued'
                THEN RAISE(ABORT, 'drawing references may bind only to the issued revision')
            END;
        END""",
    "CREATE TRIGGER drawing_references_no_update BEFORE UPDATE ON drawing_references BEGIN SELECT RAISE(ABORT, 'drawing references are exact and append-only'); END",
    "CREATE TRIGGER drawing_references_no_delete BEFORE DELETE ON drawing_references BEGIN SELECT RAISE(ABORT, 'drawing references are exact and append-only'); END",
]


class DrawingError(RuntimeError):
    """Invalid drawing register input or an illegal register transition."""


class Plugin:
    def __init__(self, cipher):
        self.c = cipher
        self.db = cipher.db
        self.audit = cipher.audit
        self.ledger = cipher.ledger
        self.approvals = cipher.approvals

    # ---- validation helpers ------------------------------------------------- #

    @staticmethod
    def _text(value: Any, label: str, *, required: bool = True) -> str:
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise DrawingError(f"{label} must be a string, not {type(value).__name__}")
        text = value.strip()
        if required and not text:
            raise DrawingError(f"{label} is required")
        return text

    def _project(self, project_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM projects WHERE id=?", (project_id,))
        if row is None:
            raise DrawingError(f"unknown project {project_id}")
        return row

    def _evidence_for(self, drawing: dict[str, Any], document_revision_id: Any) -> dict[str, Any]:
        """The evidence revision a drawing revision binds to.  It must exist,
        belong to the drawing's project and not already be bound to a live
        (non-withdrawn) revision of the same drawing."""
        if not isinstance(document_revision_id, str) or not document_revision_id.strip():
            raise DrawingError("document_revision_id is required")
        try:
            ev = self.c.evidence.revision(document_revision_id)
        except EvidenceError as exc:
            raise DrawingError(f"drawing revisions must bind to an existing evidence revision: {exc}") from exc
        doc = self.db.one("SELECT project_id FROM documents WHERE id=?", (ev["document_id"],))
        if doc is None or doc["project_id"] != drawing["project_id"]:
            raise DrawingError(f"evidence revision {document_revision_id} belongs to a different project than drawing {drawing['number']}")
        live = self.db.one(
            "SELECT id, label, status FROM drawing_revisions WHERE drawing_id=? AND document_revision_id=? AND status != 'withdrawn'",
            (drawing["id"], document_revision_id),
        )
        if live is not None:
            raise DrawingError(f"evidence revision {document_revision_id} is already bound to revision {live['label']} ({live['status']}) of drawing {drawing['number']}")
        return ev

    def _require_label_free(self, drawing: dict[str, Any], label: str) -> None:
        live = self.db.one("SELECT id, status FROM drawing_revisions WHERE drawing_id=? AND label=? AND status != 'withdrawn'", (drawing["id"], label))
        if live is not None:
            raise DrawingError(f"drawing {drawing['number']} already has a revision labelled {label!r} ({live['status']})")

    def _bump(self, conn, drawing: dict[str, Any]) -> int:
        version = drawing["version"] + 1
        cur = conn.execute("UPDATE drawing_register SET version=?, updated_at=? WHERE id=? AND version=?", (version, utcnow_iso(), drawing["id"], drawing["version"]))
        if cur.rowcount != 1:
            raise DrawingError(f"drawing {drawing['number']} changed concurrently; retry")
        return version

    def _insert_revision(self, conn, drawing: dict[str, Any], label: str, ev: dict[str, Any], note: str) -> str:
        seq = conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM drawing_revisions WHERE drawing_id=?", (drawing["id"],)).fetchone()[0] + 1
        rev_id = new_id("dwr")
        conn.execute(
            "INSERT INTO drawing_revisions (id, drawing_id, sequence, label, document_revision_id, content_hash, note, status, created_at) VALUES (?,?,?,?,?,?,?,'working',?)",
            (rev_id, drawing["id"], seq, label, ev["id"], ev["content_hash"], note, utcnow_iso()),
        )
        return rev_id

    # ---- drawings ---------------------------------------------------------- #

    def register_drawing(self, project_id: str, number: str, title: str, discipline: str, actor: str = "owner") -> dict[str, Any]:
        """Register a drawing on a project.  ``number`` is unique per project (case-insensitive)."""
        self._project(project_id)
        number = self._text(number, "drawing number")
        title = self._text(title, "drawing title")
        discipline = self._text(discipline, "discipline")
        actor = self._text(actor, "actor")
        drawing_id = new_id("dwg")
        now = utcnow_iso()
        with self.db.transaction() as conn:
            dup = conn.execute("SELECT number FROM drawing_register WHERE project_id=? AND lower(number)=lower(?)", (project_id, number)).fetchone()
            if dup is not None:
                raise DrawingError(f"drawing number {dup['number']!r} is already registered on project {project_id}")
            conn.execute(
                "INSERT INTO drawing_register (id, project_id, number, title, discipline, version, created_at, updated_at) VALUES (?,?,?,?,?,1,?,?)",
                (drawing_id, project_id, number, title, discipline, now, now),
            )
            self.audit.record(actor, "drawing.registered", "drawing", drawing_id, {"project_id": project_id, "number": number, "title": title, "discipline": discipline, "version": 1})
        return self.get(drawing_id)

    def update_drawing(self, drawing_id: str, *, title: str | None = None, discipline: str | None = None, actor: str = "owner") -> dict[str, Any]:
        """Edit register metadata.  The number is immutable; the version bumps so
        any open issue approval bound to the old version goes stale."""
        actor = self._text(actor, "actor")
        with self.db.transaction() as conn:
            d = self.get(drawing_id)
            changes: dict[str, Any] = {}
            if title is not None:
                t = self._text(title, "drawing title")
                if t != d["title"]:
                    changes["title"] = t
            if discipline is not None:
                disc = self._text(discipline, "discipline")
                if disc != d["discipline"]:
                    changes["discipline"] = disc
            if not changes:
                raise DrawingError(f"nothing to update on drawing {d['number']}")
            conn.execute(
                "UPDATE drawing_register SET title=?, discipline=?, version=?, updated_at=? WHERE id=? AND version=?",
                (changes.get("title", d["title"]), changes.get("discipline", d["discipline"]), d["version"] + 1, utcnow_iso(), drawing_id, d["version"]),
            )
            self.audit.record(actor, "drawing.updated", "drawing", drawing_id, {"changes": changes, "version": d["version"] + 1})
        return self.get(drawing_id)

    def get(self, drawing_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM drawing_register WHERE id=?", (drawing_id,))
        if row is None:
            raise DrawingError(f"unknown drawing {drawing_id}")
        return row

    def by_number(self, project_id: str, number: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM drawing_register WHERE project_id=? AND lower(number)=lower(?)", (project_id, self._text(number, "drawing number")))
        if row is None:
            raise DrawingError(f"no drawing {number!r} on project {project_id}")
        return row

    # ---- revisions ----------------------------------------------------------- #

    def add_revision(self, drawing_id: str, label: str, document_revision_id: str, note: str = "", actor: str = "owner") -> dict[str, Any]:
        """Add a working revision bound to an existing evidence revision of the
        same project.  Only one working revision may exist at a time."""
        label = self._text(label, "revision label")
        note = self._text(note, "note", required=False)
        actor = self._text(actor, "actor")
        with self.db.transaction() as conn:
            d = self.get(drawing_id)
            working = self.working_revision(drawing_id)
            if working is not None:
                raise DrawingError(f"drawing {d['number']} already has working revision {working['label']}; issue it or use replace_working")
            self._require_label_free(d, label)
            ev = self._evidence_for(d, document_revision_id)
            rev_id = self._insert_revision(conn, d, label, ev, note)
            version = self._bump(conn, d)
            self.audit.record(actor, "drawing.revision_added", SUBJECT_TYPE, rev_id, {
                "drawing_id": d["id"], "number": d["number"], "label": label, "document_revision_id": ev["id"],
                "content_hash": ev["content_hash"], "evidence_is_current": bool(ev["is_current"]), "note": note, "drawing_version": version,
            })
        return self.revision(rev_id)

    def replace_working(self, drawing_id: str, document_revision_id: str, actor: str = "owner", *, label: str | None = None, note: str = "") -> dict[str, Any]:
        """Withdraw the current working revision and start a new one bound to
        ``document_revision_id``.  The label carries over unless given.  Open
        approvals on the withdrawn revision are invalidated: it can never issue."""
        actor = self._text(actor, "actor")
        note = self._text(note, "note", required=False)
        with self.db.transaction() as conn:
            d = self.get(drawing_id)
            old = self.working_revision(drawing_id)
            if old is None:
                raise DrawingError(f"drawing {d['number']} has no working revision to replace; use add_revision")
            new_label = self._text(label, "revision label") if label is not None else old["label"]
            ev = self._evidence_for(d, document_revision_id)  # also rejects re-binding the evidence the working revision already holds
            now = utcnow_iso()
            conn.execute("UPDATE drawing_revisions SET status='withdrawn', withdrawn_at=? WHERE id=? AND status='working'", (now, old["id"]))
            self._require_label_free(d, new_label)  # after the withdrawal so the same label may be reused
            rev_id = self._insert_revision(conn, d, new_label, ev, note)
            conn.execute("UPDATE drawing_revisions SET replaced_by=? WHERE id=?", (rev_id, old["id"]))
            version = self._bump(conn, d)
            invalidated = self.approvals.invalidate_for_subject(
                SUBJECT_TYPE, old["id"], reason=f"working revision {old['label']} of drawing {d['number']} was withdrawn and replaced", actor=actor
            )
            self.audit.record(actor, "drawing.revision_withdrawn", SUBJECT_TYPE, old["id"], {
                "drawing_id": d["id"], "number": d["number"], "label": old["label"], "replaced_by": rev_id, "approvals_invalidated": invalidated, "drawing_version": version,
            })
            self.audit.record(actor, "drawing.revision_added", SUBJECT_TYPE, rev_id, {
                "drawing_id": d["id"], "number": d["number"], "label": new_label, "document_revision_id": ev["id"], "content_hash": ev["content_hash"],
                "evidence_is_current": bool(ev["is_current"]), "note": note, "replaces": old["id"], "drawing_version": version,
            })
        return self.revision(rev_id)

    def _decorate(self, row: dict[str, Any]) -> dict[str, Any]:
        ev = self.db.one("SELECT document_id, revision FROM document_revisions WHERE id=?", (row["document_revision_id"],))
        current = self.db.one("SELECT id FROM document_revisions WHERE document_id=? ORDER BY revision DESC LIMIT 1", (ev["document_id"],)) if ev else None
        row["evidence_document_id"] = ev["document_id"] if ev else None
        row["evidence_revision"] = ev["revision"] if ev else None
        row["evidence_is_current"] = bool(current is not None and current["id"] == row["document_revision_id"])
        row["reference_count"] = self.db.scalar("SELECT COUNT(*) FROM drawing_references WHERE drawing_revision_id=?", (row["id"],))
        row["is_usable"] = row["status"] == "issued"
        return row

    def revision(self, revision_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM drawing_revisions WHERE id=?", (revision_id,))
        if row is None:
            raise DrawingError(f"unknown drawing revision {revision_id}")
        return self._decorate(row)

    def revisions(self, drawing_id: str) -> list[dict[str, Any]]:
        self.get(drawing_id)
        return [self._decorate(r) for r in self.db.query("SELECT * FROM drawing_revisions WHERE drawing_id=? ORDER BY sequence", (drawing_id,))]

    def working_revision(self, drawing_id: str) -> dict[str, Any] | None:
        self.get(drawing_id)
        row = self.db.one("SELECT * FROM drawing_revisions WHERE drawing_id=? AND status='working' ORDER BY sequence DESC LIMIT 1", (drawing_id,))
        return self._decorate(row) if row else None

    def usable_revision(self, drawing_id: str) -> dict[str, Any] | None:
        """The latest issued revision, even when a newer working revision exists; None if nothing was issued."""
        self.get(drawing_id)
        row = self.db.one("SELECT * FROM drawing_revisions WHERE drawing_id=? AND status='issued' ORDER BY issued_at DESC, sequence DESC LIMIT 1", (drawing_id,))
        return self._decorate(row) if row else None

    # ---- issue (approval-bound) ---------------------------------------------- #

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        """Bind everything whose change must invalidate an issue approval.  The
        manifest reflects the revision's current status rather than rejecting a
        non-working one, so the core's material-hash comparison (not a plugin
        error) is what stops a stale approval; ``apply`` enforces the status."""
        if operation != ISSUE_OPERATION:
            raise DrawingError(f"unknown drawing operation {operation}")
        rev = self.revision(subject_id)
        d = self.get(rev["drawing_id"])
        ev = self.c.evidence.revision(rev["document_revision_id"])
        usable = self.usable_revision(d["id"])
        return build_manifest(
            operation=operation,
            subject_type=SUBJECT_TYPE,
            subject_id=subject_id,
            actor_role=actor_role,
            amounts={},
            bindings={
                "project_id": d["project_id"],
                "drawing_id": d["id"],
                "drawing_number": d["number"],
                "drawing_version": d["version"],
                "revision_label": rev["label"],
                "revision_status": rev["status"],
                "document_revision_id": rev["document_revision_id"],
                "evidence_document_revision": ev["revision"],
                "evidence_content_hash": ev["content_hash"],
                "evidence_is_current": bool(ev["is_current"]),
                "supersedes": usable["id"] if usable else None,
                "supersedes_label": usable["label"] if usable else None,
            },
        )

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        """Issue the working revision: it becomes ``issued`` and the previously
        issued revision becomes ``superseded``.  The caller has consumed
        ``approval_id`` against ``manifest``."""
        if operation != ISSUE_OPERATION:
            raise DrawingError(f"unknown drawing operation {operation}")
        with self.db.transaction() as conn:
            rev = self.revision(subject_id)
            d = self.get(rev["drawing_id"])
            if rev["status"] != "working":
                raise DrawingError(f"only a working revision can be issued; drawing {d['number']} revision {rev['label']} is {rev['status']}")
            ev = self.c.evidence.revision(rev["document_revision_id"])
            if ev["content_hash"] != rev["content_hash"] or manifest["bindings"].get("evidence_content_hash") != rev["content_hash"]:
                raise DrawingError(f"evidence content hash no longer matches the binding of drawing {d['number']} revision {rev['label']}")
            pid = period_id or self.c.current_period()["id"]
            self.ledger.require_open(pid)
            now = utcnow_iso()
            superseded: list[dict[str, Any]] = []
            for prev in conn.execute("SELECT id, label FROM drawing_revisions WHERE drawing_id=? AND status='issued'", (d["id"],)).fetchall():
                conn.execute("UPDATE drawing_revisions SET status='superseded', superseded_at=?, superseded_by=? WHERE id=?", (now, rev["id"], prev["id"]))
                superseded.append({"id": prev["id"], "label": prev["label"]})
            conn.execute("UPDATE drawing_revisions SET status='issued', issued_at=?, approval_id=?, issued_period_id=? WHERE id=?", (now, approval_id, pid, rev["id"]))
            version = self._bump(conn, d)
            for s in superseded:
                self.audit.record(actor, "drawing.revision_superseded", SUBJECT_TYPE, s["id"], {"drawing_id": d["id"], "number": d["number"], "label": s["label"], "superseded_by": rev["id"]})
            self.audit.record(actor, "drawing.issued", SUBJECT_TYPE, rev["id"], {
                "drawing_id": d["id"], "number": d["number"], "label": rev["label"], "document_revision_id": rev["document_revision_id"],
                "content_hash": rev["content_hash"], "evidence_is_current": bool(ev["is_current"]), "period_id": pid, "approval_id": approval_id,
                "superseded": [s["id"] for s in superseded], "drawing_version": version,
            })
        return {
            "drawing": d["id"], "number": d["number"], "revision": rev["id"], "label": rev["label"], "status": "issued",
            "issued_at": now, "period_id": pid, "superseded": [s["id"] for s in superseded], "drawing_version": version,
        }

    # ---- references ------------------------------------------------------------ #

    def reference(self, drawing_revision_id: str, referenced_by_type: str, referenced_by_id: str, actor: str = "owner") -> dict[str, Any]:
        """Record that ``referenced_by_type``/``referenced_by_id`` relies on exactly
        this drawing revision.  Allowed only on the issued revision."""
        rtype = self._text(referenced_by_type, "referenced_by_type")
        rid = self._text(referenced_by_id, "referenced_by_id")
        actor = self._text(actor, "actor")
        with self.db.transaction() as conn:
            rev = self.revision(drawing_revision_id)
            d = self.get(rev["drawing_id"])
            if rev["status"] != "issued":
                raise DrawingError(f"drawing {d['number']} revision {rev['label']} is {rev['status']}; only the issued revision may be referenced")
            dup = conn.execute(
                "SELECT id FROM drawing_references WHERE drawing_revision_id=? AND referenced_by_type=? AND referenced_by_id=?", (rev["id"], rtype, rid)
            ).fetchone()
            if dup is not None:
                raise DrawingError(f"{rtype} {rid} already references drawing {d['number']} revision {rev['label']}")
            ref_id = new_id("dref")
            conn.execute(
                "INSERT INTO drawing_references (id, drawing_id, drawing_revision_id, referenced_by_type, referenced_by_id, content_hash, created_at) VALUES (?,?,?,?,?,?,?)",
                (ref_id, d["id"], rev["id"], rtype, rid, rev["content_hash"], utcnow_iso()),
            )
            self.audit.record(actor, "drawing.referenced", "drawing_reference", ref_id, {
                "drawing_id": d["id"], "number": d["number"], "drawing_revision_id": rev["id"], "label": rev["label"],
                "referenced_by_type": rtype, "referenced_by_id": rid, "content_hash": rev["content_hash"],
            })
        return self._reference(ref_id)

    def _reference(self, ref_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM drawing_references WHERE id=?", (ref_id,))
        if row is None:
            raise DrawingError(f"unknown drawing reference {ref_id}")
        return row

    def references(self, drawing_revision_id: str) -> list[dict[str, Any]]:
        self.revision(drawing_revision_id)
        return self.db.query("SELECT * FROM drawing_references WHERE drawing_revision_id=? ORDER BY created_at, id", (drawing_revision_id,))

    # ---- register and state ------------------------------------------------------ #

    def _describe(self, d: dict[str, Any]) -> dict[str, Any]:
        revs = self.revisions(d["id"])
        usable = next((r for r in revs if r["status"] == "issued"), None)
        working = next((r for r in revs if r["status"] == "working"), None)
        history = sorted((r for r in revs if r["status"] in ("issued", "superseded")), key=lambda r: (r["issued_at"] or "", r["sequence"]))
        return {
            **d,
            "usable_revision": usable,
            "working_revision": working,
            "issue_history": history,
            "revisions": revs,
            "reference_count": sum(r["reference_count"] for r in revs),
        }

    def register(self, project_id: str) -> list[dict[str, Any]]:
        """Every drawing on the project with its usable revision, working revision and issue history."""
        self._project(project_id)
        return [self._describe(d) for d in self.db.query("SELECT * FROM drawing_register WHERE project_id=? ORDER BY number, created_at", (project_id,))]

    def state(self, project_id: str) -> dict[str, Any]:
        reg = self.register(project_id)
        return {
            "register": reg,
            "summary": {
                "drawings": len(reg),
                "issued": sum(1 for d in reg if d["usable_revision"] is not None),
                "working": sum(1 for d in reg if d["working_revision"] is not None),
                "references": sum(d["reference_count"] for d in reg),
            },
        }
