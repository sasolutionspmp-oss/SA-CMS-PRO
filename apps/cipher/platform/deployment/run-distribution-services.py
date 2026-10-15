#!/usr/bin/env python3
"""Supervise the fixed development distribution consumer and recovery publisher."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

BENCH = Path('/home/frappe/frappe-bench')
COMMANDS = (
    ('bench', 'worker', '--queue', 'cipher_distribution'),
    ('bench', '--site', 'cipher.localhost', 'execute',
     'cipher_aec.integrations.distribution_recovery.run_forever'),
)


def signal_session(session_id, signum):
    """Include RQ work horses, which create their own group in our session."""
    groups = set()
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            pid = int(entry.name)
            if os.getsid(pid) == session_id:
                groups.add(os.getpgid(pid))
        except ProcessLookupError:
            pass
    for group in groups:
        try:
            os.killpg(group, signum)
        except ProcessLookupError:
            pass


def supervise(commands=COMMANDS, *, cwd=BENCH, shutdown_timeout=10):
    children = []
    stopping = False

    def stop(signum=None, frame=None):
        nonlocal stopping
        stopping = True

    previous = {number: signal.signal(number, stop)
                for number in (signal.SIGTERM, signal.SIGINT)}
    result = 0
    try:
        for command in commands:
            if stopping:
                break
            # Each child owns a separate session, isolating this pair from the
            # web server, native cron and unrelated workers in the container.
            children.append(subprocess.Popen(command, cwd=cwd, start_new_session=True))
        while not stopping:
            if any(child.poll() is not None for child in children):
                raise RuntimeError('A required distribution service exited.')
            time.sleep(0.25)
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        result = 1
    finally:
        # RQ interprets the first TERM as a warm shutdown. Let an active job
        # finish before terminating its separate work-horse group at deadline.
        for child in children:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + shutdown_timeout
        while any(child.poll() is None for child in children) and time.monotonic() < deadline:
            time.sleep(0.05)
        for child in children:
            signal_session(child.pid, signal.SIGKILL)
            child.wait()
        for number, handler in previous.items():
            signal.signal(number, handler)
    return result


if __name__ == '__main__':
    if len(sys.argv) != 1:
        raise SystemExit('This fixed development service accepts no arguments.')
    raise SystemExit(supervise())
