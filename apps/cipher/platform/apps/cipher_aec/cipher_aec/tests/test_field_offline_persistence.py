"""FLD02 actual repository/controller boundaries with explicit host doubles.

The shared fixture supplies metadata/session/rights/transaction objects and a
no-op trusted-write guard. These tests prove private write-plan/operation and
serialization behavior, not native Frappe trust, SQL locking or restart durability.
"""
import ast
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

from cipher_aec.api.contracts import canonical_json, digest, utc_timestamp
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_field import add_source, daily, quantity, uid
from cipher_aec.tests.test_field_offline import apply, device, envelope, fixture, stage

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / 'field_offline/schemas/api-v1.schema.json').read_text())
ROUTES = json.loads((ROOT / 'field_offline/route-contracts.json').read_text())


def validate(name, value):
    Draft202012Validator({'$ref': '#/$defs/' + name, '$defs': SCHEMA['$defs']}, format_checker=FormatChecker()).validate(value)


@contextmanager
def admitted(repo, state, action):
    """Test-only privileged operation; grants neither a native write plan nor ACL."""
    token = repo._operation.set({'action': action, 'person': state.actor.person_id, 'company': 'C', 'project': 'P'})
    try:
        yield
    finally:
        repo._operation.reset(token)


def capture_key(state, captured):
    return digest({'person': state.actor.person_id, 'capture_id': captured['capture_id']})


class OfflinePersistenceBoundaryTests(unittest.TestCase):
    def test_direct_native_insert_and_trusted_writer_alone_lack_private_write_plan(self):
        with fixture() as (state, _, _, _, repo, records, service):
            registered = device(state, service)
            original_id = registered['device']['device_id']
            value = repo.raw('device', original_id)
            identifier = uid()
            clone = {**value, 'id': identifier, 'device_id': identifier}
            fields = {**deepcopy(state.native[repo.KINDS['device'], original_id]), 'name': identifier,
                'device_id': identifier, 'record_digest': digest(clone), 'data_json': canonical_json(clone)}
            before = deepcopy(state.native)
            for trusted in (False, True):
                with self.subTest(trusted_writer=trusted):
                    doc = state.FakeDocument(fields)
                    if trusted:
                        with sys.modules['cipher_aec.governance.context'].trusted_write(), self.assertRaises(DomainError) as error:
                            doc.insert(ignore_permissions=True)
                    else:
                        with self.assertRaises(DomainError) as error:
                            doc.insert(ignore_permissions=True)
                    self.assertEqual(error.exception.code, 'field_offline_command_required')
                    self.assertEqual(state.native, before)
            self.assertIsNone(repo._plan.get())
            self.assertIsNone(repo._operation.get())

    def test_repository_exact_write_plan_without_private_operation_still_cannot_insert(self):
        with fixture() as (state, _, _, _, repo, _, service):
            registered = device(state, service)
            original = repo.raw('device', registered['device']['device_id'])
            identifier = uid()
            clone = {**original, 'id': identifier, 'device_id': identifier}
            before = deepcopy(state.native)
            with self.assertRaises(DomainError) as error:
                repo.write('device', clone)
            self.assertEqual(error.exception.code, 'field_offline_command_required')
            self.assertEqual(state.native, before)
            self.assertIsNone(repo._plan.get())
            self.assertIsNone(repo._operation.get())

    def test_existing_native_update_also_refuses_without_the_exact_private_plan(self):
        with fixture() as (state, _, _, _, repo, _, service):
            registered = device(state, service)
            name = registered['device']['device_id']
            before = deepcopy(state.native)
            doc = state.get_doc(repo.KINDS['device'], name)
            value = json.loads(doc.data_json)
            value.update(status='revoked', revoked_at=utc_timestamp(), revocation_reason='Direct native bypass attempt')
            doc.update({'status': 'revoked', 'data_json': canonical_json(value), 'record_digest': digest(value)})
            with admitted(repo, state, 'revoke'), self.assertRaises(DomainError) as error:
                doc.save(ignore_permissions=True)
            self.assertEqual(error.exception.code, 'field_offline_command_required')
            self.assertEqual(state.native, before)

    def test_privileged_repository_update_cannot_replace_immutable_envelope_or_identity(self):
        with fixture() as (state, _, _, _, repo, _, service):
            _, captured, _ = stage(state, service)
            old = repo.raw('capture', capture_key(state, captured))
            before = deepcopy(state.native)
            changed_envelope = deepcopy(old)
            changed_envelope['envelope']['command']['definition']['activities'] = ['Replacement observation under the original capture UUID']
            changed_envelope['envelope_digest'] = digest(changed_envelope['envelope'])
            from cipher_aec.field_offline.spec import business_request
            changed_envelope['business_request_hash'] = business_request(changed_envelope['envelope'])[2]
            changes = [changed_envelope]
            for key, item in (('author_user', 'different-author@example.invalid'), ('created_at', '2026-10-18T00:00:00Z'),
                              ('business_command', 'field.ticket.create.v1'), ('actor_user', 'different-capture@example.invalid'),
                              ('device_id', uid()), ('capture_id', uid()), ('company', 'Other'), ('project', 'Other')):
                changes.append({**deepcopy(old), key: item})
            for changed in changes:
                changed['revision_number'] = old['revision_number'] + 1
                with self.subTest(changed=changed), admitted(repo, state, 'discard'), self.assertRaises(DomainError):
                    repo.write('capture', changed, old=old)
                self.assertEqual(state.native, before)
                self.assertIsNone(repo._plan.get())

    def test_device_registration_identity_and_label_stay_immutable_during_revoke(self):
        with fixture() as (state, _, _, _, repo, _, service):
            registered = device(state, service)
            old = repo.raw('device', registered['device']['device_id'])
            before = deepcopy(state.native)
            for key in ('label', 'registered_user', 'author_user'):
                changed = {**deepcopy(old), 'status': 'revoked', 'revoked_at': utc_timestamp(),
                           'revocation_reason': 'Explicit revocation', key: 'Replacement identity metadata'}
                with self.subTest(field=key), admitted(repo, state, 'revoke'), self.assertRaises(DomainError):
                    repo.write('device', changed, old=old)
                self.assertEqual(state.native, before)
            service.revoke_device('C', 'P', uid(), old['device_id'], digest(old), 'Legitimate device revocation')
            self.assertEqual(repo.raw('device', old['id'])['label'], old['label'])

    def test_native_hash_and_every_index_drift_are_refused_by_actual_repository_reads(self):
        with fixture() as (state, _, _, _, repo, _, service):
            _, captured, _ = stage(state, service)
            key = (repo.KINDS['capture'], capture_key(state, captured))
            original = deepcopy(state.native[key])
            mutations = {'record_digest': 'f' * 64, 'name': 'f' * 64, 'company': 'Other', 'project': 'Other',
                'scope_type': 'Company', 'author_person': 'Other', 'status': 'committed', 'device_id': uid(),
                'capture_id': uid(), 'owner_person': 'Other', 'revision_number': 99, 'last_event': uid()}
            for field_name, item in mutations.items():
                state.native[key] = {**deepcopy(original), field_name: item}
                with self.subTest(field=field_name), self.assertRaises(DomainError) as error:
                    repo.raw('capture', key[1])
                self.assertEqual(error.exception.code, 'field_offline_integrity')
            state.native[key] = deepcopy(original)
            value = json.loads(original['data_json'])
            value['envelope']['command']['quantities'][0]['quantity'] = '99.000000'
            state.native[key]['data_json'] = canonical_json(value)
            with self.assertRaises(DomainError):
                repo.raw('capture', key[1])
            state.native[key] = original
            self.assertEqual(repo.raw('capture', key[1])['envelope'], captured)

    def test_optional_native_int_zero_is_normalized_only_when_the_record_omits_it(self):
        with fixture() as (state, _, _, _, repo, _, service):
            original_insert = state.FakeDocument.insert
            def native_default(doc, **kwargs):
                if doc.doctype == repo.KINDS['device'] and doc.get('revision_number') is None:
                    doc.revision_number = 0
                return original_insert(doc, **kwargs)
            with patch.object(state.FakeDocument, 'insert', native_default):
                registered = device(state, service)
            name = registered['device']['device_id']
            key = (repo.KINDS['device'], name)
            self.assertEqual(state.native[key]['revision_number'], 0)
            self.assertNotIn('revision_number', repo.raw('device', name))
            for invalid in ('0', 0.0, False, 1):
                state.native[key]['revision_number'] = invalid
                with self.subTest(value=invalid), self.assertRaises(DomainError):
                    repo.raw('device', name)
            state.native[key]['revision_number'] = 0
            _, captured, _ = stage(state, service)
            key = (repo.KINDS['capture'], capture_key(state, captured))
            state.native[key]['revision_number'] = 0
            with self.assertRaises(DomainError):
                repo.raw('capture', key[1])

    def test_actual_event_facts_are_immutable_and_native_trash_rename_stay_closed(self):
        with fixture() as (state, _, _, _, repo, records, service):
            registered, captured, staged = stage(state, service)
            apply(service, captured, staged)
            current = repo.raw('capture', capture_key(state, captured))
            event = repo.raw('event', current['last_event'])
            before = deepcopy(state.native)
            changed = {**event, 'reason': 'Attempted rewrite of immutable event evidence'}
            with admitted(repo, state, 'apply'), self.assertRaises(DomainError) as error:
                repo.write('event', changed, old=event)
            self.assertEqual(error.exception.code, 'field_offline_integrity')
            self.assertEqual(state.native, before)
            for kind, name in (('device', registered['device']['device_id']), ('capture', current['id']), ('event', event['id'])):
                doc = state.get_doc(repo.KINDS[kind], name)
                with self.subTest(kind=kind), self.assertRaises(DomainError) as trash:
                    records.OfflineRecord.on_trash(doc)
                self.assertEqual(trash.exception.code, 'field_offline_command_required')
                with self.assertRaises(DomainError) as rename:
                    records.OfflineRecord.before_rename(doc, name, uid())
                self.assertEqual(rename.exception.code, 'field_offline_command_required')
            self.assertEqual(state.native, before)

    def test_malformed_native_json_is_safe_and_optional_missing_reads_are_explicit(self):
        with fixture() as (state, _, _, _, repo, _, service):
            registered = device(state, service)
            key = (repo.KINDS['device'], registered['device']['device_id'])
            state.native[key]['data_json'] = '{private-capture-and-identity'
            with self.assertRaises(DomainError) as error:
                repo.raw('device', key[1])
            self.assertEqual(error.exception.code, 'field_offline_integrity')
            self.assertNotIn('private-capture', error.exception.message)
            self.assertIsNone(repo.raw('device', uid(), optional=True))
            with self.assertRaises(DomainError) as missing:
                repo.raw('device', uid())
            self.assertEqual(missing.exception.code, 'not_found')

    def test_original_metadata_receipt_and_current_redacted_projection_have_distinct_valid_wires(self):
        with fixture() as (state, _, field_repo, field_service, repo, _, service):
            registered = device(state, service)
            validate(ROUTES['responses']['register_device'], registered)
            captured = envelope(state, registered)
            stage_operation = uid()
            staged = service.stage_capture('C', 'P', stage_operation, captured)
            validate(ROUTES['responses']['stage_capture'], staged)
            validate(ROUTES['responses']['inspect_capture'], service.inspect_capture('C', 'P', captured['capture_id']))
            committed = apply(service, captured, staged)
            validate(ROUTES['responses']['apply_capture'], committed)
            original = deepcopy(committed['original_receipt'])
            old_quantity = original['quantities'][0]
            field_service.revise_record('C', 'P', uid(), 'daily', original['header']['id'], digest(original['header']),
                daily(state), [], [quantity(add_source(state), old_quantity['original_event_id'], old_quantity['id'])])
            discarded = service.discard_capture('C', 'P', uid(), captured['capture_id'], committed['capture_version'], 'Discard only the retained offline copy')
            validate(ROUTES['responses']['discard_capture'], discarded)
            current = service.get_capture('C', 'P', captured['capture_id'])
            validate(ROUTES['responses']['get_capture'], current)
            historical = service.stage_capture('C', 'P', stage_operation, captured)
            validate(ROUTES['responses']['stage_capture'], historical)
            self.assertEqual(historical['capture'], staged['capture'])
            self.assertTrue(historical['operation']['replayed'])
            self.assertEqual(historical['capture']['status'], 'staged')
            self.assertEqual(current['capture']['status'], 'committed')
            self.assertTrue(historical['capture']['payload_retained'])
            self.assertFalse(current['capture']['payload_retained'])
            self.assertIsNone(current['envelope'])
            self.assertEqual(current['original_receipt']['revision'], original['revision'])
            self.assertNotEqual(field_repo.raw('daily', original['header']['id'])['current_revision'], original['revision']['id'])
            self.assertEqual(repo.raw('capture', capture_key(state, captured))['envelope_digest'], digest(captured))


class OfflineActualRouteContractsTests(unittest.TestCase):
    def test_all_eight_actual_routes_match_closed_wire_fields_and_mutation_methods(self):
        api = ast.parse((ROOT / 'field_offline/api.py').read_text())
        functions = {node.name: node for node in api.body if isinstance(node, ast.FunctionDef)}
        self.assertEqual(set(functions), set(ROUTES['requests']))
        self.assertEqual(set(functions), set(ROUTES['responses']))
        for route, node in functions.items():
            with self.subTest(route=route):
                request = SCHEMA['$defs'][ROUTES['requests'][route]]
                arguments = [argument.arg for argument in node.args.args]
                required = arguments[:len(arguments) - len(node.args.defaults)] if node.args.defaults else arguments
                self.assertEqual(set(request['properties']), set(arguments))
                self.assertEqual(set(request['required']), set(required))
                self.assertIs(request['additionalProperties'], False)
                endpoint = next(item for item in node.decorator_list if isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == 'endpoint')
                methods = next((ast.literal_eval(item.value) for item in endpoint.keywords if item.arg == 'methods'), ['GET'])
                self.assertEqual(methods, ['GET'] if route in ('get_capture', 'inspect_capture') else ['POST'])


if __name__ == '__main__':
    unittest.main()
