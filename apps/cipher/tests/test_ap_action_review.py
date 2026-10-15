"""Independent reproductions of unexpected effects in typed AP refusals."""
import unittest
from unittest.mock import patch

from apps.cipher.ap_actions import APActionRunner
from apps.cipher.ap_contract import APContract, APRefusal
from apps.cipher.ap_preflight import APPreflight
from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
from apps.cipher.core.approvals import StaleApprovalError
from uuid import uuid4


class APActionReviewTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        secret = b"independent-action-review-key-with-32-bytes"
        self.contract = APContract(self.c, secret=secret)
        self.preflight = APPreflight(self.c, self.contract, secret=secret)
        self.runner = APActionRunner(self.c, self.contract, self.preflight)
        self.accountant = self.c.ap_practice_persona_people["accountant"]["person_id"]
        self.pm = self.c.ap_practice_persona_people["pm"]["person_id"]
        self.bill_id = self.c.ap_practice_records["draft_bill_id"]

    def grant_args(self):
        review = self.preflight.review(self.accountant, "bill.requestApproval", self.bill_id, {})
        self.assertTrue(review["allowed"], review)
        requested = self.runner.run(self.accountant, "bill.requestApproval", self.bill_id,
                                    {"fingerprint": review["fingerprint"]},
                                    repeatability_key=str(uuid4()), if_match=review["resourceVersion"])
        approval_id = requested["result"]["approvalId"]
        review = self.preflight.review(self.pm, "bill.approve", approval_id, {})
        self.assertTrue(review["allowed"], review)
        return {"person_id": self.pm, "action": "bill.approve", "resource_id": approval_id,
                "body": {"fingerprint": review["fingerprint"]}, "repeatability_key": str(uuid4()),
                "if_match": review["resourceVersion"]}

    def test_typed_stale_refusal_cannot_commit_a_dropped_financial_guard(self):
        args = self.grant_args()
        trigger = "approvals_credited_bill_release_open_payable"
        self.assertIsNotNone(self.c.db.one("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (trigger,)))
        before = tuple(self.c.db.conn.iterdump())

        def failure(*values, **kwargs):
            self.c.db.execute("DROP TRIGGER " + trigger)
            self.c.approvals.invalidate(args["resource_id"], reason="Unexpected schema write", actor="practice.pm")
            raise StaleApprovalError("Unexpected partial schema mutation")

        with patch.object(self.c, "approve", side_effect=failure):
            with self.assertRaises(APRefusal) as caught:
                self.runner.run(**args)
        self.assertEqual(caught.exception.status, 500)
        self.assertFalse(hasattr(caught.exception, "receipt_id"))
        self.assertEqual(tuple(self.c.db.conn.iterdump()), before)
        self.assertFalse(self.c.db.conn.in_transaction)


if __name__ == "__main__":
    unittest.main()
