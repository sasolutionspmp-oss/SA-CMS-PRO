from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib

import frappe
from frappe.utils import getdate, nowdate

from cipher_aec.api.contracts import digest, text
from cipher_aec.api.errors import DomainError

_trusted = ContextVar("cipher_trusted_write", default=False)
_company_native_read = ContextVar("cipher_company_native_read_call", default=None)
ENGINEERING_ABILITIES = frozenset({"engineering.package.read", "engineering.package.write", "engineering.package.check", "engineering.read", "engineering.write", "engineering.distribute"})
DOCUMENT_CONTROL_ABILITIES = frozenset({'document.control.read','document.control.write','document.rights.manage','document.issue','document.adopt','document.distribute','document.control.review'})
FIELD_ABILITIES = frozenset({'field.read','field.write','field.review','field.accept','field.acknowledge'})
SEMANTIC_ABILITIES = frozenset({"document.semantic.manage"})
PROJECT_ABILITIES = frozenset({"document.semantic.manage", "document.control.read", "document.control.write", "document.rights.manage", "document.issue", "document.adopt", "document.distribute", "document.control.review", "engineering.package.read", "engineering.package.write", "engineering.package.check", "engineering.read", "engineering.write", "engineering.distribute", "project.read", "project.write", "task.create", "task.assign", "task.update", "document.read", "document.write", "ricky.run", "approval.request", "approval.decide", "approval.execute", "estimate.read", "estimate.write", "contract.read", "contract.write", "wbs.read", "budget.read", "field.read", "field.write", "field.review", "field.accept", "field.acknowledge"})
COMPANY_ABILITIES = frozenset({"document.semantic.manage", "document.control.read", "document.control.write", "document.rights.manage", "ricky.run", "commercial.award", "project.team.delegate", "project.cost.read", "project.cost.write", "company.read", "commercial.read", "commercial.write", "commercial.distribute", "document.read", "document.write", "estimate.read", "estimate.write", "approval.request", "approval.decide", "approval.execute"})
ABILITIES = PROJECT_ABILITIES | COMPANY_ABILITIES


@dataclass(frozen=True)
class Actor:
    user: str
    person_id: str
    display_name: str


@contextmanager
def trusted_write():
    token = _trusted.set(True)
    try:
        yield
    finally:
        _trusted.reset(token)


def is_trusted_write():
    return _trusted.get()


def require_trusted_write():
    if not is_trusted_write():
        raise DomainError("governed_write_required", "Use the authorized Cipher command for this change.", 403)


def current_actor(user=None, lock=False):
    user = user or frappe.session.user
    if user == "Guest" or not user:
        raise DomainError("authentication_required", "Sign in to Cipher to continue.", 401)
    if lock:
        # Every effect locks canonical people before identity/user rows and then
        # Project. Multi-person approvals acquire this same ordered person set.
        candidate = frappe.db.get_value("Cipher Identity Binding", {"user": user, "active": 1}, "person")
        if candidate:
            frappe.db.sql("SELECT name FROM `tabCipher Person` WHERE name=%s FOR UPDATE", (candidate,))
    suffix = " FOR UPDATE" if lock else ""
    rows = frappe.db.sql(
        "SELECT b.name, b.person, b.modified AS binding_modified, p.display_name, p.active "
        "FROM `tabCipher Identity Binding` b JOIN `tabCipher Person` p ON p.name=b.person "
        "JOIN `tabUser` u ON u.name=b.user "
        "WHERE b.user=%s AND b.active=1 AND p.active=1 AND u.enabled=1" + suffix,
        (user,), as_dict=True,
    )
    if len(rows) != 1:
        raise DomainError("identity_unavailable", "Your active Cipher identity is not configured.", 403)
    row = rows[0]
    return Actor(user=user, person_id=row.person, display_name=row.display_name)


def duty_rows(actor, company=None, project=None, lock=False):
    conditions, args = ["scope_type='Project'", "project IS NOT NULL", "project<>''", "person=%s", "active=1", "(valid_from IS NULL OR valid_from<=%s)", "(valid_until IS NULL OR valid_until>=%s)"], [actor.person_id, nowdate(), nowdate()]
    if company is not None:
        conditions.append("company=%s")
        args.append(company)
    if project is not None:
        conditions.append("project=%s")
        args.append(project)
    return frappe.db.sql(
        "SELECT name,person,company,project,ability,modified,valid_from,valid_until FROM `tabCipher Project Duty` WHERE "
        + " AND ".join(conditions) + " ORDER BY name" + (" FOR UPDATE" if lock else ""), args, as_dict=True,
    )


def project_ids(actor, company=None, ability="project.read"):
    return sorted({row.project for row in duty_rows(actor, company) if row.ability == ability})


def require_project(company, project, ability="project.read", actor=None, lock=False):
    company = text(company, "Company")
    project = text(project, "Project")
    if ability not in PROJECT_ABILITIES:
        raise DomainError("unknown_capability", "This capability is not available.", 403)
    actor = actor or current_actor()
    # Refresh identity on every effect/read boundary; callers cannot keep a revoked Actor alive.
    current = current_actor(actor.user, lock=lock)
    if current.person_id != actor.person_id:
        raise DomainError("identity_changed", "Your identity changed. Sign in again.", 403)
    try:
        record = frappe.get_doc("Project", project, for_update=lock)
    except frappe.DoesNotExistError:
        raise DomainError("not_found", "This project is not available.", 404) from None
    rows = duty_rows(actor, company, project, lock=lock)
    abilities = {row.ability for row in rows}
    if record.company != company or "project.read" not in abilities:
        raise DomainError("not_found", "This project is not available.", 404)
    if ability not in abilities:
        raise DomainError("capability_denied", "Your current project duties do not allow this action.", 403)
    if not frappe.has_permission("Project", ptype="read", doc=record, user=actor.user):
        raise DomainError("not_found", "This project is not available.", 404)
    return record


def authority_fingerprint(actor, company, project, lock=False):
    current_actor(actor.user, lock=lock)
    suffix = " FOR UPDATE" if lock else ""
    bindings = frappe.db.sql("SELECT name,modified,person FROM `tabCipher Identity Binding` WHERE user=%s AND active=1" + suffix, (actor.user,), as_dict=True)
    people = frappe.db.sql("SELECT name,modified,active FROM `tabCipher Person` WHERE name=%s" + suffix, (actor.person_id,), as_dict=True)
    binding = bindings[0] if bindings else {}
    person = people[0] if people else {}
    rows = duty_rows(actor, company, project, lock=lock)
    normalize = lambda row: {key: str(value) if value is not None else None for key, value in row.items()}
    return digest({"person": normalize(person or {}), "binding": normalize(binding or {}), "duties": [normalize(row) for row in rows]})


def assert_synthetic_site():
    if frappe.conf.get("cipher_site_mode") != "synthetic":
        raise DomainError("site_mode_unqualified", "This release requires an explicitly configured synthetic Cipher site.", 503)


def execution_quarantined():
    return frappe.conf.get("cipher_execution_quarantined", False) not in (False, None, 0, "0", "false")


def require_effects_enabled():
    assert_synthetic_site()
    if execution_quarantined():
        raise DomainError("execution_quarantined", "This restored workspace is read only until its execution authority is reconciled.", 503)


def session_authority_reference(actor=None):
    """An opaque reference, never the bearer cookie, for an interactive run."""
    actor = actor or current_actor()
    sid = getattr(frappe.session, "sid", None)
    if not sid or sid == "Guest" or frappe.session.user != actor.user:
        raise DomainError("interactive_session_required", "Start this run from your active signed-in session.", 401)
    reference = hashlib.sha256(sid.encode()).hexdigest()
    require_session_authority(actor, reference)
    return reference


def require_session_authority(actor, reference, lock=False):
    from frappe.sessions import get_expired_threshold
    from frappe.utils import get_datetime, now_datetime
    if not isinstance(reference, str) or len(reference) != 64:
        raise DomainError("session_revoked", "The session that authorized this run is no longer active.", 403)
    # Pinned R0 MariaDB runtime. No raw session token is persisted in a Ricky run.
    rows = frappe.db.sql("SELECT sessiondata FROM `tabSessions` WHERE user=%s AND SHA2(sid,256)=%s AND lastupdate>%s" + (" FOR UPDATE" if lock else ""), (actor.user, reference, get_expired_threshold()), as_dict=True)
    if len(rows) != 1:
        raise DomainError("session_revoked", "The session that authorized this run is no longer active.", 403)
    data = frappe.parse_json(rows[0].sessiondata or "{}")
    if data.get("session_end") and get_datetime(data["session_end"]) <= now_datetime():
        raise DomainError("session_revoked", "The session that authorized this run expired.", 403)
    current_actor(actor.user)


def company_duty_rows(actor, company=None, lock=False):
    """Exact Company duties; NULL Project never means all Projects."""
    conditions = ["scope_type='Company'", "(project IS NULL OR project='')", "person=%s", "active=1",
        "(valid_from IS NULL OR valid_from<=%s)", "(valid_until IS NULL OR valid_until>=%s)"]
    values = [actor.person_id, nowdate(), nowdate()]
    if company is not None:
        conditions.append("company=%s")
        values.append(text(company, "Company"))
    return frappe.db.sql("SELECT name,person,company,project,ability,modified,valid_from,valid_until FROM `tabCipher Project Duty` WHERE " + " AND ".join(conditions) + " ORDER BY name" + (" FOR UPDATE" if lock else ""), values, as_dict=True)


def company_ids(actor, ability="company.read"):
    return sorted({row.company for row in company_duty_rows(actor) if row.ability == ability})


def read_company_authority(user, company, ability="company.read"):
    """Fresh identity and exact Company duties, without caching or row locks.

    One row per binding preserves ambiguous identity refusal. EXISTS avoids
    multiplying identities for duplicate duties. Locking effects keep their
    existing Person/identity/Company/duty acquisition order.
    """
    user = user or frappe.session.user
    if not user or user == "Guest":
        raise DomainError("authentication_required", "Sign in to Cipher to continue.", 401)
    day = nowdate()
    duty = ("EXISTS (SELECT 1 FROM `tabCipher Project Duty` d WHERE d.person=b.person "
        "AND d.company=%s AND d.scope_type='Company' AND (d.project IS NULL OR d.project='') "
        "AND d.active=1 AND (d.valid_from IS NULL OR d.valid_from<=%s) "
        "AND (d.valid_until IS NULL OR d.valid_until>=%s) AND d.ability=%s)")
    rows = frappe.db.sql("SELECT b.name,b.person,p.display_name," + duty + " AS can_read," + duty + " AS can_act "
        "FROM `tabCipher Identity Binding` b JOIN `tabCipher Person` p ON p.name=b.person "
        "JOIN `tabUser` u ON u.name=b.user WHERE b.user=%s AND b.active=1 AND p.active=1 AND u.enabled=1 LIMIT 2",
        (company, day, day, "company.read", company, day, day, ability, user), as_dict=True)
    if len(rows) != 1:
        raise DomainError("identity_unavailable", "Your active Cipher identity is not configured.", 403)
    row = rows[0]
    return Actor(user=user, person_id=row.person, display_name=row.display_name), bool(row.can_read), bool(row.can_act)


def _company_permission_db():
    # frappe.db is a stable LocalProxy; bind the actual request DB object.
    local = getattr(frappe, "local", None)
    return getattr(local, "db", None) if local is not None else getattr(frappe, "db", None)


def _consume_company_native_read(doc, user, ptype):
    """Single-use duplicate check inside one guard's native permission call.

    Independent and nested guards run their own identity/duty SQL. A mismatch
    spends this lexical bridge and uses the ordinary hook's fresh SQL.
    """
    proof = _company_native_read.get()
    if proof is None or not proof["available"]:
        return None
    proof["available"] = False
    actor = proof["actor"]
    db = _company_permission_db()
    if (doc is not proof["document"] or getattr(doc, "doctype", None) != "Company"
            or doc.name != proof["company"] or user != proof["user"] or ptype != "read"
            or actor.user != proof["user"] or actor.person_id != proof["person"]
            or nowdate() != proof["day"] or proof["db"] is not db
            or type(proof["writes"]) is not int
            or getattr(db, "transaction_writes", None) != proof["writes"]):
        return None
    return True


def require_company(company, ability="company.read", actor=None, lock=False):
    # A nested guard cannot consume the outer bridge while looking up its
    # identity/Company or checking its own locking native permissions.
    token = _company_native_read.set(None)
    try:
        return _require_company(company, ability, actor, lock)
    finally:
        _company_native_read.reset(token)


def _require_company(company, ability, actor, lock):
    company = text(company, "Company")
    if ability not in COMPANY_ABILITIES:
        raise DomainError("unknown_capability", "This Company capability is not available.", 403)
    if lock:
        actor = actor or current_actor()
        current = current_actor(actor.user, lock=True)
    else:
        day = nowdate()
        read_db = _company_permission_db()
        read_writes = getattr(read_db, "transaction_writes", None)
        current, can_read, can_act = read_company_authority(actor.user if actor else None, company, ability)
        actor = actor or current
    if current.person_id != actor.person_id:
        raise DomainError("identity_changed", "Your identity changed. Sign in again.", 403)
    try:
        record = frappe.get_doc("Company", company, for_update=lock)
    except frappe.DoesNotExistError:
        raise DomainError("not_found", "This Company is not available.", 404) from None
    if lock:
        abilities = {row.ability for row in company_duty_rows(actor, company, lock=True)}
        can_read, can_act = "company.read" in abilities, ability in abilities
    if not can_read:
        raise DomainError("not_found", "This Company is not available.", 404)
    if not can_act:
        raise DomainError("capability_denied", "Your current Company duties do not allow this action.", 403)
    if lock:
        native_allowed = frappe.has_permission("Company", ptype="read", doc=record, user=actor.user)
    else:
        proof = {"document": record, "company": company, "actor": actor, "user": current.user,
            "person": current.person_id, "day": day, "db": read_db, "writes": read_writes, "available": True}
        token = _company_native_read.set(proof)
        try:
            # Native roles/UserPermission/meta/share checks still run. Only
            # their duplicate Cipher SQL hook can use this same call's
            # successful exact company.read result.
            native_allowed = frappe.has_permission("Company", ptype="read", doc=record, user=actor.user)
        finally:
            proof["available"] = False
            _company_native_read.reset(token)
    if not native_allowed:
        raise DomainError("not_found", "This Company is not available.", 404)
    return record


def company_authority_fingerprint(actor, company, lock=False):
    current_actor(actor.user, lock=lock)
    suffix = " FOR UPDATE" if lock else ""
    bindings = frappe.db.sql("SELECT name,modified,person FROM `tabCipher Identity Binding` WHERE user=%s AND active=1" + suffix, (actor.user,), as_dict=True)
    people = frappe.db.sql("SELECT name,modified,active FROM `tabCipher Person` WHERE name=%s" + suffix, (actor.person_id,), as_dict=True)
    normalize = lambda row: {key: str(value) if value is not None else None for key, value in row.items()}
    return digest({"scope_type": "Company", "company": company, "person": normalize(people[0] if people else {}), "binding": normalize(bindings[0] if bindings else {}), "duties": [normalize(row) for row in company_duty_rows(actor, company, lock=lock)]})
