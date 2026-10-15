"""Idempotent app installation and explicitly synthetic development fixtures."""

import os
import secrets

import frappe

from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import ABILITIES, assert_synthetic_site, trusted_write


def after_install():
    for name in ("Cipher User", "Cipher Administrator"):
        if not frappe.db.exists("Role", name):
            frappe.get_doc({"doctype": "Role", "role_name": name}).insert(ignore_permissions=True)
    from frappe.permissions import add_permission, update_permission_property
    for doctype in ("Project", "Task"):
        add_permission(doctype, "Cipher User", 0)
        update_permission_property(doctype, "Cipher User", 0, "read", 1)
    after_migrate()


def after_migrate():
    ensure_site_keys()
    for table, columns, name in (
        ("Cipher Project Duty", ["person", "company", "project", "ability"], "cipher_duty_scope_unique"),
        ("Cipher Command Receipt", ["person", "operation_id"], "cipher_command_person_uuid_unique"),
    ):
        frappe.db.add_unique(table, columns, constraint_name=name)
    frappe.db.add_index("Cipher Project Duty", ["person", "company", "project", "active"], "cipher_duty_actor_scope")
    frappe.db.add_index("Cipher History Event", ["company", "project", "creation"], "cipher_history_scope")
    frappe.db.add_index("Cipher Integration Operation", ["state", "lease_until"], "cipher_outbox_dispatch")
    from cipher_aec.documents.install import after_migrate as document_migrate
    document_migrate()
    from cipher_aec.estimating.install import after_migrate as estimating_migrate
    estimating_migrate()
    from cipher_aec.governance.approvals import install_policy
    install_policy()
    frappe.db.add_unique("Cipher Approval Policy Revision", ["action", "version"], constraint_name="cipher_approval_policy_version")
    frappe.db.add_index("Cipher Approval Packet", ["company", "project", "creation"], "cipher_approval_scope")
    frappe.db.add_index("Cipher Approval Decision", ["packet", "creation"], "cipher_approval_decisions")


def ensure_site_keys():
    # Frappe creates this lazily for Password fields. Provision it at installation
    # so read-only paging never races to invent its own signing secret.
    from frappe.utils.password import get_encryption_key
    get_encryption_key()
    return {"configured": True}


def _person(name, display_name):
    if not frappe.db.exists("Cipher Person", name):
        frappe.get_doc({"doctype": "Cipher Person", "display_name": display_name, "active": 1}).insert(ignore_permissions=True, set_name=name)
    elif not frappe.db.get_value("Cipher Person", name, "active"):
        doc = frappe.get_doc("Cipher Person", name)
        doc.active = 1
        doc.save(ignore_permissions=True)
    return name


def _user(email, first_name, password):
    if not frappe.db.exists("User", email):
        doc = frappe.get_doc({"doctype": "User", "email": email, "first_name": first_name,
            "enabled": 1, "send_welcome_email": 0, "user_type": "System User", "new_password": password or secrets.token_urlsafe(32),
            "roles": [{"role": "Cipher User"}]})
        doc.flags.no_welcome_mail = True
        doc.insert(ignore_permissions=True)
    elif password:
        from frappe.utils.password import update_password
        update_password(email, password, logout_all_sessions=True)


def _binding(user, person):
    name = frappe.db.get_value("Cipher Identity Binding", {"user": user}, "name")
    if not name:
        frappe.get_doc({"doctype": "Cipher Identity Binding", "user": user, "person": person, "active": 1}).insert(ignore_permissions=True)
    else:
        doc = frappe.get_doc("Cipher Identity Binding", name)
        if doc.person != person:
            raise DomainError("fixture_identity_conflict", "Existing fixture binding belongs to another person.")
        if not doc.active:
            doc.active = 1
            doc.save(ignore_permissions=True)


def _grant(person, company, project, ability):
    existing = frappe.db.get_value("Cipher Project Duty", {"person": person, "company": company, "project": project, "ability": ability}, "name")
    if not existing:
        frappe.get_doc({"doctype": "Cipher Project Duty", "person": person, "company": company,
            "project": project, "ability": ability, "active": 1}).insert(ignore_permissions=True)
    else:
        doc = frappe.get_doc("Cipher Project Duty", existing)
        if not doc.active:
            doc.active = 1
            doc.save(ignore_permissions=True)


def seed_synthetic(passwords=None):
    """bench execute only: idempotent seed, never returns or logs credentials.

    Passwords are supplied by operator environment CIPHER_FIXTURE_PASSWORD or a
    per-user mapping. Random nonreturned passwords otherwise prevent shared defaults.
    """
    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise DomainError("administrator_required", "Only the synthetic site administrator can seed fixtures.", 403)
    passwords = passwords or {}
    shared = os.environ.get("CIPHER_FIXTURE_PASSWORD")
    company_name = "Cipher Synthetic Company"
    with trusted_write():
        # Fresh ERPNext sites have not run the interactive setup wizard. Reuse its
        # supported preset installer before Company creates dependent warehouses.
        if not frappe.db.exists("Warehouse Type", "Transit"):
            from erpnext.setup.setup_wizard.operations.install_fixtures import install
            install(country="United States")
        if not frappe.db.exists("Company", company_name):
            frappe.get_doc({"doctype": "Company", "company_name": company_name, "abbr": "CSA",
                "default_currency": "USD", "country": "United States"}).insert(ignore_permissions=True)
        people = {"primary": _person("CIPHER-PERSON-PM", "Morgan Lee (synthetic)"),
            "outsider": _person("CIPHER-PERSON-OTHER", "Taylor Reed (synthetic)"),
            "administrator": _person("CIPHER-PERSON-ADMIN", "Synthetic administrator"),
            "reviewer": _person("CIPHER-PERSON-REVIEWER", "Jordan Chen (synthetic reviewer)")}
        emails = {"primary": "morgan@cipher.example", "alias": "morgan.alias@cipher.example", "outsider": "taylor@cipher.example", "reviewer": "jordan@cipher.example"}
        for key, email in emails.items():
            _user(email, {"outsider": "Taylor", "reviewer": "Jordan"}.get(key, "Morgan"), passwords.get(email) or passwords.get(key) or shared)
            _binding(email, people[key if key in {"outsider", "reviewer"} else "primary"])
        _binding("Administrator", people["administrator"])
        projects = {}
        for key, project_name in (("project", "Synthetic bridge rehabilitation"), ("other_project", "Synthetic water treatment upgrade")):
            name = frappe.db.get_value("Project", {"project_name": project_name, "company": company_name}, "name")
            if not name:
                doc = frappe.get_doc({"doctype": "Project", "project_name": project_name, "company": company_name, "status": "Open"})
                doc.insert(ignore_permissions=True)
                name = doc.name
            projects[key] = name
        for ability in ("project.read", "approval.decide"):
            _grant(people["reviewer"], company_name, projects["project"], ability)
        for ability in sorted(ABILITIES):
            _grant(people["primary"], company_name, projects["project"], ability)
            _grant(people["outsider"], company_name, projects["other_project"], ability)
            for project in projects.values():
                _grant(people["administrator"], company_name, project, ability)
    return {"site_mode": "synthetic", "company": company_name, **projects,
        "users": {key: {"user": email, "person": people[key if key in {"outsider", "reviewer"} else "primary"]} for key, email in emails.items()}}


def set_synthetic_duty(user, project, ability, active):
    """Authenticated bench fixture operation for permission-revocation acceptance."""
    assert_synthetic_site()
    if frappe.session.user != "Administrator" or ability not in ABILITIES or active not in (0, 1):
        raise DomainError("fixture_operation_denied", "This fixture operation is not permitted.", 403)
    person = frappe.db.get_value("Cipher Identity Binding", {"user": user}, "person")
    name = frappe.db.get_value("Cipher Project Duty", {"person": person, "project": project, "ability": ability}, "name")
    if not name:
        raise DomainError("not_found", "Fixture duty is unavailable.", 404)
    with trusted_write():
        doc = frappe.get_doc("Cipher Project Duty", name)
        doc.active = active
        doc.save(ignore_permissions=True)
    return {"project": project, "ability": ability, "active": active}
