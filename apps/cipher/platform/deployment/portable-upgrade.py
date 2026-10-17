"""Integration-only offline upgrade orchestration. Import has no side effects."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

PROFILE = 'integration'
PYTHON = '/home/frappe/frappe-bench/env/bin/python'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    pending = path.with_suffix('.pending')
    with pending.open('w', encoding='utf-8', newline='\n') as stream:
        pending.chmod(0o600)
        stream.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def docker(*arguments):
    return subprocess.run(('docker', *arguments), check=True, text=True, stdout=subprocess.PIPE).stdout.strip()


def image(local, reference):
    record = json.loads(docker('image', 'inspect', reference))[0]
    labels = record.get('Config', {}).get('Labels') or {}
    result = {'id': record['Id'], 'build_id': labels.get('io.cipher.build-id'),
              'revision': labels.get('org.opencontainers.image.revision')}
    environment = record.get('Config', {}).get('Env') or []
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', result['id']) or not re.fullmatch(r'[a-f0-9]{64}', result['build_id'] or ''):
        raise local.LocalError('The image lacks an immutable Cipher source identity.')
    if not re.fullmatch(r'[a-f0-9]{40,64}', result['revision'] or '') or 'CIPHER_BUILD_ID=' + result['build_id'] not in environment:
        raise local.LocalError('Image revision/build labels and runtime identity must agree.')
    return result


def context():
    return {'context': docker('context', 'show'), 'daemon': docker('info', '--format', '{{.ID}}')}


def active(local):
    return local.environment_path(PROFILE).parent / 'upgrade-active.json'


def check_active(local, state, state_path):
    if active(local).exists() and json.loads(active(local).read_text()) != {'journal': str(state_path), 'id': state['id']}:
        raise local.LocalError('A different upgrade owns the integration startup guard.')


def build_candidate(local):
    if active(local).exists():
        raise local.LocalError('Resume the pending upgrade before building another candidate.')
    local.settings(PROFILE)
    revision, build = local.source_identity()
    reference = 'cipher-local:integration-' + build
    directory = local.environment_path(PROFILE).parent / 'candidates'
    local.private_directory(directory)
    receipt = directory / (build + '.json')
    if receipt.exists():
        raise local.LocalError('This candidate already has a receipt; reuse it or build new source.')
    probe = subprocess.run(('docker', 'image', 'inspect', reference), text=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode == 0:
        raise local.LocalError('The unique candidate tag exists without this receipt; refusing to overwrite it.')
    docker('build', '--file', str(local.HERE / 'Dockerfile.portable'), '--tag', reference,
           '--build-arg', 'CIPHER_SOURCE_REVISION=' + revision, '--build-arg', 'CIPHER_BUILD_ID=' + build,
           str(local.CIPHER))
    if local.source_identity() != (revision, build):
        raise local.LocalError('Source changed during the candidate build. Retain the unqualified image and rebuild frozen source under its new identity.')
    candidate = image(local, reference)
    if candidate['build_id'] != build or candidate['revision'] != revision:
        raise local.LocalError('Built candidate provenance does not match the selected source.')
    write(receipt, {'schema': 'cipher.local-candidate.v1', 'profile': PROFILE, 'reference': reference,
                    'image': candidate, 'docker': context(),
                    'upgrade_helper_sha256': digest(local.HERE / 'portable-upgrade-site.py'),
                    'compose_sha256': digest(local.HERE / 'compose.portable.yml'),
                    'created_at': datetime.now(timezone.utc).isoformat()})
    print(f'Candidate receipt: {receipt}')
    print(f'Build SHA-256: {build}')
    return receipt


def candidate_receipt(local, path):
    path = Path(path).resolve()
    candidate = json.loads(path.read_text(encoding='utf-8'))
    if candidate.get('schema') != 'cipher.local-candidate.v1' or candidate.get('profile') != PROFILE:
        raise local.LocalError('An integration candidate receipt is required.')
    expected = candidate['image']
    if candidate.get('upgrade_helper_sha256') != digest(local.HERE / 'portable-upgrade-site.py'):
        raise local.LocalError('The offline helper differs from the built candidate receipt.')
    if candidate.get('compose_sha256') != digest(local.HERE / 'compose.portable.yml'):
        raise local.LocalError('The Compose configuration differs from the candidate receipt.')
    if candidate.get('reference') != 'cipher-local:integration-' + expected['build_id']:
        raise local.LocalError('Only the unique integration source tag is accepted.')
    if image(local, candidate['reference']) != expected or image(local, expected['id']) != expected or context() != candidate['docker']:
        raise local.LocalError('Candidate image/tag or Docker daemon/context changed.')
    return path, candidate


def runtime_identity(local):
    identifier = local.compose(PROFILE, 'ps', '--all', '--quiet', 'runtime', capture=True).stdout.strip()
    if not re.fullmatch(r'[a-f0-9]{12,64}', identifier):
        raise local.LocalError('Exactly one installed integration runtime is required.')
    runtime = json.loads(docker('container', 'inspect', identifier))[0]
    labels = runtime.get('Config', {}).get('Labels') or {}
    if labels.get('com.docker.compose.project') != 'cipher-integration' or labels.get('com.docker.compose.service') != 'runtime':
        raise local.LocalError('The selected runtime is outside the integration namespace.')
    mounts = sorted(({'destination': m['Destination'], 'name': m.get('Name'), 'source': m['Source']}
                     for m in runtime['Mounts']), key=lambda item: item['destination'])
    expected = {'/home/frappe/frappe-bench/sites': 'cipher-integration_sites',
                '/home/frappe/frappe-bench/logs': 'cipher-integration_logs'}
    if {m['destination']: m['name'] for m in mounts} != expected:
        raise local.LocalError('Integration runtime volumes do not match the fixed namespace.')
    return {'container': runtime['Id'], 'image': runtime['Image'], 'mounts': mounts}


def oneoff(local, image_id, *command):
    return local.compose(PROFILE, 'run', '--rm', '--no-deps', '--entrypoint', command[0],
                         'runtime', *command[1:], capture=True, image=image_id).stdout


def site(local, state, action, *, old=False):
    source = (local.HERE / 'portable-upgrade-site.py').read_text(encoding='utf-8')
    return json.loads(oneoff(local, state['previous']['id'] if old else state['candidate']['id'],
                            PYTHON, '-c', source, action, state['id'], state['previous']['build_id'],
                            state['candidate']['build_id']).strip())


def stopped(local):
    local.compose(PROFILE, 'stop', '--timeout', '30', 'runtime')
    if local.compose(PROFILE, 'ps', '--status', 'running', '--quiet', 'runtime', capture=True).stdout.strip():
        raise local.LocalError('The integration runtime did not stop; no migration is permitted.')
    if docker('ps', '--filter', 'label=com.docker.compose.project=cipher-integration', '--filter',
              'label=com.docker.compose.service=runtime', '--format', '{{.ID}}'):
        raise local.LocalError('An integration one-off runtime is still running; wait for it to finish and reconcile before resuming.')


def dependencies(local):
    # This also permits a profile whose ordinary stop command stopped its DB.
    # Never start the serving runtime in an upgrade/recovery preparation step.
    local.compose(PROFILE, 'up', '--detach', '--no-build', '--wait', '--wait-timeout', '120', 'db', 'redis')


def export_backup(local, state, directory):
    result = site(local, state, 'backup', old=True)
    prefix = result['prefix']
    if not local.PREFIX.fullmatch(prefix):
        raise local.LocalError('The offline backup returned an invalid prefix.')
    target = directory / 'backup'
    local.private_directory(target)
    for name, expected in result['sha256'].items():
        if name not in {prefix + '-' + suffix for suffix in local.SUFFIXES}:
            raise local.LocalError('Unexpected native backup filename.')
        output = target / name
        if output.exists():
            if output.is_symlink() or digest(output) != expected:
                raise local.LocalError('The retained backup bytes changed; refusing overwrite.')
        else:
            local.compose(PROFILE, 'cp', 'runtime:/home/frappe/frappe-bench/sites/cipher.localhost/private/backups/' + name, str(output))
            output.chmod(0o600)
            if digest(output) != expected:
                raise local.LocalError('Exported native backup checksum mismatch.')
    manifest = {'schema': 'cipher.local-backup.v1', 'prefix': prefix, 'source_profile': PROFILE,
                'build_id': state['previous']['build_id'], 'image_reference': state['recovery_tag'],
                'sha256': result['sha256'], 'restore_policy': 'isolated site; scheduler paused; execution quarantined'}
    manifest_path = target / 'manifest.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise local.LocalError('The original backup manifest changed.')
    if not manifest_path.exists():
        write(manifest_path, manifest)
    local.checked_backup(target)
    return {'directory': str(target), 'manifest_sha256': digest(manifest_path)}


def upgrade(local, receipt, acknowledge, *, resume=False):
    receipt, candidate = candidate_receipt(local, receipt)
    if acknowledge != candidate['image']['build_id']:
        raise local.LocalError('Acknowledge the exact candidate build SHA-256.')
    directory = local.environment_path(PROFILE).parent / 'upgrades' / acknowledge
    state_path = directory / 'upgrade.json'
    environment = local.environment_path(PROFILE)
    source_hash = digest(local.HERE / 'portable-upgrade-site.py')
    if state_path.exists():
        if not resume:
            raise local.LocalError('This upgrade already has a journal. Use the exact candidate and --resume.')
        state = json.loads(state_path.read_text())
        if state.get('schema') != 'cipher.local-upgrade.v1' or state.get('stage') not in {
                'prepared', 'backup_complete', 'migration_intent', 'migrated', 'qualified', 'published', 'complete'}:
            raise local.LocalError('Unsupported upgrade journal or stage; retain it for reconciliation.')
        check_active(local, state, state_path)
        if state['candidate_receipt_sha256'] != digest(receipt) or state['helper_sha256'] != source_hash or state['docker'] != context():
            raise local.LocalError('Upgrade source/receipt or Docker identity changed; reconcile before resuming.')
        if state['candidate'] != candidate['image'] or image(local, state['previous']['id']) != state['previous'] or image(local, state['recovery_tag']) != state['previous']:
            raise local.LocalError('The retained image identities changed.')
        if state['stage'] == 'complete':
            active(local).unlink(missing_ok=True)
            print(f'Upgrade stages already complete: {state_path}. Start integration and qualify native/browser behavior separately.')
            return state
        original = directory / 'environment.original'
        if digest(original) != state['environment_sha256'] or digest(environment) not in (state['environment_sha256'], state.get('published_environment_sha256')):
            raise local.LocalError('The retained or current environment changed during upgrade.')
        if runtime_identity(local) != state['runtime']:
            raise local.LocalError('The installed integration container/volumes changed during upgrade.')
        if state['compose_sha256'] != digest(local.HERE / 'compose.portable.yml'):
            raise local.LocalError('The Compose configuration changed during upgrade.')
    else:
        if resume or active(local).exists():
            raise local.LocalError('No matching resumable upgrade, or a different upgrade is pending.')
        runtime = runtime_identity(local)
        previous = image(local, runtime['image'])
        if image(local, local.settings(PROFILE)['CIPHER_IMAGE']) != previous or previous == candidate['image']:
            raise local.LocalError('The selected old image moved, or this candidate is already installed.')
        dependencies(local)
        local.private_directory(directory)
        original = directory / 'environment.original'
        if original.exists() and digest(original) != digest(environment):
            raise local.LocalError('An interrupted preparation retained a different environment.')
        if not original.exists():
            with original.open('xb') as stream:
                stream.write(environment.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
        original.chmod(0o600)
        state = {'schema': 'cipher.local-upgrade.v1', 'id': uuid.uuid4().hex, 'stage': 'prepared',
                 'candidate_receipt_sha256': digest(receipt), 'candidate': candidate['image'], 'previous': previous,
                 'environment_sha256': digest(environment), 'helper_sha256': source_hash, 'runtime': runtime,
                 'compose_sha256': digest(local.HERE / 'compose.portable.yml'),
                 'docker': context(), 'created_at': datetime.now(timezone.utc).isoformat()}
        state['recovery_tag'] = 'cipher-local:recovery-' + state['id']
        docker('tag', previous['id'], state['recovery_tag'])
        write(state_path, state)
        write(active(local), {'journal': str(state_path), 'id': state['id']})
    # A failed or interrupted command leaves services stopped and startup held.
    dependencies(local)
    write(active(local), {'journal': str(state_path), 'id': state['id']})
    stopped(local)
    if state['stage'] == 'prepared':
        snapshot_path = directory / 'runtime-original.secret.json'
        if not snapshot_path.exists():
            write(snapshot_path, site(local, state, 'snapshot', old=True))
        if state.get('snapshot_sha256') not in (None, digest(snapshot_path)):
            raise local.LocalError('The original configuration snapshot changed.')
        state['snapshot_sha256'] = digest(snapshot_path)
        write(state_path, state)
        site(local, state, 'prepare', old=True)
        state['backup'] = export_backup(local, state, directory)
        state['stage'] = 'backup_complete'
        write(state_path, state)
    backup = state['backup']
    local.checked_backup(backup['directory'])
    if digest(Path(backup['directory']) / 'manifest.json') != backup['manifest_sha256'] or digest(directory / 'runtime-original.secret.json') != state['snapshot_sha256']:
        raise local.LocalError('The retained recovery manifest/configuration changed.')
    if state['stage'] in ('backup_complete', 'migration_intent'):
        state['stage'] = 'migration_intent'
        write(state_path, state)
        site(local, state, 'migrate')
        state['stage'] = 'migrated'
        write(state_path, state)
    if state['stage'] == 'migrated':
        state['readback'] = site(local, state, 'verify')
        state['stage'] = 'qualified'
        write(state_path, state)
    if state['stage'] == 'qualified':
        state['readback'] = site(local, state, 'publish')
        original = (directory / 'environment.original').read_text(encoding='utf-8')
        replacement = re.sub(r'(?m)^CIPHER_IMAGE=.*$', 'CIPHER_IMAGE=' + state['candidate']['id'], original)
        pending = environment.with_suffix('.upgrade-pending')
        pending.write_text(replacement, encoding='utf-8', newline='\n')
        pending.chmod(0o600)
        state['published_environment_sha256'] = digest(pending)
        write(state_path, state)  # Permit resuming the environment rename window.
        pending.replace(environment)
        state['stage'] = 'published'
        write(state_path, state)
    if state['stage'] == 'published':
        site(local, state, 'release')
        state['stage'] = 'complete'
        state['completed_at'] = datetime.now(timezone.utc).isoformat()
        write(state_path, state)
    active(local).unlink(missing_ok=True)
    print(f'Offline upgrade stages complete: {state_path}')
    print('Integration remains stopped. Start it explicitly; native/browser feature acceptance is separate.')
    return state


def restore_upgrade(local, receipt):
    receipt, candidate = candidate_receipt(local, receipt)
    directory = local.environment_path(PROFILE).parent / 'upgrades' / candidate['image']['build_id']
    state_path = directory / 'upgrade.json'
    state = json.loads(state_path.read_text())
    check_active(local, state, state_path)
    if state['candidate_receipt_sha256'] != digest(receipt) or state['docker'] != context() or image(local, state['recovery_tag']) != state['previous']:
        raise local.LocalError('Recovery source/image or Docker identity changed.')
    if digest(directory / 'environment.original') != state['environment_sha256'] or digest(local.environment_path(PROFILE)) not in (state['environment_sha256'], state.get('published_environment_sha256')):
        raise local.LocalError('Recovery credentials/environment changed; reconcile before restoring.')
    if state['compose_sha256'] != digest(local.HERE / 'compose.portable.yml'):
        raise local.LocalError('Recovery Compose configuration changed.')
    current_runtime = runtime_identity(local)
    if current_runtime['mounts'] != state['runtime']['mounts']:
        raise local.LocalError('Recovery runtime volumes changed.')
    bundle, manifest = local.checked_backup(state['backup']['directory'])
    if digest(bundle / 'manifest.json') != state['backup']['manifest_sha256']:
        raise local.LocalError('The original backup manifest changed.')
    dependencies(local)
    stopped(local)
    target = 'cipher-restore-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S') + '.localhost'
    # Import the independently retained host bundle even if migration removed
    # its native copies. Staging is new, private, and confined to this volume.
    staging = '/home/frappe/frappe-bench/sites/cipher.localhost/private/.cipher-upgrade-import-' + uuid.uuid4().hex
    owner = json.loads(oneoff(local, state['previous']['id'], PYTHON, '-c',
        "import os,json; print(json.dumps([os.getuid(),os.getgid()]))"))
    if len(owner) != 2 or any(type(value) is not int or value < 0 or value >= 2 ** 32 - 1 for value in owner):
        raise local.LocalError('Invalid original-image numeric ownership identifiers.')
    oneoff(local, state['previous']['id'], PYTHON, '-c',
           "from pathlib import Path; import sys; Path(sys.argv[1]).mkdir(mode=0o700)", staging)
    for name in sorted(manifest['sha256']):
        local.compose(PROFILE, 'cp', str(bundle / name), 'runtime:' + staging + '/' + name)
    local.compose(PROFILE, 'run', '--rm', '--no-deps', '--user', 'root', '--entrypoint', 'chown',
                  'runtime', '-R', ':'.join(str(value) for value in owner), staging, image=state['previous']['id'])
    publish = """import hashlib,json,shutil,sys
from pathlib import Path
source=Path(sys.argv[1]); hashes=json.loads(sys.argv[2]); target=source.parent/'backups'
target.mkdir(mode=0o700,exist_ok=True)
for name,expected in hashes.items():
 p=source/name; dest=target/name
 if hashlib.sha256(p.read_bytes()).hexdigest()!=expected: raise ValueError('Imported backup checksum mismatch')
 if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest()!=expected: raise ValueError('Native backup filename collision; refusing overwrite')
for name in hashes:
 dest=target/name
 if not dest.exists():
  with dest.open('xb') as out, (source/name).open('rb') as inp: shutil.copyfileobj(inp,out)
  dest.chmod(0o600)
shutil.rmtree(source)
"""
    oneoff(local, state['previous']['id'], PYTHON, '-c', publish, staging, json.dumps(manifest['sha256']))
    local.compose(PROFILE, 'run', '--rm', '--no-deps', '-e', 'CIPHER_RESTORE_SITE=' + target,
                  '--entrypoint', 'bash', 'runtime', '/opt/cipher/operations/restore-synthetic.sh', manifest['prefix'],
                  image=state['previous']['id'])
    source = (local.HERE / 'portable-recovery.py').read_text(encoding='utf-8')
    oneoff(local, state['previous']['id'], PYTHON, '-c', source, target,
           '/home/frappe/frappe-bench/sites/cipher.localhost/private/backups/' + manifest['prefix'] + '-site_config_backup.json')
    receipt_path = directory / ('restore-' + target + '.json')
    write(receipt_path, {'schema': 'cipher.local-upgrade-restore.v1', 'site': target,
                         'image': state['previous'], 'backup_manifest_sha256': state['backup']['manifest_sha256'],
                         'scheduler_paused': True, 'execution_quarantined': True})
    print(f'Restored only into {target}; active integration remains stopped and its upgrade hold is unchanged.')
    print(f'Isolated restore receipt: {receipt_path}. Authenticate and verify original saved records/bytes separately.')
