"""Opt-in EST-01 acceptance with real Frappe persistence and authored fixtures.

bench --site <synthetic-site> execute cipher_aec.tests.test_estimating_acceptance.run_acceptance
No model, quote provider, calibrated geometry or estimate acceptance is invoked.
"""

import hashlib
import secrets
from copy import deepcopy
from uuid import uuid4


def run_acceptance(include_schema_samples=False):
    import frappe
    from cipher_aec.api.errors import DomainError
    from cipher_aec.documents.service import upload_document, get_citation
    from cipher_aec.estimating import service
    from cipher_aec.estimating.calculation import calculate
    from cipher_aec.governance.commands import read_operation
    from cipher_aec.governance.context import ABILITIES, assert_synthetic_site, trusted_write
    from cipher_aec.install import _person, _user, _binding, _grant, set_synthetic_duty

    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise RuntimeError("Run authored EST acceptance through the synthetic site Administrator.")
    company = "Cipher Synthetic Company"
    if not frappe.db.exists("Company", company):
        raise RuntimeError("Seed the synthetic company before running EST acceptance.")
    marker = uuid4().hex[:12]
    user, person = f"est.fixture.{marker}@cipher.example", "EST-FIXTURE-" + marker
    administrator = frappe.db.get_value("Cipher Identity Binding", {"user": "Administrator", "active": 1}, "person")
    native_units = {}
    with trusted_write():
        _person(person, "Explicit EST-01 fixture")
        _user(user, "Explicit estimate fixture", secrets.token_urlsafe(32))
        _binding(user, person)
        project = frappe.get_doc({"doctype": "Project", "company": company, "project_name": "EST-01 explicit fixture " + marker, "status": "Open"}).insert(ignore_permissions=True)
        for subject in (person, administrator):
            for ability in sorted(ABILITIES):
                _grant(subject, company, project.name, ability)
        for key in ("sf", "cf", "cy", "lh", "eh", "time"):
            name = "EST fixture " + key + " " + marker
            native_units[key] = frappe.get_doc({"doctype": "UOM", "uom_name": name, "symbol": key + marker,
                                                "enabled": 1, "must_be_whole_number": 0}).insert(ignore_permissions=True).name
    native = _native_fixture(company, user, marker, native_units["cy"])
    frappe.db.commit()
    ids = {}
    for key, dimension in (("sf", "area"), ("cf", "volume"), ("cy", "volume"), ("lh", "labor_time"), ("eh", "equipment_time"), ("time", "time")):
        ids[key] = service.register_unit(company, project.name, str(uuid4()), native_units[key], dimension, 6)["unit"]["id"]
    frappe.db.commit()
    try:
        # Qualified metadata cannot change even through a trusted administrative
        # context; ordinary unqualified native UOM creation above remains valid.
        metadata_denied = None
        try:
            with trusted_write():
                doc = frappe.get_doc("UOM", native_units["sf"])
                doc.symbol = "changed-after-qualification"
                doc.save(ignore_permissions=True)
            raise AssertionError("Qualified UOM symbol changed without a successor identity")
        except DomainError as error:
            metadata_denied = error.code
            assert error.code == "immutable_unit"
            frappe.db.rollback()
        frappe.set_user(user)
        content = ("Explicit synthetic EST-01 authored source. One cubic yard equals 27 cubic feet. "
                   "Concrete rate: USD27 per cubic yard. Labor: USD25 per labor hour. Equipment: USD40 per equipment hour. "
                   "Tiny rate fixture: USD0.000000000001 per cubic foot. No freight or tax. "
                   "Per ten square feet:2 cubic feet material,2 labor hours,1 equipment hour; material factor1.1 and waste0.05.").encode()
        uploaded = upload_document(company=company, project=project.name, title="Explicit EST source " + marker, filename="explicit-est-source.txt",
                                   content=content, byte_length=len(content), sha256=hashlib.sha256(content).hexdigest(), operation_id=str(uuid4()))
        citation = get_citation(company, uploaded["revision"]["id"], 1)
        reference = {key: citation[key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")}
        frappe.db.commit()
        conversion = service.create_conversion(company, project.name, str(uuid4()), {"from_unit_id": ids["cf"], "to_unit_id": ids["cy"],
                        "dimension": "volume", "numerator": "1", "denominator": "27", "source": "Authored exact definition:27 cubic feet per cubic yard"},
                        [reference], "Explicit synthetic source authored for internal estimate verification")["conversion"]
        rate_ids, rate_inputs, rate_operations, lock_order = {}, {}, {}, {}
        for key, kind, unit, amount, scale in (("material", "material", "cy", "27", 6), ("labor", "labor", "lh", "25", 6),
                                               ("equipment", "equipment", "eh", "40", 6), ("tiny", "material", "cf", "0.000000000001", 12)):
            authored = {"title": "Explicit authored " + key, "cost_type": kind, "unit_id": ids[unit], "rate_amount": amount, "rate_precision": scale,
                        "currency": "USD", "quote_reference": "EXPLICIT-EST-FIXTURE-" + marker, "quote_date": "2026-10-01", "expiry_date": "2026-10-31",
                        "geography": "Explicit synthetic region", "inclusions": "Authored fixture only", "exclusions": "", "freight_tax_assumptions": "No freight or tax in this fixture",
                        "permission_basis": "Explicit synthetic content authored for internal estimate tests", "source_citations": [reference]}
            if key == "material":
                authored["item"] = native["item"]
            operation = str(uuid4())
            rate_inputs[key], rate_operations[key] = deepcopy(authored), operation
            if key == "material":
                result, lock_order["create_rate"] = _observe_lock_order(lambda: service.create_rate(company, project.name, operation, authored))
            else:
                result = service.create_rate(company, project.name, operation, authored)
            rate_ids[key] = result["rate_source"]["id"]
        frappe.db.commit()
        assert frappe.db.get_value("Cipher Rate Source", rate_ids["tiny"], "rate_amount") == "0.000000000001"
        assert frappe.get_meta("Cipher Rate Source").get_field("rate_amount").fieldtype == "Data"
        def q(amount, unit):
            return {"amount": amount, "unit_id": ids[unit], "precision": 6}
        components = []
        for key, kind, resource, amount, factor, waste in (("material", "material", "cf", "2", "1.1", "0.05"), ("labor", "labor", "lh", "2", "1", "0"), ("equipment", "equipment", "eh", "1", "1", "0")):
            components.append({"line_id": str(uuid4()), "rate_source_id": rate_ids[key], "kind": kind, "work_quantity": q("10", "sf"),
                               "resource_quantity": q(amount, resource), "material_factor": factor, "waste_fraction": waste})
        assembly_result, lock_order["create_assembly"] = _observe_lock_order(lambda: service.create_assembly(company, project.name, str(uuid4()), "Explicit EST assembly", ids["sf"], components,
                                           "Authored productivity, equipment duration, material factor and waste fixture", [conversion["id"]]))
        assembly = assembly_result["assembly_revision"]
        estimate = service.create_estimate(company, project.name, str(uuid4()), "Explicit authored estimate " + marker, "USD", "2026-10-15")["estimate"]
        frappe.db.commit()
        line_id = str(uuid4())
        lines = [{"line_id": line_id, "description": "Explicit material/labor/equipment build-up", "quantity": q("100", "sf"), "cost_code": "EST-TEST-01",
                  "notes": "Authored quantity with no geometry or calibration claim", "alternate": "", "included": True, "assembly_revision_id": assembly["id"]}]
        adjustments = [{"line_id": str(uuid4()), "kind": "indirect", "label": "Explicit overhead", "method": "fraction_of_direct", "value": "0.10", "basis_description": "Ten percent of rounded direct lines"},
                       {"line_id": str(uuid4()), "kind": "contingency", "label": "Explicit contingency", "method": "fixed", "value": "10.00", "basis_description": "Authored fixed allowance"}]
        operation = str(uuid4())
        arguments = dict(company=company, project=project.name, operation_id=operation, estimate_id=estimate["id"], expected_revision=None,
                         lines=lines, adjustments=adjustments, conversion_ids=[], basis_description="Explicit authored estimate; no measured geometry", basis_citations=[reference])
        first, lock_order["calculate_revision"] = _observe_lock_order(lambda: service.calculate_revision(**arguments))
        frappe.db.commit()
        assert first["revision"]["direct"]["amount"] == "923.10"
        assert first["revision"]["total"]["amount"] == "1025.41"
        replay = service.calculate_revision(**arguments)
        assert replay["operation"]["replayed"] and replay["revision"]["id"] == first["revision"]["id"]
        assert frappe.db.count("Cipher Estimate Revision", {"estimate": estimate["id"]}) == 1
        restored = service.get_record(company, project.name, "snapshot", first["calculation"]["id"])
        assert calculate(restored["inputs"]) == restored["result"]
        schema_samples = {"CalculateRevisionRequest": arguments, "CalculateRevisionResponse": first,
                          "EstSnapshotRecord": restored, "EstAssemblyRecord": assembly, "EstConversionRecord": conversion,
                          "EstRateRecord": service.get_record(company, project.name, "rate", rate_ids["material"]),
                          "ListEstimateUnitsResponse": service.list_units(company, project.name)}
        frappe.db.commit()

        immutable_denials = []
        for doctype, record_id in (("Cipher Rate Source", rate_ids["material"]), ("Cipher Assembly Revision", assembly["id"]),
                                   ("Cipher Estimate Revision", first["revision"]["id"]), ("Cipher Calculation Snapshot", first["calculation"]["id"])):
            try:
                frappe.get_doc(doctype, record_id).save(ignore_permissions=True)
                raise AssertionError("Generic estimating write bypass was accepted")
            except DomainError as error:
                assert error.code == "governed_write_required"
                immutable_denials.append(doctype)
                frappe.db.rollback()

        # Source corrections require an explicit successor; existing estimate
        # snapshots do not reprice themselves merely because a new quote exists.
        revised_content = b"Explicit revised synthetic quote:concrete USD30 per cubic yard. No freight or tax."
        updated = upload_document(company=company, project=project.name, title="Explicit revised EST source " + marker, filename="explicit-est-revised-source.txt",
                                  content=revised_content, byte_length=len(revised_content), sha256=hashlib.sha256(revised_content).hexdigest(), operation_id=str(uuid4()))
        next_citation = get_citation(company, updated["revision"]["id"], 1)
        next_reference = {key: next_citation[key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")}
        next_rate = deepcopy(rate_inputs["material"])
        next_rate.update(rate_amount="30", source_citations=[next_reference], quote_reference="EXPLICIT-EST-REVISED-" + marker)
        successor = service.create_rate(company, project.name, str(uuid4()), next_rate, predecessor=rate_ids["material"])["rate_source"]
        next_components = deepcopy(components)
        next_components[0]["rate_source_id"] = successor["id"]
        next_assembly = service.create_assembly(company, project.name, str(uuid4()), "Explicit revised assembly", ids["sf"], next_components,
                                               "Explicit revised material source; original ratios retained", [conversion["id"]], predecessor=assembly["id"])["assembly_revision"]
        frappe.db.commit()
        assert service.get_record(company, project.name, "snapshot", first["calculation"]["id"])["result"]["total"]["amount"] == "1025.41"
        second_arguments = deepcopy(arguments)
        second_arguments.update(operation_id=str(uuid4()), expected_revision=first["revision"]["id"])
        second_arguments["lines"][0]["assembly_revision_id"] = next_assembly["id"]
        second = service.calculate_revision(**second_arguments)
        frappe.db.commit()
        assert second["revision"]["total"]["amount"] == "1028.24"
        assert second["calculation"]["result"]["lines"][0]["line_id"] == line_id
        assert first["calculation"]["result"]["lines"][0]["line_id"] == line_id
        invalid = deepcopy(second_arguments)
        invalid.update(operation_id=str(uuid4()), expected_revision=second["revision"]["id"])
        invalid["lines"][0]["quantity"]["unit_id"] = ids["cf"]
        invalid_dimension = None
        try:
            service.calculate_revision(**invalid)
            raise AssertionError("Volume quantity was accepted against an area assembly")
        except DomainError as error:
            invalid_dimension = error.code
            assert error.code == "invalid_dimension"
            frappe.db.rollback()
        assert frappe.db.count("Cipher Estimate Revision", {"estimate": estimate["id"]}) == 2
        assert frappe.db.count("Cipher Calculation Snapshot", {"project": project.name}) == 2

        changed = deepcopy(arguments)
        changed["lines"][0]["notes"] = "Changed payload for original operation"
        try:
            service.calculate_revision(**changed)
            raise AssertionError("Changed idempotent payload was accepted")
        except DomainError as error:
            assert error.code == "operation_conflict"
            frappe.db.rollback()
        native_evidence = _native_reference_checks(company, project.name, user, native, rate_inputs["material"],
                                                    rate_ids["material"], arguments, first["calculation"]["id"],
                                                    first["revision"]["line_record_ids"][0])
        first_line = first["revision"]["line_record_ids"][0]
        frappe.set_user("Administrator")
        set_synthetic_duty(user, project.name, "document.read", 0)
        frappe.db.commit()
        frappe.set_user(user)
        denied = []
        for callback in (lambda: service.get_record(company, project.name, "snapshot", first["calculation"]["id"]),
                         lambda: service.get_record(company, project.name, "line", first_line),
                         lambda: read_operation(company, project.name, operation)):
            try:
                callback()
                raise AssertionError("Revoked document access leaked authored pricing or its original receipt")
            except DomainError as error:
                denied.append(error.code)
                assert error.code in {"capability_denied", "not_found"}
                frappe.db.rollback()
        report = {"label": "explicit-authored-est01-fixture-with-real-frappe-storage", "live_provider_qualified": False,
                "geometry_qualified": False, "estimate_acceptance_implemented": False, "project": project.name, "estimate": estimate["id"],
                "source_revision": citation["revision_id"], "source_sha256": citation["source_sha256"],
                "first_revision": first["revision"]["id"], "second_revision": second["revision"]["id"],
                "known_direct": "923.10", "known_total": "1025.41", "explicit_successor_total": "1028.24",
                "exact_precision_roundtrip": "0.000000000001", "native_money_storage": "canonical-decimal-Data-plus-declared-scale",
                "stable_line_id": line_id, "single_effect_replay": True, "immutable_source_snapshot": True,
                "published_schema_samples_available": sorted(schema_samples),
                "native_reference_checks": native_evidence, "actual_resource_lock_order": lock_order,
                "generic_write_denials": immutable_denials, "qualified_unit_metadata_denied": metadata_denied,
                "invalid_dimension_denied": invalid_dimension, "invalid_calculation_left_no_snapshot": True,
                "source_revocation_denied_reads_and_receipt": denied}
        if include_schema_samples:
            report["schema_samples"] = schema_samples
        return report
    finally:
        frappe.db.rollback()
        frappe.set_user("Administrator")


def _native_fixture(company, user, marker, uom):
    """New isolated native masters; no shared native roles or passwords change."""
    import frappe
    from frappe.permissions import add_permission, update_permission_property
    foreign = frappe.get_doc({"doctype": "Company", "company_name": "EST foreign fixture " + marker,
                               "abbr": "E" + marker[:7], "default_currency": "USD", "country": "United States"}).insert(ignore_permissions=True)
    item_group = frappe.get_doc({"doctype": "Item Group", "item_group_name": "EST supplies " + marker,
                                "parent_item_group": "All Item Groups", "is_group": 0}).insert(ignore_permissions=True)
    items = {}
    for key, scope in (("item", company), ("foreign_item", foreign.name)):
        item = frappe.get_doc({"doctype": "Item", "item_code": "EST-" + key + "-" + marker,
                              "item_name": "Explicit EST native material " + marker, "item_group": item_group.name,
                              "stock_uom": uom, "is_stock_item": 0, "item_defaults": [{"company": scope}]}).insert(ignore_permissions=True)
        items[key] = item.name
    supplier_group = frappe.get_doc({"doctype": "Supplier Group", "supplier_group_name": "EST suppliers " + marker,
                                    "parent_supplier_group": "All Supplier Groups", "is_group": 0}).insert(ignore_permissions=True)
    supplier = frappe.get_doc({"doctype": "Supplier", "supplier_name": "EST foreign supplier " + marker,
                              "supplier_group": supplier_group.name, "supplier_type": "Company",
                              "accounts": [{"company": foreign.name, "account": foreign.default_payable_account}]}).insert(ignore_permissions=True)
    customer_group = frappe.get_doc({"doctype": "Customer Group", "customer_group_name": "EST customers " + marker,
                                    "parent_customer_group": "All Customer Groups", "is_group": 0}).insert(ignore_permissions=True)
    customer = frappe.get_doc({"doctype": "Customer", "customer_name": "EST foreign customer " + marker,
                              "customer_type": "Company", "customer_group": customer_group.name,
                              "territory": "All Territories", "accounts": [{"company": foreign.name, "account": foreign.default_receivable_account}]}).insert(ignore_permissions=True)
    role = "EST native read " + marker
    frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
    for doctype in ("Item", "Supplier", "Customer"):
        add_permission(doctype, role, 0)
        update_permission_property(doctype, role, 0, "read", 1)
    account = frappe.get_doc("User", user)
    account.append("roles", {"role": role})
    account.save(ignore_permissions=True)
    frappe.clear_cache(user=user)
    return {**items, "foreign_company": foreign.name, "foreign_supplier": supplier.name,
            "foreign_customer": customer.name, "role": role}


def _native_reference_checks(company, project, user, native, rate_input, rate_id, arguments, snapshot_id, line_id):
    """Real company association, retained reference permission and RR replay proof."""
    import threading
    from unittest.mock import patch
    import frappe
    from frappe.permissions import update_permission_property
    from cipher_aec.api.errors import DomainError
    from cipher_aec.estimating import service
    from cipher_aec.governance import commands
    denied = []
    for key, doctype, changes in (("foreign_item", "Item", {"item": native["foreign_item"]}),
                                  ("foreign_supplier", "Supplier", {"item": None, "party_type": "Supplier", "party": native["foreign_supplier"]}),
                                  ("foreign_customer", "Customer", {"item": None, "party_type": "Customer", "party": native["foreign_customer"]})):
        assert frappe.has_permission(doctype, "read", doc=frappe.get_doc(doctype, native[key]), user=user)
        try:
            service.create_rate(company, project, str(uuid4()), {**rate_input, **changes})
            raise AssertionError("Native-readable foreign-company reference became an estimate source")
        except DomainError as error:
            assert error.code == "not_found"
            denied.append(doctype)
            frappe.db.rollback()
    # Establish an ordinary snapshot before the shared command precheck. A
    # separate DB connection changes this native master after command locks,
    # immediately before completed-receipt resource authorization.
    frappe.db.commit()
    isolation = frappe.db.sql("SELECT @@tx_isolation")[0][0]
    assert isolation == "REPEATABLE-READ"
    assert frappe.db.sql("SELECT company FROM `tabItem Default` WHERE parent=%s", native["item"])[0][0] == company
    site = frappe.local.site
    trigger, finished = threading.Event(), threading.Event()
    errors, writer_connections = [], []
    parent_connection = frappe.db.sql("SELECT CONNECTION_ID()")[0][0]
    def mutate():
        try:
            frappe.init(site=site)
            frappe.connect()
            frappe.set_user("Administrator")
            writer_connections.append(frappe.db.sql("SELECT CONNECTION_ID()")[0][0])
            if not trigger.wait(20):
                raise RuntimeError("Estimate replay never reached receipt authorization")
            doc = frappe.get_doc("Item", native["item"])
            assert doc.item_code.startswith("EST-item-")
            doc.set("item_defaults", [{"company": native["foreign_company"]}])
            doc.save(ignore_permissions=True)
            frappe.db.commit()
        except BaseException as error:
            errors.append(repr(error))
        finally:
            frappe.destroy()
            finished.set()
    thread = threading.Thread(target=mutate, daemon=True)
    thread.start()
    authorize = commands.authorize_receipt
    snapshot_observations = []
    def boundary(actor, command, actual_company, actual_project, result):
        trigger.set()
        if not finished.wait(25):
            raise RuntimeError("Native source revocation failed to commit")
        if errors:
            raise RuntimeError(errors[0])
        snapshot_observations.append(frappe.db.sql("SELECT company FROM `tabItem Default` WHERE parent=%s", native["item"])[0][0])
        return authorize(actor, command, actual_company, actual_project, result)
    conflict = False
    try:
        with patch.object(commands, "authorize_receipt", side_effect=boundary):
            service.calculate_revision(**arguments)
        raise AssertionError("An old RR snapshot replayed revoked native source authority")
    except frappe.QueryDeadlockError:
        conflict = True
        frappe.db.rollback()
        try:
            service.calculate_revision(**arguments)
            raise AssertionError("Fresh receipt replay ignored committed native source revocation")
        except DomainError as error:
            assert error.code == "not_found"
    except DomainError as error:
        assert error.code == "not_found"
    finally:
        frappe.db.rollback()
        trigger.set()
        thread.join(10)
    assert not thread.is_alive() and not errors
    assert writer_connections and writer_connections[0] != parent_connection
    assert snapshot_observations == [company], snapshot_observations
    assert frappe.db.sql("SELECT company FROM `tabItem Default` WHERE parent=%s", native["item"])[0][0] == native["foreign_company"]
    retained = []
    for kind, identifier in (("rate", rate_id), ("snapshot", snapshot_id), ("line", line_id)):
        try:
            service.get_record(company, project, kind, identifier)
            raise AssertionError("Retained pricing bypassed changed native source company association")
        except DomainError as error:
            assert error.code == "not_found"
            retained.append(kind)
            frappe.db.rollback()
    count_before = frappe.db.count("Cipher Calculation Snapshot", {"project": project})
    new_calculation = deepcopy(arguments)
    new_calculation.update(operation_id=str(uuid4()), expected_revision=service.get_record(company, project, "estimate", arguments["estimate_id"])["current_revision"])
    try:
        service.calculate_revision(**new_calculation)
        raise AssertionError("A new calculation consumed a revoked native source association")
    except DomainError as error:
        assert error.code == "not_found"
        frappe.db.rollback()
    assert frappe.db.count("Cipher Calculation Snapshot", {"project": project}) == count_before
    # Restore own fixture association, then revoke only this fixture user's
    # native role. Document/estimate duties remain active throughout this check.
    frappe.set_user("Administrator")
    doc = frappe.get_doc("Item", native["item"])
    doc.set("item_defaults", [{"company": company}])
    doc.save(ignore_permissions=True)
    update_permission_property("Item", native["role"], 0, "read", 0)
    frappe.clear_cache(user=user)
    frappe.db.commit()
    frappe.set_user(user)
    try:
        service.get_record(company, project, "rate", rate_id)
        raise AssertionError("Retained rate bypassed revoked standard Item read permission")
    except DomainError as error:
        assert error.code == "not_found"
        frappe.db.rollback()
    frappe.set_user("Administrator")
    update_permission_property("Item", native["role"], 0, "read", 1)
    frappe.clear_cache(user=user)
    frappe.db.commit()
    frappe.set_user(user)
    return {"foreign_company_native_readable_denied": denied, "retained_reference_company_denied": retained,
            "native_read_revocation_denied": True, "new_calculation_refused_revoked_source_without_snapshot": True, "separate_db_connections": True, "tx_isolation": isolation,
            "old_snapshot_observed_after_concurrent_commit": True, "receipt_replay_revocation_denied": True,
            "safe_serialization_conflict_before_fresh_denial": conflict}


def _observe_lock_order(callback):
    """Assert real effect boundaries share UOM -> Currency -> native order.

    UOM/Currency observations occur after the actual locking call completes;
    native observation occurs immediately before its locking verification begins.
    Controller validation repeats native verification without acquiring UOM locks.
    """
    from unittest.mock import patch
    from cipher_aec.estimating import sources, units
    events = []
    manifest, currency, native = units.manifest, units.currency_policy, sources.verify_native_rates
    def observed_manifest(*args, **kwargs):
        result = manifest(*args, **kwargs)
        assert kwargs.get("lock") is True
        events.append("UOM")
        return result
    def observed_currency(*args, **kwargs):
        result = currency(*args, **kwargs)
        assert kwargs.get("lock") is True
        events.append("Currency")
        return result
    def observed_native(*args, **kwargs):
        assert kwargs.get("lock") is True
        events.append("native Item/party")
        return native(*args, **kwargs)
    with patch.object(units, "manifest", side_effect=observed_manifest), patch.object(units, "currency_policy", side_effect=observed_currency), patch.object(sources, "verify_native_rates", side_effect=observed_native):
        result = callback()
    first_native = events.index("native Item/party")
    assert events.index("UOM") < first_native, events
    assert all(index < first_native for index, resource in enumerate(events) if resource in {"UOM", "Currency"}), events
    if "Currency" in events:
        assert events.index("UOM") < events.index("Currency"), events
    return result, events
