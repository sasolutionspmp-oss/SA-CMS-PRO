"""Actual HTTP preparation/intake boundaries and separated human match workflow."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from apps.cipher.ap_practice_server import make_ap_practice_server


PREFIX = "/api/ap-practice/v1/"


class APIntakeHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "ap-practice.html").write_text(
            '<!doctype html><meta name="cipher-style-nonce" content="__CIPHER_STYLE_NONCE__"><div id="root"></div>',
            encoding="utf-8")
        self.server = make_ap_practice_server(port=0, webroot=self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.records = self.server.cipher.ap_practice_records

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp.cleanup()

    def request(self, route, *, method="GET", headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, PREFIX + route, body=body, headers=headers or {})
            response = conn.getresponse()
            raw = response.read()
            return response.status, dict(response.getheaders()), json.loads(raw) if raw else None
        finally:
            conn.close()

    def session(self, persona="accountant"):
        status, headers, body = self.request("session")
        self.assertEqual(status, 200, body)
        auth = {"Cookie": headers["Set-Cookie"].split(";", 1)[0], "X-CSRF-Token": body["csrfToken"],
                "Origin": self.origin, "Content-Type": "application/json"}
        status, headers, body = self.request("session", method="POST", headers=auth,
                                             body=json.dumps({"personaId": persona}))
        self.assertEqual(status, 200, body)
        auth.update({"Cookie": headers["Set-Cookie"].split(";", 1)[0], "X-CSRF-Token": body["csrfToken"]})
        return auth, body

    def snapshot(self):
        with self.server.cipher_lock:
            c = self.server.cipher
            return ("\n".join(c.db.conn.iterdump()), c.db.conn.total_changes,
                    tuple(c.provider.submissions), dict(c.provider.transfers))

    def prepare_body(self):
        c = self.server.cipher
        commitment = c.commitments.get(self.records["prep_commitment_id"])
        return {"periodId": "2026-10", "installed": [
            {"sovLineId": line["id"], "cumulativeInstalledCents": amount}
            for line, amount in zip(commitment["sov"], (100_000, 200_000))]}

    def receive_body(self, *, number="SYN-INTAKE-1001", amount=270_000, evidence=None):
        return {"invoiceNumber": number, "invoiceDate": "2026-10-14", "amountCents": amount,
                "evidenceRevisionId": evidence or self.records["visible_invoice_evidence_revision_ids"][0]}

    def preflight(self, route, headers, body):
        status, _, review = self.request(route + ":preflight", method="POST", headers=headers, body=json.dumps(body))
        self.assertEqual(status, 200, review)
        return review

    def action_request(self, route, headers, data):
        before = self.snapshot()
        review = self.preflight(route, headers, data)
        self.assertTrue(review["allowed"], review)
        self.assertEqual(before, self.snapshot(), "The action review must write nothing.")
        headers = {**headers, "If-Match": '"' + review["resourceVersion"] + '"', "Repeatability-Request-ID": str(uuid.uuid4())}
        body = json.dumps({**data, "fingerprint": review["fingerprint"]})
        return headers, body

    def action(self, route, headers, data, *, replay=True):
        action_headers, body = self.action_request(route, headers, data)
        status, _, result = self.request(route, method="POST", headers=action_headers, body=body)
        self.assertEqual(status, 200, result)
        self.assertTrue(result["effectApplied"], result)
        self.assertFalse(result["replayed"], result)
        if replay:
            before = self.snapshot()
            status, _, repeated = self.request(route, method="POST", headers=action_headers, body=body)
            self.assertEqual(status, 200, repeated)
            self.assertTrue(repeated["replayed"])
            self.assertFalse(repeated["effectApplied"])
            self.assertEqual(repeated["result"], result["result"])
            self.assertEqual(repeated["receiptId"], result["receiptId"])
            self.assertEqual(before, self.snapshot())
        return result

    def test_registered_reviewer_has_accountant_duty_and_no_owner_persona(self):
        headers, reviewer = self.session("reviewer")
        _, accountant = self.session()
        self.assertEqual(reviewer["duties"], ["accountant"])
        self.assertNotEqual(reviewer["person"]["id"], accountant["person"]["id"])
        status, _, personas = self.request("personas", headers=headers)
        self.assertEqual(status, 200, personas)
        self.assertIn("reviewer", {value["personaId"] for value in personas["value"]})
        self.assertNotIn("owner", json.dumps(personas))

    def test_scoped_collections_preparation_etag_and_evidence_hide_hidden_job(self):
        headers, _ = self.session()
        before = self.snapshot()
        for route in ("invoices", "invoice-evidence", "match-approvals"):
            status, _, body = self.request(route, headers=headers)
            self.assertEqual(status, 200, body)
            self.assertNotIn(self.records["hidden_project_id"], json.dumps(body))
            self.assertNotIn("Hidden synthetic", json.dumps(body))
            self.assertEqual(body["mode"], "practice")
            self.assertTrue(body["synthetic"])
            self.assertEqual(self.request(route + "?projectId=" + self.records["hidden_project_id"], headers=headers)[0], 404)
        status, response_headers, preparation = self.request(
            "commitments/" + self.records["prep_commitment_id"] + "/preparation", headers=headers)
        self.assertEqual(status, 200, preparation)
        self.assertEqual(response_headers["ETag"], '"' + preparation["version"] + '"')
        self.assertEqual(len(preparation["lines"]), 2)
        for route in ("commitments/" + self.records["hidden_commitment_id"] + "/preparation",
                      "invoices/unreadable", "match-approvals/unreadable/packet"):
            self.assertEqual(self.request(route, headers=headers)[0], 404, route)
        self.assertEqual(before, self.snapshot())

    def test_new_routes_require_session_origin_and_csrf(self):
        headers, _ = self.session()
        route = "commitments/" + self.records["prep_commitment_id"] + "/prepare-bill:preflight"
        body = json.dumps(self.prepare_body())
        before = self.snapshot()
        self.assertEqual(self.request("invoice-evidence")[0], 401)
        for omit, expected in (("Cookie", 401), ("X-CSRF-Token", 403), ("Origin", 403)):
            altered = {key: value for key, value in headers.items() if key != omit}
            self.assertEqual(self.request(route, method="POST", headers=altered, body=body)[0], expected)
        for altered in ({**headers, "Origin": "https://outside.example"},
                        {**headers, "X-CSRF-Token": "bad"}, {**headers, "Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.request(route, method="POST", headers=altered, body=body)[0], 403)
        self.assertEqual(before, self.snapshot())

    def test_action_specific_integer_and_nested_body_shapes_refuse_forgery(self):
        headers, _ = self.session()
        commitment = self.records["prep_commitment_id"]
        prepare_route = "commitments/" + commitment + "/prepare-bill:preflight"
        receive_route = "commitments/" + commitment + "/receive-invoice:preflight"
        data = self.prepare_body()
        row = data["installed"][0]
        invalid = [{**data, "installed": value} for value in ({}, None, [], [row] * 101)]
        invalid.extend({**data, "installed": [value]} for value in (
            {**row, "actor": "owner"}, {"sovLineId": row["sovLineId"]},
            {**row, "sovLineId": "../source"}, {**row, "sovLineId": 7}))
        invalid.extend({**data, "installed": [{**row, "cumulativeInstalledCents": value}]} for value in
                       (True, False, "100", 100.0, -1, 9_007_199_254_740_992, None))
        invalid.append({**data, "installed": [row, row]})
        invalid.extend({**data, key: "owner"} for key in ("actor", "actorRole", "role", "personId", "provider", "mode", "supplierId"))
        before = self.snapshot()
        for value in invalid:
            status, _, refusal = self.request(prepare_route, method="POST", headers=headers, body=json.dumps(value))
            self.assertEqual(status, 422, (value, refusal))
        for field, value in (("amountCents", True), ("amountCents", 2.5), ("amountCents", "270000"),
                             ("amountCents", 0), ("amountCents", -1), ("amountCents", 9_007_199_254_740_992),
                             ("evidenceRevisionId", "../secret"), ("invoiceNumber", False),
                             ("invoiceDate", "10/14/2026"), ("supplierId", "caller-supplier")):
            status, _, refusal = self.request(receive_route, method="POST", headers=headers,
                                               body=json.dumps({**self.receive_body(), field: value}))
            self.assertEqual(status, 422, (field, value, refusal))
        self.assertEqual(before, self.snapshot())

    def test_duplicate_json_fields_at_any_depth_and_large_body_have_no_effect(self):
        headers, _ = self.session()
        commitment = self.records["prep_commitment_id"]
        route = "commitments/" + commitment + "/prepare-bill:preflight"
        sov_id = self.prepare_body()["installed"][0]["sovLineId"]
        duplicate = ('{"periodId":"2026-10","installed":[{"sovLineId":"' + sov_id +
                     '","cumulativeInstalledCents":100,"cumulativeInstalledCents":200}]}')
        before = self.snapshot()
        for raw in (duplicate, '{"periodId":"2026-10","periodId":"2026-11","installed":[]}',
                    '{"periodId":"2026-10","installed":[{"sovLineId":"x","sovLineId":"y","cumulativeInstalledCents":1}]}',
                    '{"periodId":"2026-10","installed":NaN}', "null", "[]"):
            self.assertEqual(self.request(route, method="POST", headers=headers, body=raw)[0], 422)
        self.assertEqual(self.request(route, method="POST", headers=headers, body="x" * 16_385)[0], 413)
        self.assertEqual(before, self.snapshot())

    def test_old_bill_and_session_routes_remain_string_only(self):
        headers, _ = self.session()
        before = self.snapshot()
        for route, body in (("session", {"personaId": {"role": "owner"}}),
                            ("bills/" + self.records["approved_bill_id"] + "/post:preflight", {"periodId": 202610, "reason": ""}),
                            ("bills/" + self.records["draft_bill_id"] + "/request-approval:preflight", {"installed": []})):
            self.assertEqual(self.request(route, method="POST", headers=headers, body=json.dumps(body))[0], 422)
        self.assertEqual(before, self.snapshot())

    def test_hidden_commitment_and_hidden_invoice_evidence_are_consistent_not_found(self):
        headers, _ = self.session()
        before = self.snapshot()
        for commitment, evidence in ((self.records["hidden_commitment_id"], self.records["hidden_invoice_evidence_revision_ids"][0]),
                                     (self.records["prep_commitment_id"], self.records["hidden_invoice_evidence_revision_ids"][0]),
                                     (self.records["prep_commitment_id"], "unreadable-revision")):
            route = "commitments/" + commitment + "/receive-invoice:preflight"
            status, _, refusal = self.request(route, method="POST", headers=headers, body=json.dumps(self.receive_body(evidence=evidence)))
            self.assertEqual(status, 404, refusal)
            self.assertNotIn("Hidden", json.dumps(refusal))
        self.assertEqual(before, self.snapshot())

    def test_original_accountant_distinct_reviewer_and_pm_complete_journal_free_match_then_post(self):
        accountant, accountant_dto = self.session()
        reviewer, reviewer_dto = self.session("reviewer")
        pm, pm_dto = self.session("pm")
        self.assertEqual(len({accountant_dto["person"]["id"], reviewer_dto["person"]["id"], pm_dto["person"]["id"]}), 3)
        c = self.server.cipher
        journal_count = c.db.one("SELECT COUNT(*) AS n FROM journals")["n"]
        commitment = self.records["prep_commitment_id"]
        prepared = self.action("commitments/" + commitment + "/prepare-bill", accountant, self.prepare_body())
        bill_id = prepared["result"]["billId"]
        received = self.action("commitments/" + commitment + "/receive-invoice", accountant, self.receive_body())
        invoice_id = received["result"]["invoiceId"]
        computed = self.action("invoices/" + invoice_id + "/compute-match", accountant, {})
        self.assertEqual(computed["result"]["status"], "matched")
        requested = self.action("invoices/" + invoice_id + "/request-match-approval", accountant, {})
        match_approval = requested["result"]["approvalId"]
        status, response_headers, packet = self.request("match-approvals/" + match_approval + "/packet", headers=reviewer)
        self.assertEqual(status, 200, packet)
        self.assertEqual(response_headers["ETag"], '"' + packet["version"] + '"')
        self.assertEqual(c.db.one("SELECT COUNT(*) AS n FROM journals")["n"], journal_count)
        self.assertFalse(self.preflight("match-approvals/" + match_approval + "/approve", accountant, {})["allowed"])
        self.action("match-approvals/" + match_approval + "/approve", reviewer, {})
        self.action("match-approvals/" + match_approval + "/execute", accountant, {})
        status, _, invoice = self.request("invoices/" + invoice_id, headers=accountant)
        self.assertEqual(status, 200, invoice)
        self.assertEqual(invoice["status"], "matched")
        self.assertEqual(c.bills.get(bill_id)["supplier_invoice_id"], invoice_id)
        self.assertEqual(c.db.one("SELECT COUNT(*) AS n FROM journals")["n"], journal_count)
        self.assertEqual(str(c.bills.open_payable(bill_id)), "0.00")
        bill_request = self.action("bills/" + bill_id + "/request-approval", accountant, {})
        self.action("approvals/" + bill_request["result"]["approvalId"] + "/approve", pm, {})
        self.assertEqual(c.db.one("SELECT COUNT(*) AS n FROM journals")["n"], journal_count)
        self.assertEqual(str(c.bills.open_payable(bill_id)), "0.00")
        self.action("bills/" + bill_id + "/post", accountant, {"periodId": "2026-10", "reason": ""})
        self.assertEqual(c.bills.get(bill_id)["status"], "posted")
        self.assertEqual(c.db.one("SELECT COUNT(*) AS n FROM journals")["n"], journal_count + 1)
        self.assertEqual(str(c.bills.open_payable(bill_id)), "2700.00")
        self.assertFalse(c.provider.submissions)
        self.assertFalse(c.provider.transfers)

    def test_new_collection_filters_cursor_and_totals_follow_current_scope(self):
        headers, _ = self.session()
        other, _ = self.session("reviewer")
        project = self.records["visible_project_ids"][0]
        status, _, evidence = self.request("invoice-evidence?projectId=" + project + "&status=available&search=Synthetic&top=1", headers=headers)
        self.assertEqual(status, 200, evidence)
        self.assertEqual(evidence["count"], 3)
        self.assertEqual(len(evidence["value"]), 1)
        self.assertIsNotNone(evidence["nextCursor"])
        cursor_route = "invoice-evidence?projectId=" + project + "&status=available&search=Synthetic&top=1&cursor=" + evidence["nextCursor"]
        self.assertEqual(self.request(cursor_route, headers=headers)[0], 200)
        self.assertNotEqual(self.request(cursor_route, headers=other)[0], 200)
        self.action("commitments/" + self.records["prep_commitment_id"] + "/receive-invoice", headers, self.receive_body())
        status, _, invoices = self.request("invoices?projectId=" + project + "&status=received&search=SYN-INTAKE", headers=headers)
        self.assertEqual(status, 200, invoices)
        self.assertEqual(invoices["count"], 1)
        self.assertEqual(invoices["totals"]["amountCents"], 270_000)
        for collection in ("invoices", "invoice-evidence", "match-approvals"):
            for query in ("role=owner", "actor=owner", "provider=real", "mode=live", "top=1&top=2", "status=bogus"):
                self.assertIn(self.request(collection + "?" + query, headers=headers)[0], (400, 422), query)

    def test_current_session_authority_is_rechecked_after_reading_intake_body(self):
        headers, identity = self.session()
        route = "commitments/" + self.records["prep_commitment_id"] + "/prepare-bill:preflight"
        from apps.cipher.ap_practice_server import APPracticeHandler
        original_body = APPracticeHandler._body
        c = self.server.cipher
        person = c.db.one("SELECT login FROM people_persons WHERE id=?", (identity["person"]["id"],))
        def revoke_after_body(handler, **kwargs):
            result = original_body(handler, **kwargs)
            c.plugin("people").deactivate_person(person["login"], reason="Synthetic HTTP current-authority test", actor="practice.bootstrap")
            return result
        before_bills = c.db.one("SELECT COUNT(*) AS n FROM bills")["n"]
        with patch.object(APPracticeHandler, "_body", new=revoke_after_body):
            status, _, refusal = self.request(route, method="POST", headers=headers, body=json.dumps(self.prepare_body()))
        self.assertEqual(status, 401, refusal)
        self.assertEqual(c.db.one("SELECT COUNT(*) AS n FROM bills")["n"], before_bills)
        self.assertEqual(c.db.one("SELECT COUNT(*) AS n FROM ap_action_receipts")["n"], 0)
        self.assertFalse(c.provider.submissions)

    def test_concurrent_prepare_replays_once_and_changed_body_conflicts(self):
        headers, _ = self.session()
        route = "commitments/" + self.records["prep_commitment_id"] + "/prepare-bill"
        headers, body = self.action_request(route, headers, self.prepare_body())
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.request(route, method="POST", headers=headers, body=body), range(4)))
        self.assertTrue(all(status == 200 for status, _, _ in results), results)
        self.assertEqual(len({result["receiptId"] for _, _, result in results}), 1)
        self.assertEqual(sum(not result["replayed"] for _, _, result in results), 1)
        changed = json.loads(body)
        changed["installed"][0]["cumulativeInstalledCents"] += 1
        before = self.snapshot()
        self.assertEqual(self.request(route, method="POST", headers=headers, body=json.dumps(changed))[0], 409)
        self.assertEqual(before, self.snapshot())

    def test_changed_preparation_version_or_fingerprint_has_no_effect(self):
        headers, _ = self.session()
        route = "commitments/" + self.records["prep_commitment_id"] + "/prepare-bill"
        data = self.prepare_body()
        review = self.preflight(route, headers, data)
        self.assertTrue(review["allowed"], review)
        before = self.snapshot()
        for version, fingerprint in (("stale-version", review["fingerprint"]), (review["resourceVersion"], "changed-fingerprint")):
            action_headers = {**headers, "If-Match": '"' + version + '"', "Repeatability-Request-ID": str(uuid.uuid4())}
            status, _, refusal = self.request(route, method="POST", headers=action_headers,
                                               body=json.dumps({**data, "fingerprint": fingerprint}))
            self.assertEqual(status, 412, refusal)
        self.assertEqual(before, self.snapshot())

    def test_every_intake_action_uses_fixed_body_and_review_headers(self):
        headers, _ = self.session()
        before = self.snapshot()
        routes = ("commitments/" + self.records["prep_commitment_id"] + "/prepare-bill",
                  "commitments/" + self.records["prep_commitment_id"] + "/receive-invoice",
                  "invoices/unreadable/compute-match", "invoices/unreadable/request-match-approval",
                  "match-approvals/unreadable/approve", "match-approvals/unreadable/execute")
        for route in routes:
            data = self.prepare_body() if route.endswith("prepare-bill") else self.receive_body() if route.endswith("receive-invoice") else {}
            for forged in ("actor", "personId", "role", "mode", "provider", "operation"):
                status, _, refusal = self.request(route + ":preflight", method="POST", headers=headers,
                                                   body=json.dumps({**data, forged: "owner"}))
                self.assertEqual(status, 422, (route, refusal))
            for invalid_headers in (
                {"If-Match": '"version"', "Repeatability-Request-ID": "invalid"},
                {"If-Match": "version", "Repeatability-Request-ID": str(uuid.uuid4())},
            ):
                status, _, refusal = self.request(route, method="POST", headers={**headers, **invalid_headers},
                                                   body=json.dumps({**data, "fingerprint": "unreviewed"}))
                self.assertEqual(status, 422, (route, refusal))
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
