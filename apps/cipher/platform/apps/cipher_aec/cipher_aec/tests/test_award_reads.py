"""Inactive award read contracts: native SQL paging and exact team accountability."""
from collections import Counter
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from uuid import UUID

from cipher_aec.api.errors import DomainError
from cipher_aec.awards import listing,service
from cipher_aec.tests.test_award_native import fixtures


class AwardListingTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE `tabCipher Award Handoff` (name TEXT,creation TEXT,company TEXT,project TEXT)')
        self.actor=SimpleNamespace(user='author',person_id='person');self.calls=Counter();self.denied=set();self.corrupt=set()
        def sql(q,args,**kw):return [SimpleNamespace(**dict(row)) for row in self.db.execute(q.replace('%s','?'),args)]
        for p in (patch.object(listing,'frappe',SimpleNamespace(db=SimpleNamespace(sql=sql))),patch.object(listing,'CHUNK',2),
                patch.object(listing,'company_authority_fingerprint',return_value='current'),patch.object(listing,'signing_secret',return_value='fixed-key'),
                patch.object(listing,'page_result',side_effect=lambda items,**kw:{'items':items,**kw})):
            p.start();self.addCleanup(p.stop)
    def row(self,name,date='2026-10-15 12:00:00.123456',company='A',project=None):self.db.execute('INSERT INTO `tabCipher Award Handoff` VALUES(?,?,?,?)',(name,date,company,project))
    def reader(self,name):
        self.calls[name]+=1
        if name in self.denied:raise DomainError('not_found','Unavailable',404)
        if name in self.corrupt:raise DomainError('award_integrity','Invalid',409)
        return {'id':name}
    def page(self,**kw):return listing.listed(company='A',actor=self.actor,kind='handoff',reader=self.reader,limit=2,count_mode='exact',**kw)
    def test_exact_one_pass_private_count_and_native_tie_cursor(self):
        from cipher_aec.api.paging import encode_cursor
        for name in 'abcde':self.row(name)
        self.row('later','2026-10-15 12:00:00.123457');self.denied={'c'}
        scope={'list':'award.handoff','company':'A','person':'person','user':'author','authority':'current','query':'','count_mode':'exact'}
        cursor=encode_cursor(secret='fixed-key',scope=scope,last=['2026-10-15 12:00:00.123456','e'])
        result=self.page(cursor=cursor)
        self.assertEqual(result['items'],[{'id':'d'},{'id':'b'}]);self.assertEqual(result['total'],5)
        self.assertEqual(self.calls,Counter({name:1 for name in ['a','b','c','d','e','later']}));self.assertTrue(result['has_more'])
    def test_none_early_stop_and_exact_scope(self):
        for name in 'abcdef':self.row(name)
        self.row('foreign',company='B');self.row('wrong-project',project='real')
        self.denied={'e'}
        result=listing.listed(company='A',actor=self.actor,kind='handoff',reader=self.reader,limit=1)
        self.assertEqual(result['items'],[{'id':'f'}]);self.assertIsNone(result['total']);self.assertEqual(set(self.calls),{'f','e','d'})
    def test_integrity_off_page_and_overflow_never_return_partial(self):
        for name in 'abcde':self.row(name)
        self.corrupt={'a'}
        with self.assertRaises(DomainError) as e:self.page()
        self.assertEqual(e.exception.code,'award_integrity')
        self.corrupt.clear()
        with patch.object(listing,'MAX_SCAN',3),self.assertRaises(DomainError) as e:self.page()
        self.assertEqual(e.exception.code,'authorization_scan_limit')
    def test_cursor_other_actor_filter_or_count_mode_denies_before_any_reader(self):
        from cipher_aec.api.paging import encode_cursor
        cursor=encode_cursor(secret='fixed-key',scope={'different':'scope'},last=['date','name'])
        with self.assertRaises(DomainError):self.page(cursor=cursor)
        self.assertEqual(self.calls,Counter())


class AwardReadContractsTests(unittest.TestCase):
    def test_participant_aliases_refuse_before_command_locks_and_stored_plan_discovery(self):
        from cipher_aec.awards import team
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.execute('CREATE TABLE `tabCipher Person` (name TEXT COLLATE NOCASE PRIMARY KEY)')
        db.executemany('INSERT INTO `tabCipher Person` VALUES(?)',[('author',),('member',)])
        calls=[]
        def sql(query,args):
            calls.append(query);self.assertNotIn('FOR UPDATE',query)
            return db.execute(query.replace('%s','?'),args).fetchall()
        original={'delegator_person':'author','policy_id':'policy','policy_digest':'a'*64,'members':[{'person_id':'member','abilities':['project.read']}]}
        with patch.object(team,'frappe',SimpleNamespace(db=SimpleNamespace(sql=sql))),patch.object(service.contracts,'identifier'),patch.object(service,'_actor'), \
            patch.object(service.contracts,'definition',side_effect=deepcopy),patch.object(service,'run_company_command',return_value={'planned':'not executed'}) as run:
            self.assertEqual(team.participant_names(original),('author','member'))
            for change in ('delegator','member','both-spellings'):
                selected=deepcopy(original)
                if change=='delegator':selected['delegator_person']='AUTHOR'
                elif change=='member':selected['members'][0]['person_id']='MEMBER'
                else:selected['members'].append({'person_id':'MEMBER','abilities':['project.read']})
                with self.subTest(change=change),self.assertRaises(DomainError):service.plan_handoff('A','handoff','version',{'team':selected},'operation')
                run.assert_not_called()
            result=service.plan_handoff('A','handoff','version',{'team':original},'operation')
            self.assertEqual(result,{'planned':'not executed'});self.assertEqual(run.call_args.kwargs['participant_people'],('author','member'))
            malformed={'author_person':'author','definition':{'team':{**original,'delegator_person':'AUTHOR'}},'participants':['AUTHOR','member']}
            with patch.object(service.repository,'read',return_value=malformed),self.assertRaises(DomainError):service.participant_people('A','revision')
        self.assertTrue(calls)

    def test_company_outsider_has_same_denial_before_any_participant_discovery(self):
        from cipher_aec.awards import team
        with patch.object(service.contracts,'identifier'),patch.object(service.contracts,'definition',side_effect=deepcopy), \
            patch.object(service,'_actor',side_effect=DomainError('capability_denied','Current Company award authority is required',403)) as scope, \
            patch.object(team,'participant_names') as discovery,patch.object(service,'run_company_command') as command:
            errors=[]
            for name in ('existing','nonexistent','CASE-ALIAS'):
                with self.subTest(person=name),self.assertRaises(DomainError) as raised:
                    service.plan_handoff('A','handoff','version',{'team':{'delegator_person':name}},'operation')
                errors.append((raised.exception.code,raised.exception.message,raised.exception.status))
            self.assertEqual(len(set(errors)),1);discovery.assert_not_called();command.assert_not_called()
            self.assertEqual(scope.call_count,3);self.assertTrue(scope.call_args.kwargs['write'])

    def test_locked_team_eligibility_reasserts_exact_native_person_name(self):
        from cipher_aec.awards import team
        calls=[]
        def sql(query,args,**kw):
            calls.append(query);self.assertIn('FOR UPDATE',query)
            if 'tabCipher Person' in query:return [SimpleNamespace(name='member',display_name='Current member',active=1,identity_kind='Human')]
            return [SimpleNamespace(user='member-user')]
        actor=SimpleNamespace(user='member-user',person_id='member')
        with patch.object(team,'frappe',SimpleNamespace(db=SimpleNamespace(sql=sql))),patch.object(team,'current_actor',return_value=actor),patch.object(team,'require_company'):
            with self.assertRaises(DomainError):team.eligible_person('A','MEMBER',lock=True)
            self.assertEqual(len(calls),1,'Alias refuses before binding or authority traversal')
            self.assertEqual(team.eligible_person('A','member',lock=True),{'person_id':'member','display_name':'Current member'})

    def test_schema_closed_refs_and_authoritative_dependency_copies(self):
        from jsonschema import Draft202012Validator
        root=Path(service.__file__).resolve().parents[1];schema=json.loads((root/'awards/schemas/api-v1.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        def walk(value):
            if isinstance(value,dict):
                if '$ref' in value:self.assertIn(value['$ref'].removeprefix('#/$defs/'),schema['$defs'])
                for item in value.values():walk(item)
            elif isinstance(value,list):
                for item in value:walk(item)
        walk(schema)
        for filename in ('commercial/schemas/api-v1.schema.json','estimating/schemas/api-company-v2.schema.json','construction_finance/schemas/api-v1.schema.json','project_controls/schemas/api-v1.schema.json'):
            for name,value in json.loads((root/filename).read_text())['$defs'].items():
                if name in schema['$defs']:self.assertEqual(schema['$defs'][name],value,name)
        self.assertFalse(service.availability()['action_available'])
    def test_wbs_accountability_excludes_delegator_outside_team(self):
        issue,lines,order=fixtures();issue['pricing']['total']='30.00'
        actor=SimpleNamespace(user='author',person_id='delegator')
        definition={'issue_id':issue['id'],'native_order_definition':order,'line_mappings':[{'proposal_line_id':lines[0]['proposal_line_id'],'item_code':lines[0]['item_code'],'delivery_date':lines[0]['delivery_date']}],
            'contract_definition':{'kind':'prime','direction':'receivable','party_type':'Customer','party':order['customer'],'currency':'USD','original_value':{'amount':'30.00','currency':'USD'}},
            'team':{'delegator_person':'delegator','members':[{'person_id':'member','abilities':['project.read']}]},'wbs_nodes':[{'accountable_person':'delegator'}]}
        facts={'pursuit':'pursuit','opportunity':'opportunity','issue_digest':'x','controls_plan':{'currency_exponent':2}}
        with patch.object(service.contracts,'definition',side_effect=deepcopy),patch.object(service.sources,'issue_record',return_value=issue), \
            patch.object(service.sources,'admitted',return_value=nullcontext({'native_refs':[]})),patch.object(service.sources,'facts',return_value=facts), \
            patch.object(service.team,'authorize',return_value={}),patch('cipher_aec.construction_finance.core.definition'):
            with self.assertRaises(DomainError) as error:service._build('A',{'pursuit':'pursuit','opportunity':'opportunity'},definition,actor)
            self.assertEqual(error.exception.code,'invalid_award_team')
            definition['wbs_nodes'][0]['accountable_person']='member'
            value=service._build('A',{'pursuit':'pursuit','opportunity':'opportunity'},definition,actor)
            self.assertEqual(value['participants'],['delegator','member'])
            self.assertTrue(all(str(UUID(v))==v for v in value['ids']['line_ids'].values()))
    def test_requester_without_project_access_gets_truthful_company_readback(self):
        parent={'id':'handoff','company':'A','adoption':'adopted'}
        with patch.object(service.repository,'read',return_value={'target_project':'PROJ-actual'}),patch.object(service,'require_project',side_effect=DomainError('capability_denied','Unavailable',403)):
            value=service._public_handoff(parent,object())
        self.assertEqual(value['project_access'],{'standing':'not_available','project_id':'PROJ-actual'})
        self.assertFalse(value['availability']['action_available'])
    def test_source_preview_denial_is_not_converted_to_empty_or_unqualified_success(self):
        actor=object()
        with patch.object(service,'_actor',return_value=actor),patch.object(service,'require_company',side_effect=DomainError('capability_denied','Source denied',403)),patch.object(service.contracts,'identifier') as identity:
            with self.assertRaises(DomainError):service.source_preview('A','issue')
            identity.assert_not_called()


    def test_baseline_input_gate_distinguishes_ordinary_issue_output_from_generated_inputs(self):
        from cipher_aec.awards import sources
        from cipher_aec.estimating import sources as estimates
        baseline={'manifest':{'effect':{'facts':{}}}}
        # Every normal Issue is generated output; no award resource-plan flag
        # or output PDF is an estimate-input admission decision.
        with patch.object(estimates,'GENERATED_INPUTS_QUALIFIED',False):
            self.assertTrue(sources.require_qualified_inputs(baseline)['eligible'])
            baseline['manifest']['effect']['facts']['generated_sources']=[{'document_id':'original-generated-input','input_digest':'a'*64}]
            self.assertFalse(sources.input_qualification(baseline)['eligible'])
            with self.assertRaises(DomainError) as error:sources.require_qualified_inputs(baseline)
            self.assertEqual(error.exception.code,'award_estimate_inputs_unqualified')
        baseline['manifest']['effect']['facts']['generated_sources']='invalid'
        with self.assertRaises(DomainError) as error:sources.input_qualification(baseline)
        self.assertEqual(error.exception.code,'award_integrity')

    def test_original_plan_receipt_ignores_later_private_head_but_rechecks_original_sources(self):
        original={'id':'old-plan','handoff':'handoff','issue':'old-issue'}
        snapshot={'id':'handoff','company':'A','pursuit':'p','opportunity':'O','current_revision':'old-plan','revision_number':1,'issue':'old-issue','status':'draft','adoption':None}
        later={**snapshot,'current_revision':'new-private-plan','revision_number':2,'issue':'new-private-issue'}
        def authorize(company,revision,*args,**kw):
            if revision!='old-plan':raise DomainError('not_found','Later source private',404)
            return original
        with patch.object(service,'_actor'),patch.object(service.repository,'read',return_value=later),patch.object(service,'authorize_plan',side_effect=authorize) as auth,patch.object(service,'get_handoff',side_effect=AssertionError('Receipt cannot follow current head')):
            service.authorize_receipt(object(),'A',{'plan':original,'handoff':snapshot},lock=True)
            self.assertEqual(auth.call_args.args[1],'old-plan')
            auth.side_effect=DomainError('capability_denied','Original source revoked',403)
            with self.assertRaises(DomainError):service.authorize_receipt(object(),'A',{'plan':original,'handoff':snapshot},lock=True)

    def test_original_creation_receipt_keeps_original_issue_when_current_plan_is_private(self):
        snapshot={'id':'handoff','company':'A','pursuit':'p','opportunity':'O','current_revision':None,'revision_number':0,'issue':'original','status':'draft','adoption':None}
        current={**snapshot,'current_revision':'later','revision_number':1,'issue':'private-later'}
        with patch.object(service,'_actor'),patch.object(service.repository,'read',return_value=current), \
            patch('cipher_aec.commercial.outputs.issue_source_reference',return_value={'issue':{'proposal':'proposal'}}) as issue, \
            patch('cipher_aec.commercial.service._read',return_value=(object(),{'pursuit':'p'})),patch.object(service,'get_handoff',side_effect=AssertionError('No current head lookup')):
            service.authorize_receipt(object(),'A',{'handoff':snapshot},lock=True)
            self.assertEqual(issue.call_args.args[1],'original')
            issue.side_effect=DomainError('not_found','Original now private',404)
            with self.assertRaises(DomainError):service.authorize_receipt(object(),'A',{'handoff':snapshot},lock=True)
