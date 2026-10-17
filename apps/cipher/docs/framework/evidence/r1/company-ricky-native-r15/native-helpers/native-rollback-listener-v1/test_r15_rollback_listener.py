"""Pure host tests: no native database, socket, HTTP, worker or identity edit."""
from copy import deepcopy
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('r15_listener_under_test', HERE / 'r15_rollback_listener.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)


def fixed(directory):
    return {'schema': r.SCHEMA, 'evidence_directory': str(directory), 'manifest_path': str(directory.parent / 'fixture.secret.json'),
        'binding': {'site': 'synthetic.localhost', 'company': 'Synthetic Company', 'user': 'original@example.test',
            'person': 'original-person', 'run_id': 'run-original', 'proposal_id': 'proposal-original', 'reviewed_sha256': 'reviewed',
            'session_reference': hashlib.sha256(b'original-sid').hexdigest()},
        'operation_id': '00000000-0000-4000-8000-000000000001',
        'payload': {'company': 'Synthetic Company', 'proposal_id': 'proposal-original',
            'operation_id': '00000000-0000-4000-8000-000000000001'}, 'port': 18991, 'bind': '127.0.0.1', 'method': 'POST', 'path': r.ROUTE,
        'lifecycle_source_sha256': r.SOURCE_SHA256, 'v3_sha256': r.V3_SHA256}


def request(bound):
    raw = json.dumps(bound['payload']).encode()
    return SimpleNamespace(remote_addr='127.0.0.1', method='POST', path=r.ROUTE, query_string=b'',
        host=bound['binding']['site'], scheme='http', mimetype='application/json', content_length=len(raw),
        headers={'X-Frappe-CSRF-Token': 'original-csrf', 'Idempotency-Key': bound['operation_id']},
        cookies={'sid': 'original-sid'}, get_data=lambda **kw: raw)


class Native:
    def __init__(self):
        self.events = []
        self.frappe = SimpleNamespace(local=SimpleNamespace(site='synthetic.localhost', request=None,
            db=SimpleNamespace(rollback=lambda **kw: self.events.append(('rollback', kw)))),
            session=SimpleNamespace(sid='original-sid', data=SimpleNamespace(csrf_token='original-csrf')))
        self.app = SimpleNamespace(_site=None, init_request=self.init, validate_auth=lambda: self.events.append('auth'),
            sync_database=lambda: self.events.append('sync'), run_after_request_hooks=lambda req, res: self.events.append('hooks'),
            log_request=lambda req, res: self.events.append('log'), process_response=lambda res: self.events.append('process'))
        self.actor = lambda: SimpleNamespace(user='original@example.test', person_id='original-person')
        self.Response = lambda body, status, mimetype: SimpleNamespace(body=json.loads(body), status_code=status)
    def init(self, req):
        self.events.append('init'); self.frappe.local.request = req


class Gates(unittest.TestCase):
    def setUp(self): self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup); self.fixed = fixed(Path(self.directory.name)); self.fixed['payload_sha256'] = r._sha(self.fixed['payload'])
    def test_exact_original_bounded_request_passes(self): r._gate(request(self.fixed), self.fixed)
    def test_loopback_route_method_site_and_query_are_fixed(self):
        for key, value in [('remote_addr', '10.0.0.1'), ('method', 'GET'), ('path', '/api/method/login'),
                ('query_string', b'cmd=login'), ('host', 'other.localhost'), ('scheme', 'https')]:
            req = request(self.fixed); setattr(req, key, value)
            with self.subTest(key=key), self.assertRaises(r.Refused): r._gate(req, self.fixed)
    def test_alternate_auth_forwarding_and_referrer_headers_refused(self):
        for key in ('Authorization', 'Forwarded', 'X-Forwarded-For', 'X-Forwarded-Host', 'X-Forwarded-Proto', 'Remote-Addr', 'Origin', 'Referer'):
            req = request(self.fixed); req.headers[key] = 'alternate'
            with self.subTest(key=key), self.assertRaises(r.Refused): r._gate(req, self.fixed)
    def test_csrf_operation_cookie_and_bounded_body_required(self):
        for mutate in [lambda q: q.headers.pop('X-Frappe-CSRF-Token'), lambda q: q.headers.update({'Idempotency-Key': 'replacement'}),
                lambda q: q.cookies.update(sid='Guest'), lambda q: setattr(q, 'content_length', 8193),
                lambda q: setattr(q, 'content_length', None), lambda q: setattr(q, 'mimetype', 'text/plain')]:
            req = request(self.fixed); mutate(req)
            with self.assertRaises(r.Refused): r._gate(req, self.fixed)
    def test_changed_or_duplicate_payload_rejected(self):
        for raw in (json.dumps({**self.fixed['payload'], 'company': 'Other'}).encode(),
                    b'{"company":"Synthetic Company","company":"Synthetic Company"}', b'{"a":NaN}'):
            req = request(self.fixed); req.content_length = len(raw); req.get_data = lambda **kw: raw
            with self.assertRaises(r.Refused): r._gate(req, self.fixed)
    def test_native_authentication_requires_exact_request_user_person_sid_and_csrf(self):
        for mutate in [lambda n,q: setattr(n.frappe.local, 'request', object()), lambda n,q: setattr(n.frappe.local, 'site', 'other'),
                lambda n,q: setattr(n.frappe.session, 'sid', 'other'), lambda n,q: setattr(n.frappe.session.data, 'csrf_token', 'other'),
                lambda n,q: setattr(n, 'actor', lambda: SimpleNamespace(user='Administrator', person_id='original-person')),
                lambda n,q: setattr(n, 'actor', lambda: SimpleNamespace(user='original@example.test', person_id='other'))]:
            native = Native(); req = request(self.fixed); native.frappe.local.request = req; mutate(native, req)
            with self.assertRaises(r.Refused): r._assert_authenticated(native, req, self.fixed)


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.directory = Path(self.temp.name)
        self.directory.chmod(0o700); self.fixed = fixed(self.directory); self.fixed['payload_sha256'] = r._sha(self.fixed['payload'])
        self.native = Native(); self.row = {'status': 'reviewed'}
        self.three = SimpleNamespace(_value=lambda path: {}, _proof=lambda value: {'cases': {r.CASE: self.row}},
            rollback_current_request=self.probe)
        self.boundaries = patch.object(r, 'boundaries', return_value=self.three); self.boundaries.start(); self.addCleanup(self.boundaries.stop)
        self.binding = patch.object(r, '_binding', return_value=self.fixed['binding']); self.binding.start(); self.addCleanup(self.binding.stop)
    def probe(self, path):
        self.native.events.append('real-instance-probe')
        return {'status': 'passed', 'case': r.CASE, 'hook_restored': True, 'canonical_effect_rolled_back': True}
    def test_real_init_auth_probe_sync_hooks_and_response_order(self):
        response = r._handle(request(self.fixed), self.fixed, self.native)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.native.events, ['init', 'auth', 'real-instance-probe', 'sync', 'hooks', 'log', 'process'])
        self.assertEqual(response.body['schema'], r.SCHEMA); self.assertNotEqual(response.body['schema'], 'cipher.api.v1')
        self.assertEqual(r._private_read(self.directory / 'result.secret.json')['result']['canonical_effect_rolled_back'], True)
    def test_original_authority_refusal_rolls_back_without_probe(self):
        self.native.actor = lambda: SimpleNamespace(user='Administrator', person_id='original-person')
        response = r._handle(request(self.fixed), self.fixed, self.native)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.native.events, ['init', 'auth', ('rollback', {'chain': True}), 'hooks', 'log', 'process'])
    def test_probe_failure_rolls_back_native_transaction_and_retains_error(self):
        def fail(path): self.native.events.append('probe-failed'); raise RuntimeError('native failure')
        self.three.rollback_current_request = fail
        response = r._handle(request(self.fixed), self.fixed, self.native)
        self.assertEqual(response.status_code, 500)
        self.assertIn(('rollback', {'chain': True}), self.native.events); self.assertNotIn('sync', self.native.events)
        self.assertEqual(r._private_read(self.directory / 'result.secret.json')['result']['error_type'], 'RuntimeError')
    def test_changed_review_binding_refuses_after_auth_without_probe(self):
        self.binding.stop()
        with patch.object(r, '_binding', return_value={'other': 'binding'}):
            response = r._handle(request(self.fixed), self.fixed, self.native)
        self.assertEqual(response.status_code, 403); self.assertNotIn('real-instance-probe', self.native.events)
    def test_claim_is_exclusive_and_no_second_effect_runs(self):
        r._once(self.directory / 'claim.secret.json', {'already': 'entered'})
        response = r._handle(request(self.fixed), self.fixed, self.native)
        self.assertEqual(response.status_code, 500); self.assertEqual(self.native.events, [])
    def test_after_request_error_is_retained_and_fixture_cannot_pass(self):
        def fail(req, response): raise RuntimeError('native hook failure')
        self.native.app.run_after_request_hooks = fail
        response = r._handle(request(self.fixed), self.fixed, self.native)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.body['reason'], 'native_after_request_hook_failed')
        self.assertEqual(r._private_read(self.directory / 'after-request-error.secret.json')['error_type'], 'RuntimeError')
    def test_cleanup_marker_follows_actual_native_afterresponse_and_destroy(self):
        events = self.native.events
        class Closing:
            def __init__(self, value, callbacks): self.value = value; self.callback = callbacks
            def close(self):
                if hasattr(self.value, 'close'): self.value.close()
                self.callback()
        def actual(inner):
            def run(environ, start):
                value = inner(environ, start)
                return Closing(value, lambda: events.extend(['native-after-response', 'native-destroy']))
            return run
        self.native.Request = SimpleNamespace(application=lambda fn: lambda env, start: (fn(request(self.fixed)), [])[1])
        self.native.ClosingIterator = Closing; self.native.app.after_response_wrapper = actual
        with patch.object(r, 'declaration', return_value=self.fixed), patch.object(r, '_native', return_value=self.native):
            application = r.make_application({'path': 'fixture', 'sha256': 'frozen'}); result = application({}, lambda *a: None)
            self.assertFalse((self.directory / 'closed.secret.json').exists()); result.close()
        self.assertEqual(events[-2:], ['native-after-response', 'native-destroy'])
        self.assertTrue(r._private_read(self.directory / 'closed.secret.json')['native_after_response_and_destroy_returned'])


class FrozenSources(unittest.TestCase):
    def test_sibling_hash_and_actual_pinned_copied_sources(self):
        self.assertEqual(r.boundaries().V2_SHA256, 'f47a94dd3e003984413c1c8bb87fce8ea40c7568853bd085eec1278e8bf49a8a')
        sources = HERE / 'pinned-source'
        for name, digest in r.SOURCE_SHA256.items():
            source = sources / (name + '.py')
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
        app = ast.parse((sources / 'app.py').read_text())
        functions = {node.name: node for node in app.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertIn('init_request', functions); self.assertIn('after_response_wrapper', functions)
        body = ast.get_source_segment((sources / 'app.py').read_text(), functions['application'])
        self.assertLess(body.index('init_request(request)'), body.index('validate_auth()'))
        self.assertIn('db.rollback(chain=True)', body); self.assertIn('sync_database()', body)
        wrapper = ast.get_source_segment((sources / 'app.py').read_text(), functions['after_response_wrapper'])
        self.assertLess(wrapper.index('run_after_response_callbacks,'), wrapper.index('frappe.destroy,'))
    def test_import_is_inert_and_no_identity_global_or_source_patch(self):
        source = (HERE / 'r15_rollback_listener.py').read_text(); tree = ast.parse(source)
        self.assertNotIn('set_user(', source); self.assertNotIn('frappe.init(', source)
        self.assertNotIn('frappe.session =', source); self.assertNotIn('frappe.local.request =', source)
        self.assertNotIn('serve_forever', source); self.assertNotIn('setattr(', source)
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                self.fail('Module import must not execute a call.')
    def test_evidence_is_private_exclusive_and_declaration_is_immutable(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); directory.chmod(0o700)
            f = fixed(directory); f['payload_sha256'] = r._sha(f['payload'])
            reference = r._once(directory / 'declaration.secret.json', f)
            self.assertEqual(r.declaration(reference), f)
            with self.assertRaises(FileExistsError): r._once(reference['path'], f)
            Path(reference['path']).write_text('{}')
            with self.assertRaises(AssertionError): r.declaration(reference)


class Preparation(unittest.TestCase):
    def test_original_canonical_uuid_is_prepared_once_and_bound_to_selected_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); directory.chmod(0o700); path = directory / 'fixture.secret.json'
            row = {'status': 'reviewed', 'run_id': 'run-original', 'proposal_id': 'proposal-original',
                   'reviewed': {'proposal_id': 'proposal-original', 'payload_digest': 'a' * 64},
                   'terminal': {'run': {'authority': {'session_reference': hashlib.sha256(b'original-sid').hexdigest()}}}}
            value = {'company': 'Synthetic Company', 'site': 'synthetic.localhost', 'journal_directory': str(directory),
                     'users': {'author': {'user': 'original@example.test', 'person': 'original-person'}}}
            calls = []
            class Journal:
                def __init__(self, journal): self.directory = journal
                def prepare(self, key, role, method, payload):
                    calls.append((self.directory, key, role, method, deepcopy(payload)))
                    return {'operation_id': 'original-operation', 'payload': {**payload, 'operation_id': 'original-operation'}, 'attempts': []}
            two = SimpleNamespace(_support=lambda: (SimpleNamespace(Journal=Journal),), v1=lambda: SimpleNamespace(SAVE='canonical.'))
            three = SimpleNamespace(v2=lambda: two, _value=lambda p: value, _proof=lambda v: {'cases': {r.CASE: row}})
            with patch.object(r, 'boundaries', return_value=three):
                reference = r.prepare_declaration(path, 18991)
                with self.assertRaises(FileExistsError): r.prepare_declaration(path, 18991)
            declared = r.declaration(reference)
            self.assertEqual(declared['operation_id'], 'original-operation')
            self.assertEqual(declared['manifest_path'], str(path))
            self.assertEqual(declared['payload']['payload_digest'], 'a' * 64)
            self.assertEqual(calls[0], (str(directory), r.INTENT_KEY, 'author', 'canonical.save_draft', {'company': 'Synthetic Company', **row['reviewed']}))
            self.assertEqual(declared['binding']['session_reference'], row['terminal']['run']['authority']['session_reference'])
    def test_invalid_port_is_refused_before_collaborator_access(self):
        with patch.object(r, 'boundaries', side_effect=AssertionError('must be inert')):
            for port in (True, 80, 65536, '18991'):
                with self.assertRaises(ValueError): r.prepare_declaration('/unused', port)


if __name__ == '__main__': unittest.main()
