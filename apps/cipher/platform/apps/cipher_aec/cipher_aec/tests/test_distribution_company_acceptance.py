"""Opt-in independent Company HTTP mandate and real-worker fault probes.

No identity provisioning, implicit policy activation, transport enablement or
external provider. Root coordinates the synthetic profile and consumer hold.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4


def prepare_two_recipient_issue_http(private_manifest,*,issue_context,repository,base_url,private_directory):
    """Legitimate reviewed successor, never edit the original issued addresses."""
    from cipher_aec.api.contracts import digest
    from .test_company_commercial_chain_http_acceptance import _rpc, _private_json, _pdf
    fixture,rpc=_rpc(private_manifest,repository,base_url,private_directory)
    context=json.loads(Path(issue_context).read_text());company=fixture['company'];revision=context['current_working_revision']
    if context['company']!=company:raise RuntimeError('Use only the owned working successor of the independent Issue.')
    com='cipher_aec.commercial.api.';gov='cipher_aec.api.company_approvals.'
    report={'schema':'cipher.r1.distribution-recipient-issue-http.v1','status':'failed','fixture_id':fixture['fixture_id'],
            'started_at':datetime.now(timezone.utc).isoformat(),'live_external_provider_qualified':False}
    try:
        rpc.login('author')
        prepare={**context['prepare'],'revision_id':revision['id'],'expected_revision_digest':digest(revision),
                 'recipients':[{'name':'Synthetic first recipient','email':'qa.first@cipher.example','organization':'Independent local fixture'},
                               {'name':'Synthetic second recipient','email':'qa.second@cipher.example','organization':'Independent local fixture'}],
                 'cover':'Two fixed synthetic recipients for independent partial recovery qualification. No external transmission.',
                 'operation_id':str(uuid4())}
        prepared=rpc.invoke(com+'prepare_proposal_output',prepare)['prepared_output'];_pdf(rpc,prepared)
        packet=rpc.invoke(gov+'request_action',{'company':company,'action':'proposal.issue.v1','subject_id':revision['id'],
            'expected_version':prepared['review_version'],'operation_id':str(uuid4())})['packet']
        decision={'company':company,'packet_id':packet['id'],'manifest_hash':packet['manifest_hash'],'decision':'Grant',
                  'reason':'Independently reviewed exact two-recipient successor PDF','operation_id':str(uuid4())}
        rpc.login('reviewer');rpc.invoke(gov+'decide_packet',decision)
        execute={'company':company,'packet_id':packet['id'],'manifest_hash':packet['manifest_hash'],'operation_id':str(uuid4())}
        rpc.login('author');consumed=rpc.invoke(gov+'execute_packet',execute);issue=consumed['effect']['issue']
        if consumed['packet']['state']!='Consumed' or issue['predecessor']!=context['issue']['id'] or issue['prepared_output']!=prepared or len(prepared['binding']['recipients'])!=2 or issue['distribution']!='not-sent':
            raise AssertionError('The two-recipient artifact was not independently issued as the exact legitimate successor.')
        if rpc.invoke(com+'issue',{'company':company,'issue_id':context['issue']['id']})!=context['issue']:
            raise AssertionError('The legitimate successor changed the original immutable Issue.')
        durable={**context,'revision':revision,'prepare':prepare,'prepared_output':prepared,'issue':issue,
                 'issue_packet':packet,'issue_decision':decision,'issue_execute':execute}
        _private_json(rpc.work/'two-recipient-issue-context.json',durable)
        report.update(status='passed',company=company,issue_id=issue['id'],predecessor=issue['predecessor'],
                      proposal_revision_id=revision['id'],prepared_output=prepared,recipient_count=2,distribution='not-sent')
        return report
    except Exception as error:report['failure_type']=type(error).__name__;raise
    finally:
        rpc.close();report['calls']=rpc.calls;report['schema_samples']=rpc.schema_samples;report['session_timings']=rpc.session_timings
        report['completed_at']=datetime.now(timezone.utc).isoformat()
        _private_json(rpc.work/('two-recipient-issue-'+uuid4().hex+'.result.json'),report)


def run_distribution_http_setup(private_manifest,*,issue_context,repository,base_url,private_directory,resume_journal=None,subset_first_recipient=False):
    from cipher_aec.api.contracts import digest
    from .test_company_commercial_chain_http_acceptance import _rpc, _private_json
    fixture,rpc=_rpc(private_manifest,repository,base_url,private_directory)
    context=json.loads(Path(issue_context).read_text());company=fixture['company'];issue=context['issue']
    if context['company']!=company or issue['distribution']!='not-sent':raise RuntimeError('Use the owned immutable, unsent Issue.')
    api='cipher_aec.integrations.distribution_api.';gov='cipher_aec.api.company_approvals.'
    report={'schema':'cipher.r1.distribution-http-mandate.v1','status':'failed','fixture_id':fixture['fixture_id'],
            'started_at':datetime.now(timezone.utc).isoformat(),'live_external_provider_qualified':False}
    try:
        rpc.login('author');profiles=rpc.invoke(api+'profiles',{'company':company})
        if profiles['live_transmission'] or not any(p['id']=='local-fixture-v1' and p['enabled'] for p in profiles['items']):
            raise AssertionError('Root must explicitly enable only the fixed synthetic profile.')
        prior=rpc.invoke(api+'list_dispatches',{'company':company,'issue_id':issue['id'],'count_mode':'exact'})
        if prior['next_cursor'] is not None or prior['total']!=len(prior['items']):
            raise RuntimeError('This private fixture requires a fully bounded existing dispatch inventory.')
        selected_ids=None
        if subset_first_recipient:
            choices=rpc.invoke(api+'recipient_choices',{'company':company,'issue_id':issue['id']})
            if choices['issue_id']!=issue['id'] or choices['issue_digest']!=digest(issue) or len(choices['recipients'])!=2:
                raise AssertionError('Subset qualification requires the owned exact two-recipient Issue.')
            selected_ids=[choices['recipients'][0]['id']]
        create={'company':company,'issue_id':issue['id'],'recipient_ids':selected_ids,'subject':'QA distribution '+uuid4().hex[:12],
                'body':'Independent durable fixture only; no external transmission.','profile_id':'local-fixture-v1','operation_id':str(uuid4())}
        if resume_journal is not None:
            retained=[row for row in json.loads(Path(resume_journal).read_text()) if row['method']==api+'create_instruction']
            if len(retained)!=1:raise RuntimeError('Resume requires exactly one privately retained original instruction command.')
            create=retained[0]['payload']
            if create['company']!=company or create['issue_id']!=issue['id'] or create['profile_id']!='local-fixture-v1':
                raise RuntimeError('An exact retry cannot retarget the retained Company/Issue/profile.')
        created=rpc.invoke(api+'create_instruction',create);instruction=created['instruction']
        if subset_first_recipient and [row['id'] for row in instruction['recipients']]!=selected_ids:
            raise AssertionError('The saved instruction changed the canonical recipient subset.')
        if instruction['attachment']['sha256']!=context['prepared_output']['source_sha256'] or instruction['issue_digest']!=digest(issue):
            raise AssertionError('The instruction changed the issued artifact identity.')
        rpc.login('alias');replay=rpc.invoke(api+'create_instruction',create)
        if not replay['operation']['replayed'] or replay['instruction']!=instruction:raise AssertionError('Canonical alias duplicated the immutable instruction.')
        readback=rpc.invoke(api+'get_instruction',{'company':company,'instruction_id':instruction['id']})
        if readback!={'instruction':instruction,'version':created['version']}:raise AssertionError('Instruction readback changed the exact approved payload/version.')
        rpc.login('author');request={'company':company,'action':'proposal.distribute.v1','subject_id':instruction['id'],
            'expected_version':created['version'],'operation_id':str(uuid4())}
        packet=rpc.invoke(gov+'request_action',request)['packet']
        decision={'company':company,'packet_id':packet['id'],'manifest_hash':packet['manifest_hash'],'decision':'Grant',
                  'reason':'Independent exact local fixture artifact/recipient/message review','operation_id':str(uuid4())}
        rpc.login('alias');rpc.invoke(gov+'decide_packet',decision,expected_codes={'independent_review_required'})
        rpc.login('reviewer');decision['operation_id']=str(uuid4());granted=rpc.invoke(gov+'decide_packet',decision)
        if granted['packet']['state']!='Granted':raise AssertionError('Independent dispatch review was not granted.')
        execute={'company':company,'packet_id':packet['id'],'manifest_hash':packet['manifest_hash'],'operation_id':str(uuid4())}
        rpc.login('author');consumed=rpc.invoke(gov+'execute_packet',execute);dispatch=consumed['effect']['dispatch']
        if consumed['packet']['state']!='Consumed' or dispatch['instruction_id']!=instruction['id']:raise AssertionError('The dispatch did not consume the exact reviewed instruction.')
        rpc.login('alias');retry=rpc.invoke(gov+'execute_packet',execute)
        if not retry['operation']['replayed'] or retry['effect']['dispatch']!=dispatch:raise AssertionError('Canonical retry created a second dispatch.')
        detail=rpc.invoke(api+'get_dispatch',{'company':company,'dispatch_id':dispatch['id']})
        if detail['state']!='Queued' or len(detail['deliveries'])!=len(instruction['recipients']) or any(d['state']!='Queued' for d in detail['deliveries']):
            raise AssertionError('The root-controlled consumer window did not preserve the queued fault fixture.')
        for delivery in detail['deliveries']:
            actual=rpc.invoke(api+'get_recipient_delivery',{'company':company,'dispatch_id':dispatch['id'],'recipient_id':delivery['recipient_id']})
            if actual!=delivery:raise AssertionError('Recipient readback changed the canonical queued operation.')
        listed=rpc.invoke(api+'list_dispatches',{'company':company,'issue_id':issue['id'],'count_mode':'exact'})
        if {d['id'] for d in listed['items']}!={d['id'] for d in prior['items']}|{dispatch['id']} or listed['total']!=prior['total']+1 or listed['next_cursor'] is not None:
            raise AssertionError('Original same-key retry changed the exact Issue dispatch cardinality.')
        durable={'company':company,'issue':issue,'instruction':instruction,'create':create,'packet':packet,'decision':decision,
                 'execute':execute,'dispatch':dispatch,'deliveries':detail['deliveries']}
        _private_json(rpc.work/'distribution-http-context.json',durable)
        report.update(status='passed',company=company,issue_id=issue['id'],instruction_id=instruction['id'],dispatch_id=dispatch['id'],
                      queued_operations=[d['operation_id'] for d in detail['deliveries']],recipient_count=len(detail['deliveries']),
                      transport='fixture',sink_acceptance_qualified=False,original_instruction_command_resumed=resume_journal is not None,
                      canonical_recipient_subset_qualified=subset_first_recipient)
        return report
    except Exception as error:report['failure_type']=type(error).__name__;raise
    finally:
        rpc.close();report['calls']=rpc.calls;report['schema_samples']=rpc.schema_samples;report['session_timings']=rpc.session_timings;report['completed_at']=datetime.now(timezone.utc).isoformat()
        _private_json(rpc.work/('distribution-http-'+uuid4().hex+'.result.json'),report)


def run_worker_lost_ack(private_manifest,operation_id):
    """Actual persistent sink acceptance survives lost response and DB rollback."""
    import threading
    from unittest.mock import patch
    import frappe
    from .test_company_chain_acceptance import _load_fixture
    from cipher_aec.integrations import distribution as service, distribution_transport as transport, outbox
    fixture=_load_fixture(private_manifest);op=frappe.get_doc('Cipher Integration Operation',operation_id)
    if op.company!=fixture['company'] or op.kind!='company.proposal.fixture.v1' or op.scope_type!='Company' or op.project or op.state!='Queued':
        raise RuntimeError('Only the owned queued canonical Company fixture operation may be faulted.')
    payload=json.loads(op.payload_json);dispatch=service.raw('dispatch',payload['dispatch_id'],op.company)
    instruction=service.raw('instruction',payload['instruction_id'],op.company)
    if instruction['author_user']!=fixture['users']['author']['user'] or not instruction['message']['subject'].startswith('QA distribution '):
        raise RuntimeError('Only an independently staged QA instruction may use this fault seam.')
    if transport.readback(op.logical_id) is not None:raise AssertionError('The fresh queued fixture already has a sink acceptance.')
    issue=json.loads(frappe.get_doc('Cipher Proposal Issue',instruction['issue_id']).data_json)
    probe_rows={('Cipher Integration Operation',op.name),('Company',op.company),('Quotation',issue['native_snapshot']['id']),
                ('Currency',issue['native_snapshot']['currency']),('Price List',issue['native_snapshot']['selling_price_list']),
                (issue['native_snapshot']['quotation_to'],issue['native_snapshot']['party_name'])}
    probe_rows.update(('Cipher Person',p) for p in (dispatch['requester_person'],dispatch['reviewer_person']))
    probe_rows.update(('UOM',unit['target']['name']) for unit in issue['units'].values())
    probe_rows.update(('Item',row['native_item']['item_code']) for row in issue['selected_lines'])
    connection_id=frappe.db.sql('SELECT CONNECTION_ID()')[0][0]
    frappe.db.commit();original_accept=transport.accept;observed=[];lock_probe={};site=frappe.local.site
    def unlocked():
        try:
            frappe.init(site=site);frappe.connect();frappe.db.sql('SET innodb_lock_wait_timeout=2')
            if frappe.db.sql('SELECT CONNECTION_ID()')[0][0]==connection_id:raise AssertionError('Lock probe must use an independent database connection.')
            for doctype,identifier in sorted(probe_rows):
                rows=frappe.db.sql('SELECT name FROM `tab'+doctype+'` WHERE name=%s FOR UPDATE',(identifier,))
                if len(rows)!=1:raise AssertionError('A required probe row disappeared.')
            lock_probe['independent_connection_acquired_operation_company_and_people']=True
            lock_probe['native_source_rows_acquired']=True;lock_probe['independent_connection']=True;lock_probe['row_count']=len(probe_rows)
        except BaseException as error:lock_probe['failure_type']=type(error).__name__
        finally:frappe.db.rollback();frappe.destroy()
    def accept_then_lose(*args):
        thread=threading.Thread(target=unlocked,daemon=True);thread.start();thread.join(10)
        if thread.is_alive() or lock_probe.get('failure_type') or not lock_probe.get('independent_connection_acquired_operation_company_and_people'):
            raise AssertionError('The adapter boundary retained Frappe locks or the independent probe failed.')
        ack=original_accept(*args);observed.append(ack)
        raise TimeoutError('Injected response loss after independently committed synthetic acceptance.')
    with patch.object(transport,'accept',side_effect=accept_then_lose):result=outbox.deliver(op.name)
    if result['state']!='Unknown' or len(observed)!=1:raise AssertionError('Lost acceptance acknowledgment was not persisted as Unknown.')
    frappe.db.rollback();op=frappe.get_doc('Cipher Integration Operation',operation_id)
    acknowledgment=transport.readback(op.logical_id)
    if op.state!='Unknown' or acknowledgment!=observed[0] or acknowledgment['payload_hash']!=op.payload_hash:
        raise AssertionError('Independent acceptance did not survive authoritative transaction rollback.')
    return {'schema':'cipher.r1.distribution-lost-ack-native.v1','status':'passed','operation_id':op.name,'logical_key':op.logical_id,
            'state':op.state,'fencing_token':op.fencing_token,'acknowledgment':acknowledgment,'lock_probe':lock_probe,
            'sink_commit_survived_frappe_rollback':True,'transport':'fixture','live_external_provider_qualified':False}


def cancel_distribution_http(private_manifest,*,dispatch_context,repository,base_url,private_directory):
    from .test_company_commercial_chain_http_acceptance import _rpc, _private_json
    fixture,rpc=_rpc(private_manifest,repository,base_url,private_directory)
    context=json.loads(Path(dispatch_context).read_text());company=fixture['company'];dispatch=context['dispatch']
    if context['company']!=company:raise RuntimeError('Only the owned staged dispatch may be cancelled.')
    api='cipher_aec.integrations.distribution_api.'
    report={'schema':'cipher.r1.distribution-cancel-http.v1','status':'failed','fixture_id':fixture['fixture_id'],
            'started_at':datetime.now(timezone.utc).isoformat(),'live_external_provider_qualified':False}
    try:
        command={'company':company,'dispatch_id':dispatch['id'],'reason':'Independent stop-before-acceptance fixture','operation_id':str(uuid4())}
        rpc.login('author');cancelled=rpc.invoke(api+'cancel_dispatch',command)
        if cancelled['cancellation']['dispatch_id']!=dispatch['id'] or not cancelled['cancellation']['in_flight_may_complete']:
            raise AssertionError('Cancellation failed to bind exact dispatch or misrepresented in-flight standing.')
        rpc.login('alias');replay=rpc.invoke(api+'cancel_dispatch',command)
        if not replay['operation']['replayed'] or replay['cancellation']!=cancelled['cancellation']:
            raise AssertionError('Canonical retry duplicated cancellation.')
        detail=rpc.invoke(api+'get_dispatch',{'company':company,'dispatch_id':dispatch['id']})
        if detail['cancellation']!=cancelled['cancellation']:raise AssertionError('Dispatch readback lost the exact durable cancellation.')
        report.update(status='passed',dispatch_id=dispatch['id'],cancellation=cancelled['cancellation'],original_uuid_replayed=True)
        return report
    except Exception as error:report['failure_type']=type(error).__name__;raise
    finally:
        rpc.close();report['calls']=rpc.calls;report['schema_samples']=rpc.schema_samples;report['session_timings']=rpc.session_timings
        report['completed_at']=datetime.now(timezone.utc).isoformat()
        _private_json(rpc.work/('distribution-cancel-http-'+uuid4().hex+'.result.json'),report)


def read_delivery_http(private_manifest,*,dispatch_context,expected_dispatch_state,expected_operation_states,repository,base_url,
                       private_directory,acknowledgments=None):
    """Schema-check real queued, ambiguous, partial or acknowledged read models."""
    from .test_company_commercial_chain_http_acceptance import _rpc, _private_json
    fixture,rpc=_rpc(private_manifest,repository,base_url,private_directory)
    context=json.loads(Path(dispatch_context).read_text());company=fixture['company'];dispatch=context['dispatch']
    if context['company']!=company:raise RuntimeError('Only the owned canonical dispatch may be observed.')
    api='cipher_aec.integrations.distribution_api.'
    report={'schema':'cipher.r1.distribution-state-http.v1','status':'failed','fixture_id':fixture['fixture_id'],
            'started_at':datetime.now(timezone.utc).isoformat(),'live_external_provider_qualified':False}
    try:
        rpc.login('author');profiles=rpc.invoke(api+'profiles',{'company':company})
        if profiles['live_transmission']:raise AssertionError('A fixture cannot claim live transmission.')
        detail=rpc.invoke(api+'get_dispatch',{'company':company,'dispatch_id':dispatch['id']})
        if detail['dispatch']!=dispatch or detail['state']!=expected_dispatch_state or {d['operation_id']:d['state'] for d in detail['deliveries']}!=expected_operation_states:
            raise AssertionError('Current canonical recipient states differ from the real worker results.')
        for delivery in detail['deliveries']:
            actual=rpc.invoke(api+'get_recipient_delivery',{'company':company,'dispatch_id':dispatch['id'],'recipient_id':delivery['recipient_id']})
            if actual!=delivery:raise AssertionError('Recipient readback differs from the canonical dispatch.')
            if delivery['operation_id'] in (acknowledgments or {}) and delivery['receipt']!={'mode':'fixture','receipt':acknowledgments[delivery['operation_id']]}:
                raise AssertionError('HTTP acknowledgment differs from the independently durable sink receipt.')
        report.update(status='passed',dispatch_id=dispatch['id'],detail=detail,profile=profiles['items'])
        return report
    except Exception as error:report['failure_type']=type(error).__name__;raise
    finally:
        rpc.close();report['calls']=rpc.calls;report['schema_samples']=rpc.schema_samples;report['session_timings']=rpc.session_timings
        report['completed_at']=datetime.now(timezone.utc).isoformat()
        _private_json(rpc.work/('distribution-state-http-'+uuid4().hex+'.result.json'),report)


def reconcile_worker_fixture(private_manifest,operation_id):
    """Expire only the known synthetic lease; recover by readback, never accept."""
    import frappe
    from datetime import timedelta
    from unittest.mock import patch
    from frappe.utils import now_datetime
    from .test_company_chain_acceptance import _load_fixture
    from cipher_aec.governance.context import trusted_write
    from cipher_aec.integrations.distribution_records import operation_write
    from cipher_aec.integrations import distribution_transport as transport, outbox
    fixture=_load_fixture(private_manifest);op=frappe.get_doc('Cipher Integration Operation',operation_id,for_update=True)
    if op.company!=fixture['company'] or op.actor_user!=fixture['users']['author']['user'] or op.kind!='company.proposal.fixture.v1' or op.state!='Unknown':
        raise RuntimeError('Only the owned Unknown synthetic lease may be expired for this fixture.')
    before=transport.readback(op.logical_id)
    if before is None:raise AssertionError('Lost-ack recovery requires a real independently persisted acceptance.')
    with trusted_write(),operation_write(op.name,op.fencing_token):
        op.lease_until=now_datetime()-timedelta(seconds=1);op.save(ignore_permissions=True)
    frappe.db.commit()
    with patch.object(transport,'accept',side_effect=AssertionError('Readback recovery must never resend.')) as accept:
        result=outbox.deliver(op.name)
    frappe.db.rollback();after=frappe.get_doc('Cipher Integration Operation',op.name)
    receipt=json.loads(after.result_json)['receipt']
    if result['state']!='Succeeded' or receipt!=before or accept.call_count or transport.readback(op.logical_id)!=before:
        raise AssertionError('Stable-key reconciliation duplicated or changed the independently accepted delivery.')
    return {'schema':'cipher.r1.distribution-readback-native.v1','status':'passed','operation_id':op.name,'logical_key':op.logical_id,
            'state':after.state,'fencing_token':after.fencing_token,'acknowledgment':receipt,'new_accept_calls':0,
            'fixture_controlled_lease_expiry':True,'transport':'fixture','live_external_provider_qualified':False}


def prove_stale_worker_fence(private_manifest,operation_id):
    """Late completion with an old token cannot overwrite real sink success."""
    import frappe
    from .test_company_chain_acceptance import _load_fixture
    from cipher_aec.integrations import distribution_worker as worker
    fixture=_load_fixture(private_manifest);op=frappe.get_doc('Cipher Integration Operation',operation_id)
    if op.company!=fixture['company'] or op.actor_user!=fixture['users']['author']['user'] or op.kind!='company.proposal.fixture.v1' or op.state!='Succeeded' or op.fencing_token<2:
        raise RuntimeError('Fence proof requires the owned recovered successful operation.')
    before={key:op.get(key) for key in ('state','fencing_token','attempt_count','result_json','last_error_code','modified')}
    attempts=frappe.db.count('Cipher Delivery Attempt',{'operation':op.name})
    result=worker._record(op.name,op.fencing_token-1,'Failed',code='injected_stale_response')
    frappe.db.rollback();after=frappe.get_doc('Cipher Integration Operation',op.name)
    if result!={'state':'superseded'} or any(after.get(key)!=value for key,value in before.items()) or frappe.db.count('Cipher Delivery Attempt',{'operation':op.name})!=attempts:
        raise AssertionError('An obsolete response changed a newer canonical state or attempt history.')
    return {'schema':'cipher.r1.distribution-stale-fence-native.v1','status':'passed','operation_id':op.name,
            'state':after.state,'current_fence':after.fencing_token,'refused_fence':op.fencing_token-1,
            'native_result_and_attempt_history_unchanged':True,'transport':'fixture','live_external_provider_qualified':False}


def prove_completed_worker_no_resend(private_manifest,operation_id):
    import frappe
    from unittest.mock import patch
    from .test_company_chain_acceptance import _load_fixture
    from cipher_aec.integrations import distribution_transport as transport, outbox
    fixture=_load_fixture(private_manifest);op=frappe.get_doc('Cipher Integration Operation',operation_id)
    if op.company!=fixture['company'] or op.actor_user!=fixture['users']['author']['user'] or op.kind!='company.proposal.fixture.v1' or op.state!='Succeeded':
        raise RuntimeError('Only the owned already acknowledged recipient may test duplicate delivery.')
    original=op.result_json;attempts=op.attempt_count;ack=transport.readback(op.logical_id);frappe.db.commit()
    with patch.object(transport,'accept',side_effect=AssertionError('A completed recipient must never resend.')) as accept:
        result=outbox.deliver(op.name)
    frappe.db.rollback();after=frappe.get_doc('Cipher Integration Operation',op.name)
    if result!={'state':'Succeeded'} or accept.call_count or after.result_json!=original or after.attempt_count!=attempts or transport.readback(op.logical_id)!=ack:
        raise AssertionError('A duplicate recipient job changed or resent an acknowledged delivery.')
    return {'schema':'cipher.r1.distribution-completed-no-resend.v1','status':'passed','operation_id':op.name,
            'state':after.state,'sink_accept_calls':0,'original_receipt_unchanged':True,'transport':'fixture','live_external_provider_qualified':False}


def prove_refused_new_send(private_manifest,operation_id,scenario):
    """Real queued operation with real authority/cancel state; no sink accept."""
    import frappe
    from datetime import timedelta
    from unittest.mock import patch
    from .test_company_chain_acceptance import _load_fixture
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import current_actor, require_company
    from cipher_aec.integrations import distribution as service, distribution_contracts as rules, distribution_transport as transport, outbox
    fixture=_load_fixture(private_manifest);op=frappe.get_doc('Cipher Integration Operation',operation_id)
    if op.company!=fixture['company'] or op.actor_user!=fixture['users']['author']['user'] or op.kind!=rules.KIND or op.state!='Queued':
        raise RuntimeError('Only an owned fresh queued canonical delivery may test refusal.')
    payload=json.loads(op.payload_json);dispatch=service.raw('dispatch',payload['dispatch_id'],op.company)
    if transport.readback(op.logical_id) is not None:raise AssertionError('A refusal fixture must have no prior sink acceptance.')
    expected={'revoked_distribution':('Failed','capability_denied'),'cancelled':('Cancelled','distribution_cancelled'),
              'expired_fixture_clock':('Failed','distribution_mandate_expired')}
    if scenario not in expected:raise RuntimeError('Select one explicit bounded refusal scenario.')
    if scenario=='revoked_distribution':
        try:require_company(op.company,ability='commercial.distribute',actor=current_actor(op.actor_user))
        except DomainError as error:
            if error.code!='capability_denied':raise
        else:raise AssertionError('Actual requester distribution authority was not revoked.')
    if scenario=='cancelled' and service.cancellation(dispatch['id'],op.company) is None:
        raise AssertionError('Cancellation must first exist through the actual supported command.')
    frappe.db.commit()
    with patch.object(transport,'accept',side_effect=AssertionError('A refused new attempt must not reach acceptance.')) as accept:
        if scenario=='expired_fixture_clock':
            clock=rules.moment(dispatch['valid_until'])+timedelta(seconds=1)
            with patch.object(rules,'utc_now',return_value=clock):result=outbox.deliver(op.name)
        else:result=outbox.deliver(op.name)
    frappe.db.rollback();after=frappe.get_doc('Cipher Integration Operation',op.name)
    state,code=expected[scenario]
    if result['state']!=state or after.state!=state or after.last_error_code!=code or accept.call_count or transport.readback(op.logical_id) is not None:
        raise AssertionError('The new attempt was not refused under its exact current condition.')
    return {'schema':'cipher.r1.distribution-refused-send-native.v1','status':'passed','operation_id':op.name,'scenario':scenario,
            'state':after.state,'error_code':code,'sink_accept_calls':0,'sink_acceptance_absent':True,
            'fixture_clock_after_persisted_deadline':scenario=='expired_fixture_clock','transport':'fixture','live_external_provider_qualified':False}


def distribution_source_revocation_http(private_manifest,*,dispatch_context,pending_operation_id,repository,base_url,private_directory,
                                         bench_private_manifest,container='cipher-r0-runtime-1',site='cipher.localhost',include_history=True):
    """Private ack reconciliation cannot reopen public source entitlement."""
    import subprocess
    from .test_company_commercial_chain_http_acceptance import _rpc, _private_json, _pdf
    from .test_company_chain_acceptance import company_history_inventory
    fixture,rpc=_rpc(private_manifest,repository,base_url,private_directory)
    context=json.loads(Path(dispatch_context).read_text());company=fixture['company'];dispatch=context['dispatch'];instruction=context['instruction']
    if context['company']!=company or pending_operation_id not in {row['operation_id'] for row in context['deliveries']}:
        raise RuntimeError('Only the owned ambiguous accepted recipient may reconcile inside this privacy phase.')
    api='cipher_aec.integrations.distribution_api.';gov='cipher_aec.api.company_approvals.';docs='cipher_aec.documents.company_api.'
    prepared=context['issue']['prepared_output'];denied={'capability_denied','not_found'}
    protected_subjects={instruction['id'],dispatch['id'],context['packet']['id']}
    def protected(history):return {row['id']:row for row in history['items'] if row['subject_id'] in protected_subjects}
    def native(name,values):
        command=[str(Path(repository)/'apps/cipher/platform/deployment/docker-local.sh'),'exec','--workdir','/home/frappe/frappe-bench',container,
                 'bench','--site',site,'execute',name,'--kwargs',repr(values)]
        result=subprocess.run(command,capture_output=True,text=True,timeout=90)
        if result.returncode:raise RuntimeError('Private synthetic source fixture operation failed; values remain private.')
        return json.loads(result.stdout)
    def duty(active):return native('cipher_aec.tests.test_company_chain_acceptance.set_fixture_duty',
        {'private_manifest':bench_private_manifest,'role':'author','ability':'document.read','active':active})
    def receipt(command):return rpc.invoke('cipher_aec.api.company.operation',{'company':company,'operation_id':command['operation_id']})
    report={'schema':'cipher.r1.distribution-source-privacy-http.v1','status':'failed','fixture_id':fixture['fixture_id'],
            'started_at':datetime.now(timezone.utc).isoformat(),'live_external_provider_qualified':False,'history_qualified':False}
    try:
        rpc.login('author');before=rpc.invoke(api+'get_dispatch',{'company':company,'dispatch_id':dispatch['id']})
        if next(d['state'] for d in before['deliveries'] if d['operation_id']==pending_operation_id)!='Unknown':
            raise AssertionError('The internal reconciliation proof requires a real Unknown with prior acceptance.')
        original_create=receipt(context['create']);original_execute=receipt(context['execute'])
        history_before=protected(company_history_inventory(rpc,company)) if include_history else None
        if include_history and not any(row['subject_id']==dispatch['id'] for row in history_before.values()):raise AssertionError('The protected distribution event must be visible before revocation.')
        try:
            report['document_read_revoked']=duty(0)
            for method,values in ((api+'get_instruction',{'company':company,'instruction_id':instruction['id']}),
                                  (api+'get_dispatch',{'company':company,'dispatch_id':dispatch['id']}),
                                  (api+'list_dispatches',{'company':company,'issue_id':context['issue']['id'],'count_mode':'exact'}),
                                  (api+'get_recipient_delivery',{'company':company,'dispatch_id':dispatch['id'],'recipient_id':context['deliveries'][0]['recipient_id']}),
                                  (gov+'read_packet',{'company':company,'packet_id':context['packet']['id']}),
                                  (docs+'download_revision',{'company':company,'revision_id':prepared['revision_id']})):
                rpc.invoke(method,values,expected_codes=denied)
            for command in (context['create'],context['execute']):
                rpc.invoke('cipher_aec.api.company.operation',{'company':company,'operation_id':command['operation_id']},expected_codes=denied)
            rpc.invoke(api+'create_instruction',context['create'],expected_codes=denied)
            rpc.login('alias');rpc.invoke(gov+'execute_packet',context['execute'],expected_codes=denied)
            rpc.login('author')
            if include_history and protected(company_history_inventory(rpc,company)):raise AssertionError('History disclosed source-bearing distribution facts after current source revocation.')
            report['internal_reconciliation']=native('cipher_aec.tests.test_distribution_company_acceptance.reconcile_worker_fixture',
                {'private_manifest':bench_private_manifest,'operation_id':pending_operation_id})
            rpc.invoke(api+'get_dispatch',{'company':company,'dispatch_id':dispatch['id']},expected_codes=denied)
            rpc.login('reviewer');_pdf(rpc,prepared)
        finally:
            report['document_read_restored']=duty(1)
        rpc.login('author')
        if receipt(context['create'])!=original_create or receipt(context['execute'])!=original_execute:
            raise AssertionError('Source restoration changed the exact original instruction/consumption receipts.')
        if include_history and protected(company_history_inventory(rpc,company))!=history_before:raise AssertionError('Source restoration did not recover the same immutable protected history rows.')
        restored=rpc.invoke(api+'get_dispatch',{'company':company,'dispatch_id':dispatch['id']})
        acknowledgment=report['internal_reconciliation']['acknowledgment']
        if restored['state']!='SucceededFixture' or next(d['receipt']['receipt'] for d in restored['deliveries'] if d['operation_id']==pending_operation_id)!=acknowledgment:
            raise AssertionError('Restored public state differs from observational same-key reconciliation.')
        _pdf(rpc,prepared)
        report.update(status='passed',dispatch_id=dispatch['id'],restored_detail=restored,protected_history_rows=len(history_before) if include_history else None,
                      history_qualified=include_history,history_omission_reason=None if include_history else 'Known40second first-page history failure is preserved and awaits independent owner fix/qualification.',
                      exact_original_receipts_restored=True,internal_readback_is_not_new_delivery_or_source_entitlement=True)
        return report
    except Exception as error:report['failure_type']=type(error).__name__;raise
    finally:
        rpc.close();report['calls']=rpc.calls;report['schema_samples']=rpc.schema_samples;report['session_timings']=rpc.session_timings
        report['completed_at']=datetime.now(timezone.utc).isoformat()
        _private_json(rpc.work/('distribution-source-privacy-'+uuid4().hex+'.result.json'),report)


def run_distribution_read_models_http(private_manifest,*,dispatch_context,two_recipient_context,repository,base_url,private_directory):
    """Existing records only: canonical recipients and visible scoped pagination."""
    from cipher_aec.api.contracts import digest
    from .test_company_commercial_chain_http_acceptance import _rpc,_private_json
    fixture,rpc=_rpc(private_manifest,repository,base_url,private_directory)
    original=json.loads(Path(dispatch_context).read_text())
    alternate=json.loads(Path(two_recipient_context).read_text())
    company=fixture['company'];api='cipher_aec.integrations.distribution_api.'
    if original['company']!=company or alternate['company']!=company:raise RuntimeError('Use only the owned Company sources.')
    issue=original['issue'];other=alternate['issue']
    if issue['id']==other['id']:raise RuntimeError('Cursor binding needs distinct immutable Issues.')
    report={'schema':'cipher.r1.distribution-read-model-http.v1','status':'failed',
            'started_at':datetime.now(timezone.utc).isoformat(),'business_commands_sent':0}
    try:
        rpc.login('author')
        choices=rpc.invoke(api+'recipient_choices',{'company':company,'issue_id':other['id']})
        if choices['issue_id']!=other['id'] or choices['issue_digest']!=digest(other):raise AssertionError('Recipient choices retargeted the Issue.')
        expected=[{'id':digest({'schema':'cipher.issued.recipient.v1','recipient':row}),**row}
                  for row in other['prepared_output']['binding']['recipients']]
        if choices['recipients']!=expected or len(expected)!=2:raise AssertionError('Canonical original recipient identity/order changed.')
        register=rpc.invoke(api+'list_instructions',{'company':company,'limit':50,'count_mode':'exact'})
        if register['next_cursor'] is not None or register['total']!=len(register['items']):raise RuntimeError('Owned register must fit one complete bounded page.')
        all_rows={row['instruction']['id']:row for row in register['items']}
        if len(all_rows)!=len(register['items']) or original['instruction']['id'] not in all_rows:raise AssertionError('The saved original instruction is absent or duplicated.')
        for row in all_rows.values():
            if row['instruction']['company']!=company or row['instruction']['scope_type']!='Company' or row['instruction']['project'] is not None or row['version']!=digest(row['instruction']):
                raise AssertionError('Instruction register changed scope or immutable version.')
        filtered=rpc.invoke(api+'list_instructions',{'company':company,'issue_id':issue['id'],'limit':50,'count_mode':'exact'})
        expected_ids={key for key,row in all_rows.items() if row['instruction']['issue_id']==issue['id']}
        if {row['instruction']['id'] for row in filtered['items']}!=expected_ids or filtered['total']!=len(expected_ids) or filtered['next_cursor'] is not None:
            raise AssertionError('Exact Issue filter/count differs from authorized register.')
        first=rpc.invoke(api+'list_instructions',{'company':company,'issue_id':issue['id'],'limit':1,'count_mode':'exact'})
        if len(expected_ids)<2 or first['next_cursor'] is None:raise RuntimeError('Existing saved fixture must exercise a real next page.')
        second=rpc.invoke(api+'list_instructions',{'company':company,'issue_id':issue['id'],'limit':1,'count_mode':'exact','cursor':first['next_cursor']})
        if first['items'][0]['instruction']['id']==second['items'][0]['instruction']['id'] or first['total']!=second['total'] or first['total']!=len(expected_ids):
            raise AssertionError('Instruction keyset page repeated a row or changed exact total.')
        rpc.invoke(api+'list_instructions',{'company':company,'issue_id':other['id'],'limit':1,'count_mode':'exact','cursor':first['next_cursor']},expected_codes={'invalid_cursor'})
        foreign=fixture['other_company'] if 'other_company' in fixture else fixture['company_b']
        for method,values in [('recipient_choices',{'company':foreign,'issue_id':issue['id']}),('list_instructions',{'company':foreign,'issue_id':issue['id'],'count_mode':'exact'})]:
            rpc.invoke(api+method,values,expected_codes={'capability_denied','not_found'})
        rpc.login('outsider')
        rpc.invoke(api+'recipient_choices',{'company':foreign,'issue_id':issue['id']},expected_codes={'not_found'})
        rpc.invoke(api+'list_instructions',{'company':foreign,'issue_id':issue['id'],'count_mode':'exact'},expected_codes={'not_found'})
        empty=rpc.invoke(api+'list_instructions',{'company':foreign,'count_mode':'exact'})
        if empty['items'] or empty['total']!=0 or empty['next_cursor'] is not None:raise AssertionError('Foreign Company register exposed owned Company instructions.')
        for role in ('outsider','project_only'):
            rpc.login(role)
            rpc.invoke(api+'recipient_choices',{'company':company,'issue_id':issue['id']},expected_codes={'capability_denied','not_found'})
            rpc.invoke(api+'list_instructions',{'company':company,'count_mode':'exact'},expected_codes={'capability_denied','not_found'})
        report.update(status='passed',company=company,issue_id=issue['id'],canonical_recipient_count=len(expected),
                      existing_instruction_count=register['total'],filtered_instruction_count=filtered['total'],
                      original_instruction_and_version_preserved=all_rows[original['instruction']['id']]=={'instruction':original['instruction'],'version':digest(original['instruction'])})
        if not report['original_instruction_and_version_preserved']:raise AssertionError('Original saved instruction bytes changed.')
        return report
    except Exception as error:report.update(status='failed',failure_type=type(error).__name__);raise
    finally:
        rpc.close();report.update(calls=rpc.calls,schema_samples=rpc.schema_samples,session_timings=rpc.session_timings,completed_at=datetime.now(timezone.utc).isoformat())
        _private_json(rpc.work/('distribution-read-model-'+uuid4().hex+'.result.json'),report)


def read_current_ack_delta_http(private_manifest,*,baseline_path,context_paths,repository,base_url,private_directory,
                                legacy_cancel_context=None,legacy_cancel_baseline=None):
    """Read existing acknowledged operations and their exact original receipts."""
    from cipher_aec.api.contracts import digest
    from .test_company_commercial_chain_http_acceptance import _rpc,_private_json
    fixture,rpc=_rpc(private_manifest,repository,base_url,private_directory)
    baseline=json.loads(Path(baseline_path).read_text())['cases']
    if set(context_paths)!=set(baseline):raise RuntimeError('Read only the exact independently snapshotted cases.')
    api='cipher_aec.integrations.distribution_api.'
    report={'schema':'cipher.r1.distribution-current-ack-http.v1','status':'failed','business_commands_sent':0,
            'started_at':datetime.now(timezone.utc).isoformat(),'cases':{},'fault_sequence_repeated':False}
    try:
        rpc.login('author')
        for label,path in context_paths.items():
            context=json.loads(Path(path).read_text());known=baseline[label];company=fixture['company']
            if context['company']!=company or [row['operation_id'] for row in context['deliveries']]!=[known['operation_id']]:
                raise RuntimeError('A current-state delta cannot retarget the original Company or operation.')
            instruction=rpc.invoke(api+'get_instruction',{'company':company,'instruction_id':context['instruction']['id']})
            if instruction!={'instruction':context['instruction'],'version':digest(context['instruction'])}:raise AssertionError('Original instruction/version changed.')
            detail=rpc.invoke(api+'get_dispatch',{'company':company,'dispatch_id':context['dispatch']['id']})
            if detail['dispatch']!=context['dispatch'] or detail['state']!='SucceededFixture' or len(detail['deliveries'])!=1:
                raise AssertionError('Current acknowledged dispatch changed its immutable identity or state.')
            delivery=detail['deliveries'][0]
            if delivery['operation_id']!=known['operation_id'] or delivery['state']!='Succeeded' or delivery.get('logical_key')!=known['logical_key'] or delivery.get('payload_hash')!=known['payload_hash']:
                raise AssertionError('Current delivery omitted or changed exact operation keys.')
            if delivery['receipt']!={'mode':'fixture','receipt':known['acknowledgment']}:raise AssertionError('Current acknowledgment differs from original independent sink bytes.')
            recipient=rpc.invoke(api+'get_recipient_delivery',{'company':company,'dispatch_id':context['dispatch']['id'],'recipient_id':delivery['recipient_id']})
            if recipient!=delivery:raise AssertionError('Recipient readback differs from full current delivery.')
            hashes={}
            for kind,original in known['command_receipts'].items():
                current=rpc.invoke('cipher_aec.api.company.operation',{'company':company,'operation_id':original['operation_id']})
                expected={**original['result'],'operation':{'id':original['operation_id'],'status':'succeeded','replayed':True}}
                if current!=expected:raise AssertionError('Original immutable command receipt changed after current-read validation.')
                if digest(original['result'])!=original['result_hash']:raise AssertionError('Independent original receipt baseline lost integrity.')
                hashes[kind]=original['result_hash']
            report['cases'][label]={'operation_id':known['operation_id'],'dispatch_id':context['dispatch']['id'],
                'logical_key':delivery['logical_key'],'payload_hash':delivery['payload_hash'],
                'acknowledgment':known['acknowledgment'],'original_command_receipt_hashes':hashes}
        if legacy_cancel_context is not None:
            context=json.loads(Path(legacy_cancel_context).read_text());legacy=json.loads(Path(legacy_cancel_baseline).read_text())
            if context['company']!=fixture['company']:raise RuntimeError('Legacy cancellation must remain in the owned Company.')
            current=rpc.invoke('cipher_aec.api.company.operation',{'company':context['company'],'operation_id':legacy['operation_id']})
            if current!={**legacy['result'],'operation':{'id':legacy['operation_id'],'status':'succeeded','replayed':True}} or digest(legacy['result'])!=legacy['result_hash']:
                raise AssertionError('Original legacy cancellation receipt changed under new current-read validator.')
            cancelled=rpc.invoke(api+'get_dispatch',{'company':context['company'],'dispatch_id':context['dispatch']['id']})
            if cancelled['dispatch']!=context['dispatch'] or cancelled['state']!='Cancelled' or any(row['state']!='Cancelled' for row in cancelled['deliveries']):
                raise AssertionError('Current cancelled dispatch changed its immutable identity or terminal refusal.')
            if any(not row.get('logical_key') or not row.get('payload_hash') for row in cancelled['deliveries']):raise AssertionError('Current cancelled read omitted operation keys.')
            report['legacy_cancellation']={'dispatch_id':context['dispatch']['id'],'original_command_receipt_hash':legacy['result_hash'],
                'current_state':cancelled['state'],'historical_embedded_receipt_unchanged':True}
        if rpc.journal:raise AssertionError('A read-only delta unexpectedly authored a business command.')
        report['status']='passed';return report
    except Exception as error:report.update(status='failed',failure_type=type(error).__name__);raise
    finally:
        rpc.close();report.update(calls=rpc.calls,schema_samples=rpc.schema_samples,session_timings=rpc.session_timings,completed_at=datetime.now(timezone.utc).isoformat())
        _private_json(rpc.work/('distribution-current-ack-'+uuid4().hex+'.result.json'),report)


def read_company_approval_inbox_http(private_manifest,*,granted_context,repository,base_url,private_directory):
    """Normal none-count inbox pages and original Granted packet; no decisions."""
    from .test_company_commercial_chain_http_acceptance import _rpc,_private_json
    fixture,rpc=_rpc(private_manifest,repository,base_url,private_directory)
    original=json.loads(Path(granted_context).read_text());company=fixture['company']
    if original['company']!=company or original['state']!='Granted':raise RuntimeError('Use the retained original granted UI packet.')
    api='cipher_aec.api.company_approvals.'
    report={'schema':'cipher.r1.company-approval-inbox-http.v1','status':'failed','started_at':datetime.now(timezone.utc).isoformat(),
            'business_commands_sent':0,'decisions_or_executions_attempted':False}
    def expected_packet(value):
        for key,expected in [('id',original['packet_id']),('manifest_hash',original['manifest_hash']),('action',original['action']),('state','Granted')]:
            if value[key]!=expected:raise AssertionError('Original granted packet changed '+key+'.')
        if value['company']!=company or value['scope_type']!='Company' or value['project'] is not None or value['subject']['id']!=original['subject_id'] or value['subject']['type']!=original['subject_type']:
            raise AssertionError('Original granted packet changed source or scope.')
    try:
        rpc.login('author')
        first=rpc.invoke(api+'list_packets',{'company':company,'limit':10})
        if first['count_mode']!='none' or first['total'] is not None or first['limit']!=10 or len(first['items'])!=10 or first['next_cursor'] is None:
            raise AssertionError('Normal inbox did not return a bounded none-count page with real continuation.')
        second=rpc.invoke(api+'list_packets',{'company':company,'limit':10,'count_mode':'none','cursor':first['next_cursor']})
        if second['total'] is not None or second['count_mode']!='none' or len(second['items'])>10:
            raise AssertionError('Next normal inbox page changed count or page contract.')
        ids_first={row['id'] for row in first['items']};ids_second={row['id'] for row in second['items']}
        if len(ids_first)!=len(first['items']) or len(ids_second)!=len(second['items']) or ids_first&ids_second:
            raise AssertionError('Inbox keyset pages duplicate a packet.')
        if any(row['company']!=company or row.get('scope_type')!='Company' or row['project'] is not None for row in first['items']+second['items']):
            raise AssertionError('Inbox page changed Company scope.')
        author=rpc.invoke(api+'read_packet',{'company':company,'packet_id':original['packet_id']});expected_packet(author)
        if not author['actions']['can_execute'] or author['actions']['can_decide']:raise AssertionError('Original independently granted requester packet is not executable.')
        rpc.login('reviewer')
        reviewer=rpc.invoke(api+'read_packet',{'company':company,'packet_id':original['packet_id']});expected_packet(reviewer)
        if reviewer['actions']['can_execute']:raise AssertionError('Reviewer inherited requester execution authority.')
        if {key:value for key,value in reviewer.items() if key!='actions'}!={key:value for key,value in author.items() if key!='actions'}:
            raise AssertionError('Reviewer read changed the original immutable manifest/decision/source facts.')
        rpc.invoke(api+'list_packets',{'company':company,'limit':10,'count_mode':'none','cursor':first['next_cursor']},expected_codes={'invalid_cursor'})
        own=rpc.invoke(api+'list_packets',{'company':company,'limit':10,'count_mode':'none'})
        if own['total'] is not None or len(own['items'])>10:raise AssertionError('Reviewer normal inbox changed bounded none-count contract.')
        for role in ('outsider','project_only'):
            rpc.login(role)
            rpc.invoke(api+'list_packets',{'company':company,'limit':10,'count_mode':'none'},expected_codes={'capability_denied','not_found'})
            rpc.invoke(api+'read_packet',{'company':company,'packet_id':original['packet_id']},expected_codes={'capability_denied','not_found'})
        rpc.login('author');after=rpc.invoke(api+'read_packet',{'company':company,'packet_id':original['packet_id']})
        if after!=author or rpc.journal:raise AssertionError('Read-only inbox delta changed original Granted packet or authored a command.')
        report.update(status='passed',company=company,packet_id=original['packet_id'],manifest_hash=original['manifest_hash'],
            original_granted_packet_unchanged=True,first_page_items=len(first['items']),second_page_items=len(second['items']),
            count_mode='none',reviewer_cannot_execute=True,reviewer_cannot_reuse_author_cursor=True)
        return report
    except Exception as error:report.update(status='failed',failure_type=type(error).__name__);raise
    finally:
        rpc.close();report.update(calls=rpc.calls,schema_samples=rpc.schema_samples,session_timings=rpc.session_timings,completed_at=datetime.now(timezone.utc).isoformat())
        _private_json(rpc.work/('company-approval-inbox-'+uuid4().hex+'.result.json'),report)
