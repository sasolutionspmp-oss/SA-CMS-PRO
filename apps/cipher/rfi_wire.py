"""Nine exact local RFI routes; native field operations keep their spelling."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from urllib.parse import parse_qsl

from .ap_contract import APRefusal

CONTRACT_VERSION = "cipher.rfi-practice.v1"
PROVENANCE = {"contractVersion": CONTRACT_VERSION, "mode": "practice", "synthetic": True, "currency": "USD"}
MAX_BODY_BYTES = 262_144
MAX_TEXT_CHARACTERS = 12_000
MAX_CITATIONS = 12
MAX_SAFE_INTEGER = 9_007_199_254_740_991
RECIPIENTS = ("engineer@synthetic-rfi.invalid", "owner@synthetic-rfi.invalid", "project-team@synthetic-rfi.invalid")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_COST = re.compile(r"(?:0|[1-9][0-9]{0,11})\.[0-9]{2}")


class WireRefusal(APRefusal):
    """Safe fixed-field transport error without interpolating source content."""


@dataclass(frozen=True)
class ActionRoute:
    template: str
    action: str
    resource_type: str
    duty: str


ACTION_ROUTES = (
    ActionRoute("projects/{id}/rfis", "rfi.create", "project", "staff"),
    ActionRoute("rfis/{id}/draft-response", "rfi.draftResponse", "rfi", "staff"),
    ActionRoute("rfis/{id}/request-response", "rfi.requestResponse", "rfi", "pm"),
    ActionRoute("rfi-response-approvals/{id}/approve", "rfi.approveResponse", "responseApproval", "pm"),
    ActionRoute("rfi-response-approvals/{id}/apply", "rfi.applyResponse", "responseApproval", "pm"),
    ActionRoute("rfis/{id}/distribution-list", "rfi.setDistribution", "rfi", "pm"),
    ActionRoute("rfis/{id}/request-distribution", "rfi.requestDistribution", "rfi", "pm"),
    ActionRoute("rfi-distribution-approvals/{id}/approve", "rfi.approveDistribution", "distributionApproval", "pm"),
    ActionRoute("rfi-distribution-approvals/{id}/distribute", "rfi.distribute", "distributionApproval", "pm"),
)
ACTIONS = frozenset(route.action for route in ACTION_ROUTES)
COLLECTIONS = ("projects", "rfis", "rfi-response-approvals", "rfi-distribution-approvals")
DETAIL_ROUTES = ("projects/{id}/preparation", "rfis/{id}", "rfis/{id}/distribution-preparation",
                 "rfi-response-approvals/{id}/packet", "rfi-distribution-approvals/{id}/packet")
BODY_FIELDS = {
    "rfi.create": frozenset(("subject", "question", "drawingRevisionIds", "documentRevisionIds")),
    "rfi.draftResponse": frozenset(("responseText", "costImpact", "scheduleImpactDays")),
    "rfi.setDistribution": frozenset(("recipients",)),
    **{action: frozenset() for action in ("rfi.requestResponse", "rfi.approveResponse", "rfi.applyResponse",
                                         "rfi.requestDistribution", "rfi.approveDistribution", "rfi.distribute")},
}


def _shape(message="Use the fixed fields for this RFI action.", target="body"):
    raise WireRefusal(422, "invalid_body", message, target)


def parse_json(raw):
    if type(raw) is not bytes or not raw or len(raw) > MAX_BODY_BYTES:
        _shape("Use one nonempty JSON object within the 256 KiB request limit.")
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                _shape("JSON fields may appear only once.")
            value[key] = item
        return value
    def no_float(_):
        _shape("Use an exact decimal string for optional cost impact and integer days.")
    try:
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_float=no_float, parse_constant=no_float)
    except WireRefusal:
        raise
    except (ValueError, UnicodeError, RecursionError):
        _shape("Use one valid bounded UTF-8 JSON object.")
    if type(body) is not dict:
        _shape("Use one JSON object.")
    return body


def _text(value, field, maximum, *, multiline=False):
    if (type(value) is not str or not value.strip() or len(value) > maximum or "\x00" in value
            or not multiline and any(ord(char) < 32 for char in value)):
        _shape("Use nonempty bounded text for this field.", field)
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        _shape("Use valid UTF-8 text for this field.", field)


def _reference(value, field, *, query=False):
    if type(value) is not str or _ID.fullmatch(value) is None:
        if query:
            raise WireRefusal(422, "invalid_query", "Choose a listed project reference.", field)
        _shape("Choose a listed owned RFI source reference.", field)


def _citations(value, field):
    if type(value) is not list or not 1 <= len(value) <= MAX_CITATIONS:
        _shape("Include between one and twelve complete owned citations.", field)
    seen = set()
    for identifier in value:
        _reference(identifier, field)
        if identifier in seen:
            _shape("Include each citation once, preserving the selected order.", field)
        seen.add(identifier)


def decode_action_body(action, raw, *, effect=False):
    if action not in ACTIONS:
        raise WireRefusal(404, "route_not_found", "This RFI route is unavailable.")
    body = parse_json(raw)
    expected = set(BODY_FIELDS[action]) | ({"fingerprint"} if effect else set())
    if set(body) != expected:
        _shape()
    if effect:
        _text(body["fingerprint"], "fingerprint", 256)
        if not body["fingerprint"].isascii():
            _shape("Use the opaque fingerprint from the current review.", "fingerprint")
    if action == "rfi.create":
        _text(body["subject"], "subject", 200)
        _text(body["question"], "question", MAX_TEXT_CHARACTERS, multiline=True)
        for field in ("drawingRevisionIds", "documentRevisionIds"):
            _citations(body[field], field)
    elif action == "rfi.draftResponse":
        _text(body["responseText"], "responseText", MAX_TEXT_CHARACTERS, multiline=True)
        cost, days = body["costImpact"], body["scheduleImpactDays"]
        if cost is not None and (type(cost) is not str or _COST.fullmatch(cost) is None):
            _shape("Use a nonnegative exact two-place decimal string or null for potential cost impact.", "costImpact")
        if days is not None and (type(days) is not int or not 0 <= days <= MAX_SAFE_INTEGER):
            _shape("Use a nonnegative exact whole number of potential days or null.", "scheduleImpactDays")
    elif action == "rfi.setDistribution":
        recipients = body["recipients"]
        if (type(recipients) is not list or not 1 <= len(recipients) <= len(RECIPIENTS)
                or any(type(recipient) is not str or recipient not in RECIPIENTS for recipient in recipients)
                or len(set(recipients)) != len(recipients)):
            _shape("Choose a distinct subset of the listed synthetic .invalid recipients.", "recipients")
    return body


def resolve_action_route(route):
    for definition in ACTION_ROUTES:
        pattern = re.escape(definition.template).replace(re.escape("{id}"), "(" + _ID.pattern + ")")
        match = re.fullmatch(pattern + r"(:preflight)?", route)
        if match:
            return definition, match[1], match[2] is not None
    raise WireRefusal(404, "route_not_found", "This RFI route is unavailable.")


def collection_query(collection, raw_query):
    if collection not in COLLECTIONS:
        raise WireRefusal(404, "route_not_found", "This RFI route is unavailable.")
    allowed = {"search", "top", "cursor"}
    if collection != "projects":
        allowed |= {"projectId", "status"}
    try:
        pairs = parse_qsl(raw_query, keep_blank_values=True, strict_parsing=True, max_num_fields=5)
    except ValueError:
        raise WireRefusal(422, "invalid_query", "Use the fixed RFI filters.", "query") from None
    result = {}
    for key, value in pairs:
        if key not in allowed or key in result or not value or len(value) > 2048:
            raise WireRefusal(422, "invalid_query", "Use each listed RFI filter once.", "query")
        result[key] = value
    if "top" in result and (not result["top"].isascii() or not result["top"].isdigit() or not 1 <= int(result["top"]) <= 50):
        raise WireRefusal(422, "invalid_query", "Choose a page size from one through fifty.", "top")
    if "projectId" in result:
        _reference(result["projectId"], "projectId", query=True)
    if "search" in result:
        try:
            _text(result["search"], "search", 200)
        except WireRefusal:
            raise WireRefusal(422, "invalid_query", "Use a plain search of at most 200 characters.", "search") from None
    statuses = {"open", "answered"} if collection == "rfis" else {"pending", "granted", "consumed", "expired", "invalidated", "stale"}
    if "status" in result and result["status"] not in statuses:
        raise WireRefusal(422, "invalid_query", "Choose a listed RFI status.", "status")
    return result
