"""Fixed accounting actions and durable, audited practice worker invocations.

Human effects stay atomic. Worker reservations and linked attempts commit before
the separate simulator call; observations and API receipts commit afterwards.
Importing this module does not register a schema or initialize a provider.
"""
from __future__ import annotations

from collections import Counter
import re
import threading
from uuid import UUID
from weakref import WeakKeyDictionary, ref

from .ap_actions import APActionRunner, CONTRACT_VERSION
from .ap_contract import APRefusal
from .ap_intake_actions import APIntakeActionRunner
from .core.api_receipts import APIReceiptIntegrityError, APIRepeatabilityConflict, AP_ACCOUNTING_INVOCATION_SCHEMA_STATEMENTS
from .core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash
from .core.ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow, utcnow_iso
from .domain.accounting import AccountingError, OP_QUEUE

HUMAN_ACTIONS = frozenset(("accounting.prepare", "accounting.request", "accounting.approve", "accounting.queue"))
WORKER_ACTIONS = frozenset(("accounting.deliver", "accounting.lookup", "accounting.reconcile"))
ACTIONS = HUMAN_ACTIONS | WORKER_ACTIONS
_bindings = WeakKeyDictionary()
_binding_lock = threading.RLock()
_ENTITY = "ap_accounting_invocation"
_TABLE = "ap_accounting_invocations"
_RESULT_LABELS = {"simulation": True, "quickBooksAccepted": False, "journalCountDelta": 0, "apBalanceDeltaCents": 0}


def _same_json(left, right):
    """Compare original facts without Python's bool/int/float aliases."""
    return canonical_json(left) == canonical_json(right)


def require_invocation_store(store, *, domain, worker_capability):
    """Admit only the concrete initialized store bound to this exact runtime."""
    from .accounting_worker import require_bound_worker, require_worker_capability
    from .domain.accounting import Plugin
    from .service import Cipher
    if type(store) is not APAccountingInvocations:
        raise APIReceiptIntegrityError("Unqualified accounting invocation store")
    with _binding_lock:
        binding = _bindings.get(store)
        if (type(store.cipher) is not Cipher or type(domain) is not Plugin
                or Cipher.plugin(store.cipher, "accounting") is not domain
                or binding is None or tuple(item() for item in binding) != (store.cipher, domain, store.worker)
                or store.domain is not domain or domain.db is not store.db
                or domain.c is not store.cipher or store.cipher.db is not store.db):
            raise APIReceiptIntegrityError("Accounting invocation store belongs to another runtime")
        require_bound_worker(store.worker, domain=domain)
        require_worker_capability(worker_capability, domain=domain)
        if object.__getattribute__(store.worker, "__dict__").get("_capability") is not worker_capability:
            raise APIReceiptIntegrityError("Invocation store requires its original worker")
        if any(name in object.__getattribute__(store, "__dict__") or getattr(APAccountingInvocations, name) is not method
               for name, method in _STORE_METHODS.items()):
            raise APIReceiptIntegrityError("Accounting invocation store methods changed")
    return store


def bind_accounting_invocations(cipher, worker):
    from .accounting_worker import require_bound_worker
    from .service import Cipher
    from .domain.accounting import Plugin
    if type(cipher) is not Cipher:
        raise APIReceiptIntegrityError("Accounting invocation store requires its initialized Cipher runtime")
    domain = cipher.plugin("accounting")
    if type(domain) is not Plugin or domain.c is not cipher or domain.db is not cipher.db:
        raise APIReceiptIntegrityError("Accounting invocation store requires its initialized accounting domain")
    require_bound_worker(worker, domain=domain)
    with _binding_lock:
        for store, binding in list(_bindings.items()):
            if binding[0]() is cipher:
                require_invocation_store(store, domain=domain, worker_capability=worker._capability)
                if binding[2]() is not worker:
                    raise APIReceiptIntegrityError("Accounting runtime already has another worker")
                return store
        store = APAccountingInvocations(cipher, worker)
        _bindings[store] = (ref(cipher), ref(domain), ref(worker))
        domain.bind_invocations(store, worker_capability=worker._capability)
        return store

def invocation_proof(db, audit, invocation_id):
    """Pure original reservation proof, without worker admission or calls."""
    _invocation_storage_proof(db, audit)
    row = db.one(f"SELECT * FROM {_TABLE} WHERE id=?", (invocation_id,))
    if row is None:
        raise APIReceiptIntegrityError("An audited accounting invocation disappeared")
    body = loads(row["body_json"])
    if (type(body) is not dict or canonical_json(body) != row["body_json"] or hash_json(body) != row["row_hash"]
            or canonical_json(body.get("binding")) != row["binding_json"] or hash_json(body.get("binding")) != row["binding_hash"]
            or any(body.get(key) != value for key, value in row.items() if key not in ("binding_json", "body_json", "row_hash", "audit_seq"))
            or body["workspace_id"] != db.workspace()["workspace_id"]):
        raise APIReceiptIntegrityError("Accounting invocation original binding changed")
    history = db.query("SELECT * FROM audit_log WHERE entity_type=? AND entity_id=? ORDER BY seq", (_ENTITY, invocation_id))
    previous = None
    immutable = ("id", "workspace_id", "canonical_person_id", "actor_login", "repeatability_uuid", "contract_version", "fixed_action", "resource_id", "binding", "binding_hash", "reviewed_source", "created_at", "plan_id", "logical_operation_id", "payload_hash")
    legal = {None: {"reserved"}, "reserved": {"claimed"}, "claimed": {"claimed", "awaiting_observation", "observed"},
             "awaiting_observation": {"claimed", "observed"}, "observed": {"completed"}, "completed": set()}
    for number, event in enumerate(history):
        snap = loads(event["payload_json"])
        state = snap.get("state")
        if (event["action"] != ("ap.accounting_invocation_reserved" if number == 0 else "ap.accounting_invocation_changed")
                or event["actor"] != body["actor_login"] or type(state) is not dict or state.get("revision") != number
                or state.get("state") not in legal[None if previous is None else previous["state"]]
                or hash_json(state) != snap.get("rowHash") or any(state.get(key) != body.get(key) for key in immutable)
                or previous is not None and state.get("attempt_ids", [])[:len(previous["attempt_ids"])] != previous["attempt_ids"]):
            raise APIReceiptIntegrityError("Accounting invocation lifecycle lacks its original audited chronology")
        previous = state
    if not history or previous != body or history[-1]["seq"] != row["audit_seq"]:
        raise APIReceiptIntegrityError("Accounting invocation current revision is not its audited revision")
    return body


def _invocation_storage_proof(db, audit):
    if not audit.verify_chain()["ok"]:
        raise APIReceiptIntegrityError("Accounting invocation audit chain is broken")
    for sql in AP_ACCOUNTING_INVOCATION_SCHEMA_STATEMENTS:
        match = re.match(r"CREATE TRIGGER (\w+)", sql)
        if match:
            row = db.one("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (match[1],))
            normalize = lambda value: re.sub(r"\s+", " ", value.strip())
            if row is None or normalize(row["sql"]) != normalize(sql):
                raise APIReceiptIntegrityError("Accounting invocation storage guards changed")


def invocation_inventory_proof(db, audit):
    _invocation_storage_proof(db, audit)
    rows = db.query(f"SELECT id FROM {_TABLE}")
    births = db.query("SELECT entity_id FROM audit_log WHERE action='ap.accounting_invocation_reserved' AND entity_type=?", (_ENTITY,))
    identifiers = [row["entity_id"] for row in births]
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != {row["id"] for row in rows}:
        raise APIReceiptIntegrityError("Accounting invocation inventory differs from its original audited births")
    return [invocation_proof(db, audit, identifier) for identifier in identifiers]


class APAccountingInvocations:
    """Concrete local reservation store; no method calls a provider."""

    def __init__(self, cipher, worker):
        self.cipher, self.db, self.audit = cipher, cipher.db, cipher.audit
        self.domain, self.worker = cipher.plugin("accounting"), worker
        self._phase_before = {}

    def _admit(self):
        require_invocation_store(self, domain=self.domain, worker_capability=self.worker._capability)

    def _guards(self):
        self._admit()
        if not self.audit.verify_chain()["ok"]:
            raise APIReceiptIntegrityError("Accounting invocation audit chain is broken")
        for sql in AP_ACCOUNTING_INVOCATION_SCHEMA_STATEMENTS:
            match = re.match(r"CREATE TRIGGER (\w+)", sql)
            if match:
                row = self.db.one("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (match[1],))
                normalize = lambda value: re.sub(r"\s+", " ", value.strip())
                if row is None or normalize(row["sql"]) != normalize(sql):
                    raise APIReceiptIntegrityError("Accounting invocation storage guards changed")

    def _require_transaction(self):
        self._admit()
        if not self.db.conn.in_transaction:
            raise APIReceiptIntegrityError("Accounting invocation effect requires its atomic transaction")

    def _write(self, body, *, birth=False):
        self._require_transaction()
        serialized, row_hash = canonical_json(body), hash_json(body)
        event = self.audit.record(body["actor_login"], "ap.accounting_invocation_reserved" if birth else "ap.accounting_invocation_changed",
                                  _ENTITY, body["id"], {"rowHash": row_hash, "state": body})
        if birth:
            row = {key: body[key] for key in ("id", "workspace_id", "canonical_person_id", "actor_login", "repeatability_uuid",
                   "contract_version", "fixed_action", "resource_id", "binding_hash", "state", "revision")}
            row.update(binding_json=canonical_json(body["binding"]), body_json=serialized, row_hash=row_hash, audit_seq=event["seq"])
            keys = list(row)
            self.db.execute(f"INSERT INTO {_TABLE} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", tuple(row[key] for key in keys))
        else:
            self.db.execute(f"UPDATE {_TABLE} SET state=?,revision=?,body_json=?,row_hash=?,audit_seq=? WHERE id=?",
                            (body["state"], body["revision"], serialized, row_hash, event["seq"], body["id"]))
        return body

    def _change(self, body, **changes):
        return self._write({**body, **changes, "revision": body["revision"]+1, "updated_at": utcnow_iso()})

    def get(self, invocation_id):
        self._guards()
        body = invocation_proof(self.db, self.audit, invocation_id)
        self._source(body)
        return body

    def inventory(self):
        self._guards()
        rows = self.db.query(f"SELECT id FROM {_TABLE}")
        births = self.db.query("SELECT entity_id FROM audit_log WHERE action='ap.accounting_invocation_reserved' AND entity_type=?", (_ENTITY,))
        identifiers = [event["entity_id"] for event in births]
        if len(identifiers) != len(set(identifiers)) or set(identifiers) != {row["id"] for row in rows}:
            raise APIReceiptIntegrityError("Accounting invocation inventory differs from its audited births")
        return [self.get(identifier) for identifier in identifiers]

    def find(self, person_id, repeatability_uuid):
        self.inventory()
        row = self.db.one(f"SELECT id FROM {_TABLE} WHERE canonical_person_id=? AND repeatability_uuid=?", (person_id, repeatability_uuid))
        return None if row is None else self.get(row["id"])

    def reserve(self, *, person_id, actor_login, action, intent_id, repeatability_uuid, binding, reviewed_source):
        self._require_transaction()
        self.inventory()
        if action not in WORKER_ACTIONS or self.find(person_id, repeatability_uuid) is not None:
            raise APIReceiptIntegrityError("Accounting invocation key already belongs to its original reservation")
        intent = self.domain.intent(intent_id)
        plan = self.domain.plan(intent["plan_id"])
        now = utcnow_iso()
        body = {"id": new_id("acinv"), "workspace_id": self.db.workspace()["workspace_id"], "canonical_person_id": person_id,
                "actor_login": actor_login, "repeatability_uuid": repeatability_uuid, "contract_version": CONTRACT_VERSION,
                "fixed_action": action, "resource_id": intent_id, "binding": binding, "binding_hash": hash_json(binding),
                "state": "reserved", "revision": 0, "reviewed_source": loads(canonical_json(reviewed_source)),
                "plan_id": plan["id"], "logical_operation_id": plan["logical_operation_id"], "payload_hash": plan["payload_hash"],
                "attempt_ids": [], "observation": None, "result": None, "receipt_id": None, "created_at": now, "updated_at": now}
        return self._write(body, birth=True)

    def _source(self, body):
        intent = self.domain.intent(body["resource_id"])
        plan = self.domain.plan(body["plan_id"])
        if (intent["plan_id"] != plan["id"] or plan["logical_operation_id"] != body["logical_operation_id"]
                or plan["payload_hash"] != body["payload_hash"]):
            raise APIReceiptIntegrityError("Accounting invocation original intent source changed")
        for attempt_id in body["attempt_ids"]:
            attempt = self.domain._proof("attempts", attempt_id)
            if (attempt.get("invocation_id") != body["id"] or attempt.get("invocation_hash") != body["binding_hash"]
                    or attempt["intent_id"] != body["resource_id"] or attempt["created_by"] != body["actor_login"]
                    or attempt["payload_hash"] != body["payload_hash"]):
                raise APIReceiptIntegrityError("Accounting attempt lost its original API invocation link")
        if body["observation"] is not None:
            result, proof = self.observation(body["id"], body=body)
            if not _same_json(result, body["result"]) or not _same_json(proof, body["observation"]):
                raise APIReceiptIntegrityError("Accounting invocation outcome differs from its original observation")

    def require_claim(self, invocation_id, *, intent_id, actor_login, logical_operation_id, payload_hash,
                      purpose, worker_capability, person_id=None, action=None):
        self._admit()
        require_invocation_store(self, domain=self.domain, worker_capability=worker_capability)
        body = self.get(invocation_id)
        wanted = {"accounting.deliver": "delivery", "accounting.lookup": "lookup", "accounting.reconcile": "reconciliation"}[body["fixed_action"]]
        if (body["resource_id"] != intent_id or body["actor_login"] != actor_login or body["logical_operation_id"] != logical_operation_id
                or body["payload_hash"] != payload_hash or purpose != wanted or body["state"] not in ("reserved", "claimed", "awaiting_observation")
                or person_id is not None and person_id != body["canonical_person_id"] or action is not None and action != body["fixed_action"]):
            raise APIReceiptIntegrityError("Accounting claim does not belong to its original reviewed invocation")
        authority = self.domain.require_accountant(actor_login, self.domain.plan(body["plan_id"])["project_id"])
        if authority["personId"] != body["canonical_person_id"]:
            raise APIReceiptIntegrityError("Accounting invocation canonical caller changed")
        intent = self.domain.intent(intent_id)
        if body["attempt_ids"] and intent["active_attempt_id"] == body["attempt_ids"][-1]:
            lease = self.domain._proof("leases", intent["last_lease_id"])
            if parse_iso(lease["expires_at"]) > utcnow():
                return body
        current = self.domain.worker_preflight(intent_id, actor=actor_login, purpose=purpose)
        if not body["attempt_ids"]:
            if canonical_json(current) != canonical_json(body["reviewed_source"]):
                raise StaleApprovalError("Accounting worker facts changed after reservation")
        elif purpose != "reconciliation" and current["provider_purpose"] != "lookup":
            raise APIReceiptIntegrityError("An unfinished API invocation can only recover its original UUID by lookup")
        self._phase_before[(invocation_id, "claim")] = self._phase_snapshot()
        return body

    def record_claim(self, invocation_id, *, attempt_id, phase, lease_id):
        self._require_transaction()
        # The just-created attempt is linked here in the same claim transaction;
        # source inventory is complete only after this append.
        body = invocation_proof(self.db, self.audit, invocation_id)
        attempt = self.domain._proof("attempts", attempt_id)
        lease = self.domain._proof("leases", lease_id)
        if (attempt.get("invocation_id") != invocation_id or attempt.get("invocation_hash") != body["binding_hash"]
                or attempt["lease_id"] != lease_id or attempt["purpose"] != phase or attempt["intent_id"] != body["resource_id"]
                or attempt["created_by"] != body["actor_login"] or lease["claimed_by"] != body["actor_login"]
                or attempt_id in body["attempt_ids"] or body["state"] not in ("reserved", "claimed", "awaiting_observation")):
            raise APIReceiptIntegrityError("Accounting API claim is not its exact immutable attempt")
        updated = self._change(body, state="claimed", attempt_ids=[*body["attempt_ids"], attempt_id])
        self._verify_phase(invocation_id, "claim", additions={"accounting_attempts": {attempt_id}, "accounting_leases": {lease_id}},
                           events=[("accounting.attempts_recorded", "accounting_attempts", attempt_id),
                                   ("accounting.leases_recorded", "accounting_leases", lease_id)])
        return updated

    def _phase_snapshot(self):
        snapshot = APActionRunner._control_snapshot(self)
        names = {"accounting_intents", "accounting_leases", "accounting_attempts", "accounting_attempt_results", "accounting_acceptances",
                 "accounting_reconciliations", _TABLE}
        snapshot["effectRows"] = {name: self.db.query(f"SELECT * FROM {name}") for name in names}
        return snapshot

    def begin_observation(self, invocation_id, *, attempt_id):
        self._require_transaction()
        body = self.get(invocation_id)
        if body["state"] != "claimed" or body["attempt_ids"][-1] != attempt_id:
            raise APIReceiptIntegrityError("Observation requires the original current claimed attempt")
        self._phase_before[(invocation_id, "observation")] = self._phase_snapshot()

    def _verify_phase(self, invocation_id, phase, *, additions, events):
        before = self._phase_before.pop((invocation_id, phase), None)
        if before is None:
            raise APIReceiptIntegrityError("Accounting worker phase lacks its locked original effect boundary")
        after = self._phase_snapshot()
        body = invocation_proof(self.db, self.audit, invocation_id)
        changes = {"accounting_intents": {body["resource_id"]: {"status", "body_json", "row_hash"}},
                   _TABLE: {invocation_id: {"state", "revision", "body_json", "row_hash", "audit_seq"}}}
        allowed = set(additions) | set(changes)
        if (before["schema"] != after["schema"] or before["tables"].keys() != after["tables"].keys()
                or before["approvals"] != after["approvals"]):
            raise APIReceiptIntegrityError("Accounting worker changed schema or human authorization")
        for table, value in before["tables"].items():
            if table not in allowed and value != after["tables"][table]:
                raise APIReceiptIntegrityError("Accounting worker introduced an unrelated source or financial effect")
        for table in before["effectRows"]:
            APIntakeActionRunner._row_effect(before, after, table, added=additions.get(table, ()), changed=changes.get(table))
        expected = [*events, ("accounting.intent_changed", "accounting_intents", body["resource_id"]),
                    ("ap.accounting_invocation_changed", _ENTITY, invocation_id)]
        actual = after["audit"][len(before["audit"]):]
        if (before["audit"] != after["audit"][:len(before["audit"])]
                or Counter((event["action"], event["entity_type"], event["entity_id"]) for event in actual) != Counter(expected)
                or any(event["actor"] != body["actor_login"] for event in actual)):
            raise APIReceiptIntegrityError("Accounting worker audit effects exceed its exact original phase")

    def observation(self, invocation_id, *, body=None):
        body = self.get(invocation_id) if body is None else body
        results = [row for row in self.domain._inventory("attempt_results") if row["attempt_id"] in body["attempt_ids"]]
        if not results:
            raise APIReceiptIntegrityError("Accounting invocation has no committed observation")
        # A completed invocation retains the first committed outcome forever.
        result_row = results[0]
        attempt = self.domain._proof("attempts", result_row["attempt_id"])
        if result_row["intent_id"] != body["resource_id"] or result_row["recorded_by"] != body["actor_login"]:
            raise APIReceiptIntegrityError("Accounting observation belongs to another original invocation")
        acceptance = next((row for row in self.domain._inventory("acceptances") if result_row["outcome"] == "simulated_accepted"
                           and row["intent_id"] == body["resource_id"] and row["result"] == result_row["provider_result"]), None)
        reconciliation = next((row for row in self.domain._inventory("reconciliations") if row["attempt_id"] == attempt["id"]), None)
        if reconciliation is not None:
            acceptance = self.domain._proof("acceptances", reconciliation["acceptance_id"])
            if reconciliation.get("readback") is not None:
                self.domain._worker_result(self.worker._capability, self.domain.intent(body["resource_id"]), reconciliation["readback"])
        if result_row["outcome"] == "simulated_accepted":
            if acceptance is None:
                raise APIReceiptIntegrityError("Original accounting acceptance disappeared")
            self.domain._worker_result(self.worker._capability, self.domain.intent(body["resource_id"]), result_row["provider_result"])
        status = "reconciled" if result_row["outcome"] == "reconciliation_matched" else result_row["outcome"]
        result = {**_RESULT_LABELS, "invocationId": body["id"], "intentId": body["resource_id"],
                  "logicalOperationId": body["logical_operation_id"], "status": status}
        if acceptance is not None:
            result.update(recordId=acceptance["provider_ref"], recordVersion=acceptance["result"]["recordVersion"])
        proof = {"intentId": body["resource_id"], "attemptId": attempt["id"], "invocationId": body["id"],
                 "payloadHash": body["payload_hash"], "logicalOperationId": body["logical_operation_id"],
                 "attemptResultId": result_row["id"], "acceptanceId": None if acceptance is None else acceptance["id"],
                 "reconciliationId": None if reconciliation is None else reconciliation["id"]}
        return result, proof

    def record_observation(self, invocation_id, *, attempt_id, source_proof, safe_result=None):
        self._require_transaction()
        body = self.get(invocation_id)
        result, proof = self.observation(invocation_id, body=body)
        if (body["state"] not in ("claimed", "awaiting_observation") or proof["attemptId"] != attempt_id
                or not _same_json(source_proof, proof) or safe_result is not None and not _same_json(safe_result, result)):
            raise APIReceiptIntegrityError("Accounting observation is not this invocation's exact committed outcome")
        updated = self._change(body, state="observed", observation=proof, result=result)
        additions = {"accounting_attempt_results": {proof["attemptResultId"]}}
        events = [("accounting.attempt_results_recorded", "accounting_attempt_results", proof["attemptResultId"])]
        if proof["acceptanceId"] is not None and proof["reconciliationId"] is None:
            additions["accounting_acceptances"] = {proof["acceptanceId"]}
            events.append(("accounting.acceptances_recorded", "accounting_acceptances", proof["acceptanceId"]))
        if proof["reconciliationId"] is not None:
            additions["accounting_reconciliations"] = {proof["reconciliationId"]}
            events.append(("accounting.reconciliations_recorded", "accounting_reconciliations", proof["reconciliationId"]))
        self._verify_phase(invocation_id, "observation", additions=additions, events=events)
        return updated

    def complete(self, invocation_id, *, person_id, receipt_id):
        self._require_transaction()
        body = self.get(invocation_id)
        if body["canonical_person_id"] != person_id or body["state"] != "observed":
            raise APIReceiptIntegrityError("Only the original observed invocation can complete")
        row = self.db.one("SELECT * FROM ap_action_receipts WHERE id=?", (receipt_id,))
        if (row is None or row["canonical_person_id"] != person_id or row["repeatability_uuid"] != body["repeatability_uuid"]
                or row["binding_json"] != canonical_json(body["binding"]) or row["result_json"] != canonical_json(body["result"])):
            raise APIReceiptIntegrityError("Accounting API completion lacks its original receipt")
        return self._change(body, state="completed", receipt_id=receipt_id)


_STORE_METHODS = {name: getattr(APAccountingInvocations, name) for name in
                  ("_admit", "_guards", "_require_transaction", "_write", "_change", "get", "inventory", "find", "reserve", "_source",
                   "require_claim", "record_claim", "_phase_snapshot", "begin_observation", "_verify_phase", "observation", "record_observation", "complete")}


class APAccountingActionRunner(APIntakeActionRunner):
    def __init__(self, cipher, contract, preflight, *, worker):
        super().__init__(cipher, contract, preflight)
        self.domain, self.worker = cipher.plugin("accounting"), worker
        self.invocations = bind_accounting_invocations(cipher, worker)

    def _event_row(self, proof):
        row = super()._event_row(proof)
        if not _same_json(proof, {"seq": row["seq"], "hash": row["entry_hash"]}):
            raise APIReceiptIntegrityError("An accounting source event differs from its original typed reference")
        return row

    def _shape(self, action, resource_id, body, key, if_match):
        if action not in ACTIONS or type(resource_id) is not str or not resource_id or len(resource_id) > 160:
            raise APRefusal(422, "invalid_action", "Choose a supported accounting action.")
        try:
            normalized = str(UUID(key)) if type(key) is str and len(key) == 36 else None
        except ValueError:
            normalized = None
        if normalized is None or normalized != key.casefold():
            raise APRefusal(422, "invalid_repeatability_key", "Repeatability-Request-ID must be a UUID.")
        if type(if_match) is not str or not if_match or len(if_match) > 256:
            raise APRefusal(422, "missing_record_version", "Supply the record version reviewed for this action.")
        self.preflight._body(action, body, action_body=True)
        fingerprint = body.get("fingerprint")
        if type(fingerprint) is not str or not fingerprint or len(fingerprint) > 256:
            raise APRefusal(422, "invalid_fingerprint", "Supply the preflight fingerprint for this review.")
        return normalized, {"contractVersion": CONTRACT_VERSION, "fixedAction": action, "resourceId": resource_id,
                            "canonicalTypedBody": {"fingerprint": fingerprint}, "originalIfMatch": if_match,
                            "preflightFingerprint": fingerprint}

    def run(self, person_id, action, resource_id, body, *, repeatability_key, if_match):
        key, binding = self._shape(action, resource_id, body, repeatability_key, if_match)
        try:
            if action in WORKER_ACTIONS:
                return self._worker_run(person_id, action, resource_id, body, key, binding, if_match)
            return self._human_run(person_id, action, resource_id, body, key, binding, if_match)
        except APRefusal:
            raise
        except APIRepeatabilityConflict:
            raise APRefusal(409, "repeatability_conflict", "This key belongs to a different original reviewed request.") from None
        except PermissionError:
            raise APRefusal(403, "action_not_authorized", "Your current project duties do not permit this accounting action.") from None
        except (AccountingError, ApprovalError):
            raise APRefusal(409, "action_refused", "The accounting action cannot proceed. Refresh its review.") from None
        except Exception:
            raise APRefusal(500, "action_unavailable", "The accounting action did not complete. Retry the same reviewed request.") from None

    def _replay(self, person, key, binding):
        self.receipts.require_repeatability_namespace(person, key, binding["fixedAction"], binding)
        receipt = self.receipts.find(person, key)
        if receipt is None:
            return None
        if receipt["binding_json"] != canonical_json(binding):
            raise APRefusal(409, "repeatability_conflict", "This repeatability key belongs to a different reviewed request.")
        self._verify_source(receipt)
        if receipt["outcome"] == "refused":
            raise self._stored_refusal(receipt, replayed=True)
        return self._response(receipt, replayed=True)

    def _human_run(self, person_id, action, resource_id, body, key, binding, if_match):
        deferred = None
        with self._transaction():
            self.cipher.db.require_practice_mode()
            context = self.preflight.authorize(person_id, action, resource_id)
            person = context["personId"]
            replay = self._replay(person, key, binding)
            if replay is not None:
                return replay
            if self.invocations.find(person, key) is not None:
                raise APRefusal(409, "repeatability_conflict", "This key belongs to its original worker invocation.")
            checked = self.preflight.verify(person_id, action, resource_id, body, if_match)
            if checked["personId"] != person or checked["login"] != context["login"]:
                raise APIReceiptIntegrityError("Accounting authority changed during the locked review")
            before = self._accounting_snapshot()
            plan, manifest = loads(canonical_json(checked["plan"])), loads(canonical_json(checked.get("manifest")))
            try:
                result, source = self._human_act(action, resource_id, checked)
            except (StaleApprovalError, ApprovalExpired) as exc:
                status = 423 if isinstance(exc, ApprovalExpired) else 412
                source = self._terminal_source(action, resource_id, context, before, status)
                result = {"code": "approval_expired" if status == 423 else "approval_stale", "message": "The handoff authorization changed. Request fresh approval.", "target": resource_id}
                receipt = self.receipts.record(person_id=person, actor_login=context["login"], repeatability_uuid=key,
                    contract_version=CONTRACT_VERSION, action=action, resource_id=resource_id, binding=binding,
                    outcome="refused", http_status=status, result=result, source=source)
                deferred = self._stored_refusal(receipt, replayed=False)
            else:
                self._reviewed_human_plan(action, resource_id, checked, plan, manifest, source)
                receipt = self.receipts.record(person_id=person, actor_login=context["login"], repeatability_uuid=key,
                    contract_version=CONTRACT_VERSION, action=action, resource_id=resource_id, binding=binding,
                    outcome="success", http_status=200, result=result, source=source)
            self._verify_source(receipt)
            self._human_boundary(action, resource_id, before, receipt, source)
            response = self._response(receipt, replayed=False)
        if deferred is not None:
            raise deferred
        return response

    def _human_act(self, action, resource_id, context):
        conn, savepoint = self.cipher.db.conn, new_id("accounting_act")
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            if action == "accounting.prepare":
                plan = self.domain.prepare(resource_id, context["mapping"]["id"], actor=context["login"])
                result = {"planId": plan["id"], "billId": resource_id, "status": "prepared"}
                source = {"kind": "plan", "planId": plan["id"], "plan": plan}
            elif action == "accounting.request":
                approval = self.cipher.request_approval(OP_QUEUE, resource_id, actor_role="accountant", requested_by=context["login"])
                result = {"approvalId": approval["id"], "planId": resource_id, "status": "pending"}
                source = {"kind": "request", "approvalId": approval["id"], "planId": resource_id, "proof": self.domain.approval_proof(approval["id"])}
            elif action == "accounting.approve":
                self.cipher.approve(resource_id, approver=context["login"], approver_role="accountant")
                result = {"approvalId": resource_id, "planId": context["approval"]["subject_id"], "status": "granted"}
                source = {"kind": "grant", "approvalId": resource_id, "planId": result["planId"], "proof": self.domain.approval_proof(resource_id), "event": self._event("approval.granted", "approval", resource_id)}
            else:
                done = self.cipher.execute(resource_id, actor=context["login"])
                intent = self.domain.intent(done.result["intent_id"])
                result = {"intentId": intent["id"], "approvalId": resource_id, "planId": intent["plan_id"], "status": "queued"}
                source = {"kind": "queue", "intentId": intent["id"], "approvalId": resource_id, "planId": intent["plan_id"],
                          "proof": self.domain.approval_proof(resource_id), "commandId": done.op_id,
                          "birth": self._event("accounting.intent_queued", "accounting_intents", intent["id"])}
        except (StaleApprovalError, ApprovalExpired) as exc:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
            if action in ("accounting.approve", "accounting.queue"):
                ap = self.cipher.approvals.get(resource_id)
                if ap["status"] == ("pending" if action == "accounting.approve" else "granted"):
                    if isinstance(exc, ApprovalExpired):
                        self.cipher.approvals.mark_expired(resource_id, actor=context["login"])
                    else:
                        self.cipher.approvals.invalidate(resource_id, reason=str(exc), actor=context["login"])
            raise
        except BaseException:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
            raise
        else:
            conn.execute(f"RELEASE {savepoint}")
            return {**_RESULT_LABELS, **result}, source

    def _reviewed_human_plan(self, action, resource_id, context, plan, manifest, source):
        if action == "accounting.prepare":
            actual = self.domain.plan(source["planId"])
            if actual["payload"] != plan["payload"] or actual["payload_hash"] != plan["payload_hash"] or actual["prepared_by"] != context["login"]:
                raise APIReceiptIntegrityError("Prepared accounting plan differs from its complete reviewed payload")
        else:
            ap = self.cipher.approvals.get(source["approvalId"])
            if material_hash(manifest) != ap["material_hash"] or manifest.get("governance") != ap["manifest"].get("governance"):
                raise APIReceiptIntegrityError("Accounting effect differs from its complete reviewed manifest")
            if action == "accounting.queue":
                intent = self.domain.intent(source["intentId"])
                if intent["plan_id"] != ap["subject_id"] or intent["approval_id"] != ap["id"] or intent["status"] != "queued":
                    raise APIReceiptIntegrityError("Accounting queue differs from its reviewed authorization")

    def _accounting_snapshot(self):
        snapshot = APActionRunner._control_snapshot(self)
        names = {"accounting_plans", "accounting_intents", "approvals", "idempotency", "ap_action_receipts"}
        snapshot["effectRows"] = {name: self.cipher.db.query(f"SELECT * FROM {name}") for name in names}
        return snapshot

    def _human_boundary(self, action, resource_id, before, receipt, source):
        after = self._accounting_snapshot()
        allowed = {"ap_action_receipts"}
        additions, changes = {"ap_action_receipts": {receipt["id"]}}, {}
        events = [("ap.practice_action_recorded", "ap_action_receipt", receipt["id"])]
        if source["kind"] == "refusal":
            allowed.add("approvals")
            changes["approvals"] = {resource_id: {"status", "invalidated_reason"}}
            events.append(("approval."+source["status"], "approval", resource_id))
        elif action == "accounting.prepare":
            allowed.add("accounting_plans")
            additions["accounting_plans"] = {source["planId"]}
            events.append(("accounting.plans_recorded", "accounting_plans", source["planId"]))
        elif action == "accounting.request":
            allowed.add("approvals")
            additions["approvals"] = {source["approvalId"]}
            events.append(("approval.requested", "approval", source["approvalId"]))
        elif action == "accounting.approve":
            allowed.add("approvals")
            changes["approvals"] = {resource_id: {"status", "approver", "granted_at"}}
            events.append(("approval.granted", "approval", resource_id))
        else:
            allowed.update(("approvals", "accounting_intents", "idempotency"))
            additions.update(accounting_intents={source["intentId"]}, idempotency={source["commandId"]})
            changes["approvals"] = {resource_id: {"status", "consumed_by", "consumed_at"}}
            events.extend((("approval.consumed", "approval", resource_id), ("accounting.intent_queued", "accounting_intents", source["intentId"]), ("command.executed", "command", source["commandId"])))
        if before["schema"] != after["schema"] or before["tables"].keys() != after["tables"].keys():
            raise APIReceiptIntegrityError("Accounting action changed workspace schema")
        for table, value in before["tables"].items():
            if table not in allowed and after["tables"][table] != value:
                raise APIReceiptIntegrityError("Accounting action changed facts outside its fixed resource")
        if "approvals" not in allowed and before["approvals"] != after["approvals"]:
            raise APIReceiptIntegrityError("Accounting action changed unrelated approvals")
        for table in before["effectRows"]:
            self._row_effect(before, after, table, added=additions.get(table, ()), changed=changes.get(table))
        actual = after["audit"][len(before["audit"]):]
        if (after["audit"][:len(before["audit"])] != before["audit"]
                or Counter((e["action"], e["entity_type"], e["entity_id"]) for e in actual) != Counter(events)
                or any(e["actor"] != receipt["actor_login"] for e in actual)):
            raise APIReceiptIntegrityError("Accounting action introduced an unreviewed audit effect")

    def _terminal_source(self, action, resource_id, context, before, status):
        if action not in ("accounting.approve", "accounting.queue"):
            raise APIReceiptIntegrityError("Only the reviewed original accounting approval may refuse terminally")
        old = next(row for row in before["approvals"] if row["id"] == resource_id)
        ap = self.cipher.approvals.get(resource_id)
        expected = "expired" if status == 423 else "invalidated"
        if old["status"] != ("pending" if action == "accounting.approve" else "granted") or ap["status"] != expected:
            raise APIReceiptIntegrityError("Accounting refusal changed another approval lifecycle")
        if status == 423:
            from .core import approvals as approval_clock
            if parse_iso(ap["expires_at"]) > approval_clock.utcnow():
                raise APIReceiptIntegrityError("Accounting refusal claimed an unexpired approval")
        if status == 412:
            try:
                # Verify changed source independently of the now terminal row.
                current = self.cipher._manifest(OP_QUEUE, ap["subject_id"], "accountant")
                changed = material_hash(current) != ap["material_hash"] or current.get("governance") != ap["manifest"].get("governance")
                if not changed:
                    if action == "accounting.queue":
                        self.domain.require_accountant(ap["approver"], context["projectId"])
                    raise APIReceiptIntegrityError("Accounting source does not prove the claimed stale transition")
            except AccountingError:
                pass
        return {"kind": "refusal", "approvalId": resource_id, "status": expected, "planId": ap["subject_id"],
                "proof": self.domain.approval_proof(resource_id), "event": self._event("approval."+expected, "approval", resource_id)}

    def _verify_source(self, receipt):
        source, result = loads(receipt["source_json"]), loads(receipt["result_json"])
        action = receipt["fixed_action"]
        if action not in ACTIONS:
            raise APIReceiptIntegrityError("Unknown accounting receipt action")
        if source["kind"] != "refusal" and (receipt["outcome"] != "success" or receipt["http_status"] != 200):
            raise APIReceiptIntegrityError("Accounting receipt successful outcome metadata changed")
        if source["kind"] == "worker":
            invocation = self.invocations.get(source["invocationId"])
            if (invocation["canonical_person_id"] != receipt["canonical_person_id"] or invocation["repeatability_uuid"] != receipt["repeatability_uuid"]
                    or not _same_json(invocation["binding"], loads(receipt["binding_json"])) or not _same_json(invocation["observation"], source["observation"])
                    or not _same_json(invocation["result"], result) or invocation["state"] not in ("observed", "completed")):
                raise APIReceiptIntegrityError("Accounting receipt lost its original invocation observation")
            return
        expected = None
        if source["kind"] == "plan":
            plan = self.domain.plan(source["planId"])
            if (action != "accounting.prepare" or not _same_json(source["plan"], plan) or plan["bill_id"] != receipt["resource_id"]
                    or plan["prepared_by"] != receipt["actor_login"]):
                raise APIReceiptIntegrityError("Original prepared accounting plan changed")
            expected = {**_RESULT_LABELS, "planId": plan["id"], "billId": plan["bill_id"], "status": "prepared"}
        else:
            if not _same_json(self.domain.approval_proof(source["approvalId"]), source["proof"]):
                raise APIReceiptIntegrityError("Accounting receipt lost its original approval request")
            ap = self.cipher.approvals.get(source["approvalId"])
            if ap["subject_id"] != source["planId"]:
                raise APIReceiptIntegrityError("Accounting receipt subject changed")
            if source["kind"] == "request":
                if action != "accounting.request" or ap["requested_by"] != receipt["actor_login"] or receipt["resource_id"] != source["planId"]:
                    raise APIReceiptIntegrityError("Accounting request actor or resource changed")
                expected = {**_RESULT_LABELS, "approvalId": ap["id"], "planId": ap["subject_id"], "status": "pending"}
            elif source["kind"] == "queue":
                intent = self.domain.intent(source["intentId"])
                if (action != "accounting.queue" or receipt["resource_id"] != ap["id"] or intent["approval_id"] != source["approvalId"]
                        or intent["plan_id"] != source["planId"] or intent["queued_by"] != receipt["actor_login"]):
                    raise APIReceiptIntegrityError("Accounting queue no longer binds the original consumed grant")
                birth = self._event_row(source["birth"])
                if birth["action"] != "accounting.intent_queued" or birth["entity_id"] != intent["id"] or birth["actor"] != receipt["actor_login"]:
                    raise APIReceiptIntegrityError("Accounting queue original intent birth changed")
                command = self.cipher.db.one("SELECT * FROM idempotency WHERE op_id=?", (source["commandId"],))
                payload = {"approval_id": ap["id"], "operation": OP_QUEUE, "subject_id": ap["subject_id"], "person_id": receipt["canonical_person_id"]}
                command_result = {"intent_id": intent["id"], "logical_operation_id": intent["logical_operation_id"], "status": "queued", "mode": "practice", "synthetic": True}
                events = self.cipher.db.query("SELECT * FROM audit_log WHERE action='command.executed' AND entity_type='command' AND entity_id=?", (source["commandId"],))
                if (command is None or source["commandId"] != "exec:"+ap["id"] or command["payload_hash"] != hash_json(payload)
                        or command["result_json"] != canonical_json(command_result) or len(events) != 1
                        or events[0]["actor"] != receipt["actor_login"] or loads(events[0]["payload_json"]) != {"payload_hash": hash_json(payload)}):
                    raise APIReceiptIntegrityError("Accounting queue command lost its exact original actor, payload, result or audit")
                expected = {**_RESULT_LABELS, "intentId": intent["id"], "approvalId": ap["id"], "planId": ap["subject_id"], "status": "queued"}
            else:
                event = self._event_row(source["event"])
                wanted = "approval.granted" if source["kind"] == "grant" else "approval."+source["status"]
                if event["action"] != wanted or event["entity_id"] != source["approvalId"] or event["actor"] != receipt["actor_login"]:
                    raise APIReceiptIntegrityError("Accounting receipt original lifecycle event changed")
                if source["kind"] == "grant":
                    if action != "accounting.approve" or receipt["resource_id"] != ap["id"]:
                        raise APIReceiptIntegrityError("Accounting grant receipt action or resource changed")
                    expected = {**_RESULT_LABELS, "approvalId": ap["id"], "planId": ap["subject_id"], "status": "granted"}
                elif source["kind"] == "refusal":
                    status = 423 if source["status"] == "expired" else 412
                    expected = {"code": "approval_expired" if status == 423 else "approval_stale", "message": "The handoff authorization changed. Request fresh approval.", "target": ap["id"]}
                    if (action not in ("accounting.approve", "accounting.queue") or receipt["outcome"] != "refused"
                            or receipt["http_status"] != status or ap["status"] != source["status"] or receipt["resource_id"] != ap["id"]):
                        raise APIReceiptIntegrityError("Accounting terminal refusal receipt changed")
                else:
                    raise APIReceiptIntegrityError("Accounting receipt has no fixed original source kind")
        if not _same_json(expected, result):
            raise APIReceiptIntegrityError("Accounting receipt result differs from its exact original verified effect")

    @staticmethod
    def _pending(invocation):
        return {"invocationId": invocation["id"], "state": invocation["state"], "retrySameRequest": True, "replayed": False, "effectApplied": False}

    def _complete_worker(self, invocation, person):
        if invocation["state"] != "observed":
            return None
        before = self._api_phase_snapshot()
        source = {"kind": "worker", "invocationId": invocation["id"], "observation": invocation["observation"]}
        receipt = self.receipts.record(person_id=person, actor_login=invocation["actor_login"], repeatability_uuid=invocation["repeatability_uuid"],
            contract_version=CONTRACT_VERSION, action=invocation["fixed_action"], resource_id=invocation["resource_id"], binding=invocation["binding"],
            outcome="success", http_status=200, result=invocation["result"], source=source)
        self._verify_source(receipt)
        self.invocations.complete(invocation["id"], person_id=person, receipt_id=receipt["id"])
        self._api_phase_boundary(before, invocation, receipt_id=receipt["id"])
        return self._response(receipt, replayed=False)

    def _api_phase_snapshot(self):
        snapshot = APActionRunner._control_snapshot(self)
        snapshot["effectRows"] = {table: self.cipher.db.query(f"SELECT * FROM {table}") for table in (_TABLE, "ap_action_receipts")}
        return snapshot

    def _api_phase_boundary(self, before, invocation, *, receipt_id=None):
        after = self._api_phase_snapshot()
        allowed = {_TABLE} | ({"ap_action_receipts"} if receipt_id is not None else set())
        if (before["schema"] != after["schema"] or before["tables"].keys() != after["tables"].keys()
                or before["approvals"] != after["approvals"]):
            raise APIReceiptIntegrityError("Accounting API phase changed workspace schema or authorization")
        for table, original in before["tables"].items():
            if table not in allowed and original != after["tables"][table]:
                raise APIReceiptIntegrityError("Accounting API phase changed an unrelated source or financial record")
        self._row_effect(before, after, _TABLE, added={invocation["id"]} if receipt_id is None else (),
                         changed=None if receipt_id is None else {invocation["id"]: {"state", "revision", "body_json", "row_hash", "audit_seq"}})
        self._row_effect(before, after, "ap_action_receipts", added=() if receipt_id is None else {receipt_id})
        expected = [("ap.accounting_invocation_reserved" if receipt_id is None else "ap.accounting_invocation_changed", _ENTITY, invocation["id"])]
        if receipt_id is not None:
            expected.append(("ap.practice_action_recorded", "ap_action_receipt", receipt_id))
        actual = after["audit"][len(before["audit"]):]
        if (before["audit"] != after["audit"][:len(before["audit"])]
                or Counter((event["action"], event["entity_type"], event["entity_id"]) for event in actual) != Counter(expected)
                or any(event["actor"] != invocation["actor_login"] for event in actual)):
            raise APIReceiptIntegrityError("Accounting API phase introduced unexpected audit effects")

    def _worker_run(self, person_id, action, resource_id, body, key, binding, if_match):
        from .accounting_worker import invoke_bound_worker, WorkerHeld, WorkerLocalPersistenceError
        with self._transaction():
            context = self.preflight.authorize(person_id, action, resource_id)
            person = context["personId"]
            replay = self._replay(person, key, binding)
            if replay is not None:
                return replay
            invocation = self.invocations.find(person, key)
            if invocation is not None:
                if invocation["binding"] != binding:
                    raise APRefusal(409, "repeatability_conflict", "This key belongs to a different reviewed invocation.")
                completed = self._complete_worker(invocation, person)
                if completed is not None:
                    return completed
            else:
                before = self._api_phase_snapshot()
                checked = self.preflight.verify(person_id, action, resource_id, body, if_match)
                invocation = self.invocations.reserve(person_id=person, actor_login=context["login"], action=action, intent_id=resource_id,
                    repeatability_uuid=key, binding=binding, reviewed_source=checked["plan"])
                self._api_phase_boundary(before, invocation)
        # Reservation is now committed. The trusted worker commits its linked
        # attempt before it may cross the simulator boundary.
        method = {"accounting.deliver": "deliver_once", "accounting.lookup": "lookup_once", "accounting.reconcile": "reconcile_once"}[action]
        try:
            invoke_bound_worker(self.worker, domain=self.domain, method=method, intent_id=resource_id,
                                actor=context["login"], invocation_id=invocation["id"])
        except (WorkerHeld, WorkerLocalPersistenceError):
            pass
        # A completed domain observation remains truthful even if this separate
        # API receipt transaction fails. The same UUID resumes its completion.
        try:
            with self._transaction():
                current = self.preflight.authorize(person_id, action, resource_id)
                if current["personId"] != person:
                    raise APIReceiptIntegrityError("Accounting caller changed during observation")
                invocation = self.invocations.get(invocation["id"])
                replay = self._replay(person, key, binding)
                if replay is not None:
                    return replay
                completed = self._complete_worker(invocation, person)
                return completed if completed is not None else self._pending(invocation)
        except APRefusal:
            raise
        except Exception:
            with self.cipher.db._lock:
                self.preflight.authorize(person_id, action, resource_id)
                return self._pending(self.invocations.get(invocation["id"]))

    def status(self, person_id, invocation_id):
        with self.cipher.db._lock:
            minimal = self.cipher.db.one(f"SELECT canonical_person_id,fixed_action,resource_id FROM {_TABLE} WHERE id=?", (invocation_id,))
            if minimal is None:
                raise APRefusal(404, "invocation_not_found", "This accounting invocation is unavailable.")
            context = self.preflight.authorize(person_id, minimal["fixed_action"], minimal["resource_id"])
            if context["personId"] != minimal["canonical_person_id"]:
                raise APRefusal(404, "invocation_not_found", "This accounting invocation is unavailable.")
            invocation = self.invocations.get(invocation_id)
            if invocation["state"] != "completed":
                return self._pending(invocation)
            receipt = self.receipts.find(context["personId"], invocation["repeatability_uuid"])
            if receipt is None:
                raise APIReceiptIntegrityError("Completed accounting invocation lost its receipt")
            self._verify_source(receipt)
            return self._response(receipt, replayed=True)

    def integrity_checks(self):
        problems = []
        try:
            self.invocations.inventory()
            for receipt in self.cipher.db.query("SELECT * FROM ap_action_receipts WHERE fixed_action LIKE 'accounting.%'"):
                self.receipts.verify_integrity()
                self._verify_source(receipt)
        except Exception:
            problems.append({"code": "accounting_api_source_invalid", "ok": False, "message": "Accounting API reservation or original outcome proof cannot be verified."})
        return problems

    def close_checks(self, period_id):
        return self.integrity_checks()

    def audit_export(self):
        return {"integrity": self.integrity_checks(), "invocations": [{key: value for key, value in item.items() if key not in ("reviewed_source", "binding")}
                for item in self.invocations.inventory()]}
