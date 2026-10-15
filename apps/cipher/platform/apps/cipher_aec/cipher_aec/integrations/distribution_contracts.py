"""Exact immutable transport identities; no provider or framework dependency."""
from datetime import datetime, timezone
import hashlib

from cipher_aec.api.contracts import digest, text
from cipher_aec.api.errors import DomainError

ACTION = "proposal.distribute.v1"
KIND = "company.proposal.fixture.v1"
PROFILE = "local-fixture-v1"
MAX_RECIPIENTS = 30
MAX_BYTES = 20 * 1024 * 1024
MANDATE_SECONDS = 24 * 60 * 60
ATTEMPT_SECONDS = 30
LEASE_SECONDS = 60


def fixture_enabled(value):
    return value is True or (type(value) is int and value == 1)


def chosen_recipients(issued, requested):
    """Identity is the exact originally issued recipient; address changes are new issue inputs."""
    if type(issued) is not list or not 1 <= len(issued) <= MAX_RECIPIENTS:
        raise DomainError("distribution_integrity", "The issued recipient set cannot be verified.", 409)
    records = [{"id": digest({"schema": "cipher.issued.recipient.v1", "recipient": row}), **row} for row in issued]
    if len({r["id"] for r in records}) != len(records):
        raise DomainError("distribution_integrity", "The issued recipient set is ambiguous.", 409)
    if requested is None:
        return records
    if type(requested) is not list or not 1 <= len(requested) <= MAX_RECIPIENTS or any(type(value) is not str for value in requested) or len(set(requested)) != len(requested):
        raise DomainError("invalid_distribution", "Choose each exact issued recipient identity once.", 422)
    if not set(requested) <= {r["id"] for r in records}:
        raise DomainError("invalid_distribution", "Distribution cannot add or change an issued recipient. Author a successor revision.", 422)
    return [row for row in records if row["id"] in requested]


def message(subject, body):
    value = {"subject": text(subject, "Message subject", 240), "body": text(body, "Message body", 20000, required=False)}
    if any(character in value["subject"] for character in "\r\n\x00") or "\x00" in value["body"]:
        raise DomainError("invalid_distribution", "Use plain message text without header control characters.", 422)
    return value


def logical_key(dispatch_id, recipient_id):
    return digest({"schema": "cipher.distribution.recipient.v1", "dispatch": dispatch_id, "recipient": recipient_id})


def utc_now():
    return datetime.now(timezone.utc)


def moment(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Distribution deadlines require an explicit timezone")
    return parsed.astimezone(timezone.utc)


def verify_bytes(content, attachment):
    if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_BYTES or len(content) != attachment["byte_length"] or hashlib.sha256(content).hexdigest() != attachment["sha256"]:
        raise DomainError("distribution_integrity", "The exact issued PDF bytes cannot be verified.", 409)
