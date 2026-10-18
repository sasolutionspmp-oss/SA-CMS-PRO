"""Host regression: private-source admission precedes DOC04 metadata reads.

Uses the actual SourceAdapter, privacy.authorize_source and canonical document
core. Identity/persistence/provider doubles remain explicit; no native runtime
or embedding/vector connection is exercised.
"""
from copy import deepcopy
import unittest
from unittest.mock import patch
from uuid import uuid4

from cipher_aec.api.errors import DomainError
from cipher_aec.documents.core import DocumentService
from cipher_aec.semantic_index.service import SemanticService
from cipher_aec.tests import test_semantic_source as source_tests
from cipher_aec.tests import test_semantic_index_service as service_tests
from cipher_aec.tests import test_incident_privacy_fixture as privacy_tests


class SemanticIncidentPrivacyTests(unittest.TestCase):
    def setUp(self):
        # Compose with existing real DOC02 bytes and DOC03 source/rights checks.
        # Keep the helper TestCase inside this object, so discovery cannot run
        # an imported TestCase class a second time.
        self.case = source_tests.SemanticSourceTests(
            'test_snapshot_returns_exact_canonical_pages_without_original_bytes')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.native_privacy = self.case.s.incident_privacy
        self.privacy = self.native_privacy.privacy
        case, privacy = self.case, self.privacy

        def guarded_bound(kind, actor):
            # Exact Project branch of production provenance.authorize: incident
            # admission followed by current DOC03 read rights, before bytes.
            def authorize_source(row, lock=False):
                privacy.authorize_source(row, actor, lock=lock)
                case.rights.authorize(row, actor, lock=lock)
            return DocumentService(case.repo, case.storage,
                lambda company, project, ability: case.scopes.require(
                    company, kind, project, actor, ability),
                source_authorize=authorize_source, scope_type=kind,
                allow_unscanned=case.allow_unscanned)

        self.enterContext(patch.object(case, 'bound', guarded_bound))

    def select_private(self, variant):
        case = self.case
        content = (b'\f'.join([b'Restricted synthetic source page.'] * 129)
                   if variant == 'oversize' else b'Restricted synthetic source.')
        ref = case.upload(content)
        case.grant(ref)
        selector = case.select(ref)
        self.native_privacy.add_registration(privacy_tests.registration_value(selector['document_id']))
        self.native_privacy.revisions[selector['revision_id']] = {
            'document': selector['document_id'], 'company': 'C', 'project': 'P', 'scope_type': 'Project'}
        if variant == 'ocr':
            case.repo.revs[ref['revision_id']]['extraction_status'] = 'ocr_unavailable'
        return selector

    def backend(self):
        store, embedder, index = (service_tests.MemoryStore(),
                                  service_tests.Embedder(), service_tests.Index())
        return SemanticService(store, self.case.adapter, embedder, index), store, embedder, index

    def test_ordinary_manager_cannot_probe_private_metadata_or_provider_inputs(self):
        case = self.case
        case.s.duties[case.s.actor.person_id].discard('safety.incident.read')
        for variant in ('normal', 'oversize', 'ocr'):
            with self.subTest(variant=variant):
                selector = self.select_private(variant)
                backend, store, embedder, index = self.backend()
                with patch.object(case.adapter, '_revision_metadata',
                                  wraps=case.adapter._revision_metadata) as metadata, \
                     patch.object(case.storage, 'read', wraps=case.storage.read) as storage:
                    with self.assertRaises(DomainError) as denied:
                        backend.prepare(case.scope, [selector], str(uuid4()), case.s.actor)
                    self.assertEqual(denied.exception.code, 'capability_denied')
                    self.assertEqual(denied.exception.status, 403)
                    metadata.assert_not_called()
                    storage.assert_not_called()
                    self.assertEqual(embedder.calls, [])
                    self.assertEqual(index.upserts, [])
                    self.assertEqual(store.rows, {})

    def test_authorized_explicit_ingestion_keeps_canonical_prepare_and_run(self):
        case = self.case
        case.s.duties[case.s.actor.person_id].add('safety.incident.read')
        self.native_privacy.grant(case.s.actor, 'C', 'P')
        selector = self.select_private('normal')
        backend, store, embedder, index = self.backend()
        operation = str(uuid4())
        prepared = backend.prepare(case.scope, [selector], operation, case.s.actor)
        self.assertEqual(prepared['status'], 'pending')
        active = backend.run(case.scope, operation, case.s.actor)
        self.assertEqual(active['status'], 'active')
        self.assertTrue(embedder.calls)
        self.assertTrue(index.upserts)
        self.assertTrue(store.rows)
        self.assertEqual(embedder.calls[0], ['Restricted synthetic source.'])


    def ready_private(self):
        case = self.case
        self.native_privacy.grant(case.s.actor, 'C', 'P')
        selector = self.select_private('normal')
        backend, store, embedder, index = self.backend()
        operation = str(uuid4())
        backend.prepare(case.scope, [selector], operation, case.s.actor)
        backend.run(case.scope, operation, case.s.actor)
        return backend, store, embedder, index, operation

    def test_status_reauthorizes_revoked_owner_and_other_reader_before_counts(self):
        case = self.case
        backend, store, embedder, index, operation = self.ready_private()
        self.assertEqual(backend.status(case.scope, operation, case.s.actor)['chunks'], 1)
        owner = case.s.actor
        other = source_tests.person(case.s, case.rules, 'ordinary-status-reader')
        self.native_privacy.grants.clear()
        before, calls = deepcopy(store.rows), deepcopy(embedder.calls)
        for actor in (owner, other):
            with self.subTest(actor=actor.user), patch.object(case.adapter, '_revision_metadata',
                    wraps=case.adapter._revision_metadata) as metadata, patch.object(
                    case.storage, 'read', wraps=case.storage.read) as storage:
                with self.assertRaises(DomainError) as denied:
                    backend.status(case.scope, operation, actor)
                self.assertEqual(denied.exception.code, 'capability_denied')
                metadata.assert_not_called()
                storage.assert_not_called()
        self.assertEqual(store.rows, before)
        self.assertEqual(embedder.calls, calls)
        self.native_privacy.grant(other, 'C', 'P')
        allowed = backend.status(case.scope, operation, other)
        self.assertEqual((allowed['status'], allowed['chunks'], allowed['indexed_chunks']),
                         ('active', 1, 1))

    def test_other_manager_cancel_requires_current_private_read_before_mutation(self):
        case = self.case
        backend, store, embedder, index, operation = self.ready_private()
        other = source_tests.person(case.s, case.rules, 'ordinary-cancel-manager')
        case.s.duties[other.person_id].add('document.semantic.manage')
        self.assert_cancel_denied_without_change(backend, store, embedder, operation, other)
        self.native_privacy.grant(other, 'C', 'P')
        cancelled = backend.cancel(case.scope, operation, other)
        self.assertEqual((cancelled['status'], cancelled['chunks']), ('cancelled', 1))
        self.assertIsNone(next(iter(store.rows.values()))['active_generation'])

    def test_revoked_owner_cancel_waits_for_current_source_read_restoration(self):
        case = self.case
        backend, store, embedder, index, operation = self.ready_private()
        self.native_privacy.grants.clear()
        self.assert_cancel_denied_without_change(backend, store, embedder, operation, case.s.actor)
        self.native_privacy.grant(case.s.actor, 'C', 'P')
        self.assertEqual(backend.cancel(case.scope, operation, case.s.actor)['status'], 'cancelled')

    def assert_cancel_denied_without_change(self, backend, store, embedder, operation, actor):
        case = self.case
        before, calls = deepcopy(store.rows), deepcopy(embedder.calls)
        with patch.object(case.adapter, '_revision_metadata',
                wraps=case.adapter._revision_metadata) as metadata, patch.object(
                case.storage, 'read', wraps=case.storage.read) as storage:
            with self.assertRaises(DomainError) as denied:
                backend.cancel(case.scope, operation, actor)
            self.assertEqual(denied.exception.code, 'capability_denied')
            metadata.assert_not_called()
            storage.assert_not_called()
        self.assertEqual(store.rows, before)
        self.assertEqual(embedder.calls, calls)


if __name__ == '__main__':
    unittest.main()
