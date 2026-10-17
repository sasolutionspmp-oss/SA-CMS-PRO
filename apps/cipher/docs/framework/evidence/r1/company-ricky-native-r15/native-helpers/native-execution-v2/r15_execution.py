"""Explicit R15 qualification callables; import is inert, root owns transport.

No Docker/subprocess, installation, migration, scheduler, reload, duty grant or
worker runner is provided. Existing evidence is read only. Native/HTTP functions
run only when root explicitly calls them in the qualified isolated environment.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

V1_SHA256='d78bc778428d741cc54be9449a11c09344080f4a3c1f037ce707da0c697a2b29'
KEY='execution_v2'
SCHEMA='cipher.fixture.ricky.company.draft-save-execution.v2'
POSITIVE=('scope-r15','estimate-r15')


def v1():
    path=Path(__file__).resolve().parent.parent/'native-qualification/r15_native_helper.py'
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=V1_SHA256:
        raise AssertionError('Keep the exact frozen v1 read collaborator.')
    spec=importlib.util.spec_from_file_location('cipher_r15_native_frozen_v1',path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def sha(value): return hashlib.sha256(canonical(value).encode()).hexdigest()


def stamp(): return datetime.now(timezone.utc).isoformat()


def _support(): return v1()._modules()


def _value(path):
    old=v1();value=old._value(path);proof=value['stages'][old.KEY].get(KEY)
    if not proof or proof.get('schema')!=SCHEMA: raise ValueError('Prepare the distinct R15 v2 evidence first.')
    if old._file(proof['baseline']['path'])!=proof['baseline']: raise AssertionError('The new R15 v2 baseline changed.')
    support,_,_,_=old._modules();original=support.manifest(Path(value['stages'][old.KEY]['original_directory'])/'fixture.secret.json')
    if any(value[key]!=original[key] for key in ('site','company','fixture_id','native','inputs','duties')):
        raise AssertionError('Original fixture scope, manual sources or prerequisite references changed.')
    for role,owner in value['users'].items():
        if owner['password'] is not None or any(owner[key]!=original['users'][role][key] for key in ('user','person')):
            raise AssertionError('Retain exact original identities with login credentials removed.')
    return value


def _proof(value): return value['stages'][v1().KEY][KEY]


def _save(path,**fields):
    support,_,_,_=_support();value=_value(path);_proof(value).update(deepcopy(fields));support.write_private(path,value)
    return value


def _case(path,case,**fields):
    old=v1();support,_,_,_=_support();value=_value(path)
    if case not in old.CASES: raise ValueError('Use an original distinct declared R15 case.')
    value['stages'][old.KEY]['cases'][case].update(deepcopy(fields));support.write_private(path,value)
    return value


def citation_references(value):
    citation=value['inputs']['citation']
    return [{key:citation[key] for key in ('revision_id','page','excerpt_sha256','source_sha256')}]


def authored_ids():
    return {key:str(uuid4()) for key in ('scope_section','scope_price_line','estimate_target_line','estimate_source_line')}


def target_composition(value,ids,plan):
    """Human original draft only; no estimate acceptance or generated amount."""
    from cipher_aec.commercial.contracts import composition
    unit=value['inputs']['units'][0]
    return composition({'currency':value['native'].get('company_reference',{}).get('default_currency','USD'),
        'price_list':plan['price_list'],'valid_till':plan['year_end'],
        'terms':'R15 synthetic human-authored draft; review required.',
        'sections':[{'id':ids['scope_section'],'kind':'scope','title':'R15 original human scope','text':'Original retained scope.'}],
        'price_lines':[{'id':ids['scope_price_line'],'description':'R15 original manual quantity','quantity':'2.000000',
            'unit_id':unit['id'],'unit_revision':unit['revision'],'rate':'1.25','item_code':None,'alternate_group':None,'selected':True}],
        'source_references':[{**citation_references(value)[0],'purpose':'Original raw synthetic source',
            'permission_basis':'Original human author owns the synthetic source'}],'estimate_revision':None})


def target_estimate_fields(value,ids,estimate_id,expected_revision=None,*,successor=False):
    """Two original authored lines let the selected quantity visibly change."""
    unit=value['inputs']['units'][0]
    lines=[]
    for key,amount in [('estimate_target_line','2.000000'),('estimate_source_line','3.000000')]:
        lines.append({'line_id':ids[key],'description':'R15 human '+('target' if key=='estimate_target_line' else 'source'),
            'quantity':{'amount':'4.000000' if successor and key=='estimate_target_line' else amount,'unit_id':unit['id'],'precision':6},
            'cost_code':'R15-01' if key=='estimate_target_line' else 'R15-02','notes':'Original human-authored input',
            'alternate':'','included':True,'rate_source_id':value['inputs']['rate']['id'],'material_factor':'1','waste_fraction':'0'})
    return {'estimate_id':estimate_id,'expected_revision':expected_revision,'lines':lines,'adjustments':[],
        'conversion_ids':[value['inputs']['conversion']['id']],'basis_description':'R15 original manual quantity basis',
        'basis_citations':citation_references(value)}


def exact_request(value,case):
    from cipher_aec.ricky.company_proposal_contracts import DeterministicProposalRequest,REQUEST_SCHEMA
    old=v1();proof=_proof(value)
    if case not in old.CASES: raise ValueError('Use a distinct literal R15 case.')
    action=old.CASES[case];citation=value['inputs']['citation']
    if action=='aec.scope.draft':
        revision=proof['targets']['commercial']['revision']
        arguments={'proposal_revision_id':revision['id'],'sections':[{'heading':'R15 proposed scope',
            'text':'Human-selected deterministic scope suggestion.','citation_ids':[citation['id']]}],
            'unverified_claims':['Human review is required before use.']}
    else:
        revision=proof['targets']['estimate']['revision'];lines=revision['line_record_ids']
        if len(lines)!=2 or len(set(lines))!=2: raise AssertionError('Keep the two distinct original authored line records.')
        arguments={'base_revision_id':revision['id'],'selections':[{'line_record_id':lines[0],
            'source_kind':'estimate-line','source_id':lines[1],'target_unit_id':value['inputs']['units'][0]['id']}],
            'notes':'R15 unverified deterministic selected source quantity.','citation_ids':[citation['id']],
            'unverified_claims':['Confirm the selected quantity basis.']}
    return DeterministicProposalRequest.from_value({'schema':REQUEST_SCHEMA,'pursuit_id':value['inputs']['pursuit']['id'],
        'action':action,'arguments':arguments,'sources':[{'citation_id':citation['id'],**citation_references(value)[0]}],
        'measurement_ids':[]}).binding()


def verify_queue_evidence(before,after,*,site,queue,run_id):
    """Exact ordinary RQ job identity; no queue deletion/worker action."""
    for observation in (before,after):
        if observation['site']!=site or observation['queue']!=queue or observation['workers'] or observation['started_jobs']:
            raise AssertionError('Require the exact isolated queue with no active foreign worker/job.')
    jobs=before['jobs']
    if len(jobs)!=1 or after['jobs']: raise AssertionError('Require one original queued hint and an empty final queue.')
    job=jobs[0]
    if (job['run_id']!=run_id or job['site']!=site or job['queue']!=queue
            or job['func_name']!='frappe.utils.background_jobs.execute_job'
            or job['method']!='cipher_aec.ricky.worker.process_run' or job['kwargs']!={'run_id':run_id}
            or job['status'] not in {'queued','JobStatus.QUEUED'}):
        raise AssertionError('The ordinary queued job does not bind the exact R15 Run.')
    completed=after['completed']
    if (len(completed)!=1 or completed[0]['id']!=job['id'] or completed[0]['run_id']!=run_id
            or completed[0]['status'] not in {'finished','JobStatus.FINISHED'} or not completed[0]['worker_name']
            or not completed[0]['started_at'] or not completed[0]['ended_at']):
        raise AssertionError('Require the original completed Job and actual ordinary worker evidence.')
    start=datetime.fromisoformat(completed[0]['started_at']);end=datetime.fromisoformat(completed[0]['ended_at'])
    if start>end: raise AssertionError('The real job time bounds are reversed.')
    return {'run_id':run_id,'job_id':job['id'],'worker_name':completed[0]['worker_name'],
        'started_at':completed[0]['started_at'],'ended_at':completed[0]['ended_at'],'queue':queue}


def _source(binding):
    if type(binding) is not dict or set(binding)!={'root','sha256','snapshot_sha256'} or not binding['sha256']:
        raise ValueError('Supply the exact root-reviewed installed source file binding.')
    root=Path(binding['root']).resolve();actual={}
    for relative,checksum in binding['sha256'].items():
        rel=Path(relative)
        if rel.is_absolute() or '..' in rel.parts: raise ValueError('Use only bounded relative source paths.')
        path=root/rel
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root): raise AssertionError('Installed source is missing or aliased.')
        actual[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
        if actual[relative]!=checksum: raise AssertionError('Installed source changed: '+relative)
    return {'root':str(root),'sha256':actual,'snapshot_sha256':binding['snapshot_sha256']}


def _native_config(frappe):
    path=Path(frappe.get_site_path('site_config.json'))
    return {'raw_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'parsed':json.loads(path.read_text()),
        'paused':frappe.conf.get('pause_scheduler'),'quarantine_present':'cipher_execution_quarantined' in frappe.conf,
        'quarantine_value':frappe.conf.get('cipher_execution_quarantined')}


def observe_native(path):
    """Independent connection; caller's transaction/locks are never ended."""
    old=v1();support,native,_,continuation=_support();value=_value(path)
    def read(frappe):
        inventory=old._inventory()
        records={}
        for table in ('Cipher Proposal','Cipher Proposal Revision','Cipher Estimate','Cipher Estimate Revision',
                'Cipher Calculation Snapshot','Cipher Estimate Line','Cipher Ricky Draft Save','Cipher Unit Conversion',
                'Cipher Rate Source','Cipher Assembly Revision','Cipher Estimate Acceptance'):
            records[table]={row.name:{'raw':row.data_json,'digest':row.record_digest,'value':json.loads(row.data_json)}
                for row in frappe.db.sql('SELECT name,data_json,record_digest FROM `tab'+table+'` ORDER BY name',as_dict=True)}
        receipts={row.name:dict(row) for row in frappe.db.sql('SELECT name,person,operation_id,company,scope_type,project,command,request_hash,result_json,result_hash,state '
            'FROM `tabCipher Command Receipt` ORDER BY name',as_dict=True)}
        history={row.name:dict(row) for row in frappe.db.sql('SELECT name,event,scope_type,company,project,actor_person,subject_type,subject_id,operation_id,details_json,previous_hash,event_hash,event_payload '
            'FROM `tabCipher History Event` ORDER BY creation,name',as_dict=True)}
        sessions={}
        for row in frappe.db.sql('SELECT * FROM tabSessions ORDER BY sid',as_dict=True):
            sessions[hashlib.sha256(row.sid.encode()).hexdigest()]={key:support.sha(native._native_scalar(item)) for key,item in row.items()}
        inventory['Sessions']=sessions
        applications={row.name:dict(row) for row in frappe.db.sql('SELECT name,company,scope_type,project,requested_by,person,source_proposal,run,step,invocation,receipt,saved_doctype,saved_revision '
            'FROM `tabCipher Ricky Draft Save` ORDER BY name',as_dict=True)}
        from cipher_aec.commercial.native import persisted
        quotations={name:persisted(name) for name in {row['value']['quotation'] for row in records['Cipher Proposal'].values()}}
        heads=frappe.db.sql("SELECT event_hash FROM `tabCipher History Event` WHERE scope_type='Company' AND company=%s AND (project IS NULL OR project='') ORDER BY creation DESC,name DESC LIMIT 1",(value['company'],))
        from cipher_aec.ricky.engine import ACTIVE
        from cipher_aec.ricky.storage import FrappeStore
        active=[run['id'] for run in FrappeStore(worker=True).find('run',{'status':['in',list(ACTIVE)]},limit=101)]
        return {'inventory':inventory,'records':records,'receipts':receipts,'history':history,'applications':applications,'quotations':quotations,'active_runs':active,
            'company_head':heads[0][0] if heads else '',
            'config':_native_config(frappe),'source':_source(_proof(value)['source']),
            'indexes':old._indexes(),'at':support.timestamp()}
    return continuation._independent(read)


def prepare(original_manifest,prerequisite_record,cookie_sources,new_directory,*,backup_attestation,source_review,installed_source):
    """One new R15 directory and two immutable baselines; no grant/sync."""
    old=v1();support,_,_,continuation=_support()
    source=_source(installed_source)
    if source_review.get('backup_attestation_sha256')!=old._file(backup_attestation)['sha256']:
        raise AssertionError('Root review must bind the real backup attestation bytes.')
    result=old.prepare(original_manifest,prerequisite_record,cookie_sources,new_directory,
        backup_attestation=backup_attestation,source_review=source_review)
    path=Path(result['private_manifest']);value=old._value(path)
    # Provisional v2 metadata is never treated as a completed baseline.
    proof={'schema':SCHEMA,'status':'preparing','source':source,'ids':authored_ids(),
        'baseline':old._file(value['stages'][old.KEY]['baseline']['path']),'targets':{},'wires':[]}
    value['stages'][old.KEY][KEY]=proof;support.write_private(path,value)
    state=observe_native(path);state['auth_sessions']=_observe_sessions(value)
    baseline_path=path.parent/'draft-save-r15-v2-baseline.secret.json'
    support.write_private(baseline_path,state)
    _save(path,status='prepared',baseline=old._file(baseline_path))
    return {**result,'version':2,'baseline_sha256':old._file(baseline_path)['sha256']}


def _observe_users(value): return _support()[3].observe_users(value)


def _observe_sessions(value):
    """Hash original Session columns; retain only typed heartbeat timestamps."""
    from http.cookiejar import LWPCookieJar
    support,native,_,continuation=_support();references={}
    for role in support.ROLES:
        jar=LWPCookieJar(str(Path(value['journal_directory'])/(role+'.cookies.secret')))
        jar.load(ignore_discard=True,ignore_expires=True)
        sids=[cookie.value for cookie in jar if cookie.name=='sid']
        if len(sids)!=1 or not sids[0] or sids[0]=='Guest': raise AssertionError('Require one exact original native SID in each copied jar.')
        references[role]=hashlib.sha256(sids[0].encode()).hexdigest()
    if len(set(references.values()))!=len(references): raise AssertionError('Do not alias different original User Sessions.')
    def read(frappe):
        continuation.verify_installed_session_source();result={}
        for role,reference in references.items():
            rows=frappe.db.sql('SELECT * FROM tabSessions WHERE user=%s AND SHA2(sid,256)=%s',(value['users'][role]['user'],reference),as_dict=True)
            if len(rows)!=1: raise AssertionError('The exact original native Session is unavailable; no fallback.')
            row=rows[0];details=json.loads(row.sessiondata)
            result[role]={'reference':reference,'user':row.user,
                'columns':{key:support.sha(native._native_scalar(item)) for key,item in row.items()},
                'data':{key:support.sha(item) for key,item in details.items()},
                'lastupdate':native._native_scalar(row.lastupdate),'last_updated':details.get('last_updated')}
        return result
    return continuation._independent(read)


def session_transition(before,after,role,start,end):
    """Exact pinned Session.update effect; never excuse other Session drift."""
    _,_,_,continuation=_support()
    if set(before)!=set(after) or role not in before: raise AssertionError('Original Session set changed.')
    changes=[]
    for owner,old in before.items():
        new=after[owner]
        if old==new: continue
        if owner!=role or old['reference']!=new['reference'] or old['user']!=new['user']:
            raise AssertionError('A different original Session changed during this wire.')
        if set(old['columns'])!=set(new['columns']) or set(old['data'])!=set(new['data']): raise AssertionError('Native Session field set changed.')
        columns={key for key in old['columns'] if old['columns'][key]!=new['columns'][key]}
        data={key for key in old['data'] if old['data'][key]!=new['data'][key]}
        if columns!={'lastupdate','sessiondata'} or data!={'last_updated'}:
            raise AssertionError('Only the pinned native Session heartbeat fields may change.')
        current=continuation._active(new['lastupdate']);previous=continuation._active(old['lastupdate'])
        inside=continuation._active({'type':'datetime','value':new['last_updated']})
        if (current!=inside or current<=previous or not datetime.fromisoformat(start)<=current<=datetime.fromisoformat(end)
                or new['data']['last_updated']!=sha(new['last_updated'])):
            raise AssertionError('Native Session heartbeat is not exact and time-bounded to this wire.')
        changes.append({'role':role,'reference':new['reference'],'before':old['columns'],'after':new['columns']})
    return changes


def observed_wire(client,send,method,path,values=None,*,csrf=None,operation=None):
    """Persist actual errors first; exact native User chain and wire bounds."""
    support,_,_,continuation=_support();value=_value(client.path);proof=_proof(value)
    baseline=support.load_private(value['stages'][v1().KEY]['baseline']['path'])
    native_baseline=support.load_private(proof['baseline']['path'])
    before=_observe_users(value);sessions_before=_observe_sessions(value)
    previous=proof['wires'][-1].get('after',{}).get('users') if proof['wires'] else baseline['users']['users']
    previous_sessions=proof['wires'][-1].get('sessions_after') if proof['wires'] else native_baseline['auth_sessions']
    if before['timezone']!=continuation.TIMEZONE_POLICY or before['users']!=previous:
        raise AssertionError('User bytes changed outside the exact recorded R15 wire chain.')
    if sessions_before!=previous_sessions: raise AssertionError('Session bytes changed outside the exact recorded R15 wire chain.')
    entry={'role':client.role,'method':method,'path':path,'operation_id':operation,'payload_sha256':sha(values),
        'before':before,'sessions_before':sessions_before,'started_at':stamp()};result=None;error=None
    try: result=send(method,path,values,csrf=csrf,operation=operation)
    except BaseException as failure:
        error=failure;entry['wire_error']={'type':type(failure).__name__}
    entry['completed_at']=stamp();entry['wire']=deepcopy(getattr(client,'last_wire_observation',None))
    try:
        entry['after']=_observe_users(value);entry['sessions_after']=_observe_sessions(value)
    except BaseException as failure:
        entry['observer_error']={'type':type(failure).__name__};error=error or failure
    current=_value(client.path);_proof(current)['wires'].append(entry);support.write_private(client.path,current)
    if error is not None: raise error
    if entry['after']['timezone']!=continuation.TIMEZONE_POLICY: raise AssertionError('The actual native timezone policy changed.')
    changes=continuation.user_transition(before['users'],entry['after']['users'],value['users'],client.role,entry['started_at'],entry['completed_at'])
    session_changes=session_transition(sessions_before,entry['sessions_after'],client.role,entry['started_at'],entry['completed_at'])
    entry.update(status='verified',changes=changes,session_changes=session_changes)
    current=_value(client.path);_proof(current)['wires'][-1]=entry;support.write_private(client.path,current);client.value=current
    return result


def client(path,base_url,host_header,role='author'):
    """Fixed routes; existing original cookies only, with no login method."""
    from cipher_aec.tests import test_ricky_company_http as http
    from http.cookiejar import LWPCookieJar
    old=v1();support,_,_,_=_support()
    class HTTP(http._HTTP):
        def login(self,*args,**kwargs): raise RuntimeError('R15 never invokes login or replaces a Session.')

        def authenticate(self,role):
            self.value=_value(self.path)
            if role not in support.ROLES: raise ValueError('Use an exact original identity.')
            self.role=role;self.cookie_path=self.work/(role+'.cookies.secret')
            if not self.cookie_path.is_file() or self.cookie_path.is_symlink() or self.cookie_path.stat().st_mode&0o077:
                raise ValueError('Require the exact private copied original cookie jar.')
            self.jar=LWPCookieJar(str(self.cookie_path));self.jar.load(ignore_discard=True,ignore_expires=True)
            self.opener=http._opener(self.jar)
            status,payload,_=self._wire('GET','/api/method/cipher_aec.api.v1.session')
            envelope=payload.get('message',{}) if type(payload) is dict else {};session=envelope.get('data',{})
            owner=self.value['users'][role]
            if (status!=200 or session.get('site_mode')!='synthetic' or session.get('user')!=owner['user']
                    or session.get('person',{}).get('id')!=owner['person'] or type(session.get('csrf_token')) is not str or not session['csrf_token']):
                raise AssertionError('The actual copied cookie does not identify its exact original User/Person.')
            self.csrf=session['csrf_token']

        def _wire(self,*args,**kwargs): return observed_wire(self,super()._wire,*args,**kwargs)

        def call(self,method,values,*,key=None,replay=False):
            _value(self.path)
            if method not in old.POSTS|old.GETS: raise ValueError('Route exceeds the fixed reviewed R15 surface.')
            verb='POST' if method in old.POSTS else 'GET';row=self.journal.prepare(key,self.role,method,values) if verb=='POST' else None
            if row and (row.get('attempts') or row.get('uncertain_transport')) and not replay:
                raise RuntimeError('Retain the attempted UUID; no implicit retry.')
            if replay and (not row or not row.get('attempts') or row.get('uncertain_transport')):
                raise RuntimeError('Replay requires a reconciled exact retained receipt.')
            sent=row['payload'] if row else values
            from jsonschema import Draft202012Validator,FormatChecker
            operation=self.openapi['paths']['/api/method/'+method][verb.lower()]
            if row: Draft202012Validator({'components':self.openapi['components'],**operation['requestBody']['content']['application/json']['schema']},format_checker=FormatChecker()).validate(sent)
            try:
                status,payload,seconds=self._wire(verb,'/api/method/'+method,sent,csrf=self.csrf,operation=row['operation_id'] if row else None)
                schema=operation['responses'][str(status)]['content']['application/json']['schema']
                Draft202012Validator({'components':self.openapi['components'],**schema},format_checker=FormatChecker()).validate(payload)
                envelope=payload['message']
                if envelope.get('schema')!='cipher.api.v1' or envelope.get('meta',{}).get('request_id')!=envelope.get('request_id'):
                    raise AssertionError('The actual canonical wire envelope changed.')
            except BaseException as failure:
                if row:self.journal.uncertain(row,failure,getattr(self,'last_wire_observation',None))
                raise
            if row:self.journal.response(row,status=status,envelope=envelope)
            return {'status':status,'envelope':envelope,'seconds':seconds}
    result=HTTP(path,base_url,host_header);result.authenticate(role);return result


def _data(response):
    if response['status']!=200 or 'data' not in response['envelope']: raise AssertionError('Retain the actual failed HTTP outcome/UUID.')
    return response['envelope']['data']


def create_targets(path,base_url,host_header):
    old=v1();value=_value(path);proof=_proof(value)
    if proof['status']!='prepared' or proof['targets']: raise RuntimeError('Fresh targets are one-shot; reconcile a failed phase.')
    support,_,_,_=_support();prerequisite=support.load_private(value['stages'][old.KEY]['prerequisite']['path']);plan=prerequisite['plan']
    _save(path,status='targets-entered')
    try:
        rpc=client(path,base_url,host_header)
        commercial=_data(rpc.call(old.COMMERCIAL+'create_proposal',{'company':value['company'],'pursuit_id':value['inputs']['pursuit']['id'],
            'composition':target_composition(value,proof['ids'],plan)},key='r15-create-commercial'))
        targets={'commercial':commercial};_save(path,targets=targets)
        estimate=_data(rpc.call(old.EST+'create_estimate',{'company':value['company'],'title':'R15 distinct human-authored estimate',
            'currency':'USD','pricing_date':plan['pricing_date'],'pursuit_id':value['inputs']['pursuit']['id']},key='r15-create-estimate'))['estimate']
        targets['estimate']={'estimate':estimate};_save(path,targets=targets)
        calculation=_data(rpc.call(old.EST+'calculate_revision',{'company':value['company'],
            **target_estimate_fields(value,proof['ids'],estimate['id'])},key='r15-calculate-original'))
        targets['estimate']=calculation
        if commercial['proposal']['id']==value['inputs'].get('proposal',{}).get('id') or estimate['id']==value['inputs']['estimate']['id']:
            raise AssertionError('Never adopt an earlier R14/fixture business head.')
        _save(path,status='targets-ready',targets=targets)
        return {'status':'targets-ready','proposal_id':commercial['proposal']['id'],'estimate_id':estimate['id']}
    except BaseException as failure:
        _save(path,status='targets-failed',error={'type':type(failure).__name__});raise


def _run(path,run_id):
    _,_,_,continuation=_support()
    def read(frappe):
        from cipher_aec.ricky.storage import CompanyStore
        from cipher_aec.tests.ricky_company_recovery_acceptance import _payloads
        store=CompanyStore(worker=True);run=store.get_scoped('run',run_id)
        children={kind:store.find(kind,{'run_id':run_id},limit=101) for kind in ('step','invocation','proposal','delegation','artifact')}
        return {'run':run,'children':children,'payloads':_payloads(run_id)}
    return continuation._independent(read)


def start_case(path,case,base_url,host_header):
    old=v1();value=_value(path);proof=_proof(value);row=value['stages'][old.KEY]['cases'].get(case)
    if case not in POSITIVE: raise NotImplementedError('The eight separately declared refusal/probe cases remain unrun.')
    if row['status']!='declared' or proof['status']!='targets-ready': raise RuntimeError('Require this unused case and the fresh R15 targets.')
    if case=='estimate-r15' and value['stages'][old.KEY]['cases']['scope-r15']['status'] not in {'verified','replay-verified'}:
        raise RuntimeError('Finish the scope save before starting the separate estimate deadline.')
    request=exact_request(value,case)
    _case(path,case,status='start-attempted',request=request)
    response=client(path,base_url,host_header).call(old.PROPOSAL+'start_proposal',{'company':value['company'],'request':request},key='start-'+case)
    data=_data(response)
    if data['status']!='queued' or data['action']!=old.CASES[case] or data['operation']['replayed']:
        raise AssertionError('Require a new authentic queued Stage B admission.')
    actual=_run(path,data['id']);run=actual['run']
    if (run['request']!=request or run['user']!=value['users']['author']['user'] or run['person']!=value['users']['author']['person']
            or run['company']!=value['company'] or run['operation_id']!=data['operation']['id']):
        raise AssertionError('Actual Run lost its original human/request binding.')
    _case(path,case,status='queued',run_id=data['id'],start=data,operation_id=data['operation']['id'],admitted=actual)
    return {'case':case,'status':'queued','run_id':data['id']}


def observe_queue(path,case,*,completed_ids=()):
    """Read ordinary Redis/RQ evidence only; root runs the worker separately."""
    from frappe.utils.background_jobs import get_queue,get_redis_conn
    from rq import Worker
    from rq.job import Job
    from rq.registry import StartedJobRegistry
    value=_value(path);row=value['stages'][v1().KEY]['cases'][case];run_id=row['run_id']
    queue=get_queue('short');connection=get_redis_conn();jobs=[];completed=[]
    def job_value(job):
        fields=job.kwargs
        return {'id':job.id,'run_id':fields.get('kwargs',{}).get('run_id'),'site':fields.get('site'),
            'queue':queue.name,'func_name':job.func_name,'method':fields.get('method'),'kwargs':deepcopy(fields.get('kwargs')),
            'status':str(job.get_status()),'worker_name':job.worker_name,
            'started_at':job.started_at.isoformat() if job.started_at else None,'ended_at':job.ended_at.isoformat() if job.ended_at else None}
    for job in queue.get_jobs(): jobs.append(job_value(job))
    for name in completed_ids: completed.append(job_value(Job.fetch(name,connection=connection)))
    return {'site':value['site'],'queue':queue.name,'workers':[worker.name for worker in Worker.all(connection=connection)],
        'started_jobs':StartedJobRegistry(queue=queue).get_job_ids(cleanup=False),'jobs':jobs,'completed':completed,'run_id':run_id,'at':stamp()}


def record_queue_before(path,case,observation):
    value=_value(path);row=value['stages'][v1().KEY]['cases'][case]
    if row['status']!='queued' or row.get('queue_before'): raise RuntimeError('Keep the original pre-worker observation.')
    if observation['run_id']!=row['run_id'] or len(observation['jobs'])!=1:
        raise AssertionError('Only the sole authentic queued R15 job may be consumed.')
    _case(path,case,queue_before=observation)
    return {'status':'recorded','job_ids':[job['id'] for job in observation['jobs']]}


def record_queue_after(path,case,observation):
    value=_value(path);row=value['stages'][v1().KEY]['cases'][case]
    evidence=verify_queue_evidence(row['queue_before'],observation,site=value['site'],
        queue='cipher-ai04-stage-a-20261016:short',run_id=row['run_id'])
    actual=_run(path,row['run_id']);run=actual['run'];children=actual['children']
    if (run['status']!='waiting-for-review' or run['cancel_requested'] or len(run['proposal_ids'])!=1
            or len(children['step'])!=1 or children['step'][0]['status']!='succeeded'
            or len(children['invocation'])!=1 or children['invocation'][0]['status']!='succeeded'
            or len(children['proposal'])!=1 or children['proposal'][0]['id']!=run['proposal_ids'][0]):
        raise AssertionError('The ordinary job did not leave one exact successful terminal preparation.')
    _case(path,case,status='prepared',queue_after=observation,queue_evidence=evidence,terminal=actual,proposal_id=run['proposal_ids'][0])
    return evidence


def review_subject(path,case,base_url,host_header):
    old=v1();value=_value(path);row=value['stages'][old.KEY]['cases'][case]
    if row['status']!='prepared': raise RuntimeError('Require independently verified ordinary RQ preparation first.')
    before=_run(path,row['run_id'])
    if before['payloads']!=row['terminal']['payloads']: raise AssertionError('Terminal preparation changed before review.')
    rpc=client(path,base_url,host_header)
    original_reads={'run':_data(rpc.call(old.PROPOSAL+'get_run',{'company':value['company'],'run_id':row['run_id']})),
        'proposal':_data(rpc.call(old.PROPOSAL+'get_proposal',{'company':value['company'],'proposal_id':row['proposal_id']}))}
    response=rpc.call(old.SAVE+'draft_save_subject',{'company':value['company'],'proposal_id':row['proposal_id']})
    subject=_data(response)
    if (subject['proposal_id']!=row['proposal_id'] or subject['action']!=old.CASES[case] or subject['mapping_version']!='1'
            or subject['payload_digest']!=sha(subject['payload']) or subject['eligible'] is not True or subject['application'] is not None):
        raise AssertionError('Require the exact unconsumed eligible canonical subject.')
    _case(path,case,status='reviewed',review=subject,original_reads=original_reads,review_before=observe_native(path))
    return subject


def save_reviewed(path,case,base_url,host_header):
    old=v1();value=_value(path);row=value['stages'][old.KEY]['cases'][case];subject=row['review']
    if row['status']!='reviewed' or subject['eligible'] is not True: raise RuntimeError('Review this unused eligible suggestion first.')
    deadline=datetime.fromisoformat(subject['expires_at'])
    if deadline.tzinfo is None or datetime.now(timezone.utc)>=deadline: raise RuntimeError('Retain the expired case; never extend or replace it.')
    reviewed={'proposal_id':subject['proposal_id'],'expected_version':subject['proposal_version'],
        'expected_content_digest':subject['proposal_digest'],'mapping_version':'1','expected_payload_digest':subject['payload_digest']}
    _case(path,case,status='save-attempted',reviewed=reviewed)
    response=client(path,base_url,host_header).call(old.SAVE+'save_draft',{'company':value['company'],**reviewed},key='save-'+case)
    data=_data(response)
    if data['operation']['replayed'] is not False: raise AssertionError('Require the first canonical save receipt.')
    _case(path,case,status='saved',saved=data)
    return data


def _record(state,table,name):
    row=state['records'][table][name];value=row['value']
    if json.loads(row['raw'])!=value or sha(value)!=row['digest'] or value.get('id',value.get('core',{}).get('id'))!=name:
        raise AssertionError('The independent immutable native row cannot be verified.')
    return value


def _events(state,core):
    rows=[row for row in state['history'].values() if row['operation_id']==core['operation_id']]
    for row in rows:
        body=json.loads(row['event_payload'])
        if (sha(body)!=row['event_hash'] or json.loads(row['details_json'])!=body['details']
                or any(body[key]!=row[column] for key,column in [('scope_type','scope_type'),('actor','actor_person'),('company','company'),
                    ('project','project'),('event','event'),('subject_type','subject_type'),('subject_id','subject_id'),('operation_id','operation_id'),('previous_hash','previous_hash')])):
            raise AssertionError('History payload/hash/native columns differ.')
    domain_name='commercial.proposal.revision.created' if core['action']=='aec.scope.draft' else 'estimate.revision.calculated'
    domain=[row for row in rows if row['event']==domain_name];application=[row for row in rows if row['event']=='ricky.company.proposal.draft-saved']
    if (len(rows)!=2 or len(domain)!=1 or len(application)!=1 or domain[0]['subject_id']!=core['saved_revision_id']
            or domain[0]['subject_type']!=core['saved_doctype'] or application[0]['subject_type']!='Cipher Ricky Draft Save'
            or application[0]['subject_id']!=core['id'] or application[0]['previous_hash']!=domain[0]['event_hash']
            or any(row['scope_type']!='Company' or row['company']!=core['company'] or row['project'] is not None or row['actor_person']!=core['person'] for row in rows)):
        raise AssertionError('Require exactly the canonical domain→application Company chain.')
    return [domain[0],application[0]]


def verify_saved_state(value,case,state,*,current=True):
    """Pure independent-row verifier, also used after successor/expiry replay."""
    from cipher_aec.ricky.company_draft_save_contracts import application_id,COMMANDS,derive
    old=v1();row=value['stages'][old.KEY]['cases'][case];response=row['saved'];core=response['application'];saved=response['saved']
    retained={'application':core,'saved':saved};payload=row['review']['payload'];revision=saved['revision'];target=core['target_id']
    terminal=row['terminal'];run=terminal['run'];proposal=terminal['children']['proposal'][0];invocation=terminal['children']['invocation'][0]
    command,canonical_command,domain=COMMANDS[old.CASES[case]]
    base=run['request']['arguments']['proposal_revision_id' if domain=='commercial' else 'base_revision_id']
    if (core['schema']!='cipher.ricky.company.draft-save.v1' or core['command']!=command or core['canonical_command']!=canonical_command
            or core['run_id']!=row['run_id'] or run['id']!=row['run_id'] or core['invocation_id']!=invocation['id']
            or core['step_id']!=invocation['step_id'] or core['preparation_digest']!=invocation['output_digest']
            or core['manifest_digest']!=run['original_manifest_digest'] or core['base_revision_id']!=base
            or core['proposal_version']!=proposal['version'] or core['proposal_digest']!=proposal['content_digest']
            or core['proposal_version']!=row['review']['proposal_version'] or core['proposal_digest']!=row['review']['proposal_digest']
            or target!=payload['proposal_id' if domain=='commercial' else 'estimate_id']):
        raise AssertionError('Core differs from the original native successful preparation/target binding.')
    tables={('commercial','proposal-revision'):'Cipher Proposal Revision',('estimate','revision'):'Cipher Estimate Revision',
        ('estimate','snapshot'):'Cipher Calculation Snapshot',('estimate','line'):'Cipher Estimate Line',('estimate','conversion'):'Cipher Unit Conversion',
        ('estimate','rate'):'Cipher Rate Source',('estimate','assembly'):'Cipher Assembly Revision',('estimate','acceptance'):'Cipher Estimate Acceptance'}
    originals={}
    for reference in run['original_manifest']['records']:
        key=(reference['domain'],reference['kind'],reference['id']);actual=_record(state,tables[key[:2]],key[2])
        if sha(actual)!=reference['digest']: raise AssertionError('An immutable original preparation dependency changed.')
        originals[key]=actual
    for name,item in state['records']['Cipher Unit Conversion'].items():
        originals['estimate','conversion',name]=_record(state,'Cipher Unit Conversion',name)
    citation=value['inputs']['citation'];originals['documents','citation',citation['id']]=citation
    if derive(proposal,run,originals)!=payload: raise AssertionError('Independent original mapping differs from the reviewed canonical payload.')
    if (core['id']!=application_id(row['proposal_id']) or core['proposal_id']!=row['proposal_id'] or core['company']!=value['company']
            or core['user']!=value['users']['author']['user'] or core['person']!=value['users']['author']['person']
            or core['action']!=old.CASES[case] or core['mapping_version']!='1' or core['classification']!='unverified-author-suggestion'
            or core['core_digest']!=sha({k:v for k,v in core.items() if k!='core_digest'}) or core['payload_digest']!=sha(payload)
            or core['receipt_id']!=sha({'person':core['person'],'operation_id':core['operation_id']})
            or core['saved_revision_id']!=revision['id'] or core['saved_revision_digest']!=sha(revision)):
        raise AssertionError('The actual saved application binding changed.')
    envelope=_record(state,'Cipher Ricky Draft Save',core['id'])
    if envelope!={'core':core,'receipt_result_hash':sha(retained)}: raise AssertionError('Application envelope/receipt linkage changed.')
    headers={'name':core['id'],'company':core['company'],'scope_type':'Company','project':None,'requested_by':core['user'],'person':core['person'],
        'source_proposal':core['proposal_id'],'run':core['run_id'],'step':core['step_id'],'invocation':core['invocation_id'],
        'receipt':core['receipt_id'],'saved_doctype':core['saved_doctype'],'saved_revision':core['saved_revision_id']}
    if state['applications'][core['id']]!=headers: raise AssertionError('Native application headers differ from core JSON.')
    if sum(item['value']['core']['proposal_id']==row['proposal_id'] for item in state['records']['Cipher Ricky Draft Save'].values())!=1:
        raise AssertionError('Require exactly one application for the original suggestion.')
    receipt=state['receipts'][core['receipt_id']]
    request={'scope_type':'Company','company':value['company'],'project':None,'command':core['command'],
        'payload':{'reviewed':row['reviewed'],'canonical_command':core['canonical_command'],'canonical_payload':payload}}
    if (receipt['name']!=core['receipt_id'] or receipt['request_hash']!=sha(request) or receipt['result_hash']!=sha(retained)
            or json.loads(receipt['result_json'])!=retained or receipt['person']!=core['person'] or receipt['company']!=value['company']
            or receipt['scope_type']!='Company' or receipt['project'] not in (None,'') or receipt['state']!='Succeeded'
            or receipt['command']!=core['command'] or receipt['operation_id']!=core['operation_id']):
        raise AssertionError('Actual immutable receipt differs from the exact reviewed canonical request/result.')
    if _record(state,core['saved_doctype'],revision['id'])!=revision or revision['predecessor']!=core['base_revision_id']:
        raise AssertionError('The saved native revision is not the exact original successor.')
    if core['action']=='aec.scope.draft':
        if revision['proposal']!=target or revision['composition']!=payload['composition']: raise AssertionError('Saved scope mapping changed.')
        parent=_record(state,'Cipher Proposal',target)
        if current and (parent!=saved['proposal'] or state['quotations'][parent['quotation']]!=revision['native']
                or sha(revision['native'])!=revision['native_fingerprint'] or parent['native_fingerprint']!=revision['native_fingerprint']):
            raise AssertionError('Actual current native Quotation/head differs from the canonical saved revision.')
    else:
        from cipher_aec.estimating.calculation import calculate
        if revision['estimate']!=target: raise AssertionError('Saved estimate owner changed.')
        snapshot=_record(state,'Cipher Calculation Snapshot',revision['calculation_snapshot'])
        if snapshot!=saved['calculation'] or calculate(snapshot['inputs'])!=snapshot['result']:
            raise AssertionError('Actual saved calculation does not independently recompute.')
        if any(snapshot['inputs'][key]!=payload[key] for key in ('lines','adjustments','basis_description')):
            raise AssertionError('Saved authored estimate inputs differ from the reviewed mapping.')
        if (snapshot['input_digest']!=snapshot['result']['input_digest'] or snapshot['output_digest']!=snapshot['result']['output_digest']
                or sorted(definition['id'] for definition in snapshot['inputs']['unit_manifest']['unit_conversions'])!=sorted(payload['conversion_ids'])):
            raise AssertionError('Exact conversion/calculation digests changed.')
        if any(revision[key]!=snapshot['result'][key] for key in ('direct','indirect','contingency','total')):
            raise AssertionError('Saved revision totals differ from independent canonical calculation.')
        if len(revision['line_record_ids'])!=len(payload['lines']): raise AssertionError('Saved authored line count changed.')
        for index,name in enumerate(revision['line_record_ids']):
            line=_record(state,'Cipher Estimate Line',name)
            if line['estimate_revision']!=revision['id'] or line['authored']!=payload['lines'][index] or line['calculated']!=snapshot['result']['lines'][index]:
                raise AssertionError('Actual immutable line identity/authored/calculated linkage changed.')
        parent=_record(state,'Cipher Estimate',target)
        if current and parent!=saved['estimate']: raise AssertionError('Saved estimate head differs from canonical persisted owner.')
    if current and parent['current_revision']!=revision['id']: raise AssertionError('Require one actual successor working head.')
    return {'application':deepcopy(core),'receipt':deepcopy(receipt),'events':_events(state,core)}


def verify_saved(path,case):
    value=_value(path);row=value['stages'][v1().KEY]['cases'][case]
    if row['status']!='saved': raise RuntimeError('Require the first actual successful HTTP save.')
    terminal=_run(path,row['run_id'])
    if terminal['payloads']!=row['terminal']['payloads']: raise AssertionError('Saving rewrote original Stage B preparation/terminal bytes.')
    state=observe_native(path);proof=verify_saved_state(value,case,state)
    _case(path,case,status='verified',independent_saved=proof,saved_state=state)
    return {'status':'verified','case':case,'application_digest':proof['application']['core_digest']}


def replay_saved(path,case,base_url,host_header,*,require_expired=False):
    old=v1();value=_value(path);row=value['stages'][old.KEY]['cases'][case]
    if row['status'] not in {'verified','replay-verified'}: raise RuntimeError('Verify the original native save before explicit same-UUID replay.')
    if require_expired and datetime.now(timezone.utc)<datetime.fromisoformat(row['review']['expires_at']):
        raise RuntimeError('Wait naturally; never change retained deadlines or clocks.')
    before=observe_native(path);before_run=_run(path,row['run_id'])
    response=client(path,base_url,host_header).call(old.SAVE+'save_draft',{'company':value['company'],**row['reviewed']},key='save-'+case,replay=True)
    data=_data(response)
    if (data['operation']!={'id':row['saved']['operation']['id'],'status':'succeeded','replayed':True}
            or any(data[key]!=row['saved'][key] for key in ('application','saved'))):
        raise AssertionError('Exact original save replay changed its retained result or UUID.')
    after=observe_native(path);after_run=_run(path,row['run_id'])
    for key in ('records','receipts','history','applications','quotations','config','source','indexes'):
        if before[key]!=after[key]: raise AssertionError('Replay changed independent native data: '+key)
    if before_run['payloads']!=after_run['payloads'] or after_run['payloads']!=row['terminal']['payloads']:
        raise AssertionError('Replay rewrote Stage B terminal/preparation bytes.')
    verify_saved_state(value,case,after,current=False)
    _case(path,case,status='replay-verified',replay={'response':data,'before_sha256':sha(before),'after_sha256':sha(after),'expired':require_expired})
    return {'status':'replay-verified','case':case,'expired':require_expired}


def advance_successor(path,case,base_url,host_header):
    """A separate manual command on the new R15 owner; no R14 head edits."""
    old=v1();value=_value(path);row=value['stages'][old.KEY]['cases'][case]
    if row['status'] not in {'verified','replay-verified'} or row.get('successor_attempted'):
        raise RuntimeError('Declare one separate ordinary manual successor after the verified save.')
    saved=row['saved']['saved']
    if case=='scope-r15':
        composition=deepcopy(saved['revision']['composition'])
        composition['sections'].append({'id':str(uuid4()),'kind':'scope','title':'R15 separately authored successor','text':'Later human revision.'})
        method=old.COMMERCIAL+'save_proposal_revision'
        fields={'proposal_id':saved['proposal']['id'],'expected_revision':saved['proposal']['revision_number'],
            'expected_native_fingerprint':saved['revision']['native_fingerprint'],'composition':composition}
    elif case=='estimate-r15':
        inputs=saved['calculation']['inputs'];lines=deepcopy(inputs['lines']);lines[0]['quantity']['amount']='4.000000'
        method=old.EST+'calculate_revision'
        fields={'estimate_id':saved['estimate']['id'],'expected_revision':saved['revision']['id'],'lines':lines,
            'adjustments':deepcopy(inputs['adjustments']),'conversion_ids':[definition['id'] for definition in inputs['unit_manifest']['unit_conversions']],
            'basis_description':'R15 separate human successor','basis_citations':[{key:source[key] for key in ('revision_id','page','excerpt_sha256','source_sha256')} for source in inputs['basis_citations']]}
    else: raise ValueError('Only the two positive fresh R15 owners have a successor flow.')
    _case(path,case,successor_attempted=True,successor_fields=fields)
    result=_data(client(path,base_url,host_header).call(method,{'company':value['company'],**fields},key='successor-'+case))
    if result['operation']['replayed'] or result['revision']['predecessor']!=saved['revision']['id']:
        raise AssertionError('Require the separate first ordinary manual successor receipt.')
    _case(path,case,successor=result)
    verify_saved_state(_value(path),case,observe_native(path),current=False)
    return {'status':'successor-created','case':case,'revision_id':result['revision']['id']}


def historical_reads(path,case,base_url,host_header,*,require_expired=False):
    old=v1();value=_value(path);row=value['stages'][old.KEY]['cases'][case]
    if row['status'] not in {'verified','replay-verified'}: raise RuntimeError('Verify the original saved application first.')
    if require_expired and datetime.now(timezone.utc)<datetime.fromisoformat(row['review']['expires_at']):
        raise RuntimeError('Natural expiry is required; preserve the retained deadline.')
    rpc=client(path,base_url,host_header);company={'company':value['company']}
    actual={'run':_data(rpc.call(old.PROPOSAL+'get_run',{**company,'run_id':row['run_id']})),
        'proposal':_data(rpc.call(old.PROPOSAL+'get_proposal',{**company,'proposal_id':row['proposal_id']}))}
    if actual!=row['original_reads']: raise AssertionError('Historical original API preparation changed after save/successor/expiry.')
    subject=_data(rpc.call(old.SAVE+'draft_save_subject',{**company,'proposal_id':row['proposal_id']}))
    if (subject['payload']!=row['review']['payload'] or subject['payload_digest']!=row['review']['payload_digest']
            or subject['application']!=row['saved']['application'] or subject['saved']!=row['saved']['saved']
            or subject['eligible'] is not False or subject['reason']['code']!='draft_already_saved'):
        raise AssertionError('Historical subject lost its original canonical save binding.')
    operation=_data(rpc.call('cipher_aec.api.company.operation',{**company,'operation_id':row['saved']['operation']['id']}))
    expected={**row['saved'],'operation':{**row['saved']['operation'],'replayed':True}}
    if operation!=expected: raise AssertionError('Operation GET did not return the exact original application receipt.')
    start=_data(rpc.call(old.PROPOSAL+'start_proposal',{**company,'request':row['request']},key='start-'+case,replay=True))
    if start!={**row['start'],'operation':{**row['start']['operation'],'replayed':True}}:
        raise AssertionError('Original Start receipt was rewritten or requeued.')
    history=_data(rpc.call('cipher_aec.api.company.history',{**company,'limit':50,'count_mode':'exact'}))
    event=row['independent_saved']['events'][1]
    if len([item for item in history['items'] if item['id']==event['name']])!=1:
        raise AssertionError('The current original author cannot read the exact application history event.')
    _case(path,case,historical={'expired':require_expired,'subject':subject,'operation':operation,'start':start,'history':history})
    return {'status':'historical-readable','case':case,'expired':require_expired}


def reconcile_heartbeats(value,before,after):
    """Restore only byte-proven native User/Session heartbeat fields."""
    support,_,_,continuation=_support();proof=_proof(value)
    baseline_users=support.load_private(value['stages'][v1().KEY]['baseline']['path'])['users']['users']
    users=baseline_users;sessions=before['auth_sessions']
    for wire in proof['wires']:
        if (wire.get('status')!='verified' or wire['before']['users']!=users or wire['sessions_before']!=sessions
                or wire['before']['timezone']!=continuation.TIMEZONE_POLICY or wire['after']['timezone']!=continuation.TIMEZONE_POLICY):
            raise AssertionError('An incomplete/broken wire ledger cannot excuse old-row drift.')
        changes=continuation.user_transition(users,wire['after']['users'],value['users'],wire['role'],wire['started_at'],wire['completed_at'])
        session_changes=session_transition(sessions,wire['sessions_after'],wire['role'],wire['started_at'],wire['completed_at'])
        if changes!=wire['changes'] or session_changes!=wire['session_changes']: raise AssertionError('Stored heartbeat attribution changed.')
        users=wire['after']['users'];sessions=wire['sessions_after']
    result=deepcopy(after['inventory'])
    for name,row in users.items():
        if result['User'].get(name)!=row['columns']: raise AssertionError('Current native User columns differ from the complete observed wire chain.')
        result['User'][name]=deepcopy(before['inventory']['User'][name])
    for role,row in sessions.items():
        if result['Sessions'].get(row['reference'])!=row['columns']: raise AssertionError('Current original Session columns differ from the exact wire chain.')
        result['Sessions'][row['reference']]=deepcopy(before['inventory']['Sessions'][row['reference']])
    return result


def allowed_additions(value,state,journal):
    """Concrete server results determine row IDs; no arbitrary allowlist input."""
    old=v1();proof=_proof(value);expected={table:set() for table in state['inventory']}
    def add(table,name): expected[table].add(name)
    def result(data):
        if 'proposal' in data:
            add('Cipher Proposal',data['proposal']['id']);add('Cipher Proposal Revision',data['revision']['id'])
            quote=data['proposal']['quotation'];add('Quotation',quote)
            for item in state['quotations'][quote]['items']:add('Quotation Item',item['name'])
        if 'estimate' in data:
            add('Cipher Estimate',data['estimate']['id'])
            if 'revision' in data:
                revision=data['revision'];add('Cipher Estimate Revision',revision['id'])
                add('Cipher Calculation Snapshot',revision['calculation_snapshot'])
                for name in revision['line_record_ids']:add('Cipher Estimate Line',name)
    for target in proof['targets'].values():result(target)
    tables={'run':'Cipher Ricky Run','step':'Cipher Ricky Step','invocation':'Cipher Tool Invocation',
        'proposal':'Cipher Proposed Change','delegation':'Cipher Delegation','artifact':'Cipher Run Artifact'}
    for case,row in value['stages'][old.KEY]['cases'].items():
        if 'terminal' in row:
            for kind,rows in row['terminal']['payloads'].items():
                for name in rows:add(tables[kind],name)
        if 'saved' in row:
            result(row['saved']['saved']);add('Cipher Ricky Draft Save',row['saved']['application']['id'])
        if 'successor' in row:result(row['successor'])
    commands={old.COMMERCIAL+'create_proposal':'commercial.proposal.create',old.COMMERCIAL+'save_proposal_revision':'commercial.proposal.revise',
        old.EST+'create_estimate':'estimate.create.v1',old.EST+'calculate_revision':'estimate.calculate.v1',
        old.PROPOSAL+'start_proposal':'ricky.company.proposal.start.v1',old.PROPOSAL+'cancel_run':'ricky.company.proposal.cancel.v1'}
    event_names={old.COMMERCIAL+'create_proposal':['commercial.proposal.revision.created'],old.COMMERCIAL+'save_proposal_revision':['commercial.proposal.revision.created'],
        old.EST+'create_estimate':['estimate.created'],old.EST+'calculate_revision':['estimate.revision.calculated'],
        old.PROPOSAL+'start_proposal':['ricky.company.proposal.start.accepted'],old.PROPOSAL+'cancel_run':['ricky.company.proposal.stop.accepted']}
    for entry in journal:
        if sha(entry['payload'])!=entry['payload_sha256'] or entry['payload'].get('operation_id')!=entry['operation_id']:
            raise AssertionError('The original fsynced R15 request/UUID bytes changed.')
        successes=[attempt for attempt in entry['attempts'] if attempt.get('status')==200 and 'data' in attempt.get('envelope',{})]
        if not successes:continue
        data=successes[0]['envelope']['data'];method=entry['method'];operation=entry['operation_id'];person=value['users'][entry['role']]['person']
        retained={key:item for key,item in data.items() if key!='operation'};name=sha({'person':person,'operation_id':operation})
        receipt=state['receipts'][name];payload={key:item for key,item in entry['payload'].items() if key not in {'company','operation_id'}}
        if method==old.SAVE+'save_draft':
            core=retained['application'];command=core['command'];names=['commercial.proposal.revision.created' if core['action']=='aec.scope.draft' else 'estimate.revision.calculated','ricky.company.proposal.draft-saved']
            case=next(row for row in value['stages'][old.KEY]['cases'].values() if row.get('proposal_id')==core['proposal_id'])
            if entry['payload']!={'company':value['company'],**case['reviewed'],'operation_id':operation}:
                raise AssertionError('The actual fsynced save POST differs from the reviewed binding-only payload.')
            payload={'reviewed':case['reviewed'],'canonical_command':core['canonical_command'],'canonical_payload':case['review']['payload']}
        else:command=commands[method];names=event_names[method]
        request={'scope_type':'Company','company':value['company'],'project':None,'command':command,'payload':payload}
        if (receipt['person']!=person or receipt['operation_id']!=operation or receipt['scope_type']!='Company' or receipt['company']!=value['company']
                or receipt['project'] not in (None,'') or receipt['command']!=command or receipt['state']!='Succeeded'
                or receipt['request_hash']!=sha(request) or receipt['result_hash']!=sha(retained) or json.loads(receipt['result_json'])!=retained):
            raise AssertionError('An R15 receipt does not match its exact fsynced authentic command/result.')
        add('Cipher Command Receipt',name)
        events=[row for row in state['history'].values() if row['operation_id']==operation]
        if sorted(row['event'] for row in events)!=sorted(names): raise AssertionError('Unexpected/missing canonical history events for an R15 command.')
        for event in events:
            body=json.loads(event['event_payload'])
            if (sha(body)!=event['event_hash'] or body['actor']!=person or body['company']!=value['company'] or body['scope_type']!='Company'
                    or body['project'] is not None or body['operation_id']!=operation or body['event']!=event['event']):
                raise AssertionError('An R15 history event has foreign scope, identity or payload/hash.')
            add('Cipher History Event',event['name'])
    return expected


def verify_preservation(value,before,after,journal):
    if before['config']!=after['config'] or before['source']!=after['source'] or before['indexes']!=after['indexes']:
        raise AssertionError('Exact configuration, installed source or unique indexes changed after the new R15 baseline.')
    reconciled=reconcile_heartbeats(value,before,after)
    if set(before['inventory'])!=set(reconciled): raise AssertionError('The typed native inventory table set changed.')
    for table,rows in before['inventory'].items():
        for name,fields in rows.items():
            if reconciled[table].get(name)!=fields: raise AssertionError('An original typed row changed: '+table+'/'+name)
    expected=allowed_additions(value,after,journal)
    additions={table:set(rows)-set(before['inventory'][table]) for table,rows in reconciled.items()}
    if additions!=expected:
        mismatch={table:{'unexpected':sorted(additions[table]-expected[table]),'missing':sorted(expected[table]-additions[table])}
            for table in additions if additions[table]!=expected[table]}
        raise AssertionError('Native additions differ from exact R15 command/result row identities: '+canonical(mismatch))
    # One continuous Company chain, from the retained baseline head through all
    # and only the newly attributed events, without trusting timestamp ordering.
    new=[after['history'][name] for name in additions['Cipher History Event']];head=before['company_head']
    while new:
        next_rows=[row for row in new if row['previous_hash']==head]
        if len(next_rows)!=1: raise AssertionError('R15 Company history fork/gap detected.')
        row=next_rows[0];head=row['event_hash'];new.remove(row)
    if head!=after['company_head']: raise AssertionError('The actual final Company history head differs from the exact attributed chain.')
    return {'old_rows_unchanged':True,'additions':{table:sorted(names) for table,names in additions.items() if names},
        'wire_heartbeats':len(_proof(value)['wires']),'config_source_indexes_unchanged':True}


def audit_positive(path,final_queue):
    old=v1();support,_,_,_=_support();value=_value(path);proof=_proof(value)
    for case,row in value['stages'][old.KEY]['cases'].items():
        if case in POSITIVE:
            if row['status'] not in {'verified','replay-verified'}: raise RuntimeError('Both positive saves must be independently verified.')
        elif row!={'status':'declared','action':old.CASES[case]}:
            raise RuntimeError('This audit covers the two positives; independently qualify any separately attempted boundary cases.')
    if (final_queue['site']!=value['site'] or final_queue['queue']!='cipher-ai04-stage-a-20261016:short'
            or final_queue['jobs'] or final_queue['workers'] or final_queue['started_jobs']):
        raise AssertionError('Require independently observed empty final isolated queue/worker/started inventory.')
    after=observe_native(path);before=support.load_private(proof['baseline']['path'])
    if after['active_runs']: raise AssertionError('No active Company or Project Run may remain at the final audit.')
    for case in POSITIVE:
        row=value['stages'][old.KEY]['cases'][case]
        if _run(path,row['run_id'])['payloads']!=row['terminal']['payloads']: raise AssertionError('Original terminal preparation bytes changed.')
        verify_saved_state(value,case,after,current=not bool(row.get('successor')))
    journal=support.Journal(value['journal_directory']).rows
    result=verify_preservation(value,before,after,journal)
    _save(path,status='two-positive-cases-audited',preservation=result,final_queue=final_queue,
        unrun_cases=[case for case in old.CASES if case not in POSITIVE],finished_at=stamp())
    return {'status':'two-positive-cases-audited','scope_and_estimate':True,'other_declared_cases':'not_run',**result}
