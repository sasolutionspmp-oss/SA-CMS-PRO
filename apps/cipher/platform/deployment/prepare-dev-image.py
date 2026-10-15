#!/usr/bin/env python3
"""Import a verified upstream merged filesystem without vfs layer amplification.

Requires crane 0.20.3 on PATH. Does not change daemon settings or remove images.
The upstream manifest and imported image are both recorded for reproducibility.
"""
import argparse
import json
import os
import subprocess
from pathlib import Path

UPSTREAM = 'registry-1.docker.io/frappe/erpnext@sha256:772d0f84dd308632aa8cecd615564bd7597eb98e0a7d2208bd9aa04678ced1ee'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--crane', default='crane')
    parser.add_argument('--tag', default='cipher-erpnext:v16.51.0-flat')
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    env = os.environ.copy()
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        env.pop(key, None)
    config = json.loads(subprocess.check_output([args.crane, 'config', UPSTREAM], env=env))['config']
    command = ['docker', '--host=unix:///var/run/docker.sock', 'image', 'import', '--platform=linux/amd64']
    instructions = {'User': 'USER', 'WorkingDir': 'WORKDIR', 'Entrypoint': 'ENTRYPOINT', 'Cmd': 'CMD'}
    for key, instruction in instructions.items():
        value = config.get(key)
        if value:
            command += ['--change', instruction + ' ' + (json.dumps(value) if isinstance(value, list) else value)]
    for entry in config.get('Env', []):
        key, value = entry.split('=', 1)
        command += ['--change', 'ENV ' + key + '=' + json.dumps(value)]
    command += ['-', args.tag]
    exporter = subprocess.Popen([args.crane, 'export', UPSTREAM, '-'], stdout=subprocess.PIPE, env=env)
    try:
        result = subprocess.run(command, stdin=exporter.stdout, capture_output=True, text=True, env=env)
    finally:
        exporter.stdout.close()
    export_status = exporter.wait()
    if result.returncode or export_status:
        raise SystemExit(f'Image preparation failed: export={export_status}, import={result.returncode}: {result.stderr}')
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps({'upstream': UPSTREAM, 'image_id': result.stdout.strip(),
                                      'tag': args.tag, 'method': 'verified-manifest merged rootfs import',
                                      'export_exit': export_status, 'import_exit': result.returncode}, indent=2) + '\n')
    print(result.stdout.strip())

if __name__ == '__main__':
    main()
