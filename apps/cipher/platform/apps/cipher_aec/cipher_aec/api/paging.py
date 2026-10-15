"""Signed, expiring, actor/scope-bound keyset cursors."""

import base64
import hashlib
import hmac
import json
import time

from .contracts import canonical_json, digest
from .errors import DomainError


def page_options(limit=50, cursor=None, count_mode="none"):
    try:
        if isinstance(limit, bool) or str(int(limit)) != str(limit) or not 1 <= int(limit) <= 200:
            raise ValueError
    except (ValueError, TypeError):
        raise DomainError("invalid_page", "Use a page limit from 1 to 200.") from None
    if count_mode not in {"none", "exact"}:
        raise DomainError("invalid_count_mode", "Use none or exact count mode.")
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 4096):
        raise DomainError("invalid_cursor", "This page cursor is invalid.", 422)
    return int(limit), cursor or None, count_mode


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value):
    decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _encode(decoded) != value:
        raise ValueError("Noncanonical cursor encoding")
    return decoded


def encode_cursor(*, secret, scope, last, now=None):
    now = int(time.time() if now is None else now)
    payload = {"v": 1, "scope": digest(scope), "last": last, "expires": now + 900}
    body = canonical_json(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return _encode(body) + "." + _encode(signature)


def decode_cursor(cursor, *, secret, scope, now=None):
    now = int(time.time() if now is None else now)
    try:
        encoded_body, encoded_signature = cursor.split(".")
        body, signature = _decode(encoded_body), _decode(encoded_signature)
        expected = hmac.new(secret.encode(), body, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(body)
        if set(payload) != {"v", "scope", "last", "expires"} or payload["v"] != 1 or payload["scope"] != digest(scope):
            raise ValueError
        if not isinstance(payload["expires"], int) or payload["expires"] < now:
            raise ValueError
        last = payload["last"]
        if not isinstance(last, list) or len(last) != 2 or not all(isinstance(item, str) and 0 < len(item) <= 200 for item in last):
            raise ValueError
        return last
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise DomainError("invalid_cursor", "This page cursor expired or does not match the current user and filters. Refresh the list.", 422) from None


def signing_secret():
    import frappe
    secret = frappe.conf.get("encryption_key")
    if not isinstance(secret, str) or len(secret) < 16:
        raise DomainError("cursor_unavailable", "The site's cursor signing key is unavailable.", 503)
    return hmac.new(secret.encode(), b"cipher.cursor.v1", hashlib.sha256).hexdigest()


def page_result(items, *, has_more, last, scope, limit, count_mode, total):
    cursor = encode_cursor(secret=signing_secret(), scope=scope, last=last) if has_more and last else None
    return {"items": items, "next_cursor": cursor, "limit": limit, "count_mode": count_mode, "total": total}
