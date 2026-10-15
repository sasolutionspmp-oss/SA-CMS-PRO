"""Every served tool must keep human approval and posting methods out of reach."""
from contextlib import ExitStack
import unittest
from unittest.mock import patch

from apps.cipher.ricky_served import SERVED_TOOLS, ServedRicky
from apps.cipher.tests import test_ricky_sdk as fixtures


class ServedHandlerBoundaryTests(unittest.TestCase):
    def test_every_allowed_handler_succeeds_without_approval_or_posting(self):
        w = fixtures.world()
        self.addCleanup(w.c.db.close)
        # People create the posted records and evidence before Ricky's boundary is tested.
        fx3 = fixtures.round3_fixture(w)
        fx4 = fixtures.round4_fixture(w)
        doc = w.c.evidence.register_document(project_id=w.project["id"], kind="review", title="Synthetic review document", actor="owner")
        w.c.evidence.add_revision(document_id=doc["id"], content=b"synthetic review", note="synthetic", actor="owner")
        approval = w.c.approvals.list()[0]
        served = ServedRicky(w.sdk)

        def served_call(world, tool, args, role="owner", actor="ricky-test", **kwargs):
            self.assertIs(world, w)
            return served.invoke(tool, args, actor=actor, actor_role=role, **kwargs)

        targets = (
            ("Commands.run", w.c.commands, "run"),
            ("Cipher._apply", w.c, "_apply"),
            ("Ledger.post", w.c.ledger, "post"),
            ("Cipher.execute", w.c, "execute"),
            ("Cipher.post_bill", w.c, "post_bill"),
            ("Cipher.request_approval", w.c, "request_approval"),
            ("Cipher.approve", w.c, "approve"),
            ("Approvals.request", w.c.approvals, "request"),
            ("Approvals.grant", w.c.approvals, "grant"),
        )
        with ExitStack() as stack:
            trapped = [stack.enter_context(patch.object(obj, method, side_effect=AssertionError(f"served tool reached {name}")))
                       for name, obj, method in targets]
            stack.enter_context(patch.object(fixtures, "call", side_effect=served_call))
            results = {
                "read_brief": served_call(w, "read_brief", {"project_id": w.project["id"]}),
                "read_project_state": served_call(w, "read_project_state", {
                    "project_id": w.project["id"], "keys": ["approvals", "bills", "forecast", "ap", "ar", "trial_balance", "audit_chain"],
                }),
                "read_document": served_call(w, "read_document", {"document_id": doc["id"]}),
                "draft_change": served_call(w, "draft_change", fixtures.draft_change_args(w), role="pm"),
                "draft_supplier_bill": fixtures.draft_bill(w),
                "get_status": served_call(w, "get_status", {"kind": "approval", "id": approval["id"]}),
            }
            self.assertEqual(results["draft_change"]["status"], "ok", results["draft_change"])
            results["preview"] = served_call(w, "preview", {
                "workflow": "change.execute", "context": {"change_id": results["draft_change"]["result"]["change_id"]},
            }, role="pm")
            results.update(fixtures.round3_calls(w, fx3))
            results.update(fixtures.round4_calls(w, fx4))

            # Any allowlist expansion needs a successful fixture call here before it ships.
            self.assertEqual(set(results), SERVED_TOOLS)
            for name, receipt in results.items():
                with self.subTest(tool=name):
                    self.assertEqual(receipt["status"], "ok", receipt)
            for (name, _, _), method in zip(targets, trapped):
                with self.subTest(boundary=name):
                    method.assert_not_called()

        self.assertTrue(w.sdk.verify_receipts()["ok"])
        self.assertTrue(w.c.audit.verify_chain()["ok"])


if __name__ == "__main__":
    unittest.main()
