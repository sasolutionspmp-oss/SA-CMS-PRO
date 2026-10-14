"""Separate bill business approval from an independent accounting posting duty."""
import unittest
from unittest.mock import patch

from apps.cipher.core.approvals import StaleApprovalError, build_manifest
from apps.cipher.domain.people import IdentityIntegrityError, IdentityRefused
from apps.cipher.domain.ricky import Ricky
from apps.cipher.tests.test_people import World


class BillDutyTests(unittest.TestCase):
    def test_accountant_can_post_but_cannot_approve_a_bill(self):
        self.assertFalse(Ricky.can("accountant", "bill.approve"))
        self.assertTrue(Ricky.can("accountant", "bill.post"))

    def test_bill_duties_have_no_owner_posting_wildcard(self):
        for role in ("pm", "controller", "owner"):
            with self.subTest(approver=role):
                self.assertTrue(Ricky.can(role, "bill.approve"))
        for role in ("pm", "owner", "viewer", "treasury"):
            with self.subTest(poster=role):
                self.assertFalse(Ricky.can(role, "bill.post"))
        self.assertTrue(Ricky.can("controller", "bill.post"))


class BillPostingAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.w = World().team(segregate=False)
        self.c, self.p = self.w.c, self.w.p
        self.addCleanup(self.c.db.close)

    def approval(self, *, approver="pm.lee", project=None, granted=True):
        manifest = build_manifest(operation="bill.approve", subject_type="bill", subject_id="bill_synthetic_authority",
                                  actor_role="pm", bindings={"project_id": project or self.w.a})
        bound = self.p.approval_policy("bill.approve", manifest)
        if bound:
            manifest["governance"] = {"people": bound}
        ap = self.c.approvals.request(manifest, requested_by="ext.acct")
        return self.c.approvals.grant(ap["id"], approver=approver) if granted else ap

    def snapshot(self):
        return (self.c.approvals.list(), self.c.db.query("SELECT * FROM audit_log ORDER BY seq"),
                self.c.db.query("SELECT * FROM people_self_approvals ORDER BY id"))

    def test_bill_grant_rejects_accountant_even_when_registry_is_not_enforcing(self):
        ap = self.approval(granted=False)
        with patch.object(self.p, "enforcing", return_value=False):
            with self.assertRaises(IdentityRefused):
                self.p.check_bill_grant(ap, approver="ext.acct", approver_role="accountant")

    def test_accountant_can_prepare_a_fixed_pm_business_manifest(self):
        ap = self.approval(granted=False)
        before = self.snapshot()
        self.p.check_bill_request(ap["manifest"], actor_role="accountant", requested_by="ext.acct")
        self.assertEqual(ap["manifest"]["actor_role"], "pm")
        self.assertEqual(self.snapshot(), before)

    def test_bill_request_role_does_not_elevate_the_registered_preparer(self):
        ap = self.approval(granted=False)
        for login, role in (("pm.lee", "accountant"), ("pay-worker", "accountant"), ("ext.acct", "treasury")):
            with self.subTest(login=login, role=role), self.assertRaises(IdentityRefused):
                self.p.check_bill_request(ap["manifest"], actor_role=role, requested_by=login)

    def test_approved_bill_attention_is_posting_work_for_accounting_duties(self):
        ap = self.approval()
        bill = {"id": "bill_synthetic_authority", "status": "approved", "stale": False, "sequence": 1,
                "amount_due": "100.00", "business_approval_id": ap["id"]}
        with patch.object(self.c.bills, "list", return_value=[bill]):
            for role in ("pm", "owner", "accountant", "controller"):
                with self.subTest(role=role):
                    items = self.c.ricky.brief(self.w.a, actor_role=role)["items"]
                    self.assertFalse(any(item["level"] == "execute" and item["operation"] == "bill.approve" for item in items))
                    self.assertEqual(any(item["level"] == "execute" and item["operation"] == "bill.post" for item in items), role in ("accountant", "controller"))

    def test_expired_business_approval_never_offers_a_bill_posting_action(self):
        ap = self.approval()
        self.c.db.execute("UPDATE approvals SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (ap["id"],))
        bill = {"id": "bill_synthetic_authority", "status": "approved", "stale": False, "sequence": 1,
                "amount_due": "100.00", "business_approval_id": ap["id"]}
        with patch.object(self.c.bills, "list", return_value=[bill]):
            items = self.c.ricky.brief(self.w.a, actor_role="accountant")["items"]
        self.assertFalse(any(item["level"] == "execute" and item["operation"] == "bill.post" for item in items))
        self.assertTrue(any(item["level"] == "review" and item["operation"] == "bill.approve" for item in items))

    def test_pm_controller_and_owner_can_business_approve_under_current_authority(self):
        ap = self.approval(granted=False)
        before = self.snapshot()
        for login, role in (("pm.lee", "pm"), ("ctrl.kim", "controller"), ("travis", "owner")):
            with self.subTest(login=login):
                self.p.check_bill_grant(ap, approver=login, approver_role=role)
        self.assertEqual(self.snapshot(), before)

    def test_explicit_accountant_and_controller_can_post_another_persons_approval(self):
        ap = self.approval()
        before = self.snapshot()
        for login, role in (("ext.acct", "accountant"), ("ctrl.kim", "controller")):
            with self.subTest(login=login):
                self.p.check_bill_post(ap, actor=login, actor_role=role)
        self.assertEqual(self.snapshot(), before)

    def test_owner_claimed_accounting_role_and_wildcard_do_not_authorize_posting(self):
        ap = self.approval()
        for role in ("owner", "accountant", "controller"):
            with self.subTest(role=role), self.assertRaises(IdentityRefused):
                self.p.check_bill_post(ap, actor="travis", actor_role=role)

    def test_owner_with_explicit_accountant_grant_can_post_another_persons_approval(self):
        self.w.grant("ctrl.kim", "owner")
        self.w.grant("travis", "accountant", by="ctrl.kim", approver="ctrl.kim", executor="ctrl.kim")
        self.p.check_bill_post(self.approval(), actor="travis", actor_role="accountant")

    def test_accountant_can_preview_a_fixed_pm_manifest_without_approving(self):
        bill = {"id": "bill_synthetic_authority", "status": "draft", "stale": False, "period_id": "P1",
                "sequence": 1, "amount_due": "100.00", "retainage_this_period": "5.00"}
        with patch.object(self.c.bills, "get", return_value=bill), patch.object(self.c.bills, "manifest", return_value={"actor_role": "pm"}) as manifest:
            proposal = self.c.ricky.propose("bill.approve", actor_role="accountant", context={"bill_id": bill["id"]})
        self.assertEqual(proposal["decision"], "proposed")
        manifest.assert_called_once_with(bill["id"], actor_role="pm")
        self.assertFalse(Ricky.can("accountant", "bill.approve"))

    def test_controller_never_posts_its_own_approval_after_login_normalization(self):
        ap = self.approval(approver="ctrl.kim")
        before = self.snapshot()
        for login in ("ctrl.kim", " CTRL.KIM ", "\tＣＴＲＬ.ＫＩＭ\n"):
            with self.subTest(login=login), self.assertRaisesRegex(IdentityRefused, "same person"):
                self.p.check_bill_post(ap, actor=login, actor_role="controller")
        self.assertEqual(self.snapshot(), before)

    def test_even_non_enforcing_registry_refuses_normalized_self_posting(self):
        ap = self.approval(approver="ctrl.kim")
        with patch.object(self.p, "enforcing", return_value=False):
            with self.assertRaisesRegex(IdentityRefused, "same person"):
                self.p.check_bill_post(ap, actor=" ＣＴＲＬ.ＫＩＭ ", actor_role="accountant")

    def test_shared_person_ids_cannot_supply_a_second_poster_login(self):
        ap = self.approval()
        with patch.object(self.p, "person_for", side_effect=lambda login: {"id": "one_person"}):
            with self.assertRaisesRegex(IdentityRefused, "same person"):
                self.p.check_bill_post(ap, actor="ext.acct", actor_role="accountant")

    def test_project_posting_grant_requires_the_same_project_and_current_membership(self):
        self.p.register_person("acct.job", "Synthetic job accountant", actor="travis")
        self.p.add_membership("acct.job", self.w.a, actor="travis")
        self.w.grant("acct.job", "accountant", project_id=self.w.a)
        self.p.check_bill_post(self.approval(), actor="acct.job", actor_role="accountant")
        with self.assertRaises(IdentityRefused):
            self.p.check_bill_post(self.approval(approver="pm.ana", project=self.w.b), actor="acct.job", actor_role="accountant")
        self.p.end_membership("acct.job", self.w.a, reason="job assignment ended", actor="travis")
        with self.assertRaises(IdentityRefused):
            self.p.check_bill_post(self.approval(), actor="acct.job", actor_role="accountant")

    def test_service_identity_with_accounting_grant_never_posts(self):
        self.w.grant("pay-worker", "accountant")
        with self.assertRaises(IdentityRefused):
            self.p.check_bill_post(self.approval(), actor="pay-worker", actor_role="accountant")

    def test_lost_approver_authority_is_stale_before_posting(self):
        ap = self.approval()
        self.p.deactivate_person("pm.lee", reason="left the job", actor="travis")
        before = self.snapshot()
        with self.assertRaises(StaleApprovalError):
            self.p.check_bill_post(ap, actor="ext.acct", actor_role="accountant")
        self.assertEqual(self.snapshot(), before)

    def test_changed_policy_and_broken_authority_fail_closed_without_effects(self):
        ap = self.approval()
        before = self.snapshot()
        with patch.object(self.p, "_binding", return_value={"policy_version": 99, "policy_hash": "moved"}):
            with self.assertRaises(StaleApprovalError):
                self.p.check_bill_post(ap, actor="ext.acct", actor_role="accountant")
        with patch.object(self.p, "_authority_problems", return_value=["synthetic broken authority"]):
            with self.assertRaises(IdentityIntegrityError):
                self.p.check_bill_post(ap, actor="ext.acct", actor_role="accountant")
        self.assertEqual(self.snapshot(), before)

    def test_helpers_read_the_stored_approval_not_a_forged_approver_or_scope(self):
        ap = self.approval(approver="ctrl.kim")
        forged = dict(ap, approver="pm.lee")
        with self.assertRaisesRegex(IdentityRefused, "same person"):
            self.p.check_bill_post(forged, actor="ctrl.kim", actor_role="controller")

    def test_consumed_receipt_replay_checks_current_poster_without_reapproving_history(self):
        ap = self.approval()
        self.c.approvals.consume(ap["id"], current_manifest=ap["manifest"], consumer="ext.acct")
        self.p.deactivate_person("pm.lee", reason="left after posting", actor="travis")
        before = self.snapshot()
        with patch.object(self.p, "_binding", return_value={"policy_version": 99, "policy_hash": "moved"}):
            self.p.check_bill_post(ap, actor="ext.acct", actor_role="accountant", replay=True)
        with self.assertRaises(IdentityRefused):
            self.p.check_bill_post(ap, actor="travis", actor_role="accountant", replay=True)
        self.assertEqual(self.snapshot(), before)

    def test_receipt_replay_requires_consumed_proof_and_keeps_person_separation(self):
        ap = self.approval(approver="ctrl.kim")
        with self.assertRaises(IdentityRefused):
            self.p.check_bill_post(ap, actor="ext.acct", replay=True)
        self.c.approvals.consume(ap["id"], current_manifest=ap["manifest"], consumer="ext.acct")
        before = self.snapshot()
        with self.assertRaisesRegex(IdentityRefused, "same person"):
            self.p.check_bill_post(ap, actor="ＣＴＲＬ.ＫＩＭ", actor_role="controller", replay=True)
        self.p.check_bill_post(ap, actor="ext.acct", replay=True)
        self.assertEqual(self.snapshot(), before)

    def test_only_the_original_business_approver_can_withdraw_an_approved_bill(self):
        ap = self.approval()
        before = self.snapshot()
        self.p.check_bill_cancellation(ap, actor=" ＰＭ.ＬＥＥ ")
        for actor in ("travis", "ctrl.kim", "ext.acct", "new-actor"):
            with self.subTest(actor=actor), self.assertRaises(IdentityRefused):
                self.p.check_bill_cancellation(ap, actor=actor)
        self.assertEqual(self.snapshot(), before)

    def test_withdrawal_rechecks_original_approvers_current_business_authority(self):
        ap = self.approval()
        self.p.deactivate_person("pm.lee", reason="left the company", actor="travis")
        before = self.snapshot()
        with self.assertRaises(IdentityRefused):
            self.p.check_bill_cancellation(ap, actor="pm.lee")
        self.assertEqual(self.snapshot(), before)

    def test_withdrawal_matches_shared_canonical_person_without_an_owner_exception(self):
        ap = self.approval()
        with patch.object(self.p, "person_for", return_value={"id": "same_person"}):
            self.p.check_bill_cancellation(ap, actor="pm.ana")
        with patch.object(self.p, "_authority_problems", return_value=["broken authority"]):
            with self.assertRaises(IdentityIntegrityError):
                self.p.check_bill_cancellation(ap, actor="pm.lee")


if __name__ == "__main__":
    unittest.main()
