"""An audited terminal bill authorization never becomes active again."""
import datetime
import unittest

from apps.cipher.core.approvals import ApprovalExpired
from apps.cipher.core.ids import utcnow
from apps.cipher.domain.bills import BillError
from apps.cipher.tests import test_bill_service_split as fixtures


class BillAuthorizationHistoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BillServiceSplitTests("test_grant_records_approved_state_without_journal")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.c, self.bill = self.fixture.c, self.fixture.bill

    def remove_guards(self):
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='approvals'"):
            self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')

    def snapshot(self):
        return tuple(self.c.db.conn.iterdump())

    def test_invalidated_request_cannot_be_reactivated_and_granted(self):
        approval = self.fixture.request()
        self.c.approvals.invalidate(approval["id"], reason="Synthetic business decision rejected", actor="reviewer")
        self.remove_guards()
        self.c.db.execute("UPDATE approvals SET status='pending',invalidated_reason=NULL WHERE id=?", (approval["id"],))
        before = self.snapshot()
        with self.assertRaises(BillError):
            self.c.approve(approval["id"], approver="reviewer", approver_role="pm")
        self.assertEqual(self.snapshot(), before)

    def test_expired_request_cannot_restore_original_window_and_be_granted(self):
        approval = self.fixture.request()
        self.c.db.execute("UPDATE approvals SET expires_at=? WHERE id=?",
                          ((utcnow() - datetime.timedelta(minutes=1)).isoformat(), approval["id"]))
        with self.assertRaises(ApprovalExpired):
            self.c.approve(approval["id"], approver="reviewer", approver_role="pm")
        self.remove_guards()
        self.c.db.execute("UPDATE approvals SET status='pending',expires_at=? WHERE id=?", (approval["expires_at"], approval["id"]))
        before = self.snapshot()
        with self.assertRaises(BillError):
            self.c.approve(approval["id"], approver="reviewer", approver_role="pm")
        self.assertEqual(self.snapshot(), before)

    def test_expired_recorded_grant_cannot_be_reactivated_and_posted(self):
        approval = self.fixture.grant()
        self.c.db.execute("UPDATE approvals SET expires_at=? WHERE id=?",
                          ((utcnow() - datetime.timedelta(minutes=1)).isoformat(), approval["id"]))
        with self.assertRaises(ApprovalExpired):
            self.c.post_bill(self.bill["id"], actor="poster")
        self.remove_guards()
        self.c.db.execute("UPDATE approvals SET status='granted',expires_at=? WHERE id=?", (approval["expires_at"], approval["id"]))
        before = self.snapshot()
        with self.assertRaises(BillError):
            self.c.post_bill(self.bill["id"], actor="poster")
        self.assertEqual(self.snapshot(), before)

    def test_expired_grant_can_be_withdrawn_without_reactivation(self):
        approval = self.fixture.grant()
        self.c.db.execute("UPDATE approvals SET expires_at=? WHERE id=?",
                          ((utcnow() - datetime.timedelta(minutes=1)).isoformat(), approval["id"]))
        with self.assertRaises(ApprovalExpired):
            self.c.post_bill(self.bill["id"], actor="poster")
        self.c.bills.void(self.bill["id"], actor="reviewer", reason="Synthetic expired approval withdrawn")
        self.assertEqual(self.c.bills.get(self.bill["id"])["status"], "void")
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "expired")


if __name__ == "__main__":
    unittest.main()
