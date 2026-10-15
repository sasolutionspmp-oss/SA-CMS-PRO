"""Atomic scoped intake, original proof, and concurrent exact action retries."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import datetime as dt
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.ap_actions import APActionRunner
from apps.cipher.ap_contract import APContract, APRefusal
from apps.cipher.ap_intake_actions import APIntakeActionRunner
from apps.cipher.ap_intake_contract import APIntakeContract
from apps.cipher.ap_intake_preflight import APIntakePreflight
from apps.cipher.ap_preflight import APPreflight
from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
from apps.cipher.core.api_receipts import APIReceiptIntegrityError
from apps.cipher.core.approvals import ApprovalExpired, StaleApprovalError
from apps.cipher.core.ids import loads, parse_iso


class APIntakeActionsTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        secret = b"intake-action-tests-server-key-at-least-32-bytes"
        self.base = APContract(self.c, secret=secret)
        self.contract = APIntakeContract(self.c, self.base, secret=secret)
        self.preflight = APIntakePreflight(self.c, self.contract, secret=secret)
        self.runner = APIntakeActionRunner(self.c, self.contract, self.preflight)
        self.old_runner = APActionRunner(self.c, self.base, APPreflight(self.c, self.base, secret=secret))
        self.ap = self.c.plugin("ap_intake")
        personas = self.c.ap_practice_persona_people
        self.accountant, self.reviewer, self.pm = [personas[person]["person_id"] for person in ("accountant", "reviewer", "pm")]
        self.login, self.reviewer_login = personas["accountant"]["login"], personas["reviewer"]["login"]
        self.commitment_id = self.c.ap_practice_records["prep_commitment_id"]
        self.commitment = self.c.commitments.get(self.commitment_id)
        self.evidence = self.c.ap_practice_records["visible_invoice_evidence_revision_ids"][0]

    def snapshot(self):
        return tuple(self.c.db.conn.iterdump())

    def reviewed(self, action, resource, body=None, person=None):
        person = person or self.accountant
        body = body or {}
        review = self.preflight.review(person, action, resource, body)
        self.assertTrue(review["allowed"], review)
        return {"person_id": person, "action": action, "resource_id": resource,
                "body": dict(body, fingerprint=review["fingerprint"]), "repeatability_key": str(uuid4()),
                "if_match": review["resourceVersion"]}

    def prepare_args(self):
        return self.reviewed("bill.prepare", self.commitment_id, {"periodId": "2026-10", "installed": [
            {"sovLineId": self.commitment["sov"][0]["id"], "cumulativeInstalledCents": 1234567},
            {"sovLineId": self.commitment["sov"][1]["id"], "cumulativeInstalledCents": 2345678}]})

    def prepare(self):
        args = self.prepare_args()
        return self.runner.run(**args), args

    def receive_args(self, *, amount=3222220, number="SYNTHETIC-1001", evidence=None):
        return self.reviewed("invoice.receive", self.commitment_id, {"invoiceNumber": number, "invoiceDate": "2026-10-14",
            "amountCents": amount, "evidenceRevisionId": evidence or self.evidence})

    def receive(self, **kwargs):
        args = self.receive_args(**kwargs)
        return self.runner.run(**args), args

    def computed(self):
        self.prepare()
        received, _ = self.receive()
        invoice_id = received["result"]["invoiceId"]
        args = self.reviewed("invoice.computeMatch", invoice_id)
        return self.runner.run(**args), args

    def requested(self):
        computed, _ = self.computed()
        args = self.reviewed("invoice.requestMatchApproval", computed["result"]["invoiceId"])
        return self.runner.run(**args), args

    def grant_args(self):
        requested, _ = self.requested()
        return self.reviewed("invoice.approveMatch", requested["result"]["approvalId"], person=self.reviewer)

    def execute_args(self):
        args = self.grant_args()
        granted = self.runner.run(**args)
        return self.reviewed("invoice.executeMatch", granted["result"]["approvalId"])

    def assert_refusal_no_write(self, args, status):
        before = self.snapshot()
        with self.assertRaises(APRefusal) as failure:
            self.runner.run(**args)
        self.assertEqual(failure.exception.status, status)
        self.assertEqual(self.snapshot(), before)
        return failure.exception

    def assert_failure_atomic(self, args, owner, method, side_effect):
        before = self.snapshot()
        with patch.object(owner, method, side_effect=side_effect):
            failure = self.assert_refusal_no_write(args, 500)
        self.assertEqual(failure.code, "action_unavailable")
        self.assertFalse(self.c.db.conn.in_transaction)

    def test_complete_six_action_flow_then_original_accountant_bill_pipeline(self):
        calls = []
        def run(args):
            result = self.runner.run(**args)
            calls.append((result, args))
            self.assertEqual(result["result"]["journalDelta"], 0)
            self.assertEqual(result["result"]["apDeltaCents"], 0)
            return result["result"]
        before_journals = self.c.db.scalar("SELECT COUNT(*) FROM journals")
        bill = run(self.prepare_args())
        invoice = run(self.receive_args())
        computation = run(self.reviewed("invoice.computeMatch", invoice["invoiceId"]))
        self.assertEqual(computation["status"], "matched")
        self.assertEqual(computation["matchedAmountCents"], bill["amountDueCents"])
        requested = run(self.reviewed("invoice.requestMatchApproval", invoice["invoiceId"]))
        run(self.reviewed("invoice.approveMatch", requested["approvalId"], person=self.reviewer))
        linked = run(self.reviewed("invoice.executeMatch", requested["approvalId"]))
        self.assertEqual(linked["billId"], bill["billId"])
        self.assertEqual(self.c.approvals.get(requested["approvalId"])["consumed_by"], self.login)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), before_journals)
        self.assertEqual(str(self.c.bills.open_payable(bill["billId"])), "0.00")
        # The existing independent PM business grant and accountant post follow
        # the new invoice attachment; a match does not shortcut those controls.
        business = self.c.request_approval("bill.approve", bill["billId"], actor_role="accountant", requested_by=self.login)
        self.c.approve(business["id"], approver=self.c.ap_practice_persona_people["pm"]["login"], approver_role="pm")
        self.c.post_bill(bill["billId"], actor=self.login, actor_role="accountant", period_id="2026-10")
        before = self.snapshot()
        for first, args in calls:
            replay = self.runner.run(**args)
            self.assertEqual(replay["result"], first["result"])
            self.assertEqual(replay["receiptId"], first["receiptId"])
            self.assertTrue(replay["replayed"])
            self.assertFalse(replay["effectApplied"])
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(check["ok"] for check in self.runner.integrity_checks()))
        self.assertTrue(all(check["ok"] for check in self.old_runner.integrity_checks()))
        self.assertEqual(self.old_runner.audit_export()["records"], [])
        self.assertEqual(len(self.runner.audit_export()["records"]), 6)
        self.assertEqual(self.c.provider.submissions, [])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM outbox"), 0)

    def test_prepare_original_retry_survives_draft_void(self):
        first, args = self.prepare()
        self.c.bills.void(first["result"]["billId"], actor=self.login, reason="Synthetic canceled application")
        before = self.snapshot()
        replay = self.runner.run(**args)
        self.assertEqual(replay["result"], first["result"])
        self.assertEqual(replay["result"]["status"], "draft")
        self.assertEqual(self.snapshot(), before)

    def test_received_original_retry_survives_legitimate_amount_revision(self):
        first, args = self.receive()
        invoice_id = first["result"]["invoiceId"]
        self.ap.revise_invoice(invoice_id, self.login, reason="Synthetic revised supplier invoice", amount="999.01")
        before = self.snapshot()
        self.assertEqual(self.runner.run(**args)["result"], first["result"])
        self.assertEqual(self.snapshot(), before)

    def test_received_original_retry_survives_evidence_replacement(self):
        first, args = self.receive()
        invoice = self.ap.invoice(first["result"]["invoiceId"])
        revision = self.c.evidence.add_revision(document_id=invoice["evidence_document_id"], content="Synthetic revised invoice", actor=self.login)
        self.ap.revise_invoice(invoice["id"], self.login, reason="Synthetic PDF replacement", evidence_hash=revision["content_hash"])
        before = self.snapshot()
        self.assertEqual(self.runner.run(**args)["result"], first["result"])
        self.assertEqual(self.snapshot(), before)

    def test_computation_retry_survives_new_computation_and_invoice_revision(self):
        first, args = self.computed()
        invoice_id = first["result"]["invoiceId"]
        self.ap.match(invoice_id, self.login)
        self.ap.revise_invoice(invoice_id, self.login, reason="Synthetic revised amount", amount="100.01")
        before = self.snapshot()
        self.assertEqual(self.runner.run(**args)["result"], first["result"])
        self.assertEqual(self.snapshot(), before)

    def test_request_retry_survives_expiry_without_new_request(self):
        first, args = self.requested()
        approval_id = first["result"]["approvalId"]
        future = parse_iso(self.c.approvals.get(approval_id)["expires_at"]) + dt.timedelta(seconds=1)
        self.c.approvals.mark_expired(approval_id, now=future)
        before = self.snapshot()
        self.assertEqual(self.runner.run(**args)["result"], first["result"])
        self.assertEqual(self.snapshot(), before)

    def test_grant_original_retry_survives_invoice_revision_and_invalidation(self):
        args = self.grant_args()
        first = self.runner.run(**args)
        self.ap.revise_invoice(first["result"]["invoiceId"], self.login, reason="Synthetic supplier replacement", amount="500.00")
        before = self.snapshot()
        self.assertEqual(self.runner.run(**args)["result"], first["result"])
        self.assertEqual(self.snapshot(), before)

    def test_execution_original_retry_survives_invoice_revision(self):
        args = self.execute_args()
        first = self.runner.run(**args)
        self.ap.revise_invoice(first["result"]["invoiceId"], self.login, reason="Synthetic supplier replacement", amount="700.00")
        before = self.snapshot()
        self.assertEqual(self.runner.run(**args)["result"], first["result"])
        self.assertEqual(self.snapshot(), before)

    def test_same_person_cannot_grant_their_match_request(self):
        first, _ = self.requested()
        review = self.preflight.review(self.accountant, "invoice.approveMatch", first["result"]["approvalId"])
        self.assertFalse(review["allowed"])
        before = self.snapshot()
        args = {"person_id": self.accountant, "action": "invoice.approveMatch", "resource_id": first["result"]["approvalId"],
                "body": {"fingerprint": "cannot-grant"}, "repeatability_key": str(uuid4()), "if_match": review["resourceVersion"]}
        self.assert_refusal_no_write(args, 403)
        self.assertEqual(self.snapshot(), before)

    def test_pm_cannot_prepare_receive_or_grant_match(self):
        args = self.prepare_args()
        self.assert_refusal_no_write(dict(args, person_id=self.pm), 403)
        receive = self.receive_args()
        self.assert_refusal_no_write(dict(receive, person_id=self.pm), 403)
        grants = self.grant_args()
        self.assert_refusal_no_write(dict(grants, person_id=self.pm), 403)

    def test_hidden_commitment_refusal_precedes_receipt_lookup(self):
        args = self.prepare_args()
        args["resource_id"] = self.c.ap_practice_records["hidden_commitment_id"]
        with patch.object(self.runner.receipts, "find", side_effect=AssertionError("must not disclose receipt")):
            self.assert_refusal_no_write(args, 404)

    def test_unknown_invoice_and_approval_use_same_scope_not_found(self):
        for action, resource in (("invoice.computeMatch", "invoice_missing"), ("invoice.approveMatch", "approval_missing")):
            args = dict(person_id=self.accountant, action=action, resource_id=resource, body={"fingerprint": "review"},
                        repeatability_key=str(uuid4()), if_match="version")
            self.assert_refusal_no_write(args, 404)

    def test_unsafe_actor_role_provider_operation_fields_refused(self):
        args = self.receive_args()
        for field, value in (("actor", "practice.bootstrap"), ("actorRole", "owner"), ("supplierId", "chosen-supplier"),
                             ("projectId", "chosen-project"), ("evidenceHash", "caller-hash"), ("provider", "live"), ("operation", "payment.release")):
            with self.subTest(field=field):
                self.assert_refusal_no_write(dict(args, body=dict(args["body"], **{field: value})), 422)

    def test_arbitrary_action_is_not_generic_operation_dispatch(self):
        args = self.prepare_args()
        self.assert_refusal_no_write(dict(args, action="payment.release"), 422)

    def test_shape_invalid_uuid_version_fingerprint_and_bool_amount_refused(self):
        args = self.receive_args()
        for change in ({"repeatability_key": "not-a-uuid"}, {"if_match": ""}, {"body": dict(args["body"], fingerprint="")},
                       {"body": dict(args["body"], amountCents=True)}):
            with self.subTest(change=change):
                self.assert_refusal_no_write(dict(args, **change), 422)

    def test_bad_fingerprint_and_original_version_write_nothing(self):
        args = self.prepare_args()
        self.assert_refusal_no_write(dict(args, body=dict(args["body"], fingerprint="different")), 412)
        self.assert_refusal_no_write(dict(args, if_match="different"), 412)

    def test_changed_body_after_review_requires_new_fingerprint(self):
        args = self.receive_args()
        self.assert_refusal_no_write(dict(args, body=dict(args["body"], amountCents=123)), 412)

    def test_request_different_key_cannot_duplicate_current_match(self):
        first, args = self.requested()
        failure = self.assert_refusal_no_write(dict(args, repeatability_key=str(uuid4())), 409)
        self.assertIn(failure.code, ("duplicate_request", "duplicate_open_approval"))
        self.assertEqual(failure.target, first["result"]["approvalId"])

    def test_no_certified_bill_exception_records_absent_matched_amount(self):
        received, _ = self.receive(amount=100)
        args = self.reviewed("invoice.computeMatch", received["result"]["invoiceId"])
        first = self.runner.run(**args)
        self.assertEqual(first["result"]["status"], "exception")
        self.assertIn("no_certified_bill", first["result"]["exceptions"])
        self.assertNotIn("matchedAmountCents", first["result"])
        before = self.snapshot()
        self.assertEqual(self.runner.run(**args)["result"], first["result"])
        self.assertEqual(self.snapshot(), before)

    def test_second_invoice_after_consumed_match_records_exception_once(self):
        executed = self.runner.run(**self.execute_args())
        received, _ = self.receive(amount=100, number="SECOND-SYNTHETIC-1002",
                                  evidence=self.c.ap_practice_records["visible_invoice_evidence_revision_ids"][1])
        args = self.reviewed("invoice.computeMatch", received["result"]["invoiceId"])
        first = self.runner.run(**args)
        self.assertEqual(first["result"]["status"], "exception")
        self.assertNotIn("matchedAmountCents", first["result"])
        self.assertEqual(self.runner.run(**args)["result"], first["result"])
        self.assertEqual(self.c.bills.get(executed["result"]["billId"])["supplier_invoice_id"], executed["result"]["invoiceId"])

    def test_repeatability_key_cannot_be_rebound_to_body_version_or_resource(self):
        first, args = self.receive()
        for change in ({"body": dict(args["body"], invoiceNumber="CHANGED-2")}, {"if_match": "new-version"},
                       {"resource_id": self.c.ap_practice_records["visible_commitment_ids"][0]}):
            with self.subTest(change=change):
                failure = self.assert_refusal_no_write(dict(args, **change), 409)
                self.assertEqual(failure.code, "repeatability_conflict")

    def test_other_person_same_key_has_no_replay_namespace(self):
        first, args = self.receive()
        failed = self.assert_refusal_no_write(dict(args, person_id=self.reviewer), 409)
        self.assertNotEqual(failed.code, "repeatability_conflict")
        self.assertFalse(hasattr(failed, "receipt_id"))

    def test_receipt_failure_rolls_back_every_supported_action(self):
        factories = (self.prepare_args, self.receive_args,
                     lambda: self.reviewed("invoice.computeMatch", self.receive()[0]["result"]["invoiceId"]),
                     lambda: self.reviewed("invoice.requestMatchApproval", self.computed()[0]["result"]["invoiceId"]),
                     self.grant_args, self.execute_args)
        # Each action gets a fresh fixture to keep unrelated standing drafts and
        # duplicate invoice numbers out of the fault injection evidence.
        for factory in factories:
            with self.subTest(action=factory):
                args = factory()
                original = self.runner.receipts.record
                def fail(**kwargs):
                    original(**kwargs)
                    raise RuntimeError("synthetic post-insert receipt failure")
                self.assert_failure_atomic(args, self.runner.receipts, "record", fail)
                self.c.db.close()
                self.setUp()

    def test_certification_audit_failure_rolls_back_header_and_lines(self):
        args = self.prepare_args()
        original = self.c.audit.record
        def fail(*values, **kwargs):
            if values[1] == "bill.certified":
                raise RuntimeError("certification audit failure")
            return original(*values, **kwargs)
        self.assert_failure_atomic(args, self.c.audit, "record", fail)

    def test_invoice_insert_failure_rolls_back_received_audit(self):
        args = self.receive_args()
        original = self.ap.receive_invoice
        def fail(*values, **kwargs):
            original(*values, **kwargs)
            raise RuntimeError("invoice insert completion failure")
        self.assert_failure_atomic(args, self.ap, "receive_invoice", fail)

    def test_computation_audit_failure_rolls_back_attempt_and_state(self):
        self.prepare()
        inv, _ = self.receive()
        args = self.reviewed("invoice.computeMatch", inv["result"]["invoiceId"])
        original = self.c.audit.record
        def fail(*values, **kwargs):
            if values[1] == "ap_intake.match_computed":
                raise RuntimeError("computation audit failure")
            return original(*values, **kwargs)
        self.assert_failure_atomic(args, self.c.audit, "record", fail)

    def test_request_audit_failure_rolls_back_pending_approval(self):
        computed, _ = self.computed()
        args = self.reviewed("invoice.requestMatchApproval", computed["result"]["invoiceId"])
        original = self.c.audit.record
        def fail(*values, **kwargs):
            if values[1] == "approval.requested":
                raise RuntimeError("request audit failure")
            return original(*values, **kwargs)
        self.assert_failure_atomic(args, self.c.audit, "record", fail)

    def test_grant_governor_completion_failure_rolls_back_grant(self):
        args = self.grant_args()
        owner = self.c.plugin("people")
        original = owner.on_grant
        def fail(*values, **kwargs):
            original(*values, **kwargs)
            raise RuntimeError("grant hook failure")
        self.assert_failure_atomic(args, owner, "on_grant", fail)

    def test_attachment_completion_failure_rolls_back_consume_invoice_and_command(self):
        args = self.execute_args()
        original = self.c.bills.attach_supplier_invoice
        def fail(*values, **kwargs):
            original(*values, **kwargs)
            raise RuntimeError("attachment completion failure")
        self.assert_failure_atomic(args, self.c.bills, "attach_supplier_invoice", fail)

    def test_command_completion_failure_rolls_back_consume_and_attachment(self):
        args = self.execute_args()
        original = self.c.commands.run
        def fail(*values, **kwargs):
            original(*values, **kwargs)
            raise RuntimeError("command completion failure")
        self.assert_failure_atomic(args, self.c.commands, "run", fail)

    def test_commit_failure_rolls_back_domain_and_receipt(self):
        args = self.prepare_args()
        original = self.c.db.transaction
        @contextmanager
        def fail_commit():
            outer = not self.c.db.conn.in_transaction
            with original() as conn:
                yield conn
                if outer:
                    raise RuntimeError("synthetic commit refusal")
        self.assert_failure_atomic(args, self.c.db, "transaction", fail_commit)

    def test_caught_action_failure_inside_outer_transaction_preserves_original_state(self):
        args = self.receive_args()
        before = self.snapshot()
        with self.c.db.transaction():
            with patch.object(self.runner.receipts, "record", side_effect=RuntimeError("receipt unavailable")):
                with self.assertRaises(APRefusal):
                    self.runner.run(**args)
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.snapshot(), before)

    def test_late_stale_execute_rolls_back_all_service_effects_then_only_invalidates(self):
        args = self.execute_args()
        before = self.runner._control_snapshot()
        original = self.ap.apply
        def stale_after_effect(*values, **kwargs):
            original(*values, **kwargs)
            raise StaleApprovalError("Synthetic source changed during attachment")
        with patch.object(self.ap, "apply", side_effect=stale_after_effect):
            with self.assertRaises(APRefusal) as failure:
                self.runner.run(**args)
        self.assertEqual(failure.exception.status, 412)
        approval = self.c.approvals.get(args["resource_id"])
        self.assertEqual(approval["status"], "invalidated")
        self.assertEqual(self.ap.invoice(approval["subject_id"])["status"], "received")
        self.assertIsNone(self.c.bills.get(approval["manifest"]["bindings"]["bill"]["id"])["supplier_invoice_id"])
        after = self.runner._control_snapshot()
        for table, value in before["tables"].items():
            if table != "ap_action_receipts":
                self.assertEqual(after["tables"][table], value, table)
        self.assertEqual(after["schema"], before["schema"])
        self.assertEqual(len(after["audit"]), len(before["audit"]) + 2)
        self.assertEqual(after["audit"][-2]["action"], "approval.invalidated")
        self.assertEqual(after["audit"][-1]["action"], "ap.practice_action_recorded")
        unchanged = self.snapshot()
        with self.assertRaises(APRefusal) as replay:
            self.runner.run(**args)
        self.assertTrue(replay.exception.replayed)
        self.assertEqual(replay.exception.receipt_id, failure.exception.receipt_id)
        self.assertEqual(self.snapshot(), unchanged)

    def test_expiry_during_grant_commits_only_control_transition_and_refused_receipt(self):
        args = self.grant_args()
        approval = self.c.approvals.get(args["resource_id"])
        future = parse_iso(approval["expires_at"]) + dt.timedelta(seconds=1)
        before = self.runner._control_snapshot()
        with patch("apps.cipher.core.approvals.utcnow", return_value=future):
            with self.assertRaises(APRefusal) as failure:
                self.runner.run(**args)
        self.assertEqual(failure.exception.status, 423)
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "expired")
        after = self.runner._control_snapshot()
        for table, value in before["tables"].items():
            if table != "ap_action_receipts":
                self.assertEqual(after["tables"][table], value, table)
        unchanged = self.snapshot()
        with self.assertRaises(APRefusal) as replay:
            self.runner.run(**args)
        self.assertTrue(replay.exception.replayed)
        self.assertEqual(self.snapshot(), unchanged)

    def test_refused_receipt_failure_rolls_back_the_intended_terminal_transition(self):
        args = self.execute_args()
        before = self.snapshot()
        with patch.object(self.ap, "apply", side_effect=StaleApprovalError("Synthetic stale input")):
            with patch.object(self.runner.receipts, "record", side_effect=RuntimeError("refused receipt failed")):
                with self.assertRaises(APRefusal) as failure:
                    self.runner.run(**args)
        self.assertEqual(failure.exception.status, 500)
        self.assertEqual(self.snapshot(), before)

    def test_unverified_expiry_exception_without_elapsed_deadline_rolls_back(self):
        args = self.execute_args()
        with patch.object(self.ap, "apply", side_effect=ApprovalExpired("Synthetic wrong clock")):
            self.assert_refusal_no_write(args, 500)

    def test_terminal_transition_failure_rolls_back_all_effects(self):
        args = self.execute_args()
        with patch.object(self.ap, "apply", side_effect=StaleApprovalError("Synthetic stale input")):
            with patch.object(self.c.approvals, "invalidate", side_effect=RuntimeError("control audit failed")):
                self.assert_refusal_no_write(args, 500)

    def test_exact_concurrent_retry_creates_one_invoice_and_one_receipt(self):
        args = self.receive_args()
        barrier = threading.Barrier(4)
        def invoke(_):
            barrier.wait()
            return self.runner.run(**args)
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(invoke, range(4)))
        self.assertEqual(len({item["receiptId"] for item in results}), 1)
        self.assertEqual(sum(item["effectApplied"] for item in results), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM ap_invoices"), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM ap_action_receipts"), 1)

    def test_concurrent_new_keys_do_not_duplicate_open_match_request(self):
        computed, _ = self.computed()
        args = self.reviewed("invoice.requestMatchApproval", computed["result"]["invoiceId"])
        barrier = threading.Barrier(3)
        def invoke(_):
            barrier.wait()
            try:
                return self.runner.run(**dict(args, repeatability_key=str(uuid4())))
            except APRefusal as exc:
                return exc
        with ThreadPoolExecutor(max_workers=3) as workers:
            results = list(workers.map(invoke, range(3)))
        self.assertEqual(sum(isinstance(item, dict) for item in results), 1)
        self.assertEqual(sum(isinstance(item, APRefusal) and item.status == 409 for item in results), 2)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM approvals WHERE operation='ap_intake.match_invoice'"), 1)

    def test_prepared_bill_line_tamper_fails_original_retry(self):
        first, args = self.prepare()
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='bill_lines'"):
            self.c.db.conn.execute('DROP TRIGGER "' + trigger["name"].replace('"', '""') + '"')
        self.c.db.conn.execute("UPDATE bill_lines SET cumulative_installed='0.00' WHERE bill_id=?", (first["result"]["billId"],))
        self.assert_refusal_no_write(args, 500)
        self.assertFalse(all(item["ok"] for item in self.runner.integrity_checks()))

    def test_received_invoice_rehash_without_original_audit_fails_retry(self):
        first, args = self.receive()
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='ap_invoices'"):
            self.c.db.conn.execute('DROP TRIGGER "' + trigger["name"].replace('"', '""') + '"')
        invoice = self.ap._row(first["result"]["invoiceId"])
        invoice["amount"] = "900.00"
        self.c.db.conn.execute("UPDATE ap_invoices SET amount=?,content_hash=? WHERE id=?", (invoice["amount"], self.ap._content_hash(invoice), invoice["id"]))
        self.assert_refusal_no_write(args, 500)

    def test_match_attempt_rehash_without_original_audit_fails_retry(self):
        first, args = self.computed()
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='ap_invoice_matches'"):
            self.c.db.conn.execute('DROP TRIGGER "' + trigger["name"].replace('"', '""') + '"')
        attempt = self.c.db.one("SELECT * FROM ap_invoice_matches WHERE id=?", (first["result"]["attemptId"],))
        self.c.db.conn.execute("UPDATE ap_invoice_matches SET computed_by=? WHERE id=?", (self.reviewer_login, attempt["id"]))
        # Scoped record validation detects counterfeit attempt history before
        # receipt lookup, while original-proof failures after lookup are 500.
        self.assert_refusal_no_write(args, 422)

    def test_consumed_approval_command_result_tamper_fails_match_retry(self):
        args = self.execute_args()
        first = self.runner.run(**args)
        self.c.db.conn.execute("UPDATE idempotency SET result_json='{}' WHERE op_id=?", (f"exec:{first['result']['approvalId']}",))
        self.assert_refusal_no_write(args, 500)

    def test_audited_receipt_with_wrong_source_event_is_refused(self):
        first, args = self.receive()
        receipt = self.runner.receipts.find(self.accountant, args["repeatability_key"])
        source = loads(receipt["source_json"])
        source["event"]["seq"] -= 1
        with self.c.db.transaction():
            forged = self.runner.receipts.record(person_id=self.accountant, actor_login=self.login, repeatability_uuid=str(uuid4()),
                contract_version=receipt["contract_version"], action=receipt["fixed_action"], resource_id=receipt["resource_id"],
                binding=loads(receipt["binding_json"]), outcome="success", http_status=200,
                result=first["result"], source=source)
        with self.assertRaises(APIReceiptIntegrityError):
            self.runner._verify_source(forged)
        self.assertFalse(all(item["ok"] for item in self.runner.close_checks("2026-10")))

    def test_audited_received_receipt_must_bind_its_original_typed_amount(self):
        first, args = self.receive()
        receipt = self.runner.receipts.find(self.accountant, args["repeatability_key"])
        binding = loads(receipt["binding_json"])
        binding["canonicalTypedBody"]["amountCents"] += 1
        with self.c.db.transaction():
            forged = self.runner.receipts.record(person_id=self.accountant, actor_login=self.login, repeatability_uuid=str(uuid4()),
                contract_version=receipt["contract_version"], action=receipt["fixed_action"], resource_id=receipt["resource_id"],
                binding=binding, outcome="success", http_status=200, result=first["result"], source=loads(receipt["source_json"]))
        with self.assertRaises(APIReceiptIntegrityError):
            self.runner._verify_source(forged)

    def test_audited_preparation_receipt_must_bind_its_original_quantities(self):
        first, args = self.prepare()
        receipt = self.runner.receipts.find(self.accountant, args["repeatability_key"])
        binding = loads(receipt["binding_json"])
        binding["canonicalTypedBody"]["installed"][0]["cumulativeInstalledCents"] += 1
        with self.c.db.transaction():
            forged = self.runner.receipts.record(person_id=self.accountant, actor_login=self.login, repeatability_uuid=str(uuid4()),
                contract_version=receipt["contract_version"], action=receipt["fixed_action"], resource_id=receipt["resource_id"],
                binding=binding, outcome="success", http_status=200, result=first["result"], source=loads(receipt["source_json"]))
        with self.assertRaises(APIReceiptIntegrityError):
            self.runner._verify_source(forged)

    def test_successful_domain_return_with_unexpected_schema_effect_rolls_back(self):
        args = self.prepare_args()
        original = self.c.bills.certify
        def unexpected_schema(*values, **kwargs):
            result = original(*values, **kwargs)
            self.c.db.conn.execute("CREATE TABLE accidental_intake_table (value TEXT)")
            return result
        self.assert_failure_atomic(args, self.c.bills, "certify", unexpected_schema)

    def test_successful_receipt_return_with_unexpected_ledger_effect_rolls_back(self):
        args = self.receive_args()
        original = self.runner.receipts.record
        def unexpected_ledger(**kwargs):
            result = original(**kwargs)
            self.c.ledger.post(period_id="2026-10", description="Unexpected preparation journal",
                source_type="synthetic_intake_fault", source_id="unexpected", source_version="1",
                lines=[{"account": "1000", "debit": "1.00"}, {"account": "2000", "credit": "1.00"}], posted_by=self.login)
            return result
        self.assert_failure_atomic(args, self.runner.receipts, "record", unexpected_ledger)

    def test_successful_request_cannot_mutate_unrelated_approval_row(self):
        computed, _ = self.computed()
        args = self.reviewed("invoice.requestMatchApproval", computed["result"]["invoiceId"])
        unrelated = self.c.bills.get(self.c.ap_practice_records["approved_bill_id"])["business_approval_id"]
        original = self.c.request_approval
        def extra_row(*values, **kwargs):
            result = original(*values, **kwargs)
            self.c.db.conn.execute("UPDATE approvals SET requested_at='2026-01-01T00:00:00Z' WHERE id=?", (unrelated,))
            return result
        self.assert_failure_atomic(args, self.c, "request_approval", extra_row)

    def test_successful_prepare_cannot_append_unreviewed_audit_event(self):
        args = self.prepare_args()
        original = self.c.bills.certify
        def extra_event(*values, **kwargs):
            result = original(*values, **kwargs)
            self.c.audit.record(self.login, "unexpected.intake_side_effect", "bill", result["id"], {"unexpected": True})
            return result
        self.assert_failure_atomic(args, self.c.bills, "certify", extra_event)


if __name__ == "__main__":
    unittest.main()
