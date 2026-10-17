"""Host DOC03 services with explicit persistence/session doubles, never native evidence."""
from contextlib import contextmanager,ExitStack
from copy import deepcopy
import hashlib,importlib,json,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_engineering import fixtures,add_source,add_person,uid

@contextmanager
def retained_module_attributes():
    missing=object();names=('cipher_aec.governance.context','cipher_aec.governance.commands','cipher_aec.governance.history','cipher_aec.governance.approvals','cipher_aec.documents.service','cipher_aec.documents.repository')
    saved={name:getattr(sys.modules.get(name.rsplit('.',1)[0]),name.rsplit('.',1)[1],missing) for name in names}
    try:yield
    finally:
        for name,value in saved.items():
            parent=sys.modules.get(name.rsplit('.',1)[0]);attribute=name.rsplit('.',1)[1]
            if parent is None:continue
            if value is missing:
                if hasattr(parent,attribute):delattr(parent,attribute)
            else:setattr(parent,attribute,value)

@contextmanager
def fixture():
    with retained_module_attributes(),fixtures() as (state,*_):
        names=['cipher_aec.document_control.'+n for n in ('contracts','repository','rights','service','governance','clauses','locking','scopes','shared')];old={n:sys.modules.pop(n) for n in names if n in sys.modules}
        try:
            rules,repo,rights,service,gov=[importlib.import_module(n) for n in names[:5]];state.duties[state.actor.person_id]=set(rules.ABILITIES)|{'project.read','document.read','document.write'};state.locks=[];state.plans=[]
            def raw(kind,name,lock=False):
                if (kind,name) not in state.rows:raise DomainError('not_found','missing',404)
                return deepcopy(state.rows[kind,name])
            def write(kind,value,old=None):
                if old is not None and raw(kind,value['id'])!=old:raise DomainError('stale','changed',412)
                state.rows[kind,value['id']]=deepcopy(value);return value
            def latest(kind,parent,lock=False):return next(iter(sorted([deepcopy(v) for (k,_),v in state.rows.items() if k==kind and v.get('parent_id')==parent],key=lambda v:v['revision_number'],reverse=True)),None)
            def document(name,company,project,actor,lock=False):
                service.require_project(company,project,ability='document.read',actor=actor,lock=lock)
                if name not in {v['document_id'] for v in state.documents.values()}:raise DomainError('not_found','source',404)
                state.locks.append(name);head=max((v for v in state.documents.values() if v['document_id']==name),key=lambda v:v['revision_number'])
                return SimpleNamespace(name=name,company=company,project=project,scope_type='Project',current_revision=head['revision_id'])
            def locator(name):
                v=state.documents[name];return SimpleNamespace(name=name,company='C',project='P',scope_type='Project',document=v['document_id'])
            def command(**kw):
                state.plans.append(tuple(kw.get('participant_people',())))
                service.require_project(kw['company'],kw['project'],ability=kw['ability'],actor=state.actor)
                key=(state.actor.person_id,kw['operation_id']);request=digest({k:kw[k] for k in ('command','company','project','payload')})
                if key in state.receipts:
                    previous,result=state.receipts[key]
                    if previous!=request:raise DomainError('operation_conflict','conflict',409)
                    service.authorize_receipt(state.actor,'C','P',result,lock=True);return {**deepcopy(result),'operation':{'id':key[1],'status':'succeeded','replayed':True}}
                before=deepcopy((state.rows,state.events,state.receipts))
                try:
                    project=service.require_project('C','P',actor=state.actor);kw['guard'](state.actor,project);result=kw['effect'](state.actor,project)
                    if state.failed_receipt:raise RuntimeError('late receipt failure')
                    state.receipts[key]=(request,deepcopy(result));return {**result,'operation':{'id':key[1],'status':'succeeded','replayed':False}}
                except Exception:state.rows,state.events,state.receipts=before;raise
            with ExitStack() as stack:
                for target,name,value in [(repo,'raw',raw),(repo,'write',write),(repo,'latest',latest),(repo,'official',lambda kind,subject_id,lock=False:next((deepcopy(v) for (k,_),v in state.rows.items() if k==kind and v.get('subject_id')==subject_id),None)),(rights,'current',lambda name,lock=False:latest('rights',name,lock)),(service,'_document',document),(service.FrappeDocumentRepository,'revision_scope',lambda self,name:locator(name)),(service,'run_command',command)]:stack.enter_context(patch.object(target,name,value))
                yield state,rules,repo,rights,service,gov
        finally:
            for n in names:
                removed=sys.modules.pop(n,None);parentname,attribute=n.rsplit('.',1);parent=sys.modules.get(parentname)
                if removed is not None and parent is not None and getattr(parent,attribute,None) is removed:delattr(parent,attribute)
            sys.modules.update(old)
            for n,value in old.items():setattr(sys.modules[n.rsplit('.',1)[0]],n.rsplit('.',1)[1],value)

def person(state,rules,label):
    value=add_person(state,label);state.duties[value.person_id]=set(rules.ABILITIES)|{'project.read','document.read','document.write'};return value
def permission(state,**overrides):
    evidence=add_source(state)
    return {'ingest_allowed':True,'read_allowed':True,'distribute_allowed':True,'rights_basis':'Authored synthetic permission declaration, not a verified legal license.','rights_holder':'Synthetic declared rights holder','allowed_purpose':'Project ingestion, retained retrieval and internal coordination','restriction':'No external delivery or inferred legal execution','valid_from':None,'valid_until':None,'evidence_artifact':{k:evidence[k] for k in ('revision_id','source_sha256')},**overrides}
def source(state,service,*,extracted=False):
    value=add_source(state,extracted=extracted);document=state.documents[value['revision_id']]['document_id'];service.set_rights('C','P',uid(),document,None,permission(state, **({'ingest_allowed':True,'read_allowed':True,'distribute_allowed':True,'rights_basis':'Authored synthetic permission declaration; not a verified legal license.'})));return {k:value[k] for k in ('revision_id','source_sha256')}
def library(state,service,ref=None):
    ref=ref or source(state,service)
    value=service.create_library('C','P',uid(),{'title':'Original specification','category':'specification','discipline':'Structural','ownership':'Declared synthetic source owner','tags':['concrete'],'change_reason':'Initial retained original'},ref);return value,ref
def authorize(state,rules,gov,kind,value,checker):
    gov.authorize_subject(kind=kind,actor=checker,company='C',project='P',subject_id=value['id'],phase='review')
    manifest=gov.approval_manifest(kind=kind,actor=state.actor,company='C',project='P',subject_id=value['id'],expected_version=digest(value),lock=True);packetid,decisionid=uid(),uid();outer={'action':rules.ACTIONS[kind],'action_version':1,'company':'C','project':'P','source_version':digest(value),'requester_person':state.actor.person_id,'policy_revision':'fixture-document-policy','policy_hash':digest({'fixture':True}),'domain':manifest}
    state.packets[packetid]=SimpleNamespace(name=packetid,company='C',project='P',scope_type='Project',action=rules.ACTIONS[kind],subject_type=rules.KINDS[kind],subject_id=value['id'],requester_person=state.actor.person_id,manifest_json=json.dumps(outer),manifest_hash=digest(outer));state.decisions[decisionid]=SimpleNamespace(name=decisionid,packet=packetid,decision='Grant',actor_person=checker.person_id,manifest_hash=digest(outer));state.approval_effect=(rules.ACTIONS[kind],value['id'],packetid)
    try:result=gov.apply_authorization(kind=kind,actor=state.actor,company='C',project='P',manifest=manifest,packet_id=packetid,decision_id=decisionid,operation_id=uid())
    finally:state.approval_effect=None
    state.consumptions[packetid]=SimpleNamespace(packet=packetid,decision=decisionid,company='C',project='P',scope_type='Project',actor_person=state.actor.person_id,result_hash=digest(result));return result[rules.FACTS[kind]]
def adopted(state,rules,service,gov):
    created,ref=library(state,service);request=service.create_adoption('C','P',uid(),created['library_revision']['id'],digest(created['library_revision']),{'purpose':'Use exact specification','target_locator':'Project specification section 03 30 00','change_reason':'Independent adoption'})['adoption_request'];checker=person(state,rules,'checker');return created,ref,authorize(state,rules,gov,'adoption_request',request,checker),checker

class DocumentaryWorkflowTests(unittest.TestCase):
    def test_library_adoption_issue_internal_distribution_and_recipient_report(self):
        with fixture() as (s,r,repo,rights,service,gov):
            created,ref,adoption,checker=adopted(s,r,service,gov);issuedset=service.create_issue_set('C','P',uid(),{'title':'Coordination set','purpose':'Exact internal references','issue_purpose':'coordination'},[],[{'id':adoption['id'],'record_digest':digest(adoption)}])['issue_set'];issue=authorize(s,r,gov,'issue_set',issuedset,checker);recipient=person(s,r,'recipient');trans=service.create_transmittal('C','P',uid(),issue['id'],digest(issue),[recipient.user],'Review exact issued set','Acknowledge receipt')['transmittal'];self.assertIn(recipient.person_id,s.plans[-1]);distribution=authorize(s,r,gov,'transmittal',trans,checker)
            self.assertEqual(service.read('distribution',distribution['id'],'C','P',recipient),distribution);self.assertFalse(distribution['external_delivery']);s.actor=recipient;evidence=service.record_evidence('C','P',uid(),'distribution',distribution['id'],digest(distribution),'Received original internal package',[ref])['evidence'];self.assertEqual(evidence['status'],'reported_received');self.assertFalse(evidence['commercial_execution'])
    def test_vector_source_without_text_can_be_adopted_without_invented_excerpt(self):
        with fixture() as (s,r,repo,rights,service,gov):
            created,ref=library(s,service);self.assertEqual(s.documents[ref['revision_id']]['extraction_status'],'ocr_unavailable');self.assertNotIn('text',created['library_revision']);self.assertEqual(len(created['library_revision']['artifacts']),1)
    def test_source_and_library_successors_preserve_adoption_and_documentary_execution_evidence(self):
        with fixture() as (s,r,repo,rights,service,gov):
            created,ref,adoption,_=adopted(s,r,service,gov);evidence=service.record_evidence('C','P',uid(),'adoption',adoption['id'],digest(adoption),'Reported signed hardcopy is retained as documentary evidence only',[ref])['evidence'];old=deepcopy(s.rows);nextref=source(s,service);new=service.revise_library('C','P',uid(),created['library']['id'],digest(created['library']),{**created['library_revision']['definition'],'change_reason':'Explicit source successor'},nextref)
            self.assertEqual(service.get_record('C','P','adoption',adoption['id'])['library_current'],False);self.assertEqual(service.read('adoption',adoption['id'],'C','P',s.actor),adoption);self.assertEqual(service.read('evidence',evidence['id'],'C','P',s.actor),evidence);self.assertEqual(s.rows['library_revision',created['library_revision']['id']],old['library_revision',created['library_revision']['id']]);self.assertEqual(new['library_revision']['predecessor'],created['library_revision']['id']);self.assertFalse(evidence['commercial_execution'])
    def test_native_source_successor_marks_adoption_out_of_date_before_library_is_updated(self):
        with fixture() as (s,r,repo,rights,service,gov):
            created,ref,adoption,_=adopted(s,r,service,gov);self.assertTrue(service.get_record('C','P','adoption',adoption['id'])['library_current']);newid=uid();s.documents[newid]={**deepcopy(s.documents[ref['revision_id']]),'revision_id':newid,'revision_number':2}
            self.assertFalse(service.get_record('C','P','adoption',adoption['id'])['library_current']);self.assertEqual(service.read('adoption',adoption['id'],'C','P',s.actor),adoption)
    def test_current_rights_revoke_old_adoption_and_receipt_but_do_not_rewrite_originals(self):
        with fixture() as (s,r,repo,rights,service,gov):
            created,ref,adoption,_=adopted(s,r,service,gov);doc=s.documents[ref['revision_id']]['document_id'];policy=rights.current(doc);original=deepcopy(adoption);service.set_rights('C','P',uid(),doc,digest(policy),permission(s, **({'ingest_allowed':False,'read_allowed':False,'distribute_allowed':False,'rights_basis':'Current authored rights revoked'})))
            for call in (lambda:service.read('adoption',adoption['id'],'C','P',s.actor),lambda:service.authorize_receipt(s.actor,'C','P',{'library':created['library'],'library_revision':created['library_revision']})):
                with self.assertRaises(DomainError) as error:call()
                self.assertEqual(error.exception.code,'source_rights_denied')
            self.assertEqual(s.rows['adoption',adoption['id']],original)
    def test_ingestion_retrieval_distribution_flags_are_independent(self):
        with fixture() as (s,r,repo,rights,service,gov):
            created,ref=library(s,service);doc=s.documents[ref['revision_id']]['document_id'];policy=rights.current(doc);service.set_rights('C','P',uid(),doc,digest(policy),permission(s, **({'ingest_allowed':False,'read_allowed':True,'distribute_allowed':False,'rights_basis':'Retain read only'})))
            self.assertEqual(service.read('library_revision',created['library_revision']['id'],'C','P',s.actor),created['library_revision'])
            for op in ('ingest','distribute'):
                with self.assertRaises(DomainError):rights.require(doc,'C','P',op,s.actor)
    def test_current_original_document_permission_is_required_in_addition_to_policy(self):
        with fixture() as (s,r,repo,rights,service,gov):
            created,_=library(s,service);s.duties[s.actor.person_id].remove('document.read')
            with self.assertRaises(DomainError):service.read('library_revision',created['library_revision']['id'],'C','P',s.actor)
    def test_source_rights_management_is_separate_and_not_implied_by_authoring(self):
        with fixture() as (s,r,repo,rights,service,gov):
            ref=add_source(s);s.duties[s.actor.person_id].remove(r.MANAGE)
            with self.assertRaises(DomainError):service.set_rights('C','P',uid(),s.documents[ref['revision_id']]['document_id'],None,permission(s, **({'ingest_allowed':True,'read_allowed':True,'distribute_allowed':True,'rights_basis':'Declaration'})))
            self.assertFalse(s.rows)
    def test_rights_manager_can_revoke_retained_sources_after_project_closure(self):
        with fixture() as (s,r,repo,rights,service,gov):
            created,ref=library(s,service);doc=s.documents[ref['revision_id']]['document_id'];old=rights.current(doc);s.project_status='Completed';service.set_rights('C','P',uid(),doc,digest(old),permission(s, **({'ingest_allowed':False,'read_allowed':False,'distribute_allowed':False,'rights_basis':'Post-close source rights revoked'})))
            with self.assertRaises(DomainError):service.read('library_revision',created['library_revision']['id'],'C','P',s.actor)
    def test_same_uuid_replays_original_source_after_successor_and_conflicts_on_changed_input(self):
        with fixture() as (s,r,repo,rights,service,gov):
            ref=source(s,service);operation=uid();definition={'title':'Retained','category':'contract_clause','discipline':'Contract','ownership':'Declared owner','tags':[],'change_reason':'Initial'};old=service.create_library('C','P',operation,definition,ref);nextref=source(s,service);service.revise_library('C','P',uid(),old['library']['id'],digest(old['library']),{**definition,'change_reason':'Updated'},nextref);s.denied.add(nextref['revision_id']);replay=service.create_library('C','P',operation,definition,ref);self.assertTrue(replay['operation']['replayed']);self.assertEqual(replay['library_revision'],old['library_revision'])
            with self.assertRaises(DomainError):service.create_library('C','P',operation,{**definition,'title':'Changed'},ref)
            s.denied.add(ref['revision_id'])
            with self.assertRaises(DomainError):service.create_library('C','P',operation,definition,ref)
    def test_late_receipt_failure_rolls_back_revision_and_history(self):
        with fixture() as (s,r,repo,rights,service,gov):
            ref=source(s,service);before=deepcopy((s.rows,s.events,s.receipts));s.failed_receipt=True
            with self.assertRaises(RuntimeError):library(s,service,ref)
            self.assertEqual((s.rows,s.events,s.receipts),before)
    def test_alias_and_source_author_cannot_independently_review_adoption(self):
        with fixture() as (s,r,repo,rights,service,gov):
            created,_=library(s,service);request=service.create_adoption('C','P',uid(),created['library_revision']['id'],digest(created['library_revision']),{'purpose':'Adopt','target_locator':'Clause 1','change_reason':'Initial'})['adoption_request'];alias=SimpleNamespace(user='alias@example.invalid',person_id=s.actor.person_id)
            for actor in (s.actor,alias):
                with self.assertRaises(DomainError):gov.authorize_subject(kind='adoption_request',actor=actor,company='C',project='P',subject_id=request['id'],phase='review')
    def test_project_closure_blocks_new_approval_phases_and_preserves_original_reads(self):
        with fixture() as (s,r,repo,rights,service,gov):
            created,ref=library(s,service);value=service.create_issue_set('C','P',uid(),{'title':'Exact','purpose':'Review','issue_purpose':'review'},[ref],[])['issue_set'];s.project_status='Completed'
            self.assertEqual(service.read('issue_set',value['id'],'C','P',s.actor),value)
            for phase in ('request','manifest','review','execute'):
                with self.assertRaises(DomainError):gov.authorize_subject(kind='issue_set',actor=person(s,r,'checker'),company='C',project='P',subject_id=value['id'],phase=phase)
    def test_recipient_rights_rechecked_and_identity_rebinding_refused(self):
        with fixture() as (s,r,repo,rights,service,gov):
            _,ref=library(s,service);checker=person(s,r,'checker');issue=authorize(s,r,gov,'issue_set',service.create_issue_set('C','P',uid(),{'title':'Exact','purpose':'Coordinate','issue_purpose':'coordination'},[ref],[])['issue_set'],checker);recipient=person(s,r,'recipient');value=service.create_transmittal('C','P',uid(),issue['id'],digest(issue),[recipient.user],'Review','')['transmittal'];s.duties[recipient.person_id].remove('document.read')
            with self.assertRaises(DomainError):gov.authorize_subject(kind='transmittal',actor=s.actor,company='C',project='P',subject_id=value['id'],phase='request')
            s.duties[recipient.person_id].add('document.read');s.users[recipient.user]=SimpleNamespace(user=recipient.user,person_id=uid())
            with self.assertRaises(DomainError):gov.authorize_subject(kind='transmittal',actor=s.actor,company='C',project='P',subject_id=value['id'],phase='request')
    def test_authorization_fact_requires_exact_consumption_and_cannot_claim_external_effects(self):
        with fixture() as (s,r,repo,rights,service,gov):
            _,_,adoption,_=adopted(s,r,service,gov);self.assertEqual(service.read('adoption',adoption['id'],'C','P',s.actor),adoption);s.consumptions[adoption['packet_id']].result_hash='0'*64
            with self.assertRaises(DomainError):service.read('adoption',adoption['id'],'C','P',s.actor)
    def test_internal_delivery_receipt_requires_recipient_preparer_or_distribution_duty(self):
        with fixture() as (s,r,repo,rights,service,gov):
            _,ref=library(s,service);checker=person(s,r,'checker');issued=authorize(s,r,gov,'issue_set',service.create_issue_set('C','P',uid(),{'title':'Exact','purpose':'Internal','issue_purpose':'information'},[ref],[])['issue_set'],checker);recipient=person(s,r,'recipient');transmittal=service.create_transmittal('C','P',uid(),issued['id'],digest(issued),[recipient.user],'Exact internal reference','')['transmittal'];distributed=authorize(s,r,gov,'transmittal',transmittal,checker);other=person(s,r,'other');s.duties[other.person_id].remove(r.DISTRIBUTE)
            with self.assertRaises(DomainError):service.read('distribution',distributed['id'],'C','P',other)
            self.assertEqual(service.read('distribution',distributed['id'],'C','P',recipient),distributed)
    def test_no_policy_is_not_a_doc03_ingestion_entitlement(self):
        with fixture() as (s,r,repo,rights,service,gov):
            ref=add_source(s);doc=s.documents[ref['revision_id']]['document_id'];self.assertIsNone(rights.require(doc,'C','P','read',s.actor,required=False))
            with self.assertRaises(DomainError):library(s,service,{k:ref[k] for k in ('revision_id','source_sha256')})
    def test_artifact_hash_corruption_and_wrong_project_fail_closed(self):
        with fixture() as (s,r,repo,rights,service,gov):
            created,ref=library(s,service);s.documents[ref['revision_id']]['content']=b'changed bytes'
            with self.assertRaises(DomainError):service.read('library_revision',created['library_revision']['id'],'C','P',s.actor)
            with self.assertRaises(DomainError):service.read('library_revision',created['library_revision']['id'],'C','OTHER',s.actor)
    def test_library_header_and_receipt_cannot_adopt_another_entry_revision(self):
        with fixture() as (s,r,repo,rights,service,gov):
            first,_=library(s,service);second,_=library(s,service);wrong={**first['library'],'current_revision':second['library_revision']['id']};s.rows['library',first['library']['id']]=wrong
            for call in (lambda:service.read('library',first['library']['id'],'C','P',s.actor),lambda:service.authorize_receipt(s.actor,'C','P',{'library':wrong})):
                with self.assertRaises(DomainError):call()

class CentralDocumentRightsTests(unittest.TestCase):
    def test_locking_central_admission_locks_document_before_current_policy(self):
        with fixture() as (s,r,repo,rights,service,gov):
            ref=source(s,service);doc=s.documents[ref['revision_id']]['document_id'];policy=rights.current(doc);observed=[]
            def current(name,lock=False):
                if lock:observed.append('policy')
                return policy if name==doc else None
            with patch.object(service,'_document',side_effect=lambda name,*a,**kw:observed.append(name)),patch.object(rights,'current',side_effect=current):
                rights.authorize({'name':ref['revision_id'],'document':doc,'company':'C','project':'P','scope_type':'Project'},s.actor,lock=True)
            self.assertEqual(observed[:2],sorted([doc,policy['evidence_artifact']['document_id']]));self.assertEqual(observed[2],'policy')
    def test_expired_and_future_permissions_deny_every_current_use_boundary(self):
        for field,date in (('valid_until','2026-10-16'),('valid_from','2026-10-18')):
            with self.subTest(field=field),fixture() as (s,r,repo,rights,service,gov):
                created,ref=library(s,service);doc=s.documents[ref['revision_id']]['document_id'];old=rights.current(doc)
                service.set_rights('C','P',uid(),doc,digest(old),permission(s,**{field:date}))
                with patch.object(rights,'today',return_value='2026-10-17'):
                    for operation in ('ingest','read','distribute'):
                        with self.assertRaises(DomainError) as error:rights.require(doc,'C','P',operation,s.actor)
                        self.assertEqual(error.exception.code,'source_rights_inactive')
                    with self.assertRaises(DomainError):service.read('library_revision',created['library_revision']['id'],'C','P',s.actor)
                self.assertEqual(repo.raw('library_revision',created['library_revision']['id']),created['library_revision'])
    def test_original_permission_evidence_survives_successor_but_current_evidence_denial_blocks_use(self):
        with fixture() as (s,r,repo,rights,service,gov):
            created,ref=library(s,service);doc=s.documents[ref['revision_id']]['document_id'];old=rights.current(doc);evidence=deepcopy(old['evidence_artifact']);successor=uid();s.documents[successor]={**deepcopy(s.documents[evidence['revision_id']]),'revision_id':successor,'revision_number':2}
            self.assertEqual(rights.require(doc,'C','P','read',s.actor)['evidence_artifact'],evidence);s.denied.add(evidence['revision_id'])
            for operation in ('ingest','read','distribute'):
                with self.assertRaises(DomainError):rights.require(doc,'C','P',operation,s.actor)
            with self.assertRaises(DomainError):service.authorize_receipt(s.actor,'C','P',{'library_revision':created['library_revision']})
            self.assertEqual(repo.raw('rights',old['id'])['evidence_artifact'],evidence)
    def test_native_long_text_query_admission_rechecks_original_evidence_and_bounds_scan(self):
        with fixture() as (s,r,repo,rights,service,gov):
            ref=source(s,service);doc=s.documents[ref['revision_id']]['document_id'];policy=rights.current(doc);row=SimpleNamespace(parent_id=doc,company='C',project='P')
            with patch.object(rights.frappe.db,'exists',create=True,return_value=True),patch.object(rights.frappe.db,'escape',create=True,side_effect=lambda name:repr(name)),patch.object(rights.frappe.db,'sql',return_value=[row]):
                self.assertEqual(rights.query('Cipher Document Revision'),'1=1');s.denied.add(policy['evidence_artifact']['revision_id']);self.assertIn(doc,rights.query('Cipher Document Revision'))
            with patch.object(rights.frappe.db,'exists',create=True,return_value=True),patch.object(rights.frappe.db,'sql',return_value=[row]*501):self.assertEqual(rights.query('Cipher Document Revision'),'1=0')
    def test_permission_evidence_cycles_are_refused_without_an_effect(self):
        with fixture() as (s,r,repo,rights,service,gov):
            a=add_source(s);b=add_source(s);adoc=s.documents[a['revision_id']]['document_id'];bdoc=s.documents[b['revision_id']]['document_id'];service.set_rights('C','P',uid(),adoc,None,permission(s,evidence_artifact={k:b[k] for k in ('revision_id','source_sha256')}));before=deepcopy(s.rows)
            with self.assertRaises(DomainError):service.set_rights('C','P',uid(),bdoc,None,permission(s,evidence_artifact={k:a[k] for k in ('revision_id','source_sha256')}))
            self.assertEqual(s.rows,before)
    def test_existing_engineering_distribution_honors_a_present_content_permission(self):
        from cipher_aec.tests.test_engineering import question,answer,official
        with fixture() as (s,r,repo,rights,service,gov):
            eng=importlib.import_module('cipher_aec.engineering.service');egov=importlib.import_module('cipher_aec.engineering.governance');s.duties[s.actor.person_id]|={'engineering.read','engineering.write','engineering.distribute'};ref=source(s,service);drawing={**ref,'page':1,'locator':'Original drawing detail'};created=eng.create_rfi('C','P',uid(),question(),[],[drawing]);response=eng.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[])['response'];checker=person(s,r,'engineering-reviewer');s.duties[checker.person_id].add('engineering.read');fact=official(s,eng,egov,'response',response,checker);transmittal=eng.create_transmittal('C','P',uid(),'official_response',fact['id'],digest(fact),[checker.user],'Internal technical issue','')['transmittal'];self.assertEqual(egov.authorize_subject(kind='transmittal',actor=s.actor,company='C',project='P',subject_id=transmittal['id'],phase='request')['id'],transmittal['id']);doc=s.documents[ref['revision_id']]['document_id'];policy=rights.current(doc);service.set_rights('C','P',uid(),doc,digest(policy),permission(s,distribute_allowed=False))
            with self.assertRaises(DomainError) as error:egov.authorize_subject(kind='transmittal',actor=s.actor,company='C',project='P',subject_id=transmittal['id'],phase='request')
            self.assertEqual(error.exception.code,'source_rights_denied')
    def test_real_original_utf8_bytes_preview_search_and_no_policy_compatibility(self):
        from cipher_aec.documents.core import DocumentService
        from cipher_aec.documents.storage import LocalArtifactStorage
        from cipher_aec.tests.test_documents import MemoryMetadata
        with fixture() as (s,r,repo,rights,service,gov),tempfile.TemporaryDirectory() as folder:
            metadata=MemoryMetadata();core=DocumentService(metadata,LocalArtifactStorage(folder),lambda *a:None,allow_unscanned=True,source_authorize=lambda row,lock=False:rights.authorize(row,s.actor,lock=lock))
            original=b'Exact executed clause: retain this wording.';created=core.upload(company='C',project='P',title='Original contract',filename='original.txt',content=original,byte_length=len(original),sha256=hashlib.sha256(original).hexdigest());rid=created['revision']['id'];doc=created['document']['id'];self.assertEqual(core.download('C',rid)[1],original)
            # The real native repository locator includes document before bytes/text.
            metadata.revision_scope=metadata.revision_locator
            declared=permission(s);policy={'id':uid(),'company':'C','project':'P','scope_type':'Project','parent_id':doc,'revision_number':1,**declared,'evidence_artifact':service.sources.resolve_artifacts('C','P',[declared['evidence_artifact']],s.actor)[0]};s.rows['rights',policy['id']]=policy
            self.assertIn('retain this wording',core.preview('C',rid)['text']);successor=b'New source wording.';core.upload(company='C',project='P',title='Updated',filename='updated.txt',content=successor,byte_length=len(successor),sha256=hashlib.sha256(successor).hexdigest(),document_id=doc,expected_revision=1);self.assertEqual(core.download('C',rid)[1],original)
            policy2={**policy,'id':uid(),'revision_number':2,'read_allowed':False};s.rows['rights',policy2['id']]=policy2
            for call in (lambda:core.download('C',rid),lambda:core.preview('C',rid),lambda:core.detail('C',doc)):
                with self.assertRaises(DomainError):call()
            self.assertEqual(core.search('C','P','wording'),[]);self.assertEqual(core.list('C','P'),[])

if __name__=='__main__':unittest.main()
