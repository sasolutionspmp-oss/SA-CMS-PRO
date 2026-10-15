"""Exact FIN-01 foundations; no certification, billing, or accounting authority.

Floor snapshots are a future FIN-03 integration contract, not client declarations.
The production service deliberately has no qualified floor reader in FIN-01.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from uuid import UUID

from cipher_aec.api.errors import DomainError

MAX_AMOUNT = Decimal('10000000000000')


def fail(message, field='input', code='invalid_contract', status=422):
    raise DomainError(code, message, status, {'field': field})


def closed(value, required, optional=(), path='input'):
    if type(value) is not dict or set(value) != set(required) | (set(value) & set(optional)):
        fail('Supply exactly the supported construction contract fields.', path)
    return value


def visible(value, path, maximum=200, empty=False):
    if type(value) is not str or len(value) > maximum or (not empty and not value.strip()) or any(ord(c) < 32 for c in value):
        fail('Supply bounded visible text.', path)
    return value


def identifier(value, path='id'):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError):
        fail('Supply a canonical immutable UUID.', path)
    return value


def exact(value, path, precision=12, positive=False):
    if type(value) is not str or not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', value) or len(value) > 50:
        fail('Use a nonnegative exact decimal string, without exponent or binary float.', path)
    try:
        amount = Decimal(value)
    except InvalidOperation:
        fail('Use a finite decimal string.', path)
    if amount > MAX_AMOUNT or -amount.as_tuple().exponent > precision or positive and amount == 0:
        fail('The exact value exceeds its bound or declared precision.', path)
    return amount


def money(value, currency, exponent, path='money', positive=False):
    closed(value, {'amount', 'currency'}, path=path)
    if value['currency'] != currency:
        fail('Money must use the immutable contract currency.', path + '.currency')
    return exact(value['amount'], path + '.amount', exponent, positive)


def business_date(value, path):
    try:
        if type(value) is not str or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        fail('Use an exact YYYY-MM-DD business date.', path)
    return value


def definition(value, exponent):
    closed(value, {'number', 'kind', 'direction', 'party_type', 'party', 'currency', 'original_value'})
    visible(value['number'], 'number', 140)
    if type(value['kind']) is not str or value['kind'] not in {'prime', 'subcontract', 'consultant', 'service'}:
        fail('Choose an explicit construction agreement kind.', 'kind')
    if type(value['direction']) is not str or value['direction'] not in {'receivable', 'payable'} or value['party_type'] != {'receivable': 'Customer', 'payable': 'Supplier'}[value['direction']]:
        fail('Receivable contracts require a native Customer; payable contracts require a native Supplier.', 'party_type')
    if value['kind'] == 'prime' and value['direction'] != 'receivable' or value['kind'] == 'subcontract' and value['direction'] != 'payable':
        fail('Prime contracts are receivable and construction subcontracts are payable.', 'direction')
    visible(value['party'], 'party', 140)
    money(value['original_value'], value['currency'], exponent, 'original_value', positive=True)
    return value


def terms(value):
    closed(value, {'billing_method', 'effective_date', 'end_date', 'terms_text'})
    if type(value['billing_method']) is not str or value['billing_method'] not in {'lump_sum', 'unit_price', 'cost_reimbursable', 'time_and_material'}:
        fail('Declare an explicit billing method.', 'billing_method')
    business_date(value['effective_date'], 'effective_date')
    if value['end_date'] is not None:
        business_date(value['end_date'], 'end_date')
        if value['end_date'] < value['effective_date']:
            fail('The agreement end cannot precede its effective date.', 'end_date')
    visible(value['terms_text'], 'terms_text', 8000)
    return value


def retainage(value, currency, exponent):
    closed(value, {'basis', 'tiers', 'cap', 'effective_date', 'rounding', 'reduction_conditions', 'release_conditions', 'approval_basis'})
    if type(value['basis']) is not str or value['basis'] not in {'gross_earned', 'installed_work', 'installed_plus_eligible_stored'}:
        fail('Retainage requires an explicit earned-value basis.', 'retainage.basis')
    if value['rounding'] != 'HALF_UP':
        fail('This foundation supports explicit HALF_UP currency rounding only.', 'retainage.rounding')
    business_date(value['effective_date'], 'retainage.effective_date')
    if value['cap'] is not None:
        money(value['cap'], currency, exponent, 'retainage.cap')
    if type(value['tiers']) is not list or not 1 <= len(value['tiers']) <= 8:
        fail('Supply one through eight explicit retainage tiers.', 'retainage.tiers')
    previous = Decimal(0)
    for index, tier in enumerate(value['tiers']):
        closed(tier, {'up_to', 'rate'}, path='retainage.tiers[]')
        if exact(tier['rate'], 'retainage.rate') > 1:
            fail('A retainage rate must be a fraction from zero through one.', 'retainage.rate')
        if tier['up_to'] is None:
            if index != len(value['tiers']) - 1:
                fail('Only the last tier may have an open upper bound.', 'retainage.tiers')
        else:
            upper = money(tier['up_to'], currency, exponent, 'retainage.up_to', positive=True)
            if upper <= previous or index == len(value['tiers']) - 1:
                fail('Tier bounds must increase and the final tier must be open.', 'retainage.tiers')
            previous = upper
    for field in ('reduction_conditions', 'release_conditions', 'approval_basis'):
        visible(value[field], 'retainage.' + field, 2000)
    return value


def sov(lines, currency, exponent, contract_cap, units, policy):
    if type(lines) is not list or not 1 <= len(lines) <= 100:
        fail('Supply one through 100 stable SOV lines.', 'lines')
    total, identities, codes = Decimal(0), set(), set()
    for line in lines:
        closed(line, {'line_id', 'item_code', 'description', 'quantity', 'scheduled_amount', 'cost_code', 'stored_material_eligible', 'source_line_id'})
        identifier(line['line_id'], 'line_id')
        visible(line['item_code'], 'item_code', 100)
        if line['line_id'] in identities or line['item_code'] in codes:
            fail('SOV line identities and item codes must be unique in a version.', 'lines')
        identities.add(line['line_id']); codes.add(line['item_code'])
        visible(line['description'], 'description', 1000)
        visible(line['cost_code'], 'cost_code', 140)
        if line['source_line_id'] is not None:
            identifier(line['source_line_id'], 'source_line_id')
        closed(line['quantity'], {'amount', 'unit_id', 'precision'}, path='quantity')
        q = line['quantity']; identifier(q['unit_id'], 'quantity.unit_id')
        unit = units.get(q['unit_id'])
        if not unit or type(q['precision']) is not int or q['precision'] != unit['fields']['precision']:
            fail('An SOV quantity requires its exact qualified native unit and precision.', 'quantity')
        exact(q['amount'], 'quantity.amount', q['precision'], positive=True)
        total += money(line['scheduled_amount'], currency, exponent, 'scheduled_amount')
        if type(line['stored_material_eligible']) is not bool:
            fail('Stored-material eligibility must be an explicit boolean.', 'stored_material_eligible')
        if line['stored_material_eligible'] and policy['basis'] == 'installed_work':
            fail('Stored-material eligibility conflicts with the installed-work retainage basis.', 'stored_material_eligible')
    if total > money(contract_cap, currency, exponent, 'contract_cap'):
        fail('The aggregate SOV amount exceeds the contract cap.', 'lines', 'contract_cap_exceeded', 409)
    return {'amount': format(total, f'.{exponent}f'), 'currency': currency}


@dataclass(frozen=True)
class FloorSnapshot:
    """Only a future registered server reader can supply this authority.

    Test injection exercises validation and never makes a provider qualified.
    """
    contract_id: str
    contract_revision: str
    sov_revision: str
    provider: str
    provider_version: str
    source_watermark: str
    currency: str
    lines: tuple
    correction_authority: str | None = None


def preserve_accepted(previous, proposed, *, contract_id, revision_id, sov_id, currency, floor=None):
    old = {line['line_id']: line for line in previous}
    new = {line['line_id']: line for line in proposed}
    if floor is not None:
        if not isinstance(floor, FloorSnapshot) or (floor.contract_id, floor.contract_revision, floor.sov_revision, floor.currency) != (contract_id, revision_id, sov_id, currency):
            fail('Certified floor authority must bind this exact accepted baseline.', 'floor', 'unqualified_floor', 409)
        for key in ('provider', 'provider_version', 'source_watermark'):
            visible(getattr(floor, key), 'floor.' + key, 200)
        bound = {}
        for row in floor.lines:
            closed(row, {'line_id', 'amount', 'quantity', 'unit_id'}, path='floor.lines')
            identifier(row['line_id'], 'floor.line_id')
            if row['line_id'] in bound or row['line_id'] not in old:
                fail('Floor lines must be unique accepted line identities.', 'floor.lines', 'unqualified_floor', 409)
            exact(row['amount'], 'floor.amount'); exact(row['quantity'], 'floor.quantity')
            if row['unit_id'] != old[row['line_id']]['quantity']['unit_id']:
                fail('Certified floors cannot change their native unit basis.', 'floor.unit_id', 'unqualified_floor', 409)
            bound[row['line_id']] = row
        if set(bound) != set(old):
            fail('The floor provider must cover every accepted line.', 'floor.lines', 'unqualified_floor', 409)
    else:
        bound = None
    for line_id, before in old.items():
        after = new.get(line_id)
        if before['scheduled_amount']['currency'] != currency or after is not None and after['scheduled_amount']['currency'] != currency:
            fail('Accepted SOV currency cannot change.', 'lines.currency', 'corrective_process_required', 409)
        # Identity and basis changes require a future governed correction, even
        # when a qualified certified amount happens to be zero.
        if after is None or any(after[key] != before[key] for key in ('item_code', 'source_line_id', 'cost_code', 'stored_material_eligible')) or after['quantity']['unit_id'] != before['quantity']['unit_id'] or after['quantity']['precision'] != before['quantity']['precision']:
            fail('An accepted line cannot be removed, relabeled, or moved to another obligation basis.', 'lines', 'corrective_process_required', 409)
        amount_floor = bound[line_id]['amount'] if bound else before['scheduled_amount']['amount']
        quantity_floor = bound[line_id]['quantity'] if bound else before['quantity']['amount']
        if exact(after['scheduled_amount']['amount'], 'amount') < exact(amount_floor, 'floor.amount') or exact(after['quantity']['amount'], 'quantity') < exact(quantity_floor, 'floor.quantity'):
            fail('A cap cannot fall below its authoritative certified/billed floor; without a qualified reader preserve the accepted cap.', 'lines', 'certified_floor_required', 409)
        if bound and (exact(after['scheduled_amount']['amount'], 'amount') < exact(before['scheduled_amount']['amount'], 'old.amount') or exact(after['quantity']['amount'], 'quantity') < exact(before['quantity']['amount'], 'old.quantity')) and not floor.correction_authority:
            fail('Accepted cap reductions require explicit governed correction authority.', 'floor.correction_authority', 'corrective_process_required', 409)
    return True
