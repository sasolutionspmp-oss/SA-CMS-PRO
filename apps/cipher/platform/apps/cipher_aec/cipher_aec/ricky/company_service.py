"""Draft Company strategy on the existing Ricky lease/tool journal engine.

This module constructs no model adapter. Registration/migration/runtime
qualification are separate; its current tests use explicit fixture storage.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from functools import wraps
import json
from uuid import uuid4

from .aec_backend import AECBackend
from .aec_contracts import SCHEMAS, identifier
from .company_backend import CompanyBackend, START_COMMAND, CANCEL_COMMAND
from .company_contracts import CompanyAuthority, DeterministicReadRequest, READ_KIND, decode_run_authority
from .company_records import validate_company_record, validate_run_state
from .contracts import Limits, RickyError, canonical, digest, iso, parse_time, utcnow
from .engine import RickyService, Execution, ACTIVE, FINAL
from .tools import Tool, ToolRegistry, validate


def domain_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        from cipher_aec.api.errors import DomainError
        try:
            return function(*args, **kwargs)
        except RickyError as error:
            status = {"not_found": 404, "forbidden": 403, "forbidden_tool": 403,
                "session_revoked": 403, "expired_session": 403, "identity_unavailable": 403,
                "identity_changed": 403, "capability_denied": 403, "interactive_session_required": 401,
                "execution_quarantined": 503, "lease_lost": 409, "cancelled": 409,
                "expired_delegation": 409, "resource_limit": 429,
                "source_integrity": 409, "receipt_integrity": 409, "incomplete_preparation": 409,
                "stale_source": 412, "stale_authority": 412, "source_prelock_required": 409,
                "source_dependency_unqualified": 409, "rate_limit": 429}.get(error.code, 422)
            raise DomainError(error.code, error.message, status) from None
    return wrapped


READ_METHODS = {"aec.pursuit.lookup": ("pursuit_lookup", "commercial.read"),
    "aec.estimate.recompute": ("recompute", "estimate.read"),
    "aec.estimate.compare": ("compare", "estimate.read"),
    "aec.quantity.convert": ("convert", "estimate.read")}
PERMANENT_PRECLAIM_REFUSALS = frozenset({"session_revoked", "expired_session", "stale_authority",
    "identity_changed", "identity_unavailable", "capability_denied", "not_found", "expired_delegation",
    "source_dependency_unqualified", "stale_source"})


def validate_start_receipt(run, result):
    """The immutable queued observation stays queued after current work ends."""
    authority = decode_run_authority(run)
    if type(authority) is not CompanyAuthority:
        raise RickyError("receipt_integrity", "A Company start receipt requires its original Company run.")
    admitted = {**run, "status": "queued", "cancel_requested": False, "completed_at": None,
        "result": None, "result_digest": None, "error": None}
    expected = CompanyReadService._present(admitted)
    request_hash = digest({"scope_type": "Company", "command": START_COMMAND, "company": authority.company,
        "project": None, "payload": {"request": run["request"]}})
    if (type(result) is not dict or canonical(result) != canonical(expected)
            or run["start_request_hash"] != request_hash):
        raise RickyError("receipt_integrity", "The retained start receipt differs from its exact original admission.")


def read_registry():
    registry = ToolRegistry()
    for name, (method, ability) in READ_METHODS.items():
        request, response = SCHEMAS[name]
        registry.register(Tool(name, "1", "read", ability, request, response,
            idempotency="original-run-fixed-read", scope_derivation="original-company-run",
            source_dependencies=("original-session", "original-selected-records", "current-source-rights")),
            lambda execution, arguments, method=method: execution.aec(method, arguments))
    return registry


class CompanyReadService(RickyService):
    def __init__(self, store, backend=None, *, limits=None, clock=utcnow):
        # No super initializer: it constructs the Project default registry and
        # expects a model adapter. Shared lease/tool/savepoint methods are used.
        self.store, self.backend = store, backend or CompanyBackend()
        self.limits, self.clock = limits or Limits(), clock
        self.registry = read_registry()

    def _new(self, authority, **fields):
        return {"id": str(uuid4()), "scope_type": "Company", "project": None,
            "company": authority.company, "user": authority.user, "person": authority.person,
            "run_id": authority.run_id, "authority": authority.binding(), "request_kind": READ_KIND,
            "created_at": iso(self.clock()), **fields}

    def start_read(self, company, value, operation_id):
        """NEW effect only, inside canonical Company command locks/receipt miss."""
        identifier(operation_id)
        request = DeterministicReadRequest.from_value(value)
        self.backend.require_effects_enabled()
        authority = self.backend.bind(company, request, str(uuid4()))
        self.backend.require_permission(authority, READ_METHODS[request.action][1])
        self.store.admission_lock(authority.person)
        if (self.store.count("run", {"person_id": authority.person, "status": ["in", list(ACTIVE)]}) >= self.limits.active_per_person
                or self.store.count("run", {"status": ["in", list(ACTIVE)]}) >= self.limits.site_queue):
            raise RickyError("rate_limit", "The bounded Ricky read queue is full.", retryable=True)
        with self.backend.source_scope(authority, request, lock=True, execution=True) as plan:
            reader = self.backend.reader(authority, request, lock=True, execution=True)
            reader.prepare_selected()
            manifest = reader.manifest()
        # Admission has no preexisting Run to lock. It holds aggregate/quota,
        # completes source checks, exits source admission, then inserts its
        # Run/delegation pair atomically before canonical receipt insertion.
        delegation_id = str(uuid4())
        deadline = iso(self.clock() + timedelta(seconds=self.limits.wall_seconds))
        delegation = self._new(authority, id=delegation_id, status="active", allowed_tools=[request.action],
            effect_classes=["read"], limits=asdict(self.limits), expires_at=deadline,
            grant_basis="authenticated-company-deterministic-read", grantor=authority.person)
        run = self._new(authority, id=authority.run_id, status="queued", delegation_id=delegation_id,
            operation_id=operation_id, operation_key=digest({"person": authority.person, "operation_id": operation_id}),
            start_receipt=digest({"person": authority.person, "operation_id": operation_id}),
            start_request_hash=digest({"scope_type": "Company", "command": START_COMMAND, "company": company,
                "project": None, "payload": {"request": request.binding()}}),
            original_session_reference=authority.session_reference, request=request.binding(),
            original_manifest=manifest, original_manifest_digest=digest(manifest),
            resource_plan=plan, resource_plan_digest=digest(plan),
            sources=[asdict(source) for source in request.sources], context=[], proposal_ids=[], tool_calls=0, retrieval_rounds=0, generations=0,
            lease_token=0, lease_expires_at=None, cancel_requested=False, deadline=deadline,
            result=None, result_digest=None, error=None, completed_effects=[])
        with self.backend.admission_scope(authority, delegation_id):
            self.store.insert("run", run)
            self.store.insert("delegation", delegation)
            validate_company_record("run", self.store.get("run", run["id"]), self.store)
            validate_company_record("delegation", self.store.get("delegation", delegation_id), self.store)
        citations = {item["id"]: item["digest"] for item in manifest["citations"]}
        for reference in request.sources:
            self.store.insert("artifact", self._new(authority, status="referenced", run_id=run["id"],
                kind="selected-company-document.v1", source=asdict(reference), source_digest=citations[reference.citation_id]))
        return self._present(run)

    def _load(self, company, run_id, *, lock=False):
        run = self.store.get("run", run_id, lock=lock)
        authority = decode_run_authority(run)
        if type(authority) is not CompanyAuthority or authority.company != company or run.get("request_kind") != READ_KIND:
            raise RickyError("not_found", "This Company Ricky record is not accessible.")
        return run

    def _check(self, run, *, worker=False, lock=None, **unused):
        validate_run_state(run)
        authority = decode_run_authority(run)
        originals = self.backend.authorize_result(run, execution=worker, lock=worker if lock is None else lock,
            observation=not worker and run["status"] not in FINAL)
        if run.get("result") is not None and (not run["original_manifest"]["action_complete"]
                or digest(run["result"]) != run["result_digest"]):
            raise RickyError("source_integrity", "The recorded deterministic result changed.")
        if run.get("result") is not None:
            self._result_linkage(run, originals=originals)
        return authority

    def _successful_invocation(self, run):
        request = DeterministicReadRequest.from_value(run["request"])
        arguments = json.loads(request.arguments_json)
        key = digest({"run": run["id"], "logical_call": "selected-deterministic-read", "tool": request.action, "arguments": arguments})
        rows = self.store.find("invocation", {"operation_key": key}, limit=2)
        if len(rows) != 1:
            raise RickyError("incomplete_preparation", "The original deterministic invocation is unavailable.")
        receipt = rows[0]
        step = self.store.get("step", receipt["step_id"])
        version = self.registry.definition(request.action).version
        if (receipt["status"] != "succeeded" or step["status"] != "succeeded"
                or step["id"] != receipt["step_id"] or receipt["output_digest"] != digest(receipt["output"])
                or step["output_digest"] != receipt["output_digest"]
                or any(row.get("operation_key") != key or row.get("tool_name") != request.action
                    or row.get("tool_version") != version for row in (receipt, step))
                or receipt["input_digest"] != digest(arguments) or step["input_digest"] != digest(arguments)
                or any(row.get(field) != run.get(field) for row in (receipt, step)
                    for field in ("run_id", "company", "scope_type", "project", "user", "person", "authority", "delegation_id"))):
            raise RickyError("source_integrity", "The result does not match its original successful run preparation.")
        validate(self.registry.definition(request.action).output_schema, receipt["output"])
        return receipt

    def _result_linkage(self, run, *, originals=None):
        request = DeterministicReadRequest.from_value(run["request"])
        arguments = json.loads(request.arguments_json)
        receipt = self._successful_invocation(run)
        if receipt["output_digest"] != run["result_digest"] or canonical(receipt["output"]) != canonical(run["result"]):
            raise RickyError("source_integrity", "The result differs from its original immutable invocation.")
        result, manifest = run["result"], run["original_manifest"]
        sources = {(row["domain"], row["kind"], row["id"]): row["digest"] for row in manifest["records"]}
        if request.action == "aec.pursuit.lookup":
            valid = result["record_digest"] == manifest["pursuit"]["digest"]
        elif request.action == "aec.estimate.recompute":
            valid = (result["revision_id"] == arguments["revision_id"]
                and result["revision_digest"] == sources.get(("estimate", "revision", arguments["revision_id"]))
                and ("estimate", "snapshot", result["snapshot_id"]) in sources)
            def original(kind, record_id):
                key = "estimate", kind, record_id
                value = originals[key] if originals is not None else self.store.read_original("estimate", kind, record_id)
                if (value.get("scope_type") != "Company" or value.get("company") != run["company"]
                        or value.get("project") is not None or digest(value) != sources.get(key)):
                    raise RickyError("source_integrity", "The original calculation linkage cannot be verified.")
                return value
            revision = original("revision", arguments["revision_id"])
            snapshot = original("snapshot", result["snapshot_id"])
            valid = valid and (revision["calculation_snapshot"] == result["snapshot_id"]
                and snapshot["subject_id"] == revision["id"] and snapshot["input_digest"] == result["input_digest"]
                and snapshot["output_digest"] == result["output_digest"]
                and canonical(snapshot["result"]["total"]) == canonical(result["total"])
                and snapshot["inputs"]["policy_version"] == result["policy_version"])
        elif request.action == "aec.estimate.compare":
            valid = all(result[side + "_revision_id"] == arguments[side + "_revision_id"]
                and result[side + "_digest"] == sources.get(("estimate", "revision", arguments[side + "_revision_id"]))
                for side in ("left", "right"))
        else:
            domain, kind = ("estimate", "line") if arguments["source_kind"] == "estimate-line" else ("takeoff", "measurement")
            valid = (result["source_id"] == arguments["source_id"] and result["source_kind"] == arguments["source_kind"]
                and result["target_unit_id"] == arguments["target_unit_id"]
                and result["source_digest"] == sources.get((domain, kind, arguments["source_id"])))
        if not valid or run.get("prepared_manifest_digest") != run["original_manifest_digest"]:
            raise RickyError("source_integrity", "The original result and source manifest are not bound.")

    def _ordered_run(self, run_id, *, execution):
        preview = self.store.get("run", run_id)
        if type(decode_run_authority(preview)) is not CompanyAuthority:
            raise RickyError("not_found", "A Project run cannot enter Company orchestration.")
        self.backend.lock_original(preview, execution=execution)
        run = self.store.get("run", run_id, lock=True)
        immutable = ("id", "scope_type", "company", "project", "user", "person", "authority", "request",
            "operation_id", "start_receipt", "start_request_hash", "original_session_reference", "resource_plan", "resource_plan_digest")
        if canonical({key: preview[key] for key in immutable}) != canonical({key: run[key] for key in immutable}):
            raise RickyError("source_integrity", "The locked run changed its original identity or request.")
        return run

    def claim(self, identifier):
        run = self._ordered_run(identifier, execution=True)
        if run["status"] in FINAL or run["cancel_requested"]:
            return None
        if run.get("lease_expires_at") and self.clock() < parse_time(run["lease_expires_at"]):
            return None
        self._delegation(run)
        self._check(run, worker=True)
        return self._claim_checked(run)

    def _live(self, identifier, token):
        run = self._ordered_run(identifier, execution=True)
        self._validate_live_lease(run, token)
        authority = self._check(run, worker=True)
        self._delegation(run)
        return run, authority

    def _accept_tool_result(self, execution, output, *, replay=False):
        live, _ = self._live(execution.identifier, execution.token)
        if replay:
            prior = self._successful_invocation(live)
            if prior["run_id"] != live["id"] or prior["output_digest"] != digest(output):
                raise RickyError("source_integrity", "The immutable original invocation changed.")
            candidate = live
        else:
            candidate = {**live, "original_manifest": execution.run["original_manifest"],
                "original_manifest_digest": execution.run["original_manifest_digest"]}
        self._check(candidate, worker=True)
        execution.run.update(original_manifest=candidate["original_manifest"],
            original_manifest_digest=candidate["original_manifest_digest"])

    def process(self, identifier):
        self.backend.require_effects_enabled()
        preview = self.store.get("run", identifier)
        authority = decode_run_authority(preview)
        if type(authority) is not CompanyAuthority:
            raise RickyError("not_found", "A Project run cannot enter Company orchestration.")
        token = None
        with self.backend.original_user(authority):
            try:
                claimed = self.claim(identifier)
                if claimed is None:
                    return
                run, token = claimed
                request = DeterministicReadRequest.from_value(run["request"])
                output = CompanyExecution(self, identifier, token).invoke(request.action,
                    json.loads(request.arguments_json), "selected-deterministic-read")
                run, _ = self._live(identifier, token)
                run.update(status="succeeded", result=deepcopy(output), result_digest=digest(output),
                    completed_at=iso(self.clock()))
                self._result_linkage(run)
                self.store.save("run", run)
                self.store.checkpoint()
            except Exception as error:
                failure = error if isinstance(error, RickyError) else RickyError(
                    getattr(error, "code", "internal_error"), getattr(error, "message", "The deterministic read failed."))
                if token is None:
                    self._settle_unclaimed(preview, failure)
                else:
                    self._fail(identifier, token, failure)
                if not isinstance(error, RickyError) and not hasattr(error, "code"):
                    raise

    def _settle_unclaimed(self, observed, refusal):
        """Trusted worker terminal metadata CAS, with no source facts/output.

        No authority/source/native locks are acquired after Run. An independent
        command or newer worker changing any observed state defeats this CAS.
        Transport/DB/unexpected/retryable errors leave recovery available.
        """
        if refusal.code not in PERMANENT_PRECLAIM_REFUSALS or refusal.retryable:
            return False
        current = self.store.get("run", observed["id"], lock=True)
        if (canonical(current) != canonical(observed) or current["status"] in FINAL or current["cancel_requested"]
                or current.get("lease_expires_at") and self.clock() < parse_time(current["lease_expires_at"])):
            return False
        if type(decode_run_authority(current)) is not CompanyAuthority:
            return False
        current.update(status="failed", completed_at=iso(self.clock()), error={"code": refusal.code,
            "message": "The original session, authority or selected source no longer permits this read.", "retryable": False})
        self.store.save("run", current)
        self.store.checkpoint()
        return True

    def _fail(self, identifier, token, error):
        # Pre-claim errors confer no right to mutate somebody else's queued,
        # completed or already leased run. This path never accepts output.
        if token is None:
            return
        run = self.store.get("run", identifier, lock=True)
        if run["lease_token"] != token or run["status"] not in ACTIVE or run["cancel_requested"]:
            return
        run.update(status="failed", error={"code": error.code, "message": error.message,
            "retryable": error.retryable}, completed_at=iso(self.clock()))
        self.store.save("run", run)
        self.store.checkpoint()

    def get_run(self, company, run_id, *, lock=False):
        run = self._ordered_run(run_id, execution=False) if lock else self._load(company, run_id)
        if run["company"] != company:
            raise RickyError("not_found", "This Company Ricky record is not accessible.")
        self._check(run, lock=lock)
        return self._present(run)

    def events(self, company, run_id):
        self.get_run(company, run_id)
        # Parent authorization precedes returning any step. Child linkage is
        # rechecked independently; no foreign run or scope rows may be exposed.
        rows = self.store.find("step", {"run_id": run_id}, limit=self.limits.tool_calls)
        run = self._load(company, run_id)
        for row in rows:
            if any(row.get(key) != run.get(key) for key in ("company", "project", "scope_type", "user", "person", "authority")):
                raise RickyError("source_integrity", "A step has a different original run scope.")
        return [{key: row.get(key) for key in ("id", "run_id", "status", "tool_name", "created_at", "completed_at", "error")} for row in rows]

    def cancel(self, company, run_id):
        run = self._ordered_run(run_id, execution=False)
        if run["company"] != company:
            raise RickyError("not_found", "This Company Ricky record is not accessible.")
        if run["status"] not in FINAL:
            run.update(status="cancelled", cancel_requested=True, lease_token=run["lease_token"] + 1,
                completed_at=iso(self.clock()))
            self.store.save("run", run)
        return self._stop(run)

    def start(self, *args, **kwargs):
        raise RickyError("forbidden_tool", "Company reads require an explicit fixed deterministic action.")

    def get_proposal(self, *args, **kwargs):
        raise RickyError("forbidden_tool", "Company deterministic reads have no Proposed Changes.")

    def commit_proposal(self, *args, **kwargs):
        raise RickyError("forbidden_tool", "Company deterministic reads cannot save domain changes.")

    @staticmethod
    def _stop(run):
        validate_run_state(run)
        return {key: run[key] for key in ("id", "company", "scope_type", "project", "request_kind", "status", "cancel_requested")}

    @staticmethod
    def _present(run):
        return {**CompanyReadService._stop(run), "created_at": run["created_at"],
            "completed_at": run.get("completed_at"), "action": run["request"]["action"],
            "result": deepcopy(run["result"]), "result_digest": run["result_digest"],
            "error": deepcopy(run["error"]), "standing": DeterministicReadRequest.model_standing(),
            "result_basis": "original-tool-observation-v1", "selection": deepcopy(run["request"]),
            "selection_digest": run["authority"]["selection_digest"]}


class CompanyExecution(Execution):
    def aec(self, method, arguments):
        service = self.service
        request = DeterministicReadRequest.from_value(self.run["request"])
        with service.backend.source_scope(self.authority, request, self.run["original_manifest"],
                lock=True, execution=True, expected_plan=self.run["resource_plan"]):
            reader = service.backend.reader(self.authority, request, lock=True, execution=True)
            reader.prepare_selected()
            if reader.pursuit_observation != self.run["original_manifest"]["pursuit"]:
                raise RickyError("stale_source", "The selected Pursuit changed before this read was executed.")
            output = getattr(AECBackend(request.read_context(self.authority), reader=reader), method)(arguments)
            manifest = reader.manifest(action_complete=True)
        self.run.update(original_manifest=manifest, original_manifest_digest=digest(manifest), prepared_manifest_digest=digest(manifest))
        return output


def build_service(*, worker=False):
    from .storage import CompanyStore
    return CompanyReadService(CompanyStore(worker=worker))


@domain_errors
def authorize_receipt(actor, company, result, *, command, lock=False):
    if command not in {START_COMMAND, CANCEL_COMMAND}:
        raise RickyError("forbidden", "This Company Ricky receipt command is unavailable.")
    if type(result) is not dict or type(result.get("id")) is not str:
        raise RickyError("source_integrity", "The original Company run receipt is invalid.")
    service = build_service()
    run = service._ordered_run(result["id"], execution=False) if lock else service._load(company, result["id"])
    authority = decode_run_authority(run)
    if (authority.user != actor.user or authority.person != actor.person_id or authority.company != company):
        raise RickyError("not_found", "This original Company run is not accessible.")
    if command == CANCEL_COMMAND:
        service.backend.authorize(authority, lock=lock)
        if (type(result) is not dict or set(result) != set(service._stop(run))
                or type(result["status"]) is not str or result["status"] not in {"cancelled", "succeeded", "failed"}
                or type(result["cancel_requested"]) is not bool or result["cancel_requested"] != (result["status"] == "cancelled")
                or any(type(result[key]) is not type(run[key]) or result[key] != run[key] for key in ("id", "company", "scope_type", "project", "request_kind"))):
            raise RickyError("source_integrity", "A stop receipt must contain only its original narrow metadata.")
    else:
        validate_start_receipt(run, result)
        service._check(run, lock=lock)


@domain_errors
def authorize_history(actor, company, run_id, *, lock=False):
    service = build_service()
    preview = service.store.get("run", run_id)
    if preview.get("request_kind") == "deterministic-proposal-v1":
        from .company_proposal_service import authorize_history as authorize_proposal_history
        return authorize_proposal_history(actor, company, run_id, lock=lock)
    run = service._ordered_run(run_id, execution=False) if lock else service._load(company, run_id)
    authority = decode_run_authority(run)
    if (authority.user != actor.user or authority.person != actor.person_id or authority.company != company):
        raise RickyError("not_found", "This original Company run is not accessible.")
    service._check(run, lock=lock)
