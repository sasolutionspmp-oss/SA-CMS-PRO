"""The native Select must admit exactly registered abilities before any grant."""
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]


class CapabilityMetadataTests(unittest.TestCase):
    def test_native_ability_select_matches_declared_scope_catalog(self):
        constants = {}
        for node in ast.parse((ROOT / "governance/context.py").read_text()).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {"PROJECT_ABILITIES", "COMPANY_ABILITIES"}:
                constants[node.targets[0].id] = set(ast.literal_eval(node.value.args[0]))
        metadata = json.loads((ROOT / "cipher_governance/doctype/cipher_project_duty/cipher_project_duty.json").read_text())
        field = next(field for field in metadata["fields"] if field["fieldname"] == "ability")
        self.assertEqual(set(field["options"].splitlines()), constants["PROJECT_ABILITIES"] | constants["COMPANY_ABILITIES"])
        self.assertIn("commercial.distribute", constants["COMPANY_ABILITIES"])
        self.assertNotIn("commercial.distribute", constants["PROJECT_ABILITIES"])


def run_native_acceptance():
    """Installed Select plus actual scope controller checks; no persisted rows."""
    import frappe
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import assert_synthetic_site, trusted_write, PROJECT_ABILITIES, COMPANY_ABILITIES
    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise RuntimeError("Use the synthetic operator bench context.")
    options = set(frappe.get_meta("Cipher Project Duty", cached=False).get_field("ability").options.splitlines())
    assert options == PROJECT_ABILITIES | COMPANY_ABILITIES
    rows = frappe.db.sql("SELECT name,company FROM tabProject ORDER BY name LIMIT 1")
    if not rows:
        raise RuntimeError("Use the existing seeded qualification site; do not seed from this check.")
    project, company = rows[0]
    person = frappe.db.get_value("Cipher Person", {}, "name")
    checked, denied = [], []
    with trusted_write():
        for scope, supported, other in (("Project", PROJECT_ABILITIES, COMPANY_ABILITIES), ("Company", COMPANY_ABILITIES, PROJECT_ABILITIES)):
            for ability in sorted(supported | other):
                doc = frappe.get_doc({"doctype": "Cipher Project Duty", "person": person, "company": company,
                    "scope_type": scope, "project": project if scope == "Project" else None, "ability": ability, "active": 1})
                doc._validate_selects()
                if ability in supported:
                    doc.run_method("validate")
                    checked.append([scope, ability])
                else:
                    try:
                        doc.run_method("validate")
                    except DomainError as error:
                        assert error.code == "invalid_duty"
                        denied.append([scope, ability])
                    else:
                        raise AssertionError("A cross-scope ability was accepted: " + scope + ":" + ability)
    assert ["Company", "commercial.distribute"] in checked
    assert ["Project", "commercial.distribute"] in denied
    return {"status": "passed", "installed_select_count": len(options), "accepted_scope_pairs": checked,
        "denied_cross_scope_pairs": denied, "persisted_rows": 0}
