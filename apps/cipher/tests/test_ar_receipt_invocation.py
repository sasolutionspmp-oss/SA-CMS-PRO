"""A receipt callback cannot rewrite the actual reviewed AR invocation."""
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.tests import test_ar_actions as harness


class ARReceiptInvocationTests(unittest.TestCase):
    def setUp(self):
        self.h = harness.ARActionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def request_input(self):
        h = self.h
        bill, _ = h.act(h.person, "ownerBill.prepare", h.r["basis_id"], h.input())
        return h.prepared(h.person, "ownerBill.requestApproval", bill["result"]["billId"])

    def assert_callback_rollback(self, request, callback):
        h = self.h
        with h.c.db.transaction():
            before = h.state()
            with patch.object(h.runner.receipts, "record", side_effect=callback), self.assertRaises(APRefusal):
                h.runner.run(*request[0], **request[1])
            self.assertEqual(before, h.state())

    def test_request_receipt_preserves_original_canonical_person(self):
        request = self.request_input()
        record = self.h.runner.receipts.record
        def changed(**kwargs):
            return record(**{**kwargs, "person_id": self.h.reviewer})
        self.assert_callback_rollback(request, changed)

    def test_request_receipt_preserves_original_if_match(self):
        request = self.request_input()
        record = self.h.runner.receipts.record
        def changed(**kwargs):
            binding = {**kwargs["binding"], "originalIfMatch": "owner-v1:" + "0"*64}
            return record(**{**kwargs, "binding": binding})
        self.assert_callback_rollback(request, changed)

    def test_request_receipt_preserves_original_review_fingerprint(self):
        request = self.request_input()
        record = self.h.runner.receipts.record
        def changed(**kwargs):
            binding = {**kwargs["binding"], "preflightFingerprint": "DifferentRecordedFingerprint",
                "canonicalTypedBody": {**kwargs["binding"]["canonicalTypedBody"], "fingerprint": "DifferentRecordedFingerprint"}}
            return record(**{**kwargs, "binding": binding})
        self.assert_callback_rollback(request, changed)

    def test_returned_metadata_must_equal_actual_recorded_row(self):
        request = self.request_input()
        record = self.h.runner.receipts.record
        def changed(**kwargs):
            row = record(**kwargs)
            return {**row, "receipt_hash": "0"*64}
        self.assert_callback_rollback(request, changed)

    def test_in_place_source_mutation_cannot_redefine_expected_receipt_arguments(self):
        request = self.request_input()
        record = self.h.runner.receipts.record
        def changed(**kwargs):
            kwargs["source"]["reviewedPlanHash"] = "0"*64
            return record(**kwargs)
        self.assert_callback_rollback(request, changed)

    def test_post_receipt_identity_change_restores_same_grant_journal_and_command(self):
        h = self.h
        bill, approval, _ = h.granted()
        request = h.prepared(h.poster, "ownerBill.post", bill)
        record = h.runner.receipts.record
        def changed(**kwargs):
            return record(**{**kwargs, "person_id": h.reviewer})
        self.assert_callback_rollback(request, changed)
        self.assertEqual(h.c.approvals.get(approval)["status"], "granted")
        self.assertEqual(h.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        completed = h.runner.run(*request[0], **request[1])
        h.replay(completed, request)

    def test_metadata_is_reproved_after_callback_even_when_it_returns_original_row(self):
        request = self.request_input()
        h, record = self.h, self.h.runner.receipts.record
        def changed(**kwargs):
            row = record(**kwargs)
            guard = h.c.db.one("SELECT sql FROM sqlite_master WHERE name='ar_action_receipts_no_update'")["sql"]
            with h.c.db.transaction() as conn:
                conn.execute("DROP TRIGGER ar_action_receipts_no_update")
                conn.execute("UPDATE ar_action_receipts SET canonical_person_id=? WHERE id=?", (h.reviewer, row["id"]))
                conn.execute(guard)
            return row
        self.assert_callback_rollback(request, changed)
