#!/usr/bin/env python3
"""Fixed-site offline upgrade operations; never starts services or seeds fixtures."""
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time

BENCH = Path('/home/frappe/frappe-bench')
SITE = 'cipher.localhost'
SUFFIXES = ('database.sql.gz', 'files.tgz', 'private-files.tgz', 'site_config_backup.json')


def atomic(path, value):
    pending = path.with_suffix('.upgrade-pending')
    with pending.open('w') as stream:
        pending.chmod(0o600)
        stream.write(json.dumps(value, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def bench(*arguments):
    return subprocess.run(('bench', '--site', SITE, *arguments), cwd=BENCH,
                          check=True, text=True, stdout=subprocess.PIPE).stdout


def contracts():
    installed = json.loads(bench('execute', 'frappe.get_installed_apps').strip())
    if not {'frappe', 'erpnext', 'cipher_aec'}.issubset(installed):
        raise ValueError('Required installed applications are missing.')
    metadata = json.loads(bench('execute', 'cipher_aec.projects.install.metadata_status').strip())
    if metadata.get('schema') != 'cipher.task-controls.metadata.v1' or metadata.get('ready') is not True:
        raise ValueError('The installed Task contract is not ready.')
    return {'installed_apps': installed, 'task_metadata': metadata}


def main(action, identity, previous, candidate):
    # A disconnected Docker client can leave its one-off container running.
    # Serialize native operations independently of the host process's OS lock.
    import fcntl
    with (BENCH / 'sites/.cipher-portable-upgrade.lock').open('a+b') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return perform(action, identity, previous, candidate)


def perform(action, identity, previous, candidate):
    if os.environ.get('CIPHER_SYNTHETIC') != '1' or os.environ.get('CIPHER_SITE') != SITE:
        raise ValueError('Only the fixed synthetic site is accepted.')
    if not re.fullmatch(r'[a-f0-9]{32}', identity) or any(not re.fullmatch(r'[a-f0-9]{64}', item) for item in (previous, candidate)):
        raise ValueError('Invalid upgrade identity.')
    site = BENCH / 'sites' / SITE
    marker = site / '.cipher-portable.json'
    hold = site / '.cipher-portable-upgrade.json'
    old_marker = {'schema': 1, 'build_id': previous, 'site': SITE}
    new_marker = {'schema': 1, 'build_id': candidate, 'site': SITE}
    expected = {'schema': 'cipher.local-upgrade-hold.v1', 'id': identity,
                'previous_build': previous, 'candidate_build': candidate}
    current = json.loads(marker.read_text())
    config = json.loads((site / 'site_config.json').read_text())
    if config.get('cipher_site_mode') != 'synthetic' or config.get('cipher_synthetic') is not True:
        raise ValueError('The installed site is not explicitly synthetic.')
    if action == 'snapshot':
        if current != old_marker:
            raise ValueError('The original installed build marker does not match.')
        return {'marker': marker.read_text(), 'site_config': (site / 'site_config.json').read_text(),
                'common_config': (BENCH / 'sites/common_site_config.json').read_text()}
    if action == 'prepare':
        if current != old_marker:
            raise ValueError('Cannot prepare a different installed build.')
        if hold.exists() and json.loads(hold.read_text()) != expected:
            raise ValueError('A different upgrade owns this site.')
        atomic(hold, expected)
        return {'held': True}
    if action == 'release' and not hold.exists() and current == new_marker:
        contracts()
        return {'released': True}
    if not hold.exists() or json.loads(hold.read_text()) != expected or current not in (old_marker, new_marker):
        raise ValueError('The persistent upgrade interlock or build marker changed.')
    if action == 'backup':
        if current != old_marker or os.environ.get('CIPHER_BUILD_ID') != previous:
            raise ValueError('Backup requires the original image before migration.')
        backups = site / 'private/backups'
        retained = site / ('.cipher-upgrade-backup-' + identity + '.json')
        intent = site / ('.cipher-upgrade-backup-intent-' + identity + '.json')
        names = {suffix for suffix in SUFFIXES}
        if retained.exists():
            result = json.loads(retained.read_text())
            if set(result['sha256']) != {result['prefix'] + '-' + suffix for suffix in names} or not all(hashlib.sha256((backups / name).read_bytes()).hexdigest() == value for name, value in result['sha256'].items()):
                raise ValueError('The original offline backup bytes changed.')
            return result
        if intent.exists():
            before = set(json.loads(intent.read_text())['before'])
        else:
            before = {p.name for p in backups.iterdir()} if backups.exists() else set()
            atomic(intent, {'before': sorted(before)})
            # Native names have second precision. Avoid overwriting a backup
            # created in this second; journal before the supported invocation.
            time.sleep(1.1)
            subprocess.run(('bash', '/opt/cipher/operations/backup-synthetic.sh'), cwd=BENCH,
                           check=True, text=True, stdout=subprocess.PIPE)
        # If interrupted after the native invocation, reconcile its exact new
        # files. Never run another backup against an unresolved intent.
        prefixes = [p.name[:-len('-site_config_backup.json')] for p in backups.glob('*-site_config_backup.json') if p.name not in before]
        if len(prefixes) != 1 or not all((backups / (prefixes[0] + '-' + suffix)).is_file() for suffix in SUFFIXES):
            raise ValueError('Backup intent lacks one fresh complete set; retain all files and reconcile offline before proceeding.')
        hashes = {prefixes[0] + '-' + suffix: hashlib.sha256((backups / (prefixes[0] + '-' + suffix)).read_bytes()).hexdigest() for suffix in SUFFIXES}
        result = {'prefix': prefixes[0], 'build_id': previous, 'sha256': hashes}
        atomic(retained, result)
        return result
    if os.environ.get('CIPHER_BUILD_ID') != candidate:
        raise ValueError('Migration and readback require the exact candidate image.')
    if action == 'migrate':
        if current != old_marker:
            raise ValueError('A published build cannot be migrated through this stage.')
        bench('migrate')
        return {'migrated': True}
    if action in ('verify', 'publish'):
        result = contracts()  # Every readback is in fresh supported bench processes.
        if action == 'publish':
            atomic(marker, new_marker)
        return result
    if action == 'release':
        if current != new_marker:
            raise ValueError('Release requires the qualified candidate marker.')
        contracts()
        hold.unlink()
        return {'released': True}
    raise ValueError('Unsupported offline upgrade operation.')


if __name__ == '__main__':
    print(json.dumps(main(*sys.argv[1:]), sort_keys=True))
