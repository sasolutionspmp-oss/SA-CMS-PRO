#!/usr/bin/env python3
"""Portable synthetic Cipher trial; Docker Compose v2 and Python 3.12+ required."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
CIPHER = HERE.parents[1]
PROFILES = {'trial': (18890, 18891), 'integration': (18900, 18901)}
SUFFIXES = ('database.sql.gz', 'files.tgz', 'private-files.tgz', 'site_config_backup.json')
PREFIX = re.compile(r'[0-9]{8}_[0-9]{6}-cipher_localhost')
ENV_KEYS = {'CIPHER_DB_ROOT_PASSWORD', 'CIPHER_ADMIN_PASSWORD', 'CIPHER_FIXTURE_PASSWORD',
            'CIPHER_IMAGE', 'CIPHER_HTTP_PORT', 'CIPHER_BACKEND_PORT'}


class LocalError(Exception):
    pass


def private_directory(path):
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def environment_path(profile):
    return HERE / '.local' / profile / 'environment'


def initialize(profile):
    path = environment_path(profile)
    private_directory(path.parent)
    if path.exists():
        raise LocalError('The private environment already exists; refusing to replace credentials.')
    http, backend = PROFILES[profile]
    values = {key: secrets.token_urlsafe(36) for key in
              ('CIPHER_DB_ROOT_PASSWORD', 'CIPHER_ADMIN_PASSWORD', 'CIPHER_FIXTURE_PASSWORD')}
    values.update(CIPHER_IMAGE='cipher-local:framework-trial', CIPHER_HTTP_PORT=str(http), CIPHER_BACKEND_PORT=str(backend))
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    path.chmod(0o600)
    print(f'Created private {profile} environment: {path}')
    print('Retain this file with the private recovery bundle. Credentials are not printed.')


def settings(profile):
    path = environment_path(profile)
    if not path.is_file():
        raise LocalError(f'Initialize this profile first: python cipher-local.py --profile {profile} init')
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator or key not in ENV_KEYS or key in values or not value or any(c in value for c in '\r\n$#\"\' '):
            raise LocalError('The private environment contains an unsupported entry.')
        values[key] = value
    if set(values) != ENV_KEYS:
        raise LocalError('The private environment is incomplete.')
    expected = tuple(str(port) for port in PROFILES[profile])
    if (values['CIPHER_HTTP_PORT'], values['CIPHER_BACKEND_PORT']) != expected:
        raise LocalError('Profile ports must remain distinct; use the documented profile defaults.')
    passwords = [values[key] for key in sorted(ENV_KEYS) if key.endswith('PASSWORD')]
    if len(set(passwords)) != 3 or any(len(value) < 24 or value.startswith('replace-') for value in passwords):
        raise LocalError('Use three different generated local credentials of at least 24 characters.')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.:/@-]{2,200}', values['CIPHER_IMAGE']):
        raise LocalError('The local image reference is invalid.')
    return values


def compose_command(profile, *arguments):
    settings(profile)
    return ['docker', 'compose', '--project-name', 'cipher-' + profile,
            '--env-file', str(environment_path(profile)), '-f', str(HERE / 'compose.portable.yml'), *arguments]


def compose(profile, *arguments, capture=False, image=None):
    # Host CIPHER_* variables must not override the selected profile's env-file.
    environment = {key: value for key, value in os.environ.items() if not key.startswith('CIPHER_')}
    if image is not None:
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
            raise LocalError('One-off image overrides require an immutable local image ID.')
        environment['CIPHER_IMAGE'] = image
    return subprocess.run(compose_command(profile, *arguments), cwd=HERE, env=environment,
                          check=True, text=True, stdout=subprocess.PIPE if capture else None)


@contextmanager
def profile_lock(profile):
    """OS-owned lock releases after interruption; the persistent journal does not."""
    path = environment_path(profile).parent / 'operator.lock'
    private_directory(path.parent)
    with path.open('a+b') as stream:
        stream.seek(0)
        stream.write(b'0')
        stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise LocalError('Another operator command owns this profile.') from error
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def source_identity():
    digest = hashlib.sha256()
    roots = [CIPHER / 'platform/apps/cipher_aec', CIPHER / 'product', HERE]
    excluded = {'.local', 'node_modules', 'dist', '__pycache__', 'test-results', 'playwright-report'}
    files = set()
    for root in roots:
        for path in root.rglob('*'):
            if not path.is_file() or any(part in excluded or part.endswith('.egg-info') for part in path.relative_to(root).parts):
                continue
            if path.name.startswith('.env') or path.suffix == '.pyc':
                continue
            files.add(path)
    files.update(CIPHER / 'platform/operations' / ('backup-synthetic.sh' if index == 0 else 'restore-synthetic.sh') for index in range(2))
    for path in sorted(files):
        digest.update(str(path.relative_to(CIPHER)).replace('\\', '/').encode() + b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    result = subprocess.run(['git', '-C', str(CIPHER), 'rev-parse', 'HEAD'], check=True, text=True, stdout=subprocess.PIPE)
    return result.stdout.strip(), digest.hexdigest()


def backup(profile, destination=None):
    compose(profile, 'exec', '-T', 'runtime', 'bash', '/opt/cipher/operations/backup-synthetic.sh')
    query = """import json,os
from pathlib import Path
p=Path('/home/frappe/frappe-bench/sites/cipher.localhost/private/backups')
s=('database.sql.gz','files.tgz','private-files.tgz','site_config_backup.json')
prefixes=sorted((x.name[:-len('-site_config_backup.json')] for x in p.glob('*-site_config_backup.json')), reverse=True)
complete=[prefix for prefix in prefixes if all((p/(prefix+'-'+suffix)).is_file() for suffix in s)]
if not complete: raise SystemExit('No complete backup set')
print(json.dumps({'prefix':complete[0],'build_id':os.environ['CIPHER_BUILD_ID']}))
"""
    runtime = json.loads(compose(profile, 'exec', '-T', 'runtime', 'python', '-c', query, capture=True).stdout)
    prefix = runtime['prefix']
    if not PREFIX.fullmatch(prefix):
        raise LocalError('The runtime returned an invalid backup prefix.')
    target = Path(destination).resolve() if destination else HERE / '.local' / profile / 'backups' / prefix
    if target.exists():
        raise LocalError('The backup destination already exists; refusing to overwrite it.')
    private_directory(target)
    hashes = {}
    for suffix in SUFFIXES:
        name = prefix + '-' + suffix
        compose(profile, 'cp', f'runtime:/home/frappe/frappe-bench/sites/cipher.localhost/private/backups/{name}', str(target / name))
        (target / name).chmod(0o600)
        hashes[name] = hashlib.sha256((target / name).read_bytes()).hexdigest()
    manifest = {'schema': 'cipher.local-backup.v1', 'prefix': prefix, 'source_profile': profile,
                'build_id': runtime['build_id'], 'image_reference': settings(profile)['CIPHER_IMAGE'],
                'created_at': datetime.now(timezone.utc).isoformat(), 'sha256': hashes,
                'restore_policy': 'isolated site; scheduler paused; execution quarantined'}
    manifest_path = target / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    manifest_path.chmod(0o600)
    print(f'Exported a complete private backup with SHA-256 manifest: {target}')


def checked_backup(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    prefix = manifest.get('prefix', '')
    if manifest.get('schema') != 'cipher.local-backup.v1' or not PREFIX.fullmatch(prefix):
        raise LocalError('The backup manifest has an unsupported format.')
    if not re.fullmatch(r'[a-f0-9]{64}', manifest.get('build_id', '')):
        raise LocalError('The recovery bundle is missing its source build identity.')
    names = {prefix + '-' + suffix for suffix in SUFFIXES}
    if set(manifest.get('sha256', {})) != names:
        raise LocalError('The recovery bundle must contain exactly the four supported backup files.')
    for name in names:
        path = directory / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != manifest['sha256'][name]:
            raise LocalError('Recovery bundle checksum verification failed.')
    return directory, manifest


def runtime_owner(profile):
    identifiers = []
    for option in ('-u', '-g'):
        value = compose(profile, 'exec', '-T', 'runtime', 'id', option, capture=True).stdout.strip()
        if not re.fullmatch(r'[0-9]{1,10}', value) or int(value) >= 2 ** 32 - 1:
            raise LocalError('The runtime returned an invalid numeric ownership identifier.')
        identifiers.append(str(int(value)))
    return ':'.join(identifiers)


def restore(profile, directory):
    directory, manifest = checked_backup(directory)
    identity = compose(profile, 'exec', '-T', 'runtime', 'python', '-c',
                       "import os; print(os.environ['CIPHER_BUILD_ID'])", capture=True).stdout.strip()
    if identity != manifest['build_id']:
        raise LocalError('The backup and target image have different build identities; qualify a compatible recovery image first.')
    owner = runtime_owner(profile)
    staging = '/tmp/cipher-import-' + uuid.uuid4().hex
    compose(profile, 'exec', '-T', 'runtime', 'mkdir', '-m', '700', staging)
    for name in sorted(manifest['sha256']):
        compose(profile, 'cp', str(directory / name), 'runtime:' + staging + '/' + name)
    # Docker cp creates container files as root even when the image runs frappe.
    # Restrict the ownership repair to our newly allocated import directory.
    compose(profile, 'exec', '-T', '--user', 'root', 'runtime', 'chown', '-R', owner, staging)
    # Publish only complete checked files. Existing backup bytes are preserved;
    # source site records/configuration are never replaced by this import.
    publish = """import hashlib,json,os,shutil,sys
from pathlib import Path
source=Path(sys.argv[1]); manifest=json.loads(sys.argv[2])
target=Path('/home/frappe/frappe-bench/sites/cipher.localhost/private/backups')
target.mkdir(parents=True,exist_ok=True)
for name,expected in manifest['sha256'].items():
 p=source/name; dest=target/name
 if hashlib.sha256(p.read_bytes()).hexdigest()!=expected: raise SystemExit('Imported checksum mismatch')
 if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest()!=expected: raise SystemExit('Backup filename collision; refusing overwrite')
for name in manifest['sha256']:
 dest=target/name
 if not dest.exists():
  with dest.open('xb') as out, (source/name).open('rb') as inp: shutil.copyfileobj(inp,out)
  dest.chmod(0o600)
shutil.rmtree(source)
"""
    compose(profile, 'exec', '-T', 'runtime', 'python', '-c', publish, staging, json.dumps(manifest))
    site = 'cipher-restore-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S') + '.localhost'
    compose(profile, 'exec', '-T', '-e', 'CIPHER_RESTORE_SITE=' + site, 'runtime',
            'bash', '/opt/cipher/operations/restore-synthetic.sh', manifest['prefix'])
    compose(profile, 'exec', '-T', 'runtime', 'python', '/opt/cipher/deployment/portable-recovery.py', site,
            '/home/frappe/frappe-bench/sites/cipher.localhost/private/backups/' + manifest['prefix'] + '-site_config_backup.json')
    print(f'Restored into {site} in the {profile} namespace. Scheduler is paused and execution is quarantined.')
    print('This rehearsal does not replace or serve the active trial site. Complete authenticated read/byte checks before any recovery release.')
    print('Restored users retain the original backup passwords; this profile\'s generated fixture password does not replace them.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, default='trial')
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('init', 'build', 'start', 'status', 'stop', 'logs'):
        sub.add_parser(name)
    save = sub.add_parser('backup')
    save.add_argument('--destination', type=Path)
    recover = sub.add_parser('restore')
    recover.add_argument('directory', type=Path)
    sub.add_parser('build-candidate')
    upgrade = sub.add_parser('upgrade')
    upgrade.add_argument('--candidate', type=Path, required=True)
    upgrade.add_argument('--acknowledge-build', required=True)
    upgrade.add_argument('--writers-quiesced', action='store_true', required=True)
    upgrade.add_argument('--resume', action='store_true')
    recovery = sub.add_parser('upgrade-restore')
    recovery.add_argument('--candidate', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action in ('build-candidate', 'upgrade', 'upgrade-restore'):
        if args.profile != 'integration':
            raise LocalError('Candidate upgrades and recovery are restricted to integration.')
        import importlib.util
        spec = importlib.util.spec_from_file_location('cipher_portable_upgrade', HERE / 'portable-upgrade.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from types import SimpleNamespace
        operator = SimpleNamespace(**globals())
        with profile_lock(args.profile):
            if args.action == 'build-candidate':
                module.build_candidate(operator)
            elif args.action == 'upgrade':
                module.upgrade(operator, args.candidate, args.acknowledge_build, resume=args.resume)
            else:
                module.restore_upgrade(operator, args.candidate)
        return 0
    if args.action not in ('status', 'logs', 'init'):
        with profile_lock(args.profile):
            active = environment_path(args.profile).parent / 'upgrade-active.json'
            if active.exists():
                raise LocalError('An upgrade is pending. Resume it or use upgrade-restore; ordinary profile commands are blocked.')
            return ordinary_action(args)
    return ordinary_action(args)


def ordinary_action(args):
    if args.action == 'init':
        initialize(args.profile)
    elif args.action == 'build':
        revision, build = source_identity()
        compose(args.profile, 'build', '--build-arg', 'CIPHER_SOURCE_REVISION=' + revision,
                '--build-arg', 'CIPHER_BUILD_ID=' + build, 'runtime')
        print(f'Built portable image from {revision}; source content SHA-256 {build}')
    elif args.action == 'start':
        compose(args.profile, 'up', '--detach', '--no-build', '--wait', '--wait-timeout', '900')
        print(f'{args.profile.capitalize()} UI: http://cipher-{args.profile}.localhost:{PROFILES[args.profile][0]}')
    elif args.action == 'status':
        compose(args.profile, 'ps')
        print(f'UI: http://cipher-{args.profile}.localhost:{PROFILES[args.profile][0]}')
    elif args.action == 'stop':
        compose(args.profile, 'stop', '--timeout', '30')
        print('Stopped the selected profile; all persistent volumes are retained.')
    elif args.action == 'logs':
        compose(args.profile, 'logs', '--tail', '150', 'runtime')
    elif args.action == 'backup':
        backup(args.profile, args.destination)
    elif args.action == 'restore':
        restore(args.profile, args.directory)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (LocalError, OSError, ValueError, subprocess.CalledProcessError) as error:
        # Commands contain paths/manifest hashes, never credential values.
        print('Cipher local command failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
