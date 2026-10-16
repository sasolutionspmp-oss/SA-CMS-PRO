"""Literal allocation sequencing and refusal; no site or native writer enabled."""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from uuid import uuid4
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.awards import preallocation as p
from cipher_aec.governance import approvals,domain_approvals


class AwardPreallocationTests(unittest.TestCase):
    def setUp(self):
        self.actor=SimpleNamespace(user='author',person_id='author')
        self.plan={'id':str(uuid4()),'company':'A','handoff':str(uuid4()),'author_person':'author','participants':['author','team'],
            'ids':{'profile_id':str(uuid4())},'definition':{'project_definition':{'project_name':'Reviewed actual project','expected_start_date':'2026-10-16','expected_end_date':'2026-11-16'},
                'native_order_definition':{'customer':'Customer A'},'team':{'delegator_person':'author','members':[{'person_id':'team','abilities':['project.read']}]}}}
        self.parent={'current_revision':self.plan['id'],'status':'draft','adoption':None}
        self.policy=SimpleNamespace(name='policy',definition_json=json.dumps({'fixed':True}))
        outer={'action':p.ACTION,'scope_type':'Company','company':'A','project':None,'requester_person':'author','source_version':digest(self.plan),
            'policy_hash':digest({'fixed':True}),'domain':{'effect':{'action':p.ACTION,'award_revision_id':self.plan['id'],'award_id':self.plan['handoff'],'plan_digest':digest(self.plan),'plan':deepcopy(self.plan)}}}
        self.packet=SimpleNamespace(name='packet',company='A',project=None,scope_type='Company',action=p.ACTION,requester_person='author',
            subject_id=self.plan['id'],subject_type='Cipher Award Handoff Revision',manifest_json=json.dumps(outer),manifest_hash=digest(outer),
            source_version=digest(self.plan),policy_revision='policy',expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
        self.decision=SimpleNamespace(name='decision',decision='Grant',actor_person='reviewer',manifest_hash=self.packet.manifest_hash)
        self.people=('author','reviewer','team')
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for replacement in (patch.object(p.repository,'read',side_effect=lambda kind,*a,**kw:self.plan if kind=='revision' else self.parent),
            patch('cipher_aec.awards.service.participant_people',return_value=tuple(self.plan['participants'])),
            patch.object(p.team,'authorize'),patch.object(p,'require_company'),patch('cipher_aec.commercial.native.can_create'),
            patch.object(approvals,'_consumption',return_value=None),patch.object(approvals,'_decisions',return_value=[self.decision]),
            patch.object(approvals,'_policy',return_value=self.policy)):
            self.stack.enter_context(replacement)
        self.enabled=replace(domain_approvals.ACTIONS[p.ACTION],enabled=True)
    def basic(self):
        with patch.dict(domain_approvals.ACTIONS,{p.ACTION:self.enabled}):return p._basic(self.packet,self.actor,'operation',self.people)
    def test_exact_grant_and_complete_participants_precede_any_native_allocation(self):
        plan,decision=self.basic();self.assertIs(plan,self.plan);self.assertIs(decision,self.decision)
        for field,value in [('decision','Withdraw'),('actor_person','author'),('manifest_hash','wrong')]:
            old=getattr(self.decision,field);setattr(self.decision,field,value)
            try:
                with self.subTest(field=field),self.assertRaises(DomainError):self.basic()
            finally:setattr(self.decision,field,old)
        with self.assertRaises(DomainError):
            with patch.dict(domain_approvals.ACTIONS,{p.ACTION:self.enabled}):p._basic(self.packet,self.actor,'operation',('author','reviewer'))
    def test_expired_consumed_stale_plan_and_current_authority_refuse(self):
        self.packet.expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        with self.assertRaises(DomainError):self.basic()
        self.packet.expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        with patch.object(approvals,'_consumption',return_value=object()),self.assertRaises(DomainError):self.basic()
        self.parent['current_revision']='later'
        with self.assertRaises(DomainError):self.basic()
        self.parent['current_revision']=self.plan['id']
        with patch.object(p,'require_company',side_effect=DomainError('capability_denied','Revoked',403)),self.assertRaises(DomainError):self.basic()
    def test_disabled_literal_execute_refuses_before_stage_and_allocation(self):
        self.assertFalse(domain_approvals.ACTIONS[p.ACTION].enabled)
        with patch.object(approvals,'_scope'),patch.object(approvals,'_load',return_value=self.packet),patch.object(approvals,'_decisions',return_value=[self.decision]), \
            patch.object(domain_approvals,'participant_people',return_value=tuple(self.plan['participants'])),patch.object(approvals,'_command',side_effect=lambda **kw:kw['effect'](self.actor,object())), \
            patch.object(p,'stage') as stage,self.assertRaises(DomainError) as error:
            approvals.execute_packet('A',None,'packet',self.packet.manifest_hash,'operation',scope_type='Company')
        self.assertEqual(error.exception.code,'approval_action_unqualified');stage.assert_not_called()
    def test_minimal_project_rejects_unreviewed_defaults_and_exact_document_substitution(self):
        doc=SimpleNamespace(doctype='Project',flags=SimpleNamespace(notify_update=False),is_new=lambda:True,users=[],project_template=None,sales_order=None)
        values={'company':'A','project_name':'Reviewed actual project','customer':'Customer A','expected_start_date':'2026-10-16','expected_end_date':'2026-11-16','status':'Open','percent_complete_method':'Manual','cost_center':None,'project_type':None}
        doc.get=lambda key:values.get(key)
        token=p._creating.set({'doc':doc,'company':'A','plan':self.plan})
        try:
            self.assertTrue(p.validate_native_project(doc))
            for key,value in [('cost_center','unplanned'),('project_type','External'),('customer','other')]:
                old=values[key];values[key]=value
                with self.subTest(key=key),self.assertRaises(DomainError):p.validate_native_project(doc)
                values[key]=old
            for target,key,value in [(values,'amended_from','older-project'),(vars(doc.flags),'updater_reference','updater'),(vars(doc),'_doc_before_save',object())]:
                target[key]=value
                with self.subTest(key=key),self.assertRaises(DomainError):p.validate_native_project(doc)
                target.pop(key)
            with self.assertRaises(DomainError):p.validate_native_project(deepcopy(doc))
        finally:p._creating.reset(token)

    def test_stage_uses_real_minimal_projection_and_caller_refusal_rolls_all_rows_back(self):
        # Exact pinned Project columns deliberately omit amended_from. Execute
        # the actual stage/projection SQL rather than replacing stage itself.
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        fields=('name','company','project_name','customer','expected_start_date','expected_end_date','status','percent_complete_method','cost_center','project_type','project_template','sales_order')
        db.execute('CREATE TABLE `tabProject` ('+','.join(field+' TEXT' for field in fields)+')')
        db.execute('CREATE TABLE profiles (id TEXT,project TEXT)');db.commit()
        calls=[];corrupt=[False]
        def get_doc(value):
            values=deepcopy(value);doc=SimpleNamespace(**value,flags=SimpleNamespace())
            doc.get=lambda key,default=None:values.get(key,default)
            doc.is_new=lambda:True
            def insert(**kw):
                self.assertTrue(p.validate_native_project(doc));calls.append('Project insert');doc.name='PROJECT-real'
                values['name']=doc.name
                if corrupt[0]:values['cost_center']='unplanned default'
                db.execute('INSERT INTO `tabProject` VALUES('+','.join('?' for _ in fields)+')',tuple(values.get(field) for field in fields))
            doc.insert=insert;return doc
        def sql(query,args):
            calls.append('Project projection');return db.execute(query.replace('%s','?').replace(' FOR UPDATE',''),args).fetchall()
        def profile(kind,value):
            self.assertEqual(kind,'profile');p.profile_context(value);calls.append('Profile insert')
            db.execute('INSERT INTO profiles VALUES(?,?)',(value['id'],value['project']))
        with patch.object(p,'_basic',return_value=(self.plan,self.decision)),patch.object(p.runtime,'require_native_profile') as runtime, \
            patch.object(p.runtime,'begin_callback_stage',side_effect=lambda **kw:calls.append('Callback checkpoint')), \
            patch.object(p,'frappe',SimpleNamespace(get_doc=get_doc,db=SimpleNamespace(sql=sql,exists=lambda *a,**k:False))),patch.object(p.repository,'write',side_effect=profile):
            for bad_projection in (False,True):
                corrupt[0]=bad_projection;calls.clear();db.execute('SAVEPOINT command')
                with self.subTest(bad_projection=bad_projection),self.assertRaises(DomainError):
                    with p.stage(self.packet,self.actor,'operation',self.people) as allocated:
                        self.assertEqual(allocated['project'],'PROJECT-real')
                        self.assertEqual(p.current(company='A',packet_id='packet',award_revision_id=self.plan['id'],operation_id='operation',plan_digest=digest(self.plan))['project'],'PROJECT-real')
                        raise DomainError('source_revoked','Post-allocation source refused',403)
                db.execute('ROLLBACK TO SAVEPOINT command')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM `tabProject`').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM profiles').fetchone()[0],0)
                self.assertEqual(calls[:3],['Callback checkpoint','Project insert','Project projection'])
                self.assertEqual('Profile insert' in calls,not bad_projection)
                self.assertIsNone(p._creating.get());self.assertIsNone(p._allocated.get())
            self.assertEqual(runtime.call_count,2)


    def test_withdrawn_old_reviewer_is_not_in_latest_award_allocation_team(self):
        old=SimpleNamespace(name='old-grant',decision='Grant',actor_person='old-reviewer',manifest_hash=self.packet.manifest_hash)
        withdrawn=SimpleNamespace(name='withdrawn',decision='Withdraw',actor_person='author',manifest_hash=self.packet.manifest_hash)
        history=[old,withdrawn,self.decision]
        with patch.dict(domain_approvals.ACTIONS,{p.ACTION:self.enabled}),patch.object(approvals,'_decisions',return_value=history):
            self.assertIs(p._basic(self.packet,self.actor,'operation',self.people)[1],self.decision)
            with patch.object(approvals,'_scope'),patch.object(approvals,'_load',return_value=self.packet),                 patch.object(domain_approvals,'participant_people',return_value=tuple(self.plan['participants'])),                 patch.object(approvals,'_command',side_effect=lambda **kw:kw['effect'](self.actor,object())),                 patch.object(p,'stage',side_effect=DomainError('fixture_stop','Captured before native allocation',409)) as stage,self.assertRaises(DomainError):
                approvals.execute_packet('A',None,'packet',self.packet.manifest_hash,'operation',scope_type='Company')
            self.assertEqual(stage.call_args.args[3],self.people)
            self.assertNotIn('old-reviewer',stage.call_args.args[3])
            self.assertEqual([row['person_id'] for row in self.plan['definition']['team']['members']],['team'])
