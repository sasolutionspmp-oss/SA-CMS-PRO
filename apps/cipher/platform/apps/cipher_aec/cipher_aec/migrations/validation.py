"""Strict pure validation and exact rational units for canonical manifests."""
from __future__ import annotations

from collections import deque
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math
import re
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import (DIMENSIONS, MAX_CONVERSIONS, MAX_JSON_BYTES, MAX_QUANTITIES, MAX_RECORDS,
                        NATIVE_DOCTYPES, PROJECT_STATUSES, SCHEMA, COMPANY_SCHEMA, SPECS)


class ManifestError(ValueError):
    def __init__(self, path, message):
        super().__init__(f"{path}: {message}")
        self.path, self.message = path, message


def fail(path, message):
    raise ManifestError(path, message)


def strict_object(value, required, optional, path):
    if not isinstance(value, dict) or set(value) - (set(required) | set(optional)) or set(required) - set(value):
        fail(path, "Use exactly the required and supported fields.")


def text(value, path, maximum=200):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        fail(path, f"Use 1 to {maximum} visible characters without surrounding spaces.")
    return value


def uuid(value, path):
    if not isinstance(value, str):
        fail(path, "Use a canonical UUID identity.")
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        fail(path, "Use a canonical UUID identity.")
    if str(parsed) != value or parsed.version not in (4, 5):
        fail(path, "Use a canonical UUID v4 or v5 identity.")
    return value


def positive_integer(value, path, maximum=10**24):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value) or len(value) > 25 or int(value) > maximum:
        fail(path, "Use a positive canonical integer string within the supported range.")
    return int(value)


def decimal_quantity(value, path):
    if not isinstance(value, str) or len(value) > 50 or not re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", value):
        fail(path, "Use an exact decimal string, never a JSON number or exponent.")
    amount = Decimal(value)
    if amount.is_zero() and value.startswith("-"):
        fail(path, "Negative zero is not canonical.")
    if len(amount.as_tuple().digits) > 30 or max(0, -amount.as_tuple().exponent) > 12:
        fail(path, "Quantity exceeds 30 digits or 12 fractional places.")
    return amount


def _typed(value, kind, path):
    if kind.startswith("ref:"):
        uuid(value, path)
    elif kind in {"text", "code"}:
        text(value, path, 80 if kind == "code" else 200)
    elif kind == "bool":
        if type(value) is not bool:
            fail(path, "Use a JSON boolean.")
    elif kind == "precision":
        if type(value) is not int or not 0 <= value <= 12:
            fail(path, "Use an integer precision from 0 through 12.")
    elif kind == "dimension":
        if not isinstance(value, str) or value not in DIMENSIONS:
            fail(path, "Use an explicit supported unit dimension.")
    elif kind == "currency":
        if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
            fail(path, "Use an uppercase three-letter currency code.")
    elif kind == "timezone":
        if value is None:
            return  # Explicit unconfigured policy; never silently infer a zone.
        try:
            ZoneInfo(text(value, path, 80))
        except (ZoneInfoNotFoundError, ValueError):
            fail(path, "Use a valid IANA time zone.")
    elif kind == "status":
        if not isinstance(value, str) or value not in PROJECT_STATUSES:
            fail(path, "Use an ERPNext Project lifecycle status.")
    elif kind == "dimension_kind":
        if not isinstance(value, str) or value not in {"project", "cost_center", "cost_code", "cost_type"}:
            fail(path, "Use an explicit canonical dimension value kind.")


def parse_manifest(value):
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_JSON_BYTES:
            fail("manifest", "Manifest exceeds 2 MiB.")
        def reject_duplicate(pairs):
            obj = {}
            for key, item in pairs:
                if key in obj:
                    fail("manifest", "Duplicate JSON object keys are not accepted.")
                obj[key] = item
            return obj
        try:
            value = json.loads(value, object_pairs_hook=reject_duplicate)
        except (ValueError, RecursionError) as error:
            if isinstance(error, ManifestError):
                raise
            fail("manifest", "Use a valid bounded JSON object.")
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
    except (ValueError, TypeError, RecursionError):
        fail("manifest", "Use finite JSON data without cycles.")
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        fail("manifest", "Manifest exceeds 2 MiB.")
    strict_object(value, {"schema", "dataset_id", "scope", "records", "unit_conversions"}, {"quantities", "label"}, "manifest")
    if value["schema"] not in (SCHEMA, COMPANY_SCHEMA):
        fail("schema", "Unsupported canonical schema version.")
    uuid(value["dataset_id"], "dataset_id")
    if value["schema"] == SCHEMA:
        strict_object(value["scope"], {"company", "project"}, set(), "scope")
        for key in ("company", "project"):
            text(value["scope"][key], "scope." + key, 140)
    else:
        strict_object(value["scope"], {"scope_type", "company", "project"}, set(), "scope")
        if value["scope"]["scope_type"] != "Company" or value["scope"]["project"] is not None:
            fail("scope", "Canonical v2 currently requires exact Company scope and a null Project.")
        text(value["scope"]["company"], "scope.company", 140)
    if "label" in value:
        text(value["label"], "label")
    records = value["records"]
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
        fail("records", "Use 1 through 500 canonical records.")
    by_id, identities, source_identities, business_codes = {}, set(), set(), set()
    for index, row in enumerate(records):
        path = f"records[{index}]"
        strict_object(row, {"id", "kind", "revision", "fields"}, {"target", "source"}, path)
        uuid(row["id"], path + ".id")
        if row["id"] in by_id:
            fail(path + ".id", "Duplicate immutable record identity.")
        if not isinstance(row["kind"], str) or row["kind"] not in SPECS:
            fail(path + ".kind", "Unsupported canonical entity kind.")
        if type(row["revision"]) is not int or not 1 <= row["revision"] <= 2**31 - 1:
            fail(path + ".revision", "Use a positive monotonic integer revision.")
        if value["schema"] == COMPANY_SCHEMA and row["kind"] == "project":
            fail(path + ".kind", "A Company manifest cannot bind a Project record.")
        spec = SPECS[row["kind"]]
        strict_object(row["fields"], spec["required"], spec["optional"], path + ".fields")
        for key, field in row["fields"].items():
            _typed(field, {**spec["required"], **spec["optional"]}[key], path + ".fields." + key)
        if row["kind"] in {"item", "cost_center", "cost_code", "cost_type", "accounting_dimension"}:
            code = (row["kind"], row["fields"]["code"])
            if code in business_codes:
                fail(path + ".fields.code", "Business codes must be unique for their kind within the company manifest.")
            business_codes.add(code)
        if "target" in row:
            strict_object(row["target"], {"doctype", "name"}, {"version"}, path + ".target")
            if row["target"]["doctype"] != NATIVE_DOCTYPES.get(row["kind"]):
                fail(path + ".target.doctype", "This kind has no supported native target adapter.")
            text(row["target"]["name"], path + ".target.name", 140)
            if "version" in row["target"]:
                text(row["target"]["version"], path + ".target.version", 80)
            key = (row["target"]["doctype"], row["target"]["name"])
            if key in identities:
                fail(path + ".target", "Two source identities cannot bind one target record.")
            identities.add(key)
        if "source" in row:
            strict_object(row["source"], {"system", "record_id"}, {"revision"}, path + ".source")
            for key, item in row["source"].items():
                text(item, path + ".source." + key, 140)
            source_identity = (row["kind"], row["source"]["system"], row["source"]["record_id"])
            if source_identity in source_identities:
                fail(path + ".source", "One source entity cannot bind two immutable canonical identities.")
            source_identities.add(source_identity)
        by_id[row["id"]] = row
    company_rows = [r for r in records if r["kind"] == "company"]
    if len(company_rows) != 1:
        fail("records", "Each manifest has exactly one scoped company record.")
    company_id = company_rows[0]["id"]
    if value["schema"] == COMPANY_SCHEMA and "target" in company_rows[0] and company_rows[0]["target"]["name"] != value["scope"]["company"]:
        fail("records", "The Company target must match the explicit manifest scope.")
    for row in records:
        if row["kind"] != "company" and "company_id" in row["fields"] and row["fields"]["company_id"] != company_id:
            fail("records." + row["id"], "Cross-company references are not supported.")
        spec = SPECS[row["kind"]]
        for key, kind in {**spec["required"], **spec["optional"]}.items():
            if kind.startswith("ref:") and key in row["fields"]:
                ref = by_id.get(row["fields"][key])
                if not ref or ref["kind"] != kind[4:]:
                    fail("records." + row["id"] + "." + key, "Reference must resolve to the declared entity kind in this manifest.")
    # Parent cycles are invalid even though no import effect is enabled.
    for row in records:
        if row["kind"] == "cost_center":
            seen, current = set(), row
            while current["fields"].get("parent_id"):
                if current["id"] in seen:
                    fail("records." + row["id"], "Cost center parent references contain a cycle.")
                seen.add(current["id"])
                current = by_id[current["fields"]["parent_id"]]
    _conversions(value["unit_conversions"], by_id)
    quantities = value.get("quantities", [])
    if not isinstance(quantities, list) or len(quantities) > MAX_QUANTITIES:
        fail("quantities", "Use up to 500 exact quantity examples.")
    quantity_ids = set()
    reserved_ids = set(by_id) | {row["id"] for row in value["unit_conversions"]}
    for index, row in enumerate(quantities):
        path = f"quantities[{index}]"
        strict_object(row, {"id", "amount", "unit_id"}, {"convert_to_unit_id"}, path)
        uuid(row["id"], path + ".id")
        if row["id"] in quantity_ids or row["id"] in reserved_ids:
            fail(path + ".id", "Duplicate immutable quantity identity.")
        quantity_ids.add(row["id"])
        amount = decimal_quantity(row["amount"], path + ".amount")
        uuid(row["unit_id"], path + ".unit_id")
        unit = by_id.get(row["unit_id"])
        if not unit or unit["kind"] != "uom":
            fail(path + ".unit_id", "Quantity unit must resolve to a declared unit.")
        if max(0, -amount.as_tuple().exponent) > unit["fields"]["precision"]:
            fail(path + ".amount", "Quantity exceeds the declared unit precision.")
        if "convert_to_unit_id" in row:
            uuid(row["convert_to_unit_id"], path + ".convert_to_unit_id")
            conversion_fraction(value, row["unit_id"], row["convert_to_unit_id"])
    return value


def _conversions(conversions, records):
    if not isinstance(conversions, list) or len(conversions) > MAX_CONVERSIONS:
        fail("unit_conversions", "Use up to 1000 exact unit conversions.")
    ids, pairs, graph = set(records), set(), {}
    for index, row in enumerate(conversions):
        path = f"unit_conversions[{index}]"
        strict_object(row, {"id", "revision", "from_unit_id", "to_unit_id", "dimension", "numerator", "denominator", "source"}, set(), path)
        uuid(row["id"], path + ".id")
        if row["id"] in ids:
            fail(path + ".id", "Duplicate immutable conversion identity.")
        ids.add(row["id"])
        if type(row["revision"]) is not int or not 1 <= row["revision"] <= 2**31 - 1:
            fail(path + ".revision", "Use a positive conversion revision.")
        text(row["source"], path + ".source")
        uuid(row["from_unit_id"], path + ".from_unit_id")
        uuid(row["to_unit_id"], path + ".to_unit_id")
        first, second = records.get(row["from_unit_id"]), records.get(row["to_unit_id"])
        if not first or not second or first["kind"] != "uom" or second["kind"] != "uom":
            fail(path, "Both conversion endpoints must resolve to declared units.")
        if row["dimension"] != first["fields"]["dimension"] or row["dimension"] != second["fields"]["dimension"]:
            fail(path, "Conversion endpoints must have exactly the same declared dimension.")
        numerator = positive_integer(row["numerator"], path + ".numerator")
        denominator = positive_integer(row["denominator"], path + ".denominator")
        if math.gcd(numerator, denominator) != 1:
            fail(path, "Conversion rational factors must be reduced to lowest terms.")
        pair = (row["from_unit_id"], row["to_unit_id"])
        if pair in pairs or pair[0] == pair[1]:
            fail(path, "Use one conversion per directed pair and distinct unit endpoints.")
        pairs.add(pair)
        factor = Fraction(numerator, denominator)
        graph.setdefault(pair[0], []).append((pair[1], factor))
        graph.setdefault(pair[1], []).append((pair[0], 1 / factor))
    assigned = {}
    for start in graph:
        if start in assigned:
            continue
        assigned[start] = Fraction(1)
        todo = deque([start])
        while todo:
            node = todo.popleft()
            for neighbor, factor in graph[node]:
                expected = assigned[node] * factor
                if max(abs(expected.numerator).bit_length(), expected.denominator.bit_length()) > 1024:
                    fail("unit_conversions", "Conversion paths exceed the supported exact rational budget.")
                if neighbor in assigned and assigned[neighbor] != expected:
                    fail("unit_conversions", "Conversion paths disagree; resolve the conflicting rational cycle.")
                if neighbor not in assigned:
                    assigned[neighbor] = expected
                    todo.append(neighbor)


def conversion_fraction(manifest, from_id, to_id):
    records = {row["id"]: row for row in manifest["records"]}
    first, second = records.get(from_id), records.get(to_id)
    if not first or not second or first["kind"] != "uom" or second["kind"] != "uom" or first["fields"]["dimension"] != second["fields"]["dimension"]:
        fail("quantity.units", "Quantity conversion requires compatible declared unit dimensions.")
    graph = {}
    for row in manifest["unit_conversions"]:
        factor = Fraction(int(row["numerator"]), int(row["denominator"]))
        graph.setdefault(row["from_unit_id"], []).append((row["to_unit_id"], factor))
        graph.setdefault(row["to_unit_id"], []).append((row["from_unit_id"], 1 / factor))
    todo, seen = deque([(from_id, Fraction(1))]), {from_id}
    while todo:
        node, factor = todo.popleft()
        if node == to_id:
            return factor
        for neighbor, next_factor in graph.get(node, []):
            if neighbor not in seen:
                seen.add(neighbor)
                todo.append((neighbor, factor * next_factor))
    fail("quantity.units", "No explicit exact conversion path is declared.")


def quantity_previews(manifest):
    result = []
    for row in manifest.get("quantities", []):
        if "convert_to_unit_id" not in row:
            continue
        value = Fraction(Decimal(row["amount"])) * conversion_fraction(manifest, row["unit_id"], row["convert_to_unit_id"])
        result.append({"id": row["id"], "from_amount": row["amount"], "from_unit_id": row["unit_id"],
                       "to_unit_id": row["convert_to_unit_id"], "exact_numerator": str(value.numerator),
                       "exact_denominator": str(value.denominator), "rounding_applied": False})
    return result


def manifest_digest(manifest):
    # Ordering is meaningful for display but must not change record identity or source digest.
    stable = {**manifest, "records": sorted(manifest["records"], key=lambda r: r["id"]),
              "unit_conversions": sorted(manifest["unit_conversions"], key=lambda r: r["id"])}
    if "quantities" in stable:
        stable["quantities"] = sorted(stable["quantities"], key=lambda r: r["id"])
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def manifest_requirements(manifest):
    return [{"code": "company_timezone_unconfigured", "record_id": row["id"],
             "message": "Configure the actual company time zone before any future operational import or effect."}
            for row in manifest["records"] if row["kind"] == "company" and row["fields"]["timezone"] is None]
