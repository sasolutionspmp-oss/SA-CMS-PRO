"""Atomic AP actions, immutable source proof, and concurrent exact retries."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import sqlite3
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.ap_actions import APActionRunner
from apps.cipher.ap_contract import APContract, APRefusal
from apps.cipher.ap_preflight import APPreflight
from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
from apps.cipher.core.api_receipts import APIActionReceipts
from apps.cipher.core.approvals import StaleApprovalError
from apps.cipher.core.ids import canonical_json, hash_json, parse_iso


class APActionsTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        secret = b"AP-action-test-key-with-at-least-32-bytes"
        self.contract = APContract(self.c, secret=secret)
        self.preflight = APPreflight(self.c, self.contract, secret=secret)
        self.runner = APActionRunner(self.c, self.contract, self.preflight)
        self.accountant = self.c.ap_practice_persona_people["accountant"]["person_id"]
        self.pm = self.c.ap_practice_persona_people["pm"]["person_id"]
        self.bill_id = self.c.ap_practice_records["draft_bill_id"]
        self.approved_bill_id = self.c.ap_practice_records["approved_bill_id"]

    def snapshot(self):
        return tuple(self.c.db.conn.iterdump())

    def reviewed(self, person, action, resource, body=None):
        body = body or {}
        review = self.preflight.review(person, action, resource, body)
        self.assertTrue(review["allowed"], review)
        return {"person_id": person, "action": action, "resource_id": resource,
                "body": dict(body, fingerprint=review["fingerprint"]), "repeatability_key": str(uuid4()),
                "if_match": review["resourceVersion"]}

    def request(self):
        args = self.reviewed(self.accountant, "bill.requestApproval", self.bill_id)
        return self.runner.run(**args), args

    def post_args(self):
        return self.reviewed(self.accountant, "bill.post", self.approved_bill_id,
                             {"periodId": "2026-10", "reason": ""})

    def grant_args(self):
        request, _ = self.request()
        return self.reviewed(self.pm, "bill.approve", request["result"]["approvalId"])

    def assert_rolls_back(self, args, owner, attribute, side_effect):
        before = self.snapshot()
        with patch.object(owner, attribute, side_effect=side_effect):
            with self.assertRaises(APRefusal) as failure:
                self.runner.run(**args)
        self.assertEqual(failure.exception.status, 500)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.c.db.conn.in_transaction)

    def test_two_people_request_business_grant_then_independent_post(self):
        request, request_args = self.request()
        approval_id = request["result"]["approvalId"]
        grants = self.reviewed(self.pm, "bill.approve", approval_id)
        journals = self.c.db.one("SELECT COUNT(*) AS n FROM journals")["n"]
        approved = self.runner.run(**grants)
        self.assertEqual(approved["result"]["journalDelta"], 0)
        self.assertEqual(approved["result"]["apDeltaCents"], 0)
        self.assertEqual(self.c.db.one("SELECT COUNT(*) AS n FROM journals")["n"], journals)
        self.assertEqual(str(self.c.bills.open_payable(self.bill_id)), "0.00")
        posting = self.reviewed(self.accountant, "bill.post", self.bill_id, {"periodId": "2026-10", "reason": ""})
        posted = self.runner.run(**posting)
        self.assertEqual(posted["result"]["status"], "posted")
        self.assertEqual(posted["result"]["amountDueCents"], 1111110)
        self.assertEqual(self.c.approvals.get(approval_id)["status"], "consumed")
        self.assertEqual(len(self.c.provider.submissions), 0)
        before = self.snapshot()
        for first, args in ((request, request_args), (approved, grants), (posted, posting)):
            replay = self.runner.run(**args)
            self.assertEqual(replay["receiptId"], first["receiptId"])
            self.assertEqual(replay["result"], first["result"])
            self.assertTrue(replay["replayed"])
            self.assertFalse(replay["effectApplied"])
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(r["ok"] for r in self.runner.integrity_checks()))

    def test_retry_precedes_current_expiry_and_version_checks(self):
        result, args = self.request()
        approval_id = result["result"]["approvalId"]
        future = parse_iso(self.c.approvals.get(approval_id)["expires_at"]) + dt.timedelta(seconds=1)
        with patch("apps.cipher.core.approvals.utcnow", return_value=future):
            self.c.approvals.mark_expired(approval_id)
        before = self.snapshot()
        self.assertEqual(self.runner.run(**args)["result"], result["result"])
        self.assertEqual(self.snapshot(), before)

    def test_new_key_cannot_duplicate_current_business_request(self):
        _, args = self.request()
        before = self.snapshot()
        args["repeatability_key"] = str(uuid4())
        with self.assertRaises(APRefusal) as failure:
            self.runner.run(**args)
        self.assertEqual(failure.exception.status, 409)
        self.assertIn(failure.exception.code, ("duplicate_request", "duplicate_open_approval"))
        self.assertEqual(self.snapshot(), before)

    def test_reusing_key_with_different_fingerprint_is_conflict(self):
        _, args = self.request()
        before = self.snapshot()
        args["body"] = {"fingerprint": "changed"}
        with self.assertRaises(APRefusal) as failure:
            self.runner.run(**args)
        self.assertEqual(failure.exception.code, "repeatability_conflict")
        self.assertEqual(self.snapshot(), before)

    def test_reusing_key_with_different_original_version_is_conflict(self):
        _, args = self.request()
        before = self.snapshot()
        args["if_match"] = "changed"
        with self.assertRaises(APRefusal) as failure:
            self.runner.run(**args)
        self.assertEqual(failure.exception.code, "repeatability_conflict")
        self.assertEqual(self.snapshot(), before)

    def test_key_namespace_belongs_to_canonical_person(self):
        request, args = self.request()
        grant = self.reviewed(self.pm, "bill.approve", request["result"]["approvalId"])
        grant["repeatability_key"] = args["repeatability_key"]
        approved = self.runner.run(**grant)
        self.assertNotEqual(request["receiptId"], approved["receiptId"])
        self.assertEqual(self.c.db.one("SELECT COUNT(*) AS n FROM ap_action_receipts")["n"], 2)

    def test_unauthorized_retry_reveals_no_other_person_receipt(self):
        _, args = self.request()
        before = self.snapshot()
        args["person_id"] = self.pm
        with self.assertRaises(APRefusal) as failure:
            self.runner.run(**args)
        self.assertEqual(failure.exception.status, 403)
        self.assertFalse(hasattr(failure.exception, "receipt_id"))
        self.assertEqual(self.snapshot(), before)

    def test_hidden_scope_refusal_precedes_receipt_lookup(self):
        args = self.post_args()
        args["resource_id"] = self.c.ap_practice_records["hidden_bill_id"]
        before = self.snapshot()
        with patch.object(self.runner.receipts, "find", side_effect=AssertionError("must not look up receipt")):
            with self.assertRaises(APRefusal) as failure:
                self.runner.run(**args)
        self.assertEqual(failure.exception.status, 404)
        self.assertEqual(self.snapshot(), before)

    def test_arbitrary_role_actor_and_provider_fields_are_refused(self):
        args = self.post_args()
        before = self.snapshot()
        for field, value in (("actor", "practice.pm"), ("actorRole", "owner"), ("provider", "live")):
            invalid = dict(args, body=dict(args["body"], **{field: value}))
            with self.assertRaises(APRefusal) as failure:
                self.runner.run(**invalid)
            self.assertEqual(failure.exception.status, 422)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_key_or_missing_version_makes_no_receipt(self):
        args = self.post_args()
        before = self.snapshot()
        for change in ({"repeatability_key": "not-a-uuid"}, {"if_match": ""}):
            with self.assertRaises(APRefusal) as failure:
                self.runner.run(**dict(args, **change))
            self.assertEqual(failure.exception.status, 422)
        self.assertEqual(self.snapshot(), before)

    def test_bad_preflight_is_zero_write(self):
        args = self.post_args()
        args["body"]["fingerprint"] = "changed"
        before = self.snapshot()
        with self.assertRaises(APRefusal) as failure:
            self.runner.run(**args)
        self.assertEqual(failure.exception.status, 412)
        self.assertEqual(self.snapshot(), before)

    def test_request_audit_failure_rolls_back_insert(self):
        args = self.reviewed(self.accountant, "bill.requestApproval", self.bill_id)
        original = self.c.audit.record
        def fail(*values, **kwargs):
            if values[1] == "approval.requested":
                raise RuntimeError("request audit fault")
            return original(*values, **kwargs)
        self.assert_rolls_back(args, self.c.audit, "record", fail)

    def test_api_receipt_failure_rolls_back_request_and_receipt(self):
        args = self.reviewed(self.accountant, "bill.requestApproval", self.bill_id)
        original = self.runner.receipts.record
        def fail(**kwargs):
            original(**kwargs)
            raise RuntimeError("API receipt fault")
        self.assert_rolls_back(args, self.runner.receipts, "record", fail)

    def test_api_receipt_audit_failure_rolls_back_business_grant(self):
        args = self.grant_args()
        original = self.c.audit.record
        def fail(*values, **kwargs):
            if values[1] == "ap.practice_action_recorded":
                raise RuntimeError("API audit fault")
            return original(*values, **kwargs)
        self.assert_rolls_back(args, self.c.audit, "record", fail)

    def test_business_grant_record_failure_rolls_back_grant_and_hooks(self):
        args = self.grant_args()
        original = self.c.bills.record_business_approval
        def fail(*values, **kwargs):
            original(*values, **kwargs)
            raise RuntimeError("grant record fault")
        self.assert_rolls_back(args, self.c.bills, "record_business_approval", fail)

    def test_journal_failure_rolls_back_consumption_and_journal(self):
        args = self.post_args()
        original = self.c.ledger.post
        def fail(*values, **kwargs):
            original(*values, **kwargs)
            raise RuntimeError("journal fault")
        self.assert_rolls_back(args, self.c.ledger, "post", fail)

    def test_posting_receipt_audit_failure_rolls_back_journal(self):
        args = self.post_args()
        original = self.c.audit.record
        def fail(*values, **kwargs):
            if values[1] == "bill.posting_receipt_recorded":
                raise RuntimeError("posting receipt fault")
            return original(*values, **kwargs)
        self.assert_rolls_back(args, self.c.audit, "record", fail)

    def test_command_completion_failure_rolls_back_post_and_command(self):
        args = self.post_args()
        original = self.c.commands.run
        def fail(*values, **kwargs):
            original(*values, **kwargs)
            raise RuntimeError("command fault")
        self.assert_rolls_back(args, self.c.commands, "run", fail)

    def test_api_receipt_failure_rolls_back_complete_post(self):
        args = self.post_args()
        original = self.runner.receipts.record
        def fail(**kwargs):
            original(**kwargs)
            raise RuntimeError("receipt fault")
        self.assert_rolls_back(args, self.runner.receipts, "record", fail)

    def test_actual_commit_failure_rolls_back_effect_and_receipt(self):
        args = self.post_args()
        self.c.db.execute("CREATE TABLE ap_commit_fault(value TEXT REFERENCES people_persons(id) DEFERRABLE INITIALLY DEFERRED)")
        original = self.runner.receipts.record
        def fail(**kwargs):
            receipt = original(**kwargs)
            self.c.db.execute("INSERT INTO ap_commit_fault(value) VALUES('missing-person')")
            return receipt
        self.assert_rolls_back(args, self.runner.receipts, "record", fail)

    def test_nested_caught_failure_restores_whole_action(self):
        args = self.post_args()
        original = self.runner.receipts.record
        def fail(**kwargs):
            original(**kwargs)
            raise RuntimeError("late nested fault")
        with self.c.db.transaction():
            before = self.snapshot()
            with patch.object(self.runner.receipts, "record", side_effect=fail):
                with self.assertRaises(APRefusal):
                    self.runner.run(**args)
            self.assertEqual(self.snapshot(), before)

    def test_expected_stale_grant_commits_only_invalidation_and_refused_receipt(self):
        args = self.grant_args()
        original = self.c.approve
        def fail(*values, **kwargs):
            with patch.object(self.c.plugin("people"), "check_bill_grant", side_effect=StaleApprovalError("policy changed")):
                return original(*values, **kwargs)
        before = self.c.db.query("SELECT * FROM journals")
        with patch.object(self.c, "approve", side_effect=fail):
            with self.assertRaises(APRefusal) as failure:
                self.runner.run(**args)
        self.assertEqual(failure.exception.code, "approval_stale")
        self.assertTrue(hasattr(failure.exception, "receipt_id"))
        self.assertEqual(self.c.approvals.get(args["resource_id"])["status"], "invalidated")
        self.assertEqual(self.c.db.query("SELECT * FROM journals"), before)
        self.assertEqual(self.c.db.one("SELECT COUNT(*) AS n FROM ap_action_receipts WHERE outcome='refused'")["n"], 1)
        before = self.snapshot()
        with self.assertRaises(APRefusal) as retry:
            self.runner.run(**args)
        self.assertTrue(retry.exception.replayed)
        self.assertEqual(retry.exception.receipt_id, failure.exception.receipt_id)
        self.assertEqual(self.snapshot(), before)

    def test_expected_expiry_grant_commits_only_expiry_and_refused_receipt(self):
        args = self.grant_args()
        original = self.c.approve
        future = parse_iso(self.c.approvals.get(args["resource_id"])["expires_at"]) + dt.timedelta(seconds=1)
        def fail(*values, **kwargs):
            with patch("apps.cipher.core.approvals.utcnow", return_value=future):
                return original(*values, **kwargs)
        with patch.object(self.c, "approve", side_effect=fail):
            with self.assertRaises(APRefusal) as failure:
                self.runner.run(**args)
        self.assertEqual(failure.exception.code, "approval_expired")
        self.assertEqual(self.c.approvals.get(args["resource_id"])["status"], "expired")
        self.assertEqual(self.c.db.one("SELECT COUNT(*) AS n FROM ap_action_receipts WHERE outcome='refused'")["n"], 1)

    def test_expected_post_expiry_restores_journal_then_commits_terminal_control(self):
        args = self.post_args()
        approval_id = self.c.bills.get(self.approved_bill_id)["business_approval_id"]
        future = parse_iso(self.c.approvals.get(approval_id)["expires_at"]) + dt.timedelta(seconds=1)
        original = self.c.post_bill
        def fail(*values, **kwargs):
            with patch("apps.cipher.core.approvals.utcnow", return_value=future):
                return original(*values, **kwargs)
        before = self.c.db.query("SELECT * FROM journals")
        with patch.object(self.c, "post_bill", side_effect=fail):
            with self.assertRaises(APRefusal) as failure:
                self.runner.run(**args)
        self.assertEqual(failure.exception.code, "approval_expired")
        self.assertEqual(self.c.approvals.get(approval_id)["status"], "expired")
        self.assertEqual(self.c.db.query("SELECT * FROM journals"), before)
        self.assertEqual(self.c.bills.get(self.approved_bill_id)["status"], "approved")

    def test_refused_receipt_failure_rolls_back_terminal_control(self):
        args = self.grant_args()
        original = self.c.approve
        def fail(*values, **kwargs):
            with patch.object(self.c.plugin("people"), "check_bill_grant", side_effect=StaleApprovalError("changed")):
                return original(*values, **kwargs)
        before = self.snapshot()
        with patch.object(self.c, "approve", side_effect=fail), patch.object(self.runner.receipts, "record", side_effect=RuntimeError("receipt fault")):
            with self.assertRaises(APRefusal) as failure:
                self.runner.run(**args)
        self.assertEqual(failure.exception.status, 500)
        self.assertEqual(self.snapshot(), before)

    def test_typed_refusal_cannot_commit_unverified_partial_effects(self):
        args = self.grant_args()
        def fail(*values, **kwargs):
            self.c.approvals.invalidate(args["resource_id"], reason="changed", actor="practice.pm")
            self.c.db.execute("UPDATE parties SET name='unexpected effect' WHERE id=(SELECT supplier_id FROM commitments WHERE id=(SELECT commitment_id FROM bills WHERE id=?))", (self.bill_id,))
            raise StaleApprovalError("unexpected partial writes")
        self.assert_rolls_back(args, self.c, "approve", fail)

    def test_concurrent_same_person_key_has_one_request_and_receipt(self):
        args = self.reviewed(self.accountant, "bill.requestApproval", self.bill_id)
        barrier = threading.Barrier(8)
        def send():
            barrier.wait(timeout=5)
            return self.runner.run(**args)
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: send(), range(8)))
        self.assertEqual(len({r["receiptId"] for r in results}), 1)
        self.assertEqual(sum(not r["replayed"] for r in results), 1)
        self.assertEqual(self.c.db.one("SELECT COUNT(*) AS n FROM approvals WHERE subject_id=?", (self.bill_id,))["n"], 1)

    def test_concurrent_different_keys_do_not_duplicate_current_request(self):
        args = self.reviewed(self.accountant, "bill.requestApproval", self.bill_id)
        barrier = threading.Barrier(6)
        def send():
            barrier.wait(timeout=5)
            try:
                return self.runner.run(**dict(args, repeatability_key=str(uuid4())))
            except APRefusal as exc:
                return exc.status
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda _: send(), range(6)))
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertEqual(results.count(409), 5)
        self.assertEqual(self.c.db.one("SELECT COUNT(*) AS n FROM ap_action_receipts")["n"], 1)

    def test_concurrent_post_exact_retries_create_one_journal(self):
        args = self.post_args()
        before = self.c.db.one("SELECT COUNT(*) AS n FROM journals")["n"]
        barrier = threading.Barrier(6)
        def send():
            barrier.wait(timeout=5)
            return self.runner.run(**args)
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda _: send(), range(6)))
        self.assertEqual(sum(not r["replayed"] for r in results), 1)
        self.assertEqual(self.c.db.one("SELECT COUNT(*) AS n FROM journals")["n"], before + 1)

    def test_concurrent_same_key_different_valid_post_reviews_conflict(self):
        first = self.post_args()
        second = self.reviewed(self.accountant, "bill.post", self.approved_bill_id,
                               {"periodId": "2026-11", "reason": "Late reviewed invoice"})
        second["repeatability_key"] = first["repeatability_key"]
        barrier = threading.Barrier(2)
        def send(args):
            barrier.wait(timeout=5)
            try:
                return self.runner.run(**args)
            except APRefusal as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(send, (first, second)))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertIn("repeatability_conflict", results)
        self.assertEqual(self.c.db.one("SELECT COUNT(*) AS n FROM ap_action_receipts")["n"], 1)

    def test_concurrent_different_keys_cannot_grant_twice(self):
        args = self.grant_args()
        barrier = threading.Barrier(4)
        def send():
            barrier.wait(timeout=5)
            try:
                return self.runner.run(**dict(args, repeatability_key=str(uuid4())))
            except APRefusal as exc:
                return exc.status
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: send(), range(4)))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(results.count(409), 3)
        self.assertEqual(self.c.db.one("SELECT COUNT(*) AS n FROM bill_business_approvals WHERE approval_id=?", (args["resource_id"],))["n"], 1)

    def test_receipt_trigger_refuses_update_delete_and_replace(self):
        result, _ = self.request()
        before = self.snapshot()
        for sql in ("UPDATE ap_action_receipts SET result_json='{}' WHERE id=?",
                    "DELETE FROM ap_action_receipts WHERE id=?",
                    "INSERT OR REPLACE INTO ap_action_receipts SELECT * FROM ap_action_receipts WHERE id=?"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.c.db.execute(sql, (result["receiptId"],))
        self.assertEqual(self.snapshot(), before)

    def test_rewritten_row_hash_cannot_replace_original_receipt_audit(self):
        result, args = self.request()
        self.c.db.execute("DROP TRIGGER ap_action_receipts_no_update")
        row = self.c.db.one("SELECT * FROM ap_action_receipts WHERE id=?", (result["receiptId"],))
        row["result_json"] = canonical_json({"approvalId": "forged", "billId": self.bill_id, "status": "pending"})
        row["receipt_hash"] = hash_json({k: v for k, v in row.items() if k != "receipt_hash"})
        self.c.db.execute("UPDATE ap_action_receipts SET result_json=?,receipt_hash=? WHERE id=?", (row["result_json"], row["receipt_hash"], row["id"]))
        self.assertFalse(self.runner.integrity_checks()[0]["ok"])
        with self.assertRaises(APRefusal) as failure:
            self.runner.run(**args)
        self.assertEqual(failure.exception.status, 500)

    def test_deleted_receipt_cannot_repeat_the_action(self):
        result, args = self.request()
        self.c.db.execute("DROP TRIGGER ap_action_receipts_no_delete")
        self.c.db.execute("DELETE FROM ap_action_receipts WHERE id=?", (result["receiptId"],))
        before = self.snapshot()
        with self.assertRaises(APRefusal) as failure:
            self.runner.run(**args)
        self.assertEqual(failure.exception.status, 500)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.runner.close_checks("2026-10")[0]["ok"])

    def test_grant_source_record_tamper_is_found_even_with_intact_api_receipt(self):
        args = self.grant_args()
        result = self.runner.run(**args)
        self.c.db.execute("DROP TRIGGER bill_business_approvals_no_update")
        self.c.db.execute("UPDATE bill_business_approvals SET approved_by='forged' WHERE id=?", (result["result"]["businessApprovalRecordId"],))
        self.assertTrue(self.runner.receipts.integrity_checks()[0]["ok"])
        self.assertFalse(self.runner.integrity_checks()[-1]["ok"])

        with self.assertRaises(APRefusal):
            self.runner.run(**args)

    def test_post_source_tamper_is_found_even_with_intact_api_receipt(self):
        args = self.post_args()
        result = self.runner.run(**args)
        self.c.db.execute("DROP TRIGGER bill_posting_receipts_no_update")
        self.c.db.execute("UPDATE bill_posting_receipts SET posted_by='forged' WHERE id=?", (result["result"]["postingReceiptId"],))
        self.assertFalse(self.runner.integrity_checks()[-1]["ok"])
        with self.assertRaises(APRefusal):
            self.runner.run(**args)

    def test_audited_receipt_cannot_attribute_another_persons_source(self):
        result, _ = self.request()
        original = self.c.db.one("SELECT * FROM ap_action_receipts WHERE id=?", (result["receiptId"],))
        from apps.cipher.core.ids import loads
        with self.c.db.transaction():
            self.runner.receipts.record(person_id=self.pm, actor_login=original["actor_login"], repeatability_uuid=str(uuid4()),
                                        contract_version=original["contract_version"], action=original["fixed_action"],
                                        resource_id=original["resource_id"], binding=loads(original["binding_json"]),
                                        outcome=original["outcome"], http_status=original["http_status"],
                                        result=loads(original["result_json"]), source=loads(original["source_json"]))
        self.assertFalse(self.runner.integrity_checks()[-1]["ok"])


class APLegacyReceiptDiagnosticsTests(unittest.TestCase):
    def test_pending_legacy_copy_exports_empty_receipts_without_admission(self):
        from apps.cipher.core.db import WorkspaceModeError
        from apps.cipher.domain.ledger import CHART
        from apps.cipher.service import Cipher
        from apps.cipher.tests.test_workspace_mode import legacy_file
        with tempfile.TemporaryDirectory(prefix="cipher-ap-receipt-legacy-") as directory:
            source = Path(directory) / "historical.sqlite"
            copied = Path(directory) / "copied.sqlite"
            legacy_file(source)
            with sqlite3.connect(source) as original:
                original.executemany("INSERT INTO accounts(code,name,type,control_kind) VALUES(?,?,?,?)", CHART)
            with sqlite3.connect(source) as original, sqlite3.connect(copied) as target:
                original.backup(target)
            c = Cipher(str(copied))
            self.addCleanup(c.db.close)
            self.assertEqual(c.db.mode_status()["state"], "pending_practice_declaration")
            before = tuple(c.db.conn.iterdump())
            receipts = APIActionReceipts(c.db, c.audit)
            self.assertTrue(receipts.integrity_checks()[0]["ok"])
            export = c.audit_export()
            self.assertEqual(export["ap_action_receipts"]["records"], [])
            self.assertTrue(export["ap_action_receipts"]["integrity"][0]["ok"])
            generic = c.plugin("core_reconciliation").close_checks("unused-diagnostic-period")
            self.assertTrue(next(r["ok"] for r in generic if r["check"] == "AP action receipts intact"))
            with c.db.transaction():
                with self.assertRaises(WorkspaceModeError):
                    receipts.record(person_id="not-a-person", actor_login="not-an-actor", repeatability_uuid=str(uuid4()),
                                    contract_version="cipher.ap-practice.v1", action="bill.requestApproval", resource_id="missing",
                                    binding={}, outcome="success", http_status=200, result={}, source={})
            secret = b"legacy-copy-diagnostic-test-key-with-32-bytes"
            contract = APContract(c, secret=secret)
            preflight = APPreflight(c, contract, secret=secret)
            with self.assertRaises(APRefusal):
                preflight.review("not-a-person", "bill.requestApproval", "missing", {})
            self.assertEqual(tuple(c.db.conn.iterdump()), before)
            self.assertEqual(c.provider.submissions, [])
            self.assertEqual(c.provider.transfers, {})

if __name__ == "__main__":
    unittest.main()
