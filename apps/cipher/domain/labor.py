"""AEC practice management: labor rates, phases and fee budgets, timesheets,
payroll settlement, utilization, time-and-materials billing and collection
(v2 plugin, operation prefix ``labor``).

Posting rules (fixture policy ``cipher-posting-rules/1``; SHADOW, synthetic prototype only):

* ``labor.approve_timesheet``  Dr 5300 Project cost - labor, one line per project and phase
                               (project_id set, memo carries the phase code) /
                               Cr 2200 Accrued payroll (party = employee) for the timesheet's
                               total cost, posted in the timesheet's period.
* ``labor.post_payroll``       Dr 2200 Accrued payroll / Cr 1000 Operating bank (party = employee).
                               Payroll SETTLES the accrual created by approved time; it never posts
                               labor cost a second time (plan section 10, step 3: "costs are not
                               counted twice through payroll imports").
* ``labor.bill``               Dr 1100 Accounts receivable (party = project customer) /
                               Cr 4100 Fee revenue, one credit line per phase, in the invoice's period.
* ``record_collection``        Dr 1000 Operating bank (net of fee) / Dr 6000 Bank and processing fees /
                               Cr 1100 Accounts receivable (party = invoice customer), in the receipt's
                               period.  Like ``Receivables.record_collection`` this is a plain record
                               method (simulated money in, no approval).

Rates are effective-dated per employee: the rate for a work date is the one with
the latest ``effective_from`` on or before that date.  A rate is immutable once ANY
time entry has used it, including entries later voided or re-rated (a sticky
``used`` flag set by trigger); add a new effective date instead.  A new rate dated
before time already logged re-rates the draft entries it now governs, is refused
while submitted time it would govern awaits approval (reject that timesheet first,
so the approver sees the effective rate), and leaves approved or billed time at the
rate it was approved at, because that cost is already posted.  So every draft or
submitted entry carries the rate effective for its work date.

Time entries carry their cost and bill amounts, computed at the effective rate
when logged.  Hours are exact decimals to the hundredth, greater than zero and at
most 24 per entry and per employee per day across all projects.  Time cannot be
logged on, or moved to, a work date that lies only in closed or locked periods.

Payroll is cut off by period.  A settlement recorded in period P may pay only time
approved in P or earlier periods, and may not leave the employee's accrual
overdrawn at the end of P or of any later period (payroll already recorded in a
later period may have settled that time).  The 2200 reconciliation used by the
close checklist is cut off at the period too.

Accounts receivable: T&M invoices debit control account 1100 next to prime bills.
``ar_open_items(project_id)`` exposes the labor T&M subledger (billed less collected)
in the shape of ``Receivables.ar_open_items``; the core receivables subledger
aggregates it (``Receivables.extra_ar_sources``), so the AR reconciliation behind
the close checklist, aging and Ricky ties prime bills plus T&M invoices to 1100.
The module does not report the 1100 control itself (that would be reported twice);
its own close check ``tm_receivable_reconciliation`` only proves that the T&M
subledger agrees with the 1100 lines its own invoice and collection journals posted,
cumulatively through the period, which tells a reviewer which source is off.
A billed invoice is corrected only by reversing its billing journal (the governed
``journal.reverse``): the reversal clears the whole receivable it posted, so the
subledger and 1100 still agree, and no receipt can be recorded against the invoice
afterwards.  A reversed collection journal no longer counts as collected.
``record_collection`` refuses a receipt reference already used, ignoring case, in this
module's collections or in any other 1100 receipt table (prime bill, prime retainage
and reimbursement collections); the database backs only the labor table's own
uniqueness (``labor_collections.provider_ref`` UNIQUE NOCASE).  The other direction
belongs to the other modules: ``Receivables.record_collection`` checks labor
references, while the reimbursement module's collection checks only its own table at
the time of writing, so a reimbursement receipt can still reuse a labor reference.

Record lifecycles (SQLite triggers reject every other transition):

* entry:      draft -> submitted -> approved -> billed;  submitted -> draft (timesheet rejected);
              draft -> void (``delete_entry``; rows are never deleted)
* timesheet:  submitted -> approved | rejected;  rejected -> submitted (resubmission of the SAME
              timesheet as its next version).  At most one open (submitted or rejected) timesheet
              per employee per period.
* payroll:    draft -> posted | canceled.  A reference is never reused, even after a cancel.
* invoice:    draft -> billed | void.  An entry is reserved by at most one live invoice line
              (partial UNIQUE index); voiding a draft invoice releases its lines.
* collection: immutable once recorded; only against a billed invoice of its project and customer
              (``labor_collections_billed_invoice_only``); and, from ``labor_collection_guards`` on,
              with exact two-place amount and fee, never in a period that starts before the
              invoice's billing period, never after the billing journal was reversed, only with its
              own collection journal crediting 1100 by exactly its amount, and never above the
              invoice's open amount (billed total less unreversed collections).  ``record_collection``
              checks the same rules first, with clear messages, plus the open receipt period and the
              receipt reference.

Approvals bind the subject's version, a content hash recomputed from the CURRENT
records, the exact amounts and allocation, the period and the counterparties, so
a change after an approval was granted makes it stale instead of executing
something the approver did not see.  Rejecting a timesheet, cancelling a payroll
draft or voiding an invoice also invalidates the open approvals on it.
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from ..core.approvals import build_manifest
from ..core.db import register_schema_version
from ..core.ids import canonical_json, hash_json, loads, new_id, utcnow_iso
from ..core.money import ZERO, D, MoneyError, fmt, money, total

SCHEMA_NAME = "labor"
PLUGIN_NAME = "labor"
POSTING_RULE = "cipher-posting-rules/1"

OP_APPROVE_TIMESHEET = "labor.approve_timesheet"
OP_POST_PAYROLL = "labor.post_payroll"
OP_BILL = "labor.bill"

TIMESHEET_SUBJECT = "labor_timesheet"
PAYROLL_SUBJECT = "labor_payroll"
INVOICE_SUBJECT = "labor_invoice"
COLLECTION_SUBJECT = "labor_collection"

ACCOUNT_BANK = "1000"
ACCOUNT_AR = "1100"
ACCOUNT_ACCRUED_PAYROLL = "2200"
ACCOUNT_FEE_REVENUE = "4100"
ACCOUNT_LABOR_COST = "5300"
ACCOUNT_FEES = "6000"

HOURS_Q = Decimal("0.01")
PCT_Q = Decimal("0.01")
MAX_DAY_HOURS = Decimal("24")
ZERO_HOURS = Decimal("0.00")
# range limits keep every product and sum far inside exact decimal precision
MAX_RATE = Decimal("1000000.00")            # per hour
MAX_AMOUNT = Decimal("1000000000000.00")    # budgets, payroll runs, receipts
MAX_BUDGET_HOURS = Decimal("10000000.00")

# Receipt tables of the other receivables sources that credit control account 1100 (prime
# bills, prime retainage invoices, reimbursement billings).  ``record_collection`` refuses a
# reference already used in any of them or in labor_collections, ignoring case; a table that
# does not exist (its module is not loaded) is skipped.  The reverse check is each other
# module's own (see the module docstring).
OTHER_RECEIPT_TABLES = ("collections", "prime_retainage_collections", "reimbursement_collections")

LIVE_ENTRY_STATUSES = ("draft", "submitted", "approved", "billed")
UTILIZATION_STATUSES = ("submitted", "approved", "billed")
ACTUAL_STATUSES = ("approved", "billed")

SCHEMA_STATEMENTS = [
    # chart accounts reserved for this module
    "INSERT OR IGNORE INTO accounts (code, name, type, control_kind) VALUES ('2200', 'Accrued payroll', 'liability', 'accrued_payroll')",
    "INSERT OR IGNORE INTO accounts (code, name, type, control_kind) VALUES ('4100', 'Fee revenue', 'revenue', NULL)",
    "INSERT OR IGNORE INTO accounts (code, name, type, control_kind) VALUES ('5300', 'Project cost - labor', 'expense', NULL)",
    """CREATE TABLE labor_rates (
        id TEXT PRIMARY KEY,
        employee_id TEXT NOT NULL REFERENCES parties(id),
        effective_from TEXT NOT NULL CHECK (length(effective_from) = 10),
        cost_rate TEXT NOT NULL,
        bill_rate TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        used INTEGER NOT NULL DEFAULT 0 CHECK (used IN (0, 1)),
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (employee_id, effective_from)
    )""",
    """CREATE TABLE labor_phases (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        code TEXT NOT NULL COLLATE NOCASE,
        name TEXT NOT NULL,
        fee_budget_hours TEXT NOT NULL,
        fee_budget_amount TEXT NOT NULL,
        billable INTEGER NOT NULL CHECK (billable IN (0, 1)),
        version INTEGER NOT NULL DEFAULT 1,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (project_id, code)
    )""",
    """CREATE TABLE labor_timesheets (
        id TEXT PRIMARY KEY,
        employee_id TEXT NOT NULL REFERENCES parties(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        status TEXT NOT NULL CHECK (status IN ('submitted','rejected','approved')),
        version INTEGER NOT NULL DEFAULT 1,
        content_hash TEXT NOT NULL,
        lines_json TEXT NOT NULL,
        entry_count INTEGER NOT NULL,
        total_hours TEXT NOT NULL,
        total_cost TEXT NOT NULL,
        total_bill TEXT NOT NULL,
        submitted_by TEXT NOT NULL,
        submitted_at TEXT NOT NULL,
        rejected_by TEXT,
        rejected_at TEXT,
        reject_reason TEXT,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        approved_at TEXT
    )""",
    # one open (awaiting approval or returned for correction) timesheet per employee per period
    "CREATE UNIQUE INDEX labor_timesheets_one_open ON labor_timesheets (employee_id, period_id) WHERE status IN ('submitted','rejected')",
    """CREATE TABLE labor_entries (
        id TEXT PRIMARY KEY,
        employee_id TEXT NOT NULL REFERENCES parties(id),
        project_id TEXT NOT NULL REFERENCES projects(id),
        phase_id TEXT NOT NULL REFERENCES labor_phases(id),
        work_date TEXT NOT NULL CHECK (length(work_date) = 10),
        hours TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        rate_id TEXT NOT NULL REFERENCES labor_rates(id),
        cost_rate TEXT NOT NULL,
        bill_rate TEXT NOT NULL,
        cost_amount TEXT NOT NULL,
        bill_amount TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','submitted','approved','billed','void')),
        version INTEGER NOT NULL DEFAULT 1,
        timesheet_id TEXT REFERENCES labor_timesheets(id),
        void_reason TEXT,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX labor_entries_employee_day ON labor_entries (employee_id, work_date)",
    "CREATE INDEX labor_entries_timesheet ON labor_entries (timesheet_id)",
    """CREATE TABLE labor_payroll (
        id TEXT PRIMARY KEY,
        period_id TEXT NOT NULL REFERENCES periods(id),
        employee_id TEXT NOT NULL REFERENCES parties(id),
        gross_amount TEXT NOT NULL,
        reference TEXT NOT NULL COLLATE NOCASE,
        status TEXT NOT NULL CHECK (status IN ('draft','posted','canceled')),
        version INTEGER NOT NULL DEFAULT 1,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        posted_at TEXT,
        canceled_at TEXT,
        cancel_reason TEXT
    )""",
    # a payroll reference identifies one settlement and is never reused, not even after a cancel
    "CREATE UNIQUE INDEX labor_payroll_reference ON labor_payroll (reference)",
    """CREATE TABLE labor_invoices (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        customer_id TEXT NOT NULL REFERENCES parties(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        sequence INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','billed','void')),
        version INTEGER NOT NULL DEFAULT 1,
        content_hash TEXT NOT NULL,
        line_count INTEGER NOT NULL,
        total_hours TEXT NOT NULL,
        total TEXT NOT NULL,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        billed_at TEXT,
        voided_at TEXT,
        void_reason TEXT,
        UNIQUE (project_id, sequence)
    )""",
    """CREATE TABLE labor_invoice_lines (
        id TEXT PRIMARY KEY,
        invoice_id TEXT NOT NULL REFERENCES labor_invoices(id),
        entry_id TEXT NOT NULL REFERENCES labor_entries(id),
        phase_id TEXT NOT NULL REFERENCES labor_phases(id),
        employee_id TEXT NOT NULL REFERENCES parties(id),
        work_date TEXT NOT NULL,
        hours TEXT NOT NULL,
        bill_rate TEXT NOT NULL,
        amount TEXT NOT NULL,
        released INTEGER NOT NULL DEFAULT 0 CHECK (released IN (0, 1))
    )""",
    # an entry can sit on only one non-void invoice
    "CREATE UNIQUE INDEX labor_invoice_lines_one_live_invoice ON labor_invoice_lines (entry_id) WHERE released = 0",
    """CREATE TABLE labor_collections (
        id TEXT PRIMARY KEY,
        invoice_id TEXT NOT NULL REFERENCES labor_invoices(id),
        project_id TEXT NOT NULL REFERENCES projects(id),
        customer_id TEXT NOT NULL REFERENCES parties(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        amount TEXT NOT NULL,
        fee TEXT NOT NULL,
        provider_ref TEXT NOT NULL COLLATE NOCASE UNIQUE,
        journal_id TEXT NOT NULL REFERENCES journals(id),
        created_by TEXT NOT NULL,
        received_at TEXT NOT NULL
    )""",
    "CREATE INDEX labor_collections_invoice ON labor_collections (invoice_id)",
    # ---- rates ----
    "CREATE TRIGGER labor_rates_no_delete BEFORE DELETE ON labor_rates BEGIN SELECT RAISE(ABORT, 'labor rates are never deleted; add a new effective date'); END",
    """CREATE TRIGGER labor_rates_identity_immutable BEFORE UPDATE ON labor_rates
        WHEN NEW.employee_id IS NOT OLD.employee_id OR NEW.effective_from IS NOT OLD.effective_from
        BEGIN SELECT RAISE(ABORT, 'a labor rate keeps its employee and effective date; add a new effective date instead'); END""",
    # "used" is sticky: set the first time any entry is priced at the rate, never cleared (a void or re-rated entry still used it)
    """CREATE TRIGGER labor_rates_used_sticky BEFORE UPDATE OF used ON labor_rates
        WHEN NEW.used IS NOT OLD.used AND NOT (OLD.used = 0 AND NEW.used = 1)
        BEGIN SELECT RAISE(ABORT, 'a labor rate that time has been priced at stays marked as used'); END""",
    """CREATE TRIGGER labor_rates_frozen_once_used BEFORE UPDATE ON labor_rates
        WHEN (OLD.used = 1 OR EXISTS (SELECT 1 FROM labor_entries WHERE rate_id = OLD.id))
         AND (NEW.cost_rate IS NOT OLD.cost_rate OR NEW.bill_rate IS NOT OLD.bill_rate OR NEW.version IS NOT OLD.version
              OR NEW.created_by IS NOT OLD.created_by OR NEW.created_at IS NOT OLD.created_at OR NEW.updated_at IS NOT OLD.updated_at)
        BEGIN SELECT RAISE(ABORT, 'a labor rate is immutable once time has been logged at it; add a new effective date instead'); END""",
    """CREATE TRIGGER labor_rates_mark_used_on_entry_insert AFTER INSERT ON labor_entries
        BEGIN UPDATE labor_rates SET used = 1 WHERE id = NEW.rate_id AND used = 0; END""",
    """CREATE TRIGGER labor_rates_mark_used_on_entry_rerate AFTER UPDATE OF rate_id ON labor_entries
        BEGIN UPDATE labor_rates SET used = 1 WHERE id = NEW.rate_id AND used = 0; END""",
    # ---- phases ----
    "CREATE TRIGGER labor_phases_no_delete BEFORE DELETE ON labor_phases BEGIN SELECT RAISE(ABORT, 'labor phases are never deleted'); END",
    """CREATE TRIGGER labor_phases_identity_immutable BEFORE UPDATE ON labor_phases
        WHEN NEW.project_id IS NOT OLD.project_id OR NEW.code IS NOT OLD.code OR NEW.billable IS NOT OLD.billable
        BEGIN SELECT RAISE(ABORT, 'a labor phase keeps its project, code and billable flag'); END""",
    # ---- entries ----
    "CREATE TRIGGER labor_entries_no_delete BEFORE DELETE ON labor_entries BEGIN SELECT RAISE(ABORT, 'time entries are never deleted; void a draft instead'); END",
    """CREATE TRIGGER labor_entries_born_draft BEFORE INSERT ON labor_entries
        WHEN NEW.status != 'draft' OR NEW.timesheet_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'a time entry is created as an unsubmitted draft'); END""",
    """CREATE TRIGGER labor_entries_phase_in_project_insert BEFORE INSERT ON labor_entries
        WHEN (SELECT project_id FROM labor_phases WHERE id = NEW.phase_id) IS NOT NEW.project_id
        BEGIN SELECT RAISE(ABORT, 'a time entry phase must belong to the entry project'); END""",
    """CREATE TRIGGER labor_entries_phase_in_project_update BEFORE UPDATE OF phase_id, project_id ON labor_entries
        WHEN (SELECT project_id FROM labor_phases WHERE id = NEW.phase_id) IS NOT NEW.project_id
        BEGIN SELECT RAISE(ABORT, 'a time entry phase must belong to the entry project'); END""",
    """CREATE TRIGGER labor_entries_frozen_unless_draft BEFORE UPDATE ON labor_entries
        WHEN OLD.status != 'draft' AND (
            NEW.employee_id IS NOT OLD.employee_id OR NEW.project_id IS NOT OLD.project_id OR NEW.phase_id IS NOT OLD.phase_id
            OR NEW.work_date IS NOT OLD.work_date OR NEW.hours IS NOT OLD.hours OR NEW.note IS NOT OLD.note
            OR NEW.rate_id IS NOT OLD.rate_id OR NEW.cost_rate IS NOT OLD.cost_rate OR NEW.bill_rate IS NOT OLD.bill_rate
            OR NEW.cost_amount IS NOT OLD.cost_amount OR NEW.bill_amount IS NOT OLD.bill_amount OR NEW.version IS NOT OLD.version
        )
        BEGIN SELECT RAISE(ABORT, 'only draft time entries can be edited'); END""",
    """CREATE TRIGGER labor_entries_status_forward_only BEFORE UPDATE OF status ON labor_entries
        WHEN NEW.status != OLD.status AND NOT (
            (OLD.status = 'draft' AND NEW.status IN ('submitted','void'))
            OR (OLD.status = 'submitted' AND NEW.status IN ('draft','approved'))
            OR (OLD.status = 'approved' AND NEW.status = 'billed')
        )
        BEGIN SELECT RAISE(ABORT, 'illegal time entry status transition'); END""",
    # ---- timesheets ----
    "CREATE TRIGGER labor_timesheets_no_delete BEFORE DELETE ON labor_timesheets BEGIN SELECT RAISE(ABORT, 'timesheets are never deleted'); END",
    """CREATE TRIGGER labor_timesheets_born_submitted BEFORE INSERT ON labor_timesheets
        WHEN NEW.status != 'submitted' OR NEW.journal_id IS NOT NULL OR NEW.approval_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'a timesheet is created as submitted, without a journal'); END""",
    """CREATE TRIGGER labor_timesheets_approved_immutable BEFORE UPDATE ON labor_timesheets
        WHEN OLD.status = 'approved'
        BEGIN SELECT RAISE(ABORT, 'an approved timesheet is immutable'); END""",
    """CREATE TRIGGER labor_timesheets_status_forward_only BEFORE UPDATE OF status ON labor_timesheets
        WHEN NEW.status != OLD.status AND NOT (
            (OLD.status = 'submitted' AND NEW.status IN ('approved','rejected'))
            OR (OLD.status = 'rejected' AND NEW.status = 'submitted')
        )
        BEGIN SELECT RAISE(ABORT, 'illegal timesheet status transition'); END""",
    """CREATE TRIGGER labor_timesheets_content_frozen BEFORE UPDATE ON labor_timesheets
        WHEN NEW.employee_id IS NOT OLD.employee_id OR NEW.period_id IS NOT OLD.period_id
          OR ((NEW.content_hash IS NOT OLD.content_hash OR NEW.lines_json IS NOT OLD.lines_json OR NEW.total_cost IS NOT OLD.total_cost
               OR NEW.total_hours IS NOT OLD.total_hours OR NEW.total_bill IS NOT OLD.total_bill OR NEW.entry_count IS NOT OLD.entry_count
               OR NEW.version IS NOT OLD.version)
              AND NOT (OLD.status = 'rejected' AND NEW.status = 'submitted'))
        BEGIN SELECT RAISE(ABORT, 'timesheet content changes only by resubmission after rejection'); END""",
    # ---- payroll ----
    "CREATE TRIGGER labor_payroll_no_delete BEFORE DELETE ON labor_payroll BEGIN SELECT RAISE(ABORT, 'payroll records are never deleted; cancel a draft instead'); END",
    """CREATE TRIGGER labor_payroll_born_draft BEFORE INSERT ON labor_payroll
        WHEN NEW.status != 'draft' OR NEW.journal_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'a payroll settlement is recorded as a draft'); END""",
    """CREATE TRIGGER labor_payroll_final_immutable BEFORE UPDATE ON labor_payroll
        WHEN OLD.status IN ('posted','canceled')
        BEGIN SELECT RAISE(ABORT, 'posted or canceled payroll records are immutable'); END""",
    """CREATE TRIGGER labor_payroll_content_frozen BEFORE UPDATE ON labor_payroll
        WHEN NEW.period_id IS NOT OLD.period_id OR NEW.employee_id IS NOT OLD.employee_id
          OR NEW.gross_amount IS NOT OLD.gross_amount OR NEW.reference IS NOT OLD.reference
        BEGIN SELECT RAISE(ABORT, 'a payroll record is corrected by canceling the draft and recording it again'); END""",
    """CREATE TRIGGER labor_payroll_status_forward_only BEFORE UPDATE OF status ON labor_payroll
        WHEN NEW.status != OLD.status AND NOT (OLD.status = 'draft' AND NEW.status IN ('posted','canceled'))
        BEGIN SELECT RAISE(ABORT, 'illegal payroll status transition'); END""",
    # ---- invoices ----
    "CREATE TRIGGER labor_invoices_no_delete BEFORE DELETE ON labor_invoices BEGIN SELECT RAISE(ABORT, 'labor invoices are never deleted; void a draft instead'); END",
    """CREATE TRIGGER labor_invoices_born_draft BEFORE INSERT ON labor_invoices
        WHEN NEW.status != 'draft' OR NEW.journal_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'a labor invoice is prepared as a draft'); END""",
    """CREATE TRIGGER labor_invoices_final_immutable BEFORE UPDATE ON labor_invoices
        WHEN OLD.status IN ('billed','void')
        BEGIN SELECT RAISE(ABORT, 'billed or void labor invoices are immutable'); END""",
    """CREATE TRIGGER labor_invoices_content_frozen BEFORE UPDATE ON labor_invoices
        WHEN NEW.project_id IS NOT OLD.project_id OR NEW.customer_id IS NOT OLD.customer_id OR NEW.period_id IS NOT OLD.period_id
          OR NEW.sequence IS NOT OLD.sequence OR NEW.content_hash IS NOT OLD.content_hash OR NEW.total IS NOT OLD.total
          OR NEW.total_hours IS NOT OLD.total_hours OR NEW.line_count IS NOT OLD.line_count
        BEGIN SELECT RAISE(ABORT, 'a labor invoice is corrected by voiding the draft and preparing it again'); END""",
    """CREATE TRIGGER labor_invoices_status_forward_only BEFORE UPDATE OF status ON labor_invoices
        WHEN NEW.status != OLD.status AND NOT (OLD.status = 'draft' AND NEW.status IN ('billed','void'))
        BEGIN SELECT RAISE(ABORT, 'illegal labor invoice status transition'); END""",
    "CREATE TRIGGER labor_invoice_lines_no_delete BEFORE DELETE ON labor_invoice_lines BEGIN SELECT RAISE(ABORT, 'labor invoice lines are never deleted'); END",
    """CREATE TRIGGER labor_invoice_lines_insert_guard BEFORE INSERT ON labor_invoice_lines
        WHEN NEW.released != 0
          OR (SELECT status FROM labor_entries WHERE id = NEW.entry_id) IS NOT 'approved'
          OR (SELECT status FROM labor_invoices WHERE id = NEW.invoice_id) IS NOT 'draft'
          OR (SELECT project_id FROM labor_entries WHERE id = NEW.entry_id) IS NOT (SELECT project_id FROM labor_invoices WHERE id = NEW.invoice_id)
        BEGIN SELECT RAISE(ABORT, 'only approved, unbilled time of the same project can be reserved, and only on a draft invoice'); END""",
    """CREATE TRIGGER labor_invoice_lines_release_only BEFORE UPDATE ON labor_invoice_lines
        WHEN NEW.invoice_id IS NOT OLD.invoice_id OR NEW.entry_id IS NOT OLD.entry_id OR NEW.phase_id IS NOT OLD.phase_id
          OR NEW.employee_id IS NOT OLD.employee_id OR NEW.work_date IS NOT OLD.work_date OR NEW.hours IS NOT OLD.hours
          OR NEW.bill_rate IS NOT OLD.bill_rate OR NEW.amount IS NOT OLD.amount
          OR OLD.released = 1 OR NEW.released != 1
          OR (SELECT status FROM labor_invoices WHERE id = OLD.invoice_id) IS NOT 'void'
        BEGIN SELECT RAISE(ABORT, 'labor invoice lines are immutable; a line is only released when its draft invoice is voided'); END""",
    # ---- collections ----
    "CREATE TRIGGER labor_collections_no_delete BEFORE DELETE ON labor_collections BEGIN SELECT RAISE(ABORT, 'labor collections are never deleted'); END",
    "CREATE TRIGGER labor_collections_immutable BEFORE UPDATE ON labor_collections BEGIN SELECT RAISE(ABORT, 'labor collections are immutable once recorded'); END",
    """CREATE TRIGGER labor_collections_billed_invoice_only BEFORE INSERT ON labor_collections
        WHEN (SELECT status FROM labor_invoices WHERE id = NEW.invoice_id) IS NOT 'billed'
          OR (SELECT project_id FROM labor_invoices WHERE id = NEW.invoice_id) IS NOT NEW.project_id
          OR (SELECT customer_id FROM labor_invoices WHERE id = NEW.invoice_id) IS NOT NEW.customer_id
        BEGIN SELECT RAISE(ABORT, 'a collection is recorded only against a billed labor invoice, for its project and customer'); END""",
]


def _cents(expr: str) -> str:
    """SQL integer cents of a two-place money string (exact; never REAL arithmetic)."""
    return f"CAST(REPLACE({expr}, '.', '') AS INTEGER)"


def _two_place(expr: str) -> str:
    """SQL test that a value is a non-negative money string with exactly two decimals."""
    return f"(typeof({expr}) = 'text' AND {expr} GLOB '[0-9]*.[0-9][0-9]' AND {expr} NOT GLOB '*[^0-9.]*' AND {expr} NOT GLOB '*.*.*')"


# Collection rules in the database, as their own catalog entry (``labor`` is applied history).
# ``record_collection`` already enforces them in Python; this makes a raw INSERT obey them
# too: exact two-place amount and fee (amount positive, fee below it), never in a period
# that starts before the invoice's billing period, never on an invoice whose billing
# journal was reversed, only with the row's own collection journal crediting 1100 by
# exactly its amount, and never above the invoice's open amount (billed total less the
# collections whose journals were not reversed).
COLLECTION_GUARDS_SCHEMA_NAME = "labor_collection_guards"
COLLECTION_GUARDS_SCHEMA_STATEMENTS = [
    f"""CREATE TRIGGER labor_collections_within_the_invoice BEFORE INSERT ON labor_collections
        BEGIN
            SELECT CASE
                WHEN NOT {_two_place('NEW.amount')} OR NOT {_two_place('NEW.fee')}
                  OR {_cents('NEW.amount')} <= 0 OR {_cents('NEW.fee')} >= {_cents('NEW.amount')}
                THEN RAISE(ABORT, 'a labor collection amount and fee are exact two-place money, the amount positive and the fee below it')
                WHEN (SELECT start_date FROM periods WHERE id = NEW.period_id)
                     < (SELECT p.start_date FROM labor_invoices i JOIN periods p ON p.id = i.period_id WHERE i.id = NEW.invoice_id)
                THEN RAISE(ABORT, 'a labor collection is never recorded in a period that starts before the invoice billing period')
                WHEN EXISTS (SELECT 1 FROM labor_invoices i JOIN journals r ON r.reversal_of = i.journal_id WHERE i.id = NEW.invoice_id)
                THEN RAISE(ABORT, 'a labor collection is never recorded against an invoice whose billing journal was reversed')
                WHEN (SELECT source_type FROM journals WHERE id = NEW.journal_id) IS NOT '{COLLECTION_SUBJECT}'
                  OR (SELECT source_id FROM journals WHERE id = NEW.journal_id) IS NOT NEW.id
                  OR (SELECT SUM({_cents('credit')}) - SUM({_cents('debit')}) FROM journal_lines
                      WHERE journal_id = NEW.journal_id AND account_code = '{ACCOUNT_AR}') IS NOT {_cents('NEW.amount')}
                THEN RAISE(ABORT, 'a labor collection carries its own collection journal, which credits 1100 by exactly its amount')
                WHEN {_cents('NEW.amount')} + COALESCE((SELECT SUM({_cents('c.amount')}) FROM labor_collections c
                         WHERE c.invoice_id = NEW.invoice_id AND NOT EXISTS (SELECT 1 FROM journals r WHERE r.reversal_of = c.journal_id)), 0)
                     > (SELECT {_cents('total')} FROM labor_invoices WHERE id = NEW.invoice_id)
                THEN RAISE(ABORT, 'a labor collection never exceeds the open amount of its invoice')
            END;
        END""",
]

# Registered here, in this order, so the guard entry always sits after the table it guards;
# the plugin loader's own registration of SCHEMA_NAME is then a no-op.
register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)
register_schema_version(COLLECTION_GUARDS_SCHEMA_NAME, COLLECTION_GUARDS_SCHEMA_STATEMENTS)


class LaborError(RuntimeError):
    """Invalid labor input or an action the record's state does not allow."""


# --------------------------------------------------------------------------- #
# Pure helpers                                                                 #
# --------------------------------------------------------------------------- #

def _decimal(value, label: str) -> Decimal:
    if isinstance(value, float):
        raise LaborError(f"{label} must be a string, int or Decimal, not a binary float")
    try:
        d = D(value)
    except MoneyError as exc:
        raise LaborError(f"{label} is not an exact decimal: {exc}") from exc
    if not d.is_finite():
        raise LaborError(f"{label} must be a finite number")
    return d


def _hours(value, label: str = "hours", *, allow_zero: bool = False, cap: Decimal | None = MAX_DAY_HOURS) -> Decimal:
    h = _decimal(value, label)
    try:
        q = h.quantize(HOURS_Q)
    except InvalidOperation as exc:
        raise LaborError(f"{label} is out of range: {value!r}") from exc
    if q != h:
        raise LaborError(f"{label} are recorded to the hundredth of an hour, got {value!r}")
    if q < 0 or (q == 0 and not allow_zero):
        raise LaborError(f"{label} must be greater than zero, got {_fmt_h(q)}")
    if cap is not None and q > cap:
        raise LaborError(f"{label} cannot exceed {_fmt_h(cap)}, got {_fmt_h(q)}")
    return q


def _amount(value, label: str, *, allow_zero: bool, cap: Decimal = MAX_AMOUNT) -> Decimal:
    d = _decimal(value, label)
    try:
        m = money(d)
    except InvalidOperation as exc:
        raise LaborError(f"{label} is out of range: {value!r}") from exc
    if m != d:
        raise LaborError(f"{label} must be in whole cents, got {value!r}")
    if m < 0 or (m == 0 and not allow_zero):
        raise LaborError(f"{label} must be {'zero or ' if allow_zero else ''}positive, got {fmt(m)}")
    if m > cap:
        raise LaborError(f"{label} {fmt(m)} is out of range (at most {fmt(cap)})")
    return m


def _date(value, label: str = "date") -> str:
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise LaborError(f"{label} must be YYYY-MM-DD, got {value!r}")
    try:
        return _dt.date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise LaborError(f"{label} is not a valid calendar date: {value!r}") from exc


def _text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LaborError(f"{label} is required and must be a non-empty string")
    return value.strip()


def _note(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise LaborError("note must be a string")
    return value.strip()


def _fmt_h(value) -> str:
    return f"{D(value).quantize(HOURS_Q):f}"


def _sum_hours(values) -> Decimal:
    acc = ZERO_HOURS
    for v in values:
        acc += D(v)
    return acc.quantize(HOURS_Q)


def _pct(part, whole) -> str | None:
    """``part / whole`` as a percentage string to two places; None when the
    whole is zero but the part is not (an unbudgeted overrun)."""
    p, w = D(part), D(whole)
    if w == 0:
        return "0.00" if p == 0 else None
    return f"{(p * 100 / w).quantize(PCT_Q, rounding=ROUND_HALF_UP):f}"


_ENTRY_SELECT = """SELECT e.*, p.code AS phase_code, p.billable AS phase_billable,
        (SELECT l.invoice_id FROM labor_invoice_lines l WHERE l.entry_id = e.id AND l.released = 0) AS invoice_id
    FROM labor_entries e JOIN labor_phases p ON p.id = e.phase_id"""


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

    # ---- master-data lookups --------------------------------------------- #

    def _employee(self, employee_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM parties WHERE id=?", (employee_id,))
        if row is None:
            raise LaborError(f"unknown party {employee_id}")
        if row["kind"] != "employee":
            raise LaborError(f"party {employee_id} is a {row['kind']}, not an employee")
        return row

    def _project(self, project_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM projects WHERE id=?", (project_id,))
        if row is None:
            raise LaborError(f"unknown project {project_id}")
        return row

    def _period(self, period_id: str, *, require_open: bool = False, purpose: str = "") -> dict[str, Any]:
        row = self.db.one("SELECT * FROM periods WHERE id=?", (period_id,))
        if row is None:
            raise LaborError(f"unknown period {period_id}")
        if require_open and row["status"] != "open":
            raise LaborError(f"period {period_id} is {row['status']}; {purpose or 'it no longer accepts labor records'}")
        return row

    def _customer(self, party_id: str | None, project_id: str) -> dict[str, Any]:
        """The party T&M time on ``project_id`` is billed to: it must exist and be a customer."""
        if not party_id:
            raise LaborError(f"project {project_id} has no customer to invoice")
        row = self.db.one("SELECT * FROM parties WHERE id=?", (party_id,))
        if row is None:
            raise LaborError(f"project {project_id} customer {party_id} is not a known party")
        if row["kind"] != "customer":
            raise LaborError(f"project {project_id} customer {party_id} is a {row['kind']}, not a customer; T&M time is billed only to a customer party")
        return row

    def _require_recordable_date(self, day: str) -> None:
        """Refuse a work date that lies only in closed or locked periods: time dated there could
        never be submitted or costed.  A date no period covers yet is allowed."""
        rows = self.db.query("SELECT id, status FROM periods WHERE start_date <= ? AND end_date >= ? ORDER BY start_date, id", (day, day))
        if rows and not any(r["status"] == "open" for r in rows):
            where = ", ".join(f"{r['id']} ({r['status']})" for r in rows)
            raise LaborError(f"work date {day} falls in period {where}; time can no longer be recorded there")

    @staticmethod
    def _check_period_arg(period_id: str | None, record_period: str, what: str) -> None:
        if period_id is not None and period_id != record_period:
            raise LaborError(f"{what} belongs to period {record_period} and posts there, not in {period_id}")

    # ---- rates -------------------------------------------------------------- #

    def set_rate(self, employee_id: str, effective_from: str, cost_rate, bill_rate, *, actor: str) -> dict[str, Any]:
        """Add an effective-dated cost/bill rate for an employee.

        A date earlier than time already logged is allowed: draft time it now governs is
        re-rated; approved or billed time keeps the rate it was approved at (its cost is
        posted); it is refused while submitted time it would govern awaits approval."""
        eff = _date(effective_from, "effective_from")
        cost = _amount(cost_rate, "cost rate", allow_zero=False, cap=MAX_RATE)
        bill = _amount(bill_rate, "bill rate", allow_zero=True, cap=MAX_RATE)
        rate_id = new_id("lrate")
        with self.db.transaction() as conn:
            self._employee(employee_id)
            if self.db.one("SELECT id FROM labor_rates WHERE employee_id=? AND effective_from=?", (employee_id, eff)) is not None:
                raise LaborError(f"employee {employee_id} already has a rate effective {eff}; rates are effective-dated, so add a different date")
            # live time on or after this date currently priced at an EARLIER rate is now governed by this one
            affected = self.db.query(
                _ENTRY_SELECT + " JOIN labor_rates r ON r.id = e.rate_id"
                " WHERE e.employee_id=? AND e.status != 'void' AND e.work_date >= ? AND r.effective_from < ? ORDER BY e.work_date, e.id",
                (employee_id, eff, eff),
            )
            awaiting = [e for e in affected if e["status"] == "submitted"]
            if awaiting:
                raise LaborError(
                    f"a rate effective {eff} would govern {len(awaiting)} submitted time entr{'y' if len(awaiting) == 1 else 'ies'} "
                    f"(first on {awaiting[0]['work_date']}, timesheet {awaiting[0]['timesheet_id']}) that await approval at the old rate; "
                    "reject that timesheet first so its time is re-rated before approval, or choose a later effective date"
                )
            kept = [e["id"] for e in affected if e["status"] in ACTUAL_STATUSES]
            now = utcnow_iso()
            conn.execute(
                "INSERT INTO labor_rates (id, employee_id, effective_from, cost_rate, bill_rate, version, used, created_by, created_at, updated_at) VALUES (?,?,?,?,?,1,0,?,?,?)",
                (rate_id, employee_id, eff, fmt(cost), fmt(bill), actor, now, now),
            )
            rate = self.rate(rate_id)
            rerated = [self._rerate_draft(e, rate, actor=actor) for e in affected if e["status"] == "draft"]
            self.audit.record(actor, "labor.rate_set", "labor_rate", rate_id, {
                "employee_id": employee_id, "effective_from": eff, "cost_rate": fmt(cost), "bill_rate": fmt(bill),
                "rerated_draft_entries": rerated, "approved_entries_keeping_their_rate": kept,
            })
        return self.rate(rate_id)

    def _rerate_draft(self, entry: dict[str, Any], rate: dict[str, Any], *, actor: str) -> str:
        """Caller holds the transaction; ``entry`` is a draft now governed by ``rate``."""
        hours = D(entry["hours"])
        cost, bill = self._price(hours, rate)
        self.db.execute(
            "UPDATE labor_entries SET rate_id=?, cost_rate=?, bill_rate=?, cost_amount=?, bill_amount=?, version=version+1, updated_at=? WHERE id=?",
            (rate["id"], rate["cost_rate"], rate["bill_rate"], fmt(cost), fmt(bill), utcnow_iso(), entry["id"]),
        )
        self.audit.record(actor, "labor.entry_rerated", "labor_entry", entry["id"], {
            "old_rate_id": entry["rate_id"], "new_rate_id": rate["id"], "cost_amount": fmt(cost), "bill_amount": fmt(bill), "version": entry["version"] + 1,
        })
        return entry["id"]

    def update_rate(self, rate_id: str, *, actor: str, cost_rate=None, bill_rate=None) -> dict[str, Any]:
        """Correct a rate that no time entry has ever been priced at (voided and re-rated
        entries count: once used, a rate is immutable)."""
        if cost_rate is None and bill_rate is None:
            raise LaborError("nothing to update")
        with self.db.transaction() as conn:
            r = self.rate(rate_id)
            current = self.db.scalar("SELECT COUNT(*) FROM labor_entries WHERE rate_id=?", (rate_id,)) or 0
            if r["used"] or current:
                raise LaborError(
                    f"rate {rate_id} has been used to price time (including voided or re-rated entries) and is immutable; "
                    "add a new effective date instead"
                )
            cost = _amount(cost_rate, "cost rate", allow_zero=False, cap=MAX_RATE) if cost_rate is not None else money(r["cost_rate"])
            bill = _amount(bill_rate, "bill rate", allow_zero=True, cap=MAX_RATE) if bill_rate is not None else money(r["bill_rate"])
            conn.execute(
                "UPDATE labor_rates SET cost_rate=?, bill_rate=?, version=version+1, updated_at=? WHERE id=?",
                (fmt(cost), fmt(bill), utcnow_iso(), rate_id),
            )
            self.audit.record(actor, "labor.rate_updated", "labor_rate", rate_id, {
                "before": {"cost_rate": r["cost_rate"], "bill_rate": r["bill_rate"]}, "after": {"cost_rate": fmt(cost), "bill_rate": fmt(bill)}, "version": r["version"] + 1,
            })
        return self.rate(rate_id)

    def rate(self, rate_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM labor_rates WHERE id=?", (rate_id,))
        if row is None:
            raise LaborError(f"unknown labor rate {rate_id}")
        row["used"] = bool(row["used"])
        return row

    def rates(self, employee_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM labor_rates WHERE employee_id=? ORDER BY effective_from", (employee_id,))
        for r in rows:
            r["used"] = bool(r["used"])
        return rows

    def rate_for(self, employee_id: str, work_date: str) -> dict[str, Any]:
        """The rate with the latest effective date on or before ``work_date``."""
        day = _date(work_date, "work_date")
        row = self.db.one(
            "SELECT * FROM labor_rates WHERE employee_id=? AND effective_from <= ? ORDER BY effective_from DESC LIMIT 1",
            (employee_id, day),
        )
        if row is None:
            raise LaborError(f"employee {employee_id} has no labor rate effective on {day}")
        return row

    @staticmethod
    def _price(hours: Decimal, rate: dict[str, Any]) -> tuple[Decimal, Decimal]:
        try:
            cost = money(hours * D(rate["cost_rate"]))
            bill = money(hours * D(rate["bill_rate"]))
        except (InvalidOperation, MoneyError) as exc:
            raise LaborError(f"{_fmt_h(hours)} h at cost rate {rate['cost_rate']} / bill rate {rate['bill_rate']} is out of range") from exc
        if cost <= 0:
            raise LaborError(f"{_fmt_h(hours)} h at cost rate {rate['cost_rate']} rounds to no cost; record time in larger units")
        return cost, bill

    # ---- phases and fee budgets --------------------------------------------- #

    def add_phase(self, project_id: str, code: str, name: str, fee_budget_hours, fee_budget_amount, billable: bool = True, *, actor: str) -> dict[str, Any]:
        code = _text(code, "phase code")
        name = _text(name, "phase name")
        budget_hours = _hours(fee_budget_hours, "fee budget hours", allow_zero=True, cap=MAX_BUDGET_HOURS)
        budget_amount = _amount(fee_budget_amount, "fee budget amount", allow_zero=True)
        if not isinstance(billable, bool):
            raise LaborError("billable must be True or False")
        phase_id = new_id("lphs")
        with self.db.transaction() as conn:
            self._project(project_id)
            if self.db.one("SELECT id FROM labor_phases WHERE project_id=? AND code = ? COLLATE NOCASE", (project_id, code)) is not None:
                raise LaborError(f"project {project_id} already has a phase coded {code!r}")
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO labor_phases (id, project_id, code, name, fee_budget_hours, fee_budget_amount, billable, version, created_by, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,1,?,?,?)""",
                (phase_id, project_id, code, name, _fmt_h(budget_hours), fmt(budget_amount), 1 if billable else 0, actor, now, now),
            )
            self.audit.record(actor, "labor.phase_added", "labor_phase", phase_id, {
                "project_id": project_id, "code": code, "name": name, "fee_budget_hours": _fmt_h(budget_hours), "fee_budget_amount": fmt(budget_amount), "billable": billable,
            })
        return self.phase(phase_id)

    def update_phase(self, phase_id: str, *, actor: str, name: str | None = None, fee_budget_hours=None, fee_budget_amount=None) -> dict[str, Any]:
        """Rename a phase or revise its fee budget.  Code, project and billable flag are fixed."""
        if name is None and fee_budget_hours is None and fee_budget_amount is None:
            raise LaborError("nothing to update")
        with self.db.transaction() as conn:
            ph = self.phase(phase_id)
            changes: dict[str, Any] = {}
            if name is not None:
                changes["name"] = _text(name, "phase name")
            if fee_budget_hours is not None:
                changes["fee_budget_hours"] = _fmt_h(_hours(fee_budget_hours, "fee budget hours", allow_zero=True, cap=MAX_BUDGET_HOURS))
            if fee_budget_amount is not None:
                changes["fee_budget_amount"] = fmt(_amount(fee_budget_amount, "fee budget amount", allow_zero=True))
            merged = {**ph, **changes}
            conn.execute(
                "UPDATE labor_phases SET name=?, fee_budget_hours=?, fee_budget_amount=?, version=version+1, updated_at=? WHERE id=?",
                (merged["name"], merged["fee_budget_hours"], merged["fee_budget_amount"], utcnow_iso(), phase_id),
            )
            self.audit.record(actor, "labor.phase_updated", "labor_phase", phase_id, {"changes": changes, "version": ph["version"] + 1})
        return self.phase(phase_id)

    def phase(self, phase_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM labor_phases WHERE id=?", (phase_id,))
        if row is None:
            raise LaborError(f"unknown labor phase {phase_id}")
        row["billable"] = bool(row["billable"])
        return row

    def phases(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM labor_phases WHERE project_id=? ORDER BY code", (project_id,))
        for r in rows:
            r["billable"] = bool(r["billable"])
        return rows

    # ---- time entries ------------------------------------------------------- #

    def _check_day_capacity(self, employee_id: str, work_date: str, hours: Decimal, *, exclude: str | None = None) -> None:
        sql = "SELECT hours FROM labor_entries WHERE employee_id=? AND work_date=? AND status != 'void'"
        params: list[Any] = [employee_id, work_date]
        if exclude is not None:
            sql += " AND id != ?"
            params.append(exclude)
        used = _sum_hours(r["hours"] for r in self.db.query(sql, tuple(params)))
        if used + hours > MAX_DAY_HOURS:
            raise LaborError(
                f"employee {employee_id} already has {_fmt_h(used)} h on {work_date}; adding {_fmt_h(hours)} h would exceed "
                f"{_fmt_h(MAX_DAY_HOURS)} h in one day"
            )

    def _phase_in_project(self, phase_id: str, project_id: str) -> dict[str, Any]:
        ph = self.phase(phase_id)
        if ph["project_id"] != project_id:
            raise LaborError(f"phase {phase_id} belongs to project {ph['project_id']}, not {project_id}")
        return ph

    def log_time(self, employee_id: str, project_id: str, phase_id: str, work_date: str, hours, note: str = "", *, actor: str) -> dict[str, Any]:
        """Record a draft time entry priced at the rate effective on ``work_date``."""
        day = _date(work_date, "work_date")
        h = _hours(hours)
        text = _note(note)
        entry_id = new_id("ltim")
        with self.db.transaction() as conn:
            self._employee(employee_id)
            self._project(project_id)
            self._phase_in_project(phase_id, project_id)
            self._require_recordable_date(day)
            rate = self.rate_for(employee_id, day)
            cost, bill = self._price(h, rate)
            self._check_day_capacity(employee_id, day, h)
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO labor_entries (id, employee_id, project_id, phase_id, work_date, hours, note, rate_id, cost_rate, bill_rate,
                       cost_amount, bill_amount, status, version, created_by, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'draft',1,?,?,?)""",
                (entry_id, employee_id, project_id, phase_id, day, _fmt_h(h), text, rate["id"], rate["cost_rate"], rate["bill_rate"],
                 fmt(cost), fmt(bill), actor, now, now),
            )
            self.audit.record(actor, "labor.time_logged", "labor_entry", entry_id, {
                "employee_id": employee_id, "project_id": project_id, "phase_id": phase_id, "work_date": day, "hours": _fmt_h(h),
                "rate_id": rate["id"], "cost_amount": fmt(cost), "bill_amount": fmt(bill),
            })
        return self.entry(entry_id)

    def update_entry(self, entry_id: str, *, actor: str, hours=None, work_date: str | None = None, phase_id: str | None = None, note: str | None = None) -> dict[str, Any]:
        """Edit a draft entry; the rate and amounts are recomputed and the version bumped."""
        if hours is None and work_date is None and phase_id is None and note is None:
            raise LaborError("nothing to update")
        with self.db.transaction() as conn:
            row = self._entry_row(entry_id)
            if row["status"] != "draft":
                raise LaborError(f"time entry {entry_id} is {row['status']}; only draft entries can be edited (reject the timesheet to return it to draft)")
            new_hours = _hours(hours) if hours is not None else D(row["hours"])
            new_day = _date(work_date, "work_date") if work_date is not None else row["work_date"]
            new_phase = phase_id if phase_id is not None else row["phase_id"]
            self._phase_in_project(new_phase, row["project_id"])
            self._require_recordable_date(new_day)
            new_note = _note(note) if note is not None else row["note"]
            rate = self.rate_for(row["employee_id"], new_day)
            cost, bill = self._price(new_hours, rate)
            self._check_day_capacity(row["employee_id"], new_day, new_hours, exclude=entry_id)
            version = row["version"] + 1
            conn.execute(
                """UPDATE labor_entries SET hours=?, work_date=?, phase_id=?, note=?, rate_id=?, cost_rate=?, bill_rate=?, cost_amount=?, bill_amount=?,
                       version=?, updated_at=? WHERE id=?""",
                (_fmt_h(new_hours), new_day, new_phase, new_note, rate["id"], rate["cost_rate"], rate["bill_rate"], fmt(cost), fmt(bill), version, utcnow_iso(), entry_id),
            )
            self.audit.record(actor, "labor.entry_updated", "labor_entry", entry_id, {
                "before": {k: row[k] for k in ("hours", "work_date", "phase_id", "note", "rate_id", "cost_amount", "bill_amount")},
                "after": {"hours": _fmt_h(new_hours), "work_date": new_day, "phase_id": new_phase, "note": new_note, "rate_id": rate["id"], "cost_amount": fmt(cost), "bill_amount": fmt(bill)},
                "version": version,
            })
        return self.entry(entry_id)

    def delete_entry(self, entry_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        """Void a draft entry.  Rows are never deleted."""
        with self.db.transaction() as conn:
            row = self._entry_row(entry_id)
            if row["status"] != "draft":
                raise LaborError(f"time entry {entry_id} is {row['status']}; only draft entries can be deleted")
            conn.execute(
                "UPDATE labor_entries SET status='void', void_reason=?, version=version+1, updated_at=? WHERE id=?",
                (_note(reason), utcnow_iso(), entry_id),
            )
            self.audit.record(actor, "labor.entry_voided", "labor_entry", entry_id, {"reason": _note(reason), "hours": row["hours"], "work_date": row["work_date"]})
        return self.entry(entry_id)

    def _entry_row(self, entry_id: str) -> dict[str, Any]:
        row = self.db.one(_ENTRY_SELECT + " WHERE e.id=?", (entry_id,))
        if row is None:
            raise LaborError(f"unknown time entry {entry_id}")
        return row

    @staticmethod
    def _entry_out(row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["billable"] = bool(out.pop("phase_billable"))
        return out

    def entry(self, entry_id: str) -> dict[str, Any]:
        return self._entry_out(self._entry_row(entry_id))

    def entries(self, project_id: str | None = None, *, employee_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        clauses, params = [], []
        if project_id:
            clauses.append("e.project_id = ?")
            params.append(project_id)
        if employee_id:
            clauses.append("e.employee_id = ?")
            params.append(employee_id)
        if status:
            clauses.append("e.status = ?")
            params.append(status)
        sql = _ENTRY_SELECT + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY e.work_date, e.created_at, e.id"
        return [self._entry_out(r) for r in self.db.query(sql, tuple(params))]

    # ---- timesheets ----------------------------------------------------------- #

    @staticmethod
    def _line(e: dict[str, Any]) -> dict[str, Any]:
        return {
            "entry_id": e["id"], "entry_version": e["version"], "project_id": e["project_id"], "phase_id": e["phase_id"],
            "phase_code": e["phase_code"], "billable": bool(e["phase_billable"]), "work_date": e["work_date"], "hours": e["hours"],
            "rate_id": e["rate_id"], "cost_rate": e["cost_rate"], "bill_rate": e["bill_rate"],
            "cost_amount": e["cost_amount"], "bill_amount": e["bill_amount"],
        }

    def _timesheet_content(self, employee_id: str, period_id: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        lines = [self._line(e) for e in sorted(entries, key=lambda e: (e["work_date"], e["id"]))]
        return {
            "lines": lines,
            "content_hash": hash_json({"employee_id": employee_id, "period_id": period_id, "lines": lines}),
            "entry_count": len(lines),
            "total_hours": _fmt_h(_sum_hours(ln["hours"] for ln in lines)),
            "total_cost": fmt(total(ln["cost_amount"] for ln in lines)),
            "total_bill": fmt(total(ln["bill_amount"] for ln in lines)),
        }

    @staticmethod
    def _allocation(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Labor cost grouped by project and phase (the WBS the cost is charged to)."""
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for ln in lines:
            key = (ln["project_id"], ln["phase_id"])
            g = groups.setdefault(key, {"project_id": ln["project_id"], "phase_id": ln["phase_id"], "phase_code": ln["phase_code"], "hours": ZERO_HOURS, "cost": ZERO})
            g["hours"] += D(ln["hours"])
            g["cost"] = money(g["cost"] + money(ln["cost_amount"]))
        out = []
        for g in sorted(groups.values(), key=lambda g: (g["project_id"], g["phase_code"].upper(), g["phase_id"])):
            out.append({"project_id": g["project_id"], "phase_id": g["phase_id"], "phase_code": g["phase_code"], "hours": _fmt_h(g["hours"]), "cost": fmt(g["cost"])})
        return out

    def _live_timesheet_entries(self, timesheet_id: str) -> list[dict[str, Any]]:
        return self.db.query(_ENTRY_SELECT + " WHERE e.timesheet_id=? AND e.status='submitted' ORDER BY e.work_date, e.id", (timesheet_id,))

    def submit_timesheet(self, employee_id: str, period_id: str, *, actor: str) -> dict[str, Any]:
        """Group the employee's draft entries dated within the period into one timesheet.
        A timesheet returned by ``reject_timesheet`` is resubmitted as its next version."""
        with self.db.transaction() as conn:
            self._employee(employee_id)
            period = self._period(period_id, require_open=True, purpose="time for it can no longer be submitted")
            drafts = self.db.query(
                _ENTRY_SELECT + " WHERE e.employee_id=? AND e.status='draft' AND e.work_date BETWEEN ? AND ? ORDER BY e.work_date, e.id",
                (employee_id, period["start_date"], period["end_date"]),
            )
            if not drafts:
                raise LaborError(f"employee {employee_id} has no draft time dated within period {period_id} ({period['start_date']} to {period['end_date']})")
            open_ts = self.db.one(
                "SELECT * FROM labor_timesheets WHERE employee_id=? AND period_id=? AND status IN ('submitted','rejected')",
                (employee_id, period_id),
            )
            if open_ts is not None and open_ts["status"] == "submitted":
                raise LaborError(f"timesheet {open_ts['id']} for period {period_id} already awaits approval; approve or reject it before submitting more time")
            content = self._timesheet_content(employee_id, period_id, drafts)
            now = utcnow_iso()
            if open_ts is None:
                ts_id = new_id("ltsh")
                version = 1
                conn.execute(
                    """INSERT INTO labor_timesheets (id, employee_id, period_id, status, version, content_hash, lines_json, entry_count,
                           total_hours, total_cost, total_bill, submitted_by, submitted_at)
                       VALUES (?,?,?,'submitted',1,?,?,?,?,?,?,?,?)""",
                    (ts_id, employee_id, period_id, content["content_hash"], canonical_json(content["lines"]), content["entry_count"],
                     content["total_hours"], content["total_cost"], content["total_bill"], actor, now),
                )
                action = "labor.timesheet_submitted"
            else:
                ts_id = open_ts["id"]
                version = open_ts["version"] + 1
                conn.execute(
                    """UPDATE labor_timesheets SET status='submitted', version=?, content_hash=?, lines_json=?, entry_count=?, total_hours=?,
                           total_cost=?, total_bill=?, submitted_by=?, submitted_at=? WHERE id=?""",
                    (version, content["content_hash"], canonical_json(content["lines"]), content["entry_count"], content["total_hours"],
                     content["total_cost"], content["total_bill"], actor, now, ts_id),
                )
                action = "labor.timesheet_resubmitted"
            for e in drafts:
                conn.execute("UPDATE labor_entries SET status='submitted', timesheet_id=?, updated_at=? WHERE id=?", (ts_id, now, e["id"]))
            self.audit.record(actor, action, TIMESHEET_SUBJECT, ts_id, {
                "employee_id": employee_id, "period_id": period_id, "version": version, "content_hash": content["content_hash"],
                "total_hours": content["total_hours"], "total_cost": content["total_cost"], "lines": content["lines"],
            })
        return self.timesheet(ts_id)

    def reject_timesheet(self, timesheet_id: str, reason: str, *, actor: str) -> dict[str, Any]:
        """Return a submitted timesheet for correction: its entries go back to draft and
        every open approval on it is invalidated."""
        why = _text(reason, "rejection reason")
        with self.db.transaction() as conn:
            ts = self._timesheet_row(timesheet_id)
            if ts["status"] != "submitted":
                raise LaborError(f"timesheet {timesheet_id} is {ts['status']}; only a submitted timesheet can be rejected")
            now = utcnow_iso()
            returned = [e["id"] for e in self._live_timesheet_entries(timesheet_id)]
            conn.execute("UPDATE labor_entries SET status='draft', timesheet_id=NULL, updated_at=? WHERE timesheet_id=? AND status='submitted'", (now, timesheet_id))
            conn.execute(
                "UPDATE labor_timesheets SET status='rejected', rejected_by=?, rejected_at=?, reject_reason=? WHERE id=?",
                (actor, now, why, timesheet_id),
            )
            invalidated = self.approvals.invalidate_for_subject(TIMESHEET_SUBJECT, timesheet_id, reason=f"timesheet rejected: {why}", actor=actor)
            self.audit.record(actor, "labor.timesheet_rejected", TIMESHEET_SUBJECT, timesheet_id, {
                "reason": why, "version": ts["version"], "entries_returned": returned, "approvals_invalidated": invalidated,
            })
        return self.timesheet(timesheet_id)

    def _timesheet_row(self, timesheet_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM labor_timesheets WHERE id=?", (timesheet_id,))
        if row is None:
            raise LaborError(f"unknown timesheet {timesheet_id}")
        return row

    def timesheet(self, timesheet_id: str) -> dict[str, Any]:
        row = self._timesheet_row(timesheet_id)
        row["lines"] = loads(row.pop("lines_json"))
        row["entries"] = [self._entry_out(e) for e in self.db.query(_ENTRY_SELECT + " WHERE e.timesheet_id=? ORDER BY e.work_date, e.id", (timesheet_id,))]
        row["allocation"] = self._allocation(row["lines"])
        return row

    def timesheets(self, *, employee_id: str | None = None, period_id: str | None = None, project_id: str | None = None) -> list[dict[str, Any]]:
        clauses, params = [], []
        if employee_id:
            clauses.append("employee_id = ?")
            params.append(employee_id)
        if period_id:
            clauses.append("period_id = ?")
            params.append(period_id)
        sql = "SELECT id FROM labor_timesheets" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY submitted_at, id"
        out = [self.timesheet(r["id"]) for r in self.db.query(sql, tuple(params))]
        if project_id:
            out = [t for t in out if any(ln["project_id"] == project_id for ln in t["lines"])]
        return out

    # ---- payroll ------------------------------------------------------------ #

    def _approved_cost(self, employee_id: str, *, through: str | None = None) -> Decimal:
        """Approved labor cost, for all time or in periods starting on or before ``through``."""
        sql = "SELECT t.total_cost FROM labor_timesheets t JOIN periods p ON p.id = t.period_id WHERE t.employee_id=? AND t.status='approved'"
        params: list[Any] = [employee_id]
        if through is not None:
            sql += " AND p.start_date <= ?"
            params.append(through)
        return total(r["total_cost"] for r in self.db.query(sql, tuple(params)))

    def _payroll_total(self, employee_id: str, status: str, *, exclude: str | None = None, through: str | None = None) -> Decimal:
        sql = "SELECT x.gross_amount FROM labor_payroll x JOIN periods p ON p.id = x.period_id WHERE x.employee_id=? AND x.status=?"
        params: list[Any] = [employee_id, status]
        if exclude is not None:
            sql += " AND x.id != ?"
            params.append(exclude)
        if through is not None:
            sql += " AND p.start_date <= ?"
            params.append(through)
        return total(r["gross_amount"] for r in self.db.query(sql, tuple(params)))

    def _accrual_by_period(self, employee_id: str, *, include_drafts: bool, exclude: str | None = None) -> list[tuple[str, Decimal]]:
        """The employee's accrued payroll (approved cost less payroll) cumulated through each
        period, as ``(period start date, cumulative balance)`` in date order: the 2200
        subledger balance at each period end.  Draft payroll counts when ``include_drafts``."""
        net: dict[str, Decimal] = {}
        for r in self.db.query(
            "SELECT p.start_date, t.total_cost FROM labor_timesheets t JOIN periods p ON p.id = t.period_id WHERE t.employee_id=? AND t.status='approved'",
            (employee_id,),
        ):
            net[r["start_date"]] = money(net.get(r["start_date"], ZERO) + money(r["total_cost"]))
        statuses = ("posted", "draft") if include_drafts else ("posted",)
        sql = (
            "SELECT p.start_date, x.gross_amount FROM labor_payroll x JOIN periods p ON p.id = x.period_id"
            f" WHERE x.employee_id=? AND x.status IN ({','.join('?' * len(statuses))})"
        )
        params: list[Any] = [employee_id, *statuses]
        if exclude is not None:
            sql += " AND x.id != ?"
            params.append(exclude)
        for r in self.db.query(sql, tuple(params)):
            net[r["start_date"]] = money(net.get(r["start_date"], ZERO) - money(r["gross_amount"]))
        starts = {r["start_date"] for r in self.db.query("SELECT DISTINCT start_date FROM periods")} | set(net)
        out: list[tuple[str, Decimal]] = []
        running = ZERO
        for start in sorted(starts):
            running = money(running + net.get(start, ZERO))
            out.append((start, running))
        return out

    def accrued_payroll(self, employee_id: str, period_id: str | None = None) -> Decimal:
        """Approved labor cost not yet settled by posted payroll (the 2200 subledger), for all
        time or cumulatively through ``period_id`` (periods starting on or before its start)."""
        if period_id is None:
            return money(self._approved_cost(employee_id) - self._payroll_total(employee_id, "posted"))
        through = self._period(period_id)["start_date"]
        return money(self._approved_cost(employee_id, through=through) - self._payroll_total(employee_id, "posted", through=through))

    def payroll_available(self, employee_id: str, period_id: str, *, include_drafts: bool = True, exclude: str | None = None) -> Decimal:
        """The most payroll period ``period_id`` can still settle for the employee: the lowest
        cumulative accrual at the end of that period or of any later one.  So a settlement
        never pays time approved in a later period, and never overdraws a later period whose
        own payroll already settled earlier time.  Draft payroll is held as reserved unless
        ``include_drafts`` is False; ``exclude`` leaves one payroll record out."""
        start = self._period(period_id)["start_date"]
        tail = [cum for s, cum in self._accrual_by_period(employee_id, include_drafts=include_drafts, exclude=exclude) if s >= start]
        return min(tail) if tail else ZERO

    def record_payroll(self, period_id: str, employee_id: str, gross_amount, reference: str, *, actor: str) -> dict[str, Any]:
        """Draft a payroll settlement (an imported payroll run) against the employee's accrual
        as of the period: only time approved in this or an earlier period can be settled."""
        amt = _amount(gross_amount, "gross amount", allow_zero=False)
        ref = _text(reference, "payroll reference")
        payroll_id = new_id("lpay")
        with self.db.transaction() as conn:
            self._period(period_id, require_open=True, purpose="payroll can no longer be recorded in it")
            self._employee(employee_id)
            dup = self.db.one("SELECT id, status FROM labor_payroll WHERE reference = ? COLLATE NOCASE", (ref,))
            if dup is not None:
                raise LaborError(f"payroll reference {ref!r} is already used by {dup['id']} ({dup['status']}); a payroll reference is never reused")
            accrued = self.accrued_payroll(employee_id, period_id)
            available = self.payroll_available(employee_id, period_id)
            if amt > available:
                reserved = self._payroll_total(employee_id, "draft")
                raise LaborError(
                    f"payroll {fmt(amt)} exceeds the {fmt(max(available, ZERO))} of accrued payroll employee {employee_id} can be paid in period {period_id} "
                    f"(approved time through {period_id} less posted payroll is {fmt(accrued)}"
                    + (f"; {fmt(reserved)} is held by draft payroll" if reserved > 0 else "")
                    + "; time approved in a later period, or already settled by a later period's payroll, is not available)"
                    + "; payroll settles approved time and never creates labor cost"
                )
            conn.execute(
                "INSERT INTO labor_payroll (id, period_id, employee_id, gross_amount, reference, status, version, created_by, created_at) VALUES (?,?,?,?,?,'draft',1,?,?)",
                (payroll_id, period_id, employee_id, fmt(amt), ref, actor, utcnow_iso()),
            )
            self.audit.record(actor, "labor.payroll_recorded", PAYROLL_SUBJECT, payroll_id, {
                "period_id": period_id, "employee_id": employee_id, "gross_amount": fmt(amt), "reference": ref,
                "accrued_through_period": fmt(accrued), "available_before": fmt(available),
            })
        return self.payroll(payroll_id)

    def cancel_payroll(self, payroll_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        with self.db.transaction() as conn:
            p = self.payroll(payroll_id)
            if p["status"] != "draft":
                raise LaborError(f"payroll {payroll_id} is {p['status']}; only a draft can be canceled")
            conn.execute(
                "UPDATE labor_payroll SET status='canceled', version=version+1, canceled_at=?, cancel_reason=? WHERE id=?",
                (utcnow_iso(), _note(reason), payroll_id),
            )
            invalidated = self.approvals.invalidate_for_subject(PAYROLL_SUBJECT, payroll_id, reason=f"payroll canceled: {_note(reason)}", actor=actor)
            self.audit.record(actor, "labor.payroll_canceled", PAYROLL_SUBJECT, payroll_id, {"reason": _note(reason), "reference": p["reference"], "approvals_invalidated": invalidated})
        return self.payroll(payroll_id)

    def payroll(self, payroll_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM labor_payroll WHERE id=?", (payroll_id,))
        if row is None:
            raise LaborError(f"unknown payroll record {payroll_id}")
        return row

    def payrolls(self, *, employee_id: str | None = None, period_id: str | None = None) -> list[dict[str, Any]]:
        clauses, params = [], []
        if employee_id:
            clauses.append("employee_id = ?")
            params.append(employee_id)
        if period_id:
            clauses.append("period_id = ?")
            params.append(period_id)
        sql = "SELECT * FROM labor_payroll" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY created_at, id"
        return self.db.query(sql, tuple(params))

    def _control_2200(self, *, party_id: str | None = None, through: str | None = None) -> Decimal:
        """2200 natural (credit) balance, for all time or through periods starting on or before ``through``."""
        if through is None:
            return self.ledger.balance(ACCOUNT_ACCRUED_PAYROLL, **({"party_id": party_id} if party_id else {}))
        sql = (
            "SELECT l.debit, l.credit FROM journal_lines l JOIN journals j ON j.id = l.journal_id JOIN periods p ON p.id = j.period_id"
            " WHERE l.account_code = ? AND p.start_date <= ?"
        )
        params: list[Any] = [ACCOUNT_ACCRUED_PAYROLL, through]
        if party_id is not None:
            sql += " AND l.party_id = ?"
            params.append(party_id)
        rows = self.db.query(sql, tuple(params))
        return money(total(r["credit"] for r in rows) - total(r["debit"] for r in rows))

    def accrued_payroll_reconciliation(self, period_id: str | None = None) -> dict[str, Any]:
        """Accrued payroll subledger (approved cost less posted payroll) per employee against
        the 2200 control account, for all time or cumulatively through ``period_id``.  An
        employee whose accrual is negative (payroll ahead of approved time) is overdrawn."""
        through = self._period(period_id)["start_date"] if period_id is not None else None
        ids = {r["employee_id"] for r in self.db.query("SELECT DISTINCT employee_id FROM labor_timesheets WHERE status='approved'")}
        ids |= {r["employee_id"] for r in self.db.query("SELECT DISTINCT employee_id FROM labor_payroll WHERE status='posted'")}
        ids |= {r["party_id"] for r in self.db.query("SELECT DISTINCT party_id FROM journal_lines WHERE account_code=? AND party_id IS NOT NULL", (ACCOUNT_ACCRUED_PAYROLL,))}
        items = []
        subledger = ZERO
        all_match = True
        for emp in sorted(ids):
            approved = self._approved_cost(emp, through=through)
            posted = self._payroll_total(emp, "posted", through=through)
            accrued = money(approved - posted)
            control = self._control_2200(party_id=emp, through=through)
            match = accrued == control
            all_match = all_match and match
            items.append({
                "employee_id": emp, "approved_cost": fmt(approved), "posted_payroll": fmt(posted), "accrued": fmt(accrued),
                "control_balance": fmt(control), "reconciled": match, "overdrawn": accrued < 0 or control < 0,
            })
            subledger += accrued
        control_total = self._control_2200(through=through)
        return {
            "period_id": period_id,
            "basis": f"cumulative through period {period_id}" if period_id is not None else "all periods",
            "items": items, "subledger_total": fmt(subledger), "control_balance": fmt(control_total),
            "reconciled": all_match and money(subledger) == control_total,
            "overdrawn": [it["employee_id"] for it in items if it["overdrawn"]],
        }

    # ---- T&M invoices ------------------------------------------------------- #

    @staticmethod
    def _invoice_line_content(ln: dict[str, Any]) -> dict[str, Any]:
        return {
            "entry_id": ln["entry_id"], "entry_version": ln["entry_version"], "phase_id": ln["phase_id"], "phase_code": ln["phase_code"],
            "employee_id": ln["employee_id"], "work_date": ln["work_date"], "hours": ln["hours"], "bill_rate": ln["bill_rate"], "amount": ln["amount"],
        }

    @staticmethod
    def _invoice_hash(project_id: str, customer_id: str, period_id: str, lines: list[dict[str, Any]]) -> str:
        return hash_json({"project_id": project_id, "customer_id": customer_id, "period_id": period_id, "lines": lines})

    def _live_invoice_lines(self, invoice_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            """SELECT l.*, e.version AS entry_version, e.status AS entry_status, p.code AS phase_code
               FROM labor_invoice_lines l JOIN labor_entries e ON e.id = l.entry_id JOIN labor_phases p ON p.id = l.phase_id
               WHERE l.invoice_id=? AND l.released = 0 ORDER BY l.work_date, l.entry_id""",
            (invoice_id,),
        )

    def prepare_invoice(self, project_id: str, period_id: str, *, actor: str) -> dict[str, Any]:
        """Draft a T&M invoice from approved, unbilled time on billable phases dated in the period."""
        with self.db.transaction() as conn:
            project = self._project(project_id)
            self._customer(project["customer_id"], project_id)
            period = self._period(period_id, require_open=True, purpose="it can no longer be invoiced")
            candidates = self.db.query(
                _ENTRY_SELECT + " WHERE e.project_id=? AND e.status='approved' AND p.billable=1 AND e.work_date BETWEEN ? AND ?"
                " AND NOT EXISTS (SELECT 1 FROM labor_invoice_lines x WHERE x.entry_id = e.id AND x.released = 0)"
                " ORDER BY e.work_date, e.id",
                (project_id, period["start_date"], period["end_date"]),
            )
            billable = [e for e in candidates if money(e["bill_amount"]) > 0]
            if not billable:
                raise LaborError(f"nothing to bill on project {project_id} for period {period_id}: no approved, unbilled time on billable phases")
            lines = [
                {"entry_id": e["id"], "entry_version": e["version"], "phase_id": e["phase_id"], "phase_code": e["phase_code"], "employee_id": e["employee_id"],
                 "work_date": e["work_date"], "hours": e["hours"], "bill_rate": e["bill_rate"], "amount": e["bill_amount"]}
                for e in billable
            ]
            content_hash = self._invoice_hash(project_id, project["customer_id"], period_id, lines)
            amount = total(ln["amount"] for ln in lines)
            hours = _sum_hours(ln["hours"] for ln in lines)
            sequence = (self.db.scalar("SELECT MAX(sequence) FROM labor_invoices WHERE project_id=?", (project_id,)) or 0) + 1
            invoice_id = new_id("linv")
            conn.execute(
                """INSERT INTO labor_invoices (id, project_id, customer_id, period_id, sequence, status, version, content_hash, line_count, total_hours, total, created_by, created_at)
                   VALUES (?,?,?,?,?,'draft',1,?,?,?,?,?,?)""",
                (invoice_id, project_id, project["customer_id"], period_id, sequence, content_hash, len(lines), _fmt_h(hours), fmt(amount), actor, utcnow_iso()),
            )
            for ln in lines:
                conn.execute(
                    "INSERT INTO labor_invoice_lines (id, invoice_id, entry_id, phase_id, employee_id, work_date, hours, bill_rate, amount, released) VALUES (?,?,?,?,?,?,?,?,?,0)",
                    (new_id("lnvl"), invoice_id, ln["entry_id"], ln["phase_id"], ln["employee_id"], ln["work_date"], ln["hours"], ln["bill_rate"], ln["amount"]),
                )
            self.audit.record(actor, "labor.invoice_prepared", INVOICE_SUBJECT, invoice_id, {
                "project_id": project_id, "customer_id": project["customer_id"], "period_id": period_id, "sequence": sequence,
                "total": fmt(amount), "total_hours": _fmt_h(hours), "content_hash": content_hash, "entries": [ln["entry_id"] for ln in lines],
            })
        return self.invoice(invoice_id)

    def void_invoice(self, invoice_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        """Void a draft invoice and release its time for re-invoicing."""
        with self.db.transaction() as conn:
            inv = self._invoice_row(invoice_id)
            if inv["status"] != "draft":
                raise LaborError(f"invoice {invoice_id} is {inv['status']}; only a draft invoice can be voided")
            conn.execute(
                "UPDATE labor_invoices SET status='void', version=version+1, voided_at=?, void_reason=? WHERE id=?",
                (utcnow_iso(), _note(reason), invoice_id),
            )
            released = [r["entry_id"] for r in self.db.query("SELECT entry_id FROM labor_invoice_lines WHERE invoice_id=? AND released=0", (invoice_id,))]
            conn.execute("UPDATE labor_invoice_lines SET released=1 WHERE invoice_id=? AND released=0", (invoice_id,))
            invalidated = self.approvals.invalidate_for_subject(INVOICE_SUBJECT, invoice_id, reason=f"invoice voided: {_note(reason)}", actor=actor)
            self.audit.record(actor, "labor.invoice_voided", INVOICE_SUBJECT, invoice_id, {"reason": _note(reason), "entries_released": released, "approvals_invalidated": invalidated})
        return self.invoice(invoice_id)

    def _invoice_row(self, invoice_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM labor_invoices WHERE id=?", (invoice_id,))
        if row is None:
            raise LaborError(f"unknown labor invoice {invoice_id}")
        return row

    def invoice(self, invoice_id: str) -> dict[str, Any]:
        row = self._invoice_row(invoice_id)
        row["lines"] = self.db.query("SELECT * FROM labor_invoice_lines WHERE invoice_id=? ORDER BY work_date, entry_id", (invoice_id,))
        for ln in row["lines"]:
            ln["released"] = bool(ln["released"])
        row["collections"] = self.db.query("SELECT * FROM labor_collections WHERE invoice_id=? ORDER BY received_at, id", (invoice_id,))
        bal = self._invoice_balance(row)
        row["collected"] = fmt(bal["collected"])
        row["billing_reversed"] = bal["reversal_journal_id"] is not None
        row["reversal_journal_id"] = bal["reversal_journal_id"]
        row["cleared_by_reversal"] = fmt(bal["reversed"])
        row["reversed_collections"] = bal["reversed_collections"]
        row["open"] = fmt(bal["open"])
        return row

    def _reversal(self, journal_id: str | None, *, through: str | None = None) -> dict[str, Any] | None:
        """The journal that reverses ``journal_id`` (``journal.reverse`` or ``Ledger.reverse``),
        if any; with ``through`` only a reversal posted in a period starting on or before it."""
        if not journal_id:
            return None
        sql = "SELECT j.id, j.period_id FROM journals j JOIN periods p ON p.id = j.period_id WHERE j.reversal_of = ?"
        params: tuple = (journal_id,)
        if through is not None:
            sql += " AND p.start_date <= ?"
            params = (journal_id, through)
        return self.db.one(sql, params)

    def _invoice_balance(self, inv: dict[str, Any], *, through: str | None = None) -> dict[str, Any]:
        """What a T&M invoice leaves in 1100: billed less the collections still on the books,
        and nothing billed once the billing journal itself is reversed (a reversal clears the
        whole receivable it posted, exactly as it clears the 1100 debit).  A reversed
        collection journal no longer counts as collected.  With ``through`` (a period start
        date) only journals of periods starting on or before it count, which is the cut the
        cumulative reconciliation uses."""
        billed = ZERO
        if inv["status"] == "billed" and inv.get("journal_id"):
            if through is None:
                billed = money(inv["total"])
            else:
                start = self.db.scalar("SELECT p.start_date FROM journals j JOIN periods p ON p.id = j.period_id WHERE j.id=?", (inv["journal_id"],))
                billed = money(inv["total"]) if start is not None and start <= through else ZERO
        reversal = self._reversal(inv.get("journal_id"), through=through) if billed > 0 else None
        cleared = billed if reversal is not None else ZERO
        sql = "SELECT c.id, c.amount, c.journal_id FROM labor_collections c JOIN periods p ON p.id = c.period_id WHERE c.invoice_id=?"
        params: tuple = (inv["id"],)
        if through is not None:
            sql += " AND p.start_date <= ?"
            params = (inv["id"], through)
        collected = ZERO
        reversed_collections: list[str] = []
        for col in self.db.query(sql + " ORDER BY c.received_at, c.id", params):
            if self._reversal(col["journal_id"], through=through) is not None:
                reversed_collections.append(col["id"])
                continue
            collected += money(col["amount"])
        return {
            "billed": money(billed), "collected": money(collected), "reversed": money(cleared),
            "reversal_journal_id": reversal["id"] if reversal is not None else None,
            "reversed_collections": reversed_collections, "open": money(billed - collected - cleared),
        }

    def invoices(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT id FROM labor_invoices WHERE project_id=? ORDER BY sequence", (project_id,))
        return [self.invoice(r["id"]) for r in rows]

    # ---- T&M receivables: collections and the subledger ----------------------- #

    def record_collection(self, invoice_id: str, period_id: str, amount, provider_ref: str, *, actor: str, fee="0.00") -> dict[str, Any]:
        """Record a (simulated) customer receipt against a billed T&M invoice: the gross clears
        AR, the bank receives the gross less the processing fee, the fee is expensed."""
        amt = _amount(amount, "collection amount", allow_zero=False)
        f = _amount(fee, "processing fee", allow_zero=True)
        if f >= amt:
            raise LaborError(f"processing fee {fmt(f)} must be less than the collection amount {fmt(amt)}")
        ref = _text(provider_ref, "provider reference")
        collection_id = new_id("lcol")
        with self.db.transaction() as conn:
            receipt_period = self._period(period_id, require_open=True, purpose="receipts can no longer be recorded in it")
            inv = self.invoice(invoice_id)
            if inv["status"] != "billed":
                raise LaborError(f"invoice {invoice_id} is {inv['status']}; only a billed invoice can be collected")
            billed_period = self._period(inv["period_id"])
            if receipt_period["start_date"] < billed_period["start_date"]:
                raise LaborError(
                    f"invoice {invoice_id} is billed in period {inv['period_id']}; a receipt cannot be recorded in the earlier period {period_id}, "
                    "where the receivable does not exist yet"
                )
            if inv["billing_reversed"]:
                raise LaborError(
                    f"invoice {invoice_id} billing journal {inv['journal_id']} was reversed by {inv['reversal_journal_id']}; "
                    "nothing is receivable on it, so no receipt can be recorded against it"
                )
            dup = self.db.one("SELECT id FROM labor_collections WHERE provider_ref = ? COLLATE NOCASE", (ref,))
            # a receipt reference is unique across every receivables source sharing control account 1100
            for table in OTHER_RECEIPT_TABLES:
                if dup is None and self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)) is not None:
                    dup = self.db.one(f"SELECT id FROM {table} WHERE provider_ref = ? COLLATE NOCASE", (ref,))
            if dup is not None:
                raise LaborError(f"receipt {ref!r} was already recorded as {dup['id']}")
            open_amt = money(inv["open"])
            if amt > open_amt:
                raise LaborError(f"collection {fmt(amt)} exceeds the open balance {fmt(open_amt)} of invoice {invoice_id}")
            lines = [{"account": ACCOUNT_BANK, "debit": amt - f, "project_id": inv["project_id"], "party_id": inv["customer_id"], "memo": f"receipt {ref} (simulated)"}]
            if f > 0:
                lines.append({"account": ACCOUNT_FEES, "debit": f, "project_id": inv["project_id"], "party_id": inv["customer_id"], "memo": f"processing fee on {ref}"})
            lines.append({"account": ACCOUNT_AR, "credit": amt, "project_id": inv["project_id"], "party_id": inv["customer_id"],
                          "memo": f"T&M invoice {inv['sequence']} ({invoice_id}) collected"})
            j = self.ledger.post(
                period_id=period_id,
                description=f"Collection on T&M invoice {inv['sequence']} from customer {inv['customer_id']}",
                lines=lines, source_type=COLLECTION_SUBJECT, source_id=collection_id, source_version="1", posted_by=actor,
            )
            conn.execute(
                """INSERT INTO labor_collections (id, invoice_id, project_id, customer_id, period_id, amount, fee, provider_ref, journal_id, created_by, received_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (collection_id, invoice_id, inv["project_id"], inv["customer_id"], period_id, fmt(amt), fmt(f), ref, j["id"], actor, utcnow_iso()),
            )
            self.audit.record(actor, "labor.collection_recorded", COLLECTION_SUBJECT, collection_id, {
                "invoice_id": invoice_id, "period_id": period_id, "amount": fmt(amt), "fee": fmt(f), "provider_ref": ref,
                "journal_id": j["id"], "open_after": fmt(open_amt - amt),
            })
        return self.collection(collection_id)

    def collection(self, collection_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM labor_collections WHERE id=?", (collection_id,))
        if row is None:
            raise LaborError(f"unknown labor collection {collection_id}")
        return row

    def ar_open_items(self, project_id: str | None = None) -> dict[str, Any]:
        """The labor T&M receivables subledger (billed invoices less collections), in the shape
        of ``Receivables.ar_open_items``: ``{"items": [...], "subledger_total": "<money>"}``.
        These balances sit in control account 1100 next to prime bills; the core receivables
        subledger aggregates this source so 1100 reconciles.  ``project_id=None`` covers every
        project.  Fully collected invoices are listed with ``open`` 0.00, as prime bills are.
        An invoice whose billing journal was reversed (``journal.reverse``) is cleared by
        that reversal: nothing stays open on it beyond any receipt that must be refunded
        (a negative open amount), exactly what the reversal left in 1100."""
        sql = "SELECT id FROM labor_invoices WHERE status='billed'"
        params: tuple = ()
        if project_id:
            sql += " AND project_id=?"
            params = (project_id,)
        items = []
        open_total = ZERO
        for r in self.db.query(sql + " ORDER BY project_id, sequence", params):
            inv = self.invoice(r["id"])
            items.append({
                "kind": "labor_invoice", "source": PLUGIN_NAME, "invoice_id": inv["id"], "project_id": inv["project_id"], "customer_id": inv["customer_id"],
                "sequence": inv["sequence"], "period_id": inv["period_id"], "created_at": inv["created_at"], "billed_at": inv["billed_at"],
                "journal_id": inv["journal_id"], "amount_due": inv["total"], "received": inv["collected"],
                "reversed": inv["cleared_by_reversal"], "reversal_journal_id": inv["reversal_journal_id"], "open": inv["open"],
            })
            open_total += money(inv["open"])
        return {"source": "labor T&M invoices", "control_account": ACCOUNT_AR, "project_id": project_id, "items": items, "subledger_total": fmt(open_total)}

    def tm_receivable_reconciliation(self, period_id: str | None = None) -> dict[str, Any]:
        """The T&M subledger (billed invoices less collections) against the 1100 lines this
        module's own invoice and collection journals posted, all time or cumulatively through
        ``period_id`` (journals of periods starting on or before it).  This is a source-level
        tie, not the 1100 control reconciliation, which the core AR subledger performs with
        every source included.  Any open balance below zero is reported as overcollected.
        Reversals of invoice or collection journals carry the original source type, so they
        are in the postings and clear the subledger in the same cut."""
        through = self._period(period_id)["start_date"] if period_id is not None else None
        cut = " AND p.start_date <= ?" if through is not None else ""
        args: tuple = (through,) if through is not None else ()
        # collections exist only on billed invoices (trigger), and a billed invoice never changes status
        by_invoice: dict[str, Decimal] = {}
        for inv in self.db.query("SELECT * FROM labor_invoices WHERE status='billed' ORDER BY project_id, sequence"):
            bal = self._invoice_balance(inv, through=through)
            if bal["billed"] > 0 or bal["collected"] != 0:
                by_invoice[inv["id"]] = bal["open"]
        subledger = total(by_invoice.values()) if by_invoice else ZERO
        lines = self.db.query(
            "SELECT l.debit, l.credit FROM journal_lines l JOIN journals j ON j.id = l.journal_id JOIN periods p ON p.id = j.period_id"
            " WHERE l.account_code = ? AND j.source_type IN (?, ?)" + cut,
            (ACCOUNT_AR, INVOICE_SUBJECT, COLLECTION_SUBJECT) + args,
        )
        postings = money(total(r["debit"] for r in lines) - total(r["credit"] for r in lines))
        overcollected = sorted(k for k, v in by_invoice.items() if v < 0)
        return {
            "period_id": period_id,
            "basis": f"cumulative through period {period_id}" if period_id is not None else "all periods",
            "subledger_total": fmt(subledger), "labor_postings_1100": fmt(postings),
            "reconciled": money(subledger) == postings and not overcollected,
            "overcollected": overcollected,
        }

    # ---- approvals: manifests ------------------------------------------------- #

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation == OP_APPROVE_TIMESHEET:
            return self._timesheet_manifest(subject_id, actor_role=actor_role)
        if operation == OP_POST_PAYROLL:
            return self._payroll_manifest(subject_id, actor_role=actor_role)
        if operation == OP_BILL:
            return self._bill_manifest(subject_id, actor_role=actor_role)
        raise LaborError(f"unknown labor operation {operation}")

    def _timesheet_manifest(self, timesheet_id: str, *, actor_role: str) -> dict[str, Any]:
        ts = self._timesheet_row(timesheet_id)
        if ts["status"] != "submitted":
            raise LaborError(f"timesheet {timesheet_id} is {ts['status']}, not submitted")
        # recomputed from the entries as they are NOW, so any change shows as a different hash
        live = self._timesheet_content(ts["employee_id"], ts["period_id"], self._live_timesheet_entries(timesheet_id))
        return build_manifest(
            operation=OP_APPROVE_TIMESHEET,
            subject_type=TIMESHEET_SUBJECT,
            subject_id=timesheet_id,
            actor_role=actor_role,
            amounts={"total_cost": live["total_cost"]},
            bindings={
                "timesheet_version": ts["version"],
                "content_hash": live["content_hash"],
                "employee_id": ts["employee_id"],
                "period_id": ts["period_id"],
                "total_hours": live["total_hours"],
                "entry_count": live["entry_count"],
                "allocation": self._allocation(live["lines"]),
                "debit_account": ACCOUNT_LABOR_COST,
                "credit_account": ACCOUNT_ACCRUED_PAYROLL,
                "posting_rule": POSTING_RULE,
            },
        )

    def _payroll_manifest(self, payroll_id: str, *, actor_role: str) -> dict[str, Any]:
        p = self.payroll(payroll_id)
        if p["status"] != "draft":
            raise LaborError(f"payroll {payroll_id} is {p['status']}, not draft")
        return build_manifest(
            operation=OP_POST_PAYROLL,
            subject_type=PAYROLL_SUBJECT,
            subject_id=payroll_id,
            actor_role=actor_role,
            amounts={
                "gross_amount": p["gross_amount"],
                "accrued_payroll": self.accrued_payroll(p["employee_id"]),
                "available_in_period": self.payroll_available(p["employee_id"], p["period_id"], include_drafts=False, exclude=payroll_id),
            },
            bindings={
                "payroll_version": p["version"],
                "employee_id": p["employee_id"],
                "reference": p["reference"],
                "period_id": p["period_id"],
                "settles": f"{ACCOUNT_ACCRUED_PAYROLL} accrued payroll (no labor cost is posted)",
                "funding_source": "operating-bank-simulated",
                "settlement": "payroll provider import (simulated)",
                "posting_rule": POSTING_RULE,
            },
        )

    def _bill_manifest(self, invoice_id: str, *, actor_role: str) -> dict[str, Any]:
        inv = self._invoice_row(invoice_id)
        if inv["status"] != "draft":
            raise LaborError(f"invoice {invoice_id} is {inv['status']}, not draft")
        project = self._project(inv["project_id"])
        lines = [self._invoice_line_content(ln) for ln in self._live_invoice_lines(invoice_id)]
        customer = self.db.one("SELECT kind FROM parties WHERE id=?", (project["customer_id"],)) if project["customer_id"] else None
        return build_manifest(
            operation=OP_BILL,
            subject_type=INVOICE_SUBJECT,
            subject_id=invoice_id,
            actor_role=actor_role,
            amounts={"total": total(ln["amount"] for ln in lines)},
            bindings={
                "invoice_version": inv["version"],
                "content_hash": self._invoice_hash(inv["project_id"], inv["customer_id"], inv["period_id"], lines),
                "project_id": inv["project_id"],
                "customer_id": project["customer_id"],
                "customer_kind": customer["kind"] if customer else None,
                "invoice_customer_id": inv["customer_id"],
                "period_id": inv["period_id"],
                "sequence": inv["sequence"],
                "line_count": len(lines),
                "total_hours": _fmt_h(_sum_hours(ln["hours"] for ln in lines)),
                "revenue_account": ACCOUNT_FEE_REVENUE,
                "recognition_policy": "fixture: approved T&M time billed = earned (SHADOW)",
                "posting_rule": POSTING_RULE,
            },
        )

    # ---- approvals: execution ------------------------------------------------- #

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation == OP_APPROVE_TIMESHEET:
            return self._apply_approve_timesheet(subject_id, approval_id=approval_id, actor=actor, period_id=period_id)
        if operation == OP_POST_PAYROLL:
            return self._apply_post_payroll(subject_id, approval_id=approval_id, actor=actor, period_id=period_id)
        if operation == OP_BILL:
            return self._apply_bill(subject_id, approval_id=approval_id, actor=actor, period_id=period_id)
        raise LaborError(f"unknown labor operation {operation}")

    def _apply_approve_timesheet(self, timesheet_id: str, *, approval_id: str, actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction() as conn:
            ts = self._timesheet_row(timesheet_id)
            if ts["status"] != "submitted":
                raise LaborError(f"timesheet {timesheet_id} is {ts['status']}, not submitted")
            self._check_period_arg(period_id, ts["period_id"], f"timesheet {timesheet_id}")
            live = self._timesheet_content(ts["employee_id"], ts["period_id"], self._live_timesheet_entries(timesheet_id))
            if live["content_hash"] != ts["content_hash"] or not live["lines"]:
                raise LaborError(f"timesheet {timesheet_id} entries no longer match what was submitted; reject and resubmit it")
            self.ledger.require_open(ts["period_id"])
            allocation = self._allocation(live["lines"])
            cost = money(live["total_cost"])
            lines = [
                {"account": ACCOUNT_LABOR_COST, "debit": a["cost"], "project_id": a["project_id"], "party_id": ts["employee_id"],
                 "memo": f"labor phase {a['phase_code']}: {a['hours']} h (timesheet {timesheet_id})"}
                for a in allocation
            ]
            lines.append({"account": ACCOUNT_ACCRUED_PAYROLL, "credit": cost, "party_id": ts["employee_id"], "memo": f"accrued payroll, timesheet {timesheet_id} v{ts['version']}"})
            j = self.ledger.post(
                period_id=ts["period_id"],
                description=f"Timesheet approved: {live['total_hours']} h for employee {ts['employee_id']}",
                lines=lines,
                source_type=TIMESHEET_SUBJECT, source_id=timesheet_id, source_version=str(ts["version"]), posted_by=actor, approval_id=approval_id,
            )
            now = utcnow_iso()
            conn.execute("UPDATE labor_timesheets SET status='approved', approval_id=?, journal_id=?, approved_at=? WHERE id=?", (approval_id, j["id"], now, timesheet_id))
            conn.execute("UPDATE labor_entries SET status='approved', updated_at=? WHERE timesheet_id=? AND status='submitted'", (now, timesheet_id))
            self.approvals.invalidate_for_subject(TIMESHEET_SUBJECT, timesheet_id, reason="timesheet already approved", actor=actor)
            self.audit.record(actor, "labor.timesheet_approved", TIMESHEET_SUBJECT, timesheet_id, {
                "approval_id": approval_id, "journal_id": j["id"], "period_id": ts["period_id"], "employee_id": ts["employee_id"],
                "total_hours": live["total_hours"], "total_cost": fmt(cost), "allocation": allocation, "version": ts["version"],
            })
        return {
            "timesheet": timesheet_id, "status": "approved", "journal_id": j["id"], "period_id": ts["period_id"], "employee_id": ts["employee_id"],
            "total_hours": live["total_hours"], "total_cost": fmt(cost), "allocation": allocation,
        }

    def _apply_post_payroll(self, payroll_id: str, *, approval_id: str, actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction() as conn:
            p = self.payroll(payroll_id)
            if p["status"] != "draft":
                raise LaborError(f"payroll {payroll_id} is {p['status']}, not draft")
            self._check_period_arg(period_id, p["period_id"], f"payroll {payroll_id}")
            amt = money(p["gross_amount"])
            accrued = self.accrued_payroll(p["employee_id"])
            available = self.payroll_available(p["employee_id"], p["period_id"], include_drafts=False, exclude=payroll_id)
            if amt > available:
                raise LaborError(
                    f"payroll {fmt(amt)} exceeds the {fmt(max(available, ZERO))} of accrued payroll employee {p['employee_id']} "
                    f"can be paid in period {p['period_id']}; cancel the draft and record it against the right period"
                )
            self.ledger.require_open(p["period_id"])
            j = self.ledger.post(
                period_id=p["period_id"],
                description=f"Payroll settled ({p['reference']}) for employee {p['employee_id']}",
                lines=[
                    {"account": ACCOUNT_ACCRUED_PAYROLL, "debit": amt, "party_id": p["employee_id"], "memo": f"accrued payroll settled by {p['reference']}"},
                    {"account": ACCOUNT_BANK, "credit": amt, "party_id": p["employee_id"], "memo": f"payroll disbursement {p['reference']} (simulated)"},
                ],
                source_type=PAYROLL_SUBJECT, source_id=payroll_id, source_version=str(p["version"]), posted_by=actor, approval_id=approval_id,
            )
            conn.execute("UPDATE labor_payroll SET status='posted', approval_id=?, journal_id=?, posted_at=? WHERE id=?", (approval_id, j["id"], utcnow_iso(), payroll_id))
            self.approvals.invalidate_for_subject(PAYROLL_SUBJECT, payroll_id, reason="payroll already posted", actor=actor)
            remaining = money(accrued - amt)
            self.audit.record(actor, "labor.payroll_posted", PAYROLL_SUBJECT, payroll_id, {
                "approval_id": approval_id, "journal_id": j["id"], "period_id": p["period_id"], "employee_id": p["employee_id"],
                "gross_amount": fmt(amt), "reference": p["reference"], "accrued_after": fmt(remaining),
            })
        return {
            "payroll": payroll_id, "status": "posted", "journal_id": j["id"], "period_id": p["period_id"], "employee_id": p["employee_id"],
            "gross_amount": fmt(amt), "reference": p["reference"], "accrued_after": fmt(remaining),
        }

    def _apply_bill(self, invoice_id: str, *, approval_id: str, actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction() as conn:
            inv = self._invoice_row(invoice_id)
            if inv["status"] != "draft":
                raise LaborError(f"invoice {invoice_id} is {inv['status']}, not draft")
            self._check_period_arg(period_id, inv["period_id"], f"invoice {invoice_id}")
            project = self._project(inv["project_id"])
            if not project["customer_id"] or project["customer_id"] != inv["customer_id"]:
                raise LaborError(f"project {inv['project_id']} customer is {project['customer_id']!r}, but invoice {invoice_id} was prepared for {inv['customer_id']}")
            self._customer(inv["customer_id"], inv["project_id"])
            raw = self._live_invoice_lines(invoice_id)
            if not raw or any(ln["entry_status"] != "approved" for ln in raw):
                raise LaborError(f"invoice {invoice_id} holds time that is no longer approved and unbilled; void and prepare it again")
            lines = [self._invoice_line_content(ln) for ln in raw]
            if self._invoice_hash(inv["project_id"], inv["customer_id"], inv["period_id"], lines) != inv["content_hash"]:
                raise LaborError(f"invoice {invoice_id} lines no longer match what was prepared; void and prepare it again")
            self.ledger.require_open(inv["period_id"])
            amount = total(ln["amount"] for ln in lines)
            by_phase: dict[str, dict[str, Any]] = {}
            for ln in lines:
                g = by_phase.setdefault(ln["phase_id"], {"phase_code": ln["phase_code"], "hours": ZERO_HOURS, "amount": ZERO})
                g["hours"] += D(ln["hours"])
                g["amount"] = money(g["amount"] + money(ln["amount"]))
            jlines = [{"account": ACCOUNT_AR, "debit": amount, "project_id": inv["project_id"], "party_id": inv["customer_id"], "memo": f"T&M invoice {inv['sequence']} ({invoice_id})"}]
            for phase_id, g in sorted(by_phase.items(), key=lambda kv: (kv[1]["phase_code"].upper(), kv[0])):
                if g["amount"] > 0:
                    jlines.append({"account": ACCOUNT_FEE_REVENUE, "credit": g["amount"], "project_id": inv["project_id"], "party_id": inv["customer_id"],
                                   "memo": f"fee phase {g['phase_code']}: {_fmt_h(g['hours'])} h"})
            j = self.ledger.post(
                period_id=inv["period_id"],
                description=f"T&M invoice {inv['sequence']} billed to customer {inv['customer_id']}",
                lines=jlines,
                source_type=INVOICE_SUBJECT, source_id=invoice_id, source_version=str(inv["version"]), posted_by=actor, approval_id=approval_id,
            )
            now = utcnow_iso()
            conn.execute("UPDATE labor_invoices SET status='billed', approval_id=?, journal_id=?, billed_at=? WHERE id=?", (approval_id, j["id"], now, invoice_id))
            for ln in lines:
                conn.execute("UPDATE labor_entries SET status='billed', updated_at=? WHERE id=? AND status='approved'", (now, ln["entry_id"]))
            self.approvals.invalidate_for_subject(INVOICE_SUBJECT, invoice_id, reason="invoice already billed", actor=actor)
            self.audit.record(actor, "labor.invoice_billed", INVOICE_SUBJECT, invoice_id, {
                "approval_id": approval_id, "journal_id": j["id"], "period_id": inv["period_id"], "customer_id": inv["customer_id"],
                "total": fmt(amount), "entries": [ln["entry_id"] for ln in lines],
            })
        return {
            "invoice": invoice_id, "status": "billed", "journal_id": j["id"], "period_id": inv["period_id"], "customer_id": inv["customer_id"],
            "total": fmt(amount), "line_count": len(lines),
        }

    # ---- practice analytics --------------------------------------------------- #

    def utilization(self, period_id: str, employee_id: str | None = None) -> dict[str, Any]:
        """Billable share of submitted, approved and billed hours dated within the period."""
        period = self._period(period_id)
        sql = (
            "SELECT e.employee_id, e.hours, p.billable FROM labor_entries e JOIN labor_phases p ON p.id = e.phase_id"
            " WHERE e.status IN ('submitted','approved','billed') AND e.work_date BETWEEN ? AND ?"
        )
        params: list[Any] = [period["start_date"], period["end_date"]]
        if employee_id is not None:
            self._employee(employee_id)
            sql += " AND e.employee_id = ?"
            params.append(employee_id)
        agg: dict[str, dict[str, Decimal]] = {}
        if employee_id is not None:
            agg[employee_id] = {"total": ZERO_HOURS, "billable": ZERO_HOURS}
        for r in self.db.query(sql, tuple(params)):
            a = agg.setdefault(r["employee_id"], {"total": ZERO_HOURS, "billable": ZERO_HOURS})
            a["total"] += D(r["hours"])
            if r["billable"]:
                a["billable"] += D(r["hours"])
        names = {r["id"]: r["name"] for r in self.db.query("SELECT id, name FROM parties WHERE kind='employee'")}
        rows = []
        grand_total = ZERO_HOURS
        grand_billable = ZERO_HOURS
        for emp in sorted(agg, key=lambda k: (names.get(k, ""), k)):
            a = agg[emp]
            rows.append({
                "employee_id": emp, "name": names.get(emp), "total_hours": _fmt_h(a["total"]), "billable_hours": _fmt_h(a["billable"]),
                "utilization_percent": _pct(a["billable"], a["total"]),
            })
            grand_total += a["total"]
            grand_billable += a["billable"]
        return {
            "period_id": period_id, "start_date": period["start_date"], "end_date": period["end_date"],
            "basis": "submitted, approved and billed time dated within the period",
            "employees": rows,
            "total": {"total_hours": _fmt_h(grand_total), "billable_hours": _fmt_h(grand_billable), "utilization_percent": _pct(grand_billable, grand_total)},
        }

    def fee_status(self, project_id: str) -> dict[str, Any]:
        """Per-phase fee budget against actual approved or billed time."""
        self._project(project_id)
        phases = []
        tot = {"budget_hours": ZERO_HOURS, "budget_amount": ZERO, "actual_hours": ZERO_HOURS, "actual_cost": ZERO, "actual_bill_value": ZERO}
        for ph in self.phases(project_id):
            rows = self.db.query(
                "SELECT hours, cost_amount, bill_amount FROM labor_entries WHERE phase_id=? AND status IN ('approved','billed')",
                (ph["id"],),
            )
            hours = _sum_hours(r["hours"] for r in rows)
            cost = total(r["cost_amount"] for r in rows)
            value = total(r["bill_amount"] for r in rows)
            budget_hours = D(ph["fee_budget_hours"])
            budget_amount = money(ph["fee_budget_amount"])
            over_hours = hours > budget_hours
            over_amount = cost > budget_amount
            phases.append({
                "phase_id": ph["id"], "code": ph["code"], "name": ph["name"], "billable": ph["billable"],
                "budget_hours": _fmt_h(budget_hours), "budget_amount": fmt(budget_amount),
                "actual_hours": _fmt_h(hours), "actual_cost": fmt(cost), "actual_bill_value": fmt(value),
                "percent_spent": _pct(cost, budget_amount), "percent_hours": _pct(hours, budget_hours),
                "remaining_amount": fmt(budget_amount - cost), "remaining_hours": _fmt_h(budget_hours - hours),
                "over_budget_hours": over_hours, "over_budget_amount": over_amount, "over_budget": over_hours or over_amount,
            })
            tot["budget_hours"] += budget_hours
            tot["budget_amount"] = money(tot["budget_amount"] + budget_amount)
            tot["actual_hours"] += hours
            tot["actual_cost"] = money(tot["actual_cost"] + cost)
            tot["actual_bill_value"] = money(tot["actual_bill_value"] + value)
        over_h = tot["actual_hours"] > tot["budget_hours"]
        over_a = tot["actual_cost"] > tot["budget_amount"]
        return {
            "project_id": project_id,
            "basis": "approved and billed time at cost",
            "phases": phases,
            "total": {
                "budget_hours": _fmt_h(tot["budget_hours"]), "budget_amount": fmt(tot["budget_amount"]),
                "actual_hours": _fmt_h(tot["actual_hours"]), "actual_cost": fmt(tot["actual_cost"]), "actual_bill_value": fmt(tot["actual_bill_value"]),
                "percent_spent": _pct(tot["actual_cost"], tot["budget_amount"]), "percent_hours": _pct(tot["actual_hours"], tot["budget_hours"]),
                "remaining_amount": fmt(tot["budget_amount"] - tot["actual_cost"]), "remaining_hours": _fmt_h(tot["budget_hours"] - tot["actual_hours"]),
                "over_budget_hours": over_h, "over_budget_amount": over_a, "over_budget": over_h or over_a,
                "phases_over_budget": sum(1 for p in phases if p["over_budget"]),
            },
        }

    # ---- close checklist and state ----------------------------------------------- #

    def close_checks(self, period_id: str) -> list[dict[str, Any]]:
        """Conditions that must hold before ``period_id`` closes; every failing one blocks."""
        period = self._period(period_id)

        def ids(rows: list[dict[str, Any]], limit: int = 5) -> str:
            shown = ", ".join(r["id"] for r in rows[:limit])
            return shown + (f" and {len(rows) - limit} more" if len(rows) > limit else "")

        pending = self.db.query("SELECT id FROM labor_timesheets WHERE period_id=? AND status='submitted' ORDER BY submitted_at, id", (period_id,))
        draft_time = self.db.query(
            "SELECT id FROM labor_entries WHERE status='draft' AND work_date BETWEEN ? AND ? ORDER BY work_date, id",
            (period["start_date"], period["end_date"]),
        )
        draft_invoices = self.db.query("SELECT id FROM labor_invoices WHERE period_id=? AND status='draft' ORDER BY sequence, id", (period_id,))
        draft_payroll = self.db.query("SELECT id FROM labor_payroll WHERE period_id=? AND status='draft' ORDER BY created_at, id", (period_id,))
        rec = self.accrued_payroll_reconciliation(period_id)
        tm = self.tm_receivable_reconciliation(period_id)
        return [
            {
                "check": "labor: submitted timesheets approved or rejected",
                "ok": not pending,
                "detail": (f"{len(pending)} timesheet(s) await approval: {ids(pending)}" if pending else "no timesheets await approval"),
            },
            {
                "check": "labor: no unsubmitted draft time dated in the period",
                "ok": not draft_time,
                "detail": (f"{len(draft_time)} draft time entr{'y' if len(draft_time) == 1 else 'ies'} dated {period['start_date']} to {period['end_date']} "
                           f"must be submitted or voided before close, or the labor cost is never booked: {ids(draft_time)}"
                           if draft_time else "no draft time dated in the period"),
            },
            {
                "check": "labor: no draft T&M invoices",
                "ok": not draft_invoices,
                "detail": (f"{len(draft_invoices)} draft invoice(s) must be billed or voided: {ids(draft_invoices)}" if draft_invoices else "no draft T&M invoices"),
            },
            {
                "check": "labor: no draft payroll",
                "ok": not draft_payroll,
                "detail": (f"{len(draft_payroll)} draft payroll settlement(s) must be posted or canceled: {ids(draft_payroll)}"
                           if draft_payroll else "no draft payroll in the period"),
            },
            {
                "check": "labor: accrued payroll subledger reconciles to 2200",
                "ok": rec["reconciled"],
                "detail": f"through {period_id}: subledger {rec['subledger_total']} (approved cost less posted payroll) vs control 2200 {rec['control_balance']}",
            },
            {
                "check": "labor: no employee's accrued payroll overdrawn",
                "ok": not rec["overdrawn"],
                "detail": (f"payroll exceeds approved time through {period_id} for {', '.join(rec['overdrawn'])}" if rec["overdrawn"]
                           else f"no accrued payroll balance is a debit through {period_id}"),
            },
            {
                "check": "labor: T&M receivables agree with the labor postings to 1100",
                "ok": tm["reconciled"],
                "detail": (f"through {period_id}: T&M subledger {tm['subledger_total']} (billed less collected) vs labor invoice and collection "
                           f"lines on 1100 {tm['labor_postings_1100']}"
                           + (f"; overcollected: {', '.join(tm['overcollected'])}" if tm["overcollected"] else "")
                           + " (the 1100 control itself is reconciled by the core AR check, which includes this subledger)"),
            },
        ]

    def audit_export(self) -> dict[str, Any]:
        """Every labor record, workspace-wide, plus the module's reconciliations, for an
        independent reviewer (JSON-serialisable; money as canonical strings)."""
        q = self.db.query
        timesheets = q("SELECT * FROM labor_timesheets ORDER BY submitted_at, id")
        for ts in timesheets:
            ts["lines"] = loads(ts.pop("lines_json"))
        invoice_lines = q("SELECT * FROM labor_invoice_lines ORDER BY invoice_id, work_date, entry_id")
        for ln in invoice_lines:
            ln["released"] = bool(ln["released"])
        return {
            "posting_rule": POSTING_RULE,
            "rates": q("SELECT * FROM labor_rates ORDER BY employee_id, effective_from"),
            "phases": q("SELECT * FROM labor_phases ORDER BY project_id, code"),
            "entries": q("SELECT * FROM labor_entries ORDER BY employee_id, work_date, id"),
            "timesheets": timesheets,
            "payroll": q("SELECT * FROM labor_payroll ORDER BY created_at, id"),
            "invoices": q("SELECT * FROM labor_invoices ORDER BY project_id, sequence"),
            "invoice_lines": invoice_lines,
            "collections": q("SELECT * FROM labor_collections ORDER BY received_at, id"),
            "reconciliations": {
                "accrued_payroll_2200": self.accrued_payroll_reconciliation(),
                "tm_receivables_1100": self.tm_receivable_reconciliation(),
                "ar_open_items": self.ar_open_items(),
            },
        }

    def state(self, project_id: str) -> dict[str, Any]:
        entries = self.entries(project_id)
        by_status: dict[str, dict[str, Any]] = {}
        for st in LIVE_ENTRY_STATUSES + ("void",):
            rows = [e for e in entries if e["status"] == st]
            by_status[st] = {
                "count": len(rows), "hours": _fmt_h(_sum_hours(e["hours"] for e in rows)),
                "cost": fmt(total(e["cost_amount"] for e in rows)), "bill_value": fmt(total(e["bill_amount"] for e in rows)),
            }
        fees = self.fee_status(project_id) if self.db.one("SELECT id FROM projects WHERE id=?", (project_id,)) else {"phases": [], "total": {}}
        open_periods = self.db.query("SELECT id FROM periods WHERE status='open' ORDER BY start_date")
        return {
            "phases": fees["phases"],
            "fee_total": fees["total"],
            "entries": {"by_status": by_status, "items": entries},
            "timesheets": self.timesheets(project_id=project_id),
            "invoices": self.invoices(project_id),
            "utilization": [self.utilization(p["id"]) for p in open_periods],
            "accrued_payroll": self.accrued_payroll_reconciliation(),
            "receivables": self.ar_open_items(project_id),
            "ledger": {
                "labor_cost_5300": fmt(self.ledger.balance(ACCOUNT_LABOR_COST, project_id=project_id)),
                "fee_revenue_4100": fmt(self.ledger.balance(ACCOUNT_FEE_REVENUE, project_id=project_id)),
            },
        }
