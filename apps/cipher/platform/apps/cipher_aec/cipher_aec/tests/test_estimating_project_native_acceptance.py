"""Focused universal native-master privacy proof on an isolated real Project.

Reuses the root-provisioned Project-only identity; never changes its Company
rights, original control Project, passwords or Auth. Run after QA releases its
shared native-role mutation window. Every temporary permission is restored.
"""
from copy import deepcopy
import base64
import hashlib
from uuid import uuid4


def run_project_native_acceptance(private_manifest):
    import frappe
    from frappe.permissions import update_permission_property
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import PROJECT_ABILITIES, trusted_write, current_actor, duty_rows
    from cipher_aec.install import _grant
    from cipher_aec.tests.test_company_chain_acceptance import _load_fixture, NativeCompanyRPC
    fixture = _load_fixture(private_manifest)
    company, marker = fixture["other_company"], uuid4().hex[:12]
    user = fixture["users"]["project_only"]["user"]
    person = fixture["users"]["project_only"]["person"]
    role = fixture["native_role"]
    if not role.startswith("Company chain native read "):
        raise RuntimeError("Only the root-owned fixture native role may change")
    with trusted_write():
        project = frappe.get_doc({"doctype": "Project", "company": company, "project_name": "EST native parity isolated " + marker, "status": "Open"}).insert(ignore_permissions=True)
        for subject in (person, current_actor().person_id):
            for ability in ("project.read", "document.read", "document.write", "estimate.read", "estimate.write"):
                assert ability in PROJECT_ABILITIES
                _grant(subject, company, project.name, ability)
    frappe.db.commit()
    rpc = NativeCompanyRPC(fixture)
    calls, checks, changed = [], [], []
    doc_api, est_api = "cipher_aec.documents.api.", "cipher_aec.estimating.api."
    def invoke(method, payload, expected=()):
        return rpc.invoke(method, {"company": company, **({"project": project.name} if method.startswith(est_api) or method.endswith("upload_document") else {}), **payload}, expected_codes=expected)
    def command(method, payload):
        values = {"operation_id": str(uuid4()), **payload}
        return values, invoke(method, values)
    def permission(doctype, active):
        frappe.set_user("Administrator")
        for key in ("read", "select"):
            update_permission_property(doctype, role, 0, key, active)
        frappe.clear_cache(user=user)
        frappe.db.commit()
        rpc.login("project_only")
        name = fixture["native_unit"] if doctype == "UOM" else "USD"
        assert bool(frappe.has_permission(doctype, "read", doc=frappe.get_doc(doctype, name), user=user)) == bool(active)
    try:
        rpc.login("project_only")
        content = ("Explicit isolated Project native-master privacy fixture " + marker).encode()
        _, uploaded = command(doc_api + "upload_document", {"title": "Project parity source " + marker, "filename": "project-parity.txt", "content_base64": base64.b64encode(content).decode(), "sha256": hashlib.sha256(content).hexdigest(), "byte_length": len(content)})
        citation = invoke(doc_api + "get_citation", {"revision_id": uploaded["revision"]["id"], "page": 1})
        cite = {key: citation[key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")}
        unit_id = fixture["qualified_unit"]["id"]
        rate = {"title": "Project privacy material " + marker, "cost_type": "material", "unit_id": unit_id, "rate_amount": "12.34", "rate_precision": 2, "currency": "USD", "quote_reference": "PROJECT-NATIVE-" + marker, "quote_date": "2026-10-01", "expiry_date": "2026-10-31", "geography": "Explicit synthetic", "inclusions": "Explicit authored test only", "exclusions": "", "freight_tax_assumptions": "None in this fixture", "permission_basis": "Authored synthetic content", "source_citations": [cite], "item": fixture["native"]["b"]["item"]}
        _, rate_value = command(est_api + "create_rate", {"rate": rate})
        assembly_args, assembly_value = command(est_api + "create_assembly", {"title": "Project native assembly " + marker, "basis_unit_id": unit_id,
            "components": [{"line_id": str(uuid4()), "rate_source_id": rate_value["rate_source"]["id"], "kind": "material", "work_quantity": {"amount": "1", "unit_id": unit_id, "precision": 6}, "resource_quantity": {"amount": "1", "unit_id": unit_id, "precision": 6}, "material_factor": "1", "waste_fraction": "0"}],
            "author_basis": "Explicit native currency/privacy regression", "conversion_ids": []})
        _, estimate = command(est_api + "create_estimate", {"title": "Project parity estimate " + marker, "currency": "USD", "pricing_date": "2026-10-15"})
        line = {"line_id": str(uuid4()), "description": "Explicit Project authored quantity", "quantity": {"amount": "2.500000", "unit_id": unit_id, "precision": 6}, "cost_code": "PARITY-01", "notes": "No geometry claim", "alternate": "", "included": True, "rate_source_id": rate_value["rate_source"]["id"], "material_factor": "1", "waste_fraction": "0"}
        args, calculated = command(est_api + "calculate_revision", {"estimate_id": estimate["estimate"]["id"], "expected_revision": None, "lines": [line], "adjustments": [], "conversion_ids": [], "basis_description": "Exact Project source permission proof", "basis_citations": [cite]})
        assert calculated["revision"]["total"]["amount"] == "30.85"
        assert all("scope_type" not in calculated[key] for key in ("estimate", "revision", "calculation"))
        count = frappe.db.count("Cipher Calculation Snapshot", {"project": project.name})
        for doctype in ("UOM", "Currency"):
            permission(doctype, 0)
            changed.append(doctype)
            if doctype == "UOM":
                listed = invoke(est_api + "list_units", {})
                assert listed["items"] == []
                from cipher_aec.estimating.service import authorize_receipt
                try:
                    authorize_receipt(current_actor(), company, project.name, {"unit": fixture["qualified_unit"]})
                    raise AssertionError("Returned unit receipt authorization ignored native UOM rights")
                except DomainError as error:
                    assert error.code == "not_found"
                    frappe.db.rollback()
            denied = []
            for kind, record_id in (("rate", rate_value["rate_source"]["id"]), ("assembly", assembly_value["assembly_revision"]["id"]), ("snapshot", calculated["calculation"]["id"]), ("revision", calculated["revision"]["id"]), ("line", calculated["revision"]["line_record_ids"][0])):
                result = invoke(est_api + "get_record", {"kind": kind, "record_id": record_id}, expected={"not_found"})
                assert result["error_code"] == "not_found"
                denied.append(kind)
            invoke(est_api + "create_assembly", assembly_args, expected={"not_found"})
            invoke(est_api + "calculate_revision", args, expected={"not_found"})
            invoke(est_api + "create_rate", {"operation_id": str(uuid4()), "rate": rate}, expected={"not_found"})
            assert frappe.db.count("Cipher Calculation Snapshot", {"project": project.name}) == count
            checks.append({"master": doctype, "actual_native_read_denied": True, "retained_kinds_denied": denied, "completed_receipt_denied": True, "assembly_receipt_denied": True, "selected_new_rate_denied": True, "returned_unit_receipt_callback_denied": doctype == "UOM", "no_new_snapshot": True})
            permission(doctype, 1)
            changed.remove(doctype)
            assembly_replay = invoke(est_api + "create_assembly", assembly_args)
            assert assembly_replay["operation"]["replayed"] and assembly_replay["assembly_revision"] == assembly_value["assembly_revision"]
            replay = invoke(est_api + "calculate_revision", args)
            assert replay["operation"]["replayed"] and replay["calculation"] == calculated["calculation"]
        return {"status": "passed", "qualification": "real-Frappe-native-rights-Project-fixture-with-explicit-synthetic-Sessions-not-HTTP", "project": project.name, "company": company,
                "user": user, "project_scope_payload_unchanged": True, "revision_id": calculated["revision"]["id"], "snapshot_id": calculated["calculation"]["id"],
                "original_operation_id": args["operation_id"], "checks": checks, "calls": rpc.calls,
                "temporary_native_permissions_restored": True, "live_model_qualified": False, "external_provider_qualified": False}
    finally:
        frappe.db.rollback()
        frappe.set_user("Administrator")
        for doctype in changed:
            for key in ("read", "select"):
                update_permission_property(doctype, role, 0, key, 1)
        frappe.clear_cache(user=user)
        frappe.db.commit()
        rpc.close()
