"""Extended V1 acceptance: one synthetic job end to end through the modules the plan's
section-10 test (``test_vertical_v1.py``) does not walk.

A lift-station rehabilitation runs, in one accounting period, through the estimate,
procurement (equipment, requisition, bid tab, a justified award drafting the purchase
order, receiving), contracts (agreement approval and signature as separate authorities,
insurance and bond certificates checked at bill approval and release), supplier invoice
intake with the three-way match, bill posting, payment release through the outbox and the
simulator, asset capitalization and a month of depreciation, the content-rights registry,
the shadow-finance hand-off and the period close.  Ricky's SDK carries one supplier invoice
from intake to its executed match (``record_supplier_invoice``, ``compute_invoice_match``,
``request_approval``, ``execute_approved_action``) and reads documents through the rights
check (``read_document``).

Governance is configured before the job starts and enforced throughout:

* the people registry bootstraps the owner, registers every identity (an outside
  accountant, a service identity for Ricky, a subcontract administrator with no role),
  grants roles through ``people.grant_role`` approvals (the PM's on the project only) and
  then adopts an enforcing, segregated identity policy -- from then on every approval
  needs a registered requester, an approver other than the requester who holds the
  approving role, and an executor who holds the executing role;
* the payment release policy makes a release of 25,000 or more high risk and one of
  30,000 or more need a co-signature by the outside accountant, holds a destination set by
  a governed change for five days, and needs a fresh step-up by an independent releaser;
* ``contract.require_agreements`` makes every commitment executed afterwards need a signed
  agreement.

The subcontractor changes its bank details through the governed destination change (the
outside accountant verifies the call-back), so its first pay application is a high-risk
release to a new destination: held by the cooling-off window, refused to its approver,
refused without the co-signature, refused without a step-up, then released.  The pump
supplier's purchase-order invoice is a standard release.

Clock: the payment policy's injectable clock (``Plugin.now``) is moved past the cooling-off
window, as the payment-policy tests do; every other date is the module's own (UTC today for
receipts, signatures and certificates, literal October 2026 dates for documents and the
period, and a fixed receivables calendar day for the prime bill).

Everything is driven through public service and plugin APIs and approvals; nothing here
writes SQL.  Fictional parties, synthetic bank and provider records, company-owned
placeholder evidence; nothing leaves the prototype.
"""
import datetime as _dt
import json
import unittest
from decimal import Decimal

from apps.cipher.service import Cipher  # load the service (and its plugins) first
from apps.cipher.core.ids import sha256_hex, utcnow
from apps.cipher.domain.contracts import ContractError, CoverageError
from apps.cipher.domain.payment_policy import CoolingOffHold, CosignatureRequired, IndependenceRequired, StepUpRequired
from apps.cipher.domain.payments import VERIFICATION_CHANNELS
from apps.cipher.domain.people import IdentityRefused
from apps.cipher.domain.procurement import ProcurementError

D = Decimal
SHADOW = "SHADOW - not authoritative"
ENTITY = "S&A Solutions LLC (synthetic)"
PERIOD = ("P1", "2026-10-01", "2026-10-31")
OLD_DESTINATION = "ACH-SIM-EXT-SUB-0001"
NEW_DESTINATION = "ACH-SIM-EXT-SUB-0002"
PUMP_DESTINATION = "ACH-SIM-EXT-PMP-0001"
CALL_BACK = VERIFICATION_CHANNELS[0]
TERMS_DAYS = 30
COOLING_DAYS = 5
PRIME_INVOICE_DAY = _dt.date(2026, 10, 28)
# (login, display name, kind, external)
IDENTITIES = (
    ("est.kim", "Synthetic estimator", "person", False),
    ("est.jules", "Synthetic independent estimate reviewer", "person", False),
    ("pm.lee", "Synthetic project manager", "person", False),
    ("legal.lou", "Synthetic contracts reviewer", "person", False),
    ("signer.sam", "Synthetic authorized signer", "person", False),
    ("acct.ivy", "Synthetic staff accountant", "person", False),
    ("ctrl.ana", "Synthetic controller", "person", False),
    ("tre.tom", "Synthetic treasury releaser", "person", False),
    ("bank.ben", "Synthetic bank-detail maintainer", "person", False),
    ("recon.rae", "Synthetic bank reconciler", "person", False),
    ("sub.sue", "Synthetic subcontract administrator", "person", False),
    ("ext.acct", "Synthetic external accountant", "person", True),
    ("ricky", "Ricky (service identity)", "service", False),
)
# (login, role, project-scoped)
GRANTS = (
    ("est.kim", "estimator", True),
    ("est.jules", "estimator", True),
    ("pm.lee", "pm", True),
    ("legal.lou", "legal", False),
    ("signer.sam", "signer", False),
    ("acct.ivy", "accountant", False),
    ("ctrl.ana", "controller", False),
    ("tre.tom", "treasury", False),
    ("bank.ben", "bank_admin", False),
    ("recon.rae", "reconciler", False),
    ("ext.acct", "accountant", False),
    ("ricky", "accountant", False),
)
# the role each identity approves under
ROLE_OF = {"owner": "owner", **{login: role for login, role, _ in GRANTS}}
SUB_REQUIREMENTS = [
    {"kind": "general_liability", "min_limit": "1000000"},
    {"kind": "workers_comp", "min_limit": "0"},
    {"kind": "performance_bond", "min_limit": "60000"},
    {"kind": "payment_bond", "min_limit": "60000"},
]
# journals that record a bank or provider fact rather than a human decision
BANK_FACT_SOURCES = {"provider_event"}


def lines_of(journal):
    return [(ln["account_code"], ln["debit"], ln["credit"]) for ln in journal["lines"]]


def pick(record, keys):
    return {k: record[k] for k in keys}


def day(offset=0):
    """A UTC calendar date relative to today (receipts, signatures and certificates are dated
    against the modules' own clocks, which are not moved here)."""
    return (utcnow().date() + _dt.timedelta(days=offset)).isoformat()


class ExtendedJob:
    """The shared workspace and the ordered steps; ``run_through`` runs every earlier step once."""

    def __init__(self):
        self.done: set[int] = set()
        self.failed: dict[int, str] = {}
        c = self.c = Cipher()
        self.people = c.plugin("people")
        self.policy = c.plugin("payment_policy")
        self.contracts = c.plugin("contract")
        self.proc = c.plugin("procurement")
        self.intake = c.plugin("ap_intake")
        self.assets = c.plugin("asset")
        self.rights = c.plugin("rights")
        self.handoff = c.plugin("handoff")
        self.bank = c.plugin("banking")
        self.close = c.plugin("close")
        self.sdk = c.sdk
        self.assertions = 0
        self.docs = 0
        c.receivables.today = lambda: PRIME_INVOICE_DAY

    def run_through(self, n, tc):
        for k in range(1, n + 1):
            if k in self.done:
                continue
            if k in self.failed:
                raise unittest.SkipTest(f"prerequisite step {k} failed: {self.failed[k]}")
            try:
                getattr(self, f"step{k}")(tc)
            except unittest.SkipTest:
                raise
            except BaseException as exc:
                self.failed[k] = f"{type(exc).__name__}: {exc}"
                raise
            self.done.add(k)

    # ---- helpers --------------------------------------------------------- #

    def evidence(self, kind, title, *, actor="pm.lee"):
        self.docs += 1
        doc = self.c.evidence.register_document(project_id=self.pid, kind=kind, title=f"{title} (synthetic)", actor=actor)
        rev = self.c.evidence.add_revision(document_id=doc["id"], content=f"EXT synthetic {kind} {self.docs}: {title}".encode(), actor=actor)
        return doc, rev

    def run(self, operation, subject_id, *, requester, approver, executor, actor_role, approver_role=None, period_id=None):
        """Request, grant and execute with three named identities (the policy segregates them); the
        approver approves under the role they were granted."""
        ap = self.c.request_approval(operation, subject_id, actor_role=actor_role, requested_by=requester)
        self.c.approve(ap["id"], approver=approver, approver_role=approver_role or ROLE_OF[approver])
        return ap, self.c.execute(ap["id"], actor=executor, period_id=period_id).result

    def grant(self, login, role, *, project_id=None):
        req = self.people.request_grant(login, role, reason="EXT staffing for the lift station job", actor="owner", project_id=project_id)
        return self.run("people.grant_role", req["id"], requester="owner", approver="owner", executor="owner", actor_role="owner")[1]

    def step_up(self, login):
        self.assertions += 1
        return self.policy.record_step_up(login, "webauthn", sha256_hex(f"EXT synthetic assertion {self.assertions}"), "sign-in-service")

    def sign_and_execute(self, tc, cid, *, label):
        """Contracts: the subcontract administrator registers the agreement, legal approves the exact
        revision, the authorized signer signs it, and only then does the commitment execute."""
        c, k = self.c, self.contracts
        _, agreement_rev = self.evidence("agreement", f"{label} agreement", actor="sub.sue")
        a = k.register_agreement(cid, agreement_rev["content_hash"], "sub.sue")
        tc.assertEqual(a["status"], "registered")
        with tc.assertRaises(ContractError):  # agreements are required: nothing executes before the signature
            c.request_approval("commitment.execute", cid, actor_role="pm", requested_by="pm.lee")
        ap, res = self.run("contract.approve_agreement", a["id"], requester="sub.sue", approver="legal.lou", executor="legal.lou", actor_role="legal")
        tc.assertEqual((res["status"], k.agreement(a["id"])["status"]), ("approved", "approved"))
        tc.assertEqual(ap["manifest"]["bindings"]["agreement_revision_hash"], agreement_rev["content_hash"])
        _, signed_rev = self.evidence("signed_agreement", f"{label} signed agreement", actor="sub.sue")
        k.prepare_signature(a["id"], signed_rev["content_hash"], "signer.sam", day(), "sub.sue")
        sign = c.request_approval("contract.sign", a["id"], actor_role="signer", requested_by="sub.sue")
        with tc.assertRaises(ContractError):  # a signature is personal: not even the owner grants it for the signer
            c.approve(sign["id"], approver="owner")
        c.approve(sign["id"], approver="signer.sam", approver_role="signer")
        res = c.execute(sign["id"], actor="signer.sam").result
        tc.assertEqual((res["status"], res["signer"], k.agreement(a["id"])["status"]), ("signed", "signer.sam", "signed"))
        ap, res = self.run("commitment.execute", cid, requester="pm.lee", approver="owner", executor="pm.lee", actor_role="pm")
        tc.assertEqual(res["status"], "executed")
        facts = ap["manifest"]["governance"]["contract"]
        tc.assertEqual((facts["agreements_required"], facts["agreement"]["status"], facts["agreement"]["signer"]), (True, "signed", "signer.sam"))
        return a

    def receive_and_match(self, tc, *, supplier_id, number, invoice_date, amount, commitment_id, lines):
        """Direct intake (an AP clerk): receive the invoice with its PDF and compute the match."""
        _, pdf = self.evidence("supplier_invoice", f"Supplier invoice {number}", actor="acct.ivy")
        inv = self.intake.receive_invoice(supplier_id, number, invoice_date, amount, pdf["content_hash"], "acct.ivy",
                                          project_id=self.pid, commitment_id=commitment_id, lines=lines)
        res = self.intake.match(inv["id"], "acct.ivy")
        return inv, res

    def release(self, bill_id):
        return self.c.request_approval("payment.release", bill_id, actor_role="treasury", requested_by="acct.ivy")

    # ---- step 1: governance ------------------------------------------------------------ #

    def step1(self, tc):
        """People registry, role grants, the payment release policy, required agreements, then an
        enforcing segregated identity policy."""
        c, p = self.c, self.people
        self.customer = c.add_party(kind="customer", name="Synthetic Water Authority (EXT)")
        sub = c.add_party(kind="supplier", name="Synthetic Wet Well Rehabilitation Subcontractor (EXT)", destination=OLD_DESTINATION)
        self.sub = c.verify_destination(sub["id"], destination=OLD_DESTINATION, verified_by="bank.ben")
        vendor_a = c.add_party(kind="supplier", name="Synthetic Pump Vendor A (EXT)", destination="ACH-SIM-EXT-PVA-0001")
        self.vendor_a = c.verify_destination(vendor_a["id"], destination="ACH-SIM-EXT-PVA-0001", verified_by="bank.ben")
        pumps = c.add_party(kind="supplier", name="Synthetic Pump Vendor B (EXT)", destination=PUMP_DESTINATION)
        self.pumps = c.verify_destination(pumps["id"], destination=PUMP_DESTINATION, verified_by="bank.ben")
        self.project = c.create_project(name="EXT synthetic lift station rehabilitation", entity=ENTITY, budget="150000", customer_id=self.customer["id"])
        self.pid = self.project["id"]
        c.open_period(PERIOD[0], "October 2026", PERIOD[1], PERIOD[2])
        tc.assertEqual(self.intake.set_terms(self.sub["id"], TERMS_DAYS, "ctrl.ana")["days"], TERMS_DAYS)
        tc.assertEqual(self.intake.set_terms(self.pumps["id"], TERMS_DAYS, "ctrl.ana")["days"], TERMS_DAYS)
        c.receivables.set_customer_terms(self.customer["id"], TERMS_DAYS, actor="ctrl.ana")

        # identities: the owner is bootstrapped once; everyone else is registered (registering grants nothing)
        boot = p.bootstrap_owner("owner", "Synthetic owner")
        tc.assertEqual((boot["grant"]["role"], boot["grant"]["scope"], boot["grant"]["origin"]), ("owner", "entity", "bootstrap"))
        for login, name, kind, external in IDENTITIES:
            p.register_person(login, name, actor="owner", kind=kind, external=external)
        tc.assertEqual(p.authorities("sub.sue"), [])
        for login in ("pm.lee", "est.kim", "est.jules"):
            p.add_membership(login, self.pid, actor="owner")
        with tc.assertRaises(IdentityRefused):  # no self-granting, even before enforcement
            p.request_grant("owner", "controller", reason="EXT self-grant attempt", actor="owner")
        for login, role, scoped in GRANTS:
            self.grant(login, role, project_id=self.pid if scoped else None)
        tc.assertTrue(p.holds("pm.lee", "pm", project_id=self.pid))
        tc.assertFalse(p.holds("pm.lee", "pm"))  # project-scoped: not at entity scope
        tc.assertTrue(p.holds("ricky", "accountant") and p.is_external("ext.acct"))

        # the payment release policy (owner on both sides; the first version needs no co-signature)
        draft = self.policy.draft_policy(high_risk_amount="25000", cosign_amount="30000", step_up_max_age_seconds=600,
                                         new_destination_cooling_days=COOLING_DAYS, first_payment_to_destination_is_high_risk=False,
                                         independent_parties=["ext.acct"], reason="EXT owner and external accountant release control", actor="owner")
        _, res = self.run("payment_policy.update", draft["id"], requester="owner", approver="owner", executor="owner", actor_role="owner")
        tc.assertEqual(res["payment_policy_version"], 1)
        tc.assertTrue(self.policy.verify_chain()["ok"])

        # every commitment executed from now on needs a signed agreement
        _, res = self.run("contract.require_agreements", "workspace", requester="owner", approver="owner", executor="owner", actor_role="owner")
        tc.assertTrue(res["agreements_required"])

        # the identity policy: enforcing and segregated (no solo-owner exception: staff are on the job)
        draft = p.prepare_policy(enforce=True, segregate=True, reason="EXT staffed job: identities enforced and segregated", actor="owner")
        self.run("people.set_policy", draft["id"], requester="owner", approver="owner", executor="owner", actor_role="owner")
        tc.assertTrue(p.enforcing())
        tc.assertEqual(pick(p.current_policy(), ("version", "enforce", "segregate", "solo_owner_self_approval", "intact")),
                       {"version": 1, "enforce": True, "segregate": True, "solo_owner_self_approval": False, "intact": True})

    # ---- step 2: estimate ---------------------------------------------------------- #

    def step2(self, tc):
        """The estimator prices the drawing; another actual project estimator approves it; enforcement refuses an unknown
        requester, a requester approving their own request and a service identity approving."""
        c = self.c
        _, self.drawing_rev = self.evidence("drawing", "Drawing L-1 lift station wet well and bypass", actor="est.kim")
        est = c.estimates.create(self.pid, self.drawing_rev["id"], [
            {"description": "Wet well rehabilitation and liner", "quantity": "1", "unit": "LS", "unit_price": "48000"},
            {"description": "Bypass pumping during rehabilitation", "quantity": "1", "unit": "LS", "unit_price": "12000"},
        ], "est.kim", price_book_ref="PB-2026.1")
        tc.assertEqual(est["total"], "60000.00")
        with tc.assertRaises(IdentityRefused):  # an unregistered requester
            c.request_approval("estimate.approve", est["id"], actor_role="estimator", requested_by="someone")
        ap = c.request_approval("estimate.approve", est["id"], actor_role="estimator", requested_by="est.kim")
        tc.assertEqual(ap["manifest"]["governance"]["people"]["policy_version"], 1)
        with tc.assertRaises(IdentityRefused):  # segregation: the requester cannot approve
            c.approve(ap["id"], approver="est.kim", approver_role="estimator")
        with tc.assertRaises(IdentityRefused):  # a service identity never approves
            c.approve(ap["id"], approver="ricky", approver_role="owner")
        with tc.assertRaises(IdentityRefused):  # the approver must hold the approving role
            c.approve(ap["id"], approver="acct.ivy", approver_role="estimator")
        with tc.assertRaises(IdentityRefused):  # owner wildcard cannot replace the actual project estimator duty
            c.approve(ap["id"], approver="owner")
        c.approve(ap["id"], approver="est.jules", approver_role="estimator")
        tc.assertEqual(c.execute(ap["id"], actor="est.kim").result["status"], "approved")
        self.estimate = c.estimates.get(est["id"])

    # ---- step 3: procurement ---------------------------------------------------------- #

    def step3(self, tc):
        """Equipment, requisition, bid tab, a justified award that drafts the purchase order, the
        PO executed under a signed agreement, and both pumps received in good condition."""
        c, pr = self.c, self.proc
        e1 = pr.add_equipment(self.pid, "P-201", "Submersible duty pump, 15 HP", "XX 43 21", "2027-02-01", long_lead=True, actor="pm.lee")
        e2 = pr.add_equipment(self.pid, "P-202", "Submersible standby pump, 15 HP", "XX 43 21", "2027-02-01", long_lead=True, actor="pm.lee")
        self.e1, self.e2 = e1, e2
        req = pr.create_requisition(self.pid, "Duty and standby submersible pumps", [e1["id"], e2["id"]], actor="pm.lee")
        qa = pr.add_quote(req["id"], self.vendor_a["id"], "18400.00", 30, "2099-12-31", True, actor="pm.lee")
        qb = pr.add_quote(req["id"], self.pumps["id"], "19000.00", 12, "2099-12-31", True, actor="pm.lee")
        tab = pr.bid_tab(req["id"])
        tc.assertEqual((tab["count"], tab["lowest_compliant_amount"], tab["lowest_compliant_quote_ids"]), (2, "18400.00", [qa["id"]]))
        with tc.assertRaises(ProcurementError):  # not the lowest compliant quote: a justification is required
            pr.select_quote(req["id"], qb["id"], "", actor="pm.lee")
        justification = "the low bid's 30-week lead time misses the 2027-02-01 required-on-site date; 12 weeks meets it"
        pr.select_quote(req["id"], qb["id"], justification, actor="pm.lee")
        ap, res = self.run("procurement.award", req["id"], requester="pm.lee", approver="owner", executor="pm.lee", actor_role="pm")
        tc.assertEqual((ap["manifest"]["bindings"]["lowest_compliant"], ap["manifest"]["bindings"]["justification"]), (False, justification))
        tc.assertEqual((res["status"], res["commitment_status"], res["amount"], res["sov"]), ("awarded", "draft", "19000.00", ["9500.00", "9500.00"]))
        self.po = res["commitment"]
        tc.assertEqual(c.commitments.get(self.po)["status"], "draft")  # an award drafts the PO; it never executes it
        self.po_agreement = self.sign_and_execute(tc, self.po, label="Pump purchase order")
        tc.assertEqual((c.commitments.get(self.po)["status"], c.commitments.get(self.po)["executed_amount"]), ("executed", "19000.00"))

        # receiving: both pumps arrive in good condition (dated today: a receipt is never in the future)
        self.receipts = [pr.receive(eq["id"], day(), "ok", sha256_hex(f"EXT delivery ticket {eq['tag']}"), actor="pm.lee") for eq in (e1, e2)]
        tc.assertEqual([r["condition"] for r in self.receipts], ["ok", "ok"])
        tc.assertEqual({eq["tag"]: ([r["id"] for r in eq["receipts"]], eq["award_status"], eq["commitment_status"]) for eq in pr.equipment_list(self.pid)},
                       {"P-201": ([self.receipts[0]["id"]], "awarded", "executed"), "P-202": ([self.receipts[1]["id"]], "awarded", "executed")})

    # ---- step 4: subcontract under contracts -------------------------------------------- #

    def step4(self, tc):
        """The subcontract from the estimate, with insurance and bond requirements, executed only
        after legal approved the agreement and the signer signed it; certificates are recorded."""
        c, k = self.c, self.contracts
        cmt = c.commitments.create(project_id=self.pid, supplier_id=self.sub["id"], title="EXT subcontract - wet well rehabilitation and bypass",
                                   sov_lines=[{"description": "Wet well rehabilitation and liner", "amount": "48000", "cost_code": "XX 10 00"},
                                              {"description": "Bypass pumping", "amount": "12000", "cost_code": "XX 20 00"}],
                                   retainage_rate="0.10", estimate_id=self.estimate["id"], actor="pm.lee")
        self.cid = cmt["id"]
        k.set_requirements(self.cid, SUB_REQUIREMENTS, "sub.sue")
        self.sub_agreement = self.sign_and_execute(tc, self.cid, label="Wet well subcontract")
        cmt = c.commitments.get(self.cid)
        tc.assertEqual((cmt["status"], cmt["executed_amount"], [s["amount"] for s in cmt["sov"]]), ("executed", "60000.00", ["48000.00", "12000.00"]))
        self.line1, self.line2 = cmt["sov"][0]["id"], cmt["sov"][1]["id"]
        # three of the four certificates now; the payment bond arrives later (step 7)
        self.certificates = {}
        for kind, carrier, limit in (("general_liability", "Synthetic Mutual Insurance Co", "2000000"), ("workers_comp", "Synthetic Mutual Insurance Co", "1000000"),
                                     ("performance_bond", "Synthetic Surety Co", "60000")):
            _, rev = self.evidence("insurance_certificate", f"Subcontractor {kind} certificate", actor="sub.sue")
            self.certificates[kind] = k.record_certificate(self.sub["id"], kind, carrier, f"POL-SIM-EXT-{kind[:3].upper()}", limit, day(-30), day(335),
                                                           rev["content_hash"], "sub.sue")
        cover = {row["kind"]: row["in_force"] for row in k.coverage(self.cid)}
        tc.assertEqual(cover, {"general_liability": True, "workers_comp": True, "performance_bond": True, "payment_bond": False})

    # ---- step 5: governed destination change -------------------------------------------------- #

    def step5(self, tc):
        """The subcontractor's new bank details: requested by AP, verified by the outside accountant's
        call-back, approved by the owner and executed by the bank-detail maintainer."""
        c = self.c
        _, rev = self.evidence("destination_verification", "Subcontractor bank change call-back record", actor="bank.ben")
        change_id = c.payments.governed_destination_change(self.sub["id"], NEW_DESTINATION, "acct.ivy", "ext.acct", CALL_BACK, rev["content_hash"], "bank.ben")
        _, res = self.run("party.verify_destination", change_id, requester="bank.ben", approver="owner", executor="bank.ben", actor_role="bank_admin")
        self.change = c.payments.destination_change(change_id)
        tc.assertEqual((self.change["status"], self.change["new_destination_version"]), ("executed", c.party(self.sub["id"])["destination_version"]))
        tc.assertEqual(c.party(self.sub["id"])["destination"], NEW_DESTINATION)

    # ---- step 6: pump PO invoice through Ricky's SDK (three-way), bill and standard release ------- #

    def step6(self, tc):
        """The PO bill is certified; Ricky records the supplier's invoice, computes the three-way match
        (receipts in good condition, PO lines, the certified bill) and requests the match approval;
        the controller grants it and Ricky executes it; the bill posts and the release is standard."""
        c, sdk = self.c, self.sdk
        po_lines = c.commitments.get(self.po)["sov"]
        bill = c.bills.certify(commitment_id=self.po, period_id="P1",
                               installed=[{"sov_line_id": ln["id"], "cumulative_installed": "9500"} for ln in po_lines], actor="pm.lee")
        tc.assertEqual((bill["amount_due"], bill["retainage_this_period"]), ("19000.00", "0.00"))
        _, pdf = self.evidence("supplier_invoice", "Pump vendor invoice PV-7781", actor="acct.ivy")
        args = {"project_id": self.pid, "supplier_id": self.pumps["id"], "commitment_id": self.po, "invoice_number": "PV-7781",
                "invoice_date": "2026-10-14", "amount": "19000.00", "evidence_hash": pdf["content_hash"],
                "lines": [{"description": f"{eq['tag']} supplied", "amount": "9500.00", "equipment_id": eq["id"]} for eq in (self.e1, self.e2)]}
        refused = sdk.invoke("record_supplier_invoice", args, actor="ricky", actor_role="controller")
        tc.assertEqual(refused["status"], "refused")  # Ricky holds accountant, never the role a request names
        rec = sdk.invoke("record_supplier_invoice", args, actor="ricky", actor_role="accountant")
        tc.assertEqual(rec["status"], "ok", rec.get("error"))
        inv_id = rec["result"]["invoice_id"]
        tc.assertEqual((rec["result"]["status"], rec["result"]["due_date"], rec["result"]["terms_days"]), ("received", "2026-11-13", TERMS_DAYS))
        match = sdk.invoke("compute_invoice_match", {"invoice_id": inv_id}, actor="ricky", actor_role="accountant")
        tc.assertEqual(match["status"], "ok", match.get("error"))
        m = match["result"]
        tc.assertEqual((m["basis"], m["status"], m["exceptions"], m["matched_amount"], m["bill"]["id"]), ("purchase_order", "matched", [], "19000.00", bill["id"]))
        tc.assertEqual(sorted(r["receipt_id"] for r in m["receipts"]), sorted(r["id"] for r in self.receipts))
        req = sdk.invoke("request_approval", {"operation": "ap_intake.match_invoice", "subject_id": inv_id}, actor="ricky", actor_role="accountant")
        tc.assertEqual(req["status"], "ok", req.get("error"))
        approval_id = req["result"]["approval_id"]
        tc.assertEqual((req["result"]["status"], req["result"]["granted"]), ("pending", False))
        with tc.assertRaises(IdentityRefused):  # Ricky can never grant what it requested
            c.approve(approval_id, approver="ricky", approver_role="accountant")
        c.approve(approval_id, approver="ctrl.ana", approver_role="controller")
        done = sdk.invoke("execute_approved_action", {"approval_id": approval_id}, actor="ricky", actor_role="accountant")
        tc.assertEqual(done["status"], "ok", done.get("error"))
        tc.assertEqual(pick(done["result"]["command_result"], ("status", "basis", "bill")), {"status": "matched", "basis": "purchase_order", "bill": bill["id"]})
        tc.assertEqual(c.bills.get(bill["id"])["supplier_invoice_number"], "PV-7781")
        self.po_invoice = self.intake.invoice(inv_id)

        ap = c.request_approval("bill.approve", bill["id"], actor_role="accountant", requested_by="acct.ivy")
        c.approve(ap["id"], approver="ctrl.ana", approver_role="controller")
        tc.assertEqual(c.bills.get(bill["id"])["status"], "approved")
        res = c.post_bill(bill["id"], actor="acct.ivy", actor_role="accountant").result
        tc.assertEqual(lines_of(c.ledger.journal(res["journal_id"])), [("5000", "19000.00", "0.00"), ("2000", "0.00", "19000.00")])
        tc.assertNotIn("contract", ap["manifest"].get("governance") or {})  # the PO carries no insurance requirements
        self.po_bill = c.bills.get(bill["id"])

        ap = self.release(bill["id"])
        facts = ap["manifest"]["governance"]["payment_policy"]
        tc.assertEqual((facts["classification"], facts["reasons"], facts["cosign_required"]), ("standard", [], False))
        c.approve(ap["id"], approver="owner")
        with tc.assertRaises(IdentityRefused):  # the executor must hold the executing role: the accountant is not treasury
            c.execute(ap["id"], actor="acct.ivy")
        tc.assertEqual((c.approvals.get(ap["id"])["status"], self.policy.clearances()), ("granted", []))  # the refusal rolled the clearance back
        res = c.execute(ap["id"], actor="tre.tom").result
        tc.assertEqual((res["status"], res["amount"]), ("queued", "19000.00"))
        tc.assertEqual([(x["status"], x["provider_ref"]) for x in c.dispatch_payments()], [("accepted", "sim_000001")])
        intent = c.payments.get(res["intent"])
        tc.assertTrue(c.payments.ingest_event(c.provider.settle(intent["logical_op_id"]), actor="webhook")["applied"])
        tc.assertEqual(c.bills.get(bill["id"])["status"], "paid")
        self.po_intent = intent["id"]

    # ---- step 7: subcontract pay application, coverage, high-risk release to the new destination ---- #

    def step7(self, tc):
        """Pay application 1 (40,000 gross, 4,000 retainage, 36,000 due) is invoiced and matched; bill
        approval is refused until the payment bond is on file; the release is high risk (amount and
        new destination) and needs the cooling-off window, an independent releaser, the outside
        accountant's co-signature and a fresh step-up."""
        c, k = self.c, self.contracts
        bill = c.bills.certify(commitment_id=self.cid, period_id="P1", installed=[{"sov_line_id": self.line1, "cumulative_installed": "30000"},
                                                                              {"sov_line_id": self.line2, "cumulative_installed": "10000"}], actor="pm.lee")
        tc.assertEqual(pick(bill, ("cumulative_gross", "cumulative_retainage", "amount_due")), {"cumulative_gross": "40000.00", "cumulative_retainage": "4000.00", "amount_due": "36000.00"})
        inv, res = self.receive_and_match(tc, supplier_id=self.sub["id"], number="WW-2026-001", invoice_date="2026-10-20", amount="36000.00",
                                          commitment_id=self.cid, lines=[{"description": "Pay application 1 net of 10% retainage", "amount": "36000.00",
                                                                          "sov_line_id": self.line1}])
        tc.assertEqual((res["basis"], res["status"], res["bill"]["id"]), ("progress", "matched", bill["id"]))
        _, done = self.run("ap_intake.match_invoice", inv["id"], requester="acct.ivy", approver="ctrl.ana", executor="acct.ivy",
                           actor_role="accountant")
        tc.assertEqual(done["bill"], bill["id"])
        self.sub_invoice = self.intake.invoice(inv["id"])

        # coverage: the payment bond is required and missing, so the bill cannot be approved yet
        with tc.assertRaises(CoverageError):
            c.request_approval("bill.approve", bill["id"], actor_role="accountant", requested_by="acct.ivy")
        _, rev = self.evidence("insurance_certificate", "Subcontractor payment bond", actor="sub.sue")
        self.certificates["payment_bond"] = k.record_certificate(self.sub["id"], "payment_bond", "Synthetic Surety Co", "BOND-SIM-EXT-PAY", "60000",
                                                                 day(-30), day(335), rev["content_hash"], "sub.sue")
        ap = c.request_approval("bill.approve", bill["id"], actor_role="accountant", requested_by="acct.ivy")
        c.approve(ap["id"], approver="ctrl.ana", approver_role="controller")
        tc.assertEqual(c.bills.get(bill["id"])["status"], "approved")
        res = c.post_bill(bill["id"], actor="acct.ivy", actor_role="accountant").result
        bound = ap["manifest"]["governance"]["contract"]
        tc.assertEqual({cov["kind"]: [x["id"] for x in cov["certificates"]] for cov in bound["coverage"]},
                       {kind: [cert["id"]] for kind, cert in self.certificates.items()})
        verified = [json.loads(e["payload_json"]) for e in c.audit.entries(entity_type="approval", entity_id=ap["id"]) if e["action"] == "contract.coverage_verified"]
        tc.assertEqual([sorted(v["certificates"]) for v in verified], [sorted(cert["id"] for cert in self.certificates.values())])
        tc.assertEqual(lines_of(c.ledger.journal(res["journal_id"])), [("5000", "40000.00", "0.00"), ("2000", "0.00", "36000.00"), ("2050", "0.00", "4000.00")])
        self.sub_bill = c.bills.get(bill["id"])

        # the release: high risk because of its amount and the new destination, and co-signed
        ap = self.release(bill["id"])
        facts = ap["manifest"]["governance"]["payment_policy"]
        tc.assertEqual((facts["classification"], facts["reasons"], facts["cosign_required"], facts["cosign_reasons"]),
                       ("high_risk", ["amount_at_or_over_high_risk_amount", "new_destination_from_change"], True, ["amount_at_or_over_cosign_amount"]))
        tc.assertEqual(facts["destination"]["change"]["change_id"], self.change["id"])
        with tc.assertRaises(IndependenceRequired):  # the requester cannot approve a high-risk release
            c.approve(ap["id"], approver="acct.ivy", approver_role="treasury")
        c.approve(ap["id"], approver="owner")
        with tc.assertRaises(CoolingOffHold):  # five days after the destination changed, whoever releases
            c.execute(ap["id"], actor="tre.tom")
        tc.assertEqual(c.approvals.get(ap["id"])["status"], "granted")
        base = utcnow()
        self.policy.now = lambda: base + _dt.timedelta(days=COOLING_DAYS, minutes=1)
        with tc.assertRaises(IndependenceRequired):  # the approver cannot release what they approved
            c.execute(ap["id"], actor="owner")
        with tc.assertRaises(CosignatureRequired):
            c.execute(ap["id"], actor="tre.tom")
        sig = self.policy.cosign(ap["id"], "ext.acct", "ext.acct")
        with tc.assertRaises(StepUpRequired):
            c.execute(ap["id"], actor="tre.tom")
        step = self.step_up("tre.tom")
        res = c.execute(ap["id"], actor="tre.tom").result
        tc.assertEqual((res["status"], res["amount"]), ("queued", "36000.00"))
        clearance = [k_ for k_ in self.policy.clearances() if k_["approval_id"] == ap["id"]][0]
        tc.assertEqual(pick(clearance, ("classification", "requested_by", "approver", "releaser", "step_up_id", "cosignature_id")),
                       {"classification": "high_risk", "requested_by": "acct.ivy", "approver": "owner", "releaser": "tre.tom",
                        "step_up_id": step["id"], "cosignature_id": sig["id"]})
        out = c.dispatch_payments()
        tc.assertEqual([(x["status"], x["provider_ref"]) for x in out], [("accepted", "sim_000002")])
        intent = c.payments.get(res["intent"])
        tc.assertEqual((intent["destination_version"], intent["amount"]), (self.change["new_destination_version"], "36000.00"))
        tc.assertTrue(c.payments.ingest_event(c.provider.settle(intent["logical_op_id"]), actor="webhook")["applied"])
        tc.assertEqual(c.bills.get(bill["id"])["status"], "paid")
        self.sub_intent = intent["id"]
        self.sub_release = ap

    # ---- step 8: asset capitalization and a month of depreciation --------------------------------- #

    def step8(self, tc):
        """A job asset (3,600 over 36 months) is capitalized and charged its first month (100.00)."""
        c, a = self.c, self.assets
        asset = a.register_asset(self.pid, "Portable gas monitor and confined-space entry kit (EXT)", "3600", "2026-10-05", 36, actor="acct.ivy")
        tc.assertEqual(asset["status"], "registered")
        _, res = self.run("asset.capitalise", asset["id"], requester="acct.ivy", approver="ctrl.ana", executor="acct.ivy", actor_role="accountant",
                          period_id="P1")
        tc.assertEqual(lines_of(c.ledger.journal(res["journal_id"])), [("1500", "3600.00", "0.00"), ("1000", "0.00", "3600.00")])
        run = a.schedule_run(asset["id"], "P1", "acct.ivy")
        tc.assertEqual((run["status"], run["amount"], run["charge_month"], run["sequence"]), ("draft", "100.00", "2026-10", 1))
        _, res = self.run("asset.post_depreciation", run["id"], requester="acct.ivy", approver="ctrl.ana", executor="acct.ivy", actor_role="accountant",
                          period_id="P1")
        tc.assertEqual(lines_of(c.ledger.journal(res["journal_id"])), [("5200", "100.00", "0.00"), ("1590", "0.00", "100.00")])
        self.asset = a.get_asset(asset["id"])
        tc.assertEqual((self.asset["status"], self.asset["accumulated_depreciation"], self.asset["net_book_value"]), ("active", "100.00", "3500.00"))

    # ---- step 9: content rights and Ricky's document retrieval ------------------------------------ #

    def step9(self, tc):
        """A licensed handbook may be used on the project but not retrieved by AI; Ricky's
        read_document is refused for it and allowed for the company-owned drawing."""
        c, r, sdk = self.c, self.rights, self.sdk
        handbook, _ = self.evidence("reference", "Pump station design handbook, 4th edition (licensed)", actor="pm.lee")
        lic = r.register_license("Synthetic Engineering Press", "Pump Station Design Handbook", "4th edition", ENTITY,
                                 ["internal_reference", "project_use"], expires_on="2099-12-31", actor="owner")
        r.tag_document(handbook["id"], lic["id"], actor="owner")
        tc.assertTrue(r.check_use(handbook["id"], "project_use")["allowed"])
        tc.assertFalse(r.check_use(handbook["id"], "ai_retrieval")["allowed"])
        drawing_doc = self.drawing_rev["document_id"]
        tc.assertEqual(r.filter_retrievable([handbook["id"], drawing_doc], "ai_retrieval", project_id=self.pid)["allowed"], [drawing_doc])
        refused = sdk.invoke("read_document", {"document_id": handbook["id"]}, actor="ricky", actor_role="accountant")
        tc.assertEqual(refused["status"], "refused")
        ok = sdk.invoke("read_document", {"document_id": drawing_doc}, actor="ricky", actor_role="accountant")
        tc.assertEqual(ok["status"], "ok", ok.get("error"))
        tc.assertEqual((ok["result"]["rights"]["allowed"], ok["result"]["current_revision"]["content_hash"]), (True, self.drawing_rev["content_hash"]))
        brief = sdk.invoke("read_brief", {"project_id": self.pid}, actor="pm.lee", actor_role="pm")
        tc.assertEqual(brief["status"], "ok", brief.get("error"))
        self.handbook = handbook

    # ---- step 10: prime billing ---------------------------------------------------------------- #

    def step10(self, tc):
        """The owner agency is billed 70,000 certified at 10% retainage (SHADOW recognition policy)."""
        c = self.c
        prime = c.receivables.certify(project_id=self.pid, period_id="P1", certified_cumulative="70000", retainage_rate="0.10", actor="pm.lee",
                                      invoice_date=PRIME_INVOICE_DAY.isoformat())
        tc.assertEqual(pick(prime, ("amount_due", "retainage_this_period", "revenue_this_period")),
                       {"amount_due": "63000.00", "retainage_this_period": "7000.00", "revenue_this_period": "70000.00"})
        _, res = self.run("prime_bill.approve", prime["id"], requester="acct.ivy", approver="ctrl.ana", executor="acct.ivy", actor_role="accountant")
        tc.assertEqual(lines_of(c.ledger.journal(res["journal_id"])), [("1100", "63000.00", "0.00"), ("1150", "7000.00", "0.00"), ("4000", "0.00", "70000.00")])
        tc.assertEqual(pick(c.receivables.get(prime["id"]), ("invoice_date", "due_date", "payment_terms_days")),
                       {"invoice_date": "2026-10-28", "due_date": "2026-11-27", "payment_terms_days": TERMS_DAYS})
        self.prime = c.receivables.get(prime["id"])

    # ---- step 11: bank reconciliation, hand-off and period close ---------------------------------- #

    def step11(self, tc):
        """The bank statement is matched and its reconciliation locked; the hand-off package is
        prepared, receipted by the outside accountant and acknowledged; the period closes through
        its checklist, every module's close checks passing."""
        c, bank = self.c, self.bank
        lines = [
            {"date": "2026-10-16", "amount": "-19000.00", "description": "ACH disbursement (simulator)", "reference": "sim_000001"},
            {"date": "2026-10-27", "amount": "-36000.00", "description": "ACH disbursement (simulator)", "reference": "sim_000002"},
            {"date": "2026-10-06", "amount": "-3600.00", "description": "Card purchase: gas monitor kit (simulated)", "reference": self.asset["id"]},
        ]
        st = bank.import_statement(statement_ref="SIM-BANK-EXT-2026-10", period_id="P1", opening_balance="0.00", closing_balance="-58600.00",
                                   lines=lines, actor="recon.rae")
        m = bank.auto_match(st["id"], actor="recon.rae")
        tc.assertEqual((len(m["matched"]), m["ambiguous"], m["unmatched"]), (3, [], []))
        _, res = self.run("banking.lock_reconciliation", st["id"], requester="recon.rae", approver="ctrl.ana", executor="recon.rae",
                          actor_role="reconciler", period_id="P1")
        tc.assertEqual((res["status"], res["difference"]), ("locked", "0.00"))

        # the shadow-finance hand-off: prepared, received by the outside accountant, acknowledged
        h = self.handoff.prepare_handoff("P1", "acct.ivy")
        tc.assertTrue(self.handoff.verify(h["id"])["ok"])
        self.handoff.record_receipt_details(h["id"], "RCPT-SIM-EXT-2026-10", "Synthetic external accountant", "ext.acct")
        _, res = self.run("handoff.acknowledge", h["id"], requester="acct.ivy", approver="ctrl.ana", executor="ext.acct", actor_role="accountant")
        tc.assertEqual(pick(res, ("status", "receipt_ref", "package_hash", "omission_count")),
                       {"status": "acknowledged", "receipt_ref": "RCPT-SIM-EXT-2026-10", "package_hash": h["package_hash"], "omission_count": 0})
        tc.assertEqual(pick(self.handoff.omissions(h["id"]), ("count", "ok")), {"count": 0, "ok": True})
        self.handoff_id = h["id"]

        report = self.close.checklist_report("P1")
        tc.assertTrue(report["all_ok"], report["failing"])
        checks = {ch["check"]: ch for ch in report["checks"]}
        for name in ("trial_balance_balanced", "ap_reconciled", "ar_reconciled", "no_draft_supplier_bills", "no_draft_prime_bills",
                     "no_unresolved_payments", "bank reconciliation"):
            tc.assertTrue(checks[name]["ok"], name)
        tc.assertTrue({ch["source"] for ch in report["checks"]} >= {"people", "payment_policy", "contract", "handoff", "ap_intake", "rights", "banking"})
        _, res = self.run("close.close_period", "P1", requester="acct.ivy", approver="owner", executor="ctrl.ana", actor_role="controller", period_id="P1")
        tc.assertEqual(res["status"], "closed")
        tc.assertEqual(c.ledger.period("P1")["status"], "closed")
        run = self.close.close_run(res["close_run_id"])
        tc.assertEqual(run["statements"]["label"], SHADOW)
        tc.assertTrue(run["statements"]["balance_sheet"]["balanced"])

    # ---- step 12: pass criteria ------------------------------------------------------------------ #

    def step12(self, tc):
        """Pass criteria: balanced books, reconciled subledgers, unique transfers, every action a
        consumed approval under the identity policy, the release controls used, intact records."""
        c = self.c
        # every journal balances; the trial balance balances overall and for the closed period
        journals = c.ledger.journals()
        for j in journals:
            dr = sum(D(ln["debit"]) for ln in j["lines"])
            cr = sum(D(ln["credit"]) for ln in j["lines"])
            tc.assertEqual(dr, cr, j["id"])
            tc.assertGreater(dr, 0, j["id"])
        tc.assertTrue(c.ledger.trial_balance()["balanced"])
        tc.assertTrue(c.ledger.trial_balance("P1")["balanced"])
        tc.assertTrue(self.close.statements("P1")["balance_sheet"]["balanced"])

        # AP and AR reconcile to their control accounts, as do every core subledger and the bank
        ap = c.bills.ap_open_items()
        tc.assertEqual((ap["subledger_total"], ap["control_balance"], ap["reconciled"]), ("0.00", "0.00", True))
        ar = c.receivables.ar_open_items()
        tc.assertEqual((ar["subledger_total"], ar["control_balance"], ar["reconciled"]), ("63000.00", "63000.00", True))
        for fn in (c.bills.retainage_open_items, c.bills.stored_material_items, c.receivables.retainage_receivable_items, c.payments.clearing_items):
            tc.assertTrue(fn()["reconciled"], fn.__name__)
        tc.assertTrue(self.bank.reconciliation_status("P1")["reconciled"])
        balances = {code: c.ledger.balance(code) for code in ("1000", "1100", "1150", "1200", "1500", "1590", "2000", "2050", "4000", "5000", "5200")}
        # bank: the two disbursements and the kit; cost: the PO (19,000) and the gross pay application (40,000)
        tc.assertEqual(balances, {"1000": D("-58600.00"), "1100": D("63000.00"), "1150": D("7000.00"), "1200": D("0.00"), "1500": D("3600.00"),
                                  "1590": D("-100.00"), "2000": D("0.00"), "2050": D("4000.00"), "4000": D("70000.00"), "5000": D("59000.00"),
                                  "5200": D("100.00")})

        # one transfer, one acceptance and one cash effect per release
        intents = c.payments.list()
        tc.assertEqual(sorted((p["provider_ref"], p["amount"], p["status"]) for p in intents),
                       [("sim_000001", "19000.00", "settled"), ("sim_000002", "36000.00", "settled")])
        tc.assertEqual(sorted(t["provider_ref"] for t in c.provider.transfers.values()), ["sim_000001", "sim_000002"])
        tc.assertEqual(len(c.ledger.journals(source_type="payment_intent")), 2)
        tc.assertEqual(len(c.ledger.journals(source_type="provider_event")), 2)

        # every consequential action is a consumed approval; nothing is left pending or granted
        consumed = c.approvals.list(status="consumed")
        tc.assertEqual(sorted({a["operation"] for a in consumed}), sorted([
            "people.grant_role", "payment_policy.update", "contract.require_agreements", "people.set_policy", "estimate.approve",
            "procurement.award", "contract.approve_agreement", "contract.sign", "commitment.execute", "party.verify_destination",
            "ap_intake.match_invoice", "bill.approve", "payment.release", "asset.capitalise", "asset.post_depreciation", "prime_bill.approve",
            "banking.lock_reconciliation", "handoff.acknowledge", "close.close_period"]))
        counts = {}
        for a in consumed:
            counts[a["operation"]] = counts.get(a["operation"], 0) + 1
        tc.assertEqual(pick(counts, ("people.grant_role", "contract.approve_agreement", "contract.sign", "commitment.execute", "ap_intake.match_invoice",
                                     "bill.approve", "payment.release")),
                       {"people.grant_role": len(GRANTS), "contract.approve_agreement": 2, "contract.sign": 2, "commitment.execute": 2,
                        "ap_intake.match_invoice": 2, "bill.approve": 2, "payment.release": 2})
        tc.assertEqual(c.approvals.list(status="granted"), [])
        tc.assertEqual(c.approvals.list(status="pending"), [])
        for j in journals:
            if j["approval_id"]:
                tc.assertEqual(c.approvals.get(j["approval_id"])["status"], "consumed", j["id"])
            else:
                tc.assertIn(j["source_type"], BANK_FACT_SOURCES, j["id"])

        # under the enforcing identity policy every approval named three registered identities:
        # a requester, a different approver holding the approving role, and an executor
        policy_approval = [a for a in consumed if a["operation"] == "people.set_policy"][0]["id"]
        enforced = [a for a in consumed if a["id"] > policy_approval]  # approval ids are time-ordered
        tc.assertGreaterEqual(len(enforced), 20)
        for a in enforced:
            tc.assertEqual(a["manifest"]["governance"]["people"]["policy_version"], 1, a["operation"])
            tc.assertNotEqual(a["requested_by"], a["approver"], a["operation"])
            for login in (a["requested_by"], a["approver"], a["consumed_by"]):
                tc.assertTrue(self.people.is_active(login), (a["operation"], login))
        tc.assertEqual(self.people.self_approvals(), [])

        # the release controls: one standard and one high-risk clearance, the co-signature and the step-up used once
        clearances = sorted(self.policy.clearances(), key=lambda k_: k_["classification"])
        tc.assertEqual([(k_["classification"], k_["releaser"], k_["approver"], k_["requested_by"]) for k_ in clearances],
                       [("high_risk", "tre.tom", "owner", "acct.ivy"), ("standard", "tre.tom", "owner", "acct.ivy")])
        tc.assertEqual([(s_["cosigner"], s_["approval_id"]) for s_ in self.policy.cosignatures()], [("ext.acct", self.sub_release["id"])])
        tc.assertEqual([s_["approval_id"] for s_ in self.policy.step_ups("tre.tom")], [self.sub_release["id"]])
        tc.assertTrue(self.policy.verify_chain()["ok"])

        # contracts: both commitments rest on a signed agreement; coverage was verified at bill approval and release
        for cid, agreement in ((self.po, self.po_agreement), (self.cid, self.sub_agreement)):
            tc.assertEqual((self.contracts.agreement_for(cid)["id"], self.contracts.agreement_for(cid)["status"]), (agreement["id"], "signed"))
        verified = [e for e in c.audit.entries() if e["action"] == "contract.coverage_verified"]
        tc.assertEqual(sorted(json.loads(e["payload_json"])["operation"] for e in verified), ["bill.approve", "payment.release"])

        # procurement, intake and assets
        award = self.proc.award(self.proc.requisitions(self.pid)[0]["id"])
        tc.assertEqual((award["commitment_id"], award["amount"], bool(award["lowest_compliant"])), (self.po, "19000.00", False))
        summary = c.project_state(self.pid)["ap_intake"]["summary"]
        tc.assertEqual(pick(summary, ("invoices", "matched", "unmatched", "exceptions", "possible_duplicates")),
                       {"invoices": 2, "matched": 2, "unmatched": 0, "exceptions": 0, "possible_duplicates": 0})
        tc.assertEqual({b["supplier_invoice_number"] for b in (c.bills.get(self.po_bill["id"]), c.bills.get(self.sub_bill["id"]))}, {"PV-7781", "WW-2026-001"})
        tc.assertEqual(self.assets.get_asset(self.asset["id"])["net_book_value"], "3500.00")

        # rights and Ricky: every SDK call left a receipt in an intact chain
        tc.assertEqual([(r["tool"], r["status"]) for r in self.sdk.receipts()],
                       [("record_supplier_invoice", "refused"), ("record_supplier_invoice", "ok"), ("compute_invoice_match", "ok"), ("request_approval", "ok"),
                        ("execute_approved_action", "ok"), ("read_document", "refused"), ("read_document", "ok"), ("read_brief", "ok")])
        tc.assertTrue(self.sdk.verify_receipts()["ok"])
        tc.assertFalse(self.rights.check_use(self.handbook["id"], "ai_retrieval")["allowed"])

        # the hand-off was acknowledged and the period closed through its checklist
        tc.assertEqual(self.handoff.handoff(self.handoff_id)["status"], "acknowledged")
        tc.assertEqual(c.ledger.period("P1")["status"], "closed")
        tc.assertTrue(c.audit.verify_chain()["ok"])
        state = c.project_state(self.pid)
        json.dumps(state, default=str)
        tc.assertEqual((state["forecast"]["executed_commitments"], state["forecast"]["paid_to_date"]), ("79000.00", "55000.00"))


class ExtendedVerticalTests(unittest.TestCase):
    """The extended job, step by step, then the pass criteria."""

    job: ExtendedJob | None = None

    @classmethod
    def setUpClass(cls):
        cls.job = ExtendedJob()

    def run_step(self, n):
        self.job.run_through(n, self)

    def test_step01_governance_people_payment_policy_and_required_agreements(self):
        self.run_step(1)

    def test_step02_estimate_under_identity_enforcement(self):
        self.run_step(2)

    def test_step03_procurement_award_signed_purchase_order_and_receiving(self):
        self.run_step(3)

    def test_step04_subcontract_executed_under_contracts_with_certificates(self):
        self.run_step(4)

    def test_step05_governed_destination_change(self):
        self.run_step(5)

    def test_step06_po_invoice_three_way_match_through_ricky_bill_and_standard_release(self):
        self.run_step(6)

    def test_step07_pay_application_coverage_and_high_risk_release_to_new_destination(self):
        self.run_step(7)

    def test_step08_asset_capitalization_and_one_month_of_depreciation(self):
        self.run_step(8)

    def test_step09_content_rights_and_ricky_document_retrieval(self):
        self.run_step(9)

    def test_step10_prime_billing(self):
        self.run_step(10)

    def test_step11_bank_reconciliation_handoff_and_period_close(self):
        self.run_step(11)

    def test_step12_pass_criteria(self):
        self.run_step(12)


if __name__ == "__main__":
    unittest.main()
