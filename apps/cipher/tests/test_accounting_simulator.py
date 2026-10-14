"""Provider isolation and worker protocol regressions, without live providers.

The fake domain demonstrates protocol mechanics, not Cipher audit qualification.
Domain integration separately verifies the actual audit/source proofs.
"""
from contextlib import contextmanager
import json
import sqlite3
import threading
import time
import tempfile
import unittest
from uuid import NAMESPACE_URL, uuid4, uuid5

from ..accounting_simulator import (
    CONTRACT_VERSION, ROUTE, Fault, SimulatedAccountingAdapter,
    SimulatedAccountingRecordStore, SimulationError, canonical, copied, digest,
)
from ..accounting_worker import (SimulatedAccountingWorker, WorkerHeld, WorkerLocalPersistenceError,
                               create_practice_accounting_worker, invoke_bound_worker, require_bound_worker,
                               require_worker_capability, verify_worker_result)
from ..service import Cipher


def sample_payload():
    logical_id = str(uuid5(NAMESPACE_URL, "workspace-sim|" + ROUTE + "|journal-1"))
    return {
        "contractVersion": CONTRACT_VERSION, "mode": "practice", "synthetic": True,
        "route": ROUTE, "logicalOperationId": logical_id,
        "adapter": {"name": "simulated-journal-entry", "version": "1"},
        "mapping": {"id": "mapping-1", "version": 1, "hash": digest("mapping-1")},
        "source": {"kind": "bill_posting", "billId": "bill-1", "contentHash": digest("bill-1"),
                   "sourceVersion": "1", "postingReceiptId": "receipt-1",
                   "postingReceiptHash": digest("receipt-1"), "journalId": "journal-1",
                   "businessApprovalId": "approval-1", "businessApprovalRecordId": "grant-1",
                   "supplierInvoice": None},
        "entity": "Synthetic practice entity", "currency": "USD",
        "datePolicy": "synthetic.period-end.v1", "transactionDate": "2026-10-31",
        "period": {"id": "period-1", "startDate": "2026-10-01", "endDate": "2026-10-31"},
        "lines": [
            {"sourceAccountCode": "5000", "account": "sim-account-cost", "debitCents": 10000,
             "creditCents": 0, "projectRef": "sim-project-1", "vendorRef": "sim-vendor-1",
             "memo": "Synthetic installed work"},
            {"sourceAccountCode": "2000", "account": "sim-account-ap", "debitCents": 0,
             "creditCents": 9000, "projectRef": "sim-project-1", "vendorRef": "sim-vendor-1",
             "memo": "Synthetic net payable"},
            {"sourceAccountCode": "2050", "account": "sim-account-retainage", "debitCents": 0,
             "creditCents": 1000, "projectRef": "sim-project-1", "vendorRef": "sim-vendor-1",
             "memo": "Synthetic withheld retainage"},
        ],
    }


class ProtocolDomain:
    """Disposable in-memory protocol fixture with real standalone transactions."""

    def __init__(self, payload):
        self._lock = threading.RLock()
        self.db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE intent(id TEXT PRIMARY KEY, logical_id TEXT UNIQUE, payload TEXT,
              payload_hash TEXT, state TEXT, lookup_required INTEGER, lease TEXT,
              lease_until REAL, attempt_id TEXT);
            CREATE TABLE attempts(id TEXT PRIMARY KEY, intent_id TEXT, phase TEXT,
              outcome TEXT, result TEXT, error TEXT, invocation_id TEXT, invocation_hash TEXT);
            CREATE TABLE reconciliation(intent_id TEXT PRIMARY KEY, result TEXT);
            CREATE TABLE local_journal(id TEXT); CREATE TABLE payment_call(id TEXT);
        """)
        self.original_payload = copied(payload)
        self.payload_hash = digest(payload)
        self.db.execute("INSERT INTO intent VALUES (?,?,?,?,?,?,?,?,?)",
                        ("intent-1", payload["logicalOperationId"], canonical(payload),
                         self.payload_hash, "queued", 0, "", 0, ""))
        self.facts = {"mode": "practice", "authority_generation": 1, "source_version": 1,
                      "mapping_version": 1, "policy_version": 1, "duty_version": 1,
                      "actual_accountant": True, "retained_human_duty": True,
                      "scope": "project-1", "restored": False, "writable": True,
                      "corrected": False}
        self.original_facts = copied(self.facts)
        self.fail_finish = False
        self.before_boundary = None
        self.claims = {}
        self.invocations = {}
        self.provider_boundary_transactions = []

    def transaction_open(self):
        return self.db.in_transaction

    def _row(self):
        return dict(self.db.execute("SELECT * FROM intent WHERE id='intent-1'").fetchone())

    def _proof(self, *, recovery=False):
        if (self.facts["mode"] != "practice" or self.facts["restored"]
                or not self.facts["writable"] or not self.facts["actual_accountant"]
                or not self.facts["retained_human_duty"] or self.facts["scope"] != "project-1"):
            raise ValueError("boundary held")
        row = self._row()
        if (json.loads(row["payload"]) != self.original_payload
                or row["payload_hash"] != self.payload_hash
                or row["logical_id"] != self.original_payload["logicalOperationId"]):
            raise ValueError("intent source mismatch")
        if not recovery and (self.facts != self.original_facts or self.facts["corrected"]):
            raise ValueError("current source or mapping changed")
        # Recovery binds original source/mapping; current authority and scoped duties
        # still need to pass. It can learn acceptance but cannot authorize resend.
        fingerprint_facts = self.original_facts if recovery else self.facts
        return digest({"facts": fingerprint_facts, "payloadHash": self.payload_hash,
                       "logicalOperationId": row["logical_id"]})

    def claim_intent(self, intent_id, *, actor, lease_seconds=30, purpose="delivery", worker_capability=None,
                     invocation_id=None):
        with self._lock:
            require_worker_capability(worker_capability, domain=self)
            if intent_id != "intent-1" or actor != "accountant-1" or self.db.in_transaction:
                raise ValueError("bad claim")
            row = self._row()
            if row["lease"] and row["lease_until"] > time.monotonic():
                raise ValueError("lease held")
            reconcile = purpose == "reconciliation"
            if reconcile:
                if row["state"] != "simulated_accepted":
                    raise ValueError("not accepted")
                lookup = False
            else:
                if row["state"] not in ("queued", "outcome_unknown", "delivering"):
                    raise ValueError("not deliverable")
                lookup = bool(row["lookup_required"]) or row["state"] in ("outcome_unknown", "delivering")
                if purpose == "lookup" and not lookup:
                    raise ValueError("lookup cannot submit")
            fingerprint = self._proof(recovery=lookup or reconcile)
            invocation_hash = None
            if invocation_id is not None:
                reservation = self.invocations[invocation_id]
                if (reservation["intent_id"] != intent_id or reservation["actor"] != actor
                        or reservation["purpose"] != purpose):
                    raise ValueError("wrong invocation")
                invocation_hash = digest(reservation)
            token, attempt_id = str(uuid4()), str(uuid4())
            claim = {"intent_id": intent_id, "actor": actor, "lease_token": token,
                     "attempt_id": attempt_id, "logical_operation_id": row["logical_id"],
                     "payload": json.loads(row["payload"]), "payload_hash": row["payload_hash"],
                     "state": row["state"], "lookup_required": lookup,
                     "guard_fingerprint": fingerprint, "invocation_id": invocation_id,
                     "invocation_hash": invocation_hash}
            self.db.execute("BEGIN")
            try:
                self.db.execute("UPDATE intent SET lease=?,lease_until=?,attempt_id=?,state=?,lookup_required=?",
                                (token, time.monotonic() + lease_seconds, attempt_id,
                                 row["state"] if reconcile else "delivering", int(lookup)))
                self.db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)",
                                (attempt_id, intent_id, "read_record" if reconcile else "lookup" if lookup else "submit",
                                 "started", "null", "", invocation_id, invocation_hash))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            self.claims[token] = copied(claim)
            return claim

    @contextmanager
    def delivery_boundary(self, intent_id, *, actor, lease_token, purpose):
        with self._lock:
            if self.before_boundary:
                callback, self.before_boundary = self.before_boundary, None
                callback()
            claim = self.claims[lease_token]
            if actor != claim["actor"] or not self.recheck_lease(intent_id, lease_token):
                raise ValueError("lease lost")
            recovery = purpose in ("lookup", "read_record")
            expected = "read_record" if claim["state"] == "simulated_accepted" else "lookup" if claim["lookup_required"] else "submit"
            if purpose != expected or self._proof(recovery=recovery) != claim["guard_fingerprint"]:
                raise ValueError("changed boundary")
            attempt = dict(self.db.execute("SELECT * FROM attempts WHERE id=?", (claim["attempt_id"],)).fetchone())
            if (attempt["invocation_id"] != claim["invocation_id"]
                    or attempt["invocation_hash"] != claim["invocation_hash"]
                    or claim["invocation_id"] is not None
                    and digest(self.invocations[claim["invocation_id"]]) != claim["invocation_hash"]):
                raise ValueError("invocation proof changed")
            self.provider_boundary_transactions.append(self.db.in_transaction)
            yield {**claim, "mode": "practice", "synthetic": True, "writable": True,
                   "restored_quarantine": False, "purpose": purpose}

    def recheck_lease(self, intent_id, lease_token):
        row = self._row()
        return row["id"] == intent_id and row["lease"] == lease_token and row["lease_until"] > time.monotonic()

    def finish_attempt(self, intent_id, lease_token, *, outcome, provider_result, error_code="", actor,
                       worker_capability=None):
        with self._lock:
            require_worker_capability(worker_capability, domain=self)
            if not self.recheck_lease(intent_id, lease_token) or actor != "accountant-1":
                raise ValueError("lease lost at finish")
            row = self._row()
            prior = self.claims[lease_token]
            if outcome == "simulated_accepted":
                verify_worker_result(worker_capability, domain=self, result=provider_result,
                                     payload=self.original_payload, payload_hash=self.payload_hash,
                                     logical_id=self.original_payload["logicalOperationId"])
            elif outcome == "confirmed_missing":
                verify_worker_result(worker_capability, domain=self, result=provider_result,
                                     payload=self.original_payload, payload_hash=self.payload_hash,
                                     logical_id=self.original_payload["logicalOperationId"])
            self.db.execute("BEGIN")
            try:
                self.db.execute("UPDATE attempts SET outcome=?,result=?,error=? WHERE id=?",
                                (outcome, canonical(provider_result), error_code, row["attempt_id"]))
                if self.fail_finish:
                    self.fail_finish = False
                    raise ValueError("simulated local rollback")
                if prior["state"] == "simulated_accepted":
                    state, lookup = "simulated_accepted", 0
                elif outcome == "confirmed_missing":
                    state, lookup = "queued", 0
                else:
                    state, lookup = outcome, int(outcome == "outcome_unknown")
                self.db.execute("UPDATE intent SET state=?,lookup_required=?,lease='',lease_until=0",
                                (state, lookup))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            return {"state": state, "outcome": outcome, "result": copied(provider_result),
                    "errorCode": error_code, "quickBooksAccepted": False}

    def reconcile(self, intent_id, *, provider_result, actor, lease_token, worker_capability=None):
        with self._lock:
            require_worker_capability(worker_capability, domain=self)
            if not self.recheck_lease(intent_id, lease_token) or actor != "accountant-1":
                raise ValueError("lease lost")
            if self._row()["state"] != "simulated_accepted":
                raise ValueError("not accepted")
            verify_worker_result(worker_capability, domain=self, result=provider_result,
                                 payload=self.original_payload, payload_hash=self.payload_hash,
                                 logical_id=self.original_payload["logicalOperationId"])
            self.db.execute("BEGIN")
            try:
                self.db.execute("INSERT INTO reconciliation VALUES(?,?)",
                                (intent_id, canonical(provider_result)))
                self.db.execute("UPDATE attempts SET outcome='simulated_reconciled',result=? WHERE id=?",
                                (canonical(provider_result), self._row()["attempt_id"]))
                self.db.execute("UPDATE intent SET lease='',lease_until=0")
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            return {"outcome": "simulated_reconciled", "quickBooksAccepted": False}

    def expire_lease(self):
        self.db.execute("UPDATE intent SET lease_until=0")

    def close(self):
        self.db.close()


class AccountingSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.payload = sample_payload()
        self.store = SimulatedAccountingRecordStore()
        self.adapter = SimulatedAccountingAdapter(self.store)
        self.domain = ProtocolDomain(self.payload)
        self.worker = SimulatedAccountingWorker(self.domain, self.adapter)

    def tearDown(self):
        self.assertEqual(self.domain.db.execute("SELECT count(*) FROM local_journal").fetchone()[0], 0)
        self.assertEqual(self.domain.db.execute("SELECT count(*) FROM payment_call").fetchone()[0], 0)
        self.assertNotIn(True, self.domain.provider_boundary_transactions)
        self.domain.close()

    def deliver(self):
        return self.worker.deliver_once("intent-1", actor="accountant-1")

    def test_one_effect_exact_payload_and_stable_reference(self):
        logical_id, payload_hash = self.payload["logicalOperationId"], digest(self.payload)
        first = self.adapter.submit(logical_id, self.payload, payload_hash)
        again = self.adapter.submit(logical_id, copied(self.payload), payload_hash)
        self.assertEqual(first["recordId"], again["recordId"])
        self.assertTrue(again["duplicateAcknowledgement"])
        self.assertEqual(self.store.effect_count, 1)
        self.assertFalse(first["quickBooksAccepted"])

    def test_same_logical_id_changed_payload_cannot_create_second_effect(self):
        self.adapter.submit(self.payload["logicalOperationId"], self.payload, digest(self.payload))
        changed = copied(self.payload)
        changed["lines"][0]["memo"] = "Different reviewed facts"
        with self.assertRaisesRegex(SimulationError, "logical_operation_payload_conflict"):
            self.adapter.submit(changed["logicalOperationId"], changed, digest(changed))
        self.assertEqual(self.store.effect_count, 1)

    def test_timeout_before_acceptance_requires_missing_lookup_then_same_uuid_retry(self):
        self.adapter.queue_fault("submit", Fault.TIMEOUT_BEFORE_ACCEPTANCE)
        self.assertEqual(self.deliver()["state"], "outcome_unknown")
        self.assertEqual(self.store.effect_count, 0)
        self.assertEqual(self.deliver()["outcome"], "confirmed_missing")
        self.assertEqual(self.adapter.calls["submit"], 1)
        self.assertEqual(self.deliver()["state"], "simulated_accepted")
        self.assertEqual(self.store.effect_count, 1)
        self.assertEqual(self.adapter.calls, {"submit": 2, "lookup": 1, "read_record": 0})

    def test_timeout_after_acceptance_looks_up_without_resubmission(self):
        self.adapter.queue_fault("submit", Fault.TIMEOUT_AFTER_ACCEPTANCE)
        self.assertEqual(self.deliver()["state"], "outcome_unknown")
        self.assertEqual(self.store.effect_count, 1)
        self.assertEqual(self.deliver()["state"], "simulated_accepted")
        self.assertEqual(self.adapter.calls["submit"], 1)

    def test_remote_acceptance_survives_local_outcome_rollback_and_lease_recovery(self):
        self.domain.fail_finish = True
        with self.assertRaisesRegex(WorkerLocalPersistenceError, "delivery_outcome_not_committed"):
            self.deliver()
        self.assertEqual(self.store.effect_count, 1)
        self.assertEqual(self.domain._row()["state"], "delivering")
        self.assertEqual(self.domain.db.execute("SELECT outcome FROM attempts").fetchone()[0], "started")
        with self.assertRaises(WorkerHeld):
            self.deliver()
        self.domain.expire_lease()
        self.assertEqual(self.deliver()["state"], "simulated_accepted")
        self.assertEqual(self.adapter.calls["submit"], 1)

    def test_duplicate_ack_is_accepted_once(self):
        self.adapter.queue_fault("submit", Fault.DUPLICATE_ACK)
        result = self.deliver()
        self.assertTrue(result["result"]["duplicateAcknowledgement"])
        self.assertEqual(self.store.effect_count, 1)

    def test_mismatched_ack_is_unknown_until_original_record_is_found(self):
        self.adapter.queue_fault("submit", Fault.MISMATCHED_ACK)
        result = self.deliver()
        self.assertEqual(result["state"], "outcome_unknown")
        self.assertEqual(result["errorCode"], "simulated_acknowledgement_mismatch")
        self.assertEqual(self.deliver()["state"], "simulated_accepted")
        self.assertEqual(self.store.effect_count, 1)

    def test_unknown_lookup_is_bounded_and_never_resubmits(self):
        self.adapter.queue_fault("submit", Fault.TIMEOUT_AFTER_ACCEPTANCE)
        self.deliver()
        for _ in range(3):
            self.adapter.queue_fault("lookup", Fault.LOOKUP_TIMEOUT)
        result = self.deliver()
        self.assertEqual(result["errorCode"], "simulated_lookup_exhausted")
        self.assertEqual(self.adapter.calls["lookup"], 3)
        self.assertEqual(self.adapter.calls["submit"], 1)

    def test_record_readback_and_reconciliation_are_separate_from_delivery(self):
        self.assertEqual(self.deliver()["state"], "simulated_accepted")
        self.assertEqual(self.domain.db.execute("SELECT count(*) FROM reconciliation").fetchone()[0], 0)
        result = self.worker.reconcile_once("intent-1", actor="accountant-1")
        self.assertEqual(result["outcome"], "simulated_reconciled")
        self.assertEqual(self.adapter.calls, {"submit": 1, "lookup": 0, "read_record": 1})

    def test_readback_mismatch_preserves_accepted_delivery_and_records_exception(self):
        self.deliver()
        self.adapter.queue_fault("read_record", Fault.READBACK_MISMATCH)
        result = self.worker.reconcile_once("intent-1", actor="accountant-1")
        self.assertEqual(result["state"], "simulated_accepted")
        self.assertEqual(result["errorCode"], "simulated_acknowledgement_mismatch")
        self.assertEqual(self.domain.db.execute("SELECT count(*) FROM reconciliation").fetchone()[0], 0)

    def test_version_conflict_has_no_effect_and_does_not_retry_automatically(self):
        self.adapter.queue_fault("submit", Fault.VERSION_CONFLICT)
        self.assertEqual(self.deliver()["errorCode"], "simulated_version_conflict")
        with self.assertRaises(WorkerHeld):
            self.deliver()
        self.assertEqual(self.store.effect_count, 0)

    def test_rate_limit_and_credential_failures_have_sanitized_durable_dispositions(self):
        for fault, code in ((Fault.RATE_LIMIT, "simulated_rate_limited"),
                            (Fault.CREDENTIAL_EXPIRED, "simulated_credentials_expired")):
            with self.subTest(fault=fault):
                domain = ProtocolDomain(self.payload)
                adapter = SimulatedAccountingAdapter(SimulatedAccountingRecordStore())
                adapter.queue_fault("submit", fault)
                result = SimulatedAccountingWorker(domain, adapter).deliver_once("intent-1", actor="accountant-1")
                self.assertEqual(result["state"], "refused")
                self.assertEqual(result["errorCode"], code)
                self.assertIn(result["result"]["retryAfterSeconds"], (0, 1))
                domain.close()

    def test_current_source_mapping_policy_and_duties_changed_after_claim_prevent_call(self):
        changes = {"source_version": 2, "mapping_version": 2, "policy_version": 2,
                   "duty_version": 2, "actual_accountant": False,
                   "retained_human_duty": False, "corrected": True, "scope": "hidden-project"}
        for key, value in changes.items():
            with self.subTest(key=key):
                domain = ProtocolDomain(self.payload)
                adapter = SimulatedAccountingAdapter(SimulatedAccountingRecordStore())
                domain.before_boundary = lambda d=domain, k=key, v=value: d.facts.__setitem__(k, v)
                with self.assertRaises(WorkerHeld):
                    SimulatedAccountingWorker(domain, adapter).deliver_once("intent-1", actor="accountant-1")
                self.assertEqual(sum(adapter.calls.values()), 0)
                domain.close()

    def test_unknown_recovers_original_acceptance_after_source_correction_without_submit(self):
        self.adapter.queue_fault("submit", Fault.TIMEOUT_AFTER_ACCEPTANCE)
        self.deliver()
        self.domain.facts["corrected"] = True
        self.assertEqual(self.deliver()["state"], "simulated_accepted")
        self.assertEqual(self.adapter.calls["submit"], 1)

    def test_unknown_missing_after_mapping_change_does_not_authorize_resubmit(self):
        self.adapter.queue_fault("submit", Fault.TIMEOUT_BEFORE_ACCEPTANCE)
        self.deliver()
        self.domain.facts["mapping_version"] = 2
        self.assertEqual(self.deliver()["outcome"], "confirmed_missing")
        with self.assertRaises(WorkerHeld):
            self.deliver()
        self.assertEqual(self.adapter.calls["submit"], 1)

    def test_restoration_and_live_mode_refuse_submit_and_unknown_lookup(self):
        for unknown in (False, True):
            for key, value in (("restored", True), ("mode", "live")):
                with self.subTest(unknown=unknown, key=key):
                    domain = ProtocolDomain(self.payload)
                    adapter = SimulatedAccountingAdapter(SimulatedAccountingRecordStore())
                    worker = SimulatedAccountingWorker(domain, adapter)
                    if unknown:
                        adapter.queue_fault("submit", Fault.TIMEOUT_AFTER_ACCEPTANCE)
                        worker.deliver_once("intent-1", actor="accountant-1")
                    before = copied(adapter.calls)
                    domain.facts[key] = value
                    with self.assertRaises(WorkerHeld):
                        worker.deliver_once("intent-1", actor="accountant-1")
                    self.assertEqual(adapter.calls, before)
                    domain.close()

    def test_open_outer_transaction_refuses_before_claim_or_provider(self):
        self.domain.db.execute("BEGIN")
        try:
            with self.assertRaisesRegex(WorkerHeld, "open_local_transaction"):
                self.deliver()
        finally:
            self.domain.db.execute("ROLLBACK")
        self.assertEqual(sum(self.adapter.calls.values()), 0)

    def test_tampered_rehashed_intent_refuses_before_provider(self):
        changed = copied(self.payload)
        changed["lines"][0]["memo"] = "Raw row replacement"
        self.domain.db.execute("UPDATE intent SET payload=?,payload_hash=?", (canonical(changed), digest(changed)))
        with self.assertRaises(WorkerHeld):
            self.deliver()
        self.assertEqual(sum(self.adapter.calls.values()), 0)

    def test_expired_lease_after_claim_prevents_provider(self):
        self.domain.before_boundary = self.domain.expire_lease
        with self.assertRaises(WorkerHeld):
            self.deliver()
        self.assertEqual(self.store.effect_count, 0)

    def test_two_concurrent_workers_create_one_effect(self):
        barrier = threading.Barrier(2)
        results = []
        def run():
            barrier.wait()
            try:
                results.append(self.deliver()["state"])
            except WorkerHeld:
                results.append("held")
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(results), ["held", "simulated_accepted"])
        self.assertEqual(self.store.effect_count, 1)

    def test_foreign_or_uninitialized_adapter_refused_without_getter(self):
        class Foreign:
            @property
            def capabilities(self):
                self.fail("must never access")
        for adapter in (Foreign(), object.__new__(SimulatedAccountingAdapter)):
            with self.assertRaisesRegex(SimulationError, "unqualified_accounting_adapter"):
                SimulatedAccountingWorker(self.domain, adapter)
        self.assertEqual(sum(self.adapter.calls.values()), 0)

    def test_changed_bound_record_store_is_refused(self):
        self.adapter._store = SimulatedAccountingRecordStore()
        with self.assertRaisesRegex(SimulationError, "unqualified_accounting_adapter"):
            self.deliver()

    def test_exact_cents_and_fixed_route_payload_fail_closed(self):
        changes = [lambda p: p.__setitem__("route", "quickbooks.journal-entry"),
                   lambda p: p.__setitem__("mode", "live"),
                   lambda p: p["lines"][0].__setitem__("debitCents", 10000.0),
                   lambda p: p["lines"][0].__setitem__("debitCents", True),
                   lambda p: p["lines"][1].__setitem__("creditCents", 8999),
                   lambda p: p.__setitem__("provider", "quickbooks")]
        for change in changes:
            changed = copied(self.payload)
            change(changed)
            with self.assertRaises(SimulationError):
                self.adapter.submit(changed["logicalOperationId"], changed, digest(changed))
        self.assertEqual(self.store.effect_count, 0)

    def test_guard_numeric_boolean_alias_is_refused(self):
        claim = self.worker._claim("intent-1", "accountant-1")
        current = {**claim, "mode": "practice", "synthetic": 1, "writable": True,
                   "restored_quarantine": False, "purpose": "submit"}
        with self.assertRaises(WorkerHeld):
            self.worker._validate_boundary(claim, current, "submit")

    def test_readback_float_money_alias_is_refused(self):
        claim = self.worker._claim("intent-1", "accountant-1")
        result = self.adapter.submit(claim["logical_operation_id"], claim["payload"], claim["payload_hash"])
        result["payload"] = copied(claim["payload"])
        result["payload"]["lines"][0]["debitCents"] = 10000.0
        with self.assertRaises(SimulationError):
            self.worker._acknowledgement(claim, result, readback=True)

    def test_missing_numeric_boolean_alias_cannot_authorize_retry(self):
        claim = self.worker._claim("intent-1", "accountant-1")
        result = {"status": "simulated_missing", "mode": "practice", "synthetic": 1,
                  "simulation": True, "route": ROUTE,
                  "logicalOperationId": claim["logical_operation_id"],
                  "payloadHash": claim["payload_hash"], "quickBooksAccepted": False}
        self.assertFalse(self.worker._missing(claim, result))

    def test_rebound_initialized_adapter_method_cannot_execute_foreign_callable(self):
        calls = []
        original = self.adapter.submit
        def foreign_submit(*args):
            calls.append("foreign")
            return original(*args)
        self.adapter.submit = foreign_submit
        with self.assertRaisesRegex(SimulationError, "unqualified_accounting_adapter"):
            self.deliver()
        self.assertEqual(calls, [])

    def test_rebound_initialized_store_method_cannot_execute_foreign_callable(self):
        calls = []
        original = self.store._accept
        def foreign_accept(*args):
            calls.append("foreign")
            return original(*args)
        self.store._accept = foreign_accept
        with self.assertRaisesRegex(SimulationError, "unqualified_accounting_adapter"):
            self.deliver()
        self.assertEqual(calls, [])

    def test_human_actor_cannot_claim_worker_lease_or_record_disposition(self):
        before = self.domain.db.total_changes
        with self.assertRaisesRegex(WorkerHeld, "unqualified_accounting_worker"):
            self.domain.claim_intent("intent-1", actor="accountant-1")
        with self.assertRaisesRegex(WorkerHeld, "unqualified_accounting_worker"):
            self.domain.finish_attempt("intent-1", "invented-token", outcome="outcome_unknown",
                                       provider_result=None, actor="accountant-1")
        self.assertEqual(self.domain.db.total_changes, before)
        self.assertEqual(sum(self.adapter.calls.values()), 0)

    def test_unregistered_same_class_capability_is_refused(self):
        forged = type(self.worker._capability)()
        with self.assertRaisesRegex(WorkerHeld, "unqualified_accounting_worker"):
            require_worker_capability(forged, domain=self.domain)

    def test_even_valid_worker_capability_cannot_record_public_hashes_without_actual_record(self):
        claim = self.worker._claim("intent-1", "accountant-1")
        logical_id, payload_hash = claim["logical_operation_id"], claim["payload_hash"]
        from hashlib import sha256
        fake = {"status": "simulated_accepted", "mode": "practice", "synthetic": True,
                "simulation": True, "route": ROUTE, "logicalOperationId": logical_id,
                "payloadHash": payload_hash, "quickBooksAccepted": False,
                "recordId": "SIM-JE-" + sha256(logical_id.encode()).hexdigest()[:24],
                "recordVersion": "1", "duplicateAcknowledgement": False,
                "recordHash": digest({"logicalOperationId": logical_id, "payloadHash": payload_hash,
                                      "recordVersion": "1", "payload": claim["payload"]})}
        before = self.domain.db.total_changes
        with self.assertRaisesRegex(WorkerHeld, "simulated_record_proof_unavailable"):
            self.domain.finish_attempt("intent-1", claim["lease_token"], outcome="simulated_accepted",
                                       provider_result=fake, actor="accountant-1",
                                       worker_capability=self.worker._capability)
        self.assertEqual(self.store.effect_count, 0)
        self.assertEqual(self.domain.db.total_changes, before)
        self.assertEqual(sum(self.adapter.calls.values()), 0)

    def test_replacement_adapter_or_empty_store_is_unavailable_not_missing(self):
        for adapter in (SimulatedAccountingAdapter(self.store),
                        SimulatedAccountingAdapter(SimulatedAccountingRecordStore())):
            with self.assertRaisesRegex(WorkerHeld, "simulated_store_unavailable"):
                SimulatedAccountingWorker(self.domain, adapter)
        self.assertEqual(sum(self.adapter.calls.values()), 0)

    def test_lost_bound_store_history_cannot_confirm_missing_or_resubmit(self):
        self.adapter.queue_fault("submit", Fault.TIMEOUT_AFTER_ACCEPTANCE)
        self.deliver()
        self.store._records.clear()
        before = self.domain.db.total_changes
        with self.assertRaisesRegex(SimulationError, "simulated_store_unavailable"):
            self.deliver()
        self.assertEqual(self.domain._row()["state"], "outcome_unknown")
        self.assertEqual(self.domain.db.total_changes, before)
        self.assertEqual(self.adapter.calls, {"submit": 1, "lookup": 0, "read_record": 0})

    def test_retained_result_proof_is_pure_and_does_not_make_provider_calls(self):
        result = self.adapter.submit(self.payload["logicalOperationId"], self.payload, digest(self.payload))
        before_changes, before_calls = self.domain.db.total_changes, copied(self.adapter.calls)
        verify_worker_result(self.worker._capability, domain=self.domain, result=result,
                             payload=self.payload, payload_hash=digest(self.payload),
                             logical_id=self.payload["logicalOperationId"])
        self.assertEqual(self.domain.db.total_changes, before_changes)
        self.assertEqual(self.adapter.calls, before_calls)

    def test_retained_record_payload_snapshot_cannot_mutate_external_fact(self):
        result = self.adapter.submit(self.payload["logicalOperationId"], self.payload, digest(self.payload))
        snapshot = self.store._lookup(self.payload["logicalOperationId"]).payload
        snapshot["lines"][0]["debitCents"] = 10000.0
        readback = self.adapter.read_record(result["recordId"])
        self.assertIs(type(readback["payload"]["lines"][0]["debitCents"]), int)

    def test_worker_method_shadow_cannot_use_initialized_capability(self):
        self.worker._missing = lambda claim, result: True
        with self.assertRaisesRegex(WorkerHeld, "unqualified_accounting_worker"):
            self.deliver()
        self.assertEqual(sum(self.adapter.calls.values()), 0)

    def test_missing_result_proof_is_pure_and_refuses_existing_record(self):
        missing = self.adapter.lookup(self.payload["logicalOperationId"], digest(self.payload))
        before = copied(self.adapter.calls)
        verify_worker_result(self.worker._capability, domain=self.domain, result=missing,
                             payload=self.payload, payload_hash=digest(self.payload),
                             logical_id=self.payload["logicalOperationId"])
        self.assertEqual(self.adapter.calls, before)
        self.adapter.submit(self.payload["logicalOperationId"], self.payload, digest(self.payload))
        with self.assertRaisesRegex(WorkerHeld, "simulated_record_proof_mismatch"):
            verify_worker_result(self.worker._capability, domain=self.domain, result=missing,
                                 payload=self.payload, payload_hash=digest(self.payload),
                                 logical_id=self.payload["logicalOperationId"])

    def test_missing_proof_numeric_boolean_alias_is_refused(self):
        missing = self.adapter.lookup(self.payload["logicalOperationId"], digest(self.payload))
        missing["synthetic"] = 1
        with self.assertRaisesRegex(WorkerHeld, "simulated_record_proof_mismatch"):
            verify_worker_result(self.worker._capability, domain=self.domain, result=missing,
                                 payload=self.payload, payload_hash=digest(self.payload),
                                 logical_id=self.payload["logicalOperationId"])

    def test_original_invoice_binding_is_retained_exactly(self):
        payload = copied(self.payload)
        payload["source"]["supplierInvoice"] = {
            "id": "invoice-1", "number": "SYN-100", "invoice_date": "2026-10-14",
            "due_date": "2026-11-13", "invoice_hash": digest("invoice-1"),
            "evidence_hash": digest("evidence-1"), "approval_id": "match-approval-1",
            "current": {"status": "matched", "version": 1, "invoice_hash": digest("invoice-1"),
                        "number": "SYN-100", "invoice_date": "2026-10-14", "due_date": "2026-11-13",
                        "evidence_hash": digest("evidence-1"), "evidence_current_hash": digest("evidence-1")}}
        result = self.adapter.submit(payload["logicalOperationId"], payload, digest(payload))
        self.assertEqual(self.adapter.read_record(result["recordId"])["payload"]["source"]["supplierInvoice"],
                         payload["source"]["supplierInvoice"])

    def test_opaque_invoice_binding_is_bounded_and_keeps_exact_types(self):
        for binding in ([], {"current": {"version": 1.0}}, {"number": "x" * 513},
                        {str(index): None for index in range(33)}):
            payload = copied(self.payload)
            payload["source"]["supplierInvoice"] = binding
            with self.assertRaises(SimulationError):
                self.adapter.submit(payload["logicalOperationId"], payload, digest(payload))
        self.assertEqual(self.store.effect_count, 0)

    def test_fixed_lookup_missing_retry_never_turns_into_submit(self):
        self.adapter.queue_fault("submit", Fault.TIMEOUT_BEFORE_ACCEPTANCE)
        self.deliver()
        result = self.worker.lookup_once("intent-1", actor="accountant-1")
        self.assertEqual(result["outcome"], "confirmed_missing")
        before = copied(self.adapter.calls)
        with self.assertRaises(WorkerHeld):
            self.worker.lookup_once("intent-1", actor="accountant-1")
        self.assertEqual(self.adapter.calls, before)
        self.assertEqual(self.store.effect_count, 0)

    def test_fixed_lookup_refuses_fresh_queued_intent_before_claim(self):
        before = self.domain.db.total_changes
        with self.assertRaises(WorkerHeld):
            self.worker.lookup_once("intent-1", actor="accountant-1")
        self.assertEqual(self.domain.db.total_changes, before)
        self.assertEqual(sum(self.adapter.calls.values()), 0)

    def test_bound_worker_check_is_pure_and_refuses_counterfeit_copied_capability(self):
        before_changes, before_calls = self.domain.db.total_changes, copied(self.adapter.calls)
        require_bound_worker(self.worker, domain=self.domain)
        counterfeit = object.__new__(SimulatedAccountingWorker)
        counterfeit.__dict__.update(self.worker.__dict__)
        with self.assertRaisesRegex(WorkerHeld, "unqualified_accounting_worker"):
            require_bound_worker(counterfeit, domain=self.domain)
        self.assertEqual(self.domain.db.total_changes, before_changes)
        self.assertEqual(self.adapter.calls, before_calls)

    def test_invocation_binding_is_committed_before_provider_call(self):
        reservation = {"intent_id": "intent-1", "actor": "accountant-1", "purpose": "delivery",
                       "operation": "accounting.deliver", "reviewHash": digest("original review")}
        self.domain.invocations["invocation-1"] = reservation
        result = invoke_bound_worker(self.worker, domain=self.domain, method="deliver_once",
                                     intent_id="intent-1", actor="accountant-1", invocation_id="invocation-1")
        self.assertEqual(result["state"], "simulated_accepted")
        attempt = self.domain.db.execute("SELECT invocation_id,invocation_hash FROM attempts").fetchone()
        self.assertEqual(tuple(attempt), ("invocation-1", digest(reservation)))
        self.assertEqual(self.store.effect_count, 1)

    def test_changed_invocation_source_hash_holds_before_provider_call(self):
        self.domain.invocations["invocation-1"] = {
            "intent_id": "intent-1", "actor": "accountant-1", "purpose": "delivery",
            "reviewHash": digest("original review")}
        self.domain.before_boundary = lambda: self.domain.invocations["invocation-1"].__setitem__("reviewHash", digest("replaced review"))
        with self.assertRaises(WorkerHeld):
            self.worker.deliver_once("intent-1", actor="accountant-1", invocation_id="invocation-1")
        self.assertEqual(sum(self.adapter.calls.values()), 0)
        self.assertEqual(self.store.effect_count, 0)

    def test_uncommitted_or_wrong_actor_invocation_refuses_before_attempt(self):
        self.domain.invocations["wrong-invocation"] = {
            "intent_id": "intent-1", "actor": "another-accountant", "purpose": "delivery"}
        for invocation_id in ("unreserved", "wrong-invocation"):
            before = self.domain.db.total_changes
            with self.assertRaises(WorkerHeld):
                self.worker.deliver_once("intent-1", actor="accountant-1", invocation_id=invocation_id)
            self.assertEqual(self.domain.db.total_changes, before)
            self.assertEqual(sum(self.adapter.calls.values()), 0)

    def test_unfinished_same_invocation_recovers_by_lookup(self):
        self.domain.invocations["invocation-1"] = {
            "intent_id": "intent-1", "actor": "accountant-1", "purpose": "delivery"}
        self.domain.fail_finish = True
        with self.assertRaises(WorkerLocalPersistenceError):
            self.worker.deliver_once("intent-1", actor="accountant-1", invocation_id="invocation-1")
        self.domain.expire_lease()
        result = self.worker.deliver_once("intent-1", actor="accountant-1", invocation_id="invocation-1")
        self.assertEqual(result["state"], "simulated_accepted")
        self.assertEqual(self.adapter.calls, {"submit": 1, "lookup": 1, "read_record": 0})
        attempts = self.domain.db.execute("SELECT DISTINCT invocation_id,invocation_hash FROM attempts").fetchall()
        self.assertEqual(len(attempts), 1)

    def test_fixed_captured_dispatch_refuses_shadowed_callable_before_invocation(self):
        called = []
        self.worker.deliver_once = lambda *args, **kwargs: called.append("foreign")
        with self.assertRaisesRegex(WorkerHeld, "unqualified_accounting_worker"):
            invoke_bound_worker(self.worker, domain=self.domain, method="deliver_once",
                                intent_id="intent-1", actor="accountant-1")
        self.assertEqual(called, [])
        self.assertEqual(sum(self.adapter.calls.values()), 0)


class AccountingWorkerFactoryTests(unittest.TestCase):
    def test_owned_factory_pins_one_worker_without_sql_or_financial_seeding(self):
        c = Cipher()
        self.addCleanup(c.db.close)
        before = c.db.conn.total_changes
        worker = create_practice_accounting_worker(c)
        self.assertIs(create_practice_accounting_worker(c), worker)
        require_bound_worker(worker, domain=c.plugin("accounting"))
        self.assertEqual(c.db.conn.total_changes, before)
        self.assertEqual(worker._adapter.calls, {"submit": 0, "lookup": 0, "read_record": 0})
        self.assertEqual(c.db.one("SELECT count(*) AS n FROM accounting_mapping_versions")["n"], 0)

    def test_foreign_factory_object_refused_before_getter(self):
        class Foreign:
            @property
            def db(self):
                raise AssertionError("foreign getter executed")
        with self.assertRaisesRegex(WorkerHeld, "accounting_worker_unavailable"):
            create_practice_accounting_worker(Foreign())

    def test_file_workspace_factory_refused_without_sql_effect(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            c = Cipher(str(Path(directory) / "synthetic.sqlite"))
            try:
                before = c.db.conn.total_changes
                with self.assertRaisesRegex(WorkerHeld, "accounting_worker_requires_owned_memory_runtime"):
                    create_practice_accounting_worker(c)
                self.assertEqual(c.db.conn.total_changes, before)
            finally:
                c.db.close()

    def test_outer_transaction_factory_refused_without_sql_effect(self):
        c = Cipher()
        self.addCleanup(c.db.close)
        with c.db.transaction():
            before = c.db.conn.total_changes
            with self.assertRaisesRegex(WorkerHeld, "accounting_worker_requires_owned_memory_runtime"):
                create_practice_accounting_worker(c)
            self.assertEqual(c.db.conn.total_changes, before)

    def test_lost_owned_worker_cannot_silently_create_new_adapter(self):
        import gc
        c = Cipher()
        self.addCleanup(c.db.close)
        worker = create_practice_accounting_worker(c)
        adapter = worker._adapter
        del worker
        gc.collect()
        with self.assertRaisesRegex(WorkerHeld, "simulated_store_unavailable"):
            create_practice_accounting_worker(c)
        self.assertEqual(adapter.calls, {"submit": 0, "lookup": 0, "read_record": 0})


if __name__ == "__main__":
    unittest.main()
