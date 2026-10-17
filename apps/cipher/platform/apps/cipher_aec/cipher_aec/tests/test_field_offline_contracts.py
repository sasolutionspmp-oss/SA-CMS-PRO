"""Pure FLD02 wire/JSON validation; no device authority or native sync claim."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid1, uuid4, uuid5, NAMESPACE_URL

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.field import contracts as field
from cipher_aec.field_offline import contracts as rules

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / 'field_offline/schemas/api-v1.schema.json').read_text())
ROUTES = json.loads((ROOT / 'field_offline/route-contracts.json').read_text())


def uid():
    return str(uuid4())


def source():
    return {'revision_id': 'REV-exact-original', 'source_sha256': 'a' * 64, 'page': 1, 'locator': 'Grid A / original source'}


def daily():
    return {'local_date': '2026-10-17', 'superintendent_user': 'superintendent@example.invalid',
        'weather': '', 'weather_sources': [], 'crews': ['Civil crew'], 'activities': ['Observed pipe installation.'],
        'delays': [], 'visitors': []}


def quantity():
    return {'original_event_id': uid(), 'supersedes_event_id': None, 'kind': 'installed',
        'description': 'Pipe observation', 'wbs_code': '02.01', 'cost_code': 'PIPE',
        'quantity': '12.375000', 'unit': 'LF', 'location': 'Grid A', 'sources': [source()]}


def ticket():
    return {'local_date': '2026-10-17', 'title': 'Documented obstruction', 'customer_name': 'Synthetic owner',
        'location': 'Grid A', 'work_description': 'Removed the observed obstruction.', 'potential_change_reference': '',
        'lines': [{'kind': 'labor', 'description': 'Crew observation', 'quantity': '3.250000', 'unit': 'person-hours', 'sources': [source()]}]}


def command(family='daily', action='create'):
    value = {'action': action, 'family': family, 'definition': daily() if family == 'daily' else ticket(),
        'photos': [{'source': source(), 'caption': 'Authored photo observation', 'captured_at': '2026-10-17T09:15:00-04:00', 'representation': 'photo_on_pdf_page'}],
        'quantities': [quantity()] if family == 'daily' else []}
    if action == 'revise':
        value.update(record_id=uid(), expected_version='b' * 64, base_revision_id=uid(),
                     base_revision_digest='c' * 64, amendment_reason='')
    return value


def envelope(family='daily', action='create'):
    return {'schema': rules.SCHEMA, 'device_id': uid(), 'capture_id': uid(), 'company': 'C', 'project': 'P',
        'actor_person': 'canonical-person-id', 'actor_user': 'original-capture-user@example.invalid',
        'captured_at': '2026-10-17T09:15:00-04:00', 'command': command(family, action)}


def validate(name, value):
    Draft202012Validator({'$ref': '#/$defs/' + name, '$defs': SCHEMA['$defs']}, format_checker=FormatChecker()).validate(value)


class OfflineEnvelopeContractsTests(unittest.TestCase):
    def test_daily_ticket_create_and_revise_return_exact_original_json(self):
        for family in ('daily', 'ticket'):
            for action in ('create', 'revise'):
                value = envelope(family, action)
                before = deepcopy(value)
                with self.subTest(family=family, action=action):
                    self.assertIs(rules.envelope(value), value)
                    self.assertIs(rules.command(value['command']), value['command'])
                    self.assertEqual(value, before)
                    validate('FoEnvelope', value)
                    if family == 'daily':
                        self.assertEqual(value['command']['quantities'][0]['quantity'], '12.375000')
                    else:
                        self.assertEqual(value['command']['definition']['lines'][0]['quantity'], '3.250000')
                    self.assertEqual(value['captured_at'], '2026-10-17T09:15:00-04:00')

    def test_capture_and_device_ids_are_canonical_uuid4_without_trimming(self):
        invalid = [str(uuid1()), str(uuid5(NAMESPACE_URL, 'offline-field')), 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA',
                   ' ' + uid(), uid() + ' ', 'not-a-uuid', None, 4, True]
        for field_name in ('capture_id', 'device_id'):
            for identifier in invalid:
                value = envelope()
                value[field_name] = identifier
                with self.subTest(field=field_name, identifier=identifier), self.assertRaises(DomainError):
                    rules.envelope(value)
                with self.assertRaises(ValidationError):
                    validate('FoEnvelope', value)
        original = uid()
        self.assertEqual(rules.identifier(original), original)

    def test_scope_requires_declared_company_and_project_and_preserves_authored_text(self):
        self.assertEqual(rules.scope('Company A', 'Project A'), {'company': 'Company A', 'scope_type': 'Project', 'project': 'Project A'})
        for company, project in ((None, 'P'), ('C', None), ('C', ''), ('C', '  '), ('', 'P'), ('C', 3)):
            value = envelope()
            value.update(company=company, project=project)
            with self.subTest(company=company, project=project), self.assertRaises(DomainError):
                rules.envelope(value)
        value = envelope()
        value['scope_type'] = 'Company'
        with self.assertRaises(DomainError):
            rules.envelope(value)

    def test_actor_attribution_is_required_bounded_data_without_authority_coercion(self):
        value = envelope()
        value['actor_person'] = 'declared-person-awaiting-server-registration-check'
        value['actor_user'] = 'original-registration-alias@example.invalid'
        self.assertIs(rules.envelope(value), value)
        for key in ('actor_person', 'actor_user'):
            for invalid in ('', ' ', 'x' * 141, None, {'person': 'spoof'}):
                mutation = deepcopy(value)
                mutation[key] = invalid
                with self.subTest(key=key, invalid=invalid), self.assertRaises(DomainError):
                    rules.envelope(mutation)
        # Device ownership, alias-to-Person binding and current rights are not
        # inferred by these pure validators; the server performs those checks.
        self.assertEqual(value['actor_user'], 'original-registration-alias@example.invalid')

    def test_envelope_is_closed_and_requires_the_supported_version(self):
        value = envelope()
        for key in list(value):
            missing = {name: item for name, item in value.items() if name != key}
            with self.subTest(missing=key), self.assertRaises(DomainError):
                rules.envelope(missing)
        for mutation in ({**value, 'schema': 'cipher.field.offline.v2'}, {**value, 'operation_id': uid()},
                         {**value, 'permission': 'owner'}, {**value, 'source_rights': True}):
            with self.subTest(mutation=mutation), self.assertRaises(DomainError):
                rules.envelope(mutation)
            with self.assertRaises(ValidationError):
                validate('FoEnvelope', mutation)

    def test_only_exact_documentary_create_and_revise_variants_are_admitted(self):
        for action in ('submit', 'review', 'return', 'accept', 'acknowledge', 'post', 'pay', None):
            value = command()
            value['action'] = action
            with self.subTest(action=action), self.assertRaises(DomainError):
                rules.command(value)
            with self.assertRaises(ValidationError):
                validate('FoCommand', value)
        for key, item in (('actor', 'owner'), ('approval_id', uid()), ('invoice_id', uid()), ('no_effects', {}), ('rate', '10.00')):
            value = command()
            value[key] = item
            with self.subTest(key=key), self.assertRaises(DomainError):
                rules.command(value)
        with self.assertRaises(DomainError):
            rules.command({**command(), 'family': 'quantity'})

    def test_revision_base_is_exact_required_data_without_server_truth_inference(self):
        value = command(action='revise')
        self.assertIs(rules.command(value), value)
        for key in ('record_id', 'expected_version', 'base_revision_id', 'base_revision_digest', 'amendment_reason'):
            mutated = {name: item for name, item in value.items() if name != key}
            with self.subTest(missing=key), self.assertRaises(DomainError):
                rules.command(mutated)
            with self.assertRaises(ValidationError):
                validate('FoReviseCommand', mutated)
        for key in ('expected_version', 'base_revision_digest'):
            with self.subTest(key=key), self.assertRaises(DomainError):
                rules.command({**value, key: 'A' * 64})
        with self.assertRaises(DomainError):
            rules.command({**command(), 'base_revision_id': uid()})
        with self.assertRaises(DomainError):
            rules.command({**value, 'amendment_reason': 'x' * 2001})
        # Valid-looking unknown bases remain declarative; server verification is
        # required before the original FLD01 command can mutate a field record.
        self.assertIs(rules.command({**value, 'record_id': uid(), 'base_revision_id': uid()})['action'], value['action'])

    def test_decimal_quantity_and_source_shapes_reuse_fld01_exact_bounds(self):
        for observed in ('0', '0.000000', '-1', '1e3', '1.0000001', '1000000000000', 1.25, True):
            for family in ('daily', 'ticket'):
                value = command(family)
                target = value['quantities'][0] if family == 'daily' else value['definition']['lines'][0]
                target['quantity'] = observed
                with self.subTest(family=family, quantity=observed), self.assertRaises(DomainError):
                    rules.command(value)
                with self.assertRaises(ValidationError):
                    validate('FoCommand', value)
        for key, item in (('document_id', 'client-canonical-claim'), ('content', 'original bytes'), ('mime_type', 'image/jpeg'), ('url', 'https://example.invalid/file')):
            value = command()
            value['quantities'][0]['sources'][0][key] = item
            with self.subTest(key=key), self.assertRaises(DomainError):
                rules.command(value)
        for page in (0, 201, True):
            value = command()
            value['quantities'][0]['sources'][0]['page'] = page
            with self.subTest(page=page), self.assertRaises(DomainError):
                rules.command(value)

    def test_family_pairing_and_duplicate_quantity_capture_are_refused(self):
        with self.assertRaises(DomainError):
            rules.command({**command(), 'family': 'ticket'})
        value = command('ticket')
        value['quantities'] = [quantity()]
        with self.assertRaises(DomainError):
            rules.command(value)
        value = command()
        value['quantities'].append({**deepcopy(value['quantities'][0]), 'description': 'Different observation for duplicate original ID'})
        with self.assertRaises(DomainError):
            rules.command(value)
        value = command()
        value['quantities'] *= 41
        with self.assertRaises(DomainError):
            rules.command(value)

    def test_fld01_photo_weather_and_offset_timestamp_requirements_remain_in_force(self):
        for mutation in (lambda value: value.update(captured_at='2026-10-17T09:15:00'),
                         lambda value: value['command']['photos'][0].update(captured_at='2026-10-17'),
                         lambda value: value['command']['photos'][0].update(representation='original_camera_image'),
                         lambda value: value['command']['definition'].update(weather='Clear', weather_sources=[]),
                         lambda value: value['command']['definition'].update(local_date='2026-02-30'),
                         lambda value: value['command']['definition'].update(activities=[])):
            value = envelope()
            mutation(value)
            with self.subTest(value=value), self.assertRaises(DomainError):
                rules.envelope(value)
            with self.assertRaises(ValidationError):
                validate('FoEnvelope', value)
        value = envelope()
        value['command']['definition'].update(weather='Authored clear weather observation', weather_sources=[source()])
        self.assertIs(rules.envelope(value), value)

    def test_non_json_nonfinite_and_coercible_python_values_are_refused_safely(self):
        for item in (float('nan'), float('inf'), float('-inf'), Decimal('1.25'), b'private-data',
                     datetime.now(timezone.utc), ('tuple',), {'set'}, {1: 'integer-key'}, '\ud800'):
            value = envelope()
            value['command']['definition']['weather'] = item
            with self.subTest(type=type(item).__name__), self.assertRaises(DomainError) as error:
                rules.envelope(value)
            self.assertNotIn('private-data', error.exception.message)
        value = envelope()
        value['command']['definition']['weather'] = value
        with self.assertRaises(DomainError):
            rules.envelope(value)
        nested = []
        for _ in range(rules.MAX_JSON_DEPTH + 2):
            nested = [nested]
        with self.assertRaises(DomainError):
            rules.json_input(nested)

    def test_256_kib_budget_counts_utf8_and_json_escaping_exactly(self):
        self.assertEqual(rules.MAX_ENVELOPE_BYTES, 256 * 1024)
        value = envelope()
        value['command']['definition']['activities'] = ['Observed 界😀 installation.']
        size = len(canonical_json(value).encode('utf-8'))
        with patch.object(rules, 'MAX_ENVELOPE_BYTES', size):
            self.assertIs(rules.envelope(value), value)
        with patch.object(rules, 'MAX_ENVELOPE_BYTES', size - 1), self.assertRaises(DomainError) as error:
            rules.envelope(value)
        self.assertEqual(error.exception.code, 'field_offline_limit')
        # Every item stays within FLD01 bounds while aggregate JSON exceeds the
        # offline transport budget; repeated exact revisions do not add bytes.
        value = envelope()
        value['command']['quantities'] = []
        for _ in range(40):
            observed = quantity()
            observed['sources'] = [{**source(), 'locator': str(index) + 'x' * 999} for index in range(8)]
            value['command']['quantities'].append(observed)
        with self.assertRaises(DomainError) as error:
            rules.envelope(value)
        self.assertEqual(error.exception.code, 'field_offline_limit')


class OfflineWireSchemaTests(unittest.TestCase):
    def test_all_objects_are_closed_and_all_local_references_resolve(self):
        Draft202012Validator.check_schema(SCHEMA)
        def walk(value):
            if isinstance(value, dict):
                if value.get('type') == 'object':
                    self.assertIs(value.get('additionalProperties'), False)
                    self.assertLessEqual(set(value['required']), set(value['properties']))
                if '$ref' in value:
                    self.assertTrue(value['$ref'].startswith('#/$defs/Fo'))
                    self.assertIn(value['$ref'].split('/')[-1], SCHEMA['$defs'])
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(SCHEMA)
        self.assertEqual(SCHEMA['$defs']['FoEnvelope']['x-max-json-bytes'], rules.MAX_ENVELOPE_BYTES)

    def test_copied_fld01_inputs_and_original_receipt_keep_exact_existing_schemas(self):
        original = json.loads((ROOT / 'field/schemas/api-v1.schema.json').read_text())['$defs']
        def rename(value):
            if isinstance(value, dict):
                return {key: '#/$defs/Fo' + item.removeprefix('#/$defs/Fd') if key == '$ref' else rename(item) for key, item in value.items()}
            if isinstance(value, list):
                return [rename(item) for item in value]
            return value
        for name in ('SourceInput', 'DailyDefinitionInput', 'TicketDefinitionInput', 'PhotoInput', 'QuantityDefinitionInput', 'QuantityValue', 'CreateRecordResponse'):
            with self.subTest(name=name):
                self.assertEqual(SCHEMA['$defs']['Fo' + name], rename(original['Fd' + name]))

    def test_route_requests_match_the_exact_agreed_api_signatures(self):
        signatures = {
            'register_device': ['company', 'project', 'operation_id', 'device_id', 'label'],
            'revoke_device': ['company', 'project', 'operation_id', 'device_id', 'expected_version', 'reason'],
            'stage_capture': ['company', 'project', 'operation_id', 'envelope'],
            'get_capture': ['company', 'project', 'capture_id'],
            'inspect_capture': ['company', 'project', 'capture_id'],
            'apply_capture': ['company', 'project', 'operation_id', 'capture_id', 'expected_version'],
            'discard_capture': ['company', 'project', 'operation_id', 'capture_id', 'expected_version', 'reason'],
            'resolve_capture': ['company', 'project', 'operation_id', 'capture_id', 'expected_version', 'replacement_envelope', 'reason'],
        }
        self.assertEqual(set(ROUTES), {'requests', 'responses'})
        self.assertEqual(set(ROUTES['requests']), set(signatures))
        self.assertEqual(set(ROUTES['responses']), set(signatures))
        for route, names in signatures.items():
            with self.subTest(route=route):
                request = SCHEMA['$defs'][ROUTES['requests'][route]]
                self.assertEqual(set(request['properties']), set(names))
                self.assertEqual(set(request['required']), set(names))
                self.assertIn(ROUTES['responses'][route], SCHEMA['$defs'])
        request = {'company': 'C', 'project': 'P', 'operation_id': uid(), 'envelope': envelope()}
        validate(ROUTES['requests']['stage_capture'], request)
        self.assertNotEqual(request['operation_id'], request['envelope']['capture_id'])
        validate(ROUTES['requests']['apply_capture'], {'company': 'C', 'project': 'P', 'operation_id': request['envelope']['capture_id'], 'capture_id': request['envelope']['capture_id'], 'expected_version': 'a' * 64})

    def test_capture_summaries_and_conflicts_are_closed_and_do_not_carry_plaintext(self):
        captured = envelope()
        summary = {key: captured[key] for key in ('capture_id', 'device_id', 'company', 'project', 'actor_person', 'actor_user')}
        summary.update(envelope_digest=digest(captured), status='staged', payload_retained=True, replaces_capture_id=None, replacement_capture_id=None)
        validate('FoCaptureSummary', summary)
        read = {'capture': summary, 'capture_version': 'a' * 64, 'envelope': captured, 'original_receipt': None}
        validate('FoGetCaptureResponse', read)
        validate('FoGetCaptureResponse', {**read, 'envelope': None})
        conflict = {'code': 'base_changed', 'current_header_version': 'b' * 64, 'current_revision_id': uid(), 'current_revision_digest': 'c' * 64}
        inspect = {'capture': summary, 'capture_version': 'a' * 64, 'disposition': 'conflict', 'conflict': conflict, 'original_receipt': None}
        validate('FoInspectCaptureResponse', inspect)
        for mutation in ({**summary, 'command': captured['command']}, {**summary, 'status': 'accepted'}, {**summary, 'payload_retained': 'yes'}):
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                validate('FoCaptureSummary', mutation)
        with self.assertRaises(ValidationError):
            validate('FoInspectCaptureResponse', {**inspect, 'disposition': 'ready'})
        with self.assertRaises(ValidationError):
            validate('FoInspectCaptureResponse', {**inspect, 'conflict': None})


if __name__ == '__main__':
    unittest.main()
