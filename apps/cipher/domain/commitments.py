"""Commitments (subcontracts / purchase orders), schedules of values and changes.

A commitment is executed only through a consumed approval that binds the
supplier, its verified destination version, the estimate it came from, the
exact SOV, and the project's legal entity and currency.  ``execute`` and
``execute_change`` themselves refuse to run without that approval: it must be
consumed, cover the same operation and subject, never have taken effect
before, and its material facts must still equal the manifest rebuilt from the
current commitment / change (version, status, SOV, amounts, entity, currency,
destination).  A direct call can therefore never execute what no human saw.

A pending change only affects the forecast; the authorized commitment changes
only when the change itself is approved and executed, which bumps the
commitment version and therefore invalidates any open bill approval.

Per-line cap: cumulative installed value plus remaining stored material on an
SOV line may never exceed the line amount.  Bills enforce it when material is
stored and when work is certified; a deductive change enforces it here, so a
line can never be reduced below what is already installed and stored on it.

Closing (``close``) is the low-level close.  It refuses while a draft supplier
bill, remaining stored material (billed or not) or a pending change is open on
the commitment, and while a field closeout for the commitment exists but has
not been accepted through ``field.accept_closeout`` (the field module calls
``close`` from inside that acceptance).  Interactive surfaces close only through
the accepted closeout (``Cipher.close_commitment``); fixtures may close a
commitment that never had a field closeout, and the closure record says which
basis applied.  Every close writes an append-only closure record first; the
database refuses a commitment status of ``closed`` without one and refuses any
change to a closed commitment, so a raw status edit can neither close nor
reopen it.  Retainage release (``bills``) requires the closure record.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..core.approvals import build_manifest, material_hash
from ..core.audit import Audit
from ..core.db import Database, register_schema_version
from ..core.ids import hash_json, loads, new_id, utcnow_iso
from ..core.money import ZERO, fmt, money, rate, total
from .estimates import Estimates, EstimateError

# The approval that accepts a commitment's closeout (owned by the field module).
CLOSEOUT_OPERATION = "field.accept_closeout"

# Append-only schema entry: closure records and the closed-status guards.  Never
# edit these statements once applied; add a new uniquely named entry instead.
COMMITMENTS_SCHEMA_NAME = "commitment_closure_controls"
COMMITMENTS_SCHEMA_STATEMENTS = [
    """CREATE TABLE commitment_closures (
        commitment_id TEXT PRIMARY KEY REFERENCES commitments(id),
        commitment_version INTEGER NOT NULL,
        basis TEXT NOT NULL CHECK (basis IN ('closeout_accepted','direct','legacy')),
        closeout_approval_id TEXT REFERENCES approvals(id),
        closed_by TEXT NOT NULL CHECK (length(trim(closed_by)) > 0),
        closed_at TEXT NOT NULL,
        CHECK ((basis = 'closeout_accepted') = (closeout_approval_id IS NOT NULL))
    )""",
    # commitments closed before closure records existed (before the guards below)
    """INSERT INTO commitment_closures (commitment_id, commitment_version, basis, closeout_approval_id, closed_by, closed_at)
        SELECT id, version, 'legacy', NULL, 'legacy', COALESCE(closed_at, created_at) FROM commitments WHERE status = 'closed'""",
    "CREATE TRIGGER commitment_closures_no_update BEFORE UPDATE ON commitment_closures BEGIN SELECT RAISE(ABORT, 'commitment closure records are append-only'); END",
    "CREATE TRIGGER commitment_closures_no_delete BEFORE DELETE ON commitment_closures BEGIN SELECT RAISE(ABORT, 'commitment closure records are append-only'); END",
    """CREATE TRIGGER commitment_closures_executed_only BEFORE INSERT ON commitment_closures
        WHEN (SELECT status FROM commitments WHERE id = NEW.commitment_id) IS NOT 'executed'
        BEGIN SELECT RAISE(ABORT, 'only an executed commitment is closed'); END""",
    """CREATE TRIGGER commitments_closed_needs_closure BEFORE UPDATE OF status ON commitments
        WHEN NEW.status = 'closed' AND OLD.status IS NOT 'closed'
          AND NOT EXISTS (SELECT 1 FROM commitment_closures WHERE commitment_id = NEW.id)
        BEGIN SELECT RAISE(ABORT, 'a commitment is closed only through Commitments.close (closure record required)'); END""",
    """CREATE TRIGGER commitments_closed_immutable BEFORE UPDATE ON commitments
        WHEN OLD.status = 'closed' AND (
          NEW.status IS NOT OLD.status OR NEW.executed_amount IS NOT OLD.executed_amount OR NEW.original_amount IS NOT OLD.original_amount
          OR NEW.version IS NOT OLD.version OR NEW.retainage_rate IS NOT OLD.retainage_rate OR NEW.supplier_id IS NOT OLD.supplier_id
          OR NEW.project_id IS NOT OLD.project_id OR NEW.approval_id IS NOT OLD.approval_id OR NEW.closed_at IS NOT OLD.closed_at)
        BEGIN SELECT RAISE(ABORT, 'a closed commitment is immutable'); END""",
]
register_schema_version(COMMITMENTS_SCHEMA_NAME, COMMITMENTS_SCHEMA_STATEMENTS)


class CommitmentError(RuntimeError):
    pass


class Commitments:
    def __init__(self, db: Database, audit: Audit, estimates: Estimates):
        self.db = db
        self.audit = audit
        self.estimates = estimates

    # ---- creation ---------------------------------------------------------- #

    def create(
        self,
        *,
        project_id: str,
        supplier_id: str,
        title: str,
        sov_lines: list[dict[str, Any]],
        retainage_rate: str | Decimal = "0.10",
        estimate_id: str | None = None,
        actor: str,
    ) -> dict[str, Any]:
        if not sov_lines:
            raise CommitmentError("a commitment needs at least one SOV line")
        self._scope(project_id)  # the project must exist
        supplier = self.db.one("SELECT * FROM parties WHERE id=? AND kind='supplier'", (supplier_id,))
        if supplier is None:
            raise CommitmentError(f"unknown supplier {supplier_id}")
        if estimate_id:
            est = self.estimates.get(estimate_id)
            if est["project_id"] != project_id:
                raise CommitmentError("estimate belongs to another project")
        for idx, ln in enumerate(sov_lines, start=1):
            if not isinstance(ln, dict) or "amount" not in ln or "description" not in ln:
                raise CommitmentError(f"SOV line {idx} needs a description and an amount")
        amounts = [money(ln["amount"]) for ln in sov_lines]
        if any(a < 0 for a in amounts):
            raise CommitmentError("negative SOV line")
        original = total(amounts)
        cid = new_id("cmt")
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO commitments (id, project_id, supplier_id, estimate_id, title, status, original_amount, executed_amount, retainage_rate, version, created_at)
                   VALUES (?,?,?,?,?,'draft',?,?,?,1,?)""",
                (cid, project_id, supplier_id, estimate_id, title, fmt(original), fmt(original), f"{rate(retainage_rate):f}", utcnow_iso()),
            )
            for idx, (ln, amt) in enumerate(zip(sov_lines, amounts), start=1):
                conn.execute(
                    "INSERT INTO sov_lines (id, commitment_id, line_no, description, cost_code, amount) VALUES (?,?,?,?,?,?)",
                    (new_id("sov"), cid, idx, str(ln["description"]), str(ln.get("cost_code", "")), fmt(amt)),
                )
            self.audit.record(actor, "commitment.created", "commitment", cid, {"project_id": project_id, "supplier_id": supplier_id, "estimate_id": estimate_id, "original_amount": fmt(original)})
        return self.get(cid)

    # ---- reading ----------------------------------------------------------- #

    def get(self, commitment_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM commitments WHERE id=?", (commitment_id,))
        if row is None:
            raise CommitmentError(f"unknown commitment {commitment_id}")
        row["sov"] = self.db.query("SELECT * FROM sov_lines WHERE commitment_id=? ORDER BY line_no", (commitment_id,))
        row["changes"] = self.db.query("SELECT * FROM changes WHERE commitment_id=? ORDER BY created_at", (commitment_id,))
        row["pending_exposure"] = fmt(total(c["amount"] for c in row["changes"] if c["status"] in ("pending", "approved")))
        row["sov_total"] = fmt(total(s["amount"] for s in row["sov"]))
        supplier = self.db.one("SELECT * FROM parties WHERE id=?", (row["supplier_id"],))
        row["supplier"] = supplier
        if row["estimate_id"]:
            est = self.estimates.get(row["estimate_id"])
            row["estimate"] = {"id": est["id"], "revision": est["revision"], "content_hash": est["content_hash"], "status": est["status"], "stale": est["stale"], "total": est["total"]}
        else:
            row["estimate"] = None
        return row

    def list(self, project_id: str) -> list[dict[str, Any]]:
        return [self.get(r["id"]) for r in self.db.query("SELECT id FROM commitments WHERE project_id=? ORDER BY created_at", (project_id,))]

    def sov_hash(self, commitment_id: str) -> str:
        rows = self.db.query("SELECT line_no, description, cost_code, amount FROM sov_lines WHERE commitment_id=? ORDER BY line_no", (commitment_id,))
        return hash_json(rows)

    def _scope(self, project_id: str) -> dict[str, str]:
        """The legal entity and currency an approval on this project's records binds."""
        row = self.db.one("SELECT entity, currency FROM projects WHERE id=?", (project_id,))
        if row is None:
            raise CommitmentError(f"unknown project {project_id}")
        return {"entity": row["entity"], "currency": row["currency"] or "USD"}

    def line_billed(self, sov_line_id: str) -> Decimal:
        """Value already claimed on an SOV line: cumulative installed on the latest
        non-void bill that carries the line, plus the remaining stored material on it."""
        row = self.db.one(
            """SELECT bl.cumulative_installed FROM bill_lines bl JOIN bills b ON b.id = bl.bill_id
               WHERE bl.sov_line_id=? AND b.status != 'void' ORDER BY b.sequence DESC LIMIT 1""",
            (sov_line_id,),
        )
        installed = money(row["cumulative_installed"]) if row else ZERO
        lots = self.db.query("SELECT remaining_amount FROM stored_material_lots WHERE sov_line_id=?", (sov_line_id,))
        stored = total(l["remaining_amount"] for l in lots) if lots else ZERO
        return money(installed + stored)

    def closure(self, commitment_id: str) -> dict[str, Any] | None:
        """The append-only closure record written when the commitment closed (None while open)."""
        return self.db.one("SELECT * FROM commitment_closures WHERE commitment_id=?", (commitment_id,))

    # ---- approvals ---------------------------------------------------------- #

    def _consumed_approval(self, approval_id: Any, operation: str, subject_type: str, subject_id: str, *, used_sql: str) -> dict[str, Any]:
        """The manifest of the approval the executing command has just consumed.

        ``Cipher.execute`` consumes the approval and applies it in one transaction;
        a direct call with no approval, another operation's or subject's approval, an
        approval that is not consumed, or one whose effect is already on record
        (``used_sql`` finds it) is refused."""
        if not isinstance(approval_id, str) or not approval_id.strip():
            raise CommitmentError(f"{operation} on {subject_id} runs only against its own consumed approval; none was given")
        row = self.db.one("SELECT operation, subject_type, subject_id, status, manifest_json FROM approvals WHERE id=?", (approval_id,))
        if row is None:
            raise CommitmentError(f"unknown approval {approval_id}")
        if (row["operation"], row["subject_type"], row["subject_id"]) != (operation, subject_type, subject_id):
            raise CommitmentError(f"approval {approval_id} covers {row['operation']} on {row['subject_id']}, not {operation} on {subject_id}")
        if row["status"] != "consumed":
            raise CommitmentError(f"approval {approval_id} is {row['status']}; it must be consumed by the executing command")
        used = self.db.one(used_sql, (approval_id,))
        if used is not None:
            raise CommitmentError(f"approval {approval_id} already took effect on {used['id']}; an approval takes effect once")
        return loads(row["manifest_json"]) or {}

    @staticmethod
    def _require_unchanged(approved: dict[str, Any], current: dict[str, Any], what: str) -> None:
        """The approved material facts must equal the manifest rebuilt from current state."""
        if material_hash(approved) != material_hash(current):
            changed = [k for k in ("entity", "currency", "amounts", "bindings", "destination", "actor_role") if approved.get(k) != current.get(k)]
            raise CommitmentError(f"{what} changed after it was approved ({', '.join(changed) or 'material facts'}); request a new approval")

    # ---- execution --------------------------------------------------------- #

    def manifest(self, commitment_id: str, *, actor_role: str) -> dict[str, Any]:
        c = self.get(commitment_id)
        bindings = {
            "commitment_version": c["version"],
            "commitment_status": c["status"],
            "project_id": c["project_id"],
            "sov_hash": self.sov_hash(commitment_id),
            "supplier_id": c["supplier_id"],
            "retainage_rate": c["retainage_rate"],
        }
        if c["estimate"]:
            # Retain stale manifests as review diagnostics for existing grants;
            # a current source must already have genuine acceptance provenance.
            if not c["estimate"]["stale"]:
                try:
                    self.estimates.baseline_proof(c["estimate"]["id"], require_current=True, require_accepted=True)
                except EstimateError as exc:
                    raise CommitmentError("the commitment source estimate is not genuinely accepted") from exc
            bindings.update({"estimate_id": c["estimate"]["id"], "estimate_hash": c["estimate"]["content_hash"], "estimate_stale": c["estimate"]["stale"]})
        return build_manifest(
            operation="commitment.execute",
            subject_type="commitment",
            subject_id=commitment_id,
            actor_role=actor_role,
            amounts={"total": c["original_amount"]},
            bindings=bindings,
            destination={"party_id": c["supplier_id"], "destination": c["supplier"]["destination"], "destination_version": c["supplier"]["destination_version"]},
            **self._scope(c["project_id"]),
        )

    def execute(self, commitment_id: str, *, approval_id: str, actor: str) -> dict[str, Any]:
        """Execute a draft commitment against its own consumed ``commitment.execute`` approval."""
        with self.db.transaction() as conn:
            c = self.get(commitment_id)
            if c["status"] != "draft":
                raise CommitmentError(f"commitment {commitment_id} is {c['status']}")
            if c["estimate"] and c["estimate"]["stale"]:
                raise CommitmentError("the commitment's estimate is priced from a superseded document; revise the estimate first")
            if c["estimate"]:
                try:
                    self.estimates.baseline_proof(c["estimate"]["id"], require_current=True, require_accepted=True)
                except EstimateError as exc:
                    raise CommitmentError("the commitment source estimate is not genuinely accepted") from exc
            approved = self._consumed_approval(approval_id, "commitment.execute", "commitment", commitment_id,
                                               used_sql="SELECT id FROM commitments WHERE approval_id=?")
            self._require_unchanged(approved, self.manifest(commitment_id, actor_role=approved.get("actor_role", "")), f"commitment {commitment_id}")
            conn.execute(
                "UPDATE commitments SET status='executed', executed_amount=original_amount, approval_id=?, version=version+1, executed_at=? WHERE id=?",
                (approval_id, utcnow_iso(), commitment_id),
            )
            self.audit.record(actor, "commitment.executed", "commitment", commitment_id, {"approval_id": approval_id, "amount": c["original_amount"], "version": c["version"] + 1})
        return self.get(commitment_id)

    # ---- changes ----------------------------------------------------------- #

    def propose_change(self, commitment_id: str, *, amount: str | Decimal, reason: str, sov_line_id: str | None = None, actor: str) -> dict[str, Any]:
        amt = money(amount)
        if amt == 0:
            raise CommitmentError("a change must carry a non-zero amount")
        if not isinstance(reason, str):
            raise CommitmentError("a change reason must be text")
        with self.db.transaction() as conn:
            c = self.get(commitment_id)
            if c["status"] != "executed":
                raise CommitmentError("changes apply only to executed commitments")
            if sov_line_id and not any(s["id"] == sov_line_id for s in c["sov"]):
                raise CommitmentError("SOV line does not belong to this commitment")
            if sov_line_id is None and amt < 0:
                raise CommitmentError("a deductive change must name the SOV line it reduces")
            ch_id = new_id("chg")
            conn.execute(
                "INSERT INTO changes (id, commitment_id, sov_line_id, amount, reason, status, version, created_at) VALUES (?,?,?,?,?,'pending',1,?)",
                (ch_id, commitment_id, sov_line_id, fmt(amt), reason, utcnow_iso()),
            )
            self.audit.record(actor, "change.proposed", "change", ch_id, {"commitment_id": commitment_id, "amount": fmt(amt), "reason": reason})
        return self.change(ch_id)

    def change(self, change_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM changes WHERE id=?", (change_id,))
        if row is None:
            raise CommitmentError(f"unknown change {change_id}")
        return row

    def _check_line_reduction(self, c: dict[str, Any], ch: dict[str, Any]) -> None:
        """A change may never take an SOV line negative or below the value already
        installed and stored on it (the per-line cap, seen from the commitment side)."""
        if not ch["sov_line_id"]:
            return
        line = next((s for s in c["sov"] if s["id"] == ch["sov_line_id"]), None)
        if line is None:
            raise CommitmentError(f"SOV line {ch['sov_line_id']} no longer belongs to commitment {c['id']}")
        new_amount = money(line["amount"]) + money(ch["amount"])
        if new_amount < 0:
            raise CommitmentError(f"change would make SOV line {line['line_no']} negative ({fmt(new_amount)})")
        if money(ch["amount"]) < 0:
            claimed = self.line_billed(line["id"])
            if new_amount < claimed:
                raise CommitmentError(
                    f"change would reduce SOV line {line['line_no']} to {fmt(new_amount)}, below the {fmt(claimed)} already installed and stored on it"
                )

    def change_manifest(self, change_id: str, *, actor_role: str) -> dict[str, Any]:
        ch = self.change(change_id)
        c = self.get(ch["commitment_id"])
        if ch["status"] in ("pending", "approved"):
            self._check_line_reduction(c, ch)  # refuse a request that could never execute
        return build_manifest(
            operation="change.execute",
            subject_type="change",
            subject_id=change_id,
            actor_role=actor_role,
            amounts={"change": ch["amount"], "resulting_commitment": fmt(money(c["executed_amount"]) + money(ch["amount"]))},
            bindings={
                "commitment_id": c["id"], "commitment_version": c["version"], "commitment_status": c["status"], "project_id": c["project_id"],
                "sov_hash": self.sov_hash(c["id"]), "change_version": ch["version"], "change_status": ch["status"],
                "sov_line_id": ch["sov_line_id"], "reason": ch["reason"],
            },
            destination={"party_id": c["supplier_id"], "destination": c["supplier"]["destination"], "destination_version": c["supplier"]["destination_version"]},
            **self._scope(c["project_id"]),
        )

    def execute_change(self, change_id: str, *, approval_id: str, actor: str) -> dict[str, Any]:
        """Execute a pending change against its own consumed ``change.execute`` approval."""
        with self.db.transaction() as conn:
            ch = self.change(change_id)
            if ch["status"] not in ("pending", "approved"):
                raise CommitmentError(f"change {change_id} is {ch['status']}")
            c = self.get(ch["commitment_id"])
            if c["status"] != "executed":
                raise CommitmentError(f"commitment {c['id']} is {c['status']}; changes execute only on an executed commitment")
            approved = self._consumed_approval(approval_id, "change.execute", "change", change_id,
                                               used_sql="SELECT id FROM changes WHERE approval_id=?")
            self._require_unchanged(approved, self.change_manifest(change_id, actor_role=approved.get("actor_role", "")), f"change {change_id}")
            amt = money(ch["amount"])
            self._check_line_reduction(c, ch)
            if ch["sov_line_id"]:
                line = next(s for s in c["sov"] if s["id"] == ch["sov_line_id"])
                new_amount = money(line["amount"]) + amt
                conn.execute("UPDATE sov_lines SET amount=? WHERE id=?", (fmt(new_amount), ch["sov_line_id"]))
            else:
                next_no = max(s["line_no"] for s in c["sov"]) + 1
                conn.execute(
                    "INSERT INTO sov_lines (id, commitment_id, line_no, description, cost_code, amount) VALUES (?,?,?,?,?,?)",
                    (new_id("sov"), c["id"], next_no, f"Change: {ch['reason']}", "", fmt(amt)),
                )
            conn.execute("UPDATE changes SET status='executed', approval_id=?, executed_at=? WHERE id=?", (approval_id, utcnow_iso(), change_id))
            conn.execute(
                "UPDATE commitments SET executed_amount=?, version=version+1 WHERE id=?",
                (fmt(money(c["executed_amount"]) + amt), c["id"]),
            )
            self.audit.record(actor, "change.executed", "change", change_id, {"commitment_id": c["id"], "amount": fmt(amt), "approval_id": approval_id, "commitment_version": c["version"] + 1})
        return self.change(change_id)

    def reject_change(self, change_id: str, *, actor: str, reason: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            ch = self.change(change_id)
            if ch["status"] == "executed":
                raise CommitmentError("an executed change cannot be rejected; propose a deductive change instead")
            if ch["status"] == "rejected":
                raise CommitmentError(f"change {change_id} was already rejected")
            conn.execute("UPDATE changes SET status='rejected' WHERE id=?", (change_id,))
            self.audit.record(actor, "change.rejected", "change", change_id, {"reason": reason})
        return self.change(change_id)

    # ---- closing ------------------------------------------------------------ #

    def _closeout_basis(self, commitment_id: str) -> tuple[str, str | None]:
        """('closeout_accepted', approval) when the field closeout was accepted through its
        consumed approval, ('direct', None) when the commitment never had a field closeout.
        A closeout that exists but is not accepted refuses the close."""
        if self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='field_closeouts'") is None:
            return "direct", None
        co = self.db.one("SELECT status, approval_id FROM field_closeouts WHERE commitment_id=?", (commitment_id,))
        if co is None:
            return "direct", None
        if co["status"] != "accepted" or not co["approval_id"]:
            raise CommitmentError(
                f"commitment {commitment_id} has a field closeout that is {co['status']}; it closes only when that closeout is accepted ({CLOSEOUT_OPERATION})"
            )
        ap = self.db.one("SELECT status, operation, subject_id FROM approvals WHERE id=?", (co["approval_id"],))
        if ap is None or ap["status"] != "consumed" or ap["operation"] != CLOSEOUT_OPERATION or ap["subject_id"] != commitment_id:
            raise CommitmentError(f"the closeout of commitment {commitment_id} does not rest on a consumed {CLOSEOUT_OPERATION} approval")
        return "closeout_accepted", co["approval_id"]

    def close(self, commitment_id: str, *, actor: str) -> dict[str, Any]:
        """Close an executed commitment once nothing is left open on it (see the module
        docstring).  Writes the append-only closure record, then the status."""
        if not isinstance(actor, str) or not actor.strip():
            raise CommitmentError("closing a commitment requires an actor")
        with self.db.transaction() as conn:
            c = self.get(commitment_id)
            if c["status"] != "executed":
                raise CommitmentError("only executed commitments close")
            drafts = conn.execute("SELECT id, sequence FROM bills WHERE commitment_id=? AND status IN ('draft','approved') ORDER BY sequence", (commitment_id,)).fetchall()
            if drafts:
                raise CommitmentError(f"commitment {commitment_id} has draft supplier bill(s) {', '.join(str(d['sequence']) for d in drafts)}; post or void them before closing")
            stored = [r for r in conn.execute("SELECT id, remaining_amount FROM stored_material_lots WHERE commitment_id=? ORDER BY created_at, id", (commitment_id,)).fetchall()
                      if money(r["remaining_amount"]) > 0]
            if stored:
                raise CommitmentError(
                    f"commitment {commitment_id} still carries stored material on lot(s) {', '.join(r['id'] for r in stored)} "
                    f"({fmt(total(r['remaining_amount'] for r in stored))}); transfer it to installed or withdraw it before closing"
                )
            pending = [ch for ch in c["changes"] if ch["status"] in ("pending", "approved")]
            if pending:
                raise CommitmentError(f"commitment {commitment_id} has {len(pending)} pending change(s); execute or reject them before closing")
            basis, closeout_approval = self._closeout_basis(commitment_id)
            now = utcnow_iso()
            conn.execute(
                "INSERT INTO commitment_closures (commitment_id, commitment_version, basis, closeout_approval_id, closed_by, closed_at) VALUES (?,?,?,?,?,?)",
                (commitment_id, c["version"] + 1, basis, closeout_approval, actor.strip(), now),
            )
            conn.execute("UPDATE commitments SET status='closed', closed_at=?, version=version+1 WHERE id=?", (now, commitment_id))
            self.audit.record(actor, "commitment.closed", "commitment", commitment_id, {
                "version": c["version"] + 1, "basis": basis, "closeout_approval_id": closeout_approval, "executed_amount": c["executed_amount"],
            })
        return self.get(commitment_id)

    def pending_exposure(self, project_id: str) -> Decimal:
        rows = self.db.query(
            "SELECT ch.amount FROM changes ch JOIN commitments c ON c.id = ch.commitment_id WHERE c.project_id=? AND ch.status IN ('pending','approved')",
            (project_id,),
        )
        return total(r["amount"] for r in rows) if rows else ZERO

    def executed_total(self, project_id: str) -> Decimal:
        rows = self.db.query("SELECT executed_amount FROM commitments WHERE project_id=? AND status IN ('executed','closed')", (project_id,))
        return total(r["executed_amount"] for r in rows) if rows else ZERO
