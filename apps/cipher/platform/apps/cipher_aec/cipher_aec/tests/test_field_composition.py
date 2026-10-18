"""FLD02/03 integration checks against the composed custom-app source.

The shared receipt/history dispatchers and owned authorization callbacks are real.
Frappe identity, persistence and request objects are explicit host doubles. Route
tests retain actual transport/wrappers and spy only on the downstream service.
This does not qualify native transactions, HTTP middleware, CSRF or concurrency.
"""
from contextlib import contextmanager
from copy import deepcopy
import importlib
import importlib.util
import inspect
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cipher_aec
from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_field import add_person, create as create_field, uid
from cipher_aec.tests.test_field_offline import fixture as offline_fixture, stage
from cipher_aec.tests.quality_safety_fixtures import fixtures as quality_fixture
from cipher_aec.tests.test_quality_safety import create as create_quality

ROOT = Path(cipher_aec.__file__).resolve().parent


def load_source(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def shared_dispatchers(state):
    """Load unmodified dispatchers with only missing native context boundaries."""
    context = sys.modules['cipher_aec.governance.context']
    additions = {
        'assert_synthetic_site': lambda: None,
        'require_company': lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError('Project receipt must not use Company admission')),
        'require_effects_enabled': lambda: None,
        'session_authority_reference': lambda *args: 'host-session-reference',
        'require_session_authority': lambda *args, **kwargs: None,
    }
    patches = [patch.object(context, key, value, create=True)
               for key, value in additions.items() if not hasattr(context, key)]
    for item in patches:
        item.start()
    names = ['cipher_aec.governance._field_composition_commands',
             'cipher_aec.governance._field_composition_history']
    old = {name: sys.modules.get(name) for name in names}
    try:
        commands = load_source(names[0], 'governance/commands.py')
        history = load_source(names[1], 'governance/history_access.py')
        yield commands, history
    finally:
        for name, original in old.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
        for item in reversed(patches):
            item.stop()


@contextmanager
def stored_receipt(state, command, operation, result):
    """One actual shared receipt read; reject a different Person namespace."""
    clean = {key: deepcopy(value) for key, value in result.items() if key != 'operation'}
    owner = state.actor.person_id
    name = digest({'person': owner, 'operation_id': operation})
    row = SimpleNamespace(company='C', project='P', scope_type='Project', command=command,
                          result_json=canonical_json(clean), result_hash=digest(clean))
    original_get_value = getattr(sys.modules['frappe'].db, 'get_value', None)
    def get_value(doctype, requested, fields, as_dict=False):
        if doctype != 'Cipher Command Receipt':
            if original_get_value is not None:
                return original_get_value(doctype, requested, fields, as_dict=as_dict)
            raise AssertionError('Unexpected native receipt lookup: ' + doctype)
        return row if requested == name else None
    with patch.object(sys.modules['frappe'].db, 'get_value', get_value, create=True):
        yield clean, row


class ComposedReceiptAndHistoryTests(unittest.TestCase):
    def test_offline_shared_operation_calls_real_callback_and_preserves_original_summary(self):
        with offline_fixture() as (state, _, _, _, repo, _, offline):
            _, captured, staged = stage(state, offline)
            operation = uid()
            with shared_dispatchers(state) as (commands, _), stored_receipt(
                    state, 'offline.field.stage.v1', operation, staged) as (clean, _):
                with patch.object(offline, 'authorize_receipt', wraps=offline.authorize_receipt) as callback:
                    actual = commands.read_operation('C', 'P', operation)
                callback.assert_called_once_with(state.actor, 'C', 'P', clean, lock=True)
                self.assertEqual(actual['capture'], staged['capture'])
                self.assertTrue(actual['operation']['replayed'])
                self.assertNotIn('envelope', actual)
                self.assertEqual(repo.raw('capture', digest({'person': state.actor.person_id,
                    'capture_id': captured['capture_id']}))['envelope'], captured)

    def test_offline_shared_read_rechecks_current_field_read_before_private_storage(self):
        with offline_fixture() as (state, _, _, _, repo, _, offline):
            _, _, staged = stage(state, offline)
            operation = uid()
            state.duties[state.actor.person_id] = {'project.read', 'field.write', 'document.read'}
            with shared_dispatchers(state) as (commands, _), stored_receipt(
                    state, 'offline.field.stage.v1', operation, staged), patch.object(
                    repo, 'raw', side_effect=AssertionError('Denied metadata must not be read')) as raw:
                with self.assertRaises(DomainError) as caught:
                    commands.read_operation('C', 'P', operation)
                self.assertEqual(caught.exception.code, 'capability_denied')
                raw.assert_not_called()

    def test_field_shared_receipt_keeps_existing_exact_source_callback(self):
        with offline_fixture() as (state, _, _, field, _, _, offline):
            operation = uid()
            original = create_field(state, field, operation=operation)
            with shared_dispatchers(state) as (commands, _), stored_receipt(
                    state, 'field.daily.create.v1', operation, original) as (clean, _):
                with patch.object(field, 'authorize_receipt', wraps=field.authorize_receipt) as callback, patch.object(
                        offline, 'authorize_receipt', side_effect=AssertionError('Wrong prefix dispatch')):
                    result = commands.read_operation('C', 'P', operation)
                callback.assert_called_once_with(state.actor, 'C', 'P', clean, lock=True)
                self.assertEqual(result['revision'], original['revision'])
                source = original['quantities'][0]['definition']['sources'][0]
                state.rights[source['document_id']] = 'read_denied'
                with self.assertRaises(DomainError):
                    commands.read_operation('C', 'P', operation)

    def test_device_history_requires_current_owner_scope_and_field_read(self):
        with offline_fixture() as (state, _, _, _, _, _, offline):
            device, _, _ = stage(state, offline)
            event = SimpleNamespace(subject_type='Cipher Field Offline Device',
                subject_id=device['device']['device_id'], details_json='{}', event='offline.field.device.revoked')
            with shared_dispatchers(state) as (_, history):
                with patch.object(offline, 'authorize_history_subject', wraps=offline.authorize_history_subject) as callback:
                    self.assertTrue(history.readable(event, state.actor, 'C', 'P'))
                callback.assert_called_once_with(state.actor, 'C', 'P', event.subject_type, event.subject_id)
                self.assertFalse(history.readable(event, state.actor, 'C', None))
                owner = state.actor
                state.actor = add_person(state, 'other-device-reader')
                self.assertFalse(history.readable(event, state.actor, 'C', 'P'))
                state.actor = owner
                state.duties[owner.person_id] = {'project.read', 'document.read'}
                self.assertFalse(history.readable(event, owner, 'C', 'P'))
                event.subject_type = 'Cipher Field Offline Capture'
                self.assertFalse(history.readable(event, owner, 'C', 'P'))

    def test_incident_shared_receipt_enforces_restricted_duty_and_command_family(self):
        with quality_fixture() as (state, _, repo, _, quality, _):
            # The reused host fixture cleans up this lazy owned module too.
            # Materialize its real source so teardown has an actual module.
            importlib.import_module('cipher_aec.quality_safety.evidence')
            operation = uid()
            original = create_quality(state, quality, 'incident', operation=operation)
            with shared_dispatchers(state) as (commands, _), stored_receipt(
                    state, 'quality_safety.incident.create.v1', operation, original) as (clean, row):
                with patch.object(quality, 'authorize_command_receipt', wraps=quality.authorize_command_receipt) as callback:
                    result = commands.read_operation('C', 'P', operation)
                callback.assert_called_once_with(state.actor, row.command, 'C', 'P', clean, lock=True)
                self.assertEqual(result['revision'], original['revision'])
                self.assertIsNone(result['history_id'])
                row.command = 'quality_safety.record.create.v1'
                with self.assertRaises(DomainError) as caught:
                    commands.read_operation('C', 'P', operation)
                self.assertEqual(caught.exception.code, 'quality_safety_receipt_integrity')
                row.command = 'quality_safety.incident.create.v1'
                state.duties[state.actor.person_id] = {'project.read', 'document.read', 'quality.read'}
                with patch.object(repo, 'raw', side_effect=AssertionError('Restricted content must stay unread')) as raw:
                    with self.assertRaises(DomainError) as denied:
                        commands.read_operation('C', 'P', operation)
                    self.assertEqual(denied.exception.code, 'capability_denied')
                    raw.assert_not_called()


OWNED = {
    'field_offline': ('register_device', 'revoke_device', 'stage_capture', 'get_capture',
                      'inspect_capture', 'apply_capture', 'discard_capture', 'resolve_capture'),
    'quality_safety': ('upload_evidence', 'create_record', 'revise_record', 'transition',
                       'get_record', 'list_records'),
}
GET_ROUTES = {'get_capture', 'inspect_capture', 'get_record', 'list_records'}


@contextmanager
def transport_routes(owned):
    """Real wrappers/transport; emulate Frappe filtering original raw fields."""
    package_name = 'cipher_aec.' + owned
    package = importlib.import_module(package_name)
    api_package = importlib.import_module('cipher_aec.api')
    service = ModuleType(package_name + '.service')
    calls = {name: Mock(name=owned + '.' + name, return_value={'accepted': name}) for name in OWNED[owned]}
    service.__dict__.update(calls)
    evidence = ModuleType(package_name + '.evidence')
    evidence.upload_evidence = calls.get('upload_evidence')
    headers = {}
    frappe = ModuleType('frappe')
    frappe.local = SimpleNamespace(request=SimpleNamespace(method='GET'), response={}, response_headers={})
    frappe.form_dict = {}
    frappe.db = SimpleNamespace(rollback=Mock())
    frappe.get_request_header = lambda key: headers.get(key)
    frappe.whitelist = lambda **kwargs: lambda function: function
    frappe.log_error = Mock()
    frappe.QueryDeadlockError = type('HostDeadlock', (Exception,), {})
    frappe.QueryTimeoutError = type('HostTimeout', (Exception,), {})
    context = ModuleType('cipher_aec.governance.context')
    context.assert_synthetic_site = lambda: None
    context.current_actor = lambda: SimpleNamespace(user='host@example.invalid', person_id='host-person')
    mocked = {'frappe': frappe, 'cipher_aec.governance.context': context,
              package_name + '.service': service, package_name + '.evidence': evidence}
    with patch.dict(sys.modules, mocked), patch.object(package, 'service', service, create=True), patch.object(
            package, 'evidence', evidence, create=True):
        transport = load_source('cipher_aec.api.transport', 'api/transport.py')
        with patch.object(api_package, 'transport', transport, create=True):
            api = load_source(package_name + '.api', owned + '/api.py')
            with patch.object(package, 'api', api, create=True):
                yield api, frappe, headers, calls


def route_values(function):
    values = {'company': 'C', 'project': 'P', 'operation_id': uid(), 'device_id': uid(),
        'capture_id': uid(), 'label': 'Host device', 'expected_version': 'a' * 64,
        'reason': 'Explicit host action', 'envelope': {}, 'replacement_envelope': {},
        'title': 'Evidence', 'filename': 'evidence.pdf', 'content_base64': 'cGRm',
        'byte_length': 3, 'sha256': 'b' * 64, 'rights_basis': 'owned',
        'permission_evidence': 'Host source permission', 'family': 'record',
        'category': 'inspection', 'definition': {}, 'evidence': [], 'record_id': uid(),
        'amendment_reason': '', 'action': 'submit', 'comment': 'Documentary action',
        'closure': [], 'kind': 'record', 'parent_id': None, 'limit': 25,
        'cursor': None, 'count_mode': 'none'}
    result = {key: deepcopy(values[key]) for key in inspect.signature(function).parameters}
    if function.__name__ == 'apply_capture':
        result['operation_id'] = result['capture_id']
    return result


def call_route(api, frappe, headers, route, *, extra=None, key='matching', cmd='matching'):
    function = getattr(api, route)
    values = route_values(function)
    frappe.local.request.method = 'GET' if route in GET_ROUTES else 'POST'
    frappe.local.response.clear()
    headers.clear()
    if 'operation_id' in values and key != 'missing':
        headers['Idempotency-Key'] = values['operation_id'] if key == 'matching' else uid()
    frappe.form_dict = deepcopy(values)
    if cmd is not None:
        frappe.form_dict['cmd'] = function.__module__ + '.' + route if cmd == 'matching' else cmd
    frappe.form_dict.update(extra or {})
    # The original request has extras; Frappe's invoked kwargs do not.
    return function(**values), values


class ComposedOwnedTransportTests(unittest.TestCase):
    def test_exact_requests_keep_real_transport_and_original_operation_identity(self):
        for owned, routes in OWNED.items():
            with transport_routes(owned) as (api, frappe, headers, calls):
                for route in routes:
                    with self.subTest(owned=owned, route=route):
                        body, values = call_route(api, frappe, headers, route)
                        self.assertNotIn('error', body)
                        self.assertEqual(body['data'], {'accepted': route})
                        self.assertEqual(frappe.local.response.get('http_status_code', 200), 200)
                        calls[route].assert_called_once_with(*values.values())
                        if route == 'apply_capture':
                            self.assertEqual(values['capture_id'], values['operation_id'])

    def test_all_owned_routes_reject_original_unknown_fields_before_service(self):
        for owned, routes in OWNED.items():
            with transport_routes(owned) as (api, frappe, headers, calls):
                for route in routes:
                    with self.subTest(owned=owned, route=route):
                        body, _ = call_route(api, frappe, headers, route, extra={'unexpected': True})
                        self.assertIn('error', body)
                        self.assertEqual(frappe.local.response['http_status_code'], 422)
                        calls[route].assert_not_called()

    def test_all_owned_routes_reject_original_different_cmd_before_service(self):
        for owned, routes in OWNED.items():
            with transport_routes(owned) as (api, frappe, headers, calls):
                for route in routes:
                    with self.subTest(owned=owned, route=route):
                        body, _ = call_route(api, frappe, headers, route,
                            cmd='cipher_aec.projects.api.create_project')
                        self.assertIn('error', body)
                        self.assertEqual(frappe.local.response['http_status_code'], 422)
                        calls[route].assert_not_called()

    def test_get_routes_reject_original_authority_fields_before_service(self):
        for owned, routes in OWNED.items():
            with transport_routes(owned) as (api, frappe, headers, calls):
                for route in set(routes) & GET_ROUTES:
                    for field in ('actor', 'person_id', 'ignore_permissions'):
                        with self.subTest(owned=owned, route=route, field=field):
                            body, _ = call_route(api, frappe, headers, route, extra={field: 'forged'})
                            self.assertIn('error', body)
                            self.assertEqual(frappe.local.response['http_status_code'], 422)
                            calls[route].assert_not_called()

    def test_post_routes_preserve_missing_key_and_conflicting_body_key_refusals(self):
        for owned, routes in OWNED.items():
            with transport_routes(owned) as (api, frappe, headers, calls):
                for route in set(routes) - GET_ROUTES:
                    for mode, status, code in (('missing', 428, 'idempotency_key_required'),
                                              ('different', 409, 'operation_conflict')):
                        with self.subTest(owned=owned, route=route, key=mode):
                            body, _ = call_route(api, frappe, headers, route, key=mode)
                            self.assertEqual(body['error']['code'], code)
                            self.assertEqual(frappe.local.response['http_status_code'], status)
                            calls[route].assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
