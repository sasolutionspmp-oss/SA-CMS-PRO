"""Opt-in R15 native refusals/probes. Import is inert; root owns execution.

No Docker/worker/migration/reload runner, new grant, login, class/global patch,
Session/User substitution, clock edit or old-journal mutation is provided.
"""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from threading import Thread
from threading import Barrier
import time
from types import MethodType
from uuid import uuid4

V2_SHA256='f47a94dd3e003984413c1c8bb87fce8ea40c7568853bd085eec1278e8bf49a8a'
KEY='execution_v3'
SCHEMA='cipher.fixture.ricky.company.boundaries.v3'
CASES={'cancel-before-finalization-r15':'aec.scope.draft','source-outage-r15':'aec.scope.draft',
    'native-write-outage-r15':'aec.scope.draft','duty-outage-r15':'aec.estimate.draft','stale-target-r15':'aec.scope.draft',
    'identity-refusal-r15':'aec.scope.draft','unsaved-expiry-r15':'aec.scope.draft','rollback-r15':'aec.scope.draft','two-operation-r15':'aec.scope.draft'}


def v2():
    p=Path(__file__).resolve().parent.parent/'native-execution-v2/r15_execution.py'
    if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=V2_SHA256:raise AssertionError('Keep the exact frozen v2 collaborator.')
    spec=importlib.util.spec_from_file_location('cipher_r15_frozen_v2',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def _value(path):
    two=v2();value=two._value(path);proof=two._proof(value).get(KEY)
    if not proof or proof.get('schema')!=SCHEMA or set(proof['cases'])!=set(CASES):raise ValueError('Declare the separate v3 boundary evidence first.')
    if two.v1()._file(proof['baseline']['path'])!=proof['baseline']:raise AssertionError('The v3 baseline changed.')
    for row in proof['cases'].values():
        references=[row[key] for key in ('review_before_ref','race_evidence') if key in row]
        references.extend(item['evidence'] for item in row.get('refusals',[]))
        if 'rollback' in row:references.append(row['rollback']['evidence'])
        for reference in references:
            target=Path(reference['path'])
            if ({**two.v1()._file(target),'bytes':target.stat().st_size}!=reference
                    or target.parent.resolve()!=(Path(path).parent/'r15-v3-evidence').resolve()):raise AssertionError('A one-shot v3 evidence reference changed.')
    return value


def _proof(value):return v2()._proof(value)[KEY]


def _case(path,case,**fields):
    two=v2();value=_value(path)
    if case not in CASES:raise ValueError('Use one distinct v3 case; never repurpose an older UUID.')
    _proof(value)['cases'][case].update(deepcopy(fields))
    # Original ten-case declaration stays exact; the additional unsaved-expiry
    # case belongs only to this v3 declaration.
    if case in two.v1().CASES:value['stages'][two.v1().KEY]['cases'][case]=deepcopy(_proof(value)['cases'][case])
    two._support()[0].write_private(path,value);return value


def _evidence(path,case,label,value):
    """One-shot private sidecar; never embed another native inventory."""
    if case not in {*CASES,'baseline'} or label not in {'baseline','review-before','rollback','race-batch','final-audit',
            'refusal-author','refusal-alias','refusal-outsider'}:raise ValueError('Use only literal v3 evidence slots.')
    directory=Path(path).parent/'r15-v3-evidence'
    if directory.is_symlink():raise ValueError('Evidence directory aliases are refused.')
    directory.mkdir(mode=0o700,exist_ok=True)
    if directory.stat().st_mode&0o077:raise ValueError('Keep the v3 evidence directory private.')
    target=directory/(case+'-'+label+'.secret.json')
    data=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    descriptor=os.open(directory,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return {'path':str(target.resolve()),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}


def _fingerprint(state):
    two=v2()
    return {'at':state.get('at'),'collections':{key:{'sha256':two.sha(state[key]),'entries':len(state[key])}
        for key in ('records','receipts','history','applications','quotations')},'inventory_sha256':two.sha(state['inventory']),
        'source_sha256':two.sha(state['source']),'config_sha256':two.sha(state['config']),
        'indexes_sha256':two.sha(state['indexes']),'company_head':state['company_head']}


def declare(path):
    two=v2();value=two._value(path)
    if KEY in two._proof(value):raise RuntimeError('Never reset an entered boundary declaration.')
    if two._proof(value)['status']!='two-positive-cases-audited':raise RuntimeError('Finish and preserve the separately audited positive cases first.')
    state=two.observe_native(path)
    if state['active_runs']:raise AssertionError('Require no active Company/Project Run before v3.')
    reference=_evidence(path,'baseline','baseline',state)
    two._proof(value)[KEY]={'schema':SCHEMA,'status':'declared','baseline':{key:reference[key] for key in ('path','sha256')},'baseline_bytes':reference['bytes'],
        'cases':{case:{'status':'declared','action':action,'ids':two.authored_ids()} for case,action in CASES.items()},'restorations':[]}
    two._support()[0].write_private(path,value)
    return {'status':'declared','cases':list(CASES)}


def _request(value,case):
    two=v2();row=_proof(value)['cases'][case];shadow=deepcopy(value)
    two._proof(shadow)['targets']=deepcopy(row['targets']);two._proof(shadow)['ids']=deepcopy(row['ids'])
    # The extra unsaved-expiry case uses the same closed scope action codec,
    # with its own fresh target/intent/Run identity.
    return two.exact_request(shadow,'scope-r15' if case=='unsaved-expiry-r15' else case)


def create_target(path,case,base_url,host_header):
    two=v2();old=two.v1();value=_value(path);row=_proof(value)['cases'][case]
    if row['status']!='declared' or row.get('targets'):raise RuntimeError('Each boundary owns one fresh target phase; no automatic retry.')
    if two.observe_native(path)['active_runs']:raise AssertionError('Finish the earlier active case first.')
    plan=two._support()[0].load_private(value['stages'][old.KEY]['prerequisite']['path'])['plan'];targets={}
    _case(path,case,status='target-attempted')
    try:
        rpc=two.client(path,base_url,host_header)
        if CASES[case]=='aec.scope.draft':
            targets['commercial']=two._data(rpc.call(old.COMMERCIAL+'create_proposal',{'company':value['company'],
                'pursuit_id':value['inputs']['pursuit']['id'],'composition':two.target_composition(value,row['ids'],plan)},key='v3-target-'+case))
        else:
            estimate=two._data(rpc.call(old.EST+'create_estimate',{'company':value['company'],'title':'R15 fresh '+case,'currency':'USD',
                'pricing_date':plan['pricing_date'],'pursuit_id':value['inputs']['pursuit']['id']},key='v3-estimate-'+case))['estimate']
            targets['estimate']={'estimate':estimate};_case(path,case,targets=targets)
            targets['estimate']=two._data(rpc.call(old.EST+'calculate_revision',{'company':value['company'],
                **two.target_estimate_fields(value,row['ids'],estimate['id'])},key='v3-base-'+case))
        positive=two._proof(value)['targets']
        for domain,data in targets.items():
            key='proposal' if domain=='commercial' else 'estimate'
            forbidden={positive[domain][key]['id'],value['inputs'].get(key,{}).get('id')}
            for other in _proof(value)['cases'].values():
                if domain in other.get('targets',{}):forbidden.add(other['targets'][domain][key]['id'])
            if data[key]['id'] in forbidden:raise AssertionError('Never adopt a positive/R14/other-case business head.')
        _case(path,case,status='target-ready',targets=targets)
        return {'status':'target-ready','case':case}
    except BaseException as failure:
        _case(path,case,status='target-failed',targets=targets,error={'type':type(failure).__name__});raise


def start(path,case,base_url,host_header):
    two=v2();old=two.v1();value=_value(path);row=_proof(value)['cases'][case]
    if row['status']!='target-ready' or two.observe_native(path)['active_runs']:raise RuntimeError('Use this unused fresh target after all older active Runs finish.')
    request=_request(value,case);_case(path,case,status='start-attempted',request=request)
    response=two._data(two.client(path,base_url,host_header).call(old.PROPOSAL+'start_proposal',{'company':value['company'],'request':request},key='v3-start-'+case))
    actual=two._run(path,response['id'])
    if response['status']!='queued' or response['operation']['replayed'] or actual['run']['request']!=request:
        raise AssertionError('Require the exact fresh authentic queued boundary Run.')
    _case(path,case,status='queued',run_id=response['id'],operation_id=response['operation']['id'],start=response,admitted=actual)
    return {'status':'queued','case':case,'run_id':response['id']}


def record_preparation(path,case,before_queue,after_queue):
    two=v2();value=_value(path);row=_proof(value)['cases'][case]
    proof=two.verify_queue_evidence(before_queue,after_queue,site=value['site'],queue='cipher-ai04-stage-a-20261016:short',run_id=row['run_id'])
    actual=two._run(path,row['run_id']);run=actual['run'];children=actual['children']
    if case=='cancel-before-finalization-r15':
        if (row['status']!='cancelled-before-rq' or run['status']!='cancelled' or run['proposal_ids'] or children['proposal'] or children['invocation']):
            raise AssertionError('The ordinary cancelled job must leave no successful preparation or suggestion.')
        _case(path,case,status='passed',queue_evidence=proof,queue_before=before_queue,queue_after=after_queue,terminal=actual);return {'status':'passed','case':case}
    if (row['status']!='queued' or run['status']!='waiting-for-review' or run['cancel_requested'] or len(run['proposal_ids'])!=1
            or len(children['proposal'])!=1 or len(children['invocation'])!=1 or children['invocation'][0]['status']!='succeeded'):
        raise AssertionError('Require one ordinary successful terminal suggestion for this distinct case.')
    _case(path,case,status='prepared',proposal_id=run['proposal_ids'][0],terminal=actual,queue_evidence=proof,queue_before=before_queue,queue_after=after_queue)
    return {'status':'prepared','case':case}


def observe_queue(path,case,*,completed_ids=()):
    from frappe.utils.background_jobs import get_queue,get_redis_conn
    from rq import Worker
    from rq.job import Job
    from rq.registry import StartedJobRegistry
    value=_value(path);row=_proof(value)['cases'][case];queue=get_queue('short');connection=get_redis_conn()
    def item(job):
        fields=job.kwargs
        return {'id':job.id,'run_id':fields.get('kwargs',{}).get('run_id'),'site':fields.get('site'),'queue':queue.name,
            'func_name':job.func_name,'method':fields.get('method'),'kwargs':deepcopy(fields.get('kwargs')),'status':str(job.get_status()),
            'worker_name':job.worker_name,'started_at':job.started_at.isoformat() if job.started_at else None,'ended_at':job.ended_at.isoformat() if job.ended_at else None}
    return {'site':value['site'],'run_id':row['run_id'],'queue':queue.name,'workers':[worker.name for worker in Worker.all(connection=connection)],
        'started_jobs':StartedJobRegistry(queue=queue).get_job_ids(cleanup=False),'jobs':[item(job) for job in queue.get_jobs()],
        'completed':[item(Job.fetch(name,connection=connection)) for name in completed_ids],'at':v2().stamp()}


def review(path,case,base_url,host_header):
    two=v2();old=two.v1();value=_value(path);row=_proof(value)['cases'][case]
    if row['status']!='prepared':raise RuntimeError('Require independently observed ordinary RQ completion first.')
    subject=two._data(two.client(path,base_url,host_header).call(old.SAVE+'draft_save_subject',{'company':value['company'],'proposal_id':row['proposal_id']}))
    if subject['eligible'] is not True or subject['application'] is not None or subject['payload_digest']!=two.sha(subject['payload']):raise AssertionError('Require this exact fresh eligible review before refusal.')
    reviewed={'proposal_id':subject['proposal_id'],'expected_version':subject['proposal_version'],'expected_content_digest':subject['proposal_digest'],
        'mapping_version':'1','expected_payload_digest':subject['payload_digest']}
    reference=_evidence(path,case,'review-before',_fingerprint(two.observe_native(path)))
    _case(path,case,status='reviewed',review=subject,reviewed=reviewed,review_before_ref=reference)
    return subject


def cancel_before_rq(path,base_url,host_header):
    two=v2();old=two.v1();case='cancel-before-finalization-r15';value=_value(path);row=_proof(value)['cases'][case]
    if row['status']!='queued' or any(two._run(path,row['run_id'])['children'][kind] for kind in ('step','invocation','proposal')):
        raise RuntimeError('Cancel this authentic queued Run before any ordinary RQ preparation.')
    result=two._data(two.client(path,base_url,host_header).call(old.PROPOSAL+'cancel_run',{'company':value['company'],'run_id':row['run_id']},key='v3-cancel-'+case))
    if result['status']!='cancelled' or result['cancel_requested'] is not True or result['operation']['replayed']:raise AssertionError('Require first ordinary pre-RQ cancellation.')
    _case(path,case,status='cancelled-before-rq',cancel=result)
    return {'status':'cancelled-before-rq','case':case,'root_next':'Consume only the original queued job with ordinary RQ; record cancellation evidence.'}


def _no_effect(before,after):
    for key in ('records','receipts','history','applications','quotations','company_head','source','indexes','config'):
        if before[key]!=after[key]:raise AssertionError('Refused/probed save changed actual native state: '+key)


def refused_save(path,case,base_url,host_header,*,role='author',codes,require_expired=False,key=None):
    two=v2();old=two.v1();value=_value(path);row=_proof(value)['cases'][case]
    if row['status']!='reviewed':raise RuntimeError('Retain the original reviewed case; no reused failed UUID.')
    if require_expired and datetime.now(timezone.utc)<datetime.fromisoformat(row['review']['expires_at']):raise RuntimeError('Wait for natural unsaved expiry; never edit clocks/deadlines.')
    before=two.observe_native(path);terminal=two._run(path,row['run_id'])
    response=two.client(path,base_url,host_header,role=role).call(old.SAVE+'save_draft',{'company':value['company'],**row['reviewed']},key=key or 'v3-refuse-'+case)
    code=response['envelope'].get('error',{}).get('code')
    if response['status']<400 or code not in codes:raise AssertionError('The actual native/HTTP refusal differs from the separately declared expectation.')
    after=two.observe_native(path);_no_effect(before,after)
    if two._run(path,row['run_id'])['payloads']!=terminal['payloads']:raise AssertionError('Refusal changed immutable terminal/preparation bytes.')
    reference=_evidence(path,case,'refusal-'+role,{'before':_fingerprint(before),'after':_fingerprint(after),'response':response,'terminal_payload_sha256':two.sha(terminal['payloads'])})
    _case(path,case,refusals=[*_proof(_value(path))['cases'][case].get('refusals',[]),{'role':role,'response':response,'evidence':reference,'expired':require_expired}])
    return response


def _row(table,name):
    import frappe
    two=v2();support,native,_,continuation=two._support()
    if table not in {'Cipher Project Duty','Custom DocPerm'}:raise ValueError('Only exact existing outage records are readable here.')
    def read(frappe):
        rows=frappe.db.sql('SELECT * FROM `tab'+table+'` WHERE name=%s',(name,),as_dict=True)
        if len(rows)!=1:raise AssertionError('The exact existing outage row is unavailable.')
        return {'name':name,'table':table,'values':{key:native._native_scalar(item) for key,item in rows[0].items()},
            'columns':{key:support.sha(native._native_scalar(item)) for key,item in rows[0].items()}}
    return continuation._independent(read)


def restoration(before,after):
    if before['table']!=after['table'] or before['name']!=after['name'] or set(before['columns'])!=set(after['columns']):raise AssertionError('Outage restoration row identity/columns changed.')
    for row in (before,after):
        if set(row['values'])!=set(row['columns']) or any(v2().sha(item)!=row['columns'][key] for key,item in row['values'].items()):raise AssertionError('Typed restoration values differ from exact column hashes.')
    fields={key for key in before['columns'] if before['columns'][key]!=after['columns'][key]}
    if fields-{'modified','modified_by'}:raise AssertionError('Supported restoration did not preserve exact original semantic columns.')
    return {'table':before['table'],'name':before['name'],'before':before,'after':after,'changed_audit_columns':sorted(fields),'semantic_restored':True}


@contextmanager
def duty_outage(path,case,ability):
    """Exact current fixture duty, supported save and mandatory restoration."""
    import frappe
    from cipher_aec.governance.context import trusted_write
    two=v2();value=_value(path)
    allowed={'source-outage-r15':'document.read','duty-outage-r15':'estimate.write'}
    if allowed.get(case)!=ability or _proof(value)['cases'][case]['status']!='reviewed':raise ValueError('Use only this exact declared duty outage after review.')
    name=value['duties'][ability];before=_row('Cipher Project Duty',name)
    expected={'company':value['company'],'person':value['users']['author']['person'],'scope_type':'Company','project':None,'ability':ability,'active':1}
    doc=frappe.get_doc('Cipher Project Duty',name)
    if any(doc.get(key)!=item for key,item in expected.items()):raise AssertionError('Existing original active Company duty binding changed.')
    _case(path,case,outage_before=before)
    try:
        with trusted_write():doc.active=0;doc.save(ignore_permissions=True)
        frappe.db.commit()
        if _row('Cipher Project Duty',name)['values']['active']!={'type':'int','value':'0'}:raise AssertionError('Independent observer did not see the outage.')
        yield
    finally:
        observed=_row('Cipher Project Duty',name)
        if set(observed['columns'])!=set(before['columns']) or any(observed['columns'][key]!=before['columns'][key] for key in before['columns'] if key not in {'active','modified','modified_by'}):
            raise AssertionError('Refuse restoration across unrelated duty drift; retain the outage for explicit reconciliation.')
        current=frappe.get_doc('Cipher Project Duty',name)
        with trusted_write():current.active=1;current.save(ignore_permissions=True)
        frappe.db.commit();proof=restoration(before,_row('Cipher Project Duty',name))
        _case(path,case,restoration=proof)


@contextmanager
def native_write_outage(path):
    """Disable only an existing exact Quotation write flag; never add grants."""
    import frappe
    two=v2();case='native-write-outage-r15';value=_value(path);role=value['native']['role']
    if _proof(value)['cases'][case]['status']!='reviewed':raise RuntimeError('Review this fresh case before changing the native flag.')
    names=frappe.get_all('Custom DocPerm',filters={'parent':'Quotation','role':role,'permlevel':0,'if_owner':0},pluck='name')
    if len(names)!=1:raise AssertionError('Require one existing exact fixture-role Quotation Custom DocPerm.')
    name=names[0];before=_row('Custom DocPerm',name);doc=frappe.get_doc('Custom DocPerm',name)
    if doc.write!=1 or doc.read!=1:raise AssertionError('Meaningful native-write outage requires current write/read permissions.')
    _case(path,case,outage_before=before)
    try:
        doc.write=0;doc.save(ignore_permissions=True);frappe.clear_cache(doctype='Quotation');frappe.db.commit()
        if _effective_quotation_write(value):raise AssertionError('Another native write grant still authorizes this actor.')
        yield
    finally:
        observed=_row('Custom DocPerm',name)
        if set(observed['columns'])!=set(before['columns']) or any(observed['columns'][key]!=before['columns'][key] for key in before['columns'] if key not in {'write','modified','modified_by'}):
            raise AssertionError('Refuse restoration across unrelated native permission drift; retain the outage for explicit reconciliation.')
        current=frappe.get_doc('Custom DocPerm',name);current.write=1;current.save(ignore_permissions=True)
        frappe.clear_cache(doctype='Quotation');frappe.db.commit();proof=restoration(before,_row('Custom DocPerm',name))
        if not _effective_quotation_write(value):raise AssertionError('Exact native write restoration was not independently effective.')
        _case(path,case,restoration=proof)


def _effective_quotation_write(value):
    return v2()._support()[3]._independent(lambda frappe:bool(frappe.has_permission('Quotation',ptype='write',user=value['users']['author']['user'])))


def run_outage(path,case,base_url,host_header):
    if case=='source-outage-r15':
        with duty_outage(path,case,'document.read'):response=refused_save(path,case,base_url,host_header,codes={'capability_denied','not_found'})
    elif case=='duty-outage-r15':
        with duty_outage(path,case,'estimate.write'):response=refused_save(path,case,base_url,host_header,codes={'capability_denied'})
    elif case=='native-write-outage-r15':
        with native_write_outage(path):response=refused_save(path,case,base_url,host_header,codes={'native_permission_denied'})
    else:raise ValueError('Use one of the three declared supported outages.')
    _case(path,case,status='passed');return {'status':'passed','case':case,'code':response['envelope']['error']['code']}


def run_identity_refusals(path,base_url,host_header):
    case='identity-refusal-r15'
    for role in ('alias','outsider'):
        refused_save(path,case,base_url,host_header,role=role,codes={'not_found','capability_denied'},key='v3-'+role+'-'+case)
    _case(path,case,status='passed');return {'status':'passed','case':case,'identities':['alias','outsider']}


def run_unsaved_expiry(path,base_url,host_header):
    case='unsaved-expiry-r15'
    response=refused_save(path,case,base_url,host_header,codes={'draft_save_expired'},require_expired=True)
    _case(path,case,status='passed');return {'status':'passed','case':case,'code':response['envelope']['error']['code']}


def run_stale_target(path,base_url,host_header):
    two=v2();old=two.v1();case='stale-target-r15';value=_value(path);row=_proof(value)['cases'][case]
    if row['status']!='reviewed' or row.get('successor_attempted'):raise RuntimeError('Use one separately declared manual successor before this unsaved attempt.')
    original=row['targets']['commercial'];composition=deepcopy(original['revision']['composition'])
    composition['sections'].append({'id':str(uuid4()),'kind':'scope','title':'R15 stale-case human successor','text':'Separate current working head.'})
    _case(path,case,successor_attempted=True)
    result=two._data(two.client(path,base_url,host_header).call(old.COMMERCIAL+'save_proposal_revision',{'company':value['company'],
        'proposal_id':original['proposal']['id'],'expected_revision':original['proposal']['revision_number'],
        'expected_native_fingerprint':original['revision']['native_fingerprint'],'composition':composition},key='v3-stale-successor'))
    _case(path,case,successor=result)
    refused_save(path,case,base_url,host_header,codes={'stale_source','stale_commercial','stale_native_source'})
    _case(path,case,status='passed');return {'status':'passed','case':case}


class RollbackProbe(RuntimeError):pass


@contextmanager
def instance_persist_probe(context,observe):
    """One concrete instance only; real persist finishes before forced failure."""
    from cipher_aec.ricky.company_draft_save import DraftSaveContext
    if type(context) is not DraftSaveContext:raise TypeError('Require the concrete actual canonical save context.')
    inherited='persist' not in context.__dict__;original=context.persist;previous=context.__dict__.get('persist')
    def fail(self,actor,result):
        original(actor,result);observe(result);raise RollbackProbe('R15 explicit instance-only failure after real receipt/application/history insertion.')
    context.persist=MethodType(fail,context)
    try:yield
    finally:
        if inherited:del context.persist
        else:context.persist=previous
        if context.persist!=original:raise AssertionError('The exact instance method was not restored.')


def rollback_current_request(path):
    """Root must invoke inside an already genuine original authenticated request.

    No User/SID/request is constructed or replaced here. A bench Administrator
    context is refused. Root owns any separately source-reviewed native entry.
    """
    import frappe
    from cipher_aec.ricky.company_draft_save import DraftSaveContext
    from cipher_aec.governance.context import current_actor
    two=v2();case='rollback-r15';value=_value(path);row=_proof(value)['cases'][case];actor=current_actor()
    sid=getattr(frappe.session,'sid',None);authority=row['terminal']['run']['authority']
    if (not getattr(frappe.local,'request',None) or actor.user!=value['users']['author']['user'] or actor.person_id!=value['users']['author']['person']
            or not sid or sid=='Guest' or hashlib.sha256(sid.encode()).hexdigest()!=authority['session_reference']):
        raise RuntimeError('Use the actual original authenticated request context; never substitute an identity or Session.')
    if row['status']!='reviewed':raise RuntimeError('Require this distinct fresh reviewed rollback case.')
    support=two._support()[0];journal=support.Journal(value['journal_directory'])
    intent=journal.prepare('v3-instance-rollback','author',two.v1().SAVE+'save_draft',{'company':value['company'],**row['reviewed']})
    if intent['attempts'] or intent.get('uncertain_transport'):raise RuntimeError('Retain/reconcile the original native-probe UUID; never retry it implicitly.')
    before=two.observe_native(path);local_before=_local_effect_rows();context=DraftSaveContext(value['company'],row['proposal_id'],row['reviewed']).prepare();observations=[]
    def observe(result):observations.append({'receipt_id':result['application']['receipt_id'],'application_id':result['application']['id'],'result_digest':two.sha(result)})
    try:
        with instance_persist_probe(context,observe):
            if context.spec[2]=='commercial':
                from cipher_aec.commercial.service import save_proposal_revision
                save_proposal_revision(company=value['company'],operation_id=intent['operation_id'],**context.payload,_draft_save=context)
            else:
                from cipher_aec.estimating.company_service import calculate_revision
                calculate_revision(company=value['company'],operation_id=intent['operation_id'],**context.payload,_draft_save=context)
    except RollbackProbe:
        after=two.observe_native(path);_no_effect(before,after)
        if _local_effect_rows()!=local_before:raise AssertionError('The owning transaction still contains a partial canonical effect after savepoint rollback.')
        if len(observations)!=1:raise AssertionError('The real canonical persist boundary was not reached exactly once.')
        intent['attempts'].append({'status':'rolled_back','channel':'authenticated-native-instance-probe','observations':observations,'at':two.stamp()})
        reference=_evidence(path,case,'rollback',{'before':_fingerprint(before),'after':_fingerprint(after),'observations':observations,'owner_transaction_rows_sha256':two.sha(local_before)})
        support.write_private(journal.path,journal.rows);_case(path,case,status='passed',rollback={'evidence':reference,'observations':observations})
        return {'status':'passed','case':case,'hook_restored':True,'canonical_effect_rolled_back':True}
    else:raise AssertionError('The scoped probe did not force rollback after real persistence.')


def _local_effect_rows():
    """Current owning connection, separately from the committed observer."""
    import frappe
    two=v2();support,native,_,_=two._support();result={}
    for table in ('Cipher Proposal','Cipher Proposal Revision','Quotation','Quotation Item','Cipher Estimate','Cipher Estimate Revision',
            'Cipher Calculation Snapshot','Cipher Estimate Line','Cipher Command Receipt','Cipher Ricky Draft Save','Cipher History Event'):
        result[table]={row['name']:{key:support.sha(native._native_scalar(item)) for key,item in row.items()}
            for row in frappe.db.sql('SELECT * FROM `tab'+table+'` ORDER BY name',as_dict=True)}
    return result


def verify_race(entries):
    """Exactly two overlapping authentic attempts, one first-effect winner."""
    two=v2()
    if len(entries)!=2 or len({row['operation_id'] for row in entries})!=2:raise AssertionError('Keep both original distinct operation UUIDs.')
    if any(row.get('error') or row.get('truncated') for row in entries):raise AssertionError('Preserve uncertain race outcomes; never infer a winner.')
    starts=[datetime.fromisoformat(row['started_at']) for row in entries];ends=[datetime.fromisoformat(row['completed_at']) for row in entries]
    if any(start>end for start,end in zip(starts,ends)) or max(starts)>=min(ends):raise AssertionError('Actual bounded wire intervals did not overlap.')
    payloads=[{key:item for key,item in row['payload'].items() if key!='operation_id'} for row in entries]
    if payloads[0]!=payloads[1] or any(row['payload']['operation_id']!=row['operation_id'] for row in entries):raise AssertionError('Competing operations must bind one exact reviewed payload.')
    winners=[row for row in entries if row['status']==200];losers=[row for row in entries if row['status']==409]
    if len(winners)!=1 or len(losers)!=1 or losers[0]['envelope'].get('error',{}).get('code')!='draft_already_saved':
        raise AssertionError('Normal Company locking must produce one save and one immutable-application refusal.')
    operation=winners[0]['envelope']['data']['operation']
    if operation!={'id':winners[0]['operation_id'],'status':'succeeded','replayed':False}:raise AssertionError('Require a first-effect original UUID winner.')
    return {'winner':winners[0]['operation_id'],'loser':losers[0]['operation_id'],'started_at':min(starts).isoformat(),'completed_at':max(ends).isoformat()}


def _race_wire(rpc,intent,barrier):
    """No file/journal writes in worker threads; root invokes this explicitly."""
    from urllib.request import Request
    from urllib.error import HTTPError
    two=v2();method=two.v1().SAVE+'save_draft';path='/api/method/'+method
    payload=deepcopy(intent['payload']);body=json.dumps(payload,allow_nan=False).encode()
    headers={'Accept':'application/json','Content-Type':'application/json','X-Frappe-CSRF-Token':rpc.csrf,'Idempotency-Key':intent['operation_id']}
    if rpc.host:headers['Host']=rpc.host
    request=Request(rpc.origin+path,data=body,headers=headers,method='POST')
    entry={'operation_id':intent['operation_id'],'payload':payload,'role':'author','method':'POST','path':path,'request_sha256':hashlib.sha256(body).hexdigest()}
    barrier.wait(timeout=5);entry['started_at']=two.stamp()
    try:
        try:response=rpc.opener.open(request,timeout=30)
        except HTTPError as response:
            with response:status,raw=response.code,response.read(2097153)
        else:
            with response:status,raw=response.status,response.read(2097153)
        entry.update(status=status,observed_bytes=len(raw),body_sha256=hashlib.sha256(raw).hexdigest(),truncated=len(raw)>2097152)
        if entry['truncated'] or 300<=status<400:raise AssertionError('Bounded race wire refuses redirects and oversized responses.')
        payload_response=json.loads(raw);operation=rpc.openapi['paths'][path]['post']
        from jsonschema import Draft202012Validator,FormatChecker
        schema=operation['responses'][str(status)]['content']['application/json']['schema']
        Draft202012Validator({'components':rpc.openapi['components'],**schema},format_checker=FormatChecker()).validate(payload_response)
        entry['envelope']=payload_response['message']
    except BaseException as failure:entry['error']={'type':type(failure).__name__}
    finally:entry['completed_at']=two.stamp()
    return entry


def two_operation_posts(path,base_url,host_header):
    """Serial fsynced intents, two bounded wires, serial evidence persistence."""
    two=v2();old=two.v1();case='two-operation-r15';value=_value(path);row=_proof(value)['cases'][case]
    if row['status']!='reviewed' or row.get('race_entered'):raise RuntimeError('Use one explicit competition; preserve all attempted UUIDs.')
    support,_,_,continuation=two._support();journal=support.Journal(value['journal_directory'])
    fields={'company':value['company'],**row['reviewed']}
    intents=[journal.prepare('v3-compete-'+str(index),'author',old.SAVE+'save_draft',fields) for index in range(2)]
    if any(intent['attempts'] or intent.get('uncertain_transport') for intent in intents):raise RuntimeError('Both original UUIDs must be unused; no automatic retries.')
    _case(path,case,race_entered=True,race_intents=[deepcopy(intent) for intent in intents])
    clients=[two.client(path,base_url,host_header) for _ in range(2)] # authentic sequential session GETs
    from jsonschema import Draft202012Validator,FormatChecker
    for rpc,intent in zip(clients,intents):
        operation=rpc.openapi['paths']['/api/method/'+old.SAVE+'save_draft']['post']
        Draft202012Validator({'components':rpc.openapi['components'],**operation['requestBody']['content']['application/json']['schema']},format_checker=FormatChecker()).validate(intent['payload'])
    before_users=two._observe_users(_value(path));before_sessions=two._observe_sessions(_value(path))
    last=two._proof(_value(path))['wires'][-1]
    if before_users['users']!=last['after']['users'] or before_sessions!=last['sessions_after']:raise AssertionError('The exact pre-batch auth chain changed.')
    barrier=Barrier(2);outputs=[None,None];threads=[];batch_start=two.stamp()
    def send(index):
        try:outputs[index]=_race_wire(clients[index],intents[index],barrier)
        except BaseException as failure:outputs[index]={'operation_id':intents[index]['operation_id'],'error':{'type':type(failure).__name__}}
    for index in range(2):
        thread=Thread(target=send,args=(index,),daemon=True);threads.append(thread);thread.start()
    deadline=time.monotonic()+45
    for thread in threads:thread.join(max(0,deadline-time.monotonic()))
    batch_end=two.stamp();alive=[thread.is_alive() for thread in threads]
    entry={'batch':case,'role':'author','method':'POST batch','path':'/api/method/'+old.SAVE+'save_draft','before':before_users,
        'sessions_before':before_sessions,'started_at':batch_start,'completed_at':batch_end,'entries':deepcopy(outputs),'threads_alive':alive}
    try:entry['after']=two._observe_users(_value(path));entry['sessions_after']=two._observe_sessions(_value(path))
    except BaseException as failure:entry['observer_error']={'type':type(failure).__name__}
    # Persist batch and each response serially before any success assertion.
    current=_value(path);two._proof(current)['wires'].append(entry);support.write_private(path,current)
    for intent,output in zip(intents,outputs):
        if output and 'envelope' in output:journal.response(intent,status=output['status'],envelope=output['envelope'])
        else:journal.uncertain(intent,RuntimeError('Bounded competition outcome uncertain.'),output)
    if any(alive) or any(output is None for output in outputs) or entry.get('observer_error'):
        raise AssertionError('Preserve the uncertain batch; do not retry or reset a thread/UUID.')
    result=verify_race(outputs)
    entry.update(dispatch_started_at=batch_start,dispatch_completed_at=batch_end,started_at=result['started_at'],completed_at=result['completed_at'])
    entry['changes']=continuation.user_transition(before_users['users'],entry['after']['users'],value['users'],'author',entry['started_at'],entry['completed_at'])
    entry['session_changes']=two.session_transition(before_sessions,entry['sessions_after'],'author',entry['started_at'],entry['completed_at'])
    entry.update(status='verified-batch',outcome=result)
    current=_value(path);two._proof(current)['wires'][-1]=entry;support.write_private(path,current)
    winner=next(output for output in outputs if output['operation_id']==result['winner'])['envelope']['data']
    reference=_evidence(path,case,'race-batch',entry)
    _case(path,case,status='saved',saved=winner,race=result,race_evidence=reference)
    state=two.observe_native(path);two.verify_saved_state(_value(path),case,state)
    if two._run(path,row['run_id'])['payloads']!=row['terminal']['payloads']:raise AssertionError('Competing saves rewrote original terminal/preparation bytes.')
    _case(path,case,status='passed',race_state_sha256=two.sha(state))
    return {'status':'passed','case':case,**result}


def _batch_ledger(value):
    """Validate one concrete overlap batch before using its aggregate heartbeat."""
    two=v2();shadow=deepcopy(value);batches=[wire for wire in two._proof(shadow)['wires'] if 'batch' in wire]
    if len(batches)!=1:raise AssertionError('Require exactly the single separately declared overlap batch.')
    batch=batches[0];case=_proof(value)['cases']['two-operation-r15']
    if batch.get('status')!='verified-batch' or batch['batch']!='two-operation-r15' or len(batch['threads_alive'])!=2 or any(batch['threads_alive']):raise AssertionError('Incomplete overlap batch cannot excuse auth drift.')
    expected={intent['operation_id'] for intent in case['race_intents']}
    if {entry['operation_id'] for entry in batch['entries']}!=expected or verify_race(batch['entries'])!=case['race'] or batch['outcome']!=case['race']:
        raise AssertionError('Overlap attribution differs from the exact two fsynced intents/outcomes.')
    for intent in case['race_intents']:
        actual=next(entry for entry in batch['entries'] if entry['operation_id']==intent['operation_id'])
        if actual['payload']!=intent['payload']:raise AssertionError('A batch wire changed its exact original fsynced payload.')
    if any(batch[key]!=case['race'][key] for key in ('started_at','completed_at')):raise AssertionError('Batch heartbeat bounds must be the actual overlapping wire union.')
    batch['status']='verified' # private verifier view; retained ledger stays explicitly a batch
    return shadow


def restored_inventory(value,before,after):
    """Only the three literal existing outage rows receive audit attribution."""
    two=v2();adjusted=deepcopy(after);restored=[]
    for case,row in _proof(value)['cases'].items():
        if 'restoration' not in row:continue
        note=row['restoration'];check=restoration(note['before'],note['after'])
        if case in {'source-outage-r15','duty-outage-r15'}:
            ability='document.read' if case=='source-outage-r15' else 'estimate.write'
            if note['table']!='Cipher Project Duty' or note['name']!=value['duties'][ability]:raise AssertionError('Only the exact existing declared Company duty may receive restoration attribution.')
        elif case=='native-write-outage-r15':
            values=note['before']['values']
            expected={'parent':{'type':'str','value':'Quotation'},'role':{'type':'str','value':value['native']['role']},
                'permlevel':{'type':'int','value':'0'},'if_owner':{'type':'int','value':'0'},'write':{'type':'int','value':'1'},'read':{'type':'int','value':'1'}}
            if note['table']!='Custom DocPerm' or any(values.get(key)!=item for key,item in expected.items()):raise AssertionError('Only the existing exact fixture-role Quotation write permission row may receive restoration attribution.')
        else:raise AssertionError('No arbitrary case or old row may introduce a restoration exception.')
        if note!=check or after['inventory'][note['table']].get(note['name'])!=note['after']['columns']:
            raise AssertionError('Actual final supported restoration differs from its independent exact typed readback.')
        if before['inventory'][note['table']].get(note['name'])!=note['before']['columns']:
            raise AssertionError('Only the exact original baseline outage row can receive audit-column attribution.')
        adjusted['inventory'][note['table']][note['name']]=deepcopy(note['before']['columns']);restored.append(note)
    return adjusted,restored


def audit(path,final_queue):
    """Whole R15 audit with exact supported restoration/batch attribution."""
    two=v2();support,_,_,_=two._support();value=_value(path);proof=_proof(value)
    if any(row['status']!='passed' for row in proof['cases'].values()):raise RuntimeError('Every distinct v3 case must pass before a complete boundary audit.')
    if (final_queue['site']!=value['site'] or final_queue['queue']!='cipher-ai04-stage-a-20261016:short'
            or final_queue['jobs'] or final_queue['workers'] or final_queue['started_jobs']):raise AssertionError('Require independently observed empty final ordinary runtime inventory.')
    after=two.observe_native(path)
    if after['active_runs']:raise AssertionError('An active Company/Project Run remains.')
    before=support.load_private(two._proof(value)['baseline']['path']);adjusted,restored=restored_inventory(value,before,after)
    for case,row in proof['cases'].items():
        if row.get('run_id') and two._run(path,row['run_id'])['payloads']!=row['terminal']['payloads']:
            raise AssertionError('An original v3 terminal/preparation payload changed.')
        if case!='two-operation-r15' and row.get('proposal_id'):
            if any(item['value']['core']['proposal_id']==row['proposal_id'] for item in after['records']['Cipher Ricky Draft Save'].values()):
                raise AssertionError('A refused/probed suggestion acquired an application.')
    shadow=_batch_ledger(value)
    for case,row in proof['cases'].items():
        shadow['stages'][two.v1().KEY]['cases'][case]=deepcopy(row)
        for domain,target in row.get('targets',{}).items():two._proof(shadow)['targets'][case+'-'+domain]=deepcopy(target)
    result=two.verify_preservation(shadow,before,adjusted,support.Journal(value['journal_directory']).rows)
    value=_value(path);_proof(value).update(status='audited',restorations=restored,final_queue=final_queue,preservation=result,finished_at=two.stamp())
    support.write_private(path,value)
    return {'status':'audited','cases':len(CASES),'supported_restorations':len(restored),'overlap_batches':1,**result}
