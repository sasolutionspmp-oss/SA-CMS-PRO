"""Staff expense reimbursements, kept separate from customer billing.

An employee submits a claim backed by a receipt.  Nothing touches the books
until an owner approves the claim; approval posts the reimbursable expense and
the employee payable.  Payments draw the payable down (partial payments are
allowed, over-payment is not) and leave Cipher the same way every other
payment does: through a payment intent, the durable outbox and the provider.
Billing the customer for a billable claim is a *separate* authority path: it
posts receivable and revenue and never changes the employee payable.  An
approval granted in error is corrected by voiding the claim, which appends a
reversal of the approval journal; posted journals are never edited.

Posting rules (fixture policy ``cipher-posting-rules/1``):

* ``reimbursement.approve``  Dr 5100 reimbursable expense / Cr 2100 employee payable (party = employee)
* ``reimbursement.pay``      posts nothing itself: it queues a payment intent (payable account 2100,
                             project = the claim's project, source = the reimbursement payment) to the
                             employee's independently verified destination.  The core payment path then posts
                             provider acceptance  Dr 2100 / Cr 1200 provider clearing
                             settlement           Dr 1200 / Cr 1000 operating bank
                             a provider return    Dr 1000 (or 1200 before settlement) / Cr 2100, reinstating the payable
* ``reimbursement.bill``     Dr 1100 accounts receivable (party = project customer) / Cr 4000 contract revenue
* billing collection        Dr 1000 operating bank (net of fee) / Dr 6000 fee / Cr 1100 (``record_billing_collection``:
                             a bank fact like a prime-bill collection, so it needs no approval; one per provider reference)
* ``reimbursement.void``     reversal of the approval journal (Dr 2100 / Cr 5100); only while nothing
                             has been paid, is in flight or has been billed on the claim

Accounts receivable from billings (``ar_open_items``): each posted billing is open for its
billed amount less the collections recorded against it whose journal still stands; a reversal
of the billing journal (for example through ``journal.reverse``) clears whatever it billed,
and a reversal of a collection journal (a customer receipt returned unpaid) reinstates what
that collection cleared, so the billing can be collected again under a new provider reference.
Nothing else clears a billing.  The receivables domain adds these items to the AR subledger it reconciles to 1100
(``receivables.extra_ar_sources``), and ``close_checks`` confirms the items match the 1100
postings made by billings, their collections and their reversals.

Record lifecycle (schema triggers reject every other change, including an ``INSERT OR
REPLACE`` that would overwrite a stored row: ``reimbursements_no_replace``):

* claim:    submitted -> approved -> partially_paid -> paid   (only with a booked payment on it)
                         approved -> voided                   (only with nothing booked or in flight)
            a provider return moves partially_paid / paid back, once per returned payment: to
            approved when no booked payment remains, otherwise to partially_paid
* payment:  draft -> in_flight -> booked -> returned
                     in_flight -> failed
                     in_flight -> draft   (its intent was canceled before dispatch)
            draft -> canceled
  A payment's status follows its payment intent: queued / submitted / outcome unknown = in_flight,
  accepted / settled = booked, failed = failed (the obligation stays open: the in-flight
  reservation is released, so the claim's outstanding balance is payable again through a new
  payment and a fresh approval), returned = returned.  A canceled intent puts the payment back
  to ``draft``: the link to the canceled intent and its approval are cleared (the canceled intent
  still names this payment as its source, and the audit log records the cancel), the version
  bumps, and the same payment can be approved and released again (or canceled as a draft).
  An intent is canceled only while it is still queued (``Payments.cancel_intent``), so a canceled
  intent never posted anything.  (Payments whose intents were canceled before
  ``reimbursements_cancel_reopens`` was applied stay ``failed``.)
  Its approval is the one its intent was created under; its journal and period are the intent's
  acceptance journal and that journal's period.
  Restore recovery: a provider transfer for one of these payments that the restored copy never
  recorded is adopted through the core ``payment.adopt_transfer`` approval; this module checks the
  payment (draft, or in flight on a queued intent the adoption supersedes), the amount, the payee
  and the claim's outstanding balance, then links the adopted intent like a release would.
  The core payment module notifies this module inside the transaction that changes the intent.
  Should this module's handler fail there, the core still commits the intent change (the provider
  has acted) and audits the failure; the payment is then out of step with its intent, which
  ``close_checks`` reports and ``sync_payments`` repairs.
* billing:  draft -> billed | canceled

Amounts on an approved claim:

* ``payable``      approved amount - booked payments: the liability on the books, reconciled to 2100
* ``in_flight``    payments released to the outbox and not yet accepted or failed
* ``outstanding``  payable - in_flight: what may still be paid (in-flight amounts are reserved,
                   so a second payment can never overpay while the first is unresolved)

Approvals bind the record version and content hash of the subject, the amount,
the employee, the receipt hash and (for payments) the claim's outstanding
balance, the employee's verified destination and its version, the project's
entity and currency, the value date and the provider fee, so any
material change after an approval was granted invalidates it instead of
executing something the approver did not see.  Editing a submitted claim,
releasing a payment, posting a billing or voiding the claim also proactively
invalidates the open approvals that the change makes meaningless.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..core.approvals import build_manifest
from ..core.db import register_schema_version
from ..core.ids import hash_json, new_id, utcnow_iso
from ..core.money import ZERO, MoneyError, fmt, money, total
from .payments import SCOPE_SCHEMA_NAME  # noqa: F401  (registers the payment scope columns first)

SCHEMA_NAME = "reimbursements"
PLUGIN_NAME = "reimbursement"
POSTING_RULE = "cipher-posting-rules/1"
EMPLOYEE_PAYABLE = "2100"
PAYMENT_ROUTE = "payment-intent outbox (simulated provider)"

CLAIM_SUBJECT = "reimbursement_claim"
PAYMENT_SUBJECT = "reimbursement_payment"
BILLING_SUBJECT = "reimbursement_billing"

OP_APPROVE = "reimbursement.approve"
OP_PAY = "reimbursement.pay"
OP_BILL = "reimbursement.bill"
OP_VOID = "reimbursement.void"

APPROVED_STATES = ("approved", "partially_paid", "paid")
PAYABLE_STATES = ("approved", "partially_paid")

SCHEMA_STATEMENTS = [
    """CREATE TABLE reimbursement_claims (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        employee_id TEXT NOT NULL REFERENCES parties(id),
        description TEXT NOT NULL,
        amount TEXT NOT NULL,
        receipt_hash TEXT NOT NULL,
        billable INTEGER NOT NULL DEFAULT 0 CHECK (billable IN (0, 1)),
        status TEXT NOT NULL CHECK (status IN ('submitted','approved','partially_paid','paid','voided')),
        version INTEGER NOT NULL DEFAULT 1,
        content_hash TEXT NOT NULL,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        period_id TEXT REFERENCES periods(id),
        void_approval_id TEXT REFERENCES approvals(id),
        reversal_journal_id TEXT REFERENCES journals(id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        approved_at TEXT,
        voided_at TEXT
    )""",
    # One live claim per receipt.  A voided claim keeps its row as history but releases the
    # receipt so the employee can resubmit a corrected claim for it.
    "CREATE UNIQUE INDEX reimbursement_claims_live_receipt ON reimbursement_claims(receipt_hash) WHERE status != 'voided'",
    """CREATE TABLE reimbursement_payments (
        id TEXT PRIMARY KEY,
        claim_id TEXT NOT NULL REFERENCES reimbursement_claims(id),
        amount TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','booked','canceled')),
        version INTEGER NOT NULL DEFAULT 1,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        period_id TEXT REFERENCES periods(id),
        created_at TEXT NOT NULL,
        booked_at TEXT,
        canceled_at TEXT
    )""",
    """CREATE TABLE reimbursement_billings (
        id TEXT PRIMARY KEY,
        claim_id TEXT NOT NULL REFERENCES reimbursement_claims(id),
        customer_id TEXT NOT NULL REFERENCES parties(id),
        amount TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','billed','canceled')),
        version INTEGER NOT NULL DEFAULT 1,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        period_id TEXT REFERENCES periods(id),
        created_at TEXT NOT NULL,
        billed_at TEXT,
        canceled_at TEXT
    )""",
    # Once a claim has been approved its content is frozen: corrections go through reimbursement.void.
    """CREATE TRIGGER reimbursement_claims_frozen_after_approval
        BEFORE UPDATE OF amount, description, receipt_hash, employee_id, project_id, billable ON reimbursement_claims
        WHEN OLD.status != 'submitted'
        BEGIN SELECT RAISE(ABORT, 'approved reimbursement claims are immutable; correct through reimbursement.void'); END""",
    # The status column only ever moves forward along the documented lifecycle.
    """CREATE TRIGGER reimbursement_claims_status_forward_only
        BEFORE UPDATE OF status ON reimbursement_claims
        WHEN NEW.status != OLD.status AND NOT (
            (OLD.status = 'submitted' AND NEW.status = 'approved')
            OR (OLD.status = 'approved' AND NEW.status IN ('partially_paid','paid','voided'))
            OR (OLD.status = 'partially_paid' AND NEW.status = 'paid')
        )
        BEGIN SELECT RAISE(ABORT, 'illegal reimbursement claim status transition'); END""",
    "CREATE TRIGGER reimbursement_claims_no_delete BEFORE DELETE ON reimbursement_claims BEGIN SELECT RAISE(ABORT, 'reimbursement claims are never deleted'); END",
    """CREATE TRIGGER reimbursement_payments_final_immutable BEFORE UPDATE ON reimbursement_payments
        WHEN OLD.status IN ('booked','canceled')
        BEGIN SELECT RAISE(ABORT, 'booked or canceled reimbursement payments are immutable'); END""",
    "CREATE TRIGGER reimbursement_payments_no_delete BEFORE DELETE ON reimbursement_payments BEGIN SELECT RAISE(ABORT, 'reimbursement payments are never deleted'); END",
    """CREATE TRIGGER reimbursement_billings_final_immutable BEFORE UPDATE ON reimbursement_billings
        WHEN OLD.status IN ('billed','canceled')
        BEGIN SELECT RAISE(ABORT, 'billed or canceled reimbursement billings are immutable'); END""",
    "CREATE TRIGGER reimbursement_billings_no_delete BEFORE DELETE ON reimbursement_billings BEGIN SELECT RAISE(ABORT, 'reimbursement billings are never deleted'); END",
]

# Payments through the core payment outbox.  ``reimbursements`` above is applied
# history (checksummed, append-only), so the change arrives as its own catalog
# entry: the payments table is rebuilt (SQLite cannot widen a CHECK constraint)
# with the in-flight lifecycle and a link to its payment intent; existing rows,
# including legacy booked payments posted straight to the bank, are copied as they are.
OUTBOX_SCHEMA_NAME = "reimbursements_outbox"
OUTBOX_SCHEMA_STATEMENTS = [
    "ALTER TABLE reimbursement_claims ADD COLUMN payments_returned INTEGER NOT NULL DEFAULT 0",
    """CREATE TABLE reimbursement_payments_outbox (
        id TEXT PRIMARY KEY,
        claim_id TEXT NOT NULL REFERENCES reimbursement_claims(id),
        amount TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','in_flight','booked','failed','returned','canceled')),
        version INTEGER NOT NULL DEFAULT 1,
        approval_id TEXT REFERENCES approvals(id),
        intent_id TEXT UNIQUE REFERENCES payment_intents(id),
        journal_id TEXT REFERENCES journals(id),
        period_id TEXT REFERENCES periods(id),
        created_at TEXT NOT NULL,
        released_at TEXT,
        booked_at TEXT,
        resolved_at TEXT,
        canceled_at TEXT
    )""",
    """INSERT INTO reimbursement_payments_outbox (id, claim_id, amount, status, version, approval_id, journal_id, period_id, created_at, booked_at, canceled_at)
        SELECT id, claim_id, amount, status, version, approval_id, journal_id, period_id, created_at, booked_at, canceled_at FROM reimbursement_payments""",
    "DROP TABLE reimbursement_payments",
    "ALTER TABLE reimbursement_payments_outbox RENAME TO reimbursement_payments",
    "CREATE INDEX reimbursement_payments_claim ON reimbursement_payments(claim_id)",
    """CREATE TRIGGER reimbursement_payments_start_as_draft BEFORE INSERT ON reimbursement_payments
        WHEN NEW.status != 'draft' OR NEW.intent_id IS NOT NULL OR NEW.journal_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'reimbursement payments start as drafts with no intent or journal'); END""",
    # A payment's status can only follow its own payment intent.
    """CREATE TRIGGER reimbursement_payments_follow_intent BEFORE UPDATE ON reimbursement_payments
        WHEN NEW.id IS NOT OLD.id OR NEW.claim_id IS NOT OLD.claim_id OR NEW.amount IS NOT OLD.amount OR NEW.created_at IS NOT OLD.created_at
          OR (OLD.intent_id IS NOT NULL AND NEW.intent_id IS NOT OLD.intent_id)
          OR NOT (
            (OLD.status = 'draft' AND NEW.status = 'canceled' AND NEW.intent_id IS NULL)
            OR (OLD.status = 'draft' AND NEW.status = 'in_flight' AND EXISTS (
                SELECT 1 FROM payment_intents i WHERE i.id = NEW.intent_id AND i.source_type = 'reimbursement_payment'
                AND i.source_id = NEW.id AND i.amount = NEW.amount AND i.payable_account = '2100'))
            OR (OLD.status = 'in_flight' AND NEW.status = 'booked' AND EXISTS (
                SELECT 1 FROM payment_intents i WHERE i.id = NEW.intent_id AND i.status IN ('accepted','settled','returned') AND i.journal_id IS NOT NULL))
            OR (OLD.status = 'in_flight' AND NEW.status = 'failed' AND EXISTS (
                SELECT 1 FROM payment_intents i WHERE i.id = NEW.intent_id AND i.status IN ('failed','canceled')))
            OR (OLD.status = 'booked' AND NEW.status = 'returned' AND EXISTS (
                SELECT 1 FROM payment_intents i WHERE i.id = NEW.intent_id AND i.status = 'returned'))
          )
        BEGIN SELECT RAISE(ABORT, 'reimbursement payments follow their payment intent: draft -> in_flight or canceled, in_flight -> booked or failed, booked -> returned'); END""",
    "CREATE TRIGGER reimbursement_payments_no_delete BEFORE DELETE ON reimbursement_payments BEGIN SELECT RAISE(ABORT, 'reimbursement payments are never deleted'); END",
    "DROP TRIGGER IF EXISTS reimbursement_claims_status_forward_only",
    # Forward only, except that each returned payment allows exactly one step back.
    """CREATE TRIGGER reimbursement_claims_status_lifecycle
        BEFORE UPDATE OF status ON reimbursement_claims
        WHEN NEW.status != OLD.status AND NOT (
            (OLD.status = 'submitted' AND NEW.status = 'approved')
            OR (OLD.status = 'approved' AND NEW.status IN ('partially_paid','paid','voided'))
            OR (OLD.status = 'partially_paid' AND NEW.status = 'paid')
            OR (OLD.status IN ('partially_paid','paid') AND NEW.status IN ('approved','partially_paid')
                AND NEW.payments_returned = OLD.payments_returned + 1)
        )
        BEGIN SELECT RAISE(ABORT, 'illegal reimbursement claim status transition'); END""",
    """CREATE TRIGGER reimbursement_claims_returns_follow_payments
        BEFORE UPDATE OF payments_returned ON reimbursement_claims
        WHEN NEW.payments_returned != OLD.payments_returned AND NOT (
            NEW.payments_returned = OLD.payments_returned + 1
            AND NEW.payments_returned = (SELECT COUNT(*) FROM reimbursement_payments p WHERE p.claim_id = NEW.id AND p.status = 'returned')
        )
        BEGIN SELECT RAISE(ABORT, 'a reimbursement claim return count only follows returned payments'); END""",
]

# Tighter guards on the outbox lifecycle, as their own entry so a workspace that
# already applied ``reimbursements_outbox`` upgrades in place:
# * a payment's journal and period can only be set when it is booked, and then
#   only to its intent's acceptance journal and that journal's period; its
#   approval is set once, on release, to the approval its intent was created under;
# * a claim's status follows its payments: it can only become (partially) paid
#   with a booked payment on it, only be voided with nothing booked or in flight,
#   and a return moves it back to ``approved`` only when no booked payment remains
#   (to ``partially_paid`` only when one does).
OUTBOX_GUARDS_SCHEMA_NAME = "reimbursements_outbox_guards"
OUTBOX_GUARDS_SCHEMA_STATEMENTS = [
    "DROP TRIGGER reimbursement_payments_follow_intent",
    """CREATE TRIGGER reimbursement_payments_follow_intent BEFORE UPDATE ON reimbursement_payments
        WHEN NEW.id IS NOT OLD.id OR NEW.claim_id IS NOT OLD.claim_id OR NEW.amount IS NOT OLD.amount OR NEW.created_at IS NOT OLD.created_at
          OR (OLD.intent_id IS NOT NULL AND NEW.intent_id IS NOT OLD.intent_id)
          OR (OLD.status != 'draft' AND NEW.approval_id IS NOT OLD.approval_id)
          OR (NOT (OLD.status = 'in_flight' AND NEW.status = 'booked')
              AND (NEW.journal_id IS NOT OLD.journal_id OR NEW.period_id IS NOT OLD.period_id))
          OR NOT (
            (OLD.status = 'draft' AND NEW.status = 'canceled' AND NEW.intent_id IS NULL AND NEW.approval_id IS OLD.approval_id)
            OR (OLD.status = 'draft' AND NEW.status = 'in_flight' AND EXISTS (
                SELECT 1 FROM payment_intents i WHERE i.id = NEW.intent_id AND i.source_type = 'reimbursement_payment'
                AND i.source_id = NEW.id AND i.amount = NEW.amount AND i.payable_account = '2100' AND i.approval_id = NEW.approval_id))
            OR (OLD.status = 'in_flight' AND NEW.status = 'booked' AND EXISTS (
                SELECT 1 FROM payment_intents i JOIN journals j ON j.id = i.journal_id
                WHERE i.id = NEW.intent_id AND i.status IN ('accepted','settled','returned')
                AND NEW.journal_id = i.journal_id AND NEW.period_id = j.period_id))
            OR (OLD.status = 'in_flight' AND NEW.status = 'failed' AND EXISTS (
                SELECT 1 FROM payment_intents i WHERE i.id = NEW.intent_id AND i.status IN ('failed','canceled')))
            OR (OLD.status = 'booked' AND NEW.status = 'returned' AND EXISTS (
                SELECT 1 FROM payment_intents i WHERE i.id = NEW.intent_id AND i.status = 'returned'))
          )
        BEGIN SELECT RAISE(ABORT, 'reimbursement payments follow their payment intent: draft -> in_flight or canceled, in_flight -> booked (on the acceptance journal) or failed, booked -> returned'); END""",
    "DROP TRIGGER reimbursement_claims_status_lifecycle",
    """CREATE TRIGGER reimbursement_claims_status_lifecycle
        BEFORE UPDATE OF status ON reimbursement_claims
        WHEN NEW.status != OLD.status AND NOT (
            (OLD.status = 'submitted' AND NEW.status = 'approved')
            OR (OLD.status = 'approved' AND NEW.status = 'voided' AND NOT EXISTS (
                SELECT 1 FROM reimbursement_payments p WHERE p.claim_id = NEW.id AND p.status IN ('in_flight','booked')))
            OR (OLD.status = 'approved' AND NEW.status IN ('partially_paid','paid') AND EXISTS (
                SELECT 1 FROM reimbursement_payments p WHERE p.claim_id = NEW.id AND p.status = 'booked'))
            OR (OLD.status = 'partially_paid' AND NEW.status = 'paid')
            OR (OLD.status IN ('partially_paid','paid') AND NEW.payments_returned = OLD.payments_returned + 1 AND (
                (NEW.status = 'approved' AND NOT EXISTS (
                    SELECT 1 FROM reimbursement_payments p WHERE p.claim_id = NEW.id AND p.status = 'booked'))
                OR (NEW.status = 'partially_paid' AND EXISTS (
                    SELECT 1 FROM reimbursement_payments p WHERE p.claim_id = NEW.id AND p.status = 'booked'))))
        )
        BEGIN SELECT RAISE(ABORT, 'illegal reimbursement claim status transition'); END""",
]

# Customer collections against posted billings, so the receivable a billing creates
# can be cleared and the AR subledger reconciles to 1100.  Each row cites its own
# posted journal; rows are immutable (a correction is a reversal, never an edit).
BILLING_AR_SCHEMA_NAME = "reimbursements_billing_collections"
BILLING_AR_SCHEMA_STATEMENTS = [
    """CREATE TABLE reimbursement_collections (
        id TEXT PRIMARY KEY,
        billing_id TEXT NOT NULL REFERENCES reimbursement_billings(id),
        amount TEXT NOT NULL,
        fee TEXT NOT NULL DEFAULT '0.00',
        provider_ref TEXT NOT NULL UNIQUE,
        journal_id TEXT NOT NULL REFERENCES journals(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        received_at TEXT NOT NULL,
        recorded_by TEXT NOT NULL
    )""",
    "CREATE INDEX reimbursement_collections_billing ON reimbursement_collections(billing_id)",
    """CREATE TRIGGER reimbursement_collections_cite_their_journal BEFORE INSERT ON reimbursement_collections
        WHEN NOT EXISTS (
            SELECT 1 FROM journals j WHERE j.id = NEW.journal_id AND j.source_type = 'reimbursement_collection'
            AND j.source_id = NEW.id AND j.period_id = NEW.period_id)
          OR NOT EXISTS (SELECT 1 FROM reimbursement_billings b WHERE b.id = NEW.billing_id AND b.status = 'billed')
        BEGIN SELECT RAISE(ABORT, 'a reimbursement collection must cite its own posted journal against a billed reimbursement billing'); END""",
    "CREATE TRIGGER reimbursement_collections_no_update BEFORE UPDATE ON reimbursement_collections BEGIN SELECT RAISE(ABORT, 'reimbursement collections are immutable'); END",
    "CREATE TRIGGER reimbursement_collections_no_delete BEFORE DELETE ON reimbursement_collections BEGIN SELECT RAISE(ABORT, 'reimbursement collections are immutable'); END",
]

# SQLite's REPLACE conflict resolution deletes the conflicting row without firing
# DELETE or UPDATE triggers (recursive_triggers is off), so ``INSERT OR REPLACE`` /
# ``REPLACE INTO`` could rewrite an "immutable" collection (reusing its own id and
# journal passes the cite-their-journal check), an approved claim, a booked payment
# or a posted billing.  BEFORE INSERT triggers fire before REPLACE deletes anything:
# refuse every insert that collides with a stored row on any unique key (which also
# covers OR IGNORE and upserts).  A payment's ``intent_id`` needs no check here:
# payments are inserted as drafts with no intent (``reimbursement_payments_start_as_draft``).
# A separate entry, because applied entries are append-only.
NO_REPLACE_SCHEMA_NAME = "reimbursements_no_replace"
NO_REPLACE_SCHEMA_STATEMENTS = [
    """CREATE TRIGGER reimbursement_claims_no_replace BEFORE INSERT ON reimbursement_claims
        WHEN EXISTS (SELECT 1 FROM reimbursement_claims r
                     WHERE r.id = NEW.id OR (r.receipt_hash = NEW.receipt_hash AND r.status != 'voided' AND NEW.status != 'voided'))
        BEGIN SELECT RAISE(ABORT, 'reimbursement claims are never replaced: a stored claim already has this id or live receipt'); END""",
    """CREATE TRIGGER reimbursement_payments_no_replace BEFORE INSERT ON reimbursement_payments
        WHEN EXISTS (SELECT 1 FROM reimbursement_payments p WHERE p.id = NEW.id)
        BEGIN SELECT RAISE(ABORT, 'reimbursement payments are never replaced: a stored payment already has this id'); END""",
    """CREATE TRIGGER reimbursement_billings_no_replace BEFORE INSERT ON reimbursement_billings
        WHEN EXISTS (SELECT 1 FROM reimbursement_billings b WHERE b.id = NEW.id)
        BEGIN SELECT RAISE(ABORT, 'reimbursement billings are never replaced: a stored billing already has this id'); END""",
    """CREATE TRIGGER reimbursement_collections_no_replace BEFORE INSERT ON reimbursement_collections
        WHEN EXISTS (SELECT 1 FROM reimbursement_collections k WHERE k.id = NEW.id OR k.provider_ref = NEW.provider_ref)
        BEGIN SELECT RAISE(ABORT, 'reimbursement collections are immutable: a stored collection already has this id or provider reference'); END""",
]

# A payment whose intent was canceled before dispatch goes back to ``draft`` (an open state)
# instead of the terminal ``failed``: the trigger below is ``reimbursements_outbox_guards``'
# lifecycle plus exactly one transition, in_flight -> draft, allowed only when the payment's
# own intent is canceled and never posted, and only while clearing the intent link and the
# approval (so the next release needs a fresh approval and a new intent).  A separate entry,
# because applied entries are append-only; it replaces the trigger by name.
REOPEN_SCHEMA_NAME = "reimbursements_cancel_reopens"
REOPEN_SCHEMA_STATEMENTS = [
    "DROP TRIGGER IF EXISTS reimbursement_payments_follow_intent",
    """CREATE TRIGGER reimbursement_payments_follow_intent BEFORE UPDATE ON reimbursement_payments
        WHEN NEW.id IS NOT OLD.id OR NEW.claim_id IS NOT OLD.claim_id OR NEW.amount IS NOT OLD.amount OR NEW.created_at IS NOT OLD.created_at
          OR (OLD.intent_id IS NOT NULL AND NEW.intent_id IS NOT OLD.intent_id
              AND NOT (OLD.status = 'in_flight' AND NEW.status = 'draft' AND NEW.intent_id IS NULL))
          OR (OLD.status != 'draft' AND NEW.approval_id IS NOT OLD.approval_id
              AND NOT (OLD.status = 'in_flight' AND NEW.status = 'draft' AND NEW.approval_id IS NULL))
          OR (NOT (OLD.status = 'in_flight' AND NEW.status = 'booked')
              AND (NEW.journal_id IS NOT OLD.journal_id OR NEW.period_id IS NOT OLD.period_id))
          OR NOT (
            (OLD.status = 'draft' AND NEW.status = 'canceled' AND NEW.intent_id IS NULL AND NEW.approval_id IS OLD.approval_id)
            OR (OLD.status = 'draft' AND NEW.status = 'in_flight' AND EXISTS (
                SELECT 1 FROM payment_intents i WHERE i.id = NEW.intent_id AND i.source_type = 'reimbursement_payment'
                AND i.source_id = NEW.id AND i.amount = NEW.amount AND i.payable_account = '2100' AND i.approval_id = NEW.approval_id))
            OR (OLD.status = 'in_flight' AND NEW.status = 'booked' AND EXISTS (
                SELECT 1 FROM payment_intents i JOIN journals j ON j.id = i.journal_id
                WHERE i.id = NEW.intent_id AND i.status IN ('accepted','settled','returned')
                AND NEW.journal_id = i.journal_id AND NEW.period_id = j.period_id))
            OR (OLD.status = 'in_flight' AND NEW.status = 'failed' AND EXISTS (
                SELECT 1 FROM payment_intents i WHERE i.id = NEW.intent_id AND i.status IN ('failed','canceled')))
            OR (OLD.status = 'in_flight' AND NEW.status = 'draft' AND NEW.intent_id IS NULL AND NEW.approval_id IS NULL
                AND NEW.journal_id IS NULL AND NEW.period_id IS NULL AND EXISTS (
                SELECT 1 FROM payment_intents i WHERE i.id = OLD.intent_id AND i.status = 'canceled' AND i.journal_id IS NULL
                AND i.source_type = 'reimbursement_payment' AND i.source_id = OLD.id))
            OR (OLD.status = 'booked' AND NEW.status = 'returned' AND EXISTS (
                SELECT 1 FROM payment_intents i WHERE i.id = NEW.intent_id AND i.status = 'returned'))
          )
        BEGIN SELECT RAISE(ABORT, 'reimbursement payments follow their payment intent: draft -> in_flight or canceled, in_flight -> booked (on the acceptance journal), failed or (intent canceled) draft, booked -> returned'); END""",
]

# Registered here, in this order, so each follow-on entry always sits after the
# objects it changes; the plugin loader's own registration of SCHEMA_NAME is then a no-op.
register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)
register_schema_version(OUTBOX_SCHEMA_NAME, OUTBOX_SCHEMA_STATEMENTS)
register_schema_version(OUTBOX_GUARDS_SCHEMA_NAME, OUTBOX_GUARDS_SCHEMA_STATEMENTS)
register_schema_version(BILLING_AR_SCHEMA_NAME, BILLING_AR_SCHEMA_STATEMENTS)
register_schema_version(NO_REPLACE_SCHEMA_NAME, NO_REPLACE_SCHEMA_STATEMENTS)
register_schema_version(REOPEN_SCHEMA_NAME, REOPEN_SCHEMA_STATEMENTS)

AR_ACCOUNT = "1100"
BANK_ACCOUNT = "1000"
FEE_ACCOUNT = "6000"
COLLECTION_SOURCE = "reimbursement_collection"


class ReimbursementError(RuntimeError):
    """Invalid reimbursement input or an action the claim's state does not allow."""


def _positive_amount(value, label: str = "amount") -> Decimal:
    try:
        amt = money(value)
    except MoneyError as exc:
        raise ReimbursementError(f"{label} is not exact money: {exc}") from exc
    if amt <= 0:
        raise ReimbursementError(f"{label} must be positive, got {fmt(amt)}")
    return amt


def _non_empty(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReimbursementError(f"{label} is required and must be a non-empty string")
    return value.strip()


def _claim_content_hash(row: dict[str, Any]) -> str:
    return hash_json({
        "project_id": row["project_id"],
        "employee_id": row["employee_id"],
        "description": row["description"],
        "amount": fmt(row["amount"]),
        "receipt_hash": row["receipt_hash"],
        "billable": bool(row["billable"]),
    })


def _payment_status_for_intent(intent_status: str) -> str:
    """The reimbursement payment status an intent status implies.  A canceled intent
    (withdrawn before dispatch) returns the payment to an open draft."""
    if intent_status in ("accepted", "settled"):
        return "booked"
    if intent_status == "returned":
        return "returned"
    if intent_status == "failed":
        return "failed"
    if intent_status == "canceled":
        return "draft"
    return "in_flight"  # approved, queued, submitted, outcome_unknown


_PAYMENT_SELECT = "SELECT p.*, i.status AS intent_status FROM reimbursement_payments p LEFT JOIN payment_intents i ON i.id = p.intent_id"


class Plugin:
    def __init__(self, cipher):
        self.c = cipher
        self.db = cipher.db
        self.audit = cipher.audit
        self.ledger = cipher.ledger
        self.approvals = cipher.approvals
        # the core payment path tells us, inside its own transaction, when one of our intents moves
        cipher.payments.subscribe(PAYMENT_SUBJECT, self._on_intent_change)
        # restore recovery: a provider transfer for one of our payments that this copy never
        # recorded is adopted through the core payment.adopt_transfer approval
        register = getattr(cipher.payments, "register_adoption", None)
        if register is not None:
            register(PAYMENT_SUBJECT, plan=self._adoption_plan, link=self._link_adopted_intent, label="reimbursement payment")

    # ---- claims ----------------------------------------------------------- #

    def submit_claim(self, *, project_id: str, employee_id: str, description: str, amount, receipt_hash: str, billable: bool = False, actor: str) -> dict[str, Any]:
        # shape validation is stateless and can run before the lock is taken
        description = _non_empty(description, "description")
        amt = _positive_amount(amount)
        receipt = _non_empty(receipt_hash, "receipt_hash")
        if not isinstance(billable, bool):
            raise ReimbursementError("billable must be True or False")
        claim_id = new_id("rclm")
        content = {"project_id": project_id, "employee_id": employee_id, "description": description, "amount": fmt(amt), "receipt_hash": receipt, "billable": billable}
        content_hash = _claim_content_hash(content)
        with self.db.transaction() as conn:
            # state-dependent checks run under the write lock so nothing can change
            # between the check and the insert
            if self.db.one("SELECT id FROM projects WHERE id=?", (project_id,)) is None:
                raise ReimbursementError(f"unknown project {project_id}")
            employee = self.db.one("SELECT id, kind FROM parties WHERE id=?", (employee_id,))
            if employee is None:
                raise ReimbursementError(f"unknown party {employee_id}")
            if employee["kind"] != "employee":
                raise ReimbursementError(f"only employee parties can claim reimbursement; {employee_id} is a {employee['kind']}")
            if self._live_claim_for_receipt(receipt) is not None:
                raise ReimbursementError(f"a claim already exists for receipt {receipt}")
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO reimbursement_claims (id, project_id, employee_id, description, amount, receipt_hash, billable, status, version, content_hash, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,'submitted',1,?,?,?)""",
                (claim_id, project_id, employee_id, description, fmt(amt), receipt, 1 if billable else 0, content_hash, now, now),
            )
            self.audit.record(actor, "reimbursement.claim_submitted", CLAIM_SUBJECT, claim_id, {**content, "content_hash": content_hash})
        return self.claim(claim_id)

    def update_claim(self, claim_id: str, *, actor: str, amount=None, description: str | None = None, billable: bool | None = None, receipt_hash: str | None = None) -> dict[str, Any]:
        """Edit a submitted claim.  Bumps the version and invalidates every open
        approval bound to the previous version."""
        if amount is None and description is None and billable is None and receipt_hash is None:
            raise ReimbursementError("nothing to update")
        with self.db.transaction() as conn:
            row = self._claim_row(claim_id)
            if row["status"] != "submitted":
                raise ReimbursementError(f"claim {claim_id} is {row['status']}; only submitted claims can be edited")
            changes: dict[str, Any] = {}
            if amount is not None:
                changes["amount"] = fmt(_positive_amount(amount))
            if description is not None:
                changes["description"] = _non_empty(description, "description")
            if billable is not None:
                if not isinstance(billable, bool):
                    raise ReimbursementError("billable must be True or False")
                changes["billable"] = billable
            if receipt_hash is not None:
                receipt = _non_empty(receipt_hash, "receipt_hash")
                if self._live_claim_for_receipt(receipt, exclude=claim_id) is not None:
                    raise ReimbursementError(f"a claim already exists for receipt {receipt}")
                changes["receipt_hash"] = receipt
            merged = {**row, **changes}
            new_version = row["version"] + 1
            content_hash = _claim_content_hash(merged)
            conn.execute(
                "UPDATE reimbursement_claims SET amount=?, description=?, billable=?, receipt_hash=?, version=?, content_hash=?, updated_at=? WHERE id=?",
                (fmt(merged["amount"]), merged["description"], 1 if merged["billable"] else 0, merged["receipt_hash"], new_version, content_hash, utcnow_iso(), claim_id),
            )
            invalidated = self.approvals.invalidate_for_subject(CLAIM_SUBJECT, claim_id, reason=f"claim edited to version {new_version} after approval was requested", actor=actor)
            self.audit.record(actor, "reimbursement.claim_updated", CLAIM_SUBJECT, claim_id, {"changes": changes, "version": new_version, "content_hash": content_hash, "approvals_invalidated": invalidated})
        return self.claim(claim_id)

    def _claim_row(self, claim_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM reimbursement_claims WHERE id=?", (claim_id,))
        if row is None:
            raise ReimbursementError(f"unknown reimbursement claim {claim_id}")
        return row

    def _live_claim_for_receipt(self, receipt: str, *, exclude: str | None = None) -> dict[str, Any] | None:
        """The non-voided claim holding this receipt, if any."""
        if exclude is None:
            return self.db.one("SELECT id FROM reimbursement_claims WHERE receipt_hash=? AND status != 'voided'", (receipt,))
        return self.db.one("SELECT id FROM reimbursement_claims WHERE receipt_hash=? AND status != 'voided' AND id != ?", (receipt, exclude))

    def _payment_total(self, claim_id: str, status: str) -> Decimal:
        rows = self.db.query("SELECT amount FROM reimbursement_payments WHERE claim_id=? AND status=?", (claim_id, status))
        return total(r["amount"] for r in rows)

    def _booked_total(self, claim_id: str) -> Decimal:
        return self._payment_total(claim_id, "booked")

    def _in_flight_total(self, claim_id: str) -> Decimal:
        return self._payment_total(claim_id, "in_flight")

    def _draft_payment_total(self, claim_id: str) -> Decimal:
        return self._payment_total(claim_id, "draft")

    def _billed_total(self, claim_id: str, *, include_drafts: bool) -> Decimal:
        statuses = "('draft','billed')" if include_drafts else "('billed')"
        rows = self.db.query(f"SELECT amount FROM reimbursement_billings WHERE claim_id=? AND status IN {statuses}", (claim_id,))
        return total(r["amount"] for r in rows)

    def _payable_row(self, row: dict[str, Any]) -> Decimal:
        """Approved amount less booked payments: the claim's share of the 2100 control balance."""
        if row["status"] not in APPROVED_STATES:
            return ZERO
        return money(money(row["amount"]) - self._booked_total(row["id"]))

    def _outstanding_row(self, row: dict[str, Any]) -> Decimal:
        """Payable less payments in flight: what may still be paid."""
        if row["status"] not in APPROVED_STATES:
            return ZERO
        return money(self._payable_row(row) - self._in_flight_total(row["id"]))

    def outstanding(self, claim_id: str) -> Decimal:
        """Approved amount less booked and in-flight payments.  A claim that is not
        approved (or was voided) owes nothing."""
        return self._outstanding_row(self._claim_row(claim_id))

    def claim(self, claim_id: str) -> dict[str, Any]:
        row = self._claim_row(claim_id)
        row["billable"] = bool(row["billable"])
        row["payable"] = fmt(self._payable_row(row))
        row["in_flight"] = fmt(self._in_flight_total(claim_id))
        row["outstanding"] = fmt(self._outstanding_row(row))
        row["paid"] = fmt(self._booked_total(claim_id))
        row["billed"] = fmt(self._billed_total(claim_id, include_drafts=False))
        row["payments"] = self.db.query(f"{_PAYMENT_SELECT} WHERE p.claim_id=? ORDER BY p.created_at, p.id", (claim_id,))
        row["billings"] = self.db.query("SELECT * FROM reimbursement_billings WHERE claim_id=? ORDER BY created_at, id", (claim_id,))
        return row

    def claims(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT id FROM reimbursement_claims WHERE project_id=? ORDER BY created_at, id", (project_id,))
        return [self.claim(r["id"]) for r in rows]

    # ---- payments ----------------------------------------------------------- #

    def record_payment(self, claim_id: str, amount, *, actor: str) -> dict[str, Any]:
        """Draft a payment against an approved claim.  It may be partial but, together
        with payments in flight and other unreleased drafts, may not exceed the payable."""
        amt = _positive_amount(amount, "payment amount")
        with self.db.transaction() as conn:
            row = self._claim_row(claim_id)
            if row["status"] not in PAYABLE_STATES:
                raise ReimbursementError(f"claim {claim_id} is {row['status']}; only approved claims with an outstanding balance can be paid")
            outstanding = self._outstanding_row(row)
            in_flight = self._in_flight_total(claim_id)
            reserved = self._draft_payment_total(claim_id)
            available = money(outstanding - reserved)
            if amt > available:
                raise ReimbursementError(
                    f"payment {fmt(amt)} exceeds the outstanding balance {fmt(outstanding)} on claim {claim_id}"
                    + (f" ({fmt(in_flight)} is already in flight)" if in_flight > 0 else "")
                    + (f" less {fmt(reserved)} already in draft payments" if reserved > 0 else "")
                )
            payment_id = new_id("rpay")
            conn.execute(
                "INSERT INTO reimbursement_payments (id, claim_id, amount, status, version, created_at) VALUES (?,?,?,'draft',1,?)",
                (payment_id, claim_id, fmt(amt), utcnow_iso()),
            )
            self.audit.record(actor, "reimbursement.payment_recorded", PAYMENT_SUBJECT, payment_id, {"claim_id": claim_id, "amount": fmt(amt), "outstanding_before": fmt(outstanding), "in_flight": fmt(in_flight)})
        return self.payment(payment_id)

    def cancel_payment(self, payment_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        with self.db.transaction():
            p = self.payment(payment_id)
            if p["status"] != "draft":
                raise ReimbursementError(f"payment {payment_id} is {p['status']}; only draft payments can be canceled")
            self._cancel_draft_payment(p, actor=actor, reason=reason)
        return self.payment(payment_id)

    def _cancel_draft_payment(self, p: dict[str, Any], *, actor: str, reason: str) -> None:
        """Caller holds the transaction and has checked that ``p`` is a draft."""
        self.db.execute("UPDATE reimbursement_payments SET status='canceled', version=version+1, canceled_at=? WHERE id=?", (utcnow_iso(), p["id"]))
        invalidated = self.approvals.invalidate_for_subject(PAYMENT_SUBJECT, p["id"], reason=f"payment canceled: {reason}", actor=actor)
        self.audit.record(actor, "reimbursement.payment_canceled", PAYMENT_SUBJECT, p["id"], {"claim_id": p["claim_id"], "amount": p["amount"], "reason": reason, "approvals_invalidated": invalidated})

    def payment(self, payment_id: str) -> dict[str, Any]:
        """The payment row plus ``intent_status`` (None until it is released)."""
        row = self.db.one(f"{_PAYMENT_SELECT} WHERE p.id=?", (payment_id,))
        if row is None:
            raise ReimbursementError(f"unknown reimbursement payment {payment_id}")
        return row

    def payments(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            f"{_PAYMENT_SELECT} JOIN reimbursement_claims c ON c.id=p.claim_id WHERE c.project_id=? ORDER BY p.created_at, p.id",
            (project_id,),
        )

    # ---- payments: following the payment intent --------------------------------- #

    def _on_intent_change(self, intent: dict[str, Any], *, actor: str) -> None:
        """Called by the core payment module inside the transaction that changed ``intent``."""
        p = self.db.one(f"{_PAYMENT_SELECT} WHERE p.intent_id=?", (intent["id"],))
        if p is None:
            return  # the intent is being created; the payment row links to it in the same transaction
        self._follow_intent(p, intent, actor=actor)

    def _follow_intent(self, p: dict[str, Any], intent: dict[str, Any], *, actor: str) -> list[str]:
        """Move the payment (and its claim) to the state its intent implies.  Idempotent."""
        target = _payment_status_for_intent(intent["status"])
        moved: list[str] = []
        with self.db.transaction():
            if p["status"] == "in_flight" and target in ("booked", "returned"):
                self._book_payment(p, intent, actor=actor)
                moved.append("booked")
                p = self.payment(p["id"])
            if p["status"] == "in_flight" and target == "failed":
                self._fail_payment(p, intent, actor=actor)
                moved.append("failed")
            elif p["status"] == "in_flight" and target == "draft":
                self._reopen_payment(p, intent, actor=actor)
                moved.append("draft")
            elif p["status"] == "booked" and target == "returned" and p["intent_id"]:
                self._return_payment(p, intent, actor=actor)
                moved.append("returned")
        return moved

    def _book_payment(self, p: dict[str, Any], intent: dict[str, Any], *, actor: str) -> None:
        row = self._claim_row(p["claim_id"])
        journal = self.ledger.journal(intent["journal_id"])
        now = utcnow_iso()
        self.db.execute(
            "UPDATE reimbursement_payments SET status='booked', journal_id=?, period_id=?, booked_at=?, version=version+1 WHERE id=?",
            (journal["id"], journal["period_id"], now, p["id"]),
        )
        payable = money(money(row["amount"]) - self._booked_total(row["id"]))
        if payable < 0:
            raise ReimbursementError(f"booking payment {p['id']} would overpay claim {row['id']} by {fmt(-payable)}")
        claim_status = "paid" if payable == ZERO else "partially_paid"
        if claim_status != row["status"]:
            self.db.execute("UPDATE reimbursement_claims SET status=?, updated_at=? WHERE id=?", (claim_status, now, row["id"]))
        self.approvals.invalidate_for_subject(PAYMENT_SUBJECT, p["id"], reason="payment already booked", actor=actor)
        self.audit.record(actor, "reimbursement.payment_booked", PAYMENT_SUBJECT, p["id"], {
            "claim_id": row["id"], "intent_id": intent["id"], "provider_ref": intent["provider_ref"], "journal_id": journal["id"],
            "amount": p["amount"], "payable_after": fmt(payable), "claim_status": claim_status, "period_id": journal["period_id"],
        })

    def _fail_payment(self, p: dict[str, Any], intent: dict[str, Any], *, actor: str) -> None:
        """The intent failed (refused at dispatch, by the provider or by reconciliation): the
        in-flight reservation is released and the claim's outstanding balance is open again.
        The failed payment itself is finished; the balance is paid through a new payment."""
        self.db.execute("UPDATE reimbursement_payments SET status='failed', resolved_at=?, version=version+1 WHERE id=?", (utcnow_iso(), p["id"]))
        row = self._claim_row(p["claim_id"])
        self.audit.record(actor, "reimbursement.payment_failed", PAYMENT_SUBJECT, p["id"], {
            "claim_id": row["id"], "intent_id": intent["id"], "intent_status": intent["status"], "amount": p["amount"], "reason": intent["note"],
            "outstanding_after": fmt(self._outstanding_row(row)),
        })

    def _reopen_payment(self, p: dict[str, Any], intent: dict[str, Any], *, actor: str) -> None:
        """The intent was canceled before dispatch: the payment is an open draft again (its
        intent link and approval are cleared, the version bumps), so the same payment can be
        approved and released again; the claim's outstanding balance is open again."""
        self.db.execute(
            "UPDATE reimbursement_payments SET status='draft', intent_id=NULL, approval_id=NULL, released_at=NULL, version=version+1 WHERE id=?",
            (p["id"],),
        )
        row = self._claim_row(p["claim_id"])
        self.audit.record(actor, "reimbursement.payment_reopened", PAYMENT_SUBJECT, p["id"], {
            "claim_id": row["id"], "canceled_intent_id": intent["id"], "released_under_approval": p["approval_id"], "amount": p["amount"],
            "reason": intent["note"], "outstanding_after": fmt(self._outstanding_row(row)),
        })

    def _return_payment(self, p: dict[str, Any], intent: dict[str, Any], *, actor: str) -> None:
        now = utcnow_iso()
        self.db.execute("UPDATE reimbursement_payments SET status='returned', resolved_at=?, version=version+1 WHERE id=?", (now, p["id"]))
        row = self._claim_row(p["claim_id"])
        booked = self._booked_total(row["id"])
        claim_status = "approved" if booked == ZERO else "partially_paid"
        self.db.execute(
            "UPDATE reimbursement_claims SET status=?, payments_returned=payments_returned+1, updated_at=? WHERE id=?",
            (claim_status, now, row["id"]),
        )
        self.audit.record(actor, "reimbursement.payment_returned", PAYMENT_SUBJECT, p["id"], {
            "claim_id": row["id"], "intent_id": intent["id"], "amount": p["amount"], "claim_status": claim_status,
            "payable_after": fmt(money(money(row["amount"]) - booked)),
        })

    def _out_of_sync(self) -> list[dict[str, Any]]:
        rows = self.db.query(f"{_PAYMENT_SELECT} WHERE p.intent_id IS NOT NULL AND p.status IN ('in_flight','booked')")
        return [r for r in rows if _payment_status_for_intent(r["intent_status"]) != r["status"]]

    def sync_payments(self, *, actor: str) -> dict[str, Any]:
        """Repair path: re-derive every released payment from its intent.  The
        intent notifications normally keep them in step, so this finds nothing
        unless intents moved while this module was not loaded."""
        moved = []
        with self.db.transaction():
            for p in self._out_of_sync():
                intent = self.db.one("SELECT * FROM payment_intents WHERE id=?", (p["intent_id"],))
                changes = self._follow_intent(p, intent, actor=actor)
                if changes:
                    moved.append({"payment": p["id"], "intent": intent["id"], "intent_status": intent["status"], "moved": changes})
        return {"moved": moved}

    # ---- payments: restore recovery (payment.adopt_transfer) ------------------------ #

    def _adoption_plan(self, payment_id: str, *, amount, party_id: str | None, superseded: list[str], transfer_status: str) -> dict[str, Any]:
        """Can a provider transfer this copy never recorded be booked as payment ``payment_id``?
        The payment must be a draft, or in flight on a queued intent the adoption supersedes
        (that intent is canceled first, which reopens the payment); the amounts must match
        and the claim must still owe at least the transfer."""
        try:
            p = self.payment(payment_id)
        except ReimbursementError:
            raise ReimbursementError(f"reimbursement payment {payment_id} does not exist in this copy; draft it again and name it: "
                                     f"'<provider_ref>={PAYMENT_SUBJECT}:<payment id>'") from None
        reopening = p["status"] == "in_flight" and p["intent_id"] in superseded
        if p["status"] != "draft" and not reopening:
            raise ReimbursementError(f"reimbursement payment {payment_id} is {p['status']} in this copy; only a draft (or one in flight on a queued intent "
                                     "the provider never saw) can take an adopted transfer")
        if money(p["amount"]) != money(amount):
            raise ReimbursementError(f"the transfer is for {fmt(amount)} but reimbursement payment {payment_id} is for {p['amount']}")
        row = self._claim_row(p["claim_id"])
        if row["status"] not in PAYABLE_STATES:
            raise ReimbursementError(f"claim {row['id']} is {row['status']} in this copy; nothing is payable on it")
        if party_id is not None and party_id != row["employee_id"]:
            raise ReimbursementError(f"the transfer paid party {party_id}, but claim {row['id']} is owed to {row['employee_id']}")
        outstanding = self._outstanding_row(row) + (money(p["amount"]) if reopening else ZERO)
        if money(amount) > outstanding:
            raise ReimbursementError(f"the transfer {fmt(amount)} exceeds what claim {row['id']} still owes in this copy ({fmt(outstanding)})")
        return {
            "project_id": row["project_id"], "party_id": row["employee_id"], "payable_account": EMPLOYEE_PAYABLE,
            "binding": {"payment_version": p["version"], "payment_status": p["status"], "claim_id": row["id"], "claim_version": row["version"],
                        "claim_hash": row["content_hash"], "claim_outstanding": fmt(outstanding)},
        }

    def _link_adopted_intent(self, intent: dict[str, Any], *, approval_id: str, actor: str) -> None:
        """Called inside the adoption transaction: link the adopted intent the way a release
        would (draft -> in_flight); the core then books its acceptance, which books the payment."""
        p = self.payment(intent["source_id"])
        if p["status"] != "draft":
            raise ReimbursementError(f"reimbursement payment {p['id']} is {p['status']}; only a draft can take an adopted transfer")
        if money(p["amount"]) != money(intent["amount"]):
            raise ReimbursementError(f"the adopted transfer is for {intent['amount']} but reimbursement payment {p['id']} is for {p['amount']}")
        self.db.execute(
            "UPDATE reimbursement_payments SET status='in_flight', intent_id=?, approval_id=?, released_at=?, version=version+1 WHERE id=?",
            (intent["id"], approval_id, utcnow_iso(), p["id"]),
        )
        self.approvals.invalidate_for_subject(PAYMENT_SUBJECT, p["id"], reason="payment matched to a provider transfer adopted in recovery", actor=actor)
        self.approvals.invalidate_for_subject(CLAIM_SUBJECT, p["claim_id"], reason=f"payment {p['id']} matched to an adopted provider transfer", actor=actor)
        self.audit.record(actor, "reimbursement.payment_adopted", PAYMENT_SUBJECT, p["id"], {
            "claim_id": p["claim_id"], "intent_id": intent["id"], "approval_id": approval_id, "amount": p["amount"], "logical_op_id": intent["logical_op_id"],
        })

    # ---- billings ------------------------------------------------------------ #

    def create_billing(self, claim_id: str, amount, *, actor: str) -> dict[str, Any]:
        """Draft a customer billing for a billable, approved claim.  Billings
        (drafted or billed) may not exceed the claim amount in total."""
        amt = _positive_amount(amount, "billing amount")
        with self.db.transaction() as conn:
            row = self._claim_row(claim_id)
            if not row["billable"]:
                raise ReimbursementError(f"claim {claim_id} is not billable to the customer")
            if row["status"] not in APPROVED_STATES:
                raise ReimbursementError(f"claim {claim_id} is {row['status']}; only approved claims can be billed")
            project = self.db.one("SELECT customer_id FROM projects WHERE id=?", (row["project_id"],))
            if project is None or not project["customer_id"]:
                raise ReimbursementError("project has no customer party to bill")
            already = self._billed_total(claim_id, include_drafts=True)
            remaining = money(money(row["amount"]) - already)
            if amt > remaining:
                raise ReimbursementError(f"billing {fmt(amt)} exceeds the unbilled claim amount {fmt(remaining)} (claim {row['amount']}, billed or drafted {fmt(already)})")
            billing_id = new_id("rbil")
            conn.execute(
                "INSERT INTO reimbursement_billings (id, claim_id, customer_id, amount, status, version, created_at) VALUES (?,?,?,?,'draft',1,?)",
                (billing_id, claim_id, project["customer_id"], fmt(amt), utcnow_iso()),
            )
            self.audit.record(actor, "reimbursement.billing_created", BILLING_SUBJECT, billing_id, {"claim_id": claim_id, "customer_id": project["customer_id"], "amount": fmt(amt)})
        return self.billing(billing_id)

    def cancel_billing(self, billing_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        with self.db.transaction():
            b = self.billing(billing_id)
            if b["status"] != "draft":
                raise ReimbursementError(f"billing {billing_id} is {b['status']}; only draft billings can be canceled")
            self._cancel_draft_billing(b, actor=actor, reason=reason)
        return self.billing(billing_id)

    def _cancel_draft_billing(self, b: dict[str, Any], *, actor: str, reason: str) -> None:
        """Caller holds the transaction and has checked that ``b`` is a draft."""
        self.db.execute("UPDATE reimbursement_billings SET status='canceled', version=version+1, canceled_at=? WHERE id=?", (utcnow_iso(), b["id"]))
        invalidated = self.approvals.invalidate_for_subject(BILLING_SUBJECT, b["id"], reason=f"billing canceled: {reason}", actor=actor)
        self.audit.record(actor, "reimbursement.billing_canceled", BILLING_SUBJECT, b["id"], {"claim_id": b["claim_id"], "amount": b["amount"], "reason": reason, "approvals_invalidated": invalidated})

    def billing(self, billing_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM reimbursement_billings WHERE id=?", (billing_id,))
        if row is None:
            raise ReimbursementError(f"unknown reimbursement billing {billing_id}")
        return row

    def billings(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT b.* FROM reimbursement_billings b JOIN reimbursement_claims c ON c.id=b.claim_id WHERE c.project_id=? ORDER BY b.created_at, b.id",
            (project_id,),
        )

    # ---- billings: customer collections ------------------------------------------ #

    def _billing_balance(self, b: dict[str, Any]) -> dict[str, Decimal]:
        """Billed, collected and reversed amounts of a posted billing, and what stays open.

        A collection clears the receivable only while its own journal stands: a reversal
        of the collection journal (for example a customer receipt returned unpaid, through
        ``journal.reverse``) puts its amount back on 1100, so it counts as ``returned`` and
        the billing is open (and collectable) for it again.  A reversal of the billing
        journal clears the whole billing."""
        billed = money(b["amount"]) if b["status"] == "billed" else ZERO
        rows = self.db.query(
            """SELECT k.amount, EXISTS (SELECT 1 FROM journals r WHERE r.reversal_of = k.journal_id) AS reversed
               FROM reimbursement_collections k WHERE k.billing_id=?""",
            (b["id"],),
        )
        collected = total(r["amount"] for r in rows if not r["reversed"])
        returned = total(r["amount"] for r in rows if r["reversed"])
        reversed_ = bool(b.get("journal_id")) and self.db.one("SELECT id FROM journals WHERE reversal_of=?", (b["journal_id"],)) is not None
        cleared_by_reversal = billed if reversed_ else ZERO
        return {"billed": billed, "collected": collected, "returned": returned, "reversed": cleared_by_reversal,
                "open": money(billed - collected - cleared_by_reversal)}

    def record_billing_collection(self, billing_id: str, amount, *, period_id: str, provider_ref: str, fee="0", actor: str) -> dict[str, Any]:
        """Record the customer's payment of a posted billing: Dr 1000 (net of the fee) /
        Dr 6000 fee / Cr 1100.  Partial collections are allowed; collecting more than
        is open, collecting a reversed billing, reusing a provider reference or posting
        into a period that is not open are refused."""
        amt = _positive_amount(amount, "collection amount")
        try:
            f = money(fee)
        except MoneyError as exc:
            raise ReimbursementError(f"fee is not exact money: {exc}") from exc
        if f < 0 or f > amt:
            raise ReimbursementError(f"fee {fmt(f)} must be between 0.00 and the collected amount {fmt(amt)}")
        ref = _non_empty(provider_ref, "provider_ref")
        with self.db.transaction() as conn:
            b = self.billing(billing_id)
            if b["status"] != "billed":
                raise ReimbursementError(f"billing {billing_id} is {b['status']}; only posted billings can be collected")
            if self.db.one("SELECT id FROM reimbursement_collections WHERE provider_ref=?", (ref,)) is not None:
                raise ReimbursementError(f"collection {ref} was already recorded")
            bal = self._billing_balance(b)
            if bal["reversed"] > 0:
                raise ReimbursementError(f"billing {billing_id} was reversed; nothing is receivable on it")
            if amt > bal["open"]:
                raise ReimbursementError(f"collection {fmt(amt)} exceeds the open receivable {fmt(bal['open'])} on billing {billing_id}")
            self.ledger.require_open(period_id)
            row = self._claim_row(b["claim_id"])
            collection_id = new_id("rcol")
            scope = {"project_id": row["project_id"], "party_id": b["customer_id"]}
            lines = []
            if amt - f > 0:
                lines.append({"account": BANK_ACCOUNT, "debit": amt - f, **scope, "memo": f"customer receipt {ref} (simulated)"})
            if f > 0:
                lines.append({"account": FEE_ACCOUNT, "debit": f, **scope, "memo": "processing fee"})
            lines.append({"account": AR_ACCOUNT, "credit": amt, **scope, "memo": f"reimbursement billing {billing_id} collected"})
            j = self.ledger.post(
                period_id=period_id, description=f"Collection on reimbursement billing {billing_id}", lines=lines,
                source_type=COLLECTION_SOURCE, source_id=collection_id, source_version="1", posted_by=actor,
            )
            conn.execute(
                "INSERT INTO reimbursement_collections (id, billing_id, amount, fee, provider_ref, journal_id, period_id, received_at, recorded_by) VALUES (?,?,?,?,?,?,?,?,?)",
                (collection_id, billing_id, fmt(amt), fmt(f), ref, j["id"], period_id, utcnow_iso(), actor),
            )
            self.audit.record(actor, "reimbursement.billing_collected", BILLING_SUBJECT, billing_id, {
                "collection_id": collection_id, "provider_ref": ref, "amount": fmt(amt), "fee": fmt(f), "journal_id": j["id"],
                "period_id": period_id, "open_after": fmt(bal["open"] - amt),
            })
        return self.collection(collection_id)

    def collection(self, collection_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM reimbursement_collections WHERE id=?", (collection_id,))
        if row is None:
            raise ReimbursementError(f"unknown reimbursement collection {collection_id}")
        return row

    def collections(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            """SELECT k.* FROM reimbursement_collections k JOIN reimbursement_billings b ON b.id=k.billing_id
               JOIN reimbursement_claims c ON c.id=b.claim_id WHERE c.project_id=? ORDER BY k.received_at, k.id""",
            (project_id,),
        )

    def ar_open_items(self, project_id: str | None = None) -> dict[str, Any]:
        """Receivables created by reimbursement billings (which debit 1100): billed less
        collected, and nothing open once the billing journal is reversed.  The receivables
        domain adds ``items``/``subledger_total`` to its AR subledger; ``ledger_postings``
        is this source's own share of 1100 (billings, their reversals and collections), and
        ``reconciled_to_postings`` says the items explain it exactly."""
        sql = ("SELECT b.*, c.project_id FROM reimbursement_billings b JOIN reimbursement_claims c ON c.id=b.claim_id "
               "WHERE b.status='billed'")
        params: tuple = ()
        if project_id:
            sql += " AND c.project_id=?"
            params = (project_id,)
        items = []
        open_total = ZERO
        for b in self.db.query(sql + " ORDER BY b.billed_at, b.id", params):
            bal = self._billing_balance(b)
            items.append({
                "kind": BILLING_SUBJECT, "billing_id": b["id"], "claim_id": b["claim_id"], "project_id": b["project_id"], "customer_id": b["customer_id"],
                "amount_due": fmt(bal["billed"]), "received": fmt(bal["collected"]), "returned": fmt(bal["returned"]),
                "reversed": fmt(bal["reversed"]), "open": fmt(bal["open"]),
            })
            open_total += bal["open"]
        postings_sql = ("SELECT l.debit, l.credit FROM journal_lines l JOIN journals j ON j.id=l.journal_id "
                        "WHERE l.account_code=? AND j.source_type IN (?, ?)")
        postings_params: list[Any] = [AR_ACCOUNT, BILLING_SUBJECT, COLLECTION_SOURCE]
        if project_id:
            postings_sql += " AND l.project_id=?"
            postings_params.append(project_id)
        postings = ZERO
        for ln in self.db.query(postings_sql, tuple(postings_params)):
            postings += money(ln["debit"]) - money(ln["credit"])
        subledger = money(open_total)
        return {
            "source": "reimbursement_billings",
            "items": items, "subledger_total": fmt(subledger), "ledger_postings": fmt(postings), "reconciled_to_postings": subledger == money(postings),
            "cleared_by": ("collections recorded with record_billing_collection whose journal has not been reversed (a reversed collection "
                           "puts its amount back on the receivable); a reversal of the billing journal clears the whole billing"),
        }

    # ---- approvals: manifests ------------------------------------------------ #

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation == OP_APPROVE:
            return self._approve_manifest(subject_id, actor_role=actor_role)
        if operation == OP_PAY:
            return self._pay_manifest(subject_id, actor_role=actor_role)
        if operation == OP_BILL:
            return self._bill_manifest(subject_id, actor_role=actor_role)
        if operation == OP_VOID:
            return self._void_manifest(subject_id, actor_role=actor_role)
        raise ReimbursementError(f"unknown reimbursement operation {operation}")

    def _approve_manifest(self, claim_id: str, *, actor_role: str) -> dict[str, Any]:
        row = self._claim_row(claim_id)
        if row["status"] != "submitted":
            raise ReimbursementError(f"claim {claim_id} is {row['status']}, not submitted")
        return build_manifest(
            operation=OP_APPROVE,
            subject_type=CLAIM_SUBJECT,
            subject_id=claim_id,
            actor_role=actor_role,
            amounts={"amount": row["amount"]},
            bindings={
                "claim_version": row["version"],
                "claim_hash": row["content_hash"],
                "project_id": row["project_id"],
                "employee_id": row["employee_id"],
                "receipt_hash": row["receipt_hash"],
                "billable": bool(row["billable"]),
                "posting_rule": POSTING_RULE,
            },
        )

    def _verified_employee(self, employee_id: str) -> dict[str, Any]:
        """The payee, which must hold an independently verified destination."""
        employee = self.db.one("SELECT * FROM parties WHERE id=?", (employee_id,))
        if employee is None:
            raise ReimbursementError(f"unknown party {employee_id}")
        if not employee["destination"]:
            raise ReimbursementError(f"employee {employee_id} has no payment destination on file; record one and verify it independently before paying")
        if not employee["destination_verified"]:
            raise ReimbursementError(f"employee {employee_id} payment destination has not been independently verified; verify it (verify_destination) before paying")
        return employee

    def _pay_manifest(self, payment_id: str, *, actor_role: str) -> dict[str, Any]:
        p = self.payment(payment_id)
        if p["status"] != "draft":
            raise ReimbursementError(f"payment {payment_id} is {p['status']}, not draft")
        row = self._claim_row(p["claim_id"])
        if row["status"] not in PAYABLE_STATES:
            raise ReimbursementError(f"claim {row['id']} is {row['status']}; nothing is payable")
        employee = self._verified_employee(row["employee_id"])
        # the transfer terms the core payment path quotes: entity, currency, value date, provider fee
        terms = self.c.payments.payment_terms(p["amount"], row["project_id"])
        # The claim's status is deliberately not bound: an earlier in-flight payment being
        # accepted moves it (approved -> partially_paid) without changing anything this
        # approval covers.  What could matter -- the outstanding balance after reservations,
        # the claim content, the destination and the transfer terms -- is bound.
        return build_manifest(
            operation=OP_PAY,
            subject_type=PAYMENT_SUBJECT,
            subject_id=payment_id,
            actor_role=actor_role,
            amounts={"amount": p["amount"], "claim_outstanding": self._outstanding_row(row)},
            bindings={
                "payment_version": p["version"],
                "claim_id": row["id"],
                "claim_version": row["version"],
                "claim_hash": row["content_hash"],
                "project_id": row["project_id"],
                "employee_id": row["employee_id"],
                "destination_verified": bool(employee["destination_verified"]),
                "payable_account": EMPLOYEE_PAYABLE,
                "route": PAYMENT_ROUTE,
                "funding_source": "operating-bank-simulated",
                "fees": terms["fee"],
                "value_date": terms["value_date"],
                "posting_rule": POSTING_RULE,
            },
            destination={"party_id": employee["id"], "destination": employee["destination"], "destination_version": employee["destination_version"]},
            entity=terms["entity"],
            currency=terms["currency"],
        )

    def _bill_manifest(self, billing_id: str, *, actor_role: str) -> dict[str, Any]:
        b = self.billing(billing_id)
        if b["status"] != "draft":
            raise ReimbursementError(f"billing {billing_id} is {b['status']}, not draft")
        row = self._claim_row(b["claim_id"])
        return build_manifest(
            operation=OP_BILL,
            subject_type=BILLING_SUBJECT,
            subject_id=billing_id,
            actor_role=actor_role,
            amounts={"amount": b["amount"], "claim_amount": row["amount"], "billed_before": self._billed_total(row["id"], include_drafts=False)},
            bindings={
                "billing_version": b["version"],
                "claim_id": row["id"],
                "claim_version": row["version"],
                "claim_hash": row["content_hash"],
                "billable": bool(row["billable"]),
                "project_id": row["project_id"],
                "customer_id": b["customer_id"],
                "receipt_hash": row["receipt_hash"],
                "recognition_policy": "fixture: reimbursable expense billed = earned (SHADOW)",
                "posting_rule": POSTING_RULE,
            },
        )

    def _check_voidable(self, row: dict[str, Any]) -> None:
        """A void unwinds an approval nobody has acted on: the claim must still be
        plainly approved, with no booked or in-flight payment and nothing billed to the customer."""
        if row["status"] != "approved":
            raise ReimbursementError(f"claim {row['id']} is {row['status']}; only approved claims with nothing paid or billed can be voided")
        booked = self._booked_total(row["id"])
        if booked != ZERO:
            raise ReimbursementError(f"claim {row['id']} has {fmt(booked)} of booked payments; a settled claim cannot be voided")
        in_flight = self._in_flight_total(row["id"])
        if in_flight != ZERO:
            raise ReimbursementError(f"claim {row['id']} has {fmt(in_flight)} of payments in flight; resolve them before voiding")
        billed = self._billed_total(row["id"], include_drafts=False)
        if billed != ZERO:
            raise ReimbursementError(f"claim {row['id']} has {fmt(billed)} billed to the customer; a billed claim cannot be voided")
        if not row["journal_id"]:
            raise ReimbursementError(f"claim {row['id']} has no approval journal to reverse")

    def _void_manifest(self, claim_id: str, *, actor_role: str) -> dict[str, Any]:
        row = self._claim_row(claim_id)
        self._check_voidable(row)
        return build_manifest(
            operation=OP_VOID,
            subject_type=CLAIM_SUBJECT,
            subject_id=claim_id,
            actor_role=actor_role,
            amounts={
                "amount": row["amount"],
                "booked_payments": self._booked_total(claim_id),
                "in_flight_payments": self._in_flight_total(claim_id),
                "posted_billings": self._billed_total(claim_id, include_drafts=False),
            },
            bindings={
                "claim_version": row["version"],
                "claim_hash": row["content_hash"],
                "claim_status": row["status"],
                "journal_id": row["journal_id"],
                "approval_id": row["approval_id"],
                "project_id": row["project_id"],
                "employee_id": row["employee_id"],
                "receipt_hash": row["receipt_hash"],
                "posting_rule": POSTING_RULE,
            },
        )

    # ---- approvals: execution --------------------------------------------------- #

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        pid = period_id or self.c.current_period()["id"]
        if operation == OP_APPROVE:
            return self._apply_approve(subject_id, approval_id=approval_id, actor=actor, period_id=pid)
        if operation == OP_PAY:
            return self._apply_pay(subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=pid)
        if operation == OP_BILL:
            return self._apply_bill(subject_id, approval_id=approval_id, actor=actor, period_id=pid)
        if operation == OP_VOID:
            return self._apply_void(subject_id, approval_id=approval_id, actor=actor, period_id=pid)
        raise ReimbursementError(f"unknown reimbursement operation {operation}")

    def _apply_approve(self, claim_id: str, *, approval_id: str, actor: str, period_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = self._claim_row(claim_id)
            if row["status"] != "submitted":
                raise ReimbursementError(f"claim {claim_id} is {row['status']}, not submitted")
            self.ledger.require_open(period_id)
            amt = money(row["amount"])
            j = self.ledger.post(
                period_id=period_id,
                description=f"Reimbursement claim approved: {row['description']}",
                lines=[
                    {"account": "5100", "debit": amt, "project_id": row["project_id"], "party_id": row["employee_id"], "memo": f"receipt {row['receipt_hash']}"},
                    {"account": EMPLOYEE_PAYABLE, "credit": amt, "project_id": row["project_id"], "party_id": row["employee_id"], "memo": "owed to employee"},
                ],
                source_type=CLAIM_SUBJECT, source_id=claim_id, source_version=str(row["version"]), posted_by=actor, approval_id=approval_id,
            )
            now = utcnow_iso()
            conn.execute(
                "UPDATE reimbursement_claims SET status='approved', approval_id=?, journal_id=?, period_id=?, approved_at=?, updated_at=? WHERE id=?",
                (approval_id, j["id"], period_id, now, now, claim_id),
            )
            # any other approval still open on this claim was for a state that no longer exists
            self.approvals.invalidate_for_subject(CLAIM_SUBJECT, claim_id, reason="claim already approved", actor=actor)
            self.audit.record(actor, "reimbursement.approved", CLAIM_SUBJECT, claim_id, {"approval_id": approval_id, "journal_id": j["id"], "amount": fmt(amt), "period_id": period_id, "employee_id": row["employee_id"]})
        return {"claim": claim_id, "status": "approved", "journal_id": j["id"], "amount": fmt(amt), "period_id": period_id}

    def _apply_pay(self, payment_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str) -> dict[str, Any]:
        """Release the payment to the core payment outbox.  Nothing is posted here:
        the books move when the provider accepts (Dr 2100 / Cr 1200) and settles
        (Dr 1200 / Cr 1000).  Restore quarantine applies through create_intent."""
        with self.db.transaction() as conn:
            p = self.payment(payment_id)
            if p["status"] != "draft":
                raise ReimbursementError(f"payment {payment_id} is {p['status']}, not draft")
            row = self._claim_row(p["claim_id"])
            if row["status"] not in PAYABLE_STATES:
                raise ReimbursementError(f"claim {row['id']} is {row['status']}; nothing is payable")
            outstanding = self._outstanding_row(row)
            amt = money(p["amount"])
            if amt > outstanding:
                raise ReimbursementError(f"payment {fmt(amt)} exceeds the outstanding balance {fmt(outstanding)} on claim {row['id']}")
            employee = self._verified_employee(row["employee_id"])
            if (manifest.get("destination") or {}).get("party_id") != employee["id"]:
                raise ReimbursementError(f"the payment manifest does not name employee {employee['id']} as the payee")
            self.ledger.require_open(period_id)
            intent = self.c.payments.create_intent(
                manifest=manifest, approval_id=approval_id, bill_id=None, note="reimbursement payment", actor=actor,
                project_id=row["project_id"], source_type=PAYMENT_SUBJECT, source_id=payment_id, payable_account=EMPLOYEE_PAYABLE,
            )
            now = utcnow_iso()
            conn.execute(
                "UPDATE reimbursement_payments SET status='in_flight', intent_id=?, approval_id=?, released_at=?, version=version+1 WHERE id=?",
                (intent["id"], approval_id, now, payment_id),
            )
            remaining = money(outstanding - amt)
            # a duplicate approval on this payment would now describe a state that no longer exists,
            # and so would an open void of the claim: money is moving
            self.approvals.invalidate_for_subject(PAYMENT_SUBJECT, payment_id, reason="payment already released to the payment outbox", actor=actor)
            self.approvals.invalidate_for_subject(CLAIM_SUBJECT, row["id"], reason=f"payment {payment_id} released against the claim", actor=actor)
            self.audit.record(actor, "reimbursement.payment_released", PAYMENT_SUBJECT, payment_id, {
                "claim_id": row["id"], "approval_id": approval_id, "intent_id": intent["id"], "amount": fmt(amt),
                "outstanding_after": fmt(remaining), "destination_version": employee["destination_version"], "period_id": period_id,
            })
        return {
            "payment": payment_id, "claim": row["id"], "status": "in_flight", "intent": intent["id"], "intent_status": intent["status"],
            "claim_status": row["status"], "amount": fmt(amt), "outstanding": fmt(remaining), "period_id": period_id,
        }

    def _apply_bill(self, billing_id: str, *, approval_id: str, actor: str, period_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            b = self.billing(billing_id)
            if b["status"] != "draft":
                raise ReimbursementError(f"billing {billing_id} is {b['status']}, not draft")
            row = self._claim_row(b["claim_id"])
            if not row["billable"]:
                raise ReimbursementError(f"claim {row['id']} is not billable to the customer")
            if row["status"] not in APPROVED_STATES:
                raise ReimbursementError(f"claim {row['id']} is {row['status']}; only approved claims can be billed")
            amt = money(b["amount"])
            billed = self._billed_total(row["id"], include_drafts=False)
            if money(billed + amt) > money(row["amount"]):
                raise ReimbursementError(f"billing {fmt(amt)} would exceed the claim amount {row['amount']} (already billed {fmt(billed)})")
            self.ledger.require_open(period_id)
            j = self.ledger.post(
                period_id=period_id,
                description=f"Reimbursable expense billed to customer on claim {row['id']}",
                lines=[
                    {"account": "1100", "debit": amt, "project_id": row["project_id"], "party_id": b["customer_id"], "memo": f"reimbursable: {row['description']}"},
                    {"account": "4000", "credit": amt, "project_id": row["project_id"], "party_id": b["customer_id"], "memo": "reimbursable expense billed (fixture policy)"},
                ],
                source_type=BILLING_SUBJECT, source_id=billing_id, source_version=str(b["version"]), posted_by=actor, approval_id=approval_id,
            )
            conn.execute(
                "UPDATE reimbursement_billings SET status='billed', approval_id=?, journal_id=?, period_id=?, billed_at=? WHERE id=?",
                (approval_id, j["id"], period_id, utcnow_iso(), billing_id),
            )
            self.approvals.invalidate_for_subject(BILLING_SUBJECT, billing_id, reason="billing already posted", actor=actor)
            # a billed claim can no longer be voided; drop any open void approval on it
            self.approvals.invalidate_for_subject(CLAIM_SUBJECT, row["id"], reason=f"billing {billing_id} posted against the claim", actor=actor)
            self.audit.record(actor, "reimbursement.billed", BILLING_SUBJECT, billing_id, {"claim_id": row["id"], "customer_id": b["customer_id"], "approval_id": approval_id, "journal_id": j["id"], "amount": fmt(amt), "period_id": period_id})
        return {"billing": billing_id, "claim": row["id"], "status": "billed", "amount": fmt(amt), "customer_id": b["customer_id"], "journal_id": j["id"], "period_id": period_id}

    def _apply_void(self, claim_id: str, *, approval_id: str, actor: str, period_id: str) -> dict[str, Any]:
        """Reverse the approval journal and retire the claim.  Draft payments and
        billings on it are canceled; booked, in-flight or billed ones block the void."""
        with self.db.transaction() as conn:
            row = self._claim_row(claim_id)
            self._check_voidable(row)
            self.ledger.require_open(period_id)
            canceled_payments = []
            for p in self.db.query("SELECT * FROM reimbursement_payments WHERE claim_id=? AND status='draft' ORDER BY created_at, id", (claim_id,)):
                self._cancel_draft_payment(p, actor=actor, reason=f"claim {claim_id} voided")
                canceled_payments.append(p["id"])
            canceled_billings = []
            for b in self.db.query("SELECT * FROM reimbursement_billings WHERE claim_id=? AND status='draft' ORDER BY created_at, id", (claim_id,)):
                self._cancel_draft_billing(b, actor=actor, reason=f"claim {claim_id} voided")
                canceled_billings.append(b["id"])
            j = self.ledger.reverse(row["journal_id"], period_id=period_id, posted_by=actor, reason=f"reimbursement claim {claim_id} voided", approval_id=approval_id)
            now = utcnow_iso()
            conn.execute(
                "UPDATE reimbursement_claims SET status='voided', void_approval_id=?, reversal_journal_id=?, voided_at=?, updated_at=? WHERE id=?",
                (approval_id, j["id"], now, now, claim_id),
            )
            self.approvals.invalidate_for_subject(CLAIM_SUBJECT, claim_id, reason="claim voided", actor=actor)
            self.audit.record(actor, "reimbursement.voided", CLAIM_SUBJECT, claim_id, {
                "approval_id": approval_id, "reversed_journal_id": row["journal_id"], "reversal_journal_id": j["id"], "amount": row["amount"],
                "period_id": period_id, "employee_id": row["employee_id"], "receipt_hash": row["receipt_hash"],
                "payments_canceled": canceled_payments, "billings_canceled": canceled_billings,
            })
        return {
            "claim": claim_id, "status": "voided", "amount": row["amount"], "reversed_journal_id": row["journal_id"], "reversal_journal_id": j["id"],
            "period_id": period_id, "payments_canceled": canceled_payments, "billings_canceled": canceled_billings,
        }

    # ---- subledger, close checks and state ---------------------------------------- #

    def employee_payable_reconciliation(self, project_id: str) -> dict[str, Any]:
        """Payable (approved less booked) on approved / partially paid claims against
        the 2100 control account.  In-flight payments are still owed until the
        provider accepts them, so they stay in the payable and are reported apart."""
        items = []
        subledger = ZERO
        in_flight_total = ZERO
        rows = self.db.query(
            "SELECT * FROM reimbursement_claims WHERE project_id=? AND status IN ('approved','partially_paid') ORDER BY created_at, id",
            (project_id,),
        )
        for row in rows:
            payable = self._payable_row(row)
            in_flight = self._in_flight_total(row["id"])
            items.append({
                "claim_id": row["id"], "employee_id": row["employee_id"], "status": row["status"], "amount": row["amount"],
                "paid": fmt(self._booked_total(row["id"])), "in_flight": fmt(in_flight), "payable": fmt(payable), "outstanding": fmt(payable - in_flight),
            })
            subledger += payable
            in_flight_total += in_flight
        control = self.ledger.balance(EMPLOYEE_PAYABLE, project_id=project_id)
        return {"items": items, "subledger_total": fmt(subledger), "in_flight_total": fmt(in_flight_total), "control_balance": fmt(control), "reconciled": money(subledger) == control}

    def close_checks(self, period_id: str) -> list[dict[str, Any]]:
        """Checks only this module can make (cumulative, not per period).  The close
        module already checks the 2100 reconciliation and unresolved payment intents."""
        out_of_sync = self._out_of_sync()
        moving = self.db.query("SELECT amount FROM reimbursement_payments WHERE status='in_flight'")
        ar = self.ar_open_items()
        return [
            {"check": "reimbursement payments follow their payment intents", "ok": not out_of_sync,
             "detail": (f"{len(out_of_sync)} payment(s) out of step with their intent: " + ", ".join(p["id"] for p in out_of_sync) + "; run sync_payments"
                        if out_of_sync else "every released reimbursement payment matches its payment intent")},
            {"check": "reimbursement payments in flight", "ok": True,
             "detail": f"{len(moving)} in flight ({fmt(total(m['amount'] for m in moving))}); they post when the provider accepts them"},
            {"check": "reimbursement billings receivable matches its 1100 postings", "ok": ar["reconciled_to_postings"],
             "detail": f"open billings {ar['subledger_total']} vs 1100 postings by billings, reversals and collections {ar['ledger_postings']}"},
        ]

    def state(self, project_id: str) -> dict[str, Any]:
        return {
            "claims": self.claims(project_id),
            "payments": self.payments(project_id),
            "billings": self.billings(project_id),
            "collections": self.collections(project_id),
            "reconciliation": self.employee_payable_reconciliation(project_id),
            "receivable": self.ar_open_items(project_id),
        }

    def audit_export(self) -> dict[str, Any]:
        q = self.db.query
        return {
            "claims": q("SELECT * FROM reimbursement_claims ORDER BY created_at, id"),
            "payments": q("SELECT * FROM reimbursement_payments ORDER BY created_at, id"),
            "billings": q("SELECT * FROM reimbursement_billings ORDER BY created_at, id"),
            "collections": q("SELECT * FROM reimbursement_collections ORDER BY received_at, id"),
            "receivable": self.ar_open_items(),
            "employee_payable": {p["project_id"]: self.employee_payable_reconciliation(p["project_id"])
                                 for p in q("SELECT DISTINCT project_id FROM reimbursement_claims ORDER BY project_id")},
        }
