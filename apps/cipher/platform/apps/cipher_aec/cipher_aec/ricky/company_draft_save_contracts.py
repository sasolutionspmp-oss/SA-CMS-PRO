"""Stage C mapping: pure exact values, never authority or a second writer."""
from copy import deepcopy
from fractions import Fraction
from uuid import NAMESPACE_URL, uuid5
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from .company_proposal_contracts import validate_preparation

SCHEMA = 'cipher.ricky.company.draft-save.v1'
MAPPING_VERSION = '1'
CLASSIFICATION = 'unverified-author-suggestion'
PREFIX = 'Unverified author suggestion: '
COMMANDS = {'aec.scope.draft': ('ricky.company.proposal.save-scope.v1', 'commercial.proposal.revise', 'commercial'),
            'aec.estimate.draft': ('ricky.company.proposal.save-estimate.v1', 'estimate.calculate.v1', 'estimate')}

def refuse(message, code='draft_save_conflict', status=409):
    raise DomainError(code, message, status)

def application_id(proposal_id):
    return str(uuid5(NAMESPACE_URL, 'cipher:ricky:company:draft-save:v1:' + proposal_id))

def decimal_amount(numerator, denominator, precision):
    from cipher_aec.migrations.validation import ManifestError
    try:
        if type(numerator) is not str or type(denominator) is not str or type(precision) is not int or not 0 <= precision <= 12:
            raise ValueError
        value = Fraction(int(numerator), int(denominator))
        if value < 0 or int(denominator) <= 0: raise ValueError
        rest, twos, fives = value.denominator, 0, 0
        while rest % 2 == 0: rest //= 2; twos += 1
        while rest % 5 == 0: rest //= 5; fives += 1
        scale = max(twos, fives)
        if rest != 1 or scale > precision: raise ValueError
        digits = str(value.numerator * (10**scale // value.denominator))
        text = digits if not scale else (digits.zfill(scale+1)[:-scale] + '.' + digits.zfill(scale+1)[-scale:]).rstrip('0').rstrip('.')
        from cipher_aec.migrations.validation import decimal_quantity
        decimal_quantity(text, 'suggestion.quantity')
        return text
    except (ValueError, ZeroDivisionError, OverflowError, ManifestError):
        refuse('The prepared rational requires an exact supported decimal; rounding is unavailable.', 'unsupported_draft_quantity', 422)

def citation_union(existing, references, *, commercial=False):
    # Saved EST snapshots contain canonical citation DTOs; authored command
    # inputs require only the exact closed locator/checksum reference.
    result = deepcopy(existing) if commercial else [
        {key:row[key] for key in ('revision_id','page','excerpt_sha256','source_sha256')} for row in existing]
    seen = {}
    for row in result:
        key = row['revision_id'], row['page']
        if key in seen: refuse('Duplicate original citation locator.')
        seen[key] = row
    for reference in references:
        row = {key: reference[key] for key in ('revision_id','page','excerpt_sha256','source_sha256')}
        key = row['revision_id'], row['page']
        if key in seen:
            if any(seen[key].get(k) != row[k] for k in ('excerpt_sha256','source_sha256')): refuse('Conflicting source bytes at one citation locator.')
        else:
            if commercial: row.update(purpose='Human-reviewed unverified author suggestion', permission_basis='Current canonical source authorization')
            result.append(row); seen[key] = row
    if len(result) > (30 if commercial else 8): refuse('The saved citation union exceeds the canonical input bound.', 'draft_save_limit', 422)
    return result

def scope_composition(proposal_id, original, preparation):
    from cipher_aec.commercial.contracts import composition
    result = deepcopy(original)
    sections = result['sections']
    for index, row in enumerate(preparation['proposed_fields']['sections']):
        title = PREFIX + row['heading']
        if len(title) > 140: refuse('The visibly unverified section title exceeds 140 characters.', 'draft_save_limit', 422)
        sections.append({'id':str(uuid5(NAMESPACE_URL, f'cipher:ricky:{proposal_id}:scope:{index}')), 'kind':'scope', 'title':title, 'text':row['text']})
    for index, claim in enumerate(preparation['unverified_claims']):
        sections.append({'id':str(uuid5(NAMESPACE_URL, f'cipher:ricky:{proposal_id}:claim:{index}')), 'kind':'assumption',
            'title':'Unverified author statement', 'text':claim})
    if len({row['id'] for row in sections}) != len(sections): refuse('Suggestion section identity collides with an existing section.')
    result['source_references'] = citation_union(result.get('source_references', []), preparation['verified_source_references'], commercial=True)
    return composition(result)

def derive(proposal, run, originals):
    """Caller supplies the independently authorized original canonical objects."""
    validate_preparation(run, proposal['preparation'], originals=originals, require_citations=True)
    action, prepared = proposal['action'], proposal['preparation']
    arguments = run['request']['arguments']
    if action == 'aec.scope.draft':
        revision = originals['commercial','proposal-revision',arguments['proposal_revision_id']]
        payload = {'proposal_id':revision['proposal'], 'expected_revision':revision['revision_number'],
            'expected_native_fingerprint':revision['native_fingerprint'],
            'composition':scope_composition(proposal['id'],revision['composition'],prepared)}
    elif action == 'aec.estimate.draft':
        revision = originals['estimate','revision',arguments['base_revision_id']]
        snapshot = originals['estimate','snapshot',revision['calculation_snapshot']]
        inputs = snapshot['inputs']; lines = deepcopy(inputs['lines'])
        by_id = {row['line_id']:row for row in lines}
        if len(by_id) != len(lines): refuse('Original authored line identity is ambiguous.')
        for selected in prepared['proposed_fields']['quantity_selections']:
            line = originals['estimate','line',selected['line_record_id']]
            authored = by_id.get(line['line_id'])
            if line['estimate_revision'] != revision['id'] or authored != line['authored']: refuse('The target line differs from the original snapshot.')
            quantity = selected['quantity']
            if quantity['target_unit_id'] != authored['quantity']['unit_id']: refuse('The selected target unit changed.')
            if quantity['quantity_basis'] == 'after-takeoff-waste-v1' and any(int(c['waste_fraction']['numerator']) for c in line['calculated']['components']):
                refuse('After-takeoff-waste quantities cannot receive target component waste again.')
            authored['quantity']['amount'] = decimal_amount(quantity['numerator'],quantity['denominator'],authored['quantity']['precision'])
        conversions = []
        for definition in inputs['unit_manifest']['unit_conversions']:
            matches = [value['id'] for (domain,kind,_),value in originals.items() if domain=='estimate' and kind=='conversion' and value['definition']==definition]
            if len(matches) != 1: refuse('The original exact conversion revision is unavailable.')
            conversions.extend(matches)
        notes = [inputs['basis_description']]
        if prepared['proposed_fields']['notes']: notes.append('Unverified author suggestion: ' + prepared['proposed_fields']['notes'])
        notes.extend('Unverified author statement: ' + claim for claim in prepared['unverified_claims'])
        basis = '; '.join(notes)
        if len(basis)>2000: refuse('The retained basis and unverified notes exceed 2000 characters.', 'draft_save_limit', 422)
        from cipher_aec.estimating.contracts import visible
        visible(basis,'basis_description',2000)
        payload = {'estimate_id':revision['estimate'],'expected_revision':revision['id'],'lines':lines,'adjustments':deepcopy(inputs['adjustments']),
            'conversion_ids':sorted(set(conversions)),'basis_description':basis,
            'basis_citations':citation_union(inputs['basis_citations'],prepared['verified_source_references'])}
    else: refuse('Unsupported suggestion action.')
    return payload

def binding(proposal, payload):
    return {'proposal_id':proposal['id'],'expected_version':proposal['version'],'expected_content_digest':proposal['content_digest'],
        'mapping_version':MAPPING_VERSION,'expected_payload_digest':digest(payload)}

def check_binding(value, proposal, payload):
    expected = binding(proposal,payload)
    if type(value) is not dict or set(value) != set(expected) or any(type(value[k]) is not type(v) or value[k] != v for k,v in expected.items()):
        refuse('The reviewed suggestion or canonical payload changed.', 'stale_draft_save', 412)
