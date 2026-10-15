"""Independent process/SQLite receipt tests; no provider or Frappe fixture."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.integrations import distribution_contracts as rules


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "independent-sink.sqlite3")
        self.content = b"%PDF-1.4\nExact issued synthetic bytes\n%%EOF"
        self.payload = {"attachment": {"sha256": hashlib.sha256(self.content).hexdigest(), "byte_length": len(self.content)},
            "recipient": {"name": "Synthetic intended recipient", "email": "recipient@example.invalid"},
            "message": {"subject": "Synthetic exact issue", "body": "Original text"}}
        self.key = rules.logical_key("dispatch-identity", "exact-issued-recipient")

    def invoke(self, operation="accept", *, payload=None, content=None, deadline=None, check=True):
        args = {"operation": operation, "logical_key": self.key}
        if operation == "accept":
            args.update(payload=payload or self.payload, content_base64=base64.b64encode(content if content is not None else self.content).decode(),
                attempt_not_after=deadline or (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat())
        result = subprocess.run([sys.executable, "-m", "cipher_aec.integrations.distribution_sink", self.path], input=canonical_json(args), capture_output=True, text=True, timeout=15)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)["receipt"]
        return result

    def test_independent_process_commits_original_bytes_before_exact_readback(self):
        receipt = self.invoke()
        self.assertEqual(receipt, self.invoke("readback"))
        with sqlite3.connect(self.path) as database:
            row = database.execute("SELECT payload_hash,pdf FROM receipt").fetchone()
        self.assertEqual(row, (digest(self.payload), self.content))
        self.assertEqual(receipt["mode"], "fixture")

    def test_concurrent_same_key_has_one_durable_receipt_and_original_ack(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: self.invoke(), range(2)))
        self.assertEqual(first, second)
        with sqlite3.connect(self.path) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM receipt").fetchone()[0], 1)

    def test_lost_ack_recovery_uses_same_key_and_does_not_insert_again(self):
        self.invoke()  # Treat the process's successful output as lost to Frappe.
        recovered = self.invoke("readback")
        self.assertEqual(self.invoke(), recovered)
        self.assertEqual(recovered["logical_key"], self.key)

    def test_authoritative_absence_waits_for_accept_past_deadline_check(self):
        ready = str(Path(self.directory.name) / "past-deadline-check")
        release = str(Path(self.directory.name) / "resume-commit")
        # This separate test process pauses after capturing the deadline-check
        # clock while BEGIN IMMEDIATE is held. No production fault hook exists.
        program = """
import base64,json,sys,time
from pathlib import Path
from cipher_aec.integrations import distribution_sink as sink
request=json.loads(sys.stdin.read())
clock=sink.datetime
class PausedClock:
 @staticmethod
 def now(tz):
  instant=clock.now(tz)
  Path(request['ready']).touch()
  while not Path(request['release']).exists(): time.sleep(0.005)
  return instant
sink.datetime=PausedClock
receipt=sink.accept(sys.argv[1],request['key'],request['payload'],base64.b64decode(request['content']),request['deadline'])
print(json.dumps(receipt))
"""
        request = {"ready": ready, "release": release, "key": self.key, "payload": self.payload,
            "content": base64.b64encode(self.content).decode(), "deadline": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()}
        process = subprocess.Popen([sys.executable, "-c", program, self.path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        process.stdin.write(json.dumps(request));process.stdin.close()
        deadline = time.monotonic() + 5
        while not Path(ready).exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(Path(ready).exists())
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.invoke, "readback")
            time.sleep(1.1)
            self.assertFalse(pending.done(), "An uncommitted accepted transaction must not look absent")
            Path(release).touch()
            observed = pending.result(timeout=10)
        process.wait(timeout=5)
        self.assertEqual(process.returncode, 0, process.stderr.read())
        original = json.loads(process.stdout.read())
        process.stderr.close();process.stdout.close()
        self.assertEqual(observed, original)

    def test_same_key_changed_message_or_pdf_is_refused_without_rewrite(self):
        original = self.invoke()
        changed = {**self.payload, "message": {"subject": "Changed", "body": "Unauthorized"}}
        self.assertNotEqual(self.invoke(payload=changed, check=False).returncode, 0)
        self.assertNotEqual(self.invoke(content=self.content + b"changed", check=False).returncode, 0)
        self.assertEqual(self.invoke("readback"), original)

    def test_expired_attempt_cannot_accept_but_prior_receipt_remains_observable(self):
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.assertNotEqual(self.invoke(deadline=expired, check=False).returncode, 0)
        self.assertIsNone(self.invoke("readback"))
        original = self.invoke()
        self.assertEqual(self.invoke("readback"), original)

    def test_original_recipient_subset_only_and_stable_dispatch_identity(self):
        issued = [{"name": "One", "email": "one@example.invalid", "organization": "Org"},
            {"name": "Two", "email": "two@example.invalid", "organization": "Org"}]
        identities = rules.chosen_recipients(issued, None)
        self.assertEqual(rules.chosen_recipients(issued, [identities[1]["id"]]), [identities[1]])
        for selected in (["new-address"], [identities[0]["id"], identities[0]["id"]], []):
            with self.assertRaises(DomainError):
                rules.chosen_recipients(issued, selected)
        self.assertEqual(rules.logical_key("dispatch", identities[0]["id"]), rules.logical_key("dispatch", identities[0]["id"]))
        self.assertNotEqual(rules.logical_key("successor-dispatch", identities[0]["id"]), rules.logical_key("dispatch", identities[0]["id"]))

    def test_corrupt_independent_receipt_is_never_reported_as_success(self):
        self.invoke()
        with sqlite3.connect(self.path) as database:
            database.execute("UPDATE receipt SET pdf=?", (b"corrupt",))
        self.assertNotEqual(self.invoke("readback", check=False).returncode, 0)

    def test_plain_message_rejects_header_injection(self):
        with self.assertRaises(DomainError):
            rules.message("Subject\r\nBcc: other@example.invalid", "body")

    def test_fixture_profile_requires_explicit_operator_boolean(self):
        self.assertTrue(rules.fixture_enabled(True))
        self.assertTrue(rules.fixture_enabled(1))
        for value in (False, None, 0, "false", "False", "True", "", "enabled", {}, []):
            self.assertFalse(rules.fixture_enabled(value))

    def test_attachment_schema_accepts_native_canonical_document_names(self):
        from jsonschema import Draft202012Validator, FormatChecker
        from uuid import uuid4
        path = Path(__file__).parents[1] / "integrations/schemas/distribution-v1.schema.json"
        value = json.loads(path.read_text())
        example = {"document_id": "DOC-" + str(uuid4()), "revision_id": "REV-" + str(uuid4()),
            "sha256": hashlib.sha256(self.content).hexdigest(), "byte_length": len(self.content), "media_type": "application/pdf"}
        Draft202012Validator({**value, "$ref": "#/$defs/DistAttachment"}, format_checker=FormatChecker()).validate(example)
