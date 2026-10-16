"""Current authorized canonical master and adopted Project record readers."""
from copy import deepcopy
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import page_options,decode_cursor,signing_secret,page_result
from cipher_aec.governance.context import current_actor,require_company,require_project
from cipher_aec.commercial.native import require_native
from . import core,repository,masters


def get_revision(company,kind,revision_id,basis_date):
    return masters.resolve_revision(actor=current_actor(),company=company,kind=kind,revision_id=revision_id,basis_date=basis_date,purpose='historical_read',for_new=False)


def _page(load_rows,reader,*,actor,scope,limit,cursor,count_mode):
    from cipher_aec.governance.context import company_authority_fingerprint,authority_fingerprint
    limit,cursor,count_mode=page_options(limit,cursor,count_mode)
    fingerprint=authority_fingerprint(actor,scope['company'],scope['project']) if scope.get('project') else company_authority_fingerprint(actor,scope['company'])
    scope={**scope,'user':actor.user,'person':actor.person_id,'count_mode':count_mode,'authority':fingerprint}
    last=decode_cursor(cursor,secret=signing_secret(),scope=scope) if cursor else None
    rows=load_rows(last)
    # SQL owns datetime precision/name collation; complete visibility precedes
    # counts and page selection so hidden off-page rows disclose nothing.
    if len(rows)>500:raise DomainError('controls_collection_limit','This controls collection exceeds its bounded authorization scope.',409)
    selected,total=[],0
    for row in rows:
        try:value=reader(row.name)
        except DomainError as error:
            if error.status in (403,404):continue
            raise
        total+=1
        if len(selected)<=limit and (not last or row.after_cursor):selected.append((row,value))
    page=selected[:limit]
    return page_result([value for _,value in page],has_more=len(selected)>limit,last=[str(page[-1][0].creation),page[-1][0].name] if page else None,scope=scope,limit=limit,count_mode=count_mode,total=total if count_mode=='exact' else None)


def _rows(kind,company,project,last):
    fields,values='name,creation',[]
    if last:
        fields+=', (creation<%s OR (creation=%s AND name<%s)) AS after_cursor'
        values.extend((last[0],last[0],last[1]))
    where='company=%s AND '+('project=%s' if project is not None else '(project IS NULL OR LENGTH(project)=0)')
    values.append(company)
    if project is not None:values.append(project)
    return frappe.db.sql('SELECT '+fields+' FROM `tab'+repository.DOCTYPES[kind]+'` WHERE '+where+' ORDER BY creation DESC,name DESC LIMIT 501',tuple(values),as_dict=True)


def list_masters(company,kind,basis_date,limit=50,cursor=None,count_mode='none'):
    if kind not in {'code','type'}:core.fail('Choose code or type.','kind')
    core.business_date(basis_date,'basis_date');actor=current_actor();require_company(company,ability='project.cost.read',actor=actor)
    def read(name):
        master=repository.read(kind,name);masters._scope(master,company)
        # The header exposes current-head identity even when an earlier exact
        # revision governs this date. Authorize both before exposing either.
        head=masters.resolve_revision(actor=actor,company=company,kind=kind,revision_id=master['current_revision'],basis_date=basis_date,purpose='historical_read',for_new=False)
        selected=masters.effective_revision(kind,master,basis_date)
        if selected is None:raise DomainError('not_found','This cost master has no revision at this date.',404)
        revision=head if selected['id']==master['current_revision'] else masters.resolve_revision(actor=actor,company=company,kind=kind,revision_id=selected['id'],basis_date=basis_date,purpose='historical_read',for_new=False)
        return {'master':master,'revision':revision,'version':digest(master)}
    return _page(lambda last:_rows(kind,company,None,last),read,actor=actor,scope={'route':'project.cost.list','company':company,'kind':kind,'basis_date':basis_date},limit=limit,cursor=cursor,count_mode=count_mode)


def _budget_access(budget,actor):
    plan=budget['plan'];company=budget['company']
    currencies={plan['currency']}|{r['native']['account_currency'] for r in plan['resolved_types'] if r['native'].get('account_currency')}
    currencies.update(r['revision']['authored_native']['account_currency'] for r in plan['resolved_types'] if r['revision']['authored_native'].get('account_currency'))
    for currency in sorted(currencies):require_native('Currency',currency,actor)
    for unit in plan['source_units']:
        native=require_native('UOM',unit['target']['name'],actor)
        if native.get('cipher_unit_id')!=unit['id']:raise DomainError('controls_integrity','The adopted quantity unit identity cannot be verified.',409)
    for kind,key in (('code','resolved_codes'),('type','resolved_types')):
        for ref in plan[key]:
            native=require_native(ref['native']['doctype'],ref['native']['name'],actor)
            if native.company!=company:raise DomainError('not_found','This adopted native accounting target is not available.',404)
    # Original Company-source access is deliberately a separate boundary:
    # adopted Project facts carry Project authority without reopening sources.


def _authorize_project_record(kind,company,project,actor):
    require_project(company,project,ability='wbs.read' if kind=='wbs' else 'budget.read',actor=actor)
    if kind=='budget':require_project(company,project,ability='wbs.read',actor=actor)


def scoped(kind,record_id,company,project,actor):
    if kind not in {'wbs','budget','budget_line'}:core.fail('Choose a Project WBS or budget record.','kind')
    _authorize_project_record(kind,company,project,actor)
    value=repository.read(kind,record_id)
    if value['company']!=company or value['project']!=project:raise DomainError('not_found','This Project controls record is not available.',404)
    budget=value if kind=='budget' else repository.read('budget',value['budget_version'])
    if budget['company']!=company or budget['project']!=project or budget['controls_plan_digest']!=value['controls_plan_digest']:raise DomainError('controls_integrity','The adopted Project lineage cannot be verified.',409)
    if kind=='wbs' and value['node'] not in budget['plan']['wbs_nodes'] or kind=='budget_line' and value['line'] not in budget['plan']['budget_lines']:raise DomainError('controls_integrity','Adopted facts must match the immutable initial budget.',409)
    if kind!='wbs':_budget_access(budget,actor)
    return value


def get_record(company,project,kind,record_id):return scoped(kind,record_id,company,project,current_actor())


def list_records(company,project,kind,limit=50,cursor=None,count_mode='none'):
    if kind not in {'wbs','budget','budget_line'}:core.fail('Choose a Project WBS or budget record.','kind')
    actor=current_actor();_authorize_project_record(kind,company,project,actor)
    return _page(lambda last:_rows(kind,company,project,last),lambda name:scoped(kind,name,company,project,actor),actor=actor,scope={'route':'project.controls.list','company':company,'project':project,'kind':kind},limit=limit,cursor=cursor,count_mode=count_mode)


def authorize_receipt(actor,company,result):
    from cipher_aec.estimating import scopes
    from cipher_aec.estimating.lockplan import prepared
    require_company(company,ability='project.cost.read',actor=actor,lock=True)
    value=result['revision'];kind=value['kind'];revision_id=value['id']
    with scopes.activate('Company',company,None):
        plan=masters.plan_resources(actor=actor,company=company,code_revision_ids=[revision_id] if kind=='code' else [],type_revision_ids=[revision_id] if kind=='type' else [],basis_date=value['definition']['effective_from'],purpose='historical_read')
        with prepared(plan,actor,company) as token:
            authorized=masters.resolve_revision(actor=actor,company=company,kind=kind,revision_id=revision_id,basis_date=value['definition']['effective_from'],purpose='historical_read',for_new=False,lock=True,resource_token=token)
            if authorized['revision']!=value or result['master']['id']!=value['master_id']:raise DomainError('controls_integrity','The original cost receipt lost its exact lineage.',409)
