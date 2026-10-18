"""Private from creation; existing ordinary/shared sources are never reclassified."""
from contextvars import ContextVar
from copy import deepcopy
import json
from uuid import uuid4
import frappe
from frappe.model.document import Document
from cipher_aec.api.contracts import canonical_json,digest,utc_timestamp
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_project,trusted_write,require_trusted_write
from . import contracts as rules,sources

DOCTYPE='Cipher Incident Evidence Registration'
_registration=ContextVar('cipher_incident_evidence_registration',default=None)

def validate_registration(value):
    rules.closed(value,{'id','company','project','scope_type','author_person','author_user','created_at','document_id','rights_basis','permission_evidence','classification'})
    rules.identifier(value['id']);rules.timestamp(value['created_at'])
    if value['scope_type']!='Project' or value['classification']!='restricted_from_creation':rules.fail('Restricted evidence requires exact original classification.')
    for key in ('company','project','author_person','author_user','document_id'):rules.text(value[key],key,140)
    rules.text(value['rights_basis'],'rights_basis',4000);rules.source_list([rules.strip_source(s) for s in value['permission_evidence']],'permission_evidence')
    for source in value['permission_evidence']:rules.captured_source(source)
    return value

def registration(document_id,*,lock=False):
    # No private upload can succeed before the additive DocType is installed.
    if not frappe.db.exists('DocType',DOCTYPE):return None
    rows=frappe.db.sql('SELECT name FROM `tab'+DOCTYPE+'` WHERE document_id=%s'+(' FOR UPDATE' if lock else ''),(document_id,),as_dict=True)
    if not rows:return None
    if len(rows)!=1:raise DomainError('incident_evidence_integrity','The original evidence registration is not unique.',409)
    doc=frappe.get_doc(DOCTYPE,rows[0].name,for_update=lock)
    try:value=json.loads(doc.data_json)
    except (ValueError,TypeError):raise DomainError('incident_evidence_integrity','The original evidence registration cannot be decoded.',409) from None
    validate_registration(value)
    if doc.name!=value['id'] or doc.record_digest!=digest(value) or any(doc.get(key)!=value[key] for key in ('company','project','document_id','author_person')):
        raise DomainError('incident_evidence_integrity','The original evidence classification differs.',409)
    return value

def authorize_source(row,actor,*,lock=False):
    name=row.get('document') or row.get('name')
    # Project revision_scope intentionally omits its parent. Resolve only its
    # metadata here before revision Long Text, previews, search or bytes load.
    if not row.get('document') and name:
        locator=frappe.db.get_value('Cipher Document Revision',name,['document','company','project','scope_type'],as_dict=True)
        if locator:
            if any((row.get(k) or None)!=(locator.get(k) or None) for k in ('company','project','scope_type')):
                raise DomainError('incident_evidence_integrity','The source locator scope differs.',409)
            name=locator.document
    value=registration(name,lock=lock) if name else None
    if value is None:return
    if (row.get('scope_type') or 'Project',row.get('company'),row.get('project'))!=('Project',value['company'],value['project']):
        raise DomainError('incident_evidence_integrity','The restricted source has a different exact scope.',409)
    require_project(value['company'],value['project'],ability='safety.incident.read',actor=actor,lock=lock)

def verify_incident_evidence(references,definition,company,project,actor,*,lock=False):
    shared=set(definition['shared_evidence_revisions'])
    for source in references:
        value=registration(source['document_id'],lock=lock)
        if value is None:
            if source['revision_id'] not in shared:raise DomainError('restricted_incident_evidence_required','Upload sensitive incident evidence through its private evidence action, or explicitly declare this exact non-sensitive shared revision.',422)
        else:
            if (value['company'],value['project'])!=(company,project):raise DomainError('not_found','This evidence is not available.',404)
            require_project(company,project,ability='safety.incident.read',actor=actor,lock=lock)
            if source['revision_id'] in shared:rules.fail('A restricted original cannot be declared ordinary shared evidence.','shared_evidence_revisions')

def query(doctype,user=None):
    """SQL exclusion precedes native lists, Long Text selections and counts."""
    if not frappe.db.exists('DocType',DOCTYPE):return '1=1'
    from cipher_aec.governance.context import project_ids
    try:
        actor=current_actor(user);allowed=[]
        for project in project_ids(actor,ability='safety.incident.read'):
            company=frappe.db.get_value('Project',project,'company')
            try:require_project(company,project,ability='safety.incident.read',actor=actor);allowed.append(project)
            except DomainError:continue
    except DomainError:allowed=[]
    identifier='name' if doctype=='Cipher Document' else 'document'
    denied='SELECT document_id FROM `tab'+DOCTYPE+'`'
    if allowed:denied+=' WHERE project NOT IN ('+','.join(frappe.db.escape(p) for p in sorted(set(allowed)))+')'
    return '`tab'+doctype+'`.`'+identifier+'` NOT IN ('+denied+')'

def require_private_upload(company,project,actor,*,lock=False):
    for ability in ('safety.incident.read','safety.incident.evidence.manage','document.read','document.write','document.rights.manage'):
        require_project(company,project,ability=ability,actor=actor,lock=lock)
    if not frappe.db.exists('DocType',DOCTYPE):raise DomainError('incident_evidence_unavailable','Private evidence storage has not been installed.',503)

def reject_shared_bytes(checksum):
    # Do not publish a second apparently private identity for bytes that already
    # have an ordinary/shared canonical identity. Reuse declared safe shared
    # revisions explicitly; migration/declassification is outside this slice.
    rows=frappe.db.sql('SELECT r.name FROM `tabCipher Document Revision` r LEFT JOIN `tab'+DOCTYPE+'` p ON p.document_id=r.document WHERE r.sha256=%s AND p.name IS NULL LIMIT 1',(checksum,),as_dict=True)
    if rows:raise DomainError('ordinary_source_already_exists','These bytes already have an ordinary source identity. Reuse the exact non-sensitive shared source explicitly; sensitive source migration is unavailable.',409)

def reject_restricted_bytes(checksum):
    # Known restricted originals cannot acquire an ordinary identity in another
    # source scope. Read only their existence; never return their identity or
    # reclassify any existing ordinary document.
    if not frappe.db.exists('DocType',DOCTYPE):return
    rows=frappe.db.sql('SELECT 1 FROM `tabCipher Document Revision` r INNER JOIN `tab'+DOCTYPE+'` p ON p.document_id=r.document WHERE r.sha256=%s LIMIT 1',(checksum,),as_dict=True)
    if rows:raise DomainError('restricted_source_already_exists','These bytes cannot be uploaded as an ordinary source. Use the private evidence action.',409)

def register_new_document(row,company,project,actor,rights_basis,permission_evidence):
    require_private_upload(company,project,actor,lock=True)
    if row.get('revision_number')!=0 or row.get('current_revision') or (row.get('scope_type'),row.get('company'),row.get('project'))!=('Project',company,project) or frappe.db.exists('Cipher Document',row['name']):
        raise DomainError('incident_evidence_registration_required','Only a newly generated private source can be registered.',403)
    value={'id':str(uuid4()),'company':company,'project':project,'scope_type':'Project','author_person':actor.person_id,'author_user':actor.user,
        'created_at':utc_timestamp(),'document_id':row['name'],'rights_basis':rights_basis,'permission_evidence':deepcopy(permission_evidence),'classification':'restricted_from_creation'}
    validate_registration(value);token=_registration.set(value)
    try:
        with trusted_write():frappe.get_doc({'doctype':DOCTYPE,'name':value['id'],**{k:value[k] for k in ('company','project','document_id','author_person')},'record_digest':digest(value),'data_json':canonical_json(value)}).insert(ignore_permissions=True,set_name=value['id'])
    finally:_registration.reset(token)
    return value

class IncidentEvidenceRegistration(Document):
    def validate(self):
        require_trusted_write()
        try:value=json.loads(self.data_json)
        except (ValueError,TypeError):raise DomainError('incident_evidence_integrity','Supply exact private evidence registration JSON.',422) from None
        validate_registration(value);actor=current_actor()
        if not self.is_new() or _registration.get()!=value or self.name!=value['id'] or self.record_digest!=digest(value) or any(self.get(key)!=value[key] for key in ('company','project','document_id','author_person')):
            raise DomainError('incident_evidence_registration_required','Use the exact private upload registration boundary.',403)
        require_private_upload(value['company'],value['project'],actor,lock=True)
        if (value['author_person'],value['author_user'])!=(actor.person_id,actor.user) or frappe.db.exists('Cipher Document',value['document_id']):
            raise DomainError('incident_evidence_registration_required','Evidence must be private before the new source exists.',403)
        resolved=sources.resolve(value['company'],value['project'],value['permission_evidence'],actor,lock=True,new_use=True)
        if any(row!=sources.mapped(row,resolved) for row in value['permission_evidence']):raise DomainError('incident_evidence_integrity','The current upload permission evidence differs.',409)
    def on_trash(self):raise DomainError('immutable_incident_evidence','An original privacy classification cannot be deleted.',409)
    def before_rename(self,*args,**kwargs):raise DomainError('immutable_incident_evidence','An original privacy classification cannot be renamed.',409)

def authorize_upload_result(result,company,project,actor,*,lock=False):
    require_project(company,project,ability='safety.incident.read',actor=actor,lock=lock)
    value=result.get('registration');validate_registration(value)
    actual=registration(value['document_id'],lock=lock)
    if value!=actual or (value['company'],value['project'])!=(company,project) or result.get('history_id') is not None or result.get('family')!='incident':
        raise DomainError('incident_evidence_integrity','The original private upload receipt differs.',409)
    from cipher_aec.documents.service import get_document,source_reference
    revision=result['revision'];details=get_document(company,value['document_id'],actor=actor)
    actual=next((r for r in details['revisions'] if r['id']==revision['id']),None)
    if actual is None or any(actual[key]!=revision[key] for key in ('id','revision_number','filename','mime_type','byte_length','sha256','page_count')) or result['document']['id']!=value['document_id']:
        raise DomainError('incident_evidence_integrity','The original private source bytes differ.',409)
    expected_document={**{key:v for key,v in revision.items() if key!='id'},'id':value['document_id'],
        'title':details['document']['title'],'company':company,'project':project,'current_revision':revision['id']}
    if result['document']!=expected_document:raise DomainError('incident_evidence_integrity','The original private document identity differs.',409)
    if actual['retrieval_status']=='available':source_reference(company,project,revision['id'],1,actor=actor,lock=lock)
    sources.verify([{'evidence':value['permission_evidence']}],company,project,actor,lock=lock)
