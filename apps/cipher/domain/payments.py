"""Payment intents, the dispatch outbox, a payment simulator, execution controls and reconciliation.

State machine (plan section 6, "Execution and recovery"):

    approved -> queued -> submitted -> accepted -> settled
                  |          |            \\-> returned      (settled -> returned too)
                  |          +-> outcome_unknown -> (reconcile) accepted | failed
                  |          +-> failed
                  +-> canceled (only before dispatch; also when an adopted transfer supersedes it)
                  +-> failed   (payee re-verification, provider fee or transfer-terms check at dispatch)
    (adopted)  submitted -> accepted ...   (a provider transfer recorded by payment.adopt_transfer;
                                            it has no outbox row and is never submitted by Cipher)

* an intent is created together with its outbox row in one transaction;
* only a pending outbox row can be dispatched, and dispatching a row twice is
  impossible because dispatch claims it (``queued`` -> ``submitted``) before the
  provider call;
* the provider is called with Cipher's logical operation id, so a replay of the
  same intent cannot create a second transfer;
* a timeout after submission is *outcome unknown*: nothing is retried until
  reconciliation establishes the result;
* after a restore (recovery epoch bump) every release is quarantined until the
  owner runs recovery reconciliation, which also looks every *queued* intent up
  at the provider first (a restored older backup may hold an intent whose
  transfer the live workspace already made): found -> recorded as submitted and
  accepted without a second submission; not found -> left queued.  Recovery then
  lists the provider's transfers for this workspace: a transfer this copy has no
  intent for (the live workspace made it after the backup, possibly under an
  approval this copy never saw) keeps the quarantine, because releasing from this
  copy could pay the same obligation twice.  Each such transfer is recorded with
  the owner-only approval ``payment.adopt_transfer`` (subject: the provider
  reference, or ``<provider_ref>=<source_type>:<source_id>`` to name a re-keyed
  local record): the transfer is booked against the record it paid (bill,
  released retainage, or a plugin source that registered an adoption path) with
  one acceptance journal plus whatever settlement or return the provider reports,
  and any local *queued* intent for the same record that the provider never saw is
  canceled as superseded.  Recovery also holds the quarantine while missed
  callbacks cannot be caught up (no webhook secret, provider unreachable).

Execution controls (catalog entry ``payments_controls``):

* ``release_allowed()`` is False -- and ``create_intent`` / ``dispatch_pending``
  refuse before any provider call -- when the workspace holds no effective write
  authority (``ReleaseQuarantined``), while the restore quarantine is active
  (``ReleaseQuarantined``) or while the kill switch is engaged (``KillSwitchEngaged``);
* ``engage_kill_switch`` is protective and takes effect at once, with no approval;
  lifting it is the approval-bound core operation ``payment.resume_releases``
  (subject ``payments``), whose manifest binds the controls version and reason.
  A schema trigger refuses any lift that is not backed by a consumed approval whose
  manifest binds exactly the engaged controls version and reason, that was granted
  and consumed (approver, timestamps and the grant/consume audit entries present);
  ``payments_controls_resume_binding`` also guards the resume approvals themselves
  (inserted only as pending requests, never replaced or deleted, manifest immutable,
  status only pending -> granted -> consumed or expired/invalidated), and
  the ``payments_controls_guards`` entry refuses every insert that would *replace* a
  stored controls row, history row or provider event (SQLite's REPLACE deletes the
  conflicting row without firing DELETE or UPDATE triggers).  Raw SQL with full
  database access can still emulate every governed step; what the schema guarantees
  is that no lift can cite a missing, stale, ungranted or reused approval;
* ``cancel_intent`` withdraws a queued (undispatched) intent: the intent becomes
  ``canceled``, its outbox row ``failed`` ("canceled: ..."), and the obligation stays
  open (a bill stays ``posted``; a reimbursement payment goes back to ``draft`` and
  can be approved again, and the claim's outstanding balance is open again).  It is refused on a
  copy without write authority and while the restore quarantine is active (a restored
  copy's local queue is exactly what recovery must not trust: the live workspace may
  already have paid that intent), and it asks the bound provider first: a transfer the
  provider already holds is never canceled, and an unreachable provider refuses the
  cancel.  The kill switch does not block a cancel (both are protective);
* dispatch re-verifies the payee: a destination or destination version that
  differs from the intent's fails the intent ("destination changed after approval")
  and nothing is submitted; a provider fee that differs from the approved one, an
  approved value date that has passed (an intent held for days by the kill switch
  must be approved again) or a project entity or currency that changed fails it
  the same way.  The checks run inside the transaction that claims the intent,
  so a destination re-verified concurrently cannot slip between check and claim.
  The provider receives the approved value date and currency (both also in the
  payload hash) and a reference naming this workspace, the intent and the record
  it pays, which is what recovery uses to attribute transfers it never recorded;
* provider callbacks are authenticated: every event the simulator emits carries an
  HMAC-SHA256 ``signature`` over the canonical JSON of the event without that field,
  keyed with the provider's per-instance ``webhook_secret``.  ``ingest_event``
  verifies it against ``Payments.webhook_secret`` (set by the service from the
  provider) and rejects unsigned, forged or malformed events (audited) before any
  state change; duplicate event ids stay idempotent.  A correctly signed event that
  contradicts Cipher's records (an unknown ``provider_ref``, or an amount that differs
  from the intent's) is rejected and audited the same way;
* ``reconcile`` also detects missing callbacks: when the provider reports an
  accepted intent settled or returned (or a settled one returned) that Cipher has
  not recorded, it ingests a signed reconciliation event with the deterministic id
  ``recon_<provider_ref>_<kind>``, so the books catch up exactly once.  A return
  of a transfer the provider had settled first carries ``settled_before_return``;
  when Cipher never recorded that settlement (callback lost) the settlement is
  booked first from a derived ``recon_<provider_ref>_settled`` event, so the fee
  and the bank leg match the path where both callbacks arrived;
* manifests for ``payment.release``, ``payment.release_retainage`` (and, through
  ``payment_terms``, ``reimbursement.pay``) bind the project's entity and currency,
  the value date (UTC today) and the provider fee (``SimulatedProvider.fee_for``),
  so a changed fee, entity or date invalidates the approval.  The approved fee is
  stored on the intent and posted at settlement (Dr 6000 fee / Cr 1000).

Provider clearing (``clearing_items``): account 1200 is debit-normal.  Acceptance
credits it (Dr payable / Cr 1200), settlement debits it back (Dr 1200 / Cr 1000) and
a return before settlement debits it back too (Dr 1200 / Cr payable).  Accepted but
unsettled intents therefore appear as a *negative* control balance; the subledger
is expressed in the same sign (minus the in-transit amount) so like is compared
with like.

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

import hashlib
import hmac
import inspect
import secrets
import weakref
from typing import Any, Callable, NoReturn

from ..core.approvals import build_manifest
from ..core.audit import Audit
from ..core.commands import Commands
from ..core.db import Database, register_schema_version
from ..core.ids import canonical_json, hash_json, new_id, utcnow, utcnow_iso
from ..core.money import ZERO, MoneyError, fmt, money, total
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

# The payment-release kill switch: one versioned controls row plus an append-only
# history.  Every change appends a history row first and bumps the version by one;
# lifting the switch needs a history row that cites a consumed
# ``payment.resume_releases`` approval (each approval lifts it at most once).
CONTROLS_SCHEMA_NAME = "payments_controls"
CONTROLS_SCHEMA_STATEMENTS = [
    """CREATE TABLE payments_controls (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        kill_switch INTEGER NOT NULL DEFAULT 0 CHECK (kill_switch IN (0, 1)),
        version INTEGER NOT NULL,
        reason TEXT NOT NULL,
        changed_by TEXT NOT NULL,
        changed_at TEXT NOT NULL
    )""",
    """CREATE TABLE payments_controls_history (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        version INTEGER NOT NULL UNIQUE,
        kill_switch INTEGER NOT NULL CHECK (kill_switch IN (0, 1)),
        reason TEXT NOT NULL,
        changed_by TEXT NOT NULL,
        changed_at TEXT NOT NULL,
        approval_id TEXT REFERENCES approvals(id)
    )""",
    "CREATE UNIQUE INDEX payments_controls_history_approval ON payments_controls_history(approval_id) WHERE approval_id IS NOT NULL",
    """INSERT INTO payments_controls_history (version, kill_switch, reason, changed_by, changed_at)
        VALUES (1, 0, 'initial: releases allowed', 'system', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))""",
    """INSERT INTO payments_controls (id, kill_switch, version, reason, changed_by, changed_at)
        VALUES (1, 0, 1, 'initial: releases allowed', 'system', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))""",
    """CREATE TRIGGER payments_controls_history_next_version BEFORE INSERT ON payments_controls_history
        WHEN NEW.version IS NOT (SELECT version FROM payments_controls WHERE id = 1) + 1
        BEGIN SELECT RAISE(ABORT, 'payment controls history only appends the next version'); END""",
    "CREATE TRIGGER payments_controls_history_no_update BEFORE UPDATE ON payments_controls_history BEGIN SELECT RAISE(ABORT, 'payment controls history is append-only'); END",
    "CREATE TRIGGER payments_controls_history_no_delete BEFORE DELETE ON payments_controls_history BEGIN SELECT RAISE(ABORT, 'payment controls history is append-only'); END",
    "CREATE TRIGGER payments_controls_no_delete BEFORE DELETE ON payments_controls BEGIN SELECT RAISE(ABORT, 'payment controls are never deleted'); END",
    """CREATE TRIGGER payments_controls_versioned BEFORE UPDATE ON payments_controls
        WHEN NEW.id IS NOT OLD.id OR NEW.version IS NOT OLD.version + 1 OR NOT EXISTS (
            SELECT 1 FROM payments_controls_history h
            WHERE h.version = NEW.version AND h.kill_switch = NEW.kill_switch AND h.reason = NEW.reason AND h.changed_by = NEW.changed_by)
        BEGIN SELECT RAISE(ABORT, 'payment controls change only by appending the next version to their history'); END""",
    """CREATE TRIGGER payments_controls_resume_needs_approval BEFORE UPDATE ON payments_controls
        WHEN OLD.kill_switch = 1 AND NEW.kill_switch = 0 AND NOT EXISTS (
            SELECT 1 FROM payments_controls_history h JOIN approvals a ON a.id = h.approval_id
            WHERE h.version = NEW.version AND h.kill_switch = 0
              AND a.operation = 'payment.resume_releases' AND a.status = 'consumed')
        BEGIN SELECT RAISE(ABORT, 'the payment kill switch is lifted only through a consumed payment.resume_releases approval'); END""",
]
register_schema_version(CONTROLS_SCHEMA_NAME, CONTROLS_SCHEMA_STATEMENTS)

# What the approver saw about the transfer itself: the fee, the value date, the
# entity and the currency.  Stored on the intent so dispatch and settlement use
# exactly the approved terms.
TERMS_SCHEMA_NAME = "payments_terms"
TERMS_SCHEMA_STATEMENTS = [
    "ALTER TABLE payment_intents ADD COLUMN fee TEXT NOT NULL DEFAULT '0.00'",
    "ALTER TABLE payment_intents ADD COLUMN value_date TEXT",
    "ALTER TABLE payment_intents ADD COLUMN entity TEXT",
    "ALTER TABLE payment_intents ADD COLUMN currency TEXT",
]
register_schema_version(TERMS_SCHEMA_NAME, TERMS_SCHEMA_STATEMENTS)

# SQLite's REPLACE conflict resolution deletes the conflicting row without firing
# DELETE or UPDATE triggers (recursive_triggers is off), so ``INSERT OR REPLACE`` /
# ``REPLACE INTO`` could lift the kill switch with no approval, rewrite or drop a
# controls history row (including one that cites a consumed resume approval, which
# would let that approval lift the switch twice) or rewrite a stored provider event.
# BEFORE INSERT triggers fire before REPLACE deletes anything: refuse every insert
# that collides with a stored row on any unique key (which also covers OR IGNORE and
# upserts).  A separate entry, because applied entries are append-only.
CONTROLS_GUARDS_SCHEMA_NAME = "payments_controls_guards"
CONTROLS_GUARDS_SCHEMA_STATEMENTS = [
    """CREATE TRIGGER payments_controls_singleton_no_replace BEFORE INSERT ON payments_controls
        WHEN EXISTS (SELECT 1 FROM payments_controls)
        BEGIN SELECT RAISE(ABORT, 'payment controls are one row that is never replaced; they change only by appending the next version to their history'); END""",
    """CREATE TRIGGER payments_controls_history_no_replace BEFORE INSERT ON payments_controls_history
        WHEN EXISTS (SELECT 1 FROM payments_controls_history h
                     WHERE h.seq = NEW.seq OR h.version = NEW.version OR (NEW.approval_id IS NOT NULL AND h.approval_id = NEW.approval_id))
        BEGIN SELECT RAISE(ABORT, 'payment controls history is append-only: a stored row already has this seq, version or approval'); END""",
    """CREATE TRIGGER payments_provider_events_no_replace BEFORE INSERT ON provider_events
        WHEN EXISTS (SELECT 1 FROM provider_events WHERE id = NEW.id)
        BEGIN SELECT RAISE(ABORT, 'provider events are immutable: an event with this id is already stored'); END""",
]
register_schema_version(CONTROLS_GUARDS_SCHEMA_NAME, CONTROLS_GUARDS_SCHEMA_STATEMENTS)

# The lift trigger above only asked for *a* consumed resume approval, and the core
# approvals table carries no triggers of its own: a raw UPDATE could promote a stale
# (invalidated) approval granted for an earlier controls version to 'consumed', or a
# raw INSERT could forge a consumed row, and either lifted the switch.  This entry
# (applied entries are append-only, so it replaces the trigger by name) binds the lift
# to an approval whose manifest names exactly the engaged controls version and reason
# and that was granted and consumed (approver, timestamps and the grant/consume audit
# entries present), and guards the resume approvals themselves: inserted only as
# pending requests, never replaced or deleted, manifest immutable, status moving only
# pending -> granted -> consumed (or expiring / being invalidated, never revived).
CONTROLS_BINDING_SCHEMA_NAME = "payments_controls_resume_binding"
CONTROLS_BINDING_SCHEMA_STATEMENTS = [
    "DROP TRIGGER IF EXISTS payments_controls_resume_needs_approval",
    """CREATE TRIGGER payments_controls_resume_needs_approval BEFORE UPDATE ON payments_controls
        WHEN OLD.kill_switch = 1 AND NEW.kill_switch = 0 AND NOT EXISTS (
            SELECT 1 FROM payments_controls_history h JOIN approvals a ON a.id = h.approval_id
            WHERE h.version = NEW.version AND h.kill_switch = 0
              AND a.operation = 'payment.resume_releases' AND a.status = 'consumed'
              AND a.subject_type = 'payment_controls' AND a.subject_id = 'payments'
              AND a.approver IS NOT NULL AND a.granted_at IS NOT NULL AND a.consumed_at IS NOT NULL AND a.consumed_by IS NOT NULL
              AND json_valid(a.manifest_json)
              AND json_extract(a.manifest_json, '$.operation') = 'payment.resume_releases'
              AND json_extract(a.manifest_json, '$.bindings.controls_version') = OLD.version
              AND json_extract(a.manifest_json, '$.bindings.reason') = OLD.reason
              AND EXISTS (SELECT 1 FROM audit_log g WHERE g.entity_type = 'approval' AND g.entity_id = a.id AND g.action = 'approval.granted')
              AND EXISTS (SELECT 1 FROM audit_log g WHERE g.entity_type = 'approval' AND g.entity_id = a.id AND g.action = 'approval.consumed'))
        BEGIN SELECT RAISE(ABORT, 'the payment kill switch is lifted only through a consumed payment.resume_releases approval bound to the engaged controls version and reason'); END""",
    """CREATE TRIGGER payments_resume_approval_starts_pending BEFORE INSERT ON approvals
        WHEN NEW.operation = 'payment.resume_releases' AND (NEW.status IS NOT 'pending' OR NEW.approver IS NOT NULL OR NEW.granted_at IS NOT NULL
             OR NEW.consumed_at IS NOT NULL OR NEW.consumed_by IS NOT NULL)
        BEGIN SELECT RAISE(ABORT, 'a payment.resume_releases approval is recorded only as a pending request'); END""",
    """CREATE TRIGGER payments_resume_approval_no_replace BEFORE INSERT ON approvals
        WHEN EXISTS (SELECT 1 FROM approvals a WHERE a.operation = 'payment.resume_releases' AND (a.id = NEW.id OR a.nonce = NEW.nonce))
        BEGIN SELECT RAISE(ABORT, 'payment.resume_releases approvals are never replaced'); END""",
    """CREATE TRIGGER payments_resume_approval_lifecycle BEFORE UPDATE ON approvals
        WHEN (OLD.operation = 'payment.resume_releases' OR NEW.operation = 'payment.resume_releases') AND (
            NEW.id IS NOT OLD.id OR NEW.operation IS NOT OLD.operation OR NEW.subject_type IS NOT OLD.subject_type OR NEW.subject_id IS NOT OLD.subject_id
            OR NEW.actor_role IS NOT OLD.actor_role OR NEW.manifest_json IS NOT OLD.manifest_json OR NEW.manifest_hash IS NOT OLD.manifest_hash
            OR NEW.material_hash IS NOT OLD.material_hash OR NEW.policy_version IS NOT OLD.policy_version OR NEW.nonce IS NOT OLD.nonce
            OR NEW.requested_by IS NOT OLD.requested_by OR NEW.requested_at IS NOT OLD.requested_at OR NEW.expires_at IS NOT OLD.expires_at
            OR NOT (
                (NEW.status = OLD.status AND OLD.status != 'consumed' AND NEW.approver IS OLD.approver AND NEW.granted_at IS OLD.granted_at
                    AND NEW.consumed_at IS OLD.consumed_at AND NEW.consumed_by IS OLD.consumed_by)
                OR (OLD.status = 'pending' AND NEW.status = 'granted' AND NEW.approver IS NOT NULL AND NEW.granted_at IS NOT NULL
                    AND NEW.consumed_at IS NULL AND NEW.consumed_by IS NULL)
                OR (OLD.status = 'granted' AND NEW.status = 'consumed' AND NEW.consumed_at IS NOT NULL AND NEW.consumed_by IS NOT NULL
                    AND NEW.approver IS OLD.approver AND NEW.granted_at IS OLD.granted_at)
                OR (OLD.status IN ('pending','granted') AND NEW.status = 'expired' AND NEW.approver IS OLD.approver
                    AND NEW.granted_at IS OLD.granted_at AND NEW.consumed_at IS NULL AND NEW.consumed_by IS NULL)
                OR (OLD.status IN ('pending','granted','expired','invalidated') AND NEW.status = 'invalidated' AND NEW.approver IS OLD.approver
                    AND NEW.granted_at IS OLD.granted_at AND NEW.consumed_at IS NULL AND NEW.consumed_by IS NULL)))
        BEGIN SELECT RAISE(ABORT, 'payment.resume_releases approvals move only pending -> granted -> consumed (or expire or are invalidated) and their manifest never changes'); END""",
    """CREATE TRIGGER payments_resume_approval_no_delete BEFORE DELETE ON approvals
        WHEN OLD.operation = 'payment.resume_releases'
        BEGIN SELECT RAISE(ABORT, 'payment.resume_releases approvals are never deleted'); END""",
]
register_schema_version(CONTROLS_BINDING_SCHEMA_NAME, CONTROLS_BINDING_SCHEMA_STATEMENTS)

DEFAULT_PAYABLE_ACCOUNT = "2000"
IN_PROGRESS_STATES = ("approved", "queued", "submitted", "outcome_unknown")
CLEARING_ACCOUNT = "1200"
FEE_ACCOUNT = "6000"

RESUME_OPERATION = "payment.resume_releases"
CONTROLS_SUBJECT_TYPE = "payment_controls"
CONTROLS_SUBJECT_ID = "payments"

# Recording a provider transfer this copy never recorded (restore recovery).
ADOPT_OPERATION = "payment.adopt_transfer"
TRANSFER_SUBJECT_TYPE = "provider_transfer"
CORE_SOURCE_LABELS = {"bill": "bill payment", "retainage_release": "retainage release payment"}

SIGNATURE_FIELD = "signature"
EVENT_KINDS = ("settled", "returned")

# An intent's ``note`` starts with its purpose label ("bill payment", "retainage
# release payment", ...); status reasons are appended after this separator so
# the label survives every status change (AP reconciliation matches on it).
_REASON_SEP = " | "


def _label(note: str | None) -> str:
    return (note or "").split(_REASON_SEP, 1)[0]


class PaymentError(RuntimeError):
    pass


class ReleaseQuarantined(PaymentError):
    """Release is blocked: no write authority on this copy, or the restore quarantine is active."""


class KillSwitchEngaged(PaymentError):
    """Release is blocked by the payment kill switch."""


class ProviderEventRejected(PaymentError):
    """A provider callback was unsigned, forged or malformed."""


def _non_empty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PaymentError(f"{label} is required and must be a non-empty string")
    return value.strip()


# --------------------------------------------------------------------------- #
# Callback signatures                                                          #
# --------------------------------------------------------------------------- #

def event_signature(event: dict[str, Any], secret: str) -> str:
    """HMAC-SHA256 over the canonical JSON of ``event`` without its signature field."""
    body = {k: v for k, v in event.items() if k != SIGNATURE_FIELD}
    return hmac.new(secret.encode("utf-8"), canonical_json(body).encode("utf-8"), hashlib.sha256).hexdigest()


def sign_event(event: dict[str, Any], secret: str) -> dict[str, Any]:
    out = {k: v for k, v in event.items() if k != SIGNATURE_FIELD}
    out[SIGNATURE_FIELD] = event_signature(out, secret)
    return out


def verify_event(event: dict[str, Any], secret: str | None) -> bool:
    sig = event.get(SIGNATURE_FIELD)
    if not secret or not isinstance(sig, str):
        return False
    try:
        expected = event_signature(event, secret)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(sig, expected)


# --------------------------------------------------------------------------- #
# Simulated provider                                                           #
# --------------------------------------------------------------------------- #

# Providers by webhook secret, so the payment domain can find the provider whose
# secret the service hands it (for fee quotes) without the service passing the
# provider object itself.  Weak: a provider disappears with its last user.
_PROVIDERS: "weakref.WeakValueDictionary[str, SimulatedProvider]" = weakref.WeakValueDictionary()


class SimulatedProvider:
    """An in-memory payment rail.  ``mode`` controls the next submission:

    ``accept``                normal acceptance
    ``timeout_after_accept``  the transfer is recorded but the response is lost
    ``reject``                the provider refuses the payment
    ``unavailable``           the provider cannot be reached at all
    ``mfa_failed``            the provider's MFA challenge for the release fails; nothing is transferred

    ``fee`` is the flat per-transfer fee quoted by ``fee_for`` (default ``0.00``,
    configurable); each transfer records the fee charged when it was made.
    ``webhook_secret`` (random per instance) signs every event the simulator emits.
    A submission may carry the approved ``value_date``, the ``currency`` and a
    ``reference`` (Cipher's workspace, intent and paid record), which the transfer
    keeps; ``list_transfers`` returns every transfer the way a provider's list
    endpoint would, and a transfer remembers whether it settled before a return.
    """

    MODES = ("accept", "timeout_after_accept", "reject", "unavailable", "mfa_failed")

    def __init__(self, *, fee: Any = "0.00", webhook_secret: str | None = None):
        self.mode = "accept"
        self.transfers: dict[str, dict[str, Any]] = {}
        self.submissions: list[dict[str, Any]] = []
        self.fee = fmt(money(fee))
        if money(self.fee) < 0:
            raise PaymentError("provider fee cannot be negative")
        self.webhook_secret = webhook_secret or secrets.token_hex(32)
        _PROVIDERS[self.webhook_secret] = self

    def fee_for(self, amount: Any) -> str:
        """The fee this provider charges for a transfer of ``amount``."""
        money(amount)  # exact money only
        fee = money(self.fee)
        if fee < 0:
            raise PaymentError("provider fee cannot be negative")
        return fmt(fee)

    def sign(self, event: dict[str, Any]) -> dict[str, Any]:
        return sign_event(event, self.webhook_secret)

    def submit(self, *, logical_op_id: str, amount: str, destination: str, payload_hash: str,
               value_date: str | None = None, currency: str | None = None, reference: dict[str, Any] | None = None) -> dict[str, Any]:
        self.submissions.append({"logical_op_id": logical_op_id, "amount": amount, "destination": destination, "mode": self.mode,
                                 "value_date": value_date, "currency": currency, "reference": dict(reference) if reference else None})
        if self.mode == "unavailable":
            raise ConnectionError("provider unavailable")
        if self.mode == "reject":
            return {"outcome": "rejected", "reason": "provider rejected the payment"}
        if self.mode == "mfa_failed":
            return {"outcome": "rejected", "reason": "MFA challenge failed"}
        existing = self.transfers.get(logical_op_id)
        if existing is None:
            existing = {
                "provider_ref": f"sim_{len(self.transfers) + 1:06d}", "logical_op_id": logical_op_id, "amount": amount, "destination": destination,
                "payload_hash": payload_hash, "status": "accepted", "settled": False, "fee": self.fee_for(amount),
                "value_date": value_date, "currency": currency, "reference": dict(reference) if reference else None,
            }
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
        return {"found": True, "provider_ref": t["provider_ref"], "status": t["status"], "amount": t["amount"], "settled": bool(t.get("settled"))}

    def list_transfers(self) -> list[dict[str, Any]]:
        """Every transfer this provider holds, oldest first (a provider's list endpoint)."""
        if self.mode == "unavailable":
            raise ConnectionError("provider unavailable")
        out = []
        for op_id, t in self.transfers.items():
            row = {k: (dict(v) if isinstance(v, dict) else v) for k, v in t.items()}
            row.setdefault("logical_op_id", op_id)
            row["settled"] = bool(row.get("settled"))
            out.append(row)
        return sorted(out, key=lambda r: r["provider_ref"])

    def _event(self, t: dict[str, Any], kind: str, **extra: Any) -> dict[str, Any]:
        return self.sign({"id": f"evt_{t['provider_ref']}_{kind}", "kind": kind, "provider_ref": t["provider_ref"], "amount": t["amount"], **extra})

    def settle(self, logical_op_id: str) -> dict[str, Any]:
        t = self.transfers[logical_op_id]
        t["status"] = "settled"
        t["settled"] = True
        return self._event(t, "settled")

    def return_payment(self, logical_op_id: str, reason: str = "account closed") -> dict[str, Any]:
        t = self.transfers[logical_op_id]
        t["status"] = "returned"
        return self._event(t, "returned", reason=reason, settled_before_return=bool(t.get("settled")))


# --------------------------------------------------------------------------- #
# Payments                                                                     #
# --------------------------------------------------------------------------- #

class Payments:
    def __init__(self, db: Database, audit: Audit, commands: Commands, ledger: Ledger):
        self.db = db
        self.audit = audit
        self.commands = commands
        self.ledger = ledger
        self.provider: Any = None
        self._webhook_secret: str | None = None
        self._listeners: dict[str, list[Callable[..., None]]] = {}
        self._adopters: dict[str, dict[str, Any]] = {}
        self._savepoint_seq = 0

    # ---- provider binding -------------------------------------------------------- #

    @property
    def webhook_secret(self) -> str | None:
        """The secret provider callbacks must be signed with.  Without one every
        callback is rejected (fail closed)."""
        return self._webhook_secret

    @webhook_secret.setter
    def webhook_secret(self, value: str | None) -> None:
        """Setting the secret also re-binds the provider whose fees manifests quote: the
        provider registered under that secret, so a replaced provider never leaves fee
        quotes on its predecessor.  A secret no registered provider holds unbinds a
        provider whose own secret differs (fees then quote 0.00 and dispatch, which asks
        the dispatching provider, fails any intent whose approved fee is wrong).  Clearing
        the secret (``None``) keeps the binding; callbacks are then refused (fail closed)."""
        self._webhook_secret = value
        if not value:
            return
        registered = _PROVIDERS.get(value)
        if registered is not None:
            self.provider = registered
        elif self.provider is not None and getattr(self.provider, "webhook_secret", None) != value:
            self.provider = None

    def attach_provider(self, provider: Any) -> None:
        """Bind the provider whose fees manifests quote and whose secret signs callbacks."""
        self.provider = provider
        self._webhook_secret = getattr(provider, "webhook_secret", None)

    def fee_for(self, amount: Any, provider: Any = None) -> str:
        provider = provider if provider is not None else self.provider
        quote = getattr(provider, "fee_for", None)
        if quote is None:
            return "0.00"
        fee = money(quote(amount))
        if fee < 0:
            raise PaymentError("provider quoted a negative fee")
        return fmt(fee)

    def payment_terms(self, amount: Any, project_id: str) -> dict[str, Any]:
        """The transfer terms an approval binds: the project's entity and currency,
        the value date (UTC today) and the provider's fee for ``amount``."""
        project = self.db.one("SELECT entity, currency FROM projects WHERE id=?", (project_id,))
        if project is None:
            raise PaymentError(f"unknown project {project_id}")
        return {
            "entity": project["entity"],
            "currency": project["currency"] or "USD",
            "value_date": utcnow().date().isoformat(),
            "fee": self.fee_for(amount),
        }

    # ---- source listeners ------------------------------------------------------ #

    def subscribe(self, source_type: str, handler: Callable[..., None]) -> None:
        """Call ``handler(intent, actor=...)`` whenever an intent whose
        ``source_type`` matches changes status (accepted, settled, returned,
        failed, canceled, outcome unknown).  The handler runs inside the transaction
        that changes the intent, under its own savepoint; if it raises, only its own
        writes roll back, the failure is audited and the intent change commits."""
        handlers = self._listeners.setdefault(source_type, [])
        if handler not in handlers:
            handlers.append(handler)

    def register_adoption(self, source_type: str, *, plan: Callable[..., dict[str, Any]], link: Callable[..., None], label: str) -> None:
        """Let ``payment.adopt_transfer`` record a provider transfer that pays one of this
        module's records (restore recovery).  ``plan(source_id, *, amount, party_id,
        superseded, transfer_status)`` validates the local record and returns
        ``{"project_id", "party_id", "payable_account", "binding"}`` (``binding``: the
        record facts the approval must bind) or raises; ``superseded`` lists local queued
        intents for the record that the adoption cancels first.  ``link(intent, *,
        approval_id, actor)`` runs inside the adoption transaction once the intent row
        exists, before the provider's acceptance is booked.  ``label`` is the intent's
        purpose label (the same one the module's own releases use)."""
        if not isinstance(label, str) or not label.strip():
            raise PaymentError("an adoption path needs the purpose label its releases use")
        self._adopters[source_type] = {"plan": plan, "link": link, "label": label.strip()}

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
        terms = self.payment_terms(b["amount_due"], b["project_id"])
        return build_manifest(
            operation="payment.release",
            subject_type="bill",
            subject_id=bill_id,
            actor_role=actor_role,
            amounts={"amount": b["amount_due"]},
            bindings={
                "bill_hash": b["content_hash"], "bill_status": b["status"], "project_id": b["project_id"], "payable_account": DEFAULT_PAYABLE_ACCOUNT,
                "destination_verified": bool(supplier["destination_verified"]), "funding_source": "operating-bank-simulated",
                "fees": terms["fee"], "value_date": terms["value_date"],
            },
            destination={"party_id": supplier["id"], "destination": supplier["destination"], "destination_version": supplier["destination_version"]},
            entity=terms["entity"],
            currency=terms["currency"],
        )

    def _retainage_paid(self, *, supplier_id: str, project_id: str) -> list[dict[str, Any]]:
        """Released-retainage intents still counting against the release: scoped ones on this
        supplier and project, plus legacy (unscoped) ones matched by their purpose label."""
        return self.db.query(
            """SELECT amount FROM payment_intents
               WHERE bill_id IS NULL AND party_id=? AND status IN ('queued','submitted','outcome_unknown','accepted','settled')
                 AND ((source_type='retainage_release' AND project_id=?) OR (payable_account IS NULL AND note LIKE 'retainage%'))""",
            (supplier_id, project_id),
        )

    def manifest_for_retainage(self, commitment_id: str, *, actor_role: str) -> dict[str, Any]:
        c = self.db.one("SELECT * FROM commitments WHERE id=?", (commitment_id,))
        if c is None:
            raise PaymentError(f"unknown commitment {commitment_id}")
        supplier = self.db.one("SELECT * FROM parties WHERE id=?", (c["supplier_id"],))
        payable = self.ledger.account_activity("2050", party_id=c["supplier_id"], project_id=c["project_id"])["debit"]
        paid = self._retainage_paid(supplier_id=c["supplier_id"], project_id=c["project_id"])
        outstanding = money(payable - sum(money(p["amount"]) for p in paid))
        if outstanding <= 0:
            raise PaymentError("no released retainage is payable")
        terms = self.payment_terms(outstanding, c["project_id"])
        return build_manifest(
            operation="payment.release",
            subject_type="commitment",
            subject_id=commitment_id,
            actor_role=actor_role,
            amounts={"amount": outstanding},
            bindings={
                "kind": "retainage", "project_id": c["project_id"], "payable_account": DEFAULT_PAYABLE_ACCOUNT,
                "destination_verified": bool(supplier["destination_verified"]), "funding_source": "operating-bank-simulated",
                "fees": terms["fee"], "value_date": terms["value_date"],
            },
            destination={"party_id": supplier["id"], "destination": supplier["destination"], "destination_version": supplier["destination_version"]},
            entity=terms["entity"],
            currency=terms["currency"],
        )

    # ---- release controls --------------------------------------------------------- #

    def controls(self) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM payments_controls WHERE id=1")
        if row is None:
            raise PaymentError("payment controls are missing; run the schema migration")
        row["kill_switch"] = bool(row["kill_switch"])
        return row

    def controls_history(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM payments_controls_history ORDER BY version")
        for r in rows:
            r["kill_switch"] = bool(r["kill_switch"])
        return rows

    def _release_block(self) -> tuple[type[PaymentError], str] | None:
        status = self.db.authority_status()
        if not status["effective_write_authority"]:
            return ReleaseQuarantined, ("this workspace copy holds no write authority; payment release is blocked until write authority "
                                        "is claimed and recovery reconciliation completes")
        if status["release_quarantined"]:
            return ReleaseQuarantined, "payment release is quarantined after a restore until recovery reconciliation completes"
        ctl = self.controls()
        if ctl["kill_switch"]:
            return KillSwitchEngaged, f"payment releases are stopped by the kill switch (controls version {ctl['version']}): {ctl['reason']}"
        return None

    def release_allowed(self) -> tuple[bool, str]:
        block = self._release_block()
        return (False, block[1]) if block else (True, "ok")

    def _require_release_allowed(self) -> None:
        block = self._release_block()
        if block is not None:
            raise block[0](block[1])

    def engage_kill_switch(self, reason: str, actor: str) -> dict[str, Any]:
        """Stop every payment release at once.  Protective, so no approval is needed;
        engaging again records the new reason under a new version (which makes any
        resume approval granted for the earlier version stale)."""
        reason = _non_empty(reason, "reason")
        actor = _non_empty(actor, "actor")
        with self.db.transaction() as conn:
            current = self.controls()
            version = current["version"] + 1
            now = utcnow_iso()
            conn.execute(
                "INSERT INTO payments_controls_history (version, kill_switch, reason, changed_by, changed_at) VALUES (?,1,?,?,?)",
                (version, reason, actor, now),
            )
            conn.execute("UPDATE payments_controls SET kill_switch=1, version=?, reason=?, changed_by=?, changed_at=? WHERE id=1", (version, reason, actor, now))
            queued = self.db.scalar("SELECT COUNT(*) FROM payment_intents WHERE status='queued'") or 0
            self.audit.record(actor, "payment.kill_switch_engaged", CONTROLS_SUBJECT_TYPE, CONTROLS_SUBJECT_ID,
                              {"version": version, "reason": reason, "was_engaged": current["kill_switch"], "queued_intents_held": queued})
        return self.controls()

    # Payments is a core domain that owns ``payment.resume_releases`` and ``payment.adopt_transfer``.

    def handles(self, operation: str) -> bool:
        return operation in (RESUME_OPERATION, ADOPT_OPERATION)

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation == ADOPT_OPERATION:
            return self._adoption_manifest(subject_id, actor_role=actor_role)
        if operation != RESUME_OPERATION:
            raise PaymentError(f"unknown payment operation {operation}")
        if subject_id != CONTROLS_SUBJECT_ID:
            raise PaymentError(f"{RESUME_OPERATION} applies to subject {CONTROLS_SUBJECT_ID!r}, not {subject_id!r}")
        ctl = self.controls()
        if not ctl["kill_switch"]:
            raise PaymentError("the payment kill switch is not engaged; there is nothing to resume")
        return build_manifest(
            operation=RESUME_OPERATION,
            subject_type=CONTROLS_SUBJECT_TYPE,
            subject_id=CONTROLS_SUBJECT_ID,
            actor_role=actor_role,
            bindings={
                "controls_version": ctl["version"], "kill_switch": True, "reason": ctl["reason"],
                "engaged_by": ctl["changed_by"], "engaged_at": ctl["changed_at"],
            },
        )

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation == ADOPT_OPERATION:
            return self._apply_adoption(subject_id, approval_id=approval_id, manifest=manifest, actor=actor)
        if operation != RESUME_OPERATION:
            raise PaymentError(f"unknown payment operation {operation}")
        with self.db.transaction() as conn:
            ctl = self.controls()
            bound = manifest.get("bindings") or {}
            if not ctl["kill_switch"]:
                raise PaymentError("the payment kill switch is not engaged; there is nothing to resume")
            if ctl["version"] != bound.get("controls_version") or ctl["reason"] != bound.get("reason"):
                raise PaymentError(f"payment controls changed after approval (now version {ctl['version']})")
            version = ctl["version"] + 1
            reason = f"releases resumed under approval {approval_id} (kill switch version {ctl['version']}: {ctl['reason']})"
            now = utcnow_iso()
            conn.execute(
                "INSERT INTO payments_controls_history (version, kill_switch, reason, changed_by, changed_at, approval_id) VALUES (?,0,?,?,?,?)",
                (version, reason, actor, now, approval_id),
            )
            conn.execute("UPDATE payments_controls SET kill_switch=0, version=?, reason=?, changed_by=?, changed_at=? WHERE id=1", (version, reason, actor, now))
            self.audit.record(actor, "payment.releases_resumed", CONTROLS_SUBJECT_TYPE, CONTROLS_SUBJECT_ID,
                              {"approval_id": approval_id, "version": version, "resumed_from_version": ctl["version"], "engaged_reason": ctl["reason"]})
        return {"kill_switch": False, "controls_version": version, "resumed_from_version": ctl["version"], "approval_id": approval_id}

    # ---- intents ------------------------------------------------------------- #

    def create_intent(self, *, manifest: dict[str, Any], approval_id: str, bill_id: str | None, note: str, actor: str,
                      project_id: str | None = None, source_type: str | None = None, source_id: str | None = None,
                      payable_account: str = DEFAULT_PAYABLE_ACCOUNT) -> dict[str, Any]:
        """Create the intent and its outbox row atomically.  ``approval_id`` must
        already be consumed by the caller against ``manifest``.

        ``project_id`` defaults to the paid bill's (or released retainage's)
        project and is required otherwise; ``source_type``/``source_id`` default
        to the bill or the commitment; ``payable_account`` is the liability the
        payment draws down when the provider accepts it.  A project or payable
        account the manifest binds must match, and so must a bound entity and
        currency.  The bound fee and value date are stored on the intent.  Only one
        intent per source may be in progress at a time."""
        self._require_release_allowed()
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
        try:
            amount = money(manifest["amounts"]["amount"])
        except (KeyError, TypeError, MoneyError) as exc:
            raise PaymentError(f"the approval manifest carries no exact payment amount: {exc}") from exc
        if amount <= 0:
            raise PaymentError("payment amount must be positive")
        bindings = manifest.get("bindings") or {}
        try:
            fee = money(bindings.get("fees", "0.00"))
        except MoneyError as exc:
            raise PaymentError(f"the approval manifest carries an invalid fee: {exc}") from exc
        if fee < 0:
            raise PaymentError("a payment fee cannot be negative")
        scope = self._resolve_scope(manifest, bill_id=bill_id, project_id=project_id, source_type=source_type, source_id=source_id, payable_account=payable_account)
        project = self.db.one("SELECT entity, currency FROM projects WHERE id=?", (scope["project_id"],))
        if manifest.get("entity") is not None and manifest["entity"] != project["entity"]:
            raise PaymentError(f"the approval manifest binds entity {manifest['entity']!r}, but project {scope['project_id']} belongs to {project['entity']!r}")
        currency = manifest.get("currency") or "USD"
        if currency != (project["currency"] or "USD"):
            raise PaymentError(f"the approval manifest binds currency {currency}, but project {scope['project_id']} is in {project['currency']}")
        value_date = bindings.get("value_date")
        if value_date is not None and not isinstance(value_date, str):
            raise PaymentError("the approval manifest carries an invalid value date")
        logical_op_id = f"pay:{approval_id}"
        # the provider's idempotency key covers every approved term, so a replay with another
        # value date, currency or entity is refused by the provider rather than executed
        payload = {"party_id": party["id"], "destination": party["destination"], "destination_version": party["destination_version"], "amount": fmt(amount), "bill_id": bill_id, "fee": fmt(fee),
                   "value_date": value_date, "currency": project["currency"] or "USD", "entity": project["entity"]}
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
                                                project_id, source_type, source_id, payable_account, fee, value_date, entity, currency)
                   VALUES (?,?,?,?,?,?,'approved',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (intent_id, bill_id, party["id"], fmt(amount), party["destination"], party["destination_version"], approval_id, logical_op_id, payload_hash, ws["recovery_epoch"], utcnow_iso(), _label(note),
                 scope["project_id"], scope["source_type"], scope["source_id"], scope["payable_account"], fmt(fee), value_date, project["entity"], project["currency"] or "USD"),
            )
            ob = self.commands.enqueue("payment", {"intent_id": intent_id, "logical_op_id": logical_op_id, "payload_hash": payload_hash})
            conn.execute("UPDATE payment_intents SET status='queued', outbox_id=? WHERE id=?", (ob["id"], intent_id))
            self.audit.record(actor, "payment.queued", "payment_intent", intent_id, {
                "amount": fmt(amount), "fee": fmt(fee), "value_date": value_date, "party_id": party["id"], "approval_id": approval_id, "outbox_id": ob["id"], **scope,
            })
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

    def _queue_untrusted(self) -> str | None:
        """Why this copy's local payment queue cannot be acted on, or None.  Without
        effective write authority nothing may change; while the restore quarantine is
        active a queued intent may already have been paid from the live workspace (the
        backup predates its dispatch), so only recovery reconciliation -- which looks
        every queued intent up at the provider -- may decide its fate."""
        status = self.db.authority_status()
        if not status["effective_write_authority"]:
            return "this workspace copy holds no write authority; its queued payment intents cannot be changed here"
        if status["release_quarantined"]:
            return ("the restore quarantine is active: a restored copy's payment queue is not trusted until recovery reconciliation "
                    "has looked every queued intent up at the provider (the live workspace may already have paid it); run complete_recovery first")
        return None

    def _provider_has_no_transfer(self, intent: dict[str, Any]) -> str:
        """Ask the bound provider whether it already holds a transfer for ``intent``.
        Refuses when it does or when it cannot be asked; returns what was checked."""
        lookup = getattr(self.provider, "lookup", None)
        if lookup is None:
            return "no provider bound; the local queue is authoritative on this copy"
        try:
            found = lookup(intent["logical_op_id"])
        except ConnectionError as exc:
            raise PaymentError(f"cannot confirm with the provider that payment intent {intent['id']} was never transferred ({exc}); "
                               "try again when it is reachable, or engage the kill switch to hold every release") from exc
        if found.get("found"):
            raise PaymentError(f"the provider already holds transfer {found.get('provider_ref')} for payment intent {intent['id']}; "
                               "it cannot be canceled -- reconcile it instead")
        return "provider has no transfer for it"

    def cancel_intent(self, intent_id: str, reason: str, actor: str) -> dict[str, Any]:
        """Withdraw a queued intent before it is dispatched.  The intent becomes
        ``canceled`` and its outbox row ``failed``; the obligation stays open (a
        bill stays posted, a reimbursement payment goes back to draft and the claim
        is payable again).  A dispatched intent is never "canceled" here:
        once the provider may have acted, only reconciliation decides.

        Refused (``ReleaseQuarantined``) on a copy without write authority and while
        the restore quarantine is active, and refused when the bound provider already
        holds a transfer for the intent or cannot be asked.  The kill switch does not
        block it: withdrawing a release is protective too."""
        reason = _non_empty(reason, "reason")
        actor = _non_empty(actor, "actor")
        untrusted = self._queue_untrusted()
        if untrusted is not None:
            raise ReleaseQuarantined(f"payment intent {intent_id} cannot be canceled: {untrusted}")
        intent = self.db.one("SELECT * FROM payment_intents WHERE id=?", (intent_id,))
        if intent is None:
            raise PaymentError(f"unknown payment intent {intent_id}")
        if intent["status"] != "queued":
            raise PaymentError(f"payment intent {intent_id} is {intent['status']}; only queued (undispatched) intents can be canceled")
        provider_check = self._provider_has_no_transfer(intent)  # outside the write lock: the provider is remote
        with self.db.transaction() as conn:
            # everything decided above is re-read under the write lock
            untrusted = self._queue_untrusted()
            if untrusted is not None:
                raise ReleaseQuarantined(f"payment intent {intent_id} cannot be canceled: {untrusted}")
            intent = self.db.one("SELECT * FROM payment_intents WHERE id=?", (intent_id,))
            failures = self._cancel_queued(intent, reason=reason, actor=actor, provider_check=provider_check)
        out = self.get(intent_id)
        if failures:
            out["listener_errors"] = failures
        return out

    def _cancel_queued(self, intent: dict[str, Any], *, reason: str, actor: str, provider_check: str,
                       extra: dict[str, Any] | None = None) -> list[dict[str, str]]:
        """Cancel a queued intent; the caller holds the write lock and has asked the provider."""
        intent_id = intent["id"]
        with self.db.transaction() as conn:
            if intent["status"] != "queued":
                raise PaymentError(f"payment intent {intent_id} is {intent['status']}; only queued (undispatched) intents can be canceled")
            ob = self.db.one("SELECT id, status FROM outbox WHERE id=?", (intent["outbox_id"],)) if intent["outbox_id"] else None
            if ob is not None and ob["status"] != "pending":
                raise PaymentError(f"payment intent {intent_id}'s outbox row is {ob['status']}; it can no longer be canceled")
            if ob is not None:
                self.commands.mark_failed(ob["id"], f"canceled: {reason}")
            bill_reopened = False
            if intent["bill_id"]:
                # a queued intent never marked its bill paid; reopen it only if no booked payment does
                booked = self.db.one("SELECT id FROM payment_intents WHERE bill_id=? AND id != ? AND status IN ('accepted','settled')", (intent["bill_id"], intent_id))
                if booked is None:
                    bill_reopened = conn.execute("UPDATE bills SET status='posted' WHERE id=? AND status='paid'", (intent["bill_id"],)).rowcount > 0
            return self._set_status(intent_id, "canceled", actor=actor, note=f"canceled: {reason}", resolved=True,
                                    extra={"reason": reason, "outbox_id": intent["outbox_id"], "bill_id": intent["bill_id"], "bill_reopened": bill_reopened,
                                           "source_type": intent["source_type"], "source_id": intent["source_id"], "amount": intent["amount"],
                                           "provider_check": provider_check, **(extra or {})})

    # ---- dispatch -------------------------------------------------------------- #

    def _payee_problem(self, intent: dict[str, Any]) -> str | None:
        party = self.db.one("SELECT destination, destination_version, destination_verified FROM parties WHERE id=?", (intent["party_id"],))
        if party is None:
            return "payee no longer exists"
        if party["destination"] != intent["destination"] or party["destination_version"] != intent["destination_version"]:
            return "destination changed after approval"
        if not party["destination_verified"]:
            return "payee destination is no longer verified"
        return None

    def _fee_problem(self, intent: dict[str, Any], provider: Any) -> str | None:
        if getattr(provider, "fee_for", None) is None:
            return None
        quoted = self.fee_for(intent["amount"], provider)
        approved = fmt(money(intent.get("fee") or "0.00"))
        if quoted != approved:
            return f"provider fee changed after approval (approved {approved}, provider now quotes {quoted})"
        return None

    def _terms_problem(self, intent: dict[str, Any]) -> str | None:
        """The approved value date must not have passed, and the project's entity and
        currency must still be the approved ones (intents created before the terms
        were recorded carry none and are not checked)."""
        value_date = intent.get("value_date")
        if value_date:
            today = utcnow().date().isoformat()
            if value_date < today:
                return f"approved value date {value_date} has passed (today is {today}); the release must be approved again"
        if intent.get("entity") is not None or intent.get("currency"):
            project = self.db.one("SELECT entity, currency FROM projects WHERE id=?", (intent.get("project_id"),)) if intent.get("project_id") else None
            if project is not None:
                if intent.get("entity") is not None and project["entity"] != intent["entity"]:
                    return f"project entity changed after approval (approved {intent['entity']!r}, now {project['entity']!r})"
                if intent.get("currency") and (project["currency"] or "USD") != intent["currency"]:
                    return f"project currency changed after approval (approved {intent['currency']}, now {project['currency']})"
        return None

    def _reference(self, intent: dict[str, Any]) -> dict[str, Any]:
        """What the provider keeps with the transfer so a restored copy can attribute it."""
        return {
            "workspace_id": self.db.workspace()["workspace_id"], "intent_id": intent["id"], "source_type": intent.get("source_type"),
            "source_id": intent.get("source_id"), "project_id": intent.get("project_id"), "party_id": intent["party_id"], "bill_id": intent.get("bill_id"),
        }

    @staticmethod
    def _accepted_keywords(fn: Any) -> set[str] | None:
        """The keyword arguments ``fn`` accepts (None: any)."""
        try:
            params = inspect.signature(fn).parameters.values()
        except (TypeError, ValueError):
            return set()
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params):
            return None
        return {p.name for p in params}

    def _submit(self, provider: Any, intent: dict[str, Any]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"logical_op_id": intent["logical_op_id"], "amount": intent["amount"], "destination": intent["destination"], "payload_hash": intent["payload_hash"]}
        accepted = self._accepted_keywords(provider.submit)
        for key, value in (("value_date", intent.get("value_date")), ("currency", intent.get("currency")), ("reference", self._reference(intent))):
            if accepted is None or key in accepted:
                kwargs[key] = value
        return provider.submit(**kwargs)

    def _fail_queued(self, intent_id: str, outbox_id: str, *, reason: str, actor: str) -> list[dict[str, str]] | None:
        """Fail a queued intent without submitting it; None when it is no longer queued."""
        with self.db.transaction() as conn:
            row = conn.execute("SELECT status FROM payment_intents WHERE id=?", (intent_id,)).fetchone()
            if row is None or row["status"] != "queued":
                return None
            self.commands.mark_failed(outbox_id, reason)
            return self._set_status(intent_id, "failed", actor=actor, note=f"{reason}; not submitted", resolved=True, extra={"outbox_id": outbox_id})

    def dispatch_pending(self, provider: SimulatedProvider, *, actor: str) -> list[dict[str, Any]]:
        self._require_release_allowed()
        results = []
        for ob in self.commands.pending("payment"):
            intent_id = ob["payload"]["intent_id"]
            intent = self.get(intent_id)
            if intent["status"] != "queued":
                self.commands.mark_failed(ob["id"], f"intent is {intent['status']}")
                continue
            # Claim the row first so a second worker can never dispatch the same intent.  Everything
            # the submission depends on -- the release controls, the intent's status, the payee's
            # destination and destination version, the provider's fee, the approved value date and
            # the project's entity and currency -- is re-read under the
            # write lock in the claiming transaction, so a kill switch engaged or a destination
            # re-verified mid-run (another thread on the shared connection) cannot slip between the
            # check and the claim: the intent goes to exactly the destination that was verified.
            problem: str | None = None
            failures: list[dict[str, str]] | None = None
            with self.db.transaction() as conn:
                block = self._release_block()
                if block is not None:
                    held = self.db.scalar("SELECT COUNT(*) FROM payment_intents WHERE status='queued'") or 0
                    self.audit.record(actor, "payment.dispatch_halted", CONTROLS_SUBJECT_TYPE, CONTROLS_SUBJECT_ID, {"reason": block[1], "queued_intents_held": held})
                    break
                intent = self.get(intent_id)
                if intent["status"] != "queued":
                    continue
                problem = self._payee_problem(intent) or self._fee_problem(intent, provider) or self._terms_problem(intent)
                if problem is not None:
                    failures = self._fail_queued(intent["id"], ob["id"], reason=problem, actor=actor)
                else:
                    claimed = conn.execute("UPDATE payment_intents SET status='submitted', submitted_at=? WHERE id=? AND status='queued'", (utcnow_iso(), intent["id"])).rowcount
                    if not claimed:
                        continue
                    self.commands.mark_dispatched(ob["id"])
            if problem is not None:
                if failures is not None:
                    results.append(self._result(intent["id"], "failed", failures, reason=problem))
                continue
            try:
                resp = self._submit(provider, intent)
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
                reason = resp.get("reason", "rejected")
                failures = self._set_status(intent["id"], "failed", actor=actor, note=reason, resolved=True)
                results.append(self._result(intent["id"], "failed", failures, reason=reason))
        return results

    def _set_status(self, intent_id: str, status: str, *, actor: str, note: str = "", provider_ref: str | None = None, resolved: bool = False,
                    extra: dict[str, Any] | None = None) -> list[dict[str, str]]:
        with self.db.transaction() as conn:
            current = conn.execute("SELECT note FROM payment_intents WHERE id=?", (intent_id,)).fetchone()
            label = _label(current["note"] if current else "")
            full_note = f"{label}{_REASON_SEP}{note}" if label and note else (note or label)
            conn.execute(
                "UPDATE payment_intents SET status=?, note=?, provider_ref=COALESCE(?, provider_ref), resolved_at=CASE WHEN ? THEN ? ELSE resolved_at END WHERE id=?",
                (status, full_note, provider_ref, 1 if resolved else 0, utcnow_iso(), intent_id),
            )
            self.audit.record(actor, f"payment.{status}", "payment_intent", intent_id, {"note": note, "provider_ref": provider_ref, **(extra or {})})
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
                    {"account": CLEARING_ACCOUNT, "credit": intent["amount"], "project_id": project_id, "party_id": intent["party_id"], "memo": "provider clearing"},
                ],
                source_type="payment_intent", source_id=intent_id, source_version="1", posted_by=actor, approval_id=intent["approval_id"],
            )
            conn.execute("UPDATE payment_intents SET status='accepted', provider_ref=?, journal_id=?, note=? WHERE id=?", (provider_ref, j["id"], _label(intent["note"]), intent_id))
            if intent["bill_id"]:
                conn.execute("UPDATE bills SET status='paid' WHERE id=? AND status='posted'", (intent["bill_id"],))
            self.audit.record(actor, "payment.accepted", "payment_intent", intent_id, {"provider_ref": provider_ref, "journal_id": j["id"], "project_id": project_id, "payable_account": payable})
            return self._notify(intent_id, actor=actor)

    # ---- reconciliation ------------------------------------------------------- #

    def _resolve_in_doubt(self, provider: SimulatedProvider, *, actor: str) -> list[dict[str, Any]]:
        """Resolve every submitted/outcome-unknown intent by durable identifier.
        Nothing is ever resubmitted from here."""
        results = []
        for row in self.db.query("SELECT id FROM payment_intents WHERE status IN ('submitted','outcome_unknown') ORDER BY created_at"):
            intent = self.get(row["id"])
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

    @staticmethod
    def _missed_kind(intent_status: str, found: dict[str, Any]) -> str | None:
        """The provider event Cipher has not recorded for an intent, or None."""
        observed = found.get("status")
        if intent_status == "accepted" and observed in EVENT_KINDS:
            return observed
        if intent_status == "settled" and observed == "returned":
            return "returned"
        return None

    def _catch_up_intent(self, intent: dict[str, Any], found: dict[str, Any], *, actor: str) -> dict[str, Any] | None:
        """Ingest the reconciliation event for one intent's missed callback (the caller has
        checked that a webhook secret is configured); None when nothing was missed."""
        kind = self._missed_kind(intent["status"], found)
        if kind is None:
            return None
        event = {"id": f"recon_{intent['provider_ref']}_{kind}", "kind": kind, "provider_ref": intent["provider_ref"], "amount": found.get("amount", intent["amount"]),
                 "source": "reconciliation", "observed_status": found.get("status")}
        if kind == "returned":
            event["reason"] = "return found by reconciliation; callback missing"
            event["settled_before_return"] = bool(found.get("settled"))
        outcome = self.ingest_event(sign_event(event, self.webhook_secret), actor=actor)
        after = self.db.one("SELECT status FROM payment_intents WHERE id=?", (intent["id"],))["status"]
        extra: dict[str, Any] = {"provider_ref": intent["provider_ref"], "caught_up_event": event["id"], "applied": outcome["applied"]}
        if outcome.get("derived_settlement"):
            extra["derived_settlement"] = outcome["derived_settlement"]
        return self._result(intent["id"], after, outcome.get("listener_errors", []), **extra)

    def _catch_up_callbacks(self, provider: SimulatedProvider, *, actor: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Missing-callback detection: when the provider reports an accepted intent
        settled or returned (or a settled one returned) and Cipher has not recorded
        it, ingest a signed reconciliation event with a deterministic id, so the
        books catch up exactly once (a late real callback is then ignored as not
        applicable, and the same reconciliation event is a duplicate).

        Returns ``(results, blocked)``: ``blocked`` names what could not be caught up
        now -- a missed event while no webhook secret is configured (reconciliation
        events are signed and verified like provider callbacks, so without a secret
        nothing can be recorded), or a provider that could not be reached."""
        results: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for row in self.db.query("SELECT id FROM payment_intents WHERE status IN ('accepted','settled') AND provider_ref IS NOT NULL ORDER BY created_at"):
            intent = self.db.one("SELECT * FROM payment_intents WHERE id=?", (row["id"],))
            try:
                found = provider.lookup(intent["logical_op_id"])
            except ConnectionError as exc:
                blocked.append({"intent_id": intent["id"], "provider_ref": intent["provider_ref"], "reason": f"provider unreachable: {exc}"})
                break  # nothing more can be learned now; the next reconciliation tries again
            if not found.get("found") or found.get("provider_ref") != intent["provider_ref"]:
                continue
            if self._missed_kind(intent["status"], found) is None:
                continue
            if not self.webhook_secret:
                blocked.append({"intent_id": intent["id"], "provider_ref": intent["provider_ref"], "provider_status": found.get("status"),
                                "reason": "no webhook secret is configured, so the missed provider event cannot be recorded as an authenticated reconciliation event"})
                continue
            outcome = self._catch_up_intent(intent, found, actor=actor)
            if outcome is not None:
                results.append(outcome)
        return results, blocked

    def reconcile(self, provider: SimulatedProvider, *, actor: str) -> list[dict[str, Any]]:
        """Resolve submitted/outcome-unknown intents by durable identifier, then catch
        up callbacks the provider sent but Cipher never received.  Nothing is ever
        resubmitted from here."""
        results = self._resolve_in_doubt(provider, actor=actor)
        caught, _blocked = self._catch_up_callbacks(provider, actor=actor)
        results.extend(caught)
        return results

    def _resolve_queued_after_restore(self, provider: SimulatedProvider, *, actor: str) -> tuple[list[dict[str, Any]], list[str]]:
        """Look every queued intent up at the provider before anything can be
        dispatched: a restored older backup may hold an intent whose transfer the
        live workspace already made.  Found: its outbox row is marked dispatched and
        the intent is recorded as submitted and accepted (one journal), with no
        second submission.  Not found: it stays queued.  Unreachable: unresolved."""
        results: list[dict[str, Any]] = []
        unresolved: list[str] = []
        for row in self.db.query("SELECT id FROM payment_intents WHERE status='queued' ORDER BY created_at"):
            intent = self.get(row["id"])
            try:
                found = provider.lookup(intent["logical_op_id"])
            except ConnectionError as exc:
                unresolved.append(intent["id"])
                results.append(self._result(intent["id"], "queued", [], note=f"provider unreachable: {exc}"))
                continue
            if not found.get("found"):
                continue
            with self.db.transaction() as conn:
                locked = conn.execute("SELECT status, outbox_id FROM payment_intents WHERE id=?", (intent["id"],)).fetchone()
                if locked["status"] != "queued":
                    continue
                if locked["outbox_id"]:
                    ob = conn.execute("SELECT status FROM outbox WHERE id=?", (locked["outbox_id"],)).fetchone()
                    if ob is not None and ob["status"] == "pending":
                        self.commands.mark_dispatched(locked["outbox_id"])
                conn.execute("UPDATE payment_intents SET status='submitted', submitted_at=? WHERE id=? AND status='queued'", (utcnow_iso(), intent["id"]))
                self.audit.record(actor, "payment.submitted", "payment_intent", intent["id"], {
                    "note": "found at the provider by recovery reconciliation; recorded as submitted without a second submission",
                    "provider_ref": found["provider_ref"], "outbox_id": locked["outbox_id"],
                })
                failures = self._accept(intent["id"], provider_ref=found["provider_ref"], actor=actor)
            results.append(self._result(intent["id"], "accepted", failures, provider_ref=found["provider_ref"], recovered_from="queued"))
        return results, unresolved

    def _provider_transfers(self, provider: Any) -> list[dict[str, Any]]:
        lister = getattr(provider, "list_transfers", None)
        if lister is None:
            raise PaymentError("the provider cannot list its transfers, so transfers this copy never recorded cannot be ruled out")
        try:
            return list(lister())
        except ConnectionError as exc:
            raise PaymentError(f"provider unreachable while listing transfers: {exc}") from exc

    def _unrecorded_transfers(self, provider: Any) -> tuple[list[dict[str, Any]], str | None]:
        """Transfers the provider holds for this workspace that no local intent records,
        each with whether ``payment.adopt_transfer`` can record it as it stands.  Returns
        ``(transfers, problem)``; ``problem`` says why the provider could not be asked."""
        try:
            transfers = self._provider_transfers(provider)
        except PaymentError as exc:
            return [], str(exc)
        workspace_id = self.db.workspace()["workspace_id"]
        known_ops = {r["logical_op_id"] for r in self.db.query("SELECT logical_op_id FROM payment_intents")}
        known_refs = {r["provider_ref"] for r in self.db.query("SELECT provider_ref FROM payment_intents WHERE provider_ref IS NOT NULL")}
        out = []
        for t in transfers:
            reference = t.get("reference") or {}
            if reference.get("workspace_id") and reference["workspace_id"] != workspace_id:
                continue  # another workspace's transfer on the same rail
            if t.get("logical_op_id") in known_ops or t.get("provider_ref") in known_refs:
                continue
            item = {k: t.get(k) for k in ("provider_ref", "logical_op_id", "amount", "fee", "destination", "status", "settled", "value_date", "currency", "reference")}
            try:
                plan = self._adoption_plan(t, None, provider)
            except (PaymentError, RuntimeError) as exc:
                item.update({"adoptable": False, "adoption_problem": str(exc)})
            else:
                item.update({"adoptable": True, "adoption_problem": None, "pays": f"{plan['source_type']} {plan['source_id']}",
                             "supersedes": plan["superseded"]})
            out.append(item)
        return out, None

    def complete_recovery_reconciliation(self, provider: SimulatedProvider, *, actor: str) -> dict[str, Any]:
        """After a restore: look queued intents up at the provider, resolve every
        in-doubt intent, catch up missed callbacks, list the provider's transfers for
        transfers this copy never recorded, and only then lift the release quarantine.
        Requires write authority on this copy.

        The quarantine stays (``quarantine_lifted`` False, reasons in ``held``) while an
        intent is unresolved, while a missed callback cannot be caught up (no webhook
        secret, or the provider is unreachable), while the provider cannot list its
        transfers, and while it holds a transfer for this workspace that no local
        intent records (``unrecorded_transfers``; record each with the approval
        ``payment.adopt_transfer`` and run recovery again).  Lifting with any of these
        open could pay an obligation the live workspace already paid."""
        self.db.require_write_authority()
        results, unresolved_queued = self._resolve_queued_after_restore(provider, actor=actor)
        results.extend(self._resolve_in_doubt(provider, actor=actor))
        callbacks, callbacks_blocked = self._catch_up_callbacks(provider, actor=actor)
        unrecorded, transfer_problem = self._unrecorded_transfers(provider)
        unresolved = [u["id"] for u in self.db.query("SELECT id FROM payment_intents WHERE status IN ('submitted','outcome_unknown') ORDER BY created_at")]
        unresolved.extend(i for i in unresolved_queued if i not in unresolved)
        still_queued = [q["id"] for q in self.db.query("SELECT id FROM payment_intents WHERE status='queued' ORDER BY created_at")]
        held: list[str] = []
        if unresolved:
            held.append(f"{len(unresolved)} payment intent(s) unresolved at the provider: {', '.join(unresolved)}")
        for b in callbacks_blocked:
            held.append(f"missed provider callback for intent {b['intent_id']} not caught up: {b['reason']}")
        if transfer_problem:
            held.append(transfer_problem)
        if unrecorded:
            held.append(f"the provider holds {len(unrecorded)} transfer(s) for this workspace that this copy never recorded "
                        f"({', '.join(t['provider_ref'] for t in unrecorded)}); record each with a {ADOPT_OPERATION} approval, then run recovery again")
        outcome = {"results": results, "callbacks": callbacks, "callbacks_unresolved": callbacks_blocked, "queued": still_queued,
                   "unrecorded_transfers": unrecorded, "held": held}
        ws = self.db.workspace()
        if held:
            with self.db.transaction():
                self.audit.record(actor, "recovery.held", "workspace", ws["workspace_id"], {
                    "recovery_epoch": ws["recovery_epoch"], "held": held, "unresolved": unresolved,
                    "unrecorded_transfers": [t["provider_ref"] for t in unrecorded], "callbacks_unresolved": callbacks_blocked,
                })
            return {"quarantine_lifted": False, "unresolved": unresolved, **outcome}
        with self.db.transaction() as conn:
            conn.execute("UPDATE workspace SET reconciled_epoch=?, updated_at=? WHERE id=1", (ws["recovery_epoch"], utcnow_iso()))
            self.audit.record(actor, "recovery.reconciled", "workspace", ws["workspace_id"], {
                "recovery_epoch": ws["recovery_epoch"], "results": results, "callbacks": callbacks, "queued_not_found": still_queued,
            })
        return {"quarantine_lifted": True, "unresolved": [], **outcome}

    # ---- adopting a provider transfer this copy never recorded ---------------------- #

    @staticmethod
    def _parse_adoption_subject(subject_id: Any) -> tuple[str, tuple[str, str] | None]:
        if not isinstance(subject_id, str) or not subject_id.strip():
            raise PaymentError(f"{ADOPT_OPERATION} needs a provider reference as its subject")
        ref, sep, source = subject_id.partition("=")
        ref = ref.strip()
        if not ref:
            raise PaymentError(f"{ADOPT_OPERATION} needs a provider reference as its subject")
        if not sep:
            return ref, None
        source_type, colon, source_id = source.partition(":")
        if not colon or not source_type.strip() or not source_id.strip():
            raise PaymentError(f"name the local record as '<provider_ref>=<source_type>:<source_id>', not {subject_id!r}")
        return ref, (source_type.strip(), source_id.strip())

    def _transfer_at_provider(self, provider_ref: str, provider: Any) -> dict[str, Any]:
        for t in self._provider_transfers(provider):
            if t.get("provider_ref") == provider_ref:
                return t
        raise PaymentError(f"the provider holds no transfer {provider_ref}")

    def _superseded_queued(self, source_type: str, source_id: str, provider: Any) -> list[str]:
        """Local in-progress intents for the record a transfer paid.  Only queued intents the
        provider has never seen can give way (they are canceled as superseded); anything
        dispatched must be reconciled first."""
        superseded = []
        rows = self.db.query(
            f"SELECT * FROM payment_intents WHERE source_type=? AND source_id=? AND status IN ({','.join('?' * len(IN_PROGRESS_STATES))}) ORDER BY created_at",
            (source_type, source_id, *IN_PROGRESS_STATES),
        )
        for i in rows:
            if i["status"] != "queued":
                raise PaymentError(f"payment intent {i['id']} for {source_type} {source_id} is {i['status']}; reconcile it before adopting another transfer for that record")
            try:
                found = provider.lookup(i["logical_op_id"])
            except ConnectionError as exc:
                raise PaymentError(f"cannot confirm with the provider that queued intent {i['id']} was never transferred ({exc})") from exc
            if found.get("found"):
                raise PaymentError(f"the provider also holds transfer {found.get('provider_ref')} for queued intent {i['id']} on {source_type} {source_id}; "
                                   "run recovery reconciliation first")
            superseded.append(i["id"])
        return superseded

    def _plan_bill(self, bill_id: str, *, amount: Any, transfer_status: str) -> dict[str, Any]:
        b = self.db.one("SELECT b.*, c.supplier_id, c.project_id FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE b.id=?", (bill_id,))
        if b is None:
            raise PaymentError(f"bill {bill_id} does not exist in this copy; re-key it, then name it: '<provider_ref>=bill:<bill id>'")
        allowed = ("posted", "paid") if transfer_status == "returned" else ("posted",)
        if b["status"] not in allowed:
            raise PaymentError(f"bill {bill_id} is {b['status']} in this copy; only a posted (unpaid) bill can take an adopted payment")
        if money(b["amount_due"]) != amount:
            raise PaymentError(f"the transfer is for {fmt(amount)} but bill {bill_id} is due {b['amount_due']}")
        return {"project_id": b["project_id"], "party_id": b["supplier_id"], "payable_account": DEFAULT_PAYABLE_ACCOUNT, "bill_id": b["id"],
                "label": CORE_SOURCE_LABELS["bill"], "binding": {"bill_hash": b["content_hash"], "bill_status": b["status"], "amount_due": b["amount_due"]}}

    def _plan_retainage(self, commitment_id: str, *, amount: Any, superseded: list[str], transfer_status: str) -> dict[str, Any]:
        c = self.db.one("SELECT * FROM commitments WHERE id=?", (commitment_id,))
        if c is None:
            raise PaymentError(f"commitment {commitment_id} does not exist in this copy")
        released = money(self.ledger.account_activity("2050", party_id=c["supplier_id"], project_id=c["project_id"])["debit"])
        paid = self.db.query(
            """SELECT id, amount FROM payment_intents
               WHERE bill_id IS NULL AND party_id=? AND status IN ('queued','submitted','outcome_unknown','accepted','settled')
                 AND ((source_type='retainage_release' AND project_id=?) OR (payable_account IS NULL AND note LIKE 'retainage%'))""",
            (c["supplier_id"], c["project_id"]),
        )
        committed = money(sum((money(p["amount"]) for p in paid if p["id"] not in superseded), ZERO))
        outstanding = money(released - committed)
        if transfer_status != "returned" and amount > outstanding:
            raise PaymentError(f"the transfer is for {fmt(amount)} but only {fmt(outstanding)} of released retainage is payable on commitment {commitment_id} in this copy")
        return {"project_id": c["project_id"], "party_id": c["supplier_id"], "payable_account": DEFAULT_PAYABLE_ACCOUNT, "bill_id": None,
                "label": CORE_SOURCE_LABELS["retainage_release"],
                "binding": {"released_retainage": fmt(released), "retainage_paid_or_in_flight": fmt(committed)}}

    def _adoption_plan(self, t: dict[str, Any], override: tuple[str, str] | None, provider: Any) -> dict[str, Any]:
        """How transfer ``t`` would be recorded in this copy, or PaymentError saying why it cannot be."""
        reference = t.get("reference") or {}
        workspace_id = self.db.workspace()["workspace_id"]
        if reference.get("workspace_id") and reference["workspace_id"] != workspace_id:
            raise PaymentError(f"transfer {t.get('provider_ref')} was made for workspace {reference['workspace_id']}, not this one")
        if self.db.one("SELECT id FROM payment_intents WHERE logical_op_id=? OR provider_ref=?", (t.get("logical_op_id"), t.get("provider_ref"))):
            raise PaymentError(f"transfer {t.get('provider_ref')} is already recorded in this copy")
        source_type, source_id = override or (reference.get("source_type"), reference.get("source_id"))
        if not source_type or not source_id:
            raise PaymentError(f"transfer {t.get('provider_ref')} names no Cipher record; name the local record it paid: '<provider_ref>=<source_type>:<source_id>'")
        try:
            amount = money(t.get("amount"))
            fee = money(t.get("fee") or "0.00")
        except MoneyError as exc:
            raise PaymentError(f"the provider reports a transfer amount or fee that is not exact money: {exc}") from exc
        if amount <= 0 or fee < 0:
            raise PaymentError(f"the provider reports amount {fmt(amount)} and fee {fmt(fee)} for transfer {t.get('provider_ref')}")
        status = t.get("status")
        if status not in ("accepted", "settled", "returned"):
            raise PaymentError(f"transfer {t.get('provider_ref')} is {status!r} at the provider")
        superseded = self._superseded_queued(source_type, source_id, provider)
        if source_type == "bill":
            plan = self._plan_bill(source_id, amount=amount, transfer_status=status)
        elif source_type == "retainage_release":
            plan = self._plan_retainage(source_id, amount=amount, superseded=superseded, transfer_status=status)
        else:
            adopter = self._adopters.get(source_type)
            if adopter is None:
                raise PaymentError(f"transfer {t.get('provider_ref')} pays {source_type} {source_id}, which has no adoption path in this copy")
            try:
                plan = dict(adopter["plan"](source_id, amount=amount, party_id=reference.get("party_id"), superseded=superseded, transfer_status=status))
            except PaymentError:
                raise
            except RuntimeError as exc:
                raise PaymentError(f"{source_type} {source_id}: {exc}") from exc
            plan.setdefault("bill_id", None)
            plan["label"] = adopter["label"]
        if reference.get("party_id") and reference["party_id"] != plan["party_id"]:
            raise PaymentError(f"transfer {t.get('provider_ref')} was made to party {reference['party_id']}, but {source_type} {source_id} pays {plan['party_id']}")
        party = self.db.one("SELECT * FROM parties WHERE id=?", (plan["party_id"],))
        if party is None:
            raise PaymentError(f"payee {plan['party_id']} does not exist in this copy")
        if party["destination"] != t.get("destination") or not party["destination_verified"]:
            raise PaymentError(f"transfer {t.get('provider_ref')} went to destination {t.get('destination')!r}, but payee {party['id']}'s verified destination in this copy "
                               "differs (or is unverified); verify the payee's destination in this copy first")
        acct = self.db.one("SELECT type FROM accounts WHERE code=?", (plan["payable_account"],))
        if acct is None or acct["type"] != "liability":
            raise PaymentError(f"payable account {plan['payable_account']} is not a liability account in the chart")
        project = self.db.one("SELECT entity, currency FROM projects WHERE id=?", (plan["project_id"],))
        if project is None:
            raise PaymentError(f"project {plan['project_id']} does not exist in this copy")
        currency = project["currency"] or "USD"
        if t.get("currency") and t["currency"] != currency:
            raise PaymentError(f"transfer {t.get('provider_ref')} is in {t['currency']}, but project {plan['project_id']} is in {currency}")
        return {**plan, "source_type": source_type, "source_id": source_id, "superseded": superseded, "amount": fmt(amount), "fee": fmt(fee),
                "party": party, "entity": project["entity"], "currency": currency}

    def _adoption_manifest(self, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        provider_ref, override = self._parse_adoption_subject(subject_id)
        if self.provider is None:
            raise PaymentError("no provider is bound; a transfer can only be adopted from the provider that holds it")
        t = self._transfer_at_provider(provider_ref, self.provider)
        plan = self._adoption_plan(t, override, self.provider)
        party = plan["party"]
        manifest = build_manifest(
            operation=ADOPT_OPERATION,
            subject_type=TRANSFER_SUBJECT_TYPE,
            subject_id=subject_id,
            actor_role=actor_role,
            amounts={"amount": plan["amount"], "fee": plan["fee"]},
            bindings={
                "provider_ref": provider_ref, "logical_op_id": t.get("logical_op_id"), "payload_hash": t.get("payload_hash"), "value_date": t.get("value_date"),
                "reference": t.get("reference"), "source_type": plan["source_type"], "source_id": plan["source_id"], "bill_id": plan["bill_id"],
                "project_id": plan["project_id"], "payable_account": plan["payable_account"], "label": plan["label"], "source": plan["binding"],
                "superseded_intents": plan["superseded"],
            },
            destination={"party_id": party["id"], "destination": party["destination"], "destination_version": party["destination_version"]},
            entity=plan["entity"],
            currency=plan["currency"],
        )
        # what the approver sees about the transfer's progress; not material (a settlement after the
        # grant is simply booked as well when the adoption executes)
        manifest["observed"] = {"provider_status": t.get("status"), "settled": bool(t.get("settled"))}
        return manifest

    def _apply_adoption(self, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str) -> dict[str, Any]:
        """Record the approved transfer: cancel the superseded queued intents, create the
        intent (no outbox row: nothing is ever submitted for it), let the source module
        link it, book the provider's acceptance (one journal) and catch up a settlement
        or return the provider reports."""
        bound = manifest.get("bindings") or {}
        provider_ref = bound["provider_ref"]
        provider = self.provider
        with self.db.transaction() as conn:
            self.db.require_write_authority()
            if conn.execute("SELECT id FROM payment_intents WHERE logical_op_id=? OR provider_ref=?", (bound["logical_op_id"], provider_ref)).fetchone():
                raise PaymentError(f"transfer {provider_ref} is already recorded in this copy")
            superseded = []
            for intent_id in bound.get("superseded_intents") or []:
                i = self.db.one("SELECT * FROM payment_intents WHERE id=?", (intent_id,))
                if i is None or i["status"] != "queued":
                    raise PaymentError(f"payment intent {intent_id} is no longer queued; request the adoption again")
                self._cancel_queued(i, reason=f"superseded by provider transfer {provider_ref}, adopted under approval {approval_id}", actor=actor,
                                    provider_check="provider has no transfer for it (checked when the adoption was executed)",
                                    extra={"superseded_by": provider_ref, "adoption_approval_id": approval_id})
                superseded.append(intent_id)
            live = conn.execute(
                f"SELECT id FROM payment_intents WHERE source_type=? AND source_id=? AND status IN ({','.join('?' * len(IN_PROGRESS_STATES))})",
                (bound["source_type"], bound["source_id"], *IN_PROGRESS_STATES),
            ).fetchone()
            if live:
                raise PaymentError(f"payment intent {live['id']} for {bound['source_type']} {bound['source_id']} is still in progress")
            dest = manifest.get("destination") or {}
            amounts = manifest.get("amounts") or {}
            ws = self.db.workspace()
            intent_id = new_id("pay")
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO payment_intents (id, bill_id, party_id, amount, destination, destination_version, status, approval_id, logical_op_id, payload_hash,
                                                recovery_epoch, created_at, submitted_at, note, project_id, source_type, source_id, payable_account, fee, value_date, entity, currency)
                   VALUES (?,?,?,?,?,?,'submitted',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (intent_id, bound.get("bill_id"), dest["party_id"], amounts["amount"], dest["destination"], dest["destination_version"], approval_id,
                 bound["logical_op_id"], bound.get("payload_hash") or hash_json({"adopted": provider_ref}), ws["recovery_epoch"], now, now,
                 f"{bound['label']}{_REASON_SEP}adopted provider transfer {provider_ref} (made outside this copy)",
                 bound["project_id"], bound["source_type"], bound["source_id"], bound["payable_account"], amounts.get("fee", "0.00"), bound.get("value_date"),
                 manifest.get("entity"), manifest.get("currency") or "USD"),
            )
            adopter = self._adopters.get(bound["source_type"])
            if adopter is not None:
                adopter["link"](self.db.one("SELECT * FROM payment_intents WHERE id=?", (intent_id,)), approval_id=approval_id, actor=actor)
            self.audit.record(actor, "payment.adopted", "payment_intent", intent_id, {
                "provider_ref": provider_ref, "logical_op_id": bound["logical_op_id"], "approval_id": approval_id, "amount": amounts["amount"], "fee": amounts.get("fee"),
                "source_type": bound["source_type"], "source_id": bound["source_id"], "project_id": bound["project_id"], "superseded_intents": superseded,
                "observed": manifest.get("observed"),
            })
            failures = self._accept(intent_id, provider_ref=provider_ref, actor=actor)
            callbacks: list[dict[str, Any]] = []
            if self.webhook_secret and provider is not None:
                intent = self.db.one("SELECT * FROM payment_intents WHERE id=?", (intent_id,))
                try:
                    found = provider.lookup(bound["logical_op_id"])
                except ConnectionError:
                    found = {"found": False}
                if found.get("found") and found.get("provider_ref") == provider_ref:
                    caught = self._catch_up_intent(intent, found, actor=actor)
                    if caught is not None:
                        callbacks.append(caught)
        status = self.db.one("SELECT status FROM payment_intents WHERE id=?", (intent_id,))["status"]
        out = {"intent": intent_id, "status": status, "provider_ref": provider_ref, "amount": amounts["amount"], "source_type": bound["source_type"],
               "source_id": bound["source_id"], "superseded": superseded, "callbacks": callbacks}
        if failures:
            out["listener_errors"] = failures
        return out

    def clearing_items(self, project_id: str | None = None) -> dict[str, Any]:
        """Accepted-but-unsettled intents against provider clearing (1200).

        Sign convention: 1200 is debit-normal and acceptance credits it, so money in
        transit shows as a *negative* control balance.  ``subledger_total`` is stated
        in that same sign (minus the in-transit total) so it compares like with like;
        ``in_transit_total`` gives the positive amount the provider still holds."""
        items = []
        in_transit = ZERO
        for intent in self.db.query("SELECT * FROM payment_intents WHERE status='accepted' ORDER BY created_at, id"):
            pid = self._project_for(intent)
            if project_id and pid != project_id:
                continue
            amt = money(intent["amount"])
            items.append({
                "intent_id": intent["id"], "provider_ref": intent["provider_ref"], "project_id": pid, "party_id": intent["party_id"],
                "amount": fmt(amt), "clearing_effect": fmt(-amt), "journal_id": intent["journal_id"],
            })
            in_transit += amt
        subledger = money(-in_transit)
        control = self.ledger.balance(CLEARING_ACCOUNT, project_id=project_id) if project_id else self.ledger.balance(CLEARING_ACCOUNT)
        return {
            "items": items, "in_transit_total": fmt(in_transit), "subledger_total": fmt(subledger), "control_balance": fmt(control),
            "reconciled": subledger == control,
            "sign_convention": "1200 is debit-normal; accepted-unsettled intents are credits, so both totals are negative while money is in transit",
        }

    # ---- provider events ------------------------------------------------------- #

    def _reject_event(self, event: Any, reason: str, *, actor: str) -> NoReturn:
        event_id = event.get("id") if isinstance(event, dict) else None
        try:
            event_hash = hash_json(event)
        except (TypeError, ValueError):
            event_hash = None
        payload = {"reason": reason, "event_hash": event_hash}
        if isinstance(event, dict):
            payload.update({"kind": event.get("kind"), "provider_ref": event.get("provider_ref"), "signed": SIGNATURE_FIELD in event})
        with self.db.transaction():
            self.audit.record(actor, "provider_event.rejected", "provider_event", str(event_id or "unidentified"), payload)
        raise ProviderEventRejected(f"provider event {event_id or '(no id)'} rejected: {reason}")

    def _authenticate_event(self, event: Any, *, actor: str) -> None:
        if not isinstance(event, dict):
            self._reject_event(event, "a provider event must be a JSON object", actor=actor)
        if not self.webhook_secret:
            self._reject_event(event, "no webhook secret is configured, so provider callbacks cannot be authenticated", actor=actor)
        if SIGNATURE_FIELD not in event:
            self._reject_event(event, "unsigned provider event", actor=actor)
        if not verify_event(event, self.webhook_secret):
            self._reject_event(event, "signature does not verify (forged or altered event)", actor=actor)
        for key in ("id", "kind", "provider_ref"):
            if not isinstance(event.get(key), str) or not event[key].strip():
                self._reject_event(event, f"malformed provider event: {key} is missing", actor=actor)

    def ingest_event(self, event: dict[str, Any], *, actor: str) -> dict[str, Any]:
        """Apply a provider callback.  The event must carry a valid signature from the
        provider's webhook secret; unsigned, forged or malformed events are rejected
        (and audited) before any state change.  Duplicates are ignored by event id.
        An authentic event that contradicts Cipher's records -- an unknown
        ``provider_ref`` or an amount other than the intent's -- is rejected with
        ``ProviderEventRejected`` and audited (``provider_event.rejected``) too.
        The intent is read under the write lock, so concurrent deliveries cannot both
        act on the same intent status.

        A return of a transfer the provider settled first (``settled_before_return``)
        on an intent Cipher still holds as accepted means the settlement callback was
        lost: the settlement is booked first from a derived, signed reconciliation
        event ``recon_<provider_ref>_settled`` (fee and bank leg as approved), so the
        books end exactly where they would had both callbacks arrived."""
        self._authenticate_event(event, actor=actor)
        with self.db.transaction() as conn:
            intent = self.db.one("SELECT * FROM payment_intents WHERE provider_ref=?", (event["provider_ref"],))
            if intent is not None and self.db.one("SELECT id FROM provider_events WHERE id=?", (event["id"],)):
                self.audit.record(actor, "provider_event.duplicate", "payment_intent", intent["id"], {"event_id": event["id"]})
                return {"intent_id": intent["id"], "applied": False, "reason": "duplicate event"}
            problem = self._event_contradiction(event, intent)
            if problem is None:
                derived: dict[str, Any] | None = None
                if event["kind"] == "returned" and intent["status"] == "accepted" and event.get("settled_before_return") is True:
                    derived = self._derived_settlement(event, intent)
                    if self.db.one("SELECT id FROM provider_events WHERE id=?", (derived["id"],)) is None:
                        derived_outcome = self._apply_event(conn, derived, intent, actor=actor)
                        intent = self.db.one("SELECT * FROM payment_intents WHERE id=?", (intent["id"],))
                    else:
                        derived_outcome = {}
                out = self._apply_event(conn, event, intent, actor=actor)
                if derived is not None:
                    out["derived_settlement"] = derived["id"]
                    errors = list(derived_outcome.get("listener_errors", [])) + list(out.get("listener_errors", []))
                    if errors:
                        out["listener_errors"] = errors
                return out
        # A provider-signed event that contradicts Cipher's records is a serious anomaly: the
        # transaction above changed nothing, and the rejection is audited in its own.
        self._reject_event(event, problem, actor=actor)

    def _derived_settlement(self, returned: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
        """The settlement a ``settled_before_return`` return proves happened."""
        event = {"id": f"recon_{intent['provider_ref']}_settled", "kind": "settled", "provider_ref": intent["provider_ref"], "amount": intent["amount"],
                 "source": "reconciliation", "observed_status": "returned", "derived_from": returned["id"]}
        return sign_event(event, self.webhook_secret) if self.webhook_secret else event

    @staticmethod
    def _event_contradiction(event: dict[str, Any], intent: dict[str, Any] | None) -> str | None:
        """Why an authentic event cannot apply to Cipher's records, or None."""
        if intent is None:
            return f"references unknown provider_ref {event['provider_ref']}"
        if "amount" in event:
            try:
                mismatch = money(event["amount"]) != money(intent["amount"])
            except MoneyError:
                mismatch = True
            if mismatch:
                return f"reports amount {event['amount']!r} but intent {intent['id']} is for {intent['amount']}"
        return None

    def _apply_event(self, conn: Any, event: dict[str, Any], intent: dict[str, Any], *, actor: str) -> dict[str, Any]:
        """Apply an authenticated, consistent, not-yet-seen event; the caller holds the write lock."""
        period = self.db.one("SELECT id FROM periods WHERE status='open' ORDER BY start_date DESC LIMIT 1")
        if period is None:
            raise PaymentError("no open period")
        project_id = self._project_for(intent)
        payable = self._payable_for(intent)
        conn.execute("INSERT INTO provider_events (id, intent_id, kind, payload_json, received_at) VALUES (?,?,?,?,?)", (event["id"], intent["id"], event["kind"], canonical_json(event), utcnow_iso()))
        if event["kind"] == "settled" and intent["status"] == "accepted":
            amount = money(intent["amount"])
            fee = money(intent.get("fee") or "0.00")
            lines = [{"account": CLEARING_ACCOUNT, "debit": amount, "project_id": project_id, "party_id": intent["party_id"], "memo": "clearing settled"}]
            if fee > 0:
                lines.append({"account": FEE_ACCOUNT, "debit": fee, "project_id": project_id, "party_id": intent["party_id"], "memo": "provider transfer fee (as approved)"})
            lines.append({"account": "1000", "credit": amount + fee, "project_id": project_id, "party_id": intent["party_id"], "memo": "bank disbursement"})
            self.ledger.post(
                period_id=period["id"], description=f"Payment settled ({intent['provider_ref']})", lines=lines,
                source_type="provider_event", source_id=event["id"], source_version="1", posted_by=actor,
            )
            conn.execute("UPDATE payment_intents SET status='settled', resolved_at=? WHERE id=?", (utcnow_iso(), intent["id"]))
        elif event["kind"] == "returned" and intent["status"] in ("accepted", "settled"):
            src = "1000" if intent["status"] == "settled" else CLEARING_ACCOUNT
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
                # the bill is open again unless another booked payment still pays it
                other = self.db.one("SELECT id FROM payment_intents WHERE bill_id=? AND id != ? AND status IN ('accepted','settled')", (intent["bill_id"], intent["id"]))
                if other is None:
                    conn.execute("UPDATE bills SET status='posted' WHERE id=? AND status='paid'", (intent["bill_id"],))
        else:
            self.audit.record(actor, "provider_event.ignored", "payment_intent", intent["id"], {"event_id": event["id"], "kind": event["kind"], "intent_status": intent["status"]})
            return {"intent_id": intent["id"], "applied": False, "reason": f"{event['kind']} not applicable to {intent['status']}"}
        self.audit.record(actor, f"provider_event.{event['kind']}", "payment_intent", intent["id"], {
            "event_id": event["id"], "project_id": project_id, "payable_account": payable, "source": event.get("source", "provider"),
        })
        failures = self._notify(intent["id"], actor=actor)
        out = {"intent_id": intent["id"], "applied": True}
        if failures:
            out["listener_errors"] = failures
        return out
