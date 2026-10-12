"""SQLite foundation: versioned schema catalog, transactions and workspace write authority.

The schema catalog is an ordered list of ``(version, name, statements)``.  A
version is applied once, inside one transaction, and its checksum is recorded
so a later edit to an already-applied version is detected instead of silently
diverging.  Immutability of posted journals, audit entries and provider events
is enforced by triggers, not by convention.

Write authority: a database file carries an instance token in a sidecar file.
A copied or restored database has no matching sidecar, so it opens read-only
until an explicit, approved claim.  That is the control the plan describes as
"a copied workspace gains write authority only through fresh approval and
explicit release".
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from .ids import new_id, sha256_hex, utcnow_iso, canonical_json


class SchemaError(RuntimeError):
    """The on-disk schema and the catalog disagree."""


class WriteAuthorityError(PermissionError):
    """The workspace does not currently hold write authority."""


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

SCHEMA_CATALOG: list[tuple[int, str, list[str]]] = [
    (1, "foundation", _V1_FOUNDATION),
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


# --------------------------------------------------------------------------- #
# Database                                                                     #
# --------------------------------------------------------------------------- #

class Database:
    """A single SQLite connection with explicit transactions and a schema lifecycle."""

    def __init__(self, path: str = ":memory:", *, migrate: bool = True):
        self.path = path
        self.in_memory = path == ":memory:"
        self.conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if not self.in_memory:
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = NORMAL")
        self._lock = threading.RLock()
        self._depth = 0
        if migrate:
            self.migrate()

    # ---- transactions ---------------------------------------------------- #

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            outermost = self._depth == 0
            if outermost:
                self.conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self.conn
            except BaseException:
                self._depth -= 1
                if outermost:
                    self.conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outermost:
                    self.conn.execute("COMMIT")

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
        """Apply every catalog version not yet applied.  Returns the versions applied now."""
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
            applied = {r["version"]: dict(r) for r in conn.execute("SELECT * FROM schema_version")}
            for version, name, statements in SCHEMA_CATALOG:
                checksum = catalog_checksum(statements)
                if version in applied:
                    if applied[version]["checksum"] != checksum:
                        raise SchemaError(
                            f"schema version {version} ({name}) was modified after it was applied; "
                            "add a new version instead of editing history"
                        )
                    continue
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_version (version, name, statement_count, checksum, applied_at) VALUES (?,?,?,?,?)",
                    (version, name, len(statements), checksum, utcnow_iso()),
                )
                applied_now.append({"version": version, "name": name, "statement_count": len(statements), "checksum": checksum})
            self._ensure_workspace(conn)
        return applied_now

    def schema_status(self) -> dict[str, Any]:
        applied = {r["version"]: r for r in self.query("SELECT * FROM schema_version ORDER BY version")}
        versions = []
        for version, name, statements in SCHEMA_CATALOG:
            row = applied.get(version)
            versions.append(
                {
                    "version": version,
                    "name": name,
                    "statement_count": len(statements),
                    "checksum": catalog_checksum(statements),
                    "applied": row is not None,
                    "applied_at": row["applied_at"] if row else None,
                    "checksum_matches": (row["checksum"] == catalog_checksum(statements)) if row else None,
                }
            )
        return {
            "current_version": max(applied) if applied else 0,
            "catalog_version": SCHEMA_CATALOG[-1][0],
            "pending": [v["version"] for v in versions if not v["applied"]],
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
        ws = self.workspace()
        if not ws["write_authority"]:
            return False
        return self._read_sidecar() == ws["instance_token"]

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
        }

    def require_write_authority(self) -> None:
        if not self.has_write_authority():
            raise WriteAuthorityError(
                "this workspace copy does not hold write authority; claim it with an explicit approval before mutating records"
            )

    def claim_write_authority(self, *, approval_ref: str, note: str = "") -> dict[str, Any]:
        """Grant write authority to this physical copy.  The caller must pass a
        consumed approval reference for operation ``workspace.claim_write_authority``;
        the claim is recorded with a new instance token and a bumped epoch."""
        if not approval_ref:
            raise WriteAuthorityError("claiming write authority requires an approval reference")
        with self.transaction() as conn:
            ws = self.workspace()
            token = new_id("inst")
            was_restored = self._read_sidecar() != ws["instance_token"]
            recovery_epoch = ws["recovery_epoch"] + (1 if was_restored else 0)
            conn.execute(
                "UPDATE workspace SET instance_token=?, write_authority=1, authority_epoch=authority_epoch+1, recovery_epoch=?, updated_at=? WHERE id=1",
                (token, recovery_epoch, utcnow_iso()),
            )
            self._write_sidecar(token)
            conn.execute(
                "INSERT INTO audit_log (ts, actor, action, entity_type, entity_id, payload_json, payload_hash, prev_hash, entry_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                self._audit_tuple("system", "workspace.claim_write_authority", "workspace", ws["workspace_id"], {"approval_ref": approval_ref, "note": note, "restored_copy": was_restored, "recovery_epoch": recovery_epoch}),
            )
        return self.authority_status()

    def release_write_authority(self, *, note: str = "") -> dict[str, Any]:
        with self.transaction() as conn:
            ws = self.workspace()
            conn.execute("UPDATE workspace SET write_authority=0, updated_at=? WHERE id=1", (utcnow_iso(),))
            p = self._authority_path()
            if p and os.path.exists(p):
                os.remove(p)
            if p is None:
                self._memory_token = None
            conn.execute(
                "INSERT INTO audit_log (ts, actor, action, entity_type, entity_id, payload_json, payload_hash, prev_hash, entry_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                self._audit_tuple("system", "workspace.release_write_authority", "workspace", ws["workspace_id"], {"note": note}),
            )
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
