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

Scope (catalog entry ``payments_scope``): every intent carries the project it
pays for, the record it settles (``source_type``/``source_id``) and the payable
control account it draws down (``payable_account``; ``2000`` for supplier bills
and released retainage, ``2100`` for staff reimbursements).  Acceptance posts
``Dr payable_account / Cr 1200``, settlement ``Dr 1200 / Cr 1000`` and a return
reinstates ``payable_account`` -- always on the intent's own project, never on a
project guessed from the payee's commitments (that lookup survives only for
intents created before the scope columns existed).  Every new intent must
resolve to a project, and when the approval manifest binds a project or a
payable account the intent must use exactly those.

Modules that own a source type can ``subscribe`` to status changes of their
intents.  A handler runs inside the transaction that changes the intent, under
its own savepoint: normally the source record moves in the same commit as the
books.  If a handler raises, only its own writes are undone, the failure is
audited (``payment.listener_failed``) and the intent change still commits --
the provider has already acted, so the core books must follow it, and one
source module's defect must never stall other payments.  The source record is
then out of step with its intent, which that module's close check reports and
its repair path (re-deriving from the intent) fixes.
"""
from __future__ import annotations

from typing import Any, Callable

from ..core.approvals import build_manifest
from ..core.audit import Audit
from ..core.commands import Commands
from ..core.db import Database, register_schema_version
from ..core.ids import canonical_json, hash_json, new_id, utcnow_iso
from ..core.money import fmt, money
from .ledger import Ledger

# The foundation schema is applied history (checksummed, append-only), so the
# scope columns arrive as their own catalog entry, registered at import time.
SCOPE_SCHEMA_NAME = "payments_scope"
SCOPE_SCHEMA_STATEMENTS = [
    "ALTER TABLE payment_intents ADD COLUMN project_id TEXT",
    "ALTER TABLE payment_intents ADD COLUMN source_type TEXT",
    "ALTER TABLE payment_intents ADD COLUMN source_id TEXT",
    "ALTER TABLE payment_intents ADD COLUMN payable_account TEXT",
]
register_schema_version(SCOPE_SCHEMA_NAME, SCOPE_SCHEMA_STATEMENTS)

DEFAULT_PAYABLE_ACCOUNT = "2000"
IN_PROGRESS_STATES = ("approved", "queued", "submitted", "outcome_unknown")

# An intent's ``note`` starts with its purpose label ("bill payment", "retainage
# release payment", ...); status reasons are appended after this separator so
# the label survives every status change (AP reconciliation matches on it).
_REASON_SEP = " | "


def _label(note: str | None) -> str:
    return (note or "").split(_REASON_SEP, 1)[0]


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
        self._listeners: dict[str, list[Callable[..., None]]] = {}
        self._savepoint_seq = 0

    # ---- source listeners ------------------------------------------------------ #

    def subscribe(self, source_type: str, handler: Callable[..., None]) -> None:
        """Call ``handler(intent, actor=...)`` whenever an intent whose
        ``source_type`` matches changes status (accepted, settled, returned,
        failed, outcome unknown).  The handler runs inside the transaction that
        changes the intent, under its own savepoint; if it raises, only its own
        writes roll back, the failure is audited and the intent change commits."""
        handlers = self._listeners.setdefault(source_type, [])
        if handler not in handlers:
            handlers.append(handler)

    def _notify(self, intent_id: str, *, actor: str) -> list[dict[str, str]]:
        """Run the source module's handlers for ``intent_id``; returns the failures."""
        failures: list[dict[str, str]] = []
        with self.db.transaction() as conn:
            intent = self.db.one("SELECT * FROM payment_intents WHERE id=?", (intent_id,))
            if intent is None or not intent.get("source_type"):
                return failures
            for handler in list(self._listeners.get(intent["source_type"], [])):
                self._savepoint_seq += 1
                savepoint = f"payment_listener_{self._savepoint_seq}"
                conn.execute(f"SAVEPOINT {savepoint}")
                try:
                    handler(intent, actor=actor)
                except Exception as exc:  # isolate the source module; never undo what the provider did
                    if not conn.in_transaction:  # the engine already rolled everything back: nothing left to isolate
                        raise
                    conn.execute(f"ROLLBACK TO {savepoint}")
                    conn.execute(f"RELEASE {savepoint}")
                    failure = {
                        "source_type": intent["source_type"], "source_id": intent["source_id"], "intent_status": intent["status"],
                        "handler": getattr(handler, "__qualname__", repr(handler)), "error": f"{type(exc).__name__}: {exc}",
                    }
                    self.audit.record(actor, "payment.listener_failed", "payment_intent", intent_id, failure)
                    failures.append(failure)
                else:
                    conn.execute(f"RELEASE {savepoint}")
        return failures

    @staticmethod
    def _result(intent_id: str, status: str, failures: list[dict[str, str]], **extra: Any) -> dict[str, Any]:
        out = {"intent_id": intent_id, "status": status, **extra}
        if failures:
            out["listener_errors"] = failures
        return out

    # ---- scope ------------------------------------------------------------------ #

    @staticmethod
    def _is_legacy(intent: dict[str, Any]) -> bool:
        """Created before the scope columns existed (create_intent always records a payable account)."""
        return not intent.get("payable_account")

    def _project_for(self, intent: dict[str, Any]) -> str | None:
        """The project an intent's postings belong to.  Intents carry it.  The
        lookups below serve only legacy intents created before the scope columns
        existed; a scoped intent is never attributed to a project guessed from the
        payee's commitments, and a payee with no commitment (an employee) yields
        None, never a crash."""
        if intent.get("project_id"):
            return intent["project_id"]
        if not self._is_legacy(intent):
            return None
        if intent.get("bill_id"):
            row = self.db.one("SELECT c.project_id FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE b.id=?", (intent["bill_id"],))
            if row is not None:
                return row["project_id"]
        row = self.db.one("SELECT project_id FROM commitments WHERE supplier_id=? ORDER BY created_at DESC LIMIT 1", (intent["party_id"],))
        return row["project_id"] if row else None

    @staticmethod
    def _payable_for(intent: dict[str, Any]) -> str:
        return intent.get("payable_account") or DEFAULT_PAYABLE_ACCOUNT

    def _resolve_scope(self, manifest: dict[str, Any], *, bill_id: str | None, project_id: str | None,
                       source_type: str | None, source_id: str | None, payable_account: str) -> dict[str, Any]:
        if (source_type is None) != (source_id is None):
            raise PaymentError("source_type and source_id must be given together")
        for label, value in (("project_id", project_id), ("source_type", source_type), ("source_id", source_id)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise PaymentError(f"{label} must be a non-empty string when given")
        subject = manifest.get("subject") or {}
        derived_project = None
        if bill_id:
            row = self.db.one("SELECT c.project_id FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE b.id=?", (bill_id,))
            if row is None:
                raise PaymentError(f"unknown bill {bill_id}")
            derived_project = row["project_id"]
            if source_type is None:
                source_type, source_id = "bill", bill_id
        elif subject.get("type") == "commitment":
            row = self.db.one("SELECT project_id FROM commitments WHERE id=?", (subject.get("id"),))
            if row is None:
                raise PaymentError(f"unknown commitment {subject.get('id')}")
            derived_project = row["project_id"]
            if source_type is None:
                source_type, source_id = "retainage_release", subject["id"]
        if project_id is None:
            project_id = derived_project
        elif derived_project is not None and project_id != derived_project:
            raise PaymentError(f"project {project_id} does not match the paid record's project {derived_project}")
        if project_id is None:
            raise PaymentError("a payment intent must name the project it pays for: pass project_id, or pay a bill or released retainage")
        if self.db.one("SELECT id FROM projects WHERE id=?", (project_id,)) is None:
            raise PaymentError(f"unknown project {project_id}")
        if source_id is not None and subject.get("id") and source_id != subject["id"]:
            raise PaymentError(f"the approval manifest covers {subject.get('type')} {subject['id']}, not {source_type} {source_id}")
        if not isinstance(payable_account, str) or not payable_account:
            raise PaymentError("payable_account is required")
        acct = self.db.one("SELECT type FROM accounts WHERE code=?", (payable_account,))
        if acct is None or acct["type"] != "liability":
            raise PaymentError(f"payable account {payable_account} is not a liability account in the chart")
        # where the approver saw a project or payable account, the intent books exactly there
        bindings = manifest.get("bindings") or {}
        if "project_id" in bindings and bindings["project_id"] != project_id:
            raise PaymentError(f"the approval manifest binds project {bindings['project_id']}, not {project_id}")
        if "payable_account" in bindings and bindings["payable_account"] != payable_account:
            raise PaymentError(f"the approval manifest binds payable account {bindings['payable_account']}, not {payable_account}")
        return {"project_id": project_id, "source_type": source_type, "source_id": source_id, "payable_account": payable_account}

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

    def create_intent(self, *, manifest: dict[str, Any], approval_id: str, bill_id: str | None, note: str, actor: str,
                      project_id: str | None = None, source_type: str | None = None, source_id: str | None = None,
                      payable_account: str = DEFAULT_PAYABLE_ACCOUNT) -> dict[str, Any]:
        """Create the intent and its outbox row atomically.  ``approval_id`` must
        already be consumed by the caller against ``manifest``.

        ``project_id`` defaults to the paid bill's (or released retainage's)
        project and is required otherwise; ``source_type``/``source_id`` default
        to the bill or the commitment; ``payable_account`` is the liability the
        payment draws down when the provider accepts it.  A project or payable
        account the manifest binds must match.  Only one intent per source may be
        in progress at a time."""
        ok, why = self.release_allowed()
        if not ok:
            raise ReleaseQuarantined(why)
        dest = manifest.get("destination") or {}
        if not dest.get("party_id"):
            raise PaymentError("the approval manifest names no payee destination")
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
        scope = self._resolve_scope(manifest, bill_id=bill_id, project_id=project_id, source_type=source_type, source_id=source_id, payable_account=payable_account)
        logical_op_id = f"pay:{approval_id}"
        payload = {"party_id": party["id"], "destination": party["destination"], "destination_version": party["destination_version"], "amount": fmt(amount), "bill_id": bill_id}
        payload_hash = hash_json(payload)
        intent_id = new_id("pay")
        with self.db.transaction() as conn:
            if conn.execute("SELECT id FROM payment_intents WHERE logical_op_id=?", (logical_op_id,)).fetchone():
                raise PaymentError("an intent already exists for this approval")
            if scope["source_type"]:
                live = conn.execute(
                    f"SELECT id FROM payment_intents WHERE source_type=? AND source_id=? AND status IN ({','.join('?' * len(IN_PROGRESS_STATES))})",
                    (scope["source_type"], scope["source_id"], *IN_PROGRESS_STATES),
                ).fetchone()
                if live:
                    raise PaymentError(f"payment intent {live['id']} for {scope['source_type']} {scope['source_id']} is still in progress")
            ws = self.db.workspace()
            conn.execute(
                """INSERT INTO payment_intents (id, bill_id, party_id, amount, destination, destination_version, status, approval_id, logical_op_id, payload_hash, recovery_epoch, created_at, note,
                                                project_id, source_type, source_id, payable_account)
                   VALUES (?,?,?,?,?,?,'approved',?,?,?,?,?,?,?,?,?,?)""",
                (intent_id, bill_id, party["id"], fmt(amount), party["destination"], party["destination_version"], approval_id, logical_op_id, payload_hash, ws["recovery_epoch"], utcnow_iso(), _label(note),
                 scope["project_id"], scope["source_type"], scope["source_id"], scope["payable_account"]),
            )
            ob = self.commands.enqueue("payment", {"intent_id": intent_id, "logical_op_id": logical_op_id, "payload_hash": payload_hash})
            conn.execute("UPDATE payment_intents SET status='queued', outbox_id=? WHERE id=?", (ob["id"], intent_id))
            self.audit.record(actor, "payment.queued", "payment_intent", intent_id, {"amount": fmt(amount), "party_id": party["id"], "approval_id": approval_id, "outbox_id": ob["id"], **scope})
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
                failures = self._set_status(intent["id"], "outcome_unknown", actor=actor, note=f"timeout after submission: {exc}")
                results.append(self._result(intent["id"], "outcome_unknown", failures))
                continue
            except ConnectionError as exc:
                failures = self._set_status(intent["id"], "outcome_unknown", actor=actor, note=f"provider unreachable: {exc}")
                results.append(self._result(intent["id"], "outcome_unknown", failures))
                continue
            if resp["outcome"] == "accepted":
                failures = self._accept(intent["id"], provider_ref=resp["provider_ref"], actor=actor)
                results.append(self._result(intent["id"], "accepted", failures, provider_ref=resp["provider_ref"]))
            else:
                failures = self._set_status(intent["id"], "failed", actor=actor, note=resp.get("reason", "rejected"))
                results.append(self._result(intent["id"], "failed", failures))
        return results

    def _set_status(self, intent_id: str, status: str, *, actor: str, note: str = "", provider_ref: str | None = None, resolved: bool = False) -> list[dict[str, str]]:
        with self.db.transaction() as conn:
            current = conn.execute("SELECT note FROM payment_intents WHERE id=?", (intent_id,)).fetchone()
            label = _label(current["note"] if current else "")
            full_note = f"{label}{_REASON_SEP}{note}" if label and note else (note or label)
            conn.execute(
                "UPDATE payment_intents SET status=?, note=?, provider_ref=COALESCE(?, provider_ref), resolved_at=CASE WHEN ? THEN ? ELSE resolved_at END WHERE id=?",
                (status, full_note, provider_ref, 1 if resolved else 0, utcnow_iso(), intent_id),
            )
            self.audit.record(actor, f"payment.{status}", "payment_intent", intent_id, {"note": note, "provider_ref": provider_ref})
            return self._notify(intent_id, actor=actor)

    def _accept(self, intent_id: str, *, provider_ref: str, actor: str) -> list[dict[str, str]]:
        with self.db.transaction() as conn:
            intent = self.get(intent_id)
            if intent["status"] in ("accepted", "settled", "returned") or intent["journal_id"]:
                return []
            project_id = self._project_for(intent)
            payable = self._payable_for(intent)
            period = self.db.one("SELECT id FROM periods WHERE status='open' ORDER BY start_date DESC LIMIT 1")
            if period is None:
                raise PaymentError("no open period to record the accepted payment")
            j = self.ledger.post(
                period_id=period["id"],
                description=f"Payment accepted by provider ({provider_ref})",
                lines=[
                    {"account": payable, "debit": intent["amount"], "project_id": project_id, "party_id": intent["party_id"], "memo": "payable settled via provider"},
                    {"account": "1200", "credit": intent["amount"], "project_id": project_id, "party_id": intent["party_id"], "memo": "provider clearing"},
                ],
                source_type="payment_intent", source_id=intent_id, source_version="1", posted_by=actor, approval_id=intent["approval_id"],
            )
            conn.execute("UPDATE payment_intents SET status='accepted', provider_ref=?, journal_id=?, note=? WHERE id=?", (provider_ref, j["id"], _label(intent["note"]), intent_id))
            if intent["bill_id"]:
                conn.execute("UPDATE bills SET status='paid' WHERE id=? AND status='posted'", (intent["bill_id"],))
            self.audit.record(actor, "payment.accepted", "payment_intent", intent_id, {"provider_ref": provider_ref, "journal_id": j["id"], "project_id": project_id, "payable_account": payable})
            return self._notify(intent_id, actor=actor)

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
                failures = self._set_status(intent["id"], "outcome_unknown", actor=actor, note=f"reconciliation pending: {exc}; held for treasury review")
                results.append(self._result(intent["id"], "outcome_unknown", failures))
                continue
            if found["found"]:
                failures = self._accept(intent["id"], provider_ref=found["provider_ref"], actor=actor)
                results.append(self._result(intent["id"], "accepted", failures, provider_ref=found["provider_ref"]))
            else:
                failures = self._set_status(intent["id"], "failed", actor=actor, note="provider has no record of the submission; obligation remains open", resolved=True)
                results.append(self._result(intent["id"], "failed", failures))
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
        """Authenticated-by-construction simulator events; duplicates are ignored by event id.
        The intent is read under the write lock, so concurrent deliveries cannot both
        act on the same intent status."""
        with self.db.transaction() as conn:
            intent = self.db.one("SELECT * FROM payment_intents WHERE provider_ref=?", (event["provider_ref"],))
            if intent is None:
                raise PaymentError(f"event {event['id']} references unknown provider_ref {event['provider_ref']}")
            if self.db.one("SELECT id FROM provider_events WHERE id=?", (event["id"],)):
                self.audit.record(actor, "provider_event.duplicate", "payment_intent", intent["id"], {"event_id": event["id"]})
                return {"intent_id": intent["id"], "applied": False, "reason": "duplicate event"}
            period = self.db.one("SELECT id FROM periods WHERE status='open' ORDER BY start_date DESC LIMIT 1")
            if period is None:
                raise PaymentError("no open period")
            project_id = self._project_for(intent)
            payable = self._payable_for(intent)
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
                        {"account": payable, "credit": intent["amount"], "project_id": project_id, "party_id": intent["party_id"], "memo": "payable reinstated"},
                    ],
                    source_type="provider_event", source_id=event["id"], source_version="1", posted_by=actor,
                )
                conn.execute("UPDATE payment_intents SET status='returned', resolved_at=? WHERE id=?", (utcnow_iso(), intent["id"]))
                if intent["bill_id"]:
                    conn.execute("UPDATE bills SET status='posted' WHERE id=? AND status='paid'", (intent["bill_id"],))
            else:
                self.audit.record(actor, "provider_event.ignored", "payment_intent", intent["id"], {"event_id": event["id"], "kind": event["kind"], "intent_status": intent["status"]})
                return {"intent_id": intent["id"], "applied": False, "reason": f"{event['kind']} not applicable to {intent['status']}"}
            self.audit.record(actor, f"provider_event.{event['kind']}", "payment_intent", intent["id"], {"event_id": event["id"], "project_id": project_id, "payable_account": payable})
            failures = self._notify(intent["id"], actor=actor)
        out = {"intent_id": intent["id"], "applied": True}
        if failures:
            out["listener_errors"] = failures
        return out
