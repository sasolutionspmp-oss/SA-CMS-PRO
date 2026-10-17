"""Closed Company suggestion contracts; no authority, writer or model adapter."""
from dataclasses import dataclass
from copy import deepcopy
import json
import re

from .aec_contracts import SourceReference, identifier, inputs, SCHEMAS
from .company_contracts import DeterministicReadRequest, REQUEST_SCHEMA as READ_SCHEMA
from .contracts import RickyError, canonical, digest
from .tools import validate

PROPOSAL_KIND = "deterministic-proposal-v1"
REQUEST_SCHEMA = "cipher.ricky.company.proposal-request.v1"
MANIFEST_SCHEMA = "cipher.ricky.company.original-proposal.v1"
PROPOSAL_SCHEMA = "cipher.ricky.company.proposal.v1"
START_COMMAND = "ricky.company.proposal.start.v1"
CANCEL_COMMAND = "ricky.company.proposal.cancel.v1"
METHODS = {"aec.scope.draft": ("scope_draft", "commercial.read", "scope-draft.v1"),
    "aec.estimate.draft": ("estimate_draft", "estimate.read", "estimate-draft.v1")}
RECORD_KINDS = {("commercial", "proposal-revision"),
    *(("estimate", kind) for kind in ("revision", "snapshot", "line", "conversion", "rate", "assembly", "acceptance")),
    *(("takeoff", kind) for kind in ("measurement", "calibration", "verification", "binding"))}


def fail(message):
    raise RickyError("source_integrity", message)


def closed(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        fail("The Company proposal has missing or unsupported fields.")


def sha(value):
    if type(value) is not str or re.fullmatch("[a-f0-9]{64}", value) is None:
        fail("The Company proposal digest is invalid.")


@dataclass(frozen=True)
class DeterministicProposalRequest(DeterministicReadRequest):
    def __post_init__(self):
        # The old codec still validates only reads; no historical codec widening.
        DeterministicReadRequest(self.pursuit_id, "aec.pursuit.lookup", "{}", self.sources, self.measurement_ids)
        if type(self.action) is not str or self.action not in METHODS:
            raise RickyError("validation_error", "Select one reviewed deterministic draft action.")
        if type(self.arguments_json) is not str or len(self.arguments_json) > 4096:
            raise RickyError("validation_error", "Use bounded canonical draft arguments.")
        try:
            arguments = json.loads(self.arguments_json)
            if canonical(arguments) != self.arguments_json:
                raise ValueError
        except (ValueError, TypeError, RecursionError):
            raise RickyError("validation_error", "Use canonical JSON draft arguments.") from None
        inputs(self.action, arguments)
        citations = {value.citation_id for value in self.sources}
        if self.action == "aec.scope.draft":
            identifier(arguments["proposal_revision_id"])
            used = [value for section in arguments["sections"] for value in section["citation_ids"]]
            if not arguments["sections"] or any(not section["citation_ids"] for section in arguments["sections"]):
                raise RickyError("missing_evidence", "Each scope section needs selected source evidence.")
        else:
            identifier(arguments["base_revision_id"])
            used = arguments["citation_ids"]
            if not arguments["selections"] or len({row["line_record_id"] for row in arguments["selections"]}) != len(arguments["selections"]):
                raise RickyError("validation_error", "Select distinct existing lines.")
            for row in arguments["selections"]:
                for field in ("line_record_id", "source_id", "target_unit_id"):
                    identifier(row[field])
                if row["source_kind"] == "measurement" and row["source_id"] not in self.measurement_ids:
                    raise RickyError("not_found", "The quantity measurement must be explicitly selected.")
        if not used or any(value not in citations for value in used):
            raise RickyError("invalid_citation", "The draft must cite its selected exact sources.")

    @classmethod
    def from_value(cls, value):
        closed(value, {"schema", "pursuit_id", "action", "arguments", "sources", "measurement_ids"})
        if value["schema"] != REQUEST_SCHEMA:
            raise RickyError("validation_error", "Use the versioned Company proposal request.")
        original = DeterministicReadRequest.from_value({**value, "schema": READ_SCHEMA,
            "action": "aec.pursuit.lookup", "arguments": {}})
        return cls(original.pursuit_id, value["action"], canonical(value["arguments"]), original.sources, original.measurement_ids)

    def binding(self):
        return {**super().binding(), "schema": REQUEST_SCHEMA}

    @staticmethod
    def model_standing():
        return {"mode": PROPOSAL_KIND, "model_invoked": False, "live_model_qualified": False}


def validate_resource_plan(value):
    from .company_backend import validate_resource_plan as read_plan
    closed(value, {"unit_ids", "currencies", "native_refs", "generated_sources"})
    # Preserve all the read plan's bounds/name/order checks while admitting only
    # the two additional native sources used by canonical commercial revisions.
    if type(value["native_refs"]) is not list or len(value["native_refs"]) > 1000:
        fail("The complete native proposal source inventory is invalid.")
    for row in value["native_refs"]:
        closed(row, {"doctype", "name"})
        if row["doctype"] in {"Quotation", "Price List"}:
            read_plan({**value, "native_refs": [{**row, "doctype": "Item"}]})
    read_plan({**value, "native_refs": [row for row in value["native_refs"] if row["doctype"] not in {"Quotation", "Price List"}]})
    keys = [(row["doctype"], row["name"]) for row in value["native_refs"]]
    if keys != sorted(set(keys)):
        fail("The proposal resource union must be sorted and unique.")
    return value


def validate_manifest(value, request):
    from .company_backend import validate_manifest as read_manifest
    fields = {"schema", "selection_digest", "action_complete", "pursuit", "citations", "records", "owners",
        "preparation_heads", "qualified_units", "quantity_standing"}
    closed(value, fields)
    if value["schema"] != MANIFEST_SCHEMA or value["selection_digest"] != request.selection_digest():
        fail("The original proposal manifest has a different selection.")
    bounds = {"records": 128, "owners": 8, "preparation_heads": 8, "qualified_units": 500, "quantity_standing": 8}
    for field, limit in bounds.items():
        if type(value[field]) is not list or len(value[field]) > limit:
            fail("The bounded proposal source manifest is invalid.")
    for row in value["records"]:
        closed(row, {"domain", "kind", "id", "digest"}); identifier(row["id"]); sha(row["digest"])
        if (row["domain"], row["kind"]) not in RECORD_KINDS:
            fail("This immutable proposal dependency kind is unsupported.")
    keys = [(row["domain"], row["kind"], row["id"]) for row in value["records"]]
    if keys != sorted(set(keys)):
        fail("Original proposal records must be sorted and unique.")
    for row in value["owners"]:
        closed(row, {"domain", "kind", "id", "pursuit_id", "digest"})
        identifier(row["id"]); sha(row["digest"])
        if (row["domain"], row["kind"]) not in {("commercial", "proposal"), ("estimate", "estimate")} or row["pursuit_id"] != request.pursuit_id:
            fail("The proposal parent belongs to another Company Pursuit.")
    for row in value["preparation_heads"]:
        closed(row, {"domain", "owner_id", "revision_id", "digest"})
        identifier(row["owner_id"]); identifier(row["revision_id"]); sha(row["digest"])
        kind = "proposal-revision" if row["domain"] == "commercial" else "revision"
        if row["domain"] not in {"commercial", "estimate"} or not any(item["domain"] == row["domain"] and item["id"] == row["owner_id"] for item in value["owners"]):
            fail("The exact prepared revision owner is missing.")
        if not any(item == {"domain": row["domain"], "kind": kind, "id": row["revision_id"], "digest": row["digest"]} for item in value["records"]):
            fail("The prepared head does not bind an exact immutable revision.")
    for row in value["qualified_units"]:
        closed(row, {"id", "digest"}); identifier(row["id"]); sha(row["digest"])
    for row in value["quantity_standing"]:
        closed(row, {"measurement_id", "eligible", "verification_id", "digest"})
        identifier(row["measurement_id"]); sha(row["digest"])
        if row["measurement_id"] not in request.measurement_ids or type(row["eligible"]) is not bool:
            fail("The quantity standing must belong to a selected measurement.")
        if row["verification_id"] is not None:
            identifier(row["verification_id"])
    for field, key in (("owners", lambda row: (row["domain"], row["id"])), ("preparation_heads", lambda row: (row["domain"], row["owner_id"])),
            ("qualified_units", lambda row: row["id"]), ("quantity_standing", lambda row: row["measurement_id"])):
        ordered = [key(row) for row in value[field]]
        if ordered != sorted(set(ordered)):
            fail("The proposal observations must be sorted and unique.")
    proxy = DeterministicReadRequest(request.pursuit_id, "aec.pursuit.lookup", "{}", request.sources, request.measurement_ids)
    allowed = {("estimate", kind) for kind in ("revision", "snapshot", "line")} | {("takeoff", kind) for kind in ("measurement", "calibration", "verification")}
    read_manifest({"schema": "cipher.ricky.company.original-read.v1", "selection_digest": proxy.selection_digest(),
        **{key: value[key] for key in ("action_complete", "pursuit", "citations")},
        "records": [row for row in value["records"] if (row["domain"], row["kind"]) in allowed],
        "owners": [{"id": row["id"], "pursuit_id": row["pursuit_id"]} for row in value["owners"] if row["domain"] == "estimate" and row["kind"] == "estimate" ]}, proxy)
    return value


def validate_preparation(run, output, *, originals=None, require_citations=False):
    request = DeterministicProposalRequest.from_value(run["request"])
    validate(SCHEMAS[request.action][1], output)
    manifest = validate_manifest(run["original_manifest"], request)
    if (output["scope_type"] != "Company" or output["company"] != run["company"] or output["pursuit_id"] != request.pursuit_id
            or output["kind"] != METHODS[request.action][2] or output["draft_digest"] != digest({key: value for key, value in output.items() if key != "draft_digest"})):
        fail("The draft output differs from its exact original preparation.")
    records = {(row["domain"], row["kind"], row["id"]): row["digest"] for row in manifest["records"]}
    owners = {(row["domain"], row["kind"], row["id"]): row["digest"] for row in manifest["owners"]}
    dependencies = {("pursuit", request.pursuit_id): manifest["pursuit"]["digest"]}
    kinds = {("commercial", "proposal"): "proposal", ("commercial", "proposal-revision"): "proposal-revision",
        ("estimate", "estimate"): "estimate", ("estimate", "revision"): "estimate-revision", ("estimate", "snapshot"): "calculation-snapshot"}
    for (domain, kind, name), checksum in {**records, **owners}.items():
        if (domain, kind) in kinds:
            dependencies[kinds[domain, kind], name] = checksum
    arguments = json.loads(request.arguments_json)
    domain = "commercial" if request.action == "aec.scope.draft" else "estimate"
    revision_id = arguments["proposal_revision_id"] if domain == "commercial" else arguments["base_revision_id"]
    heads = [row for row in manifest["preparation_heads"] if row["domain"] == domain and row["revision_id"] == revision_id]
    if len(heads) != 1:
        fail("The draft requires its exact selected base head observation.")
    owner_id = heads[0]["owner_id"]
    if domain == "commercial":
        expected_keys = [("pursuit", request.pursuit_id), ("proposal", owner_id), ("proposal-revision", revision_id)]
    else:
        if originals is None or ("estimate", "revision", revision_id) not in originals:
            fail("Original canonical estimate records are required to verify preparation.")
        revision = originals["estimate", "revision", revision_id]
        if revision["estimate"] != owner_id:
            fail("The original base revision has a different owner.")
        expected_keys = [("estimate-revision", revision_id), ("calculation-snapshot", revision["calculation_snapshot"]),
            ("estimate", owner_id), ("pursuit", request.pursuit_id)]
    expected_dependencies = [{"kind": kind, "id": name, "digest": dependencies.get((kind, name))} for kind, name in expected_keys]
    if any(row["digest"] is None for row in expected_dependencies) or canonical(output["record_dependencies"]) != canonical(expected_dependencies):
        fail("The exact ordered draft dependencies were omitted, duplicated or changed.")
    selected = {row["id"]: row["digest"] for row in manifest["citations"]}
    used = [key for row in arguments["sections"] for key in row["citation_ids"]] if domain == "commercial" else arguments["citation_ids"]
    used = list(dict.fromkeys(used))
    references = output["verified_source_references"]
    if [row["citation_id"] for row in references] != used:
        fail("The exact ordered draft citation references were omitted, duplicated or changed.")
    source_refs = {ref.citation_id: ref for ref in request.sources}
    for row in references:
        ref = source_refs[row["citation_id"]]
        if (any(row[key] != getattr(ref, key) for key in ("revision_id", "page", "excerpt_sha256", "source_sha256"))
                or selected.get(ref.citation_id) != row["canonical_digest"]):
            fail("The draft cites a different original source.")
        if require_citations and (originals is None or ("documents", "citation", ref.citation_id) not in originals):
            fail("Every prepared source requires its actual authorized canonical citation.")
        if originals is not None and ("documents", "citation", ref.citation_id) in originals:
            citation = originals["documents", "citation", ref.citation_id]
            if digest(citation) != row["canonical_digest"] or citation["document_id"] != row["document_id"]:
                fail("The original document citation identity changed.")
    if output["unverified_claims"] != arguments["unverified_claims"]:
        fail("Original unverified suggestions cannot be rewritten.")
    if request.action == "aec.scope.draft":
        if output["proposed_fields"] != {"sections": arguments["sections"]}:
            fail("The scope fields differ from the selected suggestion.")
    else:
        fields = output["proposed_fields"]
        if fields["notes"] != arguments["notes"] or len(fields["quantity_selections"]) != len(arguments["selections"]):
            fail("The estimate suggestion differs from its original selections.")
        for actual, original in zip(fields["quantity_selections"], arguments["selections"]):
            quantity = actual["quantity"]
            domain, kind = ("estimate", "line") if original["source_kind"] == "estimate-line" else ("takeoff", "measurement")
            if (actual["line_record_id"] != original["line_record_id"] or any(quantity[key] != original[key] for key in ("source_kind", "source_id", "target_unit_id"))
                    or quantity["source_digest"] != records.get((domain, kind, original["source_id"])) or quantity["eligible_for_new_use"] is not True):
                fail("The prepared quantity has a different canonical source.")
            _quantity_original(run, original, quantity, records, originals)
    return output


def _quantity_original(run, selection, actual, retained, originals):
    """Pure historical rational reconciliation; never asks for current use."""
    from cipher_aec.estimating.calculation import bounded, calculate
    from cipher_aec.estimating.contracts import quantity, exact
    from cipher_aec.migrations.validation import parse_manifest, conversion_fraction
    def original(domain, kind, name):
        value = (originals or {}).get((domain, kind, name))
        if (value is None or digest(value) != retained.get((domain, kind, name)) or value.get("scope_type") != "Company"
                or value.get("company") != run["company"] or value.get("project") is not None):
            fail("An exact authorized immutable quantity dependency is missing.")
        return value
    base = original("estimate", "revision", run["request"]["arguments"]["base_revision_id"])
    target_line = original("estimate", "line", selection["line_record_id"])
    if (target_line["id"] not in base["line_record_ids"] or target_line["estimate_revision"] != base["id"]
            or selection["target_unit_id"] != target_line["authored"]["quantity"]["unit_id"]):
        fail("The original proposed line or target unit changed.")
    if selection["source_kind"] == "estimate-line":
        source = original("estimate", "line", selection["source_id"])
        revision = original("estimate", "revision", source["estimate_revision"])
        snapshot = original("estimate", "snapshot", revision["calculation_snapshot"])
        authored = next((row for row in snapshot["inputs"]["lines"] if row["line_id"] == source["line_id"]), None)
        if (source["id"] not in revision["line_record_ids"] or source["authored"] != authored
                or snapshot["subject_id"] != revision["id"] or calculate(deepcopy(snapshot["inputs"])) != snapshot["result"]):
            fail("The original authored quantity and calculation cannot be reconciled.")
        amount, manifest = authored["quantity"], snapshot["inputs"]["unit_manifest"]
        provenance, basis, verified = "authored-estimate-line", "authored-line-v1", False
    else:
        source = original("takeoff", "measurement", selection["source_id"])
        amount, manifest = source["result"]["quantity"], source["unit_manifest"]
        method = source["definition"]["method"]
        if method not in {"manual", "calibrated"}:
            fail("The original measurement method is invalid.")
        provenance = method + "-measurement"
        basis = "after-takeoff-waste-v1" if exact(source["definition"]["waste_fraction"], "measurement.waste_fraction") > 0 else "net-quantity-v1"
        verified = False
        if method == "calibrated":
            calibration = original("takeoff", "calibration", source["calibration_id"])
            verification = original("takeoff", "verification", source["verification_id"])
            verified = verification["calibration_id"] == calibration["id"]
            if not verified or verification["calibration_digest"] != digest(calibration):
                fail("The original independent verification cannot be reconciled.")
    manifest = parse_manifest(manifest)
    units = {row["id"]: row for row in manifest["records"] if row["kind"] == "uom"}
    if manifest["scope"] != {"scope_type": "Company", "company": run["company"], "project": None} or selection["target_unit_id"] not in units:
        fail("The original quantity unit manifest has another scope or dimension.")
    converted = bounded(quantity(amount, units, "quantity") * conversion_fraction(manifest, amount["unit_id"], selection["target_unit_id"]))
    expected = {"source_unit_id": amount["unit_id"], "numerator": str(converted.numerator), "denominator": str(converted.denominator),
        "provenance": provenance, "quantity_basis": basis, "independently_verified": verified, "model_supplied_quantity": False}
    if any(type(actual[key]) is not type(value) or actual[key] != value for key, value in expected.items()):
        fail("The proposed quantity differs from its original exact rational source.")
    if basis == "after-takeoff-waste-v1" and any(int(row["waste_fraction"]["numerator"]) for row in target_line["calculated"]["components"]):
        fail("The original quantity basis would apply waste twice.")
