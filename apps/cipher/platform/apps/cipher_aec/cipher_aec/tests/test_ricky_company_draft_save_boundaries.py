"""Real authority and complete-union admission; no native execution."""
from contextlib import ExitStack,contextmanager
from copy import deepcopy
from datetime import timedelta
from types import ModuleType,SimpleNamespace
import sys
import unittest
from unittest.mock import patch
from cipher_aec.api.errors import DomainError
from cipher_aec.ricky.contracts import RickyError
from cipher_aec.tests.test_estimating_core import identity
from cipher_aec.tests.test_ricky_company_draft_saves import ready_scope
from cipher_aec.tests import test_ricky_company_proposal_boundaries as proposal_tests

class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.f,self.ctx=ready_scope(self)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.events=[];self.alive=True;self.version='b'*64
        self.abilities={'ricky.run','commercial.read','commercial.write'}
        self.frappe=SimpleNamespace(session=SimpleNamespace(user=self.f.boundary.actor.user,sid='fixture-original-sid'),
            db=SimpleNamespace(sql=lambda *args,**kwargs:self.events.append('Session')))
        module=ModuleType('cipher_aec.governance.context')
        def require(company,ability,**kwargs):
            self.events.append('Company')
            if ability not in self.abilities:raise DomainError('capability_denied','Current duty required.',403)
        def session(*args,**kwargs):
            self.events.append(('SessionCheck',kwargs.get('lock')))
            if not self.alive:raise DomainError('session_revoked','Original session ended.',403)
        module.require_company=require;module.require_session_authority=session
        module.company_authority_fingerprint=lambda *args,**kwargs:self.version
        self.stack.enter_context(patch.dict(sys.modules,{'frappe':self.frappe,'cipher_aec.governance.context':module}))

    def test_original_session_precedes_company_and_terminal_needs_no_live_worker(self):
        self.ctx.prelock(self.f.boundary.actor)
        self.ctx.run['lease_expires_at']='2026-10-15T00:00:00+00:00'
        self.ctx.authority(self.f.boundary.actor)
        self.assertLess(self.events.index('Session'),self.events.index('Company'))
        self.assertIn(('SessionCheck',False),self.events)
        self.assertEqual(self.ctx.run['status'],'waiting-for-review')

    def test_sid_original_liveness_authority_current_writer_and_deadline_each_refuse(self):
        self.ctx.prelock(self.f.boundary.actor)
        for change,restore in [
            (lambda:setattr(self.frappe.session,'sid','new-login'),lambda:setattr(self.frappe.session,'sid','fixture-original-sid')),
            (lambda:setattr(self,'alive',False),lambda:setattr(self,'alive',True)),
            (lambda:setattr(self,'version','c'*64),lambda:setattr(self,'version','b'*64)),
            (lambda:self.abilities.remove('commercial.write'),lambda:self.abilities.add('commercial.write')),
            (lambda:self.ctx.run.update(cancel_requested=True),lambda:self.ctx.run.update(cancel_requested=False))]:
            change()
            with self.assertRaises(DomainError):self.ctx.authority(self.f.boundary.actor)
            restore()
        self.f.now+=timedelta(seconds=300)
        with self.assertRaises(DomainError):self.ctx.authority(self.f.boundary.actor)

    def test_unprelocked_and_alias_identity_cannot_admit(self):
        with self.assertRaises(DomainError):self.ctx.authority(self.f.boundary.actor)
        for actor in [SimpleNamespace(user='alias@example.test',person_id=self.f.boundary.actor.person_id),
                SimpleNamespace(user=self.f.boundary.actor.user,person_id='outsider')]:
            with self.assertRaises(DomainError):self.ctx.prelock(actor)


class UnionTests(unittest.TestCase):
    def setUp(self):
        self.original=proposal_tests.ProposalDiscoveryTests();self.original.setUp();self.addCleanup(self.original.doCleanups)

    def test_original_and_writer_union_is_sorted_before_any_currency_or_native_lock(self):
        f=self.original
        extra={'unit_ids':[identity('write-only-unit')],'currencies':['EUR'],'native_refs':[],'generated_sources':[]}
        with f.boundary.source_scope(f.authority,f.request,lock=True,expected_plan=f.plan,_extra_plan=extra) as plan:
            self.assertEqual(plan['unit_ids'],sorted(set(f.plan['unit_ids']+extra['unit_ids'])))
        locks=[row for row in f.events if type(row) is tuple]
        self.assertEqual(locks[:len(plan['unit_ids'])],[('UOM',name) for name in plan['unit_ids']])
        self.assertEqual(locks[len(plan['unit_ids']):len(plan['unit_ids'])+2],[('Currency','EUR'),('Currency','USD')])

    def test_writer_union_cannot_hide_original_plan_growth_or_admit_generated_input(self):
        f=self.original
        empty={'unit_ids':[],'currencies':[],'native_refs':[],'generated_sources':[]}
        with self.assertRaises(RickyError):
            with f.boundary.source_scope(f.authority,f.request,lock=True,expected_plan=empty,_extra_plan=f.plan):pass
        self.assertFalse(any(type(row) is tuple for row in f.events))
        generated={**empty,'generated_sources':[{'document_id':'generated','input_digest':'a'*64}]}
        with self.assertRaises(RickyError):
            with f.boundary.source_scope(f.authority,f.request,lock=True,_extra_plan=generated):pass

    def test_preexisting_foreign_admission_still_fails(self):
        f=self.original;f.modules['cipher_aec.documents.provenance'].has_prelocked=lambda:True
        with self.assertRaises(RickyError):
            with f.boundary.source_scope(f.authority,f.request,lock=True,_extra_plan=f.plan):pass

class RecoveredPreparationTests(unittest.TestCase):
    def test_original_successful_invocation_with_older_token_remains_saveable(self):
        from cipher_aec.ricky.company_proposal_records import successful_invocation
        f,ctx=ready_scope(self,recover=True)
        invocation=successful_invocation(f.store,ctx.run)
        step=f.store.get('step',invocation['step_id'])
        self.assertLess(step['lease_token'],ctx.run['lease_token'])
        self.assertEqual(ctx.run['status'],'waiting-for-review')
        self.assertEqual(ctx.payload['proposal_id'],f.boundary.fixture.proposal_value['id'])


class ReplayUnionTests(unittest.TestCase):
    """Actual replay orchestration and admission, instrumented canonical reads."""
    def exercise(self, action):
        from cipher_aec.ricky import company_draft_save as saves
        from cipher_aec.ricky.company_draft_save_contracts import derive,binding,COMMANDS
        from cipher_aec.ricky.company_contracts import decode_run_authority
        from cipher_aec.ricky.company_proposal_backend import CompanyProposalBackend
        from cipher_aec.ricky.contracts import digest,canonical
        from cipher_aec.tests import test_ricky_company_proposals as fixtures
        from cipher_aec.estimating import lockplan
        f,context=ready_scope(self)
        if action=='aec.estimate.draft':
            started,_=f.start(fixtures.estimate_request(f.boundary));f.service.process(started['id'])
            run=f.store.get('run',started['id']);proposal=f.store.get('proposal',run['proposal_ids'][0])
        else: run,proposal=context.run,context.proposal
        before=canonical(run)
        # The canonical conversion record is deliberately absent from Stage B's
        # immutable record list; only its snapshot definition pins this ID.
        for kind,name in list(f.boundary.fixture.records):
            value=f.boundary.fixture.records[kind,name]
            if kind=='estimate': value['currency']='USD'
        snapshot=f.boundary.fixture.records['snapshot',f.boundary.fixture.snapshot_id]
        for definition in snapshot['inputs']['unit_manifest']['unit_conversions']:
            f.boundary.fixture.records['conversion',definition['id']]={'id':definition['id'],'scope_type':'Company',
                'project':None,'company':run['company'],'definition':deepcopy(definition),
                'source_citations':[{'revision_id':'conversion-source'}]}
        graph=proposal_tests.ProposalDiscoveryTests();graph.setUp();self.addCleanup(graph.doCleanups)
        graph.boundary.fixture=f.boundary.fixture
        stack=graph.stack
        f.boundary.source_scope=CompanyProposalBackend.source_scope.__get__(f.boundary)
        source_only={'unit_ids':[identity('conversion-source-only')],'currencies':['EUR'],
            'native_refs':[{'doctype':'Supplier','name':'Conversion Source Supplier'}],'generated_sources':[]}
        saved_plan={'unit_ids':[identity('saved-source-only')],'currencies':['GBP'],
            'native_refs':[{'doctype':'Item','name':'Saved Original Item'}],'generated_sources':[]}
        empty={'unit_ids':[],'currencies':[],'native_refs':[],'generated_sources':[]}
        def source_plan(company,name,*args,**kwargs):
            graph.events.append(('discover',name))
            return deepcopy(source_only if name=='conversion-source' else empty)
        graph.modules['cipher_aec.documents.provenance'].source_plan=source_plan
        records=f.boundary.fixture.records
        saved_id=identity('saved-replay-'+action)
        if action=='aec.estimate.draft':
            base=records['revision',f.boundary.fixture.revision_id]
            saved_snapshot=deepcopy(snapshot);saved_snapshot.update(id=identity('saved-snapshot'),subject_id=saved_id)
            saved_snapshot['inputs']['rates']={}
            saved_snapshot['inputs']['unit_manifest']['records']=[]
            saved_snapshot['inputs']['unit_manifest']['unit_conversions']=[]
            saved_snapshot['inputs']['currency']='GBP'
            saved_snapshot['source_citations']=[{'revision_id':'saved-source'}]
            graph.modules['cipher_aec.documents.provenance'].source_plan=lambda company,name,*args,**kwargs: (
                graph.events.append(('discover',name)) or deepcopy(source_only if name=='conversion-source' else saved_plan if name=='saved-source' else empty))
            records['snapshot',saved_snapshot['id']]=saved_snapshot
            records['revision',saved_id]={**base,'id':saved_id,'calculation_snapshot':saved_snapshot['id']}
        revision_values={f.boundary.fixture.proposal_revision_value['id']:{**graph.revision,'composition':{}},
            saved_id:{**graph.revision,'id':saved_id,'composition':{}}}
        stack.enter_context(patch.object(graph.canonical_sources,'revision_record',side_effect=lambda company,name,*a,**k:deepcopy(revision_values[name])))
        stack.enter_context(patch.object(graph.canonical_sources,'revision_plan',side_effect=lambda company,name,*a,**k:deepcopy(saved_plan if name==saved_id else graph.plan)))
        # Discovery uses raw immutable IDs; authorization below independently
        # reads original citations/conversions under the admitted union.
        graph.modules['cipher_aec.estimating.repository'].read=lambda kind,name,**kwargs:deepcopy(records[kind,name])
        payload=derive(proposal,run,saves._conversion_originals(f.service,run,f.boundary.originals()))
        core={'company':run['company'],'user':f.boundary.actor.user,'person':f.boundary.actor.person_id,
            'proposal_id':proposal['id'],'action':action,'command':COMMANDS[action][0],'saved_revision_id':saved_id}
        result={'application':core,'saved':{}}
        local=saves.DraftSaveContext(run['company'],proposal['id'],binding(proposal,payload),service=f.service)
        local.run,local.proposal=run,proposal
        request_hash=digest({'scope_type':'Company','command':core['command'],'company':run['company'],'project':None,'payload':local.envelope(payload)})
        stack.enter_context(patch.object(saves,'_load_records',return_value=(f.service,run,proposal)))
        stack.enter_context(patch.object(saves,'_application',return_value={'core':core}))
        stack.enter_context(patch.object(saves,'_receipt',return_value=(SimpleNamespace(request_hash=request_hash),result)))
        stack.enter_context(patch.object(saves.DraftSaveContext,'verify_core',return_value=None))
        governance=ModuleType('cipher_aec.governance.context');governance.require_company=lambda *a,**k:None
        stack.enter_context(patch.dict(sys.modules,{'cipher_aec.governance.context':governance}))
        conversion_read=saves._conversion_originals
        def original_read(*args,**kwargs):
            if kwargs.get('lock'):
                self.assertTrue(lockplan.admitted(source_only if action=='aec.estimate.draft' else empty,f.boundary.actor,run['company']))
                graph.events.append('authorize-conversion')
            return conversion_read(*args,**kwargs)
        stack.enter_context(patch.object(saves,'_conversion_originals',side_effect=original_read))
        def saved_read(core,actor,**kwargs):
            self.assertTrue(lockplan.admitted(saved_plan,actor,run['company']))
            # The actual saved EST scope must be a subset-only reuse.
            with saves._saved_scope(core,actor,True):
                with lockplan.prepared(saved_plan,actor,run['company']):graph.events.append('authorize-saved')
        stack.enter_context(patch.object(saves,'_saved_revision',side_effect=saved_read))
        saves.authorize_receipt(f.boundary.actor,run['company'],result,command=core['command'],lock=True)
        locks=[row for row in graph.events if type(row) is tuple and row[0] in {'UOM','Currency','Supplier','Item','Customer','Opportunity','Quotation','Price List'}]
        expected=graph.canonical_sources.merge(graph.plan,saved_plan,source_only if action=='aec.estimate.draft' else empty)
        # Embedded snapshot units/rates can also contribute; all UOM locks must
        # precede every Currency/native lock, with no second admission pass.
        units=[name for kind,name in locks if kind=='UOM']
        self.assertEqual(units,sorted(set(units)))
        self.assertTrue(set(expected['unit_ids']).issubset(units))
        first_native=next(i for i,row in enumerate(locks) if row[0]!='UOM')
        self.assertFalse(any(kind=='UOM' for kind,name in locks[first_native:]))
        self.assertEqual(locks.count(('Currency','GBP')),1)
        self.assertEqual(graph.events.count('authorize-saved'),1)
        self.assertLess(graph.events.index(('discover','saved-source')) if action=='aec.estimate.draft' else 0,
            next(i for i,row in enumerate(graph.events) if type(row) is tuple and row[0]=='UOM'))
        self.assertEqual(canonical(run),before)
        self.assertFalse(lockplan.active_for(f.boundary.actor,run['company']))

    def test_estimate_replay_unifies_pinned_conversion_sources_and_saved_dependencies(self):
        self.exercise('aec.estimate.draft')

    def test_scope_replay_unifies_original_and_saved_native_dependencies(self):
        self.exercise('aec.scope.draft')

class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.f,self.ctx=ready_scope(self)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        from cipher_aec import commercial
        from cipher_aec.commercial import sources
        self.plans=[]
        self.stack.enter_context(patch.object(self.ctx,'authority',return_value=None))
        service=SimpleNamespace(_source_plan=lambda *args: (('Customer','Fixture Customer'),{('Quotation','Fixture Quotation'),('Opportunity','Fixture Opportunity')}))
        self.stack.enter_context(patch.object(commercial,'service',service,create=True))
        empty={'unit_ids':[],'currencies':[],'native_refs':[],'generated_sources':[]}
        self.stack.enter_context(patch.object(sources,'plan',return_value=empty))
        from cipher_aec.ricky import company_draft_save
        self.stack.enter_context(patch.object(company_draft_save,'_closure_plan',return_value=empty))
        provenance=ModuleType('cipher_aec.documents.provenance');provenance.MAX_NODES=128
        self.stack.enter_context(patch.dict(sys.modules,{'frappe':SimpleNamespace(db=SimpleNamespace(sql=lambda *a,**k:[])),
            'cipher_aec.documents.provenance':provenance}))
        scope=self.f.boundary.source_scope
        @contextmanager
        def admitted(*args,_extra_plan=None,**kwargs):
            self.plans.append(deepcopy(_extra_plan))
            with scope(*args,**kwargs) as plan:yield plan
        self.stack.enter_context(patch.object(self.f.boundary,'source_scope',side_effect=admitted))

    def test_actual_context_discovers_writer_plan_and_verifies_current_preparation_before_yield(self):
        entered=[]
        with self.ctx.new_effect(self.f.boundary.actor):entered.append(True)
        self.assertEqual(entered,[True]);self.assertEqual(len(self.plans),1)
        self.assertEqual(self.plans[0]['unit_ids'],sorted({r['unit_id'] for r in self.ctx.payload['composition']['price_lines']}))
        self.assertIn({'doctype':'Quotation','name':'Fixture Quotation'},self.plans[0]['native_refs'])
        self.assertEqual(self.ctx._terminal_bytes,__import__('cipher_aec.ricky.contracts',fromlist=['canonical']).canonical(self.ctx.run))

    def test_current_head_source_and_reviewed_payload_changes_refuse_before_effect(self):
        original=self.f.boundary.fixture.proposal_value['current_revision']
        self.f.boundary.fixture.proposal_value['current_revision']=identity('successor')
        with self.assertRaises(RickyError):
            with self.ctx.new_effect(self.f.boundary.actor):self.fail('Stale target reached writer')
        self.f.boundary.fixture.proposal_value['current_revision']=original
        self.f.boundary.fixture.source_allowed=False
        with self.assertRaises(RickyError):
            with self.ctx.new_effect(self.f.boundary.actor):self.fail('Denied source reached writer')
        self.f.boundary.fixture.source_allowed=True
        self.ctx.payload['composition']['terms']='Unreviewed mutation'
        with self.assertRaises(DomainError):
            with self.ctx.new_effect(self.f.boundary.actor):self.fail('Changed payload reached writer')
