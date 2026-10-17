"""Actual Company integration transport, separate from native Session fixtures.

Credentials stay in the root-coordinated private fixture manifest. Commands are
journaled privately before network transmission; uncertain outcomes retain the
same UUID/payload. Only explicit retryable503+Retry-After receives bounded retry.
No function in this module provisions identities implicitly.
"""
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from uuid import UUID,uuid4


class CompanyHTTPRPC:
    def __init__(self,fixture,*,repository,base_url,private_directory,host_header=None):
        self.fixture=fixture;self.root=Path(repository).resolve();self.base_url=base_url;self.host_header=host_header
        self.work=Path(private_directory);self.work.mkdir(parents=True,exist_ok=True);self.work.chmod(0o700)
        spec=importlib.util.spec_from_file_location('company_chain_real_http_client',self.root/'apps/cipher/platform/operations/verify_r0.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.Client=module.Client;self.clients={};self.calls=[];self.journal=[];self.role=None;self.schema_samples=0
        self.session_timings=[]
        app=self.root/'apps/cipher/platform/apps/cipher_aec'
        if str(app) not in sys.path:sys.path.insert(0,str(app))
        from cipher_aec.api.catalog import ROUTES
        self.routes=ROUTES
        self.openapi=json.loads((app/'cipher_aec/api/openapi.json').read_text())

    def _journal(self):
        target=self.work/'company-chain-command-journal.json'
        temporary=target.with_name(target.name+'.'+uuid4().hex+'.pending')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(self.journal,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,target)
        directory=os.open(self.work,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
        try:os.fsync(directory)
        finally:os.close(directory)

    def login(self,role):
        if role not in self.fixture['users']:raise RuntimeError('Only explicit fixture identities may sign in.')
        if role not in self.clients:
            client=self.Client(self.base_url,self.host_header);started=time.perf_counter();stage='login'
            timing={'role':role}
            try:
                client.login(self.fixture['users'][role]);timing['login_seconds']=round(time.perf_counter()-started,6)
                stage='session';session_started=time.perf_counter();session=client.api('session')
                timing['session_seconds']=round(time.perf_counter()-session_started,6);timing['status']='passed'
            except Exception as error:
                timing.update(status='failed',failure_stage=stage,failure_type=type(error).__name__)
                raise
            finally:
                timing['total_seconds']=round(time.perf_counter()-started,6);self.session_timings.append(timing)
            if session.get('site_mode')!='synthetic' or not session.get('csrf_token'):
                raise AssertionError('Actual Company HTTP requires synthetic mode and a real server CSRF token.')
            client.csrf=session['csrf_token'];self.clients[role]=client
        self.role=role

    def _schema(self,method,part,value):
        from jsonschema import Draft202012Validator,FormatChecker,ValidationError
        operation=self.openapi['paths']['/api/method/'+method][self.routes[method].method.lower()]
        if part=='response':
            schema=operation['responses']['200']['content']['application/json']['schema']
        else:
            schema=operation['requestBody']['content']['application/json']['schema']
        try:
            Draft202012Validator({'components':self.openapi['components'],**schema},format_checker=FormatChecker()).validate(value)
        except ValidationError as error:
            # Never put response values (which can contain session tokens) in an
            # evidence error message. The instance/schema paths are sufficient.
            raise AssertionError('Actual '+part+' schema mismatch for '+method+' at '+'.'.join(map(str,error.absolute_path))) from None
        self.schema_samples+=1

    def invoke(self,method,values=None,expected_codes=()):
        if self.role is None or method not in self.routes:raise RuntimeError('Sign in and select a literal registered route.')
        route=self.routes[method];client=self.clients[self.role];values=values or {};entry=None
        if route.binary and not expected_codes:raise RuntimeError('Use the separate original-byte download probe for successful binary routes.')
        if route.method=='POST':
            operation=values.get('operation_id')
            if type(operation) is not str or str(UUID(operation))!=operation:
                raise RuntimeError('An actual command requires its canonical UUID before the first send.')
            # Even deliberately invalid input remains authored synthetic test
            # content. Login bodies, session headers and secrets never enter it.
            def secret(value):
                if isinstance(value,dict):return any(key.lower() in {'password','pwd','csrf_token','sid','cookie','authorization'} or secret(item) for key,item in value.items())
                return isinstance(value,list) and any(secret(item) for item in value)
            if secret(values):raise RuntimeError('Credentials/session fields cannot enter the command journal.')
            serialized=json.dumps(values,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
            entry={'role':self.role,'method':method,'operation_id':operation,'payload':json.loads(serialized),'payload_sha256':hashlib.sha256(serialized.encode()).hexdigest(),
                   'state':'prepared_before_network','attempts':[]}
            self.journal.append(entry);self._journal()
            if not expected_codes:self._schema(method,'request',values)
        for attempt in range(3):
            request_started=time.perf_counter()
            try:
                status,payload,raw,headers=client.request(route.method,'/api/method/'+method,values,operation=values.get('operation_id') if route.command else None)
            except Exception:
                if entry:entry['state']='outcome_unknown_original_request_retained';self._journal()
                raise
            if not isinstance(payload,dict):raise AssertionError('Actual Company RPC returned no JSON envelope.')
            envelope=payload.get('message',payload)
            if not isinstance(envelope,dict) or envelope.get('schema')!='cipher.api.v1' or not isinstance(envelope.get('meta'),dict):
                raise AssertionError('Actual Company RPC returned no versioned response metadata.')
            if any(key in payload for key in ('exc','exception','exc_type')):raise AssertionError('Actual Company API exposed a framework exception.')
            meta=envelope['meta']
            stamp=datetime.fromisoformat(meta.get('server_time','').replace('Z','+00:00'))
            if meta.get('api_version')!='v1' or not meta.get('request_id') or stamp.utcoffset()!=timezone.utc.utcoffset(None):
                raise AssertionError('Actual Company metadata has no stable request ID/version/UTC timestamp.')
            result=envelope.get('data') if status<400 else envelope.get('error')
            if not isinstance(result,dict):raise AssertionError('Actual Company RPC has no structured business result.')
            observation={'role':self.role,'method':method,'http_status':status,'request_id':meta['request_id'],'server_time':meta['server_time'],
                         'request_seconds':round(time.perf_counter()-request_started,6)}
            if status>=400:observation['error_code']=result.get('code')
            self.calls.append(observation)
            if entry:
                entry['attempts'].append(observation);entry['state']='response_recorded';self._journal()
            if status==503 and result.get('retryable') is True:
                delay=headers.get('Retry-After','')
                if attempt<2 and delay.isdigit() and 1<=int(delay)<=5:
                    time.sleep(int(delay));continue
                raise RuntimeError('Retryable command remained unavailable; original UUID/payload retained.')
            if status>=400:
                if result.get('code') not in expected_codes:raise AssertionError('Actual '+method+' returned unexpected safe error '+str(result.get('code')))
                return {'error_code':result['code']}
            if expected_codes:raise AssertionError('An expected actual Company HTTP denial succeeded: '+method)
            self._schema(method,'response',payload)
            return result
        raise AssertionError('Bounded Company command loop exhausted.')

    def original_bytes(self,company,revision_id,expected):
        method='cipher_aec.documents.company_api.download_revision';client=self.clients[self.role]
        status,payload,raw,headers=client.request('GET','/api/method/'+method,{'company':company,'revision_id':revision_id},expected=(200,))
        if raw!=expected or headers.get('Content-Disposition','').lower().find('attachment')<0:
            raise AssertionError('Actual canonical Company download did not reproduce original attachment bytes.')
        self.calls.append({'role':self.role,'method':method,'http_status':status,'original_sha256':hashlib.sha256(raw).hexdigest(),'byte_length':len(raw)})
        return {'sha256':hashlib.sha256(raw).hexdigest(),'byte_length':len(raw)}

    def close(self):
        pass

    def private_file(self,path,expected,*,denied=False):
        if not path.startswith('/private/files/') or '?' in path or '#' in path:
            raise RuntimeError('Probe only an explicit native private File URL.')
        status,payload,raw,headers=self.clients[self.role].request('GET',path)
        if denied:
            if status not in (403,404) or raw==expected or b'Authored material rate USD12.34' in raw:
                raise AssertionError('A denied native private File exposed Company source bytes.')
        elif status!=200 or raw!=expected:
            raise AssertionError('The authorized native private File changed its original Company bytes.')
        result={'role':self.role,'route':'/private/files/<owned-fixture-source>','http_status':status,'source_bytes_denied':denied}
        self.calls.append(result);return result


def run_http_manual_acceptance(private_manifest,*,repository,base_url,private_directory,host_header=None):
    """Actual positive/stale journey; root coordinates revocation phases later."""
    import base64
    app=Path(repository).resolve()/'apps/cipher/platform/apps/cipher_aec'
    if str(app) not in sys.path:sys.path.insert(0,str(app))
    from cipher_aec.tests.test_company_chain_acceptance import drive_manual_estimate,drive_stale_successor,assert_current_chain_access,assert_fixture_master_selectors
    fixture=json.loads(Path(private_manifest).read_text())
    if fixture.get('setup_status')!='ready':raise RuntimeError('Run only the explicitly provisioned, ready private fixture.')
    rpc=CompanyHTTPRPC(fixture,repository=repository,base_url=base_url,private_directory=private_directory,host_header=host_header)
    report={'schema':'cipher.r1.company-manual-http-acceptance.v1','status':'failed','fixture_id':fixture['fixture_id'],
            'company':fixture['company'],'started_at':datetime.now(timezone.utc).isoformat(),
            'qualification':'Actual authenticated cookie/CSRF Company DOC/manual EST/human grant endpoints; no calibrated geometry or COM issue claim.',
            'calibrated_company_takeoff_qualified':False,'commercial_issue_qualified':False,'live_model_qualified':False,'external_provider_qualified':False}
    try:
        context=drive_manual_estimate(rpc,fixture,'http')
        context_path=rpc.work/'company-chain-http-positive-context.json'
        descriptor=os.open(context_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w') as stream:json.dump(context,stream,indent=2,sort_keys=True);stream.write('\n')
        report['master_selectors']=assert_fixture_master_selectors(rpc,fixture)
        upload=context['payloads'][context['operations']['upload']]['values']
        report['original_attachment']=rpc.original_bytes(fixture['company'],context['source_revision']['id'],base64.b64decode(upload['content_base64']))
        report['checks']=context['checks']
        report['stale_successor']=drive_stale_successor(rpc,context)
        snapshot=assert_current_chain_access(rpc,context)
        report['historical_readback']={'history_exact_count':snapshot['history']['total'],'original_acceptance_sha256':snapshot['acceptance_digest']}
        # Preserve exact original commands/context privately for later root-
        # coordinated current-permission phases, never as reconstructed bodies.
        path=rpc.work/'company-chain-http-context.json'
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w') as stream:json.dump({'context':context,'before':snapshot},stream,indent=2,sort_keys=True);stream.write('\n')
        report['status']='passed'
        return report
    except Exception as error:
        report['failure_type']=type(error).__name__
        raise
    finally:
        rpc.close();report['calls']=rpc.calls;report['schema_samples']=rpc.schema_samples
        report['completed_at']=datetime.now(timezone.utc).isoformat()
        path=rpc.work/('company-chain-http-'+uuid4().hex+'.result.json')
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w') as stream:json.dump(report,stream,indent=2,sort_keys=True);stream.write('\n')


def run_http_source_revocation(private_manifest,*,repository,base_url,private_directory,context_file,source_file,
                               bench_private_manifest,container='cipher-r0-runtime-1',site='cipher.localhost',host_header=None):
    """Explicit root-coordinated synthetic mutation phase; no User/Auth writes."""
    import base64
    import subprocess
    app=Path(repository).resolve()/'apps/cipher/platform/apps/cipher_aec'
    if str(app) not in sys.path:sys.path.insert(0,str(app))
    from cipher_aec.tests.test_company_chain_acceptance import assert_current_chain_access,assert_company_document_revoked
    fixture=json.loads(Path(private_manifest).read_text());saved=json.loads(Path(context_file).read_text());context=saved['context']
    source=json.loads(Path(source_file).read_text())
    if context['company']!=fixture['company'] or source['company']!=fixture['company'] or source['revision_id']!=context['source_revision']['id']:
        raise RuntimeError('Revocation phase inputs must bind the exact same owned Company source.')
    content=base64.b64decode(context['payloads'][context['operations']['upload']]['values']['content_base64'])
    if hashlib.sha256(content).hexdigest()!=source['sha256']:raise RuntimeError('The explicit native File locator changed source identity.')
    rpc=CompanyHTTPRPC(fixture,repository=repository,base_url=base_url,private_directory=private_directory,host_header=host_header)
    docker=Path(repository)/'apps/cipher/platform/deployment/docker-local.sh'
    def bench(name,values):
        command=[str(docker),'exec','--workdir','/home/frappe/frappe-bench',container,'bench','--site',site,'execute',
                 'cipher_aec.tests.test_company_chain_acceptance.'+name,'--kwargs',json.dumps(values,sort_keys=True)]
        result=subprocess.run(command,capture_output=True,text=True,check=False,timeout=60)
        if result.returncode:raise RuntimeError('The explicit synthetic fixture '+name+' bench operation failed; captured output remains private.')
        return json.loads(result.stdout)
    def mutate(active):
        return bench('set_fixture_duty',{'private_manifest':bench_private_manifest,'role':'author','ability':'document.read','active':active})
    report={'schema':'cipher.r1.company-source-http-revocation.v1','status':'failed','fixture_id':fixture['fixture_id'],'company':fixture['company'],
            'started_at':datetime.now(timezone.utc).isoformat(),'qualification':'Actual cookie/CSRF source and completed-receipt denial plus native private File byte boundary. Root-coordinated Company Duty toggle only; no User/Auth writes.',
            'live_model_qualified':False,'external_provider_qualified':False,'commercial_issue_qualified':False}
    try:
        before=assert_current_chain_access(rpc,context)
        report['canonical_original_before']=rpc.original_bytes(fixture['company'],source['revision_id'],content)
        report['native_private_file']=[]
        for role in ('author','alias','outsider','project_only'):
            # Native File.is_downloadable intentionally denies every source
            # actor; original bytes use the source-authorized attachment RPC.
            rpc.login(role);report['native_private_file'].append(rpc.private_file(source['private_file_url'],content,denied=True))
        try:
            report['revocation']=mutate(0)
            report['source_revoked']=assert_company_document_revoked(rpc,context,before)
            for role in ('author','alias'):
                rpc.login(role);report['native_private_file'].append(rpc.private_file(source['private_file_url'],content,denied=True))
        finally:
            report['restoration']=mutate(1)
        after=assert_current_chain_access(rpc,context)
        if after['history']!=before['history'] or after['acceptance_digest']!=before['acceptance_digest']:
            raise AssertionError('Restored source rights did not recover the exact original history and accepted facts.')
        rpc.login('author');report['native_private_file'].append(rpc.private_file(source['private_file_url'],content,denied=True))
        report['canonical_original_after']=rpc.original_bytes(fixture['company'],source['revision_id'],content)
        report['restored_history_exact_count']=after['history']['total']
        report['native_readback']=bench('fixture_readback',{'private_manifest':bench_private_manifest})
        report['status']='passed';return report
    except Exception as error:
        report['failure_type']=type(error).__name__;raise
    finally:
        rpc.close();report['calls']=rpc.calls;report['schema_samples']=rpc.schema_samples;report['completed_at']=datetime.now(timezone.utc).isoformat()
        path=rpc.work/('company-chain-source-http-'+uuid4().hex+'.result.json')
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w') as stream:json.dump(report,stream,indent=2,sort_keys=True);stream.write('\n')
