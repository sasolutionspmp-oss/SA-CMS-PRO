"""Version-bound human approvals.

An approval binds a canonical, server-generated manifest: the operation, the
subject, the acting role, every referenced record version and content hash,
the exact amounts and allocations, the verified destination and its version,
the policy version, an expiry and a unique nonce.  Consuming an approval
re-derives the manifest from current state; any material difference
invalidates the approval instead of executing something the human did not see.
"""
from __future__ import annotations

import datetime as _dt
import secrets
from typing import Any

from .audit import Audit
from .db import Database
from .ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow, utcnow_iso
from .money import fmt

POLICY_VERSION = "cipher-approval-policy/1"
DEFAULT_EXPIRY_SECONDS = 24 * 3600
MATERIAL_KEYS = ("operation", "subject", "actor_role", "entity", "currency", "amounts", "bindings", "destination", "policy_version")


class ApprovalError(RuntimeError):
    pass


class ApprovalNotGranted(ApprovalError):
    pass


class ApprovalExpired(ApprovalNotGranted):
    """Not granted because it passed its expiry (before or after it was granted)."""


class ApprovalConsumed(ApprovalError):
    pass


class StaleApprovalError(ApprovalError):
    """The subject changed after approval; the approval has been invalidated."""


def build_manifest(
    *,
    operation: str,
    subject_type: str,
    subject_id: str,
    actor_role: str,
    amounts: dict[str, Any] | None = None,
    bindings: dict[str, Any] | None = None,
    destination: dict[str, Any] | None = None,
    policy_version: str = POLICY_VERSION,
    expiry_seconds: int = DEFAULT_EXPIRY_SECONDS,
    now: _dt.datetime | None = None,
    entity: str | None = None,
    currency: str = "USD",
) -> dict[str, Any]:
    """``entity`` (legal entity) and ``currency`` are material: an approval granted
    for one entity or currency can never execute against another."""
    now = now or utcnow()
    return {
        "operation": operation,
        "subject": {"type": subject_type, "id": subject_id},
        "actor_role": actor_role,
        "entity": entity,
        "currency": currency,
        "amounts": {k: fmt(v) for k, v in (amounts or {}).items()},
        "bindings": bindings or {},
        "destination": destination,
        "policy_version": policy_version,
        "nonce": secrets.token_hex(12),
        "expires_at": (now + _dt.timedelta(seconds=expiry_seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def material_part(manifest: dict[str, Any]) -> dict[str, Any]:
    return {k: manifest.get(k) for k in MATERIAL_KEYS}


def material_hash(manifest: dict[str, Any]) -> str:
    return hash_json(material_part(manifest))


class Approvals:
    def __init__(self, db: Database, audit: Audit):
        self.db = db
        self.audit = audit

    def request(self, manifest: dict[str, Any], *, requested_by: str) -> dict[str, Any]:
        approval_id = new_id("apr")
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO approvals (id, operation, subject_type, subject_id, actor_role, manifest_json, manifest_hash,
                   material_hash, policy_version, nonce, status, requested_by, requested_at, expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?,?,?)""",
                (
                    approval_id,
                    manifest["operation"],
                    manifest["subject"]["type"],
                    manifest["subject"]["id"],
                    manifest["actor_role"],
                    canonical_json(manifest),
                    hash_json(manifest),
                    material_hash(manifest),
                    manifest["policy_version"],
                    manifest["nonce"],
                    requested_by,
                    utcnow_iso(),
                    manifest["expires_at"],
                ),
            )
            self.audit.record(requested_by, "approval.requested", "approval", approval_id, {"operation": manifest["operation"], "subject": manifest["subject"], "manifest_hash": hash_json(manifest)})
        return self.get(approval_id)

    def get(self, approval_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
        if row is None:
            raise ApprovalError(f"unknown approval {approval_id}")
        row["manifest"] = loads(row.pop("manifest_json"))
        return row

    def pending(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM approvals WHERE status = 'pending' ORDER BY requested_at")
        for r in rows:
            r["manifest"] = loads(r.pop("manifest_json"))
        return rows

    def list(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self.db.query("SELECT * FROM approvals WHERE status = ? ORDER BY requested_at", (status,))
        else:
            rows = self.db.query("SELECT * FROM approvals ORDER BY requested_at")
        for r in rows:
            r["manifest"] = loads(r.pop("manifest_json"))
        return rows

    def grant(self, approval_id: str, *, approver: str, now: _dt.datetime | None = None) -> dict[str, Any]:
        now = now or utcnow()
        row = self.get(approval_id)
        if row["status"] != "pending":
            raise ApprovalError(f"approval {approval_id} is {row['status']}, not pending")
        if parse_iso(row["expires_at"]) <= now:
            with self.db.transaction() as conn:
                conn.execute("UPDATE approvals SET status='expired' WHERE id=?", (approval_id,))
                self.audit.record(approver, "approval.expired", "approval", approval_id, {})
            raise ApprovalExpired(f"approval {approval_id} expired before it was granted")
        with self.db.transaction() as conn:
            conn.execute("UPDATE approvals SET status='granted', approver=?, granted_at=? WHERE id=?", (approver, utcnow_iso(), approval_id))
            self.audit.record(approver, "approval.granted", "approval", approval_id, {"operation": row["operation"], "material_hash": row["material_hash"]})
        return self.get(approval_id)

    def reject(self, approval_id: str, *, approver: str, reason: str) -> dict[str, Any]:
        return self.invalidate(approval_id, reason=f"rejected by {approver}: {reason}", actor=approver)

    def invalidate(self, approval_id: str, *, reason: str, actor: str = "system") -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = self.get(approval_id)
            if row["status"] in ("consumed",):
                raise ApprovalConsumed(f"approval {approval_id} was already consumed")
            conn.execute("UPDATE approvals SET status='invalidated', invalidated_reason=? WHERE id=?", (reason, approval_id))
            self.audit.record(actor, "approval.invalidated", "approval", approval_id, {"reason": reason})
        return self.get(approval_id)

    def consume(self, approval_id: str, *, current_manifest: dict[str, Any], consumer: str, now: _dt.datetime | None = None) -> dict[str, Any]:
        """Atomically consume a granted approval if the current material facts
        still match what the human approved."""
        now = now or utcnow()
        row = self.get(approval_id)
        if row["status"] == "consumed":
            raise ApprovalConsumed(f"approval {approval_id} was already consumed by {row['consumed_by']}")
        if row["status"] == "expired":
            raise ApprovalExpired(f"approval {approval_id} expired")
        if row["status"] != "granted":
            raise ApprovalNotGranted(f"approval {approval_id} is {row['status']}, not granted")
        if parse_iso(row["expires_at"]) <= now:
            # Record the expiry in its own transaction so the fact survives the exception.
            with self.db.transaction() as conn:
                conn.execute("UPDATE approvals SET status='expired' WHERE id=?", (approval_id,))
                self.audit.record(consumer, "approval.expired", "approval", approval_id, {})
            raise ApprovalExpired(f"approval {approval_id} expired")
        current = material_hash(current_manifest)
        if current != row["material_hash"]:
            diff = _diff(material_part(row["manifest"]), material_part(current_manifest))
            with self.db.transaction() as conn:
                conn.execute("UPDATE approvals SET status='invalidated', invalidated_reason=? WHERE id=?", (f"subject changed after approval: {diff}", approval_id))
                self.audit.record(consumer, "approval.invalidated", "approval", approval_id, {"reason": "material change", "diff": diff})
            raise StaleApprovalError(f"approval {approval_id} no longer matches the subject: {diff}")
        with self.db.transaction() as conn:
            # Re-read under the write lock so two concurrent consumers cannot both succeed.
            locked = conn.execute("SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if locked["status"] != "granted":
                raise ApprovalConsumed(f"approval {approval_id} is no longer available: {locked['status']}")
            conn.execute("UPDATE approvals SET status='consumed', consumed_at=?, consumed_by=? WHERE id=?", (utcnow_iso(), consumer, approval_id))
            self.audit.record(consumer, "approval.consumed", "approval", approval_id, {"operation": row["operation"], "material_hash": current})
        return self.get(approval_id)

    def mark_expired(self, approval_id: str, *, actor: str = "system", now: _dt.datetime | None = None) -> dict[str, Any]:
        """Record that a pending or granted approval has passed its expiry.  Used when
        an execution attempt found it expired inside a transaction that rolled back,
        and by sweeps; an approval that has not expired is left unchanged."""
        now = now or utcnow()
        row = self.get(approval_id)
        if row["status"] in ("pending", "granted") and parse_iso(row["expires_at"]) <= now:
            with self.db.transaction() as conn:
                conn.execute("UPDATE approvals SET status='expired' WHERE id=? AND status IN ('pending','granted')", (approval_id,))
                self.audit.record(actor, "approval.expired", "approval", approval_id, {"expires_at": row["expires_at"]})
        return self.get(approval_id)

    def expire_due(self, *, actor: str = "system", now: _dt.datetime | None = None) -> int:
        """Mark every pending or granted approval past its expiry as expired."""
        now = now or utcnow()
        n = 0
        for r in self.db.query("SELECT id, expires_at FROM approvals WHERE status IN ('pending','granted')"):
            if parse_iso(r["expires_at"]) <= now:
                self.mark_expired(r["id"], actor=actor, now=now)
                n += 1
        return n

    def invalidate_for_subject(self, subject_type: str, subject_id: str, *, reason: str, actor: str = "system") -> int:
        """Invalidate every open approval on a subject whose state just changed."""
        rows = self.db.query("SELECT id FROM approvals WHERE subject_type=? AND subject_id=? AND status IN ('pending','granted')", (subject_type, subject_id))
        for r in rows:
            self.invalidate(r["id"], reason=reason, actor=actor)
        return len(rows)


def _diff(before: dict[str, Any], after: dict[str, Any]) -> str:
    changed = []
    for key in MATERIAL_KEYS:
        if before.get(key) != after.get(key):
            changed.append(key)
    return ",".join(changed) or "unknown"
