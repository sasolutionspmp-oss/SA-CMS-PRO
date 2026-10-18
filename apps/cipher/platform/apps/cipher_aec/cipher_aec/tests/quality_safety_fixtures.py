"""Host fixtures adapted from FLD-01; actual FLD-03 controllers and byte admission."""
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
    author=SimpleNamespace(user='quality-author@example.invalid',person_id=uid())
    state=SimpleNamespace(actor=author,users={author.user:author},native={},events=[],receipts={},documents={},denied=set(),rights={},duties={},failed_receipt=False,project_status='Open',locks=[])
    default={'project.read','document.read','document.write','document.rights.manage','safety.incident.evidence.manage',*[prefix+'.'+action for prefix in ('quality','safety.incident') for action in ('read','write','check','close')]}
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
            records=importlib.import_module('cipher_aec.quality_safety.privacy' if self.doctype=='Cipher Incident Evidence Registration' else 'cipher_aec.quality_safety.records');(records.IncidentEvidenceRegistration if self.doctype=='Cipher Incident Evidence Registration' else records.QualitySafetyRecord).validate(self)
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
        if 'WHERE document_id=%s' in query:
            return [SimpleNamespace(name=name) for (dt,name),v in state.native.items() if dt=='Cipher Incident Evidence Registration' and v['document_id']==args[0]]
        if 'FROM `tabCipher Document Revision` r LEFT JOIN' in query:
            private={v['document_id'] for (dt,_),v in state.native.items() if dt=='Cipher Incident Evidence Registration'}
            return [SimpleNamespace(name=r) for r,v in state.documents.items() if v['source_sha256']==args[0] and v['document_id'] not in private][:1]
        if 'original_event_id=%s' in query:
            return [SimpleNamespace(name=name) for (dt,name),v in state.native.items() if dt=='Cipher Field Quantity Event' and v['company']==args[0] and v['project']==args[1] and v['original_event_id']==args[2]]
        raise AssertionError(query)
    def get_value(doctype,name,fields,as_dict=False):
        if doctype=='Cipher Document Revision' and name in state.documents:
            source=state.documents[name]
            result={'document':source['document_id'],'company':'C','project':source.get('project','P'),'scope_type':'Project'}
            class Locator(dict):
                __getattr__=dict.__getitem__
            return Locator(result) if as_dict else result.get(fields)
        return None
    def source_reference(company,project,revision,page,actor=None,lock=False):
        require(company,project,'document.read',actor or state.actor,lock)
        if revision in state.denied:raise DomainError('source_denied','source access revoked',403)
        value=deepcopy(state.documents[revision])
        privacy=importlib.import_module('cipher_aec.quality_safety.privacy')
        privacy.authorize_source({'name':value['document_id'],'company':company,'project':project,'scope_type':'Project'},actor or state.actor,lock=lock)
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
      'frappe':module('frappe',get_doc=get_doc,db=SimpleNamespace(sql=sql,get_value=get_value,exists=lambda dt,name: dt=='DocType' or (dt,name) in state.native),conf={'encryption_key':'x'*32},DoesNotExistError=missing),
      'frappe.model':module('frappe.model'),'frappe.model.document':module('document',Document=FakeDocument),
      'cipher_aec.governance.context':module('context',current_actor=current,require_project=require,authority_fingerprint=lambda *a:'authority-'+str(sorted(state.duties.get(a[0].person_id,default))),trusted_write=trusted,require_trusted_write=lambda:None),
      'cipher_aec.governance.commands':module('commands',run_command=lambda **kwargs:None),
      'cipher_aec.governance.history':module('history',append_event=lambda **kwargs:state.events.append(deepcopy(kwargs)) or uid()),
      'cipher_aec.documents.service':module('documents',source_reference=source_reference),
      'cipher_aec.document_control.rights':rights}
    names=['cipher_aec.field.sources',*['cipher_aec.quality_safety.'+n for n in ('contracts','repository','sources','service','records','privacy','evidence')]]
    absent=object()
    old={name:sys.modules.get(name,absent) for name in names}
    attributes={name:getattr(sys.modules.get(name.rsplit('.',1)[0]),name.rsplit('.',1)[1],absent) for name in names}
    for name in names:sys.modules.pop(name,None)
    import cipher_aec.document_control as control
    imported={}
    try:
        with patch.dict(sys.modules,mocks),patch.object(control,'rights',rights,create=True):
            try:
                rules,repo,sources,service,records,privacy=[importlib.import_module(name) for name in names[1:7]]
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
            finally:
                imported={name:sys.modules.get(name,absent) for name in names}
    finally:
        for name in names:
            if old[name] is absent:sys.modules.pop(name,None)
            else:sys.modules[name]=old[name]
            parentname,attribute=name.rsplit('.',1);parent=sys.modules.get(parentname)
            if parent is None:continue
            current=getattr(parent,attribute,absent)
            if imported[name] is not absent and current is imported[name]:
                if attributes[name] is absent:delattr(parent,attribute)
                else:setattr(parent,attribute,attributes[name])


def add_person(state,label='independent'):
    person=SimpleNamespace(user=label+'@example.invalid',person_id=uid());state.users[person.user]=person;return person

def add_source(state,mime='application/pdf'):
    revision=uid();content=b'host fixture exact source bytes '+revision.encode()
    state.documents[revision]={'document_id':uid(),'revision_id':revision,'revision_number':1,'source_sha256':hashlib.sha256(content).hexdigest(),'byte_length':len(content),'mime_type':mime,'page_count':1,'page':1,'is_current':True,'content':content}
    state.rights[state.documents[revision]['document_id']]='allowed'
    return {'revision_id':revision,'source_sha256':state.documents[revision]['source_sha256'],'page':1,'locator':'Observation 1'}
