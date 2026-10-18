"""Closed schema parity against actual FLD-03 host command results."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator,FormatChecker,ValidationError
from .quality_safety_fixtures import fixtures,uid,add_person,add_source
from .test_quality_safety import definition,transition

ROOT=Path(__file__).parents[1]
SCHEMA=json.loads((ROOT/'quality_safety/schemas/api-v1.schema.json').read_text())
ROUTES=json.loads((ROOT/'quality_safety/route-contracts.json').read_text())
def validate(name,value):
    Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':SCHEMA['$defs']},format_checker=FormatChecker()).validate(value)

class QualitySafetyContractsTests(unittest.TestCase):
    def test_all_objects_closed_refs_resolved_and_exact_api_parameters(self):
        Draft202012Validator.check_schema(SCHEMA)
        def walk(value):
            if type(value) is dict:
                if value.get('type')=='object':self.assertIs(value.get('additionalProperties'),False)
                if '$ref' in value:self.assertIn(value['$ref'].split('/')[-1],SCHEMA['$defs'])
                for item in value.values():walk(item)
            elif type(value) is list:
                for item in value:walk(item)
        walk(SCHEMA)
        functions={f.name:f for f in ast.parse((ROOT/'quality_safety/api.py').read_text()).body if isinstance(f,ast.FunctionDef) and not f.name.startswith('_')}
        # Private raw-request validation helpers are not API endpoints.
        for node in functions.values():
            self.assertTrue(any(isinstance(d,ast.Call) and isinstance(d.func,ast.Name) and d.func.id=='endpoint' for d in node.decorator_list))
        self.assertEqual(set(functions),set(ROUTES['requests']))
        for name,node in functions.items():
            request=SCHEMA['$defs'][ROUTES['requests'][name]];args=[a.arg for a in node.args.args]
            self.assertEqual(set(request['properties']),set(args));self.assertEqual(set(request['required']),set(args[:len(args)-len(node.args.defaults)] if node.args.defaults else args))

    def test_real_all_categories_and_private_decisions_match_response_schemas(self):
        for family,category in [('record',v) for v in ('inspection','deficiency','safety_observation','permit_record')]+[('incident','incident')]:
            with self.subTest(category=category),fixtures() as (state,rules,repo,sources,service,records):
                authored=definition(family,category);refs=[add_source(state) for _ in range(3)]
                if family=='incident':authored.update(shared_evidence_revisions=[s['revision_id'] for s in refs],shared_evidence_statement='Exact declared non-sensitive ordinary sources.')
                request={'company':'C','project':'P','operation_id':uid(),'family':family,'category':category,'definition':authored,'evidence':[refs[0]]};validate('QsCreateRecordRequest',request)
                first=service.create_record(**request);validate('QsCreateRecordResponse',first)
                submitted=transition(state,service,first,'submit');validate('QsTransitionResponse',submitted);state.actor=add_person(state,'checker')
                checked=transition(state,service,submitted,'check',evidence=[refs[1]]);validate('QsTransitionResponse',checked);state.actor=add_person(state,'closer')
                closure=[{'item_id':row['item_id'],'evidence':[refs[2]]} for row in authored['required_closure_items']]
                closed=transition(state,service,checked,'close',closure=closure);validate('QsTransitionResponse',closed)
                for kind,value in ((family,closed['header']),(rules.child_kind(family,'revision'),first['revision']),(rules.child_kind(family,'decision'),closed['decision'])):
                    response=service.get_record('C','P',kind,value['id']);validate('QsGetResponse',response)
                amended=service.revise_record('C','P',uid(),family,first['header']['id'],__import__('cipher_aec.api.contracts',fromlist=['digest']).digest(closed['header']),authored,[refs[0]],'Corrected documentary content.')
                validate('QsReviseRecordResponse',amended)

    def test_closed_requests_reject_private_fields_authority_and_wrong_family(self):
        request={'company':'C','project':'P','operation_id':uid(),'family':'record','category':'inspection','definition':definition(),'evidence':[{'revision_id':uid(),'source_sha256':'a'*64,'page':1,'locator':'Exact source'}]}
        validate('QsCreateRecordRequest',request)
        for invalid in ({**request,'actor_person':uid()},{**request,'family':'incident'},{**request,'definition':{**request['definition'],'restricted_account':'Private'}},{**request,'category':'permit_record'}):
            with self.assertRaises(ValidationError):validate('QsCreateRecordRequest',invalid)
        request={'company':'C','project':'P','operation_id':uid(),'family':'record','record_id':uid(),'expected_version':'a'*64,'action':'close','comment':'Close','evidence':[],'closure':[]}
        with self.assertRaises(ValidationError):validate('QsTransitionRequest',request)

    def test_native_types_have_no_generic_role_permissions_or_edit_history(self):
        types=list((ROOT/'cipher_quality_safety/doctype').glob('*/*.json'));self.assertEqual(len(types),7)
        for path in types:
            data=json.loads(path.read_text());self.assertEqual(data['permissions'],[]);self.assertEqual(data['track_changes'],0);self.assertEqual(data['allow_rename'],0)
            if data['name'].endswith('Decision'):self.assertNotIn('revision_number',{f['fieldname'] for f in data['fields']})
        self.assertNotIn('incident',ROUTES['requests']) # no unguarded legacy path

if __name__=='__main__':unittest.main()
