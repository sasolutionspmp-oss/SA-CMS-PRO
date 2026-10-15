"""Real declared owner sources with independent synthetic human duties."""
import inspect
import unittest

from apps.cipher.ar_practice_fixture import (make_ar_practice_fixture, BOOTSTRAP_LOGIN, PM_LOGIN,
    REVIEWER_LOGIN, POSTER_LOGIN, CONTROLLER_LOGIN, INACTIVE_LOGIN)
from apps.cipher.ar_sessions import authority_for, ARIdentityRefusal


class ARPracticeFixtureTests(unittest.TestCase):
    def setUp(self):
        self.c=make_ar_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.r=self.c.ar_practice_records
        self.domain=self.c.plugin("owner_billing")

    def test_basis_prime_terms_and_close_values_are_genuine_and_no_bill_or_finance_is_inferred(self):
        self.assertTrue(self.c.db.in_memory)
        self.assertEqual(self.c.db.mode_status()["mode"],"practice")
        self.assertEqual(self.c.receivables.contract(self.r["project_id"])["contract_value"],"250000.00")
        self.assertEqual(self.c.plugin("close").contract_value(self.r["project_id"])["contract_value"],"250000.00")
        self.assertEqual(self.c.receivables.payment_terms(self.r["customer_id"])["days"],30)
        self.assertEqual(self.c.receivables.billing_recipients(self.r["customer_id"])["recipients"],["owner-billing@synthetic-owner.invalid"])
        bases=self.domain.basis_inventory(project_ids=(self.r["project_id"],))
        self.assertEqual([basis["record"]["id"] for basis in bases],[self.r["basis_id"]])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM prime_bills"),0)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM commitments"),0)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"),0)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM outbox"),0)
        self.assertEqual(tuple(self.c.provider.submissions),())
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_agreement_claim_and_review_are_separate_owned_current_original_sources(self):
        source=[]
        for field,kind in (("contract_revision_id","owner_agreement"),("claim_revision_id","owner_claim"),("review_revision_id","owner_certification")):
            revision=self.c.evidence.revision(self.r[field]);document=self.c.evidence.document(revision["document_id"])
            self.assertEqual(document["project_id"],self.r["project_id"])
            self.assertEqual(document["kind"],kind)
            self.assertTrue(revision["is_current"])
            source.append(document["id"])
        self.assertEqual(len(set(source)),3)
        self.assertNotEqual(self.r["claim_revision_id"],self.r["review_revision_id"])
        self.assertEqual(self.c.ledger.period(self.r["period_id"])["start_date"],"2026-10-01")

    def test_personas_are_actual_owned_separate_people_and_hidden_project_is_filtered_before_aggregate(self):
        people=self.c.plugin("people")
        expected={"preparer":(PM_LOGIN,"pm"),"reviewer":(REVIEWER_LOGIN,"accounting"),
                  "poster":(POSTER_LOGIN,"accounting"),"controller":(CONTROLLER_LOGIN,"accounting")}
        ids=[]
        for key,(login,duty) in expected.items():
            mapping=self.c.ar_practice_persona_people[key]
            self.assertEqual(mapping["person_id"],people.person_for(login)["id"])
            current=authority_for(self.c,mapping["person_id"],persona_id=key)
            self.assertTrue(current.allows(self.r["project_id"],duty))
            self.assertNotIn(self.r["hidden_project_id"],current.project_ids)
            ids.append(mapping["person_id"])
        self.assertEqual(len(set(ids)),4)
        self.assertEqual(authority_for(self.c,people.person_for(BOOTSTRAP_LOGIN)["id"]).project_ids,())
        with self.assertRaises(ARIdentityRefusal):authority_for(self.c,people.person_for(INACTIVE_LOGIN)["id"])
        with self.assertRaises(TypeError):self.c.ar_practice_persona_people["preparer"]["person_id"]="replacement"
        self.assertFalse(hasattr(self.c,"ap_practice_persona_people"))
        self.assertFalse(hasattr(self.c,"commercial_practice_persona_people"))

    def test_factory_selects_no_file_provider_policy_actor_or_existing_workspace(self):
        self.assertEqual(tuple(inspect.signature(make_ar_practice_fixture).parameters),())
        other=make_ar_practice_fixture()
        try:
            self.assertNotEqual(other.db.mode_status()["workspace_id"],self.c.db.mode_status()["workspace_id"])
            self.assertNotEqual(other.ar_practice_records["basis_id"],self.r["basis_id"])
        finally:other.db.close()


if __name__=="__main__":unittest.main()
