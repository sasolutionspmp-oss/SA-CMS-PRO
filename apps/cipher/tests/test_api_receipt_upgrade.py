"""Receipt expansion preserves original financial proof and quarantine."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.ap_actions import APActionRunner
from apps.cipher.ap_contract import APContract
from apps.cipher.ap_intake_actions import APIntakeActionRunner
from apps.cipher.ap_intake_contract import APIntakeContract
from apps.cipher.ap_intake_preflight import APIntakePreflight
from apps.cipher.ap_preflight import APPreflight
from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
from apps.cipher.core import db as core_db
from apps.cipher.core.api_receipts import APIActionReceipts, APIReceiptIntegrityError
from apps.cipher.service import Cipher


class APIReceiptUpgradeTests(unittest.TestCase):
    secret = b"receipt-upgrade-test-server-secret-at-least-32-bytes"

    def original_workspace(self):
        historical = [entry for entry in core_db.SCHEMA_CATALOG if entry[0] <= 67]
        self.assertEqual(historical[-1][1], "ap_practice_action_receipts")
        with patch.object(core_db, "SCHEMA_CATALOG", historical):
            c = make_ap_practice_fixture()
        self.addCleanup(c.db.close)
        contract = APContract(c, secret=self.secret)
        preflight = APPreflight(c, contract, secret=self.secret)
        runner = APActionRunner(c, contract, preflight)
        accountant = c.ap_practice_persona_people["accountant"]["person_id"]
        pm = c.ap_practice_persona_people["pm"]["person_id"]
        bill_id = c.ap_practice_records["draft_bill_id"]

        def run(person, action, resource, body=None):
            body = body or {}
            reviewed = preflight.review(person, action, resource, body)
            self.assertTrue(reviewed["allowed"], reviewed)
            return runner.run(person, action, resource,
                              dict(body, fingerprint=reviewed["fingerprint"]),
                              repeatability_key=str(uuid4()), if_match=reviewed["resourceVersion"])

        requested = run(accountant, "bill.requestApproval", bill_id)
        run(pm, "bill.approve", requested["result"]["approvalId"])
        run(accountant, "bill.post", bill_id, {"periodId": "2026-10", "reason": ""})
        self.assertTrue(all(row["ok"] for row in runner.integrity_checks()))
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM ap_action_receipts"), 3)
        return c

    def copy_to(self, c, target):
        with sqlite3.connect(target) as destination:
            c.db.conn.backup(destination)

    def intake_workspace(self):
        historical = [entry for entry in core_db.SCHEMA_CATALOG if entry[0] <= 68]
        self.assertEqual(historical[-1][1], "ap_practice_preparation_action_receipts")
        with patch.object(core_db, "SCHEMA_CATALOG", historical):
            c = make_ap_practice_fixture()
        self.addCleanup(c.db.close)
        base = APContract(c, secret=self.secret)
        old_preflight = APPreflight(c, base, secret=self.secret)
        old_runner = APActionRunner(c, base, old_preflight)
        intake = APIntakeContract(c, base, secret=self.secret)
        preflight = APIntakePreflight(c, intake, secret=self.secret)
        runner = APIntakeActionRunner(c, intake, preflight)
        persons = c.ap_practice_persona_people

        def run(action, resource, body=None, *, person="accountant", original=False):
            person_id = persons[person]["person_id"]
            active_preflight = old_preflight if original else preflight
            active_runner = old_runner if original else runner
            body = body or {}
            review = active_preflight.review(person_id, action, resource, body)
            self.assertTrue(review["allowed"], review)
            return active_runner.run(person_id, action, resource, dict(body, fingerprint=review["fingerprint"]),
                                     repeatability_key=str(uuid4()), if_match=review["resourceVersion"])["result"]

        commitment_id = c.ap_practice_records["prep_commitment_id"]
        commitment = c.commitments.get(commitment_id)
        prepared = run("bill.prepare", commitment_id, {"periodId": "2026-10", "installed": [
            {"sovLineId": line["id"], "cumulativeInstalledCents": amount}
            for line, amount in zip(commitment["sov"], (100000, 200000))]})
        invoice = run("invoice.receive", commitment_id, {"invoiceNumber": "SYNTHETIC-UPGRADE-68", "invoiceDate": "2026-10-14",
                       "amountCents": prepared["amountDueCents"],
                       "evidenceRevisionId": c.ap_practice_records["visible_invoice_evidence_revision_ids"][0]})
        run("invoice.computeMatch", invoice["invoiceId"])
        match = run("invoice.requestMatchApproval", invoice["invoiceId"])
        run("invoice.approveMatch", match["approvalId"], person="reviewer")
        run("invoice.executeMatch", match["approvalId"])
        business = run("bill.requestApproval", prepared["billId"], original=True)
        run("bill.approve", business["approvalId"], person="pm", original=True)
        run("bill.post", prepared["billId"], {"periodId": "2026-10", "reason": ""}, original=True)
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM ap_action_receipts"), 9)
        self.assertTrue(all(row["ok"] for row in runner.integrity_checks() + old_runner.integrity_checks()))
        return c

    def test_nine_authentic_schema68_receipts_keep_original_source_proof_under_exception_upgrade(self):
        original = self.intake_workspace()
        receipts = original.db.query("SELECT * FROM ap_action_receipts ORDER BY id")
        schemas = original.db.query("SELECT * FROM schema_version ORDER BY version")
        audit = original.db.query("SELECT * FROM audit_log ORDER BY seq")
        journals = original.db.query("SELECT * FROM journals ORDER BY id")
        with tempfile.TemporaryDirectory(prefix="cipher-exception-receipt-upgrade-") as directory:
            target = Path(directory) / "copy.sqlite"
            self.copy_to(original, target)
            upgraded = Cipher(str(target))
            try:
                self.assertEqual(upgraded.db.query("SELECT * FROM ap_action_receipts ORDER BY id"), receipts)
                self.assertEqual(upgraded.db.query("SELECT * FROM schema_version WHERE version<=68 ORDER BY version"), schemas)
                self.assertEqual(upgraded.db.query("SELECT * FROM audit_log WHERE seq<=? ORDER BY seq", (audit[-1]["seq"],)), audit)
                self.assertEqual(upgraded.db.query("SELECT * FROM journals ORDER BY id"), journals)
                self.assertTrue(upgraded.db.read_only)
                self.assertFalse(upgraded.db.has_write_authority())
                self.assertEqual(upgraded.db.scalar("PRAGMA query_only"), 1)
                base = APContract(upgraded, secret=self.secret)
                intake = APIntakeContract(upgraded, base, secret=self.secret)
                old = APActionRunner(upgraded, base, APPreflight(upgraded, base, secret=self.secret))
                new = APIntakeActionRunner(upgraded, intake, APIntakePreflight(upgraded, intake, secret=self.secret))
                self.assertTrue(all(row["ok"] for row in old.integrity_checks() + new.integrity_checks()))
                self.assertTrue(upgraded.audit.verify_chain()["ok"])
                self.assertEqual(upgraded.provider.submissions, [])
            finally:
                upgraded.db.close()

    def test_failed_later_entry_restores_schema68_receipts_and_storage_exactly(self):
        original = self.intake_workspace()
        before = tuple(original.db.conn.iterdump())
        failed_catalog = list(core_db.SCHEMA_CATALOG) + [
            (core_db.SCHEMA_CATALOG[-1][0] + 1, "exception_upgrade_failure_test_only", ["SELECT * FROM absent_exception_test_table"])]
        with tempfile.TemporaryDirectory(prefix="cipher-exception-upgrade-rollback-") as directory:
            target = Path(directory) / "copy.sqlite"
            self.copy_to(original, target)
            with patch.object(core_db, "SCHEMA_CATALOG", failed_catalog):
                with self.assertRaises(sqlite3.OperationalError):
                    core_db.Database(str(target))
            with sqlite3.connect(target) as inspected:
                self.assertEqual(tuple(inspected.iterdump()), before)
                self.assertEqual(inspected.execute("SELECT MAX(version) FROM schema_version").fetchone()[0], 68)

    def test_upgrade_preserves_original_receipts_schema_audit_and_accounting(self):
        original = self.original_workspace()
        receipts = original.db.query("SELECT * FROM ap_action_receipts ORDER BY id")
        schemas = original.db.query("SELECT * FROM schema_version ORDER BY version")
        audit = original.db.query("SELECT * FROM audit_log ORDER BY seq")
        journals = original.db.query("SELECT * FROM journals ORDER BY id")
        lines = original.db.query("SELECT * FROM journal_lines ORDER BY id")
        with tempfile.TemporaryDirectory(prefix="cipher-receipt-upgrade-") as directory:
            target = Path(directory) / "copy.sqlite"
            self.copy_to(original, target)
            upgraded = Cipher(str(target))
            self.addCleanup(upgraded.db.close)
            self.assertEqual(upgraded.db.query("SELECT * FROM ap_action_receipts ORDER BY id"), receipts)
            self.assertEqual(upgraded.db.query("SELECT * FROM schema_version WHERE version<=67 ORDER BY version"), schemas)
            self.assertEqual(upgraded.db.query("SELECT * FROM audit_log WHERE seq<=? ORDER BY seq", (audit[-1]["seq"],)), audit)
            self.assertEqual(upgraded.db.query("SELECT * FROM journals ORDER BY id"), journals)
            self.assertEqual(upgraded.db.query("SELECT * FROM journal_lines ORDER BY id"), lines)
            self.assertEqual(upgraded.db.schema_status()["current_version"], core_db.SCHEMA_CATALOG[-1][0])
            self.assertTrue(upgraded.db.read_only)
            self.assertFalse(upgraded.db.has_write_authority())
            self.assertEqual(upgraded.db.scalar("PRAGMA query_only"), 1)
            contract = APContract(upgraded, secret=self.secret)
            runner = APActionRunner(upgraded, contract, APPreflight(upgraded, contract, secret=self.secret))
            self.assertTrue(all(row["ok"] for row in runner.integrity_checks()))
            self.assertTrue(upgraded.audit.verify_chain()["ok"])
            self.assertEqual(upgraded.provider.submissions, [])
            with self.assertRaises(core_db.WriteAuthorityError):
                upgraded.db.execute("DELETE FROM ap_action_receipts")

    def test_later_failed_migration_rolls_back_expansion_and_all_original_guards(self):
        original = self.original_workspace()
        before = tuple(original.db.conn.iterdump())
        failed_catalog = list(core_db.SCHEMA_CATALOG) + [
            (core_db.SCHEMA_CATALOG[-1][0] + 1, "receipt_upgrade_failure_test_only", ["SELECT * FROM absent_upgrade_test_table"])]
        with tempfile.TemporaryDirectory(prefix="cipher-receipt-upgrade-rollback-") as directory:
            target = Path(directory) / "copy.sqlite"
            self.copy_to(original, target)
            with patch.object(core_db, "SCHEMA_CATALOG", failed_catalog):
                with self.assertRaises(sqlite3.OperationalError):
                    core_db.Database(str(target))
            with sqlite3.connect(target) as inspected:
                self.assertEqual(tuple(inspected.iterdump()), before)
                self.assertEqual(inspected.execute("SELECT MAX(version) FROM schema_version").fetchone()[0], 67)

    def test_unknown_fixed_action_is_refused_before_receipt_or_audit_write(self):
        c = make_ap_practice_fixture()
        self.addCleanup(c.db.close)
        before = tuple(c.db.conn.iterdump())
        person = c.ap_practice_persona_people["accountant"]
        with c.db.transaction():
            with self.assertRaises(APIReceiptIntegrityError):
                APIActionReceipts(c.db, c.audit).record(person_id=person["person_id"], actor_login=person["login"],
                                      repeatability_uuid=str(uuid4()), contract_version="cipher.ap-practice.v1",
                                      action="invoice.genericWrite", resource_id="unused", binding={},
                                      outcome="success", http_status=200, result={}, source={})
        self.assertEqual(tuple(c.db.conn.iterdump()), before)


if __name__ == "__main__":
    unittest.main()
