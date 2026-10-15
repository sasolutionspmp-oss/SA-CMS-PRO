"""Fresh-process deferred import respects the original schema load order."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import unittest


class CommercialDeferredImportReview(unittest.TestCase):
    def test_deferred_domain_import_cannot_register_forecast_or_other_historical_schema(self):
        source = Path(importlib.import_module("apps.cipher").__file__).resolve().parents[2]
        script = r'''
import ast
import importlib
from pathlib import Path
from apps.cipher.core.approvals import Approvals
from apps.cipher.core.db import SCHEMA_CATALOG
service = Path(importlib.import_module("apps.cipher").__file__).parent / "service.py"
parsed = ast.parse(service.read_text())
modules = next(ast.literal_eval(node.value) for node in parsed.body if isinstance(node, ast.Assign) and any(isinstance(target,ast.Name) and target.id=="PLUGIN_MODULES" for target in node.targets))
for module in modules:
    if module != "apps.cipher.domain.commercial":
        importlib.import_module(module)
before = tuple((version,name,tuple(sql)) for version,name,sql in SCHEMA_CATALOG)
commercial = importlib.import_module("apps.cipher.domain.commercial")
after = tuple((version,name,tuple(sql)) for version,name,sql in SCHEMA_CATALOG)
assert commercial.DEFER_SCHEMA_REGISTRATION is True
assert before == after, "deferred commercial import appended historical schema entries"
'''
        env = {**os.environ, "PYTHONPATH": str(source)}
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, cwd=source)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
