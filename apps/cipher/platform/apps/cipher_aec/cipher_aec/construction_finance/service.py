"""Scoped contract authoring; activation is exclusively a registered GOV effect."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.commands import run_command
from cipher_aec.governance.context import current_actor, require_project
from cipher_aec.governance.history import append_event
from cipher_aec.estimating import sources as document_sources, units
from . import core, repository, sources


def _new(actor, company, project, **values):
    return {'id': str(uuid4()), 'company': company, 'project': project, 'author_person': actor.person_id,
            'author_user': actor.user, 'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'authored', **values}


def version(contract):
    return digest(contract)


def _event(actor, contract, operation_id, event, record):
    return append_event(actor=actor, company=contract['company'], project=contract['project'], event=event,
                        subject_type=repository.DOCTYPES['contract'], subject_id=contract['id'], operation_id=operation_id,
                        details={'record_id': record['id'], 'record_digest': digest(record)})


def lock_sources(contract, actor, *, revision_ids=(), extra_unit_ids=()):
    """Acquire all shared masters once in EST's UOM→Currency→party order.

    Project is already locked by every effect. Include historical packet sources
    and both aggregate heads before acquiring any shared native master.
    """
    ids = set(extra_unit_ids)
    revisions = set(revision_ids) | {value for value in (contract['draft_revision'], contract['accepted_revision']) if value}
    for revision_id in sorted(revisions):
        revision = repository.read('revision', revision_id, lock=True)
        if revision['contract'] != contract['id']:
            raise DomainError('contract_integrity', 'A shared-master source belongs to another contract.', 409)
        ids.update(row['id'] for row in revision['units'])
    for unit_id in sorted(ids):
        units.qualified(unit_id, lock=True, allow_disabled=True)
    frappe.db.sql('SELECT name FROM `tabCurrency` WHERE name=%s FOR UPDATE', (contract['definition']['currency'],))
    return sources.party_snapshot(contract['company'], contract['project'], contract['definition'], actor, lock=True, allow_disabled=True)


def scoped(kind, record_id, company, project, actor, *, lock=False):
    require_project(company, project, ability='contract.read', actor=actor, lock=lock)
    value = repository.read(kind, record_id, lock=lock)
    if value['company'] != company or value['project'] != project:
        raise DomainError('not_found', 'This construction contract record is not available.', 404)
    contract = value if kind == 'contract' else repository.read('contract', value['contract'], lock=lock)
    if contract['company'] != company or contract['project'] != project:
        raise DomainError('contract_integrity', 'The contract source scope is inconsistent.', 409)
    if lock:
        revisions = [value['id']] if kind == 'revision' else [value['contract_revision']] if kind == 'sov' else []
        if kind in {'line', 'policy'}:
            revisions = [repository.read('sov', value['sov_version'], lock=True)['contract_revision']] if kind == 'line' else []
        lock_sources(contract, actor, revision_ids=revisions)
    else:
        sources.party_snapshot(company, project, contract['definition'], actor, allow_disabled=True)
    if kind != 'contract':
        document_sources.verify(company, project, value['source_citations'], actor, lock=lock)
        if 'units' in value:
            for registered in value['units']:
                if units.qualified(registered['id'], lock=lock, allow_disabled=True) != registered:
                    raise DomainError('stale_unit', 'The native SOV unit revision changed.', 412)
    return value


def create_contract(company, project, operation_id, definition):
    # Closed validation executes before any effect or receipt is created.
    if type(definition) is not dict:
        core.fail('Supply a closed contract definition.')
    currency = units.currency_policy(definition.get('currency'))
    core.definition(definition, currency['currency_exponent'])
    def effect(actor, project_doc):
        require_project(company, project, ability='contract.read', actor=actor, lock=True)
        currency_policy = units.currency_policy(definition['currency'], lock=True)
        party = sources.party_snapshot(company, project, definition, actor, lock=True)
        core.definition(definition, currency_policy['currency_exponent'])
        value = _new(actor, company, project, status='draft', definition=deepcopy(definition), currency_policy=currency_policy,
                     origin='server_created_fin01', party_at_creation=party, business_revision=1, revision_number=0, draft_revision=None, accepted_revision=None)
        value['creation_admission'] = sources.admission(value, lock=True)
        repository.insert('contract', value, contract_number=definition['number'], kind=definition['kind'], direction=definition['direction'],
                          party_type=definition['party_type'], party=definition['party'], currency=definition['currency'],
                          original_amount=definition['original_value']['amount'], revision_number=0)
        return {'contract': value, 'version': version(value), 'history_id': _event(actor, value, operation_id, 'contract.created', value)}
    return run_command(company=company, project=project, operation_id=operation_id, command='contract.create.v1',
                       payload={'definition': definition}, ability='contract.write', effect=effect)


def author_revision(company, project, operation_id, contract_id, expected_version, terms, retainage_policy, lines, source_citations):
    core.identifier(contract_id)
    core.visible(expected_version, 'expected_version', 64)
    core.terms(terms)
    def effect(actor, project_doc):
        raw_contract = repository.read('contract', contract_id, lock=True)
        if raw_contract['company'] != company or raw_contract['project'] != project:
            raise DomainError('not_found', 'This construction contract record is not available.', 404)
        if type(lines) is not list or not 1 <= len(lines) <= 100:
            core.fail('Supply one through 100 stable SOV lines.', 'lines')
        input_units = []
        for row in lines:
            if type(row) is not dict or type(row.get('quantity')) is not dict:
                core.fail('Supply typed quantities for each stable SOV line.', 'lines')
            input_units.append(core.identifier(row['quantity'].get('unit_id'), 'quantity.unit_id'))
        lock_sources(raw_contract, actor, extra_unit_ids=input_units)
        contract = scoped('contract', contract_id, company, project, actor, lock=True)
        if version(contract) != expected_version:
            raise DomainError('stale_contract', 'The contract changed. Author from its current version.', 412)
        sources.party_snapshot(company, project, contract['definition'], actor, lock=True)
        currency, exponent = contract['definition']['currency'], contract['currency_policy']['currency_exponent']
        if units.currency_policy(currency, lock=True) != contract['currency_policy']:
            raise DomainError('stale_currency_policy', 'The native currency policy changed; qualified policy migration is required.', 412)
        core.retainage(retainage_policy, currency, exponent)
        citations = document_sources.resolve(company, project, source_citations, actor, lock=True)
        if type(lines) is not list or not 1 <= len(lines) <= 100:
            core.fail('Supply one through 100 stable SOV lines.', 'lines')
        qualified = {unit_id: units.qualified(unit_id, lock=True) for unit_id in sorted(set(input_units))}
        total = core.sov(lines, currency, exponent, contract['definition']['original_value'], qualified, retainage_policy)
        if any(line['source_line_id'] is not None for line in lines):
            raise DomainError('estimate_line_link_unqualified', 'Source-line award mappings require the later qualified award integration. FIN01 authors explicit source citations and stable SOV lines.', 409)
        previous = scoped('revision', contract['draft_revision'], company, project, actor, lock=True) if contract['draft_revision'] else None
        accepted = scoped('revision', contract['accepted_revision'], company, project, actor, lock=True) if contract['accepted_revision'] else None
        if accepted:
            # FIN01 has no reader qualified to reduce certified/billed caps.
            # Retainage/billing-basis changes require later governed change control.
            if accepted['terms'] != terms or repository.read('policy', accepted['policy_revision'], lock=True)['policy'] != retainage_policy:
                raise DomainError('corrective_process_required', 'Accepted commercial terms and retainage basis require a qualified governed contract change.', 409)
            accepted_sov = scoped('sov', accepted['sov_version'], company, project, actor, lock=True)
            core.preserve_accepted(accepted_sov['lines'], lines, contract_id=contract_id, revision_id=accepted['id'], sov_id=accepted_sov['id'], currency=currency)
        number = contract['revision_number'] + 1
        policy = _new(actor, company, project, contract=contract_id, revision_number=number,
                      predecessor=previous['policy_revision'] if previous else None, currency=currency, policy=deepcopy(retainage_policy), source_citations=citations)
        repository.insert('policy', policy, contract=contract_id, revision_number=number, predecessor=policy['predecessor'], currency=currency)
        sov_id, revision_id = str(uuid4()), str(uuid4())
        revision = _new(actor, company, project, id=revision_id, contract=contract_id, revision_number=number, predecessor=contract['draft_revision'],
                        accepted_predecessor=contract['accepted_revision'], terms=deepcopy(terms), policy_revision=policy['id'], sov_version=sov_id,
                        currency=currency, contract_cap=deepcopy(contract['definition']['original_value']), approved_changes={'amount': format(0, f'.{exponent}f'), 'currency': currency},
                        source_citations=citations, units=sorted(qualified.values(), key=lambda row: row['id']))
        repository.insert('revision', revision, contract=contract_id, revision_number=number, predecessor=revision['predecessor'],
                          policy_revision=policy['id'], currency=currency, billing_method=terms['billing_method'])
        sov = _new(actor, company, project, id=sov_id, contract=contract_id, contract_revision=revision_id, revision_number=number,
                   predecessor=previous['sov_version'] if previous else None, currency=currency, scheduled_total=total, lines=deepcopy(lines),
                   source_citations=citations, units=revision['units'])
        repository.insert('sov', sov, contract=contract_id, contract_revision=revision_id, revision_number=number, predecessor=sov['predecessor'], currency=currency, scheduled_amount=total['amount'])
        for sequence, authored in enumerate(lines, start=1):
            row = _new(actor, company, project, contract=contract_id, sov_version=sov_id, line_id=authored['line_id'], sequence=sequence,
                       line=deepcopy(authored), policy_revision=policy['id'], source_citations=citations)
            repository.insert('line', row, contract=contract_id, sov_version=sov_id, line_id=authored['line_id'], item_code=authored['item_code'],
                              unit=qualified[authored['quantity']['unit_id']]['target']['name'], quantity_amount=authored['quantity']['amount'],
                              scheduled_amount=authored['scheduled_amount']['amount'], currency=currency)
        contract.update(draft_revision=revision_id, revision_number=number, business_revision=contract['business_revision']+1)
        repository.update_contract(contract)
        return {'contract': contract, 'version': version(contract), 'revision': revision, 'policy': policy, 'sov': sov,
                'history_id': _event(actor, contract, operation_id, 'contract.revision.authored', revision)}
    return run_command(company=company, project=project, operation_id=operation_id, command='contract.revision.author.v1',
                       payload={'contract_id': contract_id, 'expected_version': expected_version, 'terms': terms, 'retainage_policy': retainage_policy,
                                'lines': lines, 'source_citations': source_citations}, ability='contract.write', effect=effect)


def get_record(company, project, kind, record_id):
    if type(kind) is not str or kind not in repository.DOCTYPES:
        core.fail('Choose a supported contract record kind.', 'kind')
    value = scoped(kind, record_id, company, project, current_actor())
    return {'record': value, 'version': version(value)}


def list_contracts(company, project, limit=20, cursor=None, count_mode='none'):
    from cipher_aec.api.paging import page_options, decode_cursor, signing_secret, page_result
    from cipher_aec.governance.context import authority_fingerprint
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    actor = current_actor()
    require_project(company, project, ability='contract.read', actor=actor)
    # Establish the complete effective party-visible set before deriving even a
    # has_more bit. A bounded set that cannot be fully authorized fails closed;
    # it never reveals an inaccessible off-page contract through totals/cursors.
    parties = frappe.db.sql('SELECT DISTINCT party_type,party FROM `tabCipher Construction Contract` WHERE company=%s AND project=%s LIMIT 201', (company,project), as_dict=True)
    if len(parties) > 200:
        raise DomainError('collection_scope_unqualified', 'This contract collection exceeds the bounded native-party authorization scope.', 409)
    for party in parties:
        sources.party_snapshot(company,project,{'party_type':party.party_type,'party':party.party},actor,allow_disabled=True)
    scope = {'route': 'contract.catalog', 'user': actor.user, 'person': actor.person_id, 'company': company, 'project': project,
             'authority': authority_fingerprint(actor, company, project)}
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    where, args = 'company=%s AND project=%s', [company, project]
    if last:
        where += ' AND (creation<%s OR (creation=%s AND name<%s))'; args.extend((last[0], last[0], last[1]))
    rows = frappe.db.sql('SELECT name,creation FROM `tabCipher Construction Contract` WHERE ' + where + ' ORDER BY creation DESC,name DESC LIMIT %s', (*args, limit+1), as_dict=True)
    page = rows[:limit]
    items = [scoped('contract', row.name, company, project, actor) for row in page]
    total = frappe.db.count('Cipher Construction Contract', {'company':company, 'project':project}) if count_mode == 'exact' else None
    return page_result(items, has_more=len(rows)>limit, last=[str(page[-1].creation), page[-1].name] if page else None,
                       scope=scope, limit=limit, count_mode=count_mode, total=total)


def authorize_receipt(actor, company, project, result):
    require_project(company, project, ability='contract.read', actor=actor, lock=True)
    records, revision_ids, contract_ids = [], set(), set()
    for key in repository.DOCTYPES:
        if key not in result:
            continue
        value = repository.read(key, result[key]['id'], lock=True)
        if value['company'] != company or value['project'] != project:
            raise DomainError('not_found', 'This contract receipt is not available.', 404)
        records.append((key,value))
        contract_ids.add(value['id'] if key == 'contract' else value['contract'])
        if key == 'revision': revision_ids.add(value['id'])
        if key == 'sov': revision_ids.add(value['contract_revision'])
        if key == 'line': revision_ids.add(repository.read('sov',value['sov_version'],lock=True)['contract_revision'])
    if len(contract_ids) != 1:
        raise DomainError('contract_integrity', 'A contract command receipt must bind exactly one aggregate.', 409)
    contract = repository.read('contract',next(iter(contract_ids)),lock=True)
    # Old receipt sources may use units absent from BOTH current aggregate heads.
    # Collect every old revision before any scoped check can lock the party.
    lock_sources(contract,actor,revision_ids=revision_ids)
    for key,value in records:
        scoped(key,value['id'],company,project,actor,lock=True)
