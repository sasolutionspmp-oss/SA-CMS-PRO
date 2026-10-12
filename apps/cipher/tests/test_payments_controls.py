"""Payment execution controls: release gating (write authority, restore quarantine, kill
switch), recovery of queued intents from an older backup, cancellation, payee
re-verification at dispatch, authenticated provider callbacks, missing-callback
detection, provider MFA failure, provider clearing reconciliation, transfer terms
bound by release approvals, forecast isolation and the golden numbers."""
import contextlib
import datetime as _dt
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError, material_hash
from apps.cipher.core.db import WriteAuthorityError
from apps.cipher.core.ids import canonical_json, hash_json, utcnow
from apps.cipher.domain import payments as payments_module
from apps.cipher.domain.banking import PAYMENT_GUARD_SCHEMA_NAME as BANKING_GUARD_SCHEMA_NAME
from apps.cipher.domain.payments import (
    CONTROLS_BINDING_SCHEMA_NAME, CONTROLS_GUARDS_SCHEMA_NAME, CONTROLS_SCHEMA_NAME, TERMS_SCHEMA_NAME, KillSwitchEngaged, PaymentError,
    ProviderEventRejected, ReleaseQuarantined, SimulatedProvider, sign_event, verify_event,
)
from apps.cipher.domain.reimbursements import PLUGIN_NAME as REIMBURSEMENT
from apps.cipher.service import Cipher, RoleNotAuthorised, run_golden_fixture

D = Decimal
ENTITY = "S&A Solutions LLC (synthetic)"
DEST = "ACH-SIM-CTL-0001"


def claim_restored_copy(restored):
    """Claim write authority on a restored copy as the attested owner action (a read-only
    copy cannot record an approval of its own)."""
    return restored.claim_write_authority(approval_ref="ext-ref-restore-drill", actor="owner", reason="restore drill: claim the recovered copy")


class World:
    """Verified supplier, customer, one project (entity ``ENTITY``), open period P1 and an
    executed 100,000 subcontract (SOV 60,000 + 40,000, 10% retainage)."""

    def __init__(self, path: str = ":memory:", *, provider=None, name="Control project"):
        self.c = Cipher(path, provider=provider)
        sup = self.c.add_party(kind="supplier", name="Synthetic Subcontractor C", destination=DEST)
        self.supplier = self.c.verify_destination(sup["id"], destination=DEST, verified_by="owner")
        self.customer = self.c.add_party(kind="customer", name="Synthetic Owner Agency")
        self.project = self.c.create_project(name=name, entity=ENTITY, budget="115000", customer_id=self.customer["id"])
        self.pid = self.project["id"]
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        cmt = self.c.commitments.create(project_id=self.pid, supplier_id=self.supplier["id"], title="Sheet pile cofferdam and dewatering",
                                        sov_lines=[{"description": "Cofferdam", "amount": "60000"}, {"description": "Dewatering", "amount": "40000"}], actor="pm")
        self.c.approve_and_execute("commitment.execute", cmt["id"])
        self.cmt = self.c.commitments.get(cmt["id"])
        self.line1, self.line2 = self.cmt["sov"][0]["id"], self.cmt["sov"][1]["id"]

    def posted_bill(self, cumulative_line1: str, cumulative_line2: str | None = None):
        installed = [{"sov_line_id": self.line1, "cumulative_installed": cumulative_line1}]
        if cumulative_line2 is not None:
            installed.append({"sov_line_id": self.line2, "cumulative_installed": cumulative_line2})
        b = self.c.bills.certify(commitment_id=self.cmt["id"], period_id="P1", installed=installed, actor="pm")
        self.c.approve_and_execute("bill.approve", b["id"])
        return self.c.bills.get(b["id"])

    def release(self, bill_id):
        res = self.c.approve_and_execute("payment.release", bill_id, actor_role="treasury", actor="treasury")
        return self.c.payments.get(res.result["intent"])

    def journals(self):
        return self.c.ledger.trial_balance()["journal_count"]

    def assert_books(self, tc):
        tc.assertTrue(self.c.ledger.trial_balance()["balanced"])
        tc.assertTrue(self.c.audit.verify_chain()["ok"])
        tc.assertTrue(self.c.bills.ap_open_items(self.pid)["reconciled"], self.c.bills.ap_open_items(self.pid))
        clearing = self.c.payments.clearing_items()
        tc.assertTrue(clearing["reconciled"], clearing)


def file_world(tc, *, provider=None):
    d = tempfile.mkdtemp(prefix="cipher-ctl-")
    tc.addCleanup(shutil.rmtree, d, True)
    w = World(os.path.join(d, "live.sqlite"), provider=provider)
    tc.addCleanup(w.c.db.close)
    return w, d


def restored_copy(tc, w, path):
    r = Cipher.open_restored(path, provider=w.c.provider)
    tc.addCleanup(r.db.close)
    return r


# --------------------------------------------------------------------------- #
# 1. release gating                                                            #
# --------------------------------------------------------------------------- #

class ReleaseGateTests(unittest.TestCase):
    def test_copy_without_write_authority_refuses_release_before_any_provider_call(self):
        w, d = file_world(self)
        bill = w.posted_bill("20000")
        intent = w.release(bill["id"])
        backup = w.c.snapshot(os.path.join(d, "copy.sqlite"))
        copy = restored_copy(self, w, backup)
        self.assertFalse(copy.db.authority_status()["effective_write_authority"])
        self.assertFalse(copy.db.authority_status()["release_quarantined"])  # the epoch moves only on a claim
        ok, why = copy.payments.release_allowed()
        self.assertFalse(ok)
        self.assertIn("no write authority", why)
        with self.assertRaisesRegex(ReleaseQuarantined, "no write authority"):
            copy.dispatch_payments()
        approval = copy.approvals.get(intent["approval_id"])
        with self.assertRaises(ReleaseQuarantined):
            copy.payments.create_intent(manifest=approval["manifest"], approval_id=approval["id"], bill_id=bill["id"], note="bill payment", actor="treasury")
        with self.assertRaises(WriteAuthorityError):  # an unclaimed copy cannot lift its own quarantine either
            copy.complete_recovery(actor="reconciler")
        self.assertEqual((len(w.c.provider.submissions), len(w.c.provider.transfers)), (0, 0))
        self.assertEqual(copy.payments.get(intent["id"])["status"], "queued")
        # the live workspace still releases normally
        self.assertEqual(w.c.payments.release_allowed(), (True, "ok"))
        self.assertEqual([r["status"] for r in w.c.dispatch_payments()], ["accepted"])
        self.assertEqual(len(w.c.provider.submissions), 1)


class KillSwitchTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.c = self.w.c

    def test_engaging_stops_every_release_at_once_without_an_approval(self):
        bill1 = self.w.posted_bill("20000")
        queued = self.w.release(bill1["id"])
        bill2 = self.w.posted_bill("30000")
        ap = self.c.request_approval("payment.release", bill2["id"], actor_role="treasury")
        self.c.approve(ap["id"], approver="treasury", approver_role="treasury")
        approvals_before = len(self.c.approvals.list())
        ctl = self.c.payments.engage_kill_switch("suspected payee-detail fraud (synthetic drill)", "treasury")
        self.assertEqual((ctl["kill_switch"], ctl["version"], ctl["reason"], ctl["changed_by"]), (True, 2, "suspected payee-detail fraud (synthetic drill)", "treasury"))
        self.assertEqual(len(self.c.approvals.list()), approvals_before)  # protective: nothing to approve
        self.assertEqual([(h["version"], h["kill_switch"]) for h in self.c.payments.controls_history()], [(1, False), (2, True)])
        audit = [e for e in self.c.audit.entries(entity_type="payment_controls") if e["action"] == "payment.kill_switch_engaged"]
        self.assertEqual(len(audit), 1)
        ok, why = self.c.payments.release_allowed()
        self.assertFalse(ok)
        self.assertIn("kill switch", why)
        self.assertIn("suspected payee-detail fraud", why)
        with self.assertRaises(KillSwitchEngaged):
            self.c.dispatch_payments()
        self.assertEqual(self.c.payments.get(queued["id"])["status"], "queued")
        journals = self.w.journals()
        with self.assertRaises(KillSwitchEngaged):
            self.c.execute(ap["id"], actor="treasury")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")  # the refused command rolled back
        self.assertEqual(len(self.c.payments.list()), 1)
        self.assertEqual(self.w.journals(), journals)
        self.assertEqual(len(self.c.provider.submissions), 0)
        proposal = self.c.ricky.propose("payment.release", actor_role="treasury", context={"bill_id": bill2["id"]})
        self.assertEqual(proposal["decision"], "abstained")
        self.assertIn("kill switch", proposal["reason"])
        self.assertEqual(self.c.reconcile_payments(), [])  # reconciliation never submits, so it keeps working
        for bad in ("", "   ", None):
            with self.assertRaises(PaymentError):
                self.c.payments.engage_kill_switch(bad, "treasury")
        self.w.assert_books(self)

    def test_resume_needs_an_approval_bound_to_the_controls_version_and_reason(self):
        bill = self.w.posted_bill("20000")
        queued = self.w.release(bill["id"])
        with self.assertRaises(PaymentError):  # nothing to resume while releases run
            self.c.request_approval("payment.resume_releases", "payments", actor_role="treasury")
        self.c.payments.engage_kill_switch("bank reported a compromised token", "owner")
        with self.assertRaises(PaymentError):
            self.c.request_approval("payment.resume_releases", "something-else", actor_role="treasury")
        with self.assertRaises(RoleNotAuthorised):
            self.c.request_approval("payment.resume_releases", "payments", actor_role="pm")
        ap = self.c.request_approval("payment.resume_releases", "payments", actor_role="treasury")
        m = ap["manifest"]
        self.assertEqual((m["operation"], m["subject"]), ("payment.resume_releases", {"type": "payment_controls", "id": "payments"}))
        self.assertEqual((m["bindings"]["controls_version"], m["bindings"]["reason"], m["bindings"]["kill_switch"]), (2, "bank reported a compromised token", True))
        with self.assertRaises(RoleNotAuthorised):
            self.c.approve(ap["id"], approver="pm-user", approver_role="pm")
        self.c.approve(ap["id"], approver="treasury-user", approver_role="treasury")
        # a fresh emergency after the grant makes that approval stale
        self.c.payments.engage_kill_switch("second alert: confirm the bank callback", "owner")
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], actor="treasury")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertTrue(self.c.payments.controls()["kill_switch"])
        with self.assertRaises(KillSwitchEngaged):
            self.c.dispatch_payments()
        res = self.c.approve_and_execute("payment.resume_releases", "payments", actor_role="treasury", actor="treasury")
        self.assertEqual((res.result["kill_switch"], res.result["controls_version"], res.result["resumed_from_version"]), (False, 4, 3))
        ctl = self.c.payments.controls()
        self.assertEqual((ctl["kill_switch"], ctl["version"], ctl["changed_by"]), (False, 4, "treasury"))
        history = self.c.payments.controls_history()
        self.assertEqual([(h["version"], h["kill_switch"]) for h in history], [(1, False), (2, True), (3, True), (4, False)])
        self.assertEqual(history[-1]["approval_id"], res.result["approval_id"])
        self.assertEqual(self.c.payments.release_allowed(), (True, "ok"))
        self.assertEqual([r["status"] for r in self.c.dispatch_payments()], ["accepted"])
        self.assertEqual(self.c.payments.get(queued["id"])["status"], "accepted")
        self.w.assert_books(self)

    def test_schema_refuses_lifting_the_switch_without_a_consumed_resume_approval(self):
        self.c.payments.engage_kill_switch("drill", "owner")  # version 2
        db = self.c.db
        with self.assertRaisesRegex(sqlite3.DatabaseError, "appending the next version|consumed payment.resume_releases"):  # no history row for it
            db.execute("UPDATE payments_controls SET kill_switch=0, version=version+1, reason='raw', changed_by='intruder' WHERE id=1")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "only appends the next version"):  # history cannot skip ahead
            db.execute("INSERT INTO payments_controls_history (version, kill_switch, reason, changed_by, changed_at) VALUES (7, 0, 'raw', 'intruder', 't')")
        # a history row citing an approval that was requested but never granted or consumed does not lift it
        pending = self.c.request_approval("payment.resume_releases", "payments", actor_role="owner")
        db.execute("INSERT INTO payments_controls_history (version, kill_switch, reason, changed_by, changed_at, approval_id) VALUES (3, 0, 'raw', 'intruder', 't', ?)", (pending["id"],))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "consumed payment.resume_releases approval"):
            db.execute("UPDATE payments_controls SET kill_switch=0, version=3, reason='raw', changed_by='intruder' WHERE id=1")
        with self.assertRaises(sqlite3.DatabaseError):  # history is append-only
            db.execute("UPDATE payments_controls_history SET kill_switch=1 WHERE version=3")
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM payments_controls_history WHERE version=1")
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM payments_controls")
        with self.assertRaises(sqlite3.DatabaseError):  # a singleton
            db.execute("INSERT INTO payments_controls (id, kill_switch, version, reason, changed_by, changed_at) VALUES (2, 0, 1, 'x', 'x', 't')")
        self.assertTrue(self.c.payments.controls()["kill_switch"])
        self.assertFalse(self.c.payments.release_allowed()[0])
        status = {v["name"]: v for v in db.schema_status()["versions"]}
        self.assertTrue(status[CONTROLS_SCHEMA_NAME]["applied"] and status[CONTROLS_SCHEMA_NAME]["checksum_matches"])
        self.assertTrue(status[TERMS_SCHEMA_NAME]["applied"] and status[TERMS_SCHEMA_NAME]["checksum_matches"])
        self.assertTrue(status[CONTROLS_GUARDS_SCHEMA_NAME]["applied"] and status[CONTROLS_GUARDS_SCHEMA_NAME]["checksum_matches"])
        self.assertTrue(status[CONTROLS_BINDING_SCHEMA_NAME]["applied"] and status[CONTROLS_BINDING_SCHEMA_NAME]["checksum_matches"])

    def _approval_row(self, approval_id, manifest, **overrides):
        row = {
            "id": approval_id, "operation": manifest["operation"], "subject_type": manifest["subject"]["type"], "subject_id": manifest["subject"]["id"],
            "actor_role": manifest["actor_role"], "manifest_json": canonical_json(manifest), "manifest_hash": hash_json(manifest),
            "material_hash": material_hash(manifest), "policy_version": manifest["policy_version"], "nonce": manifest["nonce"], "status": "pending",
            "requested_by": "intruder", "requested_at": "t", "expires_at": manifest["expires_at"], "approver": None, "granted_at": None,
            "consumed_at": None, "consumed_by": None,
        }
        row.update(overrides)
        return row

    def _insert_approval(self, verb, row):
        cols = ", ".join(row)
        self.c.db.execute(f"{verb} INTO approvals ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))

    def test_a_stale_resume_approval_cannot_be_revived_by_raw_sql(self):
        """The review's probe: a resume approval granted for version 2 went stale when the switch
        was engaged again (version 3); a raw UPDATE set it to consumed and it then lifted version 3."""
        self.c.payments.engage_kill_switch("drill", "owner")  # version 2
        ap = self.c.request_approval("payment.resume_releases", "payments", actor_role="treasury")
        self.c.approve(ap["id"], approver="treasury", approver_role="treasury")
        self.c.payments.engage_kill_switch("second alert", "owner")  # version 3: the grant is stale
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], actor="treasury")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        db = self.c.db
        lifecycle = "pending -> granted -> consumed"
        for sql in ("UPDATE approvals SET status='consumed', consumed_at='t', consumed_by='intruder' WHERE id=?",
                    "UPDATE approvals SET status='granted' WHERE id=?",
                    "UPDATE approvals SET status='pending', approver=NULL, granted_at=NULL WHERE id=?",
                    "UPDATE approvals SET manifest_json='{}' WHERE id=?",
                    "UPDATE approvals SET material_hash='forged' WHERE id=?"):
            with self.assertRaisesRegex(sqlite3.DatabaseError, lifecycle, msg=sql):
                db.execute(sql, (ap["id"],))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "never deleted"):
            db.execute("DELETE FROM approvals WHERE id=?", (ap["id"],))
        # a history row citing it still cannot lift the switch
        db.execute("INSERT INTO payments_controls_history (version, kill_switch, reason, changed_by, changed_at, approval_id) VALUES (4, 0, 'raw', 'intruder', 't', ?)", (ap["id"],))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "bound to the engaged controls version"):
            db.execute("UPDATE payments_controls SET kill_switch=0, version=4, reason='raw', changed_by='intruder' WHERE id=1")
        self.assertTrue(self.c.payments.controls()["kill_switch"])
        self.assertFalse(self.c.payments.release_allowed()[0])
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")

    def test_a_forged_or_unaudited_resume_approval_cannot_lift_the_switch(self):
        """The review's other probe: a raw INSERT of a consumed approval, a history row and the
        controls UPDATE made release_allowed() true."""
        self.c.payments.engage_kill_switch("drill", "owner")  # version 2
        manifest = self.c.payments.manifest_for("payment.resume_releases", "payments", actor_role="owner")
        for status in ("consumed", "granted"):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "only as a pending request", msg=status):
                self._insert_approval("INSERT", self._approval_row(f"apr_forged_{status}", manifest, status=status, approver="intruder", granted_at="t",
                                                                   consumed_at="t" if status == "consumed" else None, consumed_by="intruder" if status == "consumed" else None))
        # stepping a raw pending row through granted -> consumed leaves no grant or consume audit entries behind
        self._insert_approval("INSERT", self._approval_row("apr_forged", manifest))
        db = self.c.db
        db.execute("UPDATE approvals SET status='granted', approver='intruder', granted_at='t' WHERE id='apr_forged'")
        db.execute("UPDATE approvals SET status='consumed', consumed_at='t', consumed_by='intruder' WHERE id='apr_forged'")
        for verb in ("REPLACE", "INSERT OR REPLACE", "INSERT OR IGNORE"):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "never replaced", msg=verb):
                self._insert_approval(verb, self._approval_row("apr_forged", dict(manifest, nonce="fresh-nonce")))
        db.execute("INSERT INTO payments_controls_history (version, kill_switch, reason, changed_by, changed_at, approval_id) VALUES (3, 0, 'raw', 'intruder', 't', 'apr_forged')")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "bound to the engaged controls version"):
            db.execute("UPDATE payments_controls SET kill_switch=0, version=3, reason='raw', changed_by='intruder' WHERE id=1")
        ctl = self.c.payments.controls()
        self.assertEqual((ctl["kill_switch"], ctl["version"]), (True, 2))
        with self.assertRaises(KillSwitchEngaged):
            self.c.dispatch_payments()

    def test_a_consumed_approval_for_another_controls_version_cannot_lift_the_switch(self):
        self.c.payments.engage_kill_switch("drill", "owner")  # version 2
        manifest = self.c.payments.manifest_for("payment.resume_releases", "payments", actor_role="owner")
        manifest["bindings"]["controls_version"] = 1  # what an approval for an earlier engagement carries
        ap = self.c.approvals.request(manifest, requested_by="owner")
        self.c.approvals.grant(ap["id"], approver="owner")
        self.c.approvals.consume(ap["id"], current_manifest=manifest, consumer="owner")  # granted and consumed, with audit entries
        db = self.c.db
        db.execute("INSERT INTO payments_controls_history (version, kill_switch, reason, changed_by, changed_at, approval_id) VALUES (3, 0, 'raw', 'intruder', 't', ?)", (ap["id"],))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "bound to the engaged controls version"):
            db.execute("UPDATE payments_controls SET kill_switch=0, version=3, reason='raw', changed_by='intruder' WHERE id=1")
        self.assertTrue(self.c.payments.controls()["kill_switch"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_schema_refuses_replacing_the_controls_or_their_history(self):
        """REPLACE deletes the conflicting row without firing UPDATE or DELETE triggers; the
        guards refuse it before anything is deleted."""
        self.c.payments.engage_kill_switch("drill", "owner")  # version 2
        db = self.c.db
        history = self.c.payments.controls_history()
        for verb in ("INSERT OR REPLACE", "REPLACE", "INSERT OR IGNORE"):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "never replaced", msg=verb):
                db.execute(f"{verb} INTO payments_controls (id, kill_switch, version, reason, changed_by, changed_at) VALUES (1, 0, 2, 'raw replace', 'intruder', 't')")
        with self.assertRaises(sqlite3.DatabaseError):  # an upsert is refused too
            db.execute("INSERT INTO payments_controls (id, kill_switch, version, reason, changed_by, changed_at) VALUES (1, 0, 3, 'upsert', 'intruder', 't') "
                       "ON CONFLICT(id) DO UPDATE SET kill_switch=0")
        for verb in ("INSERT OR REPLACE", "REPLACE"):
            # the next version passes the next-version trigger, but seq 2 is the engaged row
            with self.assertRaisesRegex(sqlite3.DatabaseError, "append-only", msg=verb):
                db.execute(f"{verb} INTO payments_controls_history (seq, version, kill_switch, reason, changed_by, changed_at) VALUES (2, 3, 0, 'rewritten', 'intruder', 't')")
        with self.assertRaises(sqlite3.DatabaseError):  # an existing version
            db.execute("REPLACE INTO payments_controls_history (version, kill_switch, reason, changed_by, changed_at) VALUES (2, 0, 'rewritten', 'intruder', 't')")
        ctl = self.c.payments.controls()
        self.assertEqual((ctl["kill_switch"], ctl["version"], ctl["reason"]), (True, 2, "drill"))
        self.assertEqual(self.c.payments.controls_history(), history)
        ok, why = self.c.payments.release_allowed()
        self.assertFalse(ok)
        self.assertIn("kill switch", why)
        with self.assertRaises(KillSwitchEngaged):
            self.c.dispatch_payments()
        # the governed path still works afterwards
        res = self.c.approve_and_execute("payment.resume_releases", "payments", actor_role="owner")
        self.assertEqual(res.result["controls_version"], 3)
        self.assertEqual(self.c.payments.release_allowed(), (True, "ok"))

    def test_a_consumed_resume_approval_cannot_be_replayed_by_replacing_its_history_row(self):
        self.c.payments.engage_kill_switch("drill", "owner")  # 2
        approval_id = self.c.approve_and_execute("payment.resume_releases", "payments", actor_role="owner").result["approval_id"]  # 3
        self.c.payments.engage_kill_switch("drill two", "owner")  # 4
        db = self.c.db
        # REPLACE on the approval's unique index would delete version 3 and re-cite the approval at version 5
        with self.assertRaisesRegex(sqlite3.DatabaseError, "append-only"):
            db.execute("REPLACE INTO payments_controls_history (version, kill_switch, reason, changed_by, changed_at, approval_id) VALUES (5, 0, 'replay', 'intruder', 't', ?)", (approval_id,))
        with self.assertRaises(sqlite3.DatabaseError):  # so the lift has no history row to stand on
            db.execute("UPDATE payments_controls SET kill_switch=0, version=5, reason='replay', changed_by='intruder' WHERE id=1")
        self.assertEqual([(h["version"], h["kill_switch"], h["approval_id"]) for h in self.c.payments.controls_history()],
                         [(1, False, None), (2, True, None), (3, False, approval_id), (4, True, None)])
        self.assertTrue(self.c.payments.controls()["kill_switch"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_one_resume_approval_lifts_the_switch_once(self):
        self.c.payments.engage_kill_switch("drill", "owner")
        res = self.c.approve_and_execute("payment.resume_releases", "payments", actor_role="owner")
        approval_id = res.result["approval_id"]
        self.c.payments.engage_kill_switch("drill two", "owner")  # version 4
        db = self.c.db
        with self.assertRaises(sqlite3.DatabaseError):  # the consumed approval is already cited by version 3
            db.execute("INSERT INTO payments_controls_history (version, kill_switch, reason, changed_by, changed_at, approval_id) VALUES (5, 0, 'replay', 'intruder', 't', ?)", (approval_id,))
        self.assertTrue(self.c.payments.controls()["kill_switch"])
        replay = self.c.execute(approval_id, actor="owner")  # the command replay returns the stored result
        self.assertTrue(replay.replayed)
        self.assertTrue(self.c.payments.controls()["kill_switch"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_engaging_mid_dispatch_holds_the_rest_of_the_run(self):
        b1 = self.w.posted_bill("20000")
        first = self.w.release(b1["id"])
        b2 = self.w.posted_bill("30000")
        second = self.w.release(b2["id"])
        original = self.c.provider.submit

        def submit_then_alarm(**kwargs):
            out = original(**kwargs)
            if len(self.c.provider.submissions) == 1:
                self.c.payments.engage_kill_switch("alarm raised while the run was in progress", "treasury")
            return out

        self.c.provider.submit = submit_then_alarm
        out = self.c.dispatch_payments()
        self.assertEqual([(r["intent_id"], r["status"]) for r in out], [(first["id"], "accepted")])
        self.assertEqual(self.c.payments.get(second["id"])["status"], "queued")
        self.assertEqual(len(self.c.provider.submissions), 1)
        halted = [e for e in self.c.audit.entries(entity_type="payment_controls") if e["action"] == "payment.dispatch_halted"]
        self.assertEqual(len(halted), 1)
        self.c.approve_and_execute("payment.resume_releases", "payments", actor_role="treasury", actor="treasury")
        self.assertEqual([r["status"] for r in self.c.dispatch_payments()], ["accepted"])
        self.assertEqual(len(self.c.provider.submissions), 2)
        self.w.assert_books(self)


# --------------------------------------------------------------------------- #
# 2. restore recovery of queued intents                                        #
# --------------------------------------------------------------------------- #

class RestoreRecoveryTests(unittest.TestCase):
    def test_older_backup_with_a_queued_intent_never_resubmits_a_transfer_that_happened(self):
        w, d = file_world(self)
        bill = w.posted_bill("20000")
        intent = w.release(bill["id"])
        backup = w.c.snapshot(os.path.join(d, "older-backup-queued.sqlite"))
        self.assertEqual([r["status"] for r in w.c.dispatch_payments()], ["accepted"])
        live = w.c.payments.get(intent["id"])
        self.assertTrue(w.c.payments.ingest_event(w.c.provider.settle(live["logical_op_id"]), actor="webhook")["applied"])
        self.assertEqual((len(w.c.provider.submissions), len(w.c.provider.transfers)), (1, 1))

        restored = restored_copy(self, w, backup)
        self.assertEqual(restored.payments.get(intent["id"])["status"], "queued")  # the backup predates the dispatch
        with self.assertRaises(ReleaseQuarantined):  # no write authority yet
            restored.dispatch_payments()
        status = claim_restored_copy(restored)
        self.assertTrue(status["effective_write_authority"] and status["release_quarantined"])
        with self.assertRaises(ReleaseQuarantined):
            restored.dispatch_payments()
        self.assertEqual(len(w.c.provider.submissions), 1)

        outcome = restored.complete_recovery(actor="reconciler")
        self.assertTrue(outcome["quarantine_lifted"])
        self.assertEqual([(r["intent_id"], r["status"], r["provider_ref"], r["recovered_from"]) for r in outcome["results"]],
                         [(intent["id"], "accepted", "sim_000001", "queued")])
        self.assertEqual([(c["status"], c["caught_up_event"]) for c in outcome["callbacks"]], [("settled", "recon_sim_000001_settled")])
        self.assertEqual(outcome["queued"], [])
        got = restored.payments.get(intent["id"])
        self.assertEqual((got["status"], got["provider_ref"]), ("settled", "sim_000001"))
        self.assertIsNotNone(got["submitted_at"])
        self.assertEqual(restored.commands.get(got["outbox_id"])["status"], "dispatched")
        self.assertEqual(len(restored.ledger.journals(source_type="payment_intent", source_id=intent["id"])), 1)
        self.assertEqual(len(restored.ledger.journals(source_type="provider_event")), 1)
        self.assertEqual(restored.dispatch_payments(), [])
        self.assertEqual((len(w.c.provider.submissions), len(w.c.provider.transfers)), (1, 1))  # nothing sent twice
        self.assertEqual(restored.bills.get(bill["id"])["status"], "paid")
        self.assertEqual(restored.ledger.balance("1000"), D("-18000.00"))
        self.assertEqual(restored.ledger.balance("1200"), D("0.00"))
        self.assertTrue(restored.bills.ap_open_items()["reconciled"])
        self.assertTrue(restored.payments.clearing_items()["reconciled"])
        self.assertTrue(restored.ledger.trial_balance()["balanced"])
        self.assertTrue(restored.audit.verify_chain()["ok"])
        self.assertTrue(w.c.db.has_write_authority())  # the live workspace is untouched

    def test_a_restored_copy_cannot_cancel_a_queued_intent_whose_transfer_already_happened(self):
        """The double-payment path: canceling the restored copy's stale queued intent would hide
        a transfer the live workspace made, reopen the bill and let it be paid again."""
        w, d = file_world(self)
        bill = w.posted_bill("20000")
        intent = w.release(bill["id"])
        backup = w.c.snapshot(os.path.join(d, "older-backup.sqlite"))
        w.c.dispatch_payments()
        w.c.payments.ingest_event(w.c.provider.settle(w.c.payments.get(intent["id"])["logical_op_id"]), actor="webhook")
        restored = restored_copy(self, w, backup)
        with self.assertRaisesRegex(ReleaseQuarantined, "no write authority"):  # an unclaimed copy changes nothing
            restored.payments.cancel_intent(intent["id"], "stale duplicate from the backup", "treasury")
        claim_restored_copy(restored)
        for actor in ("treasury", "owner"):
            with self.assertRaisesRegex(ReleaseQuarantined, "restore quarantine"):
                restored.payments.cancel_intent(intent["id"], "stale duplicate from the backup", actor)
        got = restored.payments.get(intent["id"])
        self.assertEqual(got["status"], "queued")
        self.assertEqual(restored.commands.get(got["outbox_id"])["status"], "pending")
        self.assertEqual(restored.bills.get(bill["id"])["status"], "posted")  # as the backup recorded it
        self.assertEqual([e for e in restored.audit.entries(entity_id=intent["id"]) if e["action"] == "payment.canceled"], [])
        # recovery finds the transfer, books it once and catches up the settlement
        outcome = restored.complete_recovery(actor="reconciler")
        self.assertTrue(outcome["quarantine_lifted"])
        got = restored.payments.get(intent["id"])
        self.assertEqual((got["status"], got["provider_ref"]), ("settled", "sim_000001"))
        self.assertEqual(restored.bills.get(bill["id"])["status"], "paid")
        ap = restored.bills.ap_open_items()
        self.assertEqual((ap["subledger_total"], ap["control_balance"], ap["reconciled"]), ("0.00", "0.00", True))
        self.assertEqual((restored.ledger.balance("1000"), restored.ledger.balance("1200")), (D("-18000.00"), D("0.00")))
        with self.assertRaisesRegex(PaymentError, "only queued"):
            restored.payments.cancel_intent(intent["id"], "too late", "treasury")
        with self.assertRaisesRegex(PaymentError, "only posted bills are payable"):  # no second release of a paid bill
            restored.request_approval("payment.release", bill["id"], actor_role="treasury")
        self.assertEqual(restored.dispatch_payments(), [])
        self.assertEqual((len(w.c.provider.submissions), len(w.c.provider.transfers)), (1, 1))
        self.assertTrue(restored.ledger.trial_balance()["balanced"])
        self.assertTrue(restored.audit.verify_chain()["ok"])

    def test_after_recovery_a_queued_intent_the_provider_never_saw_can_be_canceled(self):
        w, d = file_world(self)
        bill = w.posted_bill("20000")
        intent = w.release(bill["id"])
        restored = restored_copy(self, w, w.c.snapshot(os.path.join(d, "backup.sqlite")))
        claim_restored_copy(restored)
        self.assertEqual(restored.complete_recovery(actor="reconciler")["queued"], [intent["id"]])
        out = restored.payments.cancel_intent(intent["id"], "superseded after the restore drill", "treasury")
        self.assertEqual(out["status"], "canceled")
        entry = [e for e in restored.audit.entries(entity_id=intent["id"]) if e["action"] == "payment.canceled"]
        self.assertEqual(json.loads(entry[0]["payload_json"])["provider_check"], "provider has no transfer for it")
        self.assertEqual(restored.bills.get(bill["id"])["status"], "posted")
        self.assertEqual(restored.dispatch_payments(), [])
        self.assertEqual(len(w.c.provider.submissions), 0)
        self.assertTrue(restored.bills.ap_open_items()["reconciled"])

    def test_queued_intent_the_provider_never_saw_stays_queued_and_is_sent_once(self):
        w, d = file_world(self)
        bill = w.posted_bill("20000")
        intent = w.release(bill["id"])
        restored = restored_copy(self, w, w.c.snapshot(os.path.join(d, "backup.sqlite")))
        claim_restored_copy(restored)
        outcome = restored.complete_recovery(actor="reconciler")
        self.assertTrue(outcome["quarantine_lifted"])
        self.assertEqual((outcome["results"], outcome["queued"]), ([], [intent["id"]]))
        self.assertEqual(restored.payments.get(intent["id"])["status"], "queued")
        self.assertEqual([r["status"] for r in restored.dispatch_payments()], ["accepted"])
        self.assertEqual((len(w.c.provider.submissions), len(w.c.provider.transfers)), (1, 1))
        self.assertTrue(restored.ledger.trial_balance()["balanced"])

    def test_unreachable_provider_keeps_the_quarantine(self):
        w, d = file_world(self)
        bill = w.posted_bill("20000")
        intent = w.release(bill["id"])
        restored = restored_copy(self, w, w.c.snapshot(os.path.join(d, "backup.sqlite")))
        claim_restored_copy(restored)
        w.c.provider.mode = "unavailable"
        outcome = restored.complete_recovery(actor="reconciler")
        self.assertFalse(outcome["quarantine_lifted"])
        self.assertEqual(outcome["unresolved"], [intent["id"]])
        self.assertTrue(restored.db.authority_status()["release_quarantined"])
        w.c.provider.mode = "accept"
        self.assertTrue(restored.complete_recovery(actor="reconciler")["quarantine_lifted"])
        self.assertEqual(len(w.c.provider.submissions), 0)


class RestoreDoublePaymentTests(unittest.TestCase):
    """Transfers a restored copy never recorded: the live workspace paid after the backup, possibly
    under an approval the copy never saw.  Releasing from the copy would pay the obligation twice,
    so recovery keeps the quarantine until each transfer is adopted (payment.adopt_transfer)."""

    def books_match_live(self, restored, w, codes=("1000", "1200", "2000", "2050", "6000")):
        for code in codes:
            self.assertEqual(restored.ledger.balance(code), w.c.ledger.balance(code), code)
        self.assertTrue(restored.ledger.trial_balance()["balanced"])
        self.assertTrue(restored.audit.verify_chain()["ok"])
        self.assertTrue(restored.bills.ap_open_items()["reconciled"])
        self.assertTrue(restored.payments.clearing_items()["reconciled"])

    def test_a_backup_older_than_the_release_holds_the_quarantine_until_the_live_transfer_is_adopted(self):
        w, d = file_world(self, provider=SimulatedProvider(fee="1.50"))
        bill = w.posted_bill("20000")
        backup = w.c.snapshot(os.path.join(d, "older-than-the-release.sqlite"))
        live = w.release(bill["id"])
        self.assertEqual([r["status"] for r in w.c.dispatch_payments()], ["accepted"])
        w.c.payments.ingest_event(w.c.provider.settle(live["logical_op_id"]), actor="webhook")
        restored = restored_copy(self, w, backup)
        claim_restored_copy(restored)
        self.assertEqual((restored.payments.list(), restored.bills.get(bill["id"])["status"]), ([], "posted"))
        outcome = restored.complete_recovery(actor="reconciler")
        self.assertFalse(outcome["quarantine_lifted"])
        self.assertEqual((outcome["unresolved"], outcome["queued"]), ([], []))
        [t] = outcome["unrecorded_transfers"]
        self.assertEqual((t["provider_ref"], t["amount"], t["fee"], t["status"], t["adoptable"], t["pays"]), ("sim_000001", "18000.00", "1.50", "settled", True, f"bill {bill['id']}"))
        self.assertIn("never recorded", " ".join(outcome["held"]))
        self.assertTrue(restored.db.authority_status()["release_quarantined"])
        self.assertFalse(restored.payments.release_allowed()[0])
        self.assertEqual(len([e for e in restored.audit.entries(entity_type="workspace") if e["action"] == "recovery.held"]), 1)
        # the review's probe: a fresh release of the same bill from the copy
        release = restored.request_approval("payment.release", bill["id"], actor_role="treasury")
        restored.approve(release["id"], approver="treasury", approver_role="treasury")
        with self.assertRaises(ReleaseQuarantined):
            restored.execute(release["id"], actor="treasury")
        # adopting the live transfer is an owner decision bound to the transfer and the payee
        with self.assertRaises(RoleNotAuthorised):
            restored.request_approval("payment.adopt_transfer", "sim_000001", actor_role="treasury")
        adopt = restored.request_approval("payment.adopt_transfer", "sim_000001", actor_role="owner")
        m = adopt["manifest"]
        self.assertEqual((m["subject"], m["amounts"], m["entity"], m["currency"]),
                         ({"type": "provider_transfer", "id": "sim_000001"}, {"amount": "18000.00", "fee": "1.50"}, ENTITY, "USD"))
        self.assertEqual((m["bindings"]["source_type"], m["bindings"]["source_id"], m["bindings"]["logical_op_id"], m["bindings"]["superseded_intents"]),
                         ("bill", bill["id"], live["logical_op_id"], []))
        self.assertEqual((m["destination"]["party_id"], m["destination"]["destination"]), (w.supplier["id"], DEST))
        self.assertEqual(m["observed"], {"provider_status": "settled", "settled": True})
        restored.approve(adopt["id"])
        res = restored.execute(adopt["id"], actor="owner").result
        self.assertEqual((res["status"], res["provider_ref"], res["superseded"]), ("settled", "sim_000001", []))
        got = restored.payments.get(res["intent"])
        self.assertEqual((got["logical_op_id"], got["approval_id"], got["outbox_id"], got["fee"], got["source_id"]), (live["logical_op_id"], adopt["id"], None, "1.50", bill["id"]))
        self.assertEqual(restored.bills.get(bill["id"])["status"], "paid")
        self.assertEqual(len(restored.ledger.journals(source_type="payment_intent")), 1)
        self.assertEqual((restored.ledger.balance("1000"), restored.ledger.balance("6000")), (D("-18001.50"), D("1.50")))
        self.books_match_live(restored, w)
        lifted = restored.complete_recovery(actor="reconciler")
        self.assertTrue(lifted["quarantine_lifted"], lifted["held"])
        self.assertEqual((lifted["unrecorded_transfers"], lifted["held"]), ([], []))
        with self.assertRaisesRegex(PaymentError, "only posted bills are payable"):  # the approval granted earlier can never pay it again
            restored.execute(release["id"], actor="treasury")
        with self.assertRaisesRegex(PaymentError, "already recorded"):
            restored.request_approval("payment.adopt_transfer", "sim_000001", actor_role="owner")
        self.assertEqual(restored.dispatch_payments(), [])
        self.assertEqual((len(w.c.provider.submissions), len(w.c.provider.transfers)), (1, 1))  # one transfer for the bill, ever
        self.books_match_live(restored, w)

    def test_a_queued_intent_the_live_workspace_replaced_is_superseded_not_sent_again(self):
        """The review's second probe: the backup holds queued intent A; live, A failed (MFA) and
        approval B paid the bill; the restored copy left A queued and dispatched it."""
        w, d = file_world(self)
        bill = w.posted_bill("20000")
        first = w.release(bill["id"])
        backup = w.c.snapshot(os.path.join(d, "backup-with-a-queued-intent.sqlite"))
        w.c.provider.mode = "mfa_failed"
        self.assertEqual([r["status"] for r in w.c.dispatch_payments()], ["failed"])
        w.c.provider.mode = "accept"
        w.release(bill["id"])
        self.assertEqual([r["status"] for r in w.c.dispatch_payments()], ["accepted"])
        submissions = len(w.c.provider.submissions)
        restored = restored_copy(self, w, backup)
        claim_restored_copy(restored)
        outcome = restored.complete_recovery(actor="reconciler")
        self.assertFalse(outcome["quarantine_lifted"])
        self.assertEqual(outcome["queued"], [first["id"]])  # the provider never saw A: it stays queued, as specified ...
        self.assertEqual([(t["provider_ref"], t["adoptable"], t["supersedes"]) for t in outcome["unrecorded_transfers"]], [("sim_000001", True, [first["id"]])])
        with self.assertRaises(ReleaseQuarantined):  # ... but it is never sent while B is unrecorded
            restored.dispatch_payments()
        with self.assertRaisesRegex(ReleaseQuarantined, "restore quarantine"):
            restored.payments.cancel_intent(first["id"], "stale duplicate", "treasury")
        res = restored.approve_and_execute("payment.adopt_transfer", "sim_000001", actor_role="owner").result
        self.assertEqual((res["status"], res["superseded"]), ("accepted", [first["id"]]))
        old = restored.payments.get(first["id"])
        self.assertEqual(old["status"], "canceled")
        ob = restored.commands.get(old["outbox_id"])
        self.assertEqual(ob["status"], "failed")
        self.assertIn("superseded by provider transfer sim_000001", ob["last_error"])
        canceled = [json.loads(e["payload_json"]) for e in restored.audit.entries(entity_id=first["id"]) if e["action"] == "payment.canceled"]
        self.assertEqual(canceled[0]["superseded_by"], "sim_000001")
        self.assertEqual(restored.bills.get(bill["id"])["status"], "paid")
        lifted = restored.complete_recovery(actor="reconciler")
        self.assertTrue(lifted["quarantine_lifted"], lifted["held"])
        self.assertEqual(lifted["queued"], [])
        self.assertEqual(restored.dispatch_payments(), [])
        self.assertEqual((len(w.c.provider.submissions), len(w.c.provider.transfers)), (submissions, 1))  # A was never sent
        self.books_match_live(restored, w)

    def test_a_transfer_for_a_record_the_backup_never_had_is_adopted_against_the_re_keyed_record(self):
        w, d = file_world(self)
        backup = w.c.snapshot(os.path.join(d, "before-the-bill.sqlite"))
        bill = w.posted_bill("20000")
        w.release(bill["id"])
        w.c.dispatch_payments()
        restored = restored_copy(self, w, backup)
        claim_restored_copy(restored)
        outcome = restored.complete_recovery(actor="reconciler")
        self.assertFalse(outcome["quarantine_lifted"])
        [t] = outcome["unrecorded_transfers"]
        self.assertFalse(t["adoptable"])
        self.assertIn("does not exist in this copy", t["adoption_problem"])
        with self.assertRaisesRegex(PaymentError, "does not exist in this copy"):
            restored.request_approval("payment.adopt_transfer", "sim_000001", actor_role="owner")
        # re-key the lost bill in the copy (certifying and posting a bill is not a release)
        rekeyed = restored.bills.certify(commitment_id=w.cmt["id"], period_id="P1", installed=[{"sov_line_id": w.line1, "cumulative_installed": "20000"}], actor="pm")
        restored.approve_and_execute("bill.approve", rekeyed["id"])
        self.assertEqual(restored.bills.get(rekeyed["id"])["amount_due"], "18000.00")
        for subject, pattern in (("sim_000001=bill", "<provider_ref>=<source_type>:<source_id>"), ("sim_000001=nothing:x", "no adoption path"),
                                 ("sim_000001=bill:bil_missing", "does not exist in this copy"), ("sim_000099", "holds no transfer"), ("", "provider reference")):
            with self.assertRaisesRegex(PaymentError, pattern, msg=subject):
                restored.request_approval("payment.adopt_transfer", subject, actor_role="owner")
        res = restored.approve_and_execute("payment.adopt_transfer", f"sim_000001=bill:{rekeyed['id']}", actor_role="owner").result
        self.assertEqual((res["status"], res["source_id"]), ("accepted", rekeyed["id"]))
        self.assertEqual(restored.bills.get(rekeyed["id"])["status"], "paid")
        self.assertTrue(restored.complete_recovery(actor="reconciler")["quarantine_lifted"])
        self.assertEqual(restored.dispatch_payments(), [])
        self.assertEqual(len(w.c.provider.transfers), 1)
        self.books_match_live(restored, w)

    def test_a_released_retainage_payment_made_after_the_backup_is_adopted_once(self):
        w, d = file_world(self)
        bill = w.posted_bill("60000", "40000")
        w.release(bill["id"])
        w.c.dispatch_payments()
        w.c.commitments.close(w.cmt["id"], actor="pm")
        w.c.approve_and_execute("retainage.release", w.cmt["id"], period_id="P1")
        backup = w.c.snapshot(os.path.join(d, "retainage-released.sqlite"))
        res = w.c.approve_and_execute("payment.release_retainage", w.cmt["id"], actor_role="treasury", actor="treasury")
        self.assertEqual([r["status"] for r in w.c.dispatch_payments()], ["accepted"])
        live = w.c.payments.get(res.result["intent"])
        restored = restored_copy(self, w, backup)
        claim_restored_copy(restored)
        outcome = restored.complete_recovery(actor="reconciler")
        self.assertFalse(outcome["quarantine_lifted"])
        [t] = outcome["unrecorded_transfers"]
        self.assertEqual((t["provider_ref"], t["amount"], t["pays"]), (live["provider_ref"], "10000.00", f"retainage_release {w.cmt['id']}"))
        adopted = restored.approve_and_execute("payment.adopt_transfer", live["provider_ref"], actor_role="owner").result
        self.assertEqual((adopted["status"], adopted["source_type"]), ("accepted", "retainage_release"))
        got = restored.payments.get(adopted["intent"])
        self.assertEqual((got["note"], got["bill_id"], got["payable_account"]), ("retainage release payment", None, "2000"))
        self.assertTrue(restored.complete_recovery(actor="reconciler")["quarantine_lifted"])
        with self.assertRaisesRegex(PaymentError, "no released retainage is payable"):
            restored.request_approval("payment.release_retainage", w.cmt["id"], actor_role="treasury")
        self.assertEqual(restored.dispatch_payments(), [])
        self.assertEqual(len(w.c.provider.transfers), 2)
        self.books_match_live(restored, w)

    def test_an_adoption_approval_goes_stale_when_the_payee_changes_and_refuses_a_different_destination(self):
        w, d = file_world(self)
        bill = w.posted_bill("20000")
        backup = w.c.snapshot(os.path.join(d, "backup.sqlite"))
        w.release(bill["id"])
        w.c.dispatch_payments()
        restored = restored_copy(self, w, backup)
        claim_restored_copy(restored)
        ap = restored.request_approval("payment.adopt_transfer", "sim_000001", actor_role="owner")
        restored.approve(ap["id"])
        restored.verify_destination(w.supplier["id"], destination=DEST, verified_by="owner")  # re-verified: a new destination version
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):  # the bound destination version no longer holds
            restored.execute(ap["id"], actor="owner")
        self.assertEqual((restored.approvals.get(ap["id"])["status"], restored.payments.list()), ("invalidated", []))
        restored.verify_destination(w.supplier["id"], destination="ACH-SIM-CTL-OTHER", verified_by="owner")
        with self.assertRaisesRegex(PaymentError, "verified destination in this copy differs"):
            restored.request_approval("payment.adopt_transfer", "sim_000001", actor_role="owner")
        self.assertFalse(restored.complete_recovery(actor="reconciler")["quarantine_lifted"])
        restored.verify_destination(w.supplier["id"], destination=DEST, verified_by="owner")
        self.assertEqual(restored.approve_and_execute("payment.adopt_transfer", "sim_000001", actor_role="owner").result["status"], "accepted")
        self.assertTrue(restored.complete_recovery(actor="reconciler")["quarantine_lifted"])
        self.assertEqual(len(w.c.provider.submissions), 1)

    def test_recovery_holds_while_missed_callbacks_cannot_be_caught_up(self):
        """The review's probe: with no webhook secret the restored copy lifted the quarantine with
        the live settlement unrecorded (1000 = 0.00)."""
        w, d = file_world(self)
        bill = w.posted_bill("20000")
        intent = w.release(bill["id"])
        w.c.dispatch_payments()
        backup = w.c.snapshot(os.path.join(d, "backup-accepted.sqlite"))
        w.c.payments.ingest_event(w.c.provider.settle(intent["logical_op_id"]), actor="webhook")
        restored = restored_copy(self, w, backup)
        claim_restored_copy(restored)
        restored.payments.webhook_secret = None
        outcome = restored.complete_recovery(actor="reconciler")
        self.assertFalse(outcome["quarantine_lifted"])
        self.assertEqual(outcome["callbacks"], [])
        self.assertEqual([(b["intent_id"], b["provider_status"]) for b in outcome["callbacks_unresolved"]], [(intent["id"], "settled")])
        self.assertIn("no webhook secret", " ".join(outcome["held"]))
        self.assertEqual((restored.payments.get(intent["id"])["status"], restored.ledger.balance("1000")), ("accepted", D("0.00")))
        # an unreachable provider holds it too, even with nothing queued or in doubt
        restored.payments.webhook_secret = w.c.provider.webhook_secret
        w.c.provider.mode = "unavailable"
        outcome = restored.complete_recovery(actor="reconciler")
        self.assertFalse(outcome["quarantine_lifted"])
        self.assertEqual(outcome["unresolved"], [])
        self.assertIn("provider unreachable", " ".join(outcome["held"]))
        w.c.provider.mode = "accept"
        lifted = restored.complete_recovery(actor="reconciler")
        self.assertTrue(lifted["quarantine_lifted"], lifted["held"])
        self.assertEqual([(c["status"], c["caught_up_event"]) for c in lifted["callbacks"]], [("settled", "recon_sim_000001_settled")])
        self.books_match_live(restored, w)


# --------------------------------------------------------------------------- #
# 3. cancel, payee re-verification, MFA failure                                #
# --------------------------------------------------------------------------- #

class CancelTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.c = self.w.c

    def test_cancel_withdraws_a_queued_intent_and_keeps_the_obligation_open(self):
        bill = self.w.posted_bill("20000")
        intent = self.w.release(bill["id"])
        journals = self.w.journals()
        out = self.c.payments.cancel_intent(intent["id"], "released against the wrong funding account", "treasury")
        self.assertEqual(out["status"], "canceled")
        self.assertIn("canceled: released against the wrong funding account", out["note"])
        self.assertIsNotNone(out["resolved_at"])
        ob = self.c.commands.get(intent["outbox_id"])
        self.assertEqual((ob["status"], ob["last_error"]), ("failed", "canceled: released against the wrong funding account"))
        self.assertEqual(self.c.bills.get(bill["id"])["status"], "posted")
        ap = self.c.bills.ap_open_items(self.w.pid)
        self.assertEqual((ap["subledger_total"], ap["control_balance"], ap["reconciled"]), ("18000.00", "18000.00", True))
        self.assertEqual(self.w.journals(), journals)
        entry = [e for e in self.c.audit.entries(entity_id=intent["id"]) if e["action"] == "payment.canceled"]
        self.assertEqual(len(entry), 1)
        self.assertIn("wrong funding account", json.loads(entry[0]["payload_json"])["reason"])
        self.assertEqual(self.c.dispatch_payments(), [])
        self.assertEqual(len(self.c.provider.submissions), 0)
        for args in ((intent["id"], "again", "treasury"), ("pay_missing", "x", "treasury"), (intent["id"], "", "treasury")):
            with self.assertRaises(PaymentError, msg=str(args)):
                self.c.payments.cancel_intent(*args)
        # the bill is still payable under a fresh approval
        again = self.w.release(bill["id"])
        self.assertEqual([r["status"] for r in self.c.dispatch_payments()], ["accepted"])
        self.assertEqual(self.c.bills.get(bill["id"])["status"], "paid")
        with self.assertRaises(PaymentError):  # once dispatched it is never "canceled"
            self.c.payments.cancel_intent(again["id"], "too late", "treasury")
        self.w.assert_books(self)

    def test_only_queued_intents_can_be_canceled(self):
        bill = self.w.posted_bill("20000")
        intent = self.w.release(bill["id"])
        self.c.provider.mode = "timeout_after_accept"
        self.c.dispatch_payments()
        self.assertEqual(self.c.payments.get(intent["id"])["status"], "outcome_unknown")
        with self.assertRaisesRegex(PaymentError, "only queued"):
            self.c.payments.cancel_intent(intent["id"], "unsure it went", "treasury")
        self.c.provider.mode = "accept"
        self.assertEqual([r["status"] for r in self.c.reconcile_payments()], ["accepted"])
        self.w.assert_books(self)


class DispatchReverificationTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.c = self.w.c

    def test_destination_change_between_approval_and_dispatch_fails_the_intent_unsent(self):
        bill = self.w.posted_bill("20000")
        intent = self.w.release(bill["id"])
        journals = self.w.journals()
        self.c.verify_destination(self.w.supplier["id"], destination="ACH-SIM-CTL-CHANGED", verified_by="owner")
        out = self.c.dispatch_payments()
        self.assertEqual([(r["intent_id"], r["status"], r["reason"]) for r in out], [(intent["id"], "failed", "destination changed after approval")])
        got = self.c.payments.get(intent["id"])
        self.assertEqual(got["status"], "failed")
        self.assertIn("destination changed after approval", got["note"])
        self.assertEqual(self.c.commands.get(intent["outbox_id"])["status"], "failed")
        self.assertEqual((len(self.c.provider.submissions), len(self.c.provider.transfers)), (0, 0))
        self.assertEqual(self.c.bills.get(bill["id"])["status"], "posted")
        self.assertEqual(self.w.journals(), journals)
        self.assertEqual(self.c.bills.ap_open_items(self.w.pid)["subledger_total"], "18000.00")
        # a fresh approval pays the newly verified destination
        again = self.w.release(bill["id"])
        self.assertEqual((again["destination"], again["destination_version"]), ("ACH-SIM-CTL-CHANGED", 3))
        self.assertEqual([r["status"] for r in self.c.dispatch_payments()], ["accepted"])
        self.assertEqual([s["destination"] for s in self.c.provider.submissions], ["ACH-SIM-CTL-CHANGED"])
        self.w.assert_books(self)

    def test_a_reverified_same_destination_is_a_new_version_too(self):
        bill = self.w.posted_bill("20000")
        intent = self.w.release(bill["id"])
        self.c.verify_destination(self.w.supplier["id"], destination=DEST, verified_by="owner")  # same account, version bumps
        self.assertEqual([r["status"] for r in self.c.dispatch_payments()], ["failed"])
        self.assertIn("destination changed after approval", self.c.payments.get(intent["id"])["note"])
        self.assertEqual(len(self.c.provider.submissions), 0)

    def test_mfa_failure_rejects_the_release_and_keeps_the_obligation_open(self):
        bill = self.w.posted_bill("20000")
        intent = self.w.release(bill["id"])
        journals = self.w.journals()
        self.c.provider.mode = "mfa_failed"
        out = self.c.dispatch_payments()
        self.assertEqual([(r["status"], r["reason"]) for r in out], [("failed", "MFA challenge failed")])
        got = self.c.payments.get(intent["id"])
        self.assertEqual(got["status"], "failed")
        self.assertIn("MFA challenge failed", got["note"])
        self.assertEqual((len(self.c.provider.submissions), len(self.c.provider.transfers)), (1, 0))
        self.assertEqual(self.c.bills.get(bill["id"])["status"], "posted")
        self.assertEqual(self.w.journals(), journals)
        brief = self.c.ricky.brief(self.w.pid, actor_role="treasury")
        self.assertIn(intent["id"], [it["ref"] for it in brief["items"] if it["kind"] == "payment_failed"])
        self.assertEqual(self.c.reconcile_payments(), [])  # a refused release is not in doubt
        self.c.provider.mode = "accept"
        self.w.release(bill["id"])
        self.assertEqual([r["status"] for r in self.c.dispatch_payments()], ["accepted"])
        self.assertEqual(self.c.bills.get(bill["id"])["status"], "paid")
        self.w.assert_books(self)

    def test_mfa_failure_on_a_reimbursement_payment_reopens_the_claim(self):
        r = self.c.plugin(REIMBURSEMENT)
        emp = self.c.add_party(kind="employee", name="Field Engineer", destination="ACH-SIM-EMP-1")
        emp = self.c.verify_destination(emp["id"], destination="ACH-SIM-EMP-1", verified_by="owner")
        cl = r.submit_claim(project_id=self.w.pid, employee_id=emp["id"], description="Mileage to the cofferdam", amount="120.00", receipt_hash="ctl-rcpt-1", actor="emp")
        self.c.approve_and_execute("reimbursement.approve", cl["id"], period_id="P1")
        p = r.record_payment(cl["id"], "120.00", actor="treasury")
        self.c.approve_and_execute("reimbursement.pay", p["id"], actor_role="treasury", actor="treasury", period_id="P1")
        self.c.provider.mode = "mfa_failed"
        self.assertEqual([d["status"] for d in self.c.dispatch_payments()], ["failed"])
        self.assertEqual(r.payment(p["id"])["status"], "failed")
        claim = r.claim(cl["id"])
        self.assertEqual((claim["status"], claim["outstanding"], claim["in_flight"]), ("approved", "120.00", "0.00"))
        self.assertEqual(self.c.ledger.balance("2100"), D("120.00"))
        self.assertTrue(r.employee_payable_reconciliation(self.w.pid)["reconciled"])


# --------------------------------------------------------------------------- #
# 4. authenticated callbacks and missing-callback detection                    #
# --------------------------------------------------------------------------- #

class CallbackAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.c = self.w.c
        bill = self.w.posted_bill("20000")
        self.intent = self.w.release(bill["id"])
        self.c.dispatch_payments()
        self.intent = self.c.payments.get(self.intent["id"])

    def rejected(self, event, pattern):
        journals = self.w.journals()
        events = len(self.c.db.query("SELECT id FROM provider_events"))
        before = len([e for e in self.c.audit.entries(entity_type="provider_event") if e["action"] == "provider_event.rejected"])
        with self.assertRaisesRegex(ProviderEventRejected, pattern):
            self.c.payments.ingest_event(event, actor="webhook")
        self.assertEqual(self.w.journals(), journals)
        self.assertEqual(len(self.c.db.query("SELECT id FROM provider_events")), events)
        self.assertEqual(self.c.payments.get(self.intent["id"])["status"], "accepted")
        after = len([e for e in self.c.audit.entries(entity_type="provider_event") if e["action"] == "provider_event.rejected"])
        self.assertEqual(after, before + 1)

    def test_every_emitted_event_is_signed_with_a_per_instance_secret(self):
        other = SimulatedProvider()
        self.assertNotEqual(self.c.provider.webhook_secret, other.webhook_secret)
        self.assertGreaterEqual(len(self.c.provider.webhook_secret), 32)
        self.assertEqual(self.c.payments.webhook_secret, self.c.provider.webhook_secret)
        event = self.c.provider.settle(self.intent["logical_op_id"])
        self.assertIn("signature", event)
        self.assertTrue(verify_event(event, self.c.provider.webhook_secret))
        self.assertFalse(verify_event(event, other.webhook_secret))
        self.assertTrue(self.c.payments.ingest_event(event, actor="webhook")["applied"])
        dup = self.c.payments.ingest_event(event, actor="webhook")
        self.assertEqual((dup["applied"], dup["reason"]), (False, "duplicate event"))
        # the stored payload keeps its signature, so a replay from storage is still only a duplicate
        stored = json.loads(self.c.payments.get(self.intent["id"])["events"][-1]["payload_json"])
        self.assertEqual(self.c.payments.ingest_event(stored, actor="webhook-replay")["reason"], "duplicate event")
        returned = self.c.provider.return_payment(self.intent["logical_op_id"], "account closed")
        self.assertTrue(verify_event(returned, self.c.provider.webhook_secret))
        self.assertTrue(self.c.payments.ingest_event(returned, actor="webhook")["applied"])
        self.assertEqual(self.c.payments.get(self.intent["id"])["status"], "returned")
        self.w.assert_books(self)

    def test_unsigned_forged_and_malformed_events_are_rejected_before_any_change(self):
        genuine = self.c.provider.settle(self.intent["logical_op_id"])
        unsigned = {k: v for k, v in genuine.items() if k != "signature"}
        self.rejected(unsigned, "unsigned")
        self.rejected(dict(genuine, amount="1.00"), "does not verify")  # altered after signing
        self.rejected(dict(genuine, kind="returned"), "does not verify")
        self.rejected(dict(genuine, id="evt_forged"), "does not verify")
        self.rejected(dict(genuine, signature="0" * 64), "does not verify")
        self.rejected(dict(genuine, signature=None), "does not verify")
        self.rejected(sign_event(unsigned, SimulatedProvider().webhook_secret), "does not verify")  # another provider's key
        self.rejected(sign_event({"id": "evt_x", "kind": "settled"}, self.c.provider.webhook_secret), "malformed")
        self.rejected(["not", "an", "object"], "JSON object")
        # with no secret configured every callback is refused (fail closed)
        secret = self.c.payments.webhook_secret
        self.c.payments.webhook_secret = None
        try:
            self.rejected(genuine, "no webhook secret")
        finally:
            self.c.payments.webhook_secret = secret
        # the genuine event still applies, exactly once
        self.assertTrue(self.c.payments.ingest_event(genuine, actor="webhook")["applied"])
        self.assertEqual(self.c.ledger.balance("1000"), D("-18000.00"))
        self.assertEqual(len(self.c.ledger.journals(source_type="provider_event")), 1)
        self.w.assert_books(self)


class MissingCallbackTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.c = self.w.c
        self.bill = self.w.posted_bill("20000")
        intent = self.w.release(self.bill["id"])
        self.c.dispatch_payments()
        self.intent = self.c.payments.get(intent["id"])

    def test_reconcile_catches_a_missing_settlement_exactly_once(self):
        lost = self.c.provider.settle(self.intent["logical_op_id"])  # the callback never arrives
        self.assertEqual(self.c.ledger.balance("1200"), D("-18000.00"))
        out = self.c.reconcile_payments()
        self.assertEqual([(r["intent_id"], r["status"], r["caught_up_event"], r["applied"]) for r in out],
                         [(self.intent["id"], "settled", "recon_sim_000001_settled", True)])
        got = self.c.payments.get(self.intent["id"])
        self.assertEqual(got["status"], "settled")
        self.assertEqual([e["id"] for e in got["events"]], ["recon_sim_000001_settled"])
        self.assertEqual((self.c.ledger.balance("1000"), self.c.ledger.balance("1200")), (D("-18000.00"), D("0.00")))
        self.assertEqual(self.c.reconcile_payments(), [])
        late = self.c.payments.ingest_event(lost, actor="webhook")  # the real callback, late
        self.assertEqual((late["applied"], late["reason"]), (False, "settled not applicable to settled"))
        self.assertEqual(len(self.c.ledger.journals(source_type="provider_event")), 1)
        self.assertEqual(self.c.ledger.balance("1000"), D("-18000.00"))
        self.w.assert_books(self)

    def test_reconcile_catches_a_missing_return_after_settlement(self):
        self.c.payments.ingest_event(self.c.provider.settle(self.intent["logical_op_id"]), actor="webhook")
        self.c.provider.return_payment(self.intent["logical_op_id"], "account closed")  # callback lost
        out = self.c.reconcile_payments()
        self.assertEqual([(r["status"], r["caught_up_event"]) for r in out], [("returned", "recon_sim_000001_returned")])
        self.assertEqual(self.c.ledger.balance("2000"), D("18000.00"))
        self.assertEqual(self.c.ledger.balance("1000"), D("0.00"))
        self.assertEqual(self.c.bills.get(self.bill["id"])["status"], "posted")
        self.assertEqual(self.c.reconcile_payments(), [])
        self.w.assert_books(self)

    def test_reconcile_catches_a_return_that_came_before_any_settlement(self):
        self.c.provider.return_payment(self.intent["logical_op_id"], "invalid account")  # never settled, callback lost
        out = self.c.reconcile_payments()
        self.assertEqual([(r["status"], r["caught_up_event"]) for r in out], [("returned", "recon_sim_000001_returned")])
        self.assertEqual((self.c.ledger.balance("1200"), self.c.ledger.balance("2000"), self.c.ledger.balance("1000")), (D("0.00"), D("18000.00"), D("0.00")))
        self.w.assert_books(self)

    def test_an_unreachable_provider_leaves_callbacks_for_the_next_run(self):
        self.c.provider.settle(self.intent["logical_op_id"])
        self.c.provider.mode = "unavailable"
        self.assertEqual(self.c.reconcile_payments(), [])
        self.assertEqual(self.c.payments.get(self.intent["id"])["status"], "accepted")
        self.c.provider.mode = "accept"
        self.assertEqual([r["status"] for r in self.c.reconcile_payments()], ["settled"])


class FeeCatchUpTests(unittest.TestCase):
    """The review's probe: with a 1.50 fee, a settled-then-returned transfer booked 1000 = -1.50 /
    6000 = 1.50 when both callbacks arrived but 0.00 / 0.00 when reconciliation caught up."""

    EXPECTED = (D("-1.50"), D("0.00"), D("18000.00"), D("1.50"))  # 1000, 1200, 2000, 6000

    def world(self):
        w = World(provider=SimulatedProvider(fee="1.50"))
        bill = w.posted_bill("20000")
        intent = w.release(bill["id"])
        self.assertEqual([r["status"] for r in w.c.dispatch_payments()], ["accepted"])
        return w, w.c.payments.get(intent["id"])

    @staticmethod
    def balances(w):
        return tuple(w.c.ledger.balance(code) for code in ("1000", "1200", "2000", "6000"))

    def settlement_journals(self, w):
        return [[(ln["account_code"], ln["debit"], ln["credit"]) for ln in j["lines"]] for j in w.c.ledger.journals(source_type="provider_event")]

    def test_both_callbacks_arrive(self):
        w, intent = self.world()
        w.c.payments.ingest_event(w.c.provider.settle(intent["logical_op_id"]), actor="webhook")
        returned = w.c.provider.return_payment(intent["logical_op_id"])
        self.assertIs(returned["settled_before_return"], True)
        self.assertNotIn("derived_settlement", w.c.payments.ingest_event(returned, actor="webhook"))
        self.assertEqual(self.balances(w), self.EXPECTED)
        w.assert_books(self)

    def test_both_callbacks_lost_reconcile_books_the_settlement_fee_too(self):
        w, intent = self.world()
        lost = [w.c.provider.settle(intent["logical_op_id"]), w.c.provider.return_payment(intent["logical_op_id"])]
        out = w.c.reconcile_payments()
        self.assertEqual([(r["status"], r["caught_up_event"], r["derived_settlement"]) for r in out],
                         [("returned", "recon_sim_000001_returned", "recon_sim_000001_settled")])
        self.assertEqual(self.balances(w), self.EXPECTED)
        self.assertEqual(sorted(e["id"] for e in w.c.payments.get(intent["id"])["events"]), ["recon_sim_000001_returned", "recon_sim_000001_settled"])
        self.assertIn([("1200", "18000.00", "0.00"), ("6000", "1.50", "0.00"), ("1000", "0.00", "18001.50")], self.settlement_journals(w))
        self.assertEqual(w.c.reconcile_payments(), [])  # exactly once
        for event in lost:  # the real callbacks, late
            self.assertFalse(w.c.payments.ingest_event(event, actor="webhook")["applied"])
        self.assertEqual(self.balances(w), self.EXPECTED)
        self.assertEqual(len(w.c.ledger.journals(source_type="provider_event")), 2)
        w.assert_books(self)

    def test_only_the_settlement_callback_lost_the_return_proves_it(self):
        w, intent = self.world()
        lost = w.c.provider.settle(intent["logical_op_id"])
        res = w.c.payments.ingest_event(w.c.provider.return_payment(intent["logical_op_id"]), actor="webhook")
        self.assertEqual((res["applied"], res["derived_settlement"]), (True, "recon_sim_000001_settled"))
        self.assertEqual(self.balances(w), self.EXPECTED)
        self.assertEqual(w.c.payments.ingest_event(lost, actor="webhook")["reason"], "settled not applicable to returned")
        self.assertEqual(w.c.reconcile_payments(), [])
        self.assertEqual(self.balances(w), self.EXPECTED)
        self.assertEqual(len(w.c.ledger.journals(source_type="provider_event")), 2)
        w.assert_books(self)

    def test_a_return_before_any_settlement_books_no_fee(self):
        w, intent = self.world()
        returned = w.c.provider.return_payment(intent["logical_op_id"], "invalid account")
        self.assertIs(returned["settled_before_return"], False)
        w.c.payments.ingest_event(returned, actor="webhook")
        self.assertEqual(self.balances(w), (D("0.00"), D("0.00"), D("18000.00"), D("0.00")))
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 5. provider clearing and transfer terms                                      #
# --------------------------------------------------------------------------- #

class ClearingTests(unittest.TestCase):
    def test_clearing_reconciles_through_accept_settle_and_return(self):
        w = World()
        c = w.c
        empty = c.payments.clearing_items()
        self.assertEqual((empty["items"], empty["subledger_total"], empty["control_balance"], empty["reconciled"]), ([], "0.00", "0.00", True))
        b1 = w.posted_bill("20000")
        i1 = w.release(b1["id"])
        b2 = w.posted_bill("30000")
        i2 = w.release(b2["id"])
        c.dispatch_payments()
        both = c.payments.clearing_items()
        self.assertEqual([(it["intent_id"], it["amount"], it["clearing_effect"]) for it in both["items"]], [(i1["id"], "18000.00", "-18000.00"), (i2["id"], "9000.00", "-9000.00")])
        self.assertEqual((both["in_transit_total"], both["subledger_total"], both["control_balance"], both["reconciled"]), ("27000.00", "-27000.00", "-27000.00", True))
        checks = {chk["check"]: chk for chk in c.plugin("core_reconciliation").close_checks("P1")}
        self.assertTrue(checks["provider clearing reconciled (1200)"]["ok"])
        self.assertEqual(checks["provider clearing reconciled (1200)"]["detail"], "subledger -27000.00 vs control -27000.00")
        c.payments.ingest_event(c.provider.settle(c.payments.get(i1["id"])["logical_op_id"]), actor="webhook")
        one = c.payments.clearing_items(w.pid)
        self.assertEqual((one["subledger_total"], one["control_balance"], one["reconciled"]), ("-9000.00", "-9000.00", True))
        c.payments.ingest_event(c.provider.return_payment(c.payments.get(i2["id"])["logical_op_id"]), actor="webhook")  # before settlement
        none = c.payments.clearing_items()
        self.assertEqual((none["items"], none["subledger_total"], none["control_balance"], none["reconciled"]), ([], "0.00", "0.00", True))
        c.payments.ingest_event(c.provider.return_payment(c.payments.get(i1["id"])["logical_op_id"]), actor="webhook")  # after settlement
        self.assertEqual(c.payments.clearing_items()["control_balance"], "0.00")
        self.assertEqual((c.ledger.balance("1000"), c.ledger.balance("2000")), (D("0.00"), D("27000.00")))
        other = c.create_project(name="Other", entity=ENTITY, budget="0")
        self.assertEqual(c.payments.clearing_items(other["id"])["items"], [])
        w.assert_books(self)

    def test_an_approved_fee_is_bound_and_posted_at_settlement(self):
        w = World(provider=SimulatedProvider(fee="0.59"))
        c = w.c
        bill = w.posted_bill("20000")
        ap = c.request_approval("payment.release", bill["id"], actor_role="treasury")
        self.assertEqual(ap["manifest"]["bindings"]["fees"], "0.59")
        c.approve(ap["id"], approver="treasury", approver_role="treasury")
        intent = c.payments.get(c.execute(ap["id"], actor="treasury").result["intent"])
        self.assertEqual(intent["fee"], "0.59")
        c.dispatch_payments()
        c.payments.ingest_event(c.provider.settle(intent["logical_op_id"]), actor="webhook")
        settle = c.ledger.journals(source_type="provider_event")[0]
        self.assertEqual([(ln["account_code"], ln["debit"], ln["credit"]) for ln in settle["lines"]],
                         [("1200", "18000.00", "0.00"), ("6000", "0.59", "0.00"), ("1000", "0.00", "18000.59")])
        self.assertEqual((c.ledger.balance("1200"), c.ledger.balance("1000"), c.ledger.balance("6000")), (D("0.00"), D("-18000.59"), D("0.59")))
        w.assert_books(self)


class TransferTermsTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.c = self.w.c

    def test_release_manifests_bind_entity_currency_value_date_and_fee(self):
        today = utcnow().date().isoformat()
        bill = self.w.posted_bill("60000", "40000")
        m = self.c.request_approval("payment.release", bill["id"], actor_role="treasury")["manifest"]
        self.assertEqual((m["entity"], m["currency"]), (ENTITY, "USD"))
        self.assertEqual({k: m["bindings"][k] for k in ("fees", "value_date", "project_id", "payable_account")},
                         {"fees": "0.00", "value_date": today, "project_id": self.w.pid, "payable_account": "2000"})
        self.c.approve_and_execute("payment.release", bill["id"], actor_role="treasury", actor="treasury")
        self.c.dispatch_payments()
        self.c.commitments.close(self.w.cmt["id"], actor="pm")
        self.c.approve_and_execute("retainage.release", self.w.cmt["id"], period_id="P1")
        rm = self.c.request_approval("payment.release_retainage", self.w.cmt["id"], actor_role="treasury")["manifest"]
        self.assertEqual((rm["operation"], rm["entity"], rm["currency"], rm["amounts"]), ("payment.release_retainage", ENTITY, "USD", {"amount": "10000.00"}))
        self.assertEqual((rm["bindings"]["fees"], rm["bindings"]["value_date"]), ("0.00", today))

    def test_a_changed_fee_entity_or_value_date_invalidates_the_release_approval(self):
        bill = self.w.posted_bill("20000")

        def granted():
            ap = self.c.request_approval("payment.release", bill["id"], actor_role="treasury")
            self.c.approve(ap["id"], approver="treasury", approver_role="treasury")
            return ap

        ap = granted()
        self.c.provider.fee = "1.25"
        with self.assertRaisesRegex(StaleApprovalError, "bindings"):
            self.c.execute(ap["id"], actor="treasury")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.c.provider.fee = "0.00"

        ap = granted()
        self.c.db.execute("UPDATE projects SET entity='Another Entity LLC (synthetic)' WHERE id=?", (self.w.pid,))
        with self.assertRaisesRegex(StaleApprovalError, "entity"):
            self.c.execute(ap["id"], actor="treasury")
        self.c.db.execute("UPDATE projects SET entity=? WHERE id=?", (ENTITY, self.w.pid))

        ap = granted()
        tomorrow = utcnow() + _dt.timedelta(days=1)
        with mock.patch.object(payments_module, "utcnow", return_value=tomorrow):
            with self.assertRaisesRegex(StaleApprovalError, "bindings"):
                self.c.execute(ap["id"], actor="treasury")
        self.assertEqual(self.c.payments.list(), [])
        self.assertEqual(self.c.commands.pending("payment"), [])
        # the unchanged terms execute
        self.w.release(bill["id"])
        self.assertEqual([r["status"] for r in self.c.dispatch_payments()], ["accepted"])
        self.w.assert_books(self)

    def test_a_fee_change_after_execution_fails_the_intent_at_dispatch(self):
        bill = self.w.posted_bill("20000")
        intent = self.w.release(bill["id"])
        self.c.provider.fee = "2.00"
        out = self.c.dispatch_payments()
        self.assertEqual([r["status"] for r in out], ["failed"])
        self.assertIn("provider fee changed after approval (approved 0.00, provider now quotes 2.00)", out[0]["reason"])
        self.assertEqual(self.c.payments.get(intent["id"])["status"], "failed")
        self.assertEqual(len(self.c.provider.submissions), 0)
        self.assertEqual(self.c.bills.get(bill["id"])["status"], "posted")

    def test_an_intent_refuses_a_manifest_for_another_entity_or_currency(self):
        bill = self.w.posted_bill("20000")
        ap = self.c.request_approval("payment.release", bill["id"], actor_role="treasury")
        for change in ({"entity": "Another Entity LLC (synthetic)"}, {"currency": "CAD"}):
            with self.assertRaises(PaymentError, msg=str(change)):
                self.c.payments.create_intent(manifest=dict(ap["manifest"], **change), approval_id=ap["id"], bill_id=bill["id"], note="bill payment", actor="treasury")
        bad_fee = dict(ap["manifest"], bindings=dict(ap["manifest"]["bindings"], fees="-1.00"))
        with self.assertRaises(PaymentError):
            self.c.payments.create_intent(manifest=bad_fee, approval_id=ap["id"], bill_id=bill["id"], note="bill payment", actor="treasury")
        self.assertEqual(self.c.payments.list(), [])

    def test_an_approved_value_date_that_has_passed_fails_the_intent_unsent(self):
        """The review's probe: an intent whose value date had passed (held for days behind the kill
        switch) was still dispatched and accepted."""
        bill = self.w.posted_bill("20000")
        intent = self.w.release(bill["id"])
        later = utcnow() + _dt.timedelta(days=3)
        with mock.patch.object(payments_module, "utcnow", return_value=later):
            out = self.c.dispatch_payments()
        self.assertEqual([r["status"] for r in out], ["failed"])
        self.assertIn(f"approved value date {intent['value_date']} has passed", out[0]["reason"])
        self.assertEqual(len(self.c.provider.submissions), 0)
        self.assertEqual(self.c.commands.get(intent["outbox_id"])["status"], "failed")
        self.assertEqual(self.c.bills.get(bill["id"])["status"], "posted")
        # approved again, it goes out carrying the approved terms and Cipher's reference
        again = self.w.release(bill["id"])
        self.assertEqual([r["status"] for r in self.c.dispatch_payments()], ["accepted"])
        [sub] = self.c.provider.submissions
        self.assertEqual((sub["value_date"], sub["currency"]), (again["value_date"], "USD"))
        self.assertEqual(sub["reference"], {"workspace_id": self.c.db.workspace()["workspace_id"], "intent_id": again["id"], "source_type": "bill",
                                            "source_id": bill["id"], "project_id": self.w.pid, "party_id": self.w.supplier["id"], "bill_id": bill["id"]})
        t = self.c.provider.transfers[again["logical_op_id"]]
        self.assertEqual((t["value_date"], t["currency"], t["fee"], t["settled"]), (again["value_date"], "USD", "0.00", False))
        self.w.assert_books(self)

    def test_an_entity_or_currency_change_after_execution_fails_the_intent_at_dispatch(self):
        bill = self.w.posted_bill("20000")
        for column, value, expected in (("entity", "Another Entity LLC (synthetic)", "project entity changed after approval"),
                                        ("currency", "CAD", "project currency changed after approval")):
            intent = self.w.release(bill["id"])
            original = self.c.project(self.w.pid)[column]
            self.c.db.execute(f"UPDATE projects SET {column}=? WHERE id=?", (value, self.w.pid))
            try:
                out = self.c.dispatch_payments()
            finally:
                self.c.db.execute(f"UPDATE projects SET {column}=? WHERE id=?", (original, self.w.pid))
            self.assertEqual([(r["intent_id"], r["status"]) for r in out], [(intent["id"], "failed")], column)
            self.assertIn(expected, out[0]["reason"])
        self.assertEqual(len(self.c.provider.submissions), 0)
        self.assertEqual(self.c.bills.get(bill["id"])["status"], "posted")

    def test_the_payload_hash_binds_the_value_date_currency_and_entity(self):
        bill = self.w.posted_bill("20000")
        intent = self.w.release(bill["id"])
        payload = {"party_id": self.w.supplier["id"], "destination": DEST, "destination_version": intent["destination_version"], "amount": "18000.00",
                   "bill_id": bill["id"], "fee": "0.00", "value_date": intent["value_date"], "currency": "USD", "entity": ENTITY}
        self.assertEqual(intent["payload_hash"], hash_json(payload))
        self.assertNotEqual(intent["payload_hash"], hash_json(dict(payload, value_date="2020-01-01")))

    def test_provider_fee_must_be_exact_money(self):
        with self.assertRaises(Exception):
            SimulatedProvider(fee=0.59)  # binary floating point is refused
        with self.assertRaises(PaymentError):
            SimulatedProvider(fee="-0.01")
        self.assertEqual(SimulatedProvider(fee="0.5").fee_for("100.00"), "0.50")


# --------------------------------------------------------------------------- #
# 6. forecast isolation and the golden numbers                                 #
# --------------------------------------------------------------------------- #

class ForecastIsolationTests(unittest.TestCase):
    def test_paid_to_date_counts_only_the_projects_own_intents(self):
        a = World(name="Project A")
        c = a.c
        bill_a = a.posted_bill("20000")
        a.release(bill_a["id"])
        # project B: its own subcontract bill and a staff reimbursement (an intent with no bill)
        b = c.create_project(name="Project B", entity=ENTITY, budget="20000", customer_id=a.customer["id"])
        sup_b = c.add_party(kind="supplier", name="Synthetic Dewatering Sub", destination="ACH-SIM-CTL-B")
        c.verify_destination(sup_b["id"], destination="ACH-SIM-CTL-B", verified_by="owner")
        cmt_b = c.commitments.create(project_id=b["id"], supplier_id=sup_b["id"], title="Wellpoints", sov_lines=[{"description": "Wellpoints", "amount": "10000"}], actor="pm")
        c.approve_and_execute("commitment.execute", cmt_b["id"])
        line_b = c.commitments.get(cmt_b["id"])["sov"][0]["id"]
        bill_b = c.bills.certify(commitment_id=cmt_b["id"], period_id="P1", installed=[{"sov_line_id": line_b, "cumulative_installed": "10000"}], actor="pm")
        c.approve_and_execute("bill.approve", bill_b["id"])
        c.approve_and_execute("payment.release", bill_b["id"], actor_role="treasury", actor="treasury")
        r = c.plugin(REIMBURSEMENT)
        emp = c.add_party(kind="employee", name="Field Engineer", destination="ACH-SIM-EMP-B")
        c.verify_destination(emp["id"], destination="ACH-SIM-EMP-B", verified_by="owner")
        claim = r.submit_claim(project_id=b["id"], employee_id=emp["id"], description="Pump hire receipts", amount="120.00", receipt_hash="ctl-forecast-1", actor="emp")
        c.approve_and_execute("reimbursement.approve", claim["id"], period_id="P1")
        pay = r.record_payment(claim["id"], "120.00", actor="treasury")
        c.approve_and_execute("reimbursement.pay", pay["id"], actor_role="treasury", actor="treasury", period_id="P1")
        self.assertEqual([d["status"] for d in c.dispatch_payments()], ["accepted", "accepted", "accepted"])
        fa, fb = c.forecast.project(a.pid), c.forecast.project(b["id"])
        self.assertEqual(fa["paid_to_date"], "18000.00")  # previously 18120.00: B's reimbursement leaked in
        self.assertEqual(fb["paid_to_date"], "9120.00")
        # a canceled or returned intent pays nothing
        bill_a2 = a.posted_bill("30000")
        queued = a.release(bill_a2["id"])
        c.payments.cancel_intent(queued["id"], "duplicate release", "treasury")
        intent_b = [p for p in c.payments.list() if p["bill_id"] == bill_b["id"]][0]
        c.payments.ingest_event(c.provider.return_payment(intent_b["logical_op_id"]), actor="webhook")
        self.assertEqual(c.forecast.project(a.pid)["paid_to_date"], "18000.00")
        self.assertEqual(c.forecast.project(b["id"])["paid_to_date"], "120.00")
        self.assertTrue(c.ledger.trial_balance()["balanced"])


class ProcessingStateTests(unittest.TestCase):
    """The plan's processing state: after acceptance the rail reports processing (signed event);
    nothing is posted, the money stays in provider clearing, and settlement or a return follow."""

    def setUp(self):
        self.w = World()
        self.c = self.w.c
        self.bill = self.w.posted_bill("20000")
        intent = self.w.release(self.bill["id"])
        self.c.dispatch_payments()
        self.intent = self.c.payments.get(intent["id"])
        self.op = self.intent["logical_op_id"]

    def test_a_signed_processing_event_moves_an_accepted_intent_to_processing_without_posting(self):
        c = self.c
        self.assertEqual((self.intent["status"], self.intent["lifecycle_status"], self.intent["processing_at"]), ("accepted", "accepted", None))
        journals = self.w.journals()
        event = c.provider.process(self.op)
        self.assertEqual((event["id"], event["kind"], event["amount"]), ("evt_sim_000001_processing", "processing", "18000.00"))
        self.assertTrue(verify_event(event, c.provider.webhook_secret))
        self.assertTrue(c.payments.ingest_event(event, actor="webhook")["applied"])
        got = c.payments.get(self.intent["id"])
        self.assertEqual((got["status"], got["lifecycle_status"]), ("accepted", "processing"))
        self.assertIsNotNone(got["processing_at"])
        self.assertEqual(self.w.journals(), journals)  # nothing is posted
        clearing = c.payments.clearing_items()
        self.assertEqual((clearing["in_transit_total"], clearing["control_balance"], clearing["reconciled"]), ("18000.00", "-18000.00", True))
        self.assertEqual([p["id"] for p in c.payments.list(status="processing")], [self.intent["id"]])
        self.assertEqual([p["id"] for p in c.payments.list(status="accepted")], [self.intent["id"]])  # the accounting status is unchanged
        self.assertEqual(c.bills.get(self.bill["id"])["status"], "paid")
        dup = c.payments.ingest_event(event, actor="webhook")
        self.assertEqual((dup["applied"], dup["reason"]), (False, "duplicate event"))
        self.assertEqual([e["action"] for e in c.audit.entries(entity_id=self.intent["id"]) if e["action"] == "provider_event.processing"], ["provider_event.processing"])
        # processing -> settled books exactly as accepted -> settled always did
        self.assertTrue(c.payments.ingest_event(c.provider.settle(self.op), actor="webhook")["applied"])
        got = c.payments.get(self.intent["id"])
        self.assertEqual((got["status"], got["lifecycle_status"]), ("settled", "settled"))
        self.assertIsNotNone(got["processing_at"])  # history survives
        self.assertEqual((c.ledger.balance("1000"), c.ledger.balance("1200")), (D("-18000.00"), D("0.00")))
        self.assertEqual(c.payments.list(status="processing"), [])
        self.w.assert_books(self)

    def test_a_return_while_processing_reinstates_the_payable(self):
        c = self.c
        c.payments.ingest_event(c.provider.process(self.op), actor="webhook")
        self.assertTrue(c.payments.ingest_event(c.provider.return_payment(self.op, "account closed"), actor="webhook")["applied"])
        got = c.payments.get(self.intent["id"])
        self.assertEqual((got["status"], got["lifecycle_status"]), ("returned", "returned"))
        self.assertEqual((c.ledger.balance("1200"), c.ledger.balance("2000"), c.ledger.balance("1000")), (D("0.00"), D("18000.00"), D("0.00")))
        self.assertEqual(c.bills.get(self.bill["id"])["status"], "posted")
        self.w.assert_books(self)

    def test_a_processing_event_delivered_after_settlement_is_ignored(self):
        c = self.c
        processing = c.provider.process(self.op)
        settled = c.provider.settle(self.op)
        self.assertTrue(c.payments.ingest_event(settled, actor="webhook")["applied"])
        late = c.payments.ingest_event(processing, actor="webhook")
        self.assertEqual((late["applied"], late["reason"]), (False, "processing not applicable to settled"))
        got = c.payments.get(self.intent["id"])
        self.assertEqual((got["status"], got["lifecycle_status"], got["processing_at"]), ("settled", "settled", None))
        ignored = [json.loads(e["payload_json"]) for e in c.audit.entries(entity_id=self.intent["id"]) if e["action"] == "provider_event.ignored"]
        self.assertEqual((ignored[-1]["kind"], ignored[-1]["lifecycle_status"]), ("processing", "settled"))
        self.w.assert_books(self)

    def test_reconcile_catches_a_missing_processing_callback_exactly_once(self):
        c = self.c
        lost = c.provider.process(self.op)  # never delivered
        out = c.reconcile_payments()
        self.assertEqual([(r["intent_id"], r["status"], r["caught_up_event"], r["applied"]) for r in out],
                         [(self.intent["id"], "accepted", "recon_sim_000001_processing", True)])
        self.assertEqual(c.payments.get(self.intent["id"])["lifecycle_status"], "processing")
        self.assertEqual(c.reconcile_payments(), [])
        late = c.payments.ingest_event(lost, actor="webhook")
        self.assertEqual((late["applied"], late["reason"]), (False, "processing not applicable to processing"))
        self.assertEqual(len(c.ledger.journals(source_type="provider_event")), 0)
        # the provider then settles and that callback is lost too: reconciliation books it once
        c.provider.settle(self.op)
        self.assertEqual([(r["status"], r["caught_up_event"]) for r in c.reconcile_payments()], [("settled", "recon_sim_000001_settled")])
        self.assertEqual(c.ledger.balance("1000"), D("-18000.00"))
        self.w.assert_books(self)

    def test_forged_processing_events_and_processing_out_of_order_at_the_provider_are_refused(self):
        c = self.c
        genuine = c.provider.process(self.op)
        for forged in (dict(genuine, amount="1.00"), {k: v for k, v in genuine.items() if k != "signature"},
                       sign_event(dict(genuine, signature=None), SimulatedProvider().webhook_secret)):
            with self.assertRaises(ProviderEventRejected):
                c.payments.ingest_event(forged, actor="webhook")
        self.assertEqual(c.payments.get(self.intent["id"])["lifecycle_status"], "accepted")
        with self.assertRaisesRegex(ProviderEventRejected, "unknown provider_ref"):
            c.payments.ingest_event(sign_event(dict(genuine, id="evt_x", provider_ref="sim_999999", signature=None), c.provider.webhook_secret), actor="webhook")
        c.provider.settle(self.op)
        with self.assertRaisesRegex(PaymentError, "only an accepted transfer starts processing"):
            c.provider.process(self.op)

    def test_processing_is_recorded_while_every_period_is_closed_but_settlement_waits_for_an_open_period(self):
        c = self.c
        c.close_period("P1")
        journals = self.w.journals()
        self.assertTrue(c.payments.ingest_event(c.provider.process(self.op), actor="webhook")["applied"])  # nothing to post
        self.assertEqual(c.payments.get(self.intent["id"])["lifecycle_status"], "processing")
        settled = c.provider.settle(self.op)
        with self.assertRaisesRegex(PaymentError, "no open period"):
            c.payments.ingest_event(settled, actor="webhook")
        self.assertEqual((self.w.journals(), c.payments.get(self.intent["id"])["lifecycle_status"]), (journals, "processing"))
        c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        self.assertTrue(c.payments.ingest_event(settled, actor="webhook")["applied"])
        [j] = c.ledger.journals(source_type="provider_event")
        self.assertEqual((j["period_id"], c.payments.get(self.intent["id"])["lifecycle_status"]), ("P2", "settled"))
        self.w.assert_books(self)

    def test_stale_processing_lists_intents_processing_longer_than_the_threshold(self):
        c = self.c
        self.assertEqual(c.payments.stale_processing(), [])
        c.payments.ingest_event(c.provider.process(self.op), actor="webhook")
        now = utcnow()
        self.assertEqual(c.payments.stale_processing(3, now=now), [])
        self.assertEqual(c.payments.stale_processing(3, now=now + _dt.timedelta(days=2)), [])
        [stale] = c.payments.stale_processing(3, now=now + _dt.timedelta(days=4))
        self.assertEqual((stale["intent_id"], stale["amount"], stale["days_processing"], stale["threshold_days"], stale["lifecycle_status"]),
                         (self.intent["id"], "18000.00", 4, 3, "processing"))
        self.assertEqual(len(c.payments.stale_processing(now=now + _dt.timedelta(days=payments_module.STALE_PROCESSING_DAYS, hours=1))), 1)
        for bad in (-1, True, "3", 1.5, None):
            with self.assertRaises(PaymentError):
                c.payments.stale_processing(bad)
        # a timezone-naive "now" (what datetime.utcnow() returns) is read as UTC, not a TypeError
        naive = (now + _dt.timedelta(days=4)).replace(tzinfo=None)
        self.assertEqual([s["intent_id"] for s in c.payments.stale_processing(3, now=naive)], [self.intent["id"]])
        self.assertEqual(c.payments.stale_processing(3, now=(now + _dt.timedelta(days=2)).replace(tzinfo=None)), [])
        for bad_now in ("2026-10-20T00:00:00Z", 1760000000, _dt.date(2026, 10, 20)):
            with self.assertRaisesRegex(PaymentError, "now must be a datetime"):
                c.payments.stale_processing(3, now=bad_now)
        c.payments.ingest_event(c.provider.settle(self.op), actor="webhook")
        self.assertEqual(c.payments.stale_processing(0, now=now + _dt.timedelta(days=30)), [])

    def test_the_schema_writes_each_lifecycle_marker_once_and_only_from_its_accounting_status(self):
        c = self.c
        with self.assertRaisesRegex(sqlite3.DatabaseError, "bank-reconciled once, only after it settled"):
            c.db.execute("UPDATE payment_intents SET bank_reconciled_at='t', bank_reconciliation_id='brc_x', bank_journal_line_id='jl_x' WHERE id=?", (self.intent["id"],))
        c.payments.ingest_event(c.provider.process(self.op), actor="webhook")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "enters processing once"):
            c.db.execute("UPDATE payment_intents SET processing_at='2026-01-01T00:00:00Z' WHERE id=?", (self.intent["id"],))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "enters processing once"):
            c.db.execute("UPDATE payment_intents SET processing_at=NULL WHERE id=?", (self.intent["id"],))
        c.payments.ingest_event(c.provider.settle(self.op), actor="webhook")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "bank-reconciled once"):  # a settled intent still needs all three facts
            c.db.execute("UPDATE payment_intents SET bank_reconciled_at='t' WHERE id=?", (self.intent["id"],))
        settlement = c.ledger.journals(source_type="provider_event")[0]
        line = next(ln for ln in settlement["lines"] if ln["account_code"] == "1000")
        other = next(ln for ln in settlement["lines"] if ln["account_code"] != "1000")
        # raw SQL cannot mark a settled intent bank-reconciled: the line must be its own settlement bank line ...
        for bogus_line in ("y", other["id"]):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "only against its own settlement bank line"):
                c.db.execute("UPDATE payment_intents SET bank_reconciled_at='t', bank_reconciliation_id='x', bank_journal_line_id=? WHERE id=?",
                             (bogus_line, self.intent["id"]))
        # ... and a locked bank reconciliation must have matched that line to a statement line
        with self.assertRaisesRegex(sqlite3.DatabaseError, "only by a locked bank reconciliation"):
            c.db.execute("UPDATE payment_intents SET bank_reconciled_at='t', bank_reconciliation_id='brc_forged', bank_journal_line_id=? WHERE id=?",
                         (line["id"], self.intent["id"]))
        with self.assertRaisesRegex(PaymentError, "not matched to a bank statement line in a locked bank reconciliation"):
            c.payments.mark_bank_reconciled_for_journal_lines([line["id"]], "reconciler")
        self.assertEqual(c.payments.get(self.intent["id"])["lifecycle_status"], "settled")
        self.assertEqual(c.payments.list(status="bank_reconciled"), [])
        for bad in ("jl_1", None, [None], [""]):
            with self.assertRaises(PaymentError):
                c.payments.mark_bank_reconciled_for_journal_lines(bad, "reconciler")
        self.assertEqual(c.payments.mark_bank_reconciled_for_journal_lines([], "reconciler")["advanced"], [])
        self.assertEqual(payments_module.LIFECYCLE_SCHEMA_NAME, "payments_lifecycle")
        applied = [v["name"] for v in c.db.schema_status()["versions"] if v["applied"]]
        for name in ("payments_lifecycle", payments_module.LIFECYCLE_PROOF_SCHEMA_NAME, BANKING_GUARD_SCHEMA_NAME):
            self.assertIn(name, applied)
        # the guard entry follows the lifecycle columns and the banking tables it names
        self.assertLess(applied.index("payments_lifecycle"), applied.index(BANKING_GUARD_SCHEMA_NAME))
        self.assertLess(applied.index("banking"), applied.index(BANKING_GUARD_SCHEMA_NAME))


class ProcessingAdoptionTests(unittest.TestCase):
    def test_a_transfer_the_provider_is_still_processing_is_adopted_as_processing(self):
        w, d = file_world(self)
        bill = w.posted_bill("20000")
        backup = w.c.snapshot(os.path.join(d, "older-than-the-release.sqlite"))
        live = w.release(bill["id"])
        self.assertEqual([r["status"] for r in w.c.dispatch_payments()], ["accepted"])
        w.c.payments.ingest_event(w.c.provider.process(live["logical_op_id"]), actor="webhook")
        self.assertEqual(w.c.payments.get(live["id"])["lifecycle_status"], "processing")
        restored = restored_copy(self, w, backup)
        claim_restored_copy(restored)
        outcome = restored.complete_recovery(actor="reconciler")
        [t] = outcome["unrecorded_transfers"]
        self.assertEqual((t["provider_ref"], t["status"], t["adoptable"]), ("sim_000001", "processing", True))
        res = restored.approve_and_execute("payment.adopt_transfer", "sim_000001", actor_role="owner").result
        self.assertEqual((res["status"], [cb["caught_up_event"] for cb in res["callbacks"]]), ("accepted", ["recon_sim_000001_processing"]))
        got = restored.payments.get(res["intent"])
        self.assertEqual((got["status"], got["lifecycle_status"]), ("accepted", "processing"))
        self.assertTrue(restored.complete_recovery(actor="reconciler")["quarantine_lifted"])
        self.assertEqual((len(w.c.provider.submissions), len(w.c.provider.transfers)), (1, 1))
        self.assertTrue(restored.ledger.trial_balance()["balanced"] and restored.payments.clearing_items()["reconciled"])
        self.assertTrue(restored.bills.ap_open_items()["reconciled"])


class LifecycleMigrationTests(unittest.TestCase):
    def test_a_workspace_from_before_the_lifecycle_and_payee_change_entries_migrates_with_its_payments_intact(self):
        from apps.cipher.core import db as core_db
        d = tempfile.mkdtemp(prefix="cipher-lifecycle-")
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "older-release.sqlite")
        # an older release had none of the lifecycle and payee-change entries, nor the later ones that build on them
        new_entries = (payments_module.LIFECYCLE_SCHEMA_NAME, payments_module.DESTINATION_SCHEMA_NAME, payments_module.DESTINATION_VERIFICATION_SCHEMA_NAME,
                       payments_module.LIFECYCLE_PROOF_SCHEMA_NAME, BANKING_GUARD_SCHEMA_NAME)
        legacy_catalog = [e for e in core_db.SCHEMA_CATALOG if e[1] not in new_entries]
        with mock.patch.object(core_db, "SCHEMA_CATALOG", legacy_catalog):
            w = World(path)
            c = w.c
            self.assertNotIn("processing_at", {r["name"] for r in c.db.query("PRAGMA table_info(payment_intents)")})
            settled = w.release(w.posted_bill("20000")["id"])
            c.dispatch_payments()
            c.payments.ingest_event(c.provider.settle(settled["logical_op_id"]), actor="webhook")
            accepted = w.release(w.posted_bill("30000")["id"])
            c.dispatch_payments()
            self.assertEqual([p["lifecycle_status"] for p in c.payments.list()], ["settled", "accepted"])
            provider = c.provider
            c.db.close()
        reopened = Cipher(path, provider=provider)
        self.addCleanup(reopened.db.close)
        status = {v["name"]: v for v in reopened.db.schema_status()["versions"]}
        self.assertTrue(all(status[name]["applied"] for name in new_entries))
        self.assertIn("processing_at", {r["name"] for r in reopened.db.query("PRAGMA table_info(payment_intents)")})
        self.assertEqual([(p["id"], p["status"], p["lifecycle_status"]) for p in reopened.payments.list()],
                         [(settled["id"], "settled", "settled"), (accepted["id"], "accepted", "accepted")])
        # the older accepted payment now moves through processing to settlement as any other
        reopened.payments.ingest_event(provider.process(accepted["logical_op_id"]), actor="webhook")
        self.assertEqual(reopened.payments.get(accepted["id"])["lifecycle_status"], "processing")
        reopened.payments.ingest_event(provider.settle(accepted["logical_op_id"]), actor="webhook")
        change = reopened.payments.request_destination_change(w.supplier["id"], "ACH-SIM-CTL-0002", "ap-clerk", "new bank", "ap-clerk")
        self.assertEqual(change["status"], "pending")
        triggers = {r["name"] for r in reopened.db.query("SELECT name FROM sqlite_master WHERE type='trigger'")}
        for name in ("payment_intents_bank_reconciled_once", "banking_payment_bank_reconciled_needs_locked_match", "destination_changes_lifecycle"):
            self.assertIn(name, triggers)
        self.assertEqual(reopened.db.migrate(), [])
        self.assertTrue(reopened.ledger.trial_balance()["balanced"] and reopened.audit.verify_chain()["ok"])
        self.assertTrue(reopened.bills.ap_open_items()["reconciled"] and reopened.payments.clearing_items()["reconciled"])


class GoldenNumbersTests(unittest.TestCase):
    def test_golden_fixture_numbers_are_unchanged(self):
        c = Cipher()
        r = run_golden_fixture(c)
        self.assertEqual(r["executed_amount"], "122000.00")
        self.assertEqual((r["bill1"]["amount_due"], r["bill2"]["amount_due"]), ("27000.00", "18000.00"))
        f = r["forecast_before_change"]
        self.assertEqual((f["executed_commitments"], f["pending_exposure"], f["forecast_at_completion"], f["variance_to_budget"], f["paid_to_date"]),
                         ("110000.00", "12000.00", "122000.00", "-7000.00", "27000.00"))
        self.assertEqual((r["prime"]["amount_due"], r["bank"], r["fees"], r["cost"], r["stored"]), ("54000.00", "-27005.00", "5.00", "45000.00", "5000.00"))
        self.assertEqual((r["payment"]["transfers"], r["payment"]["status"], r["payment"]["duplicate_event"]["applied"]), (1, "settled", False))
        self.assertEqual(r["payment"]["dispatch"][0]["status"], "outcome_unknown")
        self.assertEqual(r["payment"]["reconciled"][0]["status"], "accepted")
        self.assertTrue(r["trial_balance"]["balanced"] and r["ap"]["reconciled"] and r["audit"]["ok"])
        clearing = c.payments.clearing_items()
        self.assertEqual((clearing["subledger_total"], clearing["control_balance"], clearing["reconciled"]), ("0.00", "0.00", True))
        self.assertEqual(c.payments.release_allowed(), (True, "ok"))

    def test_demo_command_prints_the_golden_numbers(self):
        from apps.cipher.__main__ import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main(["demo"]), 0)
        out = json.loads(buf.getvalue())
        self.assertEqual((out["executed_amount"], out["bill1"]["amount_due"], out["bill2"]["amount_due"], out["bank"], out["cost"], out["stored"]),
                         ("122000.00", "27000.00", "18000.00", "-27005.00", "45000.00", "5000.00"))
        self.assertEqual(out["forecast"], {"budget": "115000.00", "executed_commitments": "110000.00", "pending_exposure": "12000.00",
                                           "forecast_at_completion": "122000.00", "variance_to_budget": "-7000.00"})
        self.assertEqual(out["payment"], {"transfers": 1, "status": "settled", "replay_replayed": True})
        self.assertTrue(out["trial_balance_balanced"] and out["ap_reconciled"])


if __name__ == "__main__":
    unittest.main()
