"""Estimates bound to an evidence revision.

An estimate carries the exact document revision it was priced from.  If that
document gains a newer revision the estimate is *stale*: it stays readable and
approved history is preserved, but Ricky abstains from building new
commitments on it and approvals that bind it are invalidated.
"""
from __future__ import annotations

from typing import Any

from ..core.approvals import build_manifest
from ..core.audit import Audit
from ..core.db import Database
from ..core.ids import hash_json, new_id, utcnow_iso
from ..core.money import D, fmt, money, total
from .evidence import Evidence


class EstimateError(RuntimeError):
    pass


class Estimates:
    def __init__(self, db: Database, audit: Audit, evidence: Evidence):
        self.db = db
        self.audit = audit
        self.evidence = evidence

    @staticmethod
    def _normalise_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not lines:
            raise EstimateError("an estimate needs at least one line")
        out = []
        for idx, raw in enumerate(lines, start=1):
            qty = D(raw["quantity"])
            price = money(raw["unit_price"])
            if qty < 0 or price < 0:
                raise EstimateError(f"line {idx}: negative quantity or price")
            out.append({
                "line_no": idx,
                "description": str(raw["description"]),
                "quantity": f"{qty.normalize():f}",
                "unit": str(raw.get("unit", "ea")),
                "unit_price": fmt(price),
                "amount": fmt(money(qty * price)),
            })
        return out

    def create(self, *, project_id: str, document_revision_id: str, lines: list[dict[str, Any]], actor: str, supersedes: str | None = None) -> dict[str, Any]:
        rev = self.evidence.revision(document_revision_id)
        norm = self._normalise_lines(lines)
        est_total = total(ln["amount"] for ln in norm)
        content_hash = hash_json({"document_revision_id": document_revision_id, "document_hash": rev["content_hash"], "lines": norm})
        est_id = new_id("est")
        with self.db.transaction() as conn:
            revision = 1
            if supersedes:
                prev = self.get(supersedes)
                if prev["project_id"] != project_id:
                    raise EstimateError("cannot supersede an estimate from another project")
                revision = prev["revision"] + 1
                conn.execute("UPDATE estimates SET status='superseded' WHERE id=?", (supersedes,))
            conn.execute(
                "INSERT INTO estimates (id, project_id, document_revision_id, revision, supersedes, status, total, content_hash, created_at) VALUES (?,?,?,?,?,'draft',?,?,?)",
                (est_id, project_id, document_revision_id, revision, supersedes, fmt(est_total), content_hash, utcnow_iso()),
            )
            for ln in norm:
                conn.execute(
                    "INSERT INTO estimate_lines (id, estimate_id, line_no, description, quantity, unit, unit_price, amount) VALUES (?,?,?,?,?,?,?,?)",
                    (new_id("eln"), est_id, ln["line_no"], ln["description"], ln["quantity"], ln["unit"], ln["unit_price"], ln["amount"]),
                )
            self.audit.record(actor, "estimate.created", "estimate", est_id, {"project_id": project_id, "document_revision_id": document_revision_id, "total": fmt(est_total), "content_hash": content_hash, "supersedes": supersedes})
        return self.get(est_id)

    def get(self, estimate_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM estimates WHERE id=?", (estimate_id,))
        if row is None:
            raise EstimateError(f"unknown estimate {estimate_id}")
        row["lines"] = self.db.query("SELECT * FROM estimate_lines WHERE estimate_id=? ORDER BY line_no", (estimate_id,))
        rev = self.evidence.revision(row["document_revision_id"])
        row["evidence"] = {"document_id": rev["document_id"], "revision": rev["revision"], "content_hash": rev["content_hash"], "is_current": rev["is_current"], "current_revision": rev["current_revision"]}
        row["stale"] = not rev["is_current"]
        return row

    def list(self, project_id: str) -> list[dict[str, Any]]:
        return [self.get(r["id"]) for r in self.db.query("SELECT id FROM estimates WHERE project_id=? ORDER BY created_at", (project_id,))]

    def manifest(self, estimate_id: str, *, actor_role: str) -> dict[str, Any]:
        est = self.get(estimate_id)
        return build_manifest(
            operation="estimate.approve",
            subject_type="estimate",
            subject_id=estimate_id,
            actor_role=actor_role,
            amounts={"total": est["total"]},
            bindings={
                "estimate_revision": est["revision"],
                "estimate_hash": est["content_hash"],
                "document_revision_id": est["document_revision_id"],
                "document_hash": est["evidence"]["content_hash"],
                "document_is_current": est["evidence"]["is_current"],
            },
        )

    def approve(self, estimate_id: str, *, approval_id: str, actor: str) -> dict[str, Any]:
        """Mark approved.  The caller has already consumed ``approval_id``."""
        with self.db.transaction() as conn:
            est = self.get(estimate_id)
            if est["status"] != "draft":
                raise EstimateError(f"estimate {estimate_id} is {est['status']}")
            if est["stale"]:
                raise EstimateError("estimate is priced from a superseded document revision; revise it first")
            conn.execute("UPDATE estimates SET status='approved', approval_id=? WHERE id=?", (approval_id, estimate_id))
            self.audit.record(actor, "estimate.approved", "estimate", estimate_id, {"approval_id": approval_id, "total": est["total"]})
        return self.get(estimate_id)
