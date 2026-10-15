"""Current estimator duties use real audited people and native service checks."""
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.domain.people import IdentityRefused
from apps.cipher.commercial_practice_fixture import (make_commercial_practice_fixture, BOOTSTRAP_LOGIN,
    ESTIMATOR_LOGIN, REVIEWER_LOGIN, PM_LOGIN, ACCOUNTANT_LOGIN)
from apps.cipher.commercial_sessions import authority_for, require_estimator


class CommercialEstimatorControls(unittest.TestCase):
    def setUp(self):
        self.c = make_commercial_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.project = self.c.commercial_practice_records["project_id"]
        self.estimate = self.c.commercial_practice_records["current_estimate_id"]

    def state(self):
        return tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes, tuple(self.c.provider.submissions)

    def test_real_estimator_people_have_own_scoped_duties_and_pm_has_no_estimator_duty(self):
        before = self.state()
        for key in ("preparer", "reviewer"):
            person = self.c.commercial_practice_persona_people[key]
            authority = authority_for(self.c, person["person_id"], persona_id=key)
            self.assertTrue(authority.allows(self.project, "estimator"))
            self.assertFalse(authority.allows(self.project, "pm"))
            self.assertNotIn(self.c.commercial_practice_records["hidden_project_id"], authority.project_ids)
        pm = self.c.commercial_practice_persona_people["pm"]
        self.assertTrue(authority_for(self.c, pm["person_id"], persona_id="pm").allows(self.project, "pm"))
        self.assertFalse(authority_for(self.c, pm["person_id"]).allows(self.project, "estimator"))
        self.assertFalse(hasattr(self.c, "ap_practice_persona_people"))
        self.assertEqual(before, self.state())

    def test_authority_and_actual_estimator_guards_are_stable_and_zero_write(self):
        before = self.state()
        first = require_estimator(self.c, ESTIMATOR_LOGIN, self.project)
        self.assertEqual(first, require_estimator(self.c, ESTIMATOR_LOGIN, self.project))
        self.assertEqual(before, self.state())
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM commitments"), 0)

    def test_accountant_pm_and_owner_cannot_request_by_estimator_role_selector(self):
        for actor in (ACCOUNTANT_LOGIN, PM_LOGIN, BOOTSTRAP_LOGIN):
            before = self.state()
            with self.subTest(actor=actor), patch.object(self.c, "_commercial_domain_check") as source_check, \
                    patch.object(self.c, "_manifest") as manifest, self.assertRaises(IdentityRefused):
                self.c.check_estimate_request(self.estimate, requested_by=actor, actor_role="estimator")
            source_check.assert_not_called()
            manifest.assert_not_called()
            self.assertEqual(before, self.state())

    def test_wrong_role_text_by_real_estimator_does_not_build_source_or_manifest(self):
        for role in ("owner", "accountant", "pm", "controller"):
            before = self.state()
            with self.subTest(role=role), patch.object(self.c, "_commercial_domain_check") as source_check, \
                    patch.object(self.c, "_manifest") as manifest, self.assertRaises(IdentityRefused):
                self.c.check_estimate_request(self.estimate, requested_by=ESTIMATOR_LOGIN, actor_role=role)
            source_check.assert_not_called()
            manifest.assert_not_called()
            self.assertEqual(before, self.state())

    def test_ended_actual_membership_changes_scope_and_blocks_guard_without_write(self):
        before_authority = require_estimator(self.c, ESTIMATOR_LOGIN, self.project)
        self.c.plugin("people").end_membership(ESTIMATOR_LOGIN, self.project, reason="Synthetic ended commercial assignment", actor=BOOTSTRAP_LOGIN)
        before = self.state()
        identifier = self.c.plugin("people").person_for(ESTIMATOR_LOGIN)["id"]
        after = authority_for(self.c, identifier)
        self.assertNotEqual(before_authority["scopeHash"], after.scope_hash)
        self.assertEqual(after.project_ids, ())
        with self.assertRaises(APRefusal):
            require_estimator(self.c, ESTIMATOR_LOGIN, self.project)
        self.assertEqual(before, self.state())


if __name__ == "__main__":
    unittest.main()
