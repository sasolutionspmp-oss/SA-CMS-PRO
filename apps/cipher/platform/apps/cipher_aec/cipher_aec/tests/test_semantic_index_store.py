"""DOC04 real checkpoint/controller contracts with host native projections.

Only Frappe's persistence/session objects are doubled. Tests execute FrappeStore,
checkpoint validation and the actual DocType controller. No native database,
queue, provider, deployment, isolation or connected qualification is claimed.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import importlib
import json
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_semantic_index_service import ACTOR, SELECTOR, SCOPE, fixture

STORE_MODULE = 'cipher_aec.semantic_index.store'
TRANSACTIONS_MODULE = 'cipher_aec.semantic_index.transactions'
CONTROLLER_MODULE = 'cipher_aec.cipher_semantic_index.doctype.cipher_semantic_corpus.cipher_semantic_corpus'


def module(name, **attributes):
    result = ModuleType(name)
    result.__dict__.update(attributes)
    return result


def checkpoint():
    backend, memory, _, _, _ = fixture()
    backend.prepare(SCOPE, [SELECTOR], str(uuid4()), ACTOR)
    key, value = next(iter(memory.rows.items()))
    return key, deepcopy(value)


@contextmanager
def native_projection_fixture():
    """Restore both sys.modules and package attributes after temporary stubs."""
    trusted = ContextVar('semantic_store_test_trusted', default=False)
    state = SimpleNamespace(rows={}, events=[], commits=0, isolation=[['READ-COMMITTED']],
                            isolation_error=None, persistence_error=None, native_mutation=None)

    @contextmanager
    def trusted_write():
        token = trusted.set(True)
        try:
            yield
        finally:
            trusted.reset(token)

    def require_trusted_write():
        if not trusted.get():
            raise DomainError('governed_write_required', 'Use the canonical governed command.', 403)

    class Database:
        transaction_writes = 0

        def sql(self, query, args=(), **kwargs):
            state.events.append(('sql', query, args))
            if query == 'SELECT @@session.tx_isolation':
                if state.isolation_error:
                    raise state.isolation_error
                return deepcopy(state.isolation)
            if query.startswith('SELECT state_version FROM `tabCipher Semantic Corpus`'):
                row = state.rows.get(args[0])
                return [(row['state_version'],)] if row else []
            raise AssertionError('Unexpected host database query')

        def exists(self, doctype, name):
            if doctype != 'Cipher Semantic Corpus':
                raise AssertionError('Unexpected native DocType access')
            state.events.append(('exists', doctype, name))
            return name in state.rows

        def commit(self):
            state.events.append(('commit',))
            state.commits += 1
            self.transaction_writes = 0

    db = Database()

    class ProjectionDocument:
        def __init__(self, values, *, new):
            self.__dict__.update(deepcopy(values))
            self._new = new
            self._before = deepcopy(values) if not new else None

        def get(self, key, default=None):
            return getattr(self, key, default)

        def update(self, fields):
            self.__dict__.update(deepcopy(fields))

        def is_new(self):
            return self._new

        def get_doc_before_save(self):
            return SimpleNamespace(**deepcopy(self._before))

        def _persist(self):
            if state.native_mutation:
                state.native_mutation(self)
            self.validate()  # the actual CipherSemanticCorpus controller
            if state.persistence_error:
                raise state.persistence_error
            fields = {key: value for key, value in self.__dict__.items() if not key.startswith('_')}
            state.rows[self.name] = deepcopy(fields)
            db.transaction_writes += 1
            state.events.append(('write', self.name, self.state_version))
            return self

        def insert(self, **kwargs):
            if not self._new or self.name in state.rows:
                raise AssertionError('Unexpected duplicate native insert')
            return self._persist()

        def save(self, **kwargs):
            if self._new or self.name not in state.rows:
                raise AssertionError('Unexpected absent native update')
            return self._persist()

    controller = None

    def get_doc(doctype_or_fields, name=None, **kwargs):
        state.events.append(('get_doc', doctype_or_fields if isinstance(doctype_or_fields, str) else doctype_or_fields['doctype'], name, kwargs))
        if isinstance(doctype_or_fields, dict):
            return controller.CipherSemanticCorpus(doctype_or_fields, new=True)
        if doctype_or_fields != 'Cipher Semantic Corpus':
            raise AssertionError('Unexpected native DocType read')
        return controller.CipherSemanticCorpus(state.rows[name], new=False)

    stubs = {
        'frappe': module('frappe', db=db, get_doc=get_doc, DuplicateEntryError=type('DuplicateEntryError', (Exception,), {})),
        'frappe.model': module('frappe.model', __path__=[]),
        'frappe.model.document': module('frappe.model.document', Document=ProjectionDocument),
        'cipher_aec.governance.context': module('cipher_aec.governance.context', trusted_write=trusted_write,
                                               require_trusted_write=require_trusted_write),
    }
    names = set([STORE_MODULE, TRANSACTIONS_MODULE, CONTROLLER_MODULE, *stubs])
    # Importing a controller also attaches each new package to its parent.
    # Preserve those attributes, including when the package was initially absent.
    for name in list(names):
        parts = name.split('.')
        names.update('.'.join(parts[:end]) for end in range(2, len(parts)))
    missing = object()
    attributes = {}
    for name in names:
        if '.' not in name:
            continue
        parent_name, attribute = name.rsplit('.', 1)
        parent = sys.modules.get(parent_name)
        attributes[name] = (parent, getattr(parent, attribute, missing) if parent else missing)
    saved = {name: sys.modules.pop(name) for name in (STORE_MODULE, TRANSACTIONS_MODULE, CONTROLLER_MODULE) if name in sys.modules}
    try:
        with patch.dict(sys.modules, stubs):
            store = importlib.import_module(STORE_MODULE)
            controller = importlib.import_module(CONTROLLER_MODULE)
            yield state, db, store, controller, trusted_write
    finally:
        for name in (STORE_MODULE, TRANSACTIONS_MODULE, CONTROLLER_MODULE):
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        for name, (original_parent, original_attribute) in attributes.items():
            parent_name, attribute = name.rsplit('.', 1)
            parent = original_parent or sys.modules.get(parent_name)
            if parent is None:
                continue
            if original_attribute is missing:
                if hasattr(parent, attribute):
                    delattr(parent, attribute)
            else:
                setattr(parent, attribute, original_attribute)


class SemanticCheckpointStoreTests(unittest.TestCase):
    def setUp(self):
        self.state, self.db, self.store_module, self.controller, self.trusted_write = self.enterContext(native_projection_fixture())
        self.store = self.store_module.FrappeStore()
        self.key, self.value = checkpoint()

    def successor(self):
        value = deepcopy(self.value)
        value['version'] += 1
        return value

    def native_fields(self, value=None):
        value = value or self.value
        return {'doctype': self.store_module.DOCTYPE, 'name': self.key, 'company': value['scope']['company'],
            'scope_type': value['scope']['scope_type'], 'project': value['scope']['project'],
            'profile_id': value['profile_id'], 'state_version': value['version'],
            'record_digest': digest(value), 'data_json': canonical_json(value)}

    def assert_code(self, code, callback):
        with self.assertRaises(DomainError) as error:
            callback()
        self.assertEqual(error.exception.code, code)
        return error.exception

    def test_absent_load_and_exact_create_update_cas_use_actual_controller(self):
        self.assertIsNone(self.store.load(self.key))
        self.store.save(self.key, 0, self.value)
        self.assertEqual(self.store.load(self.key), self.value)
        next_value = self.successor()
        self.store.save(self.key, 1, next_value)
        self.assertEqual(self.store.load(self.key), next_value)
        self.assertEqual(self.state.rows[self.key]['record_digest'], digest(next_value))
        locks = [event for event in self.state.events if event[0] == 'sql' and 'FOR UPDATE' in event[1]]
        self.assertEqual(len(locks), 2)
        self.assertTrue(any(event[0] == 'get_doc' and event[-1].get('for_update') for event in self.state.events))
        self.assertEqual(self.state.commits, 0)

    def test_stale_create_or_update_cas_preserves_saved_projection(self):
        self.store.save(self.key, 0, self.value)
        before = deepcopy(self.state.rows)
        self.assert_code('semantic_conflict', lambda: self.store.save(self.key, 0, self.value))
        self.assertEqual(self.state.rows, before)
        self.store.save(self.key, 1, self.successor())
        before = deepcopy(self.state.rows)
        self.assert_code('semantic_conflict', lambda: self.store.save(self.key, 1, self.successor()))
        self.assertEqual(self.state.rows, before)
        self.assertEqual(self.state.commits, 0)

    def test_wrong_corpus_key_and_nonincrementing_version_refuse_before_write(self):
        for key, expected, value in [('f' * 64, 0, self.value), (self.key, 1, self.value),
                                     (self.key, 0, self.successor())]:
            with self.subTest(key=key, expected=expected):
                self.assert_code('semantic_integrity', lambda: self.store.save(key, expected, value))
        self.assertFalse(self.state.rows)
        self.assertFalse(any(event[0] == 'write' for event in self.state.events))

    def test_hash_and_every_native_scope_profile_version_projection_drift_refuse_load(self):
        self.store.save(self.key, 0, self.value)
        original = deepcopy(self.state.rows[self.key])
        mutations = {'record_digest': '0' * 64, 'profile_id': 'f' * 64, 'company': 'Other',
                     'project': 'Other', 'scope_type': 'Company', 'state_version': 2, 'name': 'f' * 64}
        for key, value in mutations.items():
            with self.subTest(field=key):
                self.state.rows[self.key] = {**deepcopy(original), key: value}
                self.assert_code('semantic_integrity', lambda: self.store.load(self.key))
        self.state.rows[self.key] = original
        self.assertEqual(self.store.load(self.key), self.value)

    def test_same_version_hash_or_profile_drift_cannot_be_overwritten_by_save(self):
        self.store.save(self.key, 0, self.value)
        original = deepcopy(self.state.rows[self.key])
        for key in ('record_digest', 'profile_id', 'company', 'project'):
            with self.subTest(field=key):
                self.state.rows[self.key] = {**deepcopy(original), key: 'drifted'}
                before = deepcopy(self.state.rows)
                self.assert_code('semantic_integrity', lambda: self.store.save(self.key, 1, self.successor()))
                self.assertEqual(self.state.rows, before)
        self.assertEqual(self.state.commits, 0)

    def test_forged_checkpoint_profile_and_plaintext_fields_fail_closed_validation(self):
        for mutate in (lambda value: value.update(excerpt='private source'),
                       lambda value: value['profile']['embedding'].update(dimensions=99),
                       lambda value: value.update(active_generation=str(uuid4()))):
            value = deepcopy(self.value)
            mutate(value)
            with self.subTest(value=value):
                self.assert_code('semantic_integrity', lambda: self.store.save(self.key, 0, value))
        self.assertFalse(self.state.rows)

    def test_malformed_persisted_json_is_safe_and_unchanged(self):
        self.state.rows[self.key] = {**self.native_fields(), 'data_json': '{private-token-and-source'}
        before = deepcopy(self.state.rows)
        error = self.assert_code('semantic_integrity', lambda: self.store.load(self.key))
        self.assertNotIn('private-token', error.message)
        self.assertEqual(self.state.rows, before)

    def test_direct_native_insert_and_update_require_both_trust_and_exact_private_plan(self):
        document = self.controller.CipherSemanticCorpus(self.native_fields(), new=True)
        self.assert_code('governed_write_required', document.validate)
        with self.trusted_write():
            self.assert_code('semantic_command_required', document.validate)
        self.store.save(self.key, 0, self.value)
        document = self.controller.CipherSemanticCorpus(self.native_fields(self.successor()), new=False)
        document._before = deepcopy(self.state.rows[self.key])
        with self.trusted_write():
            self.assert_code('semantic_command_required', document.validate)
        self.assertEqual(self.store.load(self.key), self.value)

    def test_controller_refuses_native_projection_change_even_with_valid_service_plan(self):
        for mutate in (lambda doc: setattr(doc, 'company', 'Other'),
                       lambda doc: setattr(doc, 'profile_id', 'f' * 64),
                       lambda doc: setattr(doc, 'record_digest', '0' * 64),
                       lambda doc: setattr(doc, 'state_version', 99)):
            self.state.native_mutation = mutate
            with self.subTest(mutate=mutate):
                self.assert_code('semantic_integrity', lambda: self.store.save(self.key, 0, self.value))
                self.assertFalse(self.state.rows)
                self.assertIsNone(self.store_module._plan.get())
        self.state.native_mutation = None
        self.store.save(self.key, 0, self.value)

    def test_controller_delete_rename_and_generic_native_access_stay_closed(self):
        document = self.controller.CipherSemanticCorpus(self.native_fields(), new=True)
        self.assert_code('semantic_command_required', document.on_trash)
        self.assert_code('semantic_command_required', lambda: document.before_rename('old', 'new'))
        self.assertFalse(self.store_module.deny_native_access(document, user='reader'))
        self.assertEqual(self.store_module.no_native_rows(user='reader'), '1=0')

    def test_read_committed_is_checked_for_each_load_and_save_without_changing_isolation(self):
        self.store.save(self.key, 0, self.value)
        self.state.isolation = [['REPEATABLE-READ']]
        self.assert_code('semantic_unavailable', lambda: self.store.load(self.key))
        self.assert_code('semantic_unavailable', lambda: self.store.save(self.key, 1, self.successor()))
        self.assertEqual(self.state.rows[self.key]['state_version'], 1)
        self.assertEqual(self.state.commits, 0)
        self.assertFalse(any(event[0] == 'sql' and event[1].startswith('SET ') for event in self.state.events))

    def test_unknown_unavailable_and_malformed_isolation_are_safe_refusals(self):
        for result in (None, [], {}, ['READ-COMMITTED'], [['READ-COMMITTED', 'extra']],
                       [['SERIALIZABLE']], [['REPEATABLE READ']], [[None]]):
            self.state.isolation = result
            with self.subTest(result=result):
                error = self.assert_code('semantic_unavailable', lambda: self.store.load(self.key))
                self.assertEqual(error.status, 503)
                self.assert_code('semantic_unavailable', lambda: self.store.save(self.key, 0, self.value))
        self.state.isolation_error = RuntimeError('private database endpoint and credentials')
        error = self.assert_code('semantic_unavailable', lambda: self.store.load(self.key))
        self.assertNotIn('private', error.message)
        self.assertFalse(self.state.rows)

    def test_read_committed_normalizations_are_accepted(self):
        for isolation in ('READ-COMMITTED', 'read committed', 'READ_COMMITTED'):
            self.state.isolation = [[isolation]]
            with self.subTest(isolation=isolation):
                self.assertIsNone(self.store.load(self.key))

    def test_default_request_store_never_commits_a_callers_transaction(self):
        self.db.transaction_writes = 3
        self.store.save(self.key, 0, self.value)
        self.store.save(self.key, 1, self.successor())
        self.assertEqual(self.db.transaction_writes, 5)
        self.assertEqual(self.state.commits, 0)
        self.assertFalse(self.store.durable)

    def test_durable_store_refuses_counter_only_admission_without_owned_worker_context(self):
        self.assert_code('semantic_worker_required', lambda: self.store_module.FrappeStore(durable=True))
        for writes in (0, 1, None, '0'):
            self.db.transaction_writes = writes
            with self.subTest(writes=writes):
                # This legacy projection fixture has no native job, actual local
                # DB, physical connection or callback managers. A zero counter
                # cannot establish ownership. Full worker lifecycle/recovery is
                # exercised by the separate actual-transaction host regression.
                self.assert_code('semantic_worker_required', lambda: self.store_module.dedicated_worker().__enter__())
                self.assert_code('semantic_worker_required', lambda: self.store_module.dedicated_worker(entry='rebuild').__enter__())
                self.assert_code('semantic_worker_required', lambda: self.store_module.FrappeStore(durable=True))
                self.assertEqual(self.db.transaction_writes, writes)
        self.assertEqual(self.state.commits, 0)
        self.assertFalse(self.state.rows)

    def test_unavailable_transaction_counter_cannot_establish_worker_admission(self):
        # The class default is also removed in this explicit unsupported DB.
        with patch.object(type(self.db), 'transaction_writes', None):
            self.assert_code('semantic_worker_required', lambda: self.store_module.dedicated_worker().__enter__())
            self.assert_code('semantic_worker_required', lambda: self.store_module.FrappeStore(durable=True))
        self.assertEqual(self.state.commits, 0)

    def test_private_plan_and_trust_are_released_after_persistence_failure(self):
        self.state.persistence_error = RuntimeError('Host insert failed')
        with self.assertRaises(RuntimeError):
            self.store.save(self.key, 0, self.value)
        self.assertIsNone(self.store_module._plan.get())
        self.assertFalse(self.state.rows)
        document = self.controller.CipherSemanticCorpus(self.native_fields(), new=True)
        self.assert_code('governed_write_required', document.validate)
        self.state.persistence_error = None
        self.store.save(self.key, 0, self.value)
        self.assertEqual(self.store.load(self.key), self.value)
        self.assertEqual(self.state.commits, 0)


    def test_first_insert_duplicate_is_safe_conflict_without_request_commit(self):
        duplicate = self.store_module.frappe.DuplicateEntryError('private SQL endpoint')
        self.state.persistence_error = duplicate
        error = self.assert_code('semantic_conflict', lambda: self.store.save(self.key, 0, self.value))
        self.assertEqual(error.status, 409)
        self.assertNotIn('private', error.message)
        self.assertIsNone(error.__cause__)
        self.assertIsNone(self.store_module._plan.get())
        self.assertEqual(self.state.commits, 0)
        self.assertFalse(self.state.rows)

    def test_duplicate_during_update_remains_original_persistence_fault(self):
        self.store.save(self.key, 0, self.value)
        duplicate = self.store_module.frappe.DuplicateEntryError('update failure')
        self.state.persistence_error = duplicate
        with self.assertRaises(self.store_module.frappe.DuplicateEntryError) as error:
            self.store.save(self.key, 1, self.successor())
        self.assertIs(error.exception, duplicate)
        self.assertEqual(self.store.load(self.key), self.value)
        self.assertEqual(self.state.commits, 0)
        self.assertIsNone(self.store_module._plan.get())


if __name__ == '__main__':
    unittest.main()
