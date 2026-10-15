"""Genuine same-workspace draft reads against the isolated commercial domain."""
import copy
import json
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.core.money import money
from apps.cipher.commercial_contract import API_PREFIX, CommercialContractDraft
from apps.cipher.commercial_practice_fixture import (make_commercial_practice_fixture, BOOTSTRAP_LOGIN,
                                        ESTIMATOR_LOGIN, REVIEWER_LOGIN, PM_LOGIN, HIDDEN_ESTIMATOR_LOGIN)


class CommercialDraftCommitmentContractTests(unittest.TestCase):
    def setUp(self):
        self.c = make_commercial_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.records = self.c.commercial_practice_records
        self.domain = self.c.plugin("commercial")
        self.contract = CommercialContractDraft(self.c, secret=b"draft-private-commercial-key-12345")
        self.preparer = self.c.commercial_practice_persona_people["preparer"]["person_id"]
        self.pm = self.c.commercial_practice_persona_people["pm"]["person_id"]
        self.estimate_id = self.records["current_estimate_id"]
        requested = self.c.request_approval("estimate.approve", self.estimate_id,
                                            actor_role="estimator", requested_by=ESTIMATOR_LOGIN)
        self.c.approve(requested["id"], approver=REVIEWER_LOGIN, approver_role="estimator")
        self.c.execute(requested["id"], actor=ESTIMATOR_LOGIN)
        self.approval_id = requested["id"]
        self.handoff = self.domain.prepare_handoff(self.estimate_id, self.records["package_id"], actor=ESTIMATOR_LOGIN)
        self.proof = self.domain.create_commitment(self.handoff["handoffId"], actor=PM_LOGIN)
        self.commitment_id = self.proof["commitmentId"]

    def snapshot(self):
        return (tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes,
                tuple(self.c.provider.submissions), dict(self.c.provider.transfers))

    def tamper(self, table, sql, params):
        triggers = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))
        with self.c.db.transaction():
            for trigger in triggers:
                self.c.db.conn.execute("DROP TRIGGER " + trigger["name"])
            self.c.db.conn.execute(sql, params)
            for trigger in triggers:
                self.c.db.conn.execute(trigger["sql"])

    def test_same_workspace_draft_has_exact_priced_line_correspondence_and_only_commercial_links(self):
        before = self.snapshot()
        result = self.contract.commitment(self.preparer, self.commitment_id)
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["effectiveSourceStatus"], "current")
        self.assertEqual(result["estimate"]["acceptanceApprovalId"], self.approval_id)
        self.assertEqual(result["handoffId"], self.handoff["handoffId"])
        self.assertEqual(result["originalAmountCents"], 50000)
        self.assertFalse(result["executionAvailableHere"])
        self.assertEqual(result["availableActions"], [])
        for line, source in zip(result["lines"], self.proof["lineage"]):
            fact = source["source"]
            self.assertEqual(line["estimateLineId"], fact["source_line_id"])
            self.assertEqual(line["sovLineId"], source["sov_line_id"])
            self.assertEqual(line["stableLineId"], fact["stable_line_id"])
            self.assertEqual(line["quantity"], fact["quantity"])
            self.assertEqual(line["unit"], fact["unit"])
            self.assertEqual(line["unitPriceCents"], int(money(fact["unit_price"]) * 100))
            self.assertEqual(line["amountCents"], int(money(fact["amount"]) * 100))
            self.assertEqual(line["costCode"], fact["cost_code"])
            self.assertEqual(line["sourceLocator"], fact["source_locator"])
            self.assertEqual(line["measurementMethod"], "manual_entry")
            self.assertFalse(line["verifiedGeometry"])
        self.assertTrue(all(link["apiRoute"].startswith(API_PREFIX) for link in result["relatedRecords"]))
        self.assertNotIn("ap-practice", json.dumps(result))
        self.assertNotIn("row_hash", json.dumps(result))
        self.assertNotIn("body_json", json.dumps(result))
        self.assertNotIn("destination", json.dumps(result))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        self.assertFalse(self.c.provider.submissions)

    def test_hidden_and_unrelated_visible_commitments_refuse_before_private_source_proof(self):
        hidden = self.c.commitments.create(project_id=self.records["hidden_project_id"], supplier_id=self.records["supplier_id"],
            title="Hidden unrelated draft", sov_lines=[{"description": "Hidden source", "amount": "10.00"}], actor=HIDDEN_ESTIMATOR_LOGIN)
        unrelated = self.c.commitments.create(project_id=self.records["project_id"], supplier_id=self.records["supplier_id"],
            title="Visible unrelated draft", sov_lines=[{"description": "Other source", "amount": "10.00"}], actor=PM_LOGIN)
        before = self.snapshot()
        with patch.object(self.domain, "commitment_proof", side_effect=AssertionError("Scope before proof")) as proof:
            for identity in (hidden["id"], unrelated["id"], "unknown"):
                with self.assertRaises(APRefusal) as caught:
                    self.contract.commitment(self.preparer, identity)
                self.assertEqual(caught.exception.status, 404)
                self.assertNotIn(identity, caught.exception.message)
            proof.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_raw_changed_sov_is_refused_before_exact_line_values_are_serialized(self):
        line_id = self.proof["lineage"][0]["sov_line_id"]
        self.tamper("sov_lines", "UPDATE sov_lines SET description=?,amount=? WHERE id=?",
                    ("Unreviewed altered source", "999.00", line_id))
        before = self.snapshot()
        with self.assertRaises(APRefusal) as caught:
            self.contract.commitment(self.preparer, self.commitment_id)
        self.assertEqual(caught.exception.status, 423)
        self.assertNotIn("Unreviewed", caught.exception.message)
        self.assertEqual(self.snapshot(), before)

    def test_genuine_later_estimate_revision_keeps_original_draft_mapping_readable(self):
        original = self.contract.commitment(self.preparer, self.commitment_id)
        source = self.domain.source(self.estimate_id)
        scope = source["baseline"]["scope"]
        revised = {"documentRevisionId": source["drawing"]["revisionId"],
            "lines": [{"description": line["engine_line"]["description"],
                       "quantity": "13" if index == 0 else line["engine_line"]["quantity"],
                       "unit": line["engine_line"]["unit"], "unitPriceCents": int(money(line["engine_line"]["unit_price"]) * 100),
                       "sourceLocator": line["source_locator"], "costCode": line["cost_code"],
                       "previousLineId": line["estimate_line_id"]} for index, line in enumerate(source["lines"])],
            "priceBookRef": scope["price_book_ref"], "inclusions": copy.deepcopy(scope["inclusions"]),
            "exclusions": copy.deepcopy(scope["exclusions"]), "contingencyRate": "0",
            "measurementBasis": scope["measurement_basis"], "removedExclusions": []}
        self.domain.revise(self.estimate_id, revised, actor=ESTIMATOR_LOGIN)
        before = self.snapshot()
        current = self.contract.commitment(self.preparer, self.commitment_id)
        self.assertEqual(current["status"], "draft")
        self.assertEqual(current["effectiveSourceStatus"], "stale")
        self.assertEqual(current["lines"], original["lines"])
        self.assertEqual(current["estimate"], original["estimate"])
        self.assertEqual(current["relatedRecords"], original["relatedRecords"])
        self.assertNotEqual(current["version"], original["version"])
        self.assertEqual(self.snapshot(), before)

    def test_current_ended_membership_cannot_read_previous_outcome_draft(self):
        self.c.plugin("people").end_membership(ESTIMATOR_LOGIN, self.records["project_id"],
                                               reason="Synthetic commercial assignment ended", actor=BOOTSTRAP_LOGIN)
        before = self.snapshot()
        with self.assertRaises(APRefusal) as caught:
            self.contract.commitment(self.preparer, self.commitment_id)
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(self.snapshot(), before)

    def test_genuine_separate_execution_reports_current_status_and_original_creation(self):
        original = self.contract.commitment(self.preparer, self.commitment_id)
        approval = self.c.request_approval("commitment.execute", self.commitment_id,
                                            actor_role="pm", requested_by=ESTIMATOR_LOGIN)
        self.c.approve(approval["id"], approver=PM_LOGIN, approver_role="pm")
        self.c.execute(approval["id"], actor=PM_LOGIN)
        before = self.snapshot()
        current = self.contract.commitment(self.preparer, self.commitment_id)
        self.assertEqual(current["status"], "executed")
        self.assertEqual(current["creationStatus"], "draft")
        self.assertEqual(current["lines"], original["lines"])
        self.assertEqual(current["relatedRecords"], original["relatedRecords"])
        self.assertFalse(current["executionAvailableHere"])
        self.assertEqual(current["availableActions"], [])
        self.assertNotEqual(current["version"], original["version"])
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
