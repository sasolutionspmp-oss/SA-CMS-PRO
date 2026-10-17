"""Exact private award factories/controllers, without a site or native posting."""
from contextlib import ExitStack
from copy import deepcopy
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from uuid import UUID,uuid5

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.awards import effect
from cipher_aec.construction_finance import award_factory as factory,records
from cipher_aec.tests import test_award_native as fixture


class AwardFactoryTests(unittest.TestCase):
    def setUp(self):
        self.actor=fixture.record(user='author@example.test',person_id=fixture.identity('author'))
        issue,lines,definition=fixture.fixtures()
        case=fixture.AwardNative()
        try:
            case.setUp();snapshot=case.actual()
        finally:
            case.doCleanups()
        snapshot['derived_digest']=snapshot['digest']
        contract={'number':'Reviewed prime','kind':'prime','direction':'receivable','party_type':'Customer','party':definition['customer'],
            'currency':'USD','original_value':{'amount':'30.00','currency':'USD'}}
        self.plan={'id':fixture.identity('plan'),'company':'Company A','handoff':fixture.identity('award'),'author_person':self.actor.person_id,
            'issue':issue['id'],'issue_digest':digest(issue),'source_facts':{'pursuit':fixture.identity('pursuit'),'opportunity':'OPP-original','accepted_estimate':issue['accepted_estimate']},
            'lines':lines,'definition':{'native_order_definition':definition,'contract_definition':contract,
                'team':{'members':[{'person_id':'included-member','abilities':['project.read']}]}},'controls_plan':{'immutable':'cost plan'},
            'ids':{'adoption_id':fixture.identity('adoption'),'contract_id':fixture.identity('contract'),'profile_id':fixture.identity('profile')}}
        self.binding=dict(company='Company A',project='Project A',award_id=self.plan['handoff'],award_revision_id=self.plan['id'],
            plan_digest=digest(self.plan),packet_id='packet',decision_id='decision',operation_id=fixture.identity('operation'))
        self.active={**self.binding,'actor_person':self.actor.person_id,'actor_user':self.actor.user,'plan':deepcopy(self.plan),'issue':issue,
            'adoption_id':self.plan['ids']['adoption_id'],'contract_id':self.plan['ids']['contract_id'],'profile_id':self.plan['ids']['profile_id'],
            'approved_team':self.plan['definition']['team']['members'],'controls_plan_digest':digest(self.plan['controls_plan']),
            'issue_digest':digest(issue),'lines_digest':digest(lines),'native_definition_digest':digest(definition),
            'contract_definition_digest':digest(contract),'native_output':{'sales_order':'SO-test','native_snapshot':snapshot,'native_digest':snapshot['digest'],'native_version':snapshot['version']},
            'admission_preflight':{'contract_id':self.plan['ids']['contract_id'],'channel_count':12,'status':'new_contract_without_supported_obligations'}}
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        token=effect._active.set(self.active);self.addCleanup(effect._active.reset,token)
        self.stack.enter_context(patch('cipher_aec.governance.approvals.require_approval_effect',return_value={'company':'Company A','source_version':digest(self.plan)}))
        self.stack.enter_context(patch.object(factory,'is_prelocked',return_value=True))
        self.stack.enter_context(patch.object(factory.units,'currency_policy',return_value={'currency':'USD','currency_exponent':2}))
        self.customer=fixture.record(name='Existing customer',modified='customer-v1',disabled=0)
        self.native=self.stack.enter_context(patch.object(factory,'require_native',return_value=self.customer))
        self.stack.enter_context(patch.object(records,'require_trusted_write'))
        self.stack.enter_context(patch.object(records,'current_actor',return_value=self.actor))
        self.project=self.stack.enter_context(patch.object(records,'require_project',side_effect=AssertionError('Excluded requester must not acquire invented Project duties')))
        self.sql=sqlite3.connect(':memory:');self.addCleanup(self.sql.close)
        self.sql.execute('CREATE TABLE contracts (id TEXT PRIMARY KEY,body TEXT)')

    def create(self):
        return factory.create_initial_contract(actor=self.actor,company='Company A',project='Project A',plan=self.plan,packet_id='packet',decision_id='decision',
            operation_id=self.binding['operation_id'],resource_token={'complete':'reviewed union'})

    def insert(self,record_kind,value,**fields):
        doc=fixture.record(doctype='Cipher Construction Contract',name=value['id'],data_json=json.dumps(value),record_digest=digest(value),
            company=value['company'],project=value['project'],author_person=value['author_person'],status=value['status'],**fields)
        doc.is_new=lambda:True;doc._contract=lambda body:records.FinanceRecord._contract(doc,body)
        records.FinanceRecord.validate(doc)
        self.sql.execute('INSERT INTO contracts VALUES(?,?)',(value['id'],json.dumps(value)))
        return doc

    def test_exact_initial_draft_controller_allows_excluded_requester_without_project_duties(self):
        with patch.object(factory.repository,'insert',side_effect=self.insert):result=self.create()
        self.assertEqual(result['origin'],factory.ORIGIN);self.assertEqual(result['creation_admission']['provider'],factory.INITIAL_PROVIDER)
        self.assertEqual(result['creation_admission']['status'],'qualified_award_draft_obligation')
        self.assertEqual(result['definition']['original_value']['amount'],'30.00')
        self.assertEqual(result['award_origin']['native_digest'],self.active['native_output']['native_digest'])
        self.assertIsNone(result['accepted_revision']);self.assertIsNone(result['draft_revision'])
        self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM contracts').fetchone()[0],1);self.project.assert_not_called()
        self.assertNotIn(self.actor.person_id,[member['person_id'] for member in self.active['approved_team']])
        self.assertIsNone(factory._constructing.get())

    def test_staged_controller_rejects_changed_scope_author_or_definition_before_insert(self):
        for key,value in [('company','foreign'),('author_person','forged'),('project','other-project')]:
            def substituted(record_kind,body,**fields):
                changed=deepcopy(body);changed[key]=value
                return self.insert(record_kind,changed,**fields)
            with self.subTest(key=key),patch.object(factory.repository,'insert',side_effect=substituted),self.assertRaises(DomainError):self.create()
            self.assertIsNone(factory._constructing.get())
        self.assertEqual(self.sql.execute('SELECT COUNT(*) FROM contracts').fetchone()[0],0)
        with self.assertRaises(DomainError):factory.validate_new_contract({'id':self.plan['ids']['contract_id']})

    def test_missing_source_union_native_output_preflight_or_current_party_rights_refuse(self):
        with patch.object(factory.repository,'insert') as insert:
            for field in ('native_output','admission_preflight'):
                old=self.active[field];self.active[field]=None
                with self.subTest(field=field),self.assertRaises(DomainError):self.create()
                self.active[field]=old
            with patch.object(factory,'is_prelocked',return_value=False),self.assertRaises(DomainError):self.create()
            self.native.side_effect=DomainError('native_permission_denied','Current Customer unavailable',403)
            with self.assertRaises(DomainError):self.create()
            insert.assert_not_called()

    def test_customer_mutex_preflight_is_before_native_write_and_never_calls_public_fin_create(self):
        self.active['native_output']=None;self.active['admission_preflight']=None
        proof={'contract_id':self.active['contract_id'],'channel_count':12,'status':'qualified_award_observations','source_watermark':'opaque'}
        observed=[]
        self.native.side_effect=lambda *args,**kw:(observed.append(('Customer',kw['lock'])) or self.customer)
        def scan(contract,**kw):
            self.assertEqual(observed,[('Customer',True)]);self.assertTrue(kw['lock']);return proof
        with patch.object(factory.sources,'admission',side_effect=scan):
            actual=factory.admission_preflight(actor=self.actor,company='Company A',project='Project A',plan=self.plan,packet_id='packet',decision_id='decision',
                operation_id=self.binding['operation_id'],resource_token={'complete':'reviewed union'})
        self.assertEqual(actual,proof);self.assertEqual(self.active['admission_preflight'],proof)
        with self.assertRaises(DomainError):effect.record_admission_preflight(proof)

    def test_native_effect_requires_exact_reviewed_issue_lines_definition_and_admission(self):
        kwargs={**self.binding,'actor':self.actor,'issue':self.active['issue'],'lines':self.plan['lines'],'definition':self.plan['definition']['native_order_definition']}
        with patch('cipher_aec.awards.runtime.require_native_profile') as profile:
            for key,changed in [('issue',{'id':'other'}),('lines',[]),('definition',{'customer':'other'})]:
                with self.subTest(key=key),self.assertRaises(DomainError):
                    with effect.native_order_effect(**{**kwargs,key:changed}):self.fail('Changed payload reached native effect')
            profile.assert_not_called()
            self.active['admission_preflight']=None
            with self.assertRaises(DomainError):
                with effect.native_order_effect(**kwargs):self.fail('Missing admission reached native effect')
        self.assertIsNone(effect._native.get())

    def test_active_native_hook_rejects_terms_template_amendment_updater_and_prior_doc_defaults(self):
        issue=self.active['issue'];line=self.plan['lines'][0]
        row=fixture.record(cipher_award_line_id=line['award_line_id'],cipher_proposal_line_id=line['proposal_line_id'],item_code=line['item_code'],
            uom='Count',stock_uom='Count',prevdoc_docname=None,quotation_item=None,qty='2',rate='15.00',amount='30.00',conversion_factor='1')
        doc=fixture.record(doctype='Sales Order',name='SO-test',company='Company A',project='Project A',customer='Existing customer',currency='USD',docstatus=0,
            cipher_award_handoff=self.plan['handoff'],cipher_issue=issue['id'],cipher_issue_digest=digest(issue),cipher_proposal_revision=issue['proposal_revision'],
            cipher_accepted_baseline=issue['accepted_estimate']['acceptance_id'],flags=SimpleNamespace(),items=[row],is_new=lambda:True,
            payment_schedule=[fixture.record(**self.active['native_output']['native_snapshot']['projection']['payment_schedule'][0])])
        kwargs={**self.binding,'actor':self.actor,'issue':issue,'lines':self.plan['lines'],'definition':self.plan['definition']['native_order_definition']}
        with patch('cipher_aec.awards.runtime.require_native_profile'),patch.dict('sys.modules',{'frappe':SimpleNamespace(session=SimpleNamespace(user=self.actor.user))}):
            with effect.native_order_effect(**kwargs):
                effect.validate_native_order(doc,'before_insert')
                for owner,key,bad in [(vars(doc),'tc_name','Terms with attachments'),(vars(doc),'payment_terms_template','Inherited template'),(vars(doc),'amended_from','older'),
                        (vars(doc.flags),'updater_reference','updater'),(vars(doc),'_doc_before_save',object())]:
                    owner[key]=bad
                    with self.subTest(key=key),self.assertRaises(DomainError):effect.validate_native_order(doc,'validate')
                    owner.pop(key)
                payment=doc.payment_schedule[0]
                for key,bad in [('payment_amount','29.99'),('due_date','2026-11-20'),('discount','1'),('payment_term','unreviewed')]:
                    original=getattr(payment,key);setattr(payment,key,bad)
                    with self.subTest(payment_field=key),self.assertRaises(DomainError):effect.validate_native_order(doc,'before_save')
                    setattr(payment,key,original)
                doc.payment_schedule=[]
                with self.assertRaises(DomainError):effect.validate_native_order(doc,'validate')
                doc.payment_schedule=[payment]
                doc.is_new=lambda:False
                with self.assertRaises(DomainError):effect.validate_native_order(doc,'before_save')
                doc.flags.ignore_version=True
                effect.validate_native_order(doc,'before_save')

    def adoption(self):
        plan=self.plan;native=self.active['native_output']
        return {'id':self.active['adoption_id'],'schema':'cipher.award.adoption.v1','status':'adopted','scope_type':'Company','company':'Company A','project':None,'target_project':'Project A',
            'author_person':self.actor.person_id,'author_user':self.actor.user,'handoff':plan['handoff'],'award_revision':plan['id'],'pursuit':plan['source_facts']['pursuit'],
            'opportunity':plan['source_facts']['opportunity'],'issue':plan['issue'],'issue_digest':plan['issue_digest'],'contract':self.active['contract_id'],'sales_order':native['sales_order'],
            'effect_binding':self.binding,'plan_digest':digest(plan),'accepted_estimate':plan['source_facts']['accepted_estimate'],'native_digest':native['native_digest'],
            'native_version':native['native_version'],'native_snapshot':native['native_snapshot'],'profile':self.active['profile_id'],
            'budget':str(uuid5(UUID(plan['handoff']),'initial-budget.v1')),'controls_plan_digest':self.active['controls_plan_digest'],'team':self.active['approved_team'],
            'line_adoptions':[row['award_line_id'] for row in plan['lines']],'packet_id':'packet','decision_id':'decision','operation_id':self.binding['operation_id']}

    def test_adoption_controller_binds_deterministic_ids_scope_author_native_and_exact_team(self):
        original=self.adoption();effect.validate_adoption_record('adoption',original)
        for key,value in [('id',fixture.identity('other')),('target_project','other'),('company','foreign'),('author_user','other'),('budget',fixture.identity('other-budget')),
                ('native_digest','a'*64),('team',[{'person_id':self.actor.person_id,'abilities':['project.read']}]),('contract',fixture.identity('other-contract'))]:
            changed=deepcopy(original);changed[key]=value
            with self.subTest(key=key),self.assertRaises(DomainError):effect.validate_adoption_record('adoption',changed)

    def test_line_controller_requires_exact_issued_line_and_saved_native_child(self):
        value=self.adoption();line=self.plan['lines'][0]
        for key in ('plan_digest','accepted_estimate','native_digest','native_version','native_snapshot','profile','budget','controls_plan_digest','team','line_adoptions','packet_id','decision_id','operation_id'):value.pop(key)
        value.update(id=line['award_line_id'],schema='cipher.award.line-adoption.v1',adoption=self.active['adoption_id'],proposal_line_id=line['proposal_line_id'],sales_order_item='SOI-test',source_line=deepcopy(line))
        effect.validate_adoption_record('line',value)
        for key,wrong in [('sales_order_item','other-native-child'),('adoption',fixture.identity('other')),('proposal_line_id',fixture.identity('other-line')),('target_project','foreign')]:
            changed=deepcopy(value);changed[key]=wrong
            with self.subTest(key=key),self.assertRaises(DomainError):effect.validate_adoption_record('line',changed)


    def test_borrowed_projection_setup_restores_native_function_even_on_failure(self):
        from contextlib import nullcontext
        from cipher_aec.tests.test_award_admission import lineage
        before=fixture.native._canonical_names
        for fails in (False,True):
            for borrower in ('lineage','factory'):
                with self.subTest(fails=fails,borrower=borrower):
                    inner=AwardFactoryTests('test_exact_initial_draft_controller_allows_excluded_requester_without_project_duties')
                    def build():
                        if borrower=='lineage':return lineage()
                        try:return inner.setUp()
                        finally:inner.doCleanups()
                    with patch.object(fixture.AwardNative,'actual',side_effect=RuntimeError('Projection fixture failed')) if fails else nullcontext():
                        if fails:
                            with self.assertRaises(RuntimeError):build()
                        else:build()
                    self.assertIs(fixture.native._canonical_names,before)
