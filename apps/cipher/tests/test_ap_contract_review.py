"""Independent AP presenter source and lifecycle reproductions."""
import datetime
import unittest

from apps.cipher.ap_contract import APContract, APRefusal
from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
from apps.cipher.core.approvals import ApprovalExpired
from apps.cipher.core.ids import utcnow


class APContractReviewTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.accountant = self.c.ap_practice_persona_people["accountant"]["person_id"]
        self.pm = self.c.ap_practice_persona_people["pm"]["person_id"]
        self.bill_id = self.c.ap_practice_records["draft_bill_id"]
        self.contract = APContract(self.c, secret=b"independent-contract-review-private-key")

    def request(self):
        return self.c.request_approval("bill.approve", self.bill_id, actor_role="accountant", requested_by="practice.accountant")

    def remove_approval_guards(self):
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='approvals'"):
            self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')

    def test_invalidated_authorization_cannot_be_resurrected_as_pending(self):
        approval = self.request()
        self.c.approvals.invalidate(approval["id"], reason="Synthetic rejected business request", actor="practice.pm")
        self.remove_approval_guards()
        self.c.db.execute("UPDATE approvals SET status='pending',invalidated_reason=NULL WHERE id=?", (approval["id"],))
        with self.assertRaises(APRefusal) as failure:
            self.contract.require_resource(self.pm, "bill.approve", approval["id"])
        self.assertEqual(failure.exception.code, "invalid_record")

    def test_expired_authorization_cannot_be_resurrected_with_original_deadline(self):
        approval = self.request()
        self.c.db.execute("UPDATE approvals SET expires_at=? WHERE id=?",
                          ((utcnow() - datetime.timedelta(minutes=1)).isoformat(), approval["id"]))
        with self.assertRaises(ApprovalExpired):
            self.c.approve(approval["id"], approver="practice.pm", approver_role="pm")
        self.remove_approval_guards()
        self.c.db.execute("UPDATE approvals SET status='pending',expires_at=? WHERE id=?", (approval["expires_at"], approval["id"]))
        with self.assertRaises(APRefusal) as failure:
            self.contract.packet(self.pm, approval["id"])
        self.assertEqual(failure.exception.code, "invalid_record")

    def remove_commitment_guards(self):
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='commitments'"):
            self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')

    def test_executed_retainage_terms_must_match_original_business_authorization(self):
        self.remove_commitment_guards()
        commitment_id = self.c.ap_practice_records["visible_commitment_ids"][0]
        self.c.db.execute("UPDATE commitments SET retainage_rate='0.90' WHERE id=?", (commitment_id,))
        with self.assertRaises(APRefusal) as failure:
            self.contract.read(self.accountant, "commitments")
        self.assertEqual(failure.exception.code, "invalid_record")


if __name__ == "__main__":
    unittest.main()
