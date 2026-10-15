"""Durable opt-in synthetic HTTP command recorder plus explicit fixture unit tests.

Journal entries contain authored test payloads/UUIDs, never login bodies, cookies,
CSRF tokens or headers. Actual evidence labels HTTP observations separately from
this module's explicitly simulated transport fixture.
"""
import hashlib
import json
import os
from pathlib import Path
import time
import unittest
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4


class CommandRecorder:
    def __init__(self, path):
        self.path = Path(path)
        self.entries = json.loads(self.path.read_text()) if self.path.exists() else []

    def _write(self):
        target = self.path.with_name(self.path.name + ".pending")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(self.entries, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(target, self.path)
        directory = os.open(self.path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def send(self, client, method, payload, *, operation_id, expected=(200,), retries=0):
        if str(UUID(operation_id)) != operation_id:
            raise ValueError("Record the canonical operation UUID before sending")
        def secret(value):
            if isinstance(value, dict):
                return any(key.lower() in {"pwd", "password", "csrf_token", "sid", "cookie", "authorization"} or secret(item) for key, item in value.items())
            return isinstance(value, list) and any(secret(item) for item in value)
        if secret(payload):
            raise ValueError("Credential/session fields must never enter the command journal")
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        entry = {"operation_id": operation_id, "method": method, "payload": payload,
                 "payload_sha256": hashlib.sha256(body.encode()).hexdigest(), "state": "prepared-before-send", "attempts": []}
        self.entries.append(entry)
        self._write()
        for attempt in range(retries + 1):
            if hasattr(client, "request"):
                status, body, _, _ = client.request("POST", "/api/method/" + method, payload, operation=operation_id)
                envelope = body.get("message", body)
                if envelope.get("schema") != "cipher.api.v1" or not envelope.get("request_id"):
                    raise RuntimeError("The recorded command requires a versioned Cipher response")
                entry.setdefault("response_envelopes", []).append({"http_status": status, "envelope": envelope})
                client.observations[-1]["request_id"] = envelope["request_id"]
                result = envelope.get("data") if status < 400 else envelope.get("error")
            else:
                # Only the explicitly named unit-test transport fixture uses
                # this branch. Real qualification stores exact HTTP envelopes.
                result = client.api(method, payload, method="POST", operation=operation_id, expected=tuple(set(expected) | {503}))
                status = client.observations[-1]["status"]
            entry["attempts"].append({"status": status, "error_code": result.get("code") if status >= 400 else None})
            entry["state"] = "response-recorded"
            self._write()
            if status != 503:
                if status not in expected:
                    raise AssertionError("Unexpected recorded HTTP status")
                return result
            if result.get("code") != "concurrent_change" or attempt == retries:
                raise RuntimeError("Recorded command did not complete; retain its UUID/payload for a later retry")
            time.sleep(0.01)
        raise AssertionError("Unreachable recorder state")


class DurableHTTPRecorderTests(unittest.TestCase):
    def test_explicit_fixture_503_retry_keeps_one_uuid_and_records_before_network(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            recorder = CommandRecorder(path)
            operation = str(uuid4())
            class ExplicitTransportFixture:
                observations = []
                operations = []
                def api(self, name, payload, **kwargs):
                    prepared = json.loads(path.read_text())[-1]
                    self.operations.append(kwargs["operation"])
                    assert prepared["operation_id"] == operation and prepared["payload"] == {"explicit_fixture": True}
                    status = 503 if len(self.operations) == 1 else 200
                    self.observations.append({"status": status})
                    return {"code": "concurrent_change"} if status == 503 else {"explicit_fixture_result": "succeeded"}
            fixture = ExplicitTransportFixture()
            result = recorder.send(fixture, "explicit.fixture.only", {"explicit_fixture": True}, operation_id=operation, retries=1)
            self.assertEqual(result, {"explicit_fixture_result": "succeeded"})
            self.assertEqual(fixture.operations, [operation, operation])
            self.assertEqual([row["status"] for row in recorder.entries[-1]["attempts"]], [503, 200])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_credentials_never_recorded(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            with self.assertRaises(ValueError):
                CommandRecorder(path).send(None, "never.called", {"password": "explicit-fixture-secret"}, operation_id=str(uuid4()))
            self.assertFalse(path.exists())
