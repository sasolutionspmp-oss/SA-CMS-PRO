"""Run the frozen host suite against pinned worker/store bytes, without reset."""
import importlib.abc
import importlib.util
import os
from pathlib import Path
import runpy
import subprocess
import sys

BASE = 'a3577803e09e72b9af22178bdd9c4d1225536485'
ROOT = Path(__file__).resolve().parent
CHECKOUT = Path(os.environ.get('CIPHER_SEMANTIC_SOURCE_ROOT', str(ROOT / 'workspace')))
PREFIX = 'apps/cipher/platform/apps/cipher_aec/cipher_aec/semantic_index/'


class PinnedSource(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    names = {'cipher_aec.semantic_index.store': PREFIX + 'store.py',
             'cipher_aec.semantic_index.worker': PREFIX + 'worker.py'}

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.names:
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path = self.names[module.__name__]
        source = subprocess.check_output(['git', 'show', BASE + ':' + path], cwd=CHECKOUT)
        exec(compile(source, BASE + ':' + module.__name__, 'exec'), module.__dict__)


finder = PinnedSource()
sys.meta_path.insert(0, finder)
try:
    runpy.run_path(str(ROOT / 'test_worker_transactions_host.py'), run_name='__main__')
finally:
    sys.meta_path.remove(finder)
