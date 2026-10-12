"""Ricky: deterministic, role-aware guidance.

Ricky never executes.  Given a workflow and context it either *proposes* a
preview (the exact manifest a human would approve) or *abstains* with a
reason.  Abstention is mandatory when the acting role lacks authority, when
the source evidence is stale, when the period is not open, when a payee
destination is unverified, or when releases are quarantined after a restore.
"""
from __future__ import annotations

from typing import Any

from ..core.audit import Audit
from ..core.db import Database
from ..core.ids import canonical_json, new_id, utcnow_iso
from .bills import Bills
from .commitments import Commitments
from .estimates import Estimates
from .ledger import Ledger
from .payments import Payments
from .receivables import Receivables

ROLE_AUTHORITY: dict[str, set[str]] = {
    "owner": {"*"},
    "estimator": {"estimate.approve"},
    "pm": {"commitment.execute", "change.execute", "bill.approve", "schedule.baseline", "drawing.issue", "reimbursement.bill"},
    "accountant": {"bill.approve", "prime_bill.approve", "period.close", "asset.capitalise", "asset.post_depreciation", "asset.reverse_depreciation", "asset.dispose", "reimbursement.approve", "reimbursement.pay"},
    "treasury": {"payment.release", "payment.release_retainage", "retainage.release", "reimbursement.pay"},
    "viewer": set(),
}


class Ricky:
    def __init__(self, db: Database, audit: Audit, estimates: Estimates, commitments: Commitments, bills: Bills, receivables: Receivables, payments: Payments, ledger: Ledger, plugins=None):
        self.db = db
        self.audit = audit
        self.estimates = estimates
        self.commitments = commitments
        self.bills = bills
        self.receivables = receivables
        self.payments = payments
        self.ledger = ledger
        self._plugins = plugins or (lambda: {})

    def propose(self, workflow: str, *, actor_role: str, context: dict[str, Any]) -> dict[str, Any]:
        try:
            manifest, notes = self._evaluate(workflow, actor_role, context)
        except _Abstain as ab:
            return self._record(workflow, actor_role, context, "abstained", str(ab), None)
        except Exception as exc:  # unknown record, invalid state
            return self._record(workflow, actor_role, context, "abstained", f"cannot evaluate: {exc}", None)
        return self._record(workflow, actor_role, context, "proposed", notes, manifest)

    # ---- evaluation ------------------------------------------------------------ #

    def _require_role(self, actor_role: str, operation: str) -> None:
        allowed = ROLE_AUTHORITY.get(actor_role)
        if allowed is None:
            raise _Abstain(f"unknown role {actor_role!r}; Ricky does not infer authority from the request")
        if "*" not in allowed and operation not in allowed:
            raise _Abstain(f"role {actor_role!r} is not authorised for {operation}; route to a role that is")

    def _evaluate(self, workflow: str, actor_role: str, ctx: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if workflow == "estimate.approve":
            self._require_role(actor_role, workflow)
            est = self.estimates.get(ctx["estimate_id"])
            if est["status"] != "draft":
                raise _Abstain(f"estimate is {est['status']}")
            if est["stale"]:
                raise _Abstain("the estimate's source document was revised after the estimate was priced; re-price before approval")
            return self.estimates.manifest(est["id"], actor_role=actor_role), f"approve estimate revision {est['revision']} for {est['total']}"

        if workflow == "commitment.execute":
            self._require_role(actor_role, workflow)
            c = self.commitments.get(ctx["commitment_id"])
            if c["status"] != "draft":
                raise _Abstain(f"commitment is {c['status']}")
            if c["estimate"]:
                if c["estimate"]["stale"]:
                    raise _Abstain("the commitment's estimate is priced from a superseded document revision; revise the estimate first")
                if c["estimate"]["status"] != "approved":
                    raise _Abstain("the estimate behind this commitment has not been approved")
            if not c["supplier"]["destination_verified"]:
                raise _Abstain("supplier payment destination is not independently verified")
            return self.commitments.manifest(c["id"], actor_role=actor_role), f"execute {c['title']} for {c['original_amount']} with {c['supplier']['name']}"

        if workflow == "change.execute":
            self._require_role(actor_role, workflow)
            ch = self.commitments.change(ctx["change_id"])
            if ch["status"] not in ("pending", "approved"):
                raise _Abstain(f"change is {ch['status']}")
            return self.commitments.change_manifest(ch["id"], actor_role=actor_role), f"execute change of {ch['amount']}: {ch['reason']}"

        if workflow == "bill.approve":
            self._require_role(actor_role, workflow)
            b = self.bills.get(ctx["bill_id"])
            if b["status"] != "draft":
                raise _Abstain(f"bill is {b['status']}")
            if b["stale"]:
                raise _Abstain("the commitment changed after this bill was certified; re-certify")
            if self.ledger.period(b["period_id"])["status"] != "open":
                raise _Abstain("the bill's period is not open")
            return self.bills.manifest(b["id"], actor_role=actor_role), f"approve supplier bill {b['sequence']}: {b['amount_due']} due, {b['retainage_this_period']} retained"

        if workflow == "prime_bill.approve":
            self._require_role(actor_role, workflow)
            b = self.receivables.get(ctx["prime_bill_id"])
            if b["status"] != "draft":
                raise _Abstain(f"prime bill is {b['status']}")
            return self.receivables.manifest(b["id"], actor_role=actor_role), f"approve prime bill {b['sequence']}: {b['amount_due']} due"

        if workflow == "payment.release":
            self._require_role(actor_role, workflow)
            ok, why = self.payments.release_allowed()
            if not ok:
                raise _Abstain(why)
            if "bill_id" in ctx:
                m = self.payments.manifest_for_bill(ctx["bill_id"], actor_role=actor_role)
            else:
                m = self.payments.manifest_for_retainage(ctx["commitment_id"], actor_role=actor_role)
            if not m["bindings"].get("destination_verified"):
                raise _Abstain("payee destination has not been independently verified")
            return m, f"release {m['amounts']['amount']} to {m['destination']['party_id']}"

        if workflow == "retainage.release":
            self._require_role(actor_role, workflow)
            c = self.commitments.get(ctx["commitment_id"])
            if c["status"] != "closed":
                raise _Abstain("retainage is released only after closeout acceptance (commitment closed)")
            return self.bills.retainage_manifest(c["id"], actor_role=actor_role), "release withheld retainage to ordinary payables"

        # v2 plugin operations: the plugin builds the manifest from current state and
        # raises if the subject is not in a proposable state; Ricky still gates the role.
        prefix = workflow.split(".")[0]
        plugin = self._plugins().get(prefix)
        if plugin is not None and hasattr(plugin, "manifest_for"):
            self._require_role(actor_role, workflow)
            subject_id = ctx.get("subject_id") or next((v for k, v in ctx.items() if k.endswith("_id")), None)
            if not subject_id:
                raise _Abstain("no subject id supplied")
            if self.payments.release_allowed()[0] is False and workflow.endswith(".pay"):
                raise _Abstain(self.payments.release_allowed()[1])
            manifest = plugin.manifest_for(workflow, subject_id, actor_role=actor_role)
            amounts = ", ".join(f"{k} {v}" for k, v in (manifest.get("amounts") or {}).items())
            return manifest, f"{workflow} on {subject_id}{(' for ' + amounts) if amounts else ''}"

        raise _Abstain(f"unknown workflow {workflow!r}")

    # ---- record ------------------------------------------------------------------ #

    def _record(self, workflow: str, actor_role: str, ctx: dict[str, Any], decision: str, reason: str, manifest: dict[str, Any] | None) -> dict[str, Any]:
        pid = new_id("rky")
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO ricky_proposals (id, workflow, actor_role, context_json, decision, reason, manifest_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (pid, workflow, actor_role, canonical_json(ctx), decision, reason, canonical_json(manifest) if manifest else None, utcnow_iso()),
            )
            self.audit.record("ricky", f"ricky.{decision}", "ricky_proposal", pid, {"workflow": workflow, "actor_role": actor_role, "reason": reason})
        return {"id": pid, "workflow": workflow, "actor_role": actor_role, "decision": decision, "reason": reason, "manifest": manifest}

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.query("SELECT id, workflow, actor_role, decision, reason, created_at FROM ricky_proposals ORDER BY created_at DESC LIMIT ?", (limit,))


class _Abstain(Exception):
    pass
