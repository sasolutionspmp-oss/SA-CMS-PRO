"""Empty-plugin compatibility and persistent modern identity boundary."""
import unittest

from apps.cipher.service import Cipher
from apps.cipher.domain.commercial import Plugin, register_commercial_schema
from apps.cipher.domain.people import IdentityRefused

register_commercial_schema()


class CommercialServiceBoundaryReview(unittest.TestCase):
    def legacy_source(self):
        c = Cipher()
        self.addCleanup(c.db.close)
        c.register_plugin("commercial", Plugin(c))
        project = c.create_project(name="Synthetic original empty-identity project", entity="Synthetic legacy entity", budget="1000")
        document = c.evidence.register_document(project_id=project["id"], kind="drawing", title="Synthetic legacy source", actor="estimator")
        revision = c.evidence.add_revision(document_id=document["id"], content="Synthetic legacy drawing", actor="estimator")
        estimate = c.estimates.create(project["id"], revision["id"], [{"description": "Synthetic original scope", "quantity": "2", "unit": "EA", "unit_price": "50"}], "estimator")
        return c, estimate

    def test_installed_empty_commercial_plugin_preserves_genuine_legacy_acceptance(self):
        c, estimate = self.legacy_source()
        self.assertIsNone(c.db.one("SELECT 1 FROM people_persons LIMIT 1"))
        approval = c.request_approval("estimate.approve", estimate["id"], actor_role="estimator", requested_by="estimator")
        c.approve(approval["id"], approver="owner", approver_role="owner")
        c.execute(approval["id"], actor="owner")
        self.assertEqual(c.estimates.estimate_proof(estimate["id"], accepted=True)["total"], "100.00")
        self.assertEqual(c.plugin("commercial").close_checks(None), [])

    def test_original_person_birth_keeps_modern_guard_after_current_identity_deletion(self):
        c, estimate = self.legacy_source()
        c.plugin("people").bootstrap_owner("synthetic.registered.owner", "Synthetic registered owner")
        triggers = c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('people_grants','people_persons')")
        for trigger in triggers:
            c.db.execute('DROP TRIGGER "'+trigger["name"]+'"')
        c.db.execute("DELETE FROM people_grants")
        c.db.execute("DELETE FROM people_persons")
        for trigger in triggers:
            c.db.execute(trigger["sql"])
        self.assertIsNone(c.db.one("SELECT 1 FROM people_persons LIMIT 1"))
        self.assertTrue(c._fixed_estimate_acceptance("estimate.approve", "estimator"))
        before = tuple(c.db.conn.iterdump())
        with self.assertRaises(IdentityRefused):
            c.request_approval("estimate.approve", estimate["id"], actor_role="estimator", requested_by="estimator")
        self.assertEqual(before, tuple(c.db.conn.iterdump()))


if __name__ == "__main__":
    unittest.main()
