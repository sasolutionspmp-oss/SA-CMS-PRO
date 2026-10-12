"""Ricky: deterministic, role-aware guidance.

Ricky never executes.  Given a workflow and context it either *proposes* a
preview (the exact manifest a human would approve) or *abstains* with a
reason.  Abstention is mandatory when the acting role lacks authority, when
the source evidence is stale, when the period is not open, when a payee
destination is unverified, or when releases are quarantined after a restore.
"""
from __future__ import annotations

import json
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
    "pm": {
        "commitment.execute", "change.execute", "bill.approve", "schedule.baseline", "drawing.issue", "reimbursement.bill",
        "labor.approve_timesheet", "procurement.award", "field.respond_rfi", "field.decide_submittal", "field.accept_closeout",
        "field.distribute_rfi", "prime_bill.send", "budget.revise", "contract.approve_agreement",
    },
    # plan section 10 step 1: a PM/legal reviewer approves the exact agreement; an authorised signer executes it
    "legal": {"contract.approve_agreement"},
    "signer": {"contract.sign"},
    "accountant": {
        "bill.approve", "prime_bill.approve", "period.close", "asset.capitalise", "asset.post_depreciation", "asset.reverse_depreciation",
        "asset.dispose", "reimbursement.approve", "reimbursement.pay", "banking.post_fee", "banking.lock_reconciliation",
        "close.close_period", "close.reopen_period", "close.lock_period", "close.post_wip_adjustment", "close.reverse_wip_adjustment",
        "labor.post_payroll", "labor.bill", "prime_bill.send", "prime_retainage.release", "journal.reverse", "handoff.acknowledge",
        "retainage.release", "ap_intake.match_invoice", "bill.credit_note", "bill.correct", "prime_bill.credit_memo",
        "receivable.apply_deposit",
    },
    "controller": {
        "bill.approve", "prime_bill.approve", "period.close", "close.close_period", "close.reopen_period", "close.lock_period",
        "close.post_wip_adjustment", "close.reverse_wip_adjustment", "journal.reverse", "banking.lock_reconciliation", "banking.post_fee",
        "labor.post_payroll", "labor.bill", "handoff.acknowledge", "prime_retainage.release", "asset.capitalise", "asset.post_depreciation",
        "asset.reverse_depreciation", "asset.dispose", "reimbursement.approve", "retainage.release",
        "ap_intake.match_invoice", "bill.credit_note", "bill.correct", "prime_bill.credit_memo", "receivable.write_off",
        "receivable.apply_deposit", "budget.revise",
    },
    "reconciler": {"banking.lock_reconciliation", "banking.post_fee"},
    # the plan separates the bank-detail maintainer from treasury release
    "bank_admin": {"party.verify_destination"},
    "treasury": {"payment.release", "payment.release_retainage", "retainage.release", "reimbursement.pay", "payment.resume_releases", "labor.post_payroll"},
    "viewer": set(),
}


BRIEF_LEVELS = ("blocker", "decide", "execute", "reconcile", "review", "info")


class Ricky:
    def __init__(self, db: Database, audit: Audit, estimates: Estimates, commitments: Commitments, bills: Bills, receivables: Receivables, payments: Payments, ledger: Ledger, plugins=None, forecast=None, core_owner=None):
        self._core_owner = core_owner or (lambda op: None)
        self.db = db
        self.audit = audit
        self.estimates = estimates
        self.commitments = commitments
        self.bills = bills
        self.receivables = receivables
        self.payments = payments
        self.ledger = ledger
        self.forecast = forecast
        self._plugins = plugins or (lambda: {})

    @staticmethod
    def can(actor_role: str, operation: str) -> bool:
        allowed = ROLE_AUTHORITY.get(actor_role)
        return bool(allowed) and ("*" in allowed or operation in allowed)

    # ---- read tool: attention brief ------------------------------------------- #

    def brief(self, project_id: str, *, actor_role: str = "owner") -> dict[str, Any]:
        """Deterministic, read-only list of what needs this role's attention.

        Nothing here changes state or records a proposal; every item points at the
        record and, where a decision is involved, the operation that would need an
        approval.  Decision and execution items are shown only to roles that hold
        that authority.  Approvals are entity-wide (one entity in the prototype)."""
        if actor_role not in ROLE_AUTHORITY:
            raise ValueError(f"unknown role {actor_role!r}")
        items: list[dict[str, Any]] = []

        def add(level: str, kind: str, text: str, ref: str | None = None, operation: str | None = None) -> None:
            items.append({"level": level, "kind": kind, "text": text, "ref": ref, "operation": operation})

        auth = self.db.authority_status()
        if not auth["effective_write_authority"]:
            add("blocker", "authority", "This workspace copy holds no write authority; claim it with a controller approval before changing records.")
        if auth["release_quarantined"]:
            add("blocker", "quarantine", "Payment release is quarantined after a restore; run recovery reconciliation before any release.", operation="payment.release")
        chain = self.audit.verify_chain()
        if not chain["ok"]:
            add("blocker", "audit_chain", f"Audit hash chain is broken at entry {chain.get('broken_at_seq')}.")
        tb = self.ledger.trial_balance()
        if not tb["balanced"]:
            add("blocker", "trial_balance", f"Trial balance does not balance: debits {tb['total_debit']} vs credits {tb['total_credit']}.")

        claim = self.db.one("SELECT payload_json FROM audit_log WHERE action='workspace.claim_write_authority' ORDER BY seq DESC LIMIT 1")
        if claim and (json.loads(claim["payload_json"]) or {}).get("owner_claim_code") == "not_configured":
            add("review", "claim_unsecured", "Write authority on this copy was last claimed by attestation only; set CIPHER_OWNER_SECRET so a restored copy needs an owner claim code.")

        now_iso = utcnow_iso()
        for ap in self.db.query("SELECT id, operation, subject_type, subject_id, status, manifest_json, expires_at FROM approvals WHERE status IN ('pending','granted') ORDER BY requested_at"):
            if not self.can(actor_role, ap["operation"]):
                continue
            if ap["expires_at"] <= now_iso:
                add("review", "approval_expired", f"{ap['operation']} on {ap['subject_type']} {ap['subject_id']} expired before it was executed; request a fresh approval.", ap["id"], ap["operation"])
                continue
            amounts = ", ".join(f"{k} {v}" for k, v in ((json.loads(ap["manifest_json"]) or {}).get("amounts") or {}).items())
            suffix = f" ({amounts})" if amounts else ""
            if ap["status"] == "pending":
                add("decide", "approval_pending", f"{ap['operation']} on {ap['subject_type']} {ap['subject_id']} awaits a decision{suffix}.", ap["id"], ap["operation"])
            else:
                add("execute", "approval_granted", f"{ap['operation']} on {ap['subject_type']} {ap['subject_id']} is approved and not yet executed{suffix}.", ap["id"], ap["operation"])

        if self.can(actor_role, "payment.release"):
            for p in self.db.query("SELECT id, status, amount, note FROM payment_intents WHERE status IN ('submitted','outcome_unknown') ORDER BY created_at"):
                add("reconcile", "payment_unknown", f"Payment {p['id']} for {p['amount']} has an unknown outcome; reconcile with the provider before any retry.", p["id"], "payment.release")
            pending = self.db.scalar("SELECT COUNT(*) FROM outbox WHERE status='pending'") or 0
            if pending:
                add("execute", "outbox", f"{pending} approved payment(s) are queued in the outbox for dispatch.")
            for p in self.db.query("SELECT id, amount, note FROM payment_intents WHERE status IN ('failed','returned') ORDER BY created_at"):
                add("review", "payment_failed", f"Payment {p['id']} for {p['amount']} failed or was returned; the obligation is open again ({p['note'] or 'no note'}).", p["id"])
            for s in self.payments.stale_processing():
                add("reconcile", "payment_stale", f"Payment {s['intent_id']} for {s['amount']} has been processing at the provider for {s['days_processing']} day(s); chase the provider before close.", s["intent_id"], "payment.release")

        ap_items = self.bills.ap_open_items(project_id)
        if not ap_items["reconciled"]:
            add("blocker", "ap_unreconciled", f"AP subledger {ap_items['subledger_total']} does not match the control account {ap_items['control_balance']}.")
        ar_items = self.receivables.ar_open_items(project_id)
        if not ar_items["reconciled"]:
            add("blocker", "ar_unreconciled", f"AR subledger {ar_items['subledger_total']} does not match the control account {ar_items['control_balance']}.")

        for b in self.bills.list(project_id=project_id):
            if b["status"] != "draft":
                continue
            if b["stale"]:
                add("review", "bill_stale", f"Supplier bill {b['sequence']} was certified before its commitment changed; void and re-certify it.", b["id"], "bill.approve")
            elif self.can(actor_role, "bill.approve"):
                add("decide", "bill_draft", f"Supplier bill {b['sequence']} ({b['amount_due']} due) is certified and needs approval.", b["id"], "bill.approve")
        if self.can(actor_role, "prime_bill.approve"):
            for b in self.receivables.list(project_id):
                if b["status"] == "draft":
                    add("decide", "prime_bill_draft", f"Prime bill {b['sequence']} ({b['amount_due']} due) needs approval.", b["id"], "prime_bill.approve")
        for est in self.estimates.list(project_id):
            if est["status"] in ("draft", "approved") and est["stale"]:
                add("review", "estimate_stale", f"Estimate revision {est['revision']} is priced from a superseded document revision.", est["id"], "estimate.approve")
        for c in self.commitments.list(project_id):
            if c["status"] == "draft" and self.can(actor_role, "commitment.execute"):
                blocked = c["estimate"] and c["estimate"]["stale"]
                add("review" if blocked else "decide", "commitment_draft", f"Commitment '{c['title']}' ({c['original_amount']}) is drafted" + (" but its estimate is stale." if blocked else " and needs execution approval."), c["id"], "commitment.execute")
            for ch in c["changes"]:
                if ch["status"] == "pending" and self.can(actor_role, "change.execute"):
                    add("decide", "change_pending", f"Change of {ch['amount']} on '{c['title']}' is pending ({ch['reason']}).", ch["id"], "change.execute")

        if self.forecast is not None:
            f = self.forecast.project(project_id)
            if f["over_budget"]:
                add("review", "over_budget", f"Forecast at completion {f['forecast_at_completion']} exceeds the budget {f['budget']} by {f['variance_to_budget'].lstrip('-')} (pending exposure {f['pending_exposure']}).")

        for period in self.db.query("SELECT id FROM periods WHERE status='open' ORDER BY start_date"):
            for name, plugin in sorted(self._plugins().items()):
                if not hasattr(plugin, "close_checks"):
                    continue
                try:
                    checks = plugin.close_checks(period["id"]) or []
                except Exception as exc:  # a broken module must still be visible
                    add("review", "close_check_error", f"{name} close checks for {period['id']} raised: {exc}")
                    continue
                for chk in checks:
                    if not chk.get("ok", True):
                        add("review", "close_check", f"{period['id']} · {name}: {chk.get('check')} — {chk.get('detail', '')}")

        order = {lvl: i for i, lvl in enumerate(BRIEF_LEVELS)}
        items.sort(key=lambda it: order.get(it["level"], len(order)))
        counts = {lvl: sum(1 for it in items if it["level"] == lvl) for lvl in BRIEF_LEVELS}
        return {"project_id": project_id, "role": actor_role, "items": items, "counts": counts, "read_only": True}

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

        # operations owned by a core domain (prime_bill.send, journal.reverse, ...): the
        # owner builds the manifest from current state; Ricky gates the role first.
        owner = self._core_owner(workflow)
        if owner is not None:
            self._require_role(actor_role, workflow)
            subject_id = ctx.get("subject_id") or next((v for k, v in ctx.items() if k.endswith("_id")), None)
            if not subject_id:
                raise _Abstain("no subject id supplied")
            manifest = owner.manifest_for(workflow, subject_id, actor_role=actor_role)
            amounts = ", ".join(f"{k} {v}" for k, v in (manifest.get("amounts") or {}).items())
            return manifest, f"{workflow} on {subject_id}{(' for ' + amounts) if amounts else ''}"

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
