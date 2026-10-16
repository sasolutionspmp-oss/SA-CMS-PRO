"""Explicit persistent operator setup; never migration or award activation."""
import json
from pathlib import Path

import frappe
from frappe.config import get_common_site_config, get_site_config
from frappe.installer import update_site_config

from cipher_aec.api.errors import DomainError
from cipher_aec.awards.runtime_profile import PROFILE
from cipher_aec.governance.context import assert_synthetic_site

PROFILE_KEY = "cipher_award_native_profile"
SEARCH_KEY = "disable_global_search"


def _refuse():
    raise DomainError("award_native_profile_setup_required",
        "The persistent native award profile requires operator reconciliation.", 503)


def _site_configuration():
    # Read the site file separately: a merged common value is not a persisted
    # site selection. Do not return or log any unrelated configuration values.
    value = json.loads(Path(frappe.get_site_path("site_config.json")).read_text())
    if not isinstance(value, dict):
        _refuse()
    return value


def _unrelated(value):
    return {key: item for key, item in value.items() if key not in (PROFILE_KEY, SEARCH_KEY)}


def _same(left, right):
    # JSON types matter: Python otherwise equates boolean true with integer 1.
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def configure_native_profile():
    """Select the synthetic deployment profile without qualifying its runtime.

    The operator serializes configuration changes and stops/reloads services
    separately. Supported writes persist search suppression before the profile
    marker. An interrupted setup can be retried; it never turns indexing back
    on or silently replaces another profile. Existing search entries, queues,
    native callbacks, common settings and action enablement remain untouched.
    """
    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise DomainError("operator_required",
            "Native award profile setup requires the synthetic site operator.", 403)
    try:
        before = _site_configuration()
        common = get_common_site_config(cached=False)
        fresh = get_site_config(cached=False)
        if not isinstance(common, dict) or fresh.get("cipher_site_mode") != "synthetic":
            _refuse()
        for configuration in (before, common, fresh, frappe.conf):
            if PROFILE_KEY in configuration and configuration[PROFILE_KEY] != PROFILE:
                _refuse()
        if before.get(SEARCH_KEY) is not True:
            update_site_config(SEARCH_KEY, True)
        # Verify the first durable write before publishing the profile marker.
        current = _site_configuration()
        if current.get(SEARCH_KEY) is not True or not _same(_unrelated(current), _unrelated(before)):
            _refuse()
        if PROFILE_KEY in current and current[PROFILE_KEY] != PROFILE:
            _refuse()
        if current.get(PROFILE_KEY) != PROFILE:
            update_site_config(PROFILE_KEY, PROFILE)
        after = _site_configuration()
        effective = get_site_config(cached=False)
        if (after.get(SEARCH_KEY) is not True or after.get(PROFILE_KEY) != PROFILE
                or effective.get(SEARCH_KEY) is not True or effective.get(PROFILE_KEY) != PROFILE
                or not _same(_unrelated(after), _unrelated(before))
                or not _same(get_common_site_config(cached=False), common)):
            _refuse()
    except DomainError:
        raise
    except Exception as error:
        raise DomainError("award_native_profile_setup_failed",
            "Native award profile setup did not complete; inspect the private operator log.", 503) from error
    return {"schema": "cipher.award.native-profile-setup.v1", "profile": PROFILE,
        "persisted": True, "disable_global_search": True,
        "worker_reload_required": True, "runtime_qualified": False}
