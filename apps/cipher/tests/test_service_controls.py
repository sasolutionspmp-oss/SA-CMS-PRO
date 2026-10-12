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


class GovernorHookTests(unittest.TestCase):
    """Governor plugins bind policy facts into approvals they do not own and may refuse a
    request, a grant or an execution."""

    class Governor:
        GOVERNOR = True

        def __init__(self):
            self.level = "standard"
            self.refuse = set()
            self.calls = []

        def approval_policy(self, operation, manifest):
            return {"level": self.level} if operation == "commitment.execute" else None

        def check_request(self, operation, manifest, *, actor_role, requested_by):
            self.calls.append(("request", operation, requested_by))
            if "request" in self.refuse:
                raise CipherError("request refused by policy")

        def check_grant(self, approval, *, approver, approver_role):
            self.calls.append(("grant", approval["operation"], approver))
            if "grant" in self.refuse:
                raise CipherError("grant refused by policy")

        def check_execute(self, approval, manifest, *, actor):
            self.calls.append(("execute", approval["operation"], actor))
            if "execute" in self.refuse:
                raise CipherError("execution refused by policy")

    def setUp(self):
        self.c, self.prj, self.sup, self.cmt = scenario()
        self.g = self.Governor()
        self.c.register_plugin("zz_test_governor", self.g)

    def test_policy_facts_are_bound_and_a_change_invalidates_the_approval(self):
        c, g = self.c, self.g
        ap = c.request_approval("commitment.execute", self.cmt["id"], actor_role="pm", requested_by="pm-user")
        self.assertEqual(ap["manifest"]["governance"], {"zz_test_governor": {"level": "standard"}})
        c.approve(ap["id"], approver="owner")
        g.level = "high"  # the policy moved after the grant
        from apps.cipher.core.approvals import StaleApprovalError
        with self.assertRaises(StaleApprovalError):
            c.execute(ap["id"])
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")

    def test_a_governor_that_binds_nothing_leaves_the_manifest_unchanged(self):
        self.assertIn("governance", self.c._manifest("commitment.execute", self.cmt["id"], "pm"))
        self.g.approval_policy = lambda operation, manifest: None
        self.assertNotIn("governance", self.c._manifest("commitment.execute", self.cmt["id"], "pm"))
        self.c.register_plugin("zz_test_governor", object())  # a plugin without GOVERNOR = True is never consulted
        self.assertNotIn("governance", self.c._manifest("commitment.execute", self.cmt["id"], "pm"))

    def test_an_approval_bound_by_a_governor_that_is_gone_is_invalidated(self):
        c = self.c
        ap = c.request_approval("commitment.execute", self.cmt["id"], actor_role="pm")
        c.approve(ap["id"], approver="owner")
        c.register_plugin("zz_test_governor", object())  # the governor was removed
        from apps.cipher.core.approvals import StaleApprovalError
        with self.assertRaisesRegex(StaleApprovalError, "zz_test_governor changed"):
            c.execute(ap["id"])
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")

    def test_each_check_can_refuse_and_a_refused_execution_leaves_the_grant(self):
        c, g = self.c, self.g
        g.refuse = {"request"}
        with self.assertRaisesRegex(CipherError, "request refused"):
            c.request_approval("commitment.execute", self.cmt["id"], actor_role="pm")
        g.refuse = {"grant"}
        ap = c.request_approval("commitment.execute", self.cmt["id"], actor_role="pm")
        with self.assertRaisesRegex(CipherError, "grant refused"):
            c.approve(ap["id"], approver="owner")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "pending")
        g.refuse = {"execute"}
        c.approve(ap["id"], approver="owner")
        with self.assertRaisesRegex(CipherError, "execution refused"):
            c.execute(ap["id"], actor="pm-user")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "granted")
        self.assertEqual(c.commitments.get(self.cmt["id"])["status"], "draft")
        g.refuse = set()
        self.assertEqual(c.execute(ap["id"], actor="pm-user").result["status"], "executed")
        self.assertIn(("execute", "commitment.execute", "pm-user"), g.calls)


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


class ClaimChallengeTests(unittest.TestCase):
    def _restored_pair(self):
        import os
        import tempfile
        d = tempfile.mkdtemp()
        live = Cipher(os.path.join(d, "live.sqlite"))
        live.create_project(name="P", entity="E", budget="0")
        a = Cipher.open_restored(live.snapshot(os.path.join(d, "copy_a.sqlite")))
        b = Cipher.open_restored(live.snapshot(os.path.join(d, "copy_b.sqlite")))
        return a, b

    def test_claim_codes_are_bound_to_one_copy_and_retired(self):
        import os
        from unittest import mock
        from apps.cipher.core.db import WriteAuthorityError
        a, b = self._restored_pair()
        self.assertNotEqual(a.db.claim_challenge(), b.db.claim_challenge())
        with mock.patch.dict(os.environ, {"CIPHER_OWNER_SECRET": "owner-secret-for-tests-0123"}):
            code_a = a.db.expected_claim_code("owner-secret-for-tests-0123")
            self.assertNotEqual(code_a, b.db.expected_claim_code("owner-secret-for-tests-0123"))
            with self.assertRaises(WriteAuthorityError):  # copy A's code cannot open sibling copy B
                b.claim_write_authority(actor="owner", reason="restore drill", claim_code=code_a)
            self.assertFalse(b.db.has_write_authority())
            a.claim_write_authority(actor="owner", reason="restore drill", claim_code=code_a)
            self.assertTrue(a.db.has_write_authority())
            self.assertFalse(os.path.exists(a.db.path + ".claim-challenge"))  # retired

    def test_attested_claim_is_flagged_in_the_brief(self):
        a, _ = self._restored_pair()
        a.claim_write_authority(actor="owner", reason="restore drill without owner secret")
        pid = a.projects()[0]["id"]
        self.assertIn("claim_unsecured", [it["kind"] for it in a.ricky.brief(pid)["items"]])


class GovernedSurfaceTests(unittest.TestCase):
    def test_http_send_opens_an_approval_and_unsafe_actions_are_refused(self):
        import json
        import os
        import tempfile
        import urllib.error
        import urllib.request
        c = Cipher(os.path.join(tempfile.mkdtemp(), "ws.sqlite"))

        def post(base, name, body):
            req = urllib.request.Request(base + "/api/action/" + name, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        with BackgroundServer(c) as s:
            status, body = post(s.url, "run_demo", {})
            self.assertEqual(status, 200, body)
            status, body = post(s.url, "run_demo", {})
            self.assertEqual(status, 400)  # never re-seeded into a non-empty workspace
            prime = c.receivables.certify(project_id=c.projects()[0]["id"], period_id="2026-11", certified_cumulative="70000", actor="o")
            c.approve_and_execute("prime_bill.approve", prime["id"])
            status, body = post(s.url, "send_prime_bill", {"prime_bill_id": prime["id"]})
            self.assertEqual(status, 200, body)
            self.assertEqual(body["result"]["operation"], "prime_bill.send")
            self.assertEqual(body["result"]["status"], "pending")
            for bad in ("../escape", "C:/Windows/x", "a/b", ""):
                status, _ = post(s.url, "snapshot", {"name": bad})
                self.assertEqual(status, 400, bad)
            status, body = post(s.url, "snapshot", {"name": "drill-1"})
            self.assertEqual(status, 200, body)
            self.assertTrue(body["result"]["path"].endswith(os.path.join("snapshots", "drill-1.sqlite")))
            status, body = post(s.url, "ricky_tool", {"tool": "read_brief", "args": {"project_id": c.projects()[0]["id"]}, "actor_role": "owner"})
            self.assertEqual(status, 200, body)
            self.assertEqual(body["result"]["status"], "ok")
            status, body = post(s.url, "claim_challenge", {})
            self.assertEqual(status, 200)
            self.assertNotIn("code", body["result"])

    def test_ricky_previews_core_owned_operations(self):
        c = Cipher()
        r = run_golden_fixture(c)
        prime = c.receivables.certify(project_id=r["project_id"], period_id="2026-11", certified_cumulative="70000", actor="o")
        c.approve_and_execute("prime_bill.approve", prime["id"])
        p = c.ricky.propose("prime_bill.send", actor_role="owner", context={"prime_bill_id": prime["id"]})
        self.assertEqual(p["decision"], "proposed", p["reason"])
        self.assertEqual(c.ricky.propose("prime_bill.send", actor_role="estimator", context={"prime_bill_id": prime["id"]})["decision"], "abstained")

    def test_export_tables_redact_destinations_and_withhold_keys(self):
        c = Cipher()
        run_golden_fixture(c)
        tables = c.audit_export()["tables"]
        self.assertIn("parties", tables)
        for row in tables["parties"]["rows"]:
            if row.get("destination"):
                self.assertTrue(row["destination"].startswith("sha256:"))
        withheld = [n for n, t in tables.items() if t["rows"] == "withheld: holds key material"]
        self.assertTrue(withheld)
        self.assertEqual(tables["journals"]["row_count"], c.db.scalar("SELECT COUNT(*) FROM journals"))


if __name__ == "__main__":
    unittest.main()
