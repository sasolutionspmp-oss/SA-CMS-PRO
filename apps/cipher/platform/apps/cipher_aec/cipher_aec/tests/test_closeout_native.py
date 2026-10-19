"""One ordinary Closeout integration journey on an isolated synthetic Project.

Uses real Frappe storage, scoped duties, and service commands. The case rolls
back its Project, sources, sessions, and facts; no external effects are enabled.
"""
from copy import deepcopy
from uuid import uuid4

import frappe
from frappe.tests import IntegrationTestCase

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.closeout import service
from cipher_aec.document_control import service as document_control
from cipher_aec.documents import service as documents
from cipher_aec.governance.commands import read_operation
from cipher_aec.governance.context import trusted_write
from cipher_aec.install import _grant, seed_synthetic, set_synthetic_duty
from cipher_aec.quality_safety import service as quality
from cipher_aec.tests import test_quality_safety_native as quality_fixture


class TestCloseoutNative(IntegrationTestCase):
    # Plain fixture methods only: no inherited Quality cases or super() methods.
    login = quality_fixture.TestQualitySafetyNative.login
    upload = quality_fixture.TestQualitySafetyNative.upload
    permission_definition = quality_fixture.TestQualitySafetyNative.permission_definition
    locator = quality_fixture.TestQualitySafetyNative.locator

    def setUp(self):
        super().setUp()
        frappe.set_user('Administrator')
        self.old_request = getattr(frappe.local, 'request', None)
        self.old_sid = getattr(frappe.session, 'sid', None)
        self.savepoint = 'closeout_native_' + uuid4().hex
        frappe.db.savepoint(self.savepoint)
        self.fixture = seed_synthetic()
        self.company, self.users = self.fixture['company'], self.fixture['users']
        with trusted_write():
            self.project = frappe.get_doc({
                'doctype': 'Project', 'company': self.company,
                'project_name': 'Closeout integration ' + uuid4().hex, 'status': 'Open',
            }).insert(ignore_permissions=True).name
            common = ('project.read', 'document.read', 'quality.read', 'closeout.read')
            duties = {
                'primary': ('document.write', 'document.control.read', 'document.rights.manage',
                            'quality.write', 'closeout.write', 'closeout.check', 'closeout.accept'),
                'reviewer': ('quality.check', 'closeout.check', 'closeout.write', 'closeout.accept'),
                'outsider': ('quality.close', 'closeout.accept'),
            }
            for key, abilities in duties.items():
                for ability in (*common, *abilities):
                    _grant(self.users[key]['person'], self.company, self.project, ability)
        self.login('primary')
        unique = uuid4().hex.encode()
        self.permission_upload, self.permission_ref = self.upload(
            b'Authored synthetic permission for internal documentary closeout. ' + unique,
            'closeout-permission.txt',
        )
        self.source_bytes = b'Ordinary synthetic punch correction and verification record. ' + unique
        self.source_upload, self.source = self.upload(self.source_bytes, 'closeout-correction.txt')
        document_control.set_rights(
            self.company, self.project, str(uuid4()), self.source_upload['document']['id'],
            None, self.permission_definition(self.permission_ref),
        )
        self.assertEqual(documents.download_revision(self.company, self.source['revision_id'])[1], self.source_bytes)

    def tearDown(self):
        try:
            frappe.set_user('Administrator')
            frappe.local.request, frappe.session.sid = self.old_request, self.old_sid
            frappe.db.rollback(save_point=self.savepoint)
        finally:
            super().tearDown()

    def test_native_punch_turnover_independence_and_preserved_amendment(self):
        # A punch result depends on a real ordinary three-person Quality closure.
        closure_item = str(uuid4())
        finding = quality.create_record(self.company, self.project, str(uuid4()), 'record', 'deficiency', {
            'title': 'Synthetic punch correction', 'local_date': '2026-10-18',
            'location': 'Grid A', 'description': 'Retain the documented correction and verification.',
            'required_closure_items': [{'item_id': closure_item, 'description': 'Verify the corrected item.'}],
        }, [self.locator()])
        submitted = quality.transition(
            self.company, self.project, str(uuid4()), 'record', finding['header']['id'],
            digest(finding['header']), 'submit', 'Submit the documentary finding.', [], [],
        )
        self.login('reviewer')
        checked = quality.transition(
            self.company, self.project, str(uuid4()), 'record', finding['header']['id'],
            digest(submitted['header']), 'check', 'Independently checked the exact source.', [self.locator()], [],
        )
        self.login('outsider')
        closed = quality.transition(
            self.company, self.project, str(uuid4()), 'record', finding['header']['id'],
            digest(checked['header']), 'close', 'Independently retained the correction evidence.', [],
            [{'item_id': closure_item, 'evidence': [self.locator()]}],
        )
        self.assertEqual(closed['header']['status'], 'closed')
        self.assertEqual(len({finding['revision']['author_person'], checked['decision']['author_person'],
                              closed['decision']['author_person']}), 3)

        self.login('primary')
        definition = {'title': 'Synthetic punch turnover', 'description': 'Documentary closeout only.',
                      'asset_tag': '', 'location': 'Grid A'}
        requirements = [{'item_id': str(uuid4()), 'title': 'Documented correction', 'category': 'punch',
                         'required': True, 'criteria': 'Retain independently closed deficiency evidence.'}]
        create_operation = str(uuid4())
        created = service.create_package(self.company, self.project, create_operation, definition, requirements)
        package_id = created['package']['id']
        original_revision = deepcopy(created['package_revision'])
        original_requirement = deepcopy(created['requirements'][0])
        recorded = service.record_result(
            self.company, self.project, str(uuid4()), package_id, digest(created['package']),
            original_requirement['id'], {'outcome': 'pass', 'notes': 'The correction evidence is retained.',
                                        'performed_on': '2026-10-18', 'performed_by': 'Synthetic field observer'},
            [self.locator()], [{'kind': 'quality_closure', 'id': closed['decision']['id'],
                               'record_digest': digest(closed['decision'])}],
        )
        original_result = deepcopy(recorded['result'])
        self.assertEqual(original_result['evidence'][0]['revision_id'], self.source['revision_id'])
        self.assertEqual(original_result['evidence'][0]['source_sha256'], self.source['source_sha256'])
        self.assertEqual(original_result['requirement_digest'], digest(original_requirement))
        self.assertEqual(frappe.get_doc('Cipher Test Result', original_result['id']).record_digest, digest(original_result))

        # Both users have the checking duty; the alias is the same canonical person.
        self.assertEqual(self.users['primary']['person'], self.users['alias']['person'])
        for key in ('primary', 'alias'):
            self.login(key)
            with self.assertRaises(DomainError) as denied:
                service.accept_result(
                    self.company, self.project, str(uuid4()), package_id, digest(recorded['package']),
                    original_result['id'], digest(original_result), 'Attempted self acceptance.',
                )
            self.assertEqual(denied.exception.code, 'independent_closeout_required')
        self.login('reviewer')
        accepted_result = service.accept_result(
            self.company, self.project, str(uuid4()), package_id, digest(recorded['package']),
            original_result['id'], digest(original_result), 'Independently accepted the exact passing evidence.',
        )
        self.assertNotEqual(accepted_result['decision']['author_person'], original_result['author_person'])
        assembled = service.assemble_turnover(
            self.company, self.project, str(uuid4()), package_id, digest(accepted_result['package']),
            'Assembled the independently accepted punch evidence.',
        )
        original_turnover = deepcopy(assembled['turnover'])
        self.assertEqual(original_turnover['items'], accepted_result['package']['accepted_results'])
        # The package author and the distinct assembler each have acceptance duty.
        for key in ('primary', 'reviewer'):
            self.login(key)
            with self.assertRaises(DomainError) as denied:
                service.accept_turnover(
                    self.company, self.project, str(uuid4()), package_id, digest(assembled['package']),
                    original_turnover['id'], digest(original_turnover), 'Attempted dependent turnover acceptance.',
                )
            self.assertEqual(denied.exception.code, 'independent_closeout_required')
        self.login('outsider')
        accepted = service.accept_turnover(
            self.company, self.project, str(uuid4()), package_id, digest(assembled['package']),
            original_turnover['id'], digest(original_turnover), 'Independently accepted the exact turnover snapshot.',
        )
        original_decision = deepcopy(accepted['decision'])
        self.assertEqual(accepted['package']['status'], 'accepted')
        self.assertEqual(accepted['package']['accepted_turnover'], original_turnover['id'])
        self.assertNotIn(original_decision['author_person'],
                         {original_revision['author_person'], original_turnover['author_person']})
        self.assertTrue(all(value is False for value in original_decision['no_effects'].values()))

        self.login('primary')
        with self.assertRaises(DomainError) as denied:
            service.revise_package(self.company, self.project, str(uuid4()), package_id,
                                   digest(accepted['package']), definition, requirements)
        self.assertEqual(denied.exception.code, 'invalid_closeout')
        amended = service.revise_package(
            self.company, self.project, str(uuid4()), package_id, digest(accepted['package']),
            {**definition, 'description': 'Explicit documentary successor for additional verification.'},
            requirements, 'Reopen the working package for additional documented verification.',
        )
        self.assertEqual(amended['package']['status'], 'draft')
        self.assertEqual(amended['package']['revision_number'], 2)
        self.assertEqual(amended['package']['accepted_turnover'], original_turnover['id'])
        self.assertEqual(amended['package']['result_heads'], [])
        self.assertEqual(amended['package']['accepted_results'], [])
        self.assertIsNone(amended['package']['turnover_head'])
        self.assertEqual(amended['package_revision']['predecessor'], original_revision['id'])
        self.assertEqual(amended['package_revision']['amendment_of'], original_turnover['id'])
        self.assertEqual(amended['requirements'][0]['predecessor'], original_requirement['id'])
        self.assertEqual(amended['requirements'][0]['item_id'], original_requirement['item_id'])
        for kind, original in (('package_revision', original_revision), ('requirement', original_requirement),
                               ('test_result', original_result), ('turnover', original_turnover),
                               ('decision', original_decision)):
            self.assertEqual(service.get_record(self.company, self.project, kind, original['id'])['record'], original)
        receipt = read_operation(self.company, self.project, create_operation)
        self.assertEqual(receipt['package_revision'], original_revision)
        self.assertTrue(receipt['operation']['replayed'])

        frappe.set_user('Administrator')
        set_synthetic_duty(self.users['primary']['user'], self.project, 'closeout.read', 0)
        self.login('primary')
        for read in (lambda: service.get_record(self.company, self.project, 'turnover', original_turnover['id']),
                     lambda: read_operation(self.company, self.project, create_operation)):
            with self.assertRaises(DomainError) as denied:
                read()
            self.assertEqual(denied.exception.code, 'capability_denied')
