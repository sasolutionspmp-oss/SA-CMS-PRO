"""Company-owned reusable-library host workflows, with explicit native/session doubles."""
from contextlib import contextmanager,ExitStack,nullcontext
from copy import deepcopy
import importlib,json,hashlib,sys
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_document_control import fixture,person,permission,authorize
from cipher_aec.tests.test_engineering import add_source,uid

@contextmanager
def shared_fixture():
    with fixture() as (s,r,repo,rights,service,gov):
        shared=importlib.import_module('cipher_aec.document_control.shared');locking=importlib.import_module('cipher_aec.document_control.locking');scopes=importlib.import_module('cipher_aec.document_control.scopes');commands=sys.modules['cipher_aec.governance.commands'];history=sys.modules['cipher_aec.governance.history'];documents=sys.modules['cipher_aec.documents.service'];s.company_duties={s.actor.person_id:{r.READ,r.WRITE,r.MANAGE,'company.read','document.read','document.write'}};s.project_duties={}
        def require(company,project,ability='project.read',actor=None,lock=False):
            actor=actor or s.actor
            if company!='C' or project not in ('P','SOURCE'):raise DomainError('not_found','scope',404)
            duties=s.duties.get(actor.person_id,set()) if project=='P' else s.project_duties.get(actor.person_id,set())
            if ability not in duties:raise DomainError('capability_denied','Project duty',403)
            return SimpleNamespace(status=s.project_status)
        def company(company,ability='company.read',actor=None,lock=False):
            actor=actor or s.actor
            if company!='C' or ability not in s.company_duties.get(actor.person_id,set()):raise DomainError('capability_denied','Company duty',403)
            return SimpleNamespace(name=company)
        def metadata(revision):
            row=s.documents[revision];return SimpleNamespace(name=revision,company='C',project=row.get('project','P'),scope_type=row.get('scope_type','Project'),document=row['document_id'])
        def document(name,company_name,scope_type,project,actor,lock=False):
            scopes.require(company_name,scope_type,project,actor,'document.read',lock=lock);rows=[v for v in s.documents.values() if v['document_id']==name]
            if not rows:raise DomainError('not_found','source',404)
            row=max(rows,key=lambda v:v['revision_number'])
            if row.get('scope_type','Project')!=scope_type or row.get('project','P')!=project:raise DomainError('not_found','wrong original scope',404)
            return SimpleNamespace(name=name,company='C',project=project,scope_type=scope_type,current_revision=row['revision_id'])
        def source_reference(company_name,project,revision,page,actor=None,lock=False,scope_type='Project'):
            actor=actor or s.actor;scopes.require(company_name,scope_type,project,actor,'document.read',lock=lock);row=s.documents.get(revision)
            if row is None or revision in s.denied or row.get('scope_type','Project')!=scope_type or row.get('project','P')!=project:raise DomainError('not_found','Original source denied',404)
            rights.require(row['document_id'],'C',project,'read',actor,lock=lock,required=False,scope_type=scope_type)
            value=deepcopy(row);value['page']=page
            if not 1<=page<=value['page_count']:raise DomainError('invalid_page','page',422)
            return value
        def company_command(**kw):
            company(kw['company'],ability=kw['ability'],actor=s.actor);key=(s.actor.person_id,kw['operation_id']);request=digest({'scope_type':'Company','company':kw['company'],'project':None,'command':kw['command'],'payload':kw['payload']})
            if key in s.receipts:
                previous,result=s.receipts[key]
                if previous!=request:raise DomainError('operation_conflict','Original request differs',409)
                shared.authorize_receipt(s.actor,'C',result,lock=True);return {**deepcopy(result),'operation':{'id':key[1],'status':'succeeded','replayed':True}}
            before=deepcopy((s.rows,s.events,s.receipts))
            try:
                kw['guard'](s.actor,None);result=kw['effect'](s.actor,None)
                if s.failed_receipt:raise RuntimeError('late Company receipt failure')
                s.receipts[key]=(request,deepcopy(result));return {**result,'operation':{'id':key[1],'status':'succeeded','replayed':False}}
            except Exception:s.rows,s.events,s.receipts=before;raise
        with ExitStack() as stack:
            for module,name,value in [(locking.DocumentContext,'hold',lambda *a,**kw:nullcontext()),(service,'require_project',require),(gov,'require_project',require),(shared,'require_project',require),(shared,'require_company',company),(scopes,'require_project',require),(scopes,'require_company',company),(scopes,'document',document),(service,'_document',lambda name,c,p,a,lock=False:document(name,c,'Project',p,a,lock)),(service.FrappeDocumentRepository,'revision_scope',lambda _,name:metadata(name)),(service.FrappeDocumentRepository,'document_scope',lambda _,name:next(SimpleNamespace(name=name,company='C',scope_type=v.get('scope_type','Project'),project=v.get('project','P')) for v in s.documents.values() if v['document_id']==name)),(documents,'source_reference',source_reference),(documents,'company_source_reference',lambda c,rev,page,actor=None,lock=False:source_reference(c,None,rev,page,actor,lock,scope_type='Company')),(service.sources,'source_reference',source_reference),(commands,'run_company_command',company_command),(history,'append_company_event',lambda **kw:s.events.append(kw) or uid())]:stack.enter_context(patch.object(module,name,value,create=True))
            yield s,r,repo,rights,service,gov,shared

def scoped_source(s,shared,scope='Company',project=None):
    ref=add_source(s);s.documents[ref['revision_id']].update(scope_type=scope,project=project);evidence=add_source(s);s.documents[evidence['revision_id']].update(scope_type=scope,project=project)
    definition={'ingest_allowed':True,'read_allowed':True,'distribute_allowed':True,'rights_basis':'Authored internal reuse declaration, not a verified license','rights_holder':'Synthetic holder','allowed_purpose':'Internal scoped adoption and distribution','restriction':'No external transport','valid_from':None,'valid_until':None,'evidence_artifact':{k:evidence[k] for k in ('revision_id','source_sha256')}}
    if scope=='Company':shared.set_rights('C',uid(),s.documents[ref['revision_id']]['document_id'],None,definition)
    return {k:ref[k] for k in ('revision_id','source_sha256')},definition

def company_library(s,shared):
    ref,permission=scoped_source(s,shared);definition={'title':'Reusable clause library','category':'contract_clause','discipline':'Commercial','ownership':'Explicit Company owner','tags':['retained'],'change_reason':'Original'}
    return shared.library('C',uid(),definition,ref),ref,definition,permission

class SharedLibraryTests(unittest.TestCase):
    def test_company_library_adoption_issue_and_original_scope_are_exact(self):
        with shared_fixture() as (s,r,repo,rights,service,gov,shared):
            created,ref,definition,_=company_library(s,shared);original=created['library_revision'];request=shared.create_adoption('C','P',uid(),{'scope_type':'Company','project':None},original['id'],digest(original),{'purpose':'Reuse retained Company wording','target_locator':'Project clause 3','change_reason':'Independent adoption'})['adoption_request'];checker=person(s,r,'checker');s.company_duties[checker.person_id]={r.READ,'company.read','document.read'};adoption=authorize(s,r,gov,'adoption_request',request,checker)
            self.assertEqual(request['library_scope'],{'scope_type':'Company','project':None});self.assertEqual(service.get_record('C','P','adoption',adoption['id'])['record'],adoption);self.assertEqual(adoption['artifacts'],original['artifacts']);issued=service.create_issue_set('C','P',uid(),{'title':'Reusable adopted source','purpose':'Retain exact source','issue_purpose':'information'},[],[{'id':adoption['id'],'record_digest':digest(adoption)}])['issue_set'];self.assertEqual(issued['artifacts'],original['artifacts'])
    def test_origin_company_and_target_project_permissions_are_independent(self):
        with shared_fixture() as (s,r,repo,rights,service,gov,shared):
            created,_,_,_=company_library(s,shared);original=created['library_revision'];s.company_duties[s.actor.person_id].remove('document.read')
            with self.assertRaises(DomainError):shared.create_adoption('C','P',uid(),{'scope_type':'Company','project':None},original['id'],digest(original),{'purpose':'Use','target_locator':'Section 3','change_reason':'Exact'})
            s.company_duties[s.actor.person_id].add('document.read');s.duties[s.actor.person_id].remove(r.ADOPT)
            with self.assertRaises(DomainError):shared.create_adoption('C','P',uid(),{'scope_type':'Company','project':None},original['id'],digest(original),{'purpose':'Use','target_locator':'Section 3','change_reason':'Exact'})
    def test_current_origin_rights_and_original_evidence_revocation_hide_adoption(self):
        with shared_fixture() as (s,r,repo,rights,service,gov,shared):
            created,ref,_,definition=company_library(s,shared);request=shared.create_adoption('C','P',uid(),{'scope_type':'Company','project':None},created['library_revision']['id'],digest(created['library_revision']),{'purpose':'Use','target_locator':'Section','change_reason':'Exact'})['adoption_request'];before=deepcopy(request);s.denied.add(definition['evidence_artifact']['revision_id'])
            with self.assertRaises(DomainError):service.read('adoption_request',request['id'],'C','P',s.actor)
            self.assertEqual(repo.raw('adoption_request',request['id']),before)
    def test_company_source_update_preserves_exact_original_and_receipt_after_new_library_head(self):
        with shared_fixture() as (s,r,repo,rights,service,gov,shared):
            created,ref,definition,_=company_library(s,shared);original=created['library_revision'];op=uid();request=shared.create_adoption('C','P',op,{'scope_type':'Company','project':None},original['id'],digest(original),{'purpose':'Use','target_locator':'Section','change_reason':'Exact'})['adoption_request'];newref,_=scoped_source(s,shared);new=shared.library('C',uid(),{**definition,'change_reason':'Explicit later source'},newref,created['library']['id'],digest(created['library']))
            self.assertEqual(service.read('adoption_request',request['id'],'C','P',s.actor),request);self.assertFalse(service.get_record('C','P','adoption_request',request['id'])['library_current']);self.assertEqual(repo.raw('library_revision',original['id']),original)
    def test_new_unavailable_library_head_must_not_deny_still_authorized_original_adoption(self):
        with shared_fixture() as (s,r,repo,rights,service,gov,shared):
            created,ref,definition,_=company_library(s,shared);request=shared.create_adoption('C','P',uid(),{'scope_type':'Company','project':None},created['library_revision']['id'],digest(created['library_revision']),{'purpose':'Use','target_locator':'Section','change_reason':'Original'})['adoption_request'];newref,_=scoped_source(s,shared);shared.library('C',uid(),{**definition,'change_reason':'Private newer source'},newref,created['library']['id'],digest(created['library']));s.denied.add(newref['revision_id'])
            self.assertEqual(service.get_record('C','P','adoption_request',request['id'])['record'],request)
    def test_explicit_scope_and_same_owner_required_and_late_receipt_rolls_back(self):
        with shared_fixture() as (s,r,repo,rights,service,gov,shared):
            created,ref,definition,_=company_library(s,shared);before=deepcopy((s.rows,s.events,s.receipts));s.failed_receipt=True
            with self.assertRaises(RuntimeError):shared.library('C',uid(),definition,ref)
            self.assertEqual((s.rows,s.events,s.receipts),before)
            for scope in [{'scope_type':'Project','project':None},{'scope_type':'Company','project':'P'}]:
                with self.assertRaises(DomainError):shared.origin(scope)
            with self.assertRaises(DomainError):shared.get_record('OTHER','library_revision',created['library_revision']['id'])

class SharedLibraryRecoveryTests(unittest.TestCase):
    def test_company_create_receipt_replays_exact_original_after_successor_and_revocation_denies(self):
        with shared_fixture() as (s,r,repo,rights,service,gov,shared):
            ref,_=scoped_source(s,shared);definition={'title':'Original scoped library','category':'specification','discipline':'Civil','ownership':'Company author','tags':[],'change_reason':'Initial'};op=uid();original=shared.library('C',op,definition,ref);before=deepcopy(original);successor_ref,_=scoped_source(s,shared);shared.library('C',uid(),{**definition,'change_reason':'Successor'},successor_ref,original['library']['id'],digest(original['library']));rows=deepcopy(s.rows)
            replay=shared.library('C',op,definition,ref);self.assertTrue(replay['operation']['replayed']);self.assertEqual(replay['library'],before['library']);self.assertEqual(replay['library_revision'],before['library_revision']);self.assertEqual(s.rows,rows)
            with self.assertRaises(DomainError):shared.library('C',op,{**definition,'title':'Different input'},ref)
            s.company_duties[s.actor.person_id].remove('document.read')
            with self.assertRaises(DomainError):shared.library('C',op,definition,ref)
            self.assertEqual(s.rows,rows)
    def test_project_owned_library_reuse_requires_both_original_and_target_scope(self):
        with shared_fixture() as (s,r,repo,rights,service,gov,shared):
            s.project_duties[s.actor.person_id]=set(s.duties[s.actor.person_id]);ref,permission=scoped_source(s,shared,scope='Project',project='SOURCE');service.set_rights('C','SOURCE',uid(),s.documents[ref['revision_id']]['document_id'],None,permission);created=service.create_library('C','SOURCE',uid(),{'title':'Origin Project library','category':'reference','discipline':'Civil','ownership':'Company-owned Project source','tags':[],'change_reason':'Initial'},ref);revision=created['library_revision'];op=uid();definition={'purpose':'Reuse exact source','target_locator':'Target Project section','change_reason':'Explicit two-scope adoption'}
            request=shared.create_adoption('C','P',op,{'scope_type':'Project','project':'SOURCE'},revision['id'],digest(revision),definition)['adoption_request'];self.assertEqual(request['library_scope']['project'],'SOURCE');self.assertEqual(request['artifacts'],revision['artifacts'])
            s.project_duties[s.actor.person_id].remove('document.read')
            with self.assertRaises(DomainError):service.read('adoption_request',request['id'],'C','P',s.actor)
            s.project_duties[s.actor.person_id].add('document.read');s.duties[s.actor.person_id].remove(r.ADOPT)
            with self.assertRaises(DomainError):shared.create_adoption('C','P',uid(),{'scope_type':'Project','project':'SOURCE'},revision['id'],digest(revision),definition)

class SharedWireContractTests(unittest.TestCase):
    def test_company_records_and_independent_shared_adoption_packet_match_closed_wire(self):
        from cipher_aec.tests.test_document_control_contracts import validate
        from pathlib import Path
        core=json.loads((Path(__file__).parents[1]/'api/schema.json').read_text())
        with shared_fixture() as (s,r,repo,rights,service,gov,shared):
            created,ref,_,_=company_library(s,shared)
            for kind in ['library','library_revision']:
                validate('DcCompanyGetResponse',shared.get_record('C',kind,created[kind]['id']))
            result=shared.create_adoption('C','P',uid(),{'scope_type':'Company','project':None},created['library_revision']['id'],digest(created['library_revision']),{'purpose':'Use','target_locator':'Project section','change_reason':'Independent exact adoption'});validate('DcCreateSharedAdoptionResponse',result);value=result['adoption_request'];validate('DcGetResponse',service.get_record('C','P','adoption_request',value['id']))
            checker=person(s,r,'checker');s.company_duties[checker.person_id]={r.READ,'company.read','document.read'};fact=authorize(s,r,gov,'adoption_request',value,checker);native=s.packets[fact['packet_id']];manifest=json.loads(native.manifest_json)['domain'];packet={'schema':'cipher.document.approval.v1','id':native.name,'company':'C','project':'P','action':r.ACTIONS['adoption_request'],'subject':{'id':value['id'],'type':r.KINDS['adoption_request'],'label':'Exact shared adoption'},'requester':{'id':s.actor.person_id,'display_name':'Author'},'created_at':'2026-10-17T00:00:00Z','expires_at':'2026-10-18T00:00:00Z','manifest_hash':native.manifest_hash,'source_version':digest(value),'policy':{'id':'policy','label':'Synthetic exact review','synthetic':True},'state':'Consumed','decisions':[],'actions':{'can_decide':False,'can_execute':False,'can_withdraw':False,'disabled_reason':'Consumed'},'review_manifest':manifest}
            validate('DocumentApprovalPacket',packet,core);validate('DocumentApprovalExecutionResponse',{'packet':packet,'effect':{'adoption':fact},'operation':{'id':uid(),'status':'succeeded','replayed':False}},core)
            tampered=deepcopy(packet);tampered['review_manifest']['effect']['library_scope']={'scope_type':'Company','project':'P'}
            with self.assertRaises(Exception):validate('DocumentApprovalPacket',tampered,core)

class CompanyPagingAuthorityTests(unittest.TestCase):
    def test_cursor_binds_company_duties_instead_of_unrelated_project_duties(self):
        from cipher_aec.api import paging
        with shared_fixture() as (s,r,repo,rights,service,gov,shared):
            one,_,_,_=company_library(s,shared);two,_,_,_=company_library(s,shared);rows=[SimpleNamespace(name=x['library']['id'],creation='2026-10-17 00:00:00') for x in (one,two)];context=sys.modules['cipher_aec.governance.context'];fingerprint=lambda actor,company:digest(sorted(s.company_duties[actor.person_id]))
            with patch.object(context,'company_authority_fingerprint',fingerprint,create=True),patch.object(repo,'candidates',return_value=rows),patch.object(shared,'signing_secret',return_value='fixed-synthetic-cursor-key'),patch.object(paging,'signing_secret',return_value='fixed-synthetic-cursor-key'):
                first=shared.list_records('C','library',limit=1);self.assertIsNotNone(first['next_cursor']);s.company_duties[s.actor.person_id].remove(r.WRITE)
                with self.assertRaises(DomainError) as error:shared.list_records('C','library',limit=1,cursor=first['next_cursor'])
                self.assertEqual(error.exception.code,'invalid_cursor')
