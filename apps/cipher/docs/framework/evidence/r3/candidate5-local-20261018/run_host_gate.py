"""Reproduce Candidate5's recorded 544-case host gate from a published checkout.

Only paths and the Python executable are adapted. The two external regression
modules and captured Frappe reference sources remain the exact validated bytes.
No Frappe runtime, provider, Docker service or application installation is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ARTIFACT = Path(__file__).resolve().parent


def sha(value):
    return hashlib.sha256(value).hexdigest()


def verified_bytes(path, expected):
    value = path.read_bytes()
    if sha(value) == expected:
        return value
    # Git checkouts may materialize CRLF. Bind the original LF content only;
    # never rewrite source, and never normalize a binary or non-UTF-8 file.
    value.decode('utf-8')
    if b'\0' not in value and sha(value.replace(b'\r\n', b'\n')) == expected:
        return value.replace(b'\r\n', b'\n')
    raise ValueError('Candidate5 source or regression bytes differ: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', required=True, type=Path,
                        help='Published repository root; use . when running there.')
    parser.add_argument('--output-dir', type=Path,
                        help='New external result directory. Defaults to a new temporary directory.')
    args = parser.parse_args()
    repo = args.repo_root.resolve(strict=True)
    output = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix='cipher-candidate5-host-'))
    if args.output_dir:
        output.mkdir(parents=True, exist_ok=False)
    app = repo / 'apps/cipher/platform/apps/cipher_aec'
    publication = json.loads((ARTIFACT / 'PUBLICATION_RECEIPT.json').read_text())
    source_manifest = ARTIFACT / 'SOURCE_MANIFEST.json'
    verified_bytes(source_manifest, publication['source_manifest_sha256'])
    manifest = json.loads(source_manifest.read_text())
    assert manifest['files_count'] == len(manifest['files']) == 914
    source_hashes = {}
    for row in manifest['files']:
        source_hashes[row['path']] = sha(verified_bytes(repo / row['path'], row['sha256']))
    for row in publication['exact_external_runtime_inputs']:
        verified_bytes(ARTIFACT / row['path'], row['sha256'])
    gate_file = ARTIFACT / 'HOST_GATE.json'
    verified_bytes(gate_file, publication['recorded_host_gate_sha256'])
    gate = json.loads(gate_file.read_text())
    assert gate['status'] == 'PASS' and gate['results'][0]['tests'] == 544
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE='1', CIPHER_SEMANTIC_SOURCE_ROOT=str(repo),
               PYTHONPATH=os.pathsep.join([str(app), str(ARTIFACT / 'semantic-host')]))
    results = []
    for recorded in gate['results']:
        # Preserve every recorded test/module/flag, substituting only Python.
        command = [sys.executable] + recorded['command'][1:]
        run = subprocess.run(command, cwd=app, env=env, text=True, capture_output=True)
        log = run.stdout + run.stderr
        name = recorded['case'] + '.log'
        (output / name).write_text(log, encoding='utf-8', newline='\n')
        count = re.search(r'Ran (\d+) tests?', log)
        tests = int(count.group(1)) if count else None
        result = {'case':recorded['case'], 'command':command, 'exit_code':run.returncode,
                  'tests':tests, 'log':name, 'log_sha256':sha(log.encode())}
        results.append(result)
        print(recorded['case'], run.returncode, tests if tests is not None else '', flush=True)
        if run.returncode != 0 or tests != recorded['tests']:
            raise RuntimeError('Reproduced host gate failed; retained output: ' + str(output))
        if re.search(r'\b(skipped|expected failures|unexpected successes)=', log):
            raise RuntimeError('Unexpected skip or expected-failure outcome; retained output: ' + str(output))
    for row in manifest['files']:
        assert sha(verified_bytes(repo / row['path'], row['sha256'])) == source_hashes[row['path']]
    result = {'schema':'cipher.candidate5.published-host-reproduction.v1', 'status':'PASS',
              'source_files_verified':914, 'host_tests':544, 'openapi_check':'PASS',
              'external_transaction_cas_tests':21, 'source_unchanged':True,
              'recorded_gate_sha256':publication['recorded_host_gate_sha256'],
              'source_manifest_sha256':publication['source_manifest_sha256'],
              'results':results, 'native_runtime_provider_qualification':False}
    (output / 'REPRODUCTION.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n',
                                           encoding='utf-8', newline='\n')
    print(str(output / 'REPRODUCTION.json'), flush=True)


if __name__ == '__main__':
    main()
