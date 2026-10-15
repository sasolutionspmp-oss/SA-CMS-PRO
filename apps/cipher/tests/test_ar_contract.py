"""Real scoped owner sources, independent original outcomes and dated AR reads."""
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.ap_contract import APRefusal
from apps.cipher.ar_actions import ARActionRunner
from apps.cipher.ar_contract import ARContract
from apps.cipher.ar_preflight import ARPreflight
from apps.cipher.ar_practice_fixture import make_ar_practice_fixture, PM_LOGIN, POSTER_LOGIN, BOOTSTRAP_LOGIN
from apps.cipher.ar_receipts import register_ar_receipts_schema
from apps.cipher.domain.owner_billing import register_owner_billing_schema


register_owner_billing_schema()
register_ar_receipts_schema()


class ARContractTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ar_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.r = self.c.ar_practice_records
        self.people = {key: value["person_id"] for key, value in self.c.ar_practice_persona_people.items()}
        secret = b"ar-actual-source-scoped-contract-private-key"
        self.contract = ARContract(self.c, secret=secret)
        self.preflight = ARPreflight(self.c, self.contract, secret=secret)
        self.runner = ARActionRunner(self.c, self.contract, self.preflight)
        self.domain = self.c.plugin("owner_billing")

    def snapshot(self):
        return tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes, tuple(self.c.provider.submissions), dict(self.c.provider.transfers)

    def input(self):
        return {"claimRevisionId": self.r["claim_revision_id"], "reviewRevisionId": self.r["review_revision_id"], "periodId": self.r["period_id"],
                "lines": [{"lineId": "U1", "claimedCumulative": "12", "reviewedCumulative": "10", "differenceReason": "Two items not verified",
                           "claimSourceLocator": "Claim item U1", "reviewSourceLocator": "Certification item U1"},
                          {"lineId": "L2", "claimedCumulative": "15000", "reviewedCumulative": "12500", "differenceReason": "Testing incomplete",
                           "claimSourceLocator": "Claim item L2", "reviewSourceLocator": "Certification item L2"}]}

    def act(self, persona, action, resource, typed=None):
        typed = {} if typed is None else typed
        review = self.preflight.review(self.people[persona], action, resource, typed)
        self.assertTrue(review["allowed"], review)
        return self.runner.run(self.people[persona], action, resource, {**typed, "fingerprint": review["fingerprint"]},
                               repeatability_key=str(uuid4()), if_match=review["resourceVersion"])["result"]

    def posted(self):
        bill = self.act("preparer", "ownerBill.prepare", self.r["basis_id"], self.input())["billId"]
        approval = self.act("preparer", "ownerBill.requestApproval", bill)["approvalId"]
        self.act("reviewer", "ownerBill.approve", approval)
        self.act("poster", "ownerBill.post", bill)
        return bill, approval

    def tamper(self, table, sql, params):
        triggers = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))
        with self.c.db.transaction():
            for trigger in triggers:
                self.c.db.conn.execute("DROP TRIGGER " + trigger["name"])
            self.c.db.conn.execute(sql, params)
            for trigger in triggers:
                self.c.db.conn.execute(trigger["sql"])

    def test_real_declared_basis_separates_claim_and_review_and_supplies_explicit_previous_zeros(self):
        before = self.snapshot()
        prep = self.contract.preparation(self.people["preparer"], self.r["basis_id"])
        self.assertEqual(prep["basis"]["contractValueCents"], 25000000)
        self.assertEqual(prep["basis"]["sourceStatus"], "current")
        self.assertEqual(prep["claimSources"][0]["revisionId"], self.r["claim_revision_id"])
        self.assertEqual(prep["reviewSources"][0]["revisionId"], self.r["review_revision_id"])
        self.assertNotEqual(prep["claimSources"][0]["documentId"], prep["reviewSources"][0]["documentId"])
        self.assertEqual(prep["previous"], {"billId": None, "certifiedCents": 0, "retainedCents": 0,
            "lines": [{"lineId": "U1", "reviewedQuantity": "0", "reviewedAmountCents": 0},
                      {"lineId": "L2", "reviewedQuantity": None, "reviewedAmountCents": 0}]})
        self.assertEqual(prep["periods"][0]["startDate"], "2026-10-01")
        self.assertNotIn("sourceHash", json.dumps(prep))
        self.assertNotIn("entry_hash", json.dumps(prep))
        self.assertEqual(before, self.snapshot())

    def test_hidden_unknown_or_wrong_duty_refs_refuse_before_private_source_proofs(self):
        before = self.snapshot()
        with patch.object(self.domain, "basis_proof", side_effect=AssertionError("scope before private source")) as proof:
            for identifier in (self.r["hidden_basis_id"], "unknown_basis"):
                with self.assertRaises(APRefusal) as caught:
                    self.contract.preparation(self.people["preparer"], identifier)
                self.assertEqual(caught.exception.status, 404)
            with self.assertRaises(APRefusal) as wrong_duty:
                self.contract.authorize(self.people["controller"], "ownerBill.prepare", self.r["basis_id"])
            self.assertEqual(wrong_duty.exception.status, 403)
            proof.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_counts_totals_and_serialized_choices_are_scoped_before_aggregation(self):
        before = self.snapshot()
        for collection in ("projects", "owner-bases", "owner-bills", "owner-bill-approvals", "owner-send-approvals"):
            result = self.contract.read(self.people["preparer"], collection)
            self.assertNotIn(self.r["hidden_project_id"], json.dumps(result))
            self.assertNotIn(self.r["hidden_basis_id"], json.dumps(result))
            self.assertLessEqual(result["count"], 1)
        self.assertEqual(self.contract.read(self.people["preparer"], "owner-bases")["totals"], {"contractValueCents": 25000000})
        with self.assertRaises(APRefusal) as caught:
            self.contract.read(self.people["preparer"], "owner-bills", project_id=self.r["hidden_project_id"])
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(before, self.snapshot())

    def test_native_draft_original_grant_posting_and_current_status_remain_distinct(self):
        bill = self.act("preparer", "ownerBill.prepare", self.r["basis_id"], self.input())["billId"]
        draft = self.contract.bill(self.people["preparer"], bill)
        self.assertEqual((draft["status"], draft["effectiveStatus"]), ("draft", "draft"))
        self.assertEqual(draft["totals"]["currentOpenCents"], 0)
        self.assertIsNone(draft["businessApproval"])
        self.assertIsNone(draft["posting"])
        self.assertNotEqual(draft["claimSource"]["documentId"], draft["reviewSource"]["documentId"])
        self.assertEqual(draft["lines"][0]["claimedQuantity"], "12")
        self.assertEqual(draft["lines"][0]["reviewedQuantity"], "10")
        self.assertEqual(draft["lines"][0]["claimSourceLocator"], "Claim item U1")
        request = self.act("preparer", "ownerBill.requestApproval", bill)["approvalId"]
        self.act("reviewer", "ownerBill.approve", request)
        granted = self.contract.bill(self.people["preparer"], bill)
        self.assertEqual((granted["status"], granted["effectiveStatus"]), ("draft", "approved_not_posted"))
        self.assertEqual(granted["businessApproval"]["status"], "granted")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        self.act("poster", "ownerBill.post", bill)
        before = self.snapshot()
        posted = self.contract.bill(self.people["preparer"], bill)
        self.assertEqual(posted["status"], "posted")
        self.assertEqual(posted["businessApproval"]["status"], "granted")
        self.assertEqual(posted["businessApproval"]["authorizationStatus"], "consumed")
        self.assertEqual([(line["accountCode"], line["debitCents"], line["creditCents"])
                          for line in posted["posting"]["journalPreview"]],
                         [("1100", 2025000, 0), ("1150", 225000, 0), ("4000", 0, 2250000)])
        self.assertEqual((posted["invoiceDate"], posted["dueDate"], posted["termsDays"]), ("2026-10-01", "2026-10-31", 30))
        self.assertEqual(before, self.snapshot())

    def test_current_standing_aging_dates_are_exact_and_never_claim_historical_balances(self):
        bill, _ = self.posted()
        before = self.snapshot()
        at_due = self.contract.aging(self.people["preparer"], "ar-aging", as_of="2026-10-31")
        later = self.contract.aging(self.people["preparer"], "ar-aging", as_of="2026-11-30")
        self.assertEqual(at_due["items"][0]["daysPastDue"], 0)
        self.assertEqual(later["items"][0]["daysPastDue"], 30)
        self.assertEqual(later["items"][0]["agingBucket"], "1_30")
        self.assertEqual(later["items"][0]["billId"], bill)
        self.assertEqual(later["items"][0]["currentOpenCents"], 2025000)
        self.assertFalse(later["historicalSnapshot"])
        self.assertEqual(later["balanceBasis"], "current_standing_balance")
        self.assertEqual(later["watermark"], "Working ledger, not for issue")
        self.assertEqual(later["reconciliation"], {"scope": "authorized_projects", "subledgerCents": 2025000,
                                                  "controlCents": 2025000, "reconciled": True})
        retained = self.contract.aging(self.people["preparer"], "retainage-aging", as_of="2026-11-30")
        self.assertEqual(retained["items"][0]["currentOpenCents"], 225000)
        self.assertEqual(retained["items"][0]["agingBucket"], "unreleased")
        self.assertIsNone(retained["items"][0]["dueDate"])
        self.assertIsNone(retained["items"][0]["daysPastDue"])
        self.assertEqual(before, self.snapshot())

    def test_original_synthetic_send_and_posting_survive_current_collection_balance(self):
        bill, _ = self.posted()
        request = self.act("preparer", "ownerBill.requestSend", bill)["approvalId"]
        self.act("reviewer", "ownerBill.approveSend", request)
        self.act("preparer", "ownerBill.send", request)
        original = self.contract.bill(self.people["preparer"], bill)
        self.c.receivables.record_collection(prime_bill_id=bill, period_id=self.r["period_id"], amount="100.00", fee="0", method="wire",
            provider_ref="SIM-AR-CONTRACT-READ-COLLECTION", actor=POSTER_LOGIN)
        before = self.snapshot()
        current = self.contract.bill(self.people["preparer"], bill)
        self.assertEqual(current["send"], original["send"])
        self.assertEqual(current["posting"], original["posting"])
        self.assertEqual(current["totals"]["amountDueCents"], 2025000)
        self.assertEqual(current["totals"]["currentOpenCents"], 2015000)
        self.assertEqual(current["totals"]["currentReceivedCents"], 10000)
        self.assertFalse(current["externalSettlement"])
        self.assertFalse(current["send"]["externalDelivery"])
        self.assertEqual(before, self.snapshot())

    def test_new_source_changes_version_and_deleted_newer_revision_blocks_read(self):
        person = self.people["preparer"]
        original = self.contract.preparation(person, self.r["basis_id"])
        source = self.c.evidence.revision(self.r["claim_revision_id"])
        newer = self.c.evidence.add_revision(document_id=source["document_id"], content="Actual newer synthetic owner claim", actor=PM_LOGIN)
        updated = self.contract.preparation(person, self.r["basis_id"])
        self.assertNotEqual(original["version"], updated["version"])
        self.assertEqual(updated["claimSources"][0]["revisionId"], newer["id"])
        self.tamper("document_revisions", "DELETE FROM document_revisions WHERE id=?", (newer["id"],))
        before = self.snapshot()
        with self.assertRaises(APRefusal) as caught:
            self.contract.preparation(person, self.r["basis_id"])
        self.assertEqual(caught.exception.status, 423)
        self.assertEqual(before, self.snapshot())

    def test_removed_current_membership_blocks_previous_source_read(self):
        self.c.plugin("people").end_membership(PM_LOGIN, self.r["project_id"], reason="Synthetic AR assignment ended", actor=BOOTSTRAP_LOGIN)
        before = self.snapshot()
        with self.assertRaises(APRefusal) as caught:
            self.contract.preparation(self.people["preparer"], self.r["basis_id"])
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(before, self.snapshot())

    def test_multiple_pay_apps_total_only_additive_period_values(self):
        self.posted()
        typed = self.input()
        for field, source_id, content in (
            ("claimRevisionId", self.r["claim_revision_id"], "Synthetic next claim U1 22 EA and L2 $22,500"),
            ("reviewRevisionId", self.r["review_revision_id"], "Synthetic next review U1 20 EA and L2 $20,000"),
        ):
            original = self.c.evidence.revision(source_id)
            updated = self.c.evidence.add_revision(document_id=original["document_id"], content=content, actor=PM_LOGIN)
            typed[field] = updated["id"]
        typed["lines"][0].update(claimedCumulative="22", reviewedCumulative="20")
        typed["lines"][1].update(claimedCumulative="22500", reviewedCumulative="20000")
        bill = self.act("preparer", "ownerBill.prepare", self.r["basis_id"], typed)["billId"]
        request = self.act("preparer", "ownerBill.requestApproval", bill)["approvalId"]
        self.act("reviewer", "ownerBill.approve", request)
        self.act("poster", "ownerBill.post", bill)
        before = self.snapshot()
        result = self.contract.read(self.people["preparer"], "owner-bills")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["totals"]["revenueThisPeriodCents"], 4000000)
        self.assertEqual(result["totals"]["retainageThisPeriodCents"], 400000)
        self.assertEqual(result["totals"]["amountDueCents"], 3600000)
        self.assertEqual(result["totals"]["currentOpenCents"], 3600000)
        for cumulative in ("priorCertifiedCents", "claimedCertifiedCents", "reviewedCertifiedCents", "retainedCumulativeCents"):
            self.assertNotIn(cumulative, result["totals"])
        first_page = self.contract.read(self.people["preparer"], "owner-bills", top=1)
        self.assertIsNotNone(first_page["nextCursor"])
        second_page = self.contract.read(self.people["preparer"], "owner-bills", top=1, cursor=first_page["nextCursor"])
        self.assertNotEqual(first_page["items"][0]["id"], second_page["items"][0]["id"])
        self.assertEqual(first_page["totals"], result["totals"])
        self.assertEqual(before, self.snapshot())

    def test_superseded_claim_source_keeps_original_draft_but_marks_it_stale(self):
        bill = self.act("preparer", "ownerBill.prepare", self.r["basis_id"], self.input())["billId"]
        claim = self.c.evidence.revision(self.r["claim_revision_id"])
        self.c.evidence.add_revision(document_id=claim["document_id"], content="Genuine updated claimed owner progress", actor=PM_LOGIN)
        before = self.snapshot()
        result = self.contract.bill(self.people["preparer"], bill)
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["effectiveStatus"], "stale")
        self.assertEqual(result["claimSource"]["revisionId"], self.r["claim_revision_id"])
        self.assertFalse(result["claimSource"]["current"])
        self.assertEqual(result["availableActions"], [])
        self.assertEqual(before, self.snapshot())

    def _assert_current_views_hold(self, bill):
        person = self.people["preparer"]
        before = self.snapshot()
        calls = (lambda: self.contract.bill(person, bill),
                 lambda: self.contract.read(person, "owner-bills"),
                 lambda: self.contract.version(person, bill, "bill"),
                 lambda: self.contract.aging(person, "ar-aging", as_of="2026-11-30"),
                 lambda: self.contract.aging(person, "retainage-aging", as_of="2026-11-30"),
                 lambda: self.contract.send_preparation(person, bill))
        for call in calls:
            with self.assertRaises(APRefusal) as caught:
                call()
            self.assertEqual(caught.exception.status, 423)
        self.assertEqual(before, self.snapshot())

    def test_changed_collection_cannot_be_shown_as_current_verified_balance(self):
        bill, _ = self.posted()
        collection = self.c.receivables.record_collection(prime_bill_id=bill, period_id=self.r["period_id"], amount="100.00", fee="0",
            method="check", provider_ref="SIM-AR-CONTRACT-CURRENT-SOURCE", actor=POSTER_LOGIN)
        self.assertEqual(self.contract.bill(self.people["preparer"], bill)["totals"]["currentOpenCents"], 2015000)
        self.tamper("collections", "UPDATE collections SET amount='101.00' WHERE id=?", (collection["id"],))
        self._assert_current_views_hold(bill)

    def test_deleted_collection_still_holds_current_reads_through_original_birth(self):
        bill, _ = self.posted()
        collection = self.c.receivables.record_collection(prime_bill_id=bill, period_id=self.r["period_id"], amount="100.00", fee="0",
            method="wire", provider_ref="SIM-AR-CONTRACT-DELETED-SOURCE", actor=POSTER_LOGIN)
        self.tamper("collections", "DELETE FROM collections WHERE id=?", (collection["id"],))
        self._assert_current_views_hold(bill)

    def test_unsupported_credit_source_cannot_disappear_from_current_qualification(self):
        bill, _ = self.posted()
        revision = self.c.evidence.revision(self.r["review_revision_id"])
        credit = self.c.receivables.prepare_credit_memo(bill, "100.00", "Synthetic separate credit source awaiting qualification",
                                                       revision["content_hash"], actor=POSTER_LOGIN)
        self._assert_current_views_hold(bill)
        self.tamper("prime_bill_credit_memos", "DELETE FROM prime_bill_credit_memos WHERE id=?", (credit["id"],))
        self._assert_current_views_hold(bill)


if __name__ == "__main__":
    unittest.main()
