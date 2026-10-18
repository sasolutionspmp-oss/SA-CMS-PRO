"""Cross-package wire/native contracts for the explicit FLD02/03 composition."""
import ast
import json
from pathlib import Path
import unittest

from cipher_aec.api.catalog import ROUTES
from cipher_aec.api.openapi import ROOT, generate, _rewrite
from cipher_aec.quality_safety.contracts import ABILITIES


class FieldCompositionContracts(unittest.TestCase):
    def test_owned_definitions_are_exact_core_and_openapi_mirrors(self):
        core = json.loads((ROOT / 'api/schema.json').read_text())['$defs']
        generated = generate()['components']['schemas']
        for domain in ('field_offline', 'quality_safety'):
            definitions = json.loads((ROOT / domain / 'schemas/api-v1.schema.json').read_text())['$defs']
            for name, definition in definitions.items():
                with self.subTest(domain=domain, definition=name):
                    self.assertEqual(core[name], definition)
                    self.assertEqual(generated[name], _rewrite(definition))

    def test_all_owned_routes_keep_exact_closed_body_conditions_and_command_headers(self):
        document = generate()
        for domain in ('field_offline', 'quality_safety'):
            module = 'cipher_aec.' + domain + '.api'
            contracts = json.loads((ROOT / domain / 'route-contracts.json').read_text())
            definitions = json.loads((ROOT / domain / 'schemas/api-v1.schema.json').read_text())['$defs']
            self.assertEqual(set(contracts['requests']), set(contracts['responses']))
            for method, request in contracts['requests'].items():
                route_id = module + '.' + method
                route = ROUTES[route_id]
                operation = document['paths']['/api/method/' + route_id][route.method.lower()]
                expected = _rewrite(definitions[request])
                with self.subTest(route=route_id):
                    self.assertEqual(route.response, contracts['responses'][method])
                    if route.method == 'POST':
                        body = operation['requestBody']['content']['application/json']['schema']
                        self.assertEqual(body, expected)
                        self.assertFalse(body['additionalProperties'])
                        self.assertEqual({p['name'] for p in operation['parameters']}, {'X-Frappe-CSRF-Token', 'Idempotency-Key'})
                        self.assertTrue(route.command)
                    else:
                        self.assertFalse(route.command)
                        self.assertEqual({p['name']: p['schema'] for p in operation['parameters']}, expected['properties'])
                        self.assertEqual(operation['x-request-schema'], expected)

    def test_nine_explicit_quality_duties_have_native_choices_and_no_default_grants(self):
        context = ast.parse((ROOT / 'governance/context.py').read_text())
        values = {'QUALITY_SAFETY_ABILITIES': ABILITIES}
        for node in context.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id.endswith('ABILITIES'):
                values[node.targets[0].id] = eval(compile(ast.Expression(node.value), '<capability catalog>', 'eval'), {'frozenset': frozenset}, values)
        metadata = json.loads((ROOT / 'cipher_governance/doctype/cipher_project_duty/cipher_project_duty.json').read_text())
        field = next(row for row in metadata['fields'] if row['fieldname'] == 'ability')
        self.assertEqual(len(ABILITIES), 9)
        self.assertTrue(ABILITIES <= values['PROJECT_ABILITIES'])
        self.assertFalse(ABILITIES & values['COMPANY_ABILITIES'])
        self.assertEqual(set(field['options'].splitlines()), values['ABILITIES'])
        seed = next(n for n in ast.parse((ROOT / 'install.py').read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'seed_synthetic')
        grants = [n.iter for n in ast.walk(seed) if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == 'ability' and any(isinstance(child, ast.Name) and child.id == 'PROJECT_ABILITIES' for child in ast.walk(n.iter))]
        self.assertEqual(len(grants), 1)
        actual = set(eval(compile(ast.Expression(grants[0]), '<default grants>', 'eval'), {'sorted': sorted}, values))
        self.assertFalse(actual & ABILITIES)
        self.assertIn('project.write', actual)

    def test_every_new_native_json_type_has_both_effective_deny_hooks(self):
        from cipher_aec import hooks
        for directory in ('cipher_field_offline', 'cipher_quality_safety'):
            for path in (ROOT / directory / 'doctype').glob('*/*.json'):
                metadata = json.loads(path.read_text())
                doctype = metadata['name']
                with self.subTest(doctype=doctype):
                    self.assertIn(doctype, hooks.permission_query_conditions)
                    self.assertIn(doctype, hooks.has_permission)
                    # FLD02 keeps System Manager read metadata; the hooks must
                    # deny even that role before any native row is exposed.
                    for row in metadata.get('permissions', []):
                        self.assertEqual(row['role'], 'System Manager')
                        self.assertFalse(any(row.get(key) for key in ('write', 'create', 'delete', 'export')))
                    for registry, expected in ((hooks.permission_query_conditions, '1=0'), (hooks.has_permission, False)):
                        module, function = registry[doctype].rsplit('.', 1)
                        source = ROOT.joinpath(*module.split('.')[1:]).with_suffix('.py')
                        node = next(node for node in ast.parse(source.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == function)
                        namespace = {}
                        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
                        callback = namespace[function]
                        actual = callback(user='Administrator') if expected == '1=0' else callback(None, user='Administrator')
                        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
