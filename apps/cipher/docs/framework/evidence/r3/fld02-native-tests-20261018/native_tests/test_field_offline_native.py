"""UNRUN: real Frappe 16.52/MariaDB FLD02 integration tests for local composition.

Proposed destination: cipher_aec/tests/test_field_offline_native.py. Requires an
already installed synthetic site, FLD01/FLD02 controllers, private ACL hooks and
receipt dispatch, plus separate fld02_native_fixture.prepare_fixture execution.
No service, controller, authority, storage, or transaction implementation is
replaced. Only the native test runner may execute this module on an isolated site.
"""
import base64
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import struct
from uuid import uuid4
import zlib

import frappe
from frappe.tests import IntegrationTestCase

from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.document_control import service as document_control
from cipher_aec.documents import service as documents
from cipher_aec.field import contracts as field_rules, repository as field_repository, service as field
from cipher_aec.field_offline import contracts as offline_rules, repository as offline_repository, service as offline
from cipher_aec.governance.commands import read_operation
from cipher_aec.governance.context import current_actor, trusted_write
from cipher_aec.install import _grant, set_synthetic_duty
from cipher_aec.tests.fld02_native_fixture import verify_fixture


class TestFieldOfflineNative(IntegrationTestCase):
    """Each case owns fresh Projects, explicit duties, commands, and source bytes."""

    def setUp(self):
        # IntegrationTestCase class setup owns the framework's initial transaction;
        # its per-case setUp does not roll back or establish this case's savepoint.
        super().setUp()
        self.previous_user = frappe.session.user
        self.previous_session = deepcopy(dict(frappe.session))
        self.previous_request = getattr(frappe.local, "request", None)
        self.had_request = hasattr(frappe.local, "request")
        self.addCleanup(self.restore_context)
        self.fixture = verify_fixture()  # Read only: no seed/install/commit here.
        self.company, self.users = self.fixture["company"], self.fixture["users"]
        self.assert_installed_offline_boundary()
        self.marker = "fld02_native_" + uuid4().hex
        self.upload_attempts = []
        self.uploads = {}
        self.savepoint = self.marker
        frappe.db.savepoint(self.savepoint)
        # Register before the first write so partial setUp failures are covered.
        self.addCleanup(self.rollback_case)
        self.login_administrator()
        with trusted_write():
            self.project = frappe.get_doc({
                "doctype": "Project", "company": self.company,
                "project_name": "FLD02 native " + self.marker, "status": "Open",
            }).insert(ignore_permissions=True).name
            self.other_project = frappe.get_doc({
                "doctype": "Project", "company": self.company,
                "project_name": "FLD02 separate " + self.marker, "status": "Open",
            }).insert(ignore_permissions=True).name
            for key in ("owner", "reviewer"):
                for ability in (
                    "project.read", "document.read", "field.read", "field.write",
                    "field.review", "field.accept", "field.acknowledge",
                ):
                    _grant(self.users[key]["person"], self.company, self.project, ability)
            for ability in ("document.write", "document.control.read", "document.rights.manage"):
                _grant(self.users["owner"]["person"], self.company, self.project, ability)
            for ability in ("project.read", "document.read", "field.read", "field.write"):
                _grant(self.users["outsider"]["person"], self.company, self.other_project, ability)
        self.login("owner")
        self.permission_upload, self.permission_ref = self.upload(
            ("Synthetic authored FLD02 permission declaration: internal Project evidence only. " + self.marker).encode(),
        )
        self.source_bytes = (
            "Exact synthetic installed pipe: 12.375000 LF; UTF-8 observation \u0394. " + self.marker
        ).encode("utf-8")
        self.source_upload, self.source = self.upload(self.source_bytes)
        self.source_document = self.source_upload["document"]["id"]
        self.rights_definition = self.permission_definition()
        self.source_rights = self.set_rights(self.rights_definition)
        self.device_id = str(uuid4())
        self.registration = offline.register_device(
            self.company, self.project, str(uuid4()), self.device_id, "Dedicated synthetic field tablet " + self.marker,
        )

    def restore_context(self):
        frappe.set_user(self.previous_user)
        frappe.session.clear()
        frappe.session.update(self.previous_session)
        if self.had_request:
            frappe.local.request = self.previous_request
        elif hasattr(frappe.local, "request"):
            delattr(frappe.local, "request")

    def rollback_case(self):
        self.login_administrator()
        try:
            frappe.db.rollback(save_point=self.savepoint)
            for attribute in ("project", "other_project"):
                project = getattr(self, attribute, None)
                if project:
                    self.assertFalse(frappe.db.exists("Project", project))
            for upload in self.uploads.values():
                self.assertFalse(frappe.db.exists("Cipher Document Revision", upload["result"]["revision"]["id"]))
                for owned in upload["attempt"]["files"]:
                    self.assertFalse(frappe.db.exists("File", owned["name"]))
            verify_fixture()  # Also proves binding changes and all case duties rolled back.
        finally:
            # File bytes are outside MariaDB's rollback. Delete only this case's
            # predeclared UUID filenames whose exact uploaded bytes still match.
            self.cleanup_upload_files(self.upload_attempts)

    def assert_installed_offline_boundary(self):
        for doctype in offline_repository.KINDS.values():
            self.assertTrue(frappe.db.exists("DocType", doctype), "Local composition must install " + doctype)
            controller = frappe.get_doc({"doctype": doctype}).__class__.__module__
            self.assertTrue(controller.startswith("cipher_aec.cipher_field_offline.doctype."), controller)
            for hook, target in (
                ("permission_query_conditions", "cipher_aec.field_offline.install.query_denied"),
                ("has_permission", "cipher_aec.field_offline.install.permission_denied"),
            ):
                configured = frappe.get_hooks(hook).get(doctype, [])
                if isinstance(configured, str):
                    configured = [configured]
                self.assertIn(target, configured, "Compose the private offline hooks before running native tests.")

    def login(self, key):
        frappe.set_user(self.users[key]["user"])

    def login_administrator(self):
        frappe.set_user("Administrator")

    def upload(self, content, extension="txt", document_id=None, expected_revision=None):
        # Attempts are registered before the service call: even a later command
        # failure can leave a physical File after its metadata was rolled back.
        filename = self.marker + "_" + uuid4().hex + "." + extension
        attempt = {
            "filename": filename, "stem": Path(filename).stem, "suffix": "." + extension,
            "sha256": hashlib.sha256(content).hexdigest(), "size": len(content),
            "project": self.project, "marker": self.marker, "files": [],
        }
        self.upload_attempts.append(attempt)
        result = documents.upload_document(
            company=self.company, project=self.project, title="Exact retained FLD02 source " + self.marker,
            filename=filename, content=content, byte_length=len(content), sha256=attempt["sha256"],
            operation_id=str(uuid4()), document_id=document_id, expected_revision=expected_revision,
        )
        revision_id = result["revision"]["id"]
        native_revision = frappe.get_doc("Cipher Document Revision", revision_id)
        file_doc = frappe.get_doc("File", native_revision.storage_reference)
        self.assertEqual(file_doc.attached_to_doctype, "Cipher Document Revision")
        self.assertEqual(file_doc.attached_to_name, revision_id)
        self.assertEqual(native_revision.project, self.project)
        self.assertEqual(file_doc.file_name, filename)
        self.assertTrue(file_doc.is_private)
        path = Path(file_doc.get_full_path()).resolve()
        self.assertTrue(path.name.startswith(attempt["stem"]))
        attempt["files"].append({"name": file_doc.name, "path": path, "file_url": file_doc.file_url})
        self.assertEqual(result["revision"]["sha256"], attempt["sha256"])
        self.assertEqual(documents.download_revision(self.company, revision_id)[1], content)
        self.uploads[revision_id] = {"result": deepcopy(result), "bytes": content, "attempt": attempt}
        return result, {"revision_id": revision_id, "source_sha256": attempt["sha256"]}

    def cleanup_upload_files(self, attempts):
        private_files = Path(frappe.get_site_path("private", "files")).resolve()
        for attempt in attempts:
            self.assertEqual(attempt["marker"], self.marker)
            self.assertEqual(attempt["project"], self.project)
            self.assertTrue(attempt["stem"].startswith(self.marker + "_"))
            # Frappe can suffix a sanitized filename. This glob contains this
            # upload's independent UUID; it is never a site/global File diff.
            candidates = {entry["path"] for entry in attempt["files"]}
            candidates.update(private_files.glob(attempt["stem"] + "*" + attempt["suffix"]))
            for candidate in candidates:
                if candidate.is_symlink() or not candidate.exists():
                    continue
                path = candidate.resolve()
                self.assertEqual(path.parent, private_files)
                self.assertTrue(path.name.startswith(attempt["stem"]))
                self.assertTrue(path.name.endswith(attempt["suffix"]))
                content = path.read_bytes()
                self.assertEqual(len(content), attempt["size"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), attempt["sha256"])
                # A surviving reference belongs outside the rolled-back work;
                # preserve it even if another document deduplicated these bytes.
                url = "/private/files/" + path.name
                if frappe.db.exists("File", {"file_url": url}):
                    continue
                path.unlink()

    def permission_definition(self):
        return {
            "ingest_allowed": True, "read_allowed": True, "distribute_allowed": False,
            "rights_basis": "Synthetic authored internal-use declaration; no legal permission inference.",
            "rights_holder": "Synthetic FLD02 author", "allowed_purpose": "Internal Project field evidence",
            "restriction": "No outside delivery, commercial change, or financial authority",
            "valid_from": None, "valid_until": None, "evidence_artifact": self.permission_ref,
        }

    def set_rights(self, definition):
        previous = getattr(self, "source_rights", None)
        result = document_control.set_rights(
            self.company, self.project, str(uuid4()), self.source_document,
            digest(previous) if previous else None, definition,
        )["rights"]
        self.source_rights = result
        return result

    def locator(self, reference=None, label="Grid A / exact observed installed pipe"):
        return {**(reference or self.source), "page": 1, "locator": label}

    def expanded_source(self, locator):
        upload = self.uploads[locator["revision_id"]]["result"]
        revision = upload["revision"]
        return {
            **locator, "document_id": upload["document"]["id"],
            "revision_number": revision["revision_number"], "byte_length": revision["byte_length"],
            "mime_type": revision["mime_type"], "page_count": revision["page_count"],
        }

    def daily_definition(self):
        return {
            "local_date": "2026-10-17", "superintendent_user": self.users["owner"]["user"],
            "weather": "", "weather_sources": [], "crews": ["Synthetic two-person civil crew"],
            "activities": ["Installed the exact documented pipe segment."], "delays": [], "visitors": [],
        }

    def quantity(self, value="12.375000", original=None, predecessor=None, reference=None):
        return {
            "original_event_id": original or str(uuid4()), "supersedes_event_id": predecessor,
            "kind": "installed", "description": "Observed installed pipe", "wbs_code": "02.01",
            "cost_code": "PIPE", "quantity": value, "unit": "LF", "location": "Grid A",
            "sources": [self.locator(reference)],
        }

    def envelope(self, *, family="daily", command=None, capture_id=None, quantities=None, photos=None):
        if command is None:
            definition = self.daily_definition() if family == "daily" else {
                "local_date": "2026-10-17", "title": "Documented obstruction removal",
                "customer_name": "Synthetic owner", "location": "Grid A",
                "work_description": "Removed the documented obstruction.",
                "potential_change_reference": "Separate future commercial evaluation only",
                "lines": [{
                    "kind": "labor", "description": "Synthetic field crew observation", "quantity": "3.250000",
                    "unit": "person-hours", "sources": [self.locator()],
                }],
            }
            command = {
                "action": "create", "family": family, "definition": definition,
                "photos": deepcopy(photos or []),
                "quantities": deepcopy(quantities if quantities is not None else [self.quantity()] if family == "daily" else []),
            }
        return {
            "schema": offline_rules.SCHEMA, "device_id": self.device_id,
            "capture_id": capture_id or str(uuid4()), "company": self.company, "project": self.project,
            "actor_person": self.users["owner"]["person"], "actor_user": self.users["owner"]["user"],
            "captured_at": "2026-10-17T09:15:00-04:00", "command": deepcopy(command),
        }

    def revise_envelope(self, previous, value="12.500000", reason=""):
        prior = previous["quantities"][0]
        return self.envelope(command={
            "action": "revise", "family": previous["family"], "record_id": previous["header"]["id"],
            "expected_version": digest(previous["header"]), "base_revision_id": previous["revision"]["id"],
            "base_revision_digest": digest(previous["revision"]), "definition": self.daily_definition(),
            "photos": [], "quantities": [self.quantity(value, prior["original_event_id"], prior["id"])],
            "amendment_reason": reason,
        })

    def stage(self, envelope, operation=None):
        return offline.stage_capture(self.company, self.project, operation or str(uuid4()), envelope)

    def apply(self, envelope, staged):
        return offline.apply_capture(
            self.company, self.project, envelope["capture_id"], envelope["capture_id"], staged["capture_version"],
        )

    def raw_capture(self, envelope):
        return offline_repository.raw("capture", digest({
            "person": self.users["owner"]["person"], "capture_id": envelope["capture_id"],
        }))

    def assert_error(self, code, callback):
        with self.assertRaises(DomainError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def assert_no_business_receipt(self, capture_id):
        self.assertFalse(frappe.db.exists("Cipher Command Receipt", digest({
            "person": self.users["owner"]["person"], "operation_id": capture_id,
        })))

    def field_identity_snapshot(self):
        return {
            kind: sorted(frappe.get_all(doctype, filters={"project": self.project}, pluck="name"))
            for kind, doctype in field_rules.KINDS.items()
        }

    def assert_canonical_receipt(self, envelope, receipt, *, current_header=True):
        """Verify full saved Field facts and independently recomputed receipt bytes."""
        clean = {key: deepcopy(value) for key, value in receipt.items() if key != "operation"}
        command = envelope["command"]
        payload = {key: deepcopy(command[key]) for key in ("family", "definition", "photos", "quantities")}
        if command["action"] == "revise":
            payload.update({key: command[key] for key in ("record_id", "expected_version", "amendment_reason")})
        name = "field." + command["family"] + "." + command["action"] + ".v1"
        request_hash = digest({"command": name, "company": self.company, "project": self.project, "payload": payload})
        native = frappe.get_doc("Cipher Command Receipt", digest({
            "person": self.users["owner"]["person"], "operation_id": envelope["capture_id"],
        }))
        self.assertEqual(native.command, name)
        self.assertEqual(native.state, "Succeeded")
        self.assertEqual(native.person, self.users["owner"]["person"])
        self.assertEqual((native.company, native.project, native.scope_type), (self.company, self.project, "Project"))
        self.assertEqual(native.request_hash, request_hash)
        self.assertEqual(native.result_json, canonical_json(clean))
        self.assertEqual(json.loads(native.result_json), clean)
        self.assertEqual(native.result_hash, digest(clean))
        self.assertEqual(offline_repository.canonical_receipt(self.users["owner"]["person"], envelope["capture_id"]), {
            "command": name, "company": self.company, "project": self.project, "scope_type": "Project",
            "request_hash": request_hash, "result_hash": digest(clean), "state": "Succeeded", "result": clean,
        })
        family = clean["family"]
        if current_header:
            self.assertEqual(field_repository.raw(family, clean["header"]["id"]), clean["header"])
            self.assertEqual(field.get_record(self.company, self.project, family, clean["header"]["id"])["record"], clean["header"])
        self.assertEqual(field_repository.raw(family + "_revision", clean["revision"]["id"]), clean["revision"])
        self.assertEqual(field.get_record(self.company, self.project, family + "_revision", clean["revision"]["id"])["record"], clean["revision"])
        self.assertEqual(clean["revision"]["photos"], [
            {**photo, "source": self.expanded_source(photo["source"])} for photo in command["photos"]
        ])
        self.assertEqual(clean["revision"]["no_effects"], field_rules.NO_EFFECTS)
        if family == "daily":
            self.assertEqual(clean["revision"]["definition"], command["definition"])
            self.assertEqual(clean["revision"]["quantity_ids"], [quantity["id"] for quantity in clean["quantities"]])
            self.assertEqual(len(clean["quantities"]), len(command["quantities"]))
            for quantity, authored in zip(clean["quantities"], command["quantities"], strict=True):
                self.assertEqual(quantity["definition"], {
                    **authored, "sources": [self.expanded_source(source) for source in authored["sources"]],
                })
                self.assertEqual(field_repository.raw("quantity", quantity["id"]), quantity)
                self.assertEqual(field.get_record(self.company, self.project, "quantity", quantity["id"])["record"], quantity)
                self.assertEqual(quantity["source_revision"], clean["revision"]["id"])
                self.assertEqual(quantity["no_effects"], field_rules.NO_EFFECTS)
        else:
            self.assertEqual(clean["quantities"], [])
            self.assertEqual(clean["revision"]["definition"], {
                **command["definition"], "lines": [
                    {**line, "sources": [self.expanded_source(source) for source in line["sources"]]}
                    for line in command["definition"]["lines"]
                ],
            })
        captured = self.raw_capture(envelope)
        self.assertEqual(captured["envelope_digest"], digest(envelope))
        self.assertEqual(captured["commit_receipt"], {
            "operation_id": envelope["capture_id"], "request_hash": request_hash,
            "result_hash": digest(clean), "header_id": clean["header"]["id"], "revision_id": clean["revision"]["id"],
        })
        self.assertEqual(read_operation(self.company, self.project, envelope["capture_id"]), {
            **clean, "operation": {"id": envelope["capture_id"], "status": "succeeded", "replayed": True},
        })
        return clean

    def online_create(self):
        return field.create_record(self.company, self.project, str(uuid4()), "daily", self.daily_definition(), [], [self.quantity()])

    def online_revise(self, previous, value="12.625000", reason=""):
        command = self.revise_envelope(previous, value, reason)["command"]
        return field.revise_record(
            self.company, self.project, str(uuid4()), command["family"], command["record_id"],
            command["expected_version"], command["definition"], command["photos"], command["quantities"], command["amendment_reason"],
        )

    def transition(self, value, action):
        return field.transition(
            self.company, self.project, str(uuid4()), value["family"], value["header"]["id"],
            digest(value["header"]), action, "Synthetic independent documentary " + action, [], "",
        )

    def change_binding(self, key, **updates):
        previous = frappe.session.user
        self.login_administrator()
        try:
            name = frappe.db.get_value("Cipher Identity Binding", {"user": self.users[key]["user"]}, "name")
            with trusted_write():
                binding = frappe.get_doc("Cipher Identity Binding", name)
                binding.update(updates)
                binding.save(ignore_permissions=True)
        finally:
            frappe.set_user(previous)

    def change_duty(self, ability, active):
        previous = frappe.session.user
        self.login_administrator()
        try:
            set_synthetic_duty(self.users["owner"]["user"], self.project, ability, active)
        finally:
            frappe.set_user(previous)

    def photo(self):
        # A valid ancillary PNG text chunk makes bytes/filenames unique per case
        # and avoids Frappe deduplicating a fixture image onto an unrelated File.
        original = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        chunk = b"tEXt" + b"FLD02\x00" + self.marker.encode()
        content = original[:-12] + struct.pack(">I", len(chunk) - 4) + chunk + struct.pack(">I", zlib.crc32(chunk)) + original[-12:]
        uploaded, reference = self.upload(content, "png")
        document_control.set_rights(
            self.company, self.project, str(uuid4()), uploaded["document"]["id"], None, self.permission_definition(),
        )
        return {
            "source": self.locator(reference, "Exact retained original field photo"),
            "caption": "Synthetic retained installation image", "captured_at": "2026-10-17T09:15:00-04:00",
            "representation": "source_image",
        }

    def test_fld02_n01_canonical_person_owns_device_and_original_login_survives_alias_sync(self):
        self.assertEqual(current_actor().person_id, self.users["alias"]["person"])
        envelope = self.envelope()
        self.login("alias")
        self.assertEqual(current_actor().person_id, envelope["actor_person"])
        self.assertNotEqual(current_actor().user, envelope["actor_user"])
        forged = deepcopy(envelope)
        forged["actor_user"] = self.users["alias"]["user"]
        self.assert_error("field_capture_actor", lambda: self.stage(forged))
        staged = self.stage(envelope)
        self.assertEqual(staged["capture"]["actor_user"], self.users["owner"]["user"])
        applied = self.apply(envelope, staged)
        clean = self.assert_canonical_receipt(envelope, applied["original_receipt"])
        self.assertEqual(clean["revision"]["author_user"], self.users["alias"]["user"])
        self.assertEqual(clean["revision"]["author_person"], self.users["owner"]["person"])
        self.assertEqual(clean["revision"]["superintendent"], self.users["owner"])
        self.login("owner")
        original = offline.get_capture(self.company, self.project, envelope["capture_id"])
        self.assertEqual(original["envelope"], envelope)
        self.assertEqual(original["original_receipt"]["revision"], clean["revision"])
        self.login("outsider")
        self.assert_error("not_found", lambda: offline.get_capture(self.company, self.project, envelope["capture_id"]))
        self.login("reviewer")
        self.assert_error("not_found", lambda: offline.get_capture(self.company, self.project, envelope["capture_id"]))
        self.login("owner")
        self.assert_error("not_found", lambda: offline.get_capture(self.company, self.other_project, envelope["capture_id"]))

    def test_fld02_n02_revoked_device_refuses_staged_and_new_capture_without_field_effect(self):
        envelope = self.envelope()
        staged = self.stage(envelope)
        before = self.field_identity_snapshot()
        revoked = offline.revoke_device(
            self.company, self.project, str(uuid4()), self.device_id, self.registration["device_version"],
            "Explicitly retired this synthetic tablet.",
        )
        self.assertEqual(revoked["device"]["status"], "revoked")
        self.assert_error("field_device_revoked", lambda: offline.inspect_capture(self.company, self.project, envelope["capture_id"]))
        self.assert_error("field_device_revoked", lambda: self.apply(envelope, staged))
        self.assert_error("field_device_revoked", lambda: self.stage(self.envelope()))
        self.assertEqual(offline.get_capture(self.company, self.project, envelope["capture_id"])["envelope"], envelope)
        self.assertEqual(self.field_identity_snapshot(), before)
        self.assert_no_business_receipt(envelope["capture_id"])

    def test_fld02_n03_disabled_original_binding_fails_even_when_alias_is_enabled(self):
        envelope = self.envelope()
        staged = self.stage(envelope)
        original = self.raw_capture(envelope)
        self.change_binding("owner", active=0)
        self.assert_error("identity_unavailable", lambda: offline.get_capture(self.company, self.project, envelope["capture_id"]))
        self.login("alias")
        self.assert_error("identity_unavailable", lambda: offline.inspect_capture(self.company, self.project, envelope["capture_id"]))
        self.assert_error("identity_unavailable", lambda: self.apply(envelope, staged))
        self.assertEqual(self.raw_capture(envelope), original)
        self.assert_no_business_receipt(envelope["capture_id"])
        self.change_binding("owner", active=1)
        self.assert_canonical_receipt(envelope, self.apply(envelope, staged)["original_receipt"])

    def test_fld02_n04_reassigned_participant_binding_requires_explicit_new_identity_review(self):
        envelope = self.envelope()
        staged = self.stage(envelope)
        original = self.raw_capture(envelope)
        self.change_binding("owner", person=self.users["reviewer"]["person"])
        self.assert_error("not_found", lambda: offline.get_capture(self.company, self.project, envelope["capture_id"]))
        self.login("alias")
        self.assert_error("field_identity_changed", lambda: offline.inspect_capture(self.company, self.project, envelope["capture_id"]))
        self.assert_error("field_identity_changed", lambda: self.apply(envelope, staged))
        self.assertEqual(self.raw_capture(envelope), original)
        self.assert_no_business_receipt(envelope["capture_id"])
        self.change_binding("owner", person=self.users["owner"]["person"])
        self.assert_canonical_receipt(envelope, self.apply(envelope, staged)["original_receipt"])

    def test_fld02_n05_stage_inspect_apply_reconciles_exact_native_header_revision_quantity_and_photo(self):
        envelope = self.envelope(photos=[self.photo()])
        before = self.field_identity_snapshot()
        side_effects = self.side_effect_snapshot()
        staged = self.stage(envelope)
        capture = self.raw_capture(envelope)
        self.assertEqual(capture["envelope"], envelope)
        self.assertEqual(capture["envelope_digest"], digest(envelope))
        self.assertEqual(self.field_identity_snapshot(), before)
        self.assert_no_business_receipt(envelope["capture_id"])
        readback = offline.get_capture(self.company, self.project, envelope["capture_id"])
        self.assertEqual(readback["envelope"], envelope)
        self.assertIsNone(readback["original_receipt"])
        inspection = offline.inspect_capture(self.company, self.project, envelope["capture_id"])
        self.assertEqual(inspection["disposition"], "ready")
        self.assertIsNone(inspection["conflict"])
        self.assertEqual(inspection["capture_version"], staged["capture_version"])
        self.assert_error("stale_offline_capture", lambda: offline.apply_capture(
            self.company, self.project, envelope["capture_id"], envelope["capture_id"], "0" * 64,
        ))
        self.assertEqual(self.raw_capture(envelope), capture)
        self.assert_no_business_receipt(envelope["capture_id"])
        applied = self.apply(envelope, staged)
        self.assertFalse(applied["replayed"])
        clean = self.assert_canonical_receipt(envelope, applied["original_receipt"])
        self.assertEqual(clean["header"]["status"], "draft")
        self.assertEqual(clean["revision"]["photos"][0]["source"]["mime_type"], "image/png")
        self.assertEqual(clean["quantities"][0]["definition"]["quantity"], "12.375000")
        for source in (clean["quantities"][0]["definition"]["sources"][0], clean["revision"]["photos"][0]["source"]):
            content = self.uploads[source["revision_id"]]["bytes"]
            self.assertEqual(documents.download_revision(self.company, source["revision_id"])[1], content)
            self.assertEqual(source["source_sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(source["byte_length"], len(content))
        committed = self.raw_capture(envelope)
        event = offline_repository.raw("event", committed["last_event"])
        self.assertEqual((event["event_type"], event["prior_digest"], event["next_digest"]), ("committed", digest(capture), digest(committed)))
        self.assertEqual(self.side_effect_snapshot(), side_effects)

    def test_fld02_n06_current_ingest_rights_are_rechecked_after_stage_then_original_recovery_is_read_only(self):
        envelope = self.envelope()
        staged = self.stage(envelope)
        original = self.raw_capture(envelope)
        self.set_rights({**self.rights_definition, "ingest_allowed": False})
        self.assertEqual(offline.get_capture(self.company, self.project, envelope["capture_id"])["envelope"], envelope)
        self.assert_error("source_rights_denied", lambda: offline.inspect_capture(self.company, self.project, envelope["capture_id"]))
        self.assert_error("source_rights_denied", lambda: self.apply(envelope, staged))
        self.assertEqual(self.raw_capture(envelope), original)
        self.assert_no_business_receipt(envelope["capture_id"])
        self.set_rights(self.rights_definition)
        applied = self.apply(envelope, staged)
        clean = self.assert_canonical_receipt(envelope, applied["original_receipt"])
        self.set_rights({**self.rights_definition, "ingest_allowed": False})
        recovered = self.apply(envelope, staged)
        self.assertTrue(recovered["replayed"])
        self.assertEqual({key: value for key, value in recovered["original_receipt"].items() if key != "operation"}, clean)
        self.assert_canonical_receipt(envelope, recovered["original_receipt"])

    def test_fld02_n07_changed_source_head_is_an_explicit_conflict_and_preserves_original_bytes(self):
        envelope = self.envelope()
        staged = self.stage(envelope)
        original = self.raw_capture(envelope)
        changed_bytes = ("Later synthetic observed quantity source. " + self.marker).encode()
        uploaded, replacement = self.upload(changed_bytes, document_id=self.source_document, expected_revision=1)
        self.assertEqual(uploaded["revision"]["revision_number"], 2)
        self.assertNotEqual(replacement["source_sha256"], self.source["source_sha256"])
        inspection = offline.inspect_capture(self.company, self.project, envelope["capture_id"])
        self.assertEqual(inspection["disposition"], "conflict")
        self.assertEqual(inspection["conflict"], {
            "code": "source_changed", "current_header_version": None, "current_revision_id": None, "current_revision_digest": None,
        })
        error = self.assert_error("field_offline_conflict", lambda: self.apply(envelope, staged))
        self.assertEqual(error.details["conflict"], inspection["conflict"])
        self.assertEqual(self.raw_capture(envelope), original)
        self.assertEqual(documents.download_revision(self.company, self.source["revision_id"])[1], self.source_bytes)
        self.assert_no_business_receipt(envelope["capture_id"])
        self.assertTrue(all(not ids for ids in self.field_identity_snapshot().values()))

    def test_fld02_n08_duplicate_stage_and_same_operation_retry_keep_one_exact_immutable_capture(self):
        envelope, operation = self.envelope(), str(uuid4())
        first = self.stage(envelope, operation)
        raw = self.raw_capture(envelope)
        retry = self.stage(deepcopy(envelope), operation)
        self.assertTrue(retry["operation"]["replayed"])
        duplicate = self.stage(deepcopy(envelope))
        self.assertEqual(duplicate["capture"], first["capture"])
        self.assertEqual(duplicate["capture_version"], first["capture_version"])
        self.assertEqual(self.raw_capture(envelope), raw)
        changed = deepcopy(envelope)
        changed["command"]["definition"]["activities"] = ["Changed immutable capture wording."]
        self.assert_error("operation_conflict", lambda: self.stage(changed, operation))
        self.assert_error("field_capture_conflict", lambda: self.stage(changed))
        self.assertEqual(self.raw_capture(envelope), raw)
        self.assertEqual(frappe.get_all("Cipher Field Offline Capture", filters={"project": self.project}, pluck="name"), [raw["id"]])
        self.assert_no_business_receipt(envelope["capture_id"])

    def test_fld02_n09_original_uuid_recovery_and_direct_field_retry_return_one_exact_committed_result(self):
        envelope = self.envelope()
        staged = self.stage(envelope)
        applied = self.apply(envelope, staged)
        original = self.assert_canonical_receipt(envelope, applied["original_receipt"])
        identities = self.field_identity_snapshot()
        raw = self.raw_capture(envelope)
        recovered = self.apply(envelope, staged)  # Original staged token is intentionally stale.
        self.assertTrue(recovered["replayed"])
        command = envelope["command"]
        direct_retry = field.create_record(
            self.company, self.project, envelope["capture_id"], command["family"], command["definition"], command["photos"], command["quantities"],
        )
        self.assertTrue(direct_retry["operation"]["replayed"])
        for result in (recovered["original_receipt"], direct_retry):
            self.assertEqual({key: value for key, value in result.items() if key != "operation"}, original)
            self.assert_canonical_receipt(envelope, result)
        self.assertEqual(self.raw_capture(envelope), raw)
        self.assertEqual(self.field_identity_snapshot(), identities)
        self.assertEqual(identities["daily"], [original["header"]["id"]])
        self.assertEqual(identities["daily_revision"], [original["revision"]["id"]])
        self.assertEqual(identities["quantity"], sorted(original["revision"]["quantity_ids"]))

    def test_fld02_n10_shared_person_operation_collision_cannot_become_another_field_command(self):
        envelope = self.envelope()
        collision = offline.register_device(
            self.company, self.project, envelope["capture_id"], str(uuid4()), "Independent colliding registration UUID",
        )
        staged = self.stage(envelope)
        self.assert_error("operation_conflict", lambda: offline.inspect_capture(self.company, self.project, envelope["capture_id"]))
        self.assert_error("operation_conflict", lambda: self.apply(envelope, staged))
        self.assert_error("operation_conflict", lambda: offline.apply_capture(
            self.company, self.project, str(uuid4()), envelope["capture_id"], staged["capture_version"],
        ))
        other = self.envelope()
        self.assert_error("field_capture_operation_reserved", lambda: self.stage(other, other["capture_id"]))
        retained = read_operation(self.company, self.project, envelope["capture_id"])
        self.assertEqual(retained["device"], collision["device"])
        self.assertEqual(retained["device_version"], collision["device_version"])
        self.assertTrue(all(not ids for ids in self.field_identity_snapshot().values()))

    def test_fld02_n11_native_controllers_and_repository_cannot_rewrite_or_delete_capture_envelope(self):
        envelope = self.envelope()
        self.stage(envelope)
        original = self.raw_capture(envelope)
        doctype = offline_repository.KINDS["capture"]
        native = frappe.get_doc(doctype, original["id"])
        self.assertFalse(frappe.has_permission(doctype, "read", doc=native, user=frappe.session.user))
        # The ordinary Cipher User is denied at the native DocType gate before
        # the stricter private query condition could expose any row.
        with self.assertRaises(frappe.PermissionError):
            frappe.get_list(doctype, filters={"project": self.project}, fields=["name"])
        self.assert_error("governed_write_required", lambda: native.save(ignore_permissions=True))
        with trusted_write():
            fresh = frappe.get_doc(doctype, original["id"])
            self.assert_error("field_offline_command_required", lambda: fresh.save(ignore_permissions=True))
            self.assert_error("field_offline_command_required", lambda: offline_repository.write("capture", original, old=original))
        # A semantically valid changed envelope plus changed public digest still
        # cannot acquire the service's private operation/write admission.
        forged = deepcopy(original)
        forged["envelope"]["captured_at"] = "2026-10-17T09:16:00-04:00"
        forged["envelope_digest"] = digest(forged["envelope"])
        with trusted_write():
            self.assert_error("field_offline_command_required", lambda: offline_repository.write("capture", forged, old=original))
        self.assert_error("field_offline_command_required", lambda: frappe.delete_doc(doctype, original["id"], ignore_permissions=True))
        self.assertEqual(self.raw_capture(envelope), original)
        self.assert_no_business_receipt(envelope["capture_id"])

    def test_fld02_n12_base_conflict_requires_linked_fresh_uuid_and_exact_current_quantity_predecessor(self):
        first = self.online_create()
        envelope = self.revise_envelope(first)
        staged = self.stage(envelope)
        original = self.raw_capture(envelope)
        current = self.online_revise(first)
        inspection = offline.inspect_capture(self.company, self.project, envelope["capture_id"])
        self.assertEqual(inspection["disposition"], "conflict")
        self.assertEqual(inspection["conflict"], {
            "code": "base_changed", "current_header_version": digest(current["header"]),
            "current_revision_id": current["revision"]["id"], "current_revision_digest": digest(current["revision"]),
        })
        self.assert_error("field_offline_conflict", lambda: self.apply(envelope, staged))
        self.assert_no_business_receipt(envelope["capture_id"])
        replacement = self.revise_envelope(current, "12.750000")
        resolved = offline.resolve_capture(
            self.company, self.project, str(uuid4()), envelope["capture_id"], staged["capture_version"], replacement,
            "Human selected the exact current base and immediate quantity predecessor.",
        )
        superseded = self.raw_capture(envelope)
        new = self.raw_capture(replacement)
        self.assertEqual(superseded["status"], "superseded")
        self.assertEqual(superseded["envelope"], envelope)
        self.assertEqual(superseded["replacement_capture_id"], replacement["capture_id"])
        self.assertEqual(new["replaces_capture_id"], envelope["capture_id"])
        event = offline_repository.raw("event", superseded["last_event"])
        self.assertEqual((event["prior_digest"], event["next_digest"], event["related_capture_id"]), (digest(original), digest(superseded), replacement["capture_id"]))
        self.assert_error("field_capture_closed", lambda: self.apply(envelope, {"capture_version": digest(superseded)}))
        result = self.apply(replacement, resolved)["original_receipt"]
        self.assert_canonical_receipt(replacement, result)
        self.assertEqual(result["revision"]["predecessor"], current["revision"]["id"])
        self.assertEqual(result["quantities"][0]["supersedes_event_id"], current["quantities"][0]["id"])
        for old in (first, current):
            self.assertEqual(field_repository.raw("daily_revision", old["revision"]["id"]), old["revision"])
            self.assertEqual(field_repository.raw("quantity", old["quantities"][0]["id"]), old["quantities"][0])

    def test_fld02_n13_discard_with_revoked_source_read_rights_redacts_payload_and_preserves_event(self):
        envelope = self.envelope()
        staged = self.stage(envelope)
        original = self.raw_capture(envelope)
        self.set_rights({**self.rights_definition, "ingest_allowed": False, "read_allowed": False})
        self.assert_error("source_rights_denied", lambda: offline.get_capture(self.company, self.project, envelope["capture_id"]))
        self.assert_error("source_rights_denied", lambda: offline.inspect_capture(self.company, self.project, envelope["capture_id"]))
        discarded = offline.discard_capture(
            self.company, self.project, str(uuid4()), envelope["capture_id"], staged["capture_version"],
            "Explicit privacy cleanup of unsynchronized local evidence.",
        )
        self.assertEqual(discarded["capture"]["status"], "discarded")
        self.assertFalse(discarded["capture"]["payload_retained"])
        raw = self.raw_capture(envelope)
        self.assertIsNone(raw["envelope"])
        self.assertEqual(raw["envelope_digest"], original["envelope_digest"])
        self.assertIsNone(raw["commit_receipt"])
        event = offline_repository.raw("event", raw["last_event"])
        self.assertEqual((event["event_type"], event["prior_digest"], event["next_digest"]), ("discarded", digest(original), digest(raw)))
        safe = offline.get_capture(self.company, self.project, envelope["capture_id"])
        self.assertIsNone(safe["envelope"])
        self.assertIsNone(safe["original_receipt"])
        self.assert_error("field_capture_closed", lambda: self.apply(envelope, discarded))
        self.assert_no_business_receipt(envelope["capture_id"])
        self.assertTrue(all(not ids for ids in self.field_identity_snapshot().values()))

    def test_fld02_n14_recover_original_after_real_acceptance_amendment_redaction_and_write_revocation(self):
        envelope = self.envelope(photos=[self.photo()])
        staged = self.stage(envelope)
        applied = self.apply(envelope, staged)
        original = self.assert_canonical_receipt(envelope, applied["original_receipt"])
        submitted = self.transition(applied["original_receipt"], "submit")
        self.login("alias")
        self.assert_error("independent_field_review_required", lambda: self.transition(submitted, "review"))
        self.login("reviewer")
        reviewed = self.transition(submitted, "review")
        accepted = self.transition(reviewed, "accept")
        acceptance = deepcopy(accepted["decision"])
        self.login("owner")
        amended = self.online_revise({**accepted, "quantities": original["quantities"]}, "13.000001", "Independent later observation corrects the accepted installed length.")
        self.assertEqual(amended["revision"]["amendment_of"], original["revision"]["id"])
        self.assertEqual(amended["revision"]["prior_decision"], acceptance["id"])
        self.assertEqual(amended["header"]["accepted_revision"], original["revision"]["id"])
        self.assertNotEqual(amended["header"], original["header"])
        self.assertEqual(field_repository.raw("decision", acceptance["id"]), acceptance)
        current_capture = self.raw_capture(envelope)
        redacted = offline.discard_capture(
            self.company, self.project, str(uuid4()), envelope["capture_id"], digest(current_capture),
            "Remove the retained capture payload after authoritative Field persistence.",
        )
        self.assertEqual(redacted["capture"]["status"], "committed")
        self.assertFalse(redacted["capture"]["payload_retained"])
        offline.revoke_device(
            self.company, self.project, str(uuid4()), self.device_id, self.registration["device_version"], "Retired after successful synchronization.",
        )
        self.change_duty("field.write", 0)
        self.set_rights({**self.rights_definition, "ingest_allowed": False})
        recovered = self.apply(envelope, staged)
        self.assertTrue(recovered["replayed"])
        readback = offline.get_capture(self.company, self.project, envelope["capture_id"])
        self.assertIsNone(readback["envelope"])
        inspected = offline.inspect_capture(self.company, self.project, envelope["capture_id"])
        self.assertEqual(inspected["disposition"], "committed")
        for receipt in (recovered["original_receipt"], readback["original_receipt"], inspected["original_receipt"]):
            self.assertEqual({key: value for key, value in receipt.items() if key != "operation"}, original)
            self.assert_canonical_receipt(envelope, receipt, current_header=False)
        self.assertEqual(field_repository.raw("daily", amended["header"]["id"]), amended["header"])
        self.assertEqual(field_repository.raw("daily_revision", amended["revision"]["id"]), amended["revision"])
        self.assertEqual(field_repository.raw("quantity", amended["quantities"][0]["id"]), amended["quantities"][0])
        retained = self.raw_capture(envelope)
        self.assertEqual(retained["commit_receipt"], current_capture["commit_receipt"])
        event = offline_repository.raw("event", retained["last_event"])
        self.assertEqual((event["event_type"], event["prior_digest"], event["next_digest"]), ("redacted", digest(current_capture), digest(retained)))

    def test_fld02_n15_current_read_duties_and_source_rights_gate_every_historical_receipt_read(self):
        envelope = self.envelope()
        staged = self.stage(envelope)
        original = self.apply(envelope, staged)["original_receipt"]
        self.assert_canonical_receipt(envelope, original)
        native_original = self.raw_capture(envelope)
        reads = (
            lambda: offline.get_capture(self.company, self.project, envelope["capture_id"]),
            lambda: offline.inspect_capture(self.company, self.project, envelope["capture_id"]),
            lambda: self.apply(envelope, staged),
            lambda: read_operation(self.company, self.project, envelope["capture_id"]),
        )
        for ability in ("field.read", "document.read"):
            self.change_duty(ability, 0)
            try:
                for callback in reads:
                    with self.subTest(ability=ability), self.assertRaises(DomainError):
                        callback()
            finally:
                self.change_duty(ability, 1)
            self.assert_canonical_receipt(envelope, original)
        self.set_rights({**self.rights_definition, "ingest_allowed": False, "read_allowed": False})
        for callback in reads:
            self.assert_error("source_rights_denied", callback)
        self.assertEqual(self.raw_capture(envelope), native_original)
        self.assertEqual(field_repository.raw("daily_revision", original["revision"]["id"]), original["revision"])
        self.assertEqual(field_repository.raw("quantity", original["quantities"][0]["id"]), original["quantities"][0])

    def test_fld02_n16_quantity_lineage_keeps_exact_decimal_strings_and_source_byte_hashes(self):
        envelope = self.envelope(quantities=[self.quantity("999999999999.123456")])
        first = self.apply(envelope, self.stage(envelope))["original_receipt"]
        self.assert_canonical_receipt(envelope, first)
        correction = self.revise_envelope(first, "0.000001")
        second = self.apply(correction, self.stage(correction))["original_receipt"]
        self.assert_canonical_receipt(correction, second)
        prior, successor = first["quantities"][0], second["quantities"][0]
        self.assertEqual(prior["definition"]["quantity"], "999999999999.123456")
        self.assertEqual(successor["definition"]["quantity"], "0.000001")
        self.assertEqual(Decimal(successor["definition"]["quantity"]), Decimal("0.000001"))
        self.assertEqual(successor["original_event_id"], prior["original_event_id"])
        self.assertEqual(successor["supersedes_event_id"], prior["id"])
        self.assertEqual(successor["definition"]["sources"], prior["definition"]["sources"])
        self.assertEqual(successor["definition"]["sources"][0]["source_sha256"], hashlib.sha256(self.source_bytes).hexdigest())
        self.assertEqual(documents.download_revision(self.company, self.source["revision_id"])[1], self.source_bytes)
        duplicate = self.envelope(quantities=[self.quantity("1.000000", prior["original_event_id"])])
        staged = self.stage(duplicate)
        before = self.field_identity_snapshot()
        raw = self.raw_capture(duplicate)
        self.assert_error("field_quantity_duplicate", lambda: self.apply(duplicate, staged))
        self.assertEqual(self.field_identity_snapshot(), before)
        self.assertEqual(self.raw_capture(duplicate), raw)
        self.assert_no_business_receipt(duplicate["capture_id"])
        self.assertEqual(field_repository.raw("daily_revision", first["revision"]["id"]), first["revision"])
        self.assertEqual(field_repository.raw("quantity", prior["id"]), prior)
        self.assertEqual(field_repository.raw("quantity", successor["id"]), successor)

    def side_effect_snapshot(self):
        # Bound read-only snapshots detect new rows and ordinary native updates
        # to existing finance/integration records without granting test actors
        # any corresponding command or finance permission.
        global_state = {}
        for doctype in (
            "Sales Order", "Sales Invoice", "Purchase Order", "Purchase Invoice", "Journal Entry", "GL Entry",
            "Stock Ledger Entry", "Payment Entry", "Cipher Integration Operation",
        ):
            rows = frappe.get_all(doctype, fields=["name", "modified", "docstatus"], order_by="name", limit_page_length=5001)
            self.assertLessEqual(len(rows), 5000, "Use a bounded isolated synthetic native site.")
            global_state[doctype] = digest([
                {"name": row.name, "modified": str(row.modified), "docstatus": row.docstatus} for row in rows
            ])
        tasks = frappe.get_all("Task", filters={"project": self.project}, fields=["name", "subject", "status", "modified"], order_by="name")
        self.assertEqual(tasks, [], "Each case starts with a fresh Task-free Project.")
        return {"global": global_state, "tasks": tasks, "project": deepcopy(frappe.get_doc("Project", self.project).as_dict())}

    def test_fld02_n17_tm_ticket_exact_documentary_lines_apply_once_without_task_or_financial_effects(self):
        before = self.side_effect_snapshot()
        envelope = self.envelope(family="ticket")
        staged = self.stage(envelope)
        applied = self.apply(envelope, staged)
        original = self.assert_canonical_receipt(envelope, applied["original_receipt"])
        self.assertEqual(original["revision"]["definition"]["lines"][0]["quantity"], "3.250000")
        self.assertEqual(original["quantities"], [])
        self.assertTrue(all(value is False for value in original["revision"]["no_effects"].values()))
        repeated = self.apply(envelope, staged)
        self.assertTrue(repeated["replayed"])
        self.assert_canonical_receipt(envelope, repeated["original_receipt"])
        identities = self.field_identity_snapshot()
        self.assertEqual(identities["ticket"], [original["header"]["id"]])
        self.assertEqual(identities["ticket_revision"], [original["revision"]["id"]])
        self.assertEqual(identities["daily"], [])
        self.assertEqual(identities["daily_revision"], [])
        self.assertEqual(identities["quantity"], [])
        self.assertEqual(identities["decision"], [])
        self.assertEqual(self.side_effect_snapshot(), before)
        self.assertEqual(frappe.db.get_value("Project", self.project, "status"), "Open")

    def test_fld02_n18_explicit_case_rollback_removes_own_rows_files_and_preserves_unrelated_file(self):
        sentinel_bytes = ("Synthetic sentinel outside the nested rollback scope. " + self.marker).encode()
        sentinel, _ = self.upload(sentinel_bytes)
        sentinel_attempt = self.uploads[sentinel["revision"]["id"]]["attempt"]
        sentinel_path = sentinel_attempt["files"][0]["path"]
        sentinel_file = sentinel_attempt["files"][0]["name"]
        nested = "fld02_owned_" + uuid4().hex
        frappe.db.savepoint(nested)
        temporary, _ = self.upload(("Exact temporary rollback-owned upload. " + self.marker).encode())
        temporary_attempt = self.uploads[temporary["revision"]["id"]]["attempt"]
        temporary_paths = [entry["path"] for entry in temporary_attempt["files"]]
        temporary_file = temporary_attempt["files"][0]["name"]
        envelope = self.envelope()
        staged = self.stage(envelope)
        result = self.apply(envelope, staged)["original_receipt"]
        self.assert_canonical_receipt(envelope, result)
        capture = self.raw_capture(envelope)
        self.assertTrue(all(path.is_file() for path in temporary_paths))
        frappe.db.rollback(save_point=nested)
        for doctype, name in (
            ("Cipher Field Offline Capture", capture["id"]), ("Cipher Field Offline Event", capture["last_event"]),
            ("Cipher Field Daily Report", result["header"]["id"]), ("Cipher Field Daily Revision", result["revision"]["id"]),
            ("Cipher Field Quantity Event", result["quantities"][0]["id"]),
            ("Cipher Document Revision", temporary["revision"]["id"]), ("File", temporary_file),
        ):
            self.assertFalse(frappe.db.exists(doctype, name))
        self.assert_no_business_receipt(envelope["capture_id"])
        self.cleanup_upload_files([temporary_attempt])
        self.assertTrue(all(not path.exists() for path in temporary_paths))
        self.assertTrue(frappe.db.exists("File", sentinel_file))
        self.assertTrue(sentinel_path.is_file())
        self.assertEqual(sentinel_path.read_bytes(), sentinel_bytes)
        self.assertEqual(documents.download_revision(self.company, sentinel["revision"]["id"])[1], sentinel_bytes)
