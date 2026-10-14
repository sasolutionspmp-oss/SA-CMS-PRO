"""Accounting admission upgrades preserve original AP/source history and quarantine."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.ap_actions import APActionRunner
from apps.cipher.ap_contract import APContract
from apps.cipher.ap_exception_actions import APExceptionActionRunner
from apps.cipher.ap_exception_contract import APExceptionContract
from apps.cipher.ap_exception_preflight import APExceptionPreflight
from apps.cipher.ap_intake_actions import APIntakeActionRunner
from apps.cipher.ap_intake_contract import APIntakeContract
from apps.cipher.ap_intake_preflight import APIntakePreflight
from apps.cipher.ap_preflight import APPreflight
from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
from apps.cipher.accounting_worker import WorkerHeld, create_practice_accounting_worker
from apps.cipher.core import db as core_db
from apps.cipher.core.ids import loads
from apps.cipher.service import Cipher
from apps.cipher.tests import test_api_receipt_upgrade as old_upgrade


class APIAccountingUpgradeTests(unittest.TestCase):
    secret = b"accounting-upgrade-proof-server-key-at-least-32-bytes"

    def original_workspace(self):
        helper = old_upgrade.APIReceiptUpgradeTests("runTest")
        self.addCleanup(helper.doCleanups)
        c = helper.intake_workspace()
        historical = [entry for entry in core_db.SCHEMA_CATALOG if entry[0] <= 69]
        with patch.object(core_db, "SCHEMA_CATALOG", historical):
            c.db.migrate()
        self.assertEqual(c.db.schema_status()["current_version"], 69)
        base = APContract(c, secret=self.secret)
        intake = APIntakeContract(c, base, secret=self.secret)
        exceptions = APExceptionContract(c, base, intake, secret=self.secret)
        preflight = APExceptionPreflight(c, exceptions, secret=self.secret)
        runner = APExceptionActionRunner(c, exceptions, preflight)
        intake_preflight = APIntakePreflight(c, intake, secret=self.secret)
        intake_runner = APIntakeActionRunner(c, intake, intake_preflight)
        persons = c.ap_practice_persona_people

        def run(action, resource, body=None, *, person="accountant", receive=False):
            person_id, body = persons[person]["person_id"], body or {}
            active_review = intake_preflight if receive else preflight
            active_runner = intake_runner if receive else runner
            review = active_review.review(person_id, action, resource, body)
            self.assertTrue(review["allowed"], review)
            return active_runner.run(person_id, action, resource, dict(body, fingerprint=review["fingerprint"]),
                                     repeatability_key=str(uuid4()), if_match=review["resourceVersion"])["result"]

        prepared = loads(c.db.one("SELECT result_json FROM ap_action_receipts WHERE fixed_action='bill.prepare'")["result_json"])
        original_bill = c.bills.get(prepared["billId"])
        run("bill.prepareCorrection", original_bill["id"], {"reason": "Synthetic original-period handoff correction"})
        requested = run("bill.requestCorrection", original_bill["id"])
        run("bill.approveCorrection", requested["approvalId"], person="reviewer")
        run("bill.executeCorrection", requested["approvalId"], {"periodId": "2026-11"})
        invoice = c.plugin("ap_intake").invoice(original_bill["supplier_invoice_id"])
        run("invoice.revise", invoice["id"], {"reason": "Synthetic corrected invoice amount",
            "invoiceNumber": "SYNTHETIC-UPGRADE-69-REVISED", "invoiceDate": invoice["invoice_date"],
            "amountCents": prepared["amountDueCents"] + 1, "evidenceRevisionId": invoice["evidence_revision_id"]})
        run("invoice.reject", invoice["id"], {"reason": "Synthetic reissued invoice withdrawn"})
        commitment_id = c.ap_practice_records["prep_commitment_id"]
        revisions = c.ap_practice_records["visible_invoice_evidence_revision_ids"]
        for index in range(2):
            received = run("invoice.receive", commitment_id, {"invoiceNumber": f"SYNTHETIC-UPGRADE-69-DUP-{index}",
                "invoiceDate": "2026-10-14", "amountCents": 100, "evidenceRevisionId": revisions[index]}, receive=True)
        run("invoice.reviewDuplicate", received["invoiceId"], {"reason": "Synthetic distinct supplier obligation confirmed"})
        run("bill.cancel", c.ap_practice_records["draft_bill_id"], {"reason": "Synthetic draft withdrawn"})
        run("bill.cancel", c.ap_practice_records["approved_bill_id"], {"reason": "Synthetic original PM withdrawal"}, person="pm")
        self.assertEqual(len({row["fixed_action"] for row in c.db.query("SELECT fixed_action FROM ap_action_receipts")}), 17)
        self.assertTrue(all(check["ok"] for check in runner.integrity_checks()))
        return c

    @staticmethod
    def copy_to(c, target):
        with sqlite3.connect(target) as destination:
            c.db.conn.backup(destination)

    def test_accounting_schema_and_worker_reservations_follow_original_ap_history(self):
        c = Cipher()
        self.addCleanup(c.db.close)
        names = [(version, name) for version, name, _sql in core_db.SCHEMA_CATALOG]
        self.assertEqual(names[68:71], [
            (69, "ap_practice_exception_action_receipts"),
            (70, "accounting_practice_delivery"),
            (71, "ap_practice_accounting_action_receipts"),
        ])
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM ap_accounting_invocations"), 0)
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM accounting_intents"), 0)
        self.assertEqual(c.provider.submissions, [])

    def test_all_seventeen_original_actions_keep_receipts_and_source_proof_after_accounting_upgrade(self):
        original = self.original_workspace()
        receipts = original.db.query("SELECT * FROM ap_action_receipts ORDER BY id")
        schemas = original.db.query("SELECT * FROM schema_version ORDER BY version")
        audit = original.db.query("SELECT * FROM audit_log ORDER BY seq")
        journals = original.db.query("SELECT * FROM journals ORDER BY id")
        lines = original.db.query("SELECT * FROM journal_lines ORDER BY id")
        with tempfile.TemporaryDirectory(prefix="cipher-accounting-upgrade-") as directory:
            target = Path(directory) / "copy.sqlite"
            self.copy_to(original, target)
            upgraded = Cipher(str(target))
            try:
                self.assertEqual(upgraded.db.query("SELECT * FROM ap_action_receipts ORDER BY id"), receipts)
                self.assertEqual(upgraded.db.query("SELECT * FROM schema_version WHERE version<=69 ORDER BY version"), schemas)
                self.assertEqual(upgraded.db.query("SELECT * FROM audit_log WHERE seq<=? ORDER BY seq", (audit[-1]["seq"],)), audit)
                self.assertEqual(upgraded.db.query("SELECT * FROM journals ORDER BY id"), journals)
                self.assertEqual(upgraded.db.query("SELECT * FROM journal_lines ORDER BY id"), lines)
                self.assertEqual(upgraded.db.scalar("SELECT COUNT(*) FROM accounting_intents"), 0)
                self.assertEqual(upgraded.db.scalar("SELECT COUNT(*) FROM ap_accounting_invocations"), 0)
                self.assertTrue(upgraded.db.read_only)
                self.assertFalse(upgraded.db.has_write_authority())
                self.assertEqual(upgraded.db.scalar("PRAGMA query_only"), 1)
                base = APContract(upgraded, secret=self.secret)
                intake = APIntakeContract(upgraded, base, secret=self.secret)
                exceptions = APExceptionContract(upgraded, base, intake, secret=self.secret)
                runners = [
                    APActionRunner(upgraded, base, APPreflight(upgraded, base, secret=self.secret)),
                    APIntakeActionRunner(upgraded, intake, APIntakePreflight(upgraded, intake, secret=self.secret)),
                    APExceptionActionRunner(upgraded, exceptions, APExceptionPreflight(upgraded, exceptions, secret=self.secret)),
                ]
                self.assertTrue(all(check["ok"] for runner in runners for check in runner.integrity_checks()))
                self.assertTrue(upgraded.audit.verify_chain()["ok"])
                self.assertEqual(upgraded.provider.submissions, [])
                with self.assertRaises(core_db.WriteAuthorityError):
                    upgraded.db.execute("DELETE FROM ap_action_receipts")
            finally:
                upgraded.db.close()

    def test_later_failed_entry_rolls_back_accounting_and_worker_admission_with_all_original_guards(self):
        original = self.original_workspace()
        before = tuple(original.db.conn.iterdump())
        failed = list(core_db.SCHEMA_CATALOG) + [
            (core_db.SCHEMA_CATALOG[-1][0] + 1, "accounting_upgrade_failure_test_only", ["SELECT * FROM absent_accounting_upgrade_test_table"])]
        with tempfile.TemporaryDirectory(prefix="cipher-accounting-upgrade-rollback-") as directory:
            target = Path(directory) / "copy.sqlite"
            self.copy_to(original, target)
            with patch.object(core_db, "SCHEMA_CATALOG", failed):
                with self.assertRaises(sqlite3.OperationalError):
                    core_db.Database(str(target))
            with sqlite3.connect(target) as inspected:
                self.assertEqual(tuple(inspected.iterdump()), before)
                self.assertEqual(inspected.execute("SELECT MAX(version) FROM schema_version").fetchone()[0], 69)

    def test_schema70_original_plan_and_simulated_delivery_history_survive_later_api_admission(self):
        historical = [entry for entry in core_db.SCHEMA_CATALOG if entry[0] <= 70]
        with patch.object(core_db, "SCHEMA_CATALOG", historical):
            original = make_ap_practice_fixture()
        self.addCleanup(original.db.close)
        bill_id = original.ap_practice_records["approved_bill_id"]
        original.post_bill(bill_id, actor="practice.accountant", actor_role="accountant", period_id="2026-10")
        domain = original.plugin("accounting")
        bill = original.bills.get(bill_id)
        mapping = domain.prepare_synthetic_mapping(bill["project_id"], actor="practice.accountant", reason="Synthetic original accounting mapping")
        plan = domain.prepare(bill_id, mapping["id"], actor="practice.accountant")
        approval = original.request_approval("accounting.queue", plan["id"], actor_role="accountant", requested_by="practice.accountant")
        original.approve(approval["id"], approver="practice.reviewer", approver_role="accountant")
        intent_id = original.execute(approval["id"], actor="practice.accountant").result["intent_id"]
        worker = create_practice_accounting_worker(original)
        worker.deliver_once(intent_id, actor="practice.accountant")
        worker.reconcile_once(intent_id, actor="practice.accountant")
        tables = ["accounting_mapping_versions", "accounting_plans", "accounting_intents", "accounting_leases",
                  "accounting_attempts", "accounting_attempt_results", "accounting_acceptances", "accounting_reconciliations"]
        rows = {table: original.db.query(f"SELECT * FROM {table} ORDER BY id") for table in tables}
        audit = original.db.query("SELECT * FROM audit_log ORDER BY seq")
        journals = original.db.query("SELECT * FROM journals ORDER BY id")
        with tempfile.TemporaryDirectory(prefix="cipher-accounting-history-upgrade-") as directory:
            target = Path(directory) / "copy.sqlite"
            self.copy_to(original, target)
            upgraded = Cipher(str(target))
            try:
                self.assertEqual({table: upgraded.db.query(f"SELECT * FROM {table} ORDER BY id") for table in tables}, rows)
                self.assertEqual(upgraded.db.query("SELECT * FROM audit_log WHERE seq<=? ORDER BY seq", (audit[-1]["seq"],)), audit)
                self.assertEqual(upgraded.db.query("SELECT * FROM journals ORDER BY id"), journals)
                self.assertEqual(upgraded.plugin("accounting").intent(intent_id)["status"], "reconciled")
                self.assertEqual(upgraded.plugin("accounting").plan(plan["id"])["payload"], plan["payload"])
                self.assertEqual(upgraded.db.scalar("SELECT COUNT(*) FROM ap_accounting_invocations"), 0)
                self.assertTrue(upgraded.db.read_only)
                self.assertFalse(upgraded.db.has_write_authority())
                with self.assertRaisesRegex(WorkerHeld, "accounting_worker_unavailable"):
                    create_practice_accounting_worker(upgraded)
                self.assertEqual(upgraded.provider.submissions, [])
            finally:
                upgraded.db.close()


if __name__ == "__main__":
    unittest.main()
