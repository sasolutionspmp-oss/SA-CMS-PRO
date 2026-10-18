"""Actual privacy admission over explicit native metadata, without Frappe."""
from copy import deepcopy
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from uuid import uuid4

from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError


ACTOR = SimpleNamespace(user='privacy-reader@example.invalid', person_id='person-reader')


def registration_value(document='DOC-PRIVATE'):
    return {'id':str(uuid4()), 'company':'C', 'project':'P', 'scope_type':'Project',
        'author_person':'person-author', 'author_user':'author@example.invalid',
        'created_at':'2026-10-17T12:00:00Z', 'document_id':document,
        'rights_basis':'Authored synthetic permission declaration.',
        'permission_evidence':[{'revision_id':'REV-PERMISSION', 'source_sha256':'a'*64,
            'page':1, 'locator':'Synthetic original permission', 'document_id':'DOC-PERMISSION',
            'revision_number':1, 'byte_length':32, 'mime_type':'text/plain', 'page_count':1}],
        'classification':'restricted_from_creation'}


def source_row(**changes):
    return {'name':'DOC-PRIVATE', 'company':'C', 'project':'P', 'scope_type':'Project', **changes}


class IncidentPrivacyFixtureTests(unittest.TestCase):
    def setUp(self):
        self.framework_before = {name:sys.modules.get(name) for name in ('frappe','frappe.model.document','cipher_aec.governance.context')}
        from cipher_aec.tests.incident_privacy_fixture import incident_privacy_fixture
        self.state = self.enterContext(incident_privacy_fixture())
        self.privacy = self.state.privacy

    def assert_denied(self, callback, code):
        with self.assertRaises(DomainError) as error:
            callback()
        self.assertEqual(error.exception.code, code)

    def test_empty_native_registration_table_keeps_ordinary_sources_ordinary(self):
        self.privacy.authorize_source(source_row(), ACTOR)
        self.assertEqual(self.state.duty_reads, [])
        self.assertEqual(self.state.registration_reads, [('DOC-PRIVATE', False)])
        self.state.installed = False
        self.privacy.authorize_source(source_row(), ACTOR, lock=True)
        self.assertEqual(self.state.registration_reads, [('DOC-PRIVATE', False)])

    def test_registered_source_requires_explicit_current_exact_restricted_duty(self):
        value = registration_value(); self.state.add_registration(value)
        self.assert_denied(lambda:self.privacy.authorize_source(source_row(), ACTOR), 'capability_denied')
        self.state.grant(ACTOR, 'C', 'P')
        self.privacy.authorize_source(source_row(), ACTOR, lock=True)
        self.assertEqual(self.state.registration_reads[-1], ('DOC-PRIVATE', True))
        self.assertEqual(self.state.document_reads[-1], (value['id'], True))
        self.assertEqual(self.state.duty_reads[-1], ('C', 'P', 'safety.incident.read', ACTOR.user, ACTOR.person_id, True))
        self.state.grants.clear()
        self.assert_denied(lambda:self.privacy.authorize_source(source_row(), ACTOR), 'capability_denied')

    def test_revision_locator_metadata_resolves_private_parent_before_admission(self):
        self.state.add_registration(registration_value())
        self.state.revisions['REV-PRIVATE'] = {'document':'DOC-PRIVATE', 'company':'C', 'project':'P', 'scope_type':'Project'}
        row = source_row(name='REV-PRIVATE')
        self.assert_denied(lambda:self.privacy.authorize_source(row, ACTOR), 'capability_denied')
        self.state.grant(ACTOR, 'C', 'P')
        self.privacy.authorize_source(row, ACTOR, lock=True)
        self.assertEqual(self.state.locator_reads, ['REV-PRIVATE', 'REV-PRIVATE'])
        self.assertEqual(self.state.registration_reads[-1], ('DOC-PRIVATE', True))

    def test_registered_parent_and_locator_cross_scope_are_refused_before_duty(self):
        self.state.add_registration(registration_value())
        self.state.grant(ACTOR, 'C', 'P')
        for changes in ({'company':'Other'}, {'project':'Other'}, {'scope_type':'Company', 'project':None}):
            with self.subTest(changes=changes):
                self.assert_denied(lambda:self.privacy.authorize_source(source_row(**changes), ACTOR), 'incident_evidence_integrity')
        self.state.revisions['REV-PRIVATE'] = {'document':'DOC-PRIVATE', 'company':'C', 'project':'P', 'scope_type':'Project'}
        self.assert_denied(lambda:self.privacy.authorize_source(source_row(name='REV-PRIVATE', project='Other'), ACTOR), 'incident_evidence_integrity')
        self.assertEqual(self.state.duty_reads, [])

    def test_duplicate_corrupt_json_digest_and_native_metadata_are_refused(self):
        value = registration_value()
        native = self.state.add_registration(value)
        original = deepcopy(native)
        for changes in ({'data_json':'not-json'}, {'record_digest':'0'*64}, {'company':'Other'}, {'project':'Other'}, {'author_person':'Other'}):
            native.clear();native.update(deepcopy(original));native.update(changes)
            with self.subTest(changes=changes):
                self.assert_denied(lambda:self.privacy.authorize_source(source_row(), ACTOR), 'incident_evidence_integrity')
        corrupted = {**value, 'document_id':'Other'}
        native.clear();native.update(deepcopy(original))
        native.update(data_json=canonical_json(corrupted), record_digest=digest(corrupted))
        self.assert_denied(lambda:self.privacy.authorize_source(source_row(), ACTOR), 'incident_evidence_integrity')
        native.clear();native.update(original)
        self.state.add_registration({**value, 'id':str(uuid4())})
        self.assert_denied(lambda:self.privacy.authorize_source(source_row(), ACTOR), 'incident_evidence_integrity')
        self.assertEqual(self.state.duty_reads, [])

    def test_closed_registration_contract_rejects_reclassified_or_extra_data(self):
        value = registration_value();native = self.state.add_registration(value)
        for changes in ({'classification':'ordinary'}, {'scope_type':'Company'}, {'undocumented':True}):
            corrupted = {**value, **changes}
            native['data_json'] = canonical_json(corrupted);native['record_digest'] = digest(corrupted)
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                self.privacy.authorize_source(source_row(), ACTOR)
        self.assertEqual(self.state.duty_reads, [])

    def test_rebound_identity_and_different_person_alias_do_not_inherit_grant(self):
        self.state.add_registration(registration_value());self.state.grant(ACTOR, 'C', 'P')
        self.privacy.authorize_source(source_row(), ACTOR)
        self.state.bindings[ACTOR.user] = 'replacement-person'
        self.assert_denied(lambda:self.privacy.authorize_source(source_row(), ACTOR), 'capability_denied')
        alias = SimpleNamespace(user='another-user@example.invalid', person_id=ACTOR.person_id)
        self.assert_denied(lambda:self.privacy.authorize_source(source_row(), alias), 'capability_denied')

    def test_three_actual_production_functions_are_loaded_without_framework_import(self):
        expected = Path(__file__).parents[1]/'quality_safety/privacy.py'
        for name in ('validate_registration', 'registration', 'authorize_source'):
            self.assertEqual(Path(getattr(self.privacy, name).__code__.co_filename), expected)
        self.assertIs(self.privacy.digest, digest)
        self.assertIs(self.privacy.DomainError, DomainError)
        self.assertEqual({name:sys.modules.get(name) for name in self.framework_before}, self.framework_before)


class QualitySafetyCleanupTests(unittest.TestCase):
    def test_exception_restores_exact_prior_modules_and_attributes_without_deleting_unrelated_symbol(self):
        from cipher_aec.tests.quality_safety_fixtures import fixtures
        package = importlib.import_module('cipher_aec.quality_safety')
        missing = object()
        names = ['cipher_aec.field.sources', *['cipher_aec.quality_safety.'+name for name in ('contracts','repository','sources','service','records','privacy','evidence')]]
        modules_before = {name:sys.modules.get(name, missing) for name in names}
        attributes_before = {name:getattr(sys.modules.get(name.rsplit('.',1)[0]), name.rsplit('.',1)[1], missing) for name in names}
        try:
            previous = ModuleType('cipher_aec.quality_safety.contracts')
            sys.modules[previous.__name__] = previous;package.contracts = previous
            sys.modules.pop('cipher_aec.quality_safety.evidence', None)
            if hasattr(package, 'evidence'):delattr(package, 'evidence')
            expected_modules = {name:sys.modules.get(name, missing) for name in names}
            expected_attributes = {name:getattr(sys.modules.get(name.rsplit('.',1)[0]), name.rsplit('.',1)[1], missing) for name in names}
            with self.assertRaisesRegex(RuntimeError, 'injected fixture body failure'):
                with fixtures():
                    self.assertIsNot(sys.modules[previous.__name__], previous)
                    self.assertNotIn('cipher_aec.quality_safety.evidence', sys.modules)
                    raise RuntimeError('injected fixture body failure')
            for name in names:
                with self.subTest(name=name, boundary='native module'):
                    self.assertIs(sys.modules.get(name, missing), expected_modules[name])
                with self.subTest(name=name, boundary='package attribute'):
                    self.assertIs(getattr(sys.modules.get(name.rsplit('.',1)[0]), name.rsplit('.',1)[1], missing), expected_attributes[name])
            unrelated = object()
            with self.assertRaisesRegex(RuntimeError, 'unrelated symbol replacement'):
                with fixtures():
                    package.privacy = unrelated
                    raise RuntimeError('unrelated symbol replacement')
            self.assertIs(package.privacy, unrelated)
        finally:
            for name in names:
                if modules_before[name] is missing:sys.modules.pop(name, None)
                else:sys.modules[name] = modules_before[name]
                parent = sys.modules.get(name.rsplit('.',1)[0]);attribute = name.rsplit('.',1)[1]
                if parent is None:continue
                if attributes_before[name] is missing:
                    if hasattr(parent, attribute):delattr(parent, attribute)
                else:setattr(parent, attribute, attributes_before[name])

    def test_absent_lazy_evidence_module_and_attribute_remain_absent_after_fixture(self):
        from cipher_aec.tests.quality_safety_fixtures import fixtures
        package = importlib.import_module('cipher_aec.quality_safety')
        missing = object(); name = 'cipher_aec.quality_safety.evidence'
        old_module = sys.modules.pop(name, missing);old_attribute = getattr(package, 'evidence', missing)
        if hasattr(package, 'evidence'):delattr(package, 'evidence')
        try:
            with fixtures() as (state, rules, repo, sources, service, records):
                self.assertNotIn(name, sys.modules)
                self.assertFalse(hasattr(package, 'evidence'))
                self.assertEqual(state.events, [])
            self.assertNotIn(name, sys.modules)
            self.assertFalse(hasattr(package, 'evidence'))
        finally:
            if old_module is not missing:sys.modules[name] = old_module
            if old_attribute is not missing:setattr(package, 'evidence', old_attribute)


class DocumentControlFixtureCleanupTests(unittest.TestCase):
    def test_stale_package_scope_cannot_escape_current_native_fixture(self):
        from cipher_aec.tests.test_document_control import fixture
        package = importlib.import_module('cipher_aec.document_control')
        name = 'cipher_aec.document_control.scopes'; absent = object()
        prior_module = sys.modules.get(name, absent); prior_attribute = getattr(package, 'scopes', absent)
        stale = ModuleType(name)
        try:
            sys.modules[name] = stale; package.scopes = stale
            with fixture():
                shared = importlib.import_module('cipher_aec.document_control.shared')
                scopes = importlib.import_module(name)
                self.assertIsNot(scopes, stale)
                self.assertIs(shared.scopes, scopes)
                self.assertIs(scopes.frappe, sys.modules['frappe'])
            self.assertIs(sys.modules[name], stale)
            self.assertIs(package.scopes, stale)
        finally:
            if prior_module is absent:sys.modules.pop(name, None)
            else:sys.modules[name] = prior_module
            if prior_attribute is absent:
                if hasattr(package, 'scopes'):delattr(package, 'scopes')
            else:package.scopes = prior_attribute


if __name__ == '__main__':unittest.main()
