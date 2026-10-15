"""Bounded authored proposal contracts; no Frappe or binary floating arithmetic."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
import re
from uuid import UUID
from cipher_aec.api.contracts import text, digest
from cipher_aec.api.errors import DomainError


def identifier(value):
    try:
        parsed = UUID(value)
        if str(parsed) != value or parsed.version not in (4, 5):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise DomainError("invalid_commercial", "Use a canonical stable UUID.") from None
    return value


def decimal(value, *, positive=False):
    if type(value) is not str or not re.fullmatch(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,9})?", value):
        raise DomainError("invalid_commercial", "Use an unsigned exact decimal string with at most nine decimal places.")
    result = Decimal(value)
    if positive and result <= 0:
        raise DomainError("invalid_commercial", "Quantity must be positive.")
    return result


def business_date(value):
    try:
        if type(value) is not str or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except (ValueError, TypeError):
        raise DomainError("invalid_commercial", "Use an ISO calendar date.") from None
    return value


def keys(value, allowed, required=()):
    if type(value) is not dict or set(value) - set(allowed) or set(required) - set(value):
        raise DomainError("invalid_commercial", "The commercial payload contains unsupported or missing fields.")


def pursuit_fields(value):
    allowed = ("title", "sector", "delivery_method", "geography", "bid_due_at", "bid_timezone", "procurement_reference", "probability_basis")
    keys(value, allowed, ("title",))
    result = {key: text(value.get(key, ""), key, 2000 if key == "probability_basis" else 140, required=key == "title") for key in allowed}
    if result["bid_due_at"]:
        from datetime import datetime
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            parsed = datetime.fromisoformat(result["bid_due_at"].replace("Z", "+00:00"))
            if parsed.tzinfo is None or not result["bid_timezone"]:
                raise ValueError
            ZoneInfo(result["bid_timezone"])
        except (ValueError, ZoneInfoNotFoundError):
            raise DomainError("invalid_commercial", "Bid due time requires an offset and explicit IANA timezone.") from None
    return result


def composition(value):
    keys(value, ("currency", "price_list", "valid_till", "terms", "sections", "price_lines", "source_references", "estimate_revision"), ("currency", "price_list", "valid_till", "terms", "sections", "price_lines"))
    if "source_references" in value and type(value["source_references"]) is not list:
        raise DomainError("invalid_commercial", "Source references must be an array.")
    if value.get("source_references") or value.get("estimate_revision") is not None:
        raise DomainError("company_reference_unavailable", "Company-scoped document citations and estimate links are not yet qualified.", 409)
    currency = text(value["currency"], "currency", 3)
    if not re.fullmatch("[A-Z]{3}", currency):
        raise DomainError("invalid_commercial", "Use an uppercase three-letter currency code.")
    sections, lines = value["sections"], value["price_lines"]
    if type(sections) is not list or len(sections) > 80 or type(lines) is not list or not 1 <= len(lines) <= 150:
        raise DomainError("invalid_commercial", "Use at most 80 sections and between one and 150 price lines.")
    normalized_sections = []
    for row in sections:
        keys(row, ("id", "kind", "title", "text"), ("id", "kind", "title", "text"))
        if row["kind"] not in ("scope", "assumption", "exclusion", "schedule", "other"):
            raise DomainError("invalid_commercial", "Use a supported plain-text section kind.")
        normalized_sections.append({"id": identifier(row["id"]), "kind": row["kind"], "title": text(row["title"], "section title"), "text": text(row["text"], "section text", 12000, required=False)})
    normalized_lines = []
    groups = {}
    for row in lines:
        keys(row, ("id", "description", "quantity", "unit_id", "unit_revision", "rate", "item_code", "alternate_group", "selected"), ("id", "description", "quantity", "unit_id", "unit_revision", "rate", "selected"))
        decimal(row["quantity"], positive=True)
        decimal(row["rate"])
        if type(row["selected"]) is not bool or type(row["unit_revision"]) is not int or row["unit_revision"] < 1:
            raise DomainError("invalid_commercial", "Declare a unit revision and explicit selected boolean.")
        group = identifier(row["alternate_group"]) if row.get("alternate_group") else None
        item = text(row.get("item_code", ""), "Item", required=False) or None
        result = {"id": identifier(row["id"]), "description": text(row["description"], "line description", 2000), "quantity": row["quantity"], "unit_id": identifier(row["unit_id"]), "unit_revision": row["unit_revision"], "rate": row["rate"], "item_code": item, "alternate_group": group, "selected": row["selected"]}
        normalized_lines.append(result)
        if group:
            groups.setdefault(group, []).append(result)
        elif not result["selected"]:
            raise DomainError("invalid_commercial", "An unselected line must belong to an explicit alternate group.")
    for rows in groups.values():
        if len(rows) < 2 or sum(row["selected"] for row in rows) != 1:
            raise DomainError("invalid_commercial", "Each alternate group requires two or more lines and exactly one selected line.")
    for rows in (normalized_sections, normalized_lines):
        if len({row["id"] for row in rows}) != len(rows):
            raise DomainError("invalid_commercial", "Section and line UUIDs must be unique in their collection.")
    return {"currency": currency, "price_list": text(value["price_list"], "Native selling price list"), "valid_till": business_date(value["valid_till"]), "terms": text(value["terms"], "terms", 24000, required=False), "sections": normalized_sections, "price_lines": normalized_lines, "source_references": [], "estimate_revision": None}


def pricing(value, exponent):
    quantum = Decimal(1).scaleb(-exponent)
    with localcontext() as context:
        context.prec = 60
        rows = []
        for row in value["price_lines"]:
            raw = decimal(row["quantity"]) * decimal(row["rate"])
            if raw >= Decimal("1000000000000"):
                raise DomainError("unsupported_native_precision", "Line amounts exceed the qualified native decimal range.")
            rows.append({**row, "amount": format(raw.quantize(quantum, rounding=ROUND_HALF_UP), "f")})
    total = sum((Decimal(row["amount"]) for row in rows if row["selected"]), Decimal(0)).quantize(quantum)
    if total >= Decimal("1000000000000"):
        raise DomainError("unsupported_native_precision", "Proposal totals exceed the qualified native decimal range.")
    return {"policy": "native-no-tax-no-discount-half-up-v1", "currency_exponent": exponent, "lines": rows, "total": format(total, "f")}


def native_order(lines):
    result, seen = [], set()
    for row in lines:
        group = row["alternate_group"]
        if not group:
            result.append(row)
        elif group not in seen:
            group_rows = [entry for entry in lines if entry["alternate_group"] == group]
            result.extend([entry for entry in group_rows if entry["selected"]] + [entry for entry in group_rows if not entry["selected"]])
            seen.add(group)
    return result


def compare(left, right):
    def changes(key):
        before, after = {r["id"]: r for r in left[key]}, {r["id"]: r for r in right[key]}
        return {"added": [r for r in right[key] if r["id"] not in before], "removed": [r for r in left[key] if r["id"] not in after], "changed": [{"id": i, "before": before[i], "after": after[i]} for i in before if i in after and before[i] != after[i]], "order_changed": [r["id"] for r in left[key]] != [r["id"] for r in right[key]]}
    return {"sections": changes("sections"), "price_lines": changes("price_lines"), "terms": {"before": left["terms"], "after": right["terms"], "changed": left["terms"] != right["terms"]}, "validity": {"before": left["valid_till"], "after": right["valid_till"], "changed": left["valid_till"] != right["valid_till"]}}
