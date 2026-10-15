"""Standard-library practice accounting simulator. No live transport exists.

Its record store is separate from Cipher's SQLite transaction, so local rollback
cannot undo simulated acceptance. This memory store is not restart-persistent.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from enum import Enum
from hashlib import sha256
import json
import re
import threading
from types import MappingProxyType
from typing import Any
from uuid import UUID
from weakref import WeakKeyDictionary

ROUTE = "practice.simulated-journal-entry.v1"
CONTRACT_VERSION = "cipher.accounting-obligation.v1"
MAX_CENTS = 10**15
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_stores: WeakKeyDictionary = WeakKeyDictionary()
_adapters: WeakKeyDictionary = WeakKeyDictionary()
_registry_lock = threading.RLock()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def copied(value: Any) -> Any:
    return json.loads(canonical(value))


class SimulationError(Exception):
    """Constant diagnostic codes only; caller text and credentials never persist."""

    def __init__(self, code: str, *, unknown: bool = False, retry_after: int = 0):
        super().__init__(code)
        self.code = code
        self.unknown = unknown
        self.retry_after = retry_after


class Fault(str, Enum):
    TIMEOUT_BEFORE_ACCEPTANCE = "timeout_before_acceptance"
    TIMEOUT_AFTER_ACCEPTANCE = "timeout_after_acceptance"
    DUPLICATE_ACK = "duplicate_ack"
    MISMATCHED_ACK = "mismatched_ack"
    VERSION_CONFLICT = "version_conflict"
    RATE_LIMIT = "rate_limit"
    CREDENTIAL_EXPIRED = "credential_expired"
    LOOKUP_TIMEOUT = "lookup_timeout"
    READBACK_MISMATCH = "readback_mismatch"


def _fail(code: str = "invalid_simulated_payload") -> None:
    raise SimulationError(code)


def _keys(value: Any, expected: set[str]) -> None:
    if type(value) is not dict or set(value) != expected:
        _fail()


def _reference(value: Any, prefix: str = "") -> None:
    if type(value) is not str or not _REFERENCE.fullmatch(value):
        _fail()
    if prefix and not value.startswith(prefix):
        _fail()


def _hash(value: Any) -> None:
    if type(value) is not str or not _HASH.fullmatch(value):
        _fail()


def _iso_date(value: Any) -> date:
    if type(value) is not str:
        _fail()
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail()
    if parsed.isoformat() != value:
        _fail()
    return parsed


def _source_binding(value: Any) -> None:
    """Bound the original opaque approved invoice snapshot; never invent fields."""
    if value is None:
        return
    if type(value) is not dict:
        _fail()
    remaining = 256
    def visit(item: Any, depth: int = 0) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 5:
            _fail()
        if item is None or type(item) is bool:
            return
        if type(item) is str:
            if len(item) > 512:
                _fail()
            return
        if type(item) is int:
            if not -MAX_CENTS < item < MAX_CENTS:
                _fail()
            return
        if type(item) is dict:
            if len(item) > 32:
                _fail()
            for key, nested in item.items():
                if type(key) is not str or not 1 <= len(key) <= 64:
                    _fail()
                visit(nested, depth + 1)
            return
        if type(item) is list and len(item) <= 64:
            for nested in item:
                visit(nested, depth + 1)
            return
        _fail()
    visit(value)


def validate_payload(logical_id: str, payload: dict, payload_hash: str) -> dict:
    """Validate the fixed normalized route without provider-selection inputs."""
    _reference(logical_id)
    try:
        parsed_id = UUID(logical_id)
    except ValueError:
        _fail()
    if str(parsed_id) != logical_id or parsed_id.version != 5:
        _fail()
    _hash(payload_hash)
    _keys(payload, {"contractVersion", "mode", "synthetic", "route",
                    "logicalOperationId", "adapter", "mapping", "source",
                    "entity", "currency", "datePolicy", "transactionDate",
                    "period", "lines"})
    if (payload["contractVersion"] != CONTRACT_VERSION
            or payload["mode"] != "practice" or payload["synthetic"] is not True
            or payload["route"] != ROUTE or payload["logicalOperationId"] != logical_id
            or payload["currency"] != "USD"
            or payload["datePolicy"] != "synthetic.period-end.v1"):
        _fail()
    _keys(payload["adapter"], {"name", "version"})
    if payload["adapter"] != {"name": "simulated-journal-entry", "version": "1"}:
        _fail()
    _keys(payload["mapping"], {"id", "version", "hash"})
    _reference(payload["mapping"]["id"])
    if type(payload["mapping"]["version"]) is not int or payload["mapping"]["version"] < 1:
        _fail()
    _hash(payload["mapping"]["hash"])
    _keys(payload["source"], {"kind", "billId", "contentHash", "sourceVersion",
                              "postingReceiptId", "postingReceiptHash", "journalId",
                              "businessApprovalId", "businessApprovalRecordId", "supplierInvoice"})
    if payload["source"]["kind"] != "bill_posting":
        _fail()
    for key in ("billId", "postingReceiptId", "journalId", "businessApprovalId",
                "businessApprovalRecordId"):
        _reference(payload["source"][key])
    for key in ("contentHash", "postingReceiptHash"):
        _hash(payload["source"][key])
    _source_binding(payload["source"]["supplierInvoice"])
    version = payload["source"]["sourceVersion"]
    if not ((type(version) is int and version > 0)
            or (type(version) is str and _REFERENCE.fullmatch(version))):
        _fail()
    if type(payload["entity"]) is not str or not 1 <= len(payload["entity"]) <= 128:
        _fail()
    _keys(payload["period"], {"id", "startDate", "endDate"})
    _reference(payload["period"]["id"])
    start = _iso_date(payload["period"]["startDate"])
    end = _iso_date(payload["period"]["endDate"])
    transaction_date = _iso_date(payload["transactionDate"])
    if start > end or transaction_date != end:
        _fail()
    if type(payload["lines"]) is not list or not 2 <= len(payload["lines"]) <= 1000:
        _fail()
    debits = credits = 0
    accounts: dict[str, str] = {}
    for line in payload["lines"]:
        _keys(line, {"sourceAccountCode", "account", "debitCents", "creditCents",
                     "projectRef", "vendorRef", "memo"})
        code = line["sourceAccountCode"]
        if code not in ("5000", "2000", "2050"):
            _fail()
        _reference(line["account"], "sim-account-")
        _reference(line["projectRef"], "sim-project-")
        _reference(line["vendorRef"], "sim-vendor-")
        if type(line["memo"]) is not str or len(line["memo"]) > 256:
            _fail()
        debit, credit = line["debitCents"], line["creditCents"]
        if (type(debit) is not int or type(credit) is not int
                or not 0 <= debit < MAX_CENTS or not 0 <= credit < MAX_CENTS
                or bool(debit) == bool(credit)):
            _fail()
        if (code == "5000" and not debit) or (code != "5000" and not credit):
            _fail()
        if code in accounts and accounts[code] != line["account"]:
            _fail()
        accounts[code] = line["account"]
        debits += debit
        credits += credit
    if not 0 < debits == credits < MAX_CENTS or "2000" not in accounts:
        _fail()
    if digest(payload) != payload_hash:
        _fail("payload_hash_mismatch")
    return copied(payload)


@dataclass(frozen=True)
class _Record:
    logical_id: str
    payload_hash: str
    payload_json: str
    record_id: str
    version: str
    record_hash: str

    @property
    def payload(self) -> dict:
        # A returned record snapshot cannot mutate the retained external fact.
        return json.loads(self.payload_json)

    def acknowledgement(self, *, duplicate: bool = False) -> dict:
        return {"status": "simulated_accepted", "mode": "practice", "synthetic": True,
                "simulation": True, "route": ROUTE,
                "logicalOperationId": self.logical_id, "payloadHash": self.payload_hash,
                "recordId": self.record_id, "recordVersion": self.version,
                "recordHash": self.record_hash, "duplicateAcknowledgement": duplicate,
                "quickBooksAccepted": False}


class SimulatedAccountingRecordStore:
    """One deterministic external effect per UUID, independent of local transactions."""

    def __init__(self):
        self._lock = threading.RLock()
        self._records: dict[str, _Record] = {}
        self._effects = 0
        with _registry_lock:
            _stores[self] = True

    @property
    def effect_count(self) -> int:
        with self._lock:
            return self._effects

    def _accept(self, logical_id: str, payload: dict, payload_hash: str) -> tuple[_Record, bool]:
        with self._lock:
            existing = self._records.get(logical_id)
            if existing:
                if existing.payload_hash != payload_hash:
                    _fail("logical_operation_payload_conflict")
                return existing, True
            version = "1"
            record_hash = digest({"logicalOperationId": logical_id, "payloadHash": payload_hash,
                                  "recordVersion": version, "payload": payload})
            record = _Record(logical_id, payload_hash, canonical(payload),
                             "SIM-JE-" + sha256(logical_id.encode()).hexdigest()[:24],
                             version, record_hash)
            self._records[logical_id] = record
            self._effects += 1
            return record, False

    def _lookup(self, logical_id: str) -> _Record | None:
        with self._lock:
            return self._records.get(logical_id)

    def _read(self, record_id: str) -> _Record | None:
        with self._lock:
            return next((record for record in self._records.values()
                         if record.record_id == record_id), None)


def require_simulator(adapter: Any) -> "SimulatedAccountingAdapter":
    # Exact type before any adapter getter avoids trusting caller-defined providers.
    if type(adapter) is not SimulatedAccountingAdapter:
        _fail("unqualified_accounting_adapter")
    with _registry_lock:
        store = _adapters.get(adapter)
        if (store is None or type(store) is not SimulatedAccountingRecordStore or store not in _stores
                or object.__getattribute__(adapter, "_store") is not store):
            _fail("unqualified_accounting_adapter")
        for instance, owner, reviewed in ((adapter, SimulatedAccountingAdapter, _ADAPTER_FUNCTIONS),
                                          (store, SimulatedAccountingRecordStore, _STORE_FUNCTIONS)):
            attributes = object.__getattribute__(instance, "__dict__")
            if any(name in attributes or type.__getattribute__(owner, name) is not function
                   for name, function in reviewed.items()):
                _fail("unqualified_accounting_adapter")
        with store._lock:
            if len(store._records) != store._effects:
                _fail("simulated_store_unavailable")
    return adapter


class SimulatedAccountingAdapter:
    """Only this initialized fixed-route adapter is admitted by the draft worker."""

    capabilities = MappingProxyType({"route": ROUTE, "mode": "practice", "synthetic": True,
                                     "stableLogicalId": True, "authoritativeLookup": True,
                                     "recordReadback": True, "realAccountingAcceptance": False})

    def __init__(self, store: SimulatedAccountingRecordStore):
        if type(store) is not SimulatedAccountingRecordStore:
            _fail("unqualified_simulated_record_store")
        with _registry_lock:
            if store not in _stores:
                _fail("unqualified_simulated_record_store")
            _adapters[self] = store
        self._store = store
        self._lock = threading.RLock()
        self._faults: dict[str, deque[Fault]] = defaultdict(deque)
        self.calls = {"submit": 0, "lookup": 0, "read_record": 0}

    def queue_fault(self, operation: str, fault: Fault) -> None:
        require_simulator(self)
        allowed = {"submit": {Fault.TIMEOUT_BEFORE_ACCEPTANCE, Fault.TIMEOUT_AFTER_ACCEPTANCE,
                               Fault.DUPLICATE_ACK, Fault.MISMATCHED_ACK, Fault.VERSION_CONFLICT,
                               Fault.RATE_LIMIT, Fault.CREDENTIAL_EXPIRED},
                   "lookup": {Fault.LOOKUP_TIMEOUT, Fault.CREDENTIAL_EXPIRED, Fault.RATE_LIMIT},
                   "read_record": {Fault.READBACK_MISMATCH, Fault.CREDENTIAL_EXPIRED,
                                   Fault.LOOKUP_TIMEOUT}}
        if operation not in allowed or type(fault) is not Fault or fault not in allowed[operation]:
            _fail("invalid_simulation_fault")
        with self._lock:
            self._faults[operation].append(fault)

    def _begin(self, operation: str) -> Fault | None:
        require_simulator(self)
        with self._lock:
            self.calls[operation] += 1
            fault = self._faults[operation].popleft() if self._faults[operation] else None
        if fault is Fault.CREDENTIAL_EXPIRED:
            raise SimulationError("simulated_credentials_expired")
        if fault is Fault.RATE_LIMIT:
            raise SimulationError("simulated_rate_limited", retry_after=1)
        if fault is Fault.VERSION_CONFLICT:
            raise SimulationError("simulated_version_conflict")
        if fault in (Fault.TIMEOUT_BEFORE_ACCEPTANCE, Fault.LOOKUP_TIMEOUT):
            raise SimulationError("simulated_timeout", unknown=True)
        return fault

    def submit(self, logical_id: str, payload: dict, payload_hash: str) -> dict:
        require_simulator(self)
        immutable_payload = validate_payload(logical_id, payload, payload_hash)
        fault = _ADAPTER_FUNCTIONS["_begin"](self, "submit")
        # Provider state changes here, before any caller-side finish_attempt transaction.
        record, duplicate = _STORE_FUNCTIONS["_accept"](self._store, logical_id, immutable_payload, payload_hash)
        if fault is Fault.TIMEOUT_AFTER_ACCEPTANCE:
            raise SimulationError("simulated_timeout", unknown=True)
        result = record.acknowledgement(duplicate=duplicate or fault is Fault.DUPLICATE_ACK)
        if fault is Fault.MISMATCHED_ACK:
            result["payloadHash"] = "f" * 64 if payload_hash != "f" * 64 else "e" * 64
        return result

    def lookup(self, logical_id: str, expected_payload_hash: str) -> dict:
        require_simulator(self)
        _reference(logical_id)
        _hash(expected_payload_hash)
        _ADAPTER_FUNCTIONS["_begin"](self, "lookup")
        record = _STORE_FUNCTIONS["_lookup"](self._store, logical_id)
        if record is None:
            return {"status": "simulated_missing", "mode": "practice", "synthetic": True,
                    "simulation": True, "route": ROUTE, "logicalOperationId": logical_id,
                    "payloadHash": expected_payload_hash, "quickBooksAccepted": False}
        if record.payload_hash != expected_payload_hash:
            _fail("logical_operation_payload_conflict")
        return record.acknowledgement(duplicate=True)

    def read_record(self, record_id: str) -> dict:
        require_simulator(self)
        _reference(record_id, "SIM-JE-")
        fault = _ADAPTER_FUNCTIONS["_begin"](self, "read_record")
        record = _STORE_FUNCTIONS["_read"](self._store, record_id)
        if record is None:
            _fail("simulated_record_missing")
        result = record.acknowledgement()
        result["payload"] = copied(record.payload)
        if fault is Fault.READBACK_MISMATCH:
            result["payload"]["lines"][0]["debitCents"] += 1
        return result


_ADAPTER_FUNCTIONS = MappingProxyType({name: type.__getattribute__(SimulatedAccountingAdapter, name)
                                     for name in ("submit", "lookup", "read_record", "_begin")})
_STORE_FUNCTIONS = MappingProxyType({name: type.__getattribute__(SimulatedAccountingRecordStore, name)
                                   for name in ("_accept", "_lookup", "_read")})


def invoke_simulator(adapter: Any, operation: str, *args: Any) -> dict:
    """Invoke captured reviewed functions, never an instance-rebound provider hook."""
    require_simulator(adapter)
    if operation not in ("submit", "lookup", "read_record"):
        _fail("invalid_simulated_operation")
    return _ADAPTER_FUNCTIONS[operation](adapter, *args)


def retained_simulated_record(adapter: Any, logical_id: str) -> dict | None:
    """Pure internal proof read, not a provider call or a delivery operation.

    The trusted domain uses this after a call to prove an accepted record exists.
    It performs no SQL, transport, attempts, counters or payment/journal effects.
    """
    require_simulator(adapter)
    with _registry_lock:
        store = _adapters[adapter]
    record = _STORE_FUNCTIONS["_lookup"](store, logical_id)
    if record is None:
        return None
    return {"acknowledgement": record.acknowledgement(), "payload": record.payload}
