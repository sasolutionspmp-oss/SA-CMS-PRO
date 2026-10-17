"""Actual DOC02 clause names with explicit host persistence/session doubles."""
from contextlib import contextmanager
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_document_control import authorize, person
from cipher_aec.tests.test_document_control_native_names import uploaded_fixture
from cipher_aec.tests.test_engineering import uid

ROOT = Path(__file__).parents[1]
SCHEMAS = [json.loads((ROOT / name).read_text()) for name in
           ('document_control/schemas/api-v1.schema.json', 'api/schema.json')]


def validate(name, value, schemas=SCHEMAS):
    for schema in schemas:
        Draft202012Validator({'$ref': '#/$defs/' + name, '$defs': schema['$defs']},
                            format_checker=FormatChecker()).validate(value)


@contextmanager
def clause_fixture():
    with uploaded_fixture() as values:
        state, rules, repo, rights, service, gov, life, core, metadata, upload = values
        clauses = importlib.import_module('cipher_aec.document_control.clauses')
        documents = sys.modules['cipher_aec.documents.service']
        original_citation = documents.get_citation

        def citation(company, revision, page, excerpt_sha256=None, actor=None):
            if revision not in metadata.revs:
                return original_citation(company, revision, page, excerpt_sha256, actor=actor)
            service.require_project(company, 'P', ability='document.read', actor=actor)
            if revision in state.denied:
                raise DomainError('source_denied', 'Current original source denied.', 403)
            return core.citation(company, revision, page, excerpt_sha256)

        with patch.object(documents, 'get_citation', citation), \
             patch.object(service.FrappeDocumentRepository, 'revision', lambda _, name, lock=False: metadata.revision(name, lock)):
            yield (*values, clauses)


def prepare(state, rules, service, gov, core, upload, clauses):
    made, source = upload(b'Exact adopted original clause wording.')
    created = service.create_library('C', 'P', uid(),
        {'title': 'Native original clause', 'category': 'contract_clause', 'discipline': 'Civil',
         'ownership': 'Synthetic source owner', 'tags': [], 'change_reason': 'Retain exact original'}, source)
    request = service.create_adoption('C', 'P', uid(), created['library_revision']['id'],
        digest(created['library_revision']), {'purpose': 'Use exact clause', 'target_locator': 'Clause 3',
        'change_reason': 'Independent reference'})['adoption_request']
    checker = person(state, rules, 'independent-clause-checker')
    adoption = authorize(state, rules, gov, 'adoption_request', request, checker)
    target_made, target_source = upload(b'Immutable document target wording.')
    snapshot = clauses.read_target('C', 'P', 'document_revision', target_source['revision_id'])['target']
    target = {**{key: snapshot[key] for key in ('kind', 'id', 'record_digest')}, 'locator': 'Clause 3'}
    citation = core.citation('C', source['revision_id'], 1)
    reference = {key: citation[key] for key in ('revision_id', 'source_sha256', 'page', 'excerpt_sha256')}
    reference.update(start=0, end=len(citation['excerpt']))
    return adoption, reference, target, snapshot, checker, made, target_made


class NativeClauseRuntimeTests(unittest.TestCase):
    def test_actual_revision_source_and_document_target_accept_native_names(self):
        with clause_fixture() as (s, r, repo, rights, service, gov, life, core, metadata, upload, clauses):
            adoption, reference, target, snapshot, checker, made, target_made = prepare(s, r, service, gov, core, upload, clauses)
            self.assertTrue(reference['revision_id'].startswith('REV-'))
            self.assertTrue(target['id'].startswith('REV-'))
            self.assertTrue(snapshot['parent_id'].startswith('DOC-'))
            r.clause_source(reference)
            r.clause_target(target)
            quoted = clauses.quoted_source('C', 'P', reference, adoption['artifacts'], s.actor)
            self.assertEqual(quoted['text'], 'Exact adopted original clause wording.')
            for value in ('', 'REV-' + 'a' * 137, None):
                with self.subTest(value=value), self.assertRaises(DomainError):
                    r.clause_source({**reference, 'revision_id': value})
                with self.subTest(value=value), self.assertRaises(DomainError):
                    r.clause_target({**target, 'id': value})
            for kind in ('proposal_revision', 'contract_revision'):
                r.clause_target({**target, 'kind': kind, 'id': uid()})
                with self.subTest(kind=kind), self.assertRaises(DomainError):
                    r.clause_target({**target, 'kind': kind})

    def test_actual_clause_redline_approval_and_replay_preserve_native_target_and_original(self):
        with clause_fixture() as (s, r, repo, rights, service, gov, life, core, metadata, upload, clauses):
            adoption, reference, target, snapshot, checker, made, target_made = prepare(s, r, service, gov, core, upload, clauses)
            before_metadata = deepcopy((metadata.docs, metadata.revs))
            operation = uid()
            result = clauses.create_clause_use('C', 'P', operation, adoption['id'], digest(adoption),
                reference, target, 'Reference exact native clause')
            use = result['clause_use']
            validate('DcCreateClauseUseRequest', {'company': 'C', 'project': 'P', 'operation_id': operation,
                'adoption_id': adoption['id'], 'adoption_digest': digest(adoption), 'source_clause': reference,
                'target': target, 'purpose': 'Reference exact native clause'})
            validate('DcCreateClauseUseResponse', result)
            value = clauses.create_redline('C', 'P', uid(), use['id'], digest(use), None,
                'Proposed independently reviewed wording.', 'Explicit proposed clause relationship')['redline']
            fact = authorize(s, r, gov, 'redline', value, checker)
            for kind, record in (('clause_use', use), ('redline', value), ('clause_application', fact)):
                validate('DcGetResponse', service.get_record('C', 'P', kind, record['id']))
            native = s.packets[fact['packet_id']]
            packet = {'schema': 'cipher.document.approval.v1', 'id': native.name, 'company': 'C', 'project': 'P',
                'action': r.ACTIONS['redline'], 'subject': {'id': value['id'], 'type': r.KINDS['redline'], 'label': 'Exact native clause'},
                'requester': {'id': s.actor.person_id, 'display_name': 'Author'}, 'created_at': '2026-10-17T00:00:00Z',
                'expires_at': '2026-10-18T00:00:00Z', 'manifest_hash': native.manifest_hash, 'source_version': digest(value),
                'policy': {'id': 'policy', 'label': 'Independent clause review', 'synthetic': True}, 'state': 'Consumed',
                'decisions': [], 'actions': {'can_decide': False, 'can_execute': False, 'can_withdraw': False, 'disabled_reason': 'Consumed'},
                'review_manifest': json.loads(native.manifest_json)['domain']}
            validate('ApprovalPacket', packet, SCHEMAS[1:])
            validate('DocumentApprovalExecutionResponse', {'packet': packet, 'effect': {'clause_application': fact},
                'operation': {'id': uid(), 'status': 'succeeded', 'replayed': False}}, SCHEMAS[1:])
            replay = clauses.create_clause_use('C', 'P', operation, adoption['id'], digest(adoption),
                reference, target, 'Reference exact native clause')
            self.assertTrue(replay['operation']['replayed'])
            self.assertEqual(replay['clause_use'], use)
            self.assertEqual((metadata.docs, metadata.revs), before_metadata)
            self.assertEqual(core.download('C', reference['revision_id'])[1], b'Exact adopted original clause wording.')
            self.assertEqual(core.download('C', target['id'])[1], b'Immutable document target wording.')
            self.assertFalse(fact['target_changed'])
            self.assertFalse(fact['commercial_execution'])
            s.denied.add(reference['revision_id'])
            with self.assertRaises(DomainError):
                service.read('clause_use', use['id'], 'C', 'P', s.actor)
            self.assertEqual(repo.raw('clause_use', use['id']), use)


class NativeClauseWireTests(unittest.TestCase):
    def test_actual_target_reader_response_and_clause_reference_match_both_contracts(self):
        with clause_fixture() as (s, r, repo, rights, service, gov, life, core, metadata, upload, clauses):
            adoption, reference, target, snapshot, checker, made, target_made = prepare(s, r, service, gov, core, upload, clauses)
            validate('DcClauseSourceReference', reference)
            validate('DcClauseTarget', target)
            validate('DcClauseTargetSnapshot', snapshot)
            validate('DcReadClauseTargetRequest', {'company': 'C', 'project': 'P', 'kind': target['kind'], 'record_id': target['id']})
            validate('DcClauseTargetResponse', {'target': snapshot})

    def test_conditional_target_contracts_keep_commercial_revision_ids_uuid_and_shapes_closed(self):
        for kind in ('proposal_revision', 'contract_revision', 'document_revision'):
            identifier = 'REV-' + 'a' * 32 if kind == 'document_revision' else uid()
            target = {'kind': kind, 'id': identifier, 'record_digest': '1' * 64, 'locator': 'Clause 3'}
            request = {'company': 'C', 'project': 'P', 'kind': kind, 'record_id': identifier}
            snapshot = {'kind': kind, 'id': identifier, 'record_digest': '1' * 64, 'parent_id': 'DOC-' + 'b' * 32,
                        'company': 'C', 'project': None if kind == 'proposal_revision' else 'P',
                        'scope_type': 'Company' if kind == 'proposal_revision' else 'Project'}
            for name, good, key in (('DcClauseTarget', target, 'id'), ('DcReadClauseTargetRequest', request, 'record_id'),
                                    ('DcClauseTargetSnapshot', snapshot, 'id')):
                with self.subTest(kind=kind, contract=name):
                    validate(name, good)
                    for invalid in ('', 'REV-' + 'a' * 137, None, 1):
                        for schema in SCHEMAS:
                            with self.assertRaises(ValidationError):
                                validate(name, {**good, key: invalid}, [schema])
                    for schema in SCHEMAS:
                        with self.assertRaises(ValidationError):
                            validate(name, {**good, 'injected': True}, [schema])
                        if kind != 'document_revision':
                            with self.assertRaises(ValidationError):
                                validate(name, {**good, key: 'REV-' + 'a' * 32}, [schema])
            if kind == 'document_revision':
                for name, good, key in (('DcClauseTarget', target, 'id'), ('DcReadClauseTargetRequest', request, 'record_id'),
                                        ('DcClauseTargetSnapshot', snapshot, 'id'), ('DcClauseTargetSnapshot', snapshot, 'parent_id')):
                    validate(name, {**good, key: 'a' * 140})
        for schema in SCHEMAS:
            for name, key in (('DcClauseUse', 'id'), ('DcClauseUse', 'adoption_id'), ('DcRedline', 'id'),
                              ('DcRedline', 'clause_use_id'), ('DcClauseApplication', 'id'),
                              ('DcClauseApplication', 'subject_id'), ('DcCreateClauseUseRequest', 'operation_id')):
                prop = schema['$defs'][name]['properties'][key]
                self.assertEqual(prop, {'type': 'string', 'format': 'uuid'})


if __name__ == '__main__':
    unittest.main()
