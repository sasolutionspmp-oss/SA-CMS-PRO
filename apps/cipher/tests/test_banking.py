"""Bank statement import and bank reconciliation: golden sequence and adversarial variants."""
import hashlib
import json
import sqlite3
import unittest
from decimal import Decimal

from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.domain.banking import PLUGIN_NAME, BankingError, line_fingerprint
from apps.cipher.service import Cipher, run_golden_fixture


class Scenario:
    """Fresh in-memory workspace: verified supplier, customer, project, open period P1 (October 2026)."""

    def __init__(self):
        self.c = Cipher()
        self.b = self.c.plugin(PLUGIN_NAME)
        self.supplier = self.c.add_party(kind="supplier", name="Synthetic Subcontractor A", destination="ACH-SIM-0001")
        self.c.verify_destination(self.supplier["id"], destination="ACH-SIM-0001", verified_by="owner")
        self.customer = self.c.add_party(kind="customer", name="Synthetic Owner Agency")
        self.project = self.c.create_project(name="Synthetic WWTP upgrade", entity="S&A Solutions LLC (synthetic)", budget="115000", customer_id=self.customer["id"])
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        self._seq = 0

    # ---- GL setup journals (bank side line id is returned) ------------------------ #

    def _post(self, period, description, lines):
        self._seq += 1
        j = self.c.ledger.post(period_id=period, description=description, lines=lines, source_type="test_setup", source_id=f"setup-{self._seq}", source_version="1", posted_by="setup")
        return next(ln["id"] for ln in j["lines"] if ln["account_code"] == "1000")

    def pay_out(self, amount, description, *, period="P1", memo="bank disbursement"):
        return self._post(period, description, [
            {"account": "2000", "debit": amount, "project_id": self.project["id"], "party_id": self.supplier["id"], "memo": "payable settled"},
            {"account": "1000", "credit": amount, "project_id": self.project["id"], "party_id": self.supplier["id"], "memo": memo},
        ])

    def receive(self, amount, description, *, period="P1", memo="ACH receipt"):
        return self._post(period, description, [
            {"account": "1000", "debit": amount, "project_id": self.project["id"], "party_id": self.customer["id"], "memo": memo},
            {"account": "1100", "credit": amount, "project_id": self.project["id"], "party_id": self.customer["id"], "memo": "receivable collected"},
        ])

    def golden_gl(self):
        self.pay_line = self.pay_out("27000.00", "Payment settled (sim_000001)")
        self.rcv_line = self.receive("53995.00", "Collection ach_sim_rcv_0001")

    # ---- statements ---------------------------------------------------------------- #

    PAY = {"date": "2026-10-20", "amount": "-27000.00", "description": "ACH DEBIT SYNTHETIC SUBCONTRACTOR A", "reference": "sim_000001"}
    RCV = {"date": "2026-10-24", "amount": "53995.00", "description": "ACH CREDIT SYNTHETIC OWNER AGENCY", "reference": "ach_sim_rcv_0001"}
    FEE = {"date": "2026-10-31", "amount": "-15.00", "description": "MONTHLY SERVICE FEE", "reference": "FEE-2026-10"}

    def october(self, ref="OCT-2026"):
        return self.b.import_statement(statement_ref=ref, period_id="P1", opening_balance="0.00", closing_balance="26995.00",
                                       lines=[dict(self.PAY), dict(self.RCV)], actor="accountant")

    def october_with_fee(self, ref="OCT-2026-FULL"):
        return self.b.import_statement(statement_ref=ref, period_id="P1", opening_balance="0.00", closing_balance="26980.00",
                                       lines=[dict(self.PAY), dict(self.RCV), dict(self.FEE)], actor="accountant")

    def reconciled_october(self):
        self.golden_gl()
        st = self.october()
        self.b.auto_match(st["id"], "accountant")
        return st


class BankingGoldenTests(unittest.TestCase):
    def test_golden_sequence(self):
        s = Scenario()
        c, b = s.c, s.b
        s.golden_gl()
        self.assertEqual(c.ledger.balance("1000"), Decimal("26995.00"))

        oct1 = s.october()
        self.assertEqual(oct1["imported_count"], 2)
        self.assertEqual(oct1["skipped_count"], 0)
        self.assertEqual(oct1["status"], "open")
        self.assertEqual(oct1["opening_balance"], "0.00")
        self.assertEqual(oct1["closing_balance"], "26995.00")
        self.assertEqual(oct1["end_date"], "2026-10-24")
        self.assertEqual([ln["amount"] for ln in oct1["lines"]], ["-27000.00", "53995.00"])

        run = b.auto_match(oct1["id"], "accountant")
        self.assertEqual(len(run["matched"]), 2)
        self.assertEqual({m["basis"] for m in run["matched"]}, {"reference"})
        self.assertEqual({m["journal_line_id"] for m in run["matched"]}, {s.pay_line, s.rcv_line})
        self.assertEqual(run["ambiguous"], [])
        self.assertEqual(run["unmatched"], [])
        rec = b.reconciliation(oct1["id"])
        self.assertEqual(rec["statement_closing"], "26995.00")
        self.assertEqual(rec["gl_balance"], "26995.00")
        self.assertEqual(rec["in_transit_total"], "0.00")
        self.assertEqual(rec["adjusted_gl_balance"], "26995.00")
        self.assertEqual(rec["difference"], "0.00")
        self.assertEqual(rec["unmatched_statement_lines"], [])
        self.assertEqual(rec["unmatched_gl_lines"], [])
        self.assertTrue(rec["reconciled"])

        # an overlapping export repeats both lines and adds a bank fee: only the fee is new
        oct2 = s.october_with_fee()
        self.assertEqual(oct2["imported_count"], 1)
        self.assertEqual(oct2["skipped_count"], 2)
        self.assertEqual([ln["amount"] for ln in oct2["lines"]], ["-15.00"])
        self.assertEqual({sk["duplicate_of_line_id"] for sk in oct2["skipped"]}, {ln["id"] for ln in oct1["lines"]})
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM banking_lines"), 3)
        fee_line = oct2["lines"][0]

        run = b.auto_match(oct2["id"], "accountant")
        self.assertEqual(run["matched"], [])
        self.assertEqual([u["line_id"] for u in run["unmatched"]], [fee_line["id"]])
        rec2 = b.reconciliation(oct2["id"])
        self.assertFalse(rec2["reconciled"])
        self.assertEqual(rec2["statement_closing"], "26980.00")
        self.assertEqual(rec2["gl_balance"], "26995.00")
        self.assertEqual(rec2["difference"], "-15.00")
        self.assertEqual([u["line_id"] for u in rec2["unmatched_statement_lines"]], [fee_line["id"]])
        with self.assertRaises(BankingError):
            c.request_approval("banking.lock_reconciliation", oct2["id"])

        res = c.approve_and_execute("banking.post_fee", fee_line["id"], actor_role="accountant", actor="accountant", period_id="P1")
        self.assertEqual(res.result["fee"], "15.00")
        self.assertEqual(res.result["status"], "booked")
        j = c.ledger.journal(res.result["journal_id"])
        by_account = {ln["account_code"]: ln for ln in j["lines"]}
        self.assertEqual(by_account["6000"]["debit"], "15.00")
        self.assertEqual(by_account["1000"]["credit"], "15.00")
        self.assertEqual(j["period_id"], "P1")
        self.assertEqual(j["source_id"], fee_line["id"])
        self.assertIsNotNone(j["approval_id"])
        self.assertEqual(c.ledger.balance("6000"), Decimal("15.00"))
        self.assertEqual(c.ledger.balance("1000"), Decimal("26980.00"))

        rec2 = b.reconciliation(oct2["id"])
        self.assertTrue(rec2["reconciled"])
        self.assertEqual(rec2["gl_balance"], "26980.00")
        self.assertEqual(rec2["difference"], "0.00")
        # the earlier statement is reconciled on its own view: the later fee is in transit for it
        rec1 = b.reconciliation(oct1["id"])
        self.assertTrue(rec1["reconciled"])
        self.assertEqual(rec1["difference"], "0.00")
        self.assertEqual(rec1["in_transit_total"], "-15.00")
        self.assertEqual(rec1["unmatched_gl_lines"][0]["matched_to_line"], fee_line["id"])

        status = b.reconciliation_status("P1")
        self.assertTrue(status["required"])
        self.assertFalse(status["reconciled"])
        self.assertFalse(b.close_checks("P1")[0]["ok"])

        for st in (oct1, oct2):
            res = c.approve_and_execute("banking.lock_reconciliation", st["id"], actor_role="accountant", actor="accountant", period_id="P1")
            self.assertEqual(res.result["status"], "locked")
            self.assertEqual(res.result["difference"], "0.00")
        self.assertEqual(b.statement(oct2["id"])["status"], "locked")
        snap = b.reconciliation(oct2["id"])["locked_reconciliation"]
        self.assertEqual(snap["difference"], "0.00")
        self.assertEqual(snap["gl_balance"], "26980.00")

        # locked: matches are frozen
        any_match = b.matches(oct2["id"])[0]
        with self.assertRaises(BankingError):
            b.unmatch(any_match["id"], "accountant")
        with self.assertRaises(BankingError):
            b.manual_match(fee_line["id"], s.pay_line, "accountant")
        with self.assertRaises(BankingError):
            b.auto_match(oct2["id"], "accountant")

        status = b.reconciliation_status("P1")
        self.assertTrue(status["reconciled"])
        self.assertEqual(len(status["statements"]), 2)
        self.assertEqual(b.close_checks("P1"), [{"check": "bank reconciliation", "ok": True, "detail": status["detail"]}])
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])


class StatementImportTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c, self.b = self.s.c, self.s.b

    def test_unbalanced_statement_rejected_and_nothing_imported(self):
        with self.assertRaises(BankingError) as cm:
            self.b.import_statement(statement_ref="BAD-1", period_id="P1", opening_balance="0.00", closing_balance="27000.00",
                                    lines=[dict(Scenario.PAY), dict(Scenario.RCV)], actor="accountant")
        self.assertIn("does not balance", str(cm.exception))
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM banking_statements"), 0)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM banking_lines"), 0)

    def test_duplicate_statement_ref_rejected_case_insensitively(self):
        self.s.october("OCT-2026")
        with self.assertRaises(BankingError):
            self.s.october("OCT-2026")
        with self.assertRaises(BankingError):
            self.s.october("oct-2026")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM banking_statements"), 1)

    def test_fingerprint_definition_and_normalisation(self):
        st = self.s.october()
        line = st["lines"][0]
        raw = "1000|2026-10-20|-27000.00|sim_000001|ach debit synthetic subcontractor a|0"
        self.assertEqual(line["fingerprint"], hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(line["fingerprint"], line_fingerprint("1000", "2026-10-20", "-27000.00", "SIM_000001", "  ACH  DEBIT synthetic subcontractor A ", 0))
        # the same line re-exported with different case and spacing is still the same line
        again = self.b.import_statement(statement_ref="OCT-2026-REEXPORT", period_id="P1", opening_balance="0.00", closing_balance="-27000.00",
                                        lines=[{"date": "2026-10-20", "amount": "-27,000.00", "description": "ach debit   Synthetic Subcontractor A", "reference": " SIM_000001 "}], actor="accountant")
        self.assertEqual(again["imported_count"], 0)
        self.assertEqual(again["skipped"][0]["duplicate_of_line_id"], line["id"])

    def test_identical_lines_are_told_apart_by_occurrence(self):
        fee = dict(Scenario.FEE)
        first = self.b.import_statement(statement_ref="A", period_id="P1", opening_balance="100.00", closing_balance="85.00", lines=[fee], actor="accountant")
        self.assertEqual(first["lines"][0]["occurrence"], 0)
        # a later export shows the same charge twice: the second is a genuinely new charge
        second = self.b.import_statement(statement_ref="B", period_id="P1", opening_balance="100.00", closing_balance="70.00", lines=[fee, dict(fee)], actor="accountant")
        self.assertEqual(second["imported_count"], 1)
        self.assertEqual(second["skipped_count"], 1)
        self.assertEqual(second["lines"][0]["occurrence"], 1)
        self.assertEqual(second["lines"][0]["line_no"], 2)
        self.assertNotEqual(second["lines"][0]["fingerprint"], first["lines"][0]["fingerprint"])
        # two identical lines inside one fresh statement are both imported
        third = self.b.import_statement(statement_ref="C", period_id="P1", opening_balance="0.00", closing_balance="-20.00",
                                        lines=[{"date": "2026-10-05", "amount": "-10.00", "description": "WIRE FEE"}] * 2, actor="accountant")
        self.assertEqual(third["imported_count"], 2)
        self.assertEqual([ln["occurrence"] for ln in third["lines"]], [0, 1])

    def test_statement_rows_lines_and_fingerprints_are_immutable(self):
        st = self.s.october()
        line_id = st["lines"][0]["id"]
        db = self.c.db
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE banking_lines SET amount='-1.00' WHERE id=?", (line_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE banking_lines SET fingerprint='x' WHERE id=?", (line_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("DELETE FROM banking_lines WHERE id=?", (line_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE banking_statements SET closing_balance='1.00' WHERE id=?", (st["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("DELETE FROM banking_statements WHERE id=?", (st["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE banking_statements SET status='locked' WHERE id=?", (st["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO banking_lines (id, statement_id, line_no, account_code, txn_date, amount, description, reference, occurrence, fingerprint, created_at) VALUES ('x', ?, 9, '1100', '2026-10-01', '1.00', 'x', '', 0, 'fp-x', 'now')",
                (st["id"],),
            )
        self.assertEqual(self.b.statement(st["id"])["lines"][0]["amount"], "-27000.00")

    def test_invalid_input_rejected(self):
        def imp(**overrides):
            kw = {"statement_ref": "X", "period_id": "P1", "opening_balance": "0.00", "closing_balance": "-15.00", "lines": [dict(Scenario.FEE)], "actor": "accountant"}
            kw.update(overrides)
            return self.b.import_statement(**kw)

        bad_lines = [
            [{**Scenario.FEE, "amount": -15.0}],                    # binary float
            [{**Scenario.FEE, "amount": "-15.001"}],                # sub-cent
            [{**Scenario.FEE, "amount": "abc"}],
            [{**Scenario.FEE, "amount": "NaN"}],
            [{**Scenario.FEE, "amount": "-1e27"}],                  # beyond the decimal context: no InvalidOperation leak
            [{**Scenario.FEE, "amount": "-1000000000000000.00"}],   # beyond the supported magnitude
            [{**Scenario.FEE, "date": "2026-02-30"}],               # not a calendar date
            [{**Scenario.FEE, "date": "10/31/2026"}],
            [{**Scenario.FEE, "date": "2026-11-01"}],               # after the period ends
            [{**Scenario.FEE, "description": "", "reference": ""}],
            ["not a line"],
        ]
        for lines in bad_lines:
            with self.assertRaises(BankingError, msg=repr(lines)):
                imp(lines=lines)
        with self.assertRaises(BankingError):
            imp(lines=[{**Scenario.FEE, "amount": "0.00"}], closing_balance="0.00")
        with self.assertRaises(BankingError):
            imp(lines="not a list")
        with self.assertRaises(BankingError):
            imp(statement_ref="  ")
        with self.assertRaises(BankingError):
            imp(account_code="1100")  # not a bank account
        with self.assertRaises(BankingError):
            imp(account_code="9999")
        with self.assertRaises(BankingError):
            imp(period_id="NOPE")
        with self.assertRaises(BankingError):
            imp(opening_balance=0.0)
        with self.assertRaises(BankingError):
            imp(opening_balance="1e27", closing_balance="1e27", lines=[])
        with self.assertRaises(BankingError):
            imp(end_date="2026-10-30")  # a line is dated after the explicit end date
        with self.assertRaises(BankingError):
            imp(lines=[], closing_balance="0.00", end_date="2026-09-30")  # end date outside the statement period
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM banking_statements"), 0)

    def test_import_into_closed_period_rejected(self):
        self.c.close_period("P1")
        with self.assertRaises(BankingError):
            self.s.october()
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM banking_statements"), 0)

    def test_new_lines_dated_before_the_period_are_reported(self):
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        self.c.close_period("P1")
        st = self.b.import_statement(statement_ref="NOV-2026", period_id="P2", opening_balance="0.00", closing_balance="-40.00", lines=[
            {"date": "2026-10-05", "amount": "-15.00", "description": "SERVICE FEE (BACK-VALUED)", "reference": "FEE-LATE"},
            {"date": "2026-11-03", "amount": "-25.00", "description": "WIRE FEE", "reference": "W-9"},
        ], actor="accountant")
        self.assertEqual(st["imported_count"], 2)
        self.assertEqual([(w["kind"], w["line_no"], w["period_id"], w["period_status"]) for w in st["warnings"]],
                         [("dated_before_statement_period", 1, "P1", "closed")])
        # the fee still books in the statement's own open period, never in the closed one
        res = self.c.approve_and_execute("banking.post_fee", st["lines"][0]["id"], period_id="P2")
        self.assertEqual(self.c.ledger.journal(res.result["journal_id"])["period_id"], "P2")
        self.assertTrue(self.c.audit.verify_chain()["ok"])


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c, self.b = self.s.c, self.s.b

    def _one_line(self, ref, amount, *, description="CHECK PAID", date="2026-10-15", statement_ref="S1"):
        return self.b.import_statement(statement_ref=statement_ref, period_id="P1", opening_balance="0.00", closing_balance=amount,
                                       lines=[{"date": date, "amount": amount, "description": description, "reference": ref}], actor="accountant")

    def test_equal_amounts_without_reference_are_ambiguous(self):
        g1 = self.s.pay_out("500.00", "Supplier payment")
        g2 = self.s.pay_out("500.00", "Supplier payment")
        st = self._one_line("chk 1001", "-500.00")
        line_id = st["lines"][0]["id"]
        run = self.b.auto_match(st["id"], "accountant")
        self.assertEqual(run["matched"], [])
        self.assertEqual(len(run["ambiguous"]), 1)
        self.assertEqual(run["ambiguous"][0]["line_id"], line_id)
        self.assertEqual(set(run["ambiguous"][0]["candidates"]), {g1, g2})
        self.assertEqual(self.b.statement(st["id"])["version"], 1)  # nothing changed
        rec = self.b.reconciliation(st["id"])
        self.assertFalse(rec["reconciled"])
        # a person resolves it; the other payment stays in transit
        self.b.manual_match(line_id, g2, "accountant")
        rec = self.b.reconciliation(st["id"])
        self.assertTrue(rec["reconciled"])
        self.assertEqual([g["journal_line_id"] for g in rec["unmatched_gl_lines"]], [g1])
        self.assertEqual(rec["in_transit_total"], "-500.00")
        self.assertEqual(rec["difference"], "0.00")

    def test_reference_disambiguates_equal_amounts(self):
        g1 = self.s.pay_out("500.00", "Supplier payment", memo="check chk 1001")
        g2 = self.s.pay_out("500.00", "Supplier payment chk 1002")
        st = self.b.import_statement(statement_ref="S1", period_id="P1", opening_balance="0.00", closing_balance="-1000.00", lines=[
            {"date": "2026-10-10", "amount": "-500.00", "description": "CHECK", "reference": "CHK 1002"},
            {"date": "2026-10-11", "amount": "-500.00", "description": "CHECK", "reference": "chk 1001"},
        ], actor="accountant")
        run = self.b.auto_match(st["id"], "accountant")
        pairs = {m["line_no"]: (m["journal_line_id"], m["basis"]) for m in run["matched"]}
        self.assertEqual(pairs, {1: (g2, "reference"), 2: (g1, "reference")})
        self.assertTrue(self.b.reconciliation(st["id"])["reconciled"])

    def test_reference_must_be_a_whole_token(self):
        decoy = self.s.pay_out("50.00", "Payment settled (sim_0000010)")
        real = self.s.pay_out("50.00", "Payment settled (sim_000001)")
        st = self._one_line("sim_000001", "-50.00")
        run = self.b.auto_match(st["id"], "accountant")
        self.assertEqual([(m["journal_line_id"], m["basis"]) for m in run["matched"]], [(real, "reference")])
        self.assertEqual([g["journal_line_id"] for g in self.b.reconciliation(st["id"])["unmatched_gl_lines"]], [decoy])

    def test_unique_amount_matches_without_reference_and_competing_lines_stay_ambiguous(self):
        dep = self.s.receive("100.00", "Counter deposit")
        st = self._one_line("", "100.00", description="DEPOSIT")
        run = self.b.auto_match(st["id"], "accountant")
        self.assertEqual([(m["journal_line_id"], m["basis"]) for m in run["matched"]], [(dep, "amount")])
        # two identical bank lines competing for one GL line: neither is guessed
        self.s.receive("70.00", "Counter deposit")
        st2 = self.b.import_statement(statement_ref="S2", period_id="P1", opening_balance="100.00", closing_balance="240.00",
                                      lines=[{"date": "2026-10-20", "amount": "70.00", "description": "DEPOSIT"}] * 2, actor="accountant")
        run = self.b.auto_match(st2["id"], "accountant")
        self.assertEqual(run["matched"], [])
        self.assertEqual(len(run["ambiguous"]), 2)

    def test_amount_fallback_never_takes_a_line_with_a_different_reference(self):
        other = self.s.pay_out("27000.00", "Payment settled (sim_000001)")
        st = self._one_line("sim_000999", "-27000.00", description="ACH DEBIT")
        line_id = st["lines"][0]["id"]
        run = self.b.auto_match(st["id"], "accountant")
        self.assertEqual(run["matched"], [])
        self.assertEqual(len(run["ambiguous"]), 1)
        self.assertIn("different reference (sim_000001)", run["ambiguous"][0]["reason"])
        self.assertEqual(run["ambiguous"][0]["candidates"], [other])
        # a neutral candidate of the same amount is still taken on amount
        neutral = self.s.pay_out("27000.00", "Supplier payment")
        run = self.b.auto_match(st["id"], "accountant")
        self.assertEqual([(m["journal_line_id"], m["basis"]) for m in run["matched"]], [(neutral, "amount")])
        # a person can still decide otherwise
        self.b.unmatch(self.b.matches(st["id"])[0]["id"], "accountant")
        self.assertEqual(self.b.manual_match(line_id, other, "accountant")["basis"], "manual")

    def test_gl_lines_in_later_periods_are_not_candidates(self):
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        later = self.s.pay_out("27000.00", "Payment settled (sim_000001)", period="P2")
        st = self._one_line("sim_000001", "-27000.00")
        run = self.b.auto_match(st["id"], "accountant")
        self.assertEqual(run["matched"], [])
        self.assertEqual(len(run["unmatched"]), 1)
        with self.assertRaises(BankingError):
            self.b.manual_match(st["lines"][0]["id"], later, "accountant")
        rec = self.b.reconciliation(st["id"])
        self.assertEqual(rec["gl_balance"], "0.00")  # P2 is outside the statement's scope
        self.assertEqual(rec["difference"], "-27000.00")

    def test_manual_match_enforces_account_sign_and_uniqueness(self):
        s = self.s
        s.golden_gl()
        st = s.october()
        pay_id, rcv_id = st["lines"][0]["id"], st["lines"][1]["id"]
        ap_line = self.c.db.scalar("SELECT id FROM journal_lines WHERE account_code='2000'")
        with self.assertRaises(BankingError):
            self.b.manual_match(pay_id, ap_line, "accountant")      # wrong account
        with self.assertRaises(BankingError):
            self.b.manual_match(rcv_id, s.pay_line, "accountant")   # wrong sign and amount
        reversed_sign = s.receive("27000.00", "Refund received")
        with self.assertRaises(BankingError):
            self.b.manual_match(pay_id, reversed_sign, "accountant")  # same magnitude, opposite sign
        with self.assertRaises(BankingError):
            self.b.manual_match("bln_missing", s.pay_line, "accountant")
        with self.assertRaises(BankingError):
            self.b.manual_match(pay_id, "jln_missing", "accountant")
        m = self.b.manual_match(pay_id, s.pay_line, "accountant")
        self.assertEqual(m["basis"], "manual")
        self.assertEqual(m["amount"], "-27000.00")
        with self.assertRaises(BankingError):
            self.b.manual_match(pay_id, s.pay_line, "accountant")   # line already matched
        other = self.b.import_statement(statement_ref="OTHER", period_id="P1", opening_balance="0.00", closing_balance="-27000.00",
                                        lines=[{"date": "2026-10-21", "amount": "-27000.00", "description": "ANOTHER DEBIT", "reference": "x-1"}], actor="accountant")
        with self.assertRaises(BankingError):
            self.b.manual_match(other["lines"][0]["id"], s.pay_line, "accountant")  # GL line already matched
        # the schema backs the rule even if the service check were bypassed
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute(
                "INSERT INTO banking_matches (id, statement_id, line_id, journal_line_id, amount, basis, status, matched_by, matched_at) VALUES ('bmt_x', ?, ?, ?, '-27000.00', 'manual', 'active', 'x', 'now')",
                (other["id"], other["lines"][0]["id"], s.pay_line),
            )
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_unmatch_releases_and_keeps_history(self):
        st = self.s.reconciled_october()
        version = self.b.statement(st["id"])["version"]
        m = self.b.matches(st["id"])[0]
        released = self.b.unmatch(m["id"], "accountant")
        self.assertEqual(released["status"], "released")
        self.assertEqual(released["released_by"], "accountant")
        self.assertEqual(self.b.statement(st["id"])["version"], version + 1)
        rec = self.b.reconciliation(st["id"])
        self.assertFalse(rec["reconciled"])
        self.assertEqual(len(rec["unmatched_statement_lines"]), 1)
        with self.assertRaises(BankingError):
            self.b.unmatch(m["id"], "accountant")  # already released
        again = self.b.manual_match(m["line_id"], m["journal_line_id"], "accountant")
        self.assertNotEqual(again["id"], m["id"])
        self.assertTrue(self.b.reconciliation(st["id"])["reconciled"])
        self.assertEqual(len(self.b.matches(st["id"], include_released=True)), 3)
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("DELETE FROM banking_matches WHERE id=?", (m["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("UPDATE banking_matches SET status='active' WHERE id=?", (m["id"],))

    def test_payment_without_statement_line_is_in_transit(self):
        st = self.s.reconciled_october()
        outstanding = self.s.pay_out("1200.00", "Payment settled (sim_000002)")
        rec = self.b.reconciliation(st["id"])
        self.assertEqual([g["journal_line_id"] for g in rec["unmatched_gl_lines"]], [outstanding])
        self.assertEqual(rec["unmatched_gl_lines"][0]["amount"], "-1200.00")
        self.assertEqual(rec["gl_balance"], "25795.00")
        self.assertEqual(rec["in_transit_total"], "-1200.00")
        self.assertEqual(rec["adjusted_gl_balance"], "26995.00")
        self.assertEqual(rec["difference"], "0.00")
        self.assertTrue(rec["reconciled"])

    def test_overlapping_statement_covers_repeated_lines(self):
        self.s.golden_gl()
        oct1 = self.s.october()
        oct2 = self.s.october_with_fee()
        rec2 = self.b.reconciliation(oct2["id"])
        # the repeated lines belong to the first statement but the second still has to account for them
        owners = {u["statement_id"] for u in rec2["unmatched_statement_lines"]}
        self.assertEqual(owners, {oct1["id"], oct2["id"]})
        self.assertEqual(len(rec2["unmatched_statement_lines"]), 3)
        self.b.auto_match(oct1["id"], "accountant")
        self.c.approve_and_execute("banking.post_fee", oct2["lines"][0]["id"], period_id="P1")
        self.c.approve_and_execute("banking.lock_reconciliation", oct2["id"], period_id="P1")
        # oct1 is still open, but its matches are now evidence for the locked oct2 reconciliation
        m = self.b.matches(oct1["id"])[0]
        with self.assertRaises(BankingError):
            self.b.unmatch(m["id"], "accountant")
        # ... and the schema backs that even if the service check were bypassed
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("UPDATE banking_matches SET status='released', released_by='x', released_at='now' WHERE id=?", (m["id"],))
        self.assertEqual(self.b.match(m["id"])["status"], "active")


class FeeAndLockTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c, self.b = self.s.c, self.s.b
        self.s.golden_gl()
        self.oct1 = self.s.october()
        self.b.auto_match(self.oct1["id"], "accountant")
        self.oct2 = self.s.october_with_fee()
        self.fee_line = self.oct2["lines"][0]

    def test_post_fee_only_for_unmatched_withdrawals(self):
        with self.assertRaises(BankingError):
            self.c.request_approval("banking.post_fee", self.oct1["lines"][1]["id"])  # deposit (and matched)
        with self.assertRaises(BankingError):
            self.c.request_approval("banking.post_fee", self.oct1["lines"][0]["id"])  # matched withdrawal
        with self.assertRaises(BankingError):
            self.c.request_approval("banking.post_fee", "bln_missing")
        self.c.approve_and_execute("banking.post_fee", self.fee_line["id"], period_id="P1")
        with self.assertRaises(BankingError):
            self.c.approve_and_execute("banking.post_fee", self.fee_line["id"], period_id="P1")  # already booked
        self.assertEqual(self.c.ledger.balance("6000"), Decimal("15.00"))
        self.assertEqual(len(self.c.ledger.journals(source_type="banking_line")), 1)

    def test_fee_is_never_booked_twice_after_its_match_is_released(self):
        c, b = self.c, self.b
        res = c.approve_and_execute("banking.post_fee", self.fee_line["id"], period_id="P1")
        b.unmatch(res.result["match_id"], "accountant")
        with self.assertRaises(BankingError) as cm:
            c.request_approval("banking.post_fee", self.fee_line["id"])
        self.assertIn("already booked", str(cm.exception))
        self.assertIn(res.result["journal_id"], str(cm.exception))
        self.assertEqual(c.ledger.balance("6000"), Decimal("15.00"))
        self.assertFalse(b.reconciliation(self.oct2["id"])["reconciled"])
        # the remedy is to re-match the line to the fee already booked
        b.manual_match(self.fee_line["id"], res.result["journal_line_id"], "accountant")
        rec = b.reconciliation(self.oct2["id"])
        self.assertTrue(rec["reconciled"])
        self.assertEqual(rec["in_transit_total"], "0.00")
        # a fee journal that was reversed no longer counts: booking it again is legitimate
        b.unmatch(b.lines(self.oct2["id"])[0]["match_id"], "accountant")
        c.ledger.reverse(res.result["journal_id"], period_id="P1", posted_by="accountant", reason="booked against the wrong line")
        again = c.approve_and_execute("banking.post_fee", self.fee_line["id"], period_id="P1")
        self.assertNotEqual(again.result["journal_id"], res.result["journal_id"])
        self.assertEqual(c.ledger.balance("6000"), Decimal("15.00"))
        self.assertEqual(c.ledger.balance("1000"), Decimal("26980.00"))
        rec = b.reconciliation(self.oct2["id"])
        self.assertTrue(rec["reconciled"])
        self.assertEqual(rec["in_transit_total"], "0.00")  # the reversed pair nets to nil
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_fee_approval_goes_stale_when_the_fee_is_booked_by_hand(self):
        c, b = self.c, self.b
        ap = c.request_approval("banking.post_fee", self.fee_line["id"], actor_role="accountant")
        c.approve(ap["id"])
        by_hand = self.s._post("P1", "Monthly service charge", [
            {"account": "6000", "debit": "15.00", "memo": "bank charge"},
            {"account": "1000", "credit": "15.00", "memo": "bank charge"},
        ])
        with self.assertRaises(StaleApprovalError):
            c.execute(ap["id"], period_id="P1")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(c.ledger.balance("6000"), Decimal("15.00"))  # the hand entry only
        with self.assertRaises(BankingError):
            c.request_approval("banking.post_fee", self.fee_line["id"])
        b.manual_match(self.fee_line["id"], by_hand, "accountant")
        self.assertTrue(b.reconciliation(self.oct2["id"])["reconciled"])
        # a GL line carrying the statement line's reference is the same charge too
        st = b.import_statement(statement_ref="OCT-WIRE", period_id="P1", opening_balance="0.00", closing_balance="-25.00",
                                lines=[{"date": "2026-10-29", "amount": "-25.00", "description": "OUTGOING WIRE CHARGE", "reference": "WIRE-77"}], actor="accountant")
        self.s.pay_out("25.00", "Wire charge WIRE-77 recharged by vendor")
        with self.assertRaises(BankingError):
            c.request_approval("banking.post_fee", st["lines"][0]["id"])
        self.assertEqual(c.ledger.balance("6000"), Decimal("15.00"))

    def test_other_equal_amount_gl_lines_are_bound_into_the_fee_manifest(self):
        c = self.c
        courier = self.s.pay_out("15.00", "Courier invoice paid")
        ap = c.request_approval("banking.post_fee", self.fee_line["id"], actor_role="accountant")
        self.assertEqual([o["journal_line_id"] for o in ap["manifest"]["bindings"]["unmatched_equal_amount_gl_lines"]], [courier])
        c.approve(ap["id"])
        self.s.pay_out("15.00", "Parking permit paid")  # a new candidate the approver never saw
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            c.execute(ap["id"], period_id="P1")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(c.ledger.balance("6000"), Decimal("0.00"))
        res = c.approve_and_execute("banking.post_fee", self.fee_line["id"], period_id="P1")
        self.assertEqual(res.result["fee"], "15.00")
        self.assertEqual(c.ledger.balance("6000"), Decimal("15.00"))

    def test_fee_manifest_binding_and_no_false_staleness(self):
        ap = self.c.request_approval("banking.post_fee", self.fee_line["id"], actor_role="accountant")
        self.c.approve(ap["id"])
        m = ap["manifest"]
        self.assertEqual(m["amounts"], {"fee": "15.00", "line_amount": "-15.00"})
        self.assertEqual(m["bindings"]["line_fingerprint"], self.fee_line["fingerprint"])
        self.assertEqual(m["bindings"]["period_id"], "P1")
        self.assertEqual(m["bindings"]["statement_version"], self.b.statement(self.oct2["id"])["version"])
        self.assertEqual(m["bindings"]["unmatched_equal_amount_gl_lines"], [])
        # match changes on a different statement leave this approval valid
        deposit = self.s.receive("250.00", "Owner transfer in")
        extra = self.b.import_statement(statement_ref="EXTRA", period_id="P1", opening_balance="0.00", closing_balance="250.00",
                                        lines=[{"date": "2026-10-02", "amount": "250.00", "description": "TRANSFER IN"}], actor="accountant")
        self.b.manual_match(extra["lines"][0]["id"], deposit, "accountant")
        self.b.unmatch(self.b.matches(self.oct1["id"])[0]["id"], "accountant")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")
        # an auto-match run that matches nothing does not move the statement version either
        version = self.b.statement(self.oct2["id"])["version"]
        self.b.auto_match(self.oct2["id"], "accountant")
        self.assertEqual(self.b.statement(self.oct2["id"])["version"], version)
        res = self.c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual(res.result["fee"], "15.00")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "consumed")
        self.assertEqual(self.b.statement(self.oct2["id"])["version"], version + 1)

    def test_fee_approval_stale_after_match_set_change_on_its_statement(self):
        # second fee line on the same statement so the match set can change without touching the subject
        st = self.b.import_statement(statement_ref="OCT-FEES", period_id="P1", opening_balance="0.00", closing_balance="-40.00", lines=[
            {"date": "2026-10-30", "amount": "-25.00", "description": "WIRE FEE", "reference": "W-1"},
            {"date": "2026-10-31", "amount": "-15.00", "description": "SERVICE FEE", "reference": "S-1"},
        ], actor="accountant")
        wire_line, service_line = st["lines"]
        booked = self.s.pay_out("25.00", "Wire fee booked W-1")
        ap = self.c.request_approval("banking.post_fee", service_line["id"], actor_role="accountant")
        self.c.approve(ap["id"])
        self.b.manual_match(wire_line["id"], booked, "accountant")  # statement version moves on
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.c.ledger.balance("6000"), Decimal("0.00"))

    def test_fee_approval_invalidated_when_its_line_is_matched(self):
        ap = self.c.request_approval("banking.post_fee", self.fee_line["id"], actor_role="accountant")
        self.c.approve(ap["id"])
        already = self.s.pay_out("15.00", "Service fee booked by hand")
        self.b.manual_match(self.fee_line["id"], already, "accountant")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises((BankingError, ApprovalNotGranted)):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.ledger.balance("6000"), Decimal("0.00"))
        self.assertTrue(self.b.reconciliation(self.oct2["id"])["reconciled"])

    def test_fee_posting_into_closed_or_other_period_rejected(self):
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        ap = self.c.request_approval("banking.post_fee", self.fee_line["id"], actor_role="accountant")
        self.c.approve(ap["id"])
        with self.assertRaises(BankingError):
            self.c.execute(ap["id"], period_id="P2")  # a fee posts in the statement's own period only
        self.c.close_period("P1")
        with self.assertRaises(BankingError):
            self.c.execute(ap["id"], period_id="P1")
        with self.assertRaises(BankingError):
            self.c.request_approval("banking.post_fee", self.fee_line["id"])
        self.assertEqual(self.c.ledger.balance("6000"), Decimal("0.00"))
        self.assertFalse(self.b.lines(self.oct2["id"])[0]["matched"])
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])

    def test_ricky_previews_fee_for_accountant_and_abstains_for_pm(self):
        proposal = self.c.ricky.propose("banking.post_fee", actor_role="accountant", context={"line_id": self.fee_line["id"]})
        self.assertEqual(proposal["decision"], "proposed")
        self.assertEqual(proposal["manifest"]["amounts"]["fee"], "15.00")
        self.assertEqual(self.c.ricky.propose("banking.post_fee", actor_role="pm", context={"line_id": self.fee_line["id"]})["decision"], "abstained")
        self.assertEqual(self.c.ricky.propose("banking.lock_reconciliation", actor_role="accountant", context={"statement_id": self.oct2["id"]})["decision"], "abstained")
        self.assertEqual(self.c.ledger.balance("6000"), Decimal("0.00"))  # Ricky never executes

    def test_lock_requires_reconciled_statement(self):
        with self.assertRaises(BankingError):
            self.c.request_approval("banking.lock_reconciliation", self.oct2["id"])
        with self.assertRaises(BankingError):
            self.c.request_approval("banking.lock_reconciliation", "bst_missing")
        self.assertEqual(self.b.statement(self.oct2["id"])["status"], "open")

    def test_lock_approval_stale_when_reconciliation_changes(self):
        ap = self.c.request_approval("banking.lock_reconciliation", self.oct1["id"], actor_role="accountant")
        self.c.approve(ap["id"])
        self.assertEqual(ap["manifest"]["amounts"]["difference"], "0.00")
        self.assertIn("match_set_hash", ap["manifest"]["bindings"])
        # a new outstanding payment: still reconciled, but not the reconciliation that was approved
        self.s.pay_out("1200.00", "Payment settled (sim_000002)")
        self.assertTrue(self.b.reconciliation(self.oct1["id"])["reconciled"])
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.b.statement(self.oct1["id"])["status"], "open")
        # re-matching the same pair still changes the statement: the open approval is dropped
        ap2 = self.c.request_approval("banking.lock_reconciliation", self.oct1["id"], actor_role="accountant")
        self.c.approve(ap2["id"])
        m = self.b.matches(self.oct1["id"])[0]
        self.b.unmatch(m["id"], "accountant")
        self.b.manual_match(m["line_id"], m["journal_line_id"], "accountant")
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap2["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap2["id"])["status"], "invalidated")
        res = self.c.approve_and_execute("banking.lock_reconciliation", self.oct1["id"], actor_role="accountant", period_id="P1")
        self.assertEqual(res.result["in_transit_total"], "-1200.00")

    def test_lock_freezes_matches_at_schema_level(self):
        res = self.c.approve_and_execute("banking.lock_reconciliation", self.oct1["id"], actor_role="accountant", period_id="P1")
        rid = res.result["reconciliation_id"]
        db = self.c.db
        m = self.b.matches(self.oct1["id"])[0]
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE banking_matches SET status='released', released_by='x', released_at='now' WHERE id=?", (m["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("DELETE FROM banking_matches WHERE id=?", (m["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE banking_statements SET version=version+1 WHERE id=?", (self.oct1["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE banking_reconciliations SET difference='0.00' WHERE id=?", (rid,))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("DELETE FROM banking_reconciliations WHERE id=?", (rid,))
        with self.assertRaises(BankingError):
            self.b.unmatch(m["id"], "accountant")
        with self.assertRaises(BankingError):
            self.c.request_approval("banking.lock_reconciliation", self.oct1["id"])  # already locked
        snap = db.one("SELECT * FROM banking_reconciliations WHERE id=?", (rid,))
        self.assertEqual(snap["statement_closing"], "26995.00")
        self.assertEqual(snap["difference"], "0.00")
        self.assertEqual(snap["statement_hash"], self.b.statement(self.oct1["id"])["content_hash"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])


class ReconciliationViewTests(unittest.TestCase):
    """Which bank activity a statement sees, opening balances, and the locked-evidence freeze."""

    def setUp(self):
        self.s = Scenario()
        self.c, self.b = self.s.c, self.s.b

    def lock(self, statement_id, period_id="P1"):
        return self.c.approve_and_execute("banking.lock_reconciliation", statement_id, actor_role="accountant", period_id=period_id)

    def test_same_day_transaction_on_a_later_export_does_not_break_the_earlier_statement(self):
        c, b, s = self.c, self.b, self.s
        oct1 = s.reconciled_october()  # lines dated 10-20 and 10-24: cutoff 10-24
        late = s.pay_out("100.00", "Payment settled (sim_000002)")
        oct3 = b.import_statement(statement_ref="OCT-2026-LATE", period_id="P1", opening_balance="0.00", closing_balance="26895.00", lines=[
            dict(Scenario.PAY), dict(Scenario.RCV),
            {"date": "2026-10-24", "amount": "-100.00", "description": "ACH DEBIT LATER SAME DAY", "reference": "sim_000002"},
        ], actor="accountant")
        self.assertEqual(oct3["imported_count"], 1)
        new_line = oct3["lines"][0]["id"]
        run = b.auto_match(oct3["id"], "accountant")
        self.assertEqual([(m["line_id"], m["journal_line_id"]) for m in run["matched"]], [(new_line, late)])
        rec1 = b.reconciliation(oct1["id"])
        self.assertTrue(rec1["reconciled"])
        self.assertEqual(rec1["difference"], "0.00")
        self.assertEqual(rec1["in_transit_total"], "-100.00")
        self.assertEqual(rec1["unmatched_gl_lines"][0]["matched_to_line"], new_line)
        rec3 = b.reconciliation(oct3["id"])
        self.assertTrue(rec3["reconciled"])
        self.assertEqual(rec3["in_transit_total"], "0.00")
        for st in (oct1, oct3):
            self.assertEqual(self.lock(st["id"]).result["difference"], "0.00")
        self.assertTrue(b.reconciliation_status("P1")["reconciled"])

    def test_statements_imported_out_of_order_within_a_period_both_reconcile(self):
        b, s = self.b, self.s
        dep = s.receive("1000.00", "Counter deposit")
        chk = s.pay_out("300.00", "Check 501 paid")
        second_half = b.import_statement(statement_ref="OCT-B", period_id="P1", opening_balance="1000.00", closing_balance="700.00",
                                         lines=[{"date": "2026-10-20", "amount": "-300.00", "description": "CHECK PAID", "reference": "501"}], actor="accountant")
        b.auto_match(second_half["id"], "accountant")
        rec_b = b.reconciliation(second_half["id"])
        self.assertFalse(rec_b["reconciled"])
        self.assertEqual(rec_b["difference"], "1000.00")  # the first half has not been imported yet
        first_half = b.import_statement(statement_ref="OCT-A", period_id="P1", opening_balance="0.00", closing_balance="1000.00",
                                        lines=[{"date": "2026-10-05", "amount": "1000.00", "description": "COUNTER DEPOSIT"}], actor="accountant")
        self.assertEqual([m["journal_line_id"] for m in b.auto_match(first_half["id"], "accountant")["matched"]], [dep])
        rec_b = b.reconciliation(second_half["id"])
        self.assertTrue(rec_b["reconciled"])  # the deposit predates its first line: it is in its opening balance
        self.assertEqual(rec_b["in_transit_total"], "0.00")
        rec_a = b.reconciliation(first_half["id"])
        self.assertTrue(rec_a["reconciled"])
        self.assertEqual([g["journal_line_id"] for g in rec_a["unmatched_gl_lines"]], [chk])
        self.assertEqual(rec_a["in_transit_total"], "-300.00")

    def test_a_locked_later_statement_freezes_the_matches_it_rests_on(self):
        c, b, s = self.c, self.b, self.s
        oct1 = s.reconciled_october()
        outstanding = s.pay_out("500.00", "Payment settled (sim_000003)")
        c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        nov = b.import_statement(statement_ref="NOV-2026", period_id="P2", opening_balance="26995.00", closing_balance="26995.00", lines=[], actor="accountant")
        rec = b.reconciliation(nov["id"])
        self.assertTrue(rec["reconciled"])
        self.assertEqual(rec["in_transit_total"], "-500.00")
        self.assertEqual(self.lock(nov["id"], "P2").result["evidence_matches"], 2)
        # October is still open, but November's locked figures rest on its matches
        m = b.matches(oct1["id"])[0]
        with self.assertRaises(BankingError) as cm:
            b.unmatch(m["id"], "accountant")
        self.assertIn("NOV-2026", str(cm.exception))
        with self.assertRaises(sqlite3.IntegrityError):
            c.db.execute("UPDATE banking_matches SET status='released', released_by='x', released_at='now' WHERE id=?", (m["id"],))
        # a late October line that would clear the payment November carried in transit is refused
        supp = b.import_statement(statement_ref="OCT-2026-SUPP", period_id="P1", opening_balance="26995.00", closing_balance="26495.00",
                                  lines=[{"date": "2026-10-28", "amount": "-500.00", "description": "ACH DEBIT", "reference": "sim_000003"}], actor="accountant")
        run = b.auto_match(supp["id"], "accountant")
        self.assertEqual(run["matched"], [])
        self.assertIn("NOV-2026", run["unmatched"][0]["reason"])
        with self.assertRaises(BankingError):
            b.manual_match(supp["lines"][0]["id"], outstanding, "accountant")
        rec = b.reconciliation(nov["id"])
        self.assertTrue(rec["reconciled"])
        self.assertEqual(rec["difference"], "0.00")
        self.assertTrue(b.reconciliation_status("P2")["reconciled"])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_opening_balance_items_let_a_first_statement_with_history_reconcile(self):
        c, b, s = self.c, self.b, self.s
        opening = s._post("P1", "Opening bank balance", [
            {"account": "1000", "debit": "10000.00", "memo": "opening balance"},
            {"account": "3000", "credit": "10000.00", "memo": "owner equity"},
        ])
        uncleared = s.receive("2500.00", "Deposit not yet cleared")
        st = b.import_statement(statement_ref="OCT-2026", period_id="P1", opening_balance="10000.00", closing_balance="9985.00",
                                lines=[dict(Scenario.FEE)], actor="accountant")
        fee = c.approve_and_execute("banking.post_fee", st["lines"][0]["id"], period_id="P1")
        rec = b.reconciliation(st["id"])
        self.assertFalse(rec["reconciled"])
        self.assertEqual(rec["difference"], "10000.00")
        for bad in ([], [uncleared], [opening, opening], ["jln_missing"], [fee.result["journal_line_id"]], "not a list"):
            with self.assertRaises(BankingError, msg=repr(bad)):
                b.clear_opening_balance(st["id"], bad, "accountant")
        version = b.statement(st["id"])["version"]
        res = b.clear_opening_balance(st["id"], [opening], "accountant")
        self.assertEqual(res["opening_items"][0]["amount"], "10000.00")
        self.assertEqual(res["statement_version"], version + 1)
        rec = b.reconciliation(st["id"])
        self.assertTrue(rec["reconciled"])
        self.assertEqual(rec["gl_balance"], "12485.00")
        self.assertEqual(rec["opening_items_total"], "10000.00")
        self.assertEqual([g["journal_line_id"] for g in rec["unmatched_gl_lines"]], [uncleared])
        self.assertEqual(rec["adjusted_gl_balance"], "9985.00")
        # an opening item is a match like any other: released while open, frozen once locked
        item = res["opening_items"][0]["match_id"]
        b.unmatch(item, "accountant")
        self.assertFalse(b.reconciliation(st["id"])["reconciled"])
        b.clear_opening_balance(st["id"], [opening], "accountant")
        self.lock(st["id"])
        with self.assertRaises(BankingError):
            b.unmatch(b.reconciliation(st["id"])["opening_items"][0]["match_id"], "accountant")
        # later statements see the opening items; only the earliest statement may designate them
        c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        nov = b.import_statement(statement_ref="NOV-2026", period_id="P2", opening_balance="9985.00", closing_balance="9985.00", lines=[], actor="accountant")
        self.assertTrue(b.reconciliation(nov["id"])["reconciled"])
        with self.assertRaises(BankingError):
            b.clear_opening_balance(nov["id"], [uncleared], "accountant")
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])


class StatusAndStateTests(unittest.TestCase):
    def test_reconciliation_status_and_close_checks(self):
        s = Scenario()
        c, b = s.c, s.b
        status = b.reconciliation_status("P1")
        self.assertFalse(status["required"])
        self.assertFalse(status["reconciled"])
        self.assertEqual(b.close_checks("P1")[0]["ok"], True)
        s.golden_gl()  # bank activity without a statement
        status = b.reconciliation_status("P1")
        self.assertTrue(status["required"])
        self.assertFalse(status["reconciled"])
        self.assertIn("no bank statement", status["detail"])
        self.assertFalse(b.close_checks("P1")[0]["ok"])
        st = s.october()
        b.auto_match(st["id"], "accountant")
        status = b.reconciliation_status("P1")
        self.assertFalse(status["reconciled"])  # reconciled but not locked
        self.assertTrue(status["statements"][0]["reconciled"])
        c.approve_and_execute("banking.lock_reconciliation", st["id"], period_id="P1")
        status = b.reconciliation_status("P1")
        self.assertTrue(status["reconciled"])
        self.assertTrue(b.close_checks("P1")[0]["ok"])
        # a statement alone makes the check required even without GL activity
        c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        b.import_statement(statement_ref="NOV-2026", period_id="P2", opening_balance="26995.00", closing_balance="26995.00", lines=[], actor="accountant")
        status = b.reconciliation_status("P2")
        self.assertTrue(status["required"])
        self.assertFalse(status["reconciled"])
        with self.assertRaises(BankingError):
            b.reconciliation_status("NOPE")

    def test_state_shape_is_json_serialisable(self):
        s = Scenario()
        st = s.reconciled_october()
        state = s.b.state(s.project["id"])
        self.assertEqual(state["scope"], "entity")
        self.assertEqual(len(state["statements"]), 1)
        summary = state["statements"][0]
        self.assertEqual(summary["id"], st["id"])
        self.assertEqual(len(summary["matches"]), 2)
        self.assertTrue(summary["reconciliation"]["reconciled"])
        self.assertIn("P1", state["periods"])
        self.assertFalse(state["periods"]["P1"]["reconciled"])
        json.dumps(state)
        json.dumps(s.c.project_state(s.project["id"])["banking"])


class CoreFlowIntegrationTests(unittest.TestCase):
    def test_golden_fixture_bank_movements_reconcile(self):
        c = Cipher()
        run_golden_fixture(c)
        b = c.plugin(PLUGIN_NAME)
        self.assertEqual(b.reconciliation_status("2026-10")["required"], True)
        st = b.import_statement(statement_ref="NOV-2026", period_id="2026-11", opening_balance="0.00", closing_balance="-27005.00", lines=[
            {"date": "2026-10-28", "amount": "53995.00", "description": "ACH CREDIT SYNTHETIC OWNER AGENCY", "reference": "ach_sim_rcv_0001"},
            {"date": "2026-11-02", "amount": "-27000.00", "description": "ACH DEBIT SYNTHETIC SUBCONTRACTOR A", "reference": "sim_000001"},
            {"date": "2026-11-05", "amount": "-54000.00", "description": "ACH RETURN R01", "reference": "ach_sim_rcv_0001"},
        ], actor="accountant")
        run = b.auto_match(st["id"], "accountant")
        self.assertEqual(len(run["matched"]), 3)
        self.assertEqual({m["basis"] for m in run["matched"]}, {"reference"})
        rec = b.reconciliation(st["id"])
        self.assertEqual(rec["gl_balance"], "-27005.00")
        self.assertEqual(rec["difference"], "0.00")
        self.assertTrue(rec["reconciled"])
        c.approve_and_execute("banking.lock_reconciliation", st["id"], actor_role="accountant", period_id="2026-11")
        self.assertTrue(b.reconciliation_status("2026-11")["reconciled"])
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])


if __name__ == "__main__":
    unittest.main()
