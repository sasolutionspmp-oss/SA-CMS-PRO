"""SQLite foundation: versioned schema catalog, transactions and workspace write authority.

The schema catalog is an ordered list of ``(version, name, statements)``.  A
version is applied once, inside one transaction, and its checksum is recorded
so a later edit to an already-applied version is detected instead of silently
diverging.  Immutability of posted journals, audit entries and provider events
is enforced by triggers, not by convention.

Write authority: a database file carries an instance token in a sidecar file.
A copied or restored database has no matching sidecar, so it opens read-only
until an explicit, attested claim.  That is the control the plan describes as
"a copied workspace gains write authority only through fresh approval and
explicit release".  Read-only is enforced by SQLite itself: a connection
without effective write authority runs ``PRAGMA query_only=ON``, and every
write attempt (any table, any code path, any cursor, raw SQL included) surfaces
as ``WriteAuthorityError``.  Only the ``Database``'s own write-authority methods
can change ``query_only``: SQLite's authorizer refuses every other assignment,
whatever its spelling (comments, quotes, schema prefix) or cursor.  Every
connection to the same file follows a release or claim made on another one: it
re-evaluates authority whenever ``PRAGMA data_version`` shows that another
connection committed.  In-memory databases always hold authority.

Later catalog entries seal posted journals (a header-held line count enforced
by an insert trigger, exact integer-cent balance when the last line lands, and a
deferred check that refuses to commit a journal holding fewer lines than it
declares), give accounting periods their own integrity triggers (a locked period
never changes; closed -> open needs a consumed, unused ``*.reopen_period``
approval), refuse ``INSERT OR REPLACE`` on every core table whose rows are
immutable (with ``recursive_triggers`` off the delete that REPLACE performs would
fire no delete trigger), and give approvals a forward-only lifecycle.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import weakref
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import quote

from .ids import new_id, sha256_hex, utcnow_iso, canonical_json

OWNER_SECRET_ENV = "CIPHER_OWNER_SECRET"
_SQLITE_READONLY = 8
_SQLITE_AUTH = 23
_PLAIN_SELECT = re.compile(r"\s*select\b", re.IGNORECASE)  # cannot write, so it needs no authority refresh
# Pragmas whose assignment would lift a control.  The authorizer refuses them unless the
# Database itself issues the statement (query_only through the write-authority methods,
# foreign_keys once at connect).  It sees the normalized pragma name for every statement
# on every cursor, so no spelling of the statement gets past it.
_GUARDED_PRAGMAS = {
    "query_only": "write authority",
    "foreign_keys": "referential integrity (it also keeps an incomplete journal from committing)",
    "ignore_check_constraints": "CHECK constraints",
}
# sqlite3 connection switches (Connection.setconfig) that must keep these values
_LOCKED_DBCONFIG = (
    ("SQLITE_DBCONFIG_ENABLE_FKEY", True),
    ("SQLITE_DBCONFIG_ENABLE_TRIGGER", True),
    ("SQLITE_DBCONFIG_WRITABLE_SCHEMA", False),
    ("SQLITE_DBCONFIG_RESET_DATABASE", False),
)


class SchemaError(RuntimeError):
    """The on-disk schema and the catalog disagree."""


class WorkspaceModeError(SchemaError):
    """The workspace has no verified, supported runtime mode."""


class WriteAuthorityError(PermissionError):
    """The workspace does not currently hold write authority."""


_READ_ONLY_MESSAGE = (
    "write refused: this workspace connection is read-only because it does not hold write authority "
    "(a restored or copied workspace, or authority was released); claim write authority with an attested "
    "owner approval before mutating records"
)


def _is_readonly_error(exc: sqlite3.Error) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None:
        return (code & 0xFF) == _SQLITE_READONLY
    return "readonly" in str(exc).lower()


def _is_auth_error(exc: sqlite3.Error) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None:
        return (code & 0xFF) == _SQLITE_AUTH
    return "not authorized" in str(exc).lower()


def _authorizer_for(conn: "AuthorityConnection"):
    """SQLite authorizer: refuse assignments to the guarded pragmas unless the current
    thread is running one of the Database's own internal statements."""
    ref = weakref.ref(conn)

    def authorize(action, arg1, arg2, db_name, source):
        if action == sqlite3.SQLITE_PRAGMA and arg1 is not None and arg2 is not None:
            name = arg1.lower()
            if name in _GUARDED_PRAGMAS:
                c = ref()
                if c is None or not c._is_internal():
                    if c is not None:
                        c._denied_pragma = name
                    return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return authorize


class AuthorityCursor(sqlite3.Cursor):
    """Cursor that brings the connection's authority up to date before a top-level
    statement and reports refused writes as ``WriteAuthorityError``.  Every cursor of an
    ``AuthorityConnection`` is one, including those behind ``Connection.execute``."""

    def _guarded(self, run, *args):
        conn = self.connection
        before = getattr(conn, "_before_statement", None)
        if before is not None:
            before(args[0])
            conn._denied_pragma = None
        try:
            return run(*args)
        except sqlite3.DatabaseError as exc:
            translate = getattr(conn, "_translate", None)
            translated = exc if translate is None else translate(exc)
            if translated is exc:
                raise
            raise translated from exc

    def execute(self, sql, parameters=(), /):  # type: ignore[override]
        return self._guarded(super().execute, sql, parameters)

    def executemany(self, sql, parameters, /):  # type: ignore[override]
        return self._guarded(super().executemany, sql, parameters)

    def executescript(self, sql_script, /):  # type: ignore[override]
        return self._guarded(super().executescript, sql_script)


class AuthorityConnection(sqlite3.Connection):
    """SQLite connection whose every cursor reports writes refused by ``PRAGMA
    query_only`` as ``WriteAuthorityError``.  ``query_only`` (and the other guarded
    pragmas) can be assigned only by the ``Database`` that owns the connection: the
    authorizer refuses any other assignment, on any cursor and in any spelling."""

    _authority_owner: int | None = None  # thread running a Database-internal statement
    _authority_hook = None  # Database._refresh_authority (weakly bound), run before top-level statements
    _denied_pragma: str | None = None

    def _is_internal(self) -> bool:
        return self._authority_owner == threading.get_ident()

    def cursor(self, factory=None):  # type: ignore[override]
        return super().cursor(factory or AuthorityCursor)

    def execute(self, sql, parameters=(), /):  # type: ignore[override]
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql, parameters, /):  # type: ignore[override]
        return self.cursor().executemany(sql, parameters)

    def executescript(self, sql_script, /):  # type: ignore[override]
        return self.cursor().executescript(sql_script)

    def setconfig(self, op, enable=True, /):  # type: ignore[override]
        """The connection-level switches behind the same controls (foreign keys, triggers,
        schema writes) stay fixed, so ``setconfig`` cannot side-step the guarded pragmas."""
        for name, required in _LOCKED_DBCONFIG:
            if op == getattr(sqlite3, name, None) and bool(enable) != required:
                raise sqlite3.IntegrityError(f"{name} is fixed by the integrity controls on this connection")
        return super().setconfig(op, enable)

    def _before_statement(self, sql: Any) -> None:
        """Before a top-level statement that may write (anything but a plain SELECT),
        let the Database follow a release or claim committed by another connection."""
        hook = self._authority_hook
        if hook is None or self._is_internal():
            return
        if isinstance(sql, str) and _PLAIN_SELECT.match(sql):
            return
        hook()

    def _translate(self, exc: sqlite3.DatabaseError) -> BaseException:
        denied, self._denied_pragma = self._denied_pragma, None
        if denied is not None and _is_auth_error(exc):
            if denied == "query_only":
                return WriteAuthorityError(
                    "PRAGMA query_only is managed by the write-authority controls; use claim_write_authority / release_write_authority"
                )
            return sqlite3.IntegrityError(f"PRAGMA {denied} is fixed by the integrity controls ({_GUARDED_PRAGMAS[denied]}); it cannot be changed on this connection")
        if isinstance(exc, sqlite3.OperationalError) and _is_readonly_error(exc):
            return WriteAuthorityError(f"{_READ_ONLY_MESSAGE} (sqlite: {exc})")
        return exc


def _hook_for(db: "Database"):
    ref = weakref.ref(db)

    def hook() -> None:
        d = ref()
        if d is not None:
            d._refresh_authority()

    return hook


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WriteAuthorityError(f"claiming write authority requires a non-empty {label}")
    return value.strip()


# --------------------------------------------------------------------------- #
# Schema catalog                                                               #
# --------------------------------------------------------------------------- #

_V1_FOUNDATION = [
    """CREATE TABLE workspace (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        workspace_id TEXT NOT NULL,
        instance_token TEXT NOT NULL,
        write_authority INTEGER NOT NULL DEFAULT 0,
        authority_epoch INTEGER NOT NULL DEFAULT 0,
        recovery_epoch INTEGER NOT NULL DEFAULT 0,
        reconciled_epoch INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE audit_log (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        entry_hash TEXT NOT NULL UNIQUE
    )""",
    "CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END",
    "CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END",
    """CREATE TABLE idempotency (
        op_id TEXT PRIMARY KEY,
        payload_hash TEXT NOT NULL,
        result_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE approvals (
        id TEXT PRIMARY KEY,
        operation TEXT NOT NULL,
        subject_type TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        actor_role TEXT NOT NULL,
        manifest_json TEXT NOT NULL,
        manifest_hash TEXT NOT NULL,
        material_hash TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        nonce TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK (status IN ('pending','granted','consumed','expired','invalidated')),
        requested_by TEXT NOT NULL,
        requested_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        approver TEXT,
        granted_at TEXT,
        consumed_at TEXT,
        consumed_by TEXT,
        invalidated_reason TEXT
    )""",
    """CREATE TABLE outbox (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending','dispatched','failed')),
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        created_at TEXT NOT NULL,
        dispatched_at TEXT
    )""",
    """CREATE TABLE parties (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL CHECK (kind IN ('customer','supplier','employee','provider')),
        name TEXT NOT NULL,
        destination TEXT,
        destination_version INTEGER NOT NULL DEFAULT 0,
        destination_verified INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        entity TEXT NOT NULL,
        currency TEXT NOT NULL DEFAULT 'USD',
        customer_id TEXT REFERENCES parties(id),
        budget TEXT NOT NULL DEFAULT '0.00',
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE documents (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE document_revisions (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id),
        revision INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        UNIQUE (document_id, revision)
    )""",
    "CREATE TRIGGER document_revisions_no_update BEFORE UPDATE ON document_revisions BEGIN SELECT RAISE(ABORT, 'document revisions are immutable'); END",
    "CREATE TRIGGER document_revisions_no_delete BEFORE DELETE ON document_revisions BEGIN SELECT RAISE(ABORT, 'document revisions are immutable'); END",
    """CREATE TABLE estimates (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        document_revision_id TEXT NOT NULL REFERENCES document_revisions(id),
        revision INTEGER NOT NULL,
        supersedes TEXT REFERENCES estimates(id),
        status TEXT NOT NULL CHECK (status IN ('draft','approved','superseded')),
        total TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        approval_id TEXT REFERENCES approvals(id),
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE estimate_lines (
        id TEXT PRIMARY KEY,
        estimate_id TEXT NOT NULL REFERENCES estimates(id),
        line_no INTEGER NOT NULL,
        description TEXT NOT NULL,
        quantity TEXT NOT NULL,
        unit TEXT NOT NULL,
        unit_price TEXT NOT NULL,
        amount TEXT NOT NULL
    )""",
    """CREATE TABLE commitments (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        supplier_id TEXT NOT NULL REFERENCES parties(id),
        estimate_id TEXT REFERENCES estimates(id),
        title TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','approved','executed','closed')),
        original_amount TEXT NOT NULL,
        executed_amount TEXT NOT NULL,
        retainage_rate TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        approval_id TEXT REFERENCES approvals(id),
        created_at TEXT NOT NULL,
        executed_at TEXT,
        closed_at TEXT
    )""",
    """CREATE TABLE sov_lines (
        id TEXT PRIMARY KEY,
        commitment_id TEXT NOT NULL REFERENCES commitments(id),
        line_no INTEGER NOT NULL,
        description TEXT NOT NULL,
        cost_code TEXT NOT NULL DEFAULT '',
        amount TEXT NOT NULL,
        UNIQUE (commitment_id, line_no)
    )""",
    """CREATE TABLE changes (
        id TEXT PRIMARY KEY,
        commitment_id TEXT NOT NULL REFERENCES commitments(id),
        sov_line_id TEXT REFERENCES sov_lines(id),
        amount TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending','approved','executed','rejected')),
        version INTEGER NOT NULL DEFAULT 1,
        approval_id TEXT REFERENCES approvals(id),
        created_at TEXT NOT NULL,
        executed_at TEXT
    )""",
    """CREATE TABLE stored_material_lots (
        id TEXT PRIMARY KEY,
        commitment_id TEXT NOT NULL REFERENCES commitments(id),
        sov_line_id TEXT NOT NULL REFERENCES sov_lines(id),
        description TEXT NOT NULL,
        eligible_amount TEXT NOT NULL,
        remaining_amount TEXT NOT NULL,
        evidence_hash TEXT NOT NULL,
        location TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE periods (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('open','closed','locked')),
        closed_at TEXT,
        closed_by TEXT
    )""",
    """CREATE TABLE accounts (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL CHECK (type IN ('asset','liability','equity','revenue','expense')),
        control_kind TEXT
    )""",
    """CREATE TABLE journals (
        id TEXT PRIMARY KEY,
        period_id TEXT NOT NULL REFERENCES periods(id),
        posted_at TEXT NOT NULL,
        description TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_version TEXT NOT NULL,
        rule_version TEXT NOT NULL,
        approval_id TEXT,
        reversal_of TEXT REFERENCES journals(id),
        posted_by TEXT NOT NULL
    )""",
    """CREATE TABLE journal_lines (
        id TEXT PRIMARY KEY,
        journal_id TEXT NOT NULL REFERENCES journals(id),
        line_no INTEGER NOT NULL,
        account_code TEXT NOT NULL REFERENCES accounts(code),
        debit TEXT NOT NULL DEFAULT '0.00',
        credit TEXT NOT NULL DEFAULT '0.00',
        project_id TEXT,
        party_id TEXT,
        memo TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE TRIGGER journals_no_update BEFORE UPDATE ON journals BEGIN SELECT RAISE(ABORT, 'posted journals are immutable'); END",
    "CREATE TRIGGER journals_no_delete BEFORE DELETE ON journals BEGIN SELECT RAISE(ABORT, 'posted journals are immutable'); END",
    "CREATE TRIGGER journal_lines_no_update BEFORE UPDATE ON journal_lines BEGIN SELECT RAISE(ABORT, 'posted journal lines are immutable'); END",
    "CREATE TRIGGER journal_lines_no_delete BEFORE DELETE ON journal_lines BEGIN SELECT RAISE(ABORT, 'posted journal lines are immutable'); END",
    """CREATE TRIGGER journals_period_open BEFORE INSERT ON journals
        BEGIN
            SELECT CASE
                WHEN (SELECT status FROM periods WHERE id = NEW.period_id) IS NOT 'open'
                THEN RAISE(ABORT, 'period is not open for posting')
            END;
        END""",
    """CREATE TRIGGER journal_lines_period_open BEFORE INSERT ON journal_lines
        BEGIN
            SELECT CASE
                WHEN (SELECT p.status FROM journals j JOIN periods p ON p.id = j.period_id WHERE j.id = NEW.journal_id) IS NOT 'open'
                THEN RAISE(ABORT, 'period is not open for posting')
            END;
        END""",
    """CREATE TABLE bills (
        id TEXT PRIMARY KEY,
        commitment_id TEXT NOT NULL REFERENCES commitments(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        sequence INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','approved','posted','paid','void')),
        cumulative_installed TEXT NOT NULL,
        cumulative_stored TEXT NOT NULL,
        cumulative_gross TEXT NOT NULL,
        cumulative_retainage TEXT NOT NULL,
        cumulative_net TEXT NOT NULL,
        prior_net TEXT NOT NULL,
        amount_due TEXT NOT NULL,
        retainage_this_period TEXT NOT NULL,
        installed_this_period TEXT NOT NULL,
        stored_added_this_period TEXT NOT NULL,
        stored_transferred_this_period TEXT NOT NULL,
        commitment_version INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        created_at TEXT NOT NULL,
        UNIQUE (commitment_id, sequence)
    )""",
    """CREATE TABLE bill_lines (
        id TEXT PRIMARY KEY,
        bill_id TEXT NOT NULL REFERENCES bills(id),
        sov_line_id TEXT NOT NULL REFERENCES sov_lines(id),
        cumulative_installed TEXT NOT NULL,
        prior_installed TEXT NOT NULL,
        installed_this_period TEXT NOT NULL,
        stored_added TEXT NOT NULL,
        stored_transferred TEXT NOT NULL
    )""",
    """CREATE TABLE bill_transfers (
        id TEXT PRIMARY KEY,
        bill_id TEXT NOT NULL REFERENCES bills(id),
        lot_id TEXT NOT NULL REFERENCES stored_material_lots(id),
        amount TEXT NOT NULL
    )""",
    """CREATE TABLE prime_bills (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        customer_id TEXT NOT NULL REFERENCES parties(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        sequence INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','approved','posted','sent','collected','void')),
        certified_cumulative TEXT NOT NULL,
        retainage_rate TEXT NOT NULL,
        retainage_cumulative TEXT NOT NULL,
        prior_net TEXT NOT NULL,
        amount_due TEXT NOT NULL,
        revenue_this_period TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        created_at TEXT NOT NULL,
        UNIQUE (project_id, sequence)
    )""",
    """CREATE TABLE payment_intents (
        id TEXT PRIMARY KEY,
        bill_id TEXT REFERENCES bills(id),
        party_id TEXT NOT NULL REFERENCES parties(id),
        amount TEXT NOT NULL,
        destination TEXT NOT NULL,
        destination_version INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('approved','queued','submitted','outcome_unknown','accepted','settled','failed','returned','canceled')),
        approval_id TEXT NOT NULL REFERENCES approvals(id),
        logical_op_id TEXT NOT NULL UNIQUE,
        payload_hash TEXT NOT NULL,
        outbox_id TEXT REFERENCES outbox(id),
        provider_ref TEXT,
        recovery_epoch INTEGER NOT NULL,
        journal_id TEXT REFERENCES journals(id),
        created_at TEXT NOT NULL,
        submitted_at TEXT,
        resolved_at TEXT,
        note TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE provider_events (
        id TEXT PRIMARY KEY,
        intent_id TEXT NOT NULL REFERENCES payment_intents(id),
        kind TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        received_at TEXT NOT NULL
    )""",
    "CREATE TRIGGER provider_events_no_update BEFORE UPDATE ON provider_events BEGIN SELECT RAISE(ABORT, 'provider events are immutable'); END",
    "CREATE TRIGGER provider_events_no_delete BEFORE DELETE ON provider_events BEGIN SELECT RAISE(ABORT, 'provider events are immutable'); END",
    """CREATE TABLE collections (
        id TEXT PRIMARY KEY,
        prime_bill_id TEXT NOT NULL REFERENCES prime_bills(id),
        amount TEXT NOT NULL,
        fee TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('received','returned')),
        journal_id TEXT REFERENCES journals(id),
        return_journal_id TEXT REFERENCES journals(id),
        provider_ref TEXT NOT NULL,
        received_at TEXT NOT NULL,
        returned_at TEXT
    )""",
    """CREATE TABLE ricky_proposals (
        id TEXT PRIMARY KEY,
        workflow TEXT NOT NULL,
        actor_role TEXT NOT NULL,
        context_json TEXT NOT NULL,
        decision TEXT NOT NULL CHECK (decision IN ('proposed','abstained')),
        reason TEXT NOT NULL,
        manifest_json TEXT,
        created_at TEXT NOT NULL
    )""",
]

# Sealed journals and governed corrections.  Every journal header declares how many
# lines it holds; a line can only be inserted while the journal holds fewer, and the
# line that completes the journal must leave it balanced (amounts compared in integer
# cents, exact for every value money() accepts).  A raw INSERT onto a posted journal is
# therefore refused.  journals_no_update is dropped only for the one-time backfill and
# recreated with its original statement.  A journal can be reversed once (unique
# reversal_of), and a governed reversal ("journal.reverse") binds a recorded request.
_LEDGER_INTEGRITY = [
    "ALTER TABLE journals ADD COLUMN line_count INTEGER",
    "DROP TRIGGER journals_no_update",
    "UPDATE journals SET line_count = (SELECT COUNT(*) FROM journal_lines l WHERE l.journal_id = journals.id)",
    "CREATE TRIGGER journals_no_update BEFORE UPDATE ON journals BEGIN SELECT RAISE(ABORT, 'posted journals are immutable'); END",
    "CREATE INDEX IF NOT EXISTS journal_lines_by_journal ON journal_lines(journal_id, line_no)",
    """CREATE TRIGGER journals_declare_line_count BEFORE INSERT ON journals
        WHEN (NEW.line_count IS NULL OR NEW.line_count < 2)
             AND (SELECT status FROM periods WHERE id = NEW.period_id) IS 'open'
        BEGIN
            SELECT RAISE(ABORT, 'a journal must declare its sealed line count (at least 2 lines) when it is posted');
        END""",
    """CREATE TRIGGER journal_lines_sealed BEFORE INSERT ON journal_lines
        BEGIN
            SELECT CASE
                WHEN (SELECT line_count FROM journals WHERE id = NEW.journal_id) IS NULL
                THEN RAISE(ABORT, 'posted journals are immutable: the journal declares no sealed line count, so no line can be added')
                WHEN (SELECT COUNT(*) FROM journal_lines WHERE journal_id = NEW.journal_id) >= (SELECT line_count FROM journals WHERE id = NEW.journal_id)
                THEN RAISE(ABORT, 'posted journals are immutable: the journal already holds its sealed line count')
                WHEN (SELECT COUNT(*) FROM journal_lines WHERE journal_id = NEW.journal_id) + 1 = (SELECT line_count FROM journals WHERE id = NEW.journal_id)
                     AND (SELECT COALESCE(SUM(CAST(ROUND(CAST(debit AS REAL) * 100) AS INTEGER) - CAST(ROUND(CAST(credit AS REAL) * 100) AS INTEGER)), 0)
                          FROM journal_lines WHERE journal_id = NEW.journal_id)
                         + CAST(ROUND(CAST(NEW.debit AS REAL) * 100) AS INTEGER) - CAST(ROUND(CAST(NEW.credit AS REAL) * 100) AS INTEGER) <> 0
                THEN RAISE(ABORT, 'journal does not balance: its sealed lines must carry equal debits and credits')
            END;
        END""",
    "CREATE UNIQUE INDEX journals_reversed_once ON journals(reversal_of) WHERE reversal_of IS NOT NULL",
    """CREATE TABLE journal_reversal_requests (
        id TEXT PRIMARY KEY,
        journal_id TEXT NOT NULL REFERENCES journals(id),
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        status TEXT NOT NULL CHECK (status IN ('pending','executed','cancelled')),
        requested_by TEXT NOT NULL,
        requested_at TEXT NOT NULL,
        approval_id TEXT REFERENCES approvals(id),
        reversal_journal_id TEXT REFERENCES journals(id),
        resolved_by TEXT,
        resolved_at TEXT,
        resolution_note TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE UNIQUE INDEX journal_reversal_requests_one_pending ON journal_reversal_requests(journal_id) WHERE status = 'pending'",
    """CREATE TRIGGER journal_reversal_requests_insert_pending BEFORE INSERT ON journal_reversal_requests
        WHEN NEW.status <> 'pending' OR NEW.approval_id IS NOT NULL OR NEW.reversal_journal_id IS NOT NULL
        BEGIN
            SELECT RAISE(ABORT, 'a journal reversal request starts pending, with no approval or reversal journal');
        END""",
    """CREATE TRIGGER journal_reversal_requests_resolve_once BEFORE UPDATE ON journal_reversal_requests
        WHEN OLD.status <> 'pending' OR NEW.status = 'pending'
             OR NEW.id IS NOT OLD.id OR NEW.journal_id IS NOT OLD.journal_id OR NEW.reason IS NOT OLD.reason
             OR NEW.requested_by IS NOT OLD.requested_by OR NEW.requested_at IS NOT OLD.requested_at
        BEGIN
            SELECT RAISE(ABORT, 'journal reversal requests are immutable once resolved; only pending -> executed or cancelled is allowed');
        END""",
    """CREATE TRIGGER journal_reversal_requests_executed_link BEFORE UPDATE ON journal_reversal_requests
        WHEN NEW.status = 'executed'
             AND (NEW.approval_id IS NULL OR NEW.reversal_journal_id IS NULL
                  OR (SELECT reversal_of FROM journals WHERE id = NEW.reversal_journal_id) IS NOT NEW.journal_id)
        BEGIN
            SELECT RAISE(ABORT, 'an executed reversal request must carry its approval and the journal that reverses it');
        END""",
    "CREATE TRIGGER journal_reversal_requests_no_delete BEFORE DELETE ON journal_reversal_requests BEGIN SELECT RAISE(ABORT, 'journal reversal requests are append-only'); END",
]

# Period integrity.  A locked period never changes again; status moves only
# open -> closed, closed -> locked or closed -> open; closed -> open needs a consumed
# "*.reopen_period" approval scoped to that period that has not reopened anything
# before (period_reopens logs every reopen and is append-only).  The conditions are
# disjoint, so the refusal reason does not depend on trigger firing order.
_PERIOD_INTEGRITY = [
    "ALTER TABLE periods ADD COLUMN reopen_approval_id TEXT",
    """CREATE TABLE period_reopens (
        approval_id TEXT PRIMARY KEY REFERENCES approvals(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        reopened_at TEXT NOT NULL
    )""",
    "CREATE TRIGGER period_reopens_no_update BEFORE UPDATE ON period_reopens BEGIN SELECT RAISE(ABORT, 'period reopen log is append-only'); END",
    "CREATE TRIGGER period_reopens_no_delete BEFORE DELETE ON period_reopens BEGIN SELECT RAISE(ABORT, 'period reopen log is append-only'); END",
    """CREATE TRIGGER periods_status_transitions BEFORE UPDATE ON periods
        WHEN OLD.status <> 'locked' AND NEW.status IS NOT OLD.status
             AND NOT ((OLD.status = 'open' AND NEW.status = 'closed')
                      OR (OLD.status = 'closed' AND NEW.status = 'locked')
                      OR (OLD.status = 'closed' AND NEW.status = 'open'))
        BEGIN
            SELECT RAISE(ABORT, 'period status may only move open -> closed, closed -> locked, or closed -> open with a consumed reopen approval');
        END""",
    """CREATE TRIGGER periods_reopen_approval_id_guard BEFORE UPDATE ON periods
        WHEN OLD.status <> 'locked' AND NEW.reopen_approval_id IS NOT OLD.reopen_approval_id
             AND NOT (OLD.status = 'closed' AND NEW.status = 'open')
        BEGIN
            SELECT RAISE(ABORT, 'a period reopen approval is recorded only by the closed -> open transition it authorises');
        END""",
    """CREATE TRIGGER periods_reopen_requires_approval BEFORE UPDATE ON periods
        WHEN OLD.status = 'closed' AND NEW.status = 'open'
        BEGIN
            SELECT CASE
                WHEN NEW.reopen_approval_id IS NULL
                THEN RAISE(ABORT, 'reopening a closed period requires a consumed reopen_period approval for that period')
                WHEN NOT EXISTS (
                    SELECT 1 FROM approvals a
                    WHERE a.id = NEW.reopen_approval_id AND a.status = 'consumed' AND a.subject_id = NEW.id
                      AND length(a.operation) > 14 AND substr(a.operation, -14) = '.reopen_period')
                THEN RAISE(ABORT, 'reopening a closed period requires a consumed reopen_period approval for that period; the referenced approval is not one')
                WHEN EXISTS (SELECT 1 FROM period_reopens r WHERE r.approval_id = NEW.reopen_approval_id)
                THEN RAISE(ABORT, 'that reopen approval was already used to reopen a period; each reopen needs a fresh approval')
            END;
        END""",
    """CREATE TRIGGER periods_reopen_logged AFTER UPDATE ON periods
        WHEN OLD.status = 'closed' AND NEW.status = 'open'
        BEGIN
            INSERT INTO period_reopens (approval_id, period_id, reopened_at)
            VALUES (NEW.reopen_approval_id, NEW.id, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
        END""",
    "CREATE TRIGGER periods_closed_no_delete BEFORE DELETE ON periods WHEN OLD.status <> 'open' BEGIN SELECT RAISE(ABORT, 'closed and locked periods are immutable and cannot be deleted'); END",
    "CREATE TRIGGER periods_locked_immutable BEFORE UPDATE ON periods WHEN OLD.status = 'locked' BEGIN SELECT RAISE(ABORT, 'locked periods are immutable'); END",
]


def _canonical_money_sql(col: str) -> str:
    """SQL test that ``col`` is canonical stored money as ``fmt`` writes it: non-negative,
    no sign or exponent, no leading zero, exactly two decimals, below 10**13."""
    return (f"({col} GLOB '[0-9]*.[0-9][0-9]' AND NOT {col} GLOB '*[^0-9.]*' "
            f"AND length({col}) - length(replace({col}, '.', '')) = 1 AND NOT {col} GLOB '0[0-9]*' AND length({col}) <= 16)")


def _cents_sql(col: str) -> str:
    """Exact integer cents of a canonical money string (no floating point)."""
    return f"CAST(replace({col}, '.', '') AS INTEGER)"


# Integrity hardening (an append-only follow-up to the two entries above; their triggers
# that change are dropped and recreated here under the same names).
#
# * Journal lines carry canonical money text and exactly one side; the balance check on
#   the line that completes a journal works in exact integer cents.
# * A journal must be complete when its transaction commits: every new header gets a
#   completion marker whose deferred foreign key points at a table that stays empty, and
#   the line that completes the journal removes the marker.  A header committed with
#   fewer lines than it declares fails the commit (or the autocommit statement).
# * INSERT OR REPLACE is refused on the core tables whose rows are immutable: with
#   recursive_triggers off, the delete that REPLACE performs fires no delete trigger, so a
#   BEFORE INSERT trigger refuses any row that collides with a stored one.
# * Periods are created open; the reopen log is written only by the reopen it records.
# * Approvals are recorded pending and move forward only; their request and manifest
#   never change, the grant and the consumption are each recorded once with who and when,
#   and a reopen needs a period-scoped approval that was granted and consumed.
_INTEGRITY_HARDENING = [
    "DROP TRIGGER journal_lines_sealed",
    f"""CREATE TRIGGER journal_lines_sealed BEFORE INSERT ON journal_lines
        BEGIN
            SELECT CASE
                WHEN (SELECT line_count FROM journals WHERE id = NEW.journal_id) IS NULL
                THEN RAISE(ABORT, 'posted journals are immutable: the journal declares no sealed line count, so no line can be added')
                WHEN (SELECT COUNT(*) FROM journal_lines WHERE journal_id = NEW.journal_id) >= (SELECT line_count FROM journals WHERE id = NEW.journal_id)
                THEN RAISE(ABORT, 'posted journals are immutable: the journal already holds its sealed line count')
                WHEN NOT {_canonical_money_sql('NEW.debit')} OR NOT {_canonical_money_sql('NEW.credit')}
                THEN RAISE(ABORT, 'journal line amounts must be canonical money text: non-negative, two decimals, no sign, exponent or leading zero (for example 1250.00)')
                WHEN ({_cents_sql('NEW.debit')} > 0) = ({_cents_sql('NEW.credit')} > 0)
                THEN RAISE(ABORT, 'a journal line carries exactly one of debit or credit')
                WHEN (SELECT COUNT(*) FROM journal_lines WHERE journal_id = NEW.journal_id) + 1 = (SELECT line_count FROM journals WHERE id = NEW.journal_id)
                     AND (SELECT COALESCE(SUM({_cents_sql('debit')} - {_cents_sql('credit')}), 0) FROM journal_lines WHERE journal_id = NEW.journal_id)
                         + {_cents_sql('NEW.debit')} - {_cents_sql('NEW.credit')} <> 0
                THEN RAISE(ABORT, 'journal does not balance: its sealed lines must carry equal debits and credits')
            END;
        END""",
    "CREATE TABLE journal_seal_never (id TEXT PRIMARY KEY)",
    "CREATE TRIGGER journal_seal_never_stays_empty BEFORE INSERT ON journal_seal_never BEGIN SELECT RAISE(ABORT, 'journal_seal_never stays empty: it is what keeps an incomplete journal from committing'); END",
    """CREATE TABLE journal_unsealed (
        journal_id TEXT PRIMARY KEY REFERENCES journals(id),
        pending_completion TEXT NOT NULL REFERENCES journal_seal_never(id) DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TRIGGER journals_mark_unsealed AFTER INSERT ON journals WHEN NEW.line_count IS NOT NULL
        BEGIN
            INSERT INTO journal_unsealed (journal_id, pending_completion) VALUES (NEW.id, NEW.id);
        END""",
    """CREATE TRIGGER journal_lines_mark_complete AFTER INSERT ON journal_lines
        WHEN (SELECT COUNT(*) FROM journal_lines WHERE journal_id = NEW.journal_id) = (SELECT line_count FROM journals WHERE id = NEW.journal_id)
        BEGIN
            DELETE FROM journal_unsealed WHERE journal_id = NEW.journal_id;
        END""",
    """CREATE TRIGGER journal_unsealed_guard BEFORE DELETE ON journal_unsealed
        WHEN (SELECT COUNT(*) FROM journal_lines WHERE journal_id = OLD.journal_id) < COALESCE((SELECT line_count FROM journals WHERE id = OLD.journal_id), 0)
        BEGIN
            SELECT RAISE(ABORT, 'posted journals are immutable: a journal is complete only when it holds its sealed line count');
        END""",
    "CREATE TRIGGER journal_unsealed_no_update BEFORE UPDATE ON journal_unsealed BEGIN SELECT RAISE(ABORT, 'journal completion markers are immutable'); END",
    """CREATE TRIGGER journals_no_replace BEFORE INSERT ON journals
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM journals WHERE id = NEW.id)
                THEN RAISE(ABORT, 'posted journals are immutable: a journal id is never reused or replaced')
                WHEN NEW.reversal_of IS NOT NULL AND EXISTS (SELECT 1 FROM journals WHERE reversal_of = NEW.reversal_of)
                THEN RAISE(ABORT, 'a journal is reversed once: that journal already has a reversal')
            END;
        END""",
    """CREATE TRIGGER journal_lines_no_replace BEFORE INSERT ON journal_lines
        WHEN EXISTS (SELECT 1 FROM journal_lines WHERE id = NEW.id)
        BEGIN
            SELECT RAISE(ABORT, 'posted journal lines are immutable: a line id is never reused or replaced');
        END""",
    """CREATE TRIGGER periods_insert_guard BEFORE INSERT ON periods
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM periods WHERE id = NEW.id)
                THEN RAISE(ABORT, 'accounting periods are never replaced: that period id already exists (closed and locked periods are immutable)')
                WHEN NEW.status IS NOT 'open' OR NEW.reopen_approval_id IS NOT NULL OR NEW.closed_at IS NOT NULL OR NEW.closed_by IS NOT NULL
                THEN RAISE(ABORT, 'a period is created open; it is closed, locked or reopened only through its governed transitions')
            END;
        END""",
    """CREATE TRIGGER period_reopens_insert_guard BEFORE INSERT ON period_reopens
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM period_reopens WHERE approval_id = NEW.approval_id)
                THEN RAISE(ABORT, 'period reopen log is append-only: that reopen approval was already used')
                WHEN (SELECT status FROM periods WHERE id = NEW.period_id) IS NOT 'open'
                     OR (SELECT reopen_approval_id FROM periods WHERE id = NEW.period_id) IS NOT NEW.approval_id
                THEN RAISE(ABORT, 'period reopen log is append-only: a row is written only by the reopen it records')
            END;
        END""",
    """CREATE TRIGGER journal_reversal_requests_no_replace BEFORE INSERT ON journal_reversal_requests
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM journal_reversal_requests WHERE id = NEW.id)
                THEN RAISE(ABORT, 'journal reversal requests are append-only: a request id is never reused or replaced')
                WHEN EXISTS (SELECT 1 FROM journal_reversal_requests WHERE journal_id = NEW.journal_id AND status = 'pending')
                THEN RAISE(ABORT, 'journal reversal requests are append-only: that journal already has a pending reversal request')
                WHEN EXISTS (SELECT 1 FROM journals WHERE reversal_of = NEW.journal_id)
                THEN RAISE(ABORT, 'a journal is reversed once: that journal already has a reversal')
            END;
        END""",
    """CREATE TRIGGER audit_log_no_replace BEFORE INSERT ON audit_log
        WHEN EXISTS (SELECT 1 FROM audit_log WHERE seq = NEW.seq) OR EXISTS (SELECT 1 FROM audit_log WHERE entry_hash = NEW.entry_hash)
        BEGIN
            SELECT RAISE(ABORT, 'audit log is append-only: an entry is never replaced');
        END""",
    """CREATE TRIGGER document_revisions_no_replace BEFORE INSERT ON document_revisions
        WHEN EXISTS (SELECT 1 FROM document_revisions WHERE id = NEW.id)
          OR EXISTS (SELECT 1 FROM document_revisions WHERE document_id = NEW.document_id AND revision = NEW.revision)
        BEGIN
            SELECT RAISE(ABORT, 'document revisions are immutable: a revision is never replaced');
        END""",
    """CREATE TRIGGER approvals_insert_guard BEFORE INSERT ON approvals
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM approvals WHERE id = NEW.id) OR EXISTS (SELECT 1 FROM approvals WHERE nonce = NEW.nonce)
                THEN RAISE(ABORT, 'approvals are append-only: an approval id or manifest nonce is never reused or replaced')
                WHEN NEW.status IS NOT 'pending' OR NEW.approver IS NOT NULL OR NEW.granted_at IS NOT NULL
                     OR NEW.consumed_at IS NOT NULL OR NEW.consumed_by IS NOT NULL OR NEW.invalidated_reason IS NOT NULL
                THEN RAISE(ABORT, 'an approval is recorded pending, with no approver, grant or consumption; the approval workflow records those')
            END;
        END""",
    """CREATE TRIGGER approvals_request_immutable BEFORE UPDATE ON approvals
        WHEN NEW.id IS NOT OLD.id OR NEW.operation IS NOT OLD.operation OR NEW.subject_type IS NOT OLD.subject_type
          OR NEW.subject_id IS NOT OLD.subject_id OR NEW.actor_role IS NOT OLD.actor_role OR NEW.manifest_json IS NOT OLD.manifest_json
          OR NEW.manifest_hash IS NOT OLD.manifest_hash OR NEW.material_hash IS NOT OLD.material_hash
          OR NEW.policy_version IS NOT OLD.policy_version OR NEW.nonce IS NOT OLD.nonce OR NEW.requested_by IS NOT OLD.requested_by
          OR NEW.requested_at IS NOT OLD.requested_at OR NEW.expires_at IS NULL OR NEW.expires_at > OLD.expires_at
        BEGIN
            SELECT RAISE(ABORT, 'an approval request and its bound manifest are immutable (its expiry can only be brought forward)');
        END""",
    """CREATE TRIGGER approvals_lifecycle BEFORE UPDATE ON approvals
        BEGIN
            SELECT CASE
                WHEN OLD.status = 'consumed'
                  OR NOT (NEW.status = OLD.status
                          OR (OLD.status = 'pending' AND NEW.status IN ('granted', 'expired', 'invalidated'))
                          OR (OLD.status = 'granted' AND NEW.status IN ('consumed', 'expired', 'invalidated'))
                          OR (OLD.status = 'expired' AND NEW.status = 'invalidated'))
                THEN RAISE(ABORT, 'approval status moves forward only (pending -> granted -> consumed, or to expired or invalidated); a consumed approval never changes')
                WHEN (NEW.status IN ('granted', 'consumed') AND (NEW.approver IS NULL OR NEW.granted_at IS NULL))
                  OR (NEW.status = 'consumed' AND (NEW.consumed_at IS NULL OR NEW.consumed_by IS NULL))
                  OR ((NEW.approver IS NOT OLD.approver OR NEW.granted_at IS NOT OLD.granted_at) AND NOT (OLD.status = 'pending' AND NEW.status = 'granted'))
                  OR ((NEW.consumed_at IS NOT OLD.consumed_at OR NEW.consumed_by IS NOT OLD.consumed_by) AND NOT (OLD.status = 'granted' AND NEW.status = 'consumed'))
                THEN RAISE(ABORT, 'an approval records its approver and grant time when granted, and its consumer and time when consumed, each exactly once')
            END;
        END""",
    "CREATE TRIGGER approvals_no_delete BEFORE DELETE ON approvals BEGIN SELECT RAISE(ABORT, 'approvals are append-only'); END",
    "DROP TRIGGER periods_reopen_requires_approval",
    """CREATE TRIGGER periods_reopen_requires_approval BEFORE UPDATE ON periods
        WHEN OLD.status = 'closed' AND NEW.status = 'open'
        BEGIN
            SELECT CASE
                WHEN NEW.reopen_approval_id IS NULL
                THEN RAISE(ABORT, 'reopening a closed period requires a consumed reopen_period approval for that period')
                WHEN NOT EXISTS (
                    SELECT 1 FROM approvals a
                    WHERE a.id = NEW.reopen_approval_id AND a.status = 'consumed' AND a.subject_id = NEW.id
                      AND a.subject_type IN ('period', 'accounting_period')
                      AND a.approver IS NOT NULL AND a.granted_at IS NOT NULL AND a.consumed_at IS NOT NULL AND a.consumed_by IS NOT NULL
                      AND length(a.operation) > 14 AND substr(a.operation, -14) = '.reopen_period')
                THEN RAISE(ABORT, 'reopening a closed period requires a consumed reopen_period approval for that period; the referenced approval is not one (it must be a granted and consumed *.reopen_period approval scoped to this period)')
                WHEN EXISTS (SELECT 1 FROM period_reopens r WHERE r.approval_id = NEW.reopen_approval_id)
                THEN RAISE(ABORT, 'that reopen approval was already used to reopen a period; each reopen needs a fresh approval')
            END;
        END""",
]

SCHEMA_CATALOG: list[tuple[int, str, list[str]]] = [
    (1, "foundation", _V1_FOUNDATION),
    (2, "ledger_integrity", _LEDGER_INTEGRITY),
    (3, "period_integrity", _PERIOD_INTEGRITY),
    (4, "integrity_hardening", _INTEGRITY_HARDENING),
]


def register_schema_version(name: str, statements: list[str], *, version: int | None = None) -> int:
    """Domain modules append their own catalog versions at import time.

    Registration is idempotent by name.  Without an explicit ``version`` the
    next contiguous number is assigned, so plugin load order defines the
    version sequence (the order is fixed in ``service.PLUGIN_MODULES``).
    Returns the version number."""
    for existing_version, existing_name, existing_statements in SCHEMA_CATALOG:
        if existing_name == name:
            if catalog_checksum(existing_statements) != catalog_checksum(list(statements)):
                raise SchemaError(f"schema version {name!r} registered twice with different statements")
            return existing_version
    next_version = SCHEMA_CATALOG[-1][0] + 1
    if version is not None and version != next_version:
        raise SchemaError(f"schema versions must be contiguous; next is {next_version}, got {version}")
    SCHEMA_CATALOG.append((next_version, name, list(statements)))
    return next_version


def catalog_checksum(statements: list[str]) -> str:
    return sha256_hex("\n--\n".join(s.strip() for s in statements))


# Registered explicitly by the service after every historical entry. Do not move
# this registration to module import: historical catalog positions are fixed.
MODE_SCHEMA_NAME = "workspace_mode"
MODE_ACTION = "workspace.mode_declared"
MODE_SCHEMA_STATEMENTS = [
    "ALTER TABLE workspace ADD COLUMN mode TEXT CHECK (mode IN ('practice','live'))",
    "ALTER TABLE workspace ADD COLUMN mode_declaration_seq INTEGER REFERENCES audit_log(seq)",
    "CREATE UNIQUE INDEX workspace_mode_declaration_once ON audit_log(entity_id) WHERE entity_type='workspace' AND action='workspace.mode_declared'",
    """CREATE TRIGGER workspace_identity_immutable BEFORE UPDATE ON workspace
        WHEN NEW.workspace_id IS NOT OLD.workspace_id OR NEW.created_at IS NOT OLD.created_at
        BEGIN SELECT RAISE(ABORT, 'the original workspace identity is immutable'); END""",
    """CREATE TRIGGER workspace_mode_immutable BEFORE UPDATE ON workspace
        WHEN (OLD.mode IS NOT NULL OR OLD.mode_declaration_seq IS NOT NULL)
          AND (NEW.mode IS NOT OLD.mode OR NEW.mode_declaration_seq IS NOT OLD.mode_declaration_seq)
        BEGIN SELECT RAISE(ABORT, 'workspace mode is immutable'); END""",
    """CREATE TRIGGER workspace_mode_declaration_required BEFORE UPDATE ON workspace
        WHEN (NEW.mode IS NULL) IS NOT (NEW.mode_declaration_seq IS NULL)
          OR (NEW.mode IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM audit_log a WHERE a.seq=NEW.mode_declaration_seq
              AND a.action='workspace.mode_declared' AND a.entity_type='workspace'
              AND a.entity_id=NEW.workspace_id
              AND json_extract(a.payload_json, '$.workspace_id') IS NEW.workspace_id
              AND json_extract(a.payload_json, '$.mode') IS NEW.mode
              AND json_extract(a.payload_json, '$.created_at') IS NEW.created_at))
        BEGIN SELECT RAISE(ABORT, 'workspace mode requires its original audited declaration'); END""",
    "CREATE TRIGGER workspace_no_delete BEFORE DELETE ON workspace BEGIN SELECT RAISE(ABORT, 'the original workspace cannot be deleted'); END",
    "CREATE TRIGGER workspace_no_replace BEFORE INSERT ON workspace WHEN EXISTS (SELECT 1 FROM workspace) BEGIN SELECT RAISE(ABORT, 'the original workspace cannot be replaced'); END",
]


def register_workspace_mode_schema() -> int:
    return register_schema_version(MODE_SCHEMA_NAME, MODE_SCHEMA_STATEMENTS)


_KNOWN_SCHEMA_INVENTORIES: dict[tuple, dict] = {}


def _inventory(conn: sqlite3.Connection) -> dict:
    # schema_version is managed by the migration engine, not a catalog entry;
    # its columns are checked separately, without relying on formatting of DDL.
    return {(r[0], r[1]): re.sub(r"\s+", " ", r[2].strip()) for r in conn.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
        "AND name NOT IN ('schema_version','schema_version_name')")}


def _verify_known_schema(conn: sqlite3.Connection) -> None:
    """A planted catalog checksum does not prove that its schema was installed."""
    catalog = {name: statements for _, name, statements in SCHEMA_CATALOG}
    rows = list(conn.execute("SELECT version,name,statement_count,checksum FROM schema_version ORDER BY version"))
    if not rows or rows[0][1] != "foundation" or len({r[1] for r in rows}) != len(rows):
        raise SchemaError("the existing file has no recognized Cipher schema history")
    basis = []
    for row in rows:
        statements = catalog.get(row[1])
        if statements is None or row[2] != len(statements) or row[3] != catalog_checksum(statements):
            raise SchemaError("the existing file has an unknown or modified Cipher schema history")
        basis.append((row[1], row[3]))
    key = tuple(basis)
    expected = _KNOWN_SCHEMA_INVENTORIES.get(key)
    if expected is None:
        replay = sqlite3.connect(":memory:")
        try:
            for name, _ in basis:
                for statement in catalog[name]:
                    replay.execute(statement)
            expected = _inventory(replay)
        finally:
            replay.close()
        _KNOWN_SCHEMA_INVENTORIES[key] = expected
    if _inventory(conn) != expected:
        raise SchemaError("the existing file's installed schema differs from its recognized Cipher catalog")


def _verify_audit_rows(conn: sqlite3.Connection) -> None:
    prev = "0" * 64
    for row in conn.execute("SELECT ts,actor,action,entity_type,entity_id,payload_json,payload_hash,prev_hash,entry_hash FROM audit_log ORDER BY seq"):
        expected = sha256_hex("|".join([prev, *row[:5], row[6]]))
        if row[7] != prev or row[8] != expected or sha256_hex(row[5]) != row[6]:
            raise WorkspaceModeError("the workspace audit history is not intact")
        prev = row[8]


# --------------------------------------------------------------------------- #
# Database                                                                     #
# --------------------------------------------------------------------------- #

class Database:
    """A single SQLite connection with explicit transactions and a schema lifecycle."""

    def __init__(self, path: str = ":memory:", *, migrate: bool = True):
        self.path = os.fspath(path)
        self.in_memory = self.path == ":memory:"
        self._lock = threading.RLock()
        self._depth = 0
        self._read_only = False
        self._refresh_suspended = 0
        self._data_version: int | None = None
        self._original_workspace_id: str | None = None
        self._original_created_at: str | None = None
        self._legacy_recognized = False
        self._mode_origin = "created"
        self._mode_anchor: tuple | None = None
        if not self.in_memory and os.path.lexists(self.path):
            self._preflight_existing_file()
        self.conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, factory=AuthorityConnection)
        self.conn.set_authorizer(_authorizer_for(self.conn))
        self.conn.row_factory = sqlite3.Row
        with self._internal() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
        try:
            if migrate:
                self.migrate()
        except BaseException:
            self.conn.close()
            raise
        if not self.in_memory:
            if self._data_version is None:
                self._data_version = self._read_data_version()
            # from here on, a commit by any other connection to this file makes this one
            # re-evaluate its write authority before its next top-level statement
            self.conn._authority_hook = _hook_for(self)
        # In-memory workspaces need the same mutation/proof checks; data_version
        # alone cannot observe tampering through this connection.
        self.conn._authority_hook = _hook_for(self)
        self._mode_write_stamp: tuple | None = None
        self._mode_guard_schema_version: int | None = None
        # migrate=False is a diagnostic choice, not a waiver of copied-file
        # authority or undeclared-mode controls.
        self._apply_authority_mode()
        # Changing journal mode writes the file header. Determine authority first:
        # a current diagnostic copy must retain its original bytes, including a
        # DELETE-mode backup of an owned in-memory workspace. Existing WAL files
        # already retain that mode during migration without assigning the pragma.
        if not self.in_memory and not self._read_only:
            try:
                with self._internal() as conn:
                    conn.execute("PRAGMA journal_mode = WAL")
                    conn.execute("PRAGMA synchronous = NORMAL")
                    self._data_version = self._read_data_version()
            except BaseException:
                self.conn.close()
                raise

    def _preflight_existing_file(self) -> None:
        """Read and classify before WAL, migrations or authority sidecar writes."""
        inspect = None
        try:
            if not os.path.isfile(self.path) or os.path.getsize(self.path) == 0:
                raise SchemaError("an existing empty or unknown file is not a new Cipher workspace")
            uri = "file:" + quote(os.path.abspath(self.path), safe="/") + "?mode=ro"
            inspect = sqlite3.connect(uri, uri=True)
            _verify_known_schema(inspect)
            rows = list(inspect.execute("SELECT * FROM workspace"))
            columns = [r[1] for r in inspect.execute("PRAGMA table_info(workspace)")]
            if len(rows) != 1:
                raise SchemaError("the existing Cipher file must contain its original workspace row")
            workspace = dict(zip(columns, rows[0]))
            if workspace.get("id") != 1 or any(not isinstance(workspace.get(k), str) or not workspace[k].strip()
                                                for k in ("workspace_id", "instance_token", "created_at")):
                raise SchemaError("the existing file has no valid original Cipher workspace identity")
            _verify_audit_rows(inspect)
            self._original_workspace_id = workspace["workspace_id"]
            self._original_created_at = workspace["created_at"]
            self._legacy_recognized = MODE_SCHEMA_NAME not in {r[0] for r in inspect.execute("SELECT name FROM schema_version")}
            if self._legacy_recognized:
                self._mode_origin = "legacy_adopted"
            if not self._legacy_recognized:
                mode = self._mode_proof(inspect, workspace)
                if mode["mode"] == "live":
                    raise WorkspaceModeError("Live workspace runtime and integrations are unavailable in this release")
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            raise SchemaError("the existing file is not a recognized, intact Cipher workspace") from exc
        finally:
            if inspect is not None:
                inspect.close()

    @contextmanager
    def _internal(self) -> Iterator[sqlite3.Connection]:
        """Run the enclosed statements as the Database's own (the authorizer lets the
        current thread assign the guarded pragmas, and no authority refresh runs)."""
        with self._lock:
            conn = self.conn
            previous = conn._authority_owner
            conn._authority_owner = threading.get_ident()
            try:
                yield conn
            finally:
                conn._authority_owner = previous

    # ---- transactions ---------------------------------------------------- #

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One explicit transaction (nested calls join the outermost one).  A
        read-only connection opens a deferred transaction so reads still work;
        its first write is refused by SQLite and raised as WriteAuthorityError.
        Authority is re-checked once the write lock is held, so a release committed
        by another connection is honored.  A commit that fails (for example a journal
        holding fewer lines than it declares) is rolled back, never left open."""
        with self._lock:
            outermost = self._depth == 0
            if outermost:
                self._refresh_authority()
                if self._read_only:
                    self.conn.execute("BEGIN")
                else:
                    self.conn.execute("BEGIN IMMEDIATE")
                    try:
                        self._refresh_authority()  # the write lock is held: no other connection can commit now
                    except BaseException:
                        self.conn.execute("ROLLBACK")
                        raise
            self._depth += 1
            try:
                yield self.conn
            except BaseException:
                self._depth -= 1
                if outermost and self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outermost:
                    self._commit()

    def _commit(self) -> None:
        try:
            self.conn.execute("COMMIT")
        except sqlite3.Error as exc:
            unsealed: list[str] = []
            if self.conn.in_transaction:
                try:
                    unsealed = [r[0] for r in self.conn.execute("SELECT journal_id FROM journal_unsealed ORDER BY journal_id LIMIT 5")]
                except sqlite3.Error:
                    unsealed = []
                self.conn.execute("ROLLBACK")
            if unsealed:
                raise sqlite3.IntegrityError(
                    f"journal {', '.join(unsealed)} holds fewer lines than its sealed line count; a journal must be complete "
                    f"and balanced when its transaction commits, so nothing was committed ({exc})"
                ) from exc
            raise

    @property
    def in_transaction(self) -> bool:
        return self._depth > 0

    # ---- queries ---------------------------------------------------------- #

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, params)

    def scalar(self, sql: str, params: tuple | dict = ()):
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
            return None if row is None else row[0]

    # ---- schema lifecycle ------------------------------------------------- #

    def migrate(self) -> list[dict[str, Any]]:
        """Apply every catalog entry not yet applied to this database.

        Entries are matched by *name*, not by catalog position: modules register
        their schema in load order, so the same module can sit at different
        catalog positions in different releases.  ``schema_version.version`` is
        this database's own application sequence.  An applied entry whose
        statements changed is refused (history is append-only); an applied
        entry no longer in the catalog is reported as orphaned and left alone.
        Schema application is structural, so it runs with ``query_only`` lifted;
        afterwards the connection is read-only again unless this copy holds
        effective write authority.  A copy without write authority that receives
        pending entries (an older backup opened by a newer release) records the
        migration in its audit log, because those entries may backfill data.
        Returns the entries applied now."""
        with self._lock:
            self._refresh_suspended += 1
            try:
                unclaimed_copy = self._lacks_authority()
                was_read_only = self._read_only
                if was_read_only:
                    self._set_query_only(False)
                try:
                    return self._migrate(unclaimed_copy=unclaimed_copy)
                finally:
                    self._sync_data_version()
                    if not self._apply_authority_mode() and was_read_only:
                        self._set_query_only(True)
            finally:
                self._refresh_suspended -= 1

    def _lacks_authority(self) -> bool:
        """True for an existing file workspace that does not hold write authority (a new
        file has no workspace row yet and is not an unclaimed copy)."""
        if self.in_memory:
            return False
        try:
            with self._internal():
                return not self.has_write_authority()
        except (SchemaError, sqlite3.Error):
            return False

    def _migrate(self, *, unclaimed_copy: bool = False, mode_claim: bool = False) -> list[dict[str, Any]]:
        applied_now: list[dict[str, Any]] = []
        with self.transaction() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    statement_count INTEGER NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )"""
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS schema_version_name ON schema_version(name)")
            applied = {r["name"]: dict(r) for r in conn.execute("SELECT * FROM schema_version")}
            next_seq = (max((r["version"] for r in applied.values()), default=0)) + 1
            for _, name, statements in SCHEMA_CATALOG:
                # Structural upgrades retain their existing copied-workspace audit.
                # A mode declaration is an authority act, deferred until the claim.
                if name == MODE_SCHEMA_NAME and unclaimed_copy and not mode_claim:
                    continue
                checksum = catalog_checksum(statements)
                if name in applied:
                    if applied[name]["checksum"] != checksum:
                        raise SchemaError(
                            f"schema entry {name!r} (applied as version {applied[name]['version']}) was modified after it was applied; "
                            "add a new entry instead of editing history"
                        )
                    continue
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_version (version, name, statement_count, checksum, applied_at) VALUES (?,?,?,?,?)",
                    (next_seq, name, len(statements), checksum, utcnow_iso()),
                )
                applied_now.append({"version": next_seq, "name": name, "statement_count": len(statements), "checksum": checksum})
                next_seq += 1
            self._ensure_workspace(conn)
            if MODE_SCHEMA_NAME in {r[0] for r in conn.execute("SELECT name FROM schema_version")}:
                self._declare_practice_mode(conn, origin=self._mode_origin)
            if unclaimed_copy and applied_now:
                ws = conn.execute("SELECT workspace_id FROM workspace WHERE id = 1").fetchone()
                conn.execute(
                    "INSERT INTO audit_log (ts, actor, action, entity_type, entity_id, payload_json, payload_hash, prev_hash, entry_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                    self._audit_tuple("system", "workspace.schema_migrated_without_authority", "workspace", ws[0], {
                        "entries": [{"name": e["name"], "version": e["version"], "checksum": e["checksum"]} for e in applied_now],
                        "note": "schema entries applied to a copy that holds no write authority; they may backfill data, so the migration is recorded",
                    }),
                )
        return applied_now

    def schema_status(self) -> dict[str, Any]:
        rows = self.query("SELECT * FROM schema_version ORDER BY version")
        applied = {r["name"]: r for r in rows}
        catalog_names = {name for _, name, _ in SCHEMA_CATALOG}
        versions = []
        for catalog_position, name, statements in SCHEMA_CATALOG:
            row = applied.get(name)
            versions.append(
                {
                    "version": row["version"] if row else None,
                    "catalog_position": catalog_position,
                    "name": name,
                    "statement_count": len(statements),
                    "checksum": catalog_checksum(statements),
                    "applied": row is not None,
                    "applied_at": row["applied_at"] if row else None,
                    "checksum_matches": (row["checksum"] == catalog_checksum(statements)) if row else None,
                }
            )
        return {
            "current_version": max((r["version"] for r in rows), default=0),
            "catalog_version": SCHEMA_CATALOG[-1][0],
            "pending": [v["name"] for v in versions if not v["applied"]],
            "orphaned": [r["name"] for r in rows if r["name"] not in catalog_names],
            "versions": versions,
        }

    def schema_manifest(self) -> dict[str, Any]:
        """Table and trigger inventory for audit exports."""
        objects = self.query("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type, name")
        return {
            "schema_status": self.schema_status(),
            "objects": [{"type": o["type"], "name": o["name"], "sql_hash": sha256_hex(o["sql"])} for o in objects],
        }

    # ---- workspace write authority ---------------------------------------- #

    def _authority_path(self) -> str | None:
        if self.in_memory:
            return None
        return self.path + ".authority"

    def _ensure_workspace(self, conn: sqlite3.Connection) -> None:
        row = conn.execute("SELECT * FROM workspace WHERE id = 1").fetchone()
        now = utcnow_iso()
        if row is None:
            token = new_id("inst")
            conn.execute(
                "INSERT INTO workspace (id, workspace_id, instance_token, write_authority, authority_epoch, recovery_epoch, reconciled_epoch, created_at, updated_at) VALUES (1,?,?,1,1,0,0,?,?)",
                (new_id("ws"), token, now, now),
            )
            self._write_sidecar(token)
            row = conn.execute("SELECT * FROM workspace WHERE id=1").fetchone()
            self._legacy_recognized = True
        if self._original_workspace_id is None:
            self._original_workspace_id = row["workspace_id"]
            self._original_created_at = row["created_at"]

    def _declare_practice_mode(self, conn: sqlite3.Connection, *, origin: str) -> None:
        ws = dict(conn.execute("SELECT * FROM workspace WHERE id=1").fetchone())
        if ws.get("mode") is not None or ws.get("mode_declaration_seq") is not None:
            self._mode_proof(conn, ws)
            return
        if conn.execute("SELECT 1 FROM audit_log WHERE action=?", (MODE_ACTION,)).fetchone() is not None:
            raise WorkspaceModeError("a workspace with an existing mode declaration cannot be reclassified")
        payload = {"workspace_id": ws["workspace_id"], "mode": "practice", "created_at": ws["created_at"], "origin": origin}
        cursor = conn.execute(
            "INSERT INTO audit_log (ts,actor,action,entity_type,entity_id,payload_json,payload_hash,prev_hash,entry_hash) VALUES (?,?,?,?,?,?,?,?,?)",
            self._audit_tuple("system", MODE_ACTION, "workspace", ws["workspace_id"], payload))
        conn.execute("UPDATE workspace SET mode='practice', mode_declaration_seq=? WHERE id=1", (cursor.lastrowid,))
        self._mode_proof(conn, dict(conn.execute("SELECT * FROM workspace WHERE id=1").fetchone()))

    def _mode_proof(self, conn: sqlite3.Connection, ws: dict) -> dict[str, Any]:
        if (ws.get("workspace_id") != self._original_workspace_id
                or ws.get("created_at") != self._original_created_at):
            raise WorkspaceModeError("the workspace mode no longer belongs to its original workspace identity")
        rows = list(conn.execute("SELECT seq,ts,actor,action,entity_type,entity_id,payload_json,payload_hash,prev_hash,entry_hash "
                                 "FROM audit_log WHERE action=? ORDER BY seq", (MODE_ACTION,)))
        mode, seq = ws.get("mode"), ws.get("mode_declaration_seq")
        if mode is None and seq is None:
            if rows or self._mode_anchor is not None or not self._legacy_recognized:
                raise WorkspaceModeError("the original workspace mode declaration is missing")
            return {"mode": None, "state": "pending_practice_declaration", "verified": False,
                    "workspace_id": ws["workspace_id"], "runtime_authorized": False}
        if mode not in ("practice", "live") or not isinstance(seq, int) or len(rows) != 1:
            raise WorkspaceModeError("the workspace mode has no unique original audit declaration")
        row = tuple(rows[0])
        try:
            payload = json.loads(row[6])
        except (TypeError, ValueError) as exc:
            raise WorkspaceModeError("the original workspace mode declaration is invalid") from exc
        expected_payload = {"workspace_id": self._original_workspace_id, "mode": mode,
                            "created_at": self._original_created_at, "origin": payload.get("origin") if isinstance(payload, dict) else None}
        expected_hash = sha256_hex("|".join([row[8], *row[1:6], row[7]]))
        if (row[0] != seq or row[2:6] != ("system", MODE_ACTION, "workspace", self._original_workspace_id)
                or payload != expected_payload or payload["origin"] not in ("created", "legacy_adopted")
                or row[6] != canonical_json(payload) or row[7] != sha256_hex(row[6]) or row[9] != expected_hash):
            raise WorkspaceModeError("the workspace mode differs from its canonical original audit declaration")
        anchor = (self._original_workspace_id, self._original_created_at, mode, row)
        if self._mode_anchor is not None and anchor != self._mode_anchor:
            raise WorkspaceModeError("the original workspace mode proof changed on this connection")
        self._mode_anchor = anchor
        return {"mode": mode, "state": "declared", "verified": True, "workspace_id": ws["workspace_id"],
                "runtime_authorized": False, "origin": payload["origin"]}

    def mode_status(self) -> dict[str, Any]:
        """Sanitized mode fact; physical authority remains a separate control."""
        with self._lock:
            try:
                status = self._mode_proof(self.conn, self.workspace())
                if status["verified"]:
                    self._check_mode_guards()
            except WorkspaceModeError:
                raise
            except (SchemaError, sqlite3.Error) as exc:
                raise WorkspaceModeError("the original workspace identity or mode proof is missing") from exc
            status["runtime_authorized"] = (status["verified"] and status["mode"] == "practice"
                                             and self.has_write_authority() and not self.read_only)
            return status

    def _check_mode_guards(self) -> None:
        with self._internal() as conn:
            version = conn.execute("PRAGMA schema_version").fetchone()[0]
            if version == getattr(self, "_mode_guard_schema_version", None):
                return
            for statement in MODE_SCHEMA_STATEMENTS[2:]:
                match = re.match(r"CREATE (?:UNIQUE )?(?:INDEX|TRIGGER) (\w+)", statement)
                name = match[1]
                row = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
                if row is None or re.sub(r"\s+", " ", row[0].strip()) != re.sub(r"\s+", " ", statement.strip()):
                    raise WorkspaceModeError("the original workspace mode storage guards are missing or changed")
            self._mode_guard_schema_version = version

    def _check_mode_before_write(self) -> None:
        if self._original_workspace_id is None:
            return  # controlled initialization has not created the row yet
        with self._internal() as conn:
            stamp = (conn.total_changes, conn.execute("PRAGMA data_version").fetchone()[0],
                     conn.execute("PRAGMA schema_version").fetchone()[0])
            if not self.in_memory:
                # The authority sidecar can disappear without changing SQLite's
                # counters. Only mode-proof verification may use this cache.
                self._apply_authority_mode()
            if stamp == getattr(self, "_mode_write_stamp", None):
                return
            status = self.mode_status()
            if status["verified"] and status["mode"] != "practice":
                raise WorkspaceModeError("Live workspace writes and integrations are unavailable in this release")
            # Pending copies stay SQLite read-only. Historical core-only fixture
            # catalogs have no runtime admission and cannot authorize a provider.
            self._mode_write_stamp = stamp

    def require_practice_mode(self, *, allow_pending: bool = False) -> dict[str, Any]:
        """Read-only admission; accepting a declared copied mode does not authorize writes."""
        status = self.mode_status()
        if status["verified"] and status["mode"] == "practice":
            return status
        if (allow_pending and status["state"] == "pending_practice_declaration"
                and self._legacy_recognized and not self.has_write_authority()):
            return status
        if status["mode"] == "live":
            raise WorkspaceModeError("Live workspace runtime and integrations are unavailable in this release")
        raise WorkspaceModeError("this known legacy copy needs an owner claim before its practice mode is declared")

    def _write_sidecar(self, token: str) -> None:
        p = self._authority_path()
        if p is None:
            self._memory_token = token
            return
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(token)

    def _read_sidecar(self) -> str | None:
        p = self._authority_path()
        if p is None:
            return getattr(self, "_memory_token", None)
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except FileNotFoundError:
            return None

    def workspace(self) -> dict[str, Any]:
        row = self.one("SELECT * FROM workspace WHERE id = 1")
        if row is None:
            raise SchemaError("workspace row missing; run migrate()")
        return row

    def has_write_authority(self) -> bool:
        """Effective write authority of this physical copy: the workspace row grants it
        and the sidecar matches its instance token.  In-memory databases always hold it."""
        if self.in_memory:
            return True
        ws = self.workspace()
        if not ws["write_authority"]:
            return False
        return self._read_sidecar() == ws["instance_token"]

    @property
    def read_only(self) -> bool:
        """Whether SQLite currently refuses writes on this connection (``PRAGMA query_only``)."""
        with self._lock:
            return bool(self.conn.execute("PRAGMA query_only").fetchone()[0])

    def _set_query_only(self, on: bool) -> None:
        # A fresh comment makes every internal statement text unique, so a raw statement can
        # never be served from the statement cache entry of one the authorizer allowed.
        with self._internal() as conn:
            conn.execute(f"PRAGMA query_only = {'ON' if on else 'OFF'} /* write-authority {secrets.token_hex(8)} */")
            self._read_only = on

    def _read_data_version(self) -> int:
        with self._internal() as conn:
            return conn.execute("PRAGMA data_version").fetchone()[0]

    def _sync_data_version(self) -> None:
        if self.in_memory:
            return
        try:
            self._data_version = self._read_data_version()
        except sqlite3.Error:
            pass

    def _refresh_authority(self) -> None:
        """Follow a release or claim committed by another connection to this file:
        when ``PRAGMA data_version`` moved, re-evaluate authority and set ``query_only``
        to match.  Cheap when nothing changed (one pragma read)."""
        with self._lock:
            if self._refresh_suspended:
                return
            if not self.in_memory:
                with self._internal() as conn:
                    version = conn.execute("PRAGMA data_version").fetchone()[0]
                    if version != self._data_version:
                        self._data_version = version
                        self._apply_authority_mode()
            self._check_mode_before_write()

    def _apply_authority_mode(self) -> bool:
        """Make the connection read-only exactly when this copy lacks effective write
        authority.  Returns False (changing nothing) when authority cannot be
        evaluated yet, e.g. before the workspace row exists."""
        with self._internal():
            try:
                writable = self.has_write_authority()
            except (SchemaError, sqlite3.Error):
                return False
            if self._original_workspace_id is not None and any(name == MODE_SCHEMA_NAME for _, name, _ in SCHEMA_CATALOG):
                try:
                    mode = self._mode_proof(self.conn, self.workspace())
                except WorkspaceModeError:
                    self._set_query_only(True)
                    raise
                writable = writable and mode["verified"] and mode["mode"] == "practice"
            if self._read_only != (not writable):
                self._set_query_only(not writable)
            return True

    def authority_status(self) -> dict[str, Any]:
        ws = self.workspace()
        sidecar = self._read_sidecar()
        return {
            "workspace_id": ws["workspace_id"],
            "write_authority": bool(ws["write_authority"]),
            "instance_matches": sidecar == ws["instance_token"],
            "effective_write_authority": self.has_write_authority(),
            "authority_epoch": ws["authority_epoch"],
            "recovery_epoch": ws["recovery_epoch"],
            "reconciled_epoch": ws["reconciled_epoch"],
            "release_quarantined": ws["recovery_epoch"] != ws["reconciled_epoch"],
            "read_only": self.read_only,
        }

    def require_write_authority(self) -> None:
        if not self.has_write_authority():
            raise WriteAuthorityError(
                "this workspace copy does not hold write authority; claim it with an explicit approval before mutating records"
            )

    def _challenge_path(self) -> str | None:
        if self.in_memory:
            return None
        return self.path + ".claim-challenge"

    def claim_challenge(self) -> str:
        """A random challenge bound to this physical copy (kept in a file beside it,
        because a read-only copy cannot store it in the database).  Sibling copies
        restored from the same backup get different challenges, so a claim code
        computed for one copy can never open another.  The challenge is retired by
        a successful claim."""
        p = self._challenge_path()
        if p is None:
            if not getattr(self, "_memory_challenge", None):
                self._memory_challenge = secrets.token_hex(16)
            return self._memory_challenge
        try:
            with open(p, "r", encoding="utf-8") as fh:
                value = fh.read().strip()
            if value:
                return value
        except FileNotFoundError:
            pass
        value = secrets.token_hex(16)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(value)
        return value

    def _retire_challenge(self) -> None:
        p = self._challenge_path()
        if p is None:
            self._memory_challenge = None
            return
        try:
            os.remove(p)
        except FileNotFoundError:
            pass

    def expected_claim_code(self, secret: str) -> str:
        """The owner claim code for this copy at its current authority epoch:
        ``hmac-sha256(secret, f"{workspace_id}:{authority_epoch}:{challenge}")`` as hex,
        where the challenge belongs to this physical copy (see claim_challenge).
        Every successful claim bumps the epoch and retires the challenge, so a code
        works for one claim on one copy only."""
        if not isinstance(secret, str) or not secret:
            raise WriteAuthorityError("an owner secret is required to compute a claim code")
        ws = self.workspace()
        message = f"{ws['workspace_id']}:{ws['authority_epoch']}:{self.claim_challenge()}"
        return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()

    def claim_write_authority(self, *, approver: str, reason: str, approval_ref: str | None = None,
                              claim_code: str | None = None, note: str = "") -> dict[str, Any]:
        """Grant write authority to this physical copy as an attested owner action.

        A read-only copy cannot record an approval of its own, so the claim is
        governed here: a non-empty ``approver`` and ``reason`` are required and, when
        ``CIPHER_OWNER_SECRET`` is configured, ``claim_code`` must equal
        ``expected_claim_code(secret)`` for this copy's challenge (compared in
        constant time).  Without the secret the claim is attestation only and is
        recorded as such (Ricky's brief flags it).  ``approval_ref``
        is an optional external reference recorded with the claim.  The claim lifts
        ``query_only`` only for its own writes (new instance token, bumped authority
        epoch, recovery epoch bumped for a restored copy, audit entry) and then
        leaves the connection writable.  A failed claim leaves it read-only."""
        who = _required_text(approver, "approver")
        why = _required_text(reason, "reason")
        if approval_ref is not None and not isinstance(approval_ref, str):
            raise WriteAuthorityError("approval_ref must be a string when given")
        ref = approval_ref.strip() if approval_ref and approval_ref.strip() else None
        if not isinstance(note, str):
            raise WriteAuthorityError("note must be a string")
        secret = os.environ.get(OWNER_SECRET_ENV) or None
        with self._lock:
            # A sidecar is physical state outside SQLite's rollback. Neither a
            # caught nested refusal nor an outer rollback may publish a partial
            # ownership claim; this operation must own its transaction.
            if self.in_transaction or self.conn.in_transaction:
                raise WriteAuthorityError("claim write authority requires a standalone transaction")
            self._refresh_authority()
            self.require_practice_mode(allow_pending=True)
            if secret is not None:
                expected = self.expected_claim_code(secret)
                supplied = "" if claim_code is None else str(claim_code).strip()
                if not supplied or not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
                    raise WriteAuthorityError(
                        f"claiming write authority requires a valid owner claim code because {OWNER_SECRET_ENV} is configured; "
                        "the code is bound to this workspace and its current authority epoch"
                    )
            self._refresh_suspended += 1  # the claim itself decides the mode until it is done
            original_anchor = self._mode_anchor
            try:
                if self._read_only:
                    self._set_query_only(False)
                with self.transaction() as conn:
                    ws = self.workspace()
                    token = new_id("inst")
                    was_restored = self._read_sidecar() != ws["instance_token"]
                    recovery_epoch = ws["recovery_epoch"] + (1 if was_restored else 0)
                    authority_epoch = ws["authority_epoch"] + 1
                    conn.execute(
                        "UPDATE workspace SET instance_token=?, write_authority=1, authority_epoch=?, recovery_epoch=?, updated_at=? WHERE id=1",
                        (token, authority_epoch, recovery_epoch, utcnow_iso()),
                    )
                    conn.execute(
                        "INSERT INTO audit_log (ts, actor, action, entity_type, entity_id, payload_json, payload_hash, prev_hash, entry_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                        self._audit_tuple(who, "workspace.claim_write_authority", "workspace", ws["workspace_id"], {
                            "approver": who, "reason": why, "approval_ref": ref, "note": note,
                            "restored_copy": was_restored, "recovery_epoch": recovery_epoch, "authority_epoch": authority_epoch,
                            "owner_claim_code": "verified" if secret is not None else "not_configured",
                        }),
                    )
                    # Mode adoption joins the successful old authority claim. A
                    # failed claim never leaves a declaration behind on the copy.
                    if self.mode_status()["state"] == "pending_practice_declaration":
                        self._migrate(mode_claim=True)
                    # the sidecar is written last: if the transaction then fails, the token
                    # mismatch leaves this copy without authority rather than with it
                    self._write_sidecar(token)
                self._retire_challenge()
            except BaseException:
                self._mode_anchor = original_anchor
                raise
            finally:
                self._refresh_suspended -= 1
                self._sync_data_version()
                self._apply_authority_mode()
        return self.authority_status()

    def release_write_authority(self, *, note: str = "") -> dict[str, Any]:
        """Give up write authority on this copy; the connection becomes read-only, and so
        does every other connection to the same file before its next statement.  An
        in-memory database always holds authority, so it has nothing to release."""
        with self._lock:
            if self.in_memory:
                raise WriteAuthorityError("an in-memory workspace always holds write authority; there is nothing to release")
            if not self.has_write_authority():
                raise WriteAuthorityError("this workspace copy does not hold write authority; there is nothing to release")
            self._refresh_suspended += 1
            try:
                with self.transaction() as conn:
                    ws = self.workspace()
                    conn.execute("UPDATE workspace SET write_authority=0, updated_at=? WHERE id=1", (utcnow_iso(),))
                    conn.execute(
                        "INSERT INTO audit_log (ts, actor, action, entity_type, entity_id, payload_json, payload_hash, prev_hash, entry_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                        self._audit_tuple("system", "workspace.release_write_authority", "workspace", ws["workspace_id"], {"note": note}),
                    )
                    p = self._authority_path()
                    if p is not None and os.path.exists(p):
                        os.remove(p)
            finally:
                self._refresh_suspended -= 1
                self._sync_data_version()
                self._apply_authority_mode()
        return self.authority_status()

    def _audit_tuple(self, actor: str, action: str, entity_type: str, entity_id: str, payload: dict) -> tuple:
        payload_json = canonical_json(payload)
        payload_hash = sha256_hex(payload_json)
        prev = self.conn.execute("SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = prev[0] if prev else "0" * 64
        ts = utcnow_iso()
        entry_hash = sha256_hex("|".join([prev_hash, ts, actor, action, entity_type, entity_id, payload_hash]))
        return (ts, actor, action, entity_type, entity_id, payload_json, payload_hash, prev_hash, entry_hash)

    # ---- backup / restore -------------------------------------------------- #

    def snapshot(self, target_path: str) -> str:
        """Copy the database to ``target_path``.  The copy has no sidecar, so it
        opens without write authority (restore quarantine)."""
        with self._lock:
            target = sqlite3.connect(target_path)
            try:
                self.conn.backup(target)
            finally:
                target.close()
        return target_path

    def close(self) -> None:
        with self._lock:
            self.conn.close()
