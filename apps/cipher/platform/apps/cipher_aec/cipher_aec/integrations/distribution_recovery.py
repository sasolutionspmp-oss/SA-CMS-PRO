"""Republish existing literal Company fixture intents; never execute delivery.

This trusted operational entry owns a fresh, read-only database transaction per
sweep. It is deliberately separate from the general scheduler and Task outbox.
The process supervisor owns startup/restart; workers retain all effect authority.
"""
import time

from cipher_aec.api.errors import DomainError

BATCH_SIZE = 100
INTERVAL_SECONDS = 5


def publish_pending():
    """Attempt fixed-queue publication; returned count is not a Redis receipt."""
    import frappe
    from frappe.utils import now_datetime
    from .distribution import require_current_effects_enabled
    from .outbox import _schedule

    if frappe.db.transaction_writes:
        raise RuntimeError("Distribution recovery requires an isolated read-only transaction")
    # Discard any previous repeatable-read snapshot before discovering durable
    # intents. This entry is not an RPC or a helper inside a business command.
    frappe.db.rollback()
    attempted = 0
    try:
        require_current_effects_enabled()
        rows = frappe.db.sql("""SELECT name FROM `tabCipher Integration Operation`
            WHERE scope_type='Company' AND (project IS NULL OR project='')
            AND kind='company.proposal.fixture.v1'
            AND (state='Queued' OR (state IN ('Claimed','Unknown')
                AND (lease_until IS NULL OR lease_until<=%s)))
            ORDER BY name LIMIT %s""", (now_datetime(), BATCH_SIZE))
        for (name,) in rows:
            # An operator may quarantine the site while this sweep is running.
            # _schedule additionally rechecks immediately before its enqueue.
            require_current_effects_enabled()
            _schedule(name)
            attempted += 1
        return {"status": "sweep_complete", "eligible": len(rows), "publication_attempts": attempted}
    except DomainError as error:
        if error.code != "execution_quarantined":
            raise
        return {"status": "quarantined", "publication_attempts": attempted}
    finally:
        frappe.db.rollback()


def run_forever():
    """Fixed operational publisher; no caller-selected queue, method or interval."""
    import frappe
    while True:
        try:
            publish_pending()
        except Exception:
            # Redis publication itself is handled by _schedule. Database/service
            # unavailability must not turn a persisted intent into a lost one.
            frappe.logger("cipher_distribution_recovery").exception("Distribution recovery sweep unavailable")
        time.sleep(INTERVAL_SECONDS)
