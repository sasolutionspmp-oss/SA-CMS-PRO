"""Test package setup: keep every temporary workspace under one disposable root.

Tests create file-backed SQLite workspaces with ``tempfile.mkdtemp()`` to exercise
restore and write-authority behavior.  Pointing ``tempfile.tempdir`` at a
per-run root lets us remove them all: at exit (best effort, since Windows keeps
open SQLite files locked) and, reliably, at the start of the next run, which
deletes roots left behind by earlier runs.
"""
import atexit
import gc
import os
import shutil
import tempfile
import time

_PREFIX = "cipher-tests-"
_base = tempfile.gettempdir()

# remove roots from earlier runs (older than a minute, so concurrent runs are left alone)
for _name in os.listdir(_base):
    if _name.startswith(_PREFIX):
        _path = os.path.join(_base, _name)
        try:
            if time.time() - os.path.getmtime(_path) > 60:
                shutil.rmtree(_path, ignore_errors=True)
        except OSError:
            pass

_root = tempfile.mkdtemp(prefix=_PREFIX)
tempfile.tempdir = _root


@atexit.register
def _cleanup() -> None:
    gc.collect()  # drop unreferenced SQLite connections so their files unlock
    shutil.rmtree(_root, ignore_errors=True)
