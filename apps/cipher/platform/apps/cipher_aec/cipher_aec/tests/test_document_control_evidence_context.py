"""Real documentary discovery/held-union host regressions, not native proof.

Only native storage, source retrieval, duties and native master locks are doubled.
DocumentContext.discover/prelock/hold and current rights checks run unmodified.
"""
from contextlib import contextmanager, ExitStack, nullcontext
from copy import deepcopy
import importlib
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_document_control import fixture, source
from cipher_aec.tests.test_engineering import add_source, uid


@contextmanager
def context_fixture():
    with fixture() as (state, rules, repo, rights, service, governance):
        report = source(state, service)
        company_source, permission_source, later_source = [add_source(state) for _ in range(3)]
        for reference in (company_source, permission_source, later_source):
            state.documents[reference['revision_id']].update(scope_type='Company', project=None)
        artifact_keys = ('document_id', 'revision_id', 'revision_number', 'source_sha256', 'byte_length', 'mime_type', 'page_count')
        def artifact(reference):
            return {key: state.documents[reference['revision_id']][key] for key in artifact_keys}
        original = artifact(company_source)
        permission = artifact(permission_source)
        policy = {'id': uid(), 'parent_id': original['document_id'], 'company': 'C', 'project': None, 'scope_type': 'Company', 'revision_number': 1,
            'valid_from': None, 'valid_until': None, 'read_allowed': True, 'ingest_allowed': True, 'distribute_allowed': True, 'evidence_artifact': permission}
        state.rows['rights', policy['id']] = policy
        base = {'company': 'C', 'project': 'P', 'scope_type': 'Project'}
        library_id, request_id, adoption_id, transmittal_id, distribution_id = [uid() for _ in range(5)]
        rows = {
            ('library_revision', library_id): {**base, 'id': library_id, 'artifacts': [original]},
            ('adoption_request', request_id): {**base, 'id': request_id, 'library_revision': library_id, 'artifacts': [original]},
            ('adoption', adoption_id): {**base, 'id': adoption_id, 'subject_id': request_id, 'artifacts': [original]},
            ('transmittal', transmittal_id): {**base, 'id': transmittal_id, 'artifacts': [original]},
            ('distribution', distribution_id): {**base, 'id': distribution_id, 'subject_id': transmittal_id, 'artifacts': [original]},
        }
        state.rows.update(rows)
        evidence = {}
        for kind, name in (('distribution', distribution_id), ('adoption', adoption_id)):
            value = {**base, 'id': uid(), 'subject_kind': kind, 'subject_id': name, 'artifacts': [artifact(report)]}
            state.rows['evidence', value['id']] = value
            evidence[kind] = value
        locking = importlib.import_module('cipher_aec.document_control.locking')
        scopes = importlib.import_module('cipher_aec.document_control.scopes')
        documents = sys.modules['cipher_aec.documents.service']
        observed = []
        state.company_allowed = True
        def company(company, ability='company.read', actor=None, lock=False):
            observed.append(('duty', 'Company', ability))
            if company != 'C' or not state.company_allowed:
                raise DomainError('capability_denied', 'Current Company source duty denied', 403)
            return SimpleNamespace(name=company)
        original_project = service.require_project
        def project(company_name, project_name, ability='project.read', actor=None, lock=False):
            observed.append(('duty', 'Project', ability))
            return original_project(company_name, project_name, ability=ability, actor=actor, lock=lock)
        def revision(name):
            row = state.documents[name]
            return SimpleNamespace(company='C', project=row.get('project', 'P'), scope_type=row.get('scope_type', 'Project'), document=row['document_id'])
        def metadata(name):
            row = next(row for row in state.documents.values() if row['document_id'] == name)
            return SimpleNamespace(company='C', project=row.get('project', 'P'), scope_type=row.get('scope_type', 'Project'))
        def document(name, company_name, scope_type, project_name, actor, lock=False):
            scopes.require(company_name, scope_type, project_name, actor, 'document.read', lock=lock)
            row = metadata(name)
            if row.scope_type != scope_type or row.project != project_name:
                raise DomainError('not_found', 'Original scope differs', 404)
            observed.append(('document', name))
            return row
        def company_reference(company_name, revision_id, page, actor=None, lock=False):
            scopes.require(company_name, 'Company', None, actor, 'document.read', lock=lock)
            row = state.documents[revision_id]
            if row.get('scope_type') != 'Company' or row.get('project') is not None:
                raise DomainError('not_found', 'Company source differs', 404)
            rights.require(row['document_id'], company_name, None, 'read', actor, lock=lock, required=False, scope_type='Company')
            return {**deepcopy(row), 'page': page}
        provenance = ModuleType('provenance')
        provenance.MAX_NODES = 128
        provenance.binding = lambda *a: None
        provenance.source_plan = lambda *a: {'unit_ids': ['unit'], 'currencies': ['USD'], 'native_refs': [{'doctype': 'Customer', 'name': 'party'}]}
        provenance.prelocked = lambda *a: nullcontext()
        units = ModuleType('units')
        units.qualified = lambda name, **kw: observed.append(('master', 'unit', name))
        native = ModuleType('native')
        native.require_native = lambda kind, name, *a, **kw: observed.append(('master', kind, name))
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {'cipher_aec.documents.provenance': provenance, 'cipher_aec.estimating.units': units, 'cipher_aec.commercial.native': native}))
            for owner, name, value in (
                (locking, 'require_company', company), (locking, 'require_project', project), (scopes, 'require_company', company),
                (scopes, 'require_project', project), (scopes, 'document', document),
                (service.FrappeDocumentRepository, 'revision_scope', lambda _, name: revision(name)),
                (service.FrappeDocumentRepository, 'document_scope', lambda _, name: metadata(name)),
                (service.FrappeDocumentRepository, 'document', lambda _, name, **kw: {'name': name}),
                (documents, 'company_source_reference', company_reference)):
                stack.enter_context(patch.object(owner, name, value, create=True))
            yield SimpleNamespace(state=state, rules=rules, repo=repo, rights=rights, service=service, locking=locking, observed=observed,
                evidence=evidence, original=original, permission=permission, later=artifact(later_source), policy=policy)


class EvidenceOriginalContextTests(unittest.TestCase):
    def test_evidence_discovery_includes_exact_original_subject_scopes_and_permission_sources(self):
        for kind in ('distribution', 'adoption'):
            with self.subTest(kind=kind), context_fixture() as values:
                context = values.locking.for_result('C', 'P', {'evidence': values.evidence[kind]})
                plan = context.discover(values.state.actor)
                self.assertEqual(plan['scopes'], [('Company', None), ('Project', 'P')])
                self.assertIn(values.original['document_id'], plan['documents'])
                self.assertIn(values.permission['document_id'], plan['documents'])
                self.assertNotIn(values.later['document_id'], plan['documents'])
                self.assertFalse(context.standing_documents)

    def test_real_receipt_hold_covers_nested_subject_source_prelock(self):
        for kind in ('distribution', 'adoption'):
            with self.subTest(kind=kind), context_fixture() as values:
                context = values.locking.for_result('C', 'P', {'evidence': values.evidence[kind]})
                with context.hold(values.state.actor):
                    values.service._prelock([values.original], 'C', 'P', values.state.actor, lock=True, allow_foreign=True)
                    values.rights.require(values.original['document_id'], 'C', None, 'read', values.state.actor, scope_type='Company')
                    values.observed.append(('read',))
                self.assertIsNone(values.locking._active.get())
                first_master = next(index for index, item in enumerate(values.observed) if item[0] == 'master')
                self.assertIn(('duty', 'Company', 'document.read'), values.observed[:first_master])
                self.assertEqual([item[1] for item in values.observed if item[0] == 'document'], sorted(context.initial['documents']))

    def test_missing_company_duty_is_refused_before_master_or_source_locks(self):
        with context_fixture() as values:
            values.state.company_allowed = False
            context = values.locking.for_result('C', 'P', {'evidence': values.evidence['distribution']})
            with self.assertRaises(DomainError) as error:
                with context.hold(values.state.actor):
                    self.fail('No original receipt content without Company authority')
            self.assertEqual(error.exception.code, 'capability_denied')
            self.assertFalse(any(row[0] in ('master', 'document') for row in values.observed))
            self.assertIsNone(values.locking._active.get())

    def test_current_source_rights_denial_survives_receipt_union_without_an_effect(self):
        with context_fixture() as values:
            values.policy['read_allowed'] = False
            before = deepcopy(values.state.rows)
            context = values.locking.for_result('C', 'P', {'evidence': values.evidence['distribution']})
            with self.assertRaises(DomainError) as error:
                with context.hold(values.state.actor):
                    values.rights.require(values.original['document_id'], 'C', None, 'read', values.state.actor, scope_type='Company')
                    self.fail('No source content effect under revoked current rights')
            self.assertEqual(error.exception.code, 'source_rights_denied')
            self.assertEqual(values.state.rows, before)
            self.assertIsNone(values.locking._active.get())

    def test_evidence_subject_kind_allowlist_refuses_corrupted_arbitrary_root(self):
        with context_fixture() as values:
            evidence = values.evidence['distribution']
            evidence['subject_kind'] = 'clause_use'
            with self.assertRaises(DomainError) as error:
                values.locking.for_result('C', 'P', {'evidence': evidence}).discover(values.state.actor)
            self.assertEqual(error.exception.code, 'document_control_integrity')

    def test_subject_traversal_retains_existing_documentary_and_rights_graph_bounds(self):
        with context_fixture() as values:
            evidence = values.evidence['adoption']
            root = values.state.rows['adoption', evidence['subject_id']]
            previous = root
            for _ in range(129):
                name = uid()
                previous['library_revision'] = name
                value = {'id': name, 'company': 'C', 'artifacts': []}
                values.state.rows['library_revision', name] = value
                previous = value
            with self.assertRaises(DomainError) as error:
                values.locking.for_result('C', 'P', {'evidence': evidence}).discover(values.state.actor)
            self.assertEqual(error.exception.code, 'document_source_limit')
        with context_fixture() as values:
            values.policy['evidence_artifact'] = values.original
            with self.assertRaises(DomainError) as error:
                values.locking.for_result('C', 'P', {'evidence': values.evidence['distribution']}).discover(values.state.actor)
            self.assertEqual(error.exception.code, 'source_rights_cycle')


if __name__ == '__main__':
    unittest.main()
