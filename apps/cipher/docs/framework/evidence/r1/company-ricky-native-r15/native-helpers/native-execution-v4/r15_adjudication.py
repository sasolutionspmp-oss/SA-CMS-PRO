"""Explicit adjudication of one retained R15 200/503 overlap. Import is inert.

Root owns every native/HTTP action. Frozen v1/v2/v3/listener/backend files and
the original failed batch/case remain unchanged. No new command UUID is minted.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from uuid import UUID

V3_SHA256 = '57b93171fff3ca44695de772b540bfc456c4ec34a95e34dcaef8aff812492d21'
KEY = 'execution_v4'
SCHEMA = 'cipher.fixture.ricky.company.race-adjudication.v4'
CASE = 'two-operation-r15'
SAFE_503 = {'code': 'concurrent_change', 'details': {},
    'message': 'Records changed concurrently. Retry the original operation after refreshing current access.', 'retryable': True}


def v3():
    path = Path(__file__).resolve().parent.parent / 'native-execution-v3/r15_boundaries.py'
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != V3_SHA256:
        raise AssertionError('Keep the exact frozen v3 collaborator.')
    spec = importlib.util.spec_from_file_location('cipher_r15_frozen_v3_adjudication', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def _proof(value): return v3().v2()._proof(value)[KEY]


def _evidence(path, label, data):
    if label not in {'original-failure', 'same-uuid-retry', 'final-audit'}:
        raise ValueError('Use a literal, one-shot v4 evidence slot.')
    directory = Path(path).resolve().parent / 'r15-v4-evidence'
    if directory.is_symlink(): raise ValueError('Evidence aliases are refused.')
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.stat().st_mode & 0o077: raise ValueError('Keep v4 evidence private.')
    target = directory / (label + '.secret.json')
    raw = (json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
    return {'path': str(target), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _read_reference(path, reference):
    target = Path(reference['path'])
    if (target.is_symlink() or not target.is_file() or target.stat().st_mode & 0o077
            or target.parent.resolve() != (Path(path).resolve().parent / 'r15-v4-evidence')
            or set(reference) != {'path', 'sha256', 'bytes'}):
        raise AssertionError('Keep exact regular private v4 evidence references.')
    raw = target.read_bytes()
    if len(raw) != reference['bytes'] or hashlib.sha256(raw).hexdigest() != reference['sha256']:
        raise AssertionError('Retained v4 evidence bytes changed.')
    return json.loads(raw)


def _time(value):
    actual = datetime.fromisoformat(value)
    if actual.tzinfo is None: raise AssertionError('Require actual timezone-aware wire bounds.')
    return actual


def _envelope(value, *, error=None):
    kind = 'error' if error is not None else 'data'
    if (set(value) != {'schema', 'request_id', 'meta', kind} or value['schema'] != 'cipher.api.v1'
            or set(value['meta']) != {'request_id', 'api_version', 'server_time'}
            or value['meta']['request_id'] != value['request_id'] or value['meta']['api_version'] != 'v1'
            or str(UUID(value['request_id'])) != value['request_id']):
        raise AssertionError('Require the exact actual canonical API envelope.')
    _time(value['meta']['server_time'])
    if error is not None and value['error'] != error:
        raise AssertionError('Only the exact observed retryable concurrency envelope is adjudicated.')


def validate_original_race(batch, row, company):
    """Pure strict validation; original dispatch bounds/bytes are never changed."""
    two = v3().v2(); method = two.v1().SAVE + 'save_draft'; route = '/api/method/' + method
    expected_batch = {'batch', 'role', 'method', 'path', 'before', 'sessions_before', 'started_at',
        'completed_at', 'entries', 'threads_alive', 'after', 'sessions_after'}
    if (set(batch) != expected_batch or batch['batch'] != CASE or batch['role'] != 'author'
            or batch['method'] != 'POST batch' or batch['path'] != route or batch['threads_alive'] != [False, False]
            or row['status'] != 'reviewed' or row.get('race_entered') is not True or len(row['race_intents']) != 2):
        raise AssertionError('Require the retained completed, unadjudicated v3 failure exactly.')
    entries = batch['entries']; intents = row['race_intents']
    if (len(entries) != 2 or len({intent['operation_id'] for intent in intents}) != 2
            or {intent['key'] for intent in intents} != {'v3-compete-0', 'v3-compete-1'}):
        raise AssertionError('Retain both distinct original fsynced operation UUIDs.')
    if {entry['operation_id'] for entry in entries} != {intent['operation_id'] for intent in intents}:
        raise AssertionError('Actual overlap does not match both original intents.')
    required = {'operation_id', 'payload', 'role', 'method', 'path', 'request_sha256', 'started_at', 'completed_at',
        'status', 'observed_bytes', 'body_sha256', 'truncated', 'envelope'}
    for intent in intents:
        actual = next(entry for entry in entries if entry['operation_id'] == intent['operation_id'])
        operation = intent['operation_id']; payload = {'company': company, **row['reviewed'], 'operation_id': operation}
        if (set(actual) != required or intent['role'] != 'author' or intent['method'] != method
                or intent.get('attempts') or intent.get('uncertain_transport')
                or str(UUID(operation)) != operation or intent['payload'] != payload or actual['payload'] != payload
                or intent['payload_sha256'] != two.sha(payload) or actual['role'] != 'author'
                or actual['method'] != 'POST' or actual['path'] != route or actual['truncated'] is not False
                or type(actual['observed_bytes']) is not int or not 1 <= actual['observed_bytes'] <= 2097152
                or actual['request_sha256'] != hashlib.sha256(json.dumps(payload, allow_nan=False).encode()).hexdigest()
                or len(actual['body_sha256']) != 64 or any(c not in '0123456789abcdef' for c in actual['body_sha256'])):
            raise AssertionError('Require bounded complete actual wires and their exact original fsynced payloads.')
        _envelope(actual['envelope'], error=SAFE_503 if actual['status'] == 503 else None)
    starts = [_time(entry['started_at']) for entry in entries]; ends = [_time(entry['completed_at']) for entry in entries]
    if (any(start > end for start, end in zip(starts, ends)) or max(starts) >= min(ends)
            or _time(batch['started_at']) > min(starts) or _time(batch['completed_at']) < max(ends)):
        raise AssertionError('Require actual overlapping wire intervals within the retained dispatch interval.')
    winners = [entry for entry in entries if entry['status'] == 200]; losers = [entry for entry in entries if entry['status'] == 503]
    if len(winners) != 1 or len(losers) != 1:
        raise AssertionError('This supplement covers exactly one actual 200 and one exact retryable 503.')
    winner = winners[0]; loser = losers[0]; data = winner['envelope']['data']
    if (data['operation'] != {'id': winner['operation_id'], 'status': 'succeeded', 'replayed': False}
            or data['application']['operation_id'] != winner['operation_id']):
        raise AssertionError('Require the one first-effect canonical winner.')
    return {'winner': winner['operation_id'], 'loser': loser['operation_id'],
        'started_at': min(starts).isoformat(), 'completed_at': max(ends).isoformat(),
        'observed_outcome': 'one-canonical-winner-and-retryable-concurrency-refusal'}


def _journal_originals(rows, original, *, retried=False):
    """Original attempts remain exact prefixes; only one loser 409 may append."""
    outcome = original['outcome']
    expected_operations = {outcome['winner'], outcome['loser']}
    fields = {key: value for key, value in original['journal_intents'][0]['payload'].items() if key != 'operation_id'}
    matching = [entry for entry in rows if entry['method'] == original['journal_intents'][0]['method']
        and {key: value for key, value in entry['payload'].items() if key != 'operation_id'} == fields]
    if len(matching) != 2 or {entry['operation_id'] for entry in matching} != expected_operations:
        raise AssertionError('No third UUID or replacement case may target this exact reviewed payload.')
    for saved in original['journal_intents']:
        matches = [entry for entry in rows if entry['key'] == saved['key']]
        if len(matches) != 1 or sum(entry['operation_id'] == saved['operation_id'] for entry in rows) != 1:
            raise AssertionError('The original fsynced intent key or operation UUID changed or duplicated.')
        actual = matches[0]
        initial = next(intent for intent in original['case']['race_intents'] if intent['operation_id'] == saved['operation_id'])
        if ({key: value for key, value in saved.items() if key != 'attempts'} !=
                {key: value for key, value in initial.items() if key != 'attempts'}):
            raise AssertionError('The actual serial journal does not match the original fsynced race intent.')
        if ({key: value for key, value in actual.items() if key != 'attempts'} !=
                {key: value for key, value in saved.items() if key != 'attempts'}
                or actual['attempts'][:len(saved['attempts'])] != saved['attempts']):
            raise AssertionError('Original UUID, payload or retained first response bytes changed.')
        count = 2 if retried and actual['operation_id'] == outcome['loser'] else 1
        if len(saved['attempts']) != 1 or len(actual['attempts']) != count:
            raise AssertionError('No extra attempt or third operation is permitted.')
        batch = next(entry for entry in original['batch']['entries'] if entry['operation_id'] == actual['operation_id'])
        if saved['attempts'][0]['status'] != batch['status'] or saved['attempts'][0]['envelope'] != batch['envelope']:
            raise AssertionError('Actual original batch and serially retained first response differ.')
    return {entry['operation_id']: entry for entry in rows if entry['operation_id'] in {outcome['winner'], outcome['loser']}}


def _original_retained(value, original):
    three = v3(); two = three.v2(); wires = two._proof(value)['wires']; row = three._proof(value)['cases'][CASE]
    if (row != original['case'] or len(wires) < original['wire_count']
            or [two.sha(wire) for wire in wires[:original['wire_count']]] != original['wire_prefix_sha256']
            or wires[original['batch_index']] != original['batch']
            or validate_original_race(original['batch'], row, value['company']) != original['outcome']):
        raise AssertionError('The retained original failed case/batch/wire prefix changed.')


def _value(path):
    three = v3(); value = three._value(path); proof = _proof(value)
    if proof['schema'] != SCHEMA: raise ValueError('Use the distinct declared v4 adjudication.')
    original = _read_reference(path, proof['original_failure']); _original_retained(value, original)
    for key in ('retry_evidence', 'audit_evidence'):
        if key in proof: _read_reference(path, proof[key])
    return value


def _update(path, **fields):
    two = v3().v2(); value = _value(path); _proof(value).update(deepcopy(fields)); two._support()[0].write_private(path, value)
    return value


def _saved_shadow(value, original):
    three = v3(); two = three.v2(); shadow = deepcopy(value)
    winner = next(entry for entry in original['batch']['entries'] if entry['operation_id'] == original['outcome']['winner'])
    row = deepcopy(three._proof(value)['cases'][CASE]); row['saved'] = deepcopy(winner['envelope']['data'])
    shadow['stages'][two.v1().KEY]['cases'][CASE] = row
    return shadow


def verify_native_outcome(value, original, state):
    """Actual native winner through v2, and no loser receipt/history/application."""
    three = v3(); two = three.v2(); outcome = original['outcome']; loser = outcome['loser']
    proof = two.verify_saved_state(_saved_shadow(value, original), CASE, state)
    receipt_id = two.sha({'person': value['users']['author']['person'], 'operation_id': loser})
    if (receipt_id in state['receipts'] or any(row['operation_id'] == loser for row in state['receipts'].values())
            or any(row['operation_id'] == loser for row in state['history'].values())
            or any(row['value']['core']['operation_id'] == loser for row in state['records']['Cipher Ricky Draft Save'].values())
            or proof['application']['operation_id'] != outcome['winner']):
        raise AssertionError('The observed 503 loser must have no actual receipt/history/application.')
    return proof


def _attribution(value, original):
    two = v3().v2(); continuation = two._support()[3]; batch = original['batch']; outcome = original['outcome']
    if batch['before']['timezone'] != continuation.TIMEZONE_POLICY or batch['after']['timezone'] != continuation.TIMEZONE_POLICY:
        raise AssertionError('The actual native timestamp policy changed during overlap.')
    return {'changes': continuation.user_transition(batch['before']['users'], batch['after']['users'], value['users'],
                'author', outcome['started_at'], outcome['completed_at']),
        'session_changes': two.session_transition(batch['sessions_before'], batch['sessions_after'],
                'author', outcome['started_at'], outcome['completed_at'])}


def declare_adjudication(path):
    """ROOT ONLY: independent native reads; no request, retry or domain write."""
    three = v3(); two = three.v2(); value = three._value(path)
    if KEY in two._proof(value): raise RuntimeError('Never reset an entered v4 declaration.')
    wires = two._proof(value)['wires']; indices = [index for index, wire in enumerate(wires) if 'batch' in wire]
    if len(indices) != 1: raise AssertionError('Require exactly the one retained failed overlap.')
    index = indices[0]; batch = deepcopy(wires[index]); row = deepcopy(three._proof(value)['cases'][CASE])
    outcome = validate_original_race(batch, row, value['company'])
    support = two._support()[0]; journal = support.Journal(value['journal_directory'])
    intents = [deepcopy(next(entry for entry in journal.rows if entry['operation_id'] == operation))
        for operation in (outcome['winner'], outcome['loser'])]
    original = {'schema': SCHEMA, 'at': two.stamp(), 'case': row, 'batch': batch, 'outcome': outcome,
        'batch_index': index, 'wire_count': len(wires), 'wire_prefix_sha256': [two.sha(wire) for wire in wires],
        'journal_intents': intents, 'manifest_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        'journal_sha256': hashlib.sha256(Path(journal.path).read_bytes()).hexdigest()}
    _journal_originals(journal.rows, original); attribution = _attribution(value, original)
    state = two.observe_native(path); native = verify_native_outcome(value, original, state)
    if two._run(path, row['run_id'])['payloads'] != row['terminal']['payloads']:
        raise AssertionError('Original terminal/preparation bytes changed after the retained overlap.')
    reference = _evidence(path, 'original-failure', original)
    two._proof(value)[KEY] = {'schema': SCHEMA, 'status': 'winner-and-loser-reconciled', 'original_failure': reference,
        'outcome': outcome, 'attribution': attribution, 'native_winner': native,
        'native_state_fingerprint': three._fingerprint(state), 'declared_at': two.stamp()}
    support.write_private(path, value)
    return {'status': 'winner-and-loser-reconciled', **outcome, 'original_failed_batch_unchanged': True}


def _retry_refusal(response):
    if response['status'] != 409: raise AssertionError('Require exactly the same original loser UUID to receive 409.')
    envelope = response['envelope']; error = envelope.get('error', {})
    if (set(error) != {'code', 'details', 'message', 'retryable'} or error['code'] != 'draft_already_saved'
            or error['details'] != {} or error['retryable'] is not False or type(error['message']) is not str or not error['message']):
        raise AssertionError('Require the actual nonretryable immutable-application refusal.')
    _envelope(envelope, error=error)


def retry_loser_once(path, base_url, host_header):
    """ROOT ONLY: one explicit exact-payload, same-UUID retry after reconciliation."""
    three = v3(); two = three.v2(); value = _value(path); proof = _proof(value)
    if proof['status'] != 'winner-and-loser-reconciled': raise RuntimeError('No automatic repeat of an entered v4 retry.')
    original = _read_reference(path, proof['original_failure']); support = two._support()[0]
    journal = support.Journal(value['journal_directory']); intents = _journal_originals(journal.rows, original)
    loser = intents[original['outcome']['loser']]; fields = {'company': value['company'], **original['case']['reviewed']}
    before = two.observe_native(path); verify_native_outcome(value, original, before)
    count = len(two._proof(value)['wires'])
    _update(path, status='same-uuid-retry-entered', retry_intent={'key': loser['key'], 'operation_id': loser['operation_id'],
        'payload_sha256': loser['payload_sha256'], 'wire_start_index': count, 'entered_at': two.stamp()})
    rpc = two.client(path, base_url, host_header)
    response = rpc.call(two.v1().SAVE + 'save_draft', fields, key=loser['key'], replay=True)
    _retry_refusal(response)
    current = _value(path); _journal_originals(support.Journal(value['journal_directory']).rows, original, retried=True)
    after = two.observe_native(path); three._no_effect(before, after); native = verify_native_outcome(current, original, after)
    if two._run(path, original['case']['run_id'])['payloads'] != original['case']['terminal']['payloads']:
        raise AssertionError('The reconciled same-UUID refusal rewrote original preparation bytes.')
    reference = _evidence(path, 'same-uuid-retry', {'response': response, 'before': three._fingerprint(before),
        'after': three._fingerprint(after), 'native_winner': native, 'wire_start_index': count,
        'wire_end_index': len(two._proof(current)['wires']), 'operation_id': loser['operation_id']})
    _update(path, status='same-uuid-retry-observed', retry_evidence=reference, retry_completed_at=two.stamp())
    # Independently rederive wire/journal binding before reporting a pass.
    validate_retry_ledger(_value(path), original, support.Journal(value['journal_directory']).rows,
                          _read_reference(path, reference))
    _update(path, status='passed_v4_adjudicated')
    return {'status': 'passed_v4_adjudicated', 'original_503_retained': True, 'retry_status': 409,
            'operation_id': loser['operation_id'], 'original_failed_batch_unchanged': True}


def validate_retry_ledger(value, original, journal, evidence):
    two = v3().v2(); proof = _proof(value); outcome = original['outcome']; rows = _journal_originals(journal, original, retried=True)
    loser = rows[outcome['loser']]; _retry_refusal(evidence['response'])
    if (loser['attempts'][1]['status'] != 409 or loser['attempts'][1]['envelope'] != evidence['response']['envelope']
            or proof['retry_intent']['operation_id'] != outcome['loser'] or evidence['operation_id'] != outcome['loser']
            or proof['retry_intent']['key'] != loser['key'] or proof['retry_intent']['payload_sha256'] != loser['payload_sha256']
            or proof['retry_intent']['wire_start_index'] != evidence['wire_start_index']):
        raise AssertionError('Retain original 503 plus one separately observed same-UUID 409 attempt.')
    wires = two._proof(value)['wires'][evidence['wire_start_index']:evidence['wire_end_index']]
    method = two.v1().SAVE + 'save_draft'
    if (len(wires) != 2 or wires[0]['method'] != 'GET' or wires[0]['path'] != '/api/method/cipher_aec.api.v1.session'
            or wires[0].get('operation_id') is not None or wires[1]['method'] != 'POST' or wires[1]['path'] != '/api/method/' + method
            or wires[1]['operation_id'] != outcome['loser'] or wires[1]['payload_sha256'] != loser['payload_sha256']
            or wires[1]['wire']['status'] != 409 or any(wire['role'] != 'author' or wire['status'] != 'verified' for wire in wires)):
        raise AssertionError('Require the one original-author authentication and exact observed retry POST only.')
    for wire in wires:
        if _time(wire['started_at']) > _time(wire['completed_at']): raise AssertionError('Invalid actual retry wire interval.')
    return True


def adjudicated_ledger(value, original):
    """Private verifier view only; original failed ledger/case bytes stay exact."""
    three = v3(); two = three.v2(); _original_retained(value, original)
    attribution = _attribution(value, original)
    if attribution != _proof(value)['attribution']: raise AssertionError('Stored overlap heartbeat attribution changed.')
    shadow = _saved_shadow(value, original); batch = two._proof(shadow)['wires'][original['batch_index']]
    batch.update(status='verified', started_at=original['outcome']['started_at'],
                 completed_at=original['outcome']['completed_at'], **attribution)
    return shadow


def verify_positive_epoch(before, positive, after):
    """Exact native columns for every post-positive-audit addition, no exception."""
    if set(before['inventory']) != set(positive['inventory']) or set(positive['inventory']) != set(after['inventory']):
        raise AssertionError('Positive-epoch native inventory table sets changed.')
    result = {}
    for table, rows in positive['inventory'].items():
        added = set(rows) - set(before['inventory'][table])
        for name in added:
            if after['inventory'][table].get(name) != rows[name]:
                raise AssertionError('An already-audited positive R15 native row changed: ' + table + '/' + name)
        if added: result[table] = sorted(added)
    return {'positive_epoch_rows_unchanged': True, 'positive_epoch_rows': sum(len(names) for names in result.values()),
            'positive_epoch_additions': result}


def audit(path, final_queue):
    """ROOT ONLY: v3 restoration + exact v2 preservation with explicit v4 outcome."""
    three = v3(); two = three.v2(); value = _value(path); proof = _proof(value); support = two._support()[0]
    if proof['status'] != 'passed_v4_adjudicated': raise RuntimeError('Finish the separately declared same-UUID adjudication first.')
    for case, row in three._proof(value)['cases'].items():
        if case != CASE and row['status'] != 'passed': raise RuntimeError('Every other distinct v3 boundary must actually pass.')
    if (final_queue['site'] != value['site'] or final_queue['queue'] != 'cipher-ai04-stage-a-20261016:short'
            or final_queue['jobs'] or final_queue['workers'] or final_queue['started_jobs']):
        raise AssertionError('Require the independently observed empty final ordinary runtime inventory.')
    original = _read_reference(path, proof['original_failure']); journal = support.Journal(value['journal_directory']).rows
    validate_retry_ledger(value, original, journal, _read_reference(path, proof['retry_evidence']))
    after = two.observe_native(path)
    if after['active_runs']: raise AssertionError('An active Company/Project Run remains.')
    verify_native_outcome(value, original, after)
    before = support.load_private(two._proof(value)['baseline']['path'])
    positive = support.load_private(three._proof(value)['baseline']['path'])
    positive_epoch = verify_positive_epoch(before, positive, after)
    positive_saved = {}
    for case in two.POSITIVE:
        checked = two.verify_saved_state(value, case, after, current=False)
        positive_saved[case] = {'application_digest': checked['application']['core_digest'],
            'receipt_id': checked['application']['receipt_id'], 'events_sha256': two.sha(checked['events'])}
    adjusted, restorations = three.restored_inventory(value, before, after)
    for case, row in three._proof(value)['cases'].items():
        if row.get('run_id') and two._run(path, row['run_id'])['payloads'] != row['terminal']['payloads']:
            raise AssertionError('An original boundary terminal/preparation payload changed.')
        if case != CASE and row.get('proposal_id') and any(item['value']['core']['proposal_id'] == row['proposal_id']
                for item in after['records']['Cipher Ricky Draft Save'].values()):
            raise AssertionError('A refused/probed suggestion acquired an application.')
    shadow = adjudicated_ledger(value, original)
    for case, row in three._proof(value)['cases'].items():
        if case != CASE: shadow['stages'][two.v1().KEY]['cases'][case] = deepcopy(row)
        for domain, target in row.get('targets', {}).items(): two._proof(shadow)['targets'][case + '-' + domain] = deepcopy(target)
    result = two.verify_preservation(shadow, before, adjusted, journal)
    reference = _evidence(path, 'final-audit', {'result': result, 'positive_epoch': positive_epoch,
        'positive_saved_applications': positive_saved, 'restorations': restorations, 'final_queue': final_queue,
        'original_failure': proof['original_failure'], 'retry_evidence': proof['retry_evidence'],
        'original_failed_batch_unchanged': True, 'v3_race_status_retained': original['case']['status']})
    _update(path, status='audited_v4_adjudicated', audit_evidence=reference, finished_at=two.stamp())
    return {'status': 'audited_v4_adjudicated', 'cases': len(three.CASES), 'supported_restorations': len(restorations),
        'overlap_batches': 1, 'original_overlap': '200/503 concurrent_change', 'same_uuid_retry': '409 draft_already_saved',
        'original_failed_batch_unchanged': True, **positive_epoch, **result}
