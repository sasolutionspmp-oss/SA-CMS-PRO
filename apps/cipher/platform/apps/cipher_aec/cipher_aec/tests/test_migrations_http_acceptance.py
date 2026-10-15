"""Opt-in host HTTP qualification using an existing isolated MIG fixture.

PYTHONPATH=apps/cipher/platform/apps/cipher_aec python -m cipher_aec.tests.test_migrations_http_acceptance
No credentials, cookies or CSRF values are written to evidence or stdout.
"""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess


def run_http_acceptance(repository=None, base_url='http://127.0.0.1:18880'):
    repository=Path(repository or Path.cwd())
    native_path=repository/'apps/cipher/docs/framework/evidence/r0/migration-acceptance.json'
    native=json.loads(native_path.read_text())
    project,user=native['project'],native['user']
    docker=str(repository/'apps/cipher/platform/deployment/docker-local.sh')
    prefix=[docker,'exec','-w','/home/frappe/frappe-bench','cipher-r0-runtime-1','bench','--site','cipher.localhost','execute']
    password=secrets.token_urlsafe(32)
    from jsonschema import Draft202012Validator
    schema_root=repository/'apps/cipher/platform/apps/cipher_aec/cipher_aec/migrations/schemas'
    response_schema=json.loads((schema_root/'canonical-api-v1.schema.json').read_text())
    canonical_schema=json.loads((schema_root/'canonical-v1.schema.json').read_text())
    definitions={**response_schema['$defs'],'CanonicalManifest':canonical_schema}
    definitions['CanonicalExport']['properties']['manifest']={'$ref':'#/$defs/CanonicalManifest'}
    validator_root={'$schema':response_schema['$schema'],'$defs':definitions}
    response_validators={name:Draft202012Validator({**validator_root,'$ref':'#/$defs/'+schema}) for name,schema in
        (('validate_manifest','CanonicalValidation'),('preview_manifest','CanonicalPreview'),('export_records','CanonicalExport'))}
    checks=[]
    report={'schema':'cipher.r0.migration-http-acceptance.v1','status':'running','label':'actual-same-origin-session-http-read-only-canonical-tools',
            'project':project,'user':user,'origin':base_url,'checks':checks,'credentials_recorded':False}
    from http.cookiejar import CookieJar
    from urllib.error import HTTPError
    from urllib.parse import urlencode
    from urllib.request import Request, build_opener, HTTPCookieProcessor
    cookies=CookieJar()
    opener=build_opener(HTTPCookieProcessor(cookies))
    class Response:
        def __init__(self,status,body):
            self.status_code,self.body=status,body
        def json(self):
            return json.loads(self.body)
    class Session:
        headers={}
        def request(self,url,method,*,data=None,json_body=None,headers=None,timeout=20):
            request_headers={**self.headers,**(headers or {})}
            if json_body is not None:
                body=json.dumps(json_body).encode()
                request_headers['Content-Type']='application/json'
            elif data is not None:
                body=urlencode(data).encode()
                request_headers['Content-Type']='application/x-www-form-urlencoded'
            else:
                body=None
            request=Request(url,data=body,headers=request_headers,method=method)
            try:
                response=opener.open(request,timeout=timeout)
            except HTTPError as error:
                response=error
            with response:
                return Response(response.status,response.read())
        def post(self,url,*,data=None,json=None,headers=None,timeout=20):
            return self.request(url,'POST',data=data,json_body=json,headers=headers,timeout=timeout)
        def get(self,url,timeout=20):
            return self.request(url,'GET',timeout=timeout)
        def close(self):
            cookies.clear()
    session=Session()
    session.headers['Host']='cipher.localhost'

    def bench(method,kwargs,password_setup=False):
        args=prefix.copy()
        environment=os.environ.copy()
        if password_setup:
            args=[docker,'exec','-e','CIPHER_MIG_HTTP_PASSWORD','-w','/home/frappe/frappe-bench','cipher-r0-runtime-1','bench','--site','cipher.localhost','execute']
            environment['CIPHER_MIG_HTTP_PASSWORD']=password
        run=subprocess.run(args+[method,'--kwargs',json.dumps(kwargs)],cwd=repository,env=environment,capture_output=True,text=True,timeout=45)
        if run.returncode:
            raise AssertionError('Isolated MIG fixture bench setup failed; no credentials or raw diagnostics retained')
        return json.loads(run.stdout.strip().splitlines()[-1])

    def fixture(export=0,supplier_read=1,password_setup=False):
        return bench('cipher_aec.tests.test_migrations_acceptance.prepare_http_fixture',
            {'project':project,'user':user,'native_export':export,'supplier_read':supplier_read},password_setup)

    def rpc(name,payload,expected=200,csrf=True):
        headers={'X-Frappe-CSRF-Token':token} if csrf else {}
        response=session.post(base_url+'/api/method/cipher_aec.migrations.api.'+name,json=payload,headers=headers,timeout=20)
        body=response.json().get('message',{})
        assert response.status_code==expected,(name,response.status_code,expected,body.get('error',{}).get('code'))
        assert body.get('schema')=='cipher.api.v1' and isinstance(body.get('request_id'),str)
        if expected==200:
            assert 'data' in body and 'error' not in body
            response_validators[name].validate(body['data'])
        else:
            assert 'error' in body and 'data' not in body
        checks.append({'route':'cipher_aec.migrations.api.'+name,'http_status':response.status_code,'envelope':'cipher.api.v1',
                       'error_code':body.get('error',{}).get('code'),'csrf_header_sent':csrf})
        return body

    token=None
    try:
        prepared=fixture(password_setup=True)
        scope={'company':prepared['company'],'project':project}
        validate={**scope,'manifest':prepared['manifest']}
        export={**scope,'dataset_id':prepared['dataset_id'],'references':prepared['references'],
                'unit_conversions':prepared['unit_conversions'],'quantities':prepared['quantities']}
        login=session.post(base_url+'/api/method/login',data={'usr':user,'pwd':password},timeout=20)
        assert login.status_code==200
        signed=session.get(base_url+'/api/method/cipher_aec.api.v1.session',timeout=20).json()['message']
        assert signed['schema']=='cipher.api.v1' and signed['data']['user']==user
        token=signed['data']['csrf_token']
        assert isinstance(token,str) and token
        report['authenticated_fixture_session']=True
        rpc('validate_manifest',validate,400,csrf=False)
        validated=rpc('validate_manifest',validate)['data']
        assert validated['schema']=='cipher.canonical.validation.v1' and validated['valid']
        assert validated['writes_performed']==0 and not validated['target_existence_checked']
        preview=rpc('preview_manifest',validate)['data']
        assert preview['schema']=='cipher.canonical.preview.v1' and preview['writes_performed']==0
        assert all(r['action']==('declaration_candidate' if r['kind']=='uom' else 'matches') for r in preview['records'])
        assert not preview['apply_available']
        denied=rpc('export_records',export,404)
        assert denied['error']['code']=='target_unavailable'
        report['native_read_without_export_denied']=True

        fixture(export=1)
        exported=rpc('export_records',export)['data']
        assert exported['manifest']==prepared['manifest'] and exported['writes_performed']==0
        assert not exported['apply_available']
        report['successful_native_export_after_own_role_grant']=True
        report['export_manifest_sha256']=exported['manifest_sha256']

        fixture(export=0,supplier_read=0)
        private=rpc('preview_manifest',validate)['data']
        missing=copy.deepcopy(validate)
        next(r for r in missing['manifest']['records'] if r['kind']=='supplier')['target']['name']='MIG-01-missing-private-target'
        absent=rpc('preview_manifest',missing)['data']
        private_row=next(r for r in private['records'] if r['kind']=='supplier')
        absent_row=next(r for r in absent['records'] if r['kind']=='supplier')
        assert private_row==absent_row and private_row['action']=='unavailable'
        report['private_target_existence_indistinguishable']=True
        rpc('export_records',export,404)
        report['native_export_revocation_rechecked_in_same_session']=True

        bench('cipher_aec.install.set_synthetic_duty',{'user':user,'project':project,'ability':'project.read','active':0})
        for name,payload in (('validate_manifest',validate),('preview_manifest',validate),('export_records',export)):
            rpc(name,payload,404)
        report['current_project_duty_revocation_denies_all_three_routes']=True
        report['response_json_schemas_validated']=True
        report['status']='passed'
    finally:
        try:
            bench('cipher_aec.install.set_synthetic_duty',{'user':user,'project':project,'ability':'project.read','active':1})
            restored=fixture(export=0,supplier_read=1)
            if 'prepared' in locals():
                assert restored['source_versions']==prepared['source_versions']
                report['selected_native_records_unchanged']=True
        finally:
            if token:
                session.post(base_url+'/api/method/logout',headers={'X-Frappe-CSRF-Token':token},timeout=20)
            session.close()
    report['captured_at']=datetime.now(timezone.utc).isoformat()
    report['qualification_limits']=['Read-only contract routes only; no applied import/cutover.',
        'Export grants/revocations changed only this isolated fixture role; no ordinary product role or main fixture changed.']
    return report


if __name__=='__main__':
    report=run_http_acceptance()
    path=Path('apps/cipher/docs/framework/evidence/r0/migration-http-acceptance.json')
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
