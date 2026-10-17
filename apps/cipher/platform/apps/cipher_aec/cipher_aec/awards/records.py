"""Bounded factories enforce authored plans and exact independent adoption."""
import json
import frappe
from frappe.model.document import Document
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_company,require_trusted_write
from . import repository


class AwardRecord(Document):
    def validate(self):
        require_trusted_write()
        try:value=json.loads(self.data_json)
        except (TypeError,ValueError):raise DomainError('award_integrity','Canonical award JSON is required.',409) from None
        kind=next(k for k,v in repository.TYPES.items() if v==self.doctype)
        repository.require_record_write(kind,value)
        if value.get('id')!=self.name or digest(value)!=self.record_digest:
            raise DomainError('award_integrity','Award identity and complete digest must agree.',409)
        for key in ('company','project','author_person','status','handoff','revision_number','current_revision','adoption','pursuit','opportunity','issue','proposal_line_id','sales_order_item','sales_order','contract','award_revision','target_project'):
            if self.meta.has_field(key) and self.get(key)!=value.get(key) and not (self.get(key) in (None,'') and value.get(key) is None):
                raise DomainError('award_integrity','Every indexed award projection must equal canonical facts.',409,{'field':key})
        actor=current_actor()
        require_company(value['company'],ability='commercial.award',actor=actor,lock=True)
        if kind!='profile' and (value.get('scope_type')!='Company' or value.get('project') is not None):
            raise DomainError('award_integrity','Original award evidence retains explicit Company scope.',409)
        if kind in {'revision','adoption','line'} and not self.is_new():
            raise DomainError('immutable_award_record','Award plans and adopted evidence require immutable identities.',403)
        if kind in {'adoption','line'}:
            from .effect import validate_adoption_record
            validate_adoption_record(kind,value)
        if kind=='profile':
            if self.is_new():
                from .preallocation import profile_context
                profile_context(value)
            else:
                from .effect import require_award_effect
                context=require_award_effect(company=value['company'],project=value['project'],award_id=value['handoff'],award_revision_id=value['award_revision'],
                    plan_digest=value['plan_digest'],packet_id=value['packet_id'],decision_id=value['decision_id'],operation_id=value['operation_id'])
                before=json.loads(self.get_doc_before_save().data_json)
                mutable={'status','adoption','sales_order','contract'}
                if before['status']!='preallocated' or value['status']!='adopted' or {k:v for k,v in before.items() if k not in mutable}!={k:v for k,v in value.items() if k not in mutable}:
                    raise DomainError('award_integrity','The Project profile may complete only its original exact allocation.',409)
                if value['adoption']!=context['adoption_id'] or value['contract']!=context['contract_id'] or not context['native_output'] or value['sales_order']!=context['native_output']['sales_order']:
                    raise DomainError('award_integrity','The Project profile must retain the exact final adoption/native links.',409)
        if kind=='revision':
            if value['author_person']!=actor.person_id:
                raise DomainError('forged_authority','The current canonical author must author this plan.',403)
            parent=repository.read('handoff',value['handoff'],value['company'],lock=True)
            if parent['status']!='draft' or value['revision_number']!=parent['revision_number']+1 or value['predecessor']!=parent['current_revision']:
                raise DomainError('stale_award','Plan revision must advance the exact unadopted handoff.',412)
            from .service import _build
            rebuilt=_build(value['company'],parent,value['definition'],actor,ids=value['ids'],lock=True)
            if value.get('schema')!='cipher.award.plan.v1' or value['status']!='planned' or value['author_user']!=actor.user or any(value.get(k)!=v for k,v in rebuilt.items()):
                raise DomainError('award_integrity','The canonical plan must equal its fully reauthorized current source/control/team facts.',409)
        if kind=='handoff' and self.is_new():
            if value.get('original_issue')!=value.get('issue') or value.get('status')!='draft' or value.get('revision_number')!=0 or value.get('current_revision') is not None or value.get('adoption') is not None:
                raise DomainError('award_integrity','A new handoff must retain its exact original Issue and empty adoption.',409)
        if kind=='handoff' and not self.is_new():
            before=json.loads(self.get_doc_before_save().data_json)
            if before['status']!='draft':raise DomainError('award_already_adopted','A completed full handoff cannot be replanned.',409)
            mutable={'current_revision','revision_number','issue','status','adoption'}
            if {k:v for k,v in before.items() if k not in mutable}!={k:v for k,v in value.items() if k not in mutable}:
                raise DomainError('immutable_award_scope','Handoff Company/Pursuit/Opportunity reservations cannot change.',409)
            if value['status']=='adopted':
                adoption=repository.read('adoption',value['adoption'],value['company'],lock=True)
                from .effect import require_award_effect
                require_award_effect(**adoption['effect_binding'])
                if adoption['handoff']!=self.name or adoption['award_revision']!=before['current_revision'] or value['current_revision']!=before['current_revision'] or value['revision_number']!=before['revision_number']:
                    raise DomainError('award_integrity','Completed handoff must bind its exact final adoption.',409)
            elif value['status']!='draft' or value['revision_number']!=before['revision_number']+1 or value['adoption']:
                raise DomainError('stale_award','Draft handoff must advance one immutable plan.',412)
            else:
                planned=repository.read('revision',value['current_revision'],value['company'],lock=True)
                if planned['handoff']!=self.name or planned['predecessor']!=before['current_revision'] or planned['revision_number']!=value['revision_number'] or planned['issue']!=value['issue'] or planned['author_person']!=actor.person_id:
                    raise DomainError('award_integrity','The handoff must advance its own exact newly authored plan.',409)

    def on_trash(self):raise DomainError('award_history_preserved','Award evidence cannot be deleted.',403)
    def before_rename(self,*args,**kwargs):raise DomainError('immutable_award_identity','Award identities cannot be renamed.',403)


class DelegationPolicyRecord(Document):
    def validate(self):
        from .team import POLICY
        require_trusted_write()
        if frappe.session.user!='Administrator' or not self.is_new():
            raise DomainError('immutable_delegation_policy','Only the operator can install a new reviewed immutable policy.',403)
        if json.loads(self.definition_json)!=POLICY or self.definition_digest!=digest(POLICY) or self.version!=POLICY['version']:
            raise DomainError('delegation_policy_integrity','The installed delegation policy must equal the literal reviewed definition.',409)
    def on_trash(self):raise DomainError('award_history_preserved','Delegation policy history cannot be deleted.',403)
    def before_rename(self,*args,**kwargs):raise DomainError('immutable_award_identity','Delegation policy identities cannot be renamed.',403)
