"""Fixed exact wire boundary for the isolated human owner-billing workflow."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re
from urllib.parse import parse_qsl

from .ap_contract import APRefusal


CONTRACT_VERSION = "cipher.ar-practice.v1"
PROVENANCE = {"contractVersion": CONTRACT_VERSION, "mode": "practice", "synthetic": True, "currency": "USD"}
MAX_BODY_BYTES = 16_384
MAX_LINES = 100
MAX_CENTS = 9_000_000_000_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_LINE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
_MEASURE = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class WireRefusal(APRefusal):
    """A safe fixed-field error; source IDs are never interpolated."""


@dataclass(frozen=True)
class ActionRoute:
    template: str
    action: str
    resource_type: str
    duty: str


ACTION_ROUTES = (
    ActionRoute("owner-bases/{id}/prepare-bill", "ownerBill.prepare", "basis", "pm"),
    ActionRoute("owner-bills/{id}/request-approval", "ownerBill.requestApproval", "bill", "pm"),
    ActionRoute("owner-bill-approvals/{id}/approve", "ownerBill.approve", "businessApproval", "accounting"),
    ActionRoute("owner-bills/{id}/post", "ownerBill.post", "bill", "accounting"),
    ActionRoute("owner-bills/{id}/request-send", "ownerBill.requestSend", "bill", "send"),
    ActionRoute("owner-send-approvals/{id}/approve", "ownerBill.approveSend", "sendApproval", "send"),
    ActionRoute("owner-send-approvals/{id}/send", "ownerBill.send", "sendApproval", "send"),
)
ACTIONS = frozenset(route.action for route in ACTION_ROUTES)
COLLECTIONS = ("projects", "owner-bases", "owner-bills", "owner-bill-approvals", "owner-send-approvals")
AGING_ROUTES = ("ar-aging", "retainage-aging")
DETAIL_ROUTES = ("owner-bases/{id}/preparation", "owner-bills/{id}",
                 "owner-bill-approvals/{id}/packet", "owner-bills/{id}/send-preparation",
                 "owner-send-approvals/{id}/packet")
PREPARE_FIELDS = frozenset(("claimRevisionId", "reviewRevisionId", "periodId", "lines"))
LINE_FIELDS = frozenset(("lineId", "claimedCumulative", "reviewedCumulative", "differenceReason",
                         "claimSourceLocator", "reviewSourceLocator"))


def _shape(message="Use the fixed fields for this owner-billing action.", target="body"):
    raise WireRefusal(422, "invalid_body", message, target)


def parse_json(raw: bytes) -> dict:
    if type(raw) is not bytes or not raw or len(raw) > MAX_BODY_BYTES:
        _shape("Use one nonempty JSON object of at most 16 KB.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _shape("JSON fields may appear only once.")
            result[key] = value
        return result

    def no_float(_):
        _shape("Use exact decimal strings and integer cents.")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_float=no_float, parse_constant=no_float)
    except WireRefusal:
        raise
    except (ValueError, UnicodeError, RecursionError):
        _shape("Use a valid bounded JSON object.")
    if type(result) is not dict:
        _shape("Use one JSON object.")
    return result


def _text(value, field, *, maximum, empty=False):
    if (type(value) is not str or len(value) > maximum or (not empty and not value.strip())
            or any(ord(char) < 32 for char in value)):
        _shape("Use bounded plain text for this field.", field)


def _reference(value, field, *, line=False):
    if type(value) is not str or ( _LINE_ID if line else _ID).fullmatch(value) is None:
        _shape("Use a listed owner-billing source reference.", field)


def decode_action_body(action: str, raw: bytes, *, effect=False) -> dict:
    if action not in ACTIONS:
        raise WireRefusal(404, "route_not_found", "This owner-billing route is unavailable.")
    body = parse_json(raw)
    fields = set(PREPARE_FIELDS) if action == "ownerBill.prepare" else set()
    if effect:
        fields.add("fingerprint")
    if set(body) != fields:
        _shape()
    if effect:
        _text(body["fingerprint"], "fingerprint", maximum=256)
    if action != "ownerBill.prepare":
        return body
    for field in ("claimRevisionId", "reviewRevisionId", "periodId"):
        _reference(body[field], field)
    if body["claimRevisionId"] == body["reviewRevisionId"]:
        _shape("Claim and review require their separate owned source revisions.", "reviewRevisionId")
    lines = body["lines"]
    if type(lines) is not list or not 1 <= len(lines) <= MAX_LINES:
        _shape("Include between 1 and 100 complete owner SOV lines.", "lines")
    seen = set()
    for line in lines:
        if type(line) is not dict or set(line) != LINE_FIELDS:
            _shape("Use the fixed claimed and reviewed fields for every owner SOV line.", "lines")
        _reference(line["lineId"], "lineId", line=True)
        if line["lineId"] in seen:
            _shape("Include each owner SOV line once.", "lineId")
        seen.add(line["lineId"])
        for field in ("claimedCumulative", "reviewedCumulative"):
            if type(line[field]) is not str or _MEASURE.fullmatch(line[field]) is None:
                _shape("Use a nonnegative exact decimal string with at most six places.", field)
        _text(line["differenceReason"], "differenceReason", maximum=500, empty=True)
        for field in ("claimSourceLocator", "reviewSourceLocator"):
            _text(line[field], field, maximum=240)
    return body


def resolve_action_route(route: str):
    for definition in ACTION_ROUTES:
        pattern = re.escape(definition.template).replace(re.escape("{id}"), "(" + _ID.pattern + ")")
        match = re.fullmatch(pattern + r"(:preflight)?", route)
        if match:
            return definition, match[1], match[2] is not None
    raise WireRefusal(404, "route_not_found", "This owner-billing route is unavailable.")


def dated_query(value):
    if type(value) is not str or _DATE.fullmatch(value) is None:
        raise WireRefusal(422, "invalid_query", "Use an exact calendar date for As of.", "asOf")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise WireRefusal(422, "invalid_query", "Use a valid calendar date for As of.", "asOf") from None
    return value


def collection_query(collection: str, raw_query: str) -> dict:
    if collection not in (*COLLECTIONS, *AGING_ROUTES):
        raise WireRefusal(404, "route_not_found", "This owner-billing route is unavailable.")
    allowed = {"search", "top", "cursor"}
    if collection != "projects":
        allowed.add("projectId")
    if collection in ("owner-bills", "owner-bill-approvals", "owner-send-approvals"):
        allowed.add("status")
    if collection in AGING_ROUTES:
        allowed.add("asOf")
    result = {}
    try:
        fields = parse_qsl(raw_query, keep_blank_values=True, strict_parsing=True, max_num_fields=6)
    except ValueError:
        raise WireRefusal(422, "invalid_query", "Use the fixed owner-billing filters.", "query") from None
    for key, value in fields:
        if key not in allowed or key in result or not value or len(value) > 2048:
            raise WireRefusal(422, "invalid_query", "Use each listed filter once.", "query")
        result[key] = value
    if "top" in result and (not result["top"].isascii() or not result["top"].isdigit() or not 1 <= int(result["top"]) <= 50):
        raise WireRefusal(422, "invalid_query", "Choose a page size from 1 through 50.", "top")
    if "projectId" in result:
        _reference(result["projectId"], "projectId")
    if "asOf" in result:
        dated_query(result["asOf"])
    return result
