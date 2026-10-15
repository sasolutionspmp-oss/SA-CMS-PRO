"""Pure, exact and independently governed installed-work intake reviews."""
import datetime
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APContract, APRefusal
from apps.cipher.ap_intake_contract import APIntakeContract
from apps.cipher.ap_intake_preflight import APIntakePreflight, approval_proof
from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
from apps.cipher.core.approvals import StaleApprovalError
from apps.cipher.core.ids import utcnow
from apps.cipher.domain.ap_intake import APIntakeError


class APIntakePreflightTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.records = self.c.ap_practice_records
        self.accountant = self.c.ap_practice_persona_people["accountant"]["person_id"]
        self.reviewer = self.c.ap_practice_persona_people["reviewer"]["person_id"]
        self.pm = self.c.ap_practice_persona_people["pm"]["person_id"]
        self.secret = b"intake-preflight-private-test-key-32"
        self.base = APContract(self.c, secret=self.secret)
        self.contract = APIntakeContract(self.c, self.base, secret=self.secret)
        self.preflight = APIntakePreflight(self.c, self.contract, secret=self.secret)
        self.ap = self.c.plugin("ap_intake")
        self.commitment = self.c.commitments.get(self.records["prep_commitment_id"])

    def snapshot(self):
        return (tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes,
                tuple(self.c.provider.submissions), dict(self.c.provider.transfers))

    def preparation_body(self):
        return {"periodId": "2026-10", "installed": [
            {"sovLineId": self.commitment["sov"][0]["id"], "cumulativeInstalledCents": 1_000_001},
            {"sovLineId": self.commitment["sov"][1]["id"], "cumulativeInstalledCents": 2_000_002}]}

    def prepare(self):
        body = self.preparation_body()
        return self.c.bills.certify(commitment_id=self.commitment["id"], period_id=body["periodId"],
            installed=[{"sov_line_id": line["sovLineId"], "cumulative_installed": f"{line['cumulativeInstalledCents'] // 100}.{line['cumulativeInstalledCents'] % 100:02}"} for line in body["installed"]], actor="practice.accountant")

    def receive(self, *, amount=None, number="SYN-INV-101", evidence=0):
        bill = self.c.bills.latest(self.commitment["id"]) or self.prepare()
        revision = self.c.evidence.revision(self.records["visible_invoice_evidence_revision_ids"][evidence])
        return self.ap.receive_invoice(self.commitment["supplier_id"], number, "2026-10-14", amount or bill["amount_due"],
            revision["content_hash"], "practice.accountant", project_id=self.commitment["project_id"], commitment_id=self.commitment["id"])

    def request(self):
        invoice = self.receive()
        self.ap.match(invoice["id"], "practice.accountant")
        approval = self.c.request_approval("ap_intake.match_invoice", invoice["id"], actor_role="accountant", requested_by="practice.accountant")
        return invoice, approval

    def test_preparation_review_is_exact_and_never_records_any_effect(self):
        before = self.snapshot()
        review = self.preflight.review(self.accountant, "bill.prepare", self.commitment["id"], self.preparation_body())
        self.assertTrue(review["allowed"], review)
        self.assertEqual(self.snapshot(), before)
        effects = review["safeEffects"]
        self.assertEqual(effects["thisPeriodCents"], 3_000_003)
        self.assertEqual(effects["retainageCents"], 300_000)
        self.assertEqual(effects["amountDueCents"], 2_700_003)
        self.assertEqual(effects["workingLedgerJournalDelta"], 0)
        self.assertEqual(effects["apPayableDeltaCents"], 0)

    def test_receipt_review_derives_supplier_project_evidence_and_terms_without_writes(self):
        body = {"invoiceNumber": "SYN-INV-101", "invoiceDate": "2026-10-14", "amountCents": 2_700_003,
                "evidenceRevisionId": self.records["visible_invoice_evidence_revision_ids"][0]}
        before = self.snapshot()
        review = self.preflight.review(self.accountant, "invoice.receive", self.commitment["id"], body)
        context = self.preflight.verify(self.accountant, "invoice.receive", self.commitment["id"],
                                       {**body, "fingerprint": review["fingerprint"]}, review["resourceVersion"])
        self.assertTrue(review["allowed"], review)
        self.assertEqual(context["params"]["amount"], "27000.03")
        self.assertEqual(context["params"]["supplier_id"], self.commitment["supplier_id"])
        self.assertEqual(context["params"]["project_id"], self.commitment["project_id"])
        self.assertEqual(context["plan"]["content"]["due_date"], "2026-11-13")
        self.assertEqual(self.snapshot(), before)

    def test_maximum_domain_integer_cents_survive_without_float_rounding(self):
        body = {"invoiceNumber": "SYN-MAX-CENTS", "invoiceDate": "2026-10-14", "amountCents": 10**15 - 1,
                "evidenceRevisionId": self.records["visible_invoice_evidence_revision_ids"][0]}
        before = self.snapshot()
        review = self.preflight.review(self.accountant, "invoice.receive", self.commitment["id"], body)
        self.assertTrue(review["allowed"], review)
        context = self.preflight.verify(self.accountant, "invoice.receive", self.commitment["id"],
                                       {**body, "fingerprint": review["fingerprint"]}, review["resourceVersion"])
        self.assertEqual(context["params"]["amount"], "9999999999999.99")
        self.assertEqual(review["safeEffects"]["amountCents"], body["amountCents"])
        self.assertEqual(self.snapshot(), before)

    def test_client_safe_integer_that_exceeds_domain_range_is_a_typed_refusal(self):
        body = {"invoiceNumber": "SYN-MAX-CENTS", "invoiceDate": "2026-10-14", "amountCents": (1 << 53) - 1,
                "evidenceRevisionId": self.records["visible_invoice_evidence_revision_ids"][0]}
        before = self.snapshot()
        review = self.preflight.review(self.accountant, "invoice.receive", self.commitment["id"], body)
        self.assertFalse(review["allowed"], review)
        self.assertEqual(review["checks"][-1]["code"], "invalid_amount")
        self.assertIsNone(review["fingerprint"])
        self.assertEqual(self.snapshot(), before)

    def test_duplicate_and_near_duplicate_reviews_never_disclose_private_invoice_ids(self):
        revision = self.c.evidence.revision(self.records["hidden_invoice_evidence_revision_ids"][0])
        hidden = self.ap.receive_invoice(self.commitment["supplier_id"], "SYN-PRIVATE-101", "2026-10-14", "100.00",
            revision["content_hash"], "practice.hidden.accountant", project_id=self.records["hidden_project_id"])
        body = {"invoiceNumber": "SYN-PRIVATE-101", "invoiceDate": "2026-10-14", "amountCents": 10_000,
                "evidenceRevisionId": self.records["visible_invoice_evidence_revision_ids"][0]}
        before = self.snapshot()
        duplicate = self.preflight.review(self.accountant, "invoice.receive", self.commitment["id"], body)
        near = self.preflight.review(self.accountant, "invoice.receive", self.commitment["id"], {**body, "invoiceNumber": "SYN-PRIVATE-102"})
        self.assertEqual(duplicate["checks"][-1]["code"], "duplicate_invoice")
        self.assertFalse(duplicate["allowed"])
        self.assertTrue(near["allowed"], near)
        self.assertTrue(near["safeEffects"]["possibleDuplicate"])
        self.assertNotIn(hidden["id"], str(duplicate) + str(near))
        self.assertEqual(self.snapshot(), before)

    def test_all_four_match_reviews_are_pure_and_follow_two_actual_accountants(self):
        invoice = self.receive()
        before = self.snapshot()
        compute = self.preflight.review(self.accountant, "invoice.computeMatch", invoice["id"], {})
        self.assertTrue(compute["allowed"], compute)
        self.assertEqual(compute["safeEffects"]["matchStatus"], "matched")
        self.assertEqual(self.snapshot(), before)
        self.ap.match(invoice["id"], "practice.accountant")
        before = self.snapshot()
        request = self.preflight.review(self.accountant, "invoice.requestMatchApproval", invoice["id"], {})
        self.assertTrue(request["allowed"], request)
        self.assertEqual(self.snapshot(), before)
        approval = self.c.request_approval("ap_intake.match_invoice", invoice["id"], actor_role="accountant", requested_by="practice.accountant")
        before = self.snapshot()
        grant = self.preflight.review(self.reviewer, "invoice.approveMatch", approval["id"], {})
        self.assertTrue(grant["allowed"], grant)
        self.assertFalse(grant["safeEffects"]["billLinked"])
        self.assertEqual(self.snapshot(), before)
        proof = approval_proof(self.c, approval["id"])
        self.c.approve(approval["id"], approver="practice.reviewer", approver_role="accountant")
        before = self.snapshot()
        execute = self.preflight.review(self.accountant, "invoice.executeMatch", approval["id"], {})
        self.assertTrue(execute["allowed"], execute)
        self.assertTrue(execute["safeEffects"]["billLinked"])
        self.assertEqual(self.snapshot(), before)
        self.c.execute(approval["id"], actor="practice.accountant")
        self.assertEqual(approval_proof(self.c, approval["id"]), proof)
        self.assertEqual(self.ap.invoice(invoice["id"])["status"], "matched")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)

    def test_computing_exception_is_allowed_without_exposing_raw_details(self):
        invoice = self.receive(amount="1.00")
        before = self.snapshot()
        review = self.preflight.review(self.accountant, "invoice.computeMatch", invoice["id"], {})
        self.assertTrue(review["allowed"], review)
        self.assertEqual(review["safeEffects"]["matchStatus"], "exception")
        self.assertIn("amount_mismatch", review["safeEffects"]["matchExceptionCodes"])
        self.assertNotIn("details", str(review))
        self.assertEqual(self.snapshot(), before)

    def test_same_accountant_cannot_grant_and_pm_cannot_review_matching(self):
        _invoice, approval = self.request()
        before = self.snapshot()
        same = self.preflight.review(self.accountant, "invoice.approveMatch", approval["id"], {})
        self.assertFalse(same["allowed"])
        self.assertEqual(same["checks"][-1]["code"], "duty_refused")
        with self.assertRaises(APRefusal) as failure:
            self.preflight.review(self.pm, "invoice.approveMatch", approval["id"], {})
        self.assertEqual(failure.exception.status, 403)
        self.assertEqual(self.snapshot(), before)

    def test_nonce_and_clock_do_not_change_material_fingerprint(self):
        invoice = self.receive()
        self.ap.match(invoice["id"], "practice.accountant")
        first = self.preflight.review(self.accountant, "invoice.requestMatchApproval", invoice["id"], {})
        with patch("apps.cipher.core.approvals.utcnow", return_value=utcnow() + datetime.timedelta(minutes=5)):
            second = self.preflight.review(self.accountant, "invoice.requestMatchApproval", invoice["id"], {})
        self.assertTrue(first["allowed"], first)
        self.assertEqual(first["resourceVersion"], second["resourceVersion"])
        self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_closed_period_is_a_zero_write_refusal(self):
        self.c.db.execute("UPDATE periods SET status='closed' WHERE id='2026-10'")
        before = self.snapshot()
        closed = self.preflight.review(self.accountant, "bill.prepare", self.commitment["id"], self.preparation_body())
        self.assertFalse(closed["allowed"])
        self.assertEqual(closed["checks"][-1]["code"], "period_locked")
        self.assertEqual(self.snapshot(), before)

    def test_duplicate_request_is_a_zero_write_refusal(self):
        invoice, approval = self.request()
        before = self.snapshot()
        duplicate = self.preflight.review(self.accountant, "invoice.requestMatchApproval", invoice["id"], {})
        self.assertEqual(duplicate["checks"][-1]["code"], "duplicate_request")
        self.assertEqual(duplicate["checks"][-1]["target"], approval["id"])
        self.assertEqual(self.snapshot(), before)

    def test_expiry_changes_eligibility_without_writing_terminal_state(self):
        _invoice, approval = self.request()
        review = self.preflight.review(self.reviewer, "invoice.approveMatch", approval["id"], {})
        self.preflight.now = lambda: utcnow() + datetime.timedelta(days=2)
        before = self.snapshot()
        expired = self.preflight.review(self.reviewer, "invoice.approveMatch", approval["id"], {})
        self.assertFalse(expired["allowed"])
        self.assertEqual(expired["checks"][-1]["code"], "approval_expired")
        self.assertEqual(review["resourceVersion"], expired["resourceVersion"])
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "pending")
        self.assertEqual(self.snapshot(), before)

    def test_changed_bill_facts_refuse_grant_both_review_and_actual_service(self):
        invoice, approval = self.request()
        bill = self.c.bills.latest(self.commitment["id"])
        request = self.c.request_approval("bill.approve", bill["id"], actor_role="accountant", requested_by="practice.accountant")
        self.c.approve(request["id"], approver="practice.pm", approver_role="pm")
        before = self.snapshot()
        review = self.preflight.review(self.reviewer, "invoice.approveMatch", approval["id"], {})
        self.assertFalse(review["allowed"])
        self.assertEqual(review["checks"][-1]["code"], "approval_stale")
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(StaleApprovalError):
            self.c.approve(approval["id"], approver="practice.reviewer", approver_role="accountant")
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "invalidated")
        self.assertEqual(self.ap.invoice(invoice["id"])["status"], "received")

    def test_forged_body_bool_unsafe_cents_duplicate_lines_and_foreign_sov_are_refused(self):
        original = self.preparation_body()
        bad_bodies = [{**original, "actor": "practice.bootstrap"}, {**original, "installed": [original["installed"][0]] * 2},
                      {**original, "installed": [{"sovLineId": f"line-{index}", "cumulativeInstalledCents": 1} for index in range(101)]},
                      {**original, "installed": [{**original["installed"][0], "cumulativeInstalledCents": True}]},
                      {**original, "installed": [{**original["installed"][0], "cumulativeInstalledCents": 1 << 53}]},
                      {**original, "installed": [{**original["installed"][0], "transfer": "forged"}]}]
        before = self.snapshot()
        for body in bad_bodies:
            with self.subTest(body=body), self.assertRaises(APRefusal):
                self.preflight.review(self.accountant, "bill.prepare", self.commitment["id"], body)
        foreign = self.c.commitments.get(self.records["hidden_commitment_id"])["sov"][0]["id"]
        review = self.preflight.review(self.accountant, "bill.prepare", self.commitment["id"],
                                      {**original, "installed": [{"sovLineId": foreign, "cumulativeInstalledCents": 100}]})
        self.assertFalse(review["allowed"])
        self.assertNotIn(foreign, str(review))
        self.assertEqual(self.snapshot(), before)

    def test_hidden_evidence_is_404_and_stale_evidence_is_pure_block(self):
        body = {"invoiceNumber": "SYN-INV-101", "invoiceDate": "2026-10-14", "amountCents": 100,
                "evidenceRevisionId": self.records["hidden_invoice_evidence_revision_ids"][0]}
        before = self.snapshot()
        with self.assertRaises(APRefusal) as failure:
            self.preflight.review(self.accountant, "invoice.receive", self.commitment["id"], body)
        self.assertEqual(failure.exception.status, 404)
        self.assertEqual(self.snapshot(), before)
        old = self.records["visible_invoice_evidence_revision_ids"][0]
        doc = self.c.evidence.revision(old)["document_id"]
        self.c.evidence.add_revision(document_id=doc, content="Synthetic revised invoice", actor="practice.accountant")
        before = self.snapshot()
        stale = self.preflight.review(self.accountant, "invoice.receive", self.commitment["id"], {**body, "evidenceRevisionId": old})
        self.assertFalse(stale["allowed"])
        self.assertEqual(stale["checks"][-1]["code"], "evidence_stale")
        self.assertEqual(self.snapshot(), before)

    def test_changed_input_or_if_match_requires_review_without_writes(self):
        body = self.preparation_body()
        review = self.preflight.review(self.accountant, "bill.prepare", self.commitment["id"], body)
        before = self.snapshot()
        for version, fingerprint, expected in (("other", review["fingerprint"], "record_changed"),
                                               (review["resourceVersion"], "forged", "preflight_changed")):
            with self.subTest(expected=expected), self.assertRaises(APRefusal) as failure:
                self.preflight.verify(self.accountant, "bill.prepare", self.commitment["id"], {**body, "fingerprint": fingerprint}, version)
            self.assertEqual(failure.exception.code, expected)
        self.assertEqual(self.snapshot(), before)

    def test_trigger_removal_cannot_resurrect_invalidated_or_forge_match_authority(self):
        _invoice, approval = self.request()
        self.c.approvals.invalidate(approval["id"], reason="Synthetic canceled review", actor="practice.reviewer")
        self.c.db.execute("DROP TRIGGER approvals_lifecycle")
        self.c.db.execute("UPDATE approvals SET status='pending',invalidated_reason=NULL WHERE id=?", (approval["id"],))
        before = self.snapshot()
        with self.assertRaises(APIntakeError):
            approval_proof(self.c, approval["id"])
        with self.assertRaises(APIntakeError):
            self.c.check_invoice_match_grant(approval["id"], approver="practice.reviewer", approver_role="accountant")
        self.assertEqual(self.snapshot(), before)

    def test_shortened_deadline_is_valid_but_extension_or_naive_deadline_is_refused(self):
        _invoice, approval = self.request()
        shortened = (utcnow() + datetime.timedelta(hours=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.c.db.execute("UPDATE approvals SET expires_at=? WHERE id=?", (shortened, approval["id"]))
        before = self.snapshot()
        self.assertTrue(self.preflight.review(self.reviewer, "invoice.approveMatch", approval["id"], {})["allowed"])
        self.assertEqual(self.snapshot(), before)
        self.c.db.execute("DROP TRIGGER approvals_request_immutable")
        for deadline in ((utcnow() + datetime.timedelta(days=3)).isoformat(), "2099-01-01T00:00:00"):
            self.c.db.execute("UPDATE approvals SET expires_at=? WHERE id=?", (deadline, approval["id"]))
            before = self.snapshot()
            with self.subTest(deadline=deadline), self.assertRaises(APIntakeError):
                approval_proof(self.c, approval["id"])
            self.assertEqual(self.snapshot(), before)

    def test_membership_loss_refuses_review_before_disclosing_source(self):
        _invoice, approval = self.request()
        review = self.preflight.review(self.reviewer, "invoice.approveMatch", approval["id"], {})
        self.c.plugin("people").end_membership("practice.reviewer", self.commitment["project_id"],
                                               reason="Synthetic assignment ended", actor="practice.bootstrap")
        before = self.snapshot()
        with self.assertRaises(APRefusal) as failure:
            self.preflight.verify(self.reviewer, "invoice.approveMatch", approval["id"],
                                  {"fingerprint": review["fingerprint"]}, review["resourceVersion"])
        self.assertEqual(failure.exception.status, 404)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_effectful_governor_is_never_invoked_by_execution_review(self):
        _invoice, approval = self.request()
        self.c.approve(approval["id"], approver="practice.reviewer", approver_role="accountant")
        class EffectfulGovernor:
            GOVERNOR = True
            def check_execute(self, approval, manifest, *, actor):
                raise AssertionError("Effects cannot be invoked during a pure review")
        self.c.register_plugin("synthetic_effectful_governor", EffectfulGovernor())
        before = self.snapshot()
        review = self.preflight.review(self.accountant, "invoice.executeMatch", approval["id"], {})
        self.assertFalse(review["allowed"])
        self.assertEqual(review["checks"][-1]["code"], "review_unavailable")
        self.assertEqual(self.snapshot(), before)

    def test_match_control_rejects_tampered_aggregate_contributor_even_when_omitted_from_sum(self):
        invoice, approval = self.request()
        self.c.approve(approval["id"], approver="practice.reviewer", approver_role="accountant")
        self.c.execute(approval["id"], actor="practice.accountant")
        bill = self.c.bills.latest(self.commitment["id"])
        business = self.c.request_approval("bill.approve", bill["id"], actor_role="accountant", requested_by="practice.accountant")
        self.c.approve(business["id"], approver="practice.pm", approver_role="pm")
        self.c.post_bill(bill["id"], actor="practice.accountant", period_id="2026-10")
        next_bill = self.c.bills.certify(commitment_id=self.commitment["id"], period_id="2026-10", actor="practice.accountant", installed=[
            {"sov_line_id": self.commitment["sov"][0]["id"], "cumulative_installed": "20000.01"},
            {"sov_line_id": self.commitment["sov"][1]["id"], "cumulative_installed": "30000.02"}])
        revision = self.c.evidence.revision(self.records["visible_invoice_evidence_revision_ids"][1])
        second = self.ap.receive_invoice(self.commitment["supplier_id"], "SYN-INV-102", "2026-10-14", next_bill["amount_due"],
            revision["content_hash"], "practice.accountant", project_id=self.commitment["project_id"], commitment_id=self.commitment["id"])
        clean = self.preflight.review(self.accountant, "invoice.computeMatch", second["id"], {})
        self.assertTrue(clean["allowed"], clean)
        triggers = self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='ap_invoices'")
        for trigger in triggers:
            self.c.db.execute('DROP TRIGGER "' + trigger["name"].replace('"', '""') + '"')
        self.c.db.execute("UPDATE ap_invoices SET status='received' WHERE id=?", (invoice["id"],))
        before = self.snapshot()
        review = self.preflight.review(self.accountant, "invoice.computeMatch", second["id"], {})
        self.assertFalse(review["allowed"], review)
        with self.assertRaises(APIntakeError):
            self.ap.match_preflight(second["id"])
        self.assertEqual(self.snapshot(), before)

    def test_a_revised_invoice_keeps_its_genuine_historical_match_actor(self):
        invoice, approval = self.request()
        self.c.approve(approval["id"], approver="practice.reviewer", approver_role="accountant")
        self.c.execute(approval["id"], actor="practice.accountant")
        self.ap.revise_invoice(invoice["id"], "practice.accountant", reason="Synthetic later due date", due_date="2026-11-30")
        self.ap.invoice_proof(invoice["id"])
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='ap_invoices'"):
            self.c.db.execute('DROP TRIGGER "' + trigger["name"].replace('"', '""') + '"')
        self.c.db.execute("UPDATE ap_invoices SET matched_by='forged actor' WHERE id=?", (invoice["id"],))
        before = self.snapshot()
        with self.assertRaises(APIntakeError):
            self.ap.invoice_proof(invoice["id"])
        integrity_check = next(check for check in self.ap.close_checks("2026-10") if check["check"] == "ap_intake supplier invoice records intact")
        self.assertFalse(integrity_check["ok"])
        self.assertFalse(self.ap.audit_export()["source_integrity"][0]["ok"])
        self.assertEqual(self.snapshot(), before)

    def test_deleted_unreceipted_invoice_remains_an_integrity_failure_in_close_and_export(self):
        invoice = self.receive()
        self.c.db.execute("DROP TRIGGER ap_invoices_no_delete")
        self.c.db.execute("DELETE FROM ap_invoices WHERE id=?", (invoice["id"],))
        before = self.snapshot()
        check = next(check for check in self.ap.close_checks("2026-10") if check["check"] == "ap_intake supplier invoice records intact")
        self.assertFalse(check["ok"])
        exported = self.ap.audit_export()["source_integrity"]
        self.assertEqual([(row["invoice_id"], row["ok"]) for row in exported], [(invoice["id"], False)])
        self.assertEqual(self.snapshot(), before)
