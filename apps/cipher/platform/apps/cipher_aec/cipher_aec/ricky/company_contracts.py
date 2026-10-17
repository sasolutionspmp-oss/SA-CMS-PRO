"""Unregistered Company orchestration codecs; integrity is not permission.

No decoder queries Frappe, validates a live session, grants a capability or
executes a tool. Future integration must repeat those checks at execution.
Legacy Project Authority and persisted JSON are never rewritten here.
"""
from dataclasses import asdict, dataclass
import json
import re

from .aec_contracts import CompanyReadContext, SourceReference, identifier, inputs
from .contracts import Authority, RickyError, canonical, digest

AUTHORITY_SCHEMA = "cipher.ricky.authority.company.v1"
REQUEST_SCHEMA = "cipher.ricky.company.read-request.v1"
READ_KIND = "deterministic-read-v1"
READ_ACTIONS = frozenset({"aec.pursuit.lookup", "aec.estimate.recompute", "aec.estimate.compare", "aec.quantity.convert"})
LEGACY_FIELDS = frozenset(Authority.__dataclass_fields__)


def _fail(message):
    raise RickyError("invalid_company_binding", message)


def _text(value):
    if (type(value) is not str or not 1 <= len(value) <= 140 or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        _fail("Use an exact visible Company, User or native Person identifier.")
    return value


def _sha(value):
    if type(value) is not str or re.fullmatch("[a-f0-9]{64}", value) is None:
        _fail("Use the original exact SHA256 binding; never a bearer session token.")
    return value


@dataclass(frozen=True)
class CompanyAuthority:
    """Stored original identity/integrity binding, never a cached grant.

    Person names are native Frappe identifiers (including hash names), not
    forced UUIDs. run_id is the existing orchestration UUID. The original
    hashed session reference is mandatory and cannot be minted by decoding.
    """
    user: str
    person: str
    company: str
    run_id: str
    session_reference: str
    authority_version: str
    selection_digest: str

    def __post_init__(self):
        for value in (self.user, self.person, self.company):
            _text(value)
        identifier(self.run_id)
        for value in (self.session_reference, self.authority_version, self.selection_digest):
            _sha(value)

    def binding(self):
        return {"schema": AUTHORITY_SCHEMA, "scope_type": "Company", "project": None, **asdict(self)}


@dataclass(frozen=True)
class DeterministicReadRequest:
    """Explicit user-selected action; this is not model inference or a grant."""
    pursuit_id: str
    action: str
    arguments_json: str
    sources: tuple[SourceReference, ...] = ()
    measurement_ids: tuple[str, ...] = ()

    def __post_init__(self):
        identifier(self.pursuit_id)
        if type(self.action) is not str or self.action not in READ_ACTIONS:
            _fail("Select one fixed read action; draft/effect/model actions are not supported.")
        if type(self.arguments_json) is not str or len(self.arguments_json) > 4096:
            _fail("Use bounded canonical tool arguments.")
        try:
            arguments = json.loads(self.arguments_json)
            if canonical(arguments) != self.arguments_json:
                _fail("Tool arguments must retain their canonical exact JSON values.")
        except (ValueError, TypeError, RecursionError):
            _fail("Use canonical JSON tool arguments.")
        inputs(self.action, arguments)
        for name in ("revision_id", "left_revision_id", "right_revision_id", "source_id", "target_unit_id"):
            if name in arguments:
                identifier(arguments[name])
        # Reuse the frozen read-selection shape only for structural validation;
        # it confers no authority and contains no mutable nested argument dict.
        if (type(self.sources) is not tuple or len(self.sources) > 8
                or any(type(value) is not SourceReference for value in self.sources)
                or len({value.citation_id for value in self.sources}) != len(self.sources)
                or type(self.measurement_ids) is not tuple or len(self.measurement_ids) > 8):
            _fail("Use bounded immutable selected sources and measurements.")
        for value in self.measurement_ids:
            identifier(value)
        if len(set(self.measurement_ids)) != len(self.measurement_ids):
            _fail("Do not duplicate selected measurements.")
        if arguments.get("source_kind") == "measurement" and arguments["source_id"] not in self.measurement_ids:
            _fail("The requested measurement must be explicitly selected.")

    @classmethod
    def from_value(cls, value):
        fields = {"schema", "pursuit_id", "action", "arguments", "sources", "measurement_ids"}
        if type(value) is not dict or set(value) != fields or value["schema"] != REQUEST_SCHEMA:
            _fail("Use the exact versioned Company read request.")
        if type(value["sources"]) is not list or type(value["measurement_ids"]) is not list:
            _fail("Use explicit source and measurement selection arrays.")
        references = []
        for reference in value["sources"]:
            if type(reference) is not dict or set(reference) != set(SourceReference.__dataclass_fields__):
                _fail("Use the exact selected citation reference fields.")
            references.append(SourceReference(**reference))
        try:
            arguments_json = canonical(value["arguments"])
        except (ValueError, TypeError, RecursionError):
            _fail("Use canonical JSON tool arguments.")
        return cls(value["pursuit_id"], value["action"], arguments_json,
            tuple(references), tuple(value["measurement_ids"]))

    def binding(self):
        return {"schema": REQUEST_SCHEMA, "pursuit_id": self.pursuit_id, "action": self.action,
            "arguments": json.loads(self.arguments_json), "sources": [asdict(value) for value in self.sources],
            "measurement_ids": list(self.measurement_ids)}

    def selection_digest(self):
        return digest(self.binding())

    def read_context(self, authority):
        if type(authority) is not CompanyAuthority or authority.selection_digest != self.selection_digest():
            _fail("The original run authority binds a different read selection.")
        return CompanyReadContext(authority.user, authority.person, authority.company, self.pursuit_id,
            self.sources, self.measurement_ids)

    @staticmethod
    def model_standing():
        return {"mode": READ_KIND, "model_invoked": False, "live_model_qualified": False}


def decode_authority(value):
    """Decode only literal Company-v1 or the original Project binding shape."""
    if type(value) is not dict:
        _fail("A stored authority binding must be an object.")
    if "schema" in value:
        required = {"schema", "scope_type", "project", *CompanyAuthority.__dataclass_fields__}
        if (set(value) != required or value["schema"] != AUTHORITY_SCHEMA
                or value["scope_type"] != "Company" or value["project"] is not None):
            _fail("Company authority requires explicit Company scope and a null Project.")
        return CompanyAuthority(**{key: value[key] for key in CompanyAuthority.__dataclass_fields__})
    if set(value) != LEGACY_FIELDS or type(value["project"]) is not str or not value["project"]:
        _fail("A legacy Project binding requires its original real Project and exact fields.")
    # Preserve the existing Authority constructor, optional session reference,
    # opaque Project revisions and binding bytes without inserting new fields.
    return Authority(**value)


def decode_run_authority(run):
    """Check persisted headers/original selection; still no permission check."""
    if type(run) is not dict or type(run.get("authority")) is not dict:
        _fail("A stored run requires its original authority binding.")
    authority = decode_authority(run["authority"])
    expected = {"company": authority.company, "user": authority.user, "person": authority.person}
    if type(authority) is CompanyAuthority:
        if run.get("request_kind") == "deterministic-proposal-v1":
            from .company_proposal_contracts import DeterministicProposalRequest
            request = DeterministicProposalRequest.from_value(run.get("request"))
            kind = "deterministic-proposal-v1"
        else:
            request = DeterministicReadRequest.from_value(run.get("request"))
            kind = READ_KIND
        expected.update(id=authority.run_id, scope_type="Company", project=None,
            request_kind=kind, original_session_reference=authority.session_reference)
        if request.selection_digest() != authority.selection_digest:
            _fail("The stored original read selection no longer matches its authority binding.")
    else:
        if run.get("scope_type", "Project") != "Project":
            _fail("A Project binding cannot be reinterpreted as Company scope.")
        expected["project"] = authority.project
    if any(key not in run or type(run[key]) is not type(value) or run[key] != value for key, value in expected.items()):
        _fail("The run scope, original requester, session or identity differs from its stored authority.")
    return authority
