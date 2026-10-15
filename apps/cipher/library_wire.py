"""Exact fixed transport for authored text and project reference adoption."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from urllib.parse import parse_qsl

from .ap_contract import APRefusal

CONTRACT_VERSION = "cipher.library-practice.v1"
PROVENANCE = {"contractVersion": CONTRACT_VERSION, "mode": "practice", "synthetic": True}
MAX_BODY_BYTES = 524_288
MAX_TEXT_BYTES = 65_536
KINDS = ("specification_template", "contract_clause")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


class WireRefusal(APRefusal):
    """A safe exact-field refusal that does not echo private source values."""


@dataclass(frozen=True)
class ActionRoute:
    template: str
    action: str
    resource_type: str
    duty: str


ACTION_ROUTES = (
    ActionRoute("projects/{id}/create-entry", "library.create", "project", "pm"),
    ActionRoute("library-entries/{id}/revise", "library.revise", "entry", "pm"),
    ActionRoute("library-revisions/{id}/prepare-reference", "library.prepareReference", "revision", "pm"),
    ActionRoute("reference-plans/{id}/request-adoption", "library.requestAdoption", "plan", "pm"),
    ActionRoute("adoption-approvals/{id}/approve", "library.approveAdoption", "adoptionApproval", "pm"),
    ActionRoute("adoption-approvals/{id}/apply", "library.applyAdoption", "adoptionApproval", "pm"),
)
ACTIONS = frozenset(route.action for route in ACTION_ROUTES)
COLLECTIONS = ("projects", "library-entries", "reference-plans", "adoption-approvals", "project-references")
DETAIL_ROUTES = ("projects/{id}/preparation", "library-entries/{id}", "library-revisions/{id}",
                 "reference-plans/{id}", "adoption-approvals/{id}/packet", "project-references/{id}")
BODY_FIELDS = {
    "library.create": frozenset(("kind", "title", "text", "sourceLocator")),
    "library.revise": frozenset(("previousRevisionId", "text", "sourceLocator", "changeReason")),
    "library.prepareReference": frozenset(("targetLocator", "purpose")),
    "library.requestAdoption": frozenset(), "library.approveAdoption": frozenset(), "library.applyAdoption": frozenset(),
}


def _shape(message="Use the fixed fields for this library action.", target="body"):
    raise WireRefusal(422, "invalid_body", message, target)


def parse_json(raw):
    if type(raw) is not bytes or not raw or len(raw) > MAX_BODY_BYTES:
        _shape("Use one nonempty JSON object within the 512 KB request limit.")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _shape("JSON fields may appear only once.")
            result[key] = value
        return result
    def no_float(_):
        _shape("Use the listed authored text fields.")
    try:
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_float=no_float, parse_constant=no_float)
    except WireRefusal:
        raise
    except (ValueError, UnicodeError, RecursionError):
        _shape("Use one valid bounded UTF-8 JSON object.")
    if type(body) is not dict:
        _shape("Use one JSON object.")
    return body


def _plain(value, field, maximum=1000):
    if type(value) is not str or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        _shape("Use bounded plain text for this field.", field)
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        _shape("Use valid UTF-8 text for this field.", field)


def _reference(value, field):
    if type(value) is not str or _ID.fullmatch(value) is None:
        _shape("Use a listed library reference.", field)


def _authored(value):
    if type(value) is not str or not value.strip() or "\x00" in value:
        _shape("Enter authored text without NUL characters.", "text")
    try:
        length = len(value.encode("utf-8", errors="strict"))
    except UnicodeError:
        _shape("Enter valid UTF-8 authored text.", "text")
    if length > MAX_TEXT_BYTES:
        _shape("Keep the actual authored text within 64 KiB of UTF-8.", "text")


def decode_action_body(action, raw, *, effect=False):
    if action not in ACTIONS:
        raise WireRefusal(404, "route_not_found", "This library route is unavailable.")
    body = parse_json(raw)
    expected = set(BODY_FIELDS[action]) | ({"fingerprint"} if effect else set())
    if set(body) != expected:
        _shape()
    if effect:
        _plain(body["fingerprint"], "fingerprint", 256)
        if not body["fingerprint"].isascii():
            _shape("Use the fingerprint from this review.", "fingerprint")
    if action == "library.create":
        if body["kind"] not in KINDS:
            _shape("Choose a specification template or contract clause.", "kind")
        _plain(body["title"], "title", 200)
    if action in ("library.create", "library.revise"):
        _authored(body["text"])
        _plain(body["sourceLocator"], "sourceLocator")
    if action == "library.revise":
        _reference(body["previousRevisionId"], "previousRevisionId")
        _plain(body["changeReason"], "changeReason")
    if action == "library.prepareReference":
        _plain(body["targetLocator"], "targetLocator")
        _plain(body["purpose"], "purpose")
    return body


def resolve_action_route(route):
    for definition in ACTION_ROUTES:
        pattern = re.escape(definition.template).replace(re.escape("{id}"), "(" + _ID.pattern + ")")
        match = re.fullmatch(pattern + r"(:preflight)?", route)
        if match:
            return definition, match[1], match[2] is not None
    raise WireRefusal(404, "route_not_found", "This library route is unavailable.")


def collection_query(collection, raw_query):
    if collection not in COLLECTIONS:
        raise WireRefusal(404, "route_not_found", "This library route is unavailable.")
    allowed = {"search", "top", "cursor"}
    if collection != "projects":
        allowed.add("projectId")
    if collection == "library-entries":
        allowed.add("kind")
    if collection in ("reference-plans", "adoption-approvals"):
        allowed.add("status")
    try:
        pairs = parse_qsl(raw_query, keep_blank_values=True, strict_parsing=True, max_num_fields=6)
    except ValueError:
        raise WireRefusal(422, "invalid_query", "Use the fixed library filters.", "query") from None
    result = {}
    for key, value in pairs:
        if key not in allowed or key in result or not value or len(value) > 2048:
            raise WireRefusal(422, "invalid_query", "Use each listed library filter once.", "query")
        result[key] = value
    if "top" in result and (not result["top"].isascii() or not result["top"].isdigit() or not 1 <= int(result["top"]) <= 50):
        raise WireRefusal(422, "invalid_query", "Choose a page size from 1 through 50.", "top")
    if "projectId" in result:
        _reference(result["projectId"], "projectId")
    if "kind" in result and result["kind"] not in KINDS:
        raise WireRefusal(422, "invalid_query", "Choose a listed authored kind.", "kind")
    if "search" in result:
        _plain(result["search"], "search", 200)
    return result
