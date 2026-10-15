"""Nine genuine RFI HTTP actions, original retries and isolated transport."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.rfi_practice_server import API_PREFIX, COOKIE_NAME, make_rfi_practice_server
from apps.cipher.rfi_practice_fixture import STAFF_LOGIN, PM_LOGIN, BOOTSTRAP_LOGIN
from apps.cipher.core.db import WorkspaceModeError


class RFIPracticeServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "assets").mkdir()
        (self.root / "rfi-practice.html").write_text('<!doctype html><meta name="cipher-style-nonce" content="__CIPHER_STYLE_NONCE__"><div id="root"></div><script type="module" src="/assets/app.js"></script>')
        (self.root / "assets" / "app.js").write_text("export const rfi = true;")
        self.server = make_rfi_practice_server(port=0, webroot=self.root)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.c = self.server.cipher
        self.project = self.c.rfi_practice_records["project_id"]

    def request(self, path, *, method="GET", headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def api(self, path, **kwargs):
        status, headers, raw = self.request(API_PREFIX + path, **kwargs)
        return status, headers, json.loads(raw) if raw else None

    def session(self, persona="staff"):
        status, headers, body = self.api("session")
        self.assertEqual(status, 200, body)
        outgoing = {"Cookie": headers["Set-Cookie"].split(";", 1)[0], "X-CSRF-Token": body["csrfToken"],
            "Origin": self.origin, "Content-Type": "application/json"}
        status, headers, body = self.api("session", method="POST", headers=outgoing, body=json.dumps({"personaId": persona}))
        self.assertEqual(status, 200, body)
        outgoing.update({"Cookie": headers["Set-Cookie"].split(";", 1)[0], "X-CSRF-Token": body["csrfToken"]})
        return outgoing

    def state(self):
        with self.server.cipher_lock:
            return tuple(self.c.db.conn.iterdump()), tuple(self.c.provider.submissions), dict(self.c.provider.transfers)

    def question(self, **changes):
        records = self.c.rfi_practice_records
        return {"subject": "Synthetic drainage question", "question": "Which alignment should the crew use?",
            "drawingRevisionIds": [records["drawing_revision_id"]], "documentRevisionIds": [records["document_revision_id"]], **changes}

    def prepared(self, headers, route, body=None):
        typed = {} if body is None else body
        before = self.state()
        status, _, review = self.api(route + ":preflight", method="POST", headers=headers, body=json.dumps(typed))
        self.assertEqual(status, 200, review); self.assertTrue(review["allowed"], review)
        self.assertEqual(self.state(), before); self.assertEqual(review["safeEffects"]["journalDelta"], 0)
        self.assertFalse(review["safeEffects"]["externalDistribution"])
        return route, {**headers, "Repeatability-Request-ID": str(uuid4()), "If-Match": '"' + review["resourceVersion"] + '"'}, json.dumps({**typed, "fingerprint": review["fingerprint"]})

    def send(self, request):
        route, headers, body = request
        return self.api(route, method="POST", headers=headers, body=body)

    def act(self, headers, route, body=None):
        request = self.prepared(headers, route, body)
        status, _, result = self.send(request)
        self.assertEqual(status, 200, result); self.assertTrue(result["effectApplied"])
        return result, request

    def granted(self):
        staff, pm, reviewer = self.session(), self.session("pm"), self.session("reviewer")
        created, create_request = self.act(staff, f"projects/{self.project}/rfis", self.question())
        rfi = created["result"]["rfiId"]
        draft, draft_request = self.act(staff, f"rfis/{rfi}/draft-response", {"responseText": "Use the east alignment. Potential impacts only.", "costImpact": "1250.05", "scheduleImpactDays": 3})
        requested, request = self.act(pm, f"rfis/{rfi}/request-response")
        approval = requested["result"]["approvalId"]
        granted, grant_request = self.act(reviewer, f"rfi-response-approvals/{approval}/approve")
        return staff, pm, reviewer, rfi, approval, [(created, create_request), (draft, draft_request), (requested, request), (granted, grant_request)]

    def test_all_nine_actual_actions_replay_original_outcomes_after_real_later_source_revision(self):
        staff, pm, reviewer, rfi, approval, receipts = self.granted()
        self.assertEqual(self.c.approvals.get(approval)["status"], "granted")
        self.assertEqual(self.c.plugin("field").rfi(rfi)["status"], "open")
        answered, request = self.act(pm, f"rfi-response-approvals/{approval}/apply"); receipts.append((answered, request))
        recipients = [self.c.rfi_practice_records["allowed_recipients"][0]]
        listed, request = self.act(pm, f"rfis/{rfi}/distribution-list", {"recipients": recipients}); receipts.append((listed, request))
        requested, request = self.act(pm, f"rfis/{rfi}/request-distribution"); receipts.append((requested, request))
        distribution_approval = requested["result"]["approvalId"]
        granted, request = self.act(reviewer, f"rfi-distribution-approvals/{distribution_approval}/approve"); receipts.append((granted, request))
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM field_rfi_distributions"), 0)
        sent, request = self.act(pm, f"rfi-distribution-approvals/{distribution_approval}/distribute"); receipts.append((sent, request))
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM field_rfi_distributions"), 1)
        later = self.c.evidence.add_revision(document_id=self.c.rfi_practice_records["document_id"], content="Later genuine synthetic specification", actor=PM_LOGIN)
        status, response_headers, dto = self.api(f"rfis/{rfi}", headers=staff)
        self.assertEqual(status, 200, dto); self.assertEqual(response_headers["ETag"], '"' + dto["version"] + '"')
        self.assertEqual(dto["status"], "answered"); self.assertEqual(dto["officialResponse"]["costImpactCents"], 125005)
        self.assertEqual(dto["citations"]["documents"][0]["revisionId"], self.c.rfi_practice_records["document_revision_id"])
        self.assertEqual(dto["citations"]["documents"][0]["currentRevisionId"], later["id"])
        for original, attempt in receipts:
            before = self.state(); status, _, replay = self.send(attempt)
            self.assertEqual(status, 200, replay); self.assertEqual(replay, {**original, "replayed": True, "effectApplied": False})
            self.assertEqual(self.state(), before)
        for table in ("journals", "changes", "commitments", "outbox"):
            self.assertEqual(self.c.db.scalar(f"SELECT COUNT(*) FROM {table}"), 0)
        self.assertEqual(self.c.provider.submissions, [])

    def test_factory_owns_fresh_memory_and_cannot_select_file_actor_or_provider(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1'); self.assertTrue(self.c.db.in_memory)
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM field_rfis'), 0)
        for key, value in (('path', 'live.sqlite'), ('host', '0.0.0.0'), ('cipher', self.c), ('actor', 'owner'), ('mode', 'live'), ('provider', object()), ('credentials', {})):
            with self.subTest(key=key), self.assertRaises(TypeError): make_rfi_practice_server(port=0, **{key: value})

    def test_strict_origins_csrf_other_application_cookie_and_body_selectors_refuse_before_effect(self):
        headers = self.session(); route = f'projects/{self.project}/rfis:preflight'; before = self.state()
        for override, expected in (({'Origin': 'https://foreign.invalid'}, 403), ({'X-CSRF-Token': 'wrong'}, 403), ({'Cookie': 'cipher_library_practice=foreign_application_cookie_token'}, 401)):
            self.assertEqual(self.api(route, method='POST', headers={**headers, **override}, body=json.dumps(self.question()))[0], expected)
        for key in ('actor', 'personId', 'role', 'rightsUse', 'provider', 'filePath', 'destination', 'channel'):
            self.assertEqual(self.api(route, method='POST', headers=headers, body=json.dumps(self.question(**{key: 'selected'})))[0], 422)
        self.assertEqual(self.state(), before)

    def test_duplicate_framing_and_bounded_envelope_refuse_before_effect(self):
        headers = self.session(); route = API_PREFIX + f'projects/{self.project}/rfis:preflight'; before = self.state()
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        try:
            conn.putrequest('POST', route)
            for key, value in headers.items(): conn.putheader(key, value)
            conn.putheader('Content-Length', '2'); conn.putheader('Content-Length', '3'); conn.endheaders(b'{}')
            response = conn.getresponse(); self.assertEqual(response.status, 400); response.read()
        finally: conn.close()
        for extra, status in (({'Transfer-Encoding': 'chunked'}, 400), ({'Content-Length': '262145'}, 413), ({'Content-Type': 'text/plain'}, 415)):
            self.assertEqual(self.api(route.removeprefix(API_PREFIX), method='POST', headers={**headers, **extra}, body='{}')[0], status)
        self.assertEqual(self.api(route.removeprefix(API_PREFIX), method='POST', headers=headers, body='{"subject":"A","subject":"B"}')[0], 422)
        self.assertEqual(self.state(), before)

    def test_maximum_unicode_question_survives_default_json_surrogate_escape_envelope(self):
        headers = self.session(); question = self.question(question='😀' * 12000); raw = json.dumps(question)
        self.assertGreater(len(raw.encode()), 131072); self.assertLess(len(raw.encode()), 262144)
        before = self.state(); status, _, review = self.api(f'projects/{self.project}/rfis:preflight', method='POST', headers=headers, body=raw)
        self.assertEqual(status, 200, review); self.assertTrue(review['allowed']); self.assertEqual(review['preview']['question'], question['question'])
        self.assertEqual(self.state(), before)

    def test_staff_cannot_enter_any_consequential_route_even_with_review_fields(self):
        staff = self.session(); created, _ = self.act(staff, f'projects/{self.project}/rfis', self.question()); rfi = created['result']['rfiId']
        before = self.state()
        for route, body in ((f'rfis/{rfi}/request-response:preflight', {}), (f'rfis/{rfi}/distribution-list:preflight', {'recipients': [self.c.rfi_practice_records['allowed_recipients'][0]]}), (f'rfis/{rfi}/request-distribution:preflight', {})):
            self.assertEqual(self.api(route, method='POST', headers=staff, body=json.dumps(body))[0], 403)
        self.assertEqual(self.api(f'rfis/{rfi}/distribution-preparation', headers=staff)[0], 403); self.assertEqual(self.state(), before)

    def test_current_membership_precedes_completed_receipt_lookup_and_uuid_and_if_match_are_exact(self):
        request = self.prepared(self.session(), f'projects/{self.project}/rfis', self.question()); before = self.state()
        for overrides in ({'If-Match': request[1]['If-Match'].strip('"')}, {'If-Match': 'W/"old"'}, {'Repeatability-Request-ID': 'wrong'}):
            self.assertEqual(self.send((request[0], {**request[1], **overrides}, request[2]))[0], 422)
        self.assertEqual(self.state(), before); self.assertEqual(self.send(request)[0], 200)
        self.c.plugin('people').end_membership(STAFF_LOGIN, self.project, reason='Synthetic RFI staff membership ended', actor=BOOTSTRAP_LOGIN)
        before = self.state()
        with patch.object(self.server.actions.receipts, 'find', side_effect=AssertionError('Ended member disclosed a receipt')) as find:
            self.assertIn(self.send(request)[0], (401, 403, 404)); find.assert_not_called()
        self.assertEqual(self.state(), before)

    def test_simultaneous_original_apply_consumes_one_grant_and_records_one_answer(self):
        _, pm, _, rfi, approval, _ = self.granted(); request = self.prepared(pm, f'rfi-response-approvals/{approval}/apply')
        with ThreadPoolExecutor(max_workers=2) as executor: responses = list(executor.map(lambda _: self.send(request), range(2)))
        self.assertEqual([response[0] for response in responses], [200, 200], responses)
        self.assertEqual(responses[0][2]['receiptId'], responses[1][2]['receiptId']); self.assertEqual(sum(response[2]['effectApplied'] for response in responses), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='field.rfi_answered' AND entity_id=?", (rfi,)), 1)
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM journals'), 0)

    def test_late_receipt_failure_rolls_back_answer_consumption_and_native_command(self):
        _, pm, _, rfi, approval, _ = self.granted(); request = self.prepared(pm, f'rfi-response-approvals/{approval}/apply'); before = self.state()
        with patch.object(self.server.actions.receipts, 'record', side_effect=RuntimeError('private injected receipt fault')):
            status, _, refusal = self.send(request)
        self.assertEqual(status, 500, refusal); self.assertNotIn('private injected', json.dumps(refusal)); self.assertEqual(self.state(), before)
        self.assertEqual(self.c.approvals.get(approval)['status'], 'granted'); self.assertEqual(self.c.plugin('field').rfi(rfi)['status'], 'open')
        self.assertEqual(self.send(request)[0], 200)

    def test_actual_lost_tcp_response_retains_original_receipt_for_same_uuid(self):
        request = self.prepared(self.session(), f'projects/{self.project}/rfis', self.question()); route, headers, body = request
        raw = (f'POST {API_PREFIX + route} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n' + ''.join(f'{key}: {value}\r\n' for key, value in headers.items()) + f'Content-Length: {len(body.encode())}\r\nConnection: close\r\n\r\n' + body).encode()
        with socket.create_connection(('127.0.0.1', self.port), timeout=10) as conn: conn.sendall(raw); conn.shutdown(socket.SHUT_RDWR)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.server.cipher_lock:
                if self.c.db.scalar('SELECT COUNT(*) FROM rfi_action_receipts'): break
            time.sleep(.01)
        else: self.fail('Disconnected request lost its original completed receipt')
        before = self.state(); status, _, replay = self.send(request)
        self.assertEqual(status, 200, replay); self.assertTrue(replay['replayed']); self.assertFalse(replay['effectApplied']); self.assertEqual(self.state(), before)

    def test_current_reads_head_etag_hidden_scope_and_static_nonce_csp(self):
        staff = self.session(); before = self.state()
        for route in ('projects', 'rfis', 'rfi-response-approvals', 'rfi-distribution-approvals', f'projects/{self.project}/preparation'):
            self.assertEqual(self.api(route, headers=staff)[0], 200, route)
        status, headers, body = self.request(API_PREFIX + f'projects/{self.project}/preparation', method='HEAD', headers=staff)
        self.assertEqual(status, 200); self.assertEqual(body, b''); self.assertIn('ETag', headers)
        hidden = self.c.rfi_practice_records['hidden_project_id']; self.assertEqual(self.api(f'projects/{hidden}/preparation', headers=staff)[0], 404)
        self.assertEqual(self.api(f'rfis?projectId={hidden}', headers=staff)[0], 404); self.assertEqual(self.state(), before)
        status, headers, first = self.request('/'); self.assertEqual(status, 200); self.assertNotIn(b'__CIPHER_STYLE_NONCE__', first)
        self.assertIn("style-src 'self' 'nonce-", headers['Content-Security-Policy']); self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertNotEqual(first, self.request('/')[2]); self.assertEqual(self.request('/rfi/log')[0], 200)
        for path in ('/../private.py', '/%2e%2e/private.py', '/assets/missing.js', '/api/library-practice/v1/session', '/api/rfi-practice/v1/execute'):
            self.assertIn(self.request(path)[0], (400, 404))
        with patch.object(self.server, 'require_practice', side_effect=WorkspaceModeError('private mode reason')):
            status, _, body = self.api('session')
        self.assertEqual(status, 503); self.assertNotIn('private mode reason', json.dumps(body))

    def test_cli_selects_only_owned_rfi_server_and_port(self):
        from apps.cipher.__main__ import main
        with patch('apps.cipher.rfi_practice_server.serve_rfi_practice') as serve:
            self.assertEqual(main(['rfi-practice-web', '--port', '8771']), 0); serve.assert_called_once_with(port=8771)
        for option in ('--db', '--host', '--actor', '--provider', '--token'):
            with self.subTest(option=option), patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit): main(['rfi-practice-web', option, 'caller-selected'])

    def test_genuine_source_head_change_definitively_refuses_old_create_then_new_current_review_can_complete(self):
        staff = self.session(); request = self.prepared(staff, f'projects/{self.project}/rfis', self.question())
        later = self.c.evidence.add_revision(document_id=self.c.rfi_practice_records['document_id'], content='Genuine revised current supporting source', actor=PM_LOGIN)
        before = self.state(); status, _, refusal = self.send(request)
        self.assertEqual(status, 412, refusal); self.assertEqual(refusal['error']['code'], 'record_changed')
        self.assertEqual(self.send(request)[0], 412); self.assertEqual(self.state(), before)
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM rfi_action_receipts'), 0)
        fresh, _ = self.act(staff, f'projects/{self.project}/rfis', self.question(documentRevisionIds=[later['id']]))
        self.assertEqual(fresh['result']['status'], 'open'); self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM field_rfis'), 1)
