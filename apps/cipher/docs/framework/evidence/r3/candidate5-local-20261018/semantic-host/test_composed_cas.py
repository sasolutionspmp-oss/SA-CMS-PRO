"""Actual Cipher composition with captured Frappe lifecycle host projections.

This is not actual native or provider qualification. Before-insert is an explicit
host race schedule; SQL rows, connectors and providers remain host projections.
"""
from copy import deepcopy
import unittest
import test_worker_transactions_host as projection
host = projection.host


class ComposedCASHostTests(unittest.TestCase):
    assert_restored = projection.WorkerTransactionHostTests.assert_restored
    assert_blocked = projection.WorkerTransactionHostTests.assert_blocked

    def assert_rollback_before_outer_return_commit(self, h):
        controls = [event[1] for event in h.events if event[0] == 'sql'
                    and event[1] in ('rollback', 'rollback and chain', 'commit and chain')]
        self.assertIn('rollback', controls)
        self.assertIn('commit and chain', controls)
        self.assertLess(controls.index('rollback'), controls.index('commit and chain'))

    def test_first_insert_race_returns_safe_conflict_preserves_winner_and_empty_outer_commit(self):
        for entry in ('rebuild', 'reconcile'):
            with self.subTest(entry=entry), host(entry=entry) as h:
                h.committed.clear()
                winner = deepcopy(h.native_fields(h.value))
                def insert_winner(doc):
                    h.committed[h.key] = deepcopy(winner)
                    h.events.append(('independent_insert_winner',))
                h.before_insert = insert_winner
                h.probe = lambda actual: actual.store.save(h.key, 0, h.value)
                self.assert_blocked(h.execute(), 'semantic_conflict')
                self.assertEqual(h.committed, {h.key: winner})
                self.assertFalse(h.pending)
                self.assertFalse(h.callback_effects)
                self.assertFalse(h.embedder.calls)
                self.assertFalse(h.index.upserts)
                self.assertFalse(any(event[0] == 'native_write' for event in h.events))
                self.assert_rollback_before_outer_return_commit(h)
                self.assert_restored(h)

    def test_duplicate_after_partial_insert_aborts_native_rows_and_commit_callbacks(self):
        for entry in ('rebuild', 'reconcile'):
            with self.subTest(entry=entry), host(entry=entry) as h:
                h.committed.clear()
                h.fault_after_write = h.frappe.DuplicateEntryError('private partial insert')
                h.probe = lambda actual: actual.store.save(h.key, 0, h.value)
                self.assert_blocked(h.execute(), 'semantic_conflict')
                self.assertEqual(h.committed, {})
                self.assertFalse(h.pending)
                self.assertEqual(h.callback_effects, ['rollback-cache'])
                self.assertTrue(any(event[0] == 'native_write' for event in h.events))
                self.assert_rollback_before_outer_return_commit(h)
                self.assert_restored(h)

    def test_update_duplicate_is_original_error_and_owned_partial_update_is_aborted(self):
        for entry in ('rebuild', 'reconcile'):
            with self.subTest(entry=entry), host(entry=entry) as h:
                before = deepcopy(h.committed)
                fault = h.frappe.DuplicateEntryError('private update fault')
                h.fault_after_write = fault
                successor = deepcopy(h.value); successor['version'] += 1
                h.probe = lambda actual: actual.store.save(h.key, h.value['version'], successor)
                with self.assertRaises(h.frappe.DuplicateEntryError) as error:
                    h.execute()
                self.assertIs(error.exception, fault)
                self.assertEqual(h.committed, before)
                self.assertFalse(h.pending)
                self.assertNotIn('commit-cache', h.callback_effects)
                self.assertIn('rollback-cache', h.callback_effects)
                self.assert_restored(h)

    def test_request_duplicate_preserves_existing_caller_rows_callbacks_and_identity(self):
        with host() as h:
            h.committed.clear()
            h.db.sql('INSERT INTO host_caller VALUES (1)')
            callback = lambda: h.callback_effects.append('foreign-callback')
            h.db.after_commit.add(callback)
            h.frappe.local.request = object()
            before = (deepcopy(h.pending), h.db.transaction_writes, list(h.events),
                      tuple(h.db.after_commit._functions), h.frappe.session.user)
            def insert_winner(doc):
                h.committed[h.key] = deepcopy(h.native_fields(h.value))
            h.before_insert = insert_winner
            with self.assertRaises(Exception) as error:
                h.store.FrappeStore().save(h.key, 0, h.value)
            self.assertEqual(getattr(error.exception, 'code', None), 'semantic_conflict')
            self.assertEqual((h.pending, h.db.transaction_writes,
                              tuple(h.db.after_commit._functions), h.frappe.session.user),
                             (before[0], before[1], before[3], before[4]))
            self.assertEqual(h.set_users, [])
            self.assertFalse(h.callback_effects)
            new_events = h.events[len(before[2]):]
            self.assertFalse(any(event[0] == 'physical_close' for event in new_events))
            self.assertFalse(any(event[0] == 'sql' and event[1].lower().startswith(
                ('commit', 'rollback', 'start transaction')) for event in new_events))
            self.assertIsNone(h.store._plan.get())
            self.assertFalse(h.trusted.get())

    def test_insert_conflict_with_failed_rollback_cannot_return_safe_blocked(self):
        for entry in ('rebuild', 'reconcile'):
            with self.subTest(entry=entry), host(entry=entry) as h:
                h.committed.clear()
                h.fault_after_write = h.frappe.DuplicateEntryError('private partial insert')
                h.rollback_callback_fault = RuntimeError('rollback callback failed')
                h.probe = lambda actual: actual.store.save(h.key, 0, h.value)
                with self.assertRaises(RuntimeError) as error:
                    h.execute()
                self.assertEqual(type(error.exception).__name__, 'UnsafeWorkerTransaction')
                self.assertFalse(h.committed)
                self.assertFalse(h.pending)
                self.assertNotIn('commit-cache', h.callback_effects)
                self.assertTrue(any(event[0] == 'physical_close' for event in h.events))
                self.assert_restored(h)


if __name__ == '__main__':
    unittest.main(verbosity=2)
