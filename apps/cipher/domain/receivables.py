"""Prime-contract progress billing, collections and late returns.

The fixture policy recognises revenue when the owner certifies progress and
bills it; the plan is explicit that billing is *not* universally the revenue
trigger, so every statement produced here is labelled SHADOW.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..core.approvals import build_manifest
from ..core.audit import Audit
from ..core.db import Database
from ..core.ids import hash_json, new_id, utcnow_iso
from ..core.money import ZERO, fmt, money, pct, rate, total
from .ledger import Ledger


class ReceivableError(RuntimeError):
    pass


class Receivables:
    def __init__(self, db: Database, audit: Audit, ledger: Ledger):
        self.db = db
        self.audit = audit
        self.ledger = ledger

    def latest(self, project_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM prime_bills WHERE project_id=? AND status != 'void' ORDER BY sequence DESC LIMIT 1", (project_id,))
        return self.get(row["id"]) if row else None

    def certify(self, *, project_id: str, period_id: str, certified_cumulative: str | Decimal, retainage_rate: str | Decimal = "0.10", actor: str) -> dict[str, Any]:
        project = self.db.one("SELECT * FROM projects WHERE id=?", (project_id,))
        if project is None:
            raise ReceivableError(f"unknown project {project_id}")
        if not project["customer_id"]:
            raise ReceivableError("project has no customer party")
        self.ledger.require_open(period_id)
        prior = self.latest(project_id)
        if prior and prior["status"] == "draft":
            raise ReceivableError("the previous prime bill is still a draft")
        certified = money(certified_cumulative)
        prior_certified = money(prior["certified_cumulative"]) if prior else ZERO
        if certified < prior_certified:
            raise ReceivableError("certified cumulative cannot decrease")
        r = rate(retainage_rate)
        ret_cum = pct(certified, r)
        prior_net = money(prior["certified_cumulative"]) - money(prior["retainage_cumulative"]) if prior else ZERO
        amount_due = (certified - ret_cum) - prior_net
        revenue = certified - prior_certified
        retainage_this = ret_cum - (money(prior["retainage_cumulative"]) if prior else ZERO)
        sequence = (prior["sequence"] + 1) if prior else 1
        content_hash = hash_json({"project_id": project_id, "period_id": period_id, "sequence": sequence, "certified": fmt(certified), "rate": f"{r:f}", "amount_due": fmt(amount_due)})
        pid = new_id("pbl")
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO prime_bills (id, project_id, customer_id, period_id, sequence, status, certified_cumulative, retainage_rate, retainage_cumulative, prior_net, amount_due, revenue_this_period, content_hash, created_at)
                   VALUES (?,?,?,?,?,'draft',?,?,?,?,?,?,?,?)""",
                (pid, project_id, project["customer_id"], period_id, sequence, fmt(certified), f"{r:f}", fmt(ret_cum), fmt(prior_net), fmt(amount_due), fmt(revenue), content_hash, utcnow_iso()),
            )
            self.audit.record(actor, "prime_bill.certified", "prime_bill", pid, {"project_id": project_id, "sequence": sequence, "certified": fmt(certified), "amount_due": fmt(amount_due), "retainage_this_period": fmt(retainage_this)})
        return self.get(pid)

    def get(self, prime_bill_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM prime_bills WHERE id=?", (prime_bill_id,))
        if row is None:
            raise ReceivableError(f"unknown prime bill {prime_bill_id}")
        prior = self.db.one("SELECT retainage_cumulative FROM prime_bills WHERE project_id=? AND sequence < ? AND status != 'void' ORDER BY sequence DESC LIMIT 1", (row["project_id"], row["sequence"]))
        row["retainage_this_period"] = fmt(money(row["retainage_cumulative"]) - (money(prior["retainage_cumulative"]) if prior else ZERO))
        row["collections"] = self.db.query("SELECT * FROM collections WHERE prime_bill_id=? ORDER BY received_at", (prime_bill_id,))
        return row

    def list(self, project_id: str) -> list[dict[str, Any]]:
        return [self.get(r["id"]) for r in self.db.query("SELECT id FROM prime_bills WHERE project_id=? ORDER BY sequence", (project_id,))]

    def manifest(self, prime_bill_id: str, *, actor_role: str) -> dict[str, Any]:
        b = self.get(prime_bill_id)
        return build_manifest(
            operation="prime_bill.approve",
            subject_type="prime_bill",
            subject_id=prime_bill_id,
            actor_role=actor_role,
            amounts={"amount_due": b["amount_due"], "revenue_this_period": b["revenue_this_period"], "retainage_this_period": b["retainage_this_period"]},
            bindings={"project_id": b["project_id"], "customer_id": b["customer_id"], "period_id": b["period_id"], "sequence": b["sequence"], "bill_hash": b["content_hash"], "recognition_policy": "fixture: certified progress billed = earned (SHADOW)"},
        )

    def post(self, prime_bill_id: str, *, approval_id: str, actor: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            b = self.get(prime_bill_id)
            if b["status"] != "draft":
                raise ReceivableError(f"prime bill {prime_bill_id} is {b['status']}")
            lines = []
            if money(b["amount_due"]) > 0:
                lines.append({"account": "1100", "debit": b["amount_due"], "project_id": b["project_id"], "party_id": b["customer_id"], "memo": f"prime bill {b['sequence']}"})
            if money(b["retainage_this_period"]) > 0:
                lines.append({"account": "1150", "debit": b["retainage_this_period"], "project_id": b["project_id"], "party_id": b["customer_id"], "memo": "retainage receivable"})
            lines.append({"account": "4000", "credit": b["revenue_this_period"], "project_id": b["project_id"], "party_id": b["customer_id"], "memo": "certified progress (fixture policy)"})
            j = self.ledger.post(
                period_id=b["period_id"], description=f"Prime bill {b['sequence']}", lines=lines,
                source_type="prime_bill", source_id=prime_bill_id, source_version="1", posted_by=actor, approval_id=approval_id,
            )
            conn.execute("UPDATE prime_bills SET status='posted', approval_id=?, journal_id=? WHERE id=?", (approval_id, j["id"], prime_bill_id))
            self.audit.record(actor, "prime_bill.posted", "prime_bill", prime_bill_id, {"approval_id": approval_id, "journal_id": j["id"]})
        return self.get(prime_bill_id)

    def send(self, prime_bill_id: str, *, actor: str) -> dict[str, Any]:
        """Deliver to the synthetic mail sink; nothing leaves the prototype."""
        with self.db.transaction() as conn:
            b = self.get(prime_bill_id)
            if b["status"] != "posted":
                raise ReceivableError("only posted prime bills can be sent")
            conn.execute("UPDATE prime_bills SET status='sent' WHERE id=?", (prime_bill_id,))
            self.audit.record(actor, "prime_bill.sent", "prime_bill", prime_bill_id, {"channel": "mail-sink", "customer_id": b["customer_id"]})
        return self.get(prime_bill_id)

    def record_collection(self, *, prime_bill_id: str, period_id: str, amount: str | Decimal, fee: str | Decimal, provider_ref: str, actor: str) -> dict[str, Any]:
        amt = money(amount)
        f = money(fee)
        if amt <= 0 or f < 0 or f > amt:
            raise ReceivableError("invalid collection amount or fee")
        if self.db.one("SELECT id FROM collections WHERE provider_ref=?", (provider_ref,)):
            raise ReceivableError(f"collection {provider_ref} was already recorded")
        with self.db.transaction() as conn:
            b = self.get(prime_bill_id)
            if b["status"] not in ("posted", "sent"):
                raise ReceivableError(f"prime bill {prime_bill_id} is {b['status']}")
            open_amt = money(b["amount_due"]) - total(c["amount"] for c in b["collections"] if c["status"] == "received")
            if amt > open_amt:
                raise ReceivableError(f"collection {fmt(amt)} exceeds open receivable {fmt(open_amt)}")
            lines = [
                {"account": "1000", "debit": amt - f, "project_id": b["project_id"], "party_id": b["customer_id"], "memo": "ACH receipt (simulated)"},
                {"account": "1100", "credit": amt, "project_id": b["project_id"], "party_id": b["customer_id"], "memo": f"prime bill {b['sequence']} collected"},
            ]
            if f > 0:
                lines.insert(1, {"account": "6000", "debit": f, "project_id": b["project_id"], "party_id": b["customer_id"], "memo": "processing fee"})
            j = self.ledger.post(period_id=period_id, description=f"Collection on prime bill {b['sequence']}", lines=lines, source_type="collection", source_id=provider_ref, source_version="1", posted_by=actor)
            cid = new_id("col")
            conn.execute(
                "INSERT INTO collections (id, prime_bill_id, amount, fee, status, journal_id, provider_ref, received_at) VALUES (?,?,?,?,'received',?,?,?)",
                (cid, prime_bill_id, fmt(amt), fmt(f), j["id"], provider_ref, utcnow_iso()),
            )
            if amt == open_amt:
                conn.execute("UPDATE prime_bills SET status='collected' WHERE id=?", (prime_bill_id,))
            self.audit.record(actor, "collection.recorded", "collection", cid, {"prime_bill_id": prime_bill_id, "amount": fmt(amt), "fee": fmt(f), "journal_id": j["id"]})
        return self.db.one("SELECT * FROM collections WHERE id=?", (cid,))

    def record_return(self, *, collection_id: str, period_id: str, reason: str, actor: str) -> dict[str, Any]:
        """A late return (after the original period closed) is posted in the
        current open period as a linked correction; the original receipt stays."""
        with self.db.transaction() as conn:
            col = self.db.one("SELECT * FROM collections WHERE id=?", (collection_id,))
            if col is None:
                raise ReceivableError(f"unknown collection {collection_id}")
            if col["status"] == "returned":
                raise ReceivableError("collection was already returned")
            b = self.get(col["prime_bill_id"])
            amt = money(col["amount"])
            j = self.ledger.post(
                period_id=period_id,
                description=f"Returned collection {col['provider_ref']}: {reason}",
                lines=[
                    {"account": "1100", "debit": amt, "project_id": b["project_id"], "party_id": b["customer_id"], "memo": "receivable restored"},
                    {"account": "1000", "credit": amt, "project_id": b["project_id"], "party_id": b["customer_id"], "memo": "bank return"},
                ],
                source_type="collection_return", source_id=col["provider_ref"], source_version="1", posted_by=actor,
            )
            conn.execute("UPDATE collections SET status='returned', return_journal_id=?, returned_at=? WHERE id=?", (j["id"], utcnow_iso(), collection_id))
            conn.execute("UPDATE prime_bills SET status='sent' WHERE id=? AND status='collected'", (col["prime_bill_id"],))
            self.audit.record(actor, "collection.returned", "collection", collection_id, {"reason": reason, "journal_id": j["id"], "original_journal_id": col["journal_id"]})
        return self.db.one("SELECT * FROM collections WHERE id=?", (collection_id,))

    def ar_open_items(self, project_id: str | None = None) -> dict[str, Any]:
        sql = "SELECT * FROM prime_bills WHERE status IN ('posted','sent','collected')"
        params: tuple = ()
        if project_id:
            sql += " AND project_id=?"
            params = (project_id,)
        items = []
        open_total = ZERO
        for b in self.db.query(sql, params):
            received = self.db.query("SELECT amount FROM collections WHERE prime_bill_id=? AND status='received'", (b["id"],))
            rec_total = total(c["amount"] for c in received) if received else ZERO
            open_amt = money(b["amount_due"]) - rec_total
            items.append({"prime_bill_id": b["id"], "sequence": b["sequence"], "amount_due": b["amount_due"], "received": fmt(rec_total), "open": fmt(open_amt)})
            open_total += open_amt
        control = self.ledger.control_balance("ar", project_id=project_id) if project_id else self.ledger.control_balance("ar")
        return {"items": items, "subledger_total": fmt(open_total), "control_balance": fmt(control), "reconciled": money(open_total) == control}
