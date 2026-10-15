"""Commercial admission preserves genuine AP and unfinished accounting history."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.ap_accounting_actions import APAccountingActionRunner, invocation_inventory_proof
from apps.cipher.ap_accounting_contract import APAccountingContract
from apps.cipher.ap_accounting_preflight import APAccountingPreflight
from apps.cipher.ap_contract import APContract
from apps.cipher.ap_exception_contract import APExceptionContract
from apps.cipher.ap_intake_contract import APIntakeContract
from apps.cipher.accounting_simulator import Fault
from apps.cipher.accounting_worker import WorkerHeld, create_practice_accounting_worker
from apps.cipher.commercial_receipts import commercial_receipt_inventory_proof
from apps.cipher.core import db as core_db
from apps.cipher.core.api_receipts import APIActionReceipts
from apps.cipher.core.ids import hash_json, loads
from apps.cipher.domain import commercial
from apps.cipher.service import Cipher
from apps.cipher.tests import test_api_receipt_upgrade as old_upgrade


# Captured from the genuine 71-entry engine before commercial registration.
# This binds original SQL text and entry order, independently of migration rows.
HISTORICAL_71_HASH = "8b48d3f83d00ab2d41de142b52cb6e6831cb9ced7b97ece7e88aa7f7dae1e551"
COMMERCIAL_TABLES = (
    "commercial_estimate_sources", "commercial_line_sources", "commercial_packages",
    "commercial_handoffs", "commercial_commitment_sources", "commercial_action_receipts",
)
ACCOUNTING_TABLES = (
    "accounting_mapping_versions", "accounting_plans", "accounting_intents", "accounting_leases",
    "accounting_attempts", "accounting_attempt_results", "accounting_acceptances",
    "accounting_reconciliations", "ap_accounting_invocations",
)


class CommercialUpgradeTests(unittest.TestCase):
    secret = b"commercial-upgrade-proof-secret-at-least-32-bytes"

    def original_workspace(self):
        """Use real people, reviews, approvals, effects and durable API claims."""
        helper = old_upgrade.APIReceiptUpgradeTests("runTest")
        self.addCleanup(helper.doCleanups)
        c = helper.intake_workspace()
        historical = [entry for entry in core_db.SCHEMA_CATALOG if entry[0] <= 71]
        with patch.object(core_db, "SCHEMA_CATALOG", historical):
            c.db.migrate()
        self.assertEqual(c.db.schema_status()["current_version"], 71)
        base = APContract(c, secret=self.secret)
        intake = APIntakeContract(c, base, secret=self.secret)
        exceptions = APExceptionContract(c, base, intake, secret=self.secret)
        domain = c.plugin("accounting")
        worker = create_practice_accounting_worker(c)
        contract = APAccountingContract(c, base, intake, exceptions, secret=self.secret, worker=worker)
        preflight = APAccountingPreflight(c, contract, secret=self.secret, worker=worker)
        runner = APAccountingActionRunner(c, contract, preflight, worker=worker)
        people = c.ap_practice_persona_people

        def run(action, resource, *, person="accountant"):
            person_id = people[person]["person_id"]
            review = preflight.review(person_id, action, resource, {})
            self.assertTrue(review["allowed"], review)
            args = {"person_id": person_id, "action": action, "resource_id": resource,
                    "body": {"fingerprint": review["fingerprint"]},
                    "repeatability_key": str(uuid4()), "if_match": review["resourceVersion"]}
            return runner.run(**args), args

        def queue(bill_id):
            bill = c.bills.get(bill_id)
            domain.prepare_synthetic_mapping(bill["project_id"], actor="practice.accountant",
                                             reason="Synthetic commercial upgrade proof")
            prepared, _ = run("accounting.prepare", bill_id)
            requested, _ = run("accounting.request", prepared["result"]["planId"])
            approval_id = requested["result"]["approvalId"]
            run("accounting.approve", approval_id, person="reviewer")
            queued, _ = run("accounting.queue", approval_id)
            return queued["result"]["intentId"]

        posted = loads(c.db.one("SELECT result_json FROM ap_action_receipts WHERE fixed_action='bill.post'")["result_json"])
        reconciled_intent = queue(posted["billId"])
        worker._adapter.queue_fault("submit", Fault.TIMEOUT_AFTER_ACCEPTANCE)
        unknown, _ = run("accounting.deliver", reconciled_intent)
        self.assertEqual(unknown["result"]["status"], "outcome_unknown")
        accepted, _ = run("accounting.lookup", reconciled_intent)
        self.assertEqual(accepted["result"]["status"], "simulated_accepted")
        reconciled, _ = run("accounting.reconcile", reconciled_intent)
        self.assertEqual(reconciled["result"]["status"], "reconciled")

        second_bill = c.ap_practice_records["approved_bill_id"]
        c.post_bill(second_bill, actor="practice.accountant", period_id="2026-10",
                    reason="Synthetic pending accounting upgrade source")
        pending_intent = queue(second_bill)
        # The real API claim commits and the concrete simulator accepts. A local
        # observation failure leaves a genuine unfinished claim, not a forged row.
        with patch.object(domain, "finish_attempt", side_effect=RuntimeError("Synthetic local persistence fault")):
            pending, pending_args = run("accounting.deliver", pending_intent)
        self.assertEqual(pending["state"], "claimed")
        self.assertNotIn("receiptId", pending)
        self.assertEqual(worker._adapter._store.effect_count, 2)
        self.assertEqual(worker._adapter.calls, {"submit": 2, "lookup": 1, "read_record": 1})
        self.assertTrue(all(row["ok"] for row in runner.integrity_checks()))
        invocations = invocation_inventory_proof(c.db, c.audit)
        self.assertEqual([row["state"] for row in invocations].count("completed"), 3)
        self.assertEqual([row["state"] for row in invocations].count("claimed"), 1)
        return c, worker, reconciled_intent, pending_intent, pending_args

    @staticmethod
    def copy_to(c, target):
        with sqlite3.connect(target) as destination:
            c.db.conn.backup(destination)

    @staticmethod
    def rows(c):
        names = ("ap_action_receipts", "journals", "journal_lines", "bill_posting_receipts", *ACCOUNTING_TABLES)
        return {table: c.db.query(f"SELECT * FROM {table} ORDER BY id") for table in names}

    def assert_quarantined(self, c):
        self.assertTrue(c.db.read_only)
        self.assertFalse(c.db.has_write_authority())
        self.assertEqual(c.db.scalar("PRAGMA query_only"), 1)
        self.assertEqual(c.provider.submissions, [])
        with self.assertRaisesRegex(WorkerHeld, "accounting_worker_unavailable"):
            create_practice_accounting_worker(c)
        with self.assertRaises(core_db.WriteAuthorityError):
            c.db.execute("DELETE FROM commercial_action_receipts")

    def test_schema72_and73_append_after_exact_original_sql_and_checksums(self):
        prefix = [(version, name, list(sql)) for version, name, sql in core_db.SCHEMA_CATALOG if version <= 71]
        self.assertEqual(len(prefix), 71)
        self.assertEqual(hash_json(prefix), HISTORICAL_71_HASH)
        self.assertEqual([(v, n, len(sql), core_db.catalog_checksum(sql)) for v, n, sql in core_db.SCHEMA_CATALOG[71:73]], [
            (72, "commercial_manual_sources_and_handoffs", 20, "f6cf329361ced5bfc78bb96b57f81bff7d4d74acd14ccb3d2556883163d1d3f7"),
            (73, "commercial_practice_action_receipts", 4, "a7f97fa4c298fa5ef13a632b38c3ab7bcfb9e158fd5c392844a8957256857ca9"),
        ])
        c = Cipher()
        self.addCleanup(c.db.close)
        schemas = c.db.query("SELECT version,name,statement_count,checksum FROM schema_version WHERE version<=71 ORDER BY version")
        self.assertEqual(schemas, [{"version": v, "name": n, "statement_count": len(sql),
                                   "checksum": core_db.catalog_checksum(sql)} for v, n, sql in prefix])
        self.assertTrue(all(c.db.scalar(f"SELECT COUNT(*) FROM {table}") == 0 for table in COMMERCIAL_TABLES))
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM accounting_intents"), 0)
        self.assertEqual(c.provider.submissions, [])

    def test_genuine71_receipts_pending_claim_and_accepted_readback_survive_upgrade(self):
        original, worker, reconciled, pending, pending_args = self.original_workspace()
        rows = self.rows(original)
        schema_objects = original.db.query("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")
        schemas = original.db.query("SELECT * FROM schema_version ORDER BY version")
        audit = original.db.query("SELECT * FROM audit_log ORDER BY seq")
        provider_before = dict(worker._adapter.calls), worker._adapter._store.effect_count
        with tempfile.TemporaryDirectory(prefix="cipher-commercial-upgrade-") as directory:
            target = Path(directory) / "copy.sqlite"
            self.copy_to(original, target)
            upgraded = Cipher(str(target))
            try:
                self.assertEqual(self.rows(upgraded), rows)
                for item in schema_objects:
                    self.assertEqual(upgraded.db.one("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name=?", (item["name"],)), item)
                self.assertEqual(upgraded.db.query("SELECT * FROM schema_version WHERE version<=71 ORDER BY version"), schemas)
                self.assertEqual(upgraded.db.query("SELECT * FROM audit_log WHERE seq<=? ORDER BY seq", (audit[-1]["seq"],)), audit)
                migrated = upgraded.db.query("SELECT * FROM audit_log WHERE seq>? ORDER BY seq", (audit[-1]["seq"],))
                self.assertEqual([event["action"] for event in migrated], ["workspace.schema_migrated_without_authority"])
                entries = loads(migrated[0]["payload_json"])["entries"]
                appended = [(row["version"], row["name"]) for row in entries]
                self.assertEqual(appended[:2], [
                    (72, "commercial_manual_sources_and_handoffs"), (73, "commercial_practice_action_receipts")])
                self.assertEqual(appended, [(version, name) for version, name, _sql in core_db.SCHEMA_CATALOG[71:]])
                self.assertEqual(upgraded.plugin("accounting").intent(reconciled)["status"], "reconciled")
                inventory = invocation_inventory_proof(upgraded.db, upgraded.audit)
                unfinished = next(row for row in inventory if row["repeatability_uuid"] == pending_args["repeatability_key"])
                self.assertEqual(unfinished["resource_id"], pending)
                self.assertEqual(unfinished["state"], "claimed")
                self.assertIsNone(unfinished["receipt_id"])
                self.assertEqual(commercial_receipt_inventory_proof(upgraded.db, upgraded.audit), [])
                self.assertTrue(all(row["ok"] for row in APIActionReceipts(upgraded.db, upgraded.audit).integrity_checks()))
                self.assertTrue(upgraded.audit.verify_chain()["ok"])
                self.assertTrue(all(upgraded.db.scalar(f"SELECT COUNT(*) FROM {table}") == 0 for table in COMMERCIAL_TABLES))
                self.assert_quarantined(upgraded)
            finally:
                upgraded.db.close()
        self.assertEqual((dict(worker._adapter.calls), worker._adapter._store.effect_count), provider_before)

    def test_failed74_rolls_back72_73_and_all_original_rows_guards_and_claims(self):
        original, worker, _reconciled, _pending, _args = self.original_workspace()
        before = tuple(original.db.conn.iterdump())
        provider_before = dict(worker._adapter.calls), worker._adapter._store.effect_count
        failed_catalog = list(core_db.SCHEMA_CATALOG[:73]) + [(74, "commercial_upgrade_failure_test_only", [
            "CREATE TABLE commercial_upgrade_partial_test_only (id INTEGER)",
            "SELECT * FROM absent_commercial_upgrade_test_table",
        ])]
        with tempfile.TemporaryDirectory(prefix="cipher-commercial-upgrade-rollback-") as directory:
            target = Path(directory) / "copy.sqlite"
            self.copy_to(original, target)
            with patch.object(core_db, "SCHEMA_CATALOG", failed_catalog):
                with self.assertRaises(sqlite3.OperationalError):
                    core_db.Database(str(target))
            with sqlite3.connect(target) as inspected:
                self.assertEqual(tuple(inspected.iterdump()), before)
                self.assertEqual(inspected.execute("SELECT MAX(version) FROM schema_version").fetchone()[0], 71)
                self.assertEqual(inspected.execute("SELECT name FROM sqlite_master WHERE name LIKE 'commercial_%'").fetchall(), [])
            self.assertFalse(Path(str(target) + ".authority").exists())
        self.assertEqual((dict(worker._adapter.calls), worker._adapter._store.effect_count), provider_before)

    def test_current73_copy_opens_byte_preserving_without_worker_or_domain_writes(self):
        original, worker, _reconciled, _pending, _args = self.original_workspace()
        original.db.migrate()
        before_dump = tuple(original.db.conn.iterdump())
        provider_before = dict(worker._adapter.calls), worker._adapter._store.effect_count
        with tempfile.TemporaryDirectory(prefix="cipher-commercial-current-copy-") as directory:
            target = Path(directory) / "copy.sqlite"
            self.copy_to(original, target)
            before_bytes = target.read_bytes()
            with sqlite3.connect(target) as inspected:
                self.assertEqual(inspected.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            for attempt in range(2):
                with self.subTest(attempt=attempt):
                    with patch("apps.cipher.accounting_simulator.SimulatedAccountingAdapter",
                               side_effect=AssertionError("A copied file initialized an accounting provider")) as adapter_factory:
                        copied = Cipher(str(target))
                        adapter_factory.assert_not_called()
                    try:
                        self.assertEqual(tuple(copied.db.conn.iterdump()), before_dump)
                        with patch("apps.cipher.accounting_simulator.SimulatedAccountingAdapter",
                                   side_effect=AssertionError("A copied file initialized an accounting provider")) as adapter_factory:
                            self.assert_quarantined(copied)
                            adapter_factory.assert_not_called()
                        domain = commercial.Plugin(copied)
                        project = copied.db.one("SELECT id FROM projects ORDER BY id")["id"]
                        supplier = copied.db.one("SELECT id FROM parties WHERE kind='supplier' ORDER BY id")["id"]
                        with self.assertRaises(core_db.WriteAuthorityError):
                            domain.declare_package(project, supplier, "Synthetic refused copy package", "0.10",
                                                   actor="practice.pm", reason="Synthetic copy write refusal")
                        self.assertEqual(tuple(copied.db.conn.iterdump()), before_dump)
                        self.assertEqual(target.read_bytes(), before_bytes)
                    finally:
                        copied.db.close()
                    self.assertEqual(target.read_bytes(), before_bytes)
                    self.assertFalse(Path(str(target) + ".authority").exists())
                    self.assertFalse(Path(str(target) + "-wal").exists())
        self.assertEqual((dict(worker._adapter.calls), worker._adapter._store.effect_count), provider_before)


if __name__ == "__main__":
    unittest.main()
