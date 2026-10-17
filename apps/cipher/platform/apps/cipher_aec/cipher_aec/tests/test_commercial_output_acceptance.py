"""Opt-in prepared-output proof using an explicitly supplied committed Company baseline.

No User/Auth/role changes; caller coordinates this isolated Company fixture with QA.
This is intentionally not automatic fresh-site run_acceptance discovery.
"""
from uuid import uuid4


def run_output_preparation_acceptance(source, users):
    import json
    import frappe
    from datetime import date,timedelta
    from cipher_aec.api.contracts import digest
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import assert_synthetic_site, trusted_write
    from cipher_aec.governance.commands import read_company_operation
    from cipher_aec.commercial import service,outputs,contracts
    from cipher_aec.documents import service as documents
    from cipher_aec.documents.extraction import extract_source
    assert_synthetic_site()
    if frappe.session.user!='Administrator' or not source['company'].startswith('Company chain A '):
        raise RuntimeError('Explicit committed isolated Company chain fixture required')
    for table,column in [('Cipher Document','producer_kind'),('Cipher Document Revision','generation_json')]:
        if not frappe.db.has_column(table,column):raise RuntimeError('Coordinated metadata migration required')
    company=source['company'];author=users['author'];alias=users['alias'];reviewer=users['reviewer']
    checks=[]
    def reject(name,callback,codes):
        try:callback()
        except DomainError as error:
            assert error.code in codes,(name,error.code)
            checks.append({'check':name,'status':'passed','error_code':error.code})
        else:raise AssertionError('Expected rejection: '+name)
    # Quotation invokes the supported native fiscal-year validator. Keep any
    # missing synthetic setup exact to this Company; never change another year.
    from erpnext.accounts.utils import get_fiscal_year,FiscalYearError
    today=frappe.utils.getdate()
    try:get_fiscal_year(today,company=company)
    except FiscalYearError:
        frappe.get_doc({'doctype':'Fiscal Year','year':'COM02 isolated '+uuid4().hex[:10],
            'year_start_date':date(today.year,1,1),'year_end_date':date(today.year,12,31),
            'companies':[{'company':company}]}).insert(ignore_permissions=True)
    unit=source['qualified_unit'];baseline={key:source[key] for key in ('acceptance_id','acceptance_digest','revision_id','revision_digest')}
    reference={**source['source_reference'],'purpose':'Exact synthetic commercial basis','permission_basis':'Explicit authored synthetic fixture content permission'}
    group=str(uuid4())
    authored={'currency':source['currency'],'price_list':source['native']['price_list'],'valid_till':(today+timedelta(days=60)).isoformat(),
        'terms':'Explicit synthetic output. No external distribution or legal award.',
        'sections':[{'id':str(uuid4()),'kind':'scope','title':'Synthetic scope','text':'Source-bound concrete scope for independent review.'}],
        'price_lines':[{'id':str(uuid4()),'description':'Selected synthetic measured scope','quantity':'1','unit_id':unit['id'],'unit_revision':unit['revision'],
            'rate':source['total']['amount'],'item_code':source['native']['item'],'alternate_group':group,'selected':True},
            {'id':str(uuid4()),'description':'Unselected alternate','quantity':'1','unit_id':unit['id'],'unit_revision':unit['revision'],
            'rate':'40.00','item_code':source['native']['item'],'alternate_group':group,'selected':False}],
        'source_references':[reference],'estimate_reference':baseline}
    frappe.set_user(author)
    try:
        made=service.create_proposal(company,source['pursuit_id'],authored,str(uuid4()))
        proposal,revision=made['proposal'],made['revision']
        assert revision['accepted_estimate']['acceptance_id']==source['acceptance_id']
        assert revision['source_citations'][0]['citation']['source_sha256']==reference['source_sha256']
        checks.append({'check':'exact_company_pursuit_accepted_baseline_and_canonical_page_bound_to_native_draft','status':'passed'})
        args={'company':company,'proposal_id':proposal['id'],'revision_id':revision['id'],'expected_revision_digest':digest(revision),
            'recipients':[{'name':'Synthetic recipient','email':'review@example.test','organization':'Explicit local fixture'}],
            'cover':'Review these exact prepared bytes before any independent issue grant.','operation_id':str(uuid4())}
        before_docs=frappe.db.count('Cipher Document',{'company':company});before_files=frappe.db.count('File')
        reject('renderer_failure_before_canonical_artifact_or_issue',lambda:outputs.prepare_output(**{**args,'cover':'Unsupported Gothic \U00010348','operation_id':str(uuid4())}),{'unsupported_output_text'})
        assert frappe.db.count('Cipher Document',{'company':company})==before_docs and frappe.db.count('File')==before_files
        prepared=outputs.prepare_output(**args)['prepared_output']
        assert outputs.read_output(company,revision['id'])==prepared
        assert frappe.db.count('Cipher Document Revision',{'document':prepared['document_id']})==1
        revision_row,content=documents.download_company_revision(company,prepared['revision_id'])
        from hashlib import sha256
        assert sha256(content).hexdigest()==prepared['source_sha256']
        text='\n'.join(extract_source(content,'application/pdf').pages)
        assert 'review@example.test' in text and source['total']['amount'] in text
        assert prepared['binding']['accepted_estimate']['acceptance_id']==source['acceptance_id']
        assert prepared['binding']['proposal_revision_digest']==digest(revision)
        checks.append({'check':'prepare_read_canonical_exact_pdf_bytes_recipients_baseline_rendering_provenance','status':'passed'})
        frappe.set_user(alias)
        replay=outputs.prepare_output(**args)
        assert replay['operation']['replayed'] and replay['prepared_output']==prepared
        assert read_company_operation(company,args['operation_id'])['prepared_output']==prepared
        assert frappe.db.count('Cipher Document',{'producer_kind':'commercial.proposal.output.v1','producer_reference':revision['id']})==1
        checks.append({'check':'canonical_alias_completed_receipt_replay_one_document_one_revision','status':'passed'})
        content2=b'Cannot replace prepared source bytes'
        reject('public_raw_upload_cannot_append_to_generated_parent',lambda:documents.upload_company_document(company=company,title='forged',filename='forged.txt',content=content2,byte_length=len(content2),sha256=sha256(content2).hexdigest(),operation_id=str(uuid4()),document_id=prepared['document_id'],expected_revision=1),{'invalid_artifact'})
        reject('changed_cover_requires_successor_revision',lambda:outputs.prepare_output(**{**args,'cover':'Changed cover','operation_id':str(uuid4())}),{'output_already_prepared'})
        # Unrelated trusted context cannot manufacture producer attribution or
        # claimed renderer provenance, even with an authentic source binding.
        parent=frappe.get_doc('Cipher Document',prepared['document_id'])
        forged_parent={key:parent.get(key) for key in ('company','scope_type','project','title','producer_kind','producer_reference','producer_input_digest','producer_binding_json')}
        forged_parent.update(doctype='Cipher Document',name='DOC-'+uuid4().hex,revision_number=0,current_revision=None)
        def insert_generated():
            with trusted_write():
                frappe.get_doc(forged_parent).insert(ignore_permissions=True,set_name=forged_parent['name'])
        reject('unrelated_trusted_write_cannot_forge_generated_provenance',insert_generated,{'preparation_required'})
        assert not frappe.db.exists('Cipher Document',forged_parent['name'])
        # A fully syntactic, trusted internal insertion still cannot mint Issue:
        # the exact approval-effect context is required before source evaluation.
        from cipher_aec.commercial.issue_records import facts
        grant=frappe.db.get_value('Cipher Estimate Acceptance',source['acceptance_id'],['packet_id','decision_id','accepted_by_person'],as_dict=True)
        forged={'id':str(uuid4()),'company':company,'author_person':frappe.db.get_value('Cipher Identity Binding',{'user':alias,'active':1},'person'),
            'revision_number':1,'predecessor':None,'packet_id':grant.packet_id,'decision_id':grant.decision_id,'approved_by_person':grant.accepted_by_person,
            'manifest':{},'manifest_digest':digest({}),**facts(revision,prepared)}
        count=frappe.db.count('Cipher Proposal Issue')
        def insert_issue():
            with trusted_write():service._write('issue',forged)
        reject('unrelated_trusted_write_cannot_mint_issued_record',insert_issue,{'approval_required'})
        assert frappe.db.count('Cipher Proposal Issue')==count
        checks.append({'check':'no_issue_or_consumption_from_preparation','status':'passed'})
        from jsonschema import Draft202012Validator
        from pathlib import Path
        schema=json.loads(Path(service.__file__).parent.joinpath('schemas/api-v1.schema.json').read_text())
        for key,value in [('ComPreparedOutput',prepared),('ComRevision',revision)]:
            Draft202012Validator({**schema,'$ref':'#/$defs/'+key}).validate(value)
        checks.append({'check':'exact_published_prepared_output_and_source_revision_response_schemas','status':'passed'})
        frappe.db.commit()
        return {'status':'passed','company':company,'proposal_id':proposal['id'],'proposal_revision':revision['id'],
            'prepared_output':prepared,'prepare_operation_id':args['operation_id'],'prepare_args':args,'users':users,'checks':checks,
            'qualification':'Actual native ERPNext/MariaDB canonical prepared bytes and replay only; Issue effect remains disabled pending independent approval qualification.'}
    except BaseException:
        frappe.db.rollback()
        raise
    finally:
        frappe.set_user('Administrator')


def run_output_readback(prepared, users):
    """Read-only native projection/count and exact producer-node proof."""
    import frappe
    from cipher_aec.api.errors import DomainError
    from cipher_aec.documents import provenance
    from cipher_aec.governance.context import assert_synthetic_site,current_actor
    from cipher_aec.commercial import service
    assert_synthetic_site()
    if frappe.session.user!='Administrator':raise RuntimeError('Explicit synthetic bench context required')
    fileid=frappe.db.get_value('Cipher Document Revision',prepared['revision_id'],'storage_reference')
    cases=[]
    try:
        for role,expected in (('author',1),('reviewer',1),('outsider',0),('project_only',0)):
            frappe.set_user(users[role])
            for doctype,name,fields in (('Cipher Document',prepared['document_id'],['name','producer_binding_json']),
                    ('Cipher Document Revision',prepared['revision_id'],['name','pages_json']),('File',fileid,['name','file_url'])):
                rows=frappe.get_list(doctype,filters={'name':name},fields=fields)
                count=frappe.get_list(doctype,filters={'name':name},fields=[{'COUNT':'name','as':'total'}])[0]['total']
                assert len(rows)==count==expected,(role,doctype,len(rows),count)
            cases.append({'role':role,'native_document_revision_file_projection_and_count':expected})
        frappe.set_user(users['author']);actor=current_actor();company=prepared['company']
        plan=provenance.source_plan(company,prepared['revision_id'],actor)
        facts=provenance.node_manifest(plan,actor,company)
        own=next(row for row in facts if row['document_id']==prepared['document_id'])
        assert own['revision_id']==prepared['revision_id'] and own['source_sha256']==prepared['source_sha256'] and own['input_digest']==prepared['input_digest']
        assert own['accepted_baseline_digest']==prepared['binding']['accepted_estimate']['acceptance_digest']
        try:provenance.node_manifest(plan,actor,company,lock=True)
        except DomainError as error:assert error.code=='source_prelock_required'
        else:raise AssertionError('Generated node reader manufactured lock admission')
        service._actor(company,actor,lock=True)
        service._read('revision',prepared['proposal_revision_id'],company,actor,lock=True)
        with provenance.prelocked(plan,actor,company):
            assert provenance.node_manifest(plan,actor,company,lock=True)==facts
        frappe.db.rollback()
        return {'status':'passed','native_cases':cases,'exact_node_manifest':facts,'locking_without_outer_plan':'source_prelock_required','locking_after_full_union':'passed'}
    finally:
        frappe.set_user('Administrator')


def run_registered_issue_acceptance(prepared_source, reviewed_packet=None):
    """Registered native independent request/grant/consume and retained lineage."""
    import copy
    import frappe
    from cipher_aec.api.contracts import digest
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import assert_synthetic_site
    from cipher_aec.governance import approvals, domain_approvals
    from cipher_aec.governance.commands import read_company_operation
    from cipher_aec.commercial import service,outputs
    assert_synthetic_site()
    if frappe.session.user!='Administrator':raise RuntimeError('Explicit synthetic bench context required')
    if not domain_approvals.ACTIONS['proposal.issue.v1'].enabled:raise RuntimeError('Literal reviewed Issue action is not enabled; do not bypass it')
    prepared=prepared_source['prepared_output'];users=prepared_source['users'];company=prepared['company']
    checks=[]
    def reject(name,callback,codes):
        try:callback()
        except DomainError as error:
            assert error.code in codes,(name,error.code)
            checks.append({'check':name,'status':'passed','error_code':error.code})
        else:raise AssertionError('Expected rejection: '+name)
    before={table:frappe.db.count(table,{'company':company}) for table in ('GL Entry','Sales Order','Sales Invoice','Payment Entry')}
    frappe.set_user(users['author'])
    try:
        if reviewed_packet is None:
            requested=approvals.request_action(company,None,'proposal.issue.v1',prepared['proposal_revision_id'],prepared['review_version'],str(uuid4()),scope_type='Company')
            packet=requested['packet'];packet_id=packet['id'];manifest_hash=packet['manifest_hash']
            frappe.set_user(users['alias'])
            reject('noninteractive_bench_review_denied',lambda:approvals.decide_packet(company,None,packet_id,manifest_hash,'Grant',str(uuid4()),scope_type='Company'),{'interactive_review_required'})
            frappe.db.commit()
            return {'status':'awaiting_interactive_review','reviewed_packet':{'packet_id':packet_id,'manifest_hash':manifest_hash},'checks':checks,
                'qualification':'Native request persisted; independent Grant must use an actual cookie/CSRF POST. No Issue or consumption claimed.'}
        packet_id=reviewed_packet['packet_id'];manifest_hash=reviewed_packet['manifest_hash']
        packet=frappe.get_doc('Cipher Approval Packet',packet_id)
        assert packet.scope_type=='Company' and packet.company==company and not packet.project and packet.subject_id==prepared['proposal_revision_id'] and packet.manifest_hash==manifest_hash
        decision=frappe.db.sql("SELECT decision,actor_person FROM `tabCipher Approval Decision` WHERE packet=%s ORDER BY creation DESC LIMIT 1",(packet_id,),as_dict=True)[0]
        assert decision.decision=='Grant' and decision.actor_person!=packet.requester_person
        checks.append({'check':'registered_company_native_request_and_actual_cookie_csrf_independent_canonical_human_grant','status':'passed'})
        frappe.set_user(users['author']);execute_operation=str(uuid4())
        executed=approvals.execute_packet(company,None,packet_id,manifest_hash,execute_operation,scope_type='Company')
        issue=executed['effect']['issue']
        assert issue['output_revision']==prepared['revision_id'] and issue['prepared_output']==prepared
        assert issue['accepted_estimate']==prepared['binding']['accepted_estimate']
        assert issue['native_lifecycle']=='draft-snapshot' and issue['distribution']=='not-sent'
        assert all(row['line']['selected'] and row['line']['id']==row['native_item']['cipher_line_id'] for row in issue['selected_lines'])
        assert len(issue['selected_lines'])==1 and len(issue['pricing']['lines'])==2
        assert frappe.db.get_value('Quotation',issue['native_snapshot']['id'],'docstatus')==0
        assert before=={table:frappe.db.count(table,{'company':company}) for table in before}
        checks.append({'check':'exact_approved_pdf_native_draft_selected_line_and_accepted_baseline_consumed_without_financial_or_distribution_effect','status':'passed'})
        frappe.set_user(users['alias'])
        replay=approvals.execute_packet(company,None,packet_id,manifest_hash,execute_operation,scope_type='Company')
        assert replay['operation']['replayed'] and replay['effect']['issue']==issue
        assert read_company_operation(company,execute_operation)['effect']['issue']==issue
        assert frappe.db.count('Cipher Proposal Issue',{'proposal_revision':issue['proposal_revision']})==1
        assert frappe.db.count('Cipher Approval Consumption',{'packet':packet_id})==1
        checks.append({'check':'alias_original_execute_receipt_replay_one_issue_one_consumption','status':'passed'})
        current=service.get_proposal(company,issue['proposal'])
        authored=copy.deepcopy(current['revision']['composition']);authored['terms']+=' Explicit successor working draft; old Issue preserved.'
        successor=service.save_proposal_revision(company,issue['proposal'],current['revision_number'],current['native_fingerprint'],authored,str(uuid4()))
        assert successor['revision']['id']!=issue['proposal_revision']
        assert service._read('issue',issue['id'],company,service._actor(company))[1]==issue
        assert outputs.read_output(company,issue['proposal_revision'])==prepared
        assert outputs.prepare_output(**prepared_source['prepare_args'])['operation']['replayed']
        assert read_company_operation(company,execute_operation)['effect']['issue']==issue
        reject('successor_working_draft_prevents_new_issue_of_old_subject',lambda:approvals.request_action(company,None,'proposal.issue.v1',issue['proposal_revision'],prepared['review_version'],str(uuid4()),scope_type='Company'),{'stale_proposal_issue'})
        checks.append({'check':'working_successor_preserves_original_issue_artifact_and_completed_receipts','status':'passed'})
        from pathlib import Path
        from jsonschema import Draft202012Validator
        import json
        schema=json.loads(Path(service.__file__).parent.joinpath('schemas/api-v1.schema.json').read_text())
        Draft202012Validator({**schema,'$ref':'#/$defs/ComIssue'}).validate(issue)
        assert service.list_issues(company,issue['proposal'],count_mode='exact')['total']==1
        checks.append({'check':'published_issue_schema_and_authorized_count','status':'passed'})
        frappe.db.commit()
        return {'status':'passed','company':company,'issue':issue,'packet_id':packet_id,'execute_operation_id':execute_operation,
            'successor_revision_id':successor['revision']['id'],'checks':checks,
            'qualification':'Actual registered Company independent Issue effect over exact canonical PDF; native Quotation remains draft, no external distribution.'}
    except BaseException:
        frappe.db.rollback()
        raise
    finally:
        frappe.set_user('Administrator')


def run_complete_admission_acceptance(prepared_source):
    """Actual canonical bytes only after complete scoped outer lock admission."""
    import copy
    import types
    import frappe
    from unittest.mock import patch
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import assert_synthetic_site,current_actor
    from cipher_aec.documents import provenance
    from cipher_aec.documents.service import company_source_reference
    from cipher_aec.documents.storage import FrappeFileStorage
    from cipher_aec.commercial import service,sources,native,outputs
    assert_synthetic_site()
    if frappe.session.user!='Administrator':raise RuntimeError('Explicit isolated synthetic bench context required')
    p=prepared_source['prepared_output'];users=prepared_source['users'];company=p['company'];cases=[]
    frappe.set_user(users['author'])
    try:
        actor=current_actor()
        assert not provenance.has_prelocked()
        subject=outputs.output_subject(company,p['proposal_id'],actor)
        assert subject['revision_id']==p['proposal_revision_id'] and subject['revision_digest']==p['proposal_revision_digest']
        assert not provenance.has_prelocked()
        plan=provenance.source_plan(company,p['revision_id'],actor)
        assert not provenance.has_prelocked()
        for key in ('unit_ids','currencies','native_refs','generated_sources'):
            assert plan[key],key
            incomplete=copy.deepcopy(plan);incomplete[key]=incomplete[key][1:]
            with provenance.prelocked(incomplete,actor,company), patch.object(FrappeFileStorage,'read',side_effect=AssertionError('Source bytes read before complete admission')):
                assert not provenance.is_prelocked(plan,actor,company)
                try:company_source_reference(company,p['revision_id'],1,actor,lock=True)
                except DomainError as error:assert error.code=='source_prelock_required'
                else:raise AssertionError('Incomplete outer '+key+' admitted')
            cases.append({'missing':key,'error_code':'source_prelock_required','bytes_read':False})
        wrong=types.SimpleNamespace(user=users['alias'],person_id=actor.person_id)
        for admitted_actor,admitted_company in ((wrong,company),(actor,company+' unavailable')):
            with provenance.prelocked(plan,admitted_actor,admitted_company), patch.object(FrappeFileStorage,'read',side_effect=AssertionError('Source bytes read under wrong authority')):
                try:company_source_reference(company,p['revision_id'],1,actor,lock=True)
                except DomainError as error:assert error.code=='source_prelock_required'
                else:raise AssertionError('Wrong outer authority admitted')
            cases.append({'wrong':'user' if admitted_actor is wrong else 'company','error_code':'source_prelock_required','bytes_read':False})
        service._actor(company,actor,lock=True)
        revision=sources.revision_record(company,p['proposal_revision_id'],actor,lock=True)
        party,refs=service._source_plan('proposal',p['proposal_id'],company,lock=True)
        _,_,acquired=native.sources(revision['composition'],company,actor,lock=True,for_new=False,party_ref=party,native_refs=refs,extra_plan=plan,include_plan=True)
        with provenance.prelocked(acquired,actor,company):
            assert provenance.is_prelocked(plan,actor,company)
            with provenance.prelocked({'unit_ids':[]},actor,company):
                assert provenance.is_prelocked(plan,actor,company)
                result=company_source_reference(company,p['revision_id'],1,actor,lock=True)
                assert result['source_sha256']==p['source_sha256'] and len(result['content'])==p['byte_length']
                assert provenance.node_manifest(plan,actor,company,lock=True)[0]['revision_id']==p['revision_id']
        assert not provenance.has_prelocked()
        frappe.db.rollback()
        return {'status':'passed','denials':cases,'complete_actual_union_nested_bytes_and_node_proof':'passed',
            'read_and_discovery_never_create_admission':'passed','server_output_subject_digest':'passed'}
    except BaseException:
        frappe.db.rollback()
        raise
    finally:
        frappe.set_user('Administrator')
