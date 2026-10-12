"""The Cipher service façade used by the console, the CLI and the tests.

One instance owns one SQLite workspace.  Every consequential change follows
the same shape:

    request_approval(operation, subject)  -> pending approval with a bound manifest
    approve(approval_id, approver)        -> human grants it
    execute(approval_id)                  -> manifest is rebuilt from current state,
                                             consumed atomically, and the action applied
                                             as an idempotent command
"""
from __future__ import annotations

import importlib
import logging
import os
import tempfile
from typing import Any

from .core.approvals import Approvals, StaleApprovalError
from .core.db import register_schema_version

log = logging.getLogger("cipher")

# v2 modules.  Each module is optional (missing or broken modules are skipped
# with a warning) and must expose:
#   SCHEMA_NAME: str, SCHEMA_STATEMENTS: list[str]   -> registered as the next schema version, in this order
#   PLUGIN_NAME: str                                   -> the operation prefix it owns, e.g. "asset" for "asset.*"
#   class Plugin: __init__(self, cipher); manifest_for(operation, subject_id, *, actor_role) -> manifest;
#                 apply(operation, subject_id, *, approval_id, manifest, actor, period_id) -> dict;
#                 state(project_id) -> dict
PLUGIN_MODULES = [
    "apps.cipher.domain.assets",
    "apps.cipher.domain.schedule",
    "apps.cipher.domain.drawings",
    "apps.cipher.domain.reimbursements",
]
_LOADED_PLUGIN_MODULES: list[Any] = []


def _load_plugin_modules() -> list[Any]:
    if _LOADED_PLUGIN_MODULES:
        return _LOADED_PLUGIN_MODULES
    for name in PLUGIN_MODULES:
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name == name:
                continue
            log.warning("plugin %s failed to import: %s", name, exc)
            continue
        except Exception as exc:  # a broken sibling module must not take the core down
            log.warning("plugin %s failed to import: %s", name, exc)
            continue
        try:
            register_schema_version(mod.SCHEMA_NAME, list(mod.SCHEMA_STATEMENTS))
        except Exception as exc:
            log.warning("plugin %s schema rejected: %s", name, exc)
            continue
        _LOADED_PLUGIN_MODULES.append(mod)
    return _LOADED_PLUGIN_MODULES


_load_plugin_modules()
from .core.audit import Audit
from .core.commands import CommandResult, Commands
from .core.db import Database
from .core.ids import new_id, sha256_hex, utcnow_iso
from .core.money import fmt, money
from .domain.bills import Bills
from .domain.commitments import Commitments
from .domain.estimates import Estimates
from .domain.evidence import Evidence
from .domain.forecast import Forecast
from .domain.ledger import Ledger
from .domain.payments import Payments, SimulatedProvider
from .domain.receivables import Receivables
from .domain.ricky import Ricky


class CipherError(RuntimeError):
    pass


OPERATIONS = {
    "estimate.approve": "estimate",
    "commitment.execute": "commitment",
    "change.execute": "change",
    "bill.approve": "bill",
    "prime_bill.approve": "prime_bill",
    "payment.release": "bill",
    "payment.release_retainage": "commitment",
    "retainage.release": "commitment",
}


class Cipher:
    def __init__(self, path: str = ":memory:", *, provider: SimulatedProvider | None = None):
        self.db = Database(path)
        self.audit = Audit(self.db)
        self.approvals = Approvals(self.db, self.audit)
        self.commands = Commands(self.db, self.audit)
        self.ledger = Ledger(self.db, self.audit)
        self.ledger.ensure_chart()
        self.evidence = Evidence(self.db, self.audit)
        self.estimates = Estimates(self.db, self.audit, self.evidence)
        self.commitments = Commitments(self.db, self.audit, self.estimates)
        self.bills = Bills(self.db, self.audit, self.commitments, self.ledger)
        self.receivables = Receivables(self.db, self.audit, self.ledger)
        self.payments = Payments(self.db, self.audit, self.commands, self.ledger)
        self.forecast = Forecast(self.db, self.commitments, self.ledger)
        self.ricky = Ricky(self.db, self.audit, self.estimates, self.commitments, self.bills, self.receivables, self.payments, self.ledger, plugins=lambda: self._plugins)
        self.provider = provider or SimulatedProvider()
        self._plugins: dict[str, Any] = {}
        for mod in _load_plugin_modules():
            try:
                self.register_plugin(mod.PLUGIN_NAME, mod.Plugin(self))
            except Exception as exc:
                log.warning("plugin %s failed to initialise: %s", getattr(mod, "PLUGIN_NAME", mod), exc)

    # ---- plugins (v2 modules register here) ------------------------------------ #

    def register_plugin(self, name: str, module: Any) -> None:
        self._plugins[name] = module

    def plugin(self, name: str) -> Any:
        return self._plugins[name]

    # ---- master data -------------------------------------------------------------- #

    def add_party(self, *, kind: str, name: str, destination: str | None = None, actor: str = "owner") -> dict[str, Any]:
        pid = new_id("pty")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO parties (id, kind, name, destination, destination_version, destination_verified, created_at) VALUES (?,?,?,?,?,0,?)", (pid, kind, name, destination, 1 if destination else 0, utcnow_iso()))
            self.audit.record(actor, "party.created", "party", pid, {"kind": kind, "name": name})
        return self.party(pid)

    def party(self, party_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM parties WHERE id=?", (party_id,))
        if row is None:
            raise CipherError(f"unknown party {party_id}")
        return row

    def parties(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM parties ORDER BY created_at")

    def verify_destination(self, party_id: str, *, destination: str, verified_by: str, channel: str = "independent call-back") -> dict[str, Any]:
        """Record an independently verified payment destination.  Any open
        approval bound to the previous destination version is invalidated."""
        with self.db.transaction() as conn:
            p = self.party(party_id)
            conn.execute("UPDATE parties SET destination=?, destination_version=destination_version+1, destination_verified=1 WHERE id=?", (destination, party_id))
            self.audit.record(verified_by, "party.destination_verified", "party", party_id, {"destination_hash": sha256_hex(destination), "version": p["destination_version"] + 1, "channel": channel})
            for ap in self.approvals.list(status="granted") + self.approvals.list(status="pending"):
                dest = ap["manifest"].get("destination") or {}
                if dest.get("party_id") == party_id:
                    self.approvals.invalidate(ap["id"], reason="payee destination changed after approval", actor=verified_by)
        return self.party(party_id)

    def create_project(self, *, name: str, entity: str, budget: str, customer_id: str | None = None, actor: str = "owner") -> dict[str, Any]:
        pid = new_id("prj")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO projects (id, name, entity, currency, customer_id, budget, created_at) VALUES (?,?,?,?,?,?,?)", (pid, name, entity, "USD", customer_id, fmt(money(budget)), utcnow_iso()))
            self.audit.record(actor, "project.created", "project", pid, {"name": name, "budget": fmt(money(budget))})
        return self.project(pid)

    def project(self, project_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM projects WHERE id=?", (project_id,))
        if row is None:
            raise CipherError(f"unknown project {project_id}")
        return row

    def projects(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM projects ORDER BY created_at")

    def set_budget(self, project_id: str, budget: str, *, actor: str = "owner") -> dict[str, Any]:
        with self.db.transaction() as conn:
            conn.execute("UPDATE projects SET budget=? WHERE id=?", (fmt(money(budget)), project_id))
            self.audit.record(actor, "project.budget_set", "project", project_id, {"budget": fmt(money(budget))})
        return self.project(project_id)

    # ---- approvals ------------------------------------------------------------------ #

    def _manifest(self, operation: str, subject_id: str, actor_role: str) -> dict[str, Any]:
        if operation == "estimate.approve":
            return self.estimates.manifest(subject_id, actor_role=actor_role)
        if operation == "commitment.execute":
            return self.commitments.manifest(subject_id, actor_role=actor_role)
        if operation == "change.execute":
            return self.commitments.change_manifest(subject_id, actor_role=actor_role)
        if operation == "bill.approve":
            return self.bills.manifest(subject_id, actor_role=actor_role)
        if operation == "prime_bill.approve":
            return self.receivables.manifest(subject_id, actor_role=actor_role)
        if operation == "payment.release":
            return self.payments.manifest_for_bill(subject_id, actor_role=actor_role)
        if operation == "payment.release_retainage":
            m = self.payments.manifest_for_retainage(subject_id, actor_role=actor_role)
            m["operation"] = "payment.release_retainage"
            return m
        if operation == "retainage.release":
            return self.bills.retainage_manifest(subject_id, actor_role=actor_role)
        plugin = self._plugins.get(operation.split(".")[0])
        if plugin is not None and hasattr(plugin, "manifest_for"):
            return plugin.manifest_for(operation, subject_id, actor_role=actor_role)
        raise CipherError(f"unknown operation {operation}")

    def request_approval(self, operation: str, subject_id: str, *, actor_role: str = "owner", requested_by: str = "owner") -> dict[str, Any]:
        manifest = self._manifest(operation, subject_id, actor_role)
        return self.approvals.request(manifest, requested_by=requested_by)

    def approve(self, approval_id: str, *, approver: str = "owner") -> dict[str, Any]:
        return self.approvals.grant(approval_id, approver=approver)

    def reject(self, approval_id: str, *, approver: str = "owner", reason: str = "") -> dict[str, Any]:
        return self.approvals.reject(approval_id, approver=approver, reason=reason)

    def execute(self, approval_id: str, *, actor: str = "owner", op_id: str | None = None, period_id: str | None = None) -> CommandResult:
        ap = self.approvals.get(approval_id)
        operation, subject_id = ap["operation"], ap["subject_id"]
        op_id = op_id or f"exec:{approval_id}"
        payload = {"approval_id": approval_id, "operation": operation, "subject_id": subject_id}

        def handler():
            current = self._manifest(operation, subject_id, ap["actor_role"])
            self.approvals.consume(approval_id, current_manifest=current, consumer=actor)
            return self._apply(operation, subject_id, approval_id, current, actor, period_id)

        try:
            return self.commands.run(op_id, payload, handler, actor=actor)
        except StaleApprovalError as exc:
            # the command transaction rolled back; make the invalidation durable
            if self.approvals.get(approval_id)["status"] == "granted":
                self.approvals.invalidate(approval_id, reason=str(exc), actor=actor)
            raise

    def _apply(self, operation: str, subject_id: str, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation == "estimate.approve":
            return {"estimate": self.estimates.approve(subject_id, approval_id=approval_id, actor=actor)["id"], "status": "approved"}
        if operation == "commitment.execute":
            c = self.commitments.execute(subject_id, approval_id=approval_id, actor=actor)
            return {"commitment": c["id"], "status": c["status"], "executed_amount": c["executed_amount"]}
        if operation == "change.execute":
            ch = self.commitments.execute_change(subject_id, approval_id=approval_id, actor=actor)
            for b in self.bills.list(commitment_id=ch["commitment_id"]):
                if b["status"] == "draft":
                    self.approvals.invalidate_for_subject("bill", b["id"], reason="commitment changed after the bill was certified", actor=actor)
            c = self.commitments.get(ch["commitment_id"])
            return {"change": ch["id"], "commitment_executed_amount": c["executed_amount"], "commitment_version": c["version"]}
        if operation == "bill.approve":
            b = self.bills.post(subject_id, approval_id=approval_id, actor=actor)
            return {"bill": b["id"], "status": b["status"], "journal_id": b["journal_id"], "amount_due": b["amount_due"]}
        if operation == "prime_bill.approve":
            b = self.receivables.post(subject_id, approval_id=approval_id, actor=actor)
            return {"prime_bill": b["id"], "status": b["status"], "journal_id": b["journal_id"]}
        if operation == "payment.release":
            intent = self.payments.create_intent(manifest=manifest, approval_id=approval_id, bill_id=subject_id, note="bill payment", actor=actor)
            return {"intent": intent["id"], "status": intent["status"], "amount": intent["amount"]}
        if operation == "payment.release_retainage":
            intent = self.payments.create_intent(manifest=manifest, approval_id=approval_id, bill_id=None, note="retainage release payment", actor=actor)
            return {"intent": intent["id"], "status": intent["status"], "amount": intent["amount"]}
        if operation == "retainage.release":
            pid = period_id or self.current_period()["id"]
            return self.bills.release_retainage(commitment_id=subject_id, period_id=pid, approval_id=approval_id, actor=actor)
        plugin = self._plugins.get(operation.split(".")[0])
        if plugin is not None and hasattr(plugin, "apply"):
            return plugin.apply(operation, subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)
        raise CipherError(f"unknown operation {operation}")

    def approve_and_execute(self, operation: str, subject_id: str, *, actor_role: str = "owner", actor: str = "owner", period_id: str | None = None) -> CommandResult:
        """Convenience for scripts and tests: request, grant and execute in one go.
        Each step is still recorded separately."""
        ap = self.request_approval(operation, subject_id, actor_role=actor_role, requested_by=actor)
        self.approve(ap["id"], approver=actor)
        return self.execute(ap["id"], actor=actor, period_id=period_id)

    # ---- periods ------------------------------------------------------------------------ #

    def open_period(self, period_id: str, name: str, start_date: str, end_date: str, *, actor: str = "owner") -> dict[str, Any]:
        return self.ledger.open_period(period_id, name, start_date, end_date, actor=actor)

    def current_period(self) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM periods WHERE status='open' ORDER BY start_date DESC LIMIT 1")
        if row is None:
            raise CipherError("no open period")
        return row

    def close_period(self, period_id: str, *, actor: str = "owner") -> dict[str, Any]:
        return self.ledger.close_period(period_id, actor=actor)

    # ---- payments -------------------------------------------------------------------------- #

    def dispatch_payments(self, *, actor: str = "treasury-worker") -> list[dict[str, Any]]:
        return self.payments.dispatch_pending(self.provider, actor=actor)

    def reconcile_payments(self, *, actor: str = "reconciler") -> list[dict[str, Any]]:
        return self.payments.reconcile(self.provider, actor=actor)

    # ---- reading ------------------------------------------------------------------------------ #

    def project_state(self, project_id: str) -> dict[str, Any]:
        project = self.project(project_id)
        commitments = self.commitments.list(project_id)
        for c in commitments:
            c["bills"] = self.bills.list(commitment_id=c["id"])
            c["stored_lots"] = self.bills.lots(c["id"])
        state = {
            "project": project,
            "authority": self.db.authority_status(),
            "periods": self.ledger.periods(),
            "parties": self.parties(),
            "documents": self.evidence.documents(project_id),
            "estimates": self.estimates.list(project_id),
            "commitments": commitments,
            "prime_bills": self.receivables.list(project_id),
            "payments": self.payments.list(),
            "approvals": self.approvals.list(),
            "forecast": self.forecast.project(project_id),
            "ap": self.bills.ap_open_items(project_id),
            "ar": self.receivables.ar_open_items(project_id),
            "trial_balance": self.ledger.trial_balance(),
            "income_statement": self.ledger.income_statement(),
            "ricky": self.ricky.history(20),
            "audit_chain": self.audit.verify_chain(),
            "outbox_pending": self.commands.pending(),
        }
        for name, plugin in self._plugins.items():
            if hasattr(plugin, "state"):
                state[name] = plugin.state(project_id)
        return state

    def audit_export(self) -> dict[str, Any]:
        return {
            "exported_at": utcnow_iso(),
            "workspace": self.db.authority_status(),
            "schema": self.db.schema_manifest(),
            "chart_of_accounts": self.ledger.accounts(),
            "periods": self.ledger.periods(),
            "trial_balance": self.ledger.trial_balance(),
            "journals": self.ledger.journals(),
            "approvals": self.approvals.list(),
            "ap_reconciliation": self.bills.ap_open_items(),
            "ar_reconciliation": self.receivables.ar_open_items(),
            "audit": self.audit.export(),
        }

    # ---- restore ---------------------------------------------------------------------------------- #

    def snapshot(self, target_path: str) -> str:
        return self.db.snapshot(target_path)

    @classmethod
    def open_restored(cls, path: str, *, provider: SimulatedProvider | None = None) -> "Cipher":
        """Open a restored copy.  It has no write authority and payment release is
        quarantined until the owner claims authority and reconciles."""
        return cls(path, provider=provider)

    def claim_write_authority(self, *, approval_ref: str, actor: str = "owner") -> dict[str, Any]:
        return self.db.claim_write_authority(approval_ref=approval_ref, note=f"claimed by {actor}")

    def complete_recovery(self, *, actor: str = "owner") -> dict[str, Any]:
        return self.payments.complete_recovery_reconciliation(self.provider, actor=actor)


# --------------------------------------------------------------------------- #
# Golden fixture                                                               #
# --------------------------------------------------------------------------- #

def run_golden_fixture(cipher: Cipher | None = None) -> dict[str, Any]:
    """Drive the plan's synthetic vertical workflow end to end and return the
    numbers the acceptance tests assert on."""
    c = cipher or Cipher()
    owner = "owner"
    supplier = c.add_party(kind="supplier", name="Synthetic Subcontractor A", destination="ACH-SIM-0001")
    c.verify_destination(supplier["id"], destination="ACH-SIM-0001", verified_by="owner")
    customer = c.add_party(kind="customer", name="Synthetic Owner Agency")
    project = c.create_project(name="Synthetic WWTP upgrade", entity="S&A Solutions LLC (synthetic)", budget="115000", customer_id=customer["id"])
    c.open_period("2026-10", "October 2026", "2026-10-01", "2026-10-31")
    c.open_period("2026-11", "November 2026", "2026-11-01", "2026-11-30")

    drawing = c.evidence.register_document(project_id=project["id"], kind="drawing", title="Drawing A - site piping and pump station", actor=owner)
    rev1 = c.evidence.add_revision(document_id=drawing["id"], content=b"drawing A rev 1 (synthetic)", note="issued for pricing", actor=owner)
    estimate = c.estimates.create(project_id=project["id"], document_revision_id=rev1["id"], lines=[
        {"description": "Site piping", "quantity": "1", "unit": "LS", "unit_price": "60000"},
        {"description": "Pump station", "quantity": "1", "unit": "LS", "unit_price": "40000"},
    ], actor=owner)
    c.approve_and_execute("estimate.approve", estimate["id"], actor_role="owner")

    commitment = c.commitments.create(project_id=project["id"], supplier_id=supplier["id"], title="Subcontract - site piping and pump station",
                                      sov_lines=[{"description": "Site piping", "amount": "60000"}, {"description": "Pump station", "amount": "40000"}],
                                      retainage_rate="0.10", estimate_id=estimate["id"], actor=owner)
    c.approve_and_execute("commitment.execute", commitment["id"], actor_role="owner")
    line1 = c.commitments.get(commitment["id"])["sov"][0]["id"]

    change = c.commitments.propose_change(commitment["id"], amount="10000", reason="Drawing B scope addition", sov_line_id=line1, actor=owner)
    c.approve_and_execute("change.execute", change["id"], actor_role="owner")
    commitment = c.commitments.get(commitment["id"])

    # period 1
    lot1 = c.bills.add_stored_material(commitment_id=commitment["id"], sov_line_id=line1, description="Ductile iron pipe, on site", eligible_amount="10000", evidence_hash=sha256_hex(b"title/insurance/location evidence"), location="laydown yard", actor=owner)
    bill1 = c.bills.certify(commitment_id=commitment["id"], period_id="2026-10", installed=[{"sov_line_id": line1, "cumulative_installed": "20000"}], actor=owner)
    c.approve_and_execute("bill.approve", bill1["id"], actor_role="owner")
    bill1 = c.bills.get(bill1["id"])

    # payment with provider timeout, reconciliation, replay
    ap_pay = c.request_approval("payment.release", bill1["id"], actor_role="treasury", requested_by="owner")
    c.approve(ap_pay["id"], approver="owner")
    first = c.execute(ap_pay["id"], actor="treasury")
    replay = c.execute(ap_pay["id"], actor="treasury")
    c.provider.mode = "timeout_after_accept"
    dispatch = c.dispatch_payments()
    c.provider.mode = "accept"
    reconciled = c.reconcile_payments()
    intent = c.payments.get(first.result["intent"])
    settle_event = c.provider.settle(intent["logical_op_id"])
    c.payments.ingest_event(settle_event, actor="webhook")
    duplicate = c.payments.ingest_event(settle_event, actor="webhook")

    # period 2
    lot2 = c.bills.add_stored_material(commitment_id=commitment["id"], sov_line_id=line1, description="Valves, on site", eligible_amount="5000", evidence_hash=sha256_hex(b"valve evidence"), actor=owner)
    bill2 = c.bills.certify(commitment_id=commitment["id"], period_id="2026-10", installed=[{"sov_line_id": line1, "cumulative_installed": "45000"}], transfers=[{"lot_id": lot1["id"], "amount": "10000"}], actor=owner)
    c.approve_and_execute("bill.approve", bill2["id"], actor_role="owner")
    bill2 = c.bills.get(bill2["id"])

    pending_change = c.commitments.propose_change(commitment["id"], amount="12000", reason="Pending alternative - not executed", sov_line_id=line1, actor=owner)
    forecast = c.forecast.project(project["id"])

    # prime billing and collection
    prime = c.receivables.certify(project_id=project["id"], period_id="2026-10", certified_cumulative="60000", retainage_rate="0.10", actor=owner)
    c.approve_and_execute("prime_bill.approve", prime["id"], actor_role="owner")
    c.receivables.send(prime["id"], actor=owner)
    collection = c.receivables.record_collection(prime_bill_id=prime["id"], period_id="2026-10", amount="54000", fee="5", provider_ref="ach_sim_rcv_0001", actor=owner)
    c.close_period("2026-10")
    late_return = c.receivables.record_return(collection_id=collection["id"], period_id="2026-11", reason="late return after close (simulated)", actor=owner)

    # stale approval: bill certified, then commitment changed before execution
    bill3 = c.bills.certify(commitment_id=commitment["id"], period_id="2026-11", installed=[{"sov_line_id": line1, "cumulative_installed": "50000"}], actor=owner)
    ap_bill3 = c.request_approval("bill.approve", bill3["id"], actor_role="owner")
    c.approve(ap_bill3["id"])
    c.approve_and_execute("change.execute", pending_change["id"], actor_role="owner")
    stale_result = None
    try:
        c.execute(ap_bill3["id"])
    except Exception as exc:  # StaleApprovalError or ApprovalNotGranted
        stale_result = type(exc).__name__

    # Ricky abstains on stale evidence
    rev2 = c.evidence.add_revision(document_id=drawing["id"], content=b"drawing A rev 2 (synthetic)", note="revised after pricing", actor=owner)
    stale_commitment = c.commitments.create(project_id=project["id"], supplier_id=supplier["id"], title="Follow-on subcontract", sov_lines=[{"description": "Extra", "amount": "1000"}], estimate_id=estimate["id"], actor=owner)
    ricky_abstain = c.ricky.propose("commitment.execute", actor_role="pm", context={"commitment_id": stale_commitment["id"]})
    ricky_role = c.ricky.propose("payment.release", actor_role="estimator", context={"bill_id": bill2["id"]})

    bill1 = c.bills.get(bill1["id"])
    return {
        "project_id": project["id"],
        "commitment_id": commitment["id"],
        "executed_amount": c.commitments.get(commitment["id"])["executed_amount"],
        "sov": [s["amount"] for s in c.commitments.get(commitment["id"])["sov"]],
        "bill1": {k: bill1[k] for k in ("cumulative_gross", "cumulative_retainage", "amount_due", "status")},
        "bill2": {k: bill2[k] for k in ("cumulative_installed", "cumulative_stored", "cumulative_gross", "cumulative_retainage", "cumulative_net", "amount_due", "retainage_this_period", "stored_transferred_this_period", "status")},
        "payment": {"first_replayed": first.replayed, "replay_replayed": replay.replayed, "dispatch": dispatch, "reconciled": reconciled, "transfers": len(c.provider.transfers), "status": c.payments.get(intent["id"])["status"], "duplicate_event": duplicate},
        "forecast_before_change": forecast,
        "prime": {k: c.receivables.get(prime["id"])[k] for k in ("amount_due", "retainage_cumulative", "revenue_this_period", "status")},
        "collection": collection, "late_return": late_return,
        "stale_result": stale_result, "ap_bill3_status": c.approvals.get(ap_bill3["id"])["status"],
        "ricky_abstain": ricky_abstain, "ricky_role": ricky_role,
        "trial_balance": c.ledger.trial_balance(),
        "ap": c.bills.ap_open_items(project["id"]), "ar": c.receivables.ar_open_items(project["id"]),
        "bank": fmt(c.ledger.balance("1000")), "fees": fmt(c.ledger.balance("6000")), "cost": fmt(c.ledger.balance("5000")), "stored": fmt(c.ledger.balance("1300")),
        "audit": c.audit.verify_chain(),
        "lots": c.bills.lots(commitment["id"]),
    }
