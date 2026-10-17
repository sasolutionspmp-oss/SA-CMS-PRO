"""Opt-in, one-request loopback native fixture listener. Import is inert.

This is a separately labeled rollback fixture, never a Cipher API route. Root
owns launch/transport. No app source, config, hooks, class or global is patched.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

V3_SHA256 = '57b93171fff3ca44695de772b540bfc456c4ec34a95e34dcaef8aff812492d21'
SOURCE_SHA256 = {
    'app': '1e910e76bcbf596dc708dbd4d8f682f6a6e37368971afcca5f4512efeaa845f9',
    'auth': '3a618569ec1f273e956d842002e182281345f6b96384368458edfba63106631f',
    'sessions': '397aaa146652cc645cd8f1968400ea7c5aa56a784a3096d6b5374f37686795c2',
}
SCHEMA = 'cipher.fixture.native-rollback.http.v1'
ROUTE = '/__cipher_r15_fixture__/rollback'
CASE = 'rollback-r15'
INTENT_KEY = 'v3-instance-rollback'


def _stamp(): return datetime.now(timezone.utc).isoformat()
def _sha(value): return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def boundaries():
    target = Path(__file__).resolve().parent.parent / 'native-execution-v3/r15_boundaries.py'
    if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != V3_SHA256:
        raise AssertionError('Keep the exact frozen v3 sibling collaborator.')
    spec = importlib.util.spec_from_file_location('cipher_r15_frozen_boundaries', target)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def _native():
    import frappe
    import frappe.app as app
    import frappe.auth as auth
    import frappe.sessions as sessions
    from cipher_aec.governance.context import current_actor
    from werkzeug.wrappers import Request, Response
    from werkzeug.wsgi import ClosingIterator
    modules = {'app': app, 'auth': auth, 'sessions': sessions}
    sources = {}
    for name, module in modules.items():
        target = Path(module.__file__)
        if target.suffix != '.py' or hashlib.sha256(target.read_bytes()).hexdigest() != SOURCE_SHA256[name]:
            raise AssertionError('Pinned installed Frappe lifecycle source changed: ' + name)
        sources[name] = {'path': str(target.resolve()), 'sha256': SOURCE_SHA256[name]}
    if frappe.__version__ != '16.52.0' or app.validate_auth is not auth.validate_auth:
        raise AssertionError('Require the actual pinned Frappe lifecycle and auth callable.')
    return SimpleNamespace(frappe=frappe, app=app, actor=current_actor, Request=Request,
                           Response=Response, ClosingIterator=ClosingIterator, sources=sources)


def _private_read(path):
    target = Path(path)
    if not target.is_file() or target.is_symlink() or target.stat().st_mode & 0o077:
        raise ValueError('Require a retained regular private file.')
    return json.loads(target.read_text())


def _once(path, value):
    target = Path(path)
    if target.parent.is_symlink() or not target.parent.is_dir() or target.parent.stat().st_mode & 0o077:
        raise ValueError('Keep one-shot fixture evidence in a private regular directory.')
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    descriptor = os.open(target.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
    return {'path': str(target.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}


def _binding(value, row):
    return {'company': value['company'], 'site': value['site'], 'user': value['users']['author']['user'],
            'person': value['users']['author']['person'], 'run_id': row['run_id'],
            'proposal_id': row['proposal_id'], 'reviewed_sha256': _sha(row['reviewed']),
            'session_reference': row['terminal']['run']['authority']['session_reference']}


def prepare_declaration(manifest_path, port):
    """Fsync the original canonical-probe UUID before root launches transport."""
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Root must select a literal unprivileged isolated loopback port.')
    three = boundaries(); two = three.v2(); value = three._value(manifest_path)
    row = three._proof(value)['cases'][CASE]
    if row['status'] != 'reviewed': raise RuntimeError('Prepare this distinct fresh reviewed rollback case first.')
    journal = two._support()[0].Journal(value['journal_directory'])
    intent = journal.prepare(INTENT_KEY, 'author', two.v1().SAVE + 'save_draft', {'company': value['company'], **row['reviewed']})
    if intent['attempts'] or intent.get('uncertain_transport'):
        raise RuntimeError('Preserve the attempted native-probe UUID; do not relaunch or retry it.')
    directory = Path(manifest_path).resolve().parent / 'r15-rollback-listener'
    directory.mkdir(mode=0o700)  # Existing declaration is never reset.
    declaration = {'schema': SCHEMA, 'label': 'separate-native-fixture-listener', 'prepared_at': _stamp(),
        'manifest_path': str(Path(manifest_path).resolve()), 'bind': '127.0.0.1', 'port': port,
        'method': 'POST', 'path': ROUTE, 'binding': _binding(value, row),
        'operation_id': intent['operation_id'], 'payload': deepcopy(intent['payload']),
        'payload_sha256': _sha(intent['payload']), 'lifecycle_source_sha256': SOURCE_SHA256,
        'v3_sha256': V3_SHA256, 'evidence_directory': str(directory)}
    return _once(directory / 'declaration.secret.json', declaration)


def declaration(reference):
    if set(reference) != {'path', 'sha256'}:
        raise ValueError('Use the exact frozen declaration reference.')
    target = Path(reference['path']); value = _private_read(target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != reference['sha256']:
        raise AssertionError('The fixed listener declaration changed.')
    if (value['schema'] != SCHEMA or value['bind'] != '127.0.0.1' or value['method'] != 'POST' or value['path'] != ROUTE
            or value['lifecycle_source_sha256'] != SOURCE_SHA256 or value['v3_sha256'] != V3_SHA256
            or _sha(value['payload']) != value['payload_sha256'] or value['payload']['operation_id'] != value['operation_id']
            or target.resolve().parent != Path(value['evidence_directory']).resolve()
            or target.resolve().parent.parent != Path(value['manifest_path']).resolve().parent):
        raise AssertionError('The exact isolated listener declaration was not retained.')
    return value


class Refused(RuntimeError): pass


def _gate(request, fixed):
    """Closed one-route body/header gate, before native authentication/effects."""
    if (request.remote_addr != '127.0.0.1' or request.method != 'POST' or request.path != ROUTE or request.query_string
            or request.host != fixed['binding']['site'] or request.scheme != 'http'):
        raise Refused('fixed_loopback_request_required')
    headers = request.headers
    if any(headers.get(name) is not None for name in ('Authorization', 'Forwarded', 'X-Forwarded-For',
            'X-Forwarded-Host', 'X-Forwarded-Proto', 'Remote-Addr', 'Origin', 'Referer')):
        raise Refused('alternate_authority_headers_refused')
    if headers.get('X-Frappe-Site-Name') not in (None, fixed['binding']['site']):
        raise Refused('alternate_site_refused')
    if not headers.get('X-Frappe-CSRF-Token') or headers.get('Idempotency-Key') != fixed['operation_id']:
        raise Refused('original_csrf_and_operation_required')
    if request.mimetype != 'application/json' or request.content_length is None or not 1 <= request.content_length <= 8192:
        raise Refused('bounded_exact_json_required')
    raw = request.get_data(cache=True)
    if len(raw) != request.content_length or len(raw) > 8192:
        raise Refused('bounded_exact_json_required')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise Refused('duplicate_json_key_refused')
            result[key] = value
        return result
    try: payload = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda value: (_ for _ in ()).throw(Refused('nonfinite_json_refused')))
    except (ValueError, UnicodeError): raise Refused('exact_json_required') from None
    if payload != fixed['payload'] or _sha(payload) != fixed['payload_sha256']:
        raise Refused('fixed_reviewed_payload_required')
    if not request.cookies.get('sid') or request.cookies['sid'] == 'Guest':
        raise Refused('original_cookie_required')


def _assert_authenticated(native, request, fixed):
    frappe = native.frappe; actor = native.actor(); binding = fixed['binding']
    sid = getattr(frappe.session, 'sid', None)
    if (frappe.local.request is not request or frappe.local.site != binding['site']
            or actor.user != binding['user'] or actor.person_id != binding['person']
            or not sid or sid == 'Guest' or sid != request.cookies['sid']
            or hashlib.sha256(sid.encode()).hexdigest() != binding['session_reference']):
        raise Refused('actual_original_authenticated_request_required')
    # Require the actual native CSRF equality too; no allowed-referrer shortcut.
    if request.headers['X-Frappe-CSRF-Token'] != frappe.session.data.csrf_token:
        raise Refused('actual_original_csrf_required')


def _handle(request, fixed, native):
    directory = Path(fixed['evidence_directory']); response = None; result = None; entered = False
    try:
        _gate(request, fixed)
        _once(directory / 'claim.secret.json', {'at': _stamp(), 'operation_id': fixed['operation_id']})
        entered = True
        native.app.init_request(request)
        native.app.validate_auth()
        _assert_authenticated(native, request, fixed)
        three = boundaries(); value = three._value(fixed['manifest_path']); row = three._proof(value)['cases'][CASE]
        if _binding(value, row) != fixed['binding'] or row['status'] != 'reviewed':
            raise Refused('fixed_case_binding_changed')
        result = three.rollback_current_request(fixed['manifest_path'])
        if result != {'status': 'passed', 'case': CASE, 'hook_restored': True, 'canonical_effect_rolled_back': True}:
            raise AssertionError('Require the exact independently verified actual rollback result.')
        native.app.sync_database()
        response = native.Response(json.dumps({'schema': SCHEMA, 'status': 'passed', 'operation_id': fixed['operation_id'],
                                              'result': result}), status=200, mimetype='application/json')
    except BaseException as failure:
        if entered and (db := getattr(native.frappe.local, 'db', None)): db.rollback(chain=True)
        result = {'status': 'refused' if isinstance(failure, Refused) else 'failed', 'error_type': type(failure).__name__}
        if isinstance(failure, Refused): result['reason'] = str(failure)
        response = native.Response(json.dumps({'schema': SCHEMA, **result, 'operation_id': fixed['operation_id']}),
                                   status=403 if isinstance(failure, Refused) else 500, mimetype='application/json')
    finally:
        if entered:
            try: native.app.run_after_request_hooks(request, response)
            except Exception as failure:
                _once(directory / 'after-request-error.secret.json', {'error_type': type(failure).__name__, 'at': _stamp()})
                result = {'status': 'failed', 'error_type': type(failure).__name__, 'reason': 'native_after_request_hook_failed'}
                response = native.Response(json.dumps({'schema': SCHEMA, **result, 'operation_id': fixed['operation_id']}),
                                           status=500, mimetype='application/json')
    if entered:
        native.app.log_request(request, response)
        native.app.process_response(response)
    _once(directory / 'result.secret.json', {'at': _stamp(), 'http_status': response.status_code,
        'operation_id': fixed['operation_id'], 'result': result, 'native_request_entered': entered})
    return response


def make_application(reference):
    """Actual pinned init/auth/cleanup; no route registration or app patch."""
    fixed = declaration(reference); native = _native()
    if native.app._site not in (None, fixed['binding']['site']):
        raise AssertionError('The existing native site selection disagrees with the fixed site.')
    inner = native.Request.application(lambda request: _handle(request, fixed, native))
    actual = native.app.after_response_wrapper(inner)
    def application(environ, start_response):
        def closed():
            _once(Path(fixed['evidence_directory']) / 'closed.secret.json', {'at': _stamp(),
                'operation_id': fixed['operation_id'], 'native_after_response_and_destroy_returned': True})
        # ClosingIterator closes actual first: native callbacks then destroy,
        # then our marker. The sender observes only after this marker exists.
        return native.ClosingIterator(actual(environ, start_response), closed)
    return application


def serve_once(reference):
    """ROOT ONLY: one loopback request, no daemon/reloader or app mutation."""
    from wsgiref.simple_server import make_server, WSGIRequestHandler
    fixed = declaration(reference); application = make_application(reference)
    class Quiet(WSGIRequestHandler):
        def log_message(self, *args): pass  # No cookie/body logging.
    with make_server('127.0.0.1', fixed['port'], application, handler_class=Quiet) as server:
        server.timeout = 45
        _once(Path(fixed['evidence_directory']) / 'ready.secret.json', {'at': _stamp(), 'port': fixed['port'],
            'bind': '127.0.0.1', 'declaration': reference})
        server.handle_request()
    if not (Path(fixed['evidence_directory']) / 'closed.secret.json').exists():
        raise RuntimeError('No completed one-shot native fixture request; retain the original UUID/declaration.')
    return _private_read(Path(fixed['evidence_directory']) / 'closed.secret.json')


def send_once(reference, authenticated_client):
    """ROOT ONLY: original authenticated v2 client, explicit loopback HTTP."""
    from cipher_aec.tests import test_ricky_company_http as http
    fixed = declaration(reference); three = boundaries(); two = three.v2(); rpc = authenticated_client
    if (Path(rpc.path).resolve() != Path(fixed['manifest_path']).resolve() or rpc.role != 'author'
            or rpc.host != fixed['binding']['site'] or not rpc.csrf):
        raise ValueError('Use the already authenticated original-author client for this exact manifest/site.')
    ready = _private_read(Path(fixed['evidence_directory']) / 'ready.secret.json')
    if ready['declaration'] != reference: raise AssertionError('The exact declared listener is not ready.')
    directory = Path(fixed['evidence_directory'])
    _once(directory / 'send.secret.json', {'at': _stamp(), 'operation_id': fixed['operation_id']})
    proxy = SimpleNamespace(path=rpc.path, value=rpc.value, work=rpc.work, role=rpc.role, opener=rpc.opener,
        host=rpc.host, origin='http://127.0.0.1:' + str(fixed['port']), last_wire_observation=None)
    def wire(*args, **kwargs):
        result = http._HTTP._wire(proxy, *args, **kwargs)
        deadline = time.monotonic() + 10
        while not (directory / 'closed.secret.json').exists():
            if time.monotonic() >= deadline: raise RuntimeError('Native fixture cleanup completion is uncertain; never retry.')
            time.sleep(0.02)
        closed = _private_read(directory / 'closed.secret.json')
        if closed['operation_id'] != fixed['operation_id'] or closed['native_after_response_and_destroy_returned'] is not True:
            raise AssertionError('The exact native cleanup completion marker changed.')
        return result
    try:
        status, envelope, seconds = two.observed_wire(proxy, wire, 'POST', ROUTE, fixed['payload'],
            csrf=rpc.csrf, operation=fixed['operation_id'])
        expected = {'schema': SCHEMA, 'status': 'passed', 'operation_id': fixed['operation_id'],
                    'result': {'status': 'passed', 'case': CASE, 'hook_restored': True, 'canonical_effect_rolled_back': True}}
        if status != 200 or envelope != expected: raise AssertionError('The separate native fixture HTTP rollback did not pass.')
        # The canonical journal already records rolled_back, not HTTP success.
        # Never invent a canonical API receipt for this fixture response.
        _once(directory / 'http-evidence.secret.json', {'status': status, 'envelope': envelope, 'seconds': seconds,
            'wire': proxy.last_wire_observation, 'closed': _private_read(directory / 'closed.secret.json')})
        return {'status': 'passed', 'label': 'separate-native-fixture-listener', 'operation_id': fixed['operation_id']}
    except BaseException as failure:
        journal = two._support()[0].Journal(rpc.work)
        intent = next(item for item in journal.rows if item['key'] == INTENT_KEY)
        journal.uncertain(intent, failure, proxy.last_wire_observation)
        raise
