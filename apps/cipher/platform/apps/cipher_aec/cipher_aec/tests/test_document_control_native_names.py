"""Actual DOC02 name compatibility with explicit host persistence doubles.

Uploads and byte reads use DocumentService; these are not native Frappe proofs.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.documents.core import DocumentService
from cipher_aec.documents.storage import LocalArtifactStorage
from cipher_aec.tests.test_document_control import authorize, permission, person
from cipher_aec.tests.test_document_control_lifecycle import lifecycle_fixture, issue, request
from cipher_aec.tests.test_documents import MemoryMetadata
from cipher_aec.tests.test_engineering import uid

ROOT = Path(__file__).parents[1]
SCHEMAS = [json.loads((ROOT / name).read_text()) for name in
           ('document_control/schemas/api-v1.schema.json', 'api/schema.json')]
NATIVE_NAMES = (
    ('DcIssuedStandingRequest', 'document_id'),
    ('DcRequestLifecycleRequest', 'document_id'),
    ('DcIssuedStandingBody', 'document_id'),
    ('DcIssuedStanding', 'document_id'),
    ('DcLifecycleRequest', 'parent_id'),
    ('DcLifecycle', 'document_id'),
    ('DcLifecycle', 'parent_id'),
    ('DcIssueReference', 'revision_id'),
)


def validate(name, value):
    for schema in SCHEMAS:
        Draft202012Validator({'$ref': '#/$defs/' + name, '$defs': schema['$defs']},
                            format_checker=FormatChecker()).validate(value)


def validate_approval(state, rules, value, fact):
    native = state.packets[fact['packet_id']]
    packet = {'schema': 'cipher.document.approval.v1', 'id': native.name,
              'company': 'C', 'project': 'P', 'action': rules.ACTIONS['lifecycle_request'],
              'subject': {'id': value['id'], 'type': rules.KINDS['lifecycle_request'], 'label': 'Native source lifecycle'},
              'requester': {'id': state.actor.person_id, 'display_name': 'Author'},
              'created_at': '2026-10-17T00:00:00Z', 'expires_at': '2026-10-18T00:00:00Z',
              'manifest_hash': native.manifest_hash, 'source_version': digest(value),
              'policy': {'id': 'policy', 'label': 'Independent lifecycle review', 'synthetic': True},
              'state': 'Consumed', 'decisions': [],
              'actions': {'can_decide': False, 'can_execute': False, 'can_withdraw': False, 'disabled_reason': 'Consumed'},
              'review_manifest': json.loads(native.manifest_json)['domain']}
    core = SCHEMAS[1]
    for name, result in (('ApprovalPacket', packet),
                         ('DocumentApprovalExecutionResponse', {'packet': packet, 'effect': {'lifecycle': fact},
                          'operation': {'id': uid(), 'status': 'succeeded', 'replayed': False}})):
        Draft202012Validator({'$ref': '#/$defs/' + name, '$defs': core['$defs']},
                            format_checker=FormatChecker()).validate(result)


@contextmanager
def uploaded_fixture():
    with lifecycle_fixture() as values, tempfile.TemporaryDirectory() as folder:
        state, rules, repo, rights, service, gov, life = values
        metadata = MemoryMetadata()
        core = DocumentService(metadata, LocalArtifactStorage(folder),
                               lambda c, p, ability: service.require_project(c, p, ability=ability),
                               scanner=SimpleNamespace(scan=lambda content, mime: 'clean'))
        original_source = service.sources.source_reference

        def source_reference(company, project, revision, page, actor=None, lock=False):
            if revision not in metadata.revs:
                return original_source(company, project, revision, page, actor=actor, lock=lock)
            service.require_project(company, project, ability='document.read', actor=actor)
            if revision in state.denied:
                raise DomainError('source_denied', 'Current source access denied.', 403)
            return core.source_reference(company, project, revision, page, lock=lock)

        def upload(content=b'Exact original documentary source.', **changes):
            made = core.upload(company='C', project='P', title='Native named source',
                               filename='source.txt', content=content, byte_length=len(content),
                               sha256=hashlib.sha256(content).hexdigest(), **changes)
            revision = made['revision']['id']
            state.documents[revision] = core.source_reference('C', 'P', revision, 1)
            if rights.current(made['document']['id']) is None:
                service.set_rights('C', 'P', uid(), made['document']['id'], None, permission(state))
            return made, {'revision_id': revision, 'source_sha256': made['revision']['sha256']}

        with patch.object(service.sources, 'source_reference', source_reference):
            yield (*values, core, metadata, upload)


class NativeDocumentLifecycleTests(unittest.TestCase):
    def test_actual_doc02_upload_withdraws_and_replays_exact_request(self):
        with uploaded_fixture() as (s, r, repo, rights, service, gov, life, core, metadata, upload):
            made, ref = upload()
            doc, revision = made['document']['id'], made['revision']['id']
            self.assertTrue(doc.startswith('DOC-'))
            self.assertTrue(revision.startswith('REV-'))
            checker = person(s, r, 'checker')
            original = issue(s, r, service, gov, checker, ref)
            before = life.get_standing('C', 'P', doc)
            value = request(s, life, doc, original)
            fact = authorize(s, r, gov, 'lifecycle_request', value, checker)
            self.assertEqual(life.standing('C', 'P', doc, s.actor)['status'], 'withdrawn')
            operation = next(key[1] for key, (_, result) in s.receipts.items()
                             if result.get('lifecycle_request') == value)
            replay = life.request('C', 'P', operation, doc, value['expected_version'], value['definition'])
            self.assertTrue(replay['operation']['replayed'])
            self.assertEqual(replay['lifecycle_request'], value)
            self.assertEqual(service.read('lifecycle', fact['id'], 'C', 'P', s.actor), fact)
            validate_approval(s, r, value, fact)
            self.assertEqual(core.download('C', revision)[1], b'Exact original documentary source.')
            for name, result in (
                ('DcIssuedStandingRequest', {'company': 'C', 'project': 'P', 'document_id': doc}),
                ('DcIssuedStandingResponse', before),
                ('DcRequestLifecycleRequest', {'company': 'C', 'project': 'P', 'operation_id': operation,
                 'document_id': doc, 'expected_version': value['expected_version'], 'definition': value['definition']}),
                ('DcLifecycleRequest', value), ('DcLifecycle', fact),
                ('DcRequestLifecycleResponse', replay),
                ('DcIssuedStandingResponse', life.get_standing('C', 'P', doc)),
                ('DcGetResponse', service.get_record('C', 'P', 'lifecycle', fact['id'])),
            ):
                with self.subTest(contract=name):
                    validate(name, result)
            with self.assertRaises(DomainError) as error:
                service.create_transmittal('C', 'P', uid(), original['id'], digest(original),
                                          [checker.user], 'Withdrawn source', '')
            self.assertEqual(error.exception.code, 'issued_content_not_current')

    def test_actual_doc02_successor_supersedes_then_withdraws_without_rewriting_originals(self):
        with uploaded_fixture() as (s, r, repo, rights, service, gov, life, core, metadata, upload):
            made, ref = upload()
            doc, old_revision = made['document']['id'], made['revision']['id']
            checker = person(s, r, 'checker')
            original = issue(s, r, service, gov, checker, ref)
            successor, replacement_ref = upload(b'Exact successor documentary source.', document_id=doc, expected_revision=1)
            replacement = issue(s, r, service, gov, checker, replacement_ref)
            before = deepcopy(s.rows)
            value = request(s, life, doc, original, replacement=replacement)
            superseded = authorize(s, r, gov, 'lifecycle_request', value, checker)
            standing = life.get_standing('C', 'P', doc)
            self.assertEqual(standing['standing']['original_issued']['revision_id'], old_revision)
            self.assertEqual(standing['standing']['current_issued']['revision_id'], successor['revision']['id'])
            self.assertEqual(metadata.document(doc)['current_revision'], successor['revision']['id'])
            validate('DcLifecycleRequest', value)
            validate('DcLifecycle', superseded)
            validate_approval(s, r, value, superseded)
            validate('DcIssuedStandingResponse', standing)
            with self.assertRaises(DomainError) as error:
                service.create_transmittal('C', 'P', uid(), original['id'], digest(original),
                                          [checker.user], 'Superseded source', '')
            self.assertEqual(error.exception.code, 'issued_content_not_current')
            withdrawn_request = request(s, life, doc, replacement)
            withdrawn = authorize(s, r, gov, 'lifecycle_request', withdrawn_request, checker)
            validate_approval(s, r, withdrawn_request, withdrawn)
            self.assertEqual(life.standing('C', 'P', doc, s.actor)['status'], 'withdrawn')
            for name, result in (('DcLifecycleRequest', withdrawn_request), ('DcLifecycle', withdrawn),
                                 ('DcIssuedStandingResponse', life.get_standing('C', 'P', doc))):
                validate(name, result)
            self.assertEqual(service.read('lifecycle', superseded['id'], 'C', 'P', s.actor), superseded)
            self.assertEqual(service.read('issue', original['id'], 'C', 'P', s.actor), original)
            self.assertTrue(all(s.rows[key] == row for key, row in before.items()))
            self.assertEqual(core.download('C', old_revision)[1], b'Exact original documentary source.')
            s.denied.add(old_revision)
            with self.assertRaises(DomainError):
                service.read('lifecycle', superseded['id'], 'C', 'P', s.actor)
            self.assertEqual(repo.raw('lifecycle', superseded['id']), superseded)

    def test_native_revision_reference_accepts_upload_name_and_keeps_issue_uuid_strict(self):
        with uploaded_fixture() as (s, r, repo, rights, service, gov, life, core, metadata, upload):
            made, ref = upload()
            original = issue(s, r, service, gov, person(s, r, 'checker'), ref)
            reference = life.issue_ref(original, made['document']['id'])
            life._reference(reference)
            for name in ('', 'REV-' + 'a' * 137, None):
                with self.subTest(revision=name), self.assertRaises(DomainError):
                    life._reference({**reference, 'revision_id': name})
            with self.assertRaises(DomainError):
                life._reference({**reference, 'issue_id': made['document']['id']})
            definition = {'action': 'withdraw', 'issue_id': made['document']['id'],
                          'issue_digest': digest(original), 'replacement_issue_id': None,
                          'replacement_issue_digest': None, 'reason': 'Invalid documentary UUID'}
            with self.assertRaises(DomainError):
                life.definition(definition)


class NativeDocumentSchemaTests(unittest.TestCase):
    def test_actual_upload_standing_matches_domain_and_core_contracts(self):
        with uploaded_fixture() as (s, r, repo, rights, service, gov, life, core, metadata, upload):
            made, ref = upload()
            issue(s, r, service, gov, person(s, r, 'checker'), ref)
            validate('DcIssuedStandingResponse', life.get_standing('C', 'P', made['document']['id']))

    def test_only_native_name_properties_use_bounded_text_and_documentary_ids_remain_uuid(self):
        for index, schema in enumerate(SCHEMAS):
            for name, key in NATIVE_NAMES:
                prop = schema['$defs'][name]['properties'][key]
                with self.subTest(schema=index, definition=name, property=key):
                    self.assertEqual(prop, {'type': 'string', 'minLength': 1, 'maxLength': 140})
                    validator = Draft202012Validator(prop, format_checker=FormatChecker())
                    for valid in ('a', 'DOC-' + 'a' * 136, 'REV-' + 'b' * 136, uid()):
                        validator.validate(valid)
                    for invalid in ('', 'DOC-' + 'a' * 137, None, 1):
                        with self.assertRaises(ValidationError):
                            validator.validate(invalid)
            for name, key in (('DcIssueReference', 'issue_id'), ('DcLifecycleEventReference', 'id'),
                              ('DcLifecycleDefinition', 'issue_id'), ('DcLifecycleRequest', 'id'),
                              ('DcLifecycle', 'id'), ('DcLifecycle', 'subject_id'),
                              ('DcRequestLifecycleRequest', 'operation_id')):
                with self.subTest(schema=index, definition=name, property=key):
                    prop = schema['$defs'][name]['properties'][key]
                    self.assertEqual(prop, {'type': 'string', 'format': 'uuid'})
                    validator = Draft202012Validator(prop, format_checker=FormatChecker())
                    validator.validate(uid())
                    with self.assertRaises(ValidationError):
                        validator.validate('DOC-' + 'a' * 32)
        effect = SCHEMAS[1]['$defs']['DocumentLifecycleRequestApprovalPacket']['properties']['review_manifest']['properties']['effect']['properties']
        self.assertEqual(effect['document_id'], {'type': 'string', 'minLength': 1, 'maxLength': 140})
        self.assertEqual(effect['subject_id'], {'type': 'string', 'format': 'uuid'})
        validator = Draft202012Validator(effect['document_id'], format_checker=FormatChecker())
        validator.validate('DOC-' + 'a' * 136)
        for invalid in ('', 'DOC-' + 'a' * 137, None, 1):
            with self.assertRaises(ValidationError):
                validator.validate(invalid)


if __name__ == '__main__':
    unittest.main()
