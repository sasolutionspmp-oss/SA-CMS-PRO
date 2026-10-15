"""One actual person's RFI UUID cannot cross financial or library workflows."""
import unittest
from unittest.mock import patch
from uuid import uuid4
from apps.cipher.ap_contract import APRefusal
from apps.cipher.accounting_worker import WorkerHeld
from apps.cipher.core.api_receipts import APIActionReceipts, APIRepeatabilityConflict
from apps.cipher.core.ids import loads
from apps.cipher.tests import test_ar_namespace as ar_tests
from apps.cipher.rfi_contract import RFIContract
from apps.cipher.rfi_preflight import RFIPreflight
from apps.cipher.rfi_actions import RFIActionRunner
from apps.cipher.library_contract import LibraryContract
from apps.cipher.library_preflight import LibraryPreflight
from apps.cipher.library_actions import LibraryActionRunner

class RFINamespaceTests(unittest.TestCase):
    secret=b'actual-shared-person-RFI-AP-AR-library-private-key'
    state=ar_tests.ARNamespaceTests.state
    ap_request=ar_tests.ARNamespaceTests.ap_request
    ar_request=ar_tests.ARNamespaceTests.ar_request
    commercial_request=ar_tests.ARNamespaceTests.commercial_request
    accounting_request=ar_tests.ARNamespaceTests.accounting_request
    assert_conflict_without_change=ar_tests.ARNamespaceTests.assert_conflict_without_change
    remove_with_original_guards=ar_tests.ARNamespaceTests.remove_with_original_guards
    def setUp(self):
        ar_tests.ARNamespaceTests.setUp(self)
        c=self.c;people=c.plugin('people');project=self.ar_project
        people.add_membership('practice.pm',project,actor='practice.bootstrap')
        grant=people.request_grant('practice.pm','pm',project_id=project,reason='Synthetic independent drawing and RFI review',actor='practice.bootstrap')
        approval=c.request_approval('people.grant_role',grant['id'],actor_role='owner',requested_by='practice.reviewer')
        c.approve(approval['id'],approver='practice.bootstrap',approver_role='owner');c.execute(approval['id'],actor='practice.bootstrap')
        document=c.evidence.register_document(project_id=project,kind='drawing',title='Synthetic issued namespace detail',actor='practice.accountant')
        evidence=c.evidence.add_revision(document_id=document['id'],content='Synthetic authored namespace detail A',actor='practice.accountant')
        drawings=c.plugin('drawing');drawing=drawings.register_drawing(project,'NS-01','Synthetic namespace issued drawing','Civil',actor='practice.accountant')
        revision=drawings.add_revision(drawing['id'],'A',evidence['id'],actor='practice.accountant')
        issue=c.request_approval('drawing.issue',revision['id'],actor_role='pm',requested_by='practice.accountant')
        c.approve(issue['id'],approver='practice.pm',approver_role='pm');c.execute(issue['id'],actor='practice.accountant',period_id='2026-10')
        self.rfi_input={'subject':'Synthetic shared-person question','question':'Confirm this synthetic issued detail.',
                        'drawingRevisionIds':[revision['id']],'documentRevisionIds':[self.ar_input['reviewRevisionId']]}
        contract=RFIContract(c,secret=self.secret);self.rfi_preflight=RFIPreflight(c,contract,secret=self.secret);self.rfi=RFIActionRunner(c,contract,self.rfi_preflight)
        contract=LibraryContract(c,secret=self.secret);self.library_preflight=LibraryPreflight(c,contract,secret=self.secret);self.library=LibraryActionRunner(c,contract,self.library_preflight)
        self.library_input={'kind':'specification_template','title':'Synthetic shared-person specification','text':'Authored synthetic original text.','sourceLocator':'Synthetic editor / NS-01'}
    def rfi_request(self,key=None):
        review=self.rfi_preflight.review(self.person,'rfi.create',self.ar_project,self.rfi_input);self.assertTrue(review['allowed'],review)
        return {'person_id':self.person,'action':'rfi.create','resource_id':self.ar_project,'body':{**self.rfi_input,'fingerprint':review['fingerprint']},'repeatability_key':key or str(uuid4()),'if_match':review['resourceVersion']}
    def library_request(self,key=None):
        review=self.library_preflight.review(self.person,'library.create',self.ar_project,self.library_input);self.assertTrue(review['allowed'],review)
        return {'person_id':self.person,'action':'library.create','resource_id':self.ar_project,'body':{**self.library_input,'fingerprint':review['fingerprint']},'repeatability_key':key or str(uuid4()),'if_match':review['resourceVersion']}
    def test_actual_rfi_key_blocks_ap_and_original_rfi_replays(self):
        request=self.rfi_request();original=self.rfi.run(**request);self.assert_conflict_without_change(self.ap,self.ap_request(request['repeatability_key']))
        before=self.state();self.assertEqual(self.rfi.run(**request),{**original,'replayed':True,'effectApplied':False});self.assertEqual(self.state(),before)
    def test_actual_rfi_key_blocks_commercial(self):
        request=self.rfi_request();self.rfi.run(**request);self.assert_conflict_without_change(self.runner,self.commercial_request(request['repeatability_key']))
    def test_actual_rfi_key_blocks_ar(self):
        request=self.rfi_request();self.rfi.run(**request);self.assert_conflict_without_change(self.ar,self.ar_request(request['repeatability_key']))
    def test_actual_rfi_key_blocks_library(self):
        request=self.rfi_request();self.rfi.run(**request);self.assert_conflict_without_change(self.library,self.library_request(request['repeatability_key']))
    def test_actual_rfi_key_blocks_accounting_reservation_without_adapter_call(self):
        request=self.rfi_request();self.rfi.run(**request);worker=self.accounting_request(request['repeatability_key']);self.assert_conflict_without_change(self.accounting,worker)
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM ap_accounting_invocations'),0);self.assertEqual(self.worker._adapter.calls,{'submit':0,'lookup':0,'read_record':0})
    def test_actual_ap_key_blocks_rfi(self):
        request=self.ap_request();original=self.ap.run(**request);self.assert_conflict_without_change(self.rfi,self.rfi_request(request['repeatability_key']));self.assertEqual(self.ap.run(**request)['result'],original['result'])
    def test_actual_commercial_key_blocks_rfi(self):
        request=self.commercial_request();self.runner.run(**request);self.assert_conflict_without_change(self.rfi,self.rfi_request(request['repeatability_key']))
    def test_actual_ar_key_blocks_rfi(self):
        request=self.ar_request();self.ar.run(**request);self.assert_conflict_without_change(self.rfi,self.rfi_request(request['repeatability_key']))
    def test_actual_library_key_blocks_rfi(self):
        request=self.library_request();self.library.run(**request);self.assert_conflict_without_change(self.rfi,self.rfi_request(request['repeatability_key']))
    def test_real_pending_accounting_key_blocks_rfi_without_provider_attempt(self):
        request=self.accounting_request()
        with patch('apps.cipher.accounting_worker.invoke_bound_worker',side_effect=WorkerHeld('Synthetic pending RFI namespace')):pending=self.accounting.run(**request)
        self.assertEqual(pending['state'],'reserved');self.assert_conflict_without_change(self.rfi,self.rfi_request(request['repeatability_key']));self.assertEqual(self.worker._adapter.calls,{'submit':0,'lookup':0,'read_record':0})
    def test_current_rfi_scope_precedes_original_namespace_access(self):
        request=self.rfi_request();self.rfi.run(**request);self.c.plugin('people').end_membership('practice.accountant',self.ar_project,reason='Synthetic ended RFI assignment',actor='practice.bootstrap');before=self.state()
        with patch.object(APIActionReceipts,'require_repeatability_namespace',side_effect=AssertionError('Private metadata read')) as lookup:
            with self.assertRaises(APRefusal) as error:self.rfi.run(**request)
            self.assertIn(error.exception.status,(403,404));lookup.assert_not_called()
        self.assertEqual(self.state(),before)
    def test_metadata_only_lookup_proves_original_rfi_without_domain_worker_or_provider(self):
        request=self.rfi_request();self.rfi.run(**request);row=self.c.db.one('SELECT * FROM rfi_action_receipts WHERE repeatability_uuid=?',(request['repeatability_key'],));before=self.state()
        with patch.object(self.c,'plugin',side_effect=AssertionError('Domain initialized')),patch('apps.cipher.accounting_worker.invoke_bound_worker',side_effect=AssertionError('Provider used')):
            APIActionReceipts(self.c.db,self.c.audit).require_repeatability_namespace(self.person,request['repeatability_key'],row['fixed_action'],loads(row['binding_json']))
            with self.assertRaises(APIRepeatabilityConflict):APIActionReceipts(self.c.db,self.c.audit).require_repeatability_namespace(self.person,request['repeatability_key'],'bill.requestApproval',{})
        self.assertEqual(self.state(),before)
    def test_deleted_rfi_receipt_holds_fresh_ap_without_effect(self):
        original=self.rfi.run(**self.rfi_request());request=self.ap_request();self.remove_with_original_guards('rfi_action_receipts','id',original['receiptId']);before=self.state()
        with self.assertRaises(APRefusal) as error:self.ap.run(**request)
        self.assertIn(error.exception.status,(423,500));self.assertEqual(self.state(),before)
    def test_deleted_empty79_admission_holds_fresh_ap_without_effect(self):
        request=self.ap_request();self.c.db.execute("DELETE FROM schema_version WHERE name='rfi_practice_action_receipts'");before=self.state()
        with self.assertRaises(APRefusal) as error:self.ap.run(**request)
        self.assertIn(error.exception.status,(423,500));self.assertEqual(self.state(),before)
    def test_deleted_last_rfi_birth_holds_ap_even_with_intact_remaining_chain(self):
        original=self.rfi.run(**self.rfi_request());request=self.ap_request();last=self.c.db.one('SELECT * FROM audit_log ORDER BY seq DESC LIMIT 1')
        self.assertEqual(last['entity_id'],original['receiptId']);self.remove_with_original_guards('audit_log','seq',last['seq']);self.assertTrue(self.c.audit.verify_chain()['ok']);before=self.state()
        with self.assertRaises(APRefusal) as error:self.ap.run(**request)
        self.assertIn(error.exception.status,(423,500));self.assertEqual(self.state(),before)
    def test_current_ap_scope_precedes_private_rfi_namespace_but_rfi_scope_remains(self):
        request=self.rfi_request();original=self.rfi.run(**request);ap=self.ap_request(request['repeatability_key'])
        self.c.plugin('people').end_membership('practice.accountant',self.project,reason='Synthetic ended AP project assignment',actor='practice.bootstrap');before=self.state()
        with patch.object(APIActionReceipts,'require_repeatability_namespace',side_effect=AssertionError('Private RFI metadata read')) as lookup:
            with self.assertRaises(APRefusal) as error:self.ap.run(**ap)
            self.assertIn(error.exception.status,(403,404));lookup.assert_not_called()
        self.assertEqual(self.state(),before);self.assertEqual(self.rfi.run(**request)['result'],original['result'])
    def test_completed_accounting_original_key_blocks_rfi_without_second_submission(self):
        request=self.accounting_request();completed=self.accounting.run(**request);before_calls=dict(self.worker._adapter.calls);before_effects=self.worker._adapter._store.effect_count
        self.assert_conflict_without_change(self.rfi,self.rfi_request(request['repeatability_key']));self.assertEqual(self.accounting.run(**request)['result'],completed['result'])
        self.assertEqual(self.worker._adapter.calls,before_calls);self.assertEqual(self.worker._adapter._store.effect_count,before_effects)

    def test_nested_ap_key_claim_during_rfi_create_rolls_back_both_when_outer_catches(self):
        request=self.rfi_request();nested=self.ap_request(request['repeatability_key']);domain=self.c.plugin('rfi_controls');original=domain.create;observed=[]
        def create(*args,**kwargs):
            observed.append(self.ap.run(**nested));return original(*args,**kwargs)
        with self.c.db.transaction():
            before=self.state()
            with patch.object(domain,'create',side_effect=create):
                with self.assertRaises(APRefusal) as error:self.rfi.run(**request)
            self.assertEqual(error.exception.code,'repeatability_conflict');self.assertEqual(len(observed),1);self.assertEqual(self.state(),before)
    def test_nested_rfi_key_claim_during_ap_request_rolls_back_both_when_outer_catches(self):
        request=self.ap_request();nested=self.rfi_request(request['repeatability_key']);original=self.c.request_approval;observed=[]
        def approval(operation,*args,**kwargs):
            if operation=='bill.approve':observed.append(self.rfi.run(**nested))
            return original(operation,*args,**kwargs)
        with self.c.db.transaction():
            before=self.state()
            with patch.object(self.c,'request_approval',side_effect=approval):
                with self.assertRaises(APRefusal) as error:self.ap.run(**request)
            self.assertEqual(error.exception.code,'repeatability_conflict');self.assertEqual(len(observed),1);self.assertEqual(self.state(),before)

if __name__=='__main__':unittest.main()
