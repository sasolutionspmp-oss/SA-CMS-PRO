"""Identifiers, canonical JSON and hashing."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import secrets
import time
from decimal import Decimal


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def utcnow_iso() -> str:
    return utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(text: str) -> _dt.datetime:
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return _dt.datetime.fromisoformat(text)


_last_ms = 0
_seq = 0


def new_id(prefix: str) -> str:
    """Time-ordered identifier: prefix, millisecond clock, sequence, random."""
    global _last_ms, _seq
    ms = int(time.time() * 1000)
    if ms == _last_ms:
        _seq += 1
    else:
        _last_ms = ms
        _seq = 0
    return f"{prefix}_{ms:013x}{_seq:03x}{secrets.token_hex(3)}"


def _json_default(obj):
    if isinstance(obj, Decimal):
        return f"{obj:f}"
    if isinstance(obj, (_dt.datetime, _dt.date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


def canonical_json(obj) -> str:
    """Deterministic JSON: sorted keys, no whitespace, Decimal as string."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_json_default, ensure_ascii=False)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hash_json(obj) -> str:
    return sha256_hex(canonical_json(obj))


def loads(text: str | None):
    if text is None:
        return None
    return json.loads(text)
