"""Supported native controllers retain exact immutable facts and decisions."""
import json
from frappe.model.document import Document
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_project
from . import contracts as rules,repository as repo,sources

class QualitySafetyRecord(Document):
    def validate(self):
        from . import service
        kind=next(k for k,v in rules.KINDS.items() if v==self.doctype);family=rules.family_for(kind)
        try:value=json.loads(self.data_json)
        except (TypeError,ValueError):raise DomainError('quality_safety_integrity','Supply exact canonical JSON.',422) from None
        rules.record(kind,value,initial=self.is_new() and kind in rules.HEADERS);repo.require_write(self,kind,value);repo.check_indexes(self,value)
        actor=current_actor();plan=service._effect.get()
        if not plan or plan['family']!=family or plan['person']!=actor.person_id or (plan['company'],plan['project'])!=(value['company'],value['project']):
            raise DomainError('quality_safety_command_required','Use an admitted exact documentary command.',403)
        action=plan['action'];duty=rules.TRANSITIONS[action][2] if action in rules.TRANSITIONS else 'write'
        require_project(self.company,self.project,ability=rules.ability(family),actor=actor,lock=True)
        project=require_project(self.company,self.project,ability=rules.ability(family,duty),actor=actor,lock=True)
        if project.status in ('Completed','Cancelled'):raise DomainError('project_closed','This Project is closed for new documentary work.',409)
        if self.is_new() and (value['author_person'],value['author_user'])!=(actor.person_id,actor.user):
            raise DomainError('forged_authority','Authorship comes from the current canonical person.',403)
        if kind in rules.HEADERS:
            if self.is_new():
                if action!='create' or value['status']!='draft' or value['revision_number']!=0 or any(value[k] is not None for k in ('current_revision','last_decision','closed_revision')):
                    raise DomainError('quality_safety_command_required','A new record begins as an exact empty draft.',403)
                return
            old=json.loads(self.get_doc_before_save().data_json)
            if action in ('create','revise'):
                revision=service.read(rules.child_kind(family,'revision'),value['current_revision'],self.company,self.project,actor,lock=True,new_use=True)
                expected={**old,'status':'draft','revision_number':old['revision_number']+1,'current_revision':revision['id'],'last_decision':None}
                if value!=expected or revision['parent_id']!=value['id'] or revision['predecessor']!=old['current_revision'] or revision['revision_number']!=value['revision_number'] or revision['prior_decision']!=old['last_decision'] or revision['amendment_of']!=old['closed_revision']:
                    raise DomainError('quality_safety_integrity','The successor header differs from its exact revision.',409)
            elif action in rules.TRANSITIONS:
                decision=service.read(rules.child_kind(family,'decision'),value['last_decision'],self.company,self.project,actor,lock=True,new_use=action!='return')
                expected={**old,'last_decision':decision['id'],'status':decision['to_status'],'closed_revision':old['current_revision'] if action=='close' else old['closed_revision']}
                if value!=expected or decision['action']!=action or decision['parent_id']!=value['id'] or decision['source_revision']!=old['current_revision'] or decision['predecessor']!=old['last_decision'] or decision['from_status']!=old['status']:
                    raise DomainError('quality_safety_integrity','The header differs from its exact documentary decision.',409)
            else:raise DomainError('quality_safety_command_required','Unsupported documentary command.',403)
        elif kind.endswith('revision'):
            header=service._raw(family,value['parent_id'],self.company,self.project,lock=True)
            if action not in ('create','revise') or header['status'] not in ('draft','returned','closed') or value['category']!=header['category'] or value['revision_number']!=header['revision_number']+1 or value['predecessor']!=header['current_revision'] or value['prior_decision']!=header['last_decision'] or value['amendment_of']!=header['closed_revision']:
                raise DomainError('stale_quality_safety','The current successor predecessor changed.',412)
            sources.verify([value],self.company,self.project,actor,lock=True,new_use=True)
            if family=='incident':
                from .privacy import verify_incident_evidence
                verify_incident_evidence(sources.references(value),value['definition'],self.company,self.project,actor,lock=True)
        else:
            if action not in rules.TRANSITIONS or value['action']!=action:raise DomainError('quality_safety_command_required','The documentary decision differs from its exact command.',403)
            header=service._raw(family,value['parent_id'],self.company,self.project,lock=True)
            revision,values=service._collect(rules.child_kind(family,'revision'),header['current_revision'],self.company,self.project,lock=True)
            if value['source_revision']!=revision['id'] or value['source_digest']!=digest(revision) or value['category']!=header['category'] or value['from_status']!=header['status'] or value['predecessor']!=header['last_decision']:
                raise DomainError('stale_quality_safety','The decision is not for the current exact revision.',412)
            if action!='submit' and actor.person_id==revision['author_person']:raise DomainError('independent_quality_safety_required','Another canonical person must check or close this record.',403)
            previous=None
            if header['last_decision']:
                previous,prior=service._collect(rules.child_kind(family,'decision'),header['last_decision'],self.company,self.project,lock=True);values.extend(prior)
            if action=='close':service._closure_check(value,revision,previous)
            if family=='incident':
                from .privacy import verify_incident_evidence
                verify_incident_evidence(sources.references(value),revision['definition'],self.company,self.project,actor,lock=True)
            # Current source/rights rechecked by the native controller, even if
            # an internal caller tries to invoke persistence independently.
            sources.verify([*values,value],self.company,self.project,actor,lock=True,new_use=action!='return')
            if action=='return':sources.verify([value],self.company,self.project,actor,lock=True,new_use=True)

    def on_trash(self):raise DomainError('immutable_quality_safety','Original records and their documentary history cannot be deleted.',409)
    def before_rename(self,*args,**kwargs):raise DomainError('immutable_quality_safety','Record identities cannot be renamed.',409)
