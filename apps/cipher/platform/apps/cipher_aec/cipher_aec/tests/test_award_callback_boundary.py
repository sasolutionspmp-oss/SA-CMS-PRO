"""Exact native callback tails survive receipt construction, never savepoint failure."""
from contextlib import contextmanager
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from frappe.utils import CallbackManager
from cipher_aec.api.errors import DomainError
from cipher_aec.awards import runtime
from cipher_aec.documents import provenance


class AwardCallbackBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.db=SimpleNamespace(**{name:CallbackManager() for name in runtime.MANAGERS})
        self.sql=sqlite3.connect(':memory:');self.addCleanup(self.sql.close)
        self.sql.execute('CREATE TABLE records (kind TEXT PRIMARY KEY)');self.sql.commit()
        self.full_rollbacks=0
        def rollback():
            self.full_rollbacks+=1;self.sql.rollback()
            self.db.before_commit.reset();self.db.after_commit.reset()
            self.db.before_rollback.run();self.db.after_rollback.run()
        self.db.rollback=rollback
        self.local=SimpleNamespace(_webhook_queue=[],_realtime_log=[])
        self.fake=SimpleNamespace(db=self.db,local=self.local)
        p=patch.object(runtime,'frappe',self.fake);p.start();self.addCleanup(p.stop)
        self.seen=[]
        self.sentinels={name:(lambda n=name:self.seen.append(n)) for name in runtime.MANAGERS}
        for name,callback in self.sentinels.items():getattr(self.db,name).add(callback)

    def begin(self):runtime.begin_callback_stage(company='Company A',operation_id='operation',packet_id='packet',award_revision_id='revision',plan_digest='digest')

    def invalidators(self):
        state={'valid':True,'authorized':set()}
        with patch.object(provenance,'_current_db',return_value=self.db):provenance._watch_transaction(state)
        provenance._invalidate(state)

    def test_success_lifetime_includes_receipt_and_preserves_prior_callbacks(self):
        with runtime.command_boundary(company='Company A',operation_id='operation'):
            self.begin();self.sql.execute("INSERT INTO records VALUES ('Project')");self.invalidators()
            self.sql.execute("INSERT INTO records VALUES ('Receipt')")
        self.assertEqual(self.full_rollbacks,0)
        for name in runtime.MANAGERS:self.assertIs(runtime._contents(getattr(self.db,name))[0],self.sentinels[name])
        self.db.after_commit.run();self.assertEqual(self.seen,['after_commit'])
        self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM records').fetchone()[0],2)

    def test_actual_late_sql_receipt_failure_cuts_only_new_stage_tails(self):
        self.sql.execute("INSERT INTO records VALUES ('prior')");self.sql.execute('SAVEPOINT command')
        prior_webhook={'prior':'webhook'};self.local._webhook_queue.append(prior_webhook)
        try:
            with runtime.command_boundary(company='Company A',operation_id='operation'):
                self.begin();self.sql.execute("INSERT INTO records VALUES ('Project')");self.sql.execute("INSERT INTO records VALUES ('Profile')");self.invalidators()
                self.local._webhook_queue.append({'new':'unqualified'});self.db.after_commit.add(lambda:self.seen.append('unsafe'))
                self.sql.execute("INSERT INTO records VALUES ('prior')")
        except sqlite3.IntegrityError:self.sql.execute('ROLLBACK TO SAVEPOINT command')
        else:self.fail('Receipt failure must propagate')
        self.assertEqual(self.sql.execute('SELECT kind FROM records').fetchall(),[('prior',)])
        self.assertEqual(self.local._webhook_queue,[prior_webhook]);self.assertEqual(self.full_rollbacks,0)
        for name in runtime.MANAGERS:self.assertEqual(runtime._contents(getattr(self.db,name)),(self.sentinels[name],))
        self.db.after_commit.run();self.assertEqual(self.seen,['after_commit'])

    def test_unknown_callback_fails_success_and_never_runs(self):
        with self.assertRaises(DomainError) as error:
            with runtime.command_boundary(company='Company A',operation_id='operation'):
                self.begin();self.db.after_commit.add(lambda:self.seen.append('unsafe'))
        self.assertEqual(error.exception.code,'award_callback_unqualified')
        self.db.after_commit.run();self.assertEqual(self.seen,['after_commit'])

    def test_actual_realtime_queue_name_detects_unqualified_business_intent(self):
        queue=self.local._realtime_log
        with self.assertRaises(DomainError):
            with runtime.command_boundary(company='Company A',operation_id='operation'):
                self.begin();queue.append({'event':'native-realtime'})
        self.assertIs(queue,self.local._realtime_log);self.assertEqual(queue,[])

    def test_same_length_manager_reset_performs_actual_full_sql_rollback(self):
        self.sql.execute("INSERT INTO records VALUES ('prior')")
        with self.assertRaises(runtime.AwardCallbackBoundaryError):
            with runtime.command_boundary(company='Company A',operation_id='operation'):
                self.begin();self.sql.execute("INSERT INTO records VALUES ('Project')")
                self.db.after_commit.reset();self.db.after_commit.add(lambda:None)
        self.assertEqual(self.full_rollbacks,1);self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)

    def test_manager_replacement_never_uses_vanished_savepoint_recovery(self):
        with self.assertRaises(runtime.AwardCallbackBoundaryError):
            with runtime.command_boundary(company='Company A',operation_id='operation'):
                self.begin();self.db.before_commit=CallbackManager()
        self.assertEqual(self.full_rollbacks,1)

    def test_non_award_noop_does_not_change_other_action_callbacks(self):
        callback=lambda:self.seen.append('ordinary-action')
        with runtime.command_boundary(company='Company A',operation_id='operation'):self.db.after_commit.add(callback)
        self.assertEqual(runtime._contents(self.db.after_commit),(self.sentinels['after_commit'],callback));self.assertEqual(self.full_rollbacks,0)

    def test_no_receipt_safe_owner_or_wrong_operation_cannot_start_stage(self):
        with self.assertRaises(DomainError):self.begin()
        with runtime.command_boundary(company='Company B',operation_id='operation'):
            with self.assertRaises(DomainError):self.begin()

    def test_exact_write_flags_suppress_pinned_native_notify_branch_including_late_records(self):
        from frappe import _dict
        from frappe.model import document
        from cipher_aec.awards.runtime_profile import TARGETS
        from unittest.mock import Mock
        def doc(kind):
            value=SimpleNamespace(doctype=kind,name='row',company='Company A',flags=_dict(),_action='save',
                run_method=Mock(),clear_cache=Mock(),notify_update=Mock(),save_version=Mock(),is_new=lambda:True)
            value.get=lambda key,default=None:getattr(value,key,default)
            return value
        fake=SimpleNamespace(flags=_dict(in_import=False,currently_saving=[]))
        with patch.object(document,'frappe',fake),patch.object(document,'update_global_search'):
            for kind in TARGETS:
                ordinary=doc(kind);runtime.quiet_award_write(ordinary)
                document.Document.run_post_save_methods(ordinary)
                ordinary.notify_update.assert_called_once()
            with runtime.command_boundary(company='Company A',operation_id='operation'):
                self.begin()
                for kind in TARGETS:
                    current=doc(kind);runtime.quiet_award_write(current)
                    document.Document.run_post_save_methods(current)
                    current.notify_update.assert_not_called()
                    current.save_version.assert_called_once()
                    self.assertEqual([call.args for call in current.run_method.call_args_list],[('on_update',),('on_change',)])
                for kind,company in [('Version','Company A'),('Cipher Command Receipt','foreign')]:
                    refused=doc(kind);refused.company=company
                    with self.assertRaises(DomainError):runtime.quiet_award_write(refused)
                    self.assertNotIn('notify_update',refused.flags)

    @contextmanager
    def native_cache(self):
        from frappe.model import document
        self.db.value_cache={};values={};deletions=[]
        def delete(key):deletions.append(key);values.pop(key,None)
        self.fake.cache=SimpleNamespace(delete_value=delete,delete_keys=delete)
        with patch.object(document,'frappe',self.fake):yield document,values,deletions

    def written(self,name='actual-native-name'):
        value=SimpleNamespace(doctype='Project',name=name,company='Company A',flags=SimpleNamespace())
        value.get=lambda key,default=None:getattr(value,key,default)
        return value

    def test_real_native_cache_closure_preserved_on_success_and_reinvalidates_after_commit(self):
        with self.native_cache() as (document,cache,deletions):
            key=document.get_document_cache_key('Project','actual-native-name')
            with runtime.command_boundary(company='Company A',operation_id='operation'):
                self.begin();doc=self.written(None);runtime.quiet_award_write(doc)
                doc.name='actual-native-name' # Native naming follows registration.
                cache[key]='old';document.clear_document_cache('Project',doc.name)
                self.assertNotIn(key,cache);cache[key]='repopulated committed value'
            self.assertEqual(cache[key],'repopulated committed value')
            commit=runtime._contents(self.db.after_commit);rollback=runtime._contents(self.db.after_rollback)
            self.assertIs(commit[0],self.sentinels['after_commit']);self.assertIs(commit[-1],rollback[-1])
            self.db.after_commit.run();self.assertNotIn(key,cache)
            self.assertEqual(deletions,[key,key]);self.assertEqual(self.full_rollbacks,0)

    def test_refused_stage_reinvalidates_repopulated_native_cache_before_savepoint_rollback(self):
        self.sql.execute('SAVEPOINT command')
        with self.native_cache() as (document,cache,deletions):
            key=document.get_document_cache_key('Project','actual-native-name')
            with self.assertRaises(DomainError):
                with runtime.command_boundary(company='Company A',operation_id='operation'):
                    self.begin();self.sql.execute("INSERT INTO records VALUES ('Project')")
                    doc=self.written();runtime.quiet_award_write(doc)
                    document.clear_document_cache('Project',doc.name);cache[key]='uncommitted profile'
                    raise DomainError('source_revoked','Current source refusal',403)
            # No own cache reads occur between runtime cleanup and the command
            # owner's rollback. The observation follows that SQL boundary.
            self.sql.execute('ROLLBACK TO SAVEPOINT command')
            self.assertNotIn(key,cache);self.assertEqual(deletions,[key,key])
            self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
            for name in runtime.MANAGERS:self.assertEqual(runtime._contents(getattr(self.db,name)),(self.sentinels[name],))
            self.assertEqual(self.full_rollbacks,0)

    def test_native_cache_callback_requires_exact_stage_object_and_uncloned_code_identity(self):
        from types import FunctionType
        for wrong in ('different-name','doctype-wide','cloned-code','foreign-globals'):
            with self.subTest(wrong=wrong),self.native_cache() as (document,cache,deletions),self.assertRaises(runtime.AwardCallbackBoundaryError):
                with runtime.command_boundary(company='Company A',operation_id='operation'):
                    self.begin();doc=self.written();runtime.quiet_award_write(doc)
                    document.clear_document_cache('Project',doc.name if wrong in {'cloned-code','foreign-globals'} else None if wrong=='doctype-wide' else 'unwritten-name')
                    if wrong in {'cloned-code','foreign-globals'}:
                        original=runtime._contents(self.db.after_commit)[-1]
                        clone=FunctionType(original.__code__.replace() if wrong=='cloned-code' else original.__code__,
                            original.__globals__ if wrong=='cloned-code' else dict(original.__globals__),closure=original.__closure__)
                        self.db.after_commit.add(clone);self.db.after_rollback.add(clone)
            # Each forced rollback resets the native managers; restore unrelated
            # prior callback sentinels for the next independent invocation.
            for name,callback in self.sentinels.items():getattr(self.db,name).add(callback)
        self.assertEqual(self.full_rollbacks,4)

    def test_native_cache_cleanup_failure_uses_typed_full_rollback_not_a_vanished_savepoint(self):
        with self.native_cache() as (document,cache,deletions):
            actual=self.fake.cache.delete_value;calls=[]
            def fail_cleanup_once(key):
                calls.append(key)
                if len(calls)==2:raise OSError('controlled derived-cache outage')
                actual(key)
            self.fake.cache.delete_value=fail_cleanup_once
            with self.assertRaises(runtime.AwardCallbackBoundaryError) as raised:
                with runtime.command_boundary(company='Company A',operation_id='operation'):
                    self.begin();self.sql.execute("INSERT INTO records VALUES ('Project')")
                    doc=self.written();runtime.quiet_award_write(doc);document.clear_document_cache('Project',doc.name)
                    raise DomainError('source_revoked','Refused',403)
            self.assertEqual(raised.exception.code,'award_cache_cleanup_failed')
            self.assertEqual(self.full_rollbacks,1);self.assertEqual(len(calls),3)
            self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)


    def test_unknown_rollback_cleanup_runs_via_full_rollback_and_commit_intent_never_runs(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'native-effect';path.write_text('staged')
            with self.assertRaises(runtime.AwardCallbackBoundaryError):
                with runtime.command_boundary(company='Company A',operation_id='operation'):
                    self.begin();self.sql.execute("INSERT INTO records VALUES ('Project')")
                    self.db.after_rollback.add(lambda:path.unlink())
                    self.db.after_commit.add(lambda:self.seen.append('unsafe'))
            self.assertFalse(path.exists());self.assertEqual(self.full_rollbacks,1)
            self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
            self.assertNotIn('unsafe',self.seen)
            self.assertIn('before_rollback',self.seen);self.assertIn('after_rollback',self.seen)

    def test_db_switch_rolls_back_both_actual_sql_transactions(self):
        other_sql=sqlite3.connect(':memory:');self.addCleanup(other_sql.close)
        other_sql.execute('CREATE TABLE effect (id TEXT)');other_sql.commit()
        other=SimpleNamespace(**{name:CallbackManager() for name in runtime.MANAGERS})
        rolled=[]
        def other_rollback():rolled.append(True);other_sql.rollback()
        other.rollback=other_rollback
        with self.assertRaises(runtime.AwardCallbackBoundaryError):
            with runtime.command_boundary(company='Company A',operation_id='operation'):
                self.begin();self.sql.execute("INSERT INTO records VALUES ('Project')")
                other_sql.execute("INSERT INTO effect VALUES ('other')");self.fake.db=other
        self.assertEqual(self.full_rollbacks,1);self.assertEqual(rolled,[True])
        self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
        self.assertEqual(other_sql.execute('SELECT COUNT(*) FROM effect').fetchone()[0],0)

    def test_callable_equality_cannot_hide_prefix_substitution(self):
        class Callable:
            def __call__(self):pass
            def __eq__(self,other):return True
        self.db.before_commit.reset();original=Callable();self.db.before_commit.add(original)
        with self.assertRaises(runtime.AwardCallbackBoundaryError):
            with runtime.command_boundary(company='Company A',operation_id='operation'):
                self.begin();self.db.before_commit.reset();self.db.before_commit.add(Callable())
        self.assertEqual(self.full_rollbacks,1)


    def test_full_rollback_discards_prior_and_new_local_deferred_intents(self):
        self.local._webhook_queue.append({'prior':'business-intent'})
        self.local._realtime_log.append({'prior':'realtime'})
        with self.assertRaises(runtime.AwardCallbackBoundaryError):
            with runtime.command_boundary(company='Company A',operation_id='operation'):
                self.begin();self.local._webhook_queue.append({'new':'business-intent'})
                self.db.after_rollback.add(lambda:None)
        self.assertEqual(self.local._webhook_queue,[]);self.assertEqual(self.local._realtime_log,[])

    def test_throwing_rollback_cleanup_keeps_typed_fatal_boundary_and_closes_sql(self):
        def cleanup():
            self.seen.append('cleanup');raise RuntimeError('native cleanup failure')
        with self.assertRaises(runtime.AwardCallbackBoundaryError) as error:
            with runtime.command_boundary(company='Company A',operation_id='operation'):
                self.begin();self.sql.execute("INSERT INTO records VALUES ('Project')")
                self.db.before_rollback.add(cleanup)
        self.assertEqual(error.exception.code,'award_rollback_cleanup_failed')
        self.assertEqual(self.seen.count('cleanup'),1);self.assertEqual(self.full_rollbacks,2)
        self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
