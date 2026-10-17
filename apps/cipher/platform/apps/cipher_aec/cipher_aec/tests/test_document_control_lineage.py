"""Affected DOC03 lineage host tests; persistence and sessions are explicit doubles."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib,importlib,json,sys
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_document_control import fixture,source,library,person,authorize,permission
from cipher_aec.tests.test_engineering import uid
from cipher_aec.tests.test_document_control_contracts import validate

@contextmanager
def lineage():
    names=['cipher_aec.document_control.'+n for n in ('clauses','locking','scopes')]
    previous={n:sys.modules.pop(n) for n in names if n in sys.modules}
    try:
        with fixture() as (s,r,repo,rights,service,gov):
            clauses=importlib.import_module(names[0]);s.targets={}
            def target(company,project,kind,name,actor,lock=False):
                service.require_project(company,project,ability='document.read',actor=actor,lock=lock)
                if name not in s.targets or name in s.denied:raise DomainError('not_found','Exact target unavailable',404)
                return deepcopy(s.targets[name])
            with patch.object(clauses,'target_record',target):yield s,r,repo,rights,service,gov,clauses
    finally:
        for n in names:
            removed=sys.modules.pop(n,None);parent=sys.modules.get(n.rsplit('.',1)[0]);attr=n.rsplit('.',1)[1]
            if parent is not None and getattr(parent,attr,None) is removed:delattr(parent,attr)
        sys.modules.update(previous)
        for n,v in previous.items():setattr(sys.modules[n.rsplit('.',1)[0]],n.rsplit('.',1)[1],v)

def original(s,r,service,gov,clauses):
    ref=source(s,service,extracted=True);created,_=library(s,service,ref)
    request=service.create_adoption('C','P',uid(),created['library_revision']['id'],digest(created['library_revision']),{'purpose':'Exact clause adoption','target_locator':'Section 3','change_reason':'Independent reference'})['adoption_request'];checker=person(s,r,'checker');adoption=authorize(s,r,gov,'adoption_request',request,checker)
    targetid=source(s,service,extracted=True)['revision_id'];s.targets[targetid]={'kind':'document_revision','id':targetid,'record_digest':digest({'exact_target':targetid}),'parent_id':uid(),'company':'C','project':'P','scope_type':'Project'}
    target={k:s.targets[targetid][k] for k in ('kind','id','record_digest')};target['locator']='Clause 3.1'
    quote={'revision_id':ref['revision_id'],'source_sha256':ref['source_sha256'],'page':1,'excerpt_sha256':hashlib.sha256(b'Exact original specification').hexdigest(),'start':6,'end':28}
    use=clauses.create_clause_use('C','P',uid(),adoption['id'],digest(adoption),quote,target,'Record exact clause lineage')['clause_use']
    return use,adoption,created,checker

class ClauseLineageTests(unittest.TestCase):
    def test_exact_original_and_successor_redlines_and_independent_relationship_never_edit_target(self):
        with lineage() as (s,r,repo,rights,service,gov,c):
            use,adoption,created,checker=original(s,r,service,gov,c);before=deepcopy(s.targets)
            redline=c.create_redline('C','P',uid(),use['id'],digest(use),None,'Proposed reviewed specification','Explicit proposed text')['redline']
            applied=authorize(s,r,gov,'redline',redline,checker)
            self.assertEqual(applied['status'],'approved_relationship');self.assertFalse(applied['target_changed']);self.assertFalse(applied['commercial_execution']);self.assertEqual(s.targets,before)
            nextline=c.create_redline('C','P',uid(),use['id'],digest(use),digest(redline),'Second proposed wording','Retain predecessor')['redline']
            self.assertEqual(nextline['predecessor'],redline['id']);self.assertEqual(nextline['revision_number'],2);self.assertEqual(nextline['original_text'],'original specification');self.assertEqual(service.read('clause_application',applied['id'],'C','P',s.actor),applied)
            for kind,row in [('clause_use',use),('redline',redline),('redline',nextline),('clause_application',applied)]:validate('DcGetResponse',service.get_record('C','P',kind,row['id']))
            manifest=json.loads(s.packets[applied['packet_id']].manifest_json)['domain'];self.assertFalse(manifest['effect']['target_changed']);self.assertNotEqual(s.packets[applied['packet_id']].manifest_hash,digest(manifest))
    def test_exact_source_range_and_immutable_target_digest_required_before_effect(self):
        with lineage() as (s,r,repo,rights,service,gov,c):
            use,adoption,_,_=original(s,r,service,gov,c);before=deepcopy(s.rows)
            for quote,target in [({**use['source_clause']['reference'],'end':10000},use['target']),(use['source_clause']['reference'],{**use['target'],'record_digest':'0'*64}),({**use['source_clause']['reference'],'revision_id':uid()},use['target'])]:
                with self.subTest(quote=quote,target=target),self.assertRaises(DomainError):c.create_clause_use('C','P',uid(),adoption['id'],digest(adoption),quote,target,'Bad join')
            self.assertEqual(s.rows,before)
    def test_source_update_and_newer_library_do_not_rewrite_referenced_text_or_old_redline_receipt(self):
        with lineage() as (s,r,repo,rights,service,gov,c):
            use,_,created,_=original(s,r,service,gov,c);op=uid();redline=c.create_redline('C','P',op,use['id'],digest(use),None,'First proposal','Original draft')['redline'];saved=deepcopy(redline)
            service.revise_library('C','P',uid(),created['library']['id'],digest(created['library']),{**created['library_revision']['definition'],'change_reason':'Updated source'},source(s,service,extracted=True))
            c.create_redline('C','P',uid(),use['id'],digest(use),digest(redline),'Later proposal','Successor')
            replay=c.create_redline('C','P',op,use['id'],digest(use),None,'First proposal','Original draft');self.assertTrue(replay['operation']['replayed']);self.assertEqual(replay['redline'],saved);self.assertEqual(service.read('clause_use',use['id'],'C','P',s.actor)['source_clause'],use['source_clause'])
    def test_independent_person_latest_proposal_and_original_target_authority_are_required(self):
        with lineage() as (s,r,repo,rights,service,gov,c):
            use,_,_,checker=original(s,r,service,gov,c);redline=c.create_redline('C','P',uid(),use['id'],digest(use),None,'First proposal','Reason')['redline']
            with self.assertRaises(DomainError) as err:gov.authorize_subject(kind='redline',actor=s.actor,company='C',project='P',subject_id=redline['id'],phase='review')
            self.assertEqual(err.exception.code,'independent_document_review')
            c.create_redline('C','P',uid(),use['id'],digest(use),digest(redline),'Second proposal','New reason')
            with self.assertRaises(DomainError) as err:gov.authorize_subject(kind='redline',actor=checker,company='C',project='P',subject_id=redline['id'],phase='review')
            self.assertEqual(err.exception.code,'redline_superseded')
            s.denied.add(use['target']['id'])
            with self.assertRaises(DomainError):service.read('redline',redline['id'],'C','P',s.actor)
    def test_current_original_rights_and_closed_project_block_new_work_but_not_immutable_history(self):
        with lineage() as (s,r,repo,rights,service,gov,c):
            use,_,_,_=original(s,r,service,gov,c);s.project_status='Completed'
            self.assertEqual(service.read('clause_use',use['id'],'C','P',s.actor),use)
            with self.assertRaises(DomainError) as err:c.create_redline('C','P',uid(),use['id'],digest(use),None,'Closed proposal','Reason')
            self.assertEqual(err.exception.code,'project_closed');s.project_status='Open';doc=use['artifacts'][0]['document_id'];policy=rights.current(doc);service.set_rights('C','P',uid(),doc,digest(policy),permission(s,read_allowed=False))
            with self.assertRaises(DomainError):service.read('clause_use',use['id'],'C','P',s.actor)
    def test_late_receipt_failure_rolls_back_proposed_revision_and_history(self):
        with lineage() as (s,r,repo,rights,service,gov,c):
            use,_,_,_=original(s,r,service,gov,c);before=deepcopy((s.rows,s.events,s.receipts));s.failed_receipt=True
            with self.assertRaises(RuntimeError):c.create_redline('C','P',uid(),use['id'],digest(use),None,'Failed proposal','Reason')
            self.assertEqual((s.rows,s.events,s.receipts),before)

class ClauseLockAndWireTests(unittest.TestCase):
    def test_full_original_source_and_rights_evidence_union_precedes_first_master_and_locks(self):
        from contextlib import nullcontext
        from types import ModuleType
        with lineage() as (s,r,repo,rights,service,gov,c):
            use,_,_,_=original(s,r,service,gov,c);locking=importlib.import_module('cipher_aec.document_control.locking');scopes=importlib.import_module('cipher_aec.document_control.scopes');target_id=source(s,service,extracted=True)['revision_id'];target={'kind':'document_revision','id':target_id};observed=[]
            def metadata(name):
                if name not in {v['document_id'] for v in s.documents.values()}:raise DomainError('not_found','scope',404)
                return SimpleNamespace(company='C',project='P',scope_type='Project')
            def native(kind,name,actor,lock=False):observed.append(('master',kind,name))
            units=ModuleType('units');units.qualified=lambda name,**kw:observed.append(('master','unit',name))
            natives=ModuleType('native');natives.require_native=native
            provenance=ModuleType('provenance');provenance.MAX_NODES=128;provenance.prelocked=lambda *a,**kw:nullcontext();provenance.source_plan=lambda *a,**kw:{};provenance.binding=lambda *a:None
            with patch.dict(sys.modules,{'cipher_aec.estimating.units':units,'cipher_aec.commercial.native':natives,'cipher_aec.documents.provenance':provenance}),patch.object(service.FrappeDocumentRepository,'document_scope',lambda _,name:metadata(name),create=True),patch.object(locking,'target_plan',lambda *a,**kw:{'unit_ids':['u'],'currencies':['USD'],'native_refs':[{'doctype':'Customer','name':'customer'}]}),patch.object(locking,'require_project',lambda *a,**kw:observed.append(('scope',a[1]))),patch.object(scopes,'document',lambda name,*a,**kw:observed.append(('document',name))):
                context=locking.DocumentContext('C','P',[('clause_use',use['id'])],[target]);context.prelock(s.actor);plan=deepcopy(context.initial)
                self.assertEqual(set(plan['documents']),rights.document_plan({use['artifacts'][0]['document_id'],s.documents[use['target']['id']]['document_id'],s.documents[target_id]['document_id']}))
                with context.hold(s.actor):observed.append(('effect',))
                first_master=next(i for i,row in enumerate(observed) if row[0]=='master');self.assertTrue(any(row[0]=='scope' for row in observed[:first_master]));self.assertEqual([row[1] for row in observed if row[0]=='document'],sorted(plan['documents']))
                self.assertEqual(observed[-1],('effect',))
    def test_dependency_growth_after_scope_discovery_fails_before_first_source_lock(self):
        with lineage() as (s,r,repo,rights,service,gov,c):
            locking=importlib.import_module('cipher_aec.document_control.locking');context=locking.DocumentContext('C','P');initial={'scopes':[('Project','P')],'documents':{},'native':{}}
            with patch.object(context,'discover',side_effect=[deepcopy(initial),{**initial,'documents':{'new':('Project','P')}}]),patch.object(locking,'require_project',lambda *a,**kw:None):
                context.prelock(s.actor)
                with self.assertRaises(DomainError) as err:
                    with context.hold(s.actor):self.fail('No effect may run')
                self.assertEqual(err.exception.code,'document_sources_changed')
    def test_literal_redline_packet_and_effect_are_valid_with_opaque_full_manifest_hash(self):
        from cipher_aec.tests.test_document_control_contracts import CORE
        with lineage() as (s,r,repo,rights,service,gov,c):
            use,_,_,checker=original(s,r,service,gov,c);value=c.create_redline('C','P',uid(),use['id'],digest(use),None,'Proposed wording','Explicit reason')['redline'];fact=authorize(s,r,gov,'redline',value,checker);native=s.packets[fact['packet_id']];manifest=json.loads(native.manifest_json)['domain']
            packet={'schema':'cipher.document.approval.v1','id':native.name,'company':'C','project':'P','action':r.ACTIONS['redline'],'subject':{'id':value['id'],'type':r.KINDS['redline'],'label':'Proposed clause relationship'},'requester':{'id':s.actor.person_id,'display_name':'Author'},'created_at':'2026-10-17T00:00:00Z','expires_at':'2026-10-18T00:00:00Z','manifest_hash':native.manifest_hash,'source_version':digest(value),'policy':{'id':'policy','label':'Independent relationship','synthetic':True},'state':'Consumed','decisions':[],'actions':{'can_decide':False,'can_execute':False,'can_withdraw':False,'disabled_reason':'Consumed'},'review_manifest':manifest}
            validate('ApprovalPacket',packet,CORE);validate('DocumentApprovalExecutionResponse',{'packet':packet,'effect':{'clause_application':fact},'operation':{'id':uid(),'status':'succeeded','replayed':False}},CORE)
            for key,replacement in [('subject_kind','adoption_request'),('target_changed',True),('commercial_execution',True)]:
                bad=deepcopy(packet);bad['review_manifest']['effect'][key]=replacement
                with self.subTest(key=key),self.assertRaises(Exception):validate('ApprovalPacket',bad,CORE)
