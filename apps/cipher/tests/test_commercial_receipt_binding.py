"""A receipt callback cannot change the actual authorized invocation or stored row."""
import copy
import datetime
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.tests import test_commercial_actions as actions_tests
from apps.cipher.ap_contract import APRefusal
from apps.cipher.core.ids import canonical_json,parse_iso,utcnow


class CommercialReceiptBindingTests(unittest.TestCase):
    setUp=actions_tests.CommercialActionTests.setUp
    state=actions_tests.CommercialActionTests.state
    input=actions_tests.CommercialActionTests.input
    prepared=actions_tests.CommercialActionTests.prepared
    act=actions_tests.CommercialActionTests.act

    def assert_callback_refused_and_rolled_back(self,callback,request=None):
        args,kwargs=request or self.prepared(self.person,'estimate.create',self.r['project_id'],self.input())
        with self.c.db.transaction():
            before=self.state()
            with patch.object(self.runner.receipts,'record',side_effect=callback):
                with self.assertRaises(APRefusal) as refusal:self.runner.run(*args,**kwargs)
            self.assertEqual(refusal.exception.status,500)
            self.assertEqual(self.state(),before)

    def change_argument(self,key,value):
        original=self.runner.receipts.record
        def changed(**kw):
            kw[key]=value(kw) if callable(value) else value
            return original(**kw)
        return changed

    def test_callback_cannot_change_canonical_person_only(self):
        self.assert_callback_refused_and_rolled_back(self.change_argument('person_id',self.reviewer))

    def test_callback_cannot_change_repeatability_uuid_only(self):
        self.assert_callback_refused_and_rolled_back(self.change_argument('repeatability_uuid',str(uuid4())))

    def test_callback_cannot_change_original_if_match(self):
        self.assert_callback_refused_and_rolled_back(self.change_argument('binding',lambda kw:{**kw['binding'],'originalIfMatch':'unreviewed-version'}))

    def test_callback_cannot_change_review_fingerprint(self):
        def changed(kw):
            binding=copy.deepcopy(kw['binding'])
            binding['preflightFingerprint']='unreviewed-fingerprint'
            binding['canonicalTypedBody']['fingerprint']='unreviewed-fingerprint'
            return binding
        self.assert_callback_refused_and_rolled_back(self.change_argument('binding',changed))

    def test_callback_cannot_change_exact_result(self):
        self.assert_callback_refused_and_rolled_back(self.change_argument('result',lambda kw:{**kw['result'],'status':'executed_contract'}))

    def test_callback_cannot_change_exact_source(self):
        self.assert_callback_refused_and_rolled_back(self.change_argument('source',lambda kw:{**kw['source'],'reviewedPlanHash':'0'*64}))

    def test_callback_cannot_change_http_status_only(self):
        self.assert_callback_refused_and_rolled_back(self.change_argument('http_status',201))

    def test_callback_cannot_change_outcome_only(self):
        self.assert_callback_refused_and_rolled_back(self.change_argument('outcome','refused'))

    def test_callback_cannot_change_actor_login_or_action_or_resource(self):
        for key,value in (('actor_login','practice.reviewer'),('action','estimate.revise'),('resource_id','different-resource')):
            with self.subTest(key=key):self.assert_callback_refused_and_rolled_back(self.change_argument(key,value))

    def test_callback_cannot_mutate_binding_in_place(self):
        original=self.runner.receipts.record
        def changed(**kw):
            kw['binding']['originalIfMatch']='mutated-in-place'
            return original(**kw)
        self.assert_callback_refused_and_rolled_back(changed)

    def test_returned_row_must_equal_actual_stored_row(self):
        original=self.runner.receipts.record
        def changed(**kw):
            row=original(**kw)
            row['canonical_person_id']=self.reviewer
            return row
        self.assert_callback_refused_and_rolled_back(changed)

    def test_stored_row_cannot_change_even_when_returned_row_claims_original_person(self):
        original=self.runner.receipts.record
        def changed(**kw):
            intended=kw['person_id']
            kw['person_id']=self.reviewer
            row=original(**kw)
            row['canonical_person_id']=intended
            return row
        self.assert_callback_refused_and_rolled_back(changed)

    def test_post_insert_changed_receipt_is_reproved_after_callback(self):
        original=self.runner.receipts.record
        def changed(**kw):
            row=original(**kw)
            guard=self.c.db.one("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name='commercial_action_receipts_no_update'")
            self.c.db.execute('DROP TRIGGER '+guard['name'])
            self.c.db.execute('UPDATE commercial_action_receipts SET created_at=? WHERE id=?',('1900-01-01T00:00:00Z',row['id']))
            self.c.db.execute(guard['sql'])
            return self.c.db.one('SELECT * FROM commercial_action_receipts WHERE id=?',(row['id'],))
        self.assert_callback_refused_and_rolled_back(changed)

    def test_post_insert_receipt_cannot_be_reassigned_to_another_workspace(self):
        original=self.runner.receipts.record
        def changed(**kw):
            row=original(**kw)
            guard=self.c.db.one("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name='commercial_action_receipts_no_update'")
            self.c.db.execute('DROP TRIGGER '+guard['name'])
            self.c.db.execute('UPDATE commercial_action_receipts SET workspace_id=? WHERE id=?',('different-workspace',row['id']))
            self.c.db.execute(guard['sql'])
            return self.c.db.one('SELECT * FROM commercial_action_receipts WHERE id=?',(row['id'],))
        self.assert_callback_refused_and_rolled_back(changed)

    def test_terminal_refusal_receipt_cannot_change_original_person_and_rolls_back_expiry(self):
        from apps.cipher.domain import estimates as engine
        builder=engine.build_manifest
        def short_lived(**kwargs):
            manifest=builder(**kwargs)
            manifest['expires_at']=(utcnow()+datetime.timedelta(seconds=1.2)).isoformat()
            return manifest
        with patch.object(engine,'build_manifest',side_effect=short_lived):
            requested,_=self.act(self.person,'estimate.request',self.r['current_estimate_id'])
        approval=requested['result']['approvalId']
        request=self.prepared(self.reviewer,'estimate.accept',approval)
        original_record=self.runner.receipts.record
        grant=self.c.approvals.grant
        observed=[]
        def after_deadline(*args,**kwargs):
            deadline=parse_iso(self.c.approvals.get(approval)['expires_at'])
            time.sleep(max(0,(deadline-utcnow()).total_seconds())+0.02)
            return grant(*args,**kwargs)
        def record(**kw):
            observed.append((kw['outcome'],kw['http_status']))
            kw['person_id']=self.person
            return original_record(**kw)
        with patch.object(self.c.approvals,'grant',side_effect=after_deadline):
            self.assert_callback_refused_and_rolled_back(record,request)
        self.assertEqual(observed,[('refused',423)])
        self.assertEqual(self.c.approvals.get(approval)['status'],'pending')


if __name__=='__main__':unittest.main()
