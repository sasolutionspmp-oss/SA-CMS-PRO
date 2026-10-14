"""Read-only bill checks shared by AP review and consequential service acts."""
import datetime
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APContract, APRefusal
from apps.cipher.ap_preflight import APPreflight
from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
from apps.cipher.core.ids import utcnow
from apps.cipher.tests import test_bill_service_split as fixtures
from apps.cipher.tests import test_contracts as contract_fixtures
from apps.cipher.tests import test_people as people_fixtures


class SharedAPPreflightTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BillServiceSplitTests("test_grant_records_approved_state_without_journal")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.c, self.bill = self.fixture.c, self.fixture.bill

    def snapshot(self):
        return ("\n".join(self.c.db.conn.iterdump()), self.c.db.conn.total_changes,
                list(self.c.provider.submissions))

    def test_request_review_checks_the_same_manifest_without_writes(self):
        before = self.snapshot()
        manifest = self.c.check_request_approval("bill.approve", self.bill["id"],
                                                 actor_role="accountant", requested_by="poster")
        self.assertEqual(manifest["actor_role"], "pm")
        self.assertEqual(self.snapshot(), before)

    def test_grant_review_leaves_pending_authorization_and_bill_unchanged(self):
        approval = self.fixture.request()
        before = self.snapshot()
        checked = self.c.check_approval_grant(approval["id"], approver="reviewer", approver_role="pm")
        self.assertEqual(checked["approval"]["status"], "pending")
        self.assertEqual(self.snapshot(), before)

    def test_post_review_checks_exact_plan_and_cross_period_reason_without_writes(self):
        self.fixture.grant()
        before = self.snapshot()
        checked = self.c.check_bill_posting(self.bill["id"], actor="poster", period_id="P2", reason="Late invoice")
        self.assertEqual(checked["plan"], self.c.bills.journal_preview(self.bill["id"], period_id="P2"))
        self.assertEqual(checked["reason"], "Late invoice")
        self.assertEqual(self.snapshot(), before)

    def test_required_coverage_selection_is_pure_and_actual_post_records_it_once(self):
        w = contract_fixtures.World()
        self.addCleanup(w.c.db.close)
        w.certificate(expiry=2)
        commitment_id = w.signed_commitment(requirements=[{"kind": "general_liability", "min_limit": "1000000"}])
        bill = w.certify(commitment_id)
        w.request_post(bill["id"])
        before = (tuple(w.c.db.conn.iterdump()), w.c.db.conn.total_changes)
        checked = w.c.check_bill_posting(bill["id"], actor="accountant", period_id="P1")
        self.assertTrue(checked["plan"])
        self.assertEqual((tuple(w.c.db.conn.iterdump()), w.c.db.conn.total_changes), before)
        self.assertEqual(w.c.db.scalar("SELECT COUNT(*) FROM contract_coverage_checks"), 0)
        w.c.post_bill(bill["id"], actor="accountant", period_id="P1")
        self.assertEqual(w.c.db.scalar("SELECT COUNT(*) FROM contract_coverage_checks"), 1)

    def test_expired_required_coverage_refuses_pure_post_check_without_writes(self):
        w = contract_fixtures.World()
        self.addCleanup(w.c.db.close)
        w.certificate(expiry=2)
        commitment_id = w.signed_commitment(requirements=[{"kind": "general_liability", "min_limit": "1000000"}])
        bill = w.certify(commitment_id)
        w.request_post(bill["id"])
        w.clock(3)
        before = (tuple(w.c.db.conn.iterdump()), w.c.db.conn.total_changes)
        with self.assertRaises(contract_fixtures.CoverageError):
            w.c.check_bill_posting(bill["id"], actor="accountant", period_id="P1")
        self.assertEqual((tuple(w.c.db.conn.iterdump()), w.c.db.conn.total_changes), before)


class APPreflightTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.records = self.c.ap_practice_records
        self.accountant = self.c.ap_practice_persona_people["accountant"]["person_id"]
        self.pm = self.c.ap_practice_persona_people["pm"]["person_id"]
        self.contract = APContract(self.c, secret=b"practice-preflight-private-test-key")
        self.preflight = APPreflight(self.c, self.contract, secret=b"practice-preflight-private-test-key")

    def snapshot(self):
        return (tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes,
                tuple(self.c.provider.submissions), dict(self.c.provider.transfers))

    def review_post(self, **body):
        return self.preflight.review(self.accountant, "bill.post", self.records["approved_bill_id"],
                                     {"periodId": "2026-10", "reason": "", **body})

    def test_request_and_post_positive_reviews_have_zero_writes(self):
        before = self.snapshot()
        request = self.preflight.review(self.accountant, "bill.requestApproval", self.records["draft_bill_id"], {})
        post = self.review_post()
        self.assertTrue(request["allowed"], request)
        self.assertTrue(post["allowed"], post)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(request["safeEffects"]["workingLedgerJournalDelta"], 0)
        self.assertEqual(request["safeEffects"]["apPayableDeltaCents"], 0)
        self.assertEqual(post["safeEffects"]["workingLedgerJournalDelta"], 1)
        lines = post["safeEffects"]["journalPreview"][0]["lines"]
        self.assertEqual(sum(line["debitCents"] for line in lines), sum(line["creditCents"] for line in lines))
        self.assertTrue(all(line["accountName"] for line in lines))

    def test_grant_review_matches_actual_journal_free_business_effect(self):
        request = self.c.request_approval("bill.approve", self.records["draft_bill_id"],
                                          actor_role="accountant", requested_by="practice.accountant")
        before = self.snapshot()
        review = self.preflight.review(self.pm, "bill.approve", request["id"], {})
        self.assertTrue(review["allowed"], review)
        self.assertEqual(self.snapshot(), before)
        self.preflight.verify(self.pm, "bill.approve", request["id"], {"fingerprint": review["fingerprint"]}, review["resourceVersion"])
        before_journals = self.c.db.scalar("SELECT COUNT(*) FROM journals")
        self.c.approve(request["id"], approver="practice.pm", approver_role="pm")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), before_journals)
        self.assertEqual(self.c.bills.open_payable(self.records["draft_bill_id"]), 0)

    def test_fresh_manifest_nonce_and_request_time_do_not_stale_fingerprint(self):
        first = self.preflight.review(self.accountant, "bill.requestApproval", self.records["draft_bill_id"], {})
        with patch("apps.cipher.core.approvals.utcnow", return_value=utcnow() + datetime.timedelta(minutes=5)):
            second = self.preflight.review(self.accountant, "bill.requestApproval", self.records["draft_bill_id"], {})
        self.assertEqual(first["resourceVersion"], second["resourceVersion"])
        self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_reason_and_period_are_bound_into_review_without_writes(self):
        first = self.review_post()
        later = self.review_post(periodId="2026-11", reason="Late invoice")
        self.assertTrue(later["allowed"], later)
        self.assertNotEqual(first["fingerprint"], later["fingerprint"])
        before = self.snapshot()
        with self.assertRaises(APRefusal) as failure:
            self.preflight.verify(self.accountant, "bill.post", self.records["approved_bill_id"],
                                  {"periodId": "2026-11", "reason": "Different reason", "fingerprint": later["fingerprint"]}, later["resourceVersion"])
        self.assertEqual(failure.exception.code, "preflight_changed")
        self.assertEqual(self.snapshot(), before)

    def test_closed_period_and_missing_cross_period_reason_are_zero_write_refusals(self):
        self.c.db.execute("UPDATE periods SET status='closed' WHERE id='2026-10'")
        before = self.snapshot()
        closed = self.review_post()
        missing_reason = self.review_post(periodId="2026-11")
        self.assertFalse(closed["allowed"])
        self.assertIsNone(closed["fingerprint"])
        self.assertEqual(closed["checks"][-1]["code"], "period_locked")
        self.assertEqual(missing_reason["checks"][-1]["code"], "posting_reason_required")
        self.assertEqual(self.snapshot(), before)

    def test_current_clock_expiry_blocks_even_when_version_does_not_change(self):
        review = self.review_post()
        bill = self.c.bills.get(self.records["approved_bill_id"])
        approval = self.c.approvals.get(bill["business_approval_id"])
        self.preflight.now = lambda: utcnow() + datetime.timedelta(days=2)
        before = self.snapshot()
        expired = self.review_post()
        self.assertEqual(expired["resourceVersion"], review["resourceVersion"])
        self.assertFalse(expired["allowed"])
        self.assertEqual(expired["checks"][-1]["code"], "approval_expired")
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "granted")
        self.assertEqual(self.snapshot(), before)

    def test_material_supplier_change_refuses_old_version_and_review(self):
        review = self.review_post()
        bill = self.c.bills.get(self.records["approved_bill_id"])
        self.c.db.execute("UPDATE parties SET name='Synthetic revised supplier' WHERE id=?", (bill["supplier_id"],))
        before = self.snapshot()
        changed = self.review_post()
        self.assertFalse(changed["allowed"])
        self.assertEqual(changed["checks"][-1]["code"], "approval_stale")
        with self.assertRaises(APRefusal):
            self.preflight.verify(self.accountant, "bill.post", bill["id"],
                                  {"periodId": "2026-10", "reason": "", "fingerprint": review["fingerprint"]}, review["resourceVersion"])
        self.assertEqual(self.snapshot(), before)

    def test_current_duplicate_request_and_wrong_duties_do_not_write(self):
        request = self.c.request_approval("bill.approve", self.records["draft_bill_id"],
                                          actor_role="accountant", requested_by="practice.accountant")
        before = self.snapshot()
        duplicate = self.preflight.review(self.accountant, "bill.requestApproval", self.records["draft_bill_id"], {})
        self.assertEqual(duplicate["checks"][-1]["code"], "duplicate_request")
        self.assertEqual(duplicate["checks"][-1]["target"], request["id"])
        for person, action, resource in ((self.accountant, "bill.approve", request["id"]),
                                          (self.pm, "bill.post", self.records["approved_bill_id"])):
            with self.subTest(action=action), self.assertRaises(APRefusal) as failure:
                self.preflight.review(person, action, resource, {})
            self.assertIn(failure.exception.status, (403, 422))
        self.assertEqual(self.snapshot(), before)

    def test_forged_identity_fields_and_other_project_ids_fail_closed(self):
        before = self.snapshot()
        for body in ({"actor": "practice.pm"}, {"role": "owner"}, {"mode": "live"}, {"provider": "real"}):
            with self.subTest(body=body), self.assertRaises(APRefusal):
                self.preflight.review(self.accountant, "bill.requestApproval", self.records["draft_bill_id"], body)
        with self.assertRaises(APRefusal) as failure:
            self.preflight.review(self.accountant, "bill.post", self.records["hidden_bill_id"], {"periodId": "2026-10", "reason": ""})
        self.assertEqual(failure.exception.status, 404)
        self.assertEqual(self.snapshot(), before)

    def test_modified_fingerprint_and_if_match_need_a_fresh_review_without_writes(self):
        review = self.review_post()
        before = self.snapshot()
        for version, fingerprint, code in (("changed-version", review["fingerprint"], "record_changed"),
                                           (review["resourceVersion"], review["fingerprint"] + "x", "preflight_changed")):
            with self.subTest(code=code), self.assertRaises(APRefusal) as failure:
                self.preflight.verify(self.accountant, "bill.post", self.records["approved_bill_id"],
                                      {"periodId": "2026-10", "reason": "", "fingerprint": fingerprint}, version)
            self.assertEqual(failure.exception.code, code)
        self.assertEqual(self.snapshot(), before)

    def test_membership_loss_refuses_previous_review_before_record_disclosure(self):
        review = self.review_post()
        project_id = self.c.bills.get(self.records["approved_bill_id"])["project_id"]
        self.c.plugin("people").end_membership("practice.accountant", project_id,
                                                reason="Synthetic project assignment ended", actor="practice.bootstrap")
        before = self.snapshot()
        with self.assertRaises(APRefusal) as failure:
            self.preflight.verify(self.accountant, "bill.post", self.records["approved_bill_id"],
                                  {"periodId": "2026-10", "reason": "", "fingerprint": review["fingerprint"]}, review["resourceVersion"])
        self.assertEqual(failure.exception.status, 404)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_effectful_governor_blocks_without_invoking_its_hook(self):
        class EffectfulGovernor:
            GOVERNOR = True

            def check_execute(self, approval, manifest, *, actor):
                raise AssertionError("Effectful hooks must never be previewed")

        self.c.register_plugin("synthetic_effectful_governor", EffectfulGovernor())
        before = self.snapshot()
        review = self.review_post()
        self.assertFalse(review["allowed"])
        self.assertIsNone(review["fingerprint"])
        self.assertEqual(self.snapshot(), before)

    def test_post_review_never_invokes_effectful_contract_coverage_hook(self):
        before = self.snapshot()
        contracts = self.c.plugin("contract")
        with patch.object(contracts, "check_execute", side_effect=AssertionError("effectful hook")), \
                patch.object(contracts, "_record_coverage", side_effect=AssertionError("coverage write")):
            review = self.review_post()
        self.assertTrue(review["allowed"], review)
        self.assertEqual(self.snapshot(), before)

    def test_same_canonical_person_with_both_duties_cannot_post_their_own_grant(self):
        w = people_fixtures.World().team(enforce=False)
        self.addCleanup(w.c.db.close)
        w.grant("pm.lee", "accountant", project_id=w.a)
        w.p.add_membership("ext.acct", w.a, actor="travis")
        commitment_id = w.commitment()
        w.run("commitment.execute", commitment_id, requester="travis", approver="travis")
        w.policy(enforce=True, segregate=True, solo_owner_self_approval=False)
        sov = w.c.commitments.get(commitment_id)["sov"]
        bill = w.c.bills.certify(commitment_id=commitment_id, period_id="P1",
                                 installed=[{"sov_line_id": sov[0]["id"], "cumulative_installed": "100"}], actor="ext.acct")
        approval = w.c.request_approval("bill.approve", bill["id"], actor_role="accountant", requested_by="ext.acct")
        w.c.approve(approval["id"], approver="pm.lee", approver_role="pm")
        person_id = w.p.person_for("pm.lee")["id"]
        preflight = APPreflight(w.c, secret=b"independent-person-preflight-test-key")
        before = (tuple(w.c.db.conn.iterdump()), w.c.db.conn.total_changes)
        review = preflight.review(person_id, "bill.post", bill["id"], {"periodId": "P1", "reason": ""})
        self.assertFalse(review["allowed"])
        self.assertIsNone(review["fingerprint"])
        with self.assertRaises(APRefusal):
            preflight.review(" PM.LEE ", "bill.post", bill["id"], {"periodId": "P1", "reason": ""})
        self.assertEqual((tuple(w.c.db.conn.iterdump()), w.c.db.conn.total_changes), before)


if __name__ == "__main__":
    unittest.main()
