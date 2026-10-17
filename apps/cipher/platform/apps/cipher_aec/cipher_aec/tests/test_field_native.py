"""FLD-01 Frappe persistence and permissions tests, prepared for isolated native CI.

Each test owns rollback-isolated Projects and explicit field duties. Authored
permission evidence is a distinct retained TXT source. These tests use ordinary
field transitions and do not request commercial authorization or delivery.
"""
import base64
from copy import deepcopy
import hashlib
from uuid import uuid4
from unittest.mock import patch

from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request
import frappe
from frappe.model.document import Document
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.document_control import service as document_control
from cipher_aec.document_control import rights
from cipher_aec.documents import service as documents
from cipher_aec.field import contracts as rules, repository, service
from cipher_aec.governance.commands import read_operation
from cipher_aec.governance.context import trusted_write
from cipher_aec.install import _grant, seed_synthetic, set_synthetic_duty


class TestFieldNative(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user('Administrator')
        self.savepoint = 'field_native_' + uuid4().hex
        frappe.db.savepoint(self.savepoint)
        self.fixture = seed_synthetic()
        self.company = self.fixture['company']
        self.users = self.fixture['users']
        self.old_request = getattr(frappe.local, 'request', None)
        self.old_sid = getattr(frappe.session, 'sid', None)
        with trusted_write():
            self.project = frappe.get_doc({
                'doctype': 'Project', 'company': self.company,
                'project_name': 'FLD01 integration ' + uuid4().hex, 'status': 'Open',
            }).insert(ignore_permissions=True).name
            self.other_project = frappe.get_doc({
                'doctype': 'Project', 'company': self.company,
                'project_name': 'FLD01 separate scope ' + uuid4().hex, 'status': 'Open',
            }).insert(ignore_permissions=True).name
            for key in ('primary', 'reviewer'):
                for ability in (
                    'project.read', 'document.read', 'field.read', 'field.write',
                    'field.review', 'field.accept', 'field.acknowledge',
                ):
                    _grant(self.users[key]['person'], self.company, self.project, ability)
            for ability in ('project.read', 'document.read', 'field.read'):
                _grant(self.users['primary']['person'], self.company, self.other_project, ability)
            for ability in ('document.write', 'document.control.read', 'document.rights.manage'):
                _grant(self.users['primary']['person'], self.company, self.project, ability)
        self.login('primary')
        self.permission_upload, self.permission_ref = self.upload(
            b'Synthetic authored field permission evidence. Internal project use only.',
            'field-permission-evidence.txt',
        )
        self.source_bytes = b'Observed installed pipe: 12.375 LF at Grid A. Documentary field facts only.'
        self.source_upload, self.source = self.upload(self.source_bytes, 'field-observation.txt')
        self.source_document = self.source_upload['document']['id']
        self.rights_definition = self.permission_definition(self.permission_ref)
        self.source_rights = document_control.set_rights(
            self.company, self.project, str(uuid4()), self.source_document, None,
            self.rights_definition,
        )['rights']
        self.assertNotEqual(self.source_document, self.permission_upload['document']['id'])
        self.assertEqual(self.source_rights['evidence_artifact']['revision_id'], self.permission_ref['revision_id'])
        self.assertEqual(self.source_rights['evidence_artifact']['source_sha256'], self.permission_ref['source_sha256'])
        self.assertEqual(documents.download_revision(self.company, self.source['revision_id'])[1], self.source_bytes)

    def tearDown(self):
        frappe.set_user('Administrator')
        frappe.local.request = self.old_request
        frappe.session.sid = self.old_sid
        frappe.db.rollback(save_point=self.savepoint)
        super().tearDown()

    def login(self, key):
        user = self.users[key]['user']
        frappe.set_user(user)
        sid = 'synthetic-field-test-' + uuid4().hex
        frappe.session.sid = sid
        frappe.local.request = Request(EnvironBuilder(
            method='POST', base_url='http://cipher.localhost', headers={'Cookie': 'sid=' + sid},
        ).get_environ())
        frappe.db.sql(
            "INSERT INTO tabSessions (user,sid,sessiondata,lastupdate,status) VALUES (%s,%s,%s,%s,'Active')",
            (user, sid, canonical_json({'user': user}), now_datetime()),
        )

    def upload(self, content, filename):
        checksum = hashlib.sha256(content).hexdigest()
        result = documents.upload_document(
            company=self.company, project=self.project, title='Retained synthetic field source',
            filename=filename, content=content, byte_length=len(content), sha256=checksum,
            operation_id=str(uuid4()),
        )
        self.assertEqual(result['revision']['sha256'], checksum)
        return result, {'revision_id': result['revision']['id'], 'source_sha256': checksum}

    def permission_definition(self, evidence):
        return {
            'ingest_allowed': True, 'read_allowed': True, 'distribute_allowed': False,
            'rights_basis': 'Synthetic manually authored permission declaration; no legal licensing inference.',
            'rights_holder': 'Synthetic field source author',
            'allowed_purpose': 'Project field capture and retained internal reading',
            'restriction': 'No external delivery, financial authority or professional certification',
            'valid_from': None, 'valid_until': None, 'evidence_artifact': evidence,
        }

    def locator(self, reference=None, label='Grid A / installed pipe observation'):
        return {**(reference or self.source), 'page': 1, 'locator': label}

    def daily(self):
        return {
            'local_date': '2026-10-17', 'superintendent_user': self.users['primary']['user'],
            'weather': '', 'weather_sources': [], 'crews': ['Civil crew: two people'],
            'activities': ['Installed the documented pipe segment.'], 'delays': [], 'visitors': [],
        }

    def quantity(self, original=None, predecessor=None):
        return {
            'original_event_id': original or str(uuid4()), 'supersedes_event_id': predecessor,
            'kind': 'installed', 'description': 'Observed installed pipe', 'wbs_code': '02.01',
            'cost_code': 'PIPE', 'quantity': '12.375', 'unit': 'LF', 'location': 'Grid A',
            'sources': [self.locator()],
        }

    def ticket(self):
        return {
            'local_date': '2026-10-17', 'title': 'Documented obstruction removal',
            'customer_name': 'Synthetic owner', 'location': 'Grid A',
            'work_description': 'Removed the documented obstruction.',
            'potential_change_reference': 'Potential change for separate commercial evaluation',
            'lines': [{
                'kind': 'labor', 'description': 'Two-person field crew', 'quantity': '3.25',
                'unit': 'person-hours', 'sources': [self.locator()],
            }],
        }

    def create(self, family='daily', operation=None, quantities=None):
        return service.create_record(
            self.company, self.project, operation or str(uuid4()), family,
            self.daily() if family == 'daily' else self.ticket(), [],
            ([self.quantity()] if quantities is None else quantities) if family == 'daily' else [],
        )

    def transition(self, result, action, operation=None):
        return service.transition(
            self.company, self.project, operation or str(uuid4()), result['family'],
            result['header']['id'], digest(result['header']), action,
            'Recorded documentary ' + action,
            [self.locator(label='Customer acknowledgment evidence')] if action == 'acknowledge' else [],
            'Synthetic customer representative' if action == 'acknowledge' else '',
        )

    def accept(self, result):
        self.login('primary')
        result = self.transition(result, 'submit')
        self.login('reviewer')
        result = self.transition(result, 'review')
        return self.transition(result, 'accept')

    def field_counts(self):
        return {doctype: frappe.db.count(doctype, {'project': self.project}) for doctype in rules.KINDS.values()}

    def mutation_counts(self):
        return {
            **self.field_counts(),
            'history': frappe.db.count('Cipher History Event', {'project': self.project}),
            'receipts': frappe.db.count('Cipher Command Receipt', {'project': self.project}),
        }

    def assert_receipt_absent(self, operation):
        receipt = digest({'person': self.users['primary']['person'], 'operation_id': operation})
        self.assertFalse(frappe.db.exists('Cipher Command Receipt', receipt))

    def test_daily_acceptance_amendment_retains_exact_originals_and_alias_separation(self):
        operation = str(uuid4())
        authored_quantity = self.quantity()
        first = self.create(operation=operation, quantities=[authored_quantity])
        original, original_quantity = deepcopy(first['revision']), deepcopy(first['quantities'][0])
        captured = original_quantity['definition']['sources'][0]
        self.assertEqual(captured['document_id'], self.source_document)
        self.assertEqual(captured['source_sha256'], hashlib.sha256(self.source_bytes).hexdigest())
        self.assertEqual(captured['byte_length'], len(self.source_bytes))
        self.assertEqual(captured['mime_type'], 'text/plain')
        submitted = self.transition(first, 'submit')
        self.login('alias')
        with self.assertRaises(DomainError) as refused:
            self.transition(submitted, 'review')
        self.assertEqual(refused.exception.code, 'independent_field_review_required')
        self.login('reviewer')
        accepted = self.transition(self.transition(submitted, 'review'), 'accept')
        acceptance = deepcopy(accepted['decision'])
        self.login('primary')
        amended_quantity = self.quantity(original_quantity['original_event_id'], original_quantity['id'])
        amended_quantity['quantity'] = '12.500'
        amended = service.revise_record(
            self.company, self.project, str(uuid4()), 'daily', first['header']['id'],
            digest(accepted['header']), self.daily(), [], [amended_quantity],
            'Corrected the measured installed length after acceptance.',
        )
        self.assertEqual(amended['header']['status'], 'draft')
        self.assertEqual(amended['header']['accepted_revision'], original['id'])
        self.assertEqual(amended['revision']['amendment_of'], original['id'])
        self.assertEqual(amended['revision']['prior_decision'], acceptance['id'])
        self.assertEqual(amended['quantities'][0]['supersedes_event_id'], original_quantity['id'])
        for kind, value in (('daily_revision', original), ('quantity', original_quantity), ('decision', acceptance)):
            self.assertEqual(repository.raw(kind, value['id']), value)
            self.assertEqual(service.get_record(self.company, self.project, kind, value['id'])['record'], value)
        replay = service.create_record(
            self.company, self.project, operation, 'daily', self.daily(), [], [authored_quantity],
        )
        self.assertTrue(replay['operation']['replayed'])
        self.assertEqual(replay['revision'], original)
        self.assertEqual(read_operation(self.company, self.project, operation)['revision'], original)
        page = service.list_records(self.company, self.project, 'daily_revision', first['header']['id'], 1)
        self.assertEqual(len(page['items']), 1)
        self.assertIsNone(page['total'])
        self.assertTrue(page['next_cursor'])

    def test_ticket_acceptance_and_acknowledgment_have_no_commercial_or_financial_effect(self):
        names = ('Sales Order', 'Sales Invoice', 'Purchase Order', 'Purchase Invoice', 'Journal Entry', 'GL Entry')
        before = {name: frappe.db.count(name) for name in names}
        created = self.create('ticket')
        accepted = self.accept(created)
        acknowledged = self.transition(accepted, 'acknowledge')
        self.assertEqual(acknowledged['header']['status'], 'acknowledged')
        self.assertEqual(acknowledged['header']['accepted_revision'], created['revision']['id'])
        self.assertEqual(acknowledged['decision']['acknowledged_by'], 'Synthetic customer representative')
        self.assertEqual(acknowledged['decision']['no_effects'], rules.NO_EFFECTS)
        self.assertTrue(all(value is False for value in acknowledged['decision']['no_effects'].values()))
        self.assertEqual(acknowledged['decision']['evidence'][0]['document_id'], self.source_document)
        self.assertEqual({name: frappe.db.count(name) for name in names}, before)
        self.assertEqual(frappe.db.get_value('Project', self.project, 'status'), 'Open')
        self.assertEqual(repository.raw('ticket_revision', created['revision']['id']), created['revision'])
        self.assertEqual(read_operation(self.company, self.project, acknowledged['operation']['id'])['decision'], acknowledged['decision'])

    def test_generic_native_and_trusted_repository_writes_cannot_bypass_field_commands(self):
        created = self.create()
        original = created['revision']
        doctype = rules.KINDS['daily_revision']
        record = frappe.get_doc(doctype, original['id'])
        self.assertFalse(frappe.has_permission(doctype, 'read', doc=record, user=frappe.session.user))
        with self.assertRaises(DomainError):
            record.save(ignore_permissions=True)
        record = frappe.get_doc(doctype, original['id'])
        with trusted_write(), self.assertRaises(DomainError):
            record.save(ignore_permissions=True)
        forged = {**deepcopy(created['quantities'][0]), 'id': str(uuid4())}
        with trusted_write(), self.assertRaises(DomainError) as refused:
            repository.write('quantity', forged)
        self.assertEqual(refused.exception.code, 'field_command_required')
        self.assertFalse(frappe.db.exists(rules.KINDS['quantity'], forged['id']))
        self.assertEqual(repository.raw('daily_revision', original['id']), original)

    def test_cross_scope_and_revoked_field_or_document_duties_deny_original_receipts(self):
        operation = str(uuid4())
        authored_quantity = self.quantity()
        created = self.create(operation=operation, quantities=[authored_quantity])
        with self.assertRaises(DomainError):
            service.get_record(self.company, self.other_project, 'daily_revision', created['revision']['id'])
        with self.assertRaises(DomainError):
            read_operation(self.company, self.other_project, operation)
        self.assertEqual(service.list_records(self.company, self.other_project, 'daily_revision')['items'], [])
        for ability in ('field.read', 'document.read'):
            frappe.set_user('Administrator')
            set_synthetic_duty(self.users['primary']['user'], self.project, ability, 0)
            self.login('primary')
            try:
                for call in (
                    lambda: service.get_record(self.company, self.project, 'daily_revision', created['revision']['id']),
                    lambda: read_operation(self.company, self.project, operation),
                    lambda: service.create_record(self.company, self.project, operation, 'daily', self.daily(), [], [authored_quantity]),
                ):
                    with self.subTest(ability=ability), self.assertRaises(DomainError):
                        call()
            finally:
                frappe.set_user('Administrator')
                set_synthetic_duty(self.users['primary']['user'], self.project, ability, 1)
                self.login('primary')
            self.assertEqual(read_operation(self.company, self.project, operation)['revision'], created['revision'])
        self.assertEqual(repository.raw('daily_revision', created['revision']['id']), created['revision'])

    def test_current_source_rights_govern_new_use_and_original_receipt_readback(self):
        operation = str(uuid4())
        authored_quantity = self.quantity()
        created = self.create(operation=operation, quantities=[authored_quantity])
        retained = {**self.rights_definition, 'ingest_allowed': False}
        policy = document_control.set_rights(
            self.company, self.project, str(uuid4()), self.source_document,
            digest(self.source_rights), retained,
        )['rights']
        self.assertEqual(read_operation(self.company, self.project, operation)['revision'], created['revision'])
        with self.assertRaises(DomainError):
            self.transition(created, 'submit')
        document_control.set_rights(
            self.company, self.project, str(uuid4()), self.source_document, digest(policy),
            {**retained, 'read_allowed': False},
        )
        for call in (
            lambda: service.get_record(self.company, self.project, 'daily_revision', created['revision']['id']),
            lambda: read_operation(self.company, self.project, operation),
            lambda: service.create_record(self.company, self.project, operation, 'daily', self.daily(), [], [authored_quantity]),
        ):
            with self.assertRaises(DomainError):
                call()
        self.assertEqual(repository.raw('daily_revision', created['revision']['id']), created['revision'])

    def test_distinct_permission_evidence_and_its_current_read_rights_are_required(self):
        created = self.create()
        with self.assertRaises(DomainError):
            document_control.set_rights(
                self.company, self.project, str(uuid4()), self.source_document,
                digest(self.source_rights), self.permission_definition(self.source),
            )
        _, independent_evidence = self.upload(
            b'Independent synthetic declaration concerning permission-evidence access.',
            'field-permission-access-evidence.txt',
        )
        document_control.set_rights(
            self.company, self.project, str(uuid4()), self.permission_upload['document']['id'], None,
            {**self.permission_definition(independent_evidence), 'ingest_allowed': False, 'read_allowed': False},
        )
        self.assertTrue(rights.current(self.source_document)['read_allowed'])
        for call in (
            lambda: service.get_record(self.company, self.project, 'daily_revision', created['revision']['id']),
            lambda: read_operation(self.company, self.project, created['operation']['id']),
        ):
            with self.assertRaises(DomainError):
                call()

    def test_stale_versions_and_late_receipt_failures_rollback_capture_and_decision(self):
        created = self.create()
        before = self.mutation_counts()
        with self.assertRaises(DomainError) as refused:
            service.revise_record(
                self.company, self.project, str(uuid4()), 'daily', created['header']['id'],
                '0' * 64, self.daily(), [], [],
            )
        self.assertEqual(refused.exception.code, 'stale_field_record')
        self.assertEqual(self.mutation_counts(), before)
        original_insert = Document.insert

        def fail_receipt(document, *args, **kwargs):
            if document.doctype == 'Cipher Command Receipt':
                raise DomainError('field_test_receipt_failure', 'Injected late field receipt failure.', 409)
            return original_insert(document, *args, **kwargs)

        operation = str(uuid4())
        authored_quantity = self.quantity()
        with patch.object(Document, 'insert', fail_receipt), self.assertRaises(DomainError) as failed:
            self.create(operation=operation, quantities=[authored_quantity])
        self.assertEqual(failed.exception.code, 'field_test_receipt_failure')
        self.assertEqual(self.mutation_counts(), before)
        self.assert_receipt_absent(operation)
        recovered = self.create(operation=operation, quantities=[authored_quantity])
        self.assertFalse(recovered['operation']['replayed'])
        before_transition = self.mutation_counts()
        transition_operation = str(uuid4())
        with patch.object(Document, 'insert', fail_receipt), self.assertRaises(DomainError) as failed:
            self.transition(recovered, 'submit', transition_operation)
        self.assertEqual(failed.exception.code, 'field_test_receipt_failure')
        self.assertEqual(self.mutation_counts(), before_transition)
        self.assertEqual(repository.raw('daily', recovered['header']['id']), recovered['header'])
        self.assert_receipt_absent(transition_operation)
        self.assertEqual(self.transition(recovered, 'submit', transition_operation)['header']['status'], 'submitted')

    def test_exact_uploaded_png_photo_is_retained_as_source_image(self):
        content = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
        )
        uploaded, reference = self.upload(content, 'field-observation.png')
        document_control.set_rights(
            self.company, self.project, str(uuid4()), uploaded['document']['id'], None,
            self.permission_definition(self.permission_ref),
        )
        result = service.create_record(
            self.company, self.project, str(uuid4()), 'daily', self.daily(), [{
                'source': self.locator(reference, 'Original field photo'),
                'caption': 'Observed installation in the retained source image.',
                'captured_at': '2026-10-17T09:15:00-04:00', 'representation': 'source_image',
            }], [],
        )
        captured = result['revision']['photos'][0]['source']
        self.assertEqual(captured['mime_type'], 'image/png')
        self.assertEqual(captured['page_count'], 1)
        self.assertEqual(captured['byte_length'], len(content))
        self.assertEqual(captured['source_sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual(documents.download_revision(self.company, reference['revision_id'])[1], content)
