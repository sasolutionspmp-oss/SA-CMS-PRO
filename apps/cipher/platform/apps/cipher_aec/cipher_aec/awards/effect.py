"""Literal award execution capabilities; never a generic financial bypass."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError

ACTION = 'award.project.create.v1'
_active = ContextVar('cipher_exact_award_adoption', default=None)
_native = ContextVar('cipher_exact_award_sales_order', default=None)


def require_award_effect(*, company, project, award_id, award_revision_id, plan_digest, packet_id, decision_id, operation_id):
    from cipher_aec.governance.approvals import require_approval_effect
    grant = require_approval_effect(action=ACTION, subject_id=award_revision_id, packet_id=packet_id, scope_type='Company')
    expected = dict(company=company,project=project,award_id=award_id,award_revision_id=award_revision_id,
        plan_digest=plan_digest,packet_id=packet_id,decision_id=decision_id,operation_id=operation_id)
    active = _active.get()
    if not active or any(active.get(k)!=v for k,v in expected.items()) or grant['company']!=company:
        raise DomainError('award_effect_required','This exact reviewed award adoption is required.',403)
    return deepcopy(active)


@contextmanager
def adoption_effect(*,actor,company,project,plan,issue,packet_id,decision_id,operation_id):
    """Only the exact packet plan may establish the private factory context."""
    from cipher_aec.governance.approvals import require_approval_effect
    from .preallocation import current
    grant=require_approval_effect(action=ACTION,subject_id=plan['id'],packet_id=packet_id,scope_type='Company')
    allocated=current(company=company,packet_id=packet_id,award_revision_id=plan['id'],operation_id=operation_id,plan_digest=digest(plan))
    if (grant['company']!=company or grant['source_version']!=digest(plan) or plan['company']!=company
            or allocated['project']!=project or allocated['decision_id']!=decision_id or digest(issue)!=plan['issue_digest']):
        raise DomainError('award_effect_conflict','The exact approved source and allocated destination must match.',409)
    if _active.get() is not None:
        raise DomainError('nested_award_effect','An award adoption cannot be nested.',409)
    facts={'company':company,'project':project,'award_id':plan['handoff'],'award_revision_id':plan['id'],
        'plan_digest':digest(plan),'packet_id':packet_id,'decision_id':decision_id,'operation_id':operation_id,
        'actor_person':actor.person_id,'actor_user':actor.user,'plan':deepcopy(plan),'issue':deepcopy(issue),
        'adoption_id':plan['ids']['adoption_id'],'contract_id':plan['ids']['contract_id'],'profile_id':plan['ids']['profile_id'],
        'approved_team':deepcopy(plan['definition']['team']['members']),'controls_plan_digest':digest(plan['controls_plan']),
        'issue_digest':digest(issue),'lines_digest':digest(plan['lines']),'native_definition_digest':digest(plan['definition']['native_order_definition']),
        'contract_definition_digest':digest(plan['definition']['contract_definition']),'native_output':None,'admission_preflight':None}
    token=_active.set(facts)
    try:yield deepcopy(facts)
    finally:_active.reset(token)


def record_native_output(result):
    """Bind current supported native persisted projection, never caller labels."""
    active=_active.get()
    if active is None or active['native_output'] is not None:
        raise DomainError('award_effect_required','A single native order output is required inside the exact award.',403)
    from . import native
    actual=native.snapshot(sales_order_id=result['sales_order'],lock=True)
    expected=native.reconcile(actual,company=active['company'],project=active['project'],award_id=active['award_id'],
        issue=active['issue'],lines=active['plan']['lines'],definition=active['plan']['definition']['native_order_definition'])
    if actual!=result['native_snapshot'] or actual['digest']!=expected or actual['derived_digest']!=expected or actual['version']!=result['native_version'] or result['native_digest']!=expected:
        raise DomainError('award_native_integrity','The persisted native factory output cannot be verified.',409)
    active['native_output']=deepcopy(result)


def validate_adoption_record(kind,value):
    binding=value.get('effect_binding',{})
    if type(binding) is not dict or set(binding)!={'company','project','award_id','award_revision_id','plan_digest','packet_id','decision_id','operation_id'}:
        raise DomainError('award_integrity','The exact adoption effect binding is required.',409)
    active=require_award_effect(**binding)
    plan=active['plan'];native=active['native_output']
    if native is None:raise DomainError('award_integrity','Adoption requires the complete persisted native order.',409)
    expected={'company':active['company'],'scope_type':'Company','project':None,'target_project':active['project'],
        'author_person':active['actor_person'],'author_user':active['actor_user'],'handoff':active['award_id'],
        'award_revision':plan['id'],'pursuit':plan['source_facts']['pursuit'],'opportunity':plan['source_facts']['opportunity'],
        'issue':plan['issue'],'issue_digest':plan['issue_digest'],'contract':active['contract_id'],'sales_order':native['sales_order']}
    if any(value.get(k)!=v for k,v in expected.items()):
        raise DomainError('award_integrity','The adoption must retain the exact reviewed scope, author and source mappings.',409)
    if kind=='adoption':
        expected={'id':active['adoption_id'],'schema':'cipher.award.adoption.v1','status':'adopted','plan_digest':active['plan_digest'],
            'accepted_estimate':plan['source_facts']['accepted_estimate'],'native_digest':native['native_digest'],
            'native_version':native['native_version'],'native_snapshot':native['native_snapshot'],'profile':active['profile_id'],
            'budget':value.get('budget'),'controls_plan_digest':active['controls_plan_digest'],'team':active['approved_team'],
            'line_adoptions':[r['award_line_id'] for r in plan['lines']],
            'packet_id':active['packet_id'],'decision_id':active['decision_id'],'operation_id':active['operation_id']}
        from uuid import UUID,uuid5
        expected['budget']=str(uuid5(UUID(active['award_id']),'initial-budget.v1'))
        if any(value.get(k)!=v for k,v in expected.items()):raise DomainError('award_integrity','The complete canonical adoption snapshot differs from the reviewed outcome.',409)
    elif kind=='line':
        line=next((row for row in plan['lines'] if row['award_line_id']==value['id']),None)
        native_row=next((row for row in native['native_snapshot']['projection']['rows'] if row['cipher_award_line_id']==value['id']),None)
        if line is None or native_row is None or value.get('source_line')!=line or value.get('proposal_line_id')!=line['proposal_line_id'] or value.get('sales_order_item')!=native_row['name'] or value.get('adoption')!=active['adoption_id'] or value.get('schema')!='cipher.award.line-adoption.v1' or value.get('status')!='adopted':
            raise DomainError('award_integrity','Each adopted line must equal its exact reviewed/native source identity.',409)
    else:raise DomainError('award_integrity','Only the two literal adoption records use this assertion.',409)
    return active


@contextmanager
def native_order_effect(*, actor, company, project, award_id, award_revision_id, plan_digest, issue, lines, definition, packet_id, decision_id, operation_id):
    facts=dict(company=company,project=project,award_id=award_id,award_revision_id=award_revision_id,
        plan_digest=plan_digest,packet_id=packet_id,decision_id=decision_id,operation_id=operation_id)
    approved=require_award_effect(**facts)
    if (approved.get('issue_digest')!=digest(issue) or approved.get('lines_digest')!=digest(lines)
            or approved.get('native_definition_digest')!=digest(definition)):
        raise DomainError('award_effect_conflict','The native factory payload differs from the exact independently reviewed plan.',409)
    from .runtime import require_native_profile
    require_native_profile()
    if approved.get('admission_preflight') is None:
        raise DomainError('award_admission_required','The exact Customer-mutex preflight must precede the native order.',403)
    if _native.get() is not None:
        raise DomainError('nested_award_effect','Native award factories cannot be nested.',409)
    state={**facts,'actor_user':actor.user,'issue':deepcopy(issue),'lines':deepcopy(lines),'definition':deepcopy(definition),'name':None}
    token=_native.set(state)
    try:yield
    finally:_native.reset(token)


def validate_native_order(doc, method=None):
    """All other drafts/submits/cancels/deletes stay closed, including admin APIs."""
    from decimal import Decimal
    import frappe
    from .runtime import require_native_profile
    require_native_profile()
    state=_native.get()
    if not state or doc.doctype!='Sales Order' or method in {'before_submit','before_cancel','before_update_after_submit','on_trash'}:
        raise DomainError('financial_action_unqualified','This native obligation writer requires its exact qualified award factory.',403)
    require_award_effect(**{k:state[k] for k in ('company','project','award_id','award_revision_id','plan_digest','packet_id','decision_id','operation_id')})
    issue, definition=state['issue'],state['definition']
    fields={'company':state['company'],'project':state['project'],'customer':definition['customer'],'currency':issue['composition']['currency'],
        'cipher_award_handoff':state['award_id'],'cipher_issue':issue['id'],'cipher_issue_digest':digest(issue),
        'cipher_proposal_revision':issue['proposal_revision'],'cipher_accepted_baseline':issue['accepted_estimate']['acceptance_id']}
    if (frappe.session.user!=state['actor_user'] or doc.docstatus!=0 or doc.get('amended_from') or doc.get('tc_name') or doc.get('payment_terms_template') or getattr(doc.flags,'updater_reference',None)
            or doc.is_new() and getattr(doc,'_doc_before_save',None)
            or not doc.is_new() and getattr(doc.flags,'ignore_version',None) is not True
            or any(doc.get(k)!=v for k,v in fields.items())):
        raise DomainError('award_native_integrity','The native order must preserve its exact reviewed award scope.',409)
    # Native AccountsController creates its one default row during validate.
    # Before that stage an empty table is allowed; after it, the whole exact
    # default policy must hold before either parent or child is persisted.
    payments=doc.get('payment_schedule') or []
    if payments or method in {'validate','before_save'}:
        from .native import PAYMENT_NUMBERS,PAYMENT_TEXT
        if len(payments)!=1:
            raise DomainError('award_native_integrity','The exact single native default payment schedule is required.',409)
        payment=payments[0]
        texts={key:'' for key in PAYMENT_TEXT if key!='name'}
        texts.update(due_date=definition['transaction_date'],discount_type='Percentage')
        numbers={key:'0' for key in PAYMENT_NUMBERS};numbers['invoice_portion']='100'
        for key in ('payment_amount','base_payment_amount','outstanding','base_outstanding'):numbers[key]=issue['pricing']['total']
        if any(str(payment.get(key) or '')!=value for key,value in texts.items()) or any(Decimal(str(payment.get(key) or 0))!=Decimal(value) for key,value in numbers.items()):
            raise DomainError('award_native_integrity','Native payment defaults must retain the reviewed full-value transaction-date policy.',409)
    if state['name'] is None:
        if not doc.is_new():
            raise DomainError('award_native_integrity','The factory can create only its reviewed new order.',409)
        if doc.name:state['name']=doc.name
    elif doc.name!=state['name']:
        raise DomainError('award_native_integrity','One award factory can write only one native order.',409)
    expected={line['award_line_id']:line for line in state['lines']}
    if len(doc.items)!=len(expected) or len({r.cipher_award_line_id for r in doc.items})!=len(expected):
        raise DomainError('award_native_integrity','The native order requires the complete reviewed line set.',409)
    for row in doc.items:
        line=expected.get(row.cipher_award_line_id)
        if not line or row.cipher_proposal_line_id!=line['proposal_line_id'] or row.item_code!=line['item_code'] or row.uom!=line['unit']['target']['name'] or row.stock_uom!=row.uom or row.prevdoc_docname or row.quotation_item:
            raise DomainError('award_native_integrity','Native order lines cannot substitute issued lineage.',409)
        for key,exact in (('qty',line['quantity']),('rate',line['rate']),('amount',line['amount']),('conversion_factor','1')):
            if Decimal(str(row.get(key) or 0))!=Decimal(exact):
                raise DomainError('award_native_integrity','Native award quantities and values must equal the exact reviewed lines.',409)
    from .runtime import quiet_award_write
    quiet_award_write(doc)


def native_order_active():
    """Literal native hook dispatch only; this is not an effect capability."""
    return _native.get() is not None


def record_admission_preflight(proof):
    active=_active.get()
    if active is None or active['admission_preflight'] is not None or active['native_output'] is not None or proof.get('contract_id')!=active['contract_id'] or proof.get('status') not in {'new_contract_without_supported_obligations','qualified_award_observations'}:
        raise DomainError('award_admission_required','Only the exact one-time pre-order admission may be retained.',403)
    active['admission_preflight']=deepcopy(proof)
