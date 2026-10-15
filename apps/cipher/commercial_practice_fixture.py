"""Owned disposable commercial fixture with audited project people and sources.

No provider, journal, accounting mapping, budget adoption or customer issue is
performed. Native source wrappers seed two manual synthetic revisions and an
explicit audited PM package declaration before acceptance or handoff.
"""
from types import MappingProxyType

from apps.cipher.service import Cipher


BOOTSTRAP_LOGIN = "practice.commercial.bootstrap"
ESTIMATOR_LOGIN = "practice.estimator"
REVIEWER_LOGIN = "practice.estimate.reviewer"
PM_LOGIN = "practice.commercial.pm"
HIDDEN_ESTIMATOR_LOGIN = "practice.hidden.estimator"
ACCOUNTANT_LOGIN = "practice.commercial.accountant"


def make_commercial_practice_fixture():
    c = Cipher(":memory:")
    try:
        commercial = c.plugin("commercial")
        people = c.plugin("people")
        people.bootstrap_owner(BOOTSTRAP_LOGIN, "Commercial setup owner (synthetic)")
        for login, display in ((ESTIMATOR_LOGIN, "Estimate preparer (synthetic)"),
                               (REVIEWER_LOGIN, "Independent estimate reviewer (synthetic)"),
                               (PM_LOGIN, "Subcontract project manager (synthetic)"),
                               (HIDDEN_ESTIMATOR_LOGIN, "Hidden estimate preparer (synthetic)"),
                               (ACCOUNTANT_LOGIN, "Accounting control case (synthetic)")):
            people.register_person(login, display, actor=BOOTSTRAP_LOGIN)
        project = c.create_project(name="Synthetic manual estimating project", entity="Synthetic commercial entity",
                                   budget="100000.00", actor=BOOTSTRAP_LOGIN)
        hidden = c.create_project(name="Hidden synthetic estimating project", entity="Synthetic commercial entity",
                                  budget="50000.00", actor=BOOTSTRAP_LOGIN)

        def govern(operation, subject):
            requested = c.request_approval(operation, subject, actor_role="owner", requested_by=BOOTSTRAP_LOGIN)
            c.approve(requested["id"], approver=BOOTSTRAP_LOGIN, approver_role="owner")
            return c.execute(requested["id"], actor=BOOTSTRAP_LOGIN)

        for login, role, scope in ((ESTIMATOR_LOGIN, "estimator", project["id"]),
                                   (REVIEWER_LOGIN, "estimator", project["id"]),
                                   (PM_LOGIN, "pm", project["id"]),
                                   (ACCOUNTANT_LOGIN, "accountant", project["id"]),
                                   (HIDDEN_ESTIMATOR_LOGIN, "estimator", hidden["id"])):
            people.add_membership(login, scope, actor=BOOTSTRAP_LOGIN)
            request = people.request_grant(login, role, project_id=scope, reason="Synthetic commercial project assignment", actor=BOOTSTRAP_LOGIN)
            govern("people.grant_role", request["id"])
        policy = people.prepare_policy(enforce=True, segregate=True, solo_owner_self_approval=False,
                                       reason="Synthetic independent estimator acceptance", actor=BOOTSTRAP_LOGIN)
        govern("people.set_policy", policy["id"])
        document = c.evidence.register_document(project_id=project["id"], kind="drawing",
            title="Synthetic manual piping drawing A-101", actor=ESTIMATOR_LOGIN)
        first_revision = c.evidence.add_revision(document_id=document["id"], content="Synthetic A-101 revision 1: manual quantity 10 LF and 4 EA",
            note="Owned synthetic source; no geometry measurement or calibrated CAD scale", actor=ESTIMATOR_LOGIN)
        first_input = {"documentRevisionId": first_revision["id"], "lines": [
            {"description": "Manual piping installation", "quantity": "10", "unit": "LF", "unitPriceCents": 2500,
             "sourceLocator": "A-101, piping plan", "costCode": "33-110"},
            {"description": "Manual pipe sleeves", "quantity": "4", "unit": "EA", "unitPriceCents": 5000,
             "sourceLocator": "A-101, sleeve schedule", "costCode": "33-120"}],
            "priceBookRef": "Synthetic fixed practice rates v1", "inclusions": ["Piping installation", "Pipe sleeves"],
            "exclusions": ["Excavation"], "contingencyRate": "0",
            "measurementBasis": "Manual synthetic source quantities; geometry and calibrated scale unverified"}
        first = commercial.create(project["id"], first_input, actor=ESTIMATOR_LOGIN)
        second_revision = c.evidence.add_revision(document_id=document["id"], content="Synthetic A-101 revision 2: manual quantity 12 LF and 4 EA",
            note="Owned synthetic source; manual quantity changed from 10 LF to 12 LF", actor=ESTIMATOR_LOGIN)
        second_input = {**first_input, "documentRevisionId": second_revision["id"], "removedExclusions": [],
                        "lines": [{**line, "quantity": "12" if index == 0 else "4",
                                   "previousLineId": first["lines"][index]["estimate_line_id"]}
                                  for index, line in enumerate(first_input["lines"])]}
        second = commercial.revise(first["estimateId"], second_input, actor=ESTIMATOR_LOGIN)
        hidden_doc = c.evidence.register_document(project_id=hidden["id"], kind="drawing", title="Hidden synthetic source", actor=HIDDEN_ESTIMATOR_LOGIN)
        hidden_rev = c.evidence.add_revision(document_id=hidden_doc["id"], content="Hidden synthetic manual source", actor=HIDDEN_ESTIMATOR_LOGIN)
        hidden_estimate = commercial.create(hidden["id"], {
            "documentRevisionId": hidden_rev["id"], "lines": [{"description": "Hidden manual scope", "quantity": "1", "unit": "LS",
            "unitPriceCents": 10000, "sourceLocator": "Hidden drawing, manual scope", "costCode": "99-000"}],
            "priceBookRef": None, "inclusions": ["Hidden manual scope"], "exclusions": [], "contingencyRate": "0",
            "measurementBasis": "Manual synthetic hidden source; geometry unverified"}, actor=HIDDEN_ESTIMATOR_LOGIN)
        supplier = c.add_party(kind="supplier", name="Synthetic piping subcontractor", destination="SIM-COMMERCIAL-NO-DELIVERY", actor=BOOTSTRAP_LOGIN)
        package = commercial.declare_package(project["id"], supplier["id"], "Synthetic source-preserving piping subcontract", "0.10",
            actor=PM_LOGIN, reason="Explicit synthetic all-line piping package and ten percent retainage; no owner default adopted")
        persona_people = {key: MappingProxyType({"person_id": people.person_for(login)["id"], "login": login})
                          for key, login in (("preparer", ESTIMATOR_LOGIN), ("reviewer", REVIEWER_LOGIN), ("pm", PM_LOGIN))}
        c.commercial_practice_persona_people = MappingProxyType(persona_people)
        c.commercial_practice_personas = tuple(MappingProxyType({"personaId": key, "displayName": people.person_for(value["login"])["display_name"], "synthetic": True})
                                                for key, value in persona_people.items())
        c.commercial_practice_records = MappingProxyType({"project_id": project["id"], "hidden_project_id": hidden["id"],
            "drawing_id": document["id"], "first_drawing_revision_id": first_revision["id"], "current_drawing_revision_id": second_revision["id"],
            "superseded_estimate_id": first["estimateId"], "current_estimate_id": second["estimateId"], "hidden_estimate_id": hidden_estimate["estimateId"],
            "supplier_id": supplier["id"], "package_id": package["id"]})
        # All manual source sidecars were created in their original estimate
        # transactions. The fixed handoff terms are a separate audited PM act.
        return c
    except BaseException:
        c.db.close()
        raise
