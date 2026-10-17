"""Host field fixtures run real controllers/services; no native/runtime claims."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import json
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
    result=ModuleType(name);result.__dict__.update(values);return result

@contextmanager
def fixtures():
    author=SimpleNamespace(user='field-author@example.invalid',person_id=uid())
    state=SimpleNamespace(actor=author,users={author.user:author},native={},events=[],receipts={},documents={},denied=set(),rights={},duties={},failed_receipt=False,project_status='Open',locks=[])
    default={'project.read','document.read','field.read','field.write','field.review','field.accept','field.acknowledge'}
    def current(user=None,lock=False):
        actor=state.users.get(user or state.actor.user)
        if actor is None:raise DomainError('identity_unavailable','Identity revoked.',403)
        return actor
    def require(company,project,ability='project.read',actor=None,lock=False):
        actor=actor or state.actor
        if company!='C' or project!='P':raise DomainError('not_found','scope',404)
        if actor.user not in state.users or state.users[actor.user].person_id!=actor.person_id:raise DomainError('identity_changed','identity',403)
        if ability not in state.duties.get(actor.person_id,default):raise DomainError('capability_denied','duty',403)
        return SimpleNamespace(status=state.project_status)
    @contextmanager
    def trusted():yield
    class FakeDocument:
        def __init__(self,fields,new=True):self.__dict__.update(deepcopy(fields));self._new=new;self._before=None
        def get(self,key):return getattr(self,key,None)
        def is_new(self):return self._new
        def get_doc_before_save(self):return SimpleNamespace(**self._before)
        def update(self,fields):self.__dict__.update(deepcopy(fields))
        def _validate(self):
            records=importlib.import_module('cipher_aec.field.records');records.FieldRecord.validate(self)
        def insert(self,**kwargs):
            if (self.doctype,self.name) in state.native:raise RuntimeError('duplicate')
            self._validate();state.native[self.doctype,self.name]=deepcopy({k:v for k,v in self.__dict__.items() if not k.startswith('_')});self._new=False;return self
        def save(self,**kwargs):
            self._before=deepcopy(state.native[self.doctype,self.name]);self._validate();state.native[self.doctype,self.name]=deepcopy({k:v for k,v in self.__dict__.items() if not k.startswith('_')});return self
    missing=type('Missing',(Exception,),{})
    def get_doc(doctype,name=None,**kwargs):
        if type(doctype) is dict:return FakeDocument(doctype)
        try:fields=state.native[doctype,name]
        except KeyError:raise missing(name)
        return FakeDocument(fields,new=False)
    def sql(query,args=(),**kwargs):
        if 'original_event_id=%s' in query:
            return [SimpleNamespace(name=name) for (dt,name),v in state.native.items() if dt=='Cipher Field Quantity Event' and v['company']==args[0] and v['project']==args[1] and v['original_event_id']==args[2]]
        raise AssertionError(query)
    def source_reference(company,project,revision,page,actor=None,lock=False):
        require(company,project,'document.read',actor or state.actor,lock)
        if revision in state.denied:raise DomainError('source_denied','source access revoked',403)
        value=deepcopy(state.documents[revision])
        if value.get('project','P')!=project:raise DomainError('not_found','source scope',404)
        if not 1<=page<=value['page_count']:raise DomainError('invalid_page','page',422)
        if state.rights.get(value['document_id']) in ('read_denied','expired'):raise DomainError('source_rights_denied','rights',403)
        return {**value,'page':page}
    def rights_require(document,company,project,operation,actor,lock=False,required=True):
        require(company,project,'document.read',actor,lock)
        policy=state.rights.get(document)
        if required and policy is None:raise DomainError('source_rights_required','rights basis',409)
        if policy in ('ingest_denied','read_denied','expired'):raise DomainError('source_rights_denied','rights',403)
        return policy
    rights=module('rights',require=rights_require,prelock=lambda names,*a:state.locks.append(tuple(sorted(names))))
    mocks={
      'frappe':module('frappe',get_doc=get_doc,db=SimpleNamespace(sql=sql),conf={'encryption_key':'x'*32},DoesNotExistError=missing),
      'frappe.model':module('frappe.model'),'frappe.model.document':module('document',Document=FakeDocument),
      'cipher_aec.governance.context':module('context',current_actor=current,require_project=require,authority_fingerprint=lambda *a:'authority-'+str(sorted(state.duties.get(a[0].person_id,default))),trusted_write=trusted,require_trusted_write=lambda:None),
      'cipher_aec.governance.commands':module('commands',run_command=lambda **kwargs:None),
      'cipher_aec.governance.history':module('history',append_event=lambda **kwargs:state.events.append(deepcopy(kwargs)) or uid()),
      'cipher_aec.documents.service':module('documents',source_reference=source_reference),
      'cipher_aec.document_control.rights':rights}
    names=['cipher_aec.field.'+n for n in ('contracts','repository','sources','service','records')]
    old={name:sys.modules.pop(name) for name in names if name in sys.modules}
    import cipher_aec.document_control as control
    oldrights=getattr(control,'rights',None)
    with patch.dict(sys.modules,mocks),patch.object(control,'rights',rights,create=True):
        rules,repo,sources,service,records=[importlib.import_module(name) for name in names]
        def command(**kwargs):
            actor=current();require(kwargs['company'],kwargs['project'],kwargs['ability'],actor)
            key=(actor.person_id,kwargs['operation_id']);request=digest({k:kwargs[k] for k in ('command','company','project','payload')})
            if key in state.receipts:
                checksum,result=state.receipts[key]
                if checksum!=request:raise DomainError('operation_conflict','conflict',409)
                service.authorize_receipt(actor,'C','P',result,lock=True)
                return {**deepcopy(result),'operation':{'id':key[1],'status':'succeeded','replayed':True}}
            before=deepcopy((state.native,state.events,state.receipts))
            try:
                if kwargs.get('guard'):kwargs['guard'](actor,require('C','P'))
                result=kwargs['effect'](actor,require('C','P'))
                if state.failed_receipt:raise RuntimeError('late receipt failure')
                state.receipts[key]=(request,deepcopy(result))
                return {**result,'operation':{'id':key[1],'status':'succeeded','replayed':False}}
            except Exception:state.native,state.events,state.receipts=before;raise
        with patch.object(service,'run_command',command),patch.object(repo,'number',lambda *a:'FIELD-'+str(len(state.receipts)+1)):
            state.require=require;state.get_doc=get_doc;state.FakeDocument=FakeDocument
            yield state,rules,repo,sources,service,records
    for name in names:
        removed=sys.modules.pop(name,None);parentname,attribute=name.rsplit('.',1);parent=sys.modules.get(parentname)
        if parent is not None and getattr(parent,attribute,None) is removed:delattr(parent,attribute)
    sys.modules.update(old)
    for name,value in old.items():
        parentname,attribute=name.rsplit('.',1);setattr(sys.modules[parentname],attribute,value)
    if oldrights is not None:control.rights=oldrights

def add_person(state,label='independent'):
    person=SimpleNamespace(user=label+'@example.invalid',person_id=uid());state.users[person.user]=person;return person

def add_source(state,mime='application/pdf'):
    revision=uid();content=b'host fixture exact source bytes '+revision.encode()
    state.documents[revision]={'document_id':uid(),'revision_id':revision,'revision_number':1,'source_sha256':hashlib.sha256(content).hexdigest(),'byte_length':len(content),'mime_type':mime,'page_count':1,'page':1,'is_current':True,'content':content}
    state.rights[state.documents[revision]['document_id']]='allowed'
    return {'revision_id':revision,'source_sha256':state.documents[revision]['source_sha256'],'page':1,'locator':'Observation 1'}

def daily(state):return {'local_date':'2026-10-17','superintendent_user':state.actor.user,'weather':'','weather_sources':[],'crews':['Civil crew: two people'],'activities':['Installed the recorded pipe segment.'],'delays':[],'visitors':[]}
def quantity(source,original=None,predecessor=None):return {'original_event_id':original or uid(),'supersedes_event_id':predecessor,'kind':'installed','description':'Pipe installed','wbs_code':'02.01','cost_code':'PIPE','quantity':'12.375','unit':'LF','location':'Grid A','sources':[source]}
def ticket(source):return {'local_date':'2026-10-17','title':'Unexpected obstruction','customer_name':'Synthetic owner','location':'Grid A','work_description':'Removed the documented obstruction.','potential_change_reference':'Potential change only','lines':[{'kind':'labor','description':'Two-person crew','quantity':'3.25','unit':'person-hours','sources':[source]}]}
def photo(source,representation='source_image'):return {'source':source,'caption':'Observed installation','captured_at':'2026-10-17T09:15:00-04:00','representation':representation}
def create(state,service,family='daily',operation=None):
    source=add_source(state)
    return service.create_record('C','P',operation or uid(),family,daily(state) if family=='daily' else ticket(source),[],[quantity(source)] if family=='daily' else [])
def step(state,service,result,action,evidence=None):
    return service.transition('C','P',uid(),result['family'],result['header']['id'],digest(result['header']),action,'Recorded documentary '+action,evidence or [],'Named customer representative' if action=='acknowledge' else '')
def accept(state,service,result):
    result=step(state,service,result,'submit');state.actor=add_person(state)
    result=step(state,service,result,'review');return step(state,service,result,'accept')

class FieldWorkflowTests(unittest.TestCase):
    def test_exact_daily_quantity_photo_and_idempotent_replay(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            ref=add_source(state,'image/jpeg');q=quantity(ref);definition=daily(state);operation=uid();photos=[photo(ref)]
            first=service.create_record('C','P',operation,'daily',definition,photos,[q]);second=service.create_record('C','P',operation,'daily',definition,photos,[q])
            self.assertEqual(first['revision'],second['revision']);self.assertTrue(second['operation']['replayed']);self.assertEqual(len(state.native),3)
            self.assertEqual(first['quantities'][0]['definition']['quantity'],'12.375');self.assertEqual(first['revision']['photos'][0]['source']['mime_type'],'image/jpeg')
            self.assertTrue(all(v is False for v in first['revision']['no_effects'].values()))
    def test_accepted_daily_amendment_preserves_original_and_acceptance(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            first=create(state,service);original=deepcopy(first['revision']);oldquantity=deepcopy(first['quantities'][0]);accepted=accept(state,service,first);olddecision=deepcopy(accepted['decision']);state.actor=state.users[first['revision']['author_user']]
            q=quantity(add_source(state),oldquantity['original_event_id'],oldquantity['id']);q['quantity']='11.500'
            amendment=service.revise_record('C','P',uid(),'daily',first['header']['id'],digest(accepted['header']),daily(state),[],[q],'Corrected measured installed length.')
            self.assertEqual(amendment['revision']['amendment_of'],original['id']);self.assertEqual(amendment['revision']['predecessor'],original['id']);self.assertEqual(amendment['revision']['prior_decision'],olddecision['id'])
            self.assertEqual(repo.raw('daily_revision',original['id']),original);self.assertEqual(repo.raw('quantity',oldquantity['id']),oldquantity);self.assertEqual(repo.raw('decision',olddecision['id']),olddecision)
            self.assertEqual(amendment['header']['status'],'draft');self.assertEqual(amendment['header']['accepted_revision'],original['id'])
    def test_separate_accepted_and_current_source_packages_keep_amendment_readable(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            first=service.create_record('C','P',uid(),'daily',daily(state),[],[quantity(add_source(state)) for _ in range(17)])
            accepted=accept(state,service,first);state.actor=state.users[first['revision']['author_user']]
            amended=service.revise_record('C','P',uid(),'daily',first['header']['id'],digest(accepted['header']),daily(state),[],[quantity(add_source(state)) for _ in range(17)],'Document corrected observations.')
            self.assertEqual(service.get_record('C','P','daily',first['header']['id'])['record'],amended['header'])
            self.assertEqual(service.get_record('C','P','daily_revision',first['revision']['id'])['record'],first['revision'])
    def test_acknowledged_ticket_changes_no_contract_budget_procurement_or_finances(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            commercial={('Sales Order','existing-contract'):{'amount':'175000.00'},('Cipher Budget Version','existing-budget'):{'approved':'125000.00'},('Purchase Order','existing-po'):{'quantity':'20'},('Sales Invoice','existing-invoice'):{'amount':'1000.00'},('GL Entry','existing-ledger'):{'debit':'1000.00'}}
            state.native.update(deepcopy(commercial));created=create(state,service,'ticket')
            accepted=accept(state,service,created);ack=step(state,service,accepted,'acknowledge',[add_source(state)])
            self.assertEqual(ack['header']['status'],'acknowledged');self.assertTrue(all(v is False for v in ack['decision']['no_effects'].values()))
            self.assertEqual({key:value for key,value in state.native.items() if key in commercial},commercial)
            self.assertTrue(all(doctype in rules.KINDS.values() for doctype,name in set(state.native)-set(commercial)));self.assertEqual(len(state.events),5)
            state.actor=state.users[created['revision']['author_user']]
            amended=service.revise_record('C','P',uid(),'ticket',ack['header']['id'],digest(ack['header']),ticket(add_source(state)),[],[],'Correct the documentary labor observation.')
            self.assertEqual(amended['revision']['amendment_of'],created['revision']['id']);self.assertEqual(repo.raw('decision',ack['decision']['id']),ack['decision'])
    def test_same_person_alias_and_superintendent_cannot_review_accept_or_acknowledge(self):
        for family in ('daily','ticket'):
            with self.subTest(family=family),fixtures() as (state,rules,repo,sources,service,records):
                created=create(state,service,family);submitted=step(state,service,created,'submit');author=state.actor;alias=SimpleNamespace(user='alias@example.invalid',person_id=author.person_id);state.users[alias.user]=alias;state.actor=alias
                with self.assertRaises(DomainError) as refused:step(state,service,submitted,'review')
                self.assertEqual(refused.exception.code,'independent_field_review_required')
                state.actor=add_person(state);reviewed=step(state,service,submitted,'review');state.actor=alias
                with self.assertRaises(DomainError):step(state,service,reviewed,'accept')
                state.actor=add_person(state,'acceptor');accepted=step(state,service,reviewed,'accept')
                if family=='ticket':
                    state.actor=alias
                    with self.assertRaises(DomainError):step(state,service,accepted,'acknowledge',[add_source(state)])
        with fixtures() as (state,rules,repo,sources,service,records):
            superintendent=add_person(state,'superintendent');definition=daily(state);definition['superintendent_user']=superintendent.user
            created=service.create_record('C','P',uid(),'daily',definition,[],[]);submitted=step(state,service,created,'submit');state.actor=superintendent
            with self.assertRaises(DomainError):step(state,service,submitted,'review')
    def test_source_current_rights_scope_bytes_and_missing_basis_refuse_new_capture(self):
        for mutation in ('current','rights','missing_rights','bytes','hash','scope','page'):
            with self.subTest(mutation=mutation),fixtures() as (state,rules,repo,sources,service,records):
                ref=add_source(state);source=state.documents[ref['revision_id']]
                if mutation=='current':source['is_current']=False
                if mutation=='rights':state.rights[source['document_id']]='ingest_denied'
                if mutation=='missing_rights':del state.rights[source['document_id']]
                if mutation=='bytes':source['content']=b'tampered'
                if mutation=='hash':ref['source_sha256']='0'*64
                if mutation=='scope':source['project']='OTHER'
                if mutation=='page':ref['page']=2
                with self.assertRaises(DomainError):service.create_record('C','P',uid(),'daily',daily(state),[],[quantity(ref)])
                self.assertFalse(state.native);self.assertFalse(state.events);self.assertFalse(state.receipts)
    def test_historical_read_and_receipt_preserve_sources_but_new_review_refuses_superseded_source(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            ref=add_source(state);definition=daily(state);q=quantity(ref);operation=uid();created=service.create_record('C','P',operation,'daily',definition,[],[q]);submitted=step(state,service,created,'submit');state.documents[ref['revision_id']]['is_current']=False
            self.assertEqual(service.get_record('C','P','daily_revision',created['revision']['id'])['record'],created['revision'])
            self.assertTrue(service.create_record('C','P',operation,'daily',definition,[],[q])['operation']['replayed'])
            state.actor=add_person(state)
            with self.assertRaises(DomainError) as refused:step(state,service,submitted,'review')
            self.assertEqual(refused.exception.code,'stale_field_source')
            returned=step(state,service,submitted,'return')
            self.assertEqual(returned['header']['status'],'returned')
            state.actor=state.users[created['revision']['author_user']]
            amended=service.revise_record('C','P',uid(),'daily',created['header']['id'],digest(returned['header']),definition,[],[quantity(add_source(state))])
            self.assertEqual(amended['header']['status'],'draft')
    def test_revoked_read_duty_identity_rights_and_source_deny_replay(self):
        for revoked in ('field_read','document_read','identity','rights','source'):
            with self.subTest(revoked=revoked),fixtures() as (state,rules,repo,sources,service,records):
                ref=add_source(state);definition=daily(state);q=quantity(ref);operation=uid();created=service.create_record('C','P',operation,'daily',definition,[],[q]);before=deepcopy(state.native)
                if revoked=='field_read':state.duties[state.actor.person_id]={'project.read','document.read','field.write'}
                if revoked=='document_read':state.duties[state.actor.person_id]={'project.read','field.read','field.write'}
                if revoked=='identity':del state.users[state.actor.user]
                if revoked=='rights':state.rights[state.documents[ref['revision_id']]['document_id']]='read_denied'
                if revoked=='source':state.denied.add(ref['revision_id'])
                with self.assertRaises(DomainError):service.create_record('C','P',operation,'daily',definition,[],[q])
                self.assertEqual(state.native,before)
    def test_original_retry_does_not_require_later_successor_sources(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            originalref=add_source(state);definition=daily(state);operation=uid();q=quantity(originalref);first=service.create_record('C','P',operation,'daily',definition,[],[q]);laterref=add_source(state)
            later=service.revise_record('C','P',uid(),'daily',first['header']['id'],digest(first['header']),definition,[],[quantity(laterref)])
            state.denied.add(laterref['revision_id']);self.assertTrue(service.create_record('C','P',operation,'daily',definition,[],[q])['operation']['replayed'])
            with self.assertRaises(DomainError):service.get_record('C','P','daily',first['header']['id'])
            state.denied.add(originalref['revision_id'])
            with self.assertRaises(DomainError):service.create_record('C','P',operation,'daily',definition,[],[q])
    def test_stale_version_retry_conflict_and_transition_order(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            created=create(state,service);submitted=step(state,service,created,'submit');before=deepcopy(state.native)
            with self.assertRaises(DomainError) as refused:step(state,service,created,'submit')
            self.assertEqual(refused.exception.code,'stale_field_record')
            with self.assertRaises(DomainError):service.revise_record('C','P',uid(),'daily',created['header']['id'],digest(submitted['header']),daily(state),[],[])
            state.actor=add_person(state)
            with self.assertRaises(DomainError):step(state,service,submitted,'accept')
            self.assertEqual(state.native,before)
        with fixtures() as (state,rules,repo,sources,service,records):
            operation=uid();created=service.create_record('C','P',operation,'daily',daily(state),[],[])
            definition=daily(state);definition['activities']=['A different request.']
            with self.assertRaises(DomainError) as refused:service.create_record('C','P',operation,'daily',definition,[],[])
            self.assertEqual(refused.exception.code,'operation_conflict')
    def test_late_receipt_failure_rolls_back_capture_and_decision(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            state.failed_receipt=True
            with self.assertRaises(RuntimeError):create(state,service)
            self.assertFalse(state.native);self.assertFalse(state.events);self.assertFalse(state.receipts)
            state.failed_receipt=False;created=create(state,service);submitted=step(state,service,created,'submit');state.actor=add_person(state);before=deepcopy((state.native,state.events,state.receipts));state.failed_receipt=True
            with self.assertRaises(RuntimeError):step(state,service,submitted,'review')
            self.assertEqual((state.native,state.events,state.receipts),before)
    def test_explicit_ordinary_project_duties_not_implied_from_project_write(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            state.duties[state.actor.person_id]={'project.read','project.write','document.read','field.read'}
            with self.assertRaises(DomainError):create(state,service)
            self.assertFalse(state.native)
    def test_duplicate_capture_and_cross_record_quantity_correction_refuse(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            first=create(state,service);q=first['quantities'][0]
            with self.assertRaises(DomainError):service.create_record('C','P',uid(),'daily',daily(state),[],[quantity(add_source(state),q['original_event_id'])])
            second=service.create_record('C','P',uid(),'daily',daily(state),[],[])
            with self.assertRaises(DomainError):service.revise_record('C','P',uid(),'daily',second['header']['id'],digest(second['header']),daily(state),[],[quantity(add_source(state),q['original_event_id'],q['id'])])
            self.assertEqual(repo.raw('quantity',q['id']),q)
    def test_closed_fields_decimal_dates_sources_photos_and_acknowledgment_evidence(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            ref=add_source(state)
            for amount in (12.5,'-1','0','NaN','1e4','01','2.1234567'):
                q=quantity(ref);q['quantity']=amount
                with self.subTest(amount=amount),self.assertRaises(DomainError):rules.quantity_definition(q)
            for mutated in ({**daily(state),'approved_amount':'1000.00'},{**daily(state),'local_date':'2026-02-30'}):
                with self.assertRaises(DomainError):service.create_record('C','P',uid(),'daily',mutated,[],[])
            with self.assertRaises(DomainError):service.create_record('C','P',uid(),'daily',daily(state),[photo(ref)],[])
            created=service.create_record('C','P',uid(),'daily',daily(state),[photo(ref,'photo_on_pdf_page')],[])
            self.assertEqual(created['revision']['photos'][0]['representation'],'photo_on_pdf_page')
            tm=ticket(ref);tm['lines'][0]['rate']='150'
            with self.assertRaises(DomainError):service.create_record('C','P',uid(),'ticket',tm,[],[])
            accepted=accept(state,service,create(state,service,'ticket'))
            with self.assertRaises(DomainError):step(state,service,accepted,'acknowledge')
    def test_cross_scope_reads_and_closed_project_new_effects_refuse(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            created=create(state,service)
            with self.assertRaises(DomainError):service.get_record('C','OTHER','daily',created['header']['id'])
            native=state.native[rules.KINDS['daily_revision'],created['revision']['id']];value=json.loads(native['data_json']);value['project']='OTHER';native.update(data_json=json.dumps(value),record_digest=digest(value),project='OTHER')
            with self.assertRaises(DomainError):service.get_record('C','P','daily_revision',created['revision']['id'])
            state.project_status='Completed'
            with self.assertRaises(DomainError):create(state,service)

class FieldControllerTests(unittest.TestCase):
    def test_generic_write_and_trusted_writer_without_command_are_denied(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            created=create(state,service);revision=created['revision'];doc=state.get_doc(rules.KINDS['daily_revision'],revision['id'])
            with self.assertRaises(DomainError) as refused:doc.save()
            self.assertEqual(refused.exception.code,'field_command_required')
            new={**revision,'id':uid()}
            with self.assertRaises(DomainError) as refused:repo.write('daily_revision',new)
            self.assertEqual(refused.exception.code,'field_command_required')
    def test_originals_cannot_be_updated_deleted_or_renamed(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            created=create(state,service);value=created['revision'];changed={**value,'created_at':'2026-10-17T10:00:00Z'}
            token=service._command_effect.set({'action':'daily.revise','person':state.actor.person_id,'company':'C','project':'P'})
            try:
                with self.assertRaises(DomainError) as refused:repo.write('daily_revision',changed,old=value)
                self.assertEqual(refused.exception.code,'immutable_field_record')
            finally:service._command_effect.reset(token)
            doc=state.get_doc(rules.KINDS['daily_revision'],value['id'])
            with self.assertRaises(DomainError):records.FieldRecord.on_trash(doc)
            with self.assertRaises(DomainError):records.FieldRecord.before_rename(doc,'new')
    def test_canonical_index_and_digest_tampering_fail_closed(self):
        for mutation in ('digest','index','payload'):
            with self.subTest(mutation=mutation),fixtures() as (state,rules,repo,sources,service,records):
                created=create(state,service);native=state.native[rules.KINDS['quantity'],created['quantities'][0]['id']]
                if mutation=='digest':native['record_digest']='0'*64
                if mutation=='index':native['original_event_id']=uid()
                if mutation=='payload':
                    value=json.loads(native['data_json']);value['no_effects']['contract_change']=True;native['data_json']=json.dumps(value);native['record_digest']=digest(value)
                with self.assertRaises(DomainError):service.get_record('C','P','quantity',created['quantities'][0]['id'])
    def test_field_doctypes_have_guarded_controllers_and_project_scope(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            for name in rules.KINDS.values():
                slug=name.lower().replace(' ','_');folder=ROOT/'cipher_field/doctype'/slug;value=json.loads((folder/(slug+'.json')).read_text());fields={f['fieldname']:f for f in value['fields']}
                self.assertEqual(value['module'],'Cipher Field');self.assertEqual(fields['scope_type']['options'],'Project');self.assertEqual(fields['project']['reqd'],1);self.assertFalse(value['allow_rename']);self.assertIn('FieldRecord',(folder/(slug+'.py')).read_text())
    def test_bounded_authorized_keyset_and_revoked_cursor(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            items=[create(state,service)['revision'] for _ in range(3)];items.reverse()
            def rows(kind,company,project,parent_id=None,last=None,limit=25):
                start=next((i+1 for i,item in enumerate(items) if last and item['id']==last[1]),0)
                return [SimpleNamespace(name=v['id'],creation='2026-10-17 00:00:00') for v in items[start:start+limit]]
            with patch.object(repo,'candidate_rows',rows):
                first=service.list_records('C','P','daily_revision',limit=2);second=service.list_records('C','P','daily_revision',limit=2,cursor=first['next_cursor'])
                self.assertEqual(len(first['items']),2);self.assertEqual(len(second['items']),1);self.assertIsNone(second['next_cursor']);self.assertIsNone(first['total'])
                state.actor=add_person(state)
                with self.assertRaises(DomainError):service.list_records('C','P','daily_revision',limit=2,cursor=first['next_cursor'])
    def test_header_parent_filter_refuses_before_native_sql(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            for kind in ('daily','ticket'):
                with patch.object(repo,'candidate_rows',side_effect=AssertionError('Must not query an absent header column.')):
                    with self.assertRaises(DomainError):service.list_records('C','P',kind,parent_id=uid())
    def test_exact_history_rechecks_current_source_access(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            created=create(state,service);event=state.events[0]
            self.assertEqual(service.authorize_history('daily_revision',created['revision']['id'],'C','P',state.actor,event['details']),created['revision'])
            source=created['quantities'][0]['definition']['sources'][0]['revision_id'];state.denied.add(source)
            with self.assertRaises(DomainError):service.authorize_history('daily_revision',created['revision']['id'],'C','P',state.actor,event['details'])

if __name__=='__main__':unittest.main()
