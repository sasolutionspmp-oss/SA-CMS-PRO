"""Atomic full award: one preallocated Project, draft order/contract and exact cost/team."""
from copy import deepcopy
from uuid import UUID,uuid5
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.history import append_company_event,append_event
from . import repository,service,sources,team,effect,native,preallocation


def apply(*,actor,company,manifest,packet_id,decision_id,operation_id):
    approved=manifest['effect'];plan=repository.read('revision',approved['award_revision_id'],company,lock=True)
    if approved['plan']!=plan or approved['plan_digest']!=digest(plan):
        raise DomainError('stale_award','The exact reviewed immutable award plan is required.',412)
    allocated=preallocation.current(company=company,packet_id=packet_id,award_revision_id=plan['id'],operation_id=operation_id,plan_digest=digest(plan))
    project=allocated['project']
    parent=repository.read('handoff',plan['handoff'],company,lock=True)
    if parent['current_revision']!=plan['id'] or parent['status']!='draft' or parent['adoption']:
        raise DomainError('award_already_adopted','This full pursuit award was already adopted or changed.',409)
    built=service._build(company,parent,plan['definition'],actor,ids=plan['ids'],lock=True)
    if any(plan.get(k)!=v for k,v in built.items()):
        raise DomainError('stale_award_sources','Current exact source, native, cost or team facts changed.',412)
    issue=sources.issue_record(company,plan['issue'],lock=True)
    from cipher_aec.estimating import scopes
    from cipher_aec.estimating.lockplan import prepared
    with scopes.activate('Company',company,None),prepared(built['resource_plan'],actor,company,lock=True) as token, \
        effect.adoption_effect(actor=actor,company=company,project=project,plan=plan,issue=issue,packet_id=packet_id,decision_id=decision_id,operation_id=operation_id):
        from cipher_aec.construction_finance import award_factory
        award_factory.admission_preflight(actor=actor,company=company,project=project,plan=plan,packet_id=packet_id,decision_id=decision_id,operation_id=operation_id,resource_token=token)
        binding={'company':company,'project':project,'award_id':parent['id'],'award_revision_id':plan['id'],'plan_digest':digest(plan),
            'packet_id':packet_id,'decision_id':decision_id,'operation_id':operation_id}
        order=native.create_order(actor=actor,issue=issue,lines=plan['lines'],definition=plan['definition']['native_order_definition'],resource_token=token,**binding)
        effect.record_native_output(order)
        contract=award_factory.create_initial_contract(actor=actor,company=company,project=project,plan=plan,packet_id=packet_id,decision_id=decision_id,operation_id=operation_id,resource_token=token)
        append_event(actor=actor,company=company,project=project,operation_id=operation_id,event='contract.created',subject_type='Cipher Construction Contract',subject_id=contract['id'],
            details={'record_id':contract['id'],'record_digest':digest(contract)})
        from cipher_aec.project_controls.adoption import create_initial_adoption
        controls=create_initial_adoption(actor=actor,company=company,project=project,award_id=parent['id'],award_revision_id=plan['id'],
            award_plan_digest=digest(plan),reviewed_plan=plan['controls_plan'],packet_id=packet_id,decision_id=decision_id,operation_id=operation_id,resource_token=token)
        duty_ids=team.assign_initial(actor=actor,value=plan['definition']['team'],**binding)
        common={'company':company,'scope_type':'Company','project':None,'target_project':project,'handoff':parent['id'],
            'award_revision':plan['id'],'pursuit':parent['pursuit'],'opportunity':parent['opportunity'],'issue':plan['issue'],'issue_digest':plan['issue_digest'],
            'sales_order':order['sales_order'],'contract':contract['id'],'effect_binding':binding}
        adoption=service._base(actor,company,**{k:v for k,v in common.items() if k not in {'company','scope_type','project'}},
            id=plan['ids']['adoption_id'],schema='cipher.award.adoption.v1',status='adopted',plan_digest=digest(plan),
            accepted_estimate=deepcopy(plan['source_facts']['accepted_estimate']),native_digest=order['native_digest'],native_version=order['native_version'],
            native_snapshot=deepcopy(order['native_snapshot']),profile=plan['ids']['profile_id'],budget=controls['budget']['id'],
            controls_plan_digest=digest(plan['controls_plan']),team=deepcopy(plan['definition']['team']['members']),
            line_adoptions=[row['award_line_id'] for row in plan['lines']],packet_id=packet_id,decision_id=decision_id,operation_id=operation_id)
        repository.write('adoption',adoption)
        by_line={row['cipher_award_line_id']:row for row in order['native_snapshot']['projection']['rows']}
        for line in plan['lines']:
            value=service._base(actor,company,**{k:v for k,v in common.items() if k not in {'company','scope_type','project'}},
                id=line['award_line_id'],schema='cipher.award.line-adoption.v1',status='adopted',adoption=adoption['id'],
                proposal_line_id=line['proposal_line_id'],sales_order_item=by_line[line['award_line_id']]['name'],source_line=deepcopy(line))
            repository.write('line',value)
        profile=deepcopy(allocated['profile']);profile.update(status='adopted',adoption=adoption['id'],sales_order=order['sales_order'],contract=contract['id'])
        repository.write('profile',profile,update=True)
        parent.update(status='adopted',adoption=adoption['id']);repository.write('handoff',parent,update=True)
        append_company_event(actor=actor,company=company,operation_id=operation_id,event='award.adopted',
            subject_type='Cipher Award Adoption',subject_id=adoption['id'],details={'award':parent['id'],'award_revision':plan['id'],'adoption_digest':digest(adoption)})
        append_event(actor=actor,company=company,project=project,operation_id=operation_id,event='project.award.created',subject_type='Project',subject_id=project,
            details={'award':parent['id'],'award_revision':plan['id'],'adoption':adoption['id'],'initial_team_duties':len(duty_ids)})
        # Stable Company-owned result. Current destination access is separately
        # reauthorized by get_handoff and never frozen as a permanent entitlement.
        return {'adoption':adoption,'version':digest(adoption)}
