"""Static independently reviewed full-pursuit award action; inactive by default."""
from copy import deepcopy
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_company
from . import repository,service,team
from .effect import ACTION


def _scope(scope_type,project):
    if scope_type!='Company' or project is not None:raise DomainError('not_found','This Company award action is not available.',404)


def authorize_subject(*,actor,company,project,subject_id,phase,lock=False,manifest=None,scope_type):
    _scope(scope_type,project)
    plan=service.authorize_plan(company,subject_id,actor,lock=lock)
    if manifest is not None and (manifest.get('effect',{}).get('action')!=ACTION or manifest['effect'].get('award_revision_id')!=plan['id']
            or manifest['effect'].get('plan_digest')!=digest(plan) or manifest['effect'].get('plan')!=plan):
        raise DomainError('approval_integrity','The exact original award plan cannot be verified.',409)
    if phase in {'request','execute'}:
        require_company(company,ability='commercial.award',actor=actor,lock=lock)
        require_company(company,ability='project.team.delegate',actor=actor,lock=lock)
        if actor.person_id!=plan['author_person'] or actor.person_id!=plan['definition']['team']['delegator_person']:
            raise DomainError('award_requester_required','The exact current delegator and plan author must request and execute this award.',403)
        from cipher_aec.commercial.native import can_create
        can_create('Project',actor);can_create('Sales Order',actor)
        team.authorize(company,plan['definition']['team'],actor,lock=lock)
    if phase=='review' and actor.person_id in {plan['author_person'],plan['definition']['team']['delegator_person']}:
        raise DomainError('independent_award_review_required','A different canonical human must review the exact award and team.',403)
    return plan


def approval_manifest(*,actor,company,project,subject_id,expected_version,lock=False,scope_type):
    _scope(scope_type,project)
    plan=authorize_subject(actor=actor,company=company,project=None,subject_id=subject_id,phase='manifest',lock=lock,scope_type=scope_type)
    parent=repository.read('handoff',plan['handoff'],company,lock=lock)
    if expected_version!=digest(plan) or parent['current_revision']!=subject_id or parent['status']!='draft' or parent['adoption']:
        raise DomainError('stale_award','Review the exact current unadopted handoff plan.',412)
    built=service._build(company,parent,plan['definition'],actor,ids=plan['ids'],lock=lock,requester_required=False)
    if any(plan.get(k)!=v for k,v in built.items()):
        raise DomainError('stale_award_sources','Award source/native/cost/team policy facts changed. Author a new plan.',412)
    return {'subject':{'doctype':'Cipher Award Handoff Revision','name':subject_id,
            'label':plan['definition']['project_definition']['project_name']+' · Full award plan '+str(plan['revision_number'])},
        'sources':[r['citation'] for r in plan['source_facts']['award_evidence']],
        'effect':{'action':ACTION,'award_id':parent['id'],'award_revision_id':subject_id,'plan_digest':digest(plan),'plan':deepcopy(plan),
            'destination_policy':'one-new-project-full-pursuit-v1','native_order_state':'draft','native_quotation_effect':'none',
            'initial_team':deepcopy(plan['definition']['team']),'controls_plan_digest':digest(plan['controls_plan'])},
        'summary':{'project_name':plan['definition']['project_definition']['project_name'],'pursuit':parent['pursuit'],'issue':plan['issue'],
            'selling_value':{'amount':sum_selling(plan),'currency':plan['controls_plan']['currency']},
            'accepted_cost_budget':plan['controls_plan']['totals'],'team_members':len(plan['definition']['team']['members']),
            'implicit_creator_access':False,'contract_state':'draft','certified_or_billed_floor':False,'external_transmission':False}}


def sum_selling(plan):
    from decimal import Decimal
    exponent=plan['controls_plan']['currency_exponent']
    return format(sum((Decimal(r['amount']) for r in plan['lines']),Decimal(0)),f'.{exponent}f')


def apply_award(*,actor,company,project,manifest,packet_id,decision_id,operation_id,scope_type):
    _scope(scope_type,project)
    from .adoption import apply
    return apply(actor=actor,company=company,manifest=manifest,packet_id=packet_id,decision_id=decision_id,operation_id=operation_id)
