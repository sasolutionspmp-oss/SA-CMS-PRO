"""Receivables controls: prime contract and overbilling, sending as its own authority,
ACH debit mandates, prime retainage release and collection, reversals and cut-off, the
database guards behind them, upgrades of earlier workspaces, and the complete AR (1100)
and retainage receivable (1150) subledgers.  Synthetic data only."""
import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal as D
from unittest import mock

from apps.cipher.core import db as core_db
from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.money import MoneyError
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.domain.receivables import (
    CONTROLS_GUARDS_SCHEMA_NAME, CONTROLS_SCHEMA_NAME, DATES_CREDITS_GUARDS_SCHEMA_NAME, DATES_CREDITS_SCHEMA_NAME, ReceivableCutoffError, ReceivableError,
    ReceivableIneligible, ReceivableInputError, Receivables,
)
from apps.cipher.service import Cipher, RoleNotAuthorised, run_golden_fixture

ENTITY = "S&A Solutions LLC (synthetic)"
RAW_TIME = "2026-10-20T00:00:00Z"
RAW_SEND = ("INSERT INTO prime_bill_sends (id, prime_bill_id, approval_id, channel, recipients_json, bill_hash, message_hash, sent_at, sent_by) "
            "VALUES ('snd_raw', ?, ?, 'mail-sink', '[]', ?, 'h', '2026-10-12T00:00:00Z', 'raw')")
# a raw receipt records its settlement date (receivables_dates_credits): the invoice date of the
# bill it collects (the database's today for an undated draft), so it never settles before the
# invoice date, whenever the test runs (a run that spans midnight UTC included)
RAW_COLLECTION = ("INSERT INTO collections (id, prime_bill_id, amount, fee, status, journal_id, provider_ref, received_at, method, mandate_id, settlement_date) "
                  "VALUES (?1, ?2, ?3, '0.00', 'received', ?4, ?5, '2026-10-20T00:00:00Z', ?6, ?7, "
                  "COALESCE((SELECT b.invoice_date FROM prime_bills b WHERE b.id = ?2), date('now')))")
RAW_MANDATE = ("INSERT INTO customer_mandates (id, customer_id, mandate_ref, evidence_hash, evidence_revision_id, status, recorded_at, recorded_by) "
               "VALUES (?, ?, ?, ?, ?, 'active', ?, 'raw')")


def lines_of(journal):
    return [(ln["account_code"], ln["debit"], ln["credit"]) for ln in journal["lines"]]


def preview_of(manifest):
    return [(p["account"], p["debit"], p["credit"]) for p in manifest["bindings"]["journal_preview"]]


class World:
    """One synthetic customer and project (cofferdam, sheet piling and dewatering scope)
    with two open periods; optionally a prime contract."""

    def __init__(self, *, contract=None, rate="0.10", path=":memory:"):
        self.path = path
        c = self.c = Cipher(path)
        self.r = c.receivables
        self.customer = c.add_party(kind="customer", name="Synthetic Owner Agency (receivables)")
        self.cust = self.customer["id"]
        self.project = c.create_project(name="Synthetic cofferdam, sheet piling and dewatering", entity=ENTITY, budget="250000", customer_id=self.cust)
        self.pid = self.project["id"]
        c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        if contract:
            self.r.set_prime_contract(self.pid, contract, rate, actor="owner")

    def evidence_hash(self, content=b"synthetic ACH debit authorization", project_id=None):
        doc = self.c.evidence.register_document(project_id=project_id or self.pid, kind="ach_mandate", title="Customer ACH debit authorization (synthetic)", actor="owner")
        return self.c.evidence.add_revision(document_id=doc["id"], content=content, note="signed authorization", actor="owner")["content_hash"]

    def revision_id(self, content_hash):
        return self.c.db.one("SELECT id FROM document_revisions WHERE content_hash=?", (content_hash,))["id"]

    def mandate(self, ref="MANDATE-SIM-R-0001"):
        return self.r.record_mandate(self.cust, ref, self.evidence_hash(content=f"synthetic authorization {ref}".encode()), "owner")

    def reverse(self, journal_id, period="P1", reason="synthetic correction: certified against the wrong pay item"):
        """Reverse a posted journal through the governed journal.reverse approval."""
        self.c.ledger.prepare_reversal(journal_id, reason, "controller")
        return self.c.approve_and_execute("journal.reverse", journal_id, actor_role="controller", actor="controller", period_id=period).result

    def collection_journal(self, ref, amount, period="P1"):
        """A standing collection journal for a raw receipt row (Dr 1000 / Cr 1100)."""
        tags = {"project_id": self.pid, "party_id": self.cust}
        return self.c.ledger.post(period_id=period, description=f"raw receipt {ref} (synthetic)", source_type="collection", source_id=ref, source_version="1",
                                  posted_by="test", lines=[{"account": "1000", "debit": amount, **tags}, {"account": "1100", "credit": amount, **tags}])

    def reopen(self):
        self.c.db.close()
        self.c = Cipher(self.path)
        self.r = self.c.receivables

    def certify(self, certified, period="P1", project_id=None, **kw):
        return self.r.certify(project_id=project_id or self.pid, period_id=period, certified_cumulative=certified, actor="pm", **kw)

    def posted(self, certified, period="P1", project_id=None, **kw):
        b = self.certify(certified, period, project_id, **kw)
        self.c.approve_and_execute("prime_bill.approve", b["id"], actor_role="accountant", actor="accountant")
        return self.r.get(b["id"])

    def sent(self, certified, period="P1"):
        b = self.posted(certified, period)
        self.c.approve_and_execute("prime_bill.send", b["id"], actor_role="pm", actor="pm")
        return self.r.get(b["id"])

    def bal(self, code, **kw):
        return self.c.ledger.balance(code, **kw)

    def journal_count(self):
        return len(self.c.ledger.journals())

    def assert_books(self, tc):
        tc.assertTrue(self.c.ledger.trial_balance()["balanced"])
        tc.assertTrue(self.c.audit.verify_chain()["ok"])
        ar = self.r.ar_open_items()
        tc.assertTrue(ar["reconciled"], ar)
        ret = self.r.retainage_receivable_items()
        tc.assertTrue(ret["reconciled"], ret)


# --------------------------------------------------------------------------- #
# Prime contract and overbilling                                              #
# --------------------------------------------------------------------------- #

class PrimeContractTests(unittest.TestCase):
    def test_overbilling_refused_and_billing_up_to_the_contract_allowed(self):
        w = World(contract="100000")
        ct = w.r.contract(w.pid)
        self.assertEqual((ct["version"], ct["contract_value"], ct["retainage_rate"]), (1, "100000.00", "0.100000"))
        with self.assertRaises(ReceivableError) as cm:
            w.certify("100000.01")
        self.assertIn("overbilling", str(cm.exception))
        self.assertEqual(w.r.list(w.pid), [])

        b1 = w.posted("60000")
        self.assertEqual((b1["contract_version"], b1["status"], b1["amount_due"], b1["retainage_this_period"]), (1, "posted", "54000.00", "6000.00"))
        self.assertEqual(lines_of(w.c.ledger.journal(b1["journal_id"])), [("1100", "54000.00", "0.00"), ("1150", "6000.00", "0.00"), ("4000", "0.00", "60000.00")])
        b2 = w.certify("100000")  # exactly the contract value is allowed
        self.assertEqual((b2["sequence"], b2["amount_due"], b2["retainage_this_period"], b2["revenue_this_period"]), (2, "36000.00", "4000.00", "40000.00"))
        w.c.approve_and_execute("prime_bill.approve", b2["id"], actor_role="accountant", actor="accountant")
        self.assertEqual((w.bal("1100"), w.bal("1150"), w.bal("4000")), (D("90000.00"), D("10000.00"), D("100000.00")))
        with self.assertRaises(ReceivableError):  # a cent above the contract
            w.certify("100000.01")
        with self.assertRaises(ReceivableError):  # nothing new to bill
            w.certify("100000")
        self.assertEqual([b["sequence"] for b in w.r.list(w.pid)], [1, 2])
        w.assert_books(self)

    def test_contract_versions_are_immutable_and_inputs_validated(self):
        w = World()
        for kwargs in (dict(contract_value="0"), dict(contract_value="-1"), dict(contract_value=100000.0), dict(contract_value="abc"),
                       dict(contract_value="100000", retainage_rate="1.5"), dict(contract_value="100000", retainage_rate="-0.1"),
                       dict(contract_value="NaN"), dict(contract_value="100000", retainage_rate="Infinity")):
            with self.assertRaises(ReceivableInputError, msg=repr(kwargs)):
                w.r.set_prime_contract(w.pid, actor="owner", **kwargs)
        with self.assertRaises(ReceivableInputError):
            w.r.set_prime_contract(w.pid, "100000", "0.10")  # no actor
        with self.assertRaises(MoneyError):  # input errors are also money errors for generic callers
            w.r.set_prime_contract(w.pid, 100000.0, actor="owner")
        with self.assertRaises(ReceivableError):
            w.r.set_prime_contract("prj_missing", "100000", actor="owner")
        self.assertIsNone(w.r.contract(w.pid))

        w.r.set_prime_contract(w.pid, "100000", "0.10", "owner")
        with self.assertRaises(ReceivableError):  # duplicate terms
            w.r.set_prime_contract(w.pid, "100000.00", "0.100000", actor="owner")
        v2 = w.r.set_prime_contract(w.pid, "120000", "0.10", actor="owner")  # change order raises the contract
        self.assertEqual((v2["version"], v2["contract_value"]), (2, "120000.00"))
        self.assertEqual([c["version"] for c in w.r.contracts(w.pid)], [1, 2])
        w.posted("110000")
        with self.assertRaises(ReceivableError) as cm:  # the contract cannot fall below what is certified
            w.r.set_prime_contract(w.pid, "100000", "0.10", actor="owner")
        self.assertIn("overbilling", str(cm.exception))
        self.assertEqual(w.r.contract(w.pid)["version"], 2)
        with self.assertRaises(ReceivableError):  # the contract's rate governs certification
            w.certify("115000", retainage_rate="0.05")
        b = w.certify("115000", retainage_rate="0.10")
        self.assertEqual((b["retainage_rate"], b["contract_version"]), ("0.100000", 2))

        for sql in ("UPDATE prime_contracts SET contract_value='999999.00' WHERE project_id=?",
                    "DELETE FROM prime_contracts WHERE project_id=?",
                    "INSERT INTO prime_contracts (id, project_id, version, contract_value, retainage_rate, content_hash, created_at, created_by) "
                    "VALUES ('pct_raw', ?, 9, '1.00', '0.100000', 'h', '2026-10-12T00:00:00Z', 'raw')"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                w.c.db.execute(sql, (w.pid,))
        self.assertEqual(w.r.contract(w.pid)["contract_value"], "120000.00")
        self.assertEqual(len([e for e in w.c.audit.entries(entity_type="prime_contract") if e["action"] == "prime_contract.set"]), 2)
        w.assert_books(self)

    def test_retainage_reduction_under_a_new_contract_version_posts_exactly(self):
        w = World(contract="200000", rate="0.10")
        w.posted("100000")
        self.assertEqual(w.bal("1150"), D("10000.00"))
        w.r.set_prime_contract(w.pid, "200000", "0.05", actor="owner")
        b2 = w.certify("100000")  # certified unchanged; retainage reduced to 5%
        self.assertEqual((b2["retainage_rate"], b2["retainage_cumulative"], b2["retainage_this_period"], b2["amount_due"], b2["revenue_this_period"]),
                         ("0.050000", "5000.00", "-5000.00", "5000.00", "0.00"))
        ap = w.c.request_approval("prime_bill.approve", b2["id"], actor_role="accountant", requested_by="pm")
        self.assertEqual(preview_of(ap["manifest"]), [("1100", "5000.00", "0.00"), ("1150", "0.00", "5000.00")])
        w.c.approve(ap["id"], approver="controller", approver_role="controller")
        res = w.c.execute(ap["id"], actor="accountant")
        self.assertEqual(lines_of(w.c.ledger.journal(res.result["journal_id"])), [("1100", "5000.00", "0.00"), ("1150", "0.00", "5000.00")])
        self.assertEqual((w.bal("1100"), w.bal("1150"), w.bal("4000")), (D("95000.00"), D("5000.00"), D("100000.00")))
        ret = w.r.retainage_receivable_items(w.pid)
        self.assertEqual((ret["subledger_total"], ret["control_balance"], ret["reconciled"]), ("5000.00", "5000.00", True))
        # a value-only change order keeps the current rate (it never silently resets to 10%)
        v3 = w.r.set_prime_contract(w.pid, "210000", actor="owner")
        self.assertEqual((v3["version"], v3["contract_value"], v3["retainage_rate"]), (3, "210000.00", "0.050000"))
        with self.assertRaises(ReceivableError):
            w.certify("100000")  # nothing changed any more
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# prime_bill.approve                                                          #
# --------------------------------------------------------------------------- #

class PrimeBillApprovalTests(unittest.TestCase):
    def test_manifest_binds_contract_entity_currency_and_journal_preview(self):
        w = World(contract="150000")
        b = w.certify("60000")
        ap = w.c.request_approval("prime_bill.approve", b["id"], actor_role="accountant", requested_by="pm")
        m = ap["manifest"]
        self.assertEqual((m["entity"], m["currency"]), (ENTITY, "USD"))
        self.assertEqual(m["amounts"], {"amount_due": "54000.00", "revenue_this_period": "60000.00", "retainage_this_period": "6000.00", "certified_cumulative": "60000.00"})
        bd = m["bindings"]
        self.assertEqual((bd["contract_version"], bd["contract_value"], bd["bill_contract_version"], bd["bill_hash"]), (1, "150000.00", 1, b["content_hash"]))
        self.assertIn("SHADOW", bd["recognition_policy"])
        self.assertEqual(preview_of(m), [("1100", "54000.00", "0.00"), ("1150", "6000.00", "0.00"), ("4000", "0.00", "60000.00")])
        with self.assertRaises(RoleNotAuthorised):
            w.c.approve(ap["id"], approver="pm", approver_role="pm")
        w.c.approve(ap["id"], approver="controller", approver_role="controller")
        res = w.c.execute(ap["id"], actor="accountant")
        j = w.c.ledger.journal(res.result["journal_id"])
        self.assertEqual(lines_of(j), preview_of(m))
        self.assertEqual((j["approval_id"], j["period_id"]), (ap["id"], "P1"))
        with self.assertRaises(ReceivableError):  # a posted bill cannot be approved again
            w.c.request_approval("prime_bill.approve", b["id"], actor_role="accountant")
        w.assert_books(self)

    def test_contract_change_after_approval_makes_it_stale(self):
        w = World(contract="150000")
        b = w.certify("60000")
        ap = w.c.request_approval("prime_bill.approve", b["id"], actor_role="accountant")
        w.c.approve(ap["id"], approver="controller", approver_role="controller")
        w.r.set_prime_contract(w.pid, "180000", "0.10", actor="owner")
        self.assertTrue(w.r.get(b["id"])["contract_stale"])
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap["id"], actor="accountant")
        self.assertEqual(w.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(w.r.get(b["id"])["status"], "draft")
        self.assertEqual(w.c.ledger.journals(source_type="prime_bill"), [])
        with self.assertRaises(ReceivableIneligible):  # a fresh request is refused too: void and re-certify
            w.c.request_approval("prime_bill.approve", b["id"], actor_role="accountant")
        w.r.void(b["id"], actor="pm", reason="re-certify under contract version 2")
        b2 = w.posted("60000")
        self.assertEqual((b2["sequence"], b2["contract_version"], b2["status"]), (2, 2, "posted"))
        w.assert_books(self)

    def test_void_invalidates_open_approvals_and_bills_are_guarded(self):
        w = World()
        b = w.certify("10000")
        ap = w.c.request_approval("prime_bill.approve", b["id"], actor_role="accountant")
        w.c.approve(ap["id"], approver="controller", approver_role="controller")
        self.assertEqual(w.r.void(b["id"], actor="pm", reason="certified in the wrong period")["status"], "void")
        self.assertEqual(w.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises((ApprovalNotGranted, StaleApprovalError)):
            w.c.execute(ap["id"], actor="accountant")
        self.assertEqual((w.c.approvals.get(ap["id"])["status"], w.journal_count()), ("invalidated", 0))
        with self.assertRaises(ReceivableError):
            w.r.void(b["id"], actor="pm", reason="again")
        posted = w.posted("10000")
        self.assertEqual(posted["sequence"], 2)  # the voided number is never reused
        with self.assertRaises(ReceivableError):
            w.r.void(posted["id"], actor="pm", reason="posted bills are reversed, not voided")
        for sql, bid in (("UPDATE prime_bills SET status='draft' WHERE id=?", b["id"]),
                         ("UPDATE prime_bills SET amount_due='1.00' WHERE id=?", posted["id"]),
                         ("UPDATE prime_bills SET journal_id=NULL WHERE id=?", posted["id"]),
                         ("DELETE FROM prime_bills WHERE id=?", posted["id"])):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                w.c.db.execute(sql, (bid,))
        self.assertEqual(w.r.get(posted["id"])["amount_due"], "9000.00")
        w.assert_books(self)

    def test_closed_period_refuses_certification_and_posting(self):
        w = World()
        b = w.certify("10000")
        ap = w.c.request_approval("prime_bill.approve", b["id"], actor_role="accountant")
        w.c.approve(ap["id"], approver="controller", approver_role="controller")
        w.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            w.c.execute(ap["id"], actor="accountant")
        self.assertEqual((w.r.get(b["id"])["status"], w.journal_count()), ("draft", 0))
        with self.assertRaises(PeriodNotOpen):
            w.certify("20000", period="P1")
        w.assert_books(self)

    def test_certification_inputs_are_validated(self):
        w = World()
        for bad in ("-1", 10000.0, "", "abc", "NaN"):
            with self.assertRaises(ReceivableInputError, msg=repr(bad)):
                w.certify(bad)
        with self.assertRaises(ReceivableError):
            w.certify("0")  # nothing to bill
        with self.assertRaises(ReceivableInputError):
            w.r.certify(project_id=w.pid, period_id="P1", certified_cumulative="1000", actor=" ")
        orphan = w.c.create_project(name="No customer", entity=ENTITY, budget="1")
        with self.assertRaises(ReceivableError):
            w.r.certify(project_id=orphan["id"], period_id="P1", certified_cumulative="1000", actor="pm")
        w.certify("1000")
        with self.assertRaises(ReceivableError):  # the previous bill is still a draft
            w.certify("2000")
        self.assertEqual(w.journal_count(), 0)


# --------------------------------------------------------------------------- #
# prime_bill.send                                                             #
# --------------------------------------------------------------------------- #

class SendingTests(unittest.TestCase):
    def test_send_only_through_its_own_approval(self):
        w = World()
        draft = w.certify("60000")
        with self.assertRaises(ReceivableError):  # only a posted bill can be sent
            w.c.request_approval("prime_bill.send", draft["id"], actor_role="pm")
        w.c.approve_and_execute("prime_bill.approve", draft["id"], actor_role="accountant", actor="accountant")
        b = w.r.get(draft["id"])
        for call in (lambda: w.r.send(b["id"], actor="pm"), lambda: w.r.send(b["id"], "pm"), lambda: w.r.send(b["id"])):
            with self.assertRaises(ReceivableError) as cm:  # every call shape is refused the same way
                call()
            self.assertIn("prime_bill.send", str(cm.exception))
        self.assertEqual(w.r.get(b["id"])["status"], "posted")
        self.assertEqual([e for e in w.c.audit.entries(entity_type="prime_bill", entity_id=b["id"]) if e["action"] == "prime_bill.sent"], [])

        with self.assertRaises(RoleNotAuthorised):
            w.c.request_approval("prime_bill.send", b["id"], actor_role="estimator")
        ap = w.c.request_approval("prime_bill.send", b["id"], actor_role="pm", requested_by="pm")
        m = ap["manifest"]
        self.assertEqual((m["operation"], m["subject"], m["entity"], m["currency"], m["amounts"]),
                         ("prime_bill.send", {"type": "prime_bill", "id": b["id"]}, ENTITY, "USD", {"amount_due": "54000.00"}))
        bd = m["bindings"]
        self.assertEqual((bd["channel"], bd["recipients"], bd["recipients_version"], bd["bill_hash"], bd["customer_id"], bd["journal_id"]),
                         ("mail-sink", [f"mail-sink:{w.cust}"], 0, b["content_hash"], w.cust, b["journal_id"]))
        # the invoice states the balance due and everything already taken off it
        self.assertEqual((bd["balance_due"], bd["received"], bd["credited_by_memo"], bd["written_off"], bd["deposits_applied"]),
                         ("54000.00", "0.00", "0.00", "0.00", "0.00"))
        with self.assertRaises(RoleNotAuthorised):
            w.c.approve(ap["id"], approver="estimator", approver_role="estimator")
        w.c.approve(ap["id"], approver="owner")
        # the database refuses a raw send of this posted bill without its consumed send approval:
        # none, the granted (unconsumed) one, or the bill's consumed approval of another operation
        for approval_id, bill_hash, needle in ((None, b["content_hash"], "consumed prime_bill.send approval"),
                                               (ap["id"], b["content_hash"], "consumed prime_bill.send approval"),
                                               (b["approval_id"], b["content_hash"], "consumed prime_bill.send approval"),
                                               (ap["id"], "0" * 64, "hash of the bill it delivers")):
            with self.assertRaisesRegex(sqlite3.DatabaseError, needle, msg=approval_id):
                w.c.db.execute(RAW_SEND, (b["id"], approval_id, bill_hash))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "only through a recorded prime_bill.send"):
            w.c.db.execute("UPDATE prime_bills SET status='sent' WHERE id=?", (b["id"],))
        journals = w.journal_count()
        res = w.c.execute(ap["id"], actor="pm")
        self.assertEqual((res.result["status"], res.result["channel"], res.result["recipients"]), ("sent", "mail-sink", [f"mail-sink:{w.cust}"]))
        self.assertTrue(w.c.execute(ap["id"], actor="pm").replayed)
        self.assertEqual(w.journal_count(), journals)  # sending posts nothing
        sent = w.r.get(b["id"])
        self.assertEqual((sent["status"], sent["send"]["approval_id"], sent["send"]["channel"], sent["send"]["bill_hash"]), ("sent", ap["id"], "mail-sink", b["content_hash"]))
        events = [e for e in w.c.audit.entries(entity_type="prime_bill", entity_id=b["id"]) if e["action"] == "prime_bill.sent"]
        self.assertEqual(len(events), 1)
        with self.assertRaises(ReceivableError):  # never sent twice
            w.c.request_approval("prime_bill.send", b["id"], actor_role="pm")
        for sql, params, needle in (("UPDATE prime_bill_sends SET channel='smtp' WHERE prime_bill_id=?", (b["id"],), "sent records are immutable"),
                                    ("DELETE FROM prime_bill_sends WHERE prime_bill_id=?", (b["id"],), "sent records are immutable"),
                                    (RAW_SEND, (b["id"], ap["id"], b["content_hash"]), "only a posted prime bill can be sent")):
            with self.assertRaisesRegex(sqlite3.DatabaseError, needle, msg=sql):
                w.c.db.execute(sql, params)
        w.assert_books(self)

    def test_recipient_change_after_approval_is_stale(self):
        w = World()
        b = w.posted("60000")
        ap = w.c.request_approval("prime_bill.send", b["id"], actor_role="accountant", requested_by="pm")
        w.c.approve(ap["id"], approver="owner")
        new = ["ap@owner-agency.example", "pm@owner-agency.example"]
        self.assertEqual(w.r.set_billing_recipients(w.cust, new, actor="owner")["version"], 1)
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap["id"], actor="accountant")
        self.assertEqual(w.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual((w.r.get(b["id"])["status"], w.r.get(b["id"])["send"]), ("posted", None))
        ap2 = w.c.request_approval("prime_bill.send", b["id"], actor_role="accountant")
        self.assertEqual((ap2["manifest"]["bindings"]["recipients"], ap2["manifest"]["bindings"]["recipients_version"]), (new, 1))
        w.c.approve(ap2["id"], approver="owner")
        w.c.execute(ap2["id"], actor="accountant")
        self.assertEqual(w.r.get(b["id"])["send"]["recipients"], new)

        supplier = w.c.add_party(kind="supplier", name="Synthetic sheet piling subcontractor")
        for bad in ([], ["not an address"], ["a@owner.example", "A@OWNER.example"], "ap@owner.example", [None]):
            with self.assertRaises(ReceivableInputError, msg=repr(bad)):
                w.r.set_billing_recipients(w.cust, bad, actor="owner")
        with self.assertRaises(ReceivableError):  # unchanged
            w.r.set_billing_recipients(w.cust, [a.upper() for a in new], actor="owner")
        with self.assertRaises(ReceivableError):
            w.r.set_billing_recipients(supplier["id"], new, actor="owner")
        with self.assertRaises(ReceivableError):
            w.r.set_billing_recipients("pty_missing", new, actor="owner")
        w.assert_books(self)

    def test_a_receipt_after_send_approval_makes_the_send_stale(self):
        """The delivered invoice states the balance due; a receipt between approval and
        execution changes it, so the approval goes stale and nothing is delivered."""
        w = World()
        b = w.posted("60000")
        ap = w.c.request_approval("prime_bill.send", b["id"], actor_role="pm", requested_by="pm")
        self.assertEqual(ap["manifest"]["bindings"]["balance_due"], "54000.00")
        w.c.approve(ap["id"], approver="owner")
        w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="4000", provider_ref="CHK-SEND-STALE", actor="treasury", method="check")
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap["id"], actor="pm")
        self.assertEqual((w.c.approvals.get(ap["id"])["status"], w.r.get(b["id"])["send"]), ("invalidated", None))
        self.assertEqual(w.c.db.one("SELECT COUNT(*) AS n FROM prime_bill_sends")["n"], 0)
        ap2 = w.c.request_approval("prime_bill.send", b["id"], actor_role="pm", requested_by="pm")
        self.assertEqual((ap2["manifest"]["bindings"]["balance_due"], ap2["manifest"]["bindings"]["received"], ap2["manifest"]["amounts"]),
                         ("50000.00", "4000.00", {"amount_due": "54000.00"}))
        self.assertNotEqual(ap2["manifest"]["bindings"]["message_hash"], ap["manifest"]["bindings"]["message_hash"])
        w.c.approve(ap2["id"], approver="owner")
        res = w.c.execute(ap2["id"], actor="pm").result
        sent = w.r.get(b["id"])
        self.assertEqual((res["status"], sent["status"], sent["send"]["message_hash"]), ("sent", "sent", ap2["manifest"]["bindings"]["message_hash"]))
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# ACH mandates and collections                                                #
# --------------------------------------------------------------------------- #

class MandateTests(unittest.TestCase):
    def test_ach_collection_needs_an_active_mandate_check_and_wire_need_none(self):
        w = World()
        b = w.sent("60000")
        before = w.journal_count()
        for kwargs in ({}, {"method": "ach"}, {"method": "ACH"}):
            with self.assertRaises(ReceivableError) as cm:
                w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="20000", fee="5", provider_ref="ach_sim_rcv_r001", actor="treasury", **kwargs)
            self.assertIn("missing mandate", str(cm.exception))
        self.assertEqual((w.journal_count(), w.r.get(b["id"])["collections"]), (before, []))

        m = w.mandate("MANDATE-SIM-R-0001")
        self.assertEqual((m["status"], m["customer_id"]), ("active", w.cust))
        col = w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="20000", fee="5", provider_ref="ach_sim_rcv_r001", actor="treasury")
        self.assertEqual((col["amount"], col["fee"], col["method"], col["mandate_id"], col["status"]), ("20000.00", "5.00", "ach", m["id"], "received"))
        self.assertEqual(lines_of(w.c.ledger.journal(col["journal_id"])), [("1000", "19995.00", "0.00"), ("6000", "5.00", "0.00"), ("1100", "0.00", "20000.00")])

        revoked = w.r.revoke_mandate(w.cust, "MANDATE-SIM-R-0001", "owner", reason="customer withdrew the authorization")
        self.assertEqual((revoked["status"], revoked["revoked_by"]), ("revoked", "owner"))
        with self.assertRaises(ReceivableError) as cm:
            w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="10000", fee="0", provider_ref="ach_sim_rcv_r002", actor="treasury")
        self.assertIn("missing mandate", str(cm.exception))
        with self.assertRaises(ReceivableError):
            w.r.revoke_mandate(w.cust, "MANDATE-SIM-R-0001", "owner")

        chk = w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="10000", fee="0", provider_ref="CHK-0001", actor="treasury", method="check")
        self.assertEqual((chk["method"], chk["mandate_id"]), ("check", None))
        self.assertEqual(lines_of(w.c.ledger.journal(chk["journal_id"])), [("1000", "10000.00", "0.00"), ("1100", "0.00", "10000.00")])
        self.assertEqual(w.r.get(b["id"])["status"], "sent")
        wire = w.r.record_collection(prime_bill_id=b["id"], period_id="P2", amount="24000", fee="15", provider_ref="WIRE-0001", actor="treasury", method="wire")
        self.assertEqual(lines_of(w.c.ledger.journal(wire["journal_id"])), [("1000", "23985.00", "0.00"), ("6000", "15.00", "0.00"), ("1100", "0.00", "24000.00")])
        self.assertEqual(w.r.get(b["id"])["status"], "collected")
        self.assertEqual((w.bal("1000"), w.bal("6000"), w.bal("1100")), (D("53980.00"), D("20.00"), D("0.00")))
        ar = w.r.ar_open_items(w.pid)
        self.assertEqual((ar["subledger_total"], ar["control_balance"], ar["reconciled"]), ("0.00", "0.00", True))
        w.assert_books(self)

    def test_mandate_needs_owned_evidence_and_is_never_duplicated(self):
        w = World()
        with self.assertRaises(ReceivableError) as cm:
            w.r.record_mandate(w.cust, "M-1", "0" * 64, "owner")
        self.assertIn("evidence", str(cm.exception))
        other = w.c.add_party(kind="customer", name="Another synthetic owner")
        other_prj = w.c.create_project(name="Other synthetic project", entity=ENTITY, budget="1000", customer_id=other["id"])
        foreign = w.evidence_hash(content=b"another customer's authorization", project_id=other_prj["id"])
        with self.assertRaises(ReceivableError):  # evidence filed for another customer
            w.r.record_mandate(w.cust, "M-1", foreign, "owner")
        supplier = w.c.add_party(kind="supplier", name="Synthetic dewatering supplier")
        h = w.evidence_hash()
        with self.assertRaises(ReceivableError):
            w.r.record_mandate(supplier["id"], "M-1", h, "owner")
        for args in ((w.cust, " ", h, "owner"), (w.cust, "M-1", "", "owner"), (w.cust, "M-1", h, "")):
            with self.assertRaises(ReceivableInputError, msg=repr(args)):
                w.r.record_mandate(*args)
        self.assertEqual(w.r.mandates(), [])

        m = w.r.record_mandate(customer_id=w.cust, mandate_ref="M-1", evidence_hash=h, actor="owner")
        self.assertEqual((m["mandate_ref"], m["evidence_hash"], m["status"]), ("M-1", h, "active"))
        with self.assertRaises(ReceivableError):  # references are unique, ignoring case
            w.r.record_mandate(w.cust, "m-1", h, "owner")
        with self.assertRaises(ReceivableError):
            w.r.revoke_mandate(other["id"], "M-1", "owner")
        with self.assertRaises(ReceivableError):
            w.r.revoke_mandate(w.cust, "M-404", "owner")
        for sql in ("UPDATE customer_mandates SET mandate_ref='M-2' WHERE id=?", "UPDATE customer_mandates SET status='revoked' WHERE id=?",
                    "DELETE FROM customer_mandates WHERE id=?"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                w.c.db.execute(sql, (m["id"],))
        w.r.revoke_mandate(w.cust, "m-1", "owner", reason="superseded")
        with self.assertRaises(sqlite3.DatabaseError):  # a revoked mandate never becomes active again
            w.c.db.execute("UPDATE customer_mandates SET status='active', revoked_at=NULL, revoked_by=NULL WHERE id=?", (m["id"],))
        actions = [e["action"] for e in w.c.audit.entries(entity_type="customer_mandate", entity_id=m["id"])]
        self.assertEqual(actions, ["mandate.recorded", "mandate.revoked"])
        w.assert_books(self)

    def test_named_mandate_and_database_enforcement(self):
        w = World()
        b = w.posted("60000")
        w.mandate("M-ACTIVE")
        w.mandate("M-OLD")
        w.r.revoke_mandate(w.cust, "M-OLD", "owner")
        with self.assertRaises(ReceivableError) as cm:
            w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="1000", provider_ref="ach_sim_rcv_n1", actor="treasury", mandate_ref="M-OLD")
        self.assertIn("missing mandate", str(cm.exception))
        with self.assertRaises(ReceivableInputError):
            w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="1000", provider_ref="CHK-n1", actor="treasury", method="check", mandate_ref="M-ACTIVE")
        col = w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="1000", provider_ref="ach_sim_rcv_n2", actor="treasury", mandate_ref="m-active")
        active_id = w.r.mandate("M-ACTIVE")["id"]
        self.assertEqual(col["mandate_id"], active_id)
        for cid, ref, method, mandate, needle in (("col_raw1", "RAW-1", "ach", None, "missing mandate"),
                                                  ("col_raw2", "RAW-2", "ach", w.r.mandate("M-OLD")["id"], "missing mandate"),
                                                  ("col_raw3", "RAW-3", None, None, "method must be ach, check or wire"),
                                                  ("col_raw4", "ach_sim_rcv_N2", "check", None, "recorded once, ignoring case"),
                                                  ("col_raw5", "RAW-5", "check", None, "its own collection journal")):
            with self.assertRaisesRegex(sqlite3.DatabaseError, needle, msg=cid):
                w.c.db.execute(RAW_COLLECTION, (cid, b["id"], "1.00", None, ref, method, mandate))
        # positive control: a raw ACH receipt under the active mandate, citing its own collection
        # journal, is accepted (the triggers refuse what is wrong, not every raw insert)
        j = w.collection_journal("RAW-OK", "1.00")
        w.c.db.execute(RAW_COLLECTION, ("col_raw_ok", b["id"], "1.00", j["id"], "RAW-OK", "ach", active_id))
        self.assertEqual(sorted(c["provider_ref"] for c in w.r.get(b["id"])["collections"]), ["RAW-OK", "ach_sim_rcv_n2"])
        self.assertEqual(w.r.get(b["id"])["open"], "52999.00")
        for sql in ("UPDATE collections SET amount='1.00' WHERE id=?", "DELETE FROM collections WHERE id=?"):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "collection", msg=sql):
                w.c.db.execute(sql, (col["id"],))
        w.assert_books(self)

    def test_mandate_rows_need_owned_evidence_in_the_database(self):
        w = World()
        b = w.posted("60000")
        h = w.evidence_hash(content=b"synthetic ACH debit authorization (raw path)")
        rev = w.revision_id(h)
        other = w.c.add_party(kind="customer", name="Another synthetic owner (raw)")
        other_prj = w.c.create_project(name="Other synthetic dewatering project", entity=ENTITY, budget="1000", customer_id=other["id"])
        foreign_h = w.evidence_hash(content=b"another customer's ACH authorization (raw path)", project_id=other_prj["id"])
        foreign_rev = w.revision_id(foreign_h)
        for mid, ev_hash, ev_rev in (("mdt_raw1", "bogus", rev),            # not the revision's content hash
                                     ("mdt_raw2", foreign_h, foreign_rev),  # evidence filed for another customer
                                     ("mdt_raw3", foreign_h, rev)):         # the hash of a different revision
            with self.assertRaisesRegex(sqlite3.DatabaseError, "content hash of its evidence revision", msg=mid):
                w.c.db.execute(RAW_MANDATE, (mid, w.cust, f"RAW-{mid}", ev_hash, ev_rev, RAW_TIME))
        self.assertEqual(w.r.mandates(), [])
        # positive control: a raw row backed by owned evidence is accepted and authorises ACH
        w.c.db.execute(RAW_MANDATE, ("mdt_raw_ok", w.cust, "RAW-OK", h, rev, RAW_TIME))
        self.assertEqual((w.r.active_mandate(w.cust)["id"], w.r.unbacked_mandates()), ("mdt_raw_ok", []))
        col = w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="1000", provider_ref="ach_sim_rcv_raw_ok", actor="treasury", mandate_ref="raw-ok")
        self.assertEqual(col["mandate_id"], "mdt_raw_ok")
        w.assert_books(self)

    def test_mandate_forged_before_the_evidence_guard_never_authorises_ach(self):
        """A workspace written before receivables_controls_guards may hold a mandate row
        written outside record_mandate with no owned evidence; after the upgrade it is
        reported and never used, in Python or by the database."""
        path = os.path.join(tempfile.mkdtemp(), "mandate-upgrade.sqlite")
        legacy = [e for e in core_db.SCHEMA_CATALOG if e[1] != CONTROLS_GUARDS_SCHEMA_NAME]
        with mock.patch.object(core_db, "SCHEMA_CATALOG", legacy):
            w = World(path=path)
            real = w.mandate("M-REAL")
            other = w.c.add_party(kind="customer", name="Another synthetic owner (forgery)")
            other_prj = w.c.create_project(name="Other synthetic cofferdam", entity=ENTITY, budget="1000", customer_id=other["id"])
            foreign_rev = w.revision_id(w.evidence_hash(content=b"another customer's authorization (forgery)", project_id=other_prj["id"]))
            # recorded later than the real mandate, so an unguarded "latest active" lookup would pick it
            w.c.db.execute(RAW_MANDATE, ("mdt_forged", w.cust, "M-FORGED", "bogus", foreign_rev, "2099-01-01T00:00:00Z"))
        w.reopen()
        try:
            self.assertEqual(w.c.db.schema_status()["pending"], [])
            self.assertEqual([m["mandate_ref"] for m in w.r.unbacked_mandates()], ["M-FORGED"])
            self.assertEqual([m["mandate_ref"] for m in w.r.audit_export()["unbacked_mandates"]], ["M-FORGED"])
            self.assertEqual(w.r.active_mandate(w.cust)["id"], real["id"])
            self.assertIsNone(w.r.active_mandate(w.cust, "M-FORGED"))
            b = w.posted("60000")
            with self.assertRaisesRegex(ReceivableError, "missing mandate"):
                w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="1000", provider_ref="ach_sim_rcv_f1", actor="treasury", mandate_ref="M-FORGED")
            with self.assertRaisesRegex(sqlite3.DatabaseError, "missing mandate"):
                with w.c.db.transaction():  # the receipt's own journal is rolled back with the refused row
                    j = w.collection_journal("RAW-FORGED", "1.00")
                    w.c.db.execute(RAW_COLLECTION, ("col_forged", b["id"], "1.00", j["id"], "RAW-FORGED", "ach", "mdt_forged"))
            with self.assertRaisesRegex(sqlite3.DatabaseError, "content hash of its evidence revision"):
                w.c.db.execute(RAW_MANDATE, ("mdt_forged2", w.cust, "M-FORGED-2", "bogus", foreign_rev, RAW_TIME))
            col = w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="1000", provider_ref="ach_sim_rcv_f2", actor="treasury")
            self.assertEqual(col["mandate_id"], real["id"])
            w.assert_books(self)
        finally:
            w.c.db.close()

    def test_collection_inputs_duplicates_and_periods(self):
        w = World()
        b = w.posted("60000")
        draft_prj = w.c.create_project(name="Second synthetic project", entity=ENTITY, budget="1000", customer_id=w.cust)
        draft = w.certify("500", project_id=draft_prj["id"])
        base = dict(prime_bill_id=b["id"], period_id="P1", amount="1000", fee="0", provider_ref="CHK-V1", actor="treasury", method="check")
        before = w.journal_count()
        bad_inputs = [
            dict(method="card"), dict(method=None), dict(amount="0"), dict(amount=1000.0), dict(amount="-5"), dict(fee="-1"), dict(fee="1000"),
            dict(provider_ref="  "), dict(actor=""), dict(prime_bill_id=None), dict(retainage_invoice_id="rti_missing"),
        ]
        for change in bad_inputs:
            with self.assertRaises(ReceivableInputError, msg=repr(change)):
                w.r.record_collection(**{**base, **change})
        for change in (dict(prime_bill_id="pbl_missing"), dict(prime_bill_id=draft["id"]), dict(amount="54000.01")):
            with self.assertRaises(ReceivableError, msg=repr(change)):
                w.r.record_collection(**{**base, **change})
        self.assertEqual(w.journal_count(), before)
        w.r.record_collection(**base)
        with self.assertRaises(ReceivableError):  # a receipt is booked once, whatever the case of its reference
            w.r.record_collection(**{**base, "provider_ref": "chk-v1"})
        w.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            w.r.record_collection(**{**base, "provider_ref": "CHK-V2"})
        self.assertEqual(w.r.get(b["id"])["status"], "posted")
        self.assertEqual(w.r.ar_open_items(w.pid)["subledger_total"], "53000.00")
        w.assert_books(self)

    def test_late_return_restores_the_receivable_and_status(self):
        w = World()
        b = w.posted("60000")  # posted, never sent
        w.mandate()
        col = w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="54000", fee="5", provider_ref="ach_sim_rcv_l1", actor="treasury")
        self.assertEqual(w.r.get(b["id"])["status"], "collected")
        w.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            w.r.record_return(collection_id=col["id"], period_id="P1", reason="R01 (simulated)", actor="treasury")
        ret = w.r.record_return(collection_id=col["id"], period_id="P2", reason="R01 (simulated)", actor="treasury")
        self.assertEqual((ret["status"], ret["journal_id"]), ("returned", col["journal_id"]))
        rj = w.c.ledger.journal(ret["return_journal_id"])
        self.assertEqual((rj["period_id"], lines_of(rj)), ("P2", [("1100", "54000.00", "0.00"), ("1000", "0.00", "54000.00")]))
        self.assertEqual(w.r.get(b["id"])["status"], "posted")  # it was never sent
        with self.assertRaises(ReceivableError):
            w.r.record_return(collection_id=col["id"], period_id="P2", reason="again", actor="treasury")
        with self.assertRaises(ReceivableError):
            w.r.record_return(collection_id="col_missing", period_id="P2", reason="x", actor="treasury")
        self.assertEqual((w.bal("1000"), w.bal("1100"), w.bal("6000")), (D("-5.00"), D("54000.00"), D("5.00")))
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# prime_retainage.release                                                     #
# --------------------------------------------------------------------------- #

class PrimeRetainageTests(unittest.TestCase):
    def test_release_and_collect_prime_retainage_with_exact_journals(self):
        w = World(contract="100000")
        w.sent("60000")
        w.posted("100000")
        self.assertEqual(w.bal("1150"), D("10000.00"))
        ret = w.r.retainage_receivable_items(w.pid)
        self.assertEqual((ret["subledger_total"], ret["control_balance"], ret["reconciled"]), ("10000.00", "10000.00", True))
        self.assertEqual({k: ret["items"][0][k] for k in ("retained", "released", "open", "through_sequence")},
                         {"retained": "10000.00", "released": "0.00", "open": "10000.00", "through_sequence": 2})

        with self.assertRaises(RoleNotAuthorised):
            w.c.request_approval("prime_retainage.release", w.pid, actor_role="pm")
        ap = w.c.request_approval("prime_retainage.release", w.pid, actor_role="accountant", requested_by="accountant")
        m = ap["manifest"]
        self.assertEqual((m["operation"], m["subject"], m["entity"], m["currency"], m["amounts"]),
                         ("prime_retainage.release", {"type": "project", "id": w.pid}, ENTITY, "USD", {"retainage_receivable": "10000.00"}))
        bd = m["bindings"]
        self.assertEqual((bd["contract_version"], bd["contract_value"], bd["latest_prime_bill_sequence"], bd["certified_cumulative"], bd["released_to_date"], bd["customer_id"]),
                         (1, "100000.00", 2, "100000.00", "0.00", w.cust))
        self.assertEqual(preview_of(m), [("1100", "10000.00", "0.00"), ("1150", "0.00", "10000.00")])
        with self.assertRaises(RoleNotAuthorised):
            w.c.approve(ap["id"], approver="pm", approver_role="pm")
        w.c.approve(ap["id"], approver="controller", approver_role="controller")
        res = w.c.execute(ap["id"], actor="accountant", period_id="P2")
        j = w.c.ledger.journal(res.result["journal_id"])
        self.assertEqual(lines_of(j), [("1100", "10000.00", "0.00"), ("1150", "0.00", "10000.00")])
        self.assertEqual((j["period_id"], j["approval_id"], j["source_type"], j["source_id"]), ("P2", ap["id"], "prime_retainage_release", res.result["retainage_invoice"]))
        inv = w.r.retainage_invoice(res.result["retainage_invoice"])
        self.assertEqual({k: inv[k] for k in ("status", "amount", "sequence", "through_prime_bill_sequence", "contract_version", "open", "period_id")},
                         {"status": "open", "amount": "10000.00", "sequence": 1, "through_prime_bill_sequence": 2, "contract_version": 1, "open": "10000.00", "period_id": "P2"})
        self.assertEqual((w.bal("1150"), w.bal("1100")), (D("0.00"), D("100000.00")))
        ret = w.r.retainage_receivable_items(w.pid)
        self.assertEqual((ret["items"][0]["released"], ret["subledger_total"], ret["reconciled"]), ("10000.00", "0.00", True))
        ar = w.r.ar_open_items(w.pid)
        self.assertEqual((ar["subledger_total"], ar["control_balance"], ar["reconciled"]), ("100000.00", "100000.00", True))
        self.assertEqual([(i["source"], i["open"]) for i in ar["items"] if i["source"] == "prime_retainage_invoice"], [("prime_retainage_invoice", "10000.00")])
        with self.assertRaises(ReceivableError):  # nothing left to release
            w.c.request_approval("prime_retainage.release", w.pid, actor_role="accountant")

        # collected like a prime bill (a wire needs no mandate); duplicates refused across receipt tables
        col = w.r.record_collection(retainage_invoice_id=inv["id"], period_id="P2", amount="10000", fee="0", provider_ref="WIRE-RET-0001", actor="treasury", method="wire")
        self.assertEqual((col["retainage_invoice_id"], col["method"], col["status"]), (inv["id"], "wire", "received"))
        self.assertEqual(lines_of(w.c.ledger.journal(col["journal_id"])), [("1000", "10000.00", "0.00"), ("1100", "0.00", "10000.00")])
        self.assertEqual((w.r.retainage_invoice(inv["id"])["status"], w.r.retainage_invoice(inv["id"])["open"]), ("collected", "0.00"))
        with self.assertRaises(ReceivableError):
            w.r.record_collection(retainage_invoice_id=inv["id"], period_id="P2", amount="1", fee="0", provider_ref="WIRE-RET-0002", actor="treasury", method="wire")
        with self.assertRaises(ReceivableError):
            w.r.record_collection(prime_bill_id=w.r.list(w.pid)[1]["id"], period_id="P2", amount="1", fee="0", provider_ref="wire-ret-0001", actor="treasury", method="check")
        with self.assertRaises(ReceivableInputError):
            w.r.record_collection(prime_bill_id=w.r.list(w.pid)[1]["id"], retainage_invoice_id=inv["id"], period_id="P2", amount="1", provider_ref="X-1", actor="treasury", method="check")
        # the wire is recalled: the receivable and the invoice reopen, the receipt stays
        returned = w.r.record_return(collection_id=col["id"], period_id="P2", reason="recalled wire (simulated)", actor="treasury")
        self.assertEqual((returned["status"], returned["journal_id"]), ("returned", col["journal_id"]))
        self.assertEqual(lines_of(w.c.ledger.journal(returned["return_journal_id"])), [("1100", "10000.00", "0.00"), ("1000", "0.00", "10000.00")])
        self.assertEqual(w.r.retainage_invoice(inv["id"])["status"], "open")
        with self.assertRaises(ReceivableError) as cm:  # ACH on a retainage invoice needs the mandate too
            w.r.record_collection(retainage_invoice_id=inv["id"], period_id="P2", amount="10000", fee="0", provider_ref="ach_sim_rcv_ret1", actor="treasury")
        self.assertIn("missing mandate", str(cm.exception))
        w.mandate()
        again = w.r.record_collection(retainage_invoice_id=inv["id"], period_id="P2", amount="10000", fee="0", provider_ref="ach_sim_rcv_ret1", actor="treasury")
        self.assertEqual((again["method"], w.r.retainage_invoice(inv["id"])["status"]), ("ach", "collected"))
        for sql in ("UPDATE prime_retainage_invoices SET amount='1.00' WHERE id=?", "DELETE FROM prime_retainage_invoices WHERE id=?"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                w.c.db.execute(sql, (inv["id"],))
        w.assert_books(self)

    def test_release_goes_stale_after_a_new_prime_bill_or_a_contract_change(self):
        w = World(contract="200000")
        w.posted("100000")
        ap1 = w.c.request_approval("prime_retainage.release", w.pid, actor_role="controller")
        w.c.approve(ap1["id"], approver="owner")
        w.posted("150000")  # a later prime bill changes the retainage receivable and the latest sequence
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap1["id"], actor="controller", period_id="P1")
        self.assertEqual(w.c.approvals.get(ap1["id"])["status"], "invalidated")
        self.assertEqual(w.c.ledger.journals(source_type="prime_retainage_release"), [])

        ap2 = w.c.request_approval("prime_retainage.release", w.pid, actor_role="controller")
        self.assertEqual((ap2["manifest"]["amounts"]["retainage_receivable"], ap2["manifest"]["bindings"]["latest_prime_bill_sequence"]), ("15000.00", 2))
        w.c.approve(ap2["id"], approver="owner")
        w.r.set_prime_contract(w.pid, "250000", "0.10", actor="owner")
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap2["id"], actor="controller", period_id="P1")
        self.assertEqual(w.c.approvals.get(ap2["id"])["status"], "invalidated")

        ap3 = w.c.request_approval("prime_retainage.release", w.pid, actor_role="controller")
        w.c.approve(ap3["id"], approver="owner")
        draft = w.certify("160000")  # a draft progress bill pending: the granted release goes stale
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap3["id"], actor="controller", period_id="P1")
        with self.assertRaises(ReceivableError):
            w.c.request_approval("prime_retainage.release", w.pid, actor_role="controller")
        w.r.void(draft["id"], actor="pm", reason="final bill deferred")

        ap4 = w.c.request_approval("prime_retainage.release", w.pid, actor_role="controller")
        w.c.approve(ap4["id"], approver="owner")
        w.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):  # never into a closed period; the approval survives the refusal
            w.c.execute(ap4["id"], actor="controller", period_id="P1")
        self.assertEqual((w.c.approvals.get(ap4["id"])["status"], w.bal("1150")), ("granted", D("15000.00")))
        res = w.c.execute(ap4["id"], actor="controller", period_id="P2")
        self.assertEqual((res.result["amount"], res.result["period_id"]), ("15000.00", "P2"))
        self.assertEqual(w.bal("1150"), D("0.00"))
        w.assert_books(self)

    def test_released_retainage_is_never_billed_twice(self):
        w = World(contract="100000")
        w.posted("100000")
        with self.assertRaises(ReceivableError):  # unknown project
            w.c.request_approval("prime_retainage.release", "prj_missing", actor_role="accountant")
        w.c.approve_and_execute("prime_retainage.release", w.pid, actor_role="accountant", actor="accountant", period_id="P1")
        self.assertEqual((w.bal("1150"), w.bal("1100")), (D("0.00"), D("100000.00")))
        w.r.set_prime_contract(w.pid, "100000", "0.05", actor="owner")
        with self.assertRaises(ReceivableError) as cm:  # a retainage reduction would re-bill released retainage
            w.certify("100000")
        self.assertIn("already released", str(cm.exception))
        empty = World()
        with self.assertRaises(ReceivableError):  # nothing retained yet
            empty.c.request_approval("prime_retainage.release", empty.pid, actor_role="accountant")
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# Reversals (journal.reverse) and cut-off                                     #
# --------------------------------------------------------------------------- #

class ReversalTests(unittest.TestCase):
    def test_a_reversed_bill_is_never_sent_and_a_granted_send_goes_stale(self):
        w = World()
        b = w.posted("60000")
        ap = w.c.request_approval("prime_bill.send", b["id"], actor_role="pm", requested_by="pm")
        w.c.approve(ap["id"], approver="owner")
        rev = w.reverse(b["journal_id"])
        self.assertEqual(lines_of(w.c.ledger.journal(rev["reversal_journal_id"])),
                         [("1100", "0.00", "54000.00"), ("1150", "0.00", "6000.00"), ("4000", "60000.00", "0.00")])
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap["id"], actor="pm")
        self.assertEqual(w.c.approvals.get(ap["id"])["status"], "invalidated")
        got = w.r.get(b["id"])
        self.assertEqual((got["status"], got["recorded_status"], got["reversed"], got["reversal_journal_id"], got["send"], got["open"], got["credited_by_reversal"]),
                         ("reversed", "posted", True, rev["reversal_journal_id"], None, "0.00", "54000.00"))
        with self.assertRaisesRegex(ReceivableIneligible, "reversed"):
            w.c.request_approval("prime_bill.send", b["id"], actor_role="pm")
        with self.assertRaisesRegex(ReceivableError, "nothing is receivable"):
            w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="1", provider_ref="CHK-REV-1", actor="treasury", method="check")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "reversed prime bill is never sent"):
            w.c.db.execute(RAW_SEND, (b["id"], ap["id"], b["content_hash"]))
        item = w.r.ar_open_items(w.pid)["items"][0]
        self.assertEqual({k: item[k] for k in ("status", "amount_due", "received", "reversed", "reversal_journal_id", "open")},
                         {"status": "reversed", "amount_due": "54000.00", "received": "0.00", "reversed": "54000.00",
                          "reversal_journal_id": rev["reversal_journal_id"], "open": "0.00"})
        self.assertEqual((w.bal("1100"), w.bal("1150"), w.bal("4000")), (D("0.00"), D("0.00"), D("0.00")))
        w.assert_books(self)

    def test_reversal_makes_a_granted_approval_stale_and_the_work_is_billed_again_once(self):
        w = World(contract="150000")
        b1 = w.posted("60000")
        b2 = w.certify("100000")
        self.assertEqual((b2["prior_net"], b2["amount_due"], b2["revenue_this_period"]), ("54000.00", "36000.00", "40000.00"))
        ap = w.c.request_approval("prime_bill.approve", b2["id"], actor_role="accountant", requested_by="pm")
        w.c.approve(ap["id"], approver="controller", approver_role="controller")
        w.reverse(b1["journal_id"])
        self.assertTrue(w.r.get(b2["id"])["chain_stale"])
        with self.assertRaises(StaleApprovalError):
            w.c.execute(ap["id"], actor="accountant")
        self.assertEqual((w.c.approvals.get(ap["id"])["status"], w.r.get(b2["id"])["status"]), ("invalidated", "draft"))
        self.assertEqual(len(w.c.ledger.journals(source_type="prime_bill")), 2)  # bill 1 and its reversal only
        with self.assertRaisesRegex(ReceivableIneligible, "reversed"):
            w.c.request_approval("prime_bill.approve", b2["id"], actor_role="accountant")
        w.r.void(b2["id"], actor="pm", reason="re-certify after the reversal of prime bill 1")
        b3 = w.certify("100000")
        self.assertEqual((b3["sequence"], b3["prior_net"], b3["amount_due"], b3["revenue_this_period"], b3["retainage_this_period"]),
                         (3, "0.00", "90000.00", "100000.00", "10000.00"))
        w.c.approve_and_execute("prime_bill.approve", b3["id"], actor_role="accountant", actor="accountant")
        self.assertEqual((w.bal("1100"), w.bal("1150"), w.bal("4000")), (D("90000.00"), D("10000.00"), D("100000.00")))
        with self.assertRaises(ReceivableError):  # the reversed work was billed again exactly once
            w.certify("100000")
        ar = w.r.ar_open_items(w.pid)
        self.assertEqual([(i["sequence"], i["status"], i["reversed"], i["open"]) for i in ar["items"]],
                         [(1, "reversed", "54000.00", "0.00"), (3, "posted", "0.00", "90000.00")])
        w.assert_books(self)

    def test_a_reversed_receipt_no_longer_counts_and_cannot_be_returned(self):
        w = World()
        b = w.posted("60000")
        col = w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="54000", fee="0", provider_ref="CHK-R-1", actor="treasury", method="check")
        self.assertEqual(w.r.get(b["id"])["recorded_status"], "collected")
        rev = w.reverse(col["journal_id"], reason="check recorded against the wrong bill (synthetic)")
        got = w.r.collection(col["id"])
        self.assertEqual((got["status"], got["journal_reversed_by"], got["credited"]), ("received", rev["reversal_journal_id"], "0.00"))
        self.assertEqual((w.r.get(b["id"])["received"], w.r.get(b["id"])["open"]), ("0.00", "54000.00"))
        with self.assertRaisesRegex(ReceivableError, "reversed"):
            w.r.record_return(collection_id=col["id"], period_id="P2", reason="R01 (simulated)", actor="treasury")
        w.r.record_collection(prime_bill_id=b["id"], period_id="P2", amount="54000", fee="0", provider_ref="CHK-R-2", actor="treasury", method="check")
        self.assertEqual(w.r.get(b["id"])["open"], "0.00")
        self.assertEqual((w.bal("1000"), w.bal("1100")), (D("54000.00"), D("0.00")))
        w.assert_books(self)

    def test_retainage_release_follows_reversed_bills_and_invoices(self):
        w = World(contract="200000")
        w.posted("100000")              # withholds 10,000.00
        b2 = w.posted("150000")         # withholds 5,000.00 more
        ap1 = w.c.request_approval("prime_retainage.release", w.pid, actor_role="controller")
        self.assertEqual((ap1["manifest"]["amounts"]["retainage_receivable"], ap1["manifest"]["bindings"]["reversed_prime_bill_sequences"]), ("15000.00", []))
        w.c.approve(ap1["id"], approver="owner")
        w.reverse(b2["journal_id"])
        with self.assertRaises(StaleApprovalError):  # the reversal changed the receivable the release bound
            w.c.execute(ap1["id"], actor="controller", period_id="P1")
        self.assertEqual(w.c.ledger.journals(source_type="prime_retainage_release"), [])

        ap2 = w.c.request_approval("prime_retainage.release", w.pid, actor_role="controller")
        bd = ap2["manifest"]["bindings"]
        self.assertEqual((ap2["manifest"]["amounts"]["retainage_receivable"], bd["reversed_prime_bill_sequences"], bd["through_prime_bill_sequence"],
                          bd["latest_prime_bill_sequence"], bd["earliest_period"]),
                         ("10000.00", [2], 1, 2, {"id": "P1", "start_date": "2026-10-01"}))
        w.c.approve(ap2["id"], approver="owner")
        inv = w.r.retainage_invoice(w.c.execute(ap2["id"], actor="controller", period_id="P1").result["retainage_invoice"])
        self.assertEqual((inv["amount"], inv["through_prime_bill_sequence"], inv["sequence"]), ("10000.00", 1, 1))

        # reversing the release reopens the whole retainage receivable; the invoice has nothing receivable
        w.reverse(inv["journal_id"])
        inv = w.r.retainage_invoice(inv["id"])
        self.assertEqual((inv["status"], inv["recorded_status"], inv["open"], inv["credited_by_reversal"]), ("reversed", "open", "0.00", "10000.00"))
        with self.assertRaisesRegex(ReceivableError, "nothing is receivable"):
            w.r.record_collection(retainage_invoice_id=inv["id"], period_id="P2", amount="1", provider_ref="WIRE-REV-1", actor="treasury", method="wire")
        self.assertEqual(w.bal("1150"), D("10000.00"))
        ap3 = w.c.request_approval("prime_retainage.release", w.pid, actor_role="controller")
        bd = ap3["manifest"]["bindings"]
        self.assertEqual((ap3["manifest"]["amounts"]["retainage_receivable"], bd["reversed_retainage_invoice_sequences"], bd["invoice_sequence"], bd["released_to_date"]),
                         ("10000.00", [1], 2, "0.00"))
        w.c.approve(ap3["id"], approver="owner")
        res = w.c.execute(ap3["id"], actor="controller", period_id="P2")
        self.assertEqual((res.result["amount"], res.result["sequence"]), ("10000.00", 2))
        self.assertEqual((w.bal("1150"), w.bal("1100")), (D("0.00"), D("100000.00")))
        ar = w.r.ar_open_items(w.pid)
        self.assertEqual([(i["source"], i["sequence"], i["status"], i["reversed"], i["open"]) for i in ar["items"]], [
            ("prime_bill", 1, "posted", "0.00", "90000.00"), ("prime_bill", 2, "reversed", "45000.00", "0.00"),
            ("prime_retainage_invoice", 1, "reversed", "10000.00", "0.00"), ("prime_retainage_invoice", 2, "open", "0.00", "10000.00")])
        w.assert_books(self)


class CutoffTests(unittest.TestCase):
    def test_collection_return_and_release_never_precede_what_they_settle(self):
        w = World(contract="100000")
        w.posted("50000", period="P1")
        b2 = w.posted("100000", period="P2")
        before = w.journal_count()
        with self.assertRaises(ReceivableCutoffError) as cm:  # a receipt is not dated before the bill it collects
            w.r.record_collection(prime_bill_id=b2["id"], period_id="P1", amount="1000", provider_ref="CHK-CUT-1", actor="treasury", method="check")
        self.assertIn("cut-off", str(cm.exception))
        self.assertEqual(w.r.get(b2["id"])["collections"], [])
        col = w.r.record_collection(prime_bill_id=b2["id"], period_id="P2", amount="1000", provider_ref="CHK-CUT-1", actor="treasury", method="check")
        with self.assertRaises(ReceivableCutoffError):  # nor a return before its receipt
            w.r.record_return(collection_id=col["id"], period_id="P1", reason="returned check (simulated)", actor="treasury")
        self.assertEqual(w.r.collection(col["id"])["status"], "received")

        ap = w.c.request_approval("prime_retainage.release", w.pid, actor_role="accountant")
        self.assertEqual(ap["manifest"]["bindings"]["earliest_period"], {"id": "P2", "start_date": "2026-11-01"})
        self.assertIn("2026-11-01", ap["manifest"]["bindings"]["target_rule"])
        w.c.approve(ap["id"], approver="controller", approver_role="controller")
        with self.assertRaises(ReceivableCutoffError):  # nor a release before the last bill that withheld the retainage
            w.c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual((w.c.approvals.get(ap["id"])["status"], w.bal("1150")), ("granted", D("10000.00")))  # the approval survives
        res = w.c.execute(ap["id"], actor="accountant", period_id="P2")
        self.assertEqual(res.result["period_id"], "P2")
        with self.assertRaises(ReceivableCutoffError):  # nor a retainage invoice's receipt before the invoice
            w.r.record_collection(retainage_invoice_id=res.result["retainage_invoice"], period_id="P1", amount="10000", provider_ref="WIRE-CUT-1",
                                  actor="treasury", method="wire")
        self.assertEqual(w.journal_count(), before + 2)  # the P2 receipt and the release only
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# Database guards behind the Python checks                                    #
# --------------------------------------------------------------------------- #

class DatabaseGuardTests(unittest.TestCase):
    def test_receipts_never_exceed_what_is_open_and_status_follows_them(self):
        w = World(contract="100000")
        b = w.posted("60000")
        w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="100", provider_ref="CHK-G-1", actor="treasury", method="check")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "collected exactly while"):  # a partial receipt does not collect the bill
            w.c.db.execute("UPDATE prime_bills SET status='collected' WHERE id=?", (b["id"],))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "cannot exceed what is open on its prime bill"):
            with w.c.db.transaction():  # even with its own collection journal (rolled back with the refused row)
                j = w.collection_journal("CHK-G-2", "53900.01")
                w.c.db.execute(RAW_COLLECTION, ("col_raw_over", b["id"], "53900.01", j["id"], "CHK-G-2", "check", None))
        draft_prj = w.c.create_project(name="Synthetic sheet piling extension", entity=ENTITY, budget="1000", customer_id=w.cust)
        draft = w.certify("500", project_id=draft_prj["id"])
        with self.assertRaisesRegex(sqlite3.DatabaseError, "only on a posted prime bill"):
            with w.c.db.transaction():
                j = w.collection_journal("CHK-G-3", "1.00")
                w.c.db.execute(RAW_COLLECTION, ("col_raw_draft", draft["id"], "1.00", j["id"], "CHK-G-3", "check", None))
        w.r.record_collection(prime_bill_id=b["id"], period_id="P1", amount="53900", provider_ref="CHK-G-4", actor="treasury", method="check")
        self.assertEqual((w.r.get(b["id"])["recorded_status"], w.r.get(b["id"])["open"]), ("collected", "0.00"))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "collected exactly while"):  # fully received: it stays collected (and unsendable)
            w.c.db.execute("UPDATE prime_bills SET status='posted' WHERE id=?", (b["id"],))
        with self.assertRaises(ReceivableIneligible):
            w.c.request_approval("prime_bill.send", b["id"], actor_role="pm")

        # retainage invoices: the same two guards
        w.c.approve_and_execute("prime_retainage.release", w.pid, actor_role="accountant", actor="accountant", period_id="P1")
        inv = w.r.retainage_invoices(w.pid)[0]
        self.assertEqual(inv["amount"], "6000.00")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "cannot exceed what is open on its retainage invoice"):
            with w.c.db.transaction():
                j = w.collection_journal("WIRE-G-1", "50000.00")
                w.c.db.execute("""INSERT INTO prime_retainage_collections (id, retainage_invoice_id, amount, fee, method, mandate_id, status, journal_id,
                                  provider_ref, received_at, recorded_by, settlement_date) VALUES ('rcl_raw_over', ?, '50000.00', '0.00', 'wire', NULL,
                                  'received', ?, 'WIRE-G-1', ?, 'raw', ?)""", (inv["id"], j["id"], RAW_TIME, inv["invoice_date"]))
        w.r.record_collection(retainage_invoice_id=inv["id"], period_id="P1", amount="1000", provider_ref="WIRE-G-2", actor="treasury", method="wire")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "collected exactly while"):
            w.c.db.execute("UPDATE prime_retainage_invoices SET status='collected' WHERE id=?", (inv["id"],))
        w.r.record_collection(retainage_invoice_id=inv["id"], period_id="P1", amount="5000", provider_ref="WIRE-G-3", actor="treasury", method="wire")
        self.assertEqual(w.r.retainage_invoice(inv["id"])["status"], "collected")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "collected exactly while"):
            w.c.db.execute("UPDATE prime_retainage_invoices SET status='open' WHERE id=?", (inv["id"],))
        self.assertEqual((w.bal("1100"), w.bal("1150"), w.bal("1000")), (D("0.00"), D("0.00"), D("60000.00")))
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# Upgrade: bills sent by the old direct send()                                #
# --------------------------------------------------------------------------- #

class LegacySendTests(unittest.TestCase):
    @staticmethod
    def _legacy_bill(w, bill_id, project_id, *, status, certified, amount_due, retained, audit_sent):
        """A prime bill as the code before the receivables controls left it: posted with its
        journal and, when the old send() delivered it, a prime_bill.sent audit event."""
        tags = {"project_id": project_id, "party_id": w.cust}
        j = w.c.ledger.post(period_id="P1", description="Prime bill 1 (legacy)", source_type="prime_bill", source_id=bill_id, source_version="1", posted_by="owner",
                            lines=[{"account": "1100", "debit": amount_due, **tags}, {"account": "1150", "debit": retained, **tags},
                                   {"account": "4000", "credit": certified, **tags}])
        w.c.db.execute(
            """INSERT INTO prime_bills (id, project_id, customer_id, period_id, sequence, status, certified_cumulative, retainage_rate, retainage_cumulative,
               prior_net, amount_due, revenue_this_period, content_hash, approval_id, journal_id, created_at)
               VALUES (?, ?, ?, 'P1', 1, ?, ?, '0.100000', ?, '0.00', ?, ?, ?, NULL, ?, '2026-10-05T00:00:00Z')""",
            (bill_id, project_id, w.cust, status, certified, retained, amount_due, certified, f"legacy-hash-{bill_id}", j["id"]))
        if audit_sent:
            w.c.audit.record("pm", "prime_bill.sent", "prime_bill", bill_id, {"channel": "mail-sink (legacy direct send)"})

    def test_a_bill_sent_before_the_upgrade_is_never_sent_again(self):
        path = os.path.join(tempfile.mkdtemp(), "legacy-send.sqlite")
        # the dates entries build on both controls entries, so a workspace from before them lacks them too
        legacy = [e for e in core_db.SCHEMA_CATALOG
                  if e[1] not in (CONTROLS_SCHEMA_NAME, CONTROLS_GUARDS_SCHEMA_NAME, DATES_CREDITS_SCHEMA_NAME, DATES_CREDITS_GUARDS_SCHEMA_NAME)]
        with mock.patch.object(core_db, "SCHEMA_CATALOG", legacy):
            w = World(path=path)
            second = w.c.create_project(name="Synthetic dewatering wells", entity=ENTITY, budget="20000", customer_id=w.cust)["id"]
            third = w.c.create_project(name="Synthetic cofferdam bracing", entity=ENTITY, budget="20000", customer_id=w.cust)["id"]
            self._legacy_bill(w, "pbl_legacy1", w.pid, status="sent", certified="60000.00", amount_due="54000.00", retained="6000.00", audit_sent=True)
            self._legacy_bill(w, "pbl_legacy2", second, status="posted", certified="10000.00", amount_due="9000.00", retained="1000.00", audit_sent=False)
            self._legacy_bill(w, "pbl_legacy3", third, status="sent", certified="5000.00", amount_due="4500.00", retained="500.00", audit_sent=False)
        w.reopen()
        try:
            self.assertEqual(w.c.db.schema_status()["pending"], [])
            one = w.r.get("pbl_legacy1")
            self.assertEqual((one["status"], one["recorded_status"], one["send"], one["delivered"], one["legacy_send"]["detected_from"]),
                             ("sent", "sent", None, True, "audit: prime_bill.sent"))
            self.assertEqual(w.r.get("pbl_legacy3")["legacy_send"]["detected_from"], "status: sent")
            with self.assertRaisesRegex(ReceivableIneligible, "legacy send"):
                w.c.request_approval("prime_bill.send", "pbl_legacy1", actor_role="pm")
            # collected in full and then returned: it reopens, still counts as sent, and is never re-sent
            col = w.r.record_collection(prime_bill_id="pbl_legacy1", period_id="P2", amount="54000", provider_ref="CHK-LEGACY-1", actor="treasury", method="check")
            self.assertEqual(w.r.get("pbl_legacy1")["recorded_status"], "collected")
            w.r.record_return(collection_id=col["id"], period_id="P2", reason="returned check (simulated)", actor="treasury")
            one = w.r.get("pbl_legacy1")
            self.assertEqual((one["recorded_status"], one["status"], one["open"], one["delivered"]), ("posted", "sent", "54000.00", True))
            with self.assertRaisesRegex(ReceivableIneligible, "legacy send"):
                w.c.request_approval("prime_bill.send", "pbl_legacy1", actor_role="pm")
            # the bill the old code never sent is sent through its approval
            two = w.r.get("pbl_legacy2")
            self.assertEqual((two["status"], two["legacy_send"], two["delivered"]), ("posted", None, False))
            w.c.approve_and_execute("prime_bill.send", "pbl_legacy2", actor_role="pm", actor="pm")
            self.assertEqual((w.r.get("pbl_legacy2")["status"], w.r.get("pbl_legacy2")["delivered"]), ("sent", True))
            # the legacy records are fixed by the upgrade
            for sql, needle in (("INSERT INTO prime_bill_legacy_sends (prime_bill_id, detected_from, sent_at, recorded_at) VALUES ('pbl_legacy2', 'raw', NULL, 'x')", "recorded once"),
                                ("UPDATE prime_bill_legacy_sends SET detected_from='raw'", "immutable"),
                                ("DELETE FROM prime_bill_legacy_sends", "immutable")):
                with self.assertRaisesRegex(sqlite3.DatabaseError, needle, msg=sql):
                    w.c.db.execute(sql)
            self.assertEqual([r["prime_bill_id"] for r in w.r.audit_export()["prime_bill_legacy_sends"]], ["pbl_legacy1", "pbl_legacy3"])
            self.assertEqual([(i["prime_bill_id"], i["status"], i["open"]) for i in w.r.ar_open_items()["items"]],
                             sorted([("pbl_legacy1", "sent", "54000.00"), ("pbl_legacy2", "sent", "9000.00"), ("pbl_legacy3", "sent", "4500.00")],
                                    key=lambda t: {"pbl_legacy1": w.pid, "pbl_legacy2": second, "pbl_legacy3": third}[t[0]]))
            self.assertEqual((w.bal("1100"), w.bal("1150"), w.bal("1000")), (D("67500.00"), D("7500.00"), D("0.00")))
            w.assert_books(self)
        finally:
            w.c.db.close()


# --------------------------------------------------------------------------- #
# Subledgers                                                                  #
# --------------------------------------------------------------------------- #

class _FakeTimeAndMaterials:
    """A stand-in module that billed 1,500.00 through control account 1100."""

    def __init__(self, project_id):
        self.project_id = project_id
        self.calls = []

    def ar_open_items(self, project_id=None):
        self.calls.append(project_id)
        mine = project_id in (None, self.project_id)
        items = [{"kind": "fake_invoice", "source": "fake_tm", "invoice_id": "ftm-1", "project_id": self.project_id, "open": "1500.00"}] if mine else []
        return {"source": "fake T&M invoices", "items": items, "subledger_total": "1500.00" if mine else "0.00"}


class _Broken:
    def ar_open_items(self, project_id=None):
        raise RuntimeError("source offline")


class _Inconsistent:
    def ar_open_items(self, project_id=None):
        return {"source": "inconsistent", "items": [{"open": "100.00"}], "subledger_total": "200.00"}


class SubledgerTests(unittest.TestCase):
    def test_ar_subledger_includes_extra_sources_tagged_and_reconciles(self):
        w = World()
        w.posted("60000")
        w.c.ledger.post(period_id="P1", description="synthetic T&M invoice", source_type="fake_tm_invoice", source_id="ftm-1", source_version="1", posted_by="test",
                        lines=[{"account": "1100", "debit": "1500", "project_id": w.pid, "party_id": w.cust}, {"account": "4000", "credit": "1500", "project_id": w.pid, "party_id": w.cust}])
        w.r.extra_ar_sources = lambda: []
        ar = w.r.ar_open_items()
        self.assertEqual((ar["subledger_total"], ar["control_balance"], ar["reconciled"]), ("54000.00", "55500.00", False))

        fake = _FakeTimeAndMaterials(w.pid)
        w.r.extra_ar_sources = lambda: [fake]
        ar = w.r.ar_open_items()
        self.assertEqual((ar["subledger_total"], ar["control_balance"], ar["reconciled"], ar["errors"]), ("55500.00", "55500.00", True, []))
        self.assertEqual([(i["source"], i["open"]) for i in ar["items"]], [("prime_bill", "54000.00"), ("fake T&M invoices", "1500.00")])
        self.assertEqual((ar["items"][1]["item_source"], ar["items"][1]["invoice_id"]), ("fake_tm", "ftm-1"))  # the item's own tag is kept
        self.assertNotIn("item_source", ar["items"][0])
        self.assertEqual(ar["sources"], [{"source": "prime_bill", "subledger_total": "54000.00"}, {"source": "prime_retainage_invoice", "subledger_total": "0.00"},
                                         {"source": "fake T&M invoices", "subledger_total": "1500.00"}])
        self.assertTrue(w.r.ar_open_items(w.pid)["reconciled"])
        self.assertEqual(fake.calls, [None, w.pid])
        w.r.extra_ar_sources = lambda: [w.r, fake, fake]  # the core is never counted twice, nor a source
        self.assertEqual((w.r.ar_open_items()["subledger_total"], w.r.ar_open_items()["reconciled"]), ("55500.00", True))

        for bad, needle in ((_Broken(), "source offline"), (_Inconsistent(), "sum to 100.00")):
            w.r.extra_ar_sources = lambda bad=bad: [fake, bad]
            ar = w.r.ar_open_items()
            self.assertFalse(ar["reconciled"])
            self.assertEqual(len(ar["errors"]), 1)
            self.assertIn(needle, ar["errors"][0]["error"])

        def registry_down():
            raise RuntimeError("registry unavailable")
        w.r.extra_ar_sources = registry_down
        self.assertFalse(w.r.ar_open_items()["reconciled"])

        bare = Receivables(w.c.db, w.c.audit, w.c.ledger)  # without the service: no extra sources
        self.assertEqual([s["source"] for s in bare.ar_open_items()["sources"]], ["prime_bill", "prime_retainage_invoice"])
        del bare.extra_ar_sources
        self.assertEqual(bare.ar_open_items()["subledger_total"], "54000.00")

    def test_core_items_carry_plain_values_with_the_shared_column_meanings(self):
        """Prime bill and retainage invoice items hold text, integers, money strings and None
        only (a CSV export renders them unchanged), and ``reversed`` is the amount a reversal
        credited, as on the labor T&M and reimbursement items."""
        w = World(contract="100000")
        w.posted("100000")
        w.c.approve_and_execute("prime_retainage.release", w.pid, actor_role="accountant", actor="accountant", period_id="P1")
        items = w.r.ar_open_items()["items"]
        self.assertEqual([i["kind"] for i in items], ["prime_bill", "retainage_invoice"])
        for it in items:
            self.assertEqual([k for k, v in it.items() if not (v is None or isinstance(v, str) or type(v) is int)], [], it)
            self.assertEqual((it["reversed"], it["reversal_journal_id"]), ("0.00", None))
            self.assertNotIn("credited_by_reversal", it)
        self.assertEqual([(i["amount_due"], i["received"], i["open"]) for i in items], [("90000.00", "0.00", "90000.00"), ("10000.00", "0.00", "10000.00")])

    def test_service_registers_plugin_sources(self):
        c = Cipher()
        sources = c.receivables.extra_ar_sources()
        self.assertNotIn(c.receivables, sources)
        ar = c.receivables.ar_open_items()
        self.assertTrue(ar["reconciled"])
        self.assertEqual(len(ar["sources"]), 2 + len(sources))

    def test_retainage_receivable_reconciles_1150_per_project(self):
        w = World()
        w.posted("60000")
        second = w.c.create_project(name="Synthetic pump station cofferdam", entity=ENTITY, budget="50000", customer_id=w.cust)
        w.posted("20000", project_id=second["id"])
        ret = w.r.retainage_receivable_items()
        self.assertEqual((ret["subledger_total"], ret["control_balance"], ret["reconciled"]), ("8000.00", "8000.00", True))
        self.assertEqual(sorted(i["open"] for i in ret["items"]), ["2000.00", "6000.00"])
        self.assertEqual(w.r.deposits_items()["subledger_total"], "0.00")  # no deposits: 2400 ties at zero
        self.assertEqual(w.r.retainage_receivable_items(second["id"])["subledger_total"], "2000.00")
        checks = {ch["check"]: ch for ch in w.c.plugin("core_reconciliation").close_checks("P1")}
        self.assertTrue(checks["retainage receivable reconciled (1150)"]["ok"])
        # an unexplained 1150 entry breaks the reconciliation and the close check says so
        w.c.ledger.post(period_id="P1", description="unexplained retainage", source_type="test", source_id="t-1", source_version="1", posted_by="test",
                        lines=[{"account": "1150", "debit": "100", "project_id": w.pid}, {"account": "4000", "credit": "100", "project_id": w.pid}])
        self.assertFalse(w.r.retainage_receivable_items()["reconciled"])
        checks = {ch["check"]: ch for ch in w.c.plugin("core_reconciliation").close_checks("P1")}
        self.assertFalse(checks["retainage receivable reconciled (1150)"]["ok"])

    def test_audit_export_lists_the_control_records(self):
        w = World(contract="100000")
        w.mandate()
        w.sent("60000")
        exp = w.r.audit_export()
        self.assertEqual((len(exp["prime_contracts"]), len(exp["mandates"]), len(exp["prime_bill_sends"]), exp["retainage_invoices"]), (1, 1, 1, []))
        self.assertTrue(exp["ar_reconciliation"]["reconciled"] and exp["retainage_reconciliation"]["reconciled"])


# --------------------------------------------------------------------------- #
# Golden fixture and schema                                                   #
# --------------------------------------------------------------------------- #

class GoldenAndSchemaTests(unittest.TestCase):
    def test_golden_fixture_sends_through_approval_and_collects_under_mandate(self):
        c = Cipher()
        r = run_golden_fixture(c)
        prime = c.receivables.list(r["project_id"])[0]
        self.assertEqual((prime["status"], prime["amount_due"]), ("sent", "54000.00"))
        send_ap = c.approvals.get(prime["send"]["approval_id"])
        self.assertEqual((send_ap["operation"], send_ap["status"]), ("prime_bill.send", "consumed"))
        mandates = c.receivables.mandates()
        self.assertEqual([(m["mandate_ref"], m["status"]) for m in mandates], [("MANDATE-SIM-0001", "active")])
        col = prime["collections"][0]
        self.assertEqual((col["method"], col["mandate_id"], col["status"]), ("ach", mandates[0]["id"], "returned"))
        self.assertTrue(r["ar"]["reconciled"])
        ret = c.receivables.retainage_receivable_items()
        self.assertEqual((ret["subledger_total"], ret["reconciled"]), ("6000.00", True))
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_controls_schema_is_applied_and_survives_a_reopen(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "receivables.sqlite")
        w = World(contract="100000", path=path)
        w.posted("60000")
        status = {v["name"]: v for v in w.c.db.schema_status()["versions"]}
        for name in (CONTROLS_SCHEMA_NAME, CONTROLS_GUARDS_SCHEMA_NAME, DATES_CREDITS_SCHEMA_NAME, DATES_CREDITS_GUARDS_SCHEMA_NAME):
            self.assertTrue(status[name]["applied"] and status[name]["checksum_matches"], name)
        self.assertLess(status[CONTROLS_SCHEMA_NAME]["version"], status[CONTROLS_GUARDS_SCHEMA_NAME]["version"])
        self.assertLess(status[CONTROLS_GUARDS_SCHEMA_NAME]["version"], status[DATES_CREDITS_SCHEMA_NAME]["version"])
        self.assertLess(status[DATES_CREDITS_SCHEMA_NAME]["version"], status[DATES_CREDITS_GUARDS_SCHEMA_NAME]["version"])
        w.c.db.close()
        reopened = Cipher(path)
        try:
            self.assertEqual(reopened.receivables.contract(w.pid)["contract_value"], "100000.00")
            self.assertTrue(reopened.receivables.ar_open_items()["reconciled"])
            self.assertEqual(reopened.db.schema_status()["pending"], [])
        finally:
            reopened.db.close()

    def test_ineligible_subject_is_both_a_receivable_error_and_stale(self):
        self.assertTrue(issubclass(ReceivableIneligible, ReceivableError) and issubclass(ReceivableIneligible, StaleApprovalError))
        self.assertTrue(issubclass(ReceivableInputError, ReceivableError) and issubclass(ReceivableInputError, MoneyError))


if __name__ == "__main__":
    unittest.main()
