"""Private-source creation and derivative byte admission against actual core."""
import base64
from copy import deepcopy
import hashlib
import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from cipher_aec.api.errors import DomainError
from cipher_aec.documents.core import DocumentService
from cipher_aec.tests.test_documents import MemoryMetadata
from .quality_safety_fixtures import fixtures,uid,add_person,add_source
from .test_quality_safety import definition

class IncidentEvidencePrivacyTests(unittest.TestCase):
    def test_incident_rejects_ordinary_evidence_without_exact_non_sensitive_declaration(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            source=add_source(state);authored=definition('incident','incident')
            with self.assertRaises(DomainError) as caught:service.create_record('C','P',uid(),'incident','incident',authored,[source])
            self.assertEqual(caught.exception.code,'restricted_incident_evidence_required');self.assertEqual(state.native,{})
            authored.update(shared_evidence_revisions=[source['revision_id']],shared_evidence_statement='This exact ordinary source is non-sensitive shared evidence.')
            saved=service.create_record('C','P',uid(),'incident','incident',authored,[source])
            self.assertEqual(saved['revision']['evidence'][0]['revision_id'],source['revision_id'])
            privacy=importlib.import_module('cipher_aec.quality_safety.privacy');self.assertIsNone(privacy.registration(state.documents[source['revision_id']]['document_id']))

    def test_authoritative_registration_precedes_canonical_bytes_and_current_revocation_blocks_derivatives(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            privacy=importlib.import_module('cipher_aec.quality_safety.privacy');evidence=importlib.import_module('cipher_aec.quality_safety.evidence')
            source=add_source(state);events=[];metadata=MemoryMetadata();stored={}
            class Metadata:
                def __init__(self,*args):pass
                def create_document(self,row):
                    self_value=privacy.registration(row['name']);assert self_value is not None
                    events.append('private-registration-before-document');metadata.create_document(row)
                def create_revision(self,row):
                    metadata.create_revision(row);state.documents[row['name']]={'document_id':row['document'],'revision_id':row['name'],'revision_number':row['revision_number'],'source_sha256':row['sha256'],'byte_length':row['byte_length'],'mime_type':row['mime_type'],'page_count':row['page_count'],'page':1,'is_current':True,'content':stored[row['storage_reference']]}
                def advance_document(self,*args):metadata.advance_document(*args)
            class Storage:
                def put(self,rid,filename,content):
                    assert all(privacy.registration(name) for name in metadata.docs)
                    events.append('bytes-after-registration');stored[rid]=content;return rid
            documents=importlib.import_module('cipher_aec.documents.service')
            def detail(company,name,actor=None):
                privacy.authorize_source(metadata.docs[name],actor)
                from cipher_aec.documents.core import present_document,present_revision
                revisions=metadata.revisions(name);return {'document':present_document(metadata.document(name),revisions[-1]),'revisions':[present_revision(r) for r in revisions]}
            conf=importlib.import_module('frappe').conf;conf.update(cipher_site_mode='synthetic',cipher_allow_unscanned_documents=1)
            content=b'Restricted synthetic witness account.';checksum=hashlib.sha256(content).hexdigest();operation=uid()
            with patch.object(documents,'_call',lambda fn:fn(),create=True),patch.object(evidence,'FrappeDocumentRepository',Metadata),patch.object(evidence,'FrappeFileStorage',Storage),patch.object(documents,'get_document',detail,create=True),patch.dict('sys.modules',{'cipher_aec.documents.provenance':SimpleNamespace(authorize=lambda row,actor,lock=False:privacy.authorize_source(row,actor,lock=lock))}):
                result=evidence.upload_evidence('C','P',operation,'Restricted evidence','restricted.txt',base64.b64encode(content).decode(),len(content),checksum,'Authored internal permission basis',[source])
                from .test_quality_safety_contracts import validate
                validate('QsUploadEvidenceResponse',result)
                self.assertEqual(events,['private-registration-before-document','bytes-after-registration']);self.assertIsNone(result['history_id']);self.assertEqual(state.events,[])
                self.assertEqual(state.documents[result['revision']['id']]['content'],content)
                replay=evidence.upload_evidence('C','P',operation,'Restricted evidence','restricted.txt',base64.b64encode(content).decode(),len(content),checksum,'Authored internal permission basis',[source])
                self.assertTrue(replay['operation']['replayed']);self.assertEqual(len(events),2)
                state.documents[source['revision_id']]['revision_number']=9
                with self.assertRaises(DomainError):service.authorize_receipt(state.actor,'C','P',result)
                state.documents[source['revision_id']]['revision_number']=1
                private_ref={k:state.documents[result['revision']['id']][k] for k in ('revision_id','source_sha256')};private_ref.update(page=1,locator='Restricted original account')
                authored=definition('incident','incident')
                with self.assertRaises(DomainError):service.create_record('C','P',uid(),'incident','incident',authored,[private_ref])
                state.rights[result['document']['id']]='allowed'
                incident=service.create_record('C','P',uid(),'incident','incident',authored,[private_ref])
                state.actor=add_person(state,'ordinary');state.duties[state.actor.person_id]={'project.read','document.read','quality.read'}
                core=DocumentService(metadata,Storage(),lambda *a:None,allow_unscanned=True,source_authorize=lambda row,lock=False:privacy.authorize_source(row,state.actor,lock=lock))
                for name,operation in (
                    ('list',lambda:core.list('C','P')),('search',lambda:core.search('C','P','witness')),
                ):self.assertEqual(operation(),[],name)
                for operation in (lambda:core.download('C',result['revision']['id']),lambda:core.preview('C',result['revision']['id']),lambda:core.citation('C',result['revision']['id'],1),lambda:core.source_reference('C','P',result['revision']['id'],1)):
                    with self.assertRaises(DomainError):operation()
                with self.assertRaises(DomainError):service.authorize_receipt(state.actor,'C','P',result)
                with self.assertRaises(DomainError):service.get_record('C','P','incident',incident['header']['id'])

    def test_registration_cannot_reclassify_existing_document_or_generic_native_insert(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            privacy=importlib.import_module('cipher_aec.quality_safety.privacy');source=add_source(state);captured=list(sources.resolve('C','P',[source],state.actor,new_use=True).values())
            row={'name':state.documents[source['revision_id']]['document_id'],'company':'C','project':'P','scope_type':'Project','revision_number':1,'current_revision':source['revision_id']}
            before=deepcopy(state.native)
            with self.assertRaises(DomainError):privacy.register_new_document(row,'C','P',state.actor,'Authored rights basis',captured)
            with self.assertRaises(DomainError):privacy.reject_shared_bytes(source['source_sha256'])
            self.assertEqual(state.native,before)

    def test_private_upload_requires_specific_manager_and_current_permission_source(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            privacy=importlib.import_module('cipher_aec.quality_safety.privacy');source=add_source(state)
            state.duties[state.actor.person_id]=set(rules.ABILITIES)|{'document.read','document.write','project.read'}
            with self.assertRaises(DomainError):privacy.require_private_upload('C','P',state.actor)
            state.duties[state.actor.person_id].add('document.rights.manage');state.duties[state.actor.person_id].remove('safety.incident.evidence.manage')
            with self.assertRaises(DomainError):privacy.require_private_upload('C','P',state.actor)
            state.duties[state.actor.person_id].add('safety.incident.evidence.manage')
            state.documents[source['revision_id']]['is_current']=False
            with self.assertRaises(DomainError):sources.resolve('C','P',[source],state.actor,new_use=True)

    def test_malformed_closed_selectors_fail_as_domain_errors(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            for value in ([],{},None,1):
                with self.subTest(value=value),self.assertRaises(DomainError):service.create_record('C','P',uid(),value,'inspection',definition(),[add_source(state)])
                with self.subTest(value=value),self.assertRaises(DomainError):service.get_record('C','P',value,uid())
                with self.subTest(value=value),self.assertRaises(DomainError):service.transition('C','P',uid(),'record',uid(),'a'*64,value,'Comment',[],[])

if __name__=='__main__':unittest.main()
