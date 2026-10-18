"""Current exact ordinary artifacts and checked documentary dependencies."""
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.field.sources import resolve, mapped
from cipher_aec.document_control import rights
from . import contracts as rules


def _link(row, company, project, actor, *, lock=False, new_use=False):
    """Use existing domain readers; a caller's 'accepted' flag is never evidence."""
    if row['kind'] == 'engineering_check':
        from cipher_aec.engineering_packages import service, contracts
        fact = service.read('check', row['id'], company, project, actor, lock=lock)
        original = service.read(fact['subject_kind'], fact['subject_id'], company, project, actor, lock=lock)
        if new_use:
            header = service.raw('package', original['parent_id'], company, project, lock=lock)
            current = (header['basis_head'] == original['id'] if fact['subject_kind'] == 'basis'
                       else original['id'] in header[fact['subject_kind'] + '_heads'] and original['basis_revision'] == header['basis_head'])
            if not current or original['package_revision'] != header['current_revision']:
                raise DomainError('stale_closeout_dependency', 'The checked engineering revision has an explicit successor.', 412)
        values = [original]
        if fact['subject_kind'] in ('calculation', 'deliverable'):
            values.append(service.read('basis', original['basis_revision'], company, project, actor, lock=lock))
        if fact['subject_kind'] == 'deliverable':
            values.extend(service.read('calculation', r['id'], company, project, actor, lock=lock) for r in original['calculations'])
        return fact, values
    if row['kind'] == 'document_adoption':
        from cipher_aec.document_control import service
        fact = service.read('adoption', row['id'], company, project, actor, lock=lock)
        if new_use:
            # Deliberately admit only Project-local adoptions in this first slice.
            # Shared Company/global library adoption remains an explicit later extension.
            request = service.read('adoption_request', fact['subject_id'], company, project, actor, lock=lock)
            if request.get('library_scope', {'scope_type': 'Project', 'project': project}) != {'scope_type': 'Project', 'project': project}:
                raise DomainError('unsupported_closeout_dependency', 'Use a Project-local adopted revision for this closeout package.', 422)
            revision = service.read('library_revision', request['library_revision'], company, project, actor, lock=lock)
            header = service.raw('library', revision['parent_id'], company, project, lock=lock)
            if header['current_revision'] != revision['id']:
                raise DomainError('stale_closeout_dependency', 'Review the current adopted library revision before new closeout acceptance.', 412)
        return fact, [fact]
    if row['kind'] == 'quality_closure':
        from cipher_aec.quality_safety import service
        # Fixed ordinary family prevents incident existence or sensitive metadata probing.
        fact = service.read('decision', row['id'], company, project, actor, lock=lock, new_use=new_use)
        if fact['action'] != 'close' or fact['to_status'] != 'closed' or fact['category'] not in ('inspection', 'deficiency'):
            raise DomainError('closeout_quality_closure_required', 'Select an independently closed ordinary inspection or deficiency.', 422)
        revision = service.read('revision', fact['source_revision'], company, project, actor, lock=lock, new_use=new_use)
        if new_use:
            header = service.read('record', fact['parent_id'], company, project, actor, lock=lock, new_use=True)
            if header['status'] != 'closed' or header['current_revision'] != revision['id'] or header['last_decision'] != fact['id']:
                raise DomainError('stale_closeout_dependency', 'The ordinary quality closure has an explicit successor.', 412)
        return fact, [fact, revision]
    rules.fail('Choose an exact supported closeout dependency.', 'links')


def _artifacts(values):
    """Collect artifacts AND citations; canonical discovery supplies byte metadata.

    ENG-02 canonical citations intentionally have no byte_length/page_count.
    Omitting them would skip current ingest/privacy checks on citation-only work.
    """
    found, revisions = {}, {}
    def visit(value):
        if type(value) is dict:
            if {'document_id', 'revision_id', 'source_sha256'} <= set(value):
                revision = value['revision_id']
                identity = (value['document_id'], value['source_sha256'])
                if revision in revisions and revisions[revision] != identity:
                    raise DomainError('closeout_source_integrity', 'A dependency has conflicting exact source metadata.', 409)
                revisions[revision] = identity
                page = value.get('page', 1)
                locator = value.get('locator', 'Exact accepted dependency citation page ' + str(page)
                                    if 'excerpt_sha256' in value else 'Exact accepted dependency artifact')
                row = {'document_id': value['document_id'], 'revision_id': revision,
                       'source_sha256': value['source_sha256'], 'page': page, 'locator': locator}
                found[revision, page, locator] = row
            for child in value.values(): visit(child)
        elif type(value) is list:
            for child in value: visit(child)
    visit(values)
    return list(found.values())


def _prelock_groups(groups, company, project, actor):
    """Keep each rights graph bounded, then lock their complete sorted union."""
    from cipher_aec.document_control.service import _document
    planned = {key: rights.document_plan(names) for key, names in groups.items()}
    union = set().union(*planned.values()) if planned else set()
    if len(union) > 256:
        raise DomainError('closeout_lineage_limit', 'The historical closeout rights-parent union exceeds its bound.', 409)
    for name in sorted(union): _document(name, company, project, actor, lock=True)
    if any(rights.document_plan(groups[key]) != value for key, value in planned.items()):
        raise DomainError('source_rights_changed', 'Content-permission evidence changed concurrently. Retry the original request.', 503)


def _group(values, company, project, actor):
    """One immutable package revision owns its 32-source/64-MiB budget."""
    own = [r for value in values for r in value.get('evidence', [])]
    link_rows = [r for value in values for r in value.get('links', [])]
    unique = {}
    for row in link_rows:
        key = (row['kind'], row['id'])
        if key in unique and unique[key]['record_digest'] != row['record_digest']:
            raise DomainError('closeout_dependency_integrity', 'One supporting fact has conflicting digests.', 409)
        unique[key] = row
    if len(unique) > 64: rules.fail('Narrow the supporting closeout facts.', 'links')
    discovered = []
    for row in sorted(unique.values(), key=lambda r: (r['kind'], r['id'])):
        fact, closure = _link(row, company, project, actor, new_use=False)
        if digest(fact) != row['record_digest']:
            raise DomainError('closeout_dependency_integrity', 'The exact checked or accepted supporting fact differs.', 409)
        discovered.extend(closure)
    extra = _artifacts(discovered)
    stripped = [{k: r[k] for k in ('revision_id', 'source_sha256', 'page', 'locator')} for r in [*own, *extra]]
    return own, unique, stripped


def verify(values, company, project, actor, *, lock=False, new_use=False, retired_result_ids=()):
    """Authorize historical originals without spending a current revision's budget.

    All groups are discovered before parent locks. Per-revision source and rights
    limits remain unchanged; the complete historical union is separately bounded.
    """
    groups = {}
    for value in values:
        if value.get('evidence') or value.get('links'):
            # Replacing a head must retain/read its original evidence during
            # admission, but that retired leaf does not spend the prospective
            # current package's budget. Only the server supplies these exact IDs.
            key = ('retired:' + value['id'] if value.get('id') in retired_result_ids
                   else value.get('package_revision', 'standalone'))
            groups.setdefault(key, []).append(value)
    prepared, parents = {}, {}
    for key, group in sorted(groups.items()):
        own, unique, stripped = _group(group, company, project, actor)
        discovered = resolve(company, project, stripped, actor, lock=False, new_use=False)
        prepared[key] = (own, unique, stripped, discovered)
        parents[key] = {row['document_id'] for row in discovered.values()}
    if lock: _prelock_groups(parents, company, project, actor)
    result = {}
    for key, (own, unique, stripped, discovered) in prepared.items():
        # The shared Field resolver enforces 32 exact revisions/64 MiB per
        # immutable package revision and rechecks bytes/rights after full locks.
        resolved = resolve(company, project, stripped, actor, lock=lock, new_use=new_use)
        if discovered != resolved:
            raise DomainError('closeout_source_integrity', 'The complete source plan changed during admission.', 412)
        _verify_group(own, unique, resolved, company, project, actor, lock=lock, new_use=new_use)
        result.update(resolved)
    return result


def _verify_group(own, unique, resolved, company, project, actor, *, lock=False, new_use=False):
    from cipher_aec.quality_safety.privacy import registration
    for document_id in sorted({row['document_id'] for row in resolved.values()}):
        if registration(document_id, lock=lock) is not None:
            raise DomainError('closeout_source_unavailable', 'Use ordinary Project evidence for closeout.', 403)
    if any(row != mapped(row, resolved) for row in own):
        raise DomainError('closeout_source_integrity', 'Retained closeout evidence differs from its exact original bytes.', 409)
    for row in sorted(unique.values(), key=lambda r: (r['kind'], r['id'])):
        fact, _ = _link(row, company, project, actor, lock=lock, new_use=new_use)
        if digest(fact) != row['record_digest']:
            raise DomainError('closeout_dependency_integrity', 'The supporting fact changed during admission.', 412)
