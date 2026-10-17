"""Exact Company scope uses canonical source bytes and cannot widen Project scope."""
import json
from pathlib import Path
import tempfile
import unittest

from cipher_aec.documents.core import DocumentService
from cipher_aec.documents.extraction import ArtifactError, digest
from cipher_aec.documents.storage import LocalArtifactStorage
from cipher_aec.tests.test_documents import MemoryMetadata, pdf_bytes


class CompanyDocuments(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.repo=MemoryMetadata();self.storage=LocalArtifactStorage(self.directory.name)
        self.permissions={('Company','A',None,'document.read'),('Company','A',None,'document.write'),('Project','A','P','document.read'),('Project','A','P','document.write')}
        self.calls=[]
        def authorizer(kind):
            def authorize(company,project,ability):
                value=(kind,company,project,ability);self.calls.append(value)
                if value not in self.permissions:raise PermissionError('Current exact scope denied')
            return authorize
        self.company=DocumentService(self.repo,self.storage,authorizer('Company'),allow_unscanned=True,scope_type='Company')
        self.project=DocumentService(self.repo,self.storage,authorizer('Project'),allow_unscanned=True)

    def upload(self,service=None,content=b'Company-only concrete strength is 4500 psi.\fApproval uses exact retained evidence.',**kwargs):
        service=service or self.company
        values=dict(company='A',project=None if service is self.company else 'P',title='Authored source',filename='source.txt',content=content,byte_length=len(content),sha256=digest(content))
        values.update(kwargs)
        return service.upload(**values)

    def test_company_pdf_and_text_use_same_bytes_citations_and_page_preview(self):
        content=pdf_bytes(['Company construction note 4500 psi','Second page of retained scope'])
        result=self.upload(content=content,filename='scope.pdf')
        rid=result['revision']['id']
        self.assertEqual(result['document']['scope_type'],'Company')
        self.assertIsNone(result['document']['project'])
        citation=self.company.citation('A',rid,2)
        self.assertEqual(citation['scope_type'],'Company')
        self.assertEqual(citation['company'],'A');self.assertIsNone(citation['project'])
        self.assertIn('Second page',citation['excerpt'])
        self.assertEqual(self.company.download('A',rid)[1],content)
        self.assertEqual(self.company.preview('A',rid,2)['content_type'],'text/plain')
        self.assertEqual(self.company.search('A',None,'4500')[0]['revision_id'],rid)
        self.assertEqual(self.company.source_reference('A',None,rid,2,lock=True)['content'],content)

    def test_scopes_are_mutually_exclusive_even_with_both_duties(self):
        company=self.upload();project=self.upload(self.project)
        for service,result in ((self.project,company),(self.company,project)):
            for call in (lambda:service.detail('A',result['document']['id']),lambda:service.citation('A',result['revision']['id'],1),lambda:service.download('A',result['revision']['id'])):
                with self.assertRaisesRegex(ArtifactError,'outside the requested scope'):call()
        self.assertEqual([r['id'] for r in self.company.list('A',None)],[company['document']['id']])
        self.assertEqual([r['id'] for r in self.project.list('A','P')],[project['document']['id']])
        # Existing Project responses and citation checksum inputs remain identical.
        self.assertNotIn('scope_type',project['document']);self.assertNotIn('scope_type',project['revision'])
        cited=self.project.citation('A',project['revision']['id'],1)
        self.assertNotIn('scope_type',cited)
        self.assertEqual(cited['id'],digest(json.dumps([cited['revision_id'],1,cited['excerpt_sha256']],separators=(',',':')).encode()))

    def test_absent_project_is_never_implicit_company_and_invalid_scope_fails_closed(self):
        with self.assertRaises(ArtifactError):self.upload(self.project,project=None)
        self.assertEqual(self.calls,[])
        result=self.upload();rid=result['revision']['id']
        with self.assertRaises(ArtifactError):self.company.citation('B',rid,1)
        self.repo.revs[rid]['project']='P'
        with self.assertRaises(ArtifactError):self.company.citation('A',rid,1)
        with self.assertRaises(ArtifactError):self.project.citation('A',rid,1)

    def test_company_read_revocation_preserves_project_access_and_blocks_original_bytes(self):
        company=self.upload();project=self.upload(self.project)
        rid=company['revision']['id'];cited=self.company.citation('A',rid,1)
        self.permissions.remove(('Company','A',None,'document.read'))
        for call in (lambda:self.company.citation('A',rid,1,cited['excerpt_sha256']),lambda:self.company.download('A',rid),lambda:self.company.list('A',None),lambda:self.company.search('A',None,'concrete'),lambda:self.company.source_reference('A',None,rid,1)):
            with self.assertRaises(PermissionError):call()
        self.assertIn('concrete',self.project.citation('A',project['revision']['id'],1)['excerpt'])

    def test_retained_citations_current_head_and_actual_integrity(self):
        first=self.upload();did,rid=first['document']['id'],first['revision']['id']
        citation=self.company.citation('A',rid,1)
        second=self.upload(content=b'Updated concrete strength is 5000 psi.',document_id=did,expected_revision=1)
        self.assertEqual(self.company.citation('A',rid,1),citation)
        self.assertFalse(self.company.source_reference('A',None,rid,1)['is_current'])
        self.assertTrue(self.company.source_reference('A',None,second['revision']['id'],1)['is_current'])
        self.assertEqual(self.company.search('A',None,'4500'),[])
        with self.assertRaises(ArtifactError):self.upload(document_id=did,expected_revision=1)
        (Path(self.directory.name)/rid).write_bytes(b'altered source')
        with self.assertRaisesRegex(ArtifactError,'integrity'):self.company.citation('A',rid,1)
