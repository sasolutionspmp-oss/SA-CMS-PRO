"""Effective canonical Company cost masters, with finite native target profile."""
from copy import deepcopy
from contextvars import ContextVar
from contextlib import contextmanager
from uuid import uuid4
import frappe
from cipher_aec.api.contracts import digest,version_of
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_company,current_actor
from cipher_aec.commercial.native import require_native
from . import core,repository

PURPOSES={'award.initial-budget.v1','cost.author.v1','historical_read'}
_authoring=ContextVar('cipher_cost_authoring',default=None)

@contextmanager
def authoring(actor,company):
    token=_authoring.set((actor.user,actor.person_id,company))
    try:yield
    finally:_authoring.reset(token)


def _purpose(purpose):
    if purpose not in PURPOSES:core.fail('Use a fixed project controls source purpose.','purpose')

def _scope(value,company):
    if value.get('company')!=company or value.get('project') is not None:raise DomainError('not_found','This cost master is not available.',404)

def _native_plan(target):
    # Discovery is metadata only; eligibility and permissions are checked after admission.
    currencies=[]
    if target['doctype']=='Account':
        rows=frappe.db.sql('SELECT a.name,COALESCE(NULLIF(a.account_currency,\'\'),c.default_currency) FROM `tabAccount` a JOIN `tabCompany` c ON c.name=a.company WHERE a.name=%s',(target['name'],))
        if rows and rows[0][1]:currencies=[rows[0][1]]
    else:
        rows=frappe.db.sql('SELECT name FROM `tabCost Center` WHERE name=%s',(target['name'],))
    # SQL may resolve case/accent aliases to the same row. Admit only its exact
    # canonical name so Python resource ordering cannot describe aliases as
    # different locks. Metadata identity grants no current native read right.
    if len(rows)!=1:
        raise DomainError('not_found','This native cost target is not available.',404)
    core.require_native_identity(target['name'],rows[0][0])
    return {'unit_ids':[],'currencies':currencies,'native_refs':[deepcopy(target)],'generated_sources':[]}

def plan_resources(*,actor,company,code_revision_ids,type_revision_ids,basis_date,purpose):
    _purpose(purpose);core.business_date(basis_date,'basis_date')
    require_company(company,ability='project.cost.read',actor=actor)
    refs={};currencies=set();revisions=[]
    for kind,ids in (('code',code_revision_ids),('type',type_revision_ids)):
        if type(ids) is not list or len(ids)>500 or len(set(ids))!=len(ids):core.fail('Supply a bounded unique revision set.','revision_ids')
        for name in sorted(ids):
            value=repository.read(kind+'_revision',name);_scope(value,company)
            target=core.definition(kind,value['definition'])['native_target'];plan=_native_plan(target)
            refs[(target['doctype'],target['name'])]=target;currencies.update(plan['currencies'])
            original_currency=value['authored_native'].get('account_currency')
            if original_currency:currencies.add(original_currency)
            revisions.append({'kind':kind,'id':name,'digest':digest(value)})
    return {'unit_ids':[],'currencies':sorted(currencies),'native_refs':[refs[k] for k in sorted(refs)],'generated_sources':[],
            'cost_revisions':revisions}

def _admitted(plan,actor,company,token):
    from cipher_aec.documents.provenance import is_prelocked
    from cipher_aec.estimating.lockplan import resources
    if type(token) is not dict or not is_prelocked(token,actor,company) or not is_prelocked(plan,actor,company) or any(not a<=b for a,b in zip(resources(plan),resources(token))):
        raise DomainError('source_prelock_required','The complete cost/native resource union must be admitted first.',409)

def authorize_native(*,actor,company,kind,definition,for_new,lock=False,resource_token=None):
    target=definition['native_target'];plan=_native_plan(target)
    if lock:_admitted(plan,actor,company,resource_token)
    # Company was acquired before the union. Its current locked fallback must
    # be read before native acquisition; no later Currency may be discovered.
    company_record=require_company(company,ability='project.cost.read',actor=actor,lock=lock)
    # Outer union owns native locks; these rechecks cannot acquire missing resources.
    for currency in plan['currencies']: require_native('Currency',currency,actor,lock=lock)
    doc=require_native(target['doctype'],target['name'],actor,lock=lock)
    core.require_native_identity(target['name'],doc.name)
    if doc.company!=company:raise DomainError('not_found','This native cost target is not available.',404)
    if kind=='type':core.check_admitted_currency(plan['currencies'],doc.get('account_currency'),company_record.default_currency)
    if for_new and (doc.get('disabled') or doc.get('is_group') or kind=='type' and doc.get('root_type')!='Expense'):
        raise DomainError('ineligible_cost_target','Use an enabled same-Company leaf Cost Center or expense Account.',422)
    currency_policy=None
    if kind=='type' and for_new:
        from cipher_aec.estimating.units import currency_policy as qualify_currency
        currency_policy=qualify_currency(plan['currencies'][0],lock=lock,actor=actor) if plan['currencies'] else None
        if currency_policy is None:raise DomainError('currency_setup_required','The expense accounting target requires an explicit qualified Currency.',409)
    return {'currency_policy':currency_policy,'doctype':target['doctype'],'name':doc.name,'company':doc.company,'version':version_of(doc),
            'is_group':bool(doc.get('is_group')),'disabled':bool(doc.get('disabled')),
            'root_type':doc.get('root_type') if kind=='type' else None,'account_currency':plan['currencies'][0] if kind=='type' and plan['currencies'] else None}

def effective_revision(kind,master,basis_date,*,lock=False):
    """Bounded immutable-date selection, not authority or use eligibility."""
    rows=frappe.db.sql(f'SELECT name FROM `tab{repository.DOCTYPES[kind+"_revision"]}` WHERE master=%s ORDER BY revision_number DESC LIMIT 201'+(' FOR UPDATE' if lock else ''),(master['id'],))
    if len(rows)>200:raise DomainError('cost_revision_limit','Cost revision history exceeds its qualified bound.',409)
    for row in rows:
        value=repository.read(kind+'_revision',row[0],lock=lock)
        if value['master_id']!=master['id'] or any(value[k]!=master[k] for k in ('company','kind','code')):
            raise DomainError('controls_integrity','Cost revision lineage cannot be verified.',409)
        if value['definition']['effective_from']<=basis_date:return value
    return None


def resolve_revision(*,actor,company,kind,revision_id,basis_date,purpose,lock=False,resource_token=None,for_new=True):
    _purpose(purpose);core.business_date(basis_date,'basis_date')
    if kind not in {'code','type'}:core.fail('Choose code or type.','kind')
    require_company(company,ability='project.cost.read',actor=actor,lock=lock)
    discovery=repository.read(kind+'_revision',revision_id);_scope(discovery,company)
    plan=plan_resources(actor=actor,company=company,code_revision_ids=[revision_id] if kind=='code' else [],type_revision_ids=[revision_id] if kind=='type' else [],basis_date=basis_date,purpose=purpose)
    if lock:_admitted(plan,actor,company,resource_token)
    master=repository.read(kind,discovery['master_id'],lock=lock);_scope(master,company)
    value=repository.read(kind+'_revision',revision_id,lock=lock);_scope(value,company)
    if value!=discovery or value['master_id']!=master['id'] or value['code']!=master['code']:raise DomainError('controls_integrity','Cost revision lineage cannot be verified.',409)
    definition=core.definition(kind,value['definition'])
    if for_new:
        selected=effective_revision(kind,master,basis_date,lock=lock)
        if selected is None or selected['id']!=revision_id or not definition['enabled'] or definition['effective_until'] is not None and basis_date>definition['effective_until']:
            raise DomainError('stale_cost_revision','Select the effective enabled cost revision for the exact award date.',412)
    original_currency=value['authored_native'].get('account_currency')
    if original_currency:require_native('Currency',original_currency,actor,lock=lock)
    native=authorize_native(actor=actor,company=company,kind=kind,definition=definition,for_new=for_new,lock=lock,resource_token=resource_token)
    return {'kind':kind,'company':company,'basis_date':basis_date,'purpose':purpose,'revision':value,'revision_digest':digest(value),'native':native}

def _author(company,operation_id,kind,code_value,definition,master_id=None,expected_version=None):
    from cipher_aec.governance.commands import run_company_command
    from cipher_aec.estimating import scopes
    from cipher_aec.estimating.lockplan import prepared
    definition=core.definition(kind,definition)
    if master_id is None:core.code(code_value)
    else:
        core.identifier(master_id)
        from cipher_aec.api.contracts import expected_version as require_version
        expected_version=require_version(expected_version)
    payload={'kind':kind,'code':code_value,'definition':definition,'master_id':master_id,'expected_version':expected_version}
    def effect(actor, locked_company):
        require_company(company,ability='project.cost.read',actor=actor,lock=True)
        with scopes.activate('Company',company,None), authoring(actor, company):
            initial=repository.read(kind,master_id) if master_id else None
            if initial:_scope(initial,company)
            plan=_native_plan(definition['native_target'])
            if initial:
                prior=repository.read(kind+'_revision',initial['current_revision'])
                old=plan_resources(actor=actor,company=company,code_revision_ids=[prior['id']] if kind=='code' else [],type_revision_ids=[prior['id']] if kind=='type' else [],basis_date=prior['definition']['effective_from'],purpose='historical_read')
                plan['currencies']=sorted(set(plan['currencies']+old['currencies']));plan['native_refs']=sorted({(r['doctype'],r['name']):r for r in plan['native_refs']+old['native_refs']}.values(),key=lambda r:(r['doctype'],r['name']))
            with prepared(plan,actor,company) as token:
                if initial:
                    header=repository.read(kind,master_id,lock=True)
                    if digest(header)!=expected_version:raise DomainError('stale_cost_master','The cost master changed.',412)
                    prior=repository.read(kind+'_revision',header['current_revision'],lock=True)
                    resolve_revision(actor=actor,company=company,kind=kind,revision_id=prior['id'],basis_date=prior['definition']['effective_from'],purpose='historical_read',for_new=False,lock=True,resource_token=token)
                    if definition['effective_from']<=prior['definition']['effective_from']:core.fail('Successor effective dates must increase.','definition.effective_from')
                    if header['revision_number']>=200:core.fail('The bounded revision history is full.','revision')
                else:
                    existing=frappe.db.sql(f'SELECT name FROM `tab{repository.DOCTYPES[kind]}` WHERE company=%s AND code_key=%s FOR UPDATE',(company,code_value.casefold()))
                    if existing:raise DomainError('cost_code_exists','This Company already has that canonical code identity.',409)
                    header={'schema':'cipher.cost-master.v1','id':str(uuid4()),'company':company,'project':None,'kind':kind,'code':code_value,'author_person':actor.person_id,'current_revision':None,'revision_number':0}
                native=authorize_native(actor=actor,company=company,kind=kind,definition=definition,for_new=definition['enabled'],lock=True,resource_token=token)
                revision={'schema':'cipher.cost-revision.v1','id':str(uuid4()),'company':company,'project':None,'kind':kind,'master_id':header['id'],'code':header['code'],'author_person':actor.person_id,'revision_number':header['revision_number']+1,'predecessor':header['current_revision'],'definition':definition,'authored_native':native}
                if not initial:repository.write(kind,header)
                repository.write(kind+'_revision',revision)
                header={**header,'current_revision':revision['id'],'revision_number':revision['revision_number']};repository.write(kind,header,update=True)
                from cipher_aec.governance.history import append_company_event
                append_company_event(actor=actor,company=company,operation_id=operation_id,event='project.cost.revised' if initial else 'project.cost.created',subject_type=repository.DOCTYPES[kind+'_revision'],subject_id=revision['id'],details={'master_id':header['id'],'revision_digest':digest(revision)})
                return {'master':header,'revision':revision,'version':digest(header)}
    return run_company_command(company=company,operation_id=operation_id,command='project.cost.'+('revise' if master_id else 'create'),payload=payload,ability='project.cost.write',effect=effect)

def create_master(company,operation_id,kind,code,definition):return _author(company,operation_id,kind,code,definition)
def revise_master(company,operation_id,kind,master_id,expected_version,definition):return _author(company,operation_id,kind,None,definition,master_id,expected_version)
