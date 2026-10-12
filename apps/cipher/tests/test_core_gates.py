"""Accounting-core decision gates (plan section 3 / section 13 decision 4).

The gates must report the native core truthfully.  Each documented native-core gap
is probed directly against the core here, and the gate must fail exactly the
checks whose gap is present.  Nothing outside those gaps may fail.  A test-only
adapter that simulates the core fixes must pass every hard gate, which shows the
gates can be passed.  The ERPNext adapter must report ``not_run`` without touching
anything, the weights must sum to 100, and deliberately broken candidates must be
disqualified.  That includes candidates whose "refusals" are unrelated errors,
crashing plugin paths, unexercised probes or a broken reimbursement scenario.
"""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from unittest import mock

from apps.cipher.core.approvals import build_manifest
from apps.cipher.core.db import WriteAuthorityError
from apps.cipher.core.ids import new_id, utcnow_iso
from apps.cipher.core.money import D, MoneyError, allocate, fmt, money, total
from apps.cipher.domain.ledger import RULE_VERSION, LedgerError
from apps.cipher.service import Cipher
from apps.cipher.tools import core_gates as cg
from apps.cipher.tools.core_gates import (
    ALLOCATION_CASES, ASSUMED_CRITERIA, ERPNEXT_UNAVAILABLE, GATE_IDS, REFUSAL_CONTROLS, WEIGHTS, CoreGateError, ERPNextAdapter,
    NativeCipherAdapter, build_scorecard, evaluate_candidate, run_gate, weights_total,
)

PROBED_PLUGINS = ("asset", "reimbursement", "labor")


# --------------------------------------------------------------------------- #
# Independent probes of the native core, one per documented gap               #
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
    """A file-backed workspace with a sent prime bill and a released supplier payment,
    copied before dispatch, dispatched, then copied twice more.  Used to probe the
    core's restore behaviour directly (not through the gate adapter)."""

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
        c.receivables.send(prime["id"], actor="test")
        self.prime_id = prime["id"]
        c.approve_and_execute("payment.release", bill["id"], actor_role="treasury", actor="treasury")
        self.before_dispatch = c.snapshot(os.path.join(self.dir, "before-dispatch.sqlite"))
        c.dispatch_payments()
        self.copy_a = c.snapshot(os.path.join(self.dir, "copy-a.sqlite"))
        self.copy_b = c.snapshot(os.path.join(self.dir, "copy-b.sqlite"))

    def _track(self, c):
        self.opened.append(c)
        return c

    def restored(self, path):
        return self._track(Cipher.open_restored(path, provider=self.live.provider))

    def close(self):
        for c in self.opened:
            try:
                c.db.close()
            except Exception:
                pass
        shutil.rmtree(self.dir, ignore_errors=True)

    def restored_copy_mutates(self) -> bool:
        r = self.restored(self.copy_a)
        assert not r.db.has_write_authority()
        accepted = 0
        for fn in (lambda: r.receivables.record_collection(prime_bill_id=self.prime_id, period_id="P1", amount="4500.00", fee="0", provider_ref="gap-rcv", actor="test"),
                   lambda: _post(r, amount="1.00")):
            try:
                fn()
                accepted += 1
            except Exception:
                pass
        return accepted > 0

    def claim_with_unrecorded_reference(self) -> bool:
        r = self.restored(self.copy_b)
        try:
            r.claim_write_authority(approval_ref="apr_not_a_recorded_approval", actor="test")
        except Exception:
            return False
        return r.db.has_write_authority()

    def older_backup_resubmits(self) -> bool:
        old = self.restored(self.before_dispatch)
        ws = old.db.workspace()
        manifest = build_manifest(operation="workspace.claim_write_authority", subject_type="workspace", subject_id=ws["workspace_id"], actor_role="owner",
                                  bindings={"authority_epoch": ws["authority_epoch"], "recovery_epoch": ws["recovery_epoch"]})
        ap = old.approvals.request(manifest, requested_by="test")
        old.approvals.grant(ap["id"], approver="test-controller")
        old.approvals.consume(ap["id"], current_manifest=manifest, consumer="test-controller")
        old.claim_write_authority(approval_ref=ap["id"], actor="test")
        start = len(self.live.provider.submissions)
        old.complete_recovery(actor="test")
        try:
            old.dispatch_payments()
        except Exception:
            pass
        return len(self.live.provider.submissions) > start


# key -> (probe name, evidence fragment the gate must print while the gap is present)
CORE_GAPS = {
    "g1.nonfinite_refused": ("nonfinite", "to_money('NaN') ACCEPTED, returning NaN"),
    "g1.allocation_bounded": ("allocation", "allocate 0.05 over 1:1:1:1:1:1:1 gives a part of -0.01"),
    "g3.insert_line_on_posted_refused": ("insert_line", "that journal is now Dr 101.00 / Cr 100.00 over 3 lines (fingerprint CHANGED)"),
    "g4.reopen_requires_recorded_approval": ("reopen_reference", "'apr_gate_unrecorded_reopen' (a recorded approval: False) was ACCEPTED"),
    "g4.raw_unlock_refused": ("raw_unlock", "raw UPDATE setting locked period G4-SVC back to open was ACCEPTED"),
    "g8.restored_copy_refuses_mutations": ("restored_mutation", "record_collection action for 4500.00 was ACCEPTED"),
    "g8.claim_requires_recorded_approval": ("claim_reference", "'apr_gate_unrecorded_claim' (a recorded approval: False) was ACCEPTED"),
    "g8.older_backup_no_resubmission": ("older_backup", "(1 resubmission(s))"),
}


def probe_core_gaps() -> dict[str, bool]:
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
        present["claim_reference"] = scenario.claim_with_unrecorded_reference()
        present["older_backup"] = scenario.older_backup_resubmits()
    finally:
        scenario.close()
    return {key: present[name] for key, (name, _) in CORE_GAPS.items()}


# --------------------------------------------------------------------------- #
# Test adapters                                                                #
# --------------------------------------------------------------------------- #

class SkipsBalanceCheck(NativeCipherAdapter):
    """A candidate whose posting path writes journal rows without validating that they balance."""

    candidate = "broken_skips_balance_check"

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


def _largest_remainder(amount: Decimal, weights) -> list[Decimal]:
    cent = Decimal("0.01")
    ws = [D(w) for w in weights]
    exact = [amount * w / sum(ws) for w in ws]
    parts = [e.quantize(cent, rounding=ROUND_DOWN) for e in exact]
    for i in sorted(range(len(ws)), key=lambda i: exact[i] - parts[i], reverse=True)[: int((amount - sum(parts)) / cent)]:
        parts[i] += cent
    return parts


class SimulatedCoreFixes(NativeCipherAdapter):
    """TEST ONLY: the native adapter with each documented core gap closed inside the
    adapter, standing in for the core fixes.  It shows that every hard gate can be
    passed and that the gates do not fail by construction.  It is not evidence about
    the native core."""

    candidate = "simulated_core_fixes"

    def reset(self, path=None):
        super().reset(path)
        self.c.db.execute("CREATE TRIGGER IF NOT EXISTS sim_periods_locked BEFORE UPDATE ON periods WHEN OLD.status = 'locked' "
                          "BEGIN SELECT RAISE(ABORT, 'locked periods are immutable'); END")

    @staticmethod
    def _finite(value: Decimal) -> Decimal:
        if not value.is_finite():
            raise MoneyError(f"non-finite amount {value}")
        return value

    def to_money(self, value):
        return self._finite(super().to_money(value))

    def add_money(self, a, b):
        return self._finite(super().add_money(a, b))

    def sum_money(self, values):
        return self._finite(super().sum_money(values))

    def allocate(self, amount, weights):
        return _largest_remainder(self.to_money(amount), weights)

    def privileged_insert_line(self, journal_id):
        raise sqlite3.IntegrityError("posted journal lines are immutable")  # stands in for a sealed-journal trigger

    def _guard(self):
        self.c.db.require_write_authority()

    def post_journal(self, **kwargs):
        self._guard()
        return super().post_journal(**kwargs)

    def record_collection(self, *args, **kwargs):
        self._guard()
        return super().record_collection(*args, **kwargs)

    def reopen_period(self, period_id, approval_ref):
        if approval_ref and not self.approval_exists(approval_ref):
            raise LedgerError(f"approval reference {approval_ref} is not a recorded approval")
        super().reopen_period(period_id, approval_ref)

    def claim_write_authority(self, approval_ref):
        if approval_ref and not self.approval_exists(approval_ref):
            raise WriteAuthorityError(f"approval reference {approval_ref} is not a recorded approval")
        super().claim_write_authority(approval_ref)

    def complete_recovery(self):
        for intent in self.c.payments.list(status="queued"):  # ask the provider before anything is replayed
            found = self.c.provider.lookup(intent["logical_op_id"])
            if found["found"]:
                self.c.payments._accept(intent["id"], provider_ref=found["provider_ref"], actor="gate-reconciler")
        return super().complete_recovery()


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


# --------------------------------------------------------------------------- #
# Native core                                                                  #
# --------------------------------------------------------------------------- #

class NativeGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = NativeCipherAdapter()
        cls.result = evaluate_candidate(cls.adapter)
        cls.gates = {g["gate"]: g for g in cls.result["gates"]}
        cls.failed = set(cls.result["failed_checks"])
        cls.gaps = probe_core_gaps()

    def evidence(self, gate_id):
        return _text(self.gates[gate_id])

    def test_failures_are_limited_to_documented_core_gaps(self):
        self.assertEqual([g["gate"] for g in self.result["gates"]], list(GATE_IDS))
        self.assertLessEqual(self.failed, set(CORE_GAPS), "\n".join(e for g in self.result["gates"] for e in g["evidence"] if e.startswith("FAIL")))
        gap_gates = {key.split(".")[0].upper() for key in CORE_GAPS}
        for gate_id in GATE_IDS:
            if gate_id not in gap_gates:
                with self.subTest(gate=gate_id):
                    self.assertEqual(self.gates[gate_id]["status"], "pass", self.evidence(gate_id))

    def test_each_documented_gap_is_reported_exactly_when_the_core_has_it(self):
        for key, (_, fragment) in CORE_GAPS.items():
            gate_id = key.split(".")[0].upper()
            with self.subTest(check=key, present=self.gaps[key]):
                self.assertEqual(key in self.failed, self.gaps[key], self.evidence(gate_id))
                if self.gaps[key]:
                    self.assertIn(fragment, self.evidence(gate_id))
                    self.assertEqual(self.gates[gate_id]["status"], "fail")

    def test_status_follows_the_hard_gates(self):
        failing = [g["gate"] for g in self.result["gates"] if g["checks"]["failed"]]
        self.assertEqual(self.result["disqualified_by"], failing)
        self.assertEqual(self.result["hard_gate_summary"]["fail"], len(failing))
        self.assertEqual(self.result["hard_check_summary"]["failed"], len(self.result["failed_checks"]))
        if failing:
            self.assertEqual(self.result["status"], "disqualified")
            self.assertIsNone(self.result["scores"])
            self.assertIsNone(self.result["weighted_total"])
        else:
            self.assertEqual(self.result["status"], "scored")

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
        self.assertIn("0.1 + 0.2 = 0.30 exactly", self.evidence("G1"))
        self.assertIn("33.34 + 33.33 + 33.33 = 100.00", self.evidence("G1"))
        self.assertIn("2.675 -> 2.68", self.evidence("G1"))
        self.assertIn("debits 100.00, credits 99.99", self.evidence("G2"))
        self.assertIn("journals 1 -> 1", self.evidence("G2"))
        self.assertIn("UPDATE journal_lines SET debit=9999.00 refused (IntegrityError: posted journal lines are immutable)", self.evidence("G3"))
        self.assertIn("period G4-SVC closed holding 1 journal; bill of 18000.00", self.evidence("G4"))
        self.assertIn("service path: executing the granted bill approval into the closed period refused (PeriodNotOpen: period G4-SVC is closed); journals 1 -> 1",
                      self.evidence("G4"))
        self.assertIn("raw INSERT of a journal header into the locked period refused (IntegrityError: period is not open for posting)", self.evidence("G4"))
        self.assertIn("conflicts", self.evidence("G5"))
        self.assertIn("27000.00 -> 27000.01", self.evidence("G6"))
        self.assertIn("110000.00", self.evidence("G6"))
        self.assertIn("8 of 8 required immutability/period-lock triggers", self.evidence("G7"))
        self.assertRegex(self.evidence("G7"), r"the export holds every audit row: (\d+) exported, chain count \1, \1 rows in the audit log")
        self.assertIn("provider transfers 1 -> 1, submissions 1 -> 1 (no resubmission)", self.evidence("G8"))
        self.assertIn("refused (WriteAuthorityError", self.evidence("G8"))
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

    def test_g5_advisory_attributes_transfers_correctly(self):
        adv = next(a for a in self.result["advisories"] if a["gate"] == "G5")
        self.assertIn("1 is the bill's first, legitimate release", adv["observed"])
        self.assertEqual(self.result["open_advisories"], sum(1 for a in self.result["advisories"] if a["status"] == "open"))

    def test_result_has_no_binary_floats(self):
        self.assertFalse([v for v in _walk(self.result) if isinstance(v, float)])
        json.dumps(self.result)  # serialisable as is


class SimulatedFixTests(unittest.TestCase):
    """With the documented gaps closed (inside a test adapter), every hard gate passes."""

    def test_every_hard_gate_passes_when_the_gaps_are_closed(self):
        result = evaluate_candidate(SimulatedCoreFixes())
        for g in result["gates"]:
            with self.subTest(gate=g["gate"]):
                self.assertEqual(g["status"], "pass", _text(g))
        self.assertEqual(result["hard_gate_summary"], {"pass": 9, "fail": 0, "not_run": 0})
        self.assertEqual(result["status"], "scored")
        self.assertEqual(result["failed_checks"], [])
        rows = {row["criterion"]: row for row in result["scores"]}
        self.assertEqual(set(rows), set(WEIGHTS))
        self.assertTrue(rows["accounting_control_fit"]["rationale"].startswith("COMPUTED"))
        expected = Decimal(0)
        for row in rows.values():
            self.assertEqual(row["basis"], "computed" if row["criterion"] == "accounting_control_fit" else "ASSUMPTION")
            expected += Decimal(row["score"]) * row["weight"] / Decimal(100)
        self.assertEqual(result["weighted_total"], f"{expected.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f}")
        g8 = _text(_gate(result, "G8"))
        self.assertIn("record_collection action for 4500.00 refused (WriteAuthorityError", g8)
        self.assertIn("(0 resubmission(s))", g8)


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
        self.assertFailedWith(g4, ["g4.raw_header_closed", "g4.raw_line_closed"], "table journals has no column named period_idd")

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
        passes = written["native_passes_all_hard_gates"]
        self.assertEqual(code, 0 if passes else 1)
        self.assertEqual(printed["weights_total"], 100)
        self.assertEqual([c["candidate"] for c in written["candidates"]], ["native_cipher", "erpnext"])
        self.assertEqual([c["status"] for c in written["candidates"]], ["scored" if passes else "disqualified", "not_evaluated"])
        self.assertEqual(written["native_failed_checks"], native["failed_checks"])
        self.assertEqual([g["gate"] for g in written["hard_gates"]], list(GATE_IDS))
        self.assertTrue(written["does_not_prove"])
        if passes:
            self.assertIn("ASSUMPTIONS", written["decision_note"])
        else:
            self.assertIsNone(native["scores"])
            self.assertIn("No foundation can be selected", written["decision_note"])
            for gate_id in native["disqualified_by"]:
                self.assertIn(gate_id, written["decision_note"])

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


if __name__ == "__main__":
    unittest.main()
