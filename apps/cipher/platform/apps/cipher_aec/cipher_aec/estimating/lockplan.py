"""Internal Company producer dependency discovery and ordered lock admission.

Plans grant no content, result metadata or approval authority. Exact document,
commercial, baseline and native rights must still be rechecked afterward for the
passed actor. Context admission is scoped by actor/person/Company and reset on
all exits. Existing Project records/payloads are untouched.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

from cipher_aec.api.errors import DomainError
from . import scopes

_active = ContextVar("cipher_est_complete_source_locks", default=None)
MAX_RECORDS, MAX_SOURCES = 512, 128
MAX_UNITS, MAX_CURRENCIES, MAX_NATIVE = 500, 20, 1000


def identity(actor, company):
    return actor.user, actor.person_id, company


def resources(plan):
    return (frozenset(plan.get("unit_ids", [])), frozenset(plan.get("currencies", [])),
            frozenset((row["doctype"], row["name"]) for row in plan.get("native_refs", [])),
            frozenset((row["document_id"], row["input_digest"]) for row in plan.get("generated_sources", [])))


def _bounded(plan):
    if len(plan["unit_ids"]) > MAX_UNITS or len(plan["currencies"]) > MAX_CURRENCIES or len(plan["native_refs"]) > MAX_NATIVE or len(plan["generated_sources"]) > MAX_SOURCES:
        raise DomainError("source_limit", "The complete source dependency union exceeds its bounded lock budget.", 409)
    return plan


class Discovery:
    def __init__(self, company, actor, *, lock=False):
        if scopes.current(company, None).scope_type != "Company":
            raise DomainError("invalid_scope", "Producer source discovery requires explicit Company scope.", 422)
        self.company, self.actor, self.lock = company, actor, lock
        self.units, self.currencies, self.native, self.revisions = set(), set(), set(), set()
        self.visited, self.generated = set(), []

    def manifest(self, manifest):
        self.units.update(row["id"] for row in (manifest or {}).get("records", []) if row["kind"] == "uom")

    def citations(self, citations):
        from .contracts import fail, visible
        if type(citations) is not list:
            fail("Supply typed source citation references.", "source_citations")
        for row in citations:
            if type(row) is not dict or "revision_id" not in row:
                fail("Supply typed source citation references.", "source_citations")
            visible(row["revision_id"], "source.revision_id", 140)
            self.revisions.add(row["revision_id"])
        if len(self.revisions) > MAX_SOURCES:
            raise DomainError("source_limit", "The source revision discovery exceeds its bounded scope.", 409)

    def currency(self, value):
        import re
        if type(value) is not str or not re.fullmatch("[A-Z]{3}", value):
            raise DomainError("invalid_currency", "Use an uppercase three-letter currency code.", 422)
        self.currencies.add(value)

    def rates(self, rates):
        from .contracts import identifier, visible, fail
        for rate in rates:
            identifier(rate["unit_id"], "rate.unit_id")
            self.units.add(rate["unit_id"])
            self.currency(rate["currency"])
            if rate.get("item"):
                visible(rate["item"], "rate.item", 140)
                self.native.add(("Item", rate["item"]))
            if rate.get("party"):
                if type(rate.get("party_type")) is not str or rate["party_type"] not in {"Customer", "Supplier"}:
                    fail("Choose a supported native Customer or Supplier reference.", "rate.party_type")
                visible(rate["party"], "rate.party", 140)
                self.native.add((rate["party_type"], rate["party"]))
            self.citations(rate.get("source_citations", []))

    def pursuit(self, pursuit_id):
        if pursuit_id:
            from .sources import pursuit_plan
            plan = pursuit_plan(self.company, None, pursuit_id, self.actor, lock=self.lock)
            self.native.update((row["doctype"], row["name"]) for row in plan.get("native_refs", []))

    def value(self, domain, kind, value, *, current_bindings=False):
        key = domain, kind, value["id"], current_bindings if kind == "revision" else False
        if key in self.visited:
            return
        if len(self.visited) >= MAX_RECORDS:
            raise DomainError("source_limit", "Immutable dependency discovery exceeds its bounded record scope.", 409)
        self.visited.add(key)
        if not scopes.current(self.company, None).matches(value):
            raise DomainError("not_found", "This source record is not available.", 404)
        self.manifest(value.get("unit_manifest"))
        self.citations(value.get("source_citations", []))
        if domain == "estimate":
            if kind == "estimate":
                self.currency(value["currency"])
                self.pursuit(value.get("pursuit_id"))
            elif kind == "rate":
                self.rates([value["rate"]])
            elif kind == "assembly":
                self.rates(value["rates"].values())
            elif kind == "snapshot":
                self.manifest(value["inputs"]["unit_manifest"])
                self.currency(value["inputs"]["currency"])
                self.rates(value["inputs"]["rates"].values())
                if value.get("estimate"):
                    self.record("estimate", "estimate", value["estimate"])
            elif kind == "revision":
                self.record("estimate", "estimate", value["estimate"])
                self.record("estimate", "snapshot", value["calculation_snapshot"])
                if current_bindings:
                    from .governance import _binding_rows
                    for binding in _binding_rows(self.company, None, value["id"], lock=self.lock):
                        self.value("takeoff", "binding", binding)
            elif kind == "line":
                self.record("estimate", "revision", value["estimate_revision"])
            elif kind == "acceptance":
                facts = value["manifest"]["effect"]["facts"]
                self.record("estimate", "revision", value["estimate_revision"])
                self.units.update(row["id"] for row in facts["qualified_units"])
                self.native.update((row["doctype"], row["name"]) for row in facts["native_references"])
                for ref in facts["pinned_records"]:
                    self.record("estimate", ref["kind"], ref["id"])
                for ref in facts["bindings"]:
                    self.record("takeoff", "binding", ref["id"])
        else:
            if kind in {"calibration", "measurement"}:
                self.revisions.add(value["source"]["revision_id"])
                for conversion_id in value.get("conversion_ids", []):
                    self.record("estimate", "conversion", conversion_id)
                if kind == "measurement" and value["calibration_id"]:
                    self.record("takeoff", "calibration", value["calibration_id"])
            elif kind == "verification":
                self.record("takeoff", "calibration", value["calibration_id"])
            elif kind == "binding":
                self.record("takeoff", "measurement", value["measurement_id"])
                self.record("estimate", "line", value["estimate_line_record"])

    def record(self, domain, kind, name, *, current_bindings=False):
        from . import repository
        from cipher_aec.takeoff import repository as takeoffs
        value = (repository if domain == "estimate" else takeoffs).read(kind, name, lock=self.lock)
        self.value(domain, kind, value, current_bindings=current_bindings)
        return value

    def finish(self):
        from cipher_aec.documents.provenance import source_plan
        from cipher_aec.commercial.sources import merge
        if len(self.revisions) > MAX_SOURCES:
            raise DomainError("source_limit", "The source revision discovery exceeds its bounded scope.", 409)
        extra = [source_plan(self.company, name, self.actor, lock=self.lock) for name in sorted(self.revisions)]
        own = {"unit_ids": sorted(self.units), "currencies": sorted(self.currencies),
               "native_refs": [{"doctype": doctype, "name": name} for doctype, name in sorted(self.native)]}
        return _bounded(merge(own, *extra))


@contextmanager
def prepared(plan, actor, company, *, lock=True):
    """Admit producer authorization only after a complete ordered lock union."""
    from cipher_aec.documents.provenance import prelocked, is_prelocked, has_prelocked
    from cipher_aec.commercial.native import require_native
    from .units import qualified
    from cipher_aec.commercial.sources import merge
    if scopes.current(company, None).scope_type != "Company":
        raise DomainError("invalid_scope", "Producer source admission requires explicit Company scope.", 422)
    plan = deepcopy(_bounded(merge(plan)))
    active = _active.get()
    desired = resources(plan)
    if active is not None:
        if active[0] != identity(actor, company) or any(not requested.issubset(held) for requested, held in zip(desired, active[2])):
            raise DomainError("source_prelock_required", "The nested source plan exceeds the exact actor-scoped complete lock union.", 409)
        with prelocked(active[1], actor, company):
            yield deepcopy(active[1])
        return
    if not lock:
        raise DomainError("source_prelock_required", "A nonlocking source read cannot establish mutation admission.", 409)
    # A COM/DOC caller may already hold this complete union. Adoption must be
    # an exact immutable resource subset for the same user/person/Company;
    # this query grants no source rights and never acquires missing masters.
    already_held = is_prelocked(plan, actor, company)
    if has_prelocked() and not already_held:
        raise DomainError("source_prelock_required", "The source operation exceeds the caller's admitted complete dependency union.", 409)
    if lock and not already_held:
        for unit_id in plan["unit_ids"]:
            qualified(unit_id, lock=True, allow_disabled=True, actor=actor)
        for currency in plan["currencies"]:
            require_native("Currency", currency, actor, lock=True)
        for row in plan.get("native_refs", []):
            require_native(row["doctype"], row["name"], actor, lock=True)
    token = _active.set((identity(actor, company), plan, desired))
    try:
        with prelocked(plan, actor, company):
            yield deepcopy(plan)
    finally:
        _active.reset(token)


def admitted(plan, actor, company):
    active = _active.get()
    return active is not None and active[0] == identity(actor, company) and all(requested.issubset(held) for requested, held in zip(resources(plan), active[2]))


def active_for(actor, company):
    active = _active.get()
    return active is not None and active[0] == identity(actor, company)


def require_resources(plan, actor, company):
    if _active.get() is not None and not admitted(plan, actor, company):
        raise DomainError("source_prelock_required", "A source operation exceeds its exact actor-scoped complete dependency union.", 409)


def revision_plan(company, actor, revision_id, *, manifest=None, current_bindings=False, lock=False):
    discovery = Discovery(company, actor, lock=lock)
    discovery.record("estimate", "revision", revision_id, current_bindings=current_bindings)
    if manifest is not None:
        facts = manifest["effect"]["facts"]
        discovery.units.update(row["id"] for row in facts["qualified_units"])
        discovery.native.update((row["doctype"], row["name"]) for row in facts["native_references"])
        for ref in facts["pinned_records"]:
            discovery.record("estimate", ref["kind"], ref["id"])
        for ref in facts["bindings"]:
            discovery.record("takeoff", "binding", ref["id"])
    return discovery.finish()


def result_plan(company, actor, result, *, lock=False):
    discovery = Discovery(company, actor, lock=lock)
    for key, kind in (("conversion", "conversion"), ("rate_source", "rate"), ("assembly_revision", "assembly"), ("estimate", "estimate"), ("revision", "revision"), ("calculation", "snapshot"), ("acceptance", "acceptance")):
        if key in result:
            discovery.record("estimate", kind, result[key]["id"])
    for key, kind in (("takeoff_set", "set"), ("calibration", "calibration"), ("measurement", "measurement"), ("binding", "binding"), ("verification", "verification")):
        if key in result:
            discovery.record("takeoff", kind, result[key]["id"])
    if "unit" in result:
        discovery.units.add(result["unit"]["id"])
    return discovery.finish()


def command_plan(company, actor, command, payload):
    from .contracts import identifier, fail
    d = Discovery(company, actor, lock=True)
    def unit(value):
        identifier(value, "unit_id")
        d.units.add(value)
    def quantity(value):
        if type(value) is not dict or "unit_id" not in value:
            fail("A source quantity requires its explicit qualified unit.")
        unit(value["unit_id"])
    def refs(rows):
        d.citations(rows)
    def conversions(ids):
        if type(ids) is not list or len(ids) > 64:
            fail("Supply up to64 immutable conversion IDs.", "conversion_ids")
        for name in ids:
            d.record("estimate", "conversion", name)
    def source(value):
        if type(value) is not dict or type(value.get("revision_id")) is not str:
            fail("A drawing source requires its exact immutable revision.")
        d.revisions.add(value["revision_id"])
    if command == "estimate.conversion.create.v1":
        for key in ("from_unit_id", "to_unit_id"):unit(payload["definition"][key])
        refs(payload["source_citations"])
        if payload.get("predecessor"):d.record("estimate", "conversion", payload["predecessor"])
    elif command == "estimate.rate.create.v1":
        d.rates([payload["rate"]])
        if payload.get("predecessor"):d.record("estimate", "rate", payload["predecessor"])
    elif command == "estimate.assembly.create.v1":
        unit(payload["basis_unit_id"])
        for component in payload["components"]:
            if type(component) is not dict or "rate_source_id" not in component:
                fail("Each component requires an immutable rate source.", "components")
            d.record("estimate", "rate", component["rate_source_id"])
            quantity(component.get("work_quantity"));quantity(component.get("resource_quantity"))
        conversions(payload["conversion_ids"])
        if payload.get("predecessor"):d.record("estimate", "assembly", payload["predecessor"])
    elif command == "estimate.create.v1":
        d.currency(payload["currency"])
        d.pursuit(payload.get("pursuit_id"))
    elif command == "estimate.calculate.v1":
        d.record("estimate", "estimate", payload["estimate_id"])
        for line in payload["lines"]:
            if type(line) is not dict:
                fail("Each line requires an authored typed quantity.", "lines")
            quantity(line.get("quantity"))
            if line.get("assembly_revision_id"):
                d.record("estimate", "assembly", line["assembly_revision_id"])
            elif line.get("rate_source_id"):
                d.record("estimate", "rate", line["rate_source_id"])
        conversions(payload["conversion_ids"])
        refs(payload["basis_citations"])
    elif command in {"takeoff.calibration.create.v1", "takeoff.measurement.create.v1"}:
        source(payload["source"])
        definition = payload["definition"]
        if command == "takeoff.calibration.create.v1":
            quantity(definition.get("known_distance"))
            if type(definition.get("derived_units")) is not list:
                fail("Supply an explicit bounded derived unit relation list.")
            for relation in definition["derived_units"]:
                if type(relation) is not dict:
                    fail("A derived unit requires an explicit typed relation.")
                unit(relation.get("output_unit_id"));refs(relation.get("source_citations", []))
        else:
            unit(definition.get("result_unit_id"))
            if definition.get("depth"):quantity(definition["depth"])
            if definition.get("calibration_id"):d.record("takeoff", "calibration", definition["calibration_id"])
        conversions(payload["conversion_ids"])
        if payload.get("predecessor"):
            d.record("takeoff", "calibration" if command == "takeoff.calibration.create.v1" else "measurement", payload["predecessor"])
    elif command == "takeoff.line.bind.v1":
        d.record("takeoff", "measurement", payload["measurement_id"])
        d.record("estimate", "line", payload["estimate_line_record"])
    return d.finish()


def receipt_union(function):
    from functools import wraps
    @wraps(function)
    def wrapped(actor, company, project, result, scope_type="Project"):
        with scopes.activate(scope_type, company, project):
            if scope_type != "Company":
                return function(actor, company, project, result, scope_type=scope_type)
            scopes.require(company, project, ability="estimate.read", actor=actor, lock=True)
            plan = result_plan(company, actor, result, lock=True)
            with prepared(plan, actor, company):
                return function(actor, company, project, result, scope_type=scope_type)
    return wrapped


def approval_union(domain):
    """Wrap callbacks inside explicit_scope, before any eager source reader.

    Historical baseline use plans originals only. Pending packet reconstruction
    includes original plus current binding dependencies before master locking.
    """
    from functools import wraps
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            company, project, actor = kwargs["company"], kwargs["project"], kwargs["actor"]
            # Effect callbacks have no public lock argument: keep admission
            # alive through controller validation and the immutable insert.
            locking = kwargs.get("lock", function.__name__.startswith("apply_"))
            if not locking or scopes.current(company, project).scope_type != "Company":
                return function(*args, **kwargs)
            # The enclosing callback already acquired a complete immutable
            # actor-scoped union. Re-run the callback's actual authorization,
            # head/eligibility checks and bytes; avoid rediscovering the same
            # graph recursively. Resource guards refuse any union growth.
            if active_for(actor, company):
                return function(*args, **kwargs)
            scopes.require(company, project, ability="estimate.read", actor=actor, lock=True)
            subject_id = kwargs.get("subject_id")
            manifest = kwargs.get("manifest")
            if subject_id is None:
                subject_id = manifest["effect"]["revision_id" if domain == "estimate" else "calibration_id"]
            if domain == "estimate":
                plan = revision_plan(company, actor, subject_id, manifest=manifest,
                    current_bindings=kwargs.get("phase") not in {"baseline", "receipt"}, lock=True)
            else:
                discovery = Discovery(company, actor, lock=True)
                discovery.record("takeoff", "calibration", subject_id)
                plan = discovery.finish()
            with prepared(plan, actor, company):
                return function(*args, **kwargs)
        return wrapped
    return decorate
