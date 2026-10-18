"""Closed, bounded authored closeout records; no commissioning automation."""
from cipher_aec.field.contracts import (
    closed, text, identifier, checksum, day, timestamp, sequence,
    source_list, captured_source, strip_source,
)
from cipher_aec.api.errors import DomainError

KINDS = {
    'package': 'Cipher Closeout Package',
    'package_revision': 'Cipher Closeout Package Revision',
    'commissioning_requirement': 'Cipher Commissioning Requirement',
    'requirement': 'Cipher Closeout Requirement',
    'test_result': 'Cipher Test Result',
    'asset_handover': 'Cipher Asset Handover',
    'decision': 'Cipher Closeout Decision',
    'turnover': 'Cipher Turnover Revision',
}
READ, WRITE, CHECK, ACCEPT = ('closeout.' + a for a in ('read', 'write', 'check', 'accept'))
ABILITIES = frozenset((READ, WRITE, CHECK, ACCEPT))
CATEGORIES = ('commissioning', 'punch', 'om', 'warranty', 'training', 'asset_handover')
REQUIREMENTS = frozenset(('commissioning_requirement', 'requirement'))
RESULTS = frozenset(('test_result', 'asset_handover'))
LINKS = frozenset(('engineering_check', 'document_adoption', 'quality_closure'))
NO_EFFECTS = {k: False for k in (
    'engineering_approval', 'professional_seal', 'regulatory_approval',
    'operating_authority', 'contract_change', 'budget_change', 'procurement_change',
    'invoice_change', 'financial_posting', 'award_execution', 'external_transmission',
    'owner_acceptance', 'asset_capitalization', 'automated_test_execution',
)}
BASE = {'id', 'company', 'project', 'scope_type', 'author_person', 'author_user', 'created_at', 'status'}
HEADER = {'number', 'revision_number', 'current_revision', 'result_heads', 'accepted_results', 'turnover_head', 'accepted_turnover'}
REVISION = {'parent_id', 'revision_number', 'predecessor', 'definition', 'requirements', 'amendment_of', 'amendment_reason', 'no_effects'}
REQUIREMENT = {'parent_id', 'package_revision', 'revision_number', 'predecessor', 'item_id', 'title', 'category', 'required', 'criteria', 'no_effects'}
RESULT = {'parent_id', 'package_revision', 'requirement_id', 'requirement_digest', 'predecessor', 'definition', 'evidence', 'links', 'no_effects'}
DECISION = {'parent_id', 'package_revision', 'action', 'subject_kind', 'subject_id', 'subject_digest', 'comment', 'no_effects'}
TURNOVER = {'parent_id', 'package_revision', 'package_digest', 'items', 'comment', 'no_effects'}


def fail(message, field='record', code='invalid_closeout', status=422):
    raise DomainError(code, message, status, {'field': field})


def kind(value):
    if type(value) is not str or value not in KINDS:
        fail('Choose a declared closeout record kind.', 'kind')
    return value


def package_definition(value):
    closed(value, {'title', 'description', 'asset_tag', 'location'})
    text(value['title'], 'title', 240)
    text(value['description'], 'description', 12000)
    for key in ('asset_tag', 'location'):
        text(value[key], key, 240, blank=True)
    return value


def requirement_input(value):
    closed(value, {'item_id', 'title', 'category', 'required', 'criteria'})
    identifier(value['item_id'], 'item_id')
    text(value['title'], 'title', 240)
    text(value['criteria'], 'criteria', 4000)
    if type(value['category']) is not str or value['category'] not in CATEGORIES:
        fail('Choose a declared closeout requirement category.', 'category')
    if type(value['required']) is not bool:
        fail('Declare whether this requirement is required.', 'required')
    return value


def requirements(value):
    sequence(value, 'requirements', 32, 1)
    for item in value:
        requirement_input(item)
    if len({r['item_id'] for r in value}) != len(value):
        fail('Declare each stable requirement identifier once.', 'requirements')
    if not any(r['required'] for r in value):
        fail('A turnover package needs at least one required evidence item.', 'requirements')
    return value


def exact_ref(value, *, with_kind=False):
    closed(value, {'id', 'record_digest'} | ({'kind'} if with_kind else set()))
    identifier(value['id']); checksum(value['record_digest'])
    if with_kind and (type(value['kind']) is not str or value['kind'] not in REQUIREMENTS):
        fail('Choose an exact commissioning or closeout requirement.', 'kind')


def links(value):
    sequence(value, 'links', 12)
    for row in value:
        closed(row, {'kind', 'id', 'record_digest'})
        if type(row['kind']) is not str or row['kind'] not in LINKS:
            fail('Choose checked engineering, an adoption, or ordinary quality closure.', 'links')
        identifier(row['id']); checksum(row['record_digest'])
    if len({(r['kind'], r['id']) for r in value}) != len(value):
        fail('Select each exact supporting fact once.', 'links')
    return value


def result_definition(value, category):
    if category not in CATEGORIES:
        fail('Choose a declared closeout category.', 'category')
    extra = {
        'commissioning': {'test_method', 'observed_result', 'acceptance_criteria_as_recorded'},
        'punch': set(),
        'om': {'manual_title', 'manual_revision_as_recorded'},
        'warranty': {'manufacturer', 'warranty_identifier', 'starts_on', 'expires_on'},
        'training': {'attendees_as_recorded'},
        'asset_handover': {'asset_tag', 'serial_number', 'recipient_as_recorded'},
    }[category]
    closed(value, {'outcome', 'notes', 'performed_on', 'performed_by'} | extra)
    if value['outcome'] not in ('pass', 'fail'):
        fail('Record an authored pass or fail outcome.', 'outcome')
    day(value['performed_on'], 'performed_on')
    if not value['performed_on']:
        fail('Record the actual documented date.', 'performed_on')
    for key in {'notes', 'performed_by'} | (extra - {'starts_on', 'expires_on'}):
        text(value[key], key, 4000 if key != 'performed_by' else 240)
    if category == 'warranty':
        for key in ('starts_on', 'expires_on'):
            day(value[key], key)
            if not value[key]: fail('Record the exact documentary warranty dates.', key)
        if value['expires_on'] < value['starts_on']:
            fail('The warranty end precedes its recorded start.', 'expires_on')
    return value


def result_links(category, value):
    links(value)
    needed = {'commissioning': 'engineering_check', 'punch': 'quality_closure',
              'om': 'document_adoption', 'warranty': 'document_adoption'}.get(category)
    if needed and not any(row['kind'] == needed for row in value):
        fail('This requirement needs its exact checked or accepted supporting fact.', 'links')


def accepted_ref(value):
    closed(value, {'requirement_id', 'result_kind', 'result_id', 'result_digest', 'decision_id', 'decision_digest'})
    for key in ('requirement_id', 'result_id', 'decision_id'): identifier(value[key], key)
    for key in ('result_digest', 'decision_digest'): checksum(value[key], key)
    if type(value['result_kind']) is not str or value['result_kind'] not in RESULTS: fail('Use an exact recorded result kind.', 'result_kind')


def record(k, value, *, initial=False):
    kind(k)
    fields = HEADER if k == 'package' else REVISION if k == 'package_revision' else REQUIREMENT if k in REQUIREMENTS else RESULT if k in RESULTS else DECISION if k == 'decision' else TURNOVER
    closed(value, BASE | fields); identifier(value['id'])
    for key in ('company', 'project', 'author_person', 'author_user'): text(value[key], key, 140)
    if value['scope_type'] != 'Project': fail('Closeout requires an exact Project.', 'scope_type')
    timestamp(value['created_at'], 'created_at')
    if k == 'package':
        text(value['number'], 'number', 140)
        if value['status'] not in ('draft', 'assembled', 'accepted'): fail('Unsupported closeout standing.', 'status')
        for key in ('current_revision', 'turnover_head', 'accepted_turnover'):
            if value[key] is not None: identifier(value[key], key)
        if value['current_revision'] is None and not (initial and value['revision_number'] == 0):
            fail('The immutable package revision is required.')
        sequence(value['result_heads'], 'result_heads', 32)
        for row in value['result_heads']:
            closed(row, {'requirement_id', 'result_kind', 'result_id'})
            identifier(row['requirement_id']); identifier(row['result_id'])
            if type(row['result_kind']) is not str or row['result_kind'] not in RESULTS: fail('Use an exact result kind.')
        sequence(value['accepted_results'], 'accepted_results', 32)
        for row in value['accepted_results']: accepted_ref(row)
        for key in ('result_heads', 'accepted_results'):
            if len({r['requirement_id'] for r in value[key]}) != len(value[key]): fail('The current requirement mapping is ambiguous.', key)
    else:
        if value['status'] != 'recorded': fail('Immutable original facts retain recorded standing.')
        identifier(value['parent_id'], 'parent_id')
        if value['no_effects'] != NO_EFFECTS or any(v is not False for v in value['no_effects'].values()):
            fail('Closeout evidence does not authorize other business effects.', 'no_effects')
    if 'revision_number' in value and (type(value['revision_number']) is not int or value['revision_number'] < (0 if initial and k == 'package' else 1)):
        fail('Use an exact positive revision number.', 'revision_number')
    if 'predecessor' in value and value['predecessor'] is not None: identifier(value['predecessor'])
    if k == 'package_revision':
        package_definition(value['definition']); sequence(value['requirements'], 'requirements', 32, 1)
        for ref in value['requirements']: exact_ref(ref, with_kind=True)
        if len({r['id'] for r in value['requirements']}) != len(value['requirements']): fail('A package revision repeats a requirement.')
        if value['amendment_of'] is not None: identifier(value['amendment_of'])
        text(value['amendment_reason'], 'amendment_reason', 2000, blank=True)
        if bool(value['amendment_of']) != bool(value['amendment_reason'].strip()): fail('An accepted original needs its explicit amendment reason.')
    elif k in REQUIREMENTS:
        identifier(value['package_revision']); requirement_input({key: value[key] for key in ('item_id', 'title', 'category', 'required', 'criteria')})
        if (k == 'commissioning_requirement') != (value['category'] == 'commissioning'): fail('The requirement category and native kind differ.')
    elif k in RESULTS:
        identifier(value['package_revision']); identifier(value['requirement_id']); checksum(value['requirement_digest'])
        # The exact requirement supplies the discriminator during lineage verification.
        if type(value['definition']) is not dict: fail('Supply the recorded result definition.', 'definition')
        source_list([strip_source(s) for s in value['evidence']], 'evidence', minimum=1)
        for source in value['evidence']: captured_source(source)
        links(value['links'])
    elif k == 'decision':
        identifier(value['package_revision']); identifier(value['subject_id']); checksum(value['subject_digest']); text(value['comment'], 'comment', 2000)
        if type(value['action']) is not str or value['action'] not in ('accept_result', 'accept_turnover'): fail('Choose a supported independent acceptance.', 'action')
        if type(value['subject_kind']) is not str or value['subject_kind'] not in (RESULTS if value['action'] == 'accept_result' else {'turnover'}): fail('The acceptance subject kind differs.')
    elif k == 'turnover':
        identifier(value['package_revision']); checksum(value['package_digest']); text(value['comment'], 'comment', 2000)
        sequence(value['items'], 'items', 32, 1)
        for row in value['items']: accepted_ref(row)
        if len({r['requirement_id'] for r in value['items']}) != len(value['items']): fail('The turnover package repeats a requirement.')
    return value
