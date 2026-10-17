"""Metadata preflight is node admission, never content/resource authority."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cipher_aec.api.errors import DomainError
from cipher_aec.documents import provenance as p, storage
from cipher_aec.documents.core import DocumentService
from cipher_aec.documents.extraction import digest
from cipher_aec.tests.test_documents_provenance import ACTOR, document


class MutationSourceIdentity(unittest.TestCase):
    def setUp(self):
        self.parent={**document('parent'),'title':'Original','current_revision':'revision','revision_number':1}
        self.revision={**self.parent,'name':'revision','document':'parent','sha256':digest(b'original'),
            'storage_reference':'parent','byte_length':8,'page_count':1,'pages_json':'["Original page"]','scan_status':'not_scanned',
            'retrieval_status':'available','extraction_status':'ready'}
        self.locator={key:self.revision[key] for key in ('name','document','company','project','scope_type')}
        self.calls=[]
        self.repo=SimpleNamespace(revision_locator=lambda name:self.locate(name),revision_scope=lambda name:self.locate(name),
            document=lambda name,lock=False:self.read('parent',name,lock),revision=lambda name,lock=False:self.read('revision',name,lock))
        self.factory=patch('cipher_aec.documents.repository.FrappeDocumentRepository',return_value=self.repo)
        self.guard=patch('cipher_aec.governance.context.require_company')
        self.factory.start();self.required=self.guard.start();self.addCleanup(self.factory.stop);self.addCleanup(self.guard.stop)
        self.plan={'generated_sources':[{'document_id':'parent','input_digest':self.parent['producer_input_digest']}],
            'unit_ids':['unit-only-in-producer']}

    def locate(self,name):
        self.calls.append(('locator',name));return copy.deepcopy(self.locator)

    def read(self,kind,name,lock):
        self.calls.append((kind,name,lock));return copy.deepcopy(self.parent if kind=='parent' else self.revision)

    def preflight(self,actor=ACTOR,company='Company A'):
        return p.mutation_source_identity(company,'revision',actor)

    def test_raw_identity_uses_current_parent_then_revision_without_discovery_or_admission(self):
        for row in (self.parent,self.revision):
            for field in ('producer_kind','producer_reference','producer_input_digest','producer_binding_json'):row[field]=None
        with patch.object(p,'source_plan',side_effect=AssertionError('Preflight traversed dependencies')):
            self.assertEqual(self.preflight(),{'generated':False,'document_id':'parent','revision_id':'revision','input_digest':None})
        self.assertEqual(self.calls,[('locator','revision'),('parent','parent',True),('revision','revision',True)])
        self.required.assert_called_once_with('Company A',ability='document.read',actor=ACTOR,lock=True)
        self.assertFalse(p.has_prelocked())

    def test_generated_requires_exact_valid_node_and_identity_without_full_resource_checks(self):
        with self.assertRaises(DomainError):self.preflight()
        wrong=copy.deepcopy(self.plan);wrong['generated_sources'][0]['input_digest']='0'*64
        with p.prelocked(wrong,ACTOR,'Company A'):
            with self.assertRaises(DomainError):self.preflight()
        with p.prelocked(self.plan,ACTOR,'Company A'):
            with patch.object(p,'source_plan',side_effect=AssertionError('Preflight traversed dependencies')):
                self.assertEqual(self.preflight()['input_digest'],self.parent['producer_input_digest'])
            with self.assertRaises(DomainError):self.preflight(SimpleNamespace(user='alias',person_id=ACTOR.person_id))
            with self.assertRaises(DomainError):self.preflight(SimpleNamespace(user=ACTOR.user,person_id='other-person'))
            p._invalidate(p._locked_original.get())
            with self.assertRaises(DomainError):self.preflight()
        self.assertFalse(p.has_prelocked())

    def test_scope_mapping_and_each_producer_field_are_fresh_even_with_admitted_node(self):
        with p.prelocked(self.plan,ACTOR,'Company A'):
            self.preflight()
            for row,field,value in ((self.locator,'company','Company B'),(self.locator,'project','Project X'),
                (self.locator,'scope_type','Project'),(self.parent,'company','Company B'),(self.parent,'project',''),
                (self.revision,'scope_type','Project'),(self.revision,'project','Project X'),(self.revision,'company','Company B'),
                (self.revision,'document','forged-parent'),(self.revision,'name','other-revision'),
                *((self.revision,key,'forged') for key in ('producer_kind','producer_reference','producer_input_digest','producer_binding_json'))):
                old=row[field];row[field]=value
                try:
                    with self.subTest(field=field,value=value),self.assertRaises(DomainError):self.preflight()
                finally:row[field]=old
            for row in (self.parent,self.revision):row['producer_input_digest']='0'*64
            with self.assertRaises(DomainError):self.preflight()

    def test_company_permission_denial_precedes_metadata_and_no_token_is_created(self):
        self.required.side_effect=DomainError('capability_denied','Denied',403)
        with self.assertRaises(DomainError):self.preflight()
        self.assertEqual(self.calls,[]);self.assertFalse(p.has_prelocked())

    def canonical(self):
        reads=[]
        def read(reference,sha,size):
            reads.append(reference);return storage.verify_bytes(b'original',sha,size)
        service=DocumentService(self.repo,SimpleNamespace(read=read),lambda *args:None,
            allow_unscanned=True,scope_type='Company',source_authorize=lambda row,lock=False:p.authorize(row,ACTOR,lock=lock))
        return service,reads

    def test_node_only_preflight_cannot_replace_complete_resource_authority_before_bytes(self):
        node_only={'generated_sources':self.plan['generated_sources']}
        adapter=SimpleNamespace(binding_plan=lambda *a,**k:self.plan,authorize_binding=lambda *a,**k:None)
        service,reads=self.canonical()
        with patch.dict('sys.modules',{'cipher_aec.commercial.output_sources':adapter}),p.prelocked(node_only,ACTOR,'Company A'):
            self.assertTrue(self.preflight()['generated'])
            with self.assertRaises(DomainError) as error:service.citation('Company A','revision',1,lock=True)
            self.assertEqual(error.exception.code,'source_prelock_required')
        self.assertEqual(reads,[])

    def test_complete_admission_still_checks_original_rights_and_actual_bytes(self):
        def denied(*args,**kwargs):raise DomainError('not_found','Original source revoked',404)
        adapter=SimpleNamespace(binding_plan=lambda *a,**k:self.plan,authorize_binding=denied)
        service,reads=self.canonical()
        with patch.dict('sys.modules',{'cipher_aec.commercial.output_sources':adapter}),p.prelocked(self.plan,ACTOR,'Company A'):
            self.preflight()
            with self.assertRaises(DomainError):service.citation('Company A','revision',1,lock=True)
        self.assertEqual(reads,[])
        adapter.authorize_binding=lambda *a,**k:None
        with patch.dict('sys.modules',{'cipher_aec.commercial.output_sources':adapter}),p.prelocked(self.plan,ACTOR,'Company A'):
            self.preflight();service.citation('Company A','revision',1,lock=True)
            self.assertEqual(reads,['parent'])
            self.revision['sha256']='0'*64
            from cipher_aec.documents.extraction import ArtifactError
            with self.assertRaises(ArtifactError):service.citation('Company A','revision',1,lock=True)
