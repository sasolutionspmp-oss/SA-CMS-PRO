"""Host-only boundary checks; runtime acceptance requires the actual Linux stack."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace


HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cipher_local', HERE / 'cipher-local.py')
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)
runtime_spec = importlib.util.spec_from_file_location('cipher_portable_runtime', HERE / 'run-portable-services.py')
runtime = importlib.util.module_from_spec(runtime_spec)
runtime_spec.loader.exec_module(runtime)
recovery_spec = importlib.util.spec_from_file_location('cipher_portable_recovery', HERE / 'portable-recovery.py')
recovery = importlib.util.module_from_spec(recovery_spec)
recovery_spec.loader.exec_module(recovery)


class PortableBoundaries(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.task_root = Path(self.directory.name)
        self.root_patch = patch.object(local, 'HERE', self.task_root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def test_profiles_have_independent_secrets_ports_and_project_targets(self):
        with patch('builtins.print'):
            local.initialize('trial')
            local.initialize('integration')
        trial, integration = local.settings('trial'), local.settings('integration')
        self.assertNotEqual(trial['CIPHER_ADMIN_PASSWORD'], integration['CIPHER_ADMIN_PASSWORD'])
        self.assertNotEqual(trial['CIPHER_DB_ROOT_PASSWORD'], integration['CIPHER_DB_ROOT_PASSWORD'])
        self.assertNotEqual(trial['CIPHER_FIXTURE_PASSWORD'], integration['CIPHER_FIXTURE_PASSWORD'])
        self.assertNotEqual(trial['CIPHER_HTTP_PORT'], integration['CIPHER_HTTP_PORT'])
        for profile in ('trial', 'integration'):
            command = local.compose_command(profile, 'stop')
            self.assertEqual(command[command.index('--project-name') + 1], 'cipher-' + profile)
            self.assertEqual(command[command.index('--env-file') + 1], str(local.environment_path(profile)))
            self.assertNotIn(trial['CIPHER_ADMIN_PASSWORD'], command)
        original = local.environment_path('trial').read_bytes()
        with self.assertRaises(local.LocalError):
            local.initialize('trial')
        self.assertEqual(local.environment_path('trial').read_bytes(), original)

    def test_external_cipher_variables_cannot_retarget_profile(self):
        with patch('builtins.print'):
            local.initialize('trial')
        with patch.dict(local.os.environ, {'CIPHER_HTTP_PORT': '0.0.0.0', 'CIPHER_ADMIN_PASSWORD': 'wrong', 'DOCKER_CONTEXT': 'desktop-linux'}):
            with patch.object(local.subprocess, 'run') as run:
                local.compose('trial', 'ps')
        environment = run.call_args.kwargs['env']
        self.assertNotIn('CIPHER_ADMIN_PASSWORD', environment)
        self.assertNotIn('CIPHER_HTTP_PORT', environment)
        self.assertEqual(environment['DOCKER_CONTEXT'], 'desktop-linux')

    def test_cross_profile_port_reuse_is_refused(self):
        with patch('builtins.print'):
            local.initialize('integration')
        path = local.environment_path('integration')
        path.write_text(path.read_text().replace('18900', '18890'))
        with self.assertRaises(local.LocalError):
            local.compose_command('integration', 'start')

    def bundle(self):
        directory = self.task_root / 'bundle'
        directory.mkdir()
        prefix = '20261017_120000-cipher_localhost'
        hashes = {}
        for suffix in local.SUFFIXES:
            name = prefix + '-' + suffix
            data = ('synthetic ' + suffix).encode()
            (directory / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        manifest = {'schema': 'cipher.local-backup.v1', 'prefix': prefix, 'build_id': 'b' * 64, 'sha256': hashes}
        (directory / 'manifest.json').write_text(json.dumps(manifest))
        return directory, manifest

    def test_backup_tampering_or_missing_file_is_refused_before_docker(self):
        directory, manifest = self.bundle()
        self.assertEqual(local.checked_backup(directory)[1], manifest)
        path = directory / next(iter(manifest['sha256']))
        path.write_bytes(b'changed backup')
        with patch.object(local.subprocess, 'run') as run:
            with self.assertRaises(local.LocalError):
                local.restore('trial', directory)
            run.assert_not_called()
        path.unlink()
        with self.assertRaises(local.LocalError):
            local.checked_backup(directory)

    def test_manifest_cannot_select_files_outside_bundle(self):
        directory, manifest = self.bundle()
        name = next(iter(manifest['sha256']))
        manifest['sha256']['../outside'] = manifest['sha256'].pop(name)
        (directory / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(local.LocalError):
            local.checked_backup(directory)

    def test_incompatible_recovery_image_is_refused_before_import(self):
        directory, _ = self.bundle()
        with patch.object(local, 'compose', return_value=SimpleNamespace(stdout='a' * 64)) as compose:
            with self.assertRaises(local.LocalError):
                local.restore('trial', directory)
        self.assertEqual(compose.call_count, 1)
        self.assertNotIn('cp', compose.call_args.args)

    def test_runtime_owner_uses_actual_numeric_user_and_group(self):
        with patch.object(local, 'compose', side_effect=[SimpleNamespace(stdout='1000\n'), SimpleNamespace(stdout='0\n')]) as compose:
            self.assertEqual(local.runtime_owner('integration'), '1000:0')
        self.assertEqual([call.args for call in compose.call_args_list], [
            ('integration', 'exec', '-T', 'runtime', 'id', '-u'),
            ('integration', 'exec', '-T', 'runtime', 'id', '-g')])

    def test_runtime_owner_refuses_non_numeric_or_out_of_range_identifiers(self):
        for invalid in ('frappe', '1000:0', '-1', '1000\n0', '4294967295'):
            with self.subTest(identifier=invalid):
                with patch.object(local, 'compose', return_value=SimpleNamespace(stdout=invalid)):
                    with self.assertRaises(local.LocalError):
                        local.runtime_owner('trial')


class RecoveryConfigurationBoundaries(unittest.TestCase):
    def test_only_allowlisted_settings_are_restored_and_quarantine_wins(self):
        result = recovery.restored_settings({'cipher_site_mode': 'synthetic', 'cipher_synthetic': True,
            'cipher_allow_unscanned_documents': True, 'cipher_award_native_profile': recovery.PROFILE,
            'disable_global_search': True, 'pause_scheduler': False, 'cipher_execution_quarantined': False,
            'db_password': 'source-db-password', 'encryption_key': 'source-encryption-key',
            'mail_server': 'outside.example', 'allow_tests': True, 'developer_mode': 1})
        self.assertEqual(result, {'cipher_site_mode': 'synthetic', 'cipher_synthetic': True,
            'cipher_allow_unscanned_documents': True, 'cipher_award_native_profile': recovery.PROFILE,
            'disable_global_search': True, 'pause_scheduler': True, 'cipher_execution_quarantined': True})

    def test_unscanned_documents_are_never_enabled_without_source_true(self):
        for source in ({}, {'cipher_allow_unscanned_documents': False}):
            result = recovery.restored_settings({'cipher_site_mode': 'synthetic', 'cipher_synthetic': True, **source})
            self.assertIs(result['cipher_allow_unscanned_documents'], False)
        with self.assertRaises(ValueError):
            recovery.restored_settings({'cipher_site_mode': 'synthetic', 'cipher_synthetic': True,
                                        'cipher_allow_unscanned_documents': 'true'})

    def test_unknown_native_profile_and_missing_search_suppression_are_refused(self):
        base = {'cipher_site_mode': 'synthetic', 'cipher_synthetic': True}
        for extra in ({'cipher_award_native_profile': 'unexpected'},
                      {'cipher_award_native_profile': recovery.PROFILE, 'disable_global_search': False}):
            with self.assertRaises(ValueError):
                recovery.restored_settings({**base, **extra})
        with self.assertRaises(ValueError):
            recovery.restored_settings({'cipher_site_mode': 'operational', 'cipher_synthetic': True})


class PersistentStartupBoundaries(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.marker = Path(self.directory.name) / '.cipher-portable.json'
        self.marker_patch = patch.object(runtime, 'MARKER', self.marker)
        self.marker_patch.start()
        self.addCleanup(self.marker_patch.stop)
        self.env_patch = patch.dict(runtime.os.environ, CIPHER_SYNTHETIC='1', CIPHER_SITE='cipher.localhost', CIPHER_BUILD_ID='qualified-build')
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_existing_build_does_not_reseed_migrate_or_reset_credentials(self):
        self.marker.write_text(json.dumps({'schema': 1, 'build_id': 'qualified-build', 'site': 'cipher.localhost'}))
        with patch.object(runtime, 'run') as run:
            runtime.initialize()
        calls = [call.args for call in run.call_args_list]
        self.assertEqual(len(calls), 2)
        self.assertEqual({command[-1] for command in calls}, {
            'cipher_aec.integrations.distribution_install.configure_queue',
            'cipher_aec.awards.runtime_install.configure_native_profile'})

    def test_changed_image_refuses_existing_site_before_any_command(self):
        self.marker.write_text(json.dumps({'schema': 1, 'build_id': 'different-build', 'site': 'cipher.localhost'}))
        with patch.object(runtime, 'run') as run:
            with self.assertRaises(RuntimeError):
                runtime.initialize()
            run.assert_not_called()

    def test_failed_initial_fixture_never_publishes_ready_marker(self):
        def execute(*command, **kwargs):
            if command[-1] == 'frappe.get_installed_apps':
                return SimpleNamespace(stdout='["frappe","erpnext","cipher_aec"]')
            if command[-1] == 'cipher_aec.trial.seed_local_trial':
                raise RuntimeError('synthetic fixture failed')
            return SimpleNamespace(stdout='')
        with patch.object(runtime, 'run', side_effect=execute):
            with self.assertRaises(RuntimeError):
                runtime.initialize()
        self.assertFalse(self.marker.exists())


if __name__ == '__main__':
    unittest.main()
