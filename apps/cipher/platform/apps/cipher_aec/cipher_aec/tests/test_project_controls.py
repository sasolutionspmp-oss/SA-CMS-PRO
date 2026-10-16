"""Independent pure WBS and accepted-cost adoption invariants."""
from copy import deepcopy
import unittest
from uuid import UUID

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.project_controls import core


def uid(number):
    return str(UUID(int=number))


def fixture():
    company, day = 'Controls fixture company', '2026-10-15'
    def money(amount):
        return {'amount': amount, 'currency': 'USD'}
    def node(number, code, parent, leaf):
        return {'id': uid(number), 'code': code, 'parent_id': parent, 'title': code,
                'is_leaf': leaf, 'accountable_person': None, 'phase': '', 'active_from': None, 'active_until': None}
    nodes = [node(1, 'WORK', None, False), node(2, 'WORK.01', uid(1), True)]
    def authority(number, kind, allocation=None, category=None):
        definition = {'title': 'Explicit selected authority', 'effective_from': day, 'effective_until': None, 'enabled': True,
                      'native_target': {'doctype': 'Cost Center' if kind == 'code' else 'Account', 'name': 'Explicit native target'}}
        if kind == 'type':
            definition.update(allocation_class=allocation, cost_category=category)
        native = {'doctype': definition['native_target']['doctype'], 'name': 'Explicit native target', 'company': company,
                  'version': '1', 'is_group': False, 'disabled': False, 'root_type': 'Expense' if kind == 'type' else None,
                  'account_currency': 'USD' if kind == 'type' else None, 'currency_policy': {'currency': 'USD', 'currency_exponent': 2, 'fraction_units': 100, 'native_currency_version': '1'} if kind == 'type' else None}
        revision = {'schema': 'cipher.cost-revision.v1', 'id': uid(number), 'company': company, 'project': None, 'author_person': 'FIXTURE-AUTHOR',
                    'kind': kind, 'master_id': uid(number + 100), 'code': 'CODE-' + str(number), 'definition': definition,
                    'revision_number': 1, 'predecessor': None, 'authored_native': deepcopy(native)}
        return {'kind': kind, 'company': company, 'basis_date': day, 'purpose': 'award.initial-budget.v1',
                'revision': revision, 'revision_digest': digest(revision), 'native': native}
    codes = [authority(10, 'code')]
    types = [authority(20, 'type', 'component', 'material'), authority(21, 'type', 'component', 'labor'),
             authority(22, 'type', 'indirect'), authority(23, 'type', 'contingency')]
    units = [{'id': uid(number), 'kind': 'uom', 'revision': 1, 'fields': {'symbol': name, 'dimension': 'count', 'precision': 6},
              'target': {'doctype': 'UOM', 'name': name}} for number, name in ((70, 'Explicit material unit'), (71, 'Explicit labor unit'))]
    def component(number, category, unit, amount, numerator, denominator):
        return {'component_id': uid(number), 'cost_type': category, 'source_unit_id': uid(unit),
                'resource_quantity_exact': {'numerator': numerator, 'denominator': denominator},
                'priced_quantity_exact': {'numerator': numerator, 'denominator': denominator}, 'allocated_amount': money(amount)}
    result = {'schema': 'cipher.estimate.result.v1', 'policy': {'currency_exponent': 2},
              'lines': [{'line_id': uid(30), 'included': True, 'extension': money('30.03'), 'cost_code': 'descriptive only',
                         'components': [component(40, 'material', 70, '10.01', '1', '3'), component(41, 'labor', 71, '20.02', '3', '7')]},
                        {'line_id': uid(31), 'included': False, 'extension': money('99.99'),
                         'components': [component(42, 'material', 70, '99.99', '1', '1')]}],
              'adjustments': [{'line_id': uid(50), 'kind': 'indirect', 'amount': money('1.23')},
                              {'line_id': uid(51), 'kind': 'contingency', 'amount': money('0.77')}],
              'direct': money('30.03'), 'indirect': money('1.23'), 'contingency': money('0.77'), 'total': money('32.03')}
    result['output_digest'] = digest(result)
    manifest = {'effect': {'facts': {'qualified_units': units}}}
    acceptance = {'id': uid(60), 'company': company, 'scope_type': 'Company', 'project': None, 'status': 'accepted',
                  'estimate': uid(61), 'estimate_revision': uid(62), 'calculation_snapshot': uid(63), 'currency': 'USD',
                  'manifest': manifest, 'manifest_digest': digest(manifest), 'total': money('32.03'), 'accepted_result': result}
    allocations = []
    for number, source, type_id in ((80, {'kind': 'component', 'line_id': uid(30), 'component_id': uid(40)}, 20),
                                    (81, {'kind': 'component', 'line_id': uid(30), 'component_id': uid(41)}, 21),
                                    (82, {'kind': 'adjustment', 'adjustment_id': uid(50)}, 22),
                                    (83, {'kind': 'adjustment', 'adjustment_id': uid(51)}, 23)):
        allocations.append({'id': uid(number), 'source': source, 'wbs_id': uid(2), 'code_revision_id': uid(10), 'type_revision_id': uid(type_id)})
    return {'acceptance': acceptance, 'wbs_nodes': nodes, 'allocations': allocations, 'resolved_codes': codes, 'resolved_types': types, 'basis_date': day}


def refresh_result(value):
    result = value['acceptance']['accepted_result']
    result['output_digest'] = digest({key: item for key, item in result.items() if key not in {'input_digest', 'output_digest'}})


class ProjectControlPlanTests(unittest.TestCase):
    def test_exact_mixed_components_and_adjustments_preserve_cost_and_rational_quantities(self):
        values = fixture(); original = deepcopy(values)
        plan = core.plan_initial_budget(**values)
        self.assertEqual(values, original)
        self.assertEqual(plan['totals']['total'], {'amount': '32.03', 'currency': 'USD'})
        self.assertEqual([row['amount']['amount'] for row in plan['budget_lines']], ['10.01', '20.02', '1.23', '0.77'])
        self.assertEqual(plan['budget_lines'][0]['source_quantity']['priced_quantity_exact'], {'numerator': '1', 'denominator': '3'})
        self.assertIsNone(plan['budget_lines'][2]['source_quantity'])
        self.assertEqual(plan['budget_lines'][2]['allocation_class'], 'indirect')
        self.assertIsNone(plan['budget_lines'][2]['cost_category'])
        self.assertEqual([r['line_id'] for r in plan['excluded_source_lines']], [uid(31)])
        self.assertEqual(len(plan['source_units']), 2)

    def test_component_identity_is_parent_line_and_component_pair(self):
        values = fixture(); result = values['acceptance']['accepted_result']; money = lambda amount: {'amount': amount, 'currency': 'USD'}
        added = deepcopy(result['lines'][0]); added.update(line_id=uid(32), extension=money('5.00')); added['components'] = [deepcopy(added['components'][0])]
        added['components'][0]['allocated_amount'] = money('5.00'); result['lines'].append(added)
        result['direct'] = money('35.03'); result['total'] = money('37.03'); values['acceptance']['total'] = money('37.03'); refresh_result(values)
        allocation = deepcopy(values['allocations'][0]); allocation.update(id=uid(84), source={'kind': 'component', 'line_id': uid(32), 'component_id': uid(40)})
        values['allocations'].append(allocation)
        plan = core.plan_initial_budget(**values)
        self.assertEqual(len([r for r in plan['budget_lines'] if r['source'].get('component_id') == uid(40)]), 2)

    def test_omitted_source_or_duplicate_split_is_refused(self):
        values = fixture(); values['allocations'].pop()
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)
        values = fixture(); values['allocations'][1]['source'] = deepcopy(values['allocations'][0]['source'])
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)

    def test_excluded_alternative_cannot_replace_an_included_source(self):
        values = fixture(); values['allocations'][0]['source'] = {'kind': 'component', 'line_id': uid(31), 'component_id': uid(42)}
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)

    def test_category_and_adjustment_class_cannot_be_relabelled(self):
        values = fixture(); values['allocations'][1]['type_revision_id'] = uid(20)
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)
        values = fixture(); values['allocations'][3]['type_revision_id'] = uid(22)
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)

    def test_free_text_cost_code_and_summary_allocation_are_refused(self):
        values = fixture(); values['allocations'][0]['code_revision_id'] = 'descriptive only'
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)
        values = fixture(); values['allocations'][0]['wbs_id'] = uid(1)
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)

    def test_rehashed_inconsistent_component_totals_remain_refused(self):
        values = fixture(); values['acceptance']['accepted_result']['lines'][0]['components'][0]['allocated_amount']['amount'] = '10.00'
        refresh_result(values)
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)

    def test_currency_precision_and_original_result_digest_are_required(self):
        values = fixture(); values['acceptance']['accepted_result']['adjustments'][0]['amount']['currency'] = 'EUR'; refresh_result(values)
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)
        values = fixture(); values['acceptance']['accepted_result']['lines'][0]['components'][0]['allocated_amount']['amount'] = '10.010'; refresh_result(values)
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)
        values = fixture(); values['acceptance']['accepted_result']['total']['amount'] = '999.00'
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)

    def test_missing_original_native_unit_manifest_cannot_fund_quantity(self):
        values = fixture(); values['acceptance']['manifest']['effect']['facts']['qualified_units'].pop(); values['acceptance']['manifest_digest'] = digest(values['acceptance']['manifest'])
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)

    def test_cross_company_or_historical_authority_is_not_admission(self):
        values = fixture(); values['resolved_codes'][0]['company'] = 'Another Company'
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)
        values = fixture(); values['resolved_types'][0]['purpose'] = 'historical_read'
        with self.assertRaises(DomainError): core.plan_initial_budget(**values)


class WBSPlanTests(unittest.TestCase):
    def test_topological_order_is_independent_of_input_order(self):
        nodes = fixture()['wbs_nodes']; self.assertEqual(core.validate_wbs_plan(list(reversed(nodes))), nodes)

    def test_cycles_or_foreign_parent_and_scope_smuggling_are_refused(self):
        nodes = fixture()['wbs_nodes']; nodes[0]['parent_id'] = nodes[1]['id']
        with self.assertRaises(DomainError): core.validate_wbs_plan(nodes)
        nodes = fixture()['wbs_nodes']; nodes[1]['parent_id'] = uid(999)
        with self.assertRaises(DomainError): core.validate_wbs_plan(nodes)
        nodes = fixture()['wbs_nodes']; nodes[1]['project'] = 'Unrelated Project'
        with self.assertRaises(DomainError): core.validate_wbs_plan(nodes)

    def test_duplicate_code_and_false_leaf_classification_are_refused(self):
        nodes = fixture()['wbs_nodes']; nodes[1]['code'] = nodes[0]['code'].lower()
        with self.assertRaises(DomainError): core.validate_wbs_plan(nodes)
        nodes = fixture()['wbs_nodes']; nodes[0]['is_leaf'] = True
        with self.assertRaises(DomainError): core.validate_wbs_plan(nodes)

    def test_child_active_interval_cannot_escape_parent(self):
        nodes = fixture()['wbs_nodes']; nodes[0]['active_from'] = '2026-10-15'
        with self.assertRaises(DomainError): core.validate_wbs_plan(nodes)

    def test_fixed_native_targets_and_separate_cost_categories(self):
        definition = fixture()['resolved_types'][0]['revision']['definition']
        definition['native_target']['doctype'] = 'Arbitrary Accounting Dimension'
        with self.assertRaises(DomainError): core.definition('type', definition)
        definition = fixture()['resolved_types'][2]['revision']['definition']; definition['cost_category'] = 'indirect'
        with self.assertRaises(DomainError): core.definition('type', definition)


class AdoptionBoundaryTests(unittest.TestCase):
    def test_exact_award_scope_author_and_budget_identity(self):
        from uuid import uuid5
        effect = {'company': 'Company A', 'project': 'Real Project', 'award_id': uid(200), 'award_revision_id': uid(201), 'controls_plan_digest': 'a' * 64}
        value = {**effect, 'id': str(uuid5(UUID(effect['award_id']), 'initial-budget.v1')), 'author_person': 'AUTHOR'}
        core.validate_adoption_identity('budget', value, effect, 'AUTHOR')
        for field, changed in (('company', 'Company B'), ('project', 'Foreign Project'), ('author_person', 'FORGED'), ('id', uid(202)), ('award_revision_id', uid(203)), ('controls_plan_digest', 'b' * 64)):
            mutation = {**value, field: changed}
            with self.subTest(field=field), self.assertRaises(DomainError):
                core.validate_adoption_identity('budget', mutation, effect, 'AUTHOR')

    def test_reviewed_child_identity_cannot_be_duplicated_inside_award(self):
        from uuid import uuid5
        effect = {'company': 'Company A', 'project': 'Real Project', 'award_id': uid(200), 'award_revision_id': uid(201), 'controls_plan_digest': 'a' * 64}
        common = {**effect, 'id': uid(300), 'author_person': 'AUTHOR', 'budget_version': str(uuid5(UUID(effect['award_id']), 'initial-budget.v1'))}
        for kind, key in (('wbs', 'node'), ('budget_line', 'line')):
            value = {**common, key: {'id': uid(300)}}
            core.validate_adoption_identity(kind, value, effect, 'AUTHOR')
            for mutation in ({**value, 'id': uid(301)}, {**value, 'budget_version': uid(302)}):
                with self.subTest(kind=kind), self.assertRaises(DomainError):
                    core.validate_adoption_identity(kind, mutation, effect, 'AUTHOR')

    def test_current_account_or_company_currency_drift_is_refused(self):
        core.check_admitted_currency(['USD'], 'USD', 'EUR')
        core.check_admitted_currency(['USD'], None, 'USD')
        for currencies, account, company in ((['USD'], 'EUR', 'USD'), (['USD'], None, 'EUR'), ([], None, 'USD')):
            with self.subTest(account=account, company=company), self.assertRaises(DomainError) as error:
                core.check_admitted_currency(currencies, account, company)
            self.assertEqual(error.exception.code, 'cost_source_drift')

    def test_canonical_source_quantities_are_preserved_without_rounding(self):
        self.assertEqual(core.rational({'numerator': '1', 'denominator': '3'}), {'numerator': '1', 'denominator': '3'})
        for value in ({'numerator': '2', 'denominator': '6'}, {'numerator': '-1', 'denominator': '3'}, {'numerator': '1', 'denominator': '0'}):
            with self.subTest(value=value), self.assertRaises(DomainError):core.rational(value)

    def test_published_closed_plan_schema_accepts_actual_producer_shape(self):
        import json
        from pathlib import Path
        from jsonschema import Draft202012Validator, FormatChecker
        schema = json.loads((Path(core.__file__).parent / 'schemas' / 'api-v1.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator({'$ref': '#/$defs/PcInitialPlan', **schema}, format_checker=FormatChecker()).validate(core.plan_initial_budget(**fixture()))


class CalculatorCompatibilityTests(unittest.TestCase):
    def test_actual_mixed_est_calculator_output_adopts_exact_components_and_adjustments(self):
        from cipher_aec.tests.test_estimating_core import fixture as estimating_fixture
        from cipher_aec.estimating.calculation import calculate
        inputs = estimating_fixture()
        result = calculate(inputs)
        values = fixture()
        acceptance = values['acceptance']
        acceptance['accepted_result'] = result
        acceptance['total'] = result['total']
        units = [{**deepcopy(u), 'target': {'doctype': 'UOM', 'name': u['fields']['symbol']}} for u in inputs['unit_manifest']['records'] if u['kind'] == 'uom']
        acceptance['manifest']['effect']['facts']['qualified_units'] = units
        acceptance['manifest_digest'] = digest(acceptance['manifest'])
        equipment = deepcopy(values['resolved_types'][1])
        equipment['revision']['id'] = uid(24)
        equipment['revision']['master_id'] = uid(124)
        equipment['revision']['code'] = 'EQUIPMENT'
        equipment['revision']['definition']['cost_category'] = 'equipment'
        equipment['revision_digest'] = digest(equipment['revision'])
        values['resolved_types'].append(equipment)
        by_category = {r['revision']['definition']['cost_category']: r['revision']['id'] for r in values['resolved_types'] if r['revision']['definition']['allocation_class'] == 'component'}
        by_class = {r['revision']['definition']['allocation_class']: r['revision']['id'] for r in values['resolved_types'] if r['revision']['definition']['allocation_class'] != 'component'}
        allocations = []
        for line in result['lines']:
            for component in line['components']:
                allocations.append({'id': uid(400 + len(allocations)), 'source': {'kind': 'component', 'line_id': line['line_id'], 'component_id': component['component_id']}, 'wbs_id': uid(2), 'code_revision_id': uid(10), 'type_revision_id': by_category[component['cost_type']]})
        for adjustment in result['adjustments']:
            allocations.append({'id': uid(400 + len(allocations)), 'source': {'kind': 'adjustment', 'adjustment_id': adjustment['line_id']}, 'wbs_id': uid(2), 'code_revision_id': uid(10), 'type_revision_id': by_class[adjustment['kind']]})
        values['allocations'] = allocations
        adopted = core.plan_initial_budget(**values)
        self.assertEqual(adopted['totals']['total'], {'amount': '1025.41', 'currency': 'USD'})
        self.assertEqual([r['amount']['amount'] for r in adopted['budget_lines']], ['23.10', '500.00', '400.00', '92.31', '10.00'])
        self.assertEqual(adopted['budget_lines'][0]['source_quantity']['priced_quantity_exact'], result['lines'][0]['components'][0]['priced_quantity_exact'])
        self.assertTrue(all(r['source_quantity'] is None for r in adopted['budget_lines'] if r['allocation_class'] != 'component'))


class NativeIdentityTests(unittest.TestCase):
    def test_sql_case_or_accent_alias_cannot_create_another_resource_identity(self):
        self.assertEqual(core.require_native_identity('Exact Center - CO', 'Exact Center - CO'), 'Exact Center - CO')
        for alias in ('exact center - co', 'EXACT CENTER - CO', 'Éxact Center - CO'):
            with self.subTest(alias=alias), self.assertRaises(DomainError) as raised:
                core.require_native_identity(alias, 'Exact Center - CO')
            self.assertEqual(raised.exception.code, 'not_found')
