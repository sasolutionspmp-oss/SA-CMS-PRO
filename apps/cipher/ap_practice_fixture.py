"""Genuine, disposable AP records and registered synthetic human duties.

Every grant and business approval is created through Cipher.  This fixture is a
practice duty scenario; it does not adopt business limits or connect identities.
"""
from __future__ import annotations

from types import MappingProxyType

from .service import Cipher


BOOTSTRAP_LOGIN = "practice.bootstrap"
ACCOUNTANT_LOGIN = "practice.accountant"
PM_LOGIN = "practice.pm"
HIDDEN_ACCOUNTANT_LOGIN = "practice.hidden.accountant"
HIDDEN_PM_LOGIN = "practice.hidden.pm"


def make_ap_practice_fixture() -> Cipher:
    """Own a fresh memory workspace with two visible jobs and one hidden job."""
    c = Cipher(":memory:")
    try:
        people = c.plugin("people")
        people.bootstrap_owner(BOOTSTRAP_LOGIN, "Practice bootstrap owner (synthetic)")
        for login, name in (
            (ACCOUNTANT_LOGIN, "Alex Rivera (synthetic accountant)"),
            (PM_LOGIN, "Morgan Lee (synthetic project manager)"),
            (HIDDEN_ACCOUNTANT_LOGIN, "Hidden project accountant (synthetic)"),
            (HIDDEN_PM_LOGIN, "Hidden project manager (synthetic)"),
        ):
            people.register_person(login, name, actor=BOOTSTRAP_LOGIN)

        projects = [c.create_project(name=name, entity="S&A Solutions LLC (synthetic)", budget=budget,
                                     actor=BOOTSTRAP_LOGIN) for name, budget in (
            ("Synthetic water treatment upgrade", "250000.00"),
            ("Synthetic bridge rehabilitation", "180000.00"),
            ("Hidden synthetic infrastructure project", "990000.00"),
        )]
        c.open_period("2026-10", "October 2026", "2026-10-01", "2026-10-31", actor=BOOTSTRAP_LOGIN)
        c.open_period("2026-11", "November 2026", "2026-11-01", "2026-11-30", actor=BOOTSTRAP_LOGIN)

        def govern(operation, subject):
            approval = c.request_approval(operation, subject, actor_role="owner", requested_by=BOOTSTRAP_LOGIN)
            c.approve(approval["id"], approver=BOOTSTRAP_LOGIN, approver_role="owner")
            return c.execute(approval["id"], actor=BOOTSTRAP_LOGIN)

        for index, project in enumerate(projects):
            team = ((ACCOUNTANT_LOGIN, "accountant"), (PM_LOGIN, "pm")) if index < 2 else (
                (HIDDEN_ACCOUNTANT_LOGIN, "accountant"), (HIDDEN_PM_LOGIN, "pm"))
            for login, duty in team:
                people.add_membership(login, project["id"], actor=BOOTSTRAP_LOGIN)
                request = people.request_grant(login, duty, project_id=project["id"],
                                               reason="Synthetic AP project assignment", actor=BOOTSTRAP_LOGIN)
                govern("people.grant_role", request["id"])

        commitments = []
        for project, (supplier_name, title, description, amount) in zip(projects, (
            ("Synthetic site piping subcontractor", "Site piping subcontract", "Site piping installation", "100000.00"),
            ("Synthetic structural subcontractor", "Bridge repair subcontract", "Structural repair", "80000.00"),
            ("Hidden synthetic subcontractor", "Hidden infrastructure subcontract", "Hidden installed work", "500000.00"),
        )):
            supplier = c.add_party(kind="supplier", name=supplier_name, destination="SIM-PRACTICE-NO-DELIVERY",
                                   actor=BOOTSTRAP_LOGIN)
            commitment = c.commitments.create(project_id=project["id"], supplier_id=supplier["id"], title=title,
                                               sov_lines=[{"description": description, "cost_code": "03-000", "amount": amount}],
                                               retainage_rate="0.10", actor=BOOTSTRAP_LOGIN)
            govern("commitment.execute", commitment["id"])
            commitments.append(c.commitments.get(commitment["id"]))

        policy = people.prepare_policy(enforce=True, segregate=True, solo_owner_self_approval=False,
                                       reason="Synthetic distinct AP business and accounting duties", actor=BOOTSTRAP_LOGIN)
        govern("people.set_policy", policy["id"])

        bills = []
        for index, (commitment, installed) in enumerate(zip(commitments, ("12345.67", "23456.78", "98765.43"))):
            accountant = ACCOUNTANT_LOGIN if index < 2 else HIDDEN_ACCOUNTANT_LOGIN
            bill = c.bills.certify(commitment_id=commitment["id"], period_id="2026-10",
                                   installed=[{"sov_line_id": commitment["sov"][0]["id"], "cumulative_installed": installed}],
                                   actor=accountant)
            if index > 0:
                pm = PM_LOGIN if index == 1 else HIDDEN_PM_LOGIN
                approval = c.request_approval("bill.approve", bill["id"], actor_role="accountant", requested_by=accountant)
                c.approve(approval["id"], approver=pm, approver_role="pm")
            bills.append(c.bills.get(bill["id"]))

        persona_people = {
            persona: MappingProxyType({"person_id": people.person_for(login)["id"], "login": login})
            for persona, login in (("accountant", ACCOUNTANT_LOGIN), ("pm", PM_LOGIN))
        }
        c.ap_practice_persona_people = MappingProxyType(persona_people)
        c.ap_practice_personas = tuple(MappingProxyType({
            "personaId": persona, "displayName": people.person_for(person["login"])["display_name"], "synthetic": True,
        }) for persona, person in persona_people.items())
        c.ap_practice_records = MappingProxyType({
            "visible_project_ids": tuple(project["id"] for project in projects[:2]),
            "hidden_project_id": projects[2]["id"],
            "visible_commitment_ids": tuple(commitment["id"] for commitment in commitments[:2]),
            "hidden_commitment_id": commitments[2]["id"],
            "draft_bill_id": bills[0]["id"], "approved_bill_id": bills[1]["id"], "hidden_bill_id": bills[2]["id"],
            "period_ids": ("2026-10", "2026-11"),
        })
        return c
    except BaseException:
        c.db.close()
        raise
