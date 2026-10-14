"""Fixed accounting action reviews bind exact sources and make no effects."""
import unittest

from apps.cipher.ap_contract import APRefusal
from apps.cipher.ap_accounting_preflight import APAccountingPreflight
from apps.cipher.ap_practice_fixture import ACCOUNTANT_LOGIN, REVIEWER_LOGIN
from apps.cipher.tests.test_ap_accounting_contract import AccountingWorld


class APAccountingPreflightTests(AccountingWorld, unittest.TestCase):
    def test_four_human_reviews_are_pure_and_exact_original_obligation_is_displayed(self):
        self.assert_pure_review(self.person, "accounting.prepare", self.bill_id)
        self.assert_pure_review(self.person, "accounting.request", self.plan["id"])
        approval = self.request()
        self.assert_pure_review(self.reviewer, "accounting.approve", approval["id"])
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        self.assert_pure_review(self.person, "accounting.queue", approval["id"])
        before = self.snapshot()
        dto = self.contract.plan_review(self.person, self.plan["id"])
        self.assertEqual(dto["plan"]["original"]["originalCostCents"], 1234567)
        self.assertEqual(dto["plan"]["original"]["originalApCents"], 1111110)
        self.assertEqual(dto["plan"]["original"]["originalRetainageCents"], 123457)
        self.assertEqual(dto["plan"]["date"]["transactionDate"], "2026-11-30")
        self.assertEqual(dto["plan"]["preview"]["debitTotalCents"], dto["plan"]["preview"]["creditTotalCents"])
        self.assertEqual(before, self.snapshot())


    def test_fixed_bodies_refuse_actors_providers_mapping_dates_and_unknown_fields(self):
        for body in ({"actor": ACCOUNTANT_LOGIN}, {"provider": "quickbooks"}, {"mappingId": self.mapping["id"]},
                     {"transactionDate": "2026-11-30"}, {"realm": "synthetic"}, {"fingerprint": "pretend"}, []):
            before = self.snapshot()
            with self.subTest(body=body), self.assertRaises(APRefusal):
                self.preflight.review(self.person, "accounting.prepare", self.bill_id, body)
            self.assertEqual(before, self.snapshot())


    def test_fingerprint_binds_current_actor_and_resource(self):
        review = self.preflight.review(self.person, "accounting.prepare", self.bill_id, {})
        self.preflight.verify(self.person, "accounting.prepare", self.bill_id,
                              {"fingerprint": review["fingerprint"]}, review["resourceVersion"])
        before = self.snapshot()
        with self.assertRaises(APRefusal) as caught:
            self.preflight.verify(self.reviewer, "accounting.prepare", self.bill_id,
                                  {"fingerprint": review["fingerprint"]}, review["resourceVersion"])
        self.assertEqual(caught.exception.status, 412)
        self.assertEqual(before, self.snapshot())


    def test_requester_self_grant_and_duplicate_request_are_blocked_without_changes(self):
        approval = self.request()
        self.assert_pure_review(self.person, "accounting.approve", approval["id"], allowed=False)
        review = self.assert_pure_review(self.person, "accounting.request", self.plan["id"], allowed=False)
        self.assertEqual(review["checks"][-1]["code"], "duplicate_request")


    def test_delivery_and_lookup_are_state_derived_and_never_claim_in_preview(self):
        intent_id = self.queue()
        review = self.assert_pure_review(self.person, "accounting.deliver", intent_id)
        self.assertEqual(review["safeEffects"]["intendedWorkerPhase"], "submit")
        self.assertEqual(review["safeEffects"]["accountingSimulatorCallBound"], 1)
        self.assert_pure_review(self.person, "accounting.lookup", intent_id, allowed=False)
        self.assert_pure_review(self.person, "accounting.reconcile", intent_id, allowed=False)
        # An unfinished submission is represented by its actual committed local
        # attempt. No adapter is invoked to create the fail-closed disposition.
        claim = self.domain.claim_intent(intent_id, actor=ACCOUNTANT_LOGIN, worker_capability=self.worker._capability)
        self.domain.finish_attempt(intent_id, claim["lease_token"], outcome="outcome_unknown", actor=ACCOUNTANT_LOGIN,
                                   error_code="simulated_interrupted", worker_capability=self.worker._capability)
        review = self.assert_pure_review(self.person, "accounting.lookup", intent_id)
        self.assertEqual(review["safeEffects"]["intendedWorkerPhase"], "lookup")
        self.assertEqual(review["safeEffects"]["accountingSimulatorCallBound"], 3)
        self.assertEqual(self.adapter.calls, {"submit": 0, "lookup": 0, "read_record": 0})


    def test_absent_and_counterfeit_worker_are_unavailable_but_original_plan_remains_readable(self):
        intent_id = self.queue()
        class Counterfeit:
            pass
        counterfeit = Counterfeit()
        counterfeit._capability = self.worker._capability
        for worker in (None, counterfeit):
            preview = APAccountingPreflight(self.c, self.contract, secret=self.secret, worker=worker)
            before = self.snapshot()
            result = preview.review(self.person, "accounting.deliver", intent_id, {})
            self.assertFalse(result["allowed"])
            self.assertEqual(result["checks"][-1]["code"], "worker_unavailable")
            self.assertEqual(before, self.snapshot())
        self.assertEqual(self.contract.plan_review(self.person, self.plan["id"])["plan"]["billId"], self.bill_id)
