"""The deterministic 20-bill corpus (``python -m apps.cipher.tools.corpus``): its exact metrics
report, the ledger invariants it leaves, and that the simulated times come from the system's
clock abstraction.

Every figure below follows from the corpus's literal data and fixed durations; a change to a
module that alters how many approvals a bill needs, who may grant them, what is held or how
long a release waits shows up here as a changed number."""
import contextlib
import datetime as _dt
import io
import json
import os
import tempfile
import unittest
from decimal import Decimal

from apps.cipher.core.ids import parse_iso
from apps.cipher.tools import corpus as corpus_mod
from apps.cipher.tools.corpus import CORPUS, COOLING_DAYS, OWNER, Corpus, main

D = Decimal

EXPECTED_SUMMARY = {
    "format": "cipher-corpus/1",
    "items": 20,
    "released": 19,
    "blocked_items": 1,
    "released_total": "405700.00",
    "approvals": {
        "requested": 61, "consumed": 61, "invalidated": 0,
        "by_operation": {"ap_intake.match_invoice": 20, "bill.approve": 20, "bill.correct": 1, "bill.credit_note": 1, "payment.release": 19},
        "routed_to_owner": 10, "routed_to_others": 51, "owner_share": "0.16", "per_released_bill": "3.21",
        "wait_minutes": {"owner": 3600, "others": 5280},
    },
    "held": {"possible_duplicate_review": 1, "cooling_off": 1, "cosignature_required": 1, "step_up_required": 2},
    "blocked": {"duplicate_invoice": 1},
    "release_classification": {"high_risk": 2, "standard": 17},
    "intake_to_release_minutes": {"count": 19, "min": 615, "max": 2610, "total": 18761, "mean": "987.42", "median": "615.00"},
    "simulated_span_minutes": 39585,
}
# item: (status, approvals, routed to owner, held, blocked, released, classification, intake-to-release minutes)
EXPECTED_BILLS = {
    1: ("released", 3, 2, {}, {}, "27000.00", "standard", 1155),
    2: ("released", 3, 0, {}, {}, "18000.00", "standard", 615),
    3: ("released", 3, 2, {}, {}, "45000.00", "standard", 1155),
    4: ("released", 3, 2, {"cosignature_required": 1, "step_up_required": 1}, {}, "81000.00", "high_risk", 2600),
    5: ("released", 3, 2, {"cooling_off": 1, "step_up_required": 1}, {}, "28500.00", "high_risk", 1386),
    6: ("released", 3, 2, {}, {}, "38000.00", "standard", 1155),
    7: ("released", 3, 0, {}, {}, "9000.00", "standard", 615),
    8: ("blocked", 0, 0, {}, {"duplicate_invoice": 1}, None, None, None),
    9: ("released", 4, 0, {}, {}, "12000.00", "standard", 810),
    10: ("released", 6, 0, {}, {}, "14400.00", "standard", 2610),
    11: ("released", 3, 0, {}, {}, "12000.00", "standard", 615),
    12: ("released", 3, 0, {}, {}, "24000.00", "standard", 615),
    13: ("released", 3, 0, {}, {}, "10000.00", "standard", 615),
    14: ("released", 3, 0, {"possible_duplicate_review": 1}, {}, "10000.00", "standard", 1125),
    15: ("released", 3, 0, {}, {}, "10800.00", "standard", 615),
    16: ("released", 3, 0, {}, {}, "7200.00", "standard", 615),
    17: ("released", 3, 0, {}, {}, "11400.00", "standard", 615),
    18: ("released", 3, 0, {}, {}, "11400.00", "standard", 615),
    19: ("released", 3, 0, {}, {}, "18000.00", "standard", 615),
    20: ("released", 3, 0, {}, {}, "18000.00", "standard", 615),
}
EXPECTED_LEDGER = {
    "trial_balance_balanced": True, "journals_balanced": True,
    "ap_reconciled": True, "ap_open": "0.00",
    "retainage_reconciled": True, "retainage_payable": "31800.00",
    "stored_materials_reconciled": True, "stored_materials": "0.00",
    "provider_clearing_reconciled": True,
    # bank: every release; cost: 439,000 certified gross less the 1,500 credit note = releases + retainage held
    "balances": {"1000": "-405700.00", "1200": "0.00", "1300": "0.00", "2000": "0.00", "2050": "31800.00", "5000": "437500.00"},
    "payment_intents": 19, "settled": 19, "unique_provider_refs": True,
    "bills_paid": 19, "bills_corrected": 1, "invoices_matched": 19, "open_approvals": 0,
    "payment_policy_intact": True, "audit_chain_ok": True,
}


class CorpusTests(unittest.TestCase):
    corpus: Corpus | None = None
    report: dict | None = None

    @classmethod
    def setUpClass(cls):
        cls.corpus = Corpus()
        cls.report = cls.corpus.run()

    def test_the_corpus_is_twenty_literal_bills_covering_every_scenario(self):
        self.assertEqual([s["item"] for s in CORPUS], list(range(1, 21)))
        tags = {t for s in CORPUS for t in s["tags"]}
        self.assertTrue({"retainage", "stored_material", "stored_transfer", "purchase_order", "duplicate", "near_duplicate", "credit_note",
                         "correction", "high_risk_payment", "new_destination_payment"} <= tags)
        self.assertEqual({s["kind"] for s in CORPUS}, {"pay_app", "po_invoice", "duplicate"})

    def test_summary_metrics_are_exact(self):
        summary = {k: v for k, v in self.report.items() if k not in ("per_bill", "ledger")}
        self.assertEqual(summary, EXPECTED_SUMMARY)

    def test_per_bill_metrics_are_exact(self):
        got = {}
        for row in self.report["per_bill"]:
            got[row["item"]] = (row["status"], row["approvals_total"], row["routed_to_owner"], row["held"], row["blocked"], row.get("released"),
                                row.get("classification"), row.get("intake_to_release_minutes"))
            self.assertEqual(row["routed_to_owner"] + row["routed_to_others"], row["approvals_total"], row["item"])
            self.assertEqual(row["invoice"], CORPUS[row["item"] - 1]["invoice"])
        self.assertEqual(got, EXPECTED_BILLS)
        rows = {row["item"]: row for row in self.report["per_bill"]}
        self.assertEqual(rows[9]["approvals"], {"ap_intake.match_invoice": 1, "bill.approve": 1, "bill.credit_note": 1, "payment.release": 1})
        self.assertEqual(rows[10]["approvals"], {"ap_intake.match_invoice": 2, "bill.approve": 2, "bill.correct": 1, "payment.release": 1})
        self.assertEqual(rows[4]["intake_to_release_hours"], "43.33")
        # what the routing costs: a bill the owner approves twice waits 840 minutes for approvals, a staff-routed one 300
        self.assertEqual({rows[i]["approval_wait_minutes"] for i in (1, 3, 4, 5, 6)}, {840})
        self.assertEqual({rows[i]["approval_wait_minutes"] for i in (2, 7, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20)}, {300})

    def test_ledger_invariants_hold(self):
        self.assertEqual(self.report["ledger"], EXPECTED_LEDGER)
        c = self.corpus.c
        for j in c.ledger.journals():
            dr = sum(D(ln["debit"]) for ln in j["lines"])
            cr = sum(D(ln["credit"]) for ln in j["lines"])
            self.assertEqual(dr, cr, j["id"])
            if j["approval_id"]:
                self.assertEqual(c.approvals.get(j["approval_id"])["status"], "consumed", j["id"])
            else:
                self.assertEqual(j["source_type"], "provider_event", j["id"])
        released = D(self.report["released_total"])
        settled = sum(D(p["amount"]) for p in c.payments.list() if p["status"] == "settled")
        self.assertEqual(settled, released)
        self.assertEqual(-c.ledger.balance("1000"), released)
        self.assertEqual(c.ledger.balance("5000"), released + c.ledger.balance("2050"))  # all stored material went to installed
        self.assertEqual(sorted(p["provider_ref"] for p in c.payments.list()), [f"sim_{n:06d}" for n in range(1, 20)])
        for b in c.bills.list(project_id=self.corpus.pid):
            self.assertIn(b["status"], ("paid", "corrected"), b["id"])
            if b["status"] == "paid":
                self.assertTrue(b["supplier_invoice_number"], b["id"])
        # the re-sent invoice was refused, never recorded: one invoice per number
        numbers = [i["invoice_number"] for i in self.corpus.intake.invoices(self.corpus.pid)]
        self.assertEqual(len(numbers), 19)
        self.assertEqual(numbers.count("EL-101"), 1)

    def test_every_approval_was_segregated_under_the_identity_policy(self):
        c = self.corpus.c
        consumed = c.approvals.list(status="consumed")
        policy_approval = [a for a in consumed if a["operation"] == "people.set_policy"][0]["id"]
        governed = [a for a in consumed if a["id"] > policy_approval]  # approval ids are time-ordered
        self.assertGreaterEqual(len(governed), 61)
        for a in governed:
            self.assertIn("people", a["manifest"]["governance"], a["operation"])
            self.assertNotEqual(a["requested_by"], a["approver"], a["operation"])
        owner_routed = [a for a in governed if a["approver"] == OWNER and a["operation"] in ("bill.approve", "payment.release")]
        self.assertEqual(len(owner_routed), self.report["approvals"]["routed_to_owner"])
        for a in owner_routed:
            self.assertTrue(a["operation"] == "payment.release" and a["manifest"]["governance"]["payment_policy"]["classification"] == "high_risk"
                            or D(a["manifest"]["amounts"].get("amount_due") or a["manifest"]["amounts"].get("amount")) >= D("25000.00"), a["id"])

    def test_business_grants_precede_independent_accountant_posting(self):
        c = self.corpus.c
        approvals = [a for a in c.approvals.list(status="consumed") if a["operation"] == "bill.approve"]
        self.assertEqual(len(approvals), 20)
        for approval in approvals:
            bill = c.bills.get(approval["subject_id"])
            journals = [j for j in c.ledger.journals() if j["source_type"] == "bill" and j["source_id"] == bill["id"] and not j["reversal_of"]]
            self.assertTrue(journals, bill["id"])
            self.assertTrue(all(j["posted_by"] == corpus_mod.ACCOUNTANT for j in journals))
            self.assertNotEqual(approval["approver"], corpus_mod.ACCOUNTANT)
            grant = c.audit.entries(entity_type="approval", entity_id=approval["id"])
            grant_sequence = next(e["seq"] for e in grant if e["action"] == "approval.granted")
            postings = c.audit.entries(entity_type="bill", entity_id=bill["id"])
            business = next(e for e in postings if e["action"] == "bill.business_approved")
            receipt = c.bills.posting_receipt(bill["id"])
            self.assertEqual(business["actor"], approval["approver"])
            self.assertEqual(receipt["approval_id"], approval["id"])
            self.assertEqual(receipt["posted_by"], corpus_mod.ACCOUNTANT)
            self.assertEqual(receipt["period_id"], corpus_mod.PERIOD[0])
            posted_sequence = next(e["seq"] for e in postings if e["action"] == "bill.posted")
            self.assertLess(grant_sequence, posted_sequence)
            self.assertLess(business["seq"], posted_sequence)

    def test_release_times_come_from_the_system_clock(self):
        """The release instant is the clearance the payment policy recorded with its injectable
        clock -- the corpus's simulated clock, not the wall clock."""
        k = self.corpus
        clock = k.clock
        self.assertIs(k.policy.now.__self__, clock)
        self.assertIs(k.people.now.__self__, clock)
        clearances = k.policy.clearances()
        self.assertEqual(len(clearances), 19)
        new_destination = k.bills[5]
        change = k.change
        self.assertEqual(clock.start, parse_iso(change["executed_at"]))
        # held by the cooling-off window, released one minute after it ended plus the step-up's five
        self.assertEqual(new_destination.released_at, clock.start + _dt.timedelta(days=COOLING_DAYS, minutes=6))
        high = sorted((c_ for c_ in clearances if c_["classification"] == "high_risk"), key=lambda c_: c_["cleared_at"])
        self.assertEqual(len(high), 2)
        for c_ in high:
            self.assertIsNotNone(c_["step_up_id"])
            self.assertEqual((c_["requested_by"], c_["approver"], c_["releaser"]), ("acct.ivy", OWNER, "tre.tom"))
        self.assertEqual([s["cosigner"] for s in k.policy.cosignatures()], ["ext.acct"])
        self.assertEqual(clock.minutes(), self.report["simulated_span_minutes"])

    def test_the_command_line_prints_the_same_report(self):
        """A second, independent run through ``main`` prints exactly the same JSON: the corpus
        is deterministic."""
        out = io.StringIO()
        target = os.path.join(tempfile.mkdtemp(prefix="cipher-corpus-"), "report.json")
        with contextlib.redirect_stdout(out):
            code = main(["--out", target])
        self.assertEqual(code, 0)
        printed = json.loads(out.getvalue())
        self.assertEqual(printed, json.loads(json.dumps(self.report)))
        with open(target, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), printed)

    def test_module_is_runnable(self):
        self.assertTrue(callable(corpus_mod.main))
        self.assertEqual(corpus_mod.REPORT_FORMAT, "cipher-corpus/1")


if __name__ == "__main__":
    unittest.main()
