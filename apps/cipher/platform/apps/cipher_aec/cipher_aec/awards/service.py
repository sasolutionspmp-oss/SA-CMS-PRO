"""Company-origin award plans; canonical original sources stay Company owned."""
from copy import deepcopy
from datetime import datetime,timezone
from uuid import uuid4
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.commands import run_company_command
from cipher_aec.governance.context import current_actor,require_company,require_project
from cipher_aec.governance.history import append_company_event
from . import contracts,repository,sources,team

SCHEMA='cipher.award.handoff.v1'
PLAN_SCHEMA='cipher.award.plan.v1'


def _base(actor,company,**values):
    return {'id':str(uuid4()),'schema':SCHEMA,'scope_type':'Company','company':company,'project':None,
        'author_person':actor.person_id,'author_user':actor.user,'created_at':datetime.now(timezone.utc).isoformat(),**values}


def _actor(company,actor=None,*,write=False,lock=False):
    actor=actor or current_actor()
    require_company(company,ability='commercial.award' if write else 'commercial.read',actor=actor,lock=lock)
    return actor


def _event(actor,company,operation_id,kind,value,event):
    return append_company_event(actor=actor,company=company,operation_id=operation_id,event=event,
        subject_type=repository.TYPES[kind],subject_id=value['id'],details={'record_digest':digest(value)})


def _public_handoff(value,actor):
    standing='not_created';project_id=None;adopted=None
    if value['adoption']:
        adopted=repository.read('adoption',value['adoption'],value['company'])
        project_id=adopted['target_project']
        try:require_project(value['company'],project_id,actor=actor);standing='available'
        except DomainError as error:
            if error.status not in {403,404}:raise
            standing='not_available'
    return {'handoff':value,'version':digest(value),'adoption':adopted,'project_access':{'standing':standing,'project_id':project_id},'availability':availability()}


def create_handoff(company,issue_id,operation_id):
    contracts.identifier(issue_id)
    def effect(actor,record):
        from cipher_aec.commercial.outputs import issue_source_reference
        from cipher_aec.commercial.service import _read
        issue=issue_source_reference(company,issue_id,actor)['issue']
        proposal=_read('proposal',issue['proposal'],company,actor)[1]
        pursuit=_read('pursuit',proposal['pursuit'],company,actor)[1]
        old=frappe.db.sql('SELECT name FROM `tabCipher Award Handoff` WHERE company=%s AND (pursuit=%s OR opportunity=%s) FOR UPDATE',
            (company,pursuit['id'],pursuit['opportunity']))
        if old:raise DomainError('handoff_exists','This pursuit already has its canonical full award handoff.',409)
        value=_base(actor,company,status='draft',pursuit=pursuit['id'],opportunity=pursuit['opportunity'],issue=issue_id,original_issue=issue_id,
            revision_number=0,current_revision=None,adoption=None)
        repository.write('handoff',value)
        _event(actor,company,operation_id,'handoff',value,'award.handoff.created')
        return _public_handoff(value,actor)
    return run_company_command(company=company,operation_id=operation_id,command='award.handoff.create.v1',payload={'issue_id':issue_id},ability='commercial.award',effect=effect)


def _build(company,parent,definition,actor,*,ids=None,lock=False,requester_required=True):
    definition=contracts.definition(definition)
    issue=sources.issue_record(company,definition['issue_id'],lock=lock)
    mapped=contracts.selected_sales_lines(issue,definition['line_mappings'],definition['native_order_definition']['transaction_date'])
    if definition['native_order_definition']['delivery_date']!=max(r['delivery_date'] for r in mapped):
        raise DomainError('invalid_award','The reviewed order delivery date must equal the latest selected line date.',422)
    ids=ids or {'id':str(uuid4()),'profile_id':str(uuid4()),'contract_id':str(uuid4()),'adoption_id':str(uuid4()),
        'line_ids':{r['proposal_line_id']:str(uuid4()) for r in mapped}}
    lines=[{**row,'award_line_id':ids['line_ids'][row['proposal_line_id']]} for row in mapped]
    with sources.admitted(company,issue,definition,lines,actor,lock=lock) as resource_token:
        facts=sources.facts(company,issue['id'],definition,lines,actor,lock=lock,resource_token=resource_token,require_create=requester_required)
    if facts['pursuit']!=parent['pursuit'] or facts['opportunity']!=parent['opportunity']:
        raise DomainError('award_source_conflict','A handoff reserves exactly one Company pursuit and native Opportunity.',409)
    policy=team.authorize(company,definition['team'],actor,lock=lock,requester_required=requester_required)
    from cipher_aec.construction_finance.core import definition as contract_definition
    contract_definition(definition['contract_definition'],facts['controls_plan']['currency_exponent'])
    contract=definition['contract_definition'];order=definition['native_order_definition']
    if contract['kind']!='prime' or contract['direction']!='receivable' or contract['party_type']!='Customer' or contract['party']!=order['customer'] or contract['currency']!=issue['composition']['currency'] or contract['original_value']!={'amount':issue['pricing']['total'],'currency':issue['composition']['currency']}:
        raise DomainError('award_contract_conflict','The initial prime draft must equal the exact Customer/currency/issued selling value.',409)
    participants=sorted({definition['team']['delegator_person']}|{r['person_id'] for r in definition['team']['members']})
    approved_team={row['person_id'] for row in definition['team']['members']}
    if any(n.get('accountable_person') is not None and n['accountable_person'] not in approved_team for n in definition['wbs_nodes']):
        raise DomainError('invalid_award_team','WBS accountability must name an explicitly approved team person.',422)
    return {'ids':ids,'definition':definition,'issue':issue['id'],'issue_digest':facts['issue_digest'],'source_facts':{k:deepcopy(v) for k,v in facts.items() if k not in {'issue','acceptance','controls_plan'}},
        'controls_plan':facts['controls_plan'],'lines':lines,'participants':participants,'delegation_policy':policy,'resource_plan':resource_token}


def plan_handoff(company,handoff_id,expected_version,definition,operation_id):
    contracts.identifier(handoff_id);definition=contracts.definition(definition)
    _actor(company,write=True)
    people=team.participant_names(definition['team'])
    def effect(actor,record):
        parent=repository.read('handoff',handoff_id,company,lock=True)
        if digest(parent)!=expected_version:raise DomainError('stale_award','Refresh the current canonical handoff before planning.',412)
        if parent['status']!='draft':raise DomainError('award_already_adopted','A full pursuit award can be adopted only once.',409)
        built=_build(company,parent,definition,actor,lock=True)
        value=_base(actor,company,id=built['ids']['id'],schema=PLAN_SCHEMA,status='planned',handoff=handoff_id,
            revision_number=parent['revision_number']+1,predecessor=parent['current_revision'],**built)
        from cipher_aec.estimating import scopes
        from cipher_aec.estimating.lockplan import prepared
        with scopes.activate('Company',company,None),prepared(built['resource_plan'],actor,company,lock=True):
            repository.write('revision',value)
            parent.update(current_revision=value['id'],revision_number=value['revision_number'],issue=value['issue'])
            repository.write('handoff',parent,update=True)
        _event(actor,company,operation_id,'revision',value,'award.plan.authored')
        return {'plan':value,'version':digest(value),'handoff':parent,'handoff_version':digest(parent)}
    return run_company_command(company=company,operation_id=operation_id,command='award.plan.author.v1',
        payload={'handoff_id':handoff_id,'expected_version':expected_version,'definition':definition},ability='commercial.award',effect=effect,participant_people=people)


def participant_people(company,revision_id,*,lock=False):
    value=repository.read('revision',revision_id,company,lock=lock)
    declared=sorted(set(team.participant_names(value['definition']['team']))|{value['author_person']})
    if value['participants']!=declared:raise DomainError('award_integrity','The immutable participant discovery set cannot be verified.',409)
    return tuple(declared)


def authorize_plan(company,revision_id,actor=None,*,lock=False):
    actor=_actor(company,actor,lock=lock)
    require_company(company,ability='project.cost.read',actor=actor,lock=lock)
    value=repository.read('revision',revision_id,company,lock=lock)
    from .sources import authorize_historical
    authorize_historical(company,value,actor,lock=lock)
    return value


def get_plan(company,revision_id):
    value=authorize_plan(company,revision_id)
    return {'plan':value,'version':digest(value),'availability':availability()}


def get_handoff(company,handoff_id,actor=None,*,lock=False):
    actor=_actor(company,actor,lock=lock)
    value=repository.read('handoff',handoff_id,company,lock=lock)
    if value['current_revision']:authorize_plan(company,value['current_revision'],actor,lock=lock)
    else:
        from cipher_aec.commercial.outputs import issue_source_reference
        issue_source_reference(company,value['issue'],actor,lock=lock)
    return _public_handoff(value,actor)


def approval_subject(company,revision_id):
    value=authorize_plan(company,revision_id)
    parent=repository.read('handoff',value['handoff'],company)
    return {'revision_id':value['id'],'record_digest':digest(value),'handoff_id':parent['id'],
        'is_current':parent['current_revision']==revision_id and parent['status']=='draft','current_revision':parent['current_revision'],
        'adoption_id':parent['adoption'],**availability()}


def authorize_receipt(actor,company,result,*,lock=False):
    _actor(company,actor,lock=lock)
    original_plan=result.get('plan')
    if original_plan:
        actual=authorize_plan(company,original_plan['id'],actor,lock=lock)
        if actual!=original_plan:raise DomainError('award_integrity','The exact original plan receipt cannot be verified.',409)
    snapshot=result.get('handoff')
    if snapshot:
        current=repository.read('handoff',snapshot['id'],company,lock=lock)
        mutable={'current_revision','revision_number','issue','status','adoption'}
        if {k:v for k,v in current.items() if k not in mutable}!={k:v for k,v in snapshot.items() if k not in mutable}:
            raise DomainError('award_integrity','The original handoff receipt lost its immutable pursuit reservation.',409)
        if original_plan:
            if snapshot['current_revision']!=original_plan['id'] or original_plan['handoff']!=snapshot['id'] or snapshot['issue']!=original_plan['issue']:
                raise DomainError('award_integrity','The original handoff receipt lost its exact authored plan.',409)
        else:
            # A creation receipt predates every plan. Its source is the original
            # Issue, never a later working head or subsequently private plan.
            from cipher_aec.commercial.outputs import issue_source_reference
            from cipher_aec.commercial.service import _read
            issue=issue_source_reference(company,snapshot['issue'],actor,lock=lock)['issue']
            pursuit=_read('proposal',issue['proposal'],company,actor,lock=lock)[1]['pursuit']
            if pursuit!=snapshot['pursuit']:
                raise DomainError('award_integrity','The original issued pursuit cannot be verified.',409)
    if result.get('adoption'):
        value=repository.read('adoption',result['adoption']['id'],company,lock=lock)
        if value!=result['adoption']:raise DomainError('award_integrity','The exact original adoption receipt cannot be verified.',409)
        authorize_plan(company,value['award_revision'],actor,lock=lock)


def availability():
    """Writer qualification is server-owned, independently of a user's duties."""
    from cipher_aec.governance.domain_approvals import ACTIONS
    action=ACTIONS.get('award.project.create.v1')
    enabled=bool(action and action.enabled and action.scopes==('Company',))
    return {'action':'award.project.create.v1','action_available':enabled,
        'disabled_reason':None if enabled else 'The full award writer is awaiting source and runtime qualification.'}


def source_preview(company,issue_id):
    actor=_actor(company)
    for ability in ('document.read','estimate.read','project.cost.read'):
        require_company(company,ability=ability,actor=actor)
    contracts.identifier(issue_id)
    from cipher_aec.commercial.outputs import issue_source_reference
    from cipher_aec.commercial.service import _read
    from cipher_aec.estimating import scopes,repository as estimates
    from cipher_aec.estimating.company_service import accepted_baseline_reference
    with scopes.activate('Company',company,None):
        issue=issue_source_reference(company,issue_id,actor)['issue']
        proposal=_read('proposal',issue['proposal'],company,actor)[1]
        pursuit=_read('pursuit',proposal['pursuit'],company,actor)[1]
        if not issue.get('accepted_estimate'):
            raise DomainError('accepted_baseline_required','This full award requires the exact issued accepted cost baseline.',409)
        baseline=accepted_baseline_reference(company,issue['accepted_estimate']['acceptance_id'],actor)
        if baseline!=issue['accepted_estimate'] or baseline['pursuit_id']!=pursuit['id']:
            raise DomainError('award_integrity','The issued accepted baseline lineage cannot be verified.',409)
        acceptance=estimates.read('acceptance',baseline['acceptance_id'])
    existing=frappe.db.sql('SELECT name FROM `tabCipher Award Handoff` WHERE company=%s AND pursuit=%s AND opportunity=%s',(company,pursuit['id'],pursuit['opportunity']))
    if len(existing)>1:raise DomainError('award_integrity','The canonical full-pursuit handoff reservation is ambiguous.',409)
    handoff=get_handoff(company,existing[0][0],actor) if existing else None
    qualification=sources.input_qualification(acceptance)
    standing=availability()
    if not qualification['eligible']:standing.update(action_available=False,disabled_reason=qualification['disabled_reason'])
    return {'company':company,'issue':issue,'issue_digest':digest(issue),'pursuit':pursuit,'handoff':handoff,'input_qualification':qualification,
        'accepted_baseline':acceptance,'accepted_baseline_digest':digest(acceptance),'availability':standing}


def preview_plan(company,handoff_id,expected_version,definition):
    actor=_actor(company,write=True)
    parent=repository.read('handoff',handoff_id,company)
    if digest(parent)!=expected_version:raise DomainError('stale_award','Refresh the current canonical handoff before previewing.',412)
    if parent['status']!='draft':raise DomainError('award_already_adopted','A full pursuit award can be adopted only once.',409)
    built=_build(company,parent,definition,actor)
    return {key:deepcopy(built[key]) for key in ('definition','issue','issue_digest','source_facts','controls_plan','lines','participants','delegation_policy')} | {'availability':availability()}


def delegation_policy(company):
    actor=_actor(company)
    value=team.policy(company,actor,require_delegator=False)
    return {'policy':value,'requester_person':actor.person_id,'availability':availability()}


def team_choices(company,query='',limit=50,cursor=None,count_mode='none'):
    from cipher_aec.api.contracts import text
    from .listing import listed
    actor=_actor(company)
    require_company(company,ability='project.team.delegate',actor=actor)
    team.policy(company,actor)
    query=text(query,'Search',80,required=False).strip()
    return listed(company=company,actor=actor,kind='person',reader=lambda person:team.eligible_person(company,person),
        query=query,limit=limit,cursor=cursor,count_mode=count_mode)


def list_handoffs(company,limit=50,cursor=None,count_mode='none'):
    from .listing import listed
    actor=_actor(company)
    return listed(company=company,actor=actor,kind='handoff',reader=lambda name:get_handoff(company,name,actor),
        limit=limit,cursor=cursor,count_mode=count_mode)


def authorize_history(company,subject_type,subject_id,actor,*,event_name=None,details=None):
    if subject_type=='Cipher Award Handoff':
        if event_name!='award.handoff.created':raise DomainError('history_integrity','The exact award creation event is required.',409)
        current=repository.read('handoff',subject_id,company)
        original={**current,'status':'draft','issue':current['original_issue'],'revision_number':0,'current_revision':None,'adoption':None}
        if (details or {}).get('record_digest')!=digest(original):raise DomainError('history_integrity','The original award creation snapshot cannot be verified.',409)
        authorize_receipt(actor,company,{'handoff':original})
        return original
    kind={repository.TYPES[key]:key for key in ('revision','adoption','line')}.get(subject_type)
    if not kind:raise DomainError('not_found','This award history is not available.',404)
    value=repository.read(kind,subject_id,company)
    return authorize_plan(company,value['id'] if kind=='revision' else value['award_revision'],actor)
