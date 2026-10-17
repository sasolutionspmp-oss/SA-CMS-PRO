"""Pure host adjudication tests. No socket, DB, Redis, worker or runtime call."""
from copy import deepcopy
from contextlib import ExitStack
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('r15_adjudication_under_test', HERE / 'r15_adjudication.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
three = r.v3(); two = three.v2(); old = two.v1()


def uid(n): return '00000000-0000-4000-8000-' + str(n).zfill(12)
def envelope(n, *, data=None, error=None):
    result = {'schema': 'cipher.api.v1', 'request_id': uid(900 + n),
        'meta': {'request_id': uid(900 + n), 'api_version': 'v1', 'server_time': '2026-10-17T00:00:00.500000Z'}}
    result['error' if error is not None else 'data'] = deepcopy(error if error is not None else data)
    return result


def fixture():
    company = 'Synthetic Company'; reviewed = {'proposal_id': uid(1), 'expected_version': 1,
        'expected_content_digest': 'a' * 64, 'mapping_version': '1', 'expected_payload_digest': 'b' * 64}
    intents = []; entries = []; journal = []
    for index in range(2):
        operation = uid(80 + index); payload = {'company': company, **reviewed, 'operation_id': operation}
        intent = {'key': 'v3-compete-' + str(index), 'role': 'author', 'method': old.SAVE + 'save_draft',
            'operation_id': operation, 'payload': payload, 'payload_sha256': two.sha(payload),
            'prepared_at': '2026-10-16T23:59:59+00:00', 'attempts': []}
        body = envelope(index, data={'operation': {'id': operation, 'status': 'succeeded', 'replayed': False},
            'application': {'operation_id': operation}, 'saved': {}}) if index == 0 else envelope(index, error=r.SAFE_503)
        entry = {'operation_id': operation, 'payload': deepcopy(payload), 'role': 'author', 'method': 'POST',
            'path': '/api/method/' + old.SAVE + 'save_draft', 'request_sha256': hashlib.sha256(json.dumps(payload, allow_nan=False).encode()).hexdigest(),
            'started_at': '2026-10-17T00:00:00.100000+00:00', 'completed_at': '2026-10-17T00:00:00.900000+00:00',
            'status': 200 if index == 0 else 503, 'observed_bytes': 400, 'body_sha256': 'c' * 64, 'truncated': False, 'envelope': body}
        intents.append(intent); entries.append(entry); saved = deepcopy(intent)
        saved['attempts'].append({'status': entry['status'], 'envelope': deepcopy(body), 'recorded_at': '2026-10-17T00:00:01+00:00'})
        journal.append(saved)
    auth = {'users': {'original': 'same'}, 'timezone': {'native': 'exact'}}; sessions = {'author': 'same'}
    batch = {'batch': r.CASE, 'role': 'author', 'method': 'POST batch', 'path': '/api/method/' + old.SAVE + 'save_draft',
        'before': deepcopy(auth), 'after': deepcopy(auth), 'sessions_before': deepcopy(sessions), 'sessions_after': deepcopy(sessions),
        'started_at': '2026-10-17T00:00:00+00:00', 'completed_at': '2026-10-17T00:00:01+00:00',
        'entries': entries, 'threads_alive': [False, False]}
    row = {'status': 'reviewed', 'action': 'aec.scope.draft', 'race_entered': True, 'race_intents': intents,
        'reviewed': reviewed, 'run_id': uid(2), 'proposal_id': uid(1), 'terminal': {'payloads': {'run': {'exact': 'bytes'}}}}
    value = {'company': company, 'site': 'synthetic.localhost', 'journal_directory': 'new-private-r15',
        'users': {'author': {'user': 'original@example.test', 'person': 'original-person'}},
        'stages': {old.KEY: {'cases': {r.CASE: deepcopy(row)}, two.KEY: {'schema': two.SCHEMA, 'targets': {}, 'wires': [batch],
            three.KEY: {'schema': three.SCHEMA, 'cases': {case: deepcopy(row) if case == r.CASE else {'status': 'passed'} for case in three.CASES}}}}}}
    outcome = r.validate_original_race(batch, row, company)
    original = {'case': deepcopy(row), 'batch': deepcopy(batch), 'outcome': outcome, 'batch_index': 0, 'wire_count': 1,
        'wire_prefix_sha256': [two.sha(batch)], 'journal_intents': deepcopy(journal)}
    two._proof(value)[r.KEY] = {'schema': r.SCHEMA, 'status': 'winner-and-loser-reconciled', 'outcome': outcome,
        'attribution': {'changes': [], 'session_changes': []}, 'original_failure': {'path': 'original', 'sha256': 'd' * 64, 'bytes': 1}}
    return value, original, journal


def state():
    return {'records': {'Cipher Ricky Draft Save': {}}, 'receipts': {}, 'history': {}, 'applications': {}, 'quotations': {},
        'company_head': 'head', 'source': {}, 'indexes': [], 'config': {}, 'inventory': {}, 'active_runs': []}


def refused_response():
    return {'status': 409, 'envelope': envelope(3, error={'code': 'draft_already_saved', 'details': {},
        'message': 'This suggestion already has an immutable draft save.', 'retryable': False}), 'seconds': 0.1}


def append_retry(value, original, journal):
    loser = next(row for row in journal if row['operation_id'] == original['outcome']['loser']); response = refused_response()
    loser['attempts'].append({'status': 409, 'envelope': deepcopy(response['envelope']), 'recorded_at': '2026-10-17T00:00:02+00:00'})
    start = len(two._proof(value)['wires']); wires = [
        {'role': 'author', 'method': 'GET', 'path': '/api/method/cipher_aec.api.v1.session', 'operation_id': None, 'status': 'verified'},
        {'role': 'author', 'method': 'POST', 'path': '/api/method/' + old.SAVE + 'save_draft', 'operation_id': loser['operation_id'],
         'payload_sha256': loser['payload_sha256'], 'status': 'verified', 'wire': {'status': 409}}]
    for wire in wires: wire.update(started_at='2026-10-17T00:00:01+00:00', completed_at='2026-10-17T00:00:02+00:00')
    two._proof(value)['wires'].extend(wires)
    proof = r._proof(value); proof['retry_intent'] = {'key': loser['key'], 'operation_id': loser['operation_id'],
        'payload_sha256': loser['payload_sha256'], 'wire_start_index': start}
    evidence = {'response': response, 'operation_id': loser['operation_id'], 'wire_start_index': start, 'wire_end_index': start + 2}
    return evidence


class OriginalRace(unittest.TestCase):
    def test_actual_200_503_outcome_and_union_bounds_are_distinct_from_dispatch(self):
        value, original, rows = fixture(); saved = deepcopy(value)
        result = r.validate_original_race(original['batch'], original['case'], value['company'])
        self.assertEqual(result['winner'], uid(80)); self.assertEqual(result['loser'], uid(81))
        self.assertEqual(result['started_at'], '2026-10-17T00:00:00.100000+00:00')
        self.assertNotEqual(result['started_at'], original['batch']['started_at']); self.assertEqual(value, saved)
    def test_different_status_code_retryability_or_safe_error_is_refused(self):
        for mutate in [lambda x: x.update(status=500), lambda x: x.update(status=409),
                lambda x: x['envelope']['error'].update(code='request_failed'), lambda x: x['envelope']['error'].update(retryable=False),
                lambda x: x['envelope']['error'].update(details={'sql': 'hidden'}), lambda x: x['envelope']['error'].update(message='other')]:
            value, original, rows = fixture(); mutate(original['batch']['entries'][1])
            with self.assertRaises((AssertionError, KeyError)): r.validate_original_race(original['batch'], original['case'], value['company'])
    def test_uncertain_truncated_running_thread_or_changed_request_is_refused(self):
        for mutate in [lambda b: b['entries'][1].update(error={'type': 'TimeoutError'}),
                lambda b: b['entries'][1].update(truncated=True), lambda b: b.update(threads_alive=[False, True]),
                lambda b: b['entries'][1].update(request_sha256='f' * 64), lambda b: b['entries'][1]['payload'].update(company='other'),
                lambda b: b['entries'][1].update(observed_bytes=2097153), lambda b: b['entries'][1].update(body_sha256='not-a-hash')]:
            value, original, rows = fixture(); mutate(original['batch'])
            with self.assertRaises(AssertionError): r.validate_original_race(original['batch'], original['case'], value['company'])
    def test_actual_overlap_and_dispatch_enclosure_required(self):
        for mutate in [lambda b: b['entries'][1].update(started_at='2026-10-17T00:00:02+00:00'),
                lambda b: b.update(started_at='2026-10-17T00:00:00.500000+00:00'),
                lambda b: b['entries'][0].update(started_at='2026-10-17T00:00:00'),
                lambda b: b.update(completed_at='2026-10-17T00:00:00.500000+00:00')]:
            value, original, rows = fixture(); mutate(original['batch'])
            with self.assertRaises(AssertionError): r.validate_original_race(original['batch'], original['case'], value['company'])
    def test_envelope_request_id_schema_and_winner_operation_are_bound(self):
        for mutate in [lambda b: b['entries'][1]['envelope'].update(schema='other'),
                lambda b: b['entries'][1]['envelope']['meta'].update(request_id=uid(999)),
                lambda b: b['entries'][0]['envelope']['data']['operation'].update(replayed=True),
                lambda b: b['entries'][0]['envelope']['data']['application'].update(operation_id=uid(81))]:
            value, original, rows = fixture(); mutate(original['batch'])
            with self.assertRaises(AssertionError): r.validate_original_race(original['batch'], original['case'], value['company'])


class RetainedJournal(unittest.TestCase):
    def test_original_responses_retained_plus_exactly_one_loser_attempt(self):
        value, original, rows = fixture(); retained = deepcopy(original)
        r._journal_originals(rows, original); append_retry(value, original, rows)
        r._journal_originals(rows, original, retried=True)
        self.assertEqual(original, retained); self.assertEqual([x['status'] for x in rows[1]['attempts']], [503, 409])
    def test_payload_uuid_first_response_unknown_transport_or_extra_attempt_refused(self):
        for mutate in [lambda x: x[1]['payload'].update(company='other'), lambda x: x[1].update(operation_id=uid(82)),
                lambda x: x[1]['attempts'][0].update(status=409), lambda x: x[1].update(uncertain_transport={'error': 'timeout'}),
                lambda x: x[1]['attempts'].append(deepcopy(x[1]['attempts'][0])), lambda x: x.append(deepcopy(x[1]))]:
            value, original, rows = fixture(); mutate(rows)
            with self.assertRaises(AssertionError): r._journal_originals(rows, original)
    def test_original_case_and_whole_preexisting_wire_prefix_remain_exact(self):
        value, original, rows = fixture(); r._original_retained(value, original)
        for mutate in [lambda v: three._proof(v)['cases'][r.CASE].update(status='passed'),
                lambda v: two._proof(v)['wires'][0].update(status='verified-batch'),
                lambda v: two._proof(v)['wires'][0]['entries'][1].update(status=409)]:
            changed = deepcopy(value); mutate(changed)
            with self.assertRaises(AssertionError): r._original_retained(changed, original)
    def test_third_uuid_or_same_uuid_under_another_key_is_refused(self):
        for operation in (uid(82), uid(81)):
            value, original, rows = fixture(); extra = deepcopy(rows[1]); extra.update(key='replacement-case', operation_id=operation)
            extra['payload']['operation_id'] = operation; extra['payload_sha256'] = two.sha(extra['payload']); rows.append(extra)
            with self.assertRaises(AssertionError): r._journal_originals(rows, original)


class NativeOutcome(unittest.TestCase):
    def test_real_v2_winner_verifier_receives_private_saved_shadow(self):
        value, original, rows = fixture(); retained = deepcopy(value); seen = []
        def verify(shadow, case, actual):
            seen.append(shadow); self.assertEqual(case, r.CASE)
            self.assertEqual(shadow['stages'][old.KEY]['cases'][case]['saved']['operation']['id'], uid(80))
            return {'application': {'operation_id': uid(80)}, 'receipt': {}, 'events': ['domain', 'application']}
        with patch.object(r, 'v3', return_value=three), patch.object(three, 'v2', return_value=two), patch.object(two, 'verify_saved_state', side_effect=verify):
            result = r.verify_native_outcome(value, original, state())
        self.assertEqual(result['events'], ['domain', 'application']); self.assertEqual(value, retained); self.assertEqual(len(seen), 1)
    def test_any_loser_receipt_history_or_application_refuses_adjudication(self):
        for mutate in [lambda s: s['receipts'].update(other={'operation_id': uid(81)}),
                lambda s: s['history'].update(other={'operation_id': uid(81)}),
                lambda s: s['records']['Cipher Ricky Draft Save'].update(other={'value': {'core': {'operation_id': uid(81)}}})]:
            value, original, rows = fixture(); actual = state(); mutate(actual)
            with patch.object(r, 'v3', return_value=three), patch.object(three, 'v2', return_value=two),\
                    patch.object(two, 'verify_saved_state', return_value={'application': {'operation_id': uid(80)}}):
                with self.assertRaises(AssertionError): r.verify_native_outcome(value, original, actual)


class AggregateAttribution(unittest.TestCase):
    def test_native_user_and_session_functions_receive_only_actual_wire_union(self):
        value, original, rows = fixture(); calls = []
        continuation = SimpleNamespace(TIMEZONE_POLICY={'native': 'exact'}, user_transition=lambda *args: calls.append(('user', args[-2:])) or [])
        with patch.object(r, 'v3', return_value=three), patch.object(three, 'v2', return_value=two),\
                patch.object(two, '_support', return_value=(None, None, None, continuation)),\
                patch.object(two, 'session_transition', side_effect=lambda *args: calls.append(('session', args[-2:])) or []):
            result = r._attribution(value, original)
        self.assertEqual(result, {'changes': [], 'session_changes': []})
        self.assertTrue(all(bounds == (original['outcome']['started_at'], original['outcome']['completed_at']) for kind, bounds in calls))
    def test_original_failed_batch_is_changed_only_in_private_audit_view(self):
        value, original, rows = fixture(); saved = deepcopy(value)
        with patch.object(r, '_attribution', return_value={'changes': [], 'session_changes': []}): shadow = r.adjudicated_ledger(value, original)
        self.assertEqual(value, saved); self.assertNotIn('status', two._proof(value)['wires'][0])
        self.assertEqual(two._proof(shadow)['wires'][0]['status'], 'verified')
        self.assertEqual(two._proof(shadow)['wires'][0]['started_at'], original['outcome']['started_at'])
        self.assertEqual(three._proof(value)['cases'][r.CASE]['status'], 'reviewed')
    def test_stored_heartbeat_attribution_cannot_be_changed(self):
        value, original, rows = fixture(); r._proof(value)['attribution']['changes'] = ['arbitrary-exception']
        with patch.object(r, '_attribution', return_value={'changes': [], 'session_changes': []}):
            with self.assertRaises(AssertionError): r.adjudicated_ledger(value, original)


class RetryLedger(unittest.TestCase):
    def test_distinct_retained_503_then_same_uuid_409_and_two_observed_wires(self):
        value, original, rows = fixture(); evidence = append_retry(value, original, rows)
        self.assertTrue(r.validate_retry_ledger(value, original, rows, evidence))
    def test_extra_changed_wire_wrong_uuid_or_nonimmutable_refusal_rejected(self):
        for mutate in [lambda v,o,j,e: two._proof(v)['wires'][-1].update(operation_id=uid(82)),
                lambda v,o,j,e: two._proof(v)['wires'][-1].update(payload_sha256='f' * 64),
                lambda v,o,j,e: two._proof(v)['wires'][-1].update(status='unverified'),
                lambda v,o,j,e: e['response']['envelope']['error'].update(retryable=True),
                lambda v,o,j,e: e.update(wire_end_index=e['wire_end_index'] - 1),
                lambda v,o,j,e: j[1]['attempts'].append(deepcopy(j[1]['attempts'][1]))]:
            value, original, rows = fixture(); evidence = append_retry(value, original, rows); mutate(value, original, rows, evidence)
            with self.assertRaises(AssertionError): r.validate_retry_ledger(value, original, rows, evidence)


class OneExplicitRetry(unittest.TestCase):
    def setup_collaborators(self, stack, *, change_native=False):
        value, original, journal = fixture(); calls = []; evidence = {}; actual = state(); reads = []
        def observe(path):
            result = deepcopy(actual)
            if change_native and reads: result['company_head'] = 'unexpected-effect'
            reads.append(1); return result
        class Journal:
            def __init__(self, path): self.rows = journal
        support = SimpleNamespace(Journal=Journal)
        def update(path, **fields): r._proof(value).update(deepcopy(fields)); return value
        def save_evidence(path, label, data): evidence[label] = deepcopy(data); return {'label': label}
        def read_ref(path, reference): return original if reference.get('path') == 'original' else evidence[reference['label']]
        def client(path, origin, host):
            calls.append(('authenticate', path, origin, host))
            def call(method, fields, *, key, replay):
                calls.append(('post', method, deepcopy(fields), key, replay))
                append_retry(value, original, journal)
                return refused_response()
            return SimpleNamespace(call=call)
        stack.enter_context(patch.object(r, 'v3', return_value=three)); stack.enter_context(patch.object(three, 'v2', return_value=two))
        stack.enter_context(patch.object(r, '_value', return_value=value)); stack.enter_context(patch.object(r, '_update', side_effect=update))
        stack.enter_context(patch.object(r, '_evidence', side_effect=save_evidence)); stack.enter_context(patch.object(r, '_read_reference', side_effect=read_ref))
        stack.enter_context(patch.object(r, 'verify_native_outcome', return_value={'application': {'operation_id': uid(80)}}))
        stack.enter_context(patch.object(two, '_support', return_value=(support, None, None, None)))
        stack.enter_context(patch.object(two, 'observe_native', side_effect=observe)); stack.enter_context(patch.object(two, 'client', side_effect=client))
        stack.enter_context(patch.object(two, '_run', return_value=original['case']['terminal']))
        return value, original, journal, calls
    def test_one_retry_uses_original_key_payload_and_explicit_replay_flag(self):
        with ExitStack() as stack:
            value, original, rows, calls = self.setup_collaborators(stack)
            result = r.retry_loser_once('new-manifest', 'http://original-web', 'synthetic.localhost')
            self.assertEqual(result['status'], 'passed_v4_adjudicated'); self.assertEqual(result['operation_id'], uid(81))
            self.assertEqual(calls[-1], ('post', old.SAVE + 'save_draft', {'company': value['company'], **original['case']['reviewed']}, 'v3-compete-1', True))
            self.assertEqual([attempt['status'] for attempt in rows[1]['attempts']], [503, 409])
            self.assertEqual(three._proof(value)['cases'][r.CASE], original['case'])
            with self.assertRaises(RuntimeError): r.retry_loser_once('new-manifest', 'http://original-web', 'synthetic.localhost')
    def test_retry_that_changes_native_state_cannot_pass_or_repeat(self):
        with ExitStack() as stack:
            value, original, rows, calls = self.setup_collaborators(stack, change_native=True)
            with self.assertRaises(AssertionError): r.retry_loser_once('new-manifest', 'http://original-web', 'synthetic.localhost')
            self.assertEqual(r._proof(value)['status'], 'same-uuid-retry-entered')
            with self.assertRaises(RuntimeError): r.retry_loser_once('new-manifest', 'http://original-web', 'synthetic.localhost')


class EvidenceFiles(unittest.TestCase):
    def test_one_shot_private_regular_sidecar_and_strict_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'fixture.secret.json'; reference = r._evidence(path, 'original-failure', {'retained': 'exact'})
            self.assertEqual(r._read_reference(path, reference), {'retained': 'exact'})
            self.assertFalse(Path(reference['path']).stat().st_mode & 0o077)
            with self.assertRaises(FileExistsError): r._evidence(path, 'original-failure', {'reset': True})
            Path(reference['path']).write_text('{}')
            with self.assertRaises(AssertionError): r._read_reference(path, reference)
    def test_import_is_inert_no_uuid_mint_or_frozen_helper_mutation(self):
        source = (HERE / 'r15_adjudication.py').read_text()
        self.assertNotIn('uuid4', source); self.assertNotIn('set_user(', source)
        self.assertNotIn('journal.prepare(', source); self.assertNotIn('three._case(', source)
        self.assertNotIn('two_operation_posts(', source); self.assertNotIn('subprocess', source)
        self.assertEqual(r.v3().V2_SHA256, 'f47a94dd3e003984413c1c8bb87fce8ea40c7568853bd085eec1278e8bf49a8a')


class WholePreservationAudit(unittest.TestCase):
    def run_audit(self, *, other_status='passed', final_queue=None):
        value, original, journal = fixture(); retry = append_retry(value, original, journal); saved = deepcopy(value)
        r._proof(value).update(status='passed_v4_adjudicated', retry_evidence={'slot': 'retry'})
        three._proof(value)['cases']['source-outage-r15']['status'] = other_status
        baseline = {'inventory': {'original-table': {'original-row': 'exact'}}}
        positive = {'inventory': {'original-table': {'original-row': 'exact', 'positive-head': {'column': 'audited-original'}}}}
        actual = state(); actual['inventory'] = deepcopy(positive['inventory']); calls = []
        class Journal:
            def __init__(self, path): self.rows = journal
        support = SimpleNamespace(Journal=Journal, load_private=lambda path: positive if path == 'actual-v3-positive-baseline' else baseline)
        two._proof(value)['baseline'] = {'path': 'actual-retained-v2-baseline'}
        three._proof(value)['baseline'] = {'path': 'actual-v3-positive-baseline'}
        def read(path, reference): return original if reference.get('path') == 'original' else retry
        def update(path, **fields): r._proof(value).update(deepcopy(fields)); return value
        def restore(v, before, after):
            self.assertIs(v, value); self.assertIs(before, baseline); self.assertIs(after, actual)
            calls.append('exact-v3-restoration'); return {'independently': 'adjusted-by-v3'}, ['literal-restoration']
        def preserve(shadow, before, adjusted, rows):
            self.assertIs(before, baseline); self.assertEqual(adjusted, {'independently': 'adjusted-by-v3'}); self.assertIs(rows, journal)
            self.assertEqual(two._proof(shadow)['wires'][0]['status'], 'verified')
            self.assertEqual(shadow['stages'][old.KEY]['cases'][r.CASE]['saved']['operation']['id'], uid(80))
            self.assertEqual(three._proof(shadow)['cases'][r.CASE]['status'], 'reviewed')
            calls.append('exact-v2-preservation'); return {'old_rows_unchanged': True, 'additions': {'only': ['exact']}}
        def positive_saved(v, case, final, *, current):
            self.assertIs(v, value); self.assertIs(final, actual); self.assertIs(current, False)
            calls.append('positive-saved-' + case)
            return {'application': {'core_digest': 'c' * 64, 'receipt_id': 'd' * 64}, 'events': ['original-domain', 'original-application']}
        queue = final_queue or {'site': value['site'], 'queue': 'cipher-ai04-stage-a-20261016:short', 'jobs': [], 'workers': [], 'started_jobs': []}
        with ExitStack() as stack:
            stack.enter_context(patch.object(r, 'v3', return_value=three)); stack.enter_context(patch.object(three, 'v2', return_value=two))
            stack.enter_context(patch.object(r, '_value', return_value=value)); stack.enter_context(patch.object(r, '_update', side_effect=update))
            stack.enter_context(patch.object(r, '_read_reference', side_effect=read)); stack.enter_context(patch.object(r, '_evidence', return_value={'slot': 'audit'}))
            stack.enter_context(patch.object(r, '_attribution', return_value={'changes': [], 'session_changes': []}))
            stack.enter_context(patch.object(r, 'verify_native_outcome', return_value={'application': {'operation_id': uid(80)}}))
            stack.enter_context(patch.object(two, '_support', return_value=(support, None, None, None)))
            stack.enter_context(patch.object(two, 'observe_native', return_value=actual))
            stack.enter_context(patch.object(two, '_run', return_value=original['case']['terminal']))
            stack.enter_context(patch.object(two, 'verify_saved_state', side_effect=positive_saved))
            stack.enter_context(patch.object(three, 'restored_inventory', side_effect=restore))
            stack.enter_context(patch.object(two, 'verify_preservation', side_effect=preserve))
            result = r.audit('new-manifest', queue)
        return result, value, original, calls
    def test_final_audit_calls_exact_existing_restoration_and_preservation_on_private_view(self):
        result, value, original, calls = self.run_audit()
        self.assertEqual(calls, ['positive-saved-scope-r15', 'positive-saved-estimate-r15', 'exact-v3-restoration', 'exact-v2-preservation'])
        self.assertEqual(result['status'], 'audited_v4_adjudicated'); self.assertTrue(result['old_rows_unchanged'])
        self.assertTrue(result['positive_epoch_rows_unchanged']); self.assertEqual(result['positive_epoch_rows'], 1)
        self.assertEqual(three._proof(value)['cases'][r.CASE], original['case'])
        self.assertEqual(two._proof(value)['wires'][0], original['batch'])
        self.assertNotEqual(three._proof(value).get('status'), 'audited')
    def test_unfinished_other_case_or_nonempty_worker_inventory_blocks_complete_audit(self):
        with self.assertRaises(RuntimeError): self.run_audit(other_status='reviewed')
        queue = {'site': 'synthetic.localhost', 'queue': 'cipher-ai04-stage-a-20261016:short', 'jobs': [], 'workers': ['active'], 'started_jobs': []}
        with self.assertRaises(AssertionError): self.run_audit(final_queue=queue)


class PositiveEpochPreservation(unittest.TestCase):
    def fixture(self):
        before = {'inventory': {'Cipher Proposal': {'old': {'current_revision': 'old-original'}}, 'User': {'original': {'heartbeat': 'old'}}}}
        positive = deepcopy(before); positive['inventory']['Cipher Proposal']['positive-head'] = {'current_revision': 'audited-successor', 'modified': 'audited-original'}
        after = deepcopy(positive); after['inventory']['Cipher Proposal']['separate-v3-head'] = {'current_revision': 'new-v3-owner'}
        # Preexisting User metadata remains governed by the separate strict old
        # baseline/wire proof and is not an exception for any positive addition.
        after['inventory']['User']['original']['heartbeat'] = 'new-bounded-heartbeat'
        return before, positive, after
    def test_all_positive_added_native_columns_remain_exact_through_later_cases(self):
        before, positive, after = self.fixture(); saved = deepcopy((before, positive, after))
        result = r.verify_positive_epoch(before, positive, after)
        self.assertEqual(result['positive_epoch_additions'], {'Cipher Proposal': ['positive-head']})
        self.assertEqual(result['positive_epoch_rows'], 1); self.assertEqual((before, positive, after), saved)
    def test_positive_parent_current_head_or_native_modified_column_tamper_refused(self):
        for column, value in [('current_revision', 'unauthorized-head'), ('modified', 'later-native-write')]:
            before, positive, after = self.fixture(); after['inventory']['Cipher Proposal']['positive-head'][column] = value
            with self.assertRaisesRegex(AssertionError, 'already-audited positive'): r.verify_positive_epoch(before, positive, after)
    def test_positive_row_missing_or_table_set_change_refused(self):
        before, positive, after = self.fixture(); del after['inventory']['Cipher Proposal']['positive-head']
        with self.assertRaises(AssertionError): r.verify_positive_epoch(before, positive, after)
        before, positive, after = self.fixture(); after['inventory']['arbitrary-table'] = {}
        with self.assertRaises(AssertionError): r.verify_positive_epoch(before, positive, after)


if __name__ == '__main__': unittest.main()
