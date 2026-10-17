"""Closed native controllers; trusted_write alone does not admit engineering facts."""
import json
from frappe.model.document import Document
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_project
from . import contracts as rules,repository as repo

class EngineeringRecord(Document):
    def validate(self):
        kind=next(k for k,v in rules.KINDS.items() if v==self.doctype)
        try:value=json.loads(self.data_json)
        except (TypeError,ValueError):raise DomainError('engineering_integrity','Supply exact canonical engineering JSON.',422) from None
        rules.record(kind,value,initial=self.is_new() and kind in repo.HEADERS)
        repo.require_write(self,kind,value)
        if self.name!=value['id'] or self.record_digest!=digest(value):raise DomainError('engineering_integrity','The exact engineering payload identity/digest differs.',409)
        for field in ('company','project','scope_type','author_person','status',*repo.INDEX_KEYS):
            actual,expected=self.get(field),value.get(field)
            if actual!=expected and not(actual in (None,'') and expected is None):raise DomainError('engineering_integrity','The native engineering indexes differ from their canonical fact.',409)
        actor=current_actor();require_project(self.company,self.project,ability='engineering.distribute' if kind in ('transmittal','distribution') else 'engineering.write',actor=actor,lock=True)
        require_project(self.company,self.project,ability='engineering.read',actor=actor,lock=True)
        if self.is_new():
            if value['author_person']!=actor.person_id or value['author_user']!=actor.user:raise DomainError('forged_authority','Engineering authorship comes from the current canonical person.',403)
        else:
            old=json.loads(self.get_doc_before_save().data_json)
            if any(old[k]!=value[k] for k in rules.BASE_FIELDS-{'status'}):raise DomainError('immutable_engineering','A header retains its original identity and authorship.',409)
        if kind in ('official_response','official_disposition','distribution'):
            from cipher_aec.governance.approvals import require_approval_effect
            from .governance import _authors
            from .service import read
            import frappe
            sourcekind={'official_response':'response','official_disposition':'disposition','distribution':'transmittal'}[kind]
            require_approval_effect(action=rules.ACTIONS[sourcekind],subject_id=value['subject_id'],packet_id=value['packet_id'])
            original=read(sourcekind,value['subject_id'],self.company,self.project,actor,lock=True)
            decision=frappe.get_doc('Cipher Approval Decision',value['decision_id'],for_update=True)
            if digest(original)!=value['subject_digest'] or decision.packet!=value['packet_id'] or decision.decision!='Grant' or decision.actor_person!=value['checked_by_person'] or decision.actor_person in _authors(sourcekind,original,self.company,self.project,actor,lock=True):
                raise DomainError('independent_engineering_required','This exact engineering fact requires its independent human grant.',403)
    def on_trash(self):raise DomainError('immutable_engineering','Original engineering facts and headers cannot be deleted.',409)
    def before_rename(self,*args,**kwargs):raise DomainError('immutable_engineering','Engineering identities cannot be renamed.',409)
