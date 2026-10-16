"""Source-authorized immutable takeoff and subsequently attached line evidence."""
from datetime import datetime, timezone
from uuid import uuid4
from copy import deepcopy
from functools import partial
import re

import frappe
from cipher_aec.estimating.lockplan import receipt_union
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.estimating import service as estimates, sources, units
from cipher_aec.estimating.contracts import closed, identifier, visible
from cipher_aec.governance.context import current_actor
from cipher_aec.estimating.scopes import require as require_project
from cipher_aec.estimating import scopes
from cipher_aec.estimating.scopes import command as run_command
from cipher_aec.estimating.scopes import event as append_event
from cipher_aec.documents.service import source_reference

from . import geometry, pdf, repository

HEAD_POLICY = "current-working-revision-v1"


def _new(company, project, actor, *, record_id=None, status="authored", **values):
    return {**scopes.current(company, project).fields(), "id": record_id or str(uuid4()), "company": company, "project": project, "author_person": actor.person_id,
            "author_user": actor.user, "created_at": datetime.now(timezone.utc).isoformat(), "status": status, **values}


def _source(company, project, source, actor, *, lock=False, new_use=False, calibrated=False):
    return _read_source(company, project, source, actor, lock=lock, new_use=new_use, calibrated=calibrated,
                        mutation_admission=sources.require_raw_mutation_source)


def _source_original(company, project, source, actor, *, lock=False, calibrated=False):
    """Exact original drawing read; canonical rights/resources/bytes still apply."""
    return _read_source(company, project, source, actor, lock=lock, new_use=False, calibrated=calibrated,
                        mutation_admission=None)


def _read_source(company, project, source, actor, *, lock, new_use, calibrated, mutation_admission):
    closed(source, {"revision_id", "source_sha256", "page"}, path="source")
    visible(source["revision_id"], "source.revision_id", 140)
    if type(source["source_sha256"]) is not str or not re.fullmatch("[a-f0-9]{64}", source["source_sha256"]) or type(source["page"]) is not int or not 1 <= source["page"] <= 200:
        geometry.fail("Use the exact drawing SHA-256 and a supported integer page.", "source")
    if scopes.current(company, project).scope_type == "Company":
        from cipher_aec.documents.service import company_source_reference
        if lock and mutation_admission is not None:
            mutation_admission(company, source["revision_id"], actor)
        value = company_source_reference(company, source["revision_id"], source["page"], actor=actor, lock=lock)
    else:
        value = source_reference(company, project, source["revision_id"], source["page"], actor=actor, lock=lock)
    if value["source_sha256"] != source["source_sha256"]:
        raise DomainError("source_mismatch", "The drawing bytes do not match this exact measurement source.", 412)
    if new_use and not value["is_current"]:
        raise DomainError("stale_drawing", "The current working drawing changed. Create an explicit source-bound successor.", 412)
    content = value.pop("content")
    if calibrated and value["mime_type"] != "application/pdf":
        raise DomainError("unsupported_drawing", "Calibrated planar geometry requires actual stored PDF bytes.", 422)
    return value, content


def source_input(record):
    return {key: record["source"][key] for key in ("revision_id", "source_sha256", "page")}


def _verify_measurement_sources(value, actor, *, lock=False):
    return _measurement_sources(value, actor, lock=lock, conversion_reader=estimates._conversion_records, citation_verifier=sources.verify)


def _verify_original_measurement_sources(value, actor, *, lock=False):
    return _measurement_sources(value, actor, lock=lock, conversion_reader=estimates._conversion_original_records, citation_verifier=sources._verify_original)


def _measurement_sources(value, actor, *, lock, conversion_reader, citation_verifier):
    citations = value.get("source_citations")
    if citations is None:
        # Early synthetic draft records retain their immutable bodies. Resolve
        # their exact pinned conversion IDs under current source authority;
        # missing stored provenance never grants a source-permission bypass.
        conversions = conversion_reader(value["company"], value["project"], value["conversion_ids"], actor, lock=lock)
        citations = sources.merge(*(row["source_citations"] for row in conversions))
    if citations:
        citation_verifier(value["company"], value["project"], citations, actor, lock=lock)
    return citations


def _read(kind, record_id, company, project, actor, *, lock=False, new_use=False, _observations=None):
    return _read_record(kind, record_id, company, project, actor, lock=lock, new_use=new_use, observations=_observations,
                        drawing_reader=partial(_source, new_use=new_use), related_reader=partial(_read, new_use=new_use),
                        estimate_reader=estimates._scoped, citation_verifier=sources.verify, measurement_verifier=_verify_measurement_sources)


def _read_original(kind, record_id, company, project, actor, *, lock=False, _observations=None):
    """Private recursion for the exact bindings in an original acceptance fact.

    This contract never requests current-head eligibility or new-input admission.
    All ordinary record, source, calibration, unit and native authority checks
    run through the same implementations for the original actor and lock mode.
    """
    if scopes.current(company, project).scope_type != "Company" or kind not in {"binding", "measurement", "calibration", "verification"}:
        raise DomainError("approval_integrity", "This record is not an original acceptance takeoff dependency.", 409)
    return _read_record(kind, record_id, company, project, actor, lock=lock, new_use=False, observations=_observations,
                        drawing_reader=_source_original, related_reader=_read_original,
                        estimate_reader=estimates._scoped_original, citation_verifier=sources._verify_original, measurement_verifier=_verify_original_measurement_sources)


def _read_record(kind, record_id, company, project, actor, *, lock, new_use, observations,
                 drawing_reader, related_reader, estimate_reader, citation_verifier, measurement_verifier):
    require_project(company, project, ability="estimate.read", actor=actor, lock=lock)
    value = repository.read(kind, record_id, lock=lock)
    if not scopes.current(company, project).matches(value):
        raise DomainError("not_found", "This takeoff record is not available.", 404)
    if value.get("unit_manifest"):
        from cipher_aec.estimating.units import verify_manifest_access
        verify_manifest_access(value["unit_manifest"], None, actor)
    current, verified = None, None
    if kind in {"calibration", "measurement"}:
        current, _ = drawing_reader(company, project, source_input(value), actor, lock=lock, calibrated=kind == "calibration" or value["definition"]["method"] == "calibrated")
        if current["document_id"] != value["source"]["document_id"]:
            raise DomainError("source_mismatch", "The immutable drawing identity changed.", 409)
        if new_use and repository.latest(kind, value["family_id"], lock=lock) != value["id"]:
            raise DomainError("superseded_takeoff", "Use the current explicit takeoff revision.", 412)
        if kind == "calibration":
            citation_verifier(company, project, value["source_citations"], actor, lock=lock) if value["source_citations"] else None
        elif kind == "measurement":
            measurement_verifier(value, actor, lock=lock)
        if kind == "measurement" and value["definition"]["method"] == "calibrated":
            calibrated = related_reader("calibration", value["calibration_id"], company, project, actor, lock=lock, _observations=observations)
            verified = repository.verification(calibrated["id"], lock=lock)
            if not verified or verified["id"] != value["verification_id"] or verified["calibration_digest"] != digest(calibrated):
                raise DomainError("calibration_unverified", "This measurement requires its exact independent calibration verification.", 409)
    elif kind == "verification":
        related_reader("calibration", value["calibration_id"], company, project, actor, lock=lock, _observations=observations)
    elif kind == "binding":
        related_reader("measurement", value["measurement_id"], company, project, actor, lock=lock, _observations=observations)
        line = estimate_reader("line", value["estimate_line_record"], company, project, actor, lock=lock)
        if observations is not None:
            observations[("line", line["id"])] = {"record": line}
    # Observations only collect completed checks in this one recursive call.
    # They never short-circuit a read or escape the calling fact builder.
    if observations is not None:
        observations[(kind, value["id"])] = {"record": value, "source": current, "verification": verified}
    return value


def _event(actor, company, project, operation_id, kind, value):
    return append_event(actor=actor, company=company, project=project, operation_id=operation_id,
                        event="takeoff." + kind + ".authored", subject_type=repository.DOCTYPES[kind], subject_id=value["id"],
                        details={"record_digest": digest(value), "source_revision": value.get("source", {}).get("revision_id")})


def _command(company, project, operation_id, action, payload, effect):
    return run_command(company=company, project=project, operation_id=operation_id, command="takeoff." + action + ".v1", payload=payload,
                       ability="estimate.write", effect=effect)


def create_set(company, project, operation_id, title, discipline, drawing_package, basis):
    for key, value in (("title", title), ("discipline", discipline), ("drawing_package", drawing_package), ("basis", basis)):
        visible(value, key, 2000 if key == "basis" else 200)
    def effect(actor, project_doc):
        value = _new(company, project, actor, title=title, discipline=discipline, drawing_package=drawing_package,
                     basis=basis, supported_method="authored-manual-and-verified-pdf-planar-v1")
        repository.insert("set", value, title=title, discipline=discipline)
        return {"takeoff_set": value, "history_id": _event(actor, company, project, operation_id, "set", value)}
    return _command(company, project, operation_id, "set.create", {"title": title, "discipline": discipline, "drawing_package": drawing_package, "basis": basis}, effect)


def _previous(kind, predecessor, takeoff_set, company, project, actor):
    previous = _read(kind, predecessor, company, project, actor, lock=True) if predecessor else None
    if previous and (previous["takeoff_set"] != takeoff_set or repository.latest(kind, previous["family_id"], lock=True) != previous["id"]):
        raise DomainError("stale_takeoff", "Create a successor of the current immutable revision in this takeoff set.", 412)
    return previous


def create_calibration(company, project, operation_id, takeoff_set, source, definition, conversion_ids, predecessor=None):
    identifier(takeoff_set, "takeoff_set")
    if type(definition) is not dict:
        geometry.fail("Supply a closed calibration definition.")
    def effect(actor, project_doc):
        _read("set", takeoff_set, company, project, actor, lock=True)
        previous = _previous("calibration", predecessor, takeoff_set, company, project, actor)
        record_id = str(uuid4())
        actual, content = _source(company, project, source, actor, lock=True, new_use=True, calibrated=True)
        frame = pdf.page_geometry(content, actual["page"])
        authored = deepcopy(definition)
        if type(authored.get("derived_units")) is not list or len(authored["derived_units"]) > 16:
            geometry.fail("Use up to 16 explicit reviewed derived unit relations.")
        citations = []
        for relation in authored.get("derived_units", []):
            if type(relation) is not dict or "source_citations" not in relation:
                geometry.fail("A derived transform requires its explicit source citations.")
            relation["source_citations"] = sources.resolve(company, project, relation["source_citations"], actor, lock=True)
            citations.extend(relation["source_citations"])
        try:
            unit_ids = {authored["known_distance"]["unit_id"], *(row["output_unit_id"] for row in authored["derived_units"])}
        except (KeyError, TypeError):
            geometry.fail("A calibration requires explicit qualified reference/output units.")
        conversions = estimates._conversion_records(company, project, conversion_ids, actor)
        citations = sources.merge(citations, *(row["source_citations"] for row in conversions))
        manifest = units.manifest(company, project, unit_ids, conversions, lock=True, dataset_id=record_id)
        geometry.calibration(authored, manifest, frame)
        value = _new(company, project, actor, record_id=record_id, status="unverified", takeoff_set=takeoff_set,
                     family_id=previous["family_id"] if previous else str(uuid4()), revision_number=previous["revision_number"] + 1 if previous else 1,
                     predecessor=predecessor, definition=authored, source=actual, source_head_policy=HEAD_POLICY,
                     page_geometry=frame, unit_manifest=manifest, conversion_ids=conversion_ids, source_citations=citations)
        repository.insert("calibration", value, takeoff_set=takeoff_set, family_id=value["family_id"], revision_number=value["revision_number"], predecessor=predecessor,
                          source_revision=actual["revision_id"], source_sha256=actual["source_sha256"], page=actual["page"])
        return {"calibration": value, "history_id": _event(actor, company, project, operation_id, "calibration", value)}
    return _command(company, project, operation_id, "calibration.create", {"takeoff_set": takeoff_set, "source": source, "definition": definition, "conversion_ids": conversion_ids, "predecessor": predecessor}, effect)


def create_measurement(company, project, operation_id, takeoff_set, source, definition, conversion_ids, predecessor=None):
    identifier(takeoff_set, "takeoff_set")
    if type(definition) is not dict or definition.get("method") not in ("manual", "calibrated"):
        geometry.fail("Choose an explicit manual or calibrated measurement.")
    if type(conversion_ids) is not list or len(conversion_ids) > 64:
        geometry.fail("Use up to 64 distinct conversion revision IDs.")
    for value in conversion_ids:
        identifier(value, "conversion_ids[]")
    if len(set(conversion_ids)) != len(conversion_ids):
        geometry.fail("Conversion revision IDs must be distinct.")
    def effect(actor, project_doc):
        _read("set", takeoff_set, company, project, actor, lock=True)
        previous = _previous("measurement", predecessor, takeoff_set, company, project, actor)
        calibrated = definition["method"] == "calibrated"
        actual, content = _source(company, project, source, actor, lock=True, new_use=True, calibrated=calibrated)
        cal, verified, frame = None, None, None
        ids = set(conversion_ids) if type(conversion_ids) is list else set()
        if calibrated:
            cal = _read("calibration", definition.get("calibration_id"), company, project, actor, lock=True, new_use=True)
            if source_input(cal) != source:
                raise DomainError("calibration_source_mismatch", "Calibration and measurement must use the exact same drawing bytes and page.", 412)
            verified = repository.verification(cal["id"], lock=True)
            if not verified or verified["calibration_digest"] != digest(cal):
                raise DomainError("calibration_unverified", "An independent human must verify this exact calibration before geometric use.", 409)
            frame = pdf.page_geometry(content, actual["page"])
            if frame != cal["page_geometry"]:
                raise DomainError("calibration_source_mismatch", "The derived PDF page frame differs from the verified calibration.", 412)
            ids.update(cal["conversion_ids"])
        record_id = str(uuid4())
        try:
            unit_ids = {definition["result_unit_id"]}
            if cal:
                unit_ids.update(row["id"] for row in cal["unit_manifest"]["records"] if row["kind"] == "uom")
            if definition.get("depth"):
                unit_ids.add(definition["depth"]["unit_id"])
        except (KeyError, TypeError):
            geometry.fail("A measurement requires explicitly qualified output/depth units.")
        conversions = estimates._conversion_records(company, project, sorted(ids), actor)
        manifest = units.manifest(company, project, unit_ids, conversions, lock=True, dataset_id=record_id)
        result = geometry.measurement(definition, manifest, cal["definition"] if cal else None, frame)
        citations = sources.merge(cal["source_citations"] if cal else [], *(row["source_citations"] for row in conversions))
        value = _new(company, project, actor, record_id=record_id, takeoff_set=takeoff_set,
                     family_id=previous["family_id"] if previous else str(uuid4()), revision_number=previous["revision_number"] + 1 if previous else 1,
                     predecessor=predecessor, source=actual, source_head_policy=HEAD_POLICY, definition=deepcopy(definition),
                     calibration_id=cal["id"] if cal else None, calibration_digest=digest(cal) if cal else None,
                     verification_id=verified["id"] if verified else None, page_geometry=frame, unit_manifest=manifest,
                     conversion_ids=sorted(ids), source_citations=citations, result=result)
        repository.insert("measurement", value, takeoff_set=takeoff_set, family_id=value["family_id"], revision_number=value["revision_number"], predecessor=predecessor,
                          source_revision=actual["revision_id"], source_sha256=actual["source_sha256"], page=actual["page"],
                          method=definition["method"], calibration=cal["id"] if cal else None, unit=result["quantity"]["unit_id"], quantity_amount=result["quantity"]["amount"])
        return {"measurement": value, "history_id": _event(actor, company, project, operation_id, "measurement", value)}
    return _command(company, project, operation_id, "measurement.create", {"takeoff_set": takeoff_set, "source": source, "definition": definition, "conversion_ids": conversion_ids, "predecessor": predecessor}, effect)


def _binding_basis(company, project, measurement_id, estimate_line_record, quantity_basis, actor, *, lock=False):
    measured = _read("measurement", measurement_id, company, project, actor, lock=lock, new_use=True)
    line = estimates._scoped("line", estimate_line_record, company, project, actor, lock=lock)
    _validate_binding_basis(measured, line, quantity_basis)
    return measured, line


def _validate_binding_basis(measured, line, quantity_basis):
    selected, authored = measured["result"]["quantity"], line["authored"]["quantity"]
    if selected["unit_id"] != authored["unit_id"] or selected["precision"] != authored["precision"] or geometry.exact(selected["amount"], "measurement.quantity.amount", precision=selected["precision"]) != geometry.exact(authored["amount"], "line.quantity.amount", precision=authored["precision"]):
        raise DomainError("quantity_mismatch", "The saved authored line must exactly match the selected measurement quantity, unit and precision.", 412)
    has_waste = geometry.exact(measured["definition"]["waste_fraction"], "measurement.waste_fraction") > 0
    expected_basis = "after-takeoff-waste-v1" if has_waste else "net-quantity-v1"
    if quantity_basis != expected_basis:
        raise DomainError("quantity_basis_mismatch", "Explicitly select the exact net or after-takeoff-waste quantity basis.", 422)
    if has_waste and any(int(row["waste_fraction"]["numerator"]) for row in line["calculated"]["components"]):
        raise DomainError("ambiguous_double_waste", "A takeoff allowance cannot be combined with estimate component waste in this binding policy.", 422)


def verified_binding_bundle(binding_id, company, project, actor, *, lock=False):
    """One fresh binding traversal for a single current acceptance builder.

    The caller first discovers metadata and acquires its complete master union.
    This function rechecks all exact source bytes, heads, native permissions,
    calibration verification and estimate-line basis once. No result is cached
    or reused by a later builder, actor, transaction or public read.
    """
    observed = {}
    binding = _read("binding", binding_id, company, project, actor, lock=lock, new_use=True, _observations=observed)
    measurement_observation = observed[("measurement", binding["measurement_id"])]
    measured = measurement_observation["record"]
    line = observed[("line", binding["estimate_line_record"])]["record"]
    _validate_binding_basis(measured, line, binding["quantity_basis"])
    if (binding["measurement_digest"] != digest(measured) or binding["estimate_line_digest"] != digest(line)
            or binding["quantity"] != measured["result"]["quantity"] or binding["estimate_revision"] != line["estimate_revision"]
            or binding["estimate"] != line["estimate"] or binding["line_id"] != line["line_id"]
            or binding["provenance"] != "subsequently-attached-takeoff-evidence-v1"
            or binding["original_snapshot_claim"] != "authored-quantity-not-recomputed"):
        raise DomainError("takeoff_integrity", "The binding must preserve its exact authorized measurement and estimate-line basis.", 409)
    calibrated = observed[("calibration", measured["calibration_id"])]["record"] if measured["calibration_id"] else None
    verified = measurement_observation["verification"]
    current = measurement_observation["source"]
    # new_use=True already refused any changed drawing/takeoff/calibration head
    # and checked the exact verification. Derive the unchanged public DTO from
    # those completed checks instead of traversing the same sources again.
    state = {"eligible": True, "reasons": [], "current_working_revision": current["current_revision"], "head_policy": HEAD_POLICY,
             "original_record_preserved": True, "verification": {"id": verified["id"], "verified_by_person": verified["verified_by_person"]} if verified else None}
    return {"binding": binding, "measurement": measured, "calibration": calibrated, "current_use": state}


def bind_line(company, project, operation_id, measurement_id, estimate_line_record, quantity_basis, reason):
    visible(reason, "reason", 2000)
    def effect(actor, project_doc):
        measured, line = _binding_basis(company, project, measurement_id, estimate_line_record, quantity_basis, actor, lock=True)
        existing = frappe.db.sql("SELECT name FROM `tabCipher Takeoff Line Binding` WHERE estimate_revision=%s AND line_id=%s FOR UPDATE", (line["estimate_revision"], line["line_id"]))
        if existing:
            raise DomainError("line_basis_exists", "This immutable estimate line already has its one takeoff evidence basis.", 409)
        value = _new(company, project, actor, measurement_id=measured["id"], measurement_digest=digest(measured),
                     estimate_line_record=line["id"], estimate=line["estimate"], estimate_revision=line["estimate_revision"], line_id=line["line_id"],
                     estimate_line_digest=digest(line), quantity=measured["result"]["quantity"], reason=reason, quantity_basis=quantity_basis,
                     waste_policy="takeoff-waste-only-v1" if quantity_basis == "after-takeoff-waste-v1" else "net-takeoff-estimate-component-waste-v1",
                     provenance="subsequently-attached-takeoff-evidence-v1", original_snapshot_claim="authored-quantity-not-recomputed")
        repository.insert("binding", value, measurement=measured["id"], estimate=line["estimate"], estimate_revision=line["estimate_revision"],
                          estimate_line_record=line["id"], line_id=line["line_id"])
        return {"binding": value, "history_id": _event(actor, company, project, operation_id, "binding", value)}
    return _command(company, project, operation_id, "line.bind", {"measurement_id": measurement_id, "estimate_line_record": estimate_line_record, "quantity_basis": quantity_basis, "reason": reason}, effect)


def current_use(value, actor, *, lock=False):
    current, _ = _source(value["company"], value["project"], source_input(value), actor, lock=lock)
    kind = "measurement" if "result" in value else "calibration"
    reasons = []
    verified = None
    if not current["is_current"]:
        reasons.append("drawing_working_revision_changed")
    if repository.latest(kind, value["family_id"], lock=lock) != value["id"]:
        reasons.append("takeoff_revision_superseded")
    if kind == "calibration" or value["definition"]["method"] == "calibrated":
        calibration_id = value["id"] if kind == "calibration" else value["calibration_id"]
        calibrated = value if kind == "calibration" else _read("calibration", calibration_id, value["company"], value["project"], actor, lock=lock)
        if repository.latest("calibration", calibrated["family_id"], lock=lock) != calibrated["id"]:
            reasons.append("calibration_revision_superseded")
        verified = repository.verification(calibration_id, lock=lock)
        if not verified:
            reasons.append("calibration_unverified")
    return {"eligible": not reasons, "reasons": reasons, "current_working_revision": current["current_revision"], "head_policy": HEAD_POLICY,
            "original_record_preserved": True, "verification": {"id": verified["id"], "verified_by_person": verified["verified_by_person"]} if verified else None}


def get_record(company, project, kind, record_id):
    if type(kind) is not str or kind not in repository.DOCTYPES:
        geometry.fail("This takeoff record kind is unsupported.", "kind")
    actor = current_actor()
    value = _read(kind, record_id, company, project, actor)
    return {"record": value, "record_digest": digest(value), **({"current_use": current_use(value, actor)} if kind in {"calibration", "measurement"} else {})}


def list_records(company, project, kind, takeoff_set=None, limit=20, cursor=None, count_mode="none"):
    from cipher_aec.api.paging import decode_cursor, page_options, page_result, signing_secret
    from cipher_aec.governance.context import authority_fingerprint
    if type(kind) is not str or kind not in {"set", "calibration", "measurement", "binding"}:
        geometry.fail("This takeoff catalog kind is unsupported.", "kind")
    actor = current_actor()
    require_project(company, project, ability="estimate.read", actor=actor)
    require_project(company, project, ability="document.read", actor=actor)
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    scope = {"route": "takeoff.catalog", "kind": kind, "takeoff_set": takeoff_set, "user": actor.user, "person": actor.person_id,
             "company": company, "project": project, "authority": scopes.current(company, project).authority(actor), **scopes.current(company, project).fields()}
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    where, args = scopes.current(company, project).where()
    if takeoff_set:
        if kind not in {"calibration", "measurement"}:
            geometry.fail("Only calibration/measurement catalogs filter by takeoff set.")
        _read("set", takeoff_set, company, project, actor)
        where += " AND takeoff_set=%s"
        args.append(takeoff_set)
    base_where, base_args = where, list(args)
    candidates = frappe.db.sql(f"SELECT name FROM `tab{repository.DOCTYPES[kind]}` WHERE " + base_where + " ORDER BY name LIMIT 501", base_args)
    if len(candidates) > 500:
        raise DomainError("catalog_scope_limit", "This catalog exceeds the bounded authorization scope.", 503)
    for candidate in candidates:
        _read(kind, candidate[0], company, project, actor)
    if last:
        where += " AND (creation<%s OR (creation=%s AND name<%s))"
        args.extend((last[0], last[0], last[1]))
    rows = frappe.db.sql(f"SELECT name,creation FROM `tab{repository.DOCTYPES[kind]}` WHERE " + where + " ORDER BY creation DESC,name DESC LIMIT %s", (*args, limit + 1), as_dict=True)
    page = rows[:limit]
    items = [get_record(company, project, kind, row.name) for row in page]
    total = frappe.db.sql(f"SELECT COUNT(*) FROM `tab{repository.DOCTYPES[kind]}` WHERE " + base_where, base_args)[0][0] if count_mode == "exact" else None
    return page_result(items, has_more=len(rows) > limit, last=[str(page[-1].creation), page[-1].name] if page else None,
                       scope=scope, limit=limit, count_mode=count_mode, total=total)


def drawing_impact(company, project, revision_id):
    visible(revision_id, "revision_id", 140)
    actor = current_actor()
    require_project(company, project, ability="estimate.read", actor=actor)
    if scopes.current(company, project).scope_type == "Company":
        from cipher_aec.documents.service import company_source_reference
        reference = company_source_reference(company, revision_id, 1, actor=actor)
    else:
        reference = source_reference(company, project, revision_id, 1, actor=actor)
    where, arguments = scopes.current(company, project).where()
    rows = frappe.db.sql("SELECT name FROM `tabCipher Takeoff Measurement` WHERE " + where + " AND source_revision=%s ORDER BY name LIMIT 201", (*arguments, revision_id))
    if len(rows) > 200:
        geometry.fail("Drawing impact exceeds the bounded 200-measurement scope.", code="impact_limit")
    affected = []
    for row in rows:
        measured = _read("measurement", row[0], company, project, actor)
        eligibility = current_use(measured, actor)
        bindings = frappe.db.sql("SELECT name FROM `tabCipher Takeoff Line Binding` WHERE measurement=%s ORDER BY name LIMIT 201", (measured["id"],))
        if len(bindings) > 200:
            geometry.fail("Measurement impact exceeds the bounded 200-line scope.", code="impact_limit")
        attached = [_read("binding", item[0], company, project, actor) for item in bindings]
        affected.append({"measurement_id": measured["id"], "measurement_digest": digest(measured), "current_use": eligibility,
                         "bound_lines": [{key: item[key] for key in ("id", "estimate", "estimate_revision", "line_id", "estimate_line_record")} for item in attached]})
    reference.pop("content")
    return {"source": reference, "measurements": affected, "new_use_requires_explicit_successor": not reference["is_current"],
            "historical_results_changed": False, "head_policy": HEAD_POLICY}


def compare_measurements(company, project, before_id, after_id):
    actor = current_actor()
    before = _read("measurement", before_id, company, project, actor)
    after = _read("measurement", after_id, company, project, actor)
    if before["family_id"] != after["family_id"]:
        geometry.fail("Compare explicit revisions of the same stable measurement family.")
    return {"family_id": before["family_id"], "before": {"id": before_id, "digest": digest(before), "quantity": before["result"]["quantity"], "source": before["source"]},
            "after": {"id": after_id, "digest": digest(after), "quantity": after["result"]["quantity"], "source": after["source"]},
            "changed": {"source": source_input(before) != source_input(after), "quantity": before["result"]["quantity"] != after["result"]["quantity"],
                        "geometry_or_manual_inputs": before["definition"] != after["definition"], "calibration": before["calibration_id"] != after["calibration_id"]},
            "original_records_preserved": True}


@receipt_union
def authorize_receipt(actor, company, project, result, scope_type="Project"):
    with scopes.activate(scope_type, company, project):
        require_project(company, project, ability="estimate.read", actor=actor, lock=True)
        for key, kind in (("takeoff_set", "set"), ("calibration", "calibration"), ("measurement", "measurement"), ("verification", "verification"), ("binding", "binding")):
            if key in result:
                _read(kind, result[key]["id"], company, project, actor, lock=True)
