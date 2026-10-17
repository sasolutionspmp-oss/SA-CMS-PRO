"""Three literal Project engineering actions in the existing human grant engine."""
from functools import partial
from uuid import uuid4
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_project,current_actor
from cipher_aec.governance.approvals import require_approval_effect
from . import contracts as rules,repository as repo,service,sources


def participants(action,company,subject_id,*,lock=False):
    kind=next((k for k,v in rules.ACTIONS.items() if v==action),None)
    if kind is None:return ()
    value=repo.raw(kind,subject_id,lock=lock)
    if value['company']!=company or value.get('scope_type')!='Project':raise DomainError('not_found','This engineering subject is not available.',404)
    return tuple(sorted({p['person'] for p in value['recipients']})) if kind=='transmittal' else ()

def _new_eligible(kind,value,actor,*,lock):
    company,project=value['company'],value['project']
    if kind in ('response','disposition'):
        parentkind='rfi' if kind=='response' else 'submittal';header=service._raw(parentkind,value['parent_id'],company,project,lock=lock)
        current,head=('current_revision','response_head') if kind=='response' else ('current_submission','disposition_head')
        if header['status']!='open' or header[current]!=value['source_revision'] or header[head]!=value['id']:
            raise DomainError('stale_engineering','The reviewed engineering submission or proposed decision changed.',412)
        official='official_response' if kind=='response' else 'official_disposition'
        if repo.official_for(official,value['id'],lock=lock):raise DomainError('engineering_already_official','This exact technical revision already has its independent authorization.',409)
    else:
        if repo.official_for('distribution',value['id'],lock=lock):raise DomainError('engineering_already_distributed','This internal transmittal already has its immutable distribution receipt.',409)
        official=service.read(value['subject']['kind'],value['subject']['id'],company,project,actor,lock=lock)
        draftkind='response' if value['subject']['kind']=='official_response' else 'disposition'
        draft=service.read(draftkind,official['subject_id'],company,project,actor,lock=lock)
        header=service._raw('rfi' if draftkind=='response' else 'submittal',draft['parent_id'],company,project,lock=lock)
        current,head,officialkey=('current_revision','response_head','official_response') if draftkind=='response' else ('current_submission','disposition_head','official_disposition')
        if header[current]!=draft['source_revision'] or header[head]!=draft['id'] or header[officialkey]!=official['id']:
            raise DomainError('stale_engineering','New internal distribution requires the current exact official technical revision.',412)
        from cipher_aec.document_control.rights import distribution as require_content_distribution
        require_content_distribution(value,company,project,actor,lock=lock)
        for person in value['recipients']:
            # Literal immutable people were included before the command's first
            # Person/Project locks. Never lock a newly rebound recipient here.
            observed=current_actor(person['user'])
            if observed.person_id!=person['person']:raise DomainError('engineering_recipient_changed','An intended recipient identity changed. Prepare a new transmittal.',412)
            recipient=current_actor(person['user'],lock=lock)
            require_project(company,project,ability='engineering.read',actor=recipient,lock=lock)
            sources.verify(company,project,value,recipient,lock=lock)

def _authors(kind,value,company,project,actor,*,lock):
    if kind=='response':return {value['author_person']}
    if kind=='disposition':
        submission=service.read('submission',value['source_revision'],company,project,actor,lock=lock)
        return {value['author_person'],submission['author_person']}
    return {value['author_person']}

def authorize_subject(*,kind,actor,company,project,subject_id,phase,lock=False,manifest=None):
    if project is None:raise DomainError('not_found','Engineering actions require an exact Project.',404)
    if phase in ('request','manifest','review','execute'):
        current=require_project(company,project,ability='engineering.read',actor=actor,lock=lock)
        if current.status in ('Completed','Cancelled'):raise DomainError('project_closed','This Project is closed for new engineering work.',409)
    value=service.read(kind,subject_id,company,project,actor,lock=lock)
    if manifest is not None:
        effect=manifest.get('effect',{})
        if effect.get('schema')!='cipher.engineering.authorization.v1' or effect.get('action')!=rules.ACTIONS[kind] or effect.get('subject_kind')!=kind or effect.get('subject_id')!=subject_id or effect.get('subject_digest')!=digest(value):
            raise DomainError('engineering_approval_integrity','The original engineering approval has a different exact subject.',409)
    if phase in ('request','execute'):
        require_project(company,project,ability='engineering.distribute' if kind=='transmittal' else 'engineering.write',actor=actor,lock=lock)
    if phase=='review' and actor.person_id in _authors(kind,value,company,project,actor,lock=lock):
        raise DomainError('independent_engineering_required','Another canonical person must authorize this exact engineering work.',403)
    if phase in ('request','manifest','review','execute'):_new_eligible(kind,value,actor,lock=lock)
    return value

def approval_manifest(*,kind,actor,company,project,subject_id,expected_version,lock=False):
    value=authorize_subject(kind=kind,actor=actor,company=company,project=project,subject_id=subject_id,phase='manifest',lock=lock)
    if expected_version!=digest(value):raise DomainError('stale_engineering','Review the exact immutable engineering revision.',412)
    if kind=='transmittal':
        cited,package,drawings=value['source_citations'],value['artifacts'],value['drawing_references'];label=value['purpose']
    else:
        cited,package,drawings=service.closure(kind,value,company,project,actor,lock=lock)
        header=service._raw('rfi' if kind=='response' else 'submittal',value['parent_id'],company,project,lock=lock)
        label=header['number']+' · '+('Response' if kind=='response' else 'Disposition')+' revision '+str(value['revision_number'])
    effect={'schema':'cipher.engineering.authorization.v1','action':rules.ACTIONS[kind],'subject_kind':kind,'subject_id':subject_id,'subject_digest':digest(value)}
    if kind=='transmittal':effect.update(package_digest=value['package_digest'],recipients=value['recipients'],channel='internal')
    else:effect.update(parent_id=value['parent_id'],source_revision=value['source_revision'],source_digest=value['source_digest'],author_people=sorted(_authors(kind,value,company,project,actor,lock=lock)))
    return {'subject':{'doctype':rules.KINDS[kind],'name':subject_id,'label':label},'sources':[{'source_citations':cited,'artifacts':package,'drawing_references':drawings}],
        'effect':effect,'summary':{'schema':'cipher.engineering.review.v1','definition':value.get('definition'),
            'purpose':value.get('purpose'),'no_effects':dict(rules.NO_EFFECTS),'professional_seal':False,'external_delivery':False}}

def apply_authorization(*,kind,actor,company,project,manifest,packet_id,decision_id,operation_id):
    action=rules.ACTIONS[kind];subject=manifest['effect']['subject_id']
    require_approval_effect(action=action,subject_id=subject,packet_id=packet_id)
    value=authorize_subject(kind=kind,actor=actor,company=company,project=project,subject_id=subject,phase='execute',lock=True,manifest=manifest)
    actual=approval_manifest(kind=kind,actor=actor,company=company,project=project,subject_id=subject,expected_version=digest(value),lock=True)
    if actual!=manifest:raise DomainError('stale_engineering','The exact independently reviewed technical manifest changed.',412)
    decision=frappe.get_doc('Cipher Approval Decision',decision_id,for_update=True)
    if decision.packet!=packet_id or decision.decision!='Grant' or decision.actor_person in _authors(kind,value,company,project,actor,lock=True):
        raise DomainError('independent_engineering_required','This exact effect requires the independent canonical person\'s grant.',403)
    packet=frappe.get_doc('Cipher Approval Packet',packet_id,for_update=True)
    if packet.company!=company or packet.project!=project or packet.subject_id!=subject or packet.action!=action or decision.manifest_hash!=packet.manifest_hash:
        raise DomainError('engineering_approval_integrity','The decision, packet and exact engineering subject do not agree.',409)
    official_kind={'response':'official_response','disposition':'official_disposition','transmittal':'distribution'}[kind]
    result=service._base(company,project,actor,status='recorded_internally' if kind=='transmittal' else 'official',subject_id=subject,subject_digest=digest(value),packet_id=packet_id,decision_id=decision_id,
        checked_by_person=decision.actor_person,no_effects=dict(rules.NO_EFFECTS),authority='internal-technical-only')
    if kind=='transmittal':result.update(package_digest=value['package_digest'],recipients=value['recipients'],channel='internal',external_delivery=False)
    else:result.update(parent_id=value['parent_id'],source_revision=value['source_revision'],source_digest=value['source_digest'])
    repo.write(official_kind,result)
    if kind!='transmittal':
        parentkind='rfi' if kind=='response' else 'submittal';header=service._raw(parentkind,value['parent_id'],company,project,lock=True)
        final={**header,official_kind:result['id']};repo.write(parentkind,final,old=header)
    service._event(actor,result,operation_id,'internal.distribution.recorded' if kind=='transmittal' else kind+'.authorized',official_kind)
    return {official_kind:result}

CALLBACKS={action:(partial(approval_manifest,kind=kind),partial(authorize_subject,kind=kind),partial(apply_authorization,kind=kind)) for kind,action in rules.ACTIONS.items()}
