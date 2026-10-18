"""Prepared native qualification. Run only after root integrates all fragments.

Not executed by the source lane. Each case owns one rollback-isolated Project.
No provider, award, financial, payroll, offline, or operational permit effect.
"""
import base64
from copy import deepcopy
import hashlib
from uuid import uuid4
from unittest.mock import patch
import frappe
from frappe.model.document import Document
from frappe.tests import IntegrationTestCase
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.documents import service as documents
from cipher_aec.document_control import service as document_control
from cipher_aec.document_control import lifecycle
from cipher_aec.governance.commands import read_operation
from cipher_aec.governance.context import trusted_write
from cipher_aec.install import _grant,seed_synthetic,set_synthetic_duty
from cipher_aec.quality_safety import contracts as rules,service,evidence,privacy
from cipher_aec.tests import test_field_native as field_fixture
from cipher_aec.tests.test_quality_safety import definition

class TestQualitySafetyNative(IntegrationTestCase):
    login=field_fixture.TestFieldNative.login
    upload=field_fixture.TestFieldNative.upload
    permission_definition=field_fixture.TestFieldNative.permission_definition
    locator=field_fixture.TestFieldNative.locator

    def setUp(self):
        super().setUp();frappe.set_user('Administrator');self.savepoint='quality_safety_'+uuid4().hex;frappe.db.savepoint(self.savepoint)
        self.fixture=seed_synthetic();self.company=self.fixture['company'];self.users=self.fixture['users']
        self.old_request=getattr(frappe.local,'request',None);self.old_sid=getattr(frappe.session,'sid',None)
        with trusted_write():
            self.project=frappe.get_doc({'doctype':'Project','company':self.company,'project_name':'FLD03 synthetic native '+uuid4().hex,'status':'Open'}).insert(ignore_permissions=True).name
            for key in ('primary','reviewer','outsider'):
                for ability in ('project.read','document.read','document.control.read','quality.read','quality.write','quality.check','quality.close'):_grant(self.users[key]['person'],self.company,self.project,ability)
            for key in ('primary','reviewer'):
                for ability in rules.ABILITIES|{'document.write','document.rights.manage','document.control.read'}:_grant(self.users[key]['person'],self.company,self.project,ability)
        self.login('primary');self.permission_upload,self.permission_ref=self.upload(b'Authored synthetic internal content permission. No incident details.','permission.txt')
        self.rights_definition=self.permission_definition(self.permission_ref)
        # The private-upload permission proof also needs an explicit current basis.
        second,second_ref=self.upload(b'Separate synthetic permission for the upload permission proof.','permission-basis.txt')
        document_control.set_rights(self.company,self.project,str(uuid4()),self.permission_upload['document']['id'],None,self.permission_definition(second_ref))
        self.source_upload,self.source=self.upload(b'Ordinary non-sensitive documentary finding.','finding.txt')
        document_control.set_rights(self.company,self.project,str(uuid4()),self.source_upload['document']['id'],None,self.rights_definition)

    def tearDown(self):
        frappe.set_user('Administrator');frappe.local.request=self.old_request;frappe.session.sid=self.old_sid;frappe.db.rollback(save_point=self.savepoint);super().tearDown()

    def create(self,category='deficiency',operation=None):
        return service.create_record(self.company,self.project,operation or str(uuid4()),'record',category,definition('record',category),[self.locator()])

    def step(self,result,action,operation=None):
        closure=[{'item_id':r['item_id'],'evidence':[self.locator()]} for r in result['revision']['definition']['required_closure_items']] if action=='close' else []
        return service.transition(self.company,self.project,operation or str(uuid4()),result['family'],result['header']['id'],digest(result['header']),action,'Synthetic documentary '+action,[self.locator()] if action=='check' else [],closure)

    def test_native_three_person_closure_alias_denial_and_exact_amendment(self):
        first=self.create();original=deepcopy(first['revision']);submitted=self.step(first,'submit');self.login('alias')
        with self.assertRaises(DomainError):self.step(submitted,'check')
        self.login('reviewer');checked=self.step(submitted,'check')
        with self.assertRaises(DomainError):self.step(checked,'close')
        self.login('outsider');closed=self.step(checked,'close');self.assertEqual(closed['header']['closed_revision'],original['id'])
        self.login('primary');amended=service.revise_record(self.company,self.project,str(uuid4()),'record',first['header']['id'],digest(closed['header']),definition(),[self.locator()],'Corrected documentary finding.')
        self.assertEqual(amended['revision']['amendment_of'],original['id']);self.assertEqual(service.get_record(self.company,self.project,'revision',original['id'])['record'],original)

    def test_private_source_creation_denied_derivatives_native_lists_and_revoked_receipt(self):
        content=b'Restricted synthetic incident witness account.';operation=str(uuid4())
        private=evidence.upload_evidence(self.company,self.project,operation,'Restricted synthetic evidence','restricted.txt',base64.b64encode(content).decode(),len(content),hashlib.sha256(content).hexdigest(),'Authored synthetic rights basis',[self.locator(self.permission_ref,'Exact upload permission')])
        self.assertIsNotNone(privacy.registration(private['document']['id']));self.assertIsNone(private['history_id'])
        private_rights=document_control.set_rights(self.company,self.project,str(uuid4()),private['document']['id'],None,self.rights_definition)['rights']
        ref={'revision_id':private['revision']['id'],'source_sha256':private['revision']['sha256'],'page':1,'locator':'Restricted witness account'}
        incident=service.create_record(self.company,self.project,str(uuid4()),'incident','incident',definition('incident','incident'),[ref])
        self.login('outsider')
        for callback in (lambda:documents.download_revision(self.company,ref['revision_id']),lambda:documents.preview_revision(self.company,ref['revision_id']),lambda:documents.get_citation(self.company,ref['revision_id'],1),lambda:service.get_record(self.company,self.project,'incident',incident['header']['id']),lambda:lifecycle.get_standing(self.company,self.project,private['document']['id']),lambda:document_control.get_record(self.company,self.project,'rights',private_rights['id'])):
            with self.assertRaises(DomainError):callback()
        self.assertNotIn(private['document']['id'],[row['id'] for row in documents.list_documents(self.company,self.project)['items']])
        self.assertEqual(documents.search_documents(self.company,self.project,'witness'),[])
        for doctype in (*rules.KINDS.values(),privacy.DOCTYPE):
            self.assertEqual(frappe.get_list(doctype,filters={'project':self.project},fields=['name','data_json']),[])
        revision=frappe.get_doc('Cipher Document Revision',ref['revision_id']);file=frappe.get_doc('File',revision.storage_reference)
        self.assertFalse(file.is_downloadable());self.assertFalse(frappe.has_permission('File','read',doc=file))
        frappe.set_user('Administrator');set_synthetic_duty(self.users['primary']['user'],self.project,'safety.incident.read',0);self.login('primary')
        with self.assertRaises(DomainError):read_operation(self.company,self.project,operation)

    def test_late_native_receipt_failure_rolls_back_fact_decision_and_history(self):
        first=self.create();submitted=self.step(first,'submit');self.login('reviewer');before={dt:frappe.db.count(dt,{'project':self.project}) for dt in (*rules.KINDS.values(),'Cipher History Event','Cipher Command Receipt')};insert=Document.insert
        def fail_receipt(doc,*args,**kwargs):
            if doc.doctype=='Cipher Command Receipt':raise RuntimeError('Synthetic late receipt failure')
            return insert(doc,*args,**kwargs)
        with patch.object(Document,'insert',fail_receipt),self.assertRaises(RuntimeError):self.step(submitted,'check')
        self.assertEqual({dt:frappe.db.count(dt,{'project':self.project}) for dt in before},before)

    def test_native_permit_stays_documentary(self):
        first=self.create('permit_record');submitted=self.step(first,'submit');self.login('reviewer');checked=self.step(submitted,'check');self.login('outsider');closed=self.step(checked,'close')
        self.assertFalse(closed['decision']['no_effects']['hazardous_work_authority']);self.assertFalse(closed['decision']['no_effects']['regulatory_approval'])
