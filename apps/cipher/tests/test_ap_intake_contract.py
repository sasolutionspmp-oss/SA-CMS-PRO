"""Scoped intake presenters preserve source proof and exact practice money."""
import json
import unittest

from apps.cipher.ap_contract import APContract, APRefusal
from apps.cipher.ap_intake_contract import APIntakeContract
from apps.cipher.ap_practice_fixture import (
    ACCOUNTANT_LOGIN, HIDDEN_ACCOUNTANT_LOGIN, HIDDEN_PM_LOGIN, PM_LOGIN, REVIEWER_LOGIN, make_ap_practice_fixture,
)
from apps.cipher.core.ids import canonical_json, hash_json
from apps.cipher.core.money import money


class APIntakeContractTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.records = self.c.ap_practice_records
        self.people = self.c.ap_practice_persona_people
        self.accountant = self.people["accountant"]["person_id"]
        self.pm = self.people["pm"]["person_id"]
        self.reviewer = self.people["reviewer"]["person_id"]
        self.ap = self.c.plugin("ap_intake")
        secret = b"intake-contract-test-key-of-32-bytes"
        self.base = APContract(self.c, secret=secret)
        self.contract = APIntakeContract(self.c, self.base, secret=secret)

    def receive(self, *, hidden=False, number="SYN-100", amount=None, evidence_index=0, commitment_id=None):
        commitment_id = commitment_id or (self.records["hidden_commitment_id"] if hidden else self.records["visible_commitment_ids"][0])
        commitment = self.c.commitments.get(commitment_id)
        revision = self.c.evidence.revision(self.records["hidden_invoice_evidence_revision_ids" if hidden else "visible_invoice_evidence_revision_ids"][evidence_index])
        bill = self.c.bills.latest(commitment_id)
        return self.ap.receive_invoice(commitment["supplier_id"], number, "2026-10-14", amount or bill["amount_due"],
                                       revision["content_hash"], HIDDEN_ACCOUNTANT_LOGIN if hidden else ACCOUNTANT_LOGIN,
                                       project_id=commitment["project_id"], commitment_id=commitment_id)

    def approval(self, invoice):
        self.ap.match(invoice["id"], ACCOUNTANT_LOGIN)
        return self.c.request_approval("ap_intake.match_invoice", invoice["id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)

    def drop_guards(self, table):
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)):
            self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')

    def test_fixture_preparation_and_invoice_documents_have_real_sources(self):
        prep = self.contract.preparation(self.accountant, self.records["prep_commitment_id"])
        self.assertEqual(prep["status"], "executed")
        self.assertIsNone(prep["priorBill"])
        self.assertEqual([line["scheduledCents"] for line in prep["lines"]], [4000000, 6000000])
        self.assertEqual([line["priorInstalledCents"] for line in prep["lines"]], [0, 0])
        self.assertEqual(prep["retainageRateMicros"], 100000)
        self.assertEqual(set(prep["availableActions"]), {"bill.prepare", "invoice.receive"})
        evidence = self.contract.read(self.accountant, "invoice-evidence")
        self.assertEqual(evidence["count"], 6)
        self.assertTrue(all(row["available"] and row["revision"] == 1 and row["isCurrent"] for row in evidence["value"]))
        self.assertEqual(self.c.plugin("people").authority_problems(), [])

    def test_existing_bill_states_project_counts_and_duties_are_preserved(self):
        self.assertEqual(self.base.read(self.accountant, "projects")["count"], 2)
        self.assertEqual(self.base.read(self.accountant, "bills")["count"], 2)
        self.assertEqual(self.c.bills.get(self.records["draft_bill_id"])["status"], "draft")
        self.assertEqual(self.c.bills.get(self.records["approved_bill_id"])["status"], "approved")
        self.assertEqual(self.base.read(self.accountant, "commitments")["count"], 3)
        self.assertEqual(self.c.plugin("people").person_for(REVIEWER_LOGIN)["display_name"], "Jordan Chen (synthetic AP reviewer)")

    def test_intake_lists_scope_before_totals_names_evidence_and_invalid_hidden_rows(self):
        visible = self.receive()
        hidden = self.receive(hidden=True)
        self.drop_guards("ap_invoices")
        self.c.db.execute("UPDATE ap_invoices SET amount='private-bad-number' WHERE id=?", (hidden["id"],))
        result = self.contract.read(self.accountant, "invoices")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["totals"], {"amountCents": int(money(visible["amount"]) * 100)})
        text = json.dumps([result, self.contract.read(self.accountant, "invoice-evidence")])
        for private in (hidden["id"], self.records["hidden_project_id"], "Hidden", "private-bad-number"):
            self.assertNotIn(private, text)

    def test_hidden_unknown_records_have_identical_not_found(self):
        hidden = self.receive(hidden=True)
        for getter, actual in ((self.contract.invoice, hidden["id"]), (self.contract.preparation, self.records["hidden_commitment_id"])):
            errors = []
            for record_id in (actual, "unknown-record"):
                with self.assertRaises(APRefusal) as failure:
                    getter(self.accountant, record_id)
                errors.append((failure.exception.status, failure.exception.value))
            self.assertEqual(errors[0], errors[1])
            self.assertEqual(errors[0][0], 404)
        for collection in ("invoices", "invoice-evidence", "match-approvals"):
            with self.assertRaises(APRefusal) as failure:
                self.contract.read(self.accountant, collection, project_id=self.records["hidden_project_id"])
            self.assertEqual(failure.exception.status, 404)

    def test_selectable_reviewer_is_an_independent_actual_accountant(self):
        self.assertNotEqual(self.reviewer, self.accountant)
        prep = self.records["prep_commitment_id"]
        for principal in (self.accountant, self.reviewer):
            self.assertEqual(self.contract.authorize(principal, "bill.prepare", prep)["duty"], "accountant")
        with self.assertRaises(APRefusal) as failure:
            self.contract.authorize(self.pm, "bill.prepare", prep)
        self.assertEqual(failure.exception.status, 403)
        owner = self.c.plugin("people").person_for("practice.bootstrap")["id"]
        self.assertEqual(self.contract.read(owner, "invoices")["count"], 0)
        with self.assertRaises(APRefusal) as failure:
            self.contract.preparation(owner, prep)
        self.assertEqual(failure.exception.status, 404)

    def test_invoice_exact_cents_and_allowlisted_fields_do_not_leak_proofs(self):
        inv = self.receive()
        value = self.contract.invoice(self.accountant, inv["id"])
        self.assertIs(type(value["amountCents"]), int)
        self.assertEqual(value["amountCents"], 1111110)
        self.assertEqual((value["contractVersion"], value["mode"], value["synthetic"], value["currency"]),
                         ("cipher.ap-practice.v1", "practice", True, "USD"))
        self.assertEqual(value["invoiceNumber"], "SYN-100")
        self.assertEqual(value["availableActions"], ["invoice.computeMatch"])
        self.assertIsNone(value["match"])
        text = json.dumps(value)
        for private in ("manifest", "content_hash", "result_hash", "destination", "nonce", "duplicate_of", "lines_json", "actor_role"):
            self.assertNotIn('"' + private + '"', text)

    def test_recorded_match_presents_safe_codes_then_genuine_match_packet(self):
        inv = self.receive()
        ap = self.approval(inv)
        value = self.contract.invoice(self.accountant, inv["id"])
        self.assertEqual(value["match"]["status"], "matched")
        self.assertEqual(value["match"]["exceptions"], [])
        self.assertEqual(value["match"]["billId"], self.records["draft_bill_id"])
        packet = self.contract.packet(self.reviewer, ap["id"])
        self.assertEqual(packet["availableActions"], ["invoice.approveMatch"])
        self.assertEqual(packet["changes"], [])
        self.assertEqual(packet["effect"], {"invoiceStatus": "matched", "billLinked": True, "workingLedgerJournalDelta": 0, "apPayableDeltaCents": 0})
        self.assertEqual(self.contract.packet(self.accountant, ap["id"])["availableActions"], [])
        self.c.approve(ap["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        self.assertEqual(self.contract.packet(self.accountant, ap["id"])["availableActions"], ["invoice.executeMatch"])
        self.c.execute(ap["id"], actor=ACCOUNTANT_LOGIN)
        matched = self.contract.invoice(self.accountant, inv["id"])
        self.assertEqual(matched["status"], "matched")
        self.assertEqual(self.contract.packet(self.reviewer, ap["id"])["effectiveStatus"], "consumed")
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 0)

    def test_same_number_normalization_and_possible_duplicates_remain_domain_truth(self):
        first = self.receive()
        second = self.receive(number="SYN-101", evidence_index=1)
        self.ap.match(second["id"], ACCOUNTANT_LOGIN)
        value = self.contract.invoice(self.accountant, second["id"])
        self.assertTrue(value["possibleDuplicate"])
        self.assertTrue(value["duplicateBlocking"])
        self.assertEqual(value["match"]["exceptions"], [{"code": "possible_duplicate", "message": "A possible duplicate requires a separate documented review."}])
        self.assertNotIn(first["id"], json.dumps(value))
        self.assertNotIn("invoice.requestMatchApproval", value["availableActions"])

    def test_same_supplier_hidden_duplicate_ids_never_enter_match_details(self):
        original = self.c.commitments.get(self.records["visible_commitment_ids"][0])
        hidden_commitment = self.c.commitments.create(project_id=self.records["hidden_project_id"], supplier_id=original["supplier_id"],
                                                    title="Hidden supplier allocation", sov_lines=[{"description": "Hidden work", "cost_code": "03-000", "amount": "100000.00"}],
                                                    retainage_rate="0.10", actor=HIDDEN_PM_LOGIN)
        approval = self.c.request_approval("commitment.execute", hidden_commitment["id"], actor_role="pm", requested_by=HIDDEN_PM_LOGIN)
        self.c.approve(approval["id"], approver="practice.bootstrap", approver_role="owner")
        self.c.execute(approval["id"], actor=HIDDEN_PM_LOGIN)
        hidden = self.receive(hidden=True, number="HIDDEN-999", commitment_id=hidden_commitment["id"], amount="11111.10")
        visible = self.receive()
        self.ap.match(visible["id"], ACCOUNTANT_LOGIN)
        result = self.contract.invoice(self.accountant, visible["id"])
        self.assertTrue(result["duplicateBlocking"])
        self.assertNotIn(hidden["id"], json.dumps(result))
        self.assertNotIn("Hidden", json.dumps(result))

    def test_receipt_audit_rejects_attacker_rehashed_invoice(self):
        inv = self.receive()
        self.drop_guards("ap_invoices")
        self.c.db.execute("UPDATE ap_invoices SET amount='123.45' WHERE id=?", (inv["id"],))
        changed = self.c.db.one("SELECT * FROM ap_invoices WHERE id=?", (inv["id"],))
        self.c.db.execute("UPDATE ap_invoices SET content_hash=? WHERE id=?", (self.ap._content_hash(changed), inv["id"]))
        with self.assertRaises(APRefusal) as failure:
            self.contract.invoice(self.accountant, inv["id"])
        self.assertEqual((failure.exception.status, failure.exception.code), (422, "invalid_record"))

    def test_unrecorded_match_references_cannot_escape_a_received_invoice(self):
        inv = self.receive()
        hidden = self.c.bills.get(self.records["hidden_bill_id"])
        self.drop_guards("ap_invoices")
        self.c.db.execute("UPDATE ap_invoices SET match_approval_id=?,matched_bill_id=?,matched_by=? WHERE id=?",
                          (hidden["business_approval_id"], hidden["id"], HIDDEN_ACCOUNTANT_LOGIN, inv["id"]))
        with self.assertRaises(APRefusal) as failure:
            self.contract.invoice(self.accountant, inv["id"])
        self.assertEqual((failure.exception.status, failure.exception.code), (422, "invalid_record"))

    def test_untrusted_collection_and_unaudited_terms_refuse_with_safe_fields(self):
        with self.assertRaises(APRefusal) as failure:
            self.contract.read(self.accountant, ["invoices"])
        self.assertEqual((failure.exception.status, failure.exception.code), (422, "unknown_collection"))
        commitment = self.c.commitments.get(self.records["prep_commitment_id"])
        self.c.db.execute("INSERT INTO ap_supplier_terms(supplier_id,days,version,set_by,set_at) VALUES (?,99,1,?,?)",
                          (commitment["supplier_id"], "forged-terms", "2026-10-14T00:00:00Z"))
        with self.assertRaises(APRefusal) as failure:
            self.contract.preparation(self.accountant, commitment["id"])
        self.assertEqual((failure.exception.status, failure.exception.code), (422, "invalid_record"))

    def test_unrecorded_evidence_metadata_and_hash_are_refused(self):
        revision_id = self.records["visible_invoice_evidence_revision_ids"][0]
        document_id = self.c.evidence.revision(revision_id)["document_id"]
        self.c.db.execute("UPDATE documents SET title='Forged source title' WHERE id=?", (document_id,))
        with self.assertRaises(APRefusal) as failure:
            self.contract.read(self.accountant, "invoice-evidence")
        self.assertEqual(failure.exception.code, "invalid_record")

    def test_forged_match_attempt_with_rehashed_result_cannot_supply_a_packet(self):
        inv = self.receive()
        self.ap.match(inv["id"], ACCOUNTANT_LOGIN)
        self.drop_guards("ap_invoice_matches")
        row = self.c.db.one("SELECT * FROM ap_invoice_matches WHERE invoice_id=?", (inv["id"],))
        facts = json.loads(row["result_json"])
        facts["bill"]["amount_due"] = "999.99"
        self.c.db.execute("UPDATE ap_invoice_matches SET result_json=?,result_hash=? WHERE id=?", (canonical_json(facts), hash_json(facts), row["id"]))
        with self.assertRaises(APRefusal) as failure:
            self.contract.invoice(self.accountant, inv["id"])
        self.assertEqual(failure.exception.code, "invalid_record")

    def test_genuine_revision_changes_source_version_and_preserves_readable_history(self):
        inv = self.receive()
        first = self.contract.invoice(self.accountant, inv["id"])
        revised = self.ap.revise_invoice(inv["id"], ACCOUNTANT_LOGIN, reason="Synthetic replacement", amount="11200.00")
        second = self.contract.invoice(self.accountant, revised["id"])
        self.assertEqual(second["amountCents"], 1120000)
        self.assertEqual(second["invoiceVersion"], 2)
        self.assertNotEqual(first["version"], second["version"])

    def test_genuine_matched_invoice_revision_retains_original_decision_history(self):
        inv = self.receive()
        approval = self.approval(inv)
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        self.c.execute(approval["id"], actor=ACCOUNTANT_LOGIN)
        self.ap.revise_invoice(inv["id"], ACCOUNTANT_LOGIN, reason="Synthetic supplier replacement", amount="11200.00")
        current = self.contract.invoice(self.accountant, inv["id"])
        self.assertEqual((current["status"], current["invoiceVersion"]), ("received", 2))
        self.assertIsNone(current["match"])
        self.assertEqual(current["matchApprovalId"], approval["id"])
        original = self.contract.packet(self.reviewer, approval["id"])
        self.assertEqual(original["effectiveStatus"], "consumed")
        self.assertEqual(original["boundFacts"]["amountCents"], 1111110)
        self.assertEqual(original["currentFacts"]["amountCents"], 1120000)

    def test_genuine_matched_invoice_reopen_proves_next_version_and_computation(self):
        inv = self.receive()
        approval = self.approval(inv)
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        self.c.execute(approval["id"], actor=ACCOUNTANT_LOGIN)
        self.c.bills.void(self.records["draft_bill_id"], actor=ACCOUNTANT_LOGIN, reason="Synthetic replacement certification")
        self.ap.match(inv["id"], ACCOUNTANT_LOGIN)
        current = self.contract.invoice(self.accountant, inv["id"])
        self.assertEqual((current["status"], current["invoiceVersion"]), ("received", 2))
        self.assertEqual(current["match"]["status"], "exception")
        self.assertIn("no_certified_bill", {exception["code"] for exception in current["match"]["exceptions"]})
        self.assertEqual(self.contract.packet(self.reviewer, approval["id"])["effectiveStatus"], "consumed")

    def test_genuine_duplicate_review_survives_nonduplicate_fact_revision(self):
        self.receive()
        inv = self.receive(number="SYN-101", evidence_index=1)
        self.ap.clear_duplicate_flag(inv["id"], "Reviewed genuine separate source", REVIEWER_LOGIN)
        self.ap.revise_invoice(inv["id"], ACCOUNTANT_LOGIN, reason="Reviewed due date", due_date="2026-12-01")
        result = self.contract.invoice(self.accountant, inv["id"])
        self.assertTrue(result["possibleDuplicate"])
        self.assertFalse(result["duplicateBlocking"])

    def test_evidence_revision_changes_current_indicator_and_version(self):
        inv = self.receive()
        first = self.contract.invoice(self.accountant, inv["id"])
        self.c.evidence.add_revision(document_id=inv["evidence_document_id"], content="Synthetic changed PDF", actor=ACCOUNTANT_LOGIN)
        second = self.contract.invoice(self.accountant, inv["id"])
        self.assertFalse(second["evidence"]["isCurrent"])
        self.assertNotEqual(first["version"], second["version"])
        self.assertIn("evidence_stale", {reason["code"] for reason in second["blockedReasons"]})

    def test_packet_shows_changed_document_revision_without_lifecycle_writes(self):
        inv = self.receive()
        approval = self.approval(inv)
        revision = self.c.evidence.add_revision(document_id=inv["evidence_document_id"], content="Synthetic newer invoice source", actor=ACCOUNTANT_LOGIN)
        before = self.c.db.conn.total_changes
        packet = self.contract.packet(self.reviewer, approval["id"])
        self.assertEqual(packet["effectiveStatus"], "stale")
        self.assertIn({"field": "evidenceRevisionId", "before": inv["evidence_revision_id"], "after": revision["id"]}, packet["changes"])
        self.assertEqual(self.c.db.conn.total_changes, before)
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "pending")

    def test_packet_shows_bill_lifecycle_source_change(self):
        inv = self.receive()
        approval = self.approval(inv)
        bill_approval = self.c.request_approval("bill.approve", self.records["draft_bill_id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(bill_approval["id"], approver=PM_LOGIN, approver_role="pm")
        packet = self.contract.packet(self.reviewer, approval["id"])
        self.assertEqual(packet["effectiveStatus"], "stale")
        self.assertIn({"field": "billStatus", "before": "draft", "after": "approved"}, packet["changes"])
        self.assertEqual(packet["availableActions"], [])

    def test_wrong_operation_approval_has_no_match_packet_fallthrough(self):
        bill_id = self.records["draft_bill_id"]
        approval = self.c.request_approval("bill.approve", bill_id, actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        with self.assertRaises(APRefusal) as failure:
            self.contract.packet(self.accountant, approval["id"])
        self.assertEqual(failure.exception.status, 404)
        with self.assertRaises(APRefusal) as failure:
            self.contract.authorize(self.accountant, "payment.release", bill_id)
        self.assertEqual(failure.exception.code, "unsupported_action")

    def test_cursors_bind_current_person_filters_scope_and_collection(self):
        first = self.contract.read(self.accountant, "invoice-evidence", top=1)
        second = self.contract.read(self.accountant, "invoice-evidence", top=1, cursor=first["nextCursor"])
        self.assertNotEqual(first["value"][0]["id"], second["value"][0]["id"])
        for principal, collection, params in ((self.reviewer, "invoice-evidence", {"top": 1}), (self.accountant, "invoice-evidence", {"top": 2}),
                                              (self.accountant, "invoices", {"top": 1})):
            with self.assertRaises(APRefusal) as failure:
                self.contract.read(principal, collection, cursor=first["nextCursor"], **params)
            self.assertEqual(failure.exception.code, "invalid_cursor")
        self.c.plugin("people").end_membership(ACCOUNTANT_LOGIN, self.records["visible_project_ids"][0], reason="Synthetic reassignment", actor="practice.bootstrap")
        with self.assertRaises(APRefusal) as failure:
            self.contract.read(self.accountant, "invoice-evidence", top=1, cursor=first["nextCursor"])
        self.assertEqual(failure.exception.code, "invalid_cursor")

    def test_query_shape_limits_and_unregistered_principals_fail_safely(self):
        for params in ({"top": True}, {"top": 0}, {"top": 101}, {"search": "x" * 201}, {"search": "\n"}, {"status": "unknown"}, {"cursor": "forged"}):
            with self.subTest(params=params), self.assertRaises(APRefusal) as failure:
                self.contract.read(self.accountant, "invoices", **params)
            self.assertEqual(failure.exception.status, 422)
        with self.assertRaises(APRefusal) as failure:
            self.contract.read("practice.accountant", "invoices")
        self.assertEqual(failure.exception.status, 401)

    def test_reads_are_zero_write_and_signed_versions_are_stable_and_person_bound(self):
        inv = self.receive()
        approval = self.approval(inv)
        before = (self.c.db.conn.total_changes, tuple(self.c.db.conn.iterdump()), len(self.c.provider.submissions))
        for person in (self.accountant, self.pm, self.reviewer):
            for collection in ("invoices", "invoice-evidence", "match-approvals"):
                self.contract.read(person, collection)
            self.contract.preparation(person, self.records["prep_commitment_id"])
            self.contract.invoice(person, inv["id"])
            self.contract.packet(person, approval["id"])
        self.assertEqual(before, (self.c.db.conn.total_changes, tuple(self.c.db.conn.iterdump()), len(self.c.provider.submissions)))
        first = self.contract.version(self.accountant, inv["id"], "invoice")
        self.assertEqual(first, self.contract.version(self.accountant, inv["id"], "invoice"))
        self.assertNotEqual(first, self.contract.version(self.reviewer, inv["id"], "invoice"))

    def test_draft_predecessor_is_blocked_and_posted_predecessor_quantities_are_true(self):
        commitment_id = self.records["visible_commitment_ids"][0]
        blocked = self.contract.preparation(self.accountant, commitment_id)
        self.assertNotIn("bill.prepare", blocked["availableActions"])
        self.assertIn("draft_predecessor", {reason["code"] for reason in blocked["blockedReasons"]})
        bill_id = self.records["draft_bill_id"]
        ap = self.c.request_approval("bill.approve", bill_id, actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(ap["id"], approver=PM_LOGIN, approver_role="pm")
        self.c.post_bill(bill_id, actor=ACCOUNTANT_LOGIN, actor_role="accountant", period_id="2026-10")
        prep = self.contract.preparation(self.accountant, commitment_id)
        self.assertEqual(prep["priorBill"]["status"], "posted")
        self.assertEqual(prep["lines"][0]["priorInstalledCents"], 1234567)
        self.assertIn("bill.prepare", prep["availableActions"])

    def test_stored_material_preparation_does_not_offer_unsupported_intake(self):
        commitment = self.c.commitments.get(self.records["prep_commitment_id"])
        document = self.c.evidence.register_document(project_id=commitment["project_id"], kind="stored_material_evidence",
                                                    title="Synthetic stored material source", actor=ACCOUNTANT_LOGIN)
        revision = self.c.evidence.add_revision(document_id=document["id"], content="Synthetic storage title/control/location", actor=ACCOUNTANT_LOGIN)
        self.c.bills.add_stored_material(commitment_id=commitment["id"], sov_line_id=commitment["sov"][0]["id"],
                                        description="Synthetic stored material", eligible_amount="100.00", location="Synthetic yard",
                                        evidence_hash=revision["content_hash"], actor=ACCOUNTANT_LOGIN)
        prep = self.contract.preparation(self.accountant, commitment["id"])
        self.assertEqual(prep["availableActions"], [])
        self.assertIn("unsupported_stored_material", {reason["code"] for reason in prep["blockedReasons"]})


if __name__ == "__main__":
    unittest.main()
