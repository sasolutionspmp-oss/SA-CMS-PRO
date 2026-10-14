"""Grant previews are read-only; grant effects commit only with the approval."""
import unittest
from unittest.mock import patch

from apps.cipher.core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError
from apps.cipher.domain.people import IdentityRefused, PeopleError
from apps.cipher.tests.test_people import World
from apps.cipher.tests.test_payment_policy import World as PaymentWorld


class GrantPreflightTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.c, self.p = self.w.c, self.w.p
        self.p.bootstrap_owner("travis", "Synthetic sole owner")
        self.p.register_person("ext.acct", "Synthetic outside accountant", actor="travis", external=True)
        self.w.grant("ext.acct", "accountant")
        self.w.policy(enforce=True, segregate=True, solo_owner_self_approval=True)
        self.ap = self.c.request_approval("commitment.execute", self.w.commitment(), requested_by="travis")
        self.addCleanup(self.c.db.close)

    def snapshot(self):
        return {
            "approvals": self.c.approvals.list(),
            "audit": self.c.db.query("SELECT * FROM audit_log ORDER BY seq"),
            "self_approvals": self.c.db.query("SELECT * FROM people_self_approvals ORDER BY id"),
        }

    def self_approval_events(self):
        return self.c.db.query("SELECT * FROM audit_log WHERE action='people.self_approval_recorded'")

    def test_repeated_allowed_preflight_leaves_approvals_audit_and_self_approvals_unchanged(self):
        before = self.snapshot()
        for _ in range(2):
            self.p.check_grant(self.ap, approver="ＴＲＡＶＩＳ", approver_role="owner")
        self.assertEqual(self.snapshot(), before)

    def test_refused_preflight_leaves_approvals_audit_and_self_approvals_unchanged(self):
        before = self.snapshot()
        with self.assertRaises(IdentityRefused):
            self.p.check_grant(self.ap, approver="unregistered", approver_role="owner")
        self.assertEqual(self.snapshot(), before)

    def test_stale_preflight_refuses_without_invalidating(self):
        before = self.snapshot()
        with patch.object(self.p, "_binding", return_value={"policy_version": 99, "policy_hash": "moved"}):
            with self.assertRaises(StaleApprovalError):
                self.p.check_grant(self.ap, approver="travis", approver_role="owner")
        self.assertEqual(self.snapshot(), before)

    def test_successful_grant_records_self_approval_exactly_once(self):
        self.p.check_grant(self.ap, approver="travis", approver_role="owner")
        granted = self.c.approve(self.ap["id"], approver="ＴＲＡＶＩＳ")
        self.assertEqual(granted["status"], "granted")
        rows = self.p.self_approvals(awaiting_review=True)
        self.assertEqual([(r["approval_id"], r["login"]) for r in rows], [(self.ap["id"], "travis")])
        self.assertEqual(len(self.self_approval_events()), 1)
        before = self.snapshot()
        with self.assertRaises(ApprovalError):
            self.c.approve(self.ap["id"], approver="travis")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.p.integrity_problems(), [])

    def test_expired_grant_durably_expires_without_recording_self_approval(self):
        self.c.db.execute("UPDATE approvals SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (self.ap["id"],))
        with self.assertRaises(ApprovalExpired):
            self.c.approve(self.ap["id"], approver="travis")
        self.assertEqual(self.c.approvals.get(self.ap["id"])["status"], "expired")
        self.assertEqual(self.p.self_approvals(), [])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM people_self_approvals"), 0)
        self.assertEqual(self.self_approval_events(), [])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='approval.expired' AND entity_id=?", (self.ap["id"],)), 1)
        self.assertEqual(self.p.integrity_problems(), [])

    def test_later_governor_refusal_leaves_no_self_approval_or_audit_effect(self):
        class LaterGovernor:
            GOVERNOR = True

            def check_grant(self, approval, *, approver, approver_role):
                raise IdentityRefused("synthetic later governor refused")

        self.c.register_plugin("z_later", LaterGovernor())
        before = self.snapshot()
        with self.assertRaisesRegex(IdentityRefused, "later governor refused"):
            self.c.approve(self.ap["id"], approver="travis")
        self.assertEqual(self.snapshot(), before)

    def test_grant_hook_refusal_rolls_back_the_grant_and_self_approval(self):
        c, p, approval_id = self.c, self.p, self.ap["id"]

        class LaterGovernor:
            GOVERNOR = True

            def on_grant(self, approval, *, approver, approver_role):
                # The grant and the people hook have run inside the transaction.
                if approval["status"] == "granted" and p.self_approvals():
                    raise IdentityRefused("synthetic grant hook refused")

        c.register_plugin("z_later", LaterGovernor())
        before = self.snapshot()
        with self.assertRaisesRegex(IdentityRefused, "grant hook refused"):
            c.approve(approval_id, approver="travis")
        self.assertEqual(self.snapshot(), before)

    def test_direct_grant_hook_requires_an_existing_grant_transaction(self):
        granted = self.c.approvals.grant(self.ap["id"], approver="travis")
        before = self.snapshot()
        with self.assertRaisesRegex(PeopleError, "grant transaction"):
            self.p.on_grant(granted, approver="travis", approver_role="owner")
        self.assertEqual(self.snapshot(), before)

    def test_caught_grant_hook_refusal_does_not_leak_into_an_outer_transaction(self):
        class LaterGovernor:
            GOVERNOR = True

            def on_grant(self, approval, *, approver, approver_role):
                raise IdentityRefused("synthetic grant hook refused")

        self.c.register_plugin("z_later", LaterGovernor())
        with self.c.db.transaction():
            self.c.audit.record("travis", "test.outer_transaction", "approval", self.ap["id"], {})
            before = self.snapshot()
            with self.assertRaisesRegex(IdentityRefused, "grant hook refused"):
                self.c.approve(self.ap["id"], approver="travis")
        self.assertEqual(self.snapshot(), before)

    def test_caught_grant_check_refusal_preserves_an_outer_transaction(self):
        class LaterGovernor:
            GOVERNOR = True

            def check_grant(self, approval, *, approver, approver_role):
                raise IdentityRefused("synthetic grant check refused")

        self.c.register_plugin("z_later", LaterGovernor())
        with self.c.db.transaction():
            self.c.audit.record("travis", "test.outer_transaction", "approval", self.ap["id"], {})
            before = self.snapshot()
            with self.assertRaisesRegex(IdentityRefused, "grant check refused"):
                self.c.approve(self.ap["id"], approver="travis")
        self.assertEqual(self.snapshot(), before)

    def test_successful_nested_grant_commits_one_self_approval_with_outer_writes(self):
        with self.c.db.transaction():
            self.c.audit.record("travis", "test.outer_transaction", "approval", self.ap["id"], {})
            granted = self.c.approve(self.ap["id"], approver="travis")
            self.assertEqual(granted["status"], "granted")
        self.assertEqual(self.c.approvals.get(self.ap["id"])["status"], "granted")
        self.assertEqual(len(self.p.self_approvals()), 1)
        self.assertEqual(len(self.self_approval_events()), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='test.outer_transaction'"), 1)
        self.assertEqual(self.p.integrity_problems(), [])

    def test_nested_stale_and_expired_attempts_preserve_their_terminal_status(self):
        for case in ("stale", "expired"):
            with self.subTest(case=case):
                ap = self.c.request_approval("commitment.execute", self.w.commitment(), requested_by="travis")
                if case == "expired":
                    self.c.db.execute("UPDATE approvals SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (ap["id"],))
                with self.c.db.transaction():
                    self.c.audit.record("travis", "test.outer_transaction", "approval", ap["id"], {})
                    if case == "stale":
                        with patch.object(self.p, "_binding", return_value={"policy_version": 99, "policy_hash": "moved"}):
                            with self.assertRaises(StaleApprovalError):
                                self.c.approve(ap["id"], approver="travis")
                    else:
                        with self.assertRaises(ApprovalExpired):
                            self.c.approve(ap["id"], approver="travis")
                self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated" if case == "stale" else "expired")
                self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='test.outer_transaction' AND entity_id=?", (ap["id"],)), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM people_self_approvals"), 0)
        self.assertEqual(self.self_approval_events(), [])

    def test_stale_actual_grant_durably_invalidates_without_self_approval(self):
        with patch.object(self.p, "_binding", return_value={"policy_version": 99, "policy_hash": "moved"}):
            with self.assertRaises(StaleApprovalError):
                self.c.approve(self.ap["id"], approver="travis")
        self.assertEqual(self.c.approvals.get(self.ap["id"])["status"], "invalidated")
        self.assertEqual(self.p.self_approvals(), [])
        self.assertEqual(self.self_approval_events(), [])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='approval.invalidated' AND entity_id=?", (self.ap["id"],)), 1)


class PaymentPolicyPreflightTests(unittest.TestCase):
    def test_stale_payment_policy_preflight_is_read_only_and_actual_grant_invalidates(self):
        w = PaymentWorld()
        c, pp = w.c, w.pp
        self.addCleanup(c.db.close)
        w.adopt(first=False)
        ap = w.request(w.bill(20000)["id"])
        before = c.approvals.get(ap["id"])
        audit_before = c.db.query("SELECT * FROM audit_log ORDER BY seq")
        with patch.object(pp, "_policy", return_value=dict(pp.policy(), version=99)):
            with self.assertRaises(StaleApprovalError):
                pp.check_grant(ap, approver="owner", approver_role="owner")
            self.assertEqual(c.approvals.get(ap["id"]), before)
            self.assertEqual(c.db.query("SELECT * FROM audit_log ORDER BY seq"), audit_before)
            with self.assertRaises(StaleApprovalError):
                c.approve(ap["id"], approver="owner")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='approval.invalidated' AND entity_id=?", (ap["id"],)), 1)


if __name__ == "__main__":
    unittest.main()
