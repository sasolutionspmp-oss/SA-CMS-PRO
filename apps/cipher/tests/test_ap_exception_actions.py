"""Fixed AP exception effects, immutable retries and governed correction reversal."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import datetime as dt
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.ap_contract import APContract, APRefusal
from apps.cipher.ap_exception_actions import APExceptionActionRunner
from apps.cipher.ap_exception_contract import APExceptionContract
from apps.cipher.ap_exception_preflight import APExceptionPreflight
from apps.cipher.ap_intake_contract import APIntakeContract
from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
from apps.cipher.core.approvals import ApprovalExpired, StaleApprovalError
from apps.cipher.core.api_receipts import APIReceiptIntegrityError
from apps.cipher.core.ids import loads, parse_iso


class APExceptionActionsTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        secret = b"exception-action-tests-private-server-key-32-bytes"
        self.base = APContract(self.c, secret=secret)
        self.intake = APIntakeContract(self.c, self.base, secret=secret)
        self.contract = APExceptionContract(self.c, self.base, self.intake, secret=secret)
        self.preflight = APExceptionPreflight(self.c, self.contract, secret=secret)
        self.runner = APExceptionActionRunner(self.c, self.contract, self.preflight)
        self.ap = self.c.plugin("ap_intake")
        self.records = self.c.ap_practice_records
        people = self.c.ap_practice_persona_people
        self.accountant, self.pm, self.reviewer = [people[name]["person_id"] for name in ("accountant", "pm", "reviewer")]
        self.login, self.pm_login = people["accountant"]["login"], people["pm"]["login"]

    def snapshot(self):
        return tuple(self.c.db.conn.iterdump())

    def reviewed(self, action, resource, body=None, person=None):
        person, body = person or self.accountant, body or {}
        review = self.preflight.review(person, action, resource, body)
        self.assertTrue(review["allowed"], review)
        return dict(person_id=person, action=action, resource_id=resource, body=dict(body, fingerprint=review["fingerprint"]),
                    repeatability_key=str(uuid4()), if_match=review["resourceVersion"])

    def invoice(self, *, number="EXCEPTION-SYN-1001", evidence=0, amount="11111.10"):
        bill = self.c.bills.get(self.records["draft_bill_id"])
        rev = self.c.evidence.revision(self.records["visible_invoice_evidence_revision_ids"][evidence])
        return self.ap.receive_invoice(bill["supplier_id"], number, "2026-10-14", amount, rev["content_hash"], self.login,
                                       project_id=bill["project_id"], commitment_id=bill["commitment_id"])

    def revise_args(self):
        invoice = self.invoice()
        return self.reviewed("invoice.revise", invoice["id"], dict(reason="Synthetic supplier amount correction",
            invoiceNumber=invoice["invoice_number"], invoiceDate=invoice["invoice_date"], amountCents=99901,
            evidenceRevisionId=invoice["evidence_revision_id"]))

    def reject_args(self):
        return self.reviewed("invoice.reject", self.invoice()["id"], {"reason": "Synthetic invoice not owed"})

    def review_args(self):
        self.invoice()
        inv = self.invoice(number="EXCEPTION-SYN-1002", evidence=1)
        self.assertTrue(inv["possible_duplicate"])
        return self.reviewed("invoice.reviewDuplicate", inv["id"], {"reason": "Synthetic independent obligation verified"})

    def cancel_args(self, *, approved=False):
        return self.reviewed("bill.cancel", self.records["approved_bill_id"] if approved else self.records["draft_bill_id"],
                             {"reason": "Synthetic withdrawn pay application"}, person=self.pm if approved else self.accountant)

    def posted_bill(self):
        bill_id = self.records["approved_bill_id"]
        if self.c.bills.get(bill_id)["status"] == "approved":
            self.c.post_bill(bill_id, actor=self.login, actor_role="accountant", period_id="2026-10")
        return bill_id

    def prepare_args(self):
        return self.reviewed("bill.prepareCorrection", self.posted_bill(), {"reason": "Synthetic installed-work correction"})

    def request_args(self):
        self.runner.run(**self.prepare_args())
        return self.reviewed("bill.requestCorrection", self.posted_bill())

    def grant_args(self):
        requested = self.runner.run(**self.request_args())
        return self.reviewed("bill.approveCorrection", requested["result"]["approvalId"], person=self.reviewer)

    def execute_args(self):
        granted = self.runner.run(**self.grant_args())
        return self.reviewed("bill.executeCorrection", granted["result"]["approvalId"], {"periodId": "2026-11"})

    def assert_retry(self, first, args):
        before = self.snapshot()
        replay = self.runner.run(**args)
        self.assertEqual(replay["result"], first["result"])
        self.assertEqual(replay["receiptId"], first["receiptId"])
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["effectApplied"])
        self.assertEqual(self.snapshot(), before)

    def assert_refusal(self, args, status):
        before = self.snapshot()
        with self.assertRaises(APRefusal) as failure:
            self.runner.run(**args)
        self.assertEqual(failure.exception.status, status)
        self.assertEqual(self.snapshot(), before)
        return failure.exception

    def assert_fault(self, args, owner, method, effect):
        with patch.object(owner, method, side_effect=effect):
            self.assert_refusal(args, 500)

    def test_revision_replays_original_exact_result_after_later_revision(self):
        args = self.revise_args()
        first = self.runner.run(**args)
        self.assertEqual(first["result"]["invoiceVersion"], 2)
        self.ap.revise_invoice(args["resource_id"], self.login, reason="Synthetic later replacement", amount="102.03")
        self.assert_retry(first, args)

    def test_invoice_rejection_and_duplicate_review_never_create_payable(self):
        args = self.review_args()
        journals = self.c.db.scalar("SELECT COUNT(*) FROM journals")
        first = self.runner.run(**args)
        self.assertTrue(first["result"]["duplicateReviewed"])
        self.assert_retry(first, args)
        reject = self.reviewed("invoice.reject", args["resource_id"], {"reason": "Synthetic rejection after documented review"})
        rejected = self.runner.run(**reject)
        self.assertEqual(rejected["result"]["status"], "rejected")
        self.assert_retry(rejected, reject)
        self.assert_retry(first, args)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), journals)
        self.assertTrue(all(item["ok"] for item in self.runner.integrity_checks()))

    def test_draft_and_original_pm_approved_cancellations_exact_retry(self):
        draft = self.cancel_args()
        first = self.runner.run(**draft)
        self.assert_retry(first, draft)
        approved = self.cancel_args(approved=True)
        second = self.runner.run(**approved)
        self.assert_retry(second, approved)
        self.assertEqual(self.c.approvals.get(self.c.bills.get(approved["resource_id"])["business_approval_id"])["status"], "invalidated")

    def test_original_accountant_distinct_reviewer_governed_reversal_then_replacement(self):
        calls = []
        for factory in (self.prepare_args,):
            args = factory()
            calls.append((self.runner.run(**args), args))
        args = self.reviewed("bill.requestCorrection", self.posted_bill())
        requested = self.runner.run(**args)
        calls.append((requested, args))
        args = self.reviewed("bill.approveCorrection", requested["result"]["approvalId"], person=self.reviewer)
        granted = self.runner.run(**args)
        calls.append((granted, args))
        journals = self.c.db.scalar("SELECT COUNT(*) FROM journals")
        args = self.reviewed("bill.executeCorrection", requested["result"]["approvalId"], {"periodId": "2026-11"})
        corrected = self.runner.run(**args)
        calls.append((corrected, args))
        self.assertEqual(corrected["result"]["journalDelta"], 1)
        self.assertEqual(corrected["result"]["apDeltaCents"], -2111110)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), journals + 1)
        self.assertEqual(str(self.c.bills.open_payable(self.posted_bill())), "0.00")
        bill = self.c.bills.get(self.posted_bill())
        commitment = self.c.commitments.get(bill["commitment_id"])
        replacement = self.c.bills.certify(commitment_id=commitment["id"], period_id="2026-11", installed=[
            {"sov_line_id": commitment["sov"][0]["id"], "cumulative_installed": "20000.00"}], actor=self.login)
        self.assertEqual(replacement["sequence"], 2)
        for first, args in calls:
            self.assert_retry(first, args)
        self.assertTrue(all(item["ok"] for item in self.runner.integrity_checks()))
        self.assertEqual(self.c.provider.submissions, [])

    def test_requester_cannot_grant_correction_and_pm_cannot_execute(self):
        args = self.grant_args()
        self.assert_refusal(dict(args, person_id=self.accountant), 403)
        self.assert_refusal(dict(args, person_id=self.pm), 403)

    def test_accountant_cannot_cancel_original_pm_approved_bill(self):
        args = self.cancel_args(approved=True)
        self.assert_refusal(dict(args, person_id=self.accountant), 403)

    def test_hidden_bill_is_unavailable_before_receipt_lookup(self):
        args = self.cancel_args()
        args["resource_id"] = self.records["hidden_bill_id"]
        with patch.object(self.runner.receipts, "find", side_effect=AssertionError("receipt must stay private")):
            self.assert_refusal(args, 404)

    def test_changed_review_version_fingerprint_and_typed_body_are_zero_write(self):
        args = self.revise_args()
        for change in ({"if_match": "different"}, {"body": dict(args["body"], fingerprint="different")},
                       {"body": dict(args["body"], amountCents=100)}):
            self.assert_refusal(dict(args, **change), 412)

    def test_caller_role_actor_provider_and_unknown_action_refused(self):
        args = self.revise_args()
        for name in ("actor", "actorRole", "provider", "projectId", "supplierId", "operation"):
            self.assert_refusal(dict(args, body=dict(args["body"], **{name: "caller-value"})), 422)
        self.assert_refusal(dict(args, action="journal.reverse"), 422)

    def test_repeatability_key_cannot_rebind_original_reason_or_period(self):
        args = self.cancel_args()
        self.runner.run(**args)
        self.assertEqual(self.assert_refusal(dict(args, body=dict(args["body"], reason="Different")), 409).code, "repeatability_conflict")

    def test_duplicate_current_correction_request_cannot_be_created_with_new_key(self):
        args = self.request_args()
        first = self.runner.run(**args)
        failure = self.assert_refusal(dict(args, repeatability_key=str(uuid4())), 409)
        self.assertEqual(failure.target, first["result"]["approvalId"])

    def test_receipt_failure_rolls_back_each_of_eight_domain_effects(self):
        for factory in (self.revise_args, self.reject_args, self.review_args, self.cancel_args,
                        self.prepare_args, self.request_args, self.grant_args, self.execute_args):
            with self.subTest(action=factory.__name__):
                args = factory()
                original = self.runner.receipts.record
                def fail(**kwargs):
                    original(**kwargs)
                    raise RuntimeError("Synthetic receipt completion failure")
                self.assert_fault(args, self.runner.receipts, "record", fail)
                self.c.db.close()
                self.setUp()

    def test_commit_failure_rolls_back_revision_and_receipt(self):
        args = self.revise_args()
        original = self.c.db.transaction
        @contextmanager
        def refuse_commit():
            outer = not self.c.db.conn.in_transaction
            with original() as conn:
                yield conn
                if outer:
                    raise RuntimeError("Synthetic failed commit")
        self.assert_fault(args, self.c.db, "transaction", refuse_commit)

    def test_caught_nested_failure_preserves_complete_original_state(self):
        args = self.cancel_args()
        before = self.snapshot()
        with self.c.db.transaction():
            with patch.object(self.runner.receipts, "record", side_effect=RuntimeError("Receipt failed")):
                with self.assertRaises(APRefusal):
                    self.runner.run(**args)
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.snapshot(), before)

    def test_reversal_failure_after_journal_insert_rolls_back_all_effects(self):
        args = self.execute_args()
        original = self.c.ledger.reverse
        def failed(*values, **kwargs):
            original(*values, **kwargs)
            raise RuntimeError("Synthetic reversal completion failure")
        self.assert_fault(args, self.c.ledger, "reverse", failed)

    def test_late_stale_after_reversal_rolls_back_finance_then_commits_only_control_refusal(self):
        args = self.execute_args()
        before = self.runner._control_snapshot()
        original = self.c.bills._apply_correction
        def stale(*values, **kwargs):
            original(*values, **kwargs)
            raise StaleApprovalError("Synthetic stale source after reversal")
        with patch.object(self.c.bills, "_apply_correction", side_effect=stale):
            with self.assertRaises(APRefusal) as failure:
                self.runner.run(**args)
        self.assertEqual(failure.exception.status, 412)
        self.assertEqual(self.c.approvals.get(args["resource_id"])["status"], "invalidated")
        after = self.runner._control_snapshot()
        for table, value in before["tables"].items():
            if table != "ap_action_receipts":
                self.assertEqual(after["tables"][table], value, table)
        self.assertEqual(len(after["audit"]), len(before["audit"]) + 2)
        state = self.snapshot()
        with self.assertRaises(APRefusal) as replay:
            self.runner.run(**args)
        self.assertTrue(replay.exception.replayed)
        self.assertEqual(replay.exception.receipt_id, failure.exception.receipt_id)
        self.assertEqual(self.snapshot(), state)

    def test_late_expiry_grant_commits_only_control_and_refused_receipt(self):
        args = self.grant_args()
        future = parse_iso(self.c.approvals.get(args["resource_id"])["expires_at"]) + dt.timedelta(seconds=1)
        with patch("apps.cipher.core.approvals.utcnow", return_value=future):
            with self.assertRaises(APRefusal) as failure:
                self.runner.run(**args)
        self.assertEqual(failure.exception.status, 423)
        self.assertEqual(self.c.approvals.get(args["resource_id"])["status"], "expired")

    def test_refused_receipt_failure_undoes_terminal_control_transition(self):
        args = self.execute_args()
        with patch.object(self.c.bills, "_apply_correction", side_effect=StaleApprovalError("Synthetic stale")):
            with patch.object(self.runner.receipts, "record", side_effect=RuntimeError("Synthetic failed receipt")):
                self.assert_refusal(args, 500)

    def test_success_return_cannot_append_unrelated_event_or_mutate_other_invoice(self):
        unrelated = self.invoice(number="UNRELATED-SYN-1009", evidence=1, amount="10.00")
        args = self.revise_args()
        original = self.ap.revise_invoice
        def extra(*values, **kwargs):
            result = original(*values, **kwargs)
            self.ap.reject_invoice(unrelated["id"], "Unexpected rejection", self.login)
            return result
        self.assert_fault(args, self.ap, "revise_invoice", extra)

    def test_success_return_cannot_create_second_correction_approval(self):
        args = self.request_args()
        original = self.c.request_approval
        def extra(*values, **kwargs):
            result = original(*values, **kwargs)
            original(*values, **kwargs)
            return result
        self.assert_fault(args, self.c, "request_approval", extra)

    def test_success_return_cannot_modify_schema(self):
        args = self.cancel_args()
        original = self.c.bills.void
        def extra(*values, **kwargs):
            result = original(*values, **kwargs)
            self.c.db.conn.execute("CREATE TABLE unexpected_exception_table(value TEXT)")
            return result
        self.assert_fault(args, self.c.bills, "void", extra)

    def test_exact_concurrent_revision_applies_once(self):
        args = self.revise_args()
        barrier = threading.Barrier(4)
        def act(_):
            barrier.wait()
            return self.runner.run(**args)
        with ThreadPoolExecutor(max_workers=4) as workers:
            result = list(workers.map(act, range(4)))
        self.assertEqual(sum(row["effectApplied"] for row in result), 1)
        self.assertEqual(len({row["receiptId"] for row in result}), 1)
        self.assertEqual(self.ap.invoice(args["resource_id"])["version"], 2)

    def test_original_reversal_journal_tamper_refuses_retry(self):
        args = self.execute_args()
        first = self.runner.run(**args)
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='journal_lines'"):
            self.c.db.conn.execute('DROP TRIGGER "' + trigger["name"].replace('"', '""') + '"')
        self.c.db.conn.execute("UPDATE journal_lines SET memo='Raw unauthorized memo' WHERE journal_id=?", (first["result"]["reversalJournalIds"][0],))
        with self.assertRaises(APRefusal):
            self.runner.run(**args)
        self.assertFalse(all(item["ok"] for item in self.runner.integrity_checks()))

    def test_revision_of_consumed_matched_invoice_replays_after_another_revision(self):
        inv = self.invoice()
        self.ap.match(inv["id"], self.login)
        approval = self.c.request_approval("ap_intake.match_invoice", inv["id"], actor_role="accountant", requested_by=self.login)
        self.c.approve(approval["id"], approver=self.c.ap_practice_persona_people["reviewer"]["login"], approver_role="accountant")
        self.c.execute(approval["id"], actor=self.login)
        args = self.reviewed("invoice.revise", inv["id"], {"reason": "Synthetic matched source replacement",
            "invoiceNumber": inv["invoice_number"], "invoiceDate": inv["invoice_date"], "amountCents": 10000,
            "evidenceRevisionId": inv["evidence_revision_id"]})
        first = self.runner.run(**args)
        self.ap.revise_invoice(inv["id"], self.login, reason="Synthetic later source correction", amount="110.00")
        self.assert_retry(first, args)
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "consumed")

    def test_duplicate_review_retry_survives_legitimate_duplicate_reset(self):
        args = self.review_args()
        first = self.runner.run(**args)
        self.ap.revise_invoice(args["resource_id"], self.login, reason="Synthetic revised duplicate facts", amount="10.00")
        self.assertFalse(self.ap.invoice(args["resource_id"])["possible_duplicate"])
        self.assert_retry(first, args)

    def test_prepared_correction_retry_survives_cancellation_and_new_request(self):
        args = self.prepare_args()
        first = self.runner.run(**args)
        self.c.bills.cancel_correction(first["result"]["correctionId"], "Synthetic canceled correction", self.login)
        self.c.bills.prepare_correction(args["resource_id"], "Synthetic new correction reason", self.login)
        self.assert_retry(first, args)

    def test_unelapsed_expiry_exception_cannot_commit_terminal_control(self):
        args = self.execute_args()
        with patch.object(self.c.bills, "_apply_correction", side_effect=ApprovalExpired("Synthetic wrong clock")):
            self.assert_refusal(args, 500)

    def test_revision_rehash_without_matching_audit_refuses_current_retry(self):
        args = self.revise_args()
        self.runner.run(**args)
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='ap_invoices'"):
            self.c.db.conn.execute('DROP TRIGGER "' + trigger["name"].replace('"', '""') + '"')
        row = self.ap._row(args["resource_id"])
        row["amount"] = "999.02"
        self.c.db.conn.execute("UPDATE ap_invoices SET amount=?,content_hash=? WHERE id=?", (row["amount"], self.ap._content_hash(row), row["id"]))
        before = self.snapshot()
        with self.assertRaises(APRefusal):
            self.runner.run(**args)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(all(item["ok"] for item in self.runner.integrity_checks()))

    def test_audited_revision_receipt_cannot_claim_different_original_cents(self):
        args = self.revise_args()
        first = self.runner.run(**args)
        receipt = self.runner.receipts.find(self.accountant, args["repeatability_key"])
        binding = loads(receipt["binding_json"])
        binding["canonicalTypedBody"]["amountCents"] += 1
        with self.c.db.transaction():
            forged = self.runner.receipts.record(person_id=self.accountant, actor_login=self.login, repeatability_uuid=str(uuid4()),
                contract_version=receipt["contract_version"], action=receipt["fixed_action"], resource_id=receipt["resource_id"],
                binding=binding, outcome="success", http_status=200, result=first["result"], source=loads(receipt["source_json"]))
        with self.assertRaises(APIReceiptIntegrityError):
            self.runner._verify_source(forged)

    def test_correction_command_result_tamper_cannot_replay_original_financial_outcome(self):
        args = self.execute_args()
        self.runner.run(**args)
        self.c.db.conn.execute("UPDATE idempotency SET result_json='{}' WHERE op_id=?", (f"exec:{args['resource_id']}",))
        self.assert_refusal(args, 500)


if __name__ == "__main__":
    unittest.main()
