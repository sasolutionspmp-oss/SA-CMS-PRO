"""Exact estimate acceptance through the static independent-human grant engine.

Priced library revisions remain pinned. Pending authority separately binds the
current estimate pointer, native facts and complete subsequently attached
measurement inventory. Historical accepted values never reprice themselves.
"""
from functools import wraps
from cipher_aec.estimating.lockplan import approval_union
from uuid import uuid4

import frappe

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from . import repository, scopes, service, sources, units

ACTION = "estimate.accept.v1"
PINNED_POLICY = "pinned-revision-at-pricing-date"
DRAWING_POLICY = "current-working-head-v1"
MANIFEST_POLICY = "cipher.estimate.acceptance-facts.v1"


def explicit_scope(function):
    @wraps(function)
    def wrapped(*args, scope_type="Project", **kwargs):
        with scopes.activate(scope_type, kwargs["company"], kwargs["project"]):
            return function(*args, **kwargs)
    return wrapped


def _citation_record(kind, record_id, company, project, actor, groups, *, lock):
    """Defer only this builder's explicit immutable citation-bearing records."""
    if kind not in {"revision", "snapshot", "rate", "assembly", "conversion"}:
        raise DomainError("approval_integrity", "This record is not an immutable priced source.", 409)
    value = service._scoped(kind, record_id, company, project, actor, lock=lock, verify=False, verify_links=False)
    groups.extend(sources.citation_groups(kind, value))
    return value


def _pinned(company, project, snapshot, actor, *, lock, citation_groups):
    records = []
    for kind, group in (("rate", snapshot["inputs"]["rates"]), ("assembly", snapshot["inputs"]["assemblies"])):
        if type(group) is not dict or len(group) > (500 if kind == "rate" else 100):
            raise DomainError("acceptance_limit", "Use the existing bounded priced source library.", 422)
        for name, expected in sorted(group.items()):
            value = _citation_record(kind, name, company, project, actor, citation_groups, lock=lock)
            if value["rate" if kind == "rate" else "assembly"] != expected:
                raise DomainError("estimate_integrity", "A priced source differs from its pinned immutable revision.", 409)
            records.append({"kind": kind, "id": name, "digest": digest(value)})
    conversions = snapshot["inputs"]["unit_manifest"]["unit_conversions"]
    if type(conversions) is not list or len(conversions) > 64:
        raise DomainError("acceptance_limit", "Use the existing bounded conversion library.", 422)
    for expected in sorted(conversions, key=lambda row: row["id"]):
        value = _citation_record("conversion", expected["id"], company, project, actor, citation_groups, lock=lock)
        if value["definition"] != expected:
            raise DomainError("estimate_integrity", "A selected conversion differs from its priced immutable revision.", 409)
        records.append({"kind": "conversion", "id": value["id"], "digest": digest(value)})
    return records


def _binding_rows(company, project, revision_id, *, lock):
    from cipher_aec.takeoff import repository as takeoffs
    where, args = scopes.current(company, project).where()
    rows = frappe.db.sql("SELECT name FROM `tabCipher Takeoff Line Binding` WHERE " + where + " AND estimate_revision=%s ORDER BY name LIMIT 201" + (" FOR UPDATE" if lock else ""), (*args, revision_id))
    if len(rows) > 200:
        raise DomainError("acceptance_limit", "The estimate exceeds the bounded binding inventory.", 422)
    return [takeoffs.read("binding", row[0], lock=lock) for row in rows]


def _facts(*, actor, company, project, subject_id, lock=False):
    from cipher_aec.takeoff import service as takeoff
    citation_groups = []
    revision = _citation_record("revision", subject_id, company, project, actor, citation_groups, lock=lock)
    master = service._scoped("estimate", revision["estimate"], company, project, actor, lock=lock, verify_links=False)
    snapshot = _citation_record("snapshot", revision["calculation_snapshot"], company, project, actor, citation_groups, lock=lock)
    pinned = _pinned(company, project, snapshot, actor, lock=lock, citation_groups=citation_groups)
    sources.verify_groups(company, project, citation_groups, actor, lock=lock)
    if master["current_revision"] != subject_id:
        raise DomainError("stale_estimate", "Accept the current explicitly calculated estimate revision.", 412)
    plan = sources.pursuit_plan(company, project, master.get("pursuit_id"), actor, lock=lock)
    bindings = _binding_rows(company, project, subject_id, lock=lock)
    # Discover immutable unit metadata without source/native authorization.
    # Project callbacks have no outer Company union, so eager binding/line
    # reads here would acquire native refs before a later geometry-only UOM.
    expected_units = {row["id"]: row for row in snapshot["inputs"]["unit_manifest"]["records"] if row["kind"] == "uom"}
    from cipher_aec.takeoff import repository as takeoffs
    for binding in bindings:
        if not scopes.current(company, project).matches(binding):
            raise DomainError("estimate_integrity", "A binding has a different exact scope.", 409)
        measured = takeoffs.read("measurement", binding["measurement_id"], lock=lock)
        dependencies = [measured]
        if measured["calibration_id"]:
            dependencies.append(takeoffs.read("calibration", measured["calibration_id"], lock=lock))
        for dependency in dependencies:
            if not scopes.current(company, project).matches(dependency):
                raise DomainError("estimate_integrity", "Bound geometry must preserve the exact estimate scope.", 409)
            for row in dependency["unit_manifest"]["records"]:
                if row["kind"] == "uom":
                    if row["id"] in expected_units and expected_units[row["id"]] != row:
                        raise DomainError("stale_unit", "Bound geometry and pricing disagree on qualified unit facts.", 412)
                    expected_units[row["id"]] = row
    if len(expected_units) > 200:
        raise DomainError("acceptance_limit", "The complete pricing/geometry unit union exceeds200 qualified units.", 422)
    unit_facts = [units.qualified(unit_id, lock=lock, actor=actor) for unit_id in sorted(expected_units)]
    if unit_facts != [expected_units[unit_id] for unit_id in sorted(expected_units)]:
        raise DomainError("stale_unit", "The priced qualified units changed. Calculate a successor explicitly.", 412)
    currency = units.currency_policy(revision["currency"], lock=lock, actor=actor)
    if currency["currency_exponent"] != snapshot["inputs"]["currency_exponent"]:
        raise DomainError("stale_currency", "The priced currency precision changed. Calculate a successor explicitly.", 412)
    native = sources.verify_native_rates(company, project, list(snapshot["inputs"]["rates"].values()), actor, lock=lock, pursuit_plans=[plan])
    binding_facts = []
    for binding in bindings:
        bundle = takeoff.verified_binding_bundle(binding["id"], company, project, actor, lock=lock)
        actual, measured, state = bundle["binding"], bundle["measurement"], bundle["current_use"]
        if actual != binding:
            raise DomainError("estimate_integrity", "The binding changed during exact dependency qualification.", 409)
        binding_facts.append({"id": actual["id"], "digest": digest(actual), "measurement_id": measured["id"], "measurement_digest": digest(measured), "current_use": state})
    facts = {"policy": MANIFEST_POLICY, "scope": scopes.current(company, project).manifest_scope(),
             "pricing_sources_policy": PINNED_POLICY, "drawing_calibration_policy": DRAWING_POLICY,
             "estimate": {"id": master["id"], "digest": digest(master), "current_revision": subject_id},
             "revision": {"id": subject_id, "digest": digest(revision)},
             "snapshot": {"id": snapshot["id"], "digest": digest(snapshot), "input_digest": snapshot["input_digest"], "output_digest": snapshot["output_digest"]},
             "rounding_policy": revision["policy_version"], "pinned_records": pinned, "qualified_units": unit_facts,
             "currency_policy": currency, "native_references": native, "pursuit": plan, "bindings": binding_facts}
    if scopes.current(company, project).scope_type == "Company":
        from .lockplan import revision_plan
        from cipher_aec.documents.provenance import node_manifest
        source_plan = revision_plan(company, actor, subject_id, current_bindings=True, lock=lock)
        if source_plan["generated_sources"]:
            facts["generated_sources"] = node_manifest(source_plan, actor, company, lock=lock)
    return revision, snapshot, facts


def _historical(*, actor, company, project, subject_id, manifest, lock=False, prelock_current=True):
    """Check stored originals and current rights; never require latest heads."""
    from cipher_aec.takeoff import service as takeoff
    facts = manifest.get("effect", {}).get("facts")
    if type(facts) is not dict or facts.get("policy") != MANIFEST_POLICY or facts.get("scope") != scopes.current(company, project).manifest_scope() or facts.get("revision", {}).get("id") != subject_id:
        raise DomainError("approval_integrity", "This estimate packet has a different exact scope or subject.", 409)
    citation_groups = []
    revision = _citation_record("revision", subject_id, company, project, actor, citation_groups, lock=lock)
    snapshot = _citation_record("snapshot", revision["calculation_snapshot"], company, project, actor, citation_groups, lock=lock)
    if digest(revision) != facts["revision"]["digest"] or digest(snapshot) != facts["snapshot"]["digest"]:
        raise DomainError("approval_integrity", "The original accepted estimate facts cannot be verified.", 409)
    if type(facts["pinned_records"]) is not list or len(facts["pinned_records"]) > 664:
        raise DomainError("acceptance_limit", "Use the existing bounded original priced source library.", 422)
    for ref in facts["pinned_records"]:
        if ref["kind"] not in {"rate", "assembly", "conversion"}:
            raise DomainError("approval_integrity", "Original pricing references must name an immutable priced library source.", 409)
        value = _citation_record(ref["kind"], ref["id"], company, project, actor, citation_groups, lock=lock)
        if digest(value) != ref["digest"]:
            raise DomainError("approval_integrity", "An original priced source cannot be verified.", 409)
    verify_original = sources._verify_original_groups if scopes.current(company, project).scope_type == "Company" else sources.verify_groups
    verify_original(company, project, citation_groups, actor, lock=lock)
    units.verify_manifest_access({"records": facts["qualified_units"]}, revision["currency"], actor)
    # Hold original and current Pursuit native refs together before nested reads.
    master = service._scoped("estimate", revision["estimate"], company, project, actor, lock=lock, verify_links=False)
    plan = sources.pursuit_plan(company, project, master.get("pursuit_id"), actor, lock=lock)
    # Historical authorization takes the same lock order while permitting
    # disabled historical unit/currency facts; no current-state equality here.
    if lock:
        # Central authorization precedes current-manifest reconstruction. Hold
        # the union of original AND current binding UOMs now, so a subsequently
        # attached calibration never introduces UOM locks after Currency/native.
        original_ids = {row["id"] for row in facts["qualified_units"]}
        all_ids = set(original_ids)
        from cipher_aec.takeoff import repository as takeoffs
        for binding in (_binding_rows(company, project, subject_id, lock=True) if prelock_current else []):
            measured = takeoffs.read("measurement", binding["measurement_id"], lock=True)
            dependencies = [measured]
            if measured["calibration_id"]:
                dependencies.append(takeoffs.read("calibration", measured["calibration_id"], lock=True))
            for dependency in dependencies:
                if not scopes.current(company, project).matches(dependency):
                    raise DomainError("approval_integrity", "A current binding has invalid scope lineage.", 409)
                all_ids.update(row["id"] for row in dependency["unit_manifest"]["records"] if row["kind"] == "uom")
        if len(all_ids) > 500:
            raise DomainError("acceptance_limit", "The original/current unit lock union exceeds its bounded scope.", 503)
        for unit_id in sorted(all_ids):
            if unit_id in original_ids:
                units.qualified(unit_id, lock=True, allow_disabled=True, actor=actor)
            else:
                # Internal discovery adds no public authorization requirement to
                # an old baseline; fresh use later checks every current unit.
                frappe.db.sql("SELECT name FROM `tabUOM` WHERE cipher_unit_id=%s FOR UPDATE", (unit_id,))
        frappe.db.sql("SELECT name FROM `tabCurrency` WHERE name=%s FOR UPDATE", (revision["currency"],))
    sources.verify_native_rates(company, project, list(snapshot["inputs"]["rates"].values()), actor, lock=lock,
                               pursuit_plans=[plan], extra_references=facts["native_references"])
    read_original = takeoff._read_original if scopes.current(company, project).scope_type == "Company" else takeoff._read
    for ref in facts["bindings"]:
        binding = read_original("binding", ref["id"], company, project, actor, lock=lock)
        measured = read_original("measurement", ref["measurement_id"], company, project, actor, lock=lock)
        if digest(binding) != ref["digest"] or digest(measured) != ref["measurement_digest"]:
            raise DomainError("approval_integrity", "An original takeoff binding cannot be verified.", 409)
    if scopes.current(company, project).scope_type == "Company":
        from .lockplan import revision_plan
        from cipher_aec.documents.provenance import node_manifest
        original_plan = revision_plan(company, actor, subject_id, manifest=manifest, current_bindings=False, lock=lock)
        actual_nodes = node_manifest(original_plan, actor, company, lock=lock) if original_plan["generated_sources"] else []
        if actual_nodes != facts.get("generated_sources", []):
            raise DomainError("approval_integrity", "The original generated-source closure cannot be verified.", 409)
    return revision


@explicit_scope
@approval_union("estimate")
def authorize_subject(*, actor, company, project, subject_id, phase, lock=False, manifest=None):
    scopes.require(company, project, ability="estimate.read", actor=actor, lock=lock)
    if phase in {"request", "execute"}:
        scopes.require(company, project, ability="estimate.write", actor=actor, lock=lock)
    revision = _historical(actor=actor, company=company, project=project, subject_id=subject_id, manifest=manifest, lock=lock, prelock_current=phase not in {"baseline", "receipt"}) if manifest is not None else service._scoped("revision", subject_id, company, project, actor, lock=lock, verify_links=False)
    if phase == "review" and actor.person_id == revision["author_person"]:
        raise DomainError("independent_estimate_required", "An estimate author cannot independently accept their own revision through another identity.", 403)
    return revision


@explicit_scope
@approval_union("estimate")
def approval_manifest(*, actor, company, project, subject_id, expected_version, lock=False):
    scopes.require(company, project, ability="estimate.read", actor=actor, lock=lock)
    revision, snapshot, facts = _facts(actor=actor, company=company, project=project, subject_id=subject_id, lock=lock)
    if expected_version != digest(revision):
        raise DomainError("stale_estimate", "Refresh this exact estimate revision before requesting acceptance.", 412)
    if repository.acceptance_for_revision(subject_id, lock=lock):
        raise DomainError("estimate_already_accepted", "This exact estimate revision already has an immutable accepted baseline.", 409)
    return {"subject": {"doctype": "Cipher Estimate Revision", "name": subject_id, "label": "Estimate revision " + str(revision["revision_number"])},
            "sources": snapshot["source_citations"],
            "effect": {"action": ACTION, "revision_id": subject_id, "facts": facts},
            "summary": {"total": revision["total"], "currency": revision["currency"], "rounding_policy": revision["policy_version"], "binding_count": len(facts["bindings"]), "independent_acceptance_required": True}}


@explicit_scope
@approval_union("estimate")
def apply_acceptance(*, actor, company, project, manifest, packet_id, decision_id, operation_id):
    subject_id = manifest["effect"]["revision_id"]
    scopes.approval_effect(action=ACTION, subject_id=subject_id, packet_id=packet_id)
    revision = authorize_subject(actor=actor, company=company, project=project, subject_id=subject_id, phase="execute", lock=True, manifest=manifest, scope_type=scopes.current(company, project).scope_type)
    expected = approval_manifest(actor=actor, company=company, project=project, subject_id=subject_id, expected_version=digest(revision), lock=True, scope_type=scopes.current(company, project).scope_type)
    if manifest != expected:
        raise DomainError("stale_estimate_acceptance", "The approved material estimate dependencies changed. Request fresh independent acceptance.", 412)
    decision = frappe.get_doc("Cipher Approval Decision", decision_id, for_update=True)
    if decision.packet != packet_id or decision.decision != "Grant" or decision.actor_person == revision["author_person"]:
        raise DomainError("independent_estimate_required", "Acceptance requires an independent canonical human's exact grant.", 403)
    previous = repository.latest_acceptance(revision["estimate"], lock=True)
    snapshot = repository.read("snapshot", revision["calculation_snapshot"], lock=True)
    value = service._new(company, project, actor, status="accepted", record_id=str(uuid4()), estimate=revision["estimate"],
                         estimate_revision=subject_id, calculation_snapshot=snapshot["id"], baseline_number=previous["baseline_number"] + 1 if previous else 1,
                         predecessor=previous["id"] if previous else None, packet_id=packet_id, decision_id=decision_id,
                         accepted_by_person=decision.actor_person, manifest=manifest, manifest_digest=digest(manifest),
                         accepted_result=snapshot["result"], currency=revision["currency"], total=revision["total"], source_citations=snapshot["source_citations"])
    repository.insert("acceptance", value, estimate=value["estimate"], estimate_revision=subject_id, calculation_snapshot=snapshot["id"], baseline_number=value["baseline_number"], predecessor=value["predecessor"], packet_id=packet_id, decision_id=decision_id, accepted_by_person=decision.actor_person, manifest_digest=value["manifest_digest"], currency=value["currency"], total_amount=value["total"]["amount"])
    service._event(actor, company, project, operation_id, "estimate.baseline.accepted", "acceptance", value)
    return {"acceptance": value}


@explicit_scope
@approval_union("estimate")
def approval_presentation(*, actor, company, project, subject_id, lock=False):
    """New outer packet presentation; never alters the original domain manifest."""
    revision = authorize_subject(actor=actor, company=company, project=project, subject_id=subject_id,
        phase="read", lock=lock, scope_type=scopes.current(company, project).scope_type)
    owner = repository.read("estimate", revision["estimate"], lock=lock)
    if not scopes.current(company, project).matches(owner):
        raise DomainError("not_found", "This estimate is not available.", 404)
    return {"estimate_title": owner["title"], "revision_number": revision["revision_number"]}
