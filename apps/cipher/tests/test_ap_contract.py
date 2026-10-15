"""Scoped, read-only presenters for the disposable AP practice application."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APContract, APRefusal
from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
from apps.cipher.service import Cipher


class APContractTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.contract = APContract(self.c, secret=b"contract-test-key-with-at-least-32-bytes")
        self.people = self.c.ap_practice_persona_people
        self.accountant = self.people["accountant"]["person_id"]
        self.pm = self.people["pm"]["person_id"]

    def test_contract_provenance_and_scope_precede_aggregates(self):
        projects = self.contract.read(self.accountant, "projects")
        self.assertEqual((projects["contractVersion"], projects["mode"], projects["synthetic"], projects["currency"]),
                         ("cipher.ap-practice.v1", "practice", True, "USD"))
        self.assertEqual(projects["count"], 2)
        self.assertEqual(projects["count"], len(projects["value"]))
        commitments = self.contract.read(self.accountant, "commitments")
        self.assertEqual({r["projectId"] for r in commitments["value"]}, {r["id"] for r in projects["value"]})
        self.assertEqual(commitments["totals"]["committedCents"],
                         sum(r["executedAmountCents"] for r in commitments["value"] if r["status"] in ("executed", "closed")))

    def test_bill_record_exact_money_and_truthful_unnumbered_lines(self):
        bills = self.contract.read(self.accountant, "bills")["value"]
        self.assertTrue(bills)
        for bill in bills:
            self.assertIsNone(bill["displayNumber"])
            for key in ("amountDueCents", "currentDueCents", "retainageCents", "thisPeriodCents"):
                self.assertIs(type(bill[key]), int)
            for line in bill["lines"]:
                self.assertEqual(set(line), {"id", "sovLineId", "description", "costCode", "cumulativeInstalledCents", "priorInstalledCents", "thisPeriodInstalledCents"})
                self.assertEqual(line["cumulativeInstalledCents"] - line["priorInstalledCents"], line["thisPeriodInstalledCents"])

    def test_signed_cursor_rejects_other_person_or_changed_filters(self):
        first = self.contract.read(self.accountant, "projects", top=1)
        self.assertIsNotNone(first["nextCursor"])
        with self.assertRaises(APRefusal) as failure:
            self.contract.read(self.pm, "projects", top=1, cursor=first["nextCursor"])
        self.assertEqual(failure.exception.code, "invalid_cursor")
        with self.assertRaises(APRefusal):
            self.contract.read(self.accountant, "projects", top=2, cursor=first["nextCursor"])
        second = self.contract.read(self.accountant, "projects", top=1, cursor=first["nextCursor"])
        self.assertNotEqual(first["value"][0]["id"], second["value"][0]["id"])

    def test_read_does_not_mutate_database_or_simulator(self):
        before = (tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes,
                  len(self.c.provider.submissions), len(self.c.provider.transfers))
        for collection in ("projects", "commitments", "bills", "approvals"):
            self.contract.read(self.accountant, collection)
        self.contract.posting_queue(self.accountant)
        self.assertEqual(before, (tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes,
                                 len(self.c.provider.submissions), len(self.c.provider.transfers)))

    def test_response_allowlist_does_not_expose_manifest_or_destinations(self):
        text = json.dumps([self.contract.read(self.accountant, name)
                           for name in ("projects", "commitments", "bills", "approvals")])
        for name in ("manifest", "manifest_json", "nonce", "destination", "manifest_hash", "material_hash", "actor_role", "snapshot_json", "content_hash"):
            self.assertNotIn('"' + name + '"', text)

    def test_same_total_draft_line_tampering_is_not_certification_proof(self):
        bill_id = self.c.ap_practice_records["draft_bill_id"]
        bill = self.c.bills.get(bill_id)
        line = bill["lines"][0]
        # Preserve header totals and line math while introducing an unrecorded
        # second economic source. Removing triggers is part of this threat model.
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('bill_lines','sov_lines')"):
            self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
        source = self.c.db.one("SELECT * FROM sov_lines WHERE id=?", (line["sov_line_id"],))
        self.c.db.execute("INSERT INTO sov_lines(id,commitment_id,line_no,description,cost_code,amount) VALUES (?,?,?,?,?,?)",
                          ("tampered-source", source["commitment_id"], source["line_no"] + 1, "Unrecorded allocation", source["cost_code"], "100.00"))
        self.c.db.execute("UPDATE bill_lines SET cumulative_installed='12245.67',installed_this_period='12245.67' WHERE id=?", (line["id"],))
        self.c.db.execute("INSERT INTO bill_lines(id,bill_id,sov_line_id,cumulative_installed,prior_installed,installed_this_period,stored_added,stored_transferred) VALUES (?,?,?,'100.00','0.00','100.00','0.00','0.00')",
                          ("tampered-line", bill_id, "tampered-source"))
        with self.assertRaises(APRefusal) as failure:
            self.contract.require_resource(self.accountant, "bill.requestApproval", bill_id)
        self.assertEqual((failure.exception.status, failure.exception.code), (422, "invalid_record"))

    def test_line_of_another_commitment_cannot_supply_action_source(self):
        bill_id = self.c.ap_practice_records["draft_bill_id"]
        foreign = self.c.commitments.get(self.c.ap_practice_records["hidden_commitment_id"])["sov"][0]["id"]
        self.c.db.execute("UPDATE bill_lines SET sov_line_id=? WHERE bill_id=?", (foreign, bill_id))
        with self.assertRaises(APRefusal) as failure:
            self.contract.require_resource(self.accountant, "bill.requestApproval", bill_id)
        self.assertEqual((failure.exception.status, failure.exception.code), (422, "invalid_record"))

    def test_hidden_scope_and_unknown_ids_have_the_same_safe_refusal(self):
        ids = (self.c.ap_practice_records["hidden_bill_id"], "unknown-bill")
        errors = []
        for bill_id in ids:
            with self.assertRaises(APRefusal) as failure:
                self.contract.detail(self.accountant, bill_id)
            errors.append((failure.exception.status, failure.exception.value))
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(errors[0][0], 404)
        for person in (self.accountant, self.pm):
            with self.assertRaises(APRefusal) as failure:
                self.contract.read(person, "bills", project_id=self.c.ap_practice_records["hidden_project_id"])
            self.assertEqual(failure.exception.status, 404)

    def test_hidden_names_and_invalid_currency_are_filtered_before_presentation(self):
        hidden_project = self.c.ap_practice_records["hidden_project_id"]
        self.c.db.execute("UPDATE projects SET currency='EUR',budget='bad-private-number' WHERE id=?", (hidden_project,))
        text = json.dumps([self.contract.read(self.accountant, collection)
                           for collection in ("projects", "commitments", "bills", "approvals")])
        self.assertNotIn("Hidden", text)
        self.assertNotIn("bad-private-number", text)
        self.assertNotIn(hidden_project, text)
        self.assertNotIn(self.c.ap_practice_records["hidden_bill_id"], text)

    def test_membership_loss_removes_rows_and_invalidates_existing_cursor(self):
        page = self.contract.read(self.accountant, "projects", top=1)
        project = self.c.ap_practice_records["visible_project_ids"][0]
        self.c.plugin("people").end_membership(self.people["accountant"]["login"], project,
                                               reason="Synthetic reassignment", actor="practice.bootstrap")
        current = self.contract.read(self.accountant, "projects")
        self.assertEqual(current["count"], 1)
        self.assertNotIn(project, {row["id"] for row in current["value"]})
        with self.assertRaises(APRefusal) as failure:
            self.contract.read(self.accountant, "projects", top=1, cursor=page["nextCursor"])
        self.assertEqual(failure.exception.code, "invalid_cursor")
        with self.assertRaises(APRefusal) as failure:
            self.contract.detail(self.accountant, self.c.ap_practice_records["draft_bill_id"])
        self.assertEqual(failure.exception.status, 404)

    def test_owner_and_unregistered_principal_do_not_inherit_read_scope(self):
        owner = self.c.plugin("people").person_for("practice.bootstrap")["id"]
        self.assertEqual(self.contract.read(owner, "projects")["count"], 0)
        for principal in ("practice.accountant", "not-a-person", self.people["accountant"]):
            with self.assertRaises(APRefusal) as failure:
                self.contract.read(principal, "projects")
            self.assertEqual(failure.exception.status, 401)

    def test_explicit_duty_is_checked_on_the_resource_project(self):
        approved = self.c.ap_practice_records["approved_bill_id"]
        approval_id = self.c.bills.get(approved)["business_approval_id"]
        with self.assertRaises(APRefusal) as failure:
            self.contract.require_resource(self.accountant, "bill.approve", approval_id)
        self.assertEqual(failure.exception.status, 403)
        with self.assertRaises(APRefusal) as failure:
            self.contract.require_resource(self.pm, "bill.post", approved)
        self.assertEqual(failure.exception.status, 403)
        self.assertEqual(self.contract.require_resource(self.accountant, "bill.post", approved)["personId"], self.accountant)

    def test_other_operations_are_not_approval_presenter_fallthroughs(self):
        rows = self.contract.read(self.accountant, "approvals")["value"]
        self.assertEqual(len(rows), 1)
        other = self.c.db.one("SELECT id FROM approvals WHERE operation='commitment.execute' LIMIT 1")["id"]
        with self.assertRaises(APRefusal) as failure:
            self.contract.packet(self.pm, other)
        self.assertEqual(failure.exception.status, 404)
        with self.assertRaises(APRefusal) as failure:
            self.contract.require_resource(self.accountant, "payment.release", self.c.ap_practice_records["draft_bill_id"])
        self.assertEqual(failure.exception.code, "unsupported_action")

    def test_current_source_change_has_distinct_effective_status_without_lifecycle_write(self):
        bill_id = self.c.ap_practice_records["approved_bill_id"]
        before = self.contract.detail(self.accountant, bill_id)
        self.c.db.execute("UPDATE parties SET name='Revised synthetic supplier name' WHERE id=?", (before["supplierId"],))
        changed = self.contract.detail(self.accountant, bill_id)
        self.assertEqual((changed["status"], changed["effectiveStatus"]), ("approved", "stale"))
        self.assertNotEqual(before["version"], changed["version"])
        self.assertFalse(changed["availableActions"])
        packet = self.contract.packet(self.pm, changed["businessApproval"]["approvalId"])
        self.assertIn({"field": "supplierName", "before": before["supplierName"], "after": "Revised synthetic supplier name"}, packet["changes"])

    def test_versions_are_keyed_stable_and_bind_period_and_current_person(self):
        bill_id = self.c.ap_practice_records["approved_bill_id"]
        before = self.contract.version(self.accountant, bill_id)
        self.assertEqual(before, self.contract.version(self.accountant, bill_id))
        self.assertNotEqual(before, self.contract.version(self.pm, bill_id))
        other = APContract(self.c, secret=b"a-different-secret-of-at-least-32-bytes")
        self.assertNotEqual(before, other.version(self.accountant, bill_id))
        self.c.db.execute("UPDATE periods SET status='closed' WHERE id='2026-10'")
        self.assertNotEqual(before, self.contract.version(self.accountant, bill_id))

    def test_packets_are_readable_to_each_scoped_duty_and_show_journal_free_effect(self):
        approval_id = self.c.bills.get(self.c.ap_practice_records["approved_bill_id"])["business_approval_id"]
        for person in (self.accountant, self.pm):
            packet = self.contract.packet(person, approval_id)
            self.assertEqual(packet["effect"], {"billStatus": "approved", "workingLedgerJournalDelta": 0, "apPayableDeltaCents": 0})
            self.assertEqual(packet["changes"], [])
            self.assertIsInstance(packet["bill"]["postingPeriods"], list)

    def test_posting_queue_includes_scoped_blocked_rows_without_false_payables(self):
        for person in (self.accountant, self.pm):
            queue = self.contract.posting_queue(person)
            self.assertEqual(queue["count"], 1)
            self.assertEqual(queue["totals"]["currentDueCents"], 0)
            row = queue["value"][0]
            self.assertEqual(row["billId"], self.c.ap_practice_records["approved_bill_id"])
            self.assertEqual(row["ready"], person == self.accountant)
            self.assertEqual(self.contract.posting_queue(person, ready=True)["count"], int(person == self.accountant))

    def test_tampered_business_snapshot_is_refused_with_safe_fields(self):
        bill = self.c.bills.get(self.c.ap_practice_records["approved_bill_id"])
        self.c.db.execute("DROP TRIGGER bill_business_approvals_no_update")
        self.c.db.execute("UPDATE bill_business_approvals SET snapshot_json='{}' WHERE id=?", (bill["approval_record_id"],))
        with self.assertRaises(APRefusal) as failure:
            self.contract.detail(self.accountant, bill["id"])
        self.assertEqual((failure.exception.status, failure.exception.code), (422, "invalid_record"))
        self.assertNotIn("snapshot_json", failure.exception.message)
        self.assertNotIn(bill["id"], failure.exception.message)

    def test_query_limits_reject_boolean_page_size_and_forged_cursor(self):
        for query in ({"top": True}, {"top": 0}, {"top": 101}, {"status": "invisible"}, {"search": "x" * 201}, {"cursor": "forged-cursor"}):
            with self.subTest(query=query), self.assertRaises(APRefusal) as failure:
                self.contract.read(self.accountant, "bills", **query)
            self.assertEqual(failure.exception.status, 422)

    def test_file_workspace_cannot_be_used_as_a_practice_presenter(self):
        with tempfile.TemporaryDirectory() as directory:
            c = Cipher(os.path.join(directory, "workspace.sqlite"))
            try:
                with self.assertRaises(APRefusal) as failure:
                    APContract(c, secret=b"file-workspace-test-key-with-32-bytes").read(self.accountant, "projects")
                self.assertEqual((failure.exception.status, failure.exception.code), (423, "unsupported_workspace"))
                self.assertNotIn(directory, failure.exception.message)
            finally:
                c.db.close()

    def test_visible_non_usd_commitments_refuse_before_money_totals(self):
        project = self.c.ap_practice_records["visible_project_ids"][0]
        self.c.db.execute("UPDATE projects SET currency='EUR' WHERE id=?", (project,))
        with self.assertRaises(APRefusal) as failure:
            self.contract.read(self.accountant, "commitments")
        self.assertEqual(failure.exception.code, "unsupported_currency")

    def test_commitment_totals_require_the_original_audited_execution(self):
        commitment = self.c.ap_practice_records["visible_commitment_ids"][0]
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='commitments'"):
            self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
        self.c.db.execute("UPDATE commitments SET executed_amount='900000.00' WHERE id=?", (commitment,))
        with self.assertRaises(APRefusal) as failure:
            self.contract.read(self.accountant, "commitments")
        self.assertEqual(failure.exception.code, "invalid_record")

    def test_same_total_sov_source_change_does_not_supply_an_executed_commitment(self):
        commitment = self.c.ap_practice_records["visible_commitment_ids"][0]
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='sov_lines'"):
            self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
        self.c.db.execute("UPDATE sov_lines SET description='Unrecorded change to contract scope' WHERE commitment_id=?", (commitment,))
        with self.assertRaises(APRefusal) as failure:
            self.contract.read(self.accountant, "commitments")
        self.assertEqual(failure.exception.code, "invalid_record")

    def test_action_source_requires_usd_even_before_a_detail_is_presented(self):
        bill_id = self.c.ap_practice_records["draft_bill_id"]
        project = self.c.bills.get(bill_id)["project_id"]
        self.c.db.execute("UPDATE projects SET currency='EUR' WHERE id=?", (project,))
        with self.assertRaises(APRefusal) as failure:
            self.contract.require_resource(self.accountant, "bill.requestApproval", bill_id)
        self.assertEqual(failure.exception.code, "unsupported_currency")

    def test_forged_commitment_version_has_no_executed_source(self):
        commitment = self.c.ap_practice_records["visible_commitment_ids"][0]
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='commitments'"):
            self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
        self.c.db.execute("UPDATE commitments SET version=900 WHERE id=?", (commitment,))
        with self.assertRaises(APRefusal) as failure:
            self.contract.read(self.accountant, "commitments")
        self.assertEqual(failure.exception.code, "invalid_record")

    def test_genuine_governed_changes_reconcile_amounts_and_original_sov_sources(self):
        commitment = self.c.ap_practice_records["visible_commitment_ids"][0]
        line = self.c.commitments.get(commitment)["sov"][0]["id"]
        for sov_line, amount in ((line, "200.01"), (None, "300.02")):
            change = self.c.commitments.propose_change(commitment, amount=amount, reason="Synthetic added scope", actor="practice.pm", sov_line_id=sov_line)
            approval = self.c.request_approval("change.execute", change["id"], actor_role="pm", requested_by="practice.pm")
            self.c.approve(approval["id"], approver="practice.bootstrap", approver_role="owner")
            self.c.execute(approval["id"], actor="practice.pm")
        row = next(row for row in self.contract.read(self.accountant, "commitments")["value"] if row["id"] == commitment)
        self.assertEqual(row["executedAmountCents"], 10050003)
        self.assertEqual(row["version"], 4)
        bill = self.contract.detail(self.accountant, self.c.ap_practice_records["draft_bill_id"])
        self.assertEqual((bill["status"], bill["effectiveStatus"]), ("draft", "stale"))

    def test_forged_closed_status_cannot_replace_a_genuine_closure(self):
        commitment = self.c.ap_practice_records["visible_commitment_ids"][0]
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='commitments'"):
            self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
        self.c.db.execute("UPDATE commitments SET status='closed',version=3 WHERE id=?", (commitment,))
        with self.assertRaises(APRefusal) as failure:
            self.contract.read(self.accountant, "commitments")
        self.assertEqual(failure.exception.code, "invalid_record")


if __name__ == "__main__":
    unittest.main()
