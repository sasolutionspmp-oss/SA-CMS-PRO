"""Explicit site-bound composed award acceptance; never a canonical fresh entry.

These procedures provision no identities, change no authority/profile, enable
no action and start no worker. Root must release each actual invocation. Review
is real cookie/CSRF; native probes observe real factories without replacing gates.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


ACTION = 'award.project.create.v1'
AWARD = 'cipher_aec.awards.api.'
GOV = 'cipher_aec.api.company_approvals.'
# Exact installed parent tables, not prefix matches against similarly named
# child tables. Native setup/chart maintenance is measured before these probes.
BUSINESS_TABLES = (
    'Project', 'Task', 'ToDo', 'DocShare', 'Sales Order', 'Sales Order Item',
    'Cipher Project Profile', 'Cipher Construction Contract',
    'Cipher Contract Revision', 'Cipher SOV Version', 'Cipher SOV Line', 'Cipher Retainage Policy Revision',
    'Cipher Budget Version', 'Cipher Budget Line', 'Cipher WBS Node',
    'Cipher Project Duty', 'Cipher Award Handoff', 'Cipher Award Handoff Revision',
    'Cipher Award Adoption', 'Cipher Award Line Adoption', 'Cipher History Event',
    'Cipher Approval Packet', 'Cipher Approval Decision', 'Cipher Approval Consumption',
    'Cipher Command Receipt', 'Quotation', 'Quotation Item',
    'Cipher Proposal Issue', 'Cipher Proposal Revision', 'Cipher Estimate Acceptance',
    'Cipher Cost Code', 'Cipher Cost Code Revision', 'Cipher Cost Type', 'Cipher Cost Type Revision',
    'Account', 'Cost Center', 'Currency', 'UOM', 'User Permission',
    'Version', 'File', 'Document Follow', 'Item Price', 'Payment Schedule',
    'Email Queue', 'Email Queue Recipient', 'Notification Log', 'Integration Request',
    'Cipher Integration Operation', 'Cipher Integration Attempt',
    'GL Entry', 'Stock Ledger Entry',
)
REQUIRED_TABLES = frozenset({
    'Project', 'Sales Order', 'Cipher Project Profile', 'Cipher Construction Contract',
    'Cipher Budget Version', 'Cipher Budget Line', 'Cipher WBS Node', 'Cipher Project Duty',
    'Cipher Award Adoption', 'Cipher Award Line Adoption', 'Cipher Award Handoff',
    'Cipher History Event', 'Cipher Approval Consumption', 'Cipher Command Receipt',
    'Version', 'File', 'Document Follow', 'Item Price', 'Payment Schedule',
})


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False, default=str).encode()).hexdigest()


def _save(path, value):
    """Exclusive durable artifacts: a second invocation cannot erase failure."""
    path = Path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, default=str, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _work(path):
    directory = Path(path)
    # Resume must deliberately consume the original context; never allocate a
    # second set of UUIDs by rerunning a procedure into an existing directory.
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    return directory


def _fixture(private_manifest):
    manifest = Path(private_manifest)
    if manifest.stat().st_mode & 0o077:
        raise RuntimeError('Credential manifests must have no group/other permissions.')
    value = json.loads(manifest.read_text())
    if value.get('setup_status') != 'ready' or not value.get('company'):
        raise RuntimeError('Use the explicitly prepared ready synthetic fixture.')
    users = value.get('users', {})
    for role in ('author', 'alias', 'reviewer'):
        if not users.get(role, {}).get('person') or not users[role].get('user'):
            raise RuntimeError('The exact author/alias/independent reviewer fixture is required.')
    if users['author']['person'] != users['alias']['person'] or users['author']['person'] == users['reviewer']['person']:
        raise RuntimeError('Alias and independent reviewer must have the declared canonical identities.')
    return value


def _source_binding(repository, release_manifest):
    """No implicit current-disk freeze: operator supplies the released epoch."""
    root = Path(repository).resolve()
    release = json.loads(Path(release_manifest).read_text())
    if release.get('schema') != 'cipher.award.acceptance-release.v1' or not release.get('runtime_epoch'):
        raise RuntimeError('Root must supply the explicit served-source release manifest.')
    expected = release.get('source_sha256')
    if not isinstance(expected, dict) or not expected:
        raise RuntimeError('A nonempty exact product/fixture source manifest is required.')
    for name, checksum in expected.items():
        path = root / name
        if Path(name).is_absolute() or root not in path.resolve().parents:
            raise RuntimeError('Release paths must remain inside the repository.')
        if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise RuntimeError('The released source changed; do not run a different epoch.')
    return {'runtime_epoch': release['runtime_epoch'], 'source_manifest_sha256': _hash(expected),
            'source_files': len(expected), 'qualification': 'Operator-declared served epoch plus exact on-disk equality.'}


def _rpc(private_manifest, repository, base_url, directory, release_manifest, host_header=None):
    from .test_company_chain_http_acceptance import CompanyHTTPRPC
    fixture = _fixture(private_manifest)
    binding = _source_binding(repository, release_manifest)
    work = _work(directory)
    return fixture, CompanyHTTPRPC(fixture, repository=repository, base_url=base_url,
                                  private_directory=str(work), host_header=host_header), binding


def _finish(rpc, report, repository, release_manifest):
    try:
        report['source_after'] = _source_binding(repository, release_manifest)
    except Exception as error:
        report['status'] = 'failed'
        report['source_after_failure'] = type(error).__name__
        raise
    finally:
        rpc.close()
        report.update(calls=rpc.calls, schema_samples=rpc.schema_samples,
                      session_timings=rpc.session_timings, completed_at=_now())
        _save(rpc.work / 'result.json', report)


def run_award_disabled_http(private_manifest, *, company_plan_context, repository,
                            base_url, private_directory, release_manifest, host_header=None):
    """Original disabled-action result; creates no plan or approval as setup.

    Pair with separately captured native inventories before/after. The supplied
    subject is a legitimately authored plan; malformed IDs cannot prove gating.
    """
    fixture, rpc, binding = _rpc(private_manifest, repository, base_url, private_directory, release_manifest, host_header)
    context = json.loads(Path(company_plan_context).read_text())
    report = {'schema': 'cipher.award.disabled-http.v1', 'status': 'failed',
              'started_at': _now(), 'source_before': binding, 'adoption_qualified': False}
    try:
        if context['company'] != fixture['company']:
            raise RuntimeError('Use only the exact owned Company plan.')
        rpc.login('author')
        subject = rpc.invoke(AWARD + 'approval_subject', {'company': fixture['company'], 'revision_id': context['plan']['id']})
        if subject['action_available'] is not False or subject['record_digest'] != _hash(context['plan']):
            raise AssertionError('The exact legitimate plan must advertise the disabled award action.')
        request = {'company': fixture['company'], 'action': ACTION, 'subject_id': context['plan']['id'],
                   'expected_version': subject['record_digest'], 'operation_id': str(uuid4())}
        # Literal error supplied by the central disabled-action contract.
        refusal = rpc.invoke(GOV + 'request_action', request, expected_codes={'approval_action_unqualified'})
        _save(rpc.work / 'disabled-request-context.json', {'company': fixture['company'], 'request': request, 'refusal': refusal})
        report.update(status='passed', subject_id=context['plan']['id'], denial=refusal,
                      qualification='Actual disabled request only; no-allocation inventory is a separate native observation.')
        return report
    finally:
        _finish(rpc, report, repository, release_manifest)


def run_award_plan_http(private_manifest, *, authored_context, repository, base_url,
                       private_directory, release_manifest, host_header=None):
    """Legitimate Company plan commands; caller supplies reviewed fixture inputs."""
    fixture, rpc, binding = _rpc(private_manifest, repository, base_url, private_directory, release_manifest, host_header)
    authored = json.loads(Path(authored_context).read_text())
    report = {'schema': 'cipher.award.plan-http.v1', 'status': 'failed', 'started_at': _now(),
              'source_before': binding, 'adoption_qualified': False}
    try:
        company = fixture['company']; definition = authored['definition']
        if authored['company'] != company or definition['issue_id'] != authored['issue']['id']:
            raise RuntimeError('Use an actual immutable owned Issue and explicit authored definition.')
        if fixture['users']['author']['person'] in {row['person_id'] for row in definition['team']['members']}:
            raise RuntimeError('The principal independent fixture excludes the requester from its team.')
        rpc.login('author')
        create = {'company': company, 'issue_id': authored['issue']['id'], 'operation_id': str(uuid4())}
        created = rpc.invoke(AWARD + 'create_handoff', create)
        rpc.login('alias'); replay = rpc.invoke(AWARD + 'create_handoff', create)
        if not replay['operation']['replayed'] or replay['handoff'] != created['handoff']:
            raise AssertionError('Canonical alias created a second aggregate.')
        command = {'company': company, 'handoff_id': created['handoff']['id'], 'expected_version': created['version'],
                   'definition': definition, 'operation_id': str(uuid4())}
        rpc.login('author'); planned = rpc.invoke(AWARD + 'plan_handoff', command)
        rpc.login('alias'); replay = rpc.invoke(AWARD + 'plan_handoff', command)
        if not replay['operation']['replayed'] or replay['plan'] != planned['plan']:
            raise AssertionError('Canonical alias changed the immutable reviewed plan.')
        altered = deepcopy(command)
        altered['definition']['project_definition']['project_name'] += ' changed'
        rpc.invoke(AWARD + 'plan_handoff', altered, expected_codes={'operation_conflict'})
        rpc.invoke(AWARD + 'plan_handoff', {**command, 'operation_id': str(uuid4())}, expected_codes={'stale_award'})
        rpc.invoke(AWARD + 'create_handoff', {**create, 'operation_id': str(uuid4())}, expected_codes={'handoff_exists'})
        actual = rpc.invoke(AWARD + 'get_plan', {'company': company, 'revision_id': planned['plan']['id']})
        if actual['plan'] != planned['plan'] or actual['version'] != planned['version']:
            raise AssertionError('The original plan/version changed on readback.')
        durable = {'company': company, 'issue': authored['issue'], 'create': create, 'command': command,
                   'plan': planned['plan'], 'version': planned['version'], 'handoff': planned['handoff']}
        _save(rpc.work / 'award-plan-context.json', durable)
        report.update(status='passed', handoff_id=planned['handoff']['id'], revision_id=planned['plan']['id'],
                      qualification='Actual authoring/read/replay; no approval execution or Project allocation claim.')
        return report
    finally:
        _finish(rpc, report, repository, release_manifest)


def run_award_grant_http(private_manifest, *, company_plan_context, repository,
                        base_url, private_directory, release_manifest, host_header=None):
    """Request, actual same-Person refusal, independent cookie Grant; NO execute."""
    fixture, rpc, binding = _rpc(private_manifest, repository, base_url, private_directory, release_manifest, host_header)
    context = json.loads(Path(company_plan_context).read_text())
    report = {'schema': 'cipher.award.grant-http.v1', 'status': 'failed', 'started_at': _now(),
              'source_before': binding, 'adoption_qualified': False}
    try:
        company = fixture['company']
        if context['company'] != company or context['plan']['author_person'] != fixture['users']['author']['person']:
            raise RuntimeError('Use the exact original author plan.')
        rpc.login('author')
        request = {'company': company, 'action': ACTION, 'subject_id': context['plan']['id'],
                   'expected_version': context['version'], 'operation_id': str(uuid4())}
        packet = rpc.invoke(GOV + 'request_action', request)['packet']
        _save(rpc.work / 'requested-context.json', {**context, 'request': request, 'packet': packet})
        denied = {'company': company, 'packet_id': packet['id'], 'manifest_hash': packet['manifest_hash'],
                  'decision': 'Grant', 'reason': 'Same canonical author must be refused.', 'operation_id': str(uuid4())}
        rpc.login('alias'); rpc.invoke(GOV + 'decide_packet', denied, expected_codes={'independent_review_required', 'independent_award_review_required'})
        decision = {**denied, 'reason': 'Independent exact source, native, budget and bounded initial team review.', 'operation_id': str(uuid4())}
        rpc.login('reviewer'); granted = rpc.invoke(GOV + 'decide_packet', decision)['packet']
        if granted['state'] != 'Granted' or granted['manifest_hash'] != packet['manifest_hash']:
            raise AssertionError('Independent cookie review did not grant the exact immutable plan.')
        execute = {'company': company, 'packet_id': packet['id'], 'manifest_hash': packet['manifest_hash'], 'operation_id': str(uuid4())}
        _save(rpc.work / 'granted-context.json', {**context, 'request': request, 'packet': granted,
                                                'denied_alias_decision': denied, 'decision': decision, 'execute': execute})
        report.update(status='passed', packet_id=packet['id'], state='Granted',
                      qualification='Actual request/independent interactive Grant only. Execute UUID reserved and never sent.')
        return report
    finally:
        _finish(rpc, report, repository, release_manifest)


def _capture_award_inventory(db, *, company, maximum_rows=10000):
    """Observe the CURRENT transaction without changing/closing it in any way."""
    if type(maximum_rows) is not int or not 1 <= maximum_rows <= 10000:
        raise RuntimeError('Inventory must remain bounded.')
    result = {'schema': 'cipher.award.sql-inventory.v1', 'company': company, 'recorded_at': _now(),
              'tables': {}, 'absent_tables': [], 'qualification': 'Read-only SQL inventory, no callback/Redis assertion.'}
    for doctype in BUSINESS_TABLES:
        if not db.table_exists(doctype):
            if doctype in REQUIRED_TABLES:
                raise RuntimeError('A required finite award write/transitive table is not installed.')
            result['absent_tables'].append(doctype); continue
        rows = db.sql('SELECT * FROM `tab' + doctype + '` ORDER BY name LIMIT %s', (maximum_rows + 1,), as_dict=True)
        if len(rows) > maximum_rows:
            raise RuntimeError('An exact award inventory exceeded its declared bound; no preservation pass.')
        records = {row['name']: _hash(dict(row)) for row in rows}
        result['tables'][doctype] = {'count': len(records), 'records': records, 'sha256': _hash(records)}
    return result


def capture_award_inventory(*, company, maximum_rows=10000):
    """One fresh bench invocation: exact whole-table hashes, no writes/commits.

    Whole-site measurement deliberately exposes only names/hashes to private
    operator evidence. Unrelated concurrent writers invalidate a rollback proof.
    This is SQL only; callback and external queue observations remain separate.
    """
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site
    assert_synthetic_site()
    if frappe.session.user != 'Administrator' or not frappe.db.exists('Company', company):
        raise RuntimeError('Use a fresh synthetic operator invocation on the isolated fixture site.')
    try:
        return _capture_award_inventory(frappe.db, company=company, maximum_rows=maximum_rows)
    finally:
        frappe.db.rollback()


def run_award_execute_http(private_manifest, *, granted_context, repository, base_url,
                          private_directory, release_manifest, host_header=None):
    """One original execute/retry with no native fault or authority mutation.

    A fresh private_directory can deliberately retry an uncertain original
    granted_context: its reserved execute body/UUID is never regenerated.
    """
    fixture, rpc, binding = _rpc(private_manifest, repository, base_url, private_directory, release_manifest, host_header)
    context = json.loads(Path(granted_context).read_text())
    report = {'schema': 'cipher.award.execute-http.v1', 'status': 'failed', 'started_at': _now(),
              'source_before': binding, 'native_inventory_qualified': False}
    try:
        company = fixture['company']; execute = context['execute']; plan = context['plan']
        if (context['company'] != company or execute['company'] != company
                or execute['packet_id'] != context['packet']['id']
                or execute['manifest_hash'] != context['packet']['manifest_hash']):
            raise RuntimeError('Retry only the original independently Granted context and exact execute request.')
        requester = fixture['users']['author']['person']
        if requester in {row['person_id'] for row in plan['definition']['team']['members']}:
            raise RuntimeError('This qualification requires the requester outside the exact approved team.')
        rpc.login('author'); consumed = rpc.invoke(GOV + 'execute_packet', execute)
        # Save the known success before optional subsequent assertions/reads.
        _save(rpc.work / 'execute-response.json', consumed)
        adoption = consumed['effect']['adoption']; exact = adoption['effect_binding']
        expected = {'company': company, 'project': adoption['target_project'], 'award_id': plan['handoff'],
                    'award_revision_id': plan['id'], 'plan_digest': context['version'],
                    'packet_id': execute['packet_id'], 'decision_id': adoption['decision_id'], 'operation_id': execute['operation_id']}
        if exact != expected or consumed['packet']['state'] != 'Consumed' or adoption['team'] != plan['definition']['team']['members']:
            raise AssertionError('The committed adoption differs from the exact reviewed effect/team.')
        rpc.login('alias'); replay = rpc.invoke(GOV + 'execute_packet', execute)
        if not replay['operation']['replayed'] or replay['effect'] != consumed['effect']:
            raise AssertionError('Canonical alias retry changed the one committed award effect.')
        current = rpc.invoke(AWARD + 'get_handoff', {'company': company, 'handoff_id': plan['handoff']})
        if (current['adoption'] != adoption or current['project_access'] != {'standing': 'not_available', 'project_id': adoption['target_project']}):
            raise AssertionError('Excluded requester received implicit destination access or the adoption changed.')
        rpc.invoke('cipher_aec.api.v1.project', {'company': company, 'project': adoption['target_project']},
                   expected_codes={'not_found', 'capability_denied'})
        _save(rpc.work / 'adopted-context.json', {**context, 'execute_response': consumed, 'adoption': adoption})
        report.update(status='passed', adoption_id=adoption['id'], target_project=adoption['target_project'],
                      packet_id=execute['packet_id'], operation_id=execute['operation_id'], requester_project_access='not_available',
                      qualification='Actual execute/replay/read and excluded requester refusal only; native amounts, uniqueness and external intent inventories remain separate.')
        return report
    finally:
        _finish(rpc, report, repository, release_manifest)


def compare_award_inventory(before, after):
    """No allowed-table blanket: return every exact inserted/deleted/changed ID."""
    if before['company'] != after['company'] or before['absent_tables'] != after['absent_tables'] or before['tables'].keys() != after['tables'].keys():
        raise AssertionError('The inventory scope or installed native catalog changed.')
    delta = {}
    for table, old in before['tables'].items():
        prior = old['records']; current = after['tables'][table]['records']
        inserted = sorted(current.keys() - prior.keys()); deleted = sorted(prior.keys() - current.keys())
        changed = sorted(name for name in prior.keys() & current.keys() if prior[name] != current[name])
        if inserted or deleted or changed:
            delta[table] = {'inserted': inserted, 'deleted': deleted, 'changed': changed}
    return {'unchanged': not delta, 'delta': delta, 'tables_compared': len(before['tables'])}


def assert_product_rollback(before, read_current_inventory):
    """MUST run before harness cleanup; this function never rolls anything back."""
    after = read_current_inventory()
    comparison = compare_award_inventory(before, after)
    if not comparison['unchanged']:
        raise AssertionError('Product rollback left authoritative SQL residue before fixture cleanup: '
                             + ', '.join(sorted(comparison['delta'])))
    return after, comparison


def _identical_sequence(actual, expected):
    return len(actual) == len(expected) and all(a is b for a, b in zip(actual, expected))


def run_award_rollback_probe(private_manifest, *, granted_context, scenario, private_directory,
                             expected_refusal_codes, repository, release_manifest):
    """Real execute with observation-only stage or exact late-receipt fault.

    Prerequisite rights revocation happens separately BEFORE invocation, under
    root's explicit fixture slot. No permission/session/profile gate is mocked.
    This probe never commits, and cannot establish HTTP execution qualification.
    """
    import frappe
    from unittest.mock import patch
    from frappe.model.document import Document
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance import approvals
    from cipher_aec.governance.context import assert_synthetic_site, current_actor
    from cipher_aec.awards import preallocation, runtime
    assert_synthetic_site()
    if frappe.session.user != 'Administrator':
        raise RuntimeError('Use a fresh isolated synthetic bench invocation.')
    if scenario not in {'post_preallocation_refusal', 'late_receipt_failure'}:
        raise RuntimeError('Select one explicit controlled rollback case.')
    if (type(expected_refusal_codes) is not list or not expected_refusal_codes
            or any(type(value) is not str for value in expected_refusal_codes)):
        raise RuntimeError('Name the specific refusal contract before execution.')
    if scenario == 'late_receipt_failure' and expected_refusal_codes != ['fixture_late_award_receipt_failure']:
        raise RuntimeError('The late receipt probe requires its exact injected refusal.')
    fixture = _fixture(private_manifest); context = json.loads(Path(granted_context).read_text())
    company = fixture['company']; execute = context['execute']
    if context['company'] != company or execute['company'] != company or context['packet']['state'] != 'Granted':
        raise RuntimeError('Use the exact real independently Granted fixture context.')
    binding = _source_binding(repository, release_manifest)
    work = _work(private_directory)
    report = {'schema': 'cipher.award.native-rollback-probe.v1', 'status': 'failed', 'scenario': scenario,
              'company': company, 'operation_id': execute['operation_id'], 'started_at': _now(),
              'source_before': binding,
              'stage_observed': False, 'receipt_fault_observed': False, 'committed': False,
              'qualification': 'Native controlled execution only; fresh independent SQL/queue preservation readback required.'}
    # This lazily active command has no fixture-owned setup callbacks. Preserve
    # actual preexisting prefixes, including content identity of local intents.
    local_before = {name: tuple(runtime._local_queue(name) or []) for name in runtime.LOCAL_QUEUES}
    # Same-connection reads never roll back. Retained uncommitted rows must be
    # detected before the fixture's eventual finally cleanup can erase them.
    sql_before = _capture_award_inventory(frappe.db, company=company)
    _save(work / 'sql-before-command.json', sql_before)
    stage = preallocation.stage; insert = Document.insert
    stage_prefix = None
    @contextmanager
    def observed(*args, **kwargs):
        nonlocal stage_prefix
        stage_prefix = {name: runtime._contents(getattr(frappe.db, name)) for name in runtime.MANAGERS}
        report['preexisting_callback_counts'] = {name: len(callbacks) for name, callbacks in stage_prefix.items()}
        with stage(*args, **kwargs) as allocated:
            actual = frappe.db.sql('SELECT name,company FROM `tabProject` WHERE name=%s', (allocated['project'],))
            if actual != ((allocated['project'], company),) and list(actual) != [(allocated['project'], company)]:
                raise AssertionError('Real minimal Project allocation was not observed.')
            profile = frappe.db.sql('SELECT record_digest FROM `tabCipher Project Profile` WHERE project=%s', (allocated['project'],))
            if len(profile) != 1:
                raise AssertionError('Real minimal profile allocation was not observed.')
            report.update(stage_observed=True, transient_project=allocated['project'], transient_profile_sha256=profile[0][0])
            _save(work / 'allocated-before-refusal.json', {**report, 'observed_at': _now()})
            yield allocated
    def fail_exact_receipt(doc, *args, **kwargs):
        result = insert(doc, *args, **kwargs)
        if (doc.doctype == 'Cipher Command Receipt' and doc.company == company
                and doc.operation_id == execute['operation_id'] and doc.person == fixture['users']['author']['person']):
            if not report['stage_observed'] or json.loads(doc.result_json)['effect']['adoption']['effect_binding']['operation_id'] != execute['operation_id']:
                raise AssertionError('Late fault did not follow the real complete award effect.')
            report['receipt_fault_observed'] = True
            _save(work / 'receipt-inserted-before-fault.json', {'operation_id': execute['operation_id'], 'result_hash': doc.result_hash, 'observed_at': _now()})
            raise DomainError('fixture_late_award_receipt_failure', 'Controlled isolated exact receipt fault.', 409)
        return result
    try:
        frappe.set_user(fixture['users']['author']['user'])
        if current_actor().person_id != fixture['users']['author']['person']:
            raise RuntimeError('Native fixture identity binding changed.')
        with patch.object(preallocation, 'stage', observed), patch.object(Document, 'insert', fail_exact_receipt if scenario == 'late_receipt_failure' else insert):
            try:
                approvals.execute_packet(company, None, execute['packet_id'], execute['manifest_hash'], execute['operation_id'], scope_type='Company')
            except DomainError as error:
                report.update(error_code=error.code, error_status=error.status)
                if not report['stage_observed']:
                    raise AssertionError('Refusal happened before allocation; this does not prove post-allocation rollback.') from error
                if scenario == 'late_receipt_failure' and (not report['receipt_fault_observed'] or error.code != 'fixture_late_award_receipt_failure'):
                    raise AssertionError('Execution refused before the exact late receipt seam.') from error
                if error.code not in expected_refusal_codes:
                    raise AssertionError('The actual refusal differs from the declared authority/fault contract.') from error
            else:
                raise AssertionError('Rollback fixture unexpectedly executed; no commit is allowed.')
        sql_after = _capture_award_inventory(frappe.db, company=company)
        _save(work / 'sql-after-product-before-cleanup.json', sql_after)
        _, report['pre_cleanup_sql_comparison'] = assert_product_rollback(sql_before, lambda: sql_after)
        if stage_prefix is not None:
            # Prefix identity is meaningful only within this connection. It is
            # separate from fresh-connection SQL persistence observations.
            report['callback_prefix_preserved'] = all(_identical_sequence(runtime._contents(getattr(frappe.db, name)), callbacks) for name, callbacks in stage_prefix.items())
            if not report['callback_prefix_preserved']:
                raise AssertionError('The failed award changed its preallocation callback prefix.')
        report['local_intent_prefix_preserved'] = all(
            _identical_sequence(tuple(runtime._local_queue(name) or []), prefix) for name, prefix in local_before.items())
        if not report['local_intent_prefix_preserved']:
            raise AssertionError('The failed award left or changed native local webhook/realtime intents.')
        report['status'] = 'probe_completed_requires_independent_readback'
        return report
    finally:
        try:
            frappe.db.rollback(); frappe.set_user('Administrator')
        finally:
            try:
                report['source_after'] = _source_binding(repository, release_manifest)
            except Exception as error:
                report.update(status='failed', source_after_failure=type(error).__name__)
                raise
            finally:
                report['completed_at'] = _now(); _save(work / 'result.json', report)
