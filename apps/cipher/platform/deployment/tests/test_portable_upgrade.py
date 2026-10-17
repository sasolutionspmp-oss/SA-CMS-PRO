"""Host failure/recovery proofs. No Docker daemon or native database is used."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


local = load('local_upgrade_tests', HERE / 'cipher-local.py')
upgrade = load('upgrade_tests', HERE / 'portable-upgrade.py')
native = load('native_upgrade_tests', HERE / 'portable-upgrade-site.py')
runtime = load('runtime_upgrade_tests', HERE / 'run-portable-services.py')
OLD, NEW = 'a' * 64, 'b' * 64
OLD_IMAGE = {'id': 'sha256:' + '1' * 64, 'build_id': OLD, 'revision': 'c' * 40}
NEW_IMAGE = {'id': 'sha256:' + '2' * 64, 'build_id': NEW, 'revision': 'd' * 40}


class NativeOfflineBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bench = Path(self.temp.name)
        self.site = self.bench / 'sites/cipher.localhost'
        self.site.mkdir(parents=True)
        self.marker = self.site / '.cipher-portable.json'
        self.marker.write_text(json.dumps({'schema': 1, 'build_id': OLD, 'site': native.SITE}))
        (self.site / 'site_config.json').write_text(json.dumps({'cipher_site_mode': 'synthetic', 'cipher_synthetic': True, 'private_secret': 'retained'}))
        (self.bench / 'sites/common_site_config.json').write_text('{}')
        self.identity = 'e' * 32
        self.env = patch.dict(native.os.environ, CIPHER_SYNTHETIC='1', CIPHER_SITE=native.SITE, CIPHER_BUILD_ID=NEW)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root = patch.object(native, 'BENCH', self.bench)
        self.root.start()
        self.addCleanup(self.root.stop)
        native.perform('prepare', self.identity, OLD, NEW)

    def call(self, action):
        return native.perform(action, self.identity, OLD, NEW)

    def test_failed_native_migration_preserves_old_marker_and_hold(self):
        before = self.marker.read_bytes()
        with patch.object(native, 'bench', side_effect=RuntimeError('interrupted migration')):
            with self.assertRaises(RuntimeError):
                self.call('migrate')
        self.assertEqual(before, self.marker.read_bytes())
        self.assertTrue((self.site / '.cipher-portable-upgrade.json').exists())

    def test_failed_real_schema_readback_never_publishes_marker(self):
        before = self.marker.read_bytes()
        with patch.object(native, 'bench', side_effect=['["frappe","erpnext","cipher_aec"]', '{"schema":"cipher.task-controls.metadata.v1","ready":false}']):
            with self.assertRaises(ValueError):
                self.call('publish')
        self.assertEqual(before, self.marker.read_bytes())

    def test_publish_rechecks_contracts_and_release_is_interrupt_resumable(self):
        good = {'installed_apps': ['frappe', 'erpnext', 'cipher_aec'], 'task_metadata': {'ready': True}}
        with patch.object(native, 'contracts', return_value=good) as contracts:
            self.call('publish')
            self.assertEqual(json.loads(self.marker.read_text())['build_id'], NEW)
            self.assertTrue((self.site / '.cipher-portable-upgrade.json').exists())
            self.call('release')
            self.call('release')
            self.assertEqual(contracts.call_count, 3)
        self.assertFalse((self.site / '.cipher-portable-upgrade.json').exists())

    def test_incomplete_fresh_backup_cannot_fall_back_to_older_complete_set(self):
        backup = self.site / 'private/backups'
        backup.mkdir(parents=True)
        for suffix in native.SUFFIXES:
            (backup / ('20261017_120000-cipher_localhost-' + suffix)).write_bytes(b'old')
        def run(*args, **kwargs):
            (backup / '20261017_120001-cipher_localhost-site_config_backup.json').write_bytes(b'incomplete')
        with patch.dict(native.os.environ, CIPHER_BUILD_ID=OLD), patch.object(native.time, 'sleep'), patch.object(native.subprocess, 'run', side_effect=run):
            with self.assertRaises(ValueError):
                self.call('backup')
        self.assertFalse((self.site / ('.cipher-upgrade-backup-' + self.identity + '.json')).exists())

    def test_backup_resume_reuses_verified_original_bytes_without_native_backup(self):
        backup = self.site / 'private/backups'
        backup.mkdir(parents=True)
        names = ['20261017_120000-cipher_localhost-' + suffix for suffix in native.SUFFIXES]
        for name in names:
            (backup / name).write_bytes(b'original')
        result = {'prefix': '20261017_120000-cipher_localhost', 'build_id': OLD,
                  'sha256': {name: hashlib.sha256(b'original').hexdigest() for name in names}}
        (self.site / ('.cipher-upgrade-backup-' + self.identity + '.json')).write_text(json.dumps(result))
        with patch.dict(native.os.environ, CIPHER_BUILD_ID=OLD), patch.object(native.subprocess, 'run') as run:
            self.assertEqual(self.call('backup'), result)
            run.assert_not_called()

    def test_interrupted_backup_receipt_reconciles_complete_exact_invocation_without_rerun(self):
        backup = self.site / 'private/backups'
        backup.mkdir(parents=True)
        def run(*args, **kwargs):
            for suffix in native.SUFFIXES:
                (backup / ('20261017_120001-cipher_localhost-' + suffix)).write_bytes(b'saved')
        original_atomic = native.atomic
        def interrupted(path, value):
            if path.name.startswith('.cipher-upgrade-backup-') and not path.name.startswith('.cipher-upgrade-backup-intent-'):
                raise RuntimeError('receipt publication interrupted')
            original_atomic(path, value)
        with patch.dict(native.os.environ, CIPHER_BUILD_ID=OLD), patch.object(native.time, 'sleep'), patch.object(native.subprocess, 'run', side_effect=run), patch.object(native, 'atomic', side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.call('backup')
        with patch.dict(native.os.environ, CIPHER_BUILD_ID=OLD), patch.object(native.subprocess, 'run') as run:
            self.assertEqual(self.call('backup')['prefix'], '20261017_120001-cipher_localhost')
            run.assert_not_called()

    def test_unresolved_backup_intent_never_invokes_another_backup(self):
        (self.site / 'private/backups').mkdir(parents=True)
        (self.site / ('.cipher-upgrade-backup-intent-' + self.identity + '.json')).write_text('{"before":[]}')
        with patch.dict(native.os.environ, CIPHER_BUILD_ID=OLD), patch.object(native.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                self.call('backup')
            run.assert_not_called()

    def test_both_old_and_candidate_serving_are_blocked_while_pending(self):
        for build in (OLD, NEW):
            with patch.object(runtime, 'MARKER', self.marker), patch.dict(runtime.os.environ, CIPHER_BUILD_ID=build), patch.object(runtime, 'run') as run:
                with self.assertRaises(RuntimeError):
                    runtime.initialize()
                run.assert_not_called()


class HostUpgradeBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.here = patch.object(local, 'HERE', self.root)
        self.here.start()
        self.addCleanup(self.here.stop)
        (self.root / 'portable-upgrade-site.py').write_text('host helper')
        (self.root / 'portable-recovery.py').write_text('recovery helper')
        (self.root / 'compose.portable.yml').write_text('fixed integration compose')
        with patch('builtins.print'):
            local.initialize('integration')
        self.candidate = {'schema': 'cipher.local-candidate.v1', 'profile': 'integration', 'reference': 'cipher-local:integration-' + NEW, 'image': NEW_IMAGE, 'docker': {'context': 'test', 'daemon': 'test'}, 'upgrade_helper_sha256': upgrade.digest(self.root / 'portable-upgrade-site.py'), 'compose_sha256': upgrade.digest(self.root / 'compose.portable.yml')}
        self.receipt = self.root / 'candidate.json'
        self.receipt.write_text(json.dumps(self.candidate))
        self.runtime = {'container': '123', 'image': OLD_IMAGE['id'], 'mounts': []}
        self.directory = local.environment_path('integration').parent / 'upgrades' / NEW

    def images(self, operator, reference):
        return NEW_IMAGE if reference in (NEW_IMAGE['id'], self.candidate['reference']) else OLD_IMAGE

    def test_trial_upgrade_is_rejected_before_docker(self):
        with patch.object(local.subprocess, 'run') as run:
            with self.assertRaises(local.LocalError):
                local.main(['upgrade', '--candidate', str(self.receipt), '--acknowledge-build', NEW, '--writers-quiesced'])
            run.assert_not_called()

    def test_pending_upgrade_blocks_ordinary_start_before_docker(self):
        upgrade.write(upgrade.active(local), {'journal': 'pending'})
        with patch.object(local.subprocess, 'run') as run:
            with self.assertRaises(local.LocalError):
                local.main(['--profile', 'integration', 'start'])
            run.assert_not_called()

    def test_oneoff_pins_id_and_explicitly_bypasses_serving_entrypoint(self):
        with patch.object(local, 'compose', return_value=SimpleNamespace(stdout='{}')) as compose:
            upgrade.oneoff(local, NEW_IMAGE['id'], upgrade.PYTHON, '-c', 'pass')
        self.assertEqual(compose.call_args.args, ('integration', 'run', '--rm', '--no-deps', '--entrypoint', upgrade.PYTHON, 'runtime', '-c', 'pass'))
        self.assertEqual(compose.call_args.kwargs['image'], NEW_IMAGE['id'])

    def test_candidate_tag_move_is_rejected(self):
        with patch.object(upgrade, 'image', return_value=OLD_IMAGE):
            with self.assertRaises(local.LocalError):
                upgrade.candidate_receipt(local, self.receipt)

    def test_profile_lock_excludes_second_operator(self):
        with local.profile_lock('integration'):
            with self.assertRaises(local.LocalError):
                with local.profile_lock('integration'):
                    self.fail('concurrent command admitted')

    def run_upgrade(self, site_action, *, resume=False):
        with patch.object(upgrade, 'image', side_effect=self.images), patch.object(upgrade, 'context', return_value=self.candidate['docker']), patch.object(upgrade, 'runtime_identity', return_value=self.runtime), patch.object(upgrade, 'docker'), patch.object(upgrade, 'stopped'), patch.object(upgrade, 'dependencies'), patch.object(upgrade, 'site', side_effect=site_action), patch.object(upgrade, 'export_backup', return_value={'directory': str(self.directory / 'backup'), 'manifest_sha256': hashlib.sha256(b'backup').hexdigest()}), patch.object(local, 'checked_backup'), patch('builtins.print'):
            return upgrade.upgrade(local, self.receipt, NEW, resume=resume)

    def prepare_backup(self):
        path = self.directory / 'backup'
        path.mkdir(parents=True, exist_ok=True)
        (path / 'manifest.json').write_bytes(b'backup')

    def test_migration_failure_keeps_original_environment_and_durable_intent(self):
        original = local.environment_path('integration').read_bytes()
        self.prepare_backup()
        def action(operator, state, action, **kwargs):
            if action == 'migrate':
                raise RuntimeError('migration interrupted')
            return {'snapshot': 'saved'}
        with self.assertRaises(RuntimeError):
            self.run_upgrade(action)
        state = json.loads((self.directory / 'upgrade.json').read_text())
        self.assertEqual(state['stage'], 'migration_intent')
        self.assertEqual(original, local.environment_path('integration').read_bytes())
        self.assertTrue(upgrade.active(local).exists())

    def test_resume_migration_does_not_rebackup_and_completes_with_service_stopped(self):
        self.prepare_backup()
        calls = []
        def action(operator, state, action, **kwargs):
            calls.append(action)
            if action == 'migrate' and calls.count('migrate') == 1:
                raise RuntimeError('interrupted')
            return {'contract': 'readback'}
        with self.assertRaises(RuntimeError):
            self.run_upgrade(action)
        calls.clear()
        def resumed(operator, state, action, **kwargs):
            calls.append(action)
            return {'contract': 'readback'}
        self.run_upgrade(resumed, resume=True)
        self.assertEqual(calls, ['migrate', 'verify', 'publish', 'release'])
        self.assertEqual(local.settings('integration')['CIPHER_IMAGE'], NEW_IMAGE['id'])
        self.assertFalse(upgrade.active(local).exists())

    def test_failed_schema_readback_never_publishes_environment(self):
        self.prepare_backup()
        original = local.environment_path('integration').read_bytes()
        calls = []
        def action(operator, state, action, **kwargs):
            calls.append(action)
            if action == 'verify':
                raise ValueError('missing native Task column')
            return {}
        with self.assertRaises(ValueError):
            self.run_upgrade(action)
        self.assertNotIn('publish', calls)
        self.assertEqual(original, local.environment_path('integration').read_bytes())
        self.assertEqual(json.loads((self.directory / 'upgrade.json').read_text())['stage'], 'migrated')

    def test_interrupted_preparation_reuses_identical_retained_environment(self):
        self.prepare_backup()
        (self.directory / 'environment.original').write_bytes(local.environment_path('integration').read_bytes())
        result = self.run_upgrade(lambda *args, **kwargs: {})
        self.assertEqual(result['stage'], 'complete')

    def test_completed_old_upgrade_cannot_clear_another_pending_upgrade_guard(self):
        self.prepare_backup()
        self.run_upgrade(lambda *args, **kwargs: {})
        guard = {'journal': 'other-upgrade', 'id': 'f' * 32}
        upgrade.write(upgrade.active(local), guard)
        with self.assertRaises(local.LocalError):
            self.run_upgrade(lambda *args, **kwargs: {}, resume=True)
        self.assertEqual(json.loads(upgrade.active(local).read_text()), guard)

    def test_unknown_journal_stage_cannot_clear_startup_guard(self):
        self.prepare_backup()
        self.run_upgrade(lambda *args, **kwargs: {})
        state_path = self.directory / 'upgrade.json'
        state = json.loads(state_path.read_text())
        state['stage'] = 'unexpected'
        upgrade.write(state_path, state)
        upgrade.write(upgrade.active(local), {'journal': str(state_path), 'id': state['id']})
        with self.assertRaises(local.LocalError):
            self.run_upgrade(lambda *args, **kwargs: {}, resume=True)
        self.assertTrue(upgrade.active(local).exists())

    def test_retained_environment_tampering_is_refused_before_resumed_migration(self):
        self.prepare_backup()
        def failed(operator, state, action, **kwargs):
            if action == 'migrate':
                raise RuntimeError('interrupted')
            return {}
        with self.assertRaises(RuntimeError):
            self.run_upgrade(failed)
        retained = self.directory / 'environment.original'
        retained.write_bytes(retained.read_bytes() + b'# changed\n')
        actions = []
        with self.assertRaises(local.LocalError):
            self.run_upgrade(lambda *args, **kwargs: actions.append(args[2]), resume=True)
        self.assertEqual(actions, [])

    def test_recovery_imports_retained_host_files_and_restores_only_isolated_site(self):
        self.prepare_backup()
        state = self.run_upgrade(lambda *args, **kwargs: {})
        prefix = '20261017_120000-cipher_localhost'
        hashes = {prefix + '-' + suffix: 'f' * 64 for suffix in local.SUFFIXES}
        manifest = {'prefix': prefix, 'sha256': hashes}
        calls = []
        def offline(operator, image_id, *command):
            calls.append(command)
            return '[1000,0]' if 'import os,json; print(json.dumps([os.getuid(),os.getgid()]))' in command else '{}'
        with patch.object(upgrade, 'candidate_receipt', return_value=(self.receipt, self.candidate)), patch.object(upgrade, 'context', return_value=self.candidate['docker']), patch.object(upgrade, 'image', return_value=OLD_IMAGE), patch.object(upgrade, 'runtime_identity', return_value=self.runtime), patch.object(upgrade, 'stopped'), patch.object(upgrade, 'dependencies'), patch.object(local, 'checked_backup', return_value=(self.directory / 'backup', manifest)), patch.object(upgrade, 'oneoff', side_effect=offline), patch.object(local, 'compose', return_value=SimpleNamespace(stdout='')) as compose, patch('builtins.print'):
            upgrade.restore_upgrade(local, self.receipt)
        copies = [call for call in compose.call_args_list if call.args[1] == 'cp']
        self.assertEqual(len(copies), 4)
        restores = [call for call in compose.call_args_list if '/opt/cipher/operations/restore-synthetic.sh' in call.args]
        self.assertEqual(len(restores), 1)
        self.assertTrue(any(item.startswith('CIPHER_RESTORE_SITE=cipher-restore-') for item in restores[0].args))
        self.assertEqual(restores[0].kwargs['image'], OLD_IMAGE['id'])
        self.assertEqual(json.loads((self.directory / 'upgrade.json').read_text()), state)


if __name__ == '__main__':
    unittest.main()
