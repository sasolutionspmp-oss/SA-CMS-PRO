"""Pure Company row invariants and one lexical atomic admission pair."""
from contextlib import contextmanager
from contextvars import ContextVar
import json

from .aec_contracts import SourceReference, identifier
from .company_contracts import CompanyAuthority, READ_KIND, decode_authority, decode_run_authority
from .contracts import RickyError, canonical, digest
from .engine import ACTIVE, FINAL

_admission = ContextVar("cipher_company_ricky_admission", default=None)


@contextmanager
def admission_pair(authority, delegation_id):
    if type(authority) is not CompanyAuthority or _admission.get() is not None:
        raise RickyError("invalid_company_binding", "A Company read admission must be a distinct exact pair.")
    identifier(delegation_id)
    token = _admission.set((canonical(authority.binding()), delegation_id))
    try:
        yield
    finally:
        _admission.reset(token)


def fail(message):
    raise RickyError("source_integrity", message)


def initial_run_admission(value, *, before=None):
    """Only the exact queued root and its unchanged initial native save."""
    authority = decode_run_authority(value)
    return (type(authority) is CompanyAuthority and value.get("status") == "queued"
        and _admission.get() == (canonical(authority.binding()), value.get("delegation_id"))
        and (before is None or canonical(before) == canonical(value)))


def validate_run_state(value):
    """A result is exposed only at its completed successful standing."""
    status = value.get("status")
    if (type(status) is not str or status not in {"queued", "retrieving", "executing", "succeeded", "failed", "cancelled"}
            or type(value.get("cancel_requested")) is not bool
            or value["cancel_requested"] != (status == "cancelled")):
        fail("The Company run standing and cancellation flag are inconsistent.")
    if status == "succeeded":
        if (value.get("result") is None or value.get("result_digest") is None
                or value.get("error") is not None):
            fail("A successful Company run requires its original result without an error.")
    elif value.get("result") is not None or value.get("result_digest") is not None:
        fail("Only a successful Company run may retain a result.")
    if status in {"succeeded", "failed", "cancelled"}:
        if type(value.get("completed_at")) is not str or not value["completed_at"]:
            fail("A terminal Company run requires its completion time.")
    elif value.get("completed_at") is not None:
        fail("An active Company run cannot have a completion time.")


def validate_company_record(kind, value, store, *, before=None):
    if kind == "proposal":
        raise RickyError("forbidden", "Company deterministic reads cannot create Proposed Changes.")
    authority = decode_run_authority(value) if kind == "run" else decode_authority(value.get("authority"))
    if type(authority) is not CompanyAuthority:
        fail("A Company row requires its exact Company authority.")
    expected = {"scope_type": "Company", "company": authority.company, "project": None,
        "user": authority.user, "person": authority.person, "run_id": authority.run_id, "request_kind": READ_KIND}
    if any(type(value.get(key)) is not type(item) or value.get(key) != item for key, item in expected.items()):
        fail("A Company child cannot change its original run or identity.")
    if before is not None:
        immutable = {"id", "scope_type", "company", "project", "user", "person", "run_id", "request_kind", "authority"}
        if kind == "run":
            immutable |= {"request", "original_session_reference", "operation_id", "operation_key", "start_receipt", "start_request_hash",
                "resource_plan", "resource_plan_digest", "delegation_id", "created_at", "deadline"}
        if any(canonical(before.get(key)) != canonical(value.get(key)) for key in immutable):
            fail("Original Company run identity, request and session are immutable.")
        if kind in {"invocation", "artifact", "delegation"} or kind == "run" and before["status"] in FINAL or kind == "step" and before["status"] == "succeeded":
            if canonical(before) != canonical(value):
                fail("Completed Company results and immutable source history cannot be rewritten.")
    run = value if kind == "run" else store.get("run", authority.run_id)
    decode_run_authority(run)
    if canonical(run["authority"]) != canonical(value["authority"]):
        fail("A Company child has a different original authority.")
    from .company_backend import validate_manifest, validate_resource_plan
    from .company_contracts import DeterministicReadRequest
    request = DeterministicReadRequest.from_value(run["request"])
    if kind == "run":
        validate_run_state(value)
        validate_manifest(value["original_manifest"], request)
        validate_resource_plan(value["resource_plan"])
        if digest(value["original_manifest"]) != value["original_manifest_digest"] or digest(value["resource_plan"]) != value["resource_plan_digest"]:
            fail("The original manifests do not match their stored digests.")
        try:
            delegation = store.get("delegation", value["delegation_id"])
        except RickyError as error:
            # Native child Links require the Run first. Only this initial
            # lexical admission permits its not-yet-inserted delegation.
            if error.code != "not_found" or not initial_run_admission(value, before=before):
                raise
            delegation = None
        if delegation is not None and (delegation["run_id"] != value["id"] or canonical(delegation["authority"]) != canonical(value["authority"])
                or delegation["allowed_tools"] != [request.action] or delegation["effect_classes"] != ["read"]):
            fail("The Company delegation does not match the fixed read request.")
        if value["proposal_ids"] or value["generations"] or value["completed_effects"]:
            fail("Deterministic Company reads have no model/proposal/domain effects.")
        if value["status"] == "succeeded":
            from .company_service import CompanyReadService
            service = CompanyReadService(store)
            if value["result"] is None or digest(value["result"]) != value["result_digest"]:
                fail("A completed Company read requires its exact immutable result.")
            service._result_linkage(value)
    elif kind == "delegation":
        if value["id"] != run["delegation_id"] or value["allowed_tools"] != [request.action] or value["effect_classes"] != ["read"]:
            fail("A Company delegation grants only its selected fixed read.")
    elif kind in {"step", "invocation"}:
        if value["tool_name"] != request.action or value["delegation_id"] != run["delegation_id"]:
            fail("A Company invocation cannot select another tool or delegation.")
        if value["input_digest"] != digest(json.loads(request.arguments_json)):
            fail("The tool arguments differ from the original selected request.")
        if kind == "invocation":
            step = store.get("step", value["step_id"])
            if (step["run_id"] != run["id"] or step["tool_name"] != request.action
                    or step["lease_token"] != run["lease_token"] or run["status"] not in ACTIVE
                    or digest(value["output"]) != value["output_digest"]):
                fail("The Company tool result is not linked to its current fenced preparation.")
    elif kind == "artifact":
        if value["kind"] != "selected-company-document.v1":
            fail("Company read artifacts refer only to selected canonical document sources.")
        if type(value["source"]) is not dict or set(value["source"]) != set(SourceReference.__dataclass_fields__):
            fail("A Company read artifact requires the exact selected source shape.")
        source = SourceReference(**value["source"])
        citations = {row["id"]: row["digest"] for row in run["original_manifest"]["citations"]}
        if source not in request.sources or citations.get(source.citation_id) != value["source_digest"]:
            fail("The Company artifact is not an exact original selected source.")
    else:
        fail("This Company orchestration record kind is unsupported.")
