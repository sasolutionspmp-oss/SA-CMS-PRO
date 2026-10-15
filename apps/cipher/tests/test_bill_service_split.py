"""Service acceptance for journal-free business grants and distinct posting."""
import json
import unittest
from unittest.mock import patch

from apps.cipher.service import Cipher, CipherError, RoleNotAuthorized
from apps.cipher.domain.bills import BillError


class BillServiceSplitTests(unittest.TestCase):
    def setUp(self):
        self.c = Cipher()
        self.c.open_period("P1", "January", "2026-01-01", "2026-01-31")
        self.c.open_period("P2", "February", "2026-02-01", "2026-02-28")
        supplier = self.c.add_party(kind="supplier", name="Synthetic supplier")
        project = self.c.create_project(name="Synthetic split project", entity="Synthetic entity", budget="2000")
        commitment = self.c.commitments.create(project_id=project["id"], supplier_id=supplier["id"], title="Subcontract",
                                                sov_lines=[{"description": "Work", "amount": "1000"}], actor="owner")
        self.c.approve_and_execute("commitment.execute", commitment["id"], actor="owner")
        line = self.c.commitments.get(commitment["id"])["sov"][0]["id"]
        self.bill = self.c.bills.certify(commitment_id=commitment["id"], period_id="P1",
                                       installed=[{"sov_line_id": line, "cumulative_installed": "100"}], actor="poster")

    def tearDown(self):
        self.c.db.close()

    def request(self):
        return self.c.request_approval("bill.approve", self.bill["id"], actor_role="accountant", requested_by="poster")

    def grant(self):
        approval = self.request()
        return self.c.approve(approval["id"], approver="reviewer", approver_role="pm")

    def test_bill_request_binds_fixed_business_duty(self):
        approval = self.request()
        self.assertEqual(approval["actor_role"], "pm")

    def test_grant_records_approved_state_without_journal(self):
        before = self.c.db.one("SELECT COUNT(*) AS n FROM journals")["n"]
        approval = self.grant()
        bill = self.c.bills.get(self.bill["id"])
        self.assertEqual(bill["status"], "approved")
        self.assertIsNone(bill["journal_id"])
        self.assertEqual(approval["status"], "granted")
        self.assertEqual(self.c.db.one("SELECT COUNT(*) AS n FROM journals")["n"], before)
        self.assertEqual(str(self.c.bills.open_payable(bill["id"])), "0.00")

    def test_bookkeeper_cannot_grant_business_approval(self):
        approval = self.request()
        with self.assertRaises((RoleNotAuthorized, PermissionError)):
            self.c.approve(approval["id"], approver="poster", approver_role="accountant")
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "pending")

    def test_old_execute_and_combined_helper_do_not_post(self):
        approval = self.grant()
        with self.assertRaises(CipherError):
            self.c.execute(approval["id"], actor="poster")
        with self.assertRaises(CipherError):
            self.c.approve_and_execute("bill.approve", self.bill["id"])
        self.assertEqual(self.c.bills.get(self.bill["id"])["status"], "approved")
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "granted")

    def test_post_uses_distinct_person_and_replays_exact_receipt(self):
        approval = self.grant()
        with self.assertRaisesRegex((BillError, PermissionError), "approver|same person"):
            self.c.post_bill(self.bill["id"], actor=" REVIEWER ")
        first = self.c.post_bill(self.bill["id"], actor="poster", period_id="P1")
        count = self.c.db.one("SELECT COUNT(*) AS n FROM journals")["n"]
        replay = self.c.post_bill(self.bill["id"], actor="poster", period_id="P1")
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(first.result, replay.result)
        self.assertEqual(self.c.db.one("SELECT COUNT(*) AS n FROM journals")["n"], count)
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "consumed")
        self.assertEqual(first.result["posting_period_id"], "P1")

    def test_cross_period_post_preserves_certification_and_records_reason(self):
        self.grant()
        with self.assertRaisesRegex(BillError, "requires a reason"):
            self.c.post_bill(self.bill["id"], actor="poster", period_id="P2")
        posted = self.c.post_bill(self.bill["id"], actor="poster", period_id="P2", reason="Late reviewed invoice")
        bill = self.c.bills.get(self.bill["id"])
        self.assertEqual(bill["period_id"], "P1")
        self.assertEqual(posted.result["posting_period_id"], "P2")
        receipt = self.c.bills.posting_receipt(bill["id"])
        self.assertEqual(receipt["reason"], "Late reviewed invoice")

    def test_caught_failure_in_outer_transaction_leaves_business_grant_unused(self):
        approval = self.grant()
        original = self.c.ledger.post

        def fail_after_journal(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("simulated late posting failure")

        with self.c.db.transaction():
            before = "\n".join(self.c.db.conn.iterdump())
            with patch.object(self.c.ledger, "post", side_effect=fail_after_journal):
                with self.assertRaisesRegex(RuntimeError, "simulated late posting failure"):
                    self.c.post_bill(self.bill["id"], actor="poster")
            self.assertEqual(before, "\n".join(self.c.db.conn.iterdump()))
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "granted")
        self.assertIsNone(self.c.bills.get(self.bill["id"])["journal_id"])

    def test_rewritten_cached_result_cannot_replace_the_audited_posting_receipt(self):
        self.grant()
        posted = self.c.post_bill(self.bill["id"], actor="poster")
        forged = dict(posted.result, amount_due="9999.00")
        self.c.db.execute("UPDATE idempotency SET result_json=? WHERE op_id=?", (json.dumps(forged), posted.op_id))
        before = "\n".join(self.c.db.conn.iterdump())
        with self.assertRaisesRegex(CipherError, "cached posting result"):
            self.c.post_bill(self.bill["id"], actor="poster")
        self.assertEqual(before, "\n".join(self.c.db.conn.iterdump()))

    def test_receipt_replay_never_adopts_an_owner_posting_wildcard(self):
        self.grant()
        self.c.post_bill(self.bill["id"], actor="poster")
        before = "\n".join(self.c.db.conn.iterdump())
        with self.assertRaises(PermissionError):
            self.c.post_bill(self.bill["id"], actor="poster", actor_role="owner")
        self.assertEqual(before, "\n".join(self.c.db.conn.iterdump()))


if __name__ == "__main__":
    unittest.main()
