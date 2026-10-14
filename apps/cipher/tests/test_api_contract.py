"""Acceptance for the synthetic, read-only collection contract."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from apps.cipher import api_contract
from apps.cipher.core.approvals import build_manifest
from apps.cipher.core.money import money
from apps.cipher.service import Cipher


class PracticeReadContractTests(unittest.TestCase):
    def setUp(self):
        self.c = Cipher()
        self.addCleanup(self.c.db.close)
        party = self.c.add_party(kind="supplier", name="Synthetic Shared Supplier", destination="BANK-SECRET-DO-NOT-PRESENT")
        self.c.verify_destination(party["id"], destination="BANK-SECRET-DO-NOT-PRESENT", verified_by="owner")
        self.supplier = party["id"]
        self.alpha = self.c.create_project(name="Synthetic Alpha", entity="Synthetic LLC", budget="50000.33")
        self.beta = self.c.create_project(name="Synthetic Beta", entity="Synthetic LLC", budget="60000.44")
        self.c.open_period("P1", "October 2026", "2026-10-01", "2026-10-31")
        self.ca = self.commitment(self.alpha["id"], "Alpha piping", "9000.01", execute=True)
        self.cb = self.commitment(self.beta["id"], "Beta pumping", "10000.02", execute=True)
        self.draft = self.commitment(self.alpha["id"], "Alpha draft", "12.34")
        self.ba = self.bill(self.ca, "1000.01")
        self.c.approve_and_execute("bill.approve", self.ba["id"], period_id="P1")
        self.bb = self.bill(self.cb, "500.02")
        self.c.request_approval("bill.approve", self.bb["id"], actor_role="accountant")
        release = self.c.request_approval("payment.release", self.ba["id"], actor_role="treasury")
        self.c.approve(release["id"], approver="owner")

    def commitment(self, project_id, title, amount, *, execute=False):
        row = self.c.commitments.create(project_id=project_id, supplier_id=self.supplier, title=title,
                                        sov_lines=[{"description": title, "amount": amount}], actor="owner")
        if execute:
            self.c.approve_and_execute("commitment.execute", row["id"])
        return self.c.commitments.get(row["id"])

    def bill(self, commitment, amount):
        return self.c.bills.certify(commitment_id=commitment["id"], period_id="P1",
                                    installed=[{"sov_line_id": commitment["sov"][0]["id"], "cumulative_installed": amount}], actor="owner")

    def read(self, collection, **kwargs):
        return api_contract.practice_read(self.c, collection, **kwargs)

    def test_contract_names_practice_provenance_and_truthful_capabilities(self):
        result = api_contract.contract_snapshot(self.c)
        self.assertEqual(result["contractVersion"], "cipher.practice-read.v1")
        self.assertEqual((result["mode"], result["synthetic"], result["currency"], result["readOnly"]),
                         ("practice", True, "USD", True))
        self.assertEqual(result["capabilities"]["billApprovalEffect"], "posts_to_working_ledger")
        self.assertFalse(result["capabilities"]["separateBillApprovalAndPosting"])
        self.assertFalse(result["capabilities"]["authenticatedReadPermissions"])
        self.assertEqual(result["collections"], ["projects", "commitments", "bills", "approvals"])

    def test_file_workspaces_are_refused_instead_of_being_relabeled_practice(self):
        with tempfile.TemporaryDirectory() as directory:
            persisted = Cipher(os.path.join(directory, "workspace.sqlite"))
            try:
                for read in (lambda: api_contract.contract_snapshot(persisted),
                             lambda: api_contract.practice_read(persisted, "projects")):
                    with self.assertRaises(api_contract.PracticeReadRefusal) as raised:
                        read()
                    self.assertEqual(raised.exception.code, "unsupported_workspace")
                    self.assertEqual(raised.exception.target, "workspace")
                    self.assertEqual(raised.exception.message, raised.exception.value["message"])
                    self.assertNotIn(directory, raised.exception.message)
            finally:
                persisted.db.close()

    def test_all_reads_work_on_the_frozen_query_only_practice_fixture(self):
        with self.c.db._internal() as conn:
            conn.execute("PRAGMA query_only=ON")
        before = self.c.db.conn.total_changes
        api_contract.contract_snapshot(self.c)
        for collection in ("projects", "commitments", "bills", "approvals"):
            self.assertTrue(self.read(collection)["value"])
        self.assertEqual(self.c.db.conn.total_changes, before)
        self.assertEqual(self.c.db.one("PRAGMA query_only")["query_only"], 1)

    def test_approval_amount_is_the_known_operation_primary_amount(self):
        rows = self.read("approvals")["value"]
        commitment_approval = next(r for r in rows if r["operation"] == "commitment.execute" and r["subjectId"] == self.ca["id"])
        bill_approval = next(r for r in rows if r["operation"] == "bill.approve" and r["subjectId"] == self.ba["id"])
        self.assertEqual(commitment_approval["amountCents"], 900001)
        self.assertEqual(bill_approval["amountCents"], int(money(self.ba["amount_due"]) * 100))

    def test_other_currencies_and_unsafe_integer_totals_are_refused(self):
        self.c.db.execute("UPDATE projects SET currency='EUR' WHERE id=?", (self.beta["id"],))
        with self.assertRaises(api_contract.PracticeReadRefusal) as raised:
            self.read("projects")
        self.assertEqual(raised.exception.value["code"], "unsupported_currency")
        self.assertEqual(self.read("projects", project_id=self.alpha["id"])["count"], 1)
        self.c.db.execute("UPDATE projects SET currency='USD'")
        for number in range(10):
            self.c.create_project(name=f"Synthetic high-range {number}", entity="Synthetic LLC", budget="9999999999999.99")
        with self.assertRaises(api_contract.PracticeReadRefusal) as raised:
            self.read("projects")
        self.assertEqual(raised.exception.value["code"], "amount_out_of_range")

    def test_economic_rows_and_totals_reconcile_with_domains_using_integer_cents(self):
        projects = self.read("projects")
        self.assertEqual(projects["totals"]["budgetCents"], 11000077)
        commitments = self.read("commitments")
        expected = sum(int(money(self.c.commitments.executed_total(p["id"])) * 100) for p in (self.alpha, self.beta))
        self.assertEqual(commitments["totals"]["committedCents"], expected)
        self.assertEqual(commitments["count"], 3)
        self.assertEqual({r["id"]: r["status"] for r in commitments["value"]},
                         {r["id"]: r["status"] for r in (self.ca, self.cb, self.draft)})
        bills = self.read("bills")
        self.assertEqual(bills["totals"]["currentDueCents"], int(self.c.bills.open_payable(self.ba["id"]) * 100))
        self.assertEqual({r["id"]: r["status"] for r in bills["value"]}, {self.ba["id"]: "posted", self.bb["id"]: "draft"})
        for result in (projects, commitments, bills, self.read("approvals")):
            self.assertEqual((result["mode"], result["synthetic"], result["currency"]), ("practice", True, "USD"))
            for row in result["value"]:
                for key, value in row.items():
                    if key.endswith("Cents") and value is not None:
                        self.assertIs(type(value), int)
            for value in result["totals"].values():
                self.assertIs(type(value), int)

    def test_scope_filters_rows_counts_facets_and_totals_before_paging(self):
        result = self.read("commitments", project_id=self.alpha["id"], top=1)
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["value"]), 1)
        self.assertEqual(result["totals"]["committedCents"], 900001)
        self.assertEqual(result["facets"]["statuses"], [{"value": "draft", "count": 1}, {"value": "executed", "count": 1}])
        next_page = self.read("commitments", project_id=self.alpha["id"], top=1, cursor=result["nextCursor"])
        self.assertEqual(next_page["count"], result["count"])
        self.assertEqual(next_page["totals"], result["totals"])
        self.assertIsNone(next_page["nextCursor"])
        self.assertEqual({r["projectId"] for r in result["value"] + next_page["value"]}, {self.alpha["id"]})
        self.assertEqual(len({r["id"] for r in result["value"] + next_page["value"]}), 2)

    def test_status_and_search_filters_are_bounded_and_reflected_in_aggregates(self):
        result = self.read("commitments", status="executed", search="bEtA")
        self.assertEqual([r["id"] for r in result["value"]], [self.cb["id"]])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["totals"]["committedCents"], 1000002)
        self.assertEqual(result["facets"]["statuses"], [{"value": "executed", "count": 1}])
        self.assertEqual(self.read("commitments", search="' OR 1=1 --")["count"], 0)

    def test_approval_scope_is_derived_from_supported_subjects_and_conflicts_are_omitted(self):
        for operation, subject_type, subject_id, bindings in (
            ("unknown.operation", "project", self.alpha["id"], {}),
            ("bill.approve", "bill", "missing-bill", {"project_id": self.alpha["id"]}),
            ("bill.approve", "bill", self.bb["id"], {"project_id": self.alpha["id"]}),
            ("contract.require_agreements", "workspace", "workspace", {}),
        ):
            self.c.approvals.request(build_manifest(operation=operation, subject_type=subject_type, subject_id=subject_id,
                                                    actor_role="owner", bindings=bindings), requested_by="owner")
        rows = self.read("approvals", project_id=self.alpha["id"])
        self.assertTrue(rows["value"])
        self.assertEqual({r["projectId"] for r in rows["value"]}, {self.alpha["id"]})
        all_rows = self.read("approvals")
        self.assertEqual(all_rows["count"], 5)
        self.assertTrue(all(r["projectId"] is not None for r in all_rows["value"]))
        self.assertNotIn("unknown.operation", {r["operation"] for r in all_rows["value"]})

    def test_presenters_never_serialize_credentials_destinations_or_raw_manifests(self):
        results = [api_contract.contract_snapshot(self.c)] + [self.read(name) for name in ("projects", "commitments", "bills", "approvals")]
        text = json.dumps(results)
        self.assertNotIn("BANK-SECRET-DO-NOT-PRESENT", text)
        for forbidden in ("manifest", "nonce", "destination", "material_hash", "manifest_hash", "actor_role", "policy_version"):
            self.assertNotIn('"' + forbidden + '"', text)
        for approval in self.c.approvals.list():
            self.assertNotIn(approval["nonce"], text)
            self.assertNotIn(approval["material_hash"], text)

    def test_reads_and_typed_refusals_do_not_mutate_any_workspace_state(self):
        before = (tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes, self.c.audit.verify_chain(),
                  len(self.c.provider.submissions), len(self.c.provider.transfers))
        with patch.object(self.c, "_manifest", side_effect=AssertionError("reads must not rebuild approval manifests")):
            api_contract.contract_snapshot(self.c)
            for collection in ("projects", "commitments", "bills", "approvals"):
                self.read(collection, top=1)
            with self.assertRaises(api_contract.PracticeReadRefusal):
                self.read("payments")
            with self.assertRaises(api_contract.PracticeReadRefusal):
                self.read("bills", project_id="missing-project")
        after = (tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes, self.c.audit.verify_chain(),
                 len(self.c.provider.submissions), len(self.c.provider.transfers))
        self.assertEqual(after, before)

    def test_request_validation_uses_typed_refusals_without_echoing_untrusted_input(self):
        for collection, kwargs, target in (
            ("bank-secret", {}, "collection"), (True, {}, "collection"),
            ("bills", {"top": True}, "top"), ("bills", {"top": 0}, "top"),
            ("bills", {"top": 101}, "top"), ("bills", {"top": "1"}, "top"),
            ("bills", {"status": True}, "status"), ("bills", {"status": "bank-secret"}, "status"),
            ("projects", {"status": "draft"}, "status"), ("bills", {"project_id": True}, "projectId"),
            ("bills", {"search": []}, "search"), ("bills", {"search": "x" * 201}, "search"),
            ("bills", {"cursor": True}, "cursor"), ("bills", {"cursor": "bank-secret"}, "cursor"),
            ("bills", {"cursor": "x" * 1025}, "cursor"),
        ):
            with self.subTest(collection=collection, kwargs=kwargs):
                with self.assertRaises(api_contract.PracticeReadRefusal) as raised:
                    self.read(collection, **kwargs)
                error = raised.exception.value
                self.assertEqual(error["target"], target)
                self.assertIsInstance(error["code"], str)
                self.assertNotIn("bank-secret", json.dumps(error))

    def test_cursor_cannot_be_reused_with_a_different_collection_scope_or_filter(self):
        cursor = self.read("commitments", top=1)["nextCursor"]
        for collection, kwargs in (("bills", {}), ("commitments", {"project_id": self.alpha["id"]}),
                                   ("commitments", {"status": "executed"}), ("commitments", {"top": 2})):
            with self.subTest(collection=collection, kwargs=kwargs):
                with self.assertRaises(api_contract.PracticeReadRefusal):
                    self.read(collection, cursor=cursor, **({"top": 1} | kwargs))

    def test_identical_timestamps_have_deterministic_id_order(self):
        expected = sorted(r["id"] for r in self.c.db.query("SELECT id FROM commitments"))
        self.c.db.execute("UPDATE commitments SET created_at='2026-10-01T00:00:00Z'")
        self.assertEqual([r["id"] for r in self.read("commitments")["value"]], expected)


if __name__ == "__main__":
    unittest.main()
