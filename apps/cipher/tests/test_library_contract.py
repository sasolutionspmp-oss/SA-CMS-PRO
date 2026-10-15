"""Public source text, immutable copies, current authority and scoped paging."""
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.library_contract import LibraryContract
from apps.cipher.library_practice_fixture import (make_library_practice_fixture, PM_LOGIN, REVIEWER_LOGIN,
    HIDDEN_PM_LOGIN, BOOTSTRAP_LOGIN)


class LibraryContractTests(unittest.TestCase):
    def setUp(self):
        self.c = make_library_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.d = self.c.plugin("library")
        self.k = LibraryContract(self.c, secret=b"library-real-contract-integration-private-key")
        self.person = self.c.library_practice_persona_people["author"]["person_id"]
        self.reviewer = self.c.library_practice_persona_people["reviewer"]["person_id"]
        self.project = self.c.library_practice_records["project_id"]

    def state(self):
        return tuple(self.c.db.conn.iterdump()), tuple(self.c.provider.submissions)

    def create(self, title="Synthetic authored clause", text="Synthetic exact authored text.\nSecond line.", *, hidden=False):
        project = self.c.library_practice_records["hidden_project_id"] if hidden else self.project
        return self.d.create(project, {"kind": "contract_clause", "title": title, "text": text,
            "sourceLocator": "Author editor / original clause"}, actor=HIDDEN_PM_LOGIN if hidden else PM_LOGIN)

    def adopted(self):
        entry = self.create()
        plan = self.d.prepare_reference(entry["currentRevisionId"], {"targetLocator": "Project reference / section 1", "purpose": "Internal synthetic project use"}, actor=PM_LOGIN)
        approval = self.c.request_approval("library.adopt_reference", plan["id"], actor_role="pm", requested_by=PM_LOGIN)
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="pm")
        result = self.c.execute(approval["id"], actor=PM_LOGIN).result
        return entry, plan, approval, result

    def test_empty_real_fixture_read_and_preparation_are_pure_and_advertise_actual_editor(self):
        before = self.state()
        prep = self.k.preparation(self.person, self.project)
        self.assertEqual(prep["maxTextBytes"], 65536)
        self.assertEqual(prep["encoding"], "UTF-8")
        self.assertEqual(prep["kinds"], ["specification_template", "contract_clause"])
        for collection in ("library-entries", "reference-plans", "adoption-approvals", "project-references"):
            self.assertEqual(self.k.read(self.person, collection)["count"], 0)
        self.assertEqual(self.state(), before)

    def test_text_and_multibyte_size_are_exact_and_history_preserves_both_revisions(self):
        original = self.create(text="  Synthetic café clause.\r\nKeep whitespace.  ")
        entry_id = original["entry"]["record"]["id"]
        first_id = original["currentRevisionId"]
        self.d.revise(entry_id, {"previousRevisionId": first_id, "text": "Synthetic later authored clause.", "sourceLocator": "Editor / revised clause", "changeReason": "Synthetic clarification"}, actor=PM_LOGIN)
        before = self.state()
        dto = self.k.entry(self.person, entry_id)
        first, second = dto["revisions"]
        self.assertEqual(first["text"], "  Synthetic café clause.\r\nKeep whitespace.  ")
        self.assertEqual(first["byteCount"], len(first["text"].encode()))
        self.assertFalse(first["isCurrent"])
        self.assertTrue(second["isCurrent"])
        self.assertEqual(second["previousRevisionId"], first_id)
        self.assertEqual(self.k.revision(self.person, first_id)["contentHash"], first["contentHash"])
        self.assertEqual(dto["version"], self.k.version(self.person, entry_id, "entry"))
        self.assertEqual(self.state(), before)

    def test_original_adopted_copy_survives_real_later_edit_with_current_head_separate(self):
        entry, plan, approval, result = self.adopted()
        reference_id = result["referenceId"]
        original = self.k.reference(self.person, reference_id)
        self.d.revise(entry["entry"]["record"]["id"], {"previousRevisionId": entry["currentRevisionId"], "text": "Synthetic new current wording.",
            "sourceLocator": "Editor / later revision", "changeReason": "Synthetic supersession"}, actor=PM_LOGIN)
        before = self.state()
        current = self.k.reference(self.person, reference_id)
        self.assertEqual(current["text"], original["text"])
        self.assertEqual(current["contentHash"], original["contentHash"])
        self.assertEqual(current["revisionId"], original["revisionId"])
        self.assertFalse(current["sourceCurrent"])
        self.assertNotEqual(current["currentRevisionId"], current["revisionId"])
        self.assertEqual(current["status"], "adopted_reference")
        packet = self.k.packet(self.person, approval["id"])
        self.assertEqual(packet["status"], "consumed")
        self.assertEqual(packet["plan"]["sourceRevision"]["text"], original["text"])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        self.assertEqual(self.state(), before)

    def test_hidden_entry_is_refused_before_source_text_and_aggregate_counts(self):
        hidden = self.create(title="Hidden private authored text", hidden=True)
        entry_id = hidden["entry"]["record"]["id"]
        with patch.object(self.d, "entry_proof", side_effect=AssertionError("Hidden text proof was read")) as proof:
            with self.assertRaises(APRefusal) as caught:
                self.k.entry(self.person, entry_id)
            self.assertEqual(caught.exception.status, 404)
            proof.assert_not_called()
        visible = self.k.read(self.person, "library-entries")
        self.assertEqual(visible["count"], 0)
        with patch.object(self.k, "_materials", side_effect=AssertionError("Hidden aggregate was read")) as materials:
            with self.assertRaises(APRefusal) as caught:
                self.k.read(self.person, "library-entries", project_id=self.c.library_practice_records["hidden_project_id"])
            self.assertEqual(caught.exception.status, 404)
            materials.assert_not_called()

    def test_current_owned_duty_is_rederived_before_private_metadata(self):
        entry = self.create()
        self.c.plugin("people").end_membership(PM_LOGIN, self.project, reason="Synthetic project duty ended", actor=BOOTSTRAP_LOGIN)
        before = self.state()
        with patch.object(self.k, "_materials", side_effect=AssertionError("Ended member read a source inventory")) as materials:
            with self.assertRaises(APRefusal):
                self.k.entry(self.person, entry["entry"]["record"]["id"])
            materials.assert_not_called()
        self.assertEqual(self.state(), before)

    def test_person_with_no_current_own_pm_scope_cannot_read_global_receipt_metadata(self):
        self.c.plugin("people").end_membership(PM_LOGIN, self.project, reason="Synthetic current PM membership ended", actor=BOOTSTRAP_LOGIN)
        before = self.state()
        with patch.object(self.k, "_materials", side_effect=AssertionError("No-scope person read private global metadata")) as materials:
            with self.assertRaises(APRefusal) as caught:
                self.k.read(self.person, "library-entries")
            self.assertEqual(caught.exception.status, 403)
            materials.assert_not_called()
        self.assertEqual(self.state(), before)

    def test_search_reads_actual_current_text_and_cursors_bind_scope_query_and_new_source(self):
        first = self.create(title="A synthetic clause", text="Unique authored needle in actual source text.")
        self.create(title="B synthetic clause")
        self.create(title="C synthetic clause")
        self.assertEqual(self.k.read(self.person, "library-entries", search="authored needle")["count"], 1)
        page = self.k.read(self.person, "library-entries", top=1)
        self.assertEqual(page["count"], 3)
        self.assertIsNotNone(page["nextCursor"])
        self.assertEqual(len(self.k.read(self.person, "library-entries", top=1, cursor=page["nextCursor"])["items"]), 1)
        for person, query in ((self.reviewer, {}), (self.person, {"search": "needle"})):
            with self.subTest(person=person), self.assertRaises(APRefusal):
                self.k.read(person, "library-entries", top=1, cursor=page["nextCursor"], **query)
        self.d.revise(first["entry"]["record"]["id"], {"previousRevisionId": first["currentRevisionId"], "text": "Later wording changes source.",
            "sourceLocator": "Editor / changed source", "changeReason": "Synthetic current edit"}, actor=PM_LOGIN)
        with self.assertRaises(APRefusal):
            self.k.read(self.person, "library-entries", top=1, cursor=page["nextCursor"])

    def test_pending_plan_marks_stale_after_a_real_revision_without_relabeling_original_intent(self):
        entry = self.create()
        plan = self.d.prepare_reference(entry["currentRevisionId"], {"targetLocator": "Project section 1", "purpose": "Internal reference"}, actor=PM_LOGIN)
        approval = self.c.request_approval("library.adopt_reference", plan["id"], actor_role="pm", requested_by=PM_LOGIN)
        self.d.revise(entry["entry"]["record"]["id"], {"previousRevisionId": entry["currentRevisionId"], "text": "Later wording.",
            "sourceLocator": "Editor / later wording", "changeReason": "Synthetic current edit"}, actor=PM_LOGIN)
        dto = self.k.plan(self.person, plan["id"])
        self.assertEqual(dto["creationStatus"], "prepared")
        self.assertEqual(dto["status"], "pending")
        self.assertEqual(dto["effectiveStatus"], "stale")
        self.assertEqual(self.k.packet(self.person, approval["id"])["authorizationStatus"], "stale")
        self.assertEqual(self.k.read(self.person, "reference-plans", status="stale")["count"], 1)

    def test_lost_original_head_holds_entry_search_plan_and_reference_reads(self):
        entry, plan, approval, result = self.adopted()
        head = entry["currentHead"]["record"]
        guard = self.c.db.one("SELECT sql FROM sqlite_master WHERE name='library_heads_no_delete'")["sql"]
        self.c.db.execute("DROP TRIGGER library_heads_no_delete")
        self.c.db.execute("DELETE FROM library_heads WHERE id=?", (head["id"],))
        self.c.db.execute(guard)
        before = self.state()
        for read in (lambda: self.k.read(self.person, "library-entries"), lambda: self.k.entry(self.person, entry["entry"]["record"]["id"]),
                     lambda: self.k.plan(self.person, plan["id"]), lambda: self.k.reference(self.person, result["referenceId"])):
            with self.assertRaises(APRefusal) as caught: read()
            self.assertEqual(caught.exception.status, 423)
        self.assertEqual(self.state(), before)

    def test_lost_api_admission_holds_public_reads_but_keeps_native_original_copy(self):
        _entry, _plan, _approval, result = self.adopted()
        original = self.d.original_reference_proof(result["referenceId"])
        self.c.db.execute("DELETE FROM schema_version WHERE name='library_practice_action_receipts'")
        self.assertEqual(self.d.original_reference_proof(result["referenceId"]), original)
        before = self.state()
        with self.assertRaises(APRefusal) as caught:
            self.k.reference(self.person, result["referenceId"])
        self.assertEqual(caught.exception.status, 423)
        self.assertEqual(self.state(), before)

    def test_real_later_license_history_holds_current_text_views_after_untagging(self):
        entry, _plan, _approval, result = self.adopted()
        original = self.d.original_reference_proof(result["referenceId"])
        rights = self.c.plugin("rights")
        license = rights.register_license("Synthetic publisher", "Synthetic restricted text", "Practice edition", "Synthetic holder",
            ["internal_reference"], actor=BOOTSTRAP_LOGIN)
        document = entry["entry"]["record"]["document_id"]
        rights.tag_document(document, license["id"], actor=BOOTSTRAP_LOGIN)
        rights.untag_document(document, license["id"], actor=BOOTSTRAP_LOGIN, reason="Synthetic later tag removal retains its real history")
        self.assertEqual(self.d.original_reference_proof(result["referenceId"]), original)
        before = self.state()
        for read in (lambda: self.k.read(self.person, "library-entries", search="authored"),
                     lambda: self.k.reference(self.person, result["referenceId"]),
                     lambda: self.k.entry(self.person, entry["entry"]["record"]["id"])):
            with self.assertRaises(APRefusal) as caught: read()
            self.assertEqual(caught.exception.status, 423)
        self.assertEqual(self.state(), before)


if __name__ == "__main__":
    unittest.main()
