"""Additive migration; old Project payloads/business hashes stay untouched."""
from pathlib import Path

from cipher_aec.api.errors import DomainError


def after_migrate():
    import frappe
    for doctype in ("Cipher Integration Operation", "Cipher Delivery Attempt"):
        frappe.db.sql("UPDATE `tab" + doctype + "` SET scope_type='Project' WHERE scope_type IS NULL OR scope_type=''")
    frappe.db.add_index("Cipher Integration Operation", ["kind", "scope_type", "company", "state", "lease_until"], "cipher_company_delivery_recovery")
    frappe.db.add_index("Cipher Integration Operation", ["distribution_dispatch", "state"], "cipher_distribution_recipients")
    frappe.db.add_index("Cipher Distribution Dispatch", ["company", "creation"], "cipher_distribution_company")


def _worker_configuration(previous):
    if not isinstance(previous, dict) or not isinstance(previous.get("cipher_distribution", {}), dict):
        raise DomainError("queue_setup_required", "The native worker configuration must be an object.", 503)
    workers = dict(previous)
    workers["cipher_distribution"] = {**previous.get("cipher_distribution", {}), "timeout": 120}
    return workers


def configure_queue():
    """Supported operator setup; preserve all unrelated common worker settings.

    Configuration changes are serialized by the deployment operator. This is
    not a whitelisted method or a business command and creates no delivery.
    Existing worker/web processes need a reload to discard their cached catalog.
    """
    import frappe
    from frappe.config import get_common_site_config
    from frappe.installer import update_site_config
    from frappe.utils.background_jobs import get_queues_timeout
    from cipher_aec.governance.context import assert_synthetic_site

    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise DomainError("operator_required", "Queue setup requires the synthetic site operator.", 403)
    previous = get_common_site_config(cached=False).get("workers", {})
    workers = _worker_configuration(previous)
    if workers != previous:
        update_site_config("workers", workers,
            site_config_path=str(Path(frappe.local.sites_path) / "common_site_config.json"))
    get_queues_timeout.cache_clear()
    return {"queue": "cipher_distribution", "timeout": 120,
        "preserved_worker_names": sorted(name for name in previous if name != "cipher_distribution")}


def legacy_query(user=None):
    return "(scope_type='Project' OR scope_type IS NULL OR scope_type='')"


def legacy_permission(doc, ptype=None, user=None, **kwargs):
    return doc.get("scope_type") != "Company"
