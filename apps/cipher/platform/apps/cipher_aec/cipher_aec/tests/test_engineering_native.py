"""Actual Frappe ENG-01 persistence/permissions workflow; discovered by integration CI.

Explicit new duties belong only to this rollback-isolated test Project. No HTTP,
external delivery, model, financial document or production fixture is exercised.
"""
from copy import deepcopy
from datetime import datetime
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
from cipher_aec.engineering import service,repository
from cipher_aec.governance import approvals
from cipher_aec.governance.commands import read_operation
from cipher_aec.governance.context import trusted_write,current_actor
from cipher_aec.install import seed_synthetic,_grant,set_synthetic_duty


def vector_pdf():
    stream=b'80 80 m 480 80 l S\n'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> /Contents 4 0 R >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'endstream']
    data=b'%PDF-1.4\n';offsets=[]
    for index,obj in enumerate(objects,1):offsets.append(len(data));data+=str(index).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    xref=len(data);data+=('xref\n0 5\n0000000000 65535 f \n'+''.join(f'{n:010d} 00000 n \n' for n in offsets)+'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n'+str(xref)+'\n%%EOF\n').encode();return data

class TestEngineeringNative(IntegrationTestCase):
    def setUp(self):
        super().setUp();frappe.set_user('Administrator');self.savepoint='engineering_'+uuid4().hex;frappe.db.savepoint(self.savepoint)
        self.fixture=seed_synthetic();self.company=self.fixture['company'];self.users=self.fixture['users']
        self.old_request=getattr(frappe.local,'request',None);self.old_sid=getattr(frappe.session,'sid',None)
        with trusted_write():
            project=frappe.get_doc({'doctype':'Project','company':self.company,'project_name':'ENG01 integration '+uuid4().hex,'status':'Open'}).insert(ignore_permissions=True);self.project=project.name
            # Engineering duties are deliberately absent from seed defaults.
            for key in ('primary','reviewer','outsider'):
                for ability in ('project.read','document.read','engineering.read','engineering.write','engineering.distribute','approval.request','approval.decide','approval.execute'):
                    _grant(self.users[key]['person'],self.company,self.project,ability)
            _grant(self.users['primary']['person'],self.company,self.project,'document.write')
        self.login('primary');content=vector_pdf()
        uploaded=upload_document(company=self.company,project=self.project,title='Original no-text engineering drawing',filename='engineering-vector.pdf',content=content,byte_length=len(content),sha256=hashlib.sha256(content).hexdigest(),operation_id=str(uuid4()))
        self.drawing={'revision_id':uploaded['revision']['id'],'source_sha256':hashlib.sha256(content).hexdigest(),'page':1,'locator':'Grid A / Detail 2'}
        self.assertEqual(uploaded['revision']['extraction_status'],'ocr_unavailable')
    def tearDown(self):
        frappe.set_user('Administrator');frappe.local.request=self.old_request;frappe.session.sid=self.old_sid;frappe.db.rollback(save_point=self.savepoint);super().tearDown()
    def login(self,key):
        user=self.users[key]['user'];frappe.set_user(user);sid='synthetic-eng01-test-'+uuid4().hex;frappe.session.sid=sid
        frappe.local.request=Request(EnvironBuilder(method='POST',base_url='http://cipher.localhost',headers={'Cookie':'sid='+sid}).get_environ())
        frappe.db.sql("INSERT INTO tabSessions (user,sid,sessiondata,lastupdate,status) VALUES (%s,%s,%s,%s,'Active')",(user,sid,canonical_json({'user':user}),now_datetime()))
    def rfi_definition(self,subject='Bearing query'):
        return {'subject':subject,'question':'Confirm the original drawing bearing detail.','responsible_users':[],'due_date':None,'location':'Pier 2','contract_citation_ids':[]}
    def grant_execute(self,kind,record,requester='primary',checker='reviewer'):
        actions={'response':'engineering.rfi.authorize.v1','disposition':'engineering.submittal.authorize.v1','transmittal':'engineering.distribute.v1'}
        self.login(requester);packet=approvals.request_action(self.company,self.project,actions[kind],record['id'],digest(record),str(uuid4()))['packet']
        self.assertEqual(packet['schema'],'cipher.engineering.approval.v1')
        self.login(checker);approvals.decide_packet(self.company,self.project,packet['id'],packet['manifest_hash'],'Grant',str(uuid4()),'Reviewed exact immutable technical package')
        self.login(requester);operation=str(uuid4());result=approvals.execute_packet(self.company,self.project,packet['id'],packet['manifest_hash'],operation)
        replay=approvals.execute_packet(self.company,self.project,packet['id'],packet['manifest_hash'],operation)
        self.assertTrue(replay['operation']['replayed']);self.assertEqual(result['effect'],replay['effect']);return next(iter(result['effect'].values()))
    def test_immutable_rfi_submittal_independent_officials_internal_receipt_and_replay(self):
        before={n:frappe.db.count(n) for n in ('Sales Order','Sales Invoice','Purchase Order','Journal Entry')}
        operation=str(uuid4());created=service.create_rfi(self.company,self.project,operation,self.rfi_definition(),[],[self.drawing]);header,question=created['rfi'],created['revision']
        self.assertEqual(service.get_record(self.company,self.project,'rfi_revision',question['id'])['record'],question)
        # Neither native permission nor ignore_permissions + trusted_write is a writer.
        doc=frappe.get_doc('Cipher RFI Revision',question['id']);self.assertFalse(frappe.has_permission(doc.doctype,'read',doc=doc,user=frappe.session.user))
        with self.assertRaises(DomainError):doc.save(ignore_permissions=True)
        with trusted_write(),self.assertRaises(DomainError):doc.save(ignore_permissions=True)
        response=service.create_response(self.company,self.project,str(uuid4()),header['id'],question['id'],digest(header),{'answer':'Use the referenced technical detail.','potential_cost_impact':'Separate commercial decision required.','potential_schedule_impact':''},[])['response']
        packet=approvals.request_action(self.company,self.project,'engineering.rfi.authorize.v1',response['id'],digest(response),str(uuid4()))['packet']
        self.login('alias')
        with self.assertRaises(DomainError):approvals.decide_packet(self.company,self.project,packet['id'],packet['manifest_hash'],'Grant',str(uuid4()),'Alias cannot grant')
        self.login('primary');answer=self.grant_execute('response',response)
        self.assertEqual(repository.raw('rfi_revision',question['id']),question)
        tx=service.create_transmittal(self.company,self.project,str(uuid4()),'official_response',answer['id'],digest(answer),[self.users['reviewer']['user']],'For internal coordination','Acknowledge exact package')['transmittal']
        receipt=self.grant_execute('transmittal',tx);self.assertFalse(receipt['external_delivery']);self.assertEqual(receipt['package_digest'],tx['package_digest'])
        self.login('reviewer');self.assertEqual(service.get_record(self.company,self.project,'distribution',receipt['id'])['record'],receipt)
        self.login('primary');current=repository.raw('rfi',header['id']);successor=service.revise_rfi(self.company,self.project,str(uuid4()),header['id'],digest(current),self.rfi_definition('Successor question'),[],[self.drawing])
        replay=service.create_rfi(self.company,self.project,operation,self.rfi_definition(),[],[self.drawing]);self.assertTrue(replay['operation']['replayed']);self.assertEqual(replay['revision'],question)
        self.assertEqual(read_operation(self.company,self.project,operation)['revision'],question)
        definition={'title':'Bearing assembly','specification_section':'05 12 00','equipment_tag':'','required_date':None,'contractor':'Synthetic contractor','reviewer_user':self.users['reviewer']['user'],'submission_standing':'submitted'}
        submitted=service.create_submittal(self.company,self.project,str(uuid4()),definition,[{k:self.drawing[k] for k in ('revision_id','source_sha256')}],[])
        self.login('reviewer');disposition=service.create_disposition(self.company,self.project,str(uuid4()),submitted['submittal']['id'],submitted['submission']['id'],digest(submitted['submittal']),{'disposition':'approved_as_noted','comments':''},[])['disposition']
        official=self.grant_execute('disposition',disposition,requester='reviewer',checker='outsider');self.assertEqual(repository.raw('disposition',disposition['id'])['definition']['comments'],'')
        self.assertEqual(service.get_record(self.company,self.project,'official_disposition',official['id'])['record'],official)
        page=service.list_records(self.company,self.project,'rfi_revision',header['id'],1);self.assertIsNone(page['total']);self.assertEqual(len(page['items']),1);self.assertTrue(page['next_cursor'])
        self.assertEqual({n:frappe.db.count(n) for n in before},before);self.assertEqual(frappe.db.get_value('Project',self.project,'status'),'Open')
        self.assertEqual(frappe.db.count('Cipher Engineering Distribution Receipt',{'project':self.project}),1)
        self.login('primary');frappe.set_user('Administrator');set_synthetic_duty(self.users['primary']['user'],self.project,'document.read',0);self.login('primary')
        with self.assertRaises(DomainError):service.create_rfi(self.company,self.project,operation,self.rfi_definition(),[],[self.drawing])
        self.assertEqual(frappe.db.count('Cipher RFI Revision',{'project':self.project}),2)
