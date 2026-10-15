"""Strict transport primitives; independent of Frappe for boundary verification."""

from datetime import datetime, timezone
import hashlib
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from .errors import DomainError

SCHEMA = "cipher.api.v1"


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def text(value, name, maximum=140, required=True):
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise DomainError("invalid_input", f"{name} must be text.")
    result = value.strip()
    if (required and not result) or len(result) > maximum or "\x00" in result:
        raise DomainError("invalid_input", f"{name} must contain {'1' if required else '0'} to {maximum} characters.")
    return result


def operation_id(value):
    value = text(value, "Operation ID", 36)
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise DomainError("invalid_operation_id", "Use a canonical UUID operation ID.") from None
    if str(parsed) != value or parsed.version != 4:
        raise DomainError("invalid_operation_id", "Use a canonical UUID version 4 operation ID.")
    return value


def expected_version(value):
    if value is None or value == "":
        raise DomainError("version_required", "Refresh this record before saving.", 428)
    return text(value, "Expected version", 80)


def version_of(doc):
    value = doc.get("modified")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S.%f")
    return str(value)


def utc_timestamp(value=None, source_timezone=None):
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        # Frappe stores naive document timestamps in the configured site timezone.
        # Callers presenting persisted records must supply that source timezone.
        value = value.replace(tzinfo=ZoneInfo(source_timezone) if source_timezone else timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def money(value, currency="USD", precision=2):
    """Approved API money representation: exact decimal strings with currency."""
    if not isinstance(value, str) or not re.fullmatch(r"-?(0|[1-9][0-9]*)\.[0-9]{" + str(precision) + r"}", value):
        raise DomainError("invalid_money", "Use a canonical decimal money string at currency precision.")
    amount = Decimal(value)
    if amount == 0 and value.startswith("-") or abs(amount) >= Decimal("10000000000000"):
        raise DomainError("invalid_money", "Money exceeds the supported range or is negative zero.")
    if not isinstance(currency, str) or not re.fullmatch("[A-Z]{3}", currency):
        raise DomainError("invalid_currency", "Use a three-letter currency code.")
    return {"amount": value, "currency": currency}
