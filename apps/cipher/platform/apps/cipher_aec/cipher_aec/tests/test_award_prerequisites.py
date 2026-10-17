"""Opt-in legitimate award prerequisites on a root-selected isolated site.

No runtime invocation occurs on import. Native identity/master setup is one
explicit serial operator stage; all baseline/Issue reviews use real cookies.
There is no fake accepted JSON, session impersonation or award activation.
"""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .test_award_composed_acceptance import _fixture, _hash, _now, _save, _source_binding, _work


def require_original_release(binding, intent, *, fixture_id=None):
    """A replacement manifest at the original path cannot authorize recovery."""
    if intent.get('source_before') != binding or (fixture_id is not None and intent.get('fixture_id') != fixture_id):
        raise RuntimeError('Recovery requires its exact original source epoch and fixture identity before any native effect.')


def prepare_award_prerequisites(*, private_directory, repository, release_manifest):
    """ONE USE, serial User/Auth slot. Creates fresh unique canonical fixtures.

    The already reviewed Company fixture primitive provisions native masters,
    scoped identities and an unrelated Project control. Its native provisioning
    is separate from the subsequent journaled HTTP baseline/Issue commands.
    It durably saves new credentials before its first commit. On interruption,
    retain that original manifest; never rerun to allocate replacement identities.
    """
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site
    from .test_company_chain_acceptance import prepare_fixture
    from .test_award_composed_acceptance import _capture_award_inventory
    assert_synthetic_site()
    if frappe.session.user != 'Administrator':
        raise RuntimeError('Only the explicit isolated operator identity setup slot may run this stage.')
    binding = _source_binding(repository, release_manifest); work = _work(private_directory)
    existing_manifests = sorted(p.name for p in Path(frappe.get_site_path('private', 'cipher-fixtures')).glob('company-chain-*.secret.json'))
    _save(work / 'setup-intent.json', {'started_at': _now(), 'source_before': binding,
          'repository': str(Path(repository).resolve()), 'release_manifest': str(Path(release_manifest).resolve()),
          'site': frappe.local.site, 'existing_private_manifest_names': existing_manifests,
          'primitive': 'test_company_chain_acceptance.prepare_fixture(require_historical=False)',
          'on_interruption': 'Recover the original newly durable private manifest; do not allocate new identities.'})
    before = _capture_award_inventory(frappe.db, company='pre-setup-isolated-site')
    _save(work / 'before-business-inventory.json', before)
    accounts = frappe.db.sql('SELECT * FROM `tabAccount` ORDER BY name LIMIT 10001', as_dict=True)
    if len(accounts) > 10000:
        raise RuntimeError('Exact original Account attribution exceeds the fixture bound.')
    _save(work / 'original-full-account-rows.json', [dict(row) for row in accounts])
    frappe.db.rollback()
    result = prepare_fixture(require_historical=False, setup_journal_directory=str(work))
    # The native primitive has durably saved credentials; this safe result never
    # returns password values, only the private manifest FILEPATH and native IDs.
    if json.loads((work / 'base-setup-result.json').read_text()) != json.loads(json.dumps(result, default=str)):
        raise RuntimeError('The original completed base fixture result changed.')
    return {'status': 'base_setup_created_requires_completion', 'private_manifest': result['private_manifest'],
            'company': result['company'], 'fixture_id': result['fixture_id'],
            'next': 'complete_award_prerequisites with the SAME private manifest and original setup directory'}


def resume_award_base_fixture(private_manifest, *, setup_directory):
    """Recover the ORIGINAL native count-unit and Project-control Task intents.

    Called after the initial identity commit, or explicitly after interruption.
    Never creates Users/Company/Project or changes an original password.
    """
    import frappe
    from .test_company_chain_acceptance import _load_fixture, _save_private_fixture, _capture_project_controls, _native_financial_inventory
    from cipher_aec.estimating.company_service import register_unit
    from cipher_aec.projects.service import create_task
    fixture = _load_fixture(private_manifest); work = Path(setup_directory)
    setup_release = json.loads((work / 'setup-intent.json').read_text())
    binding = _source_binding(setup_release['repository'], setup_release['release_manifest'])
    require_original_release(binding, setup_release)
    intent = json.loads((work / 'base-native-command-intents.json').read_text())
    if (intent['site'] != frappe.local.site or intent['fixture_id'] != fixture['fixture_id']
            or intent['unit']['company'] != fixture['company'] or intent['unit']['uom'] != fixture['native_unit']
            or intent['task']['company'] != fixture['other_company'] or intent['task_actor'] != fixture['users']['project_only']['user']):
        raise RuntimeError('Original native setup identities and durable command scope must agree.')
    if fixture['setup_status'] not in {'prerequisites_created', 'ready'}:
        raise RuntimeError('No recoverable original native setup phase exists.')
    for company in (fixture['company'], fixture['other_company']):
        if not frappe.db.exists('Company', company):
            raise RuntimeError('Original setup did not commit. Do not invent replacement identities in recovery.')
    if not frappe.db.exists('Project', {'name': intent['task']['project'], 'company': fixture['other_company']}):
        raise RuntimeError('The original independent Project control is missing.')
    try:
        if fixture['setup_status'] != 'ready':
            unit = register_unit(**intent['unit'])['unit']; frappe.db.commit()
            frappe.set_user(intent['task_actor'])
            task = create_task(**intent['task']); frappe.db.commit()
            frappe.set_user('Administrator')
            project_control = {'project': intent['task']['project'], 'operation_id': intent['task']['operation_id'],
                               'task_id': task['task']['id'], 'immutable_rows': _capture_project_controls(intent['task']['project'])}
            fixture.update(created_at=intent['created_at'], qualified_unit=unit, project_only_control=intent['task']['project'],
                           project_receipt_control=project_control, historical_project_control=intent['historical_project_control'],
                           native_financial_before=_native_financial_inventory(fixture['company']),
                           project_count_before_company_journey=frappe.db.count('Project'), setup_status='ready',
                           qualification='Fixture setup only; no DOC/estimate/approval/proposal outcome qualified yet.')
            _save_private_fixture(fixture)
        result = {**{key: value for key, value in fixture.items() if key != 'users'},
                  'users': {key: {'user': value['user'], 'person': value['person']} for key, value in fixture['users'].items()},
                  'private_manifest': str(Path(private_manifest).resolve())}
        if _source_binding(setup_release['repository'], setup_release['release_manifest']) != binding:
            raise RuntimeError('The original native prerequisite source epoch changed.')
        target = work / 'base-setup-result.json'
        if not target.exists():
            _save(target, result)
        elif json.loads(target.read_text()) != json.loads(json.dumps(result, default=str)):
            raise RuntimeError('The recovered original native fixture result changed.')
        return result
    finally:
        frappe.db.rollback(); frappe.set_user('Administrator')


def complete_award_prerequisites(private_manifest, *, setup_directory, repository, release_manifest):
    """Resumable completion of only the newly owned roles/native prerequisites.

    No old identity password, role, Company or profile is changed. Exact native
    authoring and unit-registration command intents are saved before effects.
    """
    import frappe
    from frappe.permissions import add_permission, update_permission_property
    from cipher_aec.governance.context import assert_synthetic_site, trusted_write
    from cipher_aec.install import _grant_company
    from cipher_aec.awards import team
    from cipher_aec.estimating.company_service import register_unit
    assert_synthetic_site()
    if frappe.session.user != 'Administrator':
        raise RuntimeError('Complete setup only in the explicit serial operator slot.')
    fixture = _fixture(private_manifest); work = Path(setup_directory)
    if json.loads((work / 'base-setup-result.json').read_text())['private_manifest'] != str(Path(private_manifest).resolve()):
        raise RuntimeError('Completion must retain the original unique fixture manifest.')
    binding = _source_binding(repository, release_manifest); company = fixture['company']
    pending = work / 'completion-intent.json'
    if pending.exists():
        intent = json.loads(pending.read_text())
    else:
        intent = {'company': company, 'fixture_id': fixture['fixture_id'], 'source_before': binding,
                  'units': {kind: {'name': 'Award ' + kind + ' ' + fixture['fixture_id'], 'operation_id': str(uuid4())}
                            for kind in ('labor_time', 'equipment_time')}}
        _save(pending, intent)
    if intent['company'] != company:
        raise RuntimeError('Cannot retarget native completion.')
    require_original_release(binding, intent, fixture_id=fixture['fixture_id'])
    with trusted_write():
        for role in (fixture['native_role'], fixture['reviewer_native_role']):
            add_permission('Cost Center', role, 0)
            for permission in ('read', 'select'):
                update_permission_property('Cost Center', role, 0, permission, 1)
        for doctype in ('Project', 'Sales Order'):
            add_permission(doctype, fixture['native_role'], 0)
            update_permission_property(doctype, fixture['native_role'], 0, 'create', 1)
        _grant_company(fixture['users']['reviewer']['person'], company, 'project.cost.read')
        # Separate canonical member; no Company source/write/delegator grant.
        _grant_company(fixture['users']['project_only']['person'], company, 'company.read')
        for kind, item in intent['units'].items():
            if not frappe.db.exists('UOM', item['name']):
                frappe.get_doc({'doctype': 'UOM', 'uom_name': item['name'], 'symbol': kind + '-' + fixture['fixture_id'],
                                'enabled': 1, 'must_be_whole_number': 0}).insert(ignore_permissions=True)
    # Commit newly scoped provisioning before canonical unit commands. Their
    # complete original intent/UUID is already durable and replayable.
    frappe.db.commit()
    units = {'count': fixture['qualified_unit']}
    for kind, item in intent['units'].items():
        units[kind] = register_unit(company, item['operation_id'], item['name'], kind, 6)['unit']
        frappe.db.commit()
    policy = team.install_policy(company); frappe.db.commit()
    costs = frappe.db.sql('SELECT name FROM `tabCost Center` WHERE company=%s AND is_group=0 AND disabled=0 ORDER BY name LIMIT 1', (company,))
    accounts = frappe.db.sql("SELECT name FROM `tabAccount` WHERE company=%s AND is_group=0 AND disabled=0 AND root_type='Expense' ORDER BY name LIMIT 1", (company,))
    if not costs or not accounts:
        raise RuntimeError('Supported new Company must supply real eligible leaf accounting targets.')
    # Policy installation for EST/Issue is an existing supported install/root
    # prerequisite; this fixture never enables a registry action or inserts Grant.
    for action in ('estimate.accept.v1', 'proposal.issue.v1'):
        if not frappe.db.exists('Cipher Approval Policy Revision', {'action': action, 'scope_type': 'Company', 'enabled': 1}):
            raise RuntimeError('Root must install the existing supported Company approval policy before HTTP setup.')
    for user in fixture['users'].values():
        frappe.clear_cache(user=user['user'])
    completed = {'company': company, 'fixture_id': fixture['fixture_id'], 'units': units, 'team_policy': policy,
                 'team_person': fixture['users']['project_only']['person'],
                 'cost_center': costs[0][0], 'expense_account': accounts[0][0],
                 'private_manifest': str(Path(private_manifest).resolve()), 'source_after': _source_binding(repository, release_manifest),
                 'qualification': 'Native prerequisite setup only; no accepted baseline/Issue/award created.'}
    target = work / 'native-prerequisites.json'
    if target.exists():
        prior = json.loads(target.read_text())
        if {k: v for k, v in prior.items() if k != 'source_after'} != {k: v for k, v in completed.items() if k != 'source_after'}:
            raise RuntimeError('Completed native prerequisite facts changed; do not rebaseline.')
        return prior
    _save(target, completed); return completed


def inspect_award_setup_preservation(private_manifest, *, setup_directory):
    """Separate fresh operator readback: attribute, never repair/rebaseline.

    Whole old-row hashes are retained separately from equal non-tree columns;
    supported Company/chart setup may change Account lft/rgt. Unexpected original
    row deletion/change remains unresolved. No native row is written here.
    """
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site
    from .test_award_composed_acceptance import _capture_award_inventory, compare_award_inventory
    assert_synthetic_site()
    if frappe.session.user != 'Administrator':
        raise RuntimeError('Use a fresh explicit operator readback connection.')
    fixture = _fixture(private_manifest); work = Path(setup_directory)
    old_rows = json.loads((work / 'original-full-account-rows.json').read_text())
    before = json.loads((work / 'before-business-inventory.json').read_text())
    try:
        rows = frappe.db.sql('SELECT * FROM `tabAccount` ORDER BY name LIMIT 10001', as_dict=True)
        if len(rows) > 10000:
            raise RuntimeError('Account attribution exceeds its exact bounded inventory.')
        # Normalize actual SQL date/Decimal values through the same private JSON
        # representation as the original retained full-row artifact.
        current = {row['name']: json.loads(json.dumps(dict(row), default=str)) for row in rows}
        original = {row['name']: row for row in old_rows}; delta = {}; unresolved = []
        for name, old in original.items():
            if name not in current:
                unresolved.append({'name': name, 'reason': 'missing_original'}); continue
            differences = {key: {'before': old.get(key), 'after': current[name].get(key)}
                           for key in old.keys() | current[name].keys() if old.get(key) != current[name].get(key)}
            if differences:
                delta[name] = differences
                if set(differences) - {'lft', 'rgt'}:
                    unresolved.append({'name': name, 'reason': 'non_tree_original_change', 'fields': sorted(set(differences) - {'lft', 'rgt'})})
        def ancestor_pairs(values):
            stack = []; result = []
            for row in sorted(values, key=lambda value: int(value['lft'])):
                left, right = int(row['lft']), int(row['rgt'])
                if left >= right:
                    raise AssertionError('Original Account intervals are not a qualified tree.')
                while stack and int(stack[-1]['rgt']) < left:
                    stack.pop()
                for ancestor in stack:
                    if int(ancestor['rgt']) <= right:
                        raise AssertionError('Original Account intervals cross after setup.')
                    result.append((ancestor['name'], row['name']))
                stack.append(row)
            return sorted(result)
        ancestor_before = ancestor_pairs(old_rows)
        ancestor_after = ancestor_pairs([current[name] for name in original if name in current])
        if ancestor_before != ancestor_after:
            unresolved.append({'reason': 'original_ancestor_relation_changed'})
        # Full whole-site old-row inventory scope uses the same operator label;
        # new Company rows are shown as insertions, never compared as originals.
        after = _capture_award_inventory(frappe.db, company=before['company'])
        comparison = compare_award_inventory(before, after)
        for table, difference in comparison['delta'].items():
            if difference['deleted'] or (difference['changed'] and table != 'Account'):
                unresolved.append({'table': table, 'reason': 'unexpected_original_row_difference',
                                   'deleted': difference['deleted'], 'changed': difference['changed']})
        result = {'schema': 'cipher.award.setup-preservation.v1', 'status': 'unresolved' if unresolved else 'attributed',
                  'company': fixture['company'], 'original_account_rows': len(original), 'original_account_deltas': delta,
                  'full_original_account_rows_unchanged': not delta and not any(name not in current for name in original),
                  'non_tree_original_columns_unchanged': not any(set(fields) - {'lft', 'rgt'} for fields in delta.values()) and all(name in current for name in original),
                  'original_ancestor_relations_unchanged': ancestor_before == ancestor_after, 'original_ancestor_pairs': len(ancestor_before),
                  'new_account_companies': sorted({current[name]['company'] for name in current.keys() - original.keys()}),
                  'all_business_inventory_comparison': comparison, 'unresolved': unresolved,
                  'attribution': 'Only verified native Company/chart setup lft/rgt maintenance may be attributed; no original authoritative field repair performed.'}
        foreign_new_companies = set(result['new_account_companies']) - {fixture['company'], fixture['other_company']}
        if foreign_new_companies:
            result['unresolved'].append({'reason': 'new_account_outside_exact_fixture_companies', 'companies': sorted(foreign_new_companies)})
            result['status'] = 'unresolved'
        _save(work / ('preservation-' + uuid4().hex + '.json'), result)
        return result
    finally:
        frappe.db.rollback()


class PrerequisiteRPC:
    """Persistent per-step original intents/results around the real HTTP client.

    Known completed command responses are reused as stage data. Every later
    server command still performs its real current authorization. Unknown sends
    retry the exact original UUID/body, never a newly constructed replacement.
    """
    def __init__(self, rpc, directory):
        self.rpc = rpc; self.work = Path(directory); self.work.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.reused = []

    def login(self, role):
        self.rpc.login(role)

    def command(self, step, method, body, *, expected_codes=()):
        if not step.replace('-', '').isalnum():
            raise RuntimeError('Use a bounded fixed prerequisite step name.')
        request_path = self.work / (step + '.request.json'); response_path = self.work / (step + '.response.json')
        if request_path.exists():
            intent = json.loads(request_path.read_text())
            if intent['method'] != method or intent['role'] != self.rpc.role or {k: v for k, v in intent['values'].items() if k != 'operation_id'} != body or intent['expected_codes'] != sorted(expected_codes):
                raise RuntimeError('A resumed prerequisite cannot change its original intent.')
        else:
            intent = {'method': method, 'role': self.rpc.role, 'values': {**body, 'operation_id': str(uuid4())}, 'expected_codes': sorted(expected_codes), 'prepared_at': _now()}
            _save(request_path, intent)
        if response_path.exists():
            self.reused.append(step); return json.loads(response_path.read_text())
        result = self.rpc.invoke(method, intent['values'], expected_codes=expected_codes)
        _save(response_path, result); return result


def _http_stage(private_manifest, *, native_context, repository, base_url, private_directory, release_manifest, resume, host_header=None):
    from .test_company_chain_http_acceptance import CompanyHTTPRPC
    fixture = _fixture(private_manifest); native = json.loads(Path(native_context).read_text())
    if native['company'] != fixture['company'] or native['fixture_id'] != fixture['fixture_id']:
        raise RuntimeError('Use only this new isolated fixture native setup.')
    binding = _source_binding(repository, release_manifest); work = Path(private_directory)
    if not resume:
        _work(work)
    elif not work.is_dir() or not (work / 'stage-start.json').exists():
        raise RuntimeError('Resume requires the original durable stage directory.')
    if not (work / 'stage-start.json').exists():
        _save(work / 'stage-start.json', {'company': fixture['company'], 'fixture_id': fixture['fixture_id'], 'source_before': binding})
    elif json.loads((work / 'stage-start.json').read_text())['fixture_id'] != fixture['fixture_id']:
        raise RuntimeError('A stage cannot be resumed with replacement identities.')
    rpc = CompanyHTTPRPC(fixture, repository=repository, base_url=base_url, private_directory=str(work / ('http-' + uuid4().hex)), host_header=host_header)
    return fixture, native, work, rpc, PrerequisiteRPC(rpc, work / 'commands'), binding


def _complete_http_stage(work, rpc, journal, report, repository, release_manifest):
    try:
        report['source_after'] = _source_binding(repository, release_manifest)
    except Exception:
        report['status'] = 'failed'; raise
    finally:
        rpc.close(); report.update(calls=rpc.calls, schema_samples=rpc.schema_samples, reused_steps=journal.reused, completed_at=_now())
        _save(work / ('attempt-' + uuid4().hex + '.json'), report)


def _grant_and_consume(journal, company, action, subject, version, prefix):
    gov = 'cipher_aec.api.company_approvals.'
    journal.login('author')
    packet = journal.command(prefix + '-request', gov + 'request_action', {'company': company, 'action': action, 'subject_id': subject, 'expected_version': version})['packet']
    body = {'company': company, 'packet_id': packet['id'], 'manifest_hash': packet['manifest_hash'], 'decision': 'Grant', 'reason': 'Independent exact isolated prerequisite review.'}
    journal.login('alias'); journal.command(prefix + '-alias-denied', gov + 'decide_packet', body,
        expected_codes={'independent_review_required', 'independent_estimate_required', 'independent_proposal_required'})
    journal.login('reviewer'); granted = journal.command(prefix + '-grant', gov + 'decide_packet', body)['packet']
    if granted['state'] != 'Granted':
        raise AssertionError('Actual interactive independent prerequisite Grant was not obtained.')
    journal.login('author')
    result = journal.command(prefix + '-execute', gov + 'execute_packet', {'company': company, 'packet_id': packet['id'], 'manifest_hash': packet['manifest_hash']})
    if result['packet']['state'] != 'Consumed':
        raise AssertionError('The exact prerequisite Grant was not consumed.')
    return result


def manual_assembly_components(ids, units, rates):
    def quantity(amount, kind):
        return {'amount': amount, 'unit_id': units[kind], 'precision': 6}
    return [{'line_id': ids[category + '-component'], 'rate_source_id': rates[category]['id'], 'kind': category,
             'work_quantity': quantity('1', 'count'), 'resource_quantity': quantity(amount, kind), 'material_factor': '1', 'waste_fraction': '0'}
            for category, kind, amount in (('material', 'count', '2'), ('labor', 'labor_time', '1'), ('equipment', 'equipment_time', '0.5'))]


def manual_calculation_lines(ids, units, material_rate, assembly_revision):
    def quantity(amount):
        return {'amount': amount, 'unit_id': units['count'], 'precision': 6}
    common = {'cost_code': 'DESCRIPTIVE-NOT-AUTHORITY', 'notes': 'Explicit manual fixture', 'alternate': '', 'included': True}
    lines = [{**common, 'line_id': ids['assembly-line'], 'description': 'Mixed assembly', 'quantity': quantity('2'), 'assembly_revision_id': assembly_revision},
             {**common, 'line_id': ids['extra-line'], 'description': 'Separate material', 'quantity': quantity('1'), 'rate_source_id': material_rate, 'material_factor': '1', 'waste_fraction': '0'},
             {**common, 'line_id': ids['alternative-line'], 'description': 'Unfunded alternative', 'quantity': quantity('4'), 'rate_source_id': material_rate, 'material_factor': '1', 'waste_fraction': '0', 'included': False, 'alternate': 'Excluded alternative'}]
    adjustments = [{'line_id': ids['indirect'], 'kind': 'indirect', 'label': 'Authored indirect', 'method': 'fraction_of_direct', 'value': '0.10', 'basis_description': '10percent of rounded direct'},
                   {'line_id': ids['contingency'], 'kind': 'contingency', 'label': 'Authored contingency', 'method': 'fixed', 'value': '0.42', 'basis_description': 'Exact fixed allowance'}]
    return lines, adjustments


def build_award_manual_baseline_http(private_manifest, *, native_context, repository,
                                    base_url, private_directory, release_manifest, resume=False, host_header=None):
    """Real manual mixed assembly + extra/excluded lines + two adjustments.

    Known exact cost: material5.00 +labor4.00 +equipment3.00 +extra1.25,
    indirect1.33 +contingency0.42 =15.00. Excluded alternative5.00 unfunded.
    No generated provenance or calibrated-geometry qualification is asserted.
    """
    fixture, native, work, rpc, journal, binding = _http_stage(private_manifest, native_context=native_context,
        repository=repository, base_url=base_url, private_directory=private_directory, release_manifest=release_manifest, resume=resume, host_header=host_header)
    report = {'schema': 'cipher.award.manual-baseline-prerequisite.v1', 'status': 'failed', 'started_at': _now(), 'source_before': binding,
              'manual_inputs': True, 'generated_inputs': False, 'calibrated_geometry_qualified': False}
    try:
        from cipher_aec.api.contracts import digest
        company = fixture['company']; est = 'cipher_aec.estimating.company_api.'; docs = 'cipher_aec.documents.company_api.'
        ids_path = work / 'authored-ids.json'
        if not ids_path.exists():
            _save(ids_path, {key: str(uuid4()) for key in ('material-component', 'labor-component', 'equipment-component', 'assembly-line', 'extra-line', 'alternative-line', 'indirect', 'contingency')})
        ids = json.loads(ids_path.read_text()); marker = fixture['fixture_id']; unit = {key: value['id'] for key, value in native['units'].items()}
        content = ('Synthetic award manual source ' + marker + '\nMaterial rateUSD1.25/count; laborUSD2.00/labor-hour; equipmentUSD3.00/equipment-hour.\n'
                   'Assembly work1count needs2material-count,1labor-hour,0.5equipment-hour. Manual assembly quantity2count; extra material1count; excluded alternative4count.\n'
                   'Indirect10percent of direct; contingencyUSD0.42. Commercial selling rateUSD12.34/count separately authored. No generated/calibrated/model/provider claim.').encode()
        journal.login('author')
        uploaded = journal.command('source-upload', docs + 'upload_document', {'company': company, 'title': 'Award explicit manual source ' + marker,
            'filename': 'award-manual-source.txt', 'content_base64': base64.b64encode(content).decode(), 'sha256': hashlib.sha256(content).hexdigest(), 'byte_length': len(content)})
        citation = rpc.invoke(docs + 'get_citation', {'company': company, 'revision_id': uploaded['revision']['id'], 'page': 1})
        cite = {key: citation[key] for key in ('revision_id', 'page', 'excerpt_sha256', 'source_sha256')}
        pursuit = journal.command('pursuit', 'cipher_aec.commercial.api.create_pursuit', {'company': company, 'party_type': 'Customer', 'party_id': fixture['native']['a']['customer'], 'fields': {'title': 'Award manual pursuit ' + marker, 'sector': 'Synthetic infrastructure'}})['pursuit']
        rates = {}
        for category, kind, amount in (('material', 'count', '1.25'), ('labor', 'labor_time', '2.00'), ('equipment', 'equipment_time', '3.00')):
            rate = {'title': 'Award ' + category + ' ' + marker, 'cost_type': category, 'unit_id': unit[kind], 'rate_amount': amount, 'rate_precision': 6,
                    'currency': 'USD', 'quote_reference': 'Authored isolated manual fixture', 'quote_date': '2026-10-15', 'expiry_date': None,
                    'geography': 'Synthetic', 'inclusions': 'Explicit authored fixture', 'exclusions': 'No taxes or freight', 'freight_tax_assumptions': 'None',
                    'permission_basis': 'Owned synthetic fixture source', 'source_citations': [cite], 'item': fixture['native']['a']['item'] if category == 'material' else None}
            rates[category] = journal.command('rate-' + category, est + 'create_rate', {'company': company, 'rate': rate})['rate_source']
        components = manual_assembly_components(ids, unit, rates)
        assembly = journal.command('assembly', est + 'create_assembly', {'company': company, 'title': 'Manual mixed assembly ' + marker, 'basis_unit_id': unit['count'], 'components': components, 'author_basis': 'Exact source quantities; no generated evidence', 'conversion_ids': []})
        estimate = journal.command('estimate', est + 'create_estimate', {'company': company, 'title': 'Award manual accepted cost ' + marker, 'currency': 'USD', 'pricing_date': '2026-10-15', 'pursuit_id': pursuit['id']})['estimate']
        lines, adjustments = manual_calculation_lines(ids, unit, rates['material']['id'], assembly['assembly_revision']['id'])
        calculated = journal.command('calculate', est + 'calculate_revision', {'company': company, 'estimate_id': estimate['id'], 'expected_revision': None, 'lines': lines, 'adjustments': adjustments, 'conversion_ids': [], 'basis_description': 'Authored raw manual inputs, no generated provenance/calibration', 'basis_citations': [cite]})
        if calculated['revision']['total']['amount'] != '15.00':
            raise AssertionError('Manual exact accepted cost differs from the independently specified15.00.')
        accepted = _grant_and_consume(journal, company, 'estimate.accept.v1', calculated['revision']['id'], digest(calculated['revision']), 'baseline')
        acceptance = accepted['effect']['acceptance']
        actual = rpc.invoke(est + 'get_record', {'company': company, 'kind': 'acceptance', 'record_id': acceptance['id']})
        if actual != acceptance:
            raise AssertionError('The exact real accepted baseline differs on current authorized readback.')
        result = {'company': company, 'fixture_id': marker, 'pursuit': pursuit, 'acceptance': acceptance, 'calculated': calculated,
                  'source_reference': cite, 'qualified_unit': native['units']['count'], 'native': fixture['native']['a'],
                  'acceptance_id': acceptance['id'], 'acceptance_digest': digest(acceptance), 'revision_id': calculated['revision']['id'],
                  'revision_digest': digest(calculated['revision']), 'pursuit_id': pursuit['id'], 'qualification': 'Actual manual mixed baseline only; no calibrated/generated input.'}
        target = work / 'manual-baseline-context.json'
        if not target.exists():
            _save(target, result)
        elif json.loads(target.read_text()) != result:
            raise AssertionError('Resumed baseline context changed its exact original facts.')
        report.update(status='passed', acceptance_id=acceptance['id'], accepted_cost='15.00')
        return result
    finally:
        _complete_http_stage(work, rpc, journal, report, repository, release_manifest)


def build_award_issue_and_mappings_http(private_manifest, *, native_context, baseline_context,
                                       repository, base_url, private_directory, release_manifest, resume=False, host_header=None):
    """Actual Company proposal/PDF/independent Issue, cost revisions and team.

    Returns authored_context and company_plan_context through real authoring
    commands even in the disabled award epoch; never requests award execution.
    """
    from cipher_aec.api.contracts import digest
    from .test_company_commercial_chain_http_acceptance import _pdf
    fixture, native, work, rpc, journal, binding = _http_stage(private_manifest, native_context=native_context,
        repository=repository, base_url=base_url, private_directory=private_directory, release_manifest=release_manifest, resume=resume, host_header=host_header)
    baseline = json.loads(Path(baseline_context).read_text())
    report = {'schema': 'cipher.award.issue-plan-prerequisite.v1', 'status': 'failed', 'started_at': _now(),
              'source_before': binding, 'award_requested': False, 'award_executed': False}
    try:
        company = fixture['company']; com = 'cipher_aec.commercial.api.'; costs = 'cipher_aec.project_controls.company_api.'
        if baseline['company'] != company or baseline['fixture_id'] != fixture['fixture_id']:
            raise RuntimeError('Use only this legitimately accepted isolated manual baseline.')
        journal.login('author')
        actual = rpc.invoke('cipher_aec.estimating.company_api.get_record', {'company': company, 'kind': 'acceptance', 'record_id': baseline['acceptance']['id']})
        if actual != baseline['acceptance'] or actual['total']['amount'] != '15.00':
            raise AssertionError('The current authorized original manual baseline changed.')
        ids_path = work / 'authored-ids.json'
        if not ids_path.exists():
            _save(ids_path, {key: str(uuid4()) for key in ('scope', 'price-line', 'wbs-root', 'wbs-leaf')})
        ids = json.loads(ids_path.read_text()); marker = fixture['fixture_id']; unit = native['units']['count']
        source = {**baseline['source_reference'], 'purpose': 'Explicit original manual award evidence', 'permission_basis': 'Owned synthetic fixture source, no generated provenance'}
        estimate_reference = {key: baseline[key] for key in ('acceptance_id', 'acceptance_digest', 'revision_id', 'revision_digest')}
        composition = {'currency': 'USD', 'price_list': fixture['native']['a']['price_list'], 'valid_till': '2026-12-31',
            'terms': 'Synthetic draft terms; no legal execution or transmission.',
            'sections': [{'id': ids['scope'], 'kind': 'scope', 'title': 'Explicit manual scope', 'text': 'Known cost15.00; separately authored selling30.85.'}],
            'price_lines': [{'id': ids['price-line'], 'description': 'Explicit nonstock sales item ' + marker, 'quantity': '2.500000',
                             'unit_id': unit['id'], 'unit_revision': unit['revision'], 'rate': '12.34', 'item_code': fixture['native']['a']['item'], 'selected': True}],
            'source_references': [source], 'estimate_reference': estimate_reference}
        proposal = journal.command('proposal', com + 'create_proposal', {'company': company, 'pursuit_id': baseline['pursuit_id'], 'composition': composition})
        revision = proposal['revision']
        if revision['pricing']['total'] != '30.85':
            raise AssertionError('The fixture must distinguish issued selling30.85 from accepted cost15.00.')
        prepared = journal.command('prepare-pdf', com + 'prepare_proposal_output', {'company': company, 'proposal_id': proposal['proposal']['id'],
            'revision_id': revision['id'], 'expected_revision_digest': digest(revision),
            'recipients': [{'name': 'Synthetic award recipient', 'email': 'award.fixture@cipher.example', 'organization': 'Isolated fixture'}],
            'cover': 'Synthetic reviewed award origin only. No external transmission.'})['prepared_output']
        pdf = _pdf(rpc, prepared)
        consumed = _grant_and_consume(journal, company, 'proposal.issue.v1', revision['id'], prepared['review_version'], 'issue')
        issue = consumed['effect']['issue']
        if issue['prepared_output'] != prepared or issue['distribution'] != 'not-sent' or issue['native_lifecycle'] != 'draft-snapshot':
            raise AssertionError('Actual independent Issue lost its immutable no-send draft origin.')
        if rpc.invoke(com + 'issue', {'company': company, 'issue_id': issue['id']}) != issue:
            raise AssertionError('The exact legitimate Issue differs on authorized readback.')
        code = journal.command('cost-code', costs + 'create_master', {'company': company, 'kind': 'code', 'code': 'AWARD-WORK',
            'definition': {'title': 'Explicit existing leaf Cost Center', 'effective_from': '2026-10-15', 'effective_until': None, 'enabled': True,
                           'native_target': {'doctype': 'Cost Center', 'name': native['cost_center']}}})['revision']
        types = {}
        for category in ('material', 'labor', 'equipment', 'indirect', 'contingency'):
            definition = {'title': 'Explicit ' + category + ' accounting target', 'effective_from': '2026-10-15', 'effective_until': None, 'enabled': True,
                          'native_target': {'doctype': 'Account', 'name': native['expense_account']},
                          'cost_category': category if category in {'material', 'labor', 'equipment'} else None,
                          'allocation_class': 'component' if category in {'material', 'labor', 'equipment'} else category}
            types[category] = journal.command('cost-type-' + category, costs + 'create_master', {'company': company, 'kind': 'type', 'code': 'AWARD-' + category.upper(), 'definition': definition})['revision']
        # Exact immutable source identity -> stable authored allocation UUID.
        from uuid import NAMESPACE_URL, uuid5
        allocations = []
        def allocate(source, category):
            allocations.append({'id': str(uuid5(NAMESPACE_URL, marker + ':award-budget:' + _hash(source))), 'source': source,
                                'wbs_id': ids['wbs-leaf'], 'code_revision_id': code['id'], 'type_revision_id': types[category]['id']})
        accepted = baseline['acceptance']['accepted_result']
        for line in accepted['lines']:
            if line['included']:
                for component in line['components']:
                    allocate({'kind': 'component', 'line_id': line['line_id'], 'component_id': component['component_id']}, component['cost_type'])
        for adjustment in accepted['adjustments']:
            allocate({'kind': 'adjustment', 'adjustment_id': adjustment['line_id']}, adjustment['kind'])
        policy = rpc.invoke('cipher_aec.awards.api.delegation_policy', {'company': company})['policy']
        if policy['id'] != native['team_policy']['id'] or policy['digest'] != native['team_policy']['digest']:
            raise AssertionError('The exact prerequisite delegation policy changed before planning.')
        node = {'accountable_person': native['team_person'], 'phase': 'Initial', 'active_from': None, 'active_until': None}
        definition = {'issue_id': issue['id'],
            'project_definition': {'project_name': 'Award exact new Project ' + marker, 'expected_start_date': '2026-10-15', 'expected_end_date': '2026-12-31'},
            'native_order_definition': {'customer': fixture['native']['a']['customer'], 'transaction_date': '2026-10-15', 'delivery_date': '2026-12-31', 'selling_price_list': fixture['native']['a']['price_list']},
            'contract_definition': {'number': 'AWARD-' + marker, 'kind': 'prime', 'direction': 'receivable', 'party_type': 'Customer',
                                    'party': fixture['native']['a']['customer'], 'currency': 'USD', 'original_value': {'amount': '30.85', 'currency': 'USD'}},
            'line_mappings': [{'proposal_line_id': row['line']['id'], 'item_code': row['line']['item_code'], 'delivery_date': '2026-12-31'} for row in issue['selected_lines']],
            'award_evidence': [source], 'party_correspondence': None,
            'team': {'delegator_person': fixture['users']['author']['person'], 'policy_id': policy['id'], 'policy_digest': policy['digest'],
                     'members': [{'person_id': native['team_person'], 'abilities': ['budget.read', 'contract.read', 'project.read', 'wbs.read']}]},
            'wbs_nodes': [{**node, 'id': ids['wbs-root'], 'code': 'WORK', 'parent_id': None, 'title': 'Reviewed initial work', 'is_leaf': False},
                          {**node, 'id': ids['wbs-leaf'], 'code': 'WORK.01', 'parent_id': ids['wbs-root'], 'title': 'Exact accepted cost', 'is_leaf': True}],
            'budget_allocations': allocations}
        authored = {'company': company, 'issue': issue, 'definition': definition, 'baseline_context': str(Path(baseline_context).resolve()),
                    'private_manifest': str(Path(private_manifest).resolve()), 'initial_team_login_role': 'project_only'}
        target = work / 'authored-context.json'
        if not target.exists():
            _save(target, authored)
        elif json.loads(target.read_text()) != authored:
            raise AssertionError('Resumed authored award input changed.')
        handoff = journal.command('handoff', 'cipher_aec.awards.api.create_handoff', {'company': company, 'issue_id': issue['id']})
        planned = journal.command('award-plan', 'cipher_aec.awards.api.plan_handoff', {'company': company, 'handoff_id': handoff['handoff']['id'], 'expected_version': handoff['version'], 'definition': definition})
        context = {'company': company, 'issue': issue, 'plan': planned['plan'], 'version': planned['version'], 'handoff': planned['handoff']}
        current = rpc.invoke('cipher_aec.awards.api.get_plan', {'company': company, 'revision_id': planned['plan']['id']})
        if current['plan'] != planned['plan'] or planned['plan']['controls_plan']['totals']['total']['amount'] != '15.00':
            raise AssertionError('Actual canonical planned adoption lost exact manual cost or immutable identity.')
        target = work / 'company-plan-context.json'
        if not target.exists():
            _save(target, context)
        elif json.loads(target.read_text()) != context:
            raise AssertionError('Resumed exact Company plan changed.')
        report.update(status='passed', issue_id=issue['id'], plan_id=planned['plan']['id'], accepted_cost='15.00', selling_value='30.85',
                      pdf_sha256=hashlib.sha256(pdf).hexdigest(), initial_team_login_role='project_only', requester_in_team=False)
        return {'authored_context': str((work / 'authored-context.json').resolve()), 'company_plan_context': str(target.resolve()),
                'company': company, 'private_manifest': str(Path(private_manifest).resolve()), 'plan_id': planned['plan']['id']}
    finally:
        _complete_http_stage(work, rpc, journal, report, repository, release_manifest)
