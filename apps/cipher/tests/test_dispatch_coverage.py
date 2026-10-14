"""Coverage must still hold when a queued synthetic payment is dispatched."""
import os
import tempfile
import unittest

from apps.cipher.core.approvals import material_hash
from apps.cipher.core.ids import canonical_json, hash_json, loads
from apps.cipher.domain import contracts
from apps.cipher.domain.payments import KillSwitchEngaged, ReleaseQuarantined
from apps.cipher.service import Cipher
from apps.cipher.tests.test_contracts import GL, World


class DispatchCoverageTests(unittest.TestCase):
    def world(self, *, requirements=None, expiry=30):
        w = World()
        self.addCleanup(w.c.db.close)
        cert = w.certificate(expiry=expiry)
        cid = w.signed_commitment(requirements=requirements or GL)
        bill = w.certify(cid)
        w.post(bill["id"])
        released = w.c.execute(w.request_release(bill["id"])["id"], actor="treasury")
        intent = w.c.payments.get(released.result["intent"])
        return w, cert, cid, bill, intent

    def assert_held(self, w, intent, reason, *, audit_intact=True):
        c = w.c
        before = c.ledger.trial_balance()["journal_count"]
        result = c.dispatch_payments()
        self.assertEqual(len(result), 1, result)
        self.assertEqual(result[0]["status"], "queued", result)
        self.assertTrue(result[0]["held"], result)
        self.assertIn(reason, result[0]["reason"])
        current = c.payments.get(intent["id"])
        self.assertEqual(current["status"], "queued")
        self.assertIsNone(current["submitted_at"])
        self.assertIsNone(current["journal_id"])
        ob = c.commands.get(intent["outbox_id"])
        self.assertEqual((ob["status"], ob["attempts"]), ("pending", 0))
        self.assertIn(reason, ob["last_error"])
        self.assertEqual((len(c.provider.submissions), len(c.provider.transfers)), (0, 0))
        self.assertEqual(c.ledger.trial_balance()["journal_count"], before)
        self.assertEqual(c.approvals.get(intent["approval_id"])["status"], "consumed")
        self.assertEqual(c.audit.verify_chain()["ok"], audit_intact)

    def test_expired_coverage_holds_then_a_renewal_dispatches_the_same_intent_once(self):
        w, cert, _, bill, intent = self.world(expiry=0)
        w.clock(1)
        self.assert_held(w, intent, "expired")
        self.assert_held(w, intent, "expired")
        self.assertEqual(w.c.bills.get(bill["id"])["status"], "posted")
        renewal = w.certificate(effective=1, expiry=365)
        result = w.c.dispatch_payments()
        self.assertEqual([r["status"] for r in result], ["accepted"])
        self.assertEqual(result[0]["intent_id"], intent["id"])
        self.assertEqual(w.c.dispatch_payments(), [])
        self.assertEqual((len(w.c.provider.submissions), len(w.c.provider.transfers)), (1, 1))
        ob = w.c.commands.get(intent["outbox_id"])
        self.assertEqual((ob["status"], ob["attempts"], ob["last_error"]), ("dispatched", 1, None))
        checks = w.c.audit.entries(entity_type="payment_intent", entity_id=intent["id"])
        verified = [e for e in checks if e["action"] == "contract.dispatch_coverage_verified"]
        self.assertEqual(len(verified), 1)
        self.assertIn(renewal["id"], verified[0]["payload_json"])
        self.assertTrue(w.c.audit.verify_chain()["ok"])

    def test_a_withdrawn_certificate_holds_and_can_be_replaced(self):
        w, cert, _, _, intent = self.world()
        w.k.withdraw_certificate(cert["id"], "synthetic cancellation notice", "contracts-admin")
        self.assert_held(w, intent, "general_liability")
        w.certificate()
        self.assertEqual([r["status"] for r in w.c.payments.dispatch_pending(w.c.provider, actor="worker")], ["accepted"])

    def test_expiry_date_itself_is_still_covered(self):
        w, _, _, _, intent = self.world(expiry=0)
        result = w.c.dispatch_payments()
        self.assertEqual([(r["intent_id"], r["status"]) for r in result], [(intent["id"], "accepted")])

    def test_a_held_payment_does_not_block_another_bill_without_requirements(self):
        w, cert, _, _, held = self.world()
        plain = w.draft("20000")
        w.c.approve_and_execute("commitment.execute", plain)
        bill = w.certify(plain, "10000")
        w.post(bill["id"])
        release = w.c.execute(w.request_release(bill["id"])["id"], actor="treasury")
        w.k.withdraw_certificate(cert["id"], "synthetic cancellation", "contracts-admin")
        results = {r["intent_id"]: r for r in w.c.dispatch_payments()}
        self.assertEqual(results[held["id"]]["status"], "queued")
        self.assertTrue(results[held["id"]]["held"])
        self.assertEqual(results[release.result["intent"]]["status"], "accepted")
        self.assertEqual(len(w.c.provider.submissions), 1)

    def test_revised_certificate_evidence_holds(self):
        w, cert, _, _, intent = self.world()
        w.revise(w.c.evidence.document(cert["document_id"]), "reissued certificate")
        self.assert_held(w, intent, "general_liability")

    def test_a_rehashed_tampered_certificate_cannot_supply_dispatch_coverage(self):
        w, cert, _, _, intent = self.world(expiry=0)
        c = w.c
        forged = dict(c.db.one("SELECT * FROM contract_certificates WHERE id=?", (cert["id"],)))
        forged["expiry_date"] = "2099-12-31"
        forged["content_hash"] = hash_json({key: forged.get(key) for key in contracts._CERTIFICATE_KEYS})
        c.db.execute("DROP TRIGGER contract_certificates_binding_immutable")
        c.db.execute("DROP TRIGGER contract_certificates_lifecycle")
        c.db.execute("UPDATE contract_certificates SET expiry_date=?, content_hash=? WHERE id=?",
                     (forged["expiry_date"], forged["content_hash"], cert["id"]))
        w.clock(1)
        self.assert_held(w, intent, "general_liability")

    def test_deleted_requirements_hold_instead_of_silently_relaxing_coverage(self):
        w, _, cid, _, intent = self.world()
        w.c.db.execute("DROP TRIGGER contract_requirement_sets_no_delete")
        w.c.db.execute("DELETE FROM contract_requirement_sets WHERE commitment_id=?", (cid,))
        self.assert_held(w, intent, "audited record")

    def test_replacing_the_release_approval_cannot_hide_an_expired_bill_payment(self):
        w, _, cid, _, intent = self.world(expiry=0)
        unrelated = next(a for a in w.c.approvals.list(status="consumed")
                         if a["operation"] == "commitment.execute" and a["subject_id"] == cid)
        w.c.db.execute("UPDATE payment_intents SET bill_id=NULL, approval_id=? WHERE id=?", (unrelated["id"], intent["id"]))
        w.clock(1)
        self.assert_held(w, intent, "audited")

    def test_replacing_every_source_field_cannot_hide_an_expired_bill_payment(self):
        w, _, cid, _, intent = self.world(expiry=0)
        unrelated = next(a for a in w.c.approvals.list(status="consumed")
                         if a["operation"] == "commitment.execute" and a["subject_id"] == cid)
        w.c.db.execute("UPDATE payment_intents SET bill_id=NULL, source_type=NULL, source_id=NULL, approval_id=? WHERE id=?",
                       (unrelated["id"], intent["id"]))
        w.clock(1)
        self.assert_held(w, intent, "audited")

    def test_rewriting_the_approval_and_bill_cannot_remove_audited_coverage_requirements(self):
        for rehash in (False, True):
            with self.subTest(rehash=rehash):
                w, _, _, bill, intent = self.world(expiry=0)
                plain = w.draft("20000")
                w.c.approve_and_execute("commitment.execute", plain)
                approval = w.c.approvals.get(intent["approval_id"])
                manifest = approval["manifest"]
                manifest["governance"].pop(contracts.PLUGIN_NAME)
                w.c.db.execute("DROP TRIGGER approvals_request_immutable")
                w.c.db.execute("DROP TRIGGER approvals_lifecycle")
                w.c.db.execute("DROP TRIGGER bills_posted_figures_immutable")
                w.c.db.execute("UPDATE approvals SET manifest_json=?, manifest_hash=?, material_hash=? WHERE id=?",
                               (canonical_json(manifest), hash_json(manifest) if rehash else approval["manifest_hash"],
                                material_hash(manifest) if rehash else approval["material_hash"], approval["id"]))
                w.c.db.execute("UPDATE bills SET commitment_id=? WHERE id=?", (plain, bill["id"]))
                w.clock(1)
                self.assert_held(w, intent, "audited")

    def test_missing_or_rehashed_queue_audit_cannot_hide_a_changed_payment_source(self):
        for mode in ("delete", "rehash"):
            with self.subTest(mode=mode):
                w, _, cid, _, intent = self.world(expiry=0)
                unrelated = next(a for a in w.c.approvals.list(status="consumed")
                                 if a["operation"] == "commitment.execute" and a["subject_id"] == cid)
                w.c.db.execute("UPDATE payment_intents SET bill_id=NULL, source_type=NULL, source_id=NULL, approval_id=? WHERE id=?",
                               (unrelated["id"], intent["id"]))
                queued = w.c.db.one("SELECT * FROM audit_log WHERE action='payment.queued' AND entity_id=?", (intent["id"],))
                if mode == "delete":
                    w.c.db.execute("DROP TRIGGER audit_log_no_delete")
                    w.c.db.execute("DELETE FROM audit_log WHERE seq=?", (queued["seq"],))
                else:
                    bound = loads(queued["payload_json"])
                    bound.update(approval_id=unrelated["id"], source_type=None, source_id=None)
                    w.c.db.execute("DROP TRIGGER audit_log_no_update")
                    w.c.db.execute("UPDATE audit_log SET payload_json=?, payload_hash=? WHERE seq=?",
                                   (canonical_json(bound), hash_json(bound), queued["seq"]))
                w.clock(1)
                self.assert_held(w, intent, "audit chain", audit_intact=False)

    def test_required_bond_is_rechecked_with_insurance(self):
        w = World()
        self.addCleanup(w.c.db.close)
        w.certificate()
        w.certificate("performance_bond", "100000", expiry=0)
        cid = w.signed_commitment(requirements=GL + [{"kind": "performance_bond", "min_limit": "100000"}])
        bill = w.certify(cid)
        w.post(bill["id"])
        release = w.c.execute(w.request_release(bill["id"])["id"], actor="treasury")
        intent = w.c.payments.get(release.result["intent"])
        w.clock(1)
        self.assert_held(w, intent, "performance_bond")

    def test_retainage_dispatch_covers_every_commitment_paid_for_the_supplier(self):
        w = World()
        self.addCleanup(w.c.db.close)
        cert = w.certificate()
        governed = w.signed_commitment(requirements=GL)
        plain = w.draft("20000")
        w.c.approve_and_execute("commitment.execute", plain)
        w.post(w.certify(governed)["id"])
        w.c.commitments.close(governed, actor="pm-pat")
        w.c.approve_and_execute("retainage.release", governed, actor_role="accountant", period_id="P1")
        release = w.c.approve_and_execute("payment.release_retainage", plain, actor_role="treasury", actor="treasury")
        intent = w.c.payments.get(release.result["intent"])
        w.k.withdraw_certificate(cert["id"], "synthetic cancellation", "contracts-admin")
        self.assert_held(w, intent, "general_liability")

    def test_kill_switch_takes_precedence_over_a_coverage_hold(self):
        w, cert, _, _, intent = self.world()
        w.k.withdraw_certificate(cert["id"], "synthetic cancellation", "contracts-admin")
        w.c.payments.engage_kill_switch("synthetic protective hold", "owner")
        with self.assertRaises(KillSwitchEngaged):
            w.c.dispatch_payments()
        self.assertEqual(w.c.payments.get(intent["id"])["status"], "queued")
        self.assertEqual(len(w.c.provider.submissions), 0)

    def test_a_restored_coverage_hold_stays_read_only_before_recovery(self):
        w, cert, _, _, intent = self.world()
        w.k.withdraw_certificate(cert["id"], "synthetic cancellation", "contracts-admin")
        self.assert_held(w, intent, "general_liability")
        with tempfile.TemporaryDirectory(prefix="cipher-coverage-") as directory:
            backup = w.c.snapshot(os.path.join(directory, "copy.sqlite"))
            copied = Cipher.open_restored(backup, provider=w.c.provider)
            try:
                with self.assertRaises(ReleaseQuarantined):
                    copied.dispatch_payments()
                self.assertEqual(copied.payments.get(intent["id"])["status"], "queued")
                self.assertEqual(copied.commands.get(intent["outbox_id"])["status"], "pending")
                self.assertEqual(len(copied.provider.submissions), 0)
            finally:
                copied.db.close()


if __name__ == "__main__":
    unittest.main()
