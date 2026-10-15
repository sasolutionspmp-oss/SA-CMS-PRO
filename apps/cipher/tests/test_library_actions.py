"""Actual fixed library actions and append-only original receipt controls."""
import json
import datetime
import os
from pathlib import Path
import subprocess
import sys
import sqlite3
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.service import Cipher
from apps.cipher.library_receipts import (
    LibraryReceiptError, LibraryReceipts, library_receipt_inventory_proof,
    register_library_receipts_schema,
)
from apps.cipher.ap_contract import APRefusal
from apps.cipher.library_actions import LibraryActionRunner
from apps.cipher.library_contract import LibraryContract
from apps.cipher.library_preflight import LibraryPreflight
from apps.cipher.library_practice_fixture import (make_library_practice_fixture, PM_LOGIN, REVIEWER_LOGIN, BOOTSTRAP_LOGIN)
from apps.cipher.library_wire import ACTIONS, CONTRACT_VERSION
from apps.cipher.core.ids import parse_iso, utcnow


class LibraryReceiptMetadataTests(unittest.TestCase):
    def setUp(self):
        self.c = Cipher()
        self.addCleanup(self.c.db.close)
        register_library_receipts_schema()
        self.c.db.migrate()

    def test_import_does_not_register_or_initialize_library(self):
        script = """import json
from apps.cipher.core.db import SCHEMA_CATALOG
before=tuple((n,name,tuple(sql)) for n,name,sql in SCHEMA_CATALOG)
import apps.cipher.library_receipts
print(json.dumps({'unchanged':before==tuple((n,name,tuple(sql)) for n,name,sql in SCHEMA_CATALOG)}))
"""
        completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3])})
        self.assertEqual(json.loads(completed.stdout), {"unchanged": True})

    def test_metadata_inventory_is_pure_and_requires_no_domain_or_ap_callback(self):
        before = tuple(self.c.db.conn.iterdump())
        with patch.object(self.c, "plugin", side_effect=AssertionError("domain callback")), \
             patch("apps.cipher.core.api_receipts.APIActionReceipts.require_repeatability_namespace", side_effect=AssertionError("AP callback")):
            self.assertEqual(library_receipt_inventory_proof(self.c.db, self.c.audit), [])
        self.assertEqual(before, tuple(self.c.db.conn.iterdump()))

    def test_missing_named_admission_fails_closed_even_with_empty_receipt_inventory(self):
        self.c.db.execute("DELETE FROM schema_version WHERE name='library_practice_action_receipts'")
        with self.assertRaises(LibraryReceiptError):
            LibraryReceipts(self.c.db, self.c.audit).verify_integrity()
        with self.assertRaises(LibraryReceiptError):
            library_receipt_inventory_proof(self.c.db, self.c.audit)

    def test_named_receipt_proves_its_physical_prefix_independently_of_later_entries(self):
        # These are all actual applied schemas. Historical physical ordering
        # may differ from the canonical catalog; no catalog entry is invented.
        with self.c.db.transaction() as conn:
            conn.execute("UPDATE schema_version SET version=-1 WHERE name='library_practice_action_receipts'")
            conn.execute("UPDATE schema_version SET version=77 WHERE name='ar_practice_action_receipts'")
            conn.execute("UPDATE schema_version SET version=75 WHERE name='library_practice_action_receipts'")
        self.assertEqual(library_receipt_inventory_proof(self.c.db, self.c.audit), [])
        self.c.db.execute("DELETE FROM schema_version WHERE name='library_authored_text_and_reference_adoptions'")
        self.assertEqual(library_receipt_inventory_proof(self.c.db, self.c.audit), [])
        self.c.db.execute("DELETE FROM schema_version WHERE name='owner_billing_sources_and_posting'")
        with self.assertRaises(LibraryReceiptError):
            library_receipt_inventory_proof(self.c.db, self.c.audit)


class LibraryActionTests(unittest.TestCase):
    def setUp(self):
        register_library_receipts_schema()
        self.c = make_library_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.domain = self.c.plugin("library")
        self.project = self.c.library_practice_records["project_id"]
        self.person, self.reviewer = (self.c.library_practice_persona_people[key]["person_id"] for key in ("author", "reviewer"))
        secret = b"library-actions-genuine-private-signing-key"
        self.contract = LibraryContract(self.c, secret=secret)
        self.preflight = LibraryPreflight(self.c, self.contract, secret=secret)
        self.runner = LibraryActionRunner(self.c, self.contract, self.preflight)

    def state(self):
        return tuple(self.c.db.conn.iterdump()), tuple(self.c.provider.submissions)

    def input(self, text="Practice-authored clause.\r\n  Preserve exact spaces — café 🏗.\n"):
        return {"kind": "contract_clause", "title": "Synthetic concrete reference", "text": text,
                "sourceLocator": "Practice editor / concrete / paragraph 1"}

    def prepared(self, person, action, resource, body=None):
        body = {} if body is None else body
        review = self.preflight.review(person, action, resource, body)
        self.assertTrue(review["allowed"], review)
        return (person, action, resource, {**body, "fingerprint": review["fingerprint"]}), {
            "repeatability_key": str(uuid4()), "if_match": review["resourceVersion"]}

    def act(self, person, action, resource, body=None):
        request = self.prepared(person, action, resource, body)
        return self.runner.run(*request[0], **request[1]), request

    def replay(self, original, request):
        before = self.state()
        replay = self.runner.run(*request[0], **request[1])
        self.assertEqual(replay, {**original, "replayed": True, "effectApplied": False})
        self.assertEqual(before, self.state())

    def entry(self):
        return self.act(self.person, "library.create", self.project, self.input())[0]["result"]

    def granted(self):
        entry = self.entry()
        planned, _ = self.act(self.person, "library.prepareReference", entry["revisionId"],
            {"targetLocator": "Project specifications / 03 30 00 / draft reference", "purpose": "Internal specification preparation"})
        requested, _ = self.act(self.person, "library.requestAdoption", planned["result"]["planId"])
        approval = requested["result"]["approvalId"]
        self.act(self.reviewer, "library.approveAdoption", approval)
        return entry, approval

    def test_all_six_actual_actions_replay_original_after_a_genuine_later_revision(self):
        created, create = self.act(self.person, "library.create", self.project, self.input())
        entry = created["result"]["entryId"]
        revised, revise = self.act(self.person, "library.revise", entry,
            {"previousRevisionId": created["result"]["revisionId"], "text": "Practice-authored revision two.\n",
             "sourceLocator": "Practice editor / concrete / paragraph 2", "changeReason": "Clarify internal inspection reference"})
        planned, plan = self.act(self.person, "library.prepareReference", revised["result"]["revisionId"],
            {"targetLocator": "Project specifications / 03 30 00 / draft reference", "purpose": "Internal specification preparation"})
        requested, request = self.act(self.person, "library.requestAdoption", planned["result"]["planId"])
        approval = requested["result"]["approvalId"]
        granted, grant = self.act(self.reviewer, "library.approveAdoption", approval)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM library_adoptions"), 0)
        applied, apply = self.act(self.person, "library.applyAdoption", approval)
        original = self.domain.original_reference_proof(applied["result"]["referenceId"])
        self.assertEqual(original["record"]["text"], "Practice-authored revision two.\n")
        self.domain.revise(entry, {"previousRevisionId": revised["result"]["revisionId"], "text": "Later separate authored revision three.\n",
            "sourceLocator": "Practice editor / concrete / paragraph 3", "changeReason": "Later internal revision"}, actor=PM_LOGIN)
        for outcome, args in ((created, create), (revised, revise), (planned, plan), (requested, request), (granted, grant), (applied, apply)):
            self.replay(outcome, args)
        self.assertEqual(original, self.domain.original_reference_proof(applied["result"]["referenceId"]))
        self.assertEqual(len(library_receipt_inventory_proof(self.c.db, self.c.audit)), 6)
        self.assertEqual({item["fixed_action"] for item in library_receipt_inventory_proof(self.c.db, self.c.audit)}, ACTIONS)
        self.assertEqual(self.c.ledger.journals(), [])
        self.assertEqual(self.c.provider.submissions, [])

    def test_same_uuid_concurrent_create_and_apply_each_have_one_original_effect(self):
        request = self.prepared(self.person, "library.create", self.project, self.input())
        gate = threading.Barrier(2)
        def run():
            gate.wait()
            return self.runner.run(*request[0], **request[1])
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(outcomes[0]["receiptId"], outcomes[1]["receiptId"])
        self.assertEqual(sum(o["effectApplied"] for o in outcomes), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM library_entries"), 1)
        _, approval = self.granted()
        request = self.prepared(self.person, "library.applyAdoption", approval)
        gate = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(outcomes[0]["receiptId"], outcomes[1]["receiptId"])
        self.assertEqual(sum(o["effectApplied"] for o in outcomes), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM library_adoptions"), 1)

    def test_caught_late_adoption_receipt_failure_restores_grant_copy_and_command(self):
        _, approval = self.granted()
        request = self.prepared(self.person, "library.applyAdoption", approval)
        record = self.c.audit.record
        def late(*args, **kwargs):
            result = record(*args, **kwargs)
            if args[1] == "library.practice_action_recorded":
                raise RuntimeError("Injected late library API receipt fault")
            return result
        with self.c.db.transaction():
            before = self.state()
            with patch.object(self.c.audit, "record", side_effect=late), self.assertRaises(APRefusal):
                self.runner.run(*request[0], **request[1])
            self.assertEqual(before, self.state())
            self.assertEqual(self.c.approvals.get(approval)["status"], "granted")
        completed = self.runner.run(*request[0], **request[1])
        self.replay(completed, request)

    def test_outer_commit_failure_rolls_back_authored_text_evidence_head_and_receipt(self):
        request = self.prepared(self.person, "library.create", self.project, self.input())
        execute = self.c.db.conn.execute
        def fail(sql, *args, **kwargs):
            if sql == "COMMIT":
                raise sqlite3.OperationalError("Injected library commit failure")
            return execute(sql, *args, **kwargs)
        before = self.state()
        with patch.object(self.c.db.conn, "execute", side_effect=fail), self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())
        completed = self.runner.run(*request[0], **request[1])
        self.replay(completed, request)

    def test_exact_result_types_unreviewed_schema_and_extra_genuine_source_all_roll_back(self):
        request = self.prepared(self.person, "library.create", self.project, self.input())
        apply = self.runner._apply
        for fault in ("float", "schema", "extra"):
            with self.subTest(fault=fault):
                def unexpected(*args):
                    result, source = apply(*args)
                    if fault == "float":
                        result["providerCallsDelta"] = 0.0
                    elif fault == "schema":
                        self.c.db.execute("CREATE TABLE unreviewed_library_side_effect (id TEXT)")
                    else:
                        self.domain.create(self.project, self.input("Unreviewed second genuine authored source"), actor=PM_LOGIN)
                    return result, source
                before = self.state()
                with patch.object(self.runner, "_apply", side_effect=unexpected), self.assertRaises(APRefusal):
                    self.runner.run(*request[0], **request[1])
                self.assertEqual(before, self.state())

    def test_actual_text_and_reference_purpose_cannot_override_reviewed_native_plan(self):
        request = self.prepared(self.person, "library.create", self.project, self.input())
        create = self.domain.create
        def different(project, body, **kwargs):
            return create(project, {**body, "text": "A different internally valid authored clause"}, **kwargs)
        before = self.state()
        with patch.object(self.domain, "create", side_effect=different), self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())
        entry = self.entry()
        request = self.prepared(self.person, "library.prepareReference", entry["revisionId"],
            {"targetLocator": "Project specifications / draft reference", "purpose": "Internal design reference"})
        prepare = self.domain.prepare_reference
        def wrong_purpose(revision, body, **kwargs):
            return prepare(revision, {**body, "purpose": "Unreviewed internally valid reference purpose"}, **kwargs)
        before = self.state()
        with patch.object(self.domain, "prepare_reference", side_effect=wrong_purpose), self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())

    def test_current_own_pm_duty_precedes_original_receipt_or_namespace_disclosure(self):
        completed, request = self.act(self.person, "library.create", self.project, self.input())
        self.c.plugin("people").end_membership(PM_LOGIN, self.project, reason="Synthetic project reassignment", actor=BOOTSTRAP_LOGIN)
        before = self.state()
        with patch.object(self.runner.receipts, "find", side_effect=AssertionError("receipt disclosure")), \
             patch("apps.cipher.library_actions.require_other_namespaces", side_effect=AssertionError("namespace disclosure")), \
             self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())

    def test_changed_body_and_cross_action_key_refuse_before_second_effect(self):
        completed, request = self.act(self.person, "library.create", self.project, self.input())
        args, kwargs = request
        changed = (*args[:3], {**args[3], "sourceLocator": "Different original typed locator"})
        before = self.state()
        with self.assertRaises(APRefusal) as refusal:
            self.runner.run(*changed, **kwargs)
        self.assertEqual(refusal.exception.status, 409)
        cross = self.prepared(self.person, "library.prepareReference", completed["result"]["revisionId"],
            {"targetLocator": "Project draft reference", "purpose": "Internal preparation"})
        with self.assertRaises(APRefusal) as refusal:
            self.runner.run(*cross[0], **{**cross[1], "repeatability_key": kwargs["repeatability_key"]})
        self.assertEqual(refusal.exception.status, 409)
        self.assertEqual(before, self.state())

    def test_original_apply_retry_refuses_tampered_command_payload(self):
        _, approval = self.granted()
        completed, request = self.act(self.person, "library.applyAdoption", approval)
        self.c.db.execute("UPDATE idempotency SET payload_hash=? WHERE op_id=?", ("0"*64, "exec:"+approval))
        before = self.state()
        with self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())
        self.assertFalse(self.runner.integrity_checks()["ok"])

    def test_current_receipt_named_schema_admission_cannot_be_removed_after_success(self):
        completed, request = self.act(self.person, "library.create", self.project, self.input())
        self.c.db.execute("DELETE FROM schema_version WHERE name='library_practice_action_receipts'")
        before = self.state()
        with self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())
        self.assertFalse(self.runner.integrity_checks()["ok"])

    def test_deleted_original_receipt_birth_refuses_recreation(self):
        completed, request = self.act(self.person, "library.create", self.project, self.input())
        guard = self.c.db.one("SELECT sql FROM sqlite_master WHERE name='library_action_receipts_no_delete'")["sql"]
        with self.c.db.transaction() as conn:
            conn.execute("DROP TRIGGER library_action_receipts_no_delete")
            conn.execute("DELETE FROM library_action_receipts WHERE id=?", (completed["receiptId"],))
            conn.execute(guard)
        before = self.state()
        with self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())
        self.assertFalse(self.runner.integrity_checks()["ok"])

    def test_response_assembly_failure_rolls_back_before_original_committed_retry(self):
        request = self.prepared(self.person, "library.create", self.project, self.input())
        before = self.state()
        with patch.object(self.runner, "_response", side_effect=RuntimeError("Injected response assembly fault")), self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())
        completed = self.runner.run(*request[0], **request[1])
        self.replay(completed, request)

    def test_only_original_clock_expiry_can_commit_terminal_control_and_refusal(self):
        from apps.cipher.domain import library
        original_builder = library.build_manifest
        def short_manifest(**kwargs):
            return original_builder(**{**kwargs, "expiry_seconds": 4})
        entry = self.entry()
        planned, _ = self.act(self.person, "library.prepareReference", entry["revisionId"],
            {"targetLocator": "Project draft reference", "purpose": "Internal project review"})
        with patch.object(library, "build_manifest", side_effect=short_manifest):
            requested, _ = self.act(self.person, "library.requestAdoption", planned["result"]["planId"])
            approval = requested["result"]["approvalId"]
            request = self.prepared(self.reviewer, "library.approveAdoption", approval)
            apply = self.runner._apply
            deadline = parse_iso(self.c.approvals.get(approval)["expires_at"])
            def expire(*args):
                time.sleep(max(0, (deadline-utcnow()).total_seconds()) + 0.05)
                return apply(*args)
            with patch.object(self.runner, "_apply", side_effect=expire), self.assertRaises(APRefusal) as refusal:
                self.runner.run(*request[0], **request[1])
        self.assertEqual(refusal.exception.status, 423)
        self.assertEqual(self.c.approvals.get(approval)["status"], "expired")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM library_adoptions"), 0)
        original = self.c.db.one("SELECT * FROM library_action_receipts WHERE id=?", (refusal.exception.receipt_id,))
        self.assertEqual(original["outcome"], "refused")
        self.domain.revise(entry["entryId"], {"previousRevisionId": entry["revisionId"], "text": "Later separate authored revision",
            "sourceLocator": "Practice editor / later source", "changeReason": "Separate revision after expired review"}, actor=PM_LOGIN)
        before = self.state()
        with self.assertRaises(APRefusal) as replay:
            self.runner.run(*request[0], **request[1])
        self.assertEqual(replay.exception.receipt_id, original["id"])
        self.assertTrue(replay.exception.replayed)
        self.assertEqual(before, self.state())

    def test_fabricated_typed_stale_error_cannot_commit_a_partial_authored_effect(self):
        from apps.cipher.core.approvals import StaleApprovalError
        request = self.prepared(self.person, "library.create", self.project, self.input())
        apply = self.runner._apply
        def partial(*args):
            apply(*args)
            raise StaleApprovalError("Injected fake stale signal after genuine source effects")
        before = self.state()
        with patch.object(self.runner, "_apply", side_effect=partial), self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())

    def test_existing_genuine_ap_receipt_key_cannot_be_reused_for_library_creation(self):
        from apps.cipher.ap_actions import APActionRunner
        from apps.cipher.ap_contract import APContract
        from apps.cipher.ap_preflight import APPreflight
        from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
        c = make_ap_practice_fixture()
        self.addCleanup(c.db.close)
        project = c.bills.get(c.ap_practice_records["draft_bill_id"])["project_id"]
        person = c.ap_practice_persona_people["accountant"]["person_id"]
        grant = c.plugin("people").request_grant("practice.accountant", "pm", project_id=project,
            reason="Synthetic same-person AP/library composition", actor="practice.bootstrap")
        ap = c.request_approval("people.grant_role", grant["id"], actor_role="owner", requested_by="practice.reviewer")
        c.approve(ap["id"], approver="practice.bootstrap", approver_role="owner")
        c.execute(ap["id"], actor="practice.bootstrap")
        secret = b"genuine-AP-library-shared-key-synthetic-private-key"
        ap_contract = APContract(c, secret=secret)
        ap_preflight = APPreflight(c, ap_contract, secret=secret)
        ap_runner = APActionRunner(c, ap_contract, ap_preflight)
        bill = c.ap_practice_records["draft_bill_id"]
        preview = ap_preflight.review(person, "bill.requestApproval", bill, {})
        self.assertTrue(preview["allowed"], preview)
        key = str(uuid4())
        ap_runner.run(person, "bill.requestApproval", bill, {"fingerprint": preview["fingerprint"]}, repeatability_key=key, if_match=preview["resourceVersion"])
        contract = LibraryContract(c, secret=secret)
        preflight = LibraryPreflight(c, contract, secret=secret)
        runner = LibraryActionRunner(c, contract, preflight)
        body = self.input()
        review = preflight.review(person, "library.create", project, body)
        self.assertTrue(review["allowed"], review)
        before = tuple(c.db.conn.iterdump())
        with self.assertRaises(APRefusal) as refused:
            runner.run(person, "library.create", project, {**body, "fingerprint": review["fingerprint"]}, repeatability_key=key, if_match=review["resourceVersion"])
        self.assertEqual(refused.exception.status, 409)
        self.assertEqual(before, tuple(c.db.conn.iterdump()))

    def test_request_cannot_expand_or_shorten_the_reviewed_native_policy_deadline(self):
        entry = self.entry()
        native_request = self.c.approvals.request
        for days in (365, -1):
            with self.subTest(days=days):
                planned, _ = self.act(self.person, "library.prepareReference", entry["revisionId"],
                    {"targetLocator": "Project draft reference", "purpose": "Internal project review"})
                request = self.prepared(self.person, "library.requestAdoption", planned["result"]["planId"])
                def changed(manifest, **kwargs):
                    deadline = parse_iso(manifest["expires_at"]) + datetime.timedelta(days=days)
                    return native_request({**manifest, "expires_at": deadline.isoformat().replace("+00:00", "Z")}, **kwargs)
                before = self.state()
                with patch.object(self.c.approvals, "request", side_effect=changed), self.assertRaises(APRefusal):
                    self.runner.run(*request[0], **request[1])
                self.assertEqual(before, self.state())

    def test_request_allows_genuine_second_boundary_in_native_deadline_generation(self):
        entry = self.entry()
        planned, _ = self.act(self.person, "library.prepareReference", entry["revisionId"],
            {"targetLocator": "Project draft reference", "purpose": "Internal project review"})
        request = self.prepared(self.person, "library.requestAdoption", planned["result"]["planId"])
        apply = self.runner._apply
        def next_second(*args):
            time.sleep(1 - utcnow().microsecond / 1_000_000 + 0.05)
            return apply(*args)
        with patch.object(self.runner, "_apply", side_effect=next_second):
            completed = self.runner.run(*request[0], **request[1])
        self.assertEqual(completed["result"]["status"], "pending")
        self.replay(completed, request)

    def test_request_receipt_cannot_change_original_person_or_reviewed_binding(self):
        entry = self.entry()
        record = self.runner.receipts.record
        for field in ("person", "version", "fingerprint"):
            with self.subTest(field=field):
                planned, _ = self.act(self.person, "library.prepareReference", entry["revisionId"],
                    {"targetLocator": "Project draft reference", "purpose": "Internal project review"})
                request = self.prepared(self.person, "library.requestAdoption", planned["result"]["planId"])
                def changed(**kwargs):
                    if field == "person":
                        kwargs["person_id"] = self.reviewer
                    else:
                        altered = json.loads(json.dumps(kwargs["binding"]))
                        if field == "version":
                            altered["originalIfMatch"] = "libv1:" + "0"*64
                        else:
                            altered["preflightFingerprint"] = "DifferentRecordedFingerprint"
                            altered["canonicalTypedBody"]["fingerprint"] = "DifferentRecordedFingerprint"
                        kwargs["binding"] = altered
                    return record(**kwargs)
                before = self.state()
                with patch.object(self.runner.receipts, "record", side_effect=changed), self.assertRaises(APRefusal):
                    self.runner.run(*request[0], **request[1])
                self.assertEqual(before, self.state())

