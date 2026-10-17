"""Actual command/savepoint/receipt/application controller with local SQL storage."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import sys
from types import SimpleNamespace,ModuleType
import unittest
from uuid import uuid4
from unittest.mock import patch
from jsonschema import Draft202012Validator
from cipher_aec.api.contracts import canonical_json,digest
from cipher_aec.api.errors import DomainError
from cipher_aec.ricky import company_draft_save as saves
from cipher_aec.ricky.company_draft_save_contracts import COMMANDS
from cipher_aec.ricky.company_backend import validate_manifest as read_manifest,validate_resource_plan as read_plan
from cipher_aec.tests.test_estimating_core import identity
from cipher_aec.tests import test_ricky_company_history as history
from cipher_aec.tests.test_ricky_company_draft_saves import ready_scope

ROOT=Path(__file__).parents[1]

class DraftSaveCommands(unittest.TestCase):
    def setUp(self):
        self.f,self.ctx=ready_scope(self)
        self.h=h=history.CompanyCommandHistoryTests();h.setUp();self.addCleanup(h.doCleanups)
        h.actor=self.f.boundary.actor;h.company=self.ctx.company
        self.original_actor=deepcopy(h.actor)
        self.stack=h.stack
        self.stack.enter_context(patch.dict(sys.modules,{'frappe':h.fake}))
        sys.modules['cipher_aec.governance.context'].require_trusted_write=h.require_trusted
        sys.modules['cipher_aec.governance.context'].require_company=h.require_company
        import importlib
        native_history=importlib.import_module('cipher_aec.governance.history')
        self.stack.enter_context(patch.object(native_history,'append_company_event',h.append))
        from cipher_aec.ricky import company_proposal_service
        self.stack.enter_context(patch.object(company_proposal_service,'build_service',return_value=self.f.service))
        # Existing fixture cached module is intentionally a closed read stub.
        from cipher_aec.ricky.company_proposal_backend import CompanyProposalBackend
        sys.modules['cipher_aec.ricky.company_backend'].validate_manifest=read_manifest
        sys.modules['cipher_aec.ricky.company_backend'].validate_resource_plan=read_plan
        h.db.executescript('''CREATE TABLE saved_revisions(name TEXT PRIMARY KEY,body TEXT);
          CREATE TABLE heads(name TEXT PRIMARY KEY,revision TEXT);
          CREATE TABLE `tabCipher Ricky Draft Save`(name TEXT PRIMARY KEY,company TEXT,scope_type TEXT,project TEXT,requested_by TEXT,person TEXT,
            source_proposal TEXT UNIQUE,run TEXT,step TEXT,invocation TEXT,receipt TEXT UNIQUE,saved_doctype TEXT,saved_revision TEXT,data_json TEXT,record_digest TEXT);''')
        h.db.execute('INSERT INTO heads VALUES (?,?)',(self.ctx.payload['proposal_id'],self.ctx.run['request']['arguments']['proposal_revision_id']))
        sql=h.sql
        def observer(query,params=(),as_dict=False):
            if 'tabSessions' in query:h.order.append('Session');return []
            return sql(query,params,as_dict)
        h.fake.db.sql=observer
        get_doc=h.doc
        def document(value):
            if value['doctype']!=saves.DOCTYPE:return get_doc(value)
            owner=self
            class Application(SimpleNamespace):
                def get(self,key):return getattr(self,key,None)
                def is_new(self):return True
                def insert(self,**kwargs):
                    # Native Link existence is checked before the controller.
                    assert h.db.execute('SELECT 1 FROM `tabCipher Command Receipt` WHERE name=?',(self.receipt,)).fetchone()
                    assert h.db.execute('SELECT 1 FROM saved_revisions WHERE name=?',(self.saved_revision,)).fetchone()
                    assert owner.f.store.get('proposal',self.source_proposal)
                    for kind,key in [('run',self.run),('step',self.step),('invocation',self.invocation)]:assert owner.f.store.get(kind,key)
                    saves.validate_document(self)
                    return get_doc(value).insert(**kwargs)
            return Application(**value)
        h.fake.get_doc=document
        self.stack.enter_context(patch.object(saves,'_saved_revision',side_effect=self.saved_revision))
        # These command atomicity tests use a local canonical writer. Actual
        # original/saved graph admission is instrumented in ReplayUnionTests.
        empty={'unit_ids':[],'currencies':[],'native_refs':[],'generated_sources':[]}
        self.stack.enter_context(patch.object(saves,'_closure_plan',return_value=empty))
        original_scope=self.f.boundary.source_scope
        @contextmanager
        def source_scope(*args,_extra_plan=None,**kwargs):
            with original_scope(*args,**kwargs) as plan: yield plan
        self.stack.enter_context(patch.object(self.f.boundary,'source_scope',side_effect=source_scope))
        service=ModuleType('cipher_aec.commercial.service')
        service.authorize_receipt=lambda actor,company,result,**kwargs:self.saved_revision(result['application'] if 'application' in result else self.ctx._reserved['application'],actor)
        self.stack.enter_context(patch.dict(sys.modules,{'cipher_aec.commercial.service':service}))
        def authority(actor):
            if actor!=self.original_actor:raise DomainError('not_found','Original User and Person required.',404)
            if not self.f.boundary.session:raise DomainError('session_revoked','Original session ended.',403)
            if not self.write:raise DomainError('capability_denied','Current writer required.',403)
            if self.f.now>=__import__('cipher_aec.ricky.contracts',fromlist=['parse_time']).parse_time(self.ctx.proposal['expires_at']):raise DomainError('draft_save_expired','Expired.')
        self.write=True
        self.stack.enter_context(patch.object(self.ctx,'authority',side_effect=authority))
        @contextmanager
        def admitted(actor):
            authority(actor)
            if saves._application(self.ctx.proposal_id,lock=True) is not None:raise DomainError('draft_already_saved','Already saved.')
            self.ctx._terminal_bytes=canonical_json(self.ctx.run)
            yield
        self.stack.enter_context(patch.object(self.ctx,'new_effect',side_effect=admitted))
        runner=h.start.__globals__['run_company_command']
        cells=dict(zip(runner.__code__.co_freevars,(cell.cell_contents for cell in runner.__closure__)))
        command=cells['command'];command.__globals__['COMPANY_RICKY_COMMANDS']|={row[0] for row in COMMANDS.values()}
        command.__globals__['authorize_receipt']=lambda actor,command,company,project,result,**kwargs:saves.authorize_receipt(actor,company,result,command=command,lock=True)
        self.runner=runner
        self.operation=str(uuid4());self.effects=0

    def saved_revision(self,core,actor,**kwargs):
        if not self.f.boundary.fixture.source_allowed:raise DomainError('not_found','Exact source revoked.',404)
        row=self.h.db.execute('SELECT body FROM saved_revisions WHERE name=?',(core['saved_revision_id'],)).fetchone()
        if not row:raise DomainError('not_found','Saved revision missing.',404)
        value=json.loads(row[0])
        if digest(value)!=core['saved_revision_digest']:raise DomainError('draft_save_integrity','Saved revision changed.')
        return value

    def effect(self,actor,company):
        self.h.require_trusted();self.effects+=1
        revision={'id':identity('saved-r15-'+str(self.effects)),'company':self.ctx.company,'proposal':self.ctx.payload['proposal_id'],
            'predecessor':self.ctx.run['request']['arguments']['proposal_revision_id'],'composition':deepcopy(self.ctx.payload['composition'])}
        self.h.db.execute('INSERT INTO saved_revisions VALUES (?,?)',(revision['id'],canonical_json(revision)))
        self.h.db.execute('UPDATE heads SET revision=? WHERE name=?',(revision['id'],revision['proposal']))
        self.h.append(actor=actor,company=self.ctx.company,event='commercial.proposal.revision.created',subject_type='Cipher Proposal Revision',
            subject_id=revision['id'],operation_id=self.operation,details={'record_id':revision['id']})
        return {'proposal':{'id':revision['proposal'],'current_revision':revision['id']},'revision':revision}

    def save(self,operation=None):
        return self.runner(company=self.ctx.company,operation_id=operation or self.operation,command=self.ctx.spec[1],payload=self.ctx.payload,
            ability='commercial.write',effect=self.effect,draft_save=self.ctx)

    def test_real_receipt_then_native_application_links_and_history_are_atomic(self):
        old=canonical_json(list(self.f.store.rows.items()))
        result=self.save();self.h.commit()
        order=self.h.order
        self.assertLess(order.index('Session'),order.index('Cipher Command Receipt'))
        self.assertLess(order.index('Cipher Command Receipt'),order.index(saves.DOCTYPE))
        self.assertEqual([e['event'] for e in self.h.history()],['commercial.proposal.revision.created','ricky.company.proposal.draft-saved'])
        self.assertEqual(self.h.history()[1]['previous_hash'],self.h.history()[0]['event_hash'])
        self.assertEqual(result['application']['classification'],'unverified-author-suggestion')
        self.assertEqual(canonical_json(list(self.f.store.rows.items())),old)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM `tabCipher Ricky Draft Save`').fetchone()[0],1)

    def test_replay_after_expiry_write_loss_session_end_and_successor_changes_nothing(self):
        result=self.save();self.h.commit();before=[tuple(x) for x in self.h.db.execute('SELECT * FROM `tabCipher Command Receipt`')]
        self.f.now+=timedelta(seconds=301);self.write=False;self.f.boundary.session=False
        self.f.boundary.fixture.proposal_value['current_revision']=identity('later-head')
        replay=self.save();self.h.commit()
        self.assertTrue(replay['operation']['replayed']);self.assertEqual(replay['application'],result['application'])
        self.assertEqual(self.effects,1);self.assertEqual(len(self.h.history()),2)
        self.assertEqual([tuple(x) for x in self.h.db.execute('SELECT * FROM `tabCipher Command Receipt`')],before)
        self.f.boundary.fixture.source_allowed=False
        with self.assertRaises(Exception):self.save()

    def test_a_second_operation_cannot_reapply_one_suggestion(self):
        self.save();self.h.commit()
        with self.assertRaises(DomainError):self.save(str(uuid4()))
        self.assertEqual(self.effects,1)

    def test_native_application_header_tampering_refuses_retained_receipt(self):
        self.save();self.h.commit()
        for field in ('company','requested_by','person','source_proposal','run','step','invocation','receipt','saved_doctype','saved_revision'):
            with self.subTest(field=field):
                original=self.h.db.execute('SELECT '+field+' FROM `tabCipher Ricky Draft Save`').fetchone()[0]
                self.h.db.execute('UPDATE `tabCipher Ricky Draft Save` SET '+field+'=?',('foreign-header',));self.h.commit()
                with self.assertRaises(DomainError):self.save()
                self.h.db.execute('UPDATE `tabCipher Ricky Draft Save` SET '+field+'=?',(original,));self.h.commit()
        self.assertEqual(self.effects,1)

    def test_receipt_application_and_history_insert_failure_roll_back_domain_and_head(self):
        for table in ['Cipher Command Receipt',saves.DOCTYPE,'Cipher History Event']:
            with self.subTest(table=table):
                self.h.fail_insert=table
                with self.assertRaises(RuntimeError):self.save()
                self.assertEqual(self.h.db.execute('SELECT count(*) FROM saved_revisions').fetchone()[0],0)
                self.assertEqual(self.h.db.execute('SELECT count(*) FROM `tabCipher Command Receipt`').fetchone()[0],0)
                self.assertEqual(self.h.db.execute('SELECT count(*) FROM `tabCipher Ricky Draft Save`').fetchone()[0],0)
                self.assertEqual(len(self.h.history()),0)
                self.assertEqual(self.h.db.execute('SELECT revision FROM heads').fetchone()[0],self.ctx.run['request']['arguments']['proposal_revision_id'])

    def test_deadline_crossing_after_domain_effect_rolls_back_all(self):
        effect=self.effect
        def expired(actor,company):
            result=effect(actor,company);self.f.now+=timedelta(seconds=301);return result
        self.effect=expired
        with self.assertRaises(DomainError):self.save()
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM saved_revisions').fetchone()[0],0)
        self.assertEqual(len(self.h.history()),0)

    def test_ordinary_manual_command_payload_and_result_are_unchanged(self):
        effect=lambda actor,company:{'original':'manual'}
        result=self.runner(company=self.ctx.company,operation_id=self.operation,command='commercial.original',payload={'exact':'payload'},ability='commercial.write',effect=effect)
        self.assertEqual(result,{'original':'manual','operation':{'id':self.operation,'status':'succeeded','replayed':False}})
        row=self.h.db.execute('SELECT command,result_json FROM `tabCipher Command Receipt`').fetchone()
        self.assertEqual(tuple(row),('commercial.original','{"original":"manual"}'))
        self.assertNotIn('Session',self.h.order)

    def test_rehashed_application_core_and_receipt_cannot_change_original_target(self):
        self.save();self.h.commit()
        row=self.h.db.execute('SELECT data_json FROM `tabCipher Ricky Draft Save`').fetchone()
        record=json.loads(row[0]);record['core']['target_id']=identity('foreign-target')
        record['core']['core_digest']=digest({k:v for k,v in record['core'].items() if k!='core_digest'})
        receipt=json.loads(self.h.db.execute('SELECT result_json FROM `tabCipher Command Receipt`').fetchone()[0])
        receipt['application']=record['core'];record['receipt_result_hash']=digest(receipt)
        self.h.db.execute('UPDATE `tabCipher Command Receipt` SET result_json=?,result_hash=?',(canonical_json(receipt),digest(receipt)))
        self.h.db.execute('UPDATE `tabCipher Ricky Draft Save` SET data_json=?,record_digest=?',(canonical_json(record),digest(record)))
        with self.assertRaises(DomainError):self.save()

    def test_application_event_failure_rolls_back_already_inserted_application(self):
        import importlib
        canonical_history=importlib.import_module('cipher_aec.governance.history')
        append=self.h.append
        def fail_tail(**kwargs):
            result=append(**kwargs)
            if kwargs['event']=='ricky.company.proposal.draft-saved':raise RuntimeError('Explicit failure after application history insert')
            return result
        self.stack.enter_context(patch.object(canonical_history,'append_company_event',side_effect=fail_tail))
        with self.assertRaises(RuntimeError):self.save()
        for table in ('saved_revisions','tabCipher Command Receipt','tabCipher Ricky Draft Save','tabCipher History Event'):
            self.assertEqual(self.h.db.execute('SELECT count(*) FROM `'+table+'`').fetchone()[0],0)


class WireContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.openapi=json.loads((ROOT/'api/openapi.json').read_text())
        cls.defs=cls.openapi['components']['schemas']

    def validator(self,name):return Draft202012Validator({'components':{'schemas':self.defs},'$ref':'#/components/schemas/'+name})

    def company_saved(self):
        from cipher_aec.tests.test_estimating_company import company_fixture
        from cipher_aec.estimating.calculation import calculate
        inputs=company_fixture()
        inputs['basis_citations']=[deepcopy(next(iter(inputs['rates'].values()))['source_citations'][0])]
        result=calculate(inputs)
        common={'company':'Explicit EST fixture','scope_type':'Company','project':None,'author_person':'canonical-person',
            'author_user':'author@example.test','created_at':'2026-10-16T00:00:00+00:00'}
        estimate={**common,'id':identity('target'),'status':'authored','title':'Explicit target','currency':'USD','pricing_date':inputs['pricing_date'],
            'revision_number':2,'current_revision':identity('saved'),'pursuit_id':identity('pursuit')}
        revision={**common,'id':identity('saved'),'status':'draft-calculated','estimate':estimate['id'],'revision_number':2,'predecessor':identity('base'),
            'calculation_snapshot':identity('snapshot'),'currency':'USD','pricing_date':inputs['pricing_date'],'policy_version':inputs['policy_version'],
            'line_record_ids':[identity('line')],'source_citations':[],'basis_description':inputs['basis_description'],**{k:result[k] for k in ('direct','indirect','contingency','total')}}
        snapshot={**common,'id':identity('snapshot'),'status':'calculated','subject_type':'Cipher Estimate Revision','subject_id':revision['id'],
            'estimate':estimate['id'],'inputs':inputs,'result':result,'currency_policy':{'currency':'USD','currency_exponent':2,'fraction_units':100,'native_currency_version':'2026-10-15 00:00:00'},
            'input_digest':result['input_digest'],'output_digest':result['output_digest'],'source_citations':[]}
        return {'estimate':estimate,'revision':revision,'calculation':snapshot,'history_id':'ordinary-history'}

    def test_actual_company_calculation_result_matches_company_schema_and_project_refuses(self):
        value=self.company_saved();validator=self.validator('CompanyDraftSaveCanonicalResult');validator.validate(value)
        for key in ('estimate','revision','calculation'):
            bad=deepcopy(value);bad[key].pop('scope_type');bad[key]['project']='Unrelated Project'
            self.assertTrue(list(validator.iter_errors(bad)),key)
        # The original wrong Project references reject this valid Company value.
        legacy=deepcopy(self.defs['CompanyDraftSaveCanonicalResult'])
        for branch in legacy['oneOf']:
            for field in branch.get('properties',{}).values():
                if '$ref' in field:field['$ref']=field['$ref'].replace('/CompanyEst','/Est')
        self.assertTrue(list(Draft202012Validator({'components':{'schemas':self.defs},**legacy}).iter_errors(value)))

    def test_closed_request_has_only_review_bindings_and_no_callback_or_quantity(self):
        value={'company':'Explicit EST fixture','proposal_id':identity('suggestion'),'expected_version':1,'expected_content_digest':'a'*64,
            'mapping_version':'1','expected_payload_digest':'b'*64,'operation_id':'00000000-0000-4000-8000-000000000001'}
        validator=self.validator('CompanyDraftSaveRequest');validator.validate(value)
        for field in ('callback','composition','lines','authority','session_reference','project'):
            self.assertTrue(list(validator.iter_errors({**value,field:{}})))
        self.assertTrue(list(validator.iter_errors({**value,'mapping_version':'2'})))

    def test_actual_rpc_adapter_passes_only_literal_review_bindings(self):
        calls=[];returned={'exact':'service-result'}
        module=SimpleNamespace(save_draft=lambda *args:calls.append(args) or returned)
        namespace={'endpoint':lambda **kwargs:lambda fn:fn,'domain_errors':lambda fn:fn,'service':module,'_closed_request':lambda fields:None}
        function=history.function('ricky/company_draft_save_api.py','save_draft',namespace)
        result=function('C',identity('s'),1,'a'*64,'1','b'*64,'00000000-0000-4000-8000-000000000001')
        self.assertIs(result,returned)
        self.assertEqual(set(calls[0][1]),{'proposal_id','expected_version','expected_content_digest','mapping_version','expected_payload_digest'})

    def test_raw_frappe_filtered_unknown_arguments_still_refuse(self):
        function=history.function('ricky/company_draft_save_api.py','_closed_request',{})
        fake=SimpleNamespace(local=SimpleNamespace(request=object()),form_dict={'company':'C','proposal_id':identity('s'),'callback':'ignored-by-frappe'})
        with patch.dict(sys.modules,{'frappe':fake}):
            with self.assertRaises(DomainError):function({'company','proposal_id'})
            fake.form_dict.pop('callback');function({'company','proposal_id'})

    def company_subject_and_response(self):
        saved=self.company_saved();inputs=saved['calculation']['inputs']
        payload={'estimate_id':saved['estimate']['id'],'expected_revision':saved['revision']['predecessor'],'lines':deepcopy(inputs['lines']),
            'adjustments':deepcopy(inputs['adjustments']),'conversion_ids':[row['id'] for row in inputs['unit_manifest']['unit_conversions']],
            'basis_description':inputs['basis_description'],'basis_citations':[{k:row[k] for k in ('revision_id','page','excerpt_sha256','source_sha256')} for row in inputs['basis_citations']]}
        operation='00000000-0000-4000-8000-000000000001';person='canonical-person'
        core={'schema':'cipher.ricky.company.draft-save.v1','id':saves.application_id(identity('suggestion')),'scope_type':'Company','project':None,
            'company':'Explicit EST fixture','user':'author@example.test','person':person,'proposal_id':identity('suggestion'),'proposal_version':1,
            'proposal_digest':'a'*64,'run_id':identity('run'),'step_id':identity('step'),'invocation_id':identity('invocation'),
            'preparation_digest':'b'*64,'manifest_digest':'c'*64,'action':'aec.estimate.draft','classification':'unverified-author-suggestion','mapping_version':'1',
            'payload_digest':digest(payload),'command':'ricky.company.proposal.save-estimate.v1','canonical_command':'estimate.calculate.v1',
            'target_doctype':'Cipher Estimate','target_id':payload['estimate_id'],'base_revision_id':payload['expected_revision'],
            'saved_doctype':'Cipher Estimate Revision','saved_revision_id':saved['revision']['id'],'saved_revision_digest':digest(saved['revision']),
            'operation_id':operation,'receipt_id':digest({'person':person,'operation_id':operation}),'created_at':'2026-10-16T00:00:00+00:00'}
        core['core_digest']=digest(core)
        response={'application':core,'saved':saved,'operation':{'id':operation,'status':'succeeded','replayed':False}}
        subject={'proposal_id':core['proposal_id'],'proposal_version':1,'proposal_digest':core['proposal_digest'],'action':core['action'],'mapping_version':'1',
            'payload':payload,'payload_digest':digest(payload),'expires_at':'2026-10-16T00:05:00+00:00','eligible':False,
            'reason':{'code':'draft_already_saved','message':'This suggestion already has a saved canonical draft.'},'application':core,'saved':saved}
        return subject,response

    def test_full_company_subject_and_wire_response_keep_nonempty_original_citations_and_units(self):
        subject,response=self.company_subject_and_response()
        self.assertTrue(subject['payload']['basis_citations']);self.assertTrue(response['saved']['calculation']['inputs']['rates'])
        self.assertTrue(response['saved']['calculation']['inputs']['unit_manifest']['records'])
        self.validator('CompanyDraftSaveSubject').validate(subject)
        self.validator('CompanyDraftSaveResponse').validate(response)
        body={'message':{'schema':'cipher.api.v1','request_id':identity('request'),'meta':{'request_id':identity('request'),'api_version':'v1','server_time':'2026-10-16T00:00:00Z'},'data':response}}
        schema=self.openapi['paths']['/api/method/cipher_aec.ricky.company_draft_save_api.save_draft']['post']['responses']['200']['content']['application/json']['schema']
        Draft202012Validator({**schema,'components':self.openapi['components']}).validate(body)
        bad=deepcopy(subject);bad['payload']['basis_citations']=response['saved']['calculation']['inputs']['basis_citations']
        self.assertTrue(list(self.validator('CompanyDraftSaveSubject').iter_errors(bad)))
