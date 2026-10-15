"""The AP harness seeds genuine scoped people and business approval history."""
import inspect
import unittest
from unittest.mock import patch

from apps.cipher.ap_practice_fixture import ACCOUNTANT_LOGIN, BOOTSTRAP_LOGIN, PM_LOGIN, REVIEWER_LOGIN, make_ap_practice_fixture
from apps.cipher.service import Cipher


class APPracticeFixtureTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.records = self.c.ap_practice_records
        self.people = self.c.plugin("people")

    def test_factory_admits_no_file_provider_actor_or_mode_and_owns_fresh_memory(self):
        self.assertEqual(list(inspect.signature(make_ap_practice_fixture).parameters), [])
        self.assertEqual(self.c.db.path, ":memory:")
        self.assertEqual(self.c.db.require_practice_mode()["mode"], "practice")
        other = make_ap_practice_fixture()
        self.addCleanup(other.db.close)
        self.assertIsNot(self.c.db, other.db)
        self.assertNotEqual(self.records["draft_bill_id"], other.ap_practice_records["draft_bill_id"])

    def test_business_grants_are_genuine_service_calls_and_no_posting_is_seeded(self):
        original = Cipher.approve
        calls = []

        def observe(cipher, approval_id, **kwargs):
            calls.append((cipher.approvals.get(approval_id)["operation"], kwargs))
            return original(cipher, approval_id, **kwargs)

        with patch.object(Cipher, "approve", observe), patch.object(Cipher, "post_bill", side_effect=AssertionError("seed must not post")):
            fixture = make_ap_practice_fixture()
        self.addCleanup(fixture.db.close)
        bill_grants = [kwargs for operation, kwargs in calls if operation == "bill.approve"]
        self.assertEqual(len(bill_grants), 2)
        self.assertEqual(bill_grants[0], {"approver": PM_LOGIN, "approver_role": "pm"})
        self.assertTrue(all(kwargs["approver_role"] == "pm" for kwargs in bill_grants))
        self.assertEqual(len(fixture.db.query("SELECT * FROM bill_business_approvals")), 2)
        self.assertEqual(fixture.db.query("SELECT * FROM bill_posting_receipts"), [])

    def test_draft_and_approved_bills_are_on_separate_genuinely_executed_commitments(self):
        draft = self.c.bills.get(self.records["draft_bill_id"])
        approved = self.c.bills.get(self.records["approved_bill_id"])
        hidden = self.c.bills.get(self.records["hidden_bill_id"])
        self.assertEqual((draft["status"], approved["status"], hidden["status"]), ("draft", "approved", "approved"))
        self.assertNotEqual(draft["commitment_id"], approved["commitment_id"])
        self.assertEqual(draft["cumulative_installed"], "12345.67")
        self.assertEqual(approved["cumulative_installed"], "23456.78")
        self.assertEqual(len(self.c.projects()), 3)
        for bill in (draft, approved, hidden):
            self.assertEqual(self.c.commitments.get(bill["commitment_id"])["status"], "executed")
            self.assertIsNone(bill["journal_id"])
            self.assertIsNone(bill["posting_receipt_id"])
            self.assertEqual(self.c.bills.open_payable(bill["id"]), 0)
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 0)

    def test_each_selectable_person_has_only_real_project_grants_and_active_memberships(self):
        self.assertEqual({option["personaId"] for option in self.c.ap_practice_personas}, {"accountant", "pm", "reviewer"})
        self.assertNotIn(BOOTSTRAP_LOGIN, {person["login"] for person in self.c.ap_practice_persona_people.values()})
        self.assertNotEqual(self.people.person_for(ACCOUNTANT_LOGIN)["id"], self.people.person_for(PM_LOGIN)["id"])
        self.assertNotEqual(self.people.person_for(ACCOUNTANT_LOGIN)["id"], self.people.person_for(REVIEWER_LOGIN)["id"])
        for login, role in ((ACCOUNTANT_LOGIN, "accountant"), (PM_LOGIN, "pm"), (REVIEWER_LOGIN, "accountant")):
            grants = self.people.grants(login)
            self.assertEqual({grant["role"] for grant in grants}, {role})
            self.assertEqual({grant["scope"] for grant in grants}, {"project"})
            self.assertEqual({grant["project_id"] for grant in grants}, set(self.records["visible_project_ids"]))
            self.assertTrue(all(grant["origin"] == "approval" and grant["effective_today"] for grant in grants))
            person_id = self.people.person_for(login)["id"]
            memberships = [membership for membership in self.people.memberships() if membership["person_id"] == person_id]
            self.assertEqual({membership["project_id"] for membership in memberships}, set(self.records["visible_project_ids"]))
            self.assertTrue(all(membership["status"] == "active" for membership in memberships))

    def test_enforcing_policy_is_a_genuine_adoption_with_no_solo_exception_or_defaults_changed(self):
        policy = self.people.current_policy()
        self.assertEqual(policy["rules"], {"enforce": True, "segregate": True, "solo_owner_self_approval": False})
        self.assertTrue(policy["intact"])
        self.assertEqual(len(self.c.db.query("SELECT * FROM audit_log WHERE action='people.policy_adopted'")), 1)
        self.assertEqual(self.people.authority_problems(), [])
        self.assertTrue(self.c.audit.verify_chain()["ok"])
        self.assertEqual(self.people.self_approvals(), [])
        pristine = Cipher(":memory:")
        self.addCleanup(pristine.db.close)
        self.assertIsNone(pristine.plugin("people").current_policy())

    def test_accountant_requests_distinct_pm_grants_then_same_accountant_posts(self):
        bill_id = self.records["draft_bill_id"]
        approval = self.c.request_approval("bill.approve", bill_id, actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.assertEqual(approval["status"], "pending")
        self.c.approve(approval["id"], approver=PM_LOGIN, approver_role="pm")
        self.assertEqual(self.c.bills.get(bill_id)["status"], "approved")
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 0)
        self.assertEqual(self.c.bills.open_payable(bill_id), 0)
        result = self.c.post_bill(bill_id, actor=ACCOUNTANT_LOGIN, actor_role="accountant", period_id="2026-11",
                                  reason="Reviewed later-period practice posting")
        self.assertEqual(result.result["status"], "posted")
        receipt = self.c.bills.posting_receipt(bill_id)
        self.assertEqual(receipt["posted_by"], ACCOUNTANT_LOGIN)
        self.assertEqual(self.c.approvals.get(receipt["approval_id"])["approver"], PM_LOGIN)
        self.assertEqual(receipt["period_id"], "2026-11")
        self.assertGreater(self.c.bills.open_payable(bill_id), 0)
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_fixture_never_dispatches_payment_or_creates_external_handoff(self):
        self.assertEqual(self.c.provider.submissions, [])
        self.assertEqual(self.c.provider.transfers, {})
        self.assertEqual(self.c.db.query("SELECT * FROM payment_intents"), [])
        self.assertEqual(self.c.db.query("SELECT * FROM outbox"), [])
