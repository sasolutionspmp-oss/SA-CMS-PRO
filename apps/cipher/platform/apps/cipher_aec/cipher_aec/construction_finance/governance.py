"""Static GOV handler: accepting a baseline never executes a legal contract.

No certificate, native transaction, posting, payable, or legal execution is created.
"""
from datetime import datetime, timezone
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_project
from . import core, repository, sources
from .service import scoped, version, lock_sources

ACTION = 'contract.baseline.activate.v1'


def authorize_subject(*, actor, company, project, subject_id, phase, lock=False, manifest=None):
    require_project(company, project, ability='contract.read', actor=actor, lock=lock)
    if lock:
        raw = repository.read('contract', subject_id, lock=True)
        if raw['company'] != company or raw['project'] != project:
            raise DomainError('not_found', 'This construction contract record is not available.', 404)
        lock_sources(raw, actor, revision_ids=[manifest['effect']['revision_id']] if manifest else [])
    contract = scoped('contract', subject_id, company, project, actor, lock=lock)
    if phase in {'request', 'execute'}:
        require_project(company, project, ability='contract.write', actor=actor, lock=lock)
    revision_id = manifest['effect']['revision_id'] if manifest else contract['draft_revision']
    if revision_id:
        revision = scoped('revision', revision_id, company, project, actor, lock=lock)
        if revision['contract'] != subject_id:
            raise DomainError('contract_integrity', 'The approval source does not belong to this contract.', 409)
        scoped('policy', revision['policy_revision'], company, project, actor, lock=lock)
        scoped('sov', revision['sov_version'], company, project, actor, lock=lock)
    return contract


def approval_manifest(*, actor, company, project, subject_id, expected_version, lock=False):
    contract = authorize_subject(actor=actor, company=company, project=project, subject_id=subject_id, phase='read', lock=lock)
    project_doc = require_project(company, project, actor=actor, lock=lock)
    if project_doc.status in {'Completed', 'Cancelled'}:
        raise DomainError('project_closed', 'This Project is closed for new construction baseline effects.', 409)
    if version(contract) != expected_version:
        raise DomainError('stale_contract', 'The exact contract version changed. Request fresh review.', 412)
    if not contract['draft_revision'] or contract['draft_revision'] == contract['accepted_revision']:
        raise DomainError('no_unaccepted_baseline', 'Author an unaccepted contract revision before requesting baseline review.', 409)
    revision = scoped('revision', contract['draft_revision'], company, project, actor, lock=lock)
    policy = scoped('policy', revision['policy_revision'], company, project, actor, lock=lock)
    sov = scoped('sov', revision['sov_version'], company, project, actor, lock=lock)
    if revision['accepted_predecessor'] != contract['accepted_revision']:
        raise DomainError('stale_contract', 'This draft no longer succeeds the accepted baseline.', 412)
    if contract['accepted_revision']:
        accepted = scoped('revision', contract['accepted_revision'], company, project, actor, lock=lock)
        previous_sov = scoped('sov', accepted['sov_version'], company, project, actor, lock=lock)
        core.preserve_accepted(previous_sov['lines'], sov['lines'], contract_id=subject_id, revision_id=accepted['id'], sov_id=previous_sov['id'], currency=contract['definition']['currency'])
        floor = {'provider': 'qualified_fin03_reader_unavailable', 'source_version': accepted['id'], 'source_watermark': digest(previous_sov),
                 'policy': 'preserve_all_accepted_caps_and_basis', 'correction_authority': None}
    else:
        floor = sources.require_initial_admission(contract, lock=lock)
    from cipher_aec.estimating import units
    currency_policy = units.currency_policy(contract['definition']['currency'], lock=lock)
    if currency_policy != contract['currency_policy']:
        raise DomainError('stale_currency_policy', 'The native currency policy changed before baseline acceptance.', 412)
    for registered in revision['units']:
        if units.qualified(registered['id'], lock=lock) != registered:
            raise DomainError('stale_unit', 'A new baseline requires enabled qualified native units.', 412)
    party = sources.party_snapshot(company, project, contract['definition'], actor, lock=lock)
    return {'subject': {'doctype': repository.DOCTYPES['contract'], 'name': subject_id, 'label': contract['definition']['number']},
            'sources': [{'kind': 'contract', 'id': subject_id, 'version': version(contract)},
                        {'kind': 'terms', 'id': revision['id'], 'version': digest(revision)},
                        {'kind': 'retainage', 'id': policy['id'], 'version': digest(policy)},
                        {'kind': 'sov', 'id': sov['id'], 'version': digest(sov)}, {'kind': 'currency_policy', **currency_policy}, {'kind': 'native_party', **party},
                        {'kind': 'floor_admission', **floor}],
            'effect': {'contract_id': subject_id, 'contract_version': version(contract), 'revision_id': revision['id'], 'accepted_predecessor': contract['accepted_revision'],
                       'sov_version': sov['id'], 'policy_revision': policy['id'], 'currency': contract['definition']['currency'], 'contract_cap': contract['definition']['original_value'],
                       'legal_execution': False, 'certification': False, 'posting': False},
            'summary': {'label': 'Accept authored construction baseline', 'contract_number': contract['definition']['number'], 'scheduled_total': sov['scheduled_total'],
                        'line_count': len(sov['lines']), 'legal_execution': False, 'certification': False, 'posting': False}}


def apply_activation(*, actor, company, project, manifest, packet_id, decision_id, operation_id):
    from cipher_aec.governance.approvals import require_approval_effect
    effect = manifest['effect']
    require_approval_effect(action=ACTION, subject_id=effect['contract_id'], packet_id=packet_id)
    current = approval_manifest(actor=actor, company=company, project=project, subject_id=effect['contract_id'], expected_version=effect['contract_version'], lock=True)
    if current != manifest:
        raise DomainError('stale_contract', 'The reviewed exact construction baseline changed.', 412)
    contract = scoped('contract', effect['contract_id'], company, project, actor, lock=True)
    contract.update(accepted_revision=effect['revision_id'], business_revision=contract['business_revision']+1, status='baseline_accepted',
                    activation={'packet_id': packet_id, 'decision_id': decision_id, 'operation_id': operation_id,
                                'accepted_at': datetime.now(timezone.utc).isoformat(), 'accepted_person': actor.person_id,
                                'manifest_hash': digest(manifest), 'legal_execution': False, 'certification': False, 'posting': False})
    repository.update_contract(contract)
    return {'contract': contract, 'version': version(contract), 'accepted_revision': effect['revision_id'], 'sov_version': effect['sov_version'],
            'policy_revision': effect['policy_revision'], 'legal_execution': False, 'certification': False, 'posting': False}
