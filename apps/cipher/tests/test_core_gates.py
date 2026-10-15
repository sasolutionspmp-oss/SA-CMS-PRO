"""Accounting-core decision gates (plan section 3 / section 13 decision 4).

The gates must report the native core truthfully.  Since the round-two core fixes
(scorecard ``cipher-core-gates/3``) the native core passes every hard gate, and
this module asserts that: all nine gates pass, no hard check fails, and the
candidate is scored.  Each of the eight gaps the previous scorecard reported is
probed directly against the core and must be closed.

A passing native run could also come from gates that cannot fail, so each former
gap is re-opened inside a test adapter and the gate must then fail exactly the
checks that gap breaks, printing the documented evidence.  The two open G8
advisories are checked against independent probes of the core.  The ERPNext
adapter must report ``not_run`` without touching anything, the weights must sum
to 100, and deliberately broken candidates must be disqualified.  That includes
candidates whose "refusals" are unrelated errors, crashing plugin paths,
unexercised probes or a broken reimbursement scenario.

Round three (``cipher-core-gates/4``) adds G6 checks for supplier-invoice binding and
governed payee changes and G9 checks for credit notes, credit memos, write-offs and
customer deposits (2400).  Each new control is probed directly against the core, and
re-opened in a test adapter so that the gate fails exactly the checks it guards; a
scenario the candidate cannot run fails as "not exercised", never passes.
"""
import contextlib
import datetime as dt
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import unittest
from decimal import ROUND_HALF_UP, Decimal
from unittest import mock

from apps.cipher.core.approvals import StaleApprovalError
from apps.cipher.core.db import OWNER_SECRET_ENV
from apps.cipher.core.ids import new_id, utcnow_iso
from apps.cipher.core.money import ZERO, D, allocate, fmt, money, total
from apps.cipher.domain import payments as payments_module
from apps.cipher.domain.bills import BillError
from apps.cipher.domain.ledger import RULE_VERSION
from apps.cipher.domain.payments import DestinationChangeError
from apps.cipher.domain.receivables import ReceivableError, ReceivableIneligible
from apps.cipher.service import Cipher, run_golden_fixture
from apps.cipher.tests.bill_helpers import approve_and_post_bill
from apps.cipher.tools import core_gates as cg
from apps.cipher.tools.core_gates import (
    ALLOCATION_CASES, ASSUMED_CRITERIA, ERPNEXT_UNAVAILABLE, G6_INVOICE_KEYS, G6_PAYEE_KEYS, G9_ADJUSTMENT_KEYS, GATE_IDS, REFUSAL_CONTROLS,
    REQUIRED_TRIGGERS, WEIGHTS, CoreGateError, ERPNextAdapter, NativeCipherAdapter, evaluate_candidate, run_gate, weights_total,
)

PROBED_PLUGINS = ("asset", "reimbursement", "labor")
TEST_OWNER_SECRET = "test-owner-secret-core-gates"
ENTITY = "S&A Solutions LLC (synthetic)"

# Hard checks per gate in cipher-core-gates/4 (G4 adds two per probed plugin).  Round three
# added 8 checks to G6 (6 -> 14) and 9 to G9 (4 -> 13); every earlier check is kept.
CHECKS_PER_GATE = {"G1": 22, "G2": 13, "G3": 12, "G4": 15, "G5": 5, "G6": 14, "G7": 14, "G8": 13, "G9": 13}
ROUND_THREE_KEYS = {"G6": set(G6_INVOICE_KEYS) | set(G6_PAYEE_KEYS), "G9": set(G9_ADJUSTMENT_KEYS)}
# The cipher-core-gates/3 check keys of G6 and G9, which must all still run.
EARLIER_KEYS = {
    "G6": {"g6.control", "g6.one_cent", "g6.changed_base", "g6.destination_verified", "g6.destination_raw", "g6.fresh_approval"},
    "G9": {"g9.ap", "g9.ar", "g9.employee_payable", "g9.trial_balance"},
}


@contextlib.contextmanager
def owner_secret(value):
    """Configure (or, with None, remove) CIPHER_OWNER_SECRET, restoring it afterwards."""
    previous = os.environ.get(OWNER_SECRET_ENV)
    if value is None:
        os.environ.pop(OWNER_SECRET_ENV, None)
    else:
        os.environ[OWNER_SECRET_ENV] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(OWNER_SECRET_ENV, None)
        else:
            os.environ[OWNER_SECRET_ENV] = previous


@contextlib.contextmanager
def without_triggers(adapter, *names):
    """Drop triggers for one statement and put them back exactly as they were, so a
    re-opened gap stays confined to the check that exercises it."""
    saved = {}
    for name in names:
        saved[name] = adapter.c.db.scalar("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,))
        adapter.c.db.execute(f"DROP TRIGGER IF EXISTS {name}")
    try:
        yield
    finally:
        for sql in saved.values():
            if sql:
                adapter.c.db.execute(sql)


# --------------------------------------------------------------------------- #
# Independent probes of the native core, one per former gap                   #
# --------------------------------------------------------------------------- #

def _post(c, period="P1", amount="100.00"):
    return c.ledger.post(period_id=period, description="gap probe", lines=[{"account": "5000", "debit": amount}, {"account": "2000", "credit": amount}],
                         source_type="test", source_id="gap-probe", source_version="1", posted_by="test")


def _fresh(period="P1"):
    c = Cipher()
    c.open_period(period, period, "2026-10-01", "2026-10-31", actor="test")
    return c


def gap_nonfinite_money() -> bool:
    accepted = 0
    for fn in (lambda: money("NaN"), lambda: money("sNaN"), lambda: money("Infinity"), lambda: money("-Infinity"),
               lambda: money(D("1.00") + D("NaN")), lambda: total(["1.00", "NaN"]), lambda: allocate("NaN", [1, 1])):
        try:
            fn()
            accepted += 1
        except Exception:
            pass
    return accepted > 0


def gap_unbounded_allocation() -> bool:
    for amount, weights in ALLOCATION_CASES:
        parts = allocate(amount, weights)
        weight_sum = sum(D(w) for w in weights)
        for part, w in zip(parts, weights):
            share = D(amount) * D(w) / weight_sum
            if part < 0 or abs(part - share) >= Decimal("0.01"):
                return True
    return False


def gap_insert_line_on_posted_journal() -> bool:
    c = _fresh()
    try:
        j = _post(c)
        try:
            c.db.execute("INSERT INTO journal_lines (id, journal_id, line_no, account_code, debit, credit, memo) VALUES (?,?,?,?,?,?,?)",
                         (new_id("jln"), j["id"], 99, "5000", "1.00", "0.00", "gap probe"))
        except sqlite3.DatabaseError:
            return False
        return len(c.ledger.journal(j["id"])["lines"]) == 3
    finally:
        c.db.close()


def gap_reopen_with_unrecorded_reference() -> bool:
    c = _fresh()
    try:
        c.close_period("P1", actor="test")
        try:
            c.ledger.reopen_period("P1", actor="test", approval_ref="apr_not_a_recorded_approval")
        except Exception:
            return False
        return c.ledger.period("P1")["status"] == "open"
    finally:
        c.db.close()


def gap_raw_unlock_of_locked_period() -> bool:
    c = _fresh()
    try:
        c.close_period("P1", actor="test")
        c.ledger.lock_period("P1", actor="test")
        try:
            c.db.execute("UPDATE periods SET status='open' WHERE id='P1'")
        except sqlite3.DatabaseError:
            return False
        return c.ledger.period("P1")["status"] == "open"
    finally:
        c.db.close()


class RestoreScenario:
    """A file-backed workspace with a sent prime bill (through the prime_bill.send
    approval, with the customer's ACH mandate on file) and a released supplier payment,
    copied before dispatch, dispatched, then copied several more times.  Used to probe
    the core's restore behavior directly (not through the gate adapter)."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="cipher-core-gates-gap-")
        self.opened = []
        c = self.live = self._track(Cipher(os.path.join(self.dir, "live.sqlite")))
        c.open_period("P1", "P1", "2026-10-01", "2026-10-31", actor="test")
        supplier = c.add_party(kind="supplier", name="Gap Probe Subcontractor", destination="ACH-SIM-GAP-1", actor="test")
        c.verify_destination(supplier["id"], destination="ACH-SIM-GAP-1", verified_by="test")
        customer = c.add_party(kind="customer", name="Gap Probe Owner Agency", actor="test")
        project = c.create_project(name="Gap probe project", entity="S&A Solutions LLC (synthetic)", budget="100000", customer_id=customer["id"], actor="test")
        cmt = c.commitments.create(project_id=project["id"], supplier_id=supplier["id"], title="Gap probe subcontract",
                                   sov_lines=[{"description": "Work", "amount": "50000"}], retainage_rate="0.10", actor="test")
        c.approve_and_execute("commitment.execute", cmt["id"], actor="test")
        line = c.commitments.get(cmt["id"])["sov"][0]["id"]
        bill = c.bills.certify(commitment_id=cmt["id"], period_id="P1", installed=[{"sov_line_id": line, "cumulative_installed": "10000"}], actor="test")
        approve_and_post_bill(c, bill["id"], approver="test-controller", poster="test-accountant", approver_role="controller")
        prime = c.receivables.certify(project_id=project["id"], period_id="P1", certified_cumulative="10000", retainage_rate="0.10", actor="test")
        c.approve_and_execute("prime_bill.approve", prime["id"], actor="test")
        c.approve_and_execute("prime_bill.send", prime["id"], actor="test")
        doc = c.evidence.register_document(project_id=project["id"], kind="ach_mandate", title="Gap probe ACH debit authorization", actor="test")
        rev = c.evidence.add_revision(document_id=doc["id"], content=b"gap probe ACH debit authorization", note="signed authorization", actor="test")
        c.receivables.record_mandate(customer_id=customer["id"], mandate_ref="MANDATE-SIM-GAP-1", evidence_hash=rev["content_hash"], actor="test")
        self.prime_id = prime["id"]
        c.approve_and_execute("payment.release", bill["id"], actor_role="treasury", actor="treasury")
        self.before_dispatch = c.snapshot(os.path.join(self.dir, "before-dispatch.sqlite"))
        c.dispatch_payments()
        self.copies = {name: c.snapshot(os.path.join(self.dir, f"copy-{name}.sqlite")) for name in ("mutate", "claim", "default", "first", "sibling")}

    def _track(self, c):
        self.opened.append(c)
        return c

    def restored(self, name_or_path):
        path = self.copies.get(name_or_path, name_or_path)
        return self._track(Cipher.open_restored(path, provider=self.live.provider))

    def close(self):
        for c in self.opened:
            try:
                c.db.close()
            except Exception:
                pass
        shutil.rmtree(self.dir, ignore_errors=True)

    @staticmethod
    def _claim(r, code, *, secret=TEST_OWNER_SECRET):
        with owner_secret(secret):
            r.claim_write_authority(approval_ref=code, actor="test-controller", reason="core gate probe", claim_code=code)

    def restored_copy_mutates(self) -> bool:
        r = self.restored("mutate")
        assert not r.db.has_write_authority()
        before = r.db.scalar("SELECT COUNT(*) FROM journals")
        for fn in (lambda: r.receivables.record_collection(prime_bill_id=self.prime_id, period_id="P1", amount="4500.00", fee="0", provider_ref="gap-rcv", actor="test"),
                   lambda: _post(r, amount="1.00")):
            try:
                fn()
            except Exception:
                pass
        return r.db.scalar("SELECT COUNT(*) FROM journals") > before

    def claim_without_valid_code_succeeds(self) -> bool:
        r = self.restored("claim")
        for code in ("apr_not_a_recorded_approval", ""):
            try:
                self._claim(r, code)
            except Exception:
                pass
        return r.db.has_write_authority()

    def claim_without_secret_succeeds(self) -> bool:
        r = self.restored("default")
        try:
            self._claim(r, "apr_not_a_recorded_approval", secret=None)
        except Exception:
            pass
        return r.db.has_write_authority()

    def sibling_copy_accepts_used_code(self) -> bool:
        first = self.restored("first")
        code = first.db.expected_claim_code(TEST_OWNER_SECRET)
        self._claim(first, code)
        assert first.db.has_write_authority()
        sibling = self.restored("sibling")
        try:
            self._claim(sibling, code)
        except Exception:
            pass
        return sibling.db.has_write_authority()

    def older_backup_resubmits(self) -> bool:
        old = self.restored(self.before_dispatch)
        self._claim(old, old.db.expected_claim_code(TEST_OWNER_SECRET))
        start = len(self.live.provider.submissions)
        old.complete_recovery(actor="test")
        try:
            old.dispatch_payments()
        except Exception:
            pass
        return len(self.live.provider.submissions) > start


# key -> (probe name, evidence fragment the gate prints while the gap is present)
FORMER_GAPS = {
    "g1.nonfinite_refused": ("nonfinite", "to_money('NaN') ACCEPTED, returning NaN"),
    "g1.allocation_bounded": ("allocation", "allocate 0.05 over 1:1:1:1:1:1:1 gives a part of -0.01"),
    "g3.insert_line_on_posted_refused": ("insert_line", "that journal is now Dr 101.00 / Cr 100.00 over 3 lines (fingerprint CHANGED)"),
    "g4.reopen_requires_recorded_approval": ("reopen_reference", "'apr_gate_unrecorded_reopen' (a recorded approval: False) was ACCEPTED"),
    "g4.raw_unlock_refused": ("raw_unlock", "raw UPDATE setting locked period G4-SVC back to open was ACCEPTED"),
    "g8.restored_copy_refuses_mutations": ("restored_mutation", "record_collection action for 4500.00 was ACCEPTED"),
    # cipher-core-gates/2 called this check g8.claim_requires_recorded_approval
    "g8.claim_requires_attestation": ("claim_attestation", "a fabricated credential 'apr_gate_unrecorded_claim' was ACCEPTED"),
    "g8.older_backup_no_resubmission": ("older_backup", "(1 resubmission(s))"),
}


def probe_core() -> dict[str, bool]:
    """Every direct probe: the eight former gaps (True = present) and the two
    write-authority claim scopes behind the G8 advisories (True = claim accepted)."""
    present = {
        "nonfinite": gap_nonfinite_money(),
        "allocation": gap_unbounded_allocation(),
        "insert_line": gap_insert_line_on_posted_journal(),
        "reopen_reference": gap_reopen_with_unrecorded_reference(),
        "raw_unlock": gap_raw_unlock_of_locked_period(),
    }
    scenario = RestoreScenario()
    try:
        present["restored_mutation"] = scenario.restored_copy_mutates()
        present["claim_attestation"] = scenario.claim_without_valid_code_succeeds()
        present["older_backup"] = scenario.older_backup_resubmits()
        present["default_config_claim"] = scenario.claim_without_secret_succeeds()
        present["sibling_claim"] = scenario.sibling_copy_accepts_used_code()
    finally:
        scenario.close()
    return present


# --------------------------------------------------------------------------- #
# Independent probes of the round-three controls (not through the adapter)     #
# --------------------------------------------------------------------------- #

class ProbeWorld:
    """A verified sheet-pile subcontractor and an owner agency on a cofferdam project, open
    period P1 (October 2026) and an executed 60,000 + 40,000 subcontract at 10% retainage.
    Cost codes are placeholders ("XX 10 00")."""

    def __init__(self):
        c = self.c = Cipher()
        c.open_period("P1", "P1", "2026-10-01", "2026-10-31", actor="test")
        sup = c.add_party(kind="supplier", name="Probe sheet pile subcontractor", destination="ACH-SIM-PROBE-0001", actor="test")
        self.supplier = c.verify_destination(sup["id"], destination="ACH-SIM-PROBE-0001", verified_by="test-bank-detail-maintainer")
        self.customer = c.add_party(kind="customer", name="Probe owner agency", actor="test")
        self.project = c.create_project(name="Probe cofferdam and dewatering", entity=ENTITY, budget="250000", customer_id=self.customer["id"], actor="test")
        self.pid = self.project["id"]
        cmt = c.commitments.create(project_id=self.pid, supplier_id=sup["id"], title="Probe sheet pile and dewatering subcontract",
                                   sov_lines=[{"description": "Sheet piling", "amount": "60000", "cost_code": "XX 10 00"},
                                              {"description": "Dewatering", "amount": "40000", "cost_code": "XX 20 00"}],
                                   retainage_rate="0.10", actor="test")
        c.approve_and_execute("commitment.execute", cmt["id"], actor="test")
        self.cid = cmt["id"]
        self.line = c.commitments.get(cmt["id"])["sov"][0]["id"]
        self._docs = 0

    def evidence(self, kind, label):
        self._docs += 1
        doc = self.c.evidence.register_document(project_id=self.pid, kind=kind, title=f"{label} ({self._docs})", actor="test")
        return self.c.evidence.add_revision(document_id=doc["id"], content=f"probe {kind} {self._docs}: {label}".encode(), note=label, actor="test")

    def posted_bill(self, cumulative):
        b = self.c.bills.certify(commitment_id=self.cid, period_id="P1", installed=[{"sov_line_id": self.line, "cumulative_installed": cumulative}], actor="test")
        approve_and_post_bill(self.c, b["id"], approver="test-controller", poster="test-accountant", approver_role="controller")
        return self.c.bills.get(b["id"])

    def journals(self):
        return self.c.db.scalar("SELECT COUNT(*) FROM journals")

    def assert_books(self, tc):
        c = self.c
        tc.assertTrue(c.ledger.trial_balance()["balanced"])
        tc.assertTrue(c.audit.verify_chain()["ok"])
        for label, rec in (("AP 2000", c.bills.ap_open_items()), ("AR 1100", c.receivables.ar_open_items()), ("deposits 2400", c.receivables.deposits_items()),
                           ("retainage 2050", c.bills.retainage_open_items()), ("retainage 1150", c.receivables.retainage_receivable_items())):
            tc.assertTrue(rec["reconciled"], (label, rec))


def credited_bill_release_pays_open_payable() -> bool:
    """Direct probe behind the G9 credited-bill advisory: after a 1500.00 credit note on an
    18000.00 bill, does payment.release create one intent for the 16500.00 open payable?"""
    w = ProbeWorld()
    c = w.c
    try:
        bill = w.posted_bill("20000")
        note = c.bills.prepare_credit_note(bill["id"], "1500.00", "supplier credit for rejected sheet piles",
                                           w.evidence("supplier_credit_note", "credit note SP-CN-9")["content_hash"], "test-accountant")
        c.approve_and_execute("bill.credit_note", note["id"], actor_role="accountant", actor="test-accountant", period_id="P1")
        try:
            c.approve_and_execute("payment.release", bill["id"], actor_role="treasury", actor="treasury")
        except (RuntimeError, sqlite3.DatabaseError):
            pass
        intents = [p for p in c.payments.list() if p["bill_id"] == bill["id"]]
        return len(intents) == 1 and intents[0]["amount"] == "16500.00"
    finally:
        c.db.close()


def _advisory(result, check_prefix):
    [adv] = [a for a in result["advisories"] if a["check"].startswith(check_prefix)]
    return adv


def close_checklist_reconciles_deposits() -> bool:
    """Direct probe behind the G9 advisory: does the golden fixture's close checklist for
    its open period carry a check naming customer deposits or account 2400?"""
    c = Cipher()
    try:
        fixture = run_golden_fixture(c)
        assert fixture["ar"]["reconciled"]
        checklist = c.plugin("close").checklist("2026-11")
        return any("2400" in f"{ch['check']} {ch['detail']}" or "customer deposit" in f"{ch['check']} {ch['detail']}".lower() for ch in checklist)
    finally:
        c.db.close()


# --------------------------------------------------------------------------- #
# Test adapters: each former gap re-opened                                     #
# --------------------------------------------------------------------------- #

class NonFiniteMoney(NativeCipherAdapter):
    """Money parsing that lets NaN, sNaN and Infinity through (floats and bools are
    still refused by the core)."""

    candidate = "gap_nonfinite_money"

    @staticmethod
    def _lenient(value):
        if isinstance(value, (float, bool)):
            return money(value)
        d = value if isinstance(value, Decimal) else Decimal(str(value))
        return d if not d.is_finite() else d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def to_money(self, value):
        return self._lenient(value)

    def add_money(self, a, b):
        return self._lenient(self._lenient(a) + self._lenient(b))

    def sum_money(self, values):
        return self._lenient(sum((self._lenient(v) for v in values), Decimal(0)))

    def allocate(self, amount, weights):
        amt = self._lenient(amount)
        return [amt for _ in weights] if not amt.is_finite() else allocate(amt, weights)


class ResidualOnFirstPart(NativeCipherAdapter):
    """Allocation that rounds each part and puts the whole residual on the first one."""

    candidate = "gap_unbounded_allocation"

    def allocate(self, amount, weights):
        amt = money(amount)
        ws = [D(w) for w in weights]
        parts = [money(amt * w / sum(ws)) for w in ws]
        parts[0] += amt - sum(parts)
        return parts


class UnsealedPostedJournal(NativeCipherAdapter):
    """The journal seal is missing when a privileged session adds a line to a posted journal."""

    candidate = "gap_unsealed_journal"

    def privileged_insert_line(self, journal_id):
        with without_triggers(self, "journal_lines_sealed"):
            super().privileged_insert_line(journal_id)


class UnverifiedReopenReference(NativeCipherAdapter):
    """A ledger reopen that takes any non-empty reference at face value."""

    candidate = "gap_unverified_reopen"

    def reopen_period(self, period_id, approval_ref):
        if approval_ref and not self.approval_exists(approval_ref):
            with without_triggers(self, "periods_reopen_requires_approval", "periods_reopen_logged"):
                self.raw_sql("UPDATE periods SET status='open', closed_at=NULL, closed_by=NULL WHERE id=?", (period_id,))
            return
        super().reopen_period(period_id, approval_ref)


class UnlockableLockedPeriod(NativeCipherAdapter):
    """No locked-period trigger when a privileged session unlocks a locked period."""

    candidate = "gap_raw_unlock"

    def privileged_unlock_period(self, period_id):
        with without_triggers(self, "periods_locked_immutable"):
            super().privileged_unlock_period(period_id)


class WritableRestoredCopy(NativeCipherAdapter):
    """Restored copies whose connection stays writable: write authority is checked only
    at the command boundary, as before the SQLite read-only guard existed."""

    candidate = "gap_writable_restored_copy"

    def open_restored(self, path):
        other = super().open_restored(path)
        other.c.db._refresh_suspended += 1  # keep the mode below until a claim decides it
        other.c.db._set_query_only(False)
        return other


class UnattestedClaim(NativeCipherAdapter):
    """A write-authority claim that never checks its credential."""

    candidate = "gap_unattested_claim"

    def claim_write_authority(self, credential):
        self.claim_write_authority_default_config(credential)


class RecoveryIgnoresQueuedIntents(NativeCipherAdapter):
    """Recovery that does not look queued intents up at the provider before the
    quarantine is lifted, so an older backup's queued intent is dispatched again."""

    candidate = "gap_queued_recovery"

    def open_restored(self, path):
        other = super().open_restored(path)
        other.c.payments._resolve_queued_after_restore = lambda provider, *, actor: ([], [])
        return other


# gate check key -> (adapter, every hard check the re-opened gap must fail)
REINTRODUCED = {
    "g1.nonfinite_refused": (NonFiniteMoney, {"g1.nonfinite_refused"}),
    "g1.allocation_bounded": (ResidualOnFirstPart, {"g1.allocation_bounded"}),
    "g3.insert_line_on_posted_refused": (UnsealedPostedJournal, {"g3.insert_line_on_posted_refused"}),
    "g4.reopen_requires_recorded_approval": (UnverifiedReopenReference, {"g4.reopen_requires_recorded_approval"}),
    "g4.raw_unlock_refused": (UnlockableLockedPeriod, {"g4.raw_unlock_refused"}),
    "g8.restored_copy_refuses_mutations": (WritableRestoredCopy, {"g8.restored_copy_refuses_mutations", "g8.restored_copy_refuses_privileged_writes"}),
    "g8.claim_requires_attestation": (UnattestedClaim, {"g8.claim_requires_attestation", "g8.claim_credential_single_use"}),
    "g8.older_backup_no_resubmission": (RecoveryIgnoresQueuedIntents, {"g8.older_backup_no_resubmission"}),
}


# --------------------------------------------------------------------------- #
# Round three: each new control re-opened                                     #
# --------------------------------------------------------------------------- #

class InvoiceBlindBillApproval(NativeCipherAdapter):
    """bill.approve that neither binds nor re-checks the supplier invoice its bill carries."""

    candidate = "gap_invoice_blind_bill_approval"

    def reset(self, path=None):
        super().reset(path)
        self.c.bills._supplier_invoice_binding = lambda b: None


class SelfVerifiedPayeeChange(NativeCipherAdapter):
    """No two-person rule on payee changes: the service compares no names and the schema
    trigger that repeats the rule is absent while a verification is written."""

    candidate = "gap_self_verified_payee_change"

    def record_destination_verification(self, change_id, *, verified_by):
        with mock.patch.object(payments_module, "_same_person", lambda a, b: False), without_triggers(self, "destination_changes_lifecycle"):
            super().record_destination_verification(change_id, verified_by=verified_by)

    def privileged_self_verify_destination_change(self, change_id):
        with without_triggers(self, "destination_changes_lifecycle"):
            super().privileged_self_verify_destination_change(change_id)


class PendingChangeApprovable(NativeCipherAdapter):
    """party.verify_destination may be requested for a change nobody has verified yet."""

    candidate = "gap_pending_change_approvable"

    def reset(self, path=None):
        super().reset(path)
        payments = self.c.payments
        original = payments._require_change_applies

        def relaxed(ch, party):
            if ch["status"] != "pending":
                original(ch, party)

        payments._require_change_applies = relaxed


class EvidenceBlindChangeCheck(NativeCipherAdapter):
    """payments no longer checks whether a change's verification record is still current."""

    candidate = "gap_evidence_blind_change_check"

    def reset(self, path=None):
        super().reset(path)
        self.c.payments._evidence_problem = lambda ch: None


class CreditNotesOffTheSubledger(NativeCipherAdapter):
    """The AP subledger (and the open payable that bounds a credit) ignores supplier credit notes."""

    candidate = "gap_credit_notes_off_subledger"

    def reset(self, path=None):
        super().reset(path)
        self.c.bills.credited = lambda bill_id: ZERO


class DepositApplicationsIgnored(NativeCipherAdapter):
    """The deposit subledger reads every deposit as wholly unapplied; the database still
    bounds an application by the deposit's unapplied balance."""

    candidate = "gap_deposit_applications_ignored"

    def reset(self, path=None):
        super().reset(path)
        receivables = self.c.receivables
        original = receivables.deposit

        def deposit(deposit_id):
            d = original(deposit_id)
            return dict(d, applied="0.00", unapplied=d["amount"] if d["reversal_journal_id"] is None else "0.00")

        receivables.deposit = deposit


# gate check key -> (adapter, gate, every hard check the re-opened control must fail, evidence the gate prints)
ROUND_THREE_REOPENED = {
    "g6.supplier_invoice_change": (InvoiceBlindBillApproval, "G6", {"g6.supplier_invoice_change", "g6.supplier_invoice_fresh_approval"},
                                   "posting under the earlier approval was ACCEPTED; status consumed; bill posted; journals 1 -> 2"),
    "g6.payee_change_two_person": (SelfVerifiedPayeeChange, "G6", {"g6.payee_change_two_person", "g6.payee_change_raw_self_verification"},
                                   "verification by the named requester (as ' Gate-Site-PM ') was ACCEPTED"),
    "g6.payee_change_requires_evidence": (PendingChangeApprovable, "G6", {"g6.payee_change_requires_evidence"},
                                          "with no independent verification yet was ACCEPTED; approvals recorded on it: 1"),
    "g9.credit_note_ap": (CreditNotesOffTheSubledger, "G9", {"g9.credit_note_ap", "g9.credit_note_bounded", "g9.adjusted_totals"},
                          "AP subledger 18000.00 = GL 2000 16500.00 (expected 16500.00)"),
    "g9.deposit_application": (DepositApplicationsIgnored, "G9", {"g9.deposit_application", "g9.adjusted_totals"},
                               "deposits 5000.00 = GL 2400 3000.00 (expected 3000.00)"),
}


class NoSupplierInvoiceIntake(NativeCipherAdapter):
    """A candidate without supplier-invoice intake: the G6 invoice scenario cannot run."""

    candidate = "broken_no_supplier_invoice_intake"

    def _ap_intake(self):
        raise cg.GateScenarioError("no supplier-invoice intake: the ap_intake module is not registered")


class BrokenDepositScenario(NativeCipherAdapter):
    candidate = "broken_deposit_scenario"

    def record_customer_deposit(self, *args, **kwargs):
        raise AttributeError("'Receivables' object has no attribute 'record_deposit'")


class UnrelatedCreditRefusal(NativeCipherAdapter):
    """A further credit note is refused, but by a closed period: not the open-amount bound."""

    candidate = "broken_unrelated_credit_refusal"

    def post_supplier_credit_note(self, bill_id, amount, *, period_id):
        if amount != cg.G9_CREDIT_NOTE:
            raise RuntimeError(f"PeriodNotOpen: period {period_id} is closed")
        return super().post_supplier_credit_note(bill_id, amount, period_id=period_id)


class NoCloseChecklist(NativeCipherAdapter):
    candidate = "broken_no_close_checklist"

    def close_checklist(self, period_id):
        return None


# --------------------------------------------------------------------------- #
# Deliberately broken candidates                                               #
# --------------------------------------------------------------------------- #

class SkipsBalanceCheck(NativeCipherAdapter):
    """A candidate with no balance check at any layer: its posting path writes journal rows
    without validating them, and its schema has no journal seal.  (The native schema seals
    journals and refuses an unbalanced one by itself, so the seal is removed here too.)"""

    candidate = "broken_skips_balance_check"

    def reset(self, path=None):
        super().reset(path)
        for trigger in ("journals_declare_line_count", "journal_lines_sealed"):
            self.c.db.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    def post_journal(self, *, period_id, lines, source_id, description="core gate journal"):
        jid = new_id("jrn")
        with self.c.db.transaction() as conn:
            conn.execute(
                "INSERT INTO journals (id, period_id, posted_at, description, source_type, source_id, source_version, rule_version, posted_by) VALUES (?,?,?,?,?,?,?,?,?)",
                (jid, period_id, utcnow_iso(), description, "core_gate", source_id, "1", RULE_VERSION, "gate"),
            )
            for n, ln in enumerate(lines, start=1):
                conn.execute(
                    "INSERT INTO journal_lines (id, journal_id, line_no, account_code, debit, credit, memo) VALUES (?,?,?,?,?,?,?)",
                    (new_id("jln"), jid, n, ln["account"], fmt(ln.get("debit", "0")), fmt(ln.get("credit", "0")), ""),
                )
        return jid


class AllowsJournalUpdate(NativeCipherAdapter):
    """A candidate whose ledger immutability is only a convention: a privileged
    SQL session can rewrite or delete posted rows."""

    candidate = "broken_allows_update"

    def raw_sql(self, sql, params=()):
        for trigger in ("journals_no_update", "journals_no_delete", "journal_lines_no_update", "journal_lines_no_delete"):
            self.c.db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        super().raw_sql(sql, params)


class MisspelledTamperSql(AllowsJournalUpdate):
    """Immutability triggers dropped AND the tamper statements misspelled: every statement errors,
    but never because a control refused it."""

    candidate = "broken_misspelled_tamper"
    _TAMPER_SQL = {
        "update_amount": "UPDATE journal_lines SET debitt='9999.00' WHERE journal_id=? AND line_no=1",
        "update_description": "UPDATE journal SET description='x' WHERE id=?",
        "delete_lines": "DELETE FROM journal_line WHERE journal_id=?",
        "delete_journal": "DELETE FROM journal WHERE id=?",
        "unlink_reversal": "UPDATE journal SET reversal_of=NULL WHERE id=?",
    }


class MalformedInsertWithoutPeriodTriggers(NativeCipherAdapter):
    """Period-open triggers dropped and the raw INSERT malformed."""

    candidate = "broken_period_triggers"

    def privileged_insert_journal(self, period_id):
        for trigger in ("journals_period_open", "journal_lines_period_open"):
            self.c.db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        self.raw_sql("INSERT INTO journals (id, period_idd) VALUES (?, ?)", (new_id("jrn"), period_id))


class PluginProbeOnMissingSubject(NativeCipherAdapter):
    """The asset probe is pointed at a subject that does not exist."""

    candidate = "broken_missing_subject"

    def _prepare_asset_probe(self, assets, project, operation):
        probe = super()._prepare_asset_probe(assets, project, operation)
        probe["attempt"] = self._execute_into(operation, "does-not-exist", probe["period"])
        return probe


class PluginPathsCrash(NativeCipherAdapter):
    """Every plugin posting path crashes with a programming error."""

    candidate = "broken_plugin_type_error"

    def _execute_into(self, operation, subject_id, period_id):
        def crash():
            raise TypeError("approve_and_execute() got an unexpected keyword argument 'period'")
        return crash


class PluginSetupFails(NativeCipherAdapter):
    """Every plugin probe fails while preparing its subjects."""

    candidate = "broken_plugin_setup"

    def _broken(self, *args, **kwargs):
        raise RuntimeError("sibling module API moved")

    _prepare_asset_probe = _prepare_reimbursement_probe = _prepare_labor_probe = _broken


class BrokenReimbursementScenario(NativeCipherAdapter):
    candidate = "broken_reimbursement_scenario"

    def add_employee_reimbursement(self, *args, **kwargs):
        raise AttributeError("'Plugin' object has no attribute 'submit_claim'")


class TruncatedAuditExport(NativeCipherAdapter):
    """An export that drops its last audit entry and adjusts its own chain count to match."""

    candidate = "broken_truncated_export"

    def audit_export(self):
        export = super().audit_export()
        entries = export["audit"]["entries"][:-1]
        export["audit"] = dict(export["audit"], entries=entries, chain=dict(export["audit"]["chain"], entries=len(entries)))
        return export


class WildcardMarkers(NativeCipherAdapter):
    candidate = "broken_wildcard_markers"

    def refusal_markers(self):
        return {control: ".*" for control in REFUSAL_CONTROLS}


class WorkspaceUnavailable(NativeCipherAdapter):
    candidate = "broken_workspace"

    def reset(self, path=None):
        raise RuntimeError("workspace storage unavailable")


class TypeErrorOnPost(NativeCipherAdapter):
    """A broken adapter: its posting path crashes with a programming error, which must
    never be mistaken for the ledger refusing an invalid journal."""

    candidate = "broken_type_error"

    def post_journal(self, **kwargs):
        raise TypeError("post_journal() got an unexpected keyword argument")


class RecordingUnavailable(ERPNextAdapter):
    def __init__(self):
        self.calls = []

    def reset(self, path=None):
        self.calls.append("reset")
        raise AssertionError("an unavailable adapter must not be driven")


def _walk(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)
    else:
        yield value


def _gate(result, gate_id):
    return next(g for g in result["gates"] if g["gate"] == gate_id)


def _text(gate):
    return "\n".join(gate["evidence"])


def _fails(result):
    return "\n".join(e for g in result["gates"] for e in g["evidence"] if e.startswith("FAIL"))


# --------------------------------------------------------------------------- #
# Native core                                                                  #
# --------------------------------------------------------------------------- #

class NativeGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.secret_before = os.environ.get(OWNER_SECRET_ENV)
        cls.adapter = NativeCipherAdapter()
        cls.result = evaluate_candidate(cls.adapter)
        cls.secret_after = os.environ.get(OWNER_SECRET_ENV)
        cls.gates = {g["gate"]: g for g in cls.result["gates"]}
        cls.failed = set(cls.result["failed_checks"])
        cls.probes = probe_core()

    def evidence(self, gate_id):
        return _text(self.gates[gate_id])

    def test_native_core_passes_every_hard_gate(self):
        self.assertEqual([g["gate"] for g in self.result["gates"]], list(GATE_IDS))
        self.assertEqual(self.result["hard_gate_summary"], {"pass": 9, "fail": 0, "not_run": 0}, _fails(self.result))
        self.assertEqual(self.result["failed_checks"], [], _fails(self.result))
        self.assertEqual(self.result["disqualified_by"], [])
        self.assertEqual(self.result["status"], "scored")
        for gate_id in GATE_IDS:
            with self.subTest(gate=gate_id):
                self.assertEqual(self.gates[gate_id]["status"], "pass", self.evidence(gate_id))
        self.assertEqual(self.result["hard_check_summary"]["failed"], 0)

    def test_every_hard_check_ran(self):
        """No check may silently disappear from a gate: the per-gate counts are pinned."""
        probed = [name for name in PROBED_PLUGINS if f"plugin path {name}." in self.evidence("G4")]
        expected = dict(CHECKS_PER_GATE, G4=CHECKS_PER_GATE["G4"] + 2 * len(probed))
        self.assertEqual({g: self.gates[g]["checks"]["total"] for g in GATE_IDS}, expected)
        self.assertEqual(self.result["hard_check_summary"]["total"], sum(expected.values()))
        self.assertEqual(self.result["hard_check_summary"]["passed"], sum(expected.values()))
        for gate_id in GATE_IDS:
            keys = self.gates[gate_id]["check_keys"]
            with self.subTest(gate=gate_id):
                self.assertEqual(len(keys), len(set(keys)), keys)  # every check has its own stable key
                self.assertEqual(len(keys), self.gates[gate_id]["checks"]["total"])
        # round three kept every earlier G6/G9 check and added its own, in order
        for gate_id in ("G6", "G9"):
            keys = self.gates[gate_id]["check_keys"]
            with self.subTest(gate=gate_id):
                self.assertEqual(set(keys), EARLIER_KEYS[gate_id] | ROUND_THREE_KEYS[gate_id])
                self.assertEqual(set(keys[:len(EARLIER_KEYS[gate_id])]), EARLIER_KEYS[gate_id])

    def test_each_former_gap_is_closed_in_the_core(self):
        for key, (probe, fragment) in FORMER_GAPS.items():
            with self.subTest(check=key):
                self.assertFalse(self.probes[probe], f"the core has the {key} gap again")
                self.assertNotIn(key, self.failed, self.evidence(key.split(".")[0].upper()))
                self.assertNotIn(fragment, self.evidence(key.split(".")[0].upper()))

    def test_the_native_core_is_scored_from_the_executed_checks(self):
        rows = {row["criterion"]: row for row in self.result["scores"]}
        self.assertEqual(set(rows), set(WEIGHTS))
        hard = self.result["hard_check_summary"]
        advisories = self.result["advisories"]
        passed = hard["passed"] + sum(1 for adv in advisories if adv["status"] == "pass")
        executed = hard["total"] + len(advisories)
        control = (Decimal(5) * passed / executed).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.assertEqual(rows["accounting_control_fit"]["score"], f"{control:f}")
        self.assertTrue(rows["accounting_control_fit"]["rationale"].startswith(f"COMPUTED from the gates: {passed} of {executed} executed control checks passed"))
        expected = Decimal(0)
        for row in rows.values():
            self.assertEqual(row["basis"], "computed" if row["criterion"] == "accounting_control_fit" else "ASSUMPTION")
            expected += Decimal(row["score"]) * row["weight"] / Decimal(100)
        self.assertEqual(self.result["weighted_total"], f"{expected.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f}")
        if self.result["open_advisories"]:
            self.assertLess(control, Decimal("5.00"))  # open advisories lower the control-fit score

    def test_status_follows_the_hard_gates(self):
        failing = [g["gate"] for g in self.result["gates"] if g["checks"]["failed"]]
        self.assertEqual(self.result["disqualified_by"], failing)
        self.assertEqual(self.result["hard_gate_summary"]["fail"], len(failing))
        self.assertEqual(self.result["hard_check_summary"]["failed"], len(self.result["failed_checks"]))

    def test_gate_result_shape(self):
        for g in self.result["gates"]:
            self.assertTrue({"gate", "title", "status", "evidence", "checks", "failed_checks", "advisories"} <= set(g))
            self.assertIn(g["status"], ("pass", "fail", "not_run"))
            self.assertEqual(g["status"] == "pass", g["checks"]["failed"] == 0 and g["checks"]["total"] > 0)
            self.assertEqual(len(g["failed_checks"]), g["checks"]["failed"])
            self.assertTrue(g["evidence"])
            for line in g["evidence"]:
                self.assertTrue(line.startswith(("PASS: ", "FAIL: ", "INFO: ")), line)

    def test_evidence_carries_concrete_numbers_and_refusal_reasons(self):
        g1, g2, g3, g4, g7, g8 = (self.evidence(g) for g in ("G1", "G2", "G3", "G4", "G7", "G8"))
        self.assertIn("0.1 + 0.2 = 0.30 exactly", g1)
        self.assertIn("33.34 + 33.33 + 33.33 = 100.00", g1)
        self.assertIn("0.01 + 0.01 + 0.01 + 0.01 + 0.01 + 0.00 + 0.00 = 0.05", g1)
        self.assertIn("2.675 -> 2.68", g1)
        self.assertIn("non-finite amounts are refused by the money control (0 of 7 accepted, 0 refused for another reason)", g1)
        self.assertIn("to_money('sNaN') refused (MoneyError: non-finite monetary value is not allowed", g1)
        self.assertIn("debits 100.00, credits 99.99", g2)
        self.assertIn("journals 1 -> 1", g2)
        self.assertIn("(Dr 5000 100.00, Cr 2000 99.99) in open period G2 refused (IntegrityError: journal does not balance: its sealed lines must carry equal debits and credits)", g2)
        self.assertIn("holds fewer lines than its sealed line count", g2)
        self.assertIn("UPDATE journal_lines SET debit=9999.00 refused (IntegrityError: posted journal lines are immutable)", g3)
        self.assertRegex(g3, r"PASS: the correction went through the governed path: reversal \S+ carries approval apr_\w+ \(recorded: True, status consumed\)")
        self.assertIn("refused (IntegrityError: posted journals are immutable: the journal already holds its sealed line count); "
                      "that journal is now Dr 100.00 / Cr 100.00 over 2 lines (fingerprint unchanged)", g3)
        self.assertIn("period G4-SVC closed holding 1 journal; bill of 18000.00", g4)
        self.assertIn("service path: posting the business-approved bill into the closed period refused (PeriodNotOpen: period G4-SVC is closed); journals 1 -> 1", g4)
        self.assertIn("raw INSERT of a journal header into the locked period refused (IntegrityError: period is not open for posting)", g4)
        self.assertIn("raw UPDATE setting locked period G4-SVC back to open refused (IntegrityError: locked periods are immutable); the period is locked", g4)
        self.assertIn("privileged path: a raw UPDATE reopening closed period G4-REOPEN citing 'apr_gate_unrecorded_reopen' refused "
                      "(IntegrityError: reopening a closed period requires a consumed reopen_period approval", g4)
        self.assertIn("recorded reopens of G4-REOPEN 1 -> 1", g4)
        self.assertIn("conflicts", self.evidence("G5"))
        self.assertIn("27000.00 -> 27000.01", self.evidence("G6"))
        self.assertIn("110000.00", self.evidence("G6"))
        self.assertIn(f"{len(REQUIRED_TRIGGERS)} of {len(REQUIRED_TRIGGERS)} required control triggers", g7)
        self.assertRegex(g7, r"the export holds every audit row: (\d+) exported, chain count \1, \1 rows in the audit log")
        self.assertIn("record_collection action for 4500.00 refused (WriteAuthorityError: write refused: this workspace connection is read-only", g8)
        self.assertIn("switching the read-only guard off from that session refused (WriteAuthorityError: PRAGMA query_only is managed by the write-authority controls", g8)
        self.assertIn("a fabricated credential 'apr_gate_unrecorded_claim' refused (WriteAuthorityError: claiming write authority requires a valid owner claim code", g8)
        self.assertIn("credential verified True) gives write authority True", g8)
        self.assertIn("provider transfers 1 -> 1, submissions 1 -> 1 (no resubmission)", g8)
        self.assertIn("(intent statuses now accepted)", g8)
        self.assertIn("(0 resubmission(s))", g8)
        self.assertIn("AP: open-bill subledger 18000.00 = GL 2000 18000.00", self.evidence("G9"))
        self.assertIn("AR: open prime-bill subledger 54000.00 = GL 1100 54000.00", self.evidence("G9"))

    def test_round_three_g6_evidence(self):
        g6 = self.evidence("G6")
        self.assertIn("PASS: supplier invoice GATE-SI-0001 for 9000.00 (due 2026-11-14) was matched to bill ", g6)
        self.assertIn("the supplier then reissued it (version 2, due 2026-12-15): posting under the earlier approval was refused (BillIneligible: bill 2 (", g6)
        self.assertIn("was revised to version 2 after it was attached", g6)
        self.assertIn("status invalidated; bill approved; journals 1 -> 1", g6)
        self.assertIn("PASS: control case: re-matching the reissued invoice and granting fresh bill.approve let a separate accountant post the bill (posted; journals 1 -> 2); "
                      "it carries invoice version 2 due 2026-12-15 (hash matches the invoice record: True)", g6)
        self.assertIn("verification by the named requester (as ' Gate-Site-PM ') refused (DestinationChangeError: 'Gate-Site-PM' requested this destination change, "
                      "so cannot also verify it; the two-person rule", g6)
        self.assertIn("verification by the login that recorded the request (as 'GATE-AP-CLERK') refused (DestinationChangeError: 'GATE-AP-CLERK' recorded the request", g6)
        self.assertIn("the change stays pending; destination version 5 -> 5", g6)
        self.assertIn("PASS: privileged path: a raw UPDATE marking a change verified by its own requester (trusted channel, current evidence used once) refused "
                      "(IntegrityError: payee destination changes move only pending -> evidenced (a verifier other than the requester", g6)
        self.assertRegex(g6, r"PASS: requesting party\.verify_destination for a change with no independent verification yet refused \(DestinationChangeError: "
                             r"destination change dch_\w+ has no verification evidence yet;.*approvals recorded on it: 0; the change stays pending")
        self.assertRegex(g6, r"PASS: a party\.verify_destination approval granted on an independently verified change is refused once its verification record "
                             r"gains a newer revision \(DestinationChangeStale: .*\); status invalidated; destination version 5 -> 5")
        self.assertIn("verified by gate-external-accountant executes under party.verify_destination: change executed, "
                      "destination ACH-SIM-GATE-FINAL v5 -> ACH-SIM-GATE-GOVERNED v6", g6)
        self.assertRegex(g6, r"PASS: a 9000\.00 release granted before the governed change is refused \(ApprovalNotGranted: approval apr_\w+ is invalidated, not granted\); "
                             r"status invalidated; intents on the bill 0 -> 0; a fresh approval releases 9000\.00 to ACH-SIM-GATE-GOVERNED v6")

    def test_round_three_g9_evidence(self):
        g9 = self.evidence("G9")
        self.assertIn("PASS: supplier credit note 1500.00 on the 18000.00 bill posts [('2000', '1500.00', '0.00'), ('5000', '0.00', '1500.00')]; "
                      "AP subledger 16500.00 = GL 2000 16500.00 (expected 16500.00)", g9)
        self.assertIn("PASS: a further credit note of 16500.01, a cent above the 16500.00 still open, refused (BillError: credit 16500.01 exceeds what is open on bill 2: "
                      "open payable 16500.00", g9)
        self.assertIn("AP stays 16500.00 = GL 16500.00", g9)
        self.assertIn("PASS: credit memo 1000.00 on the 54000.00 progress bill posts [('4000', '1000.00', '0.00'), ('1100', '0.00', '1000.00')]; "
                      "AR subledger 53000.00 = GL 1100 53000.00 (expected 53000.00)", g9)
        self.assertIn("PASS: customer deposit 5000.00 by check: unapplied-deposit subledger 5000.00 = GL 2400 5000.00 on the project (workspace 5000.00 = 5000.00)", g9)
        self.assertIn("PASS: applying 2000.00 of the deposit to the progress bill posts [('2400', '2000.00', '0.00'), ('1100', '0.00', '2000.00')]; "
                      "deposits 3000.00 = GL 2400 3000.00 (expected 3000.00); AR 51000.00 = GL 1100 51000.00 (expected 51000.00)", g9)
        self.assertIn("PASS: applying 3000.01, a cent above the 3000.00 unapplied, refused (ReceivableError: application 3000.01 exceeds the 3000.00 unapplied on deposit", g9)
        self.assertIn("deposits stay 3000.00 = GL 2400 3000.00", g9)
        self.assertRegex(g9, r"PASS: writing 100\.00 off the golden progress bill, which is not 90 days past due, refused \(ReceivableIneligible: prime bill 1 is 0 days "
                             r"past due on \d{4}-\d{2}-\d{2} \(due \d{4}-\d{2}-\d{2}\); only a receivable at least 90 days past due can be written off\); "
                             r"journals 13 -> 13; GL 1100 stays 51000\.00")
        self.assertRegex(g9, r"PASS: a 9000\.00 progress bill 100 days past due \(due \d{4}-\d{2}-\d{2}\): writing 4000\.00 off posts "
                             r"\[\('6100', '4000\.00', '0\.00'\), \('1100', '0\.00', '4000\.00'\)\]; AR subledger 5000\.00 = GL 1100 5000\.00 on its project "
                             r"\(expected 5000\.00\); bad debt 6100 0\.00 -> 4000\.00")
        self.assertIn("PASS: workspace after the adjustments: AP 16500.00 = 16500.00, AR 56000.00 = 56000.00 (expected 56000.00), customer deposits 3000.00 = 3000.00; "
                      "trial balance Dr 306734.56 = Cr 306734.56 over 15 journals", g9)
        self.assertIn("INFO: after the adjustments: customer deposits 2400 3000.00, bad debt 6100 4000.00, contract revenue 4000 69000.00, subcontract cost 5000 43500.00", g9)

    def test_g9_credited_bill_advisory_matches_a_direct_probe_of_the_release(self):
        adv = _advisory(self.result, "a credited supplier bill is released")
        self.assertEqual(adv["gate"], "G9")
        pays = credited_bill_release_pays_open_payable()
        self.assertEqual(adv["status"], "pass" if pays else "open", adv["observed"])
        if not pays:
            self.assertIn("releasing the credited bill (amount due 18000.00, open payable 16500.00 after the 1500.00 credit note) was refused (IntegrityError: "
                          "a payment release for a bill carrying a posted supplier credit note must be for exactly its open payable", adv["observed"])
            self.assertIn("; intents on the bill: 0 - the credited bill cannot be paid through the service until the release binds the open payable", adv["observed"])

    def test_g9_advisory_matches_a_direct_probe_of_the_close_checklist(self):
        adv = _advisory(self.result, "the period-close checklist")
        self.assertEqual((adv["gate"], adv["check"]), ("G9", "the period-close checklist reconciles customer deposits (2400)"))
        covered = close_checklist_reconciles_deposits()
        self.assertEqual(adv["status"], "pass" if covered else "open", adv["observed"])
        if not covered:
            self.assertRegex(adv["observed"], r"^none of the \d+ checks the close checklist runs for 2026-11 names customer deposits or account 2400, "
                                              r"so a period can close while 2400 is unreconciled \(2400 stands at 3000\.00;")

    def test_plugin_paths_have_positive_controls_and_refuse_closed_periods(self):
        info = next(e for e in self.gates["G4"]["evidence"] if e.startswith("INFO: registered plugins:"))
        registered = info.split(";")[0].removeprefix("INFO: registered plugins: ").split(", ")
        probed = [name for name in PROBED_PLUGINS if f"plugin path {name}." in self.evidence("G4")]
        for name in PROBED_PLUGINS:
            if name not in registered:
                continue
            with self.subTest(plugin=name):
                self.assertIn(name, probed)
                lines = [e for e in self.gates["G4"]["evidence"] if f"plugin path {name}." in e]
                self.assertEqual(len(lines), 2, lines)
                self.assertTrue(lines[0].startswith("PASS: control case:") and " posted; journals " in lines[0], lines[0])
                self.assertTrue(lines[1].startswith("PASS: ") and "refused (PeriodNotOpen: period G4-" in lines[1], lines[1])

    def test_workspaces_are_released_and_the_drill_cleans_up(self):
        self.assertIsNone(self.adapter.c)
        self.assertIn("temporary workspace removed after the drill: True", self.evidence("G8"))
        self.assertEqual(self.secret_after, self.secret_before)  # the drill's owner secret is never left configured

    def test_g5_advisory_attributes_transfers_correctly(self):
        adv = next(a for a in self.result["advisories"] if a["gate"] == "G5")
        self.assertIn("1 is the bill's first, legitimate release", adv["observed"])
        self.assertEqual(self.result["open_advisories"], sum(1 for a in self.result["advisories"] if a["status"] == "open"))

    def test_g8_advisories_match_direct_probes_of_the_claim(self):
        g8 = [a for a in self.result["advisories"] if a["gate"] == "G8"]
        self.assertEqual(len(g8), 2, g8)
        default, sibling = g8
        self.assertIn("even in the default configuration", default["check"])
        self.assertIn("cannot authorize a sibling copy", sibling["check"])
        for adv, probe in ((default, "default_config_claim"), (sibling, "sibling_claim")):
            with self.subTest(advisory=adv["check"]):
                self.assertEqual(adv["status"], "open" if self.probes[probe] else "pass", adv["observed"])
                if self.probes[probe]:
                    self.assertIn("was ACCEPTED; effective write authority afterwards True", adv["observed"])

    def test_result_has_no_binary_floats(self):
        self.assertFalse([v for v in _walk(self.result) if isinstance(v, float)])
        json.dumps(self.result)  # serializable as is


class ReintroducedGapTests(unittest.TestCase):
    """The native core passes, so prove the gates still fail: re-open each former gap in a
    test adapter and the gate must fail exactly the checks that gap breaks."""

    def test_each_reintroduced_gap_fails_its_gate_with_the_documented_evidence(self):
        secret_before = os.environ.get(OWNER_SECRET_ENV)
        self.assertEqual(set(REINTRODUCED), set(FORMER_GAPS))
        for key, (adapter_cls, expected) in REINTRODUCED.items():
            gate_id = key.split(".")[0].upper()
            with self.subTest(check=key, adapter=adapter_cls.candidate):
                g = run_gate(gate_id, adapter_cls())
                self.assertEqual(g["status"], "fail", _text(g))
                self.assertEqual(set(g["failed_checks"]), expected, _text(g))
                self.assertIn(FORMER_GAPS[key][1], _text(g))
                self.assertNotIn(f"{gate_id.lower()}.aborted", g["failed_checks"])
        self.assertEqual(os.environ.get(OWNER_SECRET_ENV), secret_before)


class RoundThreeReopenedTests(unittest.TestCase):
    """Each round-three control re-opened in a test adapter: the gate fails exactly the
    checks that control guards, keeps running every other check, and prints the evidence."""

    def test_each_reopened_control_fails_exactly_its_checks(self):
        for key, (adapter_cls, gate_id, expected, fragment) in ROUND_THREE_REOPENED.items():
            with self.subTest(check=key, adapter=adapter_cls.candidate):
                g = run_gate(gate_id, adapter_cls())
                self.assertEqual(g["status"], "fail", _text(g))
                self.assertIn(key, expected)
                self.assertEqual(set(g["failed_checks"]), expected, _text(g))
                self.assertIn(fragment, _text(g))
                self.assertNotIn(f"{gate_id.lower()}.aborted", g["failed_checks"])
                self.assertEqual(set(g["check_keys"]), EARLIER_KEYS[gate_id] | ROUND_THREE_KEYS[gate_id])  # nothing skipped

    def test_the_payee_approval_also_binds_evidence_currency_in_its_manifest(self):
        """Defense in depth: without payments' own evidence check, the party.verify_destination
        manifest still binds whether the evidence revision is current, so the stale approval is
        invalidated at execution and G6 keeps passing."""
        g = run_gate("G6", EvidenceBlindChangeCheck())
        self.assertEqual((g["status"], g["failed_checks"]), ("pass", []), _text(g))
        self.assertRegex(_text(g), r"PASS: a party\.verify_destination approval granted on an independently verified change is refused once its verification "
                                   r"record gains a newer revision \(StaleApprovalError: approval apr_\w+ no longer matches the subject: bindings\); status invalidated")

    def test_the_database_bound_on_a_deposit_application_counts_as_the_open_amount_control(self):
        g = run_gate("G9", DepositApplicationsIgnored())
        self.assertNotIn("g9.deposit_application_bounded", g["failed_checks"], _text(g))
        self.assertIn("PASS: applying 3000.01, a cent above the 3000.00 unapplied, refused (IntegrityError: a deposit application cannot exceed the unapplied "
                      "balance of its deposit)", _text(g))

    def test_a_refusal_for_an_unrelated_reason_is_not_the_open_amount_bound(self):
        g = run_gate("G9", UnrelatedCreditRefusal())
        self.assertEqual(g["failed_checks"], ["g9.credit_note_bounded"], _text(g))
        self.assertIn("a cent above the 16500.00 still open, was not refused by the expected control: it failed for an unrelated reason "
                      "(RuntimeError: PeriodNotOpen: period 2026-11 is closed)", _text(g))

    def test_a_candidate_without_supplier_invoice_intake_fails_the_invoice_checks_as_not_exercised(self):
        g = run_gate("G6", NoSupplierInvoiceIntake())
        self.assertEqual(g["status"], "fail")
        self.assertEqual(set(g["failed_checks"]), set(G6_INVOICE_KEYS), _text(g))
        self.assertIn("FAIL: the supplier-invoice binding scenario did not complete, so this check was not exercised "
                      "(GateScenarioError: no supplier-invoice intake: the ap_intake module is not registered)", _text(g))
        self.assertEqual(g["checks"], {"passed": 12, "failed": 2, "total": 14})  # the payee-change checks still run and pass

    def test_a_broken_deposit_scenario_fails_g9_instead_of_reconciling_nothing(self):
        g = run_gate("G9", BrokenDepositScenario())
        self.assertEqual(g["status"], "fail")
        self.assertEqual(set(g["failed_checks"]), {"g9.deposit_recorded", "g9.deposit_application", "g9.deposit_application_bounded",
                                                   "g9.write_off_requires_age", "g9.write_off_ar", "g9.adjusted_totals"}, _text(g))
        self.assertIn("did not complete, so this check was not exercised (AttributeError: 'Receivables' object has no attribute 'record_deposit')", _text(g))
        for key in ("g9.ap", "g9.ar", "g9.credit_note_ap", "g9.credit_note_bounded", "g9.credit_memo_ar"):
            self.assertNotIn(key, g["failed_checks"])

    def test_without_a_close_checklist_the_deposit_advisory_is_open(self):
        g = run_gate("G9", NoCloseChecklist())
        self.assertEqual(g["status"], "pass", _text(g))
        adv = _advisory(g, "the period-close checklist")
        self.assertEqual(adv["status"], "open")
        self.assertIn("the candidate has no period-close checklist", adv["observed"])

    def test_the_new_refusal_markers_are_declared_and_specific(self):
        patterns = cg._markers(NativeCipherAdapter(), REFUSAL_CONTROLS)  # raises if any matches empty or unrelated errors
        self.assertEqual(len(patterns), 10)
        markers = NativeCipherAdapter().refusal_markers()
        for control, reason in ((cg.CONTROL_OPEN_AMOUNT, "PeriodNotOpen: period 2026-11 is closed"),
                                (cg.CONTROL_WRITE_OFF_AGE, "ReceivableError: write-off 100.00 exceeds the 90.00 open"),
                                (cg.CONTROL_INDEPENDENT_VERIFICATION, "DestinationChangeError: verification channel must be one of ...")):
            with self.subTest(control=control):
                self.assertIsNone(re.search(markers[control], reason, re.IGNORECASE))


# --------------------------------------------------------------------------- #
# Round three: the controls probed directly against the core                  #
# --------------------------------------------------------------------------- #

class RoundThreeCoreProbeTests(unittest.TestCase):
    """The behavior the new G6 and G9 checks report, reproduced on Cipher directly."""

    def test_bill_grant_and_posting_are_explicit_distinct_adapter_acts(self):
        adapter = NativeCipherAdapter()
        adapter.reset()
        self.addCleanup(adapter.close)
        adapter.open_period("SPLIT", "2026-10-01", "2026-10-31")
        project = adapter.setup_project()
        commitment = adapter.setup_commitment(project)
        bill = adapter.certify_bill(commitment["commitment_id"], "SPLIT", commitment["line_ids"][0], "10000")
        before = adapter.journal_count()
        approval = adapter.request_and_grant("bill.approve", bill["bill_id"], actor_role="accountant")
        self.assertEqual(adapter.bill_status(bill["bill_id"]), "approved")
        self.assertEqual(adapter.approval_status(approval), "granted")
        self.assertEqual(adapter.journal_count(), before)
        posted = adapter.post_bill(bill["bill_id"], actor="gate-accountant", period_id="SPLIT")
        self.assertEqual(posted["result"]["status"], "posted")
        self.assertEqual(adapter.approval_status(approval), "consumed")
        self.assertEqual(adapter.journal_count(), before + 1)
        self.assertNotEqual(adapter.c.approvals.get(approval)["approver"], adapter.c.ledger.journals()[-1]["posted_by"])

    def test_a_reissued_supplier_invoice_invalidates_the_bill_approval_granted_before(self):
        w = ProbeWorld()
        c = w.c
        ap_intake = c.plugin("ap_intake")
        bill = c.bills.certify(commitment_id=w.cid, period_id="P1", installed=[{"sov_line_id": w.line, "cumulative_installed": "30000"}], actor="test")
        self.assertEqual(bill["amount_due"], "27000.00")
        pdf = w.evidence("supplier_invoice", "Probe supplier invoice SP-7001")
        inv = ap_intake.receive_invoice(w.supplier["id"], "SP-7001", "2026-10-15", "27000.00", pdf["content_hash"], "probe-ap-clerk", project_id=w.pid, commitment_id=w.cid)
        self.assertEqual((inv["status"], inv["due_date"], inv["version"]), ("received", "2026-11-14", 1))
        self.assertEqual(ap_intake.match(inv["id"], "probe-ap-clerk")["status"], "matched")
        c.approve_and_execute("ap_intake.match_invoice", inv["id"], actor_role="accountant", actor="test-accountant")
        approval = c.request_approval("bill.approve", bill["id"], actor_role="accountant", requested_by="test")
        self.assertEqual(approval["manifest"]["bindings"]["supplier_invoice"]["due_date"], "2026-11-14")
        c.approve(approval["id"], approver="test-controller", approver_role="controller")
        ap_intake.revise_invoice(inv["id"], "probe-ap-clerk", reason="supplier reissued the invoice with a corrected due date", due_date="2026-12-15")
        before = w.journals()
        with self.assertRaises(StaleApprovalError):
            c.post_bill(bill["id"], actor="test-accountant")
        self.assertEqual((c.approvals.get(approval["id"])["status"], c.bills.get(bill["id"])["status"], w.journals()), ("invalidated", "approved", before))
        self.assertTrue(any("revised to version 2" in p for p in c.bills.supplier_invoice_state(bill["id"])["problems"]))
        # the stale approval is final: re-match and approve afresh
        self.assertEqual(ap_intake.match(inv["id"], "probe-ap-clerk")["status"], "matched")
        c.approve_and_execute("ap_intake.match_invoice", inv["id"], actor_role="accountant", actor="test-accountant")
        approve_and_post_bill(c, bill["id"], approver="test-controller", poster="test-accountant", approver_role="controller")
        posted = c.bills.get(bill["id"])
        self.assertEqual((posted["status"], posted["due_date"], posted["supplier_invoice_hash"]), ("posted", "2026-12-15", ap_intake.invoice(inv["id"])["content_hash"]))
        ap = c.bills.ap_open_items(w.pid)
        self.assertEqual((ap["subledger_total"], ap["control_balance"], ap["reconciled"]), ("27000.00", "27000.00", True))
        w.assert_books(self)

    def test_a_payee_change_needs_a_verifier_other_than_its_requester(self):
        w = ProbeWorld()
        c, p = w.c, w.c.payments
        change = p.request_destination_change(w.supplier["id"], "ACH-SIM-PROBE-0002", "probe-site-pm", "supplier letter announcing a new bank account", "probe-ap-clerk")
        for verifier in (" Probe-Site-PM ", "PROBE-AP-CLERK", "probe-site-pm"):
            with self.subTest(verifier=verifier), self.assertRaises(DestinationChangeError):
                p.record_verification_evidence(change["id"], "call-back to number on file", verifier,
                                               w.evidence("destination_verification", f"call-back by {verifier}")["content_hash"], "probe-bank-admin")
        with self.assertRaises(DestinationChangeError):  # nothing to approve before an independent verification
            c.request_approval("party.verify_destination", change["id"], actor_role="bank_admin", requested_by="test")
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM approvals WHERE subject_id=?", (change["id"],)), 0)
        rev = w.evidence("destination_verification", "raw self-verification")
        with self.assertRaises(sqlite3.IntegrityError):  # the schema repeats the two-person rule
            c.db.execute("UPDATE destination_changes SET status='evidenced', version=version+1, channel='call-back to number on file', verified_by=requested_by, "
                         "evidence_hash=?, evidence_revision_id=?, evidence_recorded_by='raw', evidenced_at=? WHERE id=?",
                         (rev["content_hash"], rev["id"], utcnow_iso(), change["id"]))
        self.assertEqual(p.destination_change(change["id"])["status"], "pending")
        bill = w.posted_bill("10000")
        release = c.request_approval("payment.release", bill["id"], actor_role="treasury", requested_by="test")
        c.approve(release["id"], approver="test-owner")
        p.record_verification_evidence(change["id"], "call-back to number on file", "probe-external-accountant",
                                       w.evidence("destination_verification", "independent call-back")["content_hash"], "probe-bank-admin")
        c.approve_and_execute("party.verify_destination", change["id"], actor_role="bank_admin", actor="probe-bank-admin")
        party = c.party(w.supplier["id"])
        self.assertEqual((party["destination"], party["destination_version"]), ("ACH-SIM-PROBE-0002", 3))
        self.assertEqual(c.approvals.get(release["id"])["status"], "invalidated")
        fresh = c.approve_and_execute("payment.release", bill["id"], actor_role="treasury", actor="treasury").result
        intent = c.payments.get(fresh["intent"])
        self.assertEqual((intent["amount"], intent["destination"], intent["destination_version"]), ("9000.00", "ACH-SIM-PROBE-0002", 3))
        w.assert_books(self)

    def test_credits_write_offs_and_deposits_keep_every_subledger_reconciled(self):
        w = ProbeWorld()
        c, r = w.c, w.c.receivables
        bill = w.posted_bill("20000")  # 18,000.00 payable
        note = c.bills.prepare_credit_note(bill["id"], "1500.00", "supplier credit for rejected sheet piles",
                                           w.evidence("supplier_credit_note", "credit note SP-CN-1")["content_hash"], "test-accountant")
        with self.assertRaises(BillError):  # a second draft may not reserve more than is left open
            c.bills.prepare_credit_note(bill["id"], "16500.01", "over-credit", w.evidence("supplier_credit_note", "credit note SP-CN-2")["content_hash"], "test-accountant")
        c.approve_and_execute("bill.credit_note", note["id"], actor_role="accountant", actor="test-accountant", period_id="P1")
        ap = c.bills.ap_open_items(w.pid)
        self.assertEqual((ap["subledger_total"], ap["control_balance"], ap["reconciled"]), ("16500.00", "16500.00", True))
        self.assertEqual(c.bills.open_payable(bill["id"]), D("16500.00"))

        today = r.today()
        c.open_period("P0", "P0", (today - dt.timedelta(days=170)).isoformat(), (today - dt.timedelta(days=100)).isoformat(), actor="test")
        prime = r.certify(project_id=w.pid, period_id="P0", certified_cumulative="60000", retainage_rate="0.10", actor="test",
                          invoice_date=(today - dt.timedelta(days=130)).isoformat())
        c.approve_and_execute("prime_bill.approve", prime["id"], actor_role="accountant", actor="test-accountant")
        prime = r.get(prime["id"])
        self.assertEqual((prime["amount_due"], prime["open"], prime["due_date"]), ("54000.00", "54000.00", (today - dt.timedelta(days=100)).isoformat()))
        memo = r.prepare_credit_memo(prime["id"], "1000.00", "agreed concession on a pay item", w.evidence("credit_memo_evidence", "concession")["content_hash"], "test-accountant")
        c.approve_and_execute("prime_bill.credit_memo", memo["id"], actor_role="accountant", actor="test-accountant", period_id="P1")
        deposit = r.record_deposit(w.customer["id"], w.pid, "5000.00", "PROBE-DEP-0001", "check", "test-treasury", period_id="P1")
        draft = r.prepare_deposit_application(deposit["id"], prime["id"], "2000.00", "test-accountant")
        c.approve_and_execute("receivable.apply_deposit", draft["id"], actor_role="accountant", actor="test-accountant", period_id="P1")
        with self.assertRaises(ReceivableError):
            r.prepare_deposit_application(deposit["id"], prime["id"], "3000.01", "test-accountant")
        written = r.prepare_write_off(prime["id"], "4000.00", "customer insolvent for this portion", "test-controller")
        c.approve_and_execute("receivable.write_off", written["id"], actor_role="controller", actor="test-controller", period_id="P1")
        self.assertEqual(r.get(prime["id"])["open"], "47000.00")  # 54,000 - 1,000 memo - 2,000 applied - 4,000 written off
        ar, dep = r.ar_open_items(w.pid), r.deposits_items(w.pid)
        self.assertEqual((ar["subledger_total"], ar["control_balance"], ar["reconciled"]), ("47000.00", "47000.00", True))
        self.assertEqual((dep["subledger_total"], dep["control_balance"], dep["reconciled"]), ("3000.00", "3000.00", True))
        self.assertEqual({code: fmt(c.ledger.balance(code)) for code in ("2000", "1100", "2400", "6100", "4000", "5000")},
                         {"2000": "16500.00", "1100": "47000.00", "2400": "3000.00", "6100": "4000.00", "4000": "59000.00", "5000": "18500.00"})
        w.assert_books(self)

    def test_a_receivable_not_yet_ninety_days_past_due_is_not_written_off(self):
        w = ProbeWorld()
        c, r = w.c, w.c.receivables
        prime = r.certify(project_id=w.pid, period_id="P1", certified_cumulative="10000", retainage_rate="0.10", actor="test")
        c.approve_and_execute("prime_bill.approve", prime["id"], actor_role="accountant", actor="test-accountant")
        with self.assertRaises(ReceivableIneligible):
            r.prepare_write_off(prime["id"], "100.00", "too early", "test-controller")
        self.assertEqual((r.write_offs(), fmt(c.ledger.balance("6100")), r.get(prime["id"])["open"]), ([], "0.00", "9000.00"))
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# ERPNext                                                                      #
# --------------------------------------------------------------------------- #

class ERPNextAdapterTests(unittest.TestCase):
    def test_every_gate_reports_not_run_without_raising(self):
        result = evaluate_candidate(ERPNextAdapter())
        self.assertEqual(result["status"], "not_evaluated")
        self.assertFalse(result["available"])
        self.assertEqual(result["availability"], ERPNEXT_UNAVAILABLE)
        self.assertIn("not provisioned", result["availability"])
        self.assertEqual([g["status"] for g in result["gates"]], ["not_run"] * len(GATE_IDS))
        for g in result["gates"]:
            self.assertIn("isolated container stack", g["evidence"][0])
        self.assertIsNone(result["scores"])
        self.assertIsNone(result["weighted_total"])
        self.assertEqual(result["hard_gate_summary"], {"pass": 0, "fail": 0, "not_run": 9})

    def test_unavailable_adapter_is_never_driven(self):
        adapter = RecordingUnavailable()
        self.assertEqual(run_gate("G2", adapter)["status"], "not_run")
        self.assertEqual(adapter.calls, [])

    def test_operations_are_explicitly_unimplemented(self):
        with self.assertRaises(NotImplementedError):
            ERPNextAdapter().reset()
        with self.assertRaises(NotImplementedError):
            ERPNextAdapter().post_journal(period_id="P1", lines=[], source_id="x")
        with self.assertRaises(NotImplementedError):
            ERPNextAdapter().claim_write_authority("x")
        with self.assertRaises(NotImplementedError):
            ERPNextAdapter().privileged_insert_raw_journal("P1", [], None)
        self.assertEqual(ERPNextAdapter().refusal_markers(), {})


# --------------------------------------------------------------------------- #
# Broken candidates                                                            #
# --------------------------------------------------------------------------- #

class BrokenAdapterTests(unittest.TestCase):
    def assertFailedWith(self, gate, keys, fragment=None):
        self.assertEqual(gate["status"], "fail", _text(gate))
        for key in keys:
            self.assertIn(key, gate["failed_checks"], _text(gate))
        if fragment:
            self.assertIn(fragment, _text(gate))

    def test_adapter_that_skips_the_balance_check_is_disqualified(self):
        result = evaluate_candidate(SkipsBalanceCheck())
        self.assertEqual(result["status"], "disqualified")
        self.assertIn("G2", result["disqualified_by"])
        self.assertIsNone(result["scores"])
        g2 = _gate(result, "G2")
        self.assertTrue(any(e.startswith("FAIL: unbalanced journal (debits 100.00, credits 99.99)") for e in g2["evidence"]), g2["evidence"])
        self.assertFailedWith(g2, ["g2.invalid.1", "g2.raw_header_only_refused", "g2.raw_unbalanced_refused", "g2.all_balanced"],
                              "privileged path: a raw journal of 2 lines that does not balance (Dr 5000 100.00, Cr 2000 99.99) in open period G2 was ACCEPTED")

    def test_adapter_that_allows_an_update_fails_g3(self):
        result = evaluate_candidate(AllowsJournalUpdate())
        self.assertEqual(result["status"], "disqualified")
        self.assertIn("G3", result["disqualified_by"])
        self.assertIsNone(result["scores"])
        self.assertFailedWith(_gate(result, "G3"), [f"g3.tamper.{action}" for action in ("update_amount", "update_description", "delete_lines", "delete_journal")],
                              "privileged raw SQL on a posted journal: UPDATE journal_lines SET debit=9999.00 was ACCEPTED")

    def test_a_foreign_key_error_is_not_counted_as_immutability(self):
        class DeleteHeaderFirst(AllowsJournalUpdate):
            """Without the delete trigger, deleting a header that still has lines is stopped by
            the foreign key, which is not the immutability control."""

            candidate = "broken_fk_only"

            def privileged_tamper(self, action, target_id):
                super().privileged_tamper("delete_journal" if action == "delete_lines" else action, target_id)

        g3 = run_gate("G3", DeleteHeaderFirst())
        self.assertFailedWith(g3, ["g3.tamper.delete_lines"], "failed for an unrelated reason (IntegrityError: FOREIGN KEY constraint failed)")

    def test_malformed_tamper_sql_is_not_counted_as_a_refusal(self):
        g3 = run_gate("G3", MisspelledTamperSql())
        self.assertFailedWith(g3, ["g3.tamper.update_amount", "g3.tamper.delete_journal", "g3.unlink_refused"],
                              "was not refused by the expected control: it failed for an unrelated reason (OperationalError: no such column: debitt)")

    def test_malformed_raw_insert_is_not_counted_as_a_period_lock(self):
        g4 = run_gate("G4", MalformedInsertWithoutPeriodTriggers())
        self.assertFailedWith(g4, ["g4.raw_header_closed", "g4.raw_header_locked"], "table journals has no column named period_idd")
        # With the period triggers gone, the raw line INSERT onto the closed period's posted
        # journal is still refused, by the journal seal: an expected (immutability) control.
        self.assertNotIn("g4.raw_line_closed", g4["failed_checks"], _text(g4))
        self.assertIn("raw INSERT of a line onto the closed period's journal refused (IntegrityError: posted journals are immutable: "
                      "the journal already holds its sealed line count)", _text(g4))

    def test_plugin_probe_on_a_missing_subject_fails(self):
        g4 = run_gate("G4", PluginProbeOnMissingSubject())
        if "plugin path asset." not in _text(g4):
            self.skipTest("asset plugin not registered")
        self.assertFailedWith(g4, ["g4.plugin.asset.refused"], "unknown depreciation run does-not-exist")

    def test_crashing_plugin_paths_fail_instead_of_passing(self):
        g4 = run_gate("G4", PluginPathsCrash())
        probed = [name for name in PROBED_PLUGINS if f"plugin path {name}." in _text(g4)]
        if not probed:
            self.skipTest("no probed plugin registered")
        self.assertFailedWith(g4, [f"g4.plugin.{n}.{k}" for n in probed for k in ("control", "refused")], "crashed with a programming error (TypeError")

    def test_registered_plugin_whose_probe_cannot_be_prepared_fails(self):
        g4 = run_gate("G4", PluginSetupFails())
        probed = [name for name in PROBED_PLUGINS if f"plugin path {name}." in _text(g4)]
        if not probed:
            self.skipTest("no probed plugin registered")
        self.assertFailedWith(g4, [f"g4.plugin.{n}.exercised" for n in probed], "is registered but was not exercised: preparing its subjects failed (RuntimeError: sibling module API moved)")

    def test_broken_reimbursement_scenario_fails_g9(self):
        g9 = run_gate("G9", BrokenReimbursementScenario())
        self.assertFailedWith(g9, ["g9.employee_scenario"], "employee reimbursement scenario failed (AttributeError")
        self.assertNotIn("g9.ap", g9["failed_checks"])  # AP and AR are still reconciled and reported

    def test_consistently_truncated_audit_export_fails_g7(self):
        g7 = run_gate("G7", TruncatedAuditExport())
        self.assertFailedWith(g7, ["g7.chain_recomputed"])
        self.assertRegex(_text(g7), r"(\d+) exported, chain count \1, (\d+) rows in the audit log")

    def test_wildcard_refusal_markers_are_rejected(self):
        g3 = run_gate("G3", WildcardMarkers())
        self.assertFailedWith(g3, ["g3.aborted"], "gate aborted by CoreGateError")

    def test_gate_errors_are_reported_as_failures(self):
        g = run_gate("G1", WorkspaceUnavailable())
        self.assertEqual(g["status"], "fail")
        self.assertTrue(any("gate aborted by RuntimeError: workspace storage unavailable" in e for e in g["evidence"]))

    def test_programming_errors_are_never_counted_as_refusals(self):
        g = run_gate("G2", TypeErrorOnPost())
        self.assertEqual(g["status"], "fail")
        self.assertEqual(g["checks"]["passed"], 0)
        self.assertTrue(any("gate aborted by TypeError" in e for e in g["evidence"]))


# --------------------------------------------------------------------------- #
# Scorecard and CLI                                                            #
# --------------------------------------------------------------------------- #

class ScorecardTests(unittest.TestCase):
    def test_weights_sum_to_100(self):
        self.assertEqual(weights_total(), 100)
        self.assertEqual(WEIGHTS, {"accounting_control_fit": 35, "aec_fit": 20, "maintainability_upgrades": 20, "ownership_licensing": 15, "delivery_cost": 10})

    def test_unknown_gate_is_rejected(self):
        with self.assertRaises(CoreGateError):
            run_gate("G99", NativeCipherAdapter())

    def test_score_values_are_validated(self):
        self.assertEqual(cg._score("4.5", "aec_fit"), Decimal("4.50"))
        self.assertEqual(cg._score(3, "aec_fit"), Decimal("3.00"))
        for bad in (6, -1, 4.5, True, "four", "NaN", "sNaN", "Infinity", Decimal("NaN")):
            with self.subTest(value=bad), self.assertRaises(CoreGateError):
                cg._score(bad, "aec_fit")

    def test_assumed_scores_must_be_labeled(self):
        class Unlabeled(NativeCipherAdapter):
            def assumed_scores(self):
                return {c: (3, "a guess") for c in ASSUMED_CRITERIA}

        def trivial(adapter, recorder):
            recorder.check(True, "stub")

        with mock.patch.dict(cg.GATES, {g: trivial for g in GATE_IDS}):
            with self.assertRaises(CoreGateError):
                evaluate_candidate(Unlabeled())
            scored = evaluate_candidate(NativeCipherAdapter())
        self.assertEqual(scored["status"], "scored")
        rows = {row["criterion"]: row for row in scored["scores"]}
        self.assertEqual(rows["accounting_control_fit"]["score"], "5.00")
        for criterion in ASSUMED_CRITERIA:
            self.assertTrue(rows[criterion]["rationale"].startswith("ASSUMPTION"))
        # 5*35 + 4*20 + 3*20 + 4*15 + 2*10 = 395 -> 3.95 of 5 -> 79.00%
        self.assertEqual(scored["weighted_total"], "3.95")
        self.assertEqual(scored["weighted_percent"], "79.00")

    def test_scorecard_and_cli_report_the_native_result(self):
        out_dir = tempfile.mkdtemp(prefix="cipher-core-gates-test-")
        try:
            out_path = os.path.join(out_dir, "scorecard.json")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = cg.main(["--out", out_path])
            printed = json.loads(buffer.getvalue())
            with open(out_path, encoding="utf-8") as fh:
                written = json.load(fh)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
        native = written["candidates"][0]
        self.assertTrue(written["native_passes_all_hard_gates"], native["failed_checks"])
        self.assertEqual(code, 0)
        self.assertEqual(written["version"], "cipher-core-gates/4")
        self.assertEqual(native["hard_check_summary"]["failed"], 0)
        self.assertEqual([a["gate"] for a in native["advisories"]], ["G5", "G8", "G8", "G9", "G9"])
        self.assertEqual(printed["weights_total"], 100)
        self.assertEqual([c["candidate"] for c in written["candidates"]], ["native_cipher", "erpnext"])
        self.assertEqual([c["status"] for c in written["candidates"]], ["scored", "not_evaluated"])
        self.assertEqual(written["native_failed_checks"], [])
        self.assertEqual([g["gate"] for g in written["hard_gates"]], list(GATE_IDS))
        self.assertTrue(written["does_not_prove"])
        self.assertIn("ASSUMPTIONS", written["decision_note"])
        self.assertIn("only native_cipher was scored", written["decision_note"])
        self.assertIsNotNone(native["weighted_total"])

    def test_cli_exits_zero_when_every_hard_gate_passes(self):
        def passing(adapter, recorder):
            recorder.check(True, "stub pass")

        buffer = io.StringIO()
        with mock.patch.dict(cg.GATES, {g: passing for g in GATE_IDS}), contextlib.redirect_stdout(buffer):
            code = cg.main([])
        self.assertEqual(code, 0)
        printed = json.loads(buffer.getvalue())
        self.assertTrue(printed["native_passes_all_hard_gates"])
        self.assertEqual(printed["candidates"][0]["status"], "scored")
        self.assertIn("ASSUMPTIONS", printed["decision_note"])

    def test_cli_exits_nonzero_when_the_native_core_fails_a_gate(self):
        def passing(adapter, recorder):
            recorder.check(True, "stub pass")

        def failing(adapter, recorder):
            recorder.check(False, "stub failure", key="g3.stub")

        gates = {g: passing for g in GATE_IDS}
        gates["G3"] = failing
        buffer = io.StringIO()
        with mock.patch.dict(cg.GATES, gates), contextlib.redirect_stdout(buffer):
            code = cg.main([])
        self.assertEqual(code, 1)
        printed = json.loads(buffer.getvalue())
        self.assertFalse(printed["native_passes_all_hard_gates"])
        self.assertEqual(printed["candidates"][0]["status"], "disqualified")
        self.assertEqual(printed["candidates"][0]["disqualified_by"], ["G3"])
        self.assertEqual(printed["native_failed_checks"], ["g3.stub"])
        self.assertIn("No foundation can be selected", printed["decision_note"])


if __name__ == "__main__":
    unittest.main()
