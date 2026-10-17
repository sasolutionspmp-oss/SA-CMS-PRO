"""Actual DOC03 Frappe persistence/ACL workflow declared for fresh hosted CI."""
import hashlib,json
from uuid import uuid4
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime
from cipher_aec.api.contracts import canonical_json,digest
from cipher_aec.api.errors import DomainError
from cipher_aec.documents import service as documents
from cipher_aec.document_control import service,repository,contracts as rules,clauses
from cipher_aec.governance import approvals
from cipher_aec.governance.context import trusted_write,current_actor
from cipher_aec.install import seed_synthetic,_grant

class TestDocumentControlNative(IntegrationTestCase):
 def setUp(self):
  super().setUp();frappe.set_user('Administrator');self.savepoint='doc03_'+uuid4().hex;frappe.db.savepoint(self.savepoint);self.fixture=seed_synthetic();self.company=self.fixture['company'];self.users=self.fixture['users'];self.old_request=getattr(frappe.local,'request',None);self.old_sid=getattr(frappe.session,'sid',None)
  with trusted_write():
   self.project=frappe.get_doc({'doctype':'Project','company':self.company,'project_name':'DOC03 integration '+uuid4().hex,'status':'Open'}).insert(ignore_permissions=True).name
   for key in ('primary','reviewer'):
    for ability in ('project.read','document.read',rules.READ,'approval.request','approval.decide','approval.execute'):_grant(self.users[key]['person'],self.company,self.project,ability)
   for ability in (rules.WRITE,rules.MANAGE,rules.ISSUE,rules.ADOPT,rules.DISTRIBUTE,'document.write'):_grant(self.users['primary']['person'],self.company,self.project,ability)
   for ability in (rules.WRITE,rules.REVIEW):_grant(self.users['reviewer']['person'],self.company,self.project,ability)
  self.login('primary')
 def tearDown(self):
  frappe.set_user('Administrator');frappe.local.request=self.old_request;frappe.session.sid=self.old_sid;frappe.db.rollback(save_point=self.savepoint);super().tearDown()
 def login(self,key):
  user=self.users[key]['user'];frappe.set_user(user);sid='synthetic-doc03-test-'+uuid4().hex;frappe.session.sid=sid;frappe.local.request=Request(EnvironBuilder(method='POST',base_url='http://cipher.localhost',headers={'Cookie':'sid='+sid}).get_environ());frappe.db.sql("INSERT INTO tabSessions (user,sid,sessiondata,lastupdate,status) VALUES (%s,%s,%s,%s,'Active')",(user,sid,canonical_json({'user':user}),now_datetime()))
 def upload(self,content,document_id=None):
  result=documents.upload_document(company=self.company,project=self.project,title='Exact retained specification',filename='specification.txt',content=content,byte_length=len(content),sha256=hashlib.sha256(content).hexdigest(),operation_id=str(uuid4()),document_id=document_id,expected_revision=1 if document_id else None)
  return result,{'revision_id':result['revision']['id'],'source_sha256':hashlib.sha256(content).hexdigest()}
 def authorize(self,kind,value):
  packet=approvals.request_action(self.company,self.project,rules.ACTIONS[kind],value['id'],digest(value),str(uuid4()))['packet'];self.assertEqual(packet['schema'],'cipher.document.approval.v1');self.login('alias')
  with self.assertRaises(DomainError):approvals.decide_packet(self.company,self.project,packet['id'],packet['manifest_hash'],'Grant',str(uuid4()),'Alias cannot independently authorize')
  self.login('reviewer');approvals.decide_packet(self.company,self.project,packet['id'],packet['manifest_hash'],'Grant',str(uuid4()),'Independent exact documentary review');self.login('primary');operation=str(uuid4());result=approvals.execute_packet(self.company,self.project,packet['id'],packet['manifest_hash'],operation);replay=approvals.execute_packet(self.company,self.project,packet['id'],packet['manifest_hash'],operation);self.assertTrue(replay['operation']['replayed']);self.assertEqual(result['effect'],replay['effect']);return result['effect'][rules.FACTS[kind]]
 def test_retained_text_independent_adoption_issue_internal_receipt_and_current_rights(self):
  permission_upload,permission_ref=self.upload(b'Synthetic authored permission evidence: internal project use only.');original=b'Exact original contract clause: retain this wording.';uploaded,ref=self.upload(original);doc=uploaded['document']['id'];definition={'ingest_allowed':True,'read_allowed':True,'distribute_allowed':True,'rights_basis':'Synthetic manually authored permission declaration, not verified legal licensing.','rights_holder':'Synthetic declared holder','allowed_purpose':'Project ingestion, retained retrieval and internal coordination','restriction':'No external delivery or legal-execution inference','valid_from':None,'valid_until':None,'evidence_artifact':permission_ref};policy=service.set_rights(self.company,self.project,str(uuid4()),doc,None,definition)['rights']
  library_definition={'title':'Original concrete specification','category':'specification','discipline':'Structural','ownership':'Synthetic declared owner','tags':['concrete'],'change_reason':'Initial original'};operation=str(uuid4());created=service.create_library(self.company,self.project,operation,library_definition,ref);revision=created['library_revision'];request=service.create_adoption(self.company,self.project,str(uuid4()),revision['id'],digest(revision),{'purpose':'Adopt exact original','target_locator':'Project section 03 30 00','change_reason':'Initial adoption'})['adoption_request'];adoption=self.authorize('adoption_request',request)
  target=clauses.read_target(self.company,self.project,'document_revision',ref['revision_id'])['target'];target={**{k:target[k] for k in ('kind','id','record_digest')},'locator':'Exact retained clause paragraph'}
  use=clauses.create_clause_use(self.company,self.project,str(uuid4()),adoption['id'],digest(adoption),{**ref,'page':1,'excerpt_sha256':hashlib.sha256(original).hexdigest(),'start':0,'end':len(original.decode())},target,'Retain exact original clause lineage')['clause_use'];redline_operation=str(uuid4());redline=clauses.create_redline(self.company,self.project,redline_operation,use['id'],digest(use),None,'Exact proposed successor wording.','Independent proposed documentary relationship')['redline'];application=self.authorize('redline',redline);self.assertFalse(application['target_changed']);self.assertEqual(clauses.read_target(self.company,self.project,'document_revision',ref['revision_id'])['target']['record_digest'],target['record_digest']);self.assertTrue(clauses.create_redline(self.company,self.project,redline_operation,use['id'],digest(use),None,'Exact proposed successor wording.','Independent proposed documentary relationship')['operation']['replayed'])
  issuedset=service.create_issue_set(self.company,self.project,str(uuid4()),{'title':'Coordination issue','purpose':'Retained exact specification','issue_purpose':'coordination'},[],[{'id':adoption['id'],'record_digest':digest(adoption)}])['issue_set'];issue=self.authorize('issue_set',issuedset);transmittal=service.create_transmittal(self.company,self.project,str(uuid4()),issue['id'],digest(issue),[self.users['reviewer']['user']],'Review original specification','Acknowledge internal receipt')['transmittal'];distribution=self.authorize('transmittal',transmittal)
  self.login('reviewer');self.assertTrue(service.list_people(self.company,self.project)['items']);self.assertEqual(service.get_record(self.company,self.project,'distribution',distribution['id'])['record'],distribution);evidence=service.record_evidence(self.company,self.project,str(uuid4()),'distribution',distribution['id'],digest(distribution),'Reported internal receipt only',[ref])['evidence'];self.assertEqual(evidence['status'],'reported_received');self.login('primary')
  execution=service.record_evidence(self.company,self.project,str(uuid4()),'adoption',adoption['id'],digest(adoption),'Reported hardcopy execution evidence; no commercial execution command',[ref])['evidence'];self.assertFalse(execution['commercial_execution']);new_upload,newref=self.upload(b'Later source wording.',doc);self.assertFalse(service.get_record(self.company,self.project,'adoption',adoption['id'])['library_current']);service.revise_library(self.company,self.project,str(uuid4()),created['library']['id'],digest(created['library']),{**library_definition,'change_reason':'Explicit successor'},newref)
  self.assertEqual(documents.download_revision(self.company,ref['revision_id'])[1],original);self.assertFalse(service.get_record(self.company,self.project,'adoption',adoption['id'])['library_current']);self.assertEqual(service.read('evidence',execution['id'],self.company,self.project,current_actor()),execution);self.assertEqual(repository.raw('library_revision',revision['id']),revision);self.assertTrue(service.create_library(self.company,self.project,operation,library_definition,ref)['operation']['replayed'])
  record=frappe.get_doc('Cipher Library Revision',revision['id']);self.assertFalse(frappe.has_permission(record.doctype,'read',doc=record,user=frappe.session.user))
  with trusted_write(),self.assertRaises(DomainError):record.save(ignore_permissions=True)
  # Read a fresh native object for any later assertion; failed saves alter in-memory timestamps.
  policy=service.set_rights(self.company,self.project,str(uuid4()),doc,digest(policy),{**definition,'ingest_allowed':False,'distribute_allowed':False,'rights_basis':'Retain read only'})['rights'];self.assertEqual(documents.preview_revision(self.company,ref['revision_id'])['text'],original.decode())
  with self.assertRaises(DomainError):self.upload(b'Ingestion refused.',doc)
  service.set_rights(self.company,self.project,str(uuid4()),doc,digest(policy),{**definition,'ingest_allowed':False,'read_allowed':False,'distribute_allowed':False,'rights_basis':'Current original source rights revoked'})
  for call in (lambda:documents.download_revision(self.company,ref['revision_id']),lambda:documents.preview_revision(self.company,ref['revision_id']),lambda:service.get_record(self.company,self.project,'adoption',adoption['id']),lambda:service.create_library(self.company,self.project,operation,library_definition,ref)):
   with self.assertRaises(DomainError):call()
  self.assertFalse(documents.search_documents(self.company,self.project,'wording'));self.assertFalse(frappe.get_list('Cipher Document Revision',filters={'document':doc},fields=['pages_json']));self.assertEqual(repository.raw('adoption',adoption['id']),adoption);self.assertFalse(issue['professional_seal']);self.assertFalse(distribution['external_delivery']);self.assertEqual(frappe.db.get_value('Project',self.project,'status'),'Open')
