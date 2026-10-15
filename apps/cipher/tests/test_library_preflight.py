"""Real authored sources, independent native review and side-effect-free HMAC plans."""
import unittest
from datetime import timedelta
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.core.ids import parse_iso
from apps.cipher.library_contract import LibraryContract
from apps.cipher.library_preflight import LibraryPreflight
from apps.cipher.library_practice_fixture import make_library_practice_fixture, PM_LOGIN, REVIEWER_LOGIN


class LibraryPreflightTests(unittest.TestCase):
    def setUp(self):
        self.c = make_library_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.domain = self.c.plugin("library")
        self.project = self.c.library_practice_records["project_id"]
        self.people = self.c.library_practice_persona_people
        self.author, self.reviewer = self.people["author"]["person_id"], self.people["reviewer"]["person_id"]
        self.secret = b"library-native-review-key-at-least-thirty-two-bytes"
        self.contract = LibraryContract(self.c, secret=self.secret)
        self.preflight = LibraryPreflight(self.c, self.contract, secret=self.secret)
        self.body = {"kind": "specification_template", "title": "Synthetic installation specification",
                     "text": "Original synthetic authored clause.\nMaintain access for café users.",
                     "sourceLocator": "Synthetic authoring editor / section 1"}

    def snapshot(self):
        return tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes, tuple(self.c.provider.submissions)

    def reviewed(self, person, action, resource, body):
        before = self.snapshot()
        review = self.preflight.review(person, action, resource, body)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(review["allowed"], review)
        self.assertEqual(review, self.preflight.review(person, action, resource, body))
        context = self.preflight.verify(person, action, resource, {**body, "fingerprint": review["fingerprint"]}, review["resourceVersion"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(context["operationRole"], "pm")
        self.assertEqual(context["typed"], body)
        effects = review["safeEffects"]
        self.assertEqual((effects["journalDelta"], effects["mailSinkDelta"]), (0, 0))
        for key in ("externalDistribution", "contractExecution", "engineeringCertification"):
            self.assertIs(effects[key], False)
        self.assertIs(effects["projectReferenceOnly"], True)
        return review, context

    def entry(self):
        return self.domain.create(self.project, self.body, actor=PM_LOGIN)

    def test_all_six_real_reviews_are_pure_and_exact_native_consequences(self):
        review, _ = self.reviewed(self.author, "library.create", self.project, self.body)
        self.assertEqual(review["preview"]["text"], self.body["text"])
        self.assertEqual(review["preview"]["byteCount"], len(self.body["text"].encode("utf-8")))
        self.assertEqual(review["safeEffects"]["entriesDelta"], 1)
        entry = self.entry()
        entry_id = entry["entry"]["record"]["id"]
        revision = {"previousRevisionId": entry["currentRevisionId"], "text": "Revised synthetic authored text.",
                    "sourceLocator": "Synthetic authoring editor / section 2", "changeReason": "Clarify the temporary access requirement"}
        review, _ = self.reviewed(self.author, "library.revise", entry_id, revision)
        self.assertEqual(review["safeEffects"]["revisionsDelta"], 1)
        current = self.domain.revise(entry_id, revision, actor=PM_LOGIN)
        intent = {"targetLocator": "Project reference binder / installation", "purpose": "Internal planning reference"}
        review, _ = self.reviewed(self.author, "library.prepareReference", current["currentRevisionId"], intent)
        self.assertEqual(review["preview"]["text"], revision["text"])
        reference = self.domain.prepare_reference(current["currentRevisionId"], intent, actor=PM_LOGIN)
        review, _ = self.reviewed(self.author, "library.requestAdoption", reference["id"], {})
        self.assertEqual(review["safeEffects"]["approvalStatus"], "pending")
        approval = self.c.request_approval("library.adopt_reference", reference["id"], actor_role="pm", requested_by=PM_LOGIN)
        review, _ = self.reviewed(self.reviewer, "library.approveAdoption", approval["id"], {})
        self.assertEqual(review["safeEffects"]["approvalStatus"], "granted")
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="pm")
        review, _ = self.reviewed(self.author, "library.applyAdoption", approval["id"], {})
        self.assertEqual(review["safeEffects"]["projectReferencesDelta"], 1)
        self.c.execute(approval["id"], actor=PM_LOGIN)
        adopted = self.domain.adoption_inventory(project_ids=(self.project,))
        self.assertEqual(len(adopted), 1)
        self.assertEqual(adopted[0]["record"]["text"], revision["text"])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)

    def test_typed_text_version_and_private_key_changes_refuse_without_writes(self):
        review = self.preflight.review(self.author, "library.create", self.project, self.body)
        before = self.snapshot()
        for typed, version, preflight in (
            ({**self.body, "text": self.body["text"] + " Changed."}, review["resourceVersion"], self.preflight),
            (self.body, "different-version", self.preflight),
            (self.body, review["resourceVersion"], LibraryPreflight(self.c, self.contract, secret=b"another-library-private-key-of-thirty-two-bytes")),
        ):
            with self.assertRaises(APRefusal) as caught:
                preflight.verify(self.author, "library.create", self.project,
                    {**typed, "fingerprint": review["fingerprint"]}, version)
            self.assertEqual(caught.exception.status, 412)
            self.assertEqual(self.snapshot(), before)

    def test_hidden_scope_precedes_private_source_checks(self):
        before = self.snapshot()
        with patch.object(self.domain, "create_preflight", side_effect=AssertionError("Hidden source disclosed")) as source:
            with self.assertRaises(APRefusal) as caught:
                self.preflight.review(self.author, "library.create", self.c.library_practice_records["hidden_project_id"], self.body)
            self.assertEqual(caught.exception.status, 404)
            source.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_current_revision_change_refuses_old_preparation_and_review(self):
        entry = self.entry()
        entry_id = entry["entry"]["record"]["id"]
        body = {"previousRevisionId": entry["currentRevisionId"], "text": "First proposed successor", "sourceLocator": "Section 2", "changeReason": "First proposed change"}
        review = self.preflight.review(self.author, "library.revise", entry_id, body)
        self.domain.revise(entry_id, {**body, "text": "A genuine different native successor"}, actor=REVIEWER_LOGIN)
        before = self.snapshot()
        blocked = self.preflight.review(self.author, "library.revise", entry_id, body)
        self.assertFalse(blocked["allowed"])
        self.assertIsNone(blocked["fingerprint"])
        with self.assertRaises(APRefusal) as caught:
            self.preflight.verify(self.author, "library.revise", entry_id, {**body, "fingerprint": review["fingerprint"]}, review["resourceVersion"])
        self.assertEqual(caught.exception.status, 412)
        self.assertEqual(self.snapshot(), before)

    def test_self_review_is_blocked_and_exact_pending_request_is_not_duplicated(self):
        entry = self.entry()
        intent = self.domain.prepare_reference(entry["currentRevisionId"], {"targetLocator": "Binder 1", "purpose": "Internal planning"}, actor=PM_LOGIN)
        approval = self.c.request_approval("library.adopt_reference", intent["id"], actor_role="pm", requested_by=PM_LOGIN)
        before = self.snapshot()
        for action, resource in (("library.requestAdoption", intent["id"]), ("library.approveAdoption", approval["id"])):
            review = self.preflight.review(self.author, action, resource, {})
            self.assertFalse(review["allowed"])
            self.assertIsNone(review["fingerprint"])
        self.assertEqual(self.snapshot(), before)

    def test_real_original_authorization_deadline_holds_review_without_writes(self):
        entry = self.entry()
        intent = self.domain.prepare_reference(entry["currentRevisionId"], {"targetLocator": "Binder 1", "purpose": "Internal planning"}, actor=PM_LOGIN)
        approval = self.c.request_approval("library.adopt_reference", intent["id"], actor_role="pm", requested_by=PM_LOGIN)
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="pm")
        deadline = parse_iso(approval["expires_at"]) + timedelta(seconds=1)
        before = self.snapshot()
        with patch("apps.cipher.domain.library.utcnow", return_value=deadline):
            blocked = self.preflight.review(self.author, "library.applyAdoption", approval["id"], {})
            self.assertFalse(blocked["allowed"])
            self.assertEqual(blocked["checks"][0]["code"], "library_authorization_expired")
            self.assertIsNone(blocked["fingerprint"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.c.approvals.get(approval["id"])["expires_at"], approval["expires_at"])

    def test_unknown_shape_and_nontext_values_cannot_enter_a_review(self):
        before = self.snapshot()
        for body in ({**self.body, "actor": PM_LOGIN}, {**self.body, "text": True}, {**self.body, "text": "\x00"}, {**self.body, "text": "x" * 65537}):
            with self.assertRaises(APRefusal) as caught:
                self.preflight.review(self.author, "library.create", self.project, body)
            self.assertEqual(caught.exception.status, 422)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
