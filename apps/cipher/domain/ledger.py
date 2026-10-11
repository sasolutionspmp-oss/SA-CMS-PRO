"""Double-entry general ledger: chart, periods, immutable journals, reversals, trial balance.

Invariants (from the plan, section 6):

1. exact decimal amounts;
2. every journal balances and carries source id/version, posting-rule version and approval;
3. posted entries are never updated or deleted (SQLite triggers enforce it); corrections append reversals;
4. period locks apply to every posting path (trigger on insert);
5. control balances reconcile to subledgers (checked by the subledger modules);
10. statements drill down to journals and sources.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..core.audit import Audit
from ..core.db import Database
from ..core.ids import new_id, utcnow_iso
from ..core.money import ZERO, fmt, money

RULE_VERSION = "cipher-posting-rules/1"

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


class Ledger:
    def __init__(self, db: Database, audit: Audit):
        self.db = db
        self.audit = audit

    # ---- chart and periods ------------------------------------------------ #

    def ensure_chart(self) -> None:
        with self.db.transaction() as conn:
            for code, name, typ, control in CHART:
                conn.execute("INSERT OR IGNORE INTO accounts (code, name, type, control_kind) VALUES (?,?,?,?)", (code, name, typ, control))

    def accounts(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM accounts ORDER BY code")

    def account_for_control(self, control_kind: str) -> str:
        row = self.db.one("SELECT code FROM accounts WHERE control_kind = ?", (control_kind,))
        if row is None:
            raise LedgerError(f"no control account for {control_kind}")
        return row["code"]

    def open_period(self, period_id: str, name: str, start_date: str, end_date: str, *, actor: str = "system") -> dict[str, Any]:
        with self.db.transaction() as conn:
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
        """Reopening requires a scoped controller approval reference."""
        if not approval_ref:
            raise LedgerError("reopening a period requires a controller approval reference")
        with self.db.transaction() as conn:
            p = self.period(period_id)
            if p["status"] == "locked":
                raise PeriodNotOpen(f"period {period_id} is locked and cannot be reopened")
            if p["status"] != "closed":
                raise LedgerError(f"period {period_id} is not closed")
            conn.execute("UPDATE periods SET status='open', closed_at=NULL, closed_by=NULL WHERE id=?", (period_id,))
            self.audit.record(actor, "period.reopened", "period", period_id, {"approval_ref": approval_ref})
        return self.period(period_id)

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
            debit = money(raw.get("debit", "0"))
            credit = money(raw.get("credit", "0"))
            if debit < 0 or credit < 0:
                raise UnbalancedJournal("negative debit or credit; use the opposite side instead")
            if (debit > 0) == (credit > 0):
                raise UnbalancedJournal(f"line {idx} must carry exactly one of debit or credit")
            account = raw["account"]
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
                """INSERT INTO journals (id, period_id, posted_at, description, source_type, source_id, source_version, rule_version, approval_id, reversal_of, posted_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (journal_id, period_id, utcnow_iso(), description, source_type, source_id, str(source_version), rule_version, approval_id, reversal_of, posted_by),
            )
            for ln in norm:
                conn.execute(
                    "INSERT INTO journal_lines (id, journal_id, line_no, account_code, debit, credit, project_id, party_id, memo) VALUES (?,?,?,?,?,?,?,?,?)",
                    (new_id("jln"), journal_id, ln["line_no"], ln["account_code"], ln["debit"], ln["credit"], ln["project_id"], ln["party_id"], ln["memo"]),
                )
            self.audit.record(posted_by, "journal.posted", "journal", journal_id, {
                "period_id": period_id, "source_type": source_type, "source_id": source_id, "source_version": str(source_version),
                "total": fmt(total_dr), "approval_id": approval_id, "reversal_of": reversal_of,
            })
        return self.journal(journal_id)

    def reverse(self, journal_id: str, *, period_id: str, posted_by: str, reason: str, approval_id: str | None = None) -> dict[str, Any]:
        """Append a reversing journal (debits and credits swapped) in ``period_id``."""
        original = self.journal(journal_id)
        if self.db.one("SELECT id FROM journals WHERE reversal_of = ?", (journal_id,)) is not None:
            raise LedgerError(f"journal {journal_id} was already reversed")
        lines = [
            {"account": ln["account_code"], "debit": ln["credit"], "credit": ln["debit"], "project_id": ln["project_id"], "party_id": ln["party_id"], "memo": f"reversal: {ln['memo']}"}
            for ln in original["lines"]
        ]
        return self.post(
            period_id=period_id,
            description=f"Reversal of {journal_id}: {reason}",
            lines=lines,
            source_type=original["source_type"],
            source_id=original["source_id"],
            source_version=original["source_version"],
            posted_by=posted_by,
            rule_version=original["rule_version"],
            approval_id=approval_id,
            reversal_of=journal_id,
        )

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
