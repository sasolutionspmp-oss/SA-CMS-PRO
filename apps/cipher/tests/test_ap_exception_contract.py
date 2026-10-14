"""Scoped, truthful exception record reads and private version contracts."""
import unittest

from apps.cipher.ap_contract import APRefusal
from apps.cipher.tests import test_ap_exception_preflight as fixtures


class APExceptionContractTests(unittest.TestCase):
    def setUp(self):
        self.w = fixtures.ExceptionWorld()
        self.addCleanup(self.w.c.db.close)

    def test_invoice_read_is_pure_and_exposes_named_actions_without_private_source(self):
        w = self.w
        invoice = w.receive()
        before = w.snapshot()
        value = w.contract.invoice_review(w.accountant, invoice["id"])
        self.assertEqual(set(value["availableActions"]), {"invoice.revise", "invoice.reject"})
        self.assertEqual(value["invoice"]["invoiceNumber"], "SYN-EX-101")
        self.assertEqual(value["invoice"]["amountCents"], 1111110)
        for word in ("destination", "manifest", "source_facts", "content_hash"):
            self.assertNotIn(word, str(value))
        self.assertEqual(w.snapshot(), before)

    def test_bill_read_only_offers_current_actual_duty_and_ready_actions(self):
        w = self.w
        before = w.snapshot()
        accountant = w.contract.bill_review(w.accountant, w.records["approved_bill_id"])
        pm = w.contract.bill_review(w.pm, w.records["approved_bill_id"])
        self.assertEqual(accountant["availableActions"], [])
        self.assertEqual(pm["availableActions"], ["bill.cancel"])
        self.assertEqual(w.snapshot(), before)

    def test_posted_bill_correction_read_links_real_request_and_hides_duplicate_action(self):
        w = self.w
        bill, approval = w.request_correction()
        before = w.snapshot()
        value = w.contract.bill_review(w.accountant, bill)
        self.assertEqual(value["correction"]["reason"], "Synthetic quantity correction")
        self.assertNotIn("bill.requestCorrection", value["availableActions"])
        self.assertEqual(value["blockedReasons"][0]["code"], "duplicate_request")
        packet = w.contract.packet(w.reviewer, approval["id"])
        self.assertEqual(packet["availableActions"], ["bill.approveCorrection"])
        self.assertEqual(packet["changes"], [])
        self.assertEqual({period["id"] for period in packet["correctionPeriods"]}, {"2026-10", "2026-11"})
        self.assertEqual(w.contract.packet(w.accountant, approval["id"])["availableActions"], [])
        self.assertEqual(w.snapshot(), before)

    def test_correction_collection_scopes_before_count_facets_or_cursor(self):
        w = self.w
        _bill, approval = w.request_correction()
        before = w.snapshot()
        value = w.contract.read(w.accountant, "correction-approvals", top=1)
        self.assertEqual(value["count"], 1)
        self.assertEqual(value["value"][0]["approvalId"], approval["id"])
        self.assertEqual(value["facets"], {"statuses": [{"value": "pending", "count": 1}]})
        with self.assertRaises(APRefusal) as failure:
            w.contract.read(w.accountant, project_id=w.records["hidden_project_id"])
        self.assertEqual(failure.exception.status, 404)
        self.assertEqual(w.snapshot(), before)

    def test_hidden_bill_refuses_before_source_or_approval_disclosure(self):
        w = self.w
        before = w.snapshot()
        with self.assertRaises(APRefusal) as failure:
            w.contract.bill_review(w.accountant, w.records["hidden_bill_id"])
        self.assertEqual(failure.exception.status, 404)
        self.assertEqual(w.snapshot(), before)

    def test_invalid_query_shapes_are_typed_and_pure(self):
        w = self.w
        before = w.snapshot()
        for kwargs in ({"top": True}, {"project_id": []}, {"cursor": []}, {"search": 12}, {"status": "posted"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(APRefusal) as failure:
                w.contract.read(w.accountant, **kwargs)
            self.assertEqual(failure.exception.status, 422)
        self.assertEqual(w.snapshot(), before)
