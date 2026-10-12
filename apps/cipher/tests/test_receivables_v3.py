"""Receivables v3: document dates and customer payment terms, settlement dates, credit
memos, write-offs past 90 days, customer deposits and their application, the database
guards behind them, the 2400 reconciliation, the close checklist and the upgrade of an
earlier workspace.  Synthetic data only (cofferdam, sheet piling and dewatering scope)."""
import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal as D
from unittest import mock

from apps.cipher.core import db as core_db
from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.ids import utcnow_iso
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.domain.receivables import (
    CONTROLS_GUARDS_SCHEMA_NAME, CONTROLS_SCHEMA_NAME, DATES_CREDITS_GUARDS_SCHEMA_NAME, DATES_CREDITS_SCHEMA_NAME, ReceivableCutoffError,
    ReceivableDuplicate, ReceivableError, ReceivableIneligible, ReceivableInputError,
)
from apps.cipher.service import Cipher, RoleNotAuthorised
import apps.cipher.ricky_sdk  # noqa: F401  (registers its schema entry before any test patches the catalog)

ENTITY = "S&A Solutions LLC (synthetic)"
KEEP_PLUGINS = ("close", "reimbursement", "core_reconciliation")
RAW_DRAFT_BILL = (
    "INSERT INTO prime_bills (id, project_id, customer_id, period_id, sequence, status, certified_cumulative, retainage_rate, retainage_cumulative, "
    "prior_net, amount_due, revenue_this_period, content_hash, created_at, invoice_date, due_date) "
    "VALUES (?, ?, ?, 'P1', 99, 'draft', '1000.00', '0.100000', '100.00', '0.00', '900.00', '1000.00', 'h', '2026-10-12T00:00:00Z', ?, ?)")
RAW_COLLECTION = (
    "INSERT INTO collections (id, prime_bill_id, amount, fee, status, journal_id, provider_ref, received_at, method, mandate_id, settlement_date) "
    "VALUES (?, ?, ?, '0.00', 'received', ?, ?, '2026-10-20T00:00:00Z', 'check', NULL, ?)")
RAW_MEMO = (
    "INSERT INTO prime_bill_credit_memos (id, prime_bill_id, project_id, customer_id, amount, reason, evidence_hash, evidence_revision_id, bill_hash, "
    "status, created_at, created_by) VALUES (?, ?, ?, ?, ?, 'raw', ?, ?, ?, ?, '2026-10-12T00:00:00Z', 'raw')")
RAW_WRITE_OFF = (  # the last parameter is the record time (created_at)
    "INSERT INTO receivable_write_offs (id, prime_bill_id, project_id, customer_id, amount, reason, requested_on, due_date, days_past_due, bill_hash, "
    "status, created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, 'raw')")
RAW_JOURNAL_REQUESTS = "SELECT COUNT(*) AS n FROM journal_reversal_requests WHERE journal_id=?"
PAST_START, PAST_END = "2025-01-01", "2026-09-30"  # period P0, opened on demand for bills dated well before P1
RAW_DEPOSIT = (
    "INSERT INTO customer_deposits (id, customer_id, project_id, amount, method, mandate_id, provider_ref, settlement_date, period_id, journal_id, "
    "received_at, recorded_by) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, '2026-10-12T00:00:00Z', 'raw')")
RAW_APPLICATION = (
    "INSERT INTO deposit_applications (id, deposit_id, prime_bill_id, project_id, customer_id, amount, bill_hash, status, created_at, created_by) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', '2026-10-12T00:00:00Z', 'raw')")


def lines_of(journal):
    return [(ln["account_code"], ln["debit"], ln["credit"]) for ln in journal["lines"]]


def preview_of(manifest):
    return [(p["account"], p["debit"], p["credit"]) for p in manifest["bindings"]["journal_preview"]]


class World:
    """One synthetic customer and project with two open periods (P1 October, P2 November
    2026), and P0 (2025-01-01 to 2026-09-30) on demand (``past()``) for bills dated well
    before October: an explicit invoice date is never before its bill's period.  Document
    dates are relative to the receivables clock (``day(offset)``), which is pinned to the
    day the World is built, so a run that spans midnight UTC dates every record alike."""

    def __init__(self, *, path=":memory:", isolate=False):
        c = self.c = Cipher(path)
        if isolate:  # only the modules whose close checks the scenario controls
            for name in list(c._plugins):
                if name not in KEEP_PLUGINS:
                    del c._plugins[name]
        self.r = c.receivables
        today = self.today = self.r.today()
        self.r.today = lambda: today
        self.customer = c.add_party(kind="customer", name="Synthetic Owner Agency (AR v3)")
        self.cust = self.customer["id"]
        self.project = c.create_project(name="Synthetic cofferdam, sheet piling and dewatering (AR v3)", entity=ENTITY, budget="250000", customer_id=self.cust)
        self.pid = self.project["id"]
        c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        self._docs = 0

    def day(self, offset):
        return (self.today + dt.timedelta(days=offset)).isoformat()

    def past(self):
        """Open P0 (once) and return its id: the period for bills dated before P1 starts."""
        if self.c.db.one("SELECT id FROM periods WHERE id='P0'") is None:
            self.c.open_period("P0", "P0", PAST_START, PAST_END)
        return "P0"

    def requests(self, journal_id):
        return self.c.db.one(RAW_JOURNAL_REQUESTS, (journal_id,))["n"]

    def evidence(self, content, project_id=None):
        self._docs += 1
        doc = self.c.evidence.register_document(project_id=project_id or self.pid, kind="receivable_evidence", title=f"Synthetic AR evidence {self._docs}", actor="owner")
        return self.c.evidence.add_revision(document_id=doc["id"], content=content, note="synthetic", actor="owner")["content_hash"]

    def mandate(self, ref="MANDATE-SIM-V3-0001"):
        return self.r.record_mandate(self.cust, ref, self.evidence(f"synthetic ACH authorization {ref}".encode()), "owner")

    def certify(self, certified, period="P1", project_id=None, **kw):
        return self.r.certify(project_id=project_id or self.pid, period_id=period, certified_cumulative=certified, actor="pm", **kw)

    def posted(self, certified, period="P1", project_id=None, **kw):
        b = self.certify(certified, period, project_id, **kw)
        self.c.approve_and_execute("prime_bill.approve", b["id"], actor_role="accountant", actor="accountant")
        return self.r.get(b["id"])

    def collect(self, bill, amount, ref, period="P1", **kw):
        return self.r.record_collection(prime_bill_id=bill["id"], period_id=period, amount=amount, provider_ref=ref, actor="treasury", method="check", **kw)

    def request(self, operation, subject_id, role):
        return self.c.request_approval(operation, subject_id, actor_role=role, requested_by=role)

    def grant(self, ap, role="controller"):
        return self.c.approve(ap["id"], approver=role, approver_role=role)

    def run(self, operation, subject_id, role, period="P1"):
        ap = self.request(operation, subject_id, role)
        self.grant(ap, role)
        return self.c.execute(ap["id"], actor=role, period_id=period)

    def reverse(self, journal_id, period="P1", reason="synthetic correction: recorded against the wrong pay item"):
        self.c.ledger.prepare_reversal(journal_id, reason, "controller")
        return self.c.approve_and_execute("journal.reverse", journal_id, actor_role="controller", actor="controller", period_id=period).result

    def receipt_journal(self, ref, amount, period="P1"):
        tags = {"project_id": self.pid, "party_id": self.cust}
        return self.c.ledger.post(period_id=period, description=f"raw receipt {ref} (synthetic)", source_type="collection", source_id=ref, source_version="1",
                                  posted_by="test", lines=[{"account": "1000", "debit": amount, **tags}, {"account": "1100", "credit": amount, **tags}])

    def bal(self, code, **kw):
        return self.c.ledger.balance(code, **kw)

    def assert_books(self, tc):
        tc.assertTrue(self.c.ledger.trial_balance()["balanced"])
        tc.assertTrue(self.c.audit.verify_chain()["ok"])
        for label, rec in (("AR 1100", self.r.ar_open_items()), ("retainage 1150", self.r.retainage_receivable_items()), ("deposits 2400", self.r.deposits_items())):
            tc.assertTrue(rec["reconciled"], (label, rec))


# --------------------------------------------------------------------------- #
# Dates and payment terms                                                     #
# --------------------------------------------------------------------------- #

class DateTests(unittest.TestCase):
    def test_prime_bill_is_dated_when_it_posts_and_due_on_the_customer_terms(self):
        w = World()
        self.assertEqual(w.r.payment_terms(w.cust), {"customer_id": w.cust, "version": 0, "days": 30, "source": "default"})
        for bad in (-1, 366, 4.5, "abc", True, None, "-3", ""):
            with self.assertRaises(ReceivableInputError, msg=repr(bad)):
                w.r.set_customer_terms(w.cust, bad, "accountant")
        with self.assertRaises(ReceivableInputError):
            w.r.set_customer_terms(w.cust, 45, " ")
        supplier = w.c.add_party(kind="supplier", name="Synthetic sheet pile supplier")
        for party in (supplier["id"], "pty_missing"):
            with self.assertRaises(ReceivableError, msg=party):
                w.r.set_customer_terms(party, 45, "accountant")
        terms = w.r.set_customer_terms(w.cust, "45", "accountant")
        self.assertEqual((terms["version"], terms["days"], terms["source"]), (1, 45, "recorded"))
        with self.assertRaises(ReceivableDuplicate):  # the same terms again change nothing
            w.r.set_customer_terms(w.cust, 45, "accountant")

        b = w.certify("60000")
        self.assertEqual((b["invoice_date"], b["due_date"], b["payment_terms_days"]), (None, None, None))
        ap = w.request("prime_bill.approve", b["id"], "accountant")
        bd = ap["manifest"]["bindings"]
        self.assertEqual((bd["invoice_date"], bd["invoice_date_basis"], bd["payment_terms_days"], bd["payment_terms_version"]), (None, "date of posting", 45, 1))
        w.grant(ap)
        w.c.execute(ap["id"], actor="accountant")
        b = w.r.get(b["id"])
        self.assertEqual((b["invoice_date"], b["due_date"], b["payment_terms_days"]), (w.day(0), w.day(45), 45))
        item = w.r.ar_open_items(w.pid)["items"][0]
        self.assertEqual((item["invoice_date"], item["due_date"], item["days_past_due"], item["date"]), (w.day(0), w.day(45), 0, b["created_at"][:10]))
        later = w.r.ar_open_items(w.pid, as_of=w.day(55))
        self.assertEqual((later["as_of"], later["items"][0]["days_past_due"]), (w.day(55), 10))
        self.assertEqual(w.r.ar_open_items(as_of=dt.date.fromisoformat(w.day(46)))["items"][0]["days_past_due"], 1)
        for bad in ("2026-13-01", "next week", 20261012, "2026-10-12T00:00:00Z"):
            with self.assertRaises(ReceivableInputError, msg=repr(bad)):
                w.r.ar_open_items(as_of=bad)

        # later terms leave the posted bill's due date alone
        w.r.set_customer_terms(w.cust, 15, "accountant")
        self.assertEqual(w.r.get(b["id"])["due_date"], w.day(45))
        self.assertEqual([h["days"] for h in w.r.payment_terms_history(w.cust)], [45, 15])
        # the database fixes the dates once and keeps terms versions immutable and contiguous
        for sql, params in (("UPDATE prime_bills SET due_date=? WHERE id=?", (w.day(90), b["id"])),
                            ("UPDATE prime_bills SET invoice_date=? WHERE id=?", (w.day(-5), b["id"])),
                            ("UPDATE prime_bills SET payment_terms_days=60 WHERE id=?", (b["id"],)),
                            ("UPDATE customer_payment_terms SET days=90 WHERE customer_id=?", (w.cust,)),
                            ("DELETE FROM customer_payment_terms WHERE customer_id=?", (w.cust,)),
                            ("INSERT INTO customer_payment_terms (id, customer_id, version, days, created_at, created_by) VALUES ('ptm_raw', ?, 9, 30, 'x', 'raw')", (w.cust,)),
                            ("INSERT INTO customer_payment_terms (id, customer_id, version, days, created_at, created_by) VALUES ('ptm_raw', ?, 3, 400, 'x', 'raw')", (w.cust,))):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                w.c.db.execute(sql, params)
        self.assertEqual(len([e for e in w.c.audit.entries(entity_type="party", entity_id=w.cust) if e["action"] == "payment_terms.set"]), 2)
        w.assert_books(self)

    def test_explicit_invoice_date_and_a_terms_change_after_approval(self):
        w = World()
        for bad in (w.day(1), "2026-02-30", "2026/10/01", dt.datetime.now(), 20261001):
            with self.assertRaises(ReceivableInputError, msg=repr(bad)):
                w.certify("60000", invoice_date=bad)
        # never before the start of the bill's period (P1 starts 2026-10-01): a bill booked in
        # October cannot be dated months earlier to make it look long past due
        for bad in ("2026-09-30", "1999-01-01"):
            with self.assertRaisesRegex(ReceivableInputError, "before the start of period P1", msg=bad):
                w.certify("60000", invoice_date=bad)
        self.assertEqual(w.r.list(w.pid), [])
        b = w.certify("60000", period=w.past(), invoice_date=w.day(-40))
        self.assertEqual((b["invoice_date"], b["due_date"]), (w.day(-40), None))
        ap = w.request("prime_bill.approve", b["id"], "accountant")
        bd = ap["manifest"]["bindings"]
        self.assertEqual((bd["invoice_date"], bd["invoice_date_basis"], bd["payment_terms_days"], bd["payment_terms_version"]), (w.day(-40), "explicit", 30, 0))
        w.grant(ap)
        w.r.set_customer_terms(w.cust, 60, "accountant")  # after approval: the due date the approver saw no longer follows
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap["id"], actor="accountant")
        self.assertEqual((w.c.approvals.get(ap["id"])["status"], w.r.get(b["id"])["status"]), ("invalidated", "draft"))
        self.assertEqual(w.c.ledger.journals(source_type="prime_bill"), [])
        w.run("prime_bill.approve", b["id"], "accountant")
        b = w.r.get(b["id"])
        self.assertEqual((b["status"], b["invoice_date"], b["due_date"], b["payment_terms_days"]), ("posted", w.day(-40), w.day(20), 60))
        # the delivered invoice states its dates
        sap = w.request("prime_bill.send", b["id"], "pm")
        self.assertEqual((sap["manifest"]["bindings"]["invoice_date"], sap["manifest"]["bindings"]["due_date"]), (w.day(-40), w.day(20)))
        # invoices are dated in sequence: never before the latest standing bill's invoice date
        with self.assertRaisesRegex(ReceivableInputError, "dated in sequence"):
            w.certify("70000", period=w.past(), invoice_date=w.day(-41))
        second = w.certify("70000", period=w.past(), invoice_date=w.day(-40))  # the same day is fine
        self.assertEqual(second["invoice_date"], w.day(-40))
        w.r.void(second["id"], actor="pm", reason="synthetic probe only")
        # a raw draft carries at most a valid requested invoice date, never a due date
        for invoice_date, due_date in ((w.day(-1), w.day(29)), ("2026-02-30", None), ("12 October", None)):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "at most a valid requested invoice date", msg=(invoice_date, due_date)):
                w.c.db.execute(RAW_DRAFT_BILL, ("pbl_raw", w.pid, w.cust, invoice_date, due_date))
        # ... and the database never takes an invoice date before the start of the bill's period
        with self.assertRaisesRegex(sqlite3.DatabaseError, "never before the start of the period"):
            w.c.db.execute(RAW_DRAFT_BILL, ("pbl_raw", w.pid, w.cust, "2026-09-30", None))
        w.assert_books(self)

    def test_retainage_invoice_is_dated_at_release_on_the_bound_terms(self):
        w = World()
        w.posted("60000")  # 6,000 retained
        ap = w.request("prime_retainage.release", w.pid, "accountant")
        bd = ap["manifest"]["bindings"]
        self.assertEqual((bd["payment_terms_days"], bd["payment_terms_version"], bd["invoice_date_basis"]), (30, 0, "date of posting"))
        w.grant(ap)
        w.r.set_customer_terms(w.cust, 10, "accountant")
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual(w.r.retainage_invoices(w.pid), [])
        res = w.run("prime_retainage.release", w.pid, "accountant").result
        self.assertEqual((res["invoice_date"], res["due_date"]), (w.day(0), w.day(10)))
        inv = w.r.retainage_invoice(res["retainage_invoice"])
        self.assertEqual((inv["invoice_date"], inv["due_date"], inv["payment_terms_days"], inv["amount"]), (w.day(0), w.day(10), 10, "6000.00"))
        item = next(i for i in w.r.ar_open_items(w.pid, as_of=w.day(25))["items"] if i["kind"] == "retainage_invoice")
        self.assertEqual((item["invoice_date"], item["due_date"], item["days_past_due"], item["open"]), (w.day(0), w.day(10), 15, "6000.00"))
        col = w.r.record_collection(retainage_invoice_id=inv["id"], period_id="P1", amount="6000", provider_ref="WIRE-RET-V3", actor="treasury", method="wire")
        self.assertEqual((col["settlement_date"], w.r.retainage_invoice(inv["id"])["status"]), (w.day(0), "collected"))
        for sql, key in (("UPDATE prime_retainage_invoices SET due_date='2099-01-01' WHERE id=?", inv["id"]),
                         ("UPDATE prime_retainage_collections SET settlement_date='2099-01-01' WHERE id=?", col["id"])):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                w.c.db.execute(sql, (key,))
        w.assert_books(self)

    def test_receipts_record_their_settlement_date_apart_from_the_record_time(self):
        w = World()
        b = w.posted("60000", period=w.past(), invoice_date=w.day(-10))
        base = dict(prime_bill_id=b["id"], period_id="P1", amount="1000", provider_ref="CHK-SET-1", actor="treasury", method="check")
        for bad in (w.day(1), "2026-13-01", "yesterday", dt.datetime.now(), 20261012):
            with self.assertRaises(ReceivableInputError, msg=repr(bad)):
                w.r.record_collection(**base, settlement_date=bad)
        with self.assertRaises(ReceivableError) as cm:  # before the invoice it collects: an advance is a deposit
            w.r.record_collection(**base, settlement_date=w.day(-11))
        self.assertIn("deposit", str(cm.exception))
        self.assertEqual(w.r.get(b["id"])["collections"], [])
        col = w.r.record_collection(**base, settlement_date=dt.date.fromisoformat(w.day(-3)))
        self.assertEqual(col["settlement_date"], w.day(-3))  # settled three days ago, recorded now (the real record time)
        self.assertGreaterEqual(col["received_at"][:10], w.day(0))
        col2 = w.r.record_collection(**{**base, "provider_ref": "CHK-SET-2"})
        self.assertEqual(col2["settlement_date"], w.day(0))
        self.assertEqual([c["settlement_date"] for c in w.r.get(b["id"])["collections"]], [w.day(-3), w.day(0)])
        with self.assertRaises(sqlite3.DatabaseError):
            w.c.db.execute("UPDATE collections SET settlement_date=? WHERE id=?", (w.day(-1), col["id"]))
        # the database refuses an undated receipt, a malformed date and one settled before the invoice
        for n, (settle, needle) in enumerate(((None, "records its settlement date"), ("2026-02-30", "records its settlement date"),
                                              (w.day(-11), "before the invoice date"))):
            ref = f"CHK-RAW-{n}"
            with self.assertRaisesRegex(sqlite3.DatabaseError, needle, msg=settle):
                with w.c.db.transaction():  # the receipt's own journal is rolled back with the refused row
                    j = w.receipt_journal(ref, "1.00")
                    w.c.db.execute(RAW_COLLECTION, (f"col_raw_{n}", b["id"], "1.00", j["id"], ref, settle))
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# Credit memos                                                                #
# --------------------------------------------------------------------------- #

class CreditMemoTests(unittest.TestCase):
    def test_credit_memo_posts_dr_revenue_cr_receivable_and_reduces_what_is_open(self):
        w = World()
        b = w.posted("60000")  # 54,000 due, 6,000 retained
        h = w.evidence(b"synthetic concession letter: pay item 4 re-measured")
        memo = w.r.prepare_credit_memo(b["id"], "4000", "pay item 4 re-measured at a lower quantity", h, "accountant")
        self.assertEqual((memo["status"], memo["amount"], memo["bill_hash"], memo["evidence_hash"], memo["journal_id"]), ("draft", "4000.00", b["content_hash"], h, None))
        with self.assertRaises(RoleNotAuthorised):
            w.request("prime_bill.credit_memo", memo["id"], "pm")
        ap = w.request("prime_bill.credit_memo", memo["id"], "accountant")
        m = ap["manifest"]
        self.assertEqual((m["operation"], m["subject"], m["entity"], m["currency"]),
                         ("prime_bill.credit_memo", {"type": "prime_bill_credit_memo", "id": memo["id"]}, ENTITY, "USD"))
        self.assertEqual(m["amounts"], {"amount": "4000.00", "amount_due": "54000.00", "received": "0.00", "credited_by_memo": "0.00", "written_off": "0.00",
                                        "deposits_applied": "0.00", "open_receivable": "54000.00"})
        bd = m["bindings"]
        self.assertEqual((bd["prime_bill_id"], bd["bill_hash"], bd["reason"], bd["evidence_hash"], bd["due_date"], bd["earliest_period"]["id"]),
                         (b["id"], b["content_hash"], memo["reason"], h, b["due_date"], "P1"))
        self.assertIn("SHADOW", bd["recognition_policy"])
        self.assertEqual(preview_of(m), [("4000", "4000.00", "0.00"), ("1100", "0.00", "4000.00")])
        with self.assertRaises(RoleNotAuthorised):
            w.c.approve(ap["id"], approver="pm", approver_role="pm")
        w.grant(ap)
        res = w.c.execute(ap["id"], actor="accountant", period_id="P1")
        j = w.c.ledger.journal(res.result["journal_id"])
        self.assertEqual(lines_of(j), [("4000", "4000.00", "0.00"), ("1100", "0.00", "4000.00")])
        self.assertEqual((j["source_type"], j["source_id"], j["approval_id"], j["period_id"]), ("prime_bill_credit_memo", memo["id"], ap["id"], "P1"))
        self.assertEqual(({ln["party_id"] for ln in j["lines"]}, {ln["project_id"] for ln in j["lines"]}), ({w.cust}, {w.pid}))
        self.assertTrue(w.c.execute(ap["id"], actor="accountant", period_id="P1").replayed)
        self.assertEqual(len(w.c.ledger.journals(source_type="prime_bill_credit_memo")), 1)
        posted = w.r.credit_memo(memo["id"])
        self.assertEqual((posted["status"], posted["journal_id"], posted["posted_on"], posted["standing"], posted["approval_id"]),
                         ("posted", j["id"], w.day(0), True, ap["id"]))
        bill = w.r.get(b["id"])
        self.assertEqual((bill["credited_by_memo"], bill["open"], bill["status"], bill["settled"]), ("4000.00", "50000.00", "posted", False))
        self.assertEqual((w.bal("1100"), w.bal("4000"), w.bal("1150")), (D("50000.00"), D("56000.00"), D("6000.00")))
        ar = w.r.ar_open_items(w.pid)
        self.assertEqual((ar["subledger_total"], ar["control_balance"], ar["reconciled"], ar["items"][0]["credited_by_memo"]), ("50000.00", "50000.00", True, "4000.00"))

        # the rest is collected: the bill is settled, but not "collected" (receipts cover 50,000 of the 54,000 due)
        with self.assertRaises(ReceivableError):
            w.collect(b, "50000.01", "CHK-CM-OVER")
        col = w.collect(b, "50000", "CHK-CM-1")
        bill = w.r.get(b["id"])
        self.assertEqual((bill["open"], bill["settled"], bill["recorded_status"]), ("0.00", True, "posted"))
        with self.assertRaises(ReceivableError):  # nothing open is left to credit
            w.r.prepare_credit_memo(b["id"], "1", "again", h, "accountant")
        w.r.record_return(collection_id=col["id"], period_id="P1", reason="returned check (simulated)", actor="treasury")
        bill = w.r.get(b["id"])
        self.assertEqual((bill["open"], bill["settled"], bill["credited_by_memo"]), ("50000.00", False, "4000.00"))
        for sql in ("UPDATE prime_bill_credit_memos SET amount='1.00' WHERE id=?", "DELETE FROM prime_bill_credit_memos WHERE id=?",
                    "UPDATE prime_bill_credit_memos SET status='cancelled', cancelled_at='x', cancelled_by='x' WHERE id=?"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                w.c.db.execute(sql, (memo["id"],))
        w.assert_books(self)

    def test_credit_memo_inputs_duplicates_stale_approvals_and_periods(self):
        w = World()
        b = w.posted("60000")
        h = w.evidence(b"synthetic concession (inputs)")
        other = w.c.create_project(name="Other synthetic dewatering project", entity=ENTITY, budget="1000", customer_id=w.cust)
        foreign = w.evidence(b"evidence filed on another project", project_id=other["id"])
        draft = w.certify("70000")  # sequence 2, still a draft
        base = dict(prime_bill_id=b["id"], amount="1000", reason="synthetic concession", evidence_hash=h, actor="accountant")
        for change in (dict(amount="0"), dict(amount="-5"), dict(amount=10.0), dict(amount="abc"), dict(amount="NaN"), dict(reason=" "),
                       dict(reason="x" * 501), dict(evidence_hash=""), dict(actor="")):
            with self.assertRaises(ReceivableInputError, msg=repr(change)):
                w.r.prepare_credit_memo(**{**base, **change})
        for change in (dict(evidence_hash="0" * 64), dict(evidence_hash=foreign), dict(amount="54000.01"), dict(prime_bill_id=draft["id"]),
                       dict(prime_bill_id="pbl_missing")):
            with self.assertRaises(ReceivableError, msg=repr(change)):
                w.r.prepare_credit_memo(**{**base, **change})
        self.assertEqual(w.r.credit_memos(), [])
        memo = w.r.prepare_credit_memo(**base)
        with self.assertRaises(ReceivableDuplicate):  # one open draft per bill
            w.r.prepare_credit_memo(**{**base, "amount": "10"})

        # a receipt after approval changes what is open: the approval goes stale and nothing posts
        ap = w.request("prime_bill.credit_memo", memo["id"], "accountant")
        w.grant(ap)
        w.collect(b, "500", "CHK-CM-STALE")
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual((w.c.approvals.get(ap["id"])["status"], w.r.credit_memo(memo["id"])["status"]), ("invalidated", "draft"))
        self.assertEqual(w.c.ledger.journals(source_type="prime_bill_credit_memo"), [])

        # a closed period refuses the posting but keeps the approval for the next open period
        ap2 = w.request("prime_bill.credit_memo", memo["id"], "accountant")
        w.grant(ap2)
        w.c.approve_and_execute("prime_bill.approve", draft["id"], actor_role="accountant", actor="accountant")  # no draft left behind in P1
        w.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            w.c.execute(ap2["id"], actor="accountant", period_id="P1")
        self.assertEqual(w.c.approvals.get(ap2["id"])["status"], "granted")
        res = w.c.execute(ap2["id"], actor="accountant", period_id="P2")
        self.assertEqual((w.c.ledger.journal(res.result["journal_id"])["period_id"], res.result["open"]), ("P2", "52500.00"))

        # cancelling a draft invalidates its approval; cancelled and posted memos never execute again
        m2 = w.r.prepare_credit_memo(**{**base, "amount": "200"})
        ap3 = w.request("prime_bill.credit_memo", m2["id"], "accountant")
        w.grant(ap3)
        with self.assertRaises(ReceivableInputError):
            w.r.cancel_credit_memo(m2["id"], "accountant", " ")
        cancelled = w.r.cancel_credit_memo(m2["id"], "accountant", "issued in error")
        self.assertEqual((cancelled["status"], cancelled["cancelled_by"], cancelled["cancel_reason"]), ("cancelled", "accountant", "issued in error"))
        self.assertEqual(w.c.approvals.get(ap3["id"])["status"], "invalidated")
        with self.assertRaises((ApprovalNotGranted, StaleApprovalError)):
            w.c.execute(ap3["id"], actor="accountant", period_id="P2")
        for fn in (lambda: w.r.cancel_credit_memo(m2["id"], "accountant", "again"), lambda: w.r.cancel_credit_memo(memo["id"], "accountant", "posted already"),
                   lambda: w.request("prime_bill.credit_memo", memo["id"], "accountant"), lambda: w.r.credit_memo("pcm_missing")):
            with self.assertRaises(ReceivableError):
                fn()
        self.assertEqual(w.r.get(b["id"])["open"], "52500.00")  # 54,000 - 500 received - 1,000 credited
        w.assert_books(self)

    def test_cut_off_and_the_database_behind_credit_memos(self):
        w = World()
        late = w.posted("60000", period="P2")
        h = w.evidence(b"synthetic concession (cut-off)")
        memo = w.r.prepare_credit_memo(late["id"], "1000", "concession", h, "accountant")
        ap = w.request("prime_bill.credit_memo", memo["id"], "accountant")
        w.grant(ap)
        with self.assertRaises(ReceivableCutoffError):  # never dated before the bill it credits
            w.c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual(w.c.approvals.get(ap["id"])["status"], "granted")
        w.c.execute(ap["id"], actor="accountant", period_id="P2")
        rev = w.c.db.one("SELECT id FROM document_revisions WHERE content_hash=?", (h,))["id"]
        # a raw memo is a draft, positive, within what is open, backed by evidence on its project
        for args, needle in ((("pcm_raw1", "posted", "100.00", h, rev), "recorded as a draft"),
                             (("pcm_raw2", "draft", "0.00", h, rev), "positive amount"),
                             (("pcm_raw3", "draft", "53000.01", h, rev), "cannot exceed what is open"),
                             (("pcm_raw4", "draft", "100.00", "bogus", rev), "content hash of its evidence revision")):
            mid, status, amount, ev_hash, ev_rev = args
            with self.assertRaisesRegex(sqlite3.DatabaseError, needle, msg=mid):
                w.c.db.execute(RAW_MEMO, (mid, late["id"], w.pid, w.cust, amount, ev_hash, ev_rev, late["content_hash"], status))
        # a raw draft that passes is accepted, but never posts without its consumed approval
        w.c.db.execute(RAW_MEMO, ("pcm_raw_ok", late["id"], w.pid, w.cust, "100.00", h, rev, late["content_hash"], "draft"))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "consumed prime_bill.credit_memo approval"):
            w.c.db.execute("UPDATE prime_bill_credit_memos SET status='posted', posted_at='x', posted_by='raw', posted_on=? WHERE id='pcm_raw_ok'", (w.day(0),))
        w.r.cancel_credit_memo("pcm_raw_ok", "accountant", "raw probe")
        self.assertEqual(w.r.get(late["id"])["open"], "53000.00")
        w.assert_books(self)

    def test_reversals_restore_the_receivable_and_stale_the_open_approvals(self):
        w = World()
        b = w.posted("60000")
        h = w.evidence(b"synthetic concession (reversal)")
        memo = w.r.prepare_credit_memo(b["id"], "4000", "concession", h, "accountant")
        res = w.run("prime_bill.credit_memo", memo["id"], "accountant").result
        w.reverse(res["journal_id"])  # the memo was issued in error
        rev = w.r.credit_memo(memo["id"])
        self.assertEqual((rev["status"], rev["recorded_status"], rev["standing"]), ("reversed", "posted", False))
        bill = w.r.get(b["id"])
        self.assertEqual((bill["credited_by_memo"], bill["open"]), ("0.00", "54000.00"))
        self.assertEqual((w.bal("1100"), w.bal("4000")), (D("54000.00"), D("60000.00")))
        w.assert_books(self)
        # a memo approved before its bill was reversed is invalidated, never posted
        m2 = w.r.prepare_credit_memo(b["id"], "1000", "second concession", h, "accountant")
        ap = w.request("prime_bill.credit_memo", m2["id"], "accountant")
        w.grant(ap)
        w.reverse(b["journal_id"])
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual((w.c.approvals.get(ap["id"])["status"], w.r.credit_memo(m2["id"])["status"]), ("invalidated", "draft"))
        with self.assertRaises(ReceivableError):
            w.r.prepare_credit_memo(b["id"], "1", "on a reversed bill", h, "accountant")
        self.assertEqual(w.bal("1100"), D("0.00"))
        w.assert_books(self)

    def test_a_send_approved_before_a_credit_memo_goes_stale(self):
        """The invoice states the balance due: a credit memo after the send was approved
        changes it, so the approval goes stale instead of telling the customer 54,000 is
        due when 50,000 is open."""
        w = World()
        b = w.posted("60000")
        sap = w.request("prime_bill.send", b["id"], "pm")
        self.assertEqual((sap["manifest"]["bindings"]["balance_due"], sap["manifest"]["bindings"]["credited_by_memo"]), ("54000.00", "0.00"))
        w.grant(sap, "pm")
        h = w.evidence(b"synthetic concession (send)")
        w.run("prime_bill.credit_memo", w.r.prepare_credit_memo(b["id"], "4000", "concession", h, "accountant")["id"], "accountant")
        with self.assertRaises(StaleApprovalError):
            w.c.execute(sap["id"], actor="pm")
        self.assertEqual((w.c.approvals.get(sap["id"])["status"], w.r.get(b["id"])["send"], w.r.get(b["id"])["status"]), ("invalidated", None, "posted"))
        sap2 = w.request("prime_bill.send", b["id"], "pm")
        bd = sap2["manifest"]["bindings"]
        self.assertEqual((sap2["manifest"]["amounts"], bd["credited_by_memo"], bd["balance_due"]), ({"amount_due": "54000.00"}, "4000.00", "50000.00"))
        w.grant(sap2, "pm")
        w.c.execute(sap2["id"], actor="pm")
        self.assertEqual(w.r.get(b["id"])["status"], "sent")
        w.collect(b, "50000", "CHK-SEND-BALANCE")  # the customer pays the stated balance in full
        self.assertEqual((w.r.get(b["id"])["open"], w.r.get(b["id"])["settled"]), ("0.00", True))
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# Write-offs                                                                  #
# --------------------------------------------------------------------------- #

class WriteOffTests(unittest.TestCase):
    def test_write_off_only_at_ninety_days_past_due_and_posts_bad_debt(self):
        w = World()
        old = w.posted("10000", period=w.past(), invoice_date=w.day(-120))    # due day -90: 90 days past due
        young = w.posted("20000", period=w.past(), invoice_date=w.day(-119))  # due day -89: 89 days past due
        self.assertEqual((young["amount_due"], young["due_date"], old["amount_due"], old["due_date"]), ("9000.00", w.day(-89), "9000.00", w.day(-90)))
        with self.assertRaises(ReceivableIneligible) as cm:
            w.r.prepare_write_off(young["id"], "9000", "customer insolvent (synthetic)", "controller")
        self.assertIn("89 days past due", str(cm.exception))
        base = dict(prime_bill_id=old["id"], amount="1000", reason="customer insolvent (synthetic)", actor="controller")
        for change in (dict(amount="0"), dict(amount=1.0), dict(amount="-1"), dict(reason=""), dict(actor=" ")):
            with self.assertRaises(ReceivableInputError, msg=repr(change)):
                w.r.prepare_write_off(**{**base, **change})
        for change in (dict(amount="9000.01"), dict(prime_bill_id="pbl_missing")):
            with self.assertRaises(ReceivableError, msg=repr(change)):
                w.r.prepare_write_off(**{**base, **change})
        wo = w.r.prepare_write_off(old["id"], "6000", "customer insolvent for this portion (synthetic)", "controller")
        self.assertEqual((wo["status"], wo["amount"], wo["requested_on"], wo["due_date"], wo["days_past_due"]), ("draft", "6000.00", w.day(0), w.day(-90), 90))
        with self.assertRaises(ReceivableDuplicate):
            w.r.prepare_write_off(**base)
        for role in ("accountant", "pm", "treasury"):  # a write-off is the controller's authority
            with self.assertRaises(RoleNotAuthorised, msg=role):
                w.request("receivable.write_off", wo["id"], role)
        ap = w.request("receivable.write_off", wo["id"], "controller")
        m = ap["manifest"]
        self.assertEqual((m["subject"], m["amounts"]["amount"], m["amounts"]["open_receivable"]), ({"type": "receivable_write_off", "id": wo["id"]}, "6000.00", "9000.00"))
        bd = m["bindings"]
        self.assertEqual((bd["days_past_due"], bd["minimum_days_past_due"], bd["requested_on"], bd["due_date"], bd["reason"]),
                         (90, 90, w.day(0), w.day(-90), wo["reason"]))
        self.assertGreaterEqual(bd["bill_posted_on"], w.day(0))  # the approver sees the bill reached the books today, dated 120 days ago
        self.assertIn("SHADOW", bd["policy"])
        self.assertEqual(preview_of(m), [("6100", "6000.00", "0.00"), ("1100", "0.00", "6000.00")])
        with self.assertRaises(RoleNotAuthorised):
            w.c.approve(ap["id"], approver="accountant", approver_role="accountant")
        w.grant(ap, "controller")
        res = w.c.execute(ap["id"], actor="controller", period_id="P1")
        j = w.c.ledger.journal(res.result["journal_id"])
        self.assertEqual(lines_of(j), [("6100", "6000.00", "0.00"), ("1100", "0.00", "6000.00")])
        self.assertEqual((j["source_type"], j["source_id"], j["approval_id"], res.result["days_past_due"], res.result["open"]),
                         ("receivable_write_off", wo["id"], ap["id"], 90, "3000.00"))
        self.assertEqual((w.bal("6100"), w.bal("1100")), (D("6000.00"), D("12000.00")))  # 9,000 on the young bill + 3,000 left on the old
        item = next(i for i in w.r.ar_open_items(w.pid)["items"] if i["prime_bill_id"] == old["id"])
        self.assertEqual((item["written_off"], item["open"], item["days_past_due"]), ("6000.00", "3000.00", 90))
        self.assertEqual(w.r.write_off(wo["id"])["status"], "posted")
        # the clock decides: a day earlier the old bill was only 89 days past due
        yesterday = dt.date.fromisoformat(w.day(-1))
        w.r.today = lambda: yesterday
        with self.assertRaises(ReceivableIneligible) as cm:
            w.r.prepare_write_off(old["id"], "3000", "rest uncollectable (synthetic)", "controller")
        self.assertIn("89 days past due", str(cm.exception))
        # a draft requested today is never approved on a clock that reads an earlier day: its
        # days past due would count to a date that has not come yet
        w.r.today = lambda: w.today
        rest = w.r.prepare_write_off(old["id"], "3000", "rest uncollectable (synthetic)", "controller")
        ap_rest = w.request("receivable.write_off", rest["id"], "controller")
        w.grant(ap_rest, "controller")
        w.r.today = lambda: yesterday
        with self.assertRaisesRegex(ReceivableIneligible, "after today"):
            w.request("receivable.write_off", rest["id"], "controller")
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap_rest["id"], actor="controller", period_id="P1")
        self.assertEqual((w.c.approvals.get(ap_rest["id"])["status"], w.r.write_off(rest["id"])["status"]), ("invalidated", "draft"))
        w.r.today = lambda: w.today
        res = w.run("receivable.write_off", rest["id"], "controller").result
        self.assertEqual((res["open"], w.bal("6100"), w.bal("1100")), ("0.00", D("9000.00"), D("9000.00")))
        w.assert_books(self)

    def test_a_write_off_dated_ahead_never_posts(self):
        """The reviewer's probe: a raw draft on a bill not yet due, requested 95 days after
        the due date (so in the future), is refused by the database; so is one requested
        after the day it is recorded."""
        w = World()
        old = w.posted("10000", period=w.past(), invoice_date=w.day(-130))  # due day -100
        b = w.posted("20000")  # dated today, due in 30 days
        self.assertEqual(b["due_date"], w.day(30))
        ahead = w.day(30 + 95)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "requested no later than today"):
            w.c.db.execute(RAW_WRITE_OFF, ("wof_ahead", b["id"], w.pid, w.cust, "1000.00", "raw", ahead, b["due_date"], 95, b["content_hash"], utcnow_iso()))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "no later than the day it is recorded"):
            w.c.db.execute(RAW_WRITE_OFF, ("wof_backdated_record", old["id"], w.pid, w.cust, "100.00", "raw", w.day(0), old["due_date"], 100,
                                           old["content_hash"], f"{w.day(-1)}T23:00:00Z"))
        self.assertEqual(w.r.write_offs(), [])
        self.assertEqual((w.bal("6100"), w.r.get(b["id"])["open"]), (D("0.00"), "9000.00"))
        w.assert_books(self)

    def test_write_off_approval_goes_stale_when_the_receivable_changes(self):
        w = World()
        b = w.posted("10000", period=w.past(), invoice_date=w.day(-200))
        wo = w.r.prepare_write_off(b["id"], "9000", "uncollectable (synthetic)", "controller")
        ap = w.request("receivable.write_off", wo["id"], "controller")
        w.grant(ap, "controller")
        w.collect(b, "100", "CHK-WO-LATE")  # a late partial receipt
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap["id"], actor="controller", period_id="P1")
        self.assertEqual((w.c.approvals.get(ap["id"])["status"], w.c.ledger.journals(source_type="receivable_write_off")), ("invalidated", []))
        with self.assertRaises(ReceivableIneligible):  # 9,000 no longer fits the 8,900 open
            w.request("receivable.write_off", wo["id"], "controller")
        w.r.cancel_write_off(wo["id"], "controller", "a partial receipt arrived")
        wo2 = w.r.prepare_write_off(b["id"], "8900", "uncollectable remainder (synthetic)", "controller")
        w.run("receivable.write_off", wo2["id"], "controller")
        bill = w.r.get(b["id"])
        self.assertEqual((bill["open"], bill["written_off"], bill["settled"]), ("0.00", "8900.00", True))
        item = w.r.ar_open_items(w.pid)["items"][0]
        self.assertEqual((item["due_date"], item["days_past_due"]), (w.day(-170), 0))  # settled: nothing is past due any more
        with self.assertRaises(ReceivableError):  # nothing open is left
            w.r.prepare_write_off(b["id"], "1", "again", "controller")
        # the database refuses a write-off short of 90 days, or one misstating its days past due
        fresh = w.posted("20000", period=w.past(), invoice_date=w.day(-100))  # due day -70
        for days, needle in ((70, "at least 90 days past due"), (95, "days past due on the date it was requested")):
            with self.assertRaisesRegex(sqlite3.DatabaseError, needle, msg=days):
                w.c.db.execute(RAW_WRITE_OFF, (f"wof_raw_{days}", fresh["id"], w.pid, w.cust, "100.00", "raw", w.day(0), fresh["due_date"], days,
                                               fresh["content_hash"], utcnow_iso()))
        for sql in ("UPDATE receivable_write_offs SET amount='1.00' WHERE id=?", "DELETE FROM receivable_write_offs WHERE id=?"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                w.c.db.execute(sql, (wo2["id"],))
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# Customer deposits                                                           #
# --------------------------------------------------------------------------- #

class DepositTests(unittest.TestCase):
    def test_deposit_receipt_and_application_post_exact_journals(self):
        w = World()
        b = w.posted("60000")  # 54,000 due
        dep = w.r.record_deposit(w.cust, w.pid, "20000", "WIRE-DEP-0001", "wire", "treasury", period_id="P1", settlement_date=w.day(-1))
        self.assertEqual((dep["amount"], dep["applied"], dep["unapplied"], dep["status"], dep["method"], dep["mandate_id"], dep["settlement_date"]),
                         ("20000.00", "0.00", "20000.00", "unapplied", "wire", None, w.day(-1)))
        j = w.c.ledger.journal(dep["journal_id"])
        self.assertEqual(lines_of(j), [("1000", "20000.00", "0.00"), ("2400", "0.00", "20000.00")])
        self.assertEqual((j["source_type"], j["source_id"], j["period_id"]), ("customer_deposit", dep["id"], "P1"))
        self.assertEqual(w.c.ledger.account_for_control("customer_deposits"), "2400")
        di = w.r.deposits_items()
        self.assertEqual((di["subledger_total"], di["control_balance"], di["reconciled"], di["errors"]), ("20000.00", "20000.00", True, []))

        app = w.r.prepare_deposit_application(dep["id"], b["id"], "15000", "accountant")
        self.assertEqual((app["status"], app["amount"], app["deposit_id"], app["prime_bill_id"]), ("draft", "15000.00", dep["id"], b["id"]))
        for role in ("pm", "treasury"):
            with self.assertRaises(RoleNotAuthorised, msg=role):
                w.request("receivable.apply_deposit", app["id"], role)
        ap = w.request("receivable.apply_deposit", app["id"], "accountant")
        m = ap["manifest"]
        self.assertEqual(m["amounts"], {"amount": "15000.00", "deposit_amount": "20000.00", "deposit_applied": "0.00", "deposit_unapplied": "20000.00",
                                        "amount_due": "54000.00", "received": "0.00", "credited_by_memo": "0.00", "written_off": "0.00",
                                        "deposits_applied": "0.00", "open_receivable": "54000.00"})
        self.assertEqual((m["bindings"]["deposit_id"], m["bindings"]["deposit_ref"], m["bindings"]["prime_bill_id"], m["bindings"]["bill_hash"]),
                         (dep["id"], "WIRE-DEP-0001", b["id"], b["content_hash"]))
        self.assertEqual(preview_of(m), [("2400", "15000.00", "0.00"), ("1100", "0.00", "15000.00")])
        w.grant(ap)
        res = w.c.execute(ap["id"], actor="accountant", period_id="P1")
        j2 = w.c.ledger.journal(res.result["journal_id"])
        self.assertEqual(lines_of(j2), [("2400", "15000.00", "0.00"), ("1100", "0.00", "15000.00")])
        self.assertEqual((j2["source_type"], j2["source_id"], j2["approval_id"], res.result["deposit_unapplied"], res.result["open"]),
                         ("deposit_application", app["id"], ap["id"], "5000.00", "39000.00"))
        self.assertTrue(w.c.execute(ap["id"], actor="accountant", period_id="P1").replayed)
        self.assertEqual((w.bal("1000"), w.bal("2400"), w.bal("1100")), (D("20000.00"), D("5000.00"), D("39000.00")))
        d = w.r.deposit(dep["id"])
        self.assertEqual((d["applied"], d["unapplied"], d["status"], [a["status"] for a in d["applications"]]), ("15000.00", "5000.00", "partially_applied", ["posted"]))
        bill = w.r.get(b["id"])
        self.assertEqual((bill["deposits_applied"], bill["open"], bill["recorded_status"]), ("15000.00", "39000.00", "posted"))
        di = w.r.deposits_items(w.pid)
        self.assertEqual((di["subledger_total"], di["control_balance"], di["reconciled"], [i["open"] for i in di["items"]]), ("5000.00", "5000.00", True, ["5000.00"]))
        ar = w.r.ar_open_items(w.pid)
        self.assertEqual((ar["subledger_total"], ar["control_balance"], ar["items"][0]["deposits_applied"]), ("39000.00", "39000.00", "15000.00"))
        w.assert_books(self)

    def test_deposit_inputs_mandates_references_periods_and_database_guards(self):
        w = World()
        b = w.posted("60000")
        other = w.c.add_party(kind="customer", name="Another synthetic owner")
        other_prj = w.c.create_project(name="Other synthetic cofferdam", entity=ENTITY, budget="1000", customer_id=other["id"])
        base = dict(customer_id=w.cust, project_id=w.pid, amount="1000", provider_ref="CHK-DEP-1", method="check", actor="treasury")
        for change in (dict(amount="0"), dict(amount=5.0), dict(amount="-1"), dict(method="card"), dict(method=None), dict(provider_ref=" "), dict(actor=""),
                       dict(settlement_date=w.day(1)), dict(settlement_date="2026-02-30"), dict(mandate_ref="M-1")):
            with self.assertRaises(ReceivableInputError, msg=repr(change)):
                w.r.record_deposit(**{**base, **change})
        for change in (dict(project_id=other_prj["id"]), dict(customer_id=other["id"]), dict(customer_id="pty_missing"), dict(project_id="prj_missing")):
            with self.assertRaises(ReceivableError, msg=repr(change)):
                w.r.record_deposit(**{**base, **change})
        with self.assertRaises(ReceivableError) as cm:  # ACH needs the customer's active mandate, as for collections
            w.r.record_deposit(**{**base, "method": "ach", "provider_ref": "ach_dep_1"})
        self.assertIn("missing mandate", str(cm.exception))
        self.assertEqual(w.r.deposits(), [])
        mandate = w.mandate()
        ach = w.r.record_deposit(**{**base, "method": "ach", "provider_ref": "ach_dep_1"})
        self.assertEqual((ach["mandate_id"], ach["method"]), (mandate["id"], "ach"))
        # one reference across every receipt table, ignoring case
        w.collect(b, "100", "CHK-SHARED-REF")
        for ref in ("chk-shared-ref", "ACH_DEP_1"):
            with self.assertRaises(ReceivableDuplicate, msg=ref):
                w.r.record_deposit(**{**base, "provider_ref": ref})
        with self.assertRaises(ReceivableError):
            w.collect(b, "100", "Ach_Dep_1")
        w.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            w.r.record_deposit(**base, period_id="P1")
        dep = w.r.record_deposit(**base)  # the latest open period by default
        self.assertEqual((dep["period_id"], dep["settlement_date"]), ("P2", w.day(0)))
        self.assertEqual([d["provider_ref"] for d in w.r.deposits(customer_id=w.cust)], ["ach_dep_1", "CHK-DEP-1"])
        # deposits are immutable, and a raw one needs its own journal and, for ACH, a mandate
        for sql in ("UPDATE customer_deposits SET amount='1.00' WHERE id=?", "DELETE FROM customer_deposits WHERE id=?"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                w.c.db.execute(sql, (dep["id"],))
        tags = {"project_id": w.pid, "party_id": w.cust}
        for did, method, ref, journal_amount, needle in (("dep_raw1", "ach", "RAW-DEP-1", "50.00", "missing mandate"),
                                                         ("dep_raw2", "check", "RAW-DEP-2", "49.99", "its own journal crediting 2400"),
                                                         ("dep_raw3", "check", "chk-dep-1", "50.00", "recorded once, ignoring case")):
            with self.assertRaisesRegex(sqlite3.DatabaseError, needle, msg=did):
                with w.c.db.transaction():
                    j = w.c.ledger.post(period_id="P2", description="raw deposit (synthetic)", source_type="customer_deposit", source_id=did, source_version="1",
                                        posted_by="test", lines=[{"account": "1000", "debit": journal_amount, **tags}, {"account": "2400", "credit": journal_amount, **tags}])
                    w.c.db.execute(RAW_DEPOSIT, (did, w.cust, w.pid, "50.00", method, ref, w.day(0), "P2", j["id"]))
        self.assertEqual(len(w.r.deposits()), 2)
        w.assert_books(self)

    def test_a_deposit_is_never_applied_beyond_its_balance(self):
        w = World()
        b1 = w.posted("60000")  # 54,000 due
        b2 = w.posted("80000")  # 18,000 due
        other_prj = w.c.create_project(name="Synthetic pump station dewatering", entity=ENTITY, budget="1000", customer_id=w.cust)
        b3 = w.posted("1000", project_id=other_prj["id"])
        dep = w.r.record_deposit(w.cust, w.pid, "10000", "WIRE-DEP-BAL", "wire", "treasury", period_id="P1")
        for args in ((dep["id"], b1["id"], "10000.01"), (dep["id"], b3["id"], "100"), ("dep_missing", b1["id"], "1"), (dep["id"], "pbl_missing", "1")):
            with self.assertRaises(ReceivableError, msg=args):  # beyond the deposit, another project's bill, unknown records
                w.r.prepare_deposit_application(*args, "accountant")
        for amount in ("0", "-1", 2.5):
            with self.assertRaises(ReceivableInputError):
                w.r.prepare_deposit_application(dep["id"], b1["id"], amount, "accountant")
        a1 = w.r.prepare_deposit_application(dep["id"], b1["id"], "8000", "accountant")
        a2 = w.r.prepare_deposit_application(dep["id"], b2["id"], "8000", "accountant")  # each fits on its own
        with self.assertRaises(ReceivableDuplicate):
            w.r.prepare_deposit_application(dep["id"], b1["id"], "1000", "accountant")
        ap1 = w.request("receivable.apply_deposit", a1["id"], "accountant")
        ap2 = w.request("receivable.apply_deposit", a2["id"], "accountant")
        w.grant(ap1)
        w.grant(ap2)
        w.c.execute(ap1["id"], actor="accountant", period_id="P1")
        with self.assertRaises(StaleApprovalError):  # the deposit balance it was approved on is gone
            w.c.execute(ap2["id"], actor="accountant", period_id="P1")
        self.assertEqual((w.c.approvals.get(ap2["id"])["status"], w.r.deposit_application(a2["id"])["status"]), ("invalidated", "draft"))
        with self.assertRaises(ReceivableIneligible):  # 8,000 no longer fits the 2,000 left
            w.request("receivable.apply_deposit", a2["id"], "accountant")
        # the database refuses an application beyond the balance, and a raw post of a draft
        with self.assertRaisesRegex(sqlite3.DatabaseError, "unapplied balance of its deposit"):
            w.c.db.execute(RAW_APPLICATION, ("dap_raw", dep["id"], b2["id"], w.pid, w.cust, "2000.01", b2["content_hash"]))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "a deposit is applied only to a prime bill of its own customer and project"):
            w.c.db.execute(RAW_APPLICATION, ("dap_raw2", dep["id"], b3["id"], other_prj["id"], w.cust, "1.00", b3["content_hash"]))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "consumed receivable.apply_deposit approval"):
            w.c.db.execute("UPDATE deposit_applications SET status='posted', posted_at='x', posted_by='raw' WHERE id=?", (a2["id"],))
        w.r.cancel_deposit_application(a2["id"], "accountant", "superseded by a smaller application")
        a3 = w.r.prepare_deposit_application(dep["id"], b2["id"], "2000", "accountant")
        w.run("receivable.apply_deposit", a3["id"], "accountant")
        d = w.r.deposit(dep["id"])
        self.assertEqual((d["applied"], d["unapplied"], d["status"]), ("10000.00", "0.00", "applied"))
        with self.assertRaises(ReceivableError):  # nothing is left to apply
            w.r.prepare_deposit_application(dep["id"], b2["id"], "0.01", "accountant")
        self.assertEqual((w.bal("2400"), w.bal("1100", project_id=w.pid)), (D("0.00"), D("62000.00")))  # 54,000 + 18,000 - 10,000
        self.assertEqual((w.r.get(b1["id"])["open"], w.r.get(b2["id"])["open"]), ("46000.00", "16000.00"))
        w.assert_books(self)

    def test_an_application_goes_stale_when_its_bill_changes(self):
        w = World()
        b = w.posted("60000")
        dep = w.r.record_deposit(w.cust, w.pid, "1000", "WIRE-DEP-STALE", "wire", "treasury", period_id="P1")
        app = w.r.prepare_deposit_application(dep["id"], b["id"], "1000", "accountant")
        ap = w.request("receivable.apply_deposit", app["id"], "accountant")
        w.grant(ap)
        w.collect(b, "54000", "CHK-DEP-FULL")  # the bill is collected in full before the application executes
        self.assertEqual(w.r.get(b["id"])["recorded_status"], "collected")
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual((w.c.approvals.get(ap["id"])["status"], w.r.deposit(dep["id"])["unapplied"], w.bal("2400")), ("invalidated", "1000.00", D("1000.00")))
        with self.assertRaises(ReceivableIneligible):
            w.request("receivable.apply_deposit", app["id"], "accountant")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "cannot exceed what is open"):  # nor can the database apply it
            w.c.db.execute(RAW_APPLICATION, ("dap_raw_open", dep["id"], b["id"], w.pid, w.cust, "1.00", b["content_hash"]))
        w.assert_books(self)

    def test_a_deposit_with_standing_applications_cannot_be_reversed(self):
        w = World()
        b = w.posted("60000")
        dep = w.r.record_deposit(w.cust, w.pid, "5000", "WIRE-DEP-REV", "wire", "treasury", period_id="P1")
        app = w.r.prepare_deposit_application(dep["id"], b["id"], "3000", "accountant")
        res = w.run("receivable.apply_deposit", app["id"], "accountant").result
        with self.assertRaisesRegex(sqlite3.DatabaseError, "standing applications"):  # refused when the reversal is requested
            w.reverse(dep["journal_id"])
        self.assertEqual(w.requests(dep["journal_id"]), 0)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "standing applications"):  # and on any direct reversal
            w.c.ledger.reverse(dep["journal_id"], period_id="P1", posted_by="controller", reason="direct probe")
        self.assertIsNone(w.r.deposit(dep["id"])["reversal_journal_id"])
        w.reverse(res["journal_id"])  # the application first: deposit balance and receivable restored
        self.assertEqual((w.r.deposit(dep["id"])["unapplied"], w.r.get(b["id"])["open"], w.r.deposit_application(app["id"])["status"]),
                         ("5000.00", "54000.00", "reversed"))
        w.assert_books(self)
        w.reverse(dep["journal_id"])
        d = w.r.deposit(dep["id"])
        self.assertEqual((d["status"], d["unapplied"], d["reversed"]), ("reversed", "0.00", "5000.00"))
        self.assertEqual((w.bal("2400"), w.bal("1000")), (D("0.00"), D("0.00")))
        with self.assertRaises(ReceivableError):
            w.r.prepare_deposit_application(dep["id"], b["id"], "1", "accountant")
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# Reversing a prime bill while adjustments stand                              #
# --------------------------------------------------------------------------- #

class BillReversalTests(unittest.TestCase):
    """A prime bill whose credit memos, write-offs or deposit applications still stand is
    never reversed: 1100 would go negative, revenue or bad debt would rest on a bill that
    no longer exists, and the credit could not follow a re-bill."""

    def _adjusted(self, kind):
        w = World()
        b = w.posted("60000", period=w.past(), invoice_date=w.day(-130))  # 54,000 due on day -100
        if kind == "credit memo":
            h = w.evidence(b"synthetic concession (bill reversal)")
            draft = w.r.prepare_credit_memo(b["id"], "4000", "concession", h, "accountant")
            res = w.run("prime_bill.credit_memo", draft["id"], "accountant").result
        elif kind == "write-off":
            draft = w.r.prepare_write_off(b["id"], "4000", "uncollectable portion (synthetic)", "controller")
            res = w.run("receivable.write_off", draft["id"], "controller").result
        else:
            dep = w.r.record_deposit(w.cust, w.pid, "4000", "WIRE-DEP-REVBILL", "wire", "treasury", period_id="P1")
            draft = w.r.prepare_deposit_application(dep["id"], b["id"], "4000", "accountant")
            res = w.run("receivable.apply_deposit", draft["id"], "accountant").result
        return w, b, res

    def test_a_bill_is_reversed_only_once_its_adjustments_are(self):
        for kind, account in (("credit memo", "4000"), ("write-off", "6100"), ("deposit application", "2400")):
            with self.subTest(kind):
                w, b, res = self._adjusted(kind)
                before = (w.bal("1100"), w.bal(account), len(w.c.ledger.journals()))
                self.assertEqual(before[0], D("50000.00"))
                with self.assertRaisesRegex(sqlite3.DatabaseError, "standing credit memos, write-offs or deposit applications"):
                    w.reverse(b["journal_id"])  # refused when the reversal is requested: no approval is ever sought
                self.assertEqual(w.requests(b["journal_id"]), 0)
                with self.assertRaisesRegex(sqlite3.DatabaseError, "standing credit memos, write-offs or deposit applications"):
                    w.c.ledger.reverse(b["journal_id"], period_id="P1", posted_by="controller", reason="direct probe")  # the reversing journal too
                self.assertEqual((w.bal("1100"), w.bal(account), len(w.c.ledger.journals())), before)
                self.assertFalse(w.r.get(b["id"])["reversed"])
                w.assert_books(self)
                # the adjustment first, then the bill: nothing is left open, negative or stranded
                w.reverse(res["journal_id"])
                w.reverse(b["journal_id"])
                bill = w.r.get(b["id"])
                self.assertEqual((bill["status"], bill["open"], bill["credited_by_memo"], bill["written_off"], bill["deposits_applied"]),
                                 ("reversed", "0.00", "0.00", "0.00", "0.00"))
                self.assertEqual((w.bal("1100"), w.bal("4000"), w.bal("6100"), w.bal("2400")),
                                 (D("0.00"), D("0.00"), D("0.00"), D("4000.00") if kind == "deposit application" else D("0.00")))
                # the work is billed again exactly once, with nothing carried over from the reversed bill
                rebill = w.posted("60000")
                self.assertEqual((rebill["amount_due"], rebill["open"], w.bal("1100")), ("54000.00", "54000.00", D("54000.00")))
                ar = w.r.ar_open_items()
                self.assertEqual((ar["subledger_total"], ar["errors"]), ("54000.00", []))
                w.assert_books(self)

    def test_a_reversal_requested_before_an_adjustment_posts_is_refused_at_execution(self):
        w = World()
        b = w.posted("60000")
        w.c.ledger.prepare_reversal(b["journal_id"], "synthetic correction: wrong pay item", "controller")
        ap = w.request("journal.reverse", b["journal_id"], "controller")
        w.grant(ap)
        h = w.evidence(b"synthetic concession (pending reversal)")
        w.run("prime_bill.credit_memo", w.r.prepare_credit_memo(b["id"], "1000", "concession", h, "accountant")["id"], "accountant")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "standing credit memos"):
            w.c.execute(ap["id"], actor="controller", period_id="P1")
        bill = w.r.get(b["id"])
        self.assertEqual((bill["reversed"], bill["open"], w.bal("1100"), w.bal("4000")), (False, "53000.00", D("53000.00"), D("59000.00")))
        self.assertEqual(w.c.ledger.journals(source_type="prime_bill")[0]["id"], b["journal_id"])
        self.assertEqual(len(w.c.ledger.journals(source_type="prime_bill")), 1)
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# Close, export and upgrade                                                    #
# --------------------------------------------------------------------------- #

class CloseExportAndUpgradeTests(unittest.TestCase):
    def test_close_checklist_and_statements_after_every_adjustment(self):
        w = World(isolate=True)
        b = w.posted("60000", period=w.past(), invoice_date=w.day(-130))  # 54,000 due on day -100: 100 days past due
        w.c.close_period("P0")  # the bill's own (earlier) period is closed; every adjustment posts in P1
        h = w.evidence(b"synthetic concession (close)")
        w.run("prime_bill.credit_memo", w.r.prepare_credit_memo(b["id"], "2000", "concession", h, "accountant")["id"], "accountant")
        w.run("receivable.write_off", w.r.prepare_write_off(b["id"], "1000", "uncollectable portion (synthetic)", "controller")["id"], "controller")
        dep = w.r.record_deposit(w.cust, w.pid, "7000", "WIRE-DEP-CLOSE", "wire", "treasury", period_id="P1")
        w.run("receivable.apply_deposit", w.r.prepare_deposit_application(dep["id"], b["id"], "5000", "accountant")["id"], "accountant")
        cl = w.c.plugin("close")
        report = cl.checklist_report("P1")
        self.assertTrue(report["all_ok"], report["failing"])
        ar = next(ch for ch in report["checks"] if ch["check"] == "ar_reconciled")
        self.assertEqual(ar["detail"], "AR subledger 46000.00 vs control 1100 46000.00")  # 54,000 - 2,000 - 1,000 - 5,000
        self.assertEqual((w.r.deposits_items()["subledger_total"], w.bal("2400")), ("2000.00", D("2000.00")))
        for ch in w.c.plugin("core_reconciliation").close_checks("P1"):
            self.assertTrue(ch["ok"], ch)
        st = cl.statements("P1")
        inc = st["income_statement"]
        self.assertEqual({ln["code"]: ln["amount"] for ln in inc["revenue_lines"]}, {"4000": "-2000.00"})  # P1 holds the credit memo; the bill is P0's
        self.assertEqual({ln["code"]: ln["amount"] for ln in cl.statements("P0")["income_statement"]["revenue_lines"]}, {"4000": "60000.00"})
        self.assertEqual({ln["code"]: ln["amount"] for ln in inc["expense_lines"]}, {"6100": "1000.00"})
        self.assertEqual({ln["code"]: ln["amount"] for ln in st["balance_sheet"]["liabilities"]}, {"2400": "2000.00"})
        self.assertTrue(st["balance_sheet"]["balanced"])
        # an unexplained entry on 2400 breaks the deposit reconciliation (and its core check, once wired)
        stray = w.c.ledger.post(period_id="P1", description="unexplained deposit (synthetic)", source_type="test", source_id="stray-2400", source_version="1",
                                posted_by="test", lines=[{"account": "1000", "debit": "100", "project_id": w.pid}, {"account": "2400", "credit": "100", "project_id": w.pid}])
        di = w.r.deposits_items()
        self.assertEqual((di["subledger_total"], di["control_balance"], di["reconciled"]), ("2000.00", "2100.00", False))
        for ch in w.c.plugin("core_reconciliation").close_checks("P1"):
            if "2400" in ch["check"]:
                self.assertFalse(ch["ok"], ch)
        w.c.ledger.reverse(stray["id"], period_id="P1", posted_by="owner", reason="unexplained deposit entry")
        res = w.c.approve_and_execute("close.close_period", "P1")
        self.assertEqual(res.result["status"], "closed")
        with self.assertRaises(PeriodNotOpen):
            w.r.record_deposit(w.cust, w.pid, "1", "WIRE-DEP-CLOSED", "wire", "treasury", period_id="P1")
        w.assert_books(self)

    def test_audit_export_lists_terms_credits_write_offs_and_deposits(self):
        w = World()
        w.r.set_customer_terms(w.cust, 20, "accountant")
        b = w.posted("60000", period=w.past(), invoice_date=w.day(-150))
        h = w.evidence(b"synthetic concession (export)")
        w.run("prime_bill.credit_memo", w.r.prepare_credit_memo(b["id"], "100", "concession", h, "accountant")["id"], "accountant")
        w.run("receivable.write_off", w.r.prepare_write_off(b["id"], "200", "uncollectable (synthetic)", "controller")["id"], "controller")
        dep = w.r.record_deposit(w.cust, w.pid, "300", "WIRE-DEP-EXP", "wire", "treasury", period_id="P1")
        w.run("receivable.apply_deposit", w.r.prepare_deposit_application(dep["id"], b["id"], "300", "accountant")["id"], "accountant")
        exp = w.r.audit_export()
        self.assertEqual([len(exp[k]) for k in ("payment_terms", "credit_memos", "write_offs", "customer_deposits", "deposit_applications")], [1, 1, 1, 1, 1])
        self.assertTrue(exp["ar_reconciliation"]["reconciled"] and exp["deposits_reconciliation"]["reconciled"])
        self.assertEqual(exp["ar_reconciliation"]["subledger_total"], "53400.00")
        self.assertIn("SHADOW", exp["policies"]["credit_memo"])
        full = w.c.audit_export()
        self.assertTrue(full["core_domains"]["receivables"]["deposits_reconciliation"]["reconciled"])
        self.assertEqual(full["tables"]["customer_deposits"]["row_count"], 1)
        w.assert_books(self)

    def test_an_earlier_workspace_upgrades_without_inventing_dates(self):
        path = os.path.join(tempfile.mkdtemp(), "ar-v3-upgrade.sqlite")
        legacy = [e for e in core_db.SCHEMA_CATALOG
                  if e[1] not in (CONTROLS_SCHEMA_NAME, CONTROLS_GUARDS_SCHEMA_NAME, DATES_CREDITS_SCHEMA_NAME, DATES_CREDITS_GUARDS_SCHEMA_NAME)]
        with mock.patch.object(core_db, "SCHEMA_CATALOG", legacy):
            w = World(path=path)
            tags = {"project_id": w.pid, "party_id": w.cust}
            j = w.c.ledger.post(period_id="P1", description="Prime bill 1 (legacy)", source_type="prime_bill", source_id="pbl_old", source_version="1", posted_by="owner",
                                lines=[{"account": "1100", "debit": "9000.00", **tags}, {"account": "1150", "debit": "1000.00", **tags},
                                       {"account": "4000", "credit": "10000.00", **tags}])
            w.c.db.execute(
                """INSERT INTO prime_bills (id, project_id, customer_id, period_id, sequence, status, certified_cumulative, retainage_rate, retainage_cumulative,
                   prior_net, amount_due, revenue_this_period, content_hash, approval_id, journal_id, created_at)
                   VALUES ('pbl_old', ?, ?, 'P1', 1, 'posted', '10000.00', '0.100000', '1000.00', '0.00', '9000.00', '10000.00', 'legacy-hash', NULL, ?,
                   '2026-10-05T00:00:00Z')""", (w.pid, w.cust, j["id"]))
            self.assertIsNone(w.c.db.one("SELECT name FROM sqlite_master WHERE name='customer_deposits'"))
            w.c.db.close()
        c = Cipher(path)
        try:
            self.assertEqual(c.db.schema_status()["pending"], [])
            self.assertTrue({"2400", "6100"} <= {a["code"] for a in c.ledger.accounts()})
            r = c.receivables
            old = r.get("pbl_old")
            self.assertEqual((old["invoice_date"], old["due_date"], old["payment_terms_days"], old["open"]), (None, None, None, "9000.00"))
            item = r.ar_open_items()["items"][0]
            self.assertEqual((item["invoice_date"], item["due_date"], item["days_past_due"]), (None, None, None))
            with self.assertRaises(ReceivableIneligible):  # nothing dates it, so it is never aged into a write-off
                r.prepare_write_off("pbl_old", "100", "undated receivable", "controller")
            col = r.record_collection(prime_bill_id="pbl_old", period_id="P1", amount="1000", provider_ref="CHK-OLD-1", actor="treasury", method="check")
            self.assertEqual(col["settlement_date"], r.today().isoformat())
            doc = c.evidence.register_document(project_id=w.pid, kind="receivable_evidence", title="Legacy concession (synthetic)", actor="owner")
            h = c.evidence.add_revision(document_id=doc["id"], content=b"synthetic legacy concession", note="signed", actor="owner")["content_hash"]
            memo = r.prepare_credit_memo("pbl_old", "500", "legacy concession", h, "accountant")
            c.approve_and_execute("prime_bill.credit_memo", memo["id"], actor_role="accountant", actor="accountant", period_id="P1")
            self.assertEqual(r.get("pbl_old")["open"], "7500.00")
            aged = c.plugin("close").aging(r.today().isoformat())["ar"]["items"]
            self.assertEqual([(it["ref"], it["basis"], it["due_date"]) for it in aged], [("pbl_old", "document_date", None)])
            self.assertTrue(r.ar_open_items()["reconciled"] and r.deposits_items()["reconciled"] and r.retainage_receivable_items()["reconciled"])
            self.assertTrue(c.ledger.trial_balance()["balanced"])
            self.assertTrue(c.audit.verify_chain()["ok"])
        finally:
            c.db.close()

    def test_records_written_before_the_guards_are_reported_and_never_post(self):
        """A workspace written before receivables_dates_credits_guards may hold a prime bill
        reversed under a standing credit memo (1100 negative on it) and a write-off draft
        requested in the future.  After the upgrade the first is reported (AR is not
        reconciled, so the close is blocked) and the second is never approved or posted."""
        path = os.path.join(tempfile.mkdtemp(), "ar-v3-guards-upgrade.sqlite")
        legacy = [e for e in core_db.SCHEMA_CATALOG if e[1] != DATES_CREDITS_GUARDS_SCHEMA_NAME]
        with mock.patch.object(core_db, "SCHEMA_CATALOG", legacy):
            w = World(path=path)
            b = w.posted("60000")  # 54,000 due
            h = w.evidence(b"synthetic concession (before the guards)")
            memo = w.r.prepare_credit_memo(b["id"], "4000", "concession", h, "accountant")
            memo_journal = w.run("prime_bill.credit_memo", memo["id"], "accountant").result["journal_id"]
            w.reverse(b["journal_id"])  # the earlier schema let the bill be reversed under its standing memo
            rebill = w.posted("60000")  # the work billed again: 54,000 due
            w.c.db.execute(RAW_WRITE_OFF, ("wof_ahead_legacy", rebill["id"], w.pid, w.cust, "1000.00", "raw", w.day(30 + 95), rebill["due_date"], 95,
                                           rebill["content_hash"], utcnow_iso()))  # requested 95 days after a due date 30 days ahead
            self.assertEqual(w.bal("1100"), D("50000.00"))
            w.c.db.close()
        c = Cipher(path)
        try:
            status = c.db.schema_status()
            self.assertEqual(status["pending"], [])
            r = c.receivables
            ar = r.ar_open_items()
            self.assertEqual((ar["subledger_total"], ar["control_balance"], ar["reconciled"]), ("50000.00", "50000.00", False))
            self.assertEqual([(e["source"], e["prime_bill_id"]) for e in ar["errors"]], [("prime_bill", b["id"])])
            self.assertIn(memo["id"], ar["errors"][0]["error"])
            self.assertEqual(r.get(b["id"])["open"], "-4000.00")
            check = next(ch for ch in c.plugin("close").checklist("P1") if ch["check"] == "ar_reconciled")
            self.assertFalse(check["ok"])
            self.assertIn("still stand", check["detail"])
            # the draft requested ahead is never approved, and the database never posts it
            with self.assertRaisesRegex(ReceivableIneligible, "after today"):
                c.request_approval("receivable.write_off", "wof_ahead_legacy", actor_role="controller", requested_by="controller")
            with self.assertRaises(sqlite3.DatabaseError):
                c.db.execute("UPDATE receivable_write_offs SET status='posted', posted_at='x', posted_by='raw' WHERE id='wof_ahead_legacy'")
            r.cancel_write_off("wof_ahead_legacy", "controller", "requested ahead of its date")
            self.assertEqual(r.write_off("wof_ahead_legacy")["status"], "cancelled")
            # reversing the stranded memo clears it: the reversed bill leaves nothing open
            c.ledger.prepare_reversal(memo_journal, "the prime bill it credited was reversed", "controller")
            c.approve_and_execute("journal.reverse", memo_journal, actor_role="controller", actor="controller", period_id="P1")
            ar = r.ar_open_items()
            self.assertEqual((ar["subledger_total"], ar["control_balance"], ar["reconciled"], ar["errors"]), ("54000.00", "54000.00", True, []))
            self.assertEqual((r.get(b["id"])["open"], c.ledger.balance("6100")), ("0.00", D("0.00")))
            self.assertTrue(c.ledger.trial_balance()["balanced"])
            self.assertTrue(c.audit.verify_chain()["ok"])
        finally:
            c.db.close()


if __name__ == "__main__":
    unittest.main()
