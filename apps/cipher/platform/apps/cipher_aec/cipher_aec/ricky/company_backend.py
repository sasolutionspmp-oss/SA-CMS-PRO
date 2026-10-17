"""Company deterministic-reader boundary. No models or domain write effects."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json

from .aec_backend import FrappeAECReader
from .aec_contracts import CompanyReadContext, identifier
from .company_contracts import CompanyAuthority, DeterministicReadRequest, decode_run_authority
from .contracts import RickyError, canonical, digest


START_COMMAND = "ricky.company.read.start.v1"
CANCEL_COMMAND = "ricky.company.read.cancel.v1"
MANIFEST_SCHEMA = "cipher.ricky.company.original-read.v1"
_start_session = ContextVar("cipher_company_ricky_new_start_session", default=None)


def unavailable():
    raise RickyError("not_found", "This Company Ricky record is not accessible.")


def _same_interactive_session(binding):
    import frappe
    from cipher_aec.governance.context import current_actor
    actor = current_actor()
    user, person, company, reference = binding
    sid = getattr(frappe.session, "sid", None)
    if (actor.user != user or actor.person_id != person or frappe.session.user != user
            or type(sid) is not str or not sid or sid == "Guest" or hashlib.sha256(sid.encode()).hexdigest() != reference):
        raise RickyError("session_revoked", "The interactive session changed during Company read admission.")
    return actor


@contextmanager
def start_session_binding(*, actor, company, reference):
    """Literal NEW command identity continuity, never a permission grant."""
    import re
    if (_start_session.get() is not None or type(company) is not str or not company
            or type(reference) is not str or re.fullmatch("[a-f0-9]{64}", reference) is None):
        raise RickyError("invalid_company_binding", "Use one exact canonical Company start session binding.")
    binding = actor.user, actor.person_id, company, reference
    _same_interactive_session(binding)
    token = _start_session.set(binding)
    try:
        yield
    finally:
        _start_session.reset(token)


def validate_resource_plan(plan):
    import re
    if type(plan) is not dict or set(plan) != {"unit_ids", "currencies", "native_refs", "generated_sources"}:
        raise RickyError("source_integrity", "Use the closed original source resource plan.")
    for key, maximum in (("unit_ids", 500), ("currencies", 20), ("native_refs", 1000), ("generated_sources", 0)):
        if type(plan[key]) is not list or len(plan[key]) > maximum:
            raise RickyError("source_integrity", "The source resource inventory is invalid or unqualified.")
    for value in plan["unit_ids"]:
        identifier(value)
    for value in plan["currencies"]:
        if type(value) is not str or re.fullmatch("[A-Z]{3}", value) is None:
            raise RickyError("source_integrity", "Use exact native currency names.")
    refs = []
    for row in plan["native_refs"]:
        if (type(row) is not dict or set(row) != {"doctype", "name"} or type(row["doctype"]) is not str
                or row["doctype"] not in {"Item", "Customer", "Supplier", "Lead", "Opportunity"}
                or type(row["name"]) is not str or not 1 <= len(row["name"]) <= 140
                or row["name"] != row["name"].strip() or any(ord(c) < 32 for c in row["name"])):
            raise RickyError("source_integrity", "Use exact supported native source names.")
        refs.append((row["doctype"], row["name"]))
    if (plan["unit_ids"] != sorted(set(plan["unit_ids"])) or plan["currencies"] != sorted(set(plan["currencies"]))
            or refs != sorted(set(refs))):
        raise RickyError("source_integrity", "The complete source plan must be sorted and unique.")
    return plan


def validate_manifest(value, request):
    """Closed persisted integrity shape, not a source authorization result."""
    import re
    def closed(row, fields):
        if type(row) is not dict or set(row) != set(fields):
            raise RickyError("source_integrity", "The original read manifest has invalid fields.")
    def sha(text):
        if type(text) is not str or re.fullmatch("[a-f0-9]{64}", text) is None:
            raise RickyError("source_integrity", "The original read digest is invalid.")
    def native_name(text):
        if type(text) is not str or not 1 <= len(text) <= 140 or any(ord(char) < 32 for char in text):
            raise RickyError("source_integrity", "The original native source name is invalid.")
    closed(value, {"schema", "selection_digest", "action_complete", "pursuit", "citations", "records", "owners"})
    if value["schema"] != MANIFEST_SCHEMA or value["selection_digest"] != request.selection_digest():
        raise RickyError("source_integrity", "The manifest has a different original read selection.")
    if type(value["action_complete"]) is not bool:
        raise RickyError("source_integrity", "The preparation standing must be explicit.")
    for field, maximum in (("citations", 8), ("records", 128), ("owners", 8)):
        if type(value[field]) is not list or len(value[field]) > maximum:
            raise RickyError("source_integrity", "The original source inventory exceeds its bounds.")
    pursuit = value["pursuit"]
    closed(pursuit, {"id", "digest", "party_type", "party_id", "opportunity", "native_refs"})
    if pursuit["id"] != request.pursuit_id or type(pursuit["party_type"]) is not str or pursuit["party_type"] not in {"Customer", "Lead"}:
        raise RickyError("source_integrity", "The original Pursuit binding is invalid.")
    sha(pursuit["digest"])
    native_name(pursuit["party_id"]); native_name(pursuit["opportunity"])
    expected_refs = sorted([(pursuit["party_type"], pursuit["party_id"]), ("Opportunity", pursuit["opportunity"])])
    if type(pursuit["native_refs"]) is not list or len(pursuit["native_refs"]) != 2:
        raise RickyError("source_integrity", "The complete original Pursuit native sources are required.")
    actual_refs = []
    for reference in pursuit["native_refs"]:
        closed(reference, {"doctype", "name"})
        native_name(reference["doctype"]); native_name(reference["name"])
        actual_refs.append((reference["doctype"], reference["name"]))
    if actual_refs != expected_refs:
        raise RickyError("source_integrity", "The original Pursuit native-source closure changed.")
    cited = set()
    for item in value["citations"]:
        closed(item, {"id", "digest"}); sha(item["id"]); sha(item["digest"])
        if item["id"] in cited:
            raise RickyError("source_integrity", "Duplicate original citation entries are invalid.")
        cited.add(item["id"])
    if cited != {ref.citation_id for ref in request.sources}:
        raise RickyError("source_integrity", "Every original selected citation must be retained.")
    records = set()
    for item in value["records"]:
        closed(item, {"domain", "kind", "id", "digest"})
        identifier(item["id"]); sha(item["digest"])
        if type(item["domain"]) is not str or type(item["kind"]) is not str or (item["domain"], item["kind"]) not in {
            ("estimate", "revision"), ("estimate", "snapshot"), ("estimate", "line"),
            ("takeoff", "measurement"), ("takeoff", "calibration"), ("takeoff", "verification")}:
            raise RickyError("source_integrity", "The original source kind is invalid.")
        key = item["domain"], item["kind"], item["id"]
        if key in records:
            raise RickyError("source_integrity", "Duplicate original record entries are invalid.")
        records.add(key)
    for record_id in request.measurement_ids:
        if ("takeoff", "measurement", record_id) not in records:
            raise RickyError("source_integrity", "Every selected measurement requires its exact original record.")
    owners = set()
    for owner in value["owners"]:
        closed(owner, {"id", "pursuit_id"}); identifier(owner["id"])
        if owner["pursuit_id"] != request.pursuit_id or owner["id"] in owners:
            raise RickyError("source_integrity", "The exact original estimate ownership is required.")
        owners.add(owner["id"])
    if value["action_complete"]:
        arguments = json.loads(request.arguments_json)
        required = [("estimate", "revision", arguments[key]) for key in
            ("revision_id", "left_revision_id", "right_revision_id") if key in arguments]
        if request.action == "aec.quantity.convert":
            required.append(("estimate", "line", arguments["source_id"]) if arguments["source_kind"] == "estimate-line"
                else ("takeoff", "measurement", arguments["source_id"]))
        if any(key not in records for key in required):
            raise RickyError("source_integrity", "The completed read omitted a requested original record.")
    return value


class CompanyBackend:
    """Actual Frappe authority; decoding a context never substitutes for this."""
    def require_effects_enabled(self):
        from cipher_aec.governance.context import require_effects_enabled
        require_effects_enabled()

    def admission_scope(self, authority, delegation_id):
        from .company_records import admission_pair
        return admission_pair(authority, delegation_id)

    @contextmanager
    def original_user(self, authority):
        import frappe
        previous = frappe.session.user
        frappe.set_user(authority.user)
        try:
            yield
        finally:
            frappe.set_user(previous)

    def bind(self, company, request, run_id):
        from cipher_aec.documents.provenance import has_prelocked
        if has_prelocked():
            raise RickyError("source_prelock_required", "A Company read cannot start inside another source operation.")
        from cipher_aec.governance.context import (require_company,
            require_session_authority, company_authority_fingerprint)
        binding = _start_session.get()
        if binding is None or binding[2] != company:
            raise RickyError("invalid_company_binding", "Company runs must start inside their canonical new command.")
        actor = _same_interactive_session(binding)
        reference = binding[3]
        # This exact Session row was already locked before Company/receipt by
        # the canonical literal command. Never adopt a renewed SID here.
        require_session_authority(actor, reference, lock=True)
        company_record = require_company(company, ability="ricky.run", actor=actor, lock=True)
        if company_record.name != company:
            unavailable()
        return CompanyAuthority(actor.user, actor.person_id, company, run_id,
            reference, company_authority_fingerprint(actor, company, lock=True),
            request.selection_digest())

    def authorize(self, authority, *, execution=False, lock=False):
        from cipher_aec.governance.context import (current_actor, require_company,
            require_session_authority, company_authority_fingerprint)
        if type(authority) is not CompanyAuthority:
            unavailable()
        actor = current_actor(lock=lock)
        if actor.user != authority.user or actor.person_id != authority.person:
            unavailable()
        if execution:
            # Session rows precede Company/receipt/Run. A fresh login can read
            # an old result, but never replace this original execution session.
            require_session_authority(actor, authority.session_reference, lock=lock)
        require_company(authority.company, ability="ricky.run", actor=actor, lock=lock)
        if execution and company_authority_fingerprint(actor, authority.company, lock=lock) != authority.authority_version:
            raise RickyError("stale_authority", "Company authority changed after this request was started.")
        return actor

    def require_permission(self, authority, ability):
        from cipher_aec.governance.context import require_company
        actor = self.authorize(authority, execution=True, lock=True)
        require_company(authority.company, ability=ability, actor=actor, lock=True)

    def observe_session(self, authority, actor):
        from cipher_aec.governance.context import require_session_authority
        # Read-only liveness observation. This is deliberately NOT worker
        # admission and never locks another Session after a receipt's Company.
        require_session_authority(actor, authority.session_reference, lock=False)

    def lock_original(self, run, *, execution=False):
        """Person/identity/session→Company→original Receipt, before Run locking."""
        import frappe
        from cipher_aec.documents.provenance import has_prelocked
        if has_prelocked():
            raise RickyError("source_prelock_required", "A Company run cannot lock inside another source operation.")
        authority = decode_run_authority(run)
        actor = self.authorize(authority, execution=execution, lock=True)
        expected_name = digest({"person": authority.person, "operation_id": run["operation_id"]})
        if run.get("start_receipt") != expected_name:
            raise RickyError("receipt_integrity", "The run has a different original command receipt.")
        rows = frappe.db.sql("SELECT person,scope_type,company,project,command,request_hash,result_json,result_hash,state "
            "FROM `tabCipher Command Receipt` WHERE name=%s FOR UPDATE", (expected_name,), as_dict=True)
        if len(rows) != 1:
            raise RickyError("receipt_integrity", "The original run admission receipt is unavailable.")
        row = rows[0]
        result = json.loads(row.result_json)
        if (type(result) is not dict or row.person != authority.person or row.scope_type != "Company" or row.company != authority.company
                or row.project not in (None, "") or row.command != START_COMMAND or row.state != "Succeeded"
                or row.request_hash != run.get("start_request_hash") or digest(result) != row.result_hash
                or result.get("id") != authority.run_id):
            raise RickyError("receipt_integrity", "The original run admission receipt does not match.")
        from .company_service import validate_start_receipt
        validate_start_receipt(run, result)
        return actor

    def reader(self, authority, request, *, lock=False, execution=True):
        return RunAECReader(self, authority, request, lock=lock, execution=execution)

    @contextmanager
    def source_scope(self, authority, request, manifest=None, *, lock=False, execution=False, expected_plan=None):
        """Run already locked: discover first, then one complete master union."""
        from cipher_aec.estimating import scopes
        from cipher_aec.estimating.lockplan import Discovery, prepared
        from cipher_aec.documents.provenance import has_prelocked
        if lock and has_prelocked():
            raise RickyError("source_prelock_required", "Ricky source discovery cannot inherit another operation's union.")
        actor = self.authorize(authority, execution=execution, lock=lock)
        with scopes.activate("Company", authority.company, None):
            if not lock:
                yield None
                return
            discovery = Discovery(authority.company, actor, lock=True)
            discovery.pursuit(request.pursuit_id)
            discovery.citations([{"revision_id": ref.revision_id} for ref in request.sources])
            for record_id in request.measurement_ids:
                discovery.record("takeoff", "measurement", record_id)
            arguments = json.loads(request.arguments_json)
            for key in ("revision_id", "left_revision_id", "right_revision_id"):
                if key in arguments:
                    discovery.record("estimate", "revision", arguments[key])
            if request.action == "aec.quantity.convert":
                discovery.record("takeoff" if arguments["source_kind"] == "measurement" else "estimate",
                    "measurement" if arguments["source_kind"] == "measurement" else "line", arguments["source_id"])
            if manifest is not None:
                validate_manifest(manifest, request)
                for item in manifest["records"]:
                    discovery.record(item["domain"], item["kind"], item["id"])
                discovery.native.update((ref["doctype"], ref["name"]) for ref in manifest["pursuit"]["native_refs"])
            plan = discovery.finish()
            if plan["generated_sources"]:
                raise RickyError("source_dependency_unqualified", "Generated inputs are not enabled for deterministic Company Ricky reads.")
            validate_resource_plan(plan)
            if expected_plan is not None:
                from cipher_aec.estimating.lockplan import resources
                validate_resource_plan(expected_plan)
                if any(not requested.issubset(original) for requested, original in zip(resources(plan), resources(expected_plan))):
                    raise RickyError("stale_source", "The fixed read source union grew after admission.")
            # MariaDB native names may compare case/accent-insensitively. Do
            # not let an alias change Python's order of the physical row locks.
            import frappe
            for row in [*plan["native_refs"], *({"doctype": "Currency", "name": value} for value in plan["currencies"])]:
                if frappe.db.get_value(row["doctype"], row["name"], "name") != row["name"]:
                    raise RickyError("source_integrity", "Native source aliases are not admitted as lock identities.")
            with prepared(plan, actor, authority.company):
                yield deepcopy(plan)

    def authorize_result(self, run, *, execution=False, lock=False, observation=False):
        authority = decode_run_authority(run)
        actor = self.authorize(authority, execution=execution, lock=lock)
        if observation:
            if execution:
                raise RickyError("invalid_company_binding", "Observation is not execution admission.")
            self.observe_session(authority, actor)
        request = DeterministicReadRequest.from_value(run["request"])
        if digest(run["original_manifest"]) != run["original_manifest_digest"]:
            raise RickyError("source_integrity", "The original manifest digest changed.")
        validate_resource_plan(run["resource_plan"])
        if digest(run["resource_plan"]) != run["resource_plan_digest"]:
            raise RickyError("source_integrity", "The original source lock plan changed.")
        with self.source_scope(authority, request, run["original_manifest"], lock=lock, execution=execution,
                expected_plan=run["resource_plan"] if execution else None):
            reader = self.reader(authority, request, lock=lock, execution=execution)
            return reader.verify_original(run["original_manifest"])


class RunAECReader(FrappeAECReader):
    """Canonical reader with original-run authority and exact retained facts.

    Observation collection is local to one deterministic preparation. Retained
    result authorization reopens canonical originals; it never reruns a tool.
    """
    def __init__(self, boundary, authority, request, *, lock=False, execution=True):
        self.boundary, self.authority, self.request = boundary, authority, request
        self.lock, self.execution = lock, execution
        self.context = request.read_context(authority)
        self.records = {}
        self.owners = {}
        self.pursuit_observation = None

    def actor(self, context, ability):
        from cipher_aec.governance.context import require_company
        if type(context) is not CompanyReadContext or context != self.context:
            unavailable()
        actor = self.boundary.authorize(self.authority, execution=self.execution, lock=self.lock)
        require_company(context.company, ability=ability, actor=actor, lock=self.lock)
        self._assert_scope(actor)
        return actor

    def _assert_scope(self, actor):
        if self.lock:
            from cipher_aec.estimating.lockplan import active_for
            if not active_for(actor, self.context.company):
                raise RickyError("source_prelock_required", "A locking Ricky reader requires its complete source scope.")

    def _observe(self, domain, kind, value):
        key = (domain, kind, value["id"])
        entry = {"domain": domain, "kind": kind, "id": value["id"], "digest": digest(value)}
        if key in self.records and self.records[key] != entry:
            raise RickyError("source_integrity", "An immutable source changed during preparation.")
        if len(self.records) >= 128 and key not in self.records:
            raise RickyError("resource_limit", "The bounded original-source manifest is full.")
        self.records[key] = entry

    def pursuit(self, context, actor):
        self._assert_scope(actor)
        from cipher_aec.commercial.service import _read
        value = _read("pursuit", context.pursuit_id, context.company, actor, lock=self.lock)[1]
        from cipher_aec.commercial.service import pursuit_source_plan
        plan = pursuit_source_plan(context.company, context.pursuit_id, actor=actor, lock=self.lock)
        observed = {"id": context.pursuit_id, "digest": digest(value),
            "party_type": value["party_type"], "party_id": value["party_id"], "opportunity": value["opportunity"],
            "native_refs": deepcopy(plan["native_refs"])}
        if self.pursuit_observation is None:
            self.pursuit_observation = observed
        return value

    def record(self, context, kind, record_id, actor):
        self._assert_scope(actor)
        from cipher_aec.estimating import scopes, service
        with scopes.activate("Company", context.company, None):
            value = service._scoped(kind, record_id, context.company, None, actor, lock=self.lock)
        if kind == "estimate":
            self.owners[value["id"]] = {"id": value["id"], "pursuit_id": value["pursuit_id"]}
        elif kind in {"revision", "snapshot", "line"}:
            self._observe("estimate", kind, value)
        else:
            raise RickyError("forbidden_tool", "This read cannot expand its record authority.")
        return value

    def _measurement(self, record_id, actor):
        self._assert_scope(actor)
        from cipher_aec.estimating import scopes
        from cipher_aec.takeoff import service
        with scopes.activate("Company", self.context.company, None):
            value = service._read("measurement", record_id, self.context.company, None, actor, lock=self.lock, new_use=False)
            self._observe("takeoff", "measurement", value)
            if value.get("calibration_id"):
                for kind, selected in (("calibration", value["calibration_id"]), ("verification", value["verification_id"])):
                    original = service._read(kind, selected, self.context.company, None, actor, lock=self.lock, new_use=False)
                    self._observe("takeoff", kind, original)
        self.raw_sources(self.context, [value["source"]["revision_id"],
            *(source["revision_id"] for source in self.measurement_sources(self.context, value, actor))], actor)
        return value

    def measurement(self, context, record_id, actor):
        from cipher_aec.takeoff import service
        value = self._measurement(record_id, actor)
        return value, service.current_use(value, actor, lock=self.lock)

    def measurement_sources(self, context, value, actor):
        self._assert_scope(actor)
        from cipher_aec.estimating import scopes
        from cipher_aec.takeoff.service import _verify_measurement_sources
        with scopes.activate("Company", context.company, None):
            return _verify_measurement_sources(value, actor, lock=self.lock)

    def citation(self, context, reference, actor):
        self._assert_scope(actor)
        from cipher_aec.documents.service import get_company_citation
        return get_company_citation(context.company, reference.revision_id, reference.page,
            excerpt_sha256=reference.excerpt_sha256, actor=actor, lock=self.lock)

    def raw_sources(self, context, revision_ids, actor):
        self._assert_scope(actor)
        from cipher_aec.documents.provenance import source_plan
        for record_id in sorted(set(revision_ids)):
            if source_plan(context.company, record_id, actor, lock=self.lock)["generated_sources"]:
                raise RickyError("source_dependency_unqualified", "Generated inputs are not enabled for deterministic Company Ricky reads.")

    def current_units(self, context, records, actor):
        self._assert_scope(actor)
        from cipher_aec.api.errors import DomainError
        from cipher_aec.estimating import scopes, units
        eligible = True
        with scopes.activate("Company", context.company, None):
            for original in records:
                try:
                    actual = units.qualified(original["id"], actor=actor, lock=self.lock)
                except DomainError as error:
                    if error.code != "unit_setup_required":
                        raise
                    eligible = False
                    continue
                eligible = eligible and actual == original
        return eligible

    def _selected(self, actor):
        selected = []
        for reference in self.context.sources:
            self.raw_sources(self.context, [reference.revision_id], actor)
            value = self.citation(self.context, reference, actor)
            if (value.get("scope_type") != "Company" or value.get("company") != self.context.company
                    or value.get("project") is not None or type(value.get("page")) is not int
                    or value.get("id") != reference.citation_id or value.get("revision_id") != reference.revision_id
                    or value.get("page") != reference.page or value.get("excerpt_sha256") != reference.excerpt_sha256
                    or value.get("source_sha256") != reference.source_sha256):
                raise RickyError("source_integrity", "A selected original citation cannot be verified.")
            selected.append({"id": reference.citation_id, "digest": digest(value)})
        # Deliberate selections are authority dependencies even when the fixed
        # action does not use them. These are Company-selected measurements;
        # there is no claim that a takeoff set belongs to this Pursuit.
        for record_id in self.context.measurement_ids:
            self._measurement(record_id, actor)
        return selected

    def prepare_selected(self):
        actor = self.actor(self.context, "commercial.read")
        self.pursuit(self.context, actor)
        self._selected(actor)

    def manifest(self, *, action_complete=False):
        actor = self.actor(self.context, "commercial.read")
        selected = self._selected(actor)
        value = {"schema": MANIFEST_SCHEMA, "selection_digest": self.request.selection_digest(), "action_complete": action_complete,
            "pursuit": deepcopy(self.pursuit_observation), "citations": selected,
            "records": [self.records[key] for key in sorted(self.records)],
            "owners": [self.owners[key] for key in sorted(self.owners)]}
        return validate_manifest(value, self.request)

    def verify_original(self, manifest):
        from cipher_aec.governance.context import require_company
        from cipher_aec.commercial import native
        validate_manifest(manifest, self.request)
        # Completion reads allow a fresh session of the exact original User.
        # Do not call actor(), current_use(), current_units() or AEC tools here.
        actor = self.boundary.authorize(self.authority, execution=self.execution, lock=self.lock)
        require_company(self.context.company, ability="commercial.read", actor=actor, lock=self.lock)
        current = self.pursuit(self.context, actor)
        observed = manifest["pursuit"]
        if current["id"] != self.context.pursuit_id or observed["id"] != current["id"]:
            unavailable()
        for reference in observed["native_refs"]:
            if set(reference) != {"doctype", "name"} or reference["doctype"] not in {"Customer", "Lead", "Opportunity"}:
                raise RickyError("source_integrity", "The retained native source is invalid.")
            value = native.require_native(reference["doctype"], reference["name"], actor, lock=self.lock)
            if reference["doctype"] == "Opportunity" and value.company != self.context.company:
                unavailable()
            if reference["doctype"] in {"Customer", "Lead"}:
                native.party(reference["doctype"], reference["name"], self.context.company, actor, lock=self.lock)
        for owner in manifest["owners"]:
            value = self.record(self.context, "estimate", owner["id"], actor)
            if value["pursuit_id"] != self.context.pursuit_id or owner["pursuit_id"] != value["pursuit_id"]:
                unavailable()
        stored_records = {(item["domain"], item["kind"], item["id"]): item for item in manifest["records"]}
        stored_owners = {item["id"] for item in manifest["owners"]}
        verified_records = {}
        for item in manifest["records"]:
            if item["domain"] == "estimate" and item["kind"] in {"revision", "snapshot", "line"}:
                value = self.record(self.context, item["kind"], item["id"], actor)
                # Lines have no citation collection of their own. Their exact
                # retained Revision/Snapshot closure below owns those sources.
                if item["kind"] in {"revision", "snapshot"}:
                    self.raw_records(self.context, [(item["kind"], value)], actor)
                if item["kind"] == "revision" and (value["estimate"] not in stored_owners
                        or ("estimate", "snapshot", value["calculation_snapshot"]) not in stored_records):
                    raise RickyError("source_integrity", "The original revision owner or snapshot was omitted.")
                if item["kind"] == "line" and ("estimate", "revision", value["estimate_revision"]) not in stored_records:
                    raise RickyError("source_integrity", "The original line revision was omitted.")
                if item["kind"] == "snapshot" and ("estimate", "revision", value["subject_id"]) not in stored_records:
                    raise RickyError("source_integrity", "The original snapshot revision was omitted.")
            elif item["domain"] == "takeoff" and item["kind"] in {"measurement", "calibration", "verification"}:
                from cipher_aec.estimating import scopes
                from cipher_aec.takeoff import service
                with scopes.activate("Company", self.context.company, None):
                    value = service._read(item["kind"], item["id"], self.context.company, None, actor, lock=self.lock, new_use=False)
            else:
                raise RickyError("source_integrity", "The retained source kind is invalid.")
            if value["id"] != item["id"] or digest(value) != item["digest"]:
                raise RickyError("source_integrity", "An original read dependency changed.")
            verified_records[item["domain"], item["kind"], item["id"]] = value
        # Reauthorize unused selected measurements and every selected citation;
        # no dependency DTO or stored result is returned before all pass.
        if canonical(self._selected(actor)) != canonical(manifest["citations"]):
            raise RickyError("source_integrity", "An original selected source changed.")
        retained = {(item["domain"], item["kind"], item["id"]): item for item in manifest["records"]}
        if any(retained.get(key) != item for key, item in self.records.items()):
            raise RickyError("source_integrity", "A selected record or calibration dependency was omitted or changed.")
        return verified_records
