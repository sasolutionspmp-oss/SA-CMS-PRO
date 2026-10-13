"""High-risk payment release policy (plan section 6): hash-chained policy versions changed only by
``payment_policy.update``, classification of every release, independent approval and release,
fresh single-use step-up, independent co-signature (the solo owner's external accountant),
cooling-off after a payee destination change, invalidation when the policy moves, raw-SQL
tampering, and the guarantee that without a policy nothing changes.

All parties, amounts and documents are synthetic."""
import datetime as _dt
import os
import re
import sqlite3
import unittest

from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.ids import canonical_json, hash_json, sha256_hex, utcnow
from apps.cipher.domain import payment_policy as pp_mod
from apps.cipher.domain.payment_policy import (
    GOVERNED_OPERATIONS, OP_UPDATE, PLUGIN_NAME, CoolingOffHold, CosignatureRequired, DraftStale, IndependenceRequired, PaymentPolicyError,
    PolicyIntegrityError, PolicyRefused, StepUpRequired,
)
from apps.cipher.domain.payments import VERIFY_DESTINATION_OPERATION, KillSwitchEngaged
from apps.cipher.service import Cipher, RoleNotAuthorized, run_golden_fixture

ENTITY = "S&A Solutions LLC (synthetic)"
OLD = "ACH-SIM-PP-0001"
NEW = "ACH-SIM-PP-0002"
CALL_BACK = "call-back to number on file"


class World:
    """A sheet-piling subcontractor with a fixture-verified destination (version 2), a cofferdam
    project, an executed 400,000 subcontract without retainage and an open period P1."""

    def __init__(self):
        self.c = Cipher()
        self.pp = self.c.plugin(PLUGIN_NAME)
        sup = self.c.add_party(kind="supplier", name="Synthetic Sheet Pile Subcontractor", destination=OLD)
        self.sup = self.c.verify_destination(sup["id"], destination=OLD, verified_by="owner")
        self.sid = self.sup["id"]
        customer = self.c.add_party(kind="customer", name="Synthetic Port Authority")
        self.project = self.c.create_project(name="Cofferdam, sheet piling and dewatering", entity=ENTITY, budget="500000", customer_id=customer["id"])
        self.pid = self.project["id"]
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        cmt = self.c.commitments.create(project_id=self.pid, supplier_id=self.sid, title="Sheet piling, cofferdam and dewatering",
                                        sov_lines=[{"description": "Sheet piling", "amount": "300000"}, {"description": "Dewatering", "amount": "100000"}],
                                        retainage_rate="0", actor="pm")
        self.c.approve_and_execute("commitment.execute", cmt["id"])
        self.cmt = self.c.commitments.get(cmt["id"])
        self.line1 = self.cmt["sov"][0]["id"]
        self.installed = 0
        self.assertions = 0
        self.docs = 0

    # ---- records ---------------------------------------------------------------------- #

    def bill(self, amount: int) -> dict:
        """Certify and post a bill whose amount due is ``amount``."""
        self.installed += amount
        b = self.c.bills.certify(commitment_id=self.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.line1, "cumulative_installed": str(self.installed)}], actor="pm")
        self.c.approve_and_execute("bill.approve", b["id"])
        return self.c.bills.get(b["id"])

    def adopt(self, *, high="10000.00", cosign="50000.00", age=300, cooling=10, first=True, parties=("ext-accountant",), cosign_all=False,
              reason="owner and external accountant release control", cosigner=None) -> dict:
        d = self.pp.draft_policy(high_risk_amount=high, cosign_amount=cosign, step_up_max_age_seconds=age, new_destination_cooling_days=cooling,
                                 first_payment_to_destination_is_high_risk=first, independent_parties=list(parties), cosign_all_high_risk=cosign_all,
                                 reason=reason, actor="owner")
        ap = self.c.request_approval(OP_UPDATE, d["id"], actor_role="owner", requested_by="owner")
        self.c.approve(ap["id"], approver="owner")
        if cosigner:
            self.pp.cosign(ap["id"], cosigner, cosigner)
        self.c.execute(ap["id"], actor="owner")
        return self.pp.policy()

    def request(self, bill_id: str, *, requested_by="ap-clerk", op="payment.release") -> dict:
        return self.c.request_approval(op, bill_id, actor_role="treasury", requested_by=requested_by)

    def granted(self, bill_id: str, *, requested_by="ap-clerk", approver="owner", approver_role="owner", op="payment.release") -> dict:
        ap = self.request(bill_id, requested_by=requested_by, op=op)
        return self.c.approve(ap["id"], approver=approver, approver_role=approver_role)

    def step_up(self, login="treasury", method="webauthn") -> dict:
        self.assertions += 1
        return self.pp.record_step_up(login, method, sha256_hex(f"synthetic assertion {self.assertions}"), "sign-in-service")

    def settle_last(self) -> dict:
        self.c.dispatch_payments()
        intent = self.c.payments.list()[-1]
        self.c.payments.ingest_event(self.c.provider.settle(intent["logical_op_id"]), actor="webhook")
        return self.c.payments.get(intent["id"])

    def change_destination(self, new=NEW) -> dict:
        """A governed payee destination change: requested, independently verified, executed."""
        self.docs += 1
        doc = self.c.evidence.register_document(project_id=self.pid, kind="destination_verification", title=f"Payee call-back {self.docs}", actor="bank-admin")
        rev = self.c.evidence.add_revision(document_id=doc["id"], content=f"synthetic call-back record {self.docs}".encode(), note="call-back", actor="bank-admin")
        change_id = self.c.payments.governed_destination_change(self.sid, new, "ap-clerk", "ext-accountant", CALL_BACK, rev["content_hash"], "bank-admin")
        ap = self.c.request_approval(VERIFY_DESTINATION_OPERATION, change_id, actor_role="bank_admin", requested_by="bank-admin")
        self.c.approve(ap["id"], approver="owner")
        self.c.execute(ap["id"], actor="bank-admin")
        return self.c.payments.destination_change(change_id)

    def facts(self, approval: dict) -> dict | None:
        return (approval["manifest"].get("governance") or {}).get(PLUGIN_NAME)

    def move_clock(self, **delta):
        base = utcnow()
        self.pp.now = lambda: base + _dt.timedelta(**delta)


class PeopleStub:
    """The shared identity interface the people plugin implements (is_active, holds, is_external,
    person_for, enforcing), with fixed answers."""

    def __init__(self, persons: dict, *, externals=(), inactive=(), services=(), enforce=True):
        self.persons, self.externals, self.inactive, self.services, self.enforce = persons, set(externals), set(inactive), set(services), enforce

    def enforcing(self):
        return self.enforce

    def is_active(self, login):
        return login in self.persons and login not in self.inactive

    def holds(self, login, role, *, project_id=None):
        return self.is_active(login)

    def is_external(self, login):
        return self.is_active(login) and login in self.externals

    def person_for(self, login):
        if login not in self.persons:
            return None
        return {"id": self.persons[login], "login": login, "kind": "service" if login in self.services else "person"}


STAFF = (("ap-clerk", "person", False), ("treasury", "person", False), ("ext-accountant", "person", True))


def enforce_identity(w: World, persons=STAFF, *, treasury=("treasury",)):
    """Turn the real people registry on: the owner bootstrapped, each (login, kind, external) of
    ``persons`` registered by the owner, treasury granted to the ``treasury`` logins, and an
    enforcing identity policy adopted.  Returns the people plugin."""
    people = w.c.plugin("people")
    people.bootstrap_owner("owner", "Synthetic owner")
    for login, kind, external in persons:
        people.register_person(login, f"Synthetic {login}", actor="owner", kind=kind, external=external)
    for login in treasury:
        w.c.approve_and_execute("people.grant_role", people.request_grant(login, "treasury", reason="releases payments", actor="owner")["id"])
    w.c.approve_and_execute("people.set_policy", people.prepare_policy(enforce=True, segregate=False, reason="identity enforcement", actor="owner")["id"])
    return people


# --------------------------------------------------------------------------- #
# 1. without a policy nothing changes                                          #
# --------------------------------------------------------------------------- #

class NoPolicyTests(unittest.TestCase):
    def test_golden_fixture_is_unchanged_without_a_policy(self):
        c = Cipher()
        r = run_golden_fixture(c)
        bare = Cipher()
        bare._plugins.pop(PLUGIN_NAME)
        b = run_golden_fixture(bare)
        for key in ("executed_amount", "sov", "bill1", "bill2", "prime", "bank", "fees", "cost", "stored", "stale_result", "ap_bill3_status"):
            self.assertEqual(r[key], b[key], key)
        self.assertEqual((r["payment"]["status"], r["payment"]["transfers"]), ("settled", 1))
        self.assertEqual((r["bill1"]["amount_due"], r["bill2"]["amount_due"], r["executed_amount"]), ("27000.00", "18000.00", "122000.00"))
        self.assertTrue(r["trial_balance"]["balanced"] and r["audit"]["ok"])
        for ap in c.approvals.list():
            self.assertNotIn(PLUGIN_NAME, ap["manifest"].get("governance") or {})
        pp = c.plugin(PLUGIN_NAME)
        for table in ("payment_policy_versions", "payment_policy_drafts", "payment_policy_step_ups", "payment_policy_cosignatures", "payment_policy_clearances"):
            self.assertEqual(c.db.scalar(f"SELECT COUNT(*) FROM {table}"), 0, table)
        self.assertEqual(pp.close_checks("2026-11"), [])
        self.assertIsNone(pp.policy())
        self.assertFalse(c.project_state(r["project_id"])[PLUGIN_NAME]["configured"])
        self.assertEqual([ch for ch in c.plugin("close").checklist("2026-11") if ch["source"] == PLUGIN_NAME], [])

    def test_without_a_policy_one_person_may_still_request_approve_and_release(self):
        w = World()
        b = w.bill(250000)
        ap = w.c.request_approval("payment.release", b["id"], actor_role="treasury", requested_by="owner")
        self.assertNotIn("governance", ap["manifest"])
        w.c.approve(ap["id"], approver="owner")
        res = w.c.execute(ap["id"], actor="owner")
        self.assertEqual(res.result["amount"], "250000.00")
        self.assertEqual(w.pp.clearances(), [])

    def test_the_governed_operations_are_every_path_that_creates_a_payment_intent(self):
        """Tripwire: a new caller of Payments.create_intent is a new way to release money and must
        be added to GOVERNED_OPERATIONS (and this list) before it ships."""
        self.assertEqual(set(GOVERNED_OPERATIONS), {"payment.release", "payment.release_retainage", "reimbursement.pay"})
        root = os.path.dirname(os.path.dirname(os.path.abspath(pp_mod.__file__)))
        callers = {}
        sources = [os.path.join(root, "service.py")] + [os.path.join(root, "domain", f) for f in os.listdir(os.path.join(root, "domain")) if f.endswith(".py")]
        for path in sources:
            with open(path, encoding="utf-8") as fh:
                n = len(re.findall(r"\.create_intent\(", fh.read()))
            if n:
                callers[os.path.basename(path)] = n
        self.assertEqual(callers, {"service.py": 2, "reimbursements.py": 1},
                         "a new create_intent caller appeared: govern its operation in payment_policy.GOVERNED_OPERATIONS")


# --------------------------------------------------------------------------- #
# 2. policy versions                                                           #
# --------------------------------------------------------------------------- #

class PolicyVersionTests(unittest.TestCase):
    def test_a_policy_is_adopted_only_by_the_owner_through_an_approval_and_is_hash_chained(self):
        w = World()
        d = w.pp.draft_policy(high_risk_amount="10000", cosign_amount="50000", step_up_max_age_seconds=300, new_destination_cooling_days=10,
                              first_payment_to_destination_is_high_risk=True, independent_parties=["ext-accountant"], reason="solo-owner control", actor="owner")
        self.assertEqual((d["status"], d["base_version"], d["terms"]["high_risk_amount"]), ("pending", 0, "10000.00"))
        self.assertIsNone(w.pp.policy())  # a draft changes nothing
        for role in ("treasury", "accountant", "controller", "pm"):
            with self.subTest(role=role), self.assertRaises(RoleNotAuthorized):
                w.c.request_approval(OP_UPDATE, d["id"], actor_role=role)
        ap = w.c.request_approval(OP_UPDATE, d["id"], actor_role="owner", requested_by="owner")
        self.assertEqual(ap["manifest"]["bindings"]["draft_hash"], d["content_hash"])
        with self.assertRaises(RoleNotAuthorized):
            w.c.approve(ap["id"], approver="treasury-lead", approver_role="treasury")
        w.c.approve(ap["id"], approver="owner")
        res = w.c.execute(ap["id"], actor="owner")
        self.assertEqual(res.result["payment_policy_version"], 1)
        v1 = w.pp.policy()
        self.assertEqual((v1["version"], v1["prev_hash"], v1["approval_id"]), (1, pp_mod.GENESIS_HASH, ap["id"]))
        self.assertEqual(w.pp.draft(d["id"])["status"], "adopted")
        v2 = w.adopt(high="5000.00")  # tightening needs no co-signature
        self.assertEqual((v2["version"], v2["prev_hash"]), (2, v1["hash"]))
        chain = w.pp.verify_chain()
        self.assertTrue(chain["ok"], chain)
        self.assertEqual((chain["versions"], chain["head"]), (2, v2["hash"]))
        self.assertEqual([v["version"] for v in w.c.audit_export()["modules"][PLUGIN_NAME]["versions"]], [1, 2])

    def test_draft_terms_are_validated(self):
        w = World()
        good = dict(high_risk_amount="10000", cosign_amount="50000", step_up_max_age_seconds=300, new_destination_cooling_days=10,
                    first_payment_to_destination_is_high_risk=True, independent_parties=["ext-accountant"], reason="r", actor="owner")
        bad = [dict(cosign_amount="9999.99"), dict(high_risk_amount=10000.0), dict(high_risk_amount="0"), dict(high_risk_amount="100.001"),
               dict(high_risk_amount=True), dict(step_up_max_age_seconds=0), dict(step_up_max_age_seconds=3601), dict(step_up_max_age_seconds=True),
               dict(new_destination_cooling_days=-1), dict(new_destination_cooling_days=91), dict(first_payment_to_destination_is_high_risk="yes"),
               dict(independent_parties="ext-accountant"), dict(independent_parties=["ext-accountant", "EXT-Accountant "]),
               dict(independent_parties=['quote"d']), dict(reason=" "), dict(actor="")]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(PaymentPolicyError):
                w.pp.draft_policy(**dict(good, **change))
        self.assertEqual(w.pp.drafts(), [])
        w.adopt()
        with self.assertRaises(PaymentPolicyError):  # a draft that repeats the current version changes nothing
            w.pp.draft_policy(**dict(good, high_risk_amount="10000.00"))

    def test_a_draft_against_an_older_version_is_stale_and_its_approval_invalidated(self):
        w = World()
        a = w.pp.draft_policy(high_risk_amount="10000", cosign_amount="50000", step_up_max_age_seconds=300, new_destination_cooling_days=10,
                              first_payment_to_destination_is_high_risk=True, independent_parties=["ext-accountant"], reason="a", actor="owner")
        b = w.pp.draft_policy(high_risk_amount="20000", cosign_amount="50000", step_up_max_age_seconds=300, new_destination_cooling_days=10,
                              first_payment_to_destination_is_high_risk=True, independent_parties=["ext-accountant"], reason="b", actor="owner")
        ap_b = w.c.request_approval(OP_UPDATE, b["id"], actor_role="owner")
        w.c.approve(ap_b["id"])
        ap_a = w.c.request_approval(OP_UPDATE, a["id"], actor_role="owner")
        w.c.approve(ap_a["id"])
        w.c.execute(ap_a["id"])
        self.assertEqual(w.pp.draft(b["id"])["status"], "superseded")
        self.assertEqual(w.c.approvals.get(ap_b["id"])["status"], "invalidated")
        with self.assertRaises((ApprovalNotGranted, StaleApprovalError)):
            w.c.execute(ap_b["id"])
        with self.assertRaises(DraftStale):
            w.c.request_approval(OP_UPDATE, b["id"], actor_role="owner")
        self.assertEqual(w.pp.policy()["version"], 1)

    def test_weakening_the_policy_needs_an_independent_co_signature(self):
        w = World()
        w.adopt()
        d = w.pp.draft_policy(high_risk_amount="100000", cosign_amount="500000", step_up_max_age_seconds=3600, new_destination_cooling_days=0,
                              first_payment_to_destination_is_high_risk=False, independent_parties=["ext-accountant"], reason="loosen", actor="owner")
        ap = w.c.request_approval(OP_UPDATE, d["id"], actor_role="owner")
        self.assertTrue(ap["manifest"]["bindings"]["cosign_required"])
        self.assertEqual(set(ap["manifest"]["bindings"]["weakens"]), {"high_risk_amount_raised", "cosign_amount_raised", "step_up_max_age_lengthened",
                                                                      "cooling_off_shortened", "first_payment_rule_turned_off"})
        w.c.approve(ap["id"])
        with self.assertRaises(CosignatureRequired):  # the owner cannot lower the bar alone
            w.c.execute(ap["id"])
        self.assertEqual(w.c.approvals.get(ap["id"])["status"], "granted")
        self.assertEqual(w.pp.policy()["version"], 1)
        with self.assertRaises(IndependenceRequired):  # the owner is not an independent party
            w.pp.cosign(ap["id"], "owner", "owner")
        with self.assertRaises(PolicyRefused):  # a co-signature is the co-signer's own act
            w.pp.cosign(ap["id"], "ext-accountant", "owner")
        w.pp.cosign(ap["id"], "ext-accountant", "ext-accountant")
        with self.assertRaises(PaymentPolicyError):  # one co-signature per approval
            w.pp.cosign(ap["id"], "ext-accountant", "ext-accountant")
        self.assertEqual(w.c.execute(ap["id"]).result["payment_policy_version"], 2)

    def test_adding_an_independent_party_is_weakening_once_one_is_named(self):
        w = World()
        w.adopt(parties=())  # naming no one is allowed (an enforcing people registry may supply externals)
        v2 = w.adopt(parties=("ext-accountant",))  # naming the first outside party sets the control up
        self.assertEqual(v2["terms"]["independent_parties"], ["ext-accountant"])
        d = w.pp.draft_policy(high_risk_amount="10000", cosign_amount="50000", step_up_max_age_seconds=300, new_destination_cooling_days=10,
                              first_payment_to_destination_is_high_risk=True, independent_parties=["ext-accountant", "owner-alt"], reason="add", actor="owner")
        ap = w.c.request_approval(OP_UPDATE, d["id"], actor_role="owner")
        self.assertEqual(ap["manifest"]["bindings"]["weakens"], ["independent_party_added:owner-alt"])
        w.c.approve(ap["id"])
        with self.assertRaises(CosignatureRequired):
            w.c.execute(ap["id"])
        w.pp.cosign(ap["id"], "ext-accountant", "ext-accountant")
        self.assertEqual(w.c.execute(ap["id"]).result["payment_policy_version"], 3)

    def test_removing_the_last_independent_party_is_weakening(self):
        """Otherwise the owner swaps the outside party alone in two steps: drop it (nothing named,
        so nothing to co-sign) and name their own second login as the "first" party."""
        w = World()
        w.adopt(parties=("ext-accountant",))
        d = w.pp.draft_policy(high_risk_amount="10000", cosign_amount="50000", step_up_max_age_seconds=300, new_destination_cooling_days=10,
                              first_payment_to_destination_is_high_risk=True, independent_parties=[], reason="drop the accountant", actor="owner")
        ap = w.c.request_approval(OP_UPDATE, d["id"], actor_role="owner")
        self.assertEqual(ap["manifest"]["bindings"]["weakens"], ["independent_parties_removed:ext-accountant"])
        self.assertEqual(ap["manifest"]["bindings"]["cosigners_allowed"], ["ext-accountant"])
        w.c.approve(ap["id"])
        with self.assertRaises(CosignatureRequired):
            w.c.execute(ap["id"])
        self.assertEqual(w.pp.policy()["terms"]["independent_parties"], ["ext-accountant"])
        w.pp.cosign(ap["id"], "ext-accountant", "ext-accountant")  # the outside party agrees to step down
        self.assertEqual(w.c.execute(ap["id"]).result["payment_policy_version"], 2)
        # removing one of several named parties leaves the control in place and is not weakening
        w2 = World()
        w2.adopt(parties=("ext-accountant", "ext-auditor"))
        d2 = w2.pp.draft_policy(high_risk_amount="10000", cosign_amount="50000", step_up_max_age_seconds=300, new_destination_cooling_days=10,
                                first_payment_to_destination_is_high_risk=True, independent_parties=["ext-accountant"], reason="auditor engagement ended",
                                actor="owner")
        self.assertEqual(w2.c.request_approval(OP_UPDATE, d2["id"], actor_role="owner")["manifest"]["bindings"]["weakens"], [])

    def test_withdrawing_a_draft_invalidates_its_approval(self):
        w = World()
        d = w.pp.draft_policy(high_risk_amount="10000", cosign_amount="50000", step_up_max_age_seconds=300, new_destination_cooling_days=10,
                              first_payment_to_destination_is_high_risk=True, independent_parties=[], reason="x", actor="owner")
        ap = w.c.request_approval(OP_UPDATE, d["id"], actor_role="owner")
        w.pp.withdraw_draft(d["id"], "drafted in error", "owner")
        self.assertEqual(w.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(w.pp.draft(d["id"])["status"], "withdrawn")


# --------------------------------------------------------------------------- #
# 3. classification                                                            #
# --------------------------------------------------------------------------- #

class ClassificationTests(unittest.TestCase):
    def test_amount_first_payment_and_cosign_reasons_are_bound(self):
        w = World()
        w.adopt(high="10000.00", cosign="50000.00", first=False)
        small, big, huge = w.bill(9999), w.bill(10000), w.bill(50000)
        f = w.facts(w.request(small["id"]))
        self.assertEqual((f["classification"], f["reasons"], f["cosign_required"]), ("standard", [], False))
        f = w.facts(w.request(big["id"]))
        self.assertEqual((f["classification"], f["reasons"], f["cosign_required"]), ("high_risk", ["amount_at_or_over_high_risk_amount"], False))
        f = w.facts(w.request(huge["id"]))
        self.assertEqual((f["cosign_required"], f["cosign_reasons"]), (True, ["amount_at_or_over_cosign_amount"]))
        self.assertEqual(f["policy_version"], 1)
        self.assertEqual(f["destination"]["party_id"], w.sid)
        self.assertNotIn(OLD, str(f))  # destination facts carry the version, never the account

    def test_a_destination_version_that_never_received_a_settled_payment_is_high_risk_until_one_settles(self):
        w = World()
        w.adopt(high="100000.00", cosign="200000.00", first=True)
        first = w.bill(1000)
        ap = w.granted(first["id"])
        self.assertEqual(w.facts(ap)["reasons"], ["first_payment_to_destination_version"])
        w.step_up()
        w.c.execute(ap["id"], actor="treasury")
        w.settle_last()
        second = w.bill(1000)
        f = w.facts(w.request(second["id"]))
        self.assertEqual((f["classification"], f["destination"]["has_settled_payment"]), ("standard", True))

    def test_cosign_every_high_risk_release_when_the_policy_says_so(self):
        w = World()
        w.adopt(high="10000.00", cosign="900000.00", first=False, cosign_all=True)
        f = w.facts(w.request(w.bill(10000)["id"]))
        self.assertEqual((f["cosign_required"], f["cosign_reasons"]), (True, ["policy_cosigns_every_high_risk_release"]))

    def test_retainage_and_reimbursement_releases_are_governed_too(self):
        w = World()
        cmt = w.c.commitments.create(project_id=w.pid, supplier_id=w.sid, title="Dewatering wells", sov_lines=[{"description": "Wells", "amount": "60000"}],
                                     retainage_rate="0.10", actor="pm")
        w.c.approve_and_execute("commitment.execute", cmt["id"])
        line = w.c.commitments.get(cmt["id"])["sov"][0]["id"]
        b = w.c.bills.certify(commitment_id=cmt["id"], period_id="P1", installed=[{"sov_line_id": line, "cumulative_installed": "60000"}], actor="pm")
        w.c.approve_and_execute("bill.approve", b["id"])
        w.c.commitments.close(cmt["id"], actor="pm")
        w.c.approve_and_execute("retainage.release", cmt["id"], actor_role="accountant", period_id="P1")
        emp = w.c.add_party(kind="employee", name="Field Engineer (synthetic)", destination="ACH-SIM-EMP-0001")
        w.c.verify_destination(emp["id"], destination="ACH-SIM-EMP-0001", verified_by="owner")
        r = w.c.plugin("reimbursement")
        claim = r.submit_claim(project_id=w.pid, employee_id=emp["id"], description="Dewatering pump hire", amount="7500.00", receipt_hash="rcpt-0001",
                               billable=False, actor="emp")
        w.c.approve_and_execute("reimbursement.approve", claim["id"], period_id="P1")
        pay = r.record_payment(claim["id"], "7500.00", actor="treasury")
        w.adopt(high="5000.00", cosign="50000.00", first=False)
        ret = w.request(cmt["id"], op="payment.release_retainage")
        self.assertEqual((w.facts(ret)["classification"], w.facts(ret)["amount"]), ("high_risk", "6000.00"))
        reimb = w.request(pay["id"], op="reimbursement.pay")
        self.assertEqual((w.facts(reimb)["classification"], w.facts(reimb)["amount"]), ("high_risk", "7500.00"))
        w.c.approve(reimb["id"], approver="owner")
        with self.assertRaises(StepUpRequired):
            w.c.execute(reimb["id"], actor="treasury", period_id="P1")
        w.step_up()
        self.assertEqual(w.c.execute(reimb["id"], actor="treasury", period_id="P1").result["status"], "in_flight")
        w.c.approve(ret["id"], approver="owner")
        w.step_up()
        self.assertEqual(w.c.execute(ret["id"], actor="treasury").result["amount"], "6000.00")
        self.assertEqual({k["operation"] for k in w.pp.clearances()}, {"reimbursement.pay", "payment.release_retainage"})

    def test_a_reimbursement_paid_in_parts_is_classified_on_the_whole_claim(self):
        """reimbursement.pay releases a part the requester chooses.  Classified on the part alone,
        a high-risk claim paid in parts below the threshold would need no independent control."""
        w = World()
        emp = w.c.add_party(kind="employee", name="Site Engineer (synthetic)", destination="ACH-SIM-EMP-0002")
        w.c.verify_destination(emp["id"], destination="ACH-SIM-EMP-0002", verified_by="owner")
        r = w.c.plugin("reimbursement")
        big = r.submit_claim(project_id=w.pid, employee_id=emp["id"], description="Dewatering pump hire, full season", amount="60000.00",
                             receipt_hash="rcpt-0002", billable=False, actor="emp")
        small = r.submit_claim(project_id=w.pid, employee_id=emp["id"], description="Site radios", amount="900.00", receipt_hash="rcpt-0003",
                               billable=False, actor="emp")
        for claim in (big, small):
            w.c.approve_and_execute("reimbursement.approve", claim["id"], period_id="P1")
        w.adopt(high="10000.00", cosign="50000.00", first=False)
        part = r.record_payment(big["id"], "9999.99", actor="treasury")
        ap = w.request(part["id"], op="reimbursement.pay", requested_by="owner")
        f = w.facts(ap)
        self.assertEqual((f["classification"], f["reasons"], f["cosign_required"], f["amount"], f["claim_amount"]),
                         ("high_risk", ["amount_at_or_over_high_risk_amount"], True, "9999.99", "60000.00"))
        with self.assertRaises(IndependenceRequired):  # one login cannot release a part of it alone
            w.c.approve(ap["id"], approver="owner")
        f = w.facts(w.request(r.record_payment(small["id"], "400.00", actor="treasury")["id"], op="reimbursement.pay"))
        self.assertEqual((f["classification"], f["amount"], f["claim_amount"]), ("standard", "400.00", "900.00"))


# --------------------------------------------------------------------------- #
# 4. independent approval and release, step-up                                 #
# --------------------------------------------------------------------------- #

class IndependentReleaseTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.w.adopt(high="10000.00", cosign="50000.00", first=False)
        self.c, self.pp = self.w.c, self.w.pp

    def test_a_solo_owner_cannot_release_a_high_risk_payment_alone(self):
        b = self.w.bill(20000)
        with self.assertRaises(IndependenceRequired):  # request, approve and release by one person
            self.c.approve_and_execute("payment.release", b["id"], actor_role="treasury", actor="owner")
        ap = self.c.approvals.list(status="pending")[-1]
        with self.assertRaises(IndependenceRequired):
            self.c.approve(ap["id"], approver="OWNER ", approver_role="owner")  # the same login, however spelled
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "pending")
        # an outside party approves, but the owner who requested it still cannot release it
        self.c.approve(ap["id"], approver="ext-accountant", approver_role="treasury")
        self.pp.record_step_up("owner", "security_key", sha256_hex("owner key"), "sign-in-service")
        with self.assertRaises(IndependenceRequired):
            self.c.execute(ap["id"], actor="owner")
        with self.assertRaises(IndependenceRequired):  # nor can the approver release what they approved
            self.c.execute(ap["id"], actor="ext-accountant")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")
        self.assertEqual(self.c.payments.list(), [])
        self.assertEqual(self.pp.step_ups("owner")[0]["approval_id"], None)  # a refused release uses no step-up

    def test_two_logins_of_one_owner_are_not_two_people(self):
        b = self.w.bill(20000)
        self.c.register_plugin("people", PeopleStub({"owner": "p-owner", "owner-phone": "p-owner", "treasury": "p-t", "ext-accountant": "p-x"}, externals={"ext-accountant"}))
        ap = self.w.request(b["id"], requested_by="owner")
        with self.assertRaises(IndependenceRequired):
            self.c.approve(ap["id"], approver="owner-phone", approver_role="owner")
        self.c.register_plugin("people", PeopleStub({"owner": "p-owner", "owner-phone": "p-owner"}, enforce=False))
        self.c.approve(ap["id"], approver="owner-phone", approver_role="owner")  # not enforcing: logins are compared as logins

    def test_service_identities_never_step_up_release_or_stand_as_independent(self):
        """A service identity (Ricky, a payment worker) is not a second person.  It may request a
        high-risk release, but it never receives a step-up or releases one, so the release
        always involves two people: the approver and a different releaser."""
        b = self.w.bill(20000)
        early = self.w.step_up("pay-worker")  # recorded before identity enforcement
        enforce_identity(self.w, STAFF + (("ricky", "service", False), ("pay-worker", "service", False)), treasury=("treasury", "pay-worker"))
        with self.assertRaisesRegex(PolicyRefused, "not an active person"):
            self.w.step_up("pay-worker")
        ap = self.w.granted(b["id"], requested_by="ricky")
        with self.assertRaisesRegex(IndependenceRequired, "service identity"):
            self.c.execute(ap["id"], actor="pay-worker")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")
        self.assertIsNone([s for s in self.pp.step_ups() if s["id"] == early["id"]][0]["approval_id"])
        policy = self.pp.policy()
        self.assertFalse(self.pp.is_independent("ricky", dict(policy, terms=dict(policy["terms"], independent_parties=["ricky"]))))
        self.w.step_up()
        self.assertEqual(self.c.execute(ap["id"], actor="treasury").result["amount"], "20000.00")
        k = self.pp.clearances()[-1]
        self.assertEqual((k["requested_by"], k["approver"], k["releaser"]), ("ricky", "owner", "treasury"))

    def test_independent_release_needs_a_fresh_step_up_by_the_releaser(self):
        b = self.w.bill(20000)
        ap = self.w.granted(b["id"])
        with self.assertRaises(StepUpRequired):
            self.c.execute(ap["id"], actor="treasury")
        self.w.step_up(login="treasury-2")  # someone else's step-up does not count
        with self.assertRaises(StepUpRequired):
            self.c.execute(ap["id"], actor="treasury")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")
        step = self.w.step_up()
        res = self.c.execute(ap["id"], actor="treasury")
        self.assertEqual(res.result["amount"], "20000.00")
        used = [s for s in self.pp.step_ups("treasury") if s["id"] == step["id"]][0]
        self.assertEqual(used["approval_id"], ap["id"])
        k = self.pp.clearances()[0]
        self.assertEqual((k["approval_id"], k["classification"], k["releaser"], k["approver"], k["requested_by"], k["step_up_id"]),
                         (ap["id"], "high_risk", "treasury", "owner", "ap-clerk", step["id"]))
        self.assertTrue(any(e["action"] == "payment_policy.release_cleared" for e in self.c.audit.entries(entity_type="approval", entity_id=ap["id"])))

    def test_a_step_up_that_is_too_old_is_refused(self):
        b = self.w.bill(20000)
        ap = self.w.granted(b["id"])
        self.w.step_up()
        self.w.move_clock(seconds=301)
        with self.assertRaisesRegex(StepUpRequired, "seconds old"):
            self.c.execute(ap["id"], actor="treasury")
        self.w.step_up()  # recorded at the moved clock: fresh
        self.c.execute(ap["id"], actor="treasury")

    def test_a_step_up_is_used_once_and_an_assertion_is_never_replayed(self):
        b1, b2 = self.w.bill(20000), self.w.bill(20000)
        ap1, ap2 = self.w.granted(b1["id"]), self.w.granted(b2["id"])
        h = sha256_hex("one assertion")
        self.pp.record_step_up("treasury", "totp", h, "sign-in-service")
        self.c.execute(ap1["id"], actor="treasury")
        with self.assertRaisesRegex(StepUpRequired, "already been used"):
            self.c.execute(ap2["id"], actor="treasury")
        with self.assertRaises(PolicyRefused):  # replaying the same assertion is not a fresh authentication
            self.pp.record_step_up("treasury", "totp", h, "sign-in-service")
        for bad in (("treasury", "sms", sha256_hex("x")), ("treasury", "totp", "abc"), ("", "totp", sha256_hex("y"))):
            with self.subTest(bad=bad), self.assertRaises(PaymentPolicyError):
                self.pp.record_step_up(*bad, "sign-in-service")
        self.w.step_up()
        self.c.execute(ap2["id"], actor="treasury")

    def test_a_release_that_fails_after_the_checks_leaves_the_step_up_unused(self):
        b = self.w.bill(20000)
        ap = self.w.granted(b["id"])
        step = self.w.step_up()
        self.c.payments.engage_kill_switch("suspected business e-mail compromise", "owner")
        with self.assertRaises(KillSwitchEngaged):
            self.c.execute(ap["id"], actor="treasury")
        self.assertIsNone([s for s in self.pp.step_ups() if s["id"] == step["id"]][0]["approval_id"])
        self.assertEqual(self.pp.clearances(), [])
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")

    def test_standard_releases_need_no_independence_but_are_cleared(self):
        b = self.w.bill(5000)
        res = self.c.approve_and_execute("payment.release", b["id"], actor_role="treasury", actor="owner")
        self.assertEqual(res.result["amount"], "5000.00")
        k = self.pp.clearances()[0]
        self.assertEqual((k["classification"], k["releaser"], k["step_up_id"]), ("standard", "owner", None))

    def test_the_release_check_refuses_to_run_outside_an_execution(self):
        b = self.w.bill(20000)
        ap = self.w.granted(b["id"])
        self.w.step_up()
        with self.assertRaises(PaymentPolicyError):  # e.g. through the console's generic module call
            self.pp.check_execute(ap, ap["manifest"], actor="treasury")
        self.assertEqual(self.pp.clearances(), [])
        self.assertIsNone(self.pp.step_ups()[0]["approval_id"])


# --------------------------------------------------------------------------- #
# 5. co-signature: the solo owner's external accountant                        #
# --------------------------------------------------------------------------- #

class CosignatureTests(unittest.TestCase):
    def test_an_external_accountant_co_signs_a_large_release(self):
        w = World()
        w.adopt(high="10000.00", cosign="50000.00", first=False, parties=("ext-accountant",))
        c, pp = w.c, w.pp
        b = w.bill(60000)
        ap = w.granted(b["id"])
        self.assertTrue(w.facts(ap)["cosign_required"])
        w.step_up()
        with self.assertRaises(CosignatureRequired):
            c.execute(ap["id"], actor="treasury")
        for cosigner, err in (("owner", IndependenceRequired), ("ap-clerk", IndependenceRequired), ("random-login", IndependenceRequired)):
            with self.subTest(cosigner=cosigner), self.assertRaises(err):
                pp.cosign(ap["id"], cosigner, cosigner)
        with self.assertRaises(PolicyRefused):  # the owner cannot record it on the accountant's behalf
            pp.cosign(ap["id"], "ext-accountant", "owner")
        sig = pp.cosign(ap["id"], "Ext-Accountant", "ext-accountant")
        self.assertEqual(sig["policy_version"], 1)
        with self.assertRaises(IndependenceRequired):  # the co-signer cannot also be the releaser
            c.execute(ap["id"], actor="ext-accountant")
        res = c.execute(ap["id"], actor="treasury")
        self.assertEqual(res.result["amount"], "60000.00")
        k = pp.clearances()[0]
        self.assertEqual(k["cosignature_id"], sig["id"])

    def test_a_co_signer_cannot_also_approve_and_a_standard_release_cannot_be_co_signed(self):
        w = World()
        w.adopt(high="10000.00", cosign="50000.00", first=False)
        ap = w.request(w.bill(60000)["id"])
        w.pp.cosign(ap["id"], "ext-accountant", "ext-accountant")
        with self.assertRaises(IndependenceRequired):
            w.c.approve(ap["id"], approver="ext-accountant", approver_role="treasury")
        small = w.request(w.bill(100)["id"])
        with self.assertRaises(PaymentPolicyError):
            w.pp.cosign(small["id"], "ext-accountant", "ext-accountant")

    def test_a_release_needing_a_co_signature_nobody_can_give_is_refused_at_request(self):
        w = World()
        w.adopt(high="10000.00", cosign="50000.00", first=False, parties=())
        with self.assertRaises(CosignatureRequired):
            w.request(w.bill(60000)["id"])

    def test_people_registry_externals_qualify_only_while_the_policy_names_no_party(self):
        persons = {"audit-firm": "p-af", "ext-accountant": "p-x", "ap-clerk": "p-c", "owner": "p-o", "treasury": "p-t"}
        w = World()
        w.adopt(high="10000.00", cosign="50000.00", first=False, parties=("ext-accountant",))
        ap = w.request(w.bill(60000)["id"])
        w.c.register_plugin("people", PeopleStub(persons, externals={"audit-firm"}, inactive={"ext-accountant"}))
        with self.assertRaises(IndependenceRequired):  # listed, but no longer active
            w.pp.cosign(ap["id"], "ext-accountant", "ext-accountant")
        with self.assertRaises(IndependenceRequired):  # external in the registry, but the policy names its parties
            w.pp.cosign(ap["id"], "audit-firm", "audit-firm")
        w = World()
        b = w.bill(60000)
        enforce_identity(w)  # registers ext-accountant as an external person
        w.adopt(high="10000.00", cosign="50000.00", first=False, parties=())
        ap = w.request(b["id"])
        sig = w.pp.cosign(ap["id"], "ext-accountant", "ext-accountant")  # an external person in the registry
        self.assertEqual(sig["cosigner"], "ext-accountant")
        w.c.approve(ap["id"], approver="owner")
        w.step_up()
        self.assertEqual(w.c.execute(ap["id"], actor="treasury").result["amount"], "60000.00")

    def test_while_the_policy_names_no_party_an_external_registered_after_it_is_not_one(self):
        """With no party named, the enforcing registry's external persons stand in -- but only
        those registered before the policy was adopted.  Otherwise the owner registers a second
        login as external alone (no approval) and it co-signs, and the owner could also name that
        login as the "first" party with nobody co-signing."""
        w = World()
        b, b2 = w.bill(60000), w.bill(60000)
        people = enforce_identity(w)
        w.adopt(high="10000.00", cosign="50000.00", first=False, parties=())
        people.register_person("owner-alt", "The owner's second login", actor="owner", external=True)
        self.assertTrue(people.is_external("owner-alt"))
        self.assertEqual((w.pp.is_independent("owner-alt"), w.pp.is_independent("ext-accountant")), (False, True))
        ap = w.granted(b["id"])
        with self.assertRaises(IndependenceRequired):
            w.pp.cosign(ap["id"], "owner-alt", "owner-alt")
        d = w.pp.draft_policy(high_risk_amount="900000", cosign_amount="900000", step_up_max_age_seconds=3600, new_destination_cooling_days=0,
                              first_payment_to_destination_is_high_risk=False, independent_parties=[], reason="loosen", actor="owner")
        upd = w.c.request_approval(OP_UPDATE, d["id"], actor_role="owner")
        self.assertEqual(upd["manifest"]["bindings"]["cosigners_allowed"], ["ext-accountant"])
        w.c.approve(upd["id"])
        with self.assertRaises(IndependenceRequired):
            w.pp.cosign(upd["id"], "owner-alt", "owner-alt")
        with self.assertRaises(CosignatureRequired):
            w.c.execute(upd["id"])
        w.pp.cosign(ap["id"], "ext-accountant", "ext-accountant")  # the registry's outside party still co-signs
        w.step_up()
        self.assertEqual(w.c.execute(ap["id"], actor="treasury").result["amount"], "60000.00")
        # adopting another version that names nobody (it only tightens: no co-signature) does not let it in
        w.adopt(high="9000.00", cosign="50000.00", first=False, parties=())
        self.assertEqual((w.pp.policy()["version"], w.pp.is_independent("owner-alt")), (2, False))
        ap2 = w.granted(b2["id"])
        with self.assertRaises(IndependenceRequired):
            w.pp.cosign(ap2["id"], "owner-alt", "owner-alt")
        # naming a party other than the registry's outside parties adds one: a weakening
        d = w.pp.draft_policy(high_risk_amount="9000", cosign_amount="50000", step_up_max_age_seconds=300, new_destination_cooling_days=10,
                              first_payment_to_destination_is_high_risk=False, independent_parties=["owner-alt"], reason="name a party", actor="owner")
        upd = w.c.request_approval(OP_UPDATE, d["id"], actor_role="owner")
        self.assertEqual((upd["manifest"]["bindings"]["weakens"], upd["manifest"]["bindings"]["cosigners_allowed"]),
                         (["independent_party_added:owner-alt"], ["ext-accountant"]))
        w.c.approve(upd["id"])
        with self.assertRaises(CosignatureRequired):
            w.c.execute(upd["id"])
        self.assertEqual(w.pp.policy()["version"], 2)
        # naming the registry's outside party pins it: not a weakening
        d = w.pp.draft_policy(high_risk_amount="9000", cosign_amount="50000", step_up_max_age_seconds=300, new_destination_cooling_days=10,
                              first_payment_to_destination_is_high_risk=False, independent_parties=["ext-accountant"], reason="name it", actor="owner")
        self.assertEqual(w.c.request_approval(OP_UPDATE, d["id"], actor_role="owner")["manifest"]["bindings"]["weakens"], [])
        # deactivating the outside party (no approval) leaves nobody to co-sign; it does not free
        # the owner to name a "first" party alone (as with a named party that is deactivated)
        people.deactivate_person("ext-accountant", reason="engagement ended", actor="owner")
        self.assertFalse(w.pp.is_independent("ext-accountant"))
        d = w.pp.draft_policy(high_risk_amount="9000", cosign_amount="50000", step_up_max_age_seconds=300, new_destination_cooling_days=10,
                              first_payment_to_destination_is_high_risk=False, independent_parties=["owner-alt"], reason="name a party", actor="owner")
        upd = w.c.request_approval(OP_UPDATE, d["id"], actor_role="owner")
        self.assertEqual((upd["manifest"]["bindings"]["weakens"], upd["manifest"]["bindings"]["cosigners_allowed"]),
                         (["independent_party_added:owner-alt"], ["ext-accountant"]))
        w.c.approve(upd["id"])
        with self.assertRaises(CosignatureRequired):
            w.c.execute(upd["id"])
        self.assertEqual(w.pp.policy()["terms"]["independent_parties"], [])

    def test_while_the_policy_names_no_party_and_the_registry_supplies_none_a_co_signed_release_is_refused_at_request(self):
        w = World()
        b = w.bill(60000)
        people = enforce_identity(w, persons=STAFF[:2])  # no external person yet
        w.adopt(high="10000.00", cosign="50000.00", first=False, parties=())
        people.register_person("ext-accountant", "Synthetic ext-accountant", actor="owner", external=True)
        with self.assertRaises(CosignatureRequired):
            w.request(b["id"])
        w.adopt(high="10000.00", cosign="50000.00", first=False, parties=("ext-accountant",))  # naming the first party sets the control up
        ap = w.granted(b["id"])
        w.pp.cosign(ap["id"], "ext-accountant", "ext-accountant")
        w.step_up()
        self.assertEqual(w.c.execute(ap["id"], actor="treasury").result["amount"], "60000.00")

    def test_an_outside_party_the_owner_registers_alone_cannot_stand_in_for_the_named_one(self):
        """The policy names its independent parties.  A login the owner registers as external
        (no approval, no co-signature) is not one of them, or the owner could add a co-signer
        alone where the governed route treats the same change as a weakening."""
        w = World()
        w.adopt(high="10000.00", cosign="50000.00", first=False, parties=("ext-accountant",))
        b = w.bill(60000)
        people = enforce_identity(w)
        people.register_person("owner-alt", "The owner's second login", actor="owner", external=True)
        self.assertTrue(people.is_external("owner-alt"))
        self.assertEqual((w.pp.is_independent("owner-alt"), w.pp.is_independent("ext-accountant")), (False, True))
        ap = w.granted(b["id"])
        with self.assertRaises(IndependenceRequired):
            w.pp.cosign(ap["id"], "owner-alt", "owner-alt")
        d = w.pp.draft_policy(high_risk_amount="900000", cosign_amount="900000", step_up_max_age_seconds=3600, new_destination_cooling_days=0,
                              first_payment_to_destination_is_high_risk=False, independent_parties=["ext-accountant"], reason="loosen", actor="owner")
        upd = w.c.request_approval(OP_UPDATE, d["id"], actor_role="owner")
        self.assertEqual(upd["manifest"]["bindings"]["cosigners_allowed"], ["ext-accountant"])
        w.c.approve(upd["id"])
        with self.assertRaises(IndependenceRequired):
            w.pp.cosign(upd["id"], "owner-alt", "owner-alt")
        with self.assertRaises(CosignatureRequired):
            w.c.execute(upd["id"])
        self.assertEqual(w.pp.policy()["version"], 1)
        # the co-signers the approval binds hold even if the independence check accepted another login
        w.pp.is_independent = lambda login, policy=None: True
        try:
            with self.assertRaisesRegex(IndependenceRequired, "allows"):
                w.pp.cosign(upd["id"], "owner-alt", "owner-alt")
        finally:
            del w.pp.is_independent
        w.pp.cosign(ap["id"], "ext-accountant", "ext-accountant")  # the named outside party still co-signs
        w.step_up()
        self.assertEqual(w.c.execute(ap["id"], actor="treasury").result["amount"], "60000.00")


# --------------------------------------------------------------------------- #
# 6. cooling-off after a payee destination change                              #
# --------------------------------------------------------------------------- #

class CoolingOffTests(unittest.TestCase):
    def test_a_release_to_a_changed_destination_is_held_until_the_window_passes(self):
        w = World()
        w.adopt(high="10000.00", cosign="50000.00", first=False, cooling=10, cosign_all=True)
        ch = w.change_destination()
        b = w.bill(2000)
        ap = w.granted(b["id"])
        f = w.facts(ap)
        self.assertEqual((f["classification"], f["reasons"], f["cosign_reasons"]),
                         ("high_risk", ["new_destination_from_change"], ["policy_cosigns_every_high_risk_release"]))
        self.assertEqual((f["destination"]["change"]["change_id"], f["destination"]["change"]["executed_at"]), (ch["id"], ch["executed_at"]))
        # the bound facts are recorded state, not clock readings: days later they re-derive identically
        w.move_clock(days=5)
        self.assertEqual(w.c._manifest("payment.release", b["id"], "treasury")["governance"][PLUGIN_NAME], f)
        w.pp.now = utcnow
        w.pp.cosign(ap["id"], "ext-accountant", "ext-accountant")
        w.step_up()
        with self.assertRaisesRegex(CoolingOffHold, "co-signature does not lift the hold"):
            w.c.execute(ap["id"], actor="treasury")  # co-signed and stepped up, still held
        self.assertEqual(w.c.approvals.get(ap["id"])["status"], "granted")
        state = w.c.project_state(w.pid)[PLUGIN_NAME]
        self.assertEqual([h["approval_id"] for h in state["cooling_off_holds"]], [ap["id"]])
        held = [chk for chk in w.pp.close_checks("P1") if "cooling-off" in chk["check"]][0]
        self.assertIn("1 release approval(s) held", held["detail"])
        w.move_clock(days=9, hours=23)
        with self.assertRaises(CoolingOffHold):
            w.c.execute(ap["id"], actor="treasury")
        w.move_clock(days=10, minutes=1)
        w.step_up()  # the earlier step-up is days old at the moved clock
        res = w.c.execute(ap["id"], actor="treasury")
        self.assertEqual(res.result["amount"], "2000.00")
        intent = w.c.payments.get(res.result["intent"])
        self.assertEqual(intent["destination_version"], ch["new_destination_version"])

    def test_a_changed_destination_is_high_risk_until_paid_and_the_hold_covers_standard_releases_too(self):
        w = World()
        w.adopt(high="10000.00", cosign="50000.00", first=False, cooling=0)
        w.change_destination()
        first = w.granted(w.bill(2000)["id"])
        self.assertEqual(w.facts(first)["reasons"], ["new_destination_from_change"])
        w.step_up()
        w.c.execute(first["id"], actor="treasury")  # no window configured: released (high risk, independent, stepped up)
        w.settle_last()
        f = w.facts(w.request(w.bill(2000)["id"]))
        self.assertEqual((f["classification"], f["destination"]["has_settled_payment"]), ("standard", True))
        w.adopt(high="10000.00", cosign="50000.00", first=False, cooling=10)  # tightened: the change is now inside a window
        b = w.bill(2000)
        ap = w.c.request_approval("payment.release", b["id"], actor_role="treasury", requested_by="owner")
        self.assertEqual(w.facts(ap)["classification"], "standard")
        w.c.approve(ap["id"], approver="owner")
        with self.assertRaises(CoolingOffHold):
            w.c.execute(ap["id"], actor="owner")


# --------------------------------------------------------------------------- #
# 7. a policy change invalidates in-flight releases                            #
# --------------------------------------------------------------------------- #

class PolicyChangeTests(unittest.TestCase):
    def test_a_policy_update_invalidates_an_in_flight_release_approval(self):
        w = World()
        w.adopt(high="50000.00", cosign="90000.00", first=False)
        ap = w.granted(w.bill(20000)["id"])
        self.assertEqual(w.facts(ap)["classification"], "standard")
        w.adopt(high="10000.00", cosign="90000.00", first=False)  # tightened: this release is now high risk
        self.assertEqual(w.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(ApprovalNotGranted):
            w.c.execute(ap["id"], actor="treasury")
        fresh = w.request(w.bill(1)["id"])
        self.assertEqual(w.facts(fresh)["policy_version"], 2)

    def test_an_approval_granted_before_any_policy_cannot_execute_after_one_is_adopted(self):
        w = World()
        b = w.bill(20000)
        ap = w.c.request_approval("payment.release", b["id"], actor_role="treasury", requested_by="owner")
        w.c.approve(ap["id"], approver="owner")
        w.adopt()
        self.assertEqual(w.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(ApprovalNotGranted):
            w.c.execute(ap["id"], actor="owner")
        self.assertEqual(w.c.payments.list(), [])

    def test_the_service_invalidates_a_release_whose_bound_policy_no_longer_matches(self):
        w = World()
        w.adopt(high="10000.00", first=False)
        ap = w.granted(w.bill(20000)["id"])
        # a policy move the update path did not see: the service re-derives the bound facts at execution
        stale = dict(w.pp.policy(), hash="f" * 64)
        orig = w.pp._policy
        w.pp._policy = lambda: stale
        try:
            with self.assertRaises(StaleApprovalError):
                w.c.execute(ap["id"], actor="treasury")
        finally:
            w.pp._policy = orig
        self.assertEqual(w.c.approvals.get(ap["id"])["status"], "invalidated")

    def test_a_grant_under_a_moved_policy_invalidates_the_pending_approval(self):
        w = World()
        w.adopt(high="10000.00", first=False)
        ap = w.request(w.bill(20000)["id"])
        stale = dict(w.pp.policy(), version=7)
        orig = w.pp._policy
        w.pp._policy = lambda: stale
        try:
            with self.assertRaises(StaleApprovalError):
                w.c.approve(ap["id"], approver="owner")
        finally:
            w.pp._policy = orig
        self.assertEqual(w.c.approvals.get(ap["id"])["status"], "invalidated")


# --------------------------------------------------------------------------- #
# 8. raw-SQL tampering                                                         #
# --------------------------------------------------------------------------- #

class TamperTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.v1 = self.w.adopt(high="10000.00", first=False)
        self.c, self.pp = self.w.c, self.w.pp

    def test_policy_versions_and_drafts_cannot_be_rewritten_deleted_or_forged(self):
        db = self.c.db
        for sql in ("UPDATE payment_policy_versions SET terms_json = replace(terms_json, '10000.00', '99999.00')",
                    "UPDATE payment_policy_versions SET adopted_by = 'someone'",
                    "DELETE FROM payment_policy_versions",
                    "UPDATE payment_policy_drafts SET terms_json = '{}'",
                    "UPDATE payment_policy_drafts SET status = 'pending'",
                    "DELETE FROM payment_policy_drafts"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                db.execute(sql)
        row = db.one("SELECT * FROM payment_policy_versions WHERE version = 1")
        cols = ", ".join(row)
        marks = ", ".join("?" * len(row))
        with self.assertRaises(sqlite3.DatabaseError):  # REPLACE would delete the stored version without a DELETE trigger
            db.execute(f"INSERT OR REPLACE INTO payment_policy_versions ({cols}) VALUES ({marks})", tuple(row.values()))
        forged = dict(row, version=2, prev_hash=row["hash"], hash="e" * 64, draft_id=row["draft_id"], approval_id=row["approval_id"])
        with self.assertRaises(sqlite3.DatabaseError):  # a version nobody approved
            db.execute(f"INSERT INTO payment_policy_versions ({cols}) VALUES ({marks})", tuple(forged.values()))
        d = self.pp.draft_policy(high_risk_amount="99999", cosign_amount="99999", step_up_max_age_seconds=300, new_destination_cooling_days=0,
                                 first_payment_to_destination_is_high_risk=False, independent_parties=[], reason="forge", actor="owner")
        forged = dict(row, version=2, prev_hash=row["hash"], hash="e" * 64, draft_id=d["id"], approval_id=row["approval_id"],
                      terms_json=db.scalar("SELECT terms_json FROM payment_policy_drafts WHERE id=?", (d["id"],)), terms_hash=d["content_hash"])
        with self.assertRaises(sqlite3.DatabaseError):  # a real pending draft, but no consumed approval of it
            db.execute(f"INSERT INTO payment_policy_versions ({cols}) VALUES ({marks})", tuple(forged.values()))
        ap = self.c.request_approval(OP_UPDATE, d["id"], actor_role="owner")
        with self.assertRaises(sqlite3.DatabaseError):  # its approval cannot be promoted to consumed by hand
            db.execute("UPDATE approvals SET status='consumed', approver='owner', granted_at='x', consumed_at='x', consumed_by='owner' WHERE id=?", (ap["id"],))
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM approvals WHERE id=?", (ap["id"],))
        self.assertTrue(self.pp.verify_chain()["ok"])
        self.assertEqual(self.pp.policy()["hash"], self.v1["hash"])

    def test_step_ups_co_signatures_and_clearances_cannot_be_reused_or_forged(self):
        db = self.c.db
        ap = self.w.granted(self.w.bill(20000)["id"])
        step = self.w.step_up()
        self.c.execute(ap["id"], actor="treasury")
        for sql in ("UPDATE payment_policy_step_ups SET approval_id = NULL, used_at = NULL",
                    "UPDATE payment_policy_step_ups SET recorded_at = '2999-01-01T00:00:00Z'",
                    "DELETE FROM payment_policy_step_ups",
                    "UPDATE payment_policy_clearances SET releaser = 'owner'",
                    "DELETE FROM payment_policy_clearances"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                db.execute(sql)
        with self.assertRaises(sqlite3.DatabaseError):  # a step-up cannot be born used
            db.execute("INSERT INTO payment_policy_step_ups (id, login, login_key, method, assertion_hash, recorded_by, recorded_at, approval_id, used_at) "
                       "VALUES ('psu_forged','treasury','treasury','totp',?,'x','2026-10-12T00:00:00Z',?, 'x')", (sha256_hex("forged"), ap["id"]))
        ap2 = self.w.granted(self.w.bill(20000)["id"])
        with self.assertRaises(sqlite3.DatabaseError):  # an already used step-up cannot be moved to another release
            db.execute("UPDATE payment_policy_step_ups SET approval_id=? WHERE id=?", (ap2["id"], step["id"]))
        with self.assertRaises(sqlite3.DatabaseError):  # a clearance nobody's release check wrote
            db.execute("INSERT INTO payment_policy_clearances (approval_id, operation, classification, facts_json, facts_hash, policy_version, requested_by, "
                       "approver, releaser, cleared_at) VALUES (?, 'payment.release', 'standard', '{}', ?, 1, 'ap-clerk', 'owner', 'owner', 'x')",
                       (ap2["id"], "0" * 64))
        big = self.w.request(self.w.bill(60000)["id"])
        with self.assertRaises(sqlite3.DatabaseError):  # a co-signature without the cosign path
            db.execute("INSERT INTO payment_policy_cosignatures (id, approval_id, operation, approval_manifest_hash, policy_version, cosigner, recorded_by, cosigned_at) "
                       "VALUES ('pcs_forged', ?, 'payment.release', ?, 1, 'ext-accountant', 'ext-accountant', 'x')", (big["id"], big["manifest_hash"]))
        sig = self.pp.cosign(big["id"], "ext-accountant", "ext-accountant")
        for sql in ("UPDATE payment_policy_cosignatures SET cosigner = 'owner'", "DELETE FROM payment_policy_cosignatures"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                db.execute(sql)
        self.assertEqual(self.pp.cosignatures()[0]["id"], sig["id"])

    def test_a_tampered_policy_is_detected_and_releases_fail_closed(self):
        db = self.c.db
        ap = self.w.granted(self.w.bill(20000)["id"])
        self.w.step_up()
        db.execute("DROP TRIGGER payment_policy_versions_no_update")
        db.execute("UPDATE payment_policy_versions SET terms_json = replace(terms_json, '10000.00', '99999.00')")
        chain = self.pp.verify_chain()
        self.assertFalse(chain["ok"])
        self.assertTrue(any("hash" in p for p in chain["problems"]))
        with self.assertRaises(PolicyIntegrityError):
            self.c.execute(ap["id"], actor="treasury")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")  # refused, not consumed
        with self.assertRaises(PolicyIntegrityError):
            self.w.request(self.w.bill(1)["id"])
        intact = [chk for chk in self.pp.close_checks("P1") if chk["check"] == "payment_policy records intact"][0]
        self.assertFalse(intact["ok"])
        brief = self.c.ricky.brief(self.w.pid)
        self.assertTrue(any(it["kind"] == "close_check" and "payment_policy" in it["text"] for it in brief["items"]))
        self.assertFalse(self.c.project_state(self.w.pid)[PLUGIN_NAME]["integrity"]["ok"])

    def test_deleting_every_version_with_the_triggers_dropped_is_detected(self):
        db = self.c.db
        db.execute("DROP TRIGGER payment_policy_versions_no_delete")
        db.execute("DELETE FROM payment_policy_versions")
        self.assertIn("1 policy adoption(s) but 0 version(s)", " ".join(self.pp.verify_chain()["problems"]))
        with self.assertRaises(PolicyIntegrityError):  # not "no policy": the audit log says one was adopted
            self.w.request(self.w.bill(20000)["id"])
        self.assertFalse(self.pp.close_checks("P1")[0]["ok"])

    def test_a_raw_sql_grant_by_someone_else_is_refused_at_release(self):
        ap = self.w.request(self.w.bill(20000)["id"], requested_by="owner")
        with self.assertRaises(IndependenceRequired):
            self.c.approve(ap["id"], approver="owner")
        self.c.db.execute("UPDATE approvals SET status='granted', approver='treasury-lead', granted_at='2026-10-12T00:00:00Z' WHERE id=?", (ap["id"],))
        self.w.step_up()
        with self.assertRaisesRegex(PolicyIntegrityError, "audit log"):
            self.c.execute(ap["id"], actor="treasury")
        self.assertEqual(self.c.payments.list(), [])

    def test_a_release_that_bypassed_the_governor_fails_the_close_check(self):
        ap = self.w.granted(self.w.bill(20000)["id"])
        current = self.c._manifest("payment.release", ap["subject_id"], "treasury")
        self.c.approvals.consume(ap["id"], current_manifest=current, consumer="treasury")
        intent = self.c.payments.create_intent(manifest=current, approval_id=ap["id"], bill_id=ap["subject_id"], note="bill payment", actor="treasury")
        intact = self.pp.close_checks("P1")[0]
        self.assertFalse(intact["ok"])
        self.assertIn(intent["id"], intact["detail"])
        self.assertEqual([u["intent_id"] for u in self.pp.state(self.w.pid)["integrity"]["uncleared_releases"]], [intent["id"]])

    def test_a_clearance_written_past_its_trigger_does_not_hide_a_release_that_bypassed_the_governor(self):
        ap = self.w.granted(self.w.bill(20000)["id"])
        current = self.c._manifest("payment.release", ap["subject_id"], "treasury")
        self.c.approvals.consume(ap["id"], current_manifest=current, consumer="treasury")
        intent = self.c.payments.create_intent(manifest=current, approval_id=ap["id"], bill_id=ap["subject_id"], note="bill payment", actor="treasury")
        self.c.db.execute("DROP TRIGGER payment_policy_clearances_recorded")
        facts = self.w.facts(ap)  # even the facts bound into the approval, correctly hashed
        self.c.db.execute("INSERT INTO payment_policy_clearances (approval_id, operation, classification, facts_json, facts_hash, policy_version, requested_by, "
                          "approver, releaser, cleared_at) VALUES (?, 'payment.release', 'high_risk', ?, ?, 1, 'ap-clerk', 'owner', 'treasury', '2026-10-12T00:00:00Z')",
                          (ap["id"], canonical_json(facts), hash_json(facts)))
        intact = self.pp.close_checks("P1")[0]
        self.assertFalse(intact["ok"])
        self.assertIn(intent["id"], intact["detail"])
        self.assertEqual([u["intent_id"] for u in self.pp.state(self.w.pid)["integrity"]["uncleared_releases"]], [intent["id"]])
        self.assertEqual([u["intent_id"] for u in self.pp.audit_export()["uncleared_releases"]], [intent["id"]])

    def test_a_co_signature_written_past_its_trigger_is_refused_and_reported(self):
        db = self.c.db
        ap = self.w.granted(self.w.bill(60000)["id"])
        self.w.step_up()
        d = self.pp.draft_policy(high_risk_amount="900000", cosign_amount="900000", step_up_max_age_seconds=3600, new_destination_cooling_days=0,
                                 first_payment_to_destination_is_high_risk=False, independent_parties=["ext-accountant"], reason="loosen", actor="owner")
        upd = self.c.request_approval(OP_UPDATE, d["id"], actor_role="owner")
        self.c.approve(upd["id"])
        db.execute("DROP TRIGGER payment_policy_cosignatures_recorded")
        for sig_id, target in (("pcs_forged_release", ap), ("pcs_forged_update", upd)):
            db.execute("INSERT INTO payment_policy_cosignatures (id, approval_id, operation, approval_manifest_hash, policy_version, cosigner, recorded_by, cosigned_at) "
                       "VALUES (?, ?, ?, ?, 1, 'ext-accountant', 'ext-accountant', '2026-10-12T00:00:00Z')", (sig_id, target["id"], target["operation"], target["manifest_hash"]))
        with self.assertRaisesRegex(PolicyIntegrityError, "audited"):
            self.c.execute(ap["id"], actor="treasury")
        with self.assertRaisesRegex(PolicyIntegrityError, "audited"):  # nor does it loosen the policy
            self.c.execute(upd["id"])
        self.assertEqual((self.c.approvals.get(ap["id"])["status"], self.c.payments.list(), self.pp.policy()["version"]), ("granted", [], 1))
        intact = self.pp.close_checks("P1")[0]
        self.assertFalse(intact["ok"])
        self.assertTrue("pcs_forged_release" in intact["detail"] and "pcs_forged_update" in intact["detail"])
        self.assertFalse(self.pp.state(self.w.pid)["integrity"]["ok"])

    def test_a_step_up_written_by_raw_sql_is_not_a_step_up(self):
        """The step-up insert trigger checks only that it is born unused: the audited record_step_up is what counts."""
        ap = self.w.granted(self.w.bill(20000)["id"])
        self.c.db.execute("INSERT INTO payment_policy_step_ups (id, login, login_key, method, assertion_hash, recorded_by, recorded_at) "
                          "VALUES ('psu_forged', 'treasury', 'treasury', 'webauthn', ?, 'sign-in-service', ?)", (sha256_hex("forged"), pp_mod._iso(self.pp._now())))
        with self.assertRaises(StepUpRequired):
            self.c.execute(ap["id"], actor="treasury")
        self.assertEqual(self.c.payments.list(), [])
        self.w.step_up()
        self.assertEqual(self.c.execute(ap["id"], actor="treasury").result["amount"], "20000.00")
        self.assertNotEqual(self.pp.clearances()[0]["step_up_id"], "psu_forged")


# --------------------------------------------------------------------------- #
# 9. reporting                                                                 #
# --------------------------------------------------------------------------- #

class ReportingTests(unittest.TestCase):
    def test_state_and_close_checks_list_releases_awaiting_a_control(self):
        w = World()
        w.adopt(high="10000.00", cosign="50000.00", first=False)
        pending = w.request(w.bill(20000)["id"])
        cosign = w.granted(w.bill(60000)["id"])
        standard = w.granted(w.bill(100)["id"])
        state = w.c.project_state(w.pid)[PLUGIN_NAME]
        self.assertTrue(state["configured"] and state["integrity"]["ok"])
        self.assertEqual(state["policy"]["version"], 1)
        waiting = {a["approval_id"]: a["waiting_for"] for a in state["awaiting_controls"]}
        self.assertEqual(waiting[pending["id"]], ["independent approval"])
        self.assertEqual(waiting[cosign["id"]], ["independent co-signature", "fresh step-up and independent release"])
        self.assertNotIn(standard["id"], waiting)
        checks = {chk["check"]: chk for chk in w.pp.close_checks("P1")}
        self.assertTrue(all(chk["ok"] for chk in checks.values()))
        self.assertIn("2 high-risk release approval(s) open, 1 awaiting an independent co-signature",
                      checks["payment_policy high-risk releases awaiting a control (informational)"]["detail"])
        self.assertTrue(all("name" in chk and chk["name"] == chk["check"] for chk in checks.values()))
        listed = {ch["check"]: ch for ch in w.c.plugin("close").checklist("P1")}
        self.assertEqual((listed["payment_policy records intact"]["source"], listed["payment_policy records intact"]["ok"]), (PLUGIN_NAME, True))
        export = w.c.audit_export()["modules"][PLUGIN_NAME]
        self.assertTrue(export["integrity"]["ok"])
        self.assertEqual(len(export["versions"]), 1)


if __name__ == "__main__":
    unittest.main()
