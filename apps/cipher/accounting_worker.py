"""Fixed practice accounting worker with isolated simulated provider effects.

The service must bind a trusted initialized domain and the exact simulator. The
domain commits claims/outcomes; no provider call is inside its SQL transaction.
An unfinished/expired submit claim MUST produce a lookup claim on recovery.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from hashlib import sha256
import threading
from types import MappingProxyType
from typing import Any, Protocol
from weakref import WeakKeyDictionary, ref

from .accounting_simulator import (
    ROUTE, SimulationError, canonical, copied, digest, invoke_simulator,
    require_simulator, retained_simulated_record, validate_payload,
)

CLAIM_KEYS = frozenset({"intent_id", "actor", "lease_token", "attempt_id",
                        "logical_operation_id", "payload", "payload_hash", "state",
                        "lookup_required", "guard_fingerprint", "invocation_id", "invocation_hash"})
_worker_lock = threading.RLock()
_workers: WeakKeyDictionary = WeakKeyDictionary()
_capabilities: WeakKeyDictionary = WeakKeyDictionary()
_runtime_adapters: WeakKeyDictionary = WeakKeyDictionary()
_owned_workers: WeakKeyDictionary = WeakKeyDictionary()


class _WorkerCapability:
    __slots__ = ("__weakref__",)


class DeliveryDomain(Protocol):
    """Required trusted-domain contract, not a caller-supplied capability object.

    Claims include intent_id, actor, lease_token, attempt_id, logical_operation_id,
    payload, payload_hash, state, lookup_required and guard_fingerprint. The domain
    owns phase selection. A retry caller never gets to bypass Unknown lookup.

    delivery_boundary holds the workspace authority/intent lock through one
    external call, without an SQL transaction. It yields the same canonical
    fields plus mode='practice', synthetic=True, writable=True and
    restored_quarantine=False, after verifying original source/intent/audit,
    current mapping/policy, actual scoped duty and an unexpired exclusive lease.
    Source correction refuses submit. Known-outcome lookup/readback retains the
    original immutable snapshot after current source eligibility changes; that
    recovery proof does not authorize another submit. Restoration refuses all.

    finish_attempt stores sanitized outcome atomically. 'confirmed_missing'
    allows a later same-UUID claim, never a new UUID. 'outcome_unknown' and an
    unfinished claimed submit force lookup. 'simulated_accepted' only means simulated
    acceptance here; UI and exports must retain the result's explicit label.

    Reconciliation has its own readback claim, outcome and checkpoint. Accepted
    intents cannot be submitted again, including by the reconciliation path.
    """

    def claim_intent(self, intent_id: str, *, actor: str, lease_seconds: int = 30,
                     purpose: str = "delivery", worker_capability: object,
                     invocation_id: str | None = None) -> dict: ...
    def delivery_boundary(self, intent_id: str, *, actor: str,
                          lease_token: str, purpose: str) -> AbstractContextManager[dict]: ...
    def recheck_lease(self, intent_id: str, lease_token: str) -> bool: ...
    def transaction_open(self) -> bool: ...
    def finish_attempt(self, intent_id: str, lease_token: str, *, outcome: str,
                       provider_result: dict | None, error_code: str = "", actor: str,
                       worker_capability: object) -> dict: ...
    def reconcile(self, intent_id: str, *, provider_result: dict, actor: str,
                  lease_token: str, worker_capability: object) -> dict: ...


class WorkerHeld(Exception):
    pass


class WorkerLocalPersistenceError(Exception):
    """Remote effect may exist; recovery requires lookup, never blind resubmit."""


class SimulatedAccountingWorker:
    """One submit OR bounded lookup per tick; separate record reconciliation."""

    def __init__(self, domain: DeliveryDomain, adapter: Any, *, max_lookup_attempts: int = 3):
        # Reject foreign/uninitialized provider objects before accessing properties.
        self._adapter = require_simulator(adapter)
        if type(max_lookup_attempts) is not int or not 1 <= max_lookup_attempts <= 3:
            raise WorkerHeld("invalid_lookup_bound")
        self._domain = domain
        self._max_lookup_attempts = max_lookup_attempts
        with _worker_lock:
            original_adapter = _runtime_adapters.get(domain)
            if original_adapter is not None and original_adapter is not self._adapter:
                raise WorkerHeld("simulated_store_unavailable")
            _runtime_adapters[domain] = self._adapter
            self._capability = _WorkerCapability()
            binding = (ref(self), ref(domain), self._adapter)
            _workers[self] = binding
            _capabilities[self._capability] = binding

    def _claim(self, intent_id: str, actor: str, *, purpose: str = "delivery",
               invocation_id: str | None = None) -> dict:
        require_worker_capability(self._capability, domain=self._domain)
        if purpose not in ("delivery", "lookup", "reconciliation"):
            raise WorkerHeld("invalid_worker_purpose")
        if self._domain.transaction_open():
            raise WorkerHeld("open_local_transaction")
        if invocation_id is not None and (type(invocation_id) is not str or not 1 <= len(invocation_id) <= 128):
            raise WorkerHeld("invalid_invocation_binding")
        try:
            kwargs = {"actor": actor, "purpose": purpose, "worker_capability": self._capability}
            if invocation_id is not None:
                kwargs["invocation_id"] = invocation_id
            claim = self._domain.claim_intent(intent_id, **kwargs)
        except Exception as exc:
            raise WorkerHeld("intent_claim_unavailable") from exc
        if type(claim) is not dict or set(claim) != CLAIM_KEYS:
            raise WorkerHeld("invalid_claim_context")
        if invocation_id is not None:
            if (claim["invocation_id"] != invocation_id
                    or type(claim["invocation_hash"]) is not str or len(claim["invocation_hash"]) != 64
                    or any(char not in "0123456789abcdef" for char in claim["invocation_hash"])):
                raise WorkerHeld("invalid_invocation_binding")
        elif claim["invocation_id"] is not None or claim["invocation_hash"] is not None:
            raise WorkerHeld("invalid_invocation_binding")
        if claim["intent_id"] != intent_id or claim["actor"] != actor:
            raise WorkerHeld("invalid_claim_context")
        for key in ("lease_token", "attempt_id"):
            if type(claim[key]) is not str or not claim[key]:
                raise WorkerHeld("invalid_claim_context")
        if (type(claim["lookup_required"]) is not bool or type(claim["state"]) is not str
                or type(claim["guard_fingerprint"]) is not str
                or len(claim["guard_fingerprint"]) != 64
                or any(char not in "0123456789abcdef" for char in claim["guard_fingerprint"])):
            raise WorkerHeld("invalid_claim_context")
        validate_payload(claim["logical_operation_id"], claim["payload"], claim["payload_hash"])
        if purpose == "reconciliation" and claim["state"] != "simulated_accepted":
            raise WorkerHeld("invalid_reconciliation_claim")
        if purpose == "lookup" and not claim["lookup_required"]:
            raise WorkerHeld("invalid_lookup_claim")
        return copied(claim)

    def _validate_boundary(self, claim: dict, current: dict, operation: str) -> None:
        expected = {**claim, "mode": "practice", "synthetic": True,
                    "writable": True, "restored_quarantine": False, "purpose": operation}
        if type(current) is not dict or canonical(current) != canonical(expected):
            raise WorkerHeld("delivery_context_changed")
        if not self._domain.recheck_lease(claim["intent_id"], claim["lease_token"]):
            raise WorkerHeld("delivery_lease_unavailable")
        if self._domain.transaction_open():
            raise WorkerHeld("open_local_transaction")
        require_simulator(self._adapter)

    def _provider_call(self, claim: dict, operation: str, *args: Any) -> dict:
        try:
            with self._domain.delivery_boundary(claim["intent_id"], actor=claim["actor"],
                                                lease_token=claim["lease_token"],
                                                purpose=operation) as current:
                self._validate_boundary(claim, current, operation)
                try:
                    return invoke_simulator(self._adapter, operation, *args)
                except (SimulationError, WorkerHeld):
                    raise
                except Exception as exc:
                    raise SimulationError("simulated_adapter_failure", unknown=True) from exc
        except (SimulationError, WorkerHeld):
            raise
        except Exception as exc:
            # Do not expose exception text, which could contain IDs or credentials.
            raise WorkerHeld("delivery_context_unavailable") from exc

    @staticmethod
    def _acknowledgement(claim: dict, result: dict, *, readback: bool = False) -> dict:
        keys = {"status", "mode", "synthetic", "simulation", "route", "logicalOperationId",
                "payloadHash", "recordId", "recordVersion", "recordHash",
                "duplicateAcknowledgement", "quickBooksAccepted"}
        if readback:
            keys.add("payload")
        record_id = "SIM-JE-" + sha256(claim["logical_operation_id"].encode()).hexdigest()[:24]
        record_hash = digest({"logicalOperationId": claim["logical_operation_id"],
                              "payloadHash": claim["payload_hash"], "recordVersion": "1",
                              "payload": claim["payload"]})
        valid = (type(result) is dict and set(result) == keys
                 and result["status"] == "simulated_accepted" and result["mode"] == "practice"
                 and result["synthetic"] is True and result["simulation"] is True
                 and result["quickBooksAccepted"] is False and result["route"] == ROUTE
                 and result["logicalOperationId"] == claim["logical_operation_id"]
                 and result["payloadHash"] == claim["payload_hash"]
                 and result["recordId"] == record_id and result["recordVersion"] == "1"
                 and result["recordHash"] == record_hash
                 and type(result["duplicateAcknowledgement"]) is bool)
        if not valid or (readback and canonical(result["payload"]) != canonical(claim["payload"])):
            raise SimulationError("simulated_acknowledgement_mismatch", unknown=True)
        return copied(result)

    @staticmethod
    def _missing(claim: dict, result: dict) -> bool:
        expected = {"status": "simulated_missing", "mode": "practice", "synthetic": True,
                          "simulation": True, "route": ROUTE,
                          "logicalOperationId": claim["logical_operation_id"],
                    "payloadHash": claim["payload_hash"], "quickBooksAccepted": False}
        return type(result) is dict and canonical(result) == canonical(expected)

    def _finish(self, claim: dict, outcome: str, result: dict | None = None,
                error_code: str = "") -> dict:
        if self._domain.transaction_open():
            raise WorkerLocalPersistenceError("outcome_requires_standalone_transaction")
        try:
            return self._domain.finish_attempt(claim["intent_id"], claim["lease_token"],
                                               outcome=outcome, provider_result=result,
                                               error_code=error_code, actor=claim["actor"],
                                               worker_capability=self._capability)
        except Exception as exc:
            raise WorkerLocalPersistenceError("delivery_outcome_not_committed") from exc

    def deliver_once(self, intent_id: str, *, actor: str, invocation_id: str | None = None) -> dict:
        claim = self._claim(intent_id, actor, invocation_id=invocation_id)
        logical_id, payload_hash = claim["logical_operation_id"], claim["payload_hash"]
        if claim["lookup_required"]:
            return self._lookup_claim(claim)
        try:
            result = self._provider_call(claim, "submit", logical_id, claim["payload"], payload_hash)
            result = self._acknowledgement(claim, result)
            return self._finish(claim, "simulated_accepted", result)
        except SimulationError as exc:
            if exc.unknown:
                return self._finish(claim, "outcome_unknown", error_code=exc.code)
            if exc.code in ("simulated_rate_limited", "simulated_credentials_expired"):
                return self._finish(claim, "refused", {"retryAfterSeconds": exc.retry_after}, exc.code)
            return self._finish(claim, "refused", error_code=exc.code)

    def _lookup_claim(self, claim: dict) -> dict:
        if not claim["lookup_required"]:
            raise WorkerHeld("invalid_lookup_claim")
        for _ in range(self._max_lookup_attempts):
            try:
                result = self._provider_call(claim, "lookup", claim["logical_operation_id"], claim["payload_hash"])
                if self._missing(claim, result):
                    return self._finish(claim, "confirmed_missing", result)
                result = self._acknowledgement(claim, result)
                return self._finish(claim, "simulated_accepted", result)
            except SimulationError as exc:
                if exc.code == "simulated_timeout":
                    continue
                return self._finish(claim, "outcome_unknown", error_code=exc.code)
        return self._finish(claim, "outcome_unknown", error_code="simulated_lookup_exhausted")

    def lookup_once(self, intent_id: str, *, actor: str, invocation_id: str | None = None) -> dict:
        """Resolve one Unknown outcome; this fixed action cannot submit."""
        return self._lookup_claim(self._claim(intent_id, actor, purpose="lookup", invocation_id=invocation_id))

    def reconcile_once(self, intent_id: str, *, actor: str, invocation_id: str | None = None) -> dict:
        claim = self._claim(intent_id, actor, purpose="reconciliation", invocation_id=invocation_id)
        # Accepted reference comes from the domain's original audited outcome.
        record_id = "SIM-JE-" + sha256(claim["logical_operation_id"].encode()).hexdigest()[:24]
        try:
            result = self._provider_call(claim, "read_record", record_id)
            result = self._acknowledgement(claim, result, readback=True)
            if self._domain.transaction_open():
                raise WorkerLocalPersistenceError("reconciliation_requires_standalone_transaction")
            try:
                return self._domain.reconcile(intent_id, provider_result=result, actor=actor,
                                               lease_token=claim["lease_token"],
                                               worker_capability=self._capability)
            except Exception as exc:
                raise WorkerLocalPersistenceError("reconciliation_not_committed") from exc
        except SimulationError as exc:
            # Accepted delivery remains accepted; this is a distinct readback exception.
            return self._finish(claim, "refused", error_code=exc.code)


_WORKER_FUNCTIONS = MappingProxyType({name: type.__getattribute__(SimulatedAccountingWorker, name)
                                    for name in ("__init__", "_claim", "_validate_boundary", "_provider_call",
                                                 "_acknowledgement", "_missing", "_finish", "_lookup_claim",
                                                 "deliver_once", "lookup_once", "reconcile_once")})


def require_bound_worker(worker: Any, *, domain: Any) -> None:
    """Pure check for the original server-owned worker, before any getter/call."""
    if type(worker) is not SimulatedAccountingWorker:
        raise WorkerHeld("unqualified_accounting_worker")
    with _worker_lock:
        binding = _workers.get(worker)
        if binding is None or binding[0]() is not worker or binding[1]() is not domain:
            raise WorkerHeld("unqualified_accounting_worker")
        capability = object.__getattribute__(worker, "__dict__").get("_capability")
        require_worker_capability(capability, domain=domain)


def invoke_bound_worker(worker: Any, *, domain: Any, method: str, intent_id: str,
                        actor: str, invocation_id: str | None = None) -> dict:
    """Fixed server dispatch after its durable invocation reservation commits."""
    require_bound_worker(worker, domain=domain)
    if method not in ("deliver_once", "lookup_once", "reconcile_once"):
        raise WorkerHeld("invalid_worker_purpose")
    return _WORKER_FUNCTIONS[method](worker, intent_id, actor=actor, invocation_id=invocation_id)


def create_practice_accounting_worker(cipher: Any) -> SimulatedAccountingWorker:
    """Initialize the owned practice handler's one fixed worker, without selectors.

    The handler retains the returned object privately. Only its fixed actions may
    delegate to it; public DTOs never contain worker capabilities or lease tokens.
    """
    from .service import Cipher
    from .domain.accounting import Plugin
    from .accounting_simulator import SimulatedAccountingAdapter, SimulatedAccountingRecordStore
    if type(cipher) is not Cipher:
        raise WorkerHeld("accounting_worker_unavailable")
    try:
        cipher.db.require_practice_mode()
        cipher.db.require_write_authority()
        if not cipher.db.in_memory or cipher.db.in_transaction or cipher.db.conn.in_transaction:
            raise WorkerHeld("accounting_worker_requires_owned_memory_runtime")
        domain = Cipher.plugin(cipher, "accounting")
        if type(domain) is not Plugin or domain.c is not cipher or domain.db is not cipher.db:
            raise WorkerHeld("accounting_worker_unavailable")
        with _worker_lock:
            existing_ref = _owned_workers.get(cipher)
            existing = existing_ref() if existing_ref is not None else None
            if existing is not None:
                require_bound_worker(existing, domain=domain)
                return existing
            if domain in _runtime_adapters:
                # Losing the owned worker cannot silently initialize an empty store.
                raise WorkerHeld("simulated_store_unavailable")
            adapter = SimulatedAccountingAdapter(SimulatedAccountingRecordStore())
            worker = SimulatedAccountingWorker(domain, adapter)
            _owned_workers[cipher] = ref(worker)
            return worker
    except WorkerHeld:
        raise
    except Exception as exc:
        raise WorkerHeld("accounting_worker_unavailable") from exc


def require_worker_capability(capability: Any, *, domain: Any) -> None:
    """Private runtime admission; capability never appears in action/DTO results."""
    if type(capability) is not _WorkerCapability:
        raise WorkerHeld("unqualified_accounting_worker")
    with _worker_lock:
        binding = _capabilities.get(capability)
        if binding is None:
            raise WorkerHeld("unqualified_accounting_worker")
        worker_ref, domain_ref, adapter = binding
        worker = worker_ref()
        if (worker is None or type(worker) is not SimulatedAccountingWorker
                or domain_ref() is not domain or _workers.get(worker) != binding
                or _runtime_adapters.get(domain) is not adapter):
            raise WorkerHeld("unqualified_accounting_worker")
        attributes = object.__getattribute__(worker, "__dict__")
        if (attributes.get("_capability") is not capability or attributes.get("_domain") is not domain
                or attributes.get("_adapter") is not adapter
                or any(name in attributes or type.__getattribute__(SimulatedAccountingWorker, name) is not function
                       for name, function in _WORKER_FUNCTIONS.items())):
            raise WorkerHeld("unqualified_accounting_worker")
        require_simulator(adapter)


def verify_worker_result(capability: Any, *, domain: Any, result: dict, payload: dict,
                         payload_hash: str, logical_id: str) -> None:
    """Prove an accepted/readback result against retained immutable store facts.

    This is a pure proof check inside a local bookkeeping transaction, not an
    adapter submit/lookup/read_record call. Matching public hashes is insufficient.
    """
    require_worker_capability(capability, domain=domain)
    validate_payload(logical_id, payload, payload_hash)
    with _worker_lock:
        adapter = _capabilities[capability][2]
    record = retained_simulated_record(adapter, logical_id)
    if type(result) is dict and result.get("status") == "simulated_missing":
        expected_missing = {"status": "simulated_missing", "mode": "practice", "synthetic": True,
                            "simulation": True, "route": ROUTE, "logicalOperationId": logical_id,
                            "payloadHash": payload_hash, "quickBooksAccepted": False}
        if record is not None or canonical(result) != canonical(expected_missing):
            raise WorkerHeld("simulated_record_proof_mismatch")
        return
    if record is None:
        raise WorkerHeld("simulated_record_proof_unavailable")
    if canonical(record["payload"]) != canonical(payload):
        raise WorkerHeld("simulated_record_proof_mismatch")
    if type(result) is not dict:
        raise WorkerHeld("simulated_record_proof_mismatch")
    expected = record["acknowledgement"]
    observed = {key: value for key, value in result.items()
                if key not in ("payload", "duplicateAcknowledgement")}
    stable_expected = {key: value for key, value in expected.items()
                       if key != "duplicateAcknowledgement"}
    if (canonical(observed) != canonical(stable_expected)
            or type(result.get("duplicateAcknowledgement")) is not bool
            or "payload" in result and canonical(result["payload"]) != canonical(record["payload"])):
        raise WorkerHeld("simulated_record_proof_mismatch")
