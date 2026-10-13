"""Period close, financial statements, aging and WIP (v2 plugin, operation prefix ``close``).

Everything here is SHADOW finance for the synthetic prototype: the statements,
aging and WIP schedules are derived from Cipher's own journals and subledgers
and are labeled "SHADOW - not authoritative".

Period close
    ``checklist(period_id)`` gathers the conditions that must hold before a
    period closes: the period's trial balance balances; the AP and AR
    subledgers reconcile to their control accounts; no draft (unposted)
    supplier or prime bills sit in the period; no payment intent is
    ``submitted`` or ``outcome_unknown``; the employee payable reconciles for
    every project and company-wide when the reimbursement plugin is registered;
    no prepared WIP adjustment is left in draft in the period; the WIP register
    reconciles to 1160 / 2300 as of the period; every earlier period (start
    date on or before this one's) is already closed or locked; plus every
    check returned by any other registered plugin's optional
    ``close_checks(period_id)`` hook (a hook that raises or returns a malformed
    result yields a failing check naming the plugin).  The AR check uses the
    core receivables subledger, which aggregates every plugin AR source (labor
    T&M invoices among them).  The core subledger checks for retainage payable
    (2050), stored materials (1300), retainage receivable (1150) and provider
    clearing (1200) arrive once, through the ``core_reconciliation``
    pseudo-plugin's hook; this module does not compute them again, and an
    identical check reported twice is listed once.  Bank reconciliation
    arrives through the banking plugin's hook; without a banking plugin an
    informational, passing check says so.

    Periods close in order, so a closed or locked period's cumulative balance
    sheet cannot drift: closing needs every earlier period closed (a checklist
    item), locking needs every earlier period locked, and reopening needs every
    later period open.

    ``close.close_period`` binds the checklist hash, the period's trial-balance
    totals, the statements hash, the period status and the earlier periods'
    statuses; execution re-runs the checklist inside the command, refuses unless
    every check passes, closes the period through ``Ledger.close_period`` and
    stores an append-only close run with the checklist and statements snapshot.
    ``close.reopen_period`` (closed -> open, never from locked) needs a
    controller (or the owner, who holds every role in the solo prototype), on
    both sides: the request's acting role and the role the approval is granted
    under.  The core role table also lets an accountant approve a reopen, and
    the core approval row does not keep the approver's role, so this module
    guards ``Cipher.approve`` for reopen approvals: an accountant's grant is
    refused; an owner or controller grant is recorded (``close_reopen_grants``:
    approver, role, and whether the role was declared or is the core's default
    approver role) while the approval is still pending, in the transaction in
    which the core grants it.  The database backs it
    (``close_reopen_governance``): one of this module's reopen approvals moves
    pending -> granted only with a grant row for its approver, a grant row is
    never attached to an approval already granted, and a period reopens
    against one of this module's approvals (from ``Ledger.reopen_period`` or a
    raw UPDATE alike) only with that grant, only after its execution recorded
    the reopen run, and only while every later period is open.  No reopen at
    all, whatever ``*.reopen_period`` approval the core accepts, runs while a
    later period is locked.  It is the governed reopen: ``Ledger.reopen_period`` (backed by a period
    trigger) accepts a reopen only against a consumed ``*.reopen_period``
    approval for that period, and execution hands it exactly the approval that
    ``Cipher.execute`` consumed in the same transaction.  Limits: roles are
    self-declared in the prototype (no identity directory), so a grant row is
    the approver's claim, not a verified identity; and the core still accepts
    a consumed approval of any other ``*.reopen_period`` operation (or of
    ``close.reopen_period`` with another subject type) fabricated through
    ``Approvals.request``; this module cannot refuse those without refusing the
    core's own reopen path, so they are held only to the locked-later-period
    rule.  Every ``apply`` path
    refuses to run against anything but its own consumed approval, once; the
    database backs it (``close_approval_guards``): a close run needs a consumed
    approval of its action for its period and one approval yields one run, and
    a WIP adjustment is posted or reversed only against its consumed approval.
    ``close.lock_period`` (closed -> locked) only locks a period whose current
    closed state came from a passing checklist close (the audit trail shows no
    later direct close) and whose figures still equal that close's snapshot.
    Both go through ``Ledger.reopen_period`` / ``Ledger.lock_period`` and are
    recorded as close runs too.  Manifests bind state rather than refuse on it,
    so a state change between grant and execution invalidates the approval
    instead of leaving it dangling; execution then validates state.

Statements and aging
    ``statements(period_id)``: income statement for journals in the period,
    balance sheet cumulative through the period (every period whose start date
    is on or before this one's), cash movements on 1000 grouped by journal
    source type.  ``aging(as_of)``: the AP and AR items open now (AR includes
    every source the core receivables subledger aggregates), bucketed by days
    past due at ``as_of``: ``current`` (not yet due, or due that day), 1-30,
    31-60, 61-90 and over 90 days past due.  An item that carries a
    ``due_date`` (prime bills and retainage invoices from the receivables
    subledger, supplier bills once the bills subledger dates them) is aged from
    it; an item without one falls back to its document date (the item's
    ``invoice_date`` when it has one, else the record's created date, looked up
    in the source record's own table: prime bills, retainage invoices, labor
    invoices, reimbursement billings), as if due that day.  Each aged item says
    which ``basis`` it used.  An item whose document date is after ``as_of`` is
    reported apart (``after_as_of``) and an item nothing dates is reported apart
    (``undated``), never as current, and buckets + after_as_of + undated equal
    the subledger totals.  Open balances are not reconstructed as of a past
    date; a historical ``as_of`` carries a warning saying so.

WIP (fixture policy, cost-to-cost percent complete)
    percent complete = cost to date (5000 + 5100 + 5300, cumulative, project)
    / estimated total cost (the forecast's ``fac_v2``: cost to date + estimate
    to complete + pending exposure over the same three cost types; basis
    ``fac_v2``), capped at 1, four decimal places half-up.  A project with no
    estimate (``fac_v2`` zero, or no budget and nothing beyond cost to date)
    has no WIP: computing it, and so preparing or posting an adjustment, is
    refused.  The WIP approval shows the percent complete, cost to date,
    estimate and basis.  Earned
    revenue = money(percent x contract value).  Billed to date = cumulative
    credit balance of 4000 + 4100 for the project, excluding WIP adjustment
    journals.  over/under = billed - earned (negative = underbilled).

Posting rules (fixture policy ``cipher-posting-rules/1``):

* ``close.post_wip_adjustment``     underbilled: Dr 1160 contract asset / Cr 4000 contract revenue
                                    overbilled:  Dr 4000 contract revenue / Cr 2300 contract liability
                                    (journal source type ``wip_adjustment``)
* ``close.reverse_wip_adjustment``  the adjustment journal reversed through ``Ledger.reverse``
                                    into the first open period after the adjustment's
                                    period (bound by the approval)

One live adjustment per project per period, judged from the period's cumulative
books: an adjustment is on the books from its period up to (not including) the
period it is reversed into, and those spans never overlap for a project.  A new
adjustment in period T stays live from T onwards, so every earlier adjustment
must already be reversed into T or an earlier period, and the register must
reconcile to 1160 / 2300 in every period first.  ``wip_reconciliation``
compares, period by period, the adjustments live in the period with the
cumulative 1160 / 2300 balances through it.
"""
from __future__ import annotations

import datetime as _dt
import inspect
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..core.approvals import build_manifest
from ..core.db import register_schema_version
from ..core.ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow, utcnow_iso
from ..core.money import ZERO, D, MoneyError, fmt, money, total
from .ledger import DEBIT_NORMAL
from .ricky import Ricky

SCHEMA_NAME = "close"
PLUGIN_NAME = "close"
POSTING_RULE = "cipher-posting-rules/1"
WIP_POLICY = "fixture: cost-to-cost percent complete, billed vs earned (SHADOW)"
SHADOW = "SHADOW - not authoritative"

OP_CLOSE = "close.close_period"
OP_REOPEN = "close.reopen_period"
OP_LOCK = "close.lock_period"
OP_POST_WIP = "close.post_wip_adjustment"
OP_REVERSE_WIP = "close.reverse_wip_adjustment"
OPERATIONS = (OP_CLOSE, OP_REOPEN, OP_LOCK, OP_POST_WIP, OP_REVERSE_WIP)

# Roles that may request close operations (Ricky gates its own proposals separately).
CLOSE_ROLES = ("owner", "controller", "accountant")
# Reopening needs a scoped controller approval (plan section 6, item 4); the owner
# holds every role in the solo-first prototype.
REOPEN_ROLES = ("owner", "controller")

PERIOD_SUBJECT = "accounting_period"
WIP_SUBJECT = "wip_adjustment"
WIP_SOURCE_TYPE = "wip_adjustment"

CASH_ACCOUNT = "1000"
REVENUE_ACCOUNT = "4000"
UNDERBILLINGS_ACCOUNT = "1160"
OVERBILLINGS_ACCOUNT = "2300"
COST_ACCOUNTS = ("5000", "5100", "5300")
BILLING_ACCOUNTS = ("4000", "4100")
PERCENT_PLACES = Decimal("0.0001")
ONE = Decimal("1")

AGING_BUCKETS = ("current", "1_30", "31_60", "61_90", "over_90")
AFTER_AS_OF = "after_as_of"  # dated after as_of: not aged, reported apart
UNDATED = "undated"  # no record dates the item: not aged, reported apart (never as current)
BASIS_DUE_DATE = "due_date"  # aged from the item's own due date
BASIS_DOCUMENT_DATE = "document_date"  # no due date: aged from its invoice or created date, as if due that day
# Where an AR item's created date lives, by the record id the item carries (the labor
# ``invoice_id`` only for ``labor_invoice`` items).  Prime bills are looked up directly.
AR_RECORD_TABLES = (
    ("retainage_invoice_id", "prime_retainage_invoices"),
    ("billing_id", "reimbursement_billings"),
    ("invoice_id", "labor_invoices"),
)
UNPOSTED_BILL_STATES = ("draft", "approved")
UNRESOLVED_PAYMENT_STATES = ("submitted", "outcome_unknown")

SCHEMA_STATEMENTS = [
    "INSERT OR IGNORE INTO accounts (code, name, type, control_kind) VALUES ('1160', 'Contract asset - underbillings', 'asset', 'contract_asset')",
    "INSERT OR IGNORE INTO accounts (code, name, type, control_kind) VALUES ('2300', 'Contract liability - overbillings', 'liability', 'contract_liability')",
    """CREATE TABLE close_contract_values (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        version INTEGER NOT NULL CHECK (version >= 1),
        contract_value TEXT NOT NULL,
        previous_value TEXT,
        set_by TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        UNIQUE (project_id, version)
    )""",
    "CREATE TRIGGER close_contract_values_no_update BEFORE UPDATE ON close_contract_values BEGIN SELECT RAISE(ABORT, 'contract values are versioned; set a new version instead'); END",
    "CREATE TRIGGER close_contract_values_no_delete BEFORE DELETE ON close_contract_values BEGIN SELECT RAISE(ABORT, 'contract value history is append-only'); END",
    """CREATE TABLE close_runs (
        id TEXT PRIMARY KEY,
        period_id TEXT NOT NULL REFERENCES periods(id),
        action TEXT NOT NULL CHECK (action IN ('close','reopen','lock')),
        status_before TEXT NOT NULL,
        status_after TEXT NOT NULL,
        approval_id TEXT NOT NULL REFERENCES approvals(id),
        actor TEXT NOT NULL,
        checklist_json TEXT,
        checklist_hash TEXT,
        statements_json TEXT,
        statements_hash TEXT,
        total_debit TEXT NOT NULL,
        total_credit TEXT NOT NULL,
        journal_count INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )""",
    "CREATE TRIGGER close_runs_no_update BEFORE UPDATE ON close_runs BEGIN SELECT RAISE(ABORT, 'close runs are append-only'); END",
    "CREATE TRIGGER close_runs_no_delete BEFORE DELETE ON close_runs BEGIN SELECT RAISE(ABORT, 'close runs are append-only'); END",
    """CREATE TABLE close_wip (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        status TEXT NOT NULL CHECK (status IN ('draft','posted','reversed','superseded','cancelled')),
        version INTEGER NOT NULL DEFAULT 1,
        direction TEXT NOT NULL CHECK (direction IN ('underbilled','overbilled')),
        amount TEXT NOT NULL CHECK (amount != '0.00' AND substr(amount, 1, 1) != '-'),
        debit_account TEXT NOT NULL REFERENCES accounts(code),
        credit_account TEXT NOT NULL REFERENCES accounts(code),
        contract_value TEXT NOT NULL,
        contract_version INTEGER NOT NULL,
        estimated_total_cost TEXT NOT NULL,
        cost_to_date TEXT NOT NULL,
        percent_complete TEXT NOT NULL,
        earned_revenue TEXT NOT NULL,
        billed_to_date TEXT NOT NULL,
        over_under TEXT NOT NULL,
        inputs_json TEXT NOT NULL,
        inputs_hash TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        prepared_by TEXT NOT NULL,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        reversal_approval_id TEXT REFERENCES approvals(id),
        reversal_journal_id TEXT REFERENCES journals(id),
        reversal_period_id TEXT REFERENCES periods(id),
        created_at TEXT NOT NULL,
        posted_at TEXT,
        reversed_at TEXT,
        withdrawn_at TEXT
    )""",
    # one draft-or-posted adjustment per project per period
    "CREATE UNIQUE INDEX close_wip_one_live ON close_wip (project_id, period_id) WHERE status IN ('draft','posted')",
    "CREATE TRIGGER close_wip_no_delete BEFORE DELETE ON close_wip BEGIN SELECT RAISE(ABORT, 'WIP adjustments are never deleted'); END",
    """CREATE TRIGGER close_wip_figures_immutable BEFORE UPDATE ON close_wip
        WHEN NEW.project_id IS NOT OLD.project_id OR NEW.period_id IS NOT OLD.period_id OR NEW.direction IS NOT OLD.direction
          OR NEW.amount IS NOT OLD.amount OR NEW.debit_account IS NOT OLD.debit_account OR NEW.credit_account IS NOT OLD.credit_account
          OR NEW.contract_value IS NOT OLD.contract_value OR NEW.contract_version IS NOT OLD.contract_version
          OR NEW.estimated_total_cost IS NOT OLD.estimated_total_cost OR NEW.cost_to_date IS NOT OLD.cost_to_date
          OR NEW.percent_complete IS NOT OLD.percent_complete OR NEW.earned_revenue IS NOT OLD.earned_revenue
          OR NEW.billed_to_date IS NOT OLD.billed_to_date OR NEW.over_under IS NOT OLD.over_under
          OR NEW.inputs_json IS NOT OLD.inputs_json OR NEW.inputs_hash IS NOT OLD.inputs_hash
        BEGIN SELECT RAISE(ABORT, 'WIP adjustment figures are immutable; prepare a new adjustment'); END""",
    """CREATE TRIGGER close_wip_status_forward_only BEFORE UPDATE OF status ON close_wip
        WHEN NEW.status != OLD.status AND NOT (
            (OLD.status = 'draft' AND NEW.status IN ('posted','superseded','cancelled'))
            OR (OLD.status = 'posted' AND NEW.status = 'reversed')
        )
        BEGIN SELECT RAISE(ABORT, 'illegal WIP adjustment status transition'); END""",
    """CREATE TRIGGER close_wip_posted_journal_fixed BEFORE UPDATE ON close_wip
        WHEN OLD.status = 'posted' AND (NEW.journal_id IS NOT OLD.journal_id OR NEW.approval_id IS NOT OLD.approval_id)
        BEGIN SELECT RAISE(ABORT, 'a posted WIP adjustment is corrected by reversal only'); END""",
    """CREATE TRIGGER close_wip_final_immutable BEFORE UPDATE ON close_wip
        WHEN OLD.status IN ('reversed','superseded','cancelled')
        BEGIN SELECT RAISE(ABORT, 'reversed, superseded and cancelled WIP adjustments are immutable'); END""",
]

# Approval guards, as their own catalog entry so a workspace that already applied
# ``close`` upgrades in place (applied entries are append-only): a close run is recorded
# only against a consumed close approval of the same action for that period, and one
# approval yields at most one run; a WIP adjustment is posted or reversed only against a
# consumed approval of that operation for that adjustment.
GUARDS_SCHEMA_NAME = "close_approval_guards"
GUARDS_SCHEMA_STATEMENTS = [
    "CREATE UNIQUE INDEX close_runs_one_per_approval ON close_runs (approval_id)",
    """CREATE TRIGGER close_runs_need_consumed_approval BEFORE INSERT ON close_runs
        WHEN (SELECT status FROM approvals WHERE id = NEW.approval_id AND subject_type = 'accounting_period' AND subject_id = NEW.period_id
              AND operation = (CASE NEW.action WHEN 'close' THEN 'close.close_period' WHEN 'reopen' THEN 'close.reopen_period' ELSE 'close.lock_period' END)) IS NOT 'consumed'
        BEGIN SELECT RAISE(ABORT, 'a close run is recorded only against a consumed close approval of the same action for that period'); END""",
    """CREATE TRIGGER close_wip_posting_needs_consumed_approval BEFORE UPDATE OF status ON close_wip
        WHEN NEW.status = 'posted' AND OLD.status != 'posted'
         AND (SELECT status FROM approvals WHERE id = NEW.approval_id AND operation = 'close.post_wip_adjustment'
              AND subject_type = 'wip_adjustment' AND subject_id = NEW.id) IS NOT 'consumed'
        BEGIN SELECT RAISE(ABORT, 'a WIP adjustment is posted only against a consumed close.post_wip_adjustment approval for it'); END""",
    """CREATE TRIGGER close_wip_reversal_needs_consumed_approval BEFORE UPDATE OF status ON close_wip
        WHEN NEW.status = 'reversed' AND OLD.status != 'reversed'
         AND (SELECT status FROM approvals WHERE id = NEW.reversal_approval_id AND operation = 'close.reverse_wip_adjustment'
              AND subject_type = 'wip_adjustment' AND subject_id = NEW.id) IS NOT 'consumed'
        BEGIN SELECT RAISE(ABORT, 'a WIP adjustment is reversed only against a consumed close.reverse_wip_adjustment approval for it'); END""",
]

# Reopen authority, as its own catalog entry (applied entries are append-only).  The core
# approval row records the approver's name, not the role they approved under, and the
# core role table lets more roles approve ``close.reopen_period`` than plan section 6,
# item 4 allows ("reopening requires a scoped controller approval").  The close module
# therefore records, when ``Cipher.approve`` grants a reopen approval, who granted it and
# under which role; only an owner or controller grant is admitted (CHECK), it is written
# once for a reopen approval of that period, and a reopen run is recorded only against an
# approval that carries such a grant.  (This entry first admitted the row after the core
# grant; ``close_reopen_governance`` below replaces that insert trigger so the row is
# written while the approval is pending, and adds the approval and period guards.)
REOPEN_GRANTS_SCHEMA_NAME = "close_reopen_grant_roles"
REOPEN_GRANTS_SCHEMA_STATEMENTS = [
    """CREATE TABLE close_reopen_grants (
        approval_id TEXT PRIMARY KEY REFERENCES approvals(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        approver TEXT NOT NULL,
        approver_role TEXT NOT NULL CHECK (approver_role IN ('owner','controller')),
        granted_at TEXT NOT NULL
    )""",
    """CREATE TRIGGER close_reopen_grants_granted_reopen_only BEFORE INSERT ON close_reopen_grants
        WHEN (SELECT status FROM approvals WHERE id = NEW.approval_id AND operation = 'close.reopen_period'
              AND subject_type = 'accounting_period' AND subject_id = NEW.period_id) IS NOT 'granted'
        BEGIN SELECT RAISE(ABORT, 'a reopen grant is recorded only for a granted close.reopen_period approval of that period'); END""",
    "CREATE TRIGGER close_reopen_grants_no_update BEFORE UPDATE ON close_reopen_grants BEGIN SELECT RAISE(ABORT, 'reopen grants are append-only'); END",
    "CREATE TRIGGER close_reopen_grants_no_delete BEFORE DELETE ON close_reopen_grants BEGIN SELECT RAISE(ABORT, 'reopen grants are append-only'); END",
    """CREATE TRIGGER close_runs_reopen_needs_controller_grant BEFORE INSERT ON close_runs
        WHEN NEW.action = 'reopen'
         AND NOT EXISTS (SELECT 1 FROM close_reopen_grants g WHERE g.approval_id = NEW.approval_id AND g.period_id = NEW.period_id)
        BEGIN SELECT RAISE(ABORT, 'a reopen run needs the owner or controller grant recorded for its approval'); END""",
]

# Reopen governance in the database, as its own catalog entry (the entries above are
# applied history and stay as they are).  The guards above held only on the close.apply
# path: an approval granted around ``Cipher.approve`` and consumed directly could still
# reopen through ``Ledger.reopen_period`` or a raw UPDATE, under a closed later period
# too, and a grant row could be attached to an approval someone else had already
# granted.  From this entry on:
#
# * the role claim is made at grant time: a grant row is written only while its
#   ``close.reopen_period`` approval is still pending (``Cipher.approve`` writes it and
#   lets the core grant in the same transaction), it records whether the role was
#   declared by the caller or is the core's default approver role (``role_basis``), and
#   the approval moves pending -> granted only when a grant row for its approver exists;
# * a period reopens against one of the close module's approvals (operation
#   ``close.reopen_period``, subject type ``accounting_period``) only with that grant, only
#   after the reopen run of its execution was recorded, and only while every later
#   period is open;
# * no reopen at all, whatever approval the core accepts, runs while a later period is
#   locked: a locked balance sheet includes every earlier period.
#
# Each period trigger fires only when the core's own reopen trigger
# (``periods_reopen_requires_approval``) would accept the transition, so the refusal
# reason never depends on trigger firing order.
_CORE_ACCEPTED_REOPEN = """EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.reopen_approval_id AND a.status = 'consumed' AND a.subject_id = NEW.id
                   AND length(a.operation) > 14 AND substr(a.operation, -14) = '.reopen_period')
         AND NOT EXISTS (SELECT 1 FROM period_reopens r WHERE r.approval_id = NEW.reopen_approval_id)"""
_LATER_LOCKED = """EXISTS (SELECT 1 FROM periods l WHERE l.id <> NEW.id AND l.start_date >= min(OLD.start_date, NEW.start_date) AND l.status = 'locked')"""
REOPEN_GOVERNANCE_SCHEMA_NAME = "close_reopen_governance"
REOPEN_GOVERNANCE_SCHEMA_STATEMENTS = [
    "ALTER TABLE close_reopen_grants ADD COLUMN role_basis TEXT CHECK (role_basis IS NULL OR role_basis IN ('declared','core_default'))",
    "DROP TRIGGER close_reopen_grants_granted_reopen_only",
    """CREATE TRIGGER close_reopen_grants_recorded_at_grant BEFORE INSERT ON close_reopen_grants
        WHEN NEW.role_basis IS NULL
          OR (SELECT status FROM approvals WHERE id = NEW.approval_id AND operation = 'close.reopen_period'
              AND subject_type = 'accounting_period' AND subject_id = NEW.period_id) IS NOT 'pending'
        BEGIN SELECT RAISE(ABORT, 'a reopen grant is recorded only by Cipher.approve, while it grants a pending close.reopen_period approval of that period'); END""",
    """CREATE TRIGGER close_reopen_approval_granted_with_grant BEFORE UPDATE OF status ON approvals
        WHEN NEW.status = 'granted' AND OLD.status IS NOT 'granted'
         AND NEW.operation = 'close.reopen_period' AND NEW.subject_type = 'accounting_period'
         AND NOT EXISTS (SELECT 1 FROM close_reopen_grants g WHERE g.approval_id = NEW.id AND g.period_id = NEW.subject_id AND g.approver IS NEW.approver)
        BEGIN SELECT RAISE(ABORT, 'a close.reopen_period approval is granted only through Cipher.approve by an owner or controller, which records the grant for that approver'); END""",
    f"""CREATE TRIGGER close_periods_no_reopen_under_a_locked_period BEFORE UPDATE ON periods
        WHEN OLD.status = 'closed' AND NEW.status = 'open'
         AND {_CORE_ACCEPTED_REOPEN}
         AND {_LATER_LOCKED}
        BEGIN SELECT RAISE(ABORT, 'a period cannot be reopened while a later period is locked: the locked balance sheet includes it'); END""",
    f"""CREATE TRIGGER close_periods_reopen_through_close_only BEFORE UPDATE ON periods
        WHEN OLD.status = 'closed' AND NEW.status = 'open'
         AND {_CORE_ACCEPTED_REOPEN}
         AND EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.reopen_approval_id AND a.operation = 'close.reopen_period' AND a.subject_type = 'accounting_period')
         AND NOT {_LATER_LOCKED}
        BEGIN
            SELECT CASE
                WHEN NOT EXISTS (SELECT 1 FROM close_reopen_grants g WHERE g.approval_id = NEW.reopen_approval_id AND g.period_id = NEW.id)
                THEN RAISE(ABORT, 'a close.reopen_period approval reopens a period only with the owner or controller grant recorded by Cipher.approve')
                WHEN NOT EXISTS (SELECT 1 FROM close_runs r WHERE r.approval_id = NEW.reopen_approval_id AND r.period_id = NEW.id AND r.action = 'reopen')
                THEN RAISE(ABORT, 'a close.reopen_period approval reopens a period only through its execution (Cipher.execute), which records the reopen run first')
                WHEN EXISTS (SELECT 1 FROM periods l WHERE l.id <> NEW.id AND l.start_date >= min(OLD.start_date, NEW.start_date) AND l.status <> 'open')
                THEN RAISE(ABORT, 'a period reopens only while every later period is open: their cumulative balance sheets include it')
            END;
        END""",
]

# Registered here, in this order, so the follow-on entries always sit after the objects
# they guard; the plugin loader's own registration of SCHEMA_NAME is then a no-op.
register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)
register_schema_version(GUARDS_SCHEMA_NAME, GUARDS_SCHEMA_STATEMENTS)
register_schema_version(REOPEN_GRANTS_SCHEMA_NAME, REOPEN_GRANTS_SCHEMA_STATEMENTS)
register_schema_version(REOPEN_GOVERNANCE_SCHEMA_NAME, REOPEN_GOVERNANCE_SCHEMA_STATEMENTS)


class CloseError(RuntimeError):
    """Invalid close/statement/WIP input or an operation the current state does not allow."""


class ReopenAuthorityError(CloseError, PermissionError):
    """A role that the core lets approve ``close.reopen_period`` but that is not a
    controller (or the owner) tried to grant a reopen."""


# --------------------------------------------------------------------------- #
# Pure helpers                                                                 #
# --------------------------------------------------------------------------- #

def _parse_date(text, label: str = "date") -> _dt.date:
    if not isinstance(text, str) or len(text) != 10 or text[4] != "-" or text[7] != "-":
        raise CloseError(f"{label} must be YYYY-MM-DD, got {text!r}")
    try:
        return _dt.date.fromisoformat(text)
    except ValueError as exc:
        raise CloseError(f"{label} is not a valid calendar date: {text!r}") from exc


def _non_empty(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CloseError(f"{label} is required and must be a non-empty string")
    return value.strip()


def _natural(acct_type: str, debit: Decimal, credit: Decimal) -> Decimal:
    """Debit-positive for assets and expenses, credit-positive otherwise."""
    return money(debit - credit) if acct_type in DEBIT_NORMAL else money(credit - debit)


def _bucket(days_past_due: int) -> str:
    """Aging bucket for whole days past due: current while not yet past due."""
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "1_30"
    if days_past_due <= 60:
        return "31_60"
    if days_past_due <= 90:
        return "61_90"
    return "over_90"


def _day(value) -> str | None:
    """The calendar day of a date, or of a date or timestamp text (its first ten characters), or None."""
    if isinstance(value, _dt.date):
        return value.isoformat()[:10]
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return _dt.date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def percent_complete(cost_to_date, estimated_total_cost) -> Decimal:
    """Cost-to-cost percent complete, capped at 1, four places half-up.  Zero
    when there is no estimate or no cost."""
    cost = money(cost_to_date)
    estimate = money(estimated_total_cost)
    if estimate <= 0 or cost <= 0:
        return Decimal("0.0000")
    return min(cost / estimate, ONE).quantize(PERCENT_PLACES, rounding=ROUND_HALF_UP)


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
        self._install_reopen_grant_guard()

    # ---- reopen authority ------------------------------------------------------ #

    def _install_reopen_grant_guard(self) -> None:
        """Guard ``Cipher.approve`` for ``close.reopen_period`` approvals (every surface,
        the HTTP server and ``approve_and_execute`` included, grants through it).

        A role without any reopen authority is refused by the core itself
        (``RoleNotAuthorised``).  A role the core lets approve a reopen that is not in
        ``REOPEN_ROLES`` (an accountant) is refused here with ``ReopenAuthorityError``.
        For an owner or controller, the grant row (approver, role, and whether the role
        was declared or is the core's default approver role) is written while the
        approval is still pending and the core grants it in the same transaction; if the
        core refuses, neither is kept.  The database admits the pending -> granted move of
        a close reopen approval only with that row, and a period reopens against one only
        with it (``close_reopen_governance``), so an approval granted around
        ``Cipher.approve`` (``Approvals.grant`` directly, or a raw UPDATE) cannot be
        granted at all, let alone reopen through ``Ledger.reopen_period``.

        Roles are declared by the caller everywhere in the solo-first prototype (there is
        no identity directory; the owner holds every role), so the row is what the
        approver claimed, not a verified identity: ``role_basis`` says whether the claim
        was made (``declared``) or the core's default approver role applied
        (``core_default``, e.g. ``approve_and_execute``, which passes no role)."""
        inner = getattr(self.c, "approve", None)
        if not callable(inner) or getattr(inner, "_close_reopen_guard", False):
            return
        defaults = {"approver": "owner", "approver_role": "owner"}
        try:  # follow the core's own defaults rather than restating them
            for name, param in inspect.signature(inner).parameters.items():
                if name in defaults and param.default is not inspect.Parameter.empty:
                    defaults[name] = param.default
        except (TypeError, ValueError):
            pass
        plugin = self

        def approve(approval_id, **kwargs):
            row = plugin.db.one(
                "SELECT operation, subject_type, subject_id, status, expires_at FROM approvals WHERE id=?", (approval_id,)
            ) if isinstance(approval_id, str) else None
            if row is None or row["operation"] != OP_REOPEN:
                return inner(approval_id, **kwargs)
            declared = kwargs.get("approver_role") is not None
            role = kwargs["approver_role"] if declared else defaults["approver_role"]
            approver = kwargs.get("approver") if kwargs.get("approver") is not None else defaults["approver"]
            if not Ricky.can(role, OP_REOPEN):
                return inner(approval_id, **kwargs)  # the core refuses a role with no reopen authority
            if role not in REOPEN_ROLES:
                raise ReopenAuthorityError(
                    f"reopening a period needs a scoped controller approval; role {role!r} may not grant {OP_REOPEN} "
                    f"(allowed: {', '.join(REOPEN_ROLES)})"
                )
            if row["subject_type"] != PERIOD_SUBJECT or row["status"] != "pending" or parse_iso(row["expires_at"]) <= utcnow():
                # not one of this module's pending approvals: the core refuses it (or records its expiry)
                return inner(approval_id, **kwargs)
            with plugin.db.transaction():
                plugin._record_reopen_grant(approval_id, row["subject_id"], approver, role, "declared" if declared else "core_default")
                return inner(approval_id, **kwargs)  # the core grants; its trigger finds the grant row for this approver

        approve._close_reopen_guard = True  # type: ignore[attr-defined]
        self.c.approve = approve

    def _record_reopen_grant(self, approval_id: str, period_id: str, approver: str, role: str, role_basis: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO close_reopen_grants (approval_id, period_id, approver, approver_role, granted_at, role_basis) VALUES (?,?,?,?,?,?)",
                (approval_id, period_id, str(approver), role, utcnow_iso(), role_basis),
            )
            self.audit.record(str(approver), "close.reopen_grant_recorded", "approval", approval_id,
                              {"period_id": period_id, "approver_role": role, "role_basis": role_basis})

    def reopen_grant(self, approval_id: str) -> dict[str, Any] | None:
        """Who granted a reopen approval, under which role, and whether that role was
        declared or the core's default (None when no owner or controller grant was
        recorded for it)."""
        return self.db.one("SELECT * FROM close_reopen_grants WHERE approval_id=?", (approval_id,)) if isinstance(approval_id, str) else None

    def reopen_grants(self, period_id: str | None = None) -> list[dict[str, Any]]:
        if period_id:
            return self.db.query("SELECT * FROM close_reopen_grants WHERE period_id=? ORDER BY granted_at, approval_id", (period_id,))
        return self.db.query("SELECT * FROM close_reopen_grants ORDER BY granted_at, approval_id")

    # ---- lookups -------------------------------------------------------------- #

    def _period(self, period_id) -> dict[str, Any]:
        _non_empty(period_id, "period id")
        row = self.db.one("SELECT * FROM periods WHERE id=?", (period_id,))
        if row is None:
            raise CloseError(f"unknown period {period_id}")
        return row

    def _project(self, project_id) -> dict[str, Any]:
        _non_empty(project_id, "project id")
        row = self.db.one("SELECT * FROM projects WHERE id=?", (project_id,))
        if row is None:
            raise CloseError(f"unknown project {project_id}")
        return row

    def _accounts(self) -> dict[str, dict[str, Any]]:
        return {a["code"]: a for a in self.ledger.accounts()}

    def _earlier_periods(self, period: dict[str, Any]) -> list[dict[str, Any]]:
        """Periods that feed this period's cumulative balance sheet (start on or before it)."""
        return self.db.query(
            "SELECT id, status, start_date FROM periods WHERE start_date <= ? AND id != ? ORDER BY start_date, id",
            (period["start_date"], period["id"]),
        )

    def _later_periods(self, period: dict[str, Any]) -> list[dict[str, Any]]:
        """Periods whose cumulative balance sheet includes this period (start on or after it)."""
        return self.db.query(
            "SELECT id, status, start_date FROM periods WHERE start_date >= ? AND id != ? ORDER BY start_date, id",
            (period["start_date"], period["id"]),
        )

    def _sum_lines(self, accounts, *, project_id: str | None = None, through_start: str | None = None,
                   period_id: str | None = None, exclude_source_types=()) -> tuple[Decimal, Decimal]:
        """Exact debit and credit totals over journal lines (summed in Decimal, never in SQL)."""
        accounts = tuple(accounts)
        sql = (
            "SELECT l.debit, l.credit FROM journal_lines l JOIN journals j ON j.id = l.journal_id "
            "JOIN periods p ON p.id = j.period_id WHERE l.account_code IN (" + ",".join("?" * len(accounts)) + ")"
        )
        params: list[Any] = list(accounts)
        if project_id is not None:
            sql += " AND l.project_id = ?"
            params.append(project_id)
        if through_start is not None:
            sql += " AND p.start_date <= ?"
            params.append(through_start)
        if period_id is not None:
            sql += " AND j.period_id = ?"
            params.append(period_id)
        if exclude_source_types:
            sql += " AND j.source_type NOT IN (" + ",".join("?" * len(exclude_source_types)) + ")"
            params.extend(exclude_source_types)
        dr = ZERO
        cr = ZERO
        for row in self.db.query(sql, tuple(params)):
            dr += money(row["debit"])
            cr += money(row["credit"])
        return money(dr), money(cr)

    # ---- checklist ------------------------------------------------------------- #

    def checklist(self, period_id: str) -> list[dict[str, Any]]:
        """Every condition a period close depends on, as ``{"check","ok","detail","source"}``."""
        period = self._period(period_id)
        pid = period["id"]
        checks: list[dict[str, Any]] = []

        def add(check: str, ok: bool, detail: str, source: str) -> None:
            checks.append({"check": check, "ok": ok is True, "detail": str(detail), "source": source})

        def guarded(check: str, source: str, fn) -> None:
            try:
                fn()
            except Exception as exc:  # a check that cannot run must block, not pass
                add(check, False, f"check could not run: {type(exc).__name__}: {exc}", source)

        def trial_balance():
            tb = self.ledger.trial_balance(pid)
            add("trial_balance_balanced", bool(tb["balanced"]),
                f"period {pid}: debits {tb['total_debit']} {'=' if tb['balanced'] else '!='} credits {tb['total_credit']} across {tb['journal_count']} journal(s)", "ledger")

        def ap():
            r = self.c.bills.ap_open_items()
            add("ap_reconciled", bool(r["reconciled"]), f"AP subledger {r['subledger_total']} vs control 2000 {r['control_balance']}", "bills")

        def ar():
            r = self.c.receivables.ar_open_items()
            detail = f"AR subledger {r['subledger_total']} vs control 1100 {r['control_balance']}"
            errors = r.get("errors") or []
            if errors:  # a source that raised or did not add up is named, not hidden behind the totals
                detail += "; source errors: " + "; ".join(
                    f"{e.get('source', '?')}: {e.get('error', e)}" if isinstance(e, dict) else str(e) for e in errors
                )
            add("ar_reconciled", bool(r["reconciled"]), detail, "receivables")

        def supplier_drafts():
            rows = self.db.query(
                "SELECT id, sequence, status FROM bills WHERE period_id=? AND status IN ('draft','approved') ORDER BY created_at, id", (pid,)
            )
            detail = (f"{len(rows)} unposted supplier bill(s) in {pid}: " + ", ".join(f"{r['id']} (seq {r['sequence']}, {r['status']})" for r in rows)
                      if rows else f"no draft supplier bills in {pid}")
            add("no_draft_supplier_bills", not rows, detail, "bills")

        def prime_drafts():
            rows = self.db.query(
                "SELECT id, sequence, status FROM prime_bills WHERE period_id=? AND status IN ('draft','approved') ORDER BY created_at, id", (pid,)
            )
            detail = (f"{len(rows)} unposted prime bill(s) in {pid}: " + ", ".join(f"{r['id']} (seq {r['sequence']}, {r['status']})" for r in rows)
                      if rows else f"no draft prime bills in {pid}")
            add("no_draft_prime_bills", not rows, detail, "receivables")

        def payments():
            rows = self.db.query(
                "SELECT id, status, amount FROM payment_intents WHERE status IN ('submitted','outcome_unknown') ORDER BY created_at, id"
            )
            # an intent the provider has been processing past the threshold is in doubt too
            stale = self.c.payments.stale_processing() if hasattr(self.c.payments, "stale_processing") else []
            items = [f"{r['id']} ({r['status']}, {r['amount']})" for r in rows] + [
                f"{s['intent_id']} (processing {s['days_processing']} day(s), {s['amount']})" for s in stale]
            detail = (f"{len(items)} payment intent(s) unresolved: " + ", ".join(items)
                      if items else "no payment intent is submitted, outcome-unknown or stale in processing")
            add("no_unresolved_payments", not items, detail, "payments")

        def wip_drafts():
            rows = self.db.query("SELECT id, project_id FROM close_wip WHERE period_id=? AND status='draft' ORDER BY created_at, id", (pid,))
            detail = (f"{len(rows)} prepared WIP adjustment(s) still in draft in {pid}: " + ", ".join(f"{r['id']} (project {r['project_id']})" for r in rows)
                      + "; post or cancel them" if rows else f"no draft WIP adjustments in {pid}")
            add("no_draft_wip_adjustments", not rows, detail, PLUGIN_NAME)

        def wip_reconciled():
            bad = self._wip_exceptions(period)
            detail = ("WIP register does not reconcile to 1160 / 2300 through " + pid + ": " + "; ".join(bad)) if bad \
                else f"WIP register reconciles to 1160 / 2300 through {pid} (at most one live adjustment per project)"
            add("wip_reconciled", not bad, detail, PLUGIN_NAME)

        def earlier_periods():
            still_open = [p for p in self._earlier_periods(period) if p["status"] == "open"]
            detail = (f"earlier period(s) still open: {', '.join(p['id'] for p in still_open)}; close them first, because {pid}'s balance sheet is cumulative"
                      if still_open else f"every period before {pid} is closed or locked")
            add("earlier_periods_closed", not still_open, detail, "ledger")

        guarded("trial_balance_balanced", "ledger", trial_balance)
        guarded("earlier_periods_closed", "ledger", earlier_periods)
        guarded("ap_reconciled", "bills", ap)
        guarded("ar_reconciled", "receivables", ar)
        guarded("no_draft_supplier_bills", "bills", supplier_drafts)
        guarded("no_draft_prime_bills", "receivables", prime_drafts)
        guarded("no_unresolved_payments", "payments", payments)
        guarded("no_draft_wip_adjustments", PLUGIN_NAME, wip_drafts)
        guarded("wip_reconciled", PLUGIN_NAME, wip_reconciled)

        reimb = self.c._plugins.get("reimbursement")
        if reimb is not None and hasattr(reimb, "employee_payable_reconciliation"):
            def employee_payable():
                projects = self.db.query("SELECT id FROM projects ORDER BY created_at, id")
                bad = []
                subledger = ZERO
                for p in projects:
                    rec = reimb.employee_payable_reconciliation(p["id"])
                    subledger += money(rec["subledger_total"])
                    if not rec["reconciled"]:
                        bad.append(f"{p['id']} (subledger {rec['subledger_total']} vs control 2100 {rec['control_balance']})")
                # company level: 2100 lines with no project (or outside every project) are unexplained too
                code = self.ledger.account_for_control("ap_employee")
                company = self.ledger.balance(code)
                if money(subledger) != company:
                    bad.append(f"company-wide control {code} {fmt(company)} vs subledger {fmt(subledger)} (difference {fmt(company - subledger)} on lines outside the project subledgers)")
                detail = ("employee payable unreconciled for " + ", ".join(bad)) if bad \
                    else f"employee payable reconciled for {len(projects)} project(s) and company-wide ({fmt(company)})"
                add("employee_payable_reconciled", not bad, detail, "reimbursement")
            guarded("employee_payable_reconciled", "reimbursement", employee_payable)

        # Every other registered hook, including the core subledger checks (retainage payable
        # 2050, stored materials 1300, retainage receivable 1150, provider clearing 1200) that
        # the ``core_reconciliation`` pseudo-plugin contributes.  This module computes none of
        # those itself, and a check identical to one already listed (same name, result and
        # detail, e.g. the same hook registered under two names) is reported once.
        seen = {(ch["check"], ch["ok"], ch["detail"]) for ch in checks}
        seen_hooks: set[int] = set()
        for name, plugin in list(self.c._plugins.items()):
            if plugin is self or name == PLUGIN_NAME:
                continue
            hook = getattr(plugin, "close_checks", None)
            if not callable(hook):
                continue
            if id(plugin) in seen_hooks:
                continue
            seen_hooks.add(id(plugin))
            try:
                result = hook(pid)
            except Exception as exc:
                add(f"{name}.close_checks", False, f"plugin {name} close_checks raised {type(exc).__name__}: {exc}", name)
                continue
            if result is None:
                continue
            if not isinstance(result, (list, tuple)):
                add(f"{name}.close_checks", False, f"plugin {name} close_checks returned {type(result).__name__}, not a list", name)
                continue
            for item in result:
                if not isinstance(item, dict) or "check" not in item or "ok" not in item:
                    add(f"{name}.close_checks", False, f"plugin {name} returned a malformed check: {item!r}", name)
                    continue
                key = (str(item["check"]), item["ok"] is True, str(item.get("detail", "")))
                if key in seen:
                    continue
                seen.add(key)
                add(key[0], key[1], key[2], name)

        if self._banking_plugin_name() is None:
            add("bank_reconciliation", True, "bank reconciliation is not configured: no banking plugin is registered (informational)", PLUGIN_NAME)
        return checks

    def _banking_plugin_name(self) -> str | None:
        for name, plugin in self.c._plugins.items():
            if name in ("banking", "bank") or type(plugin).__module__.endswith(".banking"):
                return name
        return None

    def checklist_report(self, period_id: str) -> dict[str, Any]:
        checks = self.checklist(period_id)
        failing = [c["check"] for c in checks if not c["ok"]]
        return {"period_id": period_id, "checks": checks, "all_ok": not failing, "failing": failing, "hash": hash_json(checks), "label": SHADOW}

    # ---- statements ------------------------------------------------------------ #

    def statements(self, period_id: str) -> dict[str, Any]:
        period = self._period(period_id)
        pid = period["id"]
        accounts = self._accounts()
        rows = self.db.query(
            """SELECT l.account_code, l.debit, l.credit, j.id AS journal_id, j.period_id, j.source_type
               FROM journal_lines l JOIN journals j ON j.id = l.journal_id JOIN periods p ON p.id = j.period_id
               WHERE p.start_date <= ? ORDER BY l.account_code, j.posted_at, j.id, l.line_no""",
            (period["start_date"],),
        )
        cum: dict[str, list[Decimal]] = {}
        cur: dict[str, list[Decimal]] = {}
        cash: dict[str, dict[str, Any]] = {}
        for r in rows:
            dr, cr = money(r["debit"]), money(r["credit"])
            acc = cum.setdefault(r["account_code"], [ZERO, ZERO])
            acc[0] += dr
            acc[1] += cr
            if r["period_id"] == pid:
                acc = cur.setdefault(r["account_code"], [ZERO, ZERO])
                acc[0] += dr
                acc[1] += cr
                if r["account_code"] == CASH_ACCOUNT:
                    g = cash.setdefault(r["source_type"], {"inflow": ZERO, "outflow": ZERO, "journals": set()})
                    g["inflow"] += dr
                    g["outflow"] += cr
                    g["journals"].add(r["journal_id"])

        def line(code: str, dr: Decimal, cr: Decimal) -> dict[str, Any]:
            a = accounts.get(code, {"name": code, "type": "asset"})
            return {"code": code, "name": a["name"], "type": a["type"], "amount": _natural(a["type"], dr, cr)}

        # income statement: journals in this period only
        revenue_lines, expense_lines = [], []
        for code in sorted(cur):
            dr, cr = cur[code]
            typ = accounts.get(code, {}).get("type")
            if typ == "revenue":
                revenue_lines.append(line(code, dr, cr))
            elif typ == "expense":
                expense_lines.append(line(code, dr, cr))
        revenue = total(l["amount"] for l in revenue_lines)
        expense = total(l["amount"] for l in expense_lines)

        # balance sheet: cumulative through this period
        sections: dict[str, list[dict[str, Any]]] = {"asset": [], "liability": [], "equity": []}
        cum_revenue = ZERO
        cum_expense = ZERO
        for code in sorted(cum):
            dr, cr = cum[code]
            ln = line(code, dr, cr)
            if ln["type"] in sections:
                sections[ln["type"]].append(ln)
            elif ln["type"] == "revenue":
                cum_revenue += ln["amount"]
            elif ln["type"] == "expense":
                cum_expense += ln["amount"]
        total_assets = total(l["amount"] for l in sections["asset"])
        total_liabilities = total(l["amount"] for l in sections["liability"])
        total_equity = total(l["amount"] for l in sections["equity"])
        current_earnings = money(cum_revenue - cum_expense)
        liabilities_and_equity = money(total_liabilities + total_equity + current_earnings)

        # cash: movements on 1000 in this period by source type
        movements = []
        for source_type in sorted(cash):
            g = cash[source_type]
            movements.append({
                "source_type": source_type, "inflow": fmt(g["inflow"]), "outflow": fmt(g["outflow"]),
                "net": fmt(g["inflow"] - g["outflow"]), "journals": sorted(g["journals"]),
            })
        cash_dr, cash_cr = cum.get(CASH_ACCOUNT, [ZERO, ZERO])
        closing = money(cash_dr - cash_cr)
        net_change = money(sum((money(g["inflow"] - g["outflow"]) for g in cash.values()), ZERO))
        included = [p["id"] for p in self.db.query("SELECT id FROM periods WHERE start_date <= ? ORDER BY start_date, id", (period["start_date"],))]

        def strs(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [{**l, "amount": fmt(l["amount"])} for l in lines]

        return {
            "period_id": pid,
            "period_name": period["name"],
            "start_date": period["start_date"],
            "end_date": period["end_date"],
            "income_statement": {
                "revenue_lines": strs(revenue_lines),
                "expense_lines": strs(expense_lines),
                "revenue": fmt(revenue),
                "expense": fmt(expense),
                "net": fmt(revenue - expense),
            },
            "balance_sheet": {
                "periods_included": included,
                "assets": strs(sections["asset"]),
                "liabilities": strs(sections["liability"]),
                "equity": strs(sections["equity"]),
                "total_assets": fmt(total_assets),
                "total_liabilities": fmt(total_liabilities),
                "total_equity": fmt(total_equity),
                "current_earnings": fmt(current_earnings),
                "total_liabilities_and_equity": fmt(liabilities_and_equity),
                "balanced": total_assets == liabilities_and_equity,
            },
            "cash": {
                "account": CASH_ACCOUNT,
                "opening": fmt(closing - net_change),
                "movements": movements,
                "net_change": fmt(net_change),
                "closing": fmt(closing),
            },
            "label": SHADOW,
        }

    # ---- aging ------------------------------------------------------------------ #

    def aging(self, as_of: str) -> dict[str, Any]:
        """The AP and AR items open now, bucketed by days past due at ``as_of``
        (YYYY-MM-DD): ``current`` while not yet past due, then 1-30, 31-60, 61-90 and
        over 90 days past due.  An item with a ``due_date`` is aged from it; an item
        without one falls back to its document date (its ``invoice_date``, else the
        record's created date (UTC), looked up in the source record's own table for every
        AR source the core subledger aggregates), as if due that day.  An item whose
        document date is after ``as_of`` is not aged: it is reported apart under
        ``after_as_of``; an item nothing dates is reported apart under ``undated`` (never
        as current), so buckets + after_as_of + undated still equal the subledger totals.
        Open balances are not reconstructed as of a past date, so a historical ``as_of``
        carries a warning."""
        as_of_date = _parse_date(as_of, "as_of")
        today = _parse_date(utcnow_iso()[:10], "today")
        ap = self.c.bills.ap_open_items()
        ar = self.c.receivables.ar_open_items()
        ap_items = []
        for item in ap["items"]:
            open_amt = money(item["open"])
            if open_amt == ZERO:
                continue
            if item.get("bill_id"):
                b = self.db.one("SELECT created_at FROM bills WHERE id=?", (item["bill_id"],))
                created = b["created_at"] if b else item.get("created_at")
                ref, kind = item["bill_id"], "supplier_bill"
            else:
                r = self.db.one(
                    "SELECT MAX(j.posted_at) AS ts FROM journals j JOIN commitments c ON c.id = j.source_id "
                    "WHERE j.source_type='retainage_release' AND c.supplier_id=?",
                    (item.get("supplier_id"),),
                )
                created = item.get("created_at") or (r and r["ts"])
                ref, kind = item.get("id"), item.get("kind", "retainage_release")
            ap_items.append({"ref": ref, "kind": kind, "party_id": item.get("supplier_id"), "sequence": item.get("sequence"),
                             "date": _day(item.get("invoice_date")) or _day(created), "due_date": _day(item.get("due_date")), "open": open_amt})
        ar_items = []
        for item in ar["items"]:
            open_amt = money(item["open"])
            if open_amt == ZERO:
                continue
            ar_items.append(self._ar_aging_item(item, open_amt, as_of))
        warning = None
        if as_of_date < today:
            warning = (f"as_of {as_of} is before today ({today.isoformat()}): these are today's open items aged at as_of; items settled since "
                       "as_of are not shown and balances are not reconstructed as of that date")
        return {
            "as_of": as_of,
            "buckets": list(AGING_BUCKETS),
            "basis": ("items open now; whole days past the item's due date at as_of (current while not yet past due; 1-30, 31-60, 61-90, over 90); "
                      "an item without a due date is aged from its document date (invoice date, else the record's created date, UTC) as if due "
                      "that day; items dated after as_of are reported under after_as_of; items nothing dates are reported under undated"),
            "warning": warning,
            "ap": self._age(ap_items, ap, as_of_date),
            "ar": self._age(ar_items, ar, as_of_date),
            "label": SHADOW,
        }

    def _table_exists(self, table: str) -> bool:
        return self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)) is not None

    def _ar_record_date(self, item: dict[str, Any], kind: str) -> str | None:
        """The created date of the record behind a receivable: looked up in the source's own
        table when the item names a known record, else the item's own date, else the posting
        time of the journal it names.  None when nothing dates it (never as_of)."""
        for key, table in AR_RECORD_TABLES:
            ident = item.get(key)
            if not ident or (key == "invoice_id" and kind != "labor_invoice") or not self._table_exists(table):
                continue
            row = self.db.one(f"SELECT created_at FROM {table} WHERE id=?", (ident,))
            if row is not None and row["created_at"]:
                return row["created_at"]
        dated = item.get("created_at") or item.get("date") or item.get("billed_at")
        if isinstance(dated, str) and dated:
            return dated
        if item.get("journal_id"):
            row = self.db.one("SELECT posted_at FROM journals WHERE id=?", (item["journal_id"],))
            if row is not None:
                return row["posted_at"]
        return None

    def _ar_aging_item(self, item: dict[str, Any], open_amt: Decimal, as_of: str) -> dict[str, Any]:
        """One open receivable for aging.  The core AR subledger lists prime bills,
        retainage invoices and the items of every plugin source it aggregates (labor T&M
        invoices, reimbursement billings, ...).  Each keeps its own due date when it has
        one and is dated by its invoice date, else by the record that created it.  An item
        nothing dates is reported as ``undated``: never aged as current."""
        due = _day(item.get("due_date"))
        if item.get("prime_bill_id"):
            b = self.db.one("SELECT created_at, customer_id FROM prime_bills WHERE id=?", (item["prime_bill_id"],))
            return {"ref": item["prime_bill_id"], "kind": "prime_bill", "party_id": b["customer_id"], "sequence": item.get("sequence"),
                    "date": _day(item.get("invoice_date")) or _day(b["created_at"]), "due_date": due, "open": open_amt}
        ref = item.get("invoice_id") or item.get("retainage_invoice_id") or item.get("billing_id") or item.get("id") or item.get("ref")
        kind = item.get("kind") or item.get("source") or "receivable"
        day = _day(item.get("invoice_date")) or _day(self._ar_record_date(item, kind))
        return {"ref": ref, "kind": kind, "source": item.get("source"), "party_id": item.get("customer_id") or item.get("party_id"),
                "sequence": item.get("sequence"), "date": day, "due_date": due, "open": open_amt}

    @staticmethod
    def _age(items: list[dict[str, Any]], source: dict[str, Any], as_of_date: _dt.date) -> dict[str, Any]:
        """Bucket each item by whole days past due at ``as_of_date``.  ``days`` is the age
        from the item's document date (negative when dated after as_of), ``days_past_due``
        the days past its due date (or past its document date when it has no due date;
        0 while not yet due) and ``basis`` which of the two it was aged from."""
        buckets = {k: ZERO for k in AGING_BUCKETS}
        after = ZERO
        undated = ZERO
        out = []
        for it in items:
            doc, due = it.get("date"), it.get("due_date")
            days = (as_of_date - _dt.date.fromisoformat(doc)).days if doc else None
            basis, past_due = None, None
            if doc is None and due is None:
                b = UNDATED
                undated += it["open"]
            elif days is not None and days < 0:
                b = AFTER_AS_OF
                after += it["open"]
            else:
                basis = BASIS_DUE_DATE if due else BASIS_DOCUMENT_DATE
                past_due = max(0, (as_of_date - _dt.date.fromisoformat(due or doc)).days)
                b = _bucket(past_due)
                buckets[b] += it["open"]
            out.append({**it, "days": days, "days_past_due": past_due, "basis": basis, "bucket": b, "open": fmt(it["open"])})
        aged = total(buckets.values())
        grand = money(aged + after + undated)
        return {
            "items": out,
            "buckets": {k: fmt(v) for k, v in buckets.items()},
            "aged_total": fmt(aged),
            AFTER_AS_OF: fmt(after),
            UNDATED: fmt(undated),
            "total": fmt(grand),
            "subledger_total": source["subledger_total"],
            "control_balance": source["control_balance"],
            "reconciled": bool(source["reconciled"]),
            "ties_to_subledger": grand == money(source["subledger_total"]),
        }

    # ---- contract values --------------------------------------------------------- #

    def contract_value(self, project_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM close_contract_values WHERE project_id=? ORDER BY version DESC LIMIT 1", (project_id,))

    def contract_values(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM close_contract_values WHERE project_id=? ORDER BY version", (project_id,))

    def set_contract_value(self, project_id: str, contract_value, actor: str, note: str = "") -> dict[str, Any]:
        """Record a new version of the project's contract value (latest wins).  Draft WIP
        adjustments computed from the previous value are superseded and their open
        approvals invalidated."""
        actor = _non_empty(actor, "actor")
        try:
            raw = D(contract_value)
            if not raw.is_finite():
                raise CloseError(f"contract value must be a finite amount, got {contract_value!r}")
            value = money(raw)
        except (MoneyError, ArithmeticError) as exc:  # decimal.InvalidOperation is an ArithmeticError
            raise CloseError(f"contract value is not exact money: {contract_value!r} ({type(exc).__name__}: {exc})") from exc
        if value != raw:
            raise CloseError(f"contract value {contract_value!r} has more than two decimal places; pass whole cents")
        if value <= 0:
            raise CloseError(f"contract value must be positive, got {fmt(value)}")
        with self.db.transaction() as conn:
            self._project(project_id)
            current = self.contract_value(project_id)
            if current is not None and money(current["contract_value"]) == value:
                raise CloseError(f"contract value for project {project_id} is already {fmt(value)} (version {current['version']})")
            version = (current["version"] + 1) if current else 1
            cv_id = new_id("ccv")
            conn.execute(
                "INSERT INTO close_contract_values (id, project_id, version, contract_value, previous_value, set_by, note, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (cv_id, project_id, version, fmt(value), current["contract_value"] if current else None, actor, note or "", utcnow_iso()),
            )
            superseded = []
            for row in self.db.query("SELECT * FROM close_wip WHERE project_id=? AND status='draft' ORDER BY created_at, id", (project_id,)):
                self._withdraw(row, "superseded", actor=actor, reason=f"contract value changed to version {version}")
                superseded.append(row["id"])
            self.audit.record(actor, "close.contract_value_set", "project", project_id, {
                "contract_value": fmt(value), "version": version, "previous_value": current["contract_value"] if current else None,
                "wip_superseded": superseded,
            })
        return self.contract_value(project_id)

    # ---- WIP ------------------------------------------------------------------------ #

    def wip(self, project_id: str, period_id: str) -> dict[str, Any]:
        project = self._project(project_id)
        period = self._period(period_id)
        return self._compute_wip(project, period)

    def _compute_wip(self, project: dict[str, Any], period: dict[str, Any]) -> dict[str, Any]:
        project_id = project["id"]
        cv = self.contract_value(project_id)
        if cv is None:
            raise CloseError(f"project {project_id} has no contract value; call set_contract_value first")
        contract = money(cv["contract_value"])
        # The estimate covers the same cost types as cost to date (5000, 5100, 5300): fac_v2,
        # not the subcontract-only forecast_at_completion.
        forecast = self.c.forecast.project(project_id)
        estimated, basis = money(forecast["fac_v2"]), "fac_v2"
        if estimated <= 0 or (money(forecast["budget"]) <= 0 and estimated <= money(forecast["cost_to_date_by_type"]["total"])):
            raise CloseError(
                f"project {project_id} has no estimate of total cost (forecast fac_v2 {fmt(estimated)}, budget {forecast['budget']}); "
                "set a budget or execute a commitment before computing WIP"
            )
        dr, cr = self._sum_lines(COST_ACCOUNTS, project_id=project_id, through_start=period["start_date"])
        cost_to_date = money(dr - cr)
        pct = percent_complete(cost_to_date, estimated)
        earned = money(pct * contract)
        bdr, bcr = self._sum_lines(BILLING_ACCOUNTS, project_id=project_id, through_start=period["start_date"], exclude_source_types=(WIP_SOURCE_TYPE,))
        billed = money(bcr - bdr)
        over_under = money(billed - earned)
        if over_under < 0:
            position = "underbilled"
            adjustment = {"direction": "underbilled", "amount": fmt(-over_under), "debit_account": UNDERBILLINGS_ACCOUNT, "credit_account": REVENUE_ACCOUNT}
        elif over_under > 0:
            position = "overbilled"
            adjustment = {"direction": "overbilled", "amount": fmt(over_under), "debit_account": REVENUE_ACCOUNT, "credit_account": OVERBILLINGS_ACCOUNT}
        else:
            position = "even"
            adjustment = None
        inputs = {
            "project_id": project_id,
            "period_id": period["id"],
            "through_start_date": period["start_date"],
            "contract_value": fmt(contract),
            "contract_version": cv["version"],
            "estimated_total_cost": fmt(estimated),
            "estimated_total_cost_basis": basis,
            "cost_to_date": fmt(cost_to_date),
            "percent_complete": f"{pct:f}",
            "earned_revenue": fmt(earned),
            "billed_to_date": fmt(billed),
            "over_under": fmt(over_under),
            "policy": WIP_POLICY,
        }
        return {**inputs, "position": position, "adjustment": adjustment, "inputs_hash": hash_json(inputs), "label": SHADOW}

    def _wip_row(self, wip_id) -> dict[str, Any]:
        _non_empty(wip_id, "WIP adjustment id")
        row = self.db.one("SELECT * FROM close_wip WHERE id=?", (wip_id,))
        if row is None:
            raise CloseError(f"unknown WIP adjustment {wip_id}")
        return row

    def wip_adjustment(self, wip_id: str) -> dict[str, Any]:
        row = self._wip_row(wip_id)
        row["inputs"] = loads(row["inputs_json"])
        return row

    def wip_adjustments(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT id FROM close_wip WHERE project_id=? ORDER BY created_at, id", (project_id,))
        return [self.wip_adjustment(r["id"]) for r in rows]

    # A booked (posted or reversed) adjustment is on the books from its period's start
    # date up to, not including, the start of the period it was reversed into.

    def _booked_adjustments(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            """SELECT w.id, w.project_id, w.period_id, w.status, w.direction, w.amount, w.reversal_period_id,
                      p.start_date AS period_start, rp.start_date AS reversal_start
               FROM close_wip w JOIN periods p ON p.id = w.period_id LEFT JOIN periods rp ON rp.id = w.reversal_period_id
               WHERE w.project_id = ? AND w.status IN ('posted','reversed')
               ORDER BY p.start_date, w.created_at, w.id""",
            (project_id,),
        )

    @staticmethod
    def _live_in(row: dict[str, Any], start_date: str) -> bool:
        return row["period_start"] <= start_date and (row["reversal_start"] is None or row["reversal_start"] > start_date)

    def _booked_fingerprint(self, project_id: str) -> str:
        return hash_json([[r["id"], r["status"], r["period_id"], r["reversal_period_id"]] for r in self._booked_adjustments(project_id)])

    def _contract_balances(self, project_id: str | None, start_date: str) -> tuple[Decimal, Decimal]:
        """Cumulative 1160 (debit-positive) and 2300 (credit-positive) through ``start_date``."""
        udr, ucr = self._sum_lines((UNDERBILLINGS_ACCOUNT,), project_id=project_id, through_start=start_date)
        odr, ocr = self._sum_lines((OVERBILLINGS_ACCOUNT,), project_id=project_id, through_start=start_date)
        return money(udr - ucr), money(ocr - odr)

    def _wip_position(self, project_id: str, period: dict[str, Any], booked: list[dict[str, Any]]) -> dict[str, Any]:
        start = period["start_date"]
        live = [r for r in booked if self._live_in(r, start)]
        reg_under = total(r["amount"] for r in live if r["direction"] == "underbilled")
        reg_over = total(r["amount"] for r in live if r["direction"] == "overbilled")
        ledger_under, ledger_over = self._contract_balances(project_id, start)
        return {
            "period_id": period["id"],
            "through_start_date": start,
            "live_adjustments": [r["id"] for r in live],
            "underbillings_register": fmt(reg_under), "underbillings_ledger": fmt(ledger_under),
            "overbillings_register": fmt(reg_over), "overbillings_ledger": fmt(ledger_over),
            "reconciled": reg_under == ledger_under and reg_over == ledger_over and len(live) <= 1,
        }

    def _wip_exceptions(self, period: dict[str, Any]) -> list[str]:
        """Every reason the WIP register does not reconcile to 1160 / 2300 through ``period``."""
        projects = {r["project_id"] for r in self.db.query("SELECT DISTINCT project_id FROM close_wip")}
        projects |= {r["project_id"] for r in self.db.query(
            "SELECT DISTINCT project_id FROM journal_lines WHERE account_code IN (?,?) AND project_id IS NOT NULL",
            (UNDERBILLINGS_ACCOUNT, OVERBILLINGS_ACCOUNT),
        )}
        bad: list[str] = []
        reg_under = ZERO
        reg_over = ZERO
        for project_id in sorted(projects):
            pos = self._wip_position(project_id, period, self._booked_adjustments(project_id))
            reg_under += money(pos["underbillings_register"])
            reg_over += money(pos["overbillings_register"])
            if not pos["reconciled"]:
                bad.append(
                    f"project {project_id}: 1160 register {pos['underbillings_register']} vs ledger {pos['underbillings_ledger']}, "
                    f"2300 register {pos['overbillings_register']} vs ledger {pos['overbillings_ledger']}, "
                    f"live adjustment(s): {', '.join(pos['live_adjustments']) or 'none'}"
                )
        ledger_under, ledger_over = self._contract_balances(None, period["start_date"])
        if money(reg_under) != ledger_under or money(reg_over) != ledger_over:
            bad.append(f"company: 1160 ledger {fmt(ledger_under)} vs register {fmt(reg_under)}, 2300 ledger {fmt(ledger_over)} vs register {fmt(reg_over)} "
                       "(contract asset / liability lines outside the WIP register)")
        return bad

    def _require_room_for_adjustment(self, project_id: str, period: dict[str, Any]) -> None:
        """A new adjustment in ``period`` stays live from ``period`` onwards, so every booked
        adjustment must already be reversed into ``period`` or earlier, and the register
        must reconcile to the ledger in every period."""
        for r in self._booked_adjustments(project_id):
            if r["reversal_start"] is not None and r["reversal_start"] <= period["start_date"]:
                continue
            if r["status"] == "posted":
                if r["period_id"] == period["id"]:
                    raise CloseError(f"a WIP adjustment ({r['id']}) is already posted for project {project_id} in {period['id']}; reverse it before preparing another")
                raise CloseError(f"the WIP adjustment {r['id']} posted in {r['period_id']} is still live; reverse it into a later period before preparing another")
            raise CloseError(
                f"WIP adjustment {r['id']} ({r['period_id']}) is reversed only in {r['reversal_period_id']}, so it is still on the books in {period['id']}; "
                f"prepare the next adjustment in {r['reversal_period_id']} or a later period"
            )
        rec = self.wip_reconciliation(project_id)
        if not rec["reconciled"]:
            raise CloseError(
                f"the WIP register for project {project_id} does not reconcile to 1160 / 2300 (in {', '.join(rec['unreconciled_periods'])}); "
                "correct the contract asset / liability postings before preparing an adjustment"
            )

    def prepare_wip_adjustment(self, project_id: str, period_id: str, actor: str) -> dict[str, Any]:
        """Draft the period's WIP adjustment from the current WIP figures.  A previous
        draft with different inputs is superseded; identical inputs are a duplicate."""
        actor = _non_empty(actor, "actor")
        with self.db.transaction() as conn:
            project = self._project(project_id)
            period = self._period(period_id)
            self.ledger.require_open(period["id"])  # raises PeriodNotOpen
            w = self._compute_wip(project, period)
            if w["adjustment"] is None:
                raise CloseError(f"project {project_id} is neither over- nor underbilled in {period['id']} (billed {w['billed_to_date']} = earned {w['earned_revenue']}); nothing to adjust")
            self._require_room_for_adjustment(project_id, period)
            existing =self.db.one("SELECT * FROM close_wip WHERE project_id=? AND period_id=? AND status='draft'", (project_id, period["id"]))
            if existing is not None:
                if existing["inputs_hash"] == w["inputs_hash"]:
                    raise CloseError(f"an identical draft WIP adjustment ({existing['id']}) already exists for project {project_id} in {period['id']}")
                self._withdraw(existing, "superseded", actor=actor, reason="WIP inputs changed; re-prepared")
            adj = w["adjustment"]
            inputs = {k: w[k] for k in w if k not in ("position", "adjustment", "inputs_hash", "label")}
            wip_id = new_id("wip")
            conn.execute(
                """INSERT INTO close_wip (id, project_id, period_id, status, version, direction, amount, debit_account, credit_account,
                   contract_value, contract_version, estimated_total_cost, cost_to_date, percent_complete, earned_revenue, billed_to_date,
                   over_under, inputs_json, inputs_hash, prepared_by, created_at)
                   VALUES (?,?,?,'draft',1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    wip_id, project_id, period["id"], adj["direction"], adj["amount"], adj["debit_account"], adj["credit_account"],
                    w["contract_value"], w["contract_version"], w["estimated_total_cost"], w["cost_to_date"], w["percent_complete"],
                    w["earned_revenue"], w["billed_to_date"], w["over_under"], canonical_json(inputs), w["inputs_hash"], actor, utcnow_iso(),
                ),
            )
            self.audit.record(actor, "close.wip_prepared", WIP_SUBJECT, wip_id, {
                "project_id": project_id, "period_id": period["id"], "direction": adj["direction"], "amount": adj["amount"],
                "inputs_hash": w["inputs_hash"], "superseded": existing["id"] if existing else None,
            })
        return self.wip_adjustment(wip_id)

    def cancel_wip_adjustment(self, wip_id: str, actor: str, reason: str = "") -> dict[str, Any]:
        actor = _non_empty(actor, "actor")
        with self.db.transaction():
            row = self._wip_row(wip_id)
            if row["status"] != "draft":
                raise CloseError(f"WIP adjustment {wip_id} is {row['status']}; only a draft can be canceled (posted adjustments are reversed)")
            self._withdraw(row, "cancelled", actor=actor, reason=reason or "cancelled")
        return self.wip_adjustment(wip_id)

    def _withdraw(self, row: dict[str, Any], status: str, *, actor: str, reason: str) -> None:
        """Caller holds the transaction; ``row`` is a draft."""
        self.db.execute(
            "UPDATE close_wip SET status=?, version=version+1, note=?, withdrawn_at=? WHERE id=?",
            (status, reason, utcnow_iso(), row["id"]),
        )
        invalidated = self.approvals.invalidate_for_subject(WIP_SUBJECT, row["id"], reason=f"WIP adjustment {status}: {reason}", actor=actor)
        self.audit.record(actor, f"close.wip_{status}", WIP_SUBJECT, row["id"], {"reason": reason, "approvals_invalidated": invalidated})

    def wip_reconciliation(self, project_id: str, period_id: str | None = None) -> dict[str, Any]:
        """The project's WIP register against 1160 / 2300 as of a period: the adjustments
        live in the period (booked in it or earlier, not reversed in it or earlier)
        against the cumulative balances through it, with at most one live adjustment.
        Without ``period_id`` every period is reconciled, plus the all-time position
        (unreversed adjustments against the all-time balances)."""
        self._project(project_id)
        booked = self._booked_adjustments(project_id)
        if period_id is not None:
            return {"project_id": project_id, **self._wip_position(project_id, self._period(period_id), booked), "label": SHADOW}
        periods = [self._wip_position(project_id, p, booked) for p in self.db.query("SELECT * FROM periods ORDER BY start_date, id")]
        unreversed = [r for r in booked if r["status"] == "posted"]
        under = total(r["amount"] for r in unreversed if r["direction"] == "underbilled")
        over = total(r["amount"] for r in unreversed if r["direction"] == "overbilled")
        ledger_under = self.ledger.balance(UNDERBILLINGS_ACCOUNT, project_id=project_id)
        ledger_over = self.ledger.balance(OVERBILLINGS_ACCOUNT, project_id=project_id)
        unreconciled = [p["period_id"] for p in periods if not p["reconciled"]]
        if under != ledger_under or over != ledger_over or len(unreversed) > 1:
            unreconciled.append("all-time")
        return {
            "project_id": project_id,
            "underbillings_register": fmt(under), "underbillings_ledger": fmt(ledger_under),
            "overbillings_register": fmt(over), "overbillings_ledger": fmt(ledger_over),
            "periods": periods,
            "unreconciled_periods": unreconciled,
            "reconciled": not unreconciled,
            "label": SHADOW,
        }

    # ---- close runs -------------------------------------------------------------------- #

    def close_run(self, run_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM close_runs WHERE id=?", (run_id,))
        if row is None:
            raise CloseError(f"unknown close run {run_id}")
        row["checklist"] = loads(row.pop("checklist_json"))
        row["statements"] = loads(row.pop("statements_json"))
        return row

    def close_runs(self, period_id: str | None = None) -> list[dict[str, Any]]:
        if period_id:
            rows = self.db.query("SELECT id FROM close_runs WHERE period_id=? ORDER BY created_at, rowid", (period_id,))
        else:
            rows = self.db.query("SELECT id FROM close_runs ORDER BY created_at, rowid")
        return [self.close_run(r["id"]) for r in rows]

    def _record_run(self, *, period_id: str, action: str, status_before: str, status_after: str, approval_id: str, actor: str,
                    tb: dict[str, Any], checklist: list[dict[str, Any]] | None = None, statements: dict[str, Any] | None = None) -> str:
        run_id = new_id("crun")
        self.db.execute(
            """INSERT INTO close_runs (id, period_id, action, status_before, status_after, approval_id, actor, checklist_json, checklist_hash,
               statements_json, statements_hash, total_debit, total_credit, journal_count, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id, period_id, action, status_before, status_after, approval_id, actor,
                canonical_json(checklist) if checklist is not None else None, hash_json(checklist) if checklist is not None else None,
                canonical_json(statements) if statements is not None else None, hash_json(statements) if statements is not None else None,
                tb["total_debit"], tb["total_credit"], tb["journal_count"], utcnow_iso(),
            ),
        )
        return run_id

    def _last_run(self, period_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT id, action, checklist_hash, statements_hash FROM close_runs WHERE period_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (period_id,))

    def _checklist_close_run(self, period_id: str) -> dict[str, Any] | None:
        """The close run that produced the period's current closed state, or None when the
        period was last closed outside the checklist.  ``close.close_period`` records its
        ``close.period_closed`` audit entry right after the ledger's ``period.closed``; a
        later ledger ``period.closed`` (a direct re-close) leaves no such entry after it."""
        ledger_closes = [e for e in self.audit.entries(entity_type="period", entity_id=period_id) if e["action"] == "period.closed"]
        if not ledger_closes:
            return None
        last_seq = ledger_closes[-1]["seq"]
        ours = [e for e in self.audit.entries(entity_type=PERIOD_SUBJECT, entity_id=period_id) if e["action"] == "close.period_closed" and e["seq"] > last_seq]
        if not ours:
            return None
        run_id = loads(ours[0]["payload_json"]).get("close_run_id")
        last = self._last_run(period_id)
        if not run_id or last is None or last["id"] != run_id:
            return None
        return self.close_run(run_id)

    # ---- manifests ----------------------------------------------------------------------- #

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation not in OPERATIONS:
            raise CloseError(f"unknown close operation {operation}")
        if actor_role not in CLOSE_ROLES:
            raise CloseError(f"role {actor_role!r} may not request {operation}; allowed: {', '.join(CLOSE_ROLES)}")
        if operation == OP_REOPEN and actor_role not in REOPEN_ROLES:
            raise CloseError(f"reopening a period needs a scoped controller approval; role {actor_role!r} may not request it (allowed: {', '.join(REOPEN_ROLES)})")
        if operation in (OP_CLOSE, OP_REOPEN, OP_LOCK):
            return self._period_manifest(operation, subject_id, actor_role=actor_role)
        return self._wip_manifest(operation, subject_id, actor_role=actor_role)

    def _period_manifest(self, operation: str, period_id: str, *, actor_role: str) -> dict[str, Any]:
        p = self._period(period_id)
        tb = self.ledger.trial_balance(p["id"])
        statements_hash = hash_json(self.statements(p["id"]))
        bindings: dict[str, Any] = {
            "period_id": p["id"],
            "period_status": p["status"],
            "start_date": p["start_date"],
            "end_date": p["end_date"],
            "journal_count": tb["journal_count"],
            "trial_balance_balanced": tb["balanced"],
            "statements_hash": statements_hash,
        }
        if operation in (OP_CLOSE, OP_LOCK):
            bindings["earlier_periods"] = [[e["id"], e["status"]] for e in self._earlier_periods(p)]
        if operation == OP_CLOSE:
            report = self.checklist_report(p["id"])
            bindings.update({"checklist_hash": report["hash"], "checklist_ok": report["all_ok"], "failing_checks": report["failing"]})
        else:
            last = self._last_run(p["id"])
            bindings.update({
                "closed_at": p["closed_at"],
                "closed_by": p["closed_by"],
                "last_close_run": last["id"] if last else None,
                "last_close_run_action": last["action"] if last else None,
            })
            if operation == OP_REOPEN:
                bindings["approval_scope"] = "controller reopen of a closed (not locked) period"
                bindings["later_periods"] = [[e["id"], e["status"]] for e in self._later_periods(p)]
            else:
                run = self._checklist_close_run(p["id"]) if p["status"] == "closed" else None
                bindings["checklist_close_run"] = run["id"] if run else None
        return build_manifest(
            operation=operation, subject_type=PERIOD_SUBJECT, subject_id=p["id"], actor_role=actor_role,
            amounts={"total_debit": tb["total_debit"], "total_credit": tb["total_credit"]},
            bindings=bindings,
        )

    def _reversal_target(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """The first open period that starts after the adjustment's period."""
        original = self._period(row["period_id"])
        return self.db.one(
            "SELECT * FROM periods WHERE status='open' AND start_date > ? ORDER BY start_date, id LIMIT 1", (original["start_date"],)
        )

    def _wip_manifest(self, operation: str, wip_id: str, *, actor_role: str) -> dict[str, Any]:
        row = self._wip_row(wip_id)
        period = self._period(row["period_id"])
        bindings: dict[str, Any] = {
            "project_id": row["project_id"],
            "period_id": row["period_id"],
            "wip_status": row["status"],
            "wip_version": row["version"],
            "inputs_hash": row["inputs_hash"],
            "direction": row["direction"],
            "contract_version": row["contract_version"],
            "percent_complete": row["percent_complete"],
            "cost_to_date": row["cost_to_date"],
            "estimated_total_cost": row["estimated_total_cost"],
            "estimated_total_cost_basis": loads(row["inputs_json"]).get("estimated_total_cost_basis"),
            "posting_rule": POSTING_RULE,
            "policy": WIP_POLICY,
        }
        if operation == OP_POST_WIP:
            try:
                current = self._compute_wip(self._project(row["project_id"]), period)["inputs_hash"]
            except CloseError as exc:
                current = f"unavailable: {exc}"
            under, over = self._contract_balances(row["project_id"], period["start_date"])
            bindings.update({
                "period_status": period["status"],
                "current_inputs_hash": current,
                "debit_account": row["debit_account"],
                "credit_account": row["credit_account"],
                "booked_adjustments_hash": self._booked_fingerprint(row["project_id"]),
                "contract_balances_through_period": {UNDERBILLINGS_ACCOUNT: fmt(under), OVERBILLINGS_ACCOUNT: fmt(over)},
            })
        else:
            target = self._reversal_target(row)
            bindings.update({
                "journal_id": row["journal_id"],
                "debit_account": row["credit_account"],
                "credit_account": row["debit_account"],
                "target_period": target["id"] if target else None,
                "target_period_start": target["start_date"] if target else None,
                "target_rule": "the first open period after " + row["period_id"],
            })
        return build_manifest(
            operation=operation, subject_type=WIP_SUBJECT, subject_id=row["id"], actor_role=actor_role,
            amounts={"amount": row["amount"], "over_under": row["over_under"], "earned_revenue": row["earned_revenue"], "billed_to_date": row["billed_to_date"]},
            bindings=bindings,
        )

    # ---- apply ----------------------------------------------------------------------------- #

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation not in OPERATIONS:
            raise CloseError(f"unknown close operation {operation}")
        self._require_consumed(approval_id, operation, PERIOD_SUBJECT if operation in (OP_CLOSE, OP_REOPEN, OP_LOCK) else WIP_SUBJECT, subject_id)
        if operation == OP_CLOSE:
            return self._apply_close(subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)
        if operation == OP_REOPEN:
            return self._apply_reopen(subject_id, approval_id=approval_id, actor=actor, period_id=period_id)
        if operation == OP_LOCK:
            return self._apply_lock(subject_id, approval_id=approval_id, actor=actor, period_id=period_id)
        if operation == OP_POST_WIP:
            return self._apply_post_wip(subject_id, approval_id=approval_id, actor=actor, period_id=period_id)
        if operation == OP_REVERSE_WIP:
            return self._apply_reverse_wip(subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)
        raise CloseError(f"unknown close operation {operation}")

    @staticmethod
    def _same_period(subject_id: str, period_id: str | None) -> None:
        if period_id and period_id != subject_id:
            raise CloseError(f"the approval is for period {subject_id}, not {period_id}")

    def _require_consumed(self, approval_id: str, operation: str, subject_type: str, subject_id: str) -> None:
        """``apply`` runs inside ``Cipher.execute`` right after the approval was consumed in the
        same transaction; refuse anything else (a direct call with an arbitrary reference, or
        an approval whose effect is already on record)."""
        ap = self.db.one("SELECT status, operation, subject_type, subject_id FROM approvals WHERE id=?", (approval_id,)) if approval_id else None
        if ap is None or ap["status"] != "consumed" or ap["operation"] != operation or ap["subject_type"] != subject_type or ap["subject_id"] != subject_id:
            raise CloseError(f"{operation} on {subject_id} runs only against its own consumed approval; {approval_id!r} is not one")
        used = self.db.one("SELECT id FROM close_runs WHERE approval_id=?", (approval_id,)) or self.db.one(
            "SELECT id FROM close_wip WHERE approval_id=? OR reversal_approval_id=?", (approval_id, approval_id)
        )
        if used is not None:
            raise CloseError(f"approval {approval_id} was already executed ({used['id']}); an approval takes effect once")

    def _apply_close(self, pid: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        self._same_period(pid, period_id)
        with self.db.transaction():
            p = self._period(pid)
            if p["status"] != "open":
                raise CloseError(f"period {pid} is {p['status']}; only an open period can be closed")
            report = self.checklist_report(pid)
            if not report["all_ok"]:
                failing = "; ".join(f"{c['check']}: {c['detail']}" for c in report["checks"] if not c["ok"])
                raise CloseError(f"period {pid} cannot close; failing checks: {failing}")
            if report["hash"] != manifest.get("bindings", {}).get("checklist_hash"):
                raise CloseError(f"the checklist for {pid} changed after approval; request a new approval")
            statements = self.statements(pid)
            tb = self.ledger.trial_balance(pid)
            self.ledger.close_period(pid, actor=actor)
            run_id = self._record_run(period_id=pid, action="close", status_before="open", status_after="closed", approval_id=approval_id,
                                      actor=actor, tb=tb, checklist=report["checks"], statements=statements)
            invalidated = self.approvals.invalidate_for_subject(PERIOD_SUBJECT, pid, reason=f"period {pid} closed", actor=actor)
            self.audit.record(actor, "close.period_closed", PERIOD_SUBJECT, pid, {
                "approval_id": approval_id, "close_run_id": run_id, "checklist_hash": report["hash"], "statements_hash": hash_json(statements),
                "total_debit": tb["total_debit"], "journal_count": tb["journal_count"], "approvals_invalidated": invalidated,
            })
        return {
            "period_id": pid, "status": "closed", "close_run_id": run_id, "checklist_hash": report["hash"], "checks": len(report["checks"]),
            "statements_hash": hash_json(statements), "total_debit": tb["total_debit"], "total_credit": tb["total_credit"],
            "net_income": statements["income_statement"]["net"],
        }

    def _apply_reopen(self, pid: str, *, approval_id: str, actor: str, period_id: str | None) -> dict[str, Any]:
        self._same_period(pid, period_id)
        with self.db.transaction():
            p = self._period(pid)
            if p["status"] == "locked":
                raise CloseError(f"period {pid} is locked and can never be reopened")
            if p["status"] != "closed":
                raise CloseError(f"period {pid} is {p['status']}; only a closed period can be reopened")
            grant = self.reopen_grant(approval_id)
            if grant is None or grant["period_id"] != pid or grant["approver_role"] not in REOPEN_ROLES:
                raise CloseError(
                    f"reopen approval {approval_id} carries no recorded owner or controller grant for {pid}; "
                    "a reopen needs a scoped controller approval granted through Cipher.approve"
                )
            later = [e for e in self._later_periods(p) if e["status"] != "open"]
            if later:
                raise CloseError(
                    f"period {pid} cannot be reopened while later period(s) {', '.join(e['id'] + ' (' + e['status'] + ')' for e in later)} "
                    f"are not open: their cumulative balance sheets include {pid}; reopen them first (a locked one never reopens)"
                )
            tb = self.ledger.trial_balance(pid)
            # The reopen run is recorded first, in the same transaction: the period trigger
            # (close_reopen_governance) lets one of this module's approvals reopen a period
            # only once its run exists, so a reopen outside this execution path is refused.
            run_id = self._record_run(period_id=pid, action="reopen", status_before="closed", status_after="open", approval_id=approval_id, actor=actor, tb=tb)
            # the ledger (and the core period trigger) accept a reopen only against a consumed
            # "*.reopen_period" approval for this period: this one, consumed by Cipher.execute
            # inside the same transaction just before apply ran
            self.ledger.reopen_period(pid, actor=actor, approval_ref=approval_id)
            invalidated = self.approvals.invalidate_for_subject(PERIOD_SUBJECT, pid, reason=f"period {pid} reopened", actor=actor)
            self.audit.record(actor, "close.period_reopened", PERIOD_SUBJECT, pid, {
                "approval_id": approval_id, "close_run_id": run_id, "approvals_invalidated": invalidated,
                "granted_by": grant["approver"], "granted_as": grant["approver_role"], "role_basis": grant.get("role_basis"),
            })
        return {"period_id": pid, "status": "open", "close_run_id": run_id, "granted_by": grant["approver"], "granted_as": grant["approver_role"],
                "role_basis": grant.get("role_basis")}

    def _apply_lock(self, pid: str, *, approval_id: str, actor: str, period_id: str | None) -> dict[str, Any]:
        self._same_period(pid, period_id)
        with self.db.transaction():
            p = self._period(pid)
            if p["status"] != "closed":
                raise CloseError(f"period {pid} is {p['status']}; only a closed period can be locked")
            run = self._checklist_close_run(pid)
            if run is None:
                raise CloseError(
                    f"period {pid} was closed outside the close checklist; reopen it and close it with close.close_period before locking"
                )
            if not run["checklist"] or not all(ch.get("ok") is True for ch in run["checklist"]):
                raise CloseError(f"the close run {run['id']} for {pid} does not show a passing checklist; it cannot be locked")
            unlocked = [e for e in self._earlier_periods(p) if e["status"] != "locked"]
            if unlocked:
                raise CloseError(
                    f"earlier period(s) {', '.join(e['id'] + ' (' + e['status'] + ')' for e in unlocked)} must be locked before {pid}: "
                    f"{pid}'s locked balance sheet includes them"
                )
            tb = self.ledger.trial_balance(pid)
            statements = self.statements(pid)
            if (tb["total_debit"], tb["total_credit"], tb["journal_count"]) != (run["total_debit"], run["total_credit"], run["journal_count"]) \
                    or hash_json(statements) != run["statements_hash"]:
                raise CloseError(f"period {pid} changed after its checklist close ({run['id']}); reopen it and close it again before locking")
            self.ledger.lock_period(pid, actor=actor)
            run_id = self._record_run(period_id=pid, action="lock", status_before="closed", status_after="locked", approval_id=approval_id,
                                      actor=actor, tb=tb, statements=statements)
            invalidated = self.approvals.invalidate_for_subject(PERIOD_SUBJECT, pid, reason=f"period {pid} locked", actor=actor)
            self.audit.record(actor, "close.period_locked", PERIOD_SUBJECT, pid, {"approval_id": approval_id, "close_run_id": run_id, "statements_hash": hash_json(statements), "approvals_invalidated": invalidated})
        return {"period_id": pid, "status": "locked", "close_run_id": run_id}

    def _apply_post_wip(self, wip_id: str, *, approval_id: str, actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = self._wip_row(wip_id)
            if row["status"] != "draft":
                raise CloseError(f"WIP adjustment {wip_id} is {row['status']}; only a draft can be posted")
            if period_id and period_id != row["period_id"]:
                raise CloseError(f"WIP adjustment {wip_id} belongs to period {row['period_id']}, not {period_id}")
            period = self.ledger.require_open(row["period_id"])  # raises PeriodNotOpen
            project = self._project(row["project_id"])
            current = self._compute_wip(project, period)
            if current["inputs_hash"] != row["inputs_hash"]:
                raise CloseError(f"WIP inputs for project {row['project_id']} changed since adjustment {wip_id} was prepared; prepare it again")
            self._require_room_for_adjustment(row["project_id"], period)
            amount = money(row["amount"])
            memo = f"WIP {row['direction']} {row['period_id']}: billed {row['billed_to_date']} vs earned {row['earned_revenue']} ({row['percent_complete']} complete)"
            customer = project["customer_id"]
            j = self.ledger.post(
                period_id=row["period_id"],
                description=f"WIP adjustment ({row['direction']}) for project {row['project_id']} in {row['period_id']}",
                lines=[
                    {"account": row["debit_account"], "debit": amount, "project_id": row["project_id"], "party_id": customer, "memo": memo},
                    {"account": row["credit_account"], "credit": amount, "project_id": row["project_id"], "party_id": customer, "memo": memo},
                ],
                source_type=WIP_SOURCE_TYPE, source_id=wip_id, source_version=str(row["version"]), posted_by=actor, approval_id=approval_id,
            )
            conn.execute(
                "UPDATE close_wip SET status='posted', version=version+1, approval_id=?, journal_id=?, posted_at=? WHERE id=?",
                (approval_id, j["id"], utcnow_iso(), wip_id),
            )
            invalidated = self.approvals.invalidate_for_subject(WIP_SUBJECT, wip_id, reason="WIP adjustment already posted", actor=actor)
            self.audit.record(actor, "close.wip_posted", WIP_SUBJECT, wip_id, {
                "approval_id": approval_id, "journal_id": j["id"], "project_id": row["project_id"], "period_id": row["period_id"],
                "direction": row["direction"], "amount": fmt(amount), "inputs_hash": row["inputs_hash"], "approvals_invalidated": invalidated,
            })
        return {
            "wip_adjustment": wip_id, "status": "posted", "journal_id": j["id"], "project_id": row["project_id"], "period_id": row["period_id"],
            "direction": row["direction"], "amount": fmt(amount), "debit_account": row["debit_account"], "credit_account": row["credit_account"],
        }

    def _apply_reverse_wip(self, wip_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if not period_id:
            raise CloseError("reversing a WIP adjustment needs period_id: the first open period after the adjustment's period")
        with self.db.transaction() as conn:
            row = self._wip_row(wip_id)
            if row["status"] != "posted":
                raise CloseError(f"WIP adjustment {wip_id} is {row['status']}; only a posted adjustment can be reversed")
            original = self._period(row["period_id"])
            target = self._period(period_id)
            if target["start_date"] <= original["start_date"]:
                raise CloseError(f"the reversal period {period_id} must start after {row['period_id']} ({original['start_date']})")
            self.ledger.require_open(target["id"])  # raises PeriodNotOpen
            expected = self._reversal_target(row)
            bound = (manifest.get("bindings") or {}).get("target_period")
            if expected is None or target["id"] != expected["id"] or target["id"] != bound:
                raise CloseError(
                    f"WIP adjustment {wip_id} reverses into the first open period after {row['period_id']} "
                    f"({expected['id'] if expected else 'none'}; approved: {bound}), not {period_id}: skipping a period would leave the "
                    "contract asset / liability on its books"
                )
            j = self.ledger.reverse(row["journal_id"], period_id=target["id"], posted_by=actor, reason=f"WIP adjustment {wip_id} reversed", approval_id=approval_id)
            conn.execute(
                "UPDATE close_wip SET status='reversed', version=version+1, reversal_approval_id=?, reversal_journal_id=?, reversal_period_id=?, reversed_at=? WHERE id=?",
                (approval_id, j["id"], target["id"], utcnow_iso(), wip_id),
            )
            invalidated = self.approvals.invalidate_for_subject(WIP_SUBJECT, wip_id, reason="WIP adjustment reversed", actor=actor)
            self.audit.record(actor, "close.wip_reversed", WIP_SUBJECT, wip_id, {
                "approval_id": approval_id, "journal_id": row["journal_id"], "reversal_journal_id": j["id"], "period_id": target["id"],
                "amount": row["amount"], "approvals_invalidated": invalidated,
            })
        return {
            "wip_adjustment": wip_id, "status": "reversed", "journal_id": row["journal_id"], "reversal_journal_id": j["id"],
            "period_id": target["id"], "amount": row["amount"],
        }

    # ---- audit export ---------------------------------------------------------------------------- #

    def audit_export(self) -> dict[str, Any]:
        """Close runs (with their checklist and statements snapshots), the recorded reopen
        grants (who granted each reopen approval, under which role), every WIP adjustment
        with its inputs, contract value history and the WIP register reconciliation per
        project, for an independent reviewer (JSON-serializable; money as strings)."""
        projects = {r["project_id"] for r in self.db.query("SELECT DISTINCT project_id FROM close_wip")}
        projects |= {r["project_id"] for r in self.db.query("SELECT DISTINCT project_id FROM close_contract_values")}
        projects |= {r["project_id"] for r in self.db.query(
            "SELECT DISTINCT project_id FROM journal_lines WHERE account_code IN (?,?) AND project_id IS NOT NULL",
            (UNDERBILLINGS_ACCOUNT, OVERBILLINGS_ACCOUNT),
        )}
        wip_rows = [self.wip_adjustment(r["id"]) for r in self.db.query("SELECT id FROM close_wip ORDER BY created_at, id")]
        return {
            "label": SHADOW,
            "posting_rule": POSTING_RULE,
            "wip_policy": WIP_POLICY,
            "close_runs": self.close_runs(),
            "reopen_grants": self.db.query("SELECT * FROM close_reopen_grants ORDER BY granted_at, approval_id"),
            "wip_adjustments": wip_rows,
            "contract_values": self.db.query("SELECT * FROM close_contract_values ORDER BY project_id, version"),
            "wip_reconciliation": {pid: self.wip_reconciliation(pid) for pid in sorted(projects)},
        }

    # ---- state --------------------------------------------------------------------------------- #

    def state(self, project_id: str) -> dict[str, Any]:
        out: dict[str, Any] = {"project_id": project_id, "label": SHADOW}
        cv = self.contract_value(project_id)
        out["contract_value"] = cv["contract_value"] if cv else None
        out["contract_version"] = cv["version"] if cv else None
        out["contract_value_history"] = self.contract_values(project_id)
        open_periods = self.db.query("SELECT * FROM periods WHERE status='open' ORDER BY start_date, id")
        checklists: dict[str, Any] = {}
        for p in open_periods:
            try:
                checklists[p["id"]] = self.checklist_report(p["id"])
            except Exception as exc:  # state must render even when a check cannot
                checklists[p["id"]] = {"period_id": p["id"], "error": f"{type(exc).__name__}: {exc}"}
        out["checklists"] = checklists
        latest = open_periods[-1] if open_periods else None
        out["wip_period_id"] = latest["id"] if latest else None
        out["wip"] = None
        out["wip_error"] = None
        if latest is None:
            out["wip_error"] = "no open period"
        else:
            try:
                out["wip"] = self._compute_wip(self._project(project_id), latest)
            except Exception as exc:
                out["wip_error"] = str(exc)
        out["wip_adjustments"] = self.wip_adjustments(project_id)
        try:
            out["wip_reconciliation"] = self.wip_reconciliation(project_id)
        except Exception as exc:
            out["wip_reconciliation"] = {"error": str(exc)}
        out["close_runs"] = self.db.query(
            """SELECT id, period_id, action, status_before, status_after, approval_id, actor, checklist_hash, statements_hash,
               total_debit, total_credit, journal_count, created_at FROM close_runs ORDER BY created_at DESC, rowid DESC LIMIT 20"""
        )
        return out
