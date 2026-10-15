"""Real commercial receipts require their own bounded named schema admission."""
import contextlib
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.tests import test_commercial_actions as harness
from apps.cipher.ap_contract import APRefusal
from apps.cipher.commercial_practice_fixture import ESTIMATOR_LOGIN,BOOTSTRAP_LOGIN
from apps.cipher.commercial_receipts import CommercialReceiptError, CommercialReceipts, commercial_receipt_inventory_proof
from apps.cipher.core.api_receipts import APIActionReceipts,APIReceiptIntegrityError
from apps.cipher.core.ids import loads,canonical_json
from apps.cipher.domain.commercial import CommercialError


class CommercialReceiptAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.h=harness.CommercialActionTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.c=self.h.c;self.contract=self.h.contract
        self.created,self.request=self.h.act(self.h.person,'estimate.create',self.h.r['project_id'],self.h.input())
        self.estimate=self.created['result']['estimateId']
        self.h.accepted(self.estimate)
        self.original=self.h.domain.source(self.estimate,accepted=True)
        self.admission=self.c.db.one("SELECT * FROM schema_version WHERE name='commercial_practice_action_receipts'")
        self.old_version=self.contract.version(self.h.person,self.estimate,'estimate')

    @contextlib.contextmanager
    def changed(self,kind):
        row=self.admission
        try:
            if kind=='missing':self.c.db.execute("DELETE FROM schema_version WHERE name=?",(row['name'],))
            elif kind=='checksum':self.c.db.execute("UPDATE schema_version SET checksum=? WHERE name=?",('0'*64,row['name']))
            elif kind=='count':self.c.db.execute("UPDATE schema_version SET statement_count=? WHERE name=?",(row['statement_count']+1,row['name']))
            else:
                version={'max':9223372036854775807,'min':-9223372036854775808,'version':173}[kind]
                self.c.db.execute("UPDATE schema_version SET version=? WHERE name=?",(version,row['name']))
            yield
        finally:
            if kind=='missing':
                self.c.db.execute('INSERT INTO schema_version ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
            else:
                self.c.db.execute('UPDATE schema_version SET version=?,statement_count=?,checksum=? WHERE name=?',(row['version'],row['statement_count'],row['checksum'],row['name']))

    def native_original(self, kind):
        if kind == 'min':
            # A negative later row intrudes into the native72 prefix itself.
            with self.assertRaises(CommercialError):self.h.domain.source(self.estimate,accepted=True)
        else:self.assertEqual(self.original,self.h.domain.source(self.estimate,accepted=True))

    def test_metadata_refuses_missing_or_corrupt_named_admission_without_unbounded_allocation(self):
        for kind in ('checksum','count','max','min','version','missing'):
            with self.subTest(kind=kind),self.changed(kind):
                before=self.h.state()
                with patch('apps.cipher.commercial_receipts.range',side_effect=AssertionError('raw metadata allocation'),create=True):
                    with self.assertRaises(CommercialReceiptError):CommercialReceipts(self.c.db,self.c.audit).verify_integrity()
                    with self.assertRaises(CommercialReceiptError):commercial_receipt_inventory_proof(self.c.db,self.c.audit)
                self.assertEqual(before,self.h.state())
                self.native_original(kind)

    def test_completed_original_action_refuses_api_admission_loss_without_changing_native72_source(self):
        for kind in ('checksum','count','max','min','version','missing'):
            with self.subTest(kind=kind),self.changed(kind):
                before=self.h.state()
                with self.assertRaises(APRefusal):self.h.runner.run(*self.request[0],**self.request[1])
                self.assertEqual(before,self.h.state());self.native_original(kind)
        self.h.replay(self.created,self.request)

    def test_public_reads_and_primed_version_require_receipt_admission_after_scope(self):
        views=(lambda:self.contract.estimate(self.h.person,self.estimate),
               lambda:self.contract.comparison(self.h.person,self.estimate),
               lambda:self.contract.preparation(self.h.person,self.h.r['project_id']),
               lambda:self.contract.handoff_preparation(self.h.person,self.estimate),
               lambda:self.contract.read(self.h.person,'projects'),
               lambda:self.contract.version(self.h.person,self.estimate,'estimate'))
        for kind in ('checksum','count','max','min','version','missing'):
            with self.subTest(kind=kind),self.changed(kind):
                before=self.h.state()
                for index,view in enumerate(views):
                    with self.subTest(view=index):
                        with self.assertRaises(APRefusal) as refused:view()
                        self.assertEqual(refused.exception.status,423)
                self.assertEqual(before,self.h.state());self.native_original(kind)

    def test_other_ap_namespace_fails_closed_on_corrupt_commercial_admission(self):
        ap=APIActionReceipts(self.c.db,self.c.audit)
        binding=loads(self.c.db.one('SELECT binding_json FROM commercial_action_receipts WHERE id=?',(self.created['receiptId'],))['binding_json'])
        for kind in ('checksum','count','max','min','version','missing'):
            with self.subTest(kind=kind),self.changed(kind):
                before=self.h.state()
                with self.assertRaises(APIReceiptIntegrityError):ap.require_repeatability_namespace(self.h.person,str(uuid4()),'estimate.create',binding)
                self.assertEqual(before,self.h.state())

    def test_hidden_source_denial_precedes_global_metadata_gate(self):
        with patch.object(self.contract,'_metadata',side_effect=AssertionError('metadata before scope'),create=True) as metadata:
            with self.assertRaises(APRefusal) as error:self.contract.preparation(self.h.person,self.h.r['hidden_project_id'])
            self.assertEqual(error.exception.status,404);metadata.assert_not_called()
            with self.assertRaises(APRefusal) as error:self.contract.version(self.h.person,'not-a-commercial-estimate','estimate')
            self.assertEqual(error.exception.status,404);metadata.assert_not_called()

    def test_last_membership_denial_precedes_global_metadata_or_private_materials(self):
        self.c.plugin('people').end_membership(ESTIMATOR_LOGIN,self.h.r['project_id'],reason='Actual project membership ended',actor=BOOTSTRAP_LOGIN)
        with patch.object(self.contract,'_metadata',side_effect=AssertionError('metadata before current duty'),create=True) as metadata:
            with self.assertRaises(APRefusal) as error:self.contract.read(self.h.person,'projects')
            self.assertEqual(error.exception.status,403);metadata.assert_not_called()

    def test_named_original_prefix_does_not_depend_on_later_actual_admissions(self):
        before=tuple(commercial_receipt_inventory_proof(self.c.db,self.c.audit))
        self.c.db.execute("DELETE FROM schema_version WHERE name='owner_billing_sources_and_posting'")
        self.assertEqual(before,tuple(commercial_receipt_inventory_proof(self.c.db,self.c.audit)))
        self.native_original('later')

    def test_original_native72_proof_survives_later_receipt_admission_loss(self):
        with self.changed('missing'):
            before=self.h.state()
            self.native_original('missing')
            self.assertEqual(before,self.h.state())
