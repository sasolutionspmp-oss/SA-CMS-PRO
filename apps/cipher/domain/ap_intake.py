"""Supplier invoice intake, duplicate detection and 3-way match (plan section 11, first slice).

Flow::

    receive_invoice ──> received ──(match: computed, recorded)──> matched | exception
        ──(ap_intake.match_invoice, approval-bound)──> invoice matched, linked to its bill
    revise_invoice (supplier replaced it) ──> received again, at the next version
    clear_duplicate_flag / reject_invoice

Intake.  ``receive_invoice`` records a supplier's invoice on a project: number, invoice
date, amount (positive whole cents), optional service period, optional lines, the commitment
it bills (optional) and the content hash of the CURRENT revision of a ``supplier_invoice``
document on the project (the invoice PDF; one document backs one live invoice).  The due
date defaults to the invoice date plus the supplier's payment terms (``set_terms``, default
30 days).  Lines (``description``, ``amount``, optional ``quantity`` x ``unit_price``, and
one of ``sov_line_id`` / ``equipment_id``) must add up to the invoice amount exactly.

Duplicates.  The same supplier and the same normalized invoice number (case, spaces and
punctuation ignored) is refused, whatever happened to the first invoice.  A near duplicate
-- same supplier, same amount, invoice dates within 7 days, another number -- is accepted
but flagged ``possible_duplicate``; it cannot be matched until ``clear_duplicate_flag``
records who reviewed it and why (or it is rejected).

Match (the plugin computes, then an approval binds).  ``match`` chooses the basis:

* progress subcontract (a commitment that no procurement award created): the invoice must
  name the commitment, and a certified (draft or posted) bill of that commitment, not
  stale and not carrying a link to another invoice that still holds, must be due exactly
  the invoice amount;
* purchase order (a commitment drafted by ``procurement.award``, named by the invoice or
  found through its equipment lines): every line names equipment on that purchase order
  received in condition ``ok`` through procurement's receipts, each line equals its PO line
  and the invoice equals the PO lines it bills (tolerance 0.00).  A certified bill of the
  PO commitment due exactly the invoice amount is linked too when there is one.

The result is ``matched`` or ``exception`` with explicit codes (``EXCEPTION_CODES``):
``amount_mismatch``, ``not_received``, ``damaged_receipt``, ``no_certified_bill``,
``possible_duplicate``, ``evidence_stale`` (the invoice PDF has a newer revision),
``over_commitment`` (invoices matched on the commitment would exceed its executed amount,
equipment not on the PO or already invoiced, or a PO that is not executed).  Each computation
is appended to ``ap_invoice_matches`` and reported by ``state`` and ``close_checks`` (an
unmatched invoice past its due date fails the close check of an open period).

``ap_intake.match_invoice`` (subject: the invoice).  The manifest binds the invoice hash and
version, the evidence hash and the document's current hash, the recorded match computation
and its result hash, the matched bill id, content hash and status or the matched receipt ids,
the amounts, the due date and the supplier destination version.  It can be requested only
for a received invoice whose latest computation, on its current version, still equals a
fresh one and is ``matched``; when anything moved (the bill, a receipt, the invoice, its
PDF) execution finds ``InvoiceIneligible`` -- a ``StaleApprovalError`` -- and the approval
is invalidated.  Executing records the match on the invoice and then links the invoice to
the bill through ``Bills.attach_supplier_invoice``, which copies the supplier invoice id,
number, invoice date, due date and hashes from the matched record (never from the caller).

One invoice, one live bill.  An invoice attached to a live (draft, posted or paid) bill is
matched only to that bill again -- a revised amount that no longer fits it is an
``amount_mismatch`` -- until another matched invoice replaces it there: a bill whose link
points at a rejected invoice, or at one revised since it was attached, is free for another
invoice.  A storage guard refuses one invoice on two live bills.

Unmatched.  An invoice matched to a bill that is later voided or corrected counts as
unmatched (``state``, ``close_checks``) and is reopened by the next ``match`` (version bump,
back to received), so it can be matched to the replacement bill.  A purchase-order invoice
matched to its receipts before any bill of the PO existed is reopened the same way once a
certified PO bill is due exactly its amount, so that bill is linked under a new approval.

Integrity.  Database guards back the rules: invoices are born received at version 1 with
their audit entry, change content only by a version bump that carries its audited revision
(the new version, content hash, amount and duplicate flag), are reviewed as possible
duplicates, rejected and matched only together with the audit entry the intake writes first
(a match needs a fresh consumed approval, never one an earlier version used), keep a match
state equal to the recorded computation of their version, rejected invoices are final, the
computation log is append-only and audited, and nothing is deleted.  ``match`` and the match
approval also refuse an invoice whose stored facts no longer hash to its content hash, and
``close_checks`` reports one ("supplier invoice records intact").
"""
from __future__ import annotations

import datetime as _dt
import unicodedata
from decimal import Decimal
from typing import Any

from ..core.approvals import StaleApprovalError, build_manifest
from ..core.db import register_schema_version
from ..core.ids import canonical_json, hash_json, loads, new_id, utcnow, utcnow_iso
from ..core.money import ZERO, D, MoneyError, fmt, money, total
# Imported for its schema entries: the bills columns this module's integrity entry guards
# (supplier_invoice_*) must exist, and the bills table must be in its final (rebuilt) form,
# before that entry is created -- importing bills first puts its entries ahead in the catalog.
from .bills import BILLS_LINK_PAYMENT_SCHEMA_NAME as _BILLS_ENTRIES_FIRST  # noqa: F401

SCHEMA_NAME = "ap_intake"
PLUGIN_NAME = "ap_intake"
OP_MATCH = "ap_intake.match_invoice"
INVOICE_SUBJECT = "ap_invoice"
SUPPLIER_INVOICE_KIND = "supplier_invoice"
DEFAULT_TERMS_DAYS = 30
MAX_TERMS_DAYS = 365
NEAR_DUPLICATE_DAYS = 7
MAX_LINES = 500
MAX_TEXT_LENGTH = 500
MAX_NUMBER_LENGTH = 64
BASIS_PROGRESS = "progress"
BASIS_PURCHASE_ORDER = "purchase_order"
EXCEPTION_CODES = ("amount_mismatch", "not_received", "damaged_receipt", "no_certified_bill", "possible_duplicate", "evidence_stale", "over_commitment")
LINE_KEYS = ("description", "quantity", "unit_price", "amount", "sov_line_id", "equipment_id")

SCHEMA_STATEMENTS = [
    """CREATE TABLE ap_supplier_terms (
        supplier_id TEXT PRIMARY KEY REFERENCES parties(id),
        days INTEGER NOT NULL CHECK (days >= 0 AND days <= 365),
        version INTEGER NOT NULL DEFAULT 1,
        set_by TEXT NOT NULL CHECK (length(trim(set_by)) > 0),
        set_at TEXT NOT NULL
    )""",
    """CREATE TRIGGER ap_supplier_terms_versioned BEFORE UPDATE ON ap_supplier_terms
        WHEN NEW.supplier_id IS NOT OLD.supplier_id OR NEW.version IS NOT OLD.version + 1
        BEGIN SELECT RAISE(ABORT, 'supplier payment terms change only by a new version'); END""",
    "CREATE TRIGGER ap_supplier_terms_no_delete BEFORE DELETE ON ap_supplier_terms BEGIN SELECT RAISE(ABORT, 'supplier payment terms are never deleted'); END",
    """CREATE TABLE ap_invoices (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        supplier_id TEXT NOT NULL REFERENCES parties(id),
        commitment_id TEXT REFERENCES commitments(id),
        invoice_number TEXT NOT NULL CHECK (length(trim(invoice_number)) > 0),
        number_key TEXT NOT NULL CHECK (length(number_key) > 0),
        invoice_date TEXT NOT NULL,
        due_date TEXT NOT NULL CHECK (due_date >= invoice_date),
        terms_days INTEGER,
        amount TEXT NOT NULL,
        service_period_start TEXT,
        service_period_end TEXT,
        evidence_hash TEXT NOT NULL CHECK (length(trim(evidence_hash)) > 0),
        evidence_document_id TEXT NOT NULL REFERENCES documents(id),
        evidence_revision_id TEXT NOT NULL REFERENCES document_revisions(id),
        lines_json TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL CHECK (status IN ('received','matched','rejected')),
        possible_duplicate INTEGER NOT NULL DEFAULT 0 CHECK (possible_duplicate IN (0, 1)),
        duplicate_of_json TEXT NOT NULL DEFAULT '[]',
        duplicate_cleared_by TEXT,
        duplicate_cleared_at TEXT,
        duplicate_clear_reason TEXT,
        match_status TEXT CHECK (match_status IS NULL OR match_status IN ('matched','exception')),
        match_basis TEXT CHECK (match_basis IS NULL OR match_basis IN ('progress','purchase_order')),
        match_exceptions_json TEXT NOT NULL DEFAULT '[]',
        match_attempt_id TEXT,
        matched_bill_id TEXT REFERENCES bills(id),
        matched_commitment_id TEXT REFERENCES commitments(id),
        match_approval_id TEXT UNIQUE REFERENCES approvals(id),
        matched_at TEXT,
        matched_by TEXT,
        rejected_by TEXT,
        rejected_at TEXT,
        reject_reason TEXT,
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK ((service_period_start IS NULL) = (service_period_end IS NULL)),
        CHECK (service_period_start IS NULL OR service_period_start <= service_period_end)
    )""",
    # the same supplier never has two invoices with one normalized number
    "CREATE UNIQUE INDEX ap_invoices_supplier_number ON ap_invoices (supplier_id, number_key)",
    "CREATE UNIQUE INDEX ap_invoices_one_per_document ON ap_invoices (evidence_document_id) WHERE status != 'rejected'",
    "CREATE INDEX ap_invoices_by_project ON ap_invoices (project_id, created_at)",
    """CREATE TRIGGER ap_invoices_born_received BEFORE INSERT ON ap_invoices
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM ap_invoices WHERE id = NEW.id)
            THEN RAISE(ABORT, 'supplier invoices are never replaced: that invoice id already exists')
          WHEN EXISTS (SELECT 1 FROM ap_invoices WHERE supplier_id = NEW.supplier_id AND number_key = NEW.number_key)
            THEN RAISE(ABORT, 'duplicate supplier invoice: that supplier already has an invoice with this number')
          WHEN EXISTS (SELECT 1 FROM ap_invoices WHERE evidence_document_id = NEW.evidence_document_id AND status != 'rejected')
            THEN RAISE(ABORT, 'that invoice document already supports another supplier invoice')
          WHEN NEW.status IS NOT 'received' OR NEW.version IS NOT 1 OR NEW.match_status IS NOT NULL OR NEW.match_attempt_id IS NOT NULL
            OR NEW.matched_bill_id IS NOT NULL OR NEW.match_approval_id IS NOT NULL OR NEW.matched_at IS NOT NULL
            OR NEW.duplicate_cleared_at IS NOT NULL OR NEW.rejected_at IS NOT NULL
            THEN RAISE(ABORT, 'a supplier invoice is received unmatched, at version 1')
        END; END""",
    """CREATE TRIGGER ap_invoices_identity_immutable BEFORE UPDATE ON ap_invoices
        WHEN NEW.id IS NOT OLD.id OR NEW.project_id IS NOT OLD.project_id OR NEW.supplier_id IS NOT OLD.supplier_id
          OR NEW.created_by IS NOT OLD.created_by OR NEW.created_at IS NOT OLD.created_at
        BEGIN SELECT RAISE(ABORT, 'a supplier invoice''s project, supplier and receipt are immutable'); END""",
    """CREATE TRIGGER ap_invoices_rejected_final BEFORE UPDATE ON ap_invoices WHEN OLD.status = 'rejected'
        BEGIN SELECT RAISE(ABORT, 'a rejected supplier invoice is final'); END""",
    """CREATE TRIGGER ap_invoices_revision_bumps BEFORE UPDATE ON ap_invoices
        WHEN (NEW.invoice_number IS NOT OLD.invoice_number OR NEW.number_key IS NOT OLD.number_key OR NEW.invoice_date IS NOT OLD.invoice_date
              OR NEW.due_date IS NOT OLD.due_date OR NEW.terms_days IS NOT OLD.terms_days OR NEW.amount IS NOT OLD.amount
              OR NEW.commitment_id IS NOT OLD.commitment_id OR NEW.service_period_start IS NOT OLD.service_period_start
              OR NEW.service_period_end IS NOT OLD.service_period_end OR NEW.evidence_hash IS NOT OLD.evidence_hash
              OR NEW.evidence_document_id IS NOT OLD.evidence_document_id OR NEW.evidence_revision_id IS NOT OLD.evidence_revision_id
              OR NEW.lines_json IS NOT OLD.lines_json OR NEW.content_hash IS NOT OLD.content_hash OR NEW.version IS NOT OLD.version)
          AND (NEW.version IS NOT OLD.version + 1 OR NEW.content_hash IS OLD.content_hash)
        BEGIN SELECT RAISE(ABORT, 'a supplier invoice changes only by a revision that bumps its version and content hash'); END""",
    """CREATE TRIGGER ap_invoices_status_machine BEFORE UPDATE OF status ON ap_invoices
        WHEN NEW.status IS NOT OLD.status AND NOT (
             (OLD.status = 'received' AND NEW.status = 'rejected' AND NEW.rejected_at IS NOT NULL AND NEW.rejected_by IS NOT NULL
              AND length(trim(COALESCE(NEW.reject_reason, ''))) > 0)
          OR (OLD.status = 'received' AND NEW.status = 'matched' AND NEW.match_status = 'matched' AND NEW.matched_at IS NOT NULL
              AND (NEW.possible_duplicate = 0 OR NEW.duplicate_cleared_at IS NOT NULL)
              AND EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.match_approval_id AND a.status = 'consumed'
                            AND a.operation = 'ap_intake.match_invoice' AND a.subject_id = NEW.id))
          OR (OLD.status = 'matched' AND NEW.status = 'received' AND NEW.version = OLD.version + 1))
        BEGIN SELECT RAISE(ABORT, 'a supplier invoice moves received -> matched (with its consumed match approval) or rejected, and back from matched to received only by a revision'); END""",
    """CREATE TRIGGER ap_invoices_match_recorded_by_match BEFORE UPDATE OF match_approval_id, matched_bill_id, matched_commitment_id, matched_at, matched_by ON ap_invoices
        WHEN (NEW.match_approval_id IS NOT OLD.match_approval_id OR NEW.matched_bill_id IS NOT OLD.matched_bill_id
              OR NEW.matched_commitment_id IS NOT OLD.matched_commitment_id OR NEW.matched_at IS NOT OLD.matched_at OR NEW.matched_by IS NOT OLD.matched_by)
          AND NOT (OLD.status = 'received' AND NEW.status = 'matched')
        BEGIN SELECT RAISE(ABORT, 'a supplier invoice''s match is recorded only by the match approval it executes'); END""",
    """CREATE TRIGGER ap_invoices_duplicate_review_once BEFORE UPDATE OF duplicate_cleared_by, duplicate_cleared_at, duplicate_clear_reason, possible_duplicate ON ap_invoices
        WHEN (NEW.duplicate_cleared_at IS NOT OLD.duplicate_cleared_at OR NEW.duplicate_cleared_by IS NOT OLD.duplicate_cleared_by
              OR NEW.duplicate_clear_reason IS NOT OLD.duplicate_clear_reason OR NEW.possible_duplicate IS NOT OLD.possible_duplicate)
          AND NEW.version IS OLD.version
          AND NOT (OLD.possible_duplicate = 1 AND NEW.possible_duplicate = 1 AND OLD.duplicate_cleared_at IS NULL AND NEW.duplicate_cleared_at IS NOT NULL
                   AND length(trim(COALESCE(NEW.duplicate_cleared_by, ''))) > 0 AND length(trim(COALESCE(NEW.duplicate_clear_reason, ''))) > 0)
        BEGIN SELECT RAISE(ABORT, 'a possible-duplicate flag is cleared once, with who and why, and is re-evaluated only by a revision'); END""",
    "CREATE TRIGGER ap_invoices_no_delete BEFORE DELETE ON ap_invoices BEGIN SELECT RAISE(ABORT, 'supplier invoices are never deleted; reject one instead'); END",
    """CREATE TABLE ap_invoice_matches (
        id TEXT PRIMARY KEY,
        invoice_id TEXT NOT NULL REFERENCES ap_invoices(id),
        invoice_version INTEGER NOT NULL,
        basis TEXT NOT NULL CHECK (basis IN ('progress','purchase_order')),
        status TEXT NOT NULL CHECK (status IN ('matched','exception')),
        exceptions_json TEXT NOT NULL,
        result_json TEXT NOT NULL,
        result_hash TEXT NOT NULL,
        computed_by TEXT NOT NULL,
        computed_at TEXT NOT NULL
    )""",
    "CREATE INDEX ap_invoice_matches_by_invoice ON ap_invoice_matches (invoice_id)",
    """CREATE TRIGGER ap_invoice_matches_no_replace BEFORE INSERT ON ap_invoice_matches WHEN EXISTS (SELECT 1 FROM ap_invoice_matches WHERE id = NEW.id)
        BEGIN SELECT RAISE(ABORT, 'match computations are append-only: an id is never reused or replaced'); END""",
    "CREATE TRIGGER ap_invoice_matches_no_update BEFORE UPDATE ON ap_invoice_matches BEGIN SELECT RAISE(ABORT, 'match computations are append-only'); END",
    "CREATE TRIGGER ap_invoice_matches_no_delete BEFORE DELETE ON ap_invoice_matches BEGIN SELECT RAISE(ABORT, 'match computations are append-only'); END",
]
# Registered here (the plugin loader registers the same entry again, a no-op by name) so the
# integrity entry below follows it in the catalog: a trigger must never name a table that does
# not exist yet (SQLite then refuses ALTER TABLE ... RENAME anywhere in the schema).
register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)


def _audited(action: str, *conditions: str, entity: str = "NEW.id") -> str:
    """SQL: an audit entry ``action`` on the supplier invoice whose payload carries the given facts."""
    where = " AND ".join(conditions)
    return (f"EXISTS (SELECT 1 FROM audit_log g WHERE g.entity_type = 'ap_invoice' AND g.entity_id = {entity} AND g.action {action}"
            + (f" AND {where}" if where else "") + ")")


def _payload(path: str, value: str) -> str:
    return f"json_extract(g.payload_json, '$.{path}') IS {value}"


# Append-only schema entry (review follow-up to ``ap_intake``).  Every change to an invoice's
# facts, duplicate review, rejection, match state or match is admitted only together with the
# audit entry the intake writes first, carrying exactly the new facts; a version bump without
# its audited revision (an amount or a duplicate flag rewritten with a forged content hash) is
# refused, and so is a match that reuses an earlier approval.  The supplier-invoice link on a
# bill must copy the invoice record matched to that bill under that approval.  (This entry
# names the bills table in its final rebuilt form, so ``bills`` is imported first, above.)
INTEGRITY_SCHEMA_NAME = "ap_intake_integrity_guards"
INTEGRITY_SCHEMA_STATEMENTS = [
    f"""CREATE TRIGGER ap_invoices_receipt_audited BEFORE INSERT ON ap_invoices
        WHEN NOT {_audited("= 'ap_intake.invoice_received'", _payload('content_hash', 'NEW.content_hash'), _payload('amount', 'NEW.amount'),
                           _payload('possible_duplicate', 'NEW.possible_duplicate'))}
        BEGIN SELECT RAISE(ABORT, 'a supplier invoice is received only through receive_invoice, which audits its content hash, amount and duplicate flag'); END""",
    f"""CREATE TRIGGER ap_invoices_revision_audited BEFORE UPDATE ON ap_invoices
        WHEN NEW.version IS NOT OLD.version
          AND NOT {_audited("IN ('ap_intake.invoice_revised','ap_intake.match_reopened')", _payload('version', 'NEW.version'),
                            _payload('content_hash', 'NEW.content_hash'), _payload('amount', 'NEW.amount'),
                            _payload('possible_duplicate', 'NEW.possible_duplicate'))}
        BEGIN SELECT RAISE(ABORT, 'a supplier invoice moves to a new version only through revise_invoice or a recorded reopen, which audit the new version, its content hash, amount and duplicate flag'); END""",
    f"""CREATE TRIGGER ap_invoices_duplicate_clear_audited BEFORE UPDATE OF duplicate_cleared_at, duplicate_cleared_by, duplicate_clear_reason ON ap_invoices
        WHEN NEW.duplicate_cleared_at IS NOT NULL
          AND (NEW.duplicate_cleared_at IS NOT OLD.duplicate_cleared_at OR NEW.duplicate_cleared_by IS NOT OLD.duplicate_cleared_by
               OR NEW.duplicate_clear_reason IS NOT OLD.duplicate_clear_reason)
          AND NOT {_audited("= 'ap_intake.duplicate_flag_cleared'", _payload('cleared_at', 'NEW.duplicate_cleared_at'),
                            _payload('cleared_by', 'NEW.duplicate_cleared_by'), _payload('reason', 'NEW.duplicate_clear_reason'),
                            _payload('version', 'NEW.version'))}
        BEGIN SELECT RAISE(ABORT, 'a possible-duplicate flag is cleared only through clear_duplicate_flag, which audits who cleared it, when and why'); END""",
    f"""CREATE TRIGGER ap_invoices_rejection_audited BEFORE UPDATE OF status ON ap_invoices
        WHEN NEW.status = 'rejected' AND OLD.status IS NOT 'rejected'
          AND NOT {_audited("= 'ap_intake.invoice_rejected'", _payload('rejected_at', 'NEW.rejected_at'), _payload('reason', 'NEW.reject_reason'),
                            _payload('version', 'NEW.version'))}
        BEGIN SELECT RAISE(ABORT, 'a supplier invoice is rejected only through reject_invoice, which audits it'); END""",
    f"""CREATE TRIGGER ap_invoices_match_fresh_and_audited BEFORE UPDATE OF status ON ap_invoices
        WHEN NEW.status = 'matched' AND OLD.status IS NOT 'matched'
          AND (NEW.match_approval_id IS OLD.match_approval_id
               OR NOT {_audited("= 'ap_intake.invoice_matched'", _payload('approval_id', 'NEW.match_approval_id'),
                                _payload('invoice_version', 'NEW.version'), _payload('bill_id', 'NEW.matched_bill_id'),
                                _payload('attempt_id', 'NEW.match_attempt_id'))})
        BEGIN SELECT RAISE(ABORT, 'a supplier invoice is matched only by a fresh consumed match approval, through ap_intake.match_invoice, which audits it'); END""",
    """CREATE TRIGGER ap_invoices_match_state_recorded BEFORE UPDATE OF match_status, match_basis, match_exceptions_json, match_attempt_id ON ap_invoices
        WHEN (NEW.match_status IS NOT OLD.match_status OR NEW.match_basis IS NOT OLD.match_basis
              OR NEW.match_exceptions_json IS NOT OLD.match_exceptions_json OR NEW.match_attempt_id IS NOT OLD.match_attempt_id)
          AND NOT ((NEW.match_attempt_id IS NULL AND NEW.match_status IS NULL AND NEW.match_basis IS NULL AND NEW.match_exceptions_json = '[]'
                    AND NEW.version IS NOT OLD.version)
                   OR EXISTS (SELECT 1 FROM ap_invoice_matches m WHERE m.id = NEW.match_attempt_id AND m.invoice_id = NEW.id
                                AND m.invoice_version = NEW.version AND m.status IS NEW.match_status AND m.basis IS NEW.match_basis
                                AND m.exceptions_json IS NEW.match_exceptions_json))
        BEGIN SELECT RAISE(ABORT, 'an invoice''s match state is the recorded computation for its current version, and is cleared only by a new version'); END""",
    f"""CREATE TRIGGER ap_invoice_matches_audited BEFORE INSERT ON ap_invoice_matches
        WHEN NOT {_audited("= 'ap_intake.match_computed'", _payload('attempt_id', 'NEW.id'), _payload('result_hash', 'NEW.result_hash'),
                           _payload('invoice_version', 'NEW.invoice_version'), _payload('status', 'NEW.status'), entity='NEW.invoice_id')}
        BEGIN SELECT RAISE(ABORT, 'a match computation is recorded only through match, which audits it'); END""",
    """CREATE TRIGGER bills_supplier_invoice_from_matched_record BEFORE UPDATE OF supplier_invoice_id, supplier_invoice_number, invoice_date, due_date,
            supplier_invoice_hash, supplier_invoice_evidence_hash, supplier_invoice_approval_id ON bills
        WHEN (NEW.supplier_invoice_id IS NOT OLD.supplier_invoice_id OR NEW.supplier_invoice_number IS NOT OLD.supplier_invoice_number
              OR NEW.invoice_date IS NOT OLD.invoice_date OR NEW.due_date IS NOT OLD.due_date OR NEW.supplier_invoice_hash IS NOT OLD.supplier_invoice_hash
              OR NEW.supplier_invoice_evidence_hash IS NOT OLD.supplier_invoice_evidence_hash OR NEW.supplier_invoice_approval_id IS NOT OLD.supplier_invoice_approval_id)
          AND NOT EXISTS (SELECT 1 FROM ap_invoices i WHERE i.id = NEW.supplier_invoice_id AND i.status = 'matched'
                            AND i.match_approval_id IS NEW.supplier_invoice_approval_id AND i.matched_bill_id IS NEW.id
                            AND i.invoice_number IS NEW.supplier_invoice_number AND i.invoice_date IS NEW.invoice_date AND i.due_date IS NEW.due_date
                            AND i.content_hash IS NEW.supplier_invoice_hash AND i.evidence_hash IS NEW.supplier_invoice_evidence_hash)
        BEGIN SELECT RAISE(ABORT, 'a bill''s supplier invoice link copies the invoice record matched to that bill under that approval, field for field'); END""",
]
register_schema_version(INTEGRITY_SCHEMA_NAME, INTEGRITY_SCHEMA_STATEMENTS)
SCHEMA_ENTRIES = (SCHEMA_NAME, INTEGRITY_SCHEMA_NAME)


class APIntakeError(RuntimeError):
    """Invalid supplier-invoice input or an action the invoice's state does not allow."""


class DuplicateInvoiceError(APIntakeError):
    """The supplier already has an invoice with this (normalized) number."""


class InvoiceIneligible(APIntakeError, StaleApprovalError):
    """The invoice cannot be (or can no longer be) matched as approved.  At request time
    this refuses; at execution it is a ``StaleApprovalError``, so the service invalidates
    the approval durably (the invoice, its bill, its receipts or its PDF moved on)."""


# --------------------------------------------------------------------------- #
# Validation helpers                                                           #
# --------------------------------------------------------------------------- #

def _text(value: Any, label: str, *, max_length: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str) or not value.strip():
        raise APIntakeError(f"{label} is required")
    text = value.strip()
    if len(text) > max_length:
        raise APIntakeError(f"{label} is longer than {max_length} characters")
    return text


def _date(value: Any, label: str) -> _dt.date:
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise APIntakeError(f"{label} must be YYYY-MM-DD, got {value!r}")
    try:
        return _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise APIntakeError(f"{label} is not a valid calendar date: {value!r}") from exc


def _amount(value: Any, label: str) -> Decimal:
    """A positive amount in whole cents; floats, non-finite and sub-cent values are refused, not rounded."""
    try:
        raw = D(value)
        amt = money(raw)
    except (MoneyError, ArithmeticError) as exc:
        raise APIntakeError(f"{label} is not exact money: {exc}") from exc
    if amt != raw:
        raise APIntakeError(f"{label} must be in whole cents, got {value!r}")
    if amt <= 0:
        raise APIntakeError(f"{label} must be positive, got {fmt(amt)}")
    return amt


def _decimal(value: Any, label: str) -> Decimal:
    try:
        return D(value)
    except MoneyError as exc:
        raise APIntakeError(f"{label} is not an exact decimal: {exc}") from exc


def _invoice_number(value: Any) -> tuple[str, str]:
    """The invoice number as given (trimmed) and its normalized key.  Quotes, backslashes
    and control characters are refused: the number is copied into audited records."""
    number = _text(value, "invoice number", max_length=MAX_NUMBER_LENGTH)
    if any(ch in number for ch in '"\\') or any(ord(ch) < 32 for ch in number):
        raise APIntakeError(f"invoice number {number!r} may not contain quotes, backslashes or control characters")
    key = normalize_invoice_number(number)
    if not key:
        raise APIntakeError(f"invoice number {number!r} carries no letters or digits")
    return number, key


def normalize_invoice_number(number: str) -> str:
    """Case-, space- and punctuation-insensitive identity of an invoice number
    ("INV-0042", "inv 0042" and "Inv/0042" are the same number)."""
    folded = unicodedata.normalize("NFKC", number).casefold()
    return "".join(ch for ch in folded if ch.isalnum())


def _today() -> _dt.date:
    return utcnow().date()


# --------------------------------------------------------------------------- #
# Plugin                                                                       #
# --------------------------------------------------------------------------- #

class Plugin:
    def __init__(self, cipher):
        self.c = cipher
        self.db = cipher.db
        self.audit = cipher.audit
        self.approvals = cipher.approvals

    # ---- lookups ----------------------------------------------------------------- #

    def _table_exists(self, name: str) -> bool:
        return self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)) is not None

    def _row(self, invoice_id: Any) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM ap_invoices WHERE id=?", (invoice_id,)) if isinstance(invoice_id, str) else None
        if row is None:
            raise APIntakeError(f"unknown supplier invoice {invoice_id}")
        return row

    def _project(self, project_id: Any) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM projects WHERE id=?", (project_id,)) if isinstance(project_id, str) else None
        if row is None:
            raise APIntakeError(f"unknown project {project_id}")
        return row

    def _supplier(self, supplier_id: Any) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM parties WHERE id=?", (supplier_id,)) if isinstance(supplier_id, str) else None
        if row is None:
            raise APIntakeError(f"unknown party {supplier_id}")
        if row["kind"] != "supplier":
            raise APIntakeError(f"supplier invoices come from supplier parties; {supplier_id} is a {row['kind']}")
        return row

    def _commitment(self, commitment_id: Any, *, project_id: str, supplier_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT id FROM commitments WHERE id=?", (commitment_id,)) if isinstance(commitment_id, str) else None
        if row is None:
            raise APIntakeError(f"unknown commitment {commitment_id}")
        c = self.c.commitments.get(commitment_id)
        if c["project_id"] != project_id:
            raise APIntakeError(f"commitment {commitment_id} belongs to another project")
        if c["supplier_id"] != supplier_id:
            raise APIntakeError(f"commitment {commitment_id} is with another supplier; an invoice bills its own supplier's commitment")
        return c

    def _current_revision(self, document_id: str | None) -> dict[str, Any] | None:
        if not document_id:
            return None
        return self.db.one("SELECT id, document_id, revision, content_hash FROM document_revisions WHERE document_id=? ORDER BY revision DESC LIMIT 1", (document_id,))

    def _resolve_evidence(self, conn, project_id: str, evidence_hash: Any, *, other_than: str | None = None) -> dict[str, Any]:
        """The current revision of a ``supplier_invoice`` document on the project carrying
        ``evidence_hash`` that backs no other live invoice."""
        if not isinstance(evidence_hash, str) or not evidence_hash.strip():
            raise APIntakeError("a supplier invoice requires the content hash of its invoice document (the PDF)")
        rows = self.db.query(
            """SELECT r.id, r.document_id, r.revision, r.content_hash, d.project_id, d.kind FROM document_revisions r
               JOIN documents d ON d.id = r.document_id WHERE r.content_hash=? ORDER BY r.created_at, r.id""",
            (evidence_hash.strip(),),
        )
        if not rows:
            raise APIntakeError("the evidence hash matches no stored document revision; register the supplier invoice document first")
        rows = [r for r in rows if r["project_id"] == project_id]
        if not rows:
            raise APIntakeError(f"the invoice document belongs to another project; register it on project {project_id}")
        rows = [r for r in rows if r["kind"] == SUPPLIER_INVOICE_KIND]
        if not rows:
            raise APIntakeError(f"a supplier invoice is backed only by a '{SUPPLIER_INVOICE_KIND}' document")
        current = [r for r in rows if (self._current_revision(r["document_id"]) or {}).get("id") == r["id"]]
        if not current:
            raise APIntakeError(f"the evidence hash matches a superseded revision of document {rows[-1]['document_id']}; bind the current revision")
        if len(current) > 1:
            raise APIntakeError("the evidence hash matches the current revision of several invoice documents; register distinct documents")
        rev = current[0]
        taken = conn.execute("SELECT id, invoice_number FROM ap_invoices WHERE evidence_document_id=? AND status != 'rejected' AND id IS NOT ?",
                             (rev["document_id"], other_than)).fetchone()
        if taken is not None:
            raise APIntakeError(f"invoice document {rev['document_id']} already supports supplier invoice {taken['invoice_number']} ({taken['id']})")
        return rev

    def _lines(self, lines: Any, *, amount: Decimal, project_id: str, commitment: dict[str, Any] | None) -> list[dict[str, Any]]:
        if lines is None:
            lines = ()
        if not isinstance(lines, (list, tuple)):
            raise APIntakeError("lines must be a list of {description, amount, quantity, unit_price, sov_line_id | equipment_id}")
        if len(lines) > MAX_LINES:
            raise APIntakeError(f"an invoice carries at most {MAX_LINES} lines")
        sov_ids = {s["id"] for s in commitment["sov"]} if commitment else set()
        has_equipment = self._table_exists("procurement_equipment")
        out: list[dict[str, Any]] = []
        seen_equipment: set[str] = set()
        for n, ln in enumerate(lines, start=1):
            if not isinstance(ln, dict):
                raise APIntakeError(f"line {n} must be a mapping")
            unknown = sorted(set(ln) - set(LINE_KEYS))
            if unknown:
                raise APIntakeError(f"line {n} has unknown field(s) {', '.join(unknown)}")
            description = _text(ln.get("description"), f"line {n} description")
            amt = _amount(ln.get("amount"), f"line {n} amount")
            quantity = unit_price = None
            if ln.get("quantity") is not None or ln.get("unit_price") is not None:
                if ln.get("quantity") is None or ln.get("unit_price") is None:
                    raise APIntakeError(f"line {n} gives a quantity or a unit price without the other")
                qty = _decimal(ln["quantity"], f"line {n} quantity")
                price = _decimal(ln["unit_price"], f"line {n} unit price")
                if qty <= 0 or price < 0:
                    raise APIntakeError(f"line {n} needs a positive quantity and a non-negative unit price")
                if money(qty * price) != amt:
                    raise APIntakeError(f"line {n}: quantity {qty:f} x unit price {price:f} = {fmt(money(qty * price))}, not the line amount {fmt(amt)}")
                quantity, unit_price = f"{qty:f}", f"{price:f}"
            sov_line_id, equipment_id = ln.get("sov_line_id"), ln.get("equipment_id")
            if sov_line_id is not None and equipment_id is not None:
                raise APIntakeError(f"line {n} names both an SOV line and equipment; it bills one of them")
            if sov_line_id is not None:
                if commitment is None:
                    raise APIntakeError(f"line {n} names SOV line {sov_line_id} but the invoice names no commitment")
                if sov_line_id not in sov_ids:
                    raise APIntakeError(f"line {n}: SOV line {sov_line_id} does not belong to commitment {commitment['id']}")
            if equipment_id is not None:
                eq = self.db.one("SELECT id, project_id FROM procurement_equipment WHERE id=?", (equipment_id,)) if has_equipment and isinstance(equipment_id, str) else None
                if eq is None or eq["project_id"] != project_id:
                    raise APIntakeError(f"line {n}: equipment {equipment_id} is not registered on project {project_id}")
                if equipment_id in seen_equipment:
                    raise APIntakeError(f"line {n}: equipment {equipment_id} is billed twice on the invoice")
                seen_equipment.add(equipment_id)
            out.append({"line_no": n, "description": description, "quantity": quantity, "unit_price": unit_price, "amount": fmt(amt),
                        "sov_line_id": sov_line_id, "equipment_id": equipment_id})
        if out and total(ln["amount"] for ln in out) != amount:
            raise APIntakeError(f"the lines add up to {fmt(total(ln['amount'] for ln in out))}, not the invoice amount {fmt(amount)}")
        return out

    @staticmethod
    def _content_hash(row: dict[str, Any]) -> str:
        keys = ("id", "version", "project_id", "supplier_id", "commitment_id", "invoice_number", "number_key", "invoice_date", "due_date", "terms_days",
                "amount", "service_period_start", "service_period_end", "evidence_hash", "evidence_document_id", "evidence_revision_id")
        return hash_json({**{k: row.get(k) for k in keys}, "lines": loads(row["lines_json"])})

    @staticmethod
    def _service_period(start: Any, end: Any) -> tuple[str | None, str | None]:
        if start is None and end is None:
            return None, None
        if start is None or end is None:
            raise APIntakeError("a service period needs both its start and its end")
        if _date(start, "service_period_start") > _date(end, "service_period_end"):
            raise APIntakeError(f"service period {start}..{end} ends before it starts")
        return start, end

    def _near_duplicates(self, conn, *, supplier_id: str, amount: Decimal, invoice_date: _dt.date, number_key: str, other_than: str | None) -> list[str]:
        rows = conn.execute("SELECT id, number_key, invoice_date, amount FROM ap_invoices WHERE supplier_id=? AND status != 'rejected' AND id IS NOT ?",
                            (supplier_id, other_than)).fetchall()
        return sorted(r["id"] for r in rows if r["number_key"] != number_key and money(r["amount"]) == amount
                      and abs((_dt.date.fromisoformat(r["invoice_date"]) - invoice_date).days) <= NEAR_DUPLICATE_DAYS)

    # ---- payment terms ---------------------------------------------------------------- #

    def set_terms(self, supplier_id: str, days: int, actor: str) -> dict[str, Any]:
        """Record a supplier's payment terms in days (0..365); invoices received later
        default their due date to the invoice date plus these days."""
        who = _text(actor, "actor")
        if isinstance(days, bool) or not isinstance(days, int) or days < 0 or days > MAX_TERMS_DAYS:
            raise APIntakeError(f"payment terms are a whole number of days between 0 and {MAX_TERMS_DAYS}, got {days!r}")
        with self.db.transaction() as conn:
            self._supplier(supplier_id)
            existing = conn.execute("SELECT * FROM ap_supplier_terms WHERE supplier_id=?", (supplier_id,)).fetchone()
            now = utcnow_iso()
            if existing is None:
                version = 1
                conn.execute("INSERT INTO ap_supplier_terms (supplier_id, days, version, set_by, set_at) VALUES (?,?,1,?,?)", (supplier_id, days, who, now))
            else:
                if existing["days"] == days:
                    raise APIntakeError(f"supplier {supplier_id} is already on {days}-day terms")
                version = existing["version"] + 1
                conn.execute("UPDATE ap_supplier_terms SET days=?, version=?, set_by=?, set_at=? WHERE supplier_id=?", (days, version, who, now, supplier_id))
            self.audit.record(who, "ap_intake.terms_set", "party", supplier_id, {"days": days, "version": version,
                                                                                  "previous_days": existing["days"] if existing else None})
        return {"supplier_id": supplier_id, "days": days, "version": version}

    def terms(self, supplier_id: str) -> int:
        row = self.db.one("SELECT days FROM ap_supplier_terms WHERE supplier_id=?", (supplier_id,))
        return row["days"] if row else DEFAULT_TERMS_DAYS

    # ---- intake --------------------------------------------------------------------------- #

    def receive_invoice(self, supplier_id: str, invoice_number: str, invoice_date: str, amount: Any, evidence_hash: str, actor: str, *,
                        project_id: str, commitment_id: str | None = None, due_date: str | None = None,
                        service_period_start: str | None = None, service_period_end: str | None = None, lines=()) -> dict[str, Any]:
        """Receive a supplier invoice (see the module docstring for the rules).  The same
        supplier and normalized number is refused (``DuplicateInvoiceError``); a near
        duplicate is accepted with ``possible_duplicate`` set."""
        who = _text(actor, "actor")
        number, key = _invoice_number(invoice_number)
        inv_date = _date(invoice_date, "invoice_date")
        amt = _amount(amount, "invoice amount")
        sp_start, sp_end = self._service_period(service_period_start, service_period_end)
        invoice_id = new_id("apinv")
        with self.db.transaction() as conn:
            self._project(project_id)
            self._supplier(supplier_id)
            commitment = self._commitment(commitment_id, project_id=project_id, supplier_id=supplier_id) if commitment_id is not None else None
            clean = self._lines(lines, amount=amt, project_id=project_id, commitment=commitment)
            dup = conn.execute("SELECT id, invoice_number, status FROM ap_invoices WHERE supplier_id=? AND number_key=?", (supplier_id, key)).fetchone()
            if dup is not None:
                raise DuplicateInvoiceError(
                    f"duplicate supplier invoice: {number!r} is the same number as invoice {dup['invoice_number']!r} ({dup['id']}, {dup['status']}) "
                    "from this supplier; revise that invoice instead of receiving it again"
                )
            rev = self._resolve_evidence(conn, project_id, evidence_hash)
            if due_date is not None:
                due, terms_days = _date(due_date, "due_date"), None
            else:
                terms_days = self.terms(supplier_id)
                due = inv_date + _dt.timedelta(days=terms_days)
            if due < inv_date:
                raise APIntakeError(f"due date {due.isoformat()} is before the invoice date {inv_date.isoformat()}")
            near = self._near_duplicates(conn, supplier_id=supplier_id, amount=amt, invoice_date=inv_date, number_key=key, other_than=None)
            now = utcnow_iso()
            row = {
                "id": invoice_id, "version": 1, "project_id": project_id, "supplier_id": supplier_id, "commitment_id": commitment_id,
                "invoice_number": number, "number_key": key, "invoice_date": inv_date.isoformat(), "due_date": due.isoformat(), "terms_days": terms_days,
                "amount": fmt(amt), "service_period_start": sp_start, "service_period_end": sp_end, "evidence_hash": rev["content_hash"],
                "evidence_document_id": rev["document_id"], "evidence_revision_id": rev["id"], "lines_json": canonical_json(clean),
            }
            row["content_hash"] = self._content_hash(row)
            # audited first: the storage guard admits an invoice only with its audit entry
            self.audit.record(who, "ap_intake.invoice_received", INVOICE_SUBJECT, invoice_id, {
                "project_id": project_id, "supplier_id": supplier_id, "commitment_id": commitment_id, "invoice_number": number, "number_key": key,
                "invoice_date": row["invoice_date"], "due_date": row["due_date"], "terms_days": terms_days, "amount": row["amount"],
                "evidence_hash": rev["content_hash"], "evidence_revision_id": rev["id"], "lines": len(clean), "content_hash": row["content_hash"],
                "possible_duplicate": 1 if near else 0, "possible_duplicate_of": near,
            })
            conn.execute(
                """INSERT INTO ap_invoices (id, project_id, supplier_id, commitment_id, invoice_number, number_key, invoice_date, due_date, terms_days, amount,
                   service_period_start, service_period_end, evidence_hash, evidence_document_id, evidence_revision_id, lines_json, content_hash, version,
                   status, possible_duplicate, duplicate_of_json, created_by, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,'received',?,?,?,?,?)""",
                (invoice_id, project_id, supplier_id, commitment_id, number, key, row["invoice_date"], row["due_date"], terms_days, row["amount"],
                 sp_start, sp_end, rev["content_hash"], rev["document_id"], rev["id"], row["lines_json"], row["content_hash"],
                 1 if near else 0, canonical_json(near), who, now, now),
            )
        return self.invoice(invoice_id)

    def revise_invoice(self, invoice_id: str, actor: str, *, reason: str, invoice_number: str | None = None, invoice_date: str | None = None,
                       amount: Any = None, evidence_hash: str | None = None, due_date: str | None = None, lines=None,
                       service_period_start: str | None = None, service_period_end: str | None = None) -> dict[str, Any]:
        """Replace the facts of a received or matched invoice (the supplier reissued it).
        The invoice moves to its next version and back to ``received``: its match must be
        computed and approved again, open approvals on it are invalidated, and a bill it
        was attached to can no longer be approved or posted until the revised invoice is
        matched again.  Duplicate checks run again on the revised facts."""
        who = _text(actor, "actor")
        why = _text(reason, "a revision reason")
        with self.db.transaction() as conn:
            inv = self._row(invoice_id)
            if inv["status"] == "rejected":
                raise APIntakeError(f"supplier invoice {inv['invoice_number']} was rejected; a rejected invoice is final")
            tampered = self._integrity_problem(inv)
            if tampered:  # a revision would re-hash (and so launder) facts nobody recorded
                raise APIntakeError(f"{tampered}; investigate it against the audit trail before revising")
            new = dict(inv)
            changes: dict[str, Any] = {}
            if invoice_number is not None:
                number, key = _invoice_number(invoice_number)
                if number != inv["invoice_number"]:
                    new["invoice_number"], new["number_key"] = number, key
                    changes["invoice_number"] = number
            if invoice_date is not None and _date(invoice_date, "invoice_date").isoformat() != inv["invoice_date"]:
                new["invoice_date"] = invoice_date
                changes["invoice_date"] = invoice_date
            if amount is not None:
                amt = _amount(amount, "invoice amount")
                if fmt(amt) != inv["amount"]:
                    new["amount"] = fmt(amt)
                    changes["amount"] = fmt(amt)
            inv_date = _dt.date.fromisoformat(new["invoice_date"])
            if due_date is not None:
                due = _date(due_date, "due_date")
                if due.isoformat() != inv["due_date"] or inv["terms_days"] is not None:
                    new["due_date"], new["terms_days"] = due.isoformat(), None
                    changes["due_date"] = due.isoformat()
            elif inv["terms_days"] is not None and "invoice_date" in changes:
                new["due_date"] = (inv_date + _dt.timedelta(days=inv["terms_days"])).isoformat()
                changes["due_date"] = new["due_date"]
            if new["due_date"] < new["invoice_date"]:
                raise APIntakeError(f"due date {new['due_date']} is before the invoice date {new['invoice_date']}")
            if service_period_start is not None or service_period_end is not None:
                sp = self._service_period(service_period_start, service_period_end)
                if sp != (inv["service_period_start"], inv["service_period_end"]):
                    new["service_period_start"], new["service_period_end"] = sp
                    changes["service_period"] = list(sp)
            if evidence_hash is not None:
                rev = self._resolve_evidence(conn, inv["project_id"], evidence_hash, other_than=invoice_id)
                if rev["id"] != inv["evidence_revision_id"]:
                    new["evidence_hash"], new["evidence_document_id"], new["evidence_revision_id"] = rev["content_hash"], rev["document_id"], rev["id"]
                    changes["evidence_revision_id"] = rev["id"]
            commitment = (self._commitment(inv["commitment_id"], project_id=inv["project_id"], supplier_id=inv["supplier_id"])
                          if inv["commitment_id"] else None)
            if lines is not None:
                clean = self._lines(lines, amount=money(new["amount"]), project_id=inv["project_id"], commitment=commitment)
                if canonical_json(clean) != inv["lines_json"]:
                    new["lines_json"] = canonical_json(clean)
                    changes["lines"] = len(clean)
            elif "amount" in changes and loads(inv["lines_json"]):
                raise APIntakeError("the invoice has lines; revise the lines together with the amount")
            if not changes:
                raise APIntakeError(f"revision of supplier invoice {inv['invoice_number']} changes nothing")
            if new["number_key"] != inv["number_key"]:
                dup = conn.execute("SELECT id, invoice_number FROM ap_invoices WHERE supplier_id=? AND number_key=? AND id != ?",
                                   (inv["supplier_id"], new["number_key"], invoice_id)).fetchone()
                if dup is not None:
                    raise DuplicateInvoiceError(f"duplicate supplier invoice: {new['invoice_number']!r} is the same number as {dup['invoice_number']!r} ({dup['id']})")
            new["version"] = inv["version"] + 1
            new["content_hash"] = self._content_hash(new)
            dup_facts_changed = (new["number_key"], new["amount"], new["invoice_date"]) != (inv["number_key"], inv["amount"], inv["invoice_date"])
            if dup_facts_changed:
                near = self._near_duplicates(conn, supplier_id=inv["supplier_id"], amount=money(new["amount"]), invoice_date=inv_date,
                                             number_key=new["number_key"], other_than=invoice_id)
                flag, near_json, cleared = (1 if near else 0), canonical_json(near), (None, None, None)
            else:
                near = loads(inv["duplicate_of_json"])
                flag, near_json = inv["possible_duplicate"], inv["duplicate_of_json"]
                cleared = (inv["duplicate_cleared_by"], inv["duplicate_cleared_at"], inv["duplicate_clear_reason"])
            now = utcnow_iso()
            invalidated = self.approvals.invalidate_for_subject(INVOICE_SUBJECT, invoice_id, reason=f"invoice revised to version {new['version']}: {why}", actor=who)
            # audited first: the storage guard admits a new version only with its audit entry
            self.audit.record(who, "ap_intake.invoice_revised", INVOICE_SUBJECT, invoice_id, {
                "reason": why, "changes": changes, "version": new["version"], "previous_status": inv["status"], "content_hash": new["content_hash"],
                "amount": new["amount"], "possible_duplicate": flag, "possible_duplicate_of": near, "approvals_invalidated": invalidated,
                "attached_bill_id": inv["matched_bill_id"],
            })
            cur = conn.execute(
                """UPDATE ap_invoices SET invoice_number=?, number_key=?, invoice_date=?, due_date=?, terms_days=?, amount=?, service_period_start=?,
                   service_period_end=?, evidence_hash=?, evidence_document_id=?, evidence_revision_id=?, lines_json=?, content_hash=?, version=?,
                   status='received', possible_duplicate=?, duplicate_of_json=?, duplicate_cleared_by=?, duplicate_cleared_at=?, duplicate_clear_reason=?,
                   match_status=NULL, match_basis=NULL, match_exceptions_json='[]', match_attempt_id=NULL, updated_at=?
                   WHERE id=? AND version=?""",
                (new["invoice_number"], new["number_key"], new["invoice_date"], new["due_date"], new["terms_days"], new["amount"], new["service_period_start"],
                 new["service_period_end"], new["evidence_hash"], new["evidence_document_id"], new["evidence_revision_id"], new["lines_json"], new["content_hash"],
                 new["version"], flag, near_json, *cleared, now, invoice_id, inv["version"]),
            )
            if cur.rowcount != 1:
                raise APIntakeError(f"supplier invoice {invoice_id} changed concurrently; retry")
        return self.invoice(invoice_id)

    def clear_duplicate_flag(self, invoice_id: str, reason: str, actor: str) -> dict[str, Any]:
        """Record the review of a possible duplicate: the invoice is genuine and may be matched."""
        who = _text(actor, "actor")
        why = _text(reason, "a review reason")
        with self.db.transaction() as conn:
            inv = self._row(invoice_id)
            if inv["status"] != "received":
                raise APIntakeError(f"supplier invoice {inv['invoice_number']} is {inv['status']}")
            if not inv["possible_duplicate"]:
                raise APIntakeError(f"supplier invoice {inv['invoice_number']} is not flagged as a possible duplicate")
            if inv["duplicate_cleared_at"]:
                raise APIntakeError(f"the possible-duplicate flag on {inv['invoice_number']} was already cleared by {inv['duplicate_cleared_by']}")
            now = utcnow_iso()
            # audited first: the storage guard admits a review only with its audit entry
            self.audit.record(who, "ap_intake.duplicate_flag_cleared", INVOICE_SUBJECT, invoice_id, {
                "reason": why, "cleared_by": who, "cleared_at": now, "possible_duplicate_of": loads(inv["duplicate_of_json"]), "version": inv["version"],
            })
            conn.execute("UPDATE ap_invoices SET duplicate_cleared_by=?, duplicate_cleared_at=?, duplicate_clear_reason=?, updated_at=? WHERE id=?",
                         (who, now, why, now, invoice_id))
        return self.invoice(invoice_id)

    def reject_invoice(self, invoice_id: str, reason: str, actor: str) -> dict[str, Any]:
        """Reject a received invoice (a confirmed duplicate, or not owed).  Final; its number
        stays taken, and open approvals on it are invalidated."""
        who = _text(actor, "actor")
        why = _text(reason, "a rejection reason")
        with self.db.transaction() as conn:
            inv = self._row(invoice_id)
            if inv["status"] != "received":
                raise APIntakeError(f"supplier invoice {inv['invoice_number']} is {inv['status']}; only a received (unmatched) invoice is rejected")
            now = utcnow_iso()
            invalidated = self.approvals.invalidate_for_subject(INVOICE_SUBJECT, invoice_id, reason=f"invoice rejected: {why}", actor=who)
            # audited first: the storage guard admits a rejection only with its audit entry
            self.audit.record(who, "ap_intake.invoice_rejected", INVOICE_SUBJECT, invoice_id, {
                "reason": why, "rejected_at": now, "version": inv["version"], "approvals_invalidated": invalidated,
            })
            conn.execute("UPDATE ap_invoices SET status='rejected', rejected_by=?, rejected_at=?, reject_reason=?, updated_at=? WHERE id=?",
                         (who, now, why, now, invoice_id))
        return self.invoice(invoice_id)

    # ---- reading -------------------------------------------------------------------------- #

    def _latest_attempt(self, invoice_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM ap_invoice_matches WHERE invoice_id=? ORDER BY rowid DESC LIMIT 1", (invoice_id,))
        if row is not None:
            row["exceptions"] = loads(row.pop("exceptions_json"))
            row["result"] = loads(row.pop("result_json"))
        return row

    def _orphaned(self, inv: dict[str, Any]) -> bool:
        """A matched invoice whose bill was voided or corrected since: no payable backs it,
        so it counts as unmatched (state, close checks) until ``match`` reopens it."""
        if inv["status"] != "matched" or not inv["matched_bill_id"]:
            return False
        status = self.db.scalar("SELECT status FROM bills WHERE id=?", (inv["matched_bill_id"],))
        return status in ("void", "corrected")

    def _unmatched(self, inv: dict[str, Any]) -> bool:
        """Received, or matched to a bill that was voided or corrected since."""
        return inv["status"] == "received" or self._orphaned(inv)

    def _integrity_problem(self, inv: dict[str, Any]) -> str | None:
        """Why the stored invoice is not the record the intake wrote (None when it is): its
        facts no longer hash to its content hash, or its duplicate flag disagrees with the
        invoices it was found to resemble."""
        if self._content_hash(inv) != inv["content_hash"]:
            return (f"supplier invoice {inv['invoice_number']} ({inv['id']}) does not hash to its recorded content hash: "
                    "its stored facts were changed outside the intake")
        if bool(inv["possible_duplicate"]) != bool(loads(inv["duplicate_of_json"])):
            return (f"supplier invoice {inv['invoice_number']} ({inv['id']}) carries a possible-duplicate flag that disagrees with the invoices "
                    "it was found to resemble: its duplicate review was changed outside the intake")
        return None

    def _attached_bill(self, inv: dict[str, Any]) -> dict[str, Any] | None:
        """The live (draft, approved, posted or paid) bill that carries this invoice, if any.
        An invoice attached to a live bill is matched only to that bill again, until another
        invoice replaces it there (one invoice, one live bill)."""
        if not self._table_exists("bills"):
            return None
        return self.db.one("SELECT id, sequence, status, amount_due FROM bills WHERE supplier_invoice_id=? AND status IN ('draft','approved','posted','paid') "
                           "ORDER BY sequence LIMIT 1", (inv["id"],))

    def invoice(self, invoice_id: str) -> dict[str, Any]:
        inv = self._row(invoice_id)
        out = dict(inv)
        out["lines"] = loads(out.pop("lines_json"))
        out["duplicate_of"] = loads(out.pop("duplicate_of_json"))
        out["match_exceptions"] = loads(out.pop("match_exceptions_json"))
        out["possible_duplicate"] = bool(inv["possible_duplicate"])
        out["duplicate_blocking"] = bool(inv["possible_duplicate"]) and not inv["duplicate_cleared_at"]
        rev = self._current_revision(inv["evidence_document_id"])
        out["evidence_current"] = rev is not None and rev["id"] == inv["evidence_revision_id"]
        out["latest_match"] = self._latest_attempt(invoice_id)
        out["orphaned_match"] = self._orphaned(inv)
        out["unmatched"] = self._unmatched(inv)
        attached = self._attached_bill(inv)
        out["attached_bill_id"] = attached["id"] if attached else None
        out["integrity_problem"] = self._integrity_problem(inv)
        out["overdue"] = out["unmatched"] and inv["due_date"] < _today().isoformat()
        return out

    def invoices(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id:
            rows = self.db.query("SELECT id FROM ap_invoices WHERE project_id=? ORDER BY created_at, id", (project_id,))
        else:
            rows = self.db.query("SELECT id FROM ap_invoices ORDER BY created_at, id")
        return [self.invoice(r["id"]) for r in rows]

    # ---- 3-way match ------------------------------------------------------------------------ #

    def _award_for(self, inv: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any] | None:
        """The procurement award behind the invoice: the award that drafted its commitment,
        else the award of the first equipment line's requisition (no commitment named)."""
        if not self._table_exists("procurement_awards"):
            return None
        if inv["commitment_id"]:
            return self.db.one("SELECT * FROM procurement_awards WHERE commitment_id=?", (inv["commitment_id"],))
        for ln in lines:
            if ln.get("equipment_id"):
                req = self.db.scalar("SELECT requisition_id FROM procurement_equipment WHERE id=?", (ln["equipment_id"],))
                award = self.db.one("SELECT * FROM procurement_awards WHERE requisition_id=?", (req,)) if req else None
                if award is not None:
                    return award
        return None

    def _po_lines(self, award: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Equipment on the purchase order -> its PO (SOV) line: the award drafted one line per
        equipment item, in the requisition's order."""
        req = self.db.one("SELECT equipment_json FROM procurement_requisitions WHERE id=?", (award["requisition_id"],))
        equipment = loads(req["equipment_json"]) if req else []
        sov = self.db.query("SELECT id, line_no, description, amount FROM sov_lines WHERE commitment_id=? ORDER BY line_no", (award["commitment_id"],))
        out: dict[str, dict[str, Any]] = {}
        for idx, eid in enumerate(equipment):
            if idx >= len(sov):
                break
            tag = self.db.scalar("SELECT tag FROM procurement_equipment WHERE id=?", (eid,)) or eid
            out[eid] = {"equipment_id": eid, "tag": tag, "sov_line_id": sov[idx]["id"], "line_no": sov[idx]["line_no"], "amount": sov[idx]["amount"]}
        return out

    def _commitment_facts(self, commitment_id: str | None) -> dict[str, Any] | None:
        if not commitment_id:
            return None
        c = self.db.one("SELECT id, version, status, executed_amount, supplier_id, project_id FROM commitments WHERE id=?", (commitment_id,))
        if c is None:
            return None
        return {"id": c["id"], "version": c["version"], "status": c["status"], "executed_amount": c["executed_amount"]}

    def _invoiced_to_date(self, commitment_id: str, *, other_than: str) -> Decimal:
        rows = self.db.query(
            """SELECT i.amount FROM ap_invoices i LEFT JOIN bills b ON b.id = i.matched_bill_id
               WHERE i.status = 'matched' AND i.matched_commitment_id = ? AND i.id != ? AND COALESCE(b.status, '') NOT IN ('void','corrected')""",
            (commitment_id, other_than),
        )
        return total(r["amount"] for r in rows) if rows else ZERO

    def _equipment_invoiced(self, *, other_than: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for r in self.db.query("SELECT id, invoice_number, lines_json FROM ap_invoices WHERE status='matched' AND match_basis=? AND id != ?",
                               (BASIS_PURCHASE_ORDER, other_than)):
            for ln in loads(r["lines_json"]):
                if ln.get("equipment_id"):
                    out[ln["equipment_id"]] = r["invoice_number"]
        return out

    def _candidate_bills(self, inv: dict[str, Any], commitment_id: str) -> tuple[list[dict[str, Any]], list[str]]:
        """Certified (draft or posted) bills of the commitment that can take this invoice:
        not stale, and not carrying a link to another invoice that still holds (a link to a
        rejected invoice, or to one revised since it was attached, leaves the bill free).  An
        invoice attached to a live bill can take only that bill (one invoice, one live bill)."""
        out, notes = [], []
        attached = self._attached_bill(inv)
        if attached is not None and attached["status"] not in ("draft", "approved", "posted"):
            notes.append(f"the invoice is attached to bill {attached['sequence']} ({attached['id']}, {attached['status']})")
        for r in self.db.query("SELECT id FROM bills WHERE commitment_id=? AND status IN ('draft','approved','posted') ORDER BY sequence", (commitment_id,)):
            b = self.c.bills.get(r["id"])
            if attached is not None and b["id"] != attached["id"]:
                notes.append(f"bill {b['sequence']} is not bill {attached['sequence']} ({attached['id']}), which carries this invoice; "
                             "the invoice moves only once another invoice replaces it there")
                continue
            if b["status"] == "draft" and b["stale"]:
                notes.append(f"bill {b['sequence']} is stale ({', '.join(b['stale_reasons'])})")
                continue
            linked = b.get("supplier_invoice_id")
            if linked and linked != inv["id"] and self.c.bills.supplier_invoice_link_holds(b):
                notes.append(f"bill {b['sequence']} is linked to another invoice")
                continue
            out.append(b)
        return out, notes

    @staticmethod
    def _bill_facts(b: dict[str, Any]) -> dict[str, Any]:
        return {"id": b["id"], "sequence": b["sequence"], "content_hash": b["content_hash"], "status": b["status"], "amount_due": b["amount_due"],
                "commitment_id": b["commitment_id"], "supplier_invoice_id": b.get("supplier_invoice_id")}

    def _facts(self, inv: dict[str, Any]) -> dict[str, Any]:
        """The deterministic match of the invoice against current state."""
        details: list[dict[str, str]] = []

        def exc(code: str, detail: str) -> None:
            details.append({"code": code, "detail": detail})

        lines = loads(inv["lines_json"])
        amount = money(inv["amount"])
        if inv["possible_duplicate"] and not inv["duplicate_cleared_at"]:
            exc("possible_duplicate", f"possible duplicate of {', '.join(loads(inv['duplicate_of_json']))}; review it with clear_duplicate_flag or reject it")
        rev = self._current_revision(inv["evidence_document_id"])
        if rev is None or rev["id"] != inv["evidence_revision_id"]:
            exc("evidence_stale", f"invoice document {inv['evidence_document_id']} has revision {rev['revision'] if rev else '?'} newer than the one bound; "
                                  "revise the invoice to bind it")
        award = self._award_for(inv, lines)
        basis = BASIS_PURCHASE_ORDER if award is not None else BASIS_PROGRESS
        commitment = self._commitment_facts(award["commitment_id"] if award is not None else inv["commitment_id"])
        bill = None
        receipts: list[dict[str, Any]] = []
        po_lines: list[dict[str, Any]] = []
        matched_amount = None
        if basis == BASIS_PROGRESS:
            if commitment is None:
                exc("no_certified_bill", "the invoice names no commitment; a progress invoice is matched to a certified bill of its commitment")
            else:
                candidates, notes = self._candidate_bills(inv, commitment["id"])
                if not candidates:
                    exc("no_certified_bill", f"commitment {commitment['id']} has no certified (draft or posted) bill free for this invoice"
                                             + (f" ({'; '.join(notes)})" if notes else ""))
                else:
                    exact = [b for b in candidates if money(b["amount_due"]) == amount]
                    exact.sort(key=lambda b: (b.get("supplier_invoice_id") != inv["id"], b["sequence"]))
                    if exact:
                        bill = self._bill_facts(exact[0])
                        matched_amount = bill["amount_due"]
                    else:
                        attached = self._attached_bill(inv)
                        exc("amount_mismatch", f"invoice {fmt(amount)} matches no certified bill: "
                                               + ", ".join(f"bill {b['sequence']} due {b['amount_due']}" for b in candidates)
                                               + (f" (the invoice is attached to bill {attached['sequence']} ({attached['id']}) and is matched only to it "
                                                  "until another invoice replaces it there)" if attached else ""))
        else:
            po = self._po_lines(award)
            elsewhere = self._equipment_invoiced(other_than=inv["id"])
            if not lines:
                exc("not_received", "a purchase-order invoice lists the received equipment it bills; this one has no lines")
            po_total = ZERO
            for ln in lines:
                n, eid = ln["line_no"], ln.get("equipment_id")
                if not eid:
                    exc("not_received", f"line {n} names no equipment received on the purchase order")
                    continue
                if eid not in po:
                    exc("over_commitment", f"line {n}: equipment {eid} is not on purchase order {award['commitment_id']}")
                    continue
                line = po[eid]
                receipt = self.db.one("SELECT id, condition, received_date FROM procurement_receipts WHERE equipment_id=?", (eid,))
                if receipt is None:
                    exc("not_received", f"line {n}: equipment {line['tag']} has not been received")
                elif receipt["condition"] != "ok":
                    exc("damaged_receipt", f"line {n}: equipment {line['tag']} was received {receipt['condition']} (receipt {receipt['id']})")
                else:
                    receipts.append({"receipt_id": receipt["id"], "equipment_id": eid, "condition": receipt["condition"], "received_date": receipt["received_date"]})
                if eid in elsewhere:
                    exc("over_commitment", f"line {n}: equipment {line['tag']} is already invoiced on {elsewhere[eid]}")
                if money(ln["amount"]) != money(line["amount"]):
                    exc("amount_mismatch", f"line {n}: invoiced {ln['amount']} for {line['tag']}, the purchase order line is {line['amount']}")
                po_total += money(line["amount"])
                po_lines.append({"equipment_id": eid, "tag": line["tag"], "sov_line_id": line["sov_line_id"], "po_amount": line["amount"], "invoiced": ln["amount"]})
            if lines and money(po_total) != amount:
                exc("amount_mismatch", f"invoice {fmt(amount)} against purchase order lines of {fmt(po_total)} for the equipment it bills (tolerance 0.00)")
            matched_amount = fmt(po_total) if lines else None
            if commitment is not None and commitment["status"] not in ("executed", "closed"):
                exc("over_commitment", f"purchase order {commitment['id']} is {commitment['status']}; nothing is authorized until it is executed")
            if commitment is not None:
                candidates, _ = self._candidate_bills(inv, commitment["id"])
                exact = sorted((b for b in candidates if money(b["amount_due"]) == amount),
                               key=lambda b: (b.get("supplier_invoice_id") != inv["id"], b["sequence"]))
                bill = self._bill_facts(exact[0]) if exact else None
            attached = self._attached_bill(inv)
            if attached is not None and (bill is None or bill["id"] != attached["id"]):
                # it stays on the bill that carries it: matching it elsewhere (or nowhere) would leave that link behind
                exc("amount_mismatch", f"the invoice is attached to bill {attached['sequence']} ({attached['id']}, {attached['status']}, due {attached['amount_due']}); "
                                       f"invoice {fmt(amount)} no longer matches it, and it moves only once another invoice replaces it there")
        invoiced = ZERO
        if commitment is not None:
            authorized = money(commitment["executed_amount"]) if commitment["status"] in ("executed", "closed") else ZERO
            invoiced = self._invoiced_to_date(commitment["id"], other_than=inv["id"])
            if invoiced + amount > authorized and not (basis == BASIS_PURCHASE_ORDER and commitment["status"] not in ("executed", "closed")):
                exc("over_commitment", f"invoices matched on commitment {commitment['id']} ({fmt(invoiced)}) plus this one ({fmt(amount)}) "
                                       f"exceed its executed amount {fmt(authorized)}")
        codes = sorted({d["code"] for d in details})
        return {
            "basis": basis,
            "status": "exception" if codes else "matched",
            "exceptions": codes,
            "details": details,
            "invoice": {"id": inv["id"], "version": inv["version"], "content_hash": inv["content_hash"], "amount": inv["amount"]},
            "evidence": {"revision_id": inv["evidence_revision_id"], "current_revision_id": rev["id"] if rev else None},
            "commitment": commitment,
            "award_id": award["id"] if award is not None else None,
            "invoiced_to_date": fmt(invoiced),
            "bill": bill,
            "receipts": receipts,
            "po_lines": po_lines,
            "matched_amount": matched_amount,
        }

    def _reopen_reason(self, inv: dict[str, Any]) -> str | None:
        """Why a matched invoice is reopened by the next ``match`` (None when it is not):
        its bill was voided or corrected (it is matched to the replacement bill), or it was
        matched to purchase-order receipts before any bill of the PO existed and a certified
        bill of the PO is now due exactly its amount (the bill is linked under a new approval)."""
        if inv["status"] != "matched":
            return None
        if self._orphaned(inv):
            return "bill_" + str(self.db.scalar("SELECT status FROM bills WHERE id=?", (inv["matched_bill_id"],)))
        if inv["match_basis"] == BASIS_PURCHASE_ORDER and not inv["matched_bill_id"] and inv["matched_commitment_id"]:
            candidates, _ = self._candidate_bills(inv, inv["matched_commitment_id"])
            if any(money(b["amount_due"]) == money(inv["amount"]) for b in candidates):
                return "po_bill_certified"
        return None

    def _reopen(self, conn, inv: dict[str, Any], actor: str, reason: str) -> dict[str, Any]:
        """Reopen a matched invoice (next version, received) so it can be matched again."""
        new = dict(inv)
        new["version"] = inv["version"] + 1
        new["content_hash"] = self._content_hash(new)
        now = utcnow_iso()
        # audited first: the storage guard admits a new version only with its audit entry
        self.audit.record(actor, "ap_intake.match_reopened", INVOICE_SUBJECT, inv["id"], {
            "reason": reason, "bill_id": inv["matched_bill_id"], "commitment_id": inv["matched_commitment_id"], "version": new["version"],
            "content_hash": new["content_hash"], "amount": inv["amount"], "possible_duplicate": inv["possible_duplicate"],
            "previous_approval_id": inv["match_approval_id"],
        })
        cur = conn.execute(
            """UPDATE ap_invoices SET version=?, content_hash=?, status='received', match_status=NULL, match_basis=NULL, match_exceptions_json='[]',
               match_attempt_id=NULL, updated_at=? WHERE id=? AND version=?""",
            (new["version"], new["content_hash"], now, inv["id"], inv["version"]),
        )
        if cur.rowcount != 1:
            raise APIntakeError(f"supplier invoice {inv['id']} changed concurrently; retry")
        return self._row(inv["id"])

    def match(self, invoice_id: str, actor: str) -> dict[str, Any]:
        """Compute the 3-way match against current state and record it (``ap_invoice_matches``).
        Returns the computation: ``status`` matched | exception, ``exceptions`` codes with
        ``details``, the basis, the bill or receipts it matched.  Executing the match is the
        separate ``ap_intake.match_invoice`` approval.  A matched invoice whose bill was
        voided or corrected, or a purchase-order invoice matched before its PO bill existed
        once that bill is certified, is reopened first (see ``_reopen_reason``).  An invoice
        whose stored facts no longer hash to its content hash is refused."""
        who = _text(actor, "actor")
        with self.db.transaction() as conn:
            inv = self._row(invoice_id)
            tampered = self._integrity_problem(inv)
            if tampered:
                raise APIntakeError(f"{tampered}; it cannot be matched")
            reason = self._reopen_reason(inv)
            if reason:
                inv = self._reopen(conn, inv, who, reason)
            if inv["status"] == "matched":
                if inv["match_basis"] == BASIS_PURCHASE_ORDER and not inv["matched_bill_id"]:
                    raise APIntakeError(f"supplier invoice {inv['invoice_number']} is matched to its purchase-order receipts; it is linked to a bill once a "
                                        "certified bill of the purchase order is due exactly its amount (run match again then)")
                raise APIntakeError(f"supplier invoice {inv['invoice_number']} is already matched to bill {inv['matched_bill_id']}; revise it if the supplier replaced it")
            if inv["status"] == "rejected":
                raise APIntakeError(f"supplier invoice {inv['invoice_number']} was rejected")
            facts = self._facts(inv)
            attempt_id = new_id("apm")
            result_hash = hash_json(facts)
            now = utcnow_iso()
            # audited first: the storage guard admits a computation only with its audit entry
            self.audit.record(who, "ap_intake.match_computed", INVOICE_SUBJECT, invoice_id, {
                "attempt_id": attempt_id, "invoice_version": inv["version"], "basis": facts["basis"], "status": facts["status"],
                "exceptions": facts["exceptions"], "bill_id": (facts["bill"] or {}).get("id"), "receipts": [r["receipt_id"] for r in facts["receipts"]],
                "result_hash": result_hash, "reopened": reason,
            })
            conn.execute(
                """INSERT INTO ap_invoice_matches (id, invoice_id, invoice_version, basis, status, exceptions_json, result_json, result_hash, computed_by, computed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (attempt_id, invoice_id, inv["version"], facts["basis"], facts["status"], canonical_json(facts["exceptions"]), canonical_json(facts),
                 result_hash, who, now),
            )
            conn.execute("UPDATE ap_invoices SET match_status=?, match_basis=?, match_exceptions_json=?, match_attempt_id=?, updated_at=? WHERE id=?",
                         (facts["status"], facts["basis"], canonical_json(facts["exceptions"]), attempt_id, now, invoice_id))
        return {**facts, "attempt_id": attempt_id, "result_hash": result_hash, "invoice_id": invoice_id}

    # ---- approval-bound operation: ap_intake.match_invoice ---------------------------------------- #

    def _eligibility(self, inv: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, list[str]]:
        problems: list[str] = []
        tampered = self._integrity_problem(inv)
        if tampered:
            problems.append(tampered)
        if inv["status"] != "received":
            problems.append(f"supplier invoice {inv['invoice_number']} is {inv['status']}"
                            + ("; its bill was voided or corrected, run match again" if self._orphaned(inv) else ""))
        facts = self._facts(inv)
        attempt = self._latest_attempt(inv["id"])
        if attempt is None or attempt["invoice_version"] != inv["version"] or attempt["id"] != inv["match_attempt_id"]:
            problems.append("no match has been computed on the current invoice version; run match(invoice_id, actor) first")
        elif attempt["result_hash"] != hash_json(facts):
            problems.append("the invoice, its bill, its receipts or its document changed since the match was computed; run match again")
        if facts["status"] != "matched":
            problems.append("the match has exceptions: " + ", ".join(facts["exceptions"]))
        return facts, attempt, problems

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation != OP_MATCH:
            raise APIntakeError(f"unknown ap_intake operation {operation}")
        inv = self._row(subject_id)
        facts, attempt, problems = self._eligibility(inv)
        if problems:
            raise InvoiceIneligible(f"supplier invoice {inv['invoice_number']} ({subject_id}) cannot be matched: " + "; ".join(problems))
        supplier = self._supplier(inv["supplier_id"])
        project = self._project(inv["project_id"])
        rev = self._current_revision(inv["evidence_document_id"])
        return build_manifest(
            operation=OP_MATCH,
            subject_type=INVOICE_SUBJECT,
            subject_id=subject_id,
            actor_role=actor_role,
            amounts={"invoice_amount": inv["amount"], "matched_amount": facts["matched_amount"]},
            bindings={
                "invoice_id": inv["id"], "invoice_version": inv["version"], "invoice_hash": inv["content_hash"], "invoice_status": inv["status"],
                "invoice_number": inv["invoice_number"], "number_key": inv["number_key"], "invoice_date": inv["invoice_date"], "due_date": inv["due_date"],
                "project_id": inv["project_id"], "supplier_id": inv["supplier_id"], "commitment_id": inv["commitment_id"],
                "evidence_hash": inv["evidence_hash"], "evidence_document_id": inv["evidence_document_id"], "evidence_revision_id": inv["evidence_revision_id"],
                "evidence_current_hash": rev["content_hash"] if rev else None,
                "possible_duplicate": bool(inv["possible_duplicate"]), "duplicate_cleared_at": inv["duplicate_cleared_at"],
                "match_attempt_id": attempt["id"], "result_hash": attempt["result_hash"],
                "basis": facts["basis"], "match_status": facts["status"], "commitment": facts["commitment"], "award_id": facts["award_id"],
                "bill": facts["bill"], "receipts": facts["receipts"], "po_lines": facts["po_lines"],
                "effect": "records the match and links the invoice to the matched bill (supplier invoice id, number, invoice date, due date)",
            },
            destination={"party_id": supplier["id"], "destination": supplier["destination"], "destination_version": supplier["destination_version"]},
            entity=project["entity"],
            currency=project["currency"] or "USD",
        )

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        """Record the approved match; the caller has consumed ``approval_id`` against ``manifest``."""
        if operation != OP_MATCH:
            raise APIntakeError(f"unknown ap_intake operation {operation}")
        bound = manifest.get("bindings") or {}
        with self.db.transaction() as conn:
            inv = self._row(subject_id)
            facts, attempt, problems = self._eligibility(inv)
            if problems:
                raise InvoiceIneligible(f"supplier invoice {inv['invoice_number']} can no longer be matched: " + "; ".join(problems))
            if bound.get("result_hash") != attempt["result_hash"] or bound.get("invoice_hash") != inv["content_hash"]:
                raise InvoiceIneligible(f"supplier invoice {inv['invoice_number']} no longer matches the approved match")
            ap = self.db.one("SELECT operation, subject_id, status FROM approvals WHERE id=?", (approval_id,))
            if ap is None or ap["operation"] != OP_MATCH or ap["subject_id"] != subject_id or ap["status"] != "consumed":
                raise APIntakeError(f"{OP_MATCH} on {subject_id} runs only against its own consumed approval")
            used = self.db.one("SELECT id FROM ap_invoices WHERE match_approval_id=?", (approval_id,))
            if used is not None:
                raise APIntakeError(f"approval {approval_id} already matched invoice {used['id']}; an approval takes effect once")
            bill_id = (facts["bill"] or {}).get("id")
            invalidated = 0
            for row in self.db.query("SELECT id FROM approvals WHERE subject_type=? AND subject_id=? AND status IN ('pending','granted') AND id != ?",
                                     (INVOICE_SUBJECT, subject_id, approval_id)):
                self.approvals.invalidate(row["id"], reason="the invoice was matched under another approval", actor=actor)
                invalidated += 1
            now = utcnow_iso()
            # audited first: the storage guard admits a match only with its audit entry
            self.audit.record(actor, "ap_intake.invoice_matched", INVOICE_SUBJECT, subject_id, {
                "approval_id": approval_id, "attempt_id": attempt["id"], "invoice_version": inv["version"], "basis": facts["basis"], "bill_id": bill_id,
                "receipts": [r["receipt_id"] for r in facts["receipts"]], "commitment_id": (facts["commitment"] or {}).get("id"),
                "amount": inv["amount"], "due_date": inv["due_date"], "approvals_invalidated": invalidated,
            })
            # the invoice record is matched to the bill first: the bill copies its link from this record
            cur = conn.execute(
                """UPDATE ap_invoices SET status='matched', match_status='matched', matched_bill_id=?, matched_commitment_id=?, match_approval_id=?,
                   matched_at=?, matched_by=?, updated_at=? WHERE id=? AND version=? AND status='received'""",
                (bill_id, (facts["commitment"] or {}).get("id"), approval_id, now, actor, now, subject_id, inv["version"]),
            )
            if cur.rowcount != 1:
                raise APIntakeError(f"supplier invoice {subject_id} changed concurrently; nothing was matched")
            if bill_id:
                self.c.bills.attach_supplier_invoice(bill_id, {"id": inv["id"], "match_approval_id": approval_id}, actor)
        return {"invoice": subject_id, "status": "matched", "basis": facts["basis"], "bill": bill_id,
                "receipts": [r["receipt_id"] for r in facts["receipts"]], "amount": inv["amount"], "due_date": inv["due_date"]}

    # ---- state, close checks and export ----------------------------------------------------------- #

    def state(self, project_id: str) -> dict[str, Any]:
        """Invoices of the project and a summary.  A matched invoice whose bill was voided or
        corrected counts as unmatched (``orphaned_matches``; in ``unmatched``, the overdue
        count and the open amount), not as matched: no payable backs it."""
        invoices = self.invoices(project_id)
        unmatched = [i for i in invoices if i["unmatched"]]
        return {
            "invoices": invoices,
            "summary": {
                "invoices": len(invoices),
                "received": sum(1 for i in invoices if i["status"] == "received"),
                "matched": sum(1 for i in invoices if i["status"] == "matched" and not i["orphaned_match"]),
                "orphaned_matches": sum(1 for i in invoices if i["orphaned_match"]),
                "unmatched": len(unmatched),
                "rejected": sum(1 for i in invoices if i["status"] == "rejected"),
                "exceptions": sum(1 for i in invoices if i["status"] == "received" and i["match_status"] == "exception"),
                "possible_duplicates": sum(1 for i in invoices if i["status"] == "received" and i["duplicate_blocking"]),
                "overdue_unmatched": sum(1 for i in invoices if i["overdue"]),
                "integrity_failures": sum(1 for i in invoices if i["integrity_problem"]),
                "open_amount": fmt(total(i["amount"] for i in unmatched)) if unmatched else "0.00",
            },
        }

    def close_checks(self, period_id: str) -> list[dict[str, Any]]:
        """An unmatched invoice -- received, or matched to a bill that was voided or corrected
        since -- dated on or before the period end whose due date falls before the period end
        fails the check of an open period.  An invoice whose stored facts no longer hash to its
        recorded content hash fails the integrity check.  Exceptions and possible duplicates
        awaiting review are reported for information."""
        period = self.db.one("SELECT * FROM periods WHERE id=?", (period_id,))
        if period is None:
            return [{"check": "ap_intake unmatched supplier invoices past due", "ok": False, "detail": f"unknown period {period_id}"}]
        end = period["end_date"]
        late = self.db.query(
            """SELECT i.id, i.invoice_number, i.supplier_id, i.due_date, i.status, i.match_status, b.status AS bill_status
                 FROM ap_invoices i LEFT JOIN bills b ON b.id = i.matched_bill_id
                WHERE (i.status = 'received' OR (i.status = 'matched' AND b.status IN ('void','corrected')))
                  AND i.invoice_date <= ? AND i.due_date < ?
                ORDER BY i.due_date, i.id""", (end, end),
        )
        ok = not late or period["status"] != "open"

        def why(r: dict[str, Any]) -> str:
            if r["status"] == "matched":
                return f"its bill was {'voided' if r['bill_status'] == 'void' else 'corrected'}: matched to no payable"
            return r["match_status"] or "not matched"

        detail = (f"{len(late)} unmatched supplier invoice(s) past due by {end}: "
                  + ", ".join(f"{r['invoice_number']} ({r['id']}, due {r['due_date']}, {why(r)})" for r in late)
                  if late else f"no unmatched supplier invoice is past due by {end}")
        tampered = [p for p in (self._integrity_problem(r) for r in self.db.query("SELECT * FROM ap_invoices ORDER BY created_at, id")) if p]
        exceptions = self.db.scalar("SELECT COUNT(*) FROM ap_invoices WHERE status='received' AND match_status='exception'") or 0
        duplicates = self.db.scalar("SELECT COUNT(*) FROM ap_invoices WHERE status='received' AND possible_duplicate=1 AND duplicate_cleared_at IS NULL") or 0
        return [
            {"check": "ap_intake unmatched supplier invoices past due", "ok": ok, "detail": detail},
            {"check": "ap_intake supplier invoice records intact", "ok": not tampered,
             "detail": "; ".join(tampered) if tampered else "every supplier invoice hashes to its recorded content hash"},
            {"check": "ap_intake match exceptions (informational)", "ok": True, "detail": f"{exceptions} received invoice(s) with match exceptions"},
            {"check": "ap_intake possible duplicates awaiting review (informational)", "ok": True,
             "detail": f"{duplicates} invoice(s) flagged as possible duplicates and not yet reviewed"},
        ]

    def audit_export(self) -> dict[str, Any]:
        return {
            "invoices": self.db.query("SELECT * FROM ap_invoices ORDER BY created_at, id"),
            "match_computations": self.db.query("SELECT * FROM ap_invoice_matches ORDER BY computed_at, id"),
            "supplier_terms": self.db.query("SELECT * FROM ap_supplier_terms ORDER BY supplier_id"),
        }
