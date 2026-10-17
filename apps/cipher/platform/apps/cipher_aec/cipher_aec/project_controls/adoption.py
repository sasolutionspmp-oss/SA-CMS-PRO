"""Private initial adoption, only inside the exact literal reviewed award effect."""
from copy import deepcopy
from uuid import UUID,uuid5
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_company
from cipher_aec.documents.provenance import is_prelocked
from cipher_aec.estimating import scopes
from . import core,repository,masters


def create_initial_adoption(*,actor,company,project,award_id,award_revision_id,award_plan_digest,reviewed_plan,packet_id,decision_id,operation_id,resource_token):
    from cipher_aec.awards.effect import require_award_effect
    facts=dict(company=company,project=project,award_id=award_id,award_revision_id=award_revision_id,plan_digest=award_plan_digest,
               packet_id=packet_id,decision_id=decision_id,operation_id=operation_id)
    active=require_award_effect(**facts)
    if active.get('controls_plan_digest')!=digest(reviewed_plan) or reviewed_plan.get('company')!=company:
        raise DomainError('controls_plan_conflict','Adopt only the exact independently reviewed cost subplan.',409)
    rows=frappe.db.sql('SELECT company FROM `tabProject` WHERE name=%s',(project,))
    if len(rows)!=1 or rows[0][0]!=company:raise DomainError('controls_plan_conflict','The reviewed real Project must exist in this Company transaction.',409)
    team={row['person_id'] for row in active['approved_team']}
    if any(node['accountable_person'] is not None and node['accountable_person'] not in team for node in reviewed_plan['wbs_nodes']):
        raise DomainError('unapproved_wbs_accountability','WBS accountability must name a reviewed Project team participant.',403)
    with scopes.activate('Company',company,None):
        from cipher_aec.estimating.company_service import accepted_baseline_reference
        from cipher_aec.estimating import repository as estimates
        require_company(company,ability='project.cost.read',actor=actor,lock=True)
        reference=accepted_baseline_reference(company,reviewed_plan['acceptance']['id'],actor,lock=True)
        acceptance=estimates.read('acceptance',reference['acceptance_id'],lock=True)
        if reference['acceptance_digest']!=digest(acceptance) or reviewed_plan['acceptance']['digest']!=digest(acceptance):
            raise DomainError('controls_plan_conflict','The original accepted baseline must match exactly.',409)
        refs={}
        for kind,key in (('code','resolved_codes'),('type','resolved_types')):
            refs[key]=[masters.resolve_revision(actor=actor,company=company,kind=kind,revision_id=row['revision']['id'],basis_date=reviewed_plan['basis_date'],purpose='award.initial-budget.v1',lock=True,resource_token=resource_token) for row in reviewed_plan[key]]
        required=masters.plan_resources(actor=actor,company=company,code_revision_ids=[r['revision']['id'] for r in refs['resolved_codes']],type_revision_ids=[r['revision']['id'] for r in refs['resolved_types']],basis_date=reviewed_plan['basis_date'],purpose='award.initial-budget.v1')
        required['unit_ids']=[r['id'] for r in reviewed_plan['source_units']];required['currencies']=sorted(set(required['currencies']+[reviewed_plan['currency']]))
        if type(resource_token) is not dict or not is_prelocked(resource_token,actor,company) or not is_prelocked(required,actor,company):raise DomainError('source_prelock_required','Initial adoption requires the full original source/native resource union.',409)
        rebuilt=core.plan_initial_budget(acceptance=acceptance,wbs_nodes=reviewed_plan['wbs_nodes'],allocations=reviewed_plan['allocations'],basis_date=reviewed_plan['basis_date'],**refs)
        if rebuilt!=reviewed_plan:raise DomainError('controls_plan_conflict','Current exact cost authority no longer matches the reviewed cost plan.',412)
        budget_id=str(uuid5(UUID(award_id),'initial-budget.v1'))
        common={'company':company,'project':project,'author_person':actor.person_id,'award_context':facts,'controls_plan_digest':digest(reviewed_plan)}
        budget={'schema':'cipher.project-budget.v1','id':budget_id,**common,'award_id':award_id,'award_revision_id':award_revision_id,'status':'adopted','version_number':1,'predecessor':None,'plan':deepcopy(reviewed_plan)}
        repository.write('budget',budget)
        for node in reviewed_plan['wbs_nodes']:
            repository.write('wbs',{'schema':'cipher.project-wbs.v1','id':node['id'],**common,'budget_version':budget_id,'node':deepcopy(node)})
        for line in reviewed_plan['budget_lines']:
            repository.write('budget_line',{'schema':'cipher.project-budget-line.v1','id':line['id'],**common,'budget_version':budget_id,'line':deepcopy(line)})
        return {'budget':budget,'budget_digest':digest(budget),'wbs_ids':[n['id'] for n in reviewed_plan['wbs_nodes']],'budget_line_ids':[r['id'] for r in reviewed_plan['budget_lines']]}
