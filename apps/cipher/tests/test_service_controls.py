"""Service-level controls: role enforcement, core-operation routing, guarded closes, export completeness."""
import unittest

from apps.cipher.core.approvals import build_manifest
from apps.cipher.server import BackgroundServer
from apps.cipher.service import Cipher, CipherError, RoleNotAuthorised, run_golden_fixture


def scenario():
    c = Cipher()
    sup = c.add_party(kind="supplier", name="Sub", destination="ACH-1")
    c.verify_destination(sup["id"], destination="ACH-1", verified_by="owner")
    prj = c.create_project(name="P", entity="E", budget="1000")
    c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
    cmt = c.commitments.create(project_id=prj["id"], supplier_id=sup["id"], title="S", sov_lines=[{"description": "a", "amount": "1000"}], actor="o")
    return c, prj, sup, cmt


class RoleEnforcementTests(unittest.TestCase):
    def test_request_requires_the_executing_role_to_hold_authority(self):
        c, prj, sup, cmt = scenario()
        with self.assertRaises(RoleNotAuthorised):
            c.request_approval("commitment.execute", cmt["id"], actor_role="estimator")
        with self.assertRaises(RoleNotAuthorised):
            c.request_approval("commitment.execute", cmt["id"], actor_role="viewer")
        with self.assertRaises(RoleNotAuthorised):
            c.request_approval("commitment.execute", cmt["id"], actor_role="intern")
        ap = c.request_approval("commitment.execute", cmt["id"], actor_role="pm")
        self.assertEqual(ap["manifest"]["actor_role"], "pm")

    def test_approver_role_must_hold_authority(self):
        c, prj, sup, cmt = scenario()
        ap = c.request_approval("commitment.execute", cmt["id"], actor_role="pm")
        with self.assertRaises(RoleNotAuthorised):
            c.approve(ap["id"], approver="someone", approver_role="treasury")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "pending")
        c.approve(ap["id"], approver="pm-user", approver_role="pm")
        self.assertEqual(c.execute(ap["id"]).result["status"], "executed")

    def test_manifest_binds_entity_and_currency(self):
        a = build_manifest(operation="x", subject_type="t", subject_id="1", actor_role="owner", entity="E1")
        b = build_manifest(operation="x", subject_type="t", subject_id="1", actor_role="owner", entity="E2")
        from apps.cipher.core.approvals import material_hash
        self.assertNotEqual(material_hash(a), material_hash(b))
        self.assertEqual(a["currency"], "USD")


class CoreRoutingTests(unittest.TestCase):
    def test_core_domain_can_own_an_operation(self):
        c, prj, sup, cmt = scenario()
        calls = []

        class Owner:
            def handles(self, operation):
                return operation == "synthetic.ping"

            def manifest_for(self, operation, subject_id, *, actor_role):
                return build_manifest(operation=operation, subject_type="t", subject_id=subject_id, actor_role=actor_role)

            def apply(self, operation, subject_id, *, approval_id, manifest, actor, period_id):
                calls.append((operation, subject_id, approval_id))
                return {"ok": True}

        c.evidence.handles = Owner().handles
        c.evidence.manifest_for = Owner().manifest_for
        c.evidence.apply = Owner().apply
        res = c.approve_and_execute("synthetic.ping", "s1")
        self.assertEqual(res.result, {"ok": True})
        self.assertEqual(calls[0][:2], ("synthetic.ping", "s1"))


class GuardedCloseTests(unittest.TestCase):
    def test_commitment_close_requires_accepted_closeout_when_field_module_present(self):
        c, prj, sup, cmt = scenario()
        c.approve_and_execute("commitment.execute", cmt["id"])
        if "field" not in c._plugins:
            self.skipTest("field module not registered")
        with self.assertRaises(CipherError):
            c.close_commitment(cmt["id"])
        self.assertEqual(c.commitments.get(cmt["id"])["status"], "executed")

    def test_http_period_close_opens_a_checklist_approval(self):
        c, prj, sup, cmt = scenario()
        if "close" not in c._plugins:
            self.skipTest("close module not registered")
        import json
        import urllib.request
        with BackgroundServer(c) as s:
            req = urllib.request.Request(s.url + "/api/action/close_period", data=json.dumps({"period_id": "P1"}).encode(), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                body = json.loads(r.read())
        self.assertTrue(body["ok"])
        self.assertEqual(body["result"]["operation"], "close.close_period")
        self.assertEqual(c.ledger.period("P1")["status"], "open")  # nothing closed without the approval


class ExportAndHookTests(unittest.TestCase):
    def test_audit_export_is_complete(self):
        c = Cipher()
        run_golden_fixture(c)
        exp = c.audit_export()
        for key in ("journals", "approvals", "source_records", "payment_execution", "reconciliations", "modules", "schema", "audit", "ap_reconciliation", "ar_reconciliation"):
            self.assertIn(key, exp)
        self.assertTrue(exp["payment_execution"]["intents"])
        self.assertTrue(exp["payment_execution"]["provider_events"])
        self.assertTrue(exp["source_records"]["document_revisions"])
        self.assertTrue(exp["audit"]["chain"]["ok"])
        journal_ids = {j["id"] for j in exp["journals"]}
        self.assertEqual(journal_ids, {r["id"] for r in c.db.query("SELECT id FROM journals")})

    def test_core_reconciliation_checks_registered(self):
        c = Cipher()
        self.assertIn("core_reconciliation", c._plugins)
        self.assertIsInstance(c.plugin("core_reconciliation").close_checks("P-any"), list)

    def test_ar_sources_hook_lists_plugins_with_ar_items(self):
        c = Cipher()
        sources = c.receivables.extra_ar_sources()
        self.assertTrue(all(hasattr(s, "ar_open_items") for s in sources))


if __name__ == "__main__":
    unittest.main()
