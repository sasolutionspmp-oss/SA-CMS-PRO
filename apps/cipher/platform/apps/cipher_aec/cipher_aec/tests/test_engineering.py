"""Host ENG-01 fixtures exercise real services; no native database claim."""
from contextlib import contextmanager
from copy import deepcopy
import importlib
import importlib.util
import json
import hashlib
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError

ROOT=Path(__file__).parents[1]
def uid():return str(uuid4())
def module(name,**values):
    value=ModuleType(name);value.__dict__.update(values);return value

@contextmanager
def fixtures():
    actor=SimpleNamespace(user='author@example.invalid',person_id=uid())
    state=SimpleNamespace(actor=actor,rows={},denied=set(),events=[],receipts={},duties={},users={actor.user:actor},documents={},packets={},decisions={},consumptions={},failed_receipt=False,project_status="Open",approval_effect=None)
    def require(company,project,ability='project.read',actor=None,lock=False):
        actor=actor or state.actor
        if company!='C' or project!='P':raise DomainError('not_found','scope',404)
        if ability not in state.duties.get(actor.person_id,{'project.read','engineering.read','engineering.write','engineering.distribute','document.read'}):raise DomainError('capability_denied','duty',403)
        return SimpleNamespace(status=state.project_status)
    def current(user=None,lock=False):return state.users[user] if user else state.actor
    @contextmanager
    def trusted():yield
    def source_verify(company,project,value,actor,lock=False):
        require(company,project,actor=actor)
        if any(r['revision_id'] in state.denied for r in value.get('source_citations',[])+value.get('artifacts',[])):raise DomainError('source_denied','source',403)
    def raw(kind,identifier,lock=False):
        try:return deepcopy(state.rows[kind,identifier])
        except KeyError:raise DomainError('not_found','record',404)
    def write(kind,value,old=None):
        if old is not None and raw(kind,value['id'])!=old:raise DomainError('stale','changed',412)
        state.rows[kind,value['id']]=deepcopy(value);return value
    def get_doc(doctype,name,**kwargs):
        return {'Cipher Approval Packet':state.packets,'Cipher Approval Decision':state.decisions}[doctype][name]
    def sql(query,args=(),**kwargs):
        if 'tabCipher Approval Consumption' in query:return [v for v in state.consumptions.values() if v.packet==args[0]]
        raise AssertionError(query)
    def source_reference(company,project,revision,page,actor=None,lock=False):
        require(company,project,'document.read',actor or state.actor)
        if revision in state.denied:raise DomainError('source_denied','source',403)
        value=deepcopy(state.documents[revision]);value.update(page=page)
        if not 1<=page<=value['page_count']:raise DomainError('invalid_page','page',422)
        return value
    def citation(company,revision,page,excerpt_sha256=None,actor=None):
        source=source_reference(company,'P',revision,page,actor)
        if source['extraction_status']!='ready':raise DomainError('text_unavailable','No extracted text',422)
        text='Exact original specification';checksum=hashlib.sha256(text.encode()).hexdigest()
        if checksum!=excerpt_sha256:raise DomainError('citation_changed','citation',412)
        return {'id':digest([revision,page,checksum]),'document_id':source['document_id'],'revision_id':revision,'document_title':'Specification','revision_number':source['revision_number'],'page':page,'page_label':str(page),'excerpt':text,'excerpt_sha256':checksum,'source_sha256':source['source_sha256']}
    def approval_effect(**kwargs):
        if state.approval_effect!=(kwargs['action'],kwargs['subject_id'],kwargs['packet_id']):raise DomainError('approval_effect_required','effect',403)
    mocks={
      'frappe':module('frappe',get_doc=get_doc,db=SimpleNamespace(sql=sql),conf={'encryption_key':'x'*32},DoesNotExistError=type('Missing',(Exception,),{})),
      'cipher_aec.governance.context':module('context',current_actor=current,require_project=require,require_company=lambda *a,**kw:None,authority_fingerprint=lambda *a:'duties',trusted_write=trusted,require_trusted_write=lambda:None),
      'cipher_aec.governance.commands':module('commands',run_command=lambda **kwargs:None),
      'cipher_aec.governance.history':module('history',append_event=lambda **kwargs:state.events.append(kwargs) or uid()),
      'cipher_aec.governance.approvals':module('approvals',require_approval_effect=approval_effect),
      'cipher_aec.documents.service':module('documents',source_reference=source_reference,get_citation=citation)}
    names=['cipher_aec.engineering.'+n for n in ('contracts','repository','sources','service','governance')]
    old={n:sys.modules.pop(n) for n in names if n in sys.modules}
    with patch.dict(sys.modules,mocks):
        rules=importlib.import_module(names[0]);repo=importlib.import_module(names[1]);sources=importlib.import_module(names[2]);service=importlib.import_module(names[3]);gov=importlib.import_module(names[4])
        state.verify=sources.verify
        with patch.object(repo,'raw',raw),patch.object(repo,'write',write),patch.object(repo,'number',lambda *a:'ENG-00001'),patch.object(repo,'official_for',lambda kind,subject_id,lock=False:next((deepcopy(v) for (k,_),v in state.rows.items() if k==kind and v.get('subject_id')==subject_id),None)),patch.object(sources,'verify',source_verify):
            def command(**kwargs):
                key=(state.actor.person_id,kwargs['operation_id']);request=digest({k:kwargs[k] for k in ('command','company','project','payload')})
                require(kwargs['company'],kwargs['project'],kwargs['ability'],state.actor)
                if key in state.receipts:
                    original=state.receipts[key]
                    if original[0]!=request:raise DomainError('operation_conflict','conflict',409)
                    service.authorize_receipt(state.actor,kwargs['company'],kwargs['project'],original[1]);result=deepcopy(original[1]);result['operation']={'id':key[1],'status':'succeeded','replayed':True};return result
                before=deepcopy((state.rows,state.events,state.receipts))
                try:
                    if kwargs.get('guard'):kwargs['guard'](state.actor,require('C','P'))
                    result=kwargs['effect'](state.actor,require('C','P'))
                    if state.failed_receipt:raise RuntimeError('fixture receipt failure')
                    state.receipts[key]=(request,deepcopy(result));result['operation']={'id':key[1],'status':'succeeded','replayed':False};return result
                except Exception:state.rows,state.events,state.receipts=before;raise
            with patch.object(service,'run_command',command):yield state,rules,repo,sources,service,gov
    for n in names:
        removed=sys.modules.pop(n,None);parentname,attribute=n.rsplit('.',1);parent=sys.modules.get(parentname)
        if parent is not None and getattr(parent,attribute,None) is removed:delattr(parent,attribute)
    sys.modules.update(old)
    for n,value in old.items():
        parentname,attribute=n.rsplit('.',1);setattr(sys.modules[parentname],attribute,value)

class EngineeringServiceTests(unittest.TestCase):
    def test_original_receipt_authorizes_original_sources_after_successor(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            old,new,headerid=uid(),uid(),uid()
            def rev(identifier,revision):return {'id':identifier,'company':'C','project':'P','scope_type':'Project','parent_id':headerid,'source_citations':[{'revision_id':revision}],'artifacts':[]}
            state.rows['rfi_revision',old]=rev(old,'original-source');state.rows['rfi_revision',new]=rev(new,'later-source')
            original={'author_person':state.actor.person_id,'author_user':state.actor.user,'number':'RFI-1','created_at':'2026-10-17T00:00:00Z','id':headerid,'company':'C','project':'P','scope_type':'Project','current_revision':old,'response_head':None,'official_response':None}
            state.rows['rfi',headerid]={**original,'current_revision':new};state.denied.add('later-source')
            service.authorize_receipt(state.actor,'C','P',{'rfi':original,'revision':state.rows['rfi_revision',old]})
            state.denied.add('original-source')
            with self.assertRaises(DomainError):service.authorize_receipt(state.actor,'C','P',{'rfi':original,'revision':state.rows['rfi_revision',old]})


def add_source(state,*,extracted=True):
    revision=uid();content=b'%PDF-1.7 exact vector drawing without text'
    state.documents[revision]={'document_id':uid(),'revision_id':revision,'revision_number':1,'source_sha256':hashlib.sha256(content).hexdigest(),'byte_length':len(content),'mime_type':'application/pdf','page_count':2,'page':1,'content':content,'extraction_status':'ready' if extracted else 'ocr_unavailable'}
    return {'revision_id':revision,'source_sha256':state.documents[revision]['source_sha256'],'page':1,'locator':'Grid A / Detail 2'}
def question(subject='Confirm bearing detail'):
    return {'subject':subject,'question':'Confirm the exact drawing detail.','responsible_users':[],'due_date':None,'location':'Pier 2','contract_citation_ids':[]}
def answer():return {'answer':'Use the stated technical detail.','potential_cost_impact':'Potential change; separate commercial review required.','potential_schedule_impact':''}
def submission(user):return {'title':'Bearing assembly','specification_section':'05 12 00','equipment_tag':'','required_date':None,'contractor':'Synthetic contractor','reviewer_user':user,'submission_standing':'submitted'}
def add_person(state,label):
    actor=SimpleNamespace(user=label+'@example.invalid',person_id=uid());state.users[actor.user]=actor;return actor

def official(state,service,gov,kind,value,checker=None):
    checker=checker or add_person(state,'checker')
    manifest=gov.approval_manifest(kind=kind,actor=state.actor,company='C',project='P',subject_id=value['id'],expected_version=digest(value),lock=True)
    packetid,decisionid=uid(),uid();outer={'domain':manifest}
    state.packets[packetid]=SimpleNamespace(name=packetid,company='C',project='P',scope_type='Project',action=gov.rules.ACTIONS[kind],subject_type=gov.rules.KINDS[kind],subject_id=value['id'],requester_person=state.actor.person_id,manifest_json=json.dumps(outer),manifest_hash=digest(outer))
    state.decisions[decisionid]=SimpleNamespace(name=decisionid,packet=packetid,decision='Grant',actor_person=checker.person_id,manifest_hash=digest(outer))
    state.approval_effect=(gov.rules.ACTIONS[kind],value['id'],packetid)
    result=gov.apply_authorization(kind=kind,actor=state.actor,company='C',project='P',manifest=manifest,packet_id=packetid,decision_id=decisionid,operation_id=uid())
    state.approval_effect=None
    state.consumptions[packetid]=SimpleNamespace(packet=packetid,decision=decisionid,company='C',project='P',scope_type='Project',actor_person=state.actor.person_id,result_hash=digest(result))
    return next(iter(result.values()))

class EngineeringHistoryTests(unittest.TestCase):
    def test_closed_event_authorizes_its_original_header_not_later_sources(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            eventreader=module('_engineering_history_fixture')
            exec(compile((ROOT/'governance/history_access.py').read_text(),str(ROOT/'governance/history_access.py'),'exec'),eventreader.__dict__)
            headerid,old,new=uid(),uid(),uid()
            def revision(identifier,source):return {'id':identifier,'company':'C','project':'P','scope_type':'Project','parent_id':headerid,'source_citations':[{'revision_id':source}],'artifacts':[]}
            state.rows['rfi_revision',old]=revision(old,'old');state.rows['rfi_revision',new]=revision(new,'new')
            snapshot={'id':headerid,'company':'C','project':'P','scope_type':'Project','author_person':state.actor.person_id,'author_user':state.actor.user,'number':'RFI-1','created_at':'2026-10-17T00:00:00Z','current_revision':old,'response_head':None,'official_response':None}
            state.rows['rfi',headerid]={**snapshot,'current_revision':new};state.denied.add('new')
            event=SimpleNamespace(subject_type='Cipher RFI',subject_id=headerid,event='engineering.rfi.closed',details_json=json.dumps({'record_digest':digest(snapshot),'header_snapshot':snapshot}))
            self.assertTrue(eventreader.readable(event,state.actor,'C','P'))
            state.denied.add('old');self.assertFalse(eventreader.readable(event,state.actor,'C','P'))


class EngineeringWorkflowTests(unittest.TestCase):
    def rfi(self,state,service):
        raw=add_source(state,extracted=False)
        return service.create_rfi('C','P',uid(),question(),[],[raw])
    def test_vector_drawing_rfi_without_text_and_exact_replay(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            raw=add_source(state,extracted=False);operation=uid()
            first=service.create_rfi('C','P',operation,question(),[],[raw])
            self.assertEqual(first['revision']['drawing_references'][0]['locator'],raw['locator'])
            state.verify('C','P',first['revision'],state.actor)
            second=service.create_rfi('C','P',operation,question(),[],[raw]);self.assertTrue(second['operation']['replayed']);self.assertEqual(first['revision'],second['revision']);self.assertEqual(len(state.rows),2)
    def test_raw_drawing_rejects_wrong_bytes_page_and_mime(self):
        for mutation in ('sha','page','mime'):
            with self.subTest(mutation=mutation),fixtures() as (state,rules,repo,sources,service,gov):
                raw=add_source(state,extracted=False)
                if mutation=='sha':raw['source_sha256']='0'*64
                if mutation=='page':raw['page']=3
                if mutation=='mime':state.documents[raw['revision_id']]['mime_type']='text/plain'
                with self.assertRaises(DomainError):service.create_rfi('C','P',uid(),question(),[],[raw])
                self.assertFalse(state.rows)
    def test_text_spec_citation_and_contract_link_are_exact(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            raw=add_source(state);ref={k:raw[k] for k in ('revision_id','source_sha256','page')};ref['excerpt_sha256']=hashlib.sha256(b'Exact original specification').hexdigest()
            cited=sources.resolve_citations('C','P',[ref],state.actor)[0];definition=question();definition['contract_citation_ids']=[cited['id']]
            result=service.create_rfi('C','P',uid(),definition,[ref],[]);self.assertEqual(result['revision']['source_citations'],[cited]);state.verify('C','P',result['revision'],state.actor)
    def test_question_requires_actual_source_and_forbids_commercial_payload(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            with self.assertRaises(DomainError):service.create_rfi('C','P',uid(),question(),[],[])
            definition={**question(),'approved_contract_change':True}
            with self.assertRaises(DomainError):service.create_rfi('C','P',uid(),definition,[],[add_source(state)])
            self.assertFalse(state.rows)
    def test_successor_retains_original_and_stale_header_refuses(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            original=self.rfi(state,service);before=deepcopy(original['revision']);header=original['rfi'];raw=add_source(state)
            revised=service.revise_rfi('C','P',uid(),header['id'],digest(header),question('Revised question'),[],[raw])
            self.assertEqual(revised['revision']['predecessor'],before['id']);self.assertEqual(repo.raw('rfi_revision',before['id']),before)
            with self.assertRaises(DomainError):service.revise_rfi('C','P',uid(),header['id'],digest(header),question(),[],[raw])
    def test_no_official_fact_without_exact_effect_context(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            created=self.rfi(state,service);response=service.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[])['response']
            manifest=gov.approval_manifest(kind='response',actor=state.actor,company='C',project='P',subject_id=response['id'],expected_version=digest(response))
            with self.assertRaises(DomainError):gov.apply_authorization(kind='response',actor=state.actor,company='C',project='P',manifest=manifest,packet_id=uid(),decision_id=uid(),operation_id=uid())
            self.assertFalse(any(k=='official_response' for k,_ in state.rows))
    def test_independent_rfi_official_and_source_preserving_internal_receipt(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            created=self.rfi(state,service);response=service.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[])['response']
            with self.assertRaises(DomainError):gov.authorize_subject(kind='response',actor=state.actor,company='C',project='P',subject_id=response['id'],phase='review')
            answerfact=official(state,service,gov,'response',response);self.assertEqual(service.read('official_response',answerfact['id'],'C','P',state.actor),answerfact)
            recipient=add_person(state,'recipient');tx=service.create_transmittal('C','P',uid(),'official_response',answerfact['id'],digest(answerfact),[recipient.user],'For technical coordination','Acknowledge')['transmittal']
            self.assertEqual(tx['drawing_references'],created['revision']['drawing_references']);receipt=official(state,service,gov,'transmittal',tx)
            self.assertFalse(receipt['external_delivery']);self.assertEqual(service.read('distribution',receipt['id'],'C','P',recipient),receipt)
            self.assertTrue(all(v is False for v in receipt['no_effects'].values()))
    def test_same_person_alias_cannot_check_author_work(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            created=self.rfi(state,service);response=service.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[])['response']
            alias=SimpleNamespace(user='alias@example.invalid',person_id=state.actor.person_id);state.users[alias.user]=alias
            with self.assertRaises(DomainError):gov.authorize_subject(kind='response',actor=alias,company='C',project='P',subject_id=response['id'],phase='review')
    def test_submittal_designated_review_blank_comments_and_third_person_grant(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            reviewer=add_person(state,'technical-reviewer');raw=add_source(state,extracted=False)
            created=service.create_submittal('C','P',uid(),submission(reviewer.user),[{k:raw[k] for k in ('revision_id','source_sha256')}],[])
            with self.assertRaises(DomainError):service.create_disposition('C','P',uid(),created['submittal']['id'],created['submission']['id'],digest(created['submittal']),{'disposition':'approved','comments':''},[])
            submitter=state.actor;state.actor=reviewer
            decided=service.create_disposition('C','P',uid(),created['submittal']['id'],created['submission']['id'],digest(created['submittal']),{'disposition':'approved_as_noted','comments':''},[])['disposition']
            self.assertEqual(decided['definition']['comments'],'')
            for person in (submitter,reviewer):
                with self.assertRaises(DomainError):gov.authorize_subject(kind='disposition',actor=person,company='C',project='P',subject_id=decided['id'],phase='review')
            fact=official(state,service,gov,'disposition',decided);self.assertEqual(service.read('official_disposition',fact['id'],'C','P',reviewer),fact)
    def test_recipient_current_access_denial_rolls_back_preparation(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            created=self.rfi(state,service);response=service.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[])['response'];fact=official(state,service,gov,'response',response)
            recipient=add_person(state,'denied');state.duties[recipient.person_id]={'project.read'};before=deepcopy(state.rows)
            with self.assertRaises(DomainError):service.create_transmittal('C','P',uid(),'official_response',fact['id'],digest(fact),[recipient.user],'coordination','')
            self.assertEqual(state.rows,before)
    def test_changed_recipient_identity_refuses_before_new_person_lock(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            recipient=add_person(state,'recipient');old=recipient.person_id;calls=[];original=service.current_actor
            def changing(user=None,lock=False):
                calls.append((user,lock))
                if user==recipient.user and len([c for c in calls if c[0]==user])>1:return SimpleNamespace(user=user,person_id=uid())
                return original(user,lock=lock)
            definition=question();definition['responsible_users']=[recipient.user]
            with patch.object(service,'current_actor',changing),self.assertRaises(DomainError):service.create_rfi('C','P',uid(),definition,[],[add_source(state)])
            self.assertNotIn((recipient.user,True),calls);self.assertFalse(state.rows)
    def test_new_approval_refuses_closed_project_but_history_remains_readable(self):
        for phase in ('request','manifest','review','execute'):
            with self.subTest(phase=phase),fixtures() as (state,rules,repo,sources,service,gov):
                created=self.rfi(state,service);response=service.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[])['response'];state.project_status='Completed'
                with self.assertRaises(DomainError) as refused:gov.authorize_subject(kind='response',actor=add_person(state,'checker'),company='C',project='P',subject_id=response['id'],phase=phase)
                self.assertEqual(refused.exception.code,'project_closed');self.assertEqual(service.read('response',response['id'],'C','P',state.actor),response)
    def test_receipt_failure_rolls_back_domain_and_history(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            state.failed_receipt=True
            with self.assertRaises(RuntimeError):self.rfi(state,service)
            self.assertFalse(state.rows);self.assertFalse(state.events);self.assertFalse(state.receipts)
    def test_uuid_payload_conflict_and_current_read_revocation(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            operation=uid();raw=add_source(state);original=service.create_rfi('C','P',operation,question(),[],[raw])
            with self.assertRaises(DomainError):service.create_rfi('C','P',operation,question('different'),[],[raw])
            state.duties[state.actor.person_id]={'project.read','engineering.write'}
            with self.assertRaises(DomainError):service.create_rfi('C','P',operation,question(),[],[raw])
    def test_official_fact_rejects_consumption_and_decision_tampering(self):
        for field in ('result_hash','decision'):
            with self.subTest(field=field),fixtures() as (state,rules,repo,sources,service,gov):
                created=self.rfi(state,service);response=service.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[])['response'];fact=official(state,service,gov,'response',response)
                setattr(state.consumptions[fact['packet_id']],field,'wrong')
                with self.assertRaises(DomainError):service.read('official_response',fact['id'],'C','P',state.actor)
    def test_original_official_read_after_successor_and_new_distribution_stale(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            created=self.rfi(state,service);response=service.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[])['response'];fact=official(state,service,gov,'response',response)
            tx=service.create_transmittal('C','P',uid(),'official_response',fact['id'],digest(fact),[add_person(state,'recipient').user],'coordination','')['transmittal']
            header=repo.raw('rfi',created['rfi']['id']);service.revise_rfi('C','P',uid(),header['id'],digest(header),question('new question'),[],[add_source(state)])
            self.assertEqual(service.read('official_response',fact['id'],'C','P',state.actor),fact)
            with self.assertRaises(DomainError):gov.approval_manifest(kind='transmittal',actor=state.actor,company='C',project='P',subject_id=tx['id'],expected_version=digest(tx))

if __name__=='__main__':unittest.main()
