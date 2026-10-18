"""Exclusive, initially unopened Frappe worker transaction leases.

No request may enter this boundary. It never repairs or rolls back a caller's
transaction. A normal worker return is safe only after its owned transaction
has been fully rolled back; completed explicit checkpoint commits survive.
"""
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
import re

import frappe
from cipher_aec.api.errors import DomainError

_owner = ContextVar('semantic_transaction_owner', default=None)
_CALLBACKS = ('before_commit', 'after_commit', 'before_rollback', 'after_rollback')
_CONTROLS = {'commit', 'rollback', 'start', 'begin', 'savepoint', 'release',
             'set', 'alter', 'create', 'drop', 'truncate', 'rename', 'lock', 'unlock'}
_ORDINARY = {'select', 'show', 'describe', 'desc', 'explain', 'insert', 'update',
             'delete', 'replace', 'with'}
_MISSING = object()


class UnsafeWorkerTransaction(RuntimeError):
    """An owned rollback/close failed; never convert this to a blocked return."""


def _refuse():
    return DomainError('semantic_worker_required',
                       'Start semantic work in a fresh dedicated worker transaction.', 409)


def _db():
    local = getattr(frappe, 'local', None)
    return getattr(local, 'db', None) if local is not None else None


def _proxy_db():
    proxy = getattr(frappe, 'db', None)
    resolve = getattr(proxy, '_get_current_object', None)
    return resolve() if callable(resolve) else proxy


def _queues(db):
    result = {}
    for name in _CALLBACKS:
        manager = getattr(db, name, None)
        functions = getattr(manager, '_functions', None)
        if (not isinstance(functions, deque)
                or not all(callable(getattr(manager, method, None)) for method in ('add', 'run', 'reset'))):
            raise _refuse()
        result[name] = tuple(functions)
    return result


def _zero(value):
    return type(value) is int and value == 0


def _read_committed(db):
    try:
        rows = db.sql('SELECT @@session.tx_isolation')
    except Exception:
        raise DomainError('semantic_unavailable',
                          'Current database read isolation cannot be verified.', 503) from None
    if (not isinstance(rows, (list, tuple)) or len(rows) != 1
            or not isinstance(rows[0], (list, tuple)) or len(rows[0]) != 1
            or str(rows[0][0]).upper().replace('_', '-').replace(' ', '-') != 'READ-COMMITTED'):
        raise DomainError('semantic_unavailable',
                          'Semantic work requires current committed database reads.', 503)


def require_worker(*, clean=False):
    owner = _owner.get()
    if owner is None:
        raise _refuse()
    owner.check(clean=clean)
    return owner


def require_clean_worker():
    return require_worker(clean=True)


def _head(text):
    """Reject batch/hidden control SQL without rejecting quoted document text."""
    i, length = 0, len(text)
    while i < length:
        char = text[i]
        if char in "'\"`":
            quote = char
            i += 1
            while i < length:
                if text[i] == '\\':
                    i += 2
                elif text[i] == quote:
                    if i + 1 < length and text[i + 1] == quote:
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    i += 1
            else:
                raise _refuse()
        elif text.startswith('/*', i):
            if text.startswith(('/*!', '/*M!', '/*m!'), i):
                raise _refuse()
            end = text.find('*/', i + 2)
            if end == -1:
                raise _refuse()
            i = end + 2
        elif char == '#' or (text.startswith('--', i)
                              and (i + 2 == length or text[i + 2].isspace())):
            end = text.find('\n', i)
            i = length if end == -1 else end + 1
        elif char == ';':
            raise _refuse()
        else:
            i += 1
    return re.sub(r'\A(?:\s+|--[^\n]*(?:\n|$)|\#[^\n]*(?:\n|$)|/\*[\s\S]*?\*/)*', '', text)


class _Owner:
    def __init__(self, entry):
        local = getattr(frappe, 'local', None)
        if local is None:
            raise _refuse()
        db = _db()
        job = getattr(local, 'job', None)
        site = getattr(local, 'site', None)
        if (_owner.get() is not None or entry not in ('rebuild', 'reconcile')
                or getattr(local, 'request', None) is not None
                or not isinstance(site, str) or not site
                or job is None or getattr(job, 'site', None) != site
                or getattr(job, 'method', None) != 'cipher_aec.semantic_index.worker.' + entry
                or db is None or _proxy_db() is not db
                or getattr(db, '_conn', _MISSING) is not None
                or getattr(db, 'last_query', None) is not None
                or getattr(db, '_cipher_semantic_worker_used', False)
                or not _zero(getattr(db, 'transaction_writes', None))
                or not _zero(getattr(db, 'auto_commit_on_many_writes', None))
                or not _zero(getattr(db, '_disable_transaction_control', None))
                or any(_queues(db).values())):
            raise _refuse()
        methods = ('sql', 'commit', 'rollback', 'begin', 'savepoint', 'release_savepoint', 'close')
        self.original = {name: getattr(db, name, None) for name in methods}
        if not callable(getattr(db, 'connect', None)) or not all(map(callable, self.original.values())):
            raise _refuse()
        self.previous = {name: vars(db).get(name, _MISSING) for name in methods}
        self.db, self.job, self.site = db, job, site
        self.method = job.method
        self.managers = {name: getattr(db, name) for name in _CALLBACKS}
        self.connection = None
        self.valid = False
        self.failure = None
        self.aborted = False
        self.unsafe = False
        self.installed = False
        self.control = None
        self.expected_sql = []
        self.epoch = None
        self.before_commit = lambda: self._before('checkpoint')
        self.before_rollback = lambda: self._before('abort')

    def _bound(self):
        return (_db() is self.db and _proxy_db() is self.db and self.db._conn is self.connection
                and getattr(frappe.local, 'job', None) is self.job
                and getattr(self.job, 'site', None) == self.site
                and getattr(self.job, 'method', None) == self.method
                and getattr(frappe.local, 'site', None) == self.site
                and getattr(frappe.local, 'request', None) is None)

    def _lost(self):
        self.valid = False
        raise _refuse()

    def _before(self, expected):
        self.valid = False  # every physical transaction boundary spends its lease
        if self.control != expected or not self._bound():
            raise _refuse()

    def _callback_identity(self):
        if any(getattr(self.db, n) is not self.managers[n] for n in _CALLBACKS):
            self._lost()

    def _callbacks(self, *, native_write=False):
        self._callback_identity()
        queues = _queues(self.db)
        if (queues['before_commit'] != (self.before_commit,)
                or queues['before_rollback'] != (self.before_rollback,)):
            self._lost()
        # Native Document.save registers cache invalidation after commit/rollback.
        # Only this exact lexical checkpoint write may acquire those callbacks.
        if not native_write and queues != self.expected_callbacks:
            self._lost()

    def check(self, *, clean=False, native_write=False):
        if self.failure is not None:
            raise self.failure
        if not self.valid or not self._bound() or self.control is not None:
            self._lost()
        if (not _zero(self.db._disable_transaction_control)
                or not _zero(self.db.auto_commit_on_many_writes)
                or type(self.db.transaction_writes) is not int
                or self.db.transaction_writes < 0
                or (clean and self.db.transaction_writes != 0)):
            self._lost()
        self._callbacks(native_write=native_write)

    def _sql(self, query, *args, **kwargs):
        text = str(query)
        # Match Frappe's string query boundary, including leading SQL comments.
        try:
            head = _head(text)
        except DomainError:
            self._lost()
        identifier = re.match(r'[A-Za-z_]+', head)
        word = identifier.group().lower() if identifier else ''
        if word in _CONTROLS:
            normalized = ' '.join(head.lower().rstrip(';').split())
            if (not self.control or not self.expected_sql
                    or normalized != self.expected_sql[0] or not self._bound()):
                self._lost()
            self.expected_sql.pop(0)
        elif word not in _ORDINARY or not self.valid or not self._bound():
            # Rollback/commit callbacks may not write or open another snapshot.
            self._lost()
        return self.original['sql'](query, *args, **kwargs)

    def _begin(self, *args, **kwargs):
        if not self.control or not self.expected_sql or self.expected_sql[0] != 'start transaction':
            self._lost()
        return self.original['begin'](*args, **kwargs)

    def _foreign_control(self, *args, **kwargs):
        self._lost()

    def open(self):
        # Mark the wrapper spent even if its fresh physical connection refuses RC.
        self.db._cipher_semantic_worker_used = True
        try:
            self.db.connect()
        finally:
            self.connection = self.db._conn
        if self.connection is None or not _zero(self.db.transaction_writes) or any(_queues(self.db).values()):
            raise _refuse()
        _read_committed(self.db)  # verify; never SET session/server isolation
        self.original['begin']()  # caller DB was proven unopened before ownership
        self._callback_identity()
        self.db.sql = self._sql
        self.db.begin = self._begin
        for name in ('commit', 'rollback', 'savepoint', 'release_savepoint', 'close'):
            setattr(self.db, name, self._foreign_control)
        self.installed = True
        self._arm()

    def _arm(self):
        if (not self._bound() or not _zero(self.db.transaction_writes)
                or not _zero(self.db._disable_transaction_control)
                or not _zero(self.db.auto_commit_on_many_writes)
                or any(_queues(self.db).values())):
            raise _refuse()
        self.db.before_commit.add(self.before_commit)
        self.db.before_rollback.add(self.before_rollback)
        self.expected_callbacks = _queues(self.db)
        self.epoch = object()
        self.valid = True
        _read_committed(self.db)

    def commit_checkpoint(self):
        self.check(native_write=True)
        _read_committed(self.db)
        self.control = 'checkpoint'
        self.expected_sql = ['commit', 'start transaction']
        try:
            self.original['commit']()
            if self.expected_sql or not self._bound():
                self._lost()
        finally:
            self.control = None
            self.expected_sql = []
        self._arm()  # only a successful owned checkpoint may renew the epoch

    def abort(self, error=None):
        if self.unsafe:
            raise UnsafeWorkerTransaction('Semantic worker connection must be discarded.')
        if self.aborted:
            return
        self.failure = error
        self.valid = False
        try:
            if (self.connection is None or not self._bound()
                    or not _zero(self.db._disable_transaction_control)):
                raise UnsafeWorkerTransaction('Semantic worker rollback ownership cannot be verified.')
            self._callback_identity()  # never run an unknown replacement manager
            self.control = 'abort'
            self.expected_sql = ['rollback', 'start transaction'] if self.installed else []
            self.original['rollback']()  # full rollback clears pending commit callbacks
            if self.expected_sql or not _zero(self.db.transaction_writes) or any(_queues(self.db).values()):
                raise UnsafeWorkerTransaction('Semantic worker rollback did not finish cleanly.')
            self.aborted = True
        except BaseException:
            self.unsafe = True
            # A failed rollback is not a safe blocked result. Closing only the
            # exact owned physical connection prevents later ordinary-return commit.
            if self.connection is not None:
                try:
                    if self.db._conn is self.connection:
                        self.original['close']()
                    else:
                        self.connection.close()
                except BaseException:
                    pass
            for manager in self.managers.values():
                try:
                    manager.reset()
                except BaseException:
                    pass
            raise UnsafeWorkerTransaction('Semantic worker rollback failed; discard this connection.') from None
        finally:
            self.control = None
            self.expected_sql = []

    def finish(self):
        if not self.aborted:
            self.check(clean=True)
            _read_committed(self.db)
            self.abort()  # release owned read locks; final framework commit is empty

    def release(self):
        self.valid = False
        cleanup_failed = False
        if self.installed:
            for name, previous in self.previous.items():
                try:
                    if previous is _MISSING:
                        delattr(self.db, name)
                    else:
                        setattr(self.db, name, previous)
                except BaseException:
                    cleanup_failed = True
        # Never close a replacement connection that another caller installed.
        if self.connection is not None and self.db._conn is self.connection:
            try:
                self.original['close']()
            except BaseException:
                cleanup_failed = True
        if cleanup_failed and not self.unsafe:
            raise UnsafeWorkerTransaction('Semantic worker cleanup failed; discard this context.')


@contextmanager
def dedicated_worker(*, entry=None):
    owner = _Owner(entry)  # all caller refusals happen before ownership/mutation
    token = _owner.set(owner)
    try:
        try:
            owner.open()
            yield owner
            owner.finish()
        except BaseException as error:
            if owner.connection is not None and not owner.aborted and not owner.unsafe:
                owner.abort(error)
            raise
    finally:
        try:
            owner.release()
        finally:
            _owner.reset(token)


@contextmanager
def worker_user(user):
    """Restore the exact worker session and locals touched by Frappe.set_user."""
    require_clean_worker()
    local, session = frappe.local, frappe.session
    local_names = ('cache', 'form_dict', 'jenv_restricted', 'jenv_unrestricted',
                   'role_permissions', 'new_doc_templates', 'user_perms')
    saved = {name: getattr(local, name, _MISSING) for name in local_names}
    session_saved = {name: getattr(session, name, _MISSING) for name in ('user', 'sid', 'data')}
    try:
        frappe.set_user(user)
        yield
    finally:
        for target, values in ((local, saved), (session, session_saved)):
            for name, value in values.items():
                if value is _MISSING:
                    if hasattr(target, name):
                        delattr(target, name)
                else:
                    setattr(target, name, value)
