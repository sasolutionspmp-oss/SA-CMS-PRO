"""Shadow-finance hand-off with receipts (v2 plugin, operation prefix ``handoff``).

Plan section 9: while the statutory books stay in the incumbent process, the
first slice hands Cipher's figures over through an accountant-owned, reviewed
export.  Each hand-off receipt is recorded and omissions are reconciled.
Everything here is labelled "SHADOW - for the incumbent books; not
authoritative"; a package is never an authoritative financial statement.

Package (``prepare_handoff(period_id, actor)``)
    One immutable package per call for one open period: every journal posted in
    the period with its lines, the period trial balance, the entity-wide AP and
    AR open items as at preparation (they are not reconstructed as of the period
    end), the subledger reconciliations the service exposes (AP, AR and the core
    reconciliation checks that exist), and CSV renderings ``journals.csv``,
    ``ap.csv`` and ``ar.csv`` with exact money strings.  The package hash is the
    SHA-256 of the package's canonical JSON.  A package whose journals or trial
    balance do not balance is refused; a package identical to the period's latest
    one is a duplicate and is refused.  Package rows are immutable (triggers);
    a new package for the same period supersedes the previous one.  Supplier-bill
    AP items are completed with their commitment and project (looked up from the
    bill) so ``ap.csv`` carries them; a value the subledger supplies is never
    overridden.

    CSV files use the RFC 4180 dialect (CRLF, minimal quoting) but are preceded by
    one label record, a single field ``# <label> | period <id> | cipher-handoff/1``
    written through the CSV writer (so a period id with a comma or quote is
    quoted).  RFC 4180 has no comment lines, so a file is RFC 4180 only after that
    first line (``LABEL_LINES``) is skipped; ``read_csv`` does exactly that, and a
    spreadsheet import must be told to start at line 2.  Columns are fixed
    (``JOURNAL_COLUMNS``, ``AP_COLUMNS``, ``AR_COLUMNS``); any extra field a
    subledger adds is appended after them (sorted) so nothing is lost.  A text
    cell that a spreadsheet would read as a formula (leading ``= + - @``, tab or
    CR, and not a plain number) is prefixed with ``'``; the JSON keeps the exact
    value.

Integrity (``verify``, close and acknowledgement)
    A package row is trusted only when its hash re-performs over canonical JSON,
    its header (format, label, period, journal count, totals) equals its own
    content, the content's journal lines add up to the stated per-journal totals,
    package totals and trial balance (per account too), its period, currency and
    open-items basis are the books' and the module's, its AP / AR reconciliations
    repeat its AP / AR sections, every listed journal still matches the books line
    for line (account names included; journals are immutable), a ``reversed_by``
    it records is the books' reversal of that journal (a reversal posted later is
    an omission, not an integrity failure), its CSV files re-render exactly from
    its content, and it has exactly one ``handoff.prepared`` audit entry recording
    this row (period, sequence, hash, journal count, totals, predecessor, label,
    preparer) that is intact in the hash-chained audit log (its own hashes and both
    neighbouring links).  The provenance check is what covers the content the books
    cannot re-derive later: AP / AR open items and subledger reconciliations are a
    snapshot as at preparation, so a raw row carrying invented subledgers fails
    because ``prepare_handoff`` never recorded it.  A package failing any of that
    cannot be proposed for acknowledgement, cannot be acknowledged under an
    approval, and fails the close check.  Limitation: with no external anchor for
    the audit head, a writer able to recompute SHA-256 for both a forged package
    and a forged, correctly chained audit entry appended to a local file is beyond
    what the workspace itself can detect.  A second catalog entry
    (``handoff_integrity_guards``) refuses the forgeable parts at the database too:
    a raw package row must carry the ``cipher-handoff/1`` format, a 64-character
    lowercase hex hash, canonical money totals, a header equal to its JSON and
    exactly the period's journals and journal totals from the books.  SQLite cannot
    compute SHA-256, so a raw row whose hash does not match its JSON (or that has no
    audit entry) is caught by the integrity check, not a trigger.

Receipt (operation ``handoff.acknowledge``, subject = hand-off id)
    ``record_receipt_details(handoff_id, receipt_ref, accountant, actor)`` is the
    pre-step: append-only, versioned details; a receipt reference belongs to one
    hand-off only, compared with Unicode compatibility caseless matching (so
    ``RCPT-É-1`` and ``rcpt-é-1`` are the same reference), and unchanged details
    are a duplicate.  The database enforces the same Unicode rule: the third
    catalog entry (``handoff_acknowledgement_guards``) compares references through
    the SQL function ``handoff_ref_key`` that the plugin registers on its
    connection (a connection without it cannot insert receipt details at all, so
    the rule fails closed).  The manifest binds the package hash, journal count and
    totals, the receipt details (version, reference, accountant), the period
    status, the period's current journal count and totals, the omissions, the
    package's integrity problems (none, when proposable), the latest hand-off of
    the period, the entity and the currency.  A later journal in the period, a
    reversal of a package journal, new receipt details, a superseding package or
    a period close therefore invalidates a granted acknowledgement instead of
    executing it.  ``manifest_for`` refuses (``HandoffRefused``, a stale-approval
    error) whenever the hand-off is already acknowledged, has no receipt details,
    fails its integrity check, or its period is not open, whatever the transaction
    depth: a proposal then records nothing, and during execution the core
    invalidates the approval.  ``apply`` re-derives the manifest itself and requires
    it to match the approval's stored material hash, so a stale approval consumed
    through the core API directly still records nothing.  A receipt row can only
    be inserted with a consumed ``handoff.acknowledge`` approval for that hand-off,
    by the actor who consumed it, carrying the facts that approval bound while
    they still hold (latest package, period journal count) and the package's true
    omission count, under an approval that bound no integrity problems, an open
    period and no earlier receipt (triggers), once per hand-off.

Omissions and close
    ``omissions(handoff_id)``: journals now in the period that are not in the
    package (posted later), package journals reversed after the package was
    prepared, and package journals missing from the books.  ``close_checks``:
    when the period has at least one hand-off, the latest must pass its integrity
    check, be acknowledged by a receipt carrying its hash, journal count and
    totals, have no omissions and state the period's current journal count and
    totals; with none, an informational passing check (the hand-off is optional
    in the prototype).
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from decimal import Decimal
from typing import Any

from ..core.approvals import StaleApprovalError, build_manifest, material_hash
from ..core.audit import GENESIS
from ..core.db import register_schema_version
from ..core.ids import canonical_json, loads, new_id, sha256_hex, utcnow_iso
from ..core.money import ZERO, MoneyError, fmt, money

SCHEMA_NAME = "handoff"
GUARDS_SCHEMA_NAME = "handoff_integrity_guards"
ACK_GUARDS_SCHEMA_NAME = "handoff_acknowledgement_guards"
PLUGIN_NAME = "handoff"
PREPARED_ACTION = "handoff.prepared"
SQL_REF_KEY = "handoff_ref_key"  # SQL function the plugin registers on its connection (Unicode caseless key)
FORMAT = "cipher-handoff/1"
LABEL = "SHADOW - for the incumbent books; not authoritative"
CURRENCY = "USD"

OP_ACKNOWLEDGE = "handoff.acknowledge"
OPERATIONS = (OP_ACKNOWLEDGE,)
SUBJECT_TYPE = "handoff"
CHECK_NAME = "handoff_receipt_reconciled"
OPEN_ITEMS_BASIS = "AP and AR open items are entity-wide as at preparation; they are not reconstructed as of the period end"

CSV_FILES = ("journals.csv", "ap.csv", "ar.csv")
LABEL_LINES = 1  # records before the RFC 4180 header row in every hand-off CSV
JOURNAL_COLUMNS = (
    "period_id", "journal_id", "posted_at", "description", "source_type", "source_id", "source_version", "rule_version",
    "approval_id", "reversal_of", "reversed_by", "posted_by", "line_no", "account_code", "account_name", "debit", "credit",
    "project_id", "party_id", "memo",
)
# Stable column sets covering every known AP / AR item shape (supplier bills and retainage
# releases; prime bills, retainage invoices and labor T&M invoices).  A field outside them is
# appended after them, sorted, so a new subledger field never reorders the known columns.
AP_COLUMNS = ("kind", "bill_id", "commitment_id", "supplier_id", "project_id", "sequence", "amount_due", "paid", "open")
AR_COLUMNS = (
    "kind", "source", "prime_bill_id", "retainage_invoice_id", "invoice_id", "project_id", "customer_id", "sequence", "period_id",
    "date", "status", "amount_due", "received", "open",
)
MAX_TEXT = 200

# The facts of a posted journal that the books keep immutable (``reversed_by`` is derived and
# may change later, so it is judged on its own; account names are never updated by any code path).
_JOURNAL_FACTS = ("id", "period_id", "posted_at", "description", "source_type", "source_id", "source_version", "rule_version",
                  "approval_id", "reversal_of", "posted_by")
_LINE_FACTS = ("line_no", "account_code", "account_name", "debit", "credit", "project_id", "party_id", "memo")
_PERIOD_FACTS = ("id", "name", "start_date", "end_date")
# What a ``handoff.prepared`` audit entry records about its package row (payload key -> row column).
_PREPARED_FACTS = ("period_id", "sequence", "package_hash", "journal_count", "total_debit", "total_credit", "supersedes")
_JOURNAL_CSV_FIELDS = ("period_id", "posted_at", "description", "source_type", "source_id", "source_version", "rule_version",
                       "approval_id", "reversal_of", "reversed_by", "posted_by")

_NUMBER = re.compile(r"-?\d+(\.\d+)?")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

SCHEMA_STATEMENTS = [
    """CREATE TABLE handoff_packages (
        id TEXT PRIMARY KEY,
        period_id TEXT NOT NULL REFERENCES periods(id),
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        label TEXT NOT NULL,
        format TEXT NOT NULL,
        package_json TEXT NOT NULL,
        package_hash TEXT NOT NULL CHECK (length(package_hash) = 64),
        journal_count INTEGER NOT NULL CHECK (journal_count >= 0),
        total_debit TEXT NOT NULL,
        total_credit TEXT NOT NULL,
        supersedes TEXT REFERENCES handoff_packages(id),
        prepared_by TEXT NOT NULL,
        prepared_at TEXT NOT NULL,
        UNIQUE (period_id, sequence)
    )""",
    "CREATE TRIGGER handoff_packages_no_update BEFORE UPDATE ON handoff_packages BEGIN SELECT RAISE(ABORT, 'hand-off packages are immutable; prepare a new hand-off'); END",
    "CREATE TRIGGER handoff_packages_no_delete BEFORE DELETE ON handoff_packages BEGIN SELECT RAISE(ABORT, 'hand-off packages are immutable and never deleted'); END",
    """CREATE TRIGGER handoff_packages_insert_guard BEFORE INSERT ON handoff_packages
        BEGIN
            SELECT CASE
                WHEN (SELECT status FROM periods WHERE id = NEW.period_id) IS NOT 'open'
                THEN RAISE(ABORT, 'a hand-off is prepared for an open period only')
                WHEN NEW.sequence IS NOT (SELECT COALESCE(MAX(sequence), 0) + 1 FROM handoff_packages WHERE period_id = NEW.period_id)
                THEN RAISE(ABORT, 'a hand-off takes the next sequence of its period')
                WHEN NEW.supersedes IS NOT (SELECT id FROM handoff_packages WHERE period_id = NEW.period_id ORDER BY sequence DESC LIMIT 1)
                THEN RAISE(ABORT, 'a hand-off supersedes the latest package of its period')
                WHEN NEW.total_debit IS NOT NEW.total_credit
                THEN RAISE(ABORT, 'a hand-off package must balance')
                WHEN NEW.label IS NOT '""" + LABEL + """'
                THEN RAISE(ABORT, 'a hand-off package carries the SHADOW label')
            END;
        END""",
    """CREATE TABLE handoff_receipt_details (
        id TEXT PRIMARY KEY,
        handoff_id TEXT NOT NULL REFERENCES handoff_packages(id),
        version INTEGER NOT NULL CHECK (version >= 1),
        receipt_ref TEXT NOT NULL COLLATE NOCASE CHECK (length(trim(receipt_ref)) > 0),
        accountant TEXT NOT NULL CHECK (length(trim(accountant)) > 0),
        recorded_by TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE (handoff_id, version)
    )""",
    "CREATE TRIGGER handoff_receipt_details_no_update BEFORE UPDATE ON handoff_receipt_details BEGIN SELECT RAISE(ABORT, 'receipt details are immutable; record a new version'); END",
    "CREATE TRIGGER handoff_receipt_details_no_delete BEFORE DELETE ON handoff_receipt_details BEGIN SELECT RAISE(ABORT, 'receipt details are immutable and never deleted'); END",
    """CREATE TRIGGER handoff_receipt_details_insert_guard BEFORE INSERT ON handoff_receipt_details
        BEGIN
            SELECT CASE
                WHEN (SELECT p.status FROM handoff_packages h JOIN periods p ON p.id = h.period_id WHERE h.id = NEW.handoff_id) IS NOT 'open'
                THEN RAISE(ABORT, 'receipt details are recorded while the hand-off period is open')
                WHEN EXISTS (SELECT 1 FROM handoff_receipts WHERE handoff_id = NEW.handoff_id)
                THEN RAISE(ABORT, 'the hand-off was already acknowledged; its receipt details are final')
                WHEN NEW.version IS NOT (SELECT COALESCE(MAX(version), 0) + 1 FROM handoff_receipt_details WHERE handoff_id = NEW.handoff_id)
                THEN RAISE(ABORT, 'receipt details take the next version of their hand-off')
                WHEN EXISTS (SELECT 1 FROM handoff_receipt_details WHERE receipt_ref = NEW.receipt_ref AND handoff_id != NEW.handoff_id)
                THEN RAISE(ABORT, 'a receipt reference belongs to one hand-off only')
            END;
        END""",
    """CREATE TABLE handoff_receipts (
        id TEXT PRIMARY KEY,
        handoff_id TEXT NOT NULL UNIQUE REFERENCES handoff_packages(id),
        receipt_details_id TEXT NOT NULL REFERENCES handoff_receipt_details(id),
        receipt_ref TEXT NOT NULL COLLATE NOCASE UNIQUE,
        accountant TEXT NOT NULL,
        package_hash TEXT NOT NULL,
        journal_count INTEGER NOT NULL,
        total_debit TEXT NOT NULL,
        total_credit TEXT NOT NULL,
        omission_count INTEGER NOT NULL CHECK (omission_count >= 0),
        approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id),
        acknowledged_by TEXT NOT NULL,
        acknowledged_at TEXT NOT NULL
    )""",
    "CREATE TRIGGER handoff_receipts_no_update BEFORE UPDATE ON handoff_receipts BEGIN SELECT RAISE(ABORT, 'hand-off receipts are immutable'); END",
    "CREATE TRIGGER handoff_receipts_no_delete BEFORE DELETE ON handoff_receipts BEGIN SELECT RAISE(ABORT, 'hand-off receipts are immutable and never deleted'); END",
    """CREATE TRIGGER handoff_receipts_insert_guard BEFORE INSERT ON handoff_receipts
        BEGIN
            SELECT CASE
                WHEN NOT EXISTS (SELECT 1 FROM approvals WHERE id = NEW.approval_id AND status = 'consumed' AND operation = 'handoff.acknowledge'
                                 AND subject_type = 'handoff' AND subject_id = NEW.handoff_id)
                THEN RAISE(ABORT, 'a hand-off receipt needs a consumed handoff.acknowledge approval for that hand-off')
                WHEN (SELECT p.status FROM handoff_packages h JOIN periods p ON p.id = h.period_id WHERE h.id = NEW.handoff_id) IS NOT 'open'
                THEN RAISE(ABORT, 'a hand-off is acknowledged while its period is open')
                WHEN NEW.receipt_details_id IS NOT (SELECT id FROM handoff_receipt_details WHERE handoff_id = NEW.handoff_id ORDER BY version DESC LIMIT 1)
                THEN RAISE(ABORT, 'a receipt binds the latest receipt details of its hand-off')
                WHEN NOT EXISTS (SELECT 1 FROM handoff_receipt_details WHERE id = NEW.receipt_details_id AND receipt_ref = NEW.receipt_ref AND accountant = NEW.accountant)
                THEN RAISE(ABORT, 'receipt reference and accountant must match the recorded receipt details')
                WHEN NOT EXISTS (SELECT 1 FROM handoff_packages WHERE id = NEW.handoff_id AND package_hash = NEW.package_hash AND journal_count = NEW.journal_count
                                 AND total_debit = NEW.total_debit AND total_credit = NEW.total_credit)
                THEN RAISE(ABORT, 'a receipt carries the package hash, journal count and totals of its hand-off')
            END;
        END""",
]


# --------------------------------------------------------------------------- #
# Integrity guards (a follow-on catalog entry; applied entries are append-only) #
# --------------------------------------------------------------------------- #

def _cents(expr: str) -> str:
    """Exact integer cents of a stored money string (the core seal trigger's idiom; exact below 10**13)."""
    return f"CAST(ROUND(CAST({expr} AS REAL) * 100) AS INTEGER)"


def _canonical_money(expr: str) -> str:
    """SQL truth value: ``expr`` is a canonical non-negative money string (digits, one point, two decimals, no leading zero)."""
    return (f"({expr} GLOB '*[0-9].[0-9][0-9]' AND {expr} NOT GLOB '*[^0-9.]*' AND {expr} NOT GLOB '*.*.*' "
            f"AND {expr} NOT GLOB '0[0-9]*')")


def _period_cents(column: str) -> str:
    return (f"(SELECT COALESCE(SUM({_cents('l.' + column)}), 0) FROM journal_lines l JOIN journals j ON j.id = l.journal_id "
            "WHERE j.period_id = NEW.period_id)")


# The new guard runs only when the base guard would pass, so the base guard's messages stay intact.
_PACKAGE_PASSES_BASE_GUARD = (
    "(SELECT status FROM periods WHERE id = NEW.period_id) IS 'open' "
    "AND NEW.sequence IS (SELECT COALESCE(MAX(sequence), 0) + 1 FROM handoff_packages WHERE period_id = NEW.period_id) "
    "AND NEW.supersedes IS (SELECT id FROM handoff_packages WHERE period_id = NEW.period_id ORDER BY sequence DESC LIMIT 1) "
    f"AND NEW.total_debit IS NEW.total_credit AND NEW.label IS '{LABEL}'"
)
_PKG = "NEW.package_json"
_FIRST_REVERSAL = "(SELECT r.id FROM journals r WHERE r.reversal_of = json_extract(e.value, '$.id') ORDER BY r.posted_at, r.id LIMIT 1)"
# The same omission count ``Plugin.omissions`` computes: period journals not listed, listed journals
# missing from the books, and listed journals whose first reversal is not the one the package recorded.
_OMISSION_COUNT = f"""(SELECT
            (SELECT COUNT(*) FROM journals j WHERE j.period_id = h.period_id
                AND NOT EXISTS (SELECT 1 FROM json_each(h.package_json, '$.journals') e WHERE json_extract(e.value, '$.id') = j.id))
          + (SELECT COUNT(*) FROM json_each(h.package_json, '$.journals') e
                WHERE NOT EXISTS (SELECT 1 FROM journals j WHERE j.id = json_extract(e.value, '$.id')))
          + (SELECT COUNT(*) FROM json_each(h.package_json, '$.journals') e
                WHERE EXISTS (SELECT 1 FROM journals j WHERE j.id = json_extract(e.value, '$.id'))
                  AND {_FIRST_REVERSAL} IS NOT NULL AND {_FIRST_REVERSAL} IS NOT json_extract(e.value, '$.reversed_by'))
        FROM handoff_packages h WHERE h.id = NEW.handoff_id)"""
_BOUND = "(SELECT json_extract(a.manifest_json, '{path}') FROM approvals a WHERE a.id = NEW.approval_id)"
_RECEIPT_PERIOD = "(SELECT period_id FROM handoff_packages WHERE id = NEW.handoff_id)"

GUARDS_SCHEMA_STATEMENTS = [
    f"""CREATE TRIGGER handoff_packages_content_guard BEFORE INSERT ON handoff_packages
        WHEN {_PACKAGE_PASSES_BASE_GUARD}
        BEGIN
            SELECT CASE
                WHEN NEW.format IS NOT '{FORMAT}'
                THEN RAISE(ABORT, 'a hand-off package has the {FORMAT} format')
                WHEN length(NEW.package_hash) IS NOT 64 OR NEW.package_hash GLOB '*[^0-9a-f]*'
                THEN RAISE(ABORT, 'a hand-off package hash is 64 lowercase hexadecimal characters')
                WHEN NOT {_canonical_money('NEW.total_debit')}
                THEN RAISE(ABORT, 'a hand-off package carries canonical money totals')
                WHEN json_valid({_PKG}) IS NOT 1 OR json_type({_PKG}) IS NOT 'object' OR json_type({_PKG}, '$.journals') IS NOT 'array'
                THEN RAISE(ABORT, 'a hand-off package is a JSON object listing its journals')
                WHEN json_extract({_PKG}, '$.format') IS NOT NEW.format OR json_extract({_PKG}, '$.label') IS NOT NEW.label
                  OR json_extract({_PKG}, '$.period.id') IS NOT NEW.period_id OR json_extract({_PKG}, '$.trial_balance.period_id') IS NOT NEW.period_id
                  OR json_extract({_PKG}, '$.journal_count') IS NOT NEW.journal_count OR json_array_length({_PKG}, '$.journals') IS NOT NEW.journal_count
                  OR json_extract({_PKG}, '$.trial_balance.journal_count') IS NOT NEW.journal_count
                  OR json_extract({_PKG}, '$.totals.debit') IS NOT NEW.total_debit OR json_extract({_PKG}, '$.totals.credit') IS NOT NEW.total_credit
                  OR json_extract({_PKG}, '$.trial_balance.total_debit') IS NOT NEW.total_debit
                  OR json_extract({_PKG}, '$.trial_balance.total_credit') IS NOT NEW.total_credit
                THEN RAISE(ABORT, 'a hand-off package header must agree with its own content')
                WHEN (SELECT COUNT(*) FROM journals WHERE period_id = NEW.period_id) IS NOT NEW.journal_count
                  OR (SELECT COUNT(DISTINCT json_extract(e.value, '$.id')) FROM json_each({_PKG}, '$.journals') e) IS NOT NEW.journal_count
                  OR EXISTS (SELECT 1 FROM json_each({_PKG}, '$.journals') e
                             WHERE NOT EXISTS (SELECT 1 FROM journals j WHERE j.id = json_extract(e.value, '$.id') AND j.period_id = NEW.period_id))
                THEN RAISE(ABORT, 'a hand-off package lists exactly the journals of its period')
                WHEN {_period_cents('debit')} IS NOT {_cents('NEW.total_debit')} OR {_period_cents('credit')} IS NOT {_cents('NEW.total_credit')}
                THEN RAISE(ABORT, 'a hand-off package carries the journal totals of its period')
            END;
        END""",
    f"""CREATE TRIGGER handoff_receipts_binding_guard BEFORE INSERT ON handoff_receipts
        WHEN EXISTS (SELECT 1 FROM approvals WHERE id = NEW.approval_id AND status = 'consumed' AND operation = 'handoff.acknowledge'
                     AND subject_type = 'handoff' AND subject_id = NEW.handoff_id)
        BEGIN
            SELECT CASE
                WHEN NEW.acknowledged_by IS NOT (SELECT consumed_by FROM approvals WHERE id = NEW.approval_id)
                THEN RAISE(ABORT, 'a hand-off receipt is recorded by the actor who consumed its approval')
                WHEN {_BOUND.format(path='$.bindings.handoff_id')} IS NOT NEW.handoff_id
                  OR {_BOUND.format(path='$.bindings.package_hash')} IS NOT NEW.package_hash
                  OR {_BOUND.format(path='$.bindings.package_journal_count')} IS NOT NEW.journal_count
                  OR {_BOUND.format(path='$.amounts.package_total_debit')} IS NOT NEW.total_debit
                  OR {_BOUND.format(path='$.amounts.package_total_credit')} IS NOT NEW.total_credit
                  OR {_BOUND.format(path='$.bindings.receipt_details_id')} IS NOT NEW.receipt_details_id
                  OR {_BOUND.format(path='$.bindings.receipt_ref')} IS NOT NEW.receipt_ref
                  OR {_BOUND.format(path='$.bindings.accountant')} IS NOT NEW.accountant
                  OR {_BOUND.format(path='$.bindings.omission_count')} IS NOT NEW.omission_count
                THEN RAISE(ABORT, 'a hand-off receipt carries exactly the facts its approval bound')
                WHEN {_BOUND.format(path='$.bindings.latest_handoff_for_period')}
                     IS NOT (SELECT l.id FROM handoff_packages l WHERE l.period_id = {_RECEIPT_PERIOD} ORDER BY l.sequence DESC LIMIT 1)
                  OR {_BOUND.format(path='$.bindings.period_now.journal_count')}
                     IS NOT (SELECT COUNT(*) FROM journals WHERE period_id = {_RECEIPT_PERIOD})
                THEN RAISE(ABORT, 'the facts the acknowledgement approval bound no longer hold (a later package or journal)')
                WHEN NEW.omission_count IS NOT {_OMISSION_COUNT}
                THEN RAISE(ABORT, 'a hand-off receipt records the true omission count of its package')
            END;
        END""",
]

# --------------------------------------------------------------------------- #
# Acknowledgement guards (a further follow-on entry; the entries above are applied history) #
# --------------------------------------------------------------------------- #

_BOUND_TYPE = "(SELECT json_type(a.manifest_json, '{path}') FROM approvals a WHERE a.id = NEW.approval_id)"
_BOUND_LENGTH = "(SELECT json_array_length(a.manifest_json, '{path}') FROM approvals a WHERE a.id = NEW.approval_id)"
_INTEGRITY_PATH = "$.bindings.package_integrity_problems"

ACK_GUARDS_SCHEMA_STATEMENTS = [
    # An approval can only acknowledge a package that had no integrity problems when it was bound, in an
    # open period, with no earlier receipt (the proposal refuses all three; this holds for raw rows too).
    f"""CREATE TRIGGER handoff_receipts_integrity_guard BEFORE INSERT ON handoff_receipts
        WHEN EXISTS (SELECT 1 FROM approvals WHERE id = NEW.approval_id AND status = 'consumed' AND operation = 'handoff.acknowledge'
                     AND subject_type = 'handoff' AND subject_id = NEW.handoff_id)
        BEGIN
            SELECT CASE
                WHEN {_BOUND_TYPE.format(path=_INTEGRITY_PATH)} IS NOT 'array' OR {_BOUND_LENGTH.format(path=_INTEGRITY_PATH)} IS NOT 0
                THEN RAISE(ABORT, 'a hand-off receipt needs an approval that bound a package with no integrity problems')
                WHEN {_BOUND.format(path='$.bindings.period_status')} IS NOT 'open'
                THEN RAISE(ABORT, 'a hand-off receipt needs an approval that bound an open period')
                WHEN {_BOUND_TYPE.format(path='$.bindings.acknowledged_by_receipt')} IS NOT 'null'
                THEN RAISE(ABORT, 'a hand-off receipt needs an approval that bound an unacknowledged hand-off')
            END;
        END""",
    # Unicode compatibility caseless uniqueness of receipt references (NOCASE folds ASCII letters only).
    f"""CREATE TRIGGER handoff_receipt_details_unicode_ref_guard BEFORE INSERT ON handoff_receipt_details
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM handoff_receipt_details d WHERE d.handoff_id IS NOT NEW.handoff_id
                             AND {SQL_REF_KEY}(d.receipt_ref) IS {SQL_REF_KEY}(NEW.receipt_ref))
                THEN RAISE(ABORT, 'a receipt reference belongs to one hand-off only (compared caseless across Unicode)')
            END;
        END""",
]

# Registered here, in this order, so each follow-on entry always sits after the tables it guards;
# the plugin loader's own registration of SCHEMA_NAME is then a no-op.
register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)
register_schema_version(GUARDS_SCHEMA_NAME, GUARDS_SCHEMA_STATEMENTS)
register_schema_version(ACK_GUARDS_SCHEMA_NAME, ACK_GUARDS_SCHEMA_STATEMENTS)


class HandoffError(RuntimeError):
    """Invalid hand-off input or an action the current state does not allow."""


class HandoffDuplicate(HandoffError):
    """The same package, receipt reference or receipt details were already recorded."""


class HandoffStale(HandoffError, StaleApprovalError):
    """The hand-off changed after the acknowledgement was approved; the core invalidates the approval."""


class HandoffRefused(HandoffStale):
    """The hand-off cannot be acknowledged in its current state (already acknowledged, no receipt
    details, failing integrity, period not open).  Raised by ``manifest_for`` at any transaction
    depth: a proposal records nothing, and an execution invalidates its approval."""


# --------------------------------------------------------------------------- #
# CSV rendering                                                                #
# --------------------------------------------------------------------------- #

def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return f"{value:f}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (dict, list, tuple)):
        return canonical_json(value)
    text = str(value)
    if text and text[0] in _FORMULA_PREFIXES and not _NUMBER.fullmatch(text):
        text = "'" + text  # a spreadsheet must not evaluate free text as a formula
    return text


def _one_line(text: Any) -> str:
    return " ".join(str(text).split())


def label_line(period_id: str) -> str:
    """The text of the single-field label record that opens every hand-off CSV."""
    return f"# {LABEL} | period {_one_line(period_id)} | {FORMAT}"


def render_csv(period_id: str, columns: list[str] | tuple[str, ...], rows: list[dict[str, Any]]) -> str:
    """One label record, then an RFC 4180 header row and data rows (CRLF, minimal quoting).

    The label record is a single field written through the CSV writer, so it is quoted when
    the period id needs it.  It is not part of RFC 4180: skip ``LABEL_LINES`` record(s), or use
    ``read_csv``, before handing the rest to a standard reader."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([label_line(period_id)])
    writer.writerow([_cell(c) for c in columns])
    for row in rows:
        writer.writerow([_cell(row.get(c)) for c in columns])
    return buf.getvalue()


def read_csv(text: str) -> tuple[str, list[str], list[dict[str, str]]]:
    """Parse a hand-off CSV: returns (label, header, rows as dicts), skipping the label record."""
    if not isinstance(text, str):
        raise HandoffError("a hand-off CSV is text")
    records = list(csv.reader(io.StringIO(text, newline="")))
    if len(records) < LABEL_LINES + 1 or len(records[0]) != 1 or not records[0][0].startswith(f"# {LABEL} | period "):
        raise HandoffError("not a hand-off CSV: it must open with its one-field SHADOW label record and a header row")
    header = records[LABEL_LINES]
    rows = []
    for n, rec in enumerate(records[LABEL_LINES + 1:], start=LABEL_LINES + 2):
        if len(rec) != len(header):
            raise HandoffError(f"hand-off CSV record {n} has {len(rec)} fields; the header has {len(header)}")
        rows.append(dict(zip(header, rec)))
    return records[0][0], header, rows


def _columns(items: list[dict[str, Any]], preferred: tuple[str, ...]) -> list[str]:
    extra = sorted({str(k) for it in items for k in it} - set(preferred))
    return list(preferred) + extra


def _journal_rows(journals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**{k: j.get(k) for k in _JOURNAL_CSV_FIELDS}, "journal_id": j.get("id"), **ln} for j in journals for ln in (j.get("lines") or [])]


def _csv_files(period_id: str, journals: list[dict[str, Any]], ap_items: list[dict[str, Any]], ar_items: list[dict[str, Any]]) -> dict[str, str]:
    return {
        "journals.csv": render_csv(period_id, JOURNAL_COLUMNS, _journal_rows(journals)),
        "ap.csv": render_csv(period_id, _columns(ap_items, AP_COLUMNS), ap_items),
        "ar.csv": render_csv(period_id, _columns(ar_items, AR_COLUMNS), ar_items),
    }


def _facts(journal: dict[str, Any]) -> dict[str, Any]:
    lines = journal.get("lines") if isinstance(journal.get("lines"), list) else []
    return {**{k: journal.get(k) for k in _JOURNAL_FACTS},
            "lines": [{k: ln.get(k) for k in _LINE_FACTS} if isinstance(ln, dict) else ln for ln in lines]}


def ref_key(text: str) -> str:
    """Unicode compatibility caseless key of a receipt reference: NFKD(casefold(NFKD(casefold(NFD(x)))))."""
    nfd = unicodedata.normalize("NFD", text)
    return unicodedata.normalize("NFKD", unicodedata.normalize("NFKD", nfd.casefold()).casefold())


def _sql_ref_key(value: Any) -> str | None:
    return ref_key(value) if isinstance(value, str) else None


def register_sql_functions(conn: Any) -> None:
    """Register ``handoff_ref_key`` (used by the receipt-details guard) on a SQLite connection."""
    conn.create_function(SQL_REF_KEY, 1, _sql_ref_key, deterministic=True)


# --------------------------------------------------------------------------- #
# Plugin                                                                       #
# --------------------------------------------------------------------------- #

class Plugin:
    def __init__(self, cipher):
        self.c = cipher
        self.db = cipher.db
        self.audit = cipher.audit
        self.ledger = cipher.ledger
        self.approvals = cipher.approvals
        register_sql_functions(self.db.conn)

    # ---- validation and lookups ------------------------------------------------ #

    @staticmethod
    def _text(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise HandoffError(f"{label} is required and must be a non-empty string")
        text = value.strip()
        if len(text) > MAX_TEXT:
            raise HandoffError(f"{label} is longer than {MAX_TEXT} characters")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
            raise HandoffError(f"{label} must not contain control characters")
        return text

    def _period(self, period_id: Any) -> dict[str, Any]:
        pid = self._text(period_id, "period id")
        row = self.db.one("SELECT * FROM periods WHERE id=?", (pid,))
        if row is None:
            raise HandoffError(f"unknown period {pid}")
        return row

    @staticmethod
    def _require_open(period: dict[str, Any], what: str) -> None:
        if period["status"] != "open":
            raise HandoffError(f"period {period['id']} is {period['status']}; {what} for an open period only")

    def _row(self, handoff_id: Any) -> dict[str, Any]:
        hid = self._text(handoff_id, "hand-off id")
        row = self.db.one("SELECT * FROM handoff_packages WHERE id=?", (hid,))
        if row is None:
            raise HandoffError(f"unknown hand-off {hid}")
        return row

    def _rows(self, period_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM handoff_packages WHERE period_id=? ORDER BY sequence", (period_id,))

    def _latest_row(self, period_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM handoff_packages WHERE period_id=? ORDER BY sequence DESC LIMIT 1", (period_id,))

    def _receipt(self, handoff_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM handoff_receipts WHERE handoff_id=?", (handoff_id,))

    def _details(self, handoff_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM handoff_receipt_details WHERE handoff_id=? ORDER BY version DESC LIMIT 1", (handoff_id,))

    def _entities(self) -> list[str]:
        return [r["entity"] for r in self.db.query("SELECT DISTINCT entity FROM projects ORDER BY entity")]

    def _entity(self) -> str | None:
        return "; ".join(self._entities()) or None

    # ---- package content --------------------------------------------------------- #

    def _load_journals(self, where: str, params: tuple) -> list[dict[str, Any]]:
        journals = self.db.query(f"SELECT {', '.join(_JOURNAL_FACTS)} FROM journals WHERE {where} ORDER BY posted_at, id", params)
        for j in journals:
            lines = self.db.query(
                """SELECT l.line_no, l.account_code, a.name AS account_name, l.debit, l.credit, l.project_id, l.party_id, l.memo
                   FROM journal_lines l LEFT JOIN accounts a ON a.code = l.account_code WHERE l.journal_id=? ORDER BY l.line_no, l.id""",
                (j["id"],),
            )
            dr = ZERO
            cr = ZERO
            for ln in lines:
                ln["debit"] = fmt(money(ln["debit"]))
                ln["credit"] = fmt(money(ln["credit"]))
                dr += money(ln["debit"])
                cr += money(ln["credit"])
            rev = self.db.one("SELECT id FROM journals WHERE reversal_of=? ORDER BY posted_at, id LIMIT 1", (j["id"],))
            j["reversed_by"] = rev["id"] if rev else None
            j["total_debit"] = fmt(dr)
            j["total_credit"] = fmt(cr)
            j["lines"] = lines
        return journals

    def _period_journals(self, period_id: str) -> list[dict[str, Any]]:
        return self._load_journals("period_id=?", (period_id,))

    def _ap_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """AP open items with their kind, and a supplier bill's commitment and project filled in from the
        bill when the subledger leaves them out (a supplied value is never overridden)."""
        out = []
        for it in items:
            item = dict(it)
            item["kind"] = item.get("kind") or ("supplier_bill" if item.get("bill_id") else "")
            if item.get("commitment_id") is None and item.get("bill_id"):
                bill = self.db.one("SELECT commitment_id FROM bills WHERE id=?", (item["bill_id"],))
                if bill is not None:
                    item["commitment_id"] = bill["commitment_id"]
            if item.get("project_id") is None and item.get("commitment_id"):
                cmt = self.db.one("SELECT project_id FROM commitments WHERE id=?", (item["commitment_id"],))
                if cmt is not None:
                    item["project_id"] = cmt["project_id"]
            out.append(item)
        return out

    @staticmethod
    def _ar_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**it, "kind": it.get("kind") or ("prime_bill" if it.get("prime_bill_id") else "")} for it in items]

    def _core_checks(self) -> tuple:
        core = self.c._plugins.get("core_reconciliation")
        checks = getattr(core, "CHECKS", None)
        if checks is None:
            from .. import service as _service  # loaded by now; never imported at module import time (cycle)
            checks = getattr(getattr(_service, "CoreReconciliationChecks", None), "CHECKS", ())
        return tuple(checks)

    def _reconciliations(self, ap: dict[str, Any], ar: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ap": {"subledger_total": ap.get("subledger_total"), "control_balance": ap.get("control_balance"), "reconciled": bool(ap.get("reconciled"))},
            "ar": {"subledger_total": ar.get("subledger_total"), "control_balance": ar.get("control_balance"), "reconciled": bool(ar.get("reconciled"))},
        }
        for label, domain_name, method in self._core_checks():
            fn = getattr(getattr(self.c, domain_name, None), method, None)
            if fn is None:
                continue
            try:
                out[label] = fn()
            except Exception as exc:  # the package says what it could not reconcile instead of hiding it
                out[label] = {"error": f"{type(exc).__name__}: {exc}"}
        return out

    def _content(self, period: dict[str, Any]) -> dict[str, Any]:
        pid = period["id"]
        journals = self._period_journals(pid)
        total_dr = ZERO
        total_cr = ZERO
        for j in journals:
            if j["total_debit"] != j["total_credit"] or not j["lines"]:
                raise HandoffError(f"journal {j['id']} in {pid} does not balance (debits {j['total_debit']}, credits {j['total_credit']}); nothing is handed off")
            total_dr += money(j["total_debit"])
            total_cr += money(j["total_credit"])
        tb = self.ledger.trial_balance(pid)
        if (not tb["balanced"] or tb["total_debit"] != fmt(total_dr) or tb["total_credit"] != fmt(total_cr)
                or tb["journal_count"] != len(journals) or total_dr != total_cr):
            raise HandoffError(
                f"the books for {pid} do not balance (trial balance debits {tb['total_debit']}, credits {tb['total_credit']}, "
                f"{tb['journal_count']} journal(s); journals {fmt(total_dr)} / {fmt(total_cr)}, {len(journals)} journal(s)); nothing is handed off"
            )
        ap = self.c.bills.ap_open_items()
        ar = self.c.receivables.ar_open_items()
        ap_items = self._ap_items(ap.get("items") or [])
        ar_items = self._ar_items(ar.get("items") or [])
        return {
            "format": FORMAT,
            "label": LABEL,
            "currency": CURRENCY,
            "entities": self._entities(),
            "period": {k: period[k] for k in ("id", "name", "start_date", "end_date")},
            "journal_count": len(journals),
            "totals": {"debit": fmt(total_dr), "credit": fmt(total_cr)},
            "journals": journals,
            "trial_balance": tb,
            "open_items_basis": OPEN_ITEMS_BASIS,
            "ap": {**ap, "items": ap_items},
            "ar": {**ar, "items": ar_items},
            "reconciliations": self._reconciliations(ap, ar),
            "csv": _csv_files(pid, journals, ap_items, ar_items),
        }

    # ---- integrity ------------------------------------------------------------------- #

    def _integrity(self, row: dict[str, Any]) -> list[str]:
        """Everything that makes a stored package untrustworthy, re-performed from its row, its JSON,
        the books and the audit log.  Empty when the package is what ``prepare_handoff`` stored."""
        return self._content_problems(row) + self._provenance(row)

    def _provenance(self, row: dict[str, Any]) -> list[str]:
        """The package row must have exactly one ``handoff.prepared`` audit entry that records it and
        is intact in the hash-chained log (its own hashes and both neighbouring links)."""
        entries = self.db.query("SELECT * FROM audit_log WHERE action=? AND entity_type=? AND entity_id=? ORDER BY seq",
                                (PREPARED_ACTION, SUBJECT_TYPE, row.get("id")))
        if not entries:
            return [f"it has no {PREPARED_ACTION} audit entry (it was not prepared through prepare_handoff)"]
        if len(entries) > 1:
            return [f"it has {len(entries)} {PREPARED_ACTION} audit entries"]
        e = entries[0]
        problems = []
        try:
            payload = loads(e["payload_json"])
        except ValueError:
            payload = None
        expected = {**{k: row.get(k) for k in _PREPARED_FACTS}, "label": LABEL}
        if (not isinstance(payload, dict) or any(k not in payload or payload[k] != v for k, v in expected.items())
                or e["actor"] != row.get("prepared_by")):
            problems.append(f"its {PREPARED_ACTION} audit entry does not record this package "
                            "(period, sequence, hash, journal count, totals, predecessor, label and preparer)")
        prev = self.db.one("SELECT entry_hash FROM audit_log WHERE seq < ? ORDER BY seq DESC LIMIT 1", (e["seq"],))
        nxt = self.db.one("SELECT prev_hash FROM audit_log WHERE seq > ? ORDER BY seq LIMIT 1", (e["seq"],))
        fields = [e["prev_hash"], e["ts"], e["actor"], e["action"], e["entity_type"], e["entity_id"], e["payload_hash"]]
        if (not all(isinstance(f, str) for f in fields) or not isinstance(e["payload_json"], str)
                or sha256_hex(e["payload_json"]) != e["payload_hash"] or e["entry_hash"] != sha256_hex("|".join(fields))
                or e["prev_hash"] != (prev["entry_hash"] if prev else GENESIS)
                or (nxt is not None and nxt["prev_hash"] != e["entry_hash"])):
            problems.append(f"its {PREPARED_ACTION} audit entry is not intact in the hash-chained audit log")
        return problems

    def _content_problems(self, row: dict[str, Any]) -> list[str]:
        """The package's own content against its row, itself and the books (no provenance)."""
        problems: list[str] = []
        text = row.get("package_json")
        if not isinstance(text, str):
            return ["its package is not stored as text"]
        if sha256_hex(text) != row.get("package_hash"):
            problems.append("its hash does not match the stored package")
        try:
            pkg = loads(text)
        except ValueError:
            return problems + ["its package is not valid JSON"]
        if not isinstance(pkg, dict):
            return problems + ["its package is not a JSON object"]
        if canonical_json(pkg) != text:
            problems.append("its package is not canonical JSON")
        if row.get("format") != FORMAT or pkg.get("format") != FORMAT:
            problems.append(f"its format is not {FORMAT}")
        if row.get("label") != LABEL or pkg.get("label") != LABEL:
            problems.append("it does not carry the SHADOW label")
        period = pkg.get("period") if isinstance(pkg.get("period"), dict) else {}
        tb = pkg.get("trial_balance") if isinstance(pkg.get("trial_balance"), dict) else {}
        totals = pkg.get("totals") if isinstance(pkg.get("totals"), dict) else {}
        pid = row.get("period_id")
        if period.get("id") != pid or tb.get("period_id") != pid:
            problems.append(f"its content is not for period {pid}")
        else:
            book_period = self.db.one("SELECT id, name, start_date, end_date FROM periods WHERE id=?", (pid,))
            if book_period is None or period != {k: book_period[k] for k in _PERIOD_FACTS}:
                problems.append(f"its period facts do not match period {pid} in the books")
        if pkg.get("currency") != CURRENCY or pkg.get("open_items_basis") != OPEN_ITEMS_BASIS:
            problems.append(f"its currency or open-items basis is not this module's ({CURRENCY}; open items as at preparation)")
        journals = pkg.get("journals")
        if not isinstance(journals, list) or not all(
                isinstance(j, dict) and isinstance(j.get("lines"), list) and all(isinstance(ln, dict) for ln in j["lines"]) for j in journals):
            return problems + ["its journals are not a list of journals with lines"]
        ids = [j.get("id") for j in journals]
        if not all(isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            problems.append("its journals are not each listed once by id")
        counts = (("header", row.get("journal_count")), ("content", pkg.get("journal_count")), ("trial balance", tb.get("journal_count")))
        wrong_counts = [f"{name} {value}" for name, value in counts if type(value) is not int or value != len(journals)]
        if wrong_counts:
            problems.append(f"its journal counts disagree with the {len(journals)} journal(s) it lists: {', '.join(wrong_counts)}")

        # every amount re-added from the listed lines
        dr = ZERO
        cr = ZERO
        per_account: dict[str, list[Decimal]] = {}
        try:
            for j in journals:
                jdr = sum((money(ln.get("debit")) for ln in j["lines"]), ZERO)
                jcr = sum((money(ln.get("credit")) for ln in j["lines"]), ZERO)
                if not j["lines"] or jdr != jcr or j.get("total_debit") != fmt(jdr) or j.get("total_credit") != fmt(jcr):
                    problems.append(f"package journal {j.get('id')} does not add up (lines {fmt(jdr)} / {fmt(jcr)}, "
                                    f"stated {j.get('total_debit')} / {j.get('total_credit')})")
                for ln in j["lines"]:
                    acc = per_account.setdefault(str(ln.get("account_code")), [ZERO, ZERO])
                    acc[0] += money(ln.get("debit"))
                    acc[1] += money(ln.get("credit"))
                dr += jdr
                cr += jcr
        except (MoneyError, TypeError, ArithmeticError):
            return problems + ["its journal lines do not carry exact money"]
        expected = (fmt(dr), fmt(cr))
        stated = (("header", row.get("total_debit"), row.get("total_credit")), ("content", totals.get("debit"), totals.get("credit")),
                  ("trial balance", tb.get("total_debit"), tb.get("total_credit")))
        wrong_totals = [f"{name} {d} / {c}" for name, d, c in stated if (d, c) != expected]
        if wrong_totals:
            problems.append(f"its totals disagree with its journal lines ({expected[0]} / {expected[1]}): {', '.join(wrong_totals)}")
        if dr != cr or tb.get("balanced") is not True:
            problems.append("it does not balance")
        tb_rows = tb.get("rows")
        by_lines = {code: (fmt(a[0]), fmt(a[1])) for code, a in per_account.items() if a[0] != ZERO or a[1] != ZERO}
        by_tb = ({str(r.get("code")): (r.get("debit"), r.get("credit")) for r in tb_rows if isinstance(r, dict)}
                 if isinstance(tb_rows, list) else None)
        if by_tb != by_lines or len(tb_rows) != len(by_tb):
            problems.append("its trial balance rows do not agree with its journal lines")

        # the listed journals against the books (immutable; a missing one is an omission, not reported here)
        known = [i for i in ids if isinstance(i, str)]
        books = {j["id"]: j for j in self._load_journals("id IN (SELECT value FROM json_each(?))", (canonical_json(known),))}
        for j in journals:
            book = books.get(j.get("id"))
            if book is None:
                continue
            if _facts(book) != _facts(j):
                problems.append(f"package journal {j.get('id')} does not match the books")
            # a recorded reversal must be the books' one (none recorded while the books have one is an omission)
            stated = j.get("reversed_by")
            if stated is not None and stated != book["reversed_by"]:
                problems.append(f"package journal {j.get('id')} records reversal {stated} that the books do not have")

        # the AP / AR reconciliations repeat the AP / AR sections they were derived from
        recon = pkg.get("reconciliations") if isinstance(pkg.get("reconciliations"), dict) else {}
        for side in ("ap", "ar"):
            section = pkg.get(side) if isinstance(pkg.get(side), dict) else {}
            derived = {"subledger_total": section.get("subledger_total"), "control_balance": section.get("control_balance"),
                       "reconciled": bool(section.get("reconciled"))}
            if recon.get(side) != derived:
                problems.append(f"its {side.upper()} reconciliation does not repeat its {side.upper()} open items section")

        # the CSV files re-render from the content exactly
        ap_items = (pkg.get("ap") or {}).get("items") if isinstance(pkg.get("ap"), dict) else None
        ar_items = (pkg.get("ar") or {}).get("items") if isinstance(pkg.get("ar"), dict) else None
        files = pkg.get("csv") if isinstance(pkg.get("csv"), dict) else {}
        if not all(isinstance(items, list) and all(isinstance(it, dict) for it in items) for items in (ap_items, ar_items)):
            problems.append("its AP or AR open items are not a list of items")
        elif isinstance(pid, str):
            rendered = _csv_files(pid, journals, ap_items, ar_items)
            for name in CSV_FILES:
                if files.get(name) != rendered[name]:
                    problems.append(f"its {name} does not match its content")
        return problems

    # ---- prepare -------------------------------------------------------------------- #

    def prepare_handoff(self, period_id: str, actor: str) -> dict[str, Any]:
        """Prepare an immutable hand-off package for one open period."""
        actor = self._text(actor, "actor")
        with self.db.transaction() as conn:
            self.db.require_write_authority()
            period = self._period(period_id)
            self._require_open(period, "a hand-off is prepared")
            content = self._content(period)
            package_json = canonical_json(content)
            package_hash = sha256_hex(package_json)
            previous = self._rows(period["id"])
            latest = previous[-1] if previous else None
            if latest is not None and latest["package_hash"] == package_hash:
                raise HandoffDuplicate(
                    f"nothing changed since hand-off {latest['id']} (#{latest['sequence']}, hash {package_hash[:12]}) for {period['id']}; "
                    "it is already the current package"
                )
            candidate = {"package_json": package_json, "package_hash": package_hash, "format": FORMAT, "label": LABEL, "period_id": period["id"],
                         "journal_count": content["journal_count"], "total_debit": content["totals"]["debit"], "total_credit": content["totals"]["credit"]}
            problems = self._content_problems(candidate)  # its provenance is the audit entry recorded below
            if problems:  # never store a package the close check would reject
                raise HandoffError(f"the package prepared for {period['id']} fails its own integrity check ({'; '.join(problems)}); nothing is handed off")
            hid = new_id("hof")
            sequence = latest["sequence"] + 1 if latest else 1
            conn.execute(
                """INSERT INTO handoff_packages (id, period_id, sequence, label, format, package_json, package_hash, journal_count, total_debit,
                   total_credit, supersedes, prepared_by, prepared_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (hid, period["id"], sequence, LABEL, FORMAT, package_json, package_hash, content["journal_count"], content["totals"]["debit"],
                 content["totals"]["credit"], latest["id"] if latest else None, actor, utcnow_iso()),
            )
            invalidated = 0
            for prev in previous:  # an acknowledgement was approved on the premise that its package is the period's latest
                invalidated += self.approvals.invalidate_for_subject(SUBJECT_TYPE, prev["id"], reason=f"superseded by hand-off {hid}", actor=actor)
            self.audit.record(actor, PREPARED_ACTION, SUBJECT_TYPE, hid, {
                "period_id": period["id"], "sequence": sequence, "package_hash": package_hash, "journal_count": content["journal_count"],
                "total_debit": content["totals"]["debit"], "total_credit": content["totals"]["credit"],
                "supersedes": latest["id"] if latest else None, "approvals_invalidated": invalidated, "label": LABEL,
            })
        return self.handoff(hid, include_package=True)

    # ---- reading ------------------------------------------------------------------------ #

    def handoff(self, handoff_id: str, *, include_package: bool = False) -> dict[str, Any]:
        row = self._row(handoff_id)
        receipt = self._receipt(row["id"])
        latest = self._latest_row(row["period_id"])
        later = self.db.one("SELECT id FROM handoff_packages WHERE period_id=? AND sequence=?", (row["period_id"], row["sequence"] + 1))
        problems = self._integrity(row)
        out = {k: row[k] for k in ("id", "period_id", "sequence", "label", "format", "package_hash", "journal_count", "total_debit",
                                   "total_credit", "supersedes", "prepared_by", "prepared_at")}
        out.update({
            "status": "acknowledged" if receipt else "prepared",
            "is_latest": latest is not None and latest["id"] == row["id"],
            "superseded_by": later["id"] if later else None,
            "hash_verified": sha256_hex(row["package_json"]) == row["package_hash"],
            "integrity_ok": not problems,
            "integrity_problems": problems,
            "receipt": receipt,
            "receipt_details": self._details(row["id"]),
        })
        if include_package:
            out["package"] = loads(row["package_json"])
        return out

    def handoffs(self, period_id: str | None = None) -> list[dict[str, Any]]:
        if period_id is None:
            rows = self.db.query("SELECT id FROM handoff_packages ORDER BY period_id, sequence")
        else:
            rows = self.db.query("SELECT id FROM handoff_packages WHERE period_id=? ORDER BY sequence", (self._period(period_id)["id"],))
        return [self._summary(r["id"]) for r in rows]

    def _summary(self, handoff_id: str) -> dict[str, Any]:
        h = self.handoff(handoff_id)
        receipt = h.pop("receipt")
        h.pop("receipt_details")
        h["receipt_ref"] = receipt["receipt_ref"] if receipt else None
        h["accountant"] = receipt["accountant"] if receipt else None
        h["acknowledged_at"] = receipt["acknowledged_at"] if receipt else None
        h["omission_count"] = self.omissions(handoff_id)["count"]
        return h

    def package(self, handoff_id: str) -> dict[str, Any]:
        """The package content exactly as prepared and hashed."""
        return loads(self._row(handoff_id)["package_json"])

    def csv_file(self, handoff_id: str, name: str) -> str:
        if name not in CSV_FILES:
            raise HandoffError(f"unknown hand-off file {name!r}; available: {', '.join(CSV_FILES)}")
        return self.package(handoff_id)["csv"][name]

    def verify(self, handoff_id: str) -> dict[str, Any]:
        """Re-perform the package hash from the stored canonical JSON, and the package's integrity
        against its own header, its own figures, its CSV files and the books."""
        row = self._row(handoff_id)
        recomputed = sha256_hex(row["package_json"])
        try:
            canonical = canonical_json(loads(row["package_json"])) == row["package_json"]
        except ValueError:
            canonical = False
        problems = self._integrity(row)
        return {"handoff_id": row["id"], "package_hash": row["package_hash"], "recomputed": recomputed, "canonical": canonical,
                "integrity_problems": problems, "ok": canonical and recomputed == row["package_hash"] and not problems}

    # ---- omissions ------------------------------------------------------------------------ #

    def omissions(self, handoff_id: str) -> dict[str, Any]:
        row = self._row(handoff_id)
        try:
            pkg = loads(row["package_json"])
        except ValueError:
            pkg = {}
        listed = pkg.get("journals") if isinstance(pkg, dict) and isinstance(pkg.get("journals"), list) else []
        listed = [j for j in listed if isinstance(j, dict) and isinstance(j.get("id"), str)]
        in_package = [j["id"] for j in listed]
        reversed_at_package = {j["id"]: j.get("reversed_by") for j in listed}
        known = set(in_package)
        not_in_package = []
        for j in self.db.query("SELECT id, posted_at, description, source_type, source_id, reversal_of FROM journals WHERE period_id=? ORDER BY posted_at, id", (row["period_id"],)):
            if j["id"] in known:
                continue
            amounts = self.db.query("SELECT debit FROM journal_lines WHERE journal_id=?", (j["id"],))
            not_in_package.append({"journal_id": j["id"], "posted_at": j["posted_at"], "description": j["description"], "source_type": j["source_type"],
                                   "source_id": j["source_id"], "reversal_of": j["reversal_of"], "total": fmt(sum((money(a["debit"]) for a in amounts), ZERO))})
        reversed_after = []
        missing = []
        for jid in in_package:
            if self.db.one("SELECT id FROM journals WHERE id=?", (jid,)) is None:
                missing.append(jid)
                continue
            rev = self.db.one("SELECT id, period_id, posted_at FROM journals WHERE reversal_of=? ORDER BY posted_at, id LIMIT 1", (jid,))
            if rev is not None and rev["id"] != reversed_at_package.get(jid):
                reversed_after.append({"journal_id": jid, "reversal_journal_id": rev["id"], "reversal_period_id": rev["period_id"], "reversed_at": rev["posted_at"]})
        count = len(not_in_package) + len(reversed_after) + len(missing)
        return {
            "handoff_id": row["id"], "period_id": row["period_id"], "sequence": row["sequence"],
            "not_in_package": not_in_package, "reversed_after_package": reversed_after, "missing_from_books": missing,
            "count": count, "ok": count == 0,
        }

    # ---- receipt details (pre-step) ------------------------------------------------------- #

    def record_receipt_details(self, handoff_id: str, receipt_ref: str, accountant: str, actor: str) -> dict[str, Any]:
        """Record (or correct, as a new version) the accountant's receipt reference and
        name.  The acknowledgement approval binds the latest version."""
        ref = self._text(receipt_ref, "receipt reference")
        name = self._text(accountant, "accountant name")
        actor = self._text(actor, "actor")
        key = ref_key(ref)
        with self.db.transaction() as conn:
            self.db.require_write_authority()
            row = self._row(handoff_id)
            self._require_open(self._period(row["period_id"]), "receipt details are recorded")
            receipt = self._receipt(row["id"])
            if receipt is not None:
                raise HandoffError(f"hand-off {row['id']} was already acknowledged (receipt {receipt['receipt_ref']}); its receipt details are final")
            # caseless across all of Unicode (SQLite's NOCASE folds ASCII letters only)
            for other in self.db.query("SELECT handoff_id, receipt_ref FROM handoff_receipt_details WHERE handoff_id!=? ORDER BY recorded_at, id", (row["id"],)):
                if ref_key(other["receipt_ref"]) == key:
                    raise HandoffDuplicate(f"receipt reference {ref!r} is already recorded for hand-off {other['handoff_id']} (as {other['receipt_ref']!r}); "
                                           "each receipt has its own reference")
            current = self._details(row["id"])
            if current is not None and current["receipt_ref"] == ref and current["accountant"] == name:
                raise HandoffDuplicate(f"hand-off {row['id']} already records receipt {ref!r} from {name} (version {current['version']})")
            did = new_id("hrd")
            version = current["version"] + 1 if current else 1
            conn.execute(
                "INSERT INTO handoff_receipt_details (id, handoff_id, version, receipt_ref, accountant, recorded_by, recorded_at) VALUES (?,?,?,?,?,?,?)",
                (did, row["id"], version, ref, name, actor, utcnow_iso()),
            )
            invalidated = self.approvals.invalidate_for_subject(SUBJECT_TYPE, row["id"], reason="receipt details changed after the acknowledgement was requested", actor=actor)
            self.audit.record(actor, "handoff.receipt_details_recorded", SUBJECT_TYPE, row["id"], {
                "receipt_details_id": did, "version": version, "receipt_ref": ref, "accountant": name,
                "package_hash": row["package_hash"], "approvals_invalidated": invalidated,
            })
        return self.db.one("SELECT * FROM handoff_receipt_details WHERE id=?", (did,))

    # ---- acknowledgement (approval-bound) --------------------------------------------------- #

    def _period_now(self, period_id: str) -> dict[str, Any]:
        tb = self.ledger.trial_balance(period_id)
        return {"journal_count": tb["journal_count"], "total_debit": tb["total_debit"], "total_credit": tb["total_credit"]}

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation not in OPERATIONS:
            raise HandoffError(f"unknown hand-off operation {operation}")
        row = self._row(subject_id)
        period = self._period(row["period_id"])
        receipt = self._receipt(row["id"])
        details = self._details(row["id"])
        integrity = self._integrity(row)
        # Refused at any transaction depth.  At proposal (request_approval, Ricky) nothing is requested;
        # during execution the error is a stale-approval error, so the core invalidates the approval.
        if receipt is not None:
            raise HandoffRefused(f"hand-off {row['id']} was already acknowledged (receipt {receipt['receipt_ref']})")
        if details is None:
            raise HandoffRefused(f"hand-off {row['id']} has no receipt details; record the accountant's receipt reference and name first (record_receipt_details)")
        if period["status"] != "open":
            raise HandoffRefused(f"period {period['id']} is {period['status']}; a hand-off is acknowledged for an open period only")
        if integrity:
            raise HandoffRefused(f"hand-off {row['id']} fails its integrity check ({'; '.join(integrity)}); prepare a new hand-off")
        latest = self._latest_row(row["period_id"])
        om = self.omissions(row["id"])
        return build_manifest(
            operation=operation,
            subject_type=SUBJECT_TYPE,
            subject_id=row["id"],
            actor_role=actor_role,
            amounts={"package_total_debit": row["total_debit"], "package_total_credit": row["total_credit"]},
            bindings={
                "handoff_id": row["id"],
                "period_id": row["period_id"],
                "sequence": row["sequence"],
                "format": row["format"],
                "label": row["label"],
                "package_hash": row["package_hash"],
                "package_journal_count": row["journal_count"],
                "package_integrity_problems": integrity,
                "latest_handoff_for_period": latest["id"] if latest else None,
                "period_status": period["status"],
                "period_now": self._period_now(row["period_id"]),
                "omissions": {
                    "not_in_package": [o["journal_id"] for o in om["not_in_package"]],
                    "reversed_after_package": [o["journal_id"] for o in om["reversed_after_package"]],
                    "missing_from_books": list(om["missing_from_books"]),
                },
                "omission_count": om["count"],
                "receipt_details_id": details["id"],
                "receipt_details_version": details["version"],
                "receipt_ref": details["receipt_ref"],
                "accountant": details["accountant"],
                "acknowledged_by_receipt": None,  # an acknowledged hand-off is refused above
            },
            entity=self._entity(),
            currency=CURRENCY,
        )

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation != OP_ACKNOWLEDGE:
            raise HandoffError(f"unknown hand-off operation {operation}")
        return self._apply_acknowledge(subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)

    def _apply_acknowledge(self, handoff_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        bound = (manifest or {}).get("bindings") or {}
        with self.db.transaction() as conn:
            row = self._row(handoff_id)
            approval = self.db.one(
                "SELECT id, status, operation, subject_type, subject_id, actor_role, material_hash, consumed_by FROM approvals WHERE id=?", (approval_id,))
            if approval is None or (approval["operation"], approval["subject_type"], approval["subject_id"]) != (OP_ACKNOWLEDGE, SUBJECT_TYPE, row["id"]):
                raise HandoffError(f"approval {approval_id} is not a {OP_ACKNOWLEDGE} approval for hand-off {row['id']}")
            if approval["status"] != "consumed":
                raise HandoffError(f"approval {approval_id} is {approval['status']}; a hand-off is acknowledged only under a consumed approval")
            if approval["consumed_by"] != actor:
                raise HandoffError(f"approval {approval_id} was consumed by {approval['consumed_by']}; {actor} cannot record its receipt")
            if period_id and period_id != row["period_id"]:
                raise HandoffError(f"the approval acknowledges a hand-off of period {row['period_id']}, not {period_id}")
            period = self._period(row["period_id"])
            if period["status"] != "open":
                raise HandoffStale(f"period {period['id']} is {period['status']}; the hand-off can no longer be acknowledged under this approval")
            receipt = self._receipt(row["id"])
            if receipt is not None:
                raise HandoffStale(f"hand-off {row['id']} was already acknowledged (receipt {receipt['receipt_ref']})")
            details = self._details(row["id"])
            if details is None or details["id"] != bound.get("receipt_details_id"):
                raise HandoffStale(f"the receipt details of hand-off {row['id']} changed after approval")
            if sha256_hex(row["package_json"]) != row["package_hash"] or row["package_hash"] != bound.get("package_hash"):
                raise HandoffStale(f"the package of hand-off {row['id']} no longer matches its approved hash")
            integrity = self._integrity(row)
            if integrity:
                raise HandoffStale(f"hand-off {row['id']} fails its integrity check ({'; '.join(integrity)}); it cannot be acknowledged")
            # the facts the human approved must still hold now, whoever consumed the approval and however
            fresh = self.manifest_for(OP_ACKNOWLEDGE, row["id"], actor_role=approval["actor_role"])
            if material_hash(fresh) != approval["material_hash"] or material_hash(manifest or {}) != approval["material_hash"]:
                raise HandoffStale(f"hand-off {row['id']} changed after the acknowledgement was approved; approval {approval_id} no longer matches it")
            om = self.omissions(row["id"])
            rid = new_id("hrc")
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO handoff_receipts (id, handoff_id, receipt_details_id, receipt_ref, accountant, package_hash, journal_count, total_debit,
                   total_credit, omission_count, approval_id, acknowledged_by, acknowledged_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rid, row["id"], details["id"], details["receipt_ref"], details["accountant"], row["package_hash"], row["journal_count"],
                 row["total_debit"], row["total_credit"], om["count"], approval_id, actor, now),
            )
            invalidated = self.approvals.invalidate_for_subject(SUBJECT_TYPE, row["id"], reason=f"hand-off {row['id']} already acknowledged", actor=actor)
            self.audit.record(actor, "handoff.acknowledged", SUBJECT_TYPE, row["id"], {
                "receipt_id": rid, "approval_id": approval_id, "receipt_ref": details["receipt_ref"], "accountant": details["accountant"],
                "package_hash": row["package_hash"], "period_id": row["period_id"], "journal_count": row["journal_count"],
                "total_debit": row["total_debit"], "omission_count": om["count"], "approvals_invalidated": invalidated,
            })
        return {
            "handoff": row["id"], "status": "acknowledged", "receipt_id": rid, "receipt_ref": details["receipt_ref"],
            "accountant": details["accountant"], "period_id": row["period_id"], "package_hash": row["package_hash"],
            "journal_count": row["journal_count"], "total_debit": row["total_debit"], "total_credit": row["total_credit"],
            "omission_count": om["count"], "acknowledged_at": now,
        }

    # ---- close checklist hook ---------------------------------------------------------------- #

    def close_checks(self, period_id: str) -> list[dict[str, Any]]:
        latest = self._latest_row(period_id)
        if latest is None:
            return [{"check": CHECK_NAME, "ok": True,
                     "detail": f"no shadow hand-off prepared for {period_id}; the hand-off is optional in the prototype (informational)"}]
        head = f"latest hand-off {latest['id']} (#{latest['sequence']}, hash {str(latest['package_hash'])[:12]})"
        problems = []
        integrity = self._integrity(latest)
        if integrity:
            problems.append(f"{head} fails its integrity check ({'; '.join(integrity)}); prepare a new hand-off")
        receipt = self._receipt(latest["id"])
        if receipt is None:
            problems.append(f"{head} is not acknowledged; record the accountant's receipt through {OP_ACKNOWLEDGE}")
        elif (receipt["package_hash"], receipt["journal_count"], receipt["total_debit"], receipt["total_credit"]) != (
                latest["package_hash"], latest["journal_count"], latest["total_debit"], latest["total_credit"]):
            problems.append(f"{head} receipt {receipt['receipt_ref']} does not carry the package's hash, journal count and totals")
        om = self.omissions(latest["id"])
        if om["count"]:
            parts = []
            if om["not_in_package"]:
                parts.append("journal(s) posted after the package: " + ", ".join(o["journal_id"] for o in om["not_in_package"]))
            if om["reversed_after_package"]:
                parts.append("package journal(s) reversed later: " + ", ".join(o["journal_id"] for o in om["reversed_after_package"]))
            if om["missing_from_books"]:
                parts.append("package journal(s) missing from the books: " + ", ".join(om["missing_from_books"]))
            problems.append(f"{head} has {om['count']} omission(s) ({'; '.join(parts)}); prepare a new hand-off")
        else:
            now = self._period_now(period_id)
            stated = {"journal_count": latest["journal_count"], "total_debit": latest["total_debit"], "total_credit": latest["total_credit"]}
            if now != stated:
                problems.append(f"{head} states {stated['journal_count']} journal(s) totalling {stated['total_debit']} / {stated['total_credit']}, "
                                f"but the period now has {now['journal_count']} totalling {now['total_debit']} / {now['total_credit']}; prepare a new hand-off")
        if problems:
            return [{"check": CHECK_NAME, "ok": False, "detail": "; ".join(problems)}]
        return [{"check": CHECK_NAME, "ok": True,
                 "detail": f"{head} acknowledged by {receipt['accountant']} (receipt {receipt['receipt_ref']}); no omissions"}]

    # ---- state and export ---------------------------------------------------------------------- #

    def state(self, project_id: str) -> dict[str, Any]:
        """Entity-level: hand-offs per period with status and omission counts."""
        periods = []
        all_summaries = []
        for p in self.db.query("SELECT id, name, status FROM periods ORDER BY start_date, id"):
            summaries = [self._summary(r["id"]) for r in self.db.query("SELECT id FROM handoff_packages WHERE period_id=? ORDER BY sequence", (p["id"],))]
            all_summaries.extend(summaries)
            periods.append({
                "period_id": p["id"], "name": p["name"], "status": p["status"], "handoffs": summaries,
                "latest": summaries[-1]["id"] if summaries else None, "close_check": self.close_checks(p["id"])[0],
            })
        return {
            "label": LABEL, "format": FORMAT, "scope": "entity", "project_id": project_id, "periods": periods,
            "handoff_count": len(all_summaries),
            "unacknowledged": sum(1 for s in all_summaries if s["status"] != "acknowledged"),
            "with_omissions": sum(1 for s in all_summaries if s["omission_count"]),
            "failing_integrity": sum(1 for s in all_summaries if not s["integrity_ok"]),
        }

    def audit_export(self) -> dict[str, Any]:
        packages = self.db.query("SELECT * FROM handoff_packages ORDER BY period_id, sequence")
        for p in packages:
            p["hash_verified"] = sha256_hex(p["package_json"]) == p["package_hash"]
            p["integrity_problems"] = self._integrity(p)
        omissions = []
        for p in packages:
            om = self.omissions(p["id"])
            omissions.append({
                "handoff_id": p["id"], "period_id": p["period_id"], "sequence": p["sequence"], "count": om["count"],
                "not_in_package": [o["journal_id"] for o in om["not_in_package"]],
                "reversed_after_package": [o["journal_id"] for o in om["reversed_after_package"]],
                "missing_from_books": om["missing_from_books"],
            })
        return {
            "label": LABEL,
            "format": FORMAT,
            "packages": packages,
            "receipt_details": self.db.query("SELECT * FROM handoff_receipt_details ORDER BY handoff_id, version"),
            "receipts": self.db.query("SELECT * FROM handoff_receipts ORDER BY acknowledged_at, id"),
            "omissions": omissions,
        }
