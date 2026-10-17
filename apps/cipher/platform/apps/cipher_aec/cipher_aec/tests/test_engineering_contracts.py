"""Closed schemas, joins, native controller plans and bounded read contracts."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator,FormatChecker
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_engineering import fixtures,add_source,add_person,question,answer,submission,official,uid
ROOT=Path(__file__).parents[1]
SCHEMA=json.loads((ROOT/'engineering/schemas/api-v1.schema.json').read_text())
GENERIC=json.loads((ROOT/'api/schema.json').read_text())
def validate(name,value,schema=SCHEMA):
    Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':schema['$defs']},format_checker=FormatChecker()).validate(value)

class EngineeringContractsTests(unittest.TestCase):
    def test_schemas_closed_references_and_explicit_action_subject_pairing(self):
        Draft202012Validator.check_schema(SCHEMA);Draft202012Validator.check_schema(GENERIC)
        defs=GENERIC['$defs'];self.assertEqual(defs['DomainApprovalPacket']['properties']['action']['enum'],['calibration.verify.v1','contract.baseline.activate.v1','estimate.accept.v1'])
        self.assertEqual(defs['DomainApprovalPacket']['properties']['subject']['properties']['type']['enum'],['Cipher Calibration','Cipher Construction Contract','Cipher Estimate Revision'])
        company=defs['CompanyApprovalPacket']['properties']['action']['enum'];self.assertFalse(any(a.startswith('engineering.') for a in company))
        for name in ('EngineeringResponseApprovalPacket','EngineeringDispositionApprovalPacket','EngineeringTransmittalApprovalPacket'):
            packet=defs[name];self.assertFalse(packet['additionalProperties']);self.assertEqual(packet['properties']['schema']['const'],'cipher.engineering.approval.v1');self.assertIn('const',packet['properties']['action']);self.assertIn('const',packet['properties']['subject']['properties']['type'])
    def test_actual_shaped_workflow_matches_closed_record_and_command_schemas(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            created=service.create_rfi('C','P',uid(),question(),[],[add_source(state,extracted=False)]);validate('EgCreateRfiResponse',created)
            for kind,name in [('rfi','EgRfi'),('rfi_revision','EgRfiRevision')]:validate(name,created[kind if kind=='rfi' else 'revision'])
            response=service.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[]);validate('EgCreateResponseResponse',response)
            fact=official(state,service,gov,'response',response['response']);validate('EgOfficialResponse',fact)
            tx=service.create_transmittal('C','P',uid(),'official_response',fact['id'],digest(fact),[add_person(state,'recipient').user],'Coordination','')['transmittal'];validate('EgTransmittal',tx)
            receipt=official(state,service,gov,'transmittal',tx);validate('EgDistribution',receipt)
            for kind,value in [('rfi',repo.raw('rfi',created['rfi']['id'])),('rfi_revision',created['revision']),('response',response['response']),('official_response',fact),('transmittal',tx),('distribution',receipt)]:rules.record(kind,value)
    def test_official_response_get_and_list_envelopes_accept_canonical_overlapping_shape(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            created=service.create_rfi('C','P',uid(),question(),[],[add_source(state)])
            response=service.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[])['response']
            fact=official(state,service,gov,'response',response)
            result=service.get_record('C','P','official_response',fact['id'])
            validate('EgGetResponse',result)
            validate('EgListResponse',{'items':[result],'next_cursor':None,'limit':25,'count_mode':'none','total':None})
    def test_official_disposition_get_and_list_envelopes_accept_canonical_overlapping_shape(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            reviewer=add_person(state,'technical-reviewer');raw=add_source(state)
            created=service.create_submittal('C','P',uid(),submission(reviewer.user),[{k:raw[k] for k in ('revision_id','source_sha256')}],[])
            state.actor=reviewer
            proposed=service.create_disposition('C','P',uid(),created['submittal']['id'],created['submission']['id'],digest(created['submittal']),{'disposition':'approved','comments':''},[])['disposition']
            fact=official(state,service,gov,'disposition',proposed)
            result=service.get_record('C','P','official_disposition',fact['id'])
            validate('EgGetResponse',result)
            validate('EgListResponse',{'items':[result],'next_cursor':None,'limit':25,'count_mode':'none','total':None})
    def test_engineering_approval_shape_refuses_action_subject_and_effect_spoof(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            created=service.create_rfi('C','P',uid(),question(),[],[add_source(state)]);response=service.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[])['response']
            manifest=gov.approval_manifest(kind='response',actor=state.actor,company='C',project='P',subject_id=response['id'],expected_version=digest(response))
            packet={'schema':'cipher.engineering.approval.v1','id':uid(),'company':'C','project':'P','action':rules.ACTIONS['response'],'subject':{'id':response['id'],'type':rules.KINDS['response'],'label':'RFI response'},'requester':{'id':state.actor.person_id,'display_name':'Author'},'created_at':'2026-10-17T00:00:00Z','expires_at':'2026-10-17T01:00:00Z','manifest_hash':'a'*64,'source_version':digest(response),'policy':{'id':'policy','label':'Exact review','synthetic':True},'state':'Pending','decisions':[],'actions':{'can_decide':False,'can_execute':False,'can_withdraw':True,'disabled_reason':None},'review_manifest':manifest}
            validate('EngineeringApprovalPacket',packet,GENERIC)
            for path,replacement in [('action','proposal.distribute.v1'),('project',None),('subject.type','Cipher Calibration'),('review_manifest.effect.action','engineering.distribute.v1')]:
                bad=deepcopy(packet);target=bad;parts=path.split('.')
                for key in parts[:-1]:target=target[key]
                target[parts[-1]]=replacement
                with self.subTest(path=path),self.assertRaises(Exception):validate('EngineeringApprovalPacket',bad,GENERIC)
    def test_direct_native_metadata_and_exact_writer_plan_are_required(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            created=service.create_rfi('C','P',uid(),question(),[],[add_source(state)]);value=created['revision'];doc=SimpleNamespace(name=value['id'],is_new=lambda:True)
            with self.assertRaises(DomainError) as refusal:repo.require_write(doc,'rfi_revision',value)
            self.assertEqual(refusal.exception.code,'engineering_command_required')
            token=repo._plan.set({'kind':'rfi_revision','id':value['id'],'digest':digest(value),'previous':None})
            try:
                repo.require_write(doc,'rfi_revision',value)
                changed={**value,'status':'forged'}
                with self.assertRaises(DomainError):repo.require_write(doc,'rfi_revision',changed)
            finally:repo._plan.reset(token)
    def test_old_revision_json_cannot_be_changed_or_privilege_fields_added(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            created=service.create_rfi('C','P',uid(),question(),[],[add_source(state)]);value=created['revision']
            for bad in ({**value,'scope_type':'Company'},{**value,'ignore_permissions':True},{**value,'no_effects':{**rules.NO_EFFECTS,'contract_change':True}}):
                with self.assertRaises(DomainError):rules.record('rfi_revision',bad)
    def test_doc_types_use_guarded_native_controllers_and_index_fields(self):
        from cipher_aec.engineering.contracts import KINDS
        for doctype in KINDS.values():
            slug=doctype.lower().replace(' ','_');folder=ROOT/'cipher_engineering/doctype'/slug;value=json.loads((folder/(slug+'.json')).read_text());fields={f['fieldname']:f for f in value['fields']}
            self.assertEqual(value['module'],'Cipher Engineering');self.assertFalse(value['allow_rename']);self.assertIn('EngineeringRecord',(folder/(slug+'.py')).read_text());self.assertEqual(fields['project']['reqd'],1);self.assertEqual(fields['scope_type']['options'],'Project')
            if 'Response Revision' in doctype or 'Disposition Revision' in doctype:self.assertIn('source_revision',fields)
    def test_explicit_engineering_duties_are_not_default_fixture_grants(self):
        import ast
        tree=ast.parse((ROOT/'install.py').read_text());seed=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='seed_synthetic');expressions=[ast.unparse(n.iter) for n in ast.walk(seed) if isinstance(n,ast.For)]
        self.assertIn('sorted(PROJECT_ABILITIES - ENGINEERING_ABILITIES - DOCUMENT_CONTROL_ABILITIES)',expressions)
        self.assertNotIn('sorted(PROJECT_ABILITIES)',expressions)
    def test_bounded_keyset_page_and_scope_cursor_denial(self):
        from cipher_aec.api import paging
        with fixtures() as (state,rules,repo,sources,service,gov):
            values=[]
            for index in range(4):
                result=service.create_rfi('C','P',uid(),question(str(index)),[],[add_source(state)]);values.append(result['revision'])
            ordered=list(reversed(values));calls=[]
            def rows(kind,company,project,parent_id=None,subject_id=None,last=None,limit=25):
                calls.append(limit);start=next((i+1 for i,v in enumerate(ordered) if last and v['id']==last[1]),0)
                return [SimpleNamespace(name=v['id'],creation='2026-10-17 00:00:00') for v in ordered[start:start+limit]]
            with patch.object(repo,'candidate_rows',rows):
                page=service.list_records('C','P','rfi_revision',limit=2);self.assertEqual(len(page['items']),2);self.assertEqual(page['total'],None);self.assertEqual(calls,[25]);self.assertTrue(page['next_cursor'])
                second=service.list_records('C','P','rfi_revision',limit=2,cursor=page['next_cursor']);self.assertFalse(second['next_cursor']);self.assertFalse({v['record']['id'] for v in page['items']} & {v['record']['id'] for v in second['items']})
                state.actor=add_person(state,'different-reader')
                with self.assertRaises(DomainError):service.list_records('C','P','rfi_revision',limit=2,cursor=page['next_cursor'])
    def test_read_refuses_cross_project_and_exact_source_digest_mismatch(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            created=service.create_rfi('C','P',uid(),question(),[],[add_source(state)]);response=service.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[])['response']
            bad=deepcopy(response);bad['source_digest']='0'*64;state.rows['response',bad['id']]=bad
            with self.assertRaises(DomainError):service.read('response',bad['id'],'C','P',state.actor)
            bad['project']='OTHER';state.rows['response',bad['id']]=bad
            with self.assertRaises(DomainError):service.read('response',bad['id'],'C','P',state.actor)


class EngineeringPeopleAndControlTests(unittest.TestCase):
    def test_scoped_people_selector_filters_current_denial_and_binds_cursor(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            one=add_person(state,'one');two=add_person(state,'two');denied=add_person(state,'denied');state.duties[denied.person_id]={'project.read'}
            ordered=sorted([one,two,denied],key=lambda a:(a.person_id,a.user));calls=[]
            def query(sql,args=(),**kwargs):
                calls.append((sql,args));rows=ordered
                if len(args)>2:rows=[a for a in rows if (a.person_id,a.user)>(args[2],args[4])]
                return [SimpleNamespace(user=a.user,person=a.person_id,display_name=a.user.split('@')[0]) for a in rows]
            with patch.object(service.frappe.db,'sql',query):
                first=service.list_people('C','P',limit=1);validate('EgPeopleResponse',first);self.assertEqual(len(first['items']),1);self.assertIsNone(first['total']);self.assertTrue(first['next_cursor'])
                second=service.list_people('C','P',limit=1,cursor=first['next_cursor']);self.assertEqual(len(second['items']),1);self.assertFalse(second['next_cursor']);self.assertNotEqual(first['items'][0]['person'],second['items'][0]['person'])
                self.assertTrue(all(q[1][:2]==['C','P'] and 'LIMIT 25' in q[0] for q in calls))
                state.actor=add_person(state,'other-reader')
                with self.assertRaises(DomainError):service.list_people('C','P',limit=1,cursor=first['next_cursor'])
    def test_recipient_access_rechecked_at_new_distribution_approval(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            created=service.create_rfi('C','P',uid(),question(),[],[add_source(state)]);response=service.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[])['response'];fact=official(state,service,gov,'response',response);recipient=add_person(state,'recipient')
            tx=service.create_transmittal('C','P',uid(),'official_response',fact['id'],digest(fact),[recipient.user],'Coordination','')['transmittal']
            manifest=gov.approval_manifest(kind='transmittal',actor=state.actor,company='C',project='P',subject_id=tx['id'],expected_version=digest(tx));self.assertEqual(manifest['effect']['recipients'],tx['recipients'])
            state.duties[recipient.person_id]={'project.read'}
            with self.assertRaises(DomainError):gov.authorize_subject(kind='transmittal',actor=add_person(state,'independent'),company='C',project='P',subject_id=tx['id'],phase='review')
    def test_package_and_approval_subject_tamper_fail_closed(self):
        with fixtures() as (state,rules,repo,sources,service,gov):
            created=service.create_rfi('C','P',uid(),question(),[],[add_source(state)]);response=service.create_response('C','P',uid(),created['rfi']['id'],created['revision']['id'],digest(created['rfi']),answer(),[])['response'];fact=official(state,service,gov,'response',response)
            tx=service.create_transmittal('C','P',uid(),'official_response',fact['id'],digest(fact),[add_person(state,'recipient').user],'Coordination','')['transmittal'];state.rows['transmittal',tx['id']]['purpose']='Unreviewed replacement'
            with self.assertRaises(DomainError):service.read('transmittal',tx['id'],'C','P',state.actor)
            manifest={'effect':{'schema':'cipher.engineering.authorization.v1','action':'engineering.distribute.v1','subject_kind':'response','subject_id':response['id'],'subject_digest':digest(response)}}
            with self.assertRaises(DomainError):gov.authorize_subject(kind='response',actor=state.actor,company='C',project='P',subject_id=response['id'],phase='receipt',manifest=manifest)

if __name__=='__main__':unittest.main()
