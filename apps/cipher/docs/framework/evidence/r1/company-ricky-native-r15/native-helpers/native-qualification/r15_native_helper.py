"""Inert R15 native qualification helpers. No transport, migration or worker runner.

Root must review/freeze this file and install the reviewed backend separately.
Every callable is opt-in; importing this module performs no native operation.
Existing R14 helpers are used only as read/journal collaborators, never as an
R14 phase entrypoint. All mutable evidence belongs to a new R15 directory.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

KEY = 'draft_save_r15'
SCHEMA = 'cipher.fixture.ricky.company.draft-save.v1'
CASES = {
    'scope-r15': 'aec.scope.draft', 'estimate-r15': 'aec.estimate.draft',
    'cancel-before-finalization-r15': 'aec.scope.draft',
    'source-outage-r15': 'aec.scope.draft', 'native-write-outage-r15': 'aec.scope.draft',
    'duty-outage-r15': 'aec.estimate.draft', 'stale-target-r15': 'aec.scope.draft',
    'identity-refusal-r15': 'aec.scope.draft', 'rollback-r15': 'aec.scope.draft',
    'two-operation-r15': 'aec.scope.draft',
}
PROPOSAL = 'cipher_aec.ricky.company_proposal_api.'
SAVE = 'cipher_aec.ricky.company_draft_save_api.'
COMMERCIAL = 'cipher_aec.commercial.api.'
EST = 'cipher_aec.estimating.company_api.'
POSTS = frozenset({PROPOSAL+'start_proposal', PROPOSAL+'cancel_run', SAVE+'save_draft',
    COMMERCIAL+'create_proposal', COMMERCIAL+'save_proposal_revision', EST+'create_estimate', EST+'calculate_revision'})
GETS = frozenset({SAVE+'draft_save_subject', PROPOSAL+'get_run', PROPOSAL+'get_proposal',
    PROPOSAL+'run_events', 'cipher_aec.api.company.operation', 'cipher_aec.api.company.history',
    EST+'get_record', EST+'list_units', COMMERCIAL+'proposal', COMMERCIAL+'proposal_revision'})


def _modules():
    from cipher_aec.tests import ricky_company_acceptance_support as support
    from cipher_aec.tests import test_ricky_company_native as native
    from cipher_aec.tests import ricky_company_proposal_prerequisites as prerequisites
    from cipher_aec.tests import ricky_company_proposal_continuation as continuation
    return support,native,prerequisites,continuation


def _file(path):
    path=Path(path)
    if not path.is_file() or path.is_symlink(): raise ValueError('Require a retained regular file.')
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def _tree(directory):
    directory=Path(directory)
    if directory.is_symlink() or not directory.is_dir(): raise ValueError('Require the retained original directory.')
    return {str(p.relative_to(directory)):_file(p)['sha256'] for p in sorted(directory.rglob('*')) if p.is_file()}


def _copy_private(source,target):
    source,target=Path(source),Path(target)
    if source.is_symlink() or not source.is_file() or source.stat().st_mode & 0o077:
        raise ValueError('Require a regular mode0600 original cookie file.')
    descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(source.read_bytes());stream.flush();os.fsync(stream.fileno())
    descriptor=os.open(target.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def _indexes():
    import frappe
    rows=frappe.db.sql("SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tabCipher Ricky Draft Save' ORDER BY INDEX_NAME,SEQ_IN_INDEX",as_dict=True)
    grouped={}
    for row in rows:
        if row.NON_UNIQUE==0: grouped.setdefault(row.INDEX_NAME,[]).append(row.COLUMN_NAME)
    if ['source_proposal'] not in grouped.values() or ['receipt'] not in grouped.values():
        raise AssertionError('Supported additive sync must install both real single-column unique indexes first.')
    return [dict(row) for row in rows]


def _inventory():
    import frappe
    support,native,prerequisites,_=_modules()
    result=prerequisites.inventory()
    result['Cipher Ricky Draft Save']={row['name']:{key:support.sha(native._native_scalar(value)) for key,value in row.items()}
        for row in frappe.db.sql('SELECT * FROM `tabCipher Ricky Draft Save` ORDER BY name',as_dict=True)}
    return result


def prepare(original_manifest, prerequisite_record, cookie_sources, new_directory, *, backup_attestation, source_review):
    """Copy original identities/cookies, capture NEW R15 baseline; no DB write."""
    import frappe
    support,native,_,continuation=_modules()
    from cipher_aec.governance.context import require_company,current_actor,require_effects_enabled
    from cipher_aec.tests.ricky_company_recovery_acceptance import _only_active
    value=native._fixture(original_manifest);require_effects_enabled();_only_active()
    if value['inputs'].get('ready') is not True: raise ValueError('Reuse the original qualified manual inputs.')
    if frappe.conf.get('pause_scheduler') is not True: raise AssertionError('Retain the existing paused scheduler.')
    if set(cookie_sources)!=set(support.ROLES): raise ValueError('Use all three original cookie paths; no login fallback.')
    if source_review.get('status')!='root_reviewed_r15_backend_and_helper': raise ValueError('Freeze the concrete root review first.')
    backup=support.load_private(backup_attestation)
    if backup.get('status')!='verified_before_additive_sync' or not backup.get('database_sha256'):
        raise ValueError('Require an actual independently verified pre-sync database backup attestation.')
    indexes=_indexes()
    actor=current_actor(user=value['users']['author']['user'])
    if actor.person_id!=value['users']['author']['person']: raise AssertionError('Original Person binding changed.')
    for ability in ('ricky.run','commercial.read','commercial.write','estimate.read','estimate.write','document.read'):
        require_company(value['company'],ability=ability,actor=actor)
    for doctype,ptype in (('Quotation','read'),('Quotation','write'),('Quotation','create'),('Price List','read')):
        if not frappe.has_permission(doctype,ptype=ptype,user=actor.user):
            raise AssertionError('Qualify the exact existing human/native prerequisites before any fresh Start.')
    origin=Path(original_manifest).resolve().parent;directory=Path(new_directory).resolve()
    base=Path(frappe.get_site_path('private','cipher-fixtures')).resolve()
    if (directory.exists() or not directory.is_relative_to(base) or directory.is_relative_to(origin)
            or origin.is_relative_to(directory) or directory.name!='company-draft-save-r15'):
        raise ValueError('Require the entirely new, separate company-draft-save-r15 directory.')
    original_files=_tree(origin)
    cookies={role:_file(path) for role,path in cookie_sources.items()}
    prerequisite=support.load_private(prerequisite_record)
    if prerequisite.get('status')!='committed' or prerequisite.get('company')!=value['company']:
        raise ValueError('Reuse the existing committed prerequisite record; never rerun its phases.')
    baseline={'inventory':_inventory(),'config':_file(frappe.get_site_path('site_config.json')),
        'indexes':indexes,'users':continuation.observe_users(value),'captured_at':support.timestamp()}
    directory.mkdir(mode=0o700)
    for role,row in cookies.items():
        _copy_private(row['path'],directory/(role+'.cookies.secret'))
    baseline_path=directory/'draft-save-r15-baseline.secret.json';support.write_private(baseline_path,baseline)
    value=deepcopy(value);value.update(journal_directory=str(directory),intents={},shared_receipt_observations=[])
    for row in value['users'].values(): row['password']=None
    value['stages']={KEY:{'schema':SCHEMA,'status':'prepared','source_review':deepcopy(source_review),
        'original_directory':str(origin),'original_files':original_files,'cookie_sources':cookies,
        'prerequisite':_file(prerequisite_record),'backup':_file(backup_attestation),'baseline':_file(baseline_path),
        'cases':{case:{'status':'declared','action':action} for case,action in CASES.items()},'heartbeats':[]}}
    path=directory/'fixture.secret.json';support.write_private(path,value);support.manifest(path)
    frappe.db.rollback()
    return {'status':'prepared','private_manifest':str(path),'cases':list(CASES),'native_business_actions':0}


def _value(path):
    support,_,_,_=_modules();value=support.manifest(path);proof=value['stages'].get(KEY)
    if not proof or proof.get('schema')!=SCHEMA or set(proof['cases'])!=set(CASES): raise ValueError('Use only the new R15 journal.')
    if _tree(proof['original_directory'])!=proof['original_files']: raise AssertionError('Retained original R14 files changed.')
    for key in ('prerequisite','backup','baseline'):
        if _file(proof[key]['path'])!=proof[key]: raise AssertionError('Retained evidence changed: '+key)
    for role,row in proof['cookie_sources'].items():
        if _file(row['path'])!=row or _file(Path(value['journal_directory'])/(role+'.cookies.secret'))['sha256']!=row['sha256']:
            raise AssertionError('Original/copy cookie bytes changed; do not log in again.')
    return value


def _update(path, case=None, **fields):
    support,_,_,_=_modules();value=_value(path)
    row=value['stages'][KEY] if case is None else value['stages'][KEY]['cases'][case]
    row.update(deepcopy(fields));support.write_private(path,value)


def client(path, base_url, host_header, role='author'):
    """Explicit authentic wire client; sends only when root calls a method."""
    from cipher_aec.tests import test_ricky_company_http as http
    support,_,_,continuation=_modules()
    class R15HTTP(http._HTTP):
        def login(self,role='author',*,fresh=False):
            _value(self.path)
            if fresh or role not in support.ROLES: raise ValueError('No login fallback or new identity.')
            jar=Path(self.value['journal_directory'])/(role+'.cookies.secret')
            if not jar.is_file() or jar.is_symlink(): raise ValueError('Require the exact copied existing cookie jar.')
            return super().login(role,fresh=False)

        def _wire(self,*args,**kwargs):
            before=continuation.observe_users(self.value)
            try: return super()._wire(*args,**kwargs)
            finally:
                after=continuation.observe_users(self.value)
                changes=continuation.user_transition(before['users'],after['users'],self.value['users'],self.role,
                    before['started_at'],after['completed_at'])
                current=_value(self.path)
                current['stages'][KEY]['heartbeats'].append({'role':self.role,'before':before,'after':after,'changes':changes})
                support.write_private(self.path,current);self.value=current

        def call(self,method,values,*,key=None,replay=False):
            _value(self.path)
            if method not in POSTS|GETS: raise ValueError('Route exceeds the fixed R15 qualification allowlist.')
            verb='POST' if method in POSTS else 'GET'
            row=self.journal.prepare(key,self.role,method,values) if verb=='POST' else None
            if row and (row.get('attempts') or row.get('uncertain_transport')) and not replay:
                raise RuntimeError('Original UUID already attempted; preserve/reconcile it, never implicitly retry.')
            if replay and (not row or not row.get('attempts') or row.get('uncertain_transport')):
                raise RuntimeError('Only an explicitly verified retained receipt may be replayed.')
            sent=row['payload'] if row else values
            operation=self.openapi['paths']['/api/method/'+method][verb.lower()]
            from jsonschema import Draft202012Validator,FormatChecker
            if row:
                schema=operation['requestBody']['content']['application/json']['schema']
                Draft202012Validator({'components':self.openapi['components'],**schema},format_checker=FormatChecker()).validate(sent)
            try:
                status,payload,seconds=self._wire(verb,'/api/method/'+method,sent,csrf=self.csrf,
                    operation=row['operation_id'] if row else None)
                schema=operation['responses'][str(status)]['content']['application/json']['schema']
                Draft202012Validator({'components':self.openapi['components'],**schema},format_checker=FormatChecker()).validate(payload)
                envelope=payload['message']
                if envelope['schema']!='cipher.api.v1': raise AssertionError('Require the actual canonical wire envelope.')
            except BaseException as error:
                if row:self.journal.uncertain(row,error,getattr(self,'last_wire_observation',None))
                raise
            if row:self.journal.response(row,status=status,envelope=envelope)
            return {'status':status,'envelope':envelope,'seconds':seconds}
    _value(path);result=R15HTTP(path,base_url,host_header);result.login(role);return result


def start_case(path, case, request, base_url, host_header):
    """Fresh terminal preparation only; root separately consumes ordinary RQ."""
    if case not in CASES: raise ValueError('Declare a distinct R15 case, never repurpose an old Run.')
    value=_value(path);row=value['stages'][KEY]['cases'][case]
    if row['status']!='declared' or request.get('action')!=row['action']: raise ValueError('Require this exact unused case/action.')
    _update(path,case,status='start-attempted')
    response=client(path,base_url,host_header).call(PROPOSAL+'start_proposal',
        {'company':value['company'],'request':request},key='start-'+case)
    if response['status']!=200: raise AssertionError('Retain the failed Start UUID and response.')
    started=response['envelope']['data']
    if started['status']!='queued': raise AssertionError('Require the authentic queued Start response.')
    _update(path,case,status='queued',run_id=started['id'],start=started)
    return response


def review_subject(path, case, base_url, host_header):
    import frappe
    from cipher_aec.ricky.storage import CompanyStore
    from cipher_aec.tests.ricky_company_recovery_acceptance import _payloads
    value=_value(path);row=value['stages'][KEY]['cases'][case]
    run=CompanyStore(worker=True).get_scoped('run',row['run_id'])
    if run['status']!='waiting-for-review' or run['cancel_requested'] or len(run['proposal_ids'])!=1:
        raise AssertionError('Require an actual successful terminal preparation, with no cancellation.')
    proposal_id=run['proposal_ids'][0]
    response=client(path,base_url,host_header).call(SAVE+'draft_save_subject',{'company':value['company'],'proposal_id':proposal_id})
    if response['status']!=200: raise AssertionError('Retain the denied subject response.')
    subject=response['envelope']['data']
    _update(path,case,status='reviewed',proposal_id=proposal_id,review=subject,terminal_payloads=_payloads(run['id']))
    frappe.db.rollback();return subject


def save_reviewed(path, case, base_url, host_header):
    value=_value(path);row=value['stages'][KEY]['cases'][case];subject=row['review']
    if row['status']!='reviewed' or subject['eligible'] is not True: raise ValueError('Review this exact eligible new suggestion first.')
    expires=datetime.fromisoformat(subject['expires_at'])
    if datetime.now(timezone.utc)>=expires: raise RuntimeError('Keep the expired case; do not reset clocks or mint a replacement UUID.')
    reviewed={'proposal_id':subject['proposal_id'],'expected_version':subject['proposal_version'],
        'expected_content_digest':subject['proposal_digest'],'mapping_version':'1','expected_payload_digest':subject['payload_digest']}
    _update(path,case,status='save-attempted',reviewed=reviewed)
    response=client(path,base_url,host_header).call(SAVE+'save_draft',{'company':value['company'],**reviewed},key='save-'+case)
    _update(path,case,status='saved' if response['status']==200 else 'refused',save_response=response)
    return response


def verify_saved(path, case):
    """Independent readback, exact receipt/application links and immutable Run."""
    import frappe
    from cipher_aec.ricky.company_draft_save import _application,_receipt
    from cipher_aec.ricky.company_draft_save_contracts import application_id
    from cipher_aec.tests.ricky_company_recovery_acceptance import _payloads
    from cipher_aec.api.contracts import digest
    support,_,_,_=_modules();value=_value(path);row=value['stages'][KEY]['cases'][case]
    if row['status']!='saved': raise ValueError('Require the actual successful retained HTTP response.')
    data=row['save_response']['envelope']['data'];retained={key:data[key] for key in ('application','saved')}
    record=_application(row['proposal_id']);receipt,result=_receipt(record)
    if result!=retained or record['core']['id']!=application_id(row['proposal_id']): raise AssertionError('Receipt/application cross-links changed.')
    if record['core']['payload_digest']!=row['review']['payload_digest']: raise AssertionError('Saved payload differs from the human review.')
    if _payloads(row['run_id'])!=row['terminal_payloads']: raise AssertionError('Stage B terminal/preparation rows changed.')
    if frappe.db.count('Cipher Ricky Draft Save',{'source_proposal':row['proposal_id']})!=1: raise AssertionError('Require one immutable application.')
    core=record['core'];native=frappe.get_doc(core['saved_doctype'],core['saved_revision_id'])
    if json.loads(native.data_json)!=data['saved']['revision'] or digest(json.loads(native.data_json))!=core['saved_revision_digest']:
        raise AssertionError('The actual saved immutable native revision differs from the receipt.')
    events=frappe.db.sql("SELECT event,subject_type,subject_id,event_hash,previous_hash FROM `tabCipher History Event` "
        "WHERE scope_type='Company' AND (project IS NULL OR project='') AND company=%s AND operation_id=%s",
        (value['company'],core['operation_id']),as_dict=True)
    expected='commercial.proposal.revision.created' if core['action']=='aec.scope.draft' else 'estimate.revision.calculated'
    domain=[event for event in events if event.event==expected]
    application=[event for event in events if event.event=='ricky.company.proposal.draft-saved']
    if (len(events)!=2 or len(domain)!=1 or len(application)!=1 or application[0].previous_hash!=domain[0].event_hash
            or domain[0].subject_id!=core['saved_revision_id'] or application[0].subject_id!=core['id']):
        raise AssertionError('Require the canonical domain event then application event, with no duplicates.')
    _update(path,case,status='verified',application=deepcopy(core),receipt_hash=receipt.result_hash,events=[dict(event) for event in events])
    frappe.db.rollback();return {'status':'verified','case':case,'application_digest':core['core_digest']}
