"""Explicit, separate Administrator preparation for the UNRUN FLD02 native suite.

Proposed destination: cipher_aec/tests/fld02_native_fixture.py. The operator must
prepare this fixture before the test runner, using its normal outer transaction.
This module never creates a Company, changes schema, seeds the application,
commits, returns passwords, or grants duties. Tests call only verify_fixture().
"""
from copy import deepcopy
import secrets

import frappe

from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import assert_synthetic_site, current_actor, trusted_write
from cipher_aec.install import _binding, _person, _user

COMPANY = "Cipher Synthetic Company"
PEOPLE = {
    "owner": "CIPHER-FLD02-PERSON-OWNER",
    "reviewer": "CIPHER-FLD02-PERSON-REVIEWER",
    "outsider": "CIPHER-FLD02-PERSON-OUTSIDER",
}
USERS = {
    "owner": {"user": "fld02.owner@synthetic.example", "person": PEOPLE["owner"]},
    "alias": {"user": "fld02.alias@synthetic.example", "person": PEOPLE["owner"]},
    "reviewer": {"user": "fld02.reviewer@synthetic.example", "person": PEOPLE["reviewer"]},
    "outsider": {"user": "fld02.outsider@synthetic.example", "person": PEOPLE["outsider"]},
}


def _required(condition, message):
    if not condition:
        raise DomainError("fld02_fixture_required", message, 503)


def _installed_prerequisites():
    assert_synthetic_site()
    _required(frappe.db.exists("Company", COMPANY), "Install the synthetic Company before preparing FLD02 identities.")
    _required(frappe.db.exists("Role", "Cipher User"), "Install cipher_aec before preparing FLD02 identities.")
    _required(frappe.db.exists("User", "Administrator"), "The installed Administrator is required.")
    administrator = current_actor("Administrator")
    _required(administrator.person_id == "CIPHER-PERSON-ADMIN", "The installed synthetic Administrator binding is required.")


def _no_default_duties():
    for person in PEOPLE.values():
        _required(
            not frappe.db.exists("Cipher Project Duty", {"person": person}),
            "Dedicated FLD02 fixture identities must start without Company or Project duties.",
        )


def prepare_fixture():
    """Administrator-only pre-suite operation; never invoked by a test lifecycle."""
    _required(frappe.session.user == "Administrator", "Only Administrator may prepare the FLD02 fixture.")
    _installed_prerequisites()
    _no_default_duties()
    with trusted_write():
        for key, person in PEOPLE.items():
            _person(person, "FLD02 synthetic " + key)
        for key, identity in USERS.items():
            # Existing identities retain their password; new users get independent,
            # random, nonreturned credentials, never an environment/shared default.
            password = None if frappe.db.exists("User", identity["user"]) else secrets.token_urlsafe(40)
            _user(identity["user"], "FLD02 " + key, password)
            _binding(identity["user"], identity["person"])
    return verify_fixture()


def verify_fixture():
    """Read-only prerequisite verification; fail rather than provisioning in tests."""
    _installed_prerequisites()
    _no_default_duties()
    for key, identity in USERS.items():
        row = frappe.db.get_value("User", identity["user"], ["enabled", "user_type"], as_dict=True)
        _required(row and row.enabled == 1 and row.user_type == "System User", "Prepare the dedicated enabled FLD02 " + key + " user.")
        _required("Cipher User" in frappe.get_roles(identity["user"]), "The dedicated FLD02 user requires its installed Cipher User role.")
        actor = current_actor(identity["user"])
        _required(actor.person_id == identity["person"], "The dedicated FLD02 identity binding differs from the declared fixture.")
        bindings = frappe.get_all("Cipher Identity Binding", filters={"user": identity["user"]}, fields=["name", "person", "active"])
        _required(len(bindings) == 1 and bindings[0].person == identity["person"] and bindings[0].active == 1, "Prepare one exact active FLD02 identity binding per login.")
    return {"company": COMPANY, "users": deepcopy(USERS), "site_mode": "synthetic"}
