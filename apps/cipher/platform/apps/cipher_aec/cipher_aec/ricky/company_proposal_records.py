"""Company proposal-only row invariants on the existing native six tables."""
import json

from .company_contracts import CompanyAuthority, decode_authority, decode_run_authority
from .company_proposal_contracts import (PROPOSAL_KIND, PROPOSAL_SCHEMA, METHODS, DeterministicProposalRequest,
    closed, fail, validate_manifest, validate_resource_plan, validate_preparation)
from .company_records import initial_run_admission
from .contracts import RickyError, canonical, digest
from .engine import ACTIVE, FINAL


def validate_run_state(value):
    status = value.get("status")
    if (type(status) is not str or status not in {*ACTIVE, "waiting-for-review", "failed", "cancelled"}
            or type(value.get("cancel_requested")) is not bool or value["cancel_requested"] != (status == "cancelled")):
        fail("The Company proposal run standing is inconsistent.")
    if status == "waiting-for-review":
        if value.get("result") is None or value.get("result_digest") is None or value.get("error") is not None:
            fail("A reviewable run requires its exact persisted suggestion reference.")
    elif value.get("result") is not None or value.get("result_digest") is not None or value.get("proposal_ids"):
        fail("An unfinished or refused run cannot expose a persisted suggestion.")
    if status in FINAL:
        if type(value.get("completed_at")) is not str or not value["completed_at"]:
            fail("A terminal proposal run requires its completion time.")
    elif value.get("completed_at") is not None:
        fail("An active preparation cannot have a completion time.")


def invocation_key(run):
    request = DeterministicProposalRequest.from_value(run["request"])
    return digest({"run": run["id"], "logical_call": "proposal", "tool": request.action,
        "arguments": json.loads(request.arguments_json)})


def preparation_originals(run):
    """Controller integrity reads only; never replaces canonical authorization."""
    from cipher_aec.estimating import repository as estimates
    from cipher_aec.takeoff import repository as takeoffs
    return {(row["domain"], row["kind"], row["id"]): (estimates if row["domain"] == "estimate" else takeoffs).read(row["kind"], row["id"])
        for row in run["original_manifest"]["records"] if row["domain"] in {"estimate", "takeoff"}}


def successful_invocation(store, run, *, originals=None, require_citations=False):
    request = DeterministicProposalRequest.from_value(run["request"])
    key = invocation_key(run)
    rows = store.find("invocation", {"operation_key": key}, limit=2)
    if len(rows) != 1:
        raise RickyError("incomplete_preparation", "The exact successful draft invocation is unavailable.")
    invocation = rows[0]
    step = store.get("step", invocation["step_id"])
    for row in (invocation, step):
        if (row["status"] != "succeeded" or row["operation_key"] != key or row["tool_name"] != request.action
                or row["tool_version"] != "1" or row["input_digest"] != digest(json.loads(request.arguments_json))
                or any(row.get(field) != run.get(field) for field in
                    ("run_id", "scope_type", "company", "project", "user", "person", "authority", "request_kind", "delegation_id"))):
            fail("The successful preparation has different original linkage.")
    if (digest(invocation["output"]) != invocation["output_digest"] or step["output_digest"] != invocation["output_digest"]
            or step["id"] != invocation["step_id"]):
        fail("The successful draft observation changed.")
    validate_preparation(run, invocation["output"], originals=preparation_originals(run) if originals is None else originals,
        require_citations=require_citations)
    return invocation


def validate_proposal(value, run, store):
    fields = {"id", "scope_type", "project", "company", "user", "person", "run_id", "authority", "request_kind", "created_at",
        "schema", "status", "version", "persistent", "action", "action_version", "kind", "delegation_id", "step_id", "invocation_id", "operation_key",
        "selection_digest", "prepared_manifest_digest", "resource_plan_digest", "preparation_digest", "draft_digest", "preparation", "source_manifest",
        "expires_at", "review_required", "claim_classification", "content_digest"}
    closed(value, fields)
    request = DeterministicProposalRequest.from_value(run["request"])
    invocation = successful_invocation(store, run)
    expected = {"schema": PROPOSAL_SCHEMA, "status": "proposed", "version": 1, "persistent": True,
        "action": request.action, "action_version": "1", "kind": METHODS[request.action][2], "delegation_id": run["delegation_id"],
        "step_id": invocation["step_id"], "invocation_id": invocation["id"], "operation_key": invocation["operation_key"],
        "selection_digest": request.selection_digest(), "prepared_manifest_digest": run["original_manifest_digest"],
        "resource_plan_digest": run["resource_plan_digest"], "preparation_digest": invocation["output_digest"],
        "draft_digest": invocation["output"]["draft_digest"], "preparation": invocation["output"], "source_manifest": run["original_manifest"],
        "expires_at": run["deadline"], "review_required": True, "claim_classification": "unverified-author-suggestion"}
    if any(type(value[key]) is not type(item) or canonical(value[key]) != canonical(item) for key, item in expected.items()):
        fail("The stored suggestion differs from its actual successful preparation.")
    if not run["original_manifest"]["action_complete"] or value["content_digest"] != digest({key: item for key, item in value.items() if key != "content_digest"}):
        fail("The completed proposal content cannot be verified.")


def validate_company_proposal_record(kind, value, store, *, before=None):
    authority = decode_run_authority(value) if kind == "run" else decode_authority(value.get("authority"))
    if type(authority) is not CompanyAuthority:
        fail("A Company suggestion requires its original Company authority.")
    expected = {"scope_type": "Company", "project": None, "company": authority.company,
        "user": authority.user, "person": authority.person, "run_id": authority.run_id, "request_kind": PROPOSAL_KIND}
    if any(type(value.get(key)) is not type(item) or value.get(key) != item for key, item in expected.items()):
        fail("The proposal row has a different original identity or Run.")
    if before is not None:
        immutable = {"id", "scope_type", "company", "project", "user", "person", "run_id", "request_kind", "authority", "created_at"}
        if kind == "run":
            immutable |= {"request", "original_session_reference", "operation_id", "operation_key", "start_receipt", "start_request_hash",
                "resource_plan", "resource_plan_digest", "delegation_id", "deadline"}
            if canonical({**before["original_manifest"], "action_complete": True}) != canonical({**value["original_manifest"], "action_complete": True}):
                fail("The original prepared source observations cannot be replaced.")
            if before["original_manifest"]["action_complete"] and not value["original_manifest"]["action_complete"]:
                fail("Completed source preparation cannot be undone.")
        if any(canonical(before.get(key)) != canonical(value.get(key)) for key in immutable):
            fail("Original proposal identity, request and source admission are immutable.")
        if kind in {"proposal", "invocation", "artifact", "delegation"} or kind == "run" and before["status"] in FINAL or kind == "step" and before["status"] == "succeeded":
            if canonical(before) != canonical(value):
                fail("Immutable proposal history and terminal results cannot be rewritten.")
    run = value if kind == "run" else store.get("run", authority.run_id)
    decode_run_authority(run)
    if run["request_kind"] != PROPOSAL_KIND or canonical(value["authority"]) != canonical(run["authority"]):
        fail("This row is not part of its original proposal preparation.")
    request = DeterministicProposalRequest.from_value(run["request"])
    if kind == "run":
        validate_run_state(run); validate_manifest(run["original_manifest"], request); validate_resource_plan(run["resource_plan"])
        if digest(run["original_manifest"]) != run["original_manifest_digest"] or digest(run["resource_plan"]) != run["resource_plan_digest"]:
            fail("The original proposal source digests changed.")
        try:
            delegation = store.get("delegation", run["delegation_id"])
        except RickyError as error:
            if error.code != "not_found" or not initial_run_admission(run, before=before):
                raise
            delegation = None
        if delegation is not None and (delegation["run_id"] != run["id"] or delegation["authority"] != run["authority"]
                or delegation["allowed_tools"] != [request.action] or delegation["effect_classes"] != ["proposal"]
                or delegation["expires_at"] != run["deadline"]):
            fail("The delegation differs from this fixed draft request.")
        if run["generations"] or run["completed_effects"]:
            fail("Company suggestions have no model or domain write effects.")
        if run["status"] == "waiting-for-review":
            from .company_proposal_service import CompanyProposalService
            CompanyProposalService(store)._result_linkage(run)
    elif kind == "proposal":
        validate_proposal(value, run, store)
        if before is None and (run["status"] not in ACTIVE or run["cancel_requested"]):
            fail("Only the live preparation can insert its new suggestion.")
    elif kind == "delegation":
        if (value["id"] != run["delegation_id"] or value["allowed_tools"] != [request.action]
                or value["effect_classes"] != ["proposal"] or value["expires_at"] != run["deadline"]):
            fail("This delegation cannot authorize another action or lifetime.")
    elif kind in {"step", "invocation"}:
        if (value["tool_name"] != request.action or value["tool_version"] != "1" or value["delegation_id"] != run["delegation_id"]
                or value["input_digest"] != digest(json.loads(request.arguments_json)) or value["operation_key"] != invocation_key(run)):
            fail("The tool journal differs from the fixed original draft.")
        if kind == "invocation":
            step = store.get("step", value["step_id"])
            if (value["status"] != "succeeded" or step["status"] != "claimed" or step["run_id"] != run["id"]
                    or step["lease_token"] != run["lease_token"] or run["status"] not in ACTIVE
                    or step["operation_key"] != value["operation_key"] or digest(value["output"]) != value["output_digest"]):
                fail("The invocation is not bound to its current fenced Step.")
            validate_preparation(run, value["output"], originals=preparation_originals(run))
    elif kind == "artifact":
        closed(value["source"], {"citation_id", "revision_id", "page", "excerpt_sha256", "source_sha256"})
        from .aec_contracts import SourceReference
        source = SourceReference(**value["source"])
        selected = {row["id"]: row["digest"] for row in run["original_manifest"]["citations"]}
        if value["kind"] != "selected-company-document.v1" or source not in request.sources or selected.get(source.citation_id) != value["source_digest"]:
            fail("Only original selected sources can be retained as artifacts.")
    else:
        fail("This Company proposal record kind is unsupported.")
