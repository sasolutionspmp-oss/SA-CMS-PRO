"""Actual command/chain functions and published wire schemas; host fixtures only."""
from copy import deepcopy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.ricky.company_proposal_contracts import START_COMMAND, CANCEL_COMMAND, DeterministicProposalRequest
from cipher_aec.ricky import company_proposal_service
from cipher_aec.ricky.company_proposal_service import CompanyProposalService, domain_errors
from cipher_aec.ricky.company_backend import validate_manifest as read_manifest, validate_resource_plan as read_resource_plan
from cipher_aec.tests import test_ricky_company_proposals as fixtures
from cipher_aec.tests import test_ricky_company_history as history


ROOT = Path(__file__).parents[1]


class ProposalAPICommands(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProposalServiceTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.history = h = history.CompanyCommandHistoryTests(); h.setUp(); self.addCleanup(h.doCleanups)
        sys.modules['cipher_aec.ricky.company_backend'].validate_manifest = read_manifest
        sys.modules['cipher_aec.ricky.company_backend'].validate_resource_plan = read_resource_plan
        f = self.fixture
        h.actor = f.boundary.actor; h.original_user = h.actor.user; h.company = 'Explicit EST fixture'
        h.request = fixtures.scope_request(f.boundary).binding()
        self.addCleanup(patch.stopall)
        patch.object(company_proposal_service, 'build_service', return_value=f.service).start()
        old_runner = h.start.__globals__['run_company_command']
        cells = dict(zip(old_runner.__code__.co_freevars, (cell.cell_contents for cell in old_runner.__closure__)))
        command = cells['command']
        command.__globals__['COMPANY_RICKY_COMMANDS'] |= {START_COMMAND, CANCEL_COMMAND}
        command.__globals__['authorize_receipt'] = lambda actor, command, company, project, result, **kwargs: company_proposal_service.authorize_receipt(
            actor, company, result, command=command, lock=True)
        def start(company, request, operation):
            h.require_trusted()
            result = f.service.start_proposal(company, request, operation)
            run = f.store.get('run', result['id'])
            f.boundary.receipts[run['start_receipt']] = run['id']
            h.db.execute('INSERT INTO runs VALUES (?,?)', (run['id'], canonical_json(result)))
            return result
        service = SimpleNamespace(start_proposal=start, cancel=f.service.cancel)
        namespace = {'__name__': 'cipher_aec.ricky.company_proposal_api', '__package__': 'cipher_aec.ricky',
            'endpoint': lambda **kwargs: lambda function: function, 'domain_errors': domain_errors,
            'DeterministicProposalRequest': DeterministicProposalRequest, 'build_service': lambda: service,
            'START_COMMAND': START_COMMAND, 'CANCEL_COMMAND': CANCEL_COMMAND,
            'run_company_command': old_runner, 'append_company_event': h.append}
        self.start = history.function('ricky/company_proposal_api.py', 'start_proposal', namespace)
        self.stop = history.function('ricky/company_proposal_api.py', 'cancel_run', namespace)
        self.schemas = json.loads((ROOT / 'api/openapi.json').read_text())

    def start_run(self):
        h = self.history
        result = self.start(h.company, h.request, h.start_id)
        h.commit()
        return result

    def validate_wire(self, method, value):
        schema = self.schemas['paths']['/api/method/cipher_aec.ricky.company_proposal_api.' + method][
            'post' if method in {'start_proposal', 'cancel_run'} else 'get']['responses']['200']['content']['application/json']['schema']
        schema = {**schema, 'components': self.schemas['components']}
        Draft202012Validator(schema).validate({'message': {'schema': 'cipher.api.v1', 'request_id': '00000000-0000-4000-8000-000000000000',
            'meta': {'request_id': '00000000-0000-4000-8000-000000000000', 'api_version': 'v1', 'server_time': '2026-10-16T00:00:00Z'}, 'data': value}})

    def test_new_start_chain_receipt_and_postcommit_hint_without_worker_history(self):
        h, f = self.history, self.fixture
        result = self.start_run()
        self.assertEqual((h.counts(), len(h.enqueued)), ([1, 1, 1], 1))
        f.service.process(result['id'])
        terminal = f.service.get_run(h.company, result['id'])
        proposal = f.service.get_proposal(h.company, terminal['result']['proposal_id'])
        self.assertEqual(len(h.history()), 1)
        event = h.history()[0]
        self.assertEqual((event['event'], event['subject_type'], event['subject_id'], event['actor_person']),
            ('ricky.company.proposal.start.accepted', 'Cipher Ricky Run', result['id'], h.actor.person_id))
        self.assertEqual(json.loads(event['details_json']), {'action': 'aec.scope.draft', 'status': 'queued'})
        self.assertEqual(event['event_hash'], digest(json.loads(event['event_payload'])))
        for secret in ('session_reference', 'authority_version', 'Author supplied suggestion.', f.boundary.actor.user):
            self.assertNotIn(secret, event['event_payload'])
        self.validate_wire('start_proposal', result)
        self.validate_wire('get_run', terminal)
        self.validate_wire('get_proposal', proposal)

    def test_exact_receipt_replays_do_not_append_dispatch_or_duplicate_proposal(self):
        h, f = self.history, self.fixture
        admitted = self.start_run(); f.service.process(admitted['id'])
        stopped = self.stop(h.company, admitted['id'], h.stop_id); h.commit()
        self.assertEqual(stopped['status'], 'waiting-for-review'); self.assertFalse(stopped['cancel_requested'])
        receipts = h.db.execute('SELECT result_json,result_hash FROM `tabCipher Command Receipt` ORDER BY name').fetchall()
        rows = [tuple(row) for row in receipts]; events = h.history(); jobs = list(h.enqueued)
        replay = self.start(h.company, h.request, h.start_id)
        stop_replay = self.stop(h.company, admitted['id'], h.stop_id)
        self.assertEqual(replay, {**admitted, 'operation': {**admitted['operation'], 'replayed': True}})
        self.assertEqual(stop_replay, {**stopped, 'operation': {**stopped['operation'], 'replayed': True}})
        self.assertEqual(replay['status'], 'queued'); h.commit()
        self.assertEqual([tuple(row) for row in h.db.execute('SELECT result_json,result_hash FROM `tabCipher Command Receipt` ORDER BY name')], rows)
        self.assertEqual(h.history(), events); self.assertEqual(h.enqueued, jobs); self.assertEqual(f.store.count('proposal', {}), 1)
        self.assertEqual(events[1]['previous_hash'], events[0]['event_hash'])
        self.validate_wire('cancel_run', stopped)

    def test_source_free_terminal_stop_does_not_enable_start_receipt_replay_or_review(self):
        h, f = self.history, self.fixture
        result = self.start_run(); f.service.process(result['id'])
        before = canonical_json(list(f.store.rows.items()))
        f.boundary.fixture.source_allowed = False
        stopped = self.stop(h.company, result['id'], h.stop_id); h.commit()
        self.assertEqual(stopped['status'], 'waiting-for-review')
        self.assertEqual(canonical_json(list(f.store.rows.items())), before)
        with self.assertRaises(DomainError): self.start(h.company, h.request, h.start_id)
        self.assertTrue(self.stop(h.company, result['id'], h.stop_id)['operation']['replayed'])
        self.assertEqual(len(h.history()), 2)

    def test_wire_schema_rejects_wrong_action_linkage_and_unwrapped_payload(self):
        result = self.start_run()
        schema = self.schemas['paths']['/api/method/cipher_aec.ricky.company_proposal_api.start_proposal']['post']['responses']['200']['content']['application/json']['schema']
        validator = Draft202012Validator({**schema, 'components': self.schemas['components']})
        self.assertTrue(list(validator.iter_errors({'data': result})))


class ProposalMixedHistoryPrivacy(unittest.TestCase):
    def setUp(self):
        self.h = h = history.CompanyCommandHistoryPrivacyTests(); h.setUp(); self.addCleanup(h.doCleanups)
        self.f = f = fixtures.ProposalServiceTests(); f.setUp(); self.addCleanup(f.doCleanups)
        # The real six tables contain old read and new proposal rows together.
        f.store = h.fixture.store
        f.service = CompanyProposalService(f.store, f.boundary, clock=lambda: f.now)
        run, _ = f.start(); f.service.process(run['id']); self.run = run
        self.stack = h.stack
        self.stack.enter_context(patch.object(company_proposal_service, 'build_service', return_value=f.service))
        for name, event in [('f-proposal-start', 'ricky.company.proposal.start.accepted'), ('g-proposal-stop', 'ricky.company.proposal.stop.accepted')]:
            h.db.execute('INSERT INTO `tabCipher History Event` VALUES (?,?,?,?,?)', (name, '2026-10-16 12:00:00.000001', h.company, 'Company', None))
            h.records[name] = SimpleNamespace(name=name, subject_type='Cipher Ricky Run', subject_id=run['id'], event=event)

    def test_exact_original_actor_and_filtered_mixed_total_cursor_before_and_after_source_denial(self):
        h, f = self.h, self.f
        page = h.history(h.company, limit=1, count_mode='exact')
        self.assertEqual(page['total'], 4); self.assertEqual(page['items'][0]['id'], 'g-proposal-stop')
        next_page = h.history(h.company, limit=1, count_mode='exact', cursor=page['next_cursor'])
        self.assertEqual(next_page['items'][0]['id'], 'f-proposal-start')
        self.assertFalse(h.readable(h.records['g-proposal-stop'], h.alias, h.company, None))
        self.assertFalse(h.readable(h.records['g-proposal-stop'], SimpleNamespace(user=h.owner.user, person_id='outsider'), h.company, None))
        f.boundary.fixture.source_allowed = False
        page = h.history(h.company, limit=1, count_mode='exact')
        self.assertEqual(page['total'], 2); self.assertEqual(page['items'][0]['id'], 'd-owner-stop')
        f.service.cancel(h.company, self.run['id'])
        self.assertEqual(h.history(h.company, count_mode='exact')['total'], 2)
