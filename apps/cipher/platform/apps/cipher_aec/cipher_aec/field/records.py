"""Supported controllers admit only the exact field command and retain originals."""
import json
from frappe.model.document import Document
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_project
from . import contracts as rules,repository as repo,sources

class FieldRecord(Document):
    def validate(self):
        from . import service
        kind=next(k for k,v in rules.KINDS.items() if v==self.doctype)
        try:value=json.loads(self.data_json)
        except (TypeError,ValueError):raise DomainError('field_integrity','Supply exact canonical field JSON.',422) from None
        rules.record(kind,value,initial=self.is_new() and kind in rules.HEADERS);repo.require_write(self,kind,value)
        actor=current_actor();plan=service._command_effect.get()
        if not plan or plan['person']!=actor.person_id or (plan['company'],plan['project'])!=(value['company'],value['project']):
            raise DomainError('field_command_required','Use an admitted exact field command.',403)
        if self.name!=value['id'] or self.record_digest!=digest(value):raise DomainError('field_integrity','The native field identity or digest differs.',409)
        for key in ('company','project','scope_type','author_person','status',*repo.INDEX_KEYS):
            actual,expected=self.get(key),value.get(key)
            if actual!=expected and not(actual in (None,'') and expected is None):raise DomainError('field_integrity','The native field indexes differ from their canonical fact.',409)
        require_project(self.company,self.project,ability='field.read',actor=actor,lock=True)
        action=plan['action'].split('.')[-1]
        ability=rules.TRANSITIONS[action][2] if action in rules.TRANSITIONS else 'field.write'
        project=require_project(self.company,self.project,ability=ability,actor=actor,lock=True)
        if project.status in ('Completed','Cancelled'):raise DomainError('project_closed','This Project is closed for new field work.',409)
        if self.is_new() and (value['author_person']!=actor.person_id or value['author_user']!=actor.user):raise DomainError('forged_authority','Field authorship comes from the current canonical person.',403)
        if kind in rules.HEADERS:
            if plan['action'].split('.')[0]!=kind:raise DomainError('field_command_required','The exact field family differs.',403)
            if self.is_new():
                if action!='create' or any(value[k] is not None for k in ('current_revision','last_decision','accepted_revision')) or value['revision_number']!=0 or value['status']!='draft':
                    raise DomainError('field_command_required','A new field header begins as an exact empty draft.',403)
                return
            old=json.loads(self.get_doc_before_save().data_json)
            if action in ('create','revise'):
                revision=service._raw(service._revision_kind(kind),value['current_revision'],self.company,self.project,lock=True)
                if (value['status']!='draft' or value['last_decision'] is not None or value['accepted_revision']!=old['accepted_revision']
                    or value['revision_number']!=old['revision_number']+1 or revision['parent_id']!=value['id']
                    or revision['revision_number']!=value['revision_number'] or revision['predecessor']!=old['current_revision']
                    or revision['prior_decision']!=old['last_decision'] or revision['amendment_of']!=old['accepted_revision']):
                    raise DomainError('field_integrity','The exact field successor header differs.',409)
            elif action in rules.TRANSITIONS:
                decision=service.read('decision',value['last_decision'],self.company,self.project,actor,lock=True,new_use=action!='return')
                expected={**old,'last_decision':decision['id'],'status':decision['to_status'],'accepted_revision':old['current_revision'] if action=='accept' else old['accepted_revision']}
                if (value!=expected or decision['action']!=action or decision['parent_id']!=value['id'] or decision['predecessor']!=old['last_decision']
                    or decision['source_revision']!=old['current_revision'] or decision['from_status']!=old['status']):raise DomainError('field_integrity','The exact documentary transition header differs.',409)
            else:raise DomainError('field_command_required','Unsupported field header command.',403)
        elif kind in ('daily_revision','ticket_revision','quantity'):
            capture=repo._capture.get()
            expected=capture['revision'] if capture and kind==capture['revision_kind'] else next((q for q in capture['quantities'] if q['id']==value['id']),None) if capture and kind=='quantity' else None
            if expected!=value or action not in ('create','revise'):raise DomainError('field_command_required','This immutable field fact differs from its exact capture plan.',403)
            family='daily' if kind in ('daily_revision','quantity') else 'ticket'
            header=service._raw(family,value['parent_id'],self.company,self.project,lock=True)
            revision=capture['revision']
            if revision['revision_number']!=header['revision_number']+1 or revision['predecessor']!=header['current_revision'] or revision['amendment_of']!=header['accepted_revision']:
                raise DomainError('stale_field_record','The current capture predecessor changed.',412)
            if kind==capture['revision_kind']:
                # The exact complete capture union is locked and rechecked once
                # before its immutable quantity inserts. Quantities still need
                # both exact writer/capture plans; no ambient cache is trusted.
                sources.verify([(capture['revision_kind'],revision),*[('quantity',q) for q in capture['quantities']]],self.company,self.project,actor,lock=True,new_use=True)
        elif kind=='decision':
            if value['action']!=action or action not in rules.TRANSITIONS:raise DomainError('field_command_required','The documentary decision differs from its command.',403)
            family=plan['action'].split('.')[0];header=service._raw(family,value['parent_id'],self.company,self.project,lock=True)
            revision=service.read(service._revision_kind(family),header['current_revision'],self.company,self.project,actor,lock=True,new_use=action!='return')
            if (value['source_revision']!=revision['id'] or value['source_digest']!=digest(revision) or value['from_status']!=header['status'] or value['predecessor']!=header['last_decision']):
                raise DomainError('stale_field_record','The documentary decision is not for the current exact field revision.',412)
            if action!='submit' and actor.person_id in service._authors(revision):raise DomainError('independent_field_review_required','A canonical author or superintendent cannot accept or acknowledge their own record.',403)
            if action=='acknowledge' and family!='ticket':raise DomainError('field_integrity','Only a T&M ticket can be acknowledged.',409)
            sources.verify([('decision',value)],self.company,self.project,actor,lock=True,new_use=True)

    def on_trash(self):raise DomainError('immutable_field_record','Original field records and their documentary history cannot be deleted.',409)
    def before_rename(self,*args,**kwargs):raise DomainError('immutable_field_record','Field identities cannot be renamed.',409)
