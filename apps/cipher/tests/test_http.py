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


def _raw(url, method="GET", body=None, headers=None):
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class BoundaryTests(unittest.TestCase):
    """CSRF, DNS-rebinding and token rules on the HTTP boundary."""

    TOKEN = "t0ken-for-tests-0123456789"

    def test_cross_site_simple_posts_are_refused(self):
        with BackgroundServer(Cipher()) as s:
            # a cross-site HTML form or no-cors fetch can only send text/plain / form encodings
            status, _, _ = _raw(s.url + "/api/action/add_party", "POST", b'{"kind":"supplier","name":"x"}', {"Content-Type": "text/plain"})
            self.assertEqual(status, 415)
            status, _, _ = _raw(s.url + "/api/action/add_party", "POST", b"kind=supplier&name=x", {"Content-Type": "application/x-www-form-urlencoded"})
            self.assertEqual(status, 415)
            # a JSON post carrying a foreign Origin is refused
            status, _, _ = _raw(s.url + "/api/action/add_party", "POST", b'{"kind":"supplier","name":"x"}', {"Content-Type": "application/json", "Origin": "https://evil.example"})
            self.assertEqual(status, 403)
            # same-origin JSON is accepted
            host = s.url.split("//", 1)[1]
            status, _, body = _raw(s.url + "/api/action/add_party", "POST", b'{"kind":"supplier","name":"ok"}', {"Content-Type": "application/json", "Origin": "http://" + host})
            self.assertEqual(status, 200, body)

    def test_oversized_body_is_refused(self):
        from apps.cipher.server import MAX_BODY_BYTES
        with BackgroundServer(Cipher()) as s:
            status, _, _ = _raw(s.url + "/api/action/add_party", "POST", b"{" + b" " * (MAX_BODY_BYTES + 10) + b"}", {"Content-Type": "application/json"})
            self.assertEqual(status, 413)

    def test_rejections_are_stable_under_repetition(self):
        # rejected posts must not reset the connection (body is drained before the response)
        with BackgroundServer(Cipher()) as s:
            for _ in range(25):
                status, _, _ = _raw(s.url + "/api/action/add_party", "POST", b'{"kind":"supplier","name":"x"}' * 200, {"Content-Type": "application/json", "Origin": "https://evil.example"})
                self.assertEqual(status, 403)

    def test_loopback_mode_rejects_foreign_host_header(self):
        with BackgroundServer(Cipher()) as s:
            status, _, _ = _raw(s.url + "/api/state", headers={"Host": "attacker.example:8765"})
            self.assertEqual(status, 403)
            status, _, _ = _raw(s.url + "/api/state", headers={"Host": "localhost:8765"})
            self.assertEqual(status, 200)

    def test_non_loopback_bind_requires_token(self):
        from apps.cipher.server import InsecureBindError, make_server
        with self.assertRaises(InsecureBindError):
            make_server(Cipher(), "0.0.0.0", 0)
        with self.assertRaises(InsecureBindError):
            make_server(Cipher(), "127.0.0.1", 0, token="short")

    def test_token_mode(self):
        with BackgroundServer(Cipher(), token=self.TOKEN) as s:
            status, _, body = _raw(s.url + "/api/state")
            self.assertEqual(status, 401)
            status, _, body = _raw(s.url + "/")
            self.assertEqual(status, 401)
            self.assertIn(b"Access token", body)
            status, _, body = _raw(s.url + "/api/health")
            self.assertEqual((status, json.loads(body)), (200, {"ok": True}))  # health leaks nothing without auth
            status, _, _ = _raw(s.url + "/api/action/add_party", "POST", b'{"kind":"supplier","name":"x"}', {"Content-Type": "application/json"})
            self.assertEqual(status, 401)
            status, _, _ = _raw(s.url + "/api/state", headers={"Authorization": "Bearer wrong-token-0123456789"})
            self.assertEqual(status, 401)
            status, _, _ = _raw(s.url + "/api/state", headers={"Authorization": f"Bearer {self.TOKEN}"})
            self.assertEqual(status, 200)
            # browser sign-in: ?token= sets an HttpOnly SameSite=Strict cookie and redirects, keeping other params
            status, headers, _ = _raw(s.url + f"/?token={self.TOKEN}&selftest=abc")
            self.assertEqual(status, 303)
            self.assertEqual(headers.get("Location"), "/?selftest=abc")
            cookie = headers.get("Set-Cookie", "")
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=Strict", cookie)
            status, _, body = _raw(s.url + "/", headers={"Cookie": cookie.split(";")[0]})
            self.assertEqual(status, 200)
            self.assertIn(b"Owner Console", body)
            status, _, _ = _raw(s.url + f"/?token=wrong-token-0123456789")
            self.assertEqual(status, 401)
            # with a token, any Host is acceptable (the token is the control)
            status, _, _ = _raw(s.url + "/api/state", headers={"Host": "cipher.internal:8765", "Authorization": f"Bearer {self.TOKEN}"})
            self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
