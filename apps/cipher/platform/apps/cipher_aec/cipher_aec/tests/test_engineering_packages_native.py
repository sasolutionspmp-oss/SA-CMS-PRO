"""Actual Frappe ENG-02 workflow declared for installation CI, never host-mocked."""
import hashlib
import json
from uuid import uuid4
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime
from cipher_aec.api.contracts import canonical_json,digest
from cipher_aec.api.errors import DomainError
from cipher_aec.documents.service import upload_document
from cipher_aec.engineering_packages import service,repository
from cipher_aec.estimating.service import register_unit
from cipher_aec.governance import approvals
from cipher_aec.governance.context import trusted_write
from cipher_aec.install import seed_synthetic,_grant
from cipher_aec.tests.test_engineering_native import vector_pdf

class TestEngineeringPackagesNative(IntegrationTestCase):
 def setUp(self):
  super().setUp();frappe.set_user('Administrator');self.savepoint='eng02_'+uuid4().hex;frappe.db.savepoint(self.savepoint);self.fixture=seed_synthetic();self.company=self.fixture['company'];self.users=self.fixture['users'];self.old_request=getattr(frappe.local,'request',None);self.old_sid=getattr(frappe.session,'sid',None)
  with trusted_write():
   self.project=frappe.get_doc({'doctype':'Project','company':self.company,'project_name':'ENG02 integration '+uuid4().hex,'status':'Open'}).insert(ignore_permissions=True).name
   for key in ('primary','reviewer'):
    for ability in ('project.read','document.read','engineering.package.read','approval.request','approval.decide','approval.execute'):_grant(self.users[key]['person'],self.company,self.project,ability)
   for ability in ('engineering.package.write','document.write'):_grant(self.users['primary']['person'],self.company,self.project,ability)
   _grant(self.users['reviewer']['person'],self.company,self.project,'engineering.package.check')
   # Native UOM read remains separate from Cipher package duties.
   from frappe.permissions import add_permission,update_permission_property
   role='ENG02 unit reader '+uuid4().hex
   frappe.get_doc({'doctype':'Role','role_name':role}).insert(ignore_permissions=True)
   add_permission('UOM',role,0);update_permission_property('UOM',role,0,'read',1)
   for key in ('primary','reviewer'):
    account=frappe.get_doc('User',self.users[key]['user']);account.append('roles',{'role':role});account.save(ignore_permissions=True);frappe.clear_cache(user=account.name)
   admin=frappe.db.get_value('Cipher Identity Binding',{'user':'Administrator','active':1},'person')
   for ability in ('project.read','estimate.read','estimate.write'):_grant(admin,self.company,self.project,ability)
   self.uom=frappe.get_doc({'doctype':'UOM','uom_name':'ENG02 metre '+uuid4().hex,'symbol':'m','enabled':1,'must_be_whole_number':0}).insert(ignore_permissions=True).name
  self.unit=register_unit(self.company,self.project,str(uuid4()),self.uom,'length',6)['unit']['id'];self.login('primary');content=vector_pdf();uploaded=upload_document(company=self.company,project=self.project,title='Exact no-text design basis',filename='eng02-vector.pdf',content=content,byte_length=len(content),sha256=hashlib.sha256(content).hexdigest(),operation_id=str(uuid4()));self.source={'revision_id':uploaded['revision']['id'],'source_sha256':hashlib.sha256(content).hexdigest(),'page':1,'locator':'Grid A / Detail 2'}
 def tearDown(self):
  frappe.set_user('Administrator');frappe.local.request=self.old_request;frappe.session.sid=self.old_sid;frappe.db.rollback(save_point=self.savepoint)
  for key in ('primary','reviewer'):frappe.clear_cache(user=self.users[key]['user'])
  frappe.clear_cache(doctype='UOM');super().tearDown()
 def login(self,key):
  user=self.users[key]['user'];frappe.set_user(user);sid='synthetic-eng02-test-'+uuid4().hex;frappe.session.sid=sid;frappe.local.request=Request(EnvironBuilder(method='POST',base_url='http://cipher.localhost',headers={'Cookie':'sid='+sid}).get_environ());frappe.db.sql("INSERT INTO tabSessions (user,sid,sessiondata,lastupdate,status) VALUES (%s,%s,%s,%s,'Active')",(user,sid,canonical_json({'user':user}),now_datetime()))
 def quantity(self,key,amount):return {'key':key,'label':'Authored design length','quantity':{'amount':amount,'unit_id':self.unit,'precision':6},'source':dict(self.source)}
 def grant(self,kind,value):
  action={'basis':'engineering.basis.check.v1','calculation':'engineering.calculation.check.v1','deliverable':'engineering.deliverable.check.v1'}[kind];packet=approvals.request_action(self.company,self.project,action,value['id'],digest(value),str(uuid4()))['packet'];self.assertEqual(packet['schema'],'cipher.engineering.package-approval.v1');self.login('alias')
  with self.assertRaises(DomainError):approvals.decide_packet(self.company,self.project,packet['id'],packet['manifest_hash'],'Grant',str(uuid4()),'Alias cannot check')
  self.login('reviewer');approvals.decide_packet(self.company,self.project,packet['id'],packet['manifest_hash'],'Grant',str(uuid4()),'Independent exact authored check');self.login('primary');operation=str(uuid4());result=approvals.execute_packet(self.company,self.project,packet['id'],packet['manifest_hash'],operation);replay=approvals.execute_packet(self.company,self.project,packet['id'],packet['manifest_hash'],operation);self.assertTrue(replay['operation']['replayed']);self.assertEqual(result['effect'],replay['effect']);return result['effect']['check']
 def test_exact_manual_workflow_independent_checks_and_no_issue_effect(self):
  definition={'title':'Bearing design work package','discipline':'Structural','scope':'Manual authored quantities and checked evidence','responsible_user':self.users['primary']['user'],'checker_user':self.users['reviewer']['user'],'due_date':None,'task_ids':[],'wbs_ids':[]};created=service.create_package(self.company,self.project,str(uuid4()),definition)
  # Package-only duties support choices without RFI/estimating capabilities.
  self.assertTrue(frappe.has_permission('UOM','read',doc=frappe.get_doc('UOM',self.uom),user=self.users['primary']['user']))
  self.assertTrue(service.list_people(self.company,self.project,'checker')['items'])
  selected=set();cursor=None
  for _ in range(20):
   page=service.list_units(self.company,self.project,cursor=cursor);self.assertIsNone(page['total']);self.assertLessEqual(len(page['items']),25);selected.update(v['id'] for v in page['items']);cursor=page['next_cursor']
   if not cursor:break
  self.assertIn(self.unit,selected)
  authored=service.create_basis(self.company,self.project,str(uuid4()),created['package']['id'],digest(created['package']),{'title':'Bearing geometry basis','criteria':'Exact source detail','assumptions':'','design_codes':[{'code':'Declared engineering reference','edition':'2026','clause':'A'}],'change_reason':'Initial authored basis'},[self.quantity('length','2.500000')],[],[self.source],[]);basis=authored['basis'];basis_check=self.grant('basis',basis)
  calculated=service.create_calculation(self.company,self.project,str(uuid4()),basis['parent_id'],digest(authored['package']),basis['id'],digest(basis),{'title':'Manual bearing result','method':'human-authored-results-v1','algorithm_reference':'Authored worksheet section A','tool_name':'Human authored worksheet','tool_version':'1','model_version':'','design_codes':[],'explanation':'Recorded human result without solver execution','change_reason':'Initial authored result'},['length'],[self.quantity('result','3.750000')],[{k:self.source[k] for k in ('revision_id','source_sha256')}]);calc=calculated['calculation'];self.assertEqual(calc['inputs'],basis['quantities']);calc_check=self.grant('calculation',calc)
  delivered=service.create_deliverable(self.company,self.project,str(uuid4()),basis['parent_id'],digest(calculated['package']),basis['id'],digest(basis),{'title':'Working design deliverable','deliverable_type':'drawing/specification','description':'Exact linked sources and manual calculation','checking_notes':'','change_reason':'Initial working deliverable'},[{'id':calc['id'],'record_digest':digest(calc)}],[],[self.source],[{k:self.source[k] for k in ('revision_id','source_sha256')}]);deliverable=delivered['deliverable'];deliverable_check=self.grant('deliverable',deliverable)
  for kind,value in [('basis',basis),('calculation',calc),('deliverable',deliverable)]:
   actual=service.get_record(self.company,self.project,kind,value['id']);self.assertEqual(actual['record'],value);self.assertEqual(actual['review']['state'],'checked');self.assertFalse(actual['review']['issue_authorized']);doc=frappe.get_doc(repository.KINDS[kind],value['id'])
   self.assertFalse(frappe.has_permission(doc.doctype,'read',doc=doc,user=frappe.session.user))
   with trusted_write(),self.assertRaises(DomainError):doc.save(ignore_permissions=True)
  self.assertEqual(calc['issue_readiness'],'not_authorized_for_issue');self.assertEqual(deliverable['issue_readiness'],'not_authorized_for_issue');self.assertEqual(frappe.db.count('Cipher Engineering Check Revision',{'project':self.project}),3);self.assertEqual(frappe.db.get_value('Project',self.project,'status'),'Open')
  original=repository.raw('basis',basis['id']);newbasis=service.create_basis(self.company,self.project,str(uuid4()),basis['parent_id'],digest(delivered['package']),{**basis['definition'],'change_reason':'Explicit successor'},[self.quantity('length','4.250000')],[],[self.source],[]);self.assertEqual(repository.raw('basis',basis['id']),original);self.assertEqual(newbasis['basis']['predecessor'],basis['id']);self.assertEqual(service.read('check',calc_check['id'],self.company,self.project,__import__('cipher_aec.governance.context',fromlist=['current_actor']).current_actor()),calc_check)
