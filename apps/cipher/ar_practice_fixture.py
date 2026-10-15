"""Fresh declared owner-billing sources and actual synthetic project duties.

All setup is local, audited practice evidence. An owner SOV declaration does not
claim a customer award, signed agreement or external engineer certification.
"""
from __future__ import annotations

from types import MappingProxyType

from .service import Cipher


BOOTSTRAP_LOGIN = "practice.ar.bootstrap"
PM_LOGIN = "practice.ar.pm"
REVIEWER_LOGIN = "practice.ar.reviewer"
POSTER_LOGIN = "practice.ar.poster"
CONTROLLER_LOGIN = "practice.ar.controller"
HIDDEN_PM_LOGIN = "practice.ar.hidden.pm"
HIDDEN_REVIEWER_LOGIN = "practice.ar.hidden.reviewer"
HIDDEN_POSTER_LOGIN = "practice.ar.hidden.poster"
INACTIVE_LOGIN = "practice.ar.inactive"


def make_ar_practice_fixture() -> Cipher:
    """Own one visible and one hidden project in a fresh memory workspace."""
    from .domain.owner_billing import register_owner_billing_schema
    register_owner_billing_schema()
    c = Cipher(":memory:")
    try:
        billing = c.plugin("owner_billing")
        people = c.plugin("people")
        people.bootstrap_owner(BOOTSTRAP_LOGIN, "AR setup owner (synthetic)")
        for login, display in (
            (PM_LOGIN, "Owner pay-app preparer (synthetic PM)"),
            (REVIEWER_LOGIN, "Independent AR reviewer (synthetic accountant)"),
            (POSTER_LOGIN, "AR posting accountant (synthetic)"),
            (CONTROLLER_LOGIN, "AR controller (synthetic)"),
            (HIDDEN_PM_LOGIN, "Hidden owner pay-app PM (synthetic)"),
            (HIDDEN_REVIEWER_LOGIN, "Hidden AR reviewer (synthetic)"),
            (HIDDEN_POSTER_LOGIN, "Hidden AR poster (synthetic)"),
            (INACTIVE_LOGIN, "Departed AR accountant (synthetic)"),
        ):
            people.register_person(login, display, actor=BOOTSTRAP_LOGIN)

        customers, projects = [], []
        for hidden in (False, True):
            label = "Hidden synthetic" if hidden else "Synthetic"
            customer = c.add_party(kind="customer", name=label + " owner agency", actor=BOOTSTRAP_LOGIN)
            project = c.create_project(name=label + " owner infrastructure project", entity="Synthetic AR entity",
                budget="200000.00", customer_id=customer["id"], actor=BOOTSTRAP_LOGIN)
            customers.append(customer)
            projects.append(project)
        c.open_period("2026-10", "October 2026", "2026-10-01", "2026-10-31", actor=BOOTSTRAP_LOGIN)
        c.open_period("2026-11", "November 2026", "2026-11-01", "2026-11-30", actor=BOOTSTRAP_LOGIN)

        def govern(operation, subject):
            request = c.request_approval(operation, subject, actor_role="owner", requested_by=BOOTSTRAP_LOGIN)
            c.approve(request["id"], approver=BOOTSTRAP_LOGIN, approver_role="owner")
            return c.execute(request["id"], actor=BOOTSTRAP_LOGIN)

        assignments = (
            (PM_LOGIN, "pm", projects[0]["id"]),
            (REVIEWER_LOGIN, "accountant", projects[0]["id"]),
            (POSTER_LOGIN, "accountant", projects[0]["id"]),
            (CONTROLLER_LOGIN, "controller", projects[0]["id"]),
            (INACTIVE_LOGIN, "accountant", projects[0]["id"]),
            (HIDDEN_PM_LOGIN, "pm", projects[1]["id"]),
            (HIDDEN_REVIEWER_LOGIN, "accountant", projects[1]["id"]),
            (HIDDEN_POSTER_LOGIN, "accountant", projects[1]["id"]),
        )
        for login, duty, project_id in assignments:
            people.add_membership(login, project_id, actor=BOOTSTRAP_LOGIN)
            request = people.request_grant(login, duty, project_id=project_id,
                reason="Synthetic owner-billing project assignment", actor=BOOTSTRAP_LOGIN)
            govern("people.grant_role", request["id"])
        policy = people.prepare_policy(enforce=True, segregate=True, solo_owner_self_approval=False,
            reason="Synthetic independent owner-billing review and posting", actor=BOOTSTRAP_LOGIN)
        govern("people.set_policy", policy["id"])
        people.deactivate_person(INACTIVE_LOGIN, reason="Synthetic departed AR staff control case", actor=BOOTSTRAP_LOGIN)

        sources = []
        for index, (project, customer) in enumerate(zip(projects, customers)):
            pm = PM_LOGIN if index == 0 else HIDDEN_PM_LOGIN
            c.receivables.set_prime_contract(project["id"], "250000.00", "0.10", actor=pm)
            c.receivables.set_customer_terms(customer["id"], 30, actor=pm)
            c.receivables.set_billing_recipients(customer["id"],
                ["owner-billing@synthetic-owner.invalid" if index == 0 else "hidden-billing@synthetic-owner.invalid"], actor=pm)
            c.plugin("close").set_contract_value(project["id"], "250000.00", actor=pm,
                note="Explicit synthetic owner basis only; not a signed contract or operational adoption")
            revisions = {}
            for kind, title, content in (
                ("owner_agreement", "Declared synthetic owner contract and full SOV",
                 "Synthetic declared owner SOV U1:100 EA at $1,000; L2:lump sum $150,000. No external award or signature asserted."),
                ("owner_claim", "Synthetic owner pay-app claimed progress",
                 "Synthetic manually claimed progress: U1 12 EA, L2 $15,000 cumulative. No geometry or external certification asserted."),
                ("owner_certification", "Synthetic PM-reviewed owner pay-app progress",
                 "Synthetic manually reviewed progress: U1 10 EA, L2 $12,500 cumulative; differences retain separate source locators and reasons."),
            ):
                document = c.evidence.register_document(project_id=project["id"], kind=kind,
                    title=("Hidden " if index else "") + title, actor=pm)
                revision = c.evidence.add_revision(document_id=document["id"], content=content,
                    note="Owned synthetic original source; no uploaded business record", actor=pm)
                revisions[kind] = {"document_id": document["id"], "revision_id": revision["id"]}
            basis = billing.declare_practice_basis(project["id"],
                contract_revision_id=revisions["owner_agreement"]["revision_id"], actor=pm)
            sources.append({"basis_id": basis["id"], "project_id": project["id"], "customer_id": customer["id"],
                "contract_revision_id": revisions["owner_agreement"]["revision_id"],
                "claim_revision_id": revisions["owner_claim"]["revision_id"],
                "review_revision_id": revisions["owner_certification"]["revision_id"]})

        persona_people = {key: MappingProxyType({"person_id": people.person_for(login)["id"], "login": login})
            for key, login in (("preparer", PM_LOGIN), ("reviewer", REVIEWER_LOGIN),
                               ("poster", POSTER_LOGIN), ("controller", CONTROLLER_LOGIN))}
        c.ar_practice_persona_people = MappingProxyType(persona_people)
        c.ar_practice_personas = tuple(MappingProxyType({"personaId": key,
            "displayName": people.person_for(value["login"])["display_name"], "synthetic": True})
            for key, value in persona_people.items())
        c.ar_practice_records = MappingProxyType({**sources[0], "visible_project_ids": (projects[0]["id"],),
            "hidden_project_id": projects[1]["id"], "hidden_basis_id": sources[1]["basis_id"],
            "hidden_claim_revision_id": sources[1]["claim_revision_id"],
            "hidden_review_revision_id": sources[1]["review_revision_id"], "period_id": "2026-10"})
        return c
    except BaseException:
        c.db.close()
        raise
