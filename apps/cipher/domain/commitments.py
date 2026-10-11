"""Commitments (subcontracts / purchase orders), schedules of values and changes.

A commitment is executed only through a consumed approval that binds the
supplier, its verified destination version, the estimate it came from and the
exact SOV.  A pending change only affects the forecast; the authorised
commitment changes only when the change itself is approved and executed, which
bumps the commitment version and therefore invalidates any open bill approval.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..core.approvals import build_manifest
from ..core.audit import Audit
from ..core.db import Database
from ..core.ids import hash_json, new_id, utcnow_iso
from ..core.money import ZERO, fmt, money, rate, total
from .estimates import Estimates


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
        supplier = self.db.one("SELECT * FROM parties WHERE id=? AND kind='supplier'", (supplier_id,))
        if supplier is None:
            raise CommitmentError(f"unknown supplier {supplier_id}")
        if estimate_id:
            est = self.estimates.get(estimate_id)
            if est["project_id"] != project_id:
                raise CommitmentError("estimate belongs to another project")
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

    # ---- execution --------------------------------------------------------- #

    def manifest(self, commitment_id: str, *, actor_role: str) -> dict[str, Any]:
        c = self.get(commitment_id)
        bindings = {
            "commitment_version": c["version"],
            "sov_hash": self.sov_hash(commitment_id),
            "supplier_id": c["supplier_id"],
            "retainage_rate": c["retainage_rate"],
        }
        if c["estimate"]:
            bindings.update({"estimate_id": c["estimate"]["id"], "estimate_hash": c["estimate"]["content_hash"], "estimate_stale": c["estimate"]["stale"]})
        return build_manifest(
            operation="commitment.execute",
            subject_type="commitment",
            subject_id=commitment_id,
            actor_role=actor_role,
            amounts={"total": c["original_amount"]},
            bindings=bindings,
            destination={"party_id": c["supplier_id"], "destination": c["supplier"]["destination"], "destination_version": c["supplier"]["destination_version"]},
        )

    def execute(self, commitment_id: str, *, approval_id: str, actor: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            c = self.get(commitment_id)
            if c["status"] != "draft":
                raise CommitmentError(f"commitment {commitment_id} is {c['status']}")
            if c["estimate"] and c["estimate"]["stale"]:
                raise CommitmentError("the commitment's estimate is priced from a superseded document; revise the estimate first")
            conn.execute(
                "UPDATE commitments SET status='executed', executed_amount=original_amount, approval_id=?, version=version+1, executed_at=? WHERE id=?",
                (approval_id, utcnow_iso(), commitment_id),
            )
            self.audit.record(actor, "commitment.executed", "commitment", commitment_id, {"approval_id": approval_id, "amount": c["original_amount"], "version": c["version"] + 1})
        return self.get(commitment_id)

    # ---- changes ----------------------------------------------------------- #

    def propose_change(self, commitment_id: str, *, amount: str | Decimal, reason: str, sov_line_id: str | None = None, actor: str) -> dict[str, Any]:
        amt = money(amount)
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

    def change_manifest(self, change_id: str, *, actor_role: str) -> dict[str, Any]:
        ch = self.change(change_id)
        c = self.get(ch["commitment_id"])
        return build_manifest(
            operation="change.execute",
            subject_type="change",
            subject_id=change_id,
            actor_role=actor_role,
            amounts={"change": ch["amount"], "resulting_commitment": fmt(money(c["executed_amount"]) + money(ch["amount"]))},
            bindings={"commitment_id": c["id"], "commitment_version": c["version"], "change_version": ch["version"], "sov_line_id": ch["sov_line_id"], "reason": ch["reason"]},
            destination={"party_id": c["supplier_id"], "destination": c["supplier"]["destination"], "destination_version": c["supplier"]["destination_version"]},
        )

    def execute_change(self, change_id: str, *, approval_id: str, actor: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            ch = self.change(change_id)
            if ch["status"] not in ("pending", "approved"):
                raise CommitmentError(f"change {change_id} is {ch['status']}")
            c = self.get(ch["commitment_id"])
            amt = money(ch["amount"])
            if ch["sov_line_id"]:
                line = next(s for s in c["sov"] if s["id"] == ch["sov_line_id"])
                new_amount = money(line["amount"]) + amt
                if new_amount < 0:
                    raise CommitmentError("change would make the SOV line negative")
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
            conn.execute("UPDATE changes SET status='rejected' WHERE id=?", (change_id,))
            self.audit.record(actor, "change.rejected", "change", change_id, {"reason": reason})
        return self.change(change_id)

    def close(self, commitment_id: str, *, actor: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            c = self.get(commitment_id)
            if c["status"] != "executed":
                raise CommitmentError("only executed commitments close")
            conn.execute("UPDATE commitments SET status='closed', closed_at=?, version=version+1 WHERE id=?", (utcnow_iso(), commitment_id))
            self.audit.record(actor, "commitment.closed", "commitment", commitment_id, {})
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
