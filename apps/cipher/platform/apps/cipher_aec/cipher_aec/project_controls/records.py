"""Native controllers require the exact typed authoring or registered award effect."""
from contextvars import ContextVar
from contextlib import contextmanager
import json
from frappe.model.document import Document
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_company,require_trusted_write
from . import core,repository
_writing=ContextVar('cipher_controls_exact_write',default=None)

@contextmanager
def exact_write(kind,value):
    token=_writing.set((kind,value['id'],digest(value)))
    try:yield
    finally:_writing.reset(token)

class ProjectControlRecord(Document):
    def validate(self):
        require_trusted_write()
        try:value=json.loads(self.data_json)
        except (TypeError,ValueError):core.fail('Supply canonical project controls data.')
        kind=next(k for k,v in repository.DOCTYPES.items() if v==self.doctype)
        core.identifier(self.name)
        shared={'schema','id','company','project','author_person'}
        fields=(shared|{'kind','code','current_revision','revision_number'} if kind in {'code','type'} else
                shared|{'kind','code','master_id','revision_number','predecessor','definition','authored_native'} if kind.endswith('_revision') else
                shared|{'award_context','controls_plan_digest'}|({'award_id','award_revision_id','status','version_number','predecessor','plan'} if kind=='budget' else {'budget_version','node' if kind=='wbs' else 'line'}))
        core.closed(value,fields,'controls_record')
        expected_schema={'code':'cipher.cost-master.v1','type':'cipher.cost-master.v1','code_revision':'cipher.cost-revision.v1','type_revision':'cipher.cost-revision.v1','wbs':'cipher.project-wbs.v1','budget':'cipher.project-budget.v1','budget_line':'cipher.project-budget-line.v1'}[kind]
        if value['schema']!=expected_schema or kind in {'code','type','code_revision','type_revision'} and value['kind']!=kind.removesuffix('_revision'):
            raise DomainError('controls_integrity','The exact typed controls schema/kind must agree.',409)

        if _writing.get()!=(kind,self.name,digest(value)) or value.get('id')!=self.name:
            raise DomainError('controls_effect_required','Use the exact supported controls effect.',403)
        for key,expected in repository.projection(kind,value).items():
            actual=self.get(key)
            if actual!=expected and not (actual in (None,'') and expected is None):
                raise DomainError('controls_integrity','Native controls projection does not match exact facts.',409,{'field':key})
        actor=current_actor()
        if kind in {'code','type','code_revision','type_revision'}:
            from .masters import _authoring
            if _authoring.get()!=(actor.user,actor.person_id,value['company']):raise DomainError('cost_effect_required','Use a canonical cost authoring command.',403)
            require_company(value['company'],ability='project.cost.write',actor=actor,lock=True)
            require_company(value['company'],ability='project.cost.read',actor=actor,lock=True)
            if value.get('project') is not None:core.fail('Cost masters have exact Company scope.')
            if kind.endswith('_revision'):
                if not self.is_new():raise DomainError('immutable_cost_revision','Author a successor cost revision.',409)
                core.definition(value['kind'],value['definition'])
                parent=repository.read(value['kind'],value['master_id'],lock=True)
                if any(parent[k]!=value[k] for k in ('company','kind','code')) or value['revision_number']!=parent['revision_number']+1 or value['predecessor']!=parent['current_revision']:
                    raise DomainError('controls_integrity','Cost revision lineage must extend its exact master.',409)
            elif not self.is_new():
                before=json.loads(self.get_doc_before_save().data_json)
                if {k:v for k,v in before.items() if k not in {'current_revision','revision_number'}}!={k:v for k,v in value.items() if k not in {'current_revision','revision_number'}} or value['revision_number']!=before['revision_number']+1:
                    raise DomainError('immutable_cost_identity','Original master identity and scope cannot change.',409)
                successor=repository.read(kind+'_revision',value['current_revision'],lock=True)
                if successor['master_id']!=value['id'] or successor['predecessor']!=before['current_revision'] or successor['revision_number']!=value['revision_number']:
                    raise DomainError('controls_integrity','Master head must match its exact immutable successor.',409)
            if self.is_new() and value['author_person']!=actor.person_id:raise DomainError('forged_authority','Use the current canonical author.',403)
        else:
            from cipher_aec.awards.effect import require_award_effect
            facts=value['award_context']
            effect=require_award_effect(**facts)
            core.validate_adoption_identity(kind,value,effect,actor.person_id)
            if not self.is_new():raise DomainError('immutable_budget','Initial WBS and adopted budget facts are immutable.',409)
            if kind=='budget':
                if digest(value['plan'])!=value['controls_plan_digest'] or value['plan']['company']!=value['company'] or value['status']!='adopted' or value['version_number']!=1 or value['predecessor'] is not None:
                    raise DomainError('controls_integrity','The initial budget must retain its exact reviewed plan.',409)
            else:
                budget=repository.read('budget',value['budget_version'],lock=True)
                if any(budget[k]!=value[k] for k in ('company','project','award_context','controls_plan_digest')):
                    raise DomainError('controls_integrity','Initial adoption lineage must agree.',409)
                if kind=='wbs' and value['node'] not in budget['plan']['wbs_nodes'] or kind=='budget_line' and value['line'] not in budget['plan']['budget_lines']:
                    raise DomainError('controls_integrity','Adopt only exact reviewed WBS/budget facts.',409)

    def on_trash(self):raise DomainError('controls_history_preserved','Controls history cannot be deleted.',403)
    def before_rename(self,*args,**kwargs):raise DomainError('immutable_controls_identity','Controls identities cannot be renamed.',403)
