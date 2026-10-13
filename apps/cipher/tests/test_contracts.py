"""Contract approval, signature and insurance / bond evidence (the ``contract`` governor plugin).

Plan section 6 (distinct authority states), section 10 steps 1 and 4 and section 7 (a
subcontract administrator checks obligations and insurance).  Every party, document, policy
number and amount here is synthetic."""
import datetime as _dt
import sqlite3
import unittest

from apps.cipher.core.approvals import ApprovalConsumed, ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.ids import hash_json, utcnow
from apps.cipher.domain.contracts import (
    COVERAGE_KINDS, OP_APPROVE, OP_REQUIRE, OP_SIGN, PLUGIN_NAME, SCHEMA_NAME, WORKSPACE_SUBJECT_ID, AgreementIneligible, ContractError,
    CoverageError,
)
from apps.cipher.service import Cipher, RoleNotAuthorized, run_golden_fixture

ENTITY = "S&A Solutions LLC (synthetic)"


def day(offset: int = 0) -> str:
    return (utcnow().date() + _dt.timedelta(days=offset)).isoformat()


class World:
    """A verified cofferdam and sheet-pile subcontractor, a river-crossing project and open
    period P1.  Drafts default to the plan's 60,000 + 40,000 schedule of values."""

    def __init__(self):
        c = self.c = Cipher()
        self.k = c.plugin(PLUGIN_NAME)
        sup = c.add_party(kind="supplier", name="Synthetic sheet pile and cofferdam subcontractor", destination="ACH-SIM-CT-0001")
        self.supplier = c.verify_destination(sup["id"], destination="ACH-SIM-CT-0001", verified_by="owner")
        other = c.add_party(kind="supplier", name="Synthetic dewatering subcontractor", destination="ACH-SIM-CT-0002")
        self.other_supplier = c.verify_destination(other["id"], destination="ACH-SIM-CT-0002", verified_by="owner")
        self.customer = c.add_party(kind="customer", name="Synthetic owner agency")
        self.project = c.create_project(name="Synthetic river crossing cofferdam and dewatering", entity=ENTITY, budget="250000",
                                        customer_id=self.customer["id"])
        self.pid = self.project["id"]
        self.other_project = c.create_project(name="Synthetic lift station", entity=ENTITY, budget="50000", customer_id=self.customer["id"])
        c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        self._n = 0

    # ---- records ---------------------------------------------------------------------------- #

    def draft(self, *amounts, supplier_id=None, title="Synthetic sheet pile cofferdam subcontract"):
        amounts = amounts or ("60000", "40000")
        cmt = self.c.commitments.create(
            project_id=self.pid, supplier_id=supplier_id or self.supplier["id"], title=title,
            sov_lines=[{"description": f"Scope {i}", "amount": a, "cost_code": f"XX {i}0 00"} for i, a in enumerate(amounts, start=1)],
            retainage_rate="0.10", actor="pm-pat",
        )
        return cmt["id"]

    def doc(self, kind, label=None, *, project_id=None):
        self._n += 1
        label = label or f"{kind} {self._n}"
        d = self.c.evidence.register_document(project_id=project_id or self.pid, kind=kind, title=f"Synthetic {label}", actor="contracts-admin")
        rev = self.c.evidence.add_revision(document_id=d["id"], content=f"synthetic {kind} {self._n}: {label}".encode(), actor="contracts-admin")
        return d, rev

    def revise(self, d, label="revised"):
        self._n += 1
        return self.c.evidence.add_revision(document_id=d["id"], content=f"synthetic revision {self._n}: {label}".encode(), actor="contracts-admin")

    def register(self, cid):
        d, rev = self.doc("agreement")
        a = self.k.register_agreement(cid, rev["content_hash"], "contracts-admin")
        return a, d

    def request_agreement_approval(self, aid, *, role="pm", by="pm-pat"):
        ap = self.c.request_approval(OP_APPROVE, aid, actor_role=role, requested_by="contracts-admin")
        self.c.approve(ap["id"], approver=by, approver_role=role)
        return ap

    def approve_agreement(self, aid, *, role="pm", by="pm-pat"):
        ap = self.request_agreement_approval(aid, role=role, by=by)
        return self.c.execute(ap["id"], actor=by)

    def prepare(self, aid, *, signer="signer-sam", signing_date=None):
        d, rev = self.doc("signed_agreement")
        sig = self.k.prepare_signature(aid, rev["content_hash"], signer, signing_date or day(), "contracts-admin")
        return sig, d

    def request_signature(self, aid, *, signer="signer-sam", role="signer"):
        ap = self.c.request_approval(OP_SIGN, aid, actor_role=role, requested_by="contracts-admin")
        self.c.approve(ap["id"], approver=signer, approver_role=role)
        return ap

    def sign(self, aid, *, signer="signer-sam"):
        self.prepare(aid, signer=signer)
        ap = self.request_signature(aid, signer=signer)
        return self.c.execute(ap["id"], actor=signer)

    def execute_commitment(self, cid):
        ap = self.c.request_approval("commitment.execute", cid, actor_role="pm", requested_by="pm-pat")
        self.c.approve(ap["id"], approver="owner")
        return self.c.execute(ap["id"], actor="pm-pat")

    def signed_commitment(self, *amounts, requirements=None, supplier_id=None):
        cid = self.draft(*amounts, supplier_id=supplier_id)
        if requirements:
            self.k.set_requirements(cid, requirements, "contracts-admin")
        a, _ = self.register(cid)
        self.approve_agreement(a["id"])
        self.sign(a["id"])
        self.execute_commitment(cid)
        return cid

    def certificate(self, kind="general_liability", limit="2000000", effective=-30, expiry=335, *, party_id=None, document=None):
        if document is None:
            document, rev = self.doc("insurance_certificate")
        else:
            rev = self.c.evidence.current_revision(document["id"])
        return self.k.record_certificate(party_id or self.supplier["id"], kind, "Synthetic Mutual Insurance Co", f"POL-SIM-{self._n:04d}", limit,
                                         day(effective), day(expiry), rev["content_hash"], "contracts-admin")

    def line(self, cid, n=1):
        return self.c.commitments.get(cid)["sov"][n - 1]["id"]

    def certify(self, cid, cumulative="30000"):
        return self.c.bills.certify(commitment_id=cid, period_id="P1", installed=[{"sov_line_id": self.line(cid), "cumulative_installed": cumulative}],
                                    actor="pm-pat")

    def request_post(self, bill_id):
        ap = self.c.request_approval("bill.approve", bill_id, actor_role="accountant", requested_by="pm-pat")
        self.c.approve(ap["id"], approver="controller", approver_role="controller")
        return ap

    def post(self, bill_id):
        return self.c.execute(self.request_post(bill_id)["id"], actor="accountant")

    def request_release(self, bill_id):
        ap = self.c.request_approval("payment.release", bill_id, actor_role="treasury", requested_by="ap-clerk")
        self.c.approve(ap["id"], approver="owner")
        return ap

    def clock(self, offset_days):
        self.k.now = lambda: utcnow() + _dt.timedelta(days=offset_days)

    def checks(self):
        return {chk["check"]: chk for chk in self.k.close_checks("P1")}


GL = [{"kind": "general_liability", "min_limit": "1000000"}]
SIGN_CHECK = "contract signed agreements on billed commitments"
COVERAGE_CHECK = "contract insurance certificates expiring within 30 days"
INTEGRITY_CHECK = "contract records intact"


# --------------------------------------------------------------------------- #
# Plan section 10 step 1                                                       #
# --------------------------------------------------------------------------- #

class PlanStepOneTests(unittest.TestCase):
    def test_pm_approves_the_exact_agreement_the_signer_signs_then_the_commitment_executes(self):
        w = World()
        c, k = w.c, w.k
        cid = w.draft("60000", "40000")
        a, _ = w.register(cid)
        self.assertEqual((a["status"], a["commitment_version"], a["commitment_amount"]), ("registered", 1, "100000.00"))

        res = w.approve_agreement(a["id"], role="pm", by="pm-pat")
        self.assertEqual(res.result["status"], "approved")
        sig, _ = w.prepare(a["id"], signer="signer-sam")
        sp = w.request_signature(a["id"], signer="signer-sam")
        self.assertEqual({key: sp["manifest"]["bindings"][key] for key in ("signer", "signing_date", "signature_id", "signed_copy_hash")},
                         {"signer": "signer-sam", "signing_date": day(), "signature_id": sig["id"], "signed_copy_hash": sig["signed_copy_hash"]})
        self.assertEqual(c.execute(sp["id"], actor="signer-sam").result["status"], "signed")

        ex = c.request_approval("commitment.execute", cid, actor_role="pm", requested_by="pm-pat")
        bound = ex["manifest"]["governance"][PLUGIN_NAME]["agreement"]
        signed = k.agreement(a["id"])
        self.assertEqual((bound["id"], bound["status"], bound["signature_id"], bound["signer"], bound["approval_id"]),
                         (a["id"], "signed", sig["id"], "signer-sam", signed["approval_id"]))
        c.approve(ex["id"], approver="owner")
        done = c.execute(ex["id"], actor="pm-pat").result
        self.assertEqual((done["status"], done["executed_amount"]), ("executed", "100000.00"))
        self.assertEqual([s["amount"] for s in c.commitments.get(cid)["sov"]], ["60000.00", "40000.00"])

        # three separate authorities, three different people, each on record
        approve_ap = c.approvals.get(signed["approval_id"])
        sign_ap = c.approvals.get(sp["id"])
        self.assertEqual((approve_ap["approver"], approve_ap["operation"]), ("pm-pat", OP_APPROVE))
        self.assertEqual((sign_ap["approver"], sign_ap["consumed_by"]), ("signer-sam", "signer-sam"))
        self.assertEqual(c.approvals.get(ex["id"])["approver"], "owner")
        self.assertEqual((signed["status"], signed["signature"]["signer"], signed["signature"]["status"]), ("signed", "signer-sam", "signed"))
        self.assertTrue(c.audit.verify_chain()["ok"])
        self.assertTrue(all(chk["ok"] for chk in w.checks().values()), w.checks())

    def test_each_authority_belongs_to_its_own_roles(self):
        w = World()
        c = w.c
        cid = w.draft()
        a, _ = w.register(cid)
        for role in ("signer", "estimator", "treasury", "accountant"):
            with self.subTest(role=role), self.assertRaises(RoleNotAuthorized):
                c.request_approval(OP_APPROVE, a["id"], actor_role=role)
        ap = c.request_approval(OP_APPROVE, a["id"], actor_role="legal", requested_by="contracts-admin")  # legal reviewer may approve too
        with self.assertRaises(RoleNotAuthorized):
            c.approve(ap["id"], approver="signer-sam", approver_role="signer")
        c.approve(ap["id"], approver="counsel-lee", approver_role="legal")
        c.execute(ap["id"], actor="counsel-lee")
        w.prepare(a["id"], signer="signer-sam")
        for role in ("pm", "legal", "accountant"):
            with self.subTest(role=role), self.assertRaises(RoleNotAuthorized):
                c.request_approval(OP_SIGN, a["id"], actor_role=role)
        sp = c.request_approval(OP_SIGN, a["id"], actor_role="signer", requested_by="contracts-admin")
        with self.assertRaises(RoleNotAuthorized):
            c.approve(sp["id"], approver="signer-sam", approver_role="pm")
        with self.assertRaisesRegex(ContractError, "only the named signer"):  # nobody signs on the signer's behalf, not even the owner
            c.approve(sp["id"], approver="owner", approver_role="owner")
        with self.assertRaisesRegex(ContractError, "only the named signer"):
            c.approve(sp["id"], approver="signer-kim", approver_role="signer")
        self.assertEqual(c.approvals.get(sp["id"])["status"], "pending")
        c.approve(sp["id"], approver=" Signer-SAM ", approver_role="signer")  # the same login, as the registry keys it
        self.assertEqual(c.execute(sp["id"], actor="signer-sam").result["status"], "signed")

    def test_a_sole_owner_holds_every_step_but_each_is_still_a_separate_recorded_action(self):
        w = World()
        c = w.c
        cid = w.draft()
        a, _ = w.register(cid)
        c.approve_and_execute(OP_APPROVE, a["id"])
        w.prepare(a["id"], signer="owner")
        c.approve_and_execute(OP_SIGN, a["id"])
        c.approve_and_execute("commitment.execute", cid)
        ops = [ap["operation"] for ap in c.approvals.list(status="consumed")]
        self.assertEqual(ops, [OP_APPROVE, OP_SIGN, "commitment.execute"])
        self.assertEqual(c.commitments.get(cid)["status"], "executed")


# --------------------------------------------------------------------------- #
# Agreements and requirements                                                  #
# --------------------------------------------------------------------------- #

class AgreementRegistrationTests(unittest.TestCase):
    def test_an_agreement_binds_the_current_revision_of_an_agreement_document_on_the_commitments_project(self):
        w = World()
        k = w.k
        cid = w.draft()
        _, drawing = w.doc("drawing")
        _, foreign = w.doc("agreement", project_id=w.other_project["id"])
        old_doc, old_rev = w.doc("agreement")
        w.revise(old_doc)
        for evidence, msg in ((None, "requires the content hash"), ("0" * 64, "matches no stored document"),
                              (drawing["content_hash"], "only by a 'agreement' document"), (foreign["content_hash"], "another project"),
                              (old_rev["content_hash"], "superseded revision")):
            with self.subTest(msg=msg), self.assertRaisesRegex(ContractError, msg):
                k.register_agreement(cid, evidence, "contracts-admin")
        with self.assertRaisesRegex(ContractError, "unknown commitment"):
            k.register_agreement("cmt_missing", old_rev["content_hash"], "contracts-admin")
        with self.assertRaisesRegex(ContractError, "actor is required"):
            k.register_agreement(cid, old_rev["content_hash"], " ")
        a, _ = w.register(cid)
        self.assertEqual((a["status"], a["document_current"], a["problems"]), ("registered", True, []))
        self.assertEqual(a["sov_hash"], w.c.commitments.sov_hash(cid))
        done = w.draft("5000")
        w.c.approve_and_execute("commitment.execute", done)  # nothing configured on it: executes as before
        _, rev = w.doc("agreement")
        with self.assertRaisesRegex(ContractError, "draft commitment"):
            k.register_agreement(done, rev["content_hash"], "contracts-admin")

    def test_one_live_agreement_per_commitment_and_per_document_and_re_registering_supersedes(self):
        w = World()
        k = w.k
        cid, other = w.draft(), w.draft("1000")
        a, d = w.register(cid)
        rev1 = w.c.evidence.current_revision(d["id"])
        with self.assertRaisesRegex(ContractError, "already binds revision 1"):
            k.register_agreement(cid, rev1["content_hash"], "contracts-admin")
        with self.assertRaisesRegex(ContractError, "already backs agreement"):
            k.register_agreement(other, rev1["content_hash"], "contracts-admin")
        rev2 = w.revise(d, "marked-up terms")
        b = k.register_agreement(cid, rev2["content_hash"], "contracts-admin")
        self.assertEqual((k.agreement(a["id"])["status"], b["supersedes"], b["revision"], k.agreement_for(cid)["id"]),
                         ("superseded", a["id"], 2, b["id"]))
        self.assertEqual(len(k.agreements(w.pid)), 2)


class RequirementTests(unittest.TestCase):
    def test_requirements_are_validated_and_versioned(self):
        w = World()
        k = w.k
        cid = w.draft()
        bad = [
            ("not a list", "must be a list"), ([{"kind": "flood"}], "kind must be one of"),
            ([{"kind": "umbrella", "min_limit": 5000000.0}], "not exact money"),
            ([{"kind": "umbrella", "min_limit": "-1"}], "zero or more"), ([{"kind": "umbrella", "min_limit": "10.005"}], "whole cents"),
            ([{"kind": "umbrella", "min_limit": "1"}, {"kind": "umbrella", "min_limit": "2"}], "required twice"),
            ([{"kind": "umbrella", "min_limit": "1", "deductible": "5"}], "unknown field"),
        ]
        for reqs, msg in bad:
            with self.subTest(msg=msg), self.assertRaisesRegex(ContractError, msg):
                k.set_requirements(cid, reqs, "contracts-admin")
        with self.assertRaisesRegex(ContractError, "no requirements to clear"):
            k.set_requirements(cid, [], "contracts-admin")
        r1 = k.set_requirements(cid, [{"kind": "umbrella", "min_limit": "5,000,000"}, {"kind": "workers_comp", "min_limit": "0"},
                                      {"kind": "general_liability", "min_limit": "1000000"}], "contracts-admin")
        self.assertEqual(r1["version"], 1)
        self.assertEqual([r["kind"] for r in r1["requirements"]], ["general_liability", "workers_comp", "umbrella"])  # canonical order
        self.assertEqual(r1["requirements"][2]["min_limit"], "5000000.00")
        with self.assertRaisesRegex(ContractError, "already carries exactly"):
            k.set_requirements(cid, list(reversed(r1["requirements"])), "contracts-admin")
        self.assertEqual(k.set_requirements(cid, [], "contracts-admin")["version"], 2)
        self.assertEqual(k.requirements(cid)["requirements"], [])

    def test_a_negative_zero_minimum_is_stored_as_zero(self):
        w = World()
        k = w.k
        cid = w.draft()
        r = k.set_requirements(cid, [{"kind": "workers_comp", "min_limit": "-0"}], "contracts-admin")
        self.assertEqual(r["requirements"], [{"kind": "workers_comp", "min_limit": "0.00"}])
        with self.assertRaisesRegex(ContractError, "already carries exactly"):  # the same requirement, however it is spelled
            k.set_requirements(cid, [{"kind": "workers_comp", "min_limit": "0"}], "contracts-admin")

    def test_requirements_are_bound_into_the_agreement_approval_and_fixed_once_it_executes(self):
        w = World()
        c, k = w.c, w.k
        cid = w.draft()
        k.set_requirements(cid, GL + [{"kind": "performance_bond", "min_limit": "100000"}], "contracts-admin")
        a, _ = w.register(cid)
        ap = w.request_agreement_approval(a["id"])
        bound = ap["manifest"]["bindings"]
        self.assertEqual([r["kind"] for r in bound["requirements"]], ["general_liability", "performance_bond"])
        self.assertEqual(bound["requirements_hash"], k.requirements(cid)["requirements_hash"])
        # a change after the request: the approver saw other requirements
        k.set_requirements(cid, GL, "contracts-admin")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        w.approve_agreement(a["id"])
        self.assertEqual(k.agreement(a["id"])["requirements_hash"], k.requirements(cid)["requirements_hash"])
        with self.assertRaisesRegex(ContractError, "fixed now"):
            k.set_requirements(cid, [], "contracts-admin")
        rs = c.db.one("SELECT * FROM contract_requirement_sets WHERE commitment_id=? ORDER BY version DESC LIMIT 1", (cid,))
        with self.assertRaises(sqlite3.DatabaseError):  # nor by raw SQL, even with an audit entry
            c.audit.record("x", "contract.requirements_set", "commitment", cid, {"set_id": "creq_forged", "version": rs["version"] + 1,
                                                                                    "requirements_hash": "0" * 64})
            c.db.execute("INSERT INTO contract_requirement_sets (id, commitment_id, version, requirements_json, requirements_hash, requirement_count, set_by, set_at) "
                         "VALUES ('creq_forged', ?, ?, '[]', ?, 0, 'x', 'now')", (cid, rs["version"] + 1, "0" * 64))
        with self.assertRaises(sqlite3.DatabaseError):
            c.db.execute("UPDATE contract_requirement_sets SET requirements_json='[]', requirement_count=0 WHERE id=?", (rs["id"],))

    def test_requirements_are_set_only_on_a_draft_commitment(self):
        w = World()
        cid = w.draft()
        w.c.approve_and_execute("commitment.execute", cid)
        with self.assertRaisesRegex(ContractError, "while it is a draft"):
            w.k.set_requirements(cid, GL, "contracts-admin")


class AgreementApprovalTests(unittest.TestCase):
    def test_the_manifest_binds_the_commitment_its_sov_amount_and_the_agreement_revision(self):
        w = World()
        cid = w.draft("60000", "40000")
        a, d = w.register(cid)
        m = w.c.request_approval(OP_APPROVE, a["id"], actor_role="pm")["manifest"]
        b = m["bindings"]
        self.assertEqual((m["subject"], m["entity"], m["currency"], m["amounts"]),
                         ({"type": "contract_agreement", "id": a["id"]}, ENTITY, "USD", {"commitment_total": "100000.00"}))
        self.assertEqual((b["commitment_id"], b["commitment_version"], b["commitment_status"], b["sov_hash"], b["agreement_revision_hash"], b["revision"]),
                         (cid, 1, "draft", w.c.commitments.sov_hash(cid), a["evidence_hash"], 1))
        self.assertEqual([s["amount"] for s in b["sov"]], ["60000.00", "40000.00"])
        self.assertEqual((b["requirements"], b["requirements_hash"]), ([], None))

    def test_an_agreement_revised_before_its_approval_executes_invalidates_the_approval(self):
        w = World()
        c = w.c
        cid = w.draft()
        a, d = w.register(cid)
        ap = w.request_agreement_approval(a["id"])
        w.revise(d, "counterparty edits")
        with self.assertRaises(StaleApprovalError):
            c.execute(ap["id"], actor="pm-pat")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(w.k.agreement(a["id"])["status"], "registered")
        with self.assertRaisesRegex(AgreementIneligible, "was revised"):
            c.request_approval(OP_APPROVE, a["id"], actor_role="pm")

    def test_an_agreement_revised_after_approval_is_never_signed_until_the_new_revision_is_approved(self):
        w = World()
        c, k = w.c, w.k
        cid = w.draft()
        a, d = w.register(cid)
        w.approve_agreement(a["id"])
        sig, _ = w.prepare(a["id"])
        sp = w.request_signature(a["id"])
        rev2 = w.revise(d, "price clause changed after approval")
        with self.assertRaises(StaleApprovalError):  # the signer would sign a revision nobody approved
            c.execute(sp["id"], actor="signer-sam")
        self.assertEqual((c.approvals.get(sp["id"])["status"], k.agreement(a["id"])["status"]), ("invalidated", "approved"))
        with self.assertRaisesRegex(ContractError, "was revised"):
            w.prepare(a["id"])
        with self.assertRaisesRegex(AgreementIneligible, "was revised"):
            c.request_approval(OP_SIGN, a["id"], actor_role="signer")
        with self.assertRaisesRegex(ContractError, "cannot be executed yet"):
            c.request_approval("commitment.execute", cid, actor_role="pm")
        # the new revision is registered (superseding the approved one), approved and signed afresh
        b = k.register_agreement(cid, rev2["content_hash"], "contracts-admin")
        self.assertEqual((k.agreement(a["id"])["status"], k.signature(sig["id"])["status"]), ("superseded", "withdrawn"))
        w.approve_agreement(b["id"])
        w.sign(b["id"])
        self.assertEqual(w.execute_commitment(cid).result["status"], "executed")
        self.assertEqual(k.agreement(b["id"])["status"], "signed")


class SignatureTests(unittest.TestCase):
    def test_prepare_signature_rules(self):
        w = World()
        c, k = w.c, w.k
        cid = w.draft()
        a, _ = w.register(cid)
        _, copy = w.doc("signed_agreement")
        with self.assertRaisesRegex(ContractError, "is registered; a signature is prepared for an approved agreement"):
            k.prepare_signature(a["id"], copy["content_hash"], "signer-sam", day(), "contracts-admin")
        w.approve_agreement(a["id"])
        _, agreement_doc = w.doc("agreement")
        _, foreign = w.doc("signed_agreement", project_id=w.other_project["id"])
        for evidence, signing_date, msg in (
            (agreement_doc["content_hash"], day(), "only by a 'signed_agreement' document"),
            (foreign["content_hash"], day(), "another project"),
            (copy["content_hash"], day(-1), "before the agreement was approved"),
            (copy["content_hash"], day(2), "in the future"),
            (copy["content_hash"], "2026-02-30", "not a valid calendar date"),
        ):
            with self.subTest(msg=msg), self.assertRaisesRegex(ContractError, msg):
                k.prepare_signature(a["id"], evidence, "signer-sam", signing_date, "contracts-admin")
        first = k.prepare_signature(a["id"], copy["content_hash"], "signer-sam", day(), "contracts-admin")
        sp = c.request_approval(OP_SIGN, a["id"], actor_role="signer")
        w.clock(2)  # a signing date two days out is allowed once that day has come
        second, _ = w.prepare(a["id"], signer="signer-kim", signing_date=day(2))
        self.assertEqual((k.signature(first["id"])["status"], c.approvals.get(sp["id"])["status"]), ("withdrawn", "invalidated"))
        ap = w.request_signature(a["id"], signer="signer-kim")
        self.assertEqual(ap["manifest"]["bindings"]["signature_id"], second["id"])

    def test_a_signed_copy_revised_after_the_request_invalidates_the_signature_approval(self):
        w = World()
        c = w.c
        cid = w.draft()
        a, _ = w.register(cid)
        w.approve_agreement(a["id"])
        _, copy_doc = w.prepare(a["id"])
        sp = w.request_signature(a["id"])
        w.revise(copy_doc, "a different page 3")
        with self.assertRaises(StaleApprovalError):
            c.execute(sp["id"], actor="signer-sam")
        self.assertEqual(w.k.agreement(a["id"])["status"], "approved")


# --------------------------------------------------------------------------- #
# Governor: commitment execution                                               #
# --------------------------------------------------------------------------- #

class ExecutionGovernanceTests(unittest.TestCase):
    def test_a_commitment_with_an_unsigned_agreement_does_not_execute_by_any_path(self):
        w = World()
        c, k = w.c, w.k
        cid = w.draft()
        pre = c.request_approval("commitment.execute", cid, actor_role="pm")  # requested before the agreement existed
        a, _ = w.register(cid)
        self.assertEqual(c.approvals.get(pre["id"])["status"], "invalidated")
        with self.assertRaisesRegex(ContractError, "registered, not signed"):
            c.request_approval("commitment.execute", cid, actor_role="pm")
        w.approve_agreement(a["id"])
        with self.assertRaisesRegex(ContractError, "approved, not signed; contract.sign must execute"):
            c.request_approval("commitment.execute", cid, actor_role="pm")
        # a direct path around the governor: an approval consumed outside Cipher.execute
        m = c.commitments.manifest(cid, actor_role="owner")
        ap = c.approvals.request(m, requested_by="owner")
        c.approvals.grant(ap["id"], approver="owner")
        c.approvals.consume(ap["id"], current_manifest=m, consumer="owner")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "only with its signed agreement"):
            c.commitments.execute(cid, approval_id=ap["id"], actor="owner")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "only with its signed agreement"):
            c.db.execute("UPDATE commitments SET status='executed', version=version+1 WHERE id=?", (cid,))
        self.assertEqual(c.commitments.get(cid)["status"], "draft")
        # check_execute itself refuses an unsigned agreement (invalidating the approval)
        facts = k._execution_facts(cid)
        with self.assertRaises(AgreementIneligible):
            k.check_execute({"operation": "commitment.execute", "subject_id": cid}, {"governance": {PLUGIN_NAME: facts}}, actor="pm-pat")

    def test_revising_the_signed_agreement_document_invalidates_an_open_execution_approval(self):
        w = World()
        c = w.c
        cid = w.draft()
        a, d = w.register(cid)
        w.approve_agreement(a["id"])
        w.sign(a["id"])
        ex = c.request_approval("commitment.execute", cid, actor_role="pm")
        c.approve(ex["id"], approver="owner")
        w.revise(d, "uploaded after signature")
        with self.assertRaisesRegex(StaleApprovalError, "contract changed"):
            c.execute(ex["id"], actor="pm-pat")
        self.assertEqual(c.approvals.get(ex["id"])["status"], "invalidated")
        with self.assertRaisesRegex(ContractError, "was revised"):
            c.request_approval("commitment.execute", cid, actor_role="pm")

    def test_a_schedule_of_values_changed_after_signature_blocks_execution(self):
        w = World()
        c = w.c
        cid = w.draft("60000", "40000")
        a, _ = w.register(cid)
        w.approve_agreement(a["id"])
        w.sign(a["id"])
        c.db.execute("UPDATE sov_lines SET amount='65000.00' WHERE id=?", (w.line(cid),))  # raw edit of the draft's SOV
        with self.assertRaisesRegex(ContractError, "schedule of values"):
            c.request_approval("commitment.execute", cid, actor_role="pm")
        c.db.execute("UPDATE commitments SET original_amount='105000.00', executed_amount='105000.00' WHERE id=?", (cid,))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "only with its signed agreement"):
            c.db.execute("UPDATE commitments SET status='executed' WHERE id=?", (cid,))

    def test_a_retainage_rate_changed_after_the_agreement_approval_blocks_signature_and_execution(self):
        w = World()
        c, k = w.c, w.k
        cid = w.draft()
        a, _ = w.register(cid)
        w.approve_agreement(a["id"])  # the approver saw 10% retainage
        c.db.execute("UPDATE commitments SET retainage_rate='0.000000' WHERE id=?", (cid,))  # raw edit of the draft's retainage
        with self.assertRaisesRegex(ContractError, "retainage rate"):
            w.prepare(a["id"])
        c.db.execute("UPDATE commitments SET retainage_rate='0.100000' WHERE id=?", (cid,))
        w.sign(a["id"])
        c.db.execute("UPDATE commitments SET retainage_rate='0.000000' WHERE id=?", (cid,))
        with self.assertRaisesRegex(ContractError, "retainage rate"):
            c.request_approval("commitment.execute", cid, actor_role="pm")
        self.assertTrue(any("retainage rate" in p for p in k.agreement(a["id"])["problems"]))
        self.assertEqual(c.commitments.get(cid)["status"], "draft")


class WorkspaceSwitchTests(unittest.TestCase):
    def test_requiring_agreements_is_the_owners_alone_and_happens_once(self):
        w = World()
        c, k = w.c, w.k
        self.assertFalse(k.agreements_required())
        with self.assertRaises((ContractError, RoleNotAuthorized)):
            c.request_approval(OP_REQUIRE, WORKSPACE_SUBJECT_ID, actor_role="pm")
        with self.assertRaisesRegex(ContractError, "applies to subject"):
            c.request_approval(OP_REQUIRE, "another-workspace", actor_role="owner")
        ap = c.request_approval(OP_REQUIRE, WORKSPACE_SUBJECT_ID, actor_role="owner")
        with self.assertRaises(RoleNotAuthorized):
            c.approve(ap["id"], approver="controller", approver_role="controller")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "pending")
        c.approve(ap["id"], approver="owner", approver_role="owner")
        self.assertTrue(c.execute(ap["id"], actor="owner").result["agreements_required"])
        self.assertTrue(k.agreements_required())
        with self.assertRaisesRegex(ContractError, "already required"):
            c.request_approval(OP_REQUIRE, WORKSPACE_SUBJECT_ID, actor_role="owner")
        for sql in ("DELETE FROM contract_workspace_policy", "UPDATE contract_workspace_policy SET set_by='someone else'"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql)
        self.assertTrue(k.agreements_required())

    def test_after_the_switch_every_commitment_executed_needs_a_signed_agreement(self):
        w = World()
        c = w.c
        before = w.draft("20000")
        c.approve_and_execute("commitment.execute", before)
        pending = w.draft("15000")
        granted = c.request_approval("commitment.execute", pending, actor_role="pm")
        c.approve(granted["id"], approver="owner")
        c.approve_and_execute(OP_REQUIRE, WORKSPACE_SUBJECT_ID)
        with self.assertRaisesRegex(StaleApprovalError, "contract changed"):  # granted before the switch, executed after it
            c.execute(granted["id"], actor="pm-pat")
        with self.assertRaisesRegex(ContractError, "agreements are required in this workspace"):
            c.request_approval("commitment.execute", pending, actor_role="pm")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "only with its signed agreement"):
            c.db.execute("UPDATE commitments SET status='executed' WHERE id=?", (pending,))
        # a commitment executed before the switch is unaffected
        w.post(w.certify(before, "10000")["id"])
        self.assertTrue(w.checks()[SIGN_CHECK]["ok"])
        a, _ = w.register(pending)
        w.approve_agreement(a["id"])
        w.sign(a["id"])
        self.assertEqual(w.execute_commitment(pending).result["status"], "executed")
        w.post(w.certify(pending, "5000")["id"])
        self.assertTrue(w.checks()[SIGN_CHECK]["ok"])
        self.assertTrue(w.k.state(w.pid)["agreements_required"])


# --------------------------------------------------------------------------- #
# Certificates and the coverage governor                                       #
# --------------------------------------------------------------------------- #

class CertificateTests(unittest.TestCase):
    def test_record_certificate_validation(self):
        w = World()
        k = w.k
        d, rev = w.doc("insurance_certificate")
        _, drawing = w.doc("drawing")
        ok = dict(kind="general_liability", carrier="Synthetic Mutual", policy_number="GL-SIM-1", limit="2000000", effective_date=day(-1),
                  expiry_date=day(364), evidence_hash=rev["content_hash"], actor="contracts-admin")
        bad = [
            (dict(party_id=w.customer["id"]), "recorded for suppliers"), (dict(party_id="pty_missing"), "unknown party"),
            (dict(kind="flood"), "kind must be one of"), (dict(limit=2000000.0), "not exact money"), (dict(limit="0"), "positive"),
            (dict(expiry_date=day(-2)), "before its effective date"), (dict(effective_date="20261001"), "YYYY-MM-DD"),
            (dict(evidence_hash=drawing["content_hash"]), "'insurance_certificate' document"), (dict(carrier=""), "carrier is required"),
        ]
        for change, msg in bad:
            args = {"party_id": w.supplier["id"], **ok, **change}
            with self.subTest(msg=msg), self.assertRaisesRegex(ContractError, msg):
                k.record_certificate(**args)
        gl = k.record_certificate(w.supplier["id"], **ok)
        self.assertEqual((gl["status"], gl["in_force"], gl["limit_amount"], gl["stale"]), ("recorded", True, "2000000.00", False))
        # one ACORD-style form carries several coverages of one supplier, each kind once
        auto = k.record_certificate(w.supplier["id"], **{**ok, "kind": "auto_liability", "policy_number": "AU-SIM-1"})
        self.assertEqual(auto["document_id"], d["id"])
        with self.assertRaisesRegex(ContractError, "already carries general_liability"):
            k.record_certificate(w.supplier["id"], **ok)
        with self.assertRaisesRegex(ContractError, "already belongs to supplier"):
            k.record_certificate(w.other_supplier["id"], **{**ok, "kind": "umbrella"})
        bond = w.certificate("performance_bond", "100000")  # a surety bond: surety, bond number, penal sum
        self.assertEqual((bond["kind"], bond["in_force"]), ("performance_bond", True))
        self.assertEqual(set(COVERAGE_KINDS), {"general_liability", "workers_comp", "auto_liability", "umbrella", "professional",
                                               "performance_bond", "payment_bond"})

    def test_a_later_revision_of_the_certificate_document_makes_it_stale_and_withdrawal_is_recorded(self):
        w = World()
        k = w.k
        d, _ = w.doc("insurance_certificate")
        cert = w.certificate(document=d)
        w.revise(d, "endorsement added")
        self.assertEqual((k.certificate(cert["id"])["stale"], k.certificate(cert["id"])["in_force"]), (True, False))
        other = w.certificate("umbrella", "5000000")
        with self.assertRaisesRegex(ContractError, "reason is required"):
            k.withdraw_certificate(other["id"], "", "contracts-admin")
        out = k.withdraw_certificate(other["id"], "insurer cancellation notice (synthetic)", "contracts-admin")
        self.assertEqual((out["status"], out["in_force"], out["withdrawn_by"]), ("withdrawn", False, "contracts-admin"))
        with self.assertRaisesRegex(ContractError, "already withdrawn"):
            k.withdraw_certificate(other["id"], "again", "contracts-admin")


class CoverageGovernanceTests(unittest.TestCase):
    def test_bill_approval_binds_the_covering_certificates_and_records_which_one_covered(self):
        w = World()
        c, k = w.c, w.k
        cert = w.certificate(limit="2000000")
        w.certificate(limit="500000")  # below the minimum: never bound
        cid = w.signed_commitment(requirements=GL)
        bill = w.certify(cid)
        ap = w.request_post(bill["id"])
        facts = ap["manifest"]["governance"][PLUGIN_NAME]
        self.assertEqual(facts["requirement_sets"][0]["commitment_id"], cid)
        [cov] = facts["coverage"]
        self.assertEqual((cov["kind"], cov["min_limit"], [x["id"] for x in cov["certificates"]]), ("general_liability", "1000000.00", [cert["id"]]))
        res = c.execute(ap["id"], actor="accountant")
        self.assertEqual(res.result["status"], "posted")
        check = c.db.one("SELECT * FROM contract_coverage_checks WHERE approval_id=?", (ap["id"],))
        self.assertEqual((check["operation"], check["checked_on"], cert["id"] in check["coverage_json"]), ("bill.approve", day(), True))
        rel = w.request_release(bill["id"])
        self.assertIn(PLUGIN_NAME, rel["manifest"]["governance"])
        c.execute(rel["id"], actor="treasury")
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM contract_coverage_checks"), 2)
        self.assertTrue(all(chk["ok"] for chk in w.checks().values()), w.checks())

    def test_missing_short_or_stale_coverage_refuses_the_request(self):
        w = World()
        c, k = w.c, w.k
        cid = w.signed_commitment(requirements=GL + [{"kind": "workers_comp", "min_limit": "0"}])
        bill = w.certify(cid)
        with self.assertRaisesRegex(CoverageError, "general_liability .*no current certificate"):
            c.request_approval("bill.approve", bill["id"], actor_role="accountant")
        d, _ = w.doc("insurance_certificate")
        short = w.certificate(limit="999999.99", document=d)
        w.certificate("workers_comp", "500000")
        with self.assertRaisesRegex(CoverageError, "general_liability"):
            c.request_approval("bill.approve", bill["id"], actor_role="accountant")
        self.assertIn("below the minimum", " ".join(k.coverage(cid)[0]["reasons"]))
        cover = w.certificate(limit="1000000")
        w.post(bill["id"])  # covered now
        w.revise(c.evidence.document(cover["document_id"]), "certificate reissued")
        with self.assertRaisesRegex(CoverageError, "general_liability"):
            w.request_release(bill["id"])
        self.assertIn("stale", " ".join(k.coverage(cid)[0]["reasons"]))
        self.assertTrue(short["id"])

    def test_an_expired_certificate_blocks_a_release(self):
        w = World()
        c, k = w.c, w.k
        w.certificate(limit="2000000", effective=-30, expiry=5)
        cid = w.signed_commitment(requirements=GL)
        bill = w.certify(cid)
        w.post(bill["id"])
        rel = w.request_release(bill["id"])
        w.clock(6)  # the policy expired before treasury executed the release
        with self.assertRaisesRegex(CoverageError, "expired on " + day(5)):
            c.execute(rel["id"], actor="treasury")
        self.assertEqual(c.approvals.get(rel["id"])["status"], "granted")  # refused, not consumed
        self.assertEqual((c.payments.list(), c.db.scalar("SELECT COUNT(*) FROM contract_coverage_checks")), ([], 1))
        self.assertFalse(w.checks()[COVERAGE_CHECK]["ok"])
        self.assertIn("not in force", w.checks()[COVERAGE_CHECK]["detail"])
        renewal = w.certificate(limit="2000000", effective=5, expiry=370)
        with self.assertRaisesRegex(StaleApprovalError, "contract changed"):  # the approver saw other evidence
            c.execute(rel["id"], actor="treasury")
        again = w.request_release(bill["id"])
        res = c.execute(again["id"], actor="treasury")
        self.assertEqual(res.result["status"], "queued")
        check = c.db.one("SELECT coverage_json FROM contract_coverage_checks WHERE approval_id=?", (again["id"],))
        self.assertIn(renewal["id"], check["coverage_json"])
        self.assertTrue(w.checks()[COVERAGE_CHECK]["ok"])

    def test_a_renewal_recorded_ahead_of_time_does_not_displace_the_policy_in_force(self):
        w = World()
        c = w.c
        current = w.certificate(effective=-300, expiry=20)
        renewal = w.certificate(effective=21, expiry=385)
        cid = w.signed_commitment(requirements=GL)
        bill = w.certify(cid)
        ap = w.request_post(bill["id"])
        self.assertEqual([x["id"] for x in ap["manifest"]["governance"][PLUGIN_NAME]["coverage"][0]["certificates"]], [current["id"], renewal["id"]])
        c.execute(ap["id"], actor="accountant")
        self.assertIn(current["id"], c.db.scalar("SELECT coverage_json FROM contract_coverage_checks WHERE approval_id=?", (ap["id"],)))
        self.assertTrue(w.checks()[COVERAGE_CHECK]["ok"])  # the renewal is on file: nothing is expiring uncovered

    def test_withdrawing_a_bound_certificate_invalidates_the_open_approval(self):
        w = World()
        c, k = w.c, w.k
        cert = w.certificate()
        cid = w.signed_commitment(requirements=GL)
        bill = w.certify(cid)
        ap = w.request_post(bill["id"])
        k.withdraw_certificate(cert["id"], "recorded against the wrong policy", "contracts-admin")
        with self.assertRaises(StaleApprovalError):
            c.execute(ap["id"], actor="accountant")
        self.assertEqual(c.bills.get(bill["id"])["status"], "draft")

    def test_a_retainage_payment_needs_the_coverage_of_every_commitment_it_may_pay(self):
        w = World()
        c = w.c
        w.certificate(limit="2000000", expiry=40)
        governed = w.signed_commitment(requirements=GL)
        plain = w.draft("20000")
        c.approve_and_execute("commitment.execute", plain)
        w.post(w.certify(governed)["id"])
        w.post(w.certify(plain, "10000")["id"])
        c.commitments.close(governed, actor="pm-pat")
        c.approve_and_execute("retainage.release", governed, actor_role="accountant", period_id="P1")
        w.clock(41)
        # naming the commitment without requirements still pays the governed commitment's retainage
        with self.assertRaisesRegex(CoverageError, "expired"):
            c.request_approval("payment.release_retainage", plain, actor_role="treasury")
        w.certificate(limit="2000000", effective=40, expiry=400)
        res = c.approve_and_execute("payment.release_retainage", plain, actor_role="treasury", actor="treasury")
        self.assertEqual(res.result["amount"], "3000.00")
        self.assertEqual(c.db.scalar("SELECT operation FROM contract_coverage_checks ORDER BY checked_at DESC, id DESC LIMIT 1"), "payment.release_retainage")

    def test_a_spent_or_rejected_approval_is_refused_as_such_not_by_the_contract_checks(self):
        w = World()
        c = w.c
        w.certificate(limit="2000000", expiry=5)
        cid = w.signed_commitment(requirements=GL)
        bill = w.certify(cid)
        ap = w.request_post(bill["id"])
        c.execute(ap["id"], actor="accountant")
        with self.assertRaises(ApprovalConsumed):  # a replay under another operation id
            c.execute(ap["id"], actor="accountant", op_id="retry-bill-approve")
        executed = next(a for a in c.approvals.list(status="consumed") if a["operation"] == "commitment.execute")
        with self.assertRaises(ApprovalConsumed):
            c.execute(executed["id"], actor="pm-pat", op_id="retry-commitment-execute")
        rel = w.request_release(bill["id"])
        c.reject(rel["id"], approver="owner", reason="held for the payment run")
        w.clock(6)  # the certificate has expired too; the rejection is still the reason nothing runs
        with self.assertRaises(ApprovalNotGranted):
            c.execute(rel["id"], actor="treasury")
        self.assertEqual((c.db.scalar("SELECT COUNT(*) FROM contract_coverage_checks"), c.payments.list()), (1, []))

    def test_requirements_set_after_a_retainage_payment_do_not_make_it_ungoverned(self):
        w = World()
        c = w.c
        first = w.draft("20000")
        c.approve_and_execute("commitment.execute", first)
        w.post(w.certify(first, "10000")["id"])
        c.commitments.close(first, actor="pm-pat")
        c.approve_and_execute("retainage.release", first, actor_role="accountant", period_id="P1")
        c.approve_and_execute("payment.release_retainage", first, actor_role="treasury", actor="treasury")  # nothing required then
        later = w.draft("5000")  # the supplier's next subcontract on the project carries requirements
        w.k.set_requirements(later, GL, "contracts-admin")
        self.assertTrue(w.checks()[INTEGRITY_CHECK]["ok"], w.checks()[INTEGRITY_CHECK]["detail"])
        # a retainage payment made around the governor while those requirements stand is still caught
        second = w.draft("10000")
        c.approve_and_execute("commitment.execute", second)
        w.post(w.certify(second, "5000")["id"])
        c.commitments.close(second, actor="pm-pat")
        c.approve_and_execute("retainage.release", second, actor_role="accountant", period_id="P1")
        m = c.payments.manifest_for_retainage(second, actor_role="treasury")
        m["operation"] = "payment.release_retainage"
        ap = c.approvals.request(m, requested_by="ap-clerk")
        c.approvals.grant(ap["id"], approver="owner")
        c.approvals.consume(ap["id"], current_manifest=m, consumer="treasury")
        intent = c.payments.create_intent(manifest=m, approval_id=ap["id"], bill_id=None, note="retainage release payment", actor="treasury")
        detail = w.checks()[INTEGRITY_CHECK]["detail"]
        self.assertIn(f"payment {intent['id']} was released under approval {ap['id']} without a recorded coverage check", detail)
        self.assertEqual(detail.count("without a recorded coverage check"), 1)


# --------------------------------------------------------------------------- #
# Close checks, state, Ricky                                                   #
# --------------------------------------------------------------------------- #

class CloseCheckAndStateTests(unittest.TestCase):
    def test_a_certificate_expiring_within_30_days_without_renewal_fails_the_check_and_reaches_ricky_and_the_close(self):
        w = World()
        c = w.c
        cid = w.draft()  # an open (draft) commitment is enough
        cert = w.certificate("umbrella", "5000000", effective=-300, expiry=25)
        w.certificate("general_liability", "2000000", effective=-300, expiry=31)  # 31 days out: not yet flagged
        chk = w.checks()[COVERAGE_CHECK]
        self.assertFalse(chk["ok"])
        self.assertIn(f"umbrella {cert['policy_number']}", chk["detail"])
        self.assertNotIn("general_liability", chk["detail"])
        brief = c.ricky.brief(w.pid)
        self.assertTrue(any(it["kind"] == "close_check" and COVERAGE_CHECK in it["text"] for it in brief["items"]))
        closing = c.plugin("close").checklist("P1")
        self.assertIn((COVERAGE_CHECK, False), [(x["check"], x["ok"]) for x in closing])
        self.assertEqual([e["certificate_id"] for e in w.k.state(w.pid)["expiring"]], [cert["id"]])
        w.certificate("umbrella", "5000000", effective=25, expiry=390)  # the renewal arrives
        self.assertTrue(w.checks()[COVERAGE_CHECK]["ok"])
        self.assertTrue(cid)

    def test_a_renewal_that_leaves_a_gap_or_falls_short_of_the_minimum_does_not_silence_the_warning(self):
        cases = (
            ("renewal starts ten days after the policy ends", GL, "2000000", 20),
            ("renewal below the required minimum", GL, "500000", 11),
            ("renewal with a gap, nothing required", None, "2000000", 20),
        )
        for label, requirements, renewal_limit, renewal_effective in cases:
            with self.subTest(case=label):
                w = World()
                current = w.certificate(limit="2000000", effective=-300, expiry=10)
                w.certificate(limit=renewal_limit, effective=renewal_effective, expiry=385)
                cid = w.signed_commitment(requirements=requirements)
                bill = w.certify(cid)
                if requirements:
                    w.post(bill["id"])  # covered today
                chk = w.checks()[COVERAGE_CHECK]
                self.assertFalse(chk["ok"], chk)
                self.assertIn(f"general_liability {current['policy_number']}", chk["detail"])
                self.assertEqual([e["certificate_id"] for e in w.k.state(w.pid)["expiring"]], [current["id"]])
                if requirements:
                    w.clock(15)  # the warning was right: in fifteen days nothing covers the requirement
                    with self.assertRaises(CoverageError):
                        w.request_release(bill["id"])

    def test_a_billed_commitment_that_needs_a_signed_agreement_and_lacks_one_is_reported(self):
        w = World()
        c = w.c
        c.approve_and_execute(OP_REQUIRE, WORKSPACE_SUBJECT_ID)
        cid = w.draft()
        # around every guard: the storage trigger dropped and the status written by raw SQL
        c.db.execute("DROP TRIGGER contract_commitment_needs_signed_agreement")
        c.db.execute("UPDATE commitments SET status='executed', executed_at='2026-10-12T00:00:00Z' WHERE id=?", (cid,))
        self.assertTrue(w.checks()[SIGN_CHECK]["ok"])  # no bills yet
        w.certify(cid)
        chk = w.checks()[SIGN_CHECK]
        self.assertFalse(chk["ok"])
        self.assertIn(cid, chk["detail"])
        self.assertEqual([u["commitment_id"] for u in w.k.state(w.pid)["unsigned_billed_commitments"]], [cid])

    def test_state_reports_agreements_requirements_coverage_and_certificates(self):
        w = World()
        k = w.k
        cert = w.certificate()
        cid = w.signed_commitment(requirements=GL)
        draft = w.draft("1000")
        w.register(draft)
        st = k.state(w.pid)
        self.assertEqual((st["summary"]["signed"], st["summary"]["registered"], st["summary"]["certificates_in_force"]), (1, 1, 1))
        row = next(x for x in st["commitments"] if x["commitment_id"] == cid)
        self.assertEqual((row["agreement"]["status"], row["coverage"][0]["certificate_id"], row["agreement_required"]), ("signed", cert["id"], True))
        self.assertEqual(w.c.project_state(w.pid)[PLUGIN_NAME]["summary"]["agreements"], 2)
        export = w.c.audit_export()["modules"][PLUGIN_NAME]
        self.assertEqual((len(export["agreements"]), len(export["certificates"]), export["integrity_problems"]), (2, 1, []))
        self.assertEqual(k.state("prj_missing")["agreements"], [])


# --------------------------------------------------------------------------- #
# Tampering                                                                    #
# --------------------------------------------------------------------------- #

class TamperingTests(unittest.TestCase):
    def test_raw_sql_cannot_rewrite_replace_or_delete_contract_records(self):
        w = World()
        c = w.c
        cert = w.certificate()
        cid = w.signed_commitment(requirements=GL)
        a = w.k.agreement_for(cid)
        draft = w.draft("1000")
        reg, _ = w.register(draft)
        w.post(w.certify(cid)["id"])
        probes = [
            ("UPDATE contract_agreements SET status='approved' WHERE id=?", reg["id"]),
            ("UPDATE contract_agreements SET evidence_hash='forged' WHERE id=?", a["id"]),
            ("UPDATE contract_agreements SET status='superseded', superseded_at='x', superseded_reason='x' WHERE id=?", a["id"]),
            ("DELETE FROM contract_agreements WHERE id=?", reg["id"]),
            ("UPDATE contract_signatures SET signer='someone-else' WHERE id=?", a["signature_id"]),
            ("UPDATE contract_signatures SET status='withdrawn' WHERE id=?", a["signature_id"]),
            ("DELETE FROM contract_signatures WHERE id=?", a["signature_id"]),
            ("UPDATE contract_certificates SET limit_amount='9000000.00' WHERE id=?", cert["id"]),
            ("UPDATE contract_certificates SET expiry_date='2099-12-31' WHERE id=?", cert["id"]),
            ("DELETE FROM contract_certificates WHERE id=?", cert["id"]),
            ("DELETE FROM contract_requirement_sets WHERE commitment_id=?", cid),
            ("UPDATE contract_coverage_checks SET coverage_json='[]' WHERE approval_id IS NOT ?", "x"),
            ("DELETE FROM contract_coverage_checks WHERE approval_id IS NOT ?", "x"),
            ("UPDATE commitments SET status='executed' WHERE id=?", draft),
        ]
        for sql, arg in probes:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql, (arg,))
        cols = [r["name"] for r in c.db.query("PRAGMA table_info(contract_agreements)")]
        clone = dict(c.db.one("SELECT * FROM contract_agreements WHERE id=?", (reg["id"],)))
        clone.update(status="signed")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "never replaced"):
            c.db.execute(f"INSERT OR REPLACE INTO contract_agreements ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(clone[x] for x in cols))
        forged = dict(c.db.one("SELECT * FROM contract_certificates WHERE id=?", (cert["id"],)))
        forged.update(id="ccert_forged", kind="umbrella", limit_amount="9000000.00")
        cert_cols = list(forged)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "only through record_certificate"):
            c.db.execute(f"INSERT INTO contract_certificates ({', '.join(cert_cols)}) VALUES ({', '.join('?' * len(cert_cols))})", tuple(forged.values()))
        with self.assertRaises(sqlite3.DatabaseError):
            c.db.execute("INSERT INTO contract_workspace_policy (id, agreements_required, workspace_id, approval_id, set_by, set_at) "
                         "VALUES (1, 1, 'ws', ?, 'x', 'now')", (a["approval_id"],))
        self.assertEqual((w.k.agreement(a["id"])["status"], w.k.certificate(cert["id"])["limit_amount"]), ("signed", "2000000.00"))
        self.assertTrue(w.checks()[INTEGRITY_CHECK]["ok"])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_tampering_around_dropped_triggers_is_detected_and_never_relied_on(self):
        w = World()
        c, k = w.c, w.k
        cert = w.certificate(limit="2000000")
        cid = w.signed_commitment(requirements=GL)
        bill = w.certify(cid)
        c.db.execute("DROP TRIGGER contract_certificates_binding_immutable")
        c.db.execute("DROP TRIGGER contract_certificates_lifecycle")
        c.db.execute("UPDATE contract_certificates SET expiry_date='2099-12-31' WHERE id=?", (cert["id"],))
        chk = w.checks()[INTEGRITY_CHECK]
        self.assertFalse(chk["ok"])
        self.assertIn(f"certificate {cert['id']} does not match its audited record", chk["detail"])
        with self.assertRaisesRegex(CoverageError, "general_liability"):  # a tampered certificate covers nothing
            c.request_approval("bill.approve", bill["id"], actor_role="accountant")
        self.assertFalse(k.certificate(cert["id"])["intact"])

    def test_a_posting_that_went_around_the_governor_is_detected(self):
        w = World()
        c = w.c
        w.certificate()
        cid = w.signed_commitment(requirements=GL)
        bill = w.certify(cid)
        m = c.bills.manifest(bill["id"], actor_role="accountant")  # built without the governors
        ap = c.approvals.request(m, requested_by="ap-clerk")
        c.approvals.grant(ap["id"], approver="controller")
        c.approvals.consume(ap["id"], current_manifest=m, consumer="accountant")
        c.bills.post(bill["id"], approval_id=ap["id"], actor="accountant")
        chk = w.checks()[INTEGRITY_CHECK]
        self.assertFalse(chk["ok"])
        self.assertIn(f"bill {bill['id']} was posted under approval {ap['id']} without a recorded coverage check", chk["detail"])
        forge = ("INSERT INTO contract_coverage_checks (id, approval_id, operation, subject_id, checked_on, coverage_json, coverage_hash, checked_by, checked_at) "
                 "VALUES ('ccov_x', ?, 'bill.approve', ?, '2026-10-12', '[]', ?, 'x', 'now')")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "while its granted approval executes"):  # a check cannot be back-filled
            c.db.execute(forge, (ap["id"], bill["id"], "0" * 64))
        c.db.execute("DROP TRIGGER contract_coverage_checks_insert")  # nor forged around the guard unnoticed
        c.db.execute(forge, (ap["id"], bill["id"], "0" * 64))
        detail = w.checks()[INTEGRITY_CHECK]["detail"]
        self.assertNotIn("without a recorded coverage check", detail)
        self.assertIn(f"coverage check ccov_x (approval {ap['id']}) does not match its audited record", detail)

    def test_a_withdrawn_certificate_restored_around_the_triggers_covers_nothing_and_is_detected(self):
        w = World()
        c, k = w.c, w.k
        cert = w.certificate(limit="2000000")
        cid = w.signed_commitment(requirements=GL)
        k.withdraw_certificate(cert["id"], "insurer cancellation notice (synthetic)", "contracts-admin")
        bill = w.certify(cid)
        c.db.execute("DROP TRIGGER contract_certificates_lifecycle")
        c.db.execute("UPDATE contract_certificates SET status='recorded', withdrawn_by=NULL, withdrawn_at=NULL, withdrawn_reason=NULL WHERE id=?", (cert["id"],))
        with self.assertRaisesRegex(CoverageError, "general_liability"):  # the audited withdrawal stands
            c.request_approval("bill.approve", bill["id"], actor_role="accountant")
        self.assertEqual((k.certificate(cert["id"])["valid"], k.certificate(cert["id"])["in_force"]), (False, False))
        chk = w.checks()[INTEGRITY_CHECK]
        self.assertFalse(chk["ok"])
        self.assertIn(f"certificate {cert['id']} reads recorded although its withdrawal was audited", chk["detail"])

    def test_a_superseded_agreement_revived_around_the_triggers_is_never_relied_on(self):
        w = World()
        c, k = w.c, w.k
        cid = w.draft()
        a, _ = w.register(cid)
        w.approve_agreement(a["id"])
        w.sign(a["id"])
        b, _ = w.register(cid)  # another agreement document: the signed agreement is superseded
        c.db.execute("DROP TRIGGER contract_agreements_lifecycle")
        c.db.execute("UPDATE contract_agreements SET status='superseded', superseded_at='2026-10-13T00:00:00Z', superseded_reason='x' WHERE id=?", (b["id"],))
        c.db.execute("UPDATE contract_agreements SET status='signed', superseded_at=NULL, superseded_reason=NULL WHERE id=?", (a["id"],))
        with self.assertRaisesRegex(ContractError, "superseded"):
            c.request_approval("commitment.execute", cid, actor_role="pm")
        self.assertEqual(c.commitments.get(cid)["status"], "draft")
        detail = w.checks()[INTEGRITY_CHECK]["detail"]
        self.assertIn(f"agreement {a['id']} reads signed although its supersession was audited", detail)
        self.assertIn(f"agreement {b['id']} reads superseded without an audited supersession", detail)

    def test_requirements_rewritten_or_deleted_around_the_triggers_fail_closed_and_are_detected(self):
        for mode in ("rewrite", "delete"):
            with self.subTest(mode=mode):
                w = World()
                c = w.c
                cid = w.signed_commitment(requirements=GL)  # no certificate on file: nothing may post or pay
                bill = w.certify(cid)
                if mode == "rewrite":
                    c.db.execute("DROP TRIGGER contract_requirement_sets_no_update")
                    c.db.execute("UPDATE contract_requirement_sets SET requirements_json='[]', requirements_hash=?, requirement_count=0 WHERE commitment_id=?",
                                 (hash_json([]), cid))
                else:
                    c.db.execute("DROP TRIGGER contract_requirement_sets_no_delete")
                    c.db.execute("DELETE FROM contract_requirement_sets WHERE commitment_id=?", (cid,))
                with self.assertRaisesRegex(ContractError, "audited"):
                    c.request_approval("bill.approve", bill["id"], actor_role="accountant")
                self.assertEqual(c.bills.get(bill["id"])["status"], "draft")
                chk = w.checks()[INTEGRITY_CHECK]
                self.assertFalse(chk["ok"])
                self.assertIn(f"(commitment {cid} version 1) " + ("does not match its audited record" if mode == "rewrite"
                                                                  else "is in the audit log but its record is missing"), chk["detail"])

    def test_records_deleted_around_the_triggers_are_detected_and_a_deleted_agreement_still_binds(self):
        w = World()
        c = w.c
        cert = w.certificate()
        cid = w.draft()
        a, _ = w.register(cid)
        w.approve_agreement(a["id"])  # approved, never signed
        other = w.draft("1000")
        o, _ = w.register(other)
        w.approve_agreement(o["id"])
        sig, _ = w.prepare(o["id"])
        for trigger, sql, arg in (("contract_agreements_no_delete", "DELETE FROM contract_agreements WHERE id=?", a["id"]),
                                  ("contract_certificates_no_delete", "DELETE FROM contract_certificates WHERE id=?", cert["id"]),
                                  ("contract_signatures_no_delete", "DELETE FROM contract_signatures WHERE id=?", sig["id"])):
            c.db.execute(f"DROP TRIGGER {trigger}")
            c.db.execute(sql, (arg,))
        with self.assertRaisesRegex(ContractError, "audit"):  # the agreement on record still has to be signed
            c.request_approval("commitment.execute", cid, actor_role="pm")
        self.assertEqual(c.commitments.get(cid)["status"], "draft")
        detail = w.checks()[INTEGRITY_CHECK]["detail"]
        for kind, rid in (("agreement", a["id"]), ("certificate", cert["id"]), ("signature", sig["id"])):
            self.assertIn(f"{kind} {rid} is in the audit log but its record is missing", detail)

    def test_a_deleted_workspace_policy_still_requires_agreements(self):
        w = World()
        c, k = w.c, w.k
        c.approve_and_execute(OP_REQUIRE, WORKSPACE_SUBJECT_ID)
        cid = w.draft()
        c.db.execute("DROP TRIGGER contract_workspace_policy_no_delete")
        c.db.execute("DELETE FROM contract_workspace_policy")
        self.assertTrue(k.agreements_required())  # the audit log records the switch; it has no "off"
        with self.assertRaisesRegex(ContractError, "agreements are required in this workspace"):
            c.request_approval("commitment.execute", cid, actor_role="pm")
        self.assertTrue(k.state(w.pid)["agreements_required"])
        self.assertIn("workspace policy record is missing", w.checks()[INTEGRITY_CHECK]["detail"])

    def test_ricky_previews_contract_operations_only_for_roles_that_hold_them(self):
        w = World()
        cid = w.draft()
        a, _ = w.register(cid)
        self.assertEqual(w.c.ricky.propose(OP_APPROVE, actor_role="legal", context={"agreement_id": a["id"]})["decision"], "proposed")
        self.assertEqual(w.c.ricky.propose(OP_APPROVE, actor_role="signer", context={"agreement_id": a["id"]})["decision"], "abstained")
        refused = w.c.ricky.propose(OP_SIGN, actor_role="signer", context={"agreement_id": a["id"]})  # not approved yet
        self.assertEqual(refused["decision"], "abstained")
        self.assertIn("only an approved agreement is signed", refused["reason"])


# --------------------------------------------------------------------------- #
# Nothing configured: existing flows unchanged                                 #
# --------------------------------------------------------------------------- #

class UnconfiguredTests(unittest.TestCase):
    def test_the_golden_fixture_runs_exactly_as_before(self):
        c = Cipher()
        k = c.plugin(PLUGIN_NAME)
        r = run_golden_fixture(c)
        self.assertEqual((r["bill1"]["amount_due"], r["bill2"]["amount_due"], r["executed_amount"], r["prime"]["amount_due"]),
                         ("27000.00", "18000.00", "122000.00", "54000.00"))
        self.assertEqual(r["payment"]["transfers"], 1)
        self.assertFalse(any(PLUGIN_NAME in (ap["manifest"].get("governance") or {}) for ap in c.approvals.list()))
        self.assertTrue(all(chk["ok"] for chk in k.close_checks("2026-11")))
        self.assertEqual(k.state(r["project_id"])["summary"]["agreements"], 0)
        self.assertEqual(k.integrity_problems(), [])
        self.assertTrue(r["trial_balance"]["balanced"])

    def test_a_commitment_with_no_agreement_and_no_requirements_binds_and_checks_nothing(self):
        w = World()
        c, k = w.c, w.k
        cid = w.draft()
        for op in ("commitment.execute",):
            self.assertIsNone(k.approval_policy(op, c.commitments.manifest(cid, actor_role="pm")))
        ex = c.request_approval("commitment.execute", cid, actor_role="pm")
        self.assertNotIn(PLUGIN_NAME, ex["manifest"].get("governance") or {})
        c.approve(ex["id"], approver="owner")
        c.execute(ex["id"])
        bill = w.certify(cid)
        ap = w.request_post(bill["id"])
        self.assertNotIn(PLUGIN_NAME, ap["manifest"].get("governance") or {})
        c.execute(ap["id"], actor="accountant")
        rel = w.request_release(bill["id"])
        self.assertNotIn(PLUGIN_NAME, rel["manifest"].get("governance") or {})
        c.execute(rel["id"], actor="treasury")
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM contract_coverage_checks"), 0)
        self.assertTrue(all(chk["ok"] for chk in w.checks().values()))

    def test_requirements_alone_govern_bills_and_payments_but_not_execution(self):
        w = World()
        c = w.c
        cid = w.draft()
        w.k.set_requirements(cid, GL, "contracts-admin")
        ex = c.request_approval("commitment.execute", cid, actor_role="pm")  # no agreement and none required
        facts = ex["manifest"]["governance"][PLUGIN_NAME]
        self.assertEqual((facts["agreement"], facts["agreements_required"], facts["requirements"]["version"]), (None, False, 1))
        c.approve(ex["id"], approver="owner")
        c.execute(ex["id"])
        bill = w.certify(cid)
        with self.assertRaises(CoverageError):
            c.request_approval("bill.approve", bill["id"], actor_role="accountant")
        w.certificate()
        w.post(bill["id"])

    def test_the_schema_entry_is_registered_and_the_plugin_governs(self):
        c = Cipher()
        names = {r["name"] for r in c.db.query("SELECT name FROM schema_version")}
        self.assertIn(SCHEMA_NAME, names)
        k = c.plugin(PLUGIN_NAME)
        self.assertIs(k.GOVERNOR, True)
        self.assertIn(PLUGIN_NAME, [n for n, _ in c._governors()])
        tables = {r["name"] for r in c.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'contract_%'")}
        self.assertEqual(tables, {"contract_workspace_policy", "contract_requirement_sets", "contract_agreements", "contract_signatures",
                                  "contract_certificates", "contract_coverage_checks"})


# --------------------------------------------------------------------------- #
# People registry (shared identity interface)                                  #
# --------------------------------------------------------------------------- #

class FakePeople:
    """The shared identity interface, enforcing, with a fixed roster."""

    def __init__(self, roster):
        self.roster = roster  # login -> {"active", "external", "roles"}
        self.on = True

    def enforcing(self):
        return self.on

    def is_active(self, login):
        return bool(self.roster.get((login or "").strip().casefold(), {}).get("active"))

    def is_external(self, login):
        return bool(self.roster.get((login or "").strip().casefold(), {}).get("external"))

    def holds(self, login, role, *, project_id=None):
        p = self.roster.get((login or "").strip().casefold(), {})
        return bool(p.get("active")) and (role in p.get("roles", ()) or "owner" in p.get("roles", ()))

    def person_for(self, login):
        return self.roster.get((login or "").strip().casefold())


class PeopleRegistryTests(unittest.TestCase):
    def roster(self):
        return {
            "contracts-admin": {"active": True, "roles": ("pm",)},
            "signer-sam": {"active": True, "roles": ("signer",)},
            "pm-pat": {"active": True, "roles": ("pm",)},
            "ext-accountant": {"active": True, "external": True, "roles": ("signer", "accountant")},
            "former-signer": {"active": False, "roles": ("signer",)},
        }

    def test_an_enforcing_registry_requires_an_active_internal_signer_who_holds_the_role(self):
        w = World()
        c, k = w.c, w.k
        cid = w.draft()
        a, _ = w.register(cid)
        w.approve_agreement(a["id"])
        people = FakePeople(self.roster())
        c.register_plugin("people", people)
        with self.assertRaisesRegex(ContractError, "not an active person"):
            k.set_requirements(cid, GL, "stranger")
        for signer, msg in (("former-signer", "not an active person"), ("ext-accountant", "external party"),
                            ("pm-pat", "does not hold the signer role")):
            with self.subTest(signer=signer), self.assertRaisesRegex(ContractError, msg):
                w.prepare(a["id"], signer=signer)
        w.prepare(a["id"], signer="signer-sam")
        sp = c.request_approval(OP_SIGN, a["id"], actor_role="signer", requested_by="contracts-admin")
        people.roster["signer-sam"]["active"] = False  # the signer left before granting
        with self.assertRaisesRegex(ContractError, "not an active person"):
            c.approve(sp["id"], approver="signer-sam", approver_role="signer")
        people.roster["signer-sam"]["active"] = True
        c.approve(sp["id"], approver="signer-sam", approver_role="signer")
        people.roster["signer-sam"]["roles"] = ()  # the signing authority was revoked before execution
        with self.assertRaisesRegex(ContractError, "does not hold the signer role"):
            c.execute(sp["id"], actor="signer-sam")
        self.assertEqual(c.approvals.get(sp["id"])["status"], "granted")
        people.roster["signer-sam"]["roles"] = ("signer",)
        self.assertEqual(c.execute(sp["id"], actor="signer-sam").result["status"], "signed")

    def test_a_registry_that_does_not_enforce_is_ignored(self):
        w = World()
        people = FakePeople({})
        people.on = False
        w.c.register_plugin("people", people)
        cid = w.signed_commitment(requirements=None)
        self.assertEqual(w.c.commitments.get(cid)["status"], "executed")


if __name__ == "__main__":
    unittest.main()
