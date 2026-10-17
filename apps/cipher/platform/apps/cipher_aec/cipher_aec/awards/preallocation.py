"""Literal NEW award allocation before any UOM/currency/native source locks.

The reviewed source plan contains no destination Project name. This temporary
identity is rolled back with the outer Company command on every later refusal.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime,timezone
import json
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_company
from .effect import ACTION
from . import repository,team,runtime

_creating=ContextVar('cipher_literal_award_project_allocation',default=None)
_allocated=ContextVar('cipher_literal_award_allocated_project',default=None)


def _refuse(message):raise DomainError('award_preallocation_denied',message,409)


def _basic(packet,actor,operation_id,participants):
    from cipher_aec.governance import approvals,domain_approvals
    domain_approvals.spec_for(ACTION,'Company')
    if packet.action!=ACTION or packet.scope_type!='Company' or packet.project or packet.requester_person!=actor.person_id:
        _refuse('Only the exact Company award requester may allocate its reviewed destination.')
    outer=json.loads(packet.manifest_json)
    if digest(outer)!=packet.manifest_hash or outer.get('action')!=ACTION or outer.get('scope_type')!='Company' or outer.get('company')!=packet.company or outer.get('project') is not None or outer.get('requester_person')!=actor.person_id:
        _refuse('The exact Company award manifest cannot be verified.')
    plan=repository.read('revision',packet.subject_id,packet.company,lock=True)
    effect=outer.get('domain',{}).get('effect',{})
    if (packet.subject_type!='Cipher Award Handoff Revision' or outer.get('source_version')!=digest(plan)
            or packet.source_version!=digest(plan) or effect.get('action')!=ACTION or effect.get('award_revision_id')!=plan['id']
            or effect.get('award_id')!=plan['handoff'] or effect.get('plan_digest')!=digest(plan) or effect.get('plan')!=plan):
        _refuse('The reviewed immutable award plan cannot be verified.')
    from .service import participant_people
    if tuple(plan['participants'])!=participant_people(packet.company,plan['id'],lock=True):_refuse('The immutable participant set changed.')
    parent=repository.read('handoff',plan['handoff'],packet.company,lock=True)
    if parent['current_revision']!=plan['id'] or parent['status']!='draft' or parent['adoption']:
        raise DomainError('stale_award','The exact unadopted current award plan is required.',412)
    if approvals._consumption(packet,True):_refuse('An already consumed grant cannot allocate another Project.')
    decisions=approvals._decisions(packet,True)
    if not decisions or decisions[-1].decision!='Grant' or decisions[-1].actor_person==actor.person_id or decisions[-1].manifest_hash!=packet.manifest_hash:
        _refuse('An unwithdrawn independent Grant for this exact manifest is required.')
    if datetime.fromisoformat(packet.expires_at.replace('Z','+00:00'))<=datetime.now(timezone.utc):_refuse('The exact award Grant expired.')
    policy=approvals._policy(True,ACTION,'Company')
    if packet.policy_revision!=policy.name or outer.get('policy_hash')!=digest(json.loads(policy.definition_json)):
        _refuse('The current exact independent approval policy is required.')
    expected=set(plan['participants'])|{packet.requester_person,decisions[-1].actor_person}
    if set(participants)!=expected:
        raise DomainError('concurrent_change','The exact review participant changed. Retry this original operation after refreshing.',503)
    for ability in ('commercial.award','project.team.delegate','approval.execute'):
        require_company(packet.company,ability=ability,actor=actor,lock=True)
    if actor.person_id!=plan['author_person'] or actor.person_id!=plan['definition']['team']['delegator_person']:
        _refuse('The current explicit delegator and original plan author must execute.')
    from cipher_aec.commercial.native import can_create
    can_create('Project',actor)
    team.authorize(packet.company,plan['definition']['team'],actor,lock=True)
    return plan,decisions[-1]


def validate_native_project(doc):
    """Called only through the existing Project guard; no bypass outside scope."""
    state=_creating.get()
    if state is None:return False
    if (doc is not state['doc'] or not doc.is_new() or doc.flags.notify_update is not False
            or doc.get('amended_from') or getattr(doc.flags,'updater_reference',None) or getattr(doc,'_doc_before_save',None)):
        _refuse('Only the exact supported new Project instance may be allocated.')
    definition=state['plan']['definition'];project=definition['project_definition']
    expected={'company':state['company'],'project_name':project['project_name'],'customer':definition['native_order_definition']['customer'],
        'expected_start_date':project['expected_start_date'],'expected_end_date':project['expected_end_date'],'status':'Open','percent_complete_method':'Manual','cost_center':'','project_type':''}
    if any(str(doc.get(k) or '')!=str(v) for k,v in expected.items()) or doc.users or doc.project_template or doc.sales_order or doc.get('attachments'):
        _refuse('The allocated Project profile cannot add templates, users, linked orders or callbacks.')
    return True


def profile_context(value):
    active=_creating.get()
    if active is None or value.get('id')!=active['plan']['ids']['profile_id'] or value.get('project')!=active.get('project'):
        _refuse('An initial profile requires the exact active Project allocation.')
    if value!=active.get('profile'):_refuse('The initial profile must equal the exact allocation snapshot.')
    return deepcopy(active)


def current(*,company,packet_id,award_revision_id,operation_id,plan_digest):
    active=_allocated.get()
    expected={'company':company,'packet_id':packet_id,'award_revision_id':award_revision_id,'operation_id':operation_id,'plan_digest':plan_digest}
    if active is None or any(active.get(k)!=v for k,v in expected.items()):
        _refuse('The exact reviewed Project must have been allocated before source admission.')
    return deepcopy(active)


@contextmanager
def stage(packet,actor,operation_id,participants):
    """Only the shared NEW execute effect calls this literal stage."""
    if _allocated.get() is not None or _creating.get() is not None:_refuse('Award allocations cannot nest.')
    plan,decision=_basic(packet,actor,operation_id,participants)
    runtime.require_native_profile()
    state={'company':packet.company,'packet_id':packet.name,'decision_id':decision.name,'award_revision_id':plan['id'],
        'award_id':plan['handoff'],'plan_digest':digest(plan),'operation_id':operation_id,'plan':plan}
    doc=frappe.get_doc({'doctype':'Project','company':packet.company,'project_name':plan['definition']['project_definition']['project_name'],
        'customer':plan['definition']['native_order_definition']['customer'],'status':'Open','percent_complete_method':'Manual',
        'expected_start_date':plan['definition']['project_definition']['expected_start_date'],
        'expected_end_date':plan['definition']['project_definition']['expected_end_date'],'users':[],'project_template':None,'sales_order':None,'cost_center':None,'project_type':None,'amended_from':None})
    doc.flags.notify_update=False;state['doc']=doc
    runtime.begin_callback_stage(company=packet.company,operation_id=operation_id,packet_id=packet.name,award_revision_id=plan['id'],plan_digest=digest(plan))
    runtime.quiet_award_write(doc)
    token=_creating.set(state)
    try:
        doc.insert(ignore_permissions=True)
        # Project has no amended_from column in the pinned native schema. The
        # in-memory guard still rejects that property before native save_version.
        fields=('name','company','project_name','customer','expected_start_date','expected_end_date','status','percent_complete_method','cost_center','project_type','project_template','sales_order')
        rows=frappe.db.sql('SELECT '+','.join(fields)+' FROM `tabProject` WHERE name=%s FOR UPDATE',(doc.name,))
        expected=(doc.name,packet.company,plan['definition']['project_definition']['project_name'],plan['definition']['native_order_definition']['customer'],
            plan['definition']['project_definition']['expected_start_date'],plan['definition']['project_definition']['expected_end_date'],'Open','Manual','','','','')
        if len(rows)!=1 or tuple(str(v or '') for v in rows[0])!=expected:_refuse('The persisted supported Project must equal the exact reviewed minimal profile.')
        for doctype,filters in (('Task',{'project':doc.name}),('ToDo',{'reference_type':'Project','reference_name':doc.name}),('DocShare',{'share_doctype':'Project','share_name':doc.name})):
            if frappe.db.exists(doctype,filters):_refuse('Native Project creation produced an unqualified task, assignment or share.')
        state['project']=doc.name
        profile={'id':plan['ids']['profile_id'],'schema':'cipher.project-profile.v1','scope_type':'Project','company':packet.company,'project':doc.name,
            'author_person':actor.person_id,'author_user':actor.user,'created_at':datetime.now(timezone.utc).isoformat(),'status':'preallocated',
            'handoff':plan['handoff'],'award_revision':plan['id'],'adoption':None,'sales_order':None,'contract':None,
            'packet_id':packet.name,'decision_id':decision.name,'operation_id':operation_id,'plan_digest':digest(plan)}
        state['profile']=profile;repository.write('profile',profile)
    finally:_creating.reset(token)
    state.pop('doc',None);token=_allocated.set(deepcopy(state))
    try:yield deepcopy(state)
    finally:_allocated.reset(token)
