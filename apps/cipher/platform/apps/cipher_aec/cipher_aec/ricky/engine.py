"""Bounded orchestration with durable authority, source and lease checkpoints."""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
import re
from uuid import UUID, uuid4

from .adapter import ConnectionProfile
from .contracts import Authority, Backend, Limits, ModelAdapter, ModelRequest, ModelResponse, RickyError, canonical, digest, iso, parse_time, utcnow
from .tools import default_registry, object_schema, validate


ACTIVE = ("queued", "retrieving", "generating", "executing", "reconciling")
FINAL = ("succeeded", "failed", "cancelled", "waiting-for-review")


def question_keywords(question: str) -> str:
    """Prepare an exact text query, with no semantic/embedding capability implied."""
    stopwords = frozenset("a an and are as at be been by can could did do does for from had has have how i in is it me my of on or our please should tell that the their them there these they this to us was we were what when where which who why will with would you your".split())
    words = [word for word in re.findall(r"[\w-]+", question, flags=re.UNICODE) if word.casefold() not in stopwords]
    return " ".join(dict.fromkeys(words))[:500] or question[:500]


class RickyService:
    def __init__(self, store, backend: Backend, adapter: ModelAdapter, *, limits: Limits | None = None,
                 profile: ConnectionProfile | None = None, clock=utcnow):
        self.store, self.backend, self.adapter = store, backend, adapter
        self.limits, self.profile, self.clock = limits or Limits(), profile or ConnectionProfile(), clock
        self.registry = default_registry()

    def _new(self, scope: Authority, **fields) -> dict:
        return {"id": str(uuid4()), "company": scope.company, "project": scope.project,
                "user": scope.user, "person": scope.person, "created_at": iso(self.clock()), **fields}

    def start(self, company: str, project: str, question: str, operation_id: str) -> dict:
        validate(object_schema({"question": {"type": "string", "minLength": 1, "maxLength": 2000}}, ("question",)), {"question": question})
        try:
            UUID(operation_id)
        except (ValueError, TypeError, AttributeError):
            raise RickyError("validation_error", "operation_id must be a UUID.") from None
        authority = self.backend.authority(company, project)
        self.backend.require_effects_enabled()
        operation_key = digest({"person": authority.person, "operation_id": operation_id})
        request_digest = digest({"authority": authority.binding(), "question": question, "version": 1})
        self.store.admission_lock(authority.person)
        existing = self.store.find("run", {"operation_key": operation_key}, limit=1)
        if existing:
            # Access was checked before even looking up a prior receipt.
            run = existing[0]
            self._check(run)
            if run["request_digest"] != request_digest:
                raise RickyError("operation_conflict", "This operation ID is already bound to another request.")
            return self._present(run)
        if self.store.count("run", {"person_id": authority.person, "status": ["in", list(ACTIVE)]}) >= self.limits.active_per_person:
            raise RickyError("rate_limit", "A Ricky request is already active for this person.", retryable=True)
        if self.store.count("run", {"status": ["in", list(ACTIVE)]}) >= self.limits.site_queue:
            raise RickyError("rate_limit", "The Ricky work queue is full.", retryable=True)
        delegation = self._new(authority, status="active", authority=authority.binding(),
                               allowed_tools=[item["name"] for item in self.registry.schemas()],
                               effect_classes=["read", "proposal"], limits=asdict(self.limits),
                               expires_at=iso(self.clock() + timedelta(seconds=self.limits.wall_seconds)),
                               grant_basis="authenticated-project-scoped-preparation", grantor=authority.person)
        self.store.insert("delegation", delegation)
        run = self._new(authority, status="queued", authority=authority.binding(), delegation_id=delegation["id"],
                        operation_id=operation_id, operation_key=operation_key, request_digest=request_digest,
                        question=question, sources=[], context=[], proposal_ids=[], tool_calls=0, retrieval_rounds=0, generations=0,
                        lease_token=0, lease_expires_at=None, cancel_requested=False, answer=None, citations=[],
                        error=None, prompt_version="cipher-r0-1", model_profile=self.profile.fingerprint(),
                        model_version="unverified", sampling={}, deadline=delegation["expires_at"], completed_effects=[])
        self.store.insert("run", run)
        return self._present(run)

    def _check(self, run: dict, *, sources: bool = True, worker: bool = False, revision: bool = True) -> Authority:
        authority = self.backend.authority(run["company"], run["project"], user=run["user"] if worker else None)
        if authority.person != run["person"] or authority.user != run["user"]:
            raise RickyError("not_found", "The requested Ricky record is not accessible.")
        if worker:
            self.backend.verify_session(Authority(**run["authority"]))
        original = run["authority"]
        if authority.authority_version != original["authority_version"]:
            raise RickyError("stale_authority", "Project authority changed. Start a new request with current access.")
        if revision and authority.project_revision != original["project_revision"]:
            raise RickyError("stale_source", "The project changed. Start a new request against its current revision.")
        if sources:
            self.backend.verify_sources(authority, run.get("sources", []))
        return authority

    def _delegation(self, run: dict) -> dict:
        delegation = self.store.get("delegation", run["delegation_id"])
        if delegation["status"] != "active" or self.clock() >= parse_time(delegation["expires_at"]):
            raise RickyError("expired_delegation", "Ricky preparation authority expired. Start a new request.")
        if delegation["authority"] != run["authority"]:
            raise RickyError("forbidden", "The run is outside its recorded delegation.")
        return delegation

    def get_run(self, identifier: str) -> dict:
        run = self.store.get("run", identifier)
        self._check(run, revision=False)
        return self._present(run)

    def get_proposal(self, identifier: str) -> dict:
        proposal = self.store.get("proposal", identifier)
        run = self.store.get("run", proposal["run_id"])
        self._check(run, revision=False)
        return self._proposal_present(proposal)

    def events(self, identifier: str) -> list[dict]:
        run = self.store.get("run", identifier)
        self._check(run, revision=False)
        return [{key: item.get(key) for key in ("id", "status", "tool_name", "created_at", "completed_at", "error", "input_digest", "output_digest")}
                for item in self.store.find("step", {"run_id": identifier})]

    def cancel(self, identifier: str) -> dict:
        run = self.store.get("run", identifier)
        authority = self._check(run, sources=False, revision=False)
        self.backend.lock_scope(authority, "ricky.run")
        run = self.store.get("run", identifier, lock=True)
        self._check(run, sources=False, revision=False)
        if run["status"] not in ("succeeded", "failed", "cancelled"):
            run["cancel_requested"] = True
            run["status"] = "cancelled"
            run["lease_token"] += 1
            run["completed_at"] = iso(self.clock())
            self.store.save("run", run)
        # Adapter cancellation is best effort and happens only after the request commits.
        return self._present(run)

    def claim(self, identifier: str) -> tuple[dict, int] | None:
        run = self.store.get("run", identifier, lock=True)
        if run["status"] in FINAL or run["cancel_requested"]:
            return None
        if run.get("lease_expires_at") and self.clock() < parse_time(run["lease_expires_at"]):
            return None
        self._check(run, worker=True)
        self._delegation(run)
        run["lease_token"] += 1
        run["lease_expires_at"] = iso(self.clock() + timedelta(seconds=self.limits.lease_seconds))
        run["status"] = "retrieving"
        self.store.save("run", run)
        self.store.checkpoint()
        return run, run["lease_token"]

    def _live(self, identifier: str, token: int) -> tuple[dict, Authority]:
        run = self.store.get("run", identifier, lock=True)
        if run["lease_token"] != token or run["cancel_requested"] or run["status"] == "cancelled":
            raise RickyError("cancelled", "This worker no longer owns the request.")
        if run["lease_expires_at"] and self.clock() >= parse_time(run["lease_expires_at"]):
            raise RickyError("lease_lost", "This worker's lease expired before its result was accepted.")
        if self.clock() >= parse_time(run["deadline"]):
            raise RickyError("resource_limit", "The interactive time budget was reached.")
        authority = self._check(run, worker=True)
        self._delegation(run)
        return run, authority

    def process(self, identifier: str) -> None:
        self.backend.require_effects_enabled()
        token = None
        try:
            claimed = self.claim(identifier)
            if claimed is None:
                return
            run, token = claimed
            if not self.adapter.status().get("available"):
                raise RickyError("upstream_unavailable", "The existing local Ricky model is unavailable. Your question is preserved.", retryable=True)
            execution = Execution(self, identifier, token)
            execution.invoke("project.lookup", {}, "initial-project")
            execution.invoke("document.search", {"query": question_keywords(run["question"]), "limit": 4}, "initial-documents")
            while True:
                run, _ = self._live(identifier, token)
                if not run["sources"]:
                    self._finish(identifier, token, ModelResponse("No accessible document evidence matched this question. Add a source document or refine the question.", model_version="not-invoked"))
                    return
                if run.get("generations", 0) >= self.limits.tool_calls + 1:
                    raise RickyError("resource_limit", "The model response-round budget was reached.")
                run["generations"] = run.get("generations", 0) + 1
                run["status"] = "generating"
                run["lease_expires_at"] = iso(self.clock() + timedelta(seconds=self.limits.lease_seconds))
                self.store.save("run", run)
                self.store.checkpoint()  # Never keep a DB transaction open during model I/O.
                response = self.adapter.generate(ModelRequest(identifier, run["question"], tuple(run["context"]),
                                                               self.registry.schemas(), run["deadline"]))
                if not isinstance(response, ModelResponse):
                    raise RickyError("invalid_model_output", "The adapter returned an invalid structured response.")
                if len(response.tool_requests) > self.limits.tool_calls:
                    raise RickyError("resource_limit", "The model requested too many tools.")
                if response.tool_requests:
                    for index, request in enumerate(response.tool_requests):
                        if type(request) is not dict or set(request) != {"name", "arguments"} or type(request["name"]) is not str:
                            raise RickyError("invalid_model_output", "Tool requests require only a registered name and typed arguments.")
                        execution.invoke(request["name"], request["arguments"], f"model-{run['tool_calls']}-{index}")
                    continue
                self._finish(identifier, token, response)
                return
        except RickyError as exc:
            self._fail(identifier, token, exc)
        except Exception as exc:
            if hasattr(exc, "code") and hasattr(exc, "message"):
                self._fail(identifier, token, RickyError(exc.code, exc.message))
                return
            self._fail(identifier, token, RickyError("internal_error", "Ricky could not finish this request. Its durable progress is preserved.", retryable=True))
            raise

    def _finish(self, identifier: str, token: int, response: ModelResponse) -> None:
        run, _ = self._live(identifier, token)
        if not isinstance(response.answer, str) or not response.answer.strip() or len(response.answer) > self.limits.answer_characters:
            raise RickyError("invalid_model_output", "The model answer exceeds the response contract.")
        if type(response.model_version) is not str or type(response.sampling) is not dict or len(canonical(response.sampling)) > 4096:
            raise RickyError("invalid_model_output", "The model metadata exceeds the response contract.")
        known = {source["citation_id"]: source for source in run["sources"]}
        if len(response.citations) > 8 or any(type(item) is not str or item not in known for item in response.citations):
            raise RickyError("invalid_citation", "The answer cites evidence outside the permitted source manifest.")
        if response.answer.strip() and known and not response.citations:
            raise RickyError("invalid_citation", "A source-based answer must cite its supplied evidence.")
        run.update(answer=response.answer, citations=list(dict.fromkeys(response.citations)),
                   model_version=response.model_version[:200], sampling=response.sampling,
                   status="waiting-for-review" if run["proposal_ids"] else "succeeded", completed_at=iso(self.clock()))
        self.store.save("run", run)
        self.store.checkpoint()

    def _fail(self, identifier: str, token: int | None, error: RickyError) -> None:
        run = self.store.get("run", identifier, lock=True)
        if token is not None and run["lease_token"] != token:
            return
        if run["status"] == "cancelled":
            return
        run.update(status="failed", error={"code": error.code, "message": error.message, "retryable": error.retryable}, completed_at=iso(self.clock()))
        self.store.save("run", run)
        self.store.checkpoint()

    def commit_proposal(self, identifier: str, proposal_version: int, operation_id: str) -> dict:
        proposal = self.store.get("proposal", identifier)
        run = self.store.get("run", proposal["run_id"])
        authority = self._check(run, revision=proposal["status"] != "applied")
        self.backend.lock_scope(authority, "task.create")
        run = self.store.get("run", proposal["run_id"], lock=True)
        proposal = self.store.get("proposal", identifier, lock=True)
        authority = self._check(run, revision=proposal["status"] != "applied")
        if type(proposal_version) is not int or proposal_version != proposal["version"]:
            raise RickyError("stale_proposal", "Review the current proposal version before saving.")
        if proposal["content_digest"] != digest({"fields": proposal["fields"], "sources": proposal["sources"], "authority": proposal["authority"], "version": proposal["version"]}):
            raise RickyError("stale_proposal", "The proposal content no longer matches its reviewed version.")
        if proposal["status"] == "applied":
            if proposal["apply_operation_id"] != operation_id:
                raise RickyError("operation_conflict", "This proposal was already saved with another operation ID.")
            return proposal["receipt"]
        if run["cancel_requested"]:
            raise RickyError("cancelled", "This request was cancelled; its proposed changes cannot be saved.")
        invocations = self.store.find("invocation", {"operation_key": proposal["operation_key"]}, limit=1)
        if (run["status"] != "waiting-for-review" or identifier not in run["proposal_ids"] or not invocations
                or invocations[0]["status"] != "succeeded" or invocations[0].get("run_id") != run["id"]
                or invocations[0].get("output", {}).get("proposal_id") != identifier
                or self.store.get("step", invocations[0]["step_id"])["status"] != "succeeded"):
            raise RickyError("incomplete_preparation", "Only a successfully prepared and reviewable proposed change can be saved.")
        if proposal["status"] != "proposed" or self.clock() >= parse_time(proposal["expires_at"]):
            raise RickyError("expired_proposal", "This proposal expired. Create and review a current proposal.")
        self.backend.require_effects_enabled()
        self.backend.verify_sources(authority, proposal["sources"])
        self.backend.verify_session(Authority(**run["authority"]))
        # Same deterministic command as the manual Task form, same transaction.
        receipt = self.backend.create_task(Authority(**run["authority"]), proposal["fields"], operation_id, proposal["sources"])
        proposal.update(status="applied", apply_operation_id=operation_id, receipt=receipt, applied_by=authority.person, applied_at=iso(self.clock()))
        self.store.save("proposal", proposal)
        run["completed_effects"].append({"proposal_id": identifier, "receipt": receipt})
        self.store.save("run", run)
        return receipt

    @staticmethod
    def _present(run: dict) -> dict:
        return {key: run.get(key) for key in ("id", "company", "project", "status", "question", "answer", "proposal_ids", "error", "cancel_requested", "created_at", "completed_at", "completed_effects")} | {
            "citations": [source for source in run["sources"] if source["citation_id"] in run.get("citations", [])],
            "model": {"profile_fingerprint": run["model_profile"], "version": run["model_version"], "prompt_version": run["prompt_version"]},
        }

    @staticmethod
    def _proposal_present(proposal: dict) -> dict:
        return {key: proposal.get(key) for key in ("id", "run_id", "status", "version", "fields", "sources", "content_digest", "expires_at", "receipt")}


class Execution:
    def __init__(self, service: RickyService, identifier: str, token: int):
        self.service, self.identifier, self.token = service, identifier, token
        self.run = None
        self.authority = None
        self.call_key = None

    def invoke(self, name: str, arguments: dict, logical_call: str) -> dict:
        service = self.service
        service.backend.require_effects_enabled()
        run, authority = service._live(self.identifier, self.token)
        delegation = service._delegation(run)
        tool = service.registry.definition(name)
        validate(tool.input_schema, arguments)
        service.backend.require_permission(authority, tool.required_permission)
        if name not in delegation["allowed_tools"] or tool.effect_class not in delegation["effect_classes"]:
            raise RickyError("forbidden_tool", "The tool is outside this preparation delegation.")
        self.call_key = digest({"run": run["id"], "logical_call": "proposal" if tool.effect_class == "proposal" else logical_call, "tool": name, "arguments": arguments})
        previous = service.store.find("invocation", {"operation_key": self.call_key}, limit=1)
        if previous:
            if previous[0]["status"] == "succeeded":
                return previous[0]["output"]
            # R0 tools have only reads or transaction-local proposals. No remote effects.
            if tool.effect_class not in ("read", "proposal"):
                raise RickyError("unknown_outcome", "The original tool operation requires readback.")
        if run["tool_calls"] >= delegation["limits"]["tool_calls"]:
            raise RickyError("resource_limit", "The tool-call budget was reached.")
        self.run, self.authority = run, authority
        run["tool_calls"] += 1
        run["status"] = "executing"
        step = service._new(authority, run_id=run["id"], status="claimed", tool_name=name, tool_version=tool.version,
                            input_digest=digest(arguments), operation_key=self.call_key, delegation_id=delegation["id"],
                            lease_token=self.token, source_revisions=[source["revision_id"] for source in run["sources"]])
        service.store.insert("step", step)
        service.store.save("run", run)
        savepoint = "ricky_tool_" + step["id"].replace("-", "")
        service.store.savepoint(savepoint)
        try:
            started = service.clock()
            output = service.registry.execute(name, arguments, self)
            if (service.clock() - started).total_seconds() > tool.timeout_seconds:
                raise RickyError("resource_limit", "The tool exceeded its reviewed execution time limit.")
            invocation = service._new(authority, run_id=run["id"], step_id=step["id"], status="succeeded", tool_name=name,
                                      tool_version=tool.version, operation_key=self.call_key, input_digest=digest(arguments),
                                      output_digest=digest(output), output=output, delegation_id=delegation["id"],
                                      source_revisions=[source["revision_id"] for source in self.run["sources"]], completed_at=iso(service.clock()))
            service.store.insert("invocation", invocation)
            step.update(status="succeeded", output_digest=invocation["output_digest"], completed_at=invocation["completed_at"])
            self.run["context"].append({"tool": name, "data": output})
            if len(canonical(self.run["context"])) > self.service.limits.context_characters + 4096:
                raise RickyError("resource_limit", "The model context budget was reached.")
            service.store.save("run", self.run)
            service.store.save("step", step)
            service.store.checkpoint()
            return output
        except Exception as exc:
            # Timeout, schema and result-size checks must roll back every local
            # handler effect, including a proposal or source reference insertion.
            service.store.rollback_to(savepoint)
            code = exc.code if hasattr(exc, "code") else "internal_error"
            message = exc.message if hasattr(exc, "message") else "The tool could not finish. Its local changes were rolled back."
            step.update(status="failed", error={"code": code, "message": message}, completed_at=iso(service.clock()))
            service.store.save("step", step)
            service.store.checkpoint()
            raise

    def project(self) -> dict:
        return self.service.backend.project(self.authority)

    def search(self, query: str, limit: int) -> dict:
        if self.run["retrieval_rounds"] >= self.service.limits.retrieval_rounds:
            raise RickyError("resource_limit", "The retrieval-round budget was reached.")
        self.run["retrieval_rounds"] += 1
        found = self.service.backend.search_documents(self.authority, query, limit)
        self.service.backend.verify_sources(self.authority, found)
        remaining = self.service.limits.context_characters - sum(len(source["excerpt"]) for source in self.run["sources"])
        selected, known = [], {source["citation_id"] for source in self.run["sources"]}
        for source in found:
            if source["citation_id"] in known:
                selected.append(source)
            elif len(source["excerpt"]) <= remaining:
                selected.append(source)
                self.run["sources"].append(source)
                remaining -= len(source["excerpt"])
                known.add(source["citation_id"])
                self.service.store.insert("artifact", self.service._new(self.authority, run_id=self.run["id"], status="referenced", source=source))
        return {"citations": selected}

    def propose(self, arguments: dict) -> dict:
        known = {source["citation_id"]: source for source in self.run["sources"]}
        if any(identifier not in known for identifier in arguments["citation_ids"]):
            raise RickyError("invalid_citation", "The proposal cites evidence outside the run source manifest.")
        sources = [known[identifier] for identifier in dict.fromkeys(arguments["citation_ids"])]
        if not sources:
            raise RickyError("missing_evidence", "A suggested Task must cite at least one accessible source.")
        fields = {"subject": arguments["subject"], "description": arguments["description"]}
        manifest = {"fields": fields, "sources": sources, "authority": self.authority.binding(), "version": 1}
        proposal = self.service._new(self.authority, run_id=self.run["id"], status="proposed", **manifest,
                                     content_digest=digest(manifest), expires_at=self.run["deadline"], operation_key=self.call_key)
        self.service.store.insert("proposal", proposal)
        self.run["proposal_ids"].append(proposal["id"])
        return {"proposal_id": proposal["id"], "proposal_version": 1, "status": "proposed"}
