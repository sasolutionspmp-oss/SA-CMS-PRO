"""Executable accounting-core decision gates and the weighted candidate scorecard.

Plan reference: CIPHER-PLAN-v1.0 section 3 ("Accounting foundation decision") and
section 13, decision 4 ("choose the two serious accounting candidates and accept
the hard gates/weighted scorecard").  The plan's hard gates become nine
executable gates that drive a candidate accounting core through a
``LedgerAdapter``:

    G1 exact decimal arithmetic and rounding
    G2 balanced and atomic posting
    G3 immutable corrections
    G4 period locks on every path
    G5 idempotency
    G6 approval binding
    G7 audit export completeness
    G8 restore safety
    G9 subledger-to-GL reconciliation

Each gate returns ``{"gate", "title", "status", "evidence", "checks",
"failed_checks", "advisories"}`` where ``status`` is ``pass``, ``fail`` or
``not_run`` and every evidence line carries the concrete numbers observed.  A gate
passes only when every one of its hard checks passes; ``failed_checks`` lists the
stable keys of the hard checks that failed.

Honest gates (the rules every gate follows):

* A scenario the harness runs and finds failing is a hard FAIL.  It is never
  downgraded to a note so that a candidate can pass.
* A refusal counts only when it comes from the control under test.  The adapter
  declares, per control, a pattern its refusals carry (``refusal_markers``); an
  error whose reason does not match (malformed SQL, an unknown subject, a foreign
  key error) is "not refused by the expected control" and fails the check.
  Programming errors (``TypeError``, ``AttributeError`` ...) are never refusals.
* Where a path can be shown to work, a positive control runs first: each plugin
  posting path posts in an open period before the same path is driven into a
  closed one, the governed reopen succeeds with a recorded approval and the
  write-authority claim with a genuine attestation, while a fabricated reference
  or credential is refused.
* A registered plugin whose probe cannot be prepared fails G4 (the path was not
  proved), and a broken employee-reimbursement scenario fails G9 instead of
  reconciling 0.00 = 0.00.
* A check follows the control as the candidate designs it, never a weaker
  stand-in: privileged (raw SQL) writes are driven against the schema controls
  the candidate claims (journal seal, period triggers, SQLite read-only copies),
  and a restored copy's write-authority claim is driven through the attestation
  the candidate requires (for the native core, an owner claim code computed from
  ``CIPHER_OWNER_SECRET``, which the adapter configures for the drill only).

*Advisories* are non-gating observations beyond a gate's specification text
(status ``pass`` or ``open``).  They lower the computed control-fit score but never
disqualify a candidate on their own.

A candidate that passes every hard gate is scored with the plan's weights
(accounting/control fit 35, AEC fit 20, maintainability/upgrades 20,
ownership/licensing 15, delivery cost 10; each 0-5).  Control fit is computed
from the executed checks; the other four come from the adapter and must be
labelled ASSUMPTION with a rationale.  A candidate failing any hard gate is
``disqualified`` and is not scored; an unavailable candidate is
``not_evaluated``.

What a pass proves: the candidate's control *mechanics* on synthetic data.  It
does not prove accounting-policy correctness, statements, tax, migration or
production readiness.  See ``apps/cipher/docs/CORE_COMPARISON.md``.

Nothing here installs, pulls or starts anything.  The ERPNext adapter reports
itself unavailable, so every gate is ``not_run`` for it.

CLI::

    python -m apps.cipher.tools.core_gates [--out FILE]

prints the JSON scorecard and exits 0 when the native core passes every hard gate
(1 otherwise).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Iterator

from ..core.approvals import ApprovalError, build_manifest
from ..core.ids import hash_json, loads, new_id, sha256_hex, utcnow_iso
from ..core.money import D, allocate, fmt, money, total
from ..domain.ledger import RULE_VERSION

SCORECARD_VERSION = "cipher-core-gates/3"
PLAN_REFERENCE = "CIPHER-PLAN-v1.0 section 3 (Accounting foundation decision) and section 13 decision 4"

GATE_IDS = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9")
GATE_TITLES = {
    "G1": "Exact decimal arithmetic and rounding",
    "G2": "Balanced and atomic posting",
    "G3": "Immutable corrections",
    "G4": "Period locks on every path",
    "G5": "Idempotency",
    "G6": "Approval binding",
    "G7": "Audit export completeness",
    "G8": "Restore safety",
    "G9": "Subledger-to-GL reconciliation",
}

# Plan section 3: "score accounting/control fit 35%, AEC fit 20%, maintainability/upgrades 20%,
# ownership/licensing 15% and delivery cost 10%".
WEIGHTS = {
    "accounting_control_fit": 35,
    "aec_fit": 20,
    "maintainability_upgrades": 20,
    "ownership_licensing": 15,
    "delivery_cost": 10,
}
CRITERIA_LABELS = {
    "accounting_control_fit": "Accounting/control fit",
    "aec_fit": "AEC fit",
    "maintainability_upgrades": "Maintainability/upgrades",
    "ownership_licensing": "Ownership/licensing",
    "delivery_cost": "Delivery cost",
}
ASSUMED_CRITERIA = ("aec_fit", "maintainability_upgrades", "ownership_licensing", "delivery_cost")
MAX_SCORE = Decimal(5)
TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")

# Triggers the audit export's schema manifest must list: the controls the gates rely on.
# The first eight are the original immutability and period-lock triggers; the rest are
# the schema controls the core now uses for them (cipher-core-gates/3): the journal seal
# (declared line count, sealed lines, completion guard), period integrity (locked periods
# immutable, reopen only with a consumed reopen approval) and append-only approvals.
REQUIRED_TRIGGERS = (
    "journals_no_update",
    "journals_no_delete",
    "journal_lines_no_update",
    "journal_lines_no_delete",
    "journals_period_open",
    "journal_lines_period_open",
    "audit_log_no_update",
    "audit_log_no_delete",
    "journals_declare_line_count",
    "journal_lines_sealed",
    "journal_unsealed_guard",
    "periods_locked_immutable",
    "periods_reopen_requires_approval",
    "approvals_lifecycle",
    "approvals_no_delete",
)

# Allocation scenarios for G1: (amount, weights).  Every part must sum exactly, be whole
# cents, never be negative and stay within one cent of its exact proportional share.
ALLOCATION_CASES: tuple[tuple[str, list], ...] = (
    ("100.00", [1, 1, 1]),
    ("0.10", [1, 1, 1]),
    ("1000.00", ["0.3333", "0.3333", "0.3334"]),
    ("27000.00", [20000, 10000]),
    ("110000.00", [70000, 40000]),
    ("0.05", [1, 1, 1, 1, 1, 1, 1]),
)

# Controls whose refusals the gates attribute by reason (see LedgerAdapter.refusal_markers).
CONTROL_EXACT_MONEY = "exact_money"
CONTROL_JOURNAL_SEAL = "journal_seal"
CONTROL_IMMUTABILITY = "immutability"
CONTROL_PERIOD_LOCK = "period_lock"
CONTROL_WRITE_AUTHORITY = "write_authority"
CONTROL_QUARANTINE = "release_quarantine"
CONTROL_APPROVAL_REFERENCE = "approval_reference"
REFUSAL_CONTROLS = (CONTROL_EXACT_MONEY, CONTROL_JOURNAL_SEAL, CONTROL_IMMUTABILITY, CONTROL_PERIOD_LOCK, CONTROL_WRITE_AUTHORITY,
                    CONTROL_QUARANTINE, CONTROL_APPROVAL_REFERENCE)
# A declared marker must not match an empty reason or these generic, unrelated failures.
_UNRELATED_REASONS = (
    "",
    "OperationalError: no such column: debitt",
    "OperationalError: table journals has no column named period_idd",
    "IntegrityError: FOREIGN KEY constraint failed",
    "RuntimeError: something unrelated went wrong",
)

DOES_NOT_PROVE = [
    "accounting-policy correctness (revenue recognition, WIP, retainage classification, accruals): controller-approved policies do not exist yet",
    "financial statements, tax, multi-entity or multi-currency behaviour",
    "migration of real data or parallel closes against the incumbent books",
    "production readiness: security, isolation, performance, backup operations, provider contracts",
    "the payment kill switch and signed provider callbacks: no gate drives them (their module tests do)",
    "anything about ERPNext or Odoo: neither was installed or run here",
]

ERPNEXT_UNAVAILABLE = (
    "not provisioned: requires an isolated container stack (database, cache, Frappe/ERPNext images) "
    "and separate execution authorization; see CORE_COMPARISON.md"
)

# Exceptions that indicate a broken adapter or gate rather than a refused operation.
# They are never counted as a "rejection"; they abort the gate (or fail the check), never pass it.
_PROGRAMMING_ERRORS = (TypeError, AttributeError, NameError, NotImplementedError, KeyError, IndexError, AssertionError)


class CoreGateError(RuntimeError):
    """Invalid use of the gate runner (unknown gate, malformed adapter score or refusal marker)."""


class GateFault(RuntimeError):
    """A failure the gates inject on purpose to prove atomicity."""


# --------------------------------------------------------------------------- #
# Adapter interface                                                            #
# --------------------------------------------------------------------------- #

class LedgerAdapter:
    """What a candidate accounting core must expose for the gates to run.

    Amounts cross this boundary as strings or ``Decimal``.  Journal ``lines`` are
    ``[{"account", "debit" | "credit", "project_id"?, "party_id"?, "memo"?}]``.
    Workspace-mutating operations act on the workspace created by the last
    ``reset``.  A candidate that cannot be exercised returns ``(False, reason)``
    from ``available`` and every gate reports ``not_run``; nothing else is called.
    """

    candidate = "abstract"
    label = "abstract ledger adapter"

    def available(self) -> tuple[bool, str]:
        return False, "abstract adapter"

    def _unsupported(self, operation: str):
        raise NotImplementedError(f"the {self.candidate} adapter does not implement {operation!r}")

    def refusal_markers(self) -> dict[str, str]:
        """``{control: regex}`` for every control in ``REFUSAL_CONTROLS``.  The regex is
        searched case-insensitively in ``"ExceptionType: message"``; a refusal whose reason
        does not match the expected control's pattern is an unrelated error, not the
        control working.  Patterns may not match an empty or generic unrelated reason."""
        return {}

    # ---- workspace ---------------------------------------------------------- #
    def reset(self, path: str | None = None) -> None:
        """Start a fresh, empty synthetic workspace (in memory, or a file at ``path``)."""
        self._unsupported("reset")

    def close(self) -> None:
        """Release the current workspace.  Must be safe to call repeatedly."""

    # ---- money -------------------------------------------------------------- #
    def to_money(self, value) -> Decimal:
        """Parse and quantise an amount to cents (half-up); reject inexact or non-finite inputs."""
        self._unsupported("to_money")

    def add_money(self, a, b) -> Decimal:
        self._unsupported("add_money")

    def sum_money(self, values) -> Decimal:
        self._unsupported("sum_money")

    def allocate(self, amount, weights) -> list[Decimal]:
        """Split ``amount`` by ``weights`` so the parts sum exactly to ``amount``."""
        self._unsupported("allocate")

    # ---- periods ------------------------------------------------------------ #
    def open_period(self, period_id: str, start_date: str, end_date: str) -> None:
        self._unsupported("open_period")

    def close_period(self, period_id: str) -> None:
        self._unsupported("close_period")

    def lock_period(self, period_id: str) -> None:
        self._unsupported("lock_period")

    def reopen_period(self, period_id: str, approval_ref: str) -> None:
        """The candidate's lowest-level reopen that takes an approval reference."""
        self._unsupported("reopen_period")

    def reopen_period_approved(self, period_id: str) -> str:
        """Reopen a closed period through the candidate's governed path with a recorded
        approval; returns the approval reference."""
        self._unsupported("reopen_period_approved")

    def period_reopen_count(self, period_id: str) -> int:
        """How many reopens of ``period_id`` the candidate has recorded."""
        self._unsupported("period_reopen_count")

    def period_status(self, period_id: str) -> str:
        self._unsupported("period_status")

    # ---- general ledger ------------------------------------------------------- #
    def post_journal(self, *, period_id: str, lines: list[dict[str, Any]], source_id: str, description: str = "core gate journal") -> str:
        """Post one journal through the candidate's ordinary posting path; returns its id."""
        self._unsupported("post_journal")

    def reverse_journal(self, journal_id: str, *, period_id: str, reason: str) -> str:
        """Correct a posted journal by the candidate's supported (governed, approval-bound
        where the candidate has one) correction path; returns the new id."""
        self._unsupported("reverse_journal")

    def journal(self, journal_id: str) -> dict[str, Any]:
        """``{id, period_id, description, source_type, source_id, source_version, rule_version,
        approval_id, reversal_of, posted_by, lines: [{account, debit, credit}]}``"""
        self._unsupported("journal")

    def journal_ids(self) -> list[str]:
        self._unsupported("journal_ids")

    def journal_count(self) -> int:
        self._unsupported("journal_count")

    def balance(self, account: str, *, project_id: str | None = None) -> Decimal:
        """Natural balance of ``account`` (debit-positive for assets and expenses)."""
        self._unsupported("balance")

    def trial_balance(self) -> dict[str, Any]:
        """``{balanced: bool, total_debit: str, total_credit: str, journal_count: int}``"""
        self._unsupported("trial_balance")

    def run_command(self, op_id: str, payload: dict[str, Any], journals: list[dict[str, Any]], *, fail_after: int | None = None) -> dict[str, Any]:
        """Post ``journals`` (``post_journal`` keyword dicts) as ONE idempotent logical
        operation ``op_id``.  ``fail_after=n`` injects a fault after ``n`` journals.
        Returns ``{replayed: bool, result: ...}``."""
        self._unsupported("run_command")

    def command_recorded(self, op_id: str) -> bool:
        self._unsupported("command_recorded")

    def privileged_tamper(self, action: str, target_id: str) -> None:
        """Attempt a direct database write that bypasses the application:
        ``update_amount``, ``update_description``, ``delete_lines``, ``delete_journal``,
        ``unlink_reversal`` (target: a journal id) or ``update_audit`` (target: unused)."""
        self._unsupported("privileged_tamper")

    def privileged_insert_journal(self, period_id: str) -> None:
        """Attempt a direct database INSERT of a journal header into ``period_id``."""
        self._unsupported("privileged_insert_journal")

    def privileged_insert_line(self, journal_id: str) -> None:
        """Attempt a direct database INSERT of a 1.00 debit line onto an existing journal."""
        self._unsupported("privileged_insert_line")

    def privileged_insert_raw_journal(self, period_id: str, lines: list[dict[str, Any]], declared_lines: int | None) -> None:
        """Attempt, in one privileged database transaction, a direct INSERT of a journal
        header into ``period_id`` declaring ``declared_lines`` lines (``None``: declares
        nothing), followed by direct INSERTs of ``lines`` - bypassing the posting path."""
        self._unsupported("privileged_insert_raw_journal")

    def privileged_unlock_period(self, period_id: str) -> None:
        """Attempt a direct database UPDATE that sets a period's status back to open."""
        self._unsupported("privileged_unlock_period")

    def privileged_reopen_period(self, period_id: str, approval_ref: str) -> None:
        """Attempt a direct database UPDATE that reopens a closed period citing ``approval_ref``."""
        self._unsupported("privileged_reopen_period")

    def privileged_lift_write_guard(self) -> None:
        """Attempt, from a privileged database session, to switch off the guard that keeps a
        copy without write authority read-only."""
        self._unsupported("privileged_lift_write_guard")

    # ---- audit ------------------------------------------------------------------ #
    def audit_export(self) -> dict[str, Any]:
        """The full audit export in the Cipher export shape (sections schema, chart_of_accounts,
        periods, trial_balance, journals, approvals, ap_reconciliation, ar_reconciliation, audit)."""
        self._unsupported("audit_export")

    def audit_row_count(self) -> int:
        """Rows in the candidate's audit log, read from storage (not from the export)."""
        self._unsupported("audit_row_count")

    # ---- commercial scenario ----------------------------------------------------- #
    def setup_project(self) -> dict[str, Any]:
        """Verified supplier, customer and project: ``{project_id, supplier_id, customer_id, destination}``."""
        self._unsupported("setup_project")

    def setup_commitment(self, project: dict[str, Any], amounts: tuple[str, ...] = ("60000.00", "40000.00")) -> dict[str, Any]:
        """An executed subcontract with 10% retainage: ``{commitment_id, line_ids, executed_amount, supplier_id}``."""
        self._unsupported("setup_commitment")

    def certify_bill(self, commitment_id: str, period_id: str, line_id: str, cumulative_installed: str) -> dict[str, Any]:
        self._unsupported("certify_bill")

    def bill_status(self, bill_id: str) -> str:
        self._unsupported("bill_status")

    def setup_sent_prime_bill(self, project: dict[str, Any], period_id: str, certified_cumulative: str) -> dict[str, Any]:
        self._unsupported("setup_sent_prime_bill")

    def record_collection(self, prime_bill_id: str, period_id: str, amount: str, provider_ref: str) -> dict[str, Any]:
        """Record a customer collection through the candidate's ordinary (console/API) action."""
        self._unsupported("record_collection")

    def propose_change(self, commitment_id: str, amount: str, line_id: str) -> str:
        self._unsupported("propose_change")

    def commitment_amount(self, commitment_id: str) -> str:
        self._unsupported("commitment_amount")

    # ---- approvals -------------------------------------------------------------- #
    def request_and_grant(self, operation: str, subject_id: str, *, actor_role: str = "owner") -> str:
        self._unsupported("request_and_grant")

    def execute_approval(self, approval_id: str, *, op_id: str | None = None, period_id: str | None = None, actor: str = "gate") -> dict[str, Any]:
        self._unsupported("execute_approval")

    def approve_and_execute(self, operation: str, subject_id: str, *, actor_role: str = "owner", period_id: str | None = None) -> dict[str, Any]:
        self._unsupported("approve_and_execute")

    def approval_status(self, approval_id: str) -> str:
        self._unsupported("approval_status")

    def approval_exists(self, approval_ref: str) -> bool:
        self._unsupported("approval_exists")

    def bound_approval_probe(self, *, approved_amount: str, current_amount: str) -> dict[str, Any]:
        """Grant an approval bound to ``approved_amount`` and consume it against ``current_amount``:
        ``{outcome: "consumed" | <refusal>, status}``."""
        self._unsupported("bound_approval_probe")

    def change_destination(self, party_id: str, destination: str, *, verified: bool = True) -> None:
        """Change a payee's destination, through independent verification or a raw master-data edit."""
        self._unsupported("change_destination")

    # ---- payments and recovery ----------------------------------------------------- #
    def payment_intents(self) -> list[dict[str, Any]]:
        self._unsupported("payment_intents")

    def provider_counts(self) -> dict[str, int]:
        """``{transfers, submissions}`` at the (simulated) payment provider."""
        self._unsupported("provider_counts")

    def set_provider_mode(self, mode: str) -> None:
        self._unsupported("set_provider_mode")

    def dispatch_payments(self) -> list[dict[str, Any]]:
        self._unsupported("dispatch_payments")

    def snapshot(self, path: str) -> str:
        self._unsupported("snapshot")

    def open_restored(self, path: str) -> "LedgerAdapter":
        """A second adapter bound to a restored copy at ``path`` (sharing the provider)."""
        self._unsupported("open_restored")

    def authority_status(self) -> dict[str, Any]:
        """``{effective_write_authority, recovery_epoch, reconciled_epoch, release_quarantined}``"""
        self._unsupported("authority_status")

    def claim_write_authority(self, credential: str) -> None:
        """Attempt the candidate's write-authority claim on this copy, in its governed
        configuration, presenting ``credential`` (a fabricated approval reference or claim
        code, or a blank one) as the claim's only authorisation; every other part of the
        claim is well formed."""
        self._unsupported("claim_write_authority")

    def claim_write_authority_approved(self) -> dict[str, Any]:
        """Claim write authority through the governed path with a genuine authorisation
        (for the native core: an attested owner claim carrying a valid owner claim code).
        Returns ``{ref, credential}``: the stored claim record's reference and the
        credential that was presented."""
        self._unsupported("claim_write_authority_approved")

    def claim_write_authority_default_config(self, credential: str) -> None:
        """Attempt the same claim as ``claim_write_authority`` in the candidate's default
        configuration (for the native core: no ``CIPHER_OWNER_SECRET``)."""
        self._unsupported("claim_write_authority_default_config")

    def authority_claims(self) -> list[dict[str, Any]]:
        """Every recorded write-authority claim, read from storage:
        ``[{ref, approver, reason, verified}]`` (``verified``: the claim's credential was
        checked against something the copy itself cannot mint)."""
        self._unsupported("authority_claims")

    def complete_recovery(self) -> dict[str, Any]:
        self._unsupported("complete_recovery")

    def ap_reconciliation(self) -> dict[str, Any]:
        self._unsupported("ap_reconciliation")

    # ---- fixture and subledgers ---------------------------------------------------- #
    def run_golden_fixture(self) -> dict[str, Any]:
        """Run the plan section 10 synthetic fixture: ``{project_id, open_period, result}``."""
        self._unsupported("run_golden_fixture")

    def subledger_reconciliation(self, project_id: str) -> dict[str, Any]:
        """``{ap, ar, employee_payable}``, each ``{subledger_total, control_balance, reconciled}`` (employee may be None)."""
        self._unsupported("subledger_reconciliation")

    def add_employee_reimbursement(self, project_id: str, period_id: str, amount: str, paid: str) -> dict[str, Any] | None:
        """Approve and partly pay an employee claim; ``None`` when the candidate has no such subledger."""
        self._unsupported("add_employee_reimbursement")

    # ---- extension paths ------------------------------------------------------------ #
    def registered_plugins(self) -> list[str]:
        return []

    def plugin_period_lock_probes(self, project: dict[str, Any]) -> list[dict[str, Any]]:
        """One probe per registered extension posting path, prepared in an open period:
        ``{plugin, path, period, control_detail, detail, run_control, close, attempt, status}``
        where ``run_control()`` drives a twin subject through the path while the period is
        open, ``close()`` closes the period, ``attempt()`` drives the probe subject into the
        closed period and ``status()`` reads the probe subject's state.  A probe whose
        preparation failed is ``{plugin, path, setup_error}``."""
        return []

    # ---- scorecard ------------------------------------------------------------------- #
    def assumed_scores(self) -> dict[str, tuple[int | str | Decimal, str]] | None:
        """``{criterion: (score 0-5, rationale)}`` for the four non-computed criteria."""
        return None


# --------------------------------------------------------------------------- #
# Native Cipher adapter                                                        #
# --------------------------------------------------------------------------- #

class NativeCipherAdapter(LedgerAdapter):
    """Wraps ``apps.cipher.service.Cipher``: its ledger, approvals, commands, payments,
    restore controls and registered plugins.  Every workspace is synthetic."""

    candidate = "native_cipher"
    label = "Native Cipher GL/subledgers (this repository: Python standard library + SQLite)"

    _TAMPER_SQL = {
        "update_amount": "UPDATE journal_lines SET debit='9999.00' WHERE journal_id=? AND line_no=1",
        "update_description": "UPDATE journals SET description='altered by a privileged path' WHERE id=?",
        "delete_lines": "DELETE FROM journal_lines WHERE journal_id=?",
        "delete_journal": "DELETE FROM journals WHERE id=?",
        "unlink_reversal": "UPDATE journals SET reversal_of=NULL WHERE id=?",
    }

    def __init__(self):
        self.c = None
        self._serial = 0
        # The owner secret the restore drill configures (CIPHER_OWNER_SECRET) while a claim
        # runs; synthetic, per adapter, shared with the restored copies it opens.
        self._owner_secret = "gate-owner-secret-" + secrets.token_hex(16)

    def available(self) -> tuple[bool, str]:
        return True, "in-process: apps.cipher.service.Cipher on a synthetic SQLite workspace"

    def refusal_markers(self) -> dict[str, str]:
        return {
            CONTROL_EXACT_MONEY: r"MoneyError|non-finite|binary floating point|boolean is not a monetary value",
            CONTROL_JOURNAL_SEAL: r"sealed line count|journal does not balance",
            CONTROL_IMMUTABILITY: r"immutable|append-only",
            CONTROL_PERIOD_LOCK: r"PeriodNotOpen|period is not open|period \S+ is (?:closed|locked)",
            CONTROL_WRITE_AUTHORITY: r"WriteAuthorityError|write authority",
            CONTROL_QUARANTINE: r"ReleaseQuarantined|quarantined",
            CONTROL_APPROVAL_REFERENCE: r"approval",
        }

    # ---- workspace ---------------------------------------------------------- #
    def reset(self, path: str | None = None) -> None:
        from ..service import Cipher

        self.close()
        self.c = Cipher(path or ":memory:")

    def close(self) -> None:
        if self.c is not None:
            try:
                self.c.db.close()
            except Exception:  # already closed
                pass
            self.c = None

    def _next(self) -> int:
        self._serial += 1
        return self._serial

    # ---- money -------------------------------------------------------------- #
    def to_money(self, value) -> Decimal:
        return money(value)

    def add_money(self, a, b) -> Decimal:
        return money(D(a) + D(b))

    def sum_money(self, values) -> Decimal:
        return total(values)

    def allocate(self, amount, weights) -> list[Decimal]:
        return allocate(amount, weights)

    # ---- periods ------------------------------------------------------------ #
    def open_period(self, period_id, start_date, end_date) -> None:
        self.c.open_period(period_id, period_id, start_date, end_date, actor="gate")

    def close_period(self, period_id) -> None:
        self.c.close_period(period_id, actor="gate")

    def lock_period(self, period_id) -> None:
        self.c.ledger.lock_period(period_id, actor="gate")

    def reopen_period(self, period_id, approval_ref) -> None:
        self.c.ledger.reopen_period(period_id, actor="gate", approval_ref=approval_ref)

    def reopen_period_approved(self, period_id) -> str:
        # The close module owns the governed, approval-bound reopen (close.reopen_period).  The
        # core has no other governed path: minting a "*.reopen_period" approval straight
        # through Approvals would bypass the role check, so without the module this refuses.
        if "close" not in self._plugins():
            raise CoreGateError("no governed reopen path: the close module (close.reopen_period) is not registered")
        ap = self.c.request_approval("close.reopen_period", period_id, actor_role="controller", requested_by="gate")
        self.c.approve(ap["id"], approver="gate-controller")
        self.c.execute(ap["id"], actor="gate-controller", period_id=period_id)
        return ap["id"]

    def period_reopen_count(self, period_id) -> int:
        return int(self.c.db.scalar("SELECT COUNT(*) FROM period_reopens WHERE period_id=?", (period_id,)))

    def period_status(self, period_id) -> str:
        return self.c.ledger.period(period_id)["status"]

    # ---- general ledger ------------------------------------------------------- #
    def post_journal(self, *, period_id, lines, source_id, description="core gate journal") -> str:
        j = self.c.ledger.post(period_id=period_id, description=description, lines=lines, source_type="core_gate",
                               source_id=source_id, source_version="1", posted_by="gate")
        return j["id"]

    def reverse_journal(self, journal_id, *, period_id, reason) -> str:
        # The governed correction (journal.reverse): a recorded reversal request, an approval
        # that binds it, and execution into an open period.
        if getattr(self.c, "_core_owner", lambda op: None)("journal.reverse") is self.c.ledger:
            self.c.ledger.prepare_reversal(journal_id, reason, "gate")
            r = self.c.approve_and_execute("journal.reverse", journal_id, actor="gate", period_id=period_id)
            return r.result["reversal_journal_id"]
        return self.c.ledger.reverse(journal_id, period_id=period_id, posted_by="gate", reason=reason)["id"]

    def journal(self, journal_id) -> dict[str, Any]:
        j = self.c.ledger.journal(journal_id)
        out = {k: j[k] for k in ("id", "period_id", "description", "source_type", "source_id", "source_version", "rule_version", "approval_id", "reversal_of", "posted_by")}
        out["lines"] = [{"account": ln["account_code"], "debit": ln["debit"], "credit": ln["credit"]} for ln in j["lines"]]
        return out

    def journal_ids(self) -> list[str]:
        return [r["id"] for r in self.c.db.query("SELECT id FROM journals ORDER BY posted_at, id")]

    def journal_count(self) -> int:
        return int(self.c.db.scalar("SELECT COUNT(*) FROM journals"))

    def balance(self, account, *, project_id=None) -> Decimal:
        if project_id:
            return self.c.ledger.balance(account, project_id=project_id)
        return self.c.ledger.balance(account)

    def trial_balance(self) -> dict[str, Any]:
        return self.c.ledger.trial_balance()

    def run_command(self, op_id, payload, journals, *, fail_after=None) -> dict[str, Any]:
        def handler():
            posted = []
            for index, spec in enumerate(journals):
                if fail_after is not None and index == fail_after:
                    raise GateFault(f"injected fault after {index} of {len(journals)} journals")
                posted.append(self.post_journal(**spec))
            if fail_after is not None and fail_after >= len(journals):
                raise GateFault(f"injected fault after all {len(journals)} journals")
            return {"journals": posted}

        r = self.c.commands.run(op_id, payload, handler, actor="gate")
        return {"replayed": r.replayed, "result": r.result}

    def command_recorded(self, op_id) -> bool:
        return self.c.db.one("SELECT op_id FROM idempotency WHERE op_id=?", (op_id,)) is not None

    def raw_sql(self, sql: str, params: tuple = ()) -> None:
        """The privileged path: a statement executed straight against the database."""
        self.c.db.execute(sql, params)

    def privileged_tamper(self, action, target_id) -> None:
        if action == "update_audit":
            self.raw_sql("UPDATE audit_log SET actor='privileged-editor' WHERE seq=(SELECT MAX(seq) FROM audit_log)")
            return
        if action not in self._TAMPER_SQL:
            raise ValueError(f"unknown tamper action {action!r}")
        self.raw_sql(self._TAMPER_SQL[action], (target_id,))

    def privileged_insert_journal(self, period_id) -> None:
        self.raw_sql(
            "INSERT INTO journals (id, period_id, posted_at, description, source_type, source_id, source_version, rule_version, posted_by) VALUES (?,?,?,?,?,?,?,?,?)",
            (new_id("jrn"), period_id, utcnow_iso(), "privileged insert", "core_gate", "privileged-insert", "1", RULE_VERSION, "privileged-editor"),
        )

    def privileged_insert_line(self, journal_id) -> None:
        self.raw_sql(
            "INSERT INTO journal_lines (id, journal_id, line_no, account_code, debit, credit, memo) VALUES (?,?,?,?,?,?,?)",
            (new_id("jln"), journal_id, 99, "5000", "1.00", "0.00", "privileged insert"),
        )

    def privileged_insert_raw_journal(self, period_id, lines, declared_lines) -> None:
        # Raw statements grouped in the core's transaction wrapper.  In a bare sqlite3 session
        # an incomplete journal fails the COMMIT with a generic "FOREIGN KEY constraint failed"
        # (the seal's deferred completion marker), which cannot be attributed by its message;
        # the wrapper only names the unsealed journal.  No posting-path code runs.
        jid = new_id("jrn")
        with self.c.db.transaction() as conn:
            conn.execute(
                "INSERT INTO journals (id, period_id, posted_at, description, source_type, source_id, source_version, rule_version, posted_by, line_count) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (jid, period_id, utcnow_iso(), "privileged raw journal", "core_gate", "privileged-raw-journal", "1", RULE_VERSION, "privileged-editor", declared_lines),
            )
            for n, ln in enumerate(lines, start=1):
                conn.execute(
                    "INSERT INTO journal_lines (id, journal_id, line_no, account_code, debit, credit, memo) VALUES (?,?,?,?,?,?,?)",
                    (new_id("jln"), jid, n, ln["account"], ln.get("debit", "0.00"), ln.get("credit", "0.00"), "privileged raw line"),
                )

    def privileged_unlock_period(self, period_id) -> None:
        self.raw_sql("UPDATE periods SET status='open' WHERE id=?", (period_id,))

    def privileged_reopen_period(self, period_id, approval_ref) -> None:
        self.raw_sql("UPDATE periods SET status='open', closed_at=NULL, closed_by=NULL, reopen_approval_id=? WHERE id=?", (approval_ref, period_id))

    def privileged_lift_write_guard(self) -> None:
        self.raw_sql("PRAGMA query_only = OFF")

    # ---- audit ------------------------------------------------------------------ #
    def audit_export(self) -> dict[str, Any]:
        return self.c.audit_export()

    def audit_row_count(self) -> int:
        return int(self.c.db.scalar("SELECT COUNT(*) FROM audit_log"))

    # ---- commercial scenario ----------------------------------------------------- #
    def setup_project(self) -> dict[str, Any]:
        n = self._next()
        destination = f"ACH-SIM-GATE-{n:03d}"
        supplier = self.c.add_party(kind="supplier", name=f"Gate Synthetic Subcontractor {n}", destination=destination, actor="gate")
        self.c.verify_destination(supplier["id"], destination=destination, verified_by="gate-bank-detail-maintainer")
        customer = self.c.add_party(kind="customer", name=f"Gate Synthetic Owner Agency {n}", actor="gate")
        project = self.c.create_project(name=f"Gate synthetic project {n}", entity="S&A Solutions LLC (synthetic)", budget="250000",
                                        customer_id=customer["id"], actor="gate")
        return {"project_id": project["id"], "supplier_id": supplier["id"], "customer_id": customer["id"], "destination": destination}

    def setup_commitment(self, project, amounts=("60000.00", "40000.00")) -> dict[str, Any]:
        cmt = self.c.commitments.create(
            project_id=project["project_id"], supplier_id=project["supplier_id"], title="Gate synthetic subcontract",
            sov_lines=[{"description": f"Gate SOV line {i}", "amount": amt} for i, amt in enumerate(amounts, start=1)],
            retainage_rate="0.10", actor="gate",
        )
        self.c.approve_and_execute("commitment.execute", cmt["id"], actor="gate")
        got = self.c.commitments.get(cmt["id"])
        return {"commitment_id": got["id"], "line_ids": [s["id"] for s in got["sov"]], "executed_amount": got["executed_amount"], "supplier_id": got["supplier_id"]}

    def certify_bill(self, commitment_id, period_id, line_id, cumulative_installed) -> dict[str, Any]:
        b = self.c.bills.certify(commitment_id=commitment_id, period_id=period_id,
                                 installed=[{"sov_line_id": line_id, "cumulative_installed": cumulative_installed}], actor="gate")
        return {"bill_id": b["id"], "amount_due": b["amount_due"], "status": b["status"]}

    def bill_status(self, bill_id) -> str:
        return self.c.bills.get(bill_id)["status"]

    def setup_sent_prime_bill(self, project, period_id, certified_cumulative) -> dict[str, Any]:
        pb = self.c.receivables.certify(project_id=project["project_id"], period_id=period_id, certified_cumulative=certified_cumulative,
                                        retainage_rate="0.10", actor="gate")
        self.c.approve_and_execute("prime_bill.approve", pb["id"], actor="gate")
        # Sending is its own authority (prime_bill.send) where the receivables domain governs it.
        if getattr(self.c, "_core_owner", lambda op: None)("prime_bill.send") is not None:
            self.c.approve_and_execute("prime_bill.send", pb["id"], actor="gate")
        else:
            self.c.receivables.send(pb["id"], actor="gate")
        # An ACH collection needs the customer's debit mandate backed by owned evidence, so the
        # collection the restore drill attempts is otherwise valid and only write authority can refuse it.
        if hasattr(self.c.receivables, "record_mandate"):
            n = self._next()
            doc = self.c.evidence.register_document(project_id=project["project_id"], kind="ach_mandate", title=f"Gate synthetic ACH debit authorization {n}", actor="gate")
            rev = self.c.evidence.add_revision(document_id=doc["id"], content=f"gate synthetic ACH debit authorization {n}".encode(), note="signed authorization", actor="gate")
            self.c.receivables.record_mandate(customer_id=project["customer_id"], mandate_ref=f"MANDATE-SIM-GATE-{n:03d}", evidence_hash=rev["content_hash"], actor="gate")
        return {"prime_bill_id": pb["id"], "amount_due": self.c.receivables.get(pb["id"])["amount_due"]}

    def record_collection(self, prime_bill_id, period_id, amount, provider_ref) -> dict[str, Any]:
        # The same call the console/HTTP "record_collection" action makes (server.py).
        return self.c.receivables.record_collection(prime_bill_id=prime_bill_id, period_id=period_id, amount=amount, fee="0",
                                                    provider_ref=provider_ref, actor="gate")

    def propose_change(self, commitment_id, amount, line_id) -> str:
        return self.c.commitments.propose_change(commitment_id, amount=amount, reason="gate change", sov_line_id=line_id, actor="gate")["id"]

    def commitment_amount(self, commitment_id) -> str:
        return self.c.commitments.get(commitment_id)["executed_amount"]

    # ---- approvals -------------------------------------------------------------- #
    def request_and_grant(self, operation, subject_id, *, actor_role="owner") -> str:
        ap = self.c.request_approval(operation, subject_id, actor_role=actor_role, requested_by="gate")
        self.c.approve(ap["id"], approver="gate-approver")
        return ap["id"]

    def execute_approval(self, approval_id, *, op_id=None, period_id=None, actor="gate") -> dict[str, Any]:
        r = self.c.execute(approval_id, actor=actor, op_id=op_id, period_id=period_id)
        return {"replayed": r.replayed, "result": r.result, "op_id": r.op_id}

    def approve_and_execute(self, operation, subject_id, *, actor_role="owner", period_id=None) -> dict[str, Any]:
        r = self.c.approve_and_execute(operation, subject_id, actor_role=actor_role, actor="gate", period_id=period_id)
        return {"replayed": r.replayed, "result": r.result}

    def approval_status(self, approval_id) -> str:
        return self.c.approvals.get(approval_id)["status"]

    def approval_exists(self, approval_ref) -> bool:
        return self.c.db.one("SELECT id FROM approvals WHERE id=?", (approval_ref,)) is not None

    def bound_approval_probe(self, *, approved_amount, current_amount) -> dict[str, Any]:
        manifest = build_manifest(operation="gate.probe", subject_type="gate_probe", subject_id=new_id("gpr"), actor_role="treasury",
                                  amounts={"amount": approved_amount}, bindings={"probe": "approval binding"})
        ap = self.c.approvals.request(manifest, requested_by="gate")
        self.c.approvals.grant(ap["id"], approver="gate-approver")
        current = dict(manifest, amounts={"amount": fmt(current_amount)})
        try:
            self.c.approvals.consume(ap["id"], current_manifest=current, consumer="gate")
            outcome = "consumed"
        except ApprovalError as exc:
            outcome = type(exc).__name__
        return {"outcome": outcome, "status": self.c.approvals.get(ap["id"])["status"]}

    def change_destination(self, party_id, destination, *, verified=True) -> None:
        if verified:
            self.c.verify_destination(party_id, destination=destination, verified_by="gate-bank-detail-maintainer")
        else:
            self.raw_sql("UPDATE parties SET destination=?, destination_version=destination_version+1 WHERE id=?", (destination, party_id))

    # ---- payments and recovery ----------------------------------------------------- #
    def payment_intents(self) -> list[dict[str, Any]]:
        return [{k: p[k] for k in ("id", "bill_id", "status", "amount", "destination", "destination_version", "provider_ref")} for p in self.c.payments.list()]

    def provider_counts(self) -> dict[str, int]:
        return {"transfers": len(self.c.provider.transfers), "submissions": len(self.c.provider.submissions)}

    def set_provider_mode(self, mode) -> None:
        self.c.provider.mode = mode

    def dispatch_payments(self) -> list[dict[str, Any]]:
        return self.c.dispatch_payments()

    def snapshot(self, path) -> str:
        return self.c.snapshot(path)

    def open_restored(self, path) -> "NativeCipherAdapter":
        from ..service import Cipher

        other = type(self)()
        other._owner_secret = self._owner_secret
        other.c = Cipher.open_restored(path, provider=self.c.provider)
        return other

    def authority_status(self) -> dict[str, Any]:
        return self.c.db.authority_status()

    @contextlib.contextmanager
    def _owner_secret_env(self, secret: str | None) -> Iterator[None]:
        """Configure (or remove) CIPHER_OWNER_SECRET for one claim, restoring the process
        environment afterwards whatever it held."""
        from ..core.db import OWNER_SECRET_ENV

        previous = os.environ.get(OWNER_SECRET_ENV)
        if secret is None:
            os.environ.pop(OWNER_SECRET_ENV, None)
        else:
            os.environ[OWNER_SECRET_ENV] = secret
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(OWNER_SECRET_ENV, None)
            else:
                os.environ[OWNER_SECRET_ENV] = previous

    def _claim(self, *, credential: str | None, secret: str | None, actor: str, reason: str) -> None:
        # The same service call the console/HTTP "claim_authority" action makes (server.py),
        # with the attestation the core asks for: approver, reason and the owner claim code.
        with self._owner_secret_env(secret):
            self.c.claim_write_authority(approval_ref=credential, actor=actor, reason=reason, claim_code=credential)

    def claim_write_authority(self, credential) -> None:
        self._claim(credential=credential, secret=self._owner_secret, actor="gate-controller", reason="gate drill: claim presenting a fabricated credential")

    def claim_write_authority_default_config(self, credential) -> None:
        self._claim(credential=credential, secret=None, actor="gate-controller", reason="gate drill: claim with no owner secret configured")

    def claim_write_authority_approved(self) -> dict[str, Any]:
        code = self.c.db.expected_claim_code(self._owner_secret)  # what the owner computes from the secret
        before = {c["ref"] for c in self.authority_claims()}
        self._claim(credential=code, secret=self._owner_secret, actor="gate-controller", reason="gate drill: owner-attested recovery claim")
        new = [c["ref"] for c in self.authority_claims() if c["ref"] not in before]
        return {"ref": new[-1] if new else None, "credential": code}

    def authority_claims(self) -> list[dict[str, Any]]:
        out = []
        for row in self.c.db.query("SELECT seq, actor, payload_json, entry_hash FROM audit_log WHERE action='workspace.claim_write_authority' ORDER BY seq"):
            payload = loads(row["payload_json"])
            out.append({"ref": row["entry_hash"], "seq": row["seq"], "approver": payload.get("approver") or row["actor"], "reason": payload.get("reason") or "",
                        "verified": payload.get("owner_claim_code") == "verified"})
        return out

    def complete_recovery(self) -> dict[str, Any]:
        return self.c.complete_recovery(actor="gate-reconciler")

    def ap_reconciliation(self) -> dict[str, Any]:
        return self.c.bills.ap_open_items()

    # ---- fixture and subledgers ---------------------------------------------------- #
    def run_golden_fixture(self) -> dict[str, Any]:
        from ..service import run_golden_fixture

        result = run_golden_fixture(self.c)
        return {"project_id": result["project_id"], "open_period": "2026-11", "result": result}

    def _plugins(self) -> dict[str, Any]:
        return getattr(self.c, "_plugins", None) or {}

    def subledger_reconciliation(self, project_id) -> dict[str, Any]:
        reimbursement = self._plugins().get("reimbursement")
        return {
            "ap": self.c.bills.ap_open_items(project_id),
            "ar": self.c.receivables.ar_open_items(project_id),
            "employee_payable": reimbursement.employee_payable_reconciliation(project_id) if reimbursement is not None else None,
        }

    def add_employee_reimbursement(self, project_id, period_id, amount, paid) -> dict[str, Any] | None:
        plugin = self._plugins().get("reimbursement")
        if plugin is None:
            return None
        n = self._next()
        destination = f"ACH-SIM-GATE-EMP-{n:03d}"
        employee = self.c.add_party(kind="employee", name=f"Gate Synthetic Employee {n}", destination=destination, actor="gate")
        self.c.verify_destination(employee["id"], destination=destination, verified_by="gate-bank-detail-maintainer")
        claim = plugin.submit_claim(project_id=project_id, employee_id=employee["id"], description="Gate synthetic site travel",
                                    amount=amount, receipt_hash=sha256_hex(f"gate receipt {n}"), actor="gate")
        self.c.approve_and_execute("reimbursement.approve", claim["id"], actor="gate", period_id=period_id)
        payment = plugin.record_payment(claim["id"], paid, actor="gate")
        self.c.approve_and_execute("reimbursement.pay", payment["id"], actor="gate", period_id=period_id)
        return {"claim_id": claim["id"], "payment_id": payment["id"]}

    # ---- extension paths ------------------------------------------------------------ #
    def registered_plugins(self) -> list[str]:
        return sorted(self._plugins())

    _PLUGIN_PROBES = (
        ("asset", "asset.post_depreciation", "_prepare_asset_probe"),
        ("reimbursement", "reimbursement.approve", "_prepare_reimbursement_probe"),
        ("labor", "labor.approve_timesheet", "_prepare_labor_probe"),
    )

    def plugin_period_lock_probes(self, project) -> list[dict[str, Any]]:
        """Each probe prepares two identical subjects in one open period: the control
        subject runs through the plugin's approval-bound posting path while the period is
        open, the period is then closed and the probe subject is driven into it."""
        plugins = self._plugins()
        probes = []
        for name, operation, prepare in self._PLUGIN_PROBES:
            if name not in plugins:
                continue
            try:
                probe = getattr(self, prepare)(plugins[name], project, operation)
            except Exception as exc:  # reported by G4 as a failed check, never as a pass
                probes.append({"plugin": name, "path": operation, "setup_error": f"{type(exc).__name__}: {_short(exc)}"})
                continue
            probe.update(plugin=name, path=operation)
            probes.append(probe)
        return probes

    def _execute_into(self, operation: str, subject_id: str, period_id: str) -> Callable[[], Any]:
        return lambda: self.c.approve_and_execute(operation, subject_id, actor="gate", period_id=period_id)

    def _probe(self, operation, period, control_id, control_detail, probe_id, detail, status_fn) -> dict[str, Any]:
        return {
            "period": period, "control_detail": control_detail, "detail": detail,
            "run_control": self._execute_into(operation, control_id, period),
            "close": lambda: self.close_period(period),
            "attempt": self._execute_into(operation, probe_id, period),
            "status": status_fn,
        }

    def _prepare_asset_probe(self, assets, project, operation):
        period = "G4-AST"
        self.open_period(period, "2026-12-01", "2026-12-31")
        runs = []
        for role in ("control", "probe"):
            asset = assets.register_asset(project["project_id"], f"Gate synthetic dewatering pump skid ({role})", "12000.00", "2026-12-01", 12, actor="gate")
            self.c.approve_and_execute("asset.capitalise", asset["id"], actor="gate", period_id=period)
            runs.append(assets.schedule_run(asset["id"], period, actor="gate"))
        control, probe = runs
        return self._probe(operation, period, control["id"], f"depreciation run of {control['amount']}", probe["id"],
                           f"depreciation run of {probe['amount']}", lambda: assets.get_run(probe["id"])["status"])

    def _prepare_reimbursement_probe(self, reimbursements, project, operation):
        period = "G4-RMB"
        claims = []
        for role in ("control", "probe"):
            n = self._next()
            employee = self.c.add_party(kind="employee", name=f"Gate Synthetic Employee {n}", actor="gate")
            claims.append(reimbursements.submit_claim(project_id=project["project_id"], employee_id=employee["id"], description=f"Gate synthetic mileage ({role})",
                                                      amount="412.50", receipt_hash=sha256_hex(f"gate period-lock receipt {n}"), actor="gate"))
        self.open_period(period, "2027-01-01", "2027-01-31")
        control, probe = claims
        return self._probe(operation, period, control["id"], f"claim of {control['amount']}", probe["id"], f"claim of {probe['amount']}",
                           lambda: reimbursements.claim(probe["id"])["status"])

    def _prepare_labor_probe(self, labor, project, operation):
        period = "G4-LAB"
        n = self._next()
        phase = labor.add_phase(project["project_id"], f"GATE{n}", "Gate synthetic design phase", "100", "15000.00", actor="gate")
        self.open_period(period, "2027-03-01", "2027-03-31")
        sheets = []
        for _role in ("control", "probe"):
            m = self._next()
            employee = self.c.add_party(kind="employee", name=f"Gate Synthetic Engineer {m}", actor="gate")
            labor.set_rate(employee["id"], "2027-03-01", "85.00", "150.00", actor="gate")
            labor.log_time(employee["id"], project["project_id"], phase["id"], "2027-03-02", "8", actor="gate")
            sheets.append(labor.submit_timesheet(employee["id"], period, actor="gate"))
        control, probe = sheets
        return self._probe(operation, period, control["id"], f"timesheet of {control['total_hours']} h costing {control['total_cost']}", probe["id"],
                           f"timesheet of {probe['total_hours']} h costing {probe['total_cost']}", lambda: labor.timesheet(probe["id"])["status"])

    # ---- scorecard ------------------------------------------------------------------- #
    def assumed_scores(self) -> dict[str, tuple[int, str]]:
        return {
            "aec_fit": (4, "ASSUMPTION (not measured by the gates): the native schema already models commitments, SOV lines, "
                           "change orders, stored materials, retainage and prime progress billing directly; held below 5 because "
                           "labor, WIP/close and field modules are still being built."),
            "maintainability_upgrades": (3, "ASSUMPTION: Python standard library and SQLite only, no framework upgrade treadmill and an "
                                            "append-only, checksummed schema catalog; held at 3 because one owner-maintainer carries the whole "
                                            "posting, close, reporting and recovery burden (plan section 3, native disposition)."),
            "ownership_licensing": (4, "ASSUMPTION: owner-written code with no third-party runtime dependency or copyleft obligation; held "
                                       "below 5 until repository ownership and licence are formally confirmed (plan section 2: the PRO root "
                                       "has no licence file)."),
            "delivery_cost": (2, "ASSUMPTION: plan section 12 budgets a native-ledger premium of 20-40 person-months ($400,000-$1.2 million) "
                                 "and 4-9 months versus a suitable reused core; not validated here."),
        }


# --------------------------------------------------------------------------- #
# ERPNext adapter (not provisioned)                                            #
# --------------------------------------------------------------------------- #

class ERPNextAdapter(LedgerAdapter):
    """Placeholder for the plan's leading mature-core candidate.  Exercising it needs
    an isolated container stack and separate execution authorization, neither of
    which exists here, so it reports itself unavailable and every gate is not_run.
    Nothing is installed, pulled or started."""

    candidate = "erpnext"
    label = "ERPNext accounting on the Frappe framework, adapted behind Cipher"

    def available(self) -> tuple[bool, str]:
        return False, ERPNEXT_UNAVAILABLE


# --------------------------------------------------------------------------- #
# Gate machinery                                                               #
# --------------------------------------------------------------------------- #

def _short(exc: BaseException, limit: int = 160) -> str:
    text = str(exc).replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _attempt(fn: Callable, *args, **kwargs) -> tuple[bool, str, Any]:
    """Run ``fn`` expecting a refusal.  Returns ``(refused, why, value)``.  Programming
    errors are re-raised so a broken adapter can never look like a working control."""
    try:
        value = fn(*args, **kwargs)
    except _PROGRAMMING_ERRORS:
        raise
    except Exception as exc:
        return True, f"{type(exc).__name__}: {_short(exc)}", None
    return False, "no error raised", value


def _markers(a: LedgerAdapter, controls: tuple[str, ...]) -> list[re.Pattern]:
    table = a.refusal_markers() or {}
    patterns = []
    for control in controls:
        pattern = table.get(control)
        if not isinstance(pattern, str) or not pattern.strip():
            raise CoreGateError(f"adapter {a.candidate} declares no refusal marker for the {control} control")
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise CoreGateError(f"adapter {a.candidate} declares an invalid refusal marker for {control}: {exc}") from exc
        if any(rx.search(reason) for reason in _UNRELATED_REASONS):
            raise CoreGateError(f"the {control} refusal marker of {a.candidate} ({pattern!r}) also matches empty or unrelated errors")
        patterns.append(rx)
    return patterns


def _refused_by(a: LedgerAdapter, controls: tuple[str, ...], fn: Callable, *args, **kwargs) -> tuple[str, str]:
    """Run ``fn`` expecting a refusal by one of ``controls``.  Returns ``(outcome, why)``:
    ``refused`` (the reason carries the control's marker), ``unrelated`` (an error that is
    not the control), or ``accepted``.  Programming errors propagate."""
    patterns = _markers(a, controls)  # validated before anything is attempted
    refused, why, _ = _attempt(fn, *args, **kwargs)
    if not refused:
        return "accepted", why
    if any(rx.search(why) for rx in patterns):
        return "refused", why
    return "unrelated", why


def _verdict(outcome: str, why: str) -> str:
    if outcome == "refused":
        return f"refused ({why})"
    if outcome == "unrelated":
        return f"was not refused by the expected control: it failed for an unrelated reason ({why})"
    if outcome == "crashed":
        return f"was not refused by the expected control: it crashed with a programming error ({why})"
    return "was ACCEPTED"


def _s(value) -> str:
    """Render a Decimal or amount string exactly (never via float)."""
    return f"{value:f}" if isinstance(value, Decimal) else str(value)


def _render(value) -> str:
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_s(v) for v in value) + "]"
    return _s(value)


class _Recorder:
    def __init__(self, gate_id: str):
        self.gate_id = gate_id
        self.evidence: list[str] = []
        self.advisories: list[dict[str, Any]] = []
        self.failed_keys: list[str] = []
        self.passed = 0
        self.failed = 0

    def check(self, ok: bool, text: str, key: str | None = None) -> bool:
        key = key or f"{self.gate_id.lower()}.check{self.passed + self.failed + 1}"
        if ok:
            self.passed += 1
        else:
            self.failed += 1
            self.failed_keys.append(key)
        self.evidence.append(f"{'PASS' if ok else 'FAIL'}: {text}")
        return ok

    def note(self, text: str) -> None:
        self.evidence.append(f"INFO: {text}")

    def advise(self, ok: bool, check: str, observed: str) -> None:
        self.advisories.append({"gate": self.gate_id, "status": "pass" if ok else "open", "check": check, "observed": observed})

    def abort(self, exc: BaseException) -> None:
        self.failed += 1
        self.failed_keys.append(f"{self.gate_id.lower()}.aborted")
        self.evidence.append(f"FAIL: gate aborted by {type(exc).__name__}: {_short(exc, 300)}")

    def result(self) -> dict[str, Any]:
        status = "pass" if self.failed == 0 and self.passed > 0 else "fail"
        return {
            "gate": self.gate_id,
            "title": GATE_TITLES[self.gate_id],
            "status": status,
            "evidence": self.evidence,
            "checks": {"passed": self.passed, "failed": self.failed, "total": self.passed + self.failed},
            "failed_checks": self.failed_keys,
            "advisories": self.advisories,
        }


def _line(account: str, side: str, amount: str) -> dict[str, Any]:
    return {"account": account, side: amount}


def _fingerprint(journal: dict[str, Any]) -> str:
    return hash_json({k: journal[k] for k in ("id", "period_id", "description", "source_id", "source_version", "rule_version", "lines")})


def _journal_totals(journal: dict[str, Any]) -> tuple[Decimal, Decimal]:
    return total(ln["debit"] for ln in journal["lines"]), total(ln["credit"] for ln in journal["lines"])


def _recompute_chain(entries: list[dict[str, Any]]) -> tuple[bool, int | None]:
    """Verify an exported audit chain from the exported rows alone."""
    prev = "0" * 64
    for e in entries:
        expected = sha256_hex("|".join([prev, e["ts"], e["actor"], e["action"], e["entity_type"], e["entity_id"], e["payload_hash"]]))
        if e["prev_hash"] != prev or e["entry_hash"] != expected or sha256_hex(e["payload_json"]) != e["payload_hash"]:
            return False, e["seq"]
        prev = e["entry_hash"]
    return True, None


# ---- G1 ---------------------------------------------------------------------- #

def gate_g1(a: LedgerAdapter, r: _Recorder) -> None:
    a.reset()
    money_control = (CONTROL_EXACT_MONEY,)
    # Since cipher-core-gates/3 every refusal here must come from the money control itself
    # (an incidental error, such as a decimal InvalidOperation, no longer counts).
    outcome, why = _refused_by(a, money_control, a.to_money, 0.1)
    r.check(outcome == "refused", f"binary float 0.1 as money {_verdict(outcome, why)}", key="g1.float_refused")
    outcome, why = _refused_by(a, money_control, a.to_money, True)
    r.check(outcome == "refused", f"boolean True as money {_verdict(outcome, why)}", key="g1.bool_refused")

    seen, accepted, unattributed = [], [], []
    patterns = _markers(a, money_control)
    for label, fn, args in (
        ("to_money('NaN')", a.to_money, ("NaN",)),
        ("to_money('sNaN')", a.to_money, ("sNaN",)),
        ("to_money('Infinity')", a.to_money, ("Infinity",)),
        ("to_money('-Infinity')", a.to_money, ("-Infinity",)),
        ("add_money('1.00', 'NaN')", a.add_money, ("1.00", "NaN")),
        ("sum_money(['1.00', 'NaN'])", a.sum_money, (["1.00", "NaN"],)),
        ("allocate('NaN', [1, 1])", a.allocate, ("NaN", [1, 1])),
    ):
        refused, why, value = _attempt(fn, *args)
        if not refused:
            accepted.append(label)
            seen.append(f"{label} ACCEPTED, returning {_render(value)}")
        elif any(rx.search(why) for rx in patterns):
            seen.append(f"{label} refused ({why})")
        else:
            unattributed.append(label)
            seen.append(f"{label} {_verdict('unrelated', why)}")
    r.check(not accepted and not unattributed,
            f"non-finite amounts are refused by the money control ({len(accepted)} of {len(seen)} accepted, {len(unattributed)} refused for another reason): "
            + "; ".join(seen), key="g1.nonfinite_refused")

    s = a.add_money("0.1", "0.2")
    r.check(s == Decimal("0.30") and _s(s) == "0.30", f"0.1 + 0.2 = {_s(s)} exactly (binary floating point gives {0.1 + 0.2!r})", key="g1.no_binary_error")
    dimes = a.sum_money(["0.10"] * 10)
    r.check(dimes == Decimal("1.00"), f"ten 0.10 amounts sum to {_s(dimes)} exactly", key="g1.dimes")

    for raw, expected in (("0.005", "0.01"), ("0.015", "0.02"), ("2.675", "2.68"), ("1234.565", "1234.57"), ("0.004999", "0.00"), ("-0.005", "-0.01")):
        got = _s(a.to_money(raw))
        extra = f" (Python float round(2.675, 2) gives {round(2.675, 2)!r})" if raw == "2.675" else ""
        r.check(got == expected, f"half-up to cents: {raw} -> {got}, expected {expected}{extra}", key=f"g1.half_up.{raw}")

    unbounded = []
    for index, (amount, weights) in enumerate(ALLOCATION_CASES, start=1):
        parts = a.allocate(amount, weights)
        summed = sum(parts, Decimal(0))
        cents = all(D(p) == D(p).quantize(TWO_PLACES) for p in parts)
        label = ":".join(str(w) for w in weights)
        r.check(summed == D(amount) and cents and len(parts) == len(weights),
                f"allocate {amount} over {label} -> {' + '.join(_s(p) for p in parts)} = {_s(summed)} (exact to the cent)", key=f"g1.allocation_exact.{index}")
        weight_sum = sum((D(w) for w in weights), Decimal(0))
        for p, w in zip(parts, weights):
            share = D(amount) * D(w) / weight_sum
            if not (Decimal(0) <= D(p) <= D(amount) and abs(D(p) - share) < TWO_PLACES):
                unbounded.append(f"allocate {amount} over {label} gives a part of {_s(p)} against an exact share of {_s(share.quantize(FOUR_PLACES))}")
    r.check(not unbounded,
            f"every allocated part is non-negative and within one cent of its exact share ({len(ALLOCATION_CASES)} cases, {len(unbounded)} violation(s))"
            + (": " + "; ".join(unbounded) + " - the whole rounding residual lands on one part" if unbounded else ""),
            key="g1.allocation_bounded")

    a.open_period("G1", "2026-10-01", "2026-10-31")
    jid = a.post_journal(period_id="G1", lines=[_line("5000", "debit", "0.10"), _line("5100", "debit", "0.20"), _line("2000", "credit", "0.30")], source_id="g1-dimes")
    j = a.journal(jid)
    stored = [(ln["account"], ln["debit"], ln["credit"]) for ln in j["lines"]]
    r.check(stored == [("5000", "0.10", "0.00"), ("5100", "0.20", "0.00"), ("2000", "0.00", "0.30")], f"posted amounts are stored exactly as decimal strings: {stored}", key="g1.stored_exact")
    tb = a.trial_balance()
    r.check(tb["balanced"] and tb["total_debit"] == "0.30" == tb["total_credit"], f"trial balance Dr {tb['total_debit']} = Cr {tb['total_credit']}", key="g1.trial_balance")
    for label, key, amount in (("float amounts (0.1)", "g1.float_journal_refused", 0.1), ("non-finite amounts ('NaN')", "g1.nonfinite_journal_refused", "NaN")):
        before = a.journal_count()
        outcome, why = _refused_by(a, money_control, a.post_journal, period_id="G1", lines=[_line("5000", "debit", amount), _line("2000", "credit", amount)], source_id=key)
        after = a.journal_count()
        r.check(outcome == "refused" and after == before, f"a journal carrying {label} {_verdict(outcome, why)}; journals {before} -> {after} (nothing may be posted)", key=key)


# ---- G2 ---------------------------------------------------------------------- #

def gate_g2(a: LedgerAdapter, r: _Recorder) -> None:
    a.reset()
    a.open_period("G2", "2026-10-01", "2026-10-31")
    cases = (
        ("unbalanced journal (debits 100.00, credits 99.99)", [_line("5000", "debit", "100.00"), _line("2000", "credit", "99.99")]),
        ("journal with a line carrying both a debit and a credit (totals 100.00 = 100.00)",
         [{"account": "5000", "debit": "50.00", "credit": "50.00"}, _line("2000", "credit", "50.00"), _line("1000", "debit", "50.00")]),
        ("journal whose last line names unknown account 9999", [_line("5000", "debit", "10.00"), _line("2000", "credit", "5.00"), _line("9999", "credit", "5.00")]),
        ("zero-value journal (every line 0.00, so no line carries a value)", [_line("5000", "debit", "0.00"), _line("2000", "credit", "0.00")]),
        ("journal with no lines", []),
    )
    for index, (label, lines) in enumerate(cases, start=1):
        before = a.journal_count()
        refused, why, _ = _attempt(a.post_journal, period_id="G2", lines=lines, source_id="g2-invalid")
        after = a.journal_count()
        r.check(refused and after == before, f"{label} refused with nothing posted ({why}); journals {before} -> {after}", key=f"g2.invalid.{index}")

    jid = a.post_journal(period_id="G2", lines=[_line("5000", "debit", "600.00"), _line("1300", "debit", "400.00"), _line("2000", "credit", "1000.00")], source_id="g2-balanced")
    j = a.journal(jid)
    dr, cr = _journal_totals(j)
    r.check(dr == cr == Decimal("1000.00") and all(j.get(k) for k in ("source_id", "source_version", "rule_version", "posted_by")),
            f"balanced 3-line journal posted (Dr {_s(dr)} = Cr {_s(cr)}) carrying source {j.get('source_id')} v{j.get('source_version')} and rule {j.get('rule_version')}",
            key="g2.balanced_posts")

    spec_a = {"period_id": "G2", "lines": [_line("5000", "debit", "125.00"), _line("2000", "credit", "125.00")], "source_id": "g2-atomic-a"}
    spec_b = {"period_id": "G2", "lines": [_line("5100", "debit", "75.00"), _line("2000", "credit", "75.00")], "source_id": "g2-atomic-b"}
    before = a.journal_count()
    refused, why, _ = _attempt(a.run_command, "g2:atomic", {"case": "two journals"}, [spec_a, spec_b], fail_after=1)
    after = a.journal_count()
    r.check(refused and after == before, f"a command posting 2 journals that faults after the first leaves no partial journal ({why}); journals {before} -> {after}", key="g2.atomic")
    r.check(not a.command_recorded("g2:atomic"), "the faulted command left no idempotency record behind", key="g2.no_record_after_fault")
    rerun = a.run_command("g2:atomic", {"case": "two journals"}, [spec_a, spec_b])
    r.check(not rerun["replayed"] and a.journal_count() == before + 2, f"re-running the same command executes fresh and posts both journals; journals {before} -> {a.journal_count()}", key="g2.rerun")

    # The posting path is not the only writer: a privileged session writing journal rows
    # directly must meet the same rules, enforced by the schema (the journal seal).
    for label, key, lines, declared in (
        ("a raw journal header with no declared line count and no lines", "g2.raw_header_only_refused", [], None),
        ("a raw journal declaring 2 lines that commits with 1 (Dr 5000 100.00)", "g2.raw_incomplete_refused",
         [_line("5000", "debit", "100.00")], 2),
        ("a raw journal of 2 lines that does not balance (Dr 5000 100.00, Cr 2000 99.99)", "g2.raw_unbalanced_refused",
         [_line("5000", "debit", "100.00"), _line("2000", "credit", "99.99")], 2),
    ):
        before = a.journal_count()
        outcome, why = _refused_by(a, (CONTROL_JOURNAL_SEAL,), a.privileged_insert_raw_journal, "G2", lines, declared)
        after = a.journal_count()
        r.check(outcome == "refused" and after == before, f"privileged path: {label} in open period G2 {_verdict(outcome, why)}; journals {before} -> {after}", key=key)

    ids = a.journal_ids()
    unbalanced = []
    for i in ids:
        jd, jc = _journal_totals(a.journal(i))
        if jd != jc:
            unbalanced.append(i)
    tb = a.trial_balance()
    r.check(not unbalanced and tb["balanced"], f"all {len(ids)} stored journals balance individually ({len(unbalanced)} do not); trial balance Dr {tb['total_debit']} = Cr {tb['total_credit']}",
            key="g2.all_balanced")


# ---- G3 ---------------------------------------------------------------------- #

def gate_g3(a: LedgerAdapter, r: _Recorder) -> None:
    a.reset()
    a.open_period("G3", "2026-10-01", "2026-10-31")
    jid = a.post_journal(period_id="G3", lines=[_line("5000", "debit", "1500.00"), _line("2000", "credit", "1500.00")], source_id="g3-original")
    fp = _fingerprint(a.journal(jid))
    for action, label in (("update_amount", "UPDATE journal_lines SET debit=9999.00"), ("update_description", "UPDATE journals SET description"),
                          ("delete_lines", "DELETE FROM journal_lines"), ("delete_journal", "DELETE FROM journals")):
        outcome, why = _refused_by(a, (CONTROL_IMMUTABILITY,), a.privileged_tamper, action, jid)
        r.check(outcome == "refused", f"privileged raw SQL on a posted journal: {label} {_verdict(outcome, why)}", key=f"g3.tamper.{action}")
    after_fp = _fingerprint(a.journal(jid))
    r.check(after_fp == fp, f"posted journal unchanged after 4 raw-SQL tamper attempts (fingerprint {fp[:16]})", key="g3.unchanged_after_tamper")

    rid = a.reverse_journal(jid, period_id="G3", reason="gate correction")
    rj = a.journal(rid)
    original = a.journal(jid)
    swapped = [(ln["account"], ln["credit"], ln["debit"]) for ln in original["lines"]]
    mirrored = [(ln["account"], ln["debit"], ln["credit"]) for ln in rj["lines"]]
    r.check(rj["reversal_of"] == jid and mirrored == swapped, f"correction appended as linked reversal {rid} -> {jid} with sides swapped: {mirrored}", key="g3.linked_reversal")
    ref = rj.get("approval_id")
    recorded = bool(ref) and a.approval_exists(ref)
    status = a.approval_status(ref) if recorded else "-"
    r.check(recorded and status == "consumed",
            f"the correction went through the governed path: reversal {rid} carries approval {ref or 'none'} (recorded: {recorded}, status {status})",
            key="g3.correction_approved")
    b5000, b2000 = a.balance("5000"), a.balance("2000")
    r.check(b5000 == Decimal("0.00") and b2000 == Decimal("0.00"), f"net effect after reversal: 5000 {_s(b5000)}, 2000 {_s(b2000)} (original 1500.00)", key="g3.reversal_nets")
    r.check(_fingerprint(a.journal(jid)) == fp, "the original journal is preserved unchanged next to its reversal", key="g3.original_preserved")
    refused, why, _ = _attempt(a.reverse_journal, jid, period_id="G3", reason="second reversal")
    r.check(refused and a.journal_count() == 2, f"a second reversal of the same journal is refused ({why}); journals {a.journal_count()}", key="g3.second_reversal_refused")
    outcome, why = _refused_by(a, (CONTROL_IMMUTABILITY,), a.privileged_tamper, "unlink_reversal", rid)
    r.check(outcome == "refused" and a.journal(rid)["reversal_of"] == jid, f"unlinking the reversal by raw SQL {_verdict(outcome, why)}", key="g3.unlink_refused")

    # A raw INSERT onto an already-posted journal must not alter it either (plan: "reject direct
    # ledger-row edits").  Run last, on its own journal, so an acceptance cannot cascade.
    probe = a.post_journal(period_id="G3", lines=[_line("5000", "debit", "100.00"), _line("2000", "credit", "100.00")], source_id="g3-insert-probe")
    pfp = _fingerprint(a.journal(probe))
    outcome, why = _refused_by(a, (CONTROL_IMMUTABILITY,), a.privileged_insert_line, probe)
    pj = a.journal(probe)
    dr, cr = _journal_totals(pj)
    tb = a.trial_balance()
    unchanged = _fingerprint(pj) == pfp
    r.check(outcome == "refused" and unchanged and tb["balanced"],
            f"raw INSERT of a 1.00 debit line onto posted journal {probe} (Dr 100.00 / Cr 100.00) in open period G3 {_verdict(outcome, why)}; "
            f"that journal is now Dr {_s(dr)} / Cr {_s(cr)} over {len(pj['lines'])} lines (fingerprint {'unchanged' if unchanged else 'CHANGED'}); "
            f"trial balance Dr {tb['total_debit']} / Cr {tb['total_credit']}, balanced={tb['balanced']}",
            key="g3.insert_line_on_posted_refused")


# ---- G4 ---------------------------------------------------------------------- #

def gate_g4(a: LedgerAdapter, r: _Recorder) -> None:
    a.reset()
    project = a.setup_project()
    cmt = a.setup_commitment(project)
    a.open_period("G4-SVC", "2026-10-01", "2026-10-31")
    seed = a.post_journal(period_id="G4-SVC", lines=[_line("5000", "debit", "100.00"), _line("3000", "credit", "100.00")], source_id="g4-seed")
    bill = a.certify_bill(cmt["commitment_id"], "G4-SVC", cmt["line_ids"][0], "20000")
    approval = a.request_and_grant("bill.approve", bill["bill_id"])
    a.close_period("G4-SVC")
    r.note(f"period G4-SVC closed holding 1 journal; bill of {bill['amount_due']} certified and its approval granted before the close")

    def lock_refusal(label: str, key: str, fn: Callable, *args, controls: tuple[str, ...] = (CONTROL_PERIOD_LOCK,), **kwargs) -> None:
        before = a.journal_count()
        outcome, why = _refused_by(a, controls, fn, *args, **kwargs)
        after = a.journal_count()
        r.check(outcome == "refused" and after == before, f"{label} {_verdict(outcome, why)}; journals {before} -> {after}", key=key)

    lock_refusal("service path: executing the granted bill approval into the closed period", "g4.service_closed", a.execute_approval, approval)
    r.check(a.bill_status(bill["bill_id"]) == "draft", f"the bill stays {a.bill_status(bill['bill_id'])}", key="g4.bill_stays_draft")
    lock_refusal("ledger path: posting into the closed period", "g4.ledger_closed", a.post_journal, period_id="G4-SVC",
                 lines=[_line("5000", "debit", "10.00"), _line("2000", "credit", "10.00")], source_id="g4-ledger")
    lock_refusal("raw INSERT of a journal header into the closed period", "g4.raw_header_closed", a.privileged_insert_journal, "G4-SVC")
    lock_refusal("raw INSERT of a line onto the closed period's journal", "g4.raw_line_closed", a.privileged_insert_line, seed,
                 controls=(CONTROL_PERIOD_LOCK, CONTROL_IMMUTABILITY))

    a.lock_period("G4-SVC")
    r.check(a.period_status("G4-SVC") == "locked", f"period G4-SVC is {a.period_status('G4-SVC')}", key="g4.locked")
    lock_refusal("ledger path: posting into the locked period", "g4.ledger_locked", a.post_journal, period_id="G4-SVC",
                 lines=[_line("5000", "debit", "10.00"), _line("2000", "credit", "10.00")], source_id="g4-locked")
    lock_refusal("raw INSERT of a journal header into the locked period", "g4.raw_header_locked", a.privileged_insert_journal, "G4-SVC")
    # Through the governed path with a recorded approval, so the lock is the only possible reason to refuse.
    outcome, why = _refused_by(a, (CONTROL_PERIOD_LOCK,), a.reopen_period_approved, "G4-SVC")
    r.check(outcome == "refused" and a.period_status("G4-SVC") == "locked",
            f"reopening the locked period through the governed path with a recorded approval {_verdict(outcome, why)}", key="g4.locked_reopen_refused")
    outcome, why = _refused_by(a, (CONTROL_PERIOD_LOCK, CONTROL_IMMUTABILITY), a.privileged_unlock_period, "G4-SVC")
    status = a.period_status("G4-SVC")
    consequence = ""
    if status != "locked":
        before = a.journal_count()
        refused, _why, _ = _attempt(a.post_journal, period_id="G4-SVC", lines=[_line("5000", "debit", "10.00"), _line("2000", "credit", "10.00")], source_id="g4-after-unlock")
        consequence = f"; the period then {'refused' if refused else 'accepted'} a direct 10.00 post (journals {before} -> {a.journal_count()})"
    r.check(outcome == "refused" and status == "locked",
            f"raw UPDATE setting locked period G4-SVC back to open {_verdict(outcome, why)}; the period is {status}{consequence}", key="g4.raw_unlock_refused")

    a.open_period("G4-REOPEN", "2027-02-01", "2027-02-28")
    a.close_period("G4-REOPEN")
    outcome, why = _refused_by(a, (CONTROL_APPROVAL_REFERENCE,), a.reopen_period, "G4-REOPEN", "")
    r.check(outcome == "refused" and a.period_status("G4-REOPEN") == "closed",
            f"reopening closed period G4-REOPEN without an approval reference {_verdict(outcome, why)}", key="g4.reopen_without_reference_refused")
    fabricated = "apr_gate_unrecorded_reopen"
    recorded = a.approval_exists(fabricated)
    outcome, why = _refused_by(a, (CONTROL_APPROVAL_REFERENCE,), a.reopen_period, "G4-REOPEN", fabricated)
    status = a.period_status("G4-REOPEN")
    r.check(not recorded and outcome == "refused" and status == "closed",
            f"reopening closed period G4-REOPEN with a fabricated approval reference '{fabricated}' (a recorded approval: {recorded}) {_verdict(outcome, why)}; "
            f"the period is {status}", key="g4.reopen_requires_recorded_approval")
    if status != "closed":  # the fabricated reference reopened it; restore the closed state for the governed path
        a.close_period("G4-REOPEN")
    # The reopen rule is enforced on the period row itself, so a privileged UPDATE citing a
    # fabricated approval is refused as well (cipher-core-gates/3).
    outcome, why = _refused_by(a, (CONTROL_APPROVAL_REFERENCE, CONTROL_PERIOD_LOCK), a.privileged_reopen_period, "G4-REOPEN", fabricated)
    status = a.period_status("G4-REOPEN")
    r.check(outcome == "refused" and status == "closed",
            f"privileged path: a raw UPDATE reopening closed period G4-REOPEN citing '{fabricated}' {_verdict(outcome, why)}; the period is {status}",
            key="g4.raw_reopen_refused")
    if status != "closed":
        a.close_period("G4-REOPEN")
    ref = a.reopen_period_approved("G4-REOPEN")
    before = a.journal_count()
    a.post_journal(period_id="G4-REOPEN", lines=[_line("5000", "debit", "20.00"), _line("3000", "credit", "20.00")], source_id="g4-reopened")
    r.check(a.approval_exists(ref) and a.period_status("G4-REOPEN") == "open" and a.journal_count() == before + 1,
            f"control case: the governed reopen with recorded approval {ref} reopens G4-REOPEN and it accepts posting again; journals {before} -> {a.journal_count()}",
            key="g4.governed_reopen")

    # A consumed reopen approval authorises one reopen of its own period: replaying it (ledger
    # path or raw UPDATE) on that period once it is closed again, or citing it for another
    # closed period, is refused.
    a.close_period("G4-REOPEN")
    a.open_period("G4-REOPEN-B", "2027-04-01", "2027-04-30")
    a.close_period("G4-REOPEN-B")
    reopens_before = a.period_reopen_count("G4-REOPEN")
    attempts = []
    for label, fn, period in (
        ("replaying it on G4-REOPEN", a.reopen_period, "G4-REOPEN"),
        ("replaying it on G4-REOPEN by raw UPDATE", a.privileged_reopen_period, "G4-REOPEN"),
        ("citing it for closed period G4-REOPEN-B", a.reopen_period, "G4-REOPEN-B"),
    ):
        outcome, why = _refused_by(a, (CONTROL_APPROVAL_REFERENCE, CONTROL_PERIOD_LOCK), fn, period, ref)
        attempts.append((outcome == "refused" and a.period_status(period) == "closed", f"{label} {_verdict(outcome, why)} (period {a.period_status(period)})"))
    reopens_after = a.period_reopen_count("G4-REOPEN")
    r.check(all(ok for ok, _ in attempts) and reopens_after == reopens_before == 1,
            f"the consumed reopen approval {ref} cannot be used again: " + "; ".join(text for _, text in attempts)
            + f"; recorded reopens of G4-REOPEN {reopens_before} -> {reopens_after}", key="g4.reopen_approval_single_use")

    probed = []
    for p in a.plugin_period_lock_probes(project):
        name, path = p["plugin"], p["path"]
        probed.append(name)
        if "setup_error" in p:
            r.check(False, f"plugin path {path} is registered but was not exercised: preparing its subjects failed ({p['setup_error']})", key=f"g4.plugin.{name}.exercised")
            continue
        before = a.journal_count()
        try:
            p["run_control"]()
            control = "posted"
        except Exception as exc:
            control = f"failed ({type(exc).__name__}: {_short(exc)})"
        after = a.journal_count()
        r.check(control == "posted" and after > before,
                f"control case: plugin path {path} ({p['control_detail']}) in open period {p['period']} {control}; journals {before} -> {after}", key=f"g4.plugin.{name}.control")
        try:
            p["close"]()
        except Exception as exc:
            r.check(False, f"plugin path {path}: closing period {p['period']} for the probe failed ({type(exc).__name__}: {_short(exc)})", key=f"g4.plugin.{name}.refused")
            continue
        before = a.journal_count()
        try:
            outcome, why = _refused_by(a, (CONTROL_PERIOD_LOCK,), p["attempt"])
        except _PROGRAMMING_ERRORS as exc:
            outcome, why = "crashed", f"{type(exc).__name__}: {_short(exc)}"
        after = a.journal_count()
        try:
            subject = p["status"]()
        except Exception as exc:
            subject = f"unreadable ({type(exc).__name__})"
        r.check(outcome == "refused" and after == before,
                f"plugin path {path} ({p['detail']}) into closed period {p['period']} {_verdict(outcome, why)}; journals {before} -> {after}; subject stays {subject}",
                key=f"g4.plugin.{name}.refused")
    registered = a.registered_plugins()
    r.note(f"registered plugins: {', '.join(registered) or 'none'}; plugin posting paths probed: {', '.join(sorted(probed)) or 'none'}; "
           f"registered without a probe: {', '.join(sorted(set(registered) - set(probed))) or 'none'} "
           "(their journal INSERTs are still subject to the period-open triggers checked above, but their own flows are not driven here)")


# ---- G5 ---------------------------------------------------------------------- #

def gate_g5(a: LedgerAdapter, r: _Recorder) -> None:
    a.reset()
    a.open_period("G5", "2026-10-01", "2026-10-31")
    spec = {"period_id": "G5", "lines": [_line("5000", "debit", "250.00"), _line("2000", "credit", "250.00")], "source_id": "g5-once"}
    first = a.run_command("g5:post-once", {"amount": "250.00"}, [spec])
    n1 = a.journal_count()
    second = a.run_command("g5:post-once", {"amount": "250.00"}, [spec])
    n2 = a.journal_count()
    r.check(not first["replayed"] and second["replayed"] and second["result"] == first["result"] and n1 == n2 == 1,
            f"replaying logical operation g5:post-once returns the stored result {second['result']} (replayed={second['replayed']}) with one effect; journals {n1} -> {n2}",
            key="g5.replay")
    other = {"period_id": "G5", "lines": [_line("5000", "debit", "260.00"), _line("2000", "credit", "260.00")], "source_id": "g5-once"}
    refused, why, _ = _attempt(a.run_command, "g5:post-once", {"amount": "260.00"}, [other])
    r.check(refused and a.journal_count() == 1, f"the same operation id with a different payload (260.00) conflicts ({why}); journals {a.journal_count()}", key="g5.conflict")

    project = a.setup_project()
    cmt = a.setup_commitment(project)
    bill = a.certify_bill(cmt["commitment_id"], "G5", cmt["line_ids"][0], "20000")
    a.approve_and_execute("bill.approve", bill["bill_id"])
    approval = a.request_and_grant("payment.release", bill["bill_id"], actor_role="treasury")
    e1 = a.execute_approval(approval, actor="treasury")
    e2 = a.execute_approval(approval, actor="treasury")
    intents = a.payment_intents()
    r.check(not e1["replayed"] and e2["replayed"] and e2["result"] == e1["result"] and len(intents) == 1,
            f"replaying the payment-release execution ({e1['op_id']}) returns intent {e1['result'].get('intent')} for {e1['result'].get('amount')} again; intents {len(intents)}",
            key="g5.release_replay")
    refused, why, _ = _attempt(a.execute_approval, approval, op_id="exec:second-worker", actor="treasury")
    r.check(refused and len(a.payment_intents()) == 1, f"a second worker with its own operation id cannot consume the approval again ({why}); intents {len(a.payment_intents())}",
            key="g5.second_worker")
    a.dispatch_payments()
    a.dispatch_payments()
    pc = a.provider_counts()
    r.check(pc["transfers"] == 1 and pc["submissions"] == 1, f"dispatching twice reaches the provider once: transfers {pc['transfers']}, submissions {pc['submissions']}",
            key="g5.dispatch_once")

    # Advisory (beyond the G5 specification): two independently approved releases for one in-flight bill.
    bill2 = a.certify_bill(cmt["commitment_id"], "G5", cmt["line_ids"][0], "30000")
    a.approve_and_execute("bill.approve", bill2["bill_id"])
    first_release = a.request_and_grant("payment.release", bill2["bill_id"], actor_role="treasury")
    a.execute_approval(first_release, actor="treasury")

    def second_release():
        approval_id = a.request_and_grant("payment.release", bill2["bill_id"], actor_role="treasury")
        return a.execute_approval(approval_id, actor="treasury")

    refused, why, _ = _attempt(second_release)
    on_bill = [p for p in a.payment_intents() if p["bill_id"] == bill2["bill_id"]]
    before_dispatch = a.provider_counts()
    a.dispatch_payments()
    after_dispatch = a.provider_counts()
    new_transfers = after_dispatch["transfers"] - before_dispatch["transfers"]
    r.advise(len(on_bill) <= 1 and new_transfers <= 1, "a bill already in flight cannot be released a second time under a new approval",
             f"bill of {bill2['amount_due']} with its first release queued: a second, independently approved release was "
             f"{'refused (' + why + ')' if refused else 'executed'}; intents on the bill {len(on_bill)}; dispatching then added {new_transfers} provider transfer(s) "
             f"for the bill ({before_dispatch['transfers']} -> {after_dispatch['transfers']}; 1 is the bill's first, legitimate release, 2 would be a double payment)")


# ---- G6 ---------------------------------------------------------------------- #

def gate_g6(a: LedgerAdapter, r: _Recorder) -> None:
    a.reset()
    a.open_period("G6", "2026-10-01", "2026-10-31")
    same = a.bound_approval_probe(approved_amount="27000.00", current_amount="27000.00")
    r.check(same["outcome"] == "consumed", f"control case: an approval for 27000.00 executed against unchanged facts is consumed (outcome {same['outcome']})", key="g6.control")
    cent = a.bound_approval_probe(approved_amount="27000.00", current_amount="27000.01")
    r.check(cent["outcome"] != "consumed" and cent["status"] == "invalidated", f"a one-cent change after grant (27000.00 -> 27000.01) invalidates: {cent['outcome']}, status {cent['status']}",
            key="g6.one_cent")

    project = a.setup_project()
    cmt = a.setup_commitment(project)
    line = cmt["line_ids"][0]
    approved_base = a.commitment_amount(cmt["commitment_id"])
    change_a = a.propose_change(cmt["commitment_id"], "10000.00", line)
    approval_a = a.request_and_grant("change.execute", change_a)
    change_b = a.propose_change(cmt["commitment_id"], "5000.00", line)
    a.approve_and_execute("change.execute", change_b)
    before = a.commitment_amount(cmt["commitment_id"])
    refused, why, _ = _attempt(a.execute_approval, approval_a)
    after = a.commitment_amount(cmt["commitment_id"])
    status = a.approval_status(approval_a)
    approved_result, current_result = money(D(approved_base) + D("10000.00")), money(D(before) + D("10000.00"))
    r.check(refused and status == "invalidated" and after == before and approved_result != current_result,
            f"a +10000.00 change order approved at a resulting commitment of {_s(approved_result)} is refused after another change moved the base "
            f"from {approved_base} to {before} (resulting {_s(current_result)}): {why}; status {status}; commitment stays {after}", key="g6.changed_base")

    bill = a.certify_bill(cmt["commitment_id"], "G6", line, "20000")
    a.approve_and_execute("bill.approve", bill["bill_id"])
    verified = a.request_and_grant("payment.release", bill["bill_id"], actor_role="treasury")
    a.change_destination(project["supplier_id"], "ACH-SIM-GATE-CHANGED", verified=True)
    refused, why, _ = _attempt(a.execute_approval, verified, actor="treasury")
    status = a.approval_status(verified)
    r.check(refused and status == "invalidated" and not a.payment_intents(),
            f"payee destination re-verified after grant ({project['destination']} -> ACH-SIM-GATE-CHANGED) invalidates the {bill['amount_due']} release ({why}); status {status}; intents {len(a.payment_intents())}",
            key="g6.destination_verified")

    raw = a.request_and_grant("payment.release", bill["bill_id"], actor_role="treasury")
    a.change_destination(project["supplier_id"], "ACH-SIM-GATE-RAW", verified=False)
    refused, why, _ = _attempt(a.execute_approval, raw, actor="treasury")
    status = a.approval_status(raw)
    pc = a.provider_counts()
    r.check(refused and status == "invalidated" and not a.payment_intents() and pc["transfers"] == 0,
            f"a raw master-data destination edit after grant is caught at execution ({why}); status {status}; intents {len(a.payment_intents())}, transfers {pc['transfers']}",
            key="g6.destination_raw")

    a.change_destination(project["supplier_id"], "ACH-SIM-GATE-FINAL", verified=True)
    final = a.request_and_grant("payment.release", bill["bill_id"], actor_role="treasury")
    a.execute_approval(final, actor="treasury")
    intents = a.payment_intents()
    r.check(len(intents) == 1 and intents[0]["destination"] == "ACH-SIM-GATE-FINAL" and intents[0]["amount"] == bill["amount_due"],
            f"control case: a fresh approval after re-verification releases {intents[0]['amount'] if intents else '-'} to {intents[0]['destination'] if intents else '-'} "
            f"(destination version {intents[0]['destination_version'] if intents else '-'})", key="g6.fresh_approval")


# ---- G7 ---------------------------------------------------------------------- #

def gate_g7(a: LedgerAdapter, r: _Recorder) -> None:
    a.reset()
    fixture = a.run_golden_fixture()
    period = fixture["open_period"]
    original = a.post_journal(period_id=period, lines=[_line("5100", "debit", "750.00"), _line("3000", "credit", "750.00")], source_id="g7-correction")
    reversal = a.reverse_journal(original, period_id=period, reason="gate export correction link")
    export = a.audit_export()
    audit_rows = a.audit_row_count()  # read straight after the export, before anything else writes

    sections = ("schema", "chart_of_accounts", "periods", "trial_balance", "journals", "approvals", "ap_reconciliation", "ar_reconciliation", "audit")
    missing = [s for s in sections if s not in export]
    r.check(not missing, f"export carries all {len(sections)} sections (chart, periods, trial balance, journals, approvals, AP/AR reconciliations, schema manifest, audit chain); "
                         f"missing: {', '.join(missing) or 'none'}", key="g7.sections")

    stored = a.journal_ids()
    exported = {j["id"]: j for j in export["journals"]}
    absent = [i for i in stored if i not in exported]
    r.check(not absent and len(exported) == len(stored), f"every stored journal id appears in the export: {len(stored)} stored, {len(exported)} exported, {len(absent)} missing",
            key="g7.journals_complete")

    incomplete = [j["id"] for j in export["journals"] if not j.get("lines") or not all(j.get(k) for k in ("source_type", "source_id", "source_version", "rule_version", "posted_by"))]
    r.check(not incomplete, f"each exported journal carries source type/id/version, posting-rule version, poster and lines ({len(export['journals'])} checked, {len(incomplete)} incomplete)",
            key="g7.journal_fields")

    grand_dr = grand_cr = Decimal("0.00")
    unbalanced = []
    for j in export["journals"]:
        jd = total(ln["debit"] for ln in j["lines"])
        jc = total(ln["credit"] for ln in j["lines"])
        grand_dr += jd
        grand_cr += jc
        if jd != jc:
            unbalanced.append(j["id"])
    tb = export["trial_balance"]
    r.check(not unbalanced and _s(grand_dr) == tb["total_debit"] and _s(grand_cr) == tb["total_credit"],
            f"exported journals balance individually and sum to the exported trial balance: Dr {_s(grand_dr)} / Cr {_s(grand_cr)} vs {tb['total_debit']} / {tb['total_credit']}",
            key="g7.export_balances")

    with_approval = [j for j in export["journals"] if j.get("approval_id")]
    refs = {j["approval_id"] for j in with_approval}
    exported_approvals = {ap["id"] for ap in export["approvals"]}
    r.check(refs <= exported_approvals, f"every approval referenced by a journal is in the export ({len(refs)} referenced, {len(refs - exported_approvals)} missing)", key="g7.approvals")
    unapproved_sources = sorted({j["source_type"] for j in export["journals"] if not j.get("approval_id")})
    r.note(f"{len(with_approval)} of {len(export['journals'])} journals carry an approval id; the rest are source-evidenced events or direct entries ({', '.join(unapproved_sources)})")
    r.check(original in exported and exported.get(reversal, {}).get("reversal_of") == original, f"correction link exported: {reversal} reversal_of {original}", key="g7.correction_link")

    entries = export["audit"]["entries"]
    posted = {e["entity_id"] for e in entries if e["action"] == "journal.posted"}
    covered = len(set(stored) & posted)
    r.check(covered == len(stored), f"every journal has a journal.posted audit entry ({covered} of {len(stored)})", key="g7.journal_audit_entries")
    chain = export["audit"]["chain"]
    r.check(bool(chain.get("ok")), f"exported hash chain verifies: {chain.get('entries')} entries, head {str(chain.get('head', ''))[:16]}", key="g7.chain_ok")
    ok, broken_at = _recompute_chain(entries)
    r.check(ok and len(entries) == chain.get("entries") == audit_rows,
            f"the chain recomputed from the exported rows alone verifies{'' if ok else f' (breaks at seq {broken_at})'} and the export holds every audit row: "
            f"{len(entries)} exported, chain count {chain.get('entries')}, {audit_rows} rows in the audit log", key="g7.chain_recomputed")
    tampered = [dict(e) for e in entries]
    k = len(tampered) // 2
    tampered[k]["payload_json"] = tampered[k]["payload_json"] + " "
    ok2, broken2 = _recompute_chain(tampered)
    r.check(not ok2 and broken2 == tampered[k]["seq"], f"a one-character change to exported entry seq {tampered[k]['seq']} is detected: recomputed chain breaks at seq {broken2}",
            key="g7.tamper_detected")
    outcome, why = _refused_by(a, (CONTROL_IMMUTABILITY,), a.privileged_tamper, "update_audit", "")
    r.check(outcome == "refused", f"raw UPDATE of the audit log {_verdict(outcome, why)}", key="g7.audit_update_refused")

    triggers = {o["name"] for o in export["schema"]["objects"] if o["type"] == "trigger"}
    missing_triggers = [t for t in REQUIRED_TRIGGERS if t not in triggers]
    r.check(not missing_triggers, f"schema manifest lists {len(REQUIRED_TRIGGERS) - len(missing_triggers)} of {len(REQUIRED_TRIGGERS)} required control triggers "
                                  f"(immutability, period lock and reopen, journal seal, append-only approvals; {len(triggers)} triggers in total); "
                                  f"missing: {', '.join(missing_triggers) or 'none'}", key="g7.triggers")
    status = export["schema"]["schema_status"]
    applied = [v for v in status["versions"] if v["applied"]]
    r.check(not status["pending"] and all(v["checksum_matches"] for v in applied),
            f"schema manifest: {len(applied)} catalog entries applied (database version {status['current_version']}), {len(status['pending'])} pending, all checksums match",
            key="g7.schema_status")
    size = len(json.dumps(export, default=str))
    r.check(size > 0, f"export serialises to JSON ({size} bytes)", key="g7.serialises")


# ---- G8 ---------------------------------------------------------------------- #

def gate_g8(a: LedgerAdapter, r: _Recorder) -> None:
    workdir = tempfile.mkdtemp(prefix="cipher-core-gate-g8-")
    opened: list[LedgerAdapter] = []
    try:
        a.reset(os.path.join(workdir, "live.sqlite"))
        a.open_period("G8-P1", "2026-10-01", "2026-10-31")
        project = a.setup_project()
        cmt = a.setup_commitment(project)
        bill = a.certify_bill(cmt["commitment_id"], "G8-P1", cmt["line_ids"][0], "20000")
        a.approve_and_execute("bill.approve", bill["bill_id"])
        prime = a.setup_sent_prime_bill(project, "G8-P1", "10000")
        release = a.request_and_grant("payment.release", bill["bill_id"], actor_role="treasury")
        a.execute_approval(release, actor="treasury")
        older = a.snapshot(os.path.join(workdir, "older-before-dispatch.sqlite"))
        a.set_provider_mode("timeout_after_accept")
        dispatched = a.dispatch_payments()
        a.set_provider_mode("accept")
        pc0 = a.provider_counts()
        r.note(f"live workspace: {bill['amount_due']} released for the bill and dispatched; the provider response was lost "
               f"({dispatched[0]['status'] if dispatched else 'nothing dispatched'}); provider holds {pc0['transfers']} transfer(s) after {pc0['submissions']} submission(s)")
        backup = a.snapshot(os.path.join(workdir, "backup-after-dispatch.sqlite"))
        probe_copy = a.snapshot(os.path.join(workdir, "probe-copy.sqlite"))

        restored = a.open_restored(backup)
        opened.append(restored)
        auth = restored.authority_status()
        r.check(not auth["effective_write_authority"], f"restored copy opens without write authority (effective_write_authority={auth['effective_write_authority']}, "
                                                       f"instance_matches={auth.get('instance_matches')})", key="g8.restored_without_authority")
        n0 = restored.journal_count()
        outcome, why = _refused_by(restored, (CONTROL_WRITE_AUTHORITY,), restored.execute_approval, release, actor="treasury")
        r.check(outcome == "refused" and restored.journal_count() == n0 and len(restored.payment_intents()) == 1,
                f"replaying the pre-restore payment execution on the restored copy {_verdict(outcome, why)}; journals {n0} -> {restored.journal_count()}", key="g8.replay_refused")

        # Spec: "a restored copy has no write authority" - every mutation path, not only the command boundary.
        probe = a.open_restored(probe_copy)
        opened.append(probe)
        authority = probe.authority_status()["effective_write_authority"]
        before = probe.journal_count()
        c_out, c_why = _refused_by(probe, (CONTROL_WRITE_AUTHORITY,), probe.record_collection, prime["prime_bill_id"], "G8-P1", "4500.00", "gate-rcv-on-restored-copy")
        mid = probe.journal_count()
        p_out, p_why = _refused_by(probe, (CONTROL_WRITE_AUTHORITY,), probe.post_journal, period_id="G8-P1",
                                   lines=[_line("5000", "debit", "1.00"), _line("3000", "credit", "1.00")], source_id="g8-direct")
        after = probe.journal_count()
        r.check(not authority and c_out == "refused" and p_out == "refused" and after == before,
                f"on a restored copy without write authority (effective_write_authority={authority}) every mutation path is refused: "
                f"the console/HTTP record_collection action for 4500.00 {_verdict(c_out, c_why)} (journals {before} -> {mid}); "
                f"a direct ledger post of 1.00 {_verdict(p_out, p_why)} (journals {mid} -> {after})", key="g8.restored_copy_refuses_mutations")

        # The read-only state is enforced by the database itself, so the privileged path is
        # refused too, including an attempt to switch the guard off first (cipher-core-gates/3).
        before = probe.journal_count()
        h_out, h_why = _refused_by(probe, (CONTROL_WRITE_AUTHORITY,), probe.privileged_insert_journal, "G8-P1")
        g_out, g_why = _refused_by(probe, (CONTROL_WRITE_AUTHORITY,), probe.privileged_lift_write_guard)
        h2_out, h2_why = _refused_by(probe, (CONTROL_WRITE_AUTHORITY,), probe.privileged_insert_journal, "G8-P1")
        after = probe.journal_count()
        still = probe.authority_status()
        r.check(h_out == "refused" and g_out == "refused" and h2_out == "refused" and after == before and not still["effective_write_authority"],
                f"privileged path on the same copy: a raw INSERT of a journal header into open period G8-P1 {_verdict(h_out, h_why)}; "
                f"switching the read-only guard off from that session {_verdict(g_out, g_why)}; the raw INSERT again {_verdict(h2_out, h2_why)}; "
                f"journals {before} -> {after}; read_only {still.get('read_only')}", key="g8.restored_copy_refuses_privileged_writes")

        # A read-only copy cannot record an approval of its own, so the claim is an attested
        # owner action whose credential the copy cannot mint (for the native core, an owner
        # claim code derived from CIPHER_OWNER_SECRET, configured for the drill).  This check
        # replaces g8.claim_requires_recorded_approval (cipher-core-gates/2).
        fabricated = "apr_gate_unrecorded_claim"
        claims_before = len(probe.authority_claims())
        attempts = []
        for label, credential in ((f"a fabricated credential '{fabricated}'", fabricated), ("a blank credential", "")):
            cl_out, cl_why = _refused_by(probe, (CONTROL_WRITE_AUTHORITY, CONTROL_APPROVAL_REFERENCE), probe.claim_write_authority, credential)
            attempts.append((cl_out == "refused", f"{label} {_verdict(cl_out, cl_why)}"))
        gained = probe.authority_status()["effective_write_authority"]
        claims_after = len(probe.authority_claims())
        r.check(all(ok for ok, _ in attempts) and not gained and claims_after == claims_before,
                "claiming write authority on a restored copy without the owner's attestation: " + "; ".join(text for _, text in attempts)
                + f"; effective write authority afterwards {gained}; recorded claims {claims_before} -> {claims_after}", key="g8.claim_requires_attestation")

        # Advisory: the same claim in the default configuration (no owner secret configured).
        d_out, d_why = _refused_by(probe, (CONTROL_WRITE_AUTHORITY, CONTROL_APPROVAL_REFERENCE), probe.claim_write_authority_default_config, fabricated)
        d_gained = probe.authority_status()["effective_write_authority"]
        r.advise(d_out == "refused" and not d_gained,
                 "a restored copy cannot gain write authority without an attestation it cannot mint, even in the default configuration",
                 f"with no owner secret configured, a claim presenting the fabricated credential '{fabricated}' {_verdict(d_out, d_why)}; "
                 f"effective write authority afterwards {d_gained}"
                 + (" - in that configuration the claim is self-attested (an approver name and a reason), so the owner secret must be "
                    "configured wherever restored copies are opened" if d_gained else ""))

        claim = restored.claim_write_authority_approved()
        auth = restored.authority_status()
        record = next((c for c in restored.authority_claims() if c["ref"] == claim["ref"]), None)
        attested = bool(record) and bool(record["approver"]) and bool(record["reason"]) and bool(record["verified"])
        r.check(attested and auth["effective_write_authority"] and auth["release_quarantined"] and auth["recovery_epoch"] > auth["reconciled_epoch"],
                f"control case: an attested claim (approver {record['approver'] if record else '-'}, reason recorded {bool(record and record['reason'])}, "
                f"credential verified {bool(record and record['verified'])}) gives write authority {auth['effective_write_authority']}, recovery epoch {auth['recovery_epoch']} > "
                f"reconciled epoch {auth['reconciled_epoch']}, release quarantined {auth['release_quarantined']}", key="g8.claim_with_attestation")
        claims_before = len(restored.authority_claims())
        epoch_before = auth["authority_epoch"]
        rp_out, rp_why = _refused_by(restored, (CONTROL_WRITE_AUTHORITY, CONTROL_APPROVAL_REFERENCE), restored.claim_write_authority, claim["credential"])
        claims_after = len(restored.authority_claims())
        epoch_after = restored.authority_status()["authority_epoch"]
        r.check(rp_out == "refused" and claims_after == claims_before and epoch_after == epoch_before,
                f"replaying the credential of that claim on the same copy {_verdict(rp_out, rp_why)}; recorded claims {claims_before} -> {claims_after}, "
                f"authority epoch {epoch_before} -> {epoch_after}", key="g8.claim_credential_single_use")

        outcome, why = _refused_by(restored, (CONTROL_QUARANTINE,), restored.dispatch_payments)
        r.check(outcome == "refused" and a.provider_counts() == pc0, f"dispatch during the quarantine {_verdict(outcome, why)}; provider transfers {a.provider_counts()['transfers']}",
                key="g8.dispatch_quarantined")
        again = restored.request_and_grant("payment.release", bill["bill_id"], actor_role="treasury")
        outcome, why = _refused_by(restored, (CONTROL_QUARANTINE,), restored.execute_approval, again, actor="treasury")
        r.check(outcome == "refused" and len(restored.payment_intents()) == 1, f"a new payment release during the quarantine {_verdict(outcome, why)}; intents {len(restored.payment_intents())}",
                key="g8.release_quarantined")

        outcome = restored.complete_recovery()
        intents = restored.payment_intents()
        pc1 = a.provider_counts()
        found = outcome.get("results", [])
        r.check(bool(outcome.get("quarantine_lifted")) and len(intents) == 1 and intents[0]["status"] == "accepted" and pc1 == pc0,
                f"recovery reconciliation found the pre-restore transfer {found[0].get('provider_ref') if found else '-'} by logical operation id: intent {intents[0]['status'] if intents else '-'}; "
                f"provider transfers {pc0['transfers']} -> {pc1['transfers']}, submissions {pc0['submissions']} -> {pc1['submissions']} (no resubmission); quarantine lifted {outcome.get('quarantine_lifted')}",
                key="g8.recovery_finds_transfer")
        sent = restored.dispatch_payments()
        pc2 = a.provider_counts()
        r.check(not sent and pc2 == pc0, f"dispatch after recovery sends nothing new ({len(sent)} dispatched); provider transfers {pc2['transfers']}", key="g8.no_dispatch_after_recovery")
        ap = restored.ap_reconciliation()
        r.check(bool(ap["reconciled"]), f"AP reconciles on the recovered copy: subledger {ap['subledger_total']} = control {ap['control_balance']}", key="g8.ap_reconciles")

        # Plan section 10 step 11: restore an OLDER backup (taken before dispatch) in recovery quarantine and
        # reconcile external receipts before allowing any release.  Nothing may be resubmitted.
        old = a.open_restored(older)
        opened.append(old)
        # Advisory: a credential issued for one restored copy should not also authorise a
        # sibling copy of the same workspace (both copies still sit at the same authority epoch).
        s_out, s_why = _refused_by(old, (CONTROL_WRITE_AUTHORITY, CONTROL_APPROVAL_REFERENCE), old.claim_write_authority, claim["credential"])
        s_gained = old.authority_status()["effective_write_authority"]
        r.advise(s_out == "refused" and not s_gained,
                 "a claim credential used on one restored copy cannot authorise a sibling copy of the same workspace",
                 f"the credential already used to claim the after-dispatch copy, presented on the older (before-dispatch) copy, {_verdict(s_out, s_why)}; "
                 f"effective write authority afterwards {s_gained}"
                 + (" - the credential is bound to the workspace and its authority epoch, which every copy taken before a claim shares, "
                    "so one disclosed credential opens every such copy (each still starts in release quarantine)" if s_gained else ""))
        if not s_gained:
            old.claim_write_authority_approved()
        start = a.provider_counts()
        recovered = old.complete_recovery()
        refused, why, value = _attempt(old.dispatch_payments)
        end = a.provider_counts()
        resubmitted = end["submissions"] - start["submissions"]
        dispatch_text = f"refused ({why})" if refused else f"sent {len(value or [])} payment(s)"
        caveat = (" - a second transfer was avoided only because the simulator honours the idempotency key, which plan section 4 says the reviewed provider docs do not establish"
                  if resubmitted and end["transfers"] == start["transfers"] else "")
        old_intents = old.payment_intents()
        held = recovered.get("held") or []
        r.check(resubmitted == 0,
                f"restoring the backup taken before dispatch: recovery reconciled {len(recovered.get('results', []))} intent(s) "
                f"(intent statuses now {', '.join(i['status'] for i in old_intents) or 'none'}) and lifted the quarantine ({recovered.get('quarantine_lifted')}"
                f"{'; held: ' + '; '.join(held) if held else ''}); "
                f"dispatch afterwards {dispatch_text}; provider submissions {start['submissions']} -> {end['submissions']} ({resubmitted} resubmission(s)), "
                f"transfers {start['transfers']} -> {end['transfers']}{caveat}", key="g8.older_backup_no_resubmission")
    finally:
        for other in opened:
            other.close()
        a.close()
        shutil.rmtree(workdir, ignore_errors=True)
        r.note(f"temporary workspace removed after the drill: {not os.path.exists(workdir)}")


# ---- G9 ---------------------------------------------------------------------- #

EMPLOYEE_CLAIM = "1234.56"
EMPLOYEE_PAID = "234.56"


def gate_g9(a: LedgerAdapter, r: _Recorder) -> None:
    a.reset()
    fixture = a.run_golden_fixture()
    project_id = fixture["project_id"]
    scenario_error = None
    try:
        reimbursement = a.add_employee_reimbursement(project_id, fixture["open_period"], EMPLOYEE_CLAIM, EMPLOYEE_PAID)
    except Exception as exc:  # recorded as a failed check below; AP and AR are still reconciled
        reimbursement, scenario_error = None, f"{type(exc).__name__}: {_short(exc)}"
    if scenario_error:
        r.check(False, f"employee reimbursement scenario failed ({scenario_error}), so the employee payable cannot be reconciled against a non-zero balance",
                key="g9.employee_scenario")
    elif reimbursement is None:
        r.note("the candidate registers no employee-payable subledger; GL 2100 must then stay at 0.00")
    else:
        r.note(f"after the golden fixture an employee claim of {EMPLOYEE_CLAIM} was approved and a {EMPLOYEE_PAID} payment released in {fixture['open_period']}")
    rec = a.subledger_reconciliation(project_id)

    ap = rec["ap"]
    gl_ap = a.balance("2000", project_id=project_id)
    r.check(bool(ap["reconciled"]) and D(ap["subledger_total"]) == gl_ap and ap["subledger_total"] == "18000.00",
            f"AP: open-bill subledger {ap['subledger_total']} = GL 2000 {_s(gl_ap)} (golden expectation 18000.00)", key="g9.ap")
    ar = rec["ar"]
    gl_ar = a.balance("1100", project_id=project_id)
    r.check(bool(ar["reconciled"]) and D(ar["subledger_total"]) == gl_ar and ar["subledger_total"] == "54000.00",
            f"AR: open prime-bill subledger {ar['subledger_total']} = GL 1100 {_s(gl_ar)} (54000.00 after the late collection return)", key="g9.ar")
    emp = rec["employee_payable"]
    gl_emp = a.balance("2100", project_id=project_id)
    if emp is None:
        r.check(gl_emp == Decimal("0.00") and reimbursement is None and scenario_error is None,
                f"employee payable: no subledger registered and GL 2100 is {_s(gl_emp)}", key="g9.employee_payable")
    else:
        in_flight = f"; {emp['in_flight_total']} of it in a payment still in flight" if "in_flight_total" in emp else ""
        exercised = reimbursement is not None and Decimal("0.00") < gl_emp <= D(EMPLOYEE_CLAIM)
        r.check(bool(emp["reconciled"]) and D(emp["subledger_total"]) == gl_emp and exercised,
                f"employee payable: open-claim subledger {emp['subledger_total']} = GL 2100 {_s(gl_emp)} across {len(emp.get('items', []))} claim(s){in_flight}"
                f"{'' if exercised else ' - not exercised: the scenario left no employee payable to reconcile'}", key="g9.employee_payable")
    tb = a.trial_balance()
    r.check(bool(tb["balanced"]), f"trial balance after the fixture: Dr {tb['total_debit']} = Cr {tb['total_credit']} over {tb['journal_count']} journals", key="g9.trial_balance")
    r.note(f"other control balances for context: retainage payable 2050 {_s(a.balance('2050'))}, stored materials 1300 {_s(a.balance('1300'))}, "
           f"operating bank 1000 {_s(a.balance('1000'))}, provider clearing 1200 {_s(a.balance('1200'))}")


GATES: dict[str, Callable[[LedgerAdapter, _Recorder], None]] = {
    "G1": gate_g1, "G2": gate_g2, "G3": gate_g3, "G4": gate_g4, "G5": gate_g5,
    "G6": gate_g6, "G7": gate_g7, "G8": gate_g8, "G9": gate_g9,
}


# --------------------------------------------------------------------------- #
# Running gates and scoring                                                    #
# --------------------------------------------------------------------------- #

def run_gate(gate_id: str, adapter: LedgerAdapter) -> dict[str, Any]:
    """Run one hard gate.  Never raises for a candidate's failure: an unavailable
    adapter yields ``not_run`` and any error inside the gate yields ``fail``."""
    if gate_id not in GATES:
        raise CoreGateError(f"unknown gate {gate_id!r}; gates are {', '.join(GATE_IDS)}")
    ok, reason = adapter.available()
    if not ok:
        return {"gate": gate_id, "title": GATE_TITLES[gate_id], "status": "not_run", "evidence": [f"NOT RUN: {reason}"],
                "checks": {"passed": 0, "failed": 0, "total": 0}, "failed_checks": [], "advisories": []}
    rec = _Recorder(gate_id)
    try:
        GATES[gate_id](adapter, rec)
    except Exception as exc:  # the gate must report, not crash the scorecard
        rec.abort(exc)
    finally:
        try:
            adapter.close()
        except Exception as exc:
            rec.note(f"adapter close failed: {type(exc).__name__}: {_short(exc)}")
    return rec.result()


def run_gates(adapter: LedgerAdapter, gate_ids: tuple[str, ...] | list[str] | None = None) -> list[dict[str, Any]]:
    return [run_gate(g, adapter) for g in (gate_ids or GATE_IDS)]


def weights_total() -> int:
    return sum(WEIGHTS.values())


def _score(value, criterion: str) -> Decimal:
    if isinstance(value, float) or isinstance(value, bool):
        raise CoreGateError(f"score for {criterion} must be an int, str or Decimal, not {type(value).__name__}")
    try:
        s = Decimal(str(value)) if not isinstance(value, Decimal) else value
    except Exception as exc:
        raise CoreGateError(f"score for {criterion} is not a number: {value!r}") from exc
    if not s.is_finite():
        raise CoreGateError(f"score for {criterion} must be a finite number, got {value!r}")
    if s < 0 or s > MAX_SCORE:
        raise CoreGateError(f"score for {criterion} must lie between 0 and 5, got {value!r}")
    return s.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _control_fit(gates: list[dict[str, Any]]) -> tuple[Decimal, str]:
    hard_passed = sum(g["checks"]["passed"] for g in gates)
    hard_total = sum(g["checks"]["total"] for g in gates)
    advisories = [adv for g in gates for adv in g["advisories"]]
    adv_passed = sum(1 for adv in advisories if adv["status"] == "pass")
    passed = hard_passed + adv_passed
    executed = hard_total + len(advisories)
    if executed == 0:
        raise CoreGateError("no control checks were executed")
    score = (MAX_SCORE * passed / executed).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    rationale = (f"COMPUTED from the gates: {passed} of {executed} executed control checks passed "
                 f"({hard_passed}/{hard_total} hard, {adv_passed}/{len(advisories)} advisory); score = 5 x {passed}/{executed}. "
                 "Measures control mechanics on synthetic data only, not accounting-policy correctness.")
    return score, rationale


def evaluate_candidate(adapter: LedgerAdapter, gate_ids: tuple[str, ...] | list[str] | None = None) -> dict[str, Any]:
    """Run the hard gates against ``adapter`` and score it if it passes all of them."""
    ok, reason = adapter.available()
    gates = run_gates(adapter, gate_ids)
    summary = {s: sum(1 for g in gates if g["status"] == s) for s in ("pass", "fail", "not_run")}
    failed = [g["gate"] for g in gates if g["status"] == "fail"]
    advisories = [adv for g in gates for adv in g["advisories"]]
    out: dict[str, Any] = {
        "candidate": adapter.candidate,
        "label": adapter.label,
        "available": ok,
        "availability": reason,
        "gates": gates,
        "hard_gate_summary": summary,
        "hard_check_summary": {"passed": sum(g["checks"]["passed"] for g in gates), "failed": sum(g["checks"]["failed"] for g in gates),
                               "total": sum(g["checks"]["total"] for g in gates)},
        "failed_checks": [key for g in gates for key in g["failed_checks"]],
        "advisories": advisories,
        "open_advisories": sum(1 for adv in advisories if adv["status"] == "open"),
        "disqualified_by": failed,
        "scores": None,
        "weighted_total": None,
        "weighted_percent": None,
    }
    if not ok:
        out["status"] = "not_evaluated"
        return out
    if failed:
        out["status"] = "disqualified"
        return out
    if summary["pass"] != len(GATE_IDS):
        out["status"] = "incomplete"
        return out

    assumed = adapter.assumed_scores() or {}
    missing = [c for c in ASSUMED_CRITERIA if c not in assumed]
    if missing:
        raise CoreGateError(f"adapter {adapter.candidate} did not supply assumed scores for: {', '.join(missing)}")
    control, control_rationale = _control_fit(gates)
    rows = [{"criterion": "accounting_control_fit", "label": CRITERIA_LABELS["accounting_control_fit"], "weight": WEIGHTS["accounting_control_fit"],
             "score": control, "basis": "computed", "rationale": control_rationale}]
    for criterion in ASSUMED_CRITERIA:
        value, rationale = assumed[criterion]
        if not isinstance(rationale, str) or not rationale.startswith("ASSUMPTION"):
            raise CoreGateError(f"the {criterion} score of {adapter.candidate} must be labelled ASSUMPTION with a rationale")
        rows.append({"criterion": criterion, "label": CRITERIA_LABELS[criterion], "weight": WEIGHTS[criterion],
                     "score": _score(value, criterion), "basis": "ASSUMPTION", "rationale": rationale})
    weighted = sum((row["score"] * row["weight"] for row in rows), Decimal(0)) / Decimal(100)
    for row in rows:
        row["weighted"] = f"{(row['score'] * row['weight'] / Decimal(100)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP):f}"
        row["score"] = f"{row['score']:f}"
    out["status"] = "scored"
    out["scores"] = rows
    out["weighted_total"] = f"{weighted.quantize(TWO_PLACES, rounding=ROUND_HALF_UP):f}"
    out["weighted_percent"] = f"{(weighted / MAX_SCORE * 100).quantize(TWO_PLACES, rounding=ROUND_HALF_UP):f}"
    return out


def _decision_note(candidates: list[dict[str, Any]], native: dict[str, Any] | None) -> str:
    scored = [c["candidate"] for c in candidates if c["status"] == "scored"]
    if native is not None and native["status"] == "disqualified":
        return ("No foundation can be selected. The native core fails hard gate(s) " + ", ".join(native["disqualified_by"])
                + " (failed checks: " + ", ".join(native["failed_checks"]) + "), so it is disqualified and not scored; "
                "no other candidate was evaluated. Fix those native-core gaps and re-run, and/or run the same gates against an isolated ERPNext stack.")
    return ("No comparative decision is possible yet: only " + (", ".join(scored) or "no candidate") + " was scored. "
            "Non-control scores are ASSUMPTIONS. Run the same gates against an isolated ERPNext stack before choosing a foundation.")


def build_scorecard(adapters: list[LedgerAdapter] | None = None) -> dict[str, Any]:
    """Evaluate every candidate (default: native Cipher and ERPNext) into one scorecard."""
    if weights_total() != 100:
        raise CoreGateError(f"scorecard weights must sum to 100, not {weights_total()}")
    adapters = adapters if adapters is not None else [NativeCipherAdapter(), ERPNextAdapter()]
    candidates = [evaluate_candidate(a) for a in adapters]
    native = next((c for c in candidates if c["candidate"] == NativeCipherAdapter.candidate), None)
    native_passes = bool(native) and native["hard_gate_summary"]["pass"] == len(GATE_IDS)
    return {
        "tool": "apps.cipher.tools.core_gates",
        "version": SCORECARD_VERSION,
        "generated_at": utcnow_iso(),
        "plan_reference": PLAN_REFERENCE,
        "scope": "Synthetic prototype, one owner, one USD entity, shadow finance, simulated payments. "
                 "The gates prove control mechanics on synthetic data.",
        "does_not_prove": DOES_NOT_PROVE,
        "weights": dict(WEIGHTS),
        "weights_total": weights_total(),
        "hard_gates": [{"gate": g, "title": GATE_TITLES[g]} for g in GATE_IDS],
        "candidates": candidates,
        "native_passes_all_hard_gates": native_passes,
        "native_failed_checks": list(native["failed_checks"]) if native else [],
        "decision_note": _decision_note(candidates, native),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m apps.cipher.tools.core_gates", description="Run the accounting-core decision gates and print the JSON scorecard.")
    parser.add_argument("--out", default=None, help="also write the JSON scorecard to this file")
    args = parser.parse_args(argv)
    scorecard = build_scorecard()
    text = json.dumps(scorecard, indent=2, sort_keys=False)
    print(text)
    if args.out:
        directory = os.path.dirname(os.path.abspath(args.out))
        os.makedirs(directory, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0 if scorecard["native_passes_all_hard_gates"] else 1


if __name__ == "__main__":
    sys.exit(main())
