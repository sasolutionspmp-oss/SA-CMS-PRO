"""Seven-action reviews over native commercial source plans."""
import unittest

from apps.cipher.ap_contract import APRefusal
from apps.cipher.commercial_practice_fixture import (make_commercial_practice_fixture, ESTIMATOR_LOGIN, REVIEWER_LOGIN, PM_LOGIN)
from apps.cipher.commercial_preflight import CommercialPreflight
from apps.cipher.commercial_sessions import CommercialPracticeSessions
from apps.cipher.commercial_contract import CommercialContract


class CommercialPreflightTests(unittest.TestCase):
    def setUp(self):
        self.c = make_commercial_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.domain = self.c.plugin("commercial")
        self.r = self.c.commercial_practice_records
        self.people = self.c.commercial_practice_persona_people
        self.person = self.people["preparer"]["person_id"]
        self.reviewer = self.people["reviewer"]["person_id"]
        self.pm = self.people["pm"]["person_id"]
        self.secret = b"commercial-native-preflight-test-private-key"
        self.contract = CommercialContract(self.c, secret=self.secret)
        self.preflight = CommercialPreflight(self.c, self.contract, secret=self.secret)

    def state(self):
        return tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes, tuple(self.c.provider.submissions)

    def input(self, *, revised=False):
        source = self.domain.source(self.r["current_estimate_id"])
        body = {"documentRevisionId": self.r["current_drawing_revision_id"], "lines": [{
            "description": "Manual piping installation", "quantity": "13", "unit": "LF", "unitPriceCents": 2500,
            "sourceLocator": "A-101, piping plan", "costCode": "33-110"}],
            "priceBookRef": "Synthetic fixed practice rates v1", "inclusions": ["Piping installation"],
            "exclusions": ["Excavation"], "contingencyRate": "0", "measurementBasis": "Manual source quantities; geometry unverified"}
        if revised:
            body["lines"][0]["previousLineId"] = source["lines"][0]["estimate_line_id"]
            body["removedExclusions"] = []
        return body

    def review(self, person, action, resource_id, body=None, *, allowed=True):
        body = {} if body is None else body
        before = self.state()
        first = self.preflight.review(person, action, resource_id, body)
        second = self.preflight.review(person, action, resource_id, body)
        self.assertEqual(first, second)
        self.assertEqual(first["allowed"], allowed, first)
        self.assertEqual(before, self.state())
        return first

    def granted(self):
        requested = self.c.request_approval("estimate.approve", self.r["current_estimate_id"], actor_role="estimator", requested_by=ESTIMATOR_LOGIN)
        self.c.approve(requested["id"], approver=REVIEWER_LOGIN, approver_role="estimator")
        return requested["id"]

    def test_all_seven_action_reviews_are_stable_zero_effect_native_plans(self):
        create = self.review(self.person, "estimate.create", self.r["project_id"], self.input())
        self.assertEqual(create["preview"]["totalCents"], 32500)
        self.assertTrue(create["safeEffects"]["createsEstimateRevision"])
        revised = self.review(self.person, "estimate.revise", self.r["current_estimate_id"], self.input(revised=True))
        self.assertEqual(revised["preview"]["revision"], 3)
        self.review(self.person, "estimate.request", self.r["current_estimate_id"])
        requested = self.c.request_approval("estimate.approve", self.r["current_estimate_id"], actor_role="estimator", requested_by=ESTIMATOR_LOGIN)
        accepted = self.review(self.reviewer, "estimate.accept", requested["id"])
        self.assertEqual(accepted["safeEffects"]["estimateStatus"], "draft")
        self.assertEqual(accepted["safeEffects"]["approvalStatus"], "granted")
        self.c.approve(requested["id"], approver=REVIEWER_LOGIN, approver_role="estimator")
        applied = self.review(self.person, "estimate.apply", requested["id"])
        self.assertTrue(applied["safeEffects"]["createsAcceptedBaseline"])
        self.c.execute(requested["id"], actor=ESTIMATOR_LOGIN)
        self.review(self.person, "estimate.prepareHandoff", self.r["current_estimate_id"])
        handoff = self.domain.prepare_handoff(self.r["current_estimate_id"], self.r["package_id"], actor=ESTIMATOR_LOGIN)
        commit = self.review(self.pm, "estimate.createCommitment", handoff["handoffId"])
        self.assertTrue(commit["safeEffects"]["createsCommitment"])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM commitments"), 0)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)

    def test_exact_body_actor_and_native_locator_changes_invalidate_original_review(self):
        body = self.input(revised=True)
        review = self.preflight.review(self.person, "estimate.revise", self.r["current_estimate_id"], body)
        self.preflight.verify(self.person, "estimate.revise", self.r["current_estimate_id"],
                              {**body, "fingerprint": review["fingerprint"]}, review["resourceVersion"])
        body["lines"][0]["sourceLocator"] = "A-101, changed locator"
        before = self.state()
        with self.assertRaises(APRefusal) as caught:
            self.preflight.verify(self.person, "estimate.revise", self.r["current_estimate_id"],
                                  {**body, "fingerprint": review["fingerprint"]}, review["resourceVersion"])
        self.assertEqual(caught.exception.status, 412)
        self.assertEqual(before, self.state())
        with self.assertRaises(APRefusal) as unicode_token:
            self.preflight.verify(self.person, "estimate.revise", self.r["current_estimate_id"],
                                  {**self.input(revised=True), "fingerprint": "€"}, review["resourceVersion"])
        self.assertEqual(unicode_token.exception.status, 412)
        self.assertEqual(before, self.state())

    def test_foreign_source_and_line_refs_are_404_before_domain_aggregates(self):
        hidden = self.domain.source(self.r["hidden_estimate_id"])
        body = self.input(revised=True)
        for field, value in (("documentRevisionId", hidden["drawing"]["revisionId"]),
                             ("previousLineId", hidden["lines"][0]["estimate_line_id"])):
            candidate = {**body, "lines": [dict(body["lines"][0])]}
            if field == "documentRevisionId":
                candidate[field] = value
            else:
                candidate["lines"][0][field] = value
            before = self.state()
            with self.subTest(field=field), self.assertRaises(APRefusal) as caught:
                self.preflight.review(self.person, "estimate.revise", self.r["current_estimate_id"], candidate)
            self.assertEqual(caught.exception.status, 404)
            self.assertEqual(before, self.state())

    def test_self_authorization_duplicate_request_and_early_handoff_are_pure_blocks(self):
        self.review(self.person, "estimate.prepareHandoff", self.r["current_estimate_id"], allowed=False)
        requested = self.c.request_approval("estimate.approve", self.r["current_estimate_id"], actor_role="estimator", requested_by=ESTIMATOR_LOGIN)
        self.review(self.person, "estimate.accept", requested["id"], allowed=False)
        duplicate = self.review(self.person, "estimate.request", self.r["current_estimate_id"], allowed=False)
        self.assertEqual(duplicate["checks"][-1]["code"], "duplicate_request")

    def test_native_source_births_lineage_package_and_session_are_genuine(self):
        old = self.domain.source(self.r["superseded_estimate_id"])
        current = self.domain.source(self.r["current_estimate_id"])
        self.assertEqual([line["stable_line_id"] for line in old["lines"]], [line["stable_line_id"] for line in current["lines"]])
        self.assertEqual([line["estimate_line_id"] for line in old["lines"]], [line["previous_line_id"] for line in current["lines"]])
        self.assertFalse(current["verifiedGeometry"])
        self.assertEqual(self.domain.package(self.r["package_id"])["created_by"], PM_LOGIN)
        sessions = CommercialPracticeSessions(self.c)
        before = self.state()
        anonymous = sessions.anonymous()
        selected = sessions.select(anonymous, "preparer")
        self.assertIsNone(sessions.get(anonymous.cookie_token))
        self.assertFalse(sessions.validate_csrf(selected, anonymous.csrf_token))
        self.assertTrue(sessions.validate_csrf(selected, selected.csrf_token))
        dto = sessions.dto(selected)
        self.assertEqual(dto["duties"], ["estimator"])
        self.assertFalse(dto["capabilities"]["microsoftSignIn"])
        self.assertEqual(before, self.state())


if __name__ == "__main__":
    unittest.main()
