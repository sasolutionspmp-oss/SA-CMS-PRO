"""Explicit local human-trial bootstrap for the new synthetic Frappe application.

This is an operator-only bench entry, never an HTTP endpoint. Domain evidence is
created through its supported services. It grants no award or external delivery
ability and does not make an engineering decision for the human trial.
"""

from datetime import date
import hashlib
import json
import os
from pathlib import Path

import frappe

from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import assert_synthetic_site, trusted_write


SCHEMA = "cipher.local-trial.v1"
AUTHOR_ROLE = "Cipher Local Trial Author"
REVIEWER_ROLE = "Cipher Local Trial Reviewer"
UNIT_OPERATION = "83dafcd3-76f0-4d06-bf0c-c8f7cfcc6ae9"
SOURCE_OPERATION = "99bf5dc6-da3a-4d55-9939-889d3624c415"
RATE_OPERATION = "424cdf9e-c625-426f-9255-b443245fd1c4"
SOURCE_BYTES = (
    "Cipher local human trial: synthetic internal coordination source.\n"
    "Trial labor rate: USD 75.00 per labor hour. No freight, tax or markup.\n"
    "Trial quantity basis: 8 authored labor hours; a successor may use 10 hours.\n"
    "RFI scenario: confirm that this document is the internal trial basis.\n"
    "This authored fixture is not a supplier quote, design instruction or professional certification.\n"
).encode("utf-8")


def _manifest_path():
    # Standard private-files backups preserve this nonsecret setup manifest.
    return Path(frappe.get_site_path("private", "files", "cipher-local-trial-v1.json"))


def _existing(doctype, filters, fields):
    name = frappe.db.get_value(doctype, filters, "name")
    if name:
        doc = frappe.get_doc(doctype, name)
        if any(doc.get(key) != value for key, value in fields.items()):
            raise DomainError("trial_fixture_conflict", "An existing local-trial master has different setup. Review it before continuing.", 409)
        return doc
    return frappe.get_doc({"doctype": doctype, **filters, **fields}).insert(ignore_permissions=True)


def _native_roles(users):
    from frappe.permissions import add_permission, update_permission_property
    readable = ("Company", "Customer", "Lead", "Price List", "Currency", "UOM", "Item", "Account", "Opportunity", "Quotation")
    for role in (AUTHOR_ROLE, REVIEWER_ROLE):
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
        for doctype in readable:
            add_permission(doctype, role, 0)
            for permission in ("read", "select", "create", "write", "submit", "cancel", "delete"):
                allowed = permission in ("read", "select") or role == AUTHOR_ROLE and doctype in ("Opportunity", "Quotation") and permission in ("create", "write")
                update_permission_property(doctype, role, 0, permission, int(allowed))
    for key, role in (("primary", AUTHOR_ROLE), ("alias", AUTHOR_ROLE), ("reviewer", REVIEWER_ROLE)):
        doc = frappe.get_doc("User", users[key]["user"])
        if role not in {row.role for row in doc.roles}:
            doc.append("roles", {"role": role})
            doc.save(ignore_permissions=True)


def _native_masters(company):
    today = date.fromisoformat(str(frappe.utils.nowdate()))
    fiscal_year = None
    for name in frappe.get_all("Fiscal Year", filters={"year_start_date": ["<=", today], "year_end_date": [">=", today], "disabled": 0},
        pluck="name", order_by="year_start_date desc,name asc", limit_page_length=0):
        candidate = frappe.get_doc("Fiscal Year", name)
        if not candidate.get("companies") or company in {row.company for row in candidate.companies}:
            fiscal_year = candidate
            break
    if fiscal_year is None:
        fiscal_year = frappe.get_doc({"doctype": "Fiscal Year", "year": f"Cipher Local Trial {today.year}",
            "year_start_date": date(today.year, 1, 1), "year_end_date": date(today.year, 12, 31),
            "companies": [{"company": company}]}).insert(ignore_permissions=True)
    customer_group = _existing("Customer Group", {"customer_group_name": "Cipher Local Trial Customers"},
        {"parent_customer_group": "All Customer Groups", "is_group": 0})
    territory = _existing("Territory", {"territory_name": "Cipher Local Trial Territory"},
        {"parent_territory": "All Territories", "is_group": 0})
    customer = _existing("Customer", {"customer_name": "Cipher Local Trial Customer"},
        {"customer_type": "Company", "customer_group": customer_group.name, "territory": territory.name})
    if customer.get("accounts") and company not in {row.company for row in customer.accounts}:
        raise DomainError("trial_fixture_conflict", "The local-trial Customer belongs to a different Company.", 409)
    price_list = _existing("Price List", {"price_list_name": "Cipher Local Trial USD Selling"},
        {"currency": "USD", "enabled": 1, "selling": 1, "buying": 0})
    unit = _existing("UOM", {"uom_name": "Cipher Local Trial Labor Hour"},
        {"symbol": "trial-lh", "enabled": 1, "must_be_whole_number": 0})
    return {"customer": customer.name, "price_list": price_list.name, "uom": unit.name, "fiscal_year": fiscal_year.name}


def _load_manifest(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value.get("site") != frappe.local.site:
        raise DomainError("trial_fixture_conflict", "The saved trial manifest does not match this site.", 409)
    checks = [("Company", value["company"]), ("Project", value["project"]),
        ("Cipher Document Revision", value["source"]["revision"]), ("Cipher Rate Source", value["rate_source"])]
    if not all(frappe.db.exists(doctype, name) for doctype, name in checks):
        raise DomainError("trial_fixture_incomplete", "The saved trial setup is incomplete. Restore its matching database and files before continuing.", 409)
    # Reruns deliberately preserve passwords, revoked duties and human work.
    return {**value, "already_initialized": True}


def seed_local_trial(passwords=None):
    """Initialize once with CIPHER_FIXTURE_PASSWORD; return IDs, never credentials.

    Only the explicit local synthetic profile should call this entry. Subsequent
    calls read the saved manifest without reseeding or restoring revoked rights.
    No task/proposal/estimate/answer/approval is manufactured for the user.
    """
    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise DomainError("administrator_required", "Only the synthetic site administrator can initialize a local trial.", 403)
    if frappe.conf.get("cipher_allow_unscanned_documents") not in (1, True, "1"):
        raise DomainError("trial_document_policy_required", "The local synthetic trial requires the explicit unscanned-document allowance.", 409)
    path = _manifest_path()
    if path.exists():
        return _load_manifest(path)
    pending = path.with_suffix(".pending.json")
    if pending.exists():
        # A process may stop after its commit and before the final rename. Never
        # reseed that setup: validate its committed IDs and publish the guard.
        value = _load_manifest(pending)
        pending.replace(path)
        return value
    accounts = {"primary": "morgan@cipher.example", "alias": "morgan.alias@cipher.example",
        "outsider": "taylor@cipher.example", "reviewer": "jordan@cipher.example"}
    if not os.environ.get("CIPHER_FIXTURE_PASSWORD") and not (
        isinstance(passwords, dict) and all(passwords.get(key) or passwords.get(email) for key, email in accounts.items())
    ):
        raise DomainError("trial_credentials_required", "Supply local trial credentials privately before initialization.", 409)
    from cipher_aec.install import seed_synthetic, _grant, _grant_company
    from cipher_aec.estimating import company_service, service as estimates
    from cipher_aec.documents.service import upload_document, get_citation
    fixture = seed_synthetic(passwords=passwords)
    company, project, users = fixture["company"], fixture["project"], fixture["users"]
    administrator = frappe.db.get_value("Cipher Identity Binding", {"user": "Administrator", "active": 1}, "person")
    with trusted_write():
        _native_roles(users)
        masters = _native_masters(company)
        for ability in ("company.read", "commercial.read", "commercial.write", "document.read", "document.write", "estimate.read", "estimate.write", "approval.request", "approval.execute"):
            _grant_company(users["primary"]["person"], company, ability)
        for ability in ("company.read", "commercial.read", "document.read", "estimate.read", "approval.decide"):
            _grant_company(users["reviewer"]["person"], company, ability)
        for ability in ("company.read", "estimate.read", "estimate.write"):
            _grant_company(administrator, company, ability)
        for ability in ("engineering.read", "engineering.write", "engineering.distribute"):
            _grant(users["primary"]["person"], company, project, ability)
        for ability in ("document.read", "engineering.read"):
            _grant(users["reviewer"]["person"], company, project, ability)
    for details in users.values():
        frappe.clear_cache(user=details["user"])
    # Qualification is an administrator operation, not an author role escalation.
    unit = company_service.register_unit(company, UNIT_OPERATION, masters["uom"], "labor_time", 6)["unit"]
    try:
        frappe.set_user(users["primary"]["user"])
        source = upload_document(company=company, project=project, operation_id=SOURCE_OPERATION,
            title="Cipher local trial source", filename="cipher-local-trial-source.txt", content=SOURCE_BYTES,
            byte_length=len(SOURCE_BYTES), sha256=hashlib.sha256(SOURCE_BYTES).hexdigest())
        citation = get_citation(company, source["revision"]["id"], 1)
        reference = {key: citation[key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")}
        rate = estimates.create_rate(company, project, RATE_OPERATION, {
            "title": "Cipher local trial labor: USD 75/hour", "cost_type": "labor", "unit_id": unit["id"],
            "rate_amount": "75.00", "rate_precision": 2, "currency": "USD", "quote_reference": "LOCAL-TRIAL-AUTHORED-V1",
            "quote_date": "2026-10-17", "expiry_date": None, "geography": "Synthetic local trial",
            "inclusions": "One authored labor hour", "exclusions": "All other costs",
            "freight_tax_assumptions": "No freight, tax or markup", "permission_basis": "Original synthetic trial fixture",
            "source_citations": [reference]})["rate_source"]
        value = {"schema": SCHEMA, "site": frappe.local.site, "site_mode": "synthetic", "company": company,
            "project": project, "other_project": fixture["other_project"], "users": users, "native": masters,
            "unit": {"id": unit["id"], "revision": unit["revision"], "dimension": "labor_time"},
            "source": {"document": source["document"]["id"], "revision": source["revision"]["id"], "citation": reference},
            "rate_source": rate["id"], "credentials_recorded": False,
            "capability_gaps": ["Task assignee, task update and task completion are unavailable in the governed API/UI.",
                "Internal engineering distribution records a persistent receipt; external delivery is unavailable.",
                "Ricky live model, accounting providers and award actions are outside this trial."]}
        path.parent.mkdir(parents=True, exist_ok=True)
        # Stage before commit so disk/write failures cannot leave a committed
        # fixture that a later invocation mistakes for an uninitialized site.
        with pending.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        frappe.db.commit()
        pending.replace(path)
        return {**value, "already_initialized": False}
    except Exception:
        frappe.db.rollback()
        raise
    finally:
        frappe.set_user("Administrator")
