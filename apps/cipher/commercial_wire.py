"""Scratch-only fixed commercial wire boundary; no workspace or effect runner.

The future public facade must pair this codec with the shared current/historical
estimate proof and pure service checks. Arithmetic uses Cipher's actual estimate
normalizer; this module does not mistake arithmetic for acceptance provenance.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
import re
from typing import Any
from urllib.parse import parse_qsl

from apps.cipher.domain.estimates import (
    EstimateError, Estimates, _key, _optional_text, _parse_rate, _text_list, _visible,
)
from apps.cipher.core.money import MoneyError, fmt, money, total
from apps.cipher.domain.forecast import normalize_cost_code

CONTRACT_VERSION = "cipher.commercial-practice.v1"
PROVENANCE = {"contractVersion": CONTRACT_VERSION, "mode": "practice",
              "synthetic": True, "currency": "USD"}
MAX_BODY_BYTES = 16_384
MAX_LINES = 50
MAX_CENTS = 999_999_999_999_999  # The engine rejects amounts >= $10**13.
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_QUANTITY = re.compile(r"(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,15})?")
_RATE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?")


class WireRefusal(ValueError):
    """Safe typed draft error; never interpolates a source record identifier."""
    def __init__(self, status: int, code: str, message: str, target: str | None = None):
        self.status, self.code, self.message, self.target = status, code, message, target
        super().__init__(message)


@dataclass(frozen=True)
class ActionRoute:
    template: str
    action: str
    resource_type: str
    duty: str


ACTION_ROUTES = (
    ActionRoute("projects/{id}/create-estimate", "estimate.create", "project", "estimator"),
    ActionRoute("estimates/{id}/revise", "estimate.revise", "estimate", "estimator"),
    ActionRoute("estimates/{id}/request-acceptance", "estimate.request", "estimate", "estimator"),
    ActionRoute("estimate-approvals/{id}/accept", "estimate.accept", "approval", "estimator"),
    ActionRoute("estimate-approvals/{id}/apply", "estimate.apply", "approval", "estimator"),
    ActionRoute("estimates/{id}/prepare-handoff", "estimate.prepareHandoff", "estimate", "estimator"),
    ActionRoute("estimate-handoffs/{id}/create-commitment", "estimate.createCommitment", "handoff", "pm"),
)
ACTIONS = frozenset(route.action for route in ACTION_ROUTES)
COLLECTIONS = ("projects", "drawing-revisions", "estimates", "estimate-approvals", "estimate-handoffs")
DETAIL_ROUTES = (
    "projects/{id}/estimate-preparation", "estimates/{id}", "estimates/{id}/comparison",
    "estimate-approvals/{id}/packet", "estimates/{id}/handoff-preparation",
    "estimate-handoffs/{id}", "commercial-commitments/{id}",
)
_ESTIMATE_FIELDS = frozenset(("documentRevisionId", "lines", "priceBookRef", "inclusions",
                              "exclusions", "contingencyRate", "measurementBasis"))
_LINE_FIELDS = frozenset(("description", "quantity", "unit", "unitPriceCents", "sourceLocator", "costCode"))


def _shape(message: str = "Use the fixed fields for this commercial action.", target: str = "body"):
    raise WireRefusal(422, "invalid_body", message, target)


def _record_missing():
    raise WireRefusal(404, "not_found", "The record is unavailable in this practice session.", "record")


def parse_json(raw: bytes) -> dict:
    """Bounded strict JSON: duplicate keys at every nesting level are refused."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BODY_BYTES:
        _shape("Use a nonempty JSON body of at most 16 KB.")

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
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_float=no_float, parse_constant=no_float)
    except WireRefusal:
        raise
    except (ValueError, UnicodeError, RecursionError):
        _shape("Use a valid JSON object with exact values.")
    if not isinstance(result, dict):
        _shape("Use one JSON object.")
    return result


def _text(value: Any, name: str, *, limit: int = 240, nullable: bool = False, empty: bool = False):
    if nullable and value is None:
        return
    if (not isinstance(value, str) or len(value) > limit or (not empty and not _visible(value))
            or any(ord(char) < 32 for char in value)):
        _shape("Use bounded plain text for this field.", name)


def _reference(value: Any, name: str, *, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _shape("Use a listed record reference.", name)


def _texts(value: Any, name: str):
    if not isinstance(value, list) or len(value) > 32:
        _shape("Use at most 32 text items.", name)
    for item in value:
        _text(item, name)


def decode_action_body(action: str, raw: bytes, *, effect: bool = False) -> dict:
    """Decode one action, retaining exact reviewed wire values for request hashes."""
    if action not in ACTIONS:
        raise WireRefusal(404, "route_not_found", "This commercial route is unavailable.")
    body = parse_json(raw)
    fields = set(_ESTIMATE_FIELDS) if action in ("estimate.create", "estimate.revise") else set()
    if action == "estimate.revise":
        fields.add("removedExclusions")
    if effect:
        fields.add("fingerprint")
    if set(body) != fields:
        _shape()
    if effect:
        _text(body["fingerprint"], "fingerprint", limit=256)
    if action not in ("estimate.create", "estimate.revise"):
        return body
    _reference(body["documentRevisionId"], "documentRevisionId")
    _text(body["priceBookRef"], "priceBookRef", nullable=True)
    _text(body["measurementBasis"], "measurementBasis", limit=400)
    for name in ("inclusions", "exclusions"):
        _texts(body[name], name)
    if action == "estimate.revise":
        _texts(body["removedExclusions"], "removedExclusions")
    value = body["contingencyRate"]
    if not isinstance(value, str) or len(value) > 10 or not _RATE.fullmatch(value):
        _shape("Use a plain decimal ratio with at most six places.", "contingencyRate")
    try:
        _parse_rate(value)
    except EstimateError:
        _shape("The estimate engine permits a ratio from zero through 0.5.", "contingencyRate")
    lines = body["lines"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        _shape("Use between 1 and 50 estimate lines.", "lines")
    seen_previous = set()
    for line in lines:
        line_fields = set(_LINE_FIELDS)
        if action == "estimate.revise":
            line_fields.add("previousLineId")
        if not isinstance(line, dict) or set(line) != line_fields:
            _shape("Use the fixed fields for each estimate line.", "lines")
        for field in ("description", "sourceLocator", "costCode"):
            _text(line[field], field, limit=120 if field == "sourceLocator" else 64 if field == "costCode" else 240)
        if not normalize_cost_code(line["costCode"]):
            _shape("Use a nonempty mapped cost code.", "costCode")
        _text(line["unit"], "unit", limit=4)
        value = line["quantity"]
        if not isinstance(value, str) or not _QUANTITY.fullmatch(value):
            _shape("Use a nonnegative plain decimal quantity string.", "quantity")
        cents = line["unitPriceCents"]
        if type(cents) is not int or not 0 <= cents <= MAX_CENTS:
            _shape("Use nonnegative exact integer cents within the engine range.", "unitPriceCents")
        if action == "estimate.revise":
            previous = line["previousLineId"]
            _reference(previous, "previousLineId", nullable=True)
            if previous is not None:
                if previous in seen_previous:
                    _shape("A previous line may be continued only once.", "previousLineId")
                seen_previous.add(previous)
    return body


def resolve_action_route(route: str):
    for definition in ACTION_ROUTES:
        pattern = re.escape(definition.template).replace(re.escape("{id}"), r"(" + _ID.pattern + r")")
        match = re.fullmatch(pattern + r"(:preflight)?", route)
        if match:
            return definition, match[1], match[2] is not None
    raise WireRefusal(404, "route_not_found", "This commercial route is unavailable.")


def collection_query(collection: str, raw_query: str) -> dict:
    if collection not in COLLECTIONS:
        raise WireRefusal(404, "route_not_found", "This commercial route is unavailable.")
    allowed = {"search", "top", "cursor"}
    if collection != "projects":
        allowed |= {"projectId", "status"}
    result = {}
    try:
        fields = parse_qsl(raw_query, keep_blank_values=True, strict_parsing=True, max_num_fields=5)
    except ValueError:
        raise WireRefusal(422, "invalid_query", "Use the fixed commercial filters.", "query") from None
    for key, value in fields:
        if key not in allowed or key in result or not value or len(value) > 512:
            raise WireRefusal(422, "invalid_query", "Use each listed filter once.", "query")
        result[key] = value
    if "top" in result and (not result["top"].isascii() or not result["top"].isdigit()
                            or not 1 <= int(result["top"]) <= 50):
        raise WireRefusal(422, "invalid_query", "Choose a page size from 1 through 50.", "top")
    if "projectId" in result:
        _reference(result["projectId"], "projectId")
    return result


def normalized_economics(body: dict) -> dict:
    """Pure server arithmetic only; source/duty/current-state checks remain separate.

    Calls the existing engine's exact normalizers instead of reimplementing
    rounding in the browser. Scope/exclusions/contingency normalization matches
    Estimates.create. Revision checks require the planned shared pure helper.
    """
    try:
        normalized = Estimates._normalize_lines([{
            "description": line["description"], "quantity": line["quantity"], "unit": line["unit"],
            "unit_price": fmt(Decimal(line["unitPriceCents"]) / 100),
        } for line in body["lines"]])
        inclusions = _text_list("inclusions", body["inclusions"])
        exclusions = _text_list("exclusions", body["exclusions"])
        if {_key(value) for value in inclusions} & {_key(value) for value in exclusions}:
            _shape("The same scope item cannot be included and excluded.", "inclusions")
        book = _optional_text("price_book_ref", body["priceBookRef"], empty_is_none=False)
        basis = _optional_text("measurement_basis", body["measurementBasis"], empty_is_none=True)
        contingency_rate = _parse_rate(body["contingencyRate"])
        subtotal = total(line["amount"] for line in normalized)
        contingency = money(subtotal * contingency_rate)
        total_amount = money(subtotal + contingency)
    except (EstimateError, MoneyError, ArithmeticError, KeyError, TypeError):
        raise WireRefusal(422, "invalid_estimate", "The exact estimate values could not be validated.", "estimate") from None
    projected = [{"lineNo": line["line_no"], "description": line["description"], "quantity": line["quantity"],
                  "unit": line["unit"], "unitPriceCents": int(money(line["unit_price"]) * 100),
                  "amountCents": int(money(line["amount"]) * 100), "sourceLocator": raw["sourceLocator"],
                  "costCode": normalize_cost_code(raw["costCode"]), "measurementMethod": "manual_entry", "verifiedGeometry": False,
                  **({"previousLineId": raw["previousLineId"]} if "previousLineId" in raw else {})}
                 for line, raw in zip(normalized, body["lines"])]
    return {"lines": projected, "subtotalCents": int(subtotal * 100), "contingencyCents": int(contingency * 100),
            "totalCents": int(total_amount * 100), "contingencyRate": str(contingency_rate),
            "priceBookRef": book, "measurementBasis": basis, "inclusions": inclusions, "exclusions": exclusions}


def scoped_estimate_row(cipher, authority, estimate_id: str):
    """Scope projection precedes estimate.get/proof; never returns a hidden ID."""
    row = cipher.db.one("SELECT id,project_id FROM estimates WHERE id=?", (estimate_id,))
    if row is None or row["project_id"] not in authority.project_ids:
        _record_missing()
    return row


def scoped_revision_row(cipher, authority, revision_id: str, *, project_id: str):
    if project_id not in authority.project_ids:
        _record_missing()
    row = cipher.db.one("""SELECT r.id,r.document_id,d.project_id FROM document_revisions r
                          JOIN documents d ON d.id=r.document_id WHERE r.id=?""", (revision_id,))
    if row is None or row["project_id"] != project_id:
        _record_missing()
    return row


def scoped_previous_lines(cipher, authority, estimate_id: str, lines: list[dict]):
    """Stable revision identity references belong to this exact predecessor."""
    scoped_estimate_row(cipher, authority, estimate_id)
    valid = {row["id"] for row in cipher.db.query("SELECT id FROM estimate_lines WHERE estimate_id=?", (estimate_id,))}
    if any(line.get("previousLineId") is not None and line["previousLineId"] not in valid for line in lines):
        _record_missing()


def scoped_estimate_inventory(cipher, authority, *, project_id: str | None = None):
    """Candidate IDs only, before source proof, counting, facets and presentation.

    The future facade must reconcile scoped audit-birth inventory as well; this
    helper intentionally does not pretend SQL rows prove a complete inventory.
    """
    scope = (project_id,) if project_id is not None else tuple(authority.project_ids)
    if project_id is not None and project_id not in authority.project_ids:
        _record_missing()
    if not scope:
        return []
    marks = ",".join("?" for _ in scope)
    return cipher.db.query(f"SELECT id,project_id FROM estimates WHERE project_id IN ({marks}) ORDER BY created_at,id", scope)
