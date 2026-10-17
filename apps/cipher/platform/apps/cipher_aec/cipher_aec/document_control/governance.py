"""Literal independent documentary authorization; internal records, no external sends."""
from functools import partial
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_project
from cipher_aec.governance.approvals import require_approval_effect
from . import contracts as rules,repository as repo,service,rights

def participants(action,company,subject_id,*,lock=False):
    if action!=rules.ACTIONS['transmittal']:return ()
    value=repo.raw('transmittal',subject_id,lock=lock)
    if value['company']!=company or value['scope_type']!='Project':raise DomainError('not_found','This internal transmittal is unavailable.',404)
    return tuple(sorted({p['person'] for p in value['recipients']}))

def _eligible(kind,value,actor,*,lock=False):
    if repo.official(rules.FACTS[kind],value['id'],lock=lock):raise DomainError('document_already_authorized','This exact immutable documentary subject already has its authorization fact.',409)
    company,project=value['company'],value['project']
    service.verify_artifacts(value['artifacts'],company,project,actor,operation='ingest' if kind=='adoption_request' else 'distribute',lock=lock)
    if kind=='transmittal':
        for declared in value['recipients']:
            observed=current_actor(declared['user'])
            if observed.person_id!=declared['person']:raise DomainError('document_people_changed','An intended internal recipient identity changed.',412)
            recipient=current_actor(declared['user'],lock=lock);require_project(company,project,ability=rules.READ,actor=recipient,lock=lock)
            service.verify_artifacts(value['artifacts'],company,project,recipient,lock=lock)

def authorize_subject(*,kind,actor,company,project,subject_id,phase,lock=False,manifest=None):
    value=service.read(kind,subject_id,company,project,actor,lock=lock)
    if manifest is not None:
        effect=manifest.get('effect',{})
        if effect.get('schema')!='cipher.document.authorization.v1' or effect.get('action')!=rules.ACTIONS[kind] or effect.get('subject_kind')!=kind or effect.get('subject_id')!=subject_id or effect.get('subject_digest')!=digest(value):raise DomainError('document_approval_integrity','The original documentary authorization has a different exact subject.',409)
    if phase in ('request','execute'):
        require_project(company,project,ability=rules.ACTION_ABILITY[kind],actor=actor,lock=lock)
        if actor.person_id!=value['author_person']:raise DomainError('document_preparer_required','The original preparer requests and records the independently authorized documentary effect.',403)
    if phase=='review':
        require_project(company,project,ability=rules.REVIEW,actor=actor,lock=lock);authors={value['author_person']}
        if kind=='adoption_request':authors.add(service.read('library_revision',value['library_revision'],company,project,actor,lock=lock)['author_person'])
        if actor.person_id in authors:raise DomainError('independent_document_review','A distinct canonical person must independently authorize the exact documentary effect.',403)
    if phase in ('request','manifest','review','execute'):
        project_doc=require_project(company,project,ability=rules.READ,actor=actor,lock=lock)
        if project_doc.status in ('Completed','Cancelled'):raise DomainError('project_closed','This Project is closed for new documentary effects.',409)
        _eligible(kind,value,actor,lock=lock)
    return value

def approval_manifest(*,kind,actor,company,project,subject_id,expected_version,lock=False):
    value=authorize_subject(kind=kind,actor=actor,company=company,project=project,subject_id=subject_id,phase='manifest',lock=lock)
    if digest(value)!=expected_version:raise DomainError('stale_documentary_subject','Review the exact immutable documentary subject.',412)
    policies=[rights.require(name,company,project,'read',actor,lock=lock) for name in sorted({r['document_id'] for r in value['artifacts']})]
    effect={'schema':'cipher.document.authorization.v1','action':rules.ACTIONS[kind],'subject_kind':kind,'subject_id':subject_id,'subject_digest':digest(value),'artifacts':value['artifacts'],'no_effects':dict(rules.NO_EFFECTS),'electronic_signature':False,'professional_seal':False,'external_delivery':False,'commercial_execution':False}
    if kind=='transmittal':effect.update(package_digest=value['package_digest'],recipients=value['recipients'],channel='internal')
    elif kind=='issue_set':effect.update(package_digest=value['package_digest'],adoptions=value['adoptions'])
    else:effect.update(library_revision=value['library_revision'],library_digest=value['library_digest'],target_locator=value['definition']['target_locator'])
    return {'subject':{'doctype':rules.KINDS[kind],'name':subject_id,'label':value['purpose'] if kind=='transmittal' else value['definition'].get('title',value['definition'].get('purpose'))},'sources':[{'artifacts':value['artifacts'],'rights':policies}],'effect':effect,'summary':{'definition':value.get('definition'),'purpose':value.get('purpose'),'required_response':value.get('required_response'),'no_effects':dict(rules.NO_EFFECTS),'rights_basis':'authored-declaration','external_delivery':False,'commercial_execution':False}}

def apply_authorization(*,kind,actor,company,project,manifest,packet_id,decision_id,operation_id):
    action=rules.ACTIONS[kind];subject=manifest['effect']['subject_id'];require_approval_effect(action=action,subject_id=subject,packet_id=packet_id)
    original=authorize_subject(kind=kind,actor=actor,company=company,project=project,subject_id=subject,phase='execute',lock=True,manifest=manifest)
    if approval_manifest(kind=kind,actor=actor,company=company,project=project,subject_id=subject,expected_version=digest(original),lock=True)!=manifest:raise DomainError('stale_documentary_subject','The independently reviewed exact sources, recipients or rights changed.',412)
    decision=frappe.get_doc('Cipher Approval Decision',decision_id,for_update=True);packet=frappe.get_doc('Cipher Approval Packet',packet_id,for_update=True)
    if decision.packet!=packet_id or decision.decision!='Grant' or decision.actor_person==original['author_person'] or packet.company!=company or packet.project!=project or packet.action!=action or packet.subject_id!=subject or decision.manifest_hash!=packet.manifest_hash:raise DomainError('independent_document_review','The exact distinct-person documentary grant is required.',403)
    factkind=rules.FACTS[kind];value=service.base(company,project,actor,parent_id=subject,subject_id=subject,subject_digest=digest(original),packet_id=packet_id,decision_id=decision_id,checked_by_person=decision.actor_person,effect_digest=digest(manifest['effect']),artifacts=original['artifacts'],status={'issue':'issued','adoption':'adopted','distribution':'recorded_internally'}[factkind],electronic_signature=False,professional_seal=False,external_delivery=False,commercial_execution=False)
    if kind in ('issue_set','transmittal'):value['package_digest']=original['package_digest']
    if kind=='transmittal':value.update(recipients=original['recipients'],channel='internal')
    repo.write(factkind,value);service.event(actor,value,operation_id,factkind,factkind+'.recorded');return {factkind:value}

CALLBACKS={action:(partial(approval_manifest,kind=kind),partial(authorize_subject,kind=kind),partial(apply_authorization,kind=kind)) for kind,action in rules.ACTIONS.items()}
