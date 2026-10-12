"""Bank statement import and bank reconciliation (entity level, SHADOW).

A bank statement is imported for one bank-control account (``1000``) and one
accounting period.  The statement must prove itself: opening balance plus the
signed line amounts (+ deposit, - withdrawal) equals the closing balance
exactly, or nothing is imported.  Statement references are unique per account.
Every statement gets an immutable ``import_seq`` (its place in import order).

Every line receives an immutable fingerprint::

    sha256(account | date | amount | normalised reference | normalised description | occurrence)

where *occurrence* is the line's index among identical lines in the same
statement (so two genuine identical charges on one statement stay distinct).
A line whose fingerprint was already imported by an earlier statement is
SKIPPED and reported; overlapping statement exports therefore never double
count.  The statement keeps the list of lines it repeated, so its
reconciliation still covers them.  New lines dated before the statement's
period are imported but reported as warnings (with the status of the period
they fall in).

Matching pairs a statement line with a GL line (``journal_lines``) on the same
account whose signed amount (debit - credit) equals the line amount.  Each
statement line and each GL line is matched at most once (partial UNIQUE
indexes over active matches).  ``auto_match`` prefers a GL line whose journal
description, line memo or journal source id carries the statement reference;
when several candidates remain it leaves the line unmatched and reports it as
ambiguous.  The amount-only fallback never takes a GL line that carries a
*different* reference of the same shape (``sim_000999`` versus
``sim_000001``); such a line is reported as ambiguous.  Matches are never
deleted: ``unmatch`` releases a match and the released row stays as history.

Opening balance: ``clear_opening_balance`` lets the account's earliest
statement designate the GL lines that make up its (non-zero) opening balance,
i.e. bank history that cleared before the first imported statement.  They are
stored as matches with basis ``opening`` (no statement line) and must total
the statement's opening balance exactly.

Which bank activity a statement S "sees" (its view):

* its own lines and the earlier lines it repeated (always);
* any other statement line dated before S's coverage start (S's earliest
  line date, or its period start when it has no lines): that is history inside
  S's opening balance;
* any other statement line dated before S's cutoff that was imported BEFORE S.
  A line imported after S never changes S unless it predates S's coverage, so
  a later export (even one with a same-day transaction on S's cutoff date)
  cannot break an earlier statement that already reconciled;
* opening items designated on S or on a statement ordered before S
  (period start, import order).

Reconciliation of a statement::

    gl_balance          = account balance from journals in periods with start_date <= statement period end
    unmatched_gl_lines  = GL lines in that scope not cleared by a match in S's view (items in transit)
    adjusted_gl_balance = gl_balance - in_transit_total
    difference          = statement_closing - adjusted_gl_balance
    reconciled          = no unmatched statement lines and difference == 0.00

Approval-bound operations (fixture policy ``cipher-posting-rules/1``):

* ``banking.post_fee`` (subject: statement line) - an unmatched withdrawal the
  books do not have yet is booked Dr 6000 bank fees / Cr <bank account> in the
  statement's period and matched to the new GL line.  It is refused (and a
  granted approval is invalidated at execute time) when the charge is already
  in the books: a live fee journal for the same line (e.g. after its fee match
  was released), or an unmatched GL line of the same amount that books the same
  fee to 6000 or carries the line's reference.  Any other unmatched GL line of
  the same amount is bound into the manifest, so the approver sees it and a new
  one appearing after approval makes the approval stale.
* ``banking.lock_reconciliation`` (subject: statement) - requires a reconciled
  statement at execute time, records an immutable reconciliation snapshot plus
  its evidence (every match that cleared something in the statement's view and
  every GL line it carried in transit) and freezes the statement's matches.
  Schema triggers reject new or released matches on a locked statement and the
  release of any evidence match, whichever statement owns it; the service also
  refuses a new match that would clear a GL line inside a locked statement's
  view.  A locked reconciliation's difference therefore cannot drift.  In the same
  transaction the lock hands the GL lines its evidence matched to statement lines to
  ``Payments.mark_bank_reconciled_for_journal_lines``: a settled payment whose settlement
  bank line is among them advances to ``bank_reconciled`` (the result lists them under
  ``payments_bank_reconciled``).  A later return of that payment still books normally and its
  bank line reconciles on a later statement.  The ``banking_payment_reconciled_guard`` schema
  entry refuses any bank-reconciled marker (raw SQL included) that does not name a locked
  reconciliation whose evidence matched that GL line to a bank statement line; the payments
  schema checks that the line is the intent's own settlement bank line.

Record methods (``auto_match``, ``manual_match``, ``unmatch``,
``clear_opening_balance``) bump the statement version, so a granted fee or lock
approval goes stale when the match set it was approved against changes.
"""
from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal
from typing import Any

from ..core.approvals import StaleApprovalError, build_manifest
from ..core.db import register_schema_version
from ..core.ids import canonical_json, hash_json, loads, new_id, sha256_hex, utcnow_iso
from ..core.money import ZERO, D, MoneyError, fmt, money, total
from . import payments as _payments  # noqa: F401  (registers the payment lifecycle columns before this module's guard entry)

SCHEMA_NAME = "banking"
PLUGIN_NAME = "banking"
POSTING_RULE = "cipher-posting-rules/1"
FINGERPRINT_RULE = "account|date|amount|reference|description|occurrence (sha256, normalised lower-case, whitespace collapsed)"

STATEMENT_SUBJECT = "banking_statement"
LINE_SUBJECT = "banking_line"
MATCH_SUBJECT = "banking_match"

OP_POST_FEE = "banking.post_fee"
OP_LOCK = "banking.lock_reconciliation"

BANK_ACCOUNT = "1000"
FEE_ACCOUNT = "6000"

# far above any real bank statement, far below the 28-digit decimal context
MAX_ABS_AMOUNT = Decimal("1000000000000000")

SCHEMA_STATEMENTS = [
    """CREATE TABLE banking_statements (
        id TEXT PRIMARY KEY,
        import_seq INTEGER NOT NULL UNIQUE,
        account_code TEXT NOT NULL REFERENCES accounts(code),
        statement_ref TEXT NOT NULL COLLATE NOCASE,
        period_id TEXT NOT NULL REFERENCES periods(id),
        end_date TEXT NOT NULL,
        opening_balance TEXT NOT NULL,
        closing_balance TEXT NOT NULL,
        line_count INTEGER NOT NULL,
        imported_count INTEGER NOT NULL,
        skipped_count INTEGER NOT NULL,
        skipped_json TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('open','locked')),
        version INTEGER NOT NULL DEFAULT 1,
        imported_by TEXT NOT NULL,
        imported_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        lock_approval_id TEXT REFERENCES approvals(id),
        locked_by TEXT,
        locked_at TEXT,
        UNIQUE (account_code, statement_ref)
    )""",
    """CREATE TABLE banking_lines (
        id TEXT PRIMARY KEY,
        statement_id TEXT NOT NULL REFERENCES banking_statements(id),
        line_no INTEGER NOT NULL,
        account_code TEXT NOT NULL REFERENCES accounts(code),
        txn_date TEXT NOT NULL,
        amount TEXT NOT NULL,
        description TEXT NOT NULL,
        reference TEXT NOT NULL,
        occurrence INTEGER NOT NULL,
        fingerprint TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        UNIQUE (statement_id, line_no)
    )""",
    # a match pairs a statement line with a GL line; basis 'opening' pairs no line:
    # the GL line cleared the bank before the statement's opening balance
    """CREATE TABLE banking_matches (
        id TEXT PRIMARY KEY,
        statement_id TEXT NOT NULL REFERENCES banking_statements(id),
        line_id TEXT REFERENCES banking_lines(id),
        journal_line_id TEXT NOT NULL REFERENCES journal_lines(id),
        amount TEXT NOT NULL,
        basis TEXT NOT NULL CHECK (basis IN ('reference','amount','manual','fee','opening')),
        status TEXT NOT NULL CHECK (status IN ('active','released')),
        matched_by TEXT NOT NULL,
        matched_at TEXT NOT NULL,
        released_by TEXT,
        released_at TEXT,
        CHECK ((basis = 'opening') = (line_id IS NULL))
    )""",
    """CREATE TABLE banking_reconciliations (
        id TEXT PRIMARY KEY,
        statement_id TEXT NOT NULL UNIQUE REFERENCES banking_statements(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        account_code TEXT NOT NULL REFERENCES accounts(code),
        cutoff_date TEXT NOT NULL,
        statement_closing TEXT NOT NULL,
        gl_balance TEXT NOT NULL,
        in_transit_total TEXT NOT NULL,
        adjusted_gl_balance TEXT NOT NULL,
        difference TEXT NOT NULL CHECK (difference = '0.00'),
        statement_hash TEXT NOT NULL,
        match_set_hash TEXT NOT NULL,
        report_json TEXT NOT NULL,
        report_hash TEXT NOT NULL,
        approval_id TEXT NOT NULL REFERENCES approvals(id),
        locked_by TEXT NOT NULL,
        locked_at TEXT NOT NULL
    )""",
    # what a locked reconciliation rested on: the matches that cleared GL lines in its view
    # and the GL lines it carried in transit
    """CREATE TABLE banking_reconciliation_evidence (
        reconciliation_id TEXT NOT NULL REFERENCES banking_reconciliations(id),
        statement_id TEXT NOT NULL REFERENCES banking_statements(id),
        kind TEXT NOT NULL CHECK (kind IN ('match','in_transit')),
        journal_line_id TEXT NOT NULL REFERENCES journal_lines(id),
        match_id TEXT REFERENCES banking_matches(id),
        CHECK ((kind = 'match') = (match_id IS NOT NULL)),
        PRIMARY KEY (reconciliation_id, kind, journal_line_id)
    )""",
    # each statement line and each GL line is matched at most once at any time
    "CREATE UNIQUE INDEX banking_matches_one_per_line ON banking_matches(line_id) WHERE status = 'active'",
    "CREATE UNIQUE INDEX banking_matches_one_per_gl_line ON banking_matches(journal_line_id) WHERE status = 'active'",
    "CREATE INDEX banking_lines_statement ON banking_lines(statement_id)",
    "CREATE INDEX banking_statements_period ON banking_statements(period_id)",
    "CREATE INDEX banking_evidence_match ON banking_reconciliation_evidence(match_id)",
    # ---- statements: imported content is immutable; the only transition is open -> locked
    "CREATE TRIGGER banking_statements_no_delete BEFORE DELETE ON banking_statements BEGIN SELECT RAISE(ABORT, 'bank statements are never deleted'); END",
    """CREATE TRIGGER banking_statements_insert_open BEFORE INSERT ON banking_statements
        WHEN NEW.status IS NOT 'open'
        BEGIN SELECT RAISE(ABORT, 'a bank statement is imported open'); END""",
    """CREATE TRIGGER banking_statements_content_immutable
        BEFORE UPDATE OF id, import_seq, account_code, statement_ref, period_id, end_date, opening_balance, closing_balance, line_count,
                         imported_count, skipped_count, skipped_json, content_hash, imported_by, imported_at ON banking_statements
        BEGIN SELECT RAISE(ABORT, 'imported bank statements are immutable'); END""",
    """CREATE TRIGGER banking_statements_locked_final BEFORE UPDATE ON banking_statements
        WHEN OLD.status = 'locked'
        BEGIN SELECT RAISE(ABORT, 'a locked bank reconciliation is final'); END""",
    """CREATE TRIGGER banking_statements_status_forward_only BEFORE UPDATE OF status ON banking_statements
        WHEN NEW.status IS NOT OLD.status AND NOT (OLD.status = 'open' AND NEW.status = 'locked')
        BEGIN SELECT RAISE(ABORT, 'illegal bank statement status transition'); END""",
    """CREATE TRIGGER banking_statements_lock_needs_reconciliation BEFORE UPDATE OF status ON banking_statements
        WHEN NEW.status = 'locked' AND NOT EXISTS (SELECT 1 FROM banking_reconciliations WHERE statement_id = NEW.id)
        BEGIN SELECT RAISE(ABORT, 'a statement is locked only through a recorded reconciliation'); END""",
    # ---- lines and fingerprints are immutable
    "CREATE TRIGGER banking_lines_no_update BEFORE UPDATE ON banking_lines BEGIN SELECT RAISE(ABORT, 'bank statement lines and fingerprints are immutable'); END",
    "CREATE TRIGGER banking_lines_no_delete BEFORE DELETE ON banking_lines BEGIN SELECT RAISE(ABORT, 'bank statement lines are never deleted'); END",
    """CREATE TRIGGER banking_lines_insert_consistent BEFORE INSERT ON banking_lines
        BEGIN
            SELECT CASE
                WHEN (SELECT status FROM banking_statements WHERE id = NEW.statement_id) IS NOT 'open'
                THEN RAISE(ABORT, 'lines are only added to an open statement')
                WHEN (SELECT account_code FROM banking_statements WHERE id = NEW.statement_id) IS NOT NEW.account_code
                THEN RAISE(ABORT, 'statement line account differs from its statement')
            END;
        END""",
    # ---- matches: frozen once the statement is locked or once they are evidence; released, never deleted
    "CREATE TRIGGER banking_matches_no_delete BEFORE DELETE ON banking_matches BEGIN SELECT RAISE(ABORT, 'bank matches are never deleted; release them'); END",
    """CREATE TRIGGER banking_matches_insert_unlocked BEFORE INSERT ON banking_matches
        WHEN (SELECT status FROM banking_statements WHERE id = NEW.statement_id) IS NOT 'open'
        BEGIN SELECT RAISE(ABORT, 'bank reconciliation is locked; its matches are frozen'); END""",
    """CREATE TRIGGER banking_matches_insert_consistent BEFORE INSERT ON banking_matches
        BEGIN
            SELECT CASE
                WHEN NEW.status IS NOT 'active'
                THEN RAISE(ABORT, 'a new bank match must be active')
                WHEN NEW.line_id IS NOT NULL AND (SELECT statement_id FROM banking_lines WHERE id = NEW.line_id) IS NOT NEW.statement_id
                THEN RAISE(ABORT, 'bank match statement does not own the line')
                WHEN NEW.line_id IS NOT NULL AND (SELECT amount FROM banking_lines WHERE id = NEW.line_id) IS NOT NEW.amount
                THEN RAISE(ABORT, 'bank match amount differs from the statement line')
                WHEN (SELECT account_code FROM journal_lines WHERE id = NEW.journal_line_id)
                     IS NOT (SELECT account_code FROM banking_statements WHERE id = NEW.statement_id)
                THEN RAISE(ABORT, 'GL line is on a different account than the statement')
            END;
        END""",
    """CREATE TRIGGER banking_matches_update_unlocked BEFORE UPDATE ON banking_matches
        WHEN (SELECT status FROM banking_statements WHERE id = OLD.statement_id) IS NOT 'open'
        BEGIN SELECT RAISE(ABORT, 'bank reconciliation is locked; its matches are frozen'); END""",
    """CREATE TRIGGER banking_matches_evidence_frozen BEFORE UPDATE ON banking_matches
        WHEN EXISTS (SELECT 1 FROM banking_reconciliation_evidence WHERE match_id = OLD.id)
        BEGIN SELECT RAISE(ABORT, 'bank match is evidence for a locked reconciliation; it is frozen'); END""",
    """CREATE TRIGGER banking_matches_release_only BEFORE UPDATE ON banking_matches
        WHEN NOT (OLD.status = 'active' AND NEW.status = 'released'
                  AND NEW.id IS OLD.id AND NEW.statement_id IS OLD.statement_id AND NEW.line_id IS OLD.line_id
                  AND NEW.journal_line_id IS OLD.journal_line_id AND NEW.amount IS OLD.amount AND NEW.basis IS OLD.basis
                  AND NEW.matched_by IS OLD.matched_by AND NEW.matched_at IS OLD.matched_at)
        BEGIN SELECT RAISE(ABORT, 'an active bank match can only be released'); END""",
    # ---- reconciliation snapshots and their evidence are immutable
    "CREATE TRIGGER banking_reconciliations_no_update BEFORE UPDATE ON banking_reconciliations BEGIN SELECT RAISE(ABORT, 'locked bank reconciliations are immutable'); END",
    "CREATE TRIGGER banking_reconciliations_no_delete BEFORE DELETE ON banking_reconciliations BEGIN SELECT RAISE(ABORT, 'locked bank reconciliations are never deleted'); END",
    """CREATE TRIGGER banking_evidence_insert_consistent BEFORE INSERT ON banking_reconciliation_evidence
        WHEN NOT EXISTS (SELECT 1 FROM banking_reconciliations WHERE id = NEW.reconciliation_id AND statement_id = NEW.statement_id)
        BEGIN SELECT RAISE(ABORT, 'reconciliation evidence needs its recorded reconciliation'); END""",
    "CREATE TRIGGER banking_evidence_no_update BEFORE UPDATE ON banking_reconciliation_evidence BEGIN SELECT RAISE(ABORT, 'bank reconciliation evidence is immutable'); END",
    "CREATE TRIGGER banking_evidence_no_delete BEFORE DELETE ON banking_reconciliation_evidence BEGIN SELECT RAISE(ABORT, 'bank reconciliation evidence is never deleted'); END",
]

# The payment lifecycle columns (payments' entries, registered by importing payments above) and
# this plugin's own tables must both exist before the guard below is created: a trigger naming a
# missing table makes SQLite refuse ALTER TABLE ... RENAME anywhere in the schema.  Registering
# this plugin's entry here (the plugin loader registers the same entry again, a no-op by name)
# puts the banking tables ahead of the guard in the catalog.
register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)

# A payment's bank-reconciled marker (payments' lifecycle columns) names a reconciliation and the
# GL line it matched.  Only a locked reconciliation whose evidence matched that line to a bank
# statement line (an opening item pairs no statement line) may set it, whatever writes it.  The
# guard fires only for a marker the payments trigger accepts (written once, on a settled intent,
# naming its own settlement bank line), so the refusal reason never depends on trigger order.
PAYMENT_GUARD_SCHEMA_NAME = "banking_payment_reconciled_guard"
PAYMENT_GUARD_SCHEMA_STATEMENTS = [
    """CREATE TRIGGER banking_payment_bank_reconciled_needs_locked_match
        BEFORE UPDATE OF bank_reconciled_at, bank_reconciliation_id, bank_journal_line_id ON payment_intents
        WHEN (NEW.bank_reconciled_at IS NOT OLD.bank_reconciled_at OR NEW.bank_reconciliation_id IS NOT OLD.bank_reconciliation_id
              OR NEW.bank_journal_line_id IS NOT OLD.bank_journal_line_id)
         AND OLD.bank_reconciled_at IS NULL AND OLD.bank_reconciliation_id IS NULL AND OLD.bank_journal_line_id IS NULL
         AND NEW.bank_reconciled_at IS NOT NULL AND NEW.bank_reconciliation_id IS NOT NULL AND NEW.bank_journal_line_id IS NOT NULL
         AND trim(NEW.bank_reconciled_at) <> '' AND trim(NEW.bank_reconciliation_id) <> ''
         AND OLD.status IS 'settled' AND NEW.status IS 'settled'
         AND EXISTS (SELECT 1 FROM journal_lines l JOIN journals j ON j.id = l.journal_id
                     JOIN provider_events pe ON j.source_type = 'provider_event' AND j.source_id = pe.id
                     WHERE l.id = NEW.bank_journal_line_id AND l.account_code = '1000' AND pe.intent_id = NEW.id AND pe.kind = 'settled')
         AND NOT EXISTS (
            SELECT 1 FROM banking_reconciliation_evidence e
            JOIN banking_reconciliations r ON r.id = e.reconciliation_id AND r.statement_id = e.statement_id
            JOIN banking_statements s ON s.id = e.statement_id
            JOIN banking_matches m ON m.id = e.match_id AND m.journal_line_id = e.journal_line_id
            WHERE e.reconciliation_id = NEW.bank_reconciliation_id AND e.journal_line_id = NEW.bank_journal_line_id
              AND e.kind = 'match' AND m.line_id IS NOT NULL AND s.status = 'locked')
        BEGIN SELECT RAISE(ABORT, 'a payment is bank-reconciled only by a locked bank reconciliation whose evidence matched its settlement bank line to a bank statement line'); END""",
]
register_schema_version(PAYMENT_GUARD_SCHEMA_NAME, PAYMENT_GUARD_SCHEMA_STATEMENTS)


class BankingError(RuntimeError):
    """Invalid bank statement input, or a reconciliation action the current state does not allow."""


class FeeAlreadyBookedError(BankingError, StaleApprovalError):
    """The bank charge behind a statement line is already in the books.

    Requesting ``banking.post_fee`` is refused (a ``BankingError``).  When it is
    raised while a granted approval is being executed, the books changed after
    the approval was granted, so the service treats the approval as stale and
    invalidates it durably (a ``StaleApprovalError``)."""


# --------------------------------------------------------------------------- #
# Pure helpers                                                                 #
# --------------------------------------------------------------------------- #

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_WORD_CHARS = "0-9a-z_"


def _z(value) -> Decimal:
    """Cents, with negative zero folded to 0.00 so stored strings stay canonical."""
    m = money(value)
    return ZERO if m == 0 else m


def _exact_money(value, label: str) -> Decimal:
    """Exact cents: floats, non-numbers, sub-cent precision and absurd magnitudes are rejected, never rounded."""
    try:
        raw = D(value)
    except MoneyError as exc:
        raise BankingError(f"{label} is not exact money: {exc}") from exc
    if not raw.is_finite():
        raise BankingError(f"{label} is not a finite amount: {value!r}")
    if abs(raw) >= MAX_ABS_AMOUNT:
        raise BankingError(f"{label} {value!r} exceeds the supported magnitude (less than {fmt(MAX_ABS_AMOUNT)})")
    try:
        cents = money(raw)
    except ArithmeticError as exc:  # decimal.InvalidOperation and friends
        raise BankingError(f"{label} is not exact money: {value!r}") from exc
    if cents != raw:
        raise BankingError(f"{label} must be a whole number of cents, got {value!r}")
    return _z(cents)


def _text(value, label: str, *, required: bool) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise BankingError(f"{label} must be a string")
    if required and not value.strip():
        raise BankingError(f"{label} is required and must be a non-empty string")
    return value.strip()


def _date(value, label: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise BankingError(f"{label} must be a YYYY-MM-DD date, got {value!r}")
    try:
        _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise BankingError(f"{label} is not a calendar date: {value!r}") from exc
    return value


def _norm(text) -> str:
    """Normalised form used in fingerprints and reference search."""
    return " ".join(str(text or "").split()).lower()


def _fp_field(text: str) -> str:
    # escape the delimiter so two different field splits can never hash alike
    return text.replace("\\", "\\\\").replace("|", "\\|")


def line_fingerprint(account_code: str, txn_date: str, amount, reference: str, description: str, occurrence: int) -> str:
    """The immutable identity of a bank line: account|date|amount|reference|description|occurrence."""
    parts = [account_code, txn_date, fmt(_z(amount)), _norm(reference), _norm(description), str(int(occurrence))]
    return sha256_hex("|".join(_fp_field(p) for p in parts))


_REF_FIELDS = ("description", "memo", "source_id")


def _carries_reference(gl: dict[str, Any], ref_norm: str) -> bool:
    """True when the journal description, line memo or journal source id contains the
    reference as a whole token (``sim_000001`` does not match ``sim_0000010``)."""
    if not ref_norm:
        return False
    pattern = re.compile(rf"(?<![{_WORD_CHARS}]){re.escape(ref_norm)}(?![{_WORD_CHARS}])")
    return any(pattern.search(_norm(gl.get(field))) for field in _REF_FIELDS)


def _reference_shape(ref_norm: str):
    """A pattern matching references of the same shape (digit runs as wildcards), or None
    when the reference has no letters or no digits (then no shape can be told apart)."""
    if not ref_norm or not re.search(r"[a-z]", ref_norm) or not re.search(r"\d", ref_norm):
        return None
    body = "".join(r"\d+" if part.isdigit() else re.escape(part) for part in re.split(r"(\d+)", ref_norm) if part)
    return re.compile(rf"(?<![{_WORD_CHARS}]){body}(?![{_WORD_CHARS}])")


def _contradicting_reference(gl: dict[str, Any], ref_norm: str) -> str | None:
    """The first reference of the same shape but a different value carried by the GL line
    (``sim_000001`` contradicts a statement line referenced ``sim_000999``), else None."""
    pattern = _reference_shape(ref_norm)
    if pattern is None:
        return None
    for field in _REF_FIELDS:
        for found in pattern.finditer(_norm(gl.get(field))):
            if found.group(0) != ref_norm:
                return found.group(0)
    return None


def _plan_matches(pending: list[dict[str, Any]], available: list[dict[str, Any]]) -> tuple[list[tuple[dict, dict, str]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministic matching plan.

    A statement line claims the GL lines of equal signed amount; if any of them carry
    its reference, only those (basis "reference"), otherwise those that do not carry a
    different reference of the same shape (basis "amount").  A line is matched only when
    its claim is a single GL line that no rival claims (reference claims outrank amount
    claims).  Matching repeats until nothing changes; every line left over is
    "ambiguous" (several candidates, contested, or only contradicting candidates) or
    "unmatched" (no candidate at all)."""
    pending = list(pending)
    avail = list(available)
    planned: list[tuple[dict, dict, str]] = []

    def claims_for(lines, pool):
        out = []
        for ln in lines:
            amount_c = [g for g in pool if g["signed"] == ln["amount_d"]]
            ref_c = [g for g in amount_c if _carries_reference(g, ln["ref_norm"])]
            if ref_c:
                out.append((ln, ref_c, "reference"))
                continue
            clean = [g for g in amount_c if _contradicting_reference(g, ln["ref_norm"]) is None]
            if clean or not amount_c:
                out.append((ln, clean, "amount"))
            else:
                out.append((ln, amount_c, "contradicted"))
        return out

    while pending:
        claims = claims_for(pending, avail)
        chosen: list[tuple[dict, dict, str]] = []
        for basis in ("reference", "amount"):
            for ln, cands, b in claims:
                if b != basis or len(cands) != 1:
                    continue
                gid = cands[0]["id"]
                rivals = [
                    other for other, oc, ob in claims
                    if other["id"] != ln["id"] and ob in ("reference", "amount") and (basis == "amount" or ob == "reference")
                    and any(g["id"] == gid for g in oc)
                ]
                if not rivals:
                    chosen.append((ln, cands[0], basis))
            if chosen:
                break
        if not chosen:
            break
        for ln, g, basis in chosen:
            planned.append((ln, g, basis))
            pending = [p for p in pending if p["id"] != ln["id"]]
            avail = [a for a in avail if a["id"] != g["id"]]

    ambiguous: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for ln, cands, basis in claims_for(pending, avail):
        item = {"line_id": ln["id"], "line_no": ln["line_no"], "date": ln["txn_date"], "amount": ln["amount"], "reference": ln["reference"], "description": ln["description"]}
        if basis == "contradicted":
            found = sorted({_contradicting_reference(g, ln["ref_norm"]) for g in cands})
            ambiguous.append({**item, "reason": f"the GL line(s) of this amount carry a different reference ({', '.join(found)})", "candidates": [g["id"] for g in cands]})
        elif not cands:
            unmatched.append({**item, "reason": "no unmatched GL line of this amount on the account"})
        elif len(cands) > 1:
            why = (f"{len(cands)} GL lines carry the reference" if basis == "reference"
                   else f"{len(cands)} GL lines have this amount and no reference disambiguates")
            ambiguous.append({**item, "reason": why, "candidates": [g["id"] for g in cands]})
        else:
            ambiguous.append({**item, "reason": "another statement line competes for the same GL line", "candidates": [cands[0]["id"]]})
    return planned, ambiguous, unmatched


def _clears_for(view: dict[str, Any], m: dict[str, Any]) -> bool:
    """Does active match ``m`` clear its GL line in the statement view ``view``?
    (The rules are spelled out in the module docstring.)"""
    if m["line_id"] is None:  # opening item: cleared before its statement's opening balance
        return (m["owner_period_start"], m["owner_seq"]) <= view["order"]
    if m["line_id"] in view["eff_ids"]:
        return True
    if m["txn_date"] < view["coverage_start"]:
        return True
    return m["owner_seq"] < view["seq"] and m["txn_date"] < view["cutoff"]


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

    # ---- import ------------------------------------------------------------- #

    def import_statement(self, *, statement_ref: str, period_id: str, opening_balance, closing_balance, lines: list[dict[str, Any]],
                         actor: str, account_code: str = BANK_ACCOUNT, end_date: str | None = None) -> dict[str, Any]:
        """Import one bank statement.  Opening + lines must equal closing exactly;
        lines already imported by an earlier statement are skipped and reported."""
        ref = _text(statement_ref, "statement_ref", required=True)
        account_code = _text(account_code, "account_code", required=True)
        opening = _exact_money(opening_balance, "opening_balance")
        closing = _exact_money(closing_balance, "closing_balance")
        if not isinstance(lines, (list, tuple)):
            raise BankingError("lines must be a list of statement lines")
        parsed: list[dict[str, Any]] = []
        for idx, raw in enumerate(lines, start=1):
            if not isinstance(raw, dict):
                raise BankingError(f"line {idx} must be an object with date, amount, description and reference")
            txn_date = _date(raw.get("date"), f"line {idx} date")
            amt = _exact_money(raw.get("amount"), f"line {idx} amount")
            if amt == ZERO:
                raise BankingError(f"line {idx} amount must not be zero")
            description = _text(raw.get("description", ""), f"line {idx} description", required=False)
            reference = _text(raw.get("reference", ""), f"line {idx} reference", required=False)
            if not description and not reference:
                raise BankingError(f"line {idx} needs a description or a reference")
            parsed.append({"line_no": idx, "txn_date": txn_date, "amount": amt, "description": description, "reference": reference})
        movement = total(p["amount"] for p in parsed)
        if _z(opening + movement) != closing:
            raise BankingError(
                f"statement {ref} does not balance: opening {fmt(opening)} + lines {fmt(movement)} = {fmt(_z(opening + movement))}, "
                f"but closing is {fmt(closing)}"
            )
        explicit_end = _date(end_date, "end_date") if end_date is not None else None

        # identical lines within this statement are told apart by their occurrence index
        seen: dict[tuple, int] = {}
        for p in parsed:
            key = (p["txn_date"], fmt(p["amount"]), _norm(p["reference"]), _norm(p["description"]))
            p["occurrence"] = seen.get(key, 0)
            seen[key] = p["occurrence"] + 1
            p["fingerprint"] = line_fingerprint(account_code, p["txn_date"], p["amount"], p["reference"], p["description"], p["occurrence"])

        statement_id = new_id("bst")
        with self.db.transaction() as conn:
            acct = self.db.one("SELECT code, control_kind FROM accounts WHERE code=?", (account_code,))
            if acct is None:
                raise BankingError(f"unknown account {account_code}")
            if acct["control_kind"] != "bank":
                raise BankingError(f"account {account_code} is not a bank account")
            period = self.db.one("SELECT * FROM periods WHERE id=?", (period_id,))
            if period is None:
                raise BankingError(f"unknown period {period_id}")
            if period["status"] != "open":
                raise BankingError(f"period {period_id} is {period['status']}; bank statements are imported only into open periods")
            late = [p for p in parsed if p["txn_date"] > period["end_date"]]
            if late:
                raise BankingError(f"line {late[0]['line_no']} is dated {late[0]['txn_date']}, after period {period_id} ends {period['end_date']}")
            if explicit_end is not None:
                if explicit_end > period["end_date"] or explicit_end < period["start_date"]:
                    raise BankingError(f"end_date {explicit_end} is outside period {period_id} ({period['start_date']} to {period['end_date']})")
                after = [p for p in parsed if p["txn_date"] > explicit_end]
                if after:
                    raise BankingError(f"line {after[0]['line_no']} is dated {after[0]['txn_date']}, after the statement end_date {explicit_end}")
                cutoff = explicit_end
            else:
                cutoff = max((p["txn_date"] for p in parsed), default=period["end_date"])
            dup = self.db.one("SELECT id FROM banking_statements WHERE account_code=? AND statement_ref=?", (account_code, ref))
            if dup is not None:
                raise BankingError(f"statement {ref} was already imported for account {account_code} ({dup['id']})")

            imported: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []
            for p in parsed:
                prior = self.db.one("SELECT id, statement_id FROM banking_lines WHERE fingerprint=?", (p["fingerprint"],))
                if prior is not None:
                    skipped.append({
                        "line_no": p["line_no"], "date": p["txn_date"], "amount": fmt(p["amount"]), "reference": p["reference"],
                        "description": p["description"], "fingerprint": p["fingerprint"],
                        "duplicate_of_line_id": prior["id"], "duplicate_of_statement_id": prior["statement_id"],
                    })
                else:
                    p["id"] = new_id("bln")
                    imported.append(p)
            # new transactions dated before the statement's period are accepted (the period they
            # fall in may be closed; any fee still posts in this open period) but reported
            warnings: list[dict[str, Any]] = []
            for p in imported:
                if p["txn_date"] < period["start_date"]:
                    home = self.db.one("SELECT id, status FROM periods WHERE start_date <= ? AND end_date >= ? ORDER BY start_date LIMIT 1", (p["txn_date"], p["txn_date"]))
                    warnings.append({
                        "kind": "dated_before_statement_period", "line_no": p["line_no"], "date": p["txn_date"], "amount": fmt(p["amount"]),
                        "period_id": home["id"] if home else None, "period_status": home["status"] if home else None,
                        "detail": (f"line {p['line_no']} is dated {p['txn_date']}, before period {period_id} starts {period['start_date']}"
                                   + (f"; it falls in {home['status']} period {home['id']}" if home else "; no period covers that date")),
                    })
            content_hash = hash_json({
                "account_code": account_code, "statement_ref": ref, "period_id": period_id, "end_date": cutoff,
                "opening_balance": fmt(opening), "closing_balance": fmt(closing),
                "fingerprints": [p["fingerprint"] for p in parsed],
            })
            import_seq = self.db.scalar("SELECT COALESCE(MAX(import_seq), 0) + 1 FROM banking_statements")
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO banking_statements (id, import_seq, account_code, statement_ref, period_id, end_date, opening_balance, closing_balance,
                   line_count, imported_count, skipped_count, skipped_json, content_hash, status, version, imported_by, imported_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'open',1,?,?,?)""",
                (statement_id, import_seq, account_code, ref, period_id, cutoff, fmt(opening), fmt(closing), len(parsed), len(imported), len(skipped),
                 canonical_json(skipped), content_hash, actor, now, now),
            )
            for p in imported:
                conn.execute(
                    """INSERT INTO banking_lines (id, statement_id, line_no, account_code, txn_date, amount, description, reference, occurrence, fingerprint, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (p["id"], statement_id, p["line_no"], account_code, p["txn_date"], fmt(p["amount"]), p["description"], p["reference"], p["occurrence"], p["fingerprint"], now),
                )
            self.audit.record(actor, "banking.statement_imported", STATEMENT_SUBJECT, statement_id, {
                "account_code": account_code, "statement_ref": ref, "period_id": period_id, "end_date": cutoff, "import_seq": import_seq,
                "opening_balance": fmt(opening), "closing_balance": fmt(closing), "content_hash": content_hash,
                "line_count": len(parsed), "imported": [p["fingerprint"] for p in imported],
                "skipped": [{"line_no": s["line_no"], "fingerprint": s["fingerprint"], "duplicate_of_line_id": s["duplicate_of_line_id"]} for s in skipped],
                "warnings": [{"kind": w["kind"], "line_no": w["line_no"], "period_id": w["period_id"], "period_status": w["period_status"]} for w in warnings],
            })
        result = self.statement(statement_id)
        result["warnings"] = warnings
        return result

    # ---- reading -------------------------------------------------------------- #

    def _statement_row(self, statement_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM banking_statements WHERE id=?", (statement_id,))
        if row is None:
            raise BankingError(f"unknown bank statement {statement_id}")
        return row

    def _line_row(self, line_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM banking_lines WHERE id=?", (line_id,))
        if row is None:
            raise BankingError(f"unknown bank statement line {line_id}")
        return row

    def _lines_with_matches(self, where: str, params: tuple) -> list[dict[str, Any]]:
        rows = self.db.query(
            f"""SELECT l.*, m.id AS match_id, m.journal_line_id AS journal_line_id, m.basis AS match_basis
                FROM banking_lines l LEFT JOIN banking_matches m ON m.line_id = l.id AND m.status = 'active'
                WHERE {where} ORDER BY l.statement_id, l.line_no""",
            params,
        )
        for r in rows:
            r["matched"] = r["match_id"] is not None
        return rows

    def lines(self, statement_id: str) -> list[dict[str, Any]]:
        self._statement_row(statement_id)
        return self._lines_with_matches("l.statement_id = ?", (statement_id,))

    def _effective_lines(self, st: dict[str, Any]) -> list[dict[str, Any]]:
        """The statement's own lines plus the earlier lines it repeated (skipped duplicates)."""
        own = self._lines_with_matches("l.statement_id = ?", (st["id"],))
        for r in own:
            r["owned_by_statement"] = st["id"]
        repeated_ids = [s["duplicate_of_line_id"] for s in loads(st["skipped_json"])]
        repeated: list[dict[str, Any]] = []
        for lid in repeated_ids:
            rows = self._lines_with_matches("l.id = ?", (lid,))
            for r in rows:
                r["owned_by_statement"] = r["statement_id"]
            repeated.extend(rows)
        return own + repeated

    def statement(self, statement_id: str) -> dict[str, Any]:
        row = self._statement_row(statement_id)
        row["skipped"] = loads(row.pop("skipped_json"))
        row["lines"] = self._lines_with_matches("l.statement_id = ?", (statement_id,))
        return row

    def statements(self, period_id: str | None = None) -> list[dict[str, Any]]:
        if period_id:
            rows = self.db.query("SELECT id FROM banking_statements WHERE period_id=? ORDER BY import_seq", (period_id,))
        else:
            rows = self.db.query("SELECT id FROM banking_statements ORDER BY import_seq")
        return [self.statement(r["id"]) for r in rows]

    def match(self, match_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM banking_matches WHERE id=?", (match_id,))
        if row is None:
            raise BankingError(f"unknown bank match {match_id}")
        return row

    def matches(self, statement_id: str, include_released: bool = False) -> list[dict[str, Any]]:
        self._statement_row(statement_id)
        if include_released:
            return self.db.query("SELECT * FROM banking_matches WHERE statement_id=? ORDER BY matched_at, id", (statement_id,))
        return self.db.query("SELECT * FROM banking_matches WHERE statement_id=? AND status='active' ORDER BY matched_at, id", (statement_id,))

    def _gl_lines(self, account_code: str, scope_end: str) -> list[dict[str, Any]]:
        """GL lines on the account in periods starting on or before ``scope_end``."""
        rows = self.db.query(
            """SELECT l.id, l.journal_id, l.line_no, l.debit, l.credit, l.memo, l.project_id, l.party_id,
                      j.description, j.source_type, j.source_id, j.period_id, j.posted_at, j.reversal_of, p.start_date,
                      (SELECT r.id FROM journals r WHERE r.reversal_of = j.id) AS reversed_by
               FROM journal_lines l JOIN journals j ON j.id = l.journal_id JOIN periods p ON p.id = j.period_id
               WHERE l.account_code = ? AND p.start_date <= ?
               ORDER BY j.posted_at, j.id, l.line_no""",
            (account_code, scope_end),
        )
        for r in rows:
            r["signed"] = _z(money(r["debit"]) - money(r["credit"]))
        return rows

    def _active_matches_by_gl(self, account_code: str) -> dict[str, dict[str, Any]]:
        """Active matches on the account (statement-line and opening matches), keyed by GL line,
        with what ``_clears_for`` needs: the bank line date and the owning statement's order."""
        rows = self.db.query(
            """SELECT m.*, b.txn_date AS txn_date, s.import_seq AS owner_seq, p.start_date AS owner_period_start
               FROM banking_matches m
               JOIN banking_statements s ON s.id = m.statement_id
               JOIN periods p ON p.id = s.period_id
               LEFT JOIN banking_lines b ON b.id = m.line_id
               WHERE m.status = 'active' AND s.account_code = ?""",
            (account_code,),
        )
        return {r["journal_line_id"]: r for r in rows}

    # ---- views and reconciliation ---------------------------------------------------- #

    def _view(self, st: dict[str, Any]) -> dict[str, Any]:
        """What bank activity statement ``st`` can see (see ``_clears_for``)."""
        period = self.ledger.period(st["period_id"])
        effective = self._effective_lines(st)
        dates = [ln["txn_date"] for ln in effective]
        return {
            "id": st["id"], "ref": st["statement_ref"], "seq": st["import_seq"], "period": period,
            "order": (period["start_date"], st["import_seq"]), "scope_end": period["end_date"],
            "coverage_start": min(dates) if dates else period["start_date"], "cutoff": st["end_date"],
            "effective": effective, "eff_ids": {ln["id"] for ln in effective},
        }

    def _locked_views(self, account_code: str, exclude: str | None = None) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM banking_statements WHERE account_code=? AND status='locked' ORDER BY import_seq", (account_code,))
        return [self._view(r) for r in rows if r["id"] != exclude]

    @staticmethod
    def _probe(st: dict[str, Any], period: dict[str, Any], line: dict[str, Any] | None) -> dict[str, Any]:
        """The ``_clears_for`` facts of a match about to be created on ``st``."""
        return {"line_id": line["id"] if line else None, "txn_date": line["txn_date"] if line else None,
                "owner_seq": st["import_seq"], "owner_period_start": period["start_date"]}

    @staticmethod
    def _locked_conflict(views: list[dict[str, Any]], probe: dict[str, Any], gl_period_start: str) -> dict[str, Any] | None:
        """The locked statement whose view the new match would change (its GL line is in that
        statement's scope and the match would clear it there), else None."""
        for v in views:
            if gl_period_start <= v["scope_end"] and _clears_for(v, probe):
                return v
        return None

    def reconciliation(self, statement_id: str) -> dict[str, Any]:
        """Live bank reconciliation of one statement (see the module docstring for the formulas)."""
        st = self._statement_row(statement_id)
        return self._reconcile(st)

    def _reconcile(self, st: dict[str, Any], *, evidence: bool = False) -> dict[str, Any]:
        view = self._view(st)
        gl = self._gl_lines(st["account_code"], view["scope_end"])
        active = self._active_matches_by_gl(st["account_code"])
        gl_balance = ZERO
        in_transit: list[dict[str, Any]] = []
        cleared: list[tuple[str, str]] = []
        for g in gl:
            gl_balance += g["signed"]
            m = active.get(g["id"])
            if m is not None and _clears_for(view, m):
                cleared.append((m["id"], g["id"]))
                continue
            in_transit.append({
                "journal_line_id": g["id"], "journal_id": g["journal_id"], "period_id": g["period_id"],
                "description": g["description"], "memo": g["memo"], "source_type": g["source_type"], "source_id": g["source_id"],
                "amount": fmt(g["signed"]),
                # matched, but outside this statement's view (a later import or a date after its cutoff)
                "match_id": m["id"] if m is not None else None,
                "matched_to_line": m["line_id"] if m is not None else None,
            })
        in_transit_total = total(i["amount"] for i in in_transit)
        gl_balance = _z(gl_balance)
        adjusted = _z(gl_balance - in_transit_total)
        closing = money(st["closing_balance"])
        difference = _z(closing - adjusted)
        effective = view["effective"]
        unmatched_lines = [
            {"line_id": ln["id"], "line_no": ln["line_no"], "statement_id": ln["owned_by_statement"], "date": ln["txn_date"],
             "amount": ln["amount"], "reference": ln["reference"], "description": ln["description"]}
            for ln in effective if not ln["matched"]
        ]
        own_opening = sorted((m for m in active.values() if m["statement_id"] == st["id"] and m["line_id"] is None), key=lambda m: m["id"])
        line_matches = sorted([ln["id"], ln["journal_line_id"], ln["match_id"]] for ln in effective if ln["matched"])
        match_set = line_matches + [["opening", m["journal_line_id"], m["id"]] for m in own_opening]
        reconciled = not unmatched_lines and difference == ZERO
        locked = None
        if st["status"] == "locked":
            snap = self.db.one("SELECT * FROM banking_reconciliations WHERE statement_id=?", (st["id"],))
            if snap is not None:
                snap.pop("report_json", None)
                locked = snap
        out = {
            "statement_id": st["id"],
            "statement_ref": st["statement_ref"],
            "account_code": st["account_code"],
            "period_id": st["period_id"],
            "scope_period_end": view["scope_end"],
            "coverage_start": view["coverage_start"],
            "cutoff_date": view["cutoff"],
            "status": st["status"],
            "statement_version": st["version"],
            "statement_opening": st["opening_balance"],
            "statement_closing": fmt(closing),
            "gl_balance": fmt(gl_balance),
            "unmatched_statement_lines": unmatched_lines,
            "unmatched_gl_lines": in_transit,
            "in_transit_total": fmt(in_transit_total),
            "adjusted_gl_balance": fmt(adjusted),
            "difference": fmt(difference),
            "reconciled": reconciled,
            "line_count": len(effective),
            "matched_count": len(line_matches),
            "opening_items": [{"match_id": m["id"], "journal_line_id": m["journal_line_id"], "amount": m["amount"]} for m in own_opening],
            "opening_items_total": fmt(total(m["amount"] for m in own_opening)),
            "cleared_count": len(cleared),
            "statement_hash": st["content_hash"],
            "match_set_hash": hash_json(match_set),
            "cleared_hash": hash_json(sorted(mid for mid, _ in cleared)),
            "in_transit_hash": hash_json(sorted(i["journal_line_id"] for i in in_transit)),
            "locked_reconciliation": locked,
        }
        if evidence:
            ev: dict[str, str] = dict(cleared)
            for ln in effective:
                if ln["matched"]:
                    ev.setdefault(ln["match_id"], ln["journal_line_id"])
            for m in own_opening:
                ev.setdefault(m["id"], m["journal_line_id"])
            out["_evidence"] = {"matches": sorted(ev.items()), "in_transit": [i["journal_line_id"] for i in in_transit]}
        return out

    def reconciliation_status(self, period_id: str) -> dict[str, Any]:
        """Is the period's bank reconciliation done?  Required when a statement exists for
        the period or a bank account has GL activity in it; reconciled only when at least
        one statement exists and every one of the period's statements is locked (and its
        live reconciliation still agrees)."""
        period = self.db.one("SELECT * FROM periods WHERE id=?", (period_id,))
        if period is None:
            raise BankingError(f"unknown period {period_id}")
        stmts = self.db.query("SELECT * FROM banking_statements WHERE period_id=? ORDER BY import_seq", (period_id,))
        bank_accounts = [r["code"] for r in self.db.query("SELECT code FROM accounts WHERE control_kind='bank' ORDER BY code")]
        active_accounts = [
            code for code in bank_accounts
            if self.db.scalar(
                "SELECT COUNT(*) FROM journal_lines l JOIN journals j ON j.id = l.journal_id WHERE l.account_code=? AND j.period_id=?",
                (code, period_id),
            )
        ]
        stmt_accounts = {s["account_code"] for s in stmts}
        missing = [a for a in active_accounts if a not in stmt_accounts]
        unlocked = [s for s in stmts if s["status"] != "locked"]
        summaries = []
        for s in stmts:
            rec = self._reconcile(s)
            summaries.append({
                "statement_id": s["id"], "statement_ref": s["statement_ref"], "account_code": s["account_code"], "status": s["status"],
                "version": s["version"], "reconciled": rec["reconciled"], "difference": rec["difference"],
                "unmatched_statement_lines": len(rec["unmatched_statement_lines"]), "in_transit_total": rec["in_transit_total"],
            })
        # defence in depth: the evidence freeze keeps a locked statement reconciled
        drifted = [s for s in summaries if s["status"] == "locked" and not s["reconciled"]]
        required = bool(stmts) or bool(active_accounts)
        reconciled = bool(stmts) and not unlocked and not missing and not drifted
        if not required:
            detail = f"no bank statement and no bank account activity in {period_id}"
        elif not stmts:
            detail = f"bank account {', '.join(active_accounts)} has activity in {period_id} but no bank statement was imported"
        elif missing:
            detail = f"no bank statement imported for account {', '.join(missing)} in {period_id}"
        elif unlocked:
            refs = ", ".join(s["statement_ref"] for s in unlocked)
            detail = f"{len(unlocked)} of {len(stmts)} bank statement(s) for {period_id} not reconciled and locked: {refs}"
        elif drifted:
            refs = ", ".join(f"{s['statement_ref']} (difference {s['difference']})" for s in drifted)
            detail = f"locked bank reconciliation(s) for {period_id} no longer agree with the ledger: {refs}"
        else:
            detail = f"{len(stmts)} bank statement(s) for {period_id} reconciled and locked"
        return {"period_id": period_id, "required": required, "reconciled": reconciled, "detail": detail, "statements": summaries}

    def close_checks(self, period_id: str) -> list[dict[str, Any]]:
        status = self.reconciliation_status(period_id)
        return [{"check": "bank reconciliation", "ok": status["reconciled"] or not status["required"], "detail": status["detail"]}]

    # ---- matching ------------------------------------------------------------------ #

    def _require_unlocked(self, st: dict[str, Any]) -> None:
        if st["status"] != "open":
            raise BankingError(f"statement {st['statement_ref']} reconciliation is {st['status']}; its matches are frozen")

    def _require_not_evidence(self, match_id: str) -> None:
        row = self.db.one(
            """SELECT s.statement_ref FROM banking_reconciliation_evidence e JOIN banking_statements s ON s.id = e.statement_id
               WHERE e.match_id = ? ORDER BY s.import_seq LIMIT 1""",
            (match_id,),
        )
        if row is not None:
            raise BankingError(f"match {match_id} is evidence for the locked reconciliation of statement {row['statement_ref']}; it is frozen")

    def _active_match_for_line(self, line_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM banking_matches WHERE line_id=? AND status='active'", (line_id,))

    def _gl_line(self, journal_line_id: str) -> dict[str, Any]:
        g = self.db.one(
            """SELECT l.*, j.period_id, p.start_date FROM journal_lines l JOIN journals j ON j.id = l.journal_id
               JOIN periods p ON p.id = j.period_id WHERE l.id = ?""",
            (journal_line_id,),
        )
        if g is None:
            raise BankingError(f"unknown GL line {journal_line_id}")
        g["signed"] = _z(money(g["debit"]) - money(g["credit"]))
        return g

    def _require_matchable_gl(self, st: dict[str, Any], period: dict[str, Any], g: dict[str, Any]) -> None:
        if g["account_code"] != st["account_code"]:
            raise BankingError(f"GL line {g['id']} is on account {g['account_code']}, not the statement account {st['account_code']}")
        if self.db.one("SELECT id FROM banking_matches WHERE journal_line_id=? AND status='active'", (g["id"],)) is not None:
            raise BankingError(f"GL line {g['id']} is already matched")
        if g["start_date"] > period["end_date"]:
            raise BankingError(f"GL line {g['id']} is in period {g['period_id']}, after the statement period {st['period_id']}")

    def _insert_match(self, st: dict[str, Any], period: dict[str, Any], *, line: dict[str, Any] | None, journal_line_id: str,
                      gl_period_start: str, basis: str, actor: str, amount: Decimal | None = None,
                      views: list[dict[str, Any]] | None = None) -> str:
        """Caller holds the transaction and has validated the pair.  Refuses a match that would
        change the view of a locked reconciliation."""
        if views is None:
            views = self._locked_views(st["account_code"], exclude=st["id"])
        blocker = self._locked_conflict(views, self._probe(st, period, line), gl_period_start)
        if blocker is not None:
            raise BankingError(
                f"matching GL line {journal_line_id} would change the locked reconciliation of statement {blocker['ref']}, "
                f"which carried it as not cleared by the bank"
            )
        match_id = new_id("bmt")
        stored_amount = line["amount"] if line is not None else fmt(amount)
        self.db.execute(
            """INSERT INTO banking_matches (id, statement_id, line_id, journal_line_id, amount, basis, status, matched_by, matched_at)
               VALUES (?,?,?,?,?,?,'active',?,?)""",
            (match_id, st["id"], line["id"] if line is not None else None, journal_line_id, stored_amount, basis, actor, utcnow_iso()),
        )
        if line is not None:
            # a fee posting for a line that is now matched would book it twice
            self.approvals.invalidate_for_subject(LINE_SUBJECT, line["id"], reason="statement line matched", actor=actor)
        self.audit.record(actor, "banking.matched", MATCH_SUBJECT, match_id, {
            "statement_id": st["id"], "line_id": line["id"] if line is not None else None,
            "fingerprint": line["fingerprint"] if line is not None else None, "journal_line_id": journal_line_id,
            "amount": stored_amount, "basis": basis,
        })
        return match_id

    def _touch(self, st: dict[str, Any], *, actor: str, reason: str) -> int:
        """The statement's match set changed: bump its version and drop open lock approvals."""
        self.db.execute("UPDATE banking_statements SET version=version+1, updated_at=? WHERE id=?", (utcnow_iso(), st["id"]))
        self.approvals.invalidate_for_subject(STATEMENT_SUBJECT, st["id"], reason=f"match set changed: {reason}", actor=actor)
        return self._statement_row(st["id"])["version"]

    def auto_match(self, statement_id: str, actor: str) -> dict[str, Any]:
        """Match the statement's unmatched lines to unmatched GL lines (see ``_plan_matches``)."""
        with self.db.transaction():
            st = self._statement_row(statement_id)
            self._require_unlocked(st)
            period = self.ledger.period(st["period_id"])
            pending = [ln for ln in self._lines_with_matches("l.statement_id = ?", (statement_id,)) if not ln["matched"]]
            for ln in pending:
                ln["amount_d"] = money(ln["amount"])
                ln["ref_norm"] = _norm(ln["reference"])
            matched_gl = self._active_matches_by_gl(st["account_code"])
            available = [g for g in self._gl_lines(st["account_code"], period["end_date"]) if g["id"] not in matched_gl]
            planned, ambiguous, unmatched = _plan_matches(pending, available)
            views = self._locked_views(st["account_code"], exclude=st["id"])
            matched = []
            for ln, g, basis in planned:
                blocker = self._locked_conflict(views, self._probe(st, period, ln), g["start_date"])
                if blocker is not None:
                    unmatched.append({
                        "line_id": ln["id"], "line_no": ln["line_no"], "date": ln["txn_date"], "amount": ln["amount"],
                        "reference": ln["reference"], "description": ln["description"],
                        "reason": f"matching GL line {g['id']} would change the locked reconciliation of statement {blocker['ref']}",
                    })
                    continue
                mid = self._insert_match(st, period, line=ln, journal_line_id=g["id"], gl_period_start=g["start_date"], basis=basis, actor=actor, views=views)
                matched.append({"match_id": mid, "line_id": ln["id"], "line_no": ln["line_no"], "journal_line_id": g["id"], "amount": ln["amount"], "basis": basis})
            version = self._touch(st, actor=actor, reason=f"auto-matched {len(matched)} line(s)") if matched else st["version"]
            self.audit.record(actor, "banking.auto_match_run", STATEMENT_SUBJECT, statement_id, {
                "matched": [m["match_id"] for m in matched], "ambiguous": [a["line_id"] for a in ambiguous],
                "unmatched": [u["line_id"] for u in unmatched], "statement_version": version,
            })
        return {"statement_id": statement_id, "matched": matched, "ambiguous": ambiguous, "unmatched": unmatched, "statement_version": version}

    def manual_match(self, line_id: str, journal_line_id: str, actor: str) -> dict[str, Any]:
        """Match one statement line to one GL line chosen by a person.  Same account, same
        signed amount, GL line within the statement's period scope, both currently unmatched."""
        with self.db.transaction():
            line = self._line_row(line_id)
            st = self._statement_row(line["statement_id"])
            self._require_unlocked(st)
            if self._active_match_for_line(line_id) is not None:
                raise BankingError(f"statement line {line_id} is already matched; unmatch it first")
            g = self._gl_line(journal_line_id)
            period = self.ledger.period(st["period_id"])
            self._require_matchable_gl(st, period, g)
            if g["signed"] != money(line["amount"]):
                raise BankingError(f"GL line signed amount {fmt(g['signed'])} does not equal the statement line amount {line['amount']}")
            match_id = self._insert_match(st, period, line=line, journal_line_id=journal_line_id, gl_period_start=g["start_date"], basis="manual", actor=actor)
            self._touch(st, actor=actor, reason=f"manual match {match_id}")
        return self.match(match_id)

    def unmatch(self, match_id: str, actor: str) -> dict[str, Any]:
        """Release an active match while the statement's reconciliation is not locked and no
        locked reconciliation rests on it."""
        with self.db.transaction():
            m = self.match(match_id)
            if m["status"] != "active":
                raise BankingError(f"match {match_id} is already {m['status']}")
            st = self._statement_row(m["statement_id"])
            self._require_unlocked(st)
            self._require_not_evidence(match_id)
            self.db.execute("UPDATE banking_matches SET status='released', released_by=?, released_at=? WHERE id=?", (actor, utcnow_iso(), match_id))
            version = self._touch(st, actor=actor, reason=f"match {match_id} released")
            self.audit.record(actor, "banking.unmatched", MATCH_SUBJECT, match_id, {
                "statement_id": st["id"], "line_id": m["line_id"], "journal_line_id": m["journal_line_id"], "amount": m["amount"],
                "basis": m["basis"], "statement_version": version,
            })
        return self.match(match_id)

    def clear_opening_balance(self, statement_id: str, journal_line_ids: list[str], actor: str) -> dict[str, Any]:
        """Designate the GL lines that make up the opening balance of the account's earliest
        statement: bank history that cleared before the first imported statement.  Together
        with the statement's existing opening items they must total its opening balance exactly.
        Opening items are matches with basis ``opening``; ``unmatch`` releases one."""
        if not isinstance(journal_line_ids, (list, tuple)) or not journal_line_ids:
            raise BankingError("journal_line_ids must be a non-empty list of GL line ids")
        ids = [_text(x, "journal_line_id", required=True) for x in journal_line_ids]
        if len(set(ids)) != len(ids):
            raise BankingError("a GL line is listed twice in the opening items")
        with self.db.transaction():
            st = self._statement_row(statement_id)
            self._require_unlocked(st)
            period = self.ledger.period(st["period_id"])
            earlier = self.db.one(
                """SELECT s.statement_ref FROM banking_statements s JOIN periods p ON p.id = s.period_id
                   WHERE s.account_code = ? AND s.id <> ? AND (p.start_date < ? OR (p.start_date = ? AND s.import_seq < ?))
                   ORDER BY p.start_date, s.import_seq LIMIT 1""",
                (st["account_code"], st["id"], period["start_date"], period["start_date"], st["import_seq"]),
            )
            if earlier is not None:
                raise BankingError(
                    f"opening items belong to the account's earliest statement; statement {earlier['statement_ref']} comes before {st['statement_ref']}"
                )
            existing = self.db.query("SELECT amount FROM banking_matches WHERE statement_id=? AND basis='opening' AND status='active'", (st["id"],))
            chosen = []
            for jl in ids:
                g = self._gl_line(jl)
                self._require_matchable_gl(st, period, g)
                chosen.append(g)
            items_total = _z(total(m["amount"] for m in existing) + total(g["signed"] for g in chosen))
            opening = money(st["opening_balance"])
            if items_total != opening:
                raise BankingError(
                    f"opening items total {fmt(items_total)} but statement {st['statement_ref']} opens at {fmt(opening)}; "
                    f"designate the GL lines that make up the opening balance exactly"
                )
            views = self._locked_views(st["account_code"], exclude=st["id"])
            created = []
            for g in chosen:
                mid = self._insert_match(st, period, line=None, journal_line_id=g["id"], gl_period_start=g["start_date"], basis="opening",
                                         actor=actor, amount=g["signed"], views=views)
                created.append({"match_id": mid, "journal_line_id": g["id"], "amount": fmt(g["signed"])})
            version = self._touch(st, actor=actor, reason=f"{len(created)} opening item(s) designated")
            self.audit.record(actor, "banking.opening_cleared", STATEMENT_SUBJECT, st["id"], {
                "opening_balance": fmt(opening), "items": created, "statement_version": version,
            })
        return {"statement_id": st["id"], "opening_balance": fmt(opening), "opening_items": created, "statement_version": version}

    # ---- approvals: manifests ------------------------------------------------------- #

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation == OP_POST_FEE:
            return self._fee_manifest(subject_id, actor_role=actor_role)
        if operation == OP_LOCK:
            return self._lock_manifest(subject_id, actor_role=actor_role)
        raise BankingError(f"unknown banking operation {operation}")

    def _live_fee_journals(self, line_id: str) -> list[dict[str, Any]]:
        """Fee journals booked for this statement line and not reversed."""
        return self.db.query(
            """SELECT j.id FROM journals j WHERE j.source_type = ? AND j.source_id = ? AND j.reversal_of IS NULL
               AND NOT EXISTS (SELECT 1 FROM journals r WHERE r.reversal_of = j.id) ORDER BY j.posted_at, j.id""",
            (LINE_SUBJECT, line_id),
        )

    def _same_charge(self, g: dict[str, Any], line: dict[str, Any], fee: Decimal) -> str | None:
        """Why the unmatched GL line ``g`` evidently is this bank charge, else None."""
        if g["source_type"] == LINE_SUBJECT and g["source_id"] == line["id"]:
            return "is a fee journal for this statement line"
        if self.db.scalar(
            "SELECT COUNT(*) FROM journal_lines WHERE journal_id=? AND account_code=? AND debit=?", (g["journal_id"], FEE_ACCOUNT, fmt(fee))
        ):
            return f"books a {fmt(fee)} bank fee to {FEE_ACCOUNT}"
        if _carries_reference(g, _norm(line["reference"])):
            return f"carries the line reference {line['reference']}"
        return None

    def _check_fee_line(self, line: dict[str, Any], st: dict[str, Any]) -> tuple[Decimal, list[dict[str, Any]]]:
        """Validate a fee posting for ``line``; returns the fee and the other unmatched GL lines
        of the same amount (bound into the manifest so the approver sees them)."""
        self._require_unlocked(st)
        if self._active_match_for_line(line["id"]) is not None:
            raise BankingError(f"statement line {line['id']} is already matched; there is nothing to book")
        amt = money(line["amount"])
        if amt >= 0:
            raise BankingError(f"statement line {line['id']} is a deposit of {line['amount']}; only withdrawals are booked as bank fees")
        period = self.ledger.period(st["period_id"])
        if period["status"] != "open":
            raise BankingError(f"statement period {st['period_id']} is {period['status']}; a fee cannot be posted into it")
        fee = _z(-amt)
        booked = self._live_fee_journals(line["id"])
        if booked:
            jid = booked[0]["id"]
            bank_gl = self.db.one("SELECT id FROM journal_lines WHERE journal_id=? AND account_code=?", (jid, st["account_code"]))
            raise FeeAlreadyBookedError(
                f"the fee for statement line {line['id']} is already booked in journal {jid}; re-match the line to its GL line "
                f"{bank_gl['id'] if bank_gl else '?'} (manual_match) instead of booking it again, or reverse journal {jid} first"
            )
        matched_gl = self._active_matches_by_gl(st["account_code"])
        candidates = [
            g for g in self._gl_lines(st["account_code"], period["end_date"])
            if g["signed"] == amt and g["id"] not in matched_gl and not g["reversal_of"] and not g["reversed_by"]
        ]
        for g in candidates:
            why = self._same_charge(g, line, fee)
            if why:
                raise FeeAlreadyBookedError(
                    f"statement line {line['id']} ({line['amount']}) is already in the books: unmatched GL line {g['id']} "
                    f"(journal {g['journal_id']}) {why}; match the line to it (manual_match or auto_match) instead of booking the fee again"
                )
        others = sorted(
            ({"journal_line_id": g["id"], "journal_id": g["journal_id"], "description": g["description"]} for g in candidates),
            key=lambda o: o["journal_line_id"],
        )
        return fee, others

    def _fee_manifest(self, line_id: str, *, actor_role: str) -> dict[str, Any]:
        line = self._line_row(line_id)
        st = self._statement_row(line["statement_id"])
        fee, others = self._check_fee_line(line, st)
        return build_manifest(
            operation=OP_POST_FEE,
            subject_type=LINE_SUBJECT,
            subject_id=line_id,
            actor_role=actor_role,
            amounts={"fee": fee, "line_amount": line["amount"]},
            bindings={
                "line_fingerprint": line["fingerprint"],
                "line_date": line["txn_date"],
                "line_reference": line["reference"],
                "statement_id": st["id"],
                "statement_ref": st["statement_ref"],
                "statement_version": st["version"],
                "statement_hash": st["content_hash"],
                "period_id": st["period_id"],
                "bank_account": st["account_code"],
                "fee_account": FEE_ACCOUNT,
                "posting_rule": POSTING_RULE,
                # other unmatched GL lines of the same amount the approver should know about
                "unmatched_equal_amount_gl_lines": others,
            },
        )

    def _lock_manifest(self, statement_id: str, *, actor_role: str) -> dict[str, Any]:
        st = self._statement_row(statement_id)
        self._require_unlocked(st)
        rec = self._reconcile(st)
        if not rec["reconciled"]:
            raise BankingError(
                f"statement {st['statement_ref']} is not reconciled: difference {rec['difference']}, "
                f"{len(rec['unmatched_statement_lines'])} unmatched statement line(s)"
            )
        return build_manifest(
            operation=OP_LOCK,
            subject_type=STATEMENT_SUBJECT,
            subject_id=statement_id,
            actor_role=actor_role,
            amounts={
                "statement_closing": rec["statement_closing"], "gl_balance": rec["gl_balance"], "in_transit_total": rec["in_transit_total"],
                "adjusted_gl_balance": rec["adjusted_gl_balance"], "difference": rec["difference"],
            },
            bindings={
                "statement_version": st["version"],
                "statement_hash": rec["statement_hash"],
                "match_set_hash": rec["match_set_hash"],
                "cleared_hash": rec["cleared_hash"],
                "in_transit_hash": rec["in_transit_hash"],
                "matched_count": rec["matched_count"],
                "period_id": st["period_id"],
                "bank_account": st["account_code"],
                "cutoff_date": rec["cutoff_date"],
                "reconciled": rec["reconciled"],
            },
        )

    # ---- approvals: execution ------------------------------------------------------- #

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation == OP_POST_FEE:
            return self._apply_post_fee(subject_id, approval_id=approval_id, actor=actor, period_id=period_id)
        if operation == OP_LOCK:
            return self._apply_lock(subject_id, approval_id=approval_id, actor=actor, period_id=period_id)
        raise BankingError(f"unknown banking operation {operation}")

    def _apply_post_fee(self, line_id: str, *, approval_id: str, actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction():
            line = self._line_row(line_id)
            st = self._statement_row(line["statement_id"])
            if period_id is not None and period_id != st["period_id"]:
                raise BankingError(f"a bank fee posts in the statement's period {st['period_id']}, not {period_id}")
            fee, _others = self._check_fee_line(line, st)
            period = self.ledger.require_open(st["period_id"])
            label = f"statement {st['statement_ref']} line {line['line_no']}"
            j = self.ledger.post(
                period_id=st["period_id"],
                description=f"Bank fee per {label}: {line['description'] or line['reference']}",
                lines=[
                    {"account": FEE_ACCOUNT, "debit": fee, "memo": f"bank fee {line['reference']}".strip()},
                    {"account": st["account_code"], "credit": fee, "memo": f"{label} ref {line['reference']}".strip()},
                ],
                source_type=LINE_SUBJECT, source_id=line_id, source_version=str(st["version"]), posted_by=actor, approval_id=approval_id,
            )
            bank_line = next(ln for ln in j["lines"] if ln["account_code"] == st["account_code"])
            match_id = self._insert_match(st, period, line=line, journal_line_id=bank_line["id"], gl_period_start=period["start_date"], basis="fee", actor=actor)
            version = self._touch(st, actor=actor, reason=f"fee posted for line {line_id}")
            self.audit.record(actor, "banking.fee_posted", LINE_SUBJECT, line_id, {
                "approval_id": approval_id, "journal_id": j["id"], "journal_line_id": bank_line["id"], "match_id": match_id,
                "fee": fmt(fee), "period_id": st["period_id"], "statement_id": st["id"], "fingerprint": line["fingerprint"],
            })
        return {
            "line": line_id, "statement_id": st["id"], "status": "booked", "fee": fmt(fee), "journal_id": j["id"],
            "journal_line_id": bank_line["id"], "match_id": match_id, "period_id": st["period_id"], "statement_version": version,
        }

    def _apply_lock(self, statement_id: str, *, approval_id: str, actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction() as conn:
            st = self._statement_row(statement_id)
            if period_id is not None and period_id != st["period_id"]:
                raise BankingError(f"statement {st['statement_ref']} belongs to period {st['period_id']}, not {period_id}")
            self._require_unlocked(st)
            rec = self._reconcile(st, evidence=True)
            if not rec["reconciled"]:
                raise BankingError(f"statement {st['statement_ref']} is not reconciled (difference {rec['difference']}); it cannot be locked")
            evidence = rec.pop("_evidence")
            report = {k: v for k, v in rec.items() if k != "locked_reconciliation"}
            report_json = canonical_json(report)
            reconciliation_id = new_id("brc")
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO banking_reconciliations (id, statement_id, period_id, account_code, cutoff_date, statement_closing, gl_balance,
                   in_transit_total, adjusted_gl_balance, difference, statement_hash, match_set_hash, report_json, report_hash,
                   approval_id, locked_by, locked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (reconciliation_id, st["id"], st["period_id"], st["account_code"], rec["cutoff_date"], rec["statement_closing"], rec["gl_balance"],
                 rec["in_transit_total"], rec["adjusted_gl_balance"], rec["difference"], rec["statement_hash"], rec["match_set_hash"],
                 report_json, sha256_hex(report_json), approval_id, actor, now),
            )
            for match_id, journal_line_id in evidence["matches"]:
                conn.execute(
                    "INSERT INTO banking_reconciliation_evidence (reconciliation_id, statement_id, kind, journal_line_id, match_id) VALUES (?,?,'match',?,?)",
                    (reconciliation_id, st["id"], journal_line_id, match_id),
                )
            for journal_line_id in evidence["in_transit"]:
                conn.execute(
                    "INSERT INTO banking_reconciliation_evidence (reconciliation_id, statement_id, kind, journal_line_id, match_id) VALUES (?,?,'in_transit',?,NULL)",
                    (reconciliation_id, st["id"], journal_line_id),
                )
            conn.execute(
                "UPDATE banking_statements SET status='locked', version=version+1, lock_approval_id=?, locked_by=?, locked_at=?, updated_at=? WHERE id=?",
                (approval_id, actor, now, now, statement_id),
            )
            # settled payments whose settlement bank line this locked reconciliation matched to a
            # statement line advance to bank_reconciled, in the same transaction as the lock
            payments_marked = self._mark_payments_bank_reconciled(evidence["matches"], reconciliation_id=reconciliation_id, actor=actor)
            self.approvals.invalidate_for_subject(STATEMENT_SUBJECT, statement_id, reason="reconciliation already locked", actor=actor)
            self.audit.record(actor, "banking.reconciliation_locked", STATEMENT_SUBJECT, statement_id, {
                "approval_id": approval_id, "reconciliation_id": reconciliation_id, "period_id": st["period_id"],
                "statement_closing": rec["statement_closing"], "gl_balance": rec["gl_balance"], "in_transit_total": rec["in_transit_total"],
                "difference": rec["difference"], "statement_hash": rec["statement_hash"], "match_set_hash": rec["match_set_hash"],
                "cleared_hash": rec["cleared_hash"], "evidence_matches": len(evidence["matches"]), "evidence_in_transit": len(evidence["in_transit"]),
                "report_hash": sha256_hex(report_json), "payments_bank_reconciled": payments_marked["advanced"],
            })
        return {
            "statement_id": statement_id, "status": "locked", "reconciliation_id": reconciliation_id, "period_id": st["period_id"],
            "statement_closing": rec["statement_closing"], "gl_balance": rec["gl_balance"], "in_transit_total": rec["in_transit_total"],
            "adjusted_gl_balance": rec["adjusted_gl_balance"], "difference": rec["difference"],
            "evidence_matches": len(evidence["matches"]), "evidence_in_transit": len(evidence["in_transit"]),
            "payments_bank_reconciled": payments_marked["advanced"],
        }

    def _mark_payments_bank_reconciled(self, evidence_matches: list[tuple[str, str]], *, reconciliation_id: str, actor: str) -> dict[str, Any]:
        """Hand the GL lines this lock matched to statement lines (opening items pair no
        statement line and are left out) to the payment domain, which advances settled
        intents whose settlement bank line is among them to ``bank_reconciled``."""
        mark = getattr(getattr(self.c, "payments", None), "mark_bank_reconciled_for_journal_lines", None)
        if mark is None:
            return {"advanced": []}
        line_matched = []
        for match_id, journal_line_id in evidence_matches:
            if self.db.scalar("SELECT line_id FROM banking_matches WHERE id=?", (match_id,)) is not None:
                line_matched.append(journal_line_id)
        return mark(line_matched, actor, reconciliation_id=reconciliation_id)

    # ---- state ------------------------------------------------------------------------ #

    def state(self, project_id: str) -> dict[str, Any]:
        """Bank data is entity level; ``project_id`` is accepted for the plugin contract and ignored."""
        statements = []
        for row in self.db.query("SELECT * FROM banking_statements ORDER BY import_seq"):
            rec = self._reconcile(row)
            summary = {k: v for k, v in row.items() if k != "skipped_json"}
            summary["skipped"] = loads(row["skipped_json"])
            summary["matches"] = self.db.query("SELECT * FROM banking_matches WHERE statement_id=? AND status='active' ORDER BY matched_at, id", (row["id"],))
            summary["reconciliation"] = rec
            statements.append(summary)
        periods = [p["id"] for p in self.ledger.periods()]
        return {
            "scope": "entity",
            "statements": statements,
            "periods": {pid: self.reconciliation_status(pid) for pid in periods},
        }
