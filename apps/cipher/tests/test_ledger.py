"""Ledger invariants: balance, immutability, period locks, reversals, reconciliation."""
import sqlite3
import unittest
from decimal import Decimal

from apps.cipher.core.audit import Audit
from apps.cipher.core.db import Database
from apps.cipher.domain.ledger import Ledger, LedgerError, PeriodNotOpen, UnbalancedJournal


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.ledger = Ledger(self.db, Audit(self.db))
        self.ledger.ensure_chart()
        self.ledger.open_period("P1", "Period 1", "2026-10-01", "2026-10-31")
        self.ledger.open_period("P2", "Period 2", "2026-11-01", "2026-11-30")

    def post(self, period="P1", amount="100"):
        return self.ledger.post(period_id=period, description="t", lines=[{"account": "5000", "debit": amount}, {"account": "2000", "credit": amount}],
                                source_type="test", source_id="s", source_version="1", posted_by="o")

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
        self.ledger.reopen_period("P1", actor="o", approval_ref="apr_ctrl")
        self.post()
        self.ledger.close_period("P1", actor="o")
        self.ledger.lock_period("P1", actor="o")
        with self.assertRaises(PeriodNotOpen):
            self.ledger.reopen_period("P1", actor="o", approval_ref="apr_ctrl")

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

    def test_close_requires_balanced_books(self):
        self.post()
        p = self.ledger.close_period("P1", actor="o")
        self.assertEqual(p["status"], "closed")


if __name__ == "__main__":
    unittest.main()
