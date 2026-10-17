"""External DOC03 reviewer-context regression; plain host boundaries only.

Actual DocumentContext discovery/prelock/hold, provenance.prelocked, canonical
approval execution/commands, documentary authorization, rights and byte checks run
unchanged. Doubles cover storage/session/duties/native master access. This is not
MariaDB, isolation, provider, native runtime or deployment qualification.
"""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

loaded_app = sys.modules.get('cipher_aec')
loaded_file = getattr(loaded_app, '__file__', None)
explicit_root = os.environ.get('CIPHER_REVIEWER_APP_ROOT')
ROOT = (Path(explicit_root) if explicit_root else Path(loaded_file).resolve().parent.parent if loaded_file
    else Path(__file__).parents[2] / 'packaging/apps/cipher/platform/apps/cipher_aec').resolve()
if not (ROOT / 'cipher_aec/document_control/locking.py').is_file():
    raise RuntimeError('CIPHER_REVIEWER_APP_ROOT must identify the tested cipher_aec app root')
if explicit_root and loaded_file and not Path(loaded_file).resolve().is_relative_to(ROOT):
    raise RuntimeError('Already-imported cipher_aec differs from CIPHER_REVIEWER_APP_ROOT')
sys.path.insert(0, str(ROOT))
from cipher_aec.api.contracts import canonical_json, digest, utc_timestamp
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_document_control import fixture, person, source, authorize
from cipher_aec.tests.test_engineering import add_source, uid


def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def reviewer_fixture():
    with fixture() as (s, r, repo, rights, service, gov), ExitStack() as stack:
        locking = importlib.import_module('cipher_aec.document_control.locking')
        scopes = importlib.import_module('cipher_aec.document_control.scopes')
        shared = importlib.import_module('cipher_aec.document_control.shared')
        provenance = importlib.import_module('cipher_aec.documents.provenance')
        documents = sys.modules['cipher_aec.documents.service']
        context = sys.modules['cipher_aec.governance.context']
        history = sys.modules['cipher_aec.governance.history']
        original_sql = sys.modules['frappe'].db.sql
        s.company_duties = {s.actor.person_id: set(r.ABILITIES) | {'company.read', 'document.read', 'document.write'}}
        s.observed = []
        s.inner_errors = []
        s.authorization_contexts = []
        s.native_receipts = {}
        s.policies = {}
        s.snapshots = {}
        s.before_commit_callbacks = []
        s.before_rollback_callbacks = []
        s.actor_lock_calls = []
        s.ambiguous_users = set()
        s.generated_producers = {}
        s.isolation_rows = [('READ-COMMITTED',)]
        s.isolation_error = None
        original_current = context.current_actor

        def current(user=None, lock=False):
            candidate = s.users[user] if user is not None else s.actor
            if lock:
                s.actor_lock_calls.append((candidate.user, candidate.person_id))
            if candidate.user in s.ambiguous_users:
                raise DomainError('identity_unavailable', 'Ambiguous current identity', 403)
            return original_current(user, lock=lock)

        def require(company, project, ability='project.read', actor=None, lock=False):
            actor = actor or s.actor
            fresh = current(actor.user, lock=lock)
            if fresh.person_id != actor.person_id:
                raise DomainError('identity_changed', 'Current Project identity changed', 403)
            s.observed.append(('duty', actor.person_id, 'Project', project, ability, lock))
            if company != 'C' or project != 'P':
                raise DomainError('not_found', 'Project scope', 404)
            if ability not in s.duties.get(actor.person_id, set()):
                raise DomainError('capability_denied', 'Current Project duty', 403)
            return SimpleNamespace(name='P', company='C', status=s.project_status)

        def company(company_name, ability='company.read', actor=None, lock=False):
            actor = actor or s.actor
            fresh = current(actor.user, lock=lock)
            if fresh.person_id != actor.person_id:
                raise DomainError('identity_changed', 'Current Company identity changed', 403)
            s.observed.append(('duty', actor.person_id, 'Company', None, ability, lock))
            if company_name != 'C' or ability not in s.company_duties.get(actor.person_id, set()):
                raise DomainError('capability_denied', 'Current Company duty', 403)
            return SimpleNamespace(name='C')

        def metadata(revision):
            row = s.documents[revision]
            return SimpleNamespace(name=revision, company='C', project=row.get('project', 'P'),
                scope_type=row.get('scope_type', 'Project'), document=row['document_id'])

        def document_metadata(name):
            row = next(v for v in s.documents.values() if v['document_id'] == name)
            return SimpleNamespace(name=name, company='C', project=row.get('project', 'P'), scope_type=row.get('scope_type', 'Project'))

        def document(name, company_name, scope_type, project_name, actor, lock=False):
            scopes.require(company_name, scope_type, project_name, actor, 'document.read', lock=lock)
            rows = [v for v in s.documents.values() if v['document_id'] == name]
            if not rows:
                raise DomainError('not_found', 'Document source', 404)
            row = max(rows, key=lambda v: v['revision_number'])
            if row.get('scope_type', 'Project') != scope_type or row.get('project', 'P') != project_name:
                raise DomainError('not_found', 'Original Document scope', 404)
            s.observed.append(('document', actor.person_id, name, lock))
            return SimpleNamespace(name=name, company='C', project=project_name,
                scope_type=scope_type, current_revision=row['revision_id'])

        def source_reference(company_name, project_name, revision, page, actor=None, lock=False, scope_type='Project'):
            actor = actor or s.actor
            scopes.require(company_name, scope_type, project_name, actor, 'document.read', lock=lock)
            row = s.documents.get(revision)
            if row is None or revision in s.denied or row.get('scope_type', 'Project') != scope_type or row.get('project', 'P') != project_name:
                raise DomainError('source_denied', 'Original source denied', 403)
            rights.require(row['document_id'], 'C', project_name, 'read', actor,
                lock=lock, required=False, scope_type=scope_type)
            if revision in s.generated_producers:
                provenance.authorize(s.generated_producers[revision], actor, lock=lock)
            value = deepcopy(row)
            value['page'] = page
            if not 1 <= page <= value['page_count']:
                raise DomainError('invalid_page', 'Original page', 422)
            s.observed.append(('bytes', actor.person_id, revision, lock))
            return value

        def company_setup_command(**kw):
            # Author fixture data before the tested canonical execution begins.
            company(kw['company'], ability=kw['ability'], actor=s.actor)
            kw['guard'](s.actor, None)
            return kw['effect'](s.actor, None)

        for owner, name, value in (
            (context, 'current_actor', current), (locking, 'current_actor', current),
            (context, 'require_project', require), (context, 'require_company', company),
            (locking, 'require_project', require), (locking, 'require_company', company),
            (service, 'require_project', require), (gov, 'require_project', require),
            (shared, 'require_project', require), (shared, 'require_company', company),
            (scopes, 'require_project', require), (scopes, 'require_company', company),
            (scopes, 'document', document),
            (service, '_document', lambda name, c, p, a, lock=False: document(name, c, 'Project', p, a, lock)),
            (service.FrappeDocumentRepository, 'revision_scope', lambda _, name: metadata(name)),
            (service.FrappeDocumentRepository, 'document_scope', lambda _, name: document_metadata(name)),
            (service.FrappeDocumentRepository, 'document', lambda _, name, **kw: {'name': name}),
            (documents, 'source_reference', source_reference),
            (documents, 'company_source_reference', lambda c, rev, page, actor=None, lock=False: source_reference(c, None, rev, page, actor, lock, scope_type='Company')),
            (service.sources, 'source_reference', source_reference),
            (sys.modules['cipher_aec.governance.commands'], 'run_company_command', company_setup_command),
            (history, 'append_company_event', lambda **kw: s.events.append(kw) or uid()),
            (provenance, 'source_plan', lambda *a, **kw: {}),
        ):
            stack.enter_context(patch.object(owner, name, value, create=True))
        # These native master modules are import boundaries; plans here contain
        # only raw canonical Documents and do not claim generated-source coverage.
        native = ModuleType('native')
        native.require_native = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Unexpected native master'))
        units = ModuleType('units')
        units.qualified = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Unexpected unit master'))
        projects = ModuleType('projects')
        for name in ('_exact_count', '_page_scope', '_query_page', 'present_project'):
            setattr(projects, name, lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Unexpected Project presentation')))
        stack.enter_context(patch.dict(sys.modules, {
            'cipher_aec.commercial.native': native, 'cipher_aec.estimating.units': units,
            'cipher_aec.projects.service': projects,
        }))
        for name, value in {
            'assert_synthetic_site': lambda: None, 'require_effects_enabled': lambda: None,
            'session_authority_reference': lambda actor: 'host-session', 'require_session_authority': lambda *a, **kw: None,
            'company_authority_fingerprint': lambda *a, **kw: 'host-company-duties',
            'duty_rows': lambda actor, c, p, **kw: [SimpleNamespace(ability=v) for v in s.duties[actor.person_id]],
            'company_duty_rows': lambda actor, c, **kw: [SimpleNamespace(ability=v) for v in s.company_duties[actor.person_id]],
        }.items():
            stack.enter_context(patch.object(context, name, value, create=True))

        class NativeDocument(SimpleNamespace):
            def insert(self, ignore_permissions=False, set_name=None):
                self.name = set_name or getattr(self, 'name', uid())
                if self.doctype == 'Cipher Approval Consumption':
                    s.consumptions[self.packet] = self
                elif self.doctype == 'Cipher Command Receipt':
                    s.native_receipts[self.name] = self
                else:
                    raise AssertionError(self.doctype)
                return self

        def get_doc(doctype, name=None, **kw):
            if isinstance(doctype, dict):
                return NativeDocument(**doctype)
            return {'Cipher Approval Packet': s.packets, 'Cipher Approval Decision': s.decisions}[doctype][name]

        def sql(query, args=(), **kw):
            if query == 'SELECT @@session.tx_isolation':
                if s.isolation_error is not None:
                    raise s.isolation_error
                return s.isolation_rows
            if 'tabCipher Person' in query:
                s.observed.append(('people', tuple(args)))
                return [('Human',)] if 'identity_kind' in query else [(p,) for p in args]
            if 'tabCipher Identity Binding' in query:
                if query.startswith('SELECT user'):
                    return [SimpleNamespace(user=a.user) for a in s.users.values() if a.person_id == args[0]]
                s.observed.append(('identities', tuple(args)))
                return []
            if 'tabCipher Approval Packet' in query:
                return [s.packets[args[0]]] if args[0] in s.packets else []
            if 'tabCipher Approval Decision' in query:
                return [v for v in s.decisions.values() if v.packet == args[0]]
            if 'tabCipher Approval Consumption' in query:
                return [v for v in s.consumptions.values() if v.packet == args[0]]
            if 'tabCipher Approval Policy Revision' in query:
                return [s.policies[args[0]]] if args[0] in s.policies else []
            if 'tabCipher Command Receipt' in query:
                return [s.native_receipts[args[0]]] if args[0] in s.native_receipts else []
            return original_sql(query, args, **kw)

        def savepoint(name):
            s.snapshots[name] = deepcopy((s.rows, s.events, s.consumptions, s.native_receipts))

        def rollback(save_point=None):
            for callback in tuple(s.before_rollback_callbacks):
                callback()
            if save_point is not None:
                s.rows, s.events, s.consumptions, s.native_receipts = deepcopy(s.snapshots[save_point])

        frappe = sys.modules['frappe']
        for owner, name, value in (
            (frappe, 'get_doc', get_doc), (frappe.db, 'sql', sql),
            (frappe.db, 'savepoint', savepoint), (frappe.db, 'rollback', rollback),
            (frappe.db, 'get_value', lambda *a, **kw: 'Synthetic registered value'),
            (frappe.db, 'before_commit', SimpleNamespace(add=s.before_commit_callbacks.append,
                run=lambda: [callback() for callback in tuple(s.before_commit_callbacks)])),
            (frappe.db, 'before_rollback', SimpleNamespace(add=s.before_rollback_callbacks.append,
                run=lambda: [callback() for callback in tuple(s.before_rollback_callbacks)])),
            (frappe, 'QueryDeadlockError', type('Deadlock', (Exception,), {})),
            (frappe, 'QueryTimeoutError', type('Timeout', (Exception,), {})),
        ):
            stack.enter_context(patch.object(owner, name, value, create=True))

        # Retain module identities so all document callback imports use the same
        # unmodified canonical command and approval engine during execution.
        command_name = 'cipher_aec.governance.commands'
        approval_name = 'cipher_aec.governance.approvals'
        with patch.dict(sys.modules):
            commands = load_source(command_name, ROOT / 'cipher_aec/governance/commands.py')
            approvals = load_source(approval_name, ROOT / 'cipher_aec/governance/approvals.py')
            # Real registry callbacks still point to real documentary functions.
            stack.enter_context(patch.object(gov, 'require_approval_effect', approvals.require_approval_effect))
            actual_authorize = approvals.domain_approvals.authorize

            def observed_authorize(packet, actor, phase='read', lock=False):
                active = locking._active.get()
                held = provenance._prelocked.get()
                s.authorization_contexts.append({'actor': actor.person_id, 'phase': phase, 'lock': lock,
                    'outer_identity': active['identity'] if active else None,
                    'provenance_identity': held[:3] if held else None})
                try:
                    return actual_authorize(packet, actor, phase=phase, lock=lock)
                except DomainError as error:
                    s.inner_errors.append({'actor': actor.person_id, 'phase': phase, 'lock': lock,
                        'code': error.code, 'status': error.status, 'message': error.message})
                    raise

            stack.enter_context(patch.object(approvals.domain_approvals, 'authorize', observed_authorize))
            yield SimpleNamespace(s=s, r=r, repo=repo, rights=rights, service=service,
                gov=gov, shared=shared, locking=locking, provenance=provenance,
                commands=commands, approvals=approvals)


def reviewer(values):
    result = person(values.s, values.r, 'reviewer')
    values.s.duties[result.person_id].add('approval.decide')
    values.s.company_duties[result.person_id] = {values.r.READ, 'company.read', 'document.read'}
    return result


def new_packet(values, kind, value, checker):
    s, approvals = values.s, values.approvals
    # Current distinct-person authority is checked before accepting this host grant.
    values.gov.authorize_subject(kind=kind, actor=checker, company='C', project='P',
        subject_id=value['id'], phase='review', lock=False)
    manifest = values.gov.approval_manifest(kind=kind, actor=s.actor, company='C', project='P',
        subject_id=value['id'], expected_version=digest(value), lock=True)
    action = values.r.ACTIONS[kind]
    definition = approvals.domain_approvals.definition(action)
    policy = SimpleNamespace(name='host-policy-' + kind, enabled=True,
        definition_json=canonical_json(definition), label='Synthetic host policy')
    s.policies[action] = policy
    now = datetime.now(timezone.utc)
    outer = {'action': action, 'action_version': 1, 'company': 'C', 'project': 'P',
        'source_version': digest(value), 'requester_person': s.actor.person_id,
        'policy_revision': policy.name, 'policy_hash': digest(definition), 'domain': manifest}
    packet = SimpleNamespace(name=uid(), company='C', project='P', scope_type='Project', action=action,
        subject_type=values.r.KINDS[kind], subject_id=value['id'], requester_person=s.actor.person_id,
        source_version=digest(value), policy_revision=policy.name, manifest_json=canonical_json(outer),
        manifest_hash=digest(outer), created_at=utc_timestamp(now), expires_at=utc_timestamp(now + timedelta(days=1)))
    decision = SimpleNamespace(name=uid(), packet=packet.name, decision='Grant', actor_person=checker.person_id,
        manifest_hash=packet.manifest_hash, decided_at=utc_timestamp(now), reason='Independent exact host review')
    s.packets[packet.name] = packet
    s.decisions[decision.name] = decision
    s.duties[s.actor.person_id].update(('approval.execute', 'approval.request'))
    return packet


def company_adoption(values):
    s, shared = values.s, values.shared
    original, evidence = add_source(s), add_source(s)
    for ref in (original, evidence):
        s.documents[ref['revision_id']].update(scope_type='Company', project=None)
    shared.set_rights('C', uid(), s.documents[original['revision_id']]['document_id'], None,
        {'ingest_allowed': True, 'read_allowed': True, 'distribute_allowed': True,
         'rights_basis': 'Synthetic manually authored internal rights', 'rights_holder': 'Synthetic holder',
         'allowed_purpose': 'Internal adoption', 'restriction': 'No external delivery',
         'valid_from': None, 'valid_until': None, 'evidence_artifact': {k: evidence[k] for k in ('revision_id', 'source_sha256')}})
    created = shared.library('C', uid(), {'title': 'Company clause', 'category': 'contract_clause',
        'discipline': 'Commercial', 'ownership': 'Synthetic Company', 'tags': [], 'change_reason': 'Original'},
        {k: original[k] for k in ('revision_id', 'source_sha256')})
    revision = created['library_revision']
    request = shared.create_adoption('C', 'P', uid(), {'scope_type': 'Company', 'project': None},
        revision['id'], digest(revision), {'purpose': 'Exact Company reuse', 'target_locator': 'Project section',
        'change_reason': 'Independent adoption'})['adoption_request']
    return request, original, evidence


def project_transmittal(values):
    s, r, service, gov = values.s, values.r, values.service, values.gov
    ref = source(s, service)
    checker = reviewer(values)
    issue_set = service.create_issue_set('C', 'P', uid(), {'title': 'Original Project set',
        'purpose': 'Internal coordination', 'issue_purpose': 'coordination'}, [ref], [])['issue_set']
    # Setup helper requires its original exact-effect double; execution below
    # returns to the real approval grant context and canonical consume path.
    original_effect = gov.require_approval_effect
    def setup_effect(**kw):
        if s.approval_effect != (kw['action'], kw['subject_id'], kw['packet_id']):
            raise DomainError('approval_required', 'Exact setup grant', 403)
    with patch.object(gov, 'require_approval_effect', setup_effect):
        issued = authorize(s, r, gov, 'issue_set', issue_set, checker)
    recipient = person(s, r, 'recipient')
    transmittal = service.create_transmittal('C', 'P', uid(), issued['id'], digest(issued),
        [recipient.user], 'Review original specification', 'Acknowledge internal receipt')['transmittal']
    return transmittal, ref, recipient, checker


def execute(values, packet):
    values.s.observed.clear()
    values.s.inner_errors.clear()
    values.s.authorization_contexts.clear()
    try:
        return values.approvals.execute_packet('C', 'P', packet.name, packet.manifest_hash, uid())
    except DomainError as error:
        error.add_note('Actual inner authorization errors: ' + canonical_json(values.s.inner_errors))
        raise


class ReviewerContextRegressionTests(unittest.TestCase):
    def assert_reviewer_keeps_requester_union(self, v, checker):
        observations = [row for row in v.s.authorization_contexts
            if row['actor'] == checker.person_id and row['phase'] == 'review']
        self.assertTrue(observations, 'The real reviewer callback must run')
        for row in observations:
            self.assertEqual(row['outer_identity'], (v.s.actor.user, v.s.actor.person_id))
            self.assertEqual(row['provenance_identity'], (v.s.actor.user, v.s.actor.person_id, 'C'))

    def test_company_adoption_consumes_current_independent_review_under_requester_union(self):
        with reviewer_fixture() as v:
            request, original, evidence = company_adoption(v)
            checker = reviewer(v)
            packet = new_packet(v, 'adoption_request', request, checker)
            result = execute(v, packet)
            self.assertEqual(result['packet']['state'], 'Consumed')
            self.assertEqual(result['effect']['adoption']['checked_by_person'], checker.person_id)
            self.assertFalse(v.s.inner_errors)
            self.assert_reviewer_keeps_requester_union(v, checker)
            self.assertIsNone(v.locking._active.get())
            self.assertIsNone(v.provenance._prelocked.get())

    def test_project_transmittal_consumes_review_and_rechecks_recipients_under_requester_union(self):
        with reviewer_fixture() as v:
            transmittal, ref, recipient, checker = project_transmittal(v)
            packet = new_packet(v, 'transmittal', transmittal, checker)
            result = execute(v, packet)
            self.assertEqual(result['packet']['state'], 'Consumed')
            self.assertEqual(result['effect']['distribution']['recipients'], transmittal['recipients'])
            self.assertTrue(any(row[0] == 'bytes' and row[1] == recipient.person_id for row in v.s.observed))
            self.assert_reviewer_keeps_requester_union(v, checker)
            self.assertIsNone(v.locking._active.get())
            self.assertIsNone(v.provenance._prelocked.get())

    def test_current_company_duty_revocation_is_still_denied_without_effect(self):
        with reviewer_fixture() as v:
            request, _, _ = company_adoption(v)
            checker = reviewer(v)
            packet = new_packet(v, 'adoption_request', request, checker)
            v.s.company_duties[checker.person_id].remove('document.read')
            before = deepcopy((v.s.rows, v.s.consumptions, v.s.native_receipts))
            with self.assertRaises(DomainError) as error:
                execute(v, packet)
            self.assertEqual(error.exception.code, 'reviewer_authority_revoked')
            self.assertEqual((v.s.rows, v.s.consumptions, v.s.native_receipts), before)

    def test_reviewer_origin_duties_precede_every_source_lock(self):
        for kind in ('adoption_request', 'transmittal'):
            with self.subTest(kind=kind), reviewer_fixture() as v:
                if kind == 'adoption_request':
                    value, _, _ = company_adoption(v)
                    checker = reviewer(v)
                    expected = {('Company', None, 'document.read'), ('Project', 'P', 'document.read')}
                else:
                    value, _, _, checker = project_transmittal(v)
                    expected = {('Project', 'P', 'document.read')}
                packet = new_packet(v, kind, value, checker)
                try:
                    execute(v, packet)
                except DomainError:
                    # Retain the ordering assertion on the unfixed source too.
                    pass
                first_source = next(i for i, row in enumerate(v.s.observed) if row[0] in ('document', 'master'))
                before_source = {(row[2], row[3], row[4]) for row in v.s.observed[:first_source]
                    if row[0] == 'duty' and row[1] == checker.person_id and row[5]}
                self.assertTrue(expected <= before_source,
                    f'Reviewer origin duties must be locked before source acquisition: expected={expected}; observed={before_source}')
                people = next(i for i, row in enumerate(v.s.observed) if row[0] == 'people')
                identities = next(i for i, row in enumerate(v.s.observed) if row[0] == 'identities')
                self.assertLess(people, identities)
                self.assertLess(identities, first_source)

    def test_current_rights_revocation_is_still_denied_without_effect(self):
        with reviewer_fixture() as v:
            request, original, _ = company_adoption(v)
            checker = reviewer(v)
            packet = new_packet(v, 'adoption_request', request, checker)
            document_id = v.s.documents[original['revision_id']]['document_id']
            for (kind, _), row in v.s.rows.items():
                if kind == 'rights' and row['parent_id'] == document_id:
                    row['read_allowed'] = False
            before = deepcopy((v.s.rows, v.s.consumptions, v.s.native_receipts))
            with self.assertRaises(DomainError) as error:
                execute(v, packet)
            self.assertEqual(error.exception.code, 'source_rights_denied')
            self.assertEqual((v.s.rows, v.s.consumptions, v.s.native_receipts), before)

    def test_current_project_review_duty_revocation_is_still_denied_without_effect(self):
        with reviewer_fixture() as v:
            transmittal, _, _, checker = project_transmittal(v)
            packet = new_packet(v, 'transmittal', transmittal, checker)
            v.s.duties[checker.person_id].remove(v.r.REVIEW)
            before = deepcopy((v.s.rows, v.s.consumptions, v.s.native_receipts))
            with self.assertRaises(DomainError) as error:
                execute(v, packet)
            self.assertEqual(error.exception.code, 'reviewer_authority_revoked')
            self.assertEqual((v.s.rows, v.s.consumptions, v.s.native_receipts), before)

    def test_current_recipient_source_duty_revocation_is_still_denied_before_source_locks(self):
        with reviewer_fixture() as v:
            transmittal, _, recipient, checker = project_transmittal(v)
            packet = new_packet(v, 'transmittal', transmittal, checker)
            v.s.duties[recipient.person_id].remove('document.read')
            before = deepcopy((v.s.rows, v.s.consumptions, v.s.native_receipts))
            with self.assertRaises(DomainError) as error:
                execute(v, packet)
            self.assertEqual(error.exception.code, 'capability_denied')
            self.assertFalse(any(row[0] == 'document' for row in v.s.observed))
            self.assertEqual((v.s.rows, v.s.consumptions, v.s.native_receipts), before)

    def test_arbitrary_nested_reviewer_hold_cannot_replace_requester_identity(self):
        with reviewer_fixture() as v:
            request, _, _ = company_adoption(v)
            checker = reviewer(v)
            outer = v.locking.DocumentContext('C', 'P', [('adoption_request', request['id'])])
            with outer.hold(v.s.actor):
                original = v.locking._active.get()
                token = v.provenance._prelocked.get()
                with self.assertRaises(DomainError) as error:
                    with v.locking.DocumentContext('C', 'P', [('adoption_request', request['id'])]).hold(checker):
                        self.fail('An arbitrary actor must not replace the admitted union')
                self.assertEqual(error.exception.code, 'document_prelock_required')
                self.assertIs(v.locking._active.get(), original)
                self.assertIs(v.provenance._prelocked.get(), token)
            self.assertIsNone(v.locking._active.get())
            self.assertIsNone(v.provenance._prelocked.get())

    def test_nested_requester_hold_cannot_grow_the_admitted_source_union(self):
        with reviewer_fixture() as v:
            request, _, _ = company_adoption(v)
            extra = add_source(v.s)
            outer = v.locking.DocumentContext('C', 'P', [('adoption_request', request['id'])])
            with outer.hold(v.s.actor):
                original = v.locking._active.get()
                token = v.provenance._prelocked.get()
                with self.assertRaises(DomainError) as error:
                    with v.locking.DocumentContext('C', 'P', [('adoption_request', request['id'])], artifacts=[extra]).hold(v.s.actor):
                        self.fail('A nested callback cannot add a new source after outer source locks')
                self.assertEqual(error.exception.code, 'document_prelock_required')
                self.assertIs(v.locking._active.get(), original)
                self.assertIs(v.provenance._prelocked.get(), token)
            self.assertIsNone(v.locking._active.get())
            self.assertIsNone(v.provenance._prelocked.get())

    def test_exception_restores_original_union_and_provenance_tokens(self):
        with reviewer_fixture() as v:
            request, _, _ = company_adoption(v)
            outer = v.locking.DocumentContext('C', 'P', [('adoption_request', request['id'])])
            with outer.hold(v.s.actor):
                original = v.locking._active.get()
                token = v.provenance._prelocked.get()
                with self.assertRaisesRegex(RuntimeError, 'after nested admitted read'):
                    with v.locking.DocumentContext('C', 'P', [('adoption_request', request['id'])]).hold(v.s.actor):
                        raise RuntimeError('after nested admitted read')
                self.assertIs(v.locking._active.get(), original)
                self.assertIs(v.provenance._prelocked.get(), token)
            self.assertIsNone(v.locking._active.get())
            self.assertIsNone(v.provenance._prelocked.get())

    def held_review(self, v, value, checker):
        return v.locking.DocumentContext('C', 'P', [('adoption_request', value['id'])],
            review_people=(v.s.actor.person_id, checker.person_id))

    def assert_helper_denied(self, v, value, actor):
        original = v.locking._active.get()
        token = v.provenance._prelocked.get()
        with self.assertRaises(DomainError) as error:
            with v.locking.reviewer_read('C', 'P', 'adoption_request', value['id'], actor):
                self.fail('The private reviewer helper must refuse this unadmitted read')
        self.assertEqual(error.exception.code, 'document_prelock_required')
        self.assertIs(v.locking._active.get(), original)
        self.assertIs(v.provenance._prelocked.get(), token)

    def test_helper_rejects_unlisted_actor_with_otherwise_current_source_rights(self):
        with reviewer_fixture() as v:
            value, _, _ = company_adoption(v)
            checker = reviewer(v)
            stranger = person(v.s, v.r, 'unlisted-reviewer')
            v.s.company_duties[stranger.person_id] = {v.r.READ, 'company.read', 'document.read'}
            with self.held_review(v, value, checker).hold(v.s.actor):
                self.assert_helper_denied(v, value, stranger)

    def test_helper_rejects_changed_document_scope_mapping_even_with_same_document_ids(self):
        with reviewer_fixture() as v:
            value, original, _ = company_adoption(v)
            checker = reviewer(v)
            with self.held_review(v, value, checker).hold(v.s.actor):
                # Metadata changed after admission: the ID remains identical.
                v.s.documents[original['revision_id']].update(scope_type='Project', project='P')
                self.assert_helper_denied(v, value, checker)

    def test_helper_rejects_generated_source_digest_growth_inside_same_document_union(self):
        with reviewer_fixture() as v:
            value, original, _ = company_adoption(v)
            checker = reviewer(v)
            document_id = v.s.documents[original['revision_id']]['document_id']
            v.s.generated_digest = 'a' * 64
            def source_plan(company, revision_id, actor, lock=False):
                return ({'generated_sources': [{'document_id': document_id, 'input_digest': v.s.generated_digest}]}
                    if revision_id == original['revision_id'] else {})
            with patch.object(v.provenance, 'source_plan', source_plan):
                with self.held_review(v, value, checker).hold(v.s.actor):
                    self.assertTrue(v.provenance.is_prelocked(
                        {'generated_sources': [{'document_id': document_id, 'input_digest': 'a' * 64}]}, v.s.actor, 'C'))
                    v.s.generated_digest = 'b' * 64
                    self.assert_helper_denied(v, value, checker)

    def test_helper_rejects_owner_identity_rebinding_after_admission(self):
        with reviewer_fixture() as v:
            value, _, _ = company_adoption(v)
            checker = reviewer(v)
            with self.held_review(v, value, checker).hold(v.s.actor):
                v.s.users[v.s.actor.user] = SimpleNamespace(user=v.s.actor.user, person_id=uid())
                self.assert_helper_denied(v, value, checker)

    def test_helper_rejects_transaction_invalidated_owner_provenance(self):
        for callback_kind in ('before_commit', 'before_rollback'):
            with self.subTest(callback=callback_kind), reviewer_fixture() as v:
                value, _, _ = company_adoption(v)
                checker = reviewer(v)
                with self.held_review(v, value, checker).hold(v.s.actor):
                    getattr(sys.modules['frappe'].db, callback_kind).run()
                    self.assertFalse(v.provenance.is_prelocked({}, v.s.actor, 'C'))
                    self.assert_helper_denied(v, value, checker)
                self.assertIsNone(v.locking._active.get())
                self.assertIsNone(v.provenance._prelocked.get())

    def test_helper_rechecks_owner_admission_when_read_returns_successfully(self):
        with reviewer_fixture() as v:
            value, _, _ = company_adoption(v)
            checker = reviewer(v)
            with self.held_review(v, value, checker).hold(v.s.actor):
                original = v.locking._active.get()
                token = v.provenance._prelocked.get()
                with self.assertRaises(DomainError) as error:
                    with v.locking.reviewer_read('C', 'P', 'adoption_request', value['id'], checker) as locking_read:
                        self.assertFalse(locking_read)
                        sys.modules['frappe'].db.before_rollback.run()
                self.assertEqual(error.exception.code, 'document_prelock_required')
                self.assertIs(v.locking._active.get(), original)
                self.assertIs(v.provenance._prelocked.get(), token)
            self.assertIsNone(v.locking._active.get())
            self.assertIsNone(v.provenance._prelocked.get())

    def test_helper_rejects_unrelated_subject_even_when_its_sources_are_an_admitted_subset(self):
        with reviewer_fixture() as v:
            value, _, _ = company_adoption(v)
            checker = reviewer(v)
            other = v.shared.create_adoption('C', 'P', uid(), value['library_scope'],
                value['library_revision'], value['library_digest'],
                {'purpose': 'Separate immutable request', 'target_locator': 'Separate Project section',
                 'change_reason': 'Different request same exact original'})['adoption_request']
            self.assertEqual(other['artifacts'], value['artifacts'])
            with self.held_review(v, value, checker).hold(v.s.actor):
                self.assert_helper_denied(v, other, checker)

    def test_helper_body_exception_preserves_requester_tokens_and_next_eligible_read(self):
        with reviewer_fixture() as v:
            value, _, _ = company_adoption(v)
            checker = reviewer(v)
            with self.held_review(v, value, checker).hold(v.s.actor):
                original = v.locking._active.get()
                token = v.provenance._prelocked.get()
                with self.assertRaisesRegex(RuntimeError, 'review body failed'):
                    with v.locking.reviewer_read('C', 'P', 'adoption_request', value['id'], checker) as locking_read:
                        self.assertFalse(locking_read)
                        self.assertIs(v.locking._active.get(), original)
                        self.assertIs(v.provenance._prelocked.get(), token)
                        raise RuntimeError('review body failed')
                self.assertIs(v.locking._active.get(), original)
                self.assertIs(v.provenance._prelocked.get(), token)
                with v.locking.reviewer_read('C', 'P', 'adoption_request', value['id'], checker) as locking_read:
                    self.assertFalse(locking_read)
                    v.gov.authorize_subject(kind='adoption_request', actor=checker, company='C', project='P',
                        subject_id=value['id'], phase='review', lock=False)
            self.assertIsNone(v.locking._active.get())
            self.assertIsNone(v.provenance._prelocked.get())

    def test_rebound_or_ambiguous_prelock_candidate_never_locks_an_unplanned_person(self):
        for mode in ('rebound', 'ambiguous'):
            with self.subTest(mode=mode), reviewer_fixture() as v:
                value, _, _ = company_adoption(v)
                checker = reviewer(v)
                unplanned_person = uid()
                if mode == 'rebound':
                    v.s.users[checker.user] = SimpleNamespace(user=checker.user, person_id=unplanned_person)
                else:
                    v.s.ambiguous_users.add(checker.user)
                db = sys.modules['frappe'].db
                actual_sql = db.sql
                def candidate_sql(query, args=(), **kw):
                    # A hint may be stale/ambiguous. The current nonlocking
                    # identity check must precede any candidate Person lock.
                    if query.startswith('SELECT user FROM `tabCipher Identity Binding`') and args[0] == checker.person_id:
                        return [SimpleNamespace(user=checker.user)]
                    return actual_sql(query, args, **kw)
                v.s.actor_lock_calls.clear()
                outer = self.held_review(v, value, checker)
                with patch.object(db, 'sql', candidate_sql), outer.hold(v.s.actor):
                    self.assertNotIn((checker.user, checker.person_id), outer.review_identities)
                    self.assert_helper_denied(v, value, checker)
                    self.assertFalse(any(user == checker.user for user, _ in v.s.actor_lock_calls),
                        'A rejected hint must not lock its candidate Person')
                    self.assertFalse(any(person_id == unplanned_person for _, person_id in v.s.actor_lock_calls))

    def test_helper_fails_closed_when_current_committed_read_isolation_cannot_be_verified(self):
        cases = [
            ('repeatable-read', [('REPEATABLE-READ',)], None),
            ('read-uncommitted', [('READ-UNCOMMITTED',)], None),
            ('serializable', [('SERIALIZABLE',)], None),
            ('unknown', [('UNKNOWN',)], None),
            ('missing', [], None),
            ('null', [(None,)], None),
            ('unexpected-shape', {'tx_isolation': 'READ-COMMITTED'}, None),
            ('sql-error', None, RuntimeError('Synthetic unsupported isolation variable')),
        ]
        for label, rows, failure in cases:
            with self.subTest(case=label), reviewer_fixture() as v:
                value, _, _ = company_adoption(v)
                checker = reviewer(v)
                with self.held_review(v, value, checker).hold(v.s.actor):
                    original = v.locking._active.get()
                    token = v.provenance._prelocked.get()
                    v.s.isolation_rows, v.s.isolation_error = rows, failure
                    with self.assertRaises(DomainError) as error:
                        with v.locking.reviewer_read('C', 'P', 'adoption_request', value['id'], checker):
                            self.fail('Unverified current-read isolation must not admit cross-identity reads')
                    self.assertEqual(error.exception.code, 'document_review_unavailable')
                    self.assertIs(v.locking._active.get(), original)
                    self.assertIs(v.provenance._prelocked.get(), token)

    def test_review_capability_revocation_after_prelock_survives_readonly_recursion(self):
        with reviewer_fixture() as v:
            value, _, _ = company_adoption(v)
            checker = reviewer(v)
            before = deepcopy((v.s.rows, v.s.consumptions, v.s.native_receipts))
            with self.held_review(v, value, checker).hold(v.s.actor):
                self.assertIn((checker.user, checker.person_id), v.locking._active.get()['review_identities'])
                v.s.duties[checker.person_id].remove(v.r.REVIEW)
                with self.assertRaises(DomainError) as error:
                    v.gov.authorize_subject(kind='adoption_request', actor=checker, company='C', project='P',
                        subject_id=value['id'], phase='review', lock=True)
                self.assertEqual(error.exception.code, 'capability_denied')
            self.assertEqual((v.s.rows, v.s.consumptions, v.s.native_receipts), before)

    def test_generated_producer_permission_revocation_reaches_unmodified_provenance_authorization(self):
        with reviewer_fixture() as v:
            value, original, _ = company_adoption(v)
            checker = reviewer(v)
            v.s.company_duties[checker.person_id].add('commercial.read')
            document_id = v.s.documents[original['revision_id']]['document_id']
            revision_id = uid()
            binding = {'schema': 'cipher.proposal.output.input.v1', 'company': 'C',
                'proposal_id': uid(), 'proposal_revision_id': revision_id,
                'proposal_revision_digest': 'a' * 64, 'native_fingerprint': 'b' * 64,
                'accepted_estimate': {}, 'source_citations': [],
                'recipients': [{'name': 'Synthetic internal', 'email': 'internal@example.invalid', 'organization': ''}],
                'cover': '', 'renderer': {}}
            checksum = digest(binding)
            producer = {'name': document_id, 'company': 'C', 'project': None, 'scope_type': 'Company',
                'producer_kind': v.provenance.PRODUCER, 'producer_reference': revision_id,
                'producer_input_digest': checksum, 'producer_binding_json': canonical_json(binding)}
            def source_plan(company, revision, actor, lock=False):
                return ({'generated_sources': [{'document_id': document_id, 'input_digest': checksum}]}
                    if revision == original['revision_id'] else {})
            with patch.object(v.provenance, 'source_plan', source_plan):
                with self.held_review(v, value, checker).hold(v.s.actor):
                    # The native retrieval boundary now reports a generated
                    # parent. Its real provenance.authorize/authorize_binding
                    # must perform fresh commercial permission checks.
                    v.s.generated_producers[original['revision_id']] = producer
                    v.s.company_duties[checker.person_id].remove('commercial.read')
                    seen = []
                    actual_authorize = v.provenance.authorize
                    def observe_provenance(row, actor, lock=False):
                        seen.append((actor.person_id, lock, row['producer_kind']))
                        return actual_authorize(row, actor, lock=lock)
                    with patch.object(v.provenance, 'authorize', observe_provenance):
                        with self.assertRaises(DomainError) as error:
                            v.gov.authorize_subject(kind='adoption_request', actor=checker, company='C', project='P',
                                subject_id=value['id'], phase='review', lock=True)
                    self.assertEqual(error.exception.code, 'capability_denied')
                    self.assertIn((checker.person_id, False, v.provenance.PRODUCER), seen)
                    self.assertFalse(v.s.consumptions)

    def test_rebound_recipient_is_still_denied_before_source_locks_or_effect(self):
        with reviewer_fixture() as v:
            transmittal, _, recipient, checker = project_transmittal(v)
            packet = new_packet(v, 'transmittal', transmittal, checker)
            v.s.users[recipient.user] = SimpleNamespace(user=recipient.user, person_id=uid())
            before = deepcopy((v.s.rows, v.s.consumptions, v.s.native_receipts))
            with self.assertRaises(DomainError) as error:
                execute(v, packet)
            self.assertEqual(error.exception.code, 'document_people_changed')
            self.assertFalse(any(row[0] == 'document' for row in v.s.observed))
            self.assertEqual((v.s.rows, v.s.consumptions, v.s.native_receipts), before)

    def test_requester_alias_is_still_not_an_independent_documentary_reviewer(self):
        with reviewer_fixture() as v:
            request, _, _ = company_adoption(v)
            alias = SimpleNamespace(user='alias@example.invalid', person_id=v.s.actor.person_id)
            v.s.users[alias.user] = alias
            with self.assertRaises(DomainError) as error:
                v.gov.authorize_subject(kind='adoption_request', actor=alias, company='C', project='P',
                    subject_id=request['id'], phase='review', lock=False)
            self.assertEqual(error.exception.code, 'independent_document_review')
            self.assertFalse(v.s.consumptions)


if __name__ == '__main__':
    unittest.main(verbosity=2)
