"""One genuine person's reviewed UUID spans AR, AP, commercial and worker work."""
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.tests import test_commercial_namespace as commercial_tests
from apps.cipher.ap_contract import APRefusal
from apps.cipher.accounting_worker import WorkerHeld
from apps.cipher.core.api_receipts import APIActionReceipts,APIRepeatabilityConflict
from apps.cipher.core.ids import loads
from apps.cipher.domain import owner_billing
from apps.cipher.ar_actions import ARActionRunner
from apps.cipher.ar_contract import ARContract
from apps.cipher.ar_preflight import ARPreflight
from apps.cipher.ar_receipts import ar_receipt_inventory_proof


class ARNamespaceTests(unittest.TestCase):
    secret=b'actual-same-person-AR-AP-commercial-shared-private-key'
    state=commercial_tests.CommercialNamespaceTests.state
    ap_request=commercial_tests.CommercialNamespaceTests.ap_request
    commercial_request=commercial_tests.CommercialNamespaceTests.commercial_request
    accounting_request=commercial_tests.CommercialNamespaceTests.accounting_request
    assert_conflict_without_change=commercial_tests.CommercialNamespaceTests.assert_conflict_without_change
    remove_with_original_guards=commercial_tests.CommercialNamespaceTests.remove_with_original_guards

    def setUp(self):
        # Reuse genuine owned AP/accountant and independently administered estimator
        # grants. This calls native people request/grant/apply under the existing
        # enforcing policy; it does not reset policy or manufacture receipt rows.
        commercial_tests.CommercialNamespaceTests.setUp(self)
        c=self.c
        customer=c.add_party(kind='customer',name='Synthetic shared-person owner agency',actor='practice.bootstrap')
        project=c.create_project(name='Synthetic shared-person owner-billing project',entity='Synthetic shared entity',
            budget='200000',customer_id=customer['id'],actor='practice.bootstrap')
        self.ar_project=project['id']
        people=c.plugin('people')
        people.add_membership('practice.accountant',project['id'],actor='practice.bootstrap')
        draft=people.request_grant('practice.accountant','pm',project_id=project['id'],
            reason='Synthetic same-person own AR project PM assignment',actor='practice.bootstrap')
        approval=c.request_approval('people.grant_role',draft['id'],actor_role='owner',requested_by='practice.reviewer')
        c.approve(approval['id'],approver='practice.bootstrap',approver_role='owner')
        c.execute(approval['id'],actor='practice.bootstrap')
        c.receivables.set_prime_contract(project['id'],'250000','0.10',actor='practice.accountant')
        c.receivables.set_customer_terms(customer['id'],30,actor='practice.accountant')
        c.receivables.set_billing_recipients(customer['id'],['owner-billing@synthetic-owner.invalid'],actor='practice.accountant')
        c.plugin('close').set_contract_value(project['id'],'250000',actor='practice.accountant',
            note='Explicit synthetic owner basis; no external award or signature')
        revisions={}
        for kind,text in (('owner_agreement','Synthetic owner agreement and fixed SOV; no external signature'),
                          ('owner_claim','Synthetic claimed count U1 12EA and L2 $15,000'),
                          ('owner_certification','Synthetic PM-reviewed count U1 10EA and L2 $12,500')):
            document=c.evidence.register_document(project_id=project['id'],kind=kind,title='Synthetic namespace '+kind,actor='practice.accountant')
            revisions[kind]=c.evidence.add_revision(document_id=document['id'],content=text,
                note='Owned synthetic original source',actor='practice.accountant')['id']
        self.basis=c.plugin('owner_billing').declare_practice_basis(project['id'],
            contract_revision_id=revisions['owner_agreement'],actor='practice.accountant')['id']
        self.ar_input={'claimRevisionId':revisions['owner_claim'],'reviewRevisionId':revisions['owner_certification'],
            'periodId':'2026-10','lines':[
                {'lineId':'U1','claimedCumulative':'12','reviewedCumulative':'10','differenceReason':'Synthetic two piles unverified',
                 'claimSourceLocator':'Owner claim U1','reviewSourceLocator':'PM review U1'},
                {'lineId':'L2','claimedCumulative':'15000','reviewedCumulative':'12500','differenceReason':'Synthetic testing incomplete',
                 'claimSourceLocator':'Owner claim L2','reviewSourceLocator':'PM review L2'}]}
        self.ar_contract=ARContract(c,secret=self.secret)
        self.ar_preflight=ARPreflight(c,self.ar_contract,secret=self.secret)
        self.ar=ARActionRunner(c,self.ar_contract,self.ar_preflight)
        actual=people.person_for('practice.accountant')['id']
        self.assertEqual(actual,self.person)
        roles=[g['role'] for g in people._live_grants(self.person,people._today())]
        self.assertIn('pm',roles)
        self.assertIn('accountant',roles)
        self.assertIn('estimator',roles)

    def ar_request(self,key=None):
        review=self.ar_preflight.review(self.person,'ownerBill.prepare',self.basis,self.ar_input)
        self.assertTrue(review['allowed'],review)
        return {'person_id':self.person,'action':'ownerBill.prepare','resource_id':self.basis,
                'body':{**self.ar_input,'fingerprint':review['fingerprint']},'repeatability_key':key or str(uuid4()),
                'if_match':review['resourceVersion']}

    def test_actual_ar_receipt_blocks_ap_key_and_preserves_exact_ar_replay(self):
        request=self.ar_request()
        original=self.ar.run(**request)
        self.assert_conflict_without_change(self.ap,self.ap_request(request['repeatability_key']))
        before=self.state()
        self.assertEqual(self.ar.run(**request),{**original,'replayed':True,'effectApplied':False})
        self.assertEqual(self.state(),before)

    def test_actual_ap_receipt_blocks_ar_key_and_preserves_exact_ap_replay(self):
        request=self.ap_request()
        original=self.ap.run(**request)
        self.assert_conflict_without_change(self.ar,self.ar_request(request['repeatability_key']))
        before=self.state()
        self.assertEqual(self.ap.run(**request),{**original,'replayed':True,'effectApplied':False})
        self.assertEqual(self.state(),before)

    def test_actual_ar_receipt_blocks_commercial_and_preserves_original_ar(self):
        request=self.ar_request()
        original=self.ar.run(**request)
        self.assert_conflict_without_change(self.runner,self.commercial_request(request['repeatability_key']))
        self.assertEqual(self.ar.run(**request)['result'],original['result'])

    def test_actual_commercial_receipt_blocks_ar_and_preserves_original_commercial(self):
        request=self.commercial_request()
        original=self.runner.run(**request)
        self.assert_conflict_without_change(self.ar,self.ar_request(request['repeatability_key']))
        self.assertEqual(self.runner.run(**request)['result'],original['result'])

    def test_actual_ar_key_cannot_reserve_or_submit_accounting_worker(self):
        request=self.ar_request()
        original=self.ar.run(**request)
        worker_request=self.accounting_request(request['repeatability_key'])
        self.assert_conflict_without_change(self.accounting,worker_request)
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM ap_accounting_invocations'),0)
        self.assertEqual(self.worker._adapter.calls,{'submit':0,'lookup':0,'read_record':0})
        self.assertEqual(self.worker._adapter._store.effect_count,0)
        self.assertEqual(self.ar.run(**request)['result'],original['result'])

    def test_actual_pending_worker_reservation_blocks_ar_without_provider_attempt(self):
        request=self.accounting_request()
        with patch('apps.cipher.accounting_worker.invoke_bound_worker',side_effect=WorkerHeld('Synthetic pending namespace worker')):
            pending=self.accounting.run(**request)
        self.assertEqual(pending['state'],'reserved')
        self.assert_conflict_without_change(self.ar,self.ar_request(request['repeatability_key']))
        before=self.state()
        with patch('apps.cipher.accounting_worker.invoke_bound_worker',side_effect=WorkerHeld('Synthetic pending namespace worker')):
            self.assertEqual(self.accounting.run(**request),pending)
        self.assertEqual(self.state(),before)
        self.assertEqual(self.worker._adapter.calls,{'submit':0,'lookup':0,'read_record':0})

    def test_actual_completed_accounting_key_blocks_ar_without_second_submit(self):
        request=self.accounting_request()
        completed=self.accounting.run(**request)
        self.assert_conflict_without_change(self.ar,self.ar_request(request['repeatability_key']))
        before=self.state(),dict(self.worker._adapter.calls),self.worker._adapter._store.effect_count
        replay=self.accounting.run(**request)
        self.assertEqual(replay['result'],completed['result'])
        self.assertEqual((self.state(),dict(self.worker._adapter.calls),self.worker._adapter._store.effect_count),before)

    def test_current_project_duty_precedes_ar_namespace_disclosure(self):
        request=self.ar_request()
        self.ar.run(**request)
        ap_request=self.ap_request(request['repeatability_key'])
        commercial_request=self.commercial_request(request['repeatability_key'])
        people=self.c.plugin('people')
        people.end_membership('practice.accountant',self.ar_project,reason='Synthetic AR duty ended',actor='practice.bootstrap')
        before=self.state()
        with patch.object(APIActionReceipts,'require_repeatability_namespace',side_effect=AssertionError('Private namespace disclosed')) as lookup:
            with self.assertRaises(APRefusal) as refusal:self.ar.run(**request)
            self.assertIn(refusal.exception.status,(403,404))
            lookup.assert_not_called()
        self.assertEqual(self.state(),before)
        # Losing AR duty does not borrow or erase the person's separate AP duty.
        self.assert_conflict_without_change(self.ap,ap_request)
        self.assert_conflict_without_change(self.runner,commercial_request)

    def test_metadata_namespace_proof_initializes_no_ar_domain_or_worker_or_provider(self):
        request=self.ar_request()
        self.ar.run(**request)
        receipt=self.c.db.one('SELECT * FROM ar_action_receipts WHERE repeatability_uuid=?',(request['repeatability_key'],))
        before=self.state(),self.c.db.conn.total_changes
        metadata=APIActionReceipts(self.c.db,self.c.audit)
        with patch.object(self.c,'plugin',side_effect=AssertionError('Domain fetched')), \
             patch.object(owner_billing.Plugin,'__init__',side_effect=AssertionError('AR domain initialized')), \
             patch('apps.cipher.accounting_worker.create_practice_accounting_worker',side_effect=AssertionError('Worker initialized')), \
             patch('apps.cipher.accounting_simulator.SimulatedAccountingAdapter',side_effect=AssertionError('Provider initialized')):
            self.assertIsNone(metadata.require_repeatability_namespace(self.person,request['repeatability_key'],'ownerBill.prepare',loads(receipt['binding_json'])))
            self.assertIsNone(metadata.require_repeatability_namespace(self.person,str(uuid4()),'bill.requestApproval',{}))
            with self.assertRaises(APIRepeatabilityConflict):
                metadata.require_repeatability_namespace(self.person,request['repeatability_key'],'bill.requestApproval',{})
            self.assertEqual(len(ar_receipt_inventory_proof(self.c.db,self.c.audit)),1)
        self.assertEqual((self.state(),self.c.db.conn.total_changes),before)

    def test_deleted_original_ar_receipt_holds_fresh_ap_and_commercial_without_effect(self):
        original=self.ar.run(**self.ar_request())
        ap_request=self.ap_request()
        commercial_request=self.commercial_request()
        self.remove_with_original_guards('ar_action_receipts','id',original['receiptId'])
        before=self.state()
        for runner,args in ((self.ap,ap_request),(self.runner,commercial_request)):
            with self.subTest(action=args['action']),self.assertRaises(APRefusal) as refusal:runner.run(**args)
            self.assertEqual(refusal.exception.status,500)
        self.assertEqual(self.state(),before)

    def test_deleted_last_original_ar_birth_holds_ap_with_intact_truncated_audit(self):
        original=self.ar.run(**self.ar_request())
        request=self.ap_request()
        last=self.c.db.one('SELECT * FROM audit_log ORDER BY seq DESC LIMIT 1')
        self.assertEqual(last['entity_id'],original['receiptId'])
        self.remove_with_original_guards('audit_log','seq',last['seq'])
        self.assertTrue(self.c.audit.verify_chain()['ok'])
        before=self.state()
        with self.assertRaises(APRefusal) as refusal:self.ap.run(**request)
        self.assertEqual(refusal.exception.status,500)
        self.assertEqual(self.state(),before)

    def test_deleted_empty_ar_admission_holds_fresh_ap_and_commercial(self):
        ap_request=self.ap_request()
        commercial_request=self.commercial_request()
        self.c.db.execute("DELETE FROM schema_version WHERE name='ar_practice_action_receipts'")
        before=self.state()
        for runner,args in ((self.ap,ap_request),(self.runner,commercial_request)):
            with self.subTest(action=args['action']),self.assertRaises(APRefusal) as refusal:runner.run(**args)
            self.assertEqual(refusal.exception.status,500)
        self.assertEqual(self.state(),before)


    def test_nested_ap_key_claim_during_ar_prepare_rolls_back_both_domain_effects(self):
        request=self.ar_request()
        nested=self.ap_request(request['repeatability_key'])
        original=self.c.plugin('owner_billing').prepare
        observed=[]
        def prepare(*args,**kwargs):
            observed.append(self.ap.run(**nested))
            return original(*args,**kwargs)
        with self.c.db.transaction():
            before=self.state()
            with patch.object(self.c.plugin('owner_billing'),'prepare',side_effect=prepare):
                with self.assertRaises(APRefusal) as refusal:self.ar.run(**request)
            self.assertEqual(refusal.exception.status,409)
            self.assertEqual(refusal.exception.code,'repeatability_conflict')
            self.assertEqual(len(observed),1)
            self.assertTrue(observed[0]['effectApplied'])
            self.assertEqual(self.state(),before)
        original=self.ar.run(**request)
        self.assertTrue(original['effectApplied'])
        self.assert_conflict_without_change(self.ap,nested)

    def test_nested_ar_key_claim_during_ap_request_rolls_back_both_domain_effects(self):
        request=self.ap_request()
        nested=self.ar_request(request['repeatability_key'])
        original=self.c.request_approval
        observed=[]
        def request_approval(operation,*args,**kwargs):
            if operation=='bill.approve':observed.append(self.ar.run(**nested))
            return original(operation,*args,**kwargs)
        with self.c.db.transaction():
            before=self.state()
            with patch.object(self.c,'request_approval',side_effect=request_approval):
                with self.assertRaises(APRefusal) as refusal:self.ap.run(**request)
            self.assertEqual(refusal.exception.status,409)
            self.assertEqual(refusal.exception.code,'repeatability_conflict')
            self.assertEqual(len(observed),1)
            self.assertTrue(observed[0]['effectApplied'])
            self.assertEqual(self.state(),before)
        original=self.ap.run(**request)
        self.assertTrue(original['effectApplied'])
        self.assert_conflict_without_change(self.ar,nested)

    def test_current_ap_and_commercial_duties_precede_cross_ar_key_lookup(self):
        request=self.ar_request()
        original=self.ar.run(**request)
        ap_request=self.ap_request(request['repeatability_key'])
        commercial_request=self.commercial_request(request['repeatability_key'])
        self.c.plugin('people').end_membership('practice.accountant',self.project,
            reason='Synthetic AP and commercial project duty ended',actor='practice.bootstrap')
        before=self.state()
        with patch.object(APIActionReceipts,'require_repeatability_namespace',side_effect=AssertionError('Private AR key disclosed')) as lookup:
            for runner,args in ((self.ap,ap_request),(self.runner,commercial_request)):
                with self.subTest(action=args['action']),self.assertRaises(APRefusal) as refusal:runner.run(**args)
                self.assertIn(refusal.exception.status,(403,404))
            lookup.assert_not_called()
        self.assertEqual(self.state(),before)
        self.assertEqual(self.ar.run(**request)['result'],original['result'])

    def test_deleted_original_ap_receipt_holds_fresh_ar_without_effect(self):
        original=self.ap.run(**self.ap_request())
        request=self.ar_request()
        self.remove_with_original_guards('ap_action_receipts','id',original['receiptId'])
        before=self.state()
        with self.assertRaises(APRefusal) as refusal:self.ar.run(**request)
        self.assertEqual(refusal.exception.status,500)
        self.assertEqual(self.state(),before)

    def test_deleted_last_original_ap_birth_holds_ar_with_intact_truncated_chain(self):
        original=self.ap.run(**self.ap_request())
        request=self.ar_request()
        last=self.c.db.one('SELECT * FROM audit_log ORDER BY seq DESC LIMIT 1')
        self.assertEqual(last['entity_id'],original['receiptId'])
        self.remove_with_original_guards('audit_log','seq',last['seq'])
        self.assertTrue(self.c.audit.verify_chain()['ok'])
        before=self.state()
        with self.assertRaises(APRefusal) as refusal:self.ar.run(**request)
        self.assertEqual(refusal.exception.status,500)
        self.assertEqual(self.state(),before)

    def test_deleted_prior_ap_admission_holds_ar_without_reclassifying_original_source(self):
        request=self.ar_request()
        self.c.db.execute("DELETE FROM schema_version WHERE name='ap_practice_preparation_action_receipts'")
        before=self.state()
        with self.assertRaises(APRefusal) as refusal:self.ar.run(**request)
        self.assertIn(refusal.exception.status,(423,500))
        self.assertEqual(self.state(),before)

if __name__=='__main__':unittest.main()
