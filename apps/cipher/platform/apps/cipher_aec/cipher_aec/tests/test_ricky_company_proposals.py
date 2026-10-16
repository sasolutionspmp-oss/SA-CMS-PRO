"""Focused Company proposal regressions; explicit fixtures, never a native proof."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from cipher_aec.ricky.aec_contracts import SourceReference
from cipher_aec.ricky.company_contracts import decode_run_authority
from cipher_aec.ricky.contracts import canonical, digest, RickyError
from cipher_aec.tests.test_estimating_core import identity
from cipher_aec.tests.test_ricky_company_service import CompanyFixtureBoundary
from cipher_aec.tests.test_ricky_company_service import CompanyFixtureStore, CompanyFixtureReader
from cipher_aec.ricky.company_proposal_contracts import (DeterministicProposalRequest, validate_manifest, validate_preparation, MANIFEST_SCHEMA)
from cipher_aec.ricky.company_proposal_backend import CompanyProposalBackend, ProposalAECReader, _discovered
from cipher_aec.ricky.company_proposal_service import CompanyProposalService, CompanyProposalExecution, validate_start_receipt
from cipher_aec.api.errors import DomainError


class ProposalContracts(unittest.TestCase):
    def test_new_literal_cannot_enter_read_registry_or_become_a_project_model_run(self):
        from cipher_aec.ricky.company_proposal_contracts import DeterministicProposalRequest, PROPOSAL_KIND
        from cipher_aec.ricky.company_proposal_service import proposal_registry
        from cipher_aec.ricky.company_service import read_registry
        self.assertEqual({row['name'] for row in proposal_registry().schemas()}, {'aec.scope.draft', 'aec.estimate.draft'})
        self.assertTrue(all(row['effect_class'] == 'proposal' for row in proposal_registry().schemas()))
        self.assertFalse({row['name'] for row in proposal_registry().schemas()} & {row['name'] for row in read_registry().schemas()})
        request = scope_request(CompanyFixtureBoundary())
        self.assertEqual(DeterministicProposalRequest.from_value(request.binding()).binding(), request.binding())
        boundary = CompanyFixtureBoundary()
        authority = boundary.bind('Explicit EST fixture', request, identity('r14-run'))
        run = dict(id=authority.run_id, scope_type='Company', project=None, company=authority.company,
            user=authority.user, person=authority.person, authority=authority.binding(), request_kind=PROPOSAL_KIND,
            original_session_reference=authority.session_reference, request=request.binding())
        self.assertEqual(decode_run_authority(run), authority)
        run['request_kind'] = 'deterministic-read-v1'
        with self.assertRaises(RickyError): decode_run_authority(run)


def scope_request(boundary):
    from cipher_aec.ricky.company_proposal_contracts import DeterministicProposalRequest
    citation = boundary.fixture.citation_value
    ref = SourceReference(citation['id'], citation['revision_id'], citation['page'], citation['excerpt_sha256'], citation['source_sha256'])
    return DeterministicProposalRequest(identity('pursuit'), 'aec.scope.draft', canonical({
        'proposal_revision_id': boundary.fixture.proposal_revision_value['id'],
        'sections': [{'heading': 'Suggested scope', 'text': 'Author supplied suggestion.', 'citation_ids': [ref.citation_id]}],
        'unverified_claims': ['Review scope.']}), (ref,), ())


def estimate_request(boundary, *, measurement=False):
    reference = scope_request(boundary).sources
    unit = boundary.fixture.records['line', boundary.fixture.line_id]['authored']['quantity']['unit_id']
    return DeterministicProposalRequest(identity('pursuit'), 'aec.estimate.draft', canonical({
        'base_revision_id': boundary.fixture.revision_id, 'selections': [{'line_record_id': boundary.fixture.line_id,
            'source_kind': 'measurement' if measurement else 'estimate-line',
            'source_id': boundary.fixture.measurement_id if measurement else boundary.fixture.line_id, 'target_unit_id': unit}],
        'notes': 'Unverified authored estimate notes.', 'citation_ids': [reference[0].citation_id], 'unverified_claims': []}),
        reference, (boundary.fixture.measurement_id,) if measurement else ())


class ProposalFixtureReader(ProposalAECReader):
    actor = CompanyFixtureReader.actor
    pursuit = CompanyFixtureReader.pursuit
    raw_sources = CompanyFixtureReader.raw_sources
    raw_records = CompanyFixtureReader.raw_records
    citation = CompanyFixtureReader.citation

    def proposal_revision(self, context, record_id, actor):
        value = self.boundary.fixture.proposal_revision(context, record_id, actor)
        self._observe('commercial', 'proposal-revision', value)
        return value

    def proposal(self, context, record_id, actor):
        value = self.boundary.fixture.proposal(context, record_id, actor)
        return self._owner('commercial', 'proposal', value)

    def raw_proposal(self, context, revision, actor):
        self.boundary.fixture.raw_proposal(context, revision, actor)

    def record(self, context, kind, record_id, actor):
        value = self.boundary.fixture.record(context, kind, record_id, actor)
        if kind == 'estimate': self._owner('estimate', 'estimate', value)
        else: self._observe('estimate', kind, value)
        return value

    def dependency(self, domain, kind, name, actor):
        if domain == 'commercial': return self.proposal_revision(self.context, name, actor)
        if domain == 'estimate': return self.record(self.context, kind, name, actor)
        if kind == 'measurement':
            value = deepcopy(self.boundary.fixture.measurement_value)
        else:
            value = deepcopy(self.boundary.takeoff[kind, name])
        self._observe(domain, kind, value)
        return value

    def measurement(self, context, record_id, actor):
        value = self._measurement(record_id, actor)
        current = deepcopy(self.boundary.fixture.current)
        self.standing[record_id] = {'measurement_id': record_id, 'eligible': current['eligible'],
            'verification_id': current['verification']['id'] if current.get('verification') else None, 'digest': digest(current)}
        return value, current

    def current_units(self, context, records, actor):
        for row in records: self.qualified[row['id']] = {'id': row['id'], 'digest': digest(row)}
        return self.boundary.fixture.current_units(context, records, actor)

    def measurement_sources(self, context, value, actor):
        return self.boundary.fixture.measurement_sources(context, value, actor)

    def verify_original(self, manifest):
        validate_manifest(manifest, self.request)
        actor = self.boundary.authorize(self.authority, execution=self.execution, lock=self.lock)
        for ability in ('ricky.run', 'commercial.read', 'document.read'):
            self.boundary.require_ability(ability)
        if self.request.action == 'aec.estimate.draft': self.boundary.require_ability('estimate.read')
        if not self.boundary.fixture.native_allowed or not self.boundary.fixture.source_allowed:
            raise RickyError('not_found', 'Explicit original source/native denial')
        originals = self.boundary.originals()
        for row in manifest['records']:
            if digest(originals[row['domain'], row['kind'], row['id']]) != row['digest']:
                raise RickyError('source_integrity', 'Explicit immutable source mismatch')
        for row in manifest['owners']:
            value = self.boundary.fixture.proposal_value if row['domain'] == 'commercial' else self.boundary.fixture.records['estimate', row['id']]
            pursuit = value.get('pursuit') if row['domain'] == 'commercial' else value['pursuit_id']
            if pursuit != self.context.pursuit_id or value['company'] != self.context.company:
                raise RickyError('not_found', 'Explicit original owner mismatch')
        if canonical(self._selected(actor)) != canonical(manifest['citations']):
            raise RickyError('source_integrity', 'Explicit selected source mismatch')
        return originals


class ProposalBoundary(CompanyFixtureBoundary, CompanyProposalBackend):
    def __init__(self):
        super().__init__()
        self.takeoff = {}

    def originals(self):
        values = {('estimate', kind, name): deepcopy(value) for (kind, name), value in self.fixture.records.items() if kind != 'estimate'}
        values['commercial', 'proposal-revision', self.fixture.proposal_revision_value['id']] = deepcopy(self.fixture.proposal_revision_value)
        values['takeoff', 'measurement', self.fixture.measurement_id] = deepcopy(self.fixture.measurement_value)
        values.update({('takeoff', kind, name): deepcopy(value) for (kind, name), value in self.takeoff.items()})
        values['documents', 'citation', self.fixture.citation_value['id']] = deepcopy(self.fixture.citation_value)
        return values

    def reader(self, authority, request, lock=False, execution=True):
        return ProposalFixtureReader(self, authority, request, lock=lock, execution=execution)

    @contextmanager
    def source_scope(self, authority, request, manifest=None, lock=False, execution=False, expected_plan=None):
        self.authorize(authority, execution=execution, lock=lock)
        plan = {'unit_ids': [], 'currencies': [], 'native_refs': [], 'generated_sources': []}
        if self.growing_plan and expected_plan is not None: raise RickyError('stale_source', 'Explicit growing source union')
        keys = [('commercial', 'proposal-revision', self.fixture.proposal_revision_value['id'])] if request.action == 'aec.scope.draft' else [
            ('estimate', kind, name) for kind, name in self.fixture.records if kind != 'estimate']
        keys += [('takeoff', 'measurement', name) for name in request.measurement_ids]
        self.events.extend(['Discovery', 'UOM', 'Currency', 'Native'])
        token = _discovered.set((canonical(authority.binding()), tuple(sorted(keys)), plan))
        try: yield plan
        finally: _discovered.reset(token)


class ProposalServiceTests(unittest.TestCase):
    def setUp(self):
        self.boundary = ProposalBoundary()
        self.store = CompanyFixtureStore(self.boundary.events)
        self.store.originals = self.boundary.fixture.records
        self.now = datetime(2026, 10, 16, tzinfo=timezone.utc)
        self.service = CompanyProposalService(self.store, self.boundary, clock=lambda: self.now)
        from cipher_aec.ricky import company_proposal_records, company_proposal_service
        self.addCleanup(patch.stopall)
        # Match the controller helper exactly: these are immutable record reads,
        # not the authorized citation objects returned by the backend boundary.
        originals = lambda run: {key: value for key, value in self.boundary.originals().items() if key[0] in {'estimate', 'takeoff'}}
        patch.object(company_proposal_records, 'preparation_originals', side_effect=originals).start()
        patch.object(company_proposal_service, 'preparation_originals', side_effect=originals).start()

    def start(self, request=None):
        dto = self.service.start_proposal('Explicit EST fixture', (request or scope_request(self.boundary)).binding(), identity('r14-operation'))
        run = self.store.get('run', dto['id'])
        self.boundary.receipts[run['start_receipt']] = run['id']
        return run, dto

    def prepare(self, request=None):
        run, dto = self.start(request)
        claimed, token = self.service.claim(run['id'])
        request = DeterministicProposalRequest.from_value(claimed['request'])
        output = CompanyProposalExecution(self.service, run['id'], token).invoke(request.action, json.loads(request.arguments_json), 'selected-deterministic-proposal')
        return self.store.get('run', run['id']), token, output, dto

    def test_scope_persists_separate_genuine_wrapper_without_mutating_draft_observation(self):
        run, dto = self.start(); self.service.process(run['id'])
        terminal = self.service.get_run(run['company'], run['id'])
        self.assertEqual(terminal['status'], 'waiting-for-review')
        proposal = self.service.get_proposal(run['company'], terminal['result']['proposal_id'])
        invocation = self.store.find('invocation', {})[0]
        self.assertEqual(canonical(proposal['preparation']), canonical(invocation['output']))
        self.assertIs(proposal['persistent'], True); self.assertIs(proposal['preparation']['persistent'], False)
        self.assertEqual(proposal['invocation_id'], invocation['id']); self.assertEqual(proposal['step_id'], invocation['step_id'])
        self.assertEqual(proposal['expires_at'], run['deadline'])
        self.assertFalse({'authority', 'session_reference', 'user', 'person', 'operation_key'} & set(proposal))
        validate_start_receipt(self.store.get('run', run['id']), dto)

    def test_estimate_rational_quantity_is_original_and_no_domain_writer_exists(self):
        run, _ = self.start(estimate_request(self.boundary)); self.service.process(run['id'])
        result = self.service.get_run(run['company'], run['id'])
        proposal = self.service.get_proposal(run['company'], result['result']['proposal_id'])
        quantity = proposal['preparation']['proposed_fields']['quantity_selections'][0]['quantity']
        self.assertEqual(quantity['quantity_basis'], 'authored-line-v1')
        self.assertFalse(quantity['model_supplied_quantity'])
        self.assertEqual(self.store.count('proposal', {}), 1)
        with self.assertRaises(RickyError): self.service.commit_proposal(proposal['id'], 1)

    def test_committed_preparation_recovery_reuses_invocation_step_and_output_bytes(self):
        run, token, output, _ = self.prepare(estimate_request(self.boundary))
        saved = canonical({kind: self.store.find(kind, {}) for kind in ('step', 'invocation', 'artifact')})
        self.assertEqual(self.store.count('proposal', {}), 0)
        self.now += timedelta(seconds=181)
        self.service.process(run['id'])
        current = self.store.get('run', run['id'])
        self.assertEqual(current['status'], 'waiting-for-review'); self.assertEqual(current['lease_token'], token + 1)
        self.assertEqual(current['tool_calls'], 1)
        self.assertEqual(canonical({kind: self.store.find(kind, {}) for kind in ('step', 'invocation', 'artifact')}), saved)
        self.service.process(run['id'])
        self.assertEqual(self.store.count('proposal', {}), 1)

    def test_finalization_failure_rolls_back_proposal_and_run_linkage_together(self):
        run, token, _, _ = self.prepare()
        before = canonical(list(self.store.rows.items()))
        original_save = self.store.save
        def fail_terminal(kind, value):
            if kind == 'run' and value['status'] == 'waiting-for-review':
                raise RuntimeError('Explicit post-proposal persistence failure')
            return original_save(kind, value)
        with patch.object(self.store, 'save', side_effect=fail_terminal):
            with self.assertRaises(RuntimeError): self.service.finalize(run['id'], token)
        self.assertEqual(canonical(list(self.store.rows.items())), before)
        self.assertEqual(self.store.count('proposal', {}), 0)
        self.service.finalize(run['id'], token)
        self.assertEqual(self.store.count('proposal', {}), 1)

    def test_finalization_refuses_fence_cancel_session_source_head_and_deadline(self):
        for change in ('fence', 'cancel', 'session', 'source', 'native', 'ability', 'head', 'deadline', 'plan'):
            with self.subTest(change=change):
                self.setUp(); run, token, _, _ = self.prepare()
                if change == 'fence':
                    value = self.store.get('run', run['id']); value['lease_token'] += 1; self.store.save('run', value)
                elif change == 'cancel': self.service.cancel(run['company'], run['id'])
                elif change == 'session': self.boundary.session = False
                elif change == 'source': self.boundary.fixture.source_allowed = False
                elif change == 'native': self.boundary.fixture.native_allowed = False
                elif change == 'ability': self.boundary.permission.remove('commercial.read')
                elif change == 'head': self.boundary.fixture.proposal_value['current_revision'] = identity('successor')
                elif change == 'deadline': self.now += timedelta(seconds=301)
                else: self.boundary.growing_plan = True
                with self.assertRaises((RickyError, DomainError)): self.service.finalize(run['id'], token)
                self.assertEqual(self.store.count('proposal', {}), 0)

    def test_historical_review_survives_successor_head_expiry_and_new_session_without_rewrite(self):
        run, dto = self.start(estimate_request(self.boundary)); self.service.process(run['id'])
        current = self.store.get('run', run['id']); proposal_id = current['proposal_ids'][0]
        before = canonical(self.service.get_proposal(run['company'], proposal_id))
        self.boundary.fixture.records['estimate', self.boundary.fixture.records['revision', self.boundary.fixture.revision_id]['estimate']]['current_revision'] = identity('new-working-head')
        self.boundary.fixture.unit_enabled = False; self.boundary.session = False; self.now += timedelta(days=1)
        self.assertEqual(canonical(self.service.get_proposal(run['company'], proposal_id)), before)
        validate_start_receipt(self.store.get('run', run['id']), dto)

    def test_source_free_terminal_stop_confers_no_result_or_proposal_read_authority(self):
        run, _ = self.start(); self.service.process(run['id'])
        current = self.store.get('run', run['id']); before = canonical(list(self.store.rows.items()))
        self.boundary.fixture.source_allowed = False; self.boundary.session = False
        self.assertEqual(self.service.cancel(run['company'], run['id'])['status'], 'waiting-for-review')
        self.assertEqual(canonical(list(self.store.rows.items())), before)
        with self.assertRaises(RickyError): self.service.get_proposal(run['company'], current['proposal_ids'][0])
        self.boundary.fixture.source_allowed = True; self.boundary.user = 'alias@example.test'
        with self.assertRaises(RickyError): self.service.get_proposal(run['company'], current['proposal_ids'][0])

    def test_exact_dependencies_and_citations_cannot_be_omitted_or_duplicated(self):
        run, _, output, _ = self.prepare()
        for key in ('record_dependencies', 'verified_source_references'):
            for value in ([], output[key] + [output[key][0]], list(reversed(output[key]))):
                if value == output[key]: continue
                bad = deepcopy(output); bad[key] = value
                bad['draft_digest'] = digest({k: v for k, v in bad.items() if k != 'draft_digest'})
                with self.assertRaises(RickyError): validate_preparation(run, bad, originals=self.boundary.originals())

    def test_rehashed_quantity_tampering_refuses_independently_of_output_digest(self):
        run, _, output, _ = self.prepare(estimate_request(self.boundary))
        for key, replacement in [('numerator', '999'), ('denominator', '999'), ('source_unit_id', identity('wrong-unit')),
                ('provenance', 'manual-measurement'), ('quantity_basis', 'net-quantity-v1'), ('independently_verified', True)]:
            with self.subTest(key=key):
                bad = deepcopy(output); bad['proposed_fields']['quantity_selections'][0]['quantity'][key] = replacement
                bad['draft_digest'] = digest({k: v for k, v in bad.items() if k != 'draft_digest'})
                with self.assertRaises(RickyError): validate_preparation(run, bad, originals=self.boundary.originals())

    def test_manual_measurement_quantity_keeps_exact_net_basis_and_historical_readability(self):
        value = self.boundary.fixture.measurement_value
        line = self.boundary.fixture.records['line', self.boundary.fixture.line_id]
        snapshot = self.boundary.fixture.records['snapshot', self.boundary.fixture.snapshot_id]
        value.update(definition={'method': 'manual', 'waste_fraction': '0'},
            result={'quantity': {**line['authored']['quantity'], 'amount': '12.5'}},
            unit_manifest=deepcopy(snapshot['inputs']['unit_manifest']), calibration_id=None, verification_id=None)
        self.boundary.fixture.current = {'eligible': True, 'verification': None}
        run, token, output, _ = self.prepare(estimate_request(self.boundary, measurement=True))
        quantity = output['proposed_fields']['quantity_selections'][0]['quantity']
        self.assertEqual((quantity['numerator'], quantity['denominator'], quantity['quantity_basis']), ('25', '2', 'net-quantity-v1'))
        self.service.finalize(run['id'], token)
        proposal_id = self.store.get('run', run['id'])['proposal_ids'][0]
        before = canonical(self.service.get_proposal(run['company'], proposal_id))
        self.boundary.fixture.current['eligible'] = False
        self.assertEqual(canonical(self.service.get_proposal(run['company'], proposal_id)), before)

    def test_acceptance_checks_actual_canonical_document_before_any_invocation_exists(self):
        run, _ = self.start()
        claimed, token = self.service.claim(run['id'])
        request = DeterministicProposalRequest.from_value(run['request'])
        execution = CompanyProposalExecution(self.service, run['id'], token)
        execution.run, execution.authority = claimed, decode_run_authority(claimed)
        output = execution.aec('scope_draft', json.loads(request.arguments_json))
        output['verified_source_references'][0]['document_id'] = identity('foreign-document')
        output['draft_digest'] = digest({key: value for key, value in output.items() if key != 'draft_digest'})
        self.assertEqual(self.store.count('invocation', {}), 0)
        with self.assertRaises(RickyError): self.service._accept_tool_result(execution, output)
        self.assertEqual(self.store.count('invocation', {}), 0)
        self.assertEqual(self.store.count('proposal', {}), 0)

    def test_recovery_finalization_checks_canonical_document_despite_rehashed_invocation(self):
        run, token, _, _ = self.prepare()
        invocation = self.store.find('invocation', {})[0]
        # Direct corruption models an integrity violation, never a supported edit.
        value = self.store.rows['invocation', invocation['id']]
        value['output']['verified_source_references'][0]['document_id'] = identity('foreign-document')
        value['output']['draft_digest'] = digest({key: row for key, row in value['output'].items() if key != 'draft_digest'})
        value['output_digest'] = digest(value['output'])
        self.store.rows['step', value['step_id']]['output_digest'] = value['output_digest']
        with self.assertRaises(RickyError): self.service.finalize(run['id'], token)
        self.assertEqual(self.store.count('proposal', {}), 0)

    def test_finalization_requires_canonical_citation_objects_not_a_missing_optional_entry(self):
        run, token, _, _ = self.prepare()
        authorize = self.boundary.authorize_result
        def omit_canonical_citation(*args, **kwargs):
            return {key: value for key, value in authorize(*args, **kwargs).items() if key[0] != 'documents'}
        with patch.object(self.boundary, 'authorize_result', side_effect=omit_canonical_citation):
            with self.assertRaises(RickyError): self.service.finalize(run['id'], token)
        self.assertEqual(self.store.count('proposal', {}), 0)
