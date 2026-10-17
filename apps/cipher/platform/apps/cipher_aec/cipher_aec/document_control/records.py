"""Native projection is command-only; original records cannot be overwritten."""
import json
from frappe.model.document import Document
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_project
from . import contracts as rules,repository as repo
BASE={'id','company','project','scope_type','author_person','author_user','created_at','status','no_effects'}
FACT={'parent_id','subject_id','subject_digest','packet_id','decision_id','checked_by_person','effect_digest','artifacts','electronic_signature','professional_seal','external_delivery','commercial_execution'}
RIGHTS_FIELDS={'ingest_allowed','read_allowed','distribute_allowed','rights_basis','rights_holder','allowed_purpose','restriction','valid_from','valid_until','evidence_artifact'}
EXTRA={'rights':{'parent_id','revision_number','predecessor'}|RIGHTS_FIELDS,'library':{'current_revision','revision_number'},'library_revision':{'parent_id','predecessor','revision_number','definition','artifacts'},'adoption_request':{'parent_id','library_revision','library_digest','definition','artifacts'},'issue_set':{'definition','artifacts','adoptions','package_digest'},'issue':FACT|{'package_digest'},'adoption':FACT,'transmittal':{'parent_id','issue_id','issue_digest','artifacts','recipients','purpose','required_response','channel','package_digest'},'distribution':FACT|{'package_digest','recipients','channel'},'evidence':{'parent_id','subject_kind','subject_id','subject_digest','statement','artifacts','commercial_execution','electronic_signature'}}

class DocumentaryRecord(Document):
    def validate(self):
        kind=next(k for k,v in rules.KINDS.items() if v==self.doctype)
        try:value=json.loads(self.data_json)
        except (TypeError,ValueError):raise DomainError('document_control_integrity','Supply exact documentary JSON.',422) from None
        rules.closed(value,BASE|EXTRA[kind])
        repo.require_write(self,kind,value)
        if value['id']!=self.name or digest(value)!=self.record_digest or value['scope_type']!='Project' or value['no_effects']!=rules.NO_EFFECTS:raise DomainError('document_control_integrity','The exact native documentary scope/record differs.',409)
        for key in ('company','project','scope_type','author_person','status',*repo.INDEXES):
            a,b=self.get(key),value.get(key)
            if key=='read_allowed' and b is None:a=None if a in (None,'',0) else a
            if a!=b and not(a in (None,'') and b is None):raise DomainError('document_control_integrity','The native documentary indexes differ.',409)
        actor=current_actor();ability=rules.MANAGE if kind=='rights' else rules.ACTION_ABILITY[kind] if kind in rules.ACTIONS else rules.ACTION_ABILITY[{'issue':'issue_set','adoption':'adoption_request','distribution':'transmittal'}[kind]] if kind in rules.FACTS.values() else rules.WRITE
        require_project(self.company,self.project,ability=ability,actor=actor,lock=True);require_project(self.company,self.project,ability=rules.READ,actor=actor,lock=True)
        if self.is_new():
            if value['author_person']!=actor.person_id or value['author_user']!=actor.user:raise DomainError('forged_authority','Documentary authorship comes from the current canonical person.',403)
        elif kind=='library':
            old=json.loads(self.get_doc_before_save().data_json)
            if any(value[k]!=old[k] for k in ('id','company','project','scope_type','author_person','author_user','created_at','status','no_effects')):raise DomainError('immutable_document_control','The library retains its original identity.',409)
        if kind=='rights':rules.rights({**{k:value[k] for k in RIGHTS_FIELDS},'evidence_artifact':{k:value['evidence_artifact'][k] for k in ('revision_id','source_sha256')}})
        if kind in rules.FACTS.values():
            from cipher_aec.governance.approvals import require_approval_effect
            subjectkind=next(k for k,v in rules.FACTS.items() if v==kind);require_approval_effect(action=rules.ACTIONS[subjectkind],subject_id=value['subject_id'],packet_id=value['packet_id'])
            if any(value[k] is not False for k in ('electronic_signature','professional_seal','external_delivery','commercial_execution')):raise DomainError('document_effect_unqualified','Documentary authorization never signs, seals, sends externally or executes a commercial contract.',403)
    def on_trash(self):raise DomainError('immutable_document_control','Original documentary facts cannot be deleted.',409)
    def before_rename(self,*args,**kwargs):raise DomainError('immutable_document_control','Original documentary identities cannot be renamed.',409)
