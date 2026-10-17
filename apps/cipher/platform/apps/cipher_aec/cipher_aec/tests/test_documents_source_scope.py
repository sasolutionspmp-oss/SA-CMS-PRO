"""One Company canonical reader, fresh row/producer authority and real bytes.

Explicit in-process repository/producer fixtures; no live provider/HTTP claim.
"""
import copy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from cipher_aec.api.errors import DomainError
from cipher_aec.documents import provenance
from cipher_aec.documents.core import DocumentService
from cipher_aec.documents.extraction import ArtifactError, digest
from cipher_aec.documents.repository import FrappeDocumentRepository
from cipher_aec.documents.storage import LocalArtifactStorage
from cipher_aec.tests.test_documents import MemoryMetadata
from cipher_aec.tests.test_documents_provenance import ACTOR, document as generated_document


class CanonicalCompanySourceScope(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo, self.calls, self.allowed = MemoryMetadata(), [], True
        self.storage = LocalArtifactStorage(self.directory.name)
        self.company = DocumentService(self.repo, self.storage, self.authorize, scope_type="Company", allow_unscanned=True)
        self.project = DocumentService(self.repo, self.storage, self.authorize, allow_unscanned=True)
        result = self.upload(self.company)
        self.did, self.rid = result["document"]["id"], result["revision"]["id"]
        self.calls.clear()

    def authorize(self, company, project, ability):
        self.calls.append((company, project, ability))
        if not self.allowed or company != "Company A" or project not in (None, "P"):
            raise PermissionError("Fresh exact Company capability denied")

    def upload(self, service, **changes):
        content = changes.pop("content", b"Exact source fixture quantities.\fRetained second page.")
        values = dict(company="Company A", project=None if service is self.company else "P", title="Source",
            filename="source.txt", content=content, byte_length=len(content), sha256=digest(content))
        values.update(changes)
        return service.upload(**values)

    def readers(self, rid=None, *, lock=False):
        rid = rid or self.rid
        return (lambda: self.company.citation("Company A", rid, 1, lock=lock),
                lambda: self.company.source_reference("Company A", None, rid, 1, lock=lock))

    def generated(self):
        fields = generated_document(self.did)
        self.repo.docs[self.did].update(fields)
        self.repo.revs[self.rid].update({key: fields[key] for key in
            ("producer_kind", "producer_reference", "producer_input_digest", "producer_binding_json")})
        self.company.source_authorize = lambda row, lock=False: provenance.authorize(row, ACTOR, lock=lock)

    def producer_adapter(self, authorize):
        return patch.dict(sys.modules, {"cipher_aec.commercial.output_sources": types.SimpleNamespace(
            authorize_binding=authorize, binding_plan=lambda value, actor, lock=False: {})})

    def test_one_fresh_company_guard_per_citation_or_source_read(self):
        for read in self.readers():
            with self.subTest(read=read):
                self.calls.clear()
                read()
                self.assertEqual(self.calls, [("Company A", None, "document.read")])

    def test_later_reader_rechecks_revocation_and_never_loads_long_text_or_bytes(self):
        for read in self.readers():
            self.allowed = True
            read()
            self.allowed = False
            with patch.object(self.repo, "revision", wraps=self.repo.revision) as revision, patch.object(self.storage, "read", wraps=self.storage.read) as content:
                with self.assertRaises(PermissionError):
                    read()
                revision.assert_not_called()
                content.assert_not_called()

    def test_a_different_actor_bound_service_cannot_reuse_previous_company_authority(self):
        self.company.citation("Company A", self.rid, 1)
        def other_actor(company, project, ability):
            raise PermissionError("The second actor has no Company document duty")
        denied = DocumentService(self.repo, self.storage, other_actor, scope_type="Company", allow_unscanned=True)
        for read in (lambda: denied.citation("Company A", self.rid, 1),
                     lambda: denied.source_reference("Company A", None, self.rid, 1)):
            with patch.object(self.repo, "revision", wraps=self.repo.revision) as revision, patch.object(self.storage, "read", wraps=self.storage.read) as content:
                with self.assertRaises(PermissionError):
                    read()
                revision.assert_not_called()
                content.assert_not_called()

    def test_later_call_rechecks_original_producer_rights_before_long_text(self):
        self.generated()
        allowed = True
        def authorize(*args, **kwargs):
            if not allowed:
                raise DomainError("not_found", "Original producer sources revoked", 404)
        with patch.object(FrappeDocumentRepository, "document", side_effect=self.repo.document), self.producer_adapter(authorize):
            for read in self.readers():
                allowed = True
                read()
                allowed = False
                with patch.object(self.repo, "revision", wraps=self.repo.revision) as revision, patch.object(self.storage, "read", wraps=self.storage.read) as content:
                    with self.assertRaises(DomainError):
                        read()
                    revision.assert_not_called()
                    content.assert_not_called()

    def test_parent_producer_denial_precedes_full_revision_and_bytes_on_every_reader(self):
        self.generated()
        def denied(*args, **kwargs):
            raise DomainError("not_found", "Original producer sources denied", 404)
        with patch.object(FrappeDocumentRepository, "document", side_effect=self.repo.document), self.producer_adapter(denied):
            for read in self.readers():
                with patch.object(self.repo, "revision", wraps=self.repo.revision) as revision, patch.object(self.storage, "read", wraps=self.storage.read) as content:
                    with self.assertRaises(DomainError):
                        read()
                    revision.assert_not_called()
                    content.assert_not_called()

    def test_generated_binding_digest_denial_precedes_full_revision(self):
        self.generated()
        self.repo.docs[self.did]["producer_input_digest"] = "0" * 64
        with patch.object(FrappeDocumentRepository, "document", side_effect=self.repo.document):
            for read in self.readers():
                with patch.object(self.repo, "revision", wraps=self.repo.revision) as revision, patch.object(self.storage, "read", wraps=self.storage.read) as content:
                    with self.assertRaises(DomainError) as error:
                        read()
                    self.assertEqual(error.exception.code, "source_integrity")
                    revision.assert_not_called()
                    content.assert_not_called()

    def test_parent_and_revision_producer_checks_both_run_and_preserve_lock_mode(self):
        self.generated()
        nodes = {"generated_sources": [{"document_id": self.did, "input_digest": self.repo.docs[self.did]["producer_input_digest"]}]}
        callback = self.company.source_authorize
        for read in self.readers(lock=True):
            order = []
            original_revision, original_document = self.repo.revision, self.repo.document
            def producer(row, lock=False):
                order.append(("producer-revision" if row.get("document") else "producer-parent", lock))
                return callback(row, lock=lock)
            def parent(name, lock=False):
                order.append(("parent-row", lock))
                return original_document(name, lock=lock)
            def revision(name, lock=False):
                order.append(("revision-long-text", lock))
                return original_revision(name, lock=lock)
            with patch.object(FrappeDocumentRepository, "document", side_effect=original_document), self.producer_adapter(lambda *args, **kwargs: None), provenance.prelocked(nodes, ACTOR, "Company A"), patch.object(self.company, "source_authorize", producer), patch.object(self.repo, "document", side_effect=parent), patch.object(self.repo, "revision", side_effect=revision):
                read()
            self.assertEqual(order, [("parent-row", True), ("producer-parent", True), ("revision-long-text", True), ("producer-revision", True)])

    def test_every_locator_parent_and_revision_scope_is_checked(self):
        for method in ("revision_locator", "document", "revision"):
            for change in ({"company": "Other"}, {"project": "P"}, {"scope_type": "Project", "project": "P"}):
                original = getattr(self.repo, method)
                def changed(*args, **kwargs):
                    return {**original(*args, **kwargs), **change}
                for read in self.readers():
                    with self.subTest(method=method, change=change), patch.object(self.repo, method, side_effect=changed), patch.object(self.storage, "read", wraps=self.storage.read) as content:
                        with self.assertRaisesRegex(ArtifactError, "outside the requested scope"):
                            read()
                        content.assert_not_called()

    def test_every_requested_identity_and_parent_mapping_is_checked(self):
        for method, change in (("revision_locator", {"name": "other-revision"}), ("document", {"name": "other-parent"}),
                               ("revision", {"name": "other-revision"}), ("revision", {"document": "other-parent"})):
            original = getattr(self.repo, method)
            for read in self.readers():
                with self.subTest(method=method, change=change), patch.object(self.repo, method, side_effect=lambda *a, **kw: {**original(*a, **kw), **change}), patch.object(self.storage, "read", wraps=self.storage.read) as content:
                    with self.assertRaisesRegex(ArtifactError, "mapping is invalid"):
                        read()
                    content.assert_not_called()
        with self.assertRaisesRegex(ArtifactError, "outside the requested scope"):
            self.company.source_reference("Company A", "P", self.rid, 1)

    def test_each_revision_producer_field_must_match_authorized_parent(self):
        self.generated()
        for field in ("producer_kind", "producer_reference", "producer_input_digest", "producer_binding_json"):
            original = copy.deepcopy(self.repo.revs[self.rid])
            self.repo.revs[self.rid][field] = "altered"
            for read in self.readers():
                with self.subTest(field=field), patch.object(FrappeDocumentRepository, "document", side_effect=self.repo.document), self.producer_adapter(lambda *a, **kw: None), patch.object(self.storage, "read", wraps=self.storage.read) as content:
                    with self.assertRaisesRegex(ArtifactError, "producer integrity"):
                        read()
                    content.assert_not_called()
            self.repo.revs[self.rid] = original

    def test_retained_heads_citations_quarantine_and_real_byte_integrity_remain_fresh(self):
        citation = self.company.citation("Company A", self.rid, 1)
        successor = self.upload(self.company, content=b"A new working head.", document_id=self.did, expected_revision=1)
        self.assertEqual(self.company.citation("Company A", self.rid, 1), citation)
        self.assertFalse(self.company.source_reference("Company A", None, self.rid, 1)["is_current"])
        self.assertTrue(self.company.source_reference("Company A", None, successor["revision"]["id"], 1)["is_current"])
        self.repo.revs[self.rid]["retrieval_status"] = "quarantined"
        for read in self.readers():
            with self.assertRaisesRegex(ArtifactError, "quarantined"):
                read()
        self.repo.revs[self.rid]["retrieval_status"] = "available"
        (Path(self.directory.name) / self.rid).write_bytes(b"altered source")
        for read in self.readers():
            with self.assertRaisesRegex(ArtifactError, "integrity"):
                read()

    def test_project_and_direct_revision_paths_retain_existing_guards(self):
        made = self.upload(self.project)
        rid = made["revision"]["id"]
        for read, expected in ((lambda: self.project.citation("Company A", rid, 1), 2),
                               (lambda: self.project.source_reference("Company A", "P", rid, 1), 3),
                               (lambda: self.company.revision("Company A", self.rid), 1)):
            self.calls.clear()
            read()
            self.assertEqual(len(self.calls), expected)


if __name__ == "__main__":
    unittest.main()
