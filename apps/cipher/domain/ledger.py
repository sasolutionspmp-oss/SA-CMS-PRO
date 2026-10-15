"""Double-entry general ledger: chart, periods, immutable journals, reversals, trial balance.

Invariants (from the plan, section 6):

1. exact decimal amounts;
2. every journal balances and carries source id/version, posting-rule version and approval;
3. posted entries are never updated or deleted (SQLite triggers enforce it); corrections append reversals;
4. period locks apply to every posting path (trigger on insert);
5. control balances reconcile to subledgers (checked by the subledger modules);
10. statements drill down to journals and sources.

Schema-level controls (core/db.py, "ledger_integrity" and "period_integrity"):
a posted journal is sealed by its declared line count, so a raw INSERT of an
extra line is refused; a journal is reversed at most once; a locked period never
changes; closed -> open needs a consumed, unused ``*.reopen_period`` approval
scoped to that period, which ``reopen_period`` also checks in Python.

The ledger is a core domain that owns one approval-bound operation,
``journal.reverse`` (subject: the journal id).  The reason is recorded first with
``prepare_reversal``; the manifest binds the journal's line fingerprint, totals,
source, reversal state and that request, and execution needs ``period_id`` of the
open period that receives the reversal.  An approval can be requested only while
the journal is unreversed and its latest request is pending; once either changes,
executing an earlier approval invalidates it.  Journals whose source document is
kept by a subledger that does not follow a bare ledger reversal (a bill stays
payable, a payment stays settled, an asset stays capitalized, an approved timesheet
stays accrued) are refused: they are corrected through the owning module's own
operation (``SUBLEDGER_OWNED_SOURCES``).  A reversal journal is never itself
reversed through ``journal.reverse``.  A module whose document follows a reversal
with a change of its own registers a hook for its source type in
``Ledger.reversal_hooks``; ``reverse`` runs it in the reversal's transaction.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Callable

from ..core.approvals import StaleApprovalError, build_manifest
from ..core.audit import Audit
from ..core.db import Database
from ..core.ids import hash_json, new_id, utcnow_iso
from ..core.money import ZERO, fmt, money
from ..core.words import us

RULE_VERSION = "cipher-posting-rules/1"
OP_REVERSE = "journal.reverse"
REOPEN_SUFFIX = ".reopen_period"
REOPEN_SUBJECT_TYPES = ("period", "accounting_period")
REVERSAL_SUBJECT = "journal"
MAX_REASON_LENGTH = 500

# Journal source types whose document lives in a subledger that does not follow a bare
# ledger reversal: reversing only the journal would leave the document live while its
# control account moves (for a bill: AP control 0, the bill still payable, and a payment
# release would still pay it).  journal.reverse refuses them and names the owning path.
# Sources whose module derives its subledger from the journals themselves and treats a
# reversal as clearing the document (prime bills, retainage invoices and collections in
# receivables; labor invoices, whose time a reversal frees to be billed again, and collections;
# reimbursement billings and collections) stay reversible.  A module that adapts can be
# dropped from Ledger.reversal_owners.
SUBLEDGER_OWNED_SOURCES: dict[str, str] = {
    "bill": "the bills subledger (the bill would stay posted and payable)",
    "retainage_release": "the bills subledger (retainage.release)",
    "payment_intent": "the payments subledger (the payment would stay settled)",
    "provider_event": "the payments subledger (provider events and returns)",
    "asset": "the asset register (asset.* operations)",
    "asset_run": "the asset register (asset.reverse_depreciation)",
    "wip_adjustment": "the close module (close.reverse_wip_adjustment)",
    "reimbursement_claim": "the reimbursements module (reimbursement.void)",
    "labor_timesheet": "the labor module (an approved timesheet stays approved; its 2200 accrual and payroll follow the timesheet, not the journal)",
    "labor_payroll": "the labor module (a posted payroll stays settled; the 2200 accrual follows payroll status, not the journal)",
}

# code, name, type, control kind
CHART: list[tuple[str, str, str, str | None]] = [
    ("1000", "Operating bank", "asset", "bank"),
    ("1100", "Accounts receivable", "asset", "ar"),
    ("1150", "Retainage receivable", "asset", "ar_retainage"),
    ("1200", "Provider clearing", "asset", "clearing"),
    ("1300", "Stored materials (controlled)", "asset", "stored_materials"),
    ("1500", "Fixed assets", "asset", "fixed_assets"),
    ("1590", "Accumulated depreciation", "asset", "accumulated_depreciation"),
    ("2000", "Accounts payable", "liability", "ap"),
    ("2050", "Retainage payable", "liability", "ap_retainage"),
    ("2100", "Employee reimbursements payable", "liability", "ap_employee"),
    ("3000", "Owner equity", "equity", None),
    ("4000", "Contract revenue", "revenue", None),
    ("5000", "Project cost - subcontract", "expense", None),
    ("5100", "Project cost - reimbursable expense", "expense", None),
    ("5200", "Depreciation expense", "expense", None),
    ("6000", "Bank and processing fees", "expense", None),
]

DEBIT_NORMAL = {"asset", "expense"}


class LedgerError(RuntimeError):
    pass


class UnbalancedJournal(LedgerError):
    pass


class PeriodNotOpen(LedgerError):
    pass


class SubledgerOwnedJournal(LedgerError):
    """journal.reverse refused: the journal's source document is kept by a subledger."""


class ReversalNotAvailable(LedgerError, StaleApprovalError):
    """The journal is already reversed, or its latest reversal request is no longer
    pending.  Raised while building a journal.reverse manifest, so a new approval cannot
    be requested and executing an earlier one invalidates it (it is a StaleApprovalError)."""


def _text(value: Any, label: str, *, max_length: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LedgerError(f"{label} is required")
    text = value.strip()
    if max_length is not None and len(text) > max_length:
        raise LedgerError(f"{label} is longer than {max_length} characters")
    return text


def lines_fingerprint(lines: list[dict[str, Any]]) -> str:
    """Hash of a journal's stored lines (order, accounts, amounts, dimensions, memo)."""
    return hash_json([
        [ln["line_no"], ln["account_code"], ln["debit"], ln["credit"], ln["project_id"], ln["party_id"], ln["memo"]]
        for ln in sorted(lines, key=lambda x: x["line_no"])
    ])


class Ledger:
    def __init__(self, db: Database, audit: Audit):
        self.db = db
        self.audit = audit
        self.reversal_owners: dict[str, str] = dict(SUBLEDGER_OWNED_SOURCES)
        # source type -> hook(original journal, reversal journal, actor), run by ``reverse``
        # inside its transaction for a module whose document follows the reversal; a hook that
        # raises rolls the reversal back.
        self.reversal_hooks: dict[str, Callable[[dict[str, Any], dict[str, Any], str], None]] = {}

    # ---- chart and periods ------------------------------------------------ #

    def ensure_chart(self) -> None:
        """Add any missing chart account.  Writes nothing when the chart is complete,
        so a read-only (restored, unclaimed) workspace still opens."""
        existing = {r["code"] for r in self.db.query("SELECT code FROM accounts")}
        missing = [row for row in CHART if row[0] not in existing]
        if not missing or getattr(self.db, "read_only", False):
            return
        with self.db.transaction() as conn:
            for code, name, typ, control in missing:
                conn.execute("INSERT OR IGNORE INTO accounts (code, name, type, control_kind) VALUES (?,?,?,?)", (code, name, typ, control))

    def accounts(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM accounts ORDER BY code")

    def account_for_control(self, control_kind: str) -> str:
        row = self.db.one("SELECT code FROM accounts WHERE control_kind = ?", (control_kind,))
        if row is None:
            raise LedgerError(f"no control account for {control_kind}")
        return row["code"]

    def open_period(self, period_id: str, name: str, start_date: str, end_date: str, *, actor: str = "system") -> dict[str, Any]:
        # Aging, cutoffs, depreciation and close compare these as ISO date text, so only exact
        # YYYY-MM-DD dates in order are accepted.
        for label, value in (("start", start_date), ("end", end_date)):
            try:
                ok = isinstance(value, str) and date.fromisoformat(value).isoformat() == value
            except ValueError:
                ok = False
            if not ok:
                raise LedgerError(f"period {label} date must be a YYYY-MM-DD date, not {value!r}")
        if end_date < start_date:
            raise LedgerError(f"period {period_id} ends {end_date}, before it starts {start_date}")
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM periods WHERE id=?", (period_id,)).fetchone() is not None:
                raise LedgerError(f"period {period_id} already exists")
            conn.execute(
                "INSERT INTO periods (id, name, start_date, end_date, status) VALUES (?,?,?,?,'open')",
                (period_id, name, start_date, end_date),
            )
            self.audit.record(actor, "period.opened", "period", period_id, {"name": name, "start": start_date, "end": end_date})
        return self.period(period_id)

    def period(self, period_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM periods WHERE id = ?", (period_id,))
        if row is None:
            raise LedgerError(f"unknown period {period_id}")
        return row

    def periods(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM periods ORDER BY start_date")

    def require_open(self, period_id: str) -> dict[str, Any]:
        p = self.period(period_id)
        if p["status"] != "open":
            raise PeriodNotOpen(f"period {period_id} is {p['status']}")
        return p

    def close_period(self, period_id: str, *, actor: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            p = self.require_open(period_id)
            tb = self.trial_balance(period_id)
            if not tb["balanced"]:
                raise UnbalancedJournal(f"period {period_id} trial balance does not balance; cannot close")
            conn.execute("UPDATE periods SET status='closed', closed_at=?, closed_by=? WHERE id=?", (utcnow_iso(), actor, period_id))
            self.audit.record(actor, "period.closed", "period", period_id, {"journals": tb["journal_count"], "total_debit": tb["total_debit"]})
        return self.period(period_id)

    def lock_period(self, period_id: str, *, actor: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            p = self.period(period_id)
            if p["status"] != "closed":
                raise LedgerError("only a closed period can be locked")
            conn.execute("UPDATE periods SET status='locked' WHERE id=?", (period_id,))
            self.audit.record(actor, "period.locked", "period", period_id, {})
        return self.period(period_id)

    def reopen_period(self, period_id: str, *, actor: str, approval_ref: str) -> dict[str, Any]:
        """Reopen a closed period.  ``approval_ref`` must be the id of a recorded
        approval for a ``*.reopen_period`` operation on this period that has been
        consumed (granted and executed) and has never reopened a period before.
        The period_integrity triggers enforce the same rule on any raw UPDATE."""
        ref = approval_ref.strip() if isinstance(approval_ref, str) else ""
        if not ref:
            raise LedgerError("reopening a period requires the id of a consumed reopen_period approval for that period")
        with self.db.transaction() as conn:
            p = self.period(period_id)
            if p["status"] == "locked":
                raise PeriodNotOpen(f"period {period_id} is locked and can never be reopened")
            if p["status"] != "closed":
                raise LedgerError(f"period {period_id} is {p['status']}; only a closed period can be reopened")
            approval = self._reopen_approval(period_id, ref)
            conn.execute("UPDATE periods SET status='open', closed_at=NULL, closed_by=NULL, reopen_approval_id=? WHERE id=?", (ref, period_id))
            self.audit.record(actor, "period.reopened", "period", period_id, {"approval_ref": ref, "approval_operation": approval["operation"]})
        return self.period(period_id)

    def _reopen_approval(self, period_id: str, ref: str) -> dict[str, Any]:
        ap = self.db.one(
            "SELECT id, operation, subject_type, subject_id, status, approver, granted_at, consumed_at, consumed_by FROM approvals WHERE id=?", (ref,))
        if ap is None:
            raise LedgerError(f"approval reference {ref!r} is not a recorded approval; reopening {period_id} needs a consumed reopen_period approval for it")
        op = ap["operation"]
        if not (op.endswith(REOPEN_SUFFIX) and len(op) > len(REOPEN_SUFFIX)):
            raise LedgerError(f"approval {ref} is for {op}, not a reopen_period approval")
        if ap["subject_type"] not in REOPEN_SUBJECT_TYPES:
            raise LedgerError(f"approval {ref} is scoped to a {ap['subject_type']}, not a period; it is not a reopen_period approval for {period_id}")
        if ap["subject_id"] != period_id:
            raise LedgerError(f"approval {ref} is scoped to period {ap['subject_id']}, not {period_id}")
        if ap["status"] != "consumed":
            raise LedgerError(f"approval {ref} is {ap['status']}; only a consumed (granted and executed) reopen approval can reopen a period")
        missing = [k for k in ("approver", "granted_at", "consumed_at", "consumed_by") if not ap[k]]
        if missing:
            raise LedgerError(
                f"approval {ref} records no {', '.join(missing)}; only a consumed reopen approval that was granted and executed "
                "through the approval workflow can reopen a period"
            )
        used = self.db.one("SELECT period_id, reopened_at FROM period_reopens WHERE approval_id=?", (ref,))
        if used is not None:
            raise LedgerError(f"approval {ref} already reopened period {used['period_id']} at {used['reopened_at']}; each reopen needs a fresh approval")
        return ap

    def reopens(self, period_id: str | None = None) -> list[dict[str, Any]]:
        """The append-only reopen log (one row per reopen, keyed by its approval)."""
        if period_id:
            return self.db.query("SELECT * FROM period_reopens WHERE period_id=? ORDER BY reopened_at, approval_id", (period_id,))
        return self.db.query("SELECT * FROM period_reopens ORDER BY reopened_at, approval_id")

    # ---- posting ----------------------------------------------------------- #

    def post(
        self,
        *,
        period_id: str,
        description: str,
        lines: list[dict[str, Any]],
        source_type: str,
        source_id: str,
        source_version: str,
        posted_by: str,
        rule_version: str = RULE_VERSION,
        approval_id: str | None = None,
        reversal_of: str | None = None,
    ) -> dict[str, Any]:
        """Post one balanced, immutable journal.  Raises instead of posting
        anything if the lines do not balance or the period is not open."""
        if not lines:
            raise UnbalancedJournal("a journal needs at least two lines")
        norm: list[dict[str, Any]] = []
        total_dr = ZERO
        total_cr = ZERO
        for idx, raw in enumerate(lines, start=1):
            if not isinstance(raw, dict):
                raise LedgerError(f"line {idx} must be a mapping with account and debit or credit")
            debit = money(raw.get("debit", "0"))
            credit = money(raw.get("credit", "0"))
            if debit < 0 or credit < 0:
                raise UnbalancedJournal("negative debit or credit; use the opposite side instead")
            if (debit > 0) == (credit > 0):
                raise UnbalancedJournal(f"line {idx} must carry exactly one of debit or credit")
            account = raw.get("account")
            if not isinstance(account, str) or not account:
                raise LedgerError(f"line {idx} has no account")
            if self.db.one("SELECT code FROM accounts WHERE code=?", (account,)) is None:
                raise LedgerError(f"unknown account {account}")
            total_dr += debit
            total_cr += credit
            norm.append({
                "line_no": idx,
                "account_code": account,
                "debit": fmt(debit),
                "credit": fmt(credit),
                "project_id": raw.get("project_id"),
                "party_id": raw.get("party_id"),
                "memo": raw.get("memo", ""),
            })
        if money(total_dr) != money(total_cr):
            raise UnbalancedJournal(f"journal does not balance: debits {fmt(total_dr)} credits {fmt(total_cr)}")
        if money(total_dr) == ZERO:
            raise UnbalancedJournal("journal has no value")
        journal_id = new_id("jrn")
        with self.db.transaction() as conn:
            self.require_open(period_id)
            conn.execute(
                """INSERT INTO journals (id, period_id, posted_at, description, source_type, source_id, source_version, rule_version, approval_id, reversal_of, posted_by, line_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (journal_id, period_id, utcnow_iso(), description, source_type, source_id, str(source_version), rule_version, approval_id, reversal_of, posted_by, len(norm)),
            )
            for ln in norm:
                conn.execute(
                    "INSERT INTO journal_lines (id, journal_id, line_no, account_code, debit, credit, project_id, party_id, memo) VALUES (?,?,?,?,?,?,?,?,?)",
                    (new_id("jln"), journal_id, ln["line_no"], ln["account_code"], ln["debit"], ln["credit"], ln["project_id"], ln["party_id"], ln["memo"]),
                )
            self.audit.record(posted_by, "journal.posted", "journal", journal_id, {
                "period_id": period_id, "source_type": source_type, "source_id": source_id, "source_version": str(source_version),
                "total": fmt(total_dr), "approval_id": approval_id, "reversal_of": reversal_of, "line_count": len(norm),
            })
        return self.journal(journal_id)

    def reverse(self, journal_id: str, *, period_id: str, posted_by: str, reason: str, approval_id: str | None = None,
                request_id: str | None = None) -> dict[str, Any]:
        """Append a reversing journal (debits and credits swapped) in ``period_id``.

        A journal is reversed at most once (also enforced by a unique index).  Any
        pending ``journal.reverse`` request for the journal is resolved in the same
        transaction: ``request_id`` (the governed path) becomes executed, any other
        pending request is canceled as superseded.  A hook registered in
        ``reversal_hooks`` for the journal's source type runs in that transaction too."""
        why = _text(reason, "a reversal reason")
        with self.db.transaction() as conn:
            original = self.journal(journal_id)
            if original["reversed_by"] is not None:
                raise LedgerError(f"journal {journal_id} was already reversed by {original['reversed_by']}; a journal can be reversed once")
            pending = [r["id"] for r in conn.execute(
                "SELECT id FROM journal_reversal_requests WHERE journal_id=? AND status='pending'", (journal_id,)).fetchall()]
            if request_id is not None and request_id not in pending:
                raise LedgerError(f"reversal request {request_id} is not pending for journal {journal_id}")
            lines = [
                {"account": ln["account_code"], "debit": ln["credit"], "credit": ln["debit"], "project_id": ln["project_id"], "party_id": ln["party_id"], "memo": f"reversal: {ln['memo']}"}
                for ln in original["lines"]
            ]
            rev = self.post(
                period_id=period_id,
                description=f"Reversal of {journal_id}: {why}",
                lines=lines,
                source_type=original["source_type"],
                source_id=original["source_id"],
                source_version=original["source_version"],
                posted_by=posted_by,
                rule_version=original["rule_version"],
                approval_id=approval_id,
                reversal_of=journal_id,
            )
            hook = self.reversal_hooks.get(original["source_type"])
            if hook is not None:
                hook(original, rev, posted_by)
            now = utcnow_iso()
            for rid in pending:
                if rid == request_id:
                    conn.execute(
                        "UPDATE journal_reversal_requests SET status='executed', approval_id=?, reversal_journal_id=?, resolved_by=?, resolved_at=?, resolution_note=? WHERE id=?",
                        (approval_id, rev["id"], posted_by, now, f"reversed by {rev['id']} in period {period_id}", rid),
                    )
                else:
                    conn.execute(
                        "UPDATE journal_reversal_requests SET status='cancelled', reversal_journal_id=?, resolved_by=?, resolved_at=?, resolution_note=? WHERE id=?",
                        (rev["id"], posted_by, now, f"superseded: journal reversed by {rev['id']} outside this request", rid),
                    )
            self.audit.record(posted_by, "journal.reversed", "journal", journal_id, {
                "reversal_journal_id": rev["id"], "period_id": period_id, "reason": why, "approval_id": approval_id,
                "request_id": request_id, "superseded_requests": [r for r in pending if r != request_id],
            })
        return rev

    # ---- governed correction: journal.reverse -------------------------------- #

    def handles(self, operation: str) -> bool:
        return operation == OP_REVERSE

    def _require_generic_reversal(self, journal: dict[str, Any]) -> None:
        """Refuse journals that ``journal.reverse`` cannot correct on its own."""
        owner = self.reversal_owners.get(journal["source_type"])
        if owner is not None:
            raise SubledgerOwnedJournal(
                f"journal {journal['id']} was posted for {journal['source_type']} {journal['source_id']}, a document kept by {owner}; "
                "reversing only the journal would leave that document live while its control account moves, so journal.reverse "
                "refuses it: correct it through the owning module"
            )
        if journal["reversal_of"] is not None:
            raise LedgerError(
                f"journal {journal['id']} is itself the reversal of {journal['reversal_of']}; journal.reverse never reverses a reversal "
                "(post the corrected entry through its source instead)"
            )

    def reversal_request(self, request_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM journal_reversal_requests WHERE id=?", (request_id,)) if isinstance(request_id, str) else None
        if row is None:
            raise LedgerError(f"unknown reversal request {request_id}")
        return row

    def reversal_requests(self, journal_id: str | None = None) -> list[dict[str, Any]]:
        if journal_id:
            return self.db.query("SELECT * FROM journal_reversal_requests WHERE journal_id=? ORDER BY rowid", (journal_id,))
        return self.db.query("SELECT * FROM journal_reversal_requests ORDER BY rowid")

    def prepare_reversal(self, journal_id: str, reason: str, actor: str) -> dict[str, Any]:
        """Record why a posted journal should be reversed.  The pending request is
        what a ``journal.reverse`` approval binds; one pending request per journal,
        and none for a journal that is already reversed."""
        why = _text(reason, "a reversal reason", max_length=MAX_REASON_LENGTH)
        who = _text(actor, "actor")
        request_id = new_id("jrr")
        with self.db.transaction() as conn:
            journal = self.journal(journal_id)
            if journal["reversed_by"] is not None:
                raise LedgerError(f"journal {journal_id} was already reversed by {journal['reversed_by']}; a journal can be reversed once")
            self._require_generic_reversal(journal)
            pending = conn.execute("SELECT id FROM journal_reversal_requests WHERE journal_id=? AND status='pending'", (journal_id,)).fetchone()
            if pending is not None:
                raise LedgerError(f"journal {journal_id} already has pending reversal request {pending['id']}; cancel it before preparing another")
            conn.execute(
                "INSERT INTO journal_reversal_requests (id, journal_id, reason, status, requested_by, requested_at) VALUES (?,?,?,'pending',?,?)",
                (request_id, journal_id, why, who, utcnow_iso()),
            )
            self.audit.record(who, "journal.reversal_requested", "journal", journal_id, {"request_id": request_id, "reason": why})
        return self.reversal_request(request_id)

    def cancel_reversal_request(self, request_id: str, *, actor: str, reason: str) -> dict[str, Any]:
        """Withdraw a pending reversal request; an approval that bound it goes stale."""
        why = _text(reason, "a cancellation reason", max_length=MAX_REASON_LENGTH)
        who = _text(actor, "actor")
        with self.db.transaction() as conn:
            req = self.reversal_request(request_id)
            if req["status"] != "pending":
                raise LedgerError(f"reversal request {request_id} is {req['status']}; only a pending request can be canceled")
            conn.execute(
                "UPDATE journal_reversal_requests SET status='cancelled', resolved_by=?, resolved_at=?, resolution_note=? WHERE id=?",
                (who, utcnow_iso(), why, request_id),
            )
            self.audit.record(who, "journal.reversal_request_cancelled", "journal", req["journal_id"], {"request_id": request_id, "reason": why})
        return self.reversal_request(request_id)

    def _latest_reversal_request(self, journal_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM journal_reversal_requests WHERE journal_id=? ORDER BY rowid DESC LIMIT 1", (journal_id,))

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation != OP_REVERSE:
            raise LedgerError(f"unknown ledger operation {operation}")
        journal = self.journal(subject_id)
        self._require_generic_reversal(journal)
        if journal["reversed_by"] is not None:
            raise ReversalNotAvailable(
                f"journal {journal['id']} was already reversed by {journal['reversed_by']}; a journal can be reversed once, so no journal.reverse approval applies to it"
            )
        request = self._latest_reversal_request(journal["id"])
        if request is None:
            raise LedgerError(
                f"journal {journal['id']} has no reversal request; call prepare_reversal(journal_id, reason, actor) first so the reason is bound into the approval"
            )
        if request["status"] != "pending":
            raise ReversalNotAvailable(
                f"the latest reversal request for journal {journal['id']} ({request['id']}) is {us(request['status'])}; "
                "prepare a new reversal request before requesting or executing a journal.reverse approval"
            )
        total_dr = money(sum((money(ln["debit"]) for ln in journal["lines"]), ZERO))
        total_cr = money(sum((money(ln["credit"]) for ln in journal["lines"]), ZERO))
        period = self.period(journal["period_id"])
        project_ids = sorted({ln["project_id"] for ln in journal["lines"] if ln["project_id"]})
        projects = [self.db.one("SELECT id, entity, currency FROM projects WHERE id=?", (pid,)) for pid in project_ids]
        entities = sorted({p["entity"] for p in projects if p})
        currencies = sorted({p["currency"] for p in projects if p})
        return build_manifest(
            operation=OP_REVERSE, subject_type=REVERSAL_SUBJECT, subject_id=journal["id"], actor_role=actor_role,
            amounts={"total_debit": total_dr, "total_credit": total_cr},
            bindings={
                "journal_id": journal["id"],
                "period_id": journal["period_id"],
                "period_start": period["start_date"],
                "posted_at": journal["posted_at"],
                "description": journal["description"],
                "source": {"type": journal["source_type"], "id": journal["source_id"], "version": journal["source_version"]},
                "rule_version": journal["rule_version"],
                "original_approval_id": journal["approval_id"],
                "reversal_of": journal["reversal_of"],
                "line_count": len(journal["lines"]),
                "lines_fingerprint": lines_fingerprint(journal["lines"]),
                "already_reversed": journal["reversed_by"] is not None,
                "reversed_by": journal["reversed_by"],
                "reversal_request": {
                    "id": request["id"], "status": request["status"], "requested_by": request["requested_by"], "requested_at": request["requested_at"],
                },
                "reason": request["reason"],
                "projects": project_ids,
                "entities": entities,
                "target_rule": f"execute with period_id of an open period starting on or after {period['start_date']}",
            },
            entity=entities[0] if len(entities) == 1 else None,
            currency=currencies[0] if len(currencies) == 1 else "USD",
        )

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation != OP_REVERSE:
            raise LedgerError(f"unknown ledger operation {operation}")
        if not period_id:
            raise LedgerError("journal.reverse needs period_id: the open period that receives the reversal")
        bindings = manifest.get("bindings") or {}
        request_binding = bindings.get("reversal_request") or {}
        reason = bindings.get("reason")
        with self.db.transaction():
            request = self.reversal_request(request_binding.get("id"))
            if request["journal_id"] != subject_id:
                raise LedgerError(f"reversal request {request['id']} is for journal {request['journal_id']}, not {subject_id}")
            if request["status"] != "pending":
                raise LedgerError(f"reversal request {request['id']} is {us(request['status'])}; prepare a new reversal request and approval")
            if reason != request["reason"]:
                raise LedgerError(f"the approved reason no longer matches reversal request {request['id']}")
            original = self.journal(subject_id)
            if original["reversed_by"] is not None:
                raise LedgerError(f"journal {subject_id} was already reversed by {original['reversed_by']}; a journal can be reversed once")
            self._require_generic_reversal(original)
            target = self.require_open(period_id)
            source_period = self.period(original["period_id"])
            if target["start_date"] < source_period["start_date"]:
                raise LedgerError(
                    f"a reversal cannot be dated before the journal it reverses: period {period_id} starts {target['start_date']}, "
                    f"journal {subject_id} is in {source_period['id']} starting {source_period['start_date']}"
                )
            rev = self.reverse(subject_id, period_id=period_id, posted_by=actor, reason=reason, approval_id=approval_id, request_id=request["id"])
        return {
            "journal_id": subject_id, "reversal_journal_id": rev["id"], "period_id": period_id, "status": "reversed",
            "reason": reason, "request_id": request["id"], "total": manifest.get("amounts", {}).get("total_debit"),
        }

    # ---- reading ----------------------------------------------------------- #

    def journal(self, journal_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM journals WHERE id = ?", (journal_id,))
        if row is None:
            raise LedgerError(f"unknown journal {journal_id}")
        row["lines"] = self.db.query("SELECT * FROM journal_lines WHERE journal_id = ? ORDER BY line_no", (journal_id,))
        rev = self.db.one("SELECT id FROM journals WHERE reversal_of = ?", (journal_id,))
        row["reversed_by"] = rev["id"] if rev else None
        return row

    def journals(self, *, period_id: str | None = None, source_type: str | None = None, source_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM journals"
        clauses, params = [], []
        if period_id:
            clauses.append("period_id = ?")
            params.append(period_id)
        if source_type:
            clauses.append("source_type = ?")
            params.append(source_type)
        if source_id:
            clauses.append("source_id = ?")
            params.append(source_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY posted_at, id"
        rows = self.db.query(sql, tuple(params))
        for r in rows:
            r["lines"] = self.db.query("SELECT * FROM journal_lines WHERE journal_id = ? ORDER BY line_no", (r["id"],))
        return rows

    def account_activity(self, account_code: str, *, period_id: str | None = None, project_id: str | None = None, party_id: str | None = None) -> dict[str, Any]:
        sql = "SELECT l.debit, l.credit FROM journal_lines l JOIN journals j ON j.id = l.journal_id WHERE l.account_code = ?"
        params: list[Any] = [account_code]
        if period_id:
            sql += " AND j.period_id = ?"
            params.append(period_id)
        if project_id:
            sql += " AND l.project_id = ?"
            params.append(project_id)
        if party_id:
            sql += " AND l.party_id = ?"
            params.append(party_id)
        dr = ZERO
        cr = ZERO
        for row in self.db.query(sql, tuple(params)):
            dr += money(row["debit"])
            cr += money(row["credit"])
        return {"debit": money(dr), "credit": money(cr)}

    def balance(self, account_code: str, **filters) -> Decimal:
        """Natural balance: debit-positive for assets/expenses, credit-positive otherwise."""
        acct = self.db.one("SELECT type FROM accounts WHERE code=?", (account_code,))
        if acct is None:
            raise LedgerError(f"unknown account {account_code}")
        act = self.account_activity(account_code, **filters)
        if acct["type"] in DEBIT_NORMAL:
            return money(act["debit"] - act["credit"])
        return money(act["credit"] - act["debit"])

    def control_balance(self, control_kind: str, **filters) -> Decimal:
        return self.balance(self.account_for_control(control_kind), **filters)

    def trial_balance(self, period_id: str | None = None) -> dict[str, Any]:
        rows = []
        total_dr = ZERO
        total_cr = ZERO
        for acct in self.accounts():
            act = self.account_activity(acct["code"], period_id=period_id)
            if act["debit"] == ZERO and act["credit"] == ZERO:
                continue
            net = act["debit"] - act["credit"]
            rows.append({
                "code": acct["code"], "name": acct["name"], "type": acct["type"],
                "debit": fmt(act["debit"]), "credit": fmt(act["credit"]),
                "balance": fmt(net if acct["type"] in DEBIT_NORMAL else -net),
            })
            total_dr += act["debit"]
            total_cr += act["credit"]
        count_sql = "SELECT COUNT(*) FROM journals" + (" WHERE period_id = ?" if period_id else "")
        count = self.db.scalar(count_sql, (period_id,) if period_id else ())
        return {
            "period_id": period_id,
            "rows": rows,
            "total_debit": fmt(total_dr),
            "total_credit": fmt(total_cr),
            "balanced": money(total_dr) == money(total_cr),
            "journal_count": count,
        }

    def income_statement(self, period_id: str | None = None) -> dict[str, Any]:
        revenue = ZERO
        expense = ZERO
        for acct in self.accounts():
            if acct["type"] == "revenue":
                revenue += self.balance(acct["code"], period_id=period_id)
            elif acct["type"] == "expense":
                expense += self.balance(acct["code"], period_id=period_id)
        return {"period_id": period_id, "revenue": fmt(revenue), "expense": fmt(expense), "net": fmt(revenue - expense), "label": "SHADOW - not authoritative"}
