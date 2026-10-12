"""HTTP boundary tests: the console API cannot bypass approvals and reports errors cleanly."""
import json
import unittest
import urllib.error
import urllib.request

from apps.cipher.server import BackgroundServer
from apps.cipher.service import Cipher


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, json.loads(r.read())


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cipher = Cipher()
        cls.server = BackgroundServer(cls.cipher).__enter__()
        cls.base = cls.server.url

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_console_and_health(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as r:
            html = r.read().decode()
        self.assertIn("Cipher", html)
        self.assertIn("Owner Console", html)
        status, body = _get(self.base + "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body["authority"]["effective_write_authority"])

    def test_empty_state_then_demo_then_full_state(self):
        with BackgroundServer(Cipher()) as fresh:  # isolated workspace so test order does not matter
            status, body = _get(fresh.url + "/api/state")
            self.assertEqual(status, 200)
            self.assertIsNone(body["project"])
            status, body = _post(fresh.url + "/api/action/run_demo", {})
            self.assertEqual(status, 200, body)
            self.assertEqual(body["result"]["bill1"]["amount_due"], "27000.00")
            status, body = _get(fresh.url + "/api/state")
            self.assertEqual(body["forecast"]["executed_commitments"], "122000.00")
            self.assertTrue(body["trial_balance"]["balanced"])
            self.assertTrue(body["audit_chain"]["ok"])
            status, export = _get(fresh.url + "/api/audit-export")
            self.assertTrue(export["audit"]["chain"]["ok"])
            self.assertIn("objects", export["schema"])

    def test_bad_requests_are_400_and_unknown_actions_404(self):
        status, body = _post(self.base + "/api/action/request_approval", {"operation": "bill.approve", "subject_id": "nope"})
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertIn("unknown bill", body["error"])
        status, body = _post(self.base + "/api/action/not_a_thing", {})
        self.assertEqual(status, 404)
        status, body = _post(self.base + "/api/action/approve", [1, 2])
        self.assertEqual(status, 400)

    def test_approval_flow_over_http(self):
        _post(self.base + "/api/action/run_demo", {}) if not self.cipher.projects() else None
        state = _get(self.base + "/api/state")[1]
        project_id = state["project"]["id"]
        supplier = next(p for p in state["parties"] if p["kind"] == "supplier")
        status, body = _post(self.base + "/api/action/create_commitment", {"project_id": project_id, "supplier_id": supplier["id"], "title": "HTTP sub", "sov_lines": [{"description": "a", "amount": "500"}]})
        self.assertEqual(status, 200, body)
        cid = body["result"]["id"]
        status, body = _post(self.base + "/api/action/request_approval", {"operation": "commitment.execute", "subject_id": cid})
        self.assertEqual(status, 200, body)
        ap = body["result"]["id"]
        status, body = _post(self.base + "/api/action/execute", {"approval_id": ap})
        self.assertEqual(status, 400)  # not granted yet
        _post(self.base + "/api/action/approve", {"approval_id": ap})
        status, body = _post(self.base + "/api/action/execute", {"approval_id": ap})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["result"]["result"]["status"], "executed")
        status, body = _post(self.base + "/api/action/execute", {"approval_id": ap})
        self.assertTrue(body["result"]["replayed"])

    def test_provider_mode_validation(self):
        status, body = _post(self.base + "/api/action/set_provider_mode", {"mode": "steal"})
        self.assertEqual(status, 400)

    def test_module_listing_and_generic_call(self):
        status, mods = _get(self.base + "/api/modules")
        self.assertEqual(status, 200)
        if not mods:
            self.skipTest("no v2 modules registered")
        name = sorted(mods)[0]
        self.assertTrue(all(not m.startswith("_") for m in mods[name]))
        self.assertNotIn("apply", mods[name])
        status, body = _post(self.base + "/api/action/module_call", {"plugin": name, "method": "apply", "kwargs": {}})
        self.assertEqual(status, 400)  # approval-bound entry points are not callable directly
        status, body = _post(self.base + "/api/action/module_call", {"plugin": "nope", "method": "x"})
        self.assertEqual(status, 400)
        status, body = _post(self.base + "/api/action/module_call", {"plugin": name, "method": mods[name][0], "kwargs": "not-an-object"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
