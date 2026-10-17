"""External, standard-library host regression evidence for semantic worker ownership.

Frappe is not imported or run. The callback queue and transaction-control methods,
plus execute_job, are AST-extracted from the captured native sources. SQL and native
persistence are explicit pending/committed host projections. Cipher worker, store,
controller and service are actual modules. No provider or connected qualification.

CIPHER_SEMANTIC_SOURCE_ROOT may name a checkout root (default: sibling workspace).
Captured reference files prefer sibling native_reference/{database.py,
background_jobs.py,utils.py}; the original cloud capture paths are fallbacks.
"""
from __future__ import annotations

import ast
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import importlib
import os
import re
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Callable
import unittest
from unittest.mock import patch
from uuid import uuid4
import warnings

ROOT = Path(__file__).resolve().parent
WORKTREE = Path(os.environ.get('CIPHER_SEMANTIC_SOURCE_ROOT', str(ROOT / 'workspace'))).resolve()
APP = WORKTREE / 'apps/cipher/platform/apps/cipher_aec'
sys.path.insert(0, str(APP))
from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.semantic_index.service import SemanticService
from cipher_aec.tests.test_semantic_index_service import ACTOR, SELECTOR, SCOPE, fixture

def reference(name, fallback):
    bundled = ROOT / 'native_reference' / name
    return bundled if bundled.is_file() else Path(fallback)


DATABASE_SOURCE = reference('database.py', '/tmp/cipher-company-proposals-r14/native-controller-review/database.py')
JOBS_SOURCE = reference('background_jobs.py', '/tmp/cipher-ai04-stage-a/pinned-runtime-source/background_jobs.py')
CALLBACK_SOURCE = reference('utils.py', ROOT / 'frappe-utils-reference.py')
STORE = 'cipher_aec.semantic_index.store'
WORKER = 'cipher_aec.semantic_index.worker'
TRANSACTIONS = 'cipher_aec.semantic_index.transactions'
CONTROLLER = 'cipher_aec.cipher_semantic_index.doctype.cipher_semantic_corpus.cipher_semantic_corpus'


def extract(path, names, namespace, *, parent=None):
    tree = ast.parse(path.read_text())
    body = tree.body
    if parent:
        body = next(node for node in body if isinstance(node, ast.ClassDef) and node.name == parent).body
    selected = [node for node in body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    if {node.name for node in selected} != set(names):
        raise AssertionError('Native reference source no longer contains the requested definitions')
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)
    return {name: namespace[name] for name in names}


CallbackManager = extract(CALLBACK_SOURCE, ['CallbackManager'], {'deque': deque, 'Callable': Callable})['CallbackManager']


class AttrDict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


class HostFrappe(ModuleType):
    def __getattr__(self, name):
        if name in ('db', 'session', 'flags', 'job', 'form_dict'):
            return getattr(self.local, name)
        raise AttributeError(name)


@contextmanager
def host(*, active=False, entry='rebuild', text=None):
    backend, memory, source, embedder, index = fixture(text)
    operation = str(uuid4())
    backend.prepare(SCOPE, [SELECTOR], operation, ACTOR)
    if active:
        backend.run(SCOPE, operation, ACTOR)
        embedder.calls.clear(); index.upserts.clear()
    key, value = next(iter(memory.rows.items()))
    h = SimpleNamespace(events=[], committed={}, pending={}, savepoints={}, operation=operation,
                        key=key, value=deepcopy(value), source=source, embedder=embedder, index=index,
                        fault_after_write=None, fault_commit=None, factory_calls=0, probe=None,
                        callback_effects=[], connections=[], set_users=[], now=100.0, rollback_callback_fault=None, before_lock=None)
    trusted = ContextVar('host_semantic_trusted', default=False)

    @contextmanager
    def trusted_write():
        token = trusted.set(True)
        try:
            yield
        finally:
            trusted.reset(token)

    def require_trusted_write():
        if not trusted.get():
            raise DomainError('governed_write_required', 'Use the governed command.', 403)

    f = HostFrappe('frappe')
    f._dict = AttrDict
    f.local = SimpleNamespace(site='semantic-host.invalid', flags=AttrDict(read_only=False),
        session=AttrDict(user='queue@example.test', sid='original-session', data=AttrDict(token='original')),
        cache={'original': True}, form_dict=AttrDict(original=True), jenv_restricted=object(),
        jenv_unrestricted=object(), role_permissions={'original': True},
        new_doc_templates={'original': True}, user_perms={'original': True})
    f.conf = AttrDict(cipher_semantic_index={'enabled': False})
    f.get_hooks = lambda name: []
    f.call = lambda method, **kwargs: method(**kwargs)
    f.RetryBackgroundJobError = type('RetryBackgroundJobError', (Exception,), {})
    f.log_error = lambda **kwargs: h.events.append(('log_error',))
    f.monitor = SimpleNamespace(add_data_to_monitor=lambda **kwargs: None)
    f.get_traceback = lambda: 'host exception'

    def set_user(username):
        h.set_users.append(username)
        f.local.session.user = username
        f.local.session.sid = username
        f.local.session.data = AttrDict()
        f.local.cache = {}
        f.local.form_dict = AttrDict()
        f.local.jenv_restricted = None
        f.local.jenv_unrestricted = None
        f.local.role_permissions = {}
        f.local.new_doc_templates = {}
        f.local.user_perms = None

    f.set_user = set_user

    class Connection:
        def __init__(self):
            self.closed = False

        def cursor(self):
            return SimpleNamespace()

        def close(self):
            h.events.append(('physical_close', self))
            if self.closed:
                raise RuntimeError('Host connection was closed twice')
            self.closed = True
            h.pending.clear()
            h.savepoints.clear()

    class Database:
        InternalError = type('InternalError', (Exception,), {})
        db_type = 'mariadb'

        def __init__(self):
            self._conn = None
            self._cursor = None
            self.transaction_writes = 0
            self._disable_transaction_control = 0
            self.auto_commit_on_many_writes = 0
            self.last_query = None
            self.value_cache = {}
            self.before_commit = CallbackManager()
            self.after_commit = CallbackManager()
            self.before_rollback = CallbackManager()
            self.after_rollback = CallbackManager()
            self.isolation = 'READ-COMMITTED'

        def connect(self):
            h.events.append(('connect', self))
            self._conn = Connection()
            self._cursor = self._conn.cursor()
            h.connections.append(self._conn)

        def sql(self, query, values=(), **kwargs):
            if not self._conn:
                self.connect()
            text = str(query).strip()
            # Model MariaDB comment syntax so an unfenced control query really
            # reaches its transaction effect on the vulnerable baseline.
            executable = re.sub(r'/\*(?:![0-9]*|[mM]![0-9]*)\s*([\s\S]*?)\*/', r'\1', text)
            executable = re.sub(r'/\*[\s\S]*?\*/', ' ', executable)
            folded = ' '.join(executable.lower().rstrip(';').split())
            h.events.append(('sql', text, values))
            self.last_query = text
            literals = {"SELECT ';'": ';', "SELECT '/*! COMMIT */;'": '/*! COMMIT */;',
                        "SELECT 'it''s; still literal'": "it's; still literal",
                        'SELECT "double;quoted"': 'double;quoted'}
            if text in literals:
                return [(literals[text],)]
            if (folded in ('select 1; commit', 'select 1 commit')
                    or folded.startswith(('call ', 'execute ', 'analyze ', 'xa '))):
                # This host records that an administrative/procedural/batch
                # statement escaped the worker fence; it executes no procedure.
                h.events.append(('unfenced_statement', text))
                return []
            if folded in ('select @@session.tx_isolation', 'select @@session.transaction_isolation'):
                return [(self.isolation,)]
            if folded.startswith('start transaction'):
                # MariaDB START TRANSACTION can commit foreign pending work.
                h.committed.update(deepcopy(h.pending)); h.pending.clear()
                h.savepoints.clear(); self.transaction_writes = 0
                return []
            if folded in ('commit', 'commit and chain'):
                if h.fault_commit:
                    fault, h.fault_commit = h.fault_commit, None
                    raise fault
                h.committed.update(deepcopy(h.pending)); h.pending.clear()
                h.savepoints.clear(); self.transaction_writes = 0
                return []
            if folded in ('rollback', 'rollback and chain'):
                h.pending.clear(); h.savepoints.clear(); self.transaction_writes = 0
                return []
            if folded.startswith('savepoint '):
                h.savepoints[text.split()[-1]] = deepcopy(h.pending)
                return []
            if folded.startswith('rollback to savepoint '):
                h.pending = deepcopy(h.savepoints[text.split()[-1]])
                self.transaction_writes = 0
                return []
            if folded.startswith('release savepoint '):
                h.savepoints.pop(text.split()[-1], None)
                return []
            if folded.startswith('select state_version from `tabcipher semantic corpus`'):
                if h.before_lock:
                    callback, h.before_lock = h.before_lock, None
                    callback()
                row = h.pending.get(values[0], h.committed.get(values[0]))
                return [(row['state_version'],)] if row else []
            if folded.startswith('insert into host_caller'):
                h.pending['host-caller'] = {'payload': 'must never be semantic-committed'}
                self.transaction_writes += 1
                return []
            if folded == 'select 1':
                return [(1,)]
            raise AssertionError('Unexpected host SQL: ' + text)

        def exists(self, doctype, name):
            if doctype != 'Cipher Semantic Corpus':
                raise AssertionError('Unexpected DocType')
            self.sql('SELECT 1')
            return name in h.pending or name in h.committed

        def is_deadlocked(self, error):
            return False

        def is_timedout(self, error):
            return False

    native = extract(DATABASE_SOURCE, ['begin', 'commit', 'rollback', 'savepoint', 'release_savepoint', 'close'],
                     {'frappe': f, 'warnings': warnings, 'TRANSACTION_DISABLED_MSG': 'disabled'}, parent='Database')
    for name, method in native.items():
        setattr(Database, name, method)
    f.local.db = db = Database()
    h.db = db
    h.frappe = f
    h.Database = Database
    h.native = native
    f.local.job = AttrDict(site=f.local.site, method='cipher_aec.semantic_index.worker.' + entry,
                          job_name='host-test', kwargs={}, user=ACTOR.user, after_job=CallbackManager())

    class NativeDocument:
        def __init__(self, fields, *, new):
            self.__dict__.update(deepcopy(fields))
            self._new = new
            self._before = deepcopy(fields) if not new else None
            self.flags = AttrDict()

        def get(self, name, default=None):
            return getattr(self, name, default)

        def update(self, fields):
            self.__dict__.update(deepcopy(fields))

        def is_new(self):
            return self._new

        def get_doc_before_save(self):
            return AttrDict(deepcopy(self._before))

        def persist(self):
            self.validate()
            fields = {name: deepcopy(value) for name, value in self.__dict__.items()
                      if not name.startswith('_') and name != 'flags'}
            h.pending[self.name] = fields
            f.db.transaction_writes += 1
            h.events.append(('native_write', self.name, self.state_version))
            # Native cache invalidation registers callbacks on both outcomes.
            f.db.after_commit.add(lambda: h.callback_effects.append('commit-cache'))
            def after_rollback():
                h.callback_effects.append('rollback-cache')
                if h.rollback_callback_fault:
                    raise h.rollback_callback_fault
            f.db.after_rollback.add(after_rollback)
            if h.fault_after_write:
                fault, h.fault_after_write = h.fault_after_write, None
                raise fault
            return self

        def save(self, **kwargs):
            return self.persist()

        def insert(self, **kwargs):
            if self.name in h.pending or self.name in h.committed:
                raise AssertionError('Unexpected duplicate insert')
            return self.persist()

    controller = None

    def get_doc(doctype, name=None, **kwargs):
        if isinstance(doctype, dict):
            return controller.CipherSemanticCorpus(doctype, new=True)
        if doctype != 'Cipher Semantic Corpus':
            raise AssertionError('Unexpected DocType')
        fields = h.pending.get(name, h.committed.get(name))
        return controller.CipherSemanticCorpus(fields, new=False)

    f.get_doc = get_doc
    h.native_fields = lambda value: {'doctype': 'Cipher Semantic Corpus', 'name': key,
        'company': value['scope']['company'], 'project': value['scope']['project'],
        'scope_type': value['scope']['scope_type'], 'state_version': value['version'],
        'profile_id': value['profile_id'], 'record_digest': digest(value), 'data_json': canonical_json(value)}
    h.committed[key] = h.native_fields(value)

    def current_actor():
        h.events.append(('actor',))
        return ACTOR

    def require_effects_enabled():
        h.events.append(('effects_guard',))

    def service(*, durable=False):
        h.factory_calls += 1
        store = store_module.FrappeStore(durable=durable)
        actual = SemanticService(store, source, embedder, index, clock=lambda: h.now)
        h.actual = actual
        if h.probe:
            return SimpleNamespace(run=lambda *args, **kwargs: h.probe(actual),
                                   reconcile=lambda *args, **kwargs: h.probe(actual))
        return actual

    context = ModuleType('cipher_aec.governance.context')
    context.__dict__.update(trusted_write=trusted_write, require_trusted_write=require_trusted_write,
        current_actor=current_actor, require_effects_enabled=require_effects_enabled)
    configuration = importlib.import_module('cipher_aec.semantic_index.configuration')
    model = ModuleType('frappe.model'); model.__path__ = []
    document = ModuleType('frappe.model.document'); document.Document = NativeDocument
    stubs = {'frappe': f, 'frappe.model': model, 'frappe.model.document': document,
             'cipher_aec.governance.context': context}
    all_names = set([STORE, WORKER, TRANSACTIONS, CONTROLLER, *stubs])
    for name in list(all_names):
        parts = name.split('.')
        all_names.update('.'.join(parts[:n]) for n in range(2, len(parts)))
    missing = object()
    attributes = {}
    for name in all_names:
        if '.' in name:
            parent_name, attribute = name.rsplit('.', 1)
            parent = sys.modules.get(parent_name)
            attributes[name] = (parent, getattr(parent, attribute, missing) if parent else missing)
    saved = {name: sys.modules.pop(name) for name in (STORE, WORKER, TRANSACTIONS, CONTROLLER) if name in sys.modules}
    try:
        with patch.dict(sys.modules, stubs), patch.object(configuration, 'service', service):
            store_module = importlib.import_module(STORE)
            controller = importlib.import_module(CONTROLLER)
            worker = importlib.import_module(WORKER)
            h.store = store_module
            h.worker = worker
            h.trusted = trusted
            f.get_attr = lambda name: getattr(worker, name.rsplit('.', 1)[1])
            execute = extract(JOBS_SOURCE, ['execute_job'], {'frappe': f, 'CallbackManager': CallbackManager})['execute_job']
            h.call = lambda: (worker.rebuild(SCOPE, operation, ACTOR.user) if entry == 'rebuild'
                              else worker.reconcile(SCOPE, ACTOR.user))
            kwargs = {'scope': SCOPE, 'requested_user': ACTOR.user}
            if entry == 'rebuild':
                kwargs['operation_id'] = operation
            h.execute = lambda: execute(site=f.local.site, method='cipher_aec.semantic_index.worker.' + entry,
                event=None, job_name='host-test', kwargs=kwargs, user=ACTOR.user, is_async=False)
            h.context_names = ('session', 'cache', 'form_dict', 'jenv_restricted', 'jenv_unrestricted',
                               'role_permissions', 'new_doc_templates', 'user_perms')
            h.original_context = {name: getattr(f.local, name) for name in h.context_names}
            h.original_session = deepcopy(f.local.session)
            yield h
    finally:
        for name in (STORE, WORKER, TRANSACTIONS, CONTROLLER):
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        for name, (original_parent, original_attribute) in attributes.items():
            parent_name, attribute = name.rsplit('.', 1)
            parent = original_parent or sys.modules.get(parent_name)
            if parent is not None:
                if original_attribute is missing:
                    if hasattr(parent, attribute):
                        delattr(parent, attribute)
                else:
                    setattr(parent, attribute, original_attribute)


class WorkerTransactionHostTests(unittest.TestCase):
    def assert_restored(self, h):
        self.assertIs(h.frappe.local.session, h.original_context['session'])
        self.assertEqual(h.frappe.session, h.original_session)
        for name, original in h.original_context.items():
            self.assertIs(getattr(h.frappe.local, name), original, name)
        self.assertIsNone(h.store._plan.get())
        with self.assertRaises(DomainError) as released:
            h.store.FrappeStore(durable=True)
        self.assertEqual(released.exception.code, 'semantic_worker_required')
        self.assertFalse(h.trusted.get())

    def assert_blocked(self, result, code=None):
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse(result['connected_qualification'])
        if code:
            self.assertEqual(result['error_code'], code)

    def assert_owned_refusal(self, h, *, execute=False):
        try:
            result = h.execute() if execute else h.call()
        except RuntimeError as error:
            self.assertEqual(type(error).__name__, 'UnsafeWorkerTransaction')
        else:
            self.assert_blocked(result, 'semantic_worker_required')

    def test_native_fault_after_write_cannot_be_committed_by_execute_job_normal_return(self):
        for entry in ('rebuild', 'reconcile'):
            for location in ('document', 'commit'):
                with self.subTest(entry=entry, location=location), host(active=entry == 'reconcile', entry=entry) as h:
                    if entry == 'reconcile':
                        h.source.revoked = True
                    before = deepcopy(h.committed)
                    fault = DomainError('semantic_unavailable', 'host native failure', 503)
                    if location == 'document':
                        h.fault_after_write = fault
                    else:
                        h.fault_commit = fault
                    result = h.execute()
                    self.assert_blocked(result)
                    self.assertEqual(h.committed, before, 'Frappe normal-return commit persisted a failed checkpoint')
                    self.assertFalse(h.pending)
                    self.assertTrue(any(e[0] == 'native_write' for e in h.events))
                    self.assertFalse(h.embedder.calls)
                    self.assertFalse(h.index.deletes)
                    # Actual execute_job always emits its ordinary-return commit.
                    self.assertTrue(any(e[:2] == ('sql', 'commit and chain') for e in h.events))
                    self.assert_restored(h)

    def test_admission_preserves_every_foreign_caller_without_set_user_or_transaction_control(self):
        cases = ('dirty', 'callback', 'savepoint', 'read_connected', 'request', 'disabled', 'wrong_method', 'wrong_site', 'shadow_db')
        for entry in ('rebuild', 'reconcile'):
            for case in cases:
                with self.subTest(entry=entry, case=case), host(entry=entry) as h:
                    if case == 'dirty':
                        h.db.sql('INSERT INTO host_caller VALUES (1)')
                    elif case == 'callback':
                        h.db.before_commit.add(lambda: h.callback_effects.append('foreign'))
                    elif case == 'savepoint':
                        h.db.savepoint('caller_savepoint')
                    elif case == 'read_connected':
                        h.db.sql('SELECT 1')
                    elif case == 'request':
                        h.frappe.local.request = object()
                    elif case == 'disabled':
                        h.db._disable_transaction_control = 1
                    elif case == 'wrong_method':
                        h.frappe.local.job.method = 'other.worker.method'
                    elif case == 'wrong_site':
                        h.frappe.local.job.site = 'other-site.invalid'
                    elif case == 'shadow_db':
                        h.frappe.db = h.Database()
                    before = (deepcopy(h.committed), deepcopy(h.pending), deepcopy(h.savepoints),
                              h.db.transaction_writes, list(h.events), list(h.db.before_commit._functions))
                    with self.assertRaises(DomainError) as refusal:
                        h.call()
                    self.assertEqual(refusal.exception.code, 'semantic_worker_required')
                    self.assertEqual((h.committed, h.pending, h.savepoints, h.db.transaction_writes,
                                      h.events, list(h.db.before_commit._functions)), before)
                    self.assertEqual(h.set_users, [], 'Denied caller context was changed before admission')
                    self.assertEqual(h.factory_calls, 0)
                    self.assertFalse(h.callback_effects)
                    self.assert_restored(h)

    def test_empty_callback_manager_with_missing_api_refuses_before_opening_or_set_user(self):
        for callback in ('before_commit', 'after_commit', 'before_rollback', 'after_rollback'):
            for missing in ('add', 'run', 'reset'):
                with self.subTest(callback=callback, missing=missing), host() as h:
                    calls = []
                    manager = SimpleNamespace(_functions=deque())
                    for method in ('add', 'run', 'reset'):
                        if method != missing:
                            setattr(manager, method, lambda *args, method=method: calls.append(method))
                    setattr(h.db, callback, manager)
                    h.probe = lambda actual: {'status': 'unsafe-admission'}
                    before = deepcopy(h.committed)
                    with self.assertRaises(DomainError) as refusal:
                        h.call()
                    self.assertEqual(refusal.exception.code, 'semantic_worker_required')
                    self.assertIs(getattr(h.db, callback), manager)
                    self.assertFalse(calls)
                    self.assertFalse(h.events)
                    self.assertFalse(h.set_users)
                    self.assertEqual(h.factory_calls, 0)
                    self.assertIsNone(h.db._conn)
                    self.assertEqual(h.committed, before)
                    self.assert_restored(h)

    def test_commented_raw_transaction_controls_never_reach_native_sql(self):
        queries = ('COMMIT/* host */', 'ROLLBACK/* host */', '/*! COMMIT */',
                   '/*!100000 COMMIT */', '/*M!100000 COMMIT */', '/*m! ROLLBACK */',
                   '/* ordinary leading comment */ COMMIT', 'CALL host_procedure()',
                   'EXECUTE host_statement', 'ANALYZE TABLE host_table', 'XA START host_branch',
                   'SELECT 1; COMMIT', 'SELECT 1/*! COMMIT */')
        for query in queries:
            with self.subTest(query=query), host() as h:
                before = deepcopy(h.committed)
                successor = deepcopy(h.value); successor['version'] += 1
                def probe(actual):
                    h.db.sql(query)
                    actual.store.save(h.key, h.value['version'], successor)
                    return {'status': 'unsafe-control'}
                h.probe = probe
                self.assert_owned_refusal(h)
                self.assertFalse(any(e[0] == 'sql' and e[1] == query for e in h.events))
                self.assertFalse(any(e[0] == 'native_write' for e in h.events))
                self.assertEqual(h.committed, before)
                self.assertFalse(h.pending)
                self.assert_restored(h)

    def test_quoted_semicolons_and_comment_text_allow_actual_rebuild_journey(self):
        with host(text='Retained specification; concrete strength is 4000 psi.') as h:
            queries = {"SELECT ';'": ';', "SELECT '/*! COMMIT */;'": '/*! COMMIT */;',
                       "SELECT 'it''s; still literal'": "it's; still literal",
                       'SELECT "double;quoted"': 'double;quoted'}
            def probe(actual):
                for query, expected in queries.items():
                    self.assertEqual(h.db.sql(query), [(expected,)])
                return actual.run(SCOPE, h.operation, ACTOR)
            h.probe = probe
            self.assertEqual(h.execute()['status'], 'active')
            self.assertEqual(h.embedder.calls[0], [h.source.text])
            self.assertIn(';', h.source.text)
            for query in queries:
                self.assertTrue(any(e[0] == 'sql' and e[1] == query for e in h.events))
            checkpoint = __import__('json').loads(h.committed[h.key]['data_json'])
            self.assertEqual(checkpoint['jobs'][h.operation]['status'], 'active')
            self.assertFalse(h.pending)
            self.assert_restored(h)

    def test_replaced_callback_manager_never_runs_unknown_replacement_cleanup(self):
        for callback in ('before_commit', 'after_commit', 'before_rollback', 'after_rollback'):
            with self.subTest(callback=callback), host() as h:
                calls = []
                replacement = SimpleNamespace(_functions=deque())
                for method in ('add', 'run', 'reset'):
                    setattr(replacement, method, lambda *args, method=method: calls.append(method))
                before = deepcopy(h.committed)
                def probe(actual):
                    h.db.sql('INSERT INTO host_caller VALUES (1)')
                    setattr(h.db, callback, replacement)
                    actual.store.load(h.key)
                    return {'status': 'unsafe-replacement'}
                h.probe = probe
                with self.assertRaises(RuntimeError) as refusal:
                    h.call()
                self.assertEqual(type(refusal.exception).__name__, 'UnsafeWorkerTransaction')
                self.assertFalse(calls, 'Unknown callback manager was invoked during cleanup')
                self.assertEqual(h.committed, before)
                self.assertFalse(h.pending)
                owned_connection = h.connections[0]
                self.assertEqual(sum(e[0] == 'physical_close' and e[1] is owned_connection for e in h.events), 1)
                self.assert_restored(h)

    def test_callback_reset_failure_preserves_unsafe_and_cleans_other_original_managers(self):
        for broken in ('before_commit', 'after_commit'):
            with self.subTest(broken=broken), host() as h:
                resets = []
                class ControlledCallbacks(CallbackManager):
                    def __init__(self, name):
                        super().__init__()
                        self.name = name
                        self.fail = False

                    def reset(self):
                        resets.append(self.name)
                        if self.fail:
                            raise RuntimeError('Host original manager reset failed')
                        super().reset()

                managers = {name: ControlledCallbacks(name) for name in
                            ('before_commit', 'after_commit', 'before_rollback', 'after_rollback')}
                for name, manager in managers.items():
                    setattr(h.db, name, manager)
                before = deepcopy(h.committed)
                def probe(actual):
                    h.db.sql('INSERT INTO host_caller VALUES (1)')
                    managers[broken].fail = True
                    raise DomainError('semantic_unavailable', 'host owned failure', 503)
                h.probe = probe
                with self.assertRaises(RuntimeError) as refusal:
                    h.call()
                self.assertEqual(type(refusal.exception).__name__, 'UnsafeWorkerTransaction')
                self.assertTrue(set(managers).issubset(resets), 'One reset failure prevented later original-manager cleanup')
                self.assertEqual(h.committed, before)
                self.assertFalse(h.pending)
                owned_connection = h.connections[0]
                self.assertEqual(sum(e[0] == 'physical_close' and e[1] is owned_connection for e in h.events), 1)
                self.assertIsNone(h.db._conn)
                self.assert_restored(h)

    def test_repeatable_read_refuses_before_plaintext_or_provider_effects(self):
        for entry in ('rebuild', 'reconcile'):
            with self.subTest(entry=entry), host(entry=entry) as h:
                h.db.isolation = 'REPEATABLE-READ'
                before = deepcopy(h.committed)
                with self.assertRaises(DomainError) as refusal:
                    h.call()
                self.assertEqual(refusal.exception.code, 'semantic_unavailable')
                self.assertEqual(h.committed, before)
                self.assertFalse(any(e[0] == 'native_write' for e in h.events))
                self.assertFalse(h.embedder.calls)
                self.assertFalse(h.index.upserts)
                self.assertFalse(h.index.deletes)
                self.assertFalse(any(e[0] == 'sql' and e[1].lower().startswith('set ') for e in h.events))
                self.assert_restored(h)

    def test_external_transaction_job_or_connection_replacement_cannot_reuse_store(self):
        for case in ('commit', 'rollback', 'savepoint', 'raw_savepoint', 'second_job', 'job_method', 'job_site', 'proxy', 'connection', 'database'):
            with self.subTest(case=case), host() as h:
                before = deepcopy(h.committed)
                successor = deepcopy(h.value); successor['version'] += 1
                def probe(actual):
                    if case == 'commit':
                        h.db.commit()
                    elif case == 'rollback':
                        h.db.rollback()
                    elif case == 'savepoint':
                        h.db.savepoint('foreign')
                    elif case == 'raw_savepoint':
                        h.db.sql('savepoint foreign')
                    elif case == 'second_job':
                        h.frappe.local.job = AttrDict(h.frappe.local.job)
                    elif case == 'job_method':
                        h.frappe.local.job.method = 'other.worker.method'
                    elif case == 'job_site':
                        h.frappe.local.job.site = 'other-site.invalid'
                    elif case == 'proxy':
                        h.frappe.db = h.Database()
                    elif case == 'connection':
                        h.db._conn = type(h.db._conn)()
                    elif case == 'database':
                        h.frappe.local.db = h.Database()
                    actual.store.load(h.key)
                    actual.store.save(h.key, h.value['version'], successor)
                    return {'status': 'unsafe-stale-owner'}
                h.probe = probe
                self.assert_owned_refusal(h)
                self.assertEqual(h.committed, before)
                self.assertFalse(any(e[0] == 'native_write' for e in h.events))
                self.assert_restored(h)

    def test_callback_or_dirty_write_added_before_owned_save_is_never_committed(self):
        for case in ('write', 'callback', 'disabled'):
            with self.subTest(case=case), host() as h:
                before = deepcopy(h.committed)
                successor = deepcopy(h.value); successor['version'] += 1
                def probe(actual):
                    if case == 'write':
                        h.db.sql('INSERT INTO host_caller VALUES (1)')
                    elif case == 'callback':
                        h.db.after_commit.add(lambda: h.callback_effects.append('foreign'))
                    else:
                        h.db._disable_transaction_control = 1
                    actual.store.save(h.key, h.value['version'], successor)
                    return {'status': 'unsafe-contaminated-save'}
                h.probe = probe
                self.assert_owned_refusal(h)
                self.assertEqual(h.committed, before)
                self.assertNotIn('foreign', h.callback_effects)
                self.assertFalse(any(e[0] == 'native_write' for e in h.events))
                self.assertFalse(h.pending)
                self.assert_restored(h)

    def test_failed_progress_save_aborts_before_service_recovery_and_replays_same_ids(self):
        for location in ('document', 'commit'):
            with self.subTest(location=location), host() as h:
                def fail_next_checkpoint():
                    fault = DomainError('semantic_unavailable', 'host progress failure', 503)
                    if location == 'document':
                        h.fault_after_write = fault
                    else:
                        h.fault_commit = fault
                h.index.after_upsert = fail_next_checkpoint
                self.assert_blocked(h.execute(), 'semantic_unavailable')
                retained = __import__('json').loads(h.committed[h.key]['data_json'])
                job = retained['jobs'][h.operation]
                self.assertEqual(retained['version'], h.value['version'] + 1)
                self.assertEqual(job['status'], 'running')
                self.assertEqual(job['next_chunk'], 0)
                self.assertEqual(sum(e[0] == 'native_write' for e in h.events), 2,
                                 'Service recovery attempted a checkpoint after native save failure')
                self.assertFalse(h.pending)
                first_ids = [point['id'] for point in h.index.upserts[0]]
                self.assert_restored(h)
                h.index.after_upsert = None
                h.now += 121
                h.frappe.local.db = h.db = h.Database()
                self.assertEqual(h.execute()['status'], 'active')
                self.assertEqual(first_ids, [point['id'] for point in h.index.upserts[1]])
                self.assertEqual(len(h.index.points), 1)
                self.assert_restored(h)

    def test_cas_conflict_retains_winner_and_resumes_same_operation_and_point_ids(self):
        with host() as h:
            winner = {}
            def race_after_upsert():
                def win_cas():
                    value = __import__('json').loads(h.committed[h.key]['data_json'])
                    value['version'] += 1
                    h.committed[h.key] = h.native_fields(value)
                    winner.update(deepcopy(h.committed))
                    h.events.append(('concurrent_cas', value['version']))
                h.before_lock = win_cas
            h.index.after_upsert = race_after_upsert
            self.assert_blocked(h.execute(), 'semantic_conflict')
            self.assertEqual(h.committed, winner, 'Recovery replaced a winning CAS checkpoint')
            self.assertEqual(sum(e[0] == 'native_write' for e in h.events), 1)
            self.assertFalse(h.pending)
            first_ids = [point['id'] for point in h.index.upserts[0]]
            self.assert_restored(h)
            h.index.after_upsert = None
            h.now += 121
            h.frappe.local.db = h.db = h.Database()
            self.assertEqual(h.execute()['status'], 'active')
            self.assertEqual(first_ids, [point['id'] for point in h.index.upserts[1]])
            self.assert_restored(h)

    def test_failing_native_rollback_callback_cannot_leave_partial_work_for_outer_commit(self):
        with host() as h:
            before = deepcopy(h.committed)
            h.fault_after_write = DomainError('semantic_unavailable', 'host persistence failure', 503)
            h.rollback_callback_fault = RuntimeError('host cache rollback callback failed')
            with self.assertRaises(RuntimeError) as refusal:
                h.execute()
            self.assertEqual(type(refusal.exception).__name__, 'UnsafeWorkerTransaction')
            self.assertEqual(h.committed, before)
            self.assertFalse(h.pending)
            self.assertTrue(any(e[0] == 'physical_close' for e in h.events))
            self.assert_restored(h)

    def test_successful_actual_rebuild_has_multiple_committed_checkpoints_and_restores_context(self):
        with host() as h:
            self.assertEqual(h.execute()['status'], 'active')
            checkpoint = __import__('json').loads(h.committed[h.key]['data_json'])
            self.assertEqual(checkpoint['jobs'][h.operation]['status'], 'active')
            self.assertGreaterEqual(checkpoint['version'], h.value['version'] + 3)
            self.assertEqual(len(h.index.points), 1)
            self.assertGreaterEqual(h.callback_effects.count('commit-cache'), 3)
            self.assertFalse(h.pending)
            self.assert_restored(h)

    def test_prior_job_store_cannot_borrow_new_job_ownership_or_abort_its_transaction(self):
        with host() as h:
            self.assertEqual(h.execute()['status'], 'active')
            previous_store = h.actual.store
            self.assert_restored(h)
            before_events, before_users = list(h.events), list(h.set_users)
            h.frappe.local.job = AttrDict(h.frappe.local.job)
            with self.assertRaises(DomainError) as refusal:
                h.call()
            self.assertEqual(refusal.exception.code, 'semantic_worker_required')
            self.assertEqual(h.events, before_events)
            self.assertEqual(h.set_users, before_users)
            h.frappe.local.db = h.db = h.Database()
            def probe(actual):
                current = actual.store.load(h.key)
                successor = deepcopy(current); successor['version'] += 1
                for attempt in (lambda: previous_store.load(h.key),
                                lambda: previous_store.save(h.key, current['version'], successor)):
                    with self.assertRaises(DomainError) as refusal:
                        attempt()
                    self.assertEqual(refusal.exception.code, 'semantic_worker_required')
                # Refusing a stale store must preserve the new job's own lease.
                self.assertEqual(actual.store.load(h.key), current)
                return {'status': 'new-job-preserved'}
            h.probe = probe
            self.assertEqual(h.execute()['status'], 'new-job-preserved')
            self.assert_restored(h)

    def test_provider_failure_retains_only_committed_progress_and_retries_same_point_ids(self):
        with host() as h:
            h.index.unknown = True
            self.assert_blocked(h.execute(), 'semantic_unavailable')
            first_ids = [point['id'] for point in h.index.upserts[0]]
            checkpoint = __import__('json').loads(h.committed[h.key]['data_json'])
            self.assertEqual(checkpoint['jobs'][h.operation]['status'], 'retryable')
            self.assert_restored(h)
            # A later job has a separate unopened wrapper; no queue/runtime is used.
            h.frappe.local.db = h.db = h.Database()
            self.assertEqual(h.execute()['status'], 'active')
            self.assertEqual(first_ids, [point['id'] for point in h.index.upserts[1]])
            self.assertEqual(len(h.index.points), 1)
            self.assert_restored(h)


if __name__ == '__main__':
    unittest.main(verbosity=2)
