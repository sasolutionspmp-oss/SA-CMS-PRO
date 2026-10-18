"""Syntax/source checks only. Never import Frappe or execute prepared probes."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
CHECKOUT = Path(os.environ.get('CIPHER_CONTRACT_CHECKOUT', str(ROOT / 'repository')))
BACKEND = '310a946bd34d06c9f7c1a3d96ab7274733142cd9'
OFFLINE = '392a19f8c01b4253a5aaeaa99878408d394dc9cb'


def run():
    tests = ROOT / 'native_tests' / 'test_field_offline_native.py'
    fixture = ROOT / 'native_tests' / 'fld02_native_fixture.py'
    assert tests.is_file() and fixture.is_file(), 'Native preparation is incomplete.'
    files = sorted([*ROOT.joinpath('native_tests').glob('*.py'),
                    *ROOT.joinpath('http_driver').glob('*.py')])
    parsed = {}
    for path in files:
        data = path.read_bytes()
        tree = ast.parse(data, filename=str(path))
        compile(tree, str(path), 'exec')  # compilation only, no import/execution
        parsed[path] = tree
    tree = parsed[tests]
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)
               and any(isinstance(b, ast.Name) and b.id == 'IntegrationTestCase' for b in n.bases)]
    assert classes, 'Expected genuine declared IntegrationTestCase subclass.'
    declared = [n.name for c in classes for n in c.body
                if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')]
    assert len(declared) >= 12, 'Expected meaningful prepared case coverage.'
    banned = {'patch', 'Mock', 'MagicMock', 'nullcontext', 'seed_synthetic', 'migrate'}
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, 'module', '') or ''
            assert 'unittest.mock' not in module
            assert not any('unittest.mock' in n.name for n in node.names)
        if isinstance(node, ast.Call):
            name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            assert name not in banned, 'Forbidden test double/setup call: ' + str(name)
            if name == 'commit':
                raise AssertionError('No commits inside the rollback-only native test module.')
            if name == 'rollback':
                assert any(k.arg == 'save_point' for k in node.keywords), 'Require a named case savepoint rollback.'
            calls.append(name)
    required = {'register_device', 'stage_capture', 'inspect_capture', 'apply_capture',
                'get_capture', 'discard_capture', 'resolve_capture', 'revoke_device'}
    assert required.issubset(calls), 'Offline native command coverage is incomplete.'
    fixture_calls = {getattr(n.func, 'id', None) or getattr(n.func, 'attr', None)
                     for n in ast.walk(parsed[fixture]) if isinstance(n, ast.Call)}
    assert not {'seed_synthetic', '_grant', '_grant_company', 'migrate'}.intersection(fixture_calls)
    for path in files:
        text = path.read_text()
        assert '@cipher.example' not in text, 'Dedicated probes must use synthetic.example identities.'
    bound = json.loads((ROOT / 'SOURCE_CONTRACTS.json').read_text())
    assert bound['backend_reference'] == BACKEND and bound['offline_reference'] == OFFLINE
    for item in bound['files']:
        data = subprocess.check_output(['git', 'show', item['ref'] + ':' + item['path']],
                                       cwd=CHECKOUT)
        assert hashlib.sha256(data).hexdigest() == item['sha256']
    receipt = {
        'qualification': 'STATIC PREPARATION ONLY; no native, HTTP, DB, runtime, provider or model execution.',
        'syntax_source_checks': 'PASS', 'declared_native_methods': declared,
        'native_status': 'UNRUN', 'http_status': 'UNRUN',
        'backend_reference': BACKEND, 'offline_reference': OFFLINE,
        'source_contract_files_verified': len(bound['files']),
        'files': [{'path': str(p.relative_to(ROOT)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                  for p in files],
    }
    (ROOT / 'STATIC_PREPARATION_RECEIPT.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    run()
