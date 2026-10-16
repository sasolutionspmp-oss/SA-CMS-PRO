"""Operator configuration uses real temporary files; no site or business writes."""
from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from cipher_aec.api.errors import DomainError
from cipher_aec.awards import runtime_install as setup


class AwardRuntimeInstall(TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.directory = Path(stack.enter_context(TemporaryDirectory()))
        self.site = self.directory / "site_config.json"
        self.common = self.directory / "common_site_config.json"
        self.site.write_text(json.dumps({"cipher_site_mode": "synthetic",
            "db_password": "private-test-value", "nested": {"kept": [1, "two"]},
            "pause_scheduler": True, "cipher_execution_quarantined": True}))
        self.common.write_text(json.dumps({"workers": {"other": {"timeout": 37}},
            "server_script_enabled": True}))
        self.loaded = self.read_site()
        self.actor = SimpleNamespace(user="Administrator")
        self.writes = []
        self.synthetic = stack.enter_context(patch.object(setup, "assert_synthetic_site"))
        stack.enter_context(patch.object(setup, "frappe", SimpleNamespace(
            conf=self.loaded, session=self.actor, get_site_path=lambda name: str(self.directory / name))))
        stack.enter_context(patch.object(setup, "get_common_site_config", side_effect=self.read_common))
        stack.enter_context(patch.object(setup, "get_site_config", side_effect=self.read_effective))
        self.update = stack.enter_context(patch.object(setup, "update_site_config", side_effect=self.write))

    def read_site(self):
        return json.loads(self.site.read_text())

    def read_common(self, *, cached=False):
        self.assertIs(cached, False)
        return json.loads(self.common.read_text())

    def read_effective(self, *, cached=False):
        self.assertIs(cached, False)
        return {**self.read_common(), **self.read_site()}

    def write(self, key, value):
        self.writes.append((key, value))
        contents = self.read_site()
        contents[key] = value
        self.site.write_text(json.dumps(contents))

    def denied(self, code="award_native_profile_setup_required"):
        with self.assertRaises(DomainError) as raised:
            setup.configure_native_profile()
        self.assertEqual(raised.exception.code, code)

    def test_ordered_supported_writes_preserve_common_and_unrelated_site_settings(self):
        before, common = self.read_site(), self.common.read_bytes()
        result = setup.configure_native_profile()
        self.assertEqual(self.writes, [(setup.SEARCH_KEY, True), (setup.PROFILE_KEY, setup.PROFILE)])
        self.assertEqual(self.read_site(), {**before, setup.SEARCH_KEY: True, setup.PROFILE_KEY: setup.PROFILE})
        self.assertEqual(self.common.read_bytes(), common)
        self.assertEqual(self.loaded, before)
        self.assertEqual(result, {"schema": "cipher.award.native-profile-setup.v1",
            "profile": setup.PROFILE, "persisted": True, "disable_global_search": True,
            "worker_reload_required": True, "runtime_qualified": False})
        self.assertNotIn("private-test-value", json.dumps(result))

    def test_repeat_is_no_write_and_does_not_assert_loaded_worker_readiness(self):
        first = setup.configure_native_profile()
        self.writes.clear()
        self.assertEqual(setup.configure_native_profile(), first)
        self.assertEqual(self.writes, [])
        self.assertNotIn(setup.PROFILE_KEY, self.loaded)

    def test_denied_nonadministrator_and_nonsynthetic_make_no_config_writes(self):
        self.actor.user = "ordinary-user"
        self.denied("operator_required")
        self.actor.user = "Administrator"
        self.synthetic.side_effect = DomainError("site_mode_unqualified", "Synthetic site required.", 503)
        self.denied("site_mode_unqualified")
        self.assertEqual(self.writes, [])

    def test_fresh_nonsynthetic_site_refuses_even_when_loaded_config_is_synthetic(self):
        self.write("cipher_site_mode", "production")
        self.writes.clear()
        self.denied()
        self.assertEqual(self.writes, [])

    def test_unknown_site_common_or_loaded_profile_refuses_without_overwriting(self):
        for location in (self.site, self.common, None):
            for value in (None, "", "unreviewed-profile", False):
                with self.subTest(location=str(location), value=value):
                    original = location.read_bytes() if location else dict(self.loaded)
                    if location:
                        contents = json.loads(original)
                        contents[setup.PROFILE_KEY] = value
                        location.write_text(json.dumps(contents))
                    else:
                        self.loaded[setup.PROFILE_KEY] = value
                    self.denied()
                    self.assertEqual(self.writes, [])
                    if location:
                        location.write_bytes(original)
                    else:
                        self.loaded.clear()
                        self.loaded.update(original)

    def test_common_profile_selection_still_persists_typed_site_keys(self):
        contents = self.read_common()
        contents.update({setup.PROFILE_KEY: setup.PROFILE, setup.SEARCH_KEY: True})
        self.common.write_text(json.dumps(contents))
        original = self.common.read_bytes()
        setup.configure_native_profile()
        self.assertEqual(self.writes, [(setup.SEARCH_KEY, True), (setup.PROFILE_KEY, setup.PROFILE)])
        self.assertEqual(self.common.read_bytes(), original)

    def test_truthy_string_and_integer_are_normalized_to_real_boolean(self):
        for value in ("True", "1", 1, False):
            with self.subTest(value=value):
                self.write(setup.SEARCH_KEY, value)
                self.writes.clear()
                setup.configure_native_profile()
                self.assertIs(self.read_site()[setup.SEARCH_KEY], True)
                self.assertEqual(self.writes[0], (setup.SEARCH_KEY, True))

    def test_failed_first_write_does_not_publish_profile_marker(self):
        self.update.side_effect = OSError("fixture write failed")
        self.denied("award_native_profile_setup_failed")
        self.update.assert_called_once_with(setup.SEARCH_KEY, True)
        self.assertNotIn(setup.PROFILE_KEY, self.read_site())

    def test_failed_second_write_leaves_search_suppressed_and_retry_completes(self):
        def fail_marker(key, value):
            if key == setup.PROFILE_KEY:
                raise OSError("fixture marker failure")
            self.write(key, value)
        self.update.side_effect = fail_marker
        self.denied("award_native_profile_setup_failed")
        self.assertIs(self.read_site()[setup.SEARCH_KEY], True)
        self.assertNotIn(setup.PROFILE_KEY, self.read_site())
        self.writes.clear()
        self.update.side_effect = self.write
        setup.configure_native_profile()
        self.assertEqual(self.writes, [(setup.PROFILE_KEY, setup.PROFILE)])

    def test_noop_first_write_cannot_publish_marker(self):
        self.update.side_effect = lambda key, value: None
        self.denied()
        self.update.assert_called_once_with(setup.SEARCH_KEY, True)

    def test_failed_profile_readback_and_unrelated_drift_are_not_success(self):
        def ignore_marker(key, value):
            if key == setup.SEARCH_KEY:
                self.write(key, value)
        self.update.side_effect = ignore_marker
        self.denied()
        def drift(key, value):
            self.write(key, value)
            self.write("pause_scheduler", False)
        self.update.side_effect = drift
        self.denied()

    def test_common_configuration_drift_is_reported_without_repair(self):
        def drift_common(key, value):
            self.write(key, value)
            self.common.write_text(json.dumps({"operator_drift": True}))
        self.update.side_effect = drift_common
        self.denied()
        self.assertEqual(self.read_common(), {"operator_drift": True})

    def test_intermediate_unexpected_profile_is_not_overwritten(self):
        def drift_profile(key, value):
            self.write(key, value)
            self.write(setup.PROFILE_KEY, "unexpected-profile")
        self.update.side_effect = drift_profile
        self.denied()
        self.update.assert_called_once_with(setup.SEARCH_KEY, True)
        self.assertEqual(self.read_site()[setup.PROFILE_KEY], "unexpected-profile")

    def test_effective_readback_must_agree_with_persisted_site_selection(self):
        def effective(*, cached):
            config = self.read_effective(cached=cached)
            if setup.PROFILE_KEY in config:
                config[setup.SEARCH_KEY] = "True"
            return config
        with patch.object(setup, "get_site_config", side_effect=effective):
            self.denied()
        self.assertIs(self.read_site()[setup.SEARCH_KEY], True)

    def test_unrelated_site_and_common_value_types_are_preserved(self):
        def site_drift(key, value):
            self.write(key, value)
            self.write("pause_scheduler", 1)
        self.update.side_effect = site_drift
        self.denied()
        self.assertNotIn(setup.PROFILE_KEY, self.read_site())
        self.write("pause_scheduler", True)
        def common_drift(key, value):
            self.write(key, value)
            common = self.read_common()
            common["server_script_enabled"] = 1
            self.common.write_text(json.dumps(common))
        self.update.side_effect = common_drift
        self.denied()

    def test_invalid_site_json_fails_before_supported_setter(self):
        self.site.write_text("invalid-json")
        self.denied("award_native_profile_setup_failed")
        self.assertEqual(self.writes, [])

    def test_nonobject_site_json_fails_before_supported_setter(self):
        self.site.write_text("[]")
        self.denied()
        self.assertEqual(self.writes, [])
