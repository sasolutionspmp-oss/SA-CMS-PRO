"""Runnable isolated commercial72 prototype checks; no main repository edits."""
import copy
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from apps.cipher import service
from apps.cipher.core.db import SCHEMA_CATALOG, WriteAuthorityError
from apps.cipher.domain import commercial
from apps.cipher.core.ids import canonical_json
from apps.cipher.commercial_practice_fixture import (make_commercial_practice_fixture, ESTIMATOR_LOGIN, REVIEWER_LOGIN, PM_LOGIN,
                                         BOOTSTRAP_LOGIN, ACCOUNTANT_LOGIN)

_PREFIX = copy.deepcopy(SCHEMA_CATALOG[:71])
commercial.register_commercial_schema()
assert SCHEMA_CATALOG[:71] == _PREFIX

class CommercialDomainTests(unittest.TestCase):
    def setUp(self):
        self.c = make_commercial_practice_fixture()
        self.addCleanup(self.c.db.close)
        if "commercial" not in self.c._plugins:
            self.c.register_plugin("commercial", commercial.Plugin(self.c))
        self.domain = self.c.plugin("commercial")
        self.project = self.c.commercial_practice_records["project_id"]
        self.supplier = self.c.commercial_practice_records["supplier_id"]
        self.document = self.c.evidence.register_document(project_id=self.project, kind="drawing", title="Synthetic isolated E-101 manual source", actor=ESTIMATOR_LOGIN)
        self.revision = self.c.evidence.add_revision(document_id=self.document["id"], content="Synthetic E-101 manual source rev1", actor=ESTIMATOR_LOGIN)
        self.body = {"documentRevisionId": self.revision["id"], "lines": [
            {"description": "Manual conduit", "quantity": "10.125000", "unit": "LF", "unitPriceCents": 2575, "sourceLocator": "E-101 / page2 / conduit run", "costCode": "26-100"},
            {"description": "Manual junction boxes", "quantity": "3", "unit": "EA", "unitPriceCents": 5000, "sourceLocator": "E-101 / page2 / detail3", "costCode": "26-110"}],
            "priceBookRef": "Synthetic fixed practice rate v1", "inclusions": ["Conduit", "Junction boxes"], "exclusions": ["Excavation"],
            "contingencyRate": "0", "measurementBasis": "Manual entry from owned drawing/page; geometry and calibration unverified"}
        self.source = self.domain.create(self.project, self.body, actor=ESTIMATOR_LOGIN)
        self.package = self.domain.declare_package(self.project, self.supplier, "Synthetic electrical subcontract package", "0.10", actor=PM_LOGIN, reason="Explicit synthetic single-package terms")

    def snapshot(self):
        return tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes, tuple(self.c.provider.submissions), self.c.ledger.trial_balance()["journal_count"]

    def accept(self):
        approval = self.c.request_approval("estimate.approve", self.source["estimateId"], actor_role="estimator", requested_by=ESTIMATOR_LOGIN)
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="estimator")
        self.c.execute(approval["id"], actor=ESTIMATOR_LOGIN)
        return approval

    def revise(self, *, bad_previous=None):
        drawing = self.c.evidence.add_revision(document_id=self.document["id"], content="Synthetic E-101 manual source rev2", actor=ESTIMATOR_LOGIN)
        body = copy.deepcopy(self.body)
        body["documentRevisionId"] = drawing["id"]
        body["lines"][0]["quantity"] = "12.625"
        for line, old in zip(body["lines"], self.source["lines"]):
            line["previousLineId"] = old["estimate_line_id"]
        if bad_previous is not None:
            body["lines"][0]["previousLineId"] = bad_previous
        body["removedExclusions"] = []
        return body

    def handoff(self):
        self.accept()
        return self.domain.prepare_handoff(self.source["estimateId"], self.package["id"], actor=ESTIMATOR_LOGIN)

    def test_quantities_rates_and_manual_page_costcode_facts_are_exact(self):
        self.assertEqual(self.source["baseline"]["total"], "410.72")
        line = self.source["lines"][0]
        self.assertEqual(line["engine_line"]["quantity"], "10.125")
        self.assertEqual(line["engine_line"]["unit_price"], "25.75")
        self.assertEqual(line["engine_line"]["amount"], "260.72")
        self.assertEqual(line["source_locator"], "E-101 / page2 / conduit run")
        self.assertEqual(line["cost_code"], "26-100")
        self.assertEqual(line["method"], "manual_entry")
        self.assertIs(line["verified_geometry"], False)

    def test_creation_preflight_is_zero_write_and_shared_engine_calculation(self):
        doc = self.c.evidence.register_document(project_id=self.project, kind="drawing", title="Synthetic different quantity source", actor=ESTIMATOR_LOGIN)
        rev = self.c.evidence.add_revision(document_id=doc["id"], content="Synthetic different source", actor=ESTIMATOR_LOGIN)
        body = copy.deepcopy(self.body)
        body["documentRevisionId"] = rev["id"]
        body["lines"][0]["description"] = "Manual independent cable"
        body["lines"][1]["description"] = "Manual independent connectors"
        before = self.snapshot()
        plan = self.domain.create_preflight(self.project, body, actor=ESTIMATOR_LOGIN)
        self.assertEqual(plan["estimatePlan"]["total"], "410.72")
        self.assertEqual(before, self.snapshot())

    def test_accountant_owner_wildcard_and_pm_cannot_supply_estimator_duty(self):
        before = self.snapshot()
        for actor in (ACCOUNTANT_LOGIN, BOOTSTRAP_LOGIN, PM_LOGIN):
            with self.subTest(actor=actor), self.assertRaises(commercial.CommercialError):
                self.domain.create_preflight(self.project, self.body, actor=actor)
        self.assertEqual(before, self.snapshot())

    def test_numeric_alias_and_extra_method_chooser_are_refused_before_writes(self):
        for change in ({"quantity": 10.125}, {"unitPriceCents": True}, {"quantity": "1e3"}, {"verifiedGeometry": True}):
            body = copy.deepcopy(self.body)
            body["lines"][0].update(change)
            before = self.snapshot()
            with self.assertRaises(commercial.CommercialError):
                self.domain.create_preflight(self.project, body, actor=ESTIMATOR_LOGIN)
            self.assertEqual(before, self.snapshot())

    def test_revision_preserves_stable_lineage_and_exact_old_new_comparison(self):
        body = self.revise()
        before = self.snapshot()
        plan = self.domain.revise_preflight(self.source["estimateId"], body, actor=ESTIMATOR_LOGIN)
        self.assertEqual(plan["estimatePlan"]["total"], "475.09")
        self.assertEqual(before, self.snapshot())
        revised = self.domain.revise(self.source["estimateId"], body, actor=ESTIMATOR_LOGIN)
        self.assertEqual(revised["lines"][0]["stable_line_id"], self.source["lines"][0]["stable_line_id"])
        self.assertEqual(revised["lines"][0]["previous_line_id"], self.source["lines"][0]["estimate_line_id"])
        comparison = self.domain.comparison(revised["estimateId"])
        self.assertEqual(comparison["deltaCents"], 6437)
        self.assertEqual(comparison["lines"][0]["kind"], "changed")
        self.assertEqual(self.domain.source(self.source["estimateId"])["sourceHash"], self.source["sourceHash"])

    def test_foreign_and_duplicate_predecessor_lines_are_refused_before_create(self):
        body = self.revise(bad_previous=self.c.estimates.get(self.c.commercial_practice_records["hidden_estimate_id"])["lines"][0]["id"])
        before = self.snapshot()
        with self.assertRaises(commercial.CommercialError):
            self.domain.revise(self.source["estimateId"], body, actor=ESTIMATOR_LOGIN)
        self.assertEqual(before, self.snapshot())
        body["lines"][0]["previousLineId"] = body["lines"][1]["previousLineId"]
        with self.assertRaises(commercial.CommercialError):
            self.domain.revise_preflight(self.source["estimateId"], body, actor=ESTIMATOR_LOGIN)

    def test_unaccepted_source_and_nonzero_contingency_cannot_become_handoff(self):
        with self.assertRaises(RuntimeError):
            self.domain.handoff_preflight(self.source["estimateId"], self.package["id"], actor=ESTIMATOR_LOGIN)
        body = self.revise()
        body["contingencyRate"] = "0.05"
        revised = self.domain.revise(self.source["estimateId"], body, actor=ESTIMATOR_LOGIN)
        self.source = revised
        self.accept()
        before = self.snapshot()
        with self.assertRaises(commercial.CommercialError):
            self.domain.prepare_handoff(revised["estimateId"], self.package["id"], actor=ESTIMATOR_LOGIN)
        self.assertEqual(before, self.snapshot())

    def test_exact_accepted_handoff_and_pm_draft_have_no_execution_or_journal(self):
        handoff = self.handoff()
        before = self.snapshot()
        plan = self.domain.commitment_preflight(handoff["handoffId"], actor=PM_LOGIN)
        self.assertEqual(plan["total"], "410.72")
        self.assertEqual(before, self.snapshot())
        created = self.domain.create_commitment(handoff["handoffId"], actor=PM_LOGIN)
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["commitment"]["original_amount"], "410.72")
        self.assertEqual(created["commitment"]["retainage_rate"], "0.100000")
        self.assertEqual(created["lineage"][0]["source"]["quantity"], "10.125")
        self.assertEqual(created["lineage"][0]["source"]["cost_code"], "26-100")
        self.assertEqual(created["lineage"][0]["sov_line_id"], created["commitment"]["sov"][0]["id"])
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 0)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM payment_intents"), 0)
        self.assertEqual(self.c.provider.submissions, [])

    def test_estimator_cannot_create_pm_draft_and_one_handoff_cannot_duplicate(self):
        handoff = self.handoff()
        before = self.snapshot()
        with self.assertRaises(commercial.CommercialError):
            self.domain.create_commitment(handoff["handoffId"], actor=ESTIMATOR_LOGIN)
        self.assertEqual(before, self.snapshot())
        self.domain.create_commitment(handoff["handoffId"], actor=PM_LOGIN)
        count = self.c.db.scalar("SELECT COUNT(*) FROM commitments")
        with self.assertRaises(commercial.CommercialError):
            self.domain.create_commitment(handoff["handoffId"], actor=PM_LOGIN)
        self.assertEqual(count, self.c.db.scalar("SELECT COUNT(*) FROM commitments"))

    def test_historic_handoff_and_draft_survive_genuine_successor_without_price_overwrite(self):
        handoff = self.handoff()
        commitment = self.domain.create_commitment(handoff["handoffId"], actor=PM_LOGIN)
        body = self.revise()
        self.domain.revise(self.source["estimateId"], body, actor=ESTIMATOR_LOGIN)
        historic = self.domain.commitment_proof(commitment["commitmentId"])
        self.assertEqual(historic["commitment"]["original_amount"], "410.72")
        self.assertEqual(historic["handoff"]["record"], handoff["record"])
        with self.assertRaises(RuntimeError):
            self.domain.commitment_proof(commitment["commitmentId"], current=True)

    def test_nested_create_failure_rolls_back_engine_and_manual_sources(self):
        body = self.revise()
        with self.c.db.transaction():
            before = self.snapshot()[0]
            original = self.domain._record
            def failing(kind, record, **kwargs):
                if kind == "estimate_sources":
                    raise RuntimeError("synthetic source audit failure")
                return original(kind, record, **kwargs)
            with patch.object(self.domain, "_record", side_effect=failing):
                with self.assertRaises(RuntimeError):
                    self.domain.revise(self.source["estimateId"], body, actor=ESTIMATOR_LOGIN)
            self.assertEqual(before, self.snapshot()[0])

    def test_nested_draft_correspondence_failure_rolls_back_commitment_and_sov(self):
        handoff = self.handoff()
        with self.c.db.transaction():
            before = self.snapshot()[0]
            with patch.object(self.domain, "_record", side_effect=RuntimeError("synthetic correspondence failure")):
                with self.assertRaises(RuntimeError):
                    self.domain.create_commitment(handoff["handoffId"], actor=PM_LOGIN)
            self.assertEqual(before, self.snapshot()[0])

    def test_raw_manual_locator_rewrite_and_deleted_birth_inventory_are_refused(self):
        row = self.source["lines"][0]
        triggers = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='commercial_line_sources'")
        for trigger in triggers:
            self.c.db.execute('DROP TRIGGER "'+trigger["name"]+'"')
        body = copy.deepcopy(row)
        body["source_locator"] = "Unrecorded page999"
        self.c.db.execute("UPDATE commercial_line_sources SET body_json=? WHERE id=?", (canonical_json(body), row["id"]))
        for trigger in triggers:
            self.c.db.execute(trigger["sql"])
        with self.assertRaises(commercial.CommercialError):
            self.domain.source(self.source["estimateId"])

    def test_foreign_drawing_and_hidden_source_inventory_never_join_owned_lines(self):
        body = copy.deepcopy(self.body)
        hidden = self.c.estimates.get(self.c.commercial_practice_records["hidden_estimate_id"])
        body["documentRevisionId"] = hidden["document_revision_id"]
        before = self.snapshot()
        with self.assertRaises(commercial.CommercialError):
            self.domain.create_preflight(self.project, body, actor=ESTIMATOR_LOGIN)
        self.assertEqual(before, self.snapshot())
        inventory = self.domain.source_inventory(project_ids=(self.project,))
        self.assertTrue(all(source["projectId"] == self.project for source in inventory))

    def test_zero_priced_source_line_is_preserved_in_complete_handoff(self):
        body = self.revise()
        body["lines"][0]["quantity"] = "0"
        self.source = self.domain.revise(self.source["estimateId"], body, actor=ESTIMATOR_LOGIN)
        handoff = self.handoff()
        created = self.domain.create_commitment(handoff["handoffId"], actor=PM_LOGIN)
        self.assertEqual(len(created["lineage"]), 2)
        self.assertEqual(created["lineage"][0]["source"]["amount"], "0.00")
        self.assertEqual(created["commitment"]["sov"][0]["amount"], "0.00")

    def test_modern_source_entity_drift_before_acceptance_is_refused(self):
        self.c.db.execute("UPDATE projects SET entity='Unrecorded shifted entity' WHERE id=?", (self.project,))
        before = self.snapshot()
        with self.assertRaises(commercial.CommercialError):
            self.domain.source(self.source["estimateId"])
        with self.assertRaises(commercial.CommercialError):
            self.c.request_approval("estimate.approve", self.source["estimateId"], actor_role="estimator", requested_by=ESTIMATOR_LOGIN)
        self.assertEqual(before, self.snapshot())

    def test_raw_commitment_execution_status_cannot_replace_original_pm_application(self):
        handoff = self.handoff()
        created = self.domain.create_commitment(handoff["handoffId"], actor=PM_LOGIN)
        triggers = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='commitments'")
        for trigger in triggers:
            self.c.db.execute('DROP TRIGGER "'+trigger["name"]+'"')
        self.c.db.execute("UPDATE commitments SET status='executed',version=2 WHERE id=?", (created["commitmentId"],))
        for trigger in triggers:
            self.c.db.execute(trigger["sql"])
        with self.assertRaises(commercial.CommercialError):
            self.domain.commitment_proof(created["commitmentId"])

    def test_genuine_separate_commitment_execution_retains_original_draft_source(self):
        handoff = self.handoff()
        created = self.domain.create_commitment(handoff["handoffId"], actor=PM_LOGIN)
        approval = self.c.request_approval("commitment.execute", created["commitmentId"], actor_role="pm", requested_by=ESTIMATOR_LOGIN)
        self.c.approve(approval["id"], approver=PM_LOGIN, approver_role="pm")
        self.c.execute(approval["id"], actor=PM_LOGIN)
        proof = self.domain.commitment_proof(created["commitmentId"])
        self.assertEqual(proof["status"], "executed")
        self.assertEqual(proof["record"], created["record"])

    def test_draft_correspondence_refuses_unrecorded_executed_amount(self):
        handoff = self.handoff()
        created = self.domain.create_commitment(handoff["handoffId"], actor=PM_LOGIN)
        commitment_id = created["commitmentId"]
        original = self.c.commitments.get(commitment_id)["executed_amount"]
        self.c.db.execute("UPDATE commitments SET executed_amount='123456.78' WHERE id=?", (commitment_id,))
        before = self.snapshot()
        with self.assertRaises(commercial.CommercialError):
            self.domain.commitment_proof(commitment_id)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(all(check["ok"] for check in self.domain.close_checks(None)))
        self.c.db.execute("UPDATE commitments SET executed_amount=? WHERE id=?", (original, commitment_id))
        self.assertEqual(self.domain.commitment_proof(commitment_id)["status"], "draft")

    def test_executed_correspondence_refuses_amount_and_attribution_time_drift(self):
        handoff = self.handoff()
        created = self.domain.create_commitment(handoff["handoffId"], actor=PM_LOGIN)
        commitment_id = created["commitmentId"]
        approval = self.c.request_approval("commitment.execute", commitment_id, actor_role="pm", requested_by=ESTIMATOR_LOGIN)
        self.c.approve(approval["id"], approver=PM_LOGIN, approver_role="pm")
        self.c.execute(approval["id"], actor=PM_LOGIN)
        original = self.c.commitments.get(commitment_id)
        for field, value in (("executed_amount", "123456.78"), ("executed_at", "1900-01-01T00:00:00+00:00")):
            with self.subTest(field=field):
                self.c.db.execute(f"UPDATE commitments SET {field}=? WHERE id=?", (value, commitment_id))
                before = self.snapshot()
                with self.assertRaises(commercial.CommercialError):
                    self.domain.commitment_proof(commitment_id)
                self.assertEqual(before, self.snapshot())
                self.assertFalse(all(check["ok"] for check in self.domain.close_checks(None)))
                self.c.db.execute(f"UPDATE commitments SET {field}=? WHERE id=?", (original[field], commitment_id))
                self.assertEqual(self.domain.commitment_proof(commitment_id)["status"], "executed")

    def test_original_manual_births_require_exact_engine_number_and_audit_reference_types(self):
        for mutation in ("line_number", "baseline_revision", "creation_sequence"):
            with self.subTest(mutation=mutation):
                document = self.c.evidence.register_document(project_id=self.project, kind="drawing", title="Synthetic exact source "+mutation, actor=ESTIMATOR_LOGIN)
                revision = self.c.evidence.add_revision(document_id=document["id"], content="Synthetic exact source "+mutation, actor=ESTIMATOR_LOGIN)
                body = copy.deepcopy(self.body)
                body["documentRevisionId"] = revision["id"]
                record = self.domain._record
                def altered_original_birth(kind, facts, **options):
                    if mutation == "line_number" and kind == "line_sources":
                        facts["engine_line"]["line_no"] = float(facts["engine_line"]["line_no"])
                    elif mutation == "baseline_revision" and kind == "estimate_sources":
                        facts["baseline"]["revision"] = float(facts["baseline"]["revision"])
                    elif mutation == "creation_sequence" and kind == "estimate_sources":
                        facts["baseline"]["creation"]["auditSeq"] = float(facts["baseline"]["creation"]["auditSeq"])
                    return record(kind, facts, **options)
                before = tuple(self.c.db.conn.iterdump()), tuple(self.c.provider.submissions)
                with patch.object(self.domain, "_record", side_effect=altered_original_birth), self.assertRaises(commercial.CommercialError):
                    self.domain.create(self.project, body, actor=ESTIMATOR_LOGIN)
                self.assertEqual(before, (tuple(self.c.db.conn.iterdump()), tuple(self.c.provider.submissions)))
                created = self.domain.create(self.project, body, actor=ESTIMATOR_LOGIN)
                self.assertIs(type(created["baseline"]["revision"]), int)
                self.assertIs(type(created["record"]["baseline"]["creation"]["auditSeq"]), int)
                self.assertTrue(all(type(line["engine_line"]["line_no"]) is int for line in created["lines"]))

    def test_separate_execution_authorization_keeps_original_attribution_times_and_deadline(self):
        handoff = self.handoff()
        created = self.domain.create_commitment(handoff["handoffId"], actor=PM_LOGIN)
        commitment_id = created["commitmentId"]
        requested = self.c.request_approval("commitment.execute", commitment_id, actor_role="pm", requested_by=ESTIMATOR_LOGIN)
        self.c.approve(requested["id"], approver=PM_LOGIN, approver_role="pm")
        self.c.execute(requested["id"], actor=PM_LOGIN)
        original = self.c.approvals.get(requested["id"])
        def replace_protected(field, value):
            triggers = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='approvals'")
            for trigger in triggers:
                self.c.db.execute('DROP TRIGGER "'+trigger["name"]+'"')
            self.c.db.execute(f"UPDATE approvals SET {field}=? WHERE id=?", (value, original["id"]))
            for trigger in triggers:
                self.c.db.execute(trigger["sql"])
        for field in ("requested_at", "granted_at", "consumed_at", "expires_at"):
            with self.subTest(field=field):
                replace_protected(field, "1900-01-01T00:00:00+00:00")
                before = self.snapshot()
                with self.assertRaises(commercial.CommercialError):
                    self.domain.commitment_proof(commitment_id)
                self.assertEqual(before, self.snapshot())
                self.assertFalse(all(check["ok"] for check in self.domain.close_checks(None)))
                replace_protected(field, original[field])
                self.assertEqual(self.domain.commitment_proof(commitment_id)["status"], "executed")

    def test_deleted_source_birth_cannot_disappear_from_historical_inventory(self):
        triggers = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='commercial_estimate_sources'")
        for trigger in triggers:
            self.c.db.execute('DROP TRIGGER "'+trigger["name"]+'"')
        self.c.db.execute("DELETE FROM commercial_estimate_sources WHERE estimate_id=?", (self.source["estimateId"],))
        for trigger in triggers:
            self.c.db.execute(trigger["sql"])
        with self.assertRaises(commercial.CommercialError):
            self.domain.source_inventory(project_ids=(self.project,))

    def test_owned_backup_is_readable_but_copy_cannot_create_manual_revision(self):
        with tempfile.TemporaryDirectory(dir="/tmp/cipher-completion/commercial-draft") as directory:
            path = os.path.join(directory, "commercial-copy.db")
            with sqlite3.connect(path) as copied_connection:
                self.c.db.conn.backup(copied_connection)
            copied = service.Cipher(path)
            try:
                copied.register_plugin("commercial", commercial.Plugin(copied))
                self.assertEqual(copied.plugin("commercial").source(self.source["estimateId"])["sourceHash"], self.source["sourceHash"])
                before = tuple(copied.db.conn.iterdump())
                with self.assertRaises(WriteAuthorityError):
                    copied.plugin("commercial").create(self.project, self.body, actor=ESTIMATOR_LOGIN)
                self.assertEqual(before, tuple(copied.db.conn.iterdump()))
            finally:
                copied.db.close()

if __name__ == "__main__":
    unittest.main()
