"""Explicit Company delegation and bounded canonical initial Project team."""
import json
from copy import deepcopy
import frappe
from frappe.utils import nowdate
from cipher_aec.api.contracts import canonical_json,digest,text
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_company,PROJECT_ABILITIES,trusted_write

POLICY_SCHEMA='cipher.project-team.delegation-policy.v1'
# A literal reviewed policy, never an automatic mirror of future capabilities.
ALLOWED=('project.read','project.write','task.create','document.read','document.write','ricky.run','approval.request','approval.decide','approval.execute','estimate.read','estimate.write','contract.read','contract.write','wbs.read','budget.read')
POLICY={'schema':POLICY_SCHEMA,'version':1,'max_members':25,'allowed_project_abilities':list(ALLOWED),
    'delegator_must_be_requester':True,'team_identity_kind':'Human','eligibility_ability':'company.read','implicit_creator_access':False,'role_copy':False}


def install_policy(company):
    from cipher_aec.governance.context import assert_synthetic_site
    assert_synthetic_site()
    if frappe.session.user!='Administrator':raise DomainError('administrator_required','Only the site operator can install this reviewed delegation policy.',403)
    frappe.db.sql('SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE',(company,))
    name='CIPHER-TEAM-'+digest({'company':company,'policy':POLICY})[:32]
    if not frappe.db.exists('Cipher Project Delegation Policy Revision',name):
        with trusted_write():frappe.get_doc({'doctype':'Cipher Project Delegation Policy Revision','company':company,'version':1,'enabled':1,
            'definition_json':canonical_json(POLICY),'definition_digest':digest(POLICY)}).insert(ignore_permissions=True,set_name=name)
    return {'id':name,'company':company,'version':1,'digest':digest(POLICY)}


def policy(company,actor,*,lock=False,require_delegator=True):
    require_company(company,ability='project.team.delegate' if require_delegator else 'commercial.read',actor=actor,lock=lock)
    rows=frappe.db.sql('SELECT name,version,enabled,definition_json,definition_digest FROM `tabCipher Project Delegation Policy Revision` WHERE company=%s ORDER BY version DESC,name DESC LIMIT 1'+(' FOR UPDATE' if lock else ''),(company,),as_dict=True)
    if not rows or not rows[0].enabled:
        raise DomainError('delegation_policy_unavailable','An operator-reviewed current delegation policy is required.',409)
    row=rows[0];value=json.loads(row.definition_json)
    if value!=POLICY or digest(value)!=row.definition_digest or not set(ALLOWED)<=PROJECT_ABILITIES:
        raise DomainError('delegation_policy_integrity','The current delegation policy cannot be verified.',409)
    return {'id':row.name,'company':company,'version':row.version,'digest':row.definition_digest,'definition':value}


def parse(value):
    if type(value) is not dict or set(value)!={'delegator_person','policy_id','policy_digest','members'}:
        raise DomainError('invalid_award_team','Supply the exact delegator, policy and bounded team.',422)
    for k in ('delegator_person','policy_id','policy_digest'):text(value[k],k,140)
    if type(value['members']) is not list or not 1<=len(value['members'])<=25:
        raise DomainError('invalid_award_team','Select one through 25 explicit canonical team members.',422)
    seen=set();rows=[]
    for row in value['members']:
        if type(row) is not dict or set(row)!={'person_id','abilities'}:
            raise DomainError('invalid_award_team','Select canonical people and exact Project abilities.',422)
        person=text(row['person_id'],'Person',140);abilities=row['abilities']
        if person in seen or type(abilities) is not list or not abilities or any(type(a) is not str for a in abilities) or len(abilities)!=len(set(abilities)) or not set(abilities)<=set(ALLOWED) or 'project.read' not in abilities:
            raise DomainError('invalid_award_team','Team identities and Project abilities must be distinct and explicitly permitted.',422)
        seen.add(person);rows.append({'person_id':person,'abilities':sorted(abilities)})
    return {**value,'members':sorted(rows,key=lambda r:r['person_id'])}


def participant_names(value):
    """Metadata discovery only: lock identities must be exact stored names.

    Native names use a case/accent insensitive DB collation. Refuse aliases
    before Python sorting can assign two orders to the same physical row.
    Eligibility and all authority remain the later locked caller boundary.
    """
    value=parse(value)
    names={value['delegator_person']}|{row['person_id'] for row in value['members']}
    rows=frappe.db.sql('SELECT name FROM `tabCipher Person` WHERE name IN ('+','.join('%s' for _ in names)+')',tuple(sorted(names)))
    if len(rows)!=len(names) or {row[0] for row in rows}!=names:
        raise DomainError('team_person_unavailable','Select exact canonical identities for this Company team.',403)
    return tuple(sorted(names))


def eligible_person(company,person,*,lock=False):
    suffix=' FOR UPDATE' if lock else ''
    people=frappe.db.sql('SELECT name,display_name,active,identity_kind FROM `tabCipher Person` WHERE name=%s'+suffix,(person,),as_dict=True)
    if not people or people[0].name!=person or not people[0].active or people[0].identity_kind!='Human':
        raise DomainError('team_person_unavailable','A selected canonical team member is not currently eligible.',403)
    bindings=frappe.db.sql('SELECT b.user FROM `tabCipher Identity Binding` b JOIN `tabUser` u ON u.name=b.user WHERE b.person=%s AND b.active=1 AND u.enabled=1 ORDER BY b.name'+suffix,(person,),as_dict=True)
    for row in bindings:
        try:
            actor=current_actor(row.user,lock=lock)
            if actor.person_id!=person:continue
            require_company(company,actor=actor,lock=lock)
            return {'person_id':person,'display_name':people[0].display_name}
        except DomainError as error:
            if error.status not in {401,403,404}:raise
    raise DomainError('team_person_unavailable','A selected canonical team member lacks current Company eligibility and usable identity.',403)


def authorize(company,value,actor,*,lock=False,requester_required=True):
    value=parse(value)
    delegator=actor if requester_required else delegator_actor(company,value['delegator_person'],lock=lock)
    current=policy(company,delegator,lock=lock)
    if value['policy_id']!=current['id'] or value['policy_digest']!=current['digest']:
        raise DomainError('stale_delegation_policy','Review the current exact delegation policy.',412)
    if requester_required and value['delegator_person']!=actor.person_id:
        raise DomainError('delegator_required','The requester must be this first-slice explicit Company delegator.',403)
    if not set(a for m in value['members'] for a in m['abilities'])<=set(current['definition']['allowed_project_abilities']):
        raise DomainError('delegation_denied','The reviewed policy does not permit every selected Project ability.',403)
    for row in value['members']:eligible_person(company,row['person_id'],lock=lock)
    return current


def assign_initial(*,actor,company,project,award_id,award_revision_id,plan_digest,packet_id,decision_id,operation_id,value):
    from .effect import require_award_effect
    context=require_award_effect(company=company,project=project,award_id=award_id,award_revision_id=award_revision_id,plan_digest=plan_digest,
        packet_id=packet_id,decision_id=decision_id,operation_id=operation_id)
    if context['approved_team']!=value['members']:
        raise DomainError('award_integrity','Initial team must equal the exact independently reviewed manifest.',409)
    authorize(company,value,actor,lock=True)
    from cipher_aec.governance.history import append_event
    assignments=[]
    for row in value['members']:
        for ability in row['abilities']:
            # Project is new: any prior assignment is an unexpected side effect.
            if frappe.db.exists('Cipher Project Duty',{'person':row['person_id'],'project':project,'company':company,'ability':ability}):
                raise DomainError('unexpected_project_authority','The new Project already has an unreviewed duty.',409)
            doc=frappe.get_doc({'doctype':'Cipher Project Duty','scope_type':'Project','person':row['person_id'],'company':company,'project':project,'ability':ability,'active':1})
            from .runtime import quiet_award_write
            quiet_award_write(doc);doc.insert(ignore_permissions=True)
            assignments.append(doc.name)
    append_event(actor=actor,company=company,project=project,operation_id=operation_id,event='project.initial_team.assigned',subject_type='Project',subject_id=project,
        details={'award':award_id,'award_revision':award_revision_id,'members':deepcopy(value['members']),'policy_id':value['policy_id'],'policy_digest':value['policy_digest']})
    return assignments


def delegator_actor(company,person,*,lock=False):
    suffix=' FOR UPDATE' if lock else ''
    rows=frappe.db.sql('SELECT b.user FROM `tabCipher Identity Binding` b JOIN `tabUser` u ON u.name=b.user WHERE b.person=%s AND b.active=1 AND u.enabled=1 ORDER BY b.name'+suffix,(person,),as_dict=True)
    for row in rows:
        try:
            actor=current_actor(row.user,lock=lock)
            if actor.person_id!=person:continue
            require_company(company,ability='project.team.delegate',actor=actor,lock=lock)
            return actor
        except DomainError as error:
            if error.status not in {401,403,404}:raise
    raise DomainError('delegator_authority_revoked','The current explicit Company delegator is no longer eligible.',403)
