#!/usr/bin/env python3
"""Initialize one synthetic persistent site, then supervise the local services."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

BENCH = Path('/home/frappe/frappe-bench')
DEPLOYMENT = Path('/opt/cipher/deployment')
SITE = 'cipher.localhost'
MARKER = BENCH / 'sites' / SITE / '.cipher-portable.json'


def run(*command, capture=False):
    return subprocess.run(command, cwd=BENCH, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None)


def initialize():
    if os.environ.get('CIPHER_SYNTHETIC') != '1' or os.environ.get('CIPHER_SITE') != SITE:
        raise RuntimeError('This image accepts only its fixed synthetic local site.')
    build = os.environ.get('CIPHER_BUILD_ID', 'unrecorded')
    if build == 'unrecorded':
        raise RuntimeError('Build with cipher-local.py so the image has a source identity.')
    if (MARKER.parent / '.cipher-portable-upgrade.json').exists():
        raise RuntimeError('An explicit upgrade is pending. Resume it offline before starting services.')
    if MARKER.exists():
        marker = json.loads(MARKER.read_text())
        if marker != {'schema': 1, 'build_id': build, 'site': SITE}:
            raise RuntimeError('The persistent site belongs to a different build. Back up and qualify an explicit upgrade before reuse.')
    else:
        run('bash', str(DEPLOYMENT / 'bootstrap-site.sh'))
        # The package and its dependencies are already installed in the image.
        # Read the actual installed-app list to resume an interrupted first boot.
        result = run('bench', '--site', SITE, 'execute', 'frappe.get_installed_apps', capture=True)
        installed = json.loads(result.stdout.strip())
        if 'cipher_aec' not in installed:
            run('bench', '--site', SITE, 'install-app', 'cipher_aec')
        run('bench', '--site', SITE, 'migrate')
        run('bench', '--site', SITE, 'set-config', 'developer_mode', '0', '--parse')
        run('bench', '--site', SITE, 'execute', 'cipher_aec.trial.seed_local_trial')
        temporary = MARKER.with_suffix('.pending')
        with temporary.open('w') as stream:
            temporary.chmod(0o600)
            stream.write(json.dumps({'schema': 1, 'build_id': build, 'site': SITE}, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(MARKER)
    # These supported operator helpers preserve unrelated settings. No business
    # fixture is reseeded and no password/duty is reset on a normal restart.
    run('bench', '--site', SITE, 'execute', 'cipher_aec.integrations.distribution_install.configure_queue')
    run('bench', '--site', SITE, 'execute', 'cipher_aec.awards.runtime_install.configure_native_profile')


def main():
    initialize()
    spec = importlib.util.spec_from_file_location('cipher_distribution_supervisor', DEPLOYMENT / 'run-distribution-services.py')
    supervisor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(supervisor)
    commands = (
        ('bash', '/usr/local/bin/start.sh'),
        ('bench', 'worker', '--queue', 'short,default'),
        ('bench', 'worker', '--queue', 'long'),
        (sys.executable, str(DEPLOYMENT / 'run-distribution-services.py')),
        ('bench', 'schedule'),
        ('/home/frappe/.nvm/current/bin/node', 'apps/frappe/socketio.js'),
        ('/usr/sbin/nginx', '-c', str(DEPLOYMENT / 'nginx.dev.conf'), '-g', 'daemon off;'),
    )
    return supervisor.supervise(commands, cwd=BENCH, shutdown_timeout=15)


if __name__ == '__main__':
    raise SystemExit(main())
