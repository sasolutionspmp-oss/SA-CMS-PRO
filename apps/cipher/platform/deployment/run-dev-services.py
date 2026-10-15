#!/usr/bin/env python3
"""Co-locate development processes to avoid vfs container copies; fail as a unit."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

BENCH = Path('/home/frappe/frappe-bench')
READY = BENCH / 'sites' / '.cipher-r0-ready'
children = []
stopping = False

def stop(signum=None, frame=None):
    global stopping
    stopping = True
    for child in children:
        if child.poll() is None:
            child.terminate()

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
while not READY.exists() and not stopping:
    time.sleep(1)
if stopping:
    sys.exit(0)
# Editable app metadata is container-local; recreate it when a fresh development
# container starts with an existing persistent site. Dependency versions are pinned.
subprocess.run([str(BENCH / 'env/bin/pip'), 'install', '-e', str(BENCH / 'apps/cipher_aec')], check=True)
# RQ validates named queues against common worker configuration before enqueue.
# Merge only this fixed queue before any worker/web process caches its catalog.
subprocess.run(['bench', '--site', 'cipher.localhost', 'execute',
                'cipher_aec.integrations.distribution_install.configure_queue'], cwd=BENCH, check=True)
commands = [
    ['bash', '/usr/local/bin/start.sh'],
    ['bench', 'worker', '--queue', 'short,default'],
    ['bench', 'worker', '--queue', 'long'],
    [sys.executable, '/opt/cipher/deployment/run-distribution-services.py'],
    ['bench', 'schedule'],
    ['/home/frappe/.nvm/current/bin/node', 'apps/frappe/socketio.js'],
    ['/usr/sbin/nginx', '-c', '/opt/cipher/deployment/nginx.dev.conf', '-g', 'daemon off;'],
]
try:
    for command in commands:
        children.append(subprocess.Popen(command, cwd=BENCH))
    while not stopping:
        if any(child.poll() is not None for child in children):
            raise RuntimeError('A development service exited; stopping the process group.')
        time.sleep(1)
except Exception as exc:
    print(str(exc), file=sys.stderr, flush=True)
    stop()
    exit_code = 1
else:
    exit_code = 0
finally:
    stop()
    deadline = time.monotonic() + 15
    for child in children:
        try:
            child.wait(timeout=max(0.1, deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
sys.exit(exit_code)
