"""Append-only DOC03 lifecycle checks with explicit host persistence doubles.

These tests do not establish native Frappe persistence or concurrency evidence.
"""
from contextlib import contextmanager,nullcontext
from copy import deepcopy
import importlib
import sys
import json
from types import SimpleNamespace,ModuleType
import unittest
from unittest.mock import patch
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_document_control import fixture,source,person,authorize
from cipher_aec.tests.test_engineering import uid,add_source

@contextmanager
def lifecycle_fixture():
    name='cipher_aec.document_control.lifecycle'
    old=sys.modules.pop(name,None)
    try:
        with fixture() as values:
            s,r,repo,rights,service,gov=values
            life=importlib.import_module(name)
            def candidates(c,p,doc,lock=False):
                return [v['id'] for (k,_),v in s.rows.items() if k=='issue' and v['company']==c and v['project']==p and any(a['document_id']==doc for a in v['artifacts'])]
            def chain(doc,lock=False):
                return sorted([deepcopy(v) for (k,_),v in s.rows.items() if k=='lifecycle' and v['parent_id']==doc],key=lambda v:v['revision_number'])
            with patch.object(repo,'issue_candidates',candidates),patch.object(repo,'lifecycle_chain',chain):
                yield (*values,life)
    finally:
        removed=sys.modules.pop(name,None);parent=sys.modules.get('cipher_aec.document_control')
        if parent is not None and getattr(parent,'lifecycle',None) is removed:delattr(parent,'lifecycle')
        if old is not None:
            sys.modules[name]=old
            if parent is not None:setattr(parent,'lifecycle',old)

def issue(s,r,service,gov,checker,ref=None):
    ref=ref or source(s,service)
    value=service.create_issue_set('C','P',uid(),{'title':'Exact issued drawing','purpose':'Coordination','issue_purpose':'coordination'},[ref],[])['issue_set']
    return authorize(s,r,gov,'issue_set',value,checker)

def request(s,life,doc,current,*,replacement=None,operation=None):
    definition={'action':'supersede' if replacement else 'withdraw','issue_id':current['id'],'issue_digest':digest(current),'replacement_issue_id':replacement['id'] if replacement else None,'replacement_issue_digest':digest(replacement) if replacement else None,'reason':'Explicit independently reviewed drawing lifecycle'}
    before=life.standing('C','P',doc,s.actor)
    return life.request('C','P',operation or uid(),doc,before['version'],definition)['lifecycle_request']

def successor(s,original):
    ref=add_source(s);row=s.documents[ref['revision_id']]
    row.update(document_id=original['artifacts'][0]['document_id'],revision_number=original['artifacts'][0]['revision_number']+1)
    return {k:ref[k] for k in ('revision_id','source_sha256')}

class LifecycleIntegrityTests(unittest.TestCase):
    def test_unanchored_original_standing_is_rejected(self):
        with lifecycle_fixture() as (s,r,repo,rights,service,gov,life):
            checker=person(s,r,'checker');original=issue(s,r,service,gov,checker);doc=original['artifacts'][0]['document_id'];value=request(s,life,doc,original)
            value['before']['original_issued']={**value['before']['original_issued'],'issue_digest':'0'*64}
            value['expected_version']=digest(value['before'])
            with self.assertRaises(DomainError):life.verify_request(value,s.actor)

    def test_event_is_verified_without_recursive_lifecycle_reads(self):
        with lifecycle_fixture() as (s,r,repo,rights,service,gov,life):
            checker=person(s,r,'checker');original=issue(s,r,service,gov,checker);doc=original['artifacts'][0]['document_id'];value=request(s,life,doc,original);event=authorize(s,r,gov,'lifecycle_request',value,checker)
            read=service.read
            def no_recursive(kind,*args,**kw):
                if kind=='lifecycle':raise AssertionError('Lifecycle prefix verification must be iterative')
                return read(kind,*args,**kw)
            with patch.object(service,'read',no_recursive):
                self.assertEqual(life.standing('C','P',doc,s.actor)['status'],'withdrawn')
            self.assertEqual(read('lifecycle',event['id'],'C','P',s.actor),event)

    def test_supersede_then_withdraw_does_not_move_working_head_or_rewrite_originals(self):
        with lifecycle_fixture() as (s,r,repo,rights,service,gov,life):
            checker=person(s,r,'checker');original=issue(s,r,service,gov,checker);doc=original['artifacts'][0]['document_id'];replacement=issue(s,r,service,gov,checker,successor(s,original));before=deepcopy(s.rows)
            self.assertEqual(life.standing('C','P',doc,s.actor)['current_issued']['issue_id'],original['id'])
            value=request(s,life,doc,original,replacement=replacement);event=authorize(s,r,gov,'lifecycle_request',value,checker)
            current=life.standing('C','P',doc,s.actor);self.assertEqual(current['original_issued']['issue_id'],original['id']);self.assertEqual(current['current_issued']['issue_id'],replacement['id'])
            self.assertEqual(service._document(doc,'C','P',s.actor).current_revision,replacement['artifacts'][0]['revision_id'])
            with self.assertRaises(DomainError) as error:service.create_transmittal('C','P',uid(),original['id'],digest(original),[checker.user],'Obsolete issue','')
            self.assertEqual(error.exception.code,'issued_content_not_current')
            trans=service.create_transmittal('C','P',uid(),replacement['id'],digest(replacement),[checker.user],'Current issue','')['transmittal']
            distributed=authorize(s,r,gov,'transmittal',trans,checker)
            withdraw=request(s,life,doc,replacement);withdrawn=authorize(s,r,gov,'lifecycle_request',withdraw,checker)
            self.assertEqual(life.standing('C','P',doc,s.actor)['status'],'withdrawn')
            self.assertEqual(service.read('distribution',distributed['id'],'C','P',s.actor),distributed)
            self.assertEqual(service.read('lifecycle',event['id'],'C','P',s.actor),event)
            self.assertEqual(service.read('lifecycle',withdrawn['id'],'C','P',s.actor),withdrawn)
            with self.assertRaises(DomainError):service.create_transmittal('C','P',uid(),replacement['id'],digest(replacement),[checker.user],'Withdrawn issue','')
            self.assertTrue(all(s.rows[key]==value for key,value in before.items()))

    def test_old_receipt_prefix_ignores_unavailable_later_sources_but_checks_original_rights(self):
        with lifecycle_fixture() as (s,r,repo,rights,service,gov,life):
            checker=person(s,r,'checker');original=issue(s,r,service,gov,checker);doc=original['artifacts'][0]['document_id'];second=issue(s,r,service,gov,checker,successor(s,original));op=uid();value=request(s,life,doc,original,replacement=second,operation=op);first=authorize(s,r,gov,'lifecycle_request',value,checker)
            third=issue(s,r,service,gov,checker,successor(s,second));later=request(s,life,doc,second,replacement=third);authorize(s,r,gov,'lifecycle_request',later,checker);s.denied.add(third['artifacts'][0]['revision_id'])
            replay=life.request('C','P',op,doc,value['expected_version'],value['definition'])
            self.assertTrue(replay['operation']['replayed']);self.assertEqual(replay['lifecycle_request'],value)
            self.assertEqual(service.read('lifecycle',first['id'],'C','P',s.actor),first)
            with self.assertRaises(DomainError):life.standing('C','P',doc,s.actor)
            s.denied.add(original['artifacts'][0]['revision_id'])
            with self.assertRaises(DomainError):life.request('C','P',op,doc,value['expected_version'],value['definition'])
            self.assertEqual(repo.raw('lifecycle',first['id']),first)

    def test_stale_competing_request_independence_and_closed_project(self):
        with lifecycle_fixture() as (s,r,repo,rights,service,gov,life):
            checker=person(s,r,'checker');original=issue(s,r,service,gov,checker);doc=original['artifacts'][0]['document_id'];first=request(s,life,doc,original);second=request(s,life,doc,original)
            alias=SimpleNamespace(user='alias@example.invalid',person_id=s.actor.person_id)
            with self.assertRaises(DomainError) as error:gov.authorize_subject(kind='lifecycle_request',actor=alias,company='C',project='P',subject_id=first['id'],phase='review')
            self.assertEqual(error.exception.code,'independent_document_review')
            s.project_status='Completed'
            for phase in ('request','manifest','review','execute'):
                with self.assertRaises(DomainError):gov.authorize_subject(kind='lifecycle_request',actor=checker if phase=='review' else s.actor,company='C',project='P',subject_id=first['id'],phase=phase)
            s.project_status='Open';authorize(s,r,gov,'lifecycle_request',first,checker);before=deepcopy(s.rows)
            with self.assertRaises(DomainError) as error:authorize(s,r,gov,'lifecycle_request',second,checker)
            self.assertEqual(error.exception.code,'stale_issued_standing');self.assertEqual(s.rows,before)

    def test_event_cycle_and_self_consistent_wrong_manifest_are_refused(self):
        with lifecycle_fixture() as (s,r,repo,rights,service,gov,life):
            checker=person(s,r,'checker');original=issue(s,r,service,gov,checker);doc=original['artifacts'][0]['document_id'];value=request(s,life,doc,original);event=authorize(s,r,gov,'lifecycle_request',value,checker)
            cyclic={**event,'predecessor':event['id']};s.rows['lifecycle',event['id']]=cyclic
            with self.assertRaises(DomainError):service.read('lifecycle',event['id'],'C','P',s.actor)
            s.rows['lifecycle',event['id']]=deepcopy(event)
            packet=s.packets[event['packet_id']];outer=json.loads(packet.manifest_json);outer['domain']['effect']['definition']['reason']='Different reviewed effect';packet.manifest_json=json.dumps(outer);packet.manifest_hash=digest(outer);s.decisions[event['decision_id']].manifest_hash=packet.manifest_hash
            tampered={**event,'effect_digest':digest(outer['domain']['effect'])};s.rows['lifecycle',event['id']]=tampered;s.consumptions[event['packet_id']].result_hash=digest({'lifecycle':tampered})
            with self.assertRaises(DomainError) as error:service.read('lifecycle',event['id'],'C','P',s.actor)
            self.assertEqual(error.exception.code,'document_approval_integrity')

    def test_ambiguous_same_document_issue_is_refused_before_fact(self):
        with lifecycle_fixture() as (s,r,repo,rights,service,gov,life):
            checker=person(s,r,'checker');ref=source(s,service);doc=s.documents[ref['revision_id']]['document_id'];nextref=add_source(s);s.documents[nextref['revision_id']].update(document_id=doc,revision_number=2)
            value=service.create_issue_set('C','P',uid(),{'title':'Ambiguous','purpose':'Coordination','issue_purpose':'coordination'},[ref,{k:nextref[k] for k in ('revision_id','source_sha256')}],[])['issue_set'];before=deepcopy(s.rows)
            with self.assertRaises(DomainError) as error:authorize(s,r,gov,'issue_set',value,checker)
            self.assertEqual(error.exception.code,'issue_document_conflict');self.assertEqual(s.rows,before)

    def test_request_late_receipt_failure_restores_rows_and_history(self):
        with lifecycle_fixture() as (s,r,repo,rights,service,gov,life):
            checker=person(s,r,'checker');original=issue(s,r,service,gov,checker);before=deepcopy((s.rows,s.events,s.receipts));s.failed_receipt=True
            with self.assertRaises(RuntimeError):request(s,life,original['artifacts'][0]['document_id'],original)
            self.assertEqual((s.rows,s.events,s.receipts),before)

    def test_actual_lifecycle_manifests_requests_facts_and_standing_match_closed_wire(self):
        from cipher_aec.tests.test_document_control_contracts import validate,CORE
        for action in ('withdraw','supersede'):
            with self.subTest(action=action),lifecycle_fixture() as (s,r,repo,rights,service,gov,life):
                checker=person(s,r,'checker');original=issue(s,r,service,gov,checker);doc=original['artifacts'][0]['document_id'];replacement=issue(s,r,service,gov,checker,successor(s,original)) if action=='supersede' else None
                value=request(s,life,doc,original,replacement=replacement);fact=authorize(s,r,gov,'lifecycle_request',value,checker)
                validate('DcLifecycleRequest',value);validate('DcLifecycle',fact);validate('DcIssuedStandingResponse',life.get_standing('C','P',doc))
                validate('DcGetResponse',service.get_record('C','P','lifecycle',fact['id']))
                native=s.packets[fact['packet_id']];domain=json.loads(native.manifest_json)['domain']
                packet={'schema':'cipher.document.approval.v1','id':native.name,'company':'C','project':'P','action':r.ACTIONS['lifecycle_request'],'subject':{'id':value['id'],'type':r.KINDS['lifecycle_request'],'label':'Explicit issued drawing lifecycle'},'requester':{'id':s.actor.person_id,'display_name':'Author'},'created_at':'2026-10-17T00:00:00Z','expires_at':'2026-10-18T00:00:00Z','manifest_hash':native.manifest_hash,'source_version':digest(value),'policy':{'id':'policy','label':'Independent lifecycle review','synthetic':True},'state':'Consumed','decisions':[],'actions':{'can_decide':False,'can_execute':False,'can_withdraw':False,'disabled_reason':'Consumed'},'review_manifest':domain}
                self.assertNotEqual(digest(domain),native.manifest_hash)
                validate('ApprovalPacket',packet,CORE);validate('DocumentApprovalExecutionResponse',{'packet':packet,'effect':{'lifecycle':fact},'operation':{'id':uid(),'status':'succeeded','replayed':False}},CORE)
                bad=deepcopy(packet);bad['review_manifest']['effect']['subject_kind']='issue_set'
                with self.assertRaises(Exception):validate('ApprovalPacket',bad,CORE)

class LifecycleLockClosureTests(unittest.TestCase):
    def test_current_union_includes_whole_prefix_but_original_receipt_excludes_later_event(self):
        with lifecycle_fixture() as (s,r,repo,rights,service,gov,life):
            checker=person(s,r,'checker');original=issue(s,r,service,gov,checker);doc=original['artifacts'][0]['document_id'];replacement=issue(s,r,service,gov,checker,successor(s,original));value=request(s,life,doc,original,replacement=replacement);event=authorize(s,r,gov,'lifecycle_request',value,checker)
            third=issue(s,r,service,gov,checker,successor(s,replacement));later=request(s,life,doc,replacement,replacement=third);authorize(s,r,gov,'lifecycle_request',later,checker)
            locking=importlib.import_module('cipher_aec.document_control.locking');provenance=ModuleType('provenance');provenance.MAX_NODES=128;provenance.source_plan=lambda *a,**kw:{};provenance.binding=lambda *a:None
            def metadata(name):return SimpleNamespace(company='C',project='P',scope_type='Project')
            original_raw=repo.raw;reads=[]
            def raw(kind,name,**kw):reads.append((kind,name));return original_raw(kind,name,**kw)
            with patch.dict(sys.modules,{'cipher_aec.documents.provenance':provenance}),patch.object(service.FrappeDocumentRepository,'document_scope',lambda _,name:metadata(name),create=True),patch.object(repo,'raw',raw):
                current=locking.for_payload('C','P','lifecycle.prepare',{'document_id':doc,'definition':value['definition']});current.discover(s.actor)
                self.assertIn(('issue',third['id']),reads);reads.clear()
                historical=locking.for_result('C','P',{'lifecycle':event});historical.discover(s.actor)
                self.assertIn(('issue',original['id']),reads);self.assertIn(('issue',replacement['id']),reads);self.assertNotIn(('issue',third['id']),reads)
                self.assertFalse(historical.standing_documents)

    def test_all_scope_and_recipient_duties_precede_master_and_document_locks(self):
        with lifecycle_fixture() as (s,r,repo,rights,service,gov,life):
            ref=source(s,service);company_ref=add_source(s);s.documents[company_ref['revision_id']].update(scope_type='Company',project=None);recipient=person(s,r,'recipient');declared={'user':recipient.user,'person':recipient.person_id};observed=[]
            locking=importlib.import_module('cipher_aec.document_control.locking');scopes=importlib.import_module('cipher_aec.document_control.scopes')
            def revision(name):
                row=s.documents[name];return SimpleNamespace(company='C',project=row.get('project','P'),scope_type=row.get('scope_type','Project'),document=row['document_id'])
            def document(name):
                row=next(row for row in s.documents.values() if row['document_id']==name);return SimpleNamespace(company='C',project=row.get('project','P'),scope_type=row.get('scope_type','Project'))
            def scope(*args,ability=None,actor=None,lock=False):observed.append(('duty',actor.person_id,ability));return SimpleNamespace()
            units=ModuleType('units');units.qualified=lambda name,**kw:observed.append(('master','unit',name))
            native=ModuleType('native');native.require_native=lambda kind,name,*a,**kw:observed.append(('master',kind,name))
            provenance=ModuleType('provenance');provenance.MAX_NODES=128;provenance.binding=lambda *a:None;provenance.prelocked=lambda *a:nullcontext();provenance.source_plan=lambda *a,**kw:{'unit_ids':['u'],'currencies':['USD'],'native_refs':[{'doctype':'Customer','name':'c'}]}
            with patch.dict(sys.modules,{'cipher_aec.documents.provenance':provenance,'cipher_aec.estimating.units':units,'cipher_aec.commercial.native':native}),patch.object(service.FrappeDocumentRepository,'document',lambda _,name,**kw:{'name':name}),patch.object(service.FrappeDocumentRepository,'revision_scope',lambda _,name:revision(name)),patch.object(service.FrappeDocumentRepository,'document_scope',lambda _,name:document(name),create=True),patch.object(locking,'require_project',scope),patch.object(locking,'require_company',scope),patch.object(scopes,'document',lambda name,*a,**kw:observed.append(('document',name))):
                ctx=locking.DocumentContext('C','P',artifacts=[ref,{k:company_ref[k] for k in ('revision_id','source_sha256')}],recipients=[declared]);ctx.prelock(s.actor)
                self.assertEqual(ctx.initial['scopes'],[('Company',None),('Project','P')])
                with ctx.hold(s.actor):observed.append(('effect',))
                master=next(i for i,row in enumerate(observed) if row[0]=='master')
                self.assertTrue(any(row[0]=='duty' and row[1]==recipient.person_id for row in observed[:master]))
                self.assertFalse(any(row[0]=='master' for row in observed[:master]))
                self.assertEqual([row[1] for row in observed if row[0]=='document'],sorted(ctx.initial['documents']))
                self.assertTrue(rights.document_plan([s.documents[ref['revision_id']]['document_id']])<=set(ctx.initial['documents']))

    def test_dependency_growth_is_refused_before_first_master(self):
        with lifecycle_fixture() as (s,r,repo,rights,service,gov,life):
            locking=importlib.import_module('cipher_aec.document_control.locking');context=locking.DocumentContext('C','P');initial={'scopes':[('Project','P')],'documents':{},'native':{},'recipients':[]};units=ModuleType('units');units.qualified=lambda *a,**kw:self.fail('No master lock before stable complete union');native=ModuleType('native');native.require_native=lambda *a,**kw:self.fail('No native lock before stable union')
            with patch.dict(sys.modules,{'cipher_aec.estimating.units':units,'cipher_aec.commercial.native':native}),patch.object(context,'discover',side_effect=[deepcopy(initial),{**initial,'documents':{'new':('Company',None)}}]),patch.object(locking,'require_project',lambda *a,**kw:None):
                context.prelock(s.actor)
                with self.assertRaises(DomainError) as error:
                    with context.hold(s.actor):self.fail('No effect before stable union')
                self.assertEqual(error.exception.code,'document_sources_changed')

    def test_distinct_recipient_generated_source_is_fresh_nonlocking_and_denial_is_not_cached(self):
        with lifecycle_fixture() as (s,r,repo,rights,service,gov,life):
            locking=importlib.import_module('cipher_aec.document_control.locking');scopes=importlib.import_module('cipher_aec.document_control.scopes');provenance=importlib.import_module('cipher_aec.documents.provenance');outputs=importlib.import_module('cipher_aec.commercial.output_sources');recipient=person(s,r,'recipient');declared={'user':recipient.user,'person':recipient.person_id};doc=uid();row={'name':doc,'company':'C','project':None,'scope_type':'Company','producer_input_digest':'1'*64};value={'company':'C','project':'P','issue_id':uid(),'artifacts':[{'document_id':doc,'revision_id':uid()}]};plan={'scopes':[('Company',None),('Project','P')],'documents':{doc:('Company',None)},'native':{},'recipients':[declared]};observed=[];denied=[]
            def producer(binding,actor,lock=False):
                observed.append((actor.person_id,lock))
                if denied:raise DomainError('capability_denied','Recipient no longer has original producer access',403)
            def verify(artifacts,company,project,actor,lock=False):provenance.authorize(row,actor,lock=lock)
            read_recipient=getattr(locking.recipient_read,'__wrapped__',locking.recipient_read)
            token=locking._active.set({'company':'C','identity':(s.actor.user,s.actor.person_id),'plan':plan})
            try:
                with patch('cipher_aec.document_control.shared.artifact_scope',return_value=('Company',None)),patch.object(scopes,'require',lambda *a,**kw:None),patch.object(rights,'authorize',lambda *a,**kw:None),patch.object(provenance,'_current_db',return_value=None),patch.object(provenance,'_document',return_value=row),patch.object(provenance,'binding',return_value={'exact':'producer'}),patch.object(outputs,'authorize_binding',producer),patch.object(service,'verify_artifacts',verify),patch.object(service,'read',lambda *a,**kw:None),provenance.prelocked({},s.actor,'C'):
                    # Warm the preparer path; it must grant nothing to another person.
                    provenance.authorize(row,s.actor,lock=False)
                    read_recipient(value,declared,s.actor,lock=True);denied.append(True)
                    with patch('cipher_aec.document_control.shared.artifact_scope',return_value=('Company',None)),self.assertRaises(DomainError):read_recipient(value,declared,s.actor,lock=True)
                self.assertEqual(observed,[(s.actor.person_id,False),(recipient.person_id,False),(recipient.person_id,False)])
            finally:locking._active.reset(token)
            with patch('cipher_aec.document_control.shared.artifact_scope',return_value=('Company',None)),self.assertRaises(DomainError):read_recipient(value,declared,s.actor,lock=True)

if __name__=='__main__':unittest.main()
