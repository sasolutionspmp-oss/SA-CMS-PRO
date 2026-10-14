"""Pure AP preparation agrees with the existing recorded domain actions."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from apps.cipher.core.ids import hash_json
from apps.cipher.domain.ap_intake import APIntakeError, DuplicateInvoiceError
from apps.cipher.domain.bills import BillError
from apps.cipher.tests.test_ap_intake import World


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.c = self.w.c
        self.addCleanup(self.c.db.close)

    def snapshot(self, *, changes=True):
        return {
            "database": hash_json(list(self.c.db.conn.iterdump())),
            "changes": self.c.db.conn.total_changes if changes else None,
            "provider_submissions": list(self.c.provider.submissions),
            "provider_transfers": dict(self.c.provider.transfers),
        }

    def certify_input(self, value="30000"):
        return {"commitment_id": self.w.cid, "period_id": "P1",
                "installed": [{"sov_line_id": self.w.line(1), "cumulative_installed": value}]}

    def receive_input(self, number="PREP-001", amount="27000"):
        _, rev = self.w.pdf(number)
        return {"supplier_id": self.w.supplier["id"], "invoice_number": number,
                "invoice_date": "2026-10-15", "amount": amount, "evidence_hash": rev["content_hash"],
                "project_id": self.w.pid, "commitment_id": self.w.cid}

    def stored_lot(self, amount="10000"):
        doc, rev = self.w.pdf("stored material", kind="stored_material_evidence")
        lot = self.c.bills.add_stored_material(commitment_id=self.w.cid, sov_line_id=self.w.line(1),
                                              description="Synthetic stored sheet pile", eligible_amount=amount,
                                              evidence_hash=rev["content_hash"], location="Synthetic yard", actor="pm")
        return doc, lot

    def test_certification_review_is_zero_write_and_agrees_with_draft(self):
        args = self.certify_input()
        before = self.snapshot()
        plan = self.c.bills.certification_preflight(**args)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(plan["content_hash"], hash_json(plan["content"]))
        self.assertEqual(plan["content"]["amount_due"], "27000.00")
        draft = self.c.bills.certify(**args, actor="accountant")
        for field in ("commitment_id", "period_id", "sequence", "cumulative_installed", "cumulative_stored",
                      "cumulative_gross", "cumulative_retainage", "cumulative_net", "prior_net", "amount_due",
                      "retainage_rate", "sov_hash", "content_hash", "retainage_this_period", "installed_this_period",
                      "stored_added_this_period", "stored_transferred_this_period"):
            expected = plan["content"].get(field, plan.get(field))
            self.assertEqual(draft[field], expected, field)
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals WHERE source_id=?", (draft["id"],)), 0)

    def test_certification_refusals_are_zero_write(self):
        bad = [self.certify_input("60000.01"), self.certify_input("0"),
               {**self.certify_input(), "installed": [{"sov_line_id": "missing", "cumulative_installed": "1"}]},
               {**self.certify_input(), "installed": self.certify_input()["installed"] * 2},
               {**self.certify_input(), "period_id": "missing"}]
        for args in bad:
            with self.subTest(args=args):
                before = self.snapshot()
                with self.assertRaises((BillError, RuntimeError)):
                    self.c.bills.certification_preflight(**args)
                self.assertEqual(before, self.snapshot())

    def test_current_draft_is_a_zero_write_certification_refusal(self):
        self.w.certify({1: "10000"})
        before = self.snapshot()
        with self.assertRaisesRegex(BillError, "still a draft"):
            self.c.bills.certification_preflight(**self.certify_input())
        self.assertEqual(before, self.snapshot())

    def test_certification_recalculates_after_a_predecessor_is_created(self):
        args = self.certify_input()
        preview = self.c.bills.certification_preflight(**args)
        first = self.w.certify({1: "10000"})
        self.w.post(first["id"])
        current = self.c.bills.certification_preflight(**args)
        self.assertNotEqual(preview["source_facts"], current["source_facts"])
        self.assertEqual(current["content"]["prior_net"], "9000.00")
        second = self.c.bills.certify(**args, actor="accountant")
        self.assertEqual(second["amount_due"], "18000.00")
        self.assertEqual(second["content_hash"], current["content_hash"])

    def test_stored_material_and_transfer_review_agrees_with_reservations(self):
        _, lot = self.stored_lot()
        args = {**self.certify_input("5000"), "transfers": [{"lot_id": lot["id"], "amount": "2000"}]}
        before = self.snapshot()
        plan = self.c.bills.certification_preflight(**args)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(plan["content"]["cumulative_stored"], "8000.00")
        self.assertEqual(plan["stored_added_this_period"], "10000.00")
        self.assertEqual(plan["stored_transferred_this_period"], "2000.00")
        self.assertEqual(plan["lot_updates"], [{"lot_id": lot["id"], "remaining_amount": "8000.00"}])
        draft = self.c.bills.certify(**args, actor="accountant")
        self.assertEqual(draft["content_hash"], plan["content_hash"])
        self.assertEqual(draft["amount_due"], "11700.00")
        current_lot = self.c.bills.lot(lot["id"])
        self.assertEqual((current_lot["remaining_amount"], current_lot["billed_bill_id"]), ("8000.00", draft["id"]))
        self.assertEqual(draft["lines"][0]["stored_added"], "10000.00")
        self.assertEqual(draft["lines"][0]["stored_transferred"], "2000.00")

    def test_frozen_excluded_lot_still_binds_the_cap_and_source_version(self):
        doc, lot = self.stored_lot()
        args = self.certify_input("5000")
        first = self.c.bills.certification_preflight(**args)
        self.w.revise_pdf(doc, "new synthetic stored evidence")
        before = self.snapshot()
        current = self.c.bills.certification_preflight(**args)
        self.assertEqual(before, self.snapshot())
        self.assertNotEqual(first["source_facts"], current["source_facts"])
        self.assertEqual(current["content"]["excluded_lots"], [lot["id"]])
        self.assertEqual(current["content"]["cumulative_stored"], "0.00")
        with self.assertRaisesRegex(BillError, "awaiting evidence confirmation"):
            self.c.bills.certification_preflight(**self.certify_input("55000"))
        self.assertEqual(before, self.snapshot())
        draft = self.c.bills.certify(**args, actor="accountant")
        self.assertEqual(draft["content_hash"], current["content_hash"])
        self.assertIsNone(self.c.bills.lot(lot["id"])["billed_bill_id"])

    def test_transfer_refusals_are_zero_write(self):
        _, lot = self.stored_lot()
        base = self.certify_input("5000")
        for transfers in ([{"lot_id": lot["id"], "amount": "10000.01"}],
                          [{"lot_id": lot["id"], "amount": "6000"}],
                          [{"lot_id": "missing", "amount": "1"}],
                          [{"lot_id": lot["id"], "amount": "1"}] * 2):
            before = self.snapshot()
            with self.assertRaises(BillError):
                self.c.bills.certification_preflight(**base, transfers=transfers)
            self.assertEqual(before, self.snapshot())

    def test_certification_failure_restores_reserved_lots_and_transfers(self):
        _, lot = self.stored_lot()
        args = {**self.certify_input("5000"), "transfers": [{"lot_id": lot["id"], "amount": "2000"}]}
        self.assert_caught_preparation_failure("bill.certified", lambda: self.c.bills.certify(**args, actor="accountant"))

    def test_invoice_receive_review_is_zero_write_and_agrees_with_record(self):
        args = self.receive_input()
        before = self.snapshot()
        plan = self.w.ap.receive_preflight(**args)
        self.assertEqual(before, self.snapshot())
        invoice = self.w.ap.receive_invoice(**args, actor="accountant")
        for field, expected in plan["content"].items():
            actual = invoice["lines"] if field == "lines" else invoice[field]
            self.assertEqual(actual, expected, field)
        self.assertEqual(invoice["possible_duplicate"], plan["possible_duplicate"])
        self.assertEqual(invoice["duplicate_of"], plan["possible_duplicate_of"])
        self.assertEqual(invoice["due_date"], "2026-11-14")
        self.assertEqual(invoice["status"], "received")

    def test_receive_line_normalization_agrees_with_exact_effect(self):
        args = self.receive_input(amount="27000.01")
        args["lines"] = [{"description": "Synthetic installed work", "amount": "27000.01",
                          "quantity": "1", "unit_price": "27000.01", "sov_line_id": self.w.line(1)}]
        args["due_date"] = "2026-10-30"
        args["service_period_start"], args["service_period_end"] = "2026-10-01", "2026-10-15"
        before = self.snapshot()
        plan = self.w.ap.receive_preflight(**args)
        self.assertEqual(before, self.snapshot())
        invoice = self.w.ap.receive_invoice(**args, actor="accountant")
        self.assertEqual(invoice["lines"], plan["content"]["lines"])
        self.assertEqual(invoice["amount"], "27000.01")
        self.assertIsNone(invoice["terms_days"])
        self.assertEqual(invoice["due_date"], "2026-10-30")

    def test_duplicate_and_invalid_intake_reviews_are_zero_write(self):
        args = self.receive_input()
        self.w.ap.receive_invoice(**args, actor="accountant")
        for change, error in (({}, DuplicateInvoiceError), ({"invoice_number": "bad", "amount": "0"}, APIntakeError),
                              ({"invoice_number": "bad", "evidence_hash": "missing"}, APIntakeError),
                              ({"invoice_number": "bad", "due_date": "2026-10-01"}, APIntakeError)):
            before = self.snapshot()
            with self.assertRaises(error):
                self.w.ap.receive_preflight(**{**args, **change})
            self.assertEqual(before, self.snapshot())

    def test_receive_review_binds_current_terms_and_near_duplicates(self):
        args = self.receive_input()
        preview = self.w.ap.receive_preflight(**args)
        self.w.ap.set_terms(self.w.supplier["id"], 45, "controller")
        self.w.receive("OTHER-NUMBER", "27000")
        before = self.snapshot()
        current = self.w.ap.receive_preflight(**args)
        self.assertEqual(before, self.snapshot())
        self.assertNotEqual(preview["source_facts"], current["source_facts"])
        self.assertEqual(current["content"]["due_date"], "2026-11-29")
        self.assertTrue(current["possible_duplicate"])
        invoice = self.w.ap.receive_invoice(**args, actor="accountant")
        self.assertEqual(invoice["due_date"], current["content"]["due_date"])
        self.assertEqual(invoice["duplicate_of"], current["possible_duplicate_of"])

    def test_terms_review_matches_audited_history_and_default(self):
        before = self.snapshot()
        default = self.w.ap.audited_terms(self.w.supplier["id"])
        self.assertEqual(before, self.snapshot())
        self.assertEqual((default["days"], default["version"], default["configured"]), (30, 0, False))
        self.w.ap.set_terms(self.w.supplier["id"], 45, "controller")
        self.w.ap.set_terms(self.w.supplier["id"], 10, "another controller")
        before = self.snapshot()
        terms = self.w.ap.audited_terms(self.w.supplier["id"])
        self.assertEqual(before, self.snapshot())
        self.assertEqual((terms["days"], terms["version"], terms["configured"]), (10, 2, True))
        self.assertEqual(terms["row"]["set_by"], "another controller")
        self.assertIsInstance(terms["audit_seq"], int)
        self.assertTrue(terms["audit_entry_hash"])

    def test_intake_review_refuses_terms_rewritten_without_an_audit_event(self):
        args = self.receive_input()
        self.w.ap.set_terms(self.w.supplier["id"], 45, "controller")
        self.c.db.execute("UPDATE ap_supplier_terms SET days=1, version=version+1 WHERE supplier_id=?", (self.w.supplier["id"],))
        before = self.snapshot()
        with self.assertRaisesRegex(APIntakeError, "terms"):
            self.w.ap.receive_preflight(**args)
        self.assertEqual(before, self.snapshot())
        with self.assertRaises(APIntakeError):
            self.w.ap.terms(self.w.supplier["id"])

    def test_deleted_terms_history_cannot_be_replaced_with_the_default(self):
        args = self.receive_input()
        self.w.ap.set_terms(self.w.supplier["id"], 45, "controller")
        self.c.db.execute("DROP TRIGGER ap_supplier_terms_no_delete")
        self.c.db.execute("DELETE FROM ap_supplier_terms WHERE supplier_id=?", (self.w.supplier["id"],))
        before = self.snapshot()
        with self.assertRaisesRegex(APIntakeError, "terms"):
            self.w.ap.receive_preflight(**args)
        self.assertEqual(before, self.snapshot())

    def test_unrecorded_terms_cannot_supply_an_intake_due_date(self):
        args = self.receive_input()
        self.c.db.execute("INSERT INTO ap_supplier_terms (supplier_id, days, version, set_by, set_at) VALUES (?,1,1,'controller','2026-10-14T00:00:00+00:00')",
                          (self.w.supplier["id"],))
        before = self.snapshot()
        with self.assertRaisesRegex(APIntakeError, "terms"):
            self.w.ap.receive_preflight(**args)
        self.assertEqual(before, self.snapshot())

    def test_terms_history_versions_cannot_be_skipped_or_replayed(self):
        self.w.ap.set_terms(self.w.supplier["id"], 45, "controller")
        self.c.audit.record("controller", "ap_intake.terms_set", "party", self.w.supplier["id"],
                            {"days": 1, "version": 1, "previous_days": 45})
        before = self.snapshot()
        with self.assertRaisesRegex(APIntakeError, "terms"):
            self.w.ap.audited_terms(self.w.supplier["id"])
        self.assertEqual(before, self.snapshot())

    def test_terms_creator_and_broken_audit_are_refused(self):
        self.w.ap.set_terms(self.w.supplier["id"], 45, "controller")
        self.c.db.execute("DROP TRIGGER ap_supplier_terms_versioned")
        self.c.db.execute("UPDATE ap_supplier_terms SET set_by='different person' WHERE supplier_id=?", (self.w.supplier["id"],))
        before = self.snapshot()
        with self.assertRaises(APIntakeError):
            self.w.ap.audited_terms(self.w.supplier["id"])
        self.assertEqual(before, self.snapshot())
        with patch.object(self.c.audit, "verify_chain", return_value={"ok": False}):
            with self.assertRaisesRegex(APIntakeError, "audit chain"):
                self.w.ap.audited_terms(self.w.supplier["id"])

    def test_receive_review_refuses_superseded_evidence_without_writes(self):
        args = self.receive_input()
        document = self.c.db.one("SELECT document_id FROM document_revisions WHERE content_hash=?", (args["evidence_hash"],))
        self.c.evidence.add_revision(document_id=document["document_id"], content=b"new synthetic invoice", actor="accountant")
        before = self.snapshot()
        with self.assertRaisesRegex(APIntakeError, "superseded"):
            self.w.ap.receive_preflight(**args)
        self.assertEqual(before, self.snapshot())

    def test_match_review_is_zero_write_for_exact_match_and_exception(self):
        bill = self.w.certify({1: "30000"})
        for number, amount, status in (("MATCH-001", "27000", "matched"), ("MATCH-002", "100", "exception")):
            invoice = self.w.receive(number, amount)
            before = self.snapshot()
            preview = self.w.ap.match_preflight(invoice["id"])
            self.assertEqual(before, self.snapshot())
            self.assertEqual(preview["facts"]["status"], status)
            result = self.w.ap.match(invoice["id"], "accountant")
            self.assertEqual(preview["result_hash"], result["result_hash"])
            self.assertEqual(preview["facts"], {key: result[key] for key in preview["facts"]})
            if status == "matched":
                self.assertEqual(result["bill"]["id"], bill["id"])

    def test_reopening_match_review_is_zero_write_and_agrees_with_effect(self):
        bill = self.w.certify({1: "30000"})
        invoice = self.w.receive("REOPEN-001", "27000")
        self.w.match_and_execute(invoice["id"])
        self.c.bills.void(bill["id"], actor="pm", reason="synthetic replacement certification")
        replacement = self.w.certify({1: "30000"})
        before = self.snapshot()
        preview = self.w.ap.match_preflight(invoice["id"])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(preview["reopen_reason"], "bill_void")
        self.assertEqual(preview["facts"]["invoice"]["version"], 2)
        self.assertEqual(preview["facts"]["bill"]["id"], replacement["id"])
        result = self.w.ap.match(invoice["id"], "accountant")
        self.assertEqual(preview["result_hash"], result["result_hash"])
        self.assertEqual(self.w.ap.invoice(invoice["id"])["version"], 2)

    def test_rejected_match_review_is_zero_write(self):
        invoice = self.w.receive("REJECT-001", "27000")
        self.w.ap.reject_invoice(invoice["id"], "synthetic wrong invoice", "accountant")
        before = self.snapshot()
        with self.assertRaisesRegex(APIntakeError, "rejected"):
            self.w.ap.match_preflight(invoice["id"])
        self.assertEqual(before, self.snapshot())

    def test_all_preparation_reviews_work_on_a_query_only_connection(self):
        args = self.receive_input()
        self.w.certify({1: "30000"})
        invoice = self.w.receive("READONLY-MATCH-001", "100")
        with self.c.db._lock:
            self.c.db._set_query_only(True)
        before = self.snapshot()
        try:
            self.w.ap.receive_preflight(**args)
            self.w.ap.match_preflight(invoice["id"])
            with self.assertRaisesRegex(BillError, "still a draft"):
                self.c.bills.certification_preflight(**self.certify_input())
            self.assertEqual(before, self.snapshot())
        finally:
            with self.c.db._lock:
                self.c.db._set_query_only(False)

    def test_competing_certifications_produce_one_draft_without_partial_effects(self):
        args = self.certify_input()

        def prepare():
            try:
                return self.c.bills.certify(**args, actor="accountant")
            except BillError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: prepare(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM bills WHERE commitment_id=?", (self.w.cid,)), 1)
        events = [event for event in self.c.audit.entries(entity_type="bill") if event["action"] == "bill.certified"]
        self.assertEqual(len(events), 1)
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_competing_intakes_produce_one_invoice_and_one_original_receipt(self):
        args = self.receive_input()

        def receive():
            try:
                return self.w.ap.receive_invoice(**args, actor="accountant")
            except DuplicateInvoiceError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: receive(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM ap_invoices"), 1)
        events = [event for event in self.c.audit.entries(entity_type="ap_invoice") if event["action"] == "ap_intake.invoice_received"]
        self.assertEqual(len(events), 1)
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_certification_failure_rolls_back_when_an_outer_caller_catches_it(self):
        self.assert_caught_preparation_failure("bill.certified", lambda: self.c.bills.certify(**self.certify_input(), actor="accountant"))

    def test_intake_failure_rolls_back_when_an_outer_caller_catches_it(self):
        args = self.receive_input()
        self.assert_caught_preparation_failure("ap_intake.invoice_received", lambda: self.w.ap.receive_invoice(**args, actor="accountant"))

    def test_match_failure_rolls_back_when_an_outer_caller_catches_it(self):
        self.w.certify({1: "30000"})
        invoice = self.w.receive("ATOMIC-MATCH-001", "27000")
        self.assert_caught_preparation_failure("ap_intake.match_computed", lambda: self.w.ap.match(invoice["id"], "accountant"))

    def test_reopened_match_failure_rolls_back_its_version_and_audit(self):
        bill = self.w.certify({1: "30000"})
        invoice = self.w.receive("ATOMIC-REOPEN-001", "27000")
        self.w.match_and_execute(invoice["id"])
        self.c.bills.void(bill["id"], actor="pm", reason="synthetic replacement certification")
        self.w.certify({1: "30000"})
        self.assert_caught_preparation_failure("ap_intake.match_computed", lambda: self.w.ap.match(invoice["id"], "accountant"))

    def assert_caught_preparation_failure(self, action, call):
        original = self.c.audit.record

        def record_then_fail(actor, code, entity_type, entity_id, payload=None):
            result = original(actor, code, entity_type, entity_id, payload)
            if code == action:
                raise RuntimeError("injected preparation failure")
            return result

        before = self.snapshot(changes=False)
        with self.c.db.transaction():
            with patch.object(self.c.audit, "record", side_effect=record_then_fail):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    call()
            self.assertEqual(before, self.snapshot(changes=False))
        self.assertEqual(before, self.snapshot(changes=False))


if __name__ == "__main__":
    unittest.main()
