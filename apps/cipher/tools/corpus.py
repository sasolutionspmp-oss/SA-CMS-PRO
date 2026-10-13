"""Deterministic 20-bill corpus with approval-time metrics.

    python -m apps.cipher.tools.corpus [--out FILE]

Twenty synthetic supplier bills (literal data, no randomness) run through supplier invoice
intake, the three-way match, approval, posting and payment release on one fresh in-memory
workspace, and the tool prints a JSON report of what the approvals cost: how many approvals
each bill needed and of which kind, how many were routed to the owner and how many to staff,
what was blocked or held and why, and the simulated time from intake to release.

The corpus mixes:

* subcontract pay applications with retainage (5 and 10 percent) and stored materials
  billed and later transferred to installed;
* purchase-order supplier invoices matched three ways (equipment received in good condition,
  the PO line, a certified PO bill);
* an exact duplicate (refused at intake), a near duplicate (same supplier and amount within
  seven days: held until a person reviews it), a supplier credit note (the release pays the
  open payable), and a posted bill corrected (reversed, re-certified and matched to the
  supplier's reissued invoice);
* a high-risk payment (at or over the payment policy's threshold: independent approval,
  the outside accountant's co-signature and a fresh step-up) and a payment to a destination
  set by a governed change days earlier (held by the cooling-off window, then high risk).

Governance is on, as in production: the people registry enforces a segregated identity policy
(every approval names a registered requester, a different approver holding the approving
role, and an executor holding the executing role) and a payment release policy is adopted.

Approval routing (the corpus's approval matrix; the system enforces who *may* approve, the
matrix chooses who *does*): match approvals, credit notes and corrections go to the
controller; bills and releases of ``OWNER_THRESHOLD`` or more, and every high-risk release, go
to the owner; smaller bills to the controller and smaller releases to the treasury manager.
Each approver answers after a fixed latency (``LATENCY_MINUTES``); other steps take fixed
times too (``*_MINUTES``).

Time.  The system's clock abstraction is the injectable clock of the governors
(``Plugin.now`` on the people, payment policy and contract plugins) and the receivables
calendar day (``Receivables.today``); tests move time by replacing them.  The corpus installs
one ``SimClock`` into all four and drives it with a discrete-event loop: each bill is a
sequence of steps scheduled on the simulated timeline, the clock only moves forward, and a
step that waits for another bill (a pay application after its predecessor posted) polls every
``POLL_MINUTES``.  The clock starts at the instant the governed destination change executed
(the time the payments module recorded), so the cooling-off window is an exact simulated
interval.  Intake is stamped from the clock when the invoice is received; release is the
``cleared_at`` the payment policy records with the same clock when the release executes.
The approvals module and the payment value date keep the wall clock (they have no injectable
clock), which is why the simulated weeks never expire an approval.

Every figure in the report is deterministic: amounts, counts and simulated durations, never
identifiers or wall-clock timestamps.  ``tests/test_corpus.py`` asserts the exact report and
the ledger invariants.  Everything is synthetic and nothing leaves the prototype.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import heapq
import json
import os
import sys
from decimal import Decimal
from typing import Any, Callable, Iterator

from ..service import Cipher  # loads the plugin modules first
from ..core.approvals import StaleApprovalError
from ..core.ids import parse_iso, sha256_hex
from ..core.money import ZERO, fmt, money
from ..domain.ap_intake import DuplicateInvoiceError
from ..domain.payment_policy import CoolingOffHold, CosignatureRequired, StepUpRequired
from ..domain.payments import VERIFICATION_CHANNELS

REPORT_FORMAT = "cipher-corpus/1"
ENTITY = "S&A Solutions LLC (synthetic)"
PERIOD = ("P1", "October 2026", "2026-10-01", "2026-10-31")
MONTH_START = _dt.date(2026, 10, 1)
TERMS_DAYS = 30
OWNER = "owner"
CLERK = "ap.clerk"          # receives invoices and computes matches (no approving role)
ACCOUNTANT = "acct.ivy"     # requests approvals and executes postings
CONTROLLER = "ctrl.ana"
TREASURY_MANAGER = "tre.mia"
RELEASER = "tre.tom"
PM = "pm.lee"
BANK_ADMIN = "bank.ben"
INDEPENDENT = "ext.acct"    # the outside accountant: co-signs and verifies payee changes
# (login, display name, external, role or None)
IDENTITIES = (
    (CLERK, "Synthetic AP clerk", False, None),
    (ACCOUNTANT, "Synthetic staff accountant", False, "accountant"),
    (CONTROLLER, "Synthetic controller", False, "controller"),
    (TREASURY_MANAGER, "Synthetic treasury manager", False, "treasury"),
    (RELEASER, "Synthetic treasury releaser", False, "treasury"),
    (PM, "Synthetic project manager", False, "pm"),
    (BANK_ADMIN, "Synthetic bank-detail maintainer", False, "bank_admin"),
    (INDEPENDENT, "Synthetic external accountant", True, "accountant"),
)
ROLE_OF = {OWNER: "owner", **{login: role for login, _, _, role in IDENTITIES if role}}

# the payment release policy and the approval matrix
HIGH_RISK_AMOUNT = "50000.00"
COSIGN_AMOUNT = "50000.00"
STEP_UP_MAX_AGE_SECONDS = 900
COOLING_DAYS = 5
OWNER_THRESHOLD = Decimal("25000.00")

# simulated durations (minutes)
LATENCY_MINUTES = {OWNER: 360, CONTROLLER: 120, TREASURY_MANAGER: 60}
ARRIVAL_MINUTES = 60          # an invoice dated day D arrives D - Oct 1 days after the start, plus this
PM_REVIEW_MINUTES = 240       # the PM certifies a pay application (or a PO bill) after this
MATCH_MINUTES = 30            # the clerk computes the match
EXECUTE_MINUTES = 15          # an executor acts on a granted approval
DUPLICATE_REVIEW_MINUTES = 180
CREDIT_NOTE_MINUTES = 60
CORRECTION_FINDING_MINUTES = 1440   # field verification finds the overstatement a day later
REISSUE_MINUTES = 120
COSIGN_MINUTES = 1440          # the outside accountant co-signs a day later
STEP_UP_MINUTES = 5
DISPATCH_MINUTES = 30
SETTLE_MINUTES = 1440
POLL_MINUTES = 30

# ---- the corpus (literal data) ------------------------------------------------ #

SUPPLIERS = {
    "S1": ("Synthetic Sheet Pile Subcontractor (corpus)", "ACH-SIM-CRP-S1-0001"),
    "S2": ("Synthetic Dewatering Subcontractor (corpus)", "ACH-SIM-CRP-S2-0001"),
    "S3": ("Synthetic Pump and Generator Supplier (corpus)", "ACH-SIM-CRP-S3-0001"),
    "S4": ("Synthetic Electrical Subcontractor (corpus)", "ACH-SIM-CRP-S4-0001"),
    "S5": ("Synthetic Valve Supplier (corpus)", "ACH-SIM-CRP-S5-0001"),
    "S6": ("Synthetic Paving Subcontractor (corpus)", "ACH-SIM-CRP-S6-0001"),
    "S7": ("Synthetic Fencing Subcontractor (corpus)", "ACH-SIM-CRP-S7-0001"),
}
CHANGED_SUPPLIER, CHANGED_DESTINATION = "S2", "ACH-SIM-CRP-S2-0002"
SUBCONTRACTS = {
    "C1": ("S1", "Sheet pile cofferdam and excavation support", "0.10",
           (("Sheet pile cofferdam", "120000", "XX 10 00"), ("Excavation support and dewatering wells", "80000", "XX 20 00"))),
    "C2": ("S2", "Dewatering and bypass pumping", "0.05",
           (("Dewatering", "60000", "XX 30 00"), ("Bypass pumping", "40000", "XX 31 00"))),
    "C3": ("S4", "Electrical and controls", "0.10",
           (("Power distribution", "30000", "XX 40 00"), ("Controls and instrumentation", "20000", "XX 41 00"))),
    "C4": ("S6", "Site paving", "0.10", (("Paving and base course", "40000", "XX 50 00"),)),
    "C5": ("S7", "Perimeter fencing", "0.05", (("Fencing and gates", "24000", "XX 60 00"),)),
}
ORDERS = {
    "PO1": ("S3", "Submersible pumps", "36000.00", (("P-301", "Submersible pump 1"), ("P-302", "Submersible pump 2"), ("P-303", "Submersible pump 3"))),
    "PO2": ("S5", "Plug valves", "20000.00", tuple((f"V-40{n}", f"Plug valve {n}") for n in range(1, 9))),
    "PO3": ("S3", "Standby generator", "18000.00", (("G-501", "Standby generator, 150 kW"),)),
}
# kind: pay_app (installed: SOV line number -> cumulative; stored: new lots; transfers: lot key -> amount),
# po_invoice (equipment tags billed), duplicate (re-sends an earlier item's invoice).  "after" is the item
# whose bill must post first (same commitment).
CORPUS: tuple[dict[str, Any], ...] = (
    {"item": 1, "kind": "pay_app", "commitment": "C1", "invoice": "SP-101", "date": "2026-10-02", "amount": "27000.00",
     "installed": {1: "20000"}, "stored": (("A", 1, "10000", "Sheet piling stored on site"),), "tags": ("retainage", "stored_material")},
    {"item": 2, "kind": "pay_app", "commitment": "C1", "invoice": "SP-102", "date": "2026-10-09", "amount": "18000.00", "after": 1,
     "installed": {1: "45000"}, "stored": (("B", 1, "5000", "Walers and struts stored on site"),), "transfers": {"A": "10000"},
     "tags": ("retainage", "stored_material", "stored_transfer")},
    {"item": 3, "kind": "pay_app", "commitment": "C1", "invoice": "SP-103", "date": "2026-10-16", "amount": "45000.00", "after": 2,
     "installed": {1: "80000", 2: "20000"}, "transfers": {"B": "5000"}, "tags": ("retainage", "stored_transfer")},
    {"item": 4, "kind": "pay_app", "commitment": "C1", "invoice": "SP-104", "date": "2026-10-23", "amount": "81000.00", "after": 3,
     "installed": {1: "120000", 2: "70000"}, "tags": ("retainage", "high_risk_payment")},
    {"item": 5, "kind": "pay_app", "commitment": "C2", "invoice": "DW-201", "date": "2026-10-05", "amount": "28500.00",
     "installed": {1: "30000"}, "tags": ("retainage", "new_destination_payment")},
    {"item": 6, "kind": "pay_app", "commitment": "C2", "invoice": "DW-202", "date": "2026-10-19", "amount": "38000.00", "after": 5,
     "installed": {1: "60000", 2: "10000"}, "tags": ("retainage",)},
    {"item": 7, "kind": "pay_app", "commitment": "C3", "invoice": "EL-101", "date": "2026-10-03", "amount": "9000.00",
     "installed": {1: "10000"}, "tags": ("retainage",)},
    {"item": 8, "kind": "duplicate", "of": 7, "invoice": "EL 101", "date": "2026-10-04", "amount": "9000.00", "tags": ("duplicate",)},
    {"item": 9, "kind": "pay_app", "commitment": "C3", "invoice": "EL-102", "date": "2026-10-12", "amount": "13500.00", "after": 7,
     "installed": {1: "25000"}, "credit_note": ("1500.00", "back-charge: trench restoration done by the general contractor"),
     "tags": ("retainage", "credit_note")},
    {"item": 10, "kind": "pay_app", "commitment": "C3", "invoice": "EL-103", "date": "2026-10-20", "amount": "18000.00", "after": 9,
     "installed": {1: "30000", 2: "15000"},
     "correction": {"reason": "controls installed overstated: field count supports 11,000, not 15,000", "installed": {1: "30000", 2: "11000"},
                    "amount": "14400.00", "date": "2026-10-24"},
     "tags": ("retainage", "correction")},
    {"item": 11, "kind": "po_invoice", "order": "PO1", "invoice": "PV-3101", "date": "2026-10-06", "amount": "12000.00",
     "equipment": ("P-301",), "tags": ("purchase_order",)},
    {"item": 12, "kind": "po_invoice", "order": "PO1", "invoice": "PV-3102", "date": "2026-10-16", "amount": "24000.00", "after": 11,
     "equipment": ("P-302", "P-303"), "tags": ("purchase_order",)},
    {"item": 13, "kind": "po_invoice", "order": "PO2", "invoice": "VS-501", "date": "2026-10-08", "amount": "10000.00",
     "equipment": ("V-401", "V-402", "V-403", "V-404"), "tags": ("purchase_order",)},
    {"item": 14, "kind": "po_invoice", "order": "PO2", "invoice": "VS-502", "date": "2026-10-08", "amount": "10000.00", "after": 13,
     "equipment": ("V-405", "V-406", "V-407", "V-408"), "tags": ("purchase_order", "near_duplicate")},
    {"item": 15, "kind": "pay_app", "commitment": "C4", "invoice": "PAV-601", "date": "2026-10-07", "amount": "10800.00",
     "installed": {1: "8000"}, "stored": (("C", 1, "4000", "Base course aggregate stockpiled on site"),), "tags": ("retainage", "stored_material")},
    {"item": 16, "kind": "pay_app", "commitment": "C4", "invoice": "PAV-602", "date": "2026-10-14", "amount": "7200.00", "after": 15,
     "installed": {1: "20000"}, "transfers": {"C": "4000"}, "tags": ("retainage", "stored_transfer")},
    {"item": 17, "kind": "pay_app", "commitment": "C5", "invoice": "FN-701", "date": "2026-10-05", "amount": "11400.00",
     "installed": {1: "12000"}, "tags": ("retainage",)},
    {"item": 18, "kind": "pay_app", "commitment": "C5", "invoice": "FN-702", "date": "2026-10-21", "amount": "11400.00", "after": 17,
     "installed": {1: "24000"}, "tags": ("retainage",)},
    {"item": 19, "kind": "po_invoice", "order": "PO3", "invoice": "PV-3103", "date": "2026-10-22", "amount": "18000.00",
     "equipment": ("G-501",), "tags": ("purchase_order",)},
    {"item": 20, "kind": "pay_app", "commitment": "C4", "invoice": "PAV-603", "date": "2026-10-27", "amount": "18000.00", "after": 16,
     "installed": {1: "40000"}, "tags": ("retainage",)},
)
HELD_REASONS = ("possible_duplicate_review", "cooling_off", "cosignature_required", "step_up_required")


class CorpusError(RuntimeError):
    """The corpus did not run as specified (a figure differs from the literal data, or a step
    the system should allow was refused)."""


class SimClock:
    """The simulated clock installed as the system's clock abstraction.  It moves only forward."""

    def __init__(self, start: _dt.datetime):
        self._t = start
        self.start = start

    def now(self) -> _dt.datetime:
        return self._t

    def today(self) -> _dt.date:
        return self._t.date()

    def move_to(self, moment: _dt.datetime) -> None:
        if moment < self._t:
            raise CorpusError(f"the simulated clock never moves back ({moment.isoformat()} < {self._t.isoformat()})")
        self._t = moment

    def minutes(self, moment: _dt.datetime | None = None) -> int:
        """Whole minutes since the start."""
        return int(((moment or self._t) - self.start).total_seconds() // 60)


class _Bill:
    """One corpus item's run: what the system recorded for it and what it cost."""

    def __init__(self, spec: dict[str, Any]):
        self.spec = spec
        self.status = "pending"
        self.subjects: set[str] = set()
        self.posted = False
        self.intake_at: _dt.datetime | None = None
        self.released_at: _dt.datetime | None = None
        self.released: str | None = None
        self.classification: str | None = None
        self.held = {k: 0 for k in HELD_REASONS}
        self.blocked: dict[str, int] = {}
        self.waits: list[dict[str, Any]] = []


class Corpus:
    """Build the synthetic job and run the corpus; ``run()`` returns the metrics report."""

    def __init__(self):
        self.c = c = Cipher()
        self.people = c.plugin("people")
        self.policy = c.plugin("payment_policy")
        self.intake = c.plugin("ap_intake")
        self.proc = c.plugin("procurement")
        self.docs = 0
        self.step_ups = 0
        self.lots: dict[str, str] = {}
        self.po_billed: dict[str, list[str]] = {k: [] for k in ORDERS}
        self.bills: dict[int, _Bill] = {}
        self.clock: SimClock | None = None

    # ---- setup (wall clock) -------------------------------------------------------------- #

    def evidence(self, kind: str, title: str, actor: str) -> tuple[dict[str, Any], dict[str, Any]]:
        self.docs += 1
        doc = self.c.evidence.register_document(project_id=self.pid, kind=kind, title=f"{title} (synthetic corpus)", actor=actor)
        rev = self.c.evidence.add_revision(document_id=doc["id"], content=f"corpus document {self.docs}: {kind}: {title}".encode(), actor=actor)
        return doc, rev

    def _run(self, operation: str, subject_id: str, *, requester: str, approver: str, executor: str, actor_role: str) -> dict[str, Any]:
        ap = self.c.request_approval(operation, subject_id, actor_role=actor_role, requested_by=requester)
        self.c.approve(ap["id"], approver=approver, approver_role=ROLE_OF[approver])
        return self.c.execute(ap["id"], actor=executor).result

    def setup(self) -> None:
        c, p = self.c, self.people
        self.parties = {}
        for key, (name, destination) in SUPPLIERS.items():
            party = c.add_party(kind="supplier", name=name, destination=destination)
            self.parties[key] = c.verify_destination(party["id"], destination=destination, verified_by=BANK_ADMIN)["id"]
        self.project = c.create_project(name="Synthetic corpus: river intake and pump station", entity=ENTITY, budget="600000")
        self.pid = self.project["id"]
        c.open_period(*PERIOD)
        for key in SUPPLIERS:
            self.intake.set_terms(self.parties[key], TERMS_DAYS, CONTROLLER)

        # people: the owner, the staff and the outside accountant; roles through people.grant_role; then enforcement
        p.bootstrap_owner(OWNER, "Synthetic owner")
        for login, name, external, _role in IDENTITIES:
            p.register_person(login, name, actor=OWNER, external=external)
        for login, _name, _external, role in IDENTITIES:
            if role:
                req = p.request_grant(login, role, reason="corpus staffing", actor=OWNER)
                self._run("people.grant_role", req["id"], requester=OWNER, approver=OWNER, executor=OWNER, actor_role="owner")
        draft = self.policy.draft_policy(high_risk_amount=HIGH_RISK_AMOUNT, cosign_amount=COSIGN_AMOUNT, step_up_max_age_seconds=STEP_UP_MAX_AGE_SECONDS,
                                         new_destination_cooling_days=COOLING_DAYS, first_payment_to_destination_is_high_risk=False,
                                         independent_parties=[INDEPENDENT], reason="corpus release control", actor=OWNER)
        self._run("payment_policy.update", draft["id"], requester=OWNER, approver=OWNER, executor=OWNER, actor_role="owner")
        draft = p.prepare_policy(enforce=True, segregate=True, reason="corpus: identities enforced and segregated", actor=OWNER)
        self._run("people.set_policy", draft["id"], requester=OWNER, approver=OWNER, executor=OWNER, actor_role="owner")

        # subcontracts, executed by the PM under the owner's approval
        self.commitments: dict[str, dict[str, Any]] = {}
        for key, (supplier, title, rate, lines) in SUBCONTRACTS.items():
            cmt = c.commitments.create(project_id=self.pid, supplier_id=self.parties[supplier], title=f"{key} - {title}",
                                       sov_lines=[{"description": d, "amount": a, "cost_code": cc} for d, a, cc in lines], retainage_rate=rate, actor=PM)
            self._run("commitment.execute", cmt["id"], requester=PM, approver=OWNER, executor=PM, actor_role="pm")
            self.commitments[key] = c.commitments.get(cmt["id"])

        # purchase orders: equipment, requisition, quote, award, executed PO, every item received in good condition
        self.orders: dict[str, dict[str, Any]] = {}
        for key, (supplier, title, amount, items) in ORDERS.items():
            equipment = [self.proc.add_equipment(self.pid, tag, desc, "XX 40 00", "2027-03-01", actor=PM) for tag, desc in items]
            req = self.proc.create_requisition(self.pid, title, [e["id"] for e in equipment], actor=PM)
            quote = self.proc.add_quote(req["id"], self.parties[supplier], amount, 8, "2099-12-31", True, actor=PM)
            self.proc.select_quote(req["id"], quote["id"], "", actor=PM)
            award = self._run("procurement.award", req["id"], requester=PM, approver=OWNER, executor=PM, actor_role="pm")
            self._run("commitment.execute", award["commitment"], requester=PM, approver=OWNER, executor=PM, actor_role="pm")
            po = c.commitments.get(award["commitment"])
            today = c.receivables.today().isoformat()
            for e in equipment:
                self.proc.receive(e["id"], today, "ok", sha256_hex(f"corpus delivery ticket {e['tag']}"), actor=PM)
            # the award drafts one PO line per equipment item, in requisition order
            self.orders[key] = {"commitment": po, "supplier": supplier, "equipment": {e["tag"]: e["id"] for e in equipment},
                                "line": {e["tag"]: ln for e, ln in zip(equipment, po["sov"])}}

        # the dewatering subcontractor's new bank details, verified by the outside accountant's call-back
        _, rev = self.evidence("destination_verification", "Dewatering subcontractor bank change call-back", BANK_ADMIN)
        change_id = c.payments.governed_destination_change(self.parties[CHANGED_SUPPLIER], CHANGED_DESTINATION, ACCOUNTANT, INDEPENDENT,
                                                           VERIFICATION_CHANNELS[0], rev["content_hash"], BANK_ADMIN)
        self._run("party.verify_destination", change_id, requester=BANK_ADMIN, approver=OWNER, executor=BANK_ADMIN, actor_role="bank_admin")
        self.change = c.payments.destination_change(change_id)

        # from here on the system runs on the simulated clock, starting when the change executed
        self.clock = SimClock(parse_iso(self.change["executed_at"]))
        for name in ("people", "payment_policy", "contract"):
            plugin = c._plugins.get(name)
            if plugin is not None:
                plugin.now = self.clock.now
        c.receivables.today = self.clock.today

    # ---- steps (simulated clock) ------------------------------------------------------- #

    def _approval(self, b: _Bill, operation: str, subject_id: str, *, actor_role: str, approver: str, executor: str) -> Iterator[Any]:
        """Request (the accountant), wait the approver's latency, grant, wait, execute."""
        ap = self.c.request_approval(operation, subject_id, actor_role=actor_role, requested_by=ACCOUNTANT)
        b.subjects.add(subject_id)
        requested = self.clock.minutes()
        yield LATENCY_MINUTES[approver]
        self.c.approve(ap["id"], approver=approver, approver_role=ROLE_OF[approver])
        b.waits.append({"operation": operation, "approver": approver, "minutes": self.clock.minutes() - requested})
        yield EXECUTE_MINUTES
        return self.c.execute(ap["id"], actor=executor).result

    def _match(self, b: _Bill, invoice_id: str) -> Iterator[Any]:
        res = self.intake.match(invoice_id, CLERK)
        if res["exceptions"] == ["possible_duplicate"]:
            b.held["possible_duplicate_review"] += 1
            yield DUPLICATE_REVIEW_MINUTES
            self.intake.clear_duplicate_flag(invoice_id, "reviewed against the earlier invoice: a second shipment, not a duplicate", CONTROLLER)
            yield MATCH_MINUTES
            res = self.intake.match(invoice_id, CLERK)
        if res["status"] != "matched":
            raise CorpusError(f"item {b.spec['item']}: invoice {b.spec['invoice']} did not match: {res['details']}")
        result = yield from self._approval(b, "ap_intake.match_invoice", invoice_id, actor_role="accountant", approver=CONTROLLER, executor=ACCOUNTANT)
        return result

    def _post(self, b: _Bill, bill: dict[str, Any], amount: str) -> Iterator[Any]:
        if bill["amount_due"] != amount:
            raise CorpusError(f"item {b.spec['item']}: certified {bill['amount_due']}, the invoice says {amount}")
        approver = OWNER if money(amount) >= OWNER_THRESHOLD else CONTROLLER
        yield from self._approval(b, "bill.approve", bill["id"], actor_role="accountant", approver=approver, executor=ACCOUNTANT)

    def _release(self, b: _Bill, bill_id: str) -> Iterator[Any]:
        """Request, route, grant and release; each refusal the payment policy raises is supplied
        (co-signature, step-up) or waited out (cooling-off) and the release retried; an approval
        the policy facts outgrew is requested again."""
        while True:
            ap = self.c.request_approval("payment.release", bill_id, actor_role="treasury", requested_by=ACCOUNTANT)
            b.subjects.add(bill_id)
            facts = ap["manifest"]["governance"]["payment_policy"]
            approver = OWNER if facts["classification"] == "high_risk" or money(facts["amount"]) >= OWNER_THRESHOLD else TREASURY_MANAGER
            requested = self.clock.minutes()
            yield LATENCY_MINUTES[approver]
            self.c.approve(ap["id"], approver=approver, approver_role=ROLE_OF[approver])
            b.waits.append({"operation": "payment.release", "approver": approver, "minutes": self.clock.minutes() - requested})
            yield EXECUTE_MINUTES
            while True:
                try:
                    res = self.c.execute(ap["id"], actor=RELEASER).result
                except CoolingOffHold:
                    b.held["cooling_off"] += 1
                    until = parse_iso(facts["destination"]["change"]["cooling_off_until"])
                    yield ("at", until + _dt.timedelta(minutes=1))
                    continue
                except CosignatureRequired:
                    b.held["cosignature_required"] += 1
                    yield COSIGN_MINUTES
                    self.policy.cosign(ap["id"], INDEPENDENT, INDEPENDENT)
                    continue
                except StepUpRequired:
                    b.held["step_up_required"] += 1
                    self.step_ups += 1
                    self.policy.record_step_up(RELEASER, "webauthn", sha256_hex(f"corpus step-up assertion {self.step_ups}"), "sign-in-service")
                    yield STEP_UP_MINUTES
                    continue
                except StaleApprovalError:
                    break  # invalidated (the report counts it from the approvals); request it again
                clearance = [k for k in self.policy.clearances() if k["approval_id"] == ap["id"]][0]
                b.released_at = parse_iso(clearance["cleared_at"])
                b.classification = clearance["classification"]
                b.released = res["amount"]
                yield DISPATCH_MINUTES
                self.c.dispatch_payments()
                yield SETTLE_MINUTES
                intent = self.c.payments.get(res["intent"])
                if intent["status"] != "accepted":
                    raise CorpusError(f"item {b.spec['item']}: intent is {intent['status']} at settlement")
                self.c.payments.ingest_event(self.c.provider.settle(intent["logical_op_id"]), actor="webhook")
                return

    def _receive(self, b: _Bill, supplier_key: str, *, commitment_id: str, lines=()) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        spec = b.spec
        doc, rev = self.evidence("supplier_invoice", f"Supplier invoice {spec['invoice']}", CLERK)
        try:
            inv = self.intake.receive_invoice(self.parties[supplier_key], spec["invoice"], spec["date"], spec["amount"], rev["content_hash"], CLERK,
                                              project_id=self.pid, commitment_id=commitment_id, lines=list(lines))
        except DuplicateInvoiceError:
            b.blocked["duplicate_invoice"] = b.blocked.get("duplicate_invoice", 0) + 1
            b.status = "blocked"
            return None, doc
        b.intake_at = self.clock.now()
        b.subjects.add(inv["id"])
        return inv, doc

    def _wait_for(self, b: _Bill) -> Iterator[Any]:
        after = b.spec.get("after")
        if after is not None and not self.bills[after].posted:
            yield ("until", lambda: self.bills[after].posted)

    def _certify(self, cid: str, installed: dict[int, str], transfers: dict[str, str] | None = None) -> dict[str, Any]:
        sov = self.c.commitments.get(cid)["sov"]
        return self.c.bills.certify(commitment_id=cid, period_id=PERIOD[0],
                                    installed=[{"sov_line_id": sov[n - 1]["id"], "cumulative_installed": v} for n, v in installed.items()],
                                    transfers=[{"lot_id": self.lots[k], "amount": v} for k, v in (transfers or {}).items()], actor=PM)

    def pay_app(self, b: _Bill) -> Iterator[Any]:
        spec = b.spec
        supplier, *_ = SUBCONTRACTS[spec["commitment"]]
        cid = self.commitments[spec["commitment"]]["id"]
        inv, doc = self._receive(b, supplier, commitment_id=cid)
        yield PM_REVIEW_MINUTES
        yield from self._wait_for(b)
        sov = self.c.commitments.get(cid)["sov"]
        for key, line, amount, description in spec.get("stored", ()):
            _, rev = self.evidence("stored_material_evidence", f"{description}: title, insurance, location and delivery", PM)
            lot = self.c.bills.add_stored_material(commitment_id=cid, sov_line_id=sov[line - 1]["id"], description=description, eligible_amount=amount,
                                                   evidence_hash=rev["content_hash"], location="Laydown yard (synthetic)", actor=PM)
            self.lots[key] = lot["id"]
        bill = self._certify(cid, spec["installed"], spec.get("transfers"))
        yield MATCH_MINUTES
        yield from self._match(b, inv["id"])
        yield from self._post(b, bill, spec["amount"])
        if spec.get("credit_note"):
            amount, reason = spec["credit_note"]
            yield CREDIT_NOTE_MINUTES
            _, rev = self.evidence("supplier_credit_note", f"Credit note against {spec['invoice']}", CLERK)
            note = self.c.bills.prepare_credit_note(bill["id"], amount, reason, rev["content_hash"], ACCOUNTANT)
            yield from self._approval(b, "bill.credit_note", note["id"], actor_role="accountant", approver=CONTROLLER, executor=ACCOUNTANT)
        if spec.get("correction"):
            fix = spec["correction"]
            yield CORRECTION_FINDING_MINUTES
            self.c.bills.prepare_correction(bill["id"], fix["reason"], ACCOUNTANT)
            yield from self._approval(b, "bill.correct", bill["id"], actor_role="accountant", approver=CONTROLLER, executor=ACCOUNTANT)
            yield REISSUE_MINUTES
            rev = self.c.evidence.add_revision(document_id=doc["id"], content=f"corpus reissued invoice {spec['invoice']} for {fix['amount']}".encode(), actor=CLERK)
            self.intake.revise_invoice(inv["id"], CLERK, reason="supplier reissued the invoice for the corrected quantities", amount=fix["amount"],
                                       invoice_date=fix["date"], evidence_hash=rev["content_hash"])
            bill = self._certify(cid, fix["installed"])
            b.subjects.add(bill["id"])
            yield MATCH_MINUTES
            yield from self._match(b, inv["id"])
            yield from self._post(b, bill, fix["amount"])
        b.posted = True
        yield from self._release(b, bill["id"])
        b.status = "released"

    def po_invoice(self, b: _Bill) -> Iterator[Any]:
        spec = b.spec
        order = self.orders[spec["order"]]
        po = order["commitment"]
        lines = [{"description": f"{tag} supplied", "amount": order["line"][tag]["amount"], "equipment_id": order["equipment"][tag]} for tag in spec["equipment"]]
        inv, _ = self._receive(b, order["supplier"], commitment_id=po["id"], lines=lines)
        yield PM_REVIEW_MINUTES
        yield from self._wait_for(b)
        self.po_billed[spec["order"]].extend(spec["equipment"])
        installed = {order["line"][tag]["line_no"]: order["line"][tag]["amount"] for tag in self.po_billed[spec["order"]]}
        bill = self._certify(po["id"], installed)
        yield MATCH_MINUTES
        yield from self._match(b, inv["id"])
        yield from self._post(b, bill, spec["amount"])
        b.posted = True
        yield from self._release(b, bill["id"])
        b.status = "released"

    def duplicate(self, b: _Bill) -> Iterator[Any]:
        supplier = SUBCONTRACTS[CORPUS[b.spec["of"] - 1]["commitment"]][0]
        inv, _ = self._receive(b, supplier, commitment_id=self.commitments[CORPUS[b.spec["of"] - 1]["commitment"]]["id"])
        if inv is not None:
            raise CorpusError(f"item {b.spec['item']}: the re-sent invoice {b.spec['invoice']} was not refused as a duplicate")
        return
        yield  # a generator, like the other kinds: it ends at intake

    # ---- the event loop ---------------------------------------------------------------- #

    def run(self) -> dict[str, Any]:
        self.setup()
        clock = self.clock
        heap: list[tuple[_dt.datetime, int, int, Iterator[Any], Callable[[], bool] | None]] = []
        seq = 0

        def push(moment, item, gen, until=None):
            nonlocal seq
            seq += 1
            heapq.heappush(heap, (moment, item, seq, gen, until))

        for spec in CORPUS:
            b = self.bills[spec["item"]] = _Bill(spec)
            arrival = clock.start + _dt.timedelta(days=(_dt.date.fromisoformat(spec["date"]) - MONTH_START).days, minutes=ARRIVAL_MINUTES)
            push(arrival, spec["item"], getattr(self, spec["kind"])(b))
        while heap:
            moment, item, _, gen, until = heapq.heappop(heap)
            clock.move_to(moment)
            if until is not None and not until():
                push(moment + _dt.timedelta(minutes=POLL_MINUTES), item, gen, until)
                continue
            try:
                req = next(gen)
            except StopIteration:
                continue
            if isinstance(req, int):
                push(moment + _dt.timedelta(minutes=req), item, gen)
            elif req[0] == "at":
                push(max(moment, req[1]), item, gen)
            elif req[0] == "until":
                push(moment, item, gen, req[1])
            else:
                raise CorpusError(f"unknown step request {req!r}")
        return self.report()

    # ---- the report ------------------------------------------------------------------------ #

    def _approvals_for(self, b: _Bill) -> list[dict[str, Any]]:
        return [a for a in self.c.approvals.list() if a["subject_id"] in b.subjects]

    @staticmethod
    def _hours(minutes: int) -> str:
        return fmt(Decimal(minutes) / Decimal(60))

    def report(self) -> dict[str, Any]:
        per_bill, elapsed = [], []
        totals = {"requested": 0, "consumed": 0, "invalidated": 0, "owner": 0, "others": 0}
        by_operation: dict[str, int] = {}
        wait = {"owner": 0, "others": 0}
        held = {k: 0 for k in HELD_REASONS}
        blocked: dict[str, int] = {}
        classes: dict[str, int] = {}
        for item, b in sorted(self.bills.items()):
            approvals = self._approvals_for(b)
            consumed = [a for a in approvals if a["status"] == "consumed"]
            ops: dict[str, int] = {}
            for a in consumed:
                ops[a["operation"]] = ops.get(a["operation"], 0) + 1
                by_operation[a["operation"]] = by_operation.get(a["operation"], 0) + 1
            owner = sum(1 for a in consumed if a["approver"] == OWNER)
            totals["requested"] += len(approvals)
            totals["consumed"] += len(consumed)
            totals["invalidated"] += sum(1 for a in approvals if a["status"] == "invalidated")
            totals["owner"] += owner
            totals["others"] += len(consumed) - owner
            for w in b.waits:
                wait["owner" if w["approver"] == OWNER else "others"] += w["minutes"]
            for k, v in b.held.items():
                held[k] += v
            for k, v in b.blocked.items():
                blocked[k] = blocked.get(k, 0) + v
            row: dict[str, Any] = {
                "item": item, "kind": b.spec["kind"], "invoice": b.spec["invoice"], "tags": list(b.spec["tags"]), "status": b.status,
                "approvals": dict(sorted(ops.items())), "approvals_total": len(consumed), "routed_to_owner": owner, "routed_to_others": len(consumed) - owner,
                "approval_wait_minutes": sum(w["minutes"] for w in b.waits),
                "held": {k: v for k, v in b.held.items() if v}, "blocked": dict(b.blocked),
            }
            if b.status == "released":
                minutes = self.clock.minutes(b.released_at) - self.clock.minutes(b.intake_at)
                elapsed.append(minutes)
                classes[b.classification] = classes.get(b.classification, 0) + 1
                row.update({"released": b.released, "classification": b.classification, "intake_to_release_minutes": minutes,
                            "intake_to_release_hours": self._hours(minutes)})
            per_bill.append(row)
        ordered = sorted(elapsed)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        released_total = sum((money(r["released"]) for r in per_bill if r.get("released")), ZERO)
        return {
            "format": REPORT_FORMAT,
            "items": len(CORPUS),
            "released": sum(1 for r in per_bill if r["status"] == "released"),
            "blocked_items": sum(1 for r in per_bill if r["status"] == "blocked"),
            "released_total": fmt(released_total),
            "approvals": {
                "requested": totals["requested"], "consumed": totals["consumed"], "invalidated": totals["invalidated"],
                "by_operation": dict(sorted(by_operation.items())),
                "routed_to_owner": totals["owner"], "routed_to_others": totals["others"],
                "owner_share": fmt(Decimal(totals["owner"]) / Decimal(totals["consumed"])) if totals["consumed"] else "0.00",
                "per_released_bill": fmt(Decimal(totals["consumed"]) / Decimal(len(elapsed))) if elapsed else "0.00",
                "wait_minutes": wait,
            },
            "held": held,
            "blocked": blocked,
            "release_classification": dict(sorted(classes.items())),
            "intake_to_release_minutes": {
                "count": len(ordered), "min": ordered[0], "max": ordered[-1], "total": sum(ordered),
                "mean": fmt(Decimal(sum(ordered)) / Decimal(len(ordered))), "median": fmt(Decimal(median)),
            } if ordered else {"count": 0},
            "simulated_span_minutes": self.clock.minutes(),
            "per_bill": per_bill,
            "ledger": self.ledger(),
        }

    def ledger(self) -> dict[str, Any]:
        """The invariants the corpus must leave: balanced books and reconciled subledgers."""
        c = self.c
        journals = c.ledger.journals()
        intents = c.payments.list()
        refs = [p["provider_ref"] for p in intents]
        ap, ret, stored, clearing = c.bills.ap_open_items(), c.bills.retainage_open_items(), c.bills.stored_material_items(), c.payments.clearing_items()
        return {
            "trial_balance_balanced": c.ledger.trial_balance()["balanced"],
            "journals_balanced": all(sum(money(ln["debit"]) for ln in j["lines"]) == sum(money(ln["credit"]) for ln in j["lines"]) for j in journals),
            "ap_reconciled": ap["reconciled"], "ap_open": ap["subledger_total"],
            "retainage_reconciled": ret["reconciled"], "retainage_payable": ret["subledger_total"],
            "stored_materials_reconciled": stored["reconciled"], "stored_materials": stored["subledger_total"],
            "provider_clearing_reconciled": clearing["reconciled"],
            "balances": {code: fmt(c.ledger.balance(code)) for code in ("1000", "1200", "1300", "2000", "2050", "5000")},
            "payment_intents": len(intents), "settled": sum(1 for p in intents if p["status"] == "settled"),
            "unique_provider_refs": len(set(refs)) == len(refs) == len(c.provider.transfers),
            "bills_paid": sum(1 for b in c.bills.list(project_id=self.pid) if b["status"] == "paid"),
            "bills_corrected": sum(1 for b in c.bills.list(project_id=self.pid) if b["status"] == "corrected"),
            "invoices_matched": sum(1 for i in self.intake.invoices(self.pid) if i["status"] == "matched"),
            "open_approvals": len(c.approvals.list(status="pending")) + len(c.approvals.list(status="granted")),
            "payment_policy_intact": self.policy.verify_chain()["ok"],
            "audit_chain_ok": c.audit.verify_chain()["ok"],
        }


def run_corpus() -> dict[str, Any]:
    return Corpus().run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m apps.cipher.tools.corpus", description="Run the 20-bill corpus and print its JSON metrics report.")
    parser.add_argument("--out", default=None, help="also write the JSON report to this file")
    args = parser.parse_args(argv)
    report = run_corpus()
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    ledger = report["ledger"]
    ok = all(ledger[k] for k in ("trial_balance_balanced", "journals_balanced", "ap_reconciled", "retainage_reconciled",
                                  "stored_materials_reconciled", "provider_clearing_reconciled", "unique_provider_refs", "audit_chain_ok"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
