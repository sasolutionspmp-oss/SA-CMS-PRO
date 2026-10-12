"""HTTP boundary tests: the console API cannot bypass approvals and reports errors cleanly."""
import json
import os
import shutil
import tempfile
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


class GovernedActionTests(unittest.TestCase):
    """Authorities that became approval-bound stay approval-bound over HTTP."""

    def test_prime_bill_send_is_approval_bound_over_http(self):
        with BackgroundServer(Cipher()) as s:
            ok = lambda name, body: _post(s.url + f"/api/action/{name}", body)  # noqa: E731
            status, cust = ok("add_party", {"kind": "customer", "name": "Synthetic Owner Agency (HTTP)"})
            self.assertEqual(status, 200, cust)
            status, prj = ok("create_project", {"name": "HTTP project", "budget": "50000", "customer_id": cust["result"]["id"]})
            self.assertEqual(status, 200, prj)
            self.assertEqual(ok("open_period", {"period_id": "P1", "name": "P1", "start_date": "2026-10-01", "end_date": "2026-10-31"})[0], 200)
            status, prime = ok("certify_prime_bill", {"project_id": prj["result"]["id"], "period_id": "P1", "certified_cumulative": "10000"})
            self.assertEqual(status, 200, prime)
            pid = prime["result"]["id"]
            ap = ok("request_approval", {"operation": "prime_bill.approve", "subject_id": pid, "actor_role": "accountant"})[1]["result"]["id"]
            ok("approve", {"approval_id": ap})
            self.assertEqual(ok("execute", {"approval_id": ap, "actor": "accountant"})[0], 200)
            # the console's send action never sends: it opens the prime_bill.send approval
            status, body = ok("send_prime_bill", {"prime_bill_id": pid})
            self.assertEqual(status, 200, body)
            self.assertEqual((body["result"]["operation"], body["result"]["status"]), ("prime_bill.send", "pending"))
            self.assertNotEqual(c_status(s.url, pid), "sent")
            status, body = ok("request_approval", {"operation": "prime_bill.send", "subject_id": pid, "actor_role": "pm"})
            self.assertEqual(status, 200, body)
            send_ap = body["result"]["id"]
            self.assertEqual(body["result"]["manifest"]["amounts"], {"amount_due": "9000.00"})
            self.assertEqual(ok("execute", {"approval_id": send_ap, "actor": "pm"})[0], 400)  # not granted yet
            ok("approve", {"approval_id": send_ap})
            status, body = ok("execute", {"approval_id": send_ap, "actor": "pm"})
            self.assertEqual((status, body["result"]["result"]["status"], body["result"]["result"]["channel"]), (200, "sent", "mail-sink"), body)
            self.assertTrue(ok("execute", {"approval_id": send_ap, "actor": "pm"})[1]["result"]["replayed"])
            self.assertEqual(ok("request_approval", {"operation": "prime_bill.send", "subject_id": pid, "actor_role": "pm"})[0], 400)  # sent once
            # an ACH collection without the customer's recorded mandate is refused
            status, body = ok("record_collection", {"prime_bill_id": pid, "period_id": "P1", "amount": "9000", "provider_ref": "ach_sim_http_0001"})
            self.assertEqual(status, 400)
            self.assertIn("missing mandate", body["error"])
            state = _get(s.url + "/api/state?project_id=" + prj["result"]["id"])[1]
            self.assertTrue(state["trial_balance"]["balanced"])
            self.assertEqual(state["ar"]["subledger_total"], "9000.00")

    def test_payee_destination_change_is_governed_over_http(self):
        """No one-call payee verification on the console surface: the change is requested,
        verified by a different person against stored evidence, and applied only through a
        granted party.verify_destination approval."""
        with BackgroundServer(Cipher()) as s:
            ok = lambda name, body: _post(s.url + f"/api/action/{name}", body)  # noqa: E731
            self.assertEqual(ok("verify_destination", {"party_id": "x", "destination": "ACH-SIM-ANY"})[0], 404)
            sup = ok("add_party", {"kind": "supplier", "name": "Synthetic Sub (HTTP payee)", "destination": "ACH-SIM-HTTP-PAYEE-1"})[1]["result"]
            cust = ok("add_party", {"kind": "customer", "name": "Synthetic Owner (HTTP payee)"})[1]["result"]
            prj = ok("create_project", {"name": "HTTP payee project", "budget": "1000", "customer_id": cust["id"]})[1]["result"]
            status, body = ok("request_destination_change", {"party_id": sup["id"], "new_destination": "ACH-SIM-HTTP-PAYEE-1",
                                                             "requested_by": "http requester", "reason": "first verification"})
            self.assertEqual(status, 200, body)
            change_id = body["result"]["id"]
            status, body = ok("request_destination_approval", {"change_id": change_id})
            self.assertEqual(status, 400, body)  # no independent verification yet
            doc = ok("register_document", {"project_id": prj["id"], "kind": "destination_verification", "title": "call-back notes"})[1]["result"]
            rev = ok("add_revision", {"document_id": doc["id"], "content": "called the number on file", "note": "call-back"})[1]["result"]
            status, body = ok("record_verification_evidence", {"change_id": change_id, "channel": "call-back to number on file",
                                                               "verified_by": "http requester", "evidence_hash": rev["content_hash"]})
            self.assertEqual(status, 400, body)  # two-person rule
            status, body = ok("record_verification_evidence", {"change_id": change_id, "channel": "call-back to number on file",
                                                               "verified_by": "outside accountant", "evidence_hash": rev["content_hash"]})
            self.assertEqual(status, 200, body)
            self.assertFalse(next(p for p in _get(s.url + "/api/state")[1]["parties"] if p["id"] == sup["id"])["destination_verified"])
            status, body = ok("request_destination_approval", {"change_id": change_id})
            self.assertEqual((status, body["result"]["operation"], body["result"]["actor_role"]), (200, "party.verify_destination", "bank_admin"), body)
            ap = body["result"]["id"]
            self.assertEqual(ok("execute", {"approval_id": ap})[0], 400)  # not granted yet
            ok("approve", {"approval_id": ap})
            status, body = ok("execute", {"approval_id": ap})
            self.assertEqual(status, 200, body)
            self.assertTrue(next(p for p in _get(s.url + "/api/state")[1]["parties"] if p["id"] == sup["id"])["destination_verified"])
            status, hist = ok("destination_changes", {"party_id": sup["id"]})
            self.assertEqual((status, [h["status"] for h in hist["result"]]), (200, ["executed"]))

    def test_round_three_actions_over_http(self):
        """Terms, deposits, budgets and forecast snapshots are reachable; corrections and
        credits only draft (their approvals apply them)."""
        with BackgroundServer(Cipher()) as s:
            ok = lambda name, body: _post(s.url + f"/api/action/{name}", body)  # noqa: E731
            cust = ok("add_party", {"kind": "customer", "name": "Synthetic Owner (HTTP r3)"})[1]["result"]
            prj = ok("create_project", {"name": "HTTP r3 project", "budget": "0", "customer_id": cust["id"]})[1]["result"]
            self.assertEqual(ok("open_period", {"period_id": "P1", "name": "P1", "start_date": "2026-10-01", "end_date": "2026-10-31"})[0], 200)
            status, body = ok("set_customer_terms", {"customer_id": cust["id"], "days": 45})
            self.assertEqual(status, 200, body)
            status, body = ok("set_initial_budget", {"project_id": prj["id"], "lines": [{"cost_code": "03-300", "amount": "25000"}]})
            self.assertEqual(status, 200, body)
            status, body = ok("prepare_budget_revision", {"project_id": prj["id"], "lines": [{"cost_code": "03-300", "amount": "27000"}], "reason": "owner change"})
            self.assertEqual(status, 200, body)
            status, body = ok("forecast_snapshot", {"project_id": prj["id"], "label": "http month-end"})
            self.assertEqual(status, 200, body)
            status, body = ok("record_deposit", {"customer_id": cust["id"], "project_id": prj["id"], "amount": "5000",
                                                 "provider_ref": "wire_sim_http_dep_1", "method": "wire", "period_id": "P1"})
            self.assertEqual(status, 200, body)
            state = _get(s.url + "/api/state?project=" + prj["id"])[1]
            self.assertTrue(state["trial_balance"]["balanced"])
            self.assertEqual(ok("stale_payments", {})[1]["result"], [])
            self.assertEqual(ok("prepare_credit_note", {"bill_id": "nope", "amount": "1", "reason": "r", "evidence_hash": "h"})[0], 400)
            self.assertEqual(ok("prepare_write_off", {"prime_bill_id": "nope", "amount": "1"})[0], 400)  # missing reason

    def test_restored_copy_is_read_only_over_http_until_claimed(self):
        d = tempfile.mkdtemp(prefix="cipher-http-restore-")
        self.addCleanup(shutil.rmtree, d, True)
        live = Cipher(os.path.join(d, "live.sqlite"))
        self.addCleanup(live.db.close)
        live.add_party(kind="supplier", name="Synthetic Subcontractor (HTTP)", destination="ACH-SIM-HTTP-0001")
        restored = Cipher.open_restored(live.snapshot(os.path.join(d, "backup.sqlite")), provider=live.provider)
        self.addCleanup(restored.db.close)
        with BackgroundServer(restored) as s:
            status, health = _get(s.url + "/api/health")
            self.assertEqual((status, health["authority"]["effective_write_authority"]), (200, False))
            status, body = _post(s.url + "/api/action/add_party", {"kind": "supplier", "name": "Injected payee", "destination": "ACH-SIM-INJECTED"})
            self.assertEqual((status, body["type"]), (400, "WriteAuthorityError"))
            status, body = _post(s.url + "/api/action/dispatch_payments", {})
            self.assertEqual((status, body["type"]), (400, "ReleaseQuarantined"))
            status, body = _post(s.url + "/api/action/claim_authority", {"approval_ref": "ext-ref-http-restore-drill"})
            self.assertEqual(status, 200, body)
            self.assertEqual((body["result"]["effective_write_authority"], body["result"]["release_quarantined"]), (True, True))
            status, body = _post(s.url + "/api/action/dispatch_payments", {})
            self.assertEqual((status, body["type"]), (400, "ReleaseQuarantined"))
            status, body = _post(s.url + "/api/action/complete_recovery", {"actor": "reconciler"})
            self.assertEqual((status, body["result"]["quarantine_lifted"]), (200, True), body)
            self.assertEqual(_post(s.url + "/api/action/dispatch_payments", {}), (200, {"ok": True, "result": []}))
            self.assertEqual(_post(s.url + "/api/action/add_party", {"kind": "supplier", "name": "Claimed copy payee"})[0], 200)
        self.assertEqual([p["name"] for p in restored.parties()], ["Synthetic Subcontractor (HTTP)", "Claimed copy payee"])


def c_status(base, prime_bill_id):
    """Status of a prime bill as the console sees it."""
    status, state = _get(base + "/api/state")
    return next((b["status"] for b in state.get("prime_bills", []) if b["id"] == prime_bill_id), None)


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
