"""Ledger invariants: balance, immutability, period locks, reversals, reconciliation."""
import sqlite3
import unittest
from decimal import Decimal

from apps.cipher.core.approvals import Approvals, build_manifest
from apps.cipher.core.audit import Audit
from apps.cipher.core.db import Database
from apps.cipher.core.money import MoneyError
from apps.cipher.domain.ledger import SUBLEDGER_OWNED_SOURCES, Ledger, LedgerError, PeriodNotOpen, SubledgerOwnedJournal, UnbalancedJournal


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.audit = Audit(self.db)
        self.approvals = Approvals(self.db, self.audit)
        self.ledger = Ledger(self.db, self.audit)
        self.ledger.ensure_chart()
        self.ledger.open_period("P1", "Period 1", "2026-10-01", "2026-10-31")
        self.ledger.open_period("P2", "Period 2", "2026-11-01", "2026-11-30")

    def post(self, period="P1", amount="100"):
        return self.ledger.post(period_id=period, description="t", lines=[{"account": "5000", "debit": amount}, {"account": "2000", "credit": amount}],
                                source_type="test", source_id="s", source_version="1", posted_by="o")

    def reopen_approval(self, period_id, *, operation="close.reopen_period", consume=True, subject_type="period"):
        """A recorded controller approval for reopening ``period_id`` (consumed unless asked otherwise)."""
        m = build_manifest(operation=operation, subject_type=subject_type, subject_id=period_id, actor_role="controller",
                           bindings={"period_status": self.ledger.period(period_id)["status"]})
        ap = self.approvals.request(m, requested_by="controller")
        self.approvals.grant(ap["id"], approver="owner")
        if consume:
            self.approvals.consume(ap["id"], current_manifest=m, consumer="controller")
        return ap["id"]

    def test_unbalanced_rejected(self):
        with self.assertRaises(UnbalancedJournal):
            self.ledger.post(period_id="P1", description="x", lines=[{"account": "5000", "debit": "1"}, {"account": "2000", "credit": "2"}], source_type="t", source_id="s", source_version="1", posted_by="o")
        self.assertEqual(self.ledger.trial_balance()["journal_count"], 0)

    def test_line_needs_one_side(self):
        with self.assertRaises(UnbalancedJournal):
            self.ledger.post(period_id="P1", description="x", lines=[{"account": "5000", "debit": "1", "credit": "1"}, {"account": "2000", "credit": "0"}], source_type="t", source_id="s", source_version="1", posted_by="o")

    def test_unknown_account(self):
        with self.assertRaises(LedgerError):
            self.ledger.post(period_id="P1", description="x", lines=[{"account": "9999", "debit": "1"}, {"account": "2000", "credit": "1"}], source_type="t", source_id="s", source_version="1", posted_by="o")

    def test_journals_are_immutable(self):
        j = self.post()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE journals SET description='x' WHERE id=?", (j["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM journal_lines WHERE journal_id=?", (j["id"],))

    def test_posted_journal_is_sealed_by_its_line_count(self):
        j = self.post(amount="250.00")
        self.assertEqual(j["line_count"], 2)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "posted journals are immutable"):
            self.db.execute("INSERT INTO journal_lines (id, journal_id, line_no, account_code, debit, credit, memo) VALUES ('jln_x', ?, 3, '5000', '1.00', '0.00', 'extra')", (j["id"],))
        self.assertEqual([(ln["account_code"], ln["debit"], ln["credit"]) for ln in self.ledger.journal(j["id"])["lines"]],
                         [("5000", "250.00", "0.00"), ("2000", "0.00", "250.00")])
        tb = self.ledger.trial_balance()
        self.assertEqual((tb["total_debit"], tb["total_credit"], tb["balanced"]), ("250.00", "250.00", True))

    def test_non_finite_and_out_of_range_amounts_post_nothing(self):
        for amount in ("NaN", "Infinity", "sNaN", "10000000000000.00"):
            with self.subTest(amount=amount), self.assertRaises(MoneyError):
                self.post(amount=amount)
        self.assertEqual(self.ledger.trial_balance()["journal_count"], 0)

    def test_reversal_needs_a_reason_and_resolves_pending_requests(self):
        j = self.post(amount="40.00")
        with self.assertRaises(LedgerError):
            self.ledger.reverse(j["id"], period_id="P1", posted_by="o", reason="  ")
        req = self.ledger.prepare_reversal(j["id"], "wrong cost account", "accountant")
        self.assertEqual(req["status"], "pending")
        r = self.ledger.reverse(j["id"], period_id="P2", posted_by="o", reason="direct correction")
        done = self.ledger.reversal_request(req["id"])
        self.assertEqual((done["status"], done["reversal_journal_id"]), ("cancelled", r["id"]))
        self.assertIn("superseded", done["resolution_note"])
        self.assertEqual(r["description"], f"Reversal of {j['id']}: direct correction")
        with self.assertRaises(LedgerError):
            self.ledger.prepare_reversal(j["id"], "again", "accountant")

    def test_governed_reversal_refuses_subledger_sources_and_reversals(self):
        for source in ("bill", "retainage_release", "payment_intent", "provider_event", "asset_run", "wip_adjustment", "reimbursement_claim"):
            j = self.ledger.post(period_id="P1", description="subledger posting", lines=[{"account": "5000", "debit": "10"}, {"account": "2000", "credit": "10"}],
                                 source_type=source, source_id=f"{source}-1", source_version="1", posted_by="o")
            with self.subTest(source=source), self.assertRaisesRegex(SubledgerOwnedJournal, "correct it through the owning module"):
                self.ledger.prepare_reversal(j["id"], "late correction", "accountant")
            with self.subTest(source=source), self.assertRaises(SubledgerOwnedJournal):
                self.ledger.manifest_for("journal.reverse", j["id"], actor_role="accountant")
        self.assertEqual(self.ledger.reversal_requests(), [])
        # a reversal journal is never itself reversed through journal.reverse
        j = self.post(amount="12.00")
        r = self.ledger.reverse(j["id"], period_id="P1", posted_by="o", reason="posted twice")
        with self.assertRaisesRegex(LedgerError, "itself the reversal"):
            self.ledger.prepare_reversal(r["id"], "undo", "accountant")
        # a module that keeps its subledger in step with a bare reversal can opt its source back in
        bill = self.ledger.journals(source_type="bill")[0]
        self.ledger.reversal_owners.pop("bill")
        self.assertEqual(self.ledger.prepare_reversal(bill["id"], "late correction", "accountant")["status"], "pending")
        self.assertIn("bill", SUBLEDGER_OWNED_SOURCES)  # the module default is untouched
        self.assertTrue(self.ledger.trial_balance()["balanced"])

    def test_period_lock_blocks_all_paths(self):
        self.post()
        self.ledger.close_period("P1", actor="o")
        with self.assertRaises(PeriodNotOpen):
            self.post()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO journals (id, period_id, posted_at, description, source_type, source_id, source_version, rule_version, posted_by) VALUES ('x','P1','t','d','s','i','1','r','o')")
        self.post("P2")

    def test_reopen_requires_approval_and_lock_is_final(self):
        self.ledger.close_period("P1", actor="o")
        with self.assertRaises(LedgerError):
            self.ledger.reopen_period("P1", actor="o", approval_ref="")
        with self.assertRaisesRegex(LedgerError, "not a recorded approval"):
            self.ledger.reopen_period("P1", actor="o", approval_ref="apr_ctrl")
        self.assertEqual(self.ledger.period("P1")["status"], "closed")
        ref = self.reopen_approval("P1")
        p = self.ledger.reopen_period("P1", actor="o", approval_ref=ref)
        self.assertEqual((p["status"], p["reopen_approval_id"]), ("open", ref))
        self.assertEqual([r["approval_id"] for r in self.ledger.reopens("P1")], [ref])
        self.post()
        self.ledger.close_period("P1", actor="o")
        with self.assertRaisesRegex(LedgerError, "already reopened period P1"):
            self.ledger.reopen_period("P1", actor="o", approval_ref=ref)  # an approval reopens once
        self.ledger.lock_period("P1", actor="o")
        with self.assertRaises(PeriodNotOpen):
            self.ledger.reopen_period("P1", actor="o", approval_ref=self.reopen_approval("P1"))
        self.assertEqual(self.ledger.period("P1")["status"], "locked")

    def test_reopen_approval_must_be_consumed_scoped_and_a_reopen(self):
        self.ledger.close_period("P1", actor="o")
        self.ledger.close_period("P2", actor="o")
        cases = (
            (self.reopen_approval("P1", consume=False), "granted; only a consumed"),
            (self.reopen_approval("P2"), "scoped to period P2, not P1"),
            (self.reopen_approval("P1", operation="close.close_period"), "not a reopen_period approval"),
            (self.reopen_approval("P1", operation="reopen_period"), "not a reopen_period approval"),
            (self.reopen_approval("P1", operation="evil.reopen_period", subject_type="journal"), "scoped to a journal, not a period"),
        )
        for ref, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(LedgerError, message):
                self.ledger.reopen_period("P1", actor="o", approval_ref=ref)
            self.assertEqual(self.ledger.period("P1")["status"], "closed")
        self.ledger.open_period("P3", "Period 3", "2026-12-01", "2026-12-31")
        with self.assertRaisesRegex(LedgerError, "P3 is open; only a closed period"):
            self.ledger.reopen_period("P3", actor="o", approval_ref=self.reopen_approval("P3"))
        with self.assertRaisesRegex(LedgerError, "unknown period"):
            self.ledger.reopen_period("P9", actor="o", approval_ref="apr_any")

    def test_reversal_appends_and_balances(self):
        j = self.post(amount="27000")
        self.assertEqual(self.ledger.balance("2000"), Decimal("27000.00"))
        r = self.ledger.reverse(j["id"], period_id="P1", posted_by="o", reason="correction")
        self.assertEqual(r["reversal_of"], j["id"])
        self.assertEqual(self.ledger.journal(j["id"])["reversed_by"], r["id"])
        self.assertEqual(self.ledger.balance("2000"), Decimal("0.00"))
        with self.assertRaises(LedgerError):
            self.ledger.reverse(j["id"], period_id="P1", posted_by="o", reason="twice")
        self.assertTrue(self.ledger.trial_balance()["balanced"])

    def test_trial_balance_and_income(self):
        self.post(amount="100")
        tb = self.ledger.trial_balance("P1")
        self.assertEqual(tb["total_debit"], "100.00")
        self.assertTrue(tb["balanced"])
        inc = self.ledger.income_statement("P1")
        self.assertEqual(inc["expense"], "100.00")
        self.assertIn("SHADOW", inc["label"])

    def test_duplicate_period_is_refused(self):
        with self.assertRaisesRegex(LedgerError, "period P1 already exists"):
            self.ledger.open_period("P1", "Again", "2026-10-01", "2026-10-31")
        self.assertEqual([p["id"] for p in self.ledger.periods()], ["P1", "P2"])

    def test_close_requires_balanced_books(self):
        self.post()
        p = self.ledger.close_period("P1", actor="o")
        self.assertEqual(p["status"], "closed")


if __name__ == "__main__":
    unittest.main()
