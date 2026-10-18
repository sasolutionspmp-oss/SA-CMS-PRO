"""Serial classification admission through actual ordinary/private upload services.

Storage, database, current duty and command/session boundaries are explicit host
doubles. These checks do not qualify native concurrency, File dedup or rollback.
"""
import base64
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cipher_aec.api.errors import DomainError
from cipher_aec.documents.core import DocumentService
from cipher_aec.tests.test_documents import MemoryMetadata
from .quality_safety_fixtures import fixtures, uid, add_source


@contextmanager
def upload_fixture():
    with fixtures() as (state, rules, repository, sources, quality, records):
        privacy = importlib.import_module('cipher_aec.quality_safety.privacy')
        evidence = importlib.import_module('cipher_aec.quality_safety.evidence')
        # The common fixture intentionally doubles the source-reference adapter.
        # Load the actual ordinary upload wrapper separately and retain that
        # adapter for permission evidence used by the real private service.
        path = Path(__file__).parents[1] / 'documents/service.py'
        spec = importlib.util.spec_from_file_location('cipher_aec.documents._serial_upload_service', path)
        ordinary = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ordinary)
        frappe = importlib.import_module('frappe')
        context = importlib.import_module('cipher_aec.governance.context')
        commands = importlib.import_module('cipher_aec.governance.commands')
        rights = importlib.import_module('cipher_aec.document_control.rights')
        metadata = MemoryMetadata()
        state.stored, state.upload_events, state.duplicate_queries = {}, [], []
        state.blocked, state.denied_companies = set(), set()

        def require(company, project, ability='project.read', actor=None, lock=False):
            actor = actor or state.actor
            if company != 'C' or project != 'P':
                raise DomainError('not_found', 'This scope is unavailable.', 404)
            if (company, project, ability) in state.blocked:
                raise DomainError('capability_denied', 'Current duty denied.', 403)
            state.require(company, project, ability, actor, lock)
            state.upload_events.append(('duty', 'Project', ability))
            return SimpleNamespace(status='Open')

        def require_company(company, ability='company.read', actor=None, lock=False):
            actor = actor or state.actor
            if company not in ('C', 'OTHER') or company in state.denied_companies:
                raise DomainError('not_found', 'This scope is unavailable.', 404)
            if actor.user not in state.users or state.users[actor.user].person_id != actor.person_id:
                raise DomainError('identity_changed', 'Current identity differs.', 403)
            if (company, None, ability) in state.blocked:
                raise DomainError('capability_denied', 'Current duty denied.', 403)
            state.upload_events.append(('duty', 'Company', ability))
            return SimpleNamespace()

        def source_authorize(row, actor, lock=False):
            privacy.authorize_source(row, actor, lock=lock)
            require_rights(row.get('document') or row['name'], row['company'], row['project'],
                           'read', actor, lock=lock, required=False, scope_type=row['scope_type'])

        def require_rights(name, company, project, operation, actor, lock=False, required=True, scope_type='Project'):
            if scope_type == 'Project': require(company, project, 'document.read', actor, lock)
            else: require_company(company, 'document.read', actor, lock)
            policy = state.rights.get(name)
            if required and policy is None:
                raise DomainError('source_rights_required', 'Current authored rights required.', 409)
            if policy in ('expired', 'read_denied') or operation == 'ingest' and policy == 'ingest_denied':
                raise DomainError('source_rights_denied', 'Current authored rights denied.', 403)
            state.upload_events.append(('rights', scope_type, operation))
            return policy

        def prelock_rights(names, company, project, actor, scope_type='Project'):
            for name in names:
                if name in metadata.docs:
                    row = metadata.document(name, lock=True)
                else:
                    source = next(value for value in state.documents.values() if value['document_id'] == name)
                    row = {'name': name, 'company': source.get('company','C'),
                           'project': source.get('project','P'), 'scope_type': source.get('scope_type','Project')}
                core = DocumentService(metadata, Storage(),
                    lambda c,p,a: require(c,p,a,actor) if scope_type == 'Project' else require_company(c,a,actor),
                    scope_type=scope_type, source_authorize=lambda value, lock=False: source_authorize(value, actor, lock))
                # Exact target source scope and current source privacy/rights
                # admission precede the ordinary wrapper's duplicate lookup.
                ordinary._call(lambda: core._scope(row, company, project, lock=True))

        class Metadata(MemoryMetadata):
            def __init__(self, scope_type='Project'):
                self.docs, self.revs = metadata.docs, metadata.revs
            def create_document(self, row):
                state.upload_events.append(('create_document', row['scope_type']))
                super().create_document(row)
            def create_revision(self, row):
                super().create_revision(row)
                state.documents[row['name']] = {
                    'document_id': row['document'], 'revision_id': row['name'],
                    'revision_number': row['revision_number'], 'source_sha256': row['sha256'],
                    'byte_length': row['byte_length'], 'mime_type': row['mime_type'],
                    'page_count': row['page_count'], 'page': 1, 'is_current': True,
                    'company': row['company'], 'project': row['project'], 'scope_type': row['scope_type'],
                    'content': state.stored[row['storage_reference']]}

        class Storage:
            def put(self, revision, filename, content):
                state.upload_events.append(('put', filename))
                state.stored[revision] = bytes(content)
                return revision

        original_sql = frappe.db.sql
        def sql(query, args=(), **kwargs):
            if 'FROM `tabCipher Document Revision` r INNER JOIN `tabCipher Incident Evidence Registration`' in query:
                state.duplicate_queries.append(('restricted', args))
                private = {v['document_id'] for (dt,_),v in state.native.items()
                           if dt == privacy.DOCTYPE}
                return [SimpleNamespace(name=name) for name,row in metadata.revs.items()
                        if row['sha256'] == args[0] and row['document'] in private][:1]
            if 'FROM `tabCipher Document Revision` r LEFT JOIN' in query:
                state.duplicate_queries.append(('ordinary', args))
            return original_sql(query, args, **kwargs)

        def command(scope_type, **kwargs):
            actor = context.current_actor(lock=True)
            if scope_type == 'Project':
                require(kwargs['company'], kwargs['project'], kwargs['ability'], actor, True)
                require(kwargs['company'], kwargs['project'], 'document.read', actor, True)
            else:
                require_company(kwargs['company'], kwargs['ability'], actor, True)
                require_company(kwargs['company'], 'document.read', actor, True)
            return kwargs['effect'](actor, SimpleNamespace(status='Open'))

        frappe.conf.update(cipher_site_mode='synthetic', cipher_allow_unscanned_documents=1)
        adapter = importlib.import_module('cipher_aec.documents.service')
        history = importlib.import_module('cipher_aec.governance.history')
        with patch.object(frappe.db, 'sql', sql), \
             patch.object(context, 'require_project', require), \
             patch.object(context, 'require_company', require_company, create=True), \
             patch.object(commands, 'run_command', lambda **kw: command('Project', **kw)), \
             patch.object(commands, 'run_company_command', lambda **kw: command('Company', **kw), create=True), \
             patch.object(rights, 'prelock', prelock_rights), patch.object(rights, 'require', require_rights), \
             patch.object(ordinary, 'FrappeDocumentRepository', Metadata), \
             patch.object(ordinary, 'FrappeFileStorage', Storage), \
             patch.object(evidence, 'FrappeDocumentRepository', Metadata), \
             patch.object(evidence, 'FrappeFileStorage', Storage), \
             patch.object(history, 'append_company_event', lambda **kw: state.events.append(deepcopy(kw)) or uid(), create=True), \
             patch.object(adapter, '_call', ordinary._call, create=True), \
             patch.object(adapter, 'get_document', ordinary.get_document, create=True), \
             patch.dict('sys.modules', {'cipher_aec.documents.provenance': SimpleNamespace(authorize=source_authorize)}):
            state.metadata = metadata
            state.permission = add_source(state)
            state.ordinary, state.private = ordinary, evidence
            yield state, privacy


def ordinary_upload(state, content, *, kind='Project', company='C', target=None):
    values = dict(company=company, operation_id=uid(), title='Ordinary source', filename='source.txt',
                  content=content, byte_length=len(content), sha256=hashlib.sha256(content).hexdigest())
    if target: values.update(document_id=target['document']['id'], expected_revision=target['revision']['revision_number'])
    if kind == 'Project': return state.ordinary.upload_document(project='P', **values)
    return state.ordinary.upload_company_document(**values)


def private_upload(state, content, **kwargs):
    values = dict(company='C', project='P', operation_id=uid(), title='Private incident source',
                  filename='incident.txt', content_base64=base64.b64encode(content).decode(),
                  byte_length=len(content), sha256=hashlib.sha256(content).hexdigest(),
                  rights_basis='Authored private evidence permission.', permission_evidence=[state.permission])
    values.update(kwargs)
    return state.private.upload_evidence(**values)


def snapshot(state):
    return deepcopy((state.metadata.docs, state.metadata.revs, state.stored, state.native,
                     state.documents, state.events, state.receipts))


class SerialIncidentPrivacyTests(unittest.TestCase):
    def test_private_first_blocks_new_ordinary_sources_in_project_and_company(self):
        for kind, company in (('Project','C'), ('Company','C'), ('Company','OTHER')):
            with self.subTest(kind=kind, company=company), upload_fixture() as (state, privacy):
                content = b'Exact private original full bytes.'
                private = private_upload(state, content)
                before = snapshot(state)
                with self.assertRaises(DomainError) as caught:
                    ordinary_upload(state, content, kind=kind, company=company)
                self.assertEqual(caught.exception.code, 'restricted_source_already_exists')
                self.assertEqual(caught.exception.status, 409)
                for secret in (private['document']['id'], private['revision']['id'], private['registration']['id'], 'OTHER'):
                    self.assertNotIn(secret, caught.exception.message)
                self.assertEqual(snapshot(state), before)

    def test_private_first_blocks_ordinary_successor_without_reclassifying_existing_source(self):
        for kind in ('Project', 'Company'):
            with self.subTest(kind=kind), upload_fixture() as (state, privacy):
                target = ordinary_upload(state, b'Existing ordinary identity.', kind=kind)
                content = b'Private successor must not publish.'
                private_upload(state, content)
                self.assertIsNone(privacy.registration(target['document']['id']))
                before = snapshot(state)
                with self.assertRaises(DomainError) as caught:
                    ordinary_upload(state, content, kind=kind, target=target)
                self.assertEqual(caught.exception.code, 'restricted_source_already_exists')
                self.assertEqual(snapshot(state), before)
                self.assertIsNone(privacy.registration(target['document']['id']))

    def test_same_private_target_cannot_declassify_by_ordinary_successor(self):
        with upload_fixture() as (state, privacy):
            content = b'Private immutable classification.'
            target = private_upload(state, content)
            before = snapshot(state)
            with self.assertRaises(DomainError) as caught:
                ordinary_upload(state, content, target=target)
            self.assertEqual(caught.exception.code, 'restricted_source_already_exists')
            self.assertEqual(snapshot(state), before)
            self.assertEqual(privacy.registration(target['document']['id']), target['registration'])

    def test_ordinary_first_still_blocks_private_upload_in_both_source_scopes(self):
        for kind in ('Project', 'Company'):
            with self.subTest(kind=kind), upload_fixture() as (state, privacy):
                content = b'Already ordinary exact source bytes.'
                target = ordinary_upload(state, content, kind=kind)
                before = snapshot(state)
                with self.assertRaises(DomainError) as caught: private_upload(state, content)
                self.assertEqual(caught.exception.code, 'ordinary_source_already_exists')
                self.assertEqual(snapshot(state), before)
                self.assertIsNone(privacy.registration(target['document']['id']))

    def test_different_bytes_on_private_target_keep_original_private_classification(self):
        with upload_fixture() as (state, privacy):
            target = private_upload(state, b'Original private source bytes.')
            content = b'Authorized new bytes still owned by the private document.'
            successor = ordinary_upload(state, content, target=target)
            self.assertEqual(state.stored[successor['revision']['id']], content)
            self.assertEqual(successor['revision']['revision_number'], 2)
            self.assertEqual(privacy.registration(target['document']['id']), target['registration'])
            state.duties[state.actor.person_id] = {'project.read', 'document.read', 'document.write'}
            with self.assertRaises(DomainError):
                privacy.authorize_source(state.metadata.revs[successor['revision']['id']], state.actor)

    def test_nonmatching_bytes_remain_ordinary_and_exact(self):
        for kind in ('Project', 'Company'):
            with self.subTest(kind=kind), upload_fixture() as (state, privacy):
                private_upload(state, b'Known private bytes.')
                content = b'Different ordinary exact full bytes.'
                result = ordinary_upload(state, content, kind=kind)
                self.assertEqual(state.stored[result['revision']['id']], content)
                self.assertIsNone(privacy.registration(result['document']['id']))
                successor = ordinary_upload(state, content + b' next', kind=kind, target=result)
                self.assertEqual(state.stored[successor['revision']['id']], content + b' next')
                self.assertEqual(successor['revision']['revision_number'], 2)

    def test_existing_ordinary_bytes_can_keep_ordinary_identities(self):
        for kind in ('Project', 'Company'):
            with self.subTest(kind=kind), upload_fixture() as (state, privacy):
                content = b'Exact non-sensitive ordinary source bytes.'
                first = ordinary_upload(state, content, kind=kind)
                duplicate = ordinary_upload(state, content, kind=kind)
                successor = ordinary_upload(state, content, kind=kind, target=first)
                self.assertNotEqual(first['document']['id'], duplicate['document']['id'])
                self.assertEqual(successor['revision']['revision_number'], 2)
                for value in (first, duplicate, successor):
                    self.assertEqual(state.stored[value['revision']['id']], content)
                    self.assertIsNone(privacy.registration(value['document']['id']))

    def test_current_duties_and_exact_destination_scope_precede_hash_lookup(self):
        for kind in ('Project', 'Company'):
            for ability in ('document.read', 'document.write'):
                with self.subTest(kind=kind, ability=ability), upload_fixture() as (state, privacy):
                    private_upload(state, b'Known private bytes.')
                    state.duplicate_queries.clear()
                    state.blocked.add(('C', 'P' if kind == 'Project' else None, ability))
                    before = snapshot(state)
                    with self.assertRaises(DomainError): ordinary_upload(state, b'Known private bytes.', kind=kind)
                    self.assertEqual(state.duplicate_queries, [])
                    self.assertEqual(snapshot(state), before)
        with upload_fixture() as (state, privacy):
            private_upload(state, b'Known private bytes.')
            state.duplicate_queries.clear()
            with self.assertRaises(DomainError): ordinary_upload(state, b'Known private bytes.', company='WRONG')
            self.assertEqual(state.duplicate_queries, [])
        with upload_fixture() as (state, privacy):
            private_upload(state, b'Known private bytes.')
            state.duplicate_queries.clear()
            del state.users[state.actor.user]
            with self.assertRaises(DomainError): ordinary_upload(state, b'Known private bytes.')
            self.assertEqual(state.duplicate_queries, [])

    def test_current_target_ingest_rights_precede_hash_lookup(self):
        for kind in ('Project', 'Company'):
            with self.subTest(kind=kind), upload_fixture() as (state, privacy):
                target = ordinary_upload(state, b'Existing allowed ordinary source.', kind=kind)
                private_upload(state, b'Known private bytes.')
                state.rights[target['document']['id']] = 'ingest_denied'
                state.duplicate_queries.clear()
                before = snapshot(state)
                with self.assertRaises(DomainError) as caught:
                    ordinary_upload(state, b'Known private bytes.', kind=kind, target=target)
                self.assertEqual(caught.exception.code, 'source_rights_denied')
                self.assertEqual(state.duplicate_queries, [])
                self.assertEqual(snapshot(state), before)
        for kind, field in (('Project', 'project'), ('Company', 'company')):
            with self.subTest(kind=kind, field=field), upload_fixture() as (state, privacy):
                target = ordinary_upload(state, b'Exact original scope.', kind=kind)
                private_upload(state, b'Known private bytes.')
                state.metadata.docs[target['document']['id']][field] = 'OTHER'
                state.duplicate_queries.clear()
                before = snapshot(state)
                with self.assertRaises(DomainError) as caught:
                    ordinary_upload(state, b'Known private bytes.', kind=kind, target=target)
                self.assertEqual(caught.exception.code, 'not_found')
                self.assertEqual(state.duplicate_queries, [])
                self.assertEqual(snapshot(state), before)

    def test_existing_target_scope_and_private_read_duty_precede_hash_lookup(self):
        with upload_fixture() as (state, privacy):
            target = private_upload(state, b'Private exact source.')
            state.duties[state.actor.person_id] = {'project.read', 'document.read', 'document.write'}
            state.duplicate_queries.clear()
            before = snapshot(state)
            with self.assertRaises(DomainError): ordinary_upload(state, b'Private exact source.', target=target)
            self.assertEqual(state.duplicate_queries, [])
            self.assertEqual(snapshot(state), before)
        for kind, other in (('Project','Company'), ('Company','Project')):
            with self.subTest(kind=kind), upload_fixture() as (state, privacy):
                target = ordinary_upload(state, b'Original scope.', kind=other)
                private_upload(state, b'Known private bytes.')
                state.duplicate_queries.clear()
                before = snapshot(state)
                with self.assertRaises(DomainError) as caught:
                    ordinary_upload(state, b'Known private bytes.', kind=kind, target=target)
                self.assertEqual(caught.exception.code, 'not_found')
                self.assertEqual(state.duplicate_queries, [])
                self.assertEqual(snapshot(state), before)

    def test_private_permission_evidence_requires_current_rights_bytes_and_exact_project(self):
        for fault in ('ingest_denied', 'expired', 'wrong_project', 'stale_bytes', 'not_current'):
            with self.subTest(fault=fault), upload_fixture() as (state, privacy):
                source = state.documents[state.permission['revision_id']]
                if fault in ('ingest_denied', 'expired'): state.rights[source['document_id']] = fault
                elif fault == 'wrong_project': source['project'] = 'OTHER'
                elif fault == 'stale_bytes': source['content'] += b' changed'
                else: source['is_current'] = False
                before = snapshot(state)
                with self.assertRaises(DomainError): private_upload(state, b'New restricted original.')
                self.assertEqual(snapshot(state), before)

    def test_missing_additive_registration_doctype_preserves_ordinary_upload(self):
        with upload_fixture() as (state, privacy):
            frappe = importlib.import_module('frappe')
            original = frappe.db.exists
            with patch.object(frappe.db, 'exists', lambda dt,name: False if (dt,name) == ('DocType',privacy.DOCTYPE) else original(dt,name)):
                result = ordinary_upload(state, b'Ordinary before additive migration.')
            self.assertEqual(state.stored[result['revision']['id']], b'Ordinary before additive migration.')
            self.assertEqual(state.duplicate_queries, [])


if __name__ == '__main__': unittest.main()
