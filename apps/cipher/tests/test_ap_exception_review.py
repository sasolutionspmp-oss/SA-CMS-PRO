"""Independent regressions for audit-backed correction sources and reads."""
import unittest

import apps.cipher.tests.test_ap_exception_actions as fixtures
from apps.cipher.ap_contract import APRefusal


class APExceptionReviewTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.APExceptionActionsTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)

    def test_bill_review_refuses_deleted_correction_request_with_intact_audit_birth(self):
        x = self.fx
        bill_id = x.posted_bill()
        request = x.c.bills.prepare_correction(bill_id, "Synthetic independent correction inventory check", x.login)
        for trigger in x.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='bill_corrections'"):
            x.c.db.conn.execute('DROP TRIGGER "' + trigger["name"].replace('"', '""') + '"')
        x.c.db.conn.execute("DELETE FROM bill_corrections WHERE id=?", (request["id"],))
        before = x.snapshot()
        with self.assertRaises(APRefusal) as refused:
            x.contract.bill_review(x.accountant, bill_id)
        self.assertEqual(refused.exception.status, 423)
        self.assertEqual(x.snapshot(), before)

    def test_original_correction_receipt_refuses_deleted_later_audited_request(self):
        x = self.fx
        args = x.prepare_args()
        first = x.runner.run(**args)
        x.c.bills.cancel_correction(first["result"]["correctionId"], "Synthetic replacement of correction request", x.login)
        later = x.c.bills.prepare_correction(args["resource_id"], "Synthetic later correction request", x.login)
        for trigger in x.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='bill_corrections'"):
            x.c.db.conn.execute('DROP TRIGGER "' + trigger["name"].replace('"', '""') + '"')
        x.c.db.conn.execute("DELETE FROM bill_corrections WHERE id=?", (later["id"],))
        before = x.snapshot()
        with self.assertRaises(APRefusal):
            x.runner.run(**args)
        self.assertEqual(x.snapshot(), before)
        self.assertFalse(all(check["ok"] for check in x.runner.integrity_checks()))


if __name__ == "__main__":
    unittest.main()
