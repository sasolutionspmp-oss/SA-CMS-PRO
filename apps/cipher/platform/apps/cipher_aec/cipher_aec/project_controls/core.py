"""Pure exact-cost adoption contracts; no storage, authority grant or repricing."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
from fractions import Fraction
import re
from uuid import UUID, uuid5

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError

COST_CATEGORIES = frozenset({'material', 'labor', 'equipment', 'subcontract', 'other'})
ALLOCATION_CLASSES = frozenset({'component', 'indirect', 'contingency'})
MAX_WBS, MAX_ALLOCATIONS = 500, 5030
PLAN_SCHEMA = 'cipher.project-controls.initial-plan.v1'


def fail(message, field='input', code='invalid_project_controls'):
    raise DomainError(code, message, 422, {'field': field})


def closed(value, required, field):
    if type(value) is not dict or set(value) != set(required):
        fail('Supply exactly the supported fields.', field)
    return value


def identifier(value, field='id'):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        fail('Use a canonical UUID.', field)
    return value


def text(value, field, maximum=140, *, empty=False):
    if type(value) is not str or len(value) > maximum or not empty and not value.strip() or value != value.strip() or any(ord(c) < 32 for c in value):
        fail('Supply bounded text without surrounding whitespace or control characters.', field)
    return value


def code(value, field='code'):
    if type(value) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', value) is None:
        fail('Use a stable code of letters, digits, dots, underscores or dashes.', field)
    return value


def business_date(value, field, *, nullable=False):
    if nullable and value is None:
        return None
    try:
        if type(value) is not str or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except (ValueError, TypeError):
        fail('Use an exact ISO business date.', field)
    return value


def definition(kind, value):
    if type(kind) is not str or kind not in {'code', 'type'}:
        fail('Select a canonical cost code or cost type.', 'kind')
    fields = {'title', 'effective_from', 'effective_until', 'enabled', 'native_target'}
    closed(value, fields | ({'cost_category', 'allocation_class'} if kind == 'type' else set()), 'definition')
    text(value['title'], 'definition.title', 200)
    business_date(value['effective_from'], 'definition.effective_from')
    business_date(value['effective_until'], 'definition.effective_until', nullable=True)
    if value['effective_until'] is not None and value['effective_until'] < value['effective_from']:
        fail('The effective interval ends before it starts.', 'definition.effective_until')
    if type(value['enabled']) is not bool:
        fail('Enablement must be an explicit boolean.', 'definition.enabled')
    target = closed(value['native_target'], {'doctype', 'name'}, 'definition.native_target')
    if target['doctype'] != ('Cost Center' if kind == 'code' else 'Account'):
        fail('Use the fixed native Cost Center or expense Account target profile.', 'definition.native_target.doctype')
    text(target['name'], 'definition.native_target.name')
    if kind == 'type':
        category, allocation = value['cost_category'], value['allocation_class']
        if type(allocation) is not str or allocation not in ALLOCATION_CLASSES or (allocation == 'component' and (type(category) is not str or category not in COST_CATEGORIES)) or (allocation != 'component' and category is not None):
            fail('Keep the five estimate cost categories separate from indirect/contingency allocations.', 'definition.cost_category')
    return deepcopy(value)


def validate_wbs_plan(nodes):
    if type(nodes) is not list or not 1 <= len(nodes) <= MAX_WBS:
        fail('Supply one through 500 explicit WBS nodes.', 'wbs_nodes')
    by_id, codes = {}, set()
    fields = {'id', 'code', 'parent_id', 'title', 'is_leaf', 'accountable_person', 'phase', 'active_from', 'active_until'}
    for value in nodes:
        closed(value, fields, 'wbs_node')
        identifier(value['id'], 'wbs_node.id'); code(value['code'], 'wbs_node.code')
        if value['id'] in by_id or value['code'].casefold() in codes:
            fail('WBS identities and Project codes must be unique.', 'wbs_node.code')
        text(value['title'], 'wbs_node.title', 200); text(value['phase'], 'wbs_node.phase', 64, empty=True)
        if type(value['is_leaf']) is not bool:
            fail('Leaf classification must be an explicit boolean.', 'wbs_node.is_leaf')
        if value['parent_id'] is not None:
            identifier(value['parent_id'], 'wbs_node.parent_id')
        if value['accountable_person'] is not None:
            text(value['accountable_person'], 'wbs_node.accountable_person')
        for field in ('active_from', 'active_until'):
            business_date(value[field], 'wbs_node.' + field, nullable=True)
        if value['active_from'] and value['active_until'] and value['active_until'] < value['active_from']:
            fail('The WBS active interval is reversed.', 'wbs_node.active_until')
        by_id[value['id']] = deepcopy(value); codes.add(value['code'].casefold())
    children = {key: [] for key in by_id}
    for key, value in by_id.items():
        parent = value['parent_id']
        if parent is not None:
            if parent not in by_id or parent == key:
                fail('A WBS parent must be a different node in this exact plan.', 'wbs_node.parent_id')
            children[parent].append(key)
            for field, comparison in (('active_from', lambda a, b: a >= b), ('active_until', lambda a, b: a <= b)):
                if by_id[parent][field] and (not value[field] or not comparison(value[field], by_id[parent][field])):
                    fail('A child active interval must fit its parent.', 'wbs_node.' + field)
    depths = {}
    for key in by_id:
        path, current = [], key
        while current is not None and current not in depths:
            if current in path or len(path) >= 64:
                fail('WBS ancestry must be acyclic and bounded to 64 levels.', 'wbs_node.parent_id')
            path.append(current); current = by_id[current]['parent_id']
        depth = depths[current] + 1 if current is not None else 0
        for visited in reversed(path):
            depths[visited] = depth; depth += 1
    for key, value in by_id.items():
        if value['is_leaf'] != (not children[key]):
            fail('Leaf/summary classification must match the actual tree.', 'wbs_node.is_leaf')
    return [by_id[key] for key in sorted(by_id, key=lambda key: (depths[key], key))]


def _money(value, currency, exponent):
    closed(value, {'amount', 'currency'}, 'amount')
    amount = value['amount']
    pattern = r'(?:0|[1-9][0-9]*)' + (r'\.[0-9]{' + str(exponent) + '}' if exponent else '')
    if value['currency'] != currency or type(amount) is not str or re.fullmatch(pattern, amount) is None or len(amount) > 32:
        fail('Preserve an exact nonnegative amount in the accepted currency precision.', 'amount')
    return Decimal(amount)


def rational(value):
    closed(value, {'numerator', 'denominator'}, 'source_quantity')
    numerator, denominator = value['numerator'], value['denominator']
    if (type(numerator) is not str or type(denominator) is not str or len(numerator) > 100 or len(denominator) > 100
            or re.fullmatch(r'(0|[1-9][0-9]*)', numerator) is None or re.fullmatch(r'[1-9][0-9]*', denominator) is None):
        fail('Preserve an exact nonnegative canonical rational source quantity.', 'source_quantity')
    fraction = Fraction(int(numerator), int(denominator))
    if str(fraction.numerator) != numerator or str(fraction.denominator) != denominator:
        fail('Preserve the reduced canonical source rational.', 'source_quantity')
    return deepcopy(value)


def _authorities(values, kind, company, basis_date):
    if type(values) is not list or len(values) > 1000:
        fail('Use a bounded exact cost authority set.', 'resolved_' + kind)
    result = {}
    for value in values:
        if type(value) is not dict or value.get('kind') != kind or value.get('company') != company or value.get('basis_date') != basis_date or value.get('purpose') != 'award.initial-budget.v1':
            fail('The resolved cost authority must match the exact Company, date and new-effect purpose.', 'resolved_' + kind)
        revision = value['revision']; identifier(revision['id'])
        if value['revision_digest'] != digest(revision) or revision['id'] in result:
            fail('Cost revision identities and digests must be exact and unique.', 'resolved_' + kind)
        definition(kind, revision['definition'])
        if revision['company'] != company or revision['kind'] != kind or not revision['definition']['enabled']:
            fail('Use an enabled cost revision in the exact Company.', 'resolved_' + kind)
        result[revision['id']] = deepcopy(value)
    return result


def plan_initial_budget(*, acceptance, wbs_nodes, allocations, resolved_codes, resolved_types, basis_date=None):
    """Adopt accepted component allocations; never calculate a selling price."""
    if type(acceptance) is not dict:
        fail('Use the exact accepted baseline.', 'acceptance')
    company = text(acceptance['company'], 'company')
    if acceptance.get('scope_type') != 'Company' or acceptance.get('project') is not None or acceptance.get('status') != 'accepted':
        fail('Initial award cost adoption requires an exact accepted Company baseline.', 'acceptance')
    basis_date = business_date(basis_date or (resolved_codes[0]['basis_date'] if resolved_codes else None), 'basis_date')
    result, currency = acceptance['accepted_result'], acceptance['currency']
    if type(currency) is not str or re.fullmatch('[A-Z]{3}', currency) is None:
        fail('Preserve the accepted exact currency.', 'acceptance.currency')
    if type(result.get('lines')) is not list or len(result['lines']) > 100 or type(result.get('adjustments')) is not list or len(result['adjustments']) > 30:
        fail('Use a bounded accepted line/adjustment result.', 'acceptance')
    exponent = result['policy']['currency_exponent']
    if type(exponent) is not int or not 0 <= exponent <= 6:
        fail('The accepted currency precision is unqualified.', 'acceptance')
    if result.get('schema') != 'cipher.estimate.result.v1' or digest({k: v for k, v in result.items() if k not in {'input_digest', 'output_digest'}}) != result['output_digest']:
        fail('The accepted result digest does not match its exact facts.', 'acceptance')
    if digest(acceptance['manifest']) != acceptance['manifest_digest']:
        fail('The accepted baseline manifest lost integrity.', 'acceptance')
    for field in ('id', 'estimate', 'estimate_revision', 'calculation_snapshot'):
        identifier(acceptance[field], 'acceptance.' + field)
    nodes = validate_wbs_plan(wbs_nodes); node_map = {n['id']: n for n in nodes}
    codes = _authorities(resolved_codes, 'code', company, basis_date)
    types = _authorities(resolved_types, 'type', company, basis_date)
    sources, excluded, line_ids, source_unit_ids = {}, [], set(), set()
    totals = {key: _money(result[key], currency, exponent) for key in ('direct', 'indirect', 'contingency', 'total')}
    sums = {'direct': Decimal(0), 'indirect': Decimal(0), 'contingency': Decimal(0)}
    with localcontext() as context:
        context.prec = 100
        for line in result['lines']:
            identifier(line['line_id']); amount = _money(line['extension'], currency, exponent)
            if line['line_id'] in line_ids or type(line['included']) is not bool:
                fail('Accepted estimate lines must have unique identities and explicit inclusion.', 'acceptance.lines')
            line_ids.add(line['line_id']); component_ids, component_sum = set(), Decimal(0)
            if type(line['components']) is not list or not 1 <= len(line['components']) <= 50:
                fail('Use a bounded accepted component set.', 'acceptance.components')
            for component in line['components']:
                component_id = identifier(component['component_id'])
                if component_id in component_ids or type(component['cost_type']) is not str or component['cost_type'] not in COST_CATEGORIES:
                    fail('Accepted component identity or cost category is invalid.', 'acceptance.components')
                component_ids.add(component_id); component_sum += _money(component['allocated_amount'], currency, exponent)
                if line['included']:
                    source_unit_ids.add(identifier(component['source_unit_id']))
                    rational(component['resource_quantity_exact']); rational(component['priced_quantity_exact'])
                    source = {'kind': 'component', 'line_id': line['line_id'], 'component_id': component_id}
                    sources[digest(source)] = {'source': source, 'amount': deepcopy(component['allocated_amount']), 'cost_category': component['cost_type'],
                        'allocation_class': 'component', 'source_quantity': {key: deepcopy(component[key]) for key in ('source_unit_id', 'resource_quantity_exact', 'priced_quantity_exact')}}
            if component_sum != amount:
                fail('Accepted component allocations must equal their parent extension exactly.', 'acceptance.components')
            if line['included']:
                sums['direct'] += amount
            else:
                excluded.append({'line_id': line['line_id'], 'digest': digest(line)})
        for adjustment in result['adjustments']:
            identifier(adjustment['line_id']); kind = adjustment['kind']
            if type(kind) is not str or kind not in {'indirect', 'contingency'}:
                fail('Preserve a supported accepted adjustment class.', 'acceptance.adjustments')
            source = {'kind': 'adjustment', 'adjustment_id': adjustment['line_id']}; key = digest(source)
            if key in sources:
                fail('Adjustment source identities must be unique.', 'acceptance.adjustments')
            sums[kind] += _money(adjustment['amount'], currency, exponent)
            sources[key] = {'source': source, 'amount': deepcopy(adjustment['amount']), 'cost_category': None, 'allocation_class': kind, 'source_quantity': None}
        if any(sums[key] != totals[key] for key in sums) or sum(sums.values()) != totals['total'] or acceptance['total'] != result['total']:
            fail('Accepted direct, indirect, contingency and total costs must reconcile exactly.', 'acceptance.total')
    if type(allocations) is not list or len(allocations) != len(sources) or len(allocations) > MAX_ALLOCATIONS:
        fail('Map every included component and each adjustment exactly once.', 'allocations')
    lines, seen, allocation_ids = [], set(), set()
    for allocation in allocations:
        closed(allocation, {'id', 'source', 'wbs_id', 'code_revision_id', 'type_revision_id'}, 'allocation')
        identifier(allocation['id']); key = digest(allocation['source'])
        if allocation['id'] in allocation_ids or key in seen or key not in sources:
            fail('Each original cost source and budget line identity is adopted exactly once.', 'allocation.source')
        identifier(allocation['wbs_id']); identifier(allocation['code_revision_id']); identifier(allocation['type_revision_id'])
        if allocation['wbs_id'] not in node_map or not node_map[allocation['wbs_id']]['is_leaf']:
            fail('Fund only an explicit leaf in this exact WBS plan.', 'allocation.wbs_id')
        if allocation['code_revision_id'] not in codes or allocation['type_revision_id'] not in types:
            fail('Map only explicitly resolved canonical Company cost revisions.', 'allocation')
        source, cost_type = sources[key], types[allocation['type_revision_id']]['revision']['definition']
        if (source['allocation_class'], source['cost_category']) != (cost_type['allocation_class'], cost_type['cost_category']):
            fail('Canonical cost type must preserve the accepted source category and allocation class.', 'allocation.type_revision_id')
        lines.append({**deepcopy(allocation), **deepcopy(source)})
        seen.add(key); allocation_ids.add(allocation['id'])
    if seen != set(sources):
        fail('Every included accepted cost source must be funded once.', 'allocations')
    used_codes = {a['code_revision_id'] for a in allocations}; used_types = {a['type_revision_id'] for a in allocations}
    if used_codes != set(codes) or used_types != set(types):
        fail('The authority set must equal the exact mapped cost revision union.', 'resolved_costs')
    units = {}
    for unit in acceptance['manifest']['effect']['facts']['qualified_units']:
        identifier(unit['id'])
        if unit['id'] in units or unit.get('kind') != 'uom' or unit.get('target', {}).get('doctype') != 'UOM':
            fail('The accepted native unit identity manifest is inconsistent.', 'acceptance.units')
        units[unit['id']] = unit
    if not source_unit_ids.issubset(units):
        fail('Every funded source quantity requires its original accepted native unit identity.', 'acceptance.units')
    return {'schema': PLAN_SCHEMA, 'company': company, 'basis_date': basis_date,
        'acceptance': {'id': acceptance['id'], 'digest': digest(acceptance), 'estimate_id': acceptance['estimate'], 'revision_id': acceptance['estimate_revision'],
                       'snapshot_id': acceptance['calculation_snapshot'], 'manifest_digest': acceptance['manifest_digest']},
        'wbs_nodes': nodes, 'allocations': sorted(deepcopy(allocations), key=lambda row: row['id']),
        'resolved_codes': [codes[key] for key in sorted(codes)], 'resolved_types': [types[key] for key in sorted(types)],
        'budget_lines': sorted(lines, key=lambda row: row['id']), 'excluded_source_lines': sorted(excluded, key=lambda row: row['line_id']),
        'source_units': [deepcopy(units[key]) for key in sorted(source_unit_ids)],
        'currency': currency, 'currency_exponent': exponent, 'totals': {key: deepcopy(result[key]) for key in totals}}


def validate_adoption_identity(kind, value, effect, author_person):
    """Bind controller payloads to one reviewed award, not ambient trust."""
    if value['company'] != effect['company'] or value['project'] != effect['project'] or value['author_person'] != author_person:
        fail('Adopted scope/author must equal the active exact award/current person.', code='controls_integrity')
    budget_id = str(uuid5(UUID(effect['award_id']), 'initial-budget.v1'))
    if (kind == 'budget' and (value['id'] != budget_id or value['award_id'] != effect['award_id'] or value['award_revision_id'] != effect['award_revision_id'])
            or kind != 'budget' and value['budget_version'] != budget_id
            or kind == 'wbs' and value['id'] != value['node']['id']
            or kind == 'budget_line' and value['id'] != value['line']['id']):
        fail('Initial adoption identities must equal the reviewed deterministic budget/child identities.', code='controls_integrity')
    if value['controls_plan_digest'] != effect['controls_plan_digest']:
        fail('Adopt only the exact reviewed cost subplan.', code='controls_integrity')


def check_admitted_currency(currencies, account_currency, company_currency):
    if currencies != [account_currency or company_currency]:
        from cipher_aec.api.errors import DomainError
        raise DomainError('cost_source_drift', 'The current expense Account/Company Currency differs from its admitted union. Retry this same intent in a fresh transaction.', 409)


def require_native_identity(requested, canonical):
    """One physical native row has one spelling in sorted resource plans."""
    if type(requested) is not str or type(canonical) is not str or requested != canonical:
        raise DomainError('not_found', 'This native cost target is not available.', 404)
    return canonical
