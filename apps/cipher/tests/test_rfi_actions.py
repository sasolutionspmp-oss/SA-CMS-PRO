"""Actual RFI effects, independent native grants and original API receipts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from apps.cipher.service import Cipher
from apps.cipher.rfi_receipts import (RFIReceiptError, RFIReceipts,
    register_rfi_receipts_schema, rfi_receipt_inventory_proof)


class RFIReceiptMetadataTests(unittest.TestCase):
    def setUp(self):
        register_rfi_receipts_schema()
        self.c = Cipher()
        self.addCleanup(self.c.db.close)

    def test_import_is_inert_without_domain_or_catalog_registration(self):
        script = """import json
from apps.cipher.core.db import SCHEMA_CATALOG
before=tuple((v,n,tuple(s)) for v,n,s in SCHEMA_CATALOG)
import apps.cipher.rfi_receipts
print(json.dumps({'unchanged':before==tuple((v,n,tuple(s)) for v,n,s in SCHEMA_CATALOG)}))
"""
        result = subprocess.run([sys.executable, "-c", script], text=True, capture_output=True, check=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3])})
        self.assertEqual(json.loads(result.stdout), {"unchanged": True})

    def test_pure_metadata_inventory_never_looks_up_domain_or_other_namespaces(self):
        before = tuple(self.c.db.conn.iterdump())
        with patch.object(self.c, "plugin", side_effect=AssertionError("domain lookup")), \
             patch("apps.cipher.rfi_receipts.require_other_namespaces", side_effect=AssertionError("namespace lookup")):
            self.assertEqual(rfi_receipt_inventory_proof(self.c.db, self.c.audit), [])
        self.assertEqual(before, tuple(self.c.db.conn.iterdump()))

    def test_extreme_named_admission_refuses_without_metadata_sized_allocation(self):
        for version in (9223372036854775807, -9223372036854775808):
            with self.subTest(version=version):
                with self.c.db.transaction():
                    self.c.db.execute("UPDATE schema_version SET version=? WHERE name='rfi_practice_action_receipts'", (version,))
                    with patch("apps.cipher.rfi_receipts.range", side_effect=AssertionError("unbounded allocation"), create=True):
                        with self.assertRaises(RFIReceiptError):
                            RFIReceipts(self.c.db, self.c.audit).verify_integrity()
                    self.c.db.execute("UPDATE schema_version SET version=79 WHERE name='rfi_practice_action_receipts'")

    def test_missing_named_receipt_admission_fails_closed(self):
        self.c.db.execute("DELETE FROM schema_version WHERE name='rfi_practice_action_receipts'")
        with self.assertRaises(RFIReceiptError):
            RFIReceipts(self.c.db, self.c.audit).verify_integrity()
        with self.assertRaises(RFIReceiptError):
            rfi_receipt_inventory_proof(self.c.db, self.c.audit)

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from apps.cipher.ap_contract import APRefusal
from apps.cipher.core.ids import canonical_json, loads
from apps.cipher.rfi_actions import RFIActionRunner
from apps.cipher.rfi_contract import RFIContract
from apps.cipher.rfi_preflight import RFIPreflight
from apps.cipher.rfi_practice_fixture import make_rfi_practice_fixture, STAFF_LOGIN, PM_LOGIN, REVIEWER_LOGIN, BOOTSTRAP_LOGIN


class RFIActionsTests(unittest.TestCase):
    def setUp(self):
        self.c=make_rfi_practice_fixture();self.addCleanup(self.c.db.close)
        self.domain=self.c.plugin('rfi_controls');self.records=self.c.rfi_practice_records
        self.project=self.records['project_id'];self.people=self.c.rfi_practice_persona_people
        self.staff,self.pm,self.reviewer=(self.people[key]['person_id'] for key in ('staff','pm','reviewer'))
        secret=b'rfi-actions-private-server-key-at-least-32-bytes'
        self.contract=RFIContract(self.c,secret=secret);self.preflight=RFIPreflight(self.c,self.contract,secret=secret)
        self.runner=RFIActionRunner(self.c,self.contract,self.preflight)
        self.body={'subject':'Synthetic drain alignment','question':'Confirm the authored drain detail at grid C4.',
                   'drawingRevisionIds':[self.records['drawing_revision_id']],'documentRevisionIds':[self.records['document_revision_id']]}
        self.response={'responseText':'Use the documented alignment; impacts await separate review.','costImpact':'1234.56','scheduleImpactDays':3}
        self.requests=[]
    def snapshot(self):return tuple(self.c.db.conn.iterdump()),tuple(self.c.provider.submissions)
    def prepared(self,person,action,resource,body):
        before=self.snapshot();review=self.preflight.review(person,action,resource,body)
        self.assertTrue(review['allowed'],review);self.assertEqual(before,self.snapshot())
        return (person,action,resource,{**body,'fingerprint':review['fingerprint']},str(uuid4()),review['resourceVersion'])
    def invoke(self,request):
        person,action,resource,body,key,version=request
        return self.runner.run(person,action,resource,body,repeatability_key=key,if_match=version)
    def act(self,person,action,resource,body):
        request=self.prepared(person,action,resource,body);out=self.invoke(request);self.requests.append((request,out));return out['result']
    def created(self):return self.act(self.staff,'rfi.create',self.project,self.body)['rfiId']
    def response_approval(self):
        rid=self.created();self.act(self.staff,'rfi.draftResponse',rid,self.response)
        aid=self.act(self.pm,'rfi.requestResponse',rid,{})['approvalId'];return rid,aid
    def answered(self):
        rid,aid=self.response_approval();self.act(self.reviewer,'rfi.approveResponse',aid,{})
        self.act(self.pm,'rfi.applyResponse',aid,{});return rid,aid
    def distributed(self):
        rid,response=self.answered();self.act(self.pm,'rfi.setDistribution',rid,{'recipients':[self.records['allowed_recipients'][0]]})
        aid=self.act(self.pm,'rfi.requestDistribution',rid,{})['approvalId']
        self.act(self.reviewer,'rfi.approveDistribution',aid,{});self.act(self.pm,'rfi.distribute',aid,{})
        return rid,response,aid
    def test_genuine_nine_action_journey_and_all_original_retries_after_later_state(self):
        rid,response,distribution=self.distributed()
        self.assertEqual(self.c.approvals.get(response)['status'],'consumed');self.assertEqual(self.c.approvals.get(distribution)['status'],'consumed')
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM journals'),0);self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM changes'),0)
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM field_rfi_distributions'),1)
        self.domain.set_distribution_list(rid,{'recipients':[self.records['allowed_recipients'][1]]},actor=PM_LOGIN)
        self.c.evidence.add_revision(document_id=self.records['document_id'],content='Genuine later authored supporting note',actor=PM_LOGIN)
        before=self.snapshot()
        for request,original in self.requests:
            replay=self.invoke(request)
            self.assertEqual(replay['result'],original['result']);self.assertEqual(replay['receiptId'],original['receiptId'])
            self.assertIs(replay['replayed'],True);self.assertIs(replay['effectApplied'],False)
        self.assertEqual(self.snapshot(),before);self.assertTrue(self.runner.integrity_checks()['ok'])
    def test_concurrent_same_request_records_one_original_effect(self):
        request=self.prepared(self.staff,'rfi.create',self.project,self.body)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.invoke(request),range(2)))
        self.assertEqual(results[0]['receiptId'],results[1]['receiptId']);self.assertEqual(sum(r['effectApplied'] for r in results),1)
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM field_rfis'),1)
    def test_cross_action_or_changed_typed_request_key_conflicts_before_effect(self):
        rid=self.created();request,original=self.requests[-1];before=self.snapshot()
        changed=(*request[:3],{**request[3],'question':'A different question'},*request[4:])
        with self.assertRaises(APRefusal) as error:self.invoke(changed)
        self.assertEqual(error.exception.status,409)
        nextreq=self.prepared(self.staff,'rfi.draftResponse',rid,self.response);nextreq=(*nextreq[:4],request[4],nextreq[5])
        with self.assertRaises(APRefusal) as error:self.invoke(nextreq)
        self.assertEqual(error.exception.status,409);self.assertEqual(before,self.snapshot())
    def test_current_authority_checked_before_original_receipt_disclosure(self):
        self.created();request,_=self.requests[-1]
        self.c.plugin('people').end_membership(STAFF_LOGIN,self.project,reason='Genuine departed project staff',actor=BOOTSTRAP_LOGIN)
        with patch.object(self.runner.receipts,'find',side_effect=AssertionError('receipt disclosure')) as lookup:
            with self.assertRaises(APRefusal):self.invoke(request)
            lookup.assert_not_called()
    def test_callback_cannot_change_receipt_person_binding_or_returned_metadata(self):
        request=self.prepared(self.staff,'rfi.create',self.project,self.body);before=self.snapshot();original=self.runner.receipts.record
        def wrong_person(**kwargs):return original(**{**kwargs,'person_id':self.reviewer})
        with patch.object(self.runner.receipts,'record',side_effect=wrong_person):
            with self.assertRaises(APRefusal):self.invoke(request)
        self.assertEqual(before,self.snapshot())
        def returned_lie(**kwargs):return {**original(**kwargs),'receipt_hash':'not-the-stored-hash'}
        with patch.object(self.runner.receipts,'record',side_effect=returned_lie):
            with self.assertRaises(APRefusal):self.invoke(request)
        self.assertEqual(before,self.snapshot());self.assertTrue(self.invoke(request)['effectApplied'])
    def test_receipt_late_audit_failure_rolls_back_caught_outer_transaction(self):
        request=self.prepared(self.staff,'rfi.create',self.project,self.body);before=self.snapshot();record=self.c.audit.record
        def late(actor,action,*args,**kwargs):
            if action=='rfi.practice_action_recorded':raise RuntimeError('late receipt fault')
            return record(actor,action,*args,**kwargs)
        with self.c.db.transaction():
            with patch.object(self.c.audit,'record',side_effect=late):
                with self.assertRaises(APRefusal):self.invoke(request)
        self.assertEqual(before,self.snapshot());self.assertTrue(self.invoke(request)['effectApplied'])
    def test_exact_typed_result_rejects_numeric_alias_or_unrelated_audited_effect(self):
        request=self.prepared(self.staff,'rfi.create',self.project,self.body);before=self.snapshot();apply=self.runner._apply
        def alias(*args):
            result,source=apply(*args);result['journalDelta']=False;return result,source
        with patch.object(self.runner,'_apply',side_effect=alias):
            with self.assertRaises(APRefusal):self.invoke(request)
        self.assertEqual(before,self.snapshot())
        def extra(*args):
            result,source=apply(*args);self.c.audit.record(STAFF_LOGIN,'extra.unreviewed','project',self.project,{})
            return result,source
        with patch.object(self.runner,'_apply',side_effect=extra):
            with self.assertRaises(APRefusal):self.invoke(request)
        self.assertEqual(before,self.snapshot())
    def test_original_source_and_command_tamper_refuse_replay(self):
        self.answered();request,_=self.requests[-1];approval=request[2]
        self.c.db.execute('UPDATE idempotency SET payload_hash=? WHERE op_id=?',('tampered','exec:'+approval))
        before=self.snapshot()
        with self.assertRaises(APRefusal):self.invoke(request)
        self.assertEqual(before,self.snapshot());self.assertFalse(self.runner.integrity_checks()['ok'])
    def test_draft_invalidation_is_disclosed_and_original_pending_result_survives(self):
        rid,aid=self.response_approval();request,original=self.requests[-1]
        self.act(self.staff,'rfi.draftResponse',rid,{**self.response,'responseText':'Genuine different proposed response.'})
        self.assertEqual(self.c.approvals.get(aid)['status'],'invalidated')
        self.assertEqual(self.invoke(request)['result'],original['result'])

    def test_outer_commit_and_response_assembly_failures_restore_same_request(self):
        import sqlite3
        request=self.prepared(self.staff,'rfi.create',self.project,self.body);before=self.snapshot()
        execute=self.c.db.conn.execute
        def fail_commit(sql,*args,**kwargs):
            if sql=='COMMIT':raise sqlite3.OperationalError('Injected commit fault')
            return execute(sql,*args,**kwargs)
        with patch.object(self.c.db.conn,'execute',side_effect=fail_commit):
            with self.assertRaises(APRefusal):self.invoke(request)
        self.assertEqual(before,self.snapshot())
        with patch.object(self.runner,'_response',side_effect=RuntimeError('Injected response assembly fault')):
            with self.assertRaises(APRefusal):self.invoke(request)
        self.assertEqual(before,self.snapshot());self.assertTrue(self.invoke(request)['effectApplied'])

    def test_grant_and_application_late_faults_preserve_original_grant_and_all_sources(self):
        rid,aid=self.response_approval();request=self.prepared(self.reviewer,'rfi.approveResponse',aid,{})
        audit=self.c.audit.record
        for phase in ('grant','apply'):
            with self.subTest(phase=phase):
                target='rfi.review_granted' if phase=='grant' else 'command.executed'
                def fail(actor,action,*args,**kwargs):
                    if action==target:raise RuntimeError('Injected late '+phase+' fault')
                    return audit(actor,action,*args,**kwargs)
                before=self.snapshot()
                with self.c.db.transaction():
                    with patch.object(self.c.audit,'record',side_effect=fail):
                        with self.assertRaises(APRefusal):self.invoke(request)
                    self.assertEqual(before,self.snapshot())
                self.assertEqual(self.c.approvals.get(aid)['status'],'pending' if phase=='grant' else 'granted')
                self.invoke(request)
                if phase=='grant':request=self.prepared(self.pm,'rfi.applyResponse',aid,{})
        self.assertEqual(self.c.approvals.get(aid)['status'],'consumed')

    def test_unreviewed_schema_and_second_genuine_rfi_effect_roll_back(self):
        request=self.prepared(self.staff,'rfi.create',self.project,self.body);before=self.snapshot();apply=self.runner._apply
        for fault in ('schema','second'):
            with self.subTest(fault=fault):
                def extra(*args):
                    result,source=apply(*args)
                    if fault=='schema':self.c.db.execute('CREATE TABLE unreviewed_rfi_effect(id TEXT)')
                    else:self.domain.create(self.project,{**self.body,'subject':'Another unreviewed question'},actor=STAFF_LOGIN)
                    return result,source
                with patch.object(self.runner,'_apply',side_effect=extra):
                    with self.assertRaises(APRefusal):self.invoke(request)
                self.assertEqual(before,self.snapshot())

    def test_partial_effect_with_fabricated_typed_stale_cannot_commit_controls(self):
        from apps.cipher.core.approvals import StaleApprovalError
        request=self.prepared(self.staff,'rfi.create',self.project,self.body);before=self.snapshot();apply=self.runner._apply
        def partial(*args):
            apply(*args);raise StaleApprovalError('Unverified partial effect')
        with patch.object(self.runner,'_apply',side_effect=partial):
            with self.assertRaises(APRefusal):self.invoke(request)
        self.assertEqual(before,self.snapshot())

    def test_request_deadline_extension_and_shortening_refused_for_both_operations(self):
        import datetime
        rid=self.created();self.act(self.staff,'rfi.draftResponse',rid,self.response)
        native=self.c.approvals.request
        for action in ('rfi.requestResponse','rfi.requestDistribution'):
            if action=='rfi.requestDistribution':
                aid=self.act(self.pm,'rfi.requestResponse',rid,{})['approvalId']
                self.act(self.reviewer,'rfi.approveResponse',aid,{});self.act(self.pm,'rfi.applyResponse',aid,{})
                self.act(self.pm,'rfi.setDistribution',rid,{'recipients':[self.records['allowed_recipients'][0]]})
            request=self.prepared(self.pm,action,rid,{})
            for seconds in (31536000,-60):
                with self.subTest(action=action,seconds=seconds):
                    def changed(manifest,**kwargs):
                        from apps.cipher.core.ids import parse_iso
                        expiry=parse_iso(manifest['expires_at'])+datetime.timedelta(seconds=seconds)
                        return native({**manifest,'expires_at':expiry.isoformat().replace('+00:00','Z')},**kwargs)
                    before=self.snapshot()
                    with self.c.db.transaction():
                        with patch.object(self.c.approvals,'request',side_effect=changed):
                            with self.assertRaises(APRefusal):self.invoke(request)
                        self.assertEqual(before,self.snapshot())

    def test_native_deadline_generation_window_and_fractional_policy_are_preserved(self):
        import datetime,time
        from apps.cipher.core.ids import utcnow
        from apps.cipher.domain import field
        rid=self.created();self.act(self.staff,'rfi.draftResponse',rid,self.response)
        native=field.build_manifest
        def fractional(**kwargs):
            result=native(**kwargs);result['expires_at']=(utcnow()+datetime.timedelta(seconds=1200.2)).isoformat().replace('+00:00','Z');return result
        for action in ('rfi.requestResponse','rfi.requestDistribution'):
            if action=='rfi.requestDistribution':
                aid=self.requests[-1][1]['result']['approvalId'];self.act(self.reviewer,'rfi.approveResponse',aid,{})
                self.act(self.pm,'rfi.applyResponse',aid,{})
                self.act(self.pm,'rfi.setDistribution',rid,{'recipients':[self.records['allowed_recipients'][0]]})
            with patch.object(field,'build_manifest',side_effect=fractional):
                request=self.prepared(self.pm,action,rid,{})
                apply=self.runner._apply
                def delay(*args):time.sleep(0.05);return apply(*args)
                with patch.object(self.runner,'_apply',side_effect=delay):out=self.invoke(request)
                self.requests.append((request,out));self.assertEqual(out['result']['status'],'pending')
                self.assertEqual(self.invoke(request)['result'],out['result'])

    def test_stale_or_expired_review_refuses_without_rewriting_original_request(self):
        import datetime
        from apps.cipher.core.ids import parse_iso
        rid,aid=self.response_approval();request=self.prepared(self.reviewer,'rfi.approveResponse',aid,{})
        expiry=parse_iso(self.c.approvals.get(aid)['expires_at'])+datetime.timedelta(seconds=1);before=self.snapshot()
        with patch('apps.cipher.domain.rfi_controls.utcnow',return_value=expiry):
            with self.assertRaises(APRefusal):self.invoke(request)
        self.assertEqual(before,self.snapshot());self.assertEqual(self.c.approvals.get(aid)['status'],'pending')
        self.c.evidence.add_revision(document_id=self.records['document_id'],content='Genuine changed supporting evidence',actor=PM_LOGIN)
        before=self.snapshot()
        with self.assertRaises(APRefusal):self.invoke(request)
        self.assertEqual(before,self.snapshot());self.assertEqual(self.c.approvals.get(aid)['status'],'pending')

    def test_receipt_callback_cannot_rebind_body_or_mutate_source_or_stored_row(self):
        from apps.cipher.core.ids import hash_json
        request=self.prepared(self.staff,'rfi.create',self.project,self.body);before=self.snapshot();record=self.runner.receipts.record
        for fault in ('version','body','source','stored'):
            with self.subTest(fault=fault):
                def changed(**kwargs):
                    if fault in ('version','body'):
                        binding=loads(canonical_json(kwargs['binding']))
                        if fault=='version':binding['originalIfMatch']='changed-version'
                        else:binding['canonicalTypedBody']['question']='Changed question'
                        return record(**{**kwargs,'binding':binding})
                    row=record(**kwargs)
                    if fault=='source':kwargs['source']['sourceHash']='changed-in-place'
                    else:
                        self.c.db.execute('DROP TRIGGER rfi_action_receipts_no_update')
                        self.c.db.execute('UPDATE rfi_action_receipts SET actor_login=? WHERE id=?',(REVIEWER_LOGIN,row['id']))
                    return row
                with patch.object(self.runner.receipts,'record',side_effect=changed):
                    with self.assertRaises(APRefusal):self.invoke(request)
                self.assertEqual(before,self.snapshot())

    def test_legitimate_expiry_between_native_check_and_grant_commits_only_terminal_refusal(self):
        import time
        from apps.cipher.core.ids import parse_iso,utcnow
        from apps.cipher.domain import field
        rid=self.created();self.act(self.staff,'rfi.draftResponse',rid,self.response)
        builder=field.build_manifest
        def short(**kwargs):return builder(**{**kwargs,'expiry_seconds':4})
        with patch.object(field,'build_manifest',side_effect=short):
            aid=self.act(self.pm,'rfi.requestResponse',rid,{})['approvalId']
            request=self.prepared(self.reviewer,'rfi.approveResponse',aid,{})
            grant=self.c.approvals.grant;deadline=parse_iso(self.c.approvals.get(aid)['expires_at'])
            def late(*args,**kwargs):
                time.sleep(max(0,(deadline-utcnow()).total_seconds())+0.03)
                return grant(*args,**kwargs)
            with patch.object(self.c.approvals,'grant',side_effect=late):
                with self.assertRaises(APRefusal) as refusal:self.invoke(request)
        self.assertEqual(refusal.exception.status,423);self.assertEqual(self.c.approvals.get(aid)['status'],'expired')
        self.assertEqual(self.c.plugin('field').rfi(rid)['status'],'open');self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM idempotency WHERE op_id=?',('exec:'+aid,)),0)
        self.domain.draft_response(rid,{**self.response,'responseText':'Genuine later proposal after expiry'},actor=STAFF_LOGIN)
        before=self.snapshot()
        with self.assertRaises(APRefusal) as replay:self.invoke(request)
        self.assertTrue(replay.exception.replayed);self.assertEqual(replay.exception.receipt_id,refusal.exception.receipt_id)
        self.assertEqual(before,self.snapshot());self.assertTrue(self.runner.integrity_checks()['ok'])

    def test_original_receipts_survive_legitimate_later_restricted_rights(self):
        rid=self.created();request,original=self.requests[-1]
        rights=self.c.plugin('rights')
        license=rights.register_license('Synthetic','Restricted authored reference','1','Holder',['internal_reference'],actor=BOOTSTRAP_LOGIN)
        rights.tag_document(self.records['document_id'],license['id'],actor=BOOTSTRAP_LOGIN)
        before=self.snapshot();replay=self.invoke(request)
        self.assertEqual(replay['result'],original['result']);self.assertEqual(before,self.snapshot())
        review=self.preflight.review(self.staff,'rfi.draftResponse',rid,self.response)
        self.assertFalse(review['allowed']);self.assertEqual(before,self.snapshot())

    def test_creation_source_cannot_record_unreviewed_original_rights(self):
        request=self.prepared(self.staff,'rfi.create',self.project,self.body);before=self.snapshot();put=self.domain._put
        def changed(kind,body,actor):
            if kind=='sources':
                body=loads(canonical_json(body));body['rightsAtCreation'][0]['allowed']=False
            return put(kind,body,actor)
        with patch.object(self.domain,'_put',side_effect=changed):
            with self.assertRaises(APRefusal):self.invoke(request)
        self.assertEqual(before,self.snapshot())
