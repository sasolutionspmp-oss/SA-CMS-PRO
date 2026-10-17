"""Pinned callback-free native award profile; no caller-selected bypass or toggle.

Native callbacks can emit synchronously. This guard precedes allocation/insert;
callback-tail cleanup is an additional rollback boundary, never compensation for
an already sent notification. Existing native search rows/queue are not purged.
"""
import frappe
from cipher_aec.api.errors import DomainError

PROFILE = 'cipher.award.native.no-side-effects.v1'
# Literal transitive writes of one award effect, including receipt/consumption.
# This is not a site-wide callback ban.
CIPHER_TARGETS = (
    'Cipher Project Profile', 'Cipher Construction Contract', 'Cipher Budget Version',
    'Cipher Budget Line', 'Cipher WBS Node', 'Cipher Project Duty',
    'Cipher Award Adoption', 'Cipher Award Line Adoption', 'Cipher Award Handoff',
    'Cipher History Event', 'Cipher Approval Consumption', 'Cipher Command Receipt',
)
TARGETS = ('Project', 'Sales Order', *CIPHER_TARGETS)
CONFIGURATIONS = (
    ('Notification', 'document_type', {'enabled': 1}),
    ('Assignment Rule', 'document_type', {'disabled': 0}),
    ('Webhook', 'webhook_doctype', {'enabled': 1}),
    ('Workflow', 'document_type', {'is_active': 1}),
    ('Automation Flow', 'document_type', {'enabled': 1}),
    ('Server Script', 'reference_doctype', {'disabled': 0, 'script_type': 'DocType Event'}),
    ('Milestone Tracker', 'document_type', {'disabled': 0}),
    # The native SLA doctype catalog includes disabled rows as well.
    ('Service Level Agreement', 'document_type', {}),
    ('User Type', 'apply_user_permission_on', {'is_standard': 0}),
)


def _deny():
    raise DomainError('award_native_profile_unqualified',
        'The current native award callback profile requires separate qualification.', 503)


def _true(value):
    return value is True or type(value) is int and value == 1


def _false(value):
    return value is False or type(value) is int and value == 0


def _empty_list(value):
    if type(value) is not list or value:
        _deny()


def _empty_scoped_map(value, *, nested=False):
    if not isinstance(value, dict):
        _deny()
    for target in TARGETS:
        if target not in value:
            continue
        rows = value[target]
        if nested:
            if not isinstance(rows, dict) or any(type(group) is not list or group for group in rows.values()):
                _deny()
        else:
            _empty_list(rows)


def require_native_profile():
    """Check fresh configuration AND the actual native effective cached paths.

    A stale enabled catalog is refused even if its current DB row is disabled.
    Server Script execution reads common-site configuration independently of a
    merged site override. This returns a static policy, not source/write rights.
    """
    from frappe.config import get_site_config
    from frappe.utils.safe_exec import is_safe_exec_enabled
    from frappe.cache_manager import get_doctype_map
    from frappe.model.workflow import get_workflow_name
    from frappe.integrations.doctype.webhook import get_all_webhooks
    from frappe.core.doctype.server_script.server_script_utils import get_server_script_map
    from frappe.automation_engine.registry import get_automations_for
    from frappe.automation.doctype.milestone_tracker.milestone_tracker import get_milestone_trackers
    from erpnext.support.doctype.service_level_agreement.service_level_agreement import get_documents_with_active_service_level_agreement
    from frappe.core.doctype.user_type.user_type import get_non_standard_user_types
    try:
        loaded, fresh = frappe.conf, get_site_config(cached=False)
        common = frappe.get_common_site_config(cached=False)
        if (loaded.get('cipher_award_native_profile') != PROFILE or fresh.get('cipher_award_native_profile') != PROFILE
                or not _true(loaded.get('disable_global_search')) or not _true(fresh.get('disable_global_search'))
                or loaded.get('server_script_enabled') or fresh.get('server_script_enabled')
                or is_safe_exec_enabled() or common.get('server_script_enabled')
                or any(frappe.flags.get(name) for name in ('in_install', 'in_migrate', 'in_patch', 'in_import', 'in_setup_wizard'))):
            _deny()
        # Document.insert uses this exact cached User preference after save;
        # on tracked Sales Order it can insert a separate Document Follow.
        user = frappe.session.user
        if (not user or user == 'Guest'
                or not _false(frappe.db.get_value('User', user, 'follow_created_documents'))
                or not _false(frappe.get_cached_value('User', user, 'follow_created_documents'))):
            _deny()
        # The item-details path can insert OR update Item Price even during
        # native validation. Every branch is dominated by this cached flag.
        if (not _false(frappe.db.get_single_value('Stock Settings', 'auto_insert_price_list_rate_if_missing', cache=False))
                or not _false(frappe.get_cached_doc('Stock Settings').get('auto_insert_price_list_rate_if_missing'))):
            _deny()
        for doctype, field, active in CONFIGURATIONS:
            if not frappe.db.exists('DocType', doctype):
                _deny()
            meta = frappe.get_meta(doctype)
            if any(not meta.has_field(name) for name in (field, *active)):
                _deny()
            if frappe.db.exists(doctype, {**active, field: ['in', list(TARGETS)]}):
                _deny()
        # These are the pinned helpers used by native Document.run_method and
        # wildcard hooks, not a separate memo/catalog or inferred cache absence.
        webhooks = frappe.client_cache.get_value('webhooks', generator=get_all_webhooks)
        _empty_scoped_map(webhooks)
        _empty_scoped_map(get_server_script_map(), nested=True)
        user_types = frappe.cache.get_value('non_standard_user_types', get_non_standard_user_types)
        if (not isinstance(user_types, dict)
                or any(type(row) is not list or len(row) != 2
                    or any(value is not None and type(value) is not str for value in row)
                    or row[0] in TARGETS for row in user_types.values())):
            _deny()
        sla_targets = get_documents_with_active_service_level_agreement()
        if (not isinstance(sla_targets, (set, frozenset, list, tuple))
                or any(type(name) is not str for name in sla_targets) or set(TARGETS).intersection(sla_targets)):
            _deny()
        for target in TARGETS:
            target_meta = frappe.get_meta(target)
            # Native save_version can itself insert a callback-bearing Version.
            # These exact Cipher writes do not claim native change history.
            if target in CIPHER_TARGETS and target_meta.get('track_changes'):
                _deny()
            fields = target_meta.get('fields')
            if (type(fields) is not list
                    or any(field.get('fieldtype') in ('Attach', 'Attach Image') for field in fields)):
                _deny()
            # Document.run_notifications defines this generator locally; use
            # the exact key, fields and filter from the pinned native method.
            notifications = frappe.client_cache.get_value('notifications::' + target,
                generator=lambda target=target: frappe.get_all('Notification', fields=['name', 'event', 'method'],
                    filters={'enabled': 1, 'document_type': target}))
            _empty_list(notifications)
            _empty_list(get_doctype_map('Assignment Rule', target,
                filters={'document_type': target, 'disabled': 0}, order_by='priority desc'))
            _empty_list(get_doctype_map('Assignment Rule', 'due_date_rules_for_' + target,
                filters={'due_date_based_on': ['is', 'set'], 'document_type': target, 'disabled': 0}))
            workflow = get_workflow_name(target)
            if workflow not in (None, '', b''):
                _deny()
            _empty_list(get_automations_for(target))
            _empty_list(get_milestone_trackers(target))
    except DomainError:
        raise
    except Exception as error:
        raise DomainError('award_native_profile_unqualified',
            'The installed native callback configuration cannot be qualified.', 503) from error
    return {'profile': PROFILE, 'disable_global_search': True, 'native_notify_update': False,
            'external_callbacks': False}
