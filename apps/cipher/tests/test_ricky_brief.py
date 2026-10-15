"""Ricky brief: a read-only, role-filtered attention list."""
import os
import tempfile
import unittest

from apps.cipher.tests.bill_helpers import approve_and_post_bill
from apps.cipher.service import Cipher, run_golden_fixture


def kinds(brief):
    return [it["kind"] for it in brief["items"]]


class RickyBriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Cipher()
        cls.r = run_golden_fixture(cls.c)

    def test_is_read_only(self):
        before_audit = self.c.audit.verify_chain()["entries"]
        before_proposals = self.c.db.scalar("SELECT COUNT(*) FROM ricky_proposals")
        b = self.c.ricky.brief(self.r["project_id"], actor_role="owner")
        self.assertTrue(b["read_only"])
        self.assertEqual(self.c.audit.verify_chain()["entries"], before_audit)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM ricky_proposals"), before_proposals)

    def test_golden_fixture_findings(self):
        b = self.c.ricky.brief(self.r["project_id"], actor_role="owner")
        k = kinds(b)
        # the fixture leaves bill 3 certified before the commitment changed, and executes the 12,000 alternative (over budget)
        self.assertIn("bill_stale", k)
        self.assertIn("over_budget", k)
        # the follow-on commitment drafted from the stale estimate is flagged, not proposed for execution
        drafts = [it for it in b["items"] if it["kind"] == "commitment_draft"]
        self.assertTrue(drafts and all(it["level"] == "review" for it in drafts))
        self.assertNotIn("ap_unreconciled", k)
        self.assertNotIn("trial_balance", k)
        levels = [it["level"] for it in b["items"]]
        order = ["blocker", "decide", "execute", "reconcile", "review", "info"]
        self.assertEqual(levels, sorted(levels, key=order.index))

    def test_role_filtering(self):
        c = Cipher()
        sup = c.add_party(kind="supplier", name="S", destination="ACH-1")
        c.verify_destination(sup["id"], destination="ACH-1", verified_by="owner")
        prj = c.create_project(name="P", entity="E", budget="1000")
        c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        cmt = c.commitments.create(project_id=prj["id"], supplier_id=sup["id"], title="S", sov_lines=[{"description": "a", "amount": "1000"}], actor="o")
        c.approve_and_execute("commitment.execute", cmt["id"])
        line = c.commitments.get(cmt["id"])["sov"][0]["id"]
        b = c.bills.certify(commitment_id=cmt["id"], period_id="P1", installed=[{"sov_line_id": line, "cumulative_installed": "1000"}], actor="o")
        approve_and_post_bill(c, b["id"], approver="owner", approver_role="owner", poster="accountant")
        ap = c.request_approval("payment.release", b["id"], actor_role="treasury")
        treasury = c.ricky.brief(prj["id"], actor_role="treasury")
        estimator = c.ricky.brief(prj["id"], actor_role="estimator")
        self.assertIn(ap["id"], [it["ref"] for it in treasury["items"] if it["kind"] == "approval_pending"])
        self.assertNotIn("approval_pending", kinds(estimator))
        c.approve(ap["id"])
        self.assertIn("approval_granted", kinds(c.ricky.brief(prj["id"], actor_role="treasury")))
        c.execute(ap["id"], actor="treasury")
        self.assertIn("outbox", kinds(c.ricky.brief(prj["id"], actor_role="treasury")))
        c.provider.mode = "timeout_after_accept"
        c.dispatch_payments()
        t = c.ricky.brief(prj["id"], actor_role="treasury")
        self.assertIn("payment_unknown", kinds(t))
        self.assertNotIn("payment_unknown", kinds(c.ricky.brief(prj["id"], actor_role="viewer")))
        c.provider.mode = "accept"
        c.reconcile_payments()
        self.assertNotIn("payment_unknown", kinds(c.ricky.brief(prj["id"], actor_role="treasury")))
        with self.assertRaises(ValueError):
            c.ricky.brief(prj["id"], actor_role="intern")

    def test_restore_quarantine_is_a_blocker(self):
        d = tempfile.mkdtemp()
        c = Cipher(os.path.join(d, "live.sqlite"))
        prj = c.create_project(name="P", entity="E", budget="0")
        restored = Cipher.open_restored(c.snapshot(os.path.join(d, "copy.sqlite")))
        b = restored.ricky.brief(prj["id"], actor_role="owner")
        self.assertIn("authority", kinds(b))
        restored.claim_write_authority(approval_ref="apr_controller")
        b = restored.ricky.brief(prj["id"], actor_role="owner")
        self.assertIn("quarantine", kinds(b))
        self.assertEqual(b["items"][0]["level"], "blocker")

    def test_failing_plugin_close_check_surfaces(self):
        c = Cipher()
        prj = c.create_project(name="P", entity="E", budget="0")
        c.open_period("P1", "P1", "2026-10-01", "2026-10-31")

        class Broken:
            def close_checks(self, period_id):
                return [{"check": "synthetic check", "ok": False, "detail": "intentionally failing"}]

        class Raising:
            def close_checks(self, period_id):
                raise RuntimeError("boom")

        c.register_plugin("zz_broken", Broken())
        c.register_plugin("zz_raising", Raising())
        k = kinds(c.ricky.brief(prj["id"]))
        self.assertIn("close_check", k)
        self.assertIn("close_check_error", k)

    def test_state_includes_brief(self):
        state = self.c.project_state(self.r["project_id"])
        self.assertIn("ricky_brief", state)
        self.assertEqual(state["ricky_brief"]["role"], "owner")


if __name__ == "__main__":
    unittest.main()
