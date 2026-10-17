"""DOC04 host source proofs using real DOC02 bytes and DOC03 domain checks.

Frappe metadata/session/transaction persistence is doubled explicitly. These
checks neither contact optional providers nor claim a connected/native runtime.
"""
from copy import deepcopy
from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.documents.core import DocumentService
from cipher_aec.documents.extraction import digest as bytes_digest
from cipher_aec.documents.storage import LocalArtifactStorage
from cipher_aec.tests.test_documents import MemoryMetadata
from cipher_aec.tests.test_document_control import authorize, person
from cipher_aec.tests.test_document_control_shared import shared_fixture
from cipher_aec.tests.test_engineering import uid


@contextmanager
def canonical_fixture():
    """Keep host DOC03 module doubles isolated from already imported adapters."""
    prefix = 'cipher_aec.document_control'
    saved = {name: module for name, module in sys.modules.items() if name == prefix or name.startswith(prefix + '.')}
    parent = importlib.import_module('cipher_aec')
    original = getattr(parent, 'document_control', None)
    for name in saved:
        sys.modules.pop(name)
    if hasattr(parent, 'document_control'):
        delattr(parent, 'document_control')
    try:
        with shared_fixture() as value:
            yield value
    finally:
        for name in list(sys.modules):
            if name == prefix or name.startswith(prefix + '.'):
                sys.modules.pop(name)
        sys.modules.update(saved)
        if original is not None:
            parent.document_control = original
        elif hasattr(parent, 'document_control'):
            delattr(parent, 'document_control')


class SemanticSourceTests(unittest.TestCase):
    def setUp(self):
        self.s, self.rules, self.dc_repo, self.rights, self.control, self.gov, self.shared = self.enterContext(canonical_fixture())
        self.scopes = importlib.import_module('cipher_aec.document_control.scopes')
        self.s.duties[self.s.actor.person_id].add('document.semantic.manage')
        self.s.company_duties[self.s.actor.person_id].add('document.semantic.manage')
        self.s.project_duties[self.s.actor.person_id] = set(self.s.duties[self.s.actor.person_id])
        self.repo = MemoryMetadata()
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.storage = LocalArtifactStorage(directory)
        self.documents = sys.modules['cipher_aec.documents.service']
        self.context = sys.modules['cipher_aec.governance.context']
        self.frappe = sys.modules['frappe']
        self.allow_unscanned = True
        # Bind the package attributes as well as sys.modules: other host test
        # modules may have imported the genuine implementation previously.
        self.enterContext(patch.object(importlib.import_module('cipher_aec.documents'), 'service', self.documents, create=True))
        self.enterContext(patch.object(importlib.import_module('cipher_aec.governance'), 'context', self.context, create=True))
        self.enterContext(patch.object(self.context, 'authority_fingerprint', lambda actor, company, project: digest([actor.person_id, project, sorted(self.duties(actor, 'Project', project))])))
        self.enterContext(patch.object(self.context, 'company_authority_fingerprint', lambda actor, company: digest([actor.person_id, 'Company', sorted(self.duties(actor, 'Company', None))]), create=True))
        self.enterContext(patch.object(self.documents, 'source_reference', self.project_source))
        self.enterContext(patch.object(self.documents, 'company_source_reference', self.company_source, create=True))
        self.enterContext(patch.object(self.documents, 'get_citation', self.project_citation))
        self.enterContext(patch.object(self.documents, 'get_company_citation', self.company_citation, create=True))
        self.enterContext(patch.object(self.control.sources, 'source_reference', self.project_source))
        self.enterContext(patch.object(self.control.sources, 'get_citation', self.project_citation))
        repository = self.control.FrappeDocumentRepository
        self.enterContext(patch.object(repository, 'document', lambda _, name, lock=False: self.repo.document(name, lock)))
        self.enterContext(patch.object(repository, 'document_scope', lambda _, name: {k: self.repo.docs[name][k] for k in ('name', 'company', 'scope_type', 'project')}))
        self.enterContext(patch.object(repository, 'revision_locator', lambda _, name: self.repo.revision_locator(name)))
        self.enterContext(patch.object(repository, 'revision_scope', lambda _, name: SimpleNamespace(**self.repo.revision_locator(name))))
        self.enterContext(patch.object(self.frappe.db, 'get_value', self.metadata, create=True))
        original_sql = self.frappe.db.sql
        def sql(query, args=(), **kwargs):
            if 'CHAR_LENGTH(pages_json)' in query:
                return [{'characters': len(self.repo.revs[args[0]]['pages_json'])}]
            return original_sql(query, args, **kwargs)
        self.enterContext(patch.object(self.frappe.db, 'sql', sql))
        # Load the adapter inside the isolated canonical-module lifetime, so
        # collecting this test module does not alter older host fixtures.
        global SourceAdapter
        SourceAdapter = importlib.import_module('cipher_aec.document_control.semantic_source').SourceAdapter
        self.adapter = SourceAdapter()
        self.scope = {'company': 'C', 'scope_type': 'Project', 'project': 'P'}
        self.ref = self.upload()
        self.grant(self.ref)
        self.selector = self.select(self.ref)

    def duties(self, actor, kind, project):
        source = self.s.company_duties if kind == 'Company' else self.s.duties if project == 'P' else self.s.project_duties
        return source.get(actor.person_id, set())

    def bound(self, kind, actor):
        return DocumentService(self.repo, self.storage,
            lambda company, project, ability: self.scopes.require(company, kind, project, actor, ability),
            source_authorize=lambda row, lock=False: self.rights.authorize(row, actor, lock=lock),
            scope_type=kind, allow_unscanned=self.allow_unscanned)

    def project_source(self, company, project, revision, page, actor=None, lock=False):
        return self.bound('Project', actor or self.s.actor).source_reference(company, project, revision, page, lock=lock)

    def company_source(self, company, revision, page, actor=None, lock=False):
        return self.bound('Company', actor or self.s.actor).source_reference(company, None, revision, page, lock=lock)

    def project_citation(self, company, revision, page, excerpt_sha256=None, actor=None):
        return self.bound('Project', actor or self.s.actor).citation(company, revision, page, excerpt_sha256)

    def company_citation(self, company, revision, page, excerpt_sha256=None, actor=None, lock=False):
        return self.bound('Company', actor or self.s.actor).citation(company, revision, page, excerpt_sha256, lock=lock)

    def metadata(self, doctype, name, fields, as_dict=False):
        self.assertEqual(doctype, 'Cipher Document Revision')
        self.assertNotIn('pages_json', fields)
        return {key: self.repo.revs[name][key] for key in fields}

    def upload(self, content=b'Concrete strength is 4000 psi.\fWind speed is 115 mph.', *, kind='Project', project='P', previous=None):
        if kind == 'Company':
            project = None
        values = dict(company='C', project=project, title='Canonical specification', filename='notes.txt',
                      content=content, byte_length=len(content), sha256=bytes_digest(content))
        if previous:
            old = self.repo.revs[previous['revision_id']]
            values.update(document_id=old['document'], expected_revision=old['revision_number'])
        result = self.bound(kind, self.s.actor).upload(**values)
        rid = result['revision']['id']
        # DOC03's existing persistence double discovers immutable artifact scope
        # and heads from this map. Content itself still comes from real storage.
        revision = self.repo.revs[rid]
        self.s.documents[rid] = {'document_id': revision['document'], 'revision_id': rid,
            'source_sha256': revision['sha256'], 'revision_number': revision['revision_number'],
            'byte_length': revision['byte_length'], 'mime_type': revision['mime_type'],
            'page_count': revision['page_count'], 'scope_type': kind, 'project': project}
        return {'revision_id': rid, 'source_sha256': revision['sha256']}

    def grant(self, ref, *, evidence=None, **changes):
        row = self.repo.revs[ref['revision_id']]
        evidence = evidence or self.upload(b'Authored source-use permission evidence.', kind=row['scope_type'], project=row['project'])
        definition = {'ingest_allowed': True, 'read_allowed': True, 'distribute_allowed': False,
            'rights_basis': 'Explicit synthetic internal semantic ingestion and read basis',
            'rights_holder': 'Synthetic owner', 'allowed_purpose': 'Internal semantic retrieval',
            'restriction': 'No external distribution', 'valid_from': None, 'valid_until': None,
            'evidence_artifact': dict(evidence), **changes}
        prior = self.rights.current(row['document'])
        if row['scope_type'] == 'Company':
            self.shared.set_rights('C', uid(), row['document'], digest(prior) if prior else None, definition)
        else:
            self.control.set_rights('C', row['project'], uid(), row['document'], digest(prior) if prior else None, definition)
        return evidence

    def select(self, ref, selection='working', adoption=None):
        return {'document_id': self.repo.revs[ref['revision_id']]['document'], **ref, 'selection': selection,
                'adoption_id': adoption['id'] if adoption else None, 'adoption_digest': digest(adoption) if adoption else None}

    def documentary_source(self, content=b'Exact documentary lifecycle source.', previous=None):
        # DOC03 lifecycle references use UUID identities. This host repository
        # explicitly supplies those identities while retaining DOC02's actual
        # immutable source bytes, extraction and canonical read implementation.
        ref = self.upload(content, previous=previous)
        old_id = ref['revision_id']
        row = self.repo.revs.pop(old_id)
        old_document = row['document']
        document_id = old_document if previous else uid()
        revision_id = uid()
        parent = self.repo.docs.pop(old_document)
        parent.update(name=document_id, current_revision=revision_id)
        self.repo.docs[document_id] = parent
        row.update(name=revision_id, document=document_id, storage_reference=revision_id)
        self.repo.revs[revision_id] = row
        (self.storage.root / old_id).rename(self.storage.root / revision_id)
        scoped = self.s.documents.pop(old_id)
        scoped.update(document_id=document_id, revision_id=revision_id)
        self.s.documents[revision_id] = scoped
        return {'revision_id': revision_id, 'source_sha256': ref['source_sha256']}

    def snapshot(self, *, scope=None, selector=None, actor=None):
        return self.adapter.snapshot(scope or self.scope, selector or self.selector, actor or self.s.actor)

    def issue(self, ref=None):
        self.grant(ref or self.ref, distribute_allowed=True)
        value = self.control.create_issue_set('C', 'P', uid(), {'title': 'Issued exact source', 'purpose': 'Internal reference', 'issue_purpose': 'information'}, [ref or self.ref], [])['issue_set']
        return authorize(self.s, self.rules, self.gov, 'issue_set', value, person(self.s, self.rules, 'independent-issue-checker'))

    def adopt(self, ref):
        row = self.repo.revs[ref['revision_id']]
        definition = {'title': 'Reusable original', 'category': 'reference', 'discipline': 'Civil', 'ownership': 'Company owner', 'tags': [], 'change_reason': 'Initial'}
        if row['scope_type'] == 'Company':
            library = self.shared.library('C', uid(), definition, ref)
        else:
            library = self.control.create_library('C', row['project'], uid(), definition, ref)
        original = library['library_revision']
        request = self.shared.create_adoption('C', 'P', uid(), {'scope_type': row['scope_type'], 'project': row['project']}, original['id'], digest(original),
            {'purpose': 'Use the retained source', 'target_locator': 'Project reference', 'change_reason': 'Independent exact adoption'})['adoption_request']
        checker = person(self.s, self.rules, 'independent-adoption-checker')
        self.s.company_duties[checker.person_id] = {self.rules.READ, 'company.read', 'document.read'}
        self.s.project_duties[checker.person_id] = set(self.s.duties[checker.person_id])
        return authorize(self.s, self.rules, self.gov, 'adoption_request', request, checker), request

    def test_snapshot_returns_exact_canonical_pages_without_original_bytes(self):
        result = self.snapshot()
        self.assertEqual(result['pages'], [self.project_citation('C', self.ref['revision_id'], page) for page in (1, 2)])
        self.assertEqual(result['source_scope'], self.scope)
        self.assertEqual(result['metadata']['source_sha256'], self.ref['source_sha256'])
        self.assertEqual(len(result['token']), 64)
        self.assertNotIn('content', result)
        self.assertNotIn('pages_json', result['metadata'])
        self.assertTrue(self.adapter.recheck(self.scope, self.selector, result['token'], self.s.actor))

    def test_company_source_is_explicit_and_citations_keep_company_scope(self):
        ref = self.upload(kind='Company')
        self.grant(ref)
        scope = {'company': 'C', 'scope_type': 'Company', 'project': None}
        result = self.snapshot(scope=scope, selector=self.select(ref))
        self.assertEqual(result['pages'][0]['scope_type'], 'Company')
        self.assertEqual(result['pages'][0]['company'], 'C')
        self.assertIsNone(result['pages'][0]['project'])
        with self.assertRaises(DomainError):
            self.snapshot(selector=self.select(ref))

    def test_manage_is_a_separate_current_duty_and_still_requires_read(self):
        self.adapter.authorize(self.scope, self.s.actor, manage=True)
        self.s.duties[self.s.actor.person_id].remove('document.semantic.manage')
        self.adapter.authorize(self.scope, self.s.actor)
        with self.assertRaises(DomainError):
            self.adapter.authorize(self.scope, self.s.actor, manage=True)
        self.s.duties[self.s.actor.person_id].add('document.semantic.manage')
        self.s.duties[self.s.actor.person_id].remove('document.read')
        with self.assertRaises(DomainError):
            self.adapter.authorize(self.scope, self.s.actor, manage=True)

    def test_closed_scope_and_selector_reject_implicit_scope_and_injected_fields(self):
        invalid_scopes = [{**self.scope, 'scope_type': 'Company'}, {**self.scope, 'project': None},
                          {k: v for k, v in self.scope.items() if k != 'scope_type'}, {**self.scope, 'extra': True}]
        invalid_selectors = [{**self.selector, 'scope_type': 'Project'}, {**self.selector, 'source_sha256': 'A' * 64},
            {**self.selector, 'adoption_id': uid()}, {**self.selector, 'selection': 'latest'},
            {**self.selector, 'selection': 'adopted'}, {k: v for k, v in self.selector.items() if k != 'adoption_digest'}]
        for scope in invalid_scopes:
            with self.subTest(scope=scope), self.assertRaises(DomainError):
                self.snapshot(scope=scope)
        for selector in invalid_selectors:
            with self.subTest(selector=selector), self.assertRaises(DomainError):
                self.snapshot(selector=selector)

    def test_current_acl_denial_precedes_metadata_plaintext_and_original_bytes(self):
        self.snapshot()
        self.s.duties[self.s.actor.person_id].remove('document.read')
        with patch.object(self.repo, 'revision', wraps=self.repo.revision) as revision, patch.object(self.storage, 'read', wraps=self.storage.read) as content:
            with self.assertRaises(DomainError):
                self.snapshot()
            revision.assert_not_called()
            content.assert_not_called()

    def test_direct_read_and_ingest_rights_are_both_current_and_required(self):
        for operation in ('read', 'ingest'):
            with self.subTest(operation=operation):
                self.grant(self.ref, **{operation + '_allowed': False})
                with patch.object(self.repo, 'revision', wraps=self.repo.revision) as revision, self.assertRaises(DomainError) as denied:
                    self.snapshot()
                self.assertEqual(denied.exception.code, 'source_rights_denied')
                self.assertNotIn(self.ref['revision_id'], [call.args[0] for call in revision.call_args_list])
                self.grant(self.ref)
        fresh = self.upload(b'No declared semantic ingest basis.')
        with self.assertRaises(DomainError) as denied:
            self.snapshot(selector=self.select(fresh))
        self.assertEqual(denied.exception.code, 'source_rights_required')

    def test_expired_rights_refuse_retrieval_without_selected_plaintext(self):
        self.grant(self.ref, valid_until='2000-01-01')
        with patch.object(self.repo, 'revision', wraps=self.repo.revision) as revision, self.assertRaises(DomainError) as denied:
            self.snapshot()
        self.assertEqual(denied.exception.code, 'source_rights_inactive')
        revision.assert_not_called()

    def test_recursive_evidence_ingest_revocation_is_checked(self):
        policy = self.rights.current(self.selector['document_id'])
        evidence = {k: policy['evidence_artifact'][k] for k in ('revision_id', 'source_sha256')}
        self.grant(evidence)
        allowed = self.snapshot()
        self.assertEqual(len(allowed['rights']), 3)
        self.grant(evidence, ingest_allowed=False)
        with self.assertRaises(DomainError) as denied:
            self.adapter.recheck(self.scope, self.selector, allowed['token'], self.s.actor)
        self.assertEqual(denied.exception.code, 'source_rights_denied')

    def test_current_recursive_policy_change_invalidates_token_without_rewriting_source(self):
        policy = self.rights.current(self.selector['document_id'])
        evidence = {k: policy['evidence_artifact'][k] for k in ('revision_id', 'source_sha256')}
        self.grant(evidence)
        before = self.snapshot()
        self.grant(evidence, restriction='Changed permitted internal purpose')
        after = self.snapshot()
        self.assertNotEqual(before['token'], after['token'])
        self.assertEqual(before['pages'], after['pages'])
        self.assertFalse(self.adapter.recheck(self.scope, self.selector, before['token'], self.s.actor))

    def test_cyclic_rights_evidence_is_bounded_and_refused(self):
        policy = self.rights.current(self.selector['document_id'])
        original = deepcopy(policy)
        policy['evidence_artifact']['document_id'] = self.selector['document_id']
        self.s.rows['rights', policy['id']] = policy
        with self.assertRaises(DomainError) as denied:
            self.snapshot()
        self.assertEqual(denied.exception.code, 'source_rights_cycle')
        self.s.rows['rights', original['id']] = original

    def test_tokens_are_actor_independent_but_each_actor_must_have_current_rights(self):
        first = self.snapshot()
        reader = person(self.s, self.rules, 'other-reader')
        second = self.snapshot(actor=reader)
        self.assertEqual(first['token'], second['token'])
        self.assertNotEqual(first['authority'], second['authority'])
        self.assertTrue(self.adapter.recheck(self.scope, self.selector, first['token'], reader))
        self.s.duties[reader.person_id].remove('document.read')
        with self.assertRaises(DomainError):
            self.adapter.recheck(self.scope, self.selector, first['token'], reader)

    def test_working_requires_the_actual_current_head(self):
        old = self.snapshot()
        next_ref = self.upload(b'New authorized working source.', previous=self.ref)
        with self.assertRaises(DomainError) as changed:
            self.snapshot()
        self.assertEqual(changed.exception.code, 'semantic_source_changed')
        self.assertEqual(self.snapshot(selector=self.select(next_ref))['metadata']['revision_number'], 2)
        with self.assertRaises(DomainError):
            self.adapter.recheck(self.scope, self.selector, old['token'], self.s.actor)

    def test_issued_selects_current_issued_revision_after_new_working_head(self):
        self.issue()
        selector = self.select(self.ref, 'issued')
        before = self.snapshot(selector=selector)
        self.upload(b'New unissued working revision.', previous=self.ref)
        after = self.snapshot(selector=selector)
        self.assertEqual(before['token'], after['token'])
        self.assertEqual(after['metadata']['revision_id'], self.ref['revision_id'])
        self.assertEqual(after['metadata']['selection'], 'issued')

    def test_actual_doc02_names_allow_initial_issue_but_doc03_lifecycle_refuses_safely(self):
        from cipher_aec.document_control import lifecycle
        self.assertTrue(self.selector['document_id'].startswith('DOC-'))
        self.assertTrue(self.ref['revision_id'].startswith('REV-'))
        issue = self.issue()
        selector = self.select(self.ref, 'issued')
        initial = self.snapshot(selector=selector)
        standing = initial['selection_proof']
        before = deepcopy((self.s.rows, self.s.events, self.s.receipts))
        with self.assertRaises(DomainError) as preparation:
            lifecycle.request('C', 'P', uid(), selector['document_id'], standing['version'],
                {'action': 'withdraw', 'issue_id': issue['id'], 'issue_digest': digest(issue),
                 'replacement_issue_id': None, 'replacement_issue_digest': None,
                 'reason': 'Actual DOC02 names must compose with the lifecycle contract'})
        self.assertEqual(preparation.exception.code, 'invalid_engineering')
        self.assertEqual((self.s.rows, self.s.events, self.s.receipts), before)
        with self.assertRaises(DomainError) as retained_reference:
            lifecycle._reference(standing['current_issued'])
        self.assertEqual(retained_reference.exception.code, 'invalid_engineering')
        # Initial issue reads do not traverse _reference; this dependency gap
        # blocks actual-name lifecycle preparation/replay, not that initial read.
        self.assertEqual(self.snapshot(selector=selector)['token'], initial['token'])

    def test_withdrawn_issued_source_is_refused(self):
        from cipher_aec.document_control import lifecycle
        ref = self.documentary_source()
        original = self.issue(ref)
        selector = self.select(ref, 'issued')
        before = self.snapshot(selector=selector)
        standing = lifecycle.standing('C', 'P', selector['document_id'], self.s.actor)
        request = lifecycle.request('C', 'P', uid(), selector['document_id'], standing['version'],
            {'action': 'withdraw', 'issue_id': original['id'], 'issue_digest': digest(original),
             'replacement_issue_id': None, 'replacement_issue_digest': None, 'reason': 'Explicit documentary withdrawal'})['lifecycle_request']
        authorize(self.s, self.rules, self.gov, 'lifecycle_request', request, person(self.s, self.rules, 'withdrawal-checker'))
        with self.assertRaises(DomainError) as changed:
            self.adapter.recheck(self.scope, selector, before['token'], self.s.actor)
        self.assertEqual(changed.exception.code, 'semantic_source_changed')

    def test_superseded_source_is_refused_and_exact_replacement_is_current(self):
        from cipher_aec.document_control import lifecycle
        ref = self.documentary_source()
        original = self.issue(ref)
        selector = self.select(ref, 'issued')
        before = self.snapshot(selector=selector)
        replacement_ref = self.documentary_source(b'Explicit replacement documentary source.', previous=ref)
        replacement = self.issue(replacement_ref)
        standing = lifecycle.standing('C', 'P', selector['document_id'], self.s.actor)
        request = lifecycle.request('C', 'P', uid(), selector['document_id'], standing['version'],
            {'action': 'supersede', 'issue_id': original['id'], 'issue_digest': digest(original),
             'replacement_issue_id': replacement['id'], 'replacement_issue_digest': digest(replacement),
             'reason': 'Explicit independently reviewed replacement'})['lifecycle_request']
        authorize(self.s, self.rules, self.gov, 'lifecycle_request', request, person(self.s, self.rules, 'supersession-checker'))
        with self.assertRaises(DomainError):
            self.adapter.recheck(self.scope, selector, before['token'], self.s.actor)
        after = self.snapshot(selector=self.select(replacement_ref, 'issued'))
        self.assertEqual(after['metadata']['revision_id'], replacement_ref['revision_id'])

    def test_unissued_company_and_foreign_project_cannot_use_issued_selection(self):
        with self.assertRaises(DomainError):
            self.snapshot(selector=self.select(self.ref, 'issued'))
        for kind, project in [('Company', None), ('Project', 'SOURCE')]:
            ref = self.upload(kind=kind, project=project)
            self.grant(ref)
            with self.subTest(kind=kind), self.assertRaises(DomainError):
                self.snapshot(selector=self.select(ref, 'issued'))

    def test_company_adoption_preserves_original_revision_and_requires_both_scopes(self):
        ref = self.upload(kind='Company')
        self.grant(ref)
        adoption, _ = self.adopt(ref)
        selector = self.select(ref, 'adopted', adoption)
        before = self.snapshot(selector=selector)
        self.upload(b'Later Company working revision.', kind='Company', previous=ref)
        after = self.snapshot(selector=selector)
        self.assertEqual(before['token'], after['token'])
        self.assertEqual(after['source_scope'], {'company': 'C', 'scope_type': 'Company', 'project': None})
        self.s.company_duties[self.s.actor.person_id].remove('document.read')
        with self.assertRaises(DomainError):
            self.snapshot(selector=selector)
        self.s.company_duties[self.s.actor.person_id].add('document.read')
        self.s.duties[self.s.actor.person_id].remove('document.read')
        with self.assertRaises(DomainError):
            self.snapshot(selector=selector)

    def test_project_adoption_keeps_source_project_authority_distinct(self):
        ref = self.upload(project='SOURCE')
        self.grant(ref)
        adoption, _ = self.adopt(ref)
        selector = self.select(ref, 'adopted', adoption)
        result = self.snapshot(selector=selector)
        self.assertEqual(result['source_scope']['project'], 'SOURCE')
        self.s.project_duties[self.s.actor.person_id].remove('document.read')
        with self.assertRaises(DomainError):
            self.snapshot(selector=selector)

    def test_adoption_requires_exact_approved_fact_digest_and_artifact(self):
        ref = self.upload(kind='Company')
        self.grant(ref)
        adoption, request = self.adopt(ref)
        selector = self.select(ref, 'adopted', adoption)
        for changes in ({'adoption_id': request['id'], 'adoption_digest': digest(request)}, {'adoption_digest': '0' * 64},
                        {'document_id': self.selector['document_id'], **self.ref}):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                self.snapshot(selector={**selector, **changes})
        self.s.decisions[adoption['decision_id']].decision = 'Reject'
        with self.assertRaises(DomainError) as denied:
            self.snapshot(selector=selector)
        self.assertEqual(denied.exception.code, 'document_approval_integrity')

    def test_wrong_owning_company_and_revision_mapping_fail_before_content(self):
        for changes in ({'company': 'Other'}, {'document': 'Other-document'}):
            original = deepcopy(self.repo.revs[self.ref['revision_id']])
            self.repo.revs[self.ref['revision_id']].update(changes)
            with self.subTest(changes=changes), patch.object(self.storage, 'read', wraps=self.storage.read) as read:
                with self.assertRaises(DomainError):
                    self.snapshot()
                read.assert_not_called()
            self.repo.revs[self.ref['revision_id']] = original

    def test_scan_quarantine_extraction_and_actual_source_bytes_remain_canonical(self):
        revision = self.repo.revs[self.ref['revision_id']]
        for key, value in [('scan_status', 'infected'), ('retrieval_status', 'quarantined'), ('extraction_status', 'ocr_unavailable')]:
            previous = revision[key]
            revision[key] = value
            with self.subTest(key=key), self.assertRaises(DomainError):
                self.snapshot()
            revision[key] = previous
        self.allow_unscanned = False
        with self.assertRaises(DomainError):
            self.snapshot()
        self.allow_unscanned = True
        (Path(self.storage.root) / self.ref['revision_id']).write_bytes(b'Altered retained source bytes.')
        with self.assertRaises(DomainError) as denied:
            self.snapshot()
        self.assertEqual(denied.exception.code, 'semantic_source_unavailable')

    def test_page_and_serialized_text_limits_precede_full_revision_or_bytes(self):
        for adapter in (SourceAdapter(max_pages=1), SourceAdapter(max_characters=10)):
            with self.subTest(adapter=adapter), patch.object(self.repo, 'revision', wraps=self.repo.revision) as revision, patch.object(self.storage, 'read', wraps=self.storage.read) as content:
                with self.assertRaises(DomainError) as denied:
                    adapter.snapshot(self.scope, self.selector, self.s.actor)
                self.assertEqual(denied.exception.code, 'semantic_source_limit')
                revision.assert_not_called()
                content.assert_not_called()

    def test_canonical_citation_checksum_mismatch_is_refused(self):
        def altered(*args, **kwargs):
            return {**self.project_citation(*args, **kwargs), 'excerpt_sha256': '0' * 64}
        with patch.object(self.documents, 'get_citation', altered), self.assertRaises(DomainError):
            self.snapshot()

    def test_source_change_during_citation_read_is_refused(self):
        changed = False
        def read(*args, **kwargs):
            nonlocal changed
            result = self.project_citation(*args, **kwargs)
            if not changed:
                changed = True
                self.upload(b'Concurrent successor.', previous=self.ref)
            return result
        with patch.object(self.documents, 'get_citation', read), self.assertRaises(DomainError) as denied:
            self.snapshot()
        self.assertEqual(denied.exception.code, 'semantic_source_changed')

    def test_recheck_invalid_token_and_malformed_canonical_json_return_safe_errors(self):
        with self.assertRaises(DomainError) as denied:
            self.adapter.recheck(self.scope, self.selector, 'unsafe-token', self.s.actor)
        self.assertEqual(denied.exception.code, 'invalid_semantic_source')
        self.repo.revs[self.ref['revision_id']]['pages_json'] = '[source-private-secret'
        with self.assertRaises(DomainError) as denied:
            self.snapshot()
        self.assertNotIn('source-private-secret', denied.exception.message)


if __name__ == '__main__':
    unittest.main()
