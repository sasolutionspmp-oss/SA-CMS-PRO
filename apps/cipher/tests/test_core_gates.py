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
"""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from decimal import ROUND_HALF_UP, Decimal
from unittest import mock

from apps.cipher.core.db import OWNER_SECRET_ENV
from apps.cipher.core.ids import new_id, utcnow_iso
from apps.cipher.core.money import D, allocate, fmt, money, total
from apps.cipher.domain.ledger import RULE_VERSION
from apps.cipher.service import Cipher
from apps.cipher.tools import core_gates as cg
from apps.cipher.tools.core_gates import (
    ALLOCATION_CASES, ASSUMED_CRITERIA, ERPNEXT_UNAVAILABLE, GATE_IDS, REFUSAL_CONTROLS, REQUIRED_TRIGGERS, WEIGHTS, CoreGateError, ERPNextAdapter,
    NativeCipherAdapter, evaluate_candidate, run_gate, weights_total,
)

PROBED_PLUGINS = ("asset", "reimbursement", "labor")
TEST_OWNER_SECRET = "test-owner-secret-core-gates"

# Hard checks per gate in cipher-core-gates/3 (G4 adds two per probed plugin).
CHECKS_PER_GATE = {"G1": 22, "G2": 13, "G3": 12, "G4": 15, "G5": 5, "G6": 6, "G7": 14, "G8": 13, "G9": 4}


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
    the core's restore behaviour directly (not through the gate adapter)."""

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
        c.approve_and_execute("bill.approve", bill["id"], actor="test")
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
        self.assertIn("service path: executing the granted bill approval into the closed period refused (PeriodNotOpen: period G4-SVC is closed); journals 1 -> 1", g4)
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
        self.assertIn("cannot authorise a sibling copy", sibling["check"])
        for adv, probe in ((default, "default_config_claim"), (sibling, "sibling_claim")):
            with self.subTest(advisory=adv["check"]):
                self.assertEqual(adv["status"], "open" if self.probes[probe] else "pass", adv["observed"])
                if self.probes[probe]:
                    self.assertIn("was ACCEPTED; effective write authority afterwards True", adv["observed"])

    def test_result_has_no_binary_floats(self):
        self.assertFalse([v for v in _walk(self.result) if isinstance(v, float)])
        json.dumps(self.result)  # serialisable as is


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

    def test_assumed_scores_must_be_labelled(self):
        class Unlabelled(NativeCipherAdapter):
            def assumed_scores(self):
                return {c: (3, "a guess") for c in ASSUMED_CRITERIA}

        def trivial(adapter, recorder):
            recorder.check(True, "stub")

        with mock.patch.dict(cg.GATES, {g: trivial for g in GATE_IDS}):
            with self.assertRaises(CoreGateError):
                evaluate_candidate(Unlabelled())
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
        self.assertEqual(written["version"], "cipher-core-gates/3")
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
