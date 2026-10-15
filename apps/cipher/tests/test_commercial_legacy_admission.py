"""An installed empty governor preserves genuine pre-commercial workspaces."""
import unittest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from apps.cipher.core import db as core_db
from apps.cipher.domain.commercial import CommercialError
from apps.cipher.service import Cipher
from apps.cipher.tests.test_workspace_mode import legacy_file


class CommercialHistoricalAdmissionTests(unittest.TestCase):
    def test_genuine71_empty_plugin_keeps_native_legacy_acceptance_and_pure_inventory(self):
        historical = [entry for entry in core_db.SCHEMA_CATALOG if entry[0] <= 71]
        with patch.object(core_db, "SCHEMA_CATALOG", historical):
            c = Cipher()
        self.addCleanup(c.db.close)
        commercial = c.plugin("commercial")
        project = c.create_project(name="Synthetic legacy estimate", entity="Synthetic entity", budget="100.00")
        document = c.evidence.register_document(project_id=project["id"], kind="drawing", title="Legacy drawing", actor="legacy.estimator")
        revision = c.evidence.add_revision(document_id=document["id"], content="Synthetic legacy manual source", actor="legacy.estimator")
        estimate = c.estimates.create(project_id=project["id"], document_revision_id=revision["id"],
                                     lines=[{"description": "Legacy source", "quantity": "1", "unit": "LS", "unit_price": "10.00"}], actor="legacy.estimator")
        before = tuple(c.db.conn.iterdump()), c.db.conn.total_changes
        self.assertEqual(commercial.source_inventory(project_ids=(project["id"],)), [])
        self.assertEqual(commercial.close_checks("2026-10"), [])
        self.assertEqual((tuple(c.db.conn.iterdump()), c.db.conn.total_changes), before)
        requested = c.request_approval("estimate.approve", estimate["id"], actor_role="estimator", requested_by="legacy.estimator")
        c.approve(requested["id"], approver="owner", approver_role="owner")
        c.execute(requested["id"], actor="legacy.estimator")
        self.assertEqual(c.estimates.get(estimate["id"])["status"], "approved")
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM journals"), 0)

    def test_missing_source_schema_admission_cannot_select_empty_legacy_inventory(self):
        c = Cipher()
        self.addCleanup(c.db.close)
        c.db.conn.execute("DELETE FROM schema_version WHERE name='commercial_manual_sources_and_handoffs'")
        before = tuple(c.db.conn.iterdump()), c.db.conn.total_changes
        with self.assertRaises(CommercialError):
            c.plugin("commercial").source_inventory(project_ids=())
        self.assertEqual((tuple(c.db.conn.iterdump()), c.db.conn.total_changes), before)


class CommercialAdmissionSequenceTests(unittest.TestCase):
    def test_real_pre_mode_copy_claim_keeps_named_source_admission_after_shifted_sequence(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "old65.sqlite", Path(folder) / "copy65.sqlite"
            legacy_file(source)
            with sqlite3.connect(source) as original, sqlite3.connect(target) as copied:
                original.backup(copied)
                before = original.execute("SELECT * FROM schema_version ORDER BY version").fetchall()
            c = Cipher(str(target))
            try:
                self.assertEqual(c.db.mode_status()["state"], "pending_practice_declaration")
                self.assertTrue(c.db.read_only)
                self.assertEqual([tuple(row.values()) for row in c.db.query("SELECT * FROM schema_version WHERE version<=65 ORDER BY version")], before)
                self.assertEqual(c.db.one("SELECT version FROM schema_version WHERE name='commercial_manual_sources_and_handoffs'")["version"], 71)
                self.assertEqual(c.plugin("commercial").source_inventory(project_ids=()), [])
                c.db.claim_write_authority(approver="synthetic.owner", reason="Attested synthetic pre-mode restoration", approval_ref="SYNTHETIC-RESTORE")
                self.assertEqual(c.db.mode_status()["origin"], "legacy_adopted")
                self.assertEqual(c.db.one("SELECT version FROM schema_version WHERE name='workspace_mode'")["version"], len(core_db.SCHEMA_CATALOG))
                self.assertEqual(c.plugin("commercial").source_inventory(project_ids=()), [])
                self.assertEqual(c.plugin("commercial").close_checks("2026-10"), [])
                self.assertTrue(c.audit.verify_chain()["ok"])
                self.assertEqual(c.provider.submissions, [])
            finally:
                c.db.close()

    def test_named_source_admission_requires_its_original_statement_count(self):
        c = Cipher()
        self.addCleanup(c.db.close)
        c.db.execute("UPDATE schema_version SET statement_count=1 WHERE name='commercial_manual_sources_and_handoffs'")
        before = tuple(c.db.conn.iterdump()), c.db.conn.total_changes
        with self.assertRaises(CommercialError):
            c.plugin("commercial").source_inventory(project_ids=())
        self.assertEqual((tuple(c.db.conn.iterdump()), c.db.conn.total_changes), before)

    def test_impossible_application_sequence_cannot_qualify_named_admission(self):
        c = Cipher()
        self.addCleanup(c.db.close)
        c.db.execute("UPDATE schema_version SET version=999 WHERE name='commercial_manual_sources_and_handoffs'")
        before = tuple(c.db.conn.iterdump()), c.db.conn.total_changes
        with self.assertRaises(CommercialError):
            c.plugin("commercial").source_inventory(project_ids=())
        self.assertEqual((tuple(c.db.conn.iterdump()), c.db.conn.total_changes), before)

if __name__ == "__main__":
    unittest.main()
