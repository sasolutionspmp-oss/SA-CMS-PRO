"""Local integrity checks for the independent opt-in acceptance artifacts."""
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from cipher_aec.tests import test_award_composed_acceptance as driver
from cipher_aec.tests import test_award_prerequisites as prerequisites


class AwardAcceptanceArtifacts(unittest.TestCase):
    def test_replaced_release_identity_refuses_before_recovery_effect(self):
        original = {'runtime_epoch': 'original-disabled', 'source_manifest_sha256': 'a' * 64, 'source_files': 3}
        intent = {'source_before': original, 'fixture_id': 'original-fixture'}
        effects = []
        for current, fixture_id in (({**original, 'runtime_epoch': 'replacement-epoch'}, 'original-fixture'),
                                    ({**original, 'source_manifest_sha256': 'b' * 64}, 'original-fixture'),
                                    (original, 'replacement-fixture')):
            with self.subTest(current=current, fixture_id=fixture_id), self.assertRaises(RuntimeError):
                prerequisites.require_original_release(current, intent, fixture_id=fixture_id)
                effects.append('must not reach native continuation')
        self.assertEqual(effects, [])
        prerequisites.require_original_release(original, intent, fixture_id='original-fixture')

    def test_interrupted_prerequisite_retries_original_uuid_and_body(self):
        with tempfile.TemporaryDirectory() as directory:
            attempts = []
            def unknown(method, values, **kwargs):
                attempts.append((method, values.copy())); raise TimeoutError('Unknown original outcome')
            rpc = SimpleNamespace(role='author', invoke=unknown)
            journal = prerequisites.PrerequisiteRPC(rpc, directory)
            with self.assertRaises(TimeoutError):
                journal.command('original', 'registered.command', {'company': 'Owned'})
            def readback(method, values, **kwargs):
                attempts.append((method, values.copy())); return {'saved': 'one-original-effect'}
            rpc.invoke = readback
            resumed = prerequisites.PrerequisiteRPC(rpc, directory)
            self.assertEqual(resumed.command('original', 'registered.command', {'company': 'Owned'}), {'saved': 'one-original-effect'})
            self.assertEqual(attempts[0], attempts[1])
            with self.assertRaises(RuntimeError):
                resumed.command('original', 'registered.command', {'company': 'Retargeted'})
            self.assertEqual(len(attempts), 2)

    def test_authored_manual_prerequisite_uses_real_calculator_exact15_and_unfunded5(self):
        from cipher_aec.tests.test_estimating_core import fixture, identity
        from cipher_aec.estimating.calculation import calculate
        inputs = fixture()
        units = {'count': identity('each'), 'labor_time': identity('lh'), 'equipment_time': identity('eh')}
        next(row for row in inputs['unit_manifest']['records'] if row['id'] == units['count'])['fields']['precision'] = 6
        rates = {}
        for kind, dimension, amount in (('material', 'count', '1.25'), ('labor', 'labor_time', '2.00'), ('equipment', 'equipment_time', '3.00')):
            row = inputs['rates'][identity('rate-' + kind)]; row.update(unit_id=units[dimension], rate_amount=amount)
            rates[kind] = row
        ids = {name: identity('award-prereq-' + name) for name in ('material-component', 'labor-component', 'equipment-component', 'assembly-line', 'extra-line', 'alternative-line', 'indirect', 'contingency')}
        assembly = next(iter(inputs['assemblies'].values()))
        assembly.update(basis_unit_id=units['count'], components=prerequisites.manual_assembly_components(ids, units, rates))
        inputs['lines'], inputs['adjustments'] = prerequisites.manual_calculation_lines(ids, units, rates['material']['id'], assembly['id'])
        result = calculate(inputs)
        self.assertEqual({name: result[name]['amount'] for name in ('direct', 'indirect', 'contingency', 'total')},
                         {'direct': '13.25', 'indirect': '1.33', 'contingency': '0.42', 'total': '15.00'})
        alternative = next(row for row in result['lines'] if not row['included'])
        self.assertEqual(alternative['extension']['amount'], '5.00')

    def test_product_residue_fails_before_harness_rollback_can_erase_it(self):
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.execute('CREATE TABLE projects (name TEXT PRIMARY KEY)'); connection.commit()
        def inventory():
            rows = connection.execute('SELECT name FROM projects ORDER BY name').fetchall()
            return {'company': 'Owned', 'absent_tables': [], 'tables': {
                'Project': {'records': {row[0]: driver._hash(row) for row in rows}}}}
        before = inventory()
        connection.execute("INSERT INTO projects VALUES ('retained-native-allocation')")
        with self.assertRaisesRegex(AssertionError, 'before fixture cleanup'):
            driver.assert_product_rollback(before, inventory)
        # The assertion itself must not perform the rollback that it measures.
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM projects').fetchone()[0], 1)
        connection.rollback()
        self.assertTrue(driver.assert_product_rollback(before, inventory)[1]['unchanged'])

    def test_callback_prefix_comparison_cannot_accept_overloaded_equality(self):
        class EqualCallback:
            def __eq__(self, other):
                return True
        original, replacement = EqualCallback(), EqualCallback()
        self.assertEqual((original,), (replacement,))
        self.assertFalse(driver._identical_sequence((replacement,), (original,)))
        self.assertTrue(driver._identical_sequence((original,), (original,)))

    def test_inventory_keeps_changed_old_rows_separate_from_new_fixture_rows(self):
        before = {'company': 'Owned', 'absent_tables': [], 'tables': {
            'Account': {'records': {'old': 'before'}}, 'Project': {'records': {}}}}
        after = {'company': 'Owned', 'absent_tables': [], 'tables': {
            'Account': {'records': {'old': 'tree-delta', 'new-company': 'new'}},
            'Project': {'records': {'partial': 'allocation-residue'}}}}
        result = driver.compare_award_inventory(before, after)
        self.assertFalse(result['unchanged'])
        self.assertEqual(result['delta']['Account'], {'inserted': ['new-company'], 'deleted': [], 'changed': ['old']})
        self.assertEqual(result['delta']['Project']['inserted'], ['partial'])
        with self.assertRaises(AssertionError):
            driver.compare_award_inventory(before, {**after, 'absent_tables': ['Version']})

    def test_artifact_and_directory_creation_cannot_replace_original_unknown_intent(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = driver._work(Path(temporary) / 'original')
            intent = {'operation_id': 'original', 'state': 'unknown'}
            target = work / 'intent.json'; driver._save(target, intent)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                driver._save(target, {'operation_id': 'replacement'})
            with self.assertRaises(FileExistsError):
                driver._work(work)
            self.assertEqual(json.loads(target.read_text()), intent)

    def test_release_refuses_source_drift_and_repository_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'owned.py'; source.write_text('original')
            release = root / 'release.json'
            value = {'schema': 'cipher.award.acceptance-release.v1', 'runtime_epoch': 'explicit-unexecuted-fixture',
                     'source_sha256': {'owned.py': driver.hashlib.sha256(b'original').hexdigest()}}
            release.write_text(json.dumps(value))
            self.assertEqual(driver._source_binding(root, release)['source_files'], 1)
            source.write_text('changed')
            with self.assertRaises(RuntimeError):
                driver._source_binding(root, release)
            value['source_sha256'] = {'../unrelated.py': '0' * 64}; release.write_text(json.dumps(value))
            with self.assertRaises(RuntimeError):
                driver._source_binding(root, release)


if __name__ == '__main__':
    unittest.main()
