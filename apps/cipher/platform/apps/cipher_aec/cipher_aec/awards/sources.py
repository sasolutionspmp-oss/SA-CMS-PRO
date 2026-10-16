"""Exact original Company evidence and complete award source admission."""
from contextlib import contextmanager
from copy import deepcopy
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_company
from cipher_aec.commercial.sources import merge,revision_plan
from cipher_aec.documents import provenance
from cipher_aec.estimating import scopes
from . import contracts

PURPOSE='award.initial-budget.v1'


def input_qualification(acceptance):
    """Only the accepted input DAG matters; its issued PDF is ordinary output."""
    from cipher_aec.estimating.sources import GENERATED_INPUTS_QUALIFIED
    try:nodes=acceptance['manifest']['effect']['facts'].get('generated_sources',[])
    except (KeyError,TypeError,AttributeError):raise DomainError('award_integrity','The accepted original input policy cannot be verified.',409) from None
    if type(nodes) is not list:raise DomainError('award_integrity','The accepted original generated input lineage cannot be verified.',409)
    eligible=not nodes or GENERATED_INPUTS_QUALIFIED
    return {'policy':'qualified-original-estimate-inputs-v1','eligible':eligible,'generated_input_count':len(nodes),
        'disabled_reason':None if eligible else 'This accepted baseline depends on generated estimate inputs whose runtime qualification is incomplete.'}


def require_qualified_inputs(acceptance):
    qualification=input_qualification(acceptance)
    if not qualification['eligible']:
        raise DomainError('award_estimate_inputs_unqualified',qualification['disabled_reason'],409)
    return qualification


def issue_record(company,issue_id,*,lock=False):
    """Internal source identity discovery only; no public authorization."""
    import json
    rows=frappe.db.sql('SELECT data_json,record_digest FROM `tabCipher Proposal Issue` WHERE name=%s AND company=%s'+(' FOR UPDATE' if lock else ''),(contracts.identifier(issue_id),company))
    if not rows:raise DomainError('not_found','The issued award source is not available.',404)
    value=json.loads(rows[0][0])
    if value.get('id')!=issue_id or value.get('company')!=company or digest(value)!=rows[0][1]:raise DomainError('issue_integrity','The issued award source cannot be verified.',409)
    return value


def code_ids(definition):
    try:
        return sorted({r['code_revision_id'] for r in definition['budget_allocations']}),sorted({r['type_revision_id'] for r in definition['budget_allocations']})
    except (TypeError,KeyError):raise DomainError('invalid_award','Map every accepted cost allocation to exact canonical revisions.',422) from None


def resource_plan(company,issue,definition,lines,actor,*,lock=False):
    from . import native
    from cipher_aec.project_controls.masters import plan_resources
    plans=[revision_plan(company,issue['proposal_revision'],actor,lock=lock),provenance.source_plan(company,issue['output_revision'],actor,lock=lock),
        native.plan_resources(company=company,issue=issue,lines=lines,definition=definition['native_order_definition'],actor=actor,lock=lock)]
    for row in definition['award_evidence']:plans.append(provenance.source_plan(company,row['revision_id'],actor,lock=lock))
    codes,types=code_ids(definition)
    plans.append(plan_resources(actor=actor,company=company,code_revision_ids=codes,type_revision_ids=types,basis_date=definition['native_order_definition']['transaction_date'],purpose=PURPOSE))
    return merge(*plans)


@contextmanager
def admitted(company,issue,definition,lines,actor,*,lock=False):
    from cipher_aec.estimating.lockplan import prepared
    with scopes.activate('Company',company,None):
        plan=resource_plan(company,issue,definition,lines,actor,lock=lock)
        if lock:
            with prepared(plan,actor,company,lock=True) as held:yield held
        else:yield plan


def facts(company,issue_id,definition,lines,actor,*,lock=False,resource_token,require_create=True):
    """Full current source rights; no mutable quote or estimate-head substitution."""
    for ability in ('commercial.read','document.read','estimate.read','project.cost.read'):
        require_company(company,ability=ability,actor=actor,lock=lock)
    from cipher_aec.commercial.outputs import issue_source_reference
    from cipher_aec.commercial.service import _read
    from cipher_aec.estimating.company_service import accepted_baseline_reference
    from cipher_aec.estimating import repository as estimates
    from cipher_aec.documents.service import get_company_citation
    from cipher_aec.project_controls.masters import resolve_revision
    from cipher_aec.project_controls.core import plan_initial_budget
    from . import native
    with scopes.activate('Company',company,None):
        source=issue_source_reference(company,issue_id,actor,lock=lock)
        issue=source['issue']
        proposal=_read('proposal',issue['proposal'],company,actor,lock=lock)[1]
        pursuit=_read('pursuit',proposal['pursuit'],company,actor,lock=lock)[1]
        baseline=accepted_baseline_reference(company,issue['accepted_estimate']['acceptance_id'],actor,lock=lock)
        if baseline!=issue['accepted_estimate'] or baseline['pursuit_id']!=pursuit['id']:
            raise DomainError('award_source_conflict','The issued accepted baseline must belong to this exact pursuit.',409)
        acceptance=estimates.read('acceptance',baseline['acceptance_id'],lock=lock)
        require_qualified_inputs(acceptance)
        native_facts=native.authorize_sources(actor=actor,company=company,lines=lines,definition=definition['native_order_definition'],resource_token=resource_token,lock=lock,require_create=require_create)
        customer=definition['native_order_definition']['customer']
        correspondence=definition['party_correspondence']
        if pursuit['party_type']=='Customer':
            if pursuit['party_id']!=customer or correspondence is not None:
                raise DomainError('award_customer_conflict','An issued native Customer cannot be substituted.',409)
        elif pursuit['party_type']=='Lead':
            if correspondence is None or correspondence['lead']!=pursuit['party_id'] or correspondence['customer']!=customer:
                raise DomainError('award_customer_correspondence_required','Bind the explicit existing Customer correspondence for the original Lead.',409)
        else:raise DomainError('award_customer_conflict','Unsupported issued counterparty.',409)
        evidence=[]
        for row in definition['award_evidence']:
            citation=get_company_citation(company,row['revision_id'],row['page'],row['excerpt_sha256'],actor,lock=lock)
            if citation['source_sha256']!=row['source_sha256']:raise DomainError('source_integrity','The exact award evidence bytes changed.',409)
            evidence.append({'citation':citation,'purpose':row['purpose'],'permission_basis':row['permission_basis']})
        codes,types=code_ids(definition);date=definition['native_order_definition']['transaction_date']
        resolved_codes=[resolve_revision(actor=actor,company=company,kind='code',revision_id=n,basis_date=date,purpose=PURPOSE,lock=lock,resource_token=resource_token) for n in codes]
        resolved_types=[resolve_revision(actor=actor,company=company,kind='type',revision_id=n,basis_date=date,purpose=PURPOSE,lock=lock,resource_token=resource_token) for n in types]
        budget=plan_initial_budget(acceptance=acceptance,wbs_nodes=definition['wbs_nodes'],allocations=definition['budget_allocations'],
            resolved_codes=resolved_codes,resolved_types=resolved_types,basis_date=date)
        return {'issue':issue,'issue_digest':digest(issue),'pursuit':pursuit['id'],'opportunity':pursuit['opportunity'],
            'accepted_estimate':baseline,'acceptance':acceptance,'controls_plan':budget,'native_sources':native_facts,
            'award_evidence':evidence,'issued_output':{k:issue['prepared_output'][k] for k in ('document_id','revision_id','source_sha256','byte_length','input_digest')}}


def authorize_historical(company,plan,actor,*,lock=False):
    """Exact stored source rights, separate from new-use/source-head eligibility."""
    from contextlib import nullcontext
    from cipher_aec.estimating.lockplan import prepared
    from cipher_aec.commercial.outputs import issue_source_reference
    from cipher_aec.estimating.company_service import accepted_baseline_reference
    from cipher_aec.documents.service import get_company_citation
    from cipher_aec.project_controls.masters import resolve_revision
    from cipher_aec.commercial.native import require_native
    for ability in ('commercial.read','document.read','estimate.read','project.cost.read'):
        require_company(company,ability=ability,actor=actor,lock=lock)
    from cipher_aec.project_controls.masters import plan_resources
    codes=[row['revision']['id'] for row in plan['controls_plan']['resolved_codes']]
    types=[row['revision']['id'] for row in plan['controls_plan']['resolved_types']]
    # Discovery adds current native permission dependencies (e.g. an Account's
    # current Currency) before any shared-master lock, without changing stored
    # original facts or using a later cost master/award plan revision.
    current_cost_plan=plan_resources(actor=actor,company=company,code_revision_ids=codes,type_revision_ids=types,
        basis_date=plan['definition']['native_order_definition']['transaction_date'],purpose=PURPOSE)
    resources=merge(plan['resource_plan'],current_cost_plan)
    with scopes.activate('Company',company,None),prepared(resources,actor,company,lock=True) if lock else nullcontext():
        actual=issue_source_reference(company,plan['issue'],actor,lock=lock)['issue']
        if digest(actual)!=plan['issue_digest'] or actual['accepted_estimate']!=plan['source_facts']['accepted_estimate']:
            raise DomainError('award_integrity','The original issued award lineage cannot be verified.',409)
        baseline=accepted_baseline_reference(company,actual['accepted_estimate']['acceptance_id'],actor,lock=lock)
        if baseline!=actual['accepted_estimate']:raise DomainError('award_integrity','The exact accepted original baseline cannot be verified.',409)
        for row in plan['source_facts']['award_evidence']:
            old=row['citation']
            current=get_company_citation(company,old['revision_id'],old['page'],old['excerpt_sha256'],actor,lock=lock)
            if current!=old:raise DomainError('source_integrity','The exact historical award evidence cannot be verified.',409)
        for row in resources['native_refs']:require_native(row['doctype'],row['name'],actor,lock=lock)
        date=plan['definition']['native_order_definition']['transaction_date']
        for kind,key in (('code','resolved_codes'),('type','resolved_types')):
            for old in plan['controls_plan'][key]:
                # Revision identity is immutable; current native permission is
                # mandatory while disabled/newer heads do not erase history.
                resolve_revision(actor=actor,company=company,kind=kind,revision_id=old['revision']['id'],basis_date=date,
                    purpose=PURPOSE,lock=lock,resource_token=resources,for_new=False)
