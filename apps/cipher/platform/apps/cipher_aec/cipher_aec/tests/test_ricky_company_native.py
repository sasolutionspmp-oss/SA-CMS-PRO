"""Opt-in ordinary Company Ricky fixture; no no-argument acceptance entrypoint.

SOURCE ONLY until root qualifies the installed synthetic site, isolated queue,
authentic HTTP starts and each runtime slot. This module never creates Sessions,
starts workers, changes queue/configuration, or originates a Ricky start.
"""
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import base64
import hashlib
import math
from pathlib import Path
import json
import secrets
import threading
from uuid import uuid4

from .ricky_company_acceptance_support import (SCHEMA, Journal, manifest, saved_intent, sha, timestamp,
    write_private, verify_read_value, require_projection_coverage, typed_equal, validate_company_reference, fixture_company_reference, declared_case)

RICKY_TABLES = ("Cipher Ricky Run", "Cipher Ricky Step", "Cipher Tool Invocation",
                "Cipher Proposed Change", "Cipher Delegation", "Cipher Run Artifact")
INVENTORY_TABLES = (*RICKY_TABLES, "Project", "Task", "Cipher Command Receipt", "Cipher History Event",
    "Company", "Account", "Currency", "UOM", "Customer", "Customer Group", "Territory", "Opportunity", "Role", "DocPerm",
    "Custom DocPerm", "DocType", "Custom Field", "Property Setter", "Module Def", "User Permission", "User", "Has Role", "DefaultValue", "Cipher Project Duty", "Cipher Person",
    "Cipher Identity Binding", "File", "Cipher Document", "Cipher Document Revision",
    "Cipher Estimate", "Cipher Estimate Revision", "Cipher Calculation Snapshot", "Cipher Rate Source",
    "Cipher Unit Conversion", "Cipher Estimate Line", "Cipher Assembly Revision", "Cipher Estimate Acceptance",
    "Cipher Takeoff Set", "Cipher Takeoff Measurement", "Cipher Calibration", "Cipher Calibration Verification",
    "Cipher Takeoff Line Binding", "Cipher Pursuit", "Cipher Proposal", "Cipher Proposal Revision",
    "Sales Order", "Sales Invoice", "Delivery Note", "Purchase Order", "Purchase Invoice", "Purchase Receipt",
    "Payment Entry", "Journal Entry", "Stock Entry", "Expense Claim", "Timesheet", "Material Request", "GL Entry", "Stock Ledger Entry")
ABILITIES = ("company.read", "ricky.run", "commercial.read", "commercial.write", "document.read",
             "document.write", "estimate.read", "estimate.write")


def _administrator():
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site
    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise RuntimeError("Use an explicit synthetic Administrator fixture context.")


def _load_fixture(path):
    import frappe
    _administrator()
    value = manifest(path)
    base = Path(frappe.get_site_path("private", "cipher-fixtures")).resolve()
    if not Path(path).resolve().is_relative_to(base) or value["site"] != frappe.local.site:
        raise RuntimeError("Use the exact installed private fixture/site.")
    return value


def _fixture(path):
    value = _load_fixture(path)
    if not value["preservation"].get("setup_old_rows_unchanged"):
        raise RuntimeError("Strict setup preservation/attribution must be ready.")
    return value


def _native_scalar(value):
    """Type-preserving native column observation, never a string coercion."""
    kind = type(value)
    if value is None:
        return {"type": "null", "value": None}
    if kind in (str, bool):
        return {"type": kind.__name__, "value": value}
    if kind is int:
        return {"type": "int", "value": str(value)}
    if kind is float:
        if not math.isfinite(value):
            raise ValueError("Nonfinite native inventory value.")
        return {"type": "float", "value": value.hex()}
    if kind is Decimal:
        if not value.is_finite():
            raise ValueError("Nonfinite native Decimal inventory value.")
        return {"type": "decimal", "value": str(value)}
    if kind in (datetime, date, time):
        return {"type": kind.__name__, "value": value.isoformat()}
    if kind is timedelta:
        return {"type": "timedelta", "value": [value.days, value.seconds, value.microseconds]}
    if kind is bytes:
        return {"type": "bytes", "value": value.hex()}
    raise TypeError("Unqualified native inventory scalar: " + kind.__name__)


DUTY_FIELDS = ("name", "company", "person", "scope_type", "project", "ability", "active",
               "valid_from", "valid_until", "scope_key")


def _duty_state(value, ability, row):
    if (not row or row.name != value["duties"][ability] or row.company != value["company"]
            or row.person != value["users"]["author"]["person"] or row.scope_type != "Company"
            or row.project not in (None, "") or row.ability != ability
            or type(row.active) is not int or row.active not in (0, 1)):
        raise AssertionError("Refusing a foreign or changed fixture authority row.")
    return {"active": row.active, "fields": {key: _native_scalar(getattr(row, key)) for key in DUTY_FIELDS}}


def _capture_duty_outage(value, ability, stage, private_manifest):
    import frappe
    original = _duty_state(value, ability, frappe.get_doc("Cipher Project Duty", value["duties"][ability]))
    baseline = value["stages"].get("original_duty_states", {}).get(ability)
    if original["active"] != 1 or not typed_equal(original, baseline):
        raise AssertionError("A meaningful outage requires the exact original active fixture duty.")
    if value["stages"].get(stage, {}).get("status") == "prepared_before_outage":
        raise RuntimeError("An earlier outage requires independent reconciliation; never replace its baseline.")
    value["stages"][stage] = {"status": "prepared_before_outage", "ability": ability,
        "original_duty": original, "at": timestamp()}
    write_private(private_manifest, value)
    return original


def _inventory():
    """Hash every existing row/column in the literal relevant business set."""
    import frappe
    hrms_installed = "hrms" in frappe.get_installed_apps()
    expense_claim_present = bool(frappe.db.exists("DocType", "Expense Claim"))
    result = {"Inventory metadata": {"Expense Claim": {"present": expense_claim_present,
        "owner_app": "hrms", "owner_app_installed": hrms_installed}}}
    if hrms_installed and not expense_claim_present:
        raise RuntimeError("Installed HRMS is missing required ordinary fixture metadata: Expense Claim")
    for table in INVENTORY_TABLES:
        if table == "Expense Claim" and not expense_claim_present:
            result[table] = {}
            continue
        if not frappe.db.exists("DocType", table):
            raise RuntimeError("Missing required ordinary fixture metadata: " + table)
        rows = frappe.db.sql("SELECT * FROM `tab" + table + "` ORDER BY name", as_dict=True)
        result[table] = {row["name"]: {key: sha(_native_scalar(value))
            for key, value in row.items()} for row in rows}
    rows = frappe.db.sql("SELECT doctype,field,value FROM tabSingles WHERE doctype IN "
        "('System Settings','Accounts Settings','Selling Settings','Stock Settings','Global Defaults') ORDER BY doctype,field", as_dict=True)
    result["Singles"] = {row["doctype"] + ":" + row["field"]: {"value": sha(_native_scalar(row["value"]))} for row in rows}
    return result


def _old_row_changes(before, after):
    return [{"doctype": table, "name": name, "before": fields, "after": after.get(table, {}).get(name)}
        for table, rows in before.items() for name, fields in rows.items()
        if fields != after.get(table, {}).get(name)]


def _setup_preconditions():
    import frappe
    from cipher_aec.governance.context import COMPANY_ABILITIES
    _administrator()
    if not set(ABILITIES).issubset(COMPANY_ABILITIES):
        raise RuntimeError("The reviewed Company Ricky metadata/ability integration is not installed.")
    for table in RICKY_TABLES:
        if not frappe.get_meta(table).has_field("scope_type"):
            raise RuntimeError("The additive Company metadata migration must be qualified first.")


def _proposed_identity_observations(value):
    """Read every original selector; never adopt an existing native record."""
    import frappe
    reference = fixture_company_reference(value)
    proposed = [("Role", value["native"]["role"]),
        ("Customer", {"customer_name": value["native"]["customer"]}),
        *(("UOM", name) for name in value["native"]["uoms"]),
        *(("UOM", {"symbol": symbol}) for symbol in value["native"]["setup_inputs"]["uom_symbols"]),
        *(("User", row["user"]) for row in value["users"].values()),
        *(("Cipher Person", person) for person in (value["users"]["author"]["person"], value["users"]["outsider"]["person"])),
        *(("Cipher Identity Binding", {"user": row["user"]}) for row in value["users"].values())]
    if reference is None:
        proposed.insert(0, ("Company", value["company"]))
        proposed.insert(3, ("Company", {"abbr": value["native"]["setup_inputs"]["company_abbr"]}))
    return [{"doctype": doctype, "selector": selector, "exists": bool(frappe.db.exists(doctype, selector))}
        for doctype, selector in proposed]


def _customer_fixture_references():
    """Require the two exact existing native leaves before any new allocation."""
    import frappe
    selected = {}
    for key, table, name in (("customer_group", "Customer Group", "Commercial"), ("territory", "Territory", "United States")):
        row = frappe.db.get_value(table, name, ["name", "is_group"], as_dict=True)
        if not row or row.get("name") != name or type(row.get("is_group")) is not int or row["is_group"] != 0:
            raise RuntimeError("Required exact non-group fixture master is unavailable: " + table + " " + name)
        selected[key] = row["name"]
    return selected


def _company_project_ids(company):
    import frappe
    ids = frappe.get_all("Project", filters={"company": company}, pluck="name", order_by="name asc", limit_page_length=0)
    if any(type(name) is not str for name in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("The actual Company Project inventory is malformed.")
    return sorted(ids)


def _read_existing_company_reference(reference):
    """Fresh readback only; never insert, save or repair Company/accounts."""
    import frappe
    validate_company_reference(reference)
    expected = {"name": reference["company"], "is_group": 0,
        **{key: reference[key] for key in ("abbr", "default_currency", "country", "default_receivable_account")}}
    company = frappe.db.get_value("Company", reference["company"], list(expected), as_dict=True)
    account = frappe.db.get_value("Account", reference["default_receivable_account"], list(reference["account"]), as_dict=True)
    if (not typed_equal(company, expected) or not typed_equal(account, reference["account"])
            or not typed_equal(_company_project_ids(reference["company"]), reference["initial_project_ids"])):
        raise RuntimeError("The existing synthetic Company/account/Project reference changed or is not exact.")
    return deepcopy(reference)


def prepare_company_fixture(private_directory, company_reference=None):
    """Allocate a new setup only in root's serial User/Auth slot.

    Every existing-row change fails preservation, including native Account-tree
    and USD/controller changes. Credentials stay in the private manifest.
    """
    import frappe
    _setup_preconditions()
    customer_references = _customer_fixture_references()
    reference = _read_existing_company_reference(company_reference) if company_reference is not None else None
    base = Path(frappe.get_site_path("private", "cipher-fixtures")).resolve()
    if Path(private_directory).resolve() != base or not base.is_dir():
        raise RuntimeError("Pass the existing site's private/cipher-fixtures directory.")
    marker = uuid4().hex[:12]
    work = base / ("ricky-company-" + marker)
    work.mkdir(mode=0o700)
    author, outsider = secrets.token_hex(5), secrets.token_hex(5)
    users = {role: {"user": f"ricky.company.{role}.{marker}@cipher.example",
        "person": author if role != "outsider" else outsider, "password": secrets.token_urlsafe(32)}
        for role in ("author", "alias", "outsider")}
    value = {"schema": SCHEMA, "fixture_id": "ricky-company-" + marker, "site": frappe.local.site,
        "created_at": timestamp(), "company": reference["company"] if reference else "Ricky Company " + marker, "users": users,
        "native": {"role": "Ricky Company read " + marker,
            "uoms": ["Ricky metre " + marker, "Ricky centimetre " + marker],
            "customer": "Ricky customer " + marker,
            "setup_inputs": {"company_abbr": reference["abbr"] if reference else "RC" + marker[:6], "currency": "USD", "country": "United States",
                "customer_group": customer_references["customer_group"], "territory": customer_references["territory"],
                "uom_symbols": ["RC" + str(index) + marker for index in range(2)]}}, "duties": {}, "inputs": {}, "intents": {},
        "stages": {}, "preservation": {}, "journal_directory": str(work),
        "metadata_preservation": {}, "native_projection_observations": [], "shared_receipt_observations": []}
    if reference is not None:
        value["native"].update(company_reference=reference, original_project_ids=deepcopy(reference["initial_project_ids"]))
    path = work / "fixture.secret.json"
    write_private(path, value)  # All introduced names/passwords before their first write.
    return _complete_company_fixture_setup(value, path)


def _private_failure_bytes(path):
    path = Path(path)
    if (path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077
            or path.stat().st_size > 1048576):
        raise RuntimeError("Use bounded exact mode0600 failed-phase evidence files.")
    return path.read_bytes()


def continue_company_fixture_preinventory(private_manifest, failed_phase_record, failed_phase_log):
    """One same-manifest continuation of the original absent-HRMS failure only.

    Root supplies the original setup phase JSON and its hash-bound raw log as
    private files. No allocated identity or password is generated or replaced.
    An archive/continuation marker or any partial setup blocks another attempt.
    """
    import frappe
    value = _load_fixture(private_manifest)
    _setup_preconditions()
    path, work = Path(private_manifest), Path(value["journal_directory"])
    if path.name != "fixture.secret.json":
        raise RuntimeError("Continue only the original allocated fixture manifest path.")
    empty_maps = ("stages", "inputs", "duties", "intents", "preservation", "metadata_preservation")
    if (any(not typed_equal(value[key], {}) for key in empty_maps)
            or value["native_projection_observations"] != [] or value["shared_receipt_observations"] != []):
        raise RuntimeError("Only an untouched original preinventory allocation may continue.")
    archive_path = work / "preinventory-continuation-original.secret.json"
    if (list(work.glob("preservation-*.secret.json")) or (work / "http-journal.secret.json").exists()
            or (work / "http-journal.secret.json").is_symlink() or archive_path.exists() or archive_path.is_symlink()):
        raise RuntimeError("Original inventory/command/continuation journals forbid setup continuation.")
    marker = value["fixture_id"].removeprefix("ricky-company-")
    expected_native = {"role": "Ricky Company read " + marker,
        "uoms": ["Ricky metre " + marker, "Ricky centimetre " + marker], "customer": "Ricky customer " + marker,
        "setup_inputs": {"company_abbr": "RC" + marker[:6], "currency": "USD", "country": "United States",
            "customer_group": "All Customer Groups", "territory": "All Territories",
            "uom_symbols": ["RC" + str(index) + marker for index in range(2)]}}
    if not typed_equal(value["native"], expected_native):
        raise RuntimeError("The original native allocation changed; never reseed or adopt it.")
    record_raw, log_raw = _private_failure_bytes(failed_phase_record), _private_failure_bytes(failed_phase_log)
    record = json.loads(record_raw)
    expected_phase = {"schema": "cipher.company-ricky.native-phase.v1", "phase": "setup", "site": value["site"],
        "module": "test_ricky_company_native", "function": "prepare_company_fixture", "status": "failed",
        "main_changed": False, "exit_code": 1, "log_sha256": hashlib.sha256(log_raw).hexdigest()}
    if (type(record) is not dict or any(not typed_equal(record.get(key), item) for key, item in expected_phase.items())
            or b"before = _inventory()" not in log_raw or b"in _inventory" not in log_raw
            or b"RuntimeError: Missing required ordinary fixture metadata: Expense Claim" not in log_raw):
        raise RuntimeError("Use the exact original Expense Claim preinventory failure record and raw log.")
    if "hrms" in frappe.get_installed_apps() or frappe.db.exists("DocType", "Expense Claim"):
        raise RuntimeError("This continuation is only for unchanged absent-HRMS/Expense Claim standing.")
    observed = _proposed_identity_observations(value)
    if len(observed) != 16 or any(row["exists"] for row in observed):
        raise RuntimeError("A proposed original fixture identity exists; partial setup can never be retried.")
    original_raw = _private_failure_bytes(path)
    if not typed_equal(json.loads(original_raw), value):
        raise RuntimeError("The original manifest changed during the independent absence readback.")
    original_sha = hashlib.sha256(original_raw).hexdigest()
    write_private(archive_path, {"schema": "cipher.fixture.ricky.company.preinventory-original.v1",
        "manifest_sha256": original_sha, "manifest_base64": base64.b64encode(original_raw).decode(),
        "failed_phase_record_sha256": hashlib.sha256(record_raw).hexdigest(),
        "failed_phase_record_base64": base64.b64encode(record_raw).decode(),
        "failed_phase_log_sha256": hashlib.sha256(log_raw).hexdigest(),
        "failed_phase_log_base64": base64.b64encode(log_raw).decode()})
    value["stages"]["preinventory_continuation"] = {"status": "prepared_before_original_setup_body", "at": timestamp(),
        "original_manifest_sha256": original_sha, "archive_path": str(archive_path),
        "failed_phase_record_sha256": hashlib.sha256(record_raw).hexdigest(), "failed_phase_log_sha256": hashlib.sha256(log_raw).hexdigest(),
        "original_identity_absence": observed, "hrms_installed": False, "expense_claim_present": False}
    write_private(path, value)
    return _complete_company_fixture_setup(value, path)


def _complete_company_fixture_setup(value, path):
    """Create fixture records with an explicit new or read-only referenced Company."""
    import frappe
    from frappe.permissions import add_permission, update_permission_property
    from cipher_aec.governance.context import trusted_write
    from cipher_aec.install import _person, _user, _binding, _grant_company
    work = Path(value["journal_directory"])
    marker = value["fixture_id"].removeprefix("ricky-company-")
    users = value["users"]
    author, outsider = users["author"]["person"], users["outsider"]["person"]
    reference = fixture_company_reference(value)
    if reference is not None:
        _read_existing_company_reference(reference)
        _customer_fixture_references()
    before = _inventory()
    write_private(work / "preservation-before.secret.json", before)
    if any(row["exists"] for row in _proposed_identity_observations(value)):
        raise RuntimeError("A proposed new fixture identity already exists; never reset it.")
    try:
        with trusted_write():
            if reference is None:
                frappe.get_doc({"doctype": "Company", "company_name": value["company"], "abbr": value["native"]["setup_inputs"]["company_abbr"],
                    "default_currency": "USD", "country": "United States"}).insert(ignore_permissions=True)
            value["stages"]["native_setup_results"] = {"company": value["company"], "people": [], "bindings": {}}
            write_private(path, value)
            for person in (author, outsider):
                _person(person, "Company Ricky fixture " + marker)
                value["stages"]["native_setup_results"]["people"].append(person)
                write_private(path, value)
            for row in users.values():
                _user(row["user"], "Company Ricky fixture", row["password"])
                _binding(row["user"], row["person"])
                value["stages"]["native_setup_results"]["bindings"][row["user"]] = frappe.db.get_value(
                    "Cipher Identity Binding", {"user": row["user"]}, "name")
                write_private(path, value)
            for ability in ABILITIES:
                _grant_company(author, value["company"], ability)
                value["duties"][ability] = frappe.db.get_value("Cipher Project Duty", {
                    "person": author, "company": value["company"], "scope_type": "Company", "ability": ability}, "name")
                value["stages"].setdefault("original_duty_states", {})[ability] = _duty_state(
                    value, ability, frappe.get_doc("Cipher Project Duty", value["duties"][ability]))
                write_private(path, value)
            role = value["native"]["role"]
            role_doc = frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
            value["stages"]["native_setup_results"]["role"] = role_doc.name
            write_private(path, value)
            for table in ("Company", "Customer", "Opportunity", "UOM", "Currency", *RICKY_TABLES):
                add_permission(table, role, 0)
                for permission in ("read", "select"):
                    update_permission_property(table, role, 0, permission, 1)
                if table == "Opportunity":
                    for permission in ("create", "write"):
                        update_permission_property(table, role, 0, permission, 1)
            for row in users.values():
                user = frappe.get_doc("User", row["user"])
                user.append("roles", {"role": role})
                user.save(ignore_permissions=True)
            company = frappe.get_doc("Company", value["company"])
            customer = frappe.get_doc({"doctype": "Customer", "customer_name": value["native"]["customer"],
                "customer_type": "Company", "customer_group": value["native"]["setup_inputs"]["customer_group"],
                "territory": value["native"]["setup_inputs"]["territory"],
                "accounts": [{"company": company.name, "account": company.default_receivable_account}]}).insert(ignore_permissions=True)
            value["native"]["customer"] = customer.name
            write_private(path, value)
            for index, name in enumerate(value["native"]["uoms"]):
                unit = frappe.get_doc({"doctype": "UOM", "uom_name": name,
                    "symbol": value["native"]["setup_inputs"]["uom_symbols"][index],
                    "enabled": 1, "must_be_whole_number": 0}).insert(ignore_permissions=True)
                value["stages"]["native_setup_results"].setdefault("uoms", []).append(unit.name)
                write_private(path, value)
        value["stages"]["native_projection_before"] = _native_listing(value)
        after = _inventory()
        changes = _old_row_changes(before, after)
        value["preservation"] = {"setup_old_rows_unchanged": not changes, "old_row_changes": changes,
            "before_sha256": sha(before), "after_sha256": sha(after),
            "qualification": "Typed literal old-row inventory; unexpected native maintenance refuses continuation pending exact separate attribution."}
        write_private(work / "preservation-after-setup.secret.json", after)
        write_private(path, value)
        if changes:
            raise RuntimeError("Native setup changed existing business/config rows; exact attribution is recorded and requires review.")
        frappe.db.commit()
        value["stages"]["setup"] = {"status": "committed", "at": timestamp()}
        write_private(path, value)
    except BaseException:
        frappe.db.rollback()
        value["stages"]["setup"] = {"status": "failed_rollback_attempted_requires_reconciliation", "at": timestamp()}
        write_private(path, value)
        raise
    return {"fixture_id": value["fixture_id"], "private_manifest": str(path), "status": "setup_only"}


def reconcile_company_setup(private_manifest):
    """Independent readback only; never reset/recreate a partial fixture."""
    import frappe
    value = _load_fixture(private_manifest)
    reference = fixture_company_reference(value)
    observations = {"company_exists": bool(frappe.db.exists("Company", value["company"])),
        "company_mode": "referenced-existing" if reference else "allocated-new",
        "company_expected_present": reference is not None,
        "users": {role: bool(frappe.db.exists("User", row["user"])) for role, row in value["users"].items()},
        "people": {person: bool(frappe.db.exists("Cipher Person", person)) for person in {row["person"] for row in value["users"].values()}},
        "role_exists": bool(frappe.db.exists("Role", value["native"]["role"]))}
    observations["proposed_identity_readback"] = _proposed_identity_observations(value)
    if reference is not None:
        try:
            _read_existing_company_reference(reference)
        except (RuntimeError, ValueError):
            observations["company_reference_matches"] = False
        else:
            observations["company_reference_matches"] = True
    before_path = Path(value["journal_directory"]) / "preservation-before.secret.json"
    if before_path.exists():
        before = json.loads(before_path.read_text())
        observations["old_row_changes"] = _old_row_changes(before, _inventory())
        observations["preservation_status"] = "original_inventory_compared"
    else:
        observations["old_row_changes"] = None
        observations["preservation_status"] = "not_established_no_original_before_inventory"
    write_private(Path(value["journal_directory"]) / "setup-reconciliation.secret.json", observations)
    frappe.db.rollback()
    return {"fixture_id": value["fixture_id"], "status": "readback_recorded_no_repair",
        "existing_fixture_users": sum(observations["users"].values()), "company_exists": observations["company_exists"],
        "company_mode": observations["company_mode"], "company_expected_present": observations["company_expected_present"],
        "company_reference_matches": observations.get("company_reference_matches"),
        "existing_old_row_changes": len(observations["old_row_changes"]) if observations["old_row_changes"] is not None else None,
        "preservation_status": observations["preservation_status"]}


def _run(value, case):
    from cipher_aec.ricky.storage import CompanyStore
    intent = saved_intent(value, case)
    run = CompanyStore(worker=True).get("run", intent["run_id"])
    if (run["company"] != value["company"] or run["user"] != value["users"]["author"]["user"]
            or run["person"] != value["users"]["author"]["person"]
            or run["operation_id"] != intent["operation_id"] or not typed_equal(run["request"], intent["payload"]["request"])):
        raise AssertionError("The native scenario does not match its original HTTP admission.")
    return run


def _native_listing(value):
    """Actual current-user ORM query/count with no permission-error fallback."""
    import frappe
    from cipher_aec.governance.context import current_actor
    result = {}
    try:
        for role, row in value["users"].items():
            frappe.set_user(row["user"])
            if current_actor().person_id != row["person"]:
                raise AssertionError("The native projection is not using the exact fixture User/Person.")
            result[role] = {}
            for table in RICKY_TABLES:
                ids = sorted(item.name for item in frappe.get_list(table, fields=["name"], limit_page_length=0))
                count = frappe.get_list(table, fields=[{"COUNT": "name", "as": "total"}])[0]["total"]
                if type(count) is not int or count != len(ids):
                    raise AssertionError("Actual native list/count observations disagree.")
                result[role][table] = {"ids": ids, "count": count}
    finally:
        frappe.set_user("Administrator")
    return result


def verify_company_native_projections(private_manifest):
    import frappe
    from cipher_aec.governance.context import current_actor
    from .ricky_company_central_acceptance import verify_native_projections
    value = _fixture(private_manifest)
    known = {table: sorted(frappe.get_all(table, filters={"company": value["company"], "scope_type": "Company"}, pluck="name"))
        for table in RICKY_TABLES}
    if known["Cipher Proposed Change"]:
        raise AssertionError("Company deterministic reads created forbidden Proposed Changes.")
    if any(not known[table] for table in RICKY_TABLES if table != "Cipher Proposed Change"):
        raise RuntimeError("Complete one real read/selected artifact before full native projection coverage.")
    after = _native_listing(value)
    observations = []
    try:
        for role, owner in value["users"].items():
            frappe.set_user(owner["user"])
            if current_actor().person_id != owner["person"]:
                raise AssertionError("The observed native actor changed.")
            for table in RICKY_TABLES:
                filtered = frappe.get_list(table, filters={"company": value["company"], "scope_type": "Company"}, fields=["name"], limit_page_length=0)
                count = frappe.get_list(table, filters={"company": value["company"], "scope_type": "Company"}, fields=[{"COUNT": "name", "as": "total"}])[0]["total"]
                permissions = [{"id": name, "allowed": bool(frappe.has_permission(table, "read", doc=frappe.get_doc(table, name), user=owner["user"]))}
                    for name in known[table]]
                observations.append({"user": owner["user"], "person": owner["person"], "company": value["company"], "doctype": table,
                    "known_company_ids": known[table], "before": value["stages"]["native_projection_before"][role][table],
                    "after": after[role][table], "company_query_ids": sorted(item.name for item in filtered),
                    "company_query_count": count, "company_read_permissions": permissions})
    finally:
        frappe.set_user("Administrator")
        frappe.db.rollback()
    require_projection_coverage(value, observations, known)
    value["native_projection_observations"] = observations
    result = verify_native_projections(value)
    write_private(private_manifest, value)
    return {"status": "passed", "actor_doctype_pairs": 18, "company_proposed_changes": "structurally_empty_forbidden_writer",
        "legacy_visibility": "unchanged_actual_baseline_only_not_positive_Project_API_qualification", **result}


def _receipt(value, case, kind):
    import frappe
    if kind not in ("start", "stop"):
        raise ValueError("Use a fixed start or stop receipt kind.")
    intent = saved_intent(value, case)
    rows = [row for row in Journal(value["journal_directory"]).rows if row["key"] == kind + "-" + case]
    if len(rows) != 1:
        raise RuntimeError("The original authentic HTTP command journal is missing.")
    command = "ricky.company.read.start.v1" if kind == "start" else "ricky.company.read.cancel.v1"
    name = sha({"person": value["users"]["author"]["person"], "operation_id": rows[0]["operation_id"]})
    receipt = frappe.db.get_value("Cipher Command Receipt", name,
        ["person", "company", "scope_type", "project", "command", "state", "result_json", "result_hash"], as_dict=True)
    if (not receipt or receipt.person != value["users"]["author"]["person"] or receipt.company != value["company"]
            or receipt.scope_type != "Company" or receipt.project or receipt.command != command or receipt.state != "Succeeded"
            or json.loads(receipt.result_json).get("id") != intent["run_id"]):
        raise AssertionError("The actual stored receipt does not match its authentic original command.")
    return rows[0], {"result_json": receipt.result_json, "result_hash": receipt.result_hash}


def capture_company_receipt_before(private_manifest, case, kind="start"):
    """Capture real canonical bytes before the subsequent replay stage."""
    import frappe
    value = _fixture(private_manifest)
    _, stored = _receipt(value, case, kind)
    key = kind + "-" + case
    snapshots = value["stages"].setdefault("receipt_before", {})
    if key in snapshots and not typed_equal(snapshots[key], stored):
        raise AssertionError("An already captured original receipt changed.")
    snapshots[key] = stored
    run = _run(value, case)
    identity = {key: run[key] for key in ("id", "user", "person", "company", "original_session_reference")}
    identity["authority_digest"] = sha(run["authority"])
    bindings = value["stages"].setdefault("original_run_bindings", {})
    if case in bindings and not typed_equal(bindings[case], identity):
        raise AssertionError("The persisted original run/session identity changed.")
    bindings[case] = identity
    write_private(private_manifest, value)
    frappe.db.rollback()
    return {"status": "actual_receipt_bytes_captured", "case": case, "kind": kind}


def verify_company_shared_receipts(private_manifest):
    """Full closure requires the declared four starts and two Stop cases."""
    import frappe
    from .ricky_company_central_acceptance import verify_shared_receipts
    value = _fixture(private_manifest)
    required = {"start-" + case for case in ("lookup", "recompute", "compare", "convert")}
    required |= {"start-" + case for case in value["stages"].get("corrected_cases", {})}
    required |= {"stop-fenced-stop", "stop-source-revoked-stop"}
    before = value["stages"].get("receipt_before", {})
    http = value["stages"].get("receipt_http_observations", {})
    missing = sorted(required - (set(before) & set(http)))
    if missing:
        return {"status": "pending", "missing_actual_captures": missing}
    observations = []
    for key in sorted(required):
        kind, case = key.split("-", 1)
        journal, stored = _receipt(value, case, kind)
        initial = [entry["envelope"]["data"] for entry in journal["attempts"] if entry["status"] < 400
            and entry.get("envelope", {}).get("data", {}).get("operation", {}).get("replayed") is False]
        if len(initial) != 1:
            raise AssertionError("The original successful non-replay HTTP response is unavailable; do not reconstruct it.")
        observations.append({"user": value["users"]["author"]["user"], "person": value["users"]["author"]["person"],
            "company": value["company"], "run_id": saved_intent(value, case)["run_id"], "operation_id": journal["operation_id"],
            "command": "ricky.company.read.start.v1" if kind == "start" else "ricky.company.read.cancel.v1",
            "initial": initial[0], "replay": http[key]["replay"], "operation_read": http[key]["operation_read"],
            "stored_receipt": {"before": before[key], "after": stored}})
    value["shared_receipt_observations"] = observations
    result = verify_shared_receipts(value)
    write_private(private_manifest, value)
    frappe.db.rollback()
    return {"status": "passed", "declared_receipt_case_coverage": sorted(required), **result}


def run_company_worker_callthrough(private_manifest, case):
    """Actual process_run callthrough against ONE authentic HTTP queued run."""
    import frappe
    from cipher_aec.ricky.worker import process_run
    value = _fixture(private_manifest)
    if case not in ("lookup", "recompute", "compare", "convert", "convert-r9", "expired-original"):
        raise ValueError("Select one fixed callthrough case.")
    declared_case(value, case)
    run = _run(value, case)
    if run["status"] != "queued":
        raise RuntimeError("The isolated consumer prerequisite did not leave this exact run queued.")
    value["stages"][case] = {"status": "prepared_before_callthrough", "run_id": run["id"], "at": timestamp()}
    write_private(private_manifest, value)
    process_run(run["id"])
    current = _run(value, case)
    expected = "failed" if case == "expired-original" else "succeeded"
    if current["status"] != expected or current["generations"] != 0 or current["proposal_ids"]:
        raise AssertionError("The real deterministic callthrough did not reach its declared standing.")
    if case == "expired-original" and (current["result"] is not None or current["error"]["code"] != "session_revoked"):
        raise AssertionError("Expired original work must refuse without accepting a result.")
    if case != "expired-original":
        assert current["result_digest"] is not None and current["result"] is not None
        verify_read_value(value["inputs"], case, current["result"])
        value["inputs"].setdefault("recorded_results", {})[case] = deepcopy(current["result"])
    value["stages"][case] = {"status": "passed", "mode": "actual_process_run_callthrough_not_RQ_delivery",
        "run_id": current["id"], "result_digest": current["result_digest"], "at": timestamp()}
    write_private(private_manifest, value)
    frappe.db.rollback()
    return deepcopy(value["stages"][case])


def _claim_failure(error):
    code = getattr(error, "code", error.args[0] if error.args else "")
    return {"error_type": type(error).__name__[:80], "error_code": str(code)[:80], "error_message": str(error)[:512]}


def run_company_claim_race(private_manifest, case="claim-race"):
    """Two ordinary native connections compete for the saved HTTP run lease."""
    import frappe
    value = _fixture(private_manifest)
    if declared_case(value, case) != "claim-race":
        raise ValueError("Use one declared claim-race case.")
    if case in value["stages"]:
        raise RuntimeError("A claim race is one-shot; retain its original observations and declare a separate corrected case.")
    run = _run(value, case)
    if run["status"] != "queued":
        raise RuntimeError("Root must hold this site's isolated queue consumer before the race.")
    site = frappe.local.site
    frappe.db.rollback()
    barrier, observations = threading.Barrier(2), []
    def claim(index):
        observation = {"thread": index}
        try:
            frappe.init(site=site)
            frappe.connect()
            from cipher_aec.ricky.company_service import build_service
            from cipher_aec.ricky.company_contracts import decode_run_authority
            service = build_service(worker=True)
            barrier.wait(10)
            with service.backend.original_user(decode_run_authority(run)):
                claimed = service.claim(run["id"])
            observation.update(claimed=claimed is not None, token=claimed[1] if claimed else None)
        except BaseException as error:
            observation.update(_claim_failure(error))
        finally:
            try:
                frappe.destroy()
            except BaseException as error:
                observation["cleanup_error"] = _claim_failure(error)
            observations.append(observation)
    threads = [threading.Thread(target=lambda index=index: claim(index), daemon=True) for index in range(2)]
    value["stages"][case] = {"status": "prepared_before_native_threads", "run_id": run["id"]}
    write_private(private_manifest, value)
    for thread in threads: thread.start()
    for thread in threads: thread.join(15)
    value["stages"][case] = {"status": "observed_before_assertions", "run_id": run["id"],
        "claims": deepcopy(observations), "thread_alive": [thread.is_alive() for thread in threads], "at": timestamp()}
    write_private(private_manifest, value)
    if any(value["stages"][case]["thread_alive"]) or len(observations) != 2 or any("error_type" in row or "cleanup_error" in row for row in observations):
        raise AssertionError("The bounded independent claim race did not complete cleanly.")
    if sum(row["claimed"] for row in observations) != 1:
        raise AssertionError("Exactly one claimant must own the original run lease.")
    value["stages"][case]["status"] = "passed"
    write_private(private_manifest, value)
    return deepcopy(value["stages"][case])


def claim_company_fenced_case(private_manifest):
    from cipher_aec.ricky.company_service import build_service
    from cipher_aec.ricky.company_contracts import decode_run_authority
    value = _fixture(private_manifest)
    run = _run(value, "fenced-stop")
    service = build_service(worker=True)
    with service.backend.original_user(decode_run_authority(run)):
        claimed = service.claim(run["id"])
    if claimed is None:
        raise AssertionError("The saved HTTP run was not claimable.")
    value["stages"]["fenced-stop"] = {"status": "awaiting_authentic_HTTP_stop", "run_id": run["id"], "token": claimed[1]}
    write_private(private_manifest, value)
    return {"status": "awaiting_authentic_HTTP_stop", "run_id": run["id"]}


def verify_company_fenced_case(private_manifest):
    import frappe
    from cipher_aec.ricky.company_service import CompanyExecution, build_service
    from cipher_aec.ricky.company_contracts import decode_run_authority
    from cipher_aec.ricky.contracts import RickyError
    value = _fixture(private_manifest)
    run = _run(value, "fenced-stop")
    if run["status"] != "cancelled":
        raise RuntimeError("The exact original HTTP case must first be stopped over authenticated HTTP.")
    before = frappe.db.count("Cipher Tool Invocation", {"run_id": run["id"]})
    service = build_service(worker=True)
    with service.backend.original_user(decode_run_authority(run)):
        try:
            CompanyExecution(service, run["id"], value["stages"]["fenced-stop"]["token"]).invoke(
                "aec.pursuit.lookup", {}, "selected-deterministic-read")
        except RickyError as error:
            if error.code not in ("cancelled", "lease_lost"):
                raise
        else:
            raise AssertionError("A cancelled original lease accepted a result.")
    if frappe.db.count("Cipher Tool Invocation", {"run_id": run["id"]}) != before:
        raise AssertionError("The fenced attempt persisted a tool output.")
    frappe.db.rollback()
    value["stages"]["fenced-stop"].update(status="passed", no_new_invocation=True)
    write_private(private_manifest, value)
    return {"status": "passed", "no_new_invocation": True}


def _duty(value, ability, active, original):
    import frappe
    from cipher_aec.governance.context import trusted_write
    if ability not in ("document.read", "ricky.run") or type(active) is not int or active not in (0, 1):
        raise ValueError("Only the two declared reversible fixture outages are supported.")
    row = frappe.get_doc("Cipher Project Duty", value["duties"][ability])
    current = _duty_state(value, ability, row)
    if not typed_equal({key: item for key, item in current["fields"].items() if key != "active"},
            {key: item for key, item in original["fields"].items() if key != "active"}):
        raise AssertionError("Refusing restoration across unrelated fixture duty drift.")
    with trusted_write():
        row.active = active
        row.save(ignore_permissions=True)
    frappe.db.commit()


def _independent_duty_readback(value, ability, original):
    """A new native connection observes exact scope/validity/active restoration.

    Supported save audit timestamps may change; no timestamp rollback is claimed.
    """
    import frappe
    site, observations = frappe.local.site, []
    def readback():
        try:
            frappe.init(site=site)
            frappe.connect()
            row = frappe.db.get_value("Cipher Project Duty", value["duties"][ability], list(DUTY_FIELDS), as_dict=True)
            observations.append({"matches": typed_equal(_duty_state(value, ability, row), original)})
        except BaseException as error:
            observations.append({"error_type": type(error).__name__})
        finally:
            try:
                frappe.db.rollback()
            finally:
                frappe.destroy()
    thread = threading.Thread(target=readback, daemon=True)
    thread.start()
    thread.join(10)
    if thread.is_alive() or observations != [{"matches": True}]:
        raise AssertionError("The independent connection did not observe exact restored fixture authority.")


def run_company_source_revocation(private_manifest, base_url, host_header=None):
    """Unused selected source denial, source-free Stop and original UUID replay."""
    from .test_ricky_company_http import _HTTP, RICKY, stop_company_http_case
    value = _fixture(private_manifest)
    for case in ("lookup", "source-revoked-stop"): saved_intent(value, case)
    original = _capture_duty_outage(value, "document.read", "source-revocation", private_manifest)
    try:
        _duty(value, "document.read", 0, original)
        rpc = _HTTP(private_manifest, base_url, host_header); rpc.login()
        for case in ("lookup", "source-revoked-stop"):
            intent = saved_intent(rpc.value, case)
            rpc.call(RICKY + "get_run", {"company": value["company"], "run_id": intent["run_id"]}, expected={"not_found", "capability_denied"})
            rpc.call(RICKY + "start_read", {key: item for key, item in intent["payload"].items() if key != "operation_id"},
                key="start-" + case, expected={"not_found", "capability_denied"})
        stop_company_http_case(private_manifest, "source-revoked-stop", base_url, host_header)
        capture_company_receipt_before(private_manifest, "source-revoked-stop", "stop")
        stop_company_http_case(private_manifest, "source-revoked-stop", base_url, host_header)
    finally:
        _duty(value, "document.read", original["active"], original)
        _independent_duty_readback(value, "document.read", original)
    rpc = _HTTP(private_manifest, base_url, host_header); rpc.login()
    intent = saved_intent(rpc.value, "lookup")
    replay = rpc.call(RICKY + "start_read", {key: item for key, item in intent["payload"].items() if key != "operation_id"}, key="start-lookup")["data"]
    if not replay["operation"]["replayed"]:
        raise AssertionError("The exact original UUID did not recover its retained queued receipt after restoration.")
    rpc.value["stages"]["source-revocation"].update(status="passed", unused_selection_denied=True,
        source_free_stop=True, same_UUID_receipt_after_restore=True, independent_restoration=True)
    write_private(private_manifest, rpc.value)
    return deepcopy(rpc.value["stages"]["source-revocation"])


def run_company_capability_revocation(private_manifest, base_url, host_header=None):
    from .test_ricky_company_http import _HTTP, RICKY
    value = _fixture(private_manifest)
    intent = saved_intent(value, "capability-revoked")
    original = _capture_duty_outage(value, "ricky.run", "capability-revocation", private_manifest)
    try:
        _duty(value, "ricky.run", 0, original)
        rpc = _HTTP(private_manifest, base_url, host_header); rpc.login()
        rpc.call(RICKY + "get_run", {"company": value["company"], "run_id": intent["run_id"]}, expected={"not_found", "capability_denied"})
        rpc.call(RICKY + "cancel_run", {"company": value["company"], "run_id": intent["run_id"]},
            key="stop-capability-revoked", expected={"not_found", "capability_denied"})
    finally:
        _duty(value, "ricky.run", original["active"], original)
        _independent_duty_readback(value, "ricky.run", original)
    rpc = _HTTP(private_manifest, base_url, host_header); rpc.login()
    result = rpc.command("stop-capability-revoked", RICKY + "cancel_run", {"run_id": intent["run_id"]})
    if result["status"] != "cancelled":
        raise AssertionError("The saved original Stop UUID did not succeed after current capability restoration.")
    rpc.value["stages"]["capability-revocation"].update(status="passed", stop_requires_current_capability=True,
        same_UUID_after_restore=True, independent_restoration=True)
    write_private(private_manifest, rpc.value)
    return deepcopy(rpc.value["stages"]["capability-revocation"])


def verify_company_restoration(private_manifest):
    """Readback only; never grants or silently repairs authority."""
    import frappe
    from cipher_aec.governance.context import current_actor, duty_rows
    value = _fixture(private_manifest)
    for role, row in value["users"].items():
        actor = current_actor(row["user"])
        if actor.person_id != row["person"] or duty_rows(actor):
            raise AssertionError("The exact Company-only fixture identity changed or acquired Project duties.")
    for ability, name in value["duties"].items():
        row = frappe.get_doc("Cipher Project Duty", name)
        if not typed_equal(_duty_state(value, ability, row), value["stages"].get("original_duty_states", {}).get(ability)):
            raise AssertionError("An original fixture duty is not independently restored.")
    reference = fixture_company_reference(value)
    expected_projects = reference["initial_project_ids"] if reference else []
    actual_projects = _company_project_ids(value["company"])
    if not typed_equal(actual_projects, expected_projects):
        raise AssertionError("The exact original Company Project set changed or a placeholder Project was introduced.")
    if reference is not None:
        _read_existing_company_reference(reference)
    for case, original in value["stages"].get("original_run_bindings", {}).items():
        run = _run(value, case)
        if any(not typed_equal(run[key], item) for key, item in original.items() if key != "authority_digest") or sha(run["authority"]) != original["authority_digest"]:
            raise AssertionError("Completed observation rebound an original run identity/session.")
    before = json.loads((Path(value["journal_directory"]) / "preservation-before.secret.json").read_text())
    changes = _old_row_changes(before, _inventory())
    if changes:
        write_private(Path(value["journal_directory"]) / "unexpected-old-row-delta.secret.json", changes)
        raise AssertionError("An existing literal business/config row changed; exact attribution is required.")
    frappe.db.rollback()
    return {"status": "passed", "old_row_inventory_unchanged": True, "company_projects": len(actual_projects), "introduced_projects": 0,
            "qualification": "Native readback only; no HTTP/queue/p95 claim."}
