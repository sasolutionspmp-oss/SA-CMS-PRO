"""Cold required-module loading and exact additive owner billing registration."""
import subprocess
import sys
import unittest


class OwnerBillingLoadingTests(unittest.TestCase):
    def test_cold_owner_import_changes_no_catalog_then_actual_required_loader_preserves73(self):
        script = r'''
from apps.cipher.core.db import SCHEMA_CATALOG
from apps.cipher.core.ids import hash_json
before = hash_json(SCHEMA_CATALOG)
from apps.cipher.domain import owner_billing
assert hash_json(SCHEMA_CATALOG) == before
assert owner_billing.DEFER_SCHEMA_REGISTRATION is True
assert owner_billing.Plugin.GOVERNOR is True
from apps.cipher.service import Cipher, PLUGIN_MODULES
assert PLUGIN_MODULES.count("apps.cipher.domain.owner_billing") == 1
assert PLUGIN_MODULES.index("apps.cipher.domain.owner_billing") > PLUGIN_MODULES.index("apps.cipher.domain.commercial")
assert hash_json(SCHEMA_CATALOG[:73]) == "f6396239c845928a66c8ba93c6563641fdb75555914906c8aff71a531d64ab69"
assert SCHEMA_CATALOG[73][1] == "owner_billing_sources_and_posting"
assert SCHEMA_CATALOG[74][1] == "ar_practice_action_receipts"
assert hash_json(SCHEMA_CATALOG[:75]) == "0b65915a8926593f21dbd2881166fb1ddff2684aac6ccdf955750fa5c5dac479"
c = Cipher()
assert c.plugin("owner_billing").state() == {"bases": [], "sources": [], "integrity": []}
assert c.db.scalar("SELECT count(*) FROM schema_version") == len(SCHEMA_CATALOG)
project = c.create_project(name="Synthetic empty owner source", entity="Synthetic entity", budget="1")
assert c.project_state(project["id"])["owner_billing"]["sources"] == []
c.db.close()
'''
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
