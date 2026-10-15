"""Test package setup: keep every temporary workspace under one disposable root.

Tests create file-backed SQLite workspaces with ``tempfile.mkdtemp()`` to exercise
restore and write-authority behavior.  Pointing ``tempfile.tempdir`` at a
per-run root lets that process remove its own files at exit (best effort, since
Windows keeps open SQLite files locked). Another process's root may still be
active regardless of its age, so importing tests never removes a peer's files.
"""
import atexit
import gc
import shutil
import tempfile

_PREFIX = "cipher-tests-"
_base = tempfile.gettempdir()

_root = tempfile.mkdtemp(prefix=_PREFIX)
tempfile.tempdir = _root


@atexit.register
def _cleanup() -> None:
    gc.collect()  # drop unreferenced SQLite connections so their files unlock
    shutil.rmtree(_root, ignore_errors=True)
