"""Exact documentary closeout services, independent acceptance, durable UUIDs."""
from contextvars import ContextVar
from copy import deepcopy
from uuid import uuid4
from cipher_aec.api.contracts import digest, utc_timestamp
from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import page_options, decode_cursor, page_result, signing_secret
from cipher_aec.governance.context import current_actor, require_project, authority_fingerprint
from cipher_aec.governance.commands import run_command
from cipher_aec.governance.history import append_event
from . import contracts as rules, repository as repo, sources

_effect = ContextVar('cipher_closeout_effect', default=None)
ACTION_DUTY = {'create_package': rules.WRITE, 'revise_package': rules.WRITE,
               'record_result': rules.WRITE, 'accept_result': rules.CHECK,
               'assemble_turnover': rules.WRITE, 'accept_turnover': rules.ACCEPT}


def _base(company, project, actor, **fields):
    return {'id': str(uuid4()), 'company': company, 'project': project, 'scope_type': 'Project',
            'author_person': actor.person_id, 'author_user': actor.user,
            'created_at': utc_timestamp(), 'status': 'recorded', **fields}


def _raw(kind, record_id, company, project, *, lock=False):
    value = repo.raw(kind, record_id, lock=lock)
    if (value['company'], value['project'], value['scope_type']) != (company, project, 'Project'):
        raise DomainError('not_found', 'This closeout record is not available.', 404)
    return value


def _integrity(message):
    raise DomainError('closeout_integrity', message, 409)


def _collect(kind, record_id, company, project, *, lock=False):
    values = {}
    def add(k, name):
        if (k, name) in values: return values[k, name]
        if len(values) >= 256: rules.fail('Narrow this closeout evidence closure.', code='closeout_lineage_limit', status=409)
        v = _raw(k, name, company, project, lock=lock); values[k, name] = v
        if k == 'package':
            revision = add('package_revision', v['current_revision'])
            if revision['parent_id'] != v['id'] or revision['revision_number'] != v['revision_number']:
                _integrity('The package head differs from its immutable revision.')
            reqs = {r['id'] for r in revision['requirements']}
            heads = {r['requirement_id']: r for r in v['result_heads']}
            for row in v['result_heads']:
                result = add(row['result_kind'], row['result_id'])
                if row['requirement_id'] not in reqs or result['requirement_id'] != row['requirement_id'] or result['parent_id'] != v['id'] or result['package_revision'] != revision['id']:
                    _integrity('The current result belongs to a different exact requirement.')
            for row in v['accepted_results']:
                _accepted(row, revision, add)
                head = heads.get(row['requirement_id'])
                if not head or (head['result_kind'], head['result_id']) != (row['result_kind'], row['result_id']):
                    _integrity('Current accepted evidence differs from its result head.')
            if v['turnover_head']:
                turnover = add('turnover', v['turnover_head'])
                if turnover['package_revision'] != revision['id'] or turnover['items'] != v['accepted_results']:
                    _integrity('The current turnover snapshot differs from its exact accepted items.')
            if v['accepted_turnover']:
                old = add('turnover', v['accepted_turnover'])
                if old['parent_id'] != v['id']: _integrity('The historical accepted turnover belongs to another package.')
                accepted = repo.accepted('turnover', old['id'], lock=lock)
                if not accepted: _integrity('An accepted turnover needs its exact independent decision.')
                add('decision', accepted['id'])
            if v['status'] == 'accepted' and (not v['turnover_head'] or v['accepted_turnover'] != v['turnover_head']):
                _integrity('Accepted standing needs its current exact accepted turnover.')
            if v['status'] == 'assembled' and not v['turnover_head']:
                _integrity('Assembled standing needs its current exact snapshot.')
            if v['status'] == 'draft' and v['turnover_head'] is not None:
                _integrity('A draft cannot retain an active assembled snapshot.')
        elif k == 'package_revision':
            header = _raw('package', v['parent_id'], company, project, lock=lock)
            if v['revision_number'] > header['revision_number'] + (1 if _effect.get() else 0):
                _integrity('The package revision sequence exceeds its header.')
            if v['predecessor']:
                old = _raw(k, v['predecessor'], company, project, lock=lock)
                if old['parent_id'] != v['parent_id'] or old['revision_number'] + 1 != v['revision_number']:
                    _integrity('The package successor has a different immediate predecessor.')
            elif v['revision_number'] != 1: _integrity('The package successor is missing its predecessor.')
            authored = []
            for row in v['requirements']:
                requirement = add(row['kind'], row['id'])
                if requirement['parent_id'] != v['parent_id'] or requirement['package_revision'] != v['id'] or requirement['revision_number'] != v['revision_number'] or digest(requirement) != row['record_digest']:
                    _integrity('A package requirement differs from its exact immutable revision.')
                authored.append({key: requirement[key] for key in ('item_id', 'title', 'category', 'required', 'criteria')})
            rules.requirements(authored)
            if v['amendment_of']:
                old = add('turnover', v['amendment_of'])
                if old['parent_id'] != v['parent_id'] or not repo.accepted('turnover', old['id'], lock=lock):
                    _integrity('The amendment must retain its exact independently accepted original.')
        elif k in rules.REQUIREMENTS:
            revision = add('package_revision', v['package_revision'])
            if not any(row == {'kind': k, 'id': v['id'], 'record_digest': digest(v)} for row in revision['requirements']):
                _integrity('The requirement is absent from its original package revision.')
            if v['predecessor']:
                old = _raw(k, v['predecessor'], company, project, lock=lock)
                if old['parent_id'] != v['parent_id'] or old['item_id'] != v['item_id'] or old['category'] != v['category'] or old['revision_number'] >= v['revision_number']:
                    _integrity('The requirement successor differs from its original item.')
        elif k in rules.RESULTS:
            revision = add('package_revision', v['package_revision'])
            reference = next((r for r in revision['requirements'] if r['id'] == v['requirement_id']), None)
            if not reference: _integrity('The result has a different original requirement.')
            requirement = add(reference['kind'], reference['id'])
            if v['parent_id'] != revision['parent_id'] or v['requirement_digest'] != digest(requirement):
                _integrity('The result requirement digest differs.')
            rules.result_definition(v['definition'], requirement['category']); rules.result_links(requirement['category'], v['links'])
            if (k == 'asset_handover') != (requirement['category'] == 'asset_handover'):
                _integrity('The result native kind differs from its requirement.')
            if v['predecessor']:
                old = _raw(k, v['predecessor'], company, project, lock=lock)
                if any(old[key] != v[key] for key in ('parent_id', 'package_revision', 'requirement_id', 'requirement_digest')):
                    _integrity('A result successor must preserve its exact requirement lineage.')
        elif k == 'decision':
            original = add(v['subject_kind'], v['subject_id'])
            if digest(original) != v['subject_digest'] or any(v[key] != original[key] for key in ('parent_id', 'package_revision')):
                _integrity('The acceptance differs from its exact immutable original.')
            if v['author_person'] == original['author_person']:
                raise DomainError('independent_closeout_required', 'Another canonical person must accept this exact evidence.', 403)
            if v['action'] == 'accept_result':
                if original['definition']['outcome'] != 'pass': _integrity('A failed result cannot have accepted standing.')
            else:
                revision = add('package_revision', v['package_revision'])
                if v['author_person'] == revision['author_person']:
                    raise DomainError('independent_closeout_required', 'The package author cannot accept its own turnover.', 403)
        else:
            revision = add('package_revision', v['package_revision'])
            if revision['parent_id'] != v['parent_id'] or digest(revision) != v['package_digest']:
                _integrity('Turnover differs from its exact immutable package revision.')
            for row in v['items']: _accepted(row, revision, add)
            required = {row['id'] for row in revision['requirements'] if add(row['kind'], row['id'])['required']}
            if not required <= {row['requirement_id'] for row in v['items']}:
                raise DomainError('closeout_evidence_required', 'Every required item needs exact independently accepted passing evidence.', 422)
        return v
    result = add(kind, record_id)
    return result, list(values.values())


def _accepted(row, revision, add):
    result = add(row['result_kind'], row['result_id']); decision = add('decision', row['decision_id'])
    if (row['requirement_id'] not in {r['id'] for r in revision['requirements']}
        or result['package_revision'] != revision['id'] or result['requirement_id'] != row['requirement_id']
        or digest(result) != row['result_digest'] or digest(decision) != row['decision_digest']
        or decision['action'] != 'accept_result' or decision['subject_kind'] != row['result_kind']
        or decision['subject_id'] != result['id'] or decision['subject_digest'] != digest(result)):
        _integrity('The turnover item differs from its exact independently accepted result.')


def read(kind, record_id, company, project, actor, *, lock=False, new_use=False):
    rules.kind(kind)
    require_project(company, project, ability=rules.READ, actor=actor, lock=lock)
    value, closure = _collect(kind, record_id, company, project, lock=lock)
    sources.verify(closure, company, project, actor, lock=lock, new_use=False)
    if new_use:
        target_revision = value['current_revision'] if kind == 'package' else value['id'] if kind == 'package_revision' else value['package_revision']
        # Historical accepted originals remain readable under current rights.
        # Their later source heads never substitute for the original bytes, and
        # do not prevent a separately authored current amendment from proceeding.
        current = [row for row in closure if row.get('package_revision') == target_revision]
        sources.verify(current, company, project, actor, lock=lock, new_use=True)
    return value


def _command(company, project, operation_id, action, payload, effect):
    actor = current_actor(); require_project(company, project, ability=rules.READ, actor=actor)
    def guard(actor, project_doc):
        require_project(company, project, ability=rules.READ, actor=actor, lock=True)
        if project_doc.status in ('Completed', 'Cancelled'):
            raise DomainError('project_closed', 'This Project is closed for new closeout work.', 409)
    def admitted(actor, project_doc):
        token = _effect.set({'action': action, 'person': actor.person_id, 'company': company, 'project': project, 'facts': {}})
        try: return effect(actor, project_doc)
        finally: _effect.reset(token)
    result = run_command(company=company, project=project, operation_id=operation_id,
                         command='closeout.' + action + '.v1', payload=payload,
                         ability=ACTION_DUTY[action], guard=guard, effect=admitted)
    authorize_command_receipt(current_actor(), 'closeout.' + action + '.v1', company, project, result, lock=True)
    return result


def _write(kind, value, *, old=None):
    plan = _effect.get()
    if not plan: raise DomainError('closeout_command_required', 'Use the exact admitted closeout command.', 403)
    plan['facts'][kind, value['id']] = deepcopy(value)
    return repo.write(kind, value, old=old)


def _event(actor, value, operation_id, action, kind):
    return append_event(actor=actor, company=value['company'], project=value['project'], operation_id=operation_id,
                        event='closeout.' + action, subject_type=rules.KINDS[kind], subject_id=value['id'],
                        details={'record_digest': digest(value), 'parent_id': value.get('parent_id'), 'documentary_only': True})


def _version(header, expected):
    rules.checksum(expected, 'expected_version')
    if digest(header) != expected:
        raise DomainError('stale_closeout', 'This closeout package changed. Review its current evidence before continuing.', 412)


def _requirement_revision(header, definition, requirements, actor, amendment_reason=''):
    old = _raw('package_revision', header['current_revision'], header['company'], header['project'], lock=True) if header['current_revision'] else None
    old_by_item, seen_revisions, previous = {}, set(), old
    # A removed stable item remains part of the package's immutable identity
    # history. Reintroduction links its last exact occurrence and keeps category.
    while previous:
        if previous['id'] in seen_revisions or len(seen_revisions) >= 64:
            raise DomainError('closeout_lineage_limit', 'The bounded requirement identity history cannot be verified.', 409)
        seen_revisions.add(previous['id'])
        for ref in previous['requirements']:
            item = _raw(ref['kind'], ref['id'], header['company'], header['project'], lock=True)
            if item['package_revision'] != previous['id'] or item['parent_id'] != header['id'] or digest(item) != ref['record_digest']:
                _integrity('The historical stable requirement identity differs.')
            old_by_item.setdefault(item['item_id'], item)
        prior = previous['predecessor']
        if prior:
            predecessor = _raw('package_revision', prior, header['company'], header['project'], lock=True)
            if predecessor['parent_id'] != header['id'] or predecessor['revision_number'] + 1 != previous['revision_number']:
                _integrity('The historical package revision predecessor differs.')
            previous = predecessor
        else:
            if previous['revision_number'] != 1: _integrity('The historical package revision sequence is incomplete.')
            previous = None
    revision = _base(header['company'], header['project'], actor, parent_id=header['id'], revision_number=header['revision_number'] + 1,
                     predecessor=header['current_revision'], definition=deepcopy(definition), requirements=[],
                     amendment_of=header['accepted_turnover'], amendment_reason=amendment_reason, no_effects=dict(rules.NO_EFFECTS))
    rows = []
    for item in requirements:
        previous = old_by_item.get(item['item_id'])
        if previous and previous['category'] != item['category']:
            rules.fail('A stable requirement keeps its original category. Add a new item for a different category.', 'category')
        kind = 'commissioning_requirement' if item['category'] == 'commissioning' else 'requirement'
        row = _base(header['company'], header['project'], actor, parent_id=header['id'], package_revision=revision['id'],
                    revision_number=revision['revision_number'], predecessor=previous['id'] if previous else None,
                    **deepcopy(item), no_effects=dict(rules.NO_EFFECTS))
        rows.append((kind, row)); revision['requirements'].append({'kind': kind, 'id': row['id'], 'record_digest': digest(row)})
    # Native controllers use this exact predeclared closure; no arbitrary trusted
    # writer can manufacture a fact or bootstrap a different parent revision.
    plan = _effect.get(); plan['facts']['package_revision', revision['id']] = deepcopy(revision)
    for kind, row in rows: plan['facts'][kind, row['id']] = deepcopy(row)
    for kind, row in rows: _write(kind, row)
    _write('package_revision', revision)
    final = {**header, 'status': 'draft', 'current_revision': revision['id'], 'revision_number': revision['revision_number'],
             'result_heads': [], 'accepted_results': [], 'turnover_head': None}
    _write('package', final, old=header)
    return final, revision, [row for _, row in rows]


def create_package(company, project, operation_id, definition, requirements):
    rules.package_definition(definition); rules.requirements(requirements)
    def effect(actor, _):
        header = _base(company, project, actor, status='draft', number=repo.number(company, project), revision_number=0,
                       current_revision=None, result_heads=[], accepted_results=[], turnover_head=None, accepted_turnover=None)
        _write('package', header)
        final, revision, rows = _requirement_revision(header, definition, requirements, actor)
        return {'package': final, 'package_revision': revision, 'requirements': rows,
                'history_id': _event(actor, revision, operation_id, 'created', 'package_revision')}
    return _command(company, project, operation_id, 'create_package', {'definition': definition, 'requirements': requirements}, effect)


def revise_package(company, project, operation_id, package_id, expected_version, definition, requirements, amendment_reason=''):
    rules.package_definition(definition); rules.requirements(requirements); rules.text(amendment_reason, 'amendment_reason', 2000, blank=True)
    def effect(actor, _):
        header = read('package', package_id, company, project, actor, lock=True); _version(header, expected_version)
        if bool(header['accepted_turnover']) != bool(amendment_reason.strip()):
            rules.fail('A successor to an accepted turnover needs its explicit amendment reason.', 'amendment_reason')
        final, revision, rows = _requirement_revision(header, definition, requirements, actor, amendment_reason)
        return {'package': final, 'package_revision': revision, 'requirements': rows,
                'history_id': _event(actor, revision, operation_id, 'revised', 'package_revision')}
    return _command(company, project, operation_id, 'revise_package', {'package_id': package_id, 'expected_version': expected_version,
                    'definition': definition, 'requirements': requirements, 'amendment_reason': amendment_reason}, effect)


def record_result(company, project, operation_id, package_id, expected_version, requirement_id, definition, evidence, links):
    rules.identifier(requirement_id); rules.source_list(evidence, 'evidence', minimum=1); rules.links(links)
    def effect(actor, _):
        # Collect the exact existing rows without locking a partial artifact set.
        # The new evidence and dependency closure join this full union below.
        header, existing = _collect('package', package_id, company, project, lock=True); _version(header, expected_version)
        if header['status'] == 'accepted':
            raise DomainError('closeout_amendment_required', 'Create an explicit package successor before changing accepted turnover evidence.', 409)
        revision = _raw('package_revision', header['current_revision'], company, project, lock=True)
        ref = next((r for r in revision['requirements'] if r['id'] == requirement_id), None)
        if not ref: raise DomainError('stale_closeout_requirement', 'Select an exact requirement from the current package revision.', 412)
        requirement = _raw(ref['kind'], ref['id'], company, project, lock=True)
        rules.result_definition(definition, requirement['category']); rules.result_links(requirement['category'], links)
        # Discover retained metadata without locking a partial source set. The
        # complete own + ENG/DOC/quality union below acquires sorted parents and
        # rechecks exact bytes and current ingest rights before any write.
        resolved = sources.resolve(company, project, evidence, actor, lock=False, new_use=False)
        kind = 'asset_handover' if requirement['category'] == 'asset_handover' else 'test_result'
        prior = next((r for r in header['result_heads'] if r['requirement_id'] == requirement_id), None)
        value = _base(company, project, actor, parent_id=header['id'], package_revision=revision['id'], requirement_id=requirement_id,
                      requirement_digest=digest(requirement), predecessor=prior['result_id'] if prior else None,
                      definition=deepcopy(definition), evidence=[sources.mapped(s, resolved) for s in evidence], links=deepcopy(links), no_effects=dict(rules.NO_EFFECTS))
        sources.verify([*existing, value], company, project, actor, lock=True, new_use=False,
                       retired_result_ids=(prior['result_id'],) if prior else ())
        sources.verify([value], company, project, actor, lock=True, new_use=True); _write(kind, value)
        heads = [r for r in header['result_heads'] if r['requirement_id'] != requirement_id]
        heads.append({'requirement_id': requirement_id, 'result_kind': kind, 'result_id': value['id']})
        final = {**header, 'status': 'draft', 'result_heads': heads, 'accepted_results': [r for r in header['accepted_results'] if r['requirement_id'] != requirement_id], 'turnover_head': None}
        _write('package', final, old=header)
        return {'package': final, 'result': value, 'history_id': _event(actor, value, operation_id, 'result_recorded', kind)}
    return _command(company, project, operation_id, 'record_result', {'package_id': package_id, 'expected_version': expected_version,
                    'requirement_id': requirement_id, 'definition': definition, 'evidence': evidence, 'links': links}, effect)


def accept_result(company, project, operation_id, package_id, expected_version, result_id, result_digest, comment):
    rules.identifier(result_id); rules.checksum(result_digest); rules.text(comment, 'comment', 2000)
    def effect(actor, _):
        header = read('package', package_id, company, project, actor, lock=True); _version(header, expected_version)
        head = next((r for r in header['result_heads'] if r['result_id'] == result_id), None)
        if not head: raise DomainError('stale_closeout_result', 'Select the exact current result before independent acceptance.', 412)
        if header['status'] == 'accepted': raise DomainError('closeout_amendment_required', 'Create an explicit package successor first.', 409)
        result = read(head['result_kind'], result_id, company, project, actor, lock=True, new_use=True)
        if digest(result) != result_digest: raise DomainError('stale_closeout_result', 'Review the exact result before accepting it.', 412)
        if actor.person_id == result['author_person']: raise DomainError('independent_closeout_required', 'Another canonical person must accept this result.', 403)
        if result['definition']['outcome'] != 'pass': raise DomainError('closeout_failed_result', 'A failed result needs a separately recorded passing successor.', 409)
        if repo.accepted(head['result_kind'], result_id, lock=True): raise DomainError('closeout_already_accepted', 'This exact result already has independent acceptance.', 409)
        value = _base(company, project, actor, parent_id=header['id'], package_revision=header['current_revision'], action='accept_result',
                      subject_kind=head['result_kind'], subject_id=result_id, subject_digest=result_digest, comment=comment, no_effects=dict(rules.NO_EFFECTS))
        _write('decision', value)
        accepted = [r for r in header['accepted_results'] if r['requirement_id'] != head['requirement_id']]
        accepted.append({'requirement_id': head['requirement_id'], 'result_kind': head['result_kind'], 'result_id': result_id,
                         'result_digest': result_digest, 'decision_id': value['id'], 'decision_digest': digest(value)})
        final = {**header, 'status': 'draft', 'accepted_results': accepted, 'turnover_head': None}; _write('package', final, old=header)
        return {'package': final, 'result': result, 'decision': value, 'history_id': _event(actor, value, operation_id, 'result_accepted', 'decision')}
    return _command(company, project, operation_id, 'accept_result', {'package_id': package_id, 'expected_version': expected_version,
                    'result_id': result_id, 'result_digest': result_digest, 'comment': comment}, effect)


def assemble_turnover(company, project, operation_id, package_id, expected_version, comment):
    rules.text(comment, 'comment', 2000)
    def effect(actor, _):
        header = read('package', package_id, company, project, actor, lock=True, new_use=True); _version(header, expected_version)
        if header['status'] != 'draft': raise DomainError('closeout_state', 'Only a working draft can assemble a new turnover snapshot.', 409)
        revision = read('package_revision', header['current_revision'], company, project, actor, lock=True)
        required = {r['id'] for r in revision['requirements'] if _raw(r['kind'], r['id'], company, project, lock=True)['required']}
        if not required <= {r['requirement_id'] for r in header['accepted_results']}:
            raise DomainError('closeout_evidence_required', 'Every required item needs exact independently accepted passing evidence.', 422)
        value = _base(company, project, actor, parent_id=header['id'], package_revision=revision['id'], package_digest=digest(revision),
                      items=deepcopy(header['accepted_results']), comment=comment, no_effects=dict(rules.NO_EFFECTS))
        _write('turnover', value)
        final = {**header, 'status': 'assembled', 'turnover_head': value['id']}; _write('package', final, old=header)
        return {'package': final, 'turnover': value, 'history_id': _event(actor, value, operation_id, 'turnover_assembled', 'turnover')}
    return _command(company, project, operation_id, 'assemble_turnover', {'package_id': package_id, 'expected_version': expected_version, 'comment': comment}, effect)


def accept_turnover(company, project, operation_id, package_id, expected_version, turnover_id, turnover_digest, comment):
    rules.identifier(turnover_id); rules.checksum(turnover_digest); rules.text(comment, 'comment', 2000)
    def effect(actor, _):
        header = read('package', package_id, company, project, actor, lock=True, new_use=True); _version(header, expected_version)
        if header['status'] != 'assembled' or header['turnover_head'] != turnover_id:
            raise DomainError('stale_closeout_turnover', 'Select the current assembled turnover snapshot.', 412)
        turnover = read('turnover', turnover_id, company, project, actor, lock=True, new_use=True)
        revision = read('package_revision', header['current_revision'], company, project, actor, lock=True)
        if digest(turnover) != turnover_digest: raise DomainError('stale_closeout_turnover', 'Review the exact assembled turnover snapshot.', 412)
        if actor.person_id in {turnover['author_person'], revision['author_person']}:
            raise DomainError('independent_closeout_required', 'A person independent of the package author and assembler must accept turnover.', 403)
        value = _base(company, project, actor, parent_id=header['id'], package_revision=revision['id'], action='accept_turnover',
                      subject_kind='turnover', subject_id=turnover_id, subject_digest=turnover_digest, comment=comment, no_effects=dict(rules.NO_EFFECTS))
        _write('decision', value)
        final = {**header, 'status': 'accepted', 'accepted_turnover': turnover_id}; _write('package', final, old=header)
        return {'package': final, 'turnover': turnover, 'decision': value, 'history_id': _event(actor, value, operation_id, 'turnover_accepted', 'decision')}
    return _command(company, project, operation_id, 'accept_turnover', {'package_id': package_id, 'expected_version': expected_version,
                    'turnover_id': turnover_id, 'turnover_digest': turnover_digest, 'comment': comment}, effect)


def authorize_receipt(actor, company, project, result, *, lock=False):
    require_project(company, project, ability=rules.READ, actor=actor, lock=lock)
    if type(result) is not dict or type(result.get('package')) is not dict:
        _integrity('The exact original closeout receipt is unavailable.')
    original = result['package']; rules.record('package', original)
    current = _raw('package', original['id'], company, project, lock=lock)
    if any(current[k] != original[k] for k in (rules.BASE - {'status'}) | {'number'}): _integrity('The receipt package identity differs.')
    # Read ORIGINAL snapshot IDs, never substitute a later working head.
    revision = read('package_revision', original['current_revision'], company, project, actor, lock=lock)
    if revision['parent_id'] != original['id'] or revision['revision_number'] != original['revision_number']:
        _integrity('The receipt original package revision differs.')
    _, values = _collect('package_revision', revision['id'], company, project, lock=lock)
    def exact(k, v):
        actual = read(k, v['id'], company, project, actor, lock=lock)
        if actual != v or v.get('parent_id') != original['id'] or v.get('package_revision', revision['id']) != revision['id']:
            _integrity('An original receipt fact differs from its exact retained revision.')
    if 'package_revision' in result and result['package_revision'] != revision: _integrity('The original revision response differs.')
    if 'requirements' in result:
        expected = [_raw(ref['kind'], ref['id'], company, project, lock=lock) for ref in revision['requirements']]
        if result['requirements'] != expected: _integrity('The original requirement response differs.')
    for row in original['result_heads']:
        v = read(row['result_kind'], row['result_id'], company, project, actor, lock=lock)
        if v['requirement_id'] != row['requirement_id'] or v['package_revision'] != revision['id']: _integrity('The receipt result head differs.')
    for row in original['accepted_results']:
        _accepted(row, revision, lambda k, i: read(k, i, company, project, actor, lock=lock))
    if 'result' in result:
        k = next((r['result_kind'] for r in original['result_heads'] if r['result_id'] == result['result'].get('id')), None)
        if not k: _integrity('The receipt result is absent from its original header.')
        exact(k, result['result'])
    if 'turnover' in result:
        exact('turnover', result['turnover'])
        if result['turnover']['id'] != original['turnover_head']: _integrity('The receipt turnover differs from its original header.')
    if 'decision' in result: exact('decision', result['decision'])
    if original['turnover_head']:
        turnover = read('turnover', original['turnover_head'], company, project, actor, lock=lock)
        if turnover['items'] != original['accepted_results'] or turnover['package_revision'] != revision['id']: _integrity('The original turnover items differ.')


def authorize_command_receipt(actor, command, company, project, result, *, lock=False):
    parts = command.split('.') if type(command) is str else []
    if len(parts) != 3 or parts[0] != 'closeout' or parts[1] not in ACTION_DUTY or parts[2] != 'v1':
        _integrity('The closeout receipt command differs.')
    action = parts[1]
    expected = {'create_package': {'package_revision', 'requirements'}, 'revise_package': {'package_revision', 'requirements'},
                'record_result': {'result'}, 'accept_result': {'result', 'decision'},
                'assemble_turnover': {'turnover'}, 'accept_turnover': {'turnover', 'decision'}}[action]
    if set(result) - {'operation'} != {'package', 'history_id'} | expected: _integrity('The closeout command result shape differs.')
    if 'decision' in expected and result['decision'].get('action') != action: _integrity('The independent acceptance action differs.')
    if action == 'accept_result':
        decision, original = result['decision'], result['result']
        if decision['subject_id'] != original['id'] or decision['subject_digest'] != digest(original):
            _integrity('The original result acceptance response identifies a different exact subject.')
        accepted = next((r for r in result['package']['accepted_results'] if r['result_id'] == original['id']), None)
        if not accepted or accepted['decision_id'] != decision['id'] or accepted['decision_digest'] != digest(decision):
            _integrity('The original accepted-result header differs from its exact decision.')
    if action == 'assemble_turnover' and result['package']['status'] != 'assembled':
        _integrity('The original assembly response has a different standing.')
    if action == 'accept_turnover':
        decision, original = result['decision'], result['turnover']
        if (decision['subject_id'] != original['id'] or decision['subject_digest'] != digest(original)
            or result['package']['status'] != 'accepted' or result['package']['accepted_turnover'] != original['id']):
            _integrity('The original turnover acceptance response identifies a different exact subject.')
    return authorize_receipt(actor, company, project, result, lock=lock)


def get_record(company, project, kind, record_id):
    value = read(kind, record_id, company, project, current_actor())
    return {'record': value, 'record_digest': digest(value)}


def list_records(company, project, kind, parent_id=None, limit=25, cursor=None, count_mode='none'):
    rules.kind(kind); limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    if limit > 100 or count_mode != 'none': rules.fail('Use bounded closeout pages without totals.', 'paging')
    actor = current_actor(); require_project(company, project, ability=rules.READ, actor=actor)
    if parent_id is not None: rules.identifier(parent_id, 'parent_id')
    scope = {'route': 'closeout.records.v1', 'company': company, 'project': project, 'kind': kind,
             'parent_id': parent_id, 'limit': limit, 'actor': actor.person_id, 'user': actor.user,
             'authority': authority_fingerprint(actor, company, project)}
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    items, last_visible, scanned = [], None, 0
    while len(items) <= limit:
        rows = repo.candidates(kind, company, project, parent_id=parent_id, last=last, limit=25)
        if not rows: break
        for row in rows:
            scanned += 1
            if scanned > 500: rules.fail('Narrow the closeout package filter.', 'paging')
            last = [str(row.creation), row.name]
            try: value = get_record(company, project, kind, row.name)
            except DomainError as error:
                if error.status in (403, 404): continue
                raise
            items.append(value)
            if len(items) <= limit: last_visible = last
            if len(items) > limit: break
        if len(rows) < 25: break
    return page_result(items[:limit], has_more=len(items) > limit, last=last_visible, scope=scope, limit=limit, count_mode='none', total=None)


def authorize_history(kind, record_id, company, project, actor, details, *, event):
    value = read(kind, record_id, company, project, actor)
    allowed = {'package_revision': ('closeout.created', 'closeout.revised'),
               'test_result': ('closeout.result_recorded',), 'asset_handover': ('closeout.result_recorded',),
               'turnover': ('closeout.turnover_assembled',),
               'decision': ('closeout.result_accepted',) if value.get('action') == 'accept_result' else ('closeout.turnover_accepted',)}
    if event not in allowed.get(kind, ()):
        _integrity('The closeout history event differs from its exact retained action.')
    if details != {'record_digest': digest(value), 'parent_id': value.get('parent_id'), 'documentary_only': True}:
        _integrity('The closeout history fact differs from its exact retained record.')
    return value
