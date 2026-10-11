"""Payment intents, the dispatch outbox, a payment simulator and reconciliation.

State machine (plan section 6, "Execution and recovery"):

    approved -> queued -> submitted -> accepted -> settled
                             |            \\-> returned
                             +-> outcome_unknown -> (reconcile) accepted | failed
                             +-> failed

* an intent is created together with its outbox row in one transaction;
* only a pending outbox row can be dispatched, and dispatching a row twice is
  impossible because dispatch marks it before the provider call completes;
* the provider is called with Cipher's logical operation id, so a replay of the
  same intent cannot create a second transfer;
* a timeout after submission is *outcome unknown*: nothing is retried until
  reconciliation establishes the result;
* after a restore (recovery epoch bump) every release is quarantined until the
  owner runs recovery reconciliation.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..core.approvals import build_manifest
from ..core.audit import Audit
from ..core.commands import Commands
from ..core.db import Database
from ..core.ids import canonical_json, hash_json, new_id, utcnow_iso
from ..core.money import fmt, money
from .ledger import Ledger


class PaymentError(RuntimeError):
    pass


class ReleaseQuarantined(PaymentError):
    pass


# --------------------------------------------------------------------------- #
# Simulated provider                                                           #
# --------------------------------------------------------------------------- #

class SimulatedProvider:
    """An in-memory payment rail.  ``mode`` controls the next submission:

    ``accept``                normal acceptance
    ``timeout_after_accept``  the transfer is recorded but the response is lost
    ``reject``                the provider refuses the payment
    ``unavailable``           the provider cannot be reached at all
    """

    def __init__(self):
        self.mode = "accept"
        self.transfers: dict[str, dict[str, Any]] = {}
        self.submissions: list[dict[str, Any]] = []

    def submit(self, *, logical_op_id: str, amount: str, destination: str, payload_hash: str) -> dict[str, Any]:
        self.submissions.append({"logical_op_id": logical_op_id, "amount": amount, "destination": destination, "mode": self.mode})
        if self.mode == "unavailable":
            raise ConnectionError("provider unavailable")
        if self.mode == "reject":
            return {"outcome": "rejected", "reason": "provider rejected the payment"}
        existing = self.transfers.get(logical_op_id)
        if existing is None:
            existing = {"provider_ref": f"sim_{len(self.transfers) + 1:06d}", "amount": amount, "destination": destination, "payload_hash": payload_hash, "status": "accepted"}
            self.transfers[logical_op_id] = existing
        elif existing["payload_hash"] != payload_hash:
            return {"outcome": "rejected", "reason": "idempotency key reused with a different payload"}
        if self.mode == "timeout_after_accept":
            raise TimeoutError("no response after submission")
        return {"outcome": "accepted", "provider_ref": existing["provider_ref"]}

    def lookup(self, logical_op_id: str) -> dict[str, Any]:
        if self.mode == "unavailable":
            raise ConnectionError("provider unavailable")
        t = self.transfers.get(logical_op_id)
        if t is None:
            return {"found": False}
        return {"found": True, "provider_ref": t["provider_ref"], "status": t["status"], "amount": t["amount"]}

    def settle(self, logical_op_id: str) -> dict[str, Any]:
        t = self.transfers[logical_op_id]
        t["status"] = "settled"
        return {"id": f"evt_{t['provider_ref']}_settled", "kind": "settled", "provider_ref": t["provider_ref"], "amount": t["amount"]}

    def return_payment(self, logical_op_id: str, reason: str = "account closed") -> dict[str, Any]:
        t = self.transfers[logical_op_id]
        t["status"] = "returned"
        return {"id": f"evt_{t['provider_ref']}_returned", "kind": "returned", "provider_ref": t["provider_ref"], "amount": t["amount"], "reason": reason}


# --------------------------------------------------------------------------- #
# Payments                                                                     #
# --------------------------------------------------------------------------- #

class Payments:
    def __init__(self, db: Database, audit: Audit, commands: Commands, ledger: Ledger):
        self.db = db
        self.audit = audit
        self.commands = commands
        self.ledger = ledger

    # ---- manifests ----------------------------------------------------------- #

    def manifest_for_bill(self, bill_id: str, *, actor_role: str) -> dict[str, Any]:
        b = self.db.one("SELECT b.*, c.supplier_id, c.project_id FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE b.id=?", (bill_id,))
        if b is None:
            raise PaymentError(f"unknown bill {bill_id}")
        if b["status"] != "posted":
            raise PaymentError(f"bill {bill_id} is {b['status']}; only posted bills are payable")
        supplier = self.db.one("SELECT * FROM parties WHERE id=?", (b["supplier_id"],))
        return build_manifest(
            operation="payment.release",
            subject_type="bill",
            subject_id=bill_id,
            actor_role=actor_role,
            amounts={"amount": b["amount_due"]},
            bindings={"bill_hash": b["content_hash"], "bill_status": b["status"], "destination_verified": bool(supplier["destination_verified"]), "funding_source": "operating-bank-simulated", "fees": "0.00"},
            destination={"party_id": supplier["id"], "destination": supplier["destination"], "destination_version": supplier["destination_version"]},
        )

    def manifest_for_retainage(self, commitment_id: str, *, actor_role: str) -> dict[str, Any]:
        c = self.db.one("SELECT * FROM commitments WHERE id=?", (commitment_id,))
        if c is None:
            raise PaymentError(f"unknown commitment {commitment_id}")
        supplier = self.db.one("SELECT * FROM parties WHERE id=?", (c["supplier_id"],))
        payable = self.ledger.account_activity("2050", party_id=c["supplier_id"], project_id=c["project_id"])["debit"]
        paid = self.db.query("SELECT amount FROM payment_intents WHERE bill_id IS NULL AND party_id=? AND note LIKE 'retainage%' AND status IN ('queued','submitted','outcome_unknown','accepted','settled')", (c["supplier_id"],))
        outstanding = money(payable - sum(money(p["amount"]) for p in paid))
        if outstanding <= 0:
            raise PaymentError("no released retainage is payable")
        return build_manifest(
            operation="payment.release",
            subject_type="commitment",
            subject_id=commitment_id,
            actor_role=actor_role,
            amounts={"amount": outstanding},
            bindings={"kind": "retainage", "destination_verified": bool(supplier["destination_verified"]), "funding_source": "operating-bank-simulated", "fees": "0.00"},
            destination={"party_id": supplier["id"], "destination": supplier["destination"], "destination_version": supplier["destination_version"]},
        )

    # ---- intents ------------------------------------------------------------- #

    def release_allowed(self) -> tuple[bool, str]:
        status = self.db.authority_status()
        if status["release_quarantined"]:
            return False, "payment release is quarantined after a restore until recovery reconciliation completes"
        return True, "ok"

    def create_intent(self, *, manifest: dict[str, Any], approval_id: str, bill_id: str | None, note: str, actor: str) -> dict[str, Any]:
        """Create the intent and its outbox row atomically.  ``approval_id`` must
        already be consumed by the caller against ``manifest``."""
        ok, why = self.release_allowed()
        if not ok:
            raise ReleaseQuarantined(why)
        dest = manifest["destination"]
        party = self.db.one("SELECT * FROM parties WHERE id=?", (dest["party_id"],))
        if party is None:
            raise PaymentError("unknown payee")
        if not party["destination_verified"]:
            raise PaymentError("payee destination has not been independently verified")
        if party["destination_version"] != dest["destination_version"] or party["destination"] != dest["destination"]:
            raise PaymentError("payee destination changed after approval")
        amount = money(manifest["amounts"]["amount"])
        if amount <= 0:
            raise PaymentError("payment amount must be positive")
        logical_op_id = f"pay:{approval_id}"
        payload = {"party_id": party["id"], "destination": party["destination"], "destination_version": party["destination_version"], "amount": fmt(amount), "bill_id": bill_id}
        payload_hash = hash_json(payload)
        intent_id = new_id("pay")
        with self.db.transaction() as conn:
            if conn.execute("SELECT id FROM payment_intents WHERE logical_op_id=?", (logical_op_id,)).fetchone():
                raise PaymentError("an intent already exists for this approval")
            ws = self.db.workspace()
            conn.execute(
                """INSERT INTO payment_intents (id, bill_id, party_id, amount, destination, destination_version, status, approval_id, logical_op_id, payload_hash, recovery_epoch, created_at, note)
                   VALUES (?,?,?,?,?,?,'approved',?,?,?,?,?,?)""",
                (intent_id, bill_id, party["id"], fmt(amount), party["destination"], party["destination_version"], approval_id, logical_op_id, payload_hash, ws["recovery_epoch"], utcnow_iso(), note),
            )
            ob = self.commands.enqueue("payment", {"intent_id": intent_id, "logical_op_id": logical_op_id, "payload_hash": payload_hash})
            conn.execute("UPDATE payment_intents SET status='queued', outbox_id=? WHERE id=?", (ob["id"], intent_id))
            self.audit.record(actor, "payment.queued", "payment_intent", intent_id, {"amount": fmt(amount), "party_id": party["id"], "approval_id": approval_id, "outbox_id": ob["id"]})
        return self.get(intent_id)

    def get(self, intent_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM payment_intents WHERE id=?", (intent_id,))
        if row is None:
            raise PaymentError(f"unknown payment intent {intent_id}")
        row["events"] = self.db.query("SELECT * FROM provider_events WHERE intent_id=? ORDER BY received_at", (intent_id,))
        return row

    def list(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self.db.query("SELECT id FROM payment_intents WHERE status=? ORDER BY created_at", (status,))
        else:
            rows = self.db.query("SELECT id FROM payment_intents ORDER BY created_at")
        return [self.get(r["id"]) for r in rows]

    # ---- dispatch -------------------------------------------------------------- #

    def dispatch_pending(self, provider: SimulatedProvider, *, actor: str) -> list[dict[str, Any]]:
        ok, why = self.release_allowed()
        if not ok:
            raise ReleaseQuarantined(why)
        results = []
        for ob in self.commands.pending("payment"):
            intent = self.get(ob["payload"]["intent_id"])
            if intent["status"] != "queued":
                self.commands.mark_failed(ob["id"], f"intent is {intent['status']}")
                continue
            # claim the row first so a second worker can never dispatch the same intent
            with self.db.transaction() as conn:
                conn.execute("UPDATE payment_intents SET status='submitted', submitted_at=? WHERE id=?", (utcnow_iso(), intent["id"]))
                self.commands.mark_dispatched(ob["id"])
            try:
                resp = provider.submit(logical_op_id=intent["logical_op_id"], amount=intent["amount"], destination=intent["destination"], payload_hash=intent["payload_hash"])
            except TimeoutError as exc:
                self._set_status(intent["id"], "outcome_unknown", actor=actor, note=f"timeout after submission: {exc}")
                results.append({"intent_id": intent["id"], "status": "outcome_unknown"})
                continue
            except ConnectionError as exc:
                self._set_status(intent["id"], "outcome_unknown", actor=actor, note=f"provider unreachable: {exc}")
                results.append({"intent_id": intent["id"], "status": "outcome_unknown"})
                continue
            if resp["outcome"] == "accepted":
                self._accept(intent["id"], provider_ref=resp["provider_ref"], actor=actor)
                results.append({"intent_id": intent["id"], "status": "accepted", "provider_ref": resp["provider_ref"]})
            else:
                self._set_status(intent["id"], "failed", actor=actor, note=resp.get("reason", "rejected"))
                results.append({"intent_id": intent["id"], "status": "failed"})
        return results

    def _set_status(self, intent_id: str, status: str, *, actor: str, note: str = "", provider_ref: str | None = None, resolved: bool = False) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE payment_intents SET status=?, note=?, provider_ref=COALESCE(?, provider_ref), resolved_at=CASE WHEN ? THEN ? ELSE resolved_at END WHERE id=?",
                (status, note, provider_ref, 1 if resolved else 0, utcnow_iso(), intent_id),
            )
            self.audit.record(actor, f"payment.{status}", "payment_intent", intent_id, {"note": note, "provider_ref": provider_ref})

    def _accept(self, intent_id: str, *, provider_ref: str, actor: str) -> None:
        intent = self.get(intent_id)
        if intent["status"] == "accepted" or intent["journal_id"]:
            return
        bill = self.db.one("SELECT b.*, c.project_id FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE b.id=?", (intent["bill_id"],)) if intent["bill_id"] else None
        project_id = bill["project_id"] if bill else self.db.one("SELECT project_id FROM commitments WHERE supplier_id=? ORDER BY created_at DESC LIMIT 1", (intent["party_id"],))["project_id"]
        period = self.db.one("SELECT id FROM periods WHERE status='open' ORDER BY start_date DESC LIMIT 1")
        if period is None:
            raise PaymentError("no open period to record the accepted payment")
        with self.db.transaction() as conn:
            j = self.ledger.post(
                period_id=period["id"],
                description=f"Payment accepted by provider ({provider_ref})",
                lines=[
                    {"account": "2000", "debit": intent["amount"], "project_id": project_id, "party_id": intent["party_id"], "memo": "payable settled via provider"},
                    {"account": "1200", "credit": intent["amount"], "project_id": project_id, "party_id": intent["party_id"], "memo": "provider clearing"},
                ],
                source_type="payment_intent", source_id=intent_id, source_version="1", posted_by=actor, approval_id=intent["approval_id"],
            )
            conn.execute("UPDATE payment_intents SET status='accepted', provider_ref=?, journal_id=?, note='' WHERE id=?", (provider_ref, j["id"], intent_id))
            if intent["bill_id"]:
                conn.execute("UPDATE bills SET status='paid' WHERE id=? AND status='posted'", (intent["bill_id"],))
            self.audit.record(actor, "payment.accepted", "payment_intent", intent_id, {"provider_ref": provider_ref, "journal_id": j["id"]})

    # ---- reconciliation ------------------------------------------------------- #

    def reconcile(self, provider: SimulatedProvider, *, actor: str) -> list[dict[str, Any]]:
        """Resolve every submitted/outcome-unknown intent by durable identifier.
        Nothing is ever resubmitted from here."""
        results = []
        for intent in self.db.query("SELECT id FROM payment_intents WHERE status IN ('submitted','outcome_unknown') ORDER BY created_at"):
            intent = self.get(intent["id"])
            try:
                found = provider.lookup(intent["logical_op_id"])
            except ConnectionError as exc:
                self._set_status(intent["id"], "outcome_unknown", actor=actor, note=f"reconciliation pending: {exc}; held for treasury review")
                results.append({"intent_id": intent["id"], "status": "outcome_unknown"})
                continue
            if found["found"]:
                self._accept(intent["id"], provider_ref=found["provider_ref"], actor=actor)
                results.append({"intent_id": intent["id"], "status": "accepted", "provider_ref": found["provider_ref"]})
            else:
                self._set_status(intent["id"], "failed", actor=actor, note="provider has no record of the submission; obligation remains open", resolved=True)
                results.append({"intent_id": intent["id"], "status": "failed"})
        return results

    def complete_recovery_reconciliation(self, provider: SimulatedProvider, *, actor: str) -> dict[str, Any]:
        """After a restore: reconcile everything, then lift the release quarantine."""
        results = self.reconcile(provider, actor=actor)
        unresolved = self.db.query("SELECT id FROM payment_intents WHERE status IN ('submitted','outcome_unknown')")
        if unresolved:
            return {"quarantine_lifted": False, "unresolved": [u["id"] for u in unresolved], "results": results}
        with self.db.transaction() as conn:
            ws = self.db.workspace()
            conn.execute("UPDATE workspace SET reconciled_epoch=?, updated_at=? WHERE id=1", (ws["recovery_epoch"], utcnow_iso()))
            self.audit.record(actor, "recovery.reconciled", "workspace", ws["workspace_id"], {"recovery_epoch": ws["recovery_epoch"], "results": results})
        return {"quarantine_lifted": True, "unresolved": [], "results": results}

    # ---- provider events ------------------------------------------------------- #

    def ingest_event(self, event: dict[str, Any], *, actor: str) -> dict[str, Any]:
        """Authenticated-by-construction simulator events; duplicates are ignored by event id."""
        intent = self.db.one("SELECT * FROM payment_intents WHERE provider_ref=?", (event["provider_ref"],))
        if intent is None:
            raise PaymentError(f"event {event['id']} references unknown provider_ref {event['provider_ref']}")
        if self.db.one("SELECT id FROM provider_events WHERE id=?", (event["id"],)):
            self.audit.record(actor, "provider_event.duplicate", "payment_intent", intent["id"], {"event_id": event["id"]})
            return {"intent_id": intent["id"], "applied": False, "reason": "duplicate event"}
        period = self.db.one("SELECT id FROM periods WHERE status='open' ORDER BY start_date DESC LIMIT 1")
        if period is None:
            raise PaymentError("no open period")
        project_id = self.db.one("SELECT project_id FROM commitments WHERE supplier_id=? ORDER BY created_at DESC LIMIT 1", (intent["party_id"],))["project_id"]
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO provider_events (id, intent_id, kind, payload_json, received_at) VALUES (?,?,?,?,?)", (event["id"], intent["id"], event["kind"], canonical_json(event), utcnow_iso()))
            if event["kind"] == "settled" and intent["status"] == "accepted":
                self.ledger.post(
                    period_id=period["id"], description=f"Payment settled ({intent['provider_ref']})",
                    lines=[
                        {"account": "1200", "debit": intent["amount"], "project_id": project_id, "party_id": intent["party_id"], "memo": "clearing settled"},
                        {"account": "1000", "credit": intent["amount"], "project_id": project_id, "party_id": intent["party_id"], "memo": "bank disbursement"},
                    ],
                    source_type="provider_event", source_id=event["id"], source_version="1", posted_by=actor,
                )
                conn.execute("UPDATE payment_intents SET status='settled', resolved_at=? WHERE id=?", (utcnow_iso(), intent["id"]))
            elif event["kind"] == "returned" and intent["status"] in ("accepted", "settled"):
                src = "1000" if intent["status"] == "settled" else "1200"
                self.ledger.post(
                    period_id=period["id"], description=f"Payment returned ({intent['provider_ref']}): {event.get('reason', '')}",
                    lines=[
                        {"account": src, "debit": intent["amount"], "project_id": project_id, "party_id": intent["party_id"], "memo": "funds returned"},
                        {"account": "2000", "credit": intent["amount"], "project_id": project_id, "party_id": intent["party_id"], "memo": "payable reinstated"},
                    ],
                    source_type="provider_event", source_id=event["id"], source_version="1", posted_by=actor,
                )
                conn.execute("UPDATE payment_intents SET status='returned', resolved_at=? WHERE id=?", (utcnow_iso(), intent["id"]))
                if intent["bill_id"]:
                    conn.execute("UPDATE bills SET status='posted' WHERE id=? AND status='paid'", (intent["bill_id"],))
            else:
                self.audit.record(actor, "provider_event.ignored", "payment_intent", intent["id"], {"event_id": event["id"], "kind": event["kind"], "intent_status": intent["status"]})
                return {"intent_id": intent["id"], "applied": False, "reason": f"{event['kind']} not applicable to {intent['status']}"}
            self.audit.record(actor, f"provider_event.{event['kind']}", "payment_intent", intent["id"], {"event_id": event["id"]})
        return {"intent_id": intent["id"], "applied": True}
