"""Opt-in real Frappe/HTTP fixture setup; no shared passwords or project reset."""
from uuid import uuid4


def pdf_fixture(label="Explicit takeoff drawing revision1", rotation="0", user_unit="1"):
    """An actual vector PDF page: 200x100 user-space rectangle + embedded text."""
    if any(c in label for c in "()\\\r\n"):
        raise ValueError("Fixture label must be a plain PDF string")
    stream = ("BT /F1 12 Tf 72 740 Td (" + label + ") Tj 0 -20 Td (Known reference:100 PDF user units equal10 feet.) Tj 0 -20 Td (One squared/cubed foot maps to one square/cubic foot output.) Tj ET\n100 100 200 100 re S\n").encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Rotate " + rotation + " /UserUnit " + user_unit + " /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>").encode(),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream"]
    data = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(index).encode() + b" 0 obj\n" + value + b"\nendobj\n"
    start = len(data)
    data += ("xref\n0 6\n0000000000 65535 f \n" + "".join(f"{offset:010d} 00000 n \n" for offset in offsets[1:]) + "trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(start) + "\n%%EOF\n").encode()
    return data


def prepare_acceptance():
    import frappe
    from cipher_aec.governance.context import PROJECT_ABILITIES as ABILITIES, assert_synthetic_site, trusted_write
    from cipher_aec.estimating.service import register_unit
    from cipher_aec.install import _grant
    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise RuntimeError("The isolated takeoff fixture must be prepared through Administrator")
    company = "Cipher Synthetic Company"
    marker = uuid4().hex[:12]
    users = {"author": "morgan@cipher.example", "reviewer": "jordan@cipher.example", "administrator": "Administrator"}
    people = {key: frappe.db.get_value("Cipher Identity Binding", {"user": user, "active": 1}, "person") for key, user in users.items()}
    if not all(people.values()) or len(set(people.values())) != 3:
        raise RuntimeError("Seed the independent synthetic identities before isolated takeoff acceptance")
    with trusted_write():
        project = frappe.get_doc({"doctype": "Project", "company": company, "project_name": "EST02 isolated takeoff fixture " + marker, "status": "Open"}).insert(ignore_permissions=True)
        for subject in (people["author"], people["administrator"]):
            for ability in sorted(ABILITIES): _grant(subject, company, project.name, ability)
        for ability in ("project.read", "estimate.read", "document.read", "approval.decide"):
            _grant(people["reviewer"], company, project.name, ability)
        native = {}
        for key in ("ft", "in", "sf", "cf"):
            native[key] = frappe.get_doc({"doctype": "UOM", "uom_name": "EST02 fixture " + key + " " + marker, "symbol": key + marker, "enabled": 1, "must_be_whole_number": 0}).insert(ignore_permissions=True).name
    frappe.db.commit()
    units = {}
    for key, dimension in (("ft", "length"), ("in", "length"), ("sf", "area"), ("cf", "volume")):
        units[key] = register_unit(company, project.name, str(uuid4()), native[key], dimension, 6)["unit"]["id"]
    frappe.db.commit()
    return {"company": company, "project": project.name, "units": units, "label": "explicit-isolated-takeoff-fixture", "existing_users_reused_without_password_changes": True}


def run_parser_acceptance():
    from cipher_aec.api.errors import DomainError
    from cipher_aec.takeoff.pdf import page_geometry
    frame = page_geometry(pdf_fixture(), 1)
    assert frame["media_box"] == ["0", "0", "612", "792"]
    denied = []
    for options in ({"rotation": "90.5"}, {"user_unit": "2"}):
        try:
            page_geometry(pdf_fixture(**options), 1)
            raise AssertionError("Malformed/unsupported source metadata became a qualified PDF frame")
        except DomainError as error:
            assert error.code == "unsupported_drawing"
            denied.append(options)
    return {"status": "passed", "label": "actual-vector-pdf-fixture-parser", "frame": frame,
            "fractional_rotation_rejected_without_truncation": True, "unsupported_UserUnit_rejected": True}


def set_acceptance_source_access(project, active):
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site
    from cipher_aec.install import set_synthetic_duty
    assert_synthetic_site()
    if frappe.session.user != "Administrator" or type(active) is not int or active not in (0, 1):
        raise RuntimeError("Explicit synthetic administrator and boolean flag required")
    if not frappe.db.get_value("Project", project, "project_name").startswith("EST02 isolated takeoff fixture "):
        raise RuntimeError("Only this isolated takeoff fixture may change")
    result = set_synthetic_duty("morgan@cipher.example", project, "document.read", active)
    frappe.db.commit()
    return {"project": project, "document_read": active, "scope": "isolated-takeoff-project-only"}


def run_guard_acceptance(project, calibration_id, measurement_id, binding_id):
    from copy import deepcopy
    import frappe
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import assert_synthetic_site, current_actor, trusted_write
    from cipher_aec.takeoff import repository
    assert_synthetic_site()
    if frappe.session.user != "Administrator" or not frappe.db.get_value("Project", project, "project_name").startswith("EST02 isolated takeoff fixture "):
        raise RuntimeError("Only the isolated takeoff fixture administrator may run this guard proof")
    denied = []
    for kind, identifier in (("calibration", calibration_id), ("measurement", measurement_id), ("binding", binding_id)):
        assert repository.read(kind, identifier)["project"] == project
        try:
            frappe.get_doc(repository.DOCTYPES[kind], identifier).save(ignore_permissions=True)
            raise AssertionError("Generic takeoff mutation bypassed the governed controller")
        except DomainError as error:
            assert error.code == "governed_write_required"
            denied.append({"kind": kind, "code": error.code})
            frappe.db.rollback()
        try:
            with trusted_write():
                frappe.get_doc(repository.DOCTYPES[kind], identifier).save(ignore_permissions=True)
            raise AssertionError("A trusted generic save changed an immutable takeoff fact")
        except DomainError as error:
            assert error.code == "immutable_takeoff"
            denied.append({"kind": kind, "code": error.code})
            frappe.db.rollback()
    existing = repository.verification(calibration_id)
    assert existing
    fake = deepcopy(existing)
    fake.update(id=str(uuid4()), author_person=current_actor().person_id, author_user="Administrator")
    try:
        repository.insert("verification", fake, calibration=calibration_id, packet_id=fake["packet_id"], decision_id=fake["decision_id"], verified_by_person=fake["verified_by_person"])
        raise AssertionError("A generic trusted writer forged an approval-bound calibration verification")
    except DomainError as error:
        assert error.code == "approval_required"
        denied.append({"kind": "verification", "code": error.code})
        frappe.db.rollback()
    receipt = frappe.db.sql("SELECT operation_id FROM `tabCipher Command Receipt` WHERE project=%s AND command='takeoff.measurement.create.v1' AND JSON_UNQUOTE(JSON_EXTRACT(result_json,'$.measurement.id'))=%s LIMIT 1", (project, measurement_id))
    assert receipt
    return {"status": "passed", "project": project, "label": "real-frappe-takeoff-controller-and-exact-approval-context-guards", "denials": denied,
            "measurement_operation": receipt[0][0]}


def set_conversion_fixture_availability(project, revision_id, available):
    """Reversible actual-storage outage on this fixture's separate conversion file."""
    import os
    from pathlib import Path
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site
    from cipher_aec.documents.storage import FrappeFileStorage
    assert_synthetic_site()
    if frappe.session.user != "Administrator" or type(available) is not int or available not in (0, 1):
        raise RuntimeError("Explicit fixture administrator and boolean flag required")
    if not frappe.db.get_value("Project", project, "project_name").startswith("EST02 isolated takeoff fixture "):
        raise RuntimeError("Only this isolated takeoff project may simulate storage outage")
    revision = frappe.get_doc("Cipher Document Revision", revision_id)
    title = frappe.db.get_value("Cipher Document", revision.document, "title")
    if revision.project != project or not title.startswith("Separate measurement conversion fixture") or revision.mime_type != "text/plain":
        raise RuntimeError("Only the explicitly separate fixture conversion source may move")
    file = frappe.get_doc("File", revision.storage_reference)
    file.validate_file_path()
    file.validate_file_url()
    original = Path(file.get_full_path())
    staged = original.with_name(original.name + ".est02-unavailable")
    if available:
        if staged.exists(): os.replace(staged, original)
        FrappeFileStorage().read(revision.storage_reference, revision.sha256, revision.byte_length)
    else:
        if staged.exists(): raise RuntimeError("Fixture source already has a staged outage")
        FrappeFileStorage().read(revision.storage_reference, revision.sha256, revision.byte_length)
        os.replace(original, staged)
    return {"project": project, "revision_id": revision_id, "available": bool(available), "scope": "separate-conversion-fixture-bytes-only"}


def prove_approval_receipts(project, calibration_id):
    """Inspect only this isolated calibration's persisted packet/effect namespace."""
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site
    assert_synthetic_site()
    if frappe.session.user != "Administrator" or not frappe.db.get_value("Project", project, "project_name").startswith("EST02 isolated takeoff fixture "):
        raise RuntimeError("Only this isolated takeoff fixture may be inspected")
    packets = frappe.db.sql("SELECT name,source_version,manifest_hash,requester_person FROM `tabCipher Approval Packet` WHERE project=%s AND action='calibration.verify.v1' AND subject_id=%s", (project, calibration_id), as_dict=True)
    assert len(packets) == 1
    packet = packets[0]
    requests = frappe.db.sql("SELECT operation_id,request_hash FROM `tabCipher Command Receipt` WHERE person=%s AND project=%s AND command='approval.request_action' AND JSON_UNQUOTE(JSON_EXTRACT(result_json,'$.packet.subject.id'))=%s", (packet.requester_person, project, calibration_id))
    consumed = frappe.db.sql("SELECT operation_id FROM `tabCipher Approval Consumption` WHERE packet=%s", packet.name)
    count = frappe.db.count("Cipher Calibration Verification", {"calibration": calibration_id})
    assert len(requests) == 1 and len(consumed) == 1 and count == 1
    from cipher_aec.api.contracts import digest
    company = frappe.db.get_value("Project", project, "company")
    expected_hash = digest({"command": "approval.request_action", "company": company, "project": project,
                            "payload": {"action": "calibration.verify.v1", "subject_id": calibration_id, "expected_version": packet.source_version}})
    assert requests[0][1] == expected_hash
    return {"project": project, "calibration_id": calibration_id, "packet_id": packet.name, "manifest_hash": packet.manifest_hash,
            "source_version": packet.source_version, "request_operation_id": requests[0][0], "execution_operation_id": consumed[0][0],
            "packet_count": len(packets), "request_receipt_count": len(requests), "verification_count": count, "consumption_count": len(consumed),
            "request_hash": expected_hash, "canonical_person": packet.requester_person}


def run_acceptance():
    """Fresh-CI parser regression only; full HTTP/guard evidence is separate."""
    parser = run_parser_acceptance()
    return {"schema": "cipher.r1.est02-parser-acceptance.v1", "status": parser["status"],
            "label": "takeoff-parser-only-actual-pypdf-regression", "live_model_qualified": False, "live_provider_qualified": False,
            "qualification": "Parser-only PDF metadata regression; no fixture provisioning, calibration approval, takeoff persistence, HTTP or receipt qualification.",
            "parser": parser}
