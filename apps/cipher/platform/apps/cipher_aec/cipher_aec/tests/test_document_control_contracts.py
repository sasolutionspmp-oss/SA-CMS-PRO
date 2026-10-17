"""Published closed DOC03 wire contracts and preserved existing boundary checks."""
from copy import deepcopy
import ast,json
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator,FormatChecker
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_document_control import permission,fixture,library,source,person,adopted,authorize
from cipher_aec.tests.test_engineering import uid
ROOT=Path(__file__).parents[1]
SCHEMA=json.loads((ROOT/'document_control/schemas/api-v1.schema.json').read_text());CORE=json.loads((ROOT/'api/schema.json').read_text())
def validate(name,value,schema=SCHEMA):Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':schema['$defs']},format_checker=FormatChecker()).validate(value)

class DocumentaryContractTests(unittest.TestCase):
    def test_every_persisted_kind_matches_exact_published_read_shape(self):
        with fixture() as (s,r,repo,rights,service,gov):
            created,ref,adoption,checker=adopted(s,r,service,gov);issue_set=service.create_issue_set('C','P',uid(),{'title':'Exact issue','purpose':'Coordination','issue_purpose':'coordination'},[],[{'id':adoption['id'],'record_digest':digest(adoption)}])['issue_set'];issued=authorize(s,r,gov,'issue_set',issue_set,checker);transmittal=service.create_transmittal('C','P',uid(),issued['id'],digest(issued),[checker.user],'Review','')['transmittal'];distribution=authorize(s,r,gov,'transmittal',transmittal,checker);service.record_evidence('C','P',uid(),'adoption',adoption['id'],digest(adoption),'Reported exact documentary evidence only',[ref])
            for (kind,name),value in s.rows.items():
                with self.subTest(kind=kind):validate('DcGetResponse',service.get_record('C','P',kind,name))
            self.assertEqual({kind for kind,_ in s.rows},{'rights','library','library_revision','adoption_request','adoption','issue_set','issue','transmittal','distribution','evidence'});self.assertEqual(set(r.KINDS),set(SCHEMA['$defs']['DcGetRecordRequest']['properties']['kind']['enum']))
    def test_three_literal_approval_pairings_and_authorized_effects_validate(self):
        Draft202012Validator.check_schema(SCHEMA);Draft202012Validator.check_schema(CORE)
        with fixture() as (s,r,repo,rights,service,gov):
            created,ref=library(s,service);adoption_request=service.create_adoption('C','P',uid(),created['library_revision']['id'],digest(created['library_revision']),{'purpose':'Adopt','target_locator':'Contract clause 3','change_reason':'Initial'})['adoption_request'];checker=person(s,r,'checker');adoption=authorize(s,r,gov,'adoption_request',adoption_request,checker);issue_set=service.create_issue_set('C','P',uid(),{'title':'Issue','purpose':'Read','issue_purpose':'information'},[ref],[])['issue_set'];issued=authorize(s,r,gov,'issue_set',issue_set,checker);transmittal=service.create_transmittal('C','P',uid(),issued['id'],digest(issued),[checker.user],'Review','')['transmittal']
            for kind,value in [('adoption_request',adoption_request),('issue_set',issue_set),('transmittal',transmittal)]:
                # Earlier consumed subjects are immutable; construct their exact original packet from persisted manifest.
                fact=next((v for (k,_),v in s.rows.items() if k==r.FACTS[kind] and v.get('subject_id')==value['id']),None)
                if not fact:fact=authorize(s,r,gov,kind,value,checker)
                native=s.packets[fact['packet_id']];manifest=json.loads(native.manifest_json)['domain'];packet={'schema':'cipher.document.approval.v1','id':native.name,'company':'C','project':'P','action':r.ACTIONS[kind],'subject':{'id':value['id'],'type':r.KINDS[kind],'label':'Exact documentary subject'},'requester':{'id':s.actor.person_id,'display_name':'Author'},'created_at':'2026-10-17T00:00:00Z','expires_at':'2026-10-18T00:00:00Z','manifest_hash':native.manifest_hash,'source_version':digest(value),'policy':{'id':'policy','label':'Synthetic exact review','synthetic':True},'state':'Consumed','decisions':[],'actions':{'can_decide':False,'can_execute':False,'can_withdraw':False,'disabled_reason':'Consumed'},'review_manifest':manifest}
                self.assertNotEqual(packet['manifest_hash'],digest(packet['review_manifest']));validate('DocumentApprovalPacket',packet,CORE);validate('ApprovalPacket',packet,CORE);validate('DocumentApprovalExecutionResponse',{'packet':packet,'effect':{r.FACTS[kind]:fact},'operation':{'id':uid(),'status':'succeeded','replayed':False}},CORE)
                for path,replacement in [('action','proposal.issue.v1'),('subject.type','Cipher Calibration'),('review_manifest.effect.subject_kind','other'),('review_manifest.effect.external_delivery',True)]:
                    wrong=deepcopy(packet);target=wrong;parts=path.split('.')
                    for part in parts[:-1]:target=target[part]
                    target[parts[-1]]=replacement
                    with self.subTest(kind=kind,path=path),self.assertRaises(Exception):validate('ApprovalPacket',wrong,CORE)
    def test_changed_authored_rights_basis_changes_new_manifest_without_rewriting_subject(self):
        with fixture() as (s,r,repo,rights,service,gov):
            _,ref=library(s,service);value=service.create_issue_set('C','P',uid(),{'title':'Issue','purpose':'Exact','issue_purpose':'review'},[ref],[])['issue_set'];before=gov.approval_manifest(kind='issue_set',actor=s.actor,company='C',project='P',subject_id=value['id'],expected_version=digest(value));doc=s.documents[ref['revision_id']]['document_id'];old=rights.current(doc);service.set_rights('C','P',uid(),doc,digest(old),permission(s, **({**{k:old[k] for k in ('ingest_allowed','read_allowed','distribute_allowed')},'rights_basis':'An explicitly different authored rights basis'})));after=gov.approval_manifest(kind='issue_set',actor=s.actor,company='C',project='P',subject_id=value['id'],expected_version=digest(value));self.assertNotEqual(before,after);self.assertEqual(repo.raw('issue_set',value['id']),value)
    def test_native_write_requires_private_exact_plan_even_with_trusted_flag(self):
        from types import SimpleNamespace
        with fixture() as (s,r,repo,rights,service,gov):
            created,_=library(s,service);value=created['library_revision'];doc=SimpleNamespace(name=value['id'],is_new=lambda:True)
            with self.assertRaises(DomainError):repo.require_write(doc,'library_revision',value)
    def test_document_duties_have_explicit_scope_and_are_not_seeded(self):
        tree=ast.parse((ROOT/'governance/context.py').read_text());values={n.targets[0].id:set(ast.literal_eval(n.value.args[0])) for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('PROJECT_ABILITIES','COMPANY_ABILITIES','DOCUMENT_CONTROL_ABILITIES')}
        self.assertTrue(values['DOCUMENT_CONTROL_ABILITIES']<=values['PROJECT_ABILITIES']);self.assertEqual(values['DOCUMENT_CONTROL_ABILITIES']&values['COMPANY_ABILITIES'],{'document.control.read','document.control.write','document.rights.manage'});self.assertIn('COMPANY_ABILITIES - DOCUMENT_CONTROL_ABILITIES',(ROOT/'install.py').read_text());self.assertIn('PROJECT_ABILITIES - ENGINEERING_ABILITIES - DOCUMENT_CONTROL_ABILITIES',(ROOT/'install.py').read_text());metadata=json.loads((ROOT/'cipher_document_control/doctype/cipher_library_revision/cipher_library_revision.json').read_text());self.assertFalse(metadata['is_submittable'])
