"""One exact award-owned initial draft; no nested public FIN command or duties."""
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime,timezone
import frappe
from cipher_aec.api.contracts import digest,version_of
from cipher_aec.api.errors import DomainError
from cipher_aec.documents.provenance import is_prelocked
from cipher_aec.commercial.native import require_native
from cipher_aec.estimating import units
from . import core,repository,sources
from .award_admission import INITIAL_PROVIDER,ORIGIN

_constructing=ContextVar('cipher_exact_award_initial_contract',default=None)


def _active(company,project,plan,packet_id,decision_id,operation_id):
    from cipher_aec.awards.effect import require_award_effect
    return require_award_effect(company=company,project=project,award_id=plan['handoff'],award_revision_id=plan['id'],plan_digest=digest(plan),
        packet_id=packet_id,decision_id=decision_id,operation_id=operation_id)


def admission_preflight(*,actor,company,project,plan,packet_id,decision_id,operation_id,resource_token):
    """Before the SO write, under the same exact Customer mutex as FIN scans."""
    active=_active(company,project,plan,packet_id,decision_id,operation_id)
    required={'unit_ids':[],'currencies':[],'generated_sources':[],
        'native_refs':[{'doctype':'Customer','name':plan['definition']['native_order_definition']['customer']}]}
    if not is_prelocked(required,actor,company) or not is_prelocked(resource_token,actor,company):
        raise DomainError('source_prelock_required','Award admission requires its complete reviewed Customer/source union.',409)
    # Reentrant exact canonical Customer read proves this audited call path has
    # physically acquired the shared mutex before scanning any native order.
    customer=require_native('Customer',required['native_refs'][0]['name'],actor,lock=True)
    if customer.name!=required['native_refs'][0]['name']:
        raise DomainError('not_found','The canonical award Customer is unavailable.',404)
    prototype={'id':active['contract_id'],'company':company,'project':project,'definition':plan['definition']['contract_definition']}
    proof=sources.admission(prototype,lock=True)
    if proof['status'] not in {'new_contract_without_supported_obligations','qualified_award_observations'}:
        raise DomainError('activity_unqualified','Unknown or ambiguous native activity prevents this full award draft.',409)
    from cipher_aec.awards.effect import record_admission_preflight
    record_admission_preflight(proof)
    return proof


def create_initial_contract(*,actor,company,project,plan,packet_id,decision_id,operation_id,resource_token):
    active=_active(company,project,plan,packet_id,decision_id,operation_id)
    native=active.get('native_output');preflight=active.get('admission_preflight')
    if native is None or preflight is None or active['contract_definition_digest']!=digest(plan['definition']['contract_definition']):
        raise DomainError('award_contract_required','The exact admitted award and persisted order must precede its initial draft contract.',403)
    definition=deepcopy(plan['definition']['contract_definition'])
    required={'unit_ids':[],'currencies':[definition['currency']],'generated_sources':[],
        'native_refs':[{'doctype':'Customer','name':definition['party']}]}
    if not is_prelocked(required,actor,company) or not is_prelocked(resource_token,actor,company):
        raise DomainError('source_prelock_required','The initial contract requires the complete reviewed native source union.',409)
    policy=units.currency_policy(definition['currency'],lock=True,actor=actor)
    core.definition(definition,policy['currency_exponent'])
    customer=require_native('Customer',definition['party'],actor,lock=True)
    if customer.name!=definition['party'] or definition['kind']!='prime' or definition['direction']!='receivable' or definition['party_type']!='Customer':
        raise DomainError('award_contract_conflict','Create only the exact approved existing-Customer prime draft.',409)
    origin={'schema':'cipher.contract.award-origin.v1','handoff':plan['handoff'],'award_revision':plan['id'],'plan_digest':digest(plan),
        'adoption_id':active['adoption_id'],'source_company':company,'project':project,'issue':plan['issue'],'issue_digest':plan['issue_digest'],
        'accepted_estimate':deepcopy(plan['source_facts']['accepted_estimate']),'sales_order':native['sales_order'],
        'native_digest':native['native_digest'],'native_version':native['native_version'],'definition_digest':digest(definition),
        'packet_id':packet_id,'decision_id':decision_id,'operation_id':operation_id}
    admission={'provider':INITIAL_PROVIDER,'provider_version':1,'contract_id':active['contract_id'],'status':'qualified_award_draft_obligation',
        'channel_count':preflight['channel_count'],'source_watermark':digest({'origin':origin,'preflight':preflight})}
    value={'id':active['contract_id'],'company':company,'project':project,'author_person':actor.person_id,'author_user':actor.user,
        'created_at':datetime.now(timezone.utc).isoformat(),'status':'draft','definition':definition,'currency_policy':policy,'origin':ORIGIN,
        'party_at_creation':{'doctype':'Customer','name':customer.name,'version':version_of(customer),'disabled':bool(customer.get('disabled'))},
        'business_revision':1,'revision_number':0,'draft_revision':None,'accepted_revision':None,'award_origin':origin,'creation_admission':admission}
    token=_constructing.set(deepcopy(value))
    try:
        repository.insert('contract',value,contract_number=definition['number'],kind=definition['kind'],direction=definition['direction'],
            party_type=definition['party_type'],party=definition['party'],currency=definition['currency'],original_amount=definition['original_value']['amount'],revision_number=0)
    finally:_constructing.reset(token)
    return value


def validate_new_contract(value):
    """Controller exception is this exact staged JSON, never trusted_write alone."""
    expected=_constructing.get()
    if expected is None or value!=expected:
        raise DomainError('award_contract_required','Only the exact literal award factory may create this origin.',403)
    origin=value['award_origin']
    from cipher_aec.awards.effect import require_award_effect
    active=require_award_effect(company=value['company'],project=value['project'],award_id=origin['handoff'],award_revision_id=origin['award_revision'],
        plan_digest=origin['plan_digest'],packet_id=origin['packet_id'],decision_id=origin['decision_id'],operation_id=origin['operation_id'])
    if value['id']!=active['contract_id'] or value['author_person']!=active['actor_person'] or value['author_user']!=active['actor_user']:
        raise DomainError('award_contract_conflict','The initial draft must retain the exact approved author and identity.',409)
    return active
