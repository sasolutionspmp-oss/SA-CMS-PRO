"""Explicit host adapters for actual ENG-02 services; no native persistence claim."""
from contextlib import contextmanager
from copy import deepcopy
import importlib
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.migrations.validation import parse_manifest
from cipher_aec.tests.test_engineering import fixtures as eng_fixtures,add_source,add_person,module,uid

ABILITIES={'project.read','document.read','engineering.package.read','engineering.package.write','engineering.package.check','native.unit.read'}
@contextmanager
def fixture():
 with eng_fixtures() as (state,oldrules,oldrepo,sources,oldservice,oldgov):
  state.duties[state.actor.person_id]=set(ABILITIES);state.unit_id=uid();state.unit={'id':state.unit_id,'kind':'uom','revision':1,'fields':{'symbol':'m','dimension':'length','precision':6},'target':{'doctype':'UOM','name':'Native metre'}};state.unit_enabled=True
  def qualified(identifier,lock=False,allow_disabled=False,actor=None):
   if identifier!=state.unit_id or not state.unit_enabled and not allow_disabled:raise DomainError('unit_setup_required','unit',409)
   if 'native.unit.read' not in state.duties[(actor or state.actor).person_id]:raise DomainError('not_found','native unit',404)
   return deepcopy(state.unit)
  def unit_manifest(company,project,ids,conversions,lock=False,dataset_id=None):
   records=[{'id':'0b7d3b2c-d9a3-51de-86bf-500047d5a5c2','kind':'company','revision':1,'fields':{'name':company,'currency':'USD','timezone':'UTC'},'target':{'doctype':'Company','name':company}}]+[qualified(i,lock=lock) for i in sorted(ids)]
   return parse_manifest({'schema':'cipher.canonical.v1','dataset_id':dataset_id,'scope':{'company':company,'project':project},'records':records,'unit_conversions':[]})
  def unit_access(manifest,currency,actor):
   if 'native.unit.read' not in state.duties[actor.person_id]:raise DomainError('not_found','unit revoked',404)
  names=['cipher_aec.engineering_packages.'+n for n in ('contracts','repository','service','governance')];old={n:sys.modules.pop(n) for n in names if n in sys.modules}
  unit_stub=module('units',manifest=unit_manifest,qualified=qualified,verify_manifest_access=unit_access)
  estimating_package=importlib.import_module('cipher_aec.estimating')
  with patch.dict(sys.modules,{'cipher_aec.estimating.units':unit_stub,'frappe.model.naming':module('naming',make_autoname=lambda *a:'ENG-WP-00001')}),patch.object(estimating_package,'units',unit_stub,create=True):
   rules=importlib.import_module(names[0]);repo=importlib.import_module(names[1]);service=importlib.import_module(names[2]);gov=importlib.import_module(names[3])
   with patch.object(sources,'verify',state.verify),patch.object(repo,'raw',oldrepo.raw),patch.object(repo,'write',oldrepo.write),patch.object(repo,'checked',lambda kind,identifier,lock=False:next((deepcopy(v) for (k,_),v in state.rows.items() if k=='check' and v['subject_id']==identifier),None)),patch.object(service,'run_command',oldservice.run_command),patch.object(oldservice,'authorize_receipt',service.authorize_receipt):
    yield state,rules,repo,service,gov,sources
  for n in names:
   removed=sys.modules.pop(n,None);parentname,attr=n.rsplit('.',1);parent=sys.modules.get(parentname)
   if parent is not None and getattr(parent,attr,None) is removed:delattr(parent,attr)
  sys.modules.update(old)
  for n,v in old.items():parentname,attr=n.rsplit('.',1);setattr(sys.modules[parentname],attr,v)

def person(state,name):
 result=add_person(state,name);state.duties[result.person_id]=set(ABILITIES);return result

def package(state,service):
 checker=person(state,'checker');definition={'title':'Bearing calculation package','discipline':'Structural','scope':'Manual design basis and exact authored results','responsible_user':state.actor.user,'checker_user':checker.user,'due_date':None,'task_ids':[],'wbs_ids':[]}
 return service.create_package('C','P',uid(),definition),checker

def quantity(state,source,amount='2.500000',key='length'):
 return {'key':key,'label':'Authored design length','quantity':{'amount':amount,'unit_id':state.unit_id,'precision':6},'source':{k:source[k] for k in ('revision_id','source_sha256','page','locator')}}
def basis(state,service,created):
 source=add_source(state,extracted=False);result=service.create_basis('C','P',uid(),created['package']['id'],digest(created['package']),{'title':'Bearing geometry','criteria':'Explicit drawing basis','assumptions':'','design_codes':[{'code':'Declared authored reference','edition':'2026','clause':''}],'change_reason':'Initial basis'},[quantity(state,source)],[],[source],[])
 return result,source

def calculation(state,service,created,source,predecessor=None):
 b=created['basis'];definition={'title':'Manual bearing result','method':'human-authored-results-v1','algorithm_reference':'Authored worksheet section A','tool_name':'Human-authored worksheet','tool_version':'1','model_version':'','design_codes':[],'explanation':'Human entered result; Cipher does not execute a formula.','change_reason':'Initial calculation' if not predecessor else 'Explicit successor'}
 return service.create_calculation('C','P',uid(),b['parent_id'],digest(created['package']),b['id'],digest(b),definition,['length'],[quantity(state,source,'3.750000','result')],[{k:source[k] for k in ('revision_id','source_sha256')}],predecessor)

def check(state,service,gov,kind,value,checker):
 manifest=gov.approval_manifest(kind=kind,actor=state.actor,company='C',project='P',subject_id=value['id'],expected_version=digest(value),lock=True)
 packetid,decisionid=uid(),uid();outer={'domain':manifest};state.packets[packetid]=SimpleNamespace(name=packetid,company='C',project='P',scope_type='Project',action=gov.rules.ACTIONS[kind],subject_type=gov.rules.KINDS[kind],subject_id=value['id'],requester_person=state.actor.person_id,manifest_json=json.dumps(outer),manifest_hash=digest(outer));state.decisions[decisionid]=SimpleNamespace(name=decisionid,packet=packetid,decision='Grant',actor_person=checker.person_id,manifest_hash=digest(outer),reason='Independent exact manual check')
 state.approval_effect=(gov.rules.ACTIONS[kind],value['id'],packetid);result=gov.apply_check(kind=kind,actor=state.actor,company='C',project='P',manifest=manifest,packet_id=packetid,decision_id=decisionid,operation_id=uid());state.approval_effect=None
 state.consumptions[packetid]=SimpleNamespace(packet=packetid,decision=decisionid,company='C',project='P',scope_type='Project',actor_person=state.actor.person_id,result_hash=digest(result));return result['check']

class PackageWorkflowTests(unittest.TestCase):
 def test_manual_basis_calculation_deliverable_and_independent_check(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,checker=package(state,service);authored,source=basis(state,service,created);calculated=calculation(state,service,authored,source);value=calculated['calculation'];self.assertEqual(value['inputs'],authored['basis']['quantities']);self.assertFalse(value['execution']['executed_by_cipher']);self.assertEqual(value['issue_readiness'],'not_authorized_for_issue')
   fact=check(state,service,gov,'calculation',value,checker);self.assertEqual(service.read('check',fact['id'],'C','P',state.actor),fact);self.assertFalse(fact['issue_authorized']);self.assertFalse(fact['sealed'])
   deliverable=service.create_deliverable('C','P',uid(),value['parent_id'],digest(calculated['package']),value['basis_revision'],value['basis_digest'],{'title':'Working drawing package','deliverable_type':'drawing/specification','description':'Retained exact source and manual calculation','checking_notes':'','change_reason':'Initial deliverable'},[{'id':value['id'],'record_digest':digest(value)}],[],[source],[{k:source[k] for k in ('revision_id','source_sha256')}])['deliverable'];self.assertEqual(deliverable['issue_readiness'],'not_authorized_for_issue');self.assertEqual(service.read('deliverable',deliverable['id'],'C','P',state.actor),deliverable)
 def test_independence_alias_and_designated_checker(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,checker=package(state,service);authored,_=basis(state,service,created)
   for actor in (state.actor,person(state,'other-checker'),SimpleNamespace(user='alias',person_id=state.actor.person_id)):
    if actor.user=='alias':state.duties[actor.person_id]=set(ABILITIES)
    with self.assertRaises(DomainError):gov.authorize_subject(kind='basis',actor=actor,company='C',project='P',subject_id=authored['basis']['id'],phase='review')
   self.assertEqual(gov.authorize_subject(kind='basis',actor=checker,company='C',project='P',subject_id=authored['basis']['id'],phase='review'),authored['basis'])
 def test_package_cannot_assign_alias_as_independent_checker(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   alias=SimpleNamespace(user='alias@example.invalid',person_id=state.actor.person_id);state.users[alias.user]=alias
   definition={'title':'Package','discipline':'Civil','scope':'Authored','responsible_user':state.actor.user,'checker_user':alias.user,'due_date':None,'task_ids':[],'wbs_ids':[]}
   with self.assertRaises(DomainError):service.create_package('C','P',uid(),definition)
   self.assertFalse(state.rows)
 def test_exact_unit_precision_and_source_page_are_enforced(self):
  for mutation in ('precision','source'):
   with self.subTest(mutation=mutation),fixture() as (state,rules,repo,service,gov,sources):
    created,_=package(state,service);source=add_source(state);row=quantity(state,source)
    if mutation=='precision':row['quantity']['precision']=2
    else:row['source']['revision_id']=uid()
    with self.assertRaises(DomainError):service.create_basis('C','P',uid(),created['package']['id'],digest(created['package']),{'title':'Basis','criteria':'Authored','assumptions':'','design_codes':[],'change_reason':'Initial'},[row],[],[source],[])
    self.assertFalse(any(k=='basis' for k,_ in state.rows))
 def test_unit_successor_invalidates_new_check_but_original_read_keeps_snapshot(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,checker=package(state,service);authored,_=basis(state,service,created);state.unit['revision']=2
   self.assertEqual(service.read('basis',authored['basis']['id'],'C','P',state.actor),authored['basis'])
   with self.assertRaises(DomainError):gov.authorize_subject(kind='basis',actor=checker,company='C',project='P',subject_id=authored['basis']['id'],phase='review',lock=True)
 def test_unsupported_code_execution_method_is_refused(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   with self.assertRaises(DomainError):rules.calculation_definition({'title':'Eval','method':'python-eval','algorithm_reference':'__import__','tool_name':'shell','tool_version':'1','model_version':'','design_codes':[],'explanation':'execute','change_reason':'bad'})
 def test_native_unit_permission_and_source_revocation_hides_originals(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,_=package(state,service);authored,source=basis(state,service,created);state.duties[state.actor.person_id].remove('native.unit.read')
   with self.assertRaises(DomainError):service.read('basis',authored['basis']['id'],'C','P',state.actor)
   state.duties[state.actor.person_id].add('native.unit.read');state.denied.add(source['revision_id'])
   with self.assertRaises(DomainError):service.read('basis',authored['basis']['id'],'C','P',state.actor)
 def test_late_receipt_failure_rolls_back_package_revision_and_history(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   state.failed_receipt=True
   with self.assertRaises(RuntimeError):package(state,service)
   self.assertFalse(state.rows);self.assertFalse(state.events)
 def test_current_head_fence_and_original_replay_after_assignment_successor(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,_=package(state,service);authored,source=basis(state,service,created);old=deepcopy(authored['basis']);definition={**created['revision']['definition'],'scope':'Revised assignment'}
   revised=service.revise_package('C','P',uid(),created['package']['id'],digest(authored['package']),definition)
   self.assertEqual(service.read('basis',old['id'],'C','P',state.actor),old)
   with self.assertRaises(DomainError):gov.approval_manifest(kind='basis',actor=state.actor,company='C',project='P',subject_id=old['id'],expected_version=digest(old))
   service.authorize_receipt(state.actor,'C','P',{'package':authored['package'],'basis':old})
 def test_calculation_successor_retains_original_and_rejects_stale_family(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,_=package(state,service);authored,source=basis(state,service,created);first=calculation(state,service,authored,source);nextinput={**authored,'package':first['package']};second=calculation(state,service,nextinput,source,first['calculation']['id'])
   self.assertEqual(second['calculation']['predecessor'],first['calculation']['id']);self.assertEqual(repo.raw('calculation',first['calculation']['id']),first['calculation'])
   with self.assertRaises(DomainError):calculation(state,service,{**authored,'package':second['package']},source,first['calculation']['id'])

if __name__=='__main__':unittest.main()

class PackageContractTests(unittest.TestCase):
 def validator(self,name,value):
  from pathlib import Path
  from jsonschema import Draft202012Validator,FormatChecker
  schema=json.loads((Path(__file__).parents[1]/'engineering_packages/schemas/api-v1.schema.json').read_text());Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':schema['$defs']},format_checker=FormatChecker()).validate(value)
 def test_closed_schemas_accept_actual_service_results(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,checker=package(state,service);self.validator('EpCreatePackageResponse',created);authored,source=basis(state,service,created);self.validator('EpCreateBasisResponse',authored);calculated=calculation(state,service,authored,source);self.validator('EpCreateCalculationResponse',calculated);fact=check(state,service,gov,'calculation',calculated['calculation'],checker);self.validator('EpCheck',fact)
   self.validator('EpGetResponse',{'record':fact,'record_digest':digest(fact),'review':None})
 def test_persisted_check_requires_exact_consumption_and_retains_original_basis(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,checker=package(state,service);authored,_=basis(state,service,created);fact=check(state,service,gov,'basis',authored['basis'],checker)
   state.consumptions[fact['packet_id']].result_hash='0'*64
   with self.assertRaises(DomainError):service.read('check',fact['id'],'C','P',state.actor)
 def test_new_check_rejects_closed_project_without_hiding_original(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,checker=package(state,service);authored,_=basis(state,service,created);state.project_status='Completed'
   with self.assertRaises(DomainError):gov.authorize_subject(kind='basis',actor=checker,company='C',project='P',subject_id=authored['basis']['id'],phase='review')
   self.assertEqual(service.read('basis',authored['basis']['id'],'C','P',state.actor),authored['basis'])
 def test_basis_source_digest_and_package_lineage_fail_closed(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,_=package(state,service);authored,source=basis(state,service,created);calculated=calculation(state,service,authored,source);value=calculated['calculation'];state.rows['calculation',value['id']]['basis_digest']='0'*64
   with self.assertRaises(DomainError):service.read('calculation',value['id'],'C','P',state.actor)
 def test_no_grant_can_create_a_check_through_an_arbitrary_trusted_writer(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   doc=SimpleNamespace(name=uid(),is_new=lambda:True);value={'id':doc.name}
   with self.assertRaises(DomainError):repo.require_write(doc,'check',value)
 def test_distinct_command_uuid_and_payload_conflicts_preserve_original(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   checker=person(state,'checker');operation=uid();definition={'title':'Package','discipline':'Civil','scope':'Initial','responsible_user':state.actor.user,'checker_user':checker.user,'due_date':None,'task_ids':[],'wbs_ids':[]}
   first=service.create_package('C','P',operation,definition);second=service.create_package('C','P',operation,definition);self.assertTrue(second['operation']['replayed']);self.assertEqual(first['revision'],second['revision'])
   with self.assertRaises(DomainError):service.create_package('C','P',operation,{**definition,'scope':'Changed'})
 def test_unit_manifest_is_pinned_to_record_and_exact_project(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,_=package(state,service);authored,_=basis(state,service,created);value=authored['basis'];value['unit_manifest']['dataset_id']=uid()
   with self.assertRaises(DomainError):service.verify_quantities(value)
 def test_review_rejected_state_is_not_a_checked_or_issued_fact(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,_=package(state,service);authored,_=basis(state,service,created);packet_id=uid();api=module('approvals',read_packet=lambda *a:{'id':packet_id,'state':'Rejected'})
   with patch.object(service.frappe.db,'sql',return_value=[(packet_id,)]),patch.dict(sys.modules,{'cipher_aec.governance.approvals':api}):
    review=service.review_state('basis',authored['basis'],state.actor)
   self.assertEqual(review,{'state':'returned','packet_id':packet_id,'check_id':None,'issue_authorized':False})

class PackageCheckLineageTests(unittest.TestCase):
 def test_self_consistent_check_receipt_still_requires_original_assignment_join(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,checker=package(state,service);authored,_=basis(state,service,created);fact=check(state,service,gov,'basis',authored['basis'],checker)
   bad={**fact,'package_digest':'0'*64};state.rows['check',fact['id']]=bad;state.consumptions[fact['packet_id']].result_hash=digest({'check':bad})
   with self.assertRaises(DomainError):service.read('check',fact['id'],'C','P',state.actor)

class PackageChoiceTests(unittest.TestCase):
 def test_selectors_use_package_roles_without_rfi_or_pricing_duties(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,checker=package(state,service);self.assertNotIn('engineering.read',state.duties[state.actor.person_id]);self.assertNotIn('estimate.read',state.duties[state.actor.person_id]);queries=[]
   def sql(query,args=(),**kwargs):
    queries.append((query,args))
    if 'tabUOM' in query:return [SimpleNamespace(cipher_unit_id=state.unit_id,name='Native metre')]
    return [SimpleNamespace(user=checker.user,person=checker.person_id,display_name='Designated checker')]
   with patch.object(service.frappe.db,'sql',sql):
    people=service.list_people('C','P','checker');catalog=service.list_units('C','P')
   self.assertEqual(people['items'][0]['person'],checker.person_id);self.assertEqual(catalog['items'][0]['id'],state.unit_id);self.assertIsNone(people['total']);self.assertEqual(queries[0][1][:3],['C','P',rules.CHECK]);self.assertTrue(all('LIMIT 25' in q for q,_ in queries))
 def test_selector_rechecks_person_role_and_native_unit_access(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   denied=person(state,'denied');state.duties[denied.person_id]={rules.READ,'project.read'}
   with patch.object(service.frappe.db,'sql',return_value=[SimpleNamespace(user=denied.user,person=denied.person_id,display_name='Unavailable checker')]):self.assertEqual(service.list_people('C','P','checker')['items'],[])
   state.duties[state.actor.person_id].remove('native.unit.read')
   with patch.object(service.frappe.db,'sql',return_value=[SimpleNamespace(cipher_unit_id=state.unit_id,name='Native metre')]):self.assertEqual(service.list_units('C','P')['items'],[])

class PackageBlankCheckTests(unittest.TestCase):
 def test_nullable_native_blank_decision_comment_roundtrips_as_authored_blank(self):
  with fixture() as (state,rules,repo,service,gov,sources):
   created,checker=package(state,service);authored,_=basis(state,service,created);fact=check(state,service,gov,'basis',authored['basis'],checker)
   state.decisions[fact['decision_id']].reason=None
   fact={**fact,'comments':''};state.rows['check',fact['id']]=fact;state.consumptions[fact['packet_id']].result_hash=digest({'check':fact})
   self.assertEqual(service.read('check',fact['id'],'C','P',state.actor)['comments'],'')
