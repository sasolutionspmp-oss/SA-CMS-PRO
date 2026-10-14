"""Receipt expansion preserves original financial proof and quarantine."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.ap_actions import APActionRunner
from apps.cipher.ap_contract import APContract
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
            self.assertEqual(upgraded.db.schema_status()["current_version"], 68)
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
            (69, "receipt_upgrade_failure_test_only", ["SELECT * FROM absent_upgrade_test_table"])]
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
