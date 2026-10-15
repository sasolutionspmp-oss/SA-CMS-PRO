"""Independent actual Company prepared-artifact/Issue HTTP acceptance.

Opt-in and site-bound: consumes the root-coordinated private Company fixture.
This module provisions no identity, enables no action, and sends no external mail.
"""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def _private_json(path,value):
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as stream:
        json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())


def _rpc(private_manifest,repository,base_url,private_directory):
    from .test_company_chain_http_acceptance import CompanyHTTPRPC
    fixture=json.loads(Path(private_manifest).read_text())
    if fixture.get('setup_status')!='ready':raise RuntimeError('Only the ready explicit Company fixture may be used.')
    return fixture,CompanyHTTPRPC(fixture,repository=repository,base_url=base_url,private_directory=private_directory)


def _pdf(rpc,prepared):
    method='cipher_aec.documents.company_api.download_revision'
    status,payload,content,headers=rpc.clients[rpc.role].request('GET','/api/method/'+method,
        {'company':prepared['company'],'revision_id':prepared['revision_id']},expected=(200,))
    if not content.startswith(b'%PDF-') or len(content)!=prepared['byte_length'] or hashlib.sha256(content).hexdigest()!=prepared['source_sha256'] or 'attachment' not in headers.get('Content-Disposition','').lower():
        raise AssertionError('Actual canonical prepared PDF bytes differ from the reviewed artifact facts.')
    rpc.calls.append({'role':rpc.role,'method':method,'http_status':status,'source_sha256':prepared['source_sha256'],'byte_length':len(content)})
    return content


def drive_prepared_output(rpc,fixture,source):
    from cipher_aec.api.contracts import digest
    company=fixture['company'];com='cipher_aec.commercial.api.';docs='cipher_aec.documents.company_api.'
    if source['company']!=company:raise RuntimeError('The exact accepted source must belong to the owned Company.')
    marker='QA-COM02-'+uuid4().hex[:12];unit=source['qualified_unit']
    reference={**source['source_reference'],'purpose':'Explicit Company proposal source '+marker,
               'permission_basis':'Authored synthetic fixture; canonical exact page and accepted baseline independently qualified.'}
    baseline={key:source[key] for key in ('acceptance_id','acceptance_digest','revision_id','revision_digest')}
    composition={'currency':'USD','price_list':source['native']['price_list'],'valid_till':'2026-12-31',
        'terms':'Synthetic commercial terms '+marker+'; no legal execution or transmission.',
        'sections':[{'id':str(uuid4()),'kind':'scope','title':marker,'text':'Explicit manual Company quantity2.500000 at USD12.34; exactUSD30.85.'}],
        'price_lines':[{'id':str(uuid4()),'description':'Authored material '+marker,'quantity':'2.500000','unit_id':unit['id'],
                        'unit_revision':unit['revision'],'rate':'12.34','item_code':source['native']['item'],'selected':True}],
        'source_references':[reference],'estimate_reference':baseline}
    create={'company':company,'pursuit_id':source['pursuit_id'],'composition':composition,'operation_id':str(uuid4())}
    rpc.login('author');created=rpc.invoke(com+'create_proposal',create)
    if created['revision']['accepted_estimate']['acceptance_id']!=source['acceptance_id'] or created['revision']['pricing']['total']!='30.85':
        raise AssertionError('The proposal lost the exact accepted manual baseline or exact commercial total.')
    rpc.login('alias');replay=rpc.invoke(com+'create_proposal',create)
    if not replay['operation']['replayed'] or replay['revision']!=created['revision']:
        raise AssertionError('Canonical alias retry duplicated or retargeted a Company proposal.')
    changed=deepcopy(create);changed['composition']['terms']+=' changed'
    rpc.invoke(com+'create_proposal',changed,expected_codes={'operation_conflict'})
    revision=created['revision'];proposal=created['proposal']
    prepare={'company':company,'proposal_id':proposal['id'],'revision_id':revision['id'],'expected_revision_digest':digest(revision),
             'recipients':[{'name':'Synthetic recipient','email':'qa.recipient@cipher.example','organization':'Explicit local qualification'}],
             'cover':'Intended recipient only; no transmission. '+marker,'operation_id':str(uuid4())}
    rpc.login('author');prepared=rpc.invoke(com+'prepare_proposal_output',prepare)['prepared_output']
    if prepared['binding']['accepted_estimate']!=revision['accepted_estimate'] or prepared['proposal_revision_digest']!=digest(revision):
        raise AssertionError('Prepared output did not bind the exact accepted baseline/proposal revision.')
    content=_pdf(rpc,prepared)
    if rpc.invoke(com+'prepared_output',{'company':company,'revision_id':revision['id']})!=prepared:
        raise AssertionError('Prepared canonical output changed at ordinary readback.')
    rpc.login('alias');retry=rpc.invoke(com+'prepare_proposal_output',prepare)
    if not retry['operation']['replayed'] or retry['prepared_output']!=prepared:raise AssertionError('Prepared output alias retry created different bytes/binding.')
    altered=deepcopy(prepare);altered['cover']+=' unseen change'
    rpc.invoke(com+'prepare_proposal_output',altered,expected_codes={'operation_conflict'})
    altered['operation_id']=str(uuid4())
    rpc.invoke(com+'prepare_proposal_output',altered,expected_codes={'output_already_prepared'})
    rpc.login('author')
    detail=rpc.invoke(docs+'get_document',{'company':company,'document_id':prepared['document_id']})
    if detail['document']['scope_type']!='Company' or detail['document']['project'] is not None or detail['revisions'][0]['id']!=prepared['revision_id']:
        raise AssertionError('Prepared output did not use canonical no-Project Company document identity.')
    text=''.join(rpc.invoke(docs+'preview_revision',{'company':company,'revision_id':prepared['revision_id'],'page':page})['text'] for page in range(1,prepared['page_count']+1))
    if marker not in text or '30.85' not in text:raise AssertionError('Actual extracted PDF pages lost the explicit proposal content/amount.')
    citation=rpc.invoke(docs+'get_citation',{'company':company,'revision_id':prepared['revision_id'],'page':1})
    if citation['source_sha256']!=prepared['source_sha256']:raise AssertionError('Prepared output citation changed original byte identity.')
    listing=rpc.invoke(docs+'list_documents',{'company':company})
    if prepared['document_id'] not in {item['id'] for item in listing['items']}:raise AssertionError('Authorized Company list omitted prepared output.')
    search=rpc.invoke(docs+'search_documents',{'company':company,'query':marker,'limit':20})
    if prepared['revision_id'] not in {item['revision_id'] for item in search['items']}:raise AssertionError('Canonical search omitted the exact rendered unique content.')
    for role in ('outsider','project_only'):
        rpc.login(role)
        rpc.invoke(com+'prepared_output',{'company':company,'revision_id':revision['id']},expected_codes={'not_found','capability_denied'})
        rpc.invoke(docs+'get_document',{'company':company,'document_id':prepared['document_id']},expected_codes={'not_found','capability_denied'})
    rpc.login('author')
    return {'company':company,'marker':marker,'proposal':proposal,'revision':revision,'create':create,'prepare':prepare,'prepared_output':prepared,
            'output_pdf_sha256':hashlib.sha256(content).hexdigest(),'output_pdf_byte_length':len(content),'citation':citation,
            'checks':['same_pursuit_exact_accepted_manual_baseline_and_native_draft','canonical_alias_proposal_and_preparation_replay',
                      'one_prepared_artifact_per_revision_cover_changes_require_successor','actual_canonical_pdf_pages_citation_search_and_bytes','outsider_and_project_only_denied'],
            'issue_qualified':False,'distribution_qualified':False,'live_external_provider_qualified':False}


def run_prepared_output_http(private_manifest,*,source_manifest,repository,base_url,private_directory):
    fixture,rpc=_rpc(private_manifest,repository,base_url,private_directory)
    report={'schema':'cipher.r1.company-prepared-output-http.v1','status':'failed','fixture_id':fixture['fixture_id'],
            'started_at':datetime.now(timezone.utc).isoformat(),'issue_qualified':False,'distribution_qualified':False,'live_external_provider_qualified':False}
    try:
        context=drive_prepared_output(rpc,fixture,json.loads(Path(source_manifest).read_text()))
        _private_json(rpc.work/'prepared-output-http-context.json',context)
        report.update(status='passed',company=context['company'],proposal_id=context['proposal']['id'],proposal_revision_id=context['revision']['id'],
                      prepared_output=context['prepared_output'],checks=context['checks'])
        return report
    except Exception as error:report['failure_type']=type(error).__name__;raise
    finally:
        rpc.close();report['calls']=rpc.calls;report['schema_samples']=rpc.schema_samples;report['completed_at']=datetime.now(timezone.utc).isoformat()
        _private_json(rpc.work/('prepared-output-http-'+uuid4().hex+'.result.json'),report)


def run_generated_source_revocation_http(private_manifest,*,context_file,manual_context_file,source_manifest,repository,base_url,
                                         private_directory,bench_private_manifest,container='cipher-r0-runtime-1',site='cipher.localhost'):
    """Actual derived-source refusal while Company document.read stays granted."""
    import subprocess
    from .test_company_chain_acceptance import company_history_inventory
    fixture,rpc=_rpc(private_manifest,repository,base_url,private_directory)
    context=json.loads(Path(context_file).read_text());manual=json.loads(Path(manual_context_file).read_text())['context']
    source=json.loads(Path(source_manifest).read_text());company=fixture['company'];prepared=context['prepared_output']
    if context['company']!=company or source['company']!=company:raise RuntimeError('Use only the owned Company generated source.')
    docs='cipher_aec.documents.company_api.';com='cipher_aec.commercial.api.';denied={'not_found','capability_denied'}
    def bench(name,values):
        command=[str(Path(repository)/'apps/cipher/platform/deployment/docker-local.sh'),'exec','--workdir','/home/frappe/frappe-bench',container,
                 'bench','--site',site,'execute','cipher_aec.tests.test_company_chain_acceptance.'+name,'--kwargs',repr(values)]
        result=subprocess.run(command,capture_output=True,text=True,timeout=60,check=False)
        if result.returncode:raise RuntimeError('Owned synthetic '+name+' failed; no captured values are published.')
        return json.loads(result.stdout)
    def projection(role,blocked):
        return bench('fixture_generated_projection',{'private_manifest':bench_private_manifest,'document_id':prepared['document_id'],'role':role,'denied':blocked})
    def inventory(role):
        rpc.login(role)
        actual=rpc.invoke(com+'prepared_output',{'company':company,'revision_id':context['revision']['id']})
        if actual!=prepared:raise AssertionError('The immutable prepared-source binding changed.')
        _pdf(rpc,prepared)
        return company_history_inventory(rpc,company)
    def assert_denied(role):
        rpc.login(role)
        for method,values in ((com+'prepared_output',{'company':company,'revision_id':context['revision']['id']}),
                              (docs+'get_document',{'company':company,'document_id':prepared['document_id']}),
                              (docs+'preview_revision',{'company':company,'revision_id':prepared['revision_id'],'page':1}),
                              (docs+'get_citation',{'company':company,'revision_id':prepared['revision_id'],'page':1}),
                              (docs+'download_revision',{'company':company,'revision_id':prepared['revision_id']})):
            rpc.invoke(method,values,expected_codes=denied)
        listed=rpc.invoke(docs+'list_documents',{'company':company})
        if prepared['document_id'] in {row['id'] for row in listed['items']}:raise AssertionError('Derived-source list leaked a native/commercial-denied output.')
        searched=rpc.invoke(docs+'search_documents',{'company':company,'query':context['marker'],'limit':20})
        if searched['items']:raise AssertionError('Derived-source search exposed native/commercial-denied generated text.')
        # Raw source remains readable: document.read itself was never revoked.
        raw=rpc.invoke(docs+'get_citation',{'company':company,'revision_id':source['source_reference']['revision_id'],'page':source['source_reference']['page']})
        if raw['source_sha256']!=source['source_reference']['source_sha256']:raise AssertionError('The derived-source phase accidentally revoked raw document access.')
        history=company_history_inventory(rpc,company)
        if {prepared['revision_id'],context['revision']['id']}.intersection(row['subject_id'] for row in history['items']):
            raise AssertionError('Derived-source history exposed the protected output/revision.')
        return {'visible_history_count':history['total'],'raw_source_and_document_read_retained':True,'native_projection':projection(role,True)}
    report={'schema':'cipher.r1.generated-source-http-revocation.v1','status':'failed','fixture_id':fixture['fixture_id'],'company':company,
            'started_at':datetime.now(timezone.utc).isoformat(),'issue_qualified':False,'distribution_qualified':False,'live_external_provider_qualified':False,
            'qualification':'Actual cookie/CSRF APIs; native SQL count/Long Text projection is separately identified bench readback under the same current role. No User/Auth writes.'}
    try:
        reviewer_before=inventory('reviewer');report['reviewer_native_before']=projection('reviewer',False)
        receipt=manual['reviewer_decision'];rpc.invoke('cipher_aec.api.company.operation',{'company':company,'operation_id':receipt['operation_id']})
        try:
            bench('set_fixture_reviewer_native_permission',{'private_manifest':bench_private_manifest,'doctype':'Customer','active':0})
            report['reviewer_customer_revoked']=assert_denied('reviewer')
            rpc.invoke('cipher_aec.api.company.operation',{'company':company,'operation_id':receipt['operation_id']},expected_codes=denied)
            rpc.invoke('cipher_aec.api.company_approvals.decide_packet',receipt,expected_codes=denied)
        finally:
            report['reviewer_customer_restored']=bench('set_fixture_reviewer_native_permission',{'private_manifest':bench_private_manifest,'doctype':'Customer','active':1})
        if inventory('reviewer')!=reviewer_before:raise AssertionError('Reviewer Customer restoration did not recover the exact original historical set.')
        report['reviewer_native_after']=projection('reviewer',False)
        author_before=inventory('author');report['author_native_before']=projection('author',False)
        try:
            bench('set_fixture_duty',{'private_manifest':bench_private_manifest,'role':'author','ability':'commercial.read','active':0})
            report['author_commercial_revoked']=assert_denied('author')
            rpc.invoke('cipher_aec.api.company.operation',{'company':company,'operation_id':context['prepare']['operation_id']},expected_codes=denied)
            rpc.invoke(com+'prepare_proposal_output',context['prepare'],expected_codes=denied)
            rpc.login('alias');rpc.invoke(com+'prepare_proposal_output',context['prepare'],expected_codes=denied)
        finally:
            report['author_commercial_restored']=bench('set_fixture_duty',{'private_manifest':bench_private_manifest,'role':'author','ability':'commercial.read','active':1})
        if inventory('author')!=author_before:raise AssertionError('Author commercial restoration did not recover exact historical source access.')
        report['author_native_after']=projection('author',False)
        rpc.login('alias');replay=rpc.invoke(com+'prepare_proposal_output',context['prepare'])
        if not replay['operation']['replayed'] or replay['prepared_output']!=prepared:raise AssertionError('Restored exact original preparation receipt did not replay.')
        report.update(status='passed',original_preparation_replayed_after_restore=True,original_pdf_sha256=prepared['source_sha256'],
                      reviewer_history_before=reviewer_before['total'],author_history_before=author_before['total'])
        return report
    except Exception as error:report['failure_type']=type(error).__name__;raise
    finally:
        rpc.close();report['calls']=rpc.calls;report['schema_samples']=rpc.schema_samples;report['completed_at']=datetime.now(timezone.utc).isoformat()
        _private_json(rpc.work/('generated-source-revocation-'+uuid4().hex+'.result.json'),report)


def run_issue_http(private_manifest,*,context_file,repository,base_url,private_directory):
    """Only after root enables/migrates the literal Issue action; no delivery."""
    from cipher_aec.api.contracts import digest
    fixture,rpc=_rpc(private_manifest,repository,base_url,private_directory)
    context=json.loads(Path(context_file).read_text());company=fixture['company'];prepared=context['prepared_output']
    if context['company']!=company:raise RuntimeError('Use the existing owned independent preparation.')
    gov='cipher_aec.api.company_approvals.';com='cipher_aec.commercial.api.'
    report={'schema':'cipher.r1.company-issue-http.v1','status':'failed','fixture_id':fixture['fixture_id'],'company':company,
            'started_at':datetime.now(timezone.utc).isoformat(),'distribution_qualified':False,'live_external_provider_qualified':False,
            'qualification':'Actual cookie/CSRF independent approved Issue; immutable PDF exists before review. No mail/provider or native quotation submission.'}
    def request(revision,output):
        return rpc.invoke(gov+'request_action',{'company':company,'action':'proposal.issue.v1','subject_id':revision['id'],
            'expected_version':output['review_version'],'operation_id':str(uuid4())})['packet']
    def grant(packet):
        decision={'company':company,'packet_id':packet['id'],'manifest_hash':packet['manifest_hash'],'decision':'Grant',
                  'reason':'Independent exact rendered-artifact synthetic review','operation_id':str(uuid4())}
        rpc.login('alias');rpc.invoke(gov+'decide_packet',decision,expected_codes={'independent_proposal_required','independent_review_required'})
        rpc.login('reviewer');decision['operation_id']=str(uuid4());result=rpc.invoke(gov+'decide_packet',decision)
        if result['packet']['state']!='Granted':raise AssertionError('Independent generated-artifact review was not granted.')
        rpc.login('author');return decision
    try:
        rpc.login('author')
        current=rpc.invoke(com+'prepared_output',{'company':company,'revision_id':context['revision']['id']})
        if current!=prepared:raise AssertionError('Prepared output changed before the exact Issue review.')
        original_pdf=_pdf(rpc,prepared)
        packet=request(context['revision'],prepared);decision=grant(packet)
        execute={'company':company,'packet_id':packet['id'],'manifest_hash':packet['manifest_hash'],'operation_id':str(uuid4())}
        consumed=rpc.invoke(gov+'execute_packet',execute);issue=consumed['effect']['issue']
        if consumed['packet']['state']!='Consumed' or issue['prepared_output']!=prepared or issue['output_revision']!=prepared['revision_id'] or issue['distribution']!='not-sent' or issue['native_snapshot']['docstatus']!=0:
            raise AssertionError('Issue did not preserve the reviewed exact artifact and draft/no-send standing.')
        rpc.login('alias');retry=rpc.invoke(gov+'execute_packet',execute)
        if not retry['operation']['replayed'] or retry['effect']['issue']!=issue:raise AssertionError('Issue alias retry duplicated or changed its effect.')
        rpc.login('reviewer')
        if rpc.invoke(com+'issue',{'company':company,'issue_id':issue['id']})!=issue:raise AssertionError('Independent authorized Issue readback changed.')
        rpc.login('author')
        # A legitimate working successor is distinct from the already issued
        # immutable commercial/native/PDF snapshot.
        composition=deepcopy(context['revision']['composition']);composition['terms']+=' Explicit successor after first immutable Issue.'
        next_revision=rpc.invoke(com+'save_proposal_revision',{'company':company,'proposal_id':context['proposal']['id'],
            'expected_revision':context['revision']['revision_number'],'expected_native_fingerprint':context['revision']['native_fingerprint'],
            'composition':composition,'operation_id':str(uuid4())})
        second=next_revision['revision']
        prepare={**context['prepare'],'revision_id':second['id'],'expected_revision_digest':digest(second),'operation_id':str(uuid4())}
        prepared_second=rpc.invoke(com+'prepare_proposal_output',prepare)['prepared_output']
        stale_packet=request(second,prepared_second);grant(stale_packet)
        composition=deepcopy(second['composition']);composition['terms']+=' Supported successor invalidates pending grant.'
        third=rpc.invoke(com+'save_proposal_revision',{'company':company,'proposal_id':context['proposal']['id'],'expected_revision':second['revision_number'],
            'expected_native_fingerprint':second['native_fingerprint'],'composition':composition,'operation_id':str(uuid4())})['revision']
        state=rpc.invoke(gov+'read_packet',{'company':company,'packet_id':stale_packet['id']})
        if state['state']!='Stale':raise AssertionError('A working successor left an old Issue grant executable.')
        rpc.invoke(gov+'execute_packet',{'company':company,'packet_id':stale_packet['id'],'manifest_hash':stale_packet['manifest_hash'],'operation_id':str(uuid4())},
            expected_codes={'approval_not_executable','stale_proposal_issue','stale_native_source'})
        if rpc.invoke(com+'issue',{'company':company,'issue_id':issue['id']})!=issue or _pdf(rpc,prepared)!=original_pdf:
            raise AssertionError('A successor rewrote the original issued snapshot/PDF.')
        replay=rpc.invoke(gov+'execute_packet',execute)
        if not replay['operation']['replayed'] or replay['effect']['issue']!=issue:raise AssertionError('Original consumed Issue receipt did not survive working successors.')
        listed=rpc.invoke(com+'issues',{'company':company,'proposal_id':context['proposal']['id'],'limit':50,'count_mode':'exact'})
        if listed['items']!=[issue] or listed['total']!=1 or listed['next_cursor'] is not None:raise AssertionError('Stale Issue grant created a duplicate issue or count/cursor.')
        for role in ('outsider','project_only'):
            rpc.login(role);rpc.invoke(com+'issue',{'company':company,'issue_id':issue['id']},expected_codes={'not_found','capability_denied'})
        durable={**context,'issue':issue,'issue_packet':packet,'issue_decision':decision,'issue_execute':execute,
                 'stale_issue_packet':stale_packet,'current_working_revision':third}
        _private_json(rpc.work/'issue-http-context.json',durable)
        report.update(status='passed',issue_id=issue['id'],proposal_id=context['proposal']['id'],issued_revision=context['revision']['id'],
            original_pdf_sha256=prepared['source_sha256'],issued_record_digest=digest(issue),stale_packet=stale_packet['id'],
            current_working_revision=third['id'],exact_issue_count=1,native_quotation_standing='draft',distribution='not-sent')
        return report
    except Exception as error:report['failure_type']=type(error).__name__;raise
    finally:
        rpc.close();report['calls']=rpc.calls;report['schema_samples']=rpc.schema_samples;report['completed_at']=datetime.now(timezone.utc).isoformat()
        _private_json(rpc.work/('issue-http-'+uuid4().hex+'.result.json'),report)


def run_issued_source_revocation_http(private_manifest,*,context_file,repository,base_url,private_directory,
                                     bench_private_manifest,container='cipher-r0-runtime-1',site='cipher.localhost'):
    """Current Company rights protect an already consumed exact Issue receipt."""
    import subprocess
    from .test_company_chain_acceptance import company_history_inventory
    fixture,rpc=_rpc(private_manifest,repository,base_url,private_directory)
    context=json.loads(Path(context_file).read_text());company=fixture['company'];issue=context['issue'];prepared=context['prepared_output']
    if context['company']!=company:raise RuntimeError('Use only the owned issued Company aggregate.')
    gov='cipher_aec.api.company_approvals.';com='cipher_aec.commercial.api.';denied={'not_found','capability_denied'}
    subjects={issue['id'],context['issue_packet']['id'],context['revision']['id'],prepared['revision_id']}
    def duty(active):
        command=[str(Path(repository)/'apps/cipher/platform/deployment/docker-local.sh'),'exec','--workdir','/home/frappe/frappe-bench',container,
                 'bench','--site',site,'execute','cipher_aec.tests.test_company_chain_acceptance.set_fixture_duty','--kwargs',
                 repr({'private_manifest':bench_private_manifest,'role':'author','ability':'commercial.read','active':active})]
        result=subprocess.run(command,capture_output=True,text=True,timeout=60)
        if result.returncode:raise RuntimeError('Owned Company duty change failed; captured private values are not published.')
        return json.loads(result.stdout)
    def protected(history):return {row['id']:row for row in history['items'] if row['subject_id'] in subjects}
    report={'schema':'cipher.r1.issued-source-http-revocation.v1','status':'failed','fixture_id':fixture['fixture_id'],'company':company,
            'started_at':datetime.now(timezone.utc).isoformat(),'distribution_qualified':False,'live_external_provider_qualified':False}
    try:
        rpc.login('author');before=protected(company_history_inventory(rpc,company))
        if not any(row['subject_id']==issue['id'] for row in before.values()):raise AssertionError('Original issued event was not visible before rights revocation.')
        rpc.invoke('cipher_aec.api.company.operation',{'company':company,'operation_id':context['issue_execute']['operation_id']})
        try:
            report['commercial_read_revoked']=duty(0)
            for method,values in ((com+'issue',{'company':company,'issue_id':issue['id']}),
                                  (com+'issues',{'company':company,'proposal_id':context['proposal']['id'],'count_mode':'exact'}),
                                  (gov+'read_packet',{'company':company,'packet_id':context['issue_packet']['id']}),
                                  ('cipher_aec.api.company.operation',{'company':company,'operation_id':context['issue_execute']['operation_id']})):
                rpc.invoke(method,values,expected_codes=denied)
            rpc.invoke(gov+'execute_packet',context['issue_execute'],expected_codes=denied)
            rpc.login('alias');rpc.invoke(gov+'execute_packet',context['issue_execute'],expected_codes=denied)
            rpc.login('author');hidden=company_history_inventory(rpc,company)
            if protected(hidden):raise AssertionError('Company history exposed original issued evidence without current commercial rights.')
            rpc.login('reviewer')
            if rpc.invoke(com+'issue',{'company':company,'issue_id':issue['id']})!=issue:raise AssertionError('Author-only revocation removed independent reviewer access.')
            _pdf(rpc,prepared)
            report['revoked_visible_history_count']=hidden['total']
        finally:
            report['commercial_read_restored']=duty(1)
        rpc.login('alias');replay=rpc.invoke(gov+'execute_packet',context['issue_execute'])
        if not replay['operation']['replayed'] or replay['effect']['issue']!=issue:raise AssertionError('Restored original UUID did not recover the same consumed Issue.')
        rpc.login('author')
        if protected(company_history_inventory(rpc,company))!=before:raise AssertionError('Original protected history bytes changed after current-rights restoration.')
        _pdf(rpc,prepared)
        report.update(status='passed',issue_id=issue['id'],protected_history_rows=len(before),original_receipt_replayed=True,
                      document_read_retained=True,reviewer_access_retained=True,original_pdf_sha256=prepared['source_sha256'])
        return report
    except Exception as error:report['failure_type']=type(error).__name__;raise
    finally:
        rpc.close();report['calls']=rpc.calls;report['schema_samples']=rpc.schema_samples;report['completed_at']=datetime.now(timezone.utc).isoformat()
        _private_json(rpc.work/('issued-source-revocation-'+uuid4().hex+'.result.json'),report)
