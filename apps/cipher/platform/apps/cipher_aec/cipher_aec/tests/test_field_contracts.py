"""FLD-01 closed contracts checked against real field services in host fixtures."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from cipher_aec.api.contracts import digest
from cipher_aec.tests.test_field import (
    add_person, add_source, daily, fixtures, photo, quantity, ticket, uid,
)

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / 'field/schemas/api-v1.schema.json').read_text())
ROUTES = json.loads((ROOT / 'field/route-contracts.json').read_text())


def validate(name, value):
    Draft202012Validator(
        {'$ref': '#/$defs/' + name, '$defs': SCHEMA['$defs']},
        format_checker=FormatChecker(),
    ).validate(value)


class FieldContractsTests(unittest.TestCase):
    def test_all_object_definitions_are_closed_and_references_resolve(self):
        Draft202012Validator.check_schema(SCHEMA)
        self.assertTrue(all(name.startswith('Fd') for name in SCHEMA['$defs']))

        def walk(value):
            if isinstance(value, dict):
                if value.get('type') == 'object':
                    self.assertIs(value.get('additionalProperties'), False)
                    self.assertLessEqual(set(value['required']), set(value['properties']))
                if '$ref' in value:
                    self.assertTrue(value['$ref'].startswith('#/$defs/Fd'))
                    self.assertIn(value['$ref'].split('/')[-1], SCHEMA['$defs'])
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(SCHEMA)

    def test_routes_match_exact_api_parameters_and_optional_defaults(self):
        api = ast.parse((ROOT / 'field/api.py').read_text())
        functions = {node.name: node for node in api.body if isinstance(node, ast.FunctionDef)}
        expected = {'create_record', 'revise_record', 'transition', 'get_record', 'list_records'}
        self.assertEqual(set(functions), expected)
        self.assertEqual(set(ROUTES['requests']), expected)
        self.assertEqual(set(ROUTES['responses']), expected)
        for route, node in functions.items():
            with self.subTest(route=route):
                request = SCHEMA['$defs'][ROUTES['requests'][route]]
                names = [arg.arg for arg in node.args.args]
                required = names[:len(names) - len(node.args.defaults)] if node.args.defaults else names
                self.assertEqual(set(request['properties']), set(names))
                self.assertEqual(set(request['required']), set(required))
                self.assertIn(ROUTES['responses'][route], SCHEMA['$defs'])
        for name in ('FdCreateRecordRequest', 'FdReviseRecordRequest'):
            self.assertEqual(len(SCHEMA['$defs'][name]['oneOf']), 2)

    def test_requests_pair_family_definition_and_documentary_quantities(self):
        with fixtures() as (state, rules, repo, sources, service, records):
            source = add_source(state)
            daily_request = {
                'company': 'C', 'project': 'P', 'operation_id': uid(), 'family': 'daily',
                'definition': daily(state), 'photos': [], 'quantities': [quantity(source)],
            }
            ticket_request = {
                **daily_request, 'operation_id': uid(), 'family': 'ticket',
                'definition': ticket(source), 'quantities': [],
            }
            for request in (daily_request, ticket_request):
                validate('FdCreateRecordRequest', request)
                validate('FdReviseRecordRequest', {
                    **request, 'record_id': uid(), 'expected_version': 'a' * 64,
                })
            invalid = [
                {**daily_request, 'family': 'ticket'},
                {**ticket_request, 'family': 'daily'},
                {**ticket_request, 'quantities': [quantity(source)]},
                {**daily_request, 'actor': 'caller-supplied-authority'},
                {**daily_request, 'definition': {**daily_request['definition'], 'approved_amount': '10.00'}},
            ]
            for request in invalid:
                with self.subTest(request=request), self.assertRaises(ValidationError):
                    validate('FdCreateRecordRequest', request)
            for observed in ('0', '0.000000', '-1', '1e3', '1.0000001', '1000000000000', 2.5):
                request = deepcopy(daily_request)
                request['quantities'][0]['quantity'] = observed
                with self.subTest(quantity=observed), self.assertRaises(ValidationError):
                    validate('FdCreateRecordRequest', request)
            request = deepcopy(ticket_request)
            request['definition']['lines'][0]['rate'] = '150.00'
            with self.assertRaises(ValidationError):
                validate('FdCreateRecordRequest', request)
            captured = service.create_record(**daily_request)['quantities'][0]['definition']['sources'][0]
            request = deepcopy(daily_request)
            request['quantities'][0]['sources'] = [captured]
            with self.assertRaises(ValidationError):
                validate('FdCreateRecordRequest', request)

    def test_transition_requests_bind_family_action_and_acknowledgment_evidence(self):
        request = {
            'company': 'C', 'project': 'P', 'operation_id': uid(), 'family': 'daily',
            'record_id': uid(), 'expected_version': 'a' * 64, 'action': 'submit',
            'comment': 'Submit the observed facts.', 'evidence': [],
        }
        validate('FdTransitionRequest', request)
        validate('FdTransitionRequest', {**request, 'acknowledged_by': ''})
        with fixtures() as (state, rules, repo, sources, service, records):
            acknowledged = {
                **request, 'family': 'ticket', 'action': 'acknowledge',
                'evidence': [add_source(state)], 'acknowledged_by': 'Customer representative',
            }
            validate('FdTransitionRequest', acknowledged)
            for invalid in (
                {**acknowledged, 'family': 'daily'},
                {**acknowledged, 'evidence': []},
                {**acknowledged, 'acknowledged_by': '  '},
                {key: value for key, value in acknowledged.items() if key != 'acknowledged_by'},
                {**request, 'acknowledged_by': 'Unrelated name'},
            ):
                with self.subTest(request=invalid), self.assertRaises(ValidationError):
                    validate('FdTransitionRequest', invalid)

    def test_header_parent_filters_are_not_part_of_the_native_contract(self):
        for kind in ('daily', 'ticket'):
            request = {'company': 'C', 'project': 'P', 'kind': kind}
            validate('FdListRecordsRequest', request)
            validate('FdListRecordsRequest', {**request, 'parent_id': None})
            with self.assertRaises(ValidationError):
                validate('FdListRecordsRequest', {**request, 'parent_id': uid()})

    def test_actual_commands_all_six_record_kinds_get_and_list_match_schemas(self):
        with fixtures() as (state, rules, repo, sources, service, records):
            author = state.actor
            reviewer = add_person(state, 'field-contract-reviewer')
            observed = set()

            def check_response(name, value):
                validate(name, value)
                validate('FdDailyHeader' if value['family'] == 'daily' else 'FdTicketHeader', value['header'])
                validate('FdDailyRevision' if value['family'] == 'daily' else 'FdTicketRevision', value['revision'])
                self.assertEqual(value['revision']['parent_id'], value['header']['id'])
                for captured in value.get('quantities', []):
                    validate('FdQuantity', captured)
                if 'decision' in value:
                    validate('FdDecision', value['decision'])
                    self.assertNotIn('quantities', value)
                else:
                    self.assertNotIn('decision', value)

            def transition(result, action):
                request = {
                    'company': 'C', 'project': 'P', 'operation_id': uid(), 'family': result['family'],
                    'record_id': result['header']['id'], 'expected_version': digest(result['header']),
                    'action': action, 'comment': 'Documentary ' + action,
                    'evidence': [add_source(state)] if action == 'acknowledge' else [],
                    'acknowledged_by': 'Customer representative' if action == 'acknowledge' else '',
                }
                validate('FdTransitionRequest', request)
                result = service.transition(**request)
                check_response('FdTransitionResponse', result)
                return result

            for family in ('daily', 'ticket'):
                state.actor = author
                source = add_source(state)
                definition = daily(state) if family == 'daily' else ticket(source)
                if family == 'daily':
                    definition.update(weather='Clear at the recorded work location.', weather_sources=[source])
                request = {
                    'company': 'C', 'project': 'P', 'operation_id': uid(), 'family': family,
                    'definition': definition, 'photos': [photo(add_source(state, 'image/jpeg'))],
                    'quantities': [quantity(source)] if family == 'daily' else [],
                }
                validate('FdCreateRecordRequest', request)
                result = service.create_record(**request)
                check_response('FdCreateRecordResponse', result)
                replay = service.create_record(**request)
                check_response('FdCreateRecordResponse', replay)
                self.assertTrue(replay['operation']['replayed'])
                revised = {
                    **request, 'operation_id': uid(), 'record_id': result['header']['id'],
                    'expected_version': digest(result['header']),
                    'quantities': [quantity(source, result['quantities'][0]['original_event_id'], result['quantities'][0]['id'])] if family == 'daily' else [],
                }
                validate('FdReviseRecordRequest', revised)
                result = service.revise_record(**revised)
                check_response('FdReviseRecordResponse', result)
                result = transition(result, 'submit')
                state.actor = reviewer
                result = transition(result, 'review')
                result = transition(result, 'return')
                state.actor = author
                result = service.revise_record(
                    'C', 'P', uid(), family, result['header']['id'], digest(result['header']),
                    definition, [], [],
                )
                check_response('FdReviseRecordResponse', result)
                result = transition(result, 'submit')
                state.actor = reviewer
                result = transition(result, 'review')
                result = transition(result, 'accept')
                if family == 'ticket':
                    result = transition(result, 'acknowledge')
                state.actor = author
                result = service.revise_record(
                    'C', 'P', uid(), family, result['header']['id'], digest(result['header']),
                    definition, [], [], 'Correct the accepted documentary observation.',
                )
                check_response('FdReviseRecordResponse', result)

            def candidates(kind, company, project, parent_id=None, last=None, limit=25):
                values = sorted((
                    json.loads(native['data_json']) for (doctype, identifier), native in state.native.items()
                    if doctype == rules.KINDS[kind]
                    and native['company'] == company and native['project'] == project
                ), key=lambda value: value['id'], reverse=True)
                if parent_id:
                    values = [value for value in values if value.get('parent_id') == parent_id]
                start = next((index + 1 for index, value in enumerate(values) if last and value['id'] == last[1]), 0)
                return [SimpleNamespace(name=value['id'], creation='2026-10-17 00:00:00') for value in values[start:start + limit]]

            names = {
                'daily': 'FdDailyHeader', 'ticket': 'FdTicketHeader',
                'daily_revision': 'FdDailyRevision', 'ticket_revision': 'FdTicketRevision',
                'quantity': 'FdQuantity', 'decision': 'FdDecision',
            }
            with patch.object(repo, 'candidate_rows', candidates):
                for kind, schema_name in names.items():
                    page = service.list_records('C', 'P', kind, limit=2)
                    validate('FdListResponse', page)
                    seen = []
                    while True:
                        for item in page['items']:
                            validate(schema_name, item['record'])
                            read = service.get_record('C', 'P', kind, item['record']['id'])
                            validate('FdGetResponse', read)
                            self.assertEqual(read, item)
                            seen.append(item['record']['id'])
                        if page['next_cursor'] is None:
                            break
                        page = service.list_records('C', 'P', kind, limit=2, cursor=page['next_cursor'])
                        validate('FdListResponse', page)
                    self.assertTrue(seen, kind)
                    self.assertEqual(len(seen), len(set(seen)))
                    observed.add(kind)
            self.assertEqual(observed, set(rules.KINDS))

    def test_outputs_refuse_extra_fields_family_swaps_and_commercial_effects(self):
        with fixtures() as (state, rules, repo, sources, service, records):
            source = add_source(state)
            result = service.create_record('C', 'P', uid(), 'daily', daily(state), [], [quantity(source)])
            for path, key, value in (
                ((), 'decision', {}), (('revision',), 'rates', []),
                (('revision', 'no_effects'), 'contract_change', True),
                (('quantities', 0, 'definition'), 'price', '12.00'),
                (('quantities', 0, 'definition', 'sources', 0), 'content', 'source bytes'),
            ):
                mutated = deepcopy(result)
                target = mutated
                for part in path:
                    target = target[part]
                target[key] = value
                with self.subTest(path=path, key=key), self.assertRaises(ValidationError):
                    validate('FdCreateRecordResponse', mutated)
            with self.assertRaises(ValidationError):
                validate('FdCreateRecordResponse', {**result, 'family': 'ticket'})
            with self.assertRaises(ValidationError):
                validate('FdGetResponse', {'record': {**result['header'], 'scope_type': 'Company'}, 'record_digest': 'a' * 64})
            with self.assertRaises(ValidationError):
                validate('FdDailyHeader', {**result['header'], 'status': 'acknowledged'})
            with self.assertRaises(ValidationError):
                validate('FdListResponse', {'items': [], 'next_cursor': None, 'limit': 101, 'count_mode': 'none', 'total': None})


if __name__ == '__main__':
    unittest.main()
