"""Project cost forecast: versioned approved budgets, full cost to date, estimate to
complete, cost-code rollup and immutable snapshots.

Legacy figures (unchanged meaning and values): ``budget``, ``executed_commitments``,
``pending_exposure``, ``forecast_at_completion`` (executed commitments plus pending
changes), ``variance_to_budget``, ``over_budget``, ``billed_*``, ``retainage_held``,
``paid_to_date``, ``cost_posted_to_date`` (5000 only), ``stored_materials_asset``,
``prime_certified_to_date`` and ``label``.  ``paid_to_date`` sums the provider-accepted
and settled payment intents whose project is this project (supplier bills, released
retainage and staff reimbursements alike); a returned, failed or canceled intent pays
nothing.

Budgets.  ``budget`` is the total of the project's current approved budget version
once one exists; until then it is the legacy ``projects.budget`` column (read only as
that fallback, as the one budget pool described below).  Version 1 is recorded by
``set_initial_budget`` (only while no version exists); every later version comes from
a draft (``prepare_budget_revision``) executed by the core operation ``budget.revise``
(subject: the draft).  Its manifest binds the project, the draft (status, base version,
new lines, their hash and total, reason), the current version number and hash, the
legal entity and currency.  A draft is executable only while it is pending and the
version it was prepared against is still current: when another revision lands first
every other pending draft of the project is superseded and its open approvals are
invalidated, and executing one of them raises ``BudgetRevisionStale`` (a
``StaleApprovalError``).  Versions are append-only, numbered consecutively, chained by
hash (``previous_hash``) and, from version 2, inserted only with their consumed
``budget.revise`` approval and exactly the pending draft it approved (SQLite triggers).
The approval must carry the core's grant and consumption (``approver``, ``granted_at``,
``consumed_by`` and their ``approval.granted`` / ``approval.consumed`` audit entries) and
a manifest that bound exactly this version (project, revision, version number, lines
hash, total, reason and the hash of the version it replaces).  ``projects.budget`` is
kept equal to the current version total: inserting a version sets it, an UPDATE to any
other value is refused and so is re-inserting a versioned project (``INSERT OR REPLACE``
would otherwise delete and re-create it without firing the update guard);
``Cipher.set_budget`` included.  ``verify`` re-checks all of it.  ``budget.revise`` may
be executed with ``period_id``; the period must then be open and is recorded as the
version's effective period.  (A writer with raw SQL who also forges the approval row and
appends audit entries is beyond what triggers can stop; ``Audit.verify_chain`` and
``verify`` are the detection for that, as elsewhere in the prototype.)

Cost codes are compared case-insensitively with whitespace collapsed and reported in
upper case.  ``UNMAPPED`` carries cost, commitments and pending changes that map to no
code (an SOV line without a cost code, which includes every line a change order adds;
reimbursable cost; unattributed ledger cost) and, until a project is versioned, the
unallocated project budget.  A budget version may give ``UNMAPPED`` its own line, which
is how uncoded commitments are budgeted once a project is versioned.

Cost to date (ledger project activity, debit less credit): subcontract 5000, labor
5300 and reimbursable 5100, reported separately and in total.  Per cost code:

* subcontract cost follows the supplier bill each 5000 line belongs to: a ``bill``
  journal (and any reversal of it) and a supplier credit note (and any reversal of it)
  belong to their bill.  Each bill's installed value this period goes to its SOV lines'
  cost codes exactly; whatever its journals and credits add or remove beyond that (a
  credit note, a reversal) is spread over the same codes in proportion to the bill's
  installed value (its stored-material additions when it installed nothing).  5000
  activity from any other source is a residual on ``UNMAPPED``.  The codes therefore
  always tie to the ledger, and with no credits or reversals each code's subcontract cost
  is the certified installed value of its SOV lines;
* labor cost follows the labor plugin's phases (the phase code is the cost code): a
  5300 line of a ``labor_timesheet`` journal is matched to the timesheet's approved
  entries grouped by phase, in the plugin's posting order (or, failing that, to the
  phase code its memo names when that phase exists on the project); a reversal line
  takes the code of the line it reverses; any other 5300 line is ``UNMAPPED``;
* reimbursable cost carries no cost code and is ``UNMAPPED``.

Committed remaining is, over SOV lines of executed commitments, the line amount less its
certified installed value (a closed commitment has nothing remaining; stored material is
an asset until installed, so it is still remaining cost; a supplier credit lowers cost to
date, not the certified value, so it lowers the forecast).

The budget each code is measured against (``budget_source`` per code):

* ``approved_version``: the code's line in the current approved budget version;
* ``none``: the code has no budget line (in a versioned project, or the unversioned pool
  below ran out before it), so all of its forecast is unbudgeted (``unbudgeted_fac``
  totals it);
* until the project is versioned its budget is not split by code.  It is one pool: each
  cost code draws from it, in code order, the forecast it needs (cost to date plus
  committed remaining, ``drawn_from_project_budget``) and whatever is left stays on
  ``UNMAPPED`` (``project_budget``).  Cost and commitments on any code are thus measured
  against the one project budget, never counted again against an unspent pool, and the
  project ETC is then ``max(budget - cost to date, committed remaining)`` overall.  A
  versioned project's budget lines are never pooled: an unspent line still forecasts its
  budget even when work coded elsewhere (or not coded) overruns, until a revision moves
  budget between lines.

Estimate to complete per cost code: ``max(budget - cost to date, committed remaining)``
when the code has a budget above zero, otherwise its committed remaining (with no budget
left to spend, a negative cost - a credit - is not remaining work).  Pending changes
(pending or approved, not executed) are a separate exposure on the code of the SOV line
they change (``UNMAPPED`` when they add a line).  ``fac_v2`` = cost to date + ETC +
pending exposure; ``uncommitted_budget`` = budget - executed commitments, per code and in
total (executed commitments not explained by SOV lines are an ``UNMAPPED`` residual).
Per-code figures add up to the project totals.

Snapshots (``snapshot``) store every figure of ``project()`` with the hash of the inputs
it was computed from; they are append-only, numbered per project, uniquely labelled
(case-insensitive) and never change.  ``variance_to_previous`` compares the latest two.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Callable

from ..core.approvals import Approvals, StaleApprovalError, build_manifest, material_hash
from ..core.db import Database, register_schema_version
from ..core.ids import canonical_json, hash_json, loads, new_id, utcnow_iso
from ..core.money import ZERO, D, MoneyError, allocate, fmt, money, total
from .commitments import Commitments
from .ledger import Ledger

OP_REVISE = "budget.revise"
REVISION_SUBJECT = "budget_revision"
UNMAPPED = "UNMAPPED"
LABEL = "SHADOW - synthetic prototype, not authoritative"
COST_TYPES: tuple[tuple[str, str], ...] = (("subcontract", "5000"), ("labor", "5300"), ("reimbursable", "5100"))
LABOR_SOURCE = "labor_timesheet"
BILL_SOURCE = "bill"
CREDIT_NOTE_SOURCE = "supplier_credit_note"  # bills.CREDIT_NOTE_SOURCE
SOURCE_APPROVED = "approved_version"
SOURCE_DRAWN = "drawn_from_project_budget"
SOURCE_POOL = "project_budget"
SOURCE_NONE = "none"
MAX_LINES = 500
MAX_CODE_LENGTH = 64
MAX_REASON_LENGTH = 500
MAX_LABEL_LENGTH = 120
MAX_ACTOR_LENGTH = 200

# Append-only schema entry.  Never edit these statements once applied; add a new
# uniquely named entry instead.
FORECAST_SCHEMA_NAME = "forecast_budget_versions"
FORECAST_SCHEMA_STATEMENTS = [
    """CREATE TABLE budget_revisions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        base_version INTEGER NOT NULL CHECK (base_version >= 1),
        base_version_hash TEXT NOT NULL,
        total TEXT NOT NULL,
        lines_json TEXT NOT NULL,
        lines_hash TEXT NOT NULL,
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        status TEXT NOT NULL CHECK (status IN ('pending','executed','superseded','cancelled')),
        prepared_by TEXT NOT NULL CHECK (length(trim(prepared_by)) > 0),
        prepared_at TEXT NOT NULL,
        approval_id TEXT REFERENCES approvals(id),
        resulting_version INTEGER,
        resolved_by TEXT,
        resolved_at TEXT,
        resolution_note TEXT,
        CHECK ((status = 'executed') = (approval_id IS NOT NULL AND resulting_version IS NOT NULL))
    )""",
    "CREATE INDEX budget_revisions_project ON budget_revisions (project_id, status)",
    "CREATE UNIQUE INDEX budget_revisions_one_approval ON budget_revisions (approval_id) WHERE approval_id IS NOT NULL",
    """CREATE TABLE budget_versions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        version INTEGER NOT NULL CHECK (version >= 1),
        total TEXT NOT NULL,
        lines_json TEXT NOT NULL,
        lines_hash TEXT NOT NULL,
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        approval_id TEXT REFERENCES approvals(id),
        revision_id TEXT REFERENCES budget_revisions(id),
        previous_hash TEXT,
        version_hash TEXT NOT NULL,
        legacy_budget TEXT,
        effective_period_id TEXT REFERENCES periods(id),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        created_at TEXT NOT NULL,
        UNIQUE (project_id, version),
        CHECK ((version = 1) = (approval_id IS NULL)),
        CHECK ((version = 1) = (revision_id IS NULL)),
        CHECK ((version = 1) = (previous_hash IS NULL))
    )""",
    "CREATE UNIQUE INDEX budget_versions_one_approval ON budget_versions (approval_id) WHERE approval_id IS NOT NULL",
    "CREATE UNIQUE INDEX budget_versions_one_revision ON budget_versions (revision_id) WHERE revision_id IS NOT NULL",
    "CREATE TRIGGER budget_versions_no_update BEFORE UPDATE ON budget_versions BEGIN SELECT RAISE(ABORT, 'approved budget versions are immutable; revise the budget through budget.revise'); END",
    "CREATE TRIGGER budget_versions_no_delete BEFORE DELETE ON budget_versions BEGIN SELECT RAISE(ABORT, 'approved budget versions are immutable'); END",
    # INSERT OR REPLACE would delete a colliding row without firing the delete trigger
    """CREATE TRIGGER budget_versions_insert_guard BEFORE INSERT ON budget_versions
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM budget_versions WHERE id = NEW.id)
                  OR (NEW.approval_id IS NOT NULL AND EXISTS (SELECT 1 FROM budget_versions WHERE approval_id = NEW.approval_id))
                  OR (NEW.revision_id IS NOT NULL AND EXISTS (SELECT 1 FROM budget_versions WHERE revision_id = NEW.revision_id))
                THEN RAISE(ABORT, 'approved budget versions are immutable: a version, its approval and its revision are never reused or replaced')
                WHEN NEW.version IS NOT COALESCE((SELECT MAX(version) FROM budget_versions WHERE project_id = NEW.project_id), 0) + 1
                THEN RAISE(ABORT, 'budget versions are numbered consecutively per project')
                WHEN NEW.version > 1 AND NEW.previous_hash IS NOT (SELECT version_hash FROM budget_versions WHERE project_id = NEW.project_id AND version = NEW.version - 1)
                THEN RAISE(ABORT, 'a budget version must chain to the version it replaces')
            END;
        END""",
    """CREATE TRIGGER budget_versions_need_consumed_approval BEFORE INSERT ON budget_versions
        WHEN NEW.version > 1 AND NOT EXISTS (
            SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND a.status = 'consumed' AND a.operation = 'budget.revise'
               AND a.subject_type = 'budget_revision' AND a.subject_id = NEW.revision_id)
        BEGIN SELECT RAISE(ABORT, 'a budget revision takes effect only through its consumed budget.revise approval'); END""",
    """CREATE TRIGGER budget_versions_match_revision BEFORE INSERT ON budget_versions
        WHEN NEW.version > 1 AND NOT EXISTS (
            SELECT 1 FROM budget_revisions r WHERE r.id = NEW.revision_id AND r.project_id = NEW.project_id AND r.status = 'pending'
               AND r.base_version = NEW.version - 1 AND r.base_version_hash = NEW.previous_hash
               AND r.lines_hash = NEW.lines_hash AND r.lines_json = NEW.lines_json AND r.total = NEW.total AND r.reason = NEW.reason)
        BEGIN SELECT RAISE(ABORT, 'a budget version must carry exactly the pending revision it executes'); END""",
    "CREATE TRIGGER budget_revisions_no_delete BEFORE DELETE ON budget_revisions BEGIN SELECT RAISE(ABORT, 'budget revision drafts are never deleted; cancel them instead'); END",
    """CREATE TRIGGER budget_revisions_born_pending BEFORE INSERT ON budget_revisions
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM budget_revisions WHERE id = NEW.id)
                THEN RAISE(ABORT, 'budget revision drafts are never replaced')
                WHEN NEW.status IS NOT 'pending' OR NEW.approval_id IS NOT NULL OR NEW.resulting_version IS NOT NULL
                  OR NEW.resolved_by IS NOT NULL OR NEW.resolved_at IS NOT NULL
                THEN RAISE(ABORT, 'a budget revision draft is born pending')
            END;
        END""",
    """CREATE TRIGGER budget_revisions_content_immutable BEFORE UPDATE ON budget_revisions
        WHEN NEW.id IS NOT OLD.id OR NEW.project_id IS NOT OLD.project_id OR NEW.base_version IS NOT OLD.base_version
          OR NEW.base_version_hash IS NOT OLD.base_version_hash OR NEW.total IS NOT OLD.total OR NEW.lines_json IS NOT OLD.lines_json
          OR NEW.lines_hash IS NOT OLD.lines_hash OR NEW.reason IS NOT OLD.reason OR NEW.prepared_by IS NOT OLD.prepared_by
          OR NEW.prepared_at IS NOT OLD.prepared_at
        BEGIN SELECT RAISE(ABORT, 'a budget revision draft is immutable; prepare a new one'); END""",
    """CREATE TRIGGER budget_revisions_resolve_once BEFORE UPDATE ON budget_revisions
        WHEN OLD.status IS NOT 'pending' OR NEW.status NOT IN ('executed','superseded','cancelled')
        BEGIN SELECT RAISE(ABORT, 'a budget revision is resolved once: pending -> executed, superseded or cancelled'); END""",
    """CREATE TRIGGER budget_revisions_executed_has_version BEFORE UPDATE ON budget_revisions
        WHEN NEW.status = 'executed' AND NOT EXISTS (
            SELECT 1 FROM budget_versions v WHERE v.revision_id = NEW.id AND v.approval_id IS NEW.approval_id AND v.version IS NEW.resulting_version)
        BEGIN SELECT RAISE(ABORT, 'a budget revision is executed only together with the budget version it created'); END""",
    # once a project is versioned its legacy budget column always equals the current version total
    """CREATE TRIGGER projects_versioned_budget_guard BEFORE UPDATE OF budget ON projects
        WHEN EXISTS (SELECT 1 FROM budget_versions WHERE project_id = NEW.id)
         AND NEW.budget IS NOT (SELECT total FROM budget_versions WHERE project_id = NEW.id ORDER BY version DESC LIMIT 1)
        BEGIN SELECT RAISE(ABORT, 'this project''s budget is versioned; change it through a budget.revise approval'); END""",
    """CREATE TABLE forecast_snapshots (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        label TEXT NOT NULL COLLATE NOCASE CHECK (length(trim(label)) > 0),
        budget_version INTEGER,
        inputs_hash TEXT NOT NULL,
        figures_json TEXT NOT NULL,
        figures_hash TEXT NOT NULL,
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        created_at TEXT NOT NULL,
        UNIQUE (project_id, sequence),
        UNIQUE (project_id, label)
    )""",
    "CREATE TRIGGER forecast_snapshots_no_update BEFORE UPDATE ON forecast_snapshots BEGIN SELECT RAISE(ABORT, 'forecast snapshots are immutable'); END",
    "CREATE TRIGGER forecast_snapshots_no_delete BEFORE DELETE ON forecast_snapshots BEGIN SELECT RAISE(ABORT, 'forecast snapshots are immutable'); END",
    """CREATE TRIGGER forecast_snapshots_insert_guard BEFORE INSERT ON forecast_snapshots
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM forecast_snapshots WHERE id = NEW.id)
                  OR EXISTS (SELECT 1 FROM forecast_snapshots WHERE project_id = NEW.project_id AND label = NEW.label COLLATE NOCASE)
                THEN RAISE(ABORT, 'forecast snapshots are immutable: a snapshot id or label is never reused or replaced')
                WHEN NEW.sequence IS NOT COALESCE((SELECT MAX(sequence) FROM forecast_snapshots WHERE project_id = NEW.project_id), 0) + 1
                THEN RAISE(ABORT, 'forecast snapshots are numbered consecutively per project')
            END;
        END""",
]
register_schema_version(FORECAST_SCHEMA_NAME, FORECAST_SCHEMA_STATEMENTS)

# Follow-on guards, as their own catalog entry (the entry above is applied history and
# stays as it is):
# * INSERT OR REPLACE deletes a colliding projects row without firing the update guard,
#   so a versioned project is never re-inserted;
# * inserting a version sets the project's legacy budget column to its total, so no
#   insert path leaves the column behind the current version;
# * a version from 2 on needs an approval the core granted and consumed (approver,
#   grant and consumption recorded, with their audit entries) whose manifest bound
#   exactly this version, not merely any consumed budget.revise approval of the draft.
FORECAST_GUARDS_SCHEMA_NAME = "forecast_budget_guards"
FORECAST_GUARDS_SCHEMA_STATEMENTS = [
    """CREATE TRIGGER projects_versioned_no_reinsert BEFORE INSERT ON projects
        WHEN EXISTS (SELECT 1 FROM budget_versions WHERE project_id = NEW.id)
        BEGIN SELECT RAISE(ABORT, 'this project''s budget is versioned; the project is never re-inserted or replaced (change its budget through a budget.revise approval)'); END""",
    """CREATE TRIGGER budget_versions_set_project_budget AFTER INSERT ON budget_versions
        BEGIN UPDATE projects SET budget = NEW.total WHERE id = NEW.project_id; END""",
    """CREATE TRIGGER budget_versions_bound_by_granted_approval BEFORE INSERT ON budget_versions
        WHEN NEW.version > 1 AND NOT EXISTS (
            SELECT 1 FROM approvals a
             WHERE a.id = NEW.approval_id AND a.status = 'consumed' AND a.operation = 'budget.revise'
               AND a.subject_type = 'budget_revision' AND a.subject_id = NEW.revision_id
               AND a.approver IS NOT NULL AND a.granted_at IS NOT NULL AND a.consumed_by IS NOT NULL
               AND json_extract(a.manifest_json, '$.operation') = 'budget.revise'
               AND json_extract(a.manifest_json, '$.subject.id') = NEW.revision_id
               AND json_extract(a.manifest_json, '$.bindings.project_id') = NEW.project_id
               AND json_extract(a.manifest_json, '$.bindings.revision_id') = NEW.revision_id
               AND json_extract(a.manifest_json, '$.bindings.new_version') = NEW.version
               AND json_extract(a.manifest_json, '$.bindings.new_lines_hash') = NEW.lines_hash
               AND json_extract(a.manifest_json, '$.bindings.new_total') = NEW.total
               AND json_extract(a.manifest_json, '$.bindings.reason') = NEW.reason
               AND json_extract(a.manifest_json, '$.bindings.current_version_hash') = NEW.previous_hash
               AND EXISTS (SELECT 1 FROM audit_log g WHERE g.action = 'approval.granted' AND g.entity_type = 'approval' AND g.entity_id = a.id)
               AND EXISTS (SELECT 1 FROM audit_log k WHERE k.action = 'approval.consumed' AND k.entity_type = 'approval' AND k.entity_id = a.id))
        BEGIN SELECT RAISE(ABORT, 'a budget version takes effect only through the granted and consumed budget.revise approval that bound exactly this version'); END""",
]
register_schema_version(FORECAST_GUARDS_SCHEMA_NAME, FORECAST_GUARDS_SCHEMA_STATEMENTS)

# the fields a budget version's hash covers (lines through lines_hash)
_VERSION_HASH_FIELDS = (
    "id", "project_id", "version", "total", "lines_hash", "reason", "approval_id", "revision_id", "previous_hash",
    "legacy_budget", "effective_period_id", "created_by", "created_at",
)
_LABOR_MEMO_PREFIX = "labor phase "
_REVERSAL_PREFIX = "reversal: "
_LABOR_MEMO_TAIL = re.compile(r"\d+(\.\d+)? h \(timesheet [^()]*\)")


class ForecastError(RuntimeError):
    pass


class BudgetAlreadySet(ForecastError):
    """set_initial_budget refused: the project already has an approved budget version."""


class BudgetRevisionStale(ForecastError, StaleApprovalError):
    """The draft is no longer pending, or another revision landed after it was prepared.
    Raised while building the budget.revise manifest, so no approval can be requested for
    it and executing an earlier approval invalidates that approval."""


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #

def normalize_cost_code(value: Any) -> str:
    """Cost codes compare case-insensitively with whitespace collapsed."""
    if value is None:
        return ""
    return " ".join(str(value).split()).upper()


def _code_or_unmapped(value: Any) -> str:
    return normalize_cost_code(value) or UNMAPPED


def phase_code_from_memo(memo: Any) -> str | None:
    """The phase code named by a labor posting memo
    (``labor phase {code}: {hours} h (timesheet {id})``, possibly behind ``reversal: ``)."""
    text = memo if isinstance(memo, str) else ""
    while text.startswith(_REVERSAL_PREFIX):
        text = text[len(_REVERSAL_PREFIX):]
    if not text.startswith(_LABOR_MEMO_PREFIX):
        return None
    head, sep, tail = text[len(_LABOR_MEMO_PREFIX):].rpartition(": ")
    if not sep or not _LABOR_MEMO_TAIL.fullmatch(tail):
        return None
    return normalize_cost_code(head) or None


def _text(value: Any, label: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ForecastError(f"{label} is required")
    text = value.strip()
    if len(text) > max_length:
        raise ForecastError(f"{label} is longer than {max_length} characters")
    return text


def _add(acc: dict[str, Decimal], code: str, amount: Decimal) -> None:
    acc[code] = money(acc.get(code, ZERO) + amount)


def _spread(amount: Decimal, *weightings: dict[str, Decimal]) -> dict[str, Decimal]:
    """Split ``amount`` exactly over cost codes in proportion to the first weighting that
    has a positive weight (largest remainder); ``UNMAPPED`` takes it when none has."""
    for weights in weightings:
        codes = sorted(code for code, w in weights.items() if w > 0)
        if codes:
            return dict(zip(codes, allocate(amount, [weights[code] for code in codes])))
    return {UNMAPPED: money(amount)}


def _canonical_lines(lines: Any) -> tuple[list[dict[str, str]], Decimal]:
    """Validate budget lines and return them sorted by cost code with the exact total."""
    if isinstance(lines, (str, bytes, dict)) or not isinstance(lines, (list, tuple)):
        raise ForecastError("budget lines must be a list of {cost_code, amount}")
    if not lines:
        raise ForecastError("a budget needs at least one cost-code line")
    if len(lines) > MAX_LINES:
        raise ForecastError(f"a budget has at most {MAX_LINES} cost-code lines")
    by_code: dict[str, Decimal] = {}
    for idx, raw in enumerate(lines, start=1):
        if not isinstance(raw, dict):
            raise ForecastError(f"budget line {idx} must be a mapping with cost_code and amount")
        extra = sorted(str(k) for k in set(raw) - {"cost_code", "amount"})
        if extra:
            raise ForecastError(f"budget line {idx} has unknown field(s) {', '.join(extra)}")
        if "cost_code" not in raw or "amount" not in raw:
            raise ForecastError(f"budget line {idx} needs a cost_code and an amount")
        if not isinstance(raw["cost_code"], str):
            raise ForecastError(f"budget line {idx}: the cost code must be text")
        code = normalize_cost_code(raw["cost_code"])
        if not code:
            raise ForecastError(f"budget line {idx}: the cost code is empty")
        if len(code) > MAX_CODE_LENGTH or not code.isprintable():
            raise ForecastError(f"budget line {idx}: cost code {code[:20]!r} must be printable and at most {MAX_CODE_LENGTH} characters")
        if code in by_code:
            raise ForecastError(f"cost code {code!r} appears twice (codes compare case-insensitively, whitespace collapsed)")
        try:
            exact = D(raw["amount"])
            amount = money(raw["amount"])
        except MoneyError as exc:
            raise ForecastError(f"budget line {idx} ({code}): {exc}") from exc
        if exact != amount:
            raise ForecastError(f"budget line {idx} ({code}): amount {raw['amount']!r} has more than two decimal places")
        if amount < 0:
            raise ForecastError(f"budget line {idx} ({code}): a budget amount cannot be negative")
        # '-0' is zero: never a signed '-0.00' whose hash would pass for a different budget
        by_code[code] = ZERO if amount == 0 else amount
    try:
        budget_total = total(by_code.values())
    except MoneyError as exc:
        raise ForecastError(f"budget total is out of range: {exc}") from exc
    if budget_total <= 0:
        raise ForecastError("a budget must total more than zero")
    return [{"cost_code": c, "amount": fmt(by_code[c])} for c in sorted(by_code)], budget_total


def _version_hash(record: dict[str, Any]) -> str:
    return hash_json({k: record.get(k) for k in _VERSION_HASH_FIELDS})


def _delta(previous: Any, latest: Any) -> dict[str, Any]:
    p = money(previous if previous is not None else "0")
    q = money(latest if latest is not None else "0")
    return {"previous": fmt(p), "latest": fmt(q), "change": fmt(q - p)}


# --------------------------------------------------------------------------- #
# Forecast                                                                     #
# --------------------------------------------------------------------------- #

class Forecast:
    def __init__(self, db: Database, commitments: Commitments, ledger: Ledger, audit: Any = None):
        self.db = db
        self.commitments = commitments
        self.ledger = ledger
        self.audit = audit or ledger.audit
        self.approvals = Approvals(db, self.audit)

    # ---- the forecast ------------------------------------------------------- #

    def project(self, project_id: str) -> dict[str, Any]:
        """Every figure of the project's forecast (legacy keys first, then v2)."""
        return self._figures(self._gather(project_id))

    def _gather(self, project_id: str) -> dict[str, Any]:
        """Every input the forecast is computed from, as plain JSON (its hash is the
        snapshot's inputs hash)."""
        project = self.db.one("SELECT id, entity, currency, budget FROM projects WHERE id=?", (project_id,))
        if project is None:
            raise KeyError(project_id)
        version = self._current_version(project_id)
        commitments = self.db.query(
            "SELECT id, status, executed_amount, version FROM commitments WHERE project_id=? ORDER BY created_at, id", (project_id,))
        sov_lines = self.db.query(
            """SELECT s.id, s.commitment_id, s.line_no, s.cost_code, s.amount FROM sov_lines s JOIN commitments c ON c.id = s.commitment_id
               WHERE c.project_id=? ORDER BY c.created_at, c.id, s.line_no""", (project_id,))
        pending_changes = self.db.query(
            """SELECT ch.id, ch.commitment_id, ch.sov_line_id, ch.amount, ch.status FROM changes ch JOIN commitments c ON c.id = ch.commitment_id
               WHERE c.project_id=? AND ch.status IN ('pending','approved') ORDER BY ch.created_at, ch.id""", (project_id,))
        # Paid to date: provider-accepted (and settled) intents of *this* project only.  Every
        # intent records its project; an intent created before intents carried one is attributed
        # through the bill it paid, never through the absence of a bill (that leaked retainage and
        # reimbursement payments of every other project into this one).
        paid = self.db.query(
            """SELECT p.id, p.status, p.amount FROM payment_intents p
               LEFT JOIN bills b ON b.id=p.bill_id LEFT JOIN commitments c ON c.id=b.commitment_id
               WHERE p.status IN ('accepted','settled') AND (p.project_id=? OR (p.project_id IS NULL AND c.project_id=?))
               ORDER BY p.created_at, p.id""",
            (project_id, project_id),
        )
        ar = self.db.one("SELECT COALESCE(MAX(certified_cumulative),'0.00') AS certified FROM prime_bills WHERE project_id=? AND status IN ('posted','sent','collected')", (project_id,))
        cost_lines = self._cost_lines(project_id)
        return {
            "project": project,
            "budget_version": None if version is None else {
                "version": version["version"], "total": version["total"], "lines": version["lines"],
                "lines_hash": version["lines_hash"], "version_hash": version["version_hash"],
            },
            "commitments": commitments,
            "sov_lines": sov_lines,
            "pending_changes": pending_changes,
            "certified": self._certified_lines(project_id),
            "billing": self._billing(project_id),
            "cost_lines": cost_lines,
            "bill_lines": self._bill_lines(project_id, {ln["bill_id"] for ln in cost_lines if ln.get("bill_id")}),
            "paid": paid,
            "prime_certified": fmt(money(ar["certified"])),
            "balances": {
                "5000": fmt(self.ledger.balance("5000", project_id=project_id)),
                "1300": fmt(self.ledger.balance("1300", project_id=project_id)),
            },
        }

    def _billing(self, project_id: str) -> list[dict[str, Any]]:
        """The latest posted or paid supplier bill of each commitment (cumulative figures)."""
        out = []
        for row in self.db.query(
            "SELECT b.commitment_id, MAX(b.sequence) AS seq FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE c.project_id=? AND b.status IN ('posted','paid') GROUP BY b.commitment_id",
            (project_id,),
        ):
            b = self.db.one("SELECT id, cumulative_net, cumulative_gross, cumulative_retainage FROM bills WHERE commitment_id=? AND sequence=?", (row["commitment_id"], row["seq"]))
            out.append({"commitment_id": row["commitment_id"], "sequence": row["seq"], "bill_id": b["id"], "cumulative_net": b["cumulative_net"],
                        "cumulative_gross": b["cumulative_gross"], "cumulative_retainage": b["cumulative_retainage"]})
        return sorted(out, key=lambda r: r["commitment_id"])

    def _certified_lines(self, project_id: str) -> list[dict[str, Any]]:
        """Certified installed value per SOV line: the line on the latest posted or paid bill carrying it."""
        latest: dict[str, dict[str, Any]] = {}
        for r in self.db.query(
            """SELECT bl.sov_line_id, bl.cumulative_installed, b.id AS bill_id, b.sequence FROM bill_lines bl
               JOIN bills b ON b.id = bl.bill_id JOIN commitments c ON c.id = b.commitment_id
               WHERE c.project_id = ? AND b.status IN ('posted','paid') ORDER BY b.commitment_id, b.sequence, bl.sov_line_id""",
            (project_id,),
        ):
            latest[r["sov_line_id"]] = r
        return [{"sov_line_id": sid, "cumulative_installed": latest[sid]["cumulative_installed"], "bill_id": latest[sid]["bill_id"]} for sid in sorted(latest)]

    def _cost_lines(self, project_id: str) -> list[dict[str, Any]]:
        accounts = tuple(acct for _, acct in COST_TYPES)
        kinds = {acct: kind for kind, acct in COST_TYPES}
        rows = self.db.query(
            f"""SELECT l.journal_id, l.line_no, l.account_code, l.debit, l.credit, l.memo, j.source_type, j.source_id, j.reversal_of
               FROM journal_lines l JOIN journals j ON j.id = l.journal_id
               WHERE l.project_id = ? AND l.account_code IN ({",".join("?" for _ in accounts)})
               ORDER BY j.posted_at, j.id, l.line_no""",
            (project_id, *accounts),
        )
        resolve = self._labor_resolver(project_id) if any(r["account_code"] == "5300" for r in rows) else None
        credited = self._credited_bills({r["source_id"] for r in rows if r["account_code"] == "5000" and r["source_type"] == CREDIT_NOTE_SOURCE})

        def bill_of(r: dict[str, Any]) -> str | None:
            """The supplier bill a 5000 line belongs to: a bill journal or its reversal, a
            credit note on the bill or its reversal (both keep their source)."""
            if r["account_code"] != "5000":
                return None
            if r["source_type"] == BILL_SOURCE:
                return r["source_id"]
            if r["source_type"] == CREDIT_NOTE_SOURCE:
                return credited.get(r["source_id"])
            return None

        return [{
            "journal_id": r["journal_id"], "line_no": r["line_no"], "account": r["account_code"], "cost_type": kinds[r["account_code"]],
            "debit": r["debit"], "credit": r["credit"],
            "cost_code": resolve(r) if (resolve is not None and r["account_code"] == "5300") else None,
            "bill_id": bill_of(r),
        } for r in rows]

    def _credited_bills(self, credit_note_ids: set[str]) -> dict[str, str]:
        if not credit_note_ids or not self._has_tables("bill_credit_notes"):
            return {}
        ids = sorted(credit_note_ids)
        return {r["id"]: r["bill_id"] for r in self.db.query(
            f"SELECT id, bill_id FROM bill_credit_notes WHERE id IN ({','.join('?' for _ in ids)})", tuple(ids))}

    def _bill_lines(self, project_id: str, bill_ids: set[str]) -> list[dict[str, Any]]:
        """Per SOV line, what each bill that 5000 activity belongs to installed (and added
        as stored material) this period; bills of other projects carry no lines here."""
        if not bill_ids:
            return []
        ids = sorted(bill_ids)
        return self.db.query(
            f"""SELECT bl.bill_id, bl.sov_line_id, bl.installed_this_period, bl.stored_added FROM bill_lines bl
               JOIN bills b ON b.id = bl.bill_id JOIN commitments c ON c.id = b.commitment_id
               WHERE c.project_id = ? AND bl.bill_id IN ({','.join('?' for _ in ids)}) ORDER BY bl.bill_id, bl.sov_line_id""",
            (project_id, *ids),
        )

    # ---- labor phases as cost codes ----------------------------------------- #

    def _has_tables(self, *names: str) -> bool:
        found = {r["name"] for r in self.db.query(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({','.join('?' for _ in names)})", tuple(names))}
        return found == set(names)

    def _labor_resolver(self, project_id: str) -> Callable[[dict[str, Any]], str]:
        if not self._has_tables("labor_phases", "labor_entries"):
            return lambda row: UNMAPPED
        phases = {normalize_cost_code(r["code"]) for r in self.db.query("SELECT code FROM labor_phases WHERE project_id=?", (project_id,))}
        phases.discard("")
        maps: dict[str, dict[int, str]] = {}

        def resolve(row: dict[str, Any]) -> str:
            if row["source_type"] != LABOR_SOURCE:
                return UNMAPPED
            root = self._root_journal(row["journal_id"], row["reversal_of"])
            if root not in maps:
                maps[root] = self._timesheet_line_codes(root, row["source_id"], project_id)
            code = maps[root].get(row["line_no"])
            if code:
                return code
            named = phase_code_from_memo(row["memo"])
            return named if named in phases else UNMAPPED

        return resolve

    def _root_journal(self, journal_id: str, reversal_of: str | None) -> str:
        """The journal a reversal (of a reversal ...) ultimately reverses; its lines keep the
        original line numbers."""
        current, parent, depth = journal_id, reversal_of, 0
        while parent and depth < 16:
            current = parent
            row = self.db.one("SELECT reversal_of FROM journals WHERE id=?", (current,))
            parent = row["reversal_of"] if row else None
            depth += 1
        return current

    def _timesheet_line_codes(self, journal_id: str, timesheet_id: str, project_id: str) -> dict[int, str]:
        """Line number -> phase code for a timesheet journal's 5300 lines on this project, when
        they match the timesheet's approved entries grouped by phase in posting order."""
        lines = self.db.query(
            "SELECT line_no, debit, credit FROM journal_lines WHERE journal_id=? AND account_code='5300' AND project_id=? ORDER BY line_no",
            (journal_id, project_id))
        groups: dict[str, dict[str, Any]] = {}
        for r in self.db.query(
            """SELECT e.phase_id, p.code AS phase_code, e.cost_amount FROM labor_entries e JOIN labor_phases p ON p.id = e.phase_id
               WHERE e.timesheet_id = ? AND e.project_id = ? AND e.status IN ('approved','billed')""",
            (timesheet_id, project_id),
        ):
            g = groups.setdefault(r["phase_id"], {"code": r["phase_code"], "cost": ZERO})
            g["cost"] = money(g["cost"] + money(r["cost_amount"]))
        allocation = sorted(groups.items(), key=lambda kv: (kv[1]["code"].upper(), kv[0]))
        if not lines or len(allocation) != len(lines):
            return {}
        out: dict[int, str] = {}
        for (_, g), ln in zip(allocation, lines):
            if money(ln["debit"]) != g["cost"] or money(ln["credit"]) != ZERO:
                return {}
            out[ln["line_no"]] = _code_or_unmapped(g["code"])
        return out

    # ---- figures ------------------------------------------------------------- #

    def _figures(self, g: dict[str, Any]) -> dict[str, Any]:
        project_id = g["project"]["id"]
        version = g["budget_version"]
        if version is not None:
            budget = money(version["total"])
            approved_lines = {ln["cost_code"]: money(ln["amount"]) for ln in version["lines"]}
            basis = "approved_version"
        else:
            budget = money(g["project"]["budget"])
            approved_lines = None
            basis = "project_budget"

        status = {c["id"]: c["status"] for c in g["commitments"]}
        executed = total(c["executed_amount"] for c in g["commitments"] if c["status"] in ("executed", "closed"))
        pending = total(ch["amount"] for ch in g["pending_changes"])
        forecast = executed + pending
        billed_net = total(b["cumulative_net"] for b in g["billing"])
        billed_gross = total(b["cumulative_gross"] for b in g["billing"])
        retainage_held = total(b["cumulative_retainage"] for b in g["billing"])
        paid_total = total(p["amount"] for p in g["paid"])

        # ---- v2: commitments by cost code
        sov_code = {s["id"]: _code_or_unmapped(s["cost_code"]) for s in g["sov_lines"]}
        installed = {r["sov_line_id"]: money(r["cumulative_installed"]) for r in g["certified"]}
        committed: dict[str, Decimal] = {}
        remaining: dict[str, Decimal] = {}
        certified: dict[str, Decimal] = {}
        for s in g["sov_lines"]:
            code, amount = sov_code[s["id"]], money(s["amount"])
            done = installed.get(s["id"], ZERO)
            if done != ZERO:
                _add(certified, code, done)
            if status.get(s["commitment_id"]) in ("executed", "closed"):
                _add(committed, code, amount)
                if status.get(s["commitment_id"]) == "executed":
                    _add(remaining, code, max(ZERO, amount - done))
        committed_residual = money(executed - total(committed.values()))
        if committed_residual != ZERO:
            _add(committed, UNMAPPED, committed_residual)

        # ---- v2: cost to date by type and code (ledger totals; codes tie to them)
        type_total = {kind: ZERO for kind, _ in COST_TYPES}
        by_type_code: dict[str, dict[str, Decimal]] = {kind: {} for kind, _ in COST_TYPES}
        bill_net: dict[str, Decimal] = {}
        unattributed = ZERO
        for ln in g["cost_lines"]:
            amount = money(money(ln["debit"]) - money(ln["credit"]))
            kind = ln["cost_type"]
            type_total[kind] = money(type_total[kind] + amount)
            if kind == "labor":
                _add(by_type_code["labor"], ln["cost_code"] or UNMAPPED, amount)
            elif kind == "reimbursable":
                _add(by_type_code["reimbursable"], UNMAPPED, amount)
            elif ln.get("bill_id"):
                _add(bill_net, ln["bill_id"], amount)
            else:
                unattributed = money(unattributed + amount)
        # subcontract: each bill's installed value this period goes to its SOV lines' codes;
        # what its journals and credit notes add or remove beyond that follows the same codes
        lines_by_bill: dict[str, list[dict[str, Any]]] = {}
        for bl in g["bill_lines"]:
            lines_by_bill.setdefault(bl["bill_id"], []).append(bl)
        bill_adjustments = ZERO
        for bill_id in sorted(bill_net):
            installed_now: dict[str, Decimal] = {}
            stored_now: dict[str, Decimal] = {}
            for bl in lines_by_bill.get(bill_id, []):
                code = sov_code.get(bl["sov_line_id"], UNMAPPED)
                _add(installed_now, code, money(bl["installed_this_period"]))
                _add(stored_now, code, money(bl["stored_added"]))
            for code, amount in installed_now.items():
                _add(by_type_code["subcontract"], code, amount)
            deviation = money(bill_net[bill_id] - total(installed_now.values()))
            if deviation != ZERO:
                bill_adjustments = money(bill_adjustments + deviation)
                for code, share in _spread(deviation, installed_now, stored_now).items():
                    _add(by_type_code["subcontract"], code, share)
        if unattributed != ZERO:
            _add(by_type_code["subcontract"], UNMAPPED, unattributed)
        cost_total = total(type_total.values())

        pending_by_code: dict[str, Decimal] = {}
        for ch in g["pending_changes"]:
            _add(pending_by_code, sov_code.get(ch["sov_line_id"], UNMAPPED) if ch["sov_line_id"] else UNMAPPED, money(ch["amount"]))

        cost_by_code: dict[str, Decimal] = {}
        for kind, _ in COST_TYPES:
            for code, amount in by_type_code[kind].items():
                _add(cost_by_code, code, amount)
        codes = set(committed) | set(certified) | set(remaining) | set(pending_by_code) | set(cost_by_code) | set(approved_lines or {})
        if approved_lines is None and budget != ZERO:
            codes.add(UNMAPPED)
        ordered = sorted(c for c in codes if c != UNMAPPED) + ([UNMAPPED] if UNMAPPED in codes else [])

        # ---- v2: the budget each code is measured against
        line_budget: dict[str, Decimal] = {}
        source: dict[str, str] = {}
        if approved_lines is not None:
            line_budget = dict(approved_lines)
            source = {code: SOURCE_APPROVED for code in approved_lines}
        elif budget != ZERO:
            # no approved version: the project budget is one pool that every code's forecast
            # draws on (code order); what is left stays unallocated on UNMAPPED
            available = budget if budget > ZERO else ZERO
            for code in ordered:
                if code == UNMAPPED:
                    continue
                need = max(money(cost_by_code.get(code, ZERO) + remaining.get(code, ZERO)), ZERO)
                take = min(need, available)
                if take > ZERO:
                    line_budget[code] = take
                    source[code] = SOURCE_DRAWN
                    available = money(available - take)
            line_budget[UNMAPPED] = available if budget > ZERO else budget
            source[UNMAPPED] = SOURCE_POOL

        by_code: dict[str, dict[str, Any]] = {}
        etc_total = ZERO
        unbudgeted_fac = ZERO
        for code in ordered:
            b = line_budget.get(code, ZERO)
            com = committed.get(code, ZERO)
            rem = remaining.get(code, ZERO)
            costs = {kind: by_type_code[kind].get(code, ZERO) for kind, _ in COST_TYPES}
            cost = total(costs.values())
            pend = pending_by_code.get(code, ZERO)
            if source.get(code) != SOURCE_APPROVED and all(v == ZERO for v in (b, com, rem, cost, pend, certified.get(code, ZERO), *costs.values())):
                continue
            # with no budget left to spend, a negative cost (a credit) is not remaining work
            etc = max(money(b - cost), rem) if b > ZERO else rem
            fac = money(cost + etc + pend)
            etc_total = money(etc_total + etc)
            if code not in source:
                unbudgeted_fac = money(unbudgeted_fac + fac)
            by_code[code] = {
                "budget": fmt(b),
                "budget_source": source.get(code, SOURCE_NONE),
                "committed": fmt(com),
                "uncommitted_budget": fmt(b - com),
                "certified_to_date": fmt(certified.get(code, ZERO)),
                "committed_remaining": fmt(rem),
                "cost_to_date_by_type": {kind: fmt(v) for kind, v in costs.items()},
                "cost_to_date": fmt(cost),
                "etc": fmt(etc),
                "pending_exposure": fmt(pend),
                "fac": fmt(fac),
                "variance_to_budget": fmt(b - fac),
            }
        fac_v2 = money(cost_total + etc_total + pending)

        return {
            # ---- legacy keys (meaning and values unchanged)
            "project_id": project_id,
            "budget": fmt(budget),
            "executed_commitments": fmt(executed),
            "pending_exposure": fmt(pending),
            "forecast_at_completion": fmt(forecast),
            "variance_to_budget": fmt(budget - forecast),
            "over_budget": forecast > budget,
            "billed_gross_to_date": fmt(billed_gross),
            "billed_net_to_date": fmt(billed_net),
            "retainage_held": fmt(retainage_held),
            "paid_to_date": fmt(paid_total),
            "cost_posted_to_date": g["balances"]["5000"],
            "stored_materials_asset": g["balances"]["1300"],
            "prime_certified_to_date": g["prime_certified"],
            "label": LABEL,
            # ---- v2
            "budget_version": version["version"] if version else None,
            "budget_version_hash": version["version_hash"] if version else None,
            "budget_basis": basis,
            "cost_to_date_by_type": {**{kind: fmt(v) for kind, v in type_total.items()}, "total": fmt(cost_total)},
            "committed_remaining": fmt(total(remaining.values())),
            "etc_total": fmt(etc_total),
            "fac_v2": fmt(fac_v2),
            "variance_to_budget_v2": fmt(budget - fac_v2),
            "over_budget_v2": fac_v2 > budget,
            "uncommitted_budget": fmt(budget - executed),
            "unbudgeted_fac": fmt(unbudgeted_fac),
            "residuals": {
                "subcontract_cost_not_on_sov_lines": fmt(unattributed),
                "subcontract_bill_credits_and_reversals": fmt(bill_adjustments),
                "commitments_not_on_sov_lines": fmt(committed_residual),
            },
            "by_cost_code": by_code,
            "inputs_hash": hash_json(g),
        }

    # ---- budget versions ------------------------------------------------------ #

    def _project_row(self, project_id: Any) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM projects WHERE id=?", (project_id,)) if isinstance(project_id, str) else None
        if row is None:
            raise ForecastError(f"unknown project {project_id}")
        return row

    @staticmethod
    def _version_out(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        out = dict(row)
        out["lines"] = loads(out.pop("lines_json"))
        return out

    def _current_version(self, project_id: str) -> dict[str, Any] | None:
        return self._version_out(self.db.one("SELECT * FROM budget_versions WHERE project_id=? ORDER BY version DESC LIMIT 1", (project_id,)))

    def budget_version(self, project_id: str, version: int | None = None) -> dict[str, Any] | None:
        """The current approved budget version (or the given one); None when the project has none."""
        self._project_row(project_id)
        if version is None:
            return self._current_version(project_id)
        return self._version_out(self.db.one("SELECT * FROM budget_versions WHERE project_id=? AND version=?", (project_id, version)))

    def budget_versions(self, project_id: str) -> list[dict[str, Any]]:
        self._project_row(project_id)
        return [self._version_out(r) for r in self.db.query("SELECT * FROM budget_versions WHERE project_id=? ORDER BY version", (project_id,))]

    def set_initial_budget(self, project_id: str, lines: Any, actor: str, *, reason: str = "initial budget") -> dict[str, Any]:
        """Record version 1 of the project's budget by cost code.  Only while the project has
        no budget version; every later change is a budget.revise approval."""
        who = _text(actor, "actor", MAX_ACTOR_LENGTH)
        why = _text(reason, "a budget reason", MAX_REASON_LENGTH)
        canon, budget_total = _canonical_lines(lines)
        with self.db.transaction() as conn:
            project = self._project_row(project_id)
            current = self._current_version(project_id)
            if current is not None:
                raise BudgetAlreadySet(
                    f"project {project_id} already has approved budget version {current['version']}; change it through prepare_budget_revision and a budget.revise approval"
                )
            record = {
                "id": new_id("bud"), "project_id": project_id, "version": 1, "total": fmt(budget_total), "lines_hash": hash_json(canon),
                "reason": why, "approval_id": None, "revision_id": None, "previous_hash": None, "legacy_budget": project["budget"],
                "effective_period_id": None, "created_by": who, "created_at": utcnow_iso(),
            }
            record["version_hash"] = _version_hash(record)
            self._insert_version(conn, record, canon)
            conn.execute("UPDATE projects SET budget=? WHERE id=?", (record["total"], project_id))
            self.audit.record(who, "budget.initial_set", "project", project_id, {
                "budget_version_id": record["id"], "version": 1, "total": record["total"], "lines_hash": record["lines_hash"],
                "line_count": len(canon), "legacy_budget": project["budget"], "version_hash": record["version_hash"], "reason": why,
            })
        return self.budget_version(project_id)

    @staticmethod
    def _insert_version(conn, record: dict[str, Any], canon: list[dict[str, str]]) -> None:
        conn.execute(
            """INSERT INTO budget_versions (id, project_id, version, total, lines_json, lines_hash, reason, approval_id, revision_id,
                   previous_hash, version_hash, legacy_budget, effective_period_id, created_by, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (record["id"], record["project_id"], record["version"], record["total"], canonical_json(canon), record["lines_hash"], record["reason"],
             record["approval_id"], record["revision_id"], record["previous_hash"], record["version_hash"], record["legacy_budget"],
             record["effective_period_id"], record["created_by"], record["created_at"]),
        )

    # ---- revision drafts ---------------------------------------------------------- #

    @staticmethod
    def _revision_out(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        out = dict(row)
        out["lines"] = loads(out.pop("lines_json"))
        return out

    def revision(self, revision_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM budget_revisions WHERE id=?", (revision_id,)) if isinstance(revision_id, str) else None
        if row is None:
            raise ForecastError(f"unknown budget revision {revision_id}")
        return self._revision_out(row)

    def revisions(self, project_id: str) -> list[dict[str, Any]]:
        self._project_row(project_id)
        return [self._revision_out(r) for r in self.db.query("SELECT * FROM budget_revisions WHERE project_id=? ORDER BY prepared_at, rowid", (project_id,))]

    def prepare_budget_revision(self, project_id: str, lines: Any, reason: str, actor: str) -> dict[str, Any]:
        """Draft a replacement of the current budget version.  Nothing changes until a
        budget.revise approval on the draft is granted and executed."""
        who = _text(actor, "actor", MAX_ACTOR_LENGTH)
        why = _text(reason, "a revision reason", MAX_REASON_LENGTH)
        canon, budget_total = _canonical_lines(lines)
        lines_hash = hash_json(canon)
        revision_id = new_id("bdr")
        with self.db.transaction() as conn:
            self._project_row(project_id)
            current = self._current_version(project_id)
            if current is None:
                raise ForecastError(f"project {project_id} has no approved budget version yet; record it with set_initial_budget first")
            if current["lines_hash"] == lines_hash:
                raise ForecastError(f"the revision equals approved budget version {current['version']}; there is nothing to revise")
            dup = conn.execute(
                "SELECT id FROM budget_revisions WHERE project_id=? AND status='pending' AND base_version=? AND lines_hash=?",
                (project_id, current["version"], lines_hash)).fetchone()
            if dup is not None:
                raise ForecastError(f"pending budget revision {dup['id']} already proposes exactly these lines; approve or cancel it")
            conn.execute(
                """INSERT INTO budget_revisions (id, project_id, base_version, base_version_hash, total, lines_json, lines_hash, reason, status, prepared_by, prepared_at)
                   VALUES (?,?,?,?,?,?,?,?,'pending',?,?)""",
                (revision_id, project_id, current["version"], current["version_hash"], fmt(budget_total), canonical_json(canon), lines_hash, why, who, utcnow_iso()),
            )
            self.audit.record(who, "budget.revision_prepared", REVISION_SUBJECT, revision_id, {
                "project_id": project_id, "base_version": current["version"], "base_version_hash": current["version_hash"],
                "total": fmt(budget_total), "current_total": current["total"], "lines_hash": lines_hash, "line_count": len(canon), "reason": why,
            })
        return self.revision(revision_id)

    def cancel_budget_revision(self, revision_id: str, *, actor: str, reason: str) -> dict[str, Any]:
        """Withdraw a pending draft; any approval that bound it goes stale."""
        who = _text(actor, "actor", MAX_ACTOR_LENGTH)
        why = _text(reason, "a cancellation reason", MAX_REASON_LENGTH)
        with self.db.transaction() as conn:
            rev = self.revision(revision_id)
            if rev["status"] != "pending":
                raise ForecastError(f"budget revision {revision_id} is {rev['status']}; only a pending draft can be cancelled")
            conn.execute("UPDATE budget_revisions SET status='cancelled', resolved_by=?, resolved_at=?, resolution_note=? WHERE id=?",
                         (who, utcnow_iso(), why, revision_id))
            invalidated = self.approvals.invalidate_for_subject(REVISION_SUBJECT, revision_id, reason=f"budget revision cancelled: {why}", actor=who)
            self.audit.record(who, "budget.revision_cancelled", REVISION_SUBJECT, revision_id, {
                "project_id": rev["project_id"], "reason": why, "approvals_invalidated": invalidated})
        return self.revision(revision_id)

    # ---- governed operation: budget.revise ----------------------------------------- #

    def handles(self, operation: str) -> bool:
        return operation == OP_REVISE

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation != OP_REVISE:
            raise ForecastError(f"unknown forecast operation {operation}")
        rev = self.revision(subject_id)
        project = self._project_row(rev["project_id"])
        if rev["status"] != "pending":
            raise BudgetRevisionStale(
                f"budget revision {rev['id']} is {rev['status']}; no budget.revise approval applies to it (prepare a new revision)")
        current = self._current_version(rev["project_id"])
        if current is None or current["version"] != rev["base_version"] or current["version_hash"] != rev["base_version_hash"]:
            raise BudgetRevisionStale(
                f"budget revision {rev['id']} was prepared against version {rev['base_version']}, but the current approved version is "
                f"{current['version'] if current else 'missing'}; another revision landed first, so prepare a new revision")
        new_total, current_total = money(rev["total"]), money(current["total"])
        return build_manifest(
            operation=OP_REVISE, subject_type=REVISION_SUBJECT, subject_id=rev["id"], actor_role=actor_role,
            amounts={"new_total": new_total, "current_total": current_total, "change": new_total - current_total},
            bindings={
                "project_id": rev["project_id"],
                "revision_id": rev["id"],
                "revision_status": rev["status"],
                "base_version": rev["base_version"],
                "current_version": current["version"],
                "current_version_hash": current["version_hash"],
                "current_lines_hash": current["lines_hash"],
                "new_version": current["version"] + 1,
                "new_lines": rev["lines"],
                "new_lines_hash": rev["lines_hash"],
                "new_total": rev["total"],
                "reason": rev["reason"],
                "prepared_by": rev["prepared_by"],
                "prepared_at": rev["prepared_at"],
                "period_rule": "optional period_id at execution must be an open period; it is recorded as the effective period",
            },
            entity=project["entity"],
            currency=project["currency"] or "USD",
        )

    def _consumed_manifest(self, approval_id: Any, revision_id: str) -> dict[str, Any]:
        """The manifest of the approval the executing command has just consumed; a direct
        call without it, or with another operation's or subject's approval, is refused."""
        if not isinstance(approval_id, str) or not approval_id.strip():
            raise ForecastError(f"{OP_REVISE} on {revision_id} runs only against its own consumed approval; none was given")
        row = self.db.one("SELECT operation, subject_type, subject_id, status, manifest_json FROM approvals WHERE id=?", (approval_id,))
        if row is None:
            raise ForecastError(f"unknown approval {approval_id}")
        if (row["operation"], row["subject_type"], row["subject_id"]) != (OP_REVISE, REVISION_SUBJECT, revision_id):
            raise ForecastError(f"approval {approval_id} covers {row['operation']} on {row['subject_id']}, not {OP_REVISE} on {revision_id}")
        if row["status"] != "consumed":
            raise ForecastError(f"approval {approval_id} is {row['status']}; it must be consumed by the executing command")
        used = self.db.one("SELECT version FROM budget_versions WHERE approval_id=?", (approval_id,))
        if used is not None:
            raise ForecastError(f"approval {approval_id} already created budget version {used['version']}; an approval takes effect once")
        return loads(row["manifest_json"]) or {}

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation != OP_REVISE:
            raise ForecastError(f"unknown forecast operation {operation}")
        who = _text(actor, "actor", MAX_ACTOR_LENGTH)
        with self.db.transaction() as conn:
            approved = self._consumed_manifest(approval_id, subject_id)
            current_manifest = self.manifest_for(OP_REVISE, subject_id, actor_role=approved.get("actor_role", ""))
            if material_hash(approved) != material_hash(current_manifest) or (manifest and material_hash(manifest) != material_hash(approved)):
                raise ForecastError(f"budget revision {subject_id} or the current budget changed after it was approved; request a new approval")
            effective = None
            if period_id is not None:
                effective = self.ledger.require_open(period_id)["id"]
            rev = self.revision(subject_id)
            current = self._current_version(rev["project_id"])
            record = {
                "id": new_id("bud"), "project_id": rev["project_id"], "version": current["version"] + 1, "total": rev["total"],
                "lines_hash": rev["lines_hash"], "reason": rev["reason"], "approval_id": approval_id, "revision_id": rev["id"],
                "previous_hash": current["version_hash"], "legacy_budget": None, "effective_period_id": effective,
                "created_by": who, "created_at": utcnow_iso(),
            }
            record["version_hash"] = _version_hash(record)
            self._insert_version(conn, record, rev["lines"])
            now = utcnow_iso()
            conn.execute(
                "UPDATE budget_revisions SET status='executed', approval_id=?, resulting_version=?, resolved_by=?, resolved_at=?, resolution_note=? WHERE id=?",
                (approval_id, record["version"], who, now, f"approved budget version {record['version']}", rev["id"]),
            )
            superseded = [r["id"] for r in conn.execute(
                "SELECT id FROM budget_revisions WHERE project_id=? AND status='pending' AND id != ? ORDER BY rowid", (rev["project_id"], rev["id"])).fetchall()]
            for other in superseded:
                conn.execute(
                    "UPDATE budget_revisions SET status='superseded', resolved_by=?, resolved_at=?, resolution_note=? WHERE id=?",
                    (who, now, f"superseded by budget version {record['version']} (revision {rev['id']})", other),
                )
                self.approvals.invalidate_for_subject(REVISION_SUBJECT, other, reason=f"another budget revision landed first (version {record['version']})", actor=who)
            self.approvals.invalidate_for_subject(REVISION_SUBJECT, rev["id"], reason="budget revision already executed", actor=who)
            conn.execute("UPDATE projects SET budget=? WHERE id=?", (record["total"], rev["project_id"]))
            self.audit.record(who, "budget.revised", "project", rev["project_id"], {
                "budget_version_id": record["id"], "version": record["version"], "previous_version": current["version"],
                "total": record["total"], "previous_total": current["total"], "lines_hash": record["lines_hash"], "revision_id": rev["id"],
                "approval_id": approval_id, "version_hash": record["version_hash"], "effective_period_id": effective,
                "superseded_revisions": superseded, "reason": rev["reason"],
            })
        return {
            "project_id": rev["project_id"], "revision_id": rev["id"], "status": "executed", "budget_version": record["version"],
            "previous_version": current["version"], "total": record["total"], "previous_total": current["total"],
            "change": fmt(money(record["total"]) - money(current["total"])), "version_hash": record["version_hash"],
            "effective_period_id": effective, "superseded_revisions": superseded,
        }

    # ---- snapshots ------------------------------------------------------------------ #

    @staticmethod
    def _snapshot_out(row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["figures"] = loads(out.pop("figures_json"))
        out["intact"] = hash_json(out["figures"]) == out["figures_hash"] and out["figures"].get("inputs_hash") == out["inputs_hash"]
        return out

    def snapshot(self, project_id: str, actor: str, label: str) -> dict[str, Any]:
        """Store the project's forecast as an immutable snapshot (every figure plus the hash
        of the inputs it was computed from)."""
        who = _text(actor, "actor", MAX_ACTOR_LENGTH)
        name = _text(label, "a snapshot label", MAX_LABEL_LENGTH)
        snapshot_id = new_id("fcs")
        with self.db.transaction() as conn:
            self._project_row(project_id)
            dup = conn.execute("SELECT id, sequence FROM forecast_snapshots WHERE project_id=? AND label=? COLLATE NOCASE", (project_id, name)).fetchone()
            if dup is not None:
                raise ForecastError(f"project {project_id} already has forecast snapshot {dup['sequence']} labelled {name!r}; labels are unique per project")
            figures = self.project(project_id)
            sequence = (conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM forecast_snapshots WHERE project_id=?", (project_id,)).fetchone()[0]) + 1
            conn.execute(
                """INSERT INTO forecast_snapshots (id, project_id, sequence, label, budget_version, inputs_hash, figures_json, figures_hash, created_by, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (snapshot_id, project_id, sequence, name, figures["budget_version"], figures["inputs_hash"], canonical_json(figures), hash_json(figures), who, utcnow_iso()),
            )
            self.audit.record(who, "forecast.snapshot_taken", "forecast_snapshot", snapshot_id, {
                "project_id": project_id, "sequence": sequence, "label": name, "budget_version": figures["budget_version"],
                "inputs_hash": figures["inputs_hash"], "figures_hash": hash_json(figures), "fac_v2": figures["fac_v2"],
                "forecast_at_completion": figures["forecast_at_completion"],
            })
        return self.snapshot_record(snapshot_id)

    def snapshot_record(self, snapshot_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM forecast_snapshots WHERE id=?", (snapshot_id,)) if isinstance(snapshot_id, str) else None
        if row is None:
            raise ForecastError(f"unknown forecast snapshot {snapshot_id}")
        return self._snapshot_out(row)

    def snapshots(self, project_id: str) -> list[dict[str, Any]]:
        self._project_row(project_id)
        return [self._snapshot_out(r) for r in self.db.query("SELECT * FROM forecast_snapshots WHERE project_id=? ORDER BY sequence", (project_id,))]

    def variance_to_previous(self, project_id: str) -> dict[str, Any]:
        """Compare the project's latest two snapshots: totals, cost by type and each cost code."""
        self._project_row(project_id)
        rows = self.db.query("SELECT * FROM forecast_snapshots WHERE project_id=? ORDER BY sequence DESC LIMIT 2", (project_id,))
        if len(rows) < 2:
            raise ForecastError(f"project {project_id} has {len(rows)} forecast snapshot(s); variance_to_previous needs at least two")
        latest, previous = (self._snapshot_out(r) for r in rows)
        lf, pf = latest["figures"], previous["figures"]
        total_keys = ("budget", "executed_commitments", "pending_exposure", "forecast_at_completion", "variance_to_budget", "cost_posted_to_date",
                      "committed_remaining", "etc_total", "fac_v2", "variance_to_budget_v2", "uncommitted_budget", "unbudgeted_fac")
        code_keys = ("budget", "committed", "uncommitted_budget", "certified_to_date", "committed_remaining", "cost_to_date", "etc",
                     "pending_exposure", "fac", "variance_to_budget")
        lc, pc = lf.get("by_cost_code") or {}, pf.get("by_cost_code") or {}
        codes = sorted(c for c in set(lc) | set(pc) if c != UNMAPPED) + ([UNMAPPED] if UNMAPPED in lc or UNMAPPED in pc else [])

        def meta(s: dict[str, Any]) -> dict[str, Any]:
            return {k: s[k] for k in ("id", "sequence", "label", "budget_version", "inputs_hash", "created_by", "created_at", "intact")}

        return {
            "project_id": project_id,
            "previous": meta(previous),
            "latest": meta(latest),
            "inputs_changed": previous["inputs_hash"] != latest["inputs_hash"],
            "budget_version": {"previous": pf.get("budget_version"), "latest": lf.get("budget_version")},
            "totals": {k: _delta(pf.get(k), lf.get(k)) for k in total_keys},
            "cost_to_date_by_type": {k: _delta((pf.get("cost_to_date_by_type") or {}).get(k), (lf.get("cost_to_date_by_type") or {}).get(k))
                                     for k in ("subcontract", "labor", "reimbursable", "total")},
            "by_cost_code": {code: {k: _delta((pc.get(code) or {}).get(k), (lc.get(code) or {}).get(k)) for k in code_keys} for code in codes},
        }

    # ---- verification and export --------------------------------------------------- #

    def _audited(self, action: str, entity_type: str, entity_id: str, payload: dict[str, Any] | None = None) -> bool:
        """Whether the audit log holds ``action`` on the entity (with these payload values)."""
        for row in self.db.query("SELECT payload_json FROM audit_log WHERE action=? AND entity_type=? AND entity_id=? ORDER BY seq",
                                 (action, entity_type, entity_id)):
            if payload is None:
                return True
            recorded = loads(row["payload_json"]) or {}
            if all(recorded.get(k) == v for k, v in payload.items()):
                return True
        return False

    def _trail_problems(self, v: dict[str, Any]) -> list[str]:
        """How a budget version came to be: version 1 by its audited initial set; every later
        one by a budget.revise approval the core granted and consumed, whose manifest bound
        exactly this version, executing its revision, with the audit entries to show it."""
        vid = v["id"]
        recorded = {"budget_version_id": vid, "version_hash": v["version_hash"]}
        if v["version"] == 1:
            return [] if self._audited("budget.initial_set", "project", v["project_id"], recorded) else [
                f"budget version {vid}: no budget.initial_set audit entry records it"]
        problems: list[str] = []
        ap = self.db.one("SELECT * FROM approvals WHERE id=?", (v["approval_id"],)) if v["approval_id"] else None
        if (ap is None or ap["status"] != "consumed" or (ap["operation"], ap["subject_type"], ap["subject_id"]) != (OP_REVISE, REVISION_SUBJECT, v["revision_id"])
                or not ap.get("approver") or not ap.get("granted_at") or not ap.get("consumed_by")):
            problems.append(f"budget version {vid}: approval {v['approval_id']} is not a granted and consumed {OP_REVISE} approval of revision {v['revision_id']}")
        else:
            bound = (loads(ap["manifest_json"]) or {}).get("bindings") or {}
            expected = {"project_id": v["project_id"], "revision_id": v["revision_id"], "new_version": v["version"], "new_lines_hash": v["lines_hash"],
                        "new_total": v["total"], "reason": v["reason"], "current_version_hash": v["previous_hash"]}
            differ = sorted(k for k, val in expected.items() if bound.get(k) != val)
            if differ:
                problems.append(f"budget version {vid}: its approval's manifest bound a different version ({', '.join(differ)})")
            for action in ("approval.granted", "approval.consumed"):
                if not self._audited(action, "approval", ap["id"]):
                    problems.append(f"budget version {vid}: approval {ap['id']} has no {action} audit entry")
        rev = self.db.one("SELECT status, approval_id, resulting_version FROM budget_revisions WHERE id=?", (v["revision_id"],)) if v["revision_id"] else None
        if rev is None or (rev["status"], rev["approval_id"], rev["resulting_version"]) != ("executed", v["approval_id"], v["version"]):
            problems.append(f"budget version {vid}: revision {v['revision_id']} is not recorded as executed into it")
        if not self._audited("budget.revised", "project", v["project_id"], {**recorded, "approval_id": v["approval_id"]}):
            problems.append(f"budget version {vid}: no budget.revised audit entry records it")
        return problems

    def verify(self) -> dict[str, Any]:
        """Re-derive every budget version's lines hash, total and chained hash, how it was
        created (audited initial set, or its granted and consumed budget.revise approval),
        that each versioned project's legacy budget column equals its current version total,
        and every snapshot's figures hash."""
        problems: list[str] = []
        versions = self.db.query("SELECT * FROM budget_versions ORDER BY project_id, version")
        previous: dict[str, str | None] = {}
        current: dict[str, dict[str, Any]] = {}
        for row in versions:
            v = self._version_out(row)
            pid = v["project_id"]
            if hash_json(v["lines"]) != v["lines_hash"]:
                problems.append(f"budget version {v['id']}: lines do not match their hash")
            try:
                if fmt(total(ln["amount"] for ln in v["lines"])) != v["total"]:
                    problems.append(f"budget version {v['id']}: lines do not add up to the total")
            except (MoneyError, KeyError, TypeError):
                problems.append(f"budget version {v['id']}: lines are not exact money")
            if v["previous_hash"] != previous.get(pid):
                problems.append(f"budget version {v['id']}: does not chain to the previous version")
            if v["version"] != (current[pid]["version"] + 1 if pid in current else 1):
                problems.append(f"budget version {v['id']}: versions of project {pid} are not numbered consecutively")
            if _version_hash(v) != v["version_hash"]:
                problems.append(f"budget version {v['id']}: version hash does not match its record")
            problems.extend(self._trail_problems(v))
            previous[pid] = v["version_hash"]
            current[pid] = v
        for pid, v in sorted(current.items()):
            column = self.db.one("SELECT budget FROM projects WHERE id=?", (pid,))
            if column is None or column["budget"] != v["total"]:
                problems.append(f"project {pid}: budget column {None if column is None else column['budget']!r} is not the current approved "
                                f"budget version {v['version']} total {v['total']}")
        for r in self.db.query(
            """SELECT r.id FROM budget_revisions r WHERE r.status = 'executed' AND NOT EXISTS (
                   SELECT 1 FROM budget_versions v WHERE v.revision_id = r.id AND v.approval_id IS r.approval_id AND v.version IS r.resulting_version)
               ORDER BY r.id"""):
            problems.append(f"budget revision {r['id']}: executed, but no budget version carries it")
        snapshots = self.db.query("SELECT * FROM forecast_snapshots ORDER BY project_id, sequence")
        for row in snapshots:
            if not self._snapshot_out(row)["intact"]:
                problems.append(f"forecast snapshot {row['id']}: figures do not match their hash")
        return {"ok": not problems, "problems": problems, "budget_versions": len(versions), "snapshots": len(snapshots)}

    def audit_export(self) -> dict[str, Any]:
        return {
            "budget_versions": [self._version_out(r) for r in self.db.query("SELECT * FROM budget_versions ORDER BY project_id, version")],
            "budget_revisions": [self._revision_out(r) for r in self.db.query("SELECT * FROM budget_revisions ORDER BY project_id, prepared_at, rowid")],
            "forecast_snapshots": [self._snapshot_out(r) for r in self.db.query("SELECT * FROM forecast_snapshots ORDER BY project_id, sequence")],
            "verification": self.verify(),
            "label": LABEL,
        }
