"""Real shared command engine, SQLite receipt/effect rollback, pinned managers."""
import json
import sqlite3
from contextlib import contextmanager,ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from frappe.utils import CallbackManager
from cipher_aec.api.errors import DomainError
from cipher_aec.governance import commands,approvals,domain_approvals
from cipher_aec.documents import provenance
from cipher_aec.awards import runtime


class AwardCommandBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.sql=sqlite3.connect(':memory:');self.sql.row_factory=sqlite3.Row;self.addCleanup(self.sql.close)
        self.sql.execute('CREATE TABLE records (kind TEXT PRIMARY KEY)')
        self.sql.execute('CREATE TABLE `tabCipher Command Receipt` (name TEXT PRIMARY KEY,request_hash TEXT,result_json TEXT,result_hash TEXT,scope_type TEXT,company TEXT,project TEXT)');self.sql.commit()
        self.rollbacks=[];self.seen=[];self.fail_receipt=False
        self.db=SimpleNamespace(**{name:CallbackManager() for name in runtime.MANAGERS})
        self.db.savepoint=lambda name:self.sql.execute('SAVEPOINT '+name)
        def rollback(*,save_point=None):
            self.rollbacks.append(save_point)
            self.assertIsNone(provenance.logical_operation_stats(),'Logical finally must precede every rollback')
            if save_point:self.sql.execute('ROLLBACK TO SAVEPOINT '+save_point)
            else:
                self.db.before_commit.reset();self.db.after_commit.reset();self.db.before_rollback.run()
                self.sql.rollback();self.db.after_rollback.run()
        self.db.rollback=rollback
        def query(q,args,as_dict=False):
            if 'tabCipher Person' in q or 'tabCipher Identity Binding' in q:return []
            rows=self.sql.execute(q.replace('%s','?').replace(' FOR UPDATE',''),args).fetchall()
            return [SimpleNamespace(**dict(r)) for r in rows] if as_dict else rows
        self.db.sql=query
        self.local=SimpleNamespace(_webhook_queue=[],_realtime_log=[])
        def get_doc(value):
            doc=SimpleNamespace(**value,flags=SimpleNamespace())
            doc.get=lambda key,default=None:getattr(doc,key,default)
            def insert(**kw):
                self.assertIsNotNone(provenance.logical_operation_stats(),'Receipt construction remains inside logical lifetime')
                if runtime._boundary.get() and runtime._boundary.get()['stage']:
                    self.assertIs(doc.flags.notify_update,False,'Late receipt must suppress native deferred UI notices')
                else:self.assertFalse(hasattr(doc.flags,'notify_update'),'Other commands keep the native default')
                if value['doctype']=='Cipher Approval Consumption':
                    self.sql.execute("INSERT INTO records VALUES ('Consumption')");return
                if self.fail_receipt:self.sql.execute("INSERT INTO records VALUES ('prior')")
                self.sql.execute('INSERT INTO `tabCipher Command Receipt` VALUES(?,?,?,?,?,?,?)',tuple(value[k] for k in ('name','request_hash','result_json','result_hash','scope_type','company','project')))
            doc.insert=insert
            return doc
        self.fake=SimpleNamespace(db=self.db,local=self.local,get_doc=get_doc,QueryDeadlockError=type('Deadlock',(Exception,),{}),QueryTimeoutError=type('Timeout',(Exception,),{}))
        self.actor=SimpleNamespace(user='author',person_id='canonical-author')
        self.sentinel=lambda:self.seen.append('prior-commit');self.db.after_commit.add(self.sentinel)
        for p in (patch.object(commands,'frappe',self.fake),patch.object(runtime,'frappe',self.fake),patch.object(commands,'current_actor',return_value=self.actor),
                patch.object(commands,'require_company',return_value=object()),patch.object(commands,'require_project',return_value=SimpleNamespace(status='Open')),
                patch.object(commands,'assert_synthetic_site'),patch.object(commands,'require_effects_enabled'),patch.object(provenance,'_current_db',return_value=self.db),
                patch.object(commands,'authorize_receipt')):
            p.start();self.addCleanup(p.stop)
        self.operation=str(uuid4())
    def call(self,effect,*,command='approval.execute'):
        return commands.run_company_command(company='A',operation_id=self.operation,command=command,payload={'packet_id':'packet'},ability='approval.execute',effect=effect)
    def begin(self):runtime.begin_callback_stage(company='A',operation_id=self.operation,packet_id='packet',award_revision_id='revision',plan_digest='digest')
    def invalidator(self):
        state={'valid':True,'authorized':set()};provenance._watch_transaction(state)
        # Literal domain finally exits before the outer command owner checks.
        provenance._invalidate(state)
    def test_real_command_success_owner_encloses_effect_receipt_and_logical_finally(self):
        def effect(*args):
            self.begin();self.sql.execute("INSERT INTO records VALUES ('Project')");self.invalidator();return {'created':'Project'}
        result=self.call(effect)
        self.assertFalse(result['operation']['replayed']);self.assertEqual(self.rollbacks,[])
        self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM `tabCipher Command Receipt`').fetchone()[0],1)
        self.assertEqual(self.sql.execute('SELECT kind FROM records').fetchone()[0],'Project');self.assertIsNone(provenance.logical_operation_stats())
        self.assertIs(runtime._contents(self.db.after_commit)[0],self.sentinel)
    def test_real_late_receipt_sql_failure_removes_effect_and_preserves_prior_callbacks(self):
        self.sql.execute("INSERT INTO records VALUES ('prior')");self.fail_receipt=True
        def effect(*args):
            self.begin();self.sql.execute("INSERT INTO records VALUES ('Project')");self.invalidator()
            self.db.after_commit.add(lambda:self.seen.append('unsafe'));return {'created':'Project'}
        with self.assertRaises(sqlite3.IntegrityError):self.call(effect)
        self.assertEqual([r[0] for r in self.sql.execute('SELECT kind FROM records')],['prior'])
        self.assertEqual(len(self.rollbacks),1);self.assertTrue(self.rollbacks[0].startswith('cipher_company_'))
        self.assertEqual(runtime._contents(self.db.after_commit),(self.sentinel,));self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM `tabCipher Command Receipt`').fetchone()[0],0)
    def test_fatal_callback_reset_skips_vanished_savepoint_and_rolls_back_receipt_too(self):
        def effect(*args):
            self.begin();self.sql.execute("INSERT INTO records VALUES ('Project')");self.db.before_commit=CallbackManager();return {'created':'Project'}
        with self.assertRaises(runtime.AwardCallbackBoundaryError):self.call(effect)
        self.assertEqual(self.rollbacks,[None]);self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
        self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM `tabCipher Command Receipt`').fetchone()[0],0)
    def test_completed_replay_never_enters_allocation_or_callback_stage(self):
        first=self.call(lambda *args:{'saved':'original'})
        with patch.object(runtime,'command_boundary',side_effect=AssertionError('Replay cannot allocate')):
            replay=self.call(lambda *args:self.fail('Replayed effect ran'))
        self.assertTrue(replay['operation']['replayed']);self.assertEqual(first['saved'],replay['saved']);self.assertEqual(self.rollbacks,[])
    def test_other_company_command_and_other_action_keep_ordinary_callbacks(self):
        callback=lambda:self.seen.append('ordinary')
        def ordinary(*args):self.db.after_commit.add(callback);return {'ordinary':True}
        self.assertTrue(self.call(ordinary)['ordinary'])
        self.assertIs(runtime._contents(self.db.after_commit)[-1],callback)
        self.operation=str(uuid4())
        with patch.object(runtime,'command_boundary',side_effect=AssertionError('Non-approval command cannot own award stage')):
            self.call(ordinary,command='company.fixture.v1')
    def test_project_command_keeps_its_original_savepoint_and_lifetime(self):
        def effect(*args):
            self.assertIsNone(provenance.logical_operation_stats());raise DomainError('fixture_denied','Denied',403)
        with patch.object(runtime,'command_boundary',side_effect=AssertionError('Project path unchanged')),self.assertRaises(DomainError):
            commands.run_command(company='A',project='real',operation_id=self.operation,command='project.fixture',payload={},ability='project.read',effect=effect)
        self.assertEqual(self.rollbacks,['cipher_command'])

    def test_real_shared_execute_suppresses_late_consumption_and_receipt_only_after_stage(self):
        # Keep the real execute and command receipt code. Stub domain authority
        # and allocation only: this proves notification placement, not grants.
        packet=SimpleNamespace(name='packet',action='award.project.create.v1',company='A',project=None,scope_type='Company',subject_id='revision',
            requester_person=self.actor.person_id,source_version='source',manifest_hash='hash',manifest_json=json.dumps({'domain':{}}))
        decision=SimpleNamespace(name='decision',actor_person='reviewer',decision='Grant')
        reviewer=SimpleNamespace(user='reviewer-user',person_id='reviewer')
        original_sql=self.db.sql
        def sql(query,args,**kw):
            if query.startswith('SELECT user FROM `tabCipher Identity Binding`'):return [SimpleNamespace(user=reviewer.user)]
            if query.startswith('SELECT identity_kind FROM `tabCipher Person`'):return [('Human',)]
            return original_sql(query,args,**kw)
        @contextmanager
        def stage(*args):self.begin();yield
        with ExitStack() as stack:
            for replacement in (patch.object(approvals,'frappe',self.fake),patch.object(approvals,'_scope'),patch.object(approvals,'_load',return_value=packet),
                patch.object(approvals,'_decisions',return_value=[decision]),patch.object(approvals,'_check_hash'),patch.object(approvals,'_state',return_value=('Granted',[decision])),
                patch.object(approvals,'current_actor',return_value=reviewer),patch.object(approvals,'_event'),patch.object(approvals,'present',return_value={'id':'packet','state':'Consumed'}),
                patch.object(domain_approvals,'participant_people',return_value=(self.actor.person_id,)),patch.object(domain_approvals,'require_participants'),
                patch.object(domain_approvals,'spec_for'),patch.object(domain_approvals,'authorize'),patch.object(domain_approvals,'callbacks',return_value=(None,None,lambda **kw:{'created':'Project'})),
                patch('cipher_aec.awards.preallocation.stage',side_effect=stage),patch.object(self.db,'sql',side_effect=sql)):
                stack.enter_context(replacement)
            result=approvals.execute_packet('A',None,'packet','hash',self.operation,scope_type='Company')
        self.assertEqual(result['effect'],{'created':'Project'});self.assertEqual(self.rollbacks,[])
        self.assertEqual(self.sql.execute('SELECT kind FROM records').fetchall()[0][0],'Consumption')
        self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM `tabCipher Command Receipt`').fetchone()[0],1)
