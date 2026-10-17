"""Separate opt-in actual cookie/CSRF FIN01 HTTP acceptance.

Bench only provisions scoped synthetic masters and independently checks native
postings; all four public FIN APIs and baseline review/effect use actual HTTP.
No credentials are returned or recorded in evidence.
"""
import json
from pathlib import Path
from uuid import uuid4


def provision_http_fixture():
    import frappe
    from cipher_aec.governance.context import PROJECT_ABILITIES, assert_synthetic_site, current_actor, trusted_write
    from cipher_aec.install import _grant
    from cipher_aec.estimating.service import register_unit
    from frappe.permissions import add_permission, update_permission_property
    assert_synthetic_site()
    if frappe.session.user != 'Administrator':
        raise RuntimeError('Use synthetic bench Administrator for isolated HTTP fixture setup.')
    marker=uuid4().hex[:12]
    company='Cipher Synthetic Company'
    users=['morgan@cipher.example','morgan.alias@cipher.example','jordan@cipher.example']
    role='FIN01 HTTP source reader ' + marker
    with trusted_write():
        frappe.get_doc({'doctype':'Role','role_name':role}).insert(ignore_permissions=True)
        for doctype in ('Customer','UOM','Currency'):
            add_permission(doctype,role,0); update_permission_property(doctype,role,0,'read',1)
        for user in users:
            account=frappe.get_doc('User',user)
            assert role not in [row.role for row in account.roles]
            account.append('roles',{'role':role}); account.save(ignore_permissions=True)
        group=frappe.get_doc({'doctype':'Customer Group','customer_group_name':'FIN01 HTTP ' + marker,'parent_customer_group':'All Customer Groups','is_group':0}).insert(ignore_permissions=True)
        territory=frappe.get_doc({'doctype':'Territory','territory_name':'FIN01 HTTP ' + marker,'parent_territory':'All Territories','is_group':0}).insert(ignore_permissions=True)
        customer=frappe.get_doc({'doctype':'Customer','customer_name':'FIN01 HTTP source ' + marker,'customer_type':'Company','customer_group':group.name,'territory':territory.name}).insert(ignore_permissions=True)
        project=frappe.get_doc({'doctype':'Project','company':company,'project_name':'FIN01 HTTP explicit fixture ' + marker,'customer':customer.name,'status':'Open'}).insert(ignore_permissions=True)
        for user in ['Administrator',users[0]]:
            person=current_actor(user).person_id
            for ability in PROJECT_ABILITIES:
                _grant(person,company,project.name,ability)
        for ability in ('project.read','contract.read','document.read','approval.decide'):
            _grant(current_actor(users[2]).person_id,company,project.name,ability)
        unit_doc=frappe.get_doc({'doctype':'UOM','uom_name':'FIN01 HTTP quantity ' + marker,'symbol':'finhttp' + marker,'enabled':1,'must_be_whole_number':0}).insert(ignore_permissions=True)
    unit=register_unit(company,project.name,str(uuid4()),unit_doc.name,'count',6)['unit']
    frappe.db.commit()
    return {'company':company,'project':project.name,'customer':customer.name,'unit':unit,'role':role,'role_users':users,'marker':marker,
            'native_posting_before':native_posting_snapshot(project.name)}


def native_posting_snapshot(project):
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site
    assert_synthetic_site()
    if frappe.session.user != 'Administrator' or not str(frappe.db.get_value('Project',project,'project_name')).startswith('FIN01 HTTP explicit fixture '):
        raise RuntimeError('Only an isolated FIN01 HTTP fixture may be inspected.')
    company=frappe.db.get_value('Project',project,'company')
    from cipher_aec.governance.approvals import prevent_unsupported_financial_transition
    tables=('Sales Order','Sales Invoice','Delivery Note','Purchase Order','Purchase Invoice','Purchase Receipt','Payment Entry','Journal Entry','Stock Entry','Expense Claim','Timesheet','Material Request','GL Entry')
    result={}
    for table in tables:
        if not frappe.db.exists('DocType',table):
            result[table]={'installed':False}; continue
        meta=frappe.get_meta(table)
        result[table]={'installed':True,'rows':frappe.db.count(table,{'company':company} if meta.has_field('company') else {})}
    return result


def cleanup_http_fixture(project, role):
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site
    from cipher_aec.install import set_synthetic_duty
    assert_synthetic_site()
    if frappe.session.user != 'Administrator' or not str(frappe.db.get_value('Project',project,'project_name')).startswith('FIN01 HTTP explicit fixture '):
        raise RuntimeError('Only an isolated FIN01 HTTP fixture may be cleaned up.')
    marker=frappe.db.get_value('Project',project,'project_name').rsplit(' ',1)[1]
    if role != 'FIN01 HTTP source reader ' + marker:
        raise RuntimeError('Refusing removal of any pre-existing role.')
    removed=[]
    for user in ('morgan@cipher.example','morgan.alias@cipher.example','jordan@cipher.example'):
        account=frappe.get_doc('User',user)
        before=[row.role for row in account.roles]
        account.set('roles',[row for row in account.roles if row.role != role]); account.save(ignore_permissions=True)
        assert sorted(row.role for row in account.roles)==sorted(name for name in before if name != role)
        removed.append({'user':user,'temporary_role_removed':role not in [row.role for row in account.roles],'pre_existing_roles_preserved':True})
    for ability in ('contract.read','document.read'):
        set_synthetic_duty('morgan@cipher.example',project,ability,1)
    frappe.db.commit()
    return {'project':project,'cleanup':removed,'native_posting_after':native_posting_snapshot(project)}


def run_http_acceptance(repository=None, fixture_path='/tmp/cipher-r0-runtime/fixture.secret.json', output=None):
    import base64
    import hashlib
    import importlib.util
    import subprocess
    from datetime import datetime,timezone
    from jsonschema import Draft202012Validator, FormatChecker
    root=Path(repository or Path(__file__).resolve().parents[7])
    # __file__ parents[7] is repository root for .../apps/cipher/platform/apps/cipher_aec/cipher_aec/tests.
    spec=importlib.util.spec_from_file_location('cipher_actual_http_verifier',root/'apps/cipher/platform/operations/verify_r0.py')
    http=importlib.util.module_from_spec(spec);spec.loader.exec_module(http)
    fixture=json.loads(Path(fixture_path).read_text())
    docker=root/'apps/cipher/platform/deployment/docker-local.sh'
    def bench(function,kwargs=None):
        cmd=[str(docker),'exec','-w','/home/frappe/frappe-bench','cipher-r0-runtime-1','bench','--site','cipher.localhost','execute',function]
        if kwargs is not None:cmd += ['--kwargs',json.dumps(kwargs)]
        result=subprocess.run(cmd,check=True,capture_output=True,text=True,timeout=90)
        for line in reversed(result.stdout.splitlines()):
            try:
                value=json.loads(line)
                if isinstance(value,dict):return value
            except ValueError:pass
        raise RuntimeError('Bench fixture operation returned no safe JSON object.')
    context=bench('cipher_aec.tests.test_construction_finance_http_acceptance.provision_http_fixture')
    schema=json.loads((Path(__file__).resolve().parents[1]/'construction_finance/schemas/api-v1.schema.json').read_text())
    clients={};checks=[];validated=[];operations={};cleanup=None;failure=None
    prefix='cipher_aec.construction_finance.api.'
    scope={'company':context['company'],'project':context['project']}
    def check_schema(name,value):
        Draft202012Validator({'$defs':schema['$defs'],**schema['$defs'][name]},format_checker=FormatChecker()).validate(value);validated.append(name)
    def call(role,name,values=None,*,method='GET',status=(200,),schema_name=None):
        value=clients[role].api(name,values,method=method,expected=status,operation=(values or {}).get('operation_id') if method=='POST' else None)
        if schema_name:check_schema(schema_name,value)
        return value
    def duty(ability,active):
        return bench('cipher_aec.install.set_synthetic_duty',{'user':fixture['users']['primary']['user'],'project':context['project'],'ability':ability,'active':active})
    try:
        for role in ('primary','alias','reviewer','outsider'):
            client=http.Client(fixture['base_url'],fixture.get('host_header'));client.login(fixture['users'][role]);session=client.api('session')
            http.require(session['site_mode']=='synthetic','HTTP side effects require an explicit synthetic site.');client.csrf=session['csrf_token'];clients[role]=client
        http.require(clients['primary'].csrf and clients['reviewer'].csrf,'Real CSRF tokens must be obtained from signed-in sessions.')
        checks.append('actual_independent_cookie_sessions_and_server_csrf_tokens')
        definition={'number':'FIN01-HTTP-' + context['marker'],'kind':'prime','direction':'receivable','party_type':'Customer','party':context['customer'],'currency':'USD','original_value':{'amount':'1000.00','currency':'USD'}}
        create={**scope,'operation_id':str(uuid4()),'definition':definition};operations['create']=create['operation_id'];check_schema('CreateContractRequest',create)
        # A missing real CSRF token must fail before any contract effect.
        csrf=clients['primary'].csrf;clients['primary'].csrf=None
        clients['primary'].request('POST','/api/method/'+prefix+'create_contract',create,operation=create['operation_id'],expected=(400,403))
        clients['primary'].csrf=csrf
        created=call('primary',prefix+'create_contract',create,method='POST',schema_name='CreateContractResponse')
        aliased=call('alias',prefix+'create_contract',create,method='POST',schema_name='CreateContractResponse')
        http.require(aliased['operation']['replayed'] and aliased['contract']['id']==created['contract']['id'],'Canonical alias retry created another contract.')
        changed={**create,'definition':{**definition,'number':definition['number']+'-changed'}}
        call('primary',prefix+'create_contract',changed,method='POST',status=(409,))
        checks.append('csrf_guard_exact_create_schema_alias_replay_and_payload_conflict')
        content=('Explicit synthetic HTTP contract source; USD1000.00 cap; authored SOV and retainage only. No legal execution, certification or posting.').encode()
        upload={**scope,'operation_id':str(uuid4()),'title':'FIN01 HTTP source '+context['marker'],'filename':'fin01-http-source.txt','content_base64':base64.b64encode(content).decode(),'byte_length':len(content),'sha256':hashlib.sha256(content).hexdigest()}
        uploaded=call('primary','cipher_aec.documents.api.upload_document',upload,method='POST')
        citation=call('primary','cipher_aec.documents.api.get_citation',{'company':context['company'],'revision_id':uploaded['revision']['id'],'page':1})
        source={key:citation[key] for key in ('revision_id','page','excerpt_sha256','source_sha256')}
        terms={'billing_method':'lump_sum','effective_date':'2026-10-15','end_date':None,'terms_text':'Explicit authored HTTP fixture terms, not legally executed.'}
        policy={'basis':'installed_plus_eligible_stored','tiers':[{'up_to':None,'rate':'0.05'}],'cap':None,'effective_date':'2026-10-15','rounding':'HALF_UP','reduction_conditions':'Qualified governed change required','release_conditions':'Future qualified retainage release','approval_basis':'Explicit synthetic fixture policy'}
        line={'line_id':str(uuid4()),'item_code':'HTTP-SOV-001','description':'Explicit HTTP authored SOV','quantity':{'amount':'10.000001','unit_id':context['unit']['id'],'precision':6},'scheduled_amount':{'amount':'100.01','currency':'USD'},'cost_code':'HTTP-FOUND','stored_material_eligible':True,'source_line_id':None}
        author={**scope,'operation_id':str(uuid4()),'contract_id':created['contract']['id'],'expected_version':created['version'],'terms':terms,'retainage_policy':policy,'lines':[line],'source_citations':[source]};operations['author']=author['operation_id'];check_schema('AuthorContractRevisionRequest',author)
        authored=call('primary',prefix+'author_revision',author,method='POST',schema_name='AuthorContractRevisionResponse')
        retry=call('alias',prefix+'author_revision',author,method='POST',schema_name='AuthorContractRevisionResponse')
        http.require(retry['operation']['replayed'] and retry['sov']['id']==authored['sov']['id'],'Revision alias replay produced another SOV.')
        call('primary',prefix+'author_revision',{**author,'operation_id':str(uuid4())},method='POST',status=(412,))
        get={**scope,'kind':'sov','record_id':authored['sov']['id']};check_schema('GetContractRecordRequest',get)
        restored=call('primary',prefix+'get_record',get,schema_name='GetContractRecordResponse');http.require(restored['record']==authored['sov'],'HTTP immutable SOV changed.')
        listing=call('primary',prefix+'list_contracts',{**scope,'limit':1,'count_mode':'exact'},schema_name='ListContractsResponse')
        http.require(listing['total']==1 and listing['next_cursor'] is None,'Retries/stale request created another contract.')
        checks.append('four_fin_public_apis_exact_schemas_and_stale_single_revision_protection')
        for endpoint,args in ((prefix+'get_record',get),(prefix+'list_contracts',scope)):
            call('outsider',endpoint,args,status=(404,))
        call('outsider',prefix+'author_revision',{**author,'operation_id':str(uuid4()),'expected_version':authored['version']},method='POST',status=(404,))
        checks.append('independent_outsider_denied_resources_collections_and_effects')
        request={**scope,'action':'contract.baseline.activate.v1','subject_id':created['contract']['id'],'expected_version':authored['version'],'operation_id':str(uuid4())}
        packet=call('primary','cipher_aec.api.approvals.request_action',request,method='POST')['packet']
        decision={**scope,'packet_id':packet['id'],'manifest_hash':packet['manifest_hash'],'decision':'Grant','reason':'Independent actual HTTP review of the exact authored synthetic baseline','operation_id':str(uuid4())}
        call('alias','cipher_aec.api.approvals.decide_packet',decision,method='POST',status=(403,))
        decision['operation_id']=str(uuid4());granted=call('reviewer','cipher_aec.api.approvals.decide_packet',decision,method='POST')
        http.require(granted['packet']['state']=='Granted','Independent actual HTTP grant was not persisted.')
        header=call('primary',prefix+'get_record',{**scope,'kind':'contract','record_id':created['contract']['id']},schema_name='GetContractRecordResponse')
        http.require(header['record']['accepted_revision'] is None,'Review alone advanced the baseline.')
        execute={**scope,'packet_id':packet['id'],'manifest_hash':packet['manifest_hash'],'operation_id':str(uuid4())};operations['execute']=execute['operation_id']
        accepted=call('primary','cipher_aec.api.approvals.execute_packet',execute,method='POST')
        replay=call('alias','cipher_aec.api.approvals.execute_packet',execute,method='POST')
        http.require(replay['operation']['replayed'] and accepted['packet']['state']=='Consumed','Actual HTTP grant consumption was not replay-safe.')
        http.require(accepted['effect']['accepted_revision']==authored['revision']['id'] and all(accepted['effect'][key] is False for key in ('legal_execution','certification','posting')),'Acceptance implied an unqualified financial/legal effect.')
        checks.append('independent_actual_http_review_one_baseline_consumption_and_alias_retry')
        # Retain Project read while revoking source-specific and contract rights.
        duty('document.read',0)
        call('primary',prefix+'get_record',get,status=(403,));call('primary',prefix+'author_revision',author,method='POST',status=(403,))
        call('primary','operation',{**scope,'operation_id':author['operation_id']},status=(403,));call('primary','cipher_aec.api.approvals.read_packet',{**scope,'packet_id':packet['id']},status=(403,))
        call('alias','cipher_aec.api.approvals.execute_packet',execute,method='POST',status=(403,));duty('document.read',1)
        duty('contract.read',0)
        call('primary',prefix+'get_record',{**scope,'kind':'contract','record_id':created['contract']['id']},status=(403,));call('alias',prefix+'create_contract',create,method='POST',status=(403,))
        call('primary','operation',{**scope,'operation_id':create['operation_id']},status=(403,));duty('contract.read',1)
        checks.append('current_scoped_contract_and_source_revocation_denies_resources_old_receipts_and_consumed_packets')
        call('primary',prefix+'get_record',get,schema_name='GetContractRecordResponse')
        call('primary','cipher_aec.api.approvals.read_packet',{**scope,'packet_id':packet['id']})
    except Exception as exc:
        failure=str(exc) if isinstance(exc,http.CheckFailure) else type(exc).__name__
    finally:
        cleanup=bench('cipher_aec.tests.test_construction_finance_http_acceptance.cleanup_http_fixture',{'project':context['project'],'role':context['role']})
    unchanged=cleanup['native_posting_after']==context['native_posting_before']
    if not unchanged:failure=failure or 'Independent native financial/activity/GL row counts changed.'
    if not all(row['temporary_role_removed'] and row['pre_existing_roles_preserved'] for row in cleanup['cleanup']):failure=failure or 'Temporary role cleanup failed.'
    checks.append('independent_bench_native_posting_counts_unchanged_and_temporary_role_cleanup')
    sourcefiles=[Path(__file__),Path(__file__).resolve().parents[1]/'construction_finance/schemas/api-v1.schema.json']
    result={'schema':'cipher.finance.http-acceptance.v1','executed_at':datetime.now(timezone.utc).isoformat(),'status':'failed' if failure else 'passed','failure':failure,'scope':scope,
      'checks':checks,'request_count':sum(len(c.observations) for c in clients.values()),'requests':{role:c.observations for role,c in clients.items()},
      'validated_schema_samples':len(validated),'validated_schema_definitions':sorted(set(validated)),'operations':operations,'cleanup':cleanup,'native_posting_before':context['native_posting_before'],'native_posting_unchanged':unchanged,
      'source_sha256':{str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sourcefiles},
      'legal_execution':False,'certification':False,'financial_posting':False,'floor_provider_qualified':False,'live_model_qualified':False,
      'qualification':'Actual independent cookie/CSRF HTTP for FIN/GOV; isolated synthetic masters and independent readback/temporary duty changes use authenticated bench. No live external provider.'}
    if output:Path(output).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result


def prepare_history_fixture(project):
    """Reuse the exact already-created source role; no new User or authority."""
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site
    assert_synthetic_site()
    title=str(frappe.db.get_value('Project',project,'project_name'))
    if frappe.session.user!='Administrator' or not title.startswith('FIN01 HTTP explicit fixture '):
        raise RuntimeError('Only an existing isolated FIN01 HTTP fixture may be prepared.')
    marker=title.rsplit(' ',1)[1];role='FIN01 HTTP source reader '+marker
    assert frappe.db.exists('Role',role)
    for user in ('morgan@cipher.example','morgan.alias@cipher.example','jordan@cipher.example'):
        account=frappe.get_doc('User',user)
        if role not in [row.role for row in account.roles]:
            account.append('roles',{'role':role});account.save(ignore_permissions=True)
    frappe.db.commit()
    return {'project':project,'company':frappe.db.get_value('Project',project,'company'),'role':role}


def set_history_fixture_party_binding(project, enabled):
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site, trusted_write
    assert_synthetic_site()
    title=str(frappe.db.get_value('Project',project,'project_name'))
    if frappe.session.user!='Administrator' or not title.startswith('FIN01 HTTP explicit fixture ') or enabled not in (0,1):
        raise RuntimeError('Only an existing isolated FIN01 HTTP source binding may be changed.')
    customer='FIN01 HTTP source '+title.rsplit(' ',1)[1]
    assert frappe.db.exists('Customer',customer)
    assert not frappe.get_doc('Customer',customer).get('accounts')
    with trusted_write():
        doc=frappe.get_doc('Project',project);doc.customer=customer if enabled else None;doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {'project':project,'native_party_company_association_restored':bool(enabled)}


def run_history_http_acceptance(repository=None, fixture_path='/tmp/cipher-r0-runtime/fixture.secret.json', project='PROJ-0030', output=None):
    import hashlib
    import importlib.util
    import subprocess
    from datetime import datetime,timezone
    root=Path(repository or Path(__file__).resolve().parents[7])
    spec=importlib.util.spec_from_file_location('cipher_fin_history_http',root/'apps/cipher/platform/operations/verify_r0.py')
    http=importlib.util.module_from_spec(spec);spec.loader.exec_module(http)
    fixture=json.loads(Path(fixture_path).read_text())
    def bench(function,kwargs):
        command=[str(root/'apps/cipher/platform/deployment/docker-local.sh'),'exec','-w','/home/frappe/frappe-bench','cipher-r0-runtime-1','bench','--site','cipher.localhost','execute',function,'--kwargs',json.dumps(kwargs)]
        completed=subprocess.run(command,check=True,capture_output=True,text=True,timeout=90)
        for line in reversed(completed.stdout.splitlines()):
            try:
                value=json.loads(line)
                if isinstance(value,dict):return value
            except ValueError:pass
        raise RuntimeError('No safe fixture result.')
    context=bench('cipher_aec.tests.test_construction_finance_http_acceptance.prepare_history_fixture',{'project':project})
    clients={};phases=[];failure=None;cleanup=None
    scope={'company':context['company'],'project':project}
    def history(role,limit=200):
        data=clients[role].api('history',{**scope,'limit':limit,'count_mode':'exact'})
        if limit==200:
            http.require(data['total']==len(data['items']) and data['next_cursor'] is None,'Exact history count/cursor included hidden records.')
        return data
    def duty(active):
        return bench('cipher_aec.install.set_synthetic_duty',{'user':fixture['users']['primary']['user'],'project':project,'ability':'document.read','active':active})
    try:
        for role in ('primary','alias'):
            client=http.Client(fixture['base_url'],fixture.get('host_header'));client.login(fixture['users'][role]);session=client.api('session');http.require(session['site_mode']=='synthetic','Synthetic guard failed.');client.csrf=session['csrf_token'];clients[role]=client
        baseline=history('primary');baseline_ids={row['id'] for row in baseline['items']}
        source_ids={row['id'] for row in baseline['items'] if row['event']=='contract.revision.authored' or row['subject_type']=='Cipher Approval Packet'}
        fin_ids={row['id'] for row in baseline['items'] if row['subject_type'].startswith('Cipher Construction') or row['event'].startswith('contract.') or row['subject_type']=='Cipher Approval Packet'}
        http.require(any(row['event']=='contract.revision.authored' for row in baseline['items']) and any(row['subject_type']=='Cipher Approval Packet' for row in baseline['items']),'Expected previously persisted FIN and approval subjects are absent.')
        phases.append({'phase':'authorized','total':baseline['total'],'history_ids':sorted(baseline_ids)})
        duty(0)
        for role in clients:
            revoked=history(role);revoked_ids={row['id'] for row in revoked['items']}
            http.require(not source_ids & revoked_ids,'Source-revoked history exposed exact old revision or approval event.')
            http.require(revoked['total']==baseline['total']-len(baseline_ids-revoked_ids),'Source-denied event count was not filtered.')
            first=history(role,1);http.require(bool(first['next_cursor'])==(revoked['total']>1),'Cursor revealed hidden off-page event.')
            phases.append({'phase':'document_read_revoked','role':role,'total':revoked['total'],'visible_ids':sorted(revoked_ids)})
        duty(1)
        bench('cipher_aec.tests.test_construction_finance_http_acceptance.set_history_fixture_party_binding',{'project':project,'enabled':0})
        for role in clients:
            revoked=history(role);revoked_ids={row['id'] for row in revoked['items']}
            http.require(not fin_ids & revoked_ids,'Revoked native-party association exposed FIN/approval history.')
            first=history(role,1);http.require(bool(first['next_cursor'])==(revoked['total']>1),'Party-denied event leaked via cursor.')
            phases.append({'phase':'native_party_association_revoked','role':role,'total':revoked['total'],'visible_ids':sorted(revoked_ids)})
        bench('cipher_aec.tests.test_construction_finance_http_acceptance.set_history_fixture_party_binding',{'project':project,'enabled':1})
        for role in clients:
            restored=history(role);http.require({row['id'] for row in restored['items']}==baseline_ids and restored['total']==baseline['total'],'Restoration did not recover exact original event identities/count.')
            phases.append({'phase':'restored','role':role,'total':restored['total']})
    except Exception as exc:
        failure=str(exc) if isinstance(exc,http.CheckFailure) else type(exc).__name__
    finally:
        bench('cipher_aec.tests.test_construction_finance_http_acceptance.set_history_fixture_party_binding',{'project':project,'enabled':1})
        cleanup=bench('cipher_aec.tests.test_construction_finance_http_acceptance.cleanup_http_fixture',{'project':project,'role':context['role']})
    sources=[Path(__file__),root/'apps/cipher/platform/apps/cipher_aec/cipher_aec/governance/history_access.py',root/'apps/cipher/platform/apps/cipher_aec/cipher_aec/governance/history_listing.py',root/'apps/cipher/platform/apps/cipher_aec/cipher_aec/construction_finance/service.py']
    report={'schema':'cipher.finance.http-history-acceptance.v1','executed_at':datetime.now(timezone.utc).isoformat(),'status':'failed' if failure else 'passed','failure':failure,'scope':scope,'phases':phases,
            'request_count':sum(len(client.observations) for client in clients.values()),'requests':{role:client.observations for role,client in clients.items()},
            'source_sha256':{str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},'cleanup':cleanup,
            'qualification':'Actual cookie/CSRF history HTTP; existing isolated fixture only. Temporary source duty/native-company association toggles and unique-role cleanup use authenticated bench. No new business effects, Users or financial posting.'}
    if output:Path(output).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    return report
