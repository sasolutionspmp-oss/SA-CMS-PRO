"""Opt-in Company PDF/calibration fixtures using the root-owned chain identities.

No implicit User/Auth provisioning, placeholder Project, model or provider.
Native Session and actual HTTP drivers are qualified separately by their caller.
"""
from copy import deepcopy
import base64
import hashlib
from uuid import uuid4


def prepare_fixture(private_manifest):
    import frappe
    from cipher_aec.governance.context import trusted_write
    from cipher_aec.estimating.company_service import register_unit
    from cipher_aec.tests.test_company_chain_acceptance import _load_fixture
    fixture = _load_fixture(private_manifest)
    marker = uuid4().hex[:12]
    before = frappe.db.count("Project")
    native = {}
    with trusted_write():
        for key in ("ft", "in", "sf", "cf"):
            native[key] = frappe.get_doc({"doctype": "UOM", "uom_name": "Company takeoff " + marker + " " + key, "symbol": key + marker, "enabled": 1, "must_be_whole_number": 0}).insert(ignore_permissions=True).name
    frappe.db.commit()
    units = {}
    for key, dimension in (("ft", "length"), ("in", "length"), ("sf", "area"), ("cf", "volume")):
        units[key] = register_unit(fixture["company"], str(uuid4()), native[key], dimension, 6)["unit"]["id"]
    frappe.db.commit()
    assert frappe.db.count("Project") == before
    return {"company": fixture["company"], "units": units, "native_units": native, "marker": marker,
            "project_count_unchanged": True, "existing_fixture_identities_reused": True}


def set_unit_enabled(private_manifest, unit_id, active):
    import frappe
    from cipher_aec.tests.test_company_chain_acceptance import _load_fixture
    _load_fixture(private_manifest)
    if type(active) is not int or active not in (0, 1):
        raise RuntimeError("An explicit fixture enabled flag is required")
    name = frappe.db.get_value("UOM", {"cipher_unit_id": unit_id}, "name")
    if not name or not name.startswith("Company takeoff "):
        raise RuntimeError("Only this isolated takeoff fixture's native unit may change")
    doc = frappe.get_doc("UOM", name)
    doc.enabled = active
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"unit_id": unit_id, "enabled": bool(active)}


def run_company_current_read_acceptance(private_manifest):
    """Separate committed DB writer versus an established old RR snapshot.

    Only a private synthetic Company scalar is temporarily changed by SQL; no
    controller/posting currency migration is claimed. Restore occurs in finally.
    """
    import threading
    import frappe
    from cipher_aec.tests.test_company_chain_acceptance import _load_fixture
    from cipher_aec.estimating import scopes, units
    from cipher_aec.governance.context import current_actor, require_company
    fixture = _load_fixture(private_manifest)
    company, site = fixture["company"], frappe.local.site
    frappe.db.commit()
    isolation = frappe.db.sql("SELECT @@tx_isolation")[0][0]
    assert isolation == "REPEATABLE-READ"
    before = frappe.db.sql("SELECT default_currency FROM `tabCompany` WHERE name=%s", (company,))[0][0]
    changed = "EUR" if before == "USD" else "USD"
    reader_id = frappe.db.sql("SELECT CONNECTION_ID()")[0][0]
    errors, writers = [], []
    def writer():
        try:
            frappe.init(site=site)
            frappe.connect()
            writers.append(frappe.db.sql("SELECT CONNECTION_ID()")[0][0])
            frappe.db.sql("UPDATE `tabCompany` SET default_currency=%s WHERE name=%s", (changed, company))
            frappe.db.commit()
        except BaseException as error:
            errors.append(type(error).__name__)
        finally:
            frappe.destroy()
    thread = threading.Thread(target=writer, daemon=True)
    try:
        thread.start()
        thread.join(20)
        assert not thread.is_alive() and not errors and writers[0] != reader_id
        assert frappe.db.sql("SELECT default_currency FROM `tabCompany` WHERE name=%s", (company,))[0][0] == before
        conflict = None
        with scopes.activate("Company", company, None):
            try:
                require_company(company, actor=current_actor(), lock=True)
            except frappe.QueryDeadlockError as error:
                # MariaDB innodb_snapshot_isolation can refuse promotion of an
                # old snapshot to a current lock with1020. This is fail-closed,
                # not evidence that an old-snapshot read returned current data.
                conflict = {"type": type(error).__name__, "native_code": 1020 if "1020" in str(error) else None}
                frappe.db.rollback()
                require_company(company, actor=current_actor(), lock=True)
            manifest = units.manifest(company, None, {fixture["qualified_unit"]["id"]}, [], lock=True, dataset_id=str(uuid4()))
        actual = next(row["fields"]["currency"] for row in manifest["records"] if row["kind"] == "company")
        assert actual == changed
        final_snapshot = frappe.db.sql("SELECT default_currency FROM `tabCompany` WHERE name=%s", (company,))[0][0]
        assert final_snapshot == (changed if conflict else before)
        return {"status": "passed", "qualification": "real-mariadb-separate-connection-old-RR-snapshot-current-read-or-fail-closed-and-fresh-transaction", "company": company,
                "isolation": isolation, "different_connection_ids": True, "ordinary_snapshot_currency": before, "locking_manifest_currency": actual,
                "old_snapshot_lock_conflict": conflict, "fresh_transaction_after_conflict": bool(conflict),
                "qualified_old_snapshot_current_read_return": conflict is None,
                "fixture_only_scalar_restored": True, "live_model_qualified": False, "external_provider_qualified": False}
    finally:
        frappe.db.rollback()
        thread.join(20)
        if thread.is_alive():
            raise RuntimeError("Fixture writer did not finish; stop before further fixture operations")
        frappe.db.sql("UPDATE `tabCompany` SET default_currency=%s WHERE name=%s", (before, company))
        frappe.db.commit()


def drive_company_takeoff(rpc, fixture, takeoff_fixture, *, pursuit_id=None, label="native"):
    """Finite known Company geometry, explicit independent grant and line evidence."""
    from cipher_aec.api.contracts import digest
    from cipher_aec.tests.test_takeoff_acceptance import pdf_fixture
    from cipher_aec.takeoff.geometry import FORMULA
    company, ids = fixture["company"], takeoff_fixture["units"]
    docs, est = "cipher_aec.documents.company_api.", "cipher_aec.estimating.company_api."
    take, gov = "cipher_aec.takeoff.company_api.", "cipher_aec.api.company_approvals."
    marker, journal, checks = uuid4().hex[:12], [], []
    def command(method, values):
        payload = {"company": company, "operation_id": str(uuid4()), **values}
        journal.append({"method": method, "payload": deepcopy(payload)})
        return payload, rpc.invoke(method, payload)
    rpc.login("author")
    content = pdf_fixture("Company actual stored known vector geometry " + marker)
    _, uploaded = command(docs + "upload_document", {"title": "Company known PDF " + marker, "filename": "company-known.pdf", "content_base64": base64.b64encode(content).decode(), "sha256": hashlib.sha256(content).hexdigest(), "byte_length": len(content)})
    citation = rpc.invoke(docs + "get_citation", {"company": company, "revision_id": uploaded["revision"]["id"], "page": 1})
    cite = {key: citation[key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")}
    source = {"revision_id": uploaded["revision"]["id"], "source_sha256": uploaded["revision"]["sha256"], "page": 1}
    _, created = command(take + "create_set", {"title": "Company takeoff " + marker, "discipline": "Explicit synthetic civil", "drawing_package": "Working PDF fixture", "basis": "Exact stored Company PDF user space; no screen pixels/model geometry"})
    takeoff_set = created["takeoff_set"]
    definition = {"title": "100 PDF units equal10 feet " + marker, "coordinate_system": "pdf-user-space-v1", "anchors": [["100", "100"], ["200", "100"]], "known_distance": {"amount": "10", "unit_id": ids["ft"], "precision": 6}, "relative_numeric_tolerance": "0.000000000001", "derived_units": [{"output_unit_id": ids[key], "power": power, "numerator": "1", "denominator": "1", "basis": "Explicit squared/cubed foot relation", "source_citations": [cite]} for key, power in (("sf", 2), ("cf", 3))], "basis": "Known synthetic vector drawing reference", "formula_version": FORMULA}
    _, calibration = command(take + "create_calibration", {"takeoff_set": takeoff_set["id"], "source": source, "definition": definition, "conversion_ids": []})
    calibration = calibration["calibration"]
    assert calibration["scope_type"] == "Company" and calibration["project"] is None
    assert calibration["page_geometry"]["media_box"] == ["0", "0", "612", "792"]
    _, request = command(gov + "request_action", {"action": "calibration.verify.v1", "subject_id": calibration["id"], "expected_version": digest(calibration)})
    packet = request["packet"]
    decision = {"company": company, "packet_id": packet["id"], "manifest_hash": packet["manifest_hash"], "decision": "Grant", "reason": "Independent Company PDF frame and known length review", "operation_id": str(uuid4())}
    rpc.login("alias")
    rpc.invoke(gov + "decide_packet", decision, expected_codes={"independent_calibration_required", "independent_review_required"})
    rpc.login("reviewer")
    decision["operation_id"] = str(uuid4())
    rpc.invoke(gov + "decide_packet", decision)
    rpc.login("author")
    execute, verified = command(gov + "execute_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"]})
    replay = rpc.invoke(gov + "execute_packet", execute)
    assert replay["operation"]["replayed"] and replay["effect"] == verified["effect"]
    measured_definition = {"method": "calibrated", "kind": "area", "locator": "PDF page1 rectangle100,100→300,200", "reason": "Known synthetic20ft by10ft", "result_unit_id": ids["sf"], "result_precision": 6, "tolerance": "0.000001", "waste_fraction": "0", "formula_version": FORMULA, "calibration_id": calibration["id"], "geometry": {"type": "rectangle", "points": [["100", "100"], ["300", "200"]]}, "depth": None}
    measure_args, measured = command(take + "create_measurement", {"takeoff_set": takeoff_set["id"], "source": source, "definition": measured_definition, "conversion_ids": []})
    measured = measured["measurement"]
    assert measured["result"]["quantity"] == {"amount": "200.000000", "unit_id": ids["sf"], "precision": 6}
    bad = deepcopy(measure_args)
    bad["operation_id"] = str(uuid4());bad["definition"]["geometry"]["points"][1][0] = "999999"
    rpc.invoke(take + "create_measurement", bad, expected_codes={"geometry_outside_page"})
    checks += ["actual_company_pdf_frame_server_derived", "independent_company_calibration_grant_one_effect_replay", "known_company_calibrated_area200_and_invalid_bounds_denied"]
    for role in ("outsider", "project_only"):
        rpc.login(role)
        rpc.invoke(take + "get_record", {"company": company, "kind": "measurement", "record_id": measured["id"]}, expected_codes={"capability_denied", "not_found"})
    rpc.login("author")
    rate = {"title": "Company geometric material " + marker, "cost_type": "material", "unit_id": ids["sf"], "rate_amount": "1.25", "rate_precision": 2, "currency": "USD", "quote_reference": "EXPLICIT-COMPANY-PDF-" + marker, "quote_date": "2026-10-01", "expiry_date": "2026-10-31", "geography": "Explicit synthetic", "inclusions": "Known synthetic material", "exclusions": "", "freight_tax_assumptions": "None in synthetic fixture", "permission_basis": "Authored synthetic PDF test content", "source_citations": [cite]}
    _, rate_value = command(est + "create_rate", {"rate": rate})
    _, estimate = command(est + "create_estimate", {"title": "Company calibrated estimate " + marker, "currency": "USD", "pricing_date": "2026-10-15", "pursuit_id": pursuit_id})
    line = {"line_id": str(uuid4()), "description": "Known Company rectangle", "quantity": measured["result"]["quantity"], "cost_code": "GEOM-01", "notes": "Subsequent takeoff evidence will be explicitly attached", "alternate": "", "included": True, "rate_source_id": rate_value["rate_source"]["id"], "material_factor": "1", "waste_fraction": "0"}
    _, calculated = command(est + "calculate_revision", {"estimate_id": estimate["estimate"]["id"], "expected_revision": None, "lines": [line], "adjustments": [], "conversion_ids": [], "basis_description": "Explicit Company geometry evidence attached after authored calculation", "basis_citations": [cite]})
    assert calculated["revision"]["total"]["amount"] == "250.00"
    bind_args, binding = command(take + "bind_line", {"measurement_id": measured["id"], "estimate_line_record": calculated["revision"]["line_record_ids"][0], "quantity_basis": "net-quantity-v1", "reason": "Attach exact known Company geometry without rewriting original snapshot"})
    binding = binding["binding"]
    assert binding["original_snapshot_claim"] == "authored-quantity-not-recomputed"
    checks.append("company_calibrated_line_exact250_and_immutable_subsequent_binding")
    return {"company": company, "label": label, "document": uploaded["document"], "source_revision": uploaded["revision"], "source": source, "citation": cite, "takeoff_set": takeoff_set, "calibration": calibration, "calibration_packet": packet, "measurement": measured, "binding": binding, "binding_payload": bind_args, "calculated": calculated, "rate": rate_value["rate_source"], "journal": journal, "checks": checks, "calibrated_company_takeoff_qualified": True, "live_model_qualified": False, "external_provider_qualified": False}


def run_native_acceptance(private_manifest, takeoff_fixture):
    """Real persistent Frappe services under explicitly synthetic Sessions."""
    from cipher_aec.tests.test_company_chain_acceptance import _load_fixture, NativeCompanyRPC
    fixture = _load_fixture(private_manifest)
    rpc = NativeCompanyRPC(fixture)
    try:
        value = drive_company_takeoff(rpc, fixture, takeoff_fixture, label="real-frappe-synthetic-session")
        value["calls"] = rpc.calls
        value["qualification"] = "real-Frappe-storage-explicit-synthetic-Session-fixture-not-HTTP"
        return value
    finally:
        rpc.close()


def drive_bound_acceptance(rpc, fixture, takeoff_fixture, run, *, mutate_unit):
    """Bound-only UOM eligibility, retained historical baseline, changed drawing."""
    from cipher_aec.api.contracts import digest
    from cipher_aec.tests.test_takeoff_acceptance import pdf_fixture
    company, gov = fixture["company"], "cipher_aec.api.company_approvals."
    est, docs, take = "cipher_aec.estimating.company_api.", "cipher_aec.documents.company_api.", "cipher_aec.takeoff.company_api."
    ids, checks, journal = takeoff_fixture["units"], [], []
    def command(method, values, expected=()):
        payload = {"company": company, "operation_id": str(uuid4()), **values}
        journal.append({"method": method, "payload": deepcopy(payload)})
        return payload, rpc.invoke(method, payload, expected_codes=expected)
    def grant(revision):
        rpc.login("author")
        _, result = command(gov + "request_action", {"action": "estimate.accept.v1", "subject_id": revision["id"], "expected_version": digest(revision)})
        packet = result["packet"]
        rpc.login("reviewer")
        command(gov + "decide_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"], "decision": "Grant", "reason": "Independent complete Company geometry and exact estimate review"})
        rpc.login("author")
        return packet
    packet = grant(run["calculated"]["revision"])
    facts = packet["review_manifest"]["effect"]["facts"]
    assert ids["ft"] in {row["id"] for row in facts["qualified_units"]}
    assert ids["cf"] in {row["id"] for row in facts["qualified_units"]}
    assert ids["ft"] not in {row["id"] for row in run["calculated"]["calculation"]["inputs"]["unit_manifest"]["records"]}
    execute = {"company": company, "packet_id": packet["id"], "manifest_hash": packet["manifest_hash"], "operation_id": str(uuid4())}
    journal.append({"method": gov + "execute_packet", "payload": deepcopy(execute)})
    try:
        mutate_unit(ids["ft"], 0)
        rpc.login("author")
        stale = rpc.invoke(gov + "read_packet", {"company": company, "packet_id": packet["id"]})
        assert stale["state"] == "Stale"
        rpc.invoke(gov + "execute_packet", execute, expected_codes={"approval_not_executable"})
        checks.append("calibration_only_disabled_unit_stales_pending_acceptance_without_effect")
    finally:
        mutate_unit(ids["ft"], 1)
        rpc.login("author")
    accepted = rpc.invoke(gov + "execute_packet", execute)
    baseline = accepted["effect"]["acceptance"]
    assert baseline["accepted_result"]["total"]["amount"] == "250.00"
    first_digest = digest(baseline)
    try:
        mutate_unit(ids["ft"], 0)
        rpc.login("author")
        old = rpc.invoke(est + "get_record", {"company": company, "kind": "acceptance", "record_id": baseline["id"]})
        replay = rpc.invoke(gov + "execute_packet", execute)
        assert digest(old) == first_digest and replay["operation"]["replayed"] and replay["effect"]["acceptance"] == baseline
        checks.append("disabled_original_geometry_unit_allows_authorized_historical_baseline_and_receipt")
    finally:
        mutate_unit(ids["ft"], 1)
        rpc.login("author")
    calc_args = next(row["payload"] for row in run["journal"] if row["method"] == est + "calculate_revision")
    revised_args = {key: deepcopy(value) for key, value in calc_args.items() if key not in ("company", "operation_id")}
    revised_args["expected_revision"] = run["calculated"]["revision"]["id"]
    _, successor = command(est + "calculate_revision", revised_args)
    _, new_binding = command(take + "bind_line", {"measurement_id": run["measurement"]["id"], "estimate_line_record": successor["revision"]["line_record_ids"][0], "quantity_basis": "net-quantity-v1", "reason": "Explicit successor line retains exact same original geometry evidence"})
    pending = grant(successor["revision"])
    content = pdf_fixture("Company actual drawing working revision2 known geometry")
    _, updated = command(docs + "upload_document", {"document_id": run["document"]["id"], "expected_revision": 1, "title": run["document"]["title"], "filename": "company-known-revision2.pdf", "content_base64": base64.b64encode(content).decode(), "sha256": hashlib.sha256(content).hexdigest(), "byte_length": len(content)})
    state = rpc.invoke(gov + "read_packet", {"company": company, "packet_id": pending["id"]})
    assert state["state"] == "Stale"
    command(gov + "execute_packet", {"packet_id": pending["id"], "manifest_hash": pending["manifest_hash"]}, expected={"approval_not_executable"})
    old = rpc.invoke(est + "get_record", {"company": company, "kind": "acceptance", "record_id": baseline["id"]})
    replay = rpc.invoke(gov + "execute_packet", execute)
    assert digest(old) == first_digest and replay["operation"]["replayed"]
    impact = rpc.invoke(take + "drawing_impact", {"company": company, "revision_id": run["source_revision"]["id"]})
    assert impact["new_use_requires_explicit_successor"] and impact["historical_results_changed"] is False
    affected = next(row for row in impact["measurements"] if row["measurement_id"] == run["measurement"]["id"])
    assert {row["id"] for row in affected["bound_lines"]} == {run["binding"]["id"], new_binding["binding"]["id"]}
    old_input = next(row["payload"] for row in run["journal"] if row["method"] == take + "create_measurement")
    invalid = deepcopy(old_input);invalid["operation_id"] = str(uuid4())
    rpc.invoke(take + "create_measurement", invalid, expected_codes={"stale_drawing"})
    checks += ["changed_attached_working_drawing_stales_independent_pending_acceptance", "drawing_impact_maps_exact_affected_stable_lines", "original_baseline_and_successful_receipt_unchanged_after_drawing_and_estimate_successor"]
    return {"checks": checks, "first_baseline": baseline, "first_baseline_digest": first_digest, "acceptance_execute_payload": execute,
            "first_packet": packet, "stale_packet": pending, "successor": successor, "working_revision2": updated["revision"], "drawing_impact": impact, "journal": journal,
            "native_unit_eligibility_restored": True, "original_operation_replayed_after_eligibility_restoration": True,
            "qualification": "real-Frappe-storage-explicit-synthetic-Sessions-not-HTTP", "live_model_qualified": False, "external_provider_qualified": False}


def continue_native_acceptance(private_manifest, takeoff_fixture, takeoff_result):
    import frappe
    from cipher_aec.tests.test_company_chain_acceptance import _load_fixture, NativeCompanyRPC
    fixture = _load_fixture(private_manifest)
    if takeoff_result["company"] != fixture["company"] or takeoff_fixture["company"] != fixture["company"]:
        raise RuntimeError("The fixture result has a different Company")
    rpc = NativeCompanyRPC(fixture)
    def mutate(unit_id, active):
        frappe.set_user("Administrator")
        set_unit_enabled(private_manifest, unit_id, active)
    try:
        result = drive_bound_acceptance(rpc, fixture, takeoff_fixture, takeoff_result, mutate_unit=mutate)
        result["calls"] = rpc.calls
        return result
    finally:
        rpc.close()


def run_pinned_successor_acceptance(private_manifest, takeoff_result, bound_result):
    """A later unused quote revision leaves explicitly selected pricing pinned."""
    from cipher_aec.tests.test_company_chain_acceptance import _load_fixture, NativeCompanyRPC
    from cipher_aec.api.contracts import digest
    fixture = _load_fixture(private_manifest)
    company, est, gov = fixture["company"], "cipher_aec.estimating.company_api.", "cipher_aec.api.company_approvals."
    rpc = NativeCompanyRPC(fixture)
    journal = []
    def command(method, values):
        payload = {"company": company, "operation_id": str(uuid4()), **values}
        journal.append({"method": method, "payload": deepcopy(payload)})
        return payload, rpc.invoke(method, payload)
    try:
        rpc.login("author")
        original = next(row["payload"] for row in takeoff_result["journal"] if row["method"] == est + "calculate_revision")
        args = {key: deepcopy(value) for key, value in original.items() if key not in ("company", "operation_id")}
        args["expected_revision"] = bound_result["successor"]["revision"]["id"]
        args["basis_description"] = "Explicit manually authored historical quantity for pinned-rate policy proof; no current calibrated evidence claimed or attached"
        _, calculated = command(est + "calculate_revision", args)
        _, requested = command(gov + "request_action", {"action": "estimate.accept.v1", "subject_id": calculated["revision"]["id"], "expected_version": digest(calculated["revision"])})
        packet = requested["packet"]
        assert packet["review_manifest"]["effect"]["facts"]["bindings"] == []
        rpc.login("reviewer")
        command(gov + "decide_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"], "decision": "Grant", "reason": "Independent exact pinned pricing review; explicitly manual quantity"})
        rpc.login("author")
        rate = deepcopy(next(row["payload"]["rate"] for row in takeoff_result["journal"] if row["method"] == est + "create_rate"))
        rate["rate_amount"] = "1.50"
        rate["quote_reference"] += "-UNSELECTED-SUCCESSOR"
        _, revised_rate = command(est + "create_rate", {"rate": rate, "predecessor": takeoff_result["rate"]["id"]})
        after = rpc.invoke(gov + "read_packet", {"company": company, "packet_id": packet["id"]})
        assert after["state"] == "Granted" and after["review_manifest"] == packet["review_manifest"]
        operation, accepted = command(gov + "execute_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"]})
        baseline = accepted["effect"]["acceptance"]
        assert baseline["total"]["amount"] == "250.00" and baseline["baseline_number"] == 2 and baseline["predecessor"] == bound_result["first_baseline"]["id"]
        assert baseline["manifest"]["effect"]["facts"]["pinned_records"][0]["id"] == takeoff_result["rate"]["id"]
        old = rpc.invoke(est + "get_record", {"company": company, "kind": "acceptance", "record_id": bound_result["first_baseline"]["id"]})
        assert digest(old) == bound_result["first_baseline_digest"]
        return {"status": "passed", "qualification": "real-Frappe-pinned-rate-successor-fixture-explicit-synthetic-Sessions-not-HTTP", "selected_rate_id": takeoff_result["rate"]["id"], "unselected_rate_successor_id": revised_rate["rate_source"]["id"],
                "before_manifest_digest": digest(packet["review_manifest"]), "after_manifest_digest": digest(after["review_manifest"]),
                "manifest_unchanged_after_unused_same_rate_family_successor": True, "pinned_accepted_total": "250.00", "new_unused_rate": "1.50", "selected_rate": "1.25",
                "new_manual_baseline": baseline, "original_geometry_baseline_preserved": True, "original_baseline_digest": digest(old),
                "manual_successor_has_no_calibrated_evidence_claim": True, "execute_payload": operation, "calls": rpc.calls, "journal": journal,
                "live_model_qualified": False, "external_provider_qualified": False}
    finally:
        rpc.close()
