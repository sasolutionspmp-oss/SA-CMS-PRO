"""Literal generated-source authority over the existing canonical documents.

Dependency discovery never grants access to content. Mutation callers must merge
its plan with their own source plan before taking any UOM/Currency/native locks.
The bounded ancestry guard allows the same source through independent branches.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json

from cipher_aec.api.contracts import digest, canonical_json
from cipher_aec.api.errors import DomainError

PRODUCER = "commercial.proposal.output.v1"
MAX_DEPTH, MAX_NODES, QUERY_SCAN_CAP = 8, 128, 500
_prelocked = ContextVar("cipher_document_provenance_prelocked", default=None)
_walk = ContextVar("cipher_document_provenance_walk", default=None)
_locked_original = ContextVar("cipher_document_provenance_locked_original", default=None)
_operation = ContextVar("cipher_document_provenance_logical_operation", default=None)
_reading = ContextVar("cipher_document_provenance_read_graph", default=None)


def _denied():
    raise DomainError("not_found", "This source is not available.", 404)


def binding(row):
    kind = row.get("producer_kind")
    if not kind:
        if any(row.get(key) for key in ("producer_reference", "producer_input_digest", "producer_binding_json")):
            raise DomainError("source_integrity", "Generated source metadata cannot be verified.", 409)
        return None
    if kind != PRODUCER or row.get("scope_type") != "Company" or row.get("project") is not None:
        _denied()
    try:
        value = json.loads(row["producer_binding_json"])
        expected_keys = {"schema", "company", "proposal_id", "proposal_revision_id", "proposal_revision_digest", "native_fingerprint", "accepted_estimate", "source_citations", "recipients", "cover", "renderer"}
        if (type(value) is not dict or set(value) != expected_keys or len(row["producer_binding_json"].encode()) > 4 * 1024 * 1024
                or value["schema"] != "cipher.proposal.output.input.v1"
                or type(value["accepted_estimate"]) is not dict or type(value["source_citations"]) is not list
                or type(value["recipients"]) is not list or not 1 <= len(value["recipients"]) <= 30
                or type(value["cover"]) is not str or type(value["renderer"]) is not dict
                or value["company"] != row["company"] or value["proposal_revision_id"] != row["producer_reference"]
                or digest(value) != row["producer_input_digest"]):
            raise ValueError
    except (KeyError, ValueError, TypeError):
        raise DomainError("source_integrity", "Generated source metadata cannot be verified.", 409) from None
    return value


@contextmanager
def _visit(document_id, actor, company, phase, *, memo_key=None):
    active = _walk.get()
    identity = (actor.user, actor.person_id, company, phase)
    root = active is None or active["identity"] != identity
    state = {"identity": identity, "stack": [], "memo": {}, "count": 0} if root else active
    token = _walk.set(state) if root else None
    try:
        if document_id in state["stack"]:
            raise DomainError("cyclic_source", "Generated sources contain a cyclic dependency.", 409)
        if (document_id if memo_key is None else memo_key) in state["memo"]:
            yield state, True
            return
        state["count"] += 1
        if len(state["stack"]) >= MAX_DEPTH or state["count"] > MAX_NODES:
            raise DomainError("source_limit", "Generated source dependencies exceed the bounded authorization limit.", 409)
        state["stack"].append(document_id)
        try:
            yield state, False
        finally:
            state["stack"].pop()
    finally:
        if token is not None:
            _walk.reset(token)


def _document(row, *, lock=False):
    if "producer_kind" in row and not row.get("document"):
        return row
    from .repository import FrappeDocumentRepository
    parent = FrappeDocumentRepository("Company").document(row.get("document") or row["name"], lock=lock)
    if "producer_kind" in row and any((row.get(key) or None) != (parent.get(key) or None) for key in ("producer_kind", "producer_reference", "producer_input_digest", "producer_binding_json")):
        raise DomainError("source_integrity", "Revision producer bindings cannot be verified.", 409)
    return parent


def authorize(row, actor, *, lock=False):
    """Current producer-source authorization; never follows its output document."""
    from cipher_aec.document_control.rights import authorize as authorize_rights
    from cipher_aec.quality_safety.privacy import authorize_source as authorize_incident_source
    authorize_incident_source(row, actor, lock=lock)
    authorize_rights(row,actor,lock=lock)
    if (row.get('scope_type') or 'Project') == 'Project':
        return
    reading = _reading.get()
    if lock and reading is not None:
        raise DomainError("source_prelock_required", "A read graph cannot authorize a locking source operation.", 409)
    parent = _document(row, lock=lock)
    if reading is not None:
        _check_read_graph(reading, actor, parent["company"])
    value = binding(parent)
    if value is None:
        return
    phase = "authorize.locked-original-v1" if lock else "authorize.read-v1"
    held = _prelocked.get() if lock else None
    memo_key = (parent["name"], parent["producer_input_digest"], held)
    # Enter ancestry even for a memo hit: cycles never become shared DAG nodes.
    with _visit(parent["name"], actor, parent["company"], phase, memo_key=memo_key) as (state, reused):
        if lock:
            expected = (parent["name"], parent["producer_input_digest"])
            if (held is None or held[:3] != (actor.user, actor.person_id, parent["company"])
                    or expected not in held[3] or not _admission_valid()):
                raise DomainError("source_prelock_required", "This generated source requires complete dependency lock planning before mutation.", 409)
        memo = _locked_original.get() if lock else reading
        key = (phase, held if lock else reading["identity"] if reading else None,
               parent["name"], parent["producer_input_digest"])
        if reused or (memo is not None and key in memo["authorized"]):
            if memo is not None:
                memo["stats"]["producer_hits"] += 1
            return
        if memo is not None:
            memo["stats"]["producer_misses"] += 1
        if lock:
            from cipher_aec.commercial.output_sources import binding_plan
            if not is_prelocked(binding_plan(value, actor, lock=True), actor, parent["company"]):
                raise DomainError("source_prelock_required", "This generated source requires complete dependency lock planning before mutation.", 409)
        from cipher_aec.commercial.output_sources import authorize_binding
        authorize_binding(value, actor, lock=lock)
        state["memo"][memo_key] = True
        if memo is not None:
            # Cache capacity is optional; actual DAG/depth bounds remain hard.
            # Saturated entries continue full authorization on every visit.
            if len(memo["authorized"]) < MAX_NODES:
                memo["authorized"].add(key)
            memo["stats"]["producer_authorized"] += 1


def source_plan(company, revision_id, actor, *, lock=False):
    """Internal immutable dependency IDs; no text/bytes or public authorization."""
    from cipher_aec.governance.context import require_company
    from .repository import FrappeDocumentRepository
    from .scope import scope_of
    require_company(company, ability="document.read", actor=actor, lock=lock)
    repo = FrappeDocumentRepository("Company")
    locator = repo.revision_locator(revision_id)
    if scope_of(locator) != "Company" or locator["company"] != company:
        _denied()
    parent = repo.document(locator["document"], lock=lock)
    if scope_of(parent) != "Company" or parent["company"] != company:
        _denied()
    value = binding(parent)
    empty = {"unit_ids": [], "currencies": [], "native_refs": [], "generated_sources": []}
    if value is None:
        return empty
    with _visit(parent["name"], actor, company, "plan") as (state, reused):
        if reused:
            return state["memo"][parent["name"]]
        from cipher_aec.commercial.output_sources import binding_plan
        result = binding_plan(value, actor, lock=lock)
        nodes = {(row["document_id"], row["input_digest"]) for row in result.get("generated_sources", [])}
        nodes.add((parent["name"], parent["producer_input_digest"]))
        result["generated_sources"] = [{"document_id": name, "input_digest": checksum} for name, checksum in sorted(nodes)]
        state["memo"][parent["name"]] = result
        return result


def producer_fields(value):
    """Server-only fields; public upload never accepts this argument."""
    row = {"scope_type": "Company", "company": value.get("company"), "project": None,
           "producer_kind": PRODUCER, "producer_reference": value.get("proposal_revision_id"),
           "producer_input_digest": digest(value), "producer_binding_json": canonical_json(value)}
    binding(row)
    return {key: row[key] for key in ("producer_kind", "producer_reference", "producer_input_digest", "producer_binding_json")}


def mutation_source_identity(company, revision_id, actor):
    """Metadata-only preflight immediately before a canonical mutation read.

    This grants neither source authority nor resource admission. Generated
    sources need their exact node in the caller's existing complete lock token;
    the following canonical citation/source reader still checks the full
    resource subset, original permissions, availability and actual bytes.
    """
    from cipher_aec.governance.context import require_company
    from .repository import FrappeDocumentRepository
    require_company(company, ability="document.read", actor=actor, lock=True)
    if type(revision_id) is not str or not 1 <= len(revision_id) <= 140:
        _denied()
    repo = FrappeDocumentRepository("Company")
    locator = repo.revision_locator(revision_id)
    def exact_scope(row):
        return row.get("scope_type") == "Company" and row.get("company") == company and row.get("project") is None
    if not exact_scope(locator) or locator.get("name") != revision_id:
        _denied()
    # The immutable locator discovers identity only. Current locking reads take
    # the parent before its revision, as the canonical document command does.
    parent = repo.document(locator["document"], lock=True)
    if not exact_scope(parent) or parent.get("name") != locator["document"]:
        _denied()
    revision = repo.revision(revision_id, lock=True)
    if not exact_scope(revision):
        _denied()
    fields = ("producer_kind", "producer_reference", "producer_input_digest", "producer_binding_json")
    if (revision.get("name") != revision_id or revision.get("document") != parent["name"]
            or any((revision.get(field) or None) != (parent.get(field) or None) for field in fields)):
        raise DomainError("source_integrity", "The source revision identity cannot be verified.", 409)
    generated = binding(parent) is not None
    checksum = parent.get("producer_input_digest") if generated else None
    if generated:
        held = _prelocked.get()
        if (held is None or held[:3] != (actor.user, actor.person_id, company)
                or (parent["name"], checksum) not in held[3] or not _admission_valid()):
            raise DomainError("source_prelock_required", "This generated source requires its exact existing dependency lock admission.", 409)
    return {"generated": generated, "document_id": parent["name"],
            "revision_id": revision_id, "input_digest": checksum}


@contextmanager
def prelocked(plan, actor, company):
    """Trusted domain boundary AFTER the complete union has been acquired.

    This is not a public API or an alternative source authorization. Nested reads
    authorize original current permissions once per exact admitted token/node,
    and always recheck exact bytes. Without a logical_operation the memo ends
    at outer prelocked exit; otherwise only the private command lifetime owns
    the store. Neither context can cross a transaction boundary.
    """
    if _reading.get() is not None:
        raise DomainError("source_prelock_required", "A read graph cannot establish source mutation admission.", 409)
    nodes = frozenset((row["document_id"], row["input_digest"]) for row in plan.get("generated_sources", []))
    resources = _resources(plan)
    previous = _prelocked.get()
    operation = _operation.get()
    if operation is not None and (not operation["valid"] or operation["identity"][0] != company):
        raise DomainError("source_prelock_required", "A callback cannot replace its logical operation scope or transaction.", 409)
    if previous is not None:
        if previous[:3] != (actor.user, actor.person_id, company) or not resources <= previous[4] or not _admission_valid():
            raise DomainError("source_prelock_required", "A nested mutation cannot replace outer authority or acquire additional source resources.", 409)
        nodes = nodes | previous[3]
        resources = resources | previous[4]
    memo_token = None
    if previous is None:
        state = operation if operation is not None else _new_original_store()
        memo_token = _locked_original.set(state)
    state = _locked_original.get()
    state["stats"]["prelocked_scopes"] += 1
    token = _prelocked.set((actor.user, actor.person_id, company, nodes, resources))
    try:
        yield
    finally:
        _prelocked.reset(token)
        if memo_token is not None:
            if operation is None:
                _invalidate(state)
            _locked_original.reset(memo_token)


def _new_original_store():
    state = {"valid": True, "authorized": set(), "stats": {
        "prelocked_scopes": 0, "producer_hits": 0,
        "producer_misses": 0, "producer_authorized": 0}}
    _watch_transaction(state)
    return state


def _invalidate(state):
    state["authorized"].clear()
    state["valid"] = False


@contextmanager
def logical_operation(company, command, operation_id):
    """Private lifetime only; grants no lock, admission, source or byte access.

    The Company command owner enters this inside its savepoint try block. Every
    callback still discovers/acquires its complete union before prelocked selects
    the success-only original store. Exit precedes rollback/commit; no store spans
    retries, operations, or savepoint recovery. Current facts remain uncached.
    """
    if _reading.get() is not None:
        raise DomainError("source_prelock_required", "A command cannot execute inside a read graph.", 409)
    identity = (company, command, operation_id)
    previous = _operation.get()
    if previous is not None:
        if previous["identity"] != identity or not previous["valid"]:
            raise DomainError("source_prelock_required", "Nested logical operations require an isolated source authorization lifetime.", 409)
        yield
        return
    if has_prelocked():
        raise DomainError("source_prelock_required", "A logical operation must begin before source lock admission.", 409)
    state = _new_original_store()
    state["identity"] = identity
    token = _operation.set(state)
    try:
        yield
    finally:
        _invalidate(state)
        _operation.reset(token)


def logical_operation_stats():
    """Internal read-only counters, never part of an RPC result or authority."""
    state = _operation.get()
    return dict(state["stats"]) if state is not None else None


def _admission_valid():
    state = _locked_original.get()
    return state is not None and state["valid"]


def _current_db():
    try:
        import frappe
    except ModuleNotFoundError:
        return None
    local = getattr(frappe, "local", None)
    return getattr(local, "db", None) if local is not None else getattr(frappe, "db", None)


def _read_identity(actor, company):
    return (actor.user, actor.person_id, company, "original-producer-read-v1")


def _read_valid(state):
    db = _current_db()
    return state["valid"] and db is state["db"] and (db is None or getattr(db, "transaction_writes", None) == 0)


def _check_read_graph(state, actor, company):
    if state["identity"] != _read_identity(actor, company) or not _read_valid(state):
        _invalidate(state)
        raise DomainError("source_read_context_invalid", "This source read requires a fresh unchanged read snapshot.", 409)


def read_graph_eligible(actor, company):
    """Private eligibility query, not authorization or mutation admission."""
    state = _reading.get()
    if state is not None:
        _check_read_graph(state, actor, company)
        return True
    db = _current_db()
    return (_operation.get() is None and not has_prelocked()
            and (db is None or getattr(db, "transaction_writes", None) == 0))


@contextmanager
def read_graph(actor, company):
    """One explicit top-level Company read, under ordinary snapshot consistency.

    This is not instantaneous mid-response revocation or a general request cache.
    Approved callers are public Company get_record, Company history, Company
    governance.approvals.list_packets/read_packet, and the bounded
    integrations.distribution.list_instructions inventory. They contain
    no writes/savepoint recovery, commands or worker effects. Root
    return and every hit verify the actual DB identity and zero write counter.
    A later call always reauthorizes. Only original producer success is reused;
    immutable parent/binding, ancestry and requested source bytes remain fresh.
    """
    previous = _reading.get()
    if not read_graph_eligible(actor, company):
        if previous is not None:
            _invalidate(previous)
        raise DomainError("source_read_context_invalid", "A source read graph requires an unchanged read-only boundary.", 409)
    if previous is not None:
        yield
        _check_read_graph(previous, actor, company)
        return
    state = _new_original_store()
    state.update(identity=_read_identity(actor, company), db=_current_db())
    token = _reading.set(state)
    try:
        yield
        _check_read_graph(state, actor, company)
    finally:
        _invalidate(state)
        _reading.reset(token)


def has_read_graph(actor, company):
    """Report an existing valid boundary; creates no root or source authority."""
    state = _reading.get()
    if state is None:
        return False
    _check_read_graph(state, actor, company)
    return True


@contextmanager
def original_read_authority(kind, record_id, record_digest, actor, company, *, lock=False, scope_type="Company"):
    """Literal immutable original-source proof, never a record/current-state cache.

    Callers freshly validate scope, canonical digest and immutable linkage BEFORE
    lookup, retain current module abilities, and keep requested byte readers
    outside this proof. Only these two Company record kinds are supported.
    """
    if type(kind) is not str or kind not in {"Company Proposal Issue", "Company Estimate Acceptance"}:
        raise DomainError("source_integrity", "This immutable source proof kind is not supported.", 409)
    state = _reading.get()
    if state is None or lock or scope_type != "Company" or _operation.get() is not None or has_prelocked():
        yield False
        return
    _check_read_graph(state, actor, company)
    if (type(record_id) is not str or not record_id or type(record_digest) is not str
            or len(record_digest) != 64 or any(c not in "0123456789abcdef" for c in record_digest)):
        raise DomainError("source_integrity", "The immutable source proof identity cannot be verified.", 409)
    ancestry = state.setdefault("original_ancestry", [])
    node = (kind, record_id)
    if node in ancestry:
        raise DomainError("cyclic_source", "Original source authority contains a cyclic dependency.", 409)
    key = ("original-record-authority-read-v1", state["identity"], kind, record_id, record_digest)
    reused = key in state["authorized"]
    stat = "original_proof_hits" if reused else "original_proof_misses"
    state["stats"][stat] = state["stats"].get(stat, 0) + 1
    ancestry.append(node)
    try:
        yield reused
        _check_read_graph(state, actor, company)
        if not reused:
            if len(state["authorized"]) < MAX_NODES:
                state["authorized"].add(key)
            state["stats"]["original_proof_authorized"] = state["stats"].get("original_proof_authorized", 0) + 1
    finally:
        ancestry.pop()


def read_graph_stats():
    """Private copy of counters; no public diagnostics or source authority."""
    state = _reading.get()
    return dict(state["stats"]) if state is not None else None


def _watch_transaction(state):
    # Command callers exit before supported savepoint recovery. Approved read
    # roots are read-only; arbitrary write+savepoint rollback is not detected by
    # Frappe's write counter and is not a supported read-root call pattern.
    db = _current_db()
    if db is None:
        return
    def invalidate():
        _invalidate(state)
    db.before_commit.add(invalidate)
    db.before_rollback.add(invalidate)


def _resources(plan):
    resources = {("UOM", unit) for unit in plan.get("unit_ids", [])}
    resources.update(("Currency", currency) for currency in plan.get("currencies", []))
    if plan.get("currency"):
        resources.add(("Currency", plan["currency"]))
    resources.update(("Native", row["doctype"], row["name"]) for row in plan.get("native_refs", []))
    return frozenset(resources)


def is_prelocked(plan, actor, company):
    """Read-only admission subset query; grants no lock or source access."""
    held = _prelocked.get()
    if held is None or held[:3] != (actor.user, actor.person_id, company) or not _admission_valid():
        return False
    nodes = frozenset((row["document_id"], row["input_digest"]) for row in plan.get("generated_sources", []))
    return nodes <= held[3] and _resources(plan) <= held[4]


def node_manifest(plan, actor, company, *, lock=False):
    """Exact immutable generated-node facts after current source authorization.

    Returns no bytes or page text. lock=True requires the caller's existing
    complete prelock admission; this reader never establishes that capability.
    Generated parents have one immutable revision, verified here explicitly.
    """
    from cipher_aec.governance.context import require_company
    from .service import _service, _company_call
    require_company(company, ability="document.read", actor=actor, lock=lock)
    nodes = plan.get("generated_sources", [])
    if type(nodes) is not list or len(nodes)>MAX_NODES:
        raise DomainError("source_limit", "Generated source dependencies exceed the bounded authorization limit.", 409)
    bound = _service(actor, scope_type="Company")
    result = []
    for node in sorted(nodes, key=lambda value:value["document_id"]):
        parent = bound.repo.document(node["document_id"], lock=lock)
        _company_call(lambda: bound._scope(parent, company, lock=lock))
        value = binding(parent)
        if value is None or parent["producer_input_digest"]!=node["input_digest"] or parent["revision_number"]!=1 or not parent["current_revision"]:
            raise DomainError("source_integrity", "Generated source identity cannot be verified.", 409)
        source = _company_call(lambda: bound.source_reference(company, None, parent["current_revision"], 1, lock=lock))
        if source["document_id"]!=parent["name"] or source["revision_number"]!=1 or not source["is_current"] or source["mime_type"]!="application/pdf":
            raise DomainError("source_integrity", "Generated source revision cannot be verified.", 409)
        baseline = value["accepted_estimate"]
        result.append({"document_id":parent["name"],"revision_id":source["revision_id"],"source_sha256":source["source_sha256"],
            "byte_length":source["byte_length"],"page_count":source["page_count"],"input_digest":parent["producer_input_digest"],
            "producer_kind":parent["producer_kind"],"proposal_revision_id":value["proposal_revision_id"],
            "proposal_revision_digest":value["proposal_revision_digest"],"native_fingerprint":value["native_fingerprint"],
            "accepted_baseline_id":baseline["acceptance_id"],"accepted_baseline_digest":baseline["acceptance_digest"],
            "accepted_revision_digest":baseline["revision_digest"],"accepted_manifest_digest":baseline["manifest_digest"],
            "citation_manifest_digest":digest(value["source_citations"]),"renderer_fingerprint":value["renderer"]["fingerprint"]})
    return result


def has_prelocked():
    """Whether any outer acquisition admission exists; no lock or authority grant."""
    return _prelocked.get() is not None
