"""Company scope metadata is explicit; legacy Project metadata stays compatible."""
import ast
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).parents[1]
# Captured from immutable618 a541854c…; no private snapshot needed by CI.
import hashlib
LEGACY_METADATA_SHA={'cipher_ricky_run': '8978514dbf380d1e4af17e79ce562eef7211a7a35c1c81b663f0e3e7f6ca92b8', 'cipher_ricky_step': 'aedd2b3df4267f9033463f9de0243dc6685dee4b3955d98ce07960575da813df', 'cipher_tool_invocation': '70dbb6a77f921968dd15dee9c5f91b6952f53bcc2f3be997d049833af0d54fc7', 'cipher_proposed_change': '035e13460d6cf3752bf1cb6c7e915d395cae8eec43e02fd99716262165c0c5c3', 'cipher_delegation': 'e53325da6d8c2baf683e3e8aed57d5e884b01c80adc7d9c24dc4378020509ea3', 'cipher_run_artifact': '55c7d25e4851fa950eec7f9a45313de5bee0873d59c4d4a9fffe63685d809116'}
NAMES=('cipher_ricky_run','cipher_ricky_step','cipher_tool_invocation','cipher_proposed_change','cipher_delegation','cipher_run_artifact')


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def ast_value(node):
    if isinstance(node,ast.AST):return {'_node':type(node).__name__,**{name:ast_value(getattr(node,name)) for name in node._fields}}
    if isinstance(node,list):return [ast_value(x) for x in node]
    return node


def abilities(path):
    values={}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('PROJECT_ABILITIES','COMPANY_ABILITIES'):
            values[node.targets[0].id]=set(ast.literal_eval(node.value.args[0]))
    return values


class CompanyRickyMetadataTests(unittest.TestCase):
    def test_company_catalog_exact_and_project_only_engineering_addition(self):
        current=abilities(ROOT/'governance/context.py');old={'PROJECT_ABILITIES': {'ricky.run', 'task.create', 'wbs.read', 'document.write', 'approval.request', 'approval.execute', 'document.read', 'approval.decide', 'estimate.write', 'budget.read', 'project.read', 'estimate.read', 'project.write', 'contract.write', 'contract.read'}, 'COMPANY_ABILITIES': {'project.cost.write', 'project.team.delegate', 'document.write', 'approval.request', 'approval.execute', 'commercial.read', 'document.read', 'estimate.write', 'approval.decide', 'commercial.distribute', 'company.read', 'estimate.read', 'commercial.write', 'project.cost.read', 'commercial.award'}}
        self.assertIn('ricky.run',current['COMPANY_ABILITIES'])
        self.assertEqual(current['PROJECT_ABILITIES'],old['PROJECT_ABILITIES']|{'document.control.read','document.control.write','document.rights.manage','document.issue','document.adopt','document.distribute','document.control.review','engineering.read','engineering.write','engineering.distribute','engineering.package.read','engineering.package.write','engineering.package.check'})
        self.assertFalse({'document.control.read','document.control.write','document.rights.manage','document.issue','document.adopt','document.distribute','document.control.review','engineering.read','engineering.write','engineering.distribute','engineering.package.read','engineering.package.write','engineering.package.check'} & current['COMPANY_ABILITIES'])
        self.assertEqual(current['COMPANY_ABILITIES'],old['COMPANY_ABILITIES']|{'ricky.run'})
        metadata=json.loads((ROOT/'cipher_governance/doctype/cipher_project_duty/cipher_project_duty.json').read_text())
        options=set(next(f for f in metadata['fields'] if f['fieldname']=='ability')['options'].splitlines())
        self.assertEqual(options,current['PROJECT_ABILITIES']|current['COMPANY_ABILITIES'])
    def test_all_six_tables_require_explicit_scope_and_project_condition(self):
        for name in NAMES:
            with self.subTest(doctype=name):
                relative=Path('cipher_ricky/doctype')/name/(name+'.json')
                new=json.loads((ROOT/relative).read_text())
                fields={f['fieldname']:f for f in new['fields']}
                self.assertEqual(fields['scope_type'],{'fieldname':'scope_type','fieldtype':'Select','label':'Scope Type','options':'Project\nCompany','default':'Project','reqd':1,'read_only':1,'search_index':1})
                self.assertEqual(fields['project']['reqd'],0)
                self.assertEqual(fields['project']['mandatory_depends_on'],"eval:doc.scope_type == 'Project'")
                # This metadata change must not modify old roles/indices/statuses
                # or smuggle Company defaults into the durable JSON contract.
                restored=json.loads(json.dumps(new));restored['fields']=[f for f in restored['fields'] if f['fieldname']!='scope_type']
                project=next(f for f in restored['fields'] if f['fieldname']=='project');project['reqd']=1;project.pop('mandatory_depends_on')
                restored['field_order'].remove('scope_type')
                self.assertEqual(canonical_sha(restored),LEGACY_METADATA_SHA[name])


# Execute the actual literal dispatcher bodies with explicit local doubles.
# No unbound frappe.db proxy, site initialization or model/service construction.
from contextlib import ExitStack
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

class BoundaryError(Exception):
    def __init__(self,code,message='',status=403):self.code=code;self.status=status;super().__init__(message)


def selected_function(relative,name,namespace):
    tree=ast.parse((ROOT/relative).read_text())
    selected=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    code=compile(ast.Module(body=[selected],type_ignores=[]),str(ROOT/relative),'exec')
    exec(code,namespace)
    return namespace[name]


class CompanyRickyDispatchTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.company_calls=[];self.receipt_calls=[];self.history_calls=[]
        service=ModuleType('cipher_aec.ricky.company_service')
        service.authorize_receipt=lambda actor,company,result,**kw:self.receipt_calls.append((actor,company,result,kw))
        service.authorize_history=lambda actor,company,run_id,**kw:self.history_calls.append((actor,company,run_id,kw))
        self.stack.enter_context(patch.dict('sys.modules',{'cipher_aec.ricky.company_service':service}))
        self.service=service
        self.actor=SimpleNamespace(user='original@example.invalid',person_id='native-person')
        self.namespace={'DomainError':BoundaryError,
            'require_company':lambda company,**kw:self.company_calls.append((company,kw)) or True,
            'require_project':lambda *args,**kw:True,
            'COMPANY_RICKY_COMMANDS':frozenset({'ricky.company.read.start.v1','ricky.company.read.cancel.v1'})}
        self.authorize=selected_function('governance/commands.py','authorize_receipt',self.namespace)
    def test_both_exact_receipts_require_company_run_and_original_result(self):
        for command in ('ricky.company.read.start.v1','ricky.company.read.cancel.v1'):
            self.company_calls.clear();self.receipt_calls.clear()
            result={'id':'original-run-id'}
            self.authorize(self.actor,command,'Company',None,result,scope_type='Company')
            self.assertEqual(self.receipt_calls,[(self.actor,'Company',result,{'command':command,'lock':True})])
            self.assertIn(('Company',{'ability':'ricky.run','actor':self.actor,'lock':True}),self.company_calls)
    def test_cancel_and_start_cannot_select_policy_from_result_shape(self):
        result={'id':'run','status':'cancelled'}
        for command in ('ricky.company.read.start.v1','ricky.company.read.cancel.v1'):
            self.authorize(self.actor,command,'Company',None,result,scope_type='Company')
        self.assertEqual([call[3]['command'] for call in self.receipt_calls],['ricky.company.read.start.v1','ricky.company.read.cancel.v1'])
    def test_unknown_company_ricky_command_fails_closed(self):
        for command in ('ricky.start.v1','ricky.company.read.commit.v1','ricky.arbitrary'):
            with self.subTest(command=command),self.assertRaises(BoundaryError):
                self.authorize(self.actor,command,'Company',None,{'id':'hidden'},scope_type='Company')
        self.assertEqual(self.receipt_calls,[])
    def test_new_command_never_falls_through_to_generic_company_read(self):
        provenance=ModuleType('cipher_aec.documents.provenance')
        provenance.logical_operation=lambda *a,**k:None
        provenance.logical_operation_stats=lambda:None
        self.stack.enter_context(patch.dict('sys.modules',{'cipher_aec.documents.provenance':provenance}))
        queries=[]
        def guard(company,**kwargs):
            self.company_calls.append((company,kwargs))
            if kwargs.get('ability')=='ricky.run':raise BoundaryError('capability_denied','',403)
            return True
        namespace={'DomainError':BoundaryError,'require_company':guard,
            'current_actor':lambda **kwargs:self.actor,'assert_synthetic_site':lambda:None,
            'session_authority_reference':lambda actor:'a'*64,'require_session_authority':lambda *a,**k:None,
            'parse_operation_id':lambda value:value,'text':lambda value,label:value,
            'frappe':SimpleNamespace(db=SimpleNamespace(sql=lambda *a,**k:queries.append(a) or [])),
            'COMPANY_RICKY_COMMANDS':self.namespace['COMPANY_RICKY_COMMANDS']}
        command=selected_function('governance/commands.py','_run_scoped_command',namespace)
        for name,expected in [('ricky.arbitrary','unsupported_company_ricky_command'),
                ('ricky.company.read.start.v1','capability_denied'),('ricky.company.read.cancel.v1','capability_denied')]:
            queries.clear()
            with self.subTest(command=name),self.assertRaises(BoundaryError) as error:
                command(company='Company',project=None,scope_type='Company',operation_id='original-uuid',
                    command=name,payload={},ability='company.read',effect=lambda *a:self.fail('Unauthorized effect'),
                    guard=None,participant_people=())
            self.assertEqual(error.exception.code,expected)
            self.assertFalse(any('Command Receipt' in row[0] for row in queries))
    def test_missing_company_run_permission_hides_receipt_before_handler(self):
        def require_company(company,**kwargs):
            if kwargs.get('ability')=='ricky.run':raise BoundaryError('capability_denied','',403)
            return True
        self.namespace['require_company']=require_company
        with self.assertRaises(BoundaryError):
            self.authorize(self.actor,'ricky.company.read.start.v1','Company',None,{'id':'private-run'},scope_type='Company')
        self.assertEqual(self.receipt_calls,[])
    def test_original_source_denial_and_integrity_errors_propagate(self):
        def deny(*args,**kwargs):raise BoundaryError('source_revoked','',403)
        self.service.authorize_receipt=deny
        with self.assertRaises(BoundaryError) as error:self.authorize(self.actor,'ricky.company.read.start.v1','Company',None,{'id':'run'},scope_type='Company')
        self.assertEqual(error.exception.code,'source_revoked')
    def test_history_is_literal_company_scope_before_reader(self):
        scope=SimpleNamespace(DoesNotExistError=type('Missing',(Exception,),{}))
        namespace={'frappe':scope,'json':json,'DomainError':BoundaryError,'EST_SUBJECTS':{},'TAKEOFF_SUBJECTS':{},'FIN_SUBJECTS':{},'COM_SUBJECTS':{},
                   'require_company':lambda *a,**k:True,'require_project':lambda *a,**k:True}
        read=selected_function('governance/history_access.py','readable',namespace)
        event=SimpleNamespace(subject_type='Cipher Ricky Run',subject_id='original-run-id')
        self.assertFalse(read(event,self.actor,'Company','real-project'))
        self.assertEqual(self.history_calls,[])
        self.assertTrue(read(event,self.actor,'Company',None))
        self.assertEqual(self.history_calls,[(self.actor,'Company','original-run-id',{'lock':False})])
        def deny(*a,**k):raise BoundaryError('private_source','',403)
        self.service.authorize_history=deny
        self.assertFalse(read(event,self.actor,'Company',None))
        def corrupt(*a,**k):raise BoundaryError('source_integrity','',409)
        self.service.authorize_history=corrupt
        with self.assertRaises(BoundaryError):read(event,self.actor,'Company',None)


class ProjectCompatibilityTests(unittest.TestCase):
    def test_only_company_branches_change_in_shared_command_code(self):
        expected={'run_command': '453326d4f845be1777664dfa7cb44041ec435f558ea445ed68c0ab1bbdcd5e9c', '_run_scoped_command': '88933249fedbb1664ff57b9e760aedd32eb3404186416a0f0a17fd06b51dbf30', 'project_receipt_branches': '3e0d2dcd94543631fca302fa1e8f698e8e0a4d68d4aaa296012087a7e9c27615'}
        new=ast.parse((ROOT/'governance/commands.py').read_text())
        def get(tree,name):return next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        self.assertEqual(canonical_sha(ast_value(get(new,'run_command'))),expected['run_command'])
        after=get(new,'_run_scoped_command')
        after.body=[n for n in after.body if not (isinstance(n,ast.If) and 'COMPANY_RICKY_COMMANDS' in ast.unparse(n.test)+' '.join(ast.unparse(x) for x in n.body) and 'command.startswith("ricky.")' in ast.unparse(n.test).replace("'",'"'))]
        # Strip only the two approved literal Company START branches; their else is
        # the original effect, and no legacy execution path uses the bridge.
        case=self
        expected_start=ast.parse("scope_type == 'Company' and command in {'ricky.company.read.start.v1', 'ricky.company.proposal.start.v1'}",mode='eval').body
        commands=next(node for node in new.body if isinstance(node,ast.Assign)
            and any(isinstance(target,ast.Name) and target.id=='COMPANY_RICKY_COMMANDS' for target in node.targets))
        self.assertEqual(ast.literal_eval(commands.value.args[0]),{'ricky.company.read.start.v1','ricky.company.read.cancel.v1',
            'ricky.company.proposal.start.v1','ricky.company.proposal.cancel.v1',
            'ricky.company.proposal.save-scope.v1','ricky.company.proposal.save-estimate.v1'})
        # Normalize only the reviewed optional Company application context.
        case.assertEqual(after.args.kwonlyargs[-1].arg,'draft_save')
        case.assertIsNone(ast.literal_eval(after.args.kw_defaults[-1]))
        after.args.kwonlyargs.pop();after.args.kw_defaults.pop()
        draft_condition=ast.parse("scope_type == 'Company' and draft_save is not None",mode='eval').body
        observed=[]
        class DraftCompanyShape(ast.NodeTransformer):
            def visit_If(self,node):
                if ast.dump(node.test)==ast.dump(draft_condition):
                    observed.append(ast.unparse(node))
                    return []
                return self.generic_visit(node)
            def visit_With(self,node):
                if len(node.items)==1 and isinstance(node.items[0].context_expr,ast.Name) and node.items[0].context_expr.id=='draft_save_boundary':
                    result=[]
                    for child in node.body:
                        value=self.visit(child)
                        result.extend(value if isinstance(value,list) else [value] if value is not None else [])
                    return result
                return self.generic_visit(node)
        after=DraftCompanyShape().visit(after)
        case.assertEqual(len(observed),5)
        class LegacyProjectShape(ast.NodeTransformer):
            def visit_If(self,node):
                if 'ricky.company.read.start.v1' in ast.unparse(node.test):
                    case.assertEqual(ast.dump(node.test),ast.dump(expected_start))
                    return node.orelse
                return self.generic_visit(node)
        after=LegacyProjectShape().visit(after)
        # This later ENG-01 epoch adds only a separate Project pre-replay read
        # guard. Validate its literal body, then retain the original hash below.
        engineering_guard=ast.parse("if scope_type == 'Project' and command.startswith('engineering.'):\n    require_project(company, project, ability='engineering.package.read' if command.startswith('engineering.package.') else 'engineering.read', actor=actor, lock=True)").body[0]
        additions=[n for n in after.body if isinstance(n,ast.If) and ast.dump(n.test)==ast.dump(engineering_guard.test)]
        self.assertEqual(len(additions),1);self.assertEqual(ast.dump(additions[0]),ast.dump(engineering_guard))
        after.body=[n for n in after.body if n is not additions[0]]
        self.assertEqual(canonical_sha(ast_value(after)),expected['_run_scoped_command'])
        # Original Project receipt branches follow the Company branch's return.
        after=get(new,'authorize_receipt')
        engineering_receipt=ast.parse("if command.startswith('engineering.'):\n    from cipher_aec.engineering.service import authorize_receipt as authorize_engineering\n    authorize_engineering(actor, company, project, result, lock=True)").body[0]
        package_receipt=ast.parse("if command.startswith('engineering.package.'):\n    from cipher_aec.engineering_packages.service import authorize_receipt as authorize_package\n    authorize_package(actor, company, project, result, lock=True)").body[0]
        documentary_receipt=ast.parse("if command.startswith('document.control.'):\n    from cipher_aec.document_control.service import authorize_receipt as authorize_documentary\n    authorize_documentary(actor, company, project, result, lock=True)").body[0]
        additions=[]
        class OriginalProjectReceipts(ast.NodeTransformer):
            def visit_If(self,node):
                for literal in (engineering_receipt,package_receipt,documentary_receipt):
                    if ast.dump(node.test)==ast.dump(literal.test):
                        case.assertEqual([ast.dump(n) for n in node.body],[ast.dump(n) for n in literal.body]);additions.append(node)
                        restored=[]
                        for child in node.orelse:
                            value=self.visit(child);restored.extend(value if isinstance(value,list) else [value])
                        return restored
                return self.generic_visit(node)
        after=OriginalProjectReceipts().visit(after);self.assertEqual(len(additions),3)
        self.assertEqual(canonical_sha(ast_value(ast.Module(body=after.body[2:],type_ignores=[]))),expected['project_receipt_branches'])




class CompanyRickyActualCallbackTests(unittest.TestCase):
    """Shared dispatch calls real callbacks; only storage/authority are fixtures."""
    def setUp(self):
        from datetime import datetime, timezone
        from cipher_aec.api.errors import DomainError
        from cipher_aec.ricky import company_service
        from cipher_aec.ricky.company_contracts import DeterministicReadRequest
        from cipher_aec.ricky.contracts import canonical
        from cipher_aec.tests.test_estimating_core import identity
        from cipher_aec.tests.test_ricky_company_service import CompanyFixtureBoundary, CompanyFixtureStore
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.boundary=CompanyFixtureBoundary()
        self.store=CompanyFixtureStore(self.boundary.events)
        self.service=company_service.CompanyReadService(self.store,self.boundary,
            clock=lambda:datetime(2026,10,16,tzinfo=timezone.utc))
        self.stack.enter_context(patch.object(company_service,'build_service',return_value=self.service))
        self.company='Explicit EST fixture';self.actor=self.boundary.actor;self.error=DomainError
        request=DeterministicReadRequest(identity('pursuit'),'aec.pursuit.lookup',canonical({}))
        self.start_result=self.service.start_read(self.company,request.binding(),identity('company-operation'))
        self.run=self.store.get('run',self.start_result['id'])
        self.boundary.receipts[self.run['start_receipt']]=self.run['id']
        namespace={'DomainError':DomainError,'require_company':lambda *a,**k:True,
            'require_project':lambda *a,**k:True,
            'COMPANY_RICKY_COMMANDS':frozenset({company_service.START_COMMAND,company_service.CANCEL_COMMAND})}
        self.authorize=selected_function('governance/commands.py','authorize_receipt',namespace)
        self.history=selected_function('governance/history_access.py','readable',{
            'frappe':SimpleNamespace(DoesNotExistError=type('Missing',(Exception,),{})),
            'json':json,'DomainError':DomainError,'EST_SUBJECTS':{},'TAKEOFF_SUBJECTS':{},'FIN_SUBJECTS':{},'COM_SUBJECTS':{}})
        self.event=SimpleNamespace(subject_type='Cipher Ricky Run',subject_id=self.run['id'])
    def receipt(self,result=None,command='ricky.company.read.start.v1',actor=None):
        return self.authorize(actor or self.actor,command,self.company,None,
            self.start_result if result is None else result,scope_type='Company')
    def completed(self):
        self.service.process(self.run['id'])
        self.assertEqual(self.store.get('run',self.run['id'])['status'],'succeeded')
    def test_completed_start_replay_and_history_use_original_sources_with_fresh_session(self):
        self.completed();self.boundary.session=False
        self.boundary.fixture.pursuit_value['title']='Later mutable title'
        self.receipt()
        self.assertTrue(self.history(self.event,self.actor,self.company,None))
        self.assertEqual(self.store.get('run',self.run['id'])['original_session_reference'],'a'*64)
        self.boundary.fixture.native_allowed=False
        with self.assertRaises(self.error):self.receipt()
        self.assertFalse(self.history(self.event,self.actor,self.company,None))
    def test_source_revoked_stop_receipt_stays_narrow_while_full_reads_deny(self):
        self.boundary.fixture.native_allowed=False;self.boundary.session=False
        stopped=self.service.cancel(self.company,self.run['id'])
        self.assertEqual(set(stopped),{'id','company','scope_type','project','request_kind','status','cancel_requested'})
        self.receipt(stopped,'ricky.company.read.cancel.v1')
        with self.assertRaises(self.error):self.receipt(stopped,'ricky.company.read.start.v1')
        self.assertFalse(self.history(self.event,self.actor,self.company,None))
        with self.assertRaises(self.error):self.receipt({**stopped,'result':{'private':True}},'ricky.company.read.cancel.v1')
    def test_original_session_expired_active_history_is_private_but_owner_can_stop(self):
        self.boundary.session=False
        self.assertFalse(self.history(self.event,self.actor,self.company,None))
        with self.assertRaises(self.error) as error:self.receipt()
        self.assertEqual(error.exception.status,403)
        stopped=self.service.cancel(self.company,self.run['id'])
        self.receipt(stopped,'ricky.company.read.cancel.v1')
    def test_generic_operation_reader_still_uses_original_run_source_authorizer(self):
        from contextlib import nullcontext
        from cipher_aec.api.contracts import digest
        self.completed();self.boundary.session=False
        provenance=ModuleType('cipher_aec.documents.provenance')
        provenance.logical_operation=lambda *a,**k:nullcontext()
        self.stack.enter_context(patch.dict('sys.modules',{'cipher_aec.documents.provenance':provenance}))
        row=SimpleNamespace(company=self.company,project=None,scope_type='Company',
            command='ricky.company.read.start.v1',result_json=json.dumps(self.start_result),result_hash=digest(self.start_result))
        function=selected_function('governance/commands.py','read_company_operation',{
            'current_actor':lambda:self.actor,'require_company':lambda *a,**k:True,
            'parse_operation_id':lambda value:value,'digest':digest,'json':json,'DomainError':self.error,
            'frappe':SimpleNamespace(db=SimpleNamespace(get_value=lambda *a,**k:row)),
            'authorize_receipt':self.authorize})
        result=function(self.company,'original-operation')
        self.assertEqual(result['id'],self.run['id']);self.assertTrue(result['operation']['replayed'])
        self.boundary.fixture.native_allowed=False
        with self.assertRaises(self.error):function(self.company,'original-operation')
    def test_actual_service_outputs_match_registered_closed_response_contracts(self):
        from jsonschema import Draft202012Validator, FormatChecker
        from cipher_aec.tests.test_estimating_core import identity
        source=json.loads((ROOT/'ricky/schemas/company-api-v1.schema.json').read_text())
        def validate(name,value):
            Draft202012Validator({'$defs':source['$defs'],'$ref':'#/$defs/'+name},
                format_checker=FormatChecker()).validate(value)
        operation={'id':identity('company-operation'),'status':'succeeded','replayed':False}
        validate('CompanyRickyStartReadResponse',{**self.start_result,'operation':operation})
        self.completed()
        validate('CompanyRickyRunResponse',self.service.get_run(self.company,self.run['id']))
        validate('CompanyRickyRunEventsResponse',{'items':self.service.events(self.company,self.run['id'])})
        validate('CompanyRickyStopResponse',{**self.service.cancel(self.company,self.run['id']),'operation':operation})
    def test_same_person_other_user_is_not_original_receipt_owner(self):
        alias=SimpleNamespace(user='alias@example.invalid',person_id=self.actor.person_id)
        with self.assertRaises(self.error):self.receipt(actor=alias)
        self.assertFalse(self.history(self.event,alias,self.company,None))
    def test_corrupt_original_result_aborts_history_instead_of_omitting_it(self):
        self.completed()
        # Fixture direct corruption represents a persisted integrity violation.
        self.store.rows['run',self.run['id']]['result_digest']='0'*64
        with self.assertRaises(self.error) as error:self.receipt()
        self.assertEqual(error.exception.status,409)
        with self.assertRaises(self.error):self.history(self.event,self.actor,self.company,None)




class CompanyRickyRegistrationTests(unittest.TestCase):
    def test_four_fixed_routes_preserve_every_existing_openapi_operation(self):
        from cipher_aec.api.catalog import ROUTES
        from cipher_aec.api.openapi import generate
        generated=generate();prefix='/api/method/cipher_aec.ricky.company_api.'
        names={'start_read':'post','get_run':'get','run_events':'get','cancel_run':'post'}
        self.assertEqual({key for key in generated['paths'] if key.startswith(prefix)},
            {prefix+name for name in names})
        for name,method in names.items():
            route=ROUTES['cipher_aec.ricky.company_api.'+name]
            self.assertEqual(route.method.lower(),method)
            self.assertEqual(route.command,method=='post')
        proposals={
            '/api/method/cipher_aec.ricky.company_proposal_api.start_proposal',
            '/api/method/cipher_aec.ricky.company_proposal_api.get_run',
            '/api/method/cipher_aec.ricky.company_proposal_api.run_events',
            '/api/method/cipher_aec.ricky.company_proposal_api.get_proposal',
            '/api/method/cipher_aec.ricky.company_proposal_api.cancel_run'}
        self.assertEqual({key for key in generated['paths'] if key.startswith('/api/method/cipher_aec.ricky.company_proposal_api.')},proposals)
        draft_saves={'/api/method/cipher_aec.ricky.company_draft_save_api.draft_save_subject',
            '/api/method/cipher_aec.ricky.company_draft_save_api.save_draft'}
        self.assertEqual({key for key in generated['paths'] if key.startswith('/api/method/cipher_aec.ricky.company_draft_save_api.')},draft_saves)
        engineering_prefix='/api/method/cipher_aec.engineering.api.'
        engineering={'create_rfi','revise_rfi','create_response','create_submittal','revise_submission','create_disposition','create_transmittal','close_rfi','get_record','list_records','list_people'}
        self.assertEqual({key for key in generated['paths'] if key.startswith(engineering_prefix)},{engineering_prefix+name for name in engineering})
        package_prefix='/api/method/cipher_aec.engineering_packages.api.'
        package_routes={'create_package','revise_package','create_basis','create_calculation','create_deliverable','get_record','list_records','list_people','list_units'}
        self.assertEqual({key for key in generated['paths'] if key.startswith(package_prefix)},{package_prefix+name for name in package_routes})
        documentary_prefix='/api/method/cipher_aec.document_control.api.'
        documentary_routes={'set_rights','create_library','revise_library','create_adoption','create_issue_set','create_transmittal','record_evidence','get_record','list_records','list_people'}
        self.assertEqual({key for key in generated['paths'] if key.startswith(documentary_prefix)},{documentary_prefix+name for name in documentary_routes})
        old_paths=json.loads(json.dumps({key:value for key,value in generated['paths'].items() if not key.startswith(prefix) and key not in proposals|draft_saves and not key.startswith(engineering_prefix) and not key.startswith(package_prefix) and not key.startswith(documentary_prefix)}))
        actions=old_paths['/api/method/cipher_aec.api.approvals.request_action']['post']['requestBody']['content']['application/json']['schema']['properties']['action']['enum']
        engineering_actions={'document.issue.v1','document.library.adopt.v1','document.transmit.v1','engineering.rfi.authorize.v1','engineering.submittal.authorize.v1','engineering.distribute.v1','engineering.basis.check.v1','engineering.calculation.check.v1','engineering.deliverable.check.v1'}
        self.assertTrue(engineering_actions<=set(actions));actions[:]=[a for a in actions if a not in engineering_actions]
        self.assertEqual(canonical_sha(old_paths),'8c755c2d712b51177683a8bed770428405d9342db1f879cedd5f7aace895a04c')
        self.assertEqual(json.loads((ROOT/'api/openapi.json').read_text()),generated)
    def test_native_projection_closes_company_rows_and_counts_without_changing_project(self):
        import sqlite3
        from cipher_aec import hooks
        from cipher_aec.ricky import permissions
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        for doctype,function in [('Cipher Ricky Run','run_query'),('Cipher Ricky Step','step_query'),
                ('Cipher Tool Invocation','invocation_query'),('Cipher Delegation','delegation_query'),
                ('Cipher Run Artifact','artifact_query'),('Cipher Proposed Change','proposal_query')]:
            with self.subTest(doctype=doctype):
                db.execute('CREATE TABLE `tab'+doctype+'` (name TEXT,scope_type TEXT)')
                db.executemany('INSERT INTO `tab'+doctype+'` VALUES (?,?)',
                    [('legacy',None),('legacy-empty',''),('project','Project'),('private-company','Company'),('malformed','Unknown')])
                predicate=getattr(permissions,function)(user='original@example.invalid')
                visible=db.execute('SELECT name FROM `tab'+doctype+'` WHERE '+predicate+' ORDER BY name').fetchall()
                self.assertEqual(visible,[('legacy',),('legacy-empty',),('project',)])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM `tab'+doctype+'` WHERE '+predicate).fetchone()[0],3)
                self.assertEqual(hooks.permission_query_conditions[doctype],'cipher_aec.ricky.permissions.'+function)
                self.assertEqual(hooks.has_permission[doctype],'cipher_aec.ricky.permissions.has_permission')
        self.assertIs(permissions.has_permission({'scope_type':'Company'},user='original@example.invalid',ptype='read'),False)
        self.assertIsNone(permissions.has_permission({'scope_type':'Project'}))
        self.assertIsNone(permissions.has_permission({}))
        self.assertIsNone(permissions.has_permission({'scope_type':''}))
        self.assertIs(permissions.has_permission({'scope_type':'Unknown'}),False)
    def test_closed_stop_contract_has_no_selected_source_result_or_session_fields(self):
        from jsonschema import Draft202012Validator
        schema=json.loads((ROOT/'ricky/schemas/company-api-v1.schema.json').read_text())
        definition=schema['$defs']['CompanyRickyStopResponse']
        self.assertEqual(set(definition['properties']),{'id','company','scope_type','project','request_kind',
            'status','cancel_requested','operation'})
        Draft202012Validator.check_schema(schema)
        prefix='cipher_aec.ricky.company_api.'
        from cipher_aec.api.catalog import ROUTES
        self.assertEqual({name for name in ROUTES if name.startswith(prefix)},
            {prefix+name for name in ('start_read','get_run','run_events','cancel_run')})




class CompanyRickySessionOrderTests(unittest.TestCase):
    """Actual dispatcher sequencing with request-local non-DB doubles."""
    def setUp(self):
        from contextlib import contextmanager, nullcontext
        import uuid
        from cipher_aec.api.contracts import digest, canonical_json
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.events=[];self.reference='a'*64;self.saved=[];self.rows=[]
        self.actor=SimpleNamespace(user='original@example.invalid',person_id='canonical-person')
        self.stop_at_guard=False;self.missing_session=False;self.effect_failure=False
        provenance=ModuleType('cipher_aec.documents.provenance')
        provenance.logical_operation=lambda *a,**k:nullcontext()
        provenance.logical_operation_stats=lambda:None
        backend=ModuleType('cipher_aec.ricky.company_backend')
        @contextmanager
        def binding(*,actor,company,reference):
            self.events.append('start-context')
            self.assertIs(actor,self.actor);self.assertEqual(company,'Company');self.assertEqual(reference,'a'*64)
            if self.reference!=reference:raise BoundaryError('session_changed','',403)
            try:yield
            finally:self.events.append('start-context-exit')
        backend.start_session_binding=binding
        runtime=ModuleType('cipher_aec.awards.runtime');runtime.quiet_award_write=lambda doc:None
        self.stack.enter_context(patch.dict('sys.modules',{'cipher_aec.documents.provenance':provenance,
            'cipher_aec.ricky.company_backend':backend,'cipher_aec.awards.runtime':runtime}))
        def sql(query,*args,**kwargs):
            if 'tabCipher Command Receipt' in query:
                self.events.append('receipt-read');return self.rows
            self.events.append('person-lock');return []
        def actor(**kwargs):
            self.events.append('actor-lock' if kwargs.get('lock') else 'actor');return self.actor
        def company(value,**kwargs):
            self.events.append('company-lock' if kwargs.get('lock') else 'company');return SimpleNamespace(status='Open')
        def session_reference(actor):
            self.events.append('session-reference');return self.reference
        def require_session(actor,reference,**kwargs):
            self.events.append('session-lock');self.assertEqual(kwargs,{'lock':True})
            if self.missing_session:raise BoundaryError('session_revoked','',403)
        def get_doc(value):
            self.saved.append(value)
            return SimpleNamespace(insert=lambda **kwargs:self.events.append('receipt-insert'))
        self.digest=digest
        self.namespace={'DomainError':BoundaryError,'json':json,'uuid':uuid,'nullcontext':nullcontext,
            'assert_synthetic_site':lambda:None,'parse_operation_id':lambda value:value,'text':lambda value,label:value,
            'current_actor':actor,'require_company':company,'require_project':lambda *a,**k:SimpleNamespace(status='Open'),
            'session_authority_reference':session_reference,'require_session_authority':require_session,
            'COMPANY_RICKY_COMMANDS':frozenset({'ricky.company.read.start.v1','ricky.company.read.cancel.v1'}),
            'digest':digest,'canonical_json':canonical_json,'require_effects_enabled':lambda:None,
            'trusted_write':nullcontext,'authorize_receipt':lambda *a,**k:self.events.append('replay-authorize'),
            'frappe':SimpleNamespace(db=SimpleNamespace(sql=sql,savepoint=lambda name:self.events.append('savepoint'),
                rollback=lambda **kwargs:self.events.append('rollback')),get_doc=get_doc,
                QueryDeadlockError=type('Deadlock',(Exception,),{}),QueryTimeoutError=type('Timeout',(Exception,),{}))}
        self.command=selected_function('governance/commands.py','_run_scoped_command',self.namespace)
    def call(self,command='ricky.company.read.start.v1',*,scope='Company',guard=None):
        def effect(*args):
            self.events.append('effect')
            if self.effect_failure:raise BoundaryError('fixture_effect_failure','',409)
            return {'id':'original-run'}
        return self.command(company='Company',project=None if scope=='Company' else 'Project',scope_type=scope,
            operation_id='original-operation',command=command,payload={},ability='ricky.run',effect=effect,guard=guard,participant_people=())
    def test_start_captures_and_locks_session_before_company_then_binds_only_effect(self):
        self.call()
        self.assertLess(self.events.index('actor-lock'),self.events.index('session-reference'))
        self.assertLess(self.events.index('session-lock'),self.events.index('company-lock'))
        self.assertLess(self.events.index('company-lock'),self.events.index('receipt-read'))
        self.assertLess(self.events.index('start-context'),self.events.index('effect'))
        self.assertLess(self.events.index('start-context-exit'),self.events.index('receipt-insert'))
    def test_missing_current_session_refuses_before_company_or_receipt(self):
        self.missing_session=True
        with self.assertRaises(BoundaryError):self.call()
        self.assertNotIn('company-lock',self.events);self.assertNotIn('receipt-read',self.events)
    def test_session_changed_by_guard_refuses_before_effect(self):
        with self.assertRaises(BoundaryError):self.call(guard=lambda *a:setattr(self,'reference','b'*64))
        self.assertNotIn('effect',self.events);self.assertNotIn('receipt-insert',self.events)
        self.assertIn('rollback',self.events)
    def test_effect_failure_exits_binding_before_savepoint_rollback(self):
        self.effect_failure=True
        with self.assertRaises(BoundaryError):self.call()
        self.assertLess(self.events.index('start-context-exit'),self.events.index('rollback'))
    def test_completed_start_replay_uses_fresh_session_without_rebinding_original_run(self):
        self.reference='b'*64
        result={'id':'original-run'}
        self.rows=[SimpleNamespace(request_hash=self.digest({'scope_type':'Company','command':'ricky.company.read.start.v1',
            'company':'Company','project':None,'payload':{}}),result_json=json.dumps(result),result_hash=self.digest(result),
            scope_type='Company',company='Company',project=None)]
        self.assertTrue(self.call()['operation']['replayed'])
        self.assertIn('session-lock',self.events);self.assertIn('replay-authorize',self.events)
        self.assertNotIn('start-context',self.events);self.assertNotIn('effect',self.events)
    def test_cancel_other_company_and_project_never_use_start_session_bridge(self):
        for command,scope in [('ricky.company.read.cancel.v1','Company'),('other.command','Company'),('ricky.start','Project'),('ricky.company.read.start.v1','Project')]:
            self.events.clear();self.call(command,scope=scope)
            self.assertNotIn('session-reference',self.events);self.assertNotIn('session-lock',self.events)
            self.assertNotIn('start-context',self.events)

if __name__=='__main__':unittest.main()
