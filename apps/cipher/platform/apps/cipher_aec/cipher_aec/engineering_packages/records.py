"""Canonical-only native controllers; originals never update or rename."""
import json
from frappe.model.document import Document
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_project
from . import contracts as rules,repository as repo
BASE={'id','company','project','scope_type','author_person','author_user','created_at','status','no_effects'}
REVISION={'parent_id','family_id','revision_number','predecessor','package_revision','package_digest','checker','definition','source_citations','drawing_references','artifacts'}
EXTRA={'package':{'number','revision_number','current_revision','basis_head','calculation_heads','deliverable_heads'},'package_revision':{'parent_id','revision_number','predecessor','definition','responsible','checker'},'basis':REVISION|{'quantities','unit_manifest'},'calculation':REVISION|{'basis_revision','basis_digest','input_keys','inputs','outputs','unit_manifest','execution','issue_readiness'},'deliverable':REVISION|{'basis_revision','basis_digest','calculations','issue_readiness'},'check':{'parent_id','subject_kind','subject_id','subject_digest','package_revision','package_digest','checker','preparer_person','packet_id','decision_id','comments','outcome','issue_authorized','sealed'}}

class PackageRecord(Document):
    def validate(self):
        kind=next(k for k,v in rules.KINDS.items() if v==self.doctype)
        try:value=json.loads(self.data_json)
        except (TypeError,ValueError):raise DomainError('package_integrity','Supply exact canonical package JSON.',422) from None
        rules.closed(value,BASE|EXTRA[kind]);repo.require_write(self,kind,value)
        if value['id']!=self.name or digest(value)!=self.record_digest or value['scope_type']!='Project' or value['no_effects']!=rules.NO_EFFECTS:raise DomainError('package_integrity','The native package payload/scope/effect bounds differ.',409)
        for key in ('company','project','scope_type','author_person','status',*repo.INDEXES):
            if self.get(key)!=value.get(key) and not(self.get(key) in (None,'') and value.get(key) is None):raise DomainError('package_integrity','Native package indexes differ from the exact fact.',409)
        actor=current_actor();require_project(self.company,self.project,ability=rules.WRITE,actor=actor,lock=True);require_project(self.company,self.project,ability=rules.READ,actor=actor,lock=True)
        if self.is_new():
            if value['author_person']!=actor.person_id or value['author_user']!=actor.user:raise DomainError('forged_authority','Package authorship comes from the current canonical person.',403)
        elif any(value[k]!=json.loads(self.get_doc_before_save().data_json)[k] for k in BASE):raise DomainError('immutable_package','A package header retains its original identity and standing.',409)
        if kind=='package_revision':rules.package_definition(value['definition'])
        elif kind in ('basis','calculation','deliverable'):
            from . import service
            {'basis':rules.basis_definition,'calculation':rules.calculation_definition,'deliverable':rules.deliverable_definition}[kind](value['definition'])
            assignment=service.read('package_revision',value['package_revision'],self.company,self.project,actor,lock=True)
            if assignment['parent_id']!=value['parent_id'] or digest(assignment)!=value['package_digest'] or assignment['responsible']['person']!=actor.person_id or assignment['checker']!=value['checker']:raise DomainError('package_integrity','The exact designated preparer/checker assignment differs.',409)
            if kind!='deliverable':service.verify_quantities(value)
            if kind in ('calculation','deliverable') and value['issue_readiness']!='not_authorized_for_issue':raise DomainError('package_issue_unqualified','Checking or completing a calculation never issues it.',403)
        elif kind=='check':
            from cipher_aec.governance.approvals import require_approval_effect
            require_approval_effect(action=rules.ACTIONS[value['subject_kind']],subject_id=value['subject_id'],packet_id=value['packet_id'])
            from .service import read
            import frappe
            original=read(value['subject_kind'],value['subject_id'],self.company,self.project,actor,lock=True);decision=frappe.get_doc('Cipher Approval Decision',value['decision_id'],for_update=True)
            if digest(original)!=value['subject_digest'] or original['checker']!=value['checker'] or original['author_person']==value['checker']['person'] or decision.packet!=value['packet_id'] or decision.decision!='Grant' or decision.actor_person!=value['checker']['person'] or value['issue_authorized'] is not False or value['sealed'] is not False:raise DomainError('independent_package_checker','The exact canonical independent checking grant is required.',403)
    def on_trash(self):raise DomainError('immutable_package','Original package evidence cannot be deleted.',409)
    def before_rename(self,*args,**kwargs):raise DomainError('immutable_package','Package identities cannot be renamed.',409)
