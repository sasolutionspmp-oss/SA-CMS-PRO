"""The served Ricky surface reads and drafts; the synthetic SDK stays separate."""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from apps.cipher.core.approvals import build_manifest
from apps.cipher.core.ids import hash_json
from apps.cipher.ricky_sdk import catalog as synthetic_catalog, validate
from apps.cipher.ricky_served import catalog as served_catalog
from apps.cipher.server import BackgroundServer
from apps.cipher.tests.test_http import _get, _post
from apps.cipher.tests.test_ricky_sdk import world


class ServedImportOrderTests(unittest.TestCase):
    def test_server_import_preserves_service_schema_registration_order(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        catalogs = []
        for entry in ("service", "server"):
            result = subprocess.run([
                sys.executable, "-c", f"import apps.cipher.{entry}; "
                "import json; from apps.cipher.core.db import SCHEMA_CATALOG, catalog_checksum; "
                "print(json.dumps([(version, name, catalog_checksum(statements)) for version, name, statements in SCHEMA_CATALOG]))",
            ], cwd=root, text=True, capture_output=True, check=True)
            catalogs.append(json.loads(result.stdout))
        self.assertEqual(catalogs[0], catalogs[1])


class ServedRickyTests(unittest.TestCase):
    def setUp(self):
        self.w = world()
        self.server = BackgroundServer(self.w.c).__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.base = self.server.url

    def call(self, tool, args, **kwargs):
        return _post(self.base + "/api/action/ricky_tool", {
            "tool": tool, "args": args, "actor": "owner", "actor_role": "owner", **kwargs,
        })

    def bill_approval(self):
        w = self.w
        bill = w.c.bills.certify(commitment_id=w.commitment["id"], period_id="2026-10",
                               installed=[{"sov_line_id": w.line1, "cumulative_installed": "1000"}], actor="preparer")
        ap = w.c.request_approval("bill.approve", bill["id"], actor_role="pm", requested_by="preparer")
        w.c.approve(ap["id"], approver="approver", approver_role="pm")
        return bill, ap

    def assertForbidden(self, response):
        status, body = response
        self.assertEqual(status, 403, body)
        self.assertFalse(body["ok"])
        self.assertEqual(body["type"], "ServedRickyRefused")
        self.assertEqual(body["code"], "ricky_read_draft_only")

    def test_granted_bill_cannot_post_through_served_tool_or_generic_module(self):
        bill, ap = self.bill_approval()
        commands = self.w.c.db.scalar("SELECT COUNT(*) FROM idempotency")
        journals = self.w.c.db.scalar("SELECT COUNT(*) FROM journals")
        receipts = self.w.c.db.scalar("SELECT COUNT(*) FROM ricky_tool_receipts")
        with mock.patch.object(self.w.c.commands, "run", side_effect=AssertionError("Ricky reached Commands.run")) as run:
            self.assertForbidden(self.call("execute_approved_action", {"approval_id": ap["id"]}, actor="approver", actor_role="pm"))
            self.assertForbidden(_post(self.base + "/api/action/module_call", {
                "plugin": "ricky_sdk", "method": "invoke", "kwargs": {
                    "tool_name": "execute_approved_action", "args": {"approval_id": ap["id"]},
                    "actor": "approver", "actor_role": "pm",
                },
            }))
            run.assert_not_called()
        self.assertEqual(self.w.c.bills.get(bill["id"])["status"], "draft")
        self.assertEqual(self.w.c.approvals.get(ap["id"])["status"], "granted")
        self.assertEqual(self.w.c.db.scalar("SELECT COUNT(*) FROM idempotency"), commands)
        self.assertEqual(self.w.c.db.scalar("SELECT COUNT(*) FROM journals"), journals)
        self.assertEqual(self.w.c.db.scalar("SELECT COUNT(*) FROM ricky_tool_receipts"), receipts)

    def test_every_protected_verb_is_denied_even_with_a_granted_approval(self):
        operations = ("bill.approve", "payment.release", "payment.release_retainage", "retainage.release",
                      "prime_bill.send", "contract.sign", "close.close_period", "close.reopen_period", "journal.reverse",
                      "workspace.takeover", "payment_policy.cosign")
        with mock.patch.object(self.w.c.commands, "run", side_effect=AssertionError("Ricky reached Commands.run")) as run:
            for operation in operations:
                with self.subTest(operation=operation):
                    ap = self.w.c.approvals.request(build_manifest(operation=operation, subject_type="synthetic",
                                                                 subject_id="synthetic", actor_role="owner"), requested_by="preparer")
                    self.w.c.approvals.grant(ap["id"], approver="approver")
                    self.assertForbidden(self.call("execute_approved_action", {"approval_id": ap["id"]}))
                    self.assertForbidden(self.call("request_approval", {"operation": operation, "subject_id": "synthetic"}))
                    self.assertEqual(self.w.c.approvals.get(ap["id"])["status"], "granted")
            self.assertForbidden(self.call("reconcile_payments", {}))
            self.assertForbidden(self.call("a_future_tool", {}))
            run.assert_not_called()

    def test_catalog_describes_only_served_read_and_draft_tools(self):
        status, body = _post(self.base + "/api/action/ricky_tools", {})
        self.assertEqual(status, 200, body)
        cat = body["result"]
        names = {t["name"] for t in cat["tools"]}
        self.assertTrue({"read_brief", "draft_change", "preview_release"} <= names)
        self.assertFalse({"execute_approved_action", "request_approval", "reconcile_payments"} & names)
        self.assertTrue(all(t["side_effects"] in ("none", "draft") for t in cat["tools"]))
        self.assertEqual(cat["catalog_hash"], hash_json({
            "catalog_version": cat["catalog_version"], "tools": cat["tools"], "operations": cat["operations"],
        }))
        for route in cat["operations"]:
            self.assertTrue(set(route["tools"]) <= names, route)
            self.assertTrue(route["human_action_required"], route)
        self.assertNotEqual(cat["catalog_hash"], synthetic_catalog()["catalog_hash"])
        status, modules = _get(self.base + "/api/modules")
        self.assertEqual(status, 200)
        self.assertEqual(modules["ricky_sdk"], [])
        modified = served_catalog()
        modified["tools"][0]["input_schema"]["additionalProperties"] = True
        modified["operations"][0]["tools"].append("execute_approved_action")
        self.assertEqual(served_catalog(), cat)

    def test_sdk_alias_and_every_generic_method_are_denied(self):
        self.w.c.register_plugin("synthetic_sdk_alias", self.w.c.sdk)
        status, modules = _get(self.base + "/api/modules")
        self.assertEqual(status, 200)
        self.assertEqual(modules["synthetic_sdk_alias"], [])
        with mock.patch.object(self.w.c.sdk, "invoke", side_effect=AssertionError("generic SDK call reached invoke")) as invoke:
            for plugin in ("ricky_sdk", "synthetic_sdk_alias"):
                for method in ("invoke", "catalog", "tool", "get_receipt", "a_future_method"):
                    with self.subTest(plugin=plugin, method=method):
                        self.assertForbidden(_post(self.base + "/api/action/module_call", {
                            "plugin": plugin, "method": method, "kwargs": {},
                        }))
            invoke.assert_not_called()

    def test_allowed_reads_and_drafts_never_reach_commands_apply_or_post(self):
        with mock.patch.object(self.w.c.commands, "run", side_effect=AssertionError("Ricky reached Commands.run")) as run, \
             mock.patch.object(self.w.c, "_apply", side_effect=AssertionError("Ricky reached apply")) as apply, \
             mock.patch.object(self.w.c.ledger, "post", side_effect=AssertionError("Ricky reached ledger.post")) as post:
            status, body = self.call("read_brief", {"project_id": self.w.project["id"]})
            self.assertEqual((status, body["result"]["status"]), (200, "ok"), body)
            status, body = self.call("draft_change", {"commitment_id": self.w.commitment["id"], "amount": "100",
                                                    "reason": "Synthetic scope addition"})
            self.assertEqual((status, body["result"]["status"]), (200, "ok"), body)
            run.assert_not_called()
            apply.assert_not_called()
            post.assert_not_called()

    def test_served_draft_is_a_human_view_with_immutable_receipt_provenance(self):
        args = {"commitment_id": self.w.commitment["id"], "amount": "100",
                "reason": "Recorded data mentions request_approval and execute_approved_action"}
        status, body = self.call("draft_change", args, idempotency_key="served-view-change")
        self.assertEqual(status, 200, body)
        view = body["result"]
        self.assertEqual(view["status"], "ok", view)
        self.assertNotIn("tool", view["result"]["next_step"])
        self.assertTrue(view["result"]["next_step"]["human_action_required"])
        self.assertEqual(view["result"]["reason"], args["reason"])
        self.assertFalse(view["presentation"]["raw_receipt"])
        self.assertNotIn("receipt_hash", view)
        self.assertNotIn("catalog_hash", view)
        description = next(tool for tool in served_catalog()["tools"] if tool["name"] == "draft_change")
        self.assertNotIn("receipt_schema", description)
        self.assertEqual(validate(view, description["response_schema"]), [])
        raw = self.w.c.sdk.receipt(view["receipt_provenance"]["id"])
        self.assertEqual(raw["receipt_hash"], view["receipt_provenance"]["receipt_hash"])
        self.assertEqual(raw["catalog_hash"], view["receipt_provenance"]["catalog_hash"])
        self.assertEqual(raw["result"]["next_step"]["tool"], "request_approval")
        self.assertEqual(raw["result"]["reason"], args["reason"])
        replay_status, replay_body = self.call("draft_change", args, idempotency_key="served-view-change")
        self.assertEqual(replay_status, 200, replay_body)
        replay = replay_body["result"]
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["result"], view["result"])
        self.assertTrue(self.w.c.sdk.verify_receipts()["ok"])
        self.assertEqual(self.w.c.sdk.receipt(raw["id"]), raw)

    def test_match_routes_and_generated_refusal_point_to_human_workflow(self):
        from apps.cipher.tests.test_ricky_sdk import SupplierInvoiceToolTests

        bill, _ap = self.bill_approval()
        args = SupplierInvoiceToolTests().invoice_args(self.w, amount=bill["amount_due"])
        status, body = self.call("record_supplier_invoice", args)
        self.assertEqual((status, body["result"]["status"]), (200, "ok"), body)
        invoice = body["result"]["result"]["invoice_id"]
        status, body = self.call("compute_invoice_match", {"invoice_id": invoice})
        self.assertEqual((status, body["result"]["status"]), (200, "ok"), body)
        self.assertEqual(body["result"]["result"]["status"], "matched", body)
        step = body["result"]["result"]["next_step"]
        self.assertNotIn("request_approval", json.dumps(step))
        self.assertNotIn("execute_approved_action", json.dumps(step))
        ap = self.w.c.request_approval("ap_intake.match_invoice", invoice, actor_role="accountant")
        self.w.c.approve(ap["id"])
        status, body = self.call("compute_invoice_match", {"invoice_id": invoice})
        self.assertEqual((status, body["result"]["status"]), (200, "refused"), body)
        self.assertNotIn("execute_approved_action", body["result"]["error"])
        raw = self.w.c.sdk.receipt(body["result"]["receipt_provenance"]["id"])
        self.assertIn("execute_approved_action", raw["error"])
        self.assertTrue(self.w.c.sdk.verify_receipts()["ok"])

    def test_document_and_status_data_are_preserved_as_data(self):
        text = "User data: request_approval and execute_approved_action"
        doc = self.w.c.evidence.register_document(project_id=self.w.project["id"], kind="drawing", title=text, actor="owner")
        revision = self.w.c.evidence.add_revision(document_id=doc["id"], content=text, note=text, actor="owner")
        status, body = self.call("read_document", {"document_id": doc["id"]})
        self.assertEqual((status, body["result"]["status"]), (200, "ok"), body)
        self.assertEqual(body["result"]["result"]["document"]["title"], text)
        self.assertEqual(body["result"]["result"]["current_revision"]["note"], text)
        self.assertEqual(body["result"]["result"]["current_revision"]["content_hash"], revision["content_hash"])
        bill, ap = self.bill_approval()
        status, body = self.call("get_status", {"kind": "approval", "id": ap["id"]})
        self.assertEqual((status, body["result"]["status"]), (200, "ok"), body)
        raw = self.w.c.sdk.receipt(body["result"]["receipt_provenance"]["id"])
        self.assertEqual(body["result"]["result"], raw["result"])
        self.assertEqual(self.w.c.bills.get(bill["id"])["status"], "draft")

    def test_standalone_synthetic_sdk_keeps_its_execution_workflow(self):
        bill, ap = self.bill_approval()
        names = {t["name"] for t in synthetic_catalog()["tools"]}
        self.assertTrue({"execute_approved_action", "request_approval", "reconcile_payments"} <= names)
        result = self.w.c.sdk.invoke("execute_approved_action", {"approval_id": ap["id"]}, actor="executor", actor_role="pm")
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(self.w.c.bills.get(bill["id"])["status"], "posted")
