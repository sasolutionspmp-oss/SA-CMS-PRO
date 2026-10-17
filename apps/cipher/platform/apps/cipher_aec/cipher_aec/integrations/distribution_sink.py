"""Independent, durable synthetic sink. This process never imports Frappe.

The caller supplies a server-owned database path. No SMTP, HTTP or real delivery
exists. Receipt commit is independent of the Frappe operation transaction.
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

from cipher_aec.api.contracts import canonical_json, digest
from .distribution_contracts import moment, verify_bytes


def _connect(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("The sink requires its server-configured absolute path")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    database = sqlite3.connect(path, timeout=10)
    path.chmod(0o600)
    database.execute("PRAGMA synchronous=FULL")
    database.execute("CREATE TABLE IF NOT EXISTS receipt (logical_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, payload_json TEXT NOT NULL, pdf BLOB NOT NULL, acknowledgment TEXT NOT NULL UNIQUE, accepted_at TEXT NOT NULL)")
    database.commit()
    return database


def _receipt(row):
    key, checksum, body, pdf, ack, accepted = row
    payload = json.loads(body)
    if digest(payload) != checksum:
        raise ValueError("The fixture sink payload failed integrity verification")
    verify_bytes(pdf, payload["attachment"])
    return {"mode": "fixture", "logical_key": key, "payload_hash": checksum,
        "attachment_sha256": hashlib.sha256(pdf).hexdigest(), "byte_length": len(pdf),
        "acknowledgment_id": ack, "accepted_at": accepted}


def readback(path, logical_key):
    with _connect(path) as database:
        # Definitive absence must serialize with an accept that passed its
        # deadline check but has not committed. A busy timeout is Unknown,
        # never evidence that an in-flight transport did not accept.
        database.execute("BEGIN IMMEDIATE")
        row = database.execute("SELECT * FROM receipt WHERE logical_key=?", (logical_key,)).fetchone()
        return _receipt(row) if row else None


def accept(path, logical_key, payload, pdf, attempt_not_after):
    verify_bytes(pdf, payload["attachment"])
    checksum = digest(payload)
    with _connect(path) as database:
        database.execute("BEGIN IMMEDIATE")
        row = database.execute("SELECT * FROM receipt WHERE logical_key=?", (logical_key,)).fetchone()
        if row:
            if row[1] != checksum:
                raise ValueError("The delivery key already identifies another exact payload")
            return _receipt(row)
        # A late/resumed old attempt cannot newly accept after its short window.
        if moment(attempt_not_after) <= datetime.now(timezone.utc):
            raise ValueError("The authorized fixture delivery attempt expired")
        database.execute("INSERT INTO receipt VALUES (?,?,?,?,?,?)", (logical_key, checksum,
            canonical_json(payload), pdf, str(uuid4()), datetime.now(timezone.utc).isoformat()))
        database.commit()
        return _receipt(database.execute("SELECT * FROM receipt WHERE logical_key=?", (logical_key,)).fetchone())


def main():
    request = json.loads(sys.stdin.read(30 * 1024 * 1024))
    if request["operation"] == "readback":
        result = readback(sys.argv[1], request["logical_key"])
    elif request["operation"] == "accept":
        result = accept(sys.argv[1], request["logical_key"], request["payload"],
            base64.b64decode(request["content_base64"], validate=True), request["attempt_not_after"])
    else:
        raise ValueError("Unsupported fixture sink operation")
    sys.stdout.write(canonical_json({"receipt": result}) + "\n")


if __name__ == "__main__":
    main()
