"""Canonical Company suggestion sources; complete discovery precedes masters."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json

from .company_backend import CompanyBackend, RunAECReader, unavailable
from .company_contracts import decode_run_authority
from .company_proposal_contracts import (START_COMMAND, METHODS, MANIFEST_SCHEMA, RECORD_KINDS,
    DeterministicProposalRequest, validate_manifest, validate_resource_plan, fail)
from .contracts import RickyError, canonical, digest

_discovered = ContextVar("cipher_company_proposal_discovered", default=None)


class CompanyProposalBackend(CompanyBackend):
    def lock_original(self, run, *, execution=False):
        import frappe
        from cipher_aec.documents.provenance import has_prelocked
        if has_prelocked():
            raise RickyError("source_prelock_required", "Company proposal locking needs its own complete source union.")
        authority = decode_run_authority(run)
        actor = self.authorize(authority, execution=execution, lock=True)
        name = digest({"person": authority.person, "operation_id": run["operation_id"]})
        if run["start_receipt"] != name:
            fail("The proposal Run has a different original admission receipt.")
        rows = frappe.db.sql("SELECT person,scope_type,company,project,command,request_hash,result_json,result_hash,state "
            "FROM `tabCipher Command Receipt` WHERE name=%s FOR UPDATE", (name,), as_dict=True)
        if len(rows) != 1:
            raise RickyError("receipt_integrity", "The original proposal admission receipt is unavailable.")
        row = rows[0]
        result = json.loads(row.result_json)
        if (row.person != authority.person or row.scope_type != "Company" or row.company != authority.company
                or row.project not in (None, "") or row.command != START_COMMAND or row.state != "Succeeded"
                or row.request_hash != run["start_request_hash"] or digest(result) != row.result_hash):
            raise RickyError("receipt_integrity", "The original proposal command receipt does not match.")
        from .company_proposal_service import validate_start_receipt
        validate_start_receipt(run, result)
        return actor

    def reader(self, authority, request, *, lock=False, execution=True):
        return ProposalAECReader(self, authority, request, lock=lock, execution=execution)

    @contextmanager
    def source_scope(self, authority, request, manifest=None, *, lock=False, execution=False, expected_plan=None):
        from cipher_aec.estimating import scopes
        from cipher_aec.estimating.lockplan import Discovery, prepared, resources
        from cipher_aec.commercial import sources as commercial
        from cipher_aec.documents.provenance import has_prelocked
        actor = self.authorize(authority, execution=execution, lock=lock)
        with scopes.activate("Company", authority.company, None):
            if not lock:
                yield None
                return
            if has_prelocked() or _discovered.get() is not None:
                raise RickyError("source_prelock_required", "Proposal discovery cannot inherit another operation's source union.")

            class ProposalDiscovery(Discovery):
                def __init__(self):
                    super().__init__(authority.company, actor, lock=True)
                    self.originals = {}

                def value(self, domain, kind, value, *, current_bindings=False):
                    if (domain, kind) not in RECORD_KINDS and (domain, kind) != ("estimate", "estimate"):
                        fail("An unsupported immutable source cannot be omitted from proposal discovery.")
                    key = domain, kind, value["id"]
                    self.originals[key] = value
                    super().value(domain, kind, value, current_bindings=current_bindings)
                    if domain == "takeoff" and kind == "measurement" and value.get("verification_id"):
                        self.record("takeoff", "verification", value["verification_id"])

            discovery = ProposalDiscovery()
            discovery.pursuit(request.pursuit_id)
            discovery.citations([{"revision_id": ref.revision_id} for ref in request.sources])
            arguments = json.loads(request.arguments_json)
            extra = []
            commercial_ids = set()

            def commercial_revision(name):
                if name in commercial_ids:
                    return
                value = commercial.revision_record(authority.company, name, actor, lock=True)
                commercial_ids.add(name)
                extra.append(commercial.revision_plan(authority.company, name, actor, lock=True))
                reference = value["composition"].get("estimate_reference")
                if reference:
                    discovery.record("estimate", "acceptance", reference["acceptance_id"])

            if request.action == "aec.scope.draft":
                commercial_revision(arguments["proposal_revision_id"])
            else:
                discovery.record("estimate", "revision", arguments["base_revision_id"])
                for row in arguments["selections"]:
                    discovery.record("estimate", "line", row["line_record_id"])
                    discovery.record("estimate" if row["source_kind"] == "estimate-line" else "takeoff",
                        "line" if row["source_kind"] == "estimate-line" else "measurement", row["source_id"])
            for name in request.measurement_ids:
                discovery.record("takeoff", "measurement", name)
            if manifest is not None:
                validate_manifest(manifest, request)
                for row in manifest["records"]:
                    if row["domain"] == "commercial":
                        commercial_revision(row["id"])
                    else:
                        discovery.record(row["domain"], row["kind"], row["id"])
                discovery.native.update((row["doctype"], row["name"]) for row in manifest["pursuit"]["native_refs"])
            plan = commercial.merge(discovery.finish(), *extra)
            if plan["generated_sources"]:
                raise RickyError("source_dependency_unqualified", "Generated inputs remain unavailable for Company suggestions.")
            validate_resource_plan(plan)
            if expected_plan is not None:
                validate_resource_plan(expected_plan)
                if any(not requested.issubset(original) for requested, original in zip(resources(plan), resources(expected_plan))):
                    raise RickyError("stale_source", "The original proposal source union grew after admission.")
            import frappe
            for row in [*plan["native_refs"], *({"doctype": "Currency", "name": name} for name in plan["currencies"])]:
                if frappe.db.get_value(row["doctype"], row["name"], "name") != row["name"]:
                    fail("Native source aliases cannot change the proposal lock order.")
            keys = sorted(key for key in discovery.originals if key[1] != "estimate")
            keys.extend(("commercial", "proposal-revision", name) for name in sorted(commercial_ids))
            with prepared(plan, actor, authority.company):
                token = _discovered.set((canonical(authority.binding()), tuple(sorted(keys)), deepcopy(plan)))
                try:
                    yield deepcopy(plan)
                finally:
                    _discovered.reset(token)

    def authorize_result(self, run, *, execution=False, lock=False, observation=False):
        authority = decode_run_authority(run)
        actor = self.authorize(authority, execution=execution, lock=lock)
        if observation:
            self.observe_session(authority, actor)
        request = DeterministicProposalRequest.from_value(run["request"])
        validate_manifest(run["original_manifest"], request); validate_resource_plan(run["resource_plan"])
        if digest(run["original_manifest"]) != run["original_manifest_digest"] or digest(run["resource_plan"]) != run["resource_plan_digest"]:
            fail("Original proposal source bindings changed.")
        with self.source_scope(authority, request, run["original_manifest"], lock=lock, execution=execution,
                expected_plan=run["resource_plan"] if execution else None):
            reader = self.reader(authority, request, lock=lock, execution=execution)
            originals = reader.verify_original(run["original_manifest"])
            if execution:
                reader.prepare_selected()
                current = reader.manifest(action_complete=run["original_manifest"]["action_complete"])
                if canonical(current) != canonical(run["original_manifest"]):
                    raise RickyError("stale_source", "The original preparation head, quantity standing or source changed.")
            return originals


class ProposalAECReader(RunAECReader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.heads, self.qualified, self.standing = {}, {}, {}

    def _owner(self, domain, kind, value):
        pursuit = value["pursuit"] if domain == "commercial" else value["pursuit_id"]
        if value["company"] != self.context.company or pursuit != self.context.pursuit_id:
            unavailable()
        key = domain, value["id"]
        self.owners[key] = {"domain": domain, "kind": kind, "id": value["id"], "pursuit_id": pursuit, "digest": digest(value)}
        return value

    def proposal_revision(self, context, record_id, actor):
        from cipher_aec.commercial.service import _read
        self._assert_scope(actor)
        value = _read("revision", record_id, context.company, actor, lock=self.lock)[1]
        self._observe("commercial", "proposal-revision", value)
        self.raw_proposal(context, value, actor)
        return value

    def proposal(self, context, record_id, actor):
        from cipher_aec.commercial.service import _read
        self._assert_scope(actor)
        value = _read("proposal", record_id, context.company, actor, lock=self.lock)[1]
        selected = json.loads(self.request.arguments_json)["proposal_revision_id"]
        if value["current_revision"] != selected:
            raise RickyError("stale_source", "Prepare from the exact current commercial revision.")
        # Exactly the canonical get_proposal DTO, under the admitted union.
        return self._owner("commercial", "proposal", {**value, "revision": self.proposal_revision(context, selected, actor)})

    def raw_proposal(self, context, revision, actor):
        self._assert_scope(actor)
        from cipher_aec.commercial.sources import plan
        if plan(revision["composition"], context.company, actor, lock=self.lock)["generated_sources"]:
            raise RickyError("source_dependency_unqualified", "Generated commercial sources remain unavailable.")
        reference = revision["composition"].get("estimate_reference")
        if reference:
            self.record(context, "acceptance", reference["acceptance_id"], actor)

    def record(self, context, kind, record_id, actor):
        from cipher_aec.estimating import scopes, service
        self._assert_scope(actor)
        with scopes.activate("Company", context.company, None):
            reader = service._scoped_original if not self.execution and kind in {"conversion", "line", "revision", "snapshot"} else service._scoped
            value = reader(kind, record_id, context.company, None, actor, lock=self.lock)
        if kind == "estimate":
            self._owner("estimate", "estimate", value)
        elif ("estimate", kind) in RECORD_KINDS:
            observed = ("estimate", kind, value["id"]) in self.records
            self._observe("estimate", kind, value)
            if kind in {"revision", "snapshot", "conversion", "rate", "assembly"}:
                self.raw_records(context, [(kind, value)], actor)
            if not observed and kind == "revision":
                self.record(context, "estimate", value["estimate"], actor)
                self.record(context, "snapshot", value["calculation_snapshot"], actor)
            elif not observed and kind == "snapshot":
                self.record(context, "revision", value["subject_id"], actor)
            elif not observed and kind == "line":
                self.record(context, "revision", value["estimate_revision"], actor)
            elif not observed and kind == "acceptance":
                self.record(context, "revision", value["estimate_revision"], actor)
                facts = value["manifest"]["effect"]["facts"]
                for row in facts["pinned_records"]:
                    self.record(context, row["kind"], row["id"], actor)
                for row in facts["bindings"]:
                    self.dependency("takeoff", "binding", row["id"], actor)
        else:
            fail("The estimate dependency kind is unsupported.")
        return value

    def dependency(self, domain, kind, name, actor):
        if domain == "commercial":
            return self.proposal_revision(self.context, name, actor)
        if domain == "estimate":
            return self.record(self.context, kind, name, actor)
        from cipher_aec.takeoff import service
        from cipher_aec.estimating import scopes
        with scopes.activate("Company", self.context.company, None):
            reader = service._read if self.execution else service._read_original
            value = reader(kind, name, self.context.company, None, actor, lock=self.lock)
        observed = ("takeoff", kind, name) in self.records
        self._observe("takeoff", kind, value)
        if kind in {"calibration", "measurement"}:
            citations = self.measurement_sources(self.context, value, actor) if kind == "measurement" else value.get("source_citations", [])
            self.raw_sources(self.context, [value["source"]["revision_id"],
                *(row["revision_id"] for row in citations)], actor)
        if not observed:
            for record_id in value.get("conversion_ids", []):
                self.record(self.context, "conversion", record_id, actor)
            if kind == "measurement" and value.get("calibration_id"):
                self.dependency("takeoff", "calibration", value["calibration_id"], actor)
                self.dependency("takeoff", "verification", value["verification_id"], actor)
            elif kind == "verification":
                self.dependency("takeoff", "calibration", value["calibration_id"], actor)
            elif kind == "binding":
                self.dependency("takeoff", "measurement", value["measurement_id"], actor)
                self.record(self.context, "line", value["estimate_line_record"], actor)
        return value

    def _measurement(self, name, actor):
        return self.dependency("takeoff", "measurement", name, actor)

    def measurement(self, context, record_id, actor):
        from cipher_aec.takeoff.service import current_use
        value = self._measurement(record_id, actor)
        current = current_use(value, actor, lock=self.lock)
        self.standing[record_id] = {"measurement_id": record_id, "eligible": current["eligible"],
            "verification_id": current["verification"]["id"] if current.get("verification") else None, "digest": digest(current)}
        return value, current

    def current_units(self, context, records, actor):
        eligible = super().current_units(context, records, actor)
        for row in records:
            self.qualified[row["id"]] = {"id": row["id"], "digest": digest(row)}
        return eligible

    def _head(self, domain, owner, revision):
        if owner["current_revision"] != revision["id"]:
            raise RickyError("stale_source", "The original selected revision is no longer the working head.")
        self.heads[domain, owner["id"]] = {"domain": domain, "owner_id": owner["id"], "revision_id": revision["id"], "digest": digest(revision)}

    def prepare_selected(self):
        actor = self.actor(self.context, "commercial.read")
        self.actor(self.context, METHODS[self.request.action][1])
        self.pursuit(self.context, actor); self._selected(actor)
        discovered = _discovered.get()
        if discovered is None or discovered[0] != canonical(self.authority.binding()):
            raise RickyError("source_prelock_required", "Proposal preparation requires its complete discovered source union.")
        for domain, kind, name in discovered[1]:
            self.dependency(domain, kind, name, actor)
        arguments = json.loads(self.request.arguments_json)
        if self.request.action == "aec.scope.draft":
            revision = self.proposal_revision(self.context, arguments["proposal_revision_id"], actor)
            owner = self.proposal(self.context, revision["proposal"], actor)
            self._head("commercial", owner, revision)
        else:
            from .aec_backend import AECBackend
            backend = AECBackend(self.context, reader=self)
            revision, owner, _, _ = backend._bundle(arguments["base_revision_id"], actor)
            self._head("estimate", owner, revision)
            for row in arguments["selections"]:
                # Canonical deterministic quantity validation is a read, never
                # a proposal/domain write or a model-supplied numeric value.
                value = backend._quantity({key: row[key] for key in ("source_kind", "source_id", "target_unit_id")}, actor)
                if not value["eligible_for_new_use"]:
                    raise RickyError("stale_source", "A selected quantity is no longer eligible for new preparation.")
                if row["source_kind"] == "estimate-line":
                    line = self.record(self.context, "line", row["source_id"], actor)
                    revision, owner, _, _ = backend._bundle(line["estimate_revision"], actor)
                    self._head("estimate", owner, revision)

    def manifest(self, *, action_complete=False):
        actor = self.actor(self.context, "commercial.read")
        value = {"schema": MANIFEST_SCHEMA, "selection_digest": self.request.selection_digest(), "action_complete": action_complete,
            "pursuit": deepcopy(self.pursuit_observation), "citations": self._selected(actor),
            "records": [self.records[key] for key in sorted(self.records)], "owners": [self.owners[key] for key in sorted(self.owners)],
            "preparation_heads": [self.heads[key] for key in sorted(self.heads)],
            "qualified_units": [self.qualified[key] for key in sorted(self.qualified)], "quantity_standing": [self.standing[key] for key in sorted(self.standing)]}
        return validate_manifest(value, self.request)

    def verify_original(self, manifest):
        from cipher_aec.governance.context import require_company
        from cipher_aec.commercial import native, service
        validate_manifest(manifest, self.request)
        actor = self.boundary.authorize(self.authority, execution=self.execution, lock=self.lock)
        require_company(self.context.company, ability="commercial.read", actor=actor, lock=self.lock)
        require_company(self.context.company, ability=METHODS[self.request.action][1], actor=actor, lock=self.lock)
        self.pursuit(self.context, actor)
        for row in manifest["pursuit"]["native_refs"]:
            value = native.require_native(row["doctype"], row["name"], actor, lock=self.lock)
            if row["doctype"] == "Opportunity" and value.company != self.context.company:
                unavailable()
            if row["doctype"] in {"Customer", "Lead"}:
                native.party(row["doctype"], row["name"], self.context.company, actor, lock=self.lock)
        for row in manifest["owners"]:
            if row["domain"] == "commercial":
                # Current owner/native identity only: never fetch its successor
                # revision or require old prepared content to equal a new head.
                owner = service._read("proposal", row["id"], self.context.company, actor, lock=self.lock)[1]
                self._owner("commercial", "proposal", owner)
            else:
                self.record(self.context, "estimate", row["id"], actor)
        originals = {}
        for row in manifest["records"]:
            value = self.dependency(row["domain"], row["kind"], row["id"], actor)
            if value["id"] != row["id"] or digest(value) != row["digest"]:
                fail("An immutable original proposal dependency changed.")
            originals[row["domain"], row["kind"], row["id"]] = value
        if canonical(self._selected(actor)) != canonical(manifest["citations"]):
            fail("An original selected citation or measurement changed.")
        retained = {(row["domain"], row["kind"], row["id"]): row for row in manifest["records"]}
        if any(retained.get(key) != row for key, row in self.records.items()):
            fail("The original complete dependency closure was omitted.")
        recorded_owners = {(row["domain"], row["kind"], row["id"], row["pursuit_id"]) for row in manifest["owners"]}
        if any((row["domain"], row["kind"], row["id"], row["pursuit_id"]) not in recorded_owners for row in self.owners.values()):
            fail("An original revision owner was omitted from its source closure.")
        for reference in self.request.sources:
            originals["documents", "citation", reference.citation_id] = self.citation(self.context, reference, actor)
        return originals
