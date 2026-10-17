"""Deterministic Company preparation with a distinct immutable stored wrapper."""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import json
from uuid import uuid4

from .aec_backend import AECBackend
from .aec_contracts import SCHEMAS, identifier
from .company_contracts import CompanyAuthority, decode_run_authority
from .company_proposal_backend import CompanyProposalBackend
from .company_proposal_contracts import (PROPOSAL_KIND, PROPOSAL_SCHEMA, START_COMMAND, CANCEL_COMMAND, METHODS,
    DeterministicProposalRequest, validate_preparation, fail)
from .company_proposal_records import (validate_run_state, validate_company_proposal_record, successful_invocation, preparation_originals)
from .company_service import CompanyReadService, domain_errors
from .contracts import Limits, RickyError, canonical, digest, iso, utcnow
from .engine import Execution, ACTIVE, FINAL
from .tools import Tool, ToolRegistry


def proposal_registry():
    registry = ToolRegistry()
    for name, (method, permission, _) in METHODS.items():
        request, response = SCHEMAS[name]
        registry.register(Tool(name, "1", "proposal", permission, request, response,
            idempotency="original-fixed-preparation-then-persisted-wrapper", scope_derivation="original-company-proposal-run",
            source_dependencies=("original-session", "original-source-manifest", "current-source-rights", "selected-working-head")),
            lambda execution, arguments, method=method: execution.aec(method, arguments))
    return registry


class CompanyProposalService(CompanyReadService):
    def __init__(self, store, backend=None, *, limits=None, clock=utcnow):
        self.store, self.backend = store, backend or CompanyProposalBackend()
        self.limits, self.clock = limits or Limits(), clock
        self.registry = proposal_registry()

    def _new(self, authority, **fields):
        return {"id": str(uuid4()), "scope_type": "Company", "project": None, "company": authority.company,
            "user": authority.user, "person": authority.person, "run_id": authority.run_id, "authority": authority.binding(),
            "request_kind": PROPOSAL_KIND, "created_at": iso(self.clock()), **fields}

    def start_proposal(self, company, value, operation_id):
        identifier(operation_id)
        request = DeterministicProposalRequest.from_value(value)
        self.backend.require_effects_enabled()
        authority = self.backend.bind(company, request, str(uuid4()))
        self.backend.require_permission(authority, METHODS[request.action][1])
        self.store.admission_lock(authority.person)
        if (self.store.count("run", {"person_id": authority.person, "status": ["in", list(ACTIVE)]}) >= self.limits.active_per_person
                or self.store.count("run", {"status": ["in", list(ACTIVE)]}) >= self.limits.site_queue):
            raise RickyError("rate_limit", "The bounded Ricky preparation queue is full.", retryable=True)
        with self.backend.source_scope(authority, request, lock=True, execution=True) as plan:
            reader = self.backend.reader(authority, request, lock=True, execution=True)
            reader.prepare_selected()
            manifest = reader.manifest()
        delegation_id = str(uuid4())
        deadline = iso(self.clock() + timedelta(seconds=self.limits.wall_seconds))
        delegation = self._new(authority, id=delegation_id, status="active", allowed_tools=[request.action], effect_classes=["proposal"],
            limits=asdict(self.limits), expires_at=deadline, grant_basis="authenticated-company-deterministic-proposal", grantor=authority.person)
        key = digest({"person": authority.person, "operation_id": operation_id})
        run = self._new(authority, id=authority.run_id, status="queued", delegation_id=delegation_id,
            operation_id=operation_id, operation_key=key, start_receipt=key,
            start_request_hash=digest({"scope_type": "Company", "command": START_COMMAND, "company": company,
                "project": None, "payload": {"request": request.binding()}}),
            original_session_reference=authority.session_reference, request=request.binding(), original_manifest=manifest,
            original_manifest_digest=digest(manifest), resource_plan=plan, resource_plan_digest=digest(plan),
            sources=[asdict(source) for source in request.sources], context=[], proposal_ids=[], tool_calls=0, retrieval_rounds=0, generations=0,
            lease_token=0, lease_expires_at=None, cancel_requested=False, deadline=deadline, result=None, result_digest=None,
            error=None, completed_at=None, completed_effects=[])
        with self.backend.admission_scope(authority, delegation_id):
            self.store.insert("run", run)
            self.store.insert("delegation", delegation)
            validate_company_proposal_record("run", self.store.get("run", run["id"]), self.store)
            validate_company_proposal_record("delegation", self.store.get("delegation", delegation_id), self.store)
        citations = {row["id"]: row["digest"] for row in manifest["citations"]}
        for source in request.sources:
            self.store.insert("artifact", self._new(authority, status="referenced", kind="selected-company-document.v1",
                source=asdict(source), source_digest=citations[source.citation_id]))
        return self._present(run)

    def _load(self, company, run_id, *, lock=False):
        run = self.store.get("run", run_id, lock=lock)
        authority = decode_run_authority(run)
        if type(authority) is not CompanyAuthority or authority.company != company or run["request_kind"] != PROPOSAL_KIND:
            raise RickyError("not_found", "This Company preparation is not accessible.")
        return run

    def _check(self, run, *, worker=False, lock=None, **unused):
        validate_run_state(run)
        authority = decode_run_authority(run)
        originals = self.backend.authorize_result(run, execution=worker, lock=worker if lock is None else lock,
            observation=not worker and run["status"] not in FINAL)
        if run["result"] is not None:
            self._result_linkage(run, originals=originals)
        return authority

    def _successful_invocation(self, run, *, originals=None, require_citations=False):
        return successful_invocation(self.store, run, originals=originals, require_citations=require_citations)

    def _result_linkage(self, run, *, originals=None):
        invocation = self._successful_invocation(run, originals=originals, require_citations=originals is not None)
        if len(run["proposal_ids"]) != 1 or run.get("prepared_manifest_digest") != run["original_manifest_digest"]:
            fail("A reviewable Run must link its exact completed preparation and one proposal.")
        proposal = self.store.get("proposal", run["proposal_ids"][0])
        validate_company_proposal_record("proposal", proposal, self.store, before=proposal)
        expected = {"proposal_id": proposal["id"], "proposal_version": 1, "proposal_digest": proposal["content_digest"],
            "preparation_digest": invocation["output_digest"]}
        if canonical(run["result"]) != canonical(expected) or run["result_digest"] != digest(expected):
            fail("The terminal Run differs from its stored suggestion.")

    def _accept_tool_result(self, execution, output, *, replay=False):
        live, _ = self._live(execution.identifier, execution.token)
        if replay:
            prior = self._successful_invocation(live)
            if canonical(output) != canonical(prior["output"]):
                fail("The original successful draft output cannot be replaced.")
            candidate = live
        else:
            candidate = {**live, "original_manifest": execution.run["original_manifest"],
                "original_manifest_digest": execution.run["original_manifest_digest"],
                "prepared_manifest_digest": execution.run["prepared_manifest_digest"]}
        validate_run_state(candidate)
        originals = self.backend.authorize_result(candidate, execution=True, lock=True)
        validate_preparation(candidate, output, originals=originals, require_citations=True)
        execution.run.update(original_manifest=candidate["original_manifest"], original_manifest_digest=candidate["original_manifest_digest"],
            prepared_manifest_digest=candidate.get("prepared_manifest_digest"))

    def finalize(self, run_id, token):
        """One guarded transaction after the successful immutable tool checkpoint."""
        self.backend.require_effects_enabled()
        run, authority = self._live(run_id, token)
        originals = self.backend.authorize_result(run, execution=True, lock=True)
        invocation = self._successful_invocation(run, originals=originals, require_citations=True)
        self._validate_live_lease(run, token)
        # The live check reopens current canonical originals and exact targets;
        # no output is recomputed and no old invocation is mutated here.
        if self.store.find("proposal", {"operation_key": invocation["operation_key"]}, limit=1):
            fail("An active preparation cannot adopt an existing proposal effect.")
        proposal = self._new(authority, schema=PROPOSAL_SCHEMA, status="proposed", version=1, persistent=True,
            action=run["request"]["action"], action_version="1", kind=METHODS[run["request"]["action"]][2],
            delegation_id=run["delegation_id"], step_id=invocation["step_id"], invocation_id=invocation["id"], operation_key=invocation["operation_key"],
            selection_digest=authority.selection_digest, prepared_manifest_digest=run["original_manifest_digest"], resource_plan_digest=run["resource_plan_digest"],
            preparation_digest=invocation["output_digest"], draft_digest=invocation["output"]["draft_digest"], preparation=deepcopy(invocation["output"]),
            source_manifest=deepcopy(run["original_manifest"]), expires_at=run["deadline"], review_required=True, claim_classification="unverified-author-suggestion")
        proposal["content_digest"] = digest(proposal)
        result = {"proposal_id": proposal["id"], "proposal_version": 1, "proposal_digest": proposal["content_digest"],
            "preparation_digest": invocation["output_digest"]}
        savepoint = "ricky_proposal_" + proposal["id"].replace("-", "")
        self.store.savepoint(savepoint)
        try:
            self.store.insert("proposal", proposal)
            run.update(proposal_ids=[proposal["id"]], status="waiting-for-review", completed_at=iso(self.clock()),
                result=result, result_digest=digest(result))
            self.store.save("run", run)
            self._result_linkage(run)
            self._validate_live_lease(run, token)
            self.store.checkpoint()
        except Exception as error:
            native = getattr(self.store, "frappe", None)
            conflicts = tuple(value for value in (getattr(native, "QueryDeadlockError", None), getattr(native, "QueryTimeoutError", None)) if isinstance(value, type))
            if conflicts and isinstance(error, conflicts):
                native.db.rollback()
            else:
                self.store.rollback_to(savepoint)
            raise
        return result

    def process(self, identifier):
        self.backend.require_effects_enabled()
        preview = self._load(self.store.get("run", identifier)["company"], identifier)
        authority = decode_run_authority(preview)
        token = None
        with self.backend.original_user(authority):
            try:
                claimed = self.claim(identifier)
                if claimed is None:
                    return
                run, token = claimed
                request = DeterministicProposalRequest.from_value(run["request"])
                CompanyProposalExecution(self, identifier, token).invoke(request.action, json.loads(request.arguments_json), "selected-deterministic-proposal")
                self.finalize(identifier, token)
            except Exception as error:
                # Unexpected/native transaction errors remain recoverable and
                # propagate to ordinary Frappe/RQ handling. Never hide them as
                # a successful proposal or commit an unrolled-back local effect.
                if not isinstance(error, RickyError) and not hasattr(error, "code"):
                    raise
                refusal = error if isinstance(error, RickyError) else RickyError(error.code, error.message)
                if token is None:
                    self._settle_unclaimed(preview, refusal)
                else:
                    self._fail(identifier, token, refusal)

    def get_proposal(self, company, proposal_id):
        proposal = self.store.get("proposal", proposal_id)
        run = self._load(company, proposal["run_id"])
        self._check(run)
        if run["status"] != "waiting-for-review" or run["proposal_ids"] != [proposal_id]:
            raise RickyError("not_found", "This stored suggestion is not accessible.")
        validate_company_proposal_record("proposal", proposal, self.store, before=proposal)
        # Authority/session details stay server-side, even for an authorized DTO.
        return {key: deepcopy(proposal[key]) for key in ("id", "schema", "scope_type", "company", "project", "run_id", "status", "version", "persistent",
            "action", "action_version", "kind", "step_id", "invocation_id", "created_at", "expires_at", "content_digest", "preparation_digest",
            "preparation", "source_manifest", "prepared_manifest_digest", "review_required", "claim_classification")}

    @staticmethod
    def _stop(run):
        validate_run_state(run)
        return {key: run[key] for key in ("id", "company", "scope_type", "project", "request_kind", "status", "cancel_requested")}

    @staticmethod
    def _present(run):
        return {**CompanyProposalService._stop(run), "created_at": run["created_at"], "completed_at": run.get("completed_at"),
            "action": run["request"]["action"], "result": deepcopy(run["result"]), "result_digest": run["result_digest"], "error": deepcopy(run["error"]),
            "standing": DeterministicProposalRequest.model_standing(), "result_basis": "persisted-proposal-reference-v1",
            "selection": deepcopy(run["request"]), "selection_digest": run["authority"]["selection_digest"]}


class CompanyProposalExecution(Execution):
    def aec(self, method, arguments):
        service = self.service
        request = DeterministicProposalRequest.from_value(self.run["request"])
        with service.backend.source_scope(self.authority, request, self.run["original_manifest"], lock=True, execution=True,
                expected_plan=self.run["resource_plan"]):
            reader = service.backend.reader(self.authority, request, lock=True, execution=True)
            reader.prepare_selected()
            output = getattr(AECBackend(request.read_context(self.authority), reader=reader), method)(arguments)
            manifest = reader.manifest(action_complete=True)
        if canonical({**manifest, "action_complete": False}) != canonical(self.run["original_manifest"]):
            raise RickyError("stale_source", "The original prepared source observations changed.")
        self.run.update(original_manifest=manifest, original_manifest_digest=digest(manifest), prepared_manifest_digest=digest(manifest))
        return output


def build_service(*, worker=False):
    from .storage import CompanyStore
    return CompanyProposalService(CompanyStore(worker=worker))


def validate_start_receipt(run, result):
    authority = decode_run_authority(run)
    admitted = {**run, "status": "queued", "cancel_requested": False, "completed_at": None, "result": None, "result_digest": None,
        "proposal_ids": [], "error": None}
    expected_hash = digest({"scope_type": "Company", "command": START_COMMAND, "company": authority.company,
        "project": None, "payload": {"request": run["request"]}})
    if run["request_kind"] != PROPOSAL_KIND or canonical(result) != canonical(CompanyProposalService._present(admitted)) or run["start_request_hash"] != expected_hash:
        raise RickyError("receipt_integrity", "The proposal Start receipt differs from its exact queued admission.")


@domain_errors
def authorize_receipt(actor, company, result, *, command, lock=False):
    if command not in {START_COMMAND, CANCEL_COMMAND} or type(result) is not dict or type(result.get("id")) is not str:
        raise RickyError("receipt_integrity", "This Company proposal receipt is unavailable.")
    service = build_service()
    run = service._ordered_run(result["id"], execution=False) if lock else service._load(company, result["id"])
    authority = decode_run_authority(run)
    if authority.user != actor.user or authority.person != actor.person_id or authority.company != company or run["request_kind"] != PROPOSAL_KIND:
        raise RickyError("not_found", "This original proposal Run is not accessible.")
    if command == START_COMMAND:
        validate_start_receipt(run, result)
        service._check(run, lock=lock)
    else:
        service.backend.authorize(authority, lock=lock)
        expected = service._stop(run)
        if (set(result) != set(expected) or result["status"] not in {"cancelled", "failed", "waiting-for-review"}
                or type(result["cancel_requested"]) is not bool or result["cancel_requested"] != (result["status"] == "cancelled")
                or any(type(result[key]) is not type(run[key]) or result[key] != run[key] for key in ("id", "company", "scope_type", "project", "request_kind"))):
            fail("A proposal Stop receipt must retain only its exact original terminal metadata.")


@domain_errors
def authorize_history(actor, company, run_id, *, lock=False):
    service = build_service()
    run = service._ordered_run(run_id, execution=False) if lock else service._load(company, run_id)
    authority = decode_run_authority(run)
    if authority.user != actor.user or authority.person != actor.person_id or authority.company != company:
        raise RickyError("not_found", "This original Company preparation is not accessible.")
    service._check(run, lock=lock)
